"""P0.2 — readiness is not liveness.

``GET /health`` is a **liveness** probe: it answers "this process is alive, restart me
if I stop answering". A container orchestrator polls it on a short interval and *kills
the pod* when it fails. Checking Postgres/Neo4j/Redis inside it therefore has the exact
wrong effect — a Neo4j blip would take out every healthy API pod at once, turning a
degraded dependency into a full outage. So ``/health`` stays static (pinned in
``test_api.py``) and dependency health moves to a **new** endpoint.

The contract pinned here
------------------------
``GET /ready`` — **public, and detail-free.** Public because the thing that polls it is
an orchestrator or a load balancer with no credentials and no session cookie; gating it
would mean the probe could only ever report "401", which is not a health signal. Safe
because the body is a fixed vocabulary — a dependency name and one of two words — and
never a DSN, a host, a port, a username or an exception string. That is the trade: the
endpoint discloses *that* Neo4j is unreachable (which an attacker learns anyway by
watching the service fail), never *where* Neo4j is or what credential it wanted::

    200  {"status": "ok",       "checks": {"postgres": "ok",   "neo4j": "ok", ...}}
    503  {"status": "degraded", "checks": {"postgres": "down", "neo4j": "ok", ...}}

**The seam.** A readiness endpoint has to be unit-testable without Postgres, Neo4j and
Redis, so the probes are a FastAPI dependency (``src.api.readiness.get_probes``) that a
test overrides — the same pattern the dashboards already use for
``get_baseline_summary_path``. A probe is ``async () -> None``: it returns on success
and **raises** on failure. ``test_the_real_probe_set_covers_postgres_neo4j_and_redis``
is what stops the overridden tests below from drifting away from the real set.

**Every probe is bounded (2 seconds).** "Down" and "hanging" are different failures and
only one of them is easy: a refused connection raises immediately, while a Neo4j whose
host has vanished leaves the driver waiting on a socket. An unbounded probe converts
readiness into a hang, the orchestrator's own probe timeout becomes the only thing
holding the system together, and the endpoint that was supposed to explain the outage
stops answering during it. Same defect class as the Phase 5.9 embed timeout. So the
budget is pinned as a constant *and* as behaviour — a probe that never returns must
still produce a 503 that names it.

``get_probes`` is imported inside each test rather than at module scope on purpose: it
does not exist yet, and a module-level import would collapse this whole file into one
collection error instead of one legible failure per pinned behaviour.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from src.api.main import app
from tests.unit.auth_fakes import cas_on

Probe = Callable[[], Awaitable[None]]

#: Every dependency the API cannot serve a request without.
DEPENDENCIES = ("postgres", "neo4j", "redis")


#: The per-probe budget. Long enough for a healthy round-trip on a loaded box, short
#: enough that three of them cannot outlast an orchestrator's own probe timeout.
PROBE_TIMEOUT_SECONDS = 2.0

#: How long a hanging probe pretends to hang for. Comfortably longer than the budget,
#: and short enough that the RED run (where no timeout exists yet) costs seconds rather
#: than tripping pytest's own 120s per-test timeout and taking the suite with it.
HANG_SECONDS = 20.0


def probes_dependency() -> Any:
    """The readiness-probe dependency. RED until P0.2 adds ``src.api.readiness``."""
    from src.api.readiness import get_probes

    return get_probes


def up() -> Probe:
    async def _probe() -> None:
        return None

    return _probe


def down(exc: Exception | None = None) -> Probe:
    async def _probe() -> None:
        raise exc or RuntimeError("unreachable")

    return _probe


def hangs() -> Probe:
    """A dependency that neither answers nor refuses — the hard case."""

    async def _probe() -> None:
        await asyncio.sleep(HANG_SECONDS)

    return _probe


@pytest.fixture(autouse=True)
def _clear_overrides() -> Iterator[None]:
    yield
    app.dependency_overrides.clear()


def client_with(probes: dict[str, Probe]) -> TestClient:
    app.dependency_overrides[probes_dependency()] = lambda: probes
    return TestClient(app, raise_server_exceptions=False)


# ── Healthy ──────────────────────────────────────────────────────────────────────────


def test_ready_returns_200_when_every_dependency_is_up() -> None:
    client = client_with({name: up() for name in DEPENDENCIES})

    resp = client.get("/ready")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["checks"] == {name: "ok" for name in DEPENDENCIES}


# ── Degraded ─────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("broken", DEPENDENCIES)
def test_ready_is_non_2xx_and_names_the_unhealthy_dependency(broken: str) -> None:
    """A readiness probe that answers 200 while Postgres is gone is worse than no probe:
    the load balancer keeps routing traffic to a pod that can only 500. And an operator
    needs to know *which* dependency, or the endpoint has told them nothing they could
    not see from the request failing."""
    client = client_with(
        {name: (down() if name == broken else up()) for name in DEPENDENCIES}
    )

    resp = client.get("/ready")

    assert resp.status_code == 503, (
        f"/ready answered {resp.status_code} with {broken} down; a degraded service "
        "must not report itself ready (503 Service Unavailable)."
    )
    body = resp.json()
    assert body["checks"][broken] == "down"
    assert body["status"] != "ok"
    for name in DEPENDENCIES:
        if name != broken:
            assert body["checks"][name] == "ok", (
                f"{name} was healthy but /ready reported {body['checks'][name]!r} — a "
                "probe that condemns everything on one failure cannot be acted on."
            )


def test_ready_reports_every_unhealthy_dependency_not_only_the_first() -> None:
    """Same reason as the startup check: one restart per fault is not a diagnosis."""
    client = client_with({name: down() for name in DEPENDENCIES})

    resp = client.get("/ready")

    assert resp.status_code == 503
    assert resp.json()["checks"] == {name: "down" for name in DEPENDENCIES}


# ── Bounded ──────────────────────────────────────────────────────────────────────────


def test_a_hanging_dependency_is_reported_down_and_does_not_hang_readiness() -> None:
    """The failure mode that matters more than a refused connection.

    A refused socket raises at once and any implementation gets this right. A host that
    has silently gone away leaves the driver waiting, and an unbounded probe turns the
    readiness endpoint itself into a casualty of the outage it exists to report — right
    when an operator is polling it to find out what broke.
    """
    client = client_with({"postgres": up(), "neo4j": hangs(), "redis": up()})

    started = time.monotonic()
    resp = client.get("/ready")
    elapsed = time.monotonic() - started

    assert elapsed < HANG_SECONDS / 2, (
        f"/ready took {elapsed:.1f}s to answer while one dependency hung — it waited "
        f"for the driver instead of bounding the probe at {PROBE_TIMEOUT_SECONDS}s. "
        "Wrap each probe in asyncio.wait_for; a timeout is a 'down', not a stall."
    )
    assert resp.status_code == 503
    assert resp.json()["checks"]["neo4j"] == "down"


def test_the_whole_probe_set_is_bounded_not_just_one_probe() -> None:
    """Three probes at 2s each is 6s worst case even if they run one after another. What
    must never happen is a per-probe budget that composes into an unbounded total."""
    client = client_with({name: hangs() for name in DEPENDENCIES})

    started = time.monotonic()
    resp = client.get("/ready")
    elapsed = time.monotonic() - started

    budget = PROBE_TIMEOUT_SECONDS * len(DEPENDENCIES) + 3.0
    assert elapsed < budget, (
        f"/ready took {elapsed:.1f}s with every dependency hanging; the bound is "
        f"{PROBE_TIMEOUT_SECONDS}s per probe ({budget:.0f}s allowed here)."
    )
    assert resp.status_code == 503
    assert resp.json()["checks"] == {name: "down" for name in DEPENDENCIES}


def test_the_probe_timeout_is_two_seconds() -> None:
    """Pinned as a named constant, not a magic number buried in a ``wait_for`` call —
    it is an ops parameter someone will want to find and reason about."""
    from src.api import readiness

    assert readiness.PROBE_TIMEOUT_SECONDS == PROBE_TIMEOUT_SECONDS


# ── Disclosure ───────────────────────────────────────────────────────────────────────


def test_ready_never_leaks_a_credential_dsn_or_host() -> None:
    """The endpoint is public, so its body is a public document. A driver's exception
    text is the single most likely place a DSN escapes — ``asyncpg`` and ``neo4j`` both
    put the connection target, and sometimes the user, into the message. The endpoint
    must classify the failure, never echo it."""
    leaky = RuntimeError(
        "could not connect to postgresql+asyncpg://app:app@postgres:5432/harness: "
        "password authentication failed for user 'app' SENTINEL-DO-NOT-ECHO"
    )
    client = client_with(
        {"postgres": down(leaky), "neo4j": up(), "redis": up()},
    )

    resp = client.get("/ready")

    body = resp.text
    for secret in (
        "SENTINEL-DO-NOT-ECHO",
        "app:app@",
        "postgresql+asyncpg",
        "postgres:5432",
        "password authentication",
    ):
        assert secret not in body, (
            f"/ready echoed {secret!r} to an unauthenticated caller. Report "
            '{"postgres": "down"} and log the exception; do not serve it.'
        )


def test_ready_is_reachable_without_credentials() -> None:
    """With CAS on and no session cookie — the orchestrator's view. It has no account,
    and a probe it cannot poll is a probe that reports the service permanently down."""
    client = client_with({name: up() for name in DEPENDENCIES})
    cas_on()

    resp = client.get("/ready")

    assert resp.status_code not in (401, 403)


# ── The override cannot drift from the real thing ────────────────────────────────────


async def test_the_real_probe_set_covers_postgres_neo4j_and_redis() -> None:
    """Every test above overrides the probes; this one asserts what is being overridden.

    Without it, the whole file would keep passing if the real endpoint checked nothing
    at all — or quietly stopped checking Redis.
    """
    from types import SimpleNamespace

    get_probes = probes_dependency()
    request = SimpleNamespace(app=app)

    probes = get_probes(request)
    if isinstance(probes, Awaitable):
        probes = await probes

    assert set(probes) == set(DEPENDENCIES)


# ── What each real probe actually does (added by the P0.2 correctness review) ────────
#
# Every test above overrides the probes, and the key-set test above asserts only their
# NAMES. So the whole file stayed green while the probe BODIES were untested: a probe
# reading `app.state.engien`, or calling a method the driver does not have, would report
# a perfectly healthy dependency `down` forever in production with nothing red here.
# These run the real probes against a strict stand-in for `app.state` that fails the
# test on any attribute the probe was not supposed to touch — so the seam between
# `readiness.py` and what the lifespan actually puts on `app.state` is pinned.


class StrictState:
    """An ``app.state`` that raises on any attribute the probe should not have read."""

    def __init__(self, **attrs: Any) -> None:
        self.__dict__["_attrs"] = attrs

    def __getattr__(self, item: str) -> Any:
        try:
            return self.__dict__["_attrs"][item]
        except KeyError:
            raise AssertionError(
                f"a readiness probe read app.state.{item}, which the API lifespan does "
                f"not set (it sets {sorted(self.__dict__['_attrs'])}). A typo here "
                "reports a healthy dependency as down, forever, in production."
            ) from None


class FakeConnection:
    def __init__(self) -> None:
        self.executed: list[str] = []

    async def execute(self, clause: object) -> None:
        self.executed.append(str(clause))


class FakeEngine:
    """Mimics ``AsyncEngine.connect()`` — an async context manager, not a coroutine."""

    def __init__(self, connection: FakeConnection, fails: Exception | None = None):
        self.connection = connection
        self.fails = fails

    def connect(self) -> FakeEngine:
        return self

    async def __aenter__(self) -> FakeConnection:
        if self.fails is not None:
            raise self.fails
        return self.connection

    async def __aexit__(self, *exc: object) -> None:
        return None


class FakeMemory:
    def __init__(self) -> None:
        self.verified = 0

    async def verify_connectivity(self) -> None:
        self.verified += 1


class FakeArq:
    def __init__(self) -> None:
        self.pinged = 0

    async def ping(self) -> None:
        self.pinged += 1


def real_probes(**state: Any) -> dict[str, Probe]:
    """The REAL probe set, aimed at a strict ``app.state``."""
    from types import SimpleNamespace

    get_probes = probes_dependency()
    request = SimpleNamespace(app=SimpleNamespace(state=StrictState(**state)))
    return dict(get_probes(request))


async def test_the_real_postgres_probe_queries_the_lifespans_engine() -> None:
    connection = FakeConnection()

    await real_probes(engine=FakeEngine(connection))["postgres"]()

    assert connection.executed, (
        "the postgres probe opened a connection but never ran a statement — an "
        "unused connection proves the pool exists, not that the database answers."
    )
    assert "select 1" in connection.executed[0].lower()


async def test_the_real_neo4j_probe_verifies_through_graph_memory() -> None:
    memory = FakeMemory()

    await real_probes(memory=memory)["neo4j"]()

    assert memory.verified == 1


async def test_the_real_redis_probe_pings_the_arq_pool() -> None:
    arq = FakeArq()

    await real_probes(arq=arq)["redis"]()

    assert arq.pinged == 1


async def test_a_real_probe_raises_when_its_dependency_is_unreachable() -> None:
    """The probe contract is "raise on failure" — if a driver error were swallowed here,
    `/ready` would report `ok` while Postgres was gone, which is worse than no probe."""
    engine = FakeEngine(FakeConnection(), fails=RuntimeError("connection refused"))

    with pytest.raises(RuntimeError):
        await real_probes(engine=engine)["postgres"]()


async def test_graph_memory_verify_connectivity_round_trips_the_neo4j_driver() -> None:
    """`FakeMemory` above is only as good as its resemblance to the real class: the
    lifespan puts a ``GraphMemory`` on ``app.state.memory``, so the method the probe
    calls must exist there AND must actually ask the driver — a stub that returned
    ``None`` would make ``/ready`` report Neo4j healthy while it was gone."""
    from src.memory.graph import GraphMemory

    class FakeDriver:
        def __init__(self) -> None:
            self.verified = 0

        async def verify_connectivity(self) -> None:
            self.verified += 1

    driver = FakeDriver()
    memory = GraphMemory(driver=driver)  # type: ignore[arg-type]

    await memory.verify_connectivity()

    assert driver.verified == 1


async def test_a_hanging_probe_is_logged_with_the_reason_it_failed(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """``asyncio.TimeoutError`` stringifies to the EMPTY STRING, so logging the
    exception alone produces "readiness probe 'neo4j' failed:" and nothing at all — in
    the one case where "it hung" versus "it refused" is the whole diagnosis. The body
    stays detail-free; the log must not."""
    from src.api import readiness

    caplog.set_level("WARNING")
    with caplog.at_level("WARNING"):
        assert await readiness._probe_succeeded("neo4j", hangs()) is False

    assert "TimeoutError" in caplog.text, (
        f"the timeout was logged as {caplog.text!r} — an operator reading the "
        "container log cannot tell a hang from a refusal. Log type(exc).__name__."
    )

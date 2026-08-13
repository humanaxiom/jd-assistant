"""P0.2 — a guard nobody can turn on is not a guard.

The production startup check (``src.settings``, ``tests/unit/test_production_posture``)
shipped **inert**, and every one of its own tests was green while it was.
``ENVIRONMENT`` appeared in ``.env.example`` and in *no* compose service; pydantic's
``env_file=".env"`` resolves against ``/app`` (= ``./core``) while the operator's
``.env`` lives at the repo root and is never mounted. So an operator following
``.env.example``'s first line, setting
``ENVIRONMENT=production`` and deploying, got ``environment='development'`` in the
container, the guard never ran, CAS stayed off and every anonymous request was a
transient admin — verbatim the failure the guard exists to prevent.

The other half of the same defect: ``DATABASE_URL`` and ``NEO4J_PASSWORD`` were compose
**literals**, not ``${VAR:-default}``. Even once ``ENVIRONMENT`` arrived, those two
conditions could never be cleared from outside the file, so every service would have
refused to start forever. A setting the check demands but the deployment cannot deliver
is not a safety control; it is a brick.

**So this file asserts the join between the two artifacts**: every setting a refusal
message can name must be *deliverable* through ``docker-compose.yml`` — present in the
shared ``&app_env`` anchor, interpolated rather than pinned, and inherited by every
service that constructs ``Settings``. It parses the compose file as data; it needs no
Docker and no running stack. Without it we stay one edit away from an inert guard.

The required set is **derived from an actual refusal**, not hand-listed: a condition
added to the check tomorrow automatically demands a compose key here, and cannot be
merged while it is undeliverable.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from src.settings import Settings
from tests.unit.test_production_posture import SAFE_PRODUCTION, VIOLATIONS

#: Where the compose file is, in each place this suite can run. The `gates` container
#: binds ONLY ``./core`` (at ``/app``), so the compose file is bind-mounted to
#: ``/docker-compose.yml`` for this test; outside a container it is at the repo root.
_CANDIDATE_PATHS = (
    Path("/docker-compose.yml"),
    Path(__file__).resolve().parents[3] / "docker-compose.yml",
)

#: Services built from our image that deliberately do NOT carry the settings env,
#: because they never construct ``Settings``: both are pure filesystem passes over
#: committed artifacts. Asserted to *stay* that way in
#: :func:`test_the_exempt_services_really_do_not_take_the_settings_environment` — an
#: exemption nobody re-checks is how a service quietly slips out of the guard.
SETTINGS_FREE_SERVICES = frozenset({"baseline", "dedup"})

#: The ONE service allowed to pin settings to compose literals, and exactly which ones.
#:
#: `gates` must be hermetic: the gate suite tests the production check, it does not run
#: under it, and it must not inherit the operator's shell. Everywhere else a literal is
#: the M1 defect — and the override idiom (`<<: *app_env` plus a pin) is already in the
#: file for anyone to copy onto `worker`, which opens the same Postgres and Neo4j and
#: serves no HTTP, so nothing would surface it booting `development` on committed
#: credentials. Named here rather than allowed generically, and asserted EXACTLY in
#: :func:`test_the_gates_service_pins_nothing_beyond_its_declared_exemptions`, so a new
#: pin has to be argued into this list.
GATES_HERMETIC_PINS = frozenset(
    {
        # Auth posture: the suite runs CAS-off, in development, with no real admins.
        "ENVIRONMENT",
        "CAS_ENABLED",
        "CAS_DEV_FAKE_USER",
        "BOOTSTRAP_ADMINS",
        # The CAS return origin and its allowlist (P0.3), pinned for the same reason and
        # added because the gap BIT: a test asserting "an unlisted origin falls back to
        # the static setting" failed on a dev box and would have passed in CI, because
        # the repo-root .env points CAS_SERVICE_BASE_URL at a live demo forward and this
        # service passed it through. Any test that reads the fallback was reading the
        # developer's machine.
        "CAS_SERVICE_BASE_URL",
        "ALLOWED_SERVICE_ORIGINS",
        # Data stores: pinned to the dev stack so no gate run can reach an ambient
        # production DSN (`alembic/env.py` falls back to `settings.database_url`).
        "DATABASE_URL",
        "NEO4J_URI",
        "NEO4J_USER",
        "NEO4J_PASSWORD",
        "REDIS_URL",
    }
)

#: The settings a refusal names today. The derived set (below) must COVER this — so a
#: condition cannot be silently dropped — and may exceed it, which is the point.
KNOWN_REFUSABLE_SETTINGS = frozenset(
    {
        "environment",
        "cas_enabled",
        "cas_dev_fake_user",
        "cas_verify_tls",
        "cas_service_base_url",
        "allowed_service_origins",
        "cas_service_from_request",
        "session_cookie_secure",
        "database_url",
        "neo4j_password",
        "ollama_base_url",
        "cas_anonymous_user",
    }
)


def _compose() -> dict[str, Any]:
    """The parsed compose file. Raises — never skips — if it cannot be found.

    A skip here would restore exactly the silence this file exists to break.
    """
    for path in _CANDIDATE_PATHS:
        if path.is_file():
            loaded: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8"))
            return loaded
    raise FileNotFoundError(
        "docker-compose.yml was not found at any of "
        f"{[str(p) for p in _CANDIDATE_PATHS]}. "
        "Inside the `gates` container it is bind-mounted read-only at "
        "/docker-compose.yml; if that mount was removed from the `gates` service, put "
        "it back rather than skipping this test."
    )


def _services() -> dict[str, dict[str, Any]]:
    services: dict[str, dict[str, Any]] = _compose()["services"]
    return services


def _env(service: str) -> dict[str, Any]:
    """A service's environment with the ``<<: *app_env`` merge applied (PyYAML resolves
    merge keys, and an explicit key in the service wins over the anchor — which is what
    lets `gates` pin ``ENVIRONMENT``)."""
    env: dict[str, Any] = _services()[service].get("environment") or {}
    return env


def _built_from_our_image() -> list[str]:
    return sorted(
        name
        for name, service in _services().items()
        if (service.get("build") or {}).get("context") == "./core"
    )


def _refusal_naming_everything() -> str:
    """One refusal message with every condition the check knows about unmet."""
    posture: dict[str, Any] = dict(SAFE_PRODUCTION)
    for override, _ in VIOLATIONS.values():
        posture.update(override)
    # The two conditions that are not in the tester's VIOLATIONS table, both of which
    # are checked in EVERY mode rather than only in production: the retired
    # header-derived origin flag (P0.2's ninth condition, retired by P0.3) and the blank
    # synthetic actor.
    posture["cas_service_from_request"] = True
    posture["cas_anonymous_user"] = ""

    with pytest.raises(Exception) as excinfo:  # noqa: B017 - type is not the contract
        Settings(**posture)
    return str(excinfo.value)


def refusable_settings() -> set[str]:
    """Every ``Settings`` field a refusal message names — the deliverability contract.

    Derived rather than listed, and that is the load-bearing part: a condition added to
    the check tomorrow lands in this set the moment its message names the setting, and
    the parametrized tests below immediately demand a compose key for it.
    """
    message = _refusal_naming_everything()
    return {field for field in Settings.model_fields if field in message}


#: Computed once, at collection, so each setting is its own test case.
REFUSABLE: list[str] = sorted(refusable_settings())


def _env_key(field: str) -> str:
    return field.upper()


def test_the_derived_set_still_covers_every_condition_we_know_about() -> None:
    """Guards the derivation itself. If a condition were deleted from the check, the
    derived set would shrink and every deliverability assertion below would pass
    vacuously — the same class of false green that let the guard ship inert."""
    missing = KNOWN_REFUSABLE_SETTINGS - refusable_settings()

    assert not missing, (
        f"the production check no longer names {sorted(missing)} in any refusal. If a "
        "condition was deliberately removed, remove it from KNOWN_REFUSABLE_SETTINGS "
        "in the same commit and say why; do not let the contract shrink silently."
    )


@pytest.mark.parametrize("field", REFUSABLE)
def test_every_setting_a_refusal_names_is_present_in_the_shared_env(field: str) -> None:
    """One case per setting, so a red run names the missing key.

    ``api`` carries the ``&app_env`` anchor itself, so it is the reference service.
    """
    key = _env_key(field)

    assert key in _env("api"), (
        f"the production check can refuse to start over {field!r}, but {key} is not in "
        "docker-compose.yml's `&app_env` anchor — so no operator can set it and the "
        "condition is unsatisfiable. Add `"
        f"{key}: ${{{key}:-<dev default>}}` to the anchor."
    )


def _settings_bearing_services() -> list[str]:
    """Every service that builds our image and constructs ``Settings``."""
    return [n for n in _built_from_our_image() if n not in SETTINGS_FREE_SERVICES]


@pytest.mark.parametrize("field", REFUSABLE)
def test_no_setting_a_refusal_names_is_pinned_to_a_compose_literal(field: str) -> None:
    """Present is not the same as deliverable — checked on **every** service.

    ``DATABASE_URL: postgresql+asyncpg://app:app@postgres:5432/harness`` was *present*
    and impossible to override, which meant "use a real database password" could never
    be satisfied. Every one of these must be `${VAR:-default}`.

    **Per-service, not just on the anchor.** A service may keep ``<<: *app_env`` and
    still pin a key back to a literal in its own block — `gates` legitimately does, so
    the idiom is already in the file to copy. Do it on `worker` and the M1 defect is
    back in its worst form: the operator sets ``ENVIRONMENT=production``, `api` refuses
    and gets fixed, and the arq worker — same Postgres, same Neo4j, no HTTP surface to
    notice it — keeps running in `development` on committed credentials with the guard
    inert. Checking only the anchor let that mutation pass 44/44 green.
    """
    key = _env_key(field)
    pinned = {
        name: str(_env(name)[key])
        for name in _settings_bearing_services()
        if key in _env(name)
        and not str(_env(name)[key]).startswith("${")
        and not (name == "gates" and key in GATES_HERMETIC_PINS)
    }

    assert not pinned, (
        f"{key} is pinned to a compose literal in {sorted(pinned)} ({pinned}), so the "
        "operator's repo-root .env cannot change it there and a production refusal "
        f"over {field!r} could never be cleared for that service. Write it as "
        f"`${{{key}:-<dev default>}}`. (Only `gates` may pin, only the keys in "
        "GATES_HERMETIC_PINS, and only for hermeticity.)"
    )


@pytest.mark.parametrize("field", REFUSABLE)
def test_every_service_that_constructs_settings_receives_it(field: str) -> None:
    """The API is not the only reader — eight pipeline services and the arq worker
    construct ``Settings`` too, and a per-service env that skipped a key would leave
    that service unable to satisfy the check (or, worse, running unguarded)."""
    key = _env_key(field)
    without = [
        name
        for name in _built_from_our_image()
        if name not in SETTINGS_FREE_SERVICES and key not in _env(name)
    ]

    assert not without, (
        f"{without} build from ./core and construct Settings, but do not receive "
        f"{key}. "
        "Give them the shared `<<: *app_env` anchor (or, if one genuinely never loads "
        "Settings, add it to SETTINGS_FREE_SERVICES with a reason)."
    )


def test_the_exempt_services_really_do_not_take_the_settings_environment() -> None:
    """Keeps the exemption honest in the other direction: if `baseline` or `dedup` ever
    gains the app env (i.e. starts loading Settings), the exemption is stale and must
    be removed rather than continuing to excuse a real service."""
    for name in sorted(SETTINGS_FREE_SERVICES):
        assert "DATABASE_URL" not in _env(name), (
            f"{name} now carries the shared settings environment, so it is no longer "
            "the filesystem-only pass SETTINGS_FREE_SERVICES claims. Drop it from that "
            "set so it is covered like every other service."
        )


def test_the_gates_service_is_pinned_to_development() -> None:
    """CI must never drift into production mode.

    ``ENVIRONMENT`` is interpolated from the host environment everywhere else; a runner
    (or a developer) with ``ENVIRONMENT=production`` exported would otherwise make the
    entire suite fail at ``Settings()``. A literal is correct here and nowhere else —
    beside the existing hermetic ``CAS_ENABLED``/``CAS_DEV_FAKE_USER`` pins.
    """
    gates = _env("gates")

    assert gates.get("ENVIRONMENT") == "development", (
        'the `gates` service must pin ENVIRONMENT: "development" literally, next to '
        "its CAS pins — the gate suite tests the production check, it does not run "
        f"under it. Found {gates.get('ENVIRONMENT')!r}."
    )
    assert str(gates.get("CAS_ENABLED")).lower() == "false"


def test_the_gate_suite_cannot_reach_an_ambient_production_data_store() -> None:
    """`gates` must talk to the dev stack and nothing else.

    The store URLs were anchor literals until the P0.2 fix made them `${VAR:-…}` so a
    production deployment could supply real credentials — which also made the gate
    suite inherit whatever DSN the operator's shell or repo-root `.env` carries.
    ``alembic/env.py`` falls back to ``get_settings().database_url``. Integration tests
    use testcontainers and do not connect to these today; this makes that a guarantee
    instead of a happy accident.
    """
    gates = _env("gates")

    assert gates["DATABASE_URL"] == "postgresql+asyncpg://app:app@postgres:5432/harness"
    assert gates["NEO4J_URI"] == "bolt://neo4j:7687"
    assert gates["NEO4J_PASSWORD"] == "harnesspass"
    assert gates["REDIS_URL"] == "redis://redis:6379/0"
    for key in ("DATABASE_URL", "NEO4J_URI", "NEO4J_PASSWORD", "REDIS_URL"):
        assert not str(gates[key]).startswith("${"), (
            f"`gates` inherits {key} from the anchor, so a gate run picks up whatever "
            "the operator's environment says — including a production store. Pin it in "
            "the gates block."
        )


def test_the_gates_service_pins_nothing_beyond_its_declared_exemptions() -> None:
    """`gates` is the single exception to the interpolation rule, so what it pins is
    itself a reviewed list. An override added here without a line in
    GATES_HERMETIC_PINS would quietly widen the one hole in the M1 pin."""
    anchor = _env("api")
    overrides = {
        key
        for key, value in _env("gates").items()
        if key in anchor and value != anchor[key]
    }

    assert overrides == set(GATES_HERMETIC_PINS), (
        "the `gates` service's pins have drifted from the reviewed exemption list.\n"
        f"  pinned but not declared: {sorted(overrides - GATES_HERMETIC_PINS)}\n"
        f"  declared but not pinned: {sorted(GATES_HERMETIC_PINS - overrides)}\n"
        "Every literal in the gates block must be justified by hermeticity and listed "
        "in GATES_HERMETIC_PINS."
    )


def test_the_committed_dev_defaults_are_still_the_compose_defaults() -> None:
    """The interpolation must not have silently changed what `make up` gives a
    developer: the dev stack keeps working precisely because each `${VAR:-default}`
    carries the same value the literal did."""
    env = _env("api")

    assert "postgresql+asyncpg://app:app@postgres:5432/harness" in env["DATABASE_URL"]
    assert "harnesspass" in env["NEO4J_PASSWORD"]
    assert "bolt://neo4j:7687" in env["NEO4J_URI"]
    assert "redis://redis:6379/0" in env["REDIS_URL"]
    assert "development" in env["ENVIRONMENT"]


def test_the_allowlist_default_is_not_empty() -> None:
    """``ALLOWED_INFERENCE_HOSTS: ${ALLOWED_INFERENCE_HOSTS:-}`` would deliver an EMPTY
    allowlist to every service, which refuses the internal Ollama host itself (NN #5
    fails closed) and breaks `make embed`. The default must name the internal
    hosts."""
    value = str(_env("api")["ALLOWED_INFERENCE_HOSTS"])

    assert value.startswith("${ALLOWED_INFERENCE_HOSTS:-")
    assert "aria-gb10-2" in value, (
        "the compose default for ALLOWED_INFERENCE_HOSTS must repeat "
        "settings.allowed_inference_hosts, not be empty — an empty allowlist refuses "
        "the very host ADR-003 puts inference on."
    )


# ── The data stores are not published to the network (P0.3) ────────────────────────


#: Services holding data, and what an unauthenticated caller who reaches the port gets.
#: Named individually so a new data service has to be classified rather than inherited.
DATA_SERVICES: dict[str, str] = {
    "postgres": "the whole relational ledger, behind the committed app/app credential",
    "neo4j": "every JD vector and the graph, behind the committed neo4j/harnesspass",
    "redis": "the arq queue, with no password at all",
}

#: The one service that is *meant* to face a network: the app. Whether the host it runs
#: on should expose it, and over what, is the open question in P0.3 part 2 — but it is a
#: question about the deployment, not about this file.
NETWORK_FACING_SERVICES = frozenset({"api"})


def _published(service: str) -> list[str]:
    return [str(spec) for spec in _services()[service].get("ports") or []]


@pytest.mark.parametrize("service", sorted(DATA_SERVICES), ids=lambda s: s)
def test_a_data_store_is_published_only_to_loopback(service: str) -> None:
    """``ports: ["25432:5432"]`` publishes on **0.0.0.0**, and Docker writes that rule
    straight into the host's forward chain — so it is reachable from anywhere that can
    route to the box **whether or not the host firewall says so**. "Nobody can reach it"
    was an assumption about the network, not a property of the deployment, and P0.3 part
    2 is the discovery that the assumption had stopped holding: the host is now
    reachable at a public DNS name.

    Every one of these answers with a credential that is committed to this repo, so the
    exposure is not "an attacker must guess a password"; it is published in git.
    """
    exposures = [
        spec for spec in _published(service) if not spec.startswith("127.0.0.1")
    ]

    assert not exposures, (
        f"{service} publishes {exposures} on all interfaces, and it holds "
        f"{DATA_SERVICES[service]}. Bind it to loopback — `127.0.0.1:${{PORT}}:…` — "
        "which costs a local developer nothing and makes remote access a deliberate "
        "edit rather than the default."
    )


def test_the_data_stores_are_still_reachable_from_the_dev_box() -> None:
    """The other direction: loopback must not mean *unpublished*. `psql`, the Neo4j
    browser and `redis-cli` on the dev box are how anyone inspects a pipeline run, and
    silently taking them away would be a worse fix than the exposure."""
    for service in DATA_SERVICES:
        assert _published(service), f"{service} publishes no host port at all"


def test_every_service_publishing_a_port_is_classified() -> None:
    """Enumerated from the compose file, not from a list someone remembers to update: a
    new service that publishes a port is either a data store (loopback) or deliberately
    network-facing, and it must be said which."""
    publishing = {name for name in _services() if _services()[name].get("ports")}

    unclassified = publishing - set(DATA_SERVICES) - NETWORK_FACING_SERVICES
    assert not unclassified, (
        f"these services publish host ports and are classified as neither a data store "
        f"nor network-facing: {sorted(unclassified)}. Decide which, and say so here."
    )

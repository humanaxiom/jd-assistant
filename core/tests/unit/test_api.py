"""Unit tests for the FastAPI app — routes, task creation, error paths.

The production lifespan connects to real Postgres/Neo4j/Redis. We never trigger
it (TestClient is used without its context manager, so startup/shutdown are
skipped) and instead inject mocks into ``app.state`` plus a dependency override
for the DB session.

The tests above the P0.1a section run in the default dev posture (``cas_enabled=False``
=> a transient admin, see ``src.api.deps``), so they still describe an *authorized*
caller. The P0.1a section turns CAS on and pins what an unauthenticated one gets.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterator
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from src.api.main import app, get_session
from src.models.db import Task, TaskStatus
from tests.unit.auth_fakes import cas_on


class FakeSession:
    """Minimal async-session stand-in; ``flush`` assigns PKs like the DB does."""

    def __init__(self, get_result: Task | None = None) -> None:
        self.added: list[Task] = []
        self.committed = False
        self._get_result = get_result

    def add(self, obj: Task) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        for obj in self.added:
            if obj.id is None:
                obj.id = uuid.uuid4()

    async def commit(self) -> None:
        self.committed = True

    async def get(self, model: type[Task], pk: uuid.UUID) -> Task | None:
        return self._get_result


@pytest.fixture
def arq_mock() -> MagicMock:
    m = MagicMock()
    m.enqueue_job = AsyncMock(return_value=MagicMock(job_id="job-123"))
    return m


@pytest.fixture
def memory_mock() -> AsyncMock:
    m = AsyncMock()
    m.task_lineage = AsyncMock(return_value=[{"subtask": "S-1", "agent": "coder"}])
    m.similar_artifacts = AsyncMock(
        return_value=[{"kind": "code", "score": 0.9, "content": "x"}]
    )
    return m


@pytest.fixture(autouse=True)
def _clear_overrides() -> Iterator[None]:
    yield
    app.dependency_overrides.clear()


def make_client(
    *, session: FakeSession, arq: MagicMock, memory: AsyncMock
) -> TestClient:
    async def override_session() -> AsyncIterator[FakeSession]:
        yield session

    app.dependency_overrides[get_session] = override_session
    app.state.arq = arq
    app.state.memory = memory
    return TestClient(app)


def test_health() -> None:
    client = make_client(session=FakeSession(), arq=MagicMock(), memory=AsyncMock())
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_create_task_enqueues_and_returns_branch(
    arq_mock: MagicMock, memory_mock: AsyncMock
) -> None:
    session = FakeSession()
    client = make_client(session=session, arq=arq_mock, memory=memory_mock)

    resp = client.post(
        "/tasks", json={"title": "Add rate limiter", "spec": "throttle the api"}
    )

    assert resp.status_code == 201
    body = resp.json()
    assert body["title"] == "Add rate limiter"
    assert body["status"] == TaskStatus.PENDING.value
    assert body["branch"].startswith("agent/")
    assert body["branch"].endswith("-add-rate-limiter")
    uuid.UUID(body["id"])  # valid UUID assigned by flush
    assert session.committed is True
    arq_mock.enqueue_job.assert_awaited_once()
    call = arq_mock.enqueue_job.await_args
    assert call.args[0] == "run_pipeline"
    assert call.kwargs["branch"] == body["branch"]


def test_create_task_validates_spec_length(
    arq_mock: MagicMock, memory_mock: AsyncMock
) -> None:
    client = make_client(session=FakeSession(), arq=arq_mock, memory=memory_mock)
    resp = client.post("/tasks", json={"title": "Valid title", "spec": "short"})
    assert resp.status_code == 422
    arq_mock.enqueue_job.assert_not_awaited()


def test_get_task_found(arq_mock: MagicMock, memory_mock: AsyncMock) -> None:
    task = Task(title="Existing", spec="an existing spec", status=TaskStatus.DONE)
    task.id = uuid.uuid4()
    task.branch = "agent/abc12345-existing"
    client = make_client(
        session=FakeSession(get_result=task), arq=arq_mock, memory=memory_mock
    )

    resp = client.get(f"/tasks/{task.id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == str(task.id)
    assert body["status"] == TaskStatus.DONE.value
    assert body["branch"] == "agent/abc12345-existing"


def test_get_task_not_found(arq_mock: MagicMock, memory_mock: AsyncMock) -> None:
    client = make_client(
        session=FakeSession(get_result=None), arq=arq_mock, memory=memory_mock
    )
    resp = client.get(f"/tasks/{uuid.uuid4()}")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "task not found"


def test_task_lineage(arq_mock: MagicMock, memory_mock: AsyncMock) -> None:
    task_id = uuid.uuid4()
    client = make_client(session=FakeSession(), arq=arq_mock, memory=memory_mock)
    resp = client.get(f"/tasks/{task_id}/lineage")
    assert resp.status_code == 200
    assert resp.json() == [{"subtask": "S-1", "agent": "coder"}]
    memory_mock.task_lineage.assert_awaited_once_with(str(task_id))


def test_memory_similar(arq_mock: MagicMock, memory_mock: AsyncMock) -> None:
    client = make_client(session=FakeSession(), arq=arq_mock, memory=memory_mock)
    resp = client.get("/memory/similar", params={"q": "rate limit", "k": 3})
    assert resp.status_code == 200
    assert resp.json()[0]["kind"] == "code"
    memory_mock.similar_artifacts.assert_awaited_once_with("rate limit", k=3)


def test_run_gates(arq_mock: MagicMock, memory_mock: AsyncMock) -> None:
    client = make_client(session=FakeSession(), arq=arq_mock, memory=memory_mock)
    resp = client.post("/gates/run", params={"branch": "agent/x-y"})
    assert resp.status_code == 200
    assert resp.json() == {"job_id": "job-123"}
    arq_mock.enqueue_job.assert_awaited_once_with("run_gates_job", branch="agent/x-y")


# --- P0.1a: the legacy harness routes are not open to the internet -------------------
#
# These write to the DB, enqueue pipeline work and expose agent memory. Whoever they
# belong to, it is not an unauthenticated caller in an HR service: they are admin-only
# (see the table in test_authorization_matrix.py). What matters here is that the refusal
# lands BEFORE the side effect — refusing after the row is written and the job is queued
# would be no fix at all. ``/health`` stays open: it is a liveness probe.


def make_anonymous_client(
    *, session: FakeSession, arq: MagicMock, memory: AsyncMock
) -> TestClient:
    """A client with **CAS on** and no session cookie. Without ``cas_on()`` every
    request here resolves to the dev transient ADMIN and these tests pass vacuously."""
    client = make_client(session=session, arq=arq, memory=memory)
    cas_on()
    return client


def test_health_stays_reachable_without_credentials(
    arq_mock: MagicMock, memory_mock: AsyncMock
) -> None:
    client = make_anonymous_client(
        session=FakeSession(), arq=arq_mock, memory=memory_mock
    )
    resp = client.get("/health")
    assert resp.status_code == 200


def test_unauthenticated_create_task_writes_nothing_and_enqueues_nothing(
    arq_mock: MagicMock, memory_mock: AsyncMock
) -> None:
    session = FakeSession()
    client = make_anonymous_client(session=session, arq=arq_mock, memory=memory_mock)

    resp = client.post(
        "/tasks", json={"title": "Add rate limiter", "spec": "throttle the api"}
    )

    assert resp.status_code == 401
    assert session.added == []  # no row was created
    assert session.committed is False
    arq_mock.enqueue_job.assert_not_awaited()  # no pipeline was started


def test_unauthenticated_run_gates_enqueues_nothing(
    arq_mock: MagicMock, memory_mock: AsyncMock
) -> None:
    client = make_anonymous_client(
        session=FakeSession(), arq=arq_mock, memory=memory_mock
    )

    resp = client.post("/gates/run", params={"branch": "agent/x-y"})

    assert resp.status_code == 401
    arq_mock.enqueue_job.assert_not_awaited()


@pytest.mark.parametrize(
    "path",
    ["/tasks/{id}", "/tasks/{id}/lineage", "/memory/similar?q=rate+limit"],
)
def test_unauthenticated_read_of_task_state_or_agent_memory_is_refused(
    path: str, arq_mock: MagicMock, memory_mock: AsyncMock
) -> None:
    task = Task(title="Existing", spec="an existing spec", status=TaskStatus.DONE)
    task.id = uuid.uuid4()
    client = make_anonymous_client(
        session=FakeSession(get_result=task), arq=arq_mock, memory=memory_mock
    )

    resp = client.get(path.replace("{id}", str(task.id)))

    assert resp.status_code == 401
    memory_mock.task_lineage.assert_not_awaited()
    memory_mock.similar_artifacts.assert_not_awaited()


# --- P0.2: /health is LIVENESS and stays static --------------------------------------
#
# An orchestrator polls `/health` on a short interval and RESTARTS the container when it
# fails. A dependency check inside it inverts what it is for: a Neo4j blip would kill
# every healthy API pod simultaneously, escalating a degraded dependency into an
# outage. Dependency health belongs to `/ready` (tests/unit/test_readiness.py); this
# pins that it never creeps back in here.


class ExplodesIfTouched:
    """An ``app.state`` stand-in that fails the test if anything reads it."""

    def __init__(self, name: str) -> None:
        self.__dict__["_name"] = name

    def __getattr__(self, item: str) -> object:
        raise AssertionError(
            f"/health read app.state.{self.__dict__['_name']}.{item} — the liveness "
            "probe must not touch a dependency (P0.2). Move the check to /ready."
        )


@pytest.fixture
def no_dependencies_reachable() -> Iterator[None]:
    keys = ("engine", "sessionmaker", "arq", "memory")
    saved = {key: getattr(app.state, key, None) for key in keys}
    for key in keys:
        setattr(app.state, key, ExplodesIfTouched(key))
    yield
    for key, value in saved.items():
        setattr(app.state, key, value)


def test_health_is_a_static_liveness_probe_and_touches_no_dependency(
    no_dependencies_reachable: None,
) -> None:
    resp = TestClient(app).get("/health")

    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_health_does_not_report_dependency_state(
    no_dependencies_reachable: None,
) -> None:
    """Not even optimistically. If ``/health`` grows a ``checks`` key, someone will wire
    an orchestrator's liveness probe to it and the restart loop is back."""
    body = TestClient(app).get("/health").json()

    assert set(body) == {"status"}

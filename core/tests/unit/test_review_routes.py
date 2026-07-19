"""Unit tests for the Phase-4.4c review routes — thin FastAPI transport over the
Phase-4.4b review service.

Mirrors ``test_api.py``'s pattern: drive ``TestClient(app)`` WITHOUT the lifespan
(startup/shutdown skipped), override ``get_session`` with a fake session, and here
ALSO monkeypatch every ``src.api.routes.jd_bank.service.<fn>`` so the route logic —
request unpacking, the single service call, commit-on-success, serialization, and the
error -> HTTP status mapping — is tested in isolation from the DB and from the service's
own behaviour (that is the 4.4b integration suite's job).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from src.api.main import app, get_session
from src.api.routes import jd_bank
from src.jd_bank.db.models import CanonicalStatus
from src.jd_bank.review import (
    CanonicalNotFoundError,
    GateOverrideError,
    IllegalTransitionError,
    MissingReasonError,
    NotApprovableError,
    ReviewPacket,
    ReviewQueueItem,
)
from src.jd_core.models.parsed_jd import SFUJobDescription
from src.jd_core.models.quality import GateDecision, GateOverride, GateReason


class FakeCanonical:
    """A minimal stand-in for ``CanonicalJD`` — only the 4 fields ``CanonicalOut``
    reads off the returned row."""

    def __init__(
        self,
        *,
        canonical_id: uuid.UUID,
        cluster_id: uuid.UUID,
        version: int,
        status: CanonicalStatus,
    ) -> None:
        self.id = canonical_id
        self.cluster_id = cluster_id
        self.version = version
        self.status = status


class FakeSession:
    """Minimal async-session stand-in. ``commit`` is an ``AsyncMock`` so tests can
    pin exactly how many times (if any) it was awaited — the one behaviour a handler
    could get wrong (acceptance #3)."""

    def __init__(self) -> None:
        self.commit = AsyncMock()


@pytest.fixture(autouse=True)
def _clear_overrides() -> Iterator[None]:
    yield
    app.dependency_overrides.clear()


def make_client(session: FakeSession) -> TestClient:
    async def override_session() -> AsyncIterator[FakeSession]:
        yield session

    app.dependency_overrides[get_session] = override_session
    return TestClient(app)


def _blocked_decision() -> GateDecision:
    return GateDecision(
        approved=False,
        blocking=(
            GateReason(
                gate_id="SFU-GATE",
                source_part="Part 11.6",
                reason="still blocking",
                overridable=False,
            ),
        ),
    )


def _validation_error() -> ValidationError:
    """A real ``pydantic.ValidationError`` — exactly what ``service.edit`` raises for
    a ``new_content`` that fails ``SFUJobDescription`` reconstruction."""
    try:
        SFUJobDescription.model_validate({})
    except ValidationError as exc:
        return exc
    raise AssertionError("expected SFUJobDescription.model_validate({}) to fail")


# --- GET /jd-bank/review/queue --------------------------------------------------------


def test_list_queue_happy_path_and_limit_passthrough(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = FakeSession()
    client = make_client(session)
    item = ReviewQueueItem(
        canonical_id=uuid.uuid4(),
        cluster_id=uuid.uuid4(),
        version=1,
        status=CanonicalStatus.DRAFT,
        title="Software Developer",
        created_at=datetime.now(UTC),
    )
    mock = AsyncMock(return_value=(item,))
    monkeypatch.setattr(jd_bank.service, "list_review_queue", mock)

    resp = client.get("/jd-bank/review/queue", params={"limit": 5})

    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["canonical_id"] == str(item.canonical_id)
    assert body[0]["title"] == "Software Developer"
    mock.assert_awaited_once()
    call = mock.await_args
    assert call.args == (session,)
    assert call.kwargs == {"limit": 5}
    session.commit.assert_not_awaited()  # a GET never commits


def test_list_queue_without_limit_passes_none(monkeypatch: pytest.MonkeyPatch) -> None:
    session = FakeSession()
    client = make_client(session)
    mock = AsyncMock(return_value=())
    monkeypatch.setattr(jd_bank.service, "list_review_queue", mock)

    resp = client.get("/jd-bank/review/queue")

    assert resp.status_code == 200
    assert resp.json() == []
    mock.assert_awaited_once_with(session, limit=None)


# --- GET /jd-bank/review/{canonical_id} -----------------------------------------------


def test_get_packet_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    session = FakeSession()
    client = make_client(session)
    canonical_id = uuid.uuid4()
    packet = ReviewPacket(
        canonical_id=canonical_id,
        cluster_id=uuid.uuid4(),
        version=1,
        status=CanonicalStatus.DRAFT,
        content={"title": "Software Developer"},
        change_log={},
        decision=GateDecision(approved=True),
        score=90.0,
        grade="A",
    )
    mock = AsyncMock(return_value=packet)
    monkeypatch.setattr(jd_bank.service, "get_review_packet", mock)

    resp = client.get(f"/jd-bank/review/{canonical_id}")

    assert resp.status_code == 200
    body = resp.json()
    assert body["canonical_id"] == str(canonical_id)
    assert body["decision"]["approved"] is True
    mock.assert_awaited_once_with(session, canonical_id)
    session.commit.assert_not_awaited()


def test_get_packet_none_returns_404(monkeypatch: pytest.MonkeyPatch) -> None:
    session = FakeSession()
    client = make_client(session)
    canonical_id = uuid.uuid4()
    mock = AsyncMock(return_value=None)
    monkeypatch.setattr(jd_bank.service, "get_review_packet", mock)

    resp = client.get(f"/jd-bank/review/{canonical_id}")

    assert resp.status_code == 404
    session.commit.assert_not_awaited()


# --- POST .../approve --------------------------------------------------------------


def test_approve_happy_path_passes_reviewer_and_overrides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = FakeSession()
    client = make_client(session)
    canonical_id = uuid.uuid4()
    cluster_id = uuid.uuid4()
    fake = FakeCanonical(
        canonical_id=canonical_id,
        cluster_id=cluster_id,
        version=2,
        status=CanonicalStatus.PUBLISHED,
    )
    mock = AsyncMock(return_value=fake)
    monkeypatch.setattr(jd_bank.service, "approve", mock)

    resp = client.post(
        f"/jd-bank/review/{canonical_id}/approve",
        json={
            "reviewer_id": "hr-1",
            "overrides": [
                {
                    "gate_id": "SFU-GATE",
                    "reviewer": "hr-1",
                    "reason": "waived for pilot",
                }
            ],
        },
    )

    assert resp.status_code == 200
    assert resp.json() == {
        "canonical_id": str(canonical_id),
        "cluster_id": str(cluster_id),
        "version": 2,
        "status": "published",
    }
    mock.assert_awaited_once()
    call = mock.await_args
    assert call.args == (session, canonical_id)
    assert call.kwargs["reviewer_id"] == "hr-1"
    assert call.kwargs["overrides"] == [
        GateOverride(gate_id="SFU-GATE", reviewer="hr-1", reason="waived for pilot")
    ]
    session.commit.assert_awaited_once()


def test_approve_default_overrides_is_empty_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = FakeSession()
    client = make_client(session)
    canonical_id = uuid.uuid4()
    fake = FakeCanonical(
        canonical_id=canonical_id,
        cluster_id=uuid.uuid4(),
        version=1,
        status=CanonicalStatus.PUBLISHED,
    )
    mock = AsyncMock(return_value=fake)
    monkeypatch.setattr(jd_bank.service, "approve", mock)

    resp = client.post(
        f"/jd-bank/review/{canonical_id}/approve", json={"reviewer_id": "hr-1"}
    )

    assert resp.status_code == 200
    mock.assert_awaited_once_with(
        session, canonical_id, reviewer_id="hr-1", overrides=[]
    )
    session.commit.assert_awaited_once()


def test_approve_rejects_malformed_override_before_calling_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A reasonless override is unconstructable (``GateOverride`` itself enforces it)
    — FastAPI's own body validation rejects it with 422 before the service is ever
    called."""
    session = FakeSession()
    client = make_client(session)
    canonical_id = uuid.uuid4()
    mock = AsyncMock()
    monkeypatch.setattr(jd_bank.service, "approve", mock)

    resp = client.post(
        f"/jd-bank/review/{canonical_id}/approve",
        json={
            "reviewer_id": "hr-1",
            "overrides": [{"gate_id": "SFU-GATE", "reviewer": "hr-1", "reason": "  "}],
        },
    )

    assert resp.status_code == 422
    mock.assert_not_awaited()
    session.commit.assert_not_awaited()


# --- POST .../reject -----------------------------------------------------------------


def test_reject_happy_path_passes_reviewer_and_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = FakeSession()
    client = make_client(session)
    canonical_id = uuid.uuid4()
    cluster_id = uuid.uuid4()
    fake = FakeCanonical(
        canonical_id=canonical_id,
        cluster_id=cluster_id,
        version=1,
        status=CanonicalStatus.ARCHIVED,
    )
    mock = AsyncMock(return_value=fake)
    monkeypatch.setattr(jd_bank.service, "reject", mock)

    resp = client.post(
        f"/jd-bank/review/{canonical_id}/reject",
        json={"reviewer_id": "hr-1", "reason": "duplicate of another cluster"},
    )

    assert resp.status_code == 200
    assert resp.json() == {
        "canonical_id": str(canonical_id),
        "cluster_id": str(cluster_id),
        "version": 1,
        "status": "archived",
    }
    mock.assert_awaited_once_with(
        session,
        canonical_id,
        reviewer_id="hr-1",
        reason="duplicate of another cluster",
    )
    session.commit.assert_awaited_once()


# --- POST .../edit ---------------------------------------------------------------


def test_edit_happy_path_passes_reviewer_content_and_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = FakeSession()
    client = make_client(session)
    canonical_id = uuid.uuid4()
    new_id = uuid.uuid4()
    cluster_id = uuid.uuid4()
    fake = FakeCanonical(
        canonical_id=new_id,
        cluster_id=cluster_id,
        version=2,
        status=CanonicalStatus.DRAFT,
    )
    mock = AsyncMock(return_value=fake)
    monkeypatch.setattr(jd_bank.service, "edit", mock)
    new_content = {"title": "Updated Title"}

    resp = client.post(
        f"/jd-bank/review/{canonical_id}/edit",
        json={
            "reviewer_id": "hr-1",
            "new_content": new_content,
            "reason": "clarified the summary",
        },
    )

    assert resp.status_code == 200
    assert resp.json() == {
        "canonical_id": str(new_id),
        "cluster_id": str(cluster_id),
        "version": 2,
        "status": "draft",
    }
    mock.assert_awaited_once_with(
        session,
        canonical_id,
        reviewer_id="hr-1",
        new_content=new_content,
        reason="clarified the summary",
    )
    session.commit.assert_awaited_once()


# --- error -> status mapping, pinned per docs/tasks/phase-4.4c-review-routes.md -------


def test_canonical_not_found_maps_to_404(monkeypatch: pytest.MonkeyPatch) -> None:
    session = FakeSession()
    client = make_client(session)
    canonical_id = uuid.uuid4()
    mock = AsyncMock(side_effect=CanonicalNotFoundError(canonical_id))
    monkeypatch.setattr(jd_bank.service, "approve", mock)

    resp = client.post(
        f"/jd-bank/review/{canonical_id}/approve", json={"reviewer_id": "hr-1"}
    )

    assert resp.status_code == 404
    session.commit.assert_not_awaited()


def test_illegal_transition_maps_to_409(monkeypatch: pytest.MonkeyPatch) -> None:
    session = FakeSession()
    client = make_client(session)
    canonical_id = uuid.uuid4()
    mock = AsyncMock(
        side_effect=IllegalTransitionError(
            canonical_id, CanonicalStatus.PUBLISHED, "approve"
        )
    )
    monkeypatch.setattr(jd_bank.service, "approve", mock)

    resp = client.post(
        f"/jd-bank/review/{canonical_id}/approve", json={"reviewer_id": "hr-1"}
    )

    assert resp.status_code == 409
    session.commit.assert_not_awaited()


def test_not_approvable_maps_to_409(monkeypatch: pytest.MonkeyPatch) -> None:
    session = FakeSession()
    client = make_client(session)
    canonical_id = uuid.uuid4()
    mock = AsyncMock(side_effect=NotApprovableError(canonical_id, _blocked_decision()))
    monkeypatch.setattr(jd_bank.service, "approve", mock)

    resp = client.post(
        f"/jd-bank/review/{canonical_id}/approve", json={"reviewer_id": "hr-1"}
    )

    assert resp.status_code == 409
    session.commit.assert_not_awaited()


def test_gate_override_error_maps_to_422(monkeypatch: pytest.MonkeyPatch) -> None:
    session = FakeSession()
    client = make_client(session)
    canonical_id = uuid.uuid4()
    mock = AsyncMock(side_effect=GateOverrideError("gate is not overridable"))
    monkeypatch.setattr(jd_bank.service, "approve", mock)

    resp = client.post(
        f"/jd-bank/review/{canonical_id}/approve",
        json={
            "reviewer_id": "hr-1",
            "overrides": [
                {"gate_id": "SFU-GATE", "reviewer": "hr-1", "reason": "waived"}
            ],
        },
    )

    assert resp.status_code == 422
    session.commit.assert_not_awaited()


def test_missing_reason_maps_to_422(monkeypatch: pytest.MonkeyPatch) -> None:
    session = FakeSession()
    client = make_client(session)
    canonical_id = uuid.uuid4()
    mock = AsyncMock(side_effect=MissingReasonError("reject"))
    monkeypatch.setattr(jd_bank.service, "reject", mock)

    resp = client.post(
        f"/jd-bank/review/{canonical_id}/reject",
        json={"reviewer_id": "hr-1", "reason": "whitespace passed the wire somehow"},
    )

    assert resp.status_code == 422
    session.commit.assert_not_awaited()


def test_malformed_edit_content_maps_to_422(monkeypatch: pytest.MonkeyPatch) -> None:
    session = FakeSession()
    client = make_client(session)
    canonical_id = uuid.uuid4()
    mock = AsyncMock(side_effect=_validation_error())
    monkeypatch.setattr(jd_bank.service, "edit", mock)

    resp = client.post(
        f"/jd-bank/review/{canonical_id}/edit",
        json={"reviewer_id": "hr-1", "new_content": {}, "reason": "typo fix"},
    )

    assert resp.status_code == 422
    session.commit.assert_not_awaited()

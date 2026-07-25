"""Unit tests for the Phase-4.4d server-rendered review UI — a thin HTML transport
over the Phase-4.4b review service.

Mirrors ``test_review_routes.py``'s pattern: drive ``TestClient(app)`` WITHOUT the
lifespan (startup/shutdown skipped), override ``get_session`` with a fake session, and
monkeypatch every ``src.api.routes.ui.service.<fn>`` so the route logic — form
unpacking, the single service call, commit-on-success, HTML rendering, and the
error -> re-render mapping — is tested in isolation from the DB and from the service's
own behaviour (that is the 4.4b integration suite's job).
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from src.api.main import app, get_session
from src.api.routes import ui
from src.jd_bank.db.models import CanonicalStatus
from src.jd_bank.review import (
    CanonicalNotFoundError,
    MissingReasonError,
    NotApprovableError,
    ReviewPacket,
    ReviewQueueItem,
)
from src.jd_core.models.parsed_jd import SFUJobDescription
from src.jd_core.models.quality import GateDecision, GateOverride, GateReason


class FakeCanonical:
    """A minimal stand-in for ``CanonicalJD`` — only the fields the redirect handlers
    read off the returned row (``id``)."""

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
    """Minimal async-session stand-in. ``commit`` is an ``AsyncMock`` so tests can pin
    exactly how many times (if any) it was awaited — the one behaviour a handler could
    get wrong, as in 4.4c."""

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
    return TestClient(app, follow_redirects=False)


def _queue_item(
    *,
    title: str = "Software Developer",
    stored_blocking_gate_count: int = 0,
) -> ReviewQueueItem:
    return ReviewQueueItem(
        canonical_id=uuid.uuid4(),
        cluster_id=uuid.uuid4(),
        version=1,
        status=CanonicalStatus.DRAFT,
        title=title,
        stored_score=72.5,
        stored_grade="B",
        stored_approvable=stored_blocking_gate_count == 0,
        stored_blocking_gate_count=stored_blocking_gate_count,
        created_at=datetime.now(UTC),
    )


def _packet(
    *,
    canonical_id: uuid.UUID | None = None,
    blocking: tuple[GateReason, ...] = (),
    approved: bool | None = None,
) -> ReviewPacket:
    resolved_approved = approved if approved is not None else not blocking
    return ReviewPacket(
        canonical_id=canonical_id or uuid.uuid4(),
        cluster_id=uuid.uuid4(),
        version=1,
        status=CanonicalStatus.DRAFT,
        content={"title": "Software Developer"},
        change_log={
            "harmonization_diff": {
                "rendered_draft": "Software Developer\n\nSummary text.",
                "per_source": [],
                "removed": [
                    {
                        "content": "Answer phones",
                        "reason": "duty_dropped_over_max",
                        "member_index": 0,
                    }
                ],
                "flagged_duties": [],
            }
        },
        decision=GateDecision(approved=resolved_approved, blocking=blocking),
        score=72.5,
        grade="B",
        issues=(),
    )


def _overridable_gate(gate_id: str = "SFU-COMP-SUMMARY") -> GateReason:
    return GateReason(
        gate_id=gate_id,
        source_part="Part 4",
        reason="the position summary is missing",
        overridable=True,
    )


def _non_overridable_gate(gate_id: str = "SFU-BANNED-WORD") -> GateReason:
    return GateReason(
        gate_id=gate_id,
        source_part="Part 11.6",
        reason="a banned word was used",
        overridable=False,
    )


def _validation_error() -> ValidationError:
    """A real ``pydantic.ValidationError`` — exactly what ``service.edit`` raises for a
    ``new_content`` that fails ``SFUJobDescription`` reconstruction."""
    try:
        SFUJobDescription.model_validate({"title": 123})
    except ValidationError as exc:
        return exc
    raise AssertionError("expected SFUJobDescription.model_validate to fail")


# --- GET /jd-bank/ui/queue -----------------------------------------------------------


def test_queue_renders_items_in_service_order(monkeypatch: pytest.MonkeyPatch) -> None:
    session = FakeSession()
    client = make_client(session)
    first = _queue_item(title="Blocked Analyst", stored_blocking_gate_count=2)
    second = _queue_item(title="Clean Developer", stored_blocking_gate_count=0)
    mock = AsyncMock(return_value=(first, second))
    monkeypatch.setattr(ui.service, "list_review_queue", mock)

    resp = client.get("/jd-bank/ui/queue")

    assert resp.status_code == 200
    body = resp.text
    assert body.index("Blocked Analyst") < body.index("Clean Developer")
    assert f"/jd-bank/ui/review/{first.canonical_id}" in body
    assert f"/jd-bank/ui/review/{second.canonical_id}" in body
    assert ">2<" in body  # the blocking-gate count badge
    mock.assert_awaited_once_with(session, limit=None)
    session.commit.assert_not_awaited()


def test_queue_limit_passthrough(monkeypatch: pytest.MonkeyPatch) -> None:
    session = FakeSession()
    client = make_client(session)
    mock = AsyncMock(return_value=())
    monkeypatch.setattr(ui.service, "list_review_queue", mock)

    resp = client.get("/jd-bank/ui/queue", params={"limit": 5})

    assert resp.status_code == 200
    mock.assert_awaited_once_with(session, limit=5)


def test_queue_empty_state_is_not_a_crash(monkeypatch: pytest.MonkeyPatch) -> None:
    session = FakeSession()
    client = make_client(session)
    mock = AsyncMock(return_value=())
    monkeypatch.setattr(ui.service, "list_review_queue", mock)

    resp = client.get("/jd-bank/ui/queue")

    assert resp.status_code == 200
    assert "No drafts awaiting review" in resp.text


# --- GET /jd-bank/ui/review/{canonical_id} --------------------------------------------


def test_detail_renders_fresh_decision_draft_diff_and_override_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = FakeSession()
    client = make_client(session)
    canonical_id = uuid.uuid4()
    packet = _packet(
        canonical_id=canonical_id,
        blocking=(
            _overridable_gate("SFU-OVERRIDABLE"),
            _non_overridable_gate("SFU-FIXED"),
        ),
        approved=False,
    )
    mock = AsyncMock(return_value=packet)
    monkeypatch.setattr(ui.service, "get_review_packet", mock)

    resp = client.get(f"/jd-bank/ui/review/{canonical_id}")

    assert resp.status_code == 200
    body = resp.text
    assert "72.5" in body
    assert ">B<" in body
    # A string UNIQUE to the rendered draft (NOT the title, which the <h2> renders
    # independently) — so this fails if _detail_context read the wrong change_log key
    # and rendered_draft came back "".
    assert "Summary text." in body  # the rendered draft
    assert "Answer phones" in body  # the 4.3 removed content
    assert "duty_dropped_over_max" in body
    # Overridable blocker gets a textarea; non-overridable does not.
    assert 'name="override_reason__SFU-OVERRIDABLE"' in body
    assert 'name="override_reason__SFU-FIXED"' not in body
    mock.assert_awaited_once_with(session, canonical_id)
    session.commit.assert_not_awaited()


def test_detail_unknown_id_returns_404(monkeypatch: pytest.MonkeyPatch) -> None:
    session = FakeSession()
    client = make_client(session)
    canonical_id = uuid.uuid4()
    mock = AsyncMock(return_value=None)
    monkeypatch.setattr(ui.service, "get_review_packet", mock)

    resp = client.get(f"/jd-bank/ui/review/{canonical_id}")

    assert resp.status_code == 404
    session.commit.assert_not_awaited()


# --- POST .../approve -----------------------------------------------------------------


def test_approve_happy_path_calls_service_commits_and_redirects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = FakeSession()
    client = make_client(session)
    canonical_id = uuid.uuid4()
    fake = FakeCanonical(
        canonical_id=canonical_id,
        cluster_id=uuid.uuid4(),
        version=2,
        status=CanonicalStatus.PUBLISHED,
    )
    mock = AsyncMock(return_value=fake)
    monkeypatch.setattr(ui.service, "approve", mock)

    resp = client.post(
        f"/jd-bank/ui/review/{canonical_id}/approve",
        data={
            "reviewer_id": "hr-1",
            "override_reason__SFU-OVERRIDABLE": "waived for pilot",
        },
    )

    assert resp.status_code == 303
    assert resp.headers["location"] == "/jd-bank/ui/queue"
    mock.assert_awaited_once()
    call = mock.await_args
    assert call.args == (session, canonical_id)
    assert call.kwargs["reviewer_id"] == "dev-anonymous"
    assert call.kwargs["overrides"] == [
        GateOverride(
            gate_id="SFU-OVERRIDABLE",
            reviewer="dev-anonymous",
            reason="waived for pilot",
        )
    ]
    session.commit.assert_awaited_once()


def test_approve_blank_override_textarea_produces_no_override(
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
    monkeypatch.setattr(ui.service, "approve", mock)

    resp = client.post(
        f"/jd-bank/ui/review/{canonical_id}/approve",
        data={
            "reviewer_id": "hr-1",
            "override_reason__SFU-OVERRIDABLE": "   ",
        },
    )

    assert resp.status_code == 303
    mock.assert_awaited_once_with(
        session, canonical_id, reviewer_id="dev-anonymous", overrides=[]
    )
    session.commit.assert_awaited_once()


def test_approve_no_override_fields_at_all_passes_empty_list(
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
    monkeypatch.setattr(ui.service, "approve", mock)

    resp = client.post(
        f"/jd-bank/ui/review/{canonical_id}/approve",
        data={"reviewer_id": "hr-1"},
    )

    assert resp.status_code == 303
    mock.assert_awaited_once_with(
        session, canonical_id, reviewer_id="dev-anonymous", overrides=[]
    )
    session.commit.assert_awaited_once()


def test_approve_of_a_blocked_draft_does_not_commit_and_rerenders_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = FakeSession()
    client = make_client(session)
    canonical_id = uuid.uuid4()
    blocked_decision = GateDecision(
        approved=False,
        blocking=(_non_overridable_gate("SFU-STILL-BLOCKING"),),
    )
    approve_mock = AsyncMock(
        side_effect=NotApprovableError(canonical_id, blocked_decision)
    )
    monkeypatch.setattr(ui.service, "approve", approve_mock)
    packet = _packet(
        canonical_id=canonical_id,
        blocking=(_non_overridable_gate("SFU-STILL-BLOCKING"),),
        approved=False,
    )
    packet_mock = AsyncMock(return_value=packet)
    monkeypatch.setattr(ui.service, "get_review_packet", packet_mock)

    resp = client.post(
        f"/jd-bank/ui/review/{canonical_id}/approve",
        data={"reviewer_id": "hr-1"},
    )

    assert resp.status_code == 200
    assert "a banned word was used" in resp.text  # the blocking gate's reason
    assert "cannot be approved" in resp.text  # the raised error text
    session.commit.assert_not_awaited()
    packet_mock.assert_awaited_once_with(session, canonical_id)


def test_approve_of_unknown_canonical_shows_404_not_a_crash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = FakeSession()
    client = make_client(session)
    canonical_id = uuid.uuid4()
    monkeypatch.setattr(
        ui.service,
        "approve",
        AsyncMock(side_effect=CanonicalNotFoundError(canonical_id)),
    )
    monkeypatch.setattr(ui.service, "get_review_packet", AsyncMock(return_value=None))

    resp = client.post(
        f"/jd-bank/ui/review/{canonical_id}/approve",
        data={"reviewer_id": "hr-1"},
    )

    assert resp.status_code == 404
    session.commit.assert_not_awaited()


# --- POST .../reject ------------------------------------------------------------------


def test_reject_happy_path_calls_service_commits_and_redirects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = FakeSession()
    client = make_client(session)
    canonical_id = uuid.uuid4()
    fake = FakeCanonical(
        canonical_id=canonical_id,
        cluster_id=uuid.uuid4(),
        version=1,
        status=CanonicalStatus.ARCHIVED,
    )
    mock = AsyncMock(return_value=fake)
    monkeypatch.setattr(ui.service, "reject", mock)

    resp = client.post(
        f"/jd-bank/ui/review/{canonical_id}/reject",
        data={"reviewer_id": "hr-1", "reason": "duplicate of another cluster"},
    )

    assert resp.status_code == 303
    assert resp.headers["location"] == "/jd-bank/ui/queue"
    mock.assert_awaited_once_with(
        session,
        canonical_id,
        reviewer_id="dev-anonymous",
        reason="duplicate of another cluster",
    )
    session.commit.assert_awaited_once()


def test_reject_blank_reason_does_not_commit_and_rerenders_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = FakeSession()
    client = make_client(session)
    canonical_id = uuid.uuid4()
    reject_mock = AsyncMock(side_effect=MissingReasonError("reject"))
    monkeypatch.setattr(ui.service, "reject", reject_mock)
    packet = _packet(canonical_id=canonical_id)
    monkeypatch.setattr(ui.service, "get_review_packet", AsyncMock(return_value=packet))

    resp = client.post(
        f"/jd-bank/ui/review/{canonical_id}/reject",
        data={"reviewer_id": "hr-1", "reason": ""},
    )

    assert resp.status_code == 200
    assert "requires a written reason" in resp.text
    session.commit.assert_not_awaited()


# --- POST .../edit --------------------------------------------------------------------


def test_edit_happy_path_calls_service_commits_and_redirects_to_new_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = FakeSession()
    client = make_client(session)
    canonical_id = uuid.uuid4()
    new_id = uuid.uuid4()
    fake = FakeCanonical(
        canonical_id=new_id,
        cluster_id=uuid.uuid4(),
        version=2,
        status=CanonicalStatus.DRAFT,
    )
    mock = AsyncMock(return_value=fake)
    monkeypatch.setattr(ui.service, "edit", mock)
    new_content = {"title": "Updated Title"}

    resp = client.post(
        f"/jd-bank/ui/review/{canonical_id}/edit",
        data={
            "reviewer_id": "hr-1",
            "reason": "clarified the summary",
            "content": json.dumps(new_content),
        },
    )

    assert resp.status_code == 303
    assert resp.headers["location"] == f"/jd-bank/ui/review/{new_id}"
    mock.assert_awaited_once_with(
        session,
        canonical_id,
        reviewer_id="dev-anonymous",
        new_content=new_content,
        reason="clarified the summary",
    )
    session.commit.assert_awaited_once()


def test_edit_malformed_json_never_calls_service_and_does_not_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = FakeSession()
    client = make_client(session)
    canonical_id = uuid.uuid4()
    edit_mock = AsyncMock()
    monkeypatch.setattr(ui.service, "edit", edit_mock)
    packet = _packet(canonical_id=canonical_id)
    monkeypatch.setattr(ui.service, "get_review_packet", AsyncMock(return_value=packet))

    resp = client.post(
        f"/jd-bank/ui/review/{canonical_id}/edit",
        data={
            "reviewer_id": "hr-1",
            "reason": "typo fix",
            "content": "{not valid json",
        },
    )

    assert resp.status_code == 200
    edit_mock.assert_not_awaited()
    session.commit.assert_not_awaited()


def test_edit_invalid_content_validation_error_does_not_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = FakeSession()
    client = make_client(session)
    canonical_id = uuid.uuid4()
    edit_mock = AsyncMock(side_effect=_validation_error())
    monkeypatch.setattr(ui.service, "edit", edit_mock)
    packet = _packet(canonical_id=canonical_id)
    monkeypatch.setattr(ui.service, "get_review_packet", AsyncMock(return_value=packet))

    resp = client.post(
        f"/jd-bank/ui/review/{canonical_id}/edit",
        data={
            "reviewer_id": "hr-1",
            "reason": "typo fix",
            "content": json.dumps({"title": 123}),
        },
    )

    assert resp.status_code == 200
    edit_mock.assert_awaited_once()
    session.commit.assert_not_awaited()

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


def test_detail_links_to_the_version_diff(monkeypatch: pytest.MonkeyPatch) -> None:
    session = FakeSession()
    client = make_client(session)
    canonical_id = uuid.uuid4()
    monkeypatch.setattr(
        ui.service,
        "get_review_packet",
        AsyncMock(return_value=_packet(canonical_id=canonical_id)),
    )
    body = client.get(f"/jd-bank/ui/review/{canonical_id}").text
    assert f"/jd-bank/ui/review/{canonical_id}/diff" in body


# --- GET /jd-bank/ui/review/{canonical_id}/diff ---------------------------------------


def test_diff_view_renders_changed_sections(monkeypatch: pytest.MonkeyPatch) -> None:
    """The diff page shows each changed section's before/after, and lists the unchanged
    ones — driven by the (faked) service ``VersionDiff``."""
    from src.jd_core.bank.version_diff import SectionChange, VersionDiff

    session = FakeSession()
    client = make_client(session)
    canonical_id = uuid.uuid4()
    monkeypatch.setattr(
        ui.service,
        "get_review_packet",
        AsyncMock(return_value=_packet(canonical_id=canonical_id)),
    )
    diff = VersionDiff(
        sections=(
            SectionChange(
                section="Title",
                before="Old Title",
                after="New Title",
                changed=True,
            ),
            SectionChange(
                section="Qualifications", before="same", after="same", changed=False
            ),
        ),
        any_changes=True,
    )
    monkeypatch.setattr(ui.service, "get_version_diff", AsyncMock(return_value=diff))

    resp = client.get(f"/jd-bank/ui/review/{canonical_id}/diff")

    assert resp.status_code == 200
    body = resp.text
    assert "Old Title" in body and "New Title" in body  # before/after both shown
    assert "Qualifications" in body  # listed as unchanged
    session.commit.assert_not_awaited()


def test_diff_view_shows_empty_state_when_no_prior_approved_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No earlier PUBLISHED version -> the service returns None -> a friendly empty
    state (200), not a 404 or a crash."""
    session = FakeSession()
    client = make_client(session)
    canonical_id = uuid.uuid4()
    monkeypatch.setattr(
        ui.service,
        "get_review_packet",
        AsyncMock(return_value=_packet(canonical_id=canonical_id)),
    )
    monkeypatch.setattr(ui.service, "get_version_diff", AsyncMock(return_value=None))

    resp = client.get(f"/jd-bank/ui/review/{canonical_id}/diff")

    assert resp.status_code == 200
    assert "No previously approved version" in resp.text


def test_diff_view_unknown_id_returns_404(monkeypatch: pytest.MonkeyPatch) -> None:
    session = FakeSession()
    client = make_client(session)
    canonical_id = uuid.uuid4()
    monkeypatch.setattr(ui.service, "get_review_packet", AsyncMock(return_value=None))

    resp = client.get(f"/jd-bank/ui/review/{canonical_id}/diff")

    assert resp.status_code == 404


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
#
# The reviewer edit view is a STRUCTURED per-field editor, not a raw-JSON textarea: a
# reviewer cannot be asked to hand-edit JSON. The route reconstructs the FULL
# ``SFUJobDescription`` dict from the form (every field, so editing one never silently
# wipes another) and hands it to ``service.edit`` (still the sole authority; validator
# stays the oracle).


def _rich_content() -> dict[str, object]:
    """A fully-populated JD content dict — every section carries data, so the edit
    reconstruction can be checked for FAITHFULNESS (nothing dropped on save)."""
    return {
        "title": "Software Developer",
        "position_number": "AP-1234",
        "department": "Information Services",
        "grade": "J",
        "employee_group": "apsa",
        "about_sfu_present": True,
        "position_summary": "Builds and maintains university systems.",
        "duties": [
            {
                "action_verb": "Develops",
                "statement": "Develops applications (60%)",
                "how_why": ["to modernize services", "under the CTO"],
                "frequency": None,
            }
        ],
        "decision_making": ["Chooses the tech stack"],
        "problem_solving": ["Diagnoses production incidents"],
        "relationships": {
            "supervisory": "Reports to the Director.",
            "internal": ["Faculty IT"],
            "external": ["Vendors"],
        },
        "qualifications": [
            {"text": "Bachelor's degree", "kind": "education", "modifier": None},
            {"text": "Python", "kind": "skill", "modifier": "advanced"},
        ],
        "territorial_acknowledgement_present": True,
        "employment_equity_present": True,
        "additional_context": "Occasional evening work.",
    }


def _edit_form_body(**overrides: str) -> dict[str, str]:
    """The structured edit form as a scalar field dict (single-value rows), matching
    what a browser posts for a one-duty / one-qual draft. Callers override fields."""
    body = {
        "reason": "clarified the summary",
        "title": "Updated Title",
        "position_number": "AP-1234",
        "department": "Information Services",
        "grade": "J",
        "employee_group": "apsa",
        "about_sfu_present": "on",
        "position_summary": "Builds and maintains university systems.",
        "duty_verb": "Develops",
        "duty_statement": "Develops applications (60%)",
        "duty_frequency": "",
        "duty_how_why": "to modernize services\nunder the CTO",
        "decision_making": "Chooses the tech stack",
        "problem_solving": "Diagnoses production incidents",
        "supervisory": "Reports to the Director.",
        "rel_internal": "Faculty IT",
        "rel_external": "Vendors",
        "qual_text": "Python",
        "qual_kind": "skill",
        "qual_modifier": "advanced",
        "territorial_acknowledgement_present": "on",
        "employment_equity_present": "on",
        "additional_context": "Occasional evening work.",
    }
    body.update(overrides)
    return body


def test_detail_renders_structured_edit_fields_not_a_raw_json_textarea(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The edit view is structured controls prefilled from the draft — no raw-JSON
    ``<textarea name="content">`` a reviewer would have to hand-edit."""
    session = FakeSession()
    client = make_client(session)
    canonical_id = uuid.uuid4()
    packet = _packet(canonical_id=canonical_id)
    packet = packet.model_copy(update={"content": _rich_content()})
    monkeypatch.setattr(ui.service, "get_review_packet", AsyncMock(return_value=packet))

    body = client.get(f"/jd-bank/ui/review/{canonical_id}").text

    # No raw-JSON editor.
    assert 'name="content"' not in body
    # Structured controls, prefilled from the draft.
    assert 'name="title"' in body
    assert "Software Developer" in body  # title value prefilled
    assert 'name="duty_statement"' in body
    assert "Develops applications (60%)" in body  # duty prefilled
    assert 'name="qual_text"' in body
    assert 'name="qual_kind"' in body
    # The how_why detail the flat editor would drop is present for editing.
    assert "to modernize services" in body


def test_edit_reconstructs_full_faithful_content_and_redirects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A structured edit rebuilds the COMPLETE JD dict (every field), so editing the
    title does not wipe grade / booleans / duties, then redirects to the new version."""
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

    resp = client.post(
        f"/jd-bank/ui/review/{canonical_id}/edit", data=_edit_form_body()
    )

    assert resp.status_code == 303
    assert resp.headers["location"] == f"/jd-bank/ui/review/{new_id}"
    mock.assert_awaited_once()
    call = mock.await_args
    assert call.args == (session, canonical_id)
    assert call.kwargs["reviewer_id"] == "dev-anonymous"
    assert call.kwargs["reason"] == "clarified the summary"
    content = call.kwargs["new_content"]
    # Every scalar/boolean survives — not just the edited title.
    assert content["title"] == "Updated Title"
    assert content["position_number"] == "AP-1234"
    assert content["grade"] == "J"
    assert content["employee_group"] == "apsa"
    assert content["about_sfu_present"] is True
    assert content["territorial_acknowledgement_present"] is True
    assert content["employment_equity_present"] is True
    assert content["decision_making"] == ["Chooses the tech stack"]
    assert content["problem_solving"] == ["Diagnoses production incidents"]
    assert content["relationships"] == {
        "supervisory": "Reports to the Director.",
        "internal": ["Faculty IT"],
        "external": ["Vendors"],
    }
    session.commit.assert_awaited_once()


def test_edit_preserves_duty_how_why_and_frequency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The per-duty ``how_why`` list and ``frequency`` a flat editor would silently
    drop must round-trip into the reconstructed content (no corruption on save)."""
    session = FakeSession()
    client = make_client(session)
    canonical_id = uuid.uuid4()
    fake = FakeCanonical(
        canonical_id=uuid.uuid4(),
        cluster_id=uuid.uuid4(),
        version=2,
        status=CanonicalStatus.DRAFT,
    )
    mock = AsyncMock(return_value=fake)
    monkeypatch.setattr(ui.service, "edit", mock)

    resp = client.post(
        f"/jd-bank/ui/review/{canonical_id}/edit",
        data=_edit_form_body(duty_frequency="weekly"),
    )

    assert resp.status_code == 303
    duties = mock.await_args.kwargs["new_content"]["duties"]
    assert duties == [
        {
            "action_verb": "Develops",
            "statement": "Develops applications (60%)",
            "how_why": ["to modernize services", "under the CTO"],
            "frequency": "weekly",
        }
    ]


def test_reconstructed_edit_content_is_a_valid_jd(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The dict the edit form reconstructs must be a REAL SFUJobDescription (the shape
    service.edit re-validates) — this feeds the captured new_content through the actual
    model, so a misnamed field or wrong shape fails here, not silently in production."""
    session = FakeSession()
    client = make_client(session)
    canonical_id = uuid.uuid4()
    fake = FakeCanonical(
        canonical_id=uuid.uuid4(),
        cluster_id=uuid.uuid4(),
        version=2,
        status=CanonicalStatus.DRAFT,
    )
    mock = AsyncMock(return_value=fake)
    monkeypatch.setattr(ui.service, "edit", mock)

    resp = client.post(
        f"/jd-bank/ui/review/{canonical_id}/edit", data=_edit_form_body()
    )

    assert resp.status_code == 303
    content = mock.await_args.kwargs["new_content"]
    # Faithful round-trip: reconstructed -> model -> dump equals the reconstructed dict.
    jd = SFUJobDescription.model_validate(content)
    assert jd.model_dump(mode="json") == content


def test_edit_qual_kind_and_modifier_captured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = FakeSession()
    client = make_client(session)
    canonical_id = uuid.uuid4()
    fake = FakeCanonical(
        canonical_id=uuid.uuid4(),
        cluster_id=uuid.uuid4(),
        version=2,
        status=CanonicalStatus.DRAFT,
    )
    mock = AsyncMock(return_value=fake)
    monkeypatch.setattr(ui.service, "edit", mock)

    resp = client.post(
        f"/jd-bank/ui/review/{canonical_id}/edit",
        data=_edit_form_body(
            qual_text="GAAP", qual_kind="knowledge", qual_modifier="excellent"
        ),
    )

    assert resp.status_code == 303
    quals = mock.await_args.kwargs["new_content"]["qualifications"]
    assert quals == [{"text": "GAAP", "kind": "knowledge", "modifier": "excellent"}]


def test_edit_empty_optional_scalars_become_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Clearing an optional scalar sends ``None`` (not ``""``), so the field is really
    cleared and not stored as an empty string the model would reject or misrepresent."""
    session = FakeSession()
    client = make_client(session)
    canonical_id = uuid.uuid4()
    fake = FakeCanonical(
        canonical_id=uuid.uuid4(),
        cluster_id=uuid.uuid4(),
        version=2,
        status=CanonicalStatus.DRAFT,
    )
    mock = AsyncMock(return_value=fake)
    monkeypatch.setattr(ui.service, "edit", mock)

    resp = client.post(
        f"/jd-bank/ui/review/{canonical_id}/edit",
        data=_edit_form_body(department="", grade="", position_number=""),
    )

    assert resp.status_code == 303
    content = mock.await_args.kwargs["new_content"]
    assert content["department"] is None
    assert content["grade"] is None
    assert content["position_number"] is None


def test_edit_unchecked_boolean_flags_become_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unchecked presence checkbox posts nothing -> the flag reconstructs as False
    (the mandated-boilerplate gates then correctly see it as absent)."""
    session = FakeSession()
    client = make_client(session)
    canonical_id = uuid.uuid4()
    fake = FakeCanonical(
        canonical_id=uuid.uuid4(),
        cluster_id=uuid.uuid4(),
        version=2,
        status=CanonicalStatus.DRAFT,
    )
    mock = AsyncMock(return_value=fake)
    monkeypatch.setattr(ui.service, "edit", mock)

    body = _edit_form_body()
    for flag in (
        "about_sfu_present",
        "territorial_acknowledgement_present",
        "employment_equity_present",
    ):
        del body[flag]  # a browser omits an unchecked checkbox entirely

    resp = client.post(f"/jd-bank/ui/review/{canonical_id}/edit", data=body)

    assert resp.status_code == 303
    content = mock.await_args.kwargs["new_content"]
    assert content["about_sfu_present"] is False
    assert content["territorial_acknowledgement_present"] is False
    assert content["employment_equity_present"] is False


def test_edit_drops_blank_duty_and_qual_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The padded blank rows a reviewer leaves empty are dropped, not sent as empty
    duties/quals the model would reject."""
    session = FakeSession()
    client = make_client(session)
    canonical_id = uuid.uuid4()
    fake = FakeCanonical(
        canonical_id=uuid.uuid4(),
        cluster_id=uuid.uuid4(),
        version=2,
        status=CanonicalStatus.DRAFT,
    )
    mock = AsyncMock(return_value=fake)
    monkeypatch.setattr(ui.service, "edit", mock)

    resp = client.post(
        f"/jd-bank/ui/review/{canonical_id}/edit",
        data=_edit_form_body(duty_statement="", qual_text=""),
    )

    assert resp.status_code == 303
    content = mock.await_args.kwargs["new_content"]
    assert content["duties"] == []
    assert content["qualifications"] == []


def test_edit_invalid_content_validation_error_does_not_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A reconstructed content the model rejects (e.g. a cleared, empty title) surfaces
    the service's ValidationError on the re-rendered page and commits nothing."""
    session = FakeSession()
    client = make_client(session)
    canonical_id = uuid.uuid4()
    edit_mock = AsyncMock(side_effect=_validation_error())
    monkeypatch.setattr(ui.service, "edit", edit_mock)
    packet = _packet(canonical_id=canonical_id)
    monkeypatch.setattr(ui.service, "get_review_packet", AsyncMock(return_value=packet))

    resp = client.post(
        f"/jd-bank/ui/review/{canonical_id}/edit",
        data=_edit_form_body(title=""),
    )

    assert resp.status_code == 200
    edit_mock.assert_awaited_once()
    session.commit.assert_not_awaited()

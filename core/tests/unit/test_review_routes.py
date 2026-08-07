"""Unit tests for the Phase-4.4c review routes — thin FastAPI transport over the
Phase-4.4b review service.

Mirrors ``test_api.py``'s pattern: drive ``TestClient(app)`` WITHOUT the lifespan
(startup/shutdown skipped), override ``get_session`` with a fake session, and here
ALSO monkeypatch every ``src.api.routes.jd_bank.service.<fn>`` so the route logic —
request unpacking, the single service call, commit-on-success, serialization, and the
error -> HTTP status mapping — is tested in isolation from the DB and from the service's
own behaviour (that is the 4.4b integration suite's job).

**P0.1a — the actor is server-derived.** These routes used to take ``reviewer_id`` from
the request *body* and hand it to the service, which writes it as ``actor`` into the
hash-chained ``audit_log``: the chain stayed intact while attesting to an identity the
caller simply typed (NN #6), on routes that had no auth gate at all (NN #1). So every
test here now signs in (:func:`tests.unit.auth_fakes.signed_in_as`) and asserts the
service receives the **authenticated** identity — never anything from the request. The
per-override ``reviewer`` is a second forgeable actor and is pinned separately.
Who may call these routes at all is pinned in ``test_authorization_matrix.py``.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from src.api.db.models import Role
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
from tests.unit.auth_fakes import cas_on, signed_in_as, user_holding

#: The signed-in reviewer these tests act as. Deliberately unlike any string a test
#: puts in a request body, so "the service got the authenticated identity" cannot be
#: confused with "the service got what the caller sent".
REVIEWER_USERNAME = "reviewer-1"


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


def _override_session(session: FakeSession) -> None:
    async def override_session() -> AsyncIterator[FakeSession]:
        yield session

    app.dependency_overrides[get_session] = override_session


def make_client(session: FakeSession) -> TestClient:
    """A client signed in as a reviewer — the normal case. The RBAC gate itself still
    runs (only the cookie -> session -> user lookup is stubbed), so these tests exercise
    an authorized request rather than an ungated one."""
    _override_session(session)
    signed_in_as(user_holding(Role.REVIEWER, username=REVIEWER_USERNAME))
    return TestClient(app)


def make_anonymous_client(session: FakeSession) -> TestClient:
    """A client with **CAS on** and no session at all — the attacker's view. No identity
    override: the real ``resolve_user`` runs, finds no cookie and must refuse."""
    _override_session(session)
    cas_on()
    return TestClient(app, follow_redirects=False)


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
            "overrides": [
                {
                    "gate_id": "SFU-GATE",
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
    # The actor is the SIGNED-IN user; the request body cannot name it (NN #1/#6).
    assert call.kwargs["reviewer_id"] == REVIEWER_USERNAME
    # An override names its reviewer too — also stamped from the session, not the body.
    assert call.kwargs["overrides"] == [
        GateOverride(
            gate_id="SFU-GATE", reviewer=REVIEWER_USERNAME, reason="waived for pilot"
        )
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

    resp = client.post(f"/jd-bank/review/{canonical_id}/approve", json={})

    assert resp.status_code == 200
    mock.assert_awaited_once_with(
        session, canonical_id, reviewer_id=REVIEWER_USERNAME, overrides=[]
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
        json={"overrides": [{"gate_id": "SFU-GATE", "reason": "  "}]},
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
        json={"reason": "duplicate of another cluster"},
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
        reviewer_id=REVIEWER_USERNAME,
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
        json={"new_content": new_content, "reason": "clarified the summary"},
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
        reviewer_id=REVIEWER_USERNAME,
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

    resp = client.post(f"/jd-bank/review/{canonical_id}/approve", json={})

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

    resp = client.post(f"/jd-bank/review/{canonical_id}/approve", json={})

    assert resp.status_code == 409
    session.commit.assert_not_awaited()


def test_not_approvable_maps_to_409(monkeypatch: pytest.MonkeyPatch) -> None:
    session = FakeSession()
    client = make_client(session)
    canonical_id = uuid.uuid4()
    mock = AsyncMock(side_effect=NotApprovableError(canonical_id, _blocked_decision()))
    monkeypatch.setattr(jd_bank.service, "approve", mock)

    resp = client.post(f"/jd-bank/review/{canonical_id}/approve", json={})

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
        json={"overrides": [{"gate_id": "SFU-GATE", "reason": "waived"}]},
    )

    assert resp.status_code == 422
    # The 422 must come from the SERVICE error, not from body validation — otherwise
    # this mapping test would still "pass" against a route that rejects every request.
    mock.assert_awaited_once()
    session.commit.assert_not_awaited()


def test_missing_reason_maps_to_422(monkeypatch: pytest.MonkeyPatch) -> None:
    session = FakeSession()
    client = make_client(session)
    canonical_id = uuid.uuid4()
    mock = AsyncMock(side_effect=MissingReasonError("reject"))
    monkeypatch.setattr(jd_bank.service, "reject", mock)

    resp = client.post(
        f"/jd-bank/review/{canonical_id}/reject",
        json={"reason": "whitespace passed the wire somehow"},
    )

    assert resp.status_code == 422
    mock.assert_awaited_once()  # the service raised it, not body validation
    session.commit.assert_not_awaited()


def test_malformed_edit_content_maps_to_422(monkeypatch: pytest.MonkeyPatch) -> None:
    session = FakeSession()
    client = make_client(session)
    canonical_id = uuid.uuid4()
    mock = AsyncMock(side_effect=_validation_error())
    monkeypatch.setattr(jd_bank.service, "edit", mock)

    resp = client.post(
        f"/jd-bank/review/{canonical_id}/edit",
        json={"new_content": {}, "reason": "typo fix"},
    )

    assert resp.status_code == 422
    mock.assert_awaited_once()  # the service raised it, not body validation
    session.commit.assert_not_awaited()


# --- P0.1a: the actor is the session, never the request ------------------------------
#
# The service writes ``actor=reviewer_id`` into the hash-chained append-only audit log.
# If a caller can choose that string, the chain is intact but the identity it attests to
# is fiction (NN #6) — so these pin the ONE thing a route may not let its caller choose.


@pytest.mark.parametrize(
    ("action", "payload"),
    [
        ("approve", {}),
        ("reject", {"reason": "duplicate of another cluster"}),
        ("edit", {"new_content": {"title": "T"}, "reason": "clarified the summary"}),
    ],
)
def test_action_is_attributed_to_the_authenticated_user(
    action: str,
    payload: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """approve / reject / edit each hand the service the SIGNED-IN identity."""
    session = FakeSession()
    client = make_client(session)
    canonical_id = uuid.uuid4()
    mock = AsyncMock(
        return_value=FakeCanonical(
            canonical_id=canonical_id,
            cluster_id=uuid.uuid4(),
            version=1,
            status=CanonicalStatus.DRAFT,
        )
    )
    monkeypatch.setattr(jd_bank.service, action, mock)

    resp = client.post(f"/jd-bank/review/{canonical_id}/{action}", json=payload)

    assert resp.status_code == 200
    mock.assert_awaited_once()
    assert mock.await_args.kwargs["reviewer_id"] == REVIEWER_USERNAME


@pytest.mark.parametrize(
    ("action", "payload"),
    [
        ("approve", {"reviewer_id": "hr-1"}),
        ("reject", {"reviewer_id": "hr-1", "reason": "duplicate"}),
        (
            "edit",
            {"reviewer_id": "hr-1", "new_content": {"title": "T"}, "reason": "typo"},
        ),
    ],
)
def test_reviewer_id_in_the_body_is_rejected_not_ignored(
    action: str,
    payload: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``reviewer_id`` must be GONE from the request models, not merely unused.

    The models are ``extra="forbid"``, so a body still carrying it fails validation
    (422) — which proves the field was removed. Silently ignoring it would leave every
    existing caller believing it had named the reviewer.
    """
    session = FakeSession()
    client = make_client(session)
    canonical_id = uuid.uuid4()
    # A mock that would succeed, so a failure here reads "200, expected 422" — i.e. the
    # route accepted a caller-named reviewer — rather than a serialization crash.
    mock = AsyncMock(
        return_value=FakeCanonical(
            canonical_id=canonical_id,
            cluster_id=uuid.uuid4(),
            version=1,
            status=CanonicalStatus.DRAFT,
        )
    )
    monkeypatch.setattr(jd_bank.service, action, mock)

    resp = client.post(f"/jd-bank/review/{canonical_id}/{action}", json=payload)

    assert resp.status_code == 422
    mock.assert_not_awaited()
    session.commit.assert_not_awaited()


def test_override_reviewer_from_the_body_never_reaches_the_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The subtle one: ``overrides[].reviewer`` is a SECOND caller-supplied actor.

    ``service.review.override`` writes ``actor=override.reviewer`` to the audit log, so
    deleting the top-level ``reviewer_id`` alone would leave the forgery open — a caller
    could still record "approved-by anyone" against a waived gate. Whether the route
    rejects the field or overwrites it is its choice; what may never happen is the
    caller's string reaching the service.

    A GUARD, not a driver: it also passes today (the whole body is rejected because
    ``reviewer_id`` is missing). The test that forces the shape is
    :func:`test_every_override_is_stamped_with_the_authenticated_reviewer` — it is RED.
    """
    session = FakeSession()
    client = make_client(session)
    canonical_id = uuid.uuid4()
    mock = AsyncMock(
        return_value=FakeCanonical(
            canonical_id=canonical_id,
            cluster_id=uuid.uuid4(),
            version=2,
            status=CanonicalStatus.PUBLISHED,
        )
    )
    monkeypatch.setattr(jd_bank.service, "approve", mock)

    resp = client.post(
        f"/jd-bank/review/{canonical_id}/approve",
        json={
            "overrides": [
                {"gate_id": "SFU-GATE", "reviewer": "mallory", "reason": "waived"}
            ]
        },
    )

    reviewers = [
        override.reviewer
        for override in (mock.await_args.kwargs["overrides"] if mock.await_args else [])
    ]
    assert "mallory" not in reviewers, (
        "a caller-supplied override reviewer reached the service and would be written "
        "to the audit log as the actor who waived the gate"
    )
    assert resp.status_code == 422 or reviewers == [REVIEWER_USERNAME]


def test_every_override_is_stamped_with_the_authenticated_reviewer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The positive half: a body names only the gate and the written reason, and the
    route stamps the session identity onto each override — the way ``ui.py`` already
    does (``_parse_overrides(pairs, reviewer_id=actor.cas_username)``)."""
    session = FakeSession()
    client = make_client(session)
    canonical_id = uuid.uuid4()
    mock = AsyncMock(
        return_value=FakeCanonical(
            canonical_id=canonical_id,
            cluster_id=uuid.uuid4(),
            version=2,
            status=CanonicalStatus.PUBLISHED,
        )
    )
    monkeypatch.setattr(jd_bank.service, "approve", mock)

    resp = client.post(
        f"/jd-bank/review/{canonical_id}/approve",
        json={
            "overrides": [
                {"gate_id": "SFU-ONE", "reason": "waived for pilot"},
                {"gate_id": "SFU-TWO", "reason": "director sign-off attached"},
            ]
        },
    )

    assert resp.status_code == 200
    assert mock.await_args.kwargs["overrides"] == [
        GateOverride(
            gate_id="SFU-ONE", reviewer=REVIEWER_USERNAME, reason="waived for pilot"
        ),
        GateOverride(
            gate_id="SFU-TWO",
            reviewer=REVIEWER_USERNAME,
            reason="director sign-off attached",
        ),
    ]


# --- P0.1a: the regression that proves the breach is closed --------------------------


def test_unauthenticated_approve_of_a_gate_clean_draft_does_not_publish(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """**The test that would have caught the original defect.**

    With CAS on and no session, ``POST /jd-bank/review/{id}/approve`` used to reach the
    review service and be refused only by *business* rules — so against a gate-clean
    DRAFT (exactly what ``service.approve`` is mocked to publish here) an anonymous
    caller would have published a canonical JD, breaching NN #1's human-approval
    requirement and writing a forged actor into the audit log.

    401, and the service is never called: the refusal happens in the gate, before any
    publish decision is even considered.
    """
    session = FakeSession()
    client = make_anonymous_client(session)
    canonical_id = uuid.uuid4()
    would_publish = AsyncMock(
        return_value=FakeCanonical(
            canonical_id=canonical_id,
            cluster_id=uuid.uuid4(),
            version=1,
            status=CanonicalStatus.PUBLISHED,
        )
    )
    monkeypatch.setattr(jd_bank.service, "approve", would_publish)

    resp = client.post(f"/jd-bank/review/{canonical_id}/approve", json={})

    assert resp.status_code == 401, (
        "an unauthenticated approve must be refused with 401 — not redirected (this is "
        "a JSON route) and not merely turned away by a business rule"
    )
    would_publish.assert_not_awaited()
    session.commit.assert_not_awaited()

"""Unit — the review service's value objects + typed error surface (Phase 4.4b).

Pure, no DB: the DB invariants (transitions / append-only audit /
no-publish-while-blocking
/ override-needs-reason / re-validate-on-approve) are pinned by the integration suite
(``tests/integration/test_review_service.py``). Here we pin the plumbing those tests
lean
on: the errors are a typed hierarchy, the value objects are frozen and carry NO approval
field, and — structurally — a reviewer waiver cannot exist without a written reason
(CLAUDE.md non-negotiable #1), which the service reuses rather than re-checks.
"""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from pydantic import ValidationError

from src.jd_bank.db.models import CanonicalStatus
from src.jd_bank.review import (
    CanonicalNotFoundError,
    GateOverrideError,
    IllegalTransitionError,
    MissingReasonError,
    NotApprovableError,
    ReviewError,
    ReviewPacket,
    ReviewQueueItem,
)
from src.jd_core.models.quality import GateOverride


def test_a_reviewer_waiver_cannot_exist_without_a_written_reason() -> None:
    """Acceptance #2 (structural half): a ``GateOverride`` — what a reviewer hands to
    ``approve`` — is unrepresentable without a written reason and a named reviewer
    (CLAUDE.md #1). The service reuses this structural guarantee; it does not add a
    second, weaker path."""
    GateOverride(
        gate_id="SFU-APPROVE-EDI-FOOTER", reviewer="hr", reason="restored later"
    )
    for bad in ("", "   "):
        with pytest.raises(ValidationError):
            GateOverride(gate_id="SFU-APPROVE-EDI-FOOTER", reviewer="hr", reason=bad)
        with pytest.raises(ValidationError):
            GateOverride(gate_id="SFU-APPROVE-EDI-FOOTER", reviewer=bad, reason="x")


def test_every_review_error_is_a_typed_review_error() -> None:
    """Every operation-level failure is a ``ReviewError`` (callers can catch the base),
    and each concrete cause is its own subclass (callers can discriminate)."""
    for cls in (
        CanonicalNotFoundError,
        IllegalTransitionError,
        NotApprovableError,
        MissingReasonError,
    ):
        assert issubclass(cls, ReviewError)
    # The override checker's error stays jd_core's, re-exported through ONE surface — an
    # unreasoned/illegal waiver is not a ReviewError subclass; it is the gate policy's.
    assert not issubclass(GateOverrideError, ReviewError)


def test_the_value_objects_are_frozen_and_forbid_extras() -> None:
    item = ReviewQueueItem(
        canonical_id=uuid.uuid4(),
        cluster_id=uuid.uuid4(),
        version=1,
        status=CanonicalStatus.DRAFT,
        title="Analyst",
        created_at=dt.datetime.now(dt.UTC),
    )
    with pytest.raises(ValidationError):
        item.title = "changed"  # type: ignore[misc]  # frozen
    with pytest.raises(ValidationError):
        ReviewQueueItem(
            canonical_id=uuid.uuid4(),
            cluster_id=uuid.uuid4(),
            version=1,
            status=CanonicalStatus.DRAFT,
            title="Analyst",
            created_at=dt.datetime.now(dt.UTC),
            approved=True,  # type: ignore[call-arg]  # no approval field on a read view
        )


def test_the_queue_item_has_no_approval_field() -> None:
    """NN #1: approval is a property of the DB row's status, never of a transport
    object. The queue item's decision-ish fields are DISPLAY roll-up only, clearly named
    ``stored_*``."""
    fields = set(ReviewQueueItem.model_fields)
    assert "approved" not in fields
    assert "stored_approvable" in fields  # display only
    assert "approved" not in set(ReviewPacket.model_fields)

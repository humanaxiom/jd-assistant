"""Phase-4.4b review SERVICE — the human-approval spine over DRAFT canonical JDs.

The consumer half of the review queue (the producer is 4.4a; routes are 4.4c; the UI is
4.4d). Lists the DRAFT ``canonical_jds`` awaiting review, assembles a reviewer packet
with a FRESHLY recomputed gate decision (validator-as-oracle, NN #3), and applies the
four reviewer decisions — approve / reject / edit / override — each as a status
transition + a ``review_actions`` row + an append-only ``audit_log`` row.

**Nothing publishes unless the gate decision permits it** (NN #1): :func:`approve` is
the only publish path and refuses a draft any gate still blocks. Overrides require a
written reason (reused from :func:`~src.jd_core.quality.gates.apply_overrides`). The
caller owns the transaction.
"""

from src.jd_bank.review.models import (
    CanonicalNotFoundError,
    GateOverrideError,
    IllegalTransitionError,
    MissingReasonError,
    NotApprovableError,
    RelatedRole,
    ReviewError,
    ReviewPacket,
    ReviewQueueItem,
    StructuralContext,
    VersionRef,
)
from src.jd_bank.review.service import (
    approve,
    edit,
    get_review_packet,
    get_structural_context,
    get_version_diff,
    list_review_queue,
    reject,
)

__all__ = [
    "CanonicalNotFoundError",
    "GateOverrideError",
    "IllegalTransitionError",
    "MissingReasonError",
    "NotApprovableError",
    "RelatedRole",
    "ReviewError",
    "ReviewPacket",
    "ReviewQueueItem",
    "StructuralContext",
    "VersionRef",
    "approve",
    "edit",
    "get_review_packet",
    "get_structural_context",
    "get_version_diff",
    "list_review_queue",
    "reject",
]

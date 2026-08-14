"""Value objects + typed errors for the Phase-4.4b review service.

The review service (:mod:`src.jd_bank.review.service`) is the consumer half of the
review queue: it lists the DRAFT ``canonical_jds`` the 4.4a producer persisted,
assembles
a reviewer packet, and applies the four reviewer decisions. This module holds the two
frozen, ``extra="forbid"`` value objects it returns and the typed error hierarchy it
raises.

**No approval lives on a value object.** ``approved`` is a property of the *decision*
and
of the persisted ``canonical_jds`` row (its ``status``), never of a transport object — a
:class:`ReviewQueueItem` / :class:`ReviewPacket` is a read view, not a place a JD could
be
declared published (CLAUDE.md non-negotiable #1). The queue item's ``stored_*`` fields
are
the DISPLAY roll-up copied from ``change_log`` for triage; the authority is always the
FRESH :class:`~src.jd_core.models.quality.GateDecision` on the packet, recomputed from
the
canonical's current content (validator-as-oracle, NN #3).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict

# Re-exported so callers waive gates through ONE error surface: the override checker
# lives in jd_core and its error is part of this service's contract.
from src.jd_bank.db.models import CanonicalStatus
from src.jd_core.models.quality import GateDecision, JDGrade, JDQualityIssue
from src.jd_core.quality import GateOverrideError

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
]


# --- typed errors --------------------------------------------------------------------


class ReviewError(RuntimeError):
    """Base of every review-service error. A reviewer operation raises one of the
    subclasses below; it never silently no-ops (CLAUDE.md #1 — a decision is recorded or
    it is refused, never quietly dropped)."""


class CanonicalNotFoundError(ReviewError):
    """No canonical JD exists for the given id — an operation on a missing row."""

    def __init__(self, canonical_id: UUID) -> None:
        self.canonical_id = canonical_id
        super().__init__(f"canonical JD {canonical_id} not found")


class IllegalTransitionError(ReviewError):
    """The canonical is not a live DRAFT, so this transition is not legal.

    Approving / rejecting / editing a canonical a reviewer has already
    published or archived is refused — there is no double-publish and no
    re-opening of a settled decision (that is a later task, recorded not built).
    """

    def __init__(
        self, canonical_id: UUID, status: CanonicalStatus, action: str
    ) -> None:
        self.canonical_id = canonical_id
        self.status = status
        self.action = action
        super().__init__(
            f"cannot {action} canonical JD {canonical_id}: its status is "
            f"{status.value!r}, not a live draft"
        )


class NotApprovableError(ReviewError):
    """``approve`` was called on a draft whose gate decision does not permit it.

    The gates still block (and were not all overridden with a written reason), so
    publishing is refused and NOTHING is written: the row stays DRAFT, no APPROVE
    action, no publish audit (CLAUDE.md #1 — the ONLY publish path is a PERMITTED
    approve). ``decision`` carries the blocking gates for the caller to surface.
    """

    def __init__(self, canonical_id: UUID, decision: GateDecision) -> None:
        self.canonical_id = canonical_id
        self.decision = decision
        blocked = [reason.gate_id for reason in decision.blocking]
        super().__init__(
            f"canonical JD {canonical_id} cannot be approved: {len(blocked)} gate(s) "
            f"still block it ({blocked}); publish nothing"
        )


class MissingReasonError(ReviewError):
    """A decision that must carry a written reason was given a blank one.

    A rejection and an edit are recorded decisions; a blank reason is not a
    reason (mirrors the override rule — the reason IS the record, NN #6).
    """

    def __init__(self, action: str) -> None:
        self.action = action
        super().__init__(
            f"a {action} requires a written reason; a blank reason is refused"
        )


# --- value objects -------------------------------------------------------------------


class ReviewQueueItem(BaseModel):
    """One draft awaiting review, as a triage label — never the full JD.

    The ``stored_*`` fields are the DISPLAY roll-up read from the draft's
    ``change_log`` (what the producer / a prior edit recorded), used only to order and
    label the queue. They are NOT the approval authority: :func:`get_review_packet`
    recomputes a FRESH decision from the current content before a reviewer acts
    (validator-as-oracle, NN #3), so a stale stored roll-up can never let a blocked
    draft be approved.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    canonical_id: UUID
    cluster_id: UUID
    version: int
    status: CanonicalStatus
    title: str
    #: Display roll-up from ``change_log`` — for triage/ordering only, not the
    # authority.
    stored_score: float | None = None
    stored_grade: JDGrade | None = None
    stored_approvable: bool | None = None
    stored_blocking_gate_count: int = 0
    created_at: datetime


class ReviewPacket(BaseModel):
    """Everything a reviewer needs to decide on one canonical draft.

    Carries the draft ``content`` and the ``change_log`` provenance packet (the 4.3
    diff, the merge provenance, the removed-content log, the advisory audit) PLUS a
    FRESHLY recomputed :class:`~src.jd_core.models.quality.GateDecision`, score, grade
    and
    issues. The fresh decision — not the stored roll-up — is the authority a reviewer
    and
    :func:`approve` act on (NN #3).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    canonical_id: UUID
    cluster_id: UUID
    version: int
    status: CanonicalStatus
    content: dict[str, Any]
    change_log: dict[str, Any]
    #: FRESHLY recomputed from ``content`` — the approval authority (NN #3).
    decision: GateDecision
    score: float
    grade: JDGrade
    issues: tuple[JDQualityIssue, ...] = ()


# --- structural context (Phase 8.3b) --------------------------------------------------


class VersionRef(BaseModel):
    """One version of this role's cluster, for the versions tree. ``is_current`` marks
    the canonical the reviewer is looking at, so the tree can highlight it without the
    template re-deriving which one that is."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    canonical_id: UUID
    version: int
    status: CanonicalStatus
    is_current: bool


class RelatedRole(BaseModel):
    """One role that Tier-3 dedup recorded as a same-role PAIR with this one, and that
    clustering deliberately did **not** merge into it.

    ⚠ **Read that twice, because "related" understates what this is.** A cross-cluster
    ``ROLE_EQUIVALENT`` edge exists exactly when a pair scored at or above the Tier-3
    pair bar (``role_equiv_threshold``, 0.5) but **below the merge bar**
    (``cluster_role_equiv_min``, 0.75 — HR-162). Measured over the live archive: of
    32,816 cross-cluster Tier-3 edges, **zero** reach 0.75. The rulebook states the
    design — *"Tier-3 edges are pairwise, clustering is transitive, so the bar to MERGE
    must be higher than the bar to record a single same-role pair"* — so these are not
    incidental neighbours, they are **the near-misses the clustering step ruled on**.
    Surfacing them shows the reviewer a decision boundary they could not otherwise see.

    **No score is carried, on purpose.** Role similarity on this corpus was measured to
    have unrelated roles outscoring true twins, so a number here would be a false
    precision. ``connecting_documents`` is a COUNT of source documents linking the two
    roles — a fact about the archive, not a similarity — and the list is ranked, never
    scored.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    cluster_id: UUID
    #: The current canonical of that cluster, when it has one — the link target.
    #: ``None`` leaves the row unlinked rather than pointing at a 404.
    canonical_id: UUID | None
    title: str
    status: CanonicalStatus | None
    #: How many source documents connect the two roles. A count, never a score.
    connecting_documents: int


class StructuralContext(BaseModel):
    """Where one draft sits in the corpus: its cluster's version history and the roles
    clustering considered merging with it. Read-only and advisory — it changes no
    verdict (NN #1)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    cluster_id: UUID
    versions: tuple[VersionRef, ...]
    related: tuple[RelatedRole, ...]

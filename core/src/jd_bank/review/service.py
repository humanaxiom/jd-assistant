"""The Phase-4.4b review SERVICE — the human-approval spine (domain layer, no HTTP).

The consumer half of the review queue. Over the DRAFT ``canonical_jds`` rows the 4.4a
producer persists, it lists the queue, assembles a reviewer packet, and applies the four
reviewer decisions — **approve / reject / edit / override** — each writing the
``canonical_jds`` status transition + a ``review_actions`` row + an **append-only**
``audit_log`` row. NO HTTP (routes are 4.4c; UI is 4.4d).

**The invariant spine (this module's whole reason to exist):**

* **NN #1 — nothing publishes unless the gate decision PERMITS it.** :func:`approve`
  RE-VALIDATES the canonical's CURRENT content, runs
  :func:`~src.jd_core.quality.gates.evaluate_gates` then
  :func:`~src.jd_core.quality.gates.apply_overrides`, and sets ``status=PUBLISHED`` ONLY
  when the resulting decision is ``approved``. Otherwise it raises
  :class:`~src.jd_bank.review.models.NotApprovableError` and publishes NOTHING (the row
  stays DRAFT, no APPROVE action, no publish audit). This is the ONLY publish path.
* **Validator-as-oracle on CURRENT content (NN #3).** :func:`approve` and :func:`edit`
  reconstruct :class:`~src.jd_core.models.parsed_jd.SFUJobDescription` from ``content``,
  flatten via the SHARED :func:`~src.jd_bank.jd_text.flatten_jd`, and recompute
  issues/score/grade/decision. The stored ``change_log`` roll-up is DISPLAY only — a
  reviewer edit could have reintroduced a blocker, and a stale stored decision would let
  it through.
* **An override REQUIRES a written reason (NN #1).** :func:`apply_overrides` is reused
  as-is — it raises :class:`~src.jd_core.quality.GateOverrideError` on an unreasoned
  override, a non-overridable gate, a not-currently-blocking gate, or a double override.
  Each applied override is persisted as its own ``review_actions`` row with
  ``action=OVERRIDE`` and the NON-NULL reason, and each waiver is audited.
* **Append-only audit (NN #6).** Every decision writes the ``audit_log`` rows it should
  and NEVER updates/deletes one. Payloads carry ids/counts/gate-ids/reasons — never JD
  prose / incumbent PII.
* **Legal transitions only.** Every operation acts only on a live DRAFT; a missing id,
  or a canonical a reviewer has already published/archived, raises a typed error — never
  a silent no-op or a double-publish.

**The caller owns the transaction.** Like the 4.4a producer and the ingest driver, these
operations ``flush`` but do not ``commit`` — the caller commits (or rolls back).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.jd_bank.db.models import (
    AuditLog,
    CanonicalJD,
    CanonicalStatus,
    ReviewAction,
    ReviewActionKind,
)
from src.jd_bank.jd_text import flatten_jd
from src.jd_bank.review.models import (
    CanonicalNotFoundError,
    IllegalTransitionError,
    MissingReasonError,
    NotApprovableError,
    RelatedRole,
    ReviewPacket,
    ReviewQueueItem,
    StructuralContext,
    VersionRef,
)
from src.jd_core.bank.version_diff import VersionDiff, build_version_diff
from src.jd_core.models.parsed_jd import SFUJobDescription
from src.jd_core.models.quality import (
    GateDecision,
    GateOverride,
    JDGrade,
    JDQualityIssue,
)
from src.jd_core.quality.gates import apply_overrides, evaluate_gates
from src.jd_core.quality.scoring import score_issues
from src.jd_core.quality.validators import evaluate_jd_rules, template_of_content
from src.jd_core.rules import Rules, get_rules

__all__ = [
    "approve",
    "edit",
    "get_review_packet",
    "get_structural_context",
    "get_version_diff",
    "list_review_queue",
    "reject",
]


# --- validator-as-oracle: recompute the decision from CURRENT content (NN #3) --------


def _recompute(
    content: dict[str, Any], rules: Rules
) -> tuple[list[JDQualityIssue], float, JDGrade, GateDecision]:
    """Re-validate a canonical's ``content`` from scratch: reconstruct the parsed JD,
    flatten it through the SHARED flattener, run the deterministic validator, score it,
    and evaluate the gates. This — never the stored ``change_log`` roll-up — is the
    authority every approve/edit acts on (NN #3): a reviewer edit could have
    reintroduced a blocker, and a stale stored decision would let it through."""
    jd = SFUJobDescription.model_validate(content)
    issues = evaluate_jd_rules(jd, flatten_jd(jd), rules=rules)
    score, grade = score_issues(issues, scoring=rules.scoring)
    decision = evaluate_gates(issues, score, grade, gates=rules.gates)
    return issues, score, grade, decision


def _validator_rollup(
    issues: Sequence[JDQualityIssue],
    score: float,
    grade: JDGrade,
    decision: GateDecision,
    rules_version: str,
) -> dict[str, Any]:
    """The freshly-recomputed roll-up stored back into ``change_log["validator"]`` (same
    shape the 4.4a producer writes) so a published/edited row's DISPLAY roll-up matches
    the decision the service actually acted on. JSON-safe."""
    return {
        "score": score,
        "grade": grade,
        "issues": [issue.model_dump(mode="json") for issue in issues],
        "gate_decision": decision.model_dump(mode="json"),
        "rules_version": rules_version,
    }


# --- lookups: legal-transition + latest-version (the 4.4a multi-version fix) ----------


async def _get_for_update(session: AsyncSession, canonical_id: UUID) -> CanonicalJD:
    """The canonical row locked ``FOR UPDATE`` (so two concurrent reviewers cannot
    double-publish the same draft). Raises :class:`CanonicalNotFoundError` if absent."""
    canonical = await session.get(CanonicalJD, canonical_id, with_for_update=True)
    if canonical is None:
        raise CanonicalNotFoundError(canonical_id)
    return canonical


def _require_live_draft(canonical: CanonicalJD, *, action: str) -> None:
    """An approve/reject decision acts only on a live DRAFT. Approving or rejecting a
    canonical already published or archived is refused (no double-publish, no re-opening
    a settled decision)."""
    if canonical.status is not CanonicalStatus.DRAFT:
        raise IllegalTransitionError(canonical.id, canonical.status, action)


def _require_editable(canonical: CanonicalJD, *, action: str) -> None:
    """An EDIT may act on a live DRAFT **or on the PUBLISHED version** — but never on an
    ARCHIVED one.

    Publishing is a settled decision; the CONTENT is not frozen for all time. An
    approved role still needs corrections (the case that surfaced this: HR assigning
    an APSA grade to an already-approved harmonized role), and refusing them pushes
    that work outside the system — precisely what the audit trail exists to prevent.
    The edit is still not a mutation of the published row and still cannot publish:
    it mints a new DRAFT for a reviewer to approve (NN #1).

    ARCHIVED stays refused. It means rejected or superseded — a settled row kept for
    provenance, and editing one would fork a new version off dead history.
    """
    if canonical.status is CanonicalStatus.ARCHIVED:
        raise IllegalTransitionError(canonical.id, canonical.status, action)


async def _next_version(session: AsyncSession, cluster_id: UUID) -> int:
    """The next canonical version for a cluster: ``max(version) + 1``. Robust to a prior
    edit having already minted a v2 (the ``order_by(version desc)`` semantics the 4.4a
    follow-up asked for — read the NEWEST, never a stale v1)."""
    highest = await session.scalar(
        select(func.max(CanonicalJD.version)).where(
            CanonicalJD.cluster_id == cluster_id
        )
    )
    return int(highest or 0) + 1


# --- list the queue -------------------------------------------------------------------


def _queue_item(canonical: CanonicalJD) -> ReviewQueueItem:
    """A triage label for one draft — the stored DISPLAY roll-up only, never a fresh
    decision (that is :func:`get_review_packet`'s job)."""
    validator = (canonical.change_log or {}).get("validator") or {}
    decision = validator.get("gate_decision") or {}
    approvable = decision.get("approved") if "approved" in decision else None
    blocking = decision.get("blocking") or []
    return ReviewQueueItem(
        canonical_id=canonical.id,
        cluster_id=canonical.cluster_id,
        version=canonical.version,
        status=canonical.status,
        title=str((canonical.content or {}).get("title") or ""),
        # The FORM, read from the draft's own content by the one separator the whole
        # system uses (CUPE Phase D) — never from the cluster row or a stored label,
        # which could disagree with what the reviewer is about to read.
        template=template_of_content(canonical.content),
        stored_score=validator.get("score"),
        stored_grade=validator.get("grade"),
        stored_approvable=approvable,
        stored_blocking_gate_count=len(blocking),
        created_at=canonical.created_at,
    )


async def list_review_queue(
    session: AsyncSession, *, limit: int | None = None
) -> tuple[ReviewQueueItem, ...]:
    """The live DRAFT canonicals needing eyes, needs-eyes-first.

    Only DRAFT rows appear (a published/archived canonical is off the queue). Ordered so
    the drafts whose STORED decision is blocked (or unknown) come first, then oldest
    first — a deterministic, triage-friendly order. ``limit`` caps the returned count
    AFTER ordering. The item carries labels/counts only; the full draft is fetched per
    canonical via :func:`get_review_packet`."""
    rows = (
        await session.scalars(
            select(CanonicalJD)
            .where(CanonicalJD.status == CanonicalStatus.DRAFT)
            .order_by(CanonicalJD.created_at.asc(), CanonicalJD.id.asc())
        )
    ).all()
    items = [_queue_item(row) for row in rows]
    # Stable sort: an approvable-looking draft (stored_approvable is True) sinks below
    # the
    # ones still blocked or unknown; created_at breaks the tie. A stable sort preserves
    # the SQL created_at/id order within each bucket.
    items.sort(key=lambda item: (item.stored_approvable is True, item.created_at))
    if limit is not None:
        items = items[:limit]
    return tuple(items)


# --- the reviewer packet --------------------------------------------------------------


async def get_review_packet(
    session: AsyncSession, canonical_id: UUID, *, rules: Rules | None = None
) -> ReviewPacket | None:
    """The full reviewer packet for one canonical: its ``content`` + ``change_log``
    provenance + a FRESHLY recomputed :class:`GateDecision` (validator-as-oracle — the
    stored roll-up is not surfaced as the authority). ``None`` if the id is unknown."""
    rulebook = rules if rules is not None else get_rules()
    canonical = await session.get(CanonicalJD, canonical_id)
    if canonical is None:
        return None
    issues, score, grade, decision = _recompute(canonical.content, rulebook)
    return ReviewPacket(
        canonical_id=canonical.id,
        cluster_id=canonical.cluster_id,
        version=canonical.version,
        status=canonical.status,
        content=canonical.content,
        change_log=canonical.change_log,
        decision=decision,
        score=score,
        grade=grade,
        issues=tuple(issues),
    )


# --- version diff (draft vs last-approved) --------------------------------------------


async def get_version_diff(
    session: AsyncSession, canonical_id: UUID
) -> VersionDiff | None:
    """A section-by-section diff of one canonical against the LAST APPROVED version of
    the same cluster — "what changed since this role was last approved?".

    Returns ``None`` when the id is unknown OR the cluster has no earlier PUBLISHED
    version to compare against (the common first-review case — the caller shows "no
    prior approved version"). "Last approved" is the highest-version ``PUBLISHED``
    canonical with a lower version than this one, so an in-flight edit (a v2 DRAFT)
    diffs against the v1 that was approved. Read-only; judges nothing (NN #1)."""
    current = await session.get(CanonicalJD, canonical_id)
    if current is None:
        return None
    prior = await session.scalar(
        select(CanonicalJD)
        .where(
            CanonicalJD.cluster_id == current.cluster_id,
            CanonicalJD.status == CanonicalStatus.PUBLISHED,
            CanonicalJD.version < current.version,
        )
        .order_by(CanonicalJD.version.desc())
        .limit(1)
    )
    if prior is None:
        return None
    return build_version_diff(
        SFUJobDescription.model_validate(prior.content),
        SFUJobDescription.model_validate(current.content),
    )


# --- structural context (Phase 8.3b) --------------------------------------------------

#: How many related roles the sidebar lists. The ONLY number in the feature — a display
#: cap, not a similarity cutoff, which is why it earns no register entry. A threshold on
#: the edge score WOULD earn one (and would be a false precision besides: role
#: similarity on this corpus has unrelated roles outscoring true twins).
_RELATED_ROLE_LIMIT = 8

#: The related-roles lookup, as SQL rather than ORM constructs.
#:
#: ``clusters.members`` is a JSONB array of ``{"source_id": …, "filename": …}`` objects,
#: so every membership test needs ``jsonb_array_elements``, and a Tier-3 edge is stored
#: **oriented** while being undirected in intent — so both endpoint pairings must be
#: considered or the list silently halves depending on which side the writer's total
#: order happened to put this cluster on. Expressing that through the ORM needs casts
#: and two self-joins on a table-valued function; this is the same statement, verified
#: against the live archive before it was written into the code (it returns the 4,602
#: directed cluster pairs the 8.3b measurements are quoted from).
#:
#: An edge with BOTH endpoints in this cluster is an intra-cluster edge; the join to
#: ``theirs`` (which excludes this cluster) drops it, which is the intended behaviour —
#: those edges are what built the cluster, not a relationship to something else.
_RELATED_ROLES_SQL = text("""
    WITH mine AS (
        SELECT (jsonb_array_elements(members) ->> 'source_id')::uuid AS src
        FROM clusters WHERE id = :cluster_id
    ),
    theirs AS (
        SELECT c.id AS cluster_id,
               (jsonb_array_elements(c.members) ->> 'source_id')::uuid AS src
        FROM clusters c WHERE c.id <> :cluster_id
    ),
    neighbours AS (
        SELECT DISTINCT CASE
                   WHEN e.source_a_id IN (SELECT src FROM mine) THEN e.source_b_id
                   ELSE e.source_a_id
               END AS other_src
        FROM dedup_edges e
        WHERE e.tier = 'ROLE_EQUIVALENT'
          AND (e.source_a_id IN (SELECT src FROM mine)
               OR e.source_b_id IN (SELECT src FROM mine))
    )
    SELECT t.cluster_id, count(DISTINCT n.other_src) AS connecting_documents
    FROM neighbours n JOIN theirs t ON t.src = n.other_src
    GROUP BY t.cluster_id
    ORDER BY connecting_documents DESC, t.cluster_id
    LIMIT :limit
    """)


async def get_structural_context(
    session: AsyncSession, canonical_id: UUID
) -> StructuralContext | None:
    """Where one canonical sits in the corpus: its cluster's version history, and the
    roles Tier-3 dedup paired it with that clustering did **not** merge in.

    Returns ``None`` for an unknown id. Read-only and advisory — it changes no verdict
    (NN #1) and carries no similarity score (see :class:`RelatedRole`).

    ⚠ **What "related" means here, precisely.** A cross-cluster ``ROLE_EQUIVALENT`` edge
    is a pair at or above the Tier-3 pair bar but **below the clustering merge bar**
    (``cluster_role_equiv_min``, HR-162) — measured live, **zero** of the 32,816
    cross-cluster edges reach it. So this list is the set of near-misses the clustering
    step ruled on, which is exactly what makes it worth a reviewer's attention.
    ``NEAR_DUPLICATE`` is deliberately NOT consulted: near-duplicates are clustered
    together by construction, and the whole archive yields **16** cross-cluster ones.
    """
    current = await session.get(CanonicalJD, canonical_id)
    if current is None:
        return None

    versions = [
        VersionRef(
            canonical_id=row.id,
            version=row.version,
            status=row.status,
            is_current=row.id == canonical_id,
        )
        for row in (
            await session.scalars(
                select(CanonicalJD)
                .where(CanonicalJD.cluster_id == current.cluster_id)
                .order_by(CanonicalJD.version)
            )
        ).all()
    ]

    return StructuralContext(
        cluster_id=current.cluster_id,
        versions=tuple(versions),
        related=await _related_roles(session, current.cluster_id),
    )


async def _related_roles(
    session: AsyncSession, cluster_id: UUID
) -> tuple[RelatedRole, ...]:
    """The other clusters joined to this one by a Tier-3 edge, most-connected first.

    Ranked by how many source documents connect the two roles, then by title so the
    order is total and the page is stable across reloads. **Never ranked by, and never
    showing, the edge score** — a similarity number the corpus cannot support.
    """
    rows = await session.execute(
        _RELATED_ROLES_SQL,
        {"cluster_id": str(cluster_id), "limit": _RELATED_ROLE_LIMIT},
    )
    counts: dict[UUID, int] = {row.cluster_id: row.connecting_documents for row in rows}
    if not counts:
        return ()

    # The CURRENT canonical of each related cluster — the link target. A cluster with no
    # canonical at all is still listed, unlinked, rather than dropped: its absence from
    # the list would be indistinguishable from "no relationship exists".
    latest: dict[UUID, CanonicalJD] = {}
    for row in (
        await session.scalars(
            select(CanonicalJD)
            .where(CanonicalJD.cluster_id.in_(counts))
            .order_by(CanonicalJD.cluster_id, CanonicalJD.version)
        )
    ).all():
        latest[row.cluster_id] = row

    related = [
        RelatedRole(
            cluster_id=other_id,
            canonical_id=canonical.id if canonical else None,
            title=(
                str(canonical.content.get("title") or "(untitled)")
                if canonical
                else "(no canonical JD yet)"
            ),
            status=canonical.status if canonical else None,
            connecting_documents=count,
        )
        for other_id, count in counts.items()
        for canonical in (latest.get(other_id),)
    ]
    related.sort(key=lambda r: (-r.connecting_documents, r.title))
    return tuple(related)


# --- approve (the ONLY publish path) --------------------------------------------------


async def approve(
    session: AsyncSession,
    canonical_id: UUID,
    *,
    reviewer_id: str,
    overrides: Sequence[GateOverride] = (),
    rules: Rules | None = None,
) -> CanonicalJD:
    """Publish a draft — but ONLY if the gate decision permits it (NN #1).

    Re-validates the CURRENT content, evaluates the gates, applies the reviewer's
    overrides, and sets ``status=PUBLISHED`` IFF the resulting decision is ``approved``.
    If any gate still blocks, raises :class:`NotApprovableError` and writes NOTHING.
    Each
    applied override is persisted as an ``OVERRIDE`` review action carrying its written
    reason, plus a waiver audit row; the publish itself writes an ``APPROVE`` review
    action + a publish audit row. Caller owns the transaction.

    Raises:
        CanonicalNotFoundError: no such canonical.
        IllegalTransitionError: the canonical is not a live DRAFT (no double-publish).
        GateOverrideError: an override is unreasoned / non-overridable / not blocking /
            doubled (from :func:`apply_overrides`) — publishes nothing.
        NotApprovableError: a gate still blocks after overrides — publishes nothing.
    """
    rulebook = rules if rules is not None else get_rules()
    canonical = await _get_for_update(session, canonical_id)
    _require_live_draft(canonical, action="approve")

    # Validator-as-oracle: the decision comes from the CURRENT content, never the stored
    # roll-up (NN #3). apply_overrides re-checks each written reason + overridability
    # and
    # raises GateOverrideError before anything is published (NN #1).
    issues, score, grade, decision = _recompute(canonical.content, rulebook)
    source_parts = {reason.gate_id: reason.source_part for reason in decision.blocking}
    permitted = apply_overrides(decision, overrides)
    if not permitted.approved:
        # A gate still blocks and was not overridden — publish NOTHING (NN #1).
        raise NotApprovableError(canonical_id, permitted)

    # PERMITTED — this is the one and only publish path.
    #
    # Retire any OTHER live published version of this cluster first. Editing a published
    # JD leaves it published (so the Bank keeps serving an approved JD while the update
    # is in review), which makes this the moment the old one retires. Without it the
    # cluster would carry two PUBLISHED rows and "the approved JD" would stop having a
    # single answer. Locked FOR UPDATE alongside the row being published so a concurrent
    # approve cannot interleave and leave both live.
    superseded = (
        await session.scalars(
            select(CanonicalJD)
            .where(
                CanonicalJD.cluster_id == canonical.cluster_id,
                CanonicalJD.status == CanonicalStatus.PUBLISHED,
                CanonicalJD.id != canonical.id,
            )
            .with_for_update()
        )
    ).all()
    for previous in superseded:
        previous.status = CanonicalStatus.ARCHIVED
        session.add(
            AuditLog(
                event_type="review.superseded",
                entity_type="canonical_jd",
                entity_id=previous.id,
                actor=reviewer_id,
                payload={
                    "cluster_id": str(canonical.cluster_id),
                    "version": previous.version,
                    "from_status": CanonicalStatus.PUBLISHED.value,
                    "to_status": CanonicalStatus.ARCHIVED.value,
                    "superseded_by_version": canonical.version,
                    "superseded_by_id": str(canonical.id),
                },
            )
        )

    canonical.status = CanonicalStatus.PUBLISHED
    canonical.change_log = {
        **(canonical.change_log or {}),
        "validator": _validator_rollup(
            issues, score, grade, permitted, rulebook.version
        ),
        "review": {
            "approved_by": reviewer_id,
            "override_count": len(permitted.overridden),
            "overridden_gate_ids": [ov.gate_id for ov in permitted.overridden],
        },
    }

    session.add(
        ReviewAction(
            canonical_jd_id=canonical.id,
            action=ReviewActionKind.APPROVE,
            reviewer_id=reviewer_id,
            payload={
                "score": score,
                "grade": grade,
                "override_count": len(permitted.overridden),
            },
        )
    )
    for override in permitted.overridden:
        session.add(
            ReviewAction(
                canonical_jd_id=canonical.id,
                action=ReviewActionKind.OVERRIDE,
                reviewer_id=override.reviewer,
                reason=override.reason,
                payload={
                    "gate_id": override.gate_id,
                    "source_part": source_parts.get(override.gate_id),
                },
            )
        )

    session.add(
        AuditLog(
            event_type="review.approved",
            entity_type="canonical_jd",
            entity_id=canonical.id,
            actor=reviewer_id,
            payload={
                "cluster_id": str(canonical.cluster_id),
                "version": canonical.version,
                "from_status": CanonicalStatus.DRAFT.value,
                "to_status": CanonicalStatus.PUBLISHED.value,
                "score": score,
                "grade": grade,
                "overridden_gate_ids": [ov.gate_id for ov in permitted.overridden],
            },
        )
    )
    for override in permitted.overridden:
        session.add(
            AuditLog(
                event_type="review.override",
                entity_type="canonical_jd",
                entity_id=canonical.id,
                actor=override.reviewer,
                payload={
                    "gate_id": override.gate_id,
                    "source_part": source_parts.get(override.gate_id),
                    # The reason IS the record (NN #6) — persisted, never elided.
                    "reason": override.reason,
                },
            )
        )
    await session.flush()
    return canonical


# --- reject ---------------------------------------------------------------------------


async def reject(
    session: AsyncSession,
    canonical_id: UUID,
    *,
    reviewer_id: str,
    reason: str,
) -> CanonicalJD:
    """Archive a draft a reviewer has turned down. A rejection is a recorded decision,
    so
    ``reason`` is mandatory — a blank reason raises :class:`MissingReasonError`. Writes
    a
    ``REJECT`` review action + an audit row; caller owns the transaction.

    Raises:
        MissingReasonError: ``reason`` is blank.
        CanonicalNotFoundError / IllegalTransitionError: as :func:`approve`.
    """
    if not reason or not reason.strip():
        raise MissingReasonError("reject")
    written = reason.strip()
    canonical = await _get_for_update(session, canonical_id)
    _require_live_draft(canonical, action="reject")

    canonical.status = CanonicalStatus.ARCHIVED
    session.add(
        ReviewAction(
            canonical_jd_id=canonical.id,
            action=ReviewActionKind.REJECT,
            reviewer_id=reviewer_id,
            reason=written,
            payload={},
        )
    )
    session.add(
        AuditLog(
            event_type="review.rejected",
            entity_type="canonical_jd",
            entity_id=canonical.id,
            actor=reviewer_id,
            payload={
                "cluster_id": str(canonical.cluster_id),
                "version": canonical.version,
                "from_status": CanonicalStatus.DRAFT.value,
                "to_status": CanonicalStatus.ARCHIVED.value,
                "reason": written,
            },
        )
    )
    await session.flush()
    return canonical


# --- edit (mint a new re-validated DRAFT version) -------------------------------------


async def edit(
    session: AsyncSession,
    canonical_id: UUID,
    *,
    reviewer_id: str,
    new_content: dict[str, Any],
    reason: str,
    rules: Rules | None = None,
) -> CanonicalJD:
    """Record a reviewer's edit as a NEW canonical version.

    Reconstructs + re-validates ``new_content`` (a malformed edit raises pydantic's
    ``ValidationError`` before anything is written), mints ``version = max+1`` as a
    fresh
    ``status=DRAFT`` row with a re-computed roll-up, and **archives the prior version**
    (the supersession is recorded, not deleted — append-only in spirit, and it takes the
    stale draft off the review queue while leaving it for provenance). The ``EDIT``
    review
    action lands on the NEW version, which is what marks that version a human artifact
    so
    the 4.4a producer's no-clobber leaves it alone. Writes the EDIT action + an audit
    row;
    caller owns the transaction. Returns the new version.

    Raises:
        MissingReasonError: ``reason`` is blank (an edit is a recorded decision).
        CanonicalNotFoundError / IllegalTransitionError: as :func:`approve`.
    """
    if not reason or not reason.strip():
        raise MissingReasonError("edit")
    written = reason.strip()
    rulebook = rules if rules is not None else get_rules()

    prior = await _get_for_update(session, canonical_id)
    _require_editable(prior, action="edit")
    was_published = prior.status is CanonicalStatus.PUBLISHED

    # Re-validate the edited content (validator-as-oracle) — a malformed edit fails
    # here.
    jd = SFUJobDescription.model_validate(new_content)
    content = jd.model_dump(mode="json")
    issues, score, grade, decision = _recompute(content, rulebook)

    new_version = await _next_version(session, prior.cluster_id)
    changed_sections = sorted(
        key
        for key in set(content) | set(prior.content or {})
        if content.get(key) != (prior.content or {}).get(key)
    )
    edited = CanonicalJD(
        cluster_id=prior.cluster_id,
        version=new_version,
        status=CanonicalStatus.DRAFT,
        content=content,
        source_document_ids=list(prior.source_document_ids or []),
        change_log={
            "validator": _validator_rollup(
                issues, score, grade, decision, rulebook.version
            ),
            "edit": {
                "from_version": prior.version,
                "from_status": prior.status.value,
                "reviewer_id": reviewer_id,
                "reason": written,
            },
        },
        validation_report_id=None,
    )
    session.add(edited)
    await session.flush()  # assign edited.id

    # Supersede the prior version — off the queue, kept for provenance. A PUBLISHED
    # prior is deliberately LEFT PUBLISHED: it is the approved JD the Bank is serving,
    # and archiving it here would leave the cluster with no live approved version for
    # the whole review window. It retires when its replacement is approved (`approve`).
    if not was_published:
        prior.status = CanonicalStatus.ARCHIVED

    session.add(
        # The EDIT action lands on the NEW version — that is what marks v2 a human
        # artifact so the 4.4a producer's no-clobber leaves the reviewer's edit alone.
        ReviewAction(
            canonical_jd_id=edited.id,
            action=ReviewActionKind.EDIT,
            reviewer_id=reviewer_id,
            reason=written,
            payload={
                "from_version": prior.version,
                "to_version": new_version,
                "changed_sections": changed_sections,
            },
        )
    )
    session.add(
        AuditLog(
            event_type="review.edited",
            entity_type="canonical_jd",
            entity_id=edited.id,
            actor=reviewer_id,
            payload={
                "cluster_id": str(prior.cluster_id),
                "from_version": prior.version,
                "to_version": new_version,
                "prior_status": CanonicalStatus.ARCHIVED.value,
                "reason": written,
                "changed_sections": changed_sections,
            },
        )
    )
    await session.flush()
    return edited

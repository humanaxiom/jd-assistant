"""Submit a composed draft into the review queue (Phase 5.6).

The one write path the JD Builder has. :func:`submit_composed_draft` persists an
author's finished draft as a DRAFT ``canonical_jds`` row so it enters the SAME
human-approval review queue the harmonized drafts flow through (the 4.4b service).
Nothing publishes here (NN #1): the row is ``status=DRAFT`` with no approval field;
only :func:`src.jd_bank.review.service.approve` — re-validating and gate-checking —
can ever publish it, composed or harmonized alike.

**Provenance.** A composed draft has no cluster from clustering, so it gets its own
synthetic singleton :class:`~src.jd_bank.db.models.Cluster` (``origin="composed"``,
no members) — ``canonical_jds.cluster_id`` is NOT NULL, and a per-submission cluster
keeps the lineage honest (this draft came from the Builder, not a role cluster). The
``change_log`` records ``origin="composed"`` + the validator roll-up (same shape the
producer/service write, so the queue's triage display works) + a human-readable
rendering for the review detail page. One append-only ``audit_log`` row is written.

**The caller owns the transaction** (like the producer and the review service): this
flushes but does not commit.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.jd_bank.db.models import AuditLog, CanonicalJD, CanonicalStatus, Cluster
from src.jd_bank.jd_text import flatten_jd
from src.jd_core.bank import render_sfu_jd_text
from src.jd_core.models.parsed_jd import SFUJobDescription
from src.jd_core.quality.gates import evaluate_gates
from src.jd_core.quality.scoring import score_issues
from src.jd_core.quality.validators import evaluate_jd_rules
from src.jd_core.rules import Rules, get_rules

#: What the Builder records as the origin of a composed draft — distinguishing it from
#: the harmonizer's ``origin``-less merged drafts in the change_log and the audit trail.
COMPOSED_ORIGIN = "composed"

#: A composed draft is version 1 (a reviewer edit, 4.4b, is what mints later versions).
_COMPOSED_VERSION = 1


async def submit_composed_draft(
    session: AsyncSession,
    jd: SFUJobDescription,
    *,
    author_id: str,
    rules: Rules | None = None,
) -> CanonicalJD:
    """Persist a composed ``SFUJobDescription`` as a DRAFT ``canonical_jds`` row in the
    review queue and return it. Flushes, does not commit (the caller owns the txn).

    Validator-as-oracle (NN #3): the stored roll-up is computed with the SAME flatten +
    validate + score + gate path the review service re-runs on approve, so the queue's
    triage display matches the decision the service will act on.
    """
    rulebook = rules if rules is not None else get_rules()
    author = author_id.strip() or "composer"

    issues = evaluate_jd_rules(jd, flatten_jd(jd), rules=rulebook)
    score, grade = score_issues(issues, scoring=rulebook.scoring)
    decision = evaluate_gates(issues, score, grade, gates=rulebook.gates)

    group = jd.employee_group
    cluster = Cluster(
        label=(jd.title or "Composed role")[:255],
        employee_group=str(group) if group is not None else None,
        level_band=None,
        members=[],
        constraint_metadata={"origin": COMPOSED_ORIGIN, "author": author},
    )
    session.add(cluster)
    await session.flush()  # assign cluster.id

    change_log: dict[str, Any] = {
        "origin": COMPOSED_ORIGIN,
        "author": author,
        # Display-only human rendering for the review detail page (the review UI reads
        # change_log["harmonization_diff"]["rendered_draft"]); the AUTHORITY is the
        # service's fresh re-validation of `content`, never this roll-up.
        "harmonization_diff": {
            "rendered_draft": render_sfu_jd_text(jd),
            "removed": [],
        },
        "validator": {
            "score": score,
            "grade": grade,
            "issues": [issue.model_dump(mode="json") for issue in issues],
            "gate_decision": decision.model_dump(mode="json"),
            "rules_version": rulebook.version,
        },
    }
    canonical = CanonicalJD(
        cluster_id=cluster.id,
        version=_COMPOSED_VERSION,
        status=CanonicalStatus.DRAFT,
        content=jd.model_dump(mode="json"),
        source_document_ids=[],  # composed — no source archive documents
        change_log=change_log,
        # validation_reports is parsed_jd-keyed; a composed draft has none, so the
        # roll-up lives in change_log["validator"] (as the producer does).
        validation_report_id=None,
    )
    session.add(canonical)
    await session.flush()  # assign canonical.id

    session.add(
        AuditLog(
            event_type="canonical_draft.composed",
            entity_type="canonical_jd",
            entity_id=canonical.id,
            actor=author,
            payload={
                "origin": COMPOSED_ORIGIN,
                "cluster_id": str(cluster.id),
                "version": _COMPOSED_VERSION,
                "status": CanonicalStatus.DRAFT.value,
                "score": score,
                "grade": grade,
                "approvable": decision.approved,
                "blocking_gates": [reason.gate_id for reason in decision.blocking],
            },
        )
    )
    await session.flush()
    return canonical

"""The Phase-4.4a canonical-draft PRODUCER runner.

Per run::

    run_clustering(session)                      # REUSE 3.5 — the JDFN+WJQ partition
        -> load_member_jds(clustered source_ids) # reconstruct each member JD
        -> per cluster: drop WJQ (COUNT it), JDFN-only
           -> merge_cluster (4.1)                # the deterministic grounded draft
           -> rewrite_merged_role (4.2a, best-effort)   # cleaner prose, anti-fab guard
           -> audit_quality (4.2b, best-effort/advisory)
           -> build_harmonization_diff (4.3) + validator + gate runner
           -> UPSERT clusters (keyed on the stable cluster_id) + persist/refresh a
              DRAFT canonical_jds row + append an audit_log row
        -> a CanonicalProducerResult (counts + stamps)

**The invariant-critical core** (the reviewer WILL hammer this):

* **DRAFT-ONLY** (NN #1): every ``canonical_jds`` row written is ``status=DRAFT``. The
  producer sets no approval field and never writes published/archived.
* **NO-CLOBBER** (highest-risk): before writing, the existing canonical is looked up. If
  it is not a DRAFT (published/archived) OR it has ANY ``review_actions`` row, it is a
  human artifact and is LEFT UNTOUCHED (counted ``skipped_reviewer_touched``). Only an
  untouched DRAFT may be refreshed — never overwritten, never cascade-deleted (the 3.5
  cascade-delete + 3.3 prune-deletes-data lessons).
* **IDEMPOTENT**: the ``clusters`` row is upserted on the content-derived ``cluster_id``
  (select-or-insert, never a blind insert); running twice yields the same rows (no dup
  clusters, no dup canonical versions).
* **APPEND-ONLY AUDIT** (NN #6): one ``audit_log`` row per persist/refresh and per skip;
  never an update/delete. Payload is counts/flags — NEVER incumbent PII.
* **BEST-EFFORT LLM**: a per-cluster rewrite/audit failure isolates + counts, never
  aborts the run and never loses the deterministic merge draft (rewrite failure -> fall
  back to the merge draft; audit is advisory -> omit on failure). ``client=None`` ->
  deterministic-only (merge draft persisted; rewrite/audit recorded as skipped).

**Persistence discipline** mirrors :mod:`src.jd_bank.ingest.driver`: the CALLER owns the
transaction and the commit; each cluster runs inside a ``begin_nested`` SAVEPOINT so a
per-cluster failure isolates that cluster and never corrupts the rest of the run.

``jd_core`` is never imported the other way round — the producer is ``jd_bank`` and it
drives ``jd_core`` (merge / diff / validator / gates) freely.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.jd_bank.canonical.models import CanonicalProducerResult
from src.jd_bank.cluster.models import ClusterRecord
from src.jd_bank.cluster.runner import run_clustering
from src.jd_bank.db.models import (
    AuditLog,
    CanonicalJD,
    CanonicalStatus,
    Cluster,
    ReviewAction,
)
from src.jd_bank.dedup.signals_load import load_member_jds

# Import — do NOT fork — the WJQ proxy the harmonize runner already established.
from src.jd_bank.harmonize.runner import is_wjq_member, member_has_frequency
from src.jd_bank.jd_text import flatten_jd
from src.jd_bank.llm.client import ChatClient
from src.jd_bank.quality.audit import audit_quality
from src.jd_bank.rewrite.harmonize import rewrite_merged_role
from src.jd_core.bank.change_log import build_harmonization_diff
from src.jd_core.bank.merge import merge_cluster
from src.jd_core.models.bank import (
    HarmonizationDiff,
    MergedRole,
    QualityAudit,
    RewrittenDraft,
)
from src.jd_core.models.parsed_jd import SFUJobDescription
from src.jd_core.models.quality import GateDecision, JDGrade, JDQualityIssue
from src.jd_core.quality.gates import evaluate_gates
from src.jd_core.quality.scoring import score_issues
from src.jd_core.quality.validators import evaluate_jd_rules
from src.jd_core.rules import Rules, get_rules

#: The ONLY status the producer ever writes — a draft a human still has to approve.
DRAFT: CanonicalStatus = CanonicalStatus.DRAFT

#: The single canonical version the producer maintains per cluster. A reviewer edit /
#: approval (4.4b) is what mints later versions; the producer only refreshes v1.
_PRODUCER_VERSION = 1


# --- pure: the no-clobber predicate --------------------------------------------------


def reviewer_touched(status: CanonicalStatus, review_action_count: int) -> bool:
    """Whether an existing canonical is a HUMAN artifact the producer must not touch.

    ``True`` iff it is no longer a DRAFT (a reviewer published/archived it) OR it has
    any ``review_actions`` row (a reviewer approved/rejected/edited/overrode it). Only
    an untouched DRAFT (``DRAFT`` + zero review actions) may be refreshed. Pure — the DB
    lookups are the caller's; this is the decision they feed."""
    return status is not DRAFT or review_action_count > 0


# --- pure: the reviewer packet (change_log JSONB) ------------------------------------


def build_change_log_packet(
    *,
    merged: MergedRole,
    diff: HarmonizationDiff,
    rewritten: RewrittenDraft | None,
    quality_audit: QualityAudit | None,
    issues: Sequence[JDQualityIssue],
    score: float,
    grade: JDGrade,
    gate_decision: GateDecision,
    rules_version: str,
    llm_enabled: bool,
    rewrite_failed: bool,
    audit_failed: bool,
) -> dict[str, Any]:
    """The self-contained reviewer packet stored in ``canonical_jds.change_log``.

    Round-trips to the 4.3 :class:`HarmonizationDiff`, the 4.1
    :class:`~src.jd_core.models.bank.MergeProvenance`, the optional 4.2a
    :class:`~src.jd_core.models.bank.AntiFabricationRecord`, the optional 4.2b
    :class:`QualityAudit`, and the validator roll-up (score / grade / issues +
    :class:`GateDecision`). ``validation_report_id`` stays NULL — ``validation_reports``
    is parsed_jd-keyed and a canonical is not a parsed_jd, so the roll-up lives HERE.

    Pure + JSON-safe (every value is ``model_dump(mode="json")``)."""
    return {
        "harmonization_diff": diff.model_dump(mode="json"),
        "merge_provenance": merged.provenance.model_dump(mode="json"),
        "anti_fabrication": (
            rewritten.anti_fabrication.model_dump(mode="json") if rewritten else None
        ),
        "quality_audit": (
            quality_audit.model_dump(mode="json") if quality_audit else None
        ),
        "validator": {
            "score": score,
            "grade": grade,
            "issues": [issue.model_dump(mode="json") for issue in issues],
            "gate_decision": gate_decision.model_dump(mode="json"),
            "rules_version": rules_version,
        },
        "pipeline": {
            "llm_enabled": llm_enabled,
            "rewrite_ran": rewritten is not None,
            "rewrite_failed": rewrite_failed,
            "audit_ran": quality_audit is not None,
            "audit_failed": audit_failed,
        },
    }


# --- per-cluster outcome (internal accumulator) --------------------------------------


@dataclass(slots=True)
class _Outcome:
    """What ONE JDFN cluster's processing did — accumulated by the caller only AFTER its
    SAVEPOINT releases, so an isolated failure never double-counts."""

    persisted: bool = False
    refreshed: bool = False
    skipped: bool = False
    rewrite_failed: bool = False
    audit_failed: bool = False


# --- LLM passes (best-effort) --------------------------------------------------------


async def _run_llm_passes(
    merged: MergedRole,
    *,
    client: ChatClient | None,
    rules: Rules,
    outcome: _Outcome,
) -> tuple[SFUJobDescription, RewrittenDraft | None, QualityAudit | None]:
    """Drive the 4.2a rewrite + 4.2b audit, best-effort.

    ``client=None`` -> the deterministic merge draft, no rewrite, no audit. Otherwise a
    rewrite is attempted (a failure falls back to the merge draft and sets
    ``rewrite_failed``), then the advisory audit is attempted on the CHOSEN draft (a
    failure omits it and sets ``audit_failed``). Neither failure ever aborts — the
    deterministic draft is never lost (mirrors hris ``evaluate_jd_quality`` +
    the embed runner's isolate-and-skip)."""
    if client is None:
        return merged.draft, None, None

    rewritten: RewrittenDraft | None = None
    try:
        rewritten = await rewrite_merged_role(merged, client=client, rules=rules)
        final_draft = rewritten.draft
    except Exception:  # noqa: BLE001 - a model failure isolates, never aborts the run
        outcome.rewrite_failed = True
        final_draft = merged.draft

    quality_audit: QualityAudit | None = None
    try:
        quality_audit = await audit_quality(final_draft, client=client, rules=rules)
    except Exception:  # noqa: BLE001 - the audit is advisory; drop it on failure
        outcome.audit_failed = True

    return final_draft, rewritten, quality_audit


# --- cluster snapshot (the clusters row) ---------------------------------------------


def _cluster_snapshot(
    record: ClusterRecord,
    *,
    jdfn_ids: Sequence[UUID],
    merged: MergedRole,
    wjq_excluded: int,
) -> dict[str, Any]:
    """The auditable ``clusters`` snapshot for a first insert: the JDFN members that fed
    the canonical, the harmonized employee group, and the cohesion metadata — counts /
    labels / filenames only (the class ``docs/cluster/`` commits), never JD prose.
    """
    filenames = {m.source_id: m.filename for m in record.members}
    group = merged.draft.employee_group
    return {
        "label": record.label,
        "employee_group": str(group) if group is not None else None,
        "members": [
            {"source_id": str(mid), "filename": filenames.get(mid)} for mid in jdfn_ids
        ],
        "constraint_metadata": {
            "constraint_violations": list(record.constraint_violations),
            "cross_department": record.cross_department,
            "cross_group": record.cross_group,
            "family_band_spread": record.family_band_spread,
            "bands": list(record.bands),
            "wjq_members_excluded": wjq_excluded,
        },
    }


# --- persist / refresh one cluster ---------------------------------------------------


async def _process_cluster(
    session: AsyncSession,
    record: ClusterRecord,
    jdfn_pairs: Sequence[tuple[UUID, SFUJobDescription]],
    *,
    wjq_excluded: int,
    client: ChatClient | None,
    rules: Rules,
) -> _Outcome:
    """Merge -> (best-effort LLM) -> validate -> upsert cluster + persist/refresh DRAFT
    + append audit_log, for ONE JDFN cluster. Runs inside the caller's SAVEPOINT.
    """
    outcome = _Outcome()
    cluster_id = record.cluster_id
    jdfn_ids = [mid for mid, _ in jdfn_pairs]
    jdfn_members = [jd for _, jd in jdfn_pairs]

    # 1. NO-CLOBBER — look up any existing canonical for this cluster FIRST.
    existing = await session.scalar(
        select(CanonicalJD).where(CanonicalJD.cluster_id == cluster_id)
    )
    if existing is not None:
        action_count = await session.scalar(
            select(func.count())
            .select_from(ReviewAction)
            .where(ReviewAction.canonical_jd_id == existing.id)
        )
        if reviewer_touched(existing.status, int(action_count or 0)):
            outcome.skipped = True
            session.add(
                AuditLog(
                    event_type="canonical_draft.skipped_reviewer_touched",
                    entity_type="canonical_jd",
                    entity_id=existing.id,
                    actor="producer",
                    payload={
                        "cluster_id": str(cluster_id),
                        "existing_status": existing.status.value,
                        "review_action_count": int(action_count or 0),
                        "reason": "reviewer_touched",
                    },
                )
            )
            return outcome

    # 2. The deterministic merge draft + the best-effort LLM passes.
    merged = merge_cluster(jdfn_members, rules=rules)
    final_draft, rewritten, quality_audit = await _run_llm_passes(
        merged, client=client, rules=rules, outcome=outcome
    )

    # 3. The validator roll-up on the FINAL draft (validator-as-oracle, NN #3).
    issues: list[JDQualityIssue] = evaluate_jd_rules(
        final_draft, flatten_jd(final_draft), rules=rules
    )
    score, grade = score_issues(issues, scoring=rules.scoring)
    gate_decision = evaluate_gates(issues, score, grade, gates=rules.gates)

    # 4. The 4.3 change-log + the reviewer packet.
    diff = build_harmonization_diff(
        merged, jdfn_members, rewrite=rewritten, rules=rules
    )
    change_log = build_change_log_packet(
        merged=merged,
        diff=diff,
        rewritten=rewritten,
        quality_audit=quality_audit,
        issues=issues,
        score=score,
        grade=grade,
        gate_decision=gate_decision,
        rules_version=rules.version,
        llm_enabled=client is not None,
        rewrite_failed=outcome.rewrite_failed,
        audit_failed=outcome.audit_failed,
    )
    content: dict[str, Any] = final_draft.model_dump(mode="json")
    source_document_ids: list[dict[str, Any]] = [
        {"source_id": str(mid)} for mid in jdfn_ids
    ]

    # 5. UPSERT the clusters row (select-or-insert on the STABLE content-derived id).
    cluster = await session.get(Cluster, cluster_id)
    if cluster is None:
        snapshot = _cluster_snapshot(
            record, jdfn_ids=jdfn_ids, merged=merged, wjq_excluded=wjq_excluded
        )
        cluster = Cluster(
            id=cluster_id,  # NOT the table's uuid4 default — the idempotency key.
            label=snapshot["label"],
            employee_group=snapshot["employee_group"],
            level_band=None,
            members=snapshot["members"],
            constraint_metadata=snapshot["constraint_metadata"],
        )
        session.add(cluster)
        await session.flush()

    # 6. Persist / refresh the DRAFT canonical.
    if existing is None:
        canonical = CanonicalJD(
            cluster_id=cluster_id,
            version=_PRODUCER_VERSION,
            status=DRAFT,
            content=content,
            source_document_ids=source_document_ids,
            change_log=change_log,
            validation_report_id=None,
        )
        session.add(canonical)
        await session.flush()
        outcome.persisted = True
        action = "persisted"
        canonical_id = canonical.id
    else:
        # An untouched DRAFT (the reviewer-touched case returned above): refresh IN
        # PLACE — no second version row. Reassigning a JSONB column marks it dirty, so
        # a refresh DOES emit an UPDATE (bumps ``updated_at``) even when byte-identical;
        # the CONTENT is unchanged and ``drafts_refreshed`` is the honest count —
        # idempotent in ROWS (no dup cluster/version), not a no-op write.
        existing.content = content
        existing.source_document_ids = source_document_ids
        existing.change_log = change_log
        existing.validation_report_id = None
        outcome.refreshed = True
        action = "refreshed"
        canonical_id = existing.id

    # 7. Append-only audit — counts / flags only, NEVER incumbent PII.
    session.add(
        AuditLog(
            event_type=f"canonical_draft.{action}",
            entity_type="canonical_jd",
            entity_id=canonical_id,
            actor="producer",
            payload={
                "cluster_id": str(cluster_id),
                "action": action,
                "version": _PRODUCER_VERSION,
                "status": DRAFT.value,
                "jdfn_member_count": len(jdfn_ids),
                "wjq_members_excluded": wjq_excluded,
                "score": score,
                "grade": grade,
                "approvable": gate_decision.approved,
                "blocking_gates": [r.gate_id for r in gate_decision.blocking],
                "merge_flags": list(merged.provenance.flags),
                "rewrite_ran": rewritten is not None,
                "rewrite_failed": outcome.rewrite_failed,
                "audit_ran": quality_audit is not None,
                "audit_failed": outcome.audit_failed,
            },
        )
    )
    return outcome


# --- the pass ------------------------------------------------------------------------


async def run_canonical_producer(
    session: AsyncSession,
    *,
    client: ChatClient | None = None,
    rules: Rules | None = None,
    limit: int | None = None,
) -> CanonicalProducerResult:
    """Produce persisted DRAFT ``canonical_jds`` over the real JDFN role clusters.

    ``client=None`` -> deterministic-only (the 4.1 merge draft is persisted; the rewrite
    and audit are recorded as skipped) — runnable without Ollama. A provided ``client``
    drives the full pipeline; a per-cluster model failure isolates + counts, not aborts.

    Deterministic + single-process for the deterministic parts; idempotent persistence.
    The CALLER owns the transaction and the commit — this runner does not commit (each
    cluster runs inside a ``begin_nested`` SAVEPOINT so a per-cluster failure isolates).
    """
    rulebook = rules if rules is not None else get_rules()

    clustering = await run_clustering(
        session, rules=rulebook, limit=limit, neo4j_driver=None
    )

    member_ids: set[UUID] = {
        m.source_id for rec in clustering.clusters for m in rec.members
    }
    jds_by_id, dropped_unvalidatable = await load_member_jds(session, member_ids)

    wjq_excluded_total = 0
    wjq_freq_confirmed = 0
    fully_wjq = 0
    mixed = 0
    clusters_seen = 0
    multi = 0
    single = 0
    persisted = 0
    refreshed = 0
    skipped = 0
    cluster_failures = 0
    rewrite_failures = 0
    audit_failures = 0

    # Deterministic cluster order (content-derived id); member order by source_id.
    for record in sorted(clustering.clusters, key=lambda r: str(r.cluster_id)):
        member_ids_sorted = sorted((m.source_id for m in record.members), key=str)
        present = [
            (mid, jds_by_id[mid]) for mid in member_ids_sorted if mid in jds_by_id
        ]
        jdfn_pairs = [(mid, jd) for mid, jd in present if not is_wjq_member(jd)]
        wjq = [jd for _, jd in present if is_wjq_member(jd)]

        wjq_excluded_total += len(wjq)
        wjq_freq_confirmed += sum(1 for jd in wjq if member_has_frequency(jd))

        if not jdfn_pairs:
            fully_wjq += 1
            continue
        if wjq:
            mixed += 1

        clusters_seen += 1
        if len(jdfn_pairs) >= 2:
            multi += 1
        else:
            single += 1

        try:
            async with session.begin_nested():
                outcome = await _process_cluster(
                    session,
                    record,
                    jdfn_pairs,
                    wjq_excluded=len(wjq),
                    client=client,
                    rules=rulebook,
                )
        except Exception:  # noqa: BLE001 - isolate a per-cluster failure, keep the run
            cluster_failures += 1
            continue

        persisted += int(outcome.persisted)
        refreshed += int(outcome.refreshed)
        skipped += int(outcome.skipped)
        rewrite_failures += int(outcome.rewrite_failed)
        audit_failures += int(outcome.audit_failed)

    return CanonicalProducerResult(
        documents_seen=clustering.documents_seen,
        documents_signed=clustering.documents_signed,
        documents_unsignable=clustering.documents_unsignable,
        clusters_recomputed=clustering.cluster_count,
        wjq_members_excluded=wjq_excluded_total,
        wjq_members_frequency_confirmed=wjq_freq_confirmed,
        clusters_fully_wjq_excluded=fully_wjq,
        clusters_mixed_jdfn_wjq=mixed,
        member_rows_dropped_unvalidatable=dropped_unvalidatable,
        clusters_seen=clusters_seen,
        multi_member_clusters=multi,
        single_member_clusters=single,
        drafts_persisted=persisted,
        drafts_refreshed=refreshed,
        skipped_reviewer_touched=skipped,
        cluster_failures=cluster_failures,
        rewrite_failures=rewrite_failures,
        audit_failures=audit_failures,
        rules_version=rulebook.version,
        llm_enabled=client is not None,
        rewrite_model=rulebook.rewrite.model,
        rewrite_prompt_version=rulebook.rewrite.prompt_version,
        quality_model=rulebook.quality.model,
        quality_prompt_version=rulebook.quality.prompt_version,
    )

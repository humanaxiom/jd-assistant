"""The Phase-4.4a canonical-draft PRODUCER runner.

Per run::

    run_clustering(session)                      # REUSE 3.5 — the JDFN+WJQ partition
        -> load_member_jds(clustered source_ids) # reconstruct each member JD
        -> per cluster: pick the authoring FORM (HR-206), drop + COUNT the rest
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

**Persistence discipline** mirrors :mod:`src.jd_bank.ingest.driver`: by default the
CALLER owns the transaction and the commit; each cluster runs inside a ``begin_nested``
SAVEPOINT so a per-cluster failure isolates that cluster and never corrupts the rest of
the run. For a long (multi-hour) LLM run an optional ``commit_every=N`` makes completed
work crash-safe: the runner commits the session BETWEEN clusters every N processed —
never inside a cluster's SAVEPOINT, so a partial cluster is never committed — and an
idempotent re-run cheaply refreshes/skips what already landed. ``commit_every=None``
(the default) is byte-identical to before: the runner never commits and the caller owns
the single final commit. An optional ``progress_every=N`` prints a counts-only progress
line to STDERR at the same cadence so the run is watchable via the container logs.

**Which FORMS get drafted** is ``harmonization.templates_harmonized`` (HR-206, CUPE
Phase D), a PRIORITY order: a cluster's draft is authored on the first listed template
with members in it, and members on any other form are dropped and counted. Before Phase
D this was hardcoded JDFN-only, which left 657 all-CUPE clusters (26.7%) with no draft
at all. Nothing downstream branches on the form — the merge carries the members' own
``employee_group`` into the draft and ``evaluate_jd_rules`` reads it back to pick that
form's rules (Phase B) and numbers (Phase C), so a CUPE draft is judged against the WJQ
profile without a single ``if template ==`` in the persistence path.

``jd_core`` is never imported the other way round — the producer is ``jd_bank`` and it
drives ``jd_core`` (merge / diff / validator / gates) freely.
"""

from __future__ import annotations

import sys
import time
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.jd_bank.canonical.models import CanonicalProducerResult, TemplateEvaluation
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
from src.jd_bank.harmonize.runner import member_has_frequency
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
from src.jd_core.models.quality import (
    WJQ_TEMPLATE,
    GateDecision,
    JDGrade,
    JDQualityIssue,
    JDTemplate,
)
from src.jd_core.quality.gates import evaluate_gates
from src.jd_core.quality.scoring import score_issues
from src.jd_core.quality.validators import evaluate_jd_rules, template_of
from src.jd_core.rules import Harmonization, Rules, get_rules

#: The ONLY status the producer ever writes — a draft a human still has to approve.
DRAFT: CanonicalStatus = CanonicalStatus.DRAFT

#: The single canonical version the producer maintains per cluster. A reviewer edit /
#: approval (4.4b) is what mints later versions; the producer only refreshes v1.
_PRODUCER_VERSION = 1


# --- pure: which FORM authors a cluster's draft (HR-206, CUPE Phase D) ---------------


def partition_by_template(
    present: Sequence[tuple[UUID, SFUJobDescription]],
) -> dict[JDTemplate, list[tuple[UUID, SFUJobDescription]]]:
    """Split a cluster's members by the form each was written on, order preserved.

    ``template_of`` is the SAME separator ``applies_to`` (Phase B) and
    ``thresholds_for`` (Phase C) read, imported rather than re-derived — three places
    deciding "is this a WJQ document?" is three places that can disagree.
    """
    by_form: dict[JDTemplate, list[tuple[UUID, SFUJobDescription]]] = {}
    for mid, jd in present:
        by_form.setdefault(template_of(jd), []).append((mid, jd))
    return by_form


def authoring_template(
    by_form: Mapping[JDTemplate, Sequence[object]], harmonization: Harmonization
) -> JDTemplate | None:
    """The form this cluster's single draft is authored on — ``None`` if no member is
    on a form the Bank drafts at all.

    ``templates_harmonized`` is a PRIORITY order, not a set, because ``canonical_jds``
    is UNIQUE on ``(cluster_id, version)``: a cluster can hold exactly one draft, so a
    cluster holding both forms needs a rule for which one wins rather than a coin toss.
    Shipped ``[jdfn, wjq]``, so a mixed cluster authors JDFN — precisely what it did
    before this knob existed.
    """
    for template in harmonization.templates_harmonized:
        if by_form.get(template):
            return template
    return None


# --- pure: the no-DOWNGRADE predicate (the second no-clobber rule) -------------------


def draft_was_llm_written(change_log: Mapping[str, Any] | None) -> bool:
    """Whether an existing draft was produced by the FULL pipeline (rewrite + audit).

    Read from the draft's own ``change_log.pipeline.llm_enabled`` — the producer's own
    record of how it built that row — rather than inferred from its content. Absent or
    malformed reads as ``False``: a draft whose provenance cannot be established must
    not be treated as precious, because that would make the producer un-runnable
    against any row it did not write.
    """
    if not change_log:
        return False
    pipeline = change_log.get("pipeline")
    return bool(isinstance(pipeline, Mapping) and pipeline.get("llm_enabled"))


def would_downgrade(change_log: Mapping[str, Any] | None, *, llm_enabled: bool) -> bool:
    """Whether refreshing this draft would REPLACE LLM-written prose with a
    deterministic merge — a strictly poorer draft in the same row.

    🔴 THE DEFECT THIS EXISTS FOR, found by running it against the live Bank on
    2026-08-17. ``--no-llm`` on an ALREADY-POPULATED Bank refreshed 1,763 untouched
    JDFN drafts, discarding the rewrite pass on every one, and reported it as
    ``drafts_refreshed`` — a word that reads like an improvement. The mean score of the
    JDFN cohort fell from 73.0 to 52.73 in thirty-two seconds, and nothing in the run's
    output said a capability had been removed rather than added.

    **The existing no-clobber rule protects HUMAN work and says nothing about PIPELINE
    work.** That was a reasonable place to stop when every run was a full run; it stops
    being reasonable the moment the producer has a cheap mode. A draft is a derived
    artifact, so refreshing it is legitimate — but *derived by a weaker process* is a
    downgrade, and a downgrade should have to be asked for.
    """
    return not llm_enabled and draft_was_llm_written(change_log)


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
    """What ONE cluster's processing did — accumulated by the caller only AFTER its
    SAVEPOINT releases, so an isolated failure never double-counts."""

    persisted: bool = False
    refreshed: bool = False
    skipped: bool = False
    #: An untouched DRAFT left alone because refreshing it would have replaced
    #: LLM-written prose with a deterministic merge (a cheap run over an expensive row).
    skipped_downgrade: bool = False
    #: An untouched DRAFT the full pipeline had already written, skipped by a RESUME
    #: run (`skip_llm_written`) because it owes no further work.
    skipped_llm_written: bool = False
    rewrite_failed: bool = False
    audit_failed: bool = False
    #: The validator's verdict on the draft this cluster WROTE — ``None`` when no draft
    #: was written (reviewer-touched, or the cluster failed). Kept ``None`` rather than
    #: zeroed: a cluster the producer did not score must not enter the cohort's mean as
    #: a zero, which would understate every form it touched.
    score: float | None = None
    grade: JDGrade | None = None
    approvable: bool = False


@dataclass(slots=True)
class _TemplateAgg:
    """Running per-form totals (CUPE Phase D). One of these per template, never one
    shared — the whole point is that no number spans two forms."""

    clusters: int = 0
    drafts_scored: int = 0
    score_total: float = 0.0
    approvable: int = 0
    grades: Counter[str] = field(default_factory=Counter)

    def evaluation(self) -> TemplateEvaluation:
        mean = self.score_total / self.drafts_scored if self.drafts_scored else 0.0
        return TemplateEvaluation(
            clusters=self.clusters,
            drafts_scored=self.drafts_scored,
            mean_score=round(mean, 2),
            approvable=self.approvable,
            grades=dict(sorted(self.grades.items())),
        )


# --- LLM passes (best-effort) --------------------------------------------------------


async def _run_llm_passes(
    merged: MergedRole,
    *,
    rewrite_client: ChatClient | None,
    audit_client: ChatClient | None,
    rules: Rules,
    outcome: _Outcome,
) -> tuple[SFUJobDescription, RewrittenDraft | None, QualityAudit | None]:
    """Drive the 4.2a rewrite + 4.2b audit, best-effort — each on its OWN client.

    The rewrite runs the model of ``rules.rewrite`` and the audit the model of
    ``rules.quality``; these are SEPARATE rulebook decisions (see ``llm/client.py``), so
    the caller injects a client bound to each. ``QualityAudit.model`` stamps
    ``rules.quality.model`` regardless of the client, so a single shared client bound to
    the rewrite model would make that stamp a provenance lie the moment ``quality.yaml``
    is retuned (NN #6) — hence two clients, each bound to its own model.

    ``rewrite_client=None`` -> the deterministic merge draft, no rewrite, no audit (the
    ``--no-llm`` path). Otherwise a rewrite is attempted (a failure falls back to the
    merge draft and sets ``rewrite_failed``), then the advisory audit is attempted on
    the CHOSEN draft with ``audit_client`` when one is provided (a failure omits it and
    sets ``audit_failed``). Neither failure ever aborts — the deterministic draft is
    never lost (mirrors hris ``evaluate_jd_quality`` + the embed isolate-and-skip)."""
    if rewrite_client is None:
        return merged.draft, None, None

    rewritten: RewrittenDraft | None = None
    try:
        rewritten = await rewrite_merged_role(
            merged, client=rewrite_client, rules=rules
        )
        final_draft = rewritten.draft
    except Exception:  # noqa: BLE001 - a model failure isolates, never aborts the run
        outcome.rewrite_failed = True
        final_draft = merged.draft

    quality_audit: QualityAudit | None = None
    if audit_client is not None:
        try:
            quality_audit = await audit_quality(
                final_draft, client=audit_client, rules=rules
            )
        except Exception:  # noqa: BLE001 - the audit is advisory; drop it on failure
            outcome.audit_failed = True

    return final_draft, rewritten, quality_audit


# --- cluster snapshot (the clusters row) ---------------------------------------------


def _cluster_snapshot(
    record: ClusterRecord,
    *,
    member_ids: Sequence[UUID],
    merged: MergedRole,
    template: JDTemplate,
    members_excluded: int,
) -> dict[str, Any]:
    """The auditable ``clusters`` snapshot for a first insert: the members that fed the
    canonical, the form they were authored on, the harmonized employee group, and the
    cohesion metadata — counts / labels / filenames only (the class ``docs/cluster/``
    commits), never JD prose.
    """
    filenames = {m.source_id: m.filename for m in record.members}
    group = merged.draft.employee_group
    return {
        "label": record.label,
        "employee_group": str(group) if group is not None else None,
        "members": [
            {"source_id": str(mid), "filename": filenames.get(mid)}
            for mid in member_ids
        ],
        "constraint_metadata": {
            "constraint_violations": list(record.constraint_violations),
            "cross_department": record.cross_department,
            "cross_group": record.cross_group,
            "family_band_spread": record.family_band_spread,
            "bands": list(record.bands),
            # The FORM this cluster's draft was authored on, and how many members were
            # dropped because they were on another one (HR-206). `members_excluded`
            # kept the old key's meaning but not its name: it read
            # `wjq_members_excluded` when WJQ was the only thing ever dropped, and a
            # count that can now hold JDFN members must not still say "wjq".
            "authored_template": template,
            "members_excluded": members_excluded,
        },
    }


# --- persist / refresh one cluster ---------------------------------------------------


async def _process_cluster(
    session: AsyncSession,
    record: ClusterRecord,
    member_pairs: Sequence[tuple[UUID, SFUJobDescription]],
    *,
    template: JDTemplate,
    members_excluded: int,
    rewrite_client: ChatClient | None,
    audit_client: ChatClient | None,
    rules: Rules,
    allow_downgrade: bool,
    skip_llm_written: bool,
) -> _Outcome:
    """Merge -> (best-effort LLM) -> validate -> upsert cluster + persist/refresh DRAFT
    + append audit_log, for ONE cluster on ONE form. Runs in the caller's SAVEPOINT.

    Template-agnostic end to end, and deliberately so: the merge carries the members'
    own ``employee_group`` into the draft, and ``evaluate_jd_rules`` reads it back to
    pick the rules (Phase B) and the numbers (Phase C) for that form. ``template`` is
    passed in for the RECORD — the audit row and the cluster snapshot — never to
    branch on.
    """
    outcome = _Outcome()
    cluster_id = record.cluster_id
    member_ids = [mid for mid, _ in member_pairs]
    members = [jd for _, jd in member_pairs]

    # 1. NO-CLOBBER — look up the LATEST existing canonical for this cluster FIRST.
    # `order_by(version desc)` so a cluster that a reviewer edit (4.4b) has grown a v2
    # on
    # resolves to the NEWEST version, never a stale v1 — the multi-version follow-up
    # 4.4a
    # deferred. The newest version is the one that carries the reviewer's EDIT action,
    # so
    # the reviewer-touched check below sees it and the producer leaves the edit alone.
    existing = await session.scalar(
        select(CanonicalJD)
        .where(CanonicalJD.cluster_id == cluster_id)
        .order_by(CanonicalJD.version.desc())
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

        # 1a. RESUME — an LLM pass over a Bank that is already part-done.
        #
        # A full LLM run over this archive measures ~44 hours (2,456 clusters at 64.8s,
        # two model calls each). Without this it is also ALL-OR-NOTHING: an interruption
        # anywhere means paying for every cluster again, including the ones already
        # rewritten. `make embed` has had exactly this property since Phase 3.2 — run it
        # again and it skips what is unchanged — and the reindex runbook calls that out
        # as the reason an interrupted reindex needs no resume flag. The producer's
        # expensive pass deserves the same.
        #
        # The predicate is `would_downgrade`'s, inverted: "was this written by the full
        # pipeline?" answers both "may a cheap run overwrite it?" and "does an expensive
        # run still owe it work?".
        if skip_llm_written and draft_was_llm_written(existing.change_log):
            outcome.skipped_llm_written = True
            return outcome

        # 1b. NO-DOWNGRADE — a cheap run must not overwrite an expensive draft.
        if not allow_downgrade and would_downgrade(
            existing.change_log, llm_enabled=rewrite_client is not None
        ):
            outcome.skipped_downgrade = True
            session.add(
                AuditLog(
                    event_type="canonical_draft.skipped_would_downgrade",
                    entity_type="canonical_jd",
                    entity_id=existing.id,
                    actor="producer",
                    payload={
                        "cluster_id": str(cluster_id),
                        "existing_status": existing.status.value,
                        "reason": "would_downgrade_llm_draft_to_deterministic",
                    },
                )
            )
            return outcome

    # 2. The deterministic merge draft + the best-effort LLM passes.
    merged = merge_cluster(members, rules=rules)
    final_draft, rewritten, quality_audit = await _run_llm_passes(
        merged,
        rewrite_client=rewrite_client,
        audit_client=audit_client,
        rules=rules,
        outcome=outcome,
    )

    # 3. The validator roll-up on the FINAL draft (validator-as-oracle, NN #3).
    issues: list[JDQualityIssue] = evaluate_jd_rules(
        final_draft, flatten_jd(final_draft), rules=rules
    )
    score, grade = score_issues(issues, scoring=rules.scoring)
    gate_decision = evaluate_gates(issues, score, grade, gates=rules.gates)

    # The per-form evaluation (CUPE Phase D). Carried on the outcome rather than
    # aggregated here, so a cluster whose SAVEPOINT rolls back contributes nothing —
    # the caller folds it in only after the SAVEPOINT releases, exactly as it already
    # does for the persist/refresh counts.
    outcome.score = score
    outcome.grade = grade
    outcome.approvable = gate_decision.approved

    # 4. The 4.3 change-log + the reviewer packet.
    diff = build_harmonization_diff(merged, members, rewrite=rewritten, rules=rules)
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
        llm_enabled=rewrite_client is not None,
        rewrite_failed=outcome.rewrite_failed,
        audit_failed=outcome.audit_failed,
    )
    content: dict[str, Any] = final_draft.model_dump(mode="json")
    source_document_ids: list[dict[str, Any]] = [
        {"source_id": str(mid)} for mid in member_ids
    ]

    # 5. UPSERT the clusters row (select-or-insert on the STABLE content-derived id).
    cluster = await session.get(Cluster, cluster_id)
    if cluster is None:
        snapshot = _cluster_snapshot(
            record,
            member_ids=member_ids,
            merged=merged,
            template=template,
            members_excluded=members_excluded,
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
                # The FORM this draft was authored on rides in the audit row so a score
                # can never be read out of the log without the bar it was scored
                # against — the per-group rule (never blend the two cohorts) applies to
                # the audit trail too, not just to the reports.
                "template": template,
                "member_count": len(member_ids),
                "members_excluded": members_excluded,
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


# --- progress logging (operational, counts-only) -------------------------------------


def _log_progress(
    *,
    processed: int,
    total: int,
    persisted: int,
    refreshed: int,
    skipped: int,
    cluster_failures: int,
    elapsed_s: float,
) -> None:
    """Emit one counts-only progress line to STDERR — makes a multi-hour run watchable
    via the container logs. Counts/timing only, NEVER JD text (mirrors the counts-only
    ``summary.json`` discipline, NN #6)."""
    print(
        f"[canonical-producer] {processed}/{total} clusters | "
        f"persisted={persisted} refreshed={refreshed} skipped={skipped} "
        f"failures={cluster_failures} | elapsed={elapsed_s:.1f}s",
        file=sys.stderr,
        flush=True,
    )


# --- the pass ------------------------------------------------------------------------


async def run_canonical_producer(
    session: AsyncSession,
    *,
    rewrite_client: ChatClient | None = None,
    audit_client: ChatClient | None = None,
    rules: Rules | None = None,
    limit: int | None = None,
    commit_every: int | None = None,
    progress_every: int | None = None,
    allow_downgrade: bool = False,
    skip_llm_written: bool = False,
) -> CanonicalProducerResult:
    """Produce persisted DRAFT ``canonical_jds`` over the real role clusters.

    ``allow_downgrade=False`` (the DEFAULT) -> a deterministic run LEAVES ALONE any
    untouched draft that the full pipeline wrote, counting it
    ``skipped_would_downgrade``. See :func:`would_downgrade`: a `--no-llm` run over an
    already-populated Bank otherwise discards the rewrite pass on every row it touches
    and reports it as a refresh. Pass ``True`` to deliberately re-baseline the Bank on
    deterministic drafts.

    ``rewrite_client=None`` -> deterministic-only (the 4.1 merge draft is persisted; the
    rewrite and audit are recorded as skipped) — runnable without Ollama. A provided
    ``rewrite_client`` drives the 4.2a rewrite and a provided ``audit_client`` the 4.2b
    audit; each is bound to its own rulebook model (``rules.rewrite`` vs
    ``rules.quality`` — separate decisions) so the ``QualityAudit.model`` stamp cannot
    lie (NN #6). A per-cluster model failure isolates + counts, not aborts.

    Deterministic + single-process for the deterministic parts; idempotent persistence.

    ``commit_every=None`` (the DEFAULT) -> the runner NEVER commits; the CALLER owns the
    transaction and the single final commit (byte-identical to before). A set
    ``commit_every=N`` -> for crash-safety on a long run the runner commits the session
    after every N processed clusters, but ONLY between clusters — after a cluster's
    ``begin_nested`` SAVEPOINT has released (success or isolated failure), so a partial
    cluster is never committed. Work committed at a checkpoint is durable if the run
    later dies, and an idempotent re-run cheaply refreshes/skips what already landed.
    The caller still owns the final commit for the remainder.

    ``progress_every=N`` -> emit a counts-only progress line to STDERR every N processed
    clusters so the run is watchable via the container logs (``None`` -> silent).

    Each cluster runs inside a ``begin_nested`` SAVEPOINT so a per-cluster failure
    isolates that cluster and never aborts the run.
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
    wjq_authored_total = 0
    wjq_freq_confirmed = 0
    fully_wjq = 0
    mixed = 0
    clusters_seen = 0
    by_template: dict[str, int] = {}
    per_form: defaultdict[str, _TemplateAgg] = defaultdict(_TemplateAgg)
    multi = 0
    single = 0
    persisted = 0
    refreshed = 0
    skipped = 0
    skipped_downgrade = 0
    skipped_llm_written = 0
    cluster_failures = 0
    rewrite_failures = 0
    audit_failures = 0

    #: JDFN clusters that have entered + released their SAVEPOINT — the cadence counter
    #: for the between-cluster checkpoint commit and the progress line. ``total`` is the
    #: denominator (all recomputed clusters; some are fully-WJQ and never processed).
    processed = 0
    total = len(clustering.clusters)
    started_at = time.monotonic()

    # Deterministic cluster order (content-derived id); member order by source_id.
    for record in sorted(clustering.clusters, key=lambda r: str(r.cluster_id)):
        member_ids_sorted = sorted((m.source_id for m in record.members), key=str)
        present = [
            (mid, jds_by_id[mid]) for mid in member_ids_sorted if mid in jds_by_id
        ]
        # Which FORM authors this cluster's draft, and which members are therefore
        # dropped (HR-206). `templates_harmonized` is a PRIORITY order, so a mixed
        # cluster authors on the first listed form present in it — `jdfn` first means a
        # mixed cluster does exactly what it did before Phase D.
        by_form = partition_by_template(present)
        template = authoring_template(by_form, rulebook.harmonization)
        wjq_members = [jd for _, jd in by_form.get(WJQ_TEMPLATE, ())]

        wjq_freq_confirmed += sum(1 for jd in wjq_members if member_has_frequency(jd))
        if template == WJQ_TEMPLATE:
            wjq_authored_total += len(wjq_members)
        else:
            wjq_excluded_total += len(wjq_members)

        if template is None:
            # No member is on a form the Bank drafts. Today that can only be an all-WJQ
            # cluster with `wjq` removed from the list — the pre-Phase-D behaviour.
            if wjq_members:
                fully_wjq += 1
            continue

        member_pairs = by_form[template]
        excluded_count = len(present) - len(member_pairs)
        if excluded_count and WJQ_TEMPLATE in by_form and template != WJQ_TEMPLATE:
            mixed += 1

        clusters_seen += 1
        by_template[template] = by_template.get(template, 0) + 1
        per_form[template].clusters += 1
        if len(member_pairs) >= 2:
            multi += 1
        else:
            single += 1

        try:
            async with session.begin_nested():
                outcome = await _process_cluster(
                    session,
                    record,
                    member_pairs,
                    template=template,
                    members_excluded=excluded_count,
                    rewrite_client=rewrite_client,
                    audit_client=audit_client,
                    rules=rulebook,
                    allow_downgrade=allow_downgrade,
                    skip_llm_written=skip_llm_written,
                )
        except Exception:  # noqa: BLE001 - isolate a per-cluster failure, keep the run
            cluster_failures += 1
        else:
            persisted += int(outcome.persisted)
            refreshed += int(outcome.refreshed)
            skipped += int(outcome.skipped)
            skipped_downgrade += int(outcome.skipped_downgrade)
            skipped_llm_written += int(outcome.skipped_llm_written)
            rewrite_failures += int(outcome.rewrite_failed)
            audit_failures += int(outcome.audit_failed)
            if outcome.score is not None and outcome.grade is not None:
                agg = per_form[template]
                agg.drafts_scored += 1
                agg.score_total += outcome.score
                agg.approvable += int(outcome.approvable)
                agg.grades[outcome.grade] += 1

        # BETWEEN clusters ONLY — the SAVEPOINT above has released (success or isolated
        # failure), so the checkpoint commit can never persist a partial cluster. The
        # caller still owns the final commit for whatever follows the last checkpoint.
        processed += 1
        if commit_every is not None and processed % commit_every == 0:
            await session.commit()
        if progress_every is not None and processed % progress_every == 0:
            _log_progress(
                processed=processed,
                total=total,
                persisted=persisted,
                refreshed=refreshed,
                skipped=skipped,
                cluster_failures=cluster_failures,
                elapsed_s=time.monotonic() - started_at,
            )

    return CanonicalProducerResult(
        documents_seen=clustering.documents_seen,
        documents_signed=clustering.documents_signed,
        documents_unsignable=clustering.documents_unsignable,
        clusters_recomputed=clustering.cluster_count,
        wjq_members_excluded=wjq_excluded_total,
        wjq_members_authored=wjq_authored_total,
        wjq_members_frequency_confirmed=wjq_freq_confirmed,
        clusters_by_template=dict(sorted(by_template.items())),
        evaluation_by_template={
            template: agg.evaluation() for template, agg in sorted(per_form.items())
        },
        clusters_fully_wjq_excluded=fully_wjq,
        clusters_mixed_jdfn_wjq=mixed,
        member_rows_dropped_unvalidatable=dropped_unvalidatable,
        clusters_seen=clusters_seen,
        multi_member_clusters=multi,
        single_member_clusters=single,
        drafts_persisted=persisted,
        drafts_refreshed=refreshed,
        skipped_reviewer_touched=skipped,
        skipped_would_downgrade=skipped_downgrade,
        skipped_already_llm_written=skipped_llm_written,
        cluster_failures=cluster_failures,
        rewrite_failures=rewrite_failures,
        audit_failures=audit_failures,
        rules_version=rulebook.version,
        llm_enabled=rewrite_client is not None,
        rewrite_model=rulebook.rewrite.model,
        rewrite_prompt_version=rulebook.rewrite.prompt_version,
        quality_model=rulebook.quality.model,
        quality_prompt_version=rulebook.quality.prompt_version,
    )

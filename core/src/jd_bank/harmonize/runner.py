"""The Phase-4.1 harmonization MEASUREMENT pass (report-only).

Per run::

    run_clustering(session)                      # REUSE 3.5 — the JDFN+WJQ partition
        -> load_member_jds(clustered source_ids) # reconstruct each member JD
        -> drop WJQ (employee_group == "cupe"), COUNT the exclusions
        -> per JDFN cluster: merge_cluster(...)   # DRIVE the real 4.1 engine
           + measure the distributions the 9 knobs cut on
        -> aggregate -> a HarmonizationResult (report-only)

**Recomputes clusters in-process** (``run_clustering``) rather than reading
``docs/cluster/cluster-members.csv`` — that artifact is filename-keyed (lossy); the
runner needs the ``source_document_id`` UUIDs to reconstruct each member JD. Clusters
are a deterministic function of the edge graph, so recomputing is cheap + reproducible.

**Persists NOTHING, commits NOTHING, picks NO knob value.** The caller owns the
(read-only) transaction. Every default is echoed UNCHANGED into the summary — the human
calibrates from the measured numbers (Tier-B: the coder MEASURES, the orchestrator
DECIDES).
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.jd_bank.cluster.runner import run_clustering
from src.jd_bank.dedup.signals_load import load_member_jds
from src.jd_bank.harmonize.models import (
    CORE_FRACTION_CANDIDATES,
    DUTY_CAP_CANDIDATES,
    DUTY_JACCARD_CANDIDATES,
    HARMONIZE_VERSION,
    PAIRWISE_STATEMENT_CAP,
    ClusterHarmonization,
    HarmonizationResult,
)
from src.jd_core.bank.merge import _jaccard, _tokens, merge_cluster
from src.jd_core.bank.signals import build_job_signals
from src.jd_core.models.parsed_jd import SFUJobDescription
from src.jd_core.models.quality import WJQ_TEMPLATE
from src.jd_core.quality.validators import template_of
from src.jd_core.rules import Harmonization, Rules, get_rules

# --- pure: the WJQ proxy (template is not persisted) --------------------------------


def is_wjq_member(jd: SFUJobDescription) -> bool:
    """Whether ``jd`` is a WJQ (CUPE) member, by the field the JD model designates as
    the JDFN/WJQ separator. ``ParseResult.template`` is not persisted, and the WJQ
    segmenter sets ``employee_group == "cupe"`` unconditionally, so this has complete
    WJQ recall (its only risk is over-excluding a JDFN doc that names CUPE in its
    identification block — the safe direction for measuring the JDFN bar).

    Expressed as ``template_of(jd) == "wjq"`` rather than as its own comparison, so
    "which documents are CUPE?" has exactly ONE answer in this codebase. It used to
    have two — see the note on :data:`~src.jd_bank.harmonize.models.WJQ_EMPLOYEE_GROUP`.
    """
    return template_of(jd) == WJQ_TEMPLATE


def member_has_frequency(jd: SFUJobDescription) -> bool:
    """Whether any duty carries a ``frequency`` marker — the WJQ-only signal (a JDFN
    duty always leaves it ``None``). Used only to cross-confirm the WJQ proxy."""
    return any(d.frequency is not None for d in jd.duties)


# --- pure: uncapped duty dedup count (mirrors merge._merge_duties grouping) ----------


def deduped_duty_count(statements: Sequence[str], threshold: float) -> int:
    """How many groups a greedy token-Jaccard dedup collapses ``statements`` into at
    ``threshold`` — UNCAPPED (before ``max_duties``), so the knee is visible above the
    cap. Mirrors ``merge._merge_duties`` exactly (same sort, same greedy, same
    tokenizer reused from ``merge``) so the measured knee cannot drift from the engine.
    """
    occ = sorted(range(len(statements)), key=lambda i: (statements[i], i))
    reps: list[frozenset[str]] = []
    for i in occ:
        toks = _tokens(statements[i])
        if not any(_jaccard(toks, rep) >= threshold for rep in reps):
            reps.append(toks)
    return len(reps)


# --- pure: histogram bin helpers ----------------------------------------------------


def _frac05_bin(value: float) -> str:
    lo = min(int(value / 0.05), 19) * 5
    return f"0.{lo:02d}-0.{lo + 5:02d}" if lo < 95 else "0.95-1.00"


def _frac10_bin(value: float) -> str:
    lo = min(int(value / 0.10), 9)
    return f"0.{lo}-0.{lo + 1}" if lo < 9 else "0.9-1.0"


def _word_bucket(words: int, lo: int, hi: int) -> str:
    if words < lo:
        return f"<{lo}"
    if words <= hi:
        return f"{lo}-{hi}"
    return f">{hi}"


def _modal_and_max(values: Sequence[int]) -> tuple[int, int]:
    """(modal, max) over non-empty ``values``; modal ties broken to the smaller."""
    counts = Counter(values)
    modal = min(counts, key=lambda v: (-counts[v], v))
    return modal, max(values)


# --- the stamp ----------------------------------------------------------------------


def harmonize_stamp(harmon: Harmonization) -> str:
    """``<HARMONIZE_VERSION>+<digest>`` over the nine knobs — the run's provenance. A
    retune of any knob (or a version bump) re-stamps the measurement."""
    payload = json.dumps(
        {
            "title_policy": harmon.title_policy,
            "summary_policy": harmon.summary_policy,
            "additional_context_policy": harmon.additional_context_policy,
            "boilerplate_presence_policy": harmon.boilerplate_presence_policy,
            "duty_dedup_jaccard_min": harmon.duty_dedup_jaccard_min,
            "max_duties": harmon.max_duties,
            "core_skill_min_fraction": harmon.core_skill_min_fraction,
            "security_policy": harmon.security_policy,
            "seniority_bar_policy": harmon.seniority_bar_policy,
        },
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"{HARMONIZE_VERSION}+{digest[:12]}"


# --- accumulator --------------------------------------------------------------------


@dataclass
class _Agg:
    """Mutable folds over harmonized clusters. Order-independent (Counters / sums)."""

    total_deduped_by_threshold: Counter[str] = field(default_factory=Counter)
    deduped_count_hist: Counter[int] = field(default_factory=Counter)
    duties_over_cap: Counter[str] = field(default_factory=Counter)
    pairwise_jaccard_hist: Counter[str] = field(default_factory=Counter)
    skill_fraction_hist: Counter[str] = field(default_factory=Counter)
    no_core_by_fraction: Counter[str] = field(default_factory=Counter)
    summary_in_range: int = 0
    summary_no_in_range: int = 0
    summary_wordcount_buckets: Counter[str] = field(default_factory=Counter)
    distinct_title_hist: Counter[int] = field(default_factory=Counter)
    modal_fraction_hist: Counter[str] = field(default_factory=Counter)
    edu_spread_hist: Counter[int] = field(default_factory=Counter)
    exp_spread_hist: Counter[int] = field(default_factory=Counter)
    edu_max_differs: int = 0
    exp_max_differs: int = 0
    members_with_context: int = 0
    clusters_with_multi_context: int = 0
    boilerplate: dict[str, Counter[str]] = field(
        default_factory=lambda: {
            "about_sfu": Counter(),
            "territorial": Counter(),
            "equity": Counter(),
        }
    )
    clusters_with_any_security: int = 0
    security_count_hist: Counter[int] = field(default_factory=Counter)
    flag_counts: Counter[str] = field(default_factory=Counter)


# --- per-cluster measurement --------------------------------------------------------


def measure_cluster(
    cluster_id: UUID,
    jdfn_members: Sequence[SFUJobDescription],
    wjq_dropped: int,
    agg: _Agg,
    *,
    rules: Rules,
) -> ClusterHarmonization:
    """Drive ``merge_cluster`` over one cluster's JDFN members and fold the measured
    distributions into ``agg``. Multi-member clusters feed the calibration histograms;
    a single-member cluster is recorded (flag ``single_member``) but kept OUT of the
    distributions so it cannot swamp them. Returns the per-cluster record."""
    harmon = rules.harmonization
    n = len(jdfn_members)
    multi = n >= 2

    merged = merge_cluster(jdfn_members, rules=rules)
    prov = merged.provenance
    for flag in prov.flags:
        agg.flag_counts[flag] += 1

    sigs = [build_job_signals(jd, rules=rules) for jd in jdfn_members]

    # --- duties (HR-171 / HR-172) ---
    statements = [d.statement for jd in jdfn_members for d in jd.duties]
    deduped_07 = deduped_duty_count(statements, harmon.duty_dedup_jaccard_min)

    # --- title (HR-167) ---
    norms = [s.normalized_title for s in sigs]
    distinct_titles = len(set(norms))
    modal_group_fraction = (max(Counter(norms).values()) / n) if norms else 1.0

    # --- core skills (HR-173) ---
    core_skill_count = sum(
        1
        for _, count in prov.skill_frequency
        if count / n >= harmon.core_skill_min_fraction
    )

    # --- security (HR-174) ---
    security_qual_count = sum(
        1 for q in merged.draft.qualifications if q.kind == "security"
    )

    # --- additional context (HR-169) ---
    members_with_context = sum(
        1
        for jd in jdfn_members
        if jd.additional_context and jd.additional_context.strip()
    )

    # --- summary (HR-168) ---
    lo = rules.thresholds.summary_min_words
    hi = rules.thresholds.summary_max_words
    summary_words = [
        len(jd.position_summary.split())
        for jd in jdfn_members
        if jd.position_summary and jd.position_summary.strip()
    ]
    in_range_available = any(lo <= w <= hi for w in summary_words)
    chosen_words = (
        len(merged.draft.position_summary.split())
        if merged.draft.position_summary
        else None
    )

    # --- seniority bars (HR-175) ---
    edu_bars = [s.education_ordinal for s in sigs if s.education_ordinal is not None]
    exp_bars = [s.experience_years for s in sigs if s.experience_years is not None]
    edu_spread = (max(edu_bars) - min(edu_bars)) if edu_bars else None
    exp_spread = (max(exp_bars) - min(exp_bars)) if exp_bars else None

    record_out = ClusterHarmonization(
        cluster_id=cluster_id,
        jdfn_member_count=n,
        wjq_members_dropped=wjq_dropped,
        deduped_duty_count=deduped_07,
        distinct_normalized_titles=distinct_titles,
        modal_group_fraction=round(modal_group_fraction, 6),
        core_skill_count=core_skill_count,
        security_qual_count=security_qual_count,
        members_with_context=members_with_context,
        summary_in_range_available=in_range_available,
        chosen_summary_words=chosen_words,
        education_bar_spread=edu_spread,
        experience_bar_spread=exp_spread,
        flags=prov.flags,
    )

    # member-level fold (single + multi)
    agg.members_with_context += members_with_context
    if security_qual_count:
        agg.clusters_with_any_security += 1
        agg.security_count_hist[security_qual_count] += 1

    if not multi:
        return record_out

    # --- distribution folds: MULTI-member clusters only ---
    for thr in DUTY_JACCARD_CANDIDATES:
        agg.total_deduped_by_threshold[f"{thr:.1f}"] += deduped_duty_count(
            statements, thr
        )
    agg.deduped_count_hist[deduped_07] += 1
    for cap in DUTY_CAP_CANDIDATES:
        if deduped_07 > cap:
            agg.duties_over_cap[str(cap)] += 1

    capped = sorted(statements)[:PAIRWISE_STATEMENT_CAP]
    toks = [_tokens(s) for s in capped]
    for i in range(len(toks)):
        for j in range(i + 1, len(toks)):
            agg.pairwise_jaccard_hist[_frac05_bin(_jaccard(toks[i], toks[j]))] += 1

    for _, count in prov.skill_frequency:
        agg.skill_fraction_hist[_frac10_bin(count / n)] += 1
    for frac in CORE_FRACTION_CANDIDATES:
        if not any(count / n >= frac for _, count in prov.skill_frequency):
            agg.no_core_by_fraction[f"{frac:.1f}"] += 1

    if in_range_available:
        agg.summary_in_range += 1
    elif summary_words:
        agg.summary_no_in_range += 1
    if chosen_words is not None:
        agg.summary_wordcount_buckets[_word_bucket(chosen_words, lo, hi)] += 1

    agg.distinct_title_hist[distinct_titles] += 1
    agg.modal_fraction_hist[_frac10_bin(modal_group_fraction)] += 1

    if edu_bars:
        agg.edu_spread_hist[max(edu_bars) - min(edu_bars)] += 1
        modal, mx = _modal_and_max(edu_bars)
        if mx != modal:
            agg.edu_max_differs += 1
    if exp_bars:
        agg.exp_spread_hist[max(exp_bars) - min(exp_bars)] += 1
        modal, mx = _modal_and_max(exp_bars)
        if mx != modal:
            agg.exp_max_differs += 1

    if members_with_context >= 2:
        agg.clusters_with_multi_context += 1

    for key, present in (
        ("about_sfu", [jd.about_sfu_present for jd in jdfn_members]),
        (
            "territorial",
            [jd.territorial_acknowledgement_present for jd in jdfn_members],
        ),
        ("equity", [jd.employment_equity_present for jd in jdfn_members]),
    ):
        if all(present):
            agg.boilerplate[key]["all_true"] += 1
        elif not any(present):
            agg.boilerplate[key]["all_false"] += 1
        else:
            agg.boilerplate[key]["mixed"] += 1

    return record_out


# --- the pass -----------------------------------------------------------------------


async def run_harmonization(
    session: AsyncSession, *, rules: Rules | None = None, limit: int | None = None
) -> HarmonizationResult:
    """Drive ``merge_cluster`` over the real JDFN role clusters and measure the nine
    knobs — report-only, deterministic, single-process. WJQ members are excluded and
    counted. ``limit`` restricts the signed corpus for a smoke run. Commits nothing."""
    rulebook = rules if rules is not None else get_rules()
    harmon = rulebook.harmonization

    clustering = await run_clustering(
        session, rules=rulebook, limit=limit, neo4j_driver=None
    )

    member_ids: set[UUID] = {
        m.source_id for rec in clustering.clusters for m in rec.members
    }
    jds_by_id, dropped_unvalidatable = await load_member_jds(session, member_ids)

    agg = _Agg()
    records: list[ClusterHarmonization] = []
    wjq_dropped_total = 0
    wjq_freq_confirmed = 0
    fully_wjq = 0
    mixed = 0
    harmonized = 0
    multi = 0
    single = 0
    jdfn_merged = 0

    # Deterministic cluster order (content-derived id); member order by source_id.
    for record in sorted(clustering.clusters, key=lambda r: str(r.cluster_id)):
        member_ids_sorted = sorted((m.source_id for m in record.members), key=str)
        present = [
            (mid, jds_by_id[mid]) for mid in member_ids_sorted if mid in jds_by_id
        ]
        jdfn = [jd for _, jd in present if not is_wjq_member(jd)]
        wjq = [jd for _, jd in present if is_wjq_member(jd)]

        wjq_dropped_total += len(wjq)
        wjq_freq_confirmed += sum(1 for jd in wjq if member_has_frequency(jd))

        if not jdfn:
            fully_wjq += 1
            continue
        if wjq:
            mixed += 1

        record_out = measure_cluster(
            record.cluster_id, jdfn, len(wjq), agg, rules=rulebook
        )
        records.append(record_out)
        harmonized += 1
        jdfn_merged += len(jdfn)
        if len(jdfn) >= 2:
            multi += 1
        else:
            single += 1

    return HarmonizationResult(
        documents_seen=clustering.documents_seen,
        documents_signed=clustering.documents_signed,
        documents_unsignable=clustering.documents_unsignable,
        singletons=clustering.singletons,
        clusters_recomputed=clustering.cluster_count,
        wjq_members_dropped=wjq_dropped_total,
        wjq_members_frequency_confirmed=wjq_freq_confirmed,
        clusters_fully_wjq_excluded=fully_wjq,
        clusters_mixed_jdfn_wjq=mixed,
        member_rows_dropped_unvalidatable=dropped_unvalidatable,
        harmonized_clusters=harmonized,
        multi_member_clusters=multi,
        single_member_clusters=single,
        jdfn_members_merged=jdfn_merged,
        total_deduped_duties_by_threshold=dict(
            sorted(agg.total_deduped_by_threshold.items())
        ),
        deduped_duty_count_histogram=dict(sorted(agg.deduped_count_hist.items())),
        duties_over_cap=dict(
            sorted(agg.duties_over_cap.items(), key=lambda kv: int(kv[0]))
        ),
        pairwise_duty_jaccard_histogram=dict(sorted(agg.pairwise_jaccard_hist.items())),
        skill_fraction_histogram=dict(sorted(agg.skill_fraction_hist.items())),
        no_core_skills_by_fraction=dict(sorted(agg.no_core_by_fraction.items())),
        summary_in_range_available_clusters=agg.summary_in_range,
        summary_no_in_range_clusters=agg.summary_no_in_range,
        chosen_summary_wordcount_buckets=dict(
            sorted(agg.summary_wordcount_buckets.items())
        ),
        distinct_normalized_title_histogram=dict(
            sorted(agg.distinct_title_hist.items())
        ),
        modal_group_fraction_histogram=dict(sorted(agg.modal_fraction_hist.items())),
        education_bar_spread_histogram=dict(sorted(agg.edu_spread_hist.items())),
        experience_bar_spread_histogram=dict(sorted(agg.exp_spread_hist.items())),
        education_max_differs_from_modal=agg.edu_max_differs,
        experience_max_differs_from_modal=agg.exp_max_differs,
        jdfn_members_with_context=agg.members_with_context,
        clusters_with_multi_context=agg.clusters_with_multi_context,
        boilerplate_agreement={
            k: dict(sorted(v.items())) for k, v in agg.boilerplate.items()
        },
        clusters_with_any_security=agg.clusters_with_any_security,
        security_count_histogram=dict(sorted(agg.security_count_hist.items())),
        flag_counts=dict(sorted(agg.flag_counts.items())),
        title_policy=harmon.title_policy,
        summary_policy=harmon.summary_policy,
        additional_context_policy=harmon.additional_context_policy,
        boilerplate_presence_policy=harmon.boilerplate_presence_policy,
        duty_dedup_jaccard_min=harmon.duty_dedup_jaccard_min,
        max_duties=harmon.max_duties,
        core_skill_min_fraction=harmon.core_skill_min_fraction,
        security_policy=harmon.security_policy,
        seniority_bar_policy=harmon.seniority_bar_policy,
        harmonize_stamp=harmonize_stamp(harmon),
        clusters=tuple(records),
    )

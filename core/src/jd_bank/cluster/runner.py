"""The Phase-3.5 clustering pass — connected components over the admitted edge graph.

The chain, per run::

    parsed_jds (v2) -> load_signed_corpus per source_document_id   (skip unsignable)
        -> load NEAR + ROLE edges from dedup_edges (both endpoints signed)
        -> SYNTHESIZE EXACT star edges from source_documents.sha256  (see below)
        -> admit_edges: tier gate + ROLE gate + band/group veto
        -> build_clusters(threshold=0.0) — union-find over the ADMITTED edges
        -> per cluster: label, metrics, representative, cohesion cap (FLAG not split),
           within-cluster drift roll-up vs the representative
        -> a ClusteringResult (report-only)

**Why synthesize EXACT in-runner.** Tier-2 structurally excludes byte-identical pairs —
it keeps ONE MinHash signature per distinct content, so two identical files never get a
near-dup edge, and no EXACT edges are persisted either. Left alone, two identical JDs
would split into separate clusters. So this runner reconstructs EXACT connectivity from
``source_documents.sha256`` (a star per duplicate group, score 1.0) using the SAME
``group_by_sha256`` Tier-1 uses — no DB write, purely to reunite the identical pairs the
persisted graph misses (measured: ~1,965 synthetic edges).

**Persists NOTHING, commits NOTHING.** No ``Cluster`` row is written (the CASCADE hazard
+ the recomputability argument — see :mod:`.models`). ``build_clusters`` /
``clustering.py`` / ``drift.py`` are CALLED, never modified. The caller owns the
(read-only) transaction.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.jd_bank.cluster.admit import DropCounts, admit_edges
from src.jd_bank.cluster.models import (
    BAND_SPREAD,
    CLUSTER_VERSION,
    GROUP_MIX,
    OVERSIZE,
    ClusterEdge,
    ClusteringResult,
    ClusterMember,
    ClusterRecord,
    cluster_id_for,
)
from src.jd_bank.db.models import DedupEdge, DedupTier
from src.jd_bank.dedup.models import DocumentRef, order_key
from src.jd_bank.dedup.signals_load import SignedCorpus, load_signed_corpus
from src.jd_bank.dedup.tier1 import EXACT_METHOD, EXACT_SCORE, group_by_sha256
from src.jd_core.bank.clustering import build_clusters, cluster_label, cluster_metrics
from src.jd_core.bank.drift import compute_drift
from src.jd_core.models.bank import DriftLevel, JobSignals
from src.jd_core.rules import Comparison, Rules, RulesError, get_rules
from src.settings import get_settings

if TYPE_CHECKING:
    from neo4j import AsyncDriver

#: Tiers read from ``dedup_edges`` (EXACT is synthesized in-runner, not persisted).
_PERSISTED_TIERS = (DedupTier.NEAR_DUPLICATE, DedupTier.ROLE_EQUIVALENT)

#: Total order over drift levels, so a cluster's roll-up is ``max`` over its members.
_DRIFT_RANK: Mapping[DriftLevel, int] = {"aligned": 0, "minor": 1, "major": 2}


# --- pure: EXACT synthesis ---------------------------------------------------


def synthesize_exact_edges(refs: Mapping[UUID, DocumentRef]) -> list[ClusterEdge]:
    """EXACT star edges reconstructed from ``refs`` by SHA-256 — the connectivity Tier-2
    structurally drops (one signature per distinct content, so byte-identical files have
    no near-dup edge). One star per duplicate group (``group_by_sha256``, the Tier-1
    grouping), rep = ``members[0]`` in canonical order, score 1.0.

    Pure: no DB. Only groups of two or more yield edges (a unique file duplicates
    nothing)."""
    edges: list[ClusterEdge] = []
    for group in group_by_sha256(refs.values()):
        rep = group.members[0]
        for member in group.members[1:]:
            edges.append(
                ClusterEdge(
                    a=rep.id,
                    b=member.id,
                    tier=DedupTier.EXACT,
                    score=EXACT_SCORE,
                    method=EXACT_METHOD,
                )
            )
    return edges


# --- pure: representative + drift + one cluster record -----------------------


def choose_representative(
    member_ids: Sequence[UUID],
    *,
    confidence: Mapping[UUID, float],
    refs: Mapping[UUID, DocumentRef],
    policy: str,
) -> UUID:
    """The member every other member's drift is measured against.

    ``max_parse_confidence`` (the only implemented policy, HR-166): the highest
    ``parse_confidence``, ties broken by the ``order_key`` archive order —
    deterministic, so two runs pick the same anchor. An unimplemented policy raises
    rather than anchoring on an arbitrary member (the ``cluster_algo`` lesson)."""
    if policy != "max_parse_confidence":
        raise RulesError(
            f"cluster_representative_policy names {policy!r}, which is not implemented "
            f"— a report would name an anchor the runner never used. Implemented: "
            f"['max_parse_confidence']."
        )
    return min(
        member_ids,
        key=lambda mid: (-confidence[mid], order_key(refs[mid])),
    )


def _drift_level(rep: JobSignals, member: JobSignals, *, rules: Rules) -> DriftLevel:
    """The skill-set drift level of ``member`` from the cluster representative ``rep``,
    with the education/experience/supervisory escalations Tier-3's drift maths applies —
    ``compute_drift`` is CALLED, not reimplemented."""
    return compute_drift(
        set(rep.skills),
        set(member.skills),
        canonical_education=rep.education_ordinal,
        job_education=member.education_ordinal,
        canonical_years=rep.experience_years,
        job_years=member.experience_years,
        canonical_reports=rep.supervisory_reports,
        job_reports=member.supervisory_reports,
        rules=rules,
    ).level


def build_cluster_record(
    member_ids: Sequence[UUID],
    internal_edges: Sequence[ClusterEdge],
    *,
    signals: Mapping[UUID, JobSignals],
    refs: Mapping[UUID, DocumentRef],
    confidence: Mapping[UUID, float],
    rules: Rules,
) -> ClusterRecord:
    """One :class:`ClusterRecord` from a connected component's members + its internal
    edges. Computes the cohesion cap but FLAGS, never splits (constraint_violations).
    Pure."""
    comparison = rules.comparison
    rep_id = choose_representative(
        member_ids,
        confidence=confidence,
        refs=refs,
        policy=comparison.cluster_representative_policy,
    )
    rep_sig = signals[rep_id]

    ordered_ids = sorted(member_ids, key=lambda mid: order_key(refs[mid]))
    members: list[ClusterMember] = []
    band_values: list[int] = []
    known_departments: set[str] = set()
    known_groups: set[str] = set()
    drift_ranks: list[int] = []
    major_count = 0
    for mid in ordered_ids:
        sig = signals[mid]
        band = comparison.family_band_ladder.get(sig.family)
        if band is not None:
            band_values.append(band)
        if sig.department:
            known_departments.add(sig.department)
        if sig.employee_group:
            known_groups.add(sig.employee_group)
        if mid == rep_id:
            level: DriftLevel = "aligned"
        else:
            level = _drift_level(rep_sig, sig, rules=rules)
        drift_ranks.append(_DRIFT_RANK[level])
        if level == "major":
            major_count += 1
        members.append(
            ClusterMember(
                source_id=mid,
                filename=refs[mid].filename,
                title=sig.title,
                normalized_title=sig.normalized_title,
                department=sig.department,
                employee_group=sig.employee_group,
                family=sig.family,
                band=band,
                restricted=sig.restricted,
                is_representative=mid == rep_id,
                parse_confidence=confidence[mid],
                drift_vs_representative=level,
            )
        )

    titles = [signals[mid].title for mid in ordered_ids]
    departments = [signals[mid].department for mid in ordered_ids]
    distinct_titles, _dept_count, cross_department = cluster_metrics(
        titles, departments, rules=rules
    )
    band_spread = max(band_values) - min(band_values) if band_values else None
    cross_group = len(known_groups) > 1

    violations: list[str] = []
    if band_spread is not None and band_spread > comparison.cluster_max_band_spread:
        violations.append(BAND_SPREAD)
    if comparison.cluster_group_homogeneous and len(known_groups) > 1:
        violations.append(GROUP_MIX)
    if len(ordered_ids) > comparison.cluster_max_size:
        violations.append(OVERSIZE)

    max_rank = max(drift_ranks)
    drift_level_max: DriftLevel = next(
        level for level, rank in _DRIFT_RANK.items() if rank == max_rank
    )

    return ClusterRecord(
        cluster_id=cluster_id_for([refs[mid].storage_ref for mid in ordered_ids]),
        label=cluster_label(titles),
        member_count=len(ordered_ids),
        titles=tuple(sorted({t for t in titles if t})),
        departments=tuple(sorted(known_departments)),
        employee_groups=tuple(sorted(known_groups)),
        distinct_titles=distinct_titles,
        cross_department=cross_department,
        cross_group=cross_group,
        family_band_spread=band_spread,
        bands=tuple(sorted(set(band_values))),
        has_restricted=any(m.restricted for m in members),
        tiers=tuple(sorted({e.tier.value for e in internal_edges})),
        min_edge_score=min(e.score for e in internal_edges),
        drift_level_max=drift_level_max,
        drift_major_count=major_count,
        constraint_violations=tuple(sorted(violations)),
        representative_filename=refs[rep_id].filename,
        members=tuple(members),
    )


# --- the clustering stamp ----------------------------------------------------


def cluster_stamp(comparison: Comparison) -> str:
    """``<CLUSTER_VERSION>+<digest>`` over the cluster knobs — the report's provenance.
    A retune of any knob (or a CLUSTER_VERSION bump) re-stamps the report."""
    payload = json.dumps(
        {
            "cluster_tiers": sorted(comparison.cluster_tiers),
            "cluster_role_equiv_min": comparison.cluster_role_equiv_min,
            "cluster_max_band_spread": comparison.cluster_max_band_spread,
            "cluster_group_homogeneous": comparison.cluster_group_homogeneous,
            "cluster_max_size": comparison.cluster_max_size,
            "cluster_representative_policy": comparison.cluster_representative_policy,
            "cluster_algo": comparison.cluster_algo,
            "min_cluster_size": comparison.min_cluster_size,
        },
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"{CLUSTER_VERSION}+{digest[:12]}"


# --- I/O: load persisted edges, count vectors --------------------------------


async def _load_persisted_edges(
    session: AsyncSession, signed_ids: set[UUID]
) -> list[ClusterEdge]:
    """Every NEAR/ROLE ``dedup_edges`` row whose BOTH endpoints this run signed. Matches
    on the enum (as Tier-2/Tier-3 reconciles do), so the persisted enum NAME is compared
    correctly. EXACT is NOT read here — it is synthesized (Tier-2 drops byte-identical
    pairs, and no EXACT rows are persisted for this corpus)."""
    rows = await session.execute(
        select(
            DedupEdge.source_a_id,
            DedupEdge.source_b_id,
            DedupEdge.tier,
            DedupEdge.score,
            DedupEdge.method,
        ).where(DedupEdge.tier.in_(_PERSISTED_TIERS))
    )
    return [
        ClusterEdge(a=a, b=b, tier=tier, score=score, method=method)
        for a, b, tier, score, method in rows
        if a in signed_ids and b in signed_ids and a != b
    ]


async def _count_vectors(
    driver: AsyncDriver, ids: Sequence[UUID], *, batch_size: int
) -> int:
    """How many of ``ids`` have a ``(:JDDocument {embedding})`` node — a report nicety
    (clustering is over the edge graph, not vectors). ONLY reads."""
    if not ids:
        return 0
    seen = 0
    async with driver.session() as neo_session:
        for start in range(0, len(ids), batch_size):
            chunk = ids[start : start + batch_size]
            result = await neo_session.run(
                "MATCH (d:JDDocument) WHERE d.id IN $ids AND d.embedding IS NOT NULL "
                "RETURN count(d) AS n",
                ids=[str(i) for i in chunk],
            )
            record = await result.single()
            if record is not None:
                seen += int(record["n"])
    return seen


# --- the pass ----------------------------------------------------------------


def _cluster_records(
    components: list[list[UUID]],
    admitted: Sequence[ClusterEdge],
    *,
    signed: SignedCorpus,
    rules: Rules,
) -> list[ClusterRecord]:
    """Attribute the admitted edges to their components, then build one record per
    cluster. Deterministic order: ``build_clusters`` sorts largest-first, ties by
    smallest member id."""
    index: dict[UUID, int] = {
        mid: i for i, members in enumerate(components) for mid in members
    }
    internal: dict[int, list[ClusterEdge]] = defaultdict(list)
    for edge in admitted:
        ci = index.get(edge.a)
        if ci is not None and ci == index.get(edge.b):
            internal[ci].append(edge)
    return [
        build_cluster_record(
            members,
            internal[i],
            signals=signed.signals,
            refs=signed.refs,
            confidence=signed.confidence,
            rules=rules,
        )
        for i, members in enumerate(components)
    ]


async def run_clustering(
    pg_session: AsyncSession,
    *,
    rules: Rules | None = None,
    limit: int | None = None,
    neo4j_driver: AsyncDriver | None = None,
) -> ClusteringResult:
    """Cluster the signed corpus over the admitted Tier-1/2/3 edge graph — report-only.

    Deterministic and side-effect-free: it writes no ``Cluster`` row, calls no embed
    client, and does not commit. ``neo4j_driver`` is optional and used ONLY to count how
    many signed JDs have a document vector (a report column); clustering itself needs
    only Postgres. ``limit`` restricts the signed corpus for a smoke run."""
    rulebook = rules if rules is not None else get_rules()
    comparison = rulebook.comparison
    batch_size = get_settings().neardup_batch_size

    signed = await load_signed_corpus(pg_session, rules=rulebook, limit=limit)
    signed_ids = set(signed.signals)

    persisted = await _load_persisted_edges(pg_session, signed_ids)
    synthetic = synthesize_exact_edges(signed.refs)
    candidate_edges = persisted + synthetic

    admitted, drops = admit_edges(
        candidate_edges, signed.signals, comparison=comparison
    )

    components = build_clusters(
        [(edge.a, edge.b, edge.score) for edge in admitted],
        threshold=0.0,
        rules=rulebook,
    )
    records = _cluster_records(components, admitted, signed=signed, rules=rulebook)

    with_vector: int | None = None
    if neo4j_driver is not None and signed_ids:
        with_vector = await _count_vectors(
            neo4j_driver, sorted(signed_ids, key=str), batch_size=batch_size
        )

    return _assemble_result(
        signed=signed,
        signed_ids=signed_ids,
        candidate_edges=candidate_edges,
        admitted=admitted,
        drops=drops,
        synthetic=synthetic,
        records=records,
        comparison=comparison,
        with_vector=with_vector,
    )


def _assemble_result(
    *,
    signed: SignedCorpus,
    signed_ids: set[UUID],
    candidate_edges: Sequence[ClusterEdge],
    admitted: Sequence[ClusterEdge],
    drops: DropCounts,
    synthetic: Sequence[ClusterEdge],
    records: Sequence[ClusterRecord],
    comparison: Comparison,
    with_vector: int | None,
) -> ClusteringResult:
    clustered = sum(record.member_count for record in records)
    signed_count = len(signed_ids)
    size_distribution: Counter[int] = Counter(r.member_count for r in records)
    violation_counts: Counter[str] = Counter(
        violation for r in records for violation in r.constraint_violations
    )
    tier_contribution: Counter[str] = Counter(tier for r in records for tier in r.tiers)
    family_distribution: Counter[str] = Counter(
        sig.family for sig in signed.signals.values()
    )
    return ClusteringResult(
        documents_seen=signed.seen,
        documents_signed=signed_count,
        documents_unsignable=signed.unsignable,
        documents_with_vector=with_vector,
        singletons=signed_count - clustered,
        clustered_documents=clustered,
        coverage_rate=(clustered / signed_count) if signed_count else 0.0,
        edges_considered=len(candidate_edges),
        edges_admitted=len(admitted),
        tier_excluded=drops.tier_excluded,
        role_below_min=drops.role_below_min,
        band_vetoed=drops.band_vetoed,
        group_vetoed=drops.group_vetoed,
        exact_synthesized=len(synthetic),
        cluster_count=len(records),
        largest_cluster=max((r.member_count for r in records), default=0),
        size_distribution=dict(sorted(size_distribution.items())),
        cross_department_clusters=sum(1 for r in records if r.cross_department),
        cross_group_clusters=sum(1 for r in records if r.cross_group),
        restricted_touching_clusters=sum(1 for r in records if r.has_restricted),
        flagged_clusters=sum(1 for r in records if r.constraint_violations),
        violation_counts=dict(sorted(violation_counts.items())),
        tier_contribution=dict(sorted(tier_contribution.items())),
        cluster_tiers=tuple(sorted(comparison.cluster_tiers)),
        cluster_role_equiv_min=comparison.cluster_role_equiv_min,
        cluster_max_band_spread=comparison.cluster_max_band_spread,
        cluster_group_homogeneous=comparison.cluster_group_homogeneous,
        cluster_max_size=comparison.cluster_max_size,
        cluster_representative_policy=comparison.cluster_representative_policy,
        cluster_stamp=cluster_stamp(comparison),
        edge_method_stamps=tuple(sorted({edge.method for edge in admitted})),
        family_distribution=dict(sorted(family_distribution.items())),
        clusters=tuple(records),
    )

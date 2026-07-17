"""Tier-3 role-equivalence dedup — the SAME-ROLE pass (Phase 3.4b).

The chain, per run::

    parsed_jds (v2) -> build_job_signals per source_document_id  (skip unsignable)
        -> compute_idf over the corpus's skill bags             (deterministic, stamped)
        -> fetch doc vectors from Neo4j                          (batched; None is OK)
        -> candidates: bucket by JobSignals.function, cosine k-NN per JD,
           PLUS seed from Tier-2 NEAR_DUPLICATE edges            (dedup the pairs)
        -> HARD CONSTRAINTS at admission, BEFORE scoring:
             * family-band CONFLICT VETO (both mapped, >max_band_gap apart) — dropped
             * employee-group SOFT VETO  (both known, differ)               — dropped
             * restricted flag carried onto survivors
        -> SCORE each admissible pair: score_job_similarity(vector, skill, seniority)
        -> edge iff blended >= role_equiv_threshold
        -> RECONCILE against `dedup_edges WHERE tier = ROLE_EQUIVALENT`

**Tier-3 edges are NOT additive** (like Tier-2, unlike Tier-1). A role-equivalence edge
is only true relative to a threshold, a veto ladder and an idf corpus, so every run
computes the full ``plan`` its live config implies and reconciles it::

    insert = plan - present            (new edges)
    update = plan & present, differing  (score/method changed — never left stale)
    prune  = present - plan            (no longer implied by the live config — deleted)

``method = f"vec+skill@{stamp}"`` where ``stamp`` digests the scoring config + the idf
corpus, so a retune (or a corpus change that moves idf) re-stamps and re-reconciles
rather than leaving a provenance falsehood in the row.

**THE PRUNE SCOPE IS WHAT THIS RUN ACTUALLY SIGNED, NEVER WHAT IT MERELY FETCHED** — the
3.3 data-loss lesson, inherited. ``read_ids`` is exactly the documents this run turned
into :class:`~src.jd_core.models.bank.JobSignals` (and tried to fetch a vector for). A
JD:

* ``--limit`` never fetched, or
* that could not be VALIDATED/SIGNED at all (an UNKNOWN, not a "no"),

is out of prune scope, so ``present - plan`` can never delete its perfectly good
existing edges. A JD that WAS signed but has NO vector stays IN scope and scores with
``vector_score`` 0.0 — a deterministic function of the config and the JD, not an
unknown, so raising the threshold MUST prune it. Both directions are pinned by mutation.

**Never constructs an embed client.** The vectors are read straight from ``(:JDDocument
{id, embedding})`` nodes Phase 3.2b already wrote, exactly like Tier-2's cosine confirm.
Does **not** commit — the caller owns the transaction.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast
from uuid import UUID

from sqlalchemy import Table, bindparam, delete, select, tuple_, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.jd_bank.db.models import DedupEdge, DedupTier
from src.jd_bank.dedup.models import order_key
from src.jd_bank.dedup.role.idf import IdfCorpus, compute_idf
from src.jd_bank.dedup.role.models import (
    ROLE_EQUIV_VERSION,
    RoleDoc,
    RoleEdgeSpec,
    RolePairRecord,
    ScoredRolePair,
    Tier3Result,
)
from src.jd_bank.dedup.signals_load import load_signed_corpus
from src.jd_core.bank.similarity import (
    score_job_similarity,
    seniority_closeness,
    skill_overlap,
)
from src.jd_core.models.bank import JobSignals
from src.jd_core.rules import Comparison, Rules, get_rules
from src.settings import get_settings

if TYPE_CHECKING:
    from neo4j import AsyncDriver

#: The tier these edges carry.
ROLE_TIER = DedupTier.ROLE_EQUIVALENT
#: The Tier-2 tier whose edges seed guaranteed-admissible candidates.
NEAR_TIER = DedupTier.NEAR_DUPLICATE


# --- pure candidate generation -----------------------------------------------


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def generate_candidates(
    docs: Mapping[UUID, RoleDoc],
    near_dup_pairs: frozenset[frozenset[UUID]],
    *,
    comparison: Comparison,
) -> set[frozenset[UUID]]:
    """Candidate role-equivalence pairs — cosine k-NN within each ``function`` bucket,
    PLUS every Tier-2 near-dup seed (``seed_from_near_dup``, applied by the caller — a
    near-dup IS role-equivalent, and reaches Tier-3 even when a JD has no vector).

    Deterministic: buckets and neighbours are resolved in a fixed order (cosine
    descending, ties broken by id), so two runs over the same corpus generate the same
    candidate set. A JD with no vector is invisible to the cosine k-NN (no neighbours)
    but is still admissible as a near-dup seed."""
    candidates: set[frozenset[UUID]] = set()

    buckets: dict[str, list[UUID]] = defaultdict(list)
    for doc_id, doc in docs.items():
        if doc.vector is not None:
            buckets[doc.signals.function].append(doc_id)

    for members in buckets.values():
        members.sort(key=str)
        for doc_id in members:
            vector = docs[doc_id].vector
            assert vector is not None  # only vectored ids are bucketed
            scored = [
                (_cosine(vector, cast(tuple[float, ...], docs[other].vector)), other)
                for other in members
                if other != doc_id
            ]
            # cosine descending, id ascending for ties -> deterministic top-k.
            scored.sort(key=lambda item: (-item[0], str(item[1])))
            for _cos, neighbour in scored[: comparison.candidate_k]:
                candidates.add(frozenset((doc_id, neighbour)))

    for pair in near_dup_pairs:
        if len(pair) == 2 and all(member in docs for member in pair):
            candidates.add(pair)

    return candidates


# --- pure vetoes + scoring ---------------------------------------------------


def band_vetoes(a: JobSignals, b: JobSignals, comparison: Comparison) -> bool:
    """The HARD constraint: two titles whose seniority bands are more than
    ``max_band_gap`` apart are NEVER role-equivalent. Fires only when BOTH families map
    to a band (``family_band_ladder``); ``unmapped`` carries no band, so a pair with
    either side unmapped is never band-vetoed — the veto is PARTIAL by design (HR-155).
    """
    ladder = comparison.family_band_ladder
    band_a = ladder.get(a.family)
    band_b = ladder.get(b.family)
    if band_a is None or band_b is None:
        return False
    return abs(band_a - band_b) > comparison.max_band_gap


def group_vetoes(a: JobSignals, b: JobSignals, comparison: Comparison) -> bool:
    """The SOFT constraint: two JDs from DIFFERENT known employee groups are not the
    same role (HR-157). Vetoes only when BOTH sides state a group and they differ — a
    null is an unknown, never a conflict."""
    if not comparison.group_conflict_veto:
        return False
    if a.employee_group is None or b.employee_group is None:
        return False
    return a.employee_group != b.employee_group


def _education_rung(ordinal: int | None, comparison: Comparison) -> str | None:
    """Map ``JobSignals.education_ordinal`` (an index) back to the rung STRING
    ``seniority_closeness`` expects — ``None`` for an absent/off-ladder ordinal, so a
    missing signal never manufactures closeness."""
    if ordinal is None:
        return None
    ladder = comparison.education_ladder
    return ladder[ordinal] if 0 <= ordinal < len(ladder) else None


def score_role_pair(
    a: RoleDoc,
    b: RoleDoc,
    *,
    idf: Mapping[str, float],
    rules: Rules,
) -> ScoredRolePair:
    """Blend the three 2.4c components for one admissible pair. ``vector_score`` is the
    document-embedding cosine (0.0 when either side has no vector — the honest bimodal
    floor); ``skill_overlap`` is the idf-weighted keyword-bag Jaccard (families ``{}``,
    the ontology deferred, ADR-007); ``seniority`` blends the experience bar and the
    education ladder. Pure — no I/O."""
    comparison = rules.comparison
    if a.vector is not None and b.vector is not None:
        # Clamp to [0, 1]: the cosine of two near-identical 768-dim embeddings floats
        # ABOVE 1.0 by a float ulp (worst 1.0000000000000002; 16% of real NEAR_DUPLICATE
        # seed pairs overshoot). ``score_job_similarity`` clamps its own copy for the
        # blend, but this RAW component is stored verbatim into a ``[0, 1]`` field
        # (``RolePairRecord.vector_score``), so an unclamped >1.0 raises in
        # ``build_plan`` — a guaranteed archive-run crash. A cosine >1.0 is a float
        # artifact, not a real similarity, so clamp the value; don't widen the bound.
        vector_score = max(0.0, min(1.0, _cosine(a.vector, b.vector)))
    else:
        vector_score = 0.0
    skill_ov = skill_overlap(
        set(a.signals.skills), set(b.signals.skills), {}, idf=idf, rules=rules
    )
    seniority = seniority_closeness(
        a.signals.experience_years,
        b.signals.experience_years,
        _education_rung(a.signals.education_ordinal, comparison),
        _education_rung(b.signals.education_ordinal, comparison),
        rules=rules,
    )
    blended = score_job_similarity(vector_score, skill_ov, seniority, rules=rules)
    return ScoredRolePair(
        a=a,
        b=b,
        vector_score=vector_score,
        skill_overlap=skill_ov,
        seniority=seniority,
        blended=blended,
        restricted=a.signals.restricted or b.signals.restricted,
        same_function=a.signals.function == b.signals.function,
    )


@dataclass(frozen=True, slots=True)
class _Admission:
    scored: tuple[ScoredRolePair, ...]
    band_vetoed: int
    group_vetoed: int


def admit_and_score(
    candidates: set[frozenset[UUID]],
    docs: Mapping[UUID, RoleDoc],
    *,
    idf: Mapping[str, float],
    rules: Rules,
) -> _Admission:
    """Apply the hard constraints at admission (BEFORE scoring), then score the
    survivors. A vetoed candidate is COUNTED and dropped, never scored."""
    comparison = rules.comparison
    scored: list[ScoredRolePair] = []
    band_vetoed = 0
    group_vetoed = 0
    for pair in candidates:
        id_a, id_b = sorted(pair, key=str)
        doc_a, doc_b = docs[id_a], docs[id_b]
        if band_vetoes(doc_a.signals, doc_b.signals, comparison):
            band_vetoed += 1
            continue
        if group_vetoes(doc_a.signals, doc_b.signals, comparison):
            group_vetoed += 1
            continue
        scored.append(score_role_pair(doc_a, doc_b, idf=idf, rules=rules))
    return _Admission(
        scored=tuple(scored), band_vetoed=band_vetoed, group_vetoed=group_vetoed
    )


# --- the Tier-3 stamp --------------------------------------------------------


def tier3_stamp(comparison: Comparison, idf: IdfCorpus) -> str:
    """``<ROLE_EQUIV_VERSION>+<digest>`` over the SCORING config + the idf corpus — what
    rides in ``DedupEdge.method``. A retune of any scoring knob, a change to the veto
    ladder, or a corpus change that moves idf all move this stamp, so the reconcile
    re-stamps (UPDATE) or re-plans (PRUNE/INSERT) rather than leaving a stale row. The
    candidate-generation knobs (``candidate_k``, ``seed_from_near_dup``) are
    deliberately NOT here: they change which pairs are CONSIDERED — captured by plan
    membership —
    never a considered pair's score/method."""
    payload = json.dumps(
        {
            "role_equiv_threshold": comparison.role_equiv_threshold,
            "weight_vector": comparison.weight_vector,
            "weight_skill": comparison.weight_skill,
            "weight_seniority": comparison.weight_seniority,
            "family_band_ladder": dict(sorted(comparison.family_band_ladder.items())),
            "max_band_gap": comparison.max_band_gap,
            "group_conflict_veto": comparison.group_conflict_veto,
            "idf": idf.stamp,
        },
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"{ROLE_EQUIV_VERSION}+{digest[:12]}"


def _method_for(stamp: str, *, restricted: bool) -> str:
    base = f"vec+skill@{stamp}"
    return f"{base}+restricted" if restricted else base


# --- pure plan ---------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Plan:
    edges: dict[tuple[UUID, UUID], RoleEdgeSpec]
    pairs: tuple[RolePairRecord, ...]


def build_plan(
    scored: Sequence[ScoredRolePair], *, comparison: Comparison, stamp: str
) -> _Plan:
    """Every scored pair becomes a :class:`RolePairRecord` (reported, so a
    below-threshold candidate reaches the adjudication sample); a pair whose ``blended``
    clears ``role_equiv_threshold`` also becomes an oriented :class:`RoleEdgeSpec`,
    oriented by :func:`~src.jd_bank.dedup.models.order_key` — the order every tier uses.
    """
    edges: dict[tuple[UUID, UUID], RoleEdgeSpec] = {}
    pairs: list[RolePairRecord] = []
    for pair in scored:
        qualifies = pair.blended >= comparison.role_equiv_threshold
        if qualifies:
            first, second = sorted((pair.a.ref, pair.b.ref), key=order_key)
            edges[(first.id, second.id)] = RoleEdgeSpec(
                source_a_id=first.id,
                source_b_id=second.id,
                score=pair.blended,
                method=_method_for(stamp, restricted=pair.restricted),
            )
        pairs.append(
            RolePairRecord(
                filename_a=pair.a.ref.filename,
                filename_b=pair.b.ref.filename,
                score=pair.blended,
                vector_score=pair.vector_score,
                skill_overlap=pair.skill_overlap,
                seniority=pair.seniority,
                family_a=pair.a.signals.family,
                family_b=pair.b.signals.family,
                restricted=pair.restricted,
                same_function=pair.same_function,
                qualifies=qualifies,
            )
        )
    return _Plan(edges=edges, pairs=tuple(pairs))


# --- I/O: fetch vectors, fetch near-dup seeds --------------------------------
#
# The ``parsed_jds -> JobSignals`` load lives in :mod:`src.jd_bank.dedup.signals_load`
# (``load_signed_corpus``), shared with the Phase-3.5 clustering runner so the two
# callers cannot drift on which JDs are in scope.


async def _fetch_vectors(
    driver: AsyncDriver, ids: Sequence[UUID], *, batch_size: int
) -> dict[UUID, tuple[float, ...]]:
    """Every ``(:JDDocument {id, embedding})`` Phase 3.2b wrote, for exactly the ids
    this run signed. ONLY reads — never constructs an embed client, never writes a node.
    Chunked at ``batch_size`` (operational, mirrors Tier-2's ``_fetch_vectors``)."""
    if not ids:
        return {}
    vectors: dict[UUID, tuple[float, ...]] = {}
    async with driver.session() as neo_session:
        for start in range(0, len(ids), batch_size):
            chunk = ids[start : start + batch_size]
            result = await neo_session.run(
                "MATCH (d:JDDocument) WHERE d.id IN $ids "
                "RETURN d.id AS id, d.embedding AS embedding",
                ids=[str(i) for i in chunk],
            )
            async for record in result:
                if record["embedding"] is not None:
                    vectors[UUID(record["id"])] = tuple(record["embedding"])
    return vectors


async def _fetch_near_dup_pairs(
    session: AsyncSession, signed_ids: set[UUID]
) -> frozenset[frozenset[UUID]]:
    """Every Tier-2 ``NEAR_DUPLICATE`` edge whose BOTH endpoints this run signed.
    Matches on the enum (``DedupTier.NEAR_DUPLICATE``), exactly as Tier-2's own
    reconcile does — the column stores the enum NAME, so a raw string would have to be
    ``'NEAR_DUPLICATE'``, not ``'near_duplicate'``; using the enum avoids the trap."""
    rows = await session.execute(
        select(DedupEdge.source_a_id, DedupEdge.source_b_id).where(
            DedupEdge.tier == NEAR_TIER
        )
    )
    return frozenset(
        frozenset((a, b))
        for a, b in rows
        if a in signed_ids and b in signed_ids and a != b
    )


# --- the reconcile (mirrors Tier-2's, scoped to read_ids) --------------------


async def _reconcile(
    session: AsyncSession,
    plan: Mapping[tuple[UUID, UUID], RoleEdgeSpec],
    *,
    read_ids: set[UUID],
    scope_in_sql: bool,
    batch_size: int,
) -> tuple[int, int, int, int]:
    """``plan`` against ``dedup_edges WHERE tier = ROLE_EQUIVALENT``, scoped to
    ``read_ids``. Returns ``(written, updated, unchanged, pruned)``.

    ``read_ids`` is what this run SIGNED, never what it merely fetched: a JD that could
    not be signed produces no planned edge, so if it were in scope ``present - plan``
    would DELETE its perfectly good edges. It is enforced in PYTHON (below) so the
    ``--limit`` and unsignable cases cannot drift apart; ``scope_in_sql`` only bounds
    the SELECT's bind parameters on a limited run (65,535-parameter headroom, as
    Tier-2).
    """
    if not read_ids:
        return 0, 0, 0, 0

    stmt = select(
        DedupEdge.source_a_id,
        DedupEdge.source_b_id,
        DedupEdge.score,
        DedupEdge.method,
    ).where(DedupEdge.tier == ROLE_TIER)
    if scope_in_sql:
        stmt = stmt.where(
            DedupEdge.source_a_id.in_(read_ids),
            DedupEdge.source_b_id.in_(read_ids),
        )
    existing = await session.execute(stmt)

    present: dict[tuple[UUID, UUID], tuple[float, str]] = {
        (a, b): (score, method)
        for a, b, score, method in existing
        if a in read_ids and b in read_ids
    }

    plan_keys = set(plan)
    present_keys = set(present)
    to_insert = plan_keys - present_keys
    shared = plan_keys & present_keys
    to_update = [
        key for key in shared if present[key] != (plan[key].score, plan[key].method)
    ]
    to_prune = present_keys - plan_keys
    unchanged = len(shared) - len(to_update)

    insert_rows = [
        {
            "source_a_id": plan[key].source_a_id,
            "source_b_id": plan[key].source_b_id,
            "tier": ROLE_TIER,
            "score": plan[key].score,
            "method": plan[key].method,
        }
        for key in to_insert
    ]
    for start in range(0, len(insert_rows), batch_size):
        await session.execute(
            pg_insert(DedupEdge)
            .values(insert_rows[start : start + batch_size])
            .on_conflict_do_nothing(constraint="uq_dedup_pair_tier")
        )

    update_rows = [
        {
            "u_a": key[0],
            "u_b": key[1],
            "u_score": plan[key].score,
            "u_method": plan[key].method,
        }
        for key in to_update
    ]
    if update_rows:
        update_stmt = (
            update(cast(Table, DedupEdge.__table__))
            .where(
                DedupEdge.source_a_id == bindparam("u_a"),
                DedupEdge.source_b_id == bindparam("u_b"),
                DedupEdge.tier == ROLE_TIER,
            )
            .values(score=bindparam("u_score"), method=bindparam("u_method"))
        )
        for start in range(0, len(update_rows), batch_size):
            await session.execute(update_stmt, update_rows[start : start + batch_size])

    prune_list = list(to_prune)
    for start in range(0, len(prune_list), batch_size):
        chunk = prune_list[start : start + batch_size]
        await session.execute(
            delete(DedupEdge).where(
                DedupEdge.tier == ROLE_TIER,
                tuple_(DedupEdge.source_a_id, DedupEdge.source_b_id).in_(chunk),
            )
        )

    if to_update or to_prune:
        session.expire_all()

    return len(to_insert), len(to_update), unchanged, len(to_prune)


async def run_tier3(
    pg_session: AsyncSession,
    *,
    neo4j_driver: AsyncDriver | None,
    rules: Rules | None = None,
    limit: int | None = None,
) -> Tier3Result:
    """Find and reconcile Tier-3 role-equivalence edges over the v2 ``parsed_jds``.

    Re-runnable, and NOT merely additive — a pass over unchanged data + unchanged config
    reports ``edges_written == edges_updated == edges_pruned == 0``. Reads doc vectors
    from Neo4j (never embeds); ``neo4j_driver`` may be ``None`` for a vectors-off smoke
    run, in which case every pair scores with ``vector_score`` 0.0 and only
    skill+seniority carry the score. Does NOT commit — the caller owns the txn."""
    rulebook = rules if rules is not None else get_rules()
    comparison = rulebook.comparison
    batch_size = get_settings().neardup_batch_size

    signed = await load_signed_corpus(pg_session, rules=rulebook, limit=limit)
    signed_ids = set(signed.signals)

    idf = compute_idf(signed.signals[i].skills for i in sorted(signed_ids, key=str))

    vectors: dict[UUID, tuple[float, ...]] = {}
    if neo4j_driver is not None and signed_ids:
        vectors = await _fetch_vectors(
            neo4j_driver, sorted(signed_ids, key=str), batch_size=batch_size
        )

    docs: dict[UUID, RoleDoc] = {
        source_id: RoleDoc(
            ref=signed.refs[source_id],
            signals=signed.signals[source_id],
            vector=vectors.get(source_id),
        )
        for source_id in signed_ids
    }

    near_dup_pairs: frozenset[frozenset[UUID]] = frozenset()
    if comparison.seed_from_near_dup:
        near_dup_pairs = await _fetch_near_dup_pairs(pg_session, signed_ids)

    candidates = generate_candidates(docs, near_dup_pairs, comparison=comparison)
    admission = admit_and_score(candidates, docs, idf=idf.weights, rules=rulebook)

    stamp = tier3_stamp(comparison, idf)
    plan = build_plan(admission.scored, comparison=comparison, stamp=stamp)

    # THE PRUNE SCOPE: documents this run actually SIGNED — never an unsignable or
    # unfetched one. An unsignable JD is an unknown; pruning on it deletes real
    # findings.
    written, updated, unchanged, pruned = await _reconcile(
        pg_session,
        plan.edges,
        read_ids=signed_ids,
        scope_in_sql=limit is not None,
        batch_size=batch_size,
    )

    family_distribution: Counter[str] = Counter(
        signals.family for signals in signed.signals.values()
    )
    with_vector = sum(1 for doc in docs.values() if doc.vector is not None)
    qualifying = sum(1 for record in plan.pairs if record.qualifies)
    restricted_flagged = sum(
        1 for record in plan.pairs if record.qualifies and record.restricted
    )

    return Tier3Result(
        documents_seen=signed.seen,
        documents_signed=len(signed_ids),
        documents_unsignable=signed.unsignable,
        documents_with_vector=with_vector,
        documents_without_vector=len(signed_ids) - with_vector,
        candidate_pairs=len(candidates),
        band_vetoed=admission.band_vetoed,
        group_vetoed=admission.group_vetoed,
        admissible_pairs=len(admission.scored),
        qualifying_pairs=qualifying,
        restricted_flagged=restricted_flagged,
        edges_written=written,
        edges_updated=updated,
        edges_unchanged=unchanged,
        edges_pruned=pruned,
        role_equiv_threshold=comparison.role_equiv_threshold,
        max_band_gap=comparison.max_band_gap,
        candidate_k=comparison.candidate_k,
        seed_from_near_dup=comparison.seed_from_near_dup,
        group_conflict_veto=comparison.group_conflict_veto,
        idf_stamp=idf.stamp,
        idf_skills=idf.num_skills,
        dedup_stamp=stamp,
        family_distribution=dict(sorted(family_distribution.items())),
        pairs=plan.pairs,
    )

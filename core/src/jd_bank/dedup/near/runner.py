"""Tier-2 near-duplicate dedup — MinHash-candidate, exact-Jaccard-scored, DB-reconciled.

The chain, per run::

    source_documents (bounded by --limit)
        -> group by sha256, INCLUDING singletons (one unit per DISTINCT content)
        -> TextSource.text_for(representative)      -- injectable I/O boundary
        -> shingle_hashes (jd_core.bank.shingles)    -- min_shingles guard
        -> minhash_signature (jd_core.bank.minhash)  -- the CANDIDATE INDEX
        -> LSH banding -> candidate CONTENT pairs
        -> exact_jaccard (THE score, never the MinHash estimate)
        -> [optional] cosine confirm, reading Neo4j vectors directly (never embeds)
        -> expand qualifying content pairs per `edge_scope` (content: 1 edge;
           file: every cross-group file pair)
        -> RECONCILE against `dedup_edges WHERE tier = NEAR_DUPLICATE`

**Tier-2 edges are NOT additive, unlike Tier-1's.** Byte-identity never stops being
true; a Jaccard edge is only true relative to a threshold and a shingle config. So
every run computes the full ``plan`` its live config implies and reconciles it against
what is ``present`` in the database:

    insert = plan - present            (new edges)
    update = plan & present, differing  (score/method changed — never left stale)
    prune  = present - plan            (no longer implied by the live config — deleted)

Idempotency is a NUMBER: unchanged corpus + unchanged config ->
``edges_written == edges_updated == edges_pruned == 0``.

**THE PRUNE SCOPE IS WHAT THIS RUN ACTUALLY *READ*, NEVER WHAT IT MERELY FETCHED** —
and getting that wrong is a DATA-LOSS bug, not an inefficiency. Two ways to not have
looked at a document, and both must be out of prune scope:

* ``--limit`` never fetched its row at all;
* its text could not be OBTAINED (:attr:`_Signatures.unreadable_shas`) — a transient
  ``OSError``, an extractor hiccup, an unsupported format.

The second is the one the first cut got wrong: it built the scope from every row
FETCHED, so an unreadable document planned no edge and ``present - plan`` **deleted its
perfectly good existing edges**. On the shipped default (``ArchiveTextSource``
re-reading 14,452 files through antiword off a bind-mounted volume) a single hiccup
would silently destroy real findings. **An unreadable document is an UNKNOWN, not a
"no."** This is the same keep-list-before-the-risky-step discipline 3.2b established
(HANDOFF: *"the keep-list is derived BEFORE embedding, so a 400 or transient failure
never triggers a delete"*).

A document that WAS read but shingled below ``min_shingles`` stays IN scope, on
purpose: that is a deterministic function of the config and the text, so raising
``min_shingles`` MUST delete its edges. Both directions are pinned
(``test_an_unreadable_document_never_prunes_its_edges`` /
``test_a_document_below_min_shingles_does_prune_its_edges``).

**The EXACT/NEAR ladder — excluded by SHA256 EQUIVALENCE CLASS, not by "an EXACT edge
exists".** Tier-1's default topology is ``star``, not ``clique``, so in a byte-identical
group of N only N-1 of the N(N-1)/2 pairs carry an EXACT edge; a check keyed to
existing-EXACT-edges would write NEAR edges for the rest. This pass never performs that
check at all: candidate CONTENT pairs are generated over one :class:`~.models.Signature`
per DISTINCT ``sha256`` (see :func:`_group_all_by_sha256`), so two members of the SAME
sha256 group can never even become a candidate — the exclusion is structural, not a
runtime lookup. Under ``edge_scope: content`` this is also why the group's whole
membership never needs enumerating for candidate generation at all; under ``file`` scope
it still holds, because candidates are always generated at the content level FIRST and
only expanded into file-level pairs (:func:`_expand_endpoints`) for qualifying CONTENT
pairs — which, by construction, are between two DIFFERENT sha256 groups.

**Never constructs an embed client.** The cosine confirm only READS
``(:JDDocument {id, embedding})`` nodes Phase 3.2b already wrote; it has no code path
that could create one, so a test can populate Neo4j directly and never touch Ollama.

Does **not** commit — the caller owns the transaction, exactly like
:func:`~src.jd_bank.dedup.tier1.run_tier1`.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from itertools import combinations
from typing import TYPE_CHECKING, cast
from uuid import UUID

from sqlalchemy import Table, bindparam, delete, select, tuple_, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.jd_bank.db.models import DedupEdge, DedupTier, SourceDocument
from src.jd_bank.dedup.models import DocumentRef, order_key
from src.jd_bank.dedup.near.models import (
    CandidatePair,
    NearEdgeSpec,
    PairRecord,
    Signature,
    Tier2Result,
)
from src.jd_bank.dedup.near.text import TextSource
from src.jd_core.bank.minhash import band_keys, exact_jaccard, minhash_signature
from src.jd_core.bank.shingles import shingle_hashes
from src.jd_core.rules import CONTENT_HASH_LENGTH, Dedup, Rules, Segmentation, get_rules
from src.settings import get_settings

if TYPE_CHECKING:
    from neo4j import AsyncDriver

#: The tier these edges carry.
NEAR_TIER = DedupTier.NEAR_DUPLICATE


class CandidateOverflowError(RuntimeError):
    """The LSH banding generated more candidate pairs than ``dedup.max_candidate_pairs``
    allows. A safety valve, not a policy lever (registered TRIVIAL): it RAISES rather
    than silently truncating the candidate list, which would silently under-report
    edges with no record that it happened."""


async def _document_refs(
    session: AsyncSession, *, limit: int | None
) -> list[DocumentRef]:
    """Every ``source_documents`` row this run considers, deterministically ordered
    (so ``--limit`` takes the same files on every run) — mirrors
    ``ingest.driver._select_paths`` / ``embeddings.runner._candidate_rows``'s
    ``limit`` shape."""
    stmt = select(
        SourceDocument.id,
        SourceDocument.sha256,
        SourceDocument.storage_ref,
        SourceDocument.filename,
    ).order_by(SourceDocument.storage_ref, SourceDocument.id)
    if limit is not None:
        stmt = stmt.limit(limit)
    rows = await session.execute(stmt)
    return [
        DocumentRef(
            id=doc_id, sha256=sha256, storage_ref=storage_ref, filename=filename
        )
        for doc_id, sha256, storage_ref, filename in rows
    ]


def _group_all_by_sha256(
    refs: Sequence[DocumentRef],
) -> dict[str, list[DocumentRef]]:
    """Every ``sha256``'s members, INCLUDING singletons — unlike
    ``dedup.tier1.group_by_sha256`` (which only returns groups of 2+, because a
    "group" of one is not a Tier-1 FINDING), Tier-2 needs a unit for every distinct
    content, duplicated or not."""
    by_hash: dict[str, list[DocumentRef]] = defaultdict(list)
    for ref in refs:
        by_hash[ref.sha256].append(ref)
    return {
        sha256: sorted(members, key=order_key) for sha256, members in by_hash.items()
    }


@dataclass(frozen=True, slots=True)
class _Signatures:
    """What one signature-building pass produced, and — just as importantly — which
    documents it was actually able to READ.

    The read/unread split is not bookkeeping: it decides the PRUNE SCOPE (see
    :func:`_reconcile`). ``below_min`` shas are READ (their text was obtained; the
    rulebook then declined to sign them, which is a deterministic function of the
    config and the text) and therefore stay IN prune scope — raising ``min_shingles``
    MUST delete their edges. ``unreadable`` shas are an UNKNOWN, not a "no", and must
    NEVER prune.
    """

    signatures: dict[str, Signature]
    #: sha256s whose text was obtained (signed OR below ``min_shingles``).
    read_shas: set[str]
    #: sha256s whose text could not be obtained at all — counted, never pruned.
    unreadable_shas: set[str]
    below_min_shas: set[str]


async def _build_signatures(
    groups: Mapping[str, list[DocumentRef]],
    *,
    text_source: TextSource,
    dedup_rules: Dedup,
    boilerplate_passages: Sequence[str],
) -> _Signatures:
    """One :class:`Signature` per DISTINCT content — one text read, one shingle set,
    one MinHash signature per ``sha256``, never per file (memoization is structural:
    the loop is over ``groups``, keyed by ``sha256``, not over individual refs).

    Every sha256 lands in exactly one of :attr:`_Signatures.signatures`,
    :attr:`~_Signatures.below_min_shas` or :attr:`~_Signatures.unreadable_shas` —
    COUNTED, never silently dropped (they surface as
    :attr:`~.models.Tier2Result.documents_unreadable` /
    :attr:`~.models.Tier2Result.documents_below_min_shingles`) — and the first two
    together are :attr:`~_Signatures.read_shas`, the prune scope.
    """
    signatures: dict[str, Signature] = {}
    unreadable_shas: set[str] = set()
    below_min_shas: set[str] = set()
    for sha256, members in groups.items():
        representative = members[0]
        result = await text_source.text_for(representative)
        if result.text is None:
            unreadable_shas.add(sha256)
            continue

        hashes = shingle_hashes(
            result.text,
            shingle_size=dedup_rules.shingle_size,
            redact_boilerplate=dedup_rules.redact_boilerplate,
            boilerplate_passages=boilerplate_passages,
        )
        if len(hashes) < dedup_rules.min_shingles:
            below_min_shas.add(sha256)
            continue

        signatures[sha256] = Signature(
            id=representative.id,
            sha256=sha256,
            filename=representative.filename,
            storage_ref=representative.storage_ref,
            group_members=tuple(member.id for member in members),
            shingles=hashes,
            minhash=minhash_signature(hashes, dedup_rules.num_perm),
        )
    return _Signatures(
        signatures=signatures,
        read_shas=set(signatures) | below_min_shas,
        unreadable_shas=unreadable_shas,
        below_min_shas=below_min_shas,
    )


def _lsh_candidates(
    signatures: Mapping[str, Signature], *, dedup_rules: Dedup
) -> set[frozenset[str]]:
    """Every pair of DISTINCT ``sha256``s that share at least one LSH bucket.

    Raises:
        CandidateOverflowError: more than ``dedup.max_candidate_pairs`` candidates
            were generated — see the module + class docstrings. Checked as buckets
            are consumed, so an oversized run fails fast rather than after building
            the whole (potentially enormous) candidate set in memory.
    """
    buckets: dict[tuple[int, tuple[int, ...]], list[str]] = defaultdict(list)
    for sha256, signature in signatures.items():
        for key in band_keys(signature.minhash, dedup_rules.bands, dedup_rules.rows):
            buckets[key].append(sha256)

    candidates: set[frozenset[str]] = set()
    for members in buckets.values():
        if len(members) < 2:
            continue
        for a, b in combinations(sorted(members), 2):
            candidates.add(frozenset((a, b)))
            if len(candidates) > dedup_rules.max_candidate_pairs:
                raise CandidateOverflowError(
                    f"LSH banding generated more than "
                    f"{dedup_rules.max_candidate_pairs} candidate pairs — refusing "
                    f"to continue rather than silently truncate the candidate set. "
                    f"Re-tune bands/rows or raise max_candidate_pairs."
                )
    return candidates


def _cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


async def _fetch_vectors(
    driver: AsyncDriver, ids: Sequence[UUID], *, batch_size: int
) -> dict[UUID, list[float]]:
    """Every ``(:JDDocument {id, embedding})`` Phase 3.2b already wrote, for exactly
    the representative ids this run's candidates need. ONLY reads — never
    constructs an embed client, never writes a node. Chunked at ``batch_size``
    (``settings.neardup_batch_size`` — OPERATIONAL, never a rulebook decision: it
    cannot change which vectors come back, only how many round trips fetching them
    costs), the same discipline the embeddings runner applies to its own Neo4j
    round trips."""
    if not ids:
        return {}
    vectors: dict[UUID, list[float]] = {}
    async with driver.session() as session:
        for start in range(0, len(ids), batch_size):
            chunk = ids[start : start + batch_size]
            result = await session.run(
                "MATCH (d:JDDocument) WHERE d.id IN $ids "
                "RETURN d.id AS id, d.embedding AS embedding",
                ids=[str(i) for i in chunk],
            )
            async for record in result:
                if record["embedding"] is not None:
                    vectors[UUID(record["id"])] = list(record["embedding"])
    return vectors


def _score_candidates(
    candidates: set[frozenset[str]], signatures: Mapping[str, Signature]
) -> list[CandidatePair]:
    """EVERY candidate scored by EXACT Jaccard — NOT filtered to ``>= jaccard_min``
    here. Whether a candidate QUALIFIES is :func:`_build_plan`'s decision, not this
    function's: a candidate that misses the threshold is exactly what
    ``docs/dedup/near-dup-adjudication-sample.csv`` exists to surface to a human
    (HR-138 — the label set already showed the 0.85 bar is unratified), so it must
    still be REPORTED, not silently discarded before it is ever recorded anywhere.
    Cosine is computed later too (:func:`_build_plan`), because the confirm only
    ever applies to a Jaccard-qualifying candidate in the first place."""
    scored: list[CandidatePair] = []
    for pair in candidates:
        sha_a, sha_b = sorted(pair)
        sig_a, sig_b = signatures[sha_a], signatures[sha_b]
        jaccard = exact_jaccard(sig_a.shingles, sig_b.shingles)
        scored.append(CandidatePair(a=sig_a, b=sig_b, jaccard=jaccard, cosine=None))
    return scored


def _method_for(dedup_rules: Dedup, *, cosine: float | None) -> str:
    base = f"minhash+jaccard@{dedup_rules.digest[:CONTENT_HASH_LENGTH]}"
    return f"{base}+cosine" if cosine is not None else base


def _same_position(
    filename_a: str | None, filename_b: str | None, segmentation: Segmentation
) -> bool | None:
    """``True``/``False`` when both filenames yield a readable position id;
    ``None`` when either does not (mirrors ``FileFacets.position_id``'s "no signal"
    contract rather than defaulting to a guess)."""
    if filename_a is None or filename_b is None:
        return None
    ids_a = set(segmentation.position_id_pattern.findall(filename_a))
    ids_b = set(segmentation.position_id_pattern.findall(filename_b))
    if not ids_a or not ids_b:
        return None
    return bool(ids_a & ids_b)


def _expand_endpoints(
    pair: CandidatePair, *, edge_scope: str
) -> list[tuple[UUID, UUID]]:
    """The individual ``(source_document_id, source_document_id)`` pairs a
    QUALIFYING content pair implies. ``content``: one edge, between the two
    representatives. ``file``: every cross-group pair — the group each side's content
    actually spans, which is why two 11-member exact-duplicate groups that are
    near-dups of each other emit 121 edges under ``file`` scope and 1 under
    ``content``."""
    if edge_scope == "content":
        return [(pair.a.id, pair.b.id)]
    return [
        (member_a, member_b)
        for member_a in pair.a.group_members
        for member_b in pair.b.group_members
    ]


@dataclass(frozen=True, slots=True)
class _Plan:
    edges: dict[tuple[UUID, UUID], NearEdgeSpec]
    pairs: tuple[PairRecord, ...]
    cosine_vetoed: int


def _build_plan(
    scored: Sequence[CandidatePair],
    *,
    refs_by_id: Mapping[UUID, DocumentRef],
    dedup_rules: Dedup,
    segmentation: Segmentation,
    vectors: Mapping[UUID, list[float]] | None = None,
) -> _Plan:
    """Every scored candidate turned into the edges the live config implies, oriented
    by :func:`~src.jd_bank.dedup.models.order_key` — the SAME total order Tier-1
    uses, so ``uq_dedup_pair_tier`` (on the ORDERED triple) never sees a mirrored
    pair from either tier.

    EVERY candidate in ``scored`` gets a :class:`~.models.PairRecord` — including one
    that misses ``jaccard_min`` outright, so it is reported
    (:attr:`~.models.PairRecord.qualifies` ``False``), never silently discarded (see
    :func:`_score_candidates`). The cosine confirm is only ever evaluated for a
    candidate that already cleared ``jaccard_min`` — a low-Jaccard candidate is never
    worth a Neo4j round trip's information, since it cannot become an edge either way.
    """
    edges: dict[tuple[UUID, UUID], NearEdgeSpec] = {}
    pairs: list[PairRecord] = []
    cosine_vetoed = 0
    vector_map = vectors if vectors is not None else {}

    for pair in scored:
        same_position = _same_position(pair.a.filename, pair.b.filename, segmentation)
        meets_jaccard = pair.jaccard >= dedup_rules.jaccard_min

        if not meets_jaccard:
            pairs.append(
                PairRecord(
                    filename_a=pair.a.filename,
                    filename_b=pair.b.filename,
                    jaccard=pair.jaccard,
                    cosine=None,
                    same_position=same_position,
                    qualifies=False,
                )
            )
            continue

        cosine: float | None = None
        if dedup_rules.cosine_confirm_min is not None:
            vec_a, vec_b = vector_map.get(pair.a.id), vector_map.get(pair.b.id)
            if vec_a is not None and vec_b is not None:
                cosine = _cosine_similarity(vec_a, vec_b)
        vetoed = (
            dedup_rules.cosine_confirm_min is not None
            and cosine is not None
            and cosine < dedup_rules.cosine_confirm_min
        )

        if vetoed:
            cosine_vetoed += 1
            pairs.append(
                PairRecord(
                    filename_a=pair.a.filename,
                    filename_b=pair.b.filename,
                    jaccard=pair.jaccard,
                    cosine=cosine,
                    same_position=same_position,
                    qualifies=False,
                )
            )
            continue

        method = _method_for(dedup_rules, cosine=cosine)
        for member_a, member_b in _expand_endpoints(
            pair, edge_scope=dedup_rules.edge_scope
        ):
            first, second = sorted(
                (refs_by_id[member_a], refs_by_id[member_b]), key=order_key
            )
            edges[(first.id, second.id)] = NearEdgeSpec(
                source_a_id=first.id,
                source_b_id=second.id,
                score=pair.jaccard,
                method=method,
            )
        pairs.append(
            PairRecord(
                filename_a=pair.a.filename,
                filename_b=pair.b.filename,
                jaccard=pair.jaccard,
                cosine=cosine,
                same_position=same_position,
                qualifies=True,
            )
        )
    return _Plan(edges=edges, pairs=tuple(pairs), cosine_vetoed=cosine_vetoed)


async def _reconcile(
    session: AsyncSession,
    plan: Mapping[tuple[UUID, UUID], NearEdgeSpec],
    *,
    read_ids: set[UUID],
    scope_in_sql: bool,
    batch_size: int,
) -> tuple[int, int, int, int]:
    """``plan`` against what is PRESENT in the database, scoped to ``read_ids``.
    Returns ``(written, updated, unchanged, pruned)``.

    Unlike Tier-1's additive pass, this is a full reconcile: a Jaccard edge is only
    true relative to a threshold and a shingle config, so a config that no longer
    implies an edge must see it DELETED, not left behind as a provenance falsehood.

    **``read_ids`` is what this run actually READ, never what it merely FETCHED**, and
    the difference is a data-loss bug the reviewer probed rather than reasoned about.
    A document whose text could not be obtained at all (:attr:`_Signatures.
    unreadable_shas`) produces no signature, therefore no planned edge — so if it were
    in prune scope, ``present - plan`` would DELETE its perfectly good existing edges.
    On the shipped default (``ArchiveTextSource`` re-reading 14,452 files off a
    bind-mounted volume through antiword) one transient ``OSError`` would silently
    destroy real near-dup findings. An unreadable document is an **unknown, not a
    "no"**. This is the same keep-list-before-the-risky-step discipline 3.2b's embedding
    runner already established (HANDOFF: *"the keep-list is derived BEFORE embedding, so
    a 400 or transient failure never triggers a delete"*); the first cut of this module
    derived it AFTER the read, and so violated its own stated principle.

    A document that WAS read but shingled below ``min_shingles`` stays IN scope on
    purpose: that is a deterministic function of the config and the text, so raising
    ``min_shingles`` MUST delete its edges.

    ``scope_in_sql`` bounds the SELECT's bind parameters. On a full run (``limit is
    None``) it is ``False`` and the whole ``NEAR_DUPLICATE`` edge set is fetched
    unfiltered — because ``DedupEdge.source_a_id.in_(read_ids)`` AND
    ``.in_(read_ids)`` would render **2 x |read_ids|** bind parameters into one
    statement, i.e. 29,130 on today's archive against PostgreSQL's hard 65,535-parameter
    cap: 2.2x headroom, and a hard failure the moment ``source_documents`` passes
    ~32,768 rows. The ``read_ids`` filter is applied in PYTHON either way (below), so
    the SQL predicate is a pure row-count optimization for the ``--limit`` case and
    never a correctness term.
    """
    if not read_ids:
        return 0, 0, 0, 0

    stmt = select(
        DedupEdge.source_a_id,
        DedupEdge.source_b_id,
        DedupEdge.score,
        DedupEdge.method,
    ).where(DedupEdge.tier == NEAR_TIER)
    if scope_in_sql:
        stmt = stmt.where(
            DedupEdge.source_a_id.in_(read_ids),
            DedupEdge.source_b_id.in_(read_ids),
        )
    existing = await session.execute(stmt)

    # THE prune scope, and it is enforced HERE rather than in SQL so that the two
    # cases (`--limit`, and an unreadable document on a full run) cannot drift apart.
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
            "tier": NEAR_TIER,
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
        # Core-level `update(DedupEdge.__table__)`, NOT the ORM-enabled
        # `update(DedupEdge)` — SQLAlchemy 2.0's ORM bulk-UPDATE extension detects
        # the "executemany-style list of dict params" shape here and insists on a
        # primary-key WHERE clause, which this is not (it is WHERE-by-endpoint-pair).
        # No `DedupEdge` instances are held live across this call in this module, so
        # there is no ORM identity map to keep in sync — a plain Core statement is
        # both correct and simpler.
        update_stmt = (
            update(cast(Table, DedupEdge.__table__))
            .where(
                DedupEdge.source_a_id == bindparam("u_a"),
                DedupEdge.source_b_id == bindparam("u_b"),
                DedupEdge.tier == NEAR_TIER,
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
                DedupEdge.tier == NEAR_TIER,
                tuple_(DedupEdge.source_a_id, DedupEdge.source_b_id).in_(chunk),
            )
        )

    if to_update or to_prune:
        # The UPDATE/DELETE above are Core-level statements (see the comment on the
        # UPDATE), so they do NOT refresh or evict any `DedupEdge` ORM objects the
        # caller's session may already have loaded — an object read via this SAME
        # session before this reconcile ran would otherwise keep showing its
        # PRE-reconcile score/method (or keep "existing" after a prune) for the rest
        # of the session's life, which is exactly the stale-provenance failure mode
        # this whole pass exists to prevent. `expire_all()` performs no I/O itself
        # (SQLAlchemy re-fetches lazily on next access), so this is cheap even when
        # nothing in the identity map is actually affected.
        session.expire_all()

    return len(to_insert), len(to_update), unchanged, len(to_prune)


async def run_tier2(
    session: AsyncSession,
    *,
    rules: Rules | None = None,
    text_source: TextSource,
    neo4j_driver: AsyncDriver | None = None,
    limit: int | None = None,
) -> Tier2Result:
    """Find and reconcile Tier-2 near-duplicate edges over ``source_documents``.

    Re-runnable, and NOT merely additive (unlike :func:`~src.jd_bank.dedup.tier1.
    run_tier1`) — see the module docstring. A pass over an unchanged corpus with an
    unchanged rulebook reports ``edges_written == edges_updated == edges_pruned == 0``.

    ``neo4j_driver`` is required only when ``dedup.cosine_confirm_min`` is set; when
    it is ``None`` (the shipped default) or the driver is omitted, every candidate is
    judged on Jaccard alone. This function never constructs an embed client — it only
    reads ``(:JDDocument {embedding})`` nodes Phase 3.2b already wrote.

    Does NOT commit — the caller owns the transaction (mirrors ``run_tier1``). The
    caller should batch-commit for a real archive-scale run (see ``__main__.py``).
    """
    rulebook = rules if rules is not None else get_rules()
    dedup_rules = rulebook.dedup
    batch_size = get_settings().neardup_batch_size
    boilerplate = rulebook.boilerplate
    boilerplate_passages = (
        boilerplate.about_sfu
        + boilerplate.territorial_acknowledgement
        + boilerplate.employment_equity
    )

    refs = await _document_refs(session, limit=limit)
    refs_by_id = {ref.id: ref for ref in refs}
    groups = _group_all_by_sha256(refs)

    built = await _build_signatures(
        groups,
        text_source=text_source,
        dedup_rules=dedup_rules,
        boilerplate_passages=boilerplate_passages,
    )
    signatures = built.signatures

    candidates = _lsh_candidates(signatures, dedup_rules=dedup_rules)

    vectors: dict[UUID, list[float]] = {}
    if dedup_rules.cosine_confirm_min is not None and neo4j_driver is not None:
        needed_ids = {signatures[sha].id for pair in candidates for sha in pair}
        vectors = await _fetch_vectors(
            neo4j_driver, sorted(needed_ids, key=str), batch_size=batch_size
        )

    scored = _score_candidates(candidates, signatures)

    plan = _build_plan(
        scored,
        refs_by_id=refs_by_id,
        dedup_rules=dedup_rules,
        segmentation=rulebook.segmentation,
        vectors=vectors,
    )

    # THE PRUNE SCOPE: documents this run actually READ — every member of every
    # sha256 group whose text we obtained (signed OR below `min_shingles`), and NOT
    # the ones we merely fetched a row for. See `_reconcile`'s docstring: an
    # unreadable document is an unknown, and pruning on an unknown deletes real
    # findings.
    read_ids = {member.id for sha in built.read_shas for member in groups[sha]}
    written, updated, unchanged, pruned = await _reconcile(
        session,
        plan.edges,
        read_ids=read_ids,
        scope_in_sql=limit is not None,
        batch_size=batch_size,
    )

    return Tier2Result(
        documents_seen=len(refs),
        distinct_contents=len(groups),
        documents_unreadable=len(built.unreadable_shas),
        documents_below_min_shingles=len(built.below_min_shas),
        documents_signed=len(signatures),
        candidate_pairs=len(candidates),
        qualifying_pairs=sum(1 for record in plan.pairs if record.qualifies),
        cosine_vetoed=plan.cosine_vetoed,
        edges_written=written,
        edges_updated=updated,
        edges_unchanged=unchanged,
        edges_pruned=pruned,
        text_source=dedup_rules.text_source,
        edge_scope=dedup_rules.edge_scope,
        jaccard_min=dedup_rules.jaccard_min,
        cosine_confirm_min=dedup_rules.cosine_confirm_min,
        s_curve_threshold=dedup_rules.s_curve_threshold,
        dedup_stamp=dedup_rules.stamp,
        pairs=plan.pairs,
    )

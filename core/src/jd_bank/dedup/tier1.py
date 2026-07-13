"""Tier-1 exact-duplicate dedup — group by SHA-256, record the finding as edges.

**Dedup is a finding, not a collapse.** ``source_documents`` is a faithful ledger of the
archive (one row per file, migration ``0002``); this module says *which of those files
are byte-identical to which*, in ``dedup_edges``, at ``tier=EXACT`` with ``score=1.0``
and ``method="sha256"``. Nothing is deleted, nothing is merged, and no filename is lost.
That is the provenance contract (CLAUDE.md non-negotiable #6) the pre-3.1 schema could
not honour: with ``sha256`` unique, the duplicate never got a row, so it never got an
id, so the edge that needed two ids could never be written — ``DedupTier.EXACT`` was
dead code asserting a capability the schema forbade.

**MEASURED on the real archive** (14,565 files, this repo's own ``compute_sha256`` —
*not* the census's md5+shell toolchain, which is a different pipeline and had to be
re-verified): **1,037** groups of more than one file, **3,009** files in a group,
**1,972** redundant copies, **largest group 11**. Distribution: 616 pairs, 207 triples,
87 quads, then a thin tail. See ``docs/dedup/README.md``.

**Topology** (HR-123, ``comparison.exact_edge_topology``): ``star`` writes N-1 edges
from a canonical representative; ``clique`` writes all N(N-1)/2. Both implemented. The
default is ``star`` — byte-identity is an *equivalence relation*, so the clique's extra
edges are all recoverable by transitivity, and ``build_clusters`` gets the same
component from either. See the YAML for the full argument.

**Idempotent by construction.** The pass reads the edges that exist, writes only the
ones that do not, and orients every edge by one total order (:func:`order_key`) so
``(b, a)`` can never land beside ``(a, b)`` — which ``uq_dedup_pair_tier``, being on the
*ordered* triple, cannot catch by itself. It is additive: it never deletes an edge,
because every edge it has written stays true when the group grows.

**Two invariants, and they are INDEPENDENT. Both are required, and each has broken
once.**

*Stability.* Additive-only is what makes the representative's stability load-bearing: a
group keeps the rep its edges already **hub on** (:func:`_anchors`) instead of
re-deriving ``members[0]`` every pass. Without that, a duplicate arriving with a
``storage_ref`` that sorts before the incumbent re-anchors the star, the old star's
edges stay behind, and the two accumulate — measured on a group of 6 ingested in reverse
order, **15 edges: the full clique**, where a clean star is 5. The "star grows linearly"
property HR-123 asks HR to ratify, quietly gone. Pinned by
``test_the_star_stays_linear_under_worst_case_arrival_order``.

*Orientation.* ``source_a`` is **always** the earlier endpoint under :func:`order_key`,
in both topologies, and it **never** depends on who the representative is. The first fix
for the stability bug conflated the two — it oriented star edges *from the anchor*,
which points backwards for every member sorting before it, i.e. in exactly the case an
anchor exists to create. Measured on the same 6: 4 of the 5 star edges reversed, and a
later flip to ``clique`` produced **19 edges with 4 mirrored pairs** (a clean clique on
6 is 15 with none) — so the star was not a subset of the clique, and HR-123's "a flip
simply ADDS the missing pairs" was false of the code. Pinned by
``test_tier1_never_writes_both_directions_of_a_pair`` (which runs **after** a re-anchor:
on a fresh star the rep *is* ``members[0]``, so the two rules coincide and a fresh pass
cannot catch a violation) and
``test_flipping_to_clique_after_a_re_anchor_writes_no_mirrored_pairs``.

⚠ **Backlog — no "current version of a path".** The idempotency key is
``(storage_ref, sha256)``, so if the bytes at a path ever change, that path gets a
second row and nothing marks which is current. :func:`_document_refs` selects *all*
rows, so such a path would be counted twice in ``documents`` and could appear twice in
one duplicate group. The archive is READ-ONLY, so this cannot arise today — but a
mutable source (the Phase 5 composer upload) would need a ``superseded_at`` or
equivalent first.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from itertools import combinations
from typing import Final
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.jd_bank.db.models import DedupEdge, DedupTier, SourceDocument
from src.jd_bank.dedup.models import (
    DocumentRef,
    DuplicateGroup,
    EdgeSpec,
    Tier1Result,
    order_key,
)
from src.jd_core.rules import ExactEdgeTopology, Rules, get_rules

#: Byte-identity is not a similarity *estimate* — it is an identity. The score is 1.0
#: by definition and the method names the hash that established it. Neither is a knob:
#: a rulebook that could set the "confidence" of a SHA-256 match to 0.8 would be
#: describing something other than a SHA-256 match. (Tiers 2 and 3 produce genuine
#: scores; that is where a threshold belongs, and they are already registered.)
EXACT_SCORE: Final[float] = 1.0
EXACT_METHOD: Final[str] = "sha256"

#: The tier these edges carry. NB the enum member is ``EXACT`` (``"exact"``), which is
#: what ``0001`` created in Postgres — not ``EXACT_DUPLICATE``.
EXACT_TIER: Final[DedupTier] = DedupTier.EXACT


def group_by_sha256(refs: Iterable[DocumentRef]) -> list[DuplicateGroup]:
    """The duplicate groups among ``refs`` — every member kept, nothing collapsed.

    Only groups of **two or more** are returned: a file that is unique in the archive is
    not a duplicate of anything, and a "group" of one is not a finding. Refs are sorted
    within a group by :func:`order_key` and the groups by their hash, so two runs over
    the same corpus produce byte-identical output regardless of walk order.
    """
    by_hash: dict[str, list[DocumentRef]] = defaultdict(list)
    for ref in refs:
        by_hash[ref.sha256].append(ref)

    return [
        DuplicateGroup(sha256=sha256, members=tuple(sorted(members, key=order_key)))
        for sha256, members in sorted(by_hash.items())
        if len(members) > 1
    ]


def exact_edges(
    groups: Iterable[DuplicateGroup],
    *,
    topology: ExactEdgeTopology | None = None,
    rules: Rules | None = None,
    anchors: Mapping[str, UUID] | None = None,
) -> list[EdgeSpec]:
    """The edges ``groups`` imply, under the rulebook's topology (HR-123).

    ``star`` (default): an edge between the representative and each other member —
    N-1 edges. ``clique``: every unordered pair — N(N-1)/2.

    **WHO the representative is and HOW an edge is oriented are two different
    questions, and they must stay separate.** Both topologies orient *every* edge by
    the same total order (:func:`order_key`): ``source_a`` is always the earlier
    endpoint. The star is therefore always precisely the subset of the clique incident
    on the representative, and no two settings — and no two *passes* — can ever write
    ``(b, a)`` beside ``(a, b)``.

    That invariant is load-bearing **because the database cannot enforce it**:
    ``uq_dedup_pair_tier`` is on the *ordered* triple, so it accepts a mirrored pair
    without complaint.

    ⚠ The first fix for the star-degradation bug (below) got this wrong: it oriented
    star edges *from the anchor*, which points backwards for every member sorting
    before it — i.e. in exactly the case ``anchors`` exists to create. MEASURED on 6
    duplicates arriving in reverse order: 4 of the 5 star edges pointed backwards, and
    flipping to ``clique`` then produced **19 edges with 4 mirrored pairs**, where a
    clean clique on 6 is 15 with none. Orientation is now derived from ``order_key``
    alone, never from the anchor.

    ``anchors`` (``sha256 -> the member id the group's edges already hub on``) **pins a
    group's existing representative**, and it is what keeps the star a star. Without it
    the rep is recomputed from scratch on every pass as ``members[0]`` — so a duplicate
    arriving with a ``storage_ref`` that sorts *before* the incumbent rep RE-ANCHORS the
    star, and because the pass never deletes an edge, the old rep's edges stay behind.
    MEASURED: a group of 6 arriving in reverse sort order, one pass per arrival,
    accumulated **15 edges — the full clique** — where a clean star is 5. Every one of
    those edges is a *true* statement of byte-identity and ``build_clusters`` recovers
    the same component, so it was never a correctness bug — but it silently falsified
    the one property HR-123 asks HR to ratify (*"star grows linearly, clique
    quadratically"*). A register that states a property the code does not have is a
    provenance bug.

    The two properties are independent and both are required. :func:`run_tier1` supplies
    ``anchors`` from the edges already in the database, so an established group keeps
    the rep it was first given, whatever arrives later — while every edge it writes
    remains ``(earlier, later)``.
    """
    choice = (
        topology
        if topology is not None
        else (
            rules if rules is not None else get_rules()
        ).comparison.exact_edge_topology
    )
    pinned = anchors or {}
    edges: list[EdgeSpec] = []
    for group in groups:
        members = group.members  # already in canonical order
        if choice == "clique":
            pairs = list(combinations(members, 2))
        else:
            rep = group.representative_or(pinned.get(group.sha256))
            pairs = [(rep, member) for member in members if member.id != rep.id]
        # ONE orientation rule for both topologies, and it does not know what an anchor
        # is: source_a is always the earlier endpoint under `order_key`.
        edges += [
            EdgeSpec(source_a_id=first.id, source_b_id=second.id)
            for first, second in (sorted(pair, key=order_key) for pair in pairs)
        ]
    return edges


async def _document_refs(session: AsyncSession) -> list[DocumentRef]:
    rows = await session.execute(
        select(
            SourceDocument.id,
            SourceDocument.sha256,
            SourceDocument.storage_ref,
            SourceDocument.filename,
        )
    )
    return [
        DocumentRef(
            id=doc_id, sha256=sha256, storage_ref=storage_ref, filename=filename
        )
        for doc_id, sha256, storage_ref, filename in rows
    ]


async def _existing_edges(session: AsyncSession) -> list[tuple[UUID, UUID]]:
    rows = await session.execute(
        select(DedupEdge.source_a_id, DedupEdge.source_b_id).where(
            DedupEdge.tier == EXACT_TIER
        )
    )
    return [(a, b) for a, b in rows]


def _anchors(
    groups: Sequence[DuplicateGroup], existing: Iterable[tuple[UUID, UUID]]
) -> dict[str, UUID]:
    """Each group's ESTABLISHED representative — the member its edges **hub on** — keyed
    by sha256.

    This is what stops the star degrading into the clique (see :func:`exact_edges`). A
    member that arrives later and sorts first must **not** re-anchor the group: the
    incumbent rep is reused, so the pass adds exactly one edge for the newcomer.

    **The rep is the HUB, not ``source_a_id``.** Edges are oriented by
    :func:`order_key`, not from the anchor (that conflation was itself a bug — it wrote
    backwards edges and let a later ``clique`` flip mirror them). So the representative
    cannot be read off an edge's ``source_a``: in a star anchored on a late-sorting
    member, the rep is the ``source_b`` of every edge that precedes it. It is recovered
    structurally instead — **the member incident to *every* edge of the group**, which
    for a star is exactly one, whichever way the edges happen to point.

    Where a group has no single hub (edges written before this fix, or a rep deleted
    from the ledger, or a genuine ``clique``), the smallest member by :func:`order_key`
    that is incident to *any* edge wins — a deterministic choice, so two passes over the
    same data converge on one rep rather than oscillating. A newcomer can never be
    picked: it has no edges yet, so it is incident to none.
    """
    incident: dict[UUID, set[frozenset[UUID]]] = defaultdict(set)
    for a, b in existing:
        pair = frozenset((a, b))
        incident[a].add(pair)
        incident[b].add(pair)

    chosen: dict[str, UUID] = {}
    for group in groups:
        member_ids = {member.id for member in group.members}
        group_edges = {
            pair
            for member in group.members
            for pair in incident.get(member.id, ())
            if pair <= member_ids
        }
        if not group_edges:
            continue  # a brand-new group: `representative_or` falls back to members[0]
        touched = [
            member
            for member in group.members
            if incident.get(member.id, set()) & group_edges
        ]
        hubs = [
            member
            for member in touched
            if len(incident[member.id] & group_edges) == len(group_edges)
        ]
        chosen[group.sha256] = min(hubs or touched, key=order_key).id
    return chosen


async def run_tier1(
    session: AsyncSession, *, rules: Rules | None = None
) -> Tier1Result:
    """Group every ``source_documents`` row by SHA-256 and record the duplicates.

    Re-runnable. Three layers hold that:

    1. each group keeps the **representative it already has** (:func:`_anchors`), so a
       late-arriving duplicate joins the existing star instead of re-anchoring it — the
       property that makes ``star`` actually linear rather than merely N-1-per-pass;
    2. the edges already present are read first, so an unchanged corpus writes nothing
       (``edges_written == 0``, and the existing rows are not even rewritten — their
       ids and ``created_at`` survive, which an upsert-everything pass would churn);
    3. the insert is ``ON CONFLICT DO NOTHING`` on ``uq_dedup_pair_tier``, so a
       concurrent pass racing this one still cannot raise.

    The pass does not commit — the caller owns the transaction boundary, exactly as
    :func:`~src.jd_bank.ingest.ingest.ingest_document` does.
    """
    refs = await _document_refs(session)
    groups = group_by_sha256(refs)
    rulebook = rules if rules is not None else get_rules()
    topology = rulebook.comparison.exact_edge_topology

    existing = await _existing_edges(session)
    wanted = exact_edges(groups, rules=rulebook, anchors=_anchors(groups, existing))

    present = set(existing)
    missing = [
        edge for edge in wanted if (edge.source_a_id, edge.source_b_id) not in present
    ]
    if missing:
        await session.execute(
            pg_insert(DedupEdge)
            .values(
                [
                    {
                        "source_a_id": edge.source_a_id,
                        "source_b_id": edge.source_b_id,
                        "tier": EXACT_TIER,
                        "score": EXACT_SCORE,
                        "method": EXACT_METHOD,
                    }
                    for edge in missing
                ]
            )
            .on_conflict_do_nothing(constraint="uq_dedup_pair_tier")
        )

    return Tier1Result(
        documents=len(refs),
        groups=len(groups),
        files_in_groups=sum(group.size for group in groups),
        redundant_files=sum(group.redundant for group in groups),
        topology=topology,
        edges_written=len(missing),
        edges_existing=len(wanted) - len(missing),
    )


def edge_counts(groups: Sequence[DuplicateGroup]) -> tuple[int, int]:
    """``(star, clique)`` — what each topology would cost on ``groups``.

    Reported side by side in the artifact so HR-123 can be *read* rather than trusted:
    on the real archive, 1,972 against 4,068.
    """
    star = sum(group.redundant for group in groups)
    clique = sum(group.size * (group.size - 1) // 2 for group in groups)
    return star, clique

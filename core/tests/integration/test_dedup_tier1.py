"""Integration — the Tier-1 pass against a real Postgres, through the real migration.

Three things only a real database can prove, and all three were the reason 3.1 exists:

1. **The migration actually drops the unique constraint.** ``0002`` runs against a
   fresh Postgres via testcontainers; two rows with the same ``sha256`` then insert.
   Asserting it against ``Base.metadata`` would prove only that the ORM changed.
2. **``uq_dedup_pair_tier`` is respected.** The pass must be re-runnable: no
   ``IntegrityError``, no second copy of an edge, and never both ``(a, b)`` and
   ``(b, a)`` — which the constraint (on the *ordered* triple) cannot catch by itself.
3. **The pass is additive and incremental.** A duplicate that arrives later joins the
   group without disturbing the edges already written.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator, Sequence
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from testcontainers.postgres import PostgresContainer

from src.jd_bank.db.models import DedupEdge, DedupTier, DocumentFormat, SourceDocument
from src.jd_bank.dedup import EXACT_METHOD, EXACT_SCORE, run_tier1
from src.jd_core.bank import build_clusters
from src.jd_core.rules import get_rules
from tests.unit.retuned_rules import retuned

CORE_DIR = Path(__file__).resolve().parents[2]
ALEMBIC_INI = CORE_DIR / "alembic.ini"


@pytest.fixture(scope="module")
def migrated_pg_url() -> Iterator[str]:
    with PostgresContainer("postgres:16-alpine") as pg:
        url = pg.get_connection_url().replace("psycopg2", "asyncpg")
        cfg = Config(str(ALEMBIC_INI))
        cfg.set_main_option("sqlalchemy.url", url)
        command.upgrade(cfg, "head")
        yield url


@pytest.fixture(autouse=True)
async def clean_tables(migrated_pg_url: str) -> None:
    """``run_tier1`` is a pass over the WHOLE ``source_documents`` table, so every test
    here needs to own it. The container is module-scoped (starting one per test would
    cost minutes); the tables are truncated per test instead."""
    engine = create_async_engine(migrated_pg_url)
    async with engine.begin() as conn:
        await conn.exec_driver_sql(
            "TRUNCATE dedup_edges, source_documents RESTART IDENTITY CASCADE"
        )
    await engine.dispose()


async def _add(session: AsyncSession, storage_ref: str, sha256: str) -> SourceDocument:
    doc = SourceDocument(
        storage_ref=storage_ref,
        filename=storage_ref.rsplit("/", 1)[-1],
        sha256=sha256,
        fmt=DocumentFormat.DOCX,
        byte_size=1024,
    )
    session.add(doc)
    await session.flush()
    return doc


async def _edges(session: AsyncSession) -> list[DedupEdge]:
    result = await session.scalars(
        select(DedupEdge)
        .where(DedupEdge.tier == DedupTier.EXACT)
        .order_by(DedupEdge.source_a_id, DedupEdge.source_b_id)
    )
    return list(result.all())


def _sha(seed: str) -> str:
    return uuid.uuid5(uuid.NAMESPACE_OID, seed).hex * 2  # 64 hex chars


def _hubs(edges: Sequence[DedupEdge]) -> set[uuid.UUID]:
    """The nodes incident to EVERY edge — for a star, exactly the representative.

    The star's representative must be identified structurally, **not** as
    ``source_a_id``. ``source_a`` is decided by the canonical orientation (the earlier
    archive path) and says nothing about who the rep is: in a star anchored on a
    late-sorting member, the rep is the ``source_b`` of every edge that precedes it.
    Asserting ``source_a == rep`` is how the backwards-edge bug got written in the first
    place — it is only true when the rep happens to sort first.
    """
    if not edges:
        return set()
    incident = [{edge.source_a_id, edge.source_b_id} for edge in edges]
    return set.intersection(*incident)


# ── the migration ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_migration_drops_the_unique_sha256_and_keeps_the_index(
    migrated_pg_url: str,
) -> None:
    """The schema must be able to *state* that two archive files are byte-identical.
    Under ``unique=True`` it could not, which is why ``DedupEdge`` was dead code.

    The INDEX stays — it is the Tier-1 lookup key, and the pass groups by it.
    """
    engine = create_async_engine(migrated_pg_url)
    async with engine.connect() as conn:
        rows = await conn.exec_driver_sql(
            "SELECT indexname, indexdef FROM pg_indexes "
            "WHERE tablename = 'source_documents'"
        )
        indexes = {name: definition for name, definition in rows}
    await engine.dispose()

    sha_index = indexes["ix_source_documents_sha256"]
    assert "UNIQUE" not in sha_index.upper()
    assert "sha256" in sha_index
    # ...and the idempotency key that replaced it.
    assert any(
        "UNIQUE" in definition.upper()
        and "storage_ref" in definition
        and "sha256" in definition
        for definition in indexes.values()
    ), indexes


@pytest.mark.asyncio
async def test_two_rows_may_now_share_a_sha256(migrated_pg_url: str) -> None:
    engine = create_async_engine(migrated_pg_url)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    sha = _sha("shared")

    async with session_maker() as session:
        await _add(session, "archive/share_a.docx", sha)
        await _add(session, "archive/share_b.docx", sha)
        await session.commit()

        count = await session.scalar(
            select(func.count())
            .select_from(SourceDocument)
            .where(SourceDocument.sha256 == sha)
        )
        assert count == 2
    await engine.dispose()


# ── the Tier-1 pass ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_tier1_writes_a_star_of_exact_edges_per_duplicate_group(
    migrated_pg_url: str,
) -> None:
    engine = create_async_engine(migrated_pg_url)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    sha = _sha("star")

    async with session_maker() as session:
        docs = [await _add(session, f"archive/star_{i}.docx", sha) for i in range(4)]
        singleton = await _add(session, "archive/star_solo.docx", _sha("solo"))
        await session.commit()

        result = await run_tier1(session)
        await session.commit()

        assert result.groups == 1
        assert result.files_in_groups == 4
        assert result.redundant_files == 3
        assert result.edges_written == 3  # N - 1, the star

        edges = await _edges(session)
        assert len(edges) == 3
        # A fresh group: the rep IS members[0], so here (and only here) it is also every
        # edge's source_a. Both facts are asserted, because on a fresh star they agree.
        rep = docs[0].id  # archive/star_0.docx sorts first
        assert _hubs(edges) == {rep}
        assert {edge.source_a_id for edge in edges} == {rep}
        assert {edge.source_b_id for edge in edges} == {d.id for d in docs[1:]}
        assert all(edge.tier is DedupTier.EXACT for edge in edges)
        assert all(edge.score == EXACT_SCORE for edge in edges)
        assert all(edge.method == EXACT_METHOD for edge in edges)
        # A singleton has nothing to be a duplicate OF.
        ids = {edge.source_a_id for edge in edges} | {
            edge.source_b_id for edge in edges
        }
        assert singleton.id not in ids
    await engine.dispose()


@pytest.mark.asyncio
async def test_tier1_is_idempotent(migrated_pg_url: str) -> None:
    """**Definition of done.** Run it twice: the same edges, no constraint violation,
    nothing written the second time. A batch pass that cannot be re-run is a pass
    nobody dares re-run."""
    engine = create_async_engine(migrated_pg_url)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    sha = _sha("idem")

    async with session_maker() as session:
        for i in range(3):
            await _add(session, f"archive/idem_{i}.docx", sha)
        await session.commit()

        first = await run_tier1(session)
        await session.commit()
        before = [(e.source_a_id, e.source_b_id, e.id) for e in await _edges(session)]

        second = await run_tier1(session)
        await session.commit()
        after = [(e.source_a_id, e.source_b_id, e.id) for e in await _edges(session)]

    assert first.edges_written == 2
    assert second.edges_written == 0
    assert second.edges_existing == 2
    assert before == after  # same rows, same ids — not even rewritten
    await engine.dispose()


@pytest.mark.asyncio
async def test_tier1_never_writes_both_directions_of_a_pair(
    migrated_pg_url: str,
) -> None:
    """``uq_dedup_pair_tier`` is on the ORDERED triple, so it happily accepts ``(b, a)``
    next to ``(a, b)``. Only the canonical orientation stops that, and the DB is where
    it has to hold.

    **This runs AFTER a re-anchor, and that is the whole point.** On a fresh star the
    representative *is* ``members[0]``, so "oriented from the anchor" and "oriented by
    ``order_key``" coincide — a fresh pass cannot tell the two apart and cannot catch a
    violation. It took a member arriving *before* the incumbent rep (exactly the case
    ``_anchors`` exists to create) to expose that the first anchor fix was writing
    backwards edges.
    """
    engine = create_async_engine(migrated_pg_url)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    sha = _sha("orient")

    async with session_maker() as session:
        for i in range(3, 6):  # orient_3 .. orient_5; rep is orient_3
            await _add(session, f"archive/orient_{i}.docx", sha)
        await session.commit()
        await run_tier1(session)
        await session.commit()

        # Now three members that ALL sort before the established representative.
        for i in range(3):
            await _add(session, f"archive/orient_{i}.docx", sha)
        await session.commit()
        await run_tier1(session)
        await session.commit()

        edges = await _edges(session)
        assert len(edges) == 5  # still a star: N - 1 for N = 6
        pairs = {(e.source_a_id, e.source_b_id) for e in edges}
        assert not (pairs & {(b, a) for a, b in pairs}), "a mirrored pair was written"

        # ...and every edge points the canonical way: source_a is the EARLIER path.
        refs = {
            doc.id: doc.storage_ref
            for doc in (
                await session.scalars(
                    select(SourceDocument).where(SourceDocument.sha256 == sha)
                )
            ).all()
        }
        for edge in edges:
            assert refs[edge.source_a_id] < refs[edge.source_b_id], (
                f"edge points backwards: {refs[edge.source_a_id]} -> "
                f"{refs[edge.source_b_id]}"
            )
    await engine.dispose()


@pytest.mark.asyncio
async def test_flipping_to_clique_after_a_re_anchor_writes_no_mirrored_pairs(
    migrated_pg_url: str,
) -> None:
    """The two settings must never fight over ``uq_dedup_pair_tier`` — and the
    constraint cannot referee, because it is on the *ordered* pair.

    HR-123 promises a flip "simply ADDS the missing pairs". That is only true if the
    star was oriented by ``order_key`` rather than from its anchor. When it was not,
    this scenario produced **19 edges with 4 mirrored pairs**, where a clean clique on 6
    is 15 with none — so the star was not a subset of the clique at all, and the
    register's HR-facing claim was false of the code.
    """
    engine = create_async_engine(migrated_pg_url)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    rules = get_rules()
    sha = _sha("flip")

    async with session_maker() as session:
        # Six duplicates in reverse sort order, a pass after each -> a heavily
        # re-anchored star whose rep is NOT members[0].
        for i in reversed(range(6)):
            await _add(session, f"archive/flip_{i}.docx", sha)
            await session.commit()
            await run_tier1(session)
            await session.commit()

        star = await _edges(session)
        assert len(star) == 5
        star_pairs = {(e.source_a_id, e.source_b_id) for e in star}

        # ...now HR flips the knob. Nothing is deleted; the clique must absorb the star.
        await run_tier1(session, rules=retuned(rules, exact_edge_topology="clique"))
        await session.commit()

        clique = await _edges(session)
        clique_pairs = {(e.source_a_id, e.source_b_id) for e in clique}

        assert len(clique) == 15, "6*5/2 — a mirrored pair would push this to 19"
        assert not (clique_pairs & {(b, a) for a, b in clique_pairs})
        # The promise HR-123 makes: the star's rows are STILL THERE, untouched.
        assert star_pairs < clique_pairs
    await engine.dispose()


@pytest.mark.asyncio
async def test_a_late_arriving_duplicate_does_not_re_anchor_the_star(
    migrated_pg_url: str,
) -> None:
    """**The star must stay a star.** The pass is additive — it never deletes an edge —
    so the representative has to be STABLE, or the stars pile up.

    The member added here sorts BEFORE the incumbent representative, which is the case
    that used to re-anchor the group: the rep was re-derived as ``members[0]`` on every
    pass, the old rep's edges stayed behind, and the two stars accumulated. This asserts
    the exact edge count (``N - 1``), not merely ``>= 1`` — the loose assertion is what
    let the bug through the first time.
    """
    engine = create_async_engine(migrated_pg_url)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    sha = _sha("late")

    async with session_maker() as session:
        early = [
            await _add(session, f"archive/late_{i}.docx", sha) for i in range(1, 3)
        ]
        await session.commit()
        await run_tier1(session)
        await session.commit()
        rep = early[0].id  # archive/late_1.docx — the incumbent

        # ...and a member that sorts BEFORE it shows up.
        newcomer = await _add(session, "archive/late_0.docx", sha)
        await session.commit()
        again = await run_tier1(session)
        await session.commit()

        assert again.edges_written == 1  # exactly ONE new edge: the newcomer's

        edges = await _edges(session)
        assert len(edges) == 2  # N - 1 for N = 3. A clique would be 3.
        # ...and they still HUB on the original rep, not on the sort-first newcomer.
        # NB the hub, not source_a: the newcomer's edge is (newcomer -> rep), because
        # orientation follows the archive path and never the anchor.
        assert _hubs(edges) == {rep}
        assert _hubs(edges) != {newcomer.id}

        component = build_clusters(
            [(e.source_a_id, e.source_b_id, e.score) for e in edges], threshold=1.0
        )
        assert len(component) == 1
        assert set(component[0]) == {newcomer.id, *(d.id for d in early)}
    await engine.dispose()


@pytest.mark.asyncio
async def test_the_star_stays_linear_under_worst_case_arrival_order(
    migrated_pg_url: str,
) -> None:
    """The reviewer's falsifying case, as a regression test.

    Six duplicates arriving in **reverse sort order**, with a Tier-1 pass after each —
    so *every* arrival is a candidate to re-anchor the star. Before the fix this left
    **15 edges: the full clique**, and quietly falsified the one property HR-123 asks HR
    to ratify ("star grows linearly, clique quadratically"). It must be 5 edges around
    exactly 1 hub.

    The hub settles on ``rev_4``, and that is worth spelling out because it is not the
    first *file* to arrive. A group does not exist until its SECOND member lands — at
    which point it is ``{rev_4, rev_5}`` and its rep is ``members[0]``, i.e. ``rev_4``.
    Every later arrival sorts before it, and none of them re-anchor it. So ``rev_5``,
    the earliest arrival, is a leaf, and the four later arrivals are leaves too.

    Which means every one of the 5 edges has a *different* ``source_a`` (each
    earlier-sorting member points at the hub, and one edge points from the hub to
    ``rev_5``). That is precisely why the representative must be identified as the HUB
    and never as ``source_a`` — and why the orientation check below still passes.
    """
    engine = create_async_engine(migrated_pg_url)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    sha = _sha("reverse")

    async with session_maker() as session:
        docs: dict[str, uuid.UUID] = {}
        for i in reversed(range(6)):  # arrives 5, 4, 3, 2, 1, 0 — worst case
            doc = await _add(session, f"archive/rev_{i}.docx", sha)
            docs[f"rev_{i}"] = doc.id
            await session.commit()
            await run_tier1(session)
            await session.commit()

        edges = await _edges(session)
        assert len(edges) == 5, "the star degraded — N-1 is 5, the clique is 15"
        # ONE hub, and it is the rep the group was born with — never re-anchored.
        assert _hubs(edges) == {docs["rev_4"]}, "the star was re-anchored"
        # ...and it is NOT every edge's source_a, which is the whole point.
        assert len({edge.source_a_id for edge in edges}) == 5

        # ...and the orientation invariant held throughout, even though the hub sorts
        # LAST: every edge still runs earlier-path -> later-path.
        refs = {
            doc.id: doc.storage_ref
            for doc in (
                await session.scalars(
                    select(SourceDocument).where(SourceDocument.sha256 == sha)
                )
            ).all()
        }
        for edge in edges:
            assert refs[edge.source_a_id] < refs[edge.source_b_id]

        component = build_clusters(
            [(e.source_a_id, e.source_b_id, e.score) for e in edges], threshold=1.0
        )
        assert len(component[0]) == 6
    await engine.dispose()

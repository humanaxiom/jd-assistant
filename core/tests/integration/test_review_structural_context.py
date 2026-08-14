"""Integration — the Phase-8.3b structural context against a real Postgres.

**Only a real database can prove any of this**, which is why there is no unit-test
counterpart:

1. **Cluster membership is a JSONB array** of ``{"source_id": …, "filename": …}``
   objects, so every membership test goes through ``jsonb_array_elements``. A fake
   session would return whatever the test handed it and prove nothing.
2. **A Tier-3 edge is stored ORIENTED** (writers orient on a structural total order over
   the endpoints) while being **undirected in intent**. A cluster can therefore sit on
   either side of an edge, and a query that checks only one side silently halves the
   list — which looks exactly like a correct, shorter list.

**What "related" means here.** A cross-cluster ``ROLE_EQUIVALENT`` edge exists exactly
when a pair scored at or above the Tier-3 pair bar (0.5) but **below the clustering
merge bar** (``cluster_role_equiv_min`` = 0.75, HR-162). Measured over the live archive,
**zero** of the 32,816 cross-cluster Tier-3 edges reach 0.75 — so this list is the set
of near-misses the clustering step ruled on, not incidental neighbours.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterator

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from testcontainers.postgres import PostgresContainer

from src.jd_bank.db.models import (
    CanonicalJD,
    CanonicalStatus,
    Cluster,
    DedupEdge,
    DedupTier,
    DocumentFormat,
    SourceDocument,
)
from src.jd_bank.review import RelatedRole, get_structural_context
from tests.integration.test_dedup_tier1 import ALEMBIC_INI
from tests.integration.test_review_service import _clean_jd


@pytest.fixture(scope="module")
def migrated_pg_url() -> Iterator[str]:
    with PostgresContainer("postgres:16-alpine") as pg:
        url = pg.get_connection_url().replace("psycopg2", "asyncpg")
        cfg = Config(str(ALEMBIC_INI))
        cfg.set_main_option("sqlalchemy.url", url)
        command.upgrade(cfg, "head")
        yield url


@pytest.fixture
async def session_maker(
    migrated_pg_url: str,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(migrated_pg_url)
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM dedup_edges"))
        await conn.execute(text("DELETE FROM canonical_jds"))
        await conn.execute(text("DELETE FROM source_documents"))
        await conn.execute(text("DELETE FROM clusters"))
    maker = async_sessionmaker(engine, expire_on_commit=False)
    yield maker
    await engine.dispose()


async def _source(session: AsyncSession, name: str) -> SourceDocument:
    source = SourceDocument(
        storage_ref=f"/archive/{name}.doc",
        filename=f"{name}.doc",
        sha256=uuid.uuid4().hex,
        fmt=DocumentFormat.DOC,
        byte_size=1024,
    )
    session.add(source)
    await session.flush()
    return source


async def _role(
    session: AsyncSession, sources: list[SourceDocument], *, title: str
) -> tuple[uuid.UUID, CanonicalJD]:
    """A cluster over ``sources`` plus its current canonical — one role, as the archive
    stores it."""
    cluster_id = uuid.uuid4()
    session.add(
        Cluster(
            id=cluster_id,
            label=title,
            members=[{"source_id": str(s.id), "filename": s.filename} for s in sources],
        )
    )
    await session.flush()
    canonical = CanonicalJD(
        cluster_id=cluster_id,
        version=1,
        status=CanonicalStatus.DRAFT,
        content=_clean_jd(title=title).model_dump(mode="json"),
        source_document_ids=[],
        change_log={},
    )
    session.add(canonical)
    await session.flush()
    return cluster_id, canonical


async def _edge(
    session: AsyncSession,
    a: SourceDocument,
    b: SourceDocument,
    *,
    tier: DedupTier = DedupTier.ROLE_EQUIVALENT,
) -> None:
    session.add(
        DedupEdge(
            source_a_id=a.id, source_b_id=b.id, tier=tier, score=0.6, method="test"
        )
    )
    await session.flush()


@pytest.mark.asyncio
async def test_related_roles_are_found_from_either_edge_orientation(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    """🔴 THE ONE THAT MATTERS. A cluster can sit on either side of an oriented edge.
    Check only ``source_a in mine`` and the list silently halves — and a half-empty
    sidebar is indistinguishable from a correct one."""
    async with session_maker() as session:
        mine_src = await _source(session, "mine")
        left_src = await _source(session, "left")
        right_src = await _source(session, "right")
        _, canonical = await _role(session, [mine_src], title="Mine")
        left_id, _ = await _role(session, [left_src], title="Left Neighbour")
        right_id, _ = await _role(session, [right_src], title="Right Neighbour")
        # One edge with my source on side A, one with my source on side B.
        await _edge(session, mine_src, left_src)
        await _edge(session, right_src, mine_src)
        canonical_id = canonical.id
        await session.commit()

    async with session_maker() as session:
        context = await get_structural_context(session, canonical_id)

    assert context is not None
    assert {r.cluster_id for r in context.related} == {left_id, right_id}


@pytest.mark.asyncio
async def test_near_duplicate_edges_are_not_related_roles(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    """Tier-2 is deliberately not consulted: near-duplicates are clustered TOGETHER by
    construction, so a cross-cluster one is an anomaly (16 in the whole live archive),
    not a relationship worth a reviewer's attention. Widen the tier filter, go red."""
    async with session_maker() as session:
        mine_src = await _source(session, "mine")
        other_src = await _source(session, "other")
        _, canonical = await _role(session, [mine_src], title="Mine")
        await _role(session, [other_src], title="Near Duplicate")
        await _edge(session, mine_src, other_src, tier=DedupTier.NEAR_DUPLICATE)
        canonical_id = canonical.id
        await session.commit()

    async with session_maker() as session:
        context = await get_structural_context(session, canonical_id)

    assert context is not None
    assert context.related == ()


@pytest.mark.asyncio
async def test_intra_cluster_edges_are_not_related_roles(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    """The edges INSIDE this cluster are what built it. Listing the role as related to
    itself would be noise, and would crowd the real near-misses out of a capped list."""
    async with session_maker() as session:
        first = await _source(session, "first")
        second = await _source(session, "second")
        _, canonical = await _role(session, [first, second], title="Mine")
        await _edge(session, first, second)
        canonical_id = canonical.id
        await session.commit()

    async with session_maker() as session:
        context = await get_structural_context(session, canonical_id)

    assert context is not None
    assert context.related == ()


@pytest.mark.asyncio
async def test_related_roles_rank_by_how_many_documents_connect_them(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    """Ranked by a COUNT of connecting source documents — a fact about the archive —
    never by the edge score, which on this corpus has unrelated roles outscoring true
    twins. The count is also the only number the page may honestly display."""
    async with session_maker() as session:
        mine_src = await _source(session, "mine")
        weak_src = await _source(session, "weak")
        strong_a = await _source(session, "strong_a")
        strong_b = await _source(session, "strong_b")
        _, canonical = await _role(session, [mine_src], title="Mine")
        weak_id, _ = await _role(session, [weak_src], title="Weakly Connected")
        strong_id, _ = await _role(
            session, [strong_a, strong_b], title="Strongly Connected"
        )
        await _edge(session, mine_src, weak_src)
        await _edge(session, mine_src, strong_a)
        await _edge(session, mine_src, strong_b)
        canonical_id = canonical.id
        await session.commit()

    async with session_maker() as session:
        context = await get_structural_context(session, canonical_id)

    assert context is not None
    assert [r.cluster_id for r in context.related] == [strong_id, weak_id]
    assert [r.connecting_documents for r in context.related] == [2, 1]


def test_a_related_role_carries_no_similarity_score() -> None:
    """Pinned as a SHAPE, not a rendering detail: role similarity on this corpus was
    measured to have unrelated roles outscoring true twins, so a number here would be a
    false precision the data cannot support. Add one and this goes red."""
    assert "score" not in RelatedRole.model_fields
    assert "similarity" not in RelatedRole.model_fields


@pytest.mark.asyncio
async def test_a_related_role_with_no_canonical_is_listed_unlinked(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    """A cluster that has no canonical JD yet is still shown, without a link, rather
    than dropped: absent from the list, it would be indistinguishable from "no such
    relationship", which is a different and false statement."""
    async with session_maker() as session:
        mine_src = await _source(session, "mine")
        bare_src = await _source(session, "bare")
        _, canonical = await _role(session, [mine_src], title="Mine")
        bare_cluster = uuid.uuid4()
        session.add(
            Cluster(
                id=bare_cluster,
                label="No canonical yet",
                members=[{"source_id": str(bare_src.id), "filename": "bare.doc"}],
            )
        )
        await session.flush()
        await _edge(session, mine_src, bare_src)
        canonical_id = canonical.id
        await session.commit()

    async with session_maker() as session:
        context = await get_structural_context(session, canonical_id)

    assert context is not None
    assert [r.cluster_id for r in context.related] == [bare_cluster]
    assert context.related[0].canonical_id is None


@pytest.mark.asyncio
async def test_the_versions_tree_marks_exactly_the_current_canonical(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    """v1 → v2 in order with exactly one marked current, so the sidebar highlights it
    without re-deriving which one the reviewer is looking at."""
    async with session_maker() as session:
        source = await _source(session, "only")
        cluster_id, first = await _role(session, [source], title="Mine")
        second = CanonicalJD(
            cluster_id=cluster_id,
            version=2,
            status=CanonicalStatus.DRAFT,
            content=_clean_jd(title="Edited").model_dump(mode="json"),
            source_document_ids=[],
            change_log={},
        )
        first.status = CanonicalStatus.PUBLISHED
        session.add(second)
        await session.flush()
        second_id = second.id
        await session.commit()

    async with session_maker() as session:
        context = await get_structural_context(session, second_id)

    assert context is not None
    assert [v.version for v in context.versions] == [1, 2]
    assert [v.is_current for v in context.versions] == [False, True]


@pytest.mark.asyncio
async def test_structural_context_is_none_for_an_unknown_id(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    async with session_maker() as session:
        assert await get_structural_context(session, uuid.uuid4()) is None

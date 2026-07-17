"""Integration — the Phase-3.5 clustering pass against a real Postgres, through the real
migration. What only a real database can prove:

1. NEAR/ROLE ``dedup_edges`` + ``parsed_jds`` become the expected connected components.
2. EXACT connectivity is SYNTHESIZED from ``source_documents.sha256`` — byte-identical
   files with NO near-dup edge (Tier-2 keeps one signature/content) cluster together.
3. Cluster ids are content-derived (``uuid5``) — two runs produce identical ids.
4. An UNSIGNABLE JD is out of scope: it never crashes and never lands in a cluster.
5. The pass writes NO ``Cluster`` row (the CASCADE hazard) and commits nothing.
6. The shared ``load_signed_corpus`` partitions signable/unsignable and keeps the
   unsignable out of scope (the direct test of the extracted loader).

No Neo4j: clustering is over the edge graph, so ``run_clustering`` is called with
``neo4j_driver=None`` (``documents_with_vector`` is a nicety, not a clustering input).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterator

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from testcontainers.postgres import PostgresContainer

from src.jd_bank.cluster.runner import run_clustering
from src.jd_bank.db.models import (
    Cluster,
    DedupEdge,
    DedupTier,
    DocumentFormat,
    ParsedJDRow,
    SourceDocument,
)
from src.jd_bank.dedup.signals_load import load_signed_corpus
from src.jd_core.models.parsed_jd import SFUJobDescription, SFUQualification
from src.jd_core.parser import PARSER_VERSION
from src.jd_core.rules import get_rules
from tests.integration.test_dedup_tier1 import ALEMBIC_INI


def _sha(seed: str) -> str:
    return uuid.uuid5(uuid.NAMESPACE_OID, seed).hex * 2  # 64 hex chars


def _analyst() -> dict[str, object]:
    return SFUJobDescription(
        title="Analyst",
        employee_group="apsa",
        qualifications=[SFUQualification(text="python sql database", kind="skill")],
    ).model_dump(mode="json")


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
        await conn.execute(text("DELETE FROM source_documents"))
    maker = async_sessionmaker(engine, expire_on_commit=False)
    yield maker
    await engine.dispose()


async def _seed(
    session: AsyncSession,
    *,
    storage_ref: str,
    sha256: str,
    parsed: dict[str, object],
    confidence: float = 1.0,
) -> SourceDocument:
    doc = SourceDocument(
        storage_ref=storage_ref,
        filename=storage_ref.rsplit("/", 1)[-1],
        sha256=sha256,
        fmt=DocumentFormat.DOCX,
        byte_size=1024,
    )
    session.add(doc)
    await session.flush()
    session.add(
        ParsedJDRow(
            source_document_id=doc.id,
            parsed=parsed,
            parser_version=PARSER_VERSION,
            parse_confidence=confidence,
        )
    )
    return doc


async def _role_edge(
    session: AsyncSession, a: uuid.UUID, b: uuid.UUID, score: float
) -> None:
    lo, hi = sorted((a, b), key=str)
    session.add(
        DedupEdge(
            source_a_id=lo,
            source_b_id=hi,
            tier=DedupTier.ROLE_EQUIVALENT,
            score=score,
            method="vec+skill@test",
        )
    )


@pytest.mark.asyncio
async def test_edges_and_parsed_jds_become_the_expected_clusters(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    async with session_maker() as session:
        a = await _seed(session, storage_ref="a", sha256=_sha("a"), parsed=_analyst())
        b = await _seed(session, storage_ref="b", sha256=_sha("b"), parsed=_analyst())
        c = await _seed(session, storage_ref="c", sha256=_sha("c"), parsed=_analyst())
        await _seed(session, storage_ref="d", sha256=_sha("d"), parsed=_analyst())
        await _role_edge(session, a.id, b.id, 0.9)
        await _role_edge(session, b.id, c.id, 0.9)
        await session.commit()

        result = await run_clustering(session, rules=get_rules(), neo4j_driver=None)

        assert result.documents_signed == 4
        assert result.cluster_count == 1
        assert result.largest_cluster == 3
        assert result.singletons == 1
        cluster = result.clusters[0]
        assert {m.source_id for m in cluster.members} == {a.id, b.id, c.id}
        assert "role_equivalent" in cluster.tiers


@pytest.mark.asyncio
async def test_a_role_edge_below_the_gate_does_not_cluster(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    async with session_maker() as session:
        a = await _seed(session, storage_ref="a", sha256=_sha("a"), parsed=_analyst())
        b = await _seed(session, storage_ref="b", sha256=_sha("b"), parsed=_analyst())
        await _role_edge(session, a.id, b.id, 0.6)  # below cluster_role_equiv_min 0.75
        await session.commit()

        result = await run_clustering(session, rules=get_rules(), neo4j_driver=None)
        assert result.cluster_count == 0
        assert result.role_below_min == 1


@pytest.mark.asyncio
async def test_byte_identical_files_cluster_via_synthesized_exact(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    """Two byte-identical files (same sha, different path) have NO near-dup edge —
    Tier-2 keeps one signature per content. The runner synthesizes EXACT connectivity so
    they reunite."""
    shared = _sha("identical")
    async with session_maker() as session:
        a = await _seed(session, storage_ref="a", sha256=shared, parsed=_analyst())
        b = await _seed(session, storage_ref="b", sha256=shared, parsed=_analyst())
        await session.commit()

        result = await run_clustering(session, rules=get_rules(), neo4j_driver=None)
        assert result.exact_synthesized >= 1
        assert result.cluster_count == 1
        assert {m.source_id for m in result.clusters[0].members} == {a.id, b.id}
        assert "exact" in result.clusters[0].tiers


@pytest.mark.asyncio
async def test_cluster_ids_are_deterministic_across_runs(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    async with session_maker() as session:
        a = await _seed(session, storage_ref="a", sha256=_sha("a"), parsed=_analyst())
        b = await _seed(session, storage_ref="b", sha256=_sha("b"), parsed=_analyst())
        await _role_edge(session, a.id, b.id, 0.9)
        await session.commit()

        first = await run_clustering(session, rules=get_rules(), neo4j_driver=None)
        second = await run_clustering(session, rules=get_rules(), neo4j_driver=None)
        assert [c.cluster_id for c in first.clusters] == [
            c.cluster_id for c in second.clusters
        ]


@pytest.mark.asyncio
async def test_an_unsignable_jd_is_out_of_scope_and_never_clustered(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    async with session_maker() as session:
        a = await _seed(session, storage_ref="a", sha256=_sha("a"), parsed=_analyst())
        b = await _seed(session, storage_ref="b", sha256=_sha("b"), parsed=_analyst())
        # ...and a third whose parse cannot be signed (missing the required title).
        ghost = await _seed(
            session, storage_ref="z", sha256=_sha("z"), parsed={"not_a_title": 1}
        )
        await _role_edge(session, a.id, b.id, 0.9)
        await _role_edge(session, a.id, ghost.id, 0.9)  # edge onto the unsignable one
        await session.commit()

        result = await run_clustering(session, rules=get_rules(), neo4j_driver=None)
        assert result.documents_unsignable == 1
        assert result.documents_signed == 2
        clustered = {m.source_id for c in result.clusters for m in c.members}
        assert ghost.id not in clustered
        assert clustered == {a.id, b.id}


@pytest.mark.asyncio
async def test_clustering_writes_no_cluster_row_and_does_not_commit(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    async with session_maker() as session:
        a = await _seed(session, storage_ref="a", sha256=_sha("a"), parsed=_analyst())
        b = await _seed(session, storage_ref="b", sha256=_sha("b"), parsed=_analyst())
        await _role_edge(session, a.id, b.id, 0.9)
        await session.commit()

        await run_clustering(session, rules=get_rules(), neo4j_driver=None)
        # The pass persists nothing to the Cluster table (the CASCADE hazard).
        count = await session.scalar(select(func.count()).select_from(Cluster))
        assert count == 0
        await session.rollback()

    async with session_maker() as session:
        count = await session.scalar(select(func.count()).select_from(Cluster))
        assert count == 0


@pytest.mark.asyncio
async def test_the_shared_loader_partitions_signable_from_unsignable(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    """The direct test of the extracted ``load_signed_corpus``: a signable JD lands in
    scope (signals/refs/confidence keyed by its id); an unsignable one is COUNTED, kept
    OUT of scope — never a key, so it can never fall into a prune/cluster set."""
    async with session_maker() as session:
        good = await _seed(
            session,
            storage_ref="a",
            sha256=_sha("a"),
            parsed=_analyst(),
            confidence=0.9,
        )
        bad = await _seed(
            session, storage_ref="z", sha256=_sha("z"), parsed={"not_a_title": 1}
        )
        await session.commit()

        corpus = await load_signed_corpus(session, rules=get_rules(), limit=None)
        assert corpus.seen == 2
        assert corpus.unsignable == 1
        assert set(corpus.signals) == {good.id}
        assert set(corpus.refs) == {good.id}
        assert corpus.confidence[good.id] == pytest.approx(0.9)
        assert bad.id not in corpus.signals

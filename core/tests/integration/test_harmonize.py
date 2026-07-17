"""Integration — the Phase-4.1 harmonization measurement pass against a real Postgres,
through the real migration. What only a real database can prove:

1. Clusters are RECOMPUTED in-process and their JDFN members harmonized (no CSV read).
2. WJQ (CUPE) members are DROPPED from a mixed cluster and COUNTED — never silent.
3. A cluster that is entirely WJQ is excluded whole and counted.
4. ``load_member_jds`` drops an unvalidatable row with a counter (drop-not-crash).
5. The pass writes NO Cluster/CanonicalJD row and commits nothing (read-only).
6. Two runs over the same DB produce a byte-identical result body (deterministic).

No Neo4j: harmonization is over the recomputed edge-graph clusters, which need only PG.
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

from src.jd_bank.db.models import (
    CanonicalJD,
    Cluster,
    DedupEdge,
    DedupTier,
    DocumentFormat,
    ParsedJDRow,
    SourceDocument,
)
from src.jd_bank.dedup.signals_load import load_member_jds
from src.jd_bank.harmonize.runner import run_harmonization
from src.jd_core.models.parsed_jd import SFUJobDescription, SFUQualification
from src.jd_core.parser import PARSER_VERSION
from src.jd_core.rules import Rules, get_rules
from tests.integration.test_dedup_tier1 import ALEMBIC_INI


def _sha(seed: str) -> str:
    return uuid.uuid5(uuid.NAMESPACE_OID, seed).hex * 2  # 64 hex chars


def _analyst(group: str = "apsa", title: str = "Analyst") -> dict[str, object]:
    return SFUJobDescription(
        title=title,
        employee_group=group,  # type: ignore[arg-type]
        qualifications=[SFUQualification(text="python sql database", kind="skill")],
    ).model_dump(mode="json")


@pytest.fixture(scope="module")
def rules() -> Rules:
    return get_rules()


def _no_group_veto(rules: Rules) -> Rules:
    """Rules with the employee-group veto OFF, so an APSA+CUPE pair can share a cluster
    — the only way to construct a MIXED JDFN/WJQ cluster (the veto blocks it in prod,
    which is why real mixed clusters are ~0; the runner still handles the branch)."""
    return rules.model_copy(
        update={
            "comparison": rules.comparison.model_copy(
                update={"group_conflict_veto": False}
            )
        }
    )


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
    session: AsyncSession, a: uuid.UUID, b: uuid.UUID, score: float = 0.9
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
async def test_jdfn_cluster_is_recomputed_and_harmonized(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    async with session_maker() as session:
        a = await _seed(session, storage_ref="a", sha256=_sha("a"), parsed=_analyst())
        b = await _seed(session, storage_ref="b", sha256=_sha("b"), parsed=_analyst())
        c = await _seed(session, storage_ref="c", sha256=_sha("c"), parsed=_analyst())
        await _role_edge(session, a.id, b.id)
        await _role_edge(session, b.id, c.id)
        await session.commit()

        result = await run_harmonization(session, rules=get_rules())
        assert result.harmonized_clusters == 1
        assert result.multi_member_clusters == 1
        assert result.jdfn_members_merged == 3
        assert result.wjq_members_dropped == 0
        assert result.clusters[0].jdfn_member_count == 3


@pytest.mark.asyncio
async def test_wjq_members_are_dropped_from_a_mixed_cluster_and_counted(
    session_maker: async_sessionmaker[AsyncSession], rules: Rules
) -> None:
    async with session_maker() as session:
        a = await _seed(session, storage_ref="a", sha256=_sha("a"), parsed=_analyst())
        b = await _seed(session, storage_ref="b", sha256=_sha("b"), parsed=_analyst())
        # A CUPE (WJQ-proxy) member welded in only because the group veto is off.
        w = await _seed(
            session, storage_ref="w", sha256=_sha("w"), parsed=_analyst(group="cupe")
        )
        await _role_edge(session, a.id, b.id)
        await _role_edge(session, b.id, w.id)
        await session.commit()

        result = await run_harmonization(session, rules=_no_group_veto(rules))
        # The cluster has 3 members; ONE is WJQ and is dropped, leaving 2 JDFN merged.
        assert result.wjq_members_dropped == 1
        assert result.clusters_mixed_jdfn_wjq == 1
        assert result.harmonized_clusters == 1
        assert result.clusters[0].jdfn_member_count == 2
        assert result.clusters[0].wjq_members_dropped == 1


@pytest.mark.asyncio
async def test_a_fully_wjq_cluster_is_excluded_whole_and_counted(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    async with session_maker() as session:
        a = await _seed(
            session, storage_ref="a", sha256=_sha("a"), parsed=_analyst(group="cupe")
        )
        b = await _seed(
            session, storage_ref="b", sha256=_sha("b"), parsed=_analyst(group="cupe")
        )
        await _role_edge(session, a.id, b.id)
        await session.commit()

        result = await run_harmonization(session, rules=get_rules())
        assert result.clusters_fully_wjq_excluded == 1
        assert result.harmonized_clusters == 0
        assert result.wjq_members_dropped == 2
        assert result.clusters == ()


@pytest.mark.asyncio
async def test_load_member_jds_drops_an_unvalidatable_row_with_a_counter(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    async with session_maker() as session:
        good = await _seed(
            session, storage_ref="a", sha256=_sha("a"), parsed=_analyst()
        )
        bad = await _seed(
            session, storage_ref="z", sha256=_sha("z"), parsed={"not_a_title": 1}
        )
        await session.commit()

        jds, dropped = await load_member_jds(session, [good.id, bad.id])
        assert set(jds) == {good.id}
        assert dropped == 1


@pytest.mark.asyncio
async def test_harmonization_writes_no_row_and_does_not_commit(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    async with session_maker() as session:
        a = await _seed(session, storage_ref="a", sha256=_sha("a"), parsed=_analyst())
        b = await _seed(session, storage_ref="b", sha256=_sha("b"), parsed=_analyst())
        await _role_edge(session, a.id, b.id)
        await session.commit()

        await run_harmonization(session, rules=get_rules())
        assert await session.scalar(select(func.count()).select_from(Cluster)) == 0
        assert await session.scalar(select(func.count()).select_from(CanonicalJD)) == 0
        await session.rollback()

    async with session_maker() as session:
        assert await session.scalar(select(func.count()).select_from(Cluster)) == 0


@pytest.mark.asyncio
async def test_two_runs_are_byte_identical(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    async with session_maker() as session:
        a = await _seed(session, storage_ref="a", sha256=_sha("a"), parsed=_analyst())
        b = await _seed(
            session,
            storage_ref="b",
            sha256=_sha("b"),
            parsed=_analyst(title="Senior Analyst"),
        )
        c = await _seed(session, storage_ref="c", sha256=_sha("c"), parsed=_analyst())
        await _role_edge(session, a.id, b.id)
        await _role_edge(session, b.id, c.id)
        await session.commit()

        first = await run_harmonization(session, rules=get_rules())
        second = await run_harmonization(session, rules=get_rules())
        # The result body carries no per-run noise (generated_at lives on the summary).
        assert first.model_dump() == second.model_dump()

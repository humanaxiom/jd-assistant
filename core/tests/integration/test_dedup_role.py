"""Integration — the Tier-3 role-equivalence pass against a real Postgres + Neo4j,
through the real migration (Phase 3.4b).

What only a real database + vector store can prove:

1. Edges are WRITTEN, oriented by ``order_key``, and scored by the blended similarity.
2. The reconcile is real, not additive: raising ``role_equiv_threshold`` DELETES an edge
   that no longer qualifies; changing a scoring weight UPDATES a surviving edge's
   score/method (a naive ``ON CONFLICT DO NOTHING`` goes green on both, leaving stale).
3. ``--limit`` and an UNSIGNABLE JD never prune edges they did not read (the 3.3
   data-loss lesson, both directions pinned).
4. A JD with NO document vector still scores (``vector_score`` 0.0), not crashed on.
5. ``run_tier3`` never commits, and it leaves EXACT/NEAR edges (other tiers) untouched.

The document vectors are written STRAIGHT into testcontainers Neo4j (no Ollama, no embed
client) — the whole point: ``run_tier3`` only READS ``(:JDDocument {embedding})``.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterator

import pytest
from alembic import command
from alembic.config import Config
from neo4j import AsyncDriver, AsyncGraphDatabase
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from testcontainers.neo4j import Neo4jContainer
from testcontainers.postgres import PostgresContainer

from src.jd_bank.db.models import (
    DedupEdge,
    DedupTier,
    DocumentFormat,
    ParsedJDRow,
    SourceDocument,
)
from src.jd_bank.dedup.role.runner import run_tier3
from src.jd_core.models.parsed_jd import SFUJobDescription, SFUQualification
from src.jd_core.parser import PARSER_VERSION
from src.jd_core.rules import get_rules
from tests.integration.test_dedup_tier1 import ALEMBIC_INI
from tests.unit.retuned_rules import retuned


def _sha(seed: str) -> str:
    return uuid.uuid5(uuid.NAMESPACE_OID, seed).hex * 2  # 64 hex chars


def _analyst_jd() -> SFUJobDescription:
    """An APSA Analyst with a non-empty, distinctive skill bag — so two copies score
    high on skills AND vectors, not just on the empty-skill floor."""
    return SFUJobDescription(
        title="Analyst",
        employee_group="apsa",
        qualifications=[SFUQualification(text="python sql database", kind="skill")],
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


@pytest.fixture(scope="module")
def neo4j_container() -> Iterator[Neo4jContainer]:
    with Neo4jContainer("neo4j:5-community") as neo:
        yield neo


@pytest.fixture
async def neo4j_driver(neo4j_container: Neo4jContainer) -> AsyncIterator[AsyncDriver]:
    driver = AsyncGraphDatabase.driver(
        neo4j_container.get_connection_url(), auth=("neo4j", neo4j_container.password)
    )
    async with driver.session() as session:
        await session.run("MATCH (n) DETACH DELETE n")
    yield driver
    await driver.close()


async def _seed_jd(
    session: AsyncSession,
    *,
    storage_ref: str,
    sha256: str,
    parsed: dict[str, object],
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
            parse_confidence=1.0,
        )
    )
    return doc


async def _write_vector(
    driver: AsyncDriver, doc_id: uuid.UUID, embedding: list[float]
) -> None:
    async with driver.session() as session:
        await session.run(
            "MERGE (d:JDDocument {id: $id}) SET d.embedding = $embedding",
            id=str(doc_id),
            embedding=embedding,
        )


async def _role_edges(session: AsyncSession) -> list[DedupEdge]:
    result = await session.scalars(
        select(DedupEdge)
        .where(DedupEdge.tier == DedupTier.ROLE_EQUIVALENT)
        .order_by(DedupEdge.source_a_id, DedupEdge.source_b_id)
    )
    return list(result.all())


async def _seed_a_b(
    session_maker: async_sessionmaker[AsyncSession], driver: AsyncDriver
) -> tuple[SourceDocument, SourceDocument]:
    jd = _analyst_jd().model_dump(mode="json")
    async with session_maker() as session:
        doc_a = await _seed_jd(
            session, storage_ref="archive/analyst_a.docx", sha256=_sha("a"), parsed=jd
        )
        doc_b = await _seed_jd(
            session, storage_ref="archive/analyst_b.docx", sha256=_sha("b"), parsed=jd
        )
        await session.commit()
    # Identical vectors -> vector_score 1.0, so the blend floors at 0.45*1.0 + 0.10*0.7
    # = 0.52 >= threshold EVEN when the idf corpus is small enough to zero the skill
    # term (df==N makes ln(N/(1+df)) collapse — honest idf, but it must not decide these
    # tests).
    await _write_vector(driver, doc_a.id, [1.0, 0.0, 0.0])
    await _write_vector(driver, doc_b.id, [1.0, 0.0, 0.0])
    return doc_a, doc_b


@pytest.mark.asyncio
async def test_edges_are_written_oriented_and_scored(
    session_maker: async_sessionmaker[AsyncSession], neo4j_driver: AsyncDriver
) -> None:
    doc_a, doc_b = await _seed_a_b(session_maker, neo4j_driver)
    rules = get_rules()

    async with session_maker() as session:
        result = await run_tier3(session, neo4j_driver=neo4j_driver, rules=rules)
        await session.commit()

        assert result.documents_signed == 2
        assert result.qualifying_pairs == 1
        assert result.edges_written == 1

        edges = await _role_edges(session)
        assert len(edges) == 1
        edge = edges[0]
        # oriented: "archive/analyst_a.docx" < "archive/analyst_b.docx"
        assert edge.source_a_id == doc_a.id
        assert edge.source_b_id == doc_b.id
        assert 0.5 <= edge.score <= 1.0
        assert edge.method.startswith("vec+skill@")
        assert edge.method == f"vec+skill@{result.dedup_stamp}"


@pytest.mark.asyncio
async def test_second_pass_over_unchanged_data_writes_nothing(
    session_maker: async_sessionmaker[AsyncSession], neo4j_driver: AsyncDriver
) -> None:
    await _seed_a_b(session_maker, neo4j_driver)
    rules = get_rules()

    async with session_maker() as session:
        first = await run_tier3(session, neo4j_driver=neo4j_driver, rules=rules)
        await session.commit()
        before = [(e.id, e.score, e.method) for e in await _role_edges(session)]

        second = await run_tier3(session, neo4j_driver=neo4j_driver, rules=rules)
        await session.commit()
        after = [(e.id, e.score, e.method) for e in await _role_edges(session)]

    assert first.edges_written == 1
    assert (second.edges_written, second.edges_updated, second.edges_pruned) == (
        0,
        0,
        0,
    )
    assert second.edges_unchanged == 1
    assert before == after


@pytest.mark.asyncio
async def test_raising_the_threshold_prunes_the_edge_that_no_longer_qualifies(
    session_maker: async_sessionmaker[AsyncSession], neo4j_driver: AsyncDriver
) -> None:
    await _seed_a_b(session_maker, neo4j_driver)
    rules = get_rules()
    strict = retuned(rules, role_equiv_threshold=0.99)  # above the ~0.97 blend

    async with session_maker() as session:
        first = await run_tier3(session, neo4j_driver=neo4j_driver, rules=rules)
        await session.commit()
        assert first.edges_written == 1

        second = await run_tier3(session, neo4j_driver=neo4j_driver, rules=strict)
        await session.commit()

        assert second.edges_pruned == 1
        assert second.edges_written == 0
        assert await _role_edges(session) == []


@pytest.mark.asyncio
async def test_changing_a_scoring_weight_updates_the_edge_not_leaves_it_stale(
    session_maker: async_sessionmaker[AsyncSession], neo4j_driver: AsyncDriver
) -> None:
    await _seed_a_b(session_maker, neo4j_driver)
    base = get_rules()
    reweighted = retuned(
        base, weight_vector=0.40, weight_skill=0.45, weight_seniority=0.15
    )

    async with session_maker() as session:
        await run_tier3(session, neo4j_driver=neo4j_driver, rules=base)
        await session.commit()
        before = (await _role_edges(session))[0]
        before_id, before_score, before_method = (
            before.id,
            before.score,
            before.method,
        )

        result = await run_tier3(session, neo4j_driver=neo4j_driver, rules=reweighted)
        await session.commit()

        assert (result.edges_written, result.edges_pruned) == (0, 0)
        assert result.edges_updated == 1
        after = (await _role_edges(session))[0]
        assert after.id == before_id  # UPDATEd, not deleted + reinserted
        assert after.score != before_score
        assert after.method != before_method
        assert after.method == f"vec+skill@{result.dedup_stamp}"


@pytest.mark.asyncio
async def test_limit_does_not_prune_an_edge_it_never_read(
    session_maker: async_sessionmaker[AsyncSession], neo4j_driver: AsyncDriver
) -> None:
    doc_a, doc_b = await _seed_a_b(session_maker, neo4j_driver)
    rules = get_rules()

    async with session_maker() as session:
        # an outsider whose storage_ref sorts BEFORE both analysts, so limit=1 reads it
        # alone and never touches doc_a / doc_b.
        await _seed_jd(
            session,
            storage_ref="archive/aaa_outsider.docx",
            sha256=_sha("outsider"),
            parsed=SFUJobDescription(title="Registrar").model_dump(mode="json"),
        )
        await session.commit()

        full = await run_tier3(session, neo4j_driver=neo4j_driver, rules=rules)
        await session.commit()
        assert full.edges_written == 1
        original = (await _role_edges(session))[0]

        limited = await run_tier3(
            session, neo4j_driver=neo4j_driver, rules=rules, limit=1
        )
        await session.commit()

        assert limited.documents_seen == 1
        assert limited.edges_pruned == 0
        edges = await _role_edges(session)
        assert len(edges) == 1
        assert edges[0].id == original.id
        assert {edges[0].source_a_id, edges[0].source_b_id} == {doc_a.id, doc_b.id}


@pytest.mark.asyncio
async def test_an_unsignable_jd_never_prunes_its_edges(
    session_maker: async_sessionmaker[AsyncSession], neo4j_driver: AsyncDriver
) -> None:
    """The 3.3 data-loss lesson, in Tier-3. A JD that cannot be VALIDATED/SIGNED is an
    UNKNOWN, not a "no" — it must never fall into prune scope, or a single bad parse row
    silently destroys a real role-equivalence edge."""
    doc_a, doc_b = await _seed_a_b(session_maker, neo4j_driver)
    rules = get_rules()

    async with session_maker() as session:
        first = await run_tier3(session, neo4j_driver=neo4j_driver, rules=rules)
        await session.commit()
        assert first.edges_written == 1
        original = (await _role_edges(session))[0]

        # ...now doc_b's parsed row becomes unsignable (missing the required title).
        await session.execute(
            update(ParsedJDRow)
            .where(ParsedJDRow.source_document_id == doc_b.id)
            .values(parsed={"not_a_title": 1})
        )
        await session.commit()

        second = await run_tier3(session, neo4j_driver=neo4j_driver, rules=rules)
        await session.commit()

        assert second.documents_unsignable == 1
        assert second.documents_signed == 1
        # THE ASSERTION — the edge survives; an unknown pruned nothing.
        assert second.edges_pruned == 0
        edges = await _role_edges(session)
        assert len(edges) == 1
        assert edges[0].id == original.id


@pytest.mark.asyncio
async def test_a_jd_with_no_vector_still_scores_via_a_near_dup_seed(
    session_maker: async_sessionmaker[AsyncSession], neo4j_driver: AsyncDriver
) -> None:
    """The 118 empty-serialization + 11 token-limit JDs have no document vector. They
    can still be role-equivalent candidates via a Tier-2 near-dup seed, and they score
    with ``vector_score`` 0.0 rather than crashing (HR-160).

    The two padding docs make the shared skills DISTINCTIVE (df 2 of N 4 -> idf > 0):
    with a floored idf a skill in EVERY signed doc weighs 0, so the near-dup pair would
    score on seniority alone and not qualify — honest, but that would hide the "scores,
    no crash" point. Empty-skill padding is the real-corpus condition (41% empty bags).
    """
    jd = _analyst_jd().model_dump(mode="json")
    filler = SFUJobDescription(title="Registrar").model_dump(mode="json")
    async with session_maker() as session:
        doc_a = await _seed_jd(
            session, storage_ref="archive/nv_a.docx", sha256=_sha("nv-a"), parsed=jd
        )
        doc_b = await _seed_jd(
            session, storage_ref="archive/nv_b.docx", sha256=_sha("nv-b"), parsed=jd
        )
        # Empty-skill padding: contributes to N (idf denominator) but not to the shared
        # skills' df, so those skills earn a positive idf. No vectors, no near-dup edge,
        # so never a candidate -> candidate_pairs stays 1.
        for i in range(2):
            await _seed_jd(
                session,
                storage_ref=f"archive/nv_pad_{i}.docx",
                sha256=_sha(f"nv-pad-{i}"),
                parsed=filler,
            )
        # a Tier-2 NEAR_DUPLICATE edge is the only thing making them candidates (no
        # vectors).
        session.add(
            DedupEdge(
                source_a_id=doc_a.id,
                source_b_id=doc_b.id,
                tier=DedupTier.NEAR_DUPLICATE,
                score=0.95,
                method="minhash+jaccard@x",
            )
        )
        await session.commit()

        # NO vectors written to Neo4j for any doc.
        result = await run_tier3(session, neo4j_driver=neo4j_driver, rules=get_rules())
        await session.commit()

        assert result.documents_without_vector == 4  # nv_a, nv_b + 2 padding
        assert result.candidate_pairs == 1  # seeded, despite no vectors
        # skills distinctive (df 2 of N 4 -> skill_ov 1.0) + seniority 0.7 clear 0.5
        # even with vector 0.0: 0.45*0 + 0.45*1.0 + 0.10*0.7 = 0.52.
        assert result.qualifying_pairs == 1
        roles = await _role_edges(session)
        assert len(roles) == 1
        # the NEAR edge is untouched alongside the new ROLE edge.
        near = await session.scalars(
            select(DedupEdge).where(DedupEdge.tier == DedupTier.NEAR_DUPLICATE)
        )
        assert len(list(near.all())) == 1


@pytest.mark.asyncio
async def test_run_tier3_does_not_commit(
    session_maker: async_sessionmaker[AsyncSession], neo4j_driver: AsyncDriver
) -> None:
    await _seed_a_b(session_maker, neo4j_driver)
    rules = get_rules()

    async with session_maker() as session:
        result = await run_tier3(session, neo4j_driver=neo4j_driver, rules=rules)
        assert result.edges_written == 1
        await session.rollback()

    async with session_maker() as session:
        assert await _role_edges(session) == []


@pytest.mark.asyncio
async def test_exact_and_near_edges_are_untouched(
    session_maker: async_sessionmaker[AsyncSession], neo4j_driver: AsyncDriver
) -> None:
    doc_a, doc_b = await _seed_a_b(session_maker, neo4j_driver)
    rules = get_rules()

    async with session_maker() as session:
        for tier, method in (
            (DedupTier.EXACT, "sha256"),
            (DedupTier.NEAR_DUPLICATE, "minhash+jaccard@x"),
        ):
            session.add(
                DedupEdge(
                    source_a_id=doc_a.id,
                    source_b_id=doc_b.id,
                    tier=tier,
                    score=1.0,
                    method=method,
                )
            )
        await session.commit()

        await run_tier3(session, neo4j_driver=neo4j_driver, rules=rules)
        await session.commit()

        for tier in (DedupTier.EXACT, DedupTier.NEAR_DUPLICATE):
            rows = list(
                (
                    await session.scalars(
                        select(DedupEdge).where(DedupEdge.tier == tier)
                    )
                ).all()
            )
            assert len(rows) == 1, tier
        assert len(await _role_edges(session)) == 1

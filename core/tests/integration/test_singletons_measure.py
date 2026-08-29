"""Integration — the HR-223 measurement against a real Postgres.

The pure split is unit-tested; what only a real database can prove is that the SQL hands
it the RIGHT ROWS. Three things go wrong here and nowhere else:

1. **``has_edge`` must test both endpoints.** Edges are oriented by a structural key, so
   checking only ``source_a_id`` calls every b-side document edgeless, and the pool then
   fills with documents clustering *did* consider. A wrong query returns a comfortable
   number exactly as convincingly as a right one.
2. **"in a role" means the CURRENT version.** Crediting a document through a superseded
   version counts lineage the Bank has replaced.
3. **The parse is scoped to one ``PARSER_VERSION``.** A stale-version row must not
   appear; v6→v7 recovered 805 titles in a day, and a title-based measurement taken
   across that boundary compares two different archives.
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
    DocumentFormat,
    ParsedJDRow,
    SourceDocument,
)
from src.jd_bank.singletons.measure import measure_singletons
from src.jd_core.models.parsed_jd import (
    SFUDuty,
    SFUJobDescription,
    SFUQualification,
)
from src.jd_core.parser import FALLBACK_TITLE, PARSER_VERSION
from tests.integration.test_dedup_tier1 import ALEMBIC_INI


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
        await conn.execute(text("DELETE FROM parsed_jds"))
        await conn.execute(text("DELETE FROM source_documents"))
        await conn.execute(text("DELETE FROM canonical_jds"))
        await conn.execute(text("DELETE FROM clusters"))
    maker = async_sessionmaker(engine, expire_on_commit=False)
    yield maker
    await engine.dispose()


def _jd(title: str, *, quals: int = 0) -> SFUJobDescription:
    return SFUJobDescription(
        title=title,
        employee_group="apsa",
        position_summary=" ".join(["word"] * 30),
        duties=[
            SFUDuty(
                action_verb="Manages",
                statement="Manages the program end to end",
                how_why=["by coordinating stakeholders"],
            )
        ],
        qualifications=[
            SFUQualification(text=f"A qualification numbered {n}") for n in range(quals)
        ],
    )


async def _doc(
    session: AsyncSession,
    filename: str,
    title: str,
    *,
    quals: int = 0,
    parser_version: str = PARSER_VERSION,
) -> uuid.UUID:
    doc = SourceDocument(
        storage_ref=f"archive/{filename}",
        filename=filename,
        sha256=uuid.uuid4().hex,
        fmt=DocumentFormat.DOCX,
        byte_size=100,
    )
    session.add(doc)
    await session.flush()
    session.add(
        ParsedJDRow(
            source_document_id=doc.id,
            parsed=_jd(title, quals=quals).model_dump(mode="json"),
            parser_version=parser_version,
            parse_confidence=0.9,
        )
    )
    await session.flush()
    return doc.id


async def _role(
    session: AsyncSession,
    *,
    doc_ids: list[uuid.UUID],
    title: str = "Role",
    version: int = 1,
    cluster_id: uuid.UUID | None = None,
) -> uuid.UUID:
    cluster_id = cluster_id or uuid.uuid4()
    if await session.get(Cluster, cluster_id) is None:
        session.add(Cluster(id=cluster_id, label=title, members=[]))
    session.add(
        CanonicalJD(
            cluster_id=cluster_id,
            version=version,
            status=CanonicalStatus.DRAFT,
            content=_jd(title).model_dump(mode="json"),
            source_document_ids=[{"source_id": str(d)} for d in doc_ids],
            change_log={},
        )
    )
    await session.flush()
    return cluster_id


async def _edge(session: AsyncSession, a: uuid.UUID, b: uuid.UUID) -> None:
    await session.execute(
        text(
            "INSERT INTO dedup_edges"
            " (id, source_a_id, source_b_id, tier, score, method)"
            " VALUES (:i, :a, :b, 'NEAR_DUPLICATE', 0.9, 'test')"
        ),
        {"i": uuid.uuid4(), "a": a, "b": b},
    )


# --- the populations reconcile ------------------------------------------------------


async def test_the_populations_reconcile(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    """parsed = in-a-role + orphans, and the four buckets sum to the pool.

    An accounting that does not close is hiding a case — which is exactly how 1,204
    documents sat inside what read as ordinary de-duplication.
    """
    async with session_maker() as session:
        kept = await _doc(session, "a.doc", "Program Assistant", quals=9)
        grouped = await _doc(session, "b.doc", "Program Assistant", quals=8)
        lone = await _doc(session, "c.doc", "Disaster Recovery Coordinator", quals=1)
        await _edge(session, grouped, kept)
        await _role(session, doc_ids=[kept])
        await session.commit()

        summary = await measure_singletons(session)

    assert summary.parsed_documents == 3
    assert summary.documents_in_a_role == 1
    assert summary.orphans == 2
    assert summary.parsed_documents == summary.documents_in_a_role + summary.orphans
    # `lone` alone: `grouped` has an edge, so clustering DID consider it.
    assert summary.buckets.pool.total == 1
    assert summary.buckets.pool.unique_title == 1
    assert lone is not None


# --- the query traps ---------------------------------------------------------------


async def test_an_edge_counts_from_either_end(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    """The b-side trap. Edges are oriented by a structural key, so a document is just as
    likely to be ``source_b_id`` as ``source_a_id``.

    Both documents here are edged and neither is in a role, so the pool must be EMPTY. A
    one-sided check would put the b-side document in it and report a one-of-a-kind job
    that has a near-duplicate sitting next to it.
    """
    async with session_maker() as session:
        a = await _doc(session, "a.doc", "Alpha Analyst")
        b = await _doc(session, "b.doc", "Beta Analyst")
        await _edge(session, a, b)
        await session.commit()

        summary = await measure_singletons(session)

    assert summary.orphans == 2, "neither reached a role"
    assert summary.documents_with_no_edge == 0
    assert summary.buckets.pool.total == 0, "an edged document is not one-of-a-kind"


async def test_membership_follows_the_current_version_of_a_role(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    """A superseded version's lineage is history, not membership.

    Version 1 cited the document; version 2 does not. Counting it through v1 would
    credit the Bank with a document its live role no longer claims — and would hide it
    from the very pool HR-223 is about.
    """
    async with session_maker() as session:
        dropped = await _doc(session, "a.doc", "Formerly Cited Officer")
        cluster = await _role(session, doc_ids=[dropped], version=1)
        await _role(session, doc_ids=[], version=2, cluster_id=cluster)
        await session.commit()

        summary = await measure_singletons(session)

    assert summary.documents_in_a_role == 0
    assert summary.buckets.pool.unique_title == 1


async def test_only_the_current_parser_version_is_measured(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    """A title-based measurement across a parser bump compares two archives.

    v6→v7 recovered 805 titles in a single day. A stale-version row must not appear at
    all — not as a document, and not as a second occurrence of a title that would make a
    unique job look shared.
    """
    async with session_maker() as session:
        await _doc(session, "a.doc", "Singular Steward")
        await _doc(
            session, "b.doc", "Singular Steward", parser_version="jd_segmenter_v1"
        )
        await session.commit()

        summary = await measure_singletons(session)

    assert summary.parsed_documents == 1
    assert (
        summary.buckets.pool.unique_title == 1
    ), "the stale-version row must not make the current one look duplicated"


# --- what the numbers must not claim ------------------------------------------------


async def test_the_placeholder_title_is_reported_as_could_not_evaluate(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    """A PLACEHOLDER IS NOT A NULL, end to end.

    Read straight out of the database, ``Untitled Position`` is a perfectly ordinary
    title string that would be counted as a unique job — inflating the one number HR is
    being asked to act on. It must land in the could-not-evaluate bucket instead.
    """
    async with session_maker() as session:
        await _doc(session, "a.doc", FALLBACK_TITLE)
        await _doc(session, "b.doc", FALLBACK_TITLE)
        await session.commit()

        summary = await measure_singletons(session)

    assert summary.buckets.pool.title_unjudgeable == 2
    assert summary.buckets.pool.unique_title == 0


async def test_a_document_in_a_role_with_no_edge_is_not_in_the_pool(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    """The Builder mints roles from no source documents at all (``origin: composed``),
    so "no edge" and "no role" are genuinely independent.

    Reported separately because a non-zero count here is not a defect — it is the reason
    the pool is defined as both conditions rather than the edge check alone.
    """
    async with session_maker() as session:
        authored = await _doc(session, "a.doc", "Composed Coordinator")
        await _role(session, doc_ids=[authored])
        await session.commit()

        summary = await measure_singletons(session)

    assert summary.documents_with_no_edge == 1
    assert summary.documents_with_no_edge_in_a_role == 1
    assert summary.buckets.pool.total == 0


async def test_the_qualification_means_are_null_rather_than_zero_when_empty(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    """0.0 would read as "these documents have no qualifications" — a finding. The
    absence of a population is not a finding about it.
    """
    async with session_maker() as session:
        lone = await _doc(session, "a.doc", "Solitary Specialist", quals=2)
        await session.commit()

        summary = await measure_singletons(session)

    assert lone is not None
    assert summary.mean_qualifications_pool == 2.0
    assert summary.mean_qualifications_in_role is None


async def test_the_median_is_reported_beside_the_mean(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    """A mean over 1,204 documents is an aggregate, and an aggregate is where this
    project keeps hiding things.

    One document with 40 parsed qualifications drags a mean anywhere it likes; the
    median next to it is what tells a genuinely qualification-rich population from a
    handful of outliers. Both are reported, always, so the reader can tell which they
    are looking at.
    """
    async with session_maker() as session:
        await _doc(session, "a.doc", "Lone Alpha", quals=1)
        await _doc(session, "b.doc", "Lone Beta", quals=2)
        await _doc(session, "c.doc", "Lone Gamma", quals=39)
        await session.commit()

        summary = await measure_singletons(session)

    assert summary.buckets.pool.total == 3
    assert summary.mean_qualifications_pool == 14.0
    assert (
        summary.median_qualifications_pool == 2.0
    ), "the median must not follow the outlier the mean does"
    assert summary.median_qualifications_in_role is None

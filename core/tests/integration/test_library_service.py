"""Integration — the read-only content library service against a real Postgres, through
the real migration. What only a real database can prove (the queries use JSONB
containment, ``DISTINCT ON``, and JSONB-path ILIKE that a fake session can't):

1. **The source-JD reader renders readable content.** ``get_source_jd`` returns the
   archive JD's rendered prose + metadata, and its back-link to the role it fed. Unknown
   / unparsed documents return ``None`` (a 404 upstream), never a crash.
2. **A role drills to its sources.** ``get_role`` returns the harmonized canonical
   rendered readable plus its member source JDs — filenames from the cluster snapshot,
   titles from each member's parse.
3. **The roles library shows one row per role, latest version.** After an edit mints a
   v2, ``list_roles`` lists the cluster once (v2), not both versions; the title filter
   and pagination ``total`` behave.
4. **The flat source archive lists + filters by filename.**

This is the browsing spine of the "where is the actual content?" overhaul — all
read-only (NN #1); nothing here publishes.
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

from src.jd_bank.composer import cluster_id_for_source, load_role_clone_answers
from src.jd_bank.db.models import (
    CanonicalJD,
    CanonicalStatus,
    Cluster,
    DocumentFormat,
    ParsedJDRow,
    SourceDocument,
)
from src.jd_bank.library import (
    get_role,
    get_source_jd,
    list_roles,
    list_source_jds,
)
from src.jd_core.models.parsed_jd import SFUDuty, SFUJobDescription
from src.jd_core.parser import PARSER_VERSION
from tests.integration.test_dedup_tier1 import ALEMBIC_INI


def _jd(title: str, **update: object) -> SFUJobDescription:
    jd = SFUJobDescription(
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
    )
    return jd.model_copy(update=update)


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
        await conn.execute(text("DELETE FROM parsed_jds"))
        await conn.execute(text("DELETE FROM source_documents"))
        await conn.execute(text("DELETE FROM canonical_jds"))
        await conn.execute(text("DELETE FROM clusters"))
    maker = async_sessionmaker(engine, expire_on_commit=False)
    yield maker
    await engine.dispose()


async def _seed_source(
    session: AsyncSession,
    *,
    filename: str,
    jd: SFUJobDescription,
    confidence: float = 0.9,
) -> uuid.UUID:
    doc = SourceDocument(
        storage_ref=f"archive/{filename}",
        filename=filename,
        sha256=uuid.uuid4().hex,
        fmt=DocumentFormat.DOCX,
        byte_size=1234,
    )
    session.add(doc)
    await session.flush()
    session.add(
        ParsedJDRow(
            source_document_id=doc.id,
            parsed=jd.model_dump(mode="json"),
            parser_version=PARSER_VERSION,
            parse_confidence=confidence,
        )
    )
    await session.flush()
    return doc.id


async def _seed_role(
    session: AsyncSession,
    *,
    content: SFUJobDescription,
    members: list[dict[str, object]],
    version: int = 1,
    status: CanonicalStatus = CanonicalStatus.DRAFT,
    cluster_id: uuid.UUID | None = None,
    change_log: dict[str, object] | None = None,
    bands: list[int] | None = None,
) -> tuple[uuid.UUID, uuid.UUID]:
    cluster_id = cluster_id or uuid.uuid4()
    if await session.get(Cluster, cluster_id) is None:
        session.add(
            Cluster(
                id=cluster_id,
                label=content.title,
                members=members,
                constraint_metadata={"bands": bands or []},
            )
        )
    canonical = CanonicalJD(
        cluster_id=cluster_id,
        version=version,
        status=status,
        content=content.model_dump(mode="json"),
        source_document_ids=[{"source_id": m["source_id"]} for m in members],
        change_log=change_log or {},
    )
    session.add(canonical)
    await session.flush()
    return cluster_id, canonical.id


# --- acceptance #1: the source-JD reader ----------------------------------------------


@pytest.mark.asyncio
async def test_get_source_jd_renders_content_and_metadata(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    async with session_maker() as session:
        jd = _jd("Research Coordinator", department="Biology", grade="A1")
        sid = await _seed_source(session, filename="research-coordinator.docx", jd=jd)
        await session.commit()

        view = await get_source_jd(session, sid)

    assert view is not None
    assert view.filename == "research-coordinator.docx"
    assert view.title == "Research Coordinator"
    assert view.department == "Biology"
    assert view.parse_confidence == pytest.approx(0.9)
    # The actual content is rendered readable — not just a filename.
    assert "Manages the program end to end" in view.rendered_text
    assert view.role is None  # not a cluster member


@pytest.mark.asyncio
async def test_get_source_jd_back_links_to_its_role(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    async with session_maker() as session:
        jd = _jd("Advisor")
        sid = await _seed_source(session, filename="advisor.docx", jd=jd)
        cluster_id, canonical_id = await _seed_role(
            session,
            content=_jd("Academic Advisor"),
            members=[{"source_id": str(sid), "filename": "advisor.docx"}],
        )
        await session.commit()

        view = await get_source_jd(session, sid)

    assert view is not None and view.role is not None
    assert view.role.cluster_id == cluster_id
    assert view.role.canonical_id == canonical_id
    assert view.role.title == "Academic Advisor"


@pytest.mark.asyncio
async def test_get_source_jd_none_for_unknown_or_unparsed(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    async with session_maker() as session:
        assert await get_source_jd(session, uuid.uuid4()) is None  # unknown
        # a document with no parse row
        doc = SourceDocument(
            storage_ref="archive/x.docx",
            filename="x.docx",
            sha256=uuid.uuid4().hex,
            fmt=DocumentFormat.DOCX,
        )
        session.add(doc)
        await session.commit()
        assert await get_source_jd(session, doc.id) is None


# --- acceptance #2: a role drills to its sources --------------------------------------


@pytest.mark.asyncio
async def test_get_role_renders_canonical_and_lists_members(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    async with session_maker() as session:
        a = await _seed_source(session, filename="a.docx", jd=_jd("Coordinator A"))
        b = await _seed_source(session, filename="b.docx", jd=_jd("Coordinator B"))
        cluster_id, _ = await _seed_role(
            session,
            content=_jd(
                "Operations Manager", position_summary="harmonized summary here"
            ),
            members=[
                {"source_id": str(a), "filename": "a.docx"},
                {"source_id": str(b), "filename": "b.docx"},
            ],
            change_log={"validator": {"score": 82.0, "grade": "A"}},
        )
        await session.commit()

        role = await get_role(session, cluster_id)

    assert role is not None
    assert role.title == "Operations Manager"
    assert role.score == pytest.approx(82.0) and role.grade == "A"
    # seniority is classified from the CLEAN canonical title (not the stored band)
    assert role.level_band == "Manager"
    assert role.source_count == 2
    filenames = {m.filename for m in role.members}
    assert filenames == {"a.docx", "b.docx"}
    titles = {m.title for m in role.members}
    assert titles == {"Coordinator A", "Coordinator B"}
    assert all(m.parsed for m in role.members)


@pytest.mark.asyncio
async def test_get_role_none_for_unknown_cluster(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    async with session_maker() as session:
        assert await get_role(session, uuid.uuid4()) is None


# --- acceptance #3: the roles library -------------------------------------------------


@pytest.mark.asyncio
async def test_list_roles_one_row_per_cluster_latest_version(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    async with session_maker() as session:
        cluster_id, _ = await _seed_role(
            session,
            content=_jd("Analyst v1"),
            members=[],
            version=1,
            status=CanonicalStatus.ARCHIVED,
        )
        # an edit minted v2 on the SAME cluster (prior archived)
        await _seed_role(
            session,
            content=_jd("Analyst v2"),
            members=[],
            version=2,
            status=CanonicalStatus.DRAFT,
            cluster_id=cluster_id,
        )
        await _seed_role(session, content=_jd("Bursar"), members=[])
        await session.commit()

        page = await list_roles(session)

    titles = [item.title for item in page.items]
    assert "Analyst v2" in titles  # the current version
    assert "Analyst v1" not in titles  # the archived prior version is not a second row
    assert "Bursar" in titles
    assert page.total == 2  # two roles (clusters), not three canonical rows


@pytest.mark.asyncio
async def test_list_roles_title_filter_and_pagination(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    async with session_maker() as session:
        for name in ("Finance Analyst", "Finance Manager", "Library Assistant"):
            await _seed_role(session, content=_jd(name), members=[])
        await session.commit()

        finance = await list_roles(session, q="finance")
        assert finance.total == 2
        assert {i.title for i in finance.items} == {
            "Finance Analyst",
            "Finance Manager",
        }

        page1 = await list_roles(session, limit=1, offset=0)
        page2 = await list_roles(session, limit=1, offset=1)
        assert page1.total == 3 and page2.total == 3
        assert len(page1.items) == 1 and len(page2.items) == 1
        assert page1.items[0].title != page2.items[0].title


@pytest.mark.asyncio
async def test_list_roles_carries_the_level_band(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    """The roles list shows the seniority tier classified from the CLEAN canonical title
    (rulebook title-family classifier) in place of the unpopulated employee group; a
    title that maps to no family shows nothing (the common case, ~70%)."""
    async with session_maker() as session:
        await _seed_role(session, content=_jd("Facilities Manager"), members=[])
        await _seed_role(session, content=_jd("Director, Finance"), members=[])
        await _seed_role(session, content=_jd("Records Coordinator"), members=[])
        await session.commit()

        page = await list_roles(session)

    by_title = {item.title: item.level_band for item in page.items}
    assert by_title["Facilities Manager"] == "Manager"
    assert by_title["Director, Finance"] == "Director"
    assert by_title["Records Coordinator"] is None  # unmapped title -> no tier


# --- acceptance #4: the flat source archive -------------------------------------------


@pytest.mark.asyncio
async def test_list_source_jds_lists_and_filters_by_filename(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    async with session_maker() as session:
        await _seed_source(
            session, filename="finance-analyst.docx", jd=_jd("Finance Analyst")
        )
        await _seed_source(
            session, filename="library-clerk.docx", jd=_jd("Library Clerk")
        )
        await session.commit()

        page = await list_source_jds(session, q="finance")

    assert page.total == 1
    assert page.items[0].filename == "finance-analyst.docx"
    assert page.items[0].title == "Finance Analyst"
    assert page.items[0].parsed is True


# --- acceptance #5: cloning the HARMONIZED role, not the raw archive JD ---------------


@pytest.mark.asyncio
async def test_load_role_clone_answers_uses_the_latest_canonical(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    async with session_maker() as session:
        cluster_id, _ = await _seed_role(
            session,
            content=_jd("Analyst v1"),
            members=[],
            version=1,
            status=CanonicalStatus.ARCHIVED,
        )
        await _seed_role(
            session,
            content=_jd("Analyst v2 harmonized"),
            members=[],
            version=2,
            status=CanonicalStatus.DRAFT,
            cluster_id=cluster_id,
        )
        await session.commit()

        answers = await load_role_clone_answers(session, cluster_id)

    assert answers is not None
    assert answers.title == "Analyst v2 harmonized"  # the current version, not v1


@pytest.mark.asyncio
async def test_load_role_clone_answers_none_for_unknown_cluster(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    async with session_maker() as session:
        assert await load_role_clone_answers(session, uuid.uuid4()) is None


@pytest.mark.asyncio
async def test_cluster_id_for_source_resolves_membership(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    async with session_maker() as session:
        member = await _seed_source(session, filename="m.docx", jd=_jd("Member"))
        singleton = await _seed_source(session, filename="s.docx", jd=_jd("Singleton"))
        cluster_id, _ = await _seed_role(
            session,
            content=_jd("Role"),
            members=[{"source_id": str(member), "filename": "m.docx"}],
        )
        await session.commit()

        assert await cluster_id_for_source(session, member) == cluster_id
        assert await cluster_id_for_source(session, singleton) is None

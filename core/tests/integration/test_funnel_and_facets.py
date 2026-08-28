"""Integration — the live funnel and facets against a real Postgres (Phase A4/A5).

What only a real database can prove:

1. **Every stage reconciles.** Documents = readable + unreadable; readable = in-a-role +
   orphans; and the orphan note's three buckets add up to the orphans. A funnel whose
   arithmetic does not close is a funnel that is hiding something — measured on the real
   archive, 1,204 documents were hiding inside what looked like ordinary de-duplication.
2. **Scope actually scopes.** The same queries over a subset return the subset, and an
   EMPTY scope returns nothing rather than everything.
3. **Facets keep their `(not stated)` bucket** and report honest coverage.
4. **`published` counts CURRENT versions**, so editing a published role lowers it.
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
from src.jd_bank.library import build_facets, build_funnel, scope_for
from src.jd_bank.library.scopes import WHOLE_BANK, Scope
from src.jd_core.models.parsed_jd import SFUDuty, SFUJobDescription
from src.jd_core.parser import PARSER_VERSION
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


async def _doc(
    session: AsyncSession, filename: str, *, parsed: bool = True
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
    if parsed:
        session.add(
            ParsedJDRow(
                source_document_id=doc.id,
                parsed=_jd("A role").model_dump(mode="json"),
                parser_version=PARSER_VERSION,
                parse_confidence=0.9,
            )
        )
        await session.flush()
    return doc.id


async def _role(
    session: AsyncSession,
    *,
    jd: SFUJobDescription,
    doc_ids: list[uuid.UUID],
    approved: bool = False,
    status: CanonicalStatus = CanonicalStatus.DRAFT,
    version: int = 1,
    cluster_id: uuid.UUID | None = None,
) -> uuid.UUID:
    cluster_id = cluster_id or uuid.uuid4()
    if await session.get(Cluster, cluster_id) is None:
        session.add(Cluster(id=cluster_id, label=jd.title, members=[]))
    session.add(
        CanonicalJD(
            cluster_id=cluster_id,
            version=version,
            status=status,
            content=jd.model_dump(mode="json"),
            source_document_ids=[{"source_id": str(d)} for d in doc_ids],
            change_log={"validator": {"gate_decision": {"approved": approved}}},
        )
    )
    await session.flush()
    return cluster_id


def _stage(funnel: object, key: str) -> object:
    return next(s for s in funnel.stages if s.key == key)  # type: ignore[attr-defined]


# --- the funnel reconciles ---------------------------------------------------------


async def test_every_stage_reconciles(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    """Documents = readable + unreadable; readable = in-a-role + orphans.

    A funnel whose arithmetic does not close is hiding something. On the real archive,
    1,204 unaccounted documents were sitting inside what read as ordinary de-
    duplication.
    """
    async with session_maker() as session:
        kept = await _doc(session, "a_ITP_I.doc")
        orphan = await _doc(session, "b_ITP_I.doc")
        await _doc(session, "c_ITP_I.doc", parsed=False)  # unreadable
        await _role(session, jd=_jd("Role"), doc_ids=[kept], approved=True)
        await session.commit()

        funnel = await build_funnel(session, WHOLE_BANK)

    docs = _stage(funnel, "documents")
    parsed = _stage(funnel, "parsed")
    in_role = _stage(funnel, "in_role")
    assert docs.count == 3
    assert parsed.count == 2
    assert parsed.lost == 1, "the unreadable document is named, not dropped"
    assert in_role.count == 1
    assert in_role.lost == 1
    assert parsed.count == in_role.count + in_role.lost
    assert docs.count == parsed.count + parsed.lost
    assert orphan is not None


async def test_the_orphan_note_buckets_add_up(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    """The three orphan buckets must sum to the orphans.

    "N de-duplicated" is a plausible sentence that can hide documents nobody has
    explained. The note therefore splits: near-duplicate of a kept document, near-
    duplicate
    of another orphan, and NO near-duplicate link at all.
    """
    async with session_maker() as session:
        kept = await _doc(session, "a_ITP_I.doc")
        dup_of_kept = await _doc(session, "b_ITP_I.doc")
        no_edge = await _doc(session, "c_ITP_I.doc")
        await _role(session, jd=_jd("Role"), doc_ids=[kept])
        await session.execute(
            text(
                "INSERT INTO dedup_edges (id, source_a_id, source_b_id, tier, score,"
                " method) VALUES (:i, :a, :b, 'NEAR_DUPLICATE', 0.9, 'test')"
            ),
            {"i": uuid.uuid4(), "a": dup_of_kept, "b": kept},
        )
        await session.commit()

        funnel = await build_funnel(session, WHOLE_BANK)

    in_role = _stage(funnel, "in_role")
    assert in_role.lost == 2
    assert in_role.note is not None
    assert "1 are near-duplicates of a document that IS in a role" in in_role.note
    assert "1 have no near-duplicate link at all" in in_role.note
    assert no_edge is not None


async def test_published_counts_current_versions_only(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    """Editing a published role mints a new DRAFT, so the live count drops.

    The archive-wide numbers differ for exactly this reason — 5 clusters have been
    published, 4 are published *now* — and a page that conflates them misreports the
    deliverable in the direction that flatters it.
    """
    async with session_maker() as session:
        doc = await _doc(session, "a_ITP_I.doc")
        cluster = await _role(
            session,
            jd=_jd("Role"),
            doc_ids=[doc],
            status=CanonicalStatus.PUBLISHED,
            version=1,
        )
        await session.commit()
        before = _stage(await build_funnel(session, WHOLE_BANK), "published").count

        await _role(
            session,
            jd=_jd("Role edited"),
            doc_ids=[doc],
            status=CanonicalStatus.DRAFT,
            version=2,
            cluster_id=cluster,
        )
        await session.commit()
        after = _stage(await build_funnel(session, WHOLE_BANK), "published").count

    assert (before, after) == (1, 0)


# --- scope actually scopes ---------------------------------------------------------


async def test_scope_restricts_and_an_empty_scope_returns_nothing(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    """⚠ The direction of this failure decides whether an empty unit shows nothing or
    shows the entire archive under that unit's name."""
    async with session_maker() as session:
        a = await _doc(session, "a_ITP_I.doc")
        b = await _doc(session, "b_APSA.doc")
        it_cluster = await _role(session, jd=_jd("IT role"), doc_ids=[a], approved=True)
        await _role(session, jd=_jd("Other role"), doc_ids=[b])
        await session.commit()

        whole = await build_funnel(session, WHOLE_BANK)
        scoped = await build_funnel(
            session, Scope(key="x", label="X", cluster_ids=frozenset({it_cluster}))
        )
        empty = await build_funnel(
            session, Scope(key="y", label="Y", cluster_ids=frozenset())
        )

    assert _stage(whole, "roles").count == 2
    assert _stage(scoped, "roles").count == 1
    assert _stage(scoped, "approvable").count == 1
    assert _stage(empty, "roles").count == 0, "an empty scope is empty, not everything"


async def test_a_scope_without_an_archive_side_definition_says_so(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    """An org-unit scope reads `department` from a parse, not a filename, so it has no
    document-side stages. It must SAY that rather than report a number it cannot defend.
    """
    async with session_maker() as session:
        doc = await _doc(session, "a_ITP_I.doc")
        cluster = await _role(session, jd=_jd("Role"), doc_ids=[doc])
        await session.commit()
        funnel = await build_funnel(
            session,
            Scope(key="vpfa", label="VPFA", cluster_ids=frozenset({cluster})),
        )

    assert funnel.documents_note is not None
    assert all(s.key not in {"documents", "parsed", "in_role"} for s in funnel.stages)
    assert _stage(funnel, "roles").count == 1


async def test_scope_for_returns_none_for_an_unknown_key(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    """A mistyped scope is a 404 upstream, never a silent fallback to the whole Bank."""
    async with session_maker() as session:
        assert await scope_for(session, "no-such-scope") is None
        assert (await scope_for(session, None)) == WHOLE_BANK
        it = await scope_for(session, "it")
        assert it is not None and it.source_filename_pattern is not None


# --- facets ------------------------------------------------------------------------


async def test_facets_keep_a_not_stated_bucket_and_report_coverage(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    """A facet that silently drops the roles it has no value for is the archive-claim
    error in UI form. For `department` the real blind spot is 27.8% of the Bank."""
    async with session_maker() as session:
        a = await _doc(session, "a_ITP_I.doc")
        b = await _doc(session, "b_ITP_I.doc")
        await _role(
            session, jd=_jd("With dept", department="Financial Services"), doc_ids=[a]
        )
        await _role(session, jd=_jd("No dept"), doc_ids=[b])
        await session.commit()

        facets = await build_facets(session, WHOLE_BANK)

    dept = next(f for f in facets if f.key == "department")
    assert dept.total == 2
    assert dept.not_stated == 1
    assert dept.known == 1
    assert dept.coverage_pct == 50.0
    assert [b.value for b in dept.buckets] == ["Financial Services"]
    assert "not an org rollup" in (dept.note or "").lower()

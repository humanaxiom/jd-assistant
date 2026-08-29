"""THE end-to-end smoke test — one miniature archive through the whole chain.

Written 2026-08-28 after review found the IT collection reporting a third of the IT
function, weeks after demos to HR and C-level executives. The instruction was explicit:
*step back and ensure the basics — parsing, dedup, categorize, filterable.* This test is
that instruction, executable.

One seeded archive exercises every path a real document can take, and the test then
walks the FOUR BASICS in order, asserting at each step that **every document is in
exactly one accounted-for state**. Nothing here is a unit test of a function; it is the
chain, and it fails if any link mis-accounts a single document.

The seeded archive (9 documents, every terminal state represented):

    unreadable.docx      no parse row               → counted unreadable, browsable
    dup_a / dup_b        near-duplicates            → ONE role, both documents behind it
    orphan_dup.docx      near-dup of dup_a, dropped → gap: duplicate of a kept document
    singleton.docx       unique job, parsed clean   → gap: one-of-a-kind (structural)
    no_title.docx        parser placeholder title   → gap: no title extracted
    it_title.docx        "Network Administrator"    → IT member via TITLE
    it_dept.docx         department "IT Services"   → IT member via DEPARTMENT
    it_code_ITP_II.docx  ITP code in the filename   → IT member via CLASSIFICATION
    gardener.docx        none of the above          → in the Bank, in no collection
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
from src.jd_bank.library import (
    build_funnel,
    build_gap,
    family_for,
    list_roles,
    list_source_jds,
    membership_coverage,
    resolve_members,
    scope_for,
)
from src.jd_bank.library.scopes import WHOLE_BANK
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
    session: AsyncSession,
    filename: str,
    *,
    jd: SFUJobDescription | None = None,
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
    if jd is not None:
        session.add(
            ParsedJDRow(
                source_document_id=doc.id,
                parsed=jd.model_dump(mode="json"),
                parser_version=PARSER_VERSION,
                parse_confidence=0.9,
            )
        )
        await session.flush()
    return doc.id


async def _role(
    session: AsyncSession,
    jd: SFUJobDescription,
    doc_ids: list[uuid.UUID],
    *,
    approved: bool = True,
) -> uuid.UUID:
    cluster_id = uuid.uuid4()
    session.add(Cluster(id=cluster_id, label=jd.title, members=[]))
    session.add(
        CanonicalJD(
            cluster_id=cluster_id,
            version=1,
            status=CanonicalStatus.DRAFT,
            content=jd.model_dump(mode="json"),
            source_document_ids=[{"source_id": str(d)} for d in doc_ids],
            change_log={"validator": {"gate_decision": {"approved": approved}}},
        )
    )
    await session.flush()
    return cluster_id


async def test_end_to_end_smoke(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    """Parsing → dedup → categorize → filterable, with total accounting at each step."""
    async with session_maker() as session:
        # ---- the seeded archive -----------------------------------------------------
        _ = await _doc(session, "unreadable.docx", jd=None)
        dup_a = await _doc(session, "dup_a.docx", jd=_jd("Program Assistant"))
        dup_b = await _doc(session, "dup_b.docx", jd=_jd("Program Assistant"))
        orphan_dup = await _doc(session, "orphan_dup.docx", jd=_jd("Program Assistant"))
        _ = await _doc(session, "singleton.docx", jd=_jd("Chief Wine Steward"))
        _ = await _doc(session, "no_title.docx", jd=_jd("Untitled Position"))
        it_title = await _doc(session, "it_title.docx", jd=_jd("Network Administrator"))
        it_dept = await _doc(
            session,
            "it_dept.docx",
            jd=_jd("Client Services Manager", department="IT Services"),
        )
        it_code = await _doc(
            session, "it_code_ITP_II.docx", jd=_jd("Something Generic")
        )
        gardener = await _doc(session, "gardener.docx", jd=_jd("Gardener"))

        role_dup = await _role(session, _jd("Program Assistant"), [dup_a, dup_b])
        role_title = await _role(session, _jd("Network Administrator"), [it_title])
        role_dept = await _role(
            session,
            _jd("Client Services Manager", department="IT Services"),
            [it_dept],
        )
        role_code = await _role(
            session, _jd("Something Generic"), [it_code], approved=False
        )
        role_none = await _role(session, _jd("Gardener"), [gardener])
        await session.execute(
            text(
                "INSERT INTO dedup_edges (id, source_a_id, source_b_id, tier, score,"
                " method) VALUES (:i, :a, :b, 'NEAR_DUPLICATE', 0.9, 'smoke')"
            ),
            {"i": uuid.uuid4(), "a": orphan_dup, "b": dup_a},
        )
        await session.commit()

        # ---- BASIC 1: PARSING — every document counted, readable or not -------------
        funnel = await build_funnel(session, WHOLE_BANK)
        stage = {s.key: s for s in funnel.stages}
        assert stage["documents"].count == 10
        assert stage["parsed"].count == 9
        assert stage["parsed"].lost == 1, "the unreadable file is named, not dropped"
        assert stage["documents"].count == stage["parsed"].count + stage["parsed"].lost

        # ---- BASIC 2: DEDUP — every parsed document in a role or a named bucket -----
        assert stage["in_role"].count == 6  # dup_a, dup_b, it_title, it_dept, it_code,
        assert stage["in_role"].lost == 3  # gardener are in roles; 3 orphans
        gap = await build_gap(session, WHOLE_BANK)
        assert gap.total == 3
        assert gap.reconciles, "every dropped document lands in exactly one bucket"
        bucket = {b.key: b.count for b in gap.buckets}
        assert bucket["dup_of_kept"] == 1  # orphan_dup — benign, represented by dup_a
        assert bucket["one_off"] == 1  # singleton — the structural gap
        assert bucket["no_title"] == 1  # the parser placeholder, NOT a real title
        # ...and the units are labelled, because a funnel that switches from documents
        # to roles without saying so was misread in review.
        assert stage["parsed"].unit == "documents"
        assert stage["roles"].unit == "roles"

        # ---- BASIC 3: CATEGORIZE — membership is the union of every direct signal ---
        assert stage["roles"].count == 5
        family = family_for("it")
        assert family is not None
        members = await resolve_members(session, family)
        assert members == {role_title, role_dept, role_code}, (
            "title, department and filename code each confer membership on their own; "
            "membership by any single signal alone was measured blind to 65% of the "
            "archive"
        )
        assert role_dup not in members and role_none not in members
        coverage = await membership_coverage(session, family)
        assert coverage.total_roles == 5
        assert coverage.members == 3
        assert (
            coverage.unmatched == 2
        ), "what the signals did NOT match is reported, or the filter is unfalsifiable"

        # ---- BASIC 4: FILTERABLE — every document and role reachable by search ------
        for filename in ("unreadable.docx", "singleton.docx", "it_code_ITP_II.docx"):
            page = await list_source_jds(session, q=filename)
            assert page.total == 1, f"{filename} must be findable in the browser"
        by_title = await list_roles(session, q="Network Administrator")
        assert by_title.total == 1
        scoped = await list_roles(session, cluster_ids=members)
        assert scoped.total == 3, "the collection filter returns exactly the members"
        it_scope = await scope_for(session, "it")
        assert it_scope is not None
        it_funnel = await build_funnel(session, it_scope)
        it_stage = {s.key: s for s in it_funnel.stages}
        assert it_stage["roles"].count == 3
        assert it_stage["approvable"].count == 2  # role_code seeded unapproved
        assert (
            await scope_for(session, "typo-scope")
        ) is None, (
            "an unknown scope is a 404 upstream, never a silent whole-Bank fallback"
        )

        # ---- and the grand total: NOTHING is unaccounted for ------------------------
        accounted = (
            stage["parsed"].lost  # unreadable
            + stage["in_role"].count  # behind a role
            + gap.total  # in a named gap bucket
        )
        assert accounted == stage["documents"].count, (
            "every single document is unreadable, behind a role, or in a named gap "
            "bucket — a document outside all three is the failure this test exists for"
        )

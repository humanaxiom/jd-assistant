"""Integration — ``prefill_from_role`` against a real Postgres (Track K, K2).

The builder reads only what the Bank holds for a role's CURRENT version — title,
department, employee group — plus the position numbers carried in its member source
documents' FILENAMES (``segmentation.position_id_pattern``; the header
``position_number`` is noisy and unused). A fact the Bank lacks stays ``None``:
nothing is guessed.
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
from src.jd_bank.forms import prefill_from_role
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
        await conn.execute(text("DELETE FROM parsed_jds"))
        await conn.execute(text("DELETE FROM source_documents"))
        await conn.execute(text("DELETE FROM canonical_jds"))
        await conn.execute(text("DELETE FROM clusters"))
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


async def _doc(session: AsyncSession, filename: str) -> uuid.UUID:
    doc = SourceDocument(
        storage_ref=f"archive/{filename}",
        filename=filename,
        sha256=uuid.uuid4().hex,
        fmt=DocumentFormat.DOCX,
        byte_size=1,
    )
    session.add(doc)
    await session.flush()
    return doc.id


async def _role(
    session: AsyncSession,
    *,
    content: dict[str, object],
    filenames: list[str],
    version: int = 1,
    cluster_id: uuid.UUID | None = None,
    parsed: list[dict[str, object] | None] | None = None,
    parser_version: str = PARSER_VERSION,
) -> uuid.UUID:
    """``parsed[i]`` is the CURRENT parse stored for ``filenames[i]`` (None: no
    parse row), so a test can give the sources facts the role lacks."""
    cluster_id = cluster_id or uuid.uuid4()
    ids = [await _doc(session, name) for name in filenames]
    for doc_id, fields in zip(ids, parsed or [], strict=False):
        if fields is not None:
            session.add(
                ParsedJDRow(
                    source_document_id=doc_id,
                    parsed=fields,
                    parser_version=parser_version,
                    parse_confidence=1.0,
                )
            )
    if await session.get(Cluster, cluster_id) is None:
        session.add(Cluster(id=cluster_id, label="x", members=[]))
    session.add(
        CanonicalJD(
            cluster_id=cluster_id,
            version=version,
            status=CanonicalStatus.DRAFT,
            content=content,
            source_document_ids=[{"source_id": str(i)} for i in ids],
        )
    )
    await session.flush()
    return cluster_id


@pytest.mark.asyncio
async def test_reevaluation_of_a_single_position_role_fills_section_b_and_position(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    async with session_maker() as session:
        rid = await _role(
            session,
            content={
                "title": "Research Coordinator",
                "department": "Biology",
                "employee_group": "apsa",
            },
            filenames=[
                "20200601_00001234_JDFN_APSA_20211117.docx",
                "20210101_00001234_Coordinator.docx",
            ],
        )
        await session.commit()
        prefill = await prefill_from_role(
            session, rid, request_type="reevaluation", position_number="00001234"
        )

    assert prefill.position_number == "00001234"
    assert prefill.position_title == "Research Coordinator"
    assert prefill.department == "Biology"
    assert prefill.employee_group == "APSA"
    assert prefill.based_on_positions_b == ("00001234",)
    assert prefill.based_on_positions_a == ()  # Section A is a different request
    assert prefill.candidate_positions == ("00001234",)
    assert prefill.positions_incomplete is False
    assert prefill.suggested_position == "00001234"


@pytest.mark.asyncio
async def test_leave_blank_stays_blank_even_for_a_single_position_role(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    """UAT review 2026-11-19: the page offered "Leave blank — I'll type it on the
    form", but a single-position role still got its one position written. A JD is
    reused across positions, so that position may not be the one being re-evaluated.
    The single position is only SUGGESTED (the page pre-selects it); what is written
    is exactly what the requester picked."""
    async with session_maker() as session:
        rid = await _role(
            session,
            content={"title": "Research Coordinator"},
            filenames=["20200601_00001234_JDFN_APSA_20211117.docx"],
        )
        await session.commit()
        prefill = await prefill_from_role(session, rid, request_type="reevaluation")

    assert prefill.suggested_position == "00001234"
    assert prefill.position_number is None
    assert prefill.based_on_positions_b == ()
    assert prefill.based_on_existing_b is False


@pytest.mark.asyncio
async def test_with_no_request_type_no_position_or_list_is_chosen(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    async with session_maker() as session:
        rid = await _role(
            session,
            content={"title": "Analyst"},
            filenames=["20200601_00001234_Analyst.docx"],
        )
        await session.commit()
        prefill = await prefill_from_role(session, rid)

    assert prefill.position_number is None
    assert prefill.based_on_positions_a == ()
    assert prefill.based_on_positions_b == ()
    assert prefill.candidate_positions == ("00001234",)  # offered to K3's picker
    assert prefill.position_title == "Analyst"


@pytest.mark.asyncio
async def test_a_new_position_with_no_pick_lists_nothing_as_based_on(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    """Section A asks which existing position the NEW one is based on. The Bank does
    not know; without a pick it lists nothing and asserts no "Yes"."""
    async with session_maker() as session:
        rid = await _role(
            session,
            content={"title": "Analyst"},
            filenames=["20200601_00001234_Analyst.docx"],
        )
        await session.commit()
        prefill = await prefill_from_role(
            session, rid, request_type="new_based_on_existing"
        )

    assert prefill.position_number is None  # the form says N/A if new
    assert prefill.based_on_positions_a == ()
    assert prefill.based_on_existing_a is False
    assert prefill.based_on_positions_b == ()


@pytest.mark.asyncio
async def test_a_multi_position_role_lists_only_the_picked_position(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    """UAT review 2026-11-19: a 58-position role wrote all 58 ids as "based on", and
    the overflow spilled into the requester's own Reason box. A role is a family of
    similar JDs, not a statement about which position this request concerns: only
    the requester's pick is written."""
    async with session_maker() as session:
        rid = await _role(
            session,
            content={"title": "Analyst"},
            filenames=[
                "20200601_00009999,_00001111_Analyst.docx",
                "20200601_00005555_Analyst.docx",
            ],
        )
        await session.commit()
        unpicked = await prefill_from_role(session, rid, request_type="reevaluation")
        picked = await prefill_from_role(
            session, rid, request_type="reevaluation", position_number="00005555"
        )

    assert unpicked.position_number is None
    assert unpicked.based_on_positions_b == ()
    assert unpicked.suggested_position is None  # several: nothing pre-selected
    assert unpicked.candidate_positions == ("00001111", "00005555", "00009999")
    assert picked.position_number == "00005555"
    assert picked.based_on_positions_b == ("00005555",)
    assert picked.based_on_existing_b is True


@pytest.mark.asyncio
async def test_an_unpadded_member_file_blocks_the_single_position_claim(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    """One member names 00001234; another's name holds no position the filename
    reader can read (a bare number after the title is not read, HR-330). The role may
    hold another position, so it must not be presented as a single one."""
    async with session_maker() as session:
        rid = await _role(
            session,
            content={"title": "Analyst"},
            filenames=[
                "20200601_00001234_Analyst.docx",
                "20060612_Clerk,_gr_7,_64368,_Res___Housing.doc",
            ],
        )
        await session.commit()
        prefill = await prefill_from_role(session, rid, request_type="reevaluation")

    assert prefill.positions_incomplete is True
    assert prefill.position_number is None
    assert prefill.suggested_position is None
    assert prefill.candidate_positions == ("00001234",)


_BUNDLE = "20200601_61,_30785,_208,_975_JDFN_APSA_20211117.docx"


@pytest.mark.asyncio
async def test_an_unpadded_leading_bundle_offers_every_position_it_names(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    """The full filename reader (HR-325 … HR-331): a role whose only member file leads
    with UNPADDED ids is no longer "we cannot see every position". ``61`` is two
    digits, so it counts only because ANOTHER file in the Bank names it padded
    (HR-328) — a file that is not even a member of this role."""
    async with session_maker() as session:
        await _doc(session, "20190101_00000061_Clerk.docx")  # vouches for 61
        rid = await _role(
            session,
            content={"title": "Advisor", "employee_group": "apsa"},
            filenames=[_BUNDLE],
        )
        await session.commit()
        prefill = await prefill_from_role(session, rid, request_type="reevaluation")

    assert prefill.positions_incomplete is False
    assert prefill.candidate_positions == (
        "00000061",
        "00000208",
        "00000975",
        "00030785",
    )
    assert prefill.position_number is None  # four positions: the Bank never picks
    assert prefill.based_on_positions_b == ()  # only a pick is ever listed


@pytest.mark.asyncio
async def test_an_unvouched_short_id_is_not_offered(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    """Without a padded witness anywhere in the Bank, ``61`` is held back (HR-328);
    the three longer ids still make the role's positions readable."""
    async with session_maker() as session:
        rid = await _role(session, content={"title": "Advisor"}, filenames=[_BUNDLE])
        await session.commit()
        prefill = await prefill_from_role(session, rid)

    assert prefill.candidate_positions == ("00000208", "00000975", "00030785")
    assert prefill.positions_incomplete is False


@pytest.mark.asyncio
async def test_without_crf_in_consumers_the_form_reads_only_padded_ids(
    session_maker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """HR-331 is read, not hardcoded: take ``crf`` out of ``consumers`` and the form
    falls back to ``segmentation.position_id_pattern`` — the bundle reads as nothing."""
    from src.jd_bank.forms import comp_requisition
    from src.jd_core.rules import get_rules

    rules = get_rules()
    seg = rules.segmentation
    off = seg.model_copy(
        update={
            "filename_positions": seg.filename_positions.model_copy(
                update={"consumers": frozenset()}
            )
        }
    )
    retuned = rules.model_copy(update={"segmentation": off})
    monkeypatch.setattr(comp_requisition, "get_rules", lambda: retuned)
    async with session_maker() as session:
        await _doc(session, "20190101_00000061_Clerk.docx")
        rid = await _role(session, content={"title": "Advisor"}, filenames=[_BUNDLE])
        await session.commit()
        prefill = await prefill_from_role(session, rid)

    assert prefill.candidate_positions == ()
    assert prefill.positions_incomplete is True


@pytest.mark.asyncio
async def test_the_department_follows_the_picked_position_s_own_file(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    """UAT review 2026-11-19: a role spanning Lifelong Learning, Physics, Chemistry…
    typed the ROLE's department whichever position was picked. The picked position's
    own source file says where THAT position sits (HR-337)."""
    async with session_maker() as session:
        rid = await _role(
            session,
            content={"title": "Analyst", "department": "Lifelong Learning"},
            filenames=[
                "20200601_00005555_Analyst.docx",
                "20210601_00005555_JDFN_APSA_20210601.docx",
                "20200601_00001111_Analyst.docx",
            ],
            parsed=[
                {"department": "Physics"},
                {"department": "physics"},
                {"department": "Lifelong Learning"},
            ],
        )
        await session.commit()
        picked = await prefill_from_role(
            session, rid, request_type="reevaluation", position_number="00005555"
        )
        unpicked = await prefill_from_role(session, rid, request_type="reevaluation")

    assert picked.department == "Physics"
    assert "department_from_position" in picked.filled_from_sources
    assert unpicked.department == "Lifelong Learning"
    assert "department_from_position" not in unpicked.filled_from_sources


@pytest.mark.asyncio
async def test_a_picked_position_whose_files_disagree_keeps_the_role_department(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    async with session_maker() as session:
        rid = await _role(
            session,
            content={"title": "Analyst", "department": "Lifelong Learning"},
            filenames=[
                "20200601_00005555_Analyst.docx",
                "20210601_00005555_JDFN_APSA_20210601.docx",
            ],
            parsed=[{"department": "Physics"}, {"department": "Chemistry"}],
        )
        await session.commit()
        picked = await prefill_from_role(
            session, rid, request_type="reevaluation", position_number="00005555"
        )

    assert picked.department == "Lifelong Learning"
    assert "department_from_position" not in picked.filled_from_sources


@pytest.mark.asyncio
async def test_the_word_attachment_is_never_claimed_by_the_builder(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    async with session_maker() as session:
        rid = await _role(
            session, content={"title": "A"}, filenames=["20200601_00001234_A.docx"]
        )
        await session.commit()
        assert (await prefill_from_role(session, rid)).jd_in_word_attached is False
        bundled = await prefill_from_role(session, rid, jd_in_word_attached=True)
        assert bundled.jd_in_word_attached is True


@pytest.mark.asyncio
async def test_what_the_bank_lacks_stays_none(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    async with session_maker() as session:
        rid = await _role(
            session,
            content={"title": "Clerk", "employee_group": "cupe"},
            filenames=["61,_30785,_208,_975_JDFN_CUPE_20211117.docx"],
        )
        await session.commit()
        prefill = await prefill_from_role(session, rid, request_type="reevaluation")

    assert prefill.position_number is None
    assert prefill.department is None
    assert prefill.employee_group is None  # CUPE: no such option
    assert prefill.based_on_positions_b == ()
    assert prefill.positions_incomplete is True
    assert prefill.position_title == "Clerk"


@pytest.mark.asyncio
async def test_only_the_current_version_is_read(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    async with session_maker() as session:
        rid = await _role(
            session,
            content={"title": "Old Title"},
            filenames=["20200101_00000001_a.docx"],
        )
        await _role(
            session,
            content={"title": "New Title"},
            filenames=["20200101_00000002_a.docx"],
            version=2,
            cluster_id=rid,
        )
        await session.commit()
        prefill = await prefill_from_role(session, rid)

    assert prefill.position_title == "New Title"
    assert prefill.candidate_positions == ("00000002",)


@pytest.mark.asyncio
async def test_an_unknown_role_is_a_lookup_error_not_an_empty_form(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    async with session_maker() as session:
        with pytest.raises(LookupError):
            await prefill_from_role(session, uuid.uuid4())


# ── K3: the caller picks ONE position for a multi-position role ──────────────────


@pytest.mark.asyncio
async def test_a_chosen_position_is_written_for_a_position_bearing_request(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    """A role spans positions and the builder never picks; K3's picker hands the
    chosen one in, and it must be one the role actually holds."""
    async with session_maker() as session:
        rid = await _role(
            session,
            content={"title": "Analyst"},
            filenames=[
                "20200601_00009999,_00001111_Analyst.docx",
                "20200601_00005555_Analyst.docx",
            ],
        )
        await session.commit()
        prefill = await prefill_from_role(
            session, rid, request_type="editorial", position_number="00005555"
        )

    assert prefill.position_number == "00005555"
    assert prefill.candidate_positions == ("00001111", "00005555", "00009999")


@pytest.mark.asyncio
async def test_a_position_the_role_does_not_hold_is_refused(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    async with session_maker() as session:
        rid = await _role(
            session,
            content={"title": "Analyst"},
            filenames=["20200601_00005555_Analyst.docx"],
        )
        await session.commit()
        with pytest.raises(ValueError, match="00007777"):
            await prefill_from_role(
                session, rid, request_type="reevaluation", position_number="00007777"
            )


@pytest.mark.asyncio
async def test_a_chosen_position_is_ignored_for_a_new_position(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    """Section A is a NEW position — the form says "N/A if new" — so the chosen id
    goes to the based-on list only, never to Position #."""
    async with session_maker() as session:
        rid = await _role(
            session,
            content={"title": "Analyst"},
            filenames=["20200601_00005555_Analyst.docx"],
        )
        await session.commit()
        prefill = await prefill_from_role(
            session,
            rid,
            request_type="new_based_on_existing",
            position_number="00005555",
        )

    assert prefill.position_number is None
    assert prefill.based_on_positions_a == ("00005555",)


# ── K3: what the role lacks, the sources may supply (HR-309 / HR-310) ─────────────


@pytest.mark.asyncio
async def test_a_fact_the_role_lacks_is_read_from_sources_that_agree(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    """The AV Systems Analyst case: the role said no department and no group, every
    source file said IT Services / APSA, and the form came out with only a title."""
    async with session_maker() as session:
        rid = await _role(
            session,
            content={"title": "AV Systems Analyst"},
            filenames=[
                "20190714_00126404_AV_Systems_Analyst.docx",
                "20191217_00126404_JDFN_APSA_20191120.docx",
            ],
            parsed=[
                {"department": "IT Services", "employee_group": "apsa", "grade": "07"},
                {"department": "it services", "employee_group": "apsa"},
            ],
        )
        await session.commit()
        prefill = await prefill_from_role(session, rid)

    assert prefill.department == "IT Services"
    assert prefill.employee_group == "APSA"
    assert prefill.filled_from_sources == ("department", "employee_group")
    assert prefill.reference_grades == ("07",)


@pytest.mark.asyncio
async def test_sources_that_disagree_leave_the_box_blank(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    async with session_maker() as session:
        rid = await _role(
            session,
            content={"title": "Analyst"},
            filenames=["a_00000001.docx", "b_00000002.docx"],
            parsed=[{"department": "Biology"}, {"department": "Chemistry"}],
        )
        await session.commit()
        prefill = await prefill_from_role(session, rid)

    assert prefill.department is None
    assert prefill.filled_from_sources == ()


@pytest.mark.asyncio
async def test_the_role_s_own_fact_wins_over_the_sources(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    async with session_maker() as session:
        rid = await _role(
            session,
            content={"title": "Analyst", "department": "Biology", "grade": "09"},
            filenames=["a_00000001.docx"],
            parsed=[{"department": "Chemistry", "grade": "08"}],
        )
        await session.commit()
        prefill = await prefill_from_role(session, rid)

    assert prefill.department == "Biology"
    assert prefill.filled_from_sources == ()
    assert prefill.reference_grades == ("08", "09")  # reference only, both shown


@pytest.mark.asyncio
async def test_a_stale_parse_is_not_a_source(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    async with session_maker() as session:
        rid = await _role(
            session,
            content={"title": "Analyst"},
            filenames=["a_00000001.docx"],
            parsed=[{"department": "Biology"}],
            parser_version="jd_segmenter_v1",
        )
        await session.commit()
        prefill = await prefill_from_role(session, rid)

    assert prefill.department is None


# ── K3: boxes and the requester (HR-311 / HR-312 / HR-313) ──────────────────────


@pytest.mark.asyncio
async def test_the_request_type_and_based_on_yes_are_asserted_only_when_written(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    async with session_maker() as session:
        rid = await _role(
            session,
            content={"title": "Analyst"},
            filenames=["a_00000001.docx"],
        )
        await session.commit()
        none = await prefill_from_role(session, rid)
        a = await prefill_from_role(
            session,
            rid,
            request_type="new_based_on_existing",
            position_number="00000001",
        )
        b = await prefill_from_role(
            session, rid, request_type="reevaluation", position_number="00000001"
        )
        c = await prefill_from_role(session, rid, request_type="editorial")

    assert none.request_type is None
    assert (none.based_on_existing_a, none.based_on_existing_b) == (False, False)
    assert a.request_type == "new_based_on_existing"
    assert (a.based_on_existing_a, a.based_on_existing_b) == (True, False)
    assert b.request_type == "reevaluation"
    assert (b.based_on_existing_a, b.based_on_existing_b) == (False, True)
    assert c.request_type == "editorial"
    assert (c.based_on_existing_a, c.based_on_existing_b) == (False, False)


@pytest.mark.asyncio
async def test_the_contact_is_whoever_the_caller_names_and_blank_otherwise(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    async with session_maker() as session:
        rid = await _role(
            session, content={"title": "Analyst"}, filenames=["a_00000001.docx"]
        )
        await session.commit()
        named = await prefill_from_role(
            session, rid, contact_name=" Pat Requester ", contact_email="p@sfu.ca"
        )
        blank = await prefill_from_role(session, rid)

    assert (named.contact_name, named.contact_email) == ("Pat Requester", "p@sfu.ca")
    assert (blank.contact_name, blank.contact_email) == (None, None)


@pytest.mark.asyncio
async def test_with_no_request_type_the_department_stays_the_role_s(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    """Judge review 2026-11-19: with no request type the picked position is never
    written, so the department must not silently switch to that position's."""
    async with session_maker() as session:
        rid = await _role(
            session,
            content={"title": "Analyst", "department": "Lifelong Learning"},
            filenames=["20200601_00005555_Analyst.docx"],
            parsed=[{"department": "Physics"}],
        )
        await session.commit()
        prefill = await prefill_from_role(session, rid, position_number="00005555")

    assert prefill.position_number is None
    assert prefill.department == "Lifelong Learning"

"""Integration — functional families against a real Postgres, through the real
migration (Phase A2).

What only a real database can prove, and what the design turns on:

1. **Membership is the classification family, and it ignores duty text entirely.** A
   role stuffed with every IT term in the rulebook is NOT a member unless its source
   filenames carry the family token. This is the measured finding in executable form:
   no term score decides membership at any cutoff.
2. **``exclude`` beats every other signal, ``include`` adds one.** A human ruling wins.
3. **The review queue ranks NON-members and carries its evidence**, ordered by matched
   terms — and the queue's cutoff moves the QUEUE, never the membership.
4. **The word boundary holds in Postgres too.** A JD about "planning" does not score for
   ``lan``. The Python guard is unit-tested; this is the same rule in the other dialect,
   where it is actually executed.
5. **The stats reconcile** — roles, the documents behind them, and how many are
   approvable, read from the stored gate decision (``validation_reports`` is empty and
   would answer 0 just as convincingly).
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
    SourceDocument,
)
from src.jd_bank.library import collection_stats, family_for, rank_candidates
from src.jd_bank.library.families import resolve_members
from src.jd_core.models.parsed_jd import SFUDuty, SFUJobDescription
from src.jd_core.rules import FunctionalFamily, get_rules
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
    maker = async_sessionmaker(engine, expire_on_commit=False)
    yield maker
    await engine.dispose()


@pytest.fixture
def it_family() -> FunctionalFamily:
    family = family_for("it")
    assert family is not None
    return family


def _jd(title: str, *, summary: str = "", duty: str = "") -> SFUJobDescription:
    return SFUJobDescription(
        title=title,
        employee_group="apsa",
        position_summary=summary or " ".join(["word"] * 30),
        duties=[
            SFUDuty(
                action_verb="Manages",
                statement=duty or "Manages the program end to end",
                how_why=["by coordinating stakeholders"],
            )
        ],
    )


async def _seed_role(
    session: AsyncSession,
    *,
    jd: SFUJobDescription,
    filenames: list[str],
    approved: bool = False,
    status: CanonicalStatus = CanonicalStatus.DRAFT,
    version: int = 1,
    cluster_id: uuid.UUID | None = None,
) -> uuid.UUID:
    """One role plus the source documents behind it, named as the archive names them."""
    cluster_id = cluster_id or uuid.uuid4()
    if await session.get(Cluster, cluster_id) is None:
        session.add(Cluster(id=cluster_id, label=jd.title, members=[]))
    source_ids: list[dict[str, object]] = []
    for filename in filenames:
        doc = SourceDocument(
            storage_ref=f"archive/{filename}",
            filename=filename,
            sha256=uuid.uuid4().hex,
            fmt=DocumentFormat.DOCX,
            byte_size=1234,
        )
        session.add(doc)
        await session.flush()
        source_ids.append({"source_id": str(doc.id)})
    session.add(
        CanonicalJD(
            cluster_id=cluster_id,
            version=version,
            status=status,
            content=jd.model_dump(mode="json"),
            source_document_ids=source_ids,
            change_log={"validator": {"gate_decision": {"approved": approved}}},
        )
    )
    await session.flush()
    return cluster_id


# --- membership -------------------------------------------------------------------


async def test_membership_is_the_classification_family_not_the_duty_terms(
    session_maker: async_sessionmaker[AsyncSession], it_family: FunctionalFamily
) -> None:
    """THE finding, executable. A role saturated with IT vocabulary is not a member;
    a role with none of it, but an ITP filename, is.

    Measured on the real archive: no term-score cutoff is both precise and complete —
    98% recall costs 46% of the archive, and trimming to a plausible size keeps 48.9%.
    So membership never consults the terms, and this test is what stops that changing
    quietly.
    """
    async with session_maker() as session:
        saturated = await _seed_role(
            session,
            jd=_jd(
                "Network Systems Developer",
                summary=(
                    "Maintains the network, servers, firewall, linux and unix hosts, "
                    "active directory, sql databases and web application middleware"
                ),
                duty="Designs data centre architecture and identity management",
            ),
            filenames=["20060503_00001_APSA_Something.doc"],
        )
        plain = await _seed_role(
            session,
            jd=_jd(
                "Business Analyst", summary="Gathers requirements from stakeholders"
            ),
            filenames=["20060503_30181_ITP_III_Gr_12.doc"],
        )
        await session.commit()

        members = await resolve_members(session, it_family)

    assert (
        plain in members
    ), "an ITP-filename role is a member on SFU's own classification"
    assert saturated not in members, (
        "duty terms must never confer membership — they were measured incapable of "
        "deciding it at any cutoff"
    )


async def test_classification_token_is_bounded_but_not_symmetrically(
    session_maker: async_sessionmaker[AsyncSession], it_family: FunctionalFamily
) -> None:
    """``ITP`` must be a token, not a fragment — but the archive jams the LEVEL onto it.

    Regression. A symmetric "non-letter on both sides" boundary rejected
    ``20120103_101503ITPIII.doc`` and nine like it, because the roman level runs
    straight into the code. That dropped 10 genuine documents and moved the
    collection's own headline from "469 → 45 roles" to "449 → 44" — a published figure
    and a shipped page disagreeing by a margin small enough to survive review.
    """
    async with session_maker() as session:
        separated = await _seed_role(
            session, jd=_jd("A"), filenames=["20060503_1353_ITP_IV_BPSI_Gr_13.doc"]
        )
        jammed = await _seed_role(
            session, jd=_jd("B"), filenames=["20120103_101503ITPIII.doc"]
        )
        comma = await _seed_role(
            session, jd=_jd("C"), filenames=["20120216_00102623ITPI,_Gr._10.doc"]
        )
        fragment = await _seed_role(
            session, jd=_jd("D"), filenames=["20060503_EXITPLAN_final.doc"]
        )
        lowercase_word = await _seed_role(
            session, jd=_jd("E"), filenames=["20060503_ITPlanning_notes.doc"]
        )
        await session.commit()
        members = await resolve_members(session, it_family)

    assert separated in members
    assert jammed in members, "the level runs into the code in 10 real archive files"
    assert comma in members
    assert fragment not in members, "'EXITPLAN' contains 'ITP' but is not an ITP JD"
    assert lowercase_word not in members, "'ITPlanning' is a word, not a classification"


async def test_exclude_beats_the_classification_and_include_adds(
    session_maker: async_sessionmaker[AsyncSession], it_family: FunctionalFamily
) -> None:
    """A human ruling always wins over a rule — that is why the overrides exist."""
    async with session_maker() as session:
        itp = await _seed_role(session, jd=_jd("ITP role"), filenames=["x_ITP_II.doc"])
        embedded = await _seed_role(
            session, jd=_jd("Library Systems Technician"), filenames=["x_CUPE_1.doc"]
        )
        await session.commit()

        overridden = it_family.model_copy(
            update={"include": (embedded,), "exclude": (itp,)}
        )
        members = await resolve_members(session, overridden)

    assert embedded in members, "`include` adds a role the signals missed"
    assert itp not in members, "`exclude` beats the classification family"


async def test_only_the_current_version_of_a_role_is_a_member(
    session_maker: async_sessionmaker[AsyncSession], it_family: FunctionalFamily
) -> None:
    """An edited role appears ONCE, as its newest version — never twice."""
    async with session_maker() as session:
        cluster = await _seed_role(
            session, jd=_jd("ITP role v1"), filenames=["a_ITP_I.doc"], version=1
        )
        await _seed_role(
            session,
            jd=_jd("ITP role v2"),
            filenames=["b_ITP_I.doc"],
            version=2,
            cluster_id=cluster,
        )
        await session.commit()
        members = await resolve_members(session, it_family)

    assert members == frozenset({cluster})


# --- the collection headline ------------------------------------------------------


async def test_stats_reconcile_roles_documents_and_approvable(
    session_maker: async_sessionmaker[AsyncSession], it_family: FunctionalFamily
) -> None:
    """Roles, the documents behind them, and how many pass every gate today.

    ``approvable`` is read from the STORED gate decision. ``validation_reports`` is
    empty in this Bank and every draft's ``validation_report_id`` is NULL, so a query
    against that table returns 0 and looks exactly like a real answer.
    """
    async with session_maker() as session:
        await _seed_role(
            session,
            jd=_jd("A"),
            filenames=["1_ITP_I.doc", "2_ITP_I.doc"],
            approved=True,
        )
        await _seed_role(
            session, jd=_jd("B"), filenames=["3_ITP_II.doc"], approved=False
        )
        await _seed_role(session, jd=_jd("Not IT"), filenames=["4_APSA.doc"])
        await session.commit()
        stats = await collection_stats(session, it_family)

    assert stats.roles == 2
    assert stats.source_documents == 3
    assert stats.approvable == 1
    assert stats.slug == "it"
    assert stats.recall_note.strip(), "a family must publish how it under-recalls"


async def test_stats_on_an_empty_family_are_zero_not_the_whole_archive(
    session_maker: async_sessionmaker[AsyncSession], it_family: FunctionalFamily
) -> None:
    """The direction of this failure decides whether an empty family shows nothing or
    shows everything."""
    async with session_maker() as session:
        await _seed_role(session, jd=_jd("Anything"), filenames=["1_APSA.doc"])
        await session.commit()
        empty = it_family.model_copy(update={"classification_families": ()})
        stats = await collection_stats(session, empty)

    assert (stats.roles, stats.source_documents, stats.approvable) == (0, 0, 0)


# --- the review queue: ordering only ----------------------------------------------


async def test_queue_ranks_non_members_and_shows_its_evidence(
    session_maker: async_sessionmaker[AsyncSession], it_family: FunctionalFamily
) -> None:
    """The worklist excludes members, orders by matched terms, and says why each row
    surfaced — as COUNTS, never a percentage or a confidence."""
    async with session_maker() as session:
        member = await _seed_role(
            session, jd=_jd("An ITP role"), filenames=["1_ITP_I.doc"]
        )
        strong = await _seed_role(
            session,
            jd=_jd(
                "Computer Systems Administrator",
                summary=(
                    "Maintains network, servers, firewall, linux, unix, sql databases, "
                    "active directory and desktop workstations"
                ),
                duty="Provides technical support and troubleshooting for computing",
            ),
            filenames=["2_CUPE.doc"],
        )
        weak = await _seed_role(
            session,
            jd=_jd("Program Assistant", summary="Coordinates events and schedules"),
            filenames=["3_APSA.doc"],
        )
        await session.commit()
        queue = await rank_candidates(session, it_family, rules=get_rules())

    ids = [candidate.cluster_id for candidate in queue]
    assert member not in ids, "a member is not a candidate for its own family"
    assert weak not in ids, "a role with no family vocabulary does not reach the queue"
    assert strong in ids
    top = next(c for c in queue if c.cluster_id == strong)
    assert top.duty_matches > 0 and top.title_matches > 0
    assert top.matches == top.duty_matches + top.title_matches


async def test_postgres_word_boundary_holds_for_lan(
    session_maker: async_sessionmaker[AsyncSession], it_family: FunctionalFamily
) -> None:
    """The 63%-of-the-corpus defect, in the dialect where it is actually executed.

    Matched as a substring, ``lan`` hits "plan"/"planning" and pulled 1,568 of 2,493
    roles into the cohort — a confident, wrong, plausible-looking answer.
    """
    async with session_maker() as session:
        await _seed_role(
            session,
            jd=_jd(
                "Planning Officer",
                summary="Plans the annual plan and planning cycle for Langara liaison",
                duty="Plans and re-plans the planning calendar",
            ),
            filenames=["1_APSA.doc"],
        )
        await session.commit()
        # Only `lan`, so any hit at all is the substring defect.
        lan_only = it_family.model_copy(
            update={"duty_terms": ("lan",), "title_terms": ()}
        )
        queue = await rank_candidates(session, lan_only, rules=get_rules())

    assert queue == (), "'planning' must not score for the term 'lan'"


async def test_the_cutoff_moves_the_queue_not_the_membership(
    session_maker: async_sessionmaker[AsyncSession], it_family: FunctionalFamily
) -> None:
    """The knob is a queue DEPTH. Raising it shortens the worklist and changes nobody's
    membership — at the shipped value the sweep finds only 17.8% of the roles SFU's own
    classification calls IT, so were it ever a membership test it would discard three of
    every four of them."""
    async with session_maker() as session:
        await _seed_role(session, jd=_jd("An ITP role"), filenames=["1_ITP_I.doc"])
        await _seed_role(
            session,
            jd=_jd(
                "Computer Technician",
                summary="Supports desktop workstations, network and servers",
                duty="Provides technical support and troubleshooting",
            ),
            filenames=["2_CUPE.doc"],
        )
        await session.commit()

        before = await resolve_members(session, it_family)
        rules = get_rules()
        generous = rules.model_copy(
            update={
                "functional_families": rules.functional_families.model_copy(
                    update={"review_queue_min_score": 1}
                )
            }
        )
        strict = rules.model_copy(
            update={
                "functional_families": rules.functional_families.model_copy(
                    update={"review_queue_min_score": 99}
                )
            }
        )
        long_queue = await rank_candidates(session, it_family, rules=generous)
        short_queue = await rank_candidates(session, it_family, rules=strict)
        after = await resolve_members(session, it_family)

    assert len(long_queue) > len(short_queue) == 0
    assert before == after, "the cutoff must not move membership in either direction"


async def test_a_department_match_also_raises_a_candidate(
    session_maker: async_sessionmaker[AsyncSession], it_family: FunctionalFamily
) -> None:
    """A role in the unit's DEPARTMENT reaches the queue even with no family vocabulary.

    Measured before this existed: 47 roles carried an ITS department without the ITP
    classification, and **45 of them were surfaced nowhere at all** — not members, not
    candidates. They included *Systems Administrator*, *Senior Systems Engineer* and
    *PeopleSoft Developer*: titles no IT director would accept as "not IT". The
    duty-term sweep missed them because they score below the queue cutoff, which is
    the same recall
    failure the sweep has now shown three times.

    ⚠ This raises a CANDIDATE, never a member. Department is evidence for a human
    to rule
    on — the measured reason being that a unit's own name matches a fraction of its
    portfolio, and academic units (`School of Computing Science`) look exactly like the
    real thing to any matcher.
    """
    async with session_maker() as session:
        by_department = await _seed_role(
            session,
            # No IT vocabulary anywhere: the duty sweep alone cannot see this role.
            jd=_jd(
                "Office Assistant", summary="Coordinates schedules and correspondence"
            ),
            filenames=["1_CUPE.doc"],
        )
        elsewhere = await _seed_role(
            session,
            jd=_jd(
                "Office Assistant", summary="Coordinates schedules and correspondence"
            ),
            filenames=["2_CUPE.doc"],
        )
        await session.execute(
            text(
                "UPDATE canonical_jds SET content = jsonb_set("
                "  content, '{department}', '\"IT Services\"') WHERE cluster_id = :c"
            ),
            {"c": by_department},
        )
        await session.execute(
            text(
                "UPDATE canonical_jds SET content = jsonb_set("
                "  content, '{department}', '\"Faculty of Education\"')"
                " WHERE cluster_id = :c"
            ),
            {"c": elsewhere},
        )
        await session.commit()

        with_dept = it_family.model_copy(update={"department_terms": ("IT Services",)})
        queue = await rank_candidates(session, with_dept, rules=get_rules())

    ids = [c.cluster_id for c in queue]
    assert (
        by_department in ids
    ), "a role in the unit's department must reach the queue even with no IT vocabulary"
    assert elsewhere not in ids, "an unrelated department does not raise a candidate"
    hit = next(c for c in queue if c.cluster_id == by_department)
    assert hit.department_match is True
    assert hit.duty_matches == 0, "it got here on department alone — say so honestly"


async def test_a_department_match_does_not_confer_membership(
    session_maker: async_sessionmaker[AsyncSession], it_family: FunctionalFamily
) -> None:
    """⚠ The whole design in one assertion. Department is a CANDIDATE signal only.

    A unit's own name matches a fraction of its portfolio (VPFA: 2 roles against ~55+),
    and `School of Computing Science` looks exactly like ITS to any matcher. Letting a
    department string decide membership would be the department-taxonomy error the
    functional plan was written to avoid.
    """
    async with session_maker() as session:
        cluster = await _seed_role(
            session, jd=_jd("Systems Administrator"), filenames=["1_CUPE.doc"]
        )
        await session.execute(
            text(
                "UPDATE canonical_jds SET content = jsonb_set("
                "  content, '{department}', '\"IT Services\"') WHERE cluster_id = :c"
            ),
            {"c": cluster},
        )
        await session.commit()
        with_dept = it_family.model_copy(update={"department_terms": ("IT Services",)})
        members = await resolve_members(session, with_dept)

    assert cluster not in members, "department raises candidates, never members"

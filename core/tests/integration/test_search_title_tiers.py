"""Integration — Track I2: the title passes behind Builder AND library search, on a real
Postgres migrated to head (so ``pg_trgm`` + the 0007 trigram indexes exist).

What only a real database can prove:

* the document-title pass reads only the CURRENT parse (``parser_version ==
  PARSER_VERSION``) — measured on the live Bank, 47 of 2,011 "Coordinator" documents
  matched only through a superseded parse;
* the typo FALLBACK (per-word ``strict_word_similarity`` floor, HR-241) recovers
  "labratory techician" / "adminstrative cordinator", runs only when no title contains
  the query, and does not turn an abbreviation ("coop coord") into a page of noise;
* the planner CAN serve the title expressions from the trigram indexes — the query
  spells the JSON key as a literal so the expression matches the index.

The embed host is a dead fake throughout: everything asserted here is title-pass
behaviour, which must not need the GPU.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import asyncpg
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.jd_bank.composer import search as search_mod
from src.jd_bank.db.models import ParsedJDRow
from src.jd_bank.library import list_roles
from src.jd_core.models.quality import WJQ_TEMPLATE
from src.jd_core.parser import PARSER_VERSION
from src.jd_core.rules import get_rules
from tests.integration.test_library_service import (  # noqa: F401
    _jd,
    _seed_role,
    _seed_source,
    migrated_pg_url,
    session_maker,
)
from tests.unit.retuned_rules import retuned_embeddings


class _DeadEmbed:
    async def embed_batch(self, texts: Any) -> list[list[float]]:
        raise ConnectionRefusedError("the inference host is down")


def _dead() -> dict[str, Any]:
    return {"embed_client": _DeadEmbed(), "neo4j_driver": object()}


async def _roles(
    session: AsyncSession, *specs: tuple[str, str]
) -> dict[str, uuid.UUID]:
    out: dict[str, uuid.UUID] = {}
    for title, group in specs:
        out[title], _ = await _seed_role(
            session, content=_jd(title, employee_group=group), members=[]
        )
    await session.commit()
    return out


# --- the extension and indexes exist at head ------------------------------------------


@pytest.mark.asyncio
async def test_head_has_pg_trgm_and_both_title_indexes(
    session_maker: async_sessionmaker[AsyncSession],  # noqa: F811
) -> None:
    async with session_maker() as session:
        extensions = set(
            (await session.scalars(text("SELECT extname FROM pg_extension"))).all()
        )
        indexes = set(
            (
                await session.scalars(
                    text("SELECT indexname FROM pg_indexes WHERE schemaname = 'public'")
                )
            ).all()
        )
    assert {"pg_trgm", "btree_gin"} <= extensions
    assert {
        "ix_parsed_jds_version_title_trgm",
        "ix_canonical_jds_title_trgm",
    } <= indexes


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("statement", "index"),
    [
        (lambda: search_mod._doc_title_statement("Coordinator", limit=30), "ix_parsed"),
        (
            lambda: search_mod._role_title_statement("Coordinator", limit=30),
            "ix_canonical_jds_title_trgm",
        ),
        (
            lambda: search_mod._doc_typo_statement(["labratory"], "labratory", 30),
            "ix_parsed",
        ),
        (
            lambda: search_mod._role_typo_statement(["labratory"], "labratory", 30),
            "ix_canonical_jds_title_trgm",
        ),
    ],
    ids=["doc-contains", "role-contains", "doc-typo", "role-typo"],
)
async def test_the_title_expressions_can_be_served_by_the_trigram_indexes(
    session_maker: async_sessionmaker[AsyncSession],  # noqa: F811
    statement: Any,
    index: str,
) -> None:
    """The index EXPRESSION must match the query expression character for character.
    ``CanonicalJD.content["title"].astext`` renders the key as a bound parameter
    (``->> $1``), which a prepared statement's generic plan cannot match to an index on
    ``->> 'title'`` — so the search spells it as a literal, and this proves the match.

    On an empty table the planner prefers any other index, so inside a transaction that
    is ROLLED BACK every other index on the table is dropped and sequential scans are
    disabled: the trigram index is then the only cheap path, and the plan uses it only
    if the expressions match."""
    # Planned exactly as the app's prepared statement is, GENERICALLY (after five runs
    # Postgres may stop re-planning per value): bound parameters stay parameters.
    compiled = statement().compile(dialect=asyncpg.dialect())
    params = [compiled.params[name] for name in (compiled.positiontup or [])]

    def _literal(value: Any) -> str:
        if isinstance(value, int):
            return str(value)
        return "'" + str(value).replace("'", "''") + "'"

    table = "parsed_jds" if index == "ix_parsed" else "canonical_jds"
    async with session_maker() as session:
        others = (
            await session.execute(
                text(
                    "SELECT c.relname, con.conname FROM pg_index i "
                    "JOIN pg_class c ON c.oid = i.indexrelid "
                    "LEFT JOIN pg_constraint con ON con.conindid = i.indexrelid "
                    "AND con.conrelid = i.indrelid "
                    "WHERE i.indrelid = CAST(:t AS regclass) "
                    "AND c.relname NOT LIKE '%trgm'"
                ),
                {"t": table},
            )
        ).all()
        for name, constraint in others:
            if constraint is not None:
                await session.execute(
                    text(f"ALTER TABLE {table} DROP CONSTRAINT {constraint} CASCADE")
                )
            else:
                await session.execute(text(f"DROP INDEX IF EXISTS {name}"))
        await session.execute(text("SET LOCAL enable_seqscan = off"))
        await session.execute(text("SET LOCAL plan_cache_mode = force_generic_plan"))
        conn = await session.connection()
        await conn.exec_driver_sql(f"PREPARE title_probe AS {compiled}")
        args = ", ".join(_literal(p) for p in params)
        explain = (
            f"EXPLAIN EXECUTE title_probe({args})"
            if args
            else "EXPLAIN EXECUTE title_probe"
        )
        plan = "\n".join(row[0] for row in (await conn.exec_driver_sql(explain)).all())
        await conn.exec_driver_sql("DEALLOCATE title_probe")
        await session.rollback()
    assert index in plan, plan


# --- the document-title pass reads the CURRENT parse only ----------------------------


async def _doc_with_superseded_title(
    session: AsyncSession, *, current: str, superseded: str
) -> uuid.UUID:
    doc = await _seed_source(
        session, filename=f"{uuid.uuid4().hex}.docx", jd=_jd(current)
    )
    session.add(
        ParsedJDRow(
            source_document_id=doc,
            parsed=_jd(superseded).model_dump(mode="json"),
            parser_version=f"{PARSER_VERSION}-superseded",
            parse_confidence=0.5,
            created_at=datetime(2020, 1, 1, tzinfo=UTC),
        )
    )
    await session.commit()
    return doc


@pytest.mark.asyncio
async def test_builder_never_finds_a_document_through_a_superseded_parse(
    session_maker: async_sessionmaker[AsyncSession],  # noqa: F811
) -> None:
    async with session_maker() as session:
        doc = await _doc_with_superseded_title(
            session, current="Budget Analyst", superseded="Events Coordinator"
        )
        old = await search_mod.search_jds(
            "Events Coordinator", session=session, **_dead()
        )
        new = await search_mod.search_jds("Budget Analyst", session=session, **_dead())

    assert old.hits == [], "a title the current parse no longer has must not match"
    assert [(h.source_document_id, h.title) for h in new.hits] == [
        (doc, "Budget Analyst")
    ]
    assert new.hits[0].match == "title"


@pytest.mark.asyncio
async def test_builder_title_tiers_rank_exact_first_before_the_page_is_cut(
    session_maker: async_sessionmaker[AsyncSession],  # noqa: F811
) -> None:
    """The role pass used to LIMIT before it ranked, so with more than ``3 x limit``
    contains-matches the exact title could be cut off the page entirely."""
    async with session_maker() as session:
        titles = [(f"Senior Analyst {i:02d}", "apsa") for i in range(12)]
        ids = await _roles(session, *titles, ("Analyst", "apsa"))
        out = await search_mod.search_jds(
            "analyst", session=session, limit=3, **_dead()
        )

    assert out.hits[0].cluster_id == ids["Analyst"]
    assert len(out.hits) == 3


# --- the typo fallback ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_builder_recovers_typed_typos_in_a_role_title(
    session_maker: async_sessionmaker[AsyncSession],  # noqa: F811
) -> None:
    async with session_maker() as session:
        ids = await _roles(
            session,
            ("Laboratory Technician", "cupe"),
            ("Administrative Coordinator", "apsa"),
            ("Residence Orientation Coordinator", "apsa"),
        )
        lab = await search_mod.search_jds(
            "labratory techician", session=session, form=WJQ_TEMPLATE, **_dead()
        )
        admin = await search_mod.search_jds(
            "adminstrative cordinator", session=session, **_dead()
        )

    assert [h.cluster_id for h in lab.hits] == [ids["Laboratory Technician"]]
    assert lab.hits[0].match == "role_title" and lab.hits[0].by_spelling is True
    assert lab.hits[0].score is None, "a spelling match carries no number"
    assert admin.hits[0].cluster_id == ids["Administrative Coordinator"]
    assert ids["Residence Orientation Coordinator"] not in {
        h.cluster_id for h in admin.hits
    }


@pytest.mark.asyncio
async def test_builder_recovers_a_typo_in_a_current_document_title(
    session_maker: async_sessionmaker[AsyncSession],  # noqa: F811
) -> None:
    async with session_maker() as session:
        doc = await _doc_with_superseded_title(
            session, current="Laboratory Technician", superseded="Old Name"
        )
        await _doc_with_superseded_title(
            session, current="Unrelated Role", superseded="Laboratory Technician"
        )
        out = await search_mod.search_jds(
            "labratory techician", session=session, **_dead()
        )

    assert [h.source_document_id for h in out.hits] == [doc]
    assert out.hits[0].match == "title" and out.hits[0].by_spelling is True


@pytest.mark.asyncio
async def test_the_typo_tier_is_a_fallback_not_an_extra_pass(
    session_maker: async_sessionmaker[AsyncSession],  # noqa: F811
) -> None:
    """When any title CONTAINS the query, no spelling matches are mixed in: the
    fallback exists for the query that would otherwise reach the vectors with nothing.
    """
    async with session_maker() as session:
        await _roles(session, ("Coordinator", "apsa"), ("Coordnator Typo", "apsa"))
        builder = await search_mod.search_jds("coordinator", session=session, **_dead())
        library = await list_roles(session, q="coordinator")

    assert [h.title for h in builder.hits] == ["Coordinator"]
    assert not any(h.by_spelling for h in builder.hits)
    assert [i.title for i in library.items] == ["Coordinator"]
    assert {i.matched_by for i in library.items} == {"title"}


@pytest.mark.asyncio
async def test_an_abbreviation_is_not_turned_into_spelling_noise(
    session_maker: async_sessionmaker[AsyncSession],  # noqa: F811
) -> None:
    """MEASURED over the live titles: whole-query ``word_similarity`` scores "coop
    coord" at 0.63 against ~445 unrelated "...Coordinator" roles, because a partial word
    extent counts. The fallback requires EVERY typed word to match a whole title word,
    so an abbreviation finds nothing here and is left to the meaning passes."""
    async with session_maker() as session:
        await _roles(
            session,
            ("Residence Orientation Coordinator", "apsa"),
            ("Facilities Service Coordinator", "apsa"),
        )
        builder = await search_mod.search_jds("coop coord", session=session, **_dead())
        library = await list_roles(session, q="coop coord")

    assert builder.hits == []
    assert library.total == 0


@pytest.mark.asyncio
async def test_the_library_recovers_a_typo_and_says_why_it_matched(
    session_maker: async_sessionmaker[AsyncSession],  # noqa: F811
) -> None:
    async with session_maker() as session:
        ids = await _roles(
            session,
            ("Administrative Coordinator", "apsa"),
            ("Administrative Coordinator, Faculty of Science", "apsa"),
            ("Library Clerk", "cupe"),
        )
        page = await list_roles(session, q="adminstrative cordinator")

    assert {i.cluster_id for i in page.items} == {
        ids["Administrative Coordinator"],
        ids["Administrative Coordinator, Faculty of Science"],
    }
    assert {i.matched_by for i in page.items} == {"spelling"}
    assert page.items[0].title == "Administrative Coordinator", "ranked, closest first"


@pytest.mark.asyncio
async def test_the_typo_floor_is_read_from_the_rulebook(
    session_maker: async_sessionmaker[AsyncSession],  # noqa: F811
) -> None:
    """HR-241 is a live knob: raise it past the typo's similarity and nothing is
    recovered — in both boxes."""
    strict = retuned_embeddings(get_rules(), title_typo_min_similarity=0.95)
    async with session_maker() as session:
        await _roles(session, ("Laboratory Technician", "cupe"))
        builder = await search_mod.search_jds(
            "labratory techician",
            session=session,
            form=WJQ_TEMPLATE,
            rules=strict,
            **_dead(),
        )
        library = await list_roles(session, q="labratory techician", rules=strict)

    assert builder.hits == []
    assert library.total == 0

"""Integration — "my drafts" reads back what the Builder wrote, against a real Postgres.

This is a JSONB query over ``clusters.constraint_metadata`` written by a *different*
module (:mod:`src.jd_bank.composer.persist`), and the two only agree if the key names
and the ``->>`` operators line up on a real database. A fake session cannot prove any of
that, so the route's unit tests deliberately do not try (see CLAUDE.md: pick the gate by
what the diff touches).

Three properties, and the second is the one that would be a breach if it broke:

1. an author sees the draft they submitted, with its stored score/grade roll-up;
2. an author sees **only their own** — the filter is the authenticated username;
3. a role that has been edited into a new version appears **once**, as its newest
   version, not once per version.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from testcontainers.postgres import PostgresContainer

from src.jd_bank.composer import list_authored_drafts, submit_composed_draft
from src.jd_bank.db.models import CanonicalJD, CanonicalStatus
from src.jd_core.models.parsed_jd import SFUDuty, SFUJobDescription
from tests.integration.test_dedup_tier1 import ALEMBIC_INI

AUTHOR = "author-1"
SOMEONE_ELSE = "author-2"


def _draft(title: str) -> SFUJobDescription:
    """A minimal composed draft — this is a READ test; the validator roll-up it stores
    is whatever the real scoring path makes of it, which is the point."""
    return SFUJobDescription(
        title=title,
        employee_group="apsa",
        position_summary=" ".join(["word"] * 60),
        duties=[SFUDuty(action_verb="Manages", statement="Manages the program")],
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
        await conn.execute(text("DELETE FROM canonical_jds"))
        await conn.execute(text("DELETE FROM clusters"))
        await conn.execute(text("DELETE FROM audit_log"))
    maker = async_sessionmaker(engine, expire_on_commit=False)
    yield maker
    await engine.dispose()


async def test_an_author_reads_back_the_draft_they_submitted(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    async with session_maker() as session:
        await submit_composed_draft(
            session, _draft("Research Coordinator"), author_id=AUTHOR
        )
        await session.commit()

    async with session_maker() as session:
        drafts = await list_authored_drafts(session, author_id=AUTHOR)

    assert [d.title for d in drafts] == ["Research Coordinator"]
    assert drafts[0].status == "draft"
    assert drafts[0].version == 1
    # The stored roll-up the queue and the library also show — display-only, but it must
    # actually arrive rather than silently read as "—" on every row.
    assert drafts[0].score is not None
    assert drafts[0].grade


async def test_an_author_never_sees_someone_elses_unpublished_draft(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    """Unpublished draft JD content is exactly what P0.1a was about."""
    async with session_maker() as session:
        await submit_composed_draft(session, _draft("Mine"), author_id=AUTHOR)
        await submit_composed_draft(session, _draft("Theirs"), author_id=SOMEONE_ELSE)
        await session.commit()

    async with session_maker() as session:
        mine = await list_authored_drafts(session, author_id=AUTHOR)
        theirs = await list_authored_drafts(session, author_id=SOMEONE_ELSE)

    assert [d.title for d in mine] == ["Mine"]
    assert [d.title for d in theirs] == ["Theirs"]


async def test_an_edited_role_appears_once_as_its_newest_version(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    """A reviewer's edit mints ``version + 1`` on the same cluster and archives the
    prior row. Listing rows rather than roles would show the author the same JD twice,
    the older of which is a lie about where their work stands."""
    async with session_maker() as session:
        canonical = await submit_composed_draft(
            session, _draft("Research Coordinator"), author_id=AUTHOR
        )
        await session.flush()
        canonical.status = CanonicalStatus.ARCHIVED
        session.add(
            CanonicalJD(
                cluster_id=canonical.cluster_id,
                version=2,
                status=CanonicalStatus.DRAFT,
                content={"title": "Research Coordinator (revised)"},
                source_document_ids=[],
                change_log={"validator": {"score": 90.0, "grade": "A"}},
            )
        )
        await session.commit()

    async with session_maker() as session:
        drafts = await list_authored_drafts(session, author_id=AUTHOR)

    assert len(drafts) == 1
    assert drafts[0].version == 2
    assert drafts[0].title == "Research Coordinator (revised)"


async def test_an_author_with_nothing_submitted_gets_an_empty_list(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    async with session_maker() as session:
        assert await list_authored_drafts(session, author_id="nobody") == []
        # A blank username must never be a wildcard.
        assert await list_authored_drafts(session, author_id="  ") == []

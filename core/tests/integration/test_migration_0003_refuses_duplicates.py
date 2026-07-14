"""Integration test — migration ``0003``'s upgrade REFUSES rather than deleting.

``0003`` adds ``uq_parsed_source_parser`` on ``(source_document_id, parser_version)``.
If duplicate pairs already exist — exactly LANDMINE 1's symptom, from a driver run
made before the constraint existed — the constraint cannot be created, and the
migration has a choice: delete rows to make room for itself, or refuse.

It refuses, loudly, naming the count. This test is what proves that: the refusal is the
one branch of ``0003`` that a normal ``upgrade head`` never reaches (the table is
empty), so without it the message is a promise nobody has checked. Mirrors ``0002``'s
downgrade refusal, whose hazard runs the other way.

Deliberately runs on its OWN Postgres container, upgraded only as far as ``0002`` —
the other integration suites go straight to ``head``, which is where the constraint
already exists and duplicates are impossible.

These tests are deliberately **synchronous**. ``alembic/env.py`` drives the migration
with its own ``asyncio.run()``, which cannot nest inside pytest-asyncio's
already-running loop — so the test body stays sync and the async DB helpers below are
driven with ``asyncio.run`` (legal here precisely because no loop is running).
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Iterator

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import create_async_engine
from testcontainers.postgres import PostgresContainer

from tests.integration.test_parse_and_store import ALEMBIC_INI

_PRE_CONSTRAINT_REVISION = "0002_one_row_per_file"


@pytest.fixture
def pg_at_0002() -> Iterator[tuple[Config, str]]:
    """A database migrated to ``0002`` — i.e. BEFORE the unique constraint exists."""
    with PostgresContainer("postgres:16-alpine") as pg:
        # asyncpg throughout: the image ships no psycopg2 driver.
        url = pg.get_connection_url().replace("psycopg2", "asyncpg")
        cfg = Config(str(ALEMBIC_INI))
        cfg.set_main_option("sqlalchemy.url", url)
        command.upgrade(cfg, _PRE_CONSTRAINT_REVISION)
        yield cfg, url


async def _seed_a_duplicate_parse(url: str) -> None:
    """Two ``parsed_jds`` rows for ONE ``(source_document_id, parser_version)`` — what
    the pre-3.2a ``parse_and_store`` produced on every re-run of the archive."""
    engine = create_async_engine(url)
    source_id = uuid.uuid4()
    async with engine.begin() as conn:
        await conn.execute(
            sa.text(
                "INSERT INTO source_documents "
                "(id, storage_ref, filename, sha256, fmt, byte_size) VALUES "
                "(:id, 'archive/dupe.txt', 'dupe.txt', :sha, 'TXT', 10)"
            ),
            {"id": source_id, "sha": "a" * 64},
        )
        for _ in range(2):
            await conn.execute(
                sa.text(
                    "INSERT INTO parsed_jds "
                    "(id, source_document_id, parsed, parser_version, "
                    " parse_confidence) VALUES "
                    "(:id, :src, '{}'::jsonb, 'jd_segmenter_v1', 0.5)"
                ),
                {"id": uuid.uuid4(), "src": source_id},
            )
    await engine.dispose()


async def _scalar(url: str, sql: str) -> object:
    engine = create_async_engine(url)
    async with engine.connect() as conn:
        value = (await conn.execute(sa.text(sql))).scalar_one_or_none()
    await engine.dispose()
    return value


def test_0003_refuses_to_upgrade_over_duplicate_parses(
    pg_at_0002: tuple[Config, str],
) -> None:
    cfg, url = pg_at_0002
    asyncio.run(_seed_a_duplicate_parse(url))

    with pytest.raises(RuntimeError) as excinfo:
        command.upgrade(cfg, "head")

    message = str(excinfo.value)
    assert "uq_parsed_source_parser" in message
    assert "1 (source_document_id, parser_version) pairs" in message
    # It tells the operator what to do — it does NOT do it for them.
    assert "a migration will not do it for you" in message

    # ...and it changed nothing: both rows are still there, for the human to triage.
    assert asyncio.run(_scalar(url, "SELECT count(*) FROM parsed_jds")) == 2


def test_0003_upgrades_cleanly_when_there_are_no_duplicates(
    pg_at_0002: tuple[Config, str],
) -> None:
    """The happy path, and the one the real database took: an empty (or already-unique)
    ``parsed_jds`` upgrades without complaint, and the constraint is then live."""
    cfg, url = pg_at_0002
    command.upgrade(cfg, "head")

    live = asyncio.run(
        _scalar(
            url,
            "SELECT conname FROM pg_constraint "
            "WHERE conname = 'uq_parsed_source_parser'",
        )
    )
    assert live == "uq_parsed_source_parser"

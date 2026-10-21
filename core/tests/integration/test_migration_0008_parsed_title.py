"""Integration test — migration ``0008``: the STORED ``parsed_jds.title`` column and
its trigram index, reversible, and the column is Postgres's own copy of the JSON title.

Own Postgres container (it walks the schema down and back up), synchronous because
``alembic/env.py`` drives migrations with its own ``asyncio.run()``.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import create_async_engine
from testcontainers.postgres import PostgresContainer

from tests.integration.test_parse_and_store import ALEMBIC_INI

_NEW = "ix_parsed_jds_version_title_col_trgm"
_OLD = "ix_parsed_jds_version_title_trgm"


@pytest.fixture
def pg() -> Iterator[tuple[Config, str]]:
    with PostgresContainer("postgres:16-alpine") as container:
        url = container.get_connection_url().replace("psycopg2", "asyncpg")
        cfg = Config(str(ALEMBIC_INI))
        cfg.set_main_option("sqlalchemy.url", url)
        yield cfg, url


async def _state(url: str) -> tuple[bool, dict[str, bool]]:
    engine = create_async_engine(url)
    async with engine.connect() as conn:
        has_column = bool(
            (
                await conn.execute(
                    sa.text(
                        "SELECT count(*) FROM information_schema.columns "
                        "WHERE table_name = 'parsed_jds' AND column_name = 'title'"
                    )
                )
            ).scalar()
        )
        rows = await conn.execute(
            sa.text(
                "SELECT c.relname, i.indisvalid FROM pg_index i "
                "JOIN pg_class c ON c.oid = i.indexrelid WHERE c.relname = ANY(:n)"
            ),
            {"n": [_NEW, _OLD]},
        )
        indexes = {name: valid for name, valid in rows}
    await engine.dispose()
    return has_column, indexes


async def _title_round_trip(url: str) -> str | None:
    """Insert a parse at head and read back the column Postgres computed."""
    engine = create_async_engine(url)
    async with engine.begin() as conn:
        doc = (
            await conn.execute(
                sa.text(
                    "INSERT INTO source_documents (id, filename, storage_ref, sha256, "
                    "byte_size, fmt, ingest_metadata) VALUES (gen_random_uuid(), "
                    "'a.docx', '/archive/a.docx', repeat('a', 64), 1, 'DOCX', '{}') "
                    "RETURNING id"
                )
            )
        ).scalar()
        title = (
            await conn.execute(
                sa.text(
                    "INSERT INTO parsed_jds (id, source_document_id, parsed, "
                    "parser_version, parse_confidence) VALUES (gen_random_uuid(), :d, "
                    "CAST(:p AS jsonb), 'v', 0.5) RETURNING title"
                ),
                {"d": doc, "p": json.dumps({"title": "Payroll Coordinator"})},
            )
        ).scalar()
    await engine.dispose()
    return title


def test_0008_adds_a_stored_title_and_swaps_the_index(pg: tuple[Config, str]) -> None:
    cfg, url = pg
    command.upgrade(cfg, "head")
    assert asyncio.run(_state(url)) == (True, {_NEW: True})
    assert asyncio.run(_title_round_trip(url)) == "Payroll Coordinator"

    command.downgrade(cfg, "0007_title_trigram_indexes")
    assert asyncio.run(_state(url)) == (False, {_OLD: True})

    command.upgrade(cfg, "head")
    assert asyncio.run(_state(url)) == (True, {_NEW: True})

"""Integration test — migration ``0007`` (pg_trgm + the two title trigram indexes) is
reversible, and re-runnable after a half-finished concurrent build.

Runs on its OWN Postgres container, because it walks the schema down and back up;
every other suite shares a head-migrated one. Synchronous for the same reason as the
``0003`` test: ``alembic/env.py`` drives the migration with its own ``asyncio.run()``.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import create_async_engine
from testcontainers.postgres import PostgresContainer

from tests.integration.test_parse_and_store import ALEMBIC_INI

_INDEXES = {"ix_parsed_jds_version_title_trgm", "ix_canonical_jds_title_trgm"}


@pytest.fixture
def pg() -> Iterator[tuple[Config, str]]:
    with PostgresContainer("postgres:16-alpine") as container:
        url = container.get_connection_url().replace("psycopg2", "asyncpg")
        cfg = Config(str(ALEMBIC_INI))
        cfg.set_main_option("sqlalchemy.url", url)
        yield cfg, url


async def _state(url: str) -> tuple[set[str], dict[str, bool]]:
    engine = create_async_engine(url)
    async with engine.connect() as conn:
        extensions = set(
            (await conn.execute(sa.text("SELECT extname FROM pg_extension"))).scalars()
        )
        rows = await conn.execute(
            sa.text(
                "SELECT c.relname, i.indisvalid FROM pg_index i "
                "JOIN pg_class c ON c.oid = i.indexrelid "
                "WHERE c.relname = ANY(:names)"
            ),
            {"names": sorted(_INDEXES)},
        )
        indexes = {name: valid for name, valid in rows}
    await engine.dispose()
    return extensions, indexes


async def _break_one_index(url: str) -> None:
    """Simulate a concurrent build that died half-way: the index exists but is
    INVALID. ``IF NOT EXISTS`` alone would skip it and leave search unindexed."""
    engine = create_async_engine(url)
    async with engine.begin() as conn:
        await conn.execute(
            sa.text(
                "UPDATE pg_index SET indisvalid = false WHERE indexrelid = "
                "'ix_canonical_jds_title_trgm'::regclass"
            )
        )
    await engine.dispose()


def test_0007_upgrades_downgrades_and_upgrades_again(pg: tuple[Config, str]) -> None:
    cfg, url = pg
    command.upgrade(cfg, "head")
    extensions, indexes = asyncio.run(_state(url))
    assert {"pg_trgm", "btree_gin"} <= extensions
    assert indexes == dict.fromkeys(_INDEXES, True)

    command.downgrade(cfg, "0006_session_csrf_token")
    extensions, indexes = asyncio.run(_state(url))
    assert not ({"pg_trgm", "btree_gin"} & extensions)
    assert indexes == {}

    command.upgrade(cfg, "head")
    assert asyncio.run(_state(url))[1] == dict.fromkeys(_INDEXES, True)


def test_0007_rebuilds_an_invalid_leftover_index(pg: tuple[Config, str]) -> None:
    cfg, url = pg
    command.upgrade(cfg, "head")
    asyncio.run(_break_one_index(url))
    assert asyncio.run(_state(url))[1]["ix_canonical_jds_title_trgm"] is False

    # Re-run 0007 over the leftover, as an operator would after a failed launch.
    command.stamp(cfg, "0006_session_csrf_token")
    command.upgrade(cfg, "head")
    assert asyncio.run(_state(url))[1] == dict.fromkeys(_INDEXES, True)

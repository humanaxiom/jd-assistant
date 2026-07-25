"""Tamper-evident audit chain (ADR-008, migration 0005) vs a migrated Postgres.

Inserts audit rows through the ORM (the trigger fills the hash chain), verifies the
chain is intact, then proves detection: altering a row's payload and deleting a row both
flip the verifier to ok=False."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from testcontainers.postgres import PostgresContainer

from src.api.services.audit import verify_audit_chain
from src.jd_bank.db.models import AuditLog

ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"


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
        await conn.execute(text("DELETE FROM audit_log"))
        await conn.execute(
            text("UPDATE audit_chain_tail SET tail_hash = '\\x00'::bytea")
        )
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


async def _seed_three(maker: async_sessionmaker[AsyncSession]) -> list[uuid.UUID]:
    ids: list[uuid.UUID] = []
    async with maker() as db:
        for i in range(3):
            row = AuditLog(event_type=f"event.{i}", actor="asalah", payload={"i": i})
            db.add(row)
            await db.flush()
            ids.append(row.id)
        await db.commit()
    return ids


async def test_intact_chain_verifies(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    await _seed_three(session_maker)
    async with session_maker() as db:
        result = await verify_audit_chain(db)
    assert result.ok is True
    assert result.checked == 3 and result.total == 3


async def test_altering_a_row_is_detected(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    ids = await _seed_three(session_maker)
    async with session_maker() as db:
        # Tamper: change a row's payload WITHOUT recomputing its hash (row_hash is only
        # set by the INSERT trigger). The recompute no longer matches -> detected.
        await db.execute(
            text("UPDATE audit_log SET payload = '{\"i\": 99}' WHERE id = :id"),
            {"id": ids[1]},
        )
        await db.commit()
        result = await verify_audit_chain(db)
    assert result.ok is False
    assert "altered" in result.detail


async def test_deleting_a_row_is_detected(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    ids = await _seed_three(session_maker)
    async with session_maker() as db:
        await db.execute(text("DELETE FROM audit_log WHERE id = :id"), {"id": ids[1]})
        await db.commit()
        result = await verify_audit_chain(db)
    assert result.ok is False
    assert "broken" in result.detail

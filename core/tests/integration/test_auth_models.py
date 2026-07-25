"""Auth identity tables (ADR-008) — round-trip against a migrated Postgres.

Exercises migration 0004 (users / user_roles / sessions + the role/userstatus enums)
and the ORM models: a user with multiple roles, the ``role_names`` set the RBAC gate
reads, the ``cas_username`` uniqueness, and a session row.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from testcontainers.postgres import PostgresContainer

from src.api.db.models import Role, Session, User, UserRole, UserStatus

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
        await conn.execute(text("DELETE FROM sessions"))
        await conn.execute(text("DELETE FROM user_roles"))
        await conn.execute(text("DELETE FROM users"))
    maker = async_sessionmaker(engine, expire_on_commit=False)
    yield maker
    await engine.dispose()


async def test_user_with_roles_and_session_round_trips(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    async with session_maker() as session:
        user = User(
            cas_username="asalah",
            display_name="Adam Salah",
            email="asalah@sfu.ca",
            roles=[UserRole(role=Role.REVIEWER), UserRole(role=Role.ADMIN)],
        )
        session.add(user)
        await session.flush()
        session.add(
            Session(
                id="tok-" + uuid.uuid4().hex,
                user_id=user.id,
                expires_at=datetime.now(UTC) + timedelta(hours=8),
            )
        )
        await session.commit()
        user_id = user.id

    async with session_maker() as session:
        loaded = await session.get(User, user_id)
        assert loaded is not None
        assert loaded.status is UserStatus.ACTIVE  # server default
        # The role set the RBAC gate reads — order-independent.
        assert loaded.role_names == frozenset({Role.REVIEWER, Role.ADMIN})
        sessions = (
            await session.scalars(select(Session).where(Session.user_id == user_id))
        ).all()
        assert len(sessions) == 1
        assert sessions[0].revoked_at is None


async def test_cas_username_is_unique(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    async with session_maker() as session:
        session.add(User(cas_username="dupe", display_name="First"))
        await session.commit()
    async with session_maker() as session:
        session.add(User(cas_username="dupe", display_name="Second"))
        with pytest.raises(IntegrityError):
            await session.commit()

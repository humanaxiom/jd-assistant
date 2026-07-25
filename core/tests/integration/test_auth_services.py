"""Auth services (ADR-008) against a migrated Postgres: user provisioning, the session
lifecycle (create/resolve/refresh/revoke), and the dev-anonymous bootstrap."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
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

from src.api.db.models import Role
from src.api.services import session_service, user_service

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
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


async def test_provision_or_get_creates_then_returns_same_user(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    async with session_maker() as db:
        created = await user_service.provision_or_get(
            db, cas_username="asalah", default_role=Role.AUTHOR
        )
        await db.commit()
        first_id, first_login = created.id, created.last_login_at

    async with session_maker() as db:
        again = await user_service.provision_or_get(
            db, cas_username="asalah", default_role=Role.AUTHOR
        )
        await db.commit()
        # Same row, default role granted, last_login advanced (not a second user).
        assert again.id == first_id
        assert again.role_names == frozenset({Role.AUTHOR})
        assert first_login is not None and again.last_login_at is not None
        assert again.last_login_at >= first_login


async def test_session_lifecycle_create_resolve_revoke(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    async with session_maker() as db:
        user = await user_service.provision_or_get(
            db, cas_username="reviewer1", default_role=Role.REVIEWER
        )
        sess = await session_service.create_session(
            db, user_id=user.id, ttl_seconds=8 * 3600
        )
        await db.commit()
        token = sess.id

    async with session_maker() as db:
        assert (await session_service.get_active_session(db, token)) is not None
        await session_service.revoke_session(db, token)
        await db.commit()

    async with session_maker() as db:
        # Revoked -> no longer resolvable.
        assert (await session_service.get_active_session(db, token)) is None


async def test_expired_session_does_not_resolve(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    async with session_maker() as db:
        user = await user_service.provision_or_get(
            db, cas_username="expiry", default_role=Role.AUTHOR
        )
        sess = await session_service.create_session(
            db, user_id=user.id, ttl_seconds=8 * 3600
        )
        sess.expires_at = datetime.now(UTC) - timedelta(seconds=1)  # force-expire
        await db.commit()
        token = sess.id

    async with session_maker() as db:
        assert (await session_service.get_active_session(db, token)) is None


async def test_revoke_user_sessions_kills_all_live(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    async with session_maker() as db:
        user = await user_service.provision_or_get(
            db, cas_username="multi", default_role=Role.AUTHOR
        )
        for _ in range(3):
            await session_service.create_session(
                db, user_id=user.id, ttl_seconds=8 * 3600
            )
        await db.commit()
        uid = user.id

    async with session_maker() as db:
        assert (await session_service.revoke_user_sessions(db, uid)) == 3
        await db.commit()


def test_transient_dev_user_carries_the_configured_role() -> None:
    # The dev/CI synthetic user is NON-persisted (no DB round-trip to render a page);
    # it just carries the configured role for identity + role-checks.
    from src.api.deps import _DEV_ANON_UUID, transient_dev_user
    from src.settings import Settings

    user = transient_dev_user(
        Settings(cas_anonymous_user="dev-anon", cas_dev_default_role="admin")
    )
    assert user.id == _DEV_ANON_UUID
    assert user.role_names == frozenset({Role.ADMIN})

"""User-management admin UI (ADR-008 phase 3) vs the real app + a migrated Postgres.

Dev mode (cas_enabled=False) makes every request the synthetic admin, so the admin-gated
routes are reachable; the test seeds users, lists them, reassigns roles, disables one,
and exercises the self-lockout guard (an admin can't strip its own admin role)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from uuid import UUID

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool
from testcontainers.postgres import PostgresContainer

from src.api.db.models import Role, User, UserRole, UserStatus
from src.api.deps import _DEV_ANON_UUID
from src.api.main import app, get_session
from src.settings import Settings, get_settings

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
def env(
    migrated_pg_url: str,
) -> Iterator[tuple[TestClient, async_sessionmaker[AsyncSession]]]:
    engine = create_async_engine(migrated_pg_url, poolclass=NullPool)
    maker = async_sessionmaker(engine, expire_on_commit=False)

    async def _override_session() -> AsyncIterator[AsyncSession]:
        async with maker() as session:
            yield session

    # Dev mode: every request is the synthetic admin -> the admin router is reachable.
    app.dependency_overrides[get_session] = _override_session
    app.dependency_overrides[get_settings] = lambda: Settings(cas_enabled=False)
    yield TestClient(app), maker
    app.dependency_overrides.clear()


def _seed(url: str) -> dict[str, UUID]:
    async def _go() -> dict[str, UUID]:
        engine = create_async_engine(url, poolclass=NullPool)
        ids: dict[str, UUID] = {}
        async with async_sessionmaker(engine)() as db:
            await db.execute(text("DELETE FROM sessions"))
            await db.execute(text("DELETE FROM user_roles"))
            await db.execute(text("DELETE FROM users"))
            alice = User(
                cas_username="alice",
                display_name="Alice",
                roles=[UserRole(role=Role.AUTHOR)],
            )
            bob = User(
                cas_username="bob",
                display_name="Bob",
                roles=[UserRole(role=Role.REVIEWER)],
            )
            db.add_all([alice, bob])
            await db.flush()
            ids = {"alice": alice.id, "bob": bob.id}
            await db.commit()
        await engine.dispose()
        return ids

    return asyncio.run(_go())


def test_admin_can_list_reassign_roles_and_disable(
    env: tuple[TestClient, async_sessionmaker[AsyncSession]],
    migrated_pg_url: str,
) -> None:
    tc, _ = env
    ids = _seed(migrated_pg_url)

    listing = tc.get("/jd-bank/ui/admin/users")
    assert listing.status_code == 200
    assert "Alice" in listing.text and "bob" in listing.text

    # Promote Alice to reviewer + admin.
    roles = tc.post(
        f"/jd-bank/ui/admin/users/{ids['alice']}/roles",
        data={"roles": ["reviewer", "admin"]},
        follow_redirects=False,
    )
    assert roles.status_code == 303

    # Disable Bob.
    disable = tc.post(
        f"/jd-bank/ui/admin/users/{ids['bob']}/status",
        data={"status": "disabled"},
        follow_redirects=False,
    )
    assert disable.status_code == 303

    async def _check() -> None:
        engine = create_async_engine(migrated_pg_url, poolclass=NullPool)
        async with async_sessionmaker(engine)() as db:
            alice = await db.get(User, ids["alice"])
            bob = await db.get(User, ids["bob"])
            assert alice is not None and bob is not None
            assert alice.role_names == frozenset({Role.REVIEWER, Role.ADMIN})
            assert bob.status is UserStatus.DISABLED
        await engine.dispose()

    asyncio.run(_check())


def test_admin_cannot_remove_own_admin_role(
    env: tuple[TestClient, async_sessionmaker[AsyncSession]],
    migrated_pg_url: str,
) -> None:
    tc, _ = env
    _seed(migrated_pg_url)
    # The dev actor is the synthetic admin (id = the nil UUID). Trying to set its own
    # roles to just `author` (dropping admin) must be refused, not applied.
    resp = tc.post(
        f"/jd-bank/ui/admin/users/{_DEV_ANON_UUID}/roles",
        data={"roles": ["author"]},
        follow_redirects=False,
    )
    assert resp.status_code == 200
    assert "cannot remove your own admin role" in resp.text

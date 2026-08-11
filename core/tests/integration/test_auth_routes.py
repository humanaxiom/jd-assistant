"""CAS auth routes (ADR-008), dev-fake flow, against the real app + a migrated Postgres.

Overrides get_session (testcontainer) and get_settings (cas_enabled + a dev-fake user),
then drives the browser dance: /cas/login -> /cas/validate mints a session cookie and
provisions the user; the cookie resolves; /logout revokes it. No live CAS is touched
(the dev-fake sentinel ticket short-circuits validation)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool
from testcontainers.postgres import PostgresContainer

from src.api.main import app, get_session
from src.api.services import session_service
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
def client(
    migrated_pg_url: str,
) -> Iterator[tuple[TestClient, async_sessionmaker[AsyncSession]]]:
    # NullPool: the TestClient drives the app through an anyio portal whose loop can
    # differ between requests, and a pooled asyncpg connection can't cross loops. A
    # fresh connection per request sidesteps that (test-only; prod uses a real pool).
    engine = create_async_engine(migrated_pg_url, poolclass=NullPool)
    maker = async_sessionmaker(engine, expire_on_commit=False)

    async def _override_session() -> AsyncIterator[AsyncSession]:
        async with maker() as session:
            yield session

    fake_settings = Settings(
        cas_enabled=True,
        cas_dev_fake_user="asalah",
        default_new_user_role="reviewer",
    )
    app.dependency_overrides[get_session] = _override_session
    app.dependency_overrides[get_settings] = lambda: fake_settings
    # `resolve_user` and the CSRF check each open their OWN short-lived session off
    # `app.state` (pure reads that must work with no request-scoped session), so both
    # doors have to lead to this database — as in test_csrf_session_token.py.
    previous = getattr(app.state, "sessionmaker", None)
    app.state.sessionmaker = maker
    yield TestClient(app), maker
    app.dependency_overrides.clear()
    app.state.sessionmaker = previous


def test_login_page_renders(
    client: tuple[TestClient, async_sessionmaker[AsyncSession]],
) -> None:
    tc, _ = client
    resp = tc.get("/jd-bank/ui/login")
    assert resp.status_code == 200
    assert "Sign in with SFU CAS" in resp.text


def test_dev_fake_login_mints_a_session_and_provisions_the_user(
    client: tuple[TestClient, async_sessionmaker[AsyncSession]],
) -> None:
    tc, _ = client
    # /cas/login (dev-fake) -> /cas/validate with the sentinel ticket.
    login = tc.get(
        "/jd-bank/ui/cas/login",
        params={"next": "/jd-bank/ui/queue"},
        follow_redirects=False,
    )
    assert login.status_code == 302
    assert "/jd-bank/ui/cas/validate" in login.headers["location"]
    assert "DEV-FAKE-CAS-TICKET" in login.headers["location"]

    validate = tc.get(login.headers["location"], follow_redirects=False)
    assert validate.status_code == 302
    assert validate.headers["location"] == "/jd-bank/ui/queue"
    # A session cookie was set.
    assert "jdbank_session" in validate.cookies


def test_logout_revokes_the_session(
    client: tuple[TestClient, async_sessionmaker[AsyncSession]],
    migrated_pg_url: str,
) -> None:
    # SYNC test: TestClient must be driven from a sync context. DB checks run via
    # asyncio.run (a fresh loop each time) so no asyncpg connection crosses loops.
    tc, _ = client
    tc.get(
        "/jd-bank/ui/cas/validate",
        params={"ticket": "DEV-FAKE-CAS-TICKET", "next": "/jd-bank/ui/queue"},
        follow_redirects=False,
    )
    token = tc.cookies.get("jdbank_session")
    assert token is not None  # login minted an active session (see the test above)

    # An AUTHENTICATED logout revokes a session row, so it is a cookie-authenticated
    # state change and carries the session's CSRF token like every other form (P0.1b-i).
    # The browser reads that token off a rendered page; here, off the session row it
    # was minted onto. Refusal is pinned in test_csrf_session_token.py.
    out = tc.post(
        "/jd-bank/ui/logout",
        data={"csrf_token": _csrf_token_of(migrated_pg_url, token)},
        follow_redirects=False,
    )
    assert out.status_code == 303
    assert out.headers["location"] == "/jd-bank/ui/login"

    # All TestClient calls done; now verify the session row is revoked, in a fresh loop.
    async def _is_active() -> bool:
        engine = create_async_engine(migrated_pg_url)
        try:
            async with async_sessionmaker(engine)() as db:
                return (await session_service.get_active_session(db, token)) is not None
        finally:
            await engine.dispose()

    assert asyncio.run(_is_active()) is False


def _csrf_token_of(pg_url: str, session_id: str) -> str:
    """The session row's own CSRF token, read in a fresh event loop (every TestClient
    call must be finished first, so no asyncpg connection crosses loops)."""

    async def _read() -> str:
        engine = create_async_engine(pg_url)
        try:
            async with async_sessionmaker(engine)() as db:
                row = await session_service.get_active_session(db, session_id)
                assert row is not None
                return str(row.csrf_token)
        finally:
            await engine.dispose()

    return asyncio.run(_read())

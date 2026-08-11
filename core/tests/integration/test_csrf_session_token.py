"""The CSRF token is a real column on a real session row (P0.1b-i), end to end.

``tests/unit/test_csrf_protection.py`` pins the *policy* — every cookie-authenticated
state change needs the session's token — with the session row faked at the service
boundary, so it can enumerate every route without a database. This file pins the half a
fake cannot: that a session row **has** a CSRF token, that Postgres and the migration
know about it, that it is minted per session rather than per process, and that the whole
browser loop closes — log in, read the token out of the rendered page, and have the
server accept it.

Both halves are needed. A unit suite alone would stay green against an implementation
that stores the token nowhere; a migration test alone would stay green against one that
never checks it.

Why the token lives on the session row at all: there is no signing key anywhere in this
service (sessions are opaque ``secrets.token_urlsafe(32)`` ids in a Postgres row, not
signed cookies), so a *signed* double-submit cookie is not available without inventing
an app secret — which P0.2 deliberately declined to do. A random per-session token in
the row it already reads on every request costs one column and no new concept.

The token is deliberately **not** the session id: the id is the ``httponly`` cookie
value, and the token is written into HTML.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from testcontainers.postgres import PostgresContainer

from src.api.db.models import Role
from src.api.main import app, get_session
from src.api.services import session_service, user_service
from src.settings import Settings, get_settings

ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"

#: The hidden form field the token rides in (mirrors the unit CSRF suite).
CSRF_FIELD = "csrf_token"

_HIDDEN_FIELD = re.compile(rf'name="{CSRF_FIELD}"\s+value="([^"]*)"')


@pytest.fixture(scope="module")
def migrated_pg_url() -> Iterator[str]:
    with PostgresContainer("postgres:16-alpine") as pg:
        url = pg.get_connection_url().replace("psycopg2", "asyncpg")
        cfg = Config(str(ALEMBIC_INI))
        cfg.set_main_option("sqlalchemy.url", url)
        command.upgrade(cfg, "head")
        yield url


@pytest.fixture
def maker(migrated_pg_url: str) -> Iterator[async_sessionmaker[AsyncSession]]:
    # NullPool for the same reason as tests/integration/test_auth_routes.py: the
    # TestClient drives the app through an anyio portal whose loop can differ between
    # requests, and a pooled asyncpg connection cannot cross loops.
    engine = create_async_engine(migrated_pg_url, poolclass=NullPool)
    yield async_sessionmaker(engine, expire_on_commit=False)


@pytest.fixture
def client(maker: async_sessionmaker[AsyncSession]) -> Iterator[TestClient]:
    """The real browser loop: CAS on, the dev-fake ticket instead of a round trip to
    ``cas.sfu.ca``, and a migrated Postgres behind it.

    ``app.state.sessionmaker`` is set as well as ``get_session`` overridden, because
    ``resolve_user`` opens its OWN short-lived session off ``app.state`` (a pure read
    that must work with no request-scoped session), while the route handlers take the
    dependency. Both doors have to lead to the same database.
    """

    async def _override_session() -> AsyncIterator[AsyncSession]:
        async with maker() as session:
            yield session

    settings = Settings(
        cas_enabled=True,
        cas_dev_fake_user="asalah",
        default_new_user_role="reviewer",
    )
    app.dependency_overrides[get_session] = _override_session
    app.dependency_overrides[get_settings] = lambda: settings
    previous = getattr(app.state, "sessionmaker", None)
    app.state.sessionmaker = maker
    yield TestClient(app, follow_redirects=False)
    app.dependency_overrides.clear()
    app.state.sessionmaker = previous


def _log_in(tc: TestClient) -> str:
    """Complete the dev-fake CAS dance and return the session cookie value."""
    tc.get(
        "/jd-bank/ui/cas/validate",
        params={"ticket": "DEV-FAKE-CAS-TICKET", "next": "/jd-bank/ui/queue"},
    )
    token = tc.cookies.get("jdbank_session")
    assert token is not None, "the dev-fake login did not mint a session cookie"
    return token


def _csrf_from_page(tc: TestClient) -> str:
    """The token as a browser would obtain it: off a rendered page."""
    page = tc.get("/jd-bank/ui/queue")
    assert page.status_code == 200, f"the queue did not render: {page.status_code}"
    match = _HIDDEN_FIELD.search(page.text)
    assert match is not None, (
        f"no hidden {CSRF_FIELD!r} field on a rendered page — every form on it would "
        "be refused"
    )
    return match.group(1)


# ── The column ───────────────────────────────────────────────────────────────────────


def test_a_new_session_row_carries_its_own_csrf_token(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    """Minted with the session, stored beside it, and readable back through the same
    query every request already runs. Two sessions must not share a token: a
    per-process (or per-deployment) constant would be a token any attacker could obtain
    by signing in once."""

    async def _mint() -> tuple[str, str, str, str]:
        async with maker() as db:
            user = await user_service.provision_or_get(
                db, cas_username="csrf-user", default_role=Role.REVIEWER
            )
            first = await session_service.create_session(
                db, user_id=user.id, ttl_seconds=3600
            )
            second = await session_service.create_session(
                db, user_id=user.id, ttl_seconds=3600
            )
            await db.commit()
            reread = await session_service.get_active_session(db, first.id)
            assert reread is not None
            return first.id, first.csrf_token, second.csrf_token, reread.csrf_token

    session_id, first_token, second_token, reread_token = asyncio.run(_mint())

    assert first_token, "the session row was created with no CSRF token"
    assert first_token != session_id, (
        "the CSRF token is the session id. The id is the httponly cookie value; the "
        "token gets written into HTML, sent in Referer headers and logged with form "
        "bodies — they cannot be the same secret."
    )
    assert first_token != second_token, "two sessions were given the same CSRF token"
    assert (
        reread_token == first_token
    ), "the token did not survive a round trip to Postgres"


# ── The browser loop ─────────────────────────────────────────────────────────────────


def test_a_form_submitted_with_the_token_from_the_page_is_accepted(
    client: TestClient, migrated_pg_url: str
) -> None:
    """Log in, read the token off the page exactly as the browser does, submit it, and
    the state change happens. The control is not a brick."""
    token = _log_in(client)
    csrf = _csrf_from_page(client)

    resp = client.post("/jd-bank/ui/logout", data={CSRF_FIELD: csrf})

    assert resp.status_code == 303
    assert _session_is_active(migrated_pg_url, token) is False


def test_the_same_form_without_the_token_is_refused_and_changes_nothing(
    client: TestClient, migrated_pg_url: str
) -> None:
    """The cross-site version of the request above: same cookie, same fields, no token.
    Refused — and, the part that matters, the session is still live afterwards."""
    token = _log_in(client)
    _csrf_from_page(client)

    resp = client.post("/jd-bank/ui/logout")

    assert resp.status_code == 403
    assert _session_is_active(migrated_pg_url, token) is True, (
        "the request was refused but the session was revoked anyway — the check ran "
        "after the effect"
    )


def test_a_token_belonging_to_another_session_is_refused(
    client: TestClient, maker: async_sessionmaker[AsyncSession], migrated_pg_url: str
) -> None:
    """A valid token, issued by this very service, for a different session. An attacker
    can always get one of these — by signing in themselves."""
    token = _log_in(client)

    async def _other_token() -> str:
        async with maker() as db:
            other = await user_service.provision_or_get(
                db, cas_username="someone-else", default_role=Role.REVIEWER
            )
            row = await session_service.create_session(
                db, user_id=other.id, ttl_seconds=3600
            )
            await db.commit()
            return str(row.csrf_token)

    resp = client.post(
        "/jd-bank/ui/logout", data={CSRF_FIELD: asyncio.run(_other_token())}
    )

    assert resp.status_code == 403
    assert _session_is_active(migrated_pg_url, token) is True


def _session_is_active(pg_url: str, session_id: str) -> bool:
    """Read the session's live-ness in a fresh event loop — every TestClient call must
    be finished first, so no asyncpg connection crosses loops."""

    async def _check() -> bool:
        engine = create_async_engine(pg_url)
        try:
            async with async_sessionmaker(engine)() as db:
                return (
                    await session_service.get_active_session(db, session_id)
                ) is not None
        finally:
            await engine.dispose()

    return asyncio.run(_check())

"""Shared scaffolding for the authorization tests (P0.1a).

**The one thing every auth test must get right is ``cas_enabled=True``.** With the
shipped default (``cas_enabled=False``) :func:`src.api.deps.resolve_user` short-circuits
*before it reads any cookie* and hands back a transient synthetic user holding
``cas_dev_default_role`` — which defaults to **admin**. Every request then passes every
gate, and an authorization test written against that default is a **false green**: it
would pass just as happily against an app with no gates at all.

So no auth test builds its own ``Settings``: it calls :func:`cas_on`, and
``test_authorization_matrix.py`` carries a guard test proving that helper really does
flip the switch.

Not a test module (no ``test_`` prefix) — a helper, like ``cluster_fakes.py``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace, TracebackType

import pytest
from fastapi import Request

from src.api.db.models import Role, User, UserRole, UserStatus
from src.api.deps import current_user
from src.api.main import app
from src.api.services import session_service, user_service
from src.settings import Settings, get_settings


def cas_on() -> Settings:
    """Force **real** authentication for the duration of a test: install a
    ``get_settings`` override with ``cas_enabled=True`` (and no dev-fake CAS user) on
    the app, and return it. The caller clears ``app.dependency_overrides`` in teardown.

    With this in place an unauthenticated request carries no session cookie, so
    ``resolve_user`` raises :class:`~src.api.deps.NotAuthenticated` (401) without any DB
    access — which is what lets these run as unit tests.
    """
    settings = Settings(cas_enabled=True, cas_dev_fake_user="")
    app.dependency_overrides[get_settings] = lambda: settings
    return settings


def user_holding(*roles: Role, username: str = "reviewer-1") -> User:
    """A non-persisted :class:`User` holding ``roles`` — the identity a signed-in
    request resolves to. ``cas_username`` is what a route must attribute an action to
    (NN #1/#6), so it is deliberately unlike anything a test sends in a request body.

    ``id`` and ``status`` are set explicitly because their model definitions carry
    *column* defaults, which SQLAlchemy applies at INSERT — a transient instance has
    ``id=None`` and ``status=None``, and ``resolve_user`` refuses a user whose status is
    not ``ACTIVE``. A fake that is silently unusable by the real resolution path is the
    kind of scaffolding bug that makes a whole auth suite vacuous.
    """
    return User(
        id=uuid.uuid4(),
        cas_username=username,
        display_name=f"{username} ({'+'.join(r.value for r in roles) or 'no roles'})",
        status=UserStatus.ACTIVE,
        roles=[UserRole(role=r) for r in roles],
    )


def signed_in_as(user: User) -> User:
    """Resolve every request to ``user`` — overrides :func:`src.api.deps.current_user`.

    Overriding the *identity* dependency (not the gate) keeps the real
    ``require_roles`` / ``require_ui_roles`` logic in the request path, so a role check
    is still genuinely exercised — only the cookie -> session -> user DB lookup is
    replaced. The caller clears ``app.dependency_overrides`` in teardown.
    """
    app.dependency_overrides[current_user] = lambda: user
    return user


def signed_in_ui_as(monkeypatch: pytest.MonkeyPatch, user: User) -> User:
    """Resolve every **UI** request to ``user``.

    :func:`signed_in_as` cannot reach the UI gate: ``require_ui_user`` calls
    ``resolve_user`` *directly* rather than depending on ``current_user``, so a
    dependency override never applies to it. Patching the name the auth module actually
    calls is the only way to hand a UI route an identity — and it leaves the real
    ``require_ui_roles`` role check in the path, which is the thing under test.
    """

    async def _resolve(request: Request, settings: Settings) -> User:
        request.state.user = user  # templates read the nav pill off request.state
        return user

    monkeypatch.setattr("src.api.routes.auth.resolve_user", _resolve)
    return user


class _FakeDbSession:
    """The short-lived ``AsyncSession`` ``resolve_user`` opens for itself. It only ever
    reads, and the only method it calls on the session object is ``expunge``."""

    def expunge(self, obj: object) -> None:
        return None


class _FakeSessionmaker:
    """``app.state.sessionmaker`` stand-in: ``async with maker() as db``."""

    def __call__(self) -> _FakeSessionmaker:
        return self

    async def __aenter__(self) -> _FakeDbSession:
        return _FakeDbSession()

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool:
        return False


def signed_in_with_session(
    monkeypatch: pytest.MonkeyPatch,
    user: User,
    *,
    session_id: str = "live-session-id",
    csrf_token: str = "live-session-csrf-token",
) -> SimpleNamespace:
    """A request authenticated the way a **real browser** is: by a session cookie whose
    value resolves, through the real code path, to a live server-side session row.

    :func:`signed_in_ui_as` replaces ``resolve_user`` wholesale, which is right when the
    thing under test is a role check — but it is useless for CSRF, because it also
    replaces the step that *finds the session*, and the session row is where the CSRF
    token lives. So this helper fakes one layer lower, at the service boundary:
    ``session_service.get_active_session`` and ``user_service.get_user_by_id`` are
    patched on the service modules (so every importer sees them), and
    ``app.state.sessionmaker`` gets a stand-in. Everything above that — reading the
    cookie by its configured name, matching it to a session, stashing the user on
    ``request.state`` — is the real code.

    Deliberately implementation-agnostic: a CSRF check that reads the token off
    ``request.state`` (stashed by ``resolve_user``) and one that looks the session up
    itself both go through ``get_active_session``, so both see this row.

    The returned row is a duck type, not a ``Session`` ORM instance, so these tests fail
    on the *behaviour* that is missing rather than on a ``TypeError`` from a column that
    does not exist yet. That the real column exists is pinned separately, against a
    migrated database, in ``tests/integration/test_csrf_session_token.py``.

    Pair it with a client that actually sends the cookie::

        client.cookies.set(settings.session_cookie_name, session_id)
    """
    row = SimpleNamespace(
        id=session_id,
        user_id=user.id,
        csrf_token=csrf_token,
        expires_at=datetime.now(UTC) + timedelta(hours=8),
        revoked_at=None,
        user_agent=None,
        ip_addr=None,
    )

    async def _get_active_session(db: object, sid: str) -> SimpleNamespace | None:
        return row if sid == session_id else None

    async def _get_user_by_id(db: object, user_id: uuid.UUID) -> User | None:
        return user if user_id == user.id else None

    monkeypatch.setattr(session_service, "get_active_session", _get_active_session)
    monkeypatch.setattr(user_service, "get_user_by_id", _get_user_by_id)
    monkeypatch.setattr(app.state, "sessionmaker", _FakeSessionmaker(), raising=False)
    return row

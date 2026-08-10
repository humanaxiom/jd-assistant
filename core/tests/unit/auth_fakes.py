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

import pytest
from fastapi import Request

from src.api.db.models import Role, User, UserRole
from src.api.deps import current_user
from src.api.main import app
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
    (NN #1/#6), so it is deliberately unlike anything a test sends in a request body."""
    return User(
        cas_username=username,
        display_name=f"{username} ({'+'.join(r.value for r in roles) or 'no roles'})",
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

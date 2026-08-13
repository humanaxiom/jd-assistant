"""FastAPI auth dependencies (ADR-008).

* :func:`current_user` — resolves the session cookie -> session row -> user, or in
  CAS-disabled dev mode returns a synthetic anonymous user with the configured role.
  Raises 401 when a real (CAS-enabled) request is unauthenticated.
* :data:`CurrentUser` — the ``Annotated[User, Depends(current_user)]`` shorthand.
* :func:`require_roles` — RBAC factory: ``Depends(require_roles(Role.REVIEWER))``.

UI routes that should *redirect* an unauthenticated visitor to the login page (rather
than return a 401) use the ``require_ui_user`` dependency in :mod:`src.api.routes.auth`,
which wraps this.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status

from src.api.db.models import Role, User, UserRole, UserStatus
from src.api.services import session_service, user_service
from src.settings import Settings, get_settings

#: Stable identity for the CAS-disabled dev/CI synthetic user, so its actor id is
#: consistent across restarts (and can be persisted on demand when a write needs an FK).
_DEV_ANON_UUID = UUID(int=0)


class NotAuthenticated(HTTPException):
    """401 — no valid session (a real, CAS-enabled request without a live session).
    JSON API routes surface this directly; UI routes turn it into a login redirect
    (see ``require_ui_user`` in :mod:`src.api.routes.auth`)."""

    def __init__(self, detail: str = "not authenticated") -> None:
        super().__init__(status_code=status.HTTP_401_UNAUTHORIZED, detail=detail)


def transient_dev_user(settings: Settings) -> User:
    """The synthetic actor for dev/CI (``cas_enabled=False``). A NON-persisted ``User``
    carrying the configured role — enough to identify + role-check + display without a
    DB round-trip (so a page renders with no session). A write that needs a real actor
    FK persists it on demand (phase 2)."""
    return User(
        id=_DEV_ANON_UUID,
        cas_username=settings.cas_anonymous_user,
        display_name=f"{settings.cas_anonymous_user} ({settings.cas_dev_default_role})",
        roles=[UserRole(role=Role(settings.cas_dev_default_role))],
    )


async def resolve_user(request: Request, settings: Settings) -> User:
    """Resolve the request's identity, DB-optional. Dev mode (``cas_enabled=False``)
    returns the transient synthetic user with no DB access; real mode reads the session
    cookie -> session row -> user in its OWN short-lived DB session (a pure read),
    raising :class:`NotAuthenticated` if there is no live session. Stashes the user on
    ``request.state.user`` so templates (the nav pill) can read it — and, beside it, the
    session's CSRF token, which is what the ``_csrf.html`` macro renders into every form
    (P0.1b-i).

    **The CSRF *check* does not read that stashed value** and must never start to: it
    resolves the session itself (:func:`src.api.csrf.expected_csrf_token`), because a
    guard that trusts ``request.state`` reads an empty state as "no session" and turns
    a skip into a bypass whenever it happens to run first. This stash is for RENDERING
    only, which is a different direction of trust.
    """
    if not settings.cas_enabled:
        dev = transient_dev_user(settings)
        request.state.user = dev
        # No session, therefore no token. The macro must render an empty value rather
        # than raise — the CAS-off posture is the one `make gates` runs in.
        request.state.csrf_token = ""
        return dev

    token = request.cookies.get(settings.session_cookie_name)
    if not token:
        raise NotAuthenticated("no session cookie")
    async with request.app.state.sessionmaker() as db:
        session = await session_service.get_active_session(db, token)
        if session is None:
            raise NotAuthenticated("session not found or expired")
        user = await user_service.get_user_by_id(db, session.user_id)
        if user is None or user.status is not UserStatus.ACTIVE:
            raise NotAuthenticated("user inactive or deleted")
        _ = user.role_names  # force the selectin role load before the session closes
        # Read before the row detaches; the templates need it on every rendered page.
        csrf_token = session.csrf_token
        db.expunge(user)
    request.state.user = user
    request.state.csrf_token = csrf_token
    return user


async def current_user(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
) -> User:
    """FastAPI dependency form of :func:`resolve_user` — the actor for a request."""
    return await resolve_user(request, settings)


CurrentUser = Annotated[User, Depends(current_user)]


#: The roles the review surfaces are gated to. Defined once so a *link* to a review page
#: and the *gate* on that page cannot drift apart — offering a link that answers 403 is
#: the P0.0 defect, and it came from a template deciding this for itself.
REVIEW_ROLES: frozenset[Role] = frozenset({Role.REVIEWER, Role.ADMIN})


def may_review(request: Request) -> bool:
    """May the current reader follow a link into the review queue?

    **An affordance question, never an authorization one** — the gate on the review
    routes is what refuses a request (``main.py`` + ``test_authorization_matrix.py``).
    This only decides whether to show a door that is locked for them.

    Reads the user :func:`resolve_user` stashed on ``request.state``; a request that
    resolved no identity simply gets ``False``.
    """
    user = getattr(request.state, "user", None)
    return bool(user is not None and (REVIEW_ROLES & user.role_names))


def require_roles(*roles: Role) -> Callable[..., Awaitable[User]]:
    """Dependency factory: pass the user through iff they hold any of ``roles``, else
    403. Usage: ``dependencies=[Depends(require_roles(Role.ADMIN))]`` or as a value
    dependency to receive the ``User``."""
    allowed = frozenset(roles)

    async def _dep(user: CurrentUser) -> User:
        if allowed and not (allowed & user.role_names):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"requires one of: {sorted(r.value for r in allowed)}",
            )
        return user

    return _dep

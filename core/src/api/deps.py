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
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.db.models import Role, User, UserRole, UserStatus
from src.api.main import get_session
from src.api.services import session_service, user_service
from src.settings import Settings, get_settings

#: Stable identity for the CAS-disabled dev/CI synthetic user, so its FKs (actor rows)
#: are consistent across process restarts.
_DEV_ANON_UUID = UUID(int=0)


class NotAuthenticated(HTTPException):
    """401 — no valid session (a real, CAS-enabled request without a live session).
    JSON API routes surface this directly; UI routes turn it into a login redirect
    (see ``require_ui_user`` in :mod:`src.api.routes.auth`)."""

    def __init__(self, detail: str = "not authenticated") -> None:
        super().__init__(status_code=status.HTTP_401_UNAUTHORIZED, detail=detail)


async def resolve_user(request: Request, db: AsyncSession, settings: Settings) -> User:
    """The identity-resolution core, shared by :func:`current_user` (401 on failure)
    and the UI redirect gate. Raises :class:`NotAuthenticated` if a CAS-enabled request
    has no live session; in dev mode (``cas_enabled=False``) returns the configured
    synthetic anonymous user."""
    if not settings.cas_enabled:
        return await _ensure_dev_anonymous_user(
            db, settings.cas_anonymous_user, settings.cas_dev_default_role
        )

    token = request.cookies.get(settings.session_cookie_name)
    if not token:
        raise NotAuthenticated("no session cookie")
    session = await session_service.get_active_session(db, token)
    if session is None:
        raise NotAuthenticated("session not found or expired")
    request.state.session = session

    user = await user_service.get_user_by_id(db, session.user_id)
    if user is None or user.status is not UserStatus.ACTIVE:
        raise NotAuthenticated("user inactive or deleted")
    return user


async def current_user(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> User:
    """FastAPI dependency form of :func:`resolve_user` — the actor for a request."""
    return await resolve_user(request, db, settings)


CurrentUser = Annotated[User, Depends(current_user)]


async def _ensure_dev_anonymous_user(
    db: AsyncSession, username: str, role_name: str
) -> User:
    """Materialise the dev-mode synthetic user as a real ``users`` row (so actor FKs
    hold), carrying the configured role. Idempotent + self-committing — it is bootstrap
    state, independent of whatever the route then does."""
    role = Role(role_name)
    user = await db.get(User, _DEV_ANON_UUID)
    if user is None:
        user = User(
            id=_DEV_ANON_UUID,
            cas_username=username,
            display_name=f"anonymous ({role_name})",
            roles=[UserRole(role=role)],
        )
        db.add(user)
        try:
            async with db.begin_nested():
                await db.flush()
        except IntegrityError:  # lost a concurrent bootstrap race
            user = await db.get(User, _DEV_ANON_UUID)
            assert user is not None
    if role not in user.role_names:  # config may have changed the dev role
        user.roles.append(UserRole(role=role))
    await db.commit()
    return user


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

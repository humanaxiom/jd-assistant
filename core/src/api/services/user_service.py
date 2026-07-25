"""User provisioning + lookups (ADR-008) — SQLAlchemy ORM port of the HRIS service.

CAS gives us a username; on first successful login for an unknown username we create a
``users`` row with the configured default role (an admin elevates from there). The
provisioning is race-safe: a lost concurrent-first-login race falls back to the row the
winner created. Admin CRUD (list/set-roles/status) lands with the admin UI (phase 3).
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.db.models import Role, User, UserRole, UserStatus


async def get_user_by_cas_username(db: AsyncSession, cas_username: str) -> User | None:
    user: User | None = await db.scalar(
        select(User).where(User.cas_username == cas_username)
    )
    return user


async def get_user_by_id(db: AsyncSession, user_id: UUID) -> User | None:
    return await db.get(User, user_id)


async def list_users(db: AsyncSession, *, limit: int = 200) -> list[User]:
    """All users, newest first (the admin table). Roles are eager-loaded (selectin)."""
    result = await db.scalars(
        select(User).order_by(User.created_at.desc()).limit(limit)
    )
    return list(result.all())


async def set_roles(db: AsyncSession, user_id: UUID, roles: set[Role]) -> User | None:
    """Replace a user's role grants with exactly ``roles`` (admin action). Returns the
    updated user, or None if no such user."""
    user = await db.get(User, user_id)
    if user is None:
        return None
    user.roles = [UserRole(role=role) for role in roles]  # delete-orphan replaces
    await db.flush()
    return user


async def set_status(
    db: AsyncSession, user_id: UUID, status: UserStatus
) -> User | None:
    """Set a user's status (admin action). Returns the updated user, or None."""
    user = await db.get(User, user_id)
    if user is None:
        return None
    user.status = status
    await db.flush()
    return user


async def ensure_role(db: AsyncSession, user: User, role: Role) -> None:
    """Grant ``role`` to ``user`` if not already held (first-admin bootstrap)."""
    if role not in user.role_names:
        user.roles.append(UserRole(role=role))
        await db.flush()


async def provision_or_get(
    db: AsyncSession,
    *,
    cas_username: str,
    display_name: str | None = None,
    email: str | None = None,
    default_role: Role,
) -> User:
    """Return the user for ``cas_username``, creating them (with ``default_role``) on
    first sight and stamping ``last_login_at`` on every login. Race-safe: a lost
    concurrent-first-login race returns the row the winning transaction created."""
    user = await get_user_by_cas_username(db, cas_username)
    if user is not None:
        user.last_login_at = datetime.now(UTC)
        await db.flush()
        return user

    user = User(
        cas_username=cas_username,
        display_name=display_name or cas_username,
        email=email,
        last_login_at=datetime.now(UTC),
        roles=[UserRole(role=default_role)],
    )
    db.add(user)
    try:
        # SAVEPOINT so a unique-violation from a concurrent first-login rolls back
        # only this insert, not the caller's whole tx (the repo's idempotency shape).
        async with db.begin_nested():
            await db.flush()
    except IntegrityError:
        existing = await get_user_by_cas_username(db, cas_username)
        if existing is None:  # a real violation, not the race we expected
            raise
        return existing
    return user

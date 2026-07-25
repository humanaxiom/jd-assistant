"""Server-side sessions (ADR-008) — SQLAlchemy ORM port of the HRIS service.

A session id is an opaque ~256-bit URL-safe token (the cookie value); the row holds
expiry, revocation, and the originating UA/IP. Sliding refresh extends a session that
is within ``idle_refresh_seconds`` of expiry. Revoke-on-disable walks a user's live
sessions. All writes flush into the caller's ``AsyncSession``; the caller commits.
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID

from sqlalchemy import CursorResult, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.db.models import Session


async def create_session(
    db: AsyncSession,
    *,
    user_id: UUID,
    ttl_seconds: int,
    user_agent: str | None = None,
    ip: str | None = None,
) -> Session:
    """Mint a new session for ``user_id`` (opaque token, ``ttl_seconds`` lifetime)."""
    row = Session(
        id=secrets.token_urlsafe(32),
        user_id=user_id,
        expires_at=datetime.now(UTC) + timedelta(seconds=ttl_seconds),
        user_agent=user_agent,
        ip_addr=ip,
    )
    db.add(row)
    await db.flush()
    return row


async def get_active_session(db: AsyncSession, session_id: str) -> Session | None:
    """The session for ``session_id`` iff it is neither revoked nor expired."""
    session: Session | None = await db.scalar(
        select(Session).where(
            Session.id == session_id,
            Session.revoked_at.is_(None),
            Session.expires_at > datetime.now(UTC),
        )
    )
    return session


async def refresh_if_needed(
    db: AsyncSession,
    session: Session,
    *,
    ttl_seconds: int,
    idle_refresh_seconds: int,
) -> Session:
    """Sliding window: if ``session`` is within ``idle_refresh_seconds`` of expiry,
    bump it by ``ttl_seconds``. Returns the (possibly refreshed) session."""
    now = datetime.now(UTC)
    if (session.expires_at - now).total_seconds() > idle_refresh_seconds:
        return session
    session.expires_at = now + timedelta(seconds=ttl_seconds)
    await db.flush()
    return session


async def revoke_session(db: AsyncSession, session_id: str) -> None:
    """Revoke one session (logout). No-op if already revoked/absent."""
    await db.execute(
        update(Session)
        .where(Session.id == session_id, Session.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )


async def revoke_user_sessions(db: AsyncSession, user_id: UUID) -> int:
    """Revoke every live session for a user (called when an admin disables them).
    Returns the number revoked."""
    result = await db.execute(
        update(Session)
        .where(Session.user_id == user_id, Session.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )
    return cast("CursorResult[Any]", result).rowcount or 0

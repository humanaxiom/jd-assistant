"""Auth / identity ORM models — the RBAC foundation (ADR-008).

Bind to the *shared* harness ``Base`` (``src.models.db.Base``) so a single
``MetaData`` covers the harness ledger, the JD Bank domain, and auth. Conventions
mirror ``jd_bank.db.models``: UUID PKs, tz-aware timestamps with server defaults,
``StrEnum`` columns for closed value sets. Identity comes from CAS — no password hash.

Roles are author / reviewer / admin, held many-to-many (a user can be both reviewer
and admin), checked by :func:`src.api.deps.require_roles`. A session is an opaque
server-side token row (revocable per-session + auditable), not a signed cookie.
"""

from __future__ import annotations

import enum
import secrets
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.db import Base


def new_csrf_token() -> str:
    """A fresh per-session CSRF secret (P0.1b-i) — the column default for
    :attr:`Session.csrf_token`. Same CSPRNG and width as the session id, and
    **independently drawn**: deriving one from the other would put the ``httponly``
    cookie value into every rendered page."""
    return secrets.token_urlsafe(32)


# ── Closed value sets (Postgres ENUM types; DB value = enum member name) ─────


class Role(enum.StrEnum):
    """A JD Bank authorization role. ``author`` uses the Builder and submits drafts;
    ``reviewer`` approves/rejects/edits/overrides in the review queue (NN #1 human
    approval); ``admin`` manages users."""

    AUTHOR = "author"
    REVIEWER = "reviewer"
    ADMIN = "admin"


class UserStatus(enum.StrEnum):
    """A user account's state. ``disabled`` blocks login and revokes live sessions."""

    ACTIVE = "active"
    DISABLED = "disabled"


class User(Base):
    """A person, keyed by their SFU CAS username. Provisioned on first CAS login."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    cas_username: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(256))
    email: Mapped[str | None] = mapped_column(String(256), nullable=True)
    status: Mapped[UserStatus] = mapped_column(
        Enum(UserStatus), default=UserStatus.ACTIVE
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    roles: Mapped[list[UserRole]] = relationship(
        back_populates="user", cascade="all, delete-orphan", lazy="selectin"
    )
    sessions: Mapped[list[Session]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )

    @property
    def role_names(self) -> frozenset[Role]:
        """The roles this user holds, as a set (what ``require_roles`` checks)."""
        return frozenset(link.role for link in self.roles)


class UserRole(Base):
    """A (user, role) grant. Composite-PK join — a user holds 0..n roles."""

    __tablename__ = "user_roles"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[Role] = mapped_column(Enum(Role), primary_key=True)

    user: Mapped[User] = relationship(back_populates="roles")


class Session(Base):
    """A server-side session: an opaque token id in a row, revocable and auditable.
    The cookie carries only :attr:`id`; everything else is looked up here."""

    __tablename__ = "sessions"

    #: Opaque, unguessable token (``secrets.token_urlsafe``) — the cookie value.
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    #: The session's CSRF token (P0.1b-i): minted with the row, rendered into every
    #: form on every page, and required back on every cookie-authenticated state
    #: change (see :mod:`src.api.csrf`).
    #:
    #: **Deliberately NOT :attr:`id`.** The id is the ``httponly`` cookie value; this
    #: goes into HTML, and from there into ``Referer`` headers and any log that records
    #: a form body. Reusing one secret for both would hand the session id to every one
    #: of those. There is no signing key in this service (sessions are opaque rows, not
    #: signed cookies, and P0.2 deliberately declined to invent an app secret), so a
    #: random per-session value in the row every request already reads is the cheapest
    #: honest answer: one column, no new concept.
    #:
    #: The default lives on the COLUMN, not in the service that mints sessions, so no
    #: code path can produce a session row without a token — a tokenless row would not
    #: fail loudly, it would silently make that session's every form submission 403.
    csrf_token: Mapped[str] = mapped_column(String(64), default=new_csrf_token)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)
    ip_addr: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    user: Mapped[User] = relationship(back_populates="sessions")

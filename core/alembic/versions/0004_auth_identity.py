"""auth identity — users, roles, sessions (RBAC foundation, ADR-008)

Adds the CAS-backed identity tables:

* ``users`` — a person keyed by ``cas_username`` (provisioned on first CAS login).
* ``user_roles`` — (user, role) grants, role ∈ {author, reviewer, admin}.
* ``sessions`` — opaque server-side session tokens (revocable, auditable).

Identity comes from CAS, so ``users`` has no password hash (ADR-008). Enum DB values
are the ORM enum member NAMES (the repo convention — see 0001), so the models round-trip
unchanged. The hash-chained tamper-evidence for ``audit_log`` lands in a later revision,
when auth/action events are wired through it.

Revision ID: 0004_auth_identity
Revises: 0003_one_parse_per_key
Create Date: 2026-07-25

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004_auth_identity"
down_revision: str | None = "0003_one_parse_per_key"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Enum types — values are the ORM enum member NAMES (repo convention, see 0001).
_ROLE = sa.Enum("AUTHOR", "REVIEWER", "ADMIN", name="role")
_USER_STATUS = sa.Enum("ACTIVE", "DISABLED", name="userstatus")

_NOW = sa.text("now()")


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("cas_username", sa.String(128), nullable=False, unique=True),
        sa.Column("display_name", sa.String(256), nullable=False),
        sa.Column("email", sa.String(256), nullable=True),
        sa.Column(
            "status", _USER_STATUS, nullable=False, server_default="ACTIVE"
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=_NOW,
            nullable=False,
        ),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_users_cas_username", "users", ["cas_username"], unique=True)

    op.create_table(
        "user_roles",
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("role", _ROLE, primary_key=True),
    )

    op.create_table(
        "sessions",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("user_agent", sa.String(512), nullable=True),
        sa.Column("ip_addr", sa.String(64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=_NOW,
            nullable=False,
        ),
    )
    op.create_index("ix_sessions_user_id", "sessions", ["user_id"])
    # Fast lookup of a user's live sessions (revoke-on-disable walks these).
    op.create_index(
        "ix_sessions_active",
        "sessions",
        ["expires_at"],
        postgresql_where=sa.text("revoked_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_sessions_active", table_name="sessions")
    op.drop_index("ix_sessions_user_id", table_name="sessions")
    op.drop_table("sessions")
    op.drop_table("user_roles")
    op.drop_index("ix_users_cas_username", table_name="users")
    op.drop_table("users")
    _ROLE.drop(op.get_bind(), checkfirst=True)
    _USER_STATUS.drop(op.get_bind(), checkfirst=True)

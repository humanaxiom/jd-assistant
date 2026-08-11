"""sessions.csrf_token — a per-session CSRF secret (P0.1b-i)

Every UI mutation in this app is a cookie-authenticated form POST. ``SameSite=Lax``
withholds the cookie from a cross-site POST, but that is a *browser* behaviour this
service cannot verify at runtime and it does not separate a same-site subdomain from us.
A token the server issues and checks is something it *can* verify — see
``src/api/csrf.py``.

There is no signing key anywhere in this service (sessions are opaque
``secrets.token_urlsafe(32)`` ids in this very table, not signed cookies; P0.2
deliberately declined to invent an app secret), so a *signed* double-submit cookie is
not available. A random per-session token in the row every request already reads costs
one column and no new concept.

**Not the session id.** The id is the ``httponly`` cookie value; this column's value is
rendered into HTML and therefore travels in ``Referer`` headers and form-body logs.

Existing rows are backfilled with a distinct random value each (``gen_random_uuid()``,
core in Postgres 13+) rather than one shared default — two sessions sharing a token
would defeat the control — and no server default is left behind, so the application must
supply one on every INSERT. A signed-in user whose session predates this migration is
not logged out: their next page render reads the backfilled token out of their own row
and puts it in the form.

**Deploy ordering: this needs an atomic code+schema swap, and it is not rolling-safe.**
Because there is no server default, *old code on the new schema* cannot INSERT a session
at all — login breaks — and *new code on the old schema* breaks everything, since every
request's session lookup selects a column that does not exist. There is no ordering of
the two that is safe on its own. That is fine for how this service is actually deployed
(``docker compose up`` replaces the image and the migration runs against a stopped app),
and it is stated here so nobody plans a rolling release around it. The alternative — a
temporary server default — would silently hand every row the same token if the backfill
were skipped, which is worse than a brief outage.

Revision ID: 0006_session_csrf_token
Revises: 0005_audit_hash_chain
Create Date: 2026-08-11

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0006_session_csrf_token"
down_revision: str | None = "0005_audit_hash_chain"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Added nullable first so the backfill can give every existing row its OWN value;
    # a server_default would give them all the same one.
    op.add_column("sessions", sa.Column("csrf_token", sa.String(64), nullable=True))
    op.execute(
        "UPDATE sessions SET csrf_token = replace(gen_random_uuid()::text, '-', '') "
        "WHERE csrf_token IS NULL"
    )
    op.alter_column("sessions", "csrf_token", nullable=False)


def downgrade() -> None:
    op.drop_column("sessions", "csrf_token")

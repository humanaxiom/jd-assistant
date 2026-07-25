"""tamper-evident audit — hash-chain the existing audit_log (ADR-008)

Makes the append-only ``audit_log`` tamper-EVIDENT (ported in shape from HRIS): a
``BEFORE INSERT`` trigger links each row to the previous one by SHA-256, so altering or
deleting any past row is detectable by recomputing the chain
(:func:`src.api.services.audit.verify_audit_chain`).

Adds ``prev_hash`` / ``row_hash`` (nullable — existing rows keep NULL and sit outside the
chain, which starts fresh at the first insert after this migration), a single-row
``audit_chain_tail`` tracker (row-locked by the trigger to serialise concurrent inserts),
a shared ``audit_log_payload()`` (the verifier calls it too, so trigger and verifier can't
drift), and the chain trigger. Hashes over the JD ``audit_log`` columns
(created_at | actor | event_type | entity_type | entity_id | payload).

Tamper-PREVENTION (REVOKE UPDATE/DELETE via a restricted app role) is a later hardening
step — it needs the app to connect as a non-owner role (ADR-008). This migration gives
detection, not prevention.

Revision ID: 0005_audit_hash_chain
Revises: 0004_auth_identity
Create Date: 2026-07-25

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0005_audit_hash_chain"
down_revision: str | None = "0004_auth_identity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# One statement per element — asyncpg (via SQLAlchemy) prepares statements and rejects a
# multi-command string, so each CREATE/ALTER/INSERT is executed on its own. The two
# CREATE FUNCTIONs stay whole (their internal ``;`` sit inside the ``$$`` body literal =
# still one command each).
_UPGRADE: tuple[str, ...] = (
    "CREATE EXTENSION IF NOT EXISTS pgcrypto",
    "ALTER TABLE audit_log ADD COLUMN prev_hash BYTEA, ADD COLUMN row_hash BYTEA",
    # Single-row tail tracker; the trigger SELECT ... FOR UPDATEs it to serialise
    # concurrent inserts (row-lock) and re-read the post-commit tail.
    "CREATE TABLE audit_chain_tail ("
    " id INT PRIMARY KEY DEFAULT 1 CHECK (id = 1), tail_hash BYTEA NOT NULL)",
    "INSERT INTO audit_chain_tail (id, tail_hash) VALUES (1, '\\x00'::bytea)",
    # Shared payload assembly — the verifier calls this too, so they can't drift.
    r"""CREATE OR REPLACE FUNCTION audit_log_payload(
    p_created_at  TIMESTAMPTZ,
    p_actor       TEXT,
    p_event_type  TEXT,
    p_entity_type TEXT,
    p_entity_id   UUID,
    p_payload     JSONB
) RETURNS BYTEA AS $$
BEGIN
  RETURN convert_to(
    coalesce(p_created_at::text, '') || '|' ||
    coalesce(p_actor, '')            || '|' ||
    coalesce(p_event_type, '')       || '|' ||
    coalesce(p_entity_type, '')      || '|' ||
    coalesce(p_entity_id::text, '')  || '|' ||
    coalesce(p_payload::text, ''),
    'UTF8'
  );
END;
$$ LANGUAGE plpgsql IMMUTABLE""",
    r"""CREATE OR REPLACE FUNCTION audit_log_hash_chain() RETURNS trigger AS $$
DECLARE
    prev BYTEA;
BEGIN
    SELECT tail_hash INTO prev FROM audit_chain_tail WHERE id = 1 FOR UPDATE;
    NEW.prev_hash := prev;
    NEW.row_hash := digest(
        prev || audit_log_payload(NEW.created_at, NEW.actor, NEW.event_type,
                                  NEW.entity_type, NEW.entity_id, NEW.payload),
        'sha256'
    );
    UPDATE audit_chain_tail SET tail_hash = NEW.row_hash WHERE id = 1;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql""",
    "CREATE TRIGGER audit_log_chain BEFORE INSERT ON audit_log"
    " FOR EACH ROW EXECUTE FUNCTION audit_log_hash_chain()",
)

_DOWNGRADE: tuple[str, ...] = (
    "DROP TRIGGER IF EXISTS audit_log_chain ON audit_log",
    "DROP FUNCTION IF EXISTS audit_log_hash_chain()",
    "DROP FUNCTION IF EXISTS audit_log_payload("
    "TIMESTAMPTZ, TEXT, TEXT, TEXT, UUID, JSONB)",
    "DROP TABLE IF EXISTS audit_chain_tail",
    "ALTER TABLE audit_log DROP COLUMN IF EXISTS row_hash",
    "ALTER TABLE audit_log DROP COLUMN IF EXISTS prev_hash",
)


def upgrade() -> None:
    for statement in _UPGRADE:
        op.execute(statement)


def downgrade() -> None:
    for statement in _DOWNGRADE:
        op.execute(statement)

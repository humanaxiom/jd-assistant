"""parsed_jds: one row per (source document, parser version)

**LANDMINE 1, closed** (Phase 3.2a, HANDOFF: "Postgres is empty and unfillable" — this
migration is a prerequisite of the archive->Postgres ingest driver). ``parse_and_store``
did an unconditional ``session.add(ParsedJDRow(...))`` and ``parsed_jds`` carried no
unique constraint at all. Running the driver twice over the same archive would have
produced **29,130** rows instead of 14,565 — a fresh UUID per re-parse — and Phase 3.2b
keys vectors off these rows, so the duplicates would orphan every vector on the next
run.

The parse is a pure function of ``(source bytes, parser_version)`` — the same source
document, re-parsed at the same parser version, must always be the SAME row. This
migration adds the constraint that makes that true at the database, mirroring ``0002``
(``source_documents``'s ``(storage_ref, sha256)`` idempotency key): one FK + one
version is one ledger row.

Note this is the OPPOSITE hazard from ``0002``. There the destructive direction was the
**downgrade** (restoring ``UNIQUE(sha256)`` is impossible once real duplicate hashes
exist, which is the archive's normal shape) and the upgrade was safe. Here the **upgrade**
is the one that can fail: if duplicate ``(source_document_id, parser_version)`` rows
already exist — exactly LANDMINE 1's symptom, from a driver run before this migration
existed — the constraint cannot be created. The downgrade (dropping a constraint) has no
such hazard.

The database is empty today (no ingest driver has ever run against it), so a hard
failure with a clear message is the honest behaviour: refuse rather than silently
deleting parses to make room for itself.

Revision ID: 0003_one_parse_per_key
Revises: 0002_one_row_per_file
Create Date: 2026-07-13

NB the revision id is short on purpose: Alembic's ``alembic_version.version_num`` is
``varchar(32)``, and a descriptive-but-long id fails at the very last statement of the
migration — after the DDL has already applied.

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003_one_parse_per_key"
down_revision: str | None = "0002_one_row_per_file"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UNIQUE = "uq_parsed_source_parser"


def upgrade() -> None:
    duplicates = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT count(*) FROM ("
                "  SELECT source_document_id, parser_version FROM parsed_jds"
                "  GROUP BY source_document_id, parser_version HAVING count(*) > 1"
                ") AS d"
            )
        )
        .scalar_one()
    )
    if duplicates:
        raise RuntimeError(
            f"cannot add {_UNIQUE}: {duplicates} (source_document_id, parser_version) "
            f"pairs already have more than one parsed_jds row. That is exactly the "
            f"duplication this constraint exists to prevent (a driver ran before this "
            f"migration, or re-parsed without the idempotency fix in "
            f"jd_core.parser.store). Decide which parse to keep per pair and delete "
            f"the rest deliberately — a migration will not do it for you."
        )
    op.create_unique_constraint(
        _UNIQUE, "parsed_jds", ["source_document_id", "parser_version"]
    )


def downgrade() -> None:
    # Safe in both directions: dropping a unique constraint never loses rows. Unlike
    # 0002's downgrade, there is no hazard here to refuse against.
    op.drop_constraint(_UNIQUE, "parsed_jds", type_="unique")

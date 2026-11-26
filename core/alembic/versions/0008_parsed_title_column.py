"""A STORED ``parsed_jds.title`` column for the document-title search pass (parser v9)

Builder search and the library find archive documents by TITLE first. Until now the
predicate was ``parsed ->> 'title'``, served by the 0007 trigram index — but only when
the planner CHOSE that index. MEASURED on the separate v9 Bank (one parse per
document, 14,522 rows; 2026-10-20): the planner costs a sequential scan cheaper (the
heap is small because ``parsed`` lives in TOAST), and every row of that scan then
DETOASTS the whole ``parsed`` JSONB to read one key — **650 ms per query**, against
**1.5 ms** through the index. v9's parses are ~2.5x larger, and the planner does not
cost the detoast at all. Builder search p95 went to 2.02 s against HR-242's 1.0 s
budget (the live v8 Bank, with eight parses per document, happens to pick the index:
p95 0.31 s). An index the planner may decline is not a guarantee.

This migration:

* adds ``title text GENERATED ALWAYS AS (parsed ->> 'title') STORED`` — written by
  Postgres from the JSON, so it can never drift from it and no app code writes it;
* builds ``ix_parsed_jds_version_title_col_trgm`` — GIN
  ``(parser_version, title gin_trgm_ops)`` — ``CONCURRENTLY``;
* drops 0007's ``ix_parsed_jds_version_title_trgm`` (nothing queries the JSON
  expression any more). The canonical_jds role-title index is untouched.

A sequential scan over the plain column reads a short inline string per row, so even
the plan the planner preferred costs milliseconds, not detoasts.

⚠ **Adding a STORED generated column rewrites ``parsed_jds``** under an ACCESS
EXCLUSIVE lock. MEASURED on a copy of the v9 Bank (14,522 rows): 1.1 s. The live v8
table holds eight parses per document (116,176 rows, ~460 MB), so expect roughly ten
seconds there. ``launch.ps1`` runs ``alembic upgrade head`` at start-up, so it happens
before the app serves. Measured effect on that copy: document-title pass p50 0.54 s ->
0.001 s; Builder search (smoke) p95 2.02 s -> 0.27 s, hit@10 unchanged at 21.

**No re-parse, no re-embed, no rules change.** ``parsed`` content, ``PARSER_VERSION``,
``rules_version`` and every vector are untouched.

Revision ID: 0008_parsed_title_column
Revises: 0007_title_trigram_indexes
Create Date: 2026-10-20

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0008_parsed_title_column"
down_revision: str | None = "0007_title_trigram_indexes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NEW = "ix_parsed_jds_version_title_col_trgm"
_OLD = "ix_parsed_jds_version_title_trgm"


def upgrade() -> None:
    op.execute(
        "ALTER TABLE parsed_jds ADD COLUMN IF NOT EXISTS title text "
        "GENERATED ALWAYS AS (parsed ->> 'title') STORED"
    )
    with op.get_context().autocommit_block():
        bind = op.get_bind()
        valid = bind.execute(
            sa.text(
                "SELECT i.indisvalid FROM pg_index i "
                "JOIN pg_class c ON c.oid = i.indexrelid WHERE c.relname = :name"
            ),
            {"name": _NEW},
        ).scalar()
        if valid is False:  # a failed earlier CONCURRENTLY build: never trust it
            op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {_NEW}")
        op.execute(
            f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {_NEW} ON parsed_jds "
            "USING gin (parser_version, title gin_trgm_ops)"
        )
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {_OLD}")


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {_OLD} ON parsed_jds "
            "USING gin (parser_version, (parsed ->> 'title') gin_trgm_ops)"
        )
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {_NEW}")
    op.execute("ALTER TABLE parsed_jds DROP COLUMN IF EXISTS title")

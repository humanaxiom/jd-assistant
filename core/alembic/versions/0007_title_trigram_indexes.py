"""pg_trgm + trigram indexes on the two title expressions search reads (Track I2)

Builder search ("start from an existing JD") and the library search find roles and
archive documents by TITLE before they ask the embedding host anything. Both title
passes were plain ``ILIKE '%q%'`` with no index able to serve them. MEASURED on the live
Bank (2026-10-19 search spike): the archive-document title pass was a **2.7 s
sequential scan** over all 116,176 ``parsed_jds`` rows (8 parser versions x 14,522
documents, 452 MB) -- about 2.7 s of the Builder's 2.9 s median.

This migration adds:

* ``pg_trgm`` -- trigram matching. Serves ``ILIKE '%q%'`` from an index, and gives the
  typo fallback (``strict_word_similarity`` / the ``<<%`` operator) that recovers
  "labratory techician" -> Laboratory Technician. Ships in ``postgres:16-alpine``
  (``pg_available_extensions``), and is a *trusted* extension, so the database owner
  can create it without superuser.
* ``btree_gin`` -- lets ONE GIN index also carry ``parser_version``. The document title
  pass reads only the CURRENT parse (``parser_version = PARSER_VERSION``, the
  codebase's own predicate); with a title-only index, Postgres would still have to
  fetch and re-check every superseded parse of every matching document (measured on a
  copy of the live table: 470 ms for "Coordinator" title-only vs 150 ms composite).
  Composite rather than a PARTIAL index (``WHERE parser_version = 'jd_segmenter_v8'``)
  on purpose: a partial index would silently stop serving the query at the next
  parser bump and would need a migration per bump. Also trusted.
* ``ix_parsed_jds_version_title_trgm`` -- GIN ``(parser_version, (parsed ->> 'title')
  gin_trgm_ops)``.
* ``ix_canonical_jds_title_trgm`` -- GIN ``((content ->> 'title') gin_trgm_ops)``: the
  harmonized-role title, which both the Builder and the library search.

The index EXPRESSIONS must match the query expressions exactly, which is why
``composer/search.py`` spells the JSON key as a literal (``->> 'title'``) rather than a
bound parameter -- a prepared statement's generic plan cannot match ``->> $1`` to an
index on ``->> 'title'``. Pinned by ``tests/integration/test_search_title_tiers.py``.

**Safe on the live Bank.** The indexes are built ``CONCURRENTLY`` inside Alembic's
``autocommit_block`` (``CREATE INDEX CONCURRENTLY`` cannot run in a transaction), so
reads AND writes continue while they build; the extensions are created in the ordinary
migration transaction first. A concurrent build that fails leaves an INVALID index
behind, and ``IF NOT EXISTS`` alone would then skip it forever -- so an invalid
leftover is dropped and rebuilt rather than trusted. Measured on a copy of the live
``parsed_jds``: the composite index builds in ~3 s and is ~10 MB.

**No re-parse, no re-embed, no rules change.** Nothing here touches ``parsed`` content,
``PARSER_VERSION``, ``rules_version`` or any vector.

**Deploys with no assistant:** ``launch.ps1`` runs ``alembic upgrade head`` on every
launch, and ``deploy/install.ps1`` runs it after restoring a bundle (a no-op when the
dump already carries this revision).

Revision ID: 0007_title_trigram_indexes
Revises: 0006_session_csrf_token
Create Date: 2026-10-19

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0007_title_trigram_indexes"
down_revision: str | None = "0006_session_csrf_token"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: ``(name, CREATE INDEX body)`` -- the body follows ``CREATE INDEX CONCURRENTLY``.
_INDEXES: tuple[tuple[str, str], ...] = (
    (
        "ix_parsed_jds_version_title_trgm",
        "ON parsed_jds USING gin "
        "(parser_version, (parsed ->> 'title') gin_trgm_ops)",
    ),
    (
        "ix_canonical_jds_title_trgm",
        "ON canonical_jds USING gin ((content ->> 'title') gin_trgm_ops)",
    ),
)


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gin")
    with op.get_context().autocommit_block():
        bind = op.get_bind()
        for name, body in _INDEXES:
            valid = bind.execute(
                sa.text(
                    "SELECT i.indisvalid FROM pg_index i "
                    "JOIN pg_class c ON c.oid = i.indexrelid WHERE c.relname = :name"
                ),
                {"name": name},
            ).scalar()
            if valid is False:  # a failed earlier CONCURRENTLY build: never trust it
                op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {name}")
            op.execute(f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {name} {body}")


def downgrade() -> None:
    with op.get_context().autocommit_block():
        for name, _body in _INDEXES:
            op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {name}")
    # Nothing else in the schema uses either extension; dropping them returns the
    # database to exactly the 0006 state.
    op.execute("DROP EXTENSION IF EXISTS btree_gin")
    op.execute("DROP EXTENSION IF EXISTS pg_trgm")

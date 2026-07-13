"""source_documents: one row per FILE, not one row per distinct content

**A provenance fix** (CLAUDE.md non-negotiable #6: every canonical JD traces to its
sources). ``source_documents.sha256`` was ``UNIQUE``, and ``ingest_document`` returned
the existing row on a duplicate hash. So the table was a ledger of distinct *content*
while every consumer read it as a ledger of the *archive*.

MEASURED on the real archive (14,565 files, this repo's own ``compute_sha256``):
**1,037** SHA-256 groups hold more than one file, **3,009** files sit in one, and
**1,972** of those are byte-for-byte redundant copies. Under the old schema those 1,972
files would have been ingested and their filenames **discarded entirely** — no row, no
record they ever existed. "Which archive files produced this canonical JD?" was
unanswerable. And ``DedupTier.EXACT`` / ``dedup_edges`` were dead code: an edge needs
two ``source_id``s and the duplicate never got one.

This migration:

* drops the **UNIQUE** on ``sha256`` but **keeps the index** — it is the Tier-1
  grouping key (``src.jd_bank.dedup``), and duplicates are now the point;
* adds ``uq_source_ref_sha256`` on ``(storage_ref, sha256)`` — the idempotency key that
  replaces it: *this exact content, at this exact location, is one ledger row*, so a
  re-run of ingestion does not double-insert the archive.

Note on the composite key's size: ``storage_ref`` is ``varchar(1024)``. Postgres's btree
entry limit (~2704 bytes) is only reachable by a storage_ref of several hundred
multi-byte characters; real archive refs are ~60. An insert that ever hit it would fail
loudly at INSERT, not corrupt anything.

Downgrade is **conditionally destructive and says so**: restoring ``UNIQUE(sha256)``
is impossible while duplicate hashes exist, which is the normal state of an ingested
archive. It raises rather than deleting rows to make room for itself.

Revision ID: 0002_one_row_per_file
Revises: 0001_initial_schema
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
revision: str = "0002_one_row_per_file"
down_revision: str | None = "0001_initial_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SHA_INDEX = "ix_source_documents_sha256"
_REF_SHA_UNIQUE = "uq_source_ref_sha256"


def upgrade() -> None:
    # The index was created UNIQUE in 0001, so the constraint and the index are the
    # same object: drop it and recreate it non-unique under the same name (which is
    # what the Tier-1 sha256 lookup uses).
    op.drop_index(_SHA_INDEX, table_name="source_documents")
    op.create_index(_SHA_INDEX, "source_documents", ["sha256"], unique=False)
    op.create_unique_constraint(
        _REF_SHA_UNIQUE, "source_documents", ["storage_ref", "sha256"]
    )


def downgrade() -> None:
    duplicates = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT count(*) FROM ("
                "  SELECT sha256 FROM source_documents"
                "  GROUP BY sha256 HAVING count(*) > 1"
                ") AS d"
            )
        )
        .scalar_one()
    )
    if duplicates:
        raise RuntimeError(
            f"cannot restore UNIQUE(source_documents.sha256): {duplicates} sha256 "
            f"values are shared by more than one file. That is the archive's real "
            f"shape (1,037 groups / 3,009 files as measured), and it is exactly what "
            f"this migration exists to allow. Decide which rows to lose and delete "
            f"them deliberately — a migration will not do it for you."
        )
    op.drop_constraint(_REF_SHA_UNIQUE, "source_documents", type_="unique")
    op.drop_index(_SHA_INDEX, table_name="source_documents")
    op.create_index(_SHA_INDEX, "source_documents", ["sha256"], unique=True)

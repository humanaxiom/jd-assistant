"""initial schema — harness ledger + JD Bank domain

Creates the complete database in one baseline revision:

* harness ledger: ``tasks``, ``runs``, ``gate_results``
* JD Bank domain: ``source_documents``, ``parsed_jds``, ``validation_reports``,
  ``dedup_edges``, ``clusters``, ``canonical_jds``, ``review_actions``,
  ``audit_log``

Enum DB values are the SQLAlchemy default (the Python enum *member names*), so
the ORM round-trips against this schema unchanged.

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-07-10

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001_initial_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# ── Enum types (values = ORM enum member names) ─────────────────────────────
_TASK_STATUS = sa.Enum(
    "PENDING",
    "PLANNING",
    "RED",
    "ITERATING",
    "REVIEW",
    "ESCALATED",
    "DONE",
    "FAILED",
    name="taskstatus",
)
_GATE_STATUS = sa.Enum("GREEN", "RED", "SKIPPED", name="gatestatus")
_DOCUMENT_FORMAT = sa.Enum(
    "DOCX", "DOC", "RTF", "TXT", "OTHER", name="documentformat"
)
_DEDUP_TIER = sa.Enum(
    "EXACT", "NEAR_DUPLICATE", "ROLE_EQUIVALENT", name="deduptier"
)
_CANONICAL_STATUS = sa.Enum(
    "DRAFT", "PUBLISHED", "ARCHIVED", name="canonicalstatus"
)
_REVIEW_ACTION_KIND = sa.Enum(
    "APPROVE", "REJECT", "EDIT", "OVERRIDE", name="reviewactionkind"
)

_JSONB_OBJ = sa.text("'{}'::jsonb")
_JSONB_ARR = sa.text("'[]'::jsonb")
_NOW = sa.text("now()")


def upgrade() -> None:
    # ── Harness ledger ──────────────────────────────────────────────────────
    op.create_table(
        "tasks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("spec", sa.Text(), nullable=False),
        sa.Column("branch", sa.String(255), nullable=True),
        sa.Column("status", _TASK_STATUS, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_NOW),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=_NOW),
    )
    op.create_table(
        "runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "task_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tasks.id"),
            nullable=False,
        ),
        sa.Column("iteration", sa.Integer(), nullable=False),
        sa.Column("agent_id", sa.String(64), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_NOW),
    )
    op.create_table(
        "gate_results",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("runs.id"),
            nullable=False,
        ),
        sa.Column("gate_name", sa.String(64), nullable=False),
        sa.Column("status", _GATE_STATUS, nullable=False),
        sa.Column("output", sa.Text(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_NOW),
    )

    # ── JD Bank domain ──────────────────────────────────────────────────────
    op.create_table(
        "source_documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("storage_ref", sa.String(1024), nullable=False),
        sa.Column("filename", sa.String(512), nullable=True),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("fmt", _DOCUMENT_FORMAT, nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column(
            "ingest_metadata",
            postgresql.JSONB(),
            server_default=_JSONB_OBJ,
            nullable=False,
        ),
        sa.Column(
            "normalization_report",
            postgresql.JSONB(),
            server_default=_JSONB_OBJ,
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_NOW),
    )
    op.create_index(
        "ix_source_documents_sha256",
        "source_documents",
        ["sha256"],
        unique=True,
    )

    op.create_table(
        "parsed_jds",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "source_document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("source_documents.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("parsed", postgresql.JSONB(), nullable=False),
        sa.Column("parser_version", sa.String(64), nullable=False),
        sa.Column("parse_confidence", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_NOW),
    )

    op.create_table(
        "validation_reports",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "parsed_jd_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("parsed_jds.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "issues",
            postgresql.JSONB(),
            server_default=_JSONB_ARR,
            nullable=False,
        ),
        sa.Column(
            "gate_results",
            postgresql.JSONB(),
            server_default=_JSONB_OBJ,
            nullable=False,
        ),
        sa.Column("passed", sa.Boolean(), nullable=False),
        sa.Column("rules_version", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_NOW),
        sa.UniqueConstraint(
            "parsed_jd_id", "version", name="uq_validation_version"
        ),
    )

    op.create_table(
        "dedup_edges",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "source_a_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("source_documents.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "source_b_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("source_documents.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("tier", _DEDUP_TIER, nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("method", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_NOW),
        sa.UniqueConstraint(
            "source_a_id", "source_b_id", "tier", name="uq_dedup_pair_tier"
        ),
    )

    op.create_table(
        "clusters",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("label", sa.String(255), nullable=True),
        sa.Column("employee_group", sa.String(32), nullable=True),
        sa.Column("level_band", sa.String(64), nullable=True),
        sa.Column(
            "members",
            postgresql.JSONB(),
            server_default=_JSONB_ARR,
            nullable=False,
        ),
        sa.Column(
            "constraint_metadata",
            postgresql.JSONB(),
            server_default=_JSONB_OBJ,
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_NOW),
    )

    op.create_table(
        "canonical_jds",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "cluster_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("clusters.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", _CANONICAL_STATUS, nullable=False),
        sa.Column("content", postgresql.JSONB(), nullable=False),
        sa.Column(
            "source_document_ids",
            postgresql.JSONB(),
            server_default=_JSONB_ARR,
            nullable=False,
        ),
        sa.Column(
            "validation_report_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("validation_reports.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "change_log",
            postgresql.JSONB(),
            server_default=_JSONB_OBJ,
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_NOW),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=_NOW),
        sa.UniqueConstraint(
            "cluster_id", "version", name="uq_canonical_version"
        ),
    )

    op.create_table(
        "review_actions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "canonical_jd_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("canonical_jds.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("action", _REVIEW_ACTION_KIND, nullable=False),
        sa.Column("reviewer_id", sa.String(128), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "payload",
            postgresql.JSONB(),
            server_default=_JSONB_OBJ,
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_NOW),
    )

    op.create_table(
        "audit_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("event_type", sa.String(128), nullable=False, index=True),
        sa.Column("entity_type", sa.String(64), nullable=True),
        sa.Column(
            "entity_id", postgresql.UUID(as_uuid=True), nullable=True, index=True
        ),
        sa.Column("actor", sa.String(128), nullable=True),
        sa.Column(
            "payload",
            postgresql.JSONB(),
            server_default=_JSONB_OBJ,
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=_NOW,
            index=True,
        ),
    )


def downgrade() -> None:
    op.drop_table("audit_log")
    op.drop_table("review_actions")
    op.drop_table("canonical_jds")
    op.drop_table("clusters")
    op.drop_table("dedup_edges")
    op.drop_table("validation_reports")
    op.drop_table("parsed_jds")
    op.drop_index("ix_source_documents_sha256", table_name="source_documents")
    op.drop_table("source_documents")
    op.drop_table("gate_results")
    op.drop_table("runs")
    op.drop_table("tasks")

    for enum_type in (
        _REVIEW_ACTION_KIND,
        _CANONICAL_STATUS,
        _DEDUP_TIER,
        _DOCUMENT_FORMAT,
        _GATE_STATUS,
        _TASK_STATUS,
    ):
        enum_type.drop(op.get_bind(), checkfirst=True)

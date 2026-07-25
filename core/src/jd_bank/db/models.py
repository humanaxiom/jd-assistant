"""JD Bank domain tables — the persistence contract for ingest → parse →
validate → dedup → cluster → harmonize → review → publish.

All models bind to the *shared* harness ``Base`` (``src.models.db.Base``) so a
single ``MetaData`` covers the harness ledger (tasks/runs/gate_results) and the
JD Bank domain. Conventions mirror the harness models: UUID primary keys,
timezone-aware timestamps with server defaults, ``StrEnum`` columns for closed
value sets, and JSONB for structured payloads (ParsedJD, validation issues,
lineage, audit events).

Provenance is a first-class concern (plan §0): the FK chain
``source_documents → parsed_jds → validation_reports`` and
``clusters → canonical_jds → review_actions`` lets every canonical JD trace
back to its raw bytes, and :class:`AuditLog` is an append-only event stream
over all of it.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

# Reuse the harness Base so one metadata registers every table (harness + JD Bank).
from src.models.db import Base

# ── Closed value sets (Postgres ENUM types) ────────────────────────────────


class DocumentFormat(enum.StrEnum):
    """Ingest source format. Legacy binary ``.doc`` is distinct from OOXML."""

    DOCX = "docx"
    DOC = "doc"
    RTF = "rtf"
    TXT = "txt"
    OTHER = "other"


class IssueSeverity(enum.StrEnum):
    """Validation severity model. ``blocking`` gates a JD from publication."""

    BLOCKING = "blocking"
    WARNING = "warning"
    INFO = "info"


class DedupTier(enum.StrEnum):
    """The three dedup tiers (plan §2.1)."""

    EXACT = "exact"  # Tier 1 — SHA-256 over normalized text
    NEAR_DUPLICATE = "near_duplicate"  # Tier 2 — MinHash + cosine confirm
    ROLE_EQUIVALENT = "role_equivalent"  # Tier 3 — embedding + skill similarity


class CanonicalStatus(enum.StrEnum):
    """Lifecycle of a canonical JD. Nothing publishes without HR approval."""

    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class ReviewActionKind(enum.StrEnum):
    """Reviewer decisions. ``override`` requires a written reason (app-enforced)."""

    APPROVE = "approve"
    REJECT = "reject"
    EDIT = "edit"
    OVERRIDE = "override"


# ── Tables ──────────────────────────────────────────────────────────────────


class SourceDocument(Base):
    """A raw archive file: a bytes reference, its SHA-256 (Tier-1 dedup key),
    detected format, ingest metadata, and the incumbent-name normalization
    report produced during ingestion.

    **ONE ROW PER FILE — a faithful ledger of the archive** (Phase 3.1, migration
    ``0002``). ``sha256`` used to be ``unique=True``, which made this table a ledger of
    distinct *content* rather than of *files*: of the 3,009 archive files that sit in
    an exact-duplicate group, 1,972 would have been ingested and their filenames
    discarded, so "which archive files produced this canonical JD?" was unanswerable
    (CLAUDE.md non-negotiable #6). It also made ``DedupEdge`` and ``DedupTier.EXACT``
    dead code: an edge needs two ``source_id``s and the duplicate never got one.

    Duplication is now a **finding**, expressed as :class:`DedupEdge` rows
    (:mod:`src.jd_bank.dedup`), never a write-time collapse.

    ``sha256`` keeps its (non-unique) index — it is the Tier-1 grouping key. The
    idempotency key that replaced the unique hash is ``(storage_ref, sha256)``: *this
    exact content, at this exact location, is one ledger row*. ``storage_ref`` alone
    would have forced a re-ingest of changed bytes to either UPDATE in place — silently
    re-pointing the ``parsed_jds`` already hanging off the row at bytes that did not
    produce them — or to raise.
    """

    __tablename__ = "source_documents"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # Reference to the stored raw bytes (object-store key / archive path), not
    # the bytes themselves — Postgres holds metadata, not blobs.
    storage_ref: Mapped[str] = mapped_column(String(1024))
    filename: Mapped[str | None] = mapped_column(String(512), nullable=True)
    #: Indexed, NOT unique — the Tier-1 dedup key, and duplicates are the point.
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    fmt: Mapped[DocumentFormat] = mapped_column(Enum(DocumentFormat))
    byte_size: Mapped[int] = mapped_column(Integer, default=0)
    ingest_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default="{}"
    )
    normalization_report: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default="{}"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    parsed_jds: Mapped[list[ParsedJDRow]] = relationship(
        back_populates="source_document"
    )

    __table_args__ = (
        UniqueConstraint("storage_ref", "sha256", name="uq_source_ref_sha256"),
    )


class ParsedJDRow(Base):
    """The structured ``ParsedJD`` (SFU 10-section schema) extracted from one
    source document, with the parser version and per-parse confidence.

    **ONE ROW PER (source document, parser version)** (Phase 3.2a, migration ``0003``).
    ``jd_core.parser.store.parse_and_store`` is idempotent on this key — re-parsing the
    same document at the same parser version returns the existing row rather than
    inserting a second one."""

    __tablename__ = "parsed_jds"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    source_document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("source_documents.id", ondelete="CASCADE"), index=True
    )
    # The serialized SFUJobDescription (jd_core.models.parsed_jd).
    parsed: Mapped[dict[str, Any]] = mapped_column(JSONB)
    parser_version: Mapped[str] = mapped_column(String(64))
    parse_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    source_document: Mapped[SourceDocument] = relationship(back_populates="parsed_jds")
    validation_reports: Mapped[list[ValidationReport]] = relationship(
        back_populates="parsed_jd"
    )

    __table_args__ = (
        # LANDMINE 1 (Phase 3.2a, migration 0003): the parse is a pure function of
        # (source bytes, parser_version), so re-parsing the same document at the same
        # parser version must be the SAME row. Without this, `parse_and_store` had no
        # constraint stopping a re-run of the archive driver from inserting a second
        # (or 14,565th) copy of every parse.
        UniqueConstraint(
            "source_document_id", "parser_version", name="uq_parsed_source_parser"
        ),
    )


class ValidationReport(Base):
    """A versioned rulebook validation of one parsed JD: the flat issue list
    (code / severity / section / evidence / recommendation) plus rolled-up gate
    results and an overall pass flag."""

    __tablename__ = "validation_reports"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    parsed_jd_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("parsed_jds.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer, default=1)
    # list[{code, severity, section, evidence, recommendation}]
    issues: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list, server_default="[]"
    )
    # {gate_id: {passed: bool, reasons: [...]}}
    gate_results: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default="{}"
    )
    passed: Mapped[bool] = mapped_column(Boolean, default=False)
    rules_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    parsed_jd: Mapped[ParsedJDRow] = relationship(back_populates="validation_reports")

    __table_args__ = (
        UniqueConstraint("parsed_jd_id", "version", name="uq_validation_version"),
    )


class DedupEdge(Base):
    """A similarity edge between two source documents, tagged with the tier that
    produced it, the score, and the method (e.g. ``sha256``, ``minhash+cosine``,
    ``vec+skill``). Undirected in intent; ``(a, b, tier)`` is unique.

    ⚠ The unique constraint is on the **ordered** triple, so it cannot by itself stop
    ``(b, a)`` from landing next to ``(a, b)``. Writers must orient every edge by one
    total order over the endpoints — a *structural* order (the archive path), never
    "whichever endpoint the writer happened to start from". :mod:`src.jd_bank.dedup`
    orients on ``dedup.order_key`` and pins it against the real database, across a
    re-anchoring and a topology flip, not merely on a single fresh pass (a fresh pass
    is the one case where the two coincide, so it cannot catch a violation)."""

    __tablename__ = "dedup_edges"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    source_a_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("source_documents.id", ondelete="CASCADE"), index=True
    )
    source_b_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("source_documents.id", ondelete="CASCADE"), index=True
    )
    tier: Mapped[DedupTier] = mapped_column(Enum(DedupTier))
    score: Mapped[float] = mapped_column(Float, default=0.0)
    method: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "source_a_id", "source_b_id", "tier", name="uq_dedup_pair_tier"
        ),
    )


class Cluster(Base):
    """A role cluster (connected component over Tier-3 edges), partitioned by the
    hard constraints (employee group × level band). ``members`` lists the source
    document ids; the constraint metadata is carried explicitly so partitioning
    is auditable."""

    __tablename__ = "clusters"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    employee_group: Mapped[str | None] = mapped_column(String(32), nullable=True)
    level_band: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # list[source_document_id] — membership captured as an auditable snapshot.
    members: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list, server_default="[]"
    )
    constraint_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default="{}"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    canonical_jds: Mapped[list[CanonicalJD]] = relationship(back_populates="cluster")


class CanonicalJD(Base):
    """The one canonical JD per role: draft and published versions, its ParsedJD
    content, and lineage back to the originating cluster + source documents.
    Optionally linked to the validation report that cleared it."""

    __tablename__ = "canonical_jds"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    cluster_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("clusters.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[CanonicalStatus] = mapped_column(
        Enum(CanonicalStatus), default=CanonicalStatus.DRAFT
    )
    # The canonical ParsedJD (SFUJobDescription) draft/published content.
    content: Mapped[dict[str, Any]] = mapped_column(JSONB)
    # Lineage: the source_document ids this canonical was harmonized from.
    source_document_ids: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list, server_default="[]"
    )
    validation_report_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("validation_reports.id", ondelete="SET NULL"), nullable=True
    )
    change_log: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default="{}"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    cluster: Mapped[Cluster] = relationship(back_populates="canonical_jds")
    review_actions: Mapped[list[ReviewAction]] = relationship(
        back_populates="canonical_jd"
    )

    __table_args__ = (
        UniqueConstraint("cluster_id", "version", name="uq_canonical_version"),
    )


class ReviewAction(Base):
    """An HR reviewer decision on a canonical JD: approve / reject / edit /
    override. ``reason`` is mandatory for ``override`` of a blocking gate
    (enforced in the review service; nullable here so non-override actions need
    no reason)."""

    __tablename__ = "review_actions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    canonical_jd_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("canonical_jds.id", ondelete="CASCADE"), index=True
    )
    action: Mapped[ReviewActionKind] = mapped_column(Enum(ReviewActionKind))
    reviewer_id: Mapped[str] = mapped_column(String(128))
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Edit payloads / diffs, override context, etc.
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default="{}"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    canonical_jd: Mapped[CanonicalJD] = relationship(back_populates="review_actions")


class AuditLog(Base):
    """Append-only event stream over everything above (plan §0: provenance
    everywhere). No update/delete path — rows are only inserted, and a hash-chain
    trigger (migration 0005, ADR-008) makes any tampering detectable."""

    __tablename__ = "audit_log"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    event_type: Mapped[str] = mapped_column(String(128), index=True)
    entity_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    actor: Mapped[str | None] = mapped_column(String(128), nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default="{}"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    # Tamper-evidence (ADR-008): set by the BEFORE INSERT hash-chain trigger, NOT the
    # writer. Nullable so rows inserted before migration 0005 (chain not yet live) keep
    # NULL and sit outside the chain. Never read by writers; the verifier walks them.
    prev_hash: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    row_hash: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)

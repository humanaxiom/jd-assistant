"""Unit tests for the JD Bank schema wiring — no DB required.

Covers two structural guarantees:

1. Importing the JD Bank models registers all 8 domain tables (plus the harness
   ledger) on the *shared* ``Base.metadata`` — proving one metadata covers
   everything (so ``Base.metadata.create_all`` and Alembic autogenerate agree).
2. The initial Alembic migration module imports cleanly and defines a non-empty
   ``revision`` with callable ``upgrade``/``downgrade`` — the structural proof
   the migration is well-formed even without applying it to a live DB.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

from src.jd_bank.db import models
from src.models.db import Base

CORE_DIR = Path(__file__).resolve().parents[2]
MIGRATION_PATH = CORE_DIR / "alembic" / "versions" / "0001_initial_schema.py"

JD_BANK_TABLES = {
    "source_documents",
    "parsed_jds",
    "validation_reports",
    "dedup_edges",
    "clusters",
    "canonical_jds",
    "review_actions",
    "audit_log",
}
HARNESS_TABLES = {"tasks", "runs", "gate_results"}


def test_jd_bank_tables_registered_on_shared_metadata() -> None:
    registered = set(Base.metadata.tables)
    assert JD_BANK_TABLES <= registered
    # Harness ledger shares the same metadata (single create_all covers both).
    assert HARNESS_TABLES <= registered


def test_source_document_to_parsed_jd_fk_defined() -> None:
    fks = models.ParsedJDRow.__table__.c.source_document_id.foreign_keys
    targets = {fk.target_fullname for fk in fks}
    assert "source_documents.id" in targets


def test_canonical_jd_lineage_fks_defined() -> None:
    canon = models.CanonicalJD.__table__
    cluster_fk = {fk.target_fullname for fk in canon.c.cluster_id.foreign_keys}
    report_fk = {fk.target_fullname for fk in canon.c.validation_report_id.foreign_keys}
    assert "clusters.id" in cluster_fk
    assert "validation_reports.id" in report_fk


def test_enums_expose_expected_values() -> None:
    assert set(models.DedupTier) == {
        models.DedupTier.EXACT,
        models.DedupTier.NEAR_DUPLICATE,
        models.DedupTier.ROLE_EQUIVALENT,
    }
    assert models.CanonicalStatus.DRAFT.value == "draft"
    assert models.ReviewActionKind.OVERRIDE.value == "override"
    assert models.IssueSeverity.BLOCKING.value == "blocking"
    assert models.DocumentFormat.DOC.value == "doc"


def _load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "jd_bank_initial_migration", MIGRATION_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_initial_migration_is_well_formed() -> None:
    module = _load_migration()
    assert isinstance(module.revision, str) and module.revision
    assert module.down_revision is None
    assert callable(module.upgrade)
    assert callable(module.downgrade)

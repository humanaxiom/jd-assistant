"""Integration tests — JD Bank schema on a real Postgres via testcontainers.

Applies the *actual* Alembic migration (``alembic upgrade head``) to a fresh
Postgres, then round-trips the full provenance lineage across the FK chain and
asserts a JSONB payload survives the trip. A fresh, module-local container is
used (not the shared ``pg_url`` from ``test_stores.py``) so the migration owns a
clean database and cannot collide with ``Base.metadata.create_all`` elsewhere.

The migration runs in the synchronous module-scoped fixture (no running event
loop), so Alembic's ``env.py`` is free to call ``asyncio.run`` for its async
engine.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from testcontainers.postgres import PostgresContainer

from src.jd_bank.db.models import (
    AuditLog,
    CanonicalJD,
    CanonicalStatus,
    Cluster,
    DedupEdge,
    DedupTier,
    DocumentFormat,
    ParsedJDRow,
    ReviewAction,
    ReviewActionKind,
    SourceDocument,
    ValidationReport,
)

CORE_DIR = Path(__file__).resolve().parents[2]
ALEMBIC_INI = CORE_DIR / "alembic.ini"


@pytest.fixture(scope="module")
def migrated_pg_url() -> Iterator[str]:
    """A fresh Postgres with the full schema applied via Alembic."""
    with PostgresContainer("postgres:16-alpine") as pg:
        url = pg.get_connection_url().replace("psycopg2", "asyncpg")
        cfg = Config(str(ALEMBIC_INI))
        cfg.set_main_option("sqlalchemy.url", url)
        command.upgrade(cfg, "head")
        yield url


@pytest.mark.asyncio
async def test_alembic_created_all_tables(migrated_pg_url: str) -> None:
    engine = create_async_engine(migrated_pg_url)
    async with engine.connect() as conn:
        rows = await conn.exec_driver_sql(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
        )
        tables = {r[0] for r in rows}
    await engine.dispose()

    expected = {
        "tasks",
        "runs",
        "gate_results",
        "source_documents",
        "parsed_jds",
        "validation_reports",
        "dedup_edges",
        "clusters",
        "canonical_jds",
        "review_actions",
        "audit_log",
        "alembic_version",
    }
    assert expected <= tables


@pytest.mark.asyncio
async def test_provenance_lineage_and_jsonb_roundtrip(migrated_pg_url: str) -> None:
    engine = create_async_engine(migrated_pg_url)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)

    parsed_payload = {
        "title": "Research Analyst",
        "employee_group": "apsa",
        "duties": [{"action_verb": "Analyze", "statement": "data", "how_why": ["x"]}],
    }

    async with session_maker() as session:
        doc_a = SourceDocument(
            storage_ref="archive/jd_a.docx",
            filename="jd_a.docx",
            sha256="a" * 64,
            fmt=DocumentFormat.DOCX,
            byte_size=2048,
            ingest_metadata={"walker": "v1", "source": "SFU_JDs"},
            normalization_report={"names_removed": ["Jane Doe"]},
        )
        doc_b = SourceDocument(
            storage_ref="archive/jd_b.doc",
            sha256="b" * 64,
            fmt=DocumentFormat.DOC,
            byte_size=1024,
        )
        session.add_all([doc_a, doc_b])
        await session.flush()

        parsed = ParsedJDRow(
            source_document_id=doc_a.id,
            parsed=parsed_payload,
            parser_version="parser-1.0",
            parse_confidence=0.92,
        )
        session.add(parsed)
        await session.flush()

        report = ValidationReport(
            parsed_jd_id=parsed.id,
            version=1,
            issues=[
                {
                    "code": "SFU-COMP-SUMMARY",
                    "severity": "blocking",
                    "section": "position_summary",
                    "evidence": "missing summary",
                }
            ],
            gate_results={"SFU-COMP-SUMMARY": {"passed": False}},
            passed=False,
            rules_version="rules-1.0",
        )
        session.add(report)

        edge = DedupEdge(
            source_a_id=doc_a.id,
            source_b_id=doc_b.id,
            tier=DedupTier.EXACT,
            score=1.0,
            method="sha256",
        )
        session.add(edge)

        cluster = Cluster(
            label="Research Analyst",
            employee_group="apsa",
            level_band="A",
            members=[{"source_document_id": str(doc_a.id)}],
            constraint_metadata={"employee_group": "apsa", "level_band": "A"},
        )
        session.add(cluster)
        await session.flush()

        canonical = CanonicalJD(
            cluster_id=cluster.id,
            version=1,
            status=CanonicalStatus.DRAFT,
            content=parsed_payload,
            source_document_ids=[{"id": str(doc_a.id)}],
            validation_report_id=report.id,
        )
        session.add(canonical)
        await session.flush()

        action = ReviewAction(
            canonical_jd_id=canonical.id,
            action=ReviewActionKind.OVERRIDE,
            reviewer_id="hr-reviewer-1",
            reason="Blocking gate overridden with documented justification.",
            payload={"gate": "SFU-COMP-SUMMARY"},
        )
        session.add(action)
        session.add(
            AuditLog(
                event_type="canonical.override",
                entity_type="canonical_jds",
                entity_id=canonical.id,
                actor="hr-reviewer-1",
                payload={"reason": "documented"},
            )
        )
        await session.commit()

        canonical_id = canonical.id
        doc_a_id = doc_a.id

    # Fresh session: verify the lineage and JSONB survived the round-trip.
    async with session_maker() as session:
        fetched = await session.get(CanonicalJD, canonical_id)
        assert fetched is not None
        assert fetched.status == CanonicalStatus.DRAFT

        # JSONB round-trip (nested list/dict preserved).
        assert fetched.content["duties"][0]["action_verb"] == "Analyze"

        # Relationship traversal via AsyncAttrs proves the FK graph is wired.
        cluster_obj = await fetched.awaitable_attrs.cluster
        assert cluster_obj.employee_group == "apsa"
        actions = await fetched.awaitable_attrs.review_actions
        assert len(actions) == 1
        assert actions[0].action == ReviewActionKind.OVERRIDE
        assert actions[0].reason is not None

        # source_document -> parsed_jd -> validation_report chain intact.
        parsed_row = (
            await session.execute(
                select(ParsedJDRow).where(ParsedJDRow.source_document_id == doc_a_id)
            )
        ).scalar_one()
        assert parsed_row.parsed["title"] == "Research Analyst"
        report_row = (
            await session.execute(
                select(ValidationReport).where(
                    ValidationReport.parsed_jd_id == parsed_row.id
                )
            )
        ).scalar_one()
        assert report_row.issues[0]["severity"] == "blocking"

        audit_count = (
            await session.execute(select(func.count()).select_from(AuditLog))
        ).scalar_one()
        assert audit_count >= 1

    await engine.dispose()


@pytest.mark.asyncio
async def test_fk_integrity_is_enforced(migrated_pg_url: str) -> None:
    """A parsed_jd pointing at a non-existent source document must be rejected."""
    engine = create_async_engine(migrated_pg_url)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    async with session_maker() as session:
        orphan = ParsedJDRow(
            source_document_id=uuid.uuid4(),  # no such source document
            parsed={"title": "Orphan"},
            parser_version="parser-1.0",
            parse_confidence=0.1,
        )
        session.add(orphan)
        with pytest.raises(IntegrityError):
            await session.commit()
    await engine.dispose()

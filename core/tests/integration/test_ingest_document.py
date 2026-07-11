"""Integration tests — ``ingest_document`` against the real 1.2 schema.

Applies the actual Alembic migration to a fresh Postgres (testcontainers), then
ingests real archive formats and asserts the persisted ``source_documents`` row
carries the correct sha256 / format / normalization report, that a duplicate
sha256 is handled gracefully, and that an unsupported format is routed to a
manual-triage row rather than crashing.
"""

from __future__ import annotations

from collections.abc import Iterator
from io import BytesIO
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from docx import Document
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from testcontainers.postgres import PostgresContainer

from src.jd_bank.db.models import DocumentFormat, SourceDocument
from src.jd_bank.ingest.ingest import compute_sha256, ingest_document

CORE_DIR = Path(__file__).resolve().parents[2]
ALEMBIC_INI = CORE_DIR / "alembic.ini"
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


@pytest.fixture(scope="module")
def migrated_pg_url() -> Iterator[str]:
    with PostgresContainer("postgres:16-alpine") as pg:
        url = pg.get_connection_url().replace("psycopg2", "asyncpg")
        cfg = Config(str(ALEMBIC_INI))
        cfg.set_main_option("sqlalchemy.url", url)
        command.upgrade(cfg, "head")
        yield url


def _docx_bytes(paragraphs: list[str]) -> bytes:
    doc = Document()
    for line in paragraphs:
        doc.add_paragraph(line)
    buf = BytesIO()
    doc.save(buf)
    return buf.getvalue()


@pytest.mark.asyncio
async def test_ingest_docx_persists_row(migrated_pg_url: str) -> None:
    engine = create_async_engine(migrated_pg_url)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)

    data = _docx_bytes(
        [
            "NAME OF EMPLOYEE: Jane Doe",
            "POSITION SUMMARY",
            "The Research Analyst compiles data. Reach jane@example.com.",
        ]
    )
    async with session_maker() as session:
        doc = await ingest_document(
            session,
            filename="20191128_00119031_JDFN_APSA.docx",
            data=data,
            storage_ref="archive/20191128_00119031_JDFN_APSA.docx",
        )
        await session.commit()
        doc_id = doc.id

    async with session_maker() as session:
        row = await session.get(SourceDocument, doc_id)
        assert row is not None
        assert row.sha256 == compute_sha256(data)
        assert row.fmt == DocumentFormat.DOCX
        assert row.byte_size == len(data)
        assert row.ingest_metadata["status"] == "ingested"
        assert row.ingest_metadata["original_extension"] == "docx"
        # Normalization ran and reported the incumbent name + email.
        assert row.normalization_report["names_removed"] == 1
        assert row.normalization_report["emails_removed"] == 1
        assert row.normalization_report["total_removed"] >= 2

    await engine.dispose()


@pytest.mark.asyncio
async def test_ingest_legacy_doc_via_antiword(migrated_pg_url: str) -> None:
    engine = create_async_engine(migrated_pg_url)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    data = (FIXTURES / "sample_legacy.doc").read_bytes()

    async with session_maker() as session:
        doc = await ingest_document(
            session,
            filename="19820219_00001211Systems_consultantII.doc",
            data=data,
            storage_ref="archive/19820219_00001211Systems_consultantII.doc",
        )
        await session.commit()
        assert doc.fmt == DocumentFormat.DOC
        assert doc.ingest_metadata["status"] == "ingested"
        assert doc.ingest_metadata["char_count"] > 0
    await engine.dispose()


@pytest.mark.asyncio
async def test_duplicate_sha256_returns_existing_row(migrated_pg_url: str) -> None:
    engine = create_async_engine(migrated_pg_url)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    data = b"Position Summary: identical bytes for a duplicate ingest test.\n"

    async with session_maker() as session:
        first = await ingest_document(
            session, filename="dup.txt", data=data, storage_ref="archive/dup1.txt"
        )
        await session.commit()
        first_id = first.id

    async with session_maker() as session:
        again = await ingest_document(
            session, filename="dup_copy.txt", data=data, storage_ref="archive/dup2.txt"
        )
        await session.commit()
        assert again.id == first_id  # same row, not a new one

        count = await session.scalar(
            select(func.count())
            .select_from(SourceDocument)
            .where(SourceDocument.sha256 == compute_sha256(data))
        )
        assert count == 1
    await engine.dispose()


@pytest.mark.asyncio
async def test_unsupported_format_routed_to_manual(migrated_pg_url: str) -> None:
    engine = create_async_engine(migrated_pg_url)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)

    async with session_maker() as session:
        doc = await ingest_document(
            session,
            filename="scan_only.tif",
            data=b"\x00\x01\x02fake-image-bytes",
            storage_ref="archive/scan_only.tif",
        )
        await session.commit()
        assert doc.fmt == DocumentFormat.OTHER
        assert doc.ingest_metadata["status"] == "unsupported"
        assert doc.normalization_report == {}
    await engine.dispose()


@pytest.mark.asyncio
async def test_corrupt_supported_format_routed_to_failed(migrated_pg_url: str) -> None:
    """A .docx that won't parse must not crash the worker — it gets a ``failed``
    row for manual triage (DoS hardening)."""
    engine = create_async_engine(migrated_pg_url)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)

    async with session_maker() as session:
        doc = await ingest_document(
            session,
            filename="20200101_broken.docx",
            data=b"PK\x03\x04 not really a docx zip",
            storage_ref="archive/20200101_broken.docx",
        )
        await session.commit()
        assert doc.fmt == DocumentFormat.DOCX
        assert doc.ingest_metadata["status"] == "failed"
        assert "reason" in doc.ingest_metadata
        assert doc.normalization_report == {}
    await engine.dispose()

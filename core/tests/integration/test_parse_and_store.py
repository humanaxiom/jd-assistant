"""Integration test — ``parse_and_store`` against the real Alembic schema.

Applies the actual migration to a fresh Postgres (testcontainers), ingests a
source document, then parses a fixture and persists a ``parsed_jds`` row.
Asserts: the FK back to ``source_documents``, a JSONB round-trip of the
``SFUJobDescription`` (rehydrates via the pydantic model), the ``parser_version``
stamp, and a plausible ``parse_confidence``.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from testcontainers.postgres import PostgresContainer

from src.jd_bank.db.models import ParsedJDRow
from src.jd_bank.ingest.ingest import ingest_document
from src.jd_core.models.parsed_jd import SFUJobDescription
from src.jd_core.parser import parse_and_store, parse_jd

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


@pytest.mark.asyncio
async def test_parse_and_store_persists_parsed_jd(migrated_pg_url: str) -> None:
    engine = create_async_engine(migrated_pg_url)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    text = (FIXTURES / "sfu_new_template.txt").read_text(encoding="utf-8")
    expected = parse_jd(text)

    async with session_maker() as session:
        source = await ingest_document(
            session,
            filename="sfu_new_template.txt",
            data=text.encode("utf-8"),
            storage_ref="archive/sfu_new_template.txt",
        )
        row = await parse_and_store(session, source, text)
        await session.commit()
        row_id = row.id
        source_id = source.id

    async with session_maker() as session:
        stored = await session.get(ParsedJDRow, row_id)
        assert stored is not None
        # FK lineage back to the source document.
        assert stored.source_document_id == source_id
        assert stored.parser_version == "jd_segmenter_v1"
        assert 0.0 < stored.parse_confidence <= 1.0
        assert stored.parse_confidence == pytest.approx(expected.parse_confidence)

        # JSONB round-trips through the pydantic contract without loss.
        rehydrated = SFUJobDescription.model_validate(stored.parsed)
        assert rehydrated.title == "Manager, Special Projects"
        assert rehydrated.employee_group == "apsa"
        assert rehydrated.territorial_acknowledgement_present is True
        assert len(rehydrated.duties) >= 3
        assert {"education", "knowledge", "skill", "ability"} <= {
            q.kind for q in rehydrated.qualifications
        }

    await engine.dispose()


@pytest.mark.asyncio
async def test_parse_and_store_legacy_doc(migrated_pg_url: str) -> None:
    """End-to-end on the real OLD-era .doc: extract → ingest → parse → persist."""
    from src.jd_bank.ingest.extract import extract_text_from_path

    engine = create_async_engine(migrated_pg_url)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    data = (FIXTURES / "sample_legacy.doc").read_bytes()
    text = extract_text_from_path(FIXTURES / "sample_legacy.doc")

    async with session_maker() as session:
        source = await ingest_document(
            session,
            filename="19820219_00001211Systems_consultantII.doc",
            data=data,
            storage_ref="archive/19820219_00001211Systems_consultantII.doc",
        )
        row = await parse_and_store(session, source, text)
        await session.commit()
        row_id = row.id

    async with session_maker() as session:
        stored = await session.get(ParsedJDRow, row_id)
        assert stored is not None
        rehydrated = SFUJobDescription.model_validate(stored.parsed)
        assert rehydrated.title == "Systems Analyst II"
        assert stored.parse_confidence > 0.0

    await engine.dispose()


@pytest.mark.asyncio
async def test_parse_and_store_flush_populates_pk(migrated_pg_url: str) -> None:
    """The row PK is available after ``parse_and_store`` (it flushes)."""
    engine = create_async_engine(migrated_pg_url)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    text = (FIXTURES / "sfu_old_template.txt").read_text(encoding="utf-8")

    async with session_maker() as session:
        source = await ingest_document(
            session,
            filename="sfu_old_template.txt",
            data=text.encode("utf-8"),
            storage_ref="archive/sfu_old_template.txt",
        )
        row = await parse_and_store(session, source, text)
        assert row.id is not None
        assert row.source_document_id == source.id
        await session.rollback()

    await engine.dispose()

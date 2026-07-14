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
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from docx import Document
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from testcontainers.postgres import PostgresContainer

from src.jd_bank.db.models import DocumentFormat, SourceDocument
from src.jd_bank.ingest import ingest as ingest_mod
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
        outcome = await ingest_document(
            session,
            filename="20191128_00119031_JDFN_APSA.docx",
            data=data,
            storage_ref="archive/20191128_00119031_JDFN_APSA.docx",
        )
        await session.commit()
        doc_id = outcome.document.id
        assert outcome.text is not None
        assert "Jane Doe" not in outcome.text
        assert "jane@example.com" not in outcome.text

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
        outcome = await ingest_document(
            session,
            filename="19820219_00001211Systems_consultantII.doc",
            data=data,
            storage_ref="archive/19820219_00001211Systems_consultantII.doc",
        )
        await session.commit()
        assert outcome.document.fmt == DocumentFormat.DOC
        assert outcome.document.ingest_metadata["status"] == "ingested"
        assert outcome.document.ingest_metadata["char_count"] > 0
        assert outcome.text is not None and len(outcome.text) > 0
    await engine.dispose()


@pytest.mark.asyncio
async def test_a_duplicate_sha256_gets_its_own_row(migrated_pg_url: str) -> None:
    """**The 3.1 provenance fix.** ``source_documents`` is a faithful ledger of the
    archive: ONE ROW PER FILE.

    It used to be the opposite. ``sha256`` was ``unique=True`` and ``ingest_document``
    returned the *existing* row on a duplicate hash — so of the **3,009** archive files
    that sit in an exact-duplicate group, **1,972** would have been ingested and their
    filenames **discarded entirely**: no row, no record they ever existed. "Which
    archive files produced this canonical JD?" was unanswerable, and
    ``DedupTier.EXACT`` / ``DedupEdge`` were dead code (an edge needs two
    ``source_id``s and the duplicate never got one).

    Dedup is now a **finding**, expressed as edges (:mod:`src.jd_bank.dedup`) — never
    a silent write-time collapse.
    """
    engine = create_async_engine(migrated_pg_url)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    data = b"Position Summary: identical bytes for a duplicate ingest test.\n"

    async with session_maker() as session:
        first = await ingest_document(
            session, filename="dup.txt", data=data, storage_ref="archive/dup1.txt"
        )
        await session.commit()
        first_id = first.document.id

    async with session_maker() as session:
        again = await ingest_document(
            session, filename="dup_copy.txt", data=data, storage_ref="archive/dup2.txt"
        )
        await session.commit()
        assert again.document.id != first_id  # a DIFFERENT row — filename survives

        rows = (
            await session.scalars(
                select(SourceDocument)
                .where(SourceDocument.sha256 == compute_sha256(data))
                .order_by(SourceDocument.storage_ref)
            )
        ).all()
        assert [row.filename for row in rows] == ["dup.txt", "dup_copy.txt"]
    await engine.dispose()


@pytest.mark.asyncio
async def test_re_ingesting_the_same_file_does_not_double_insert(
    migrated_pg_url: str,
) -> None:
    """**The idempotency key is ``(storage_ref, sha256)``** — "this exact content, at
    this exact location, is one ledger row".

    Dropping the unique ``sha256`` removed what used to make a re-run safe, so the key
    had to be replaced, not deleted. ``storage_ref`` *alone* would have been wrong: if
    the bytes at a path ever change, the only ways to honour a unique ``storage_ref``
    are to UPDATE the row in place — silently re-pointing the ``parsed_jds`` that
    already hang off it at bytes that no longer produced them, which is a provenance
    lie — or to raise. Keying on the pair instead means a changed file gets a *new*
    row and the old one keeps its lineage intact.
    """
    engine = create_async_engine(migrated_pg_url)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    data = b"Position Summary: re-ingest me.\n"
    ref = "archive/idempotent.txt"

    async with session_maker() as session:
        first = await ingest_document(
            session, filename="idempotent.txt", data=data, storage_ref=ref
        )
        await session.commit()
        first_id = first.document.id
        assert first.text is not None  # freshly extracted this call

    async with session_maker() as session:
        again = await ingest_document(
            session, filename="idempotent.txt", data=data, storage_ref=ref
        )
        await session.commit()
        assert again.document.id == first_id
        assert again.text is None  # the row already existed — nothing re-extracted

        count = await session.scalar(
            select(func.count())
            .select_from(SourceDocument)
            .where(SourceDocument.storage_ref == ref)
        )
        assert count == 1
    await engine.dispose()


@pytest.mark.asyncio
async def test_changed_bytes_at_the_same_ref_are_a_new_row_not_an_overwrite(
    migrated_pg_url: str,
) -> None:
    """The other half of the key. The archive is read-only so this is hypothetical
    today — but it is the case that decides between the two candidate keys, and
    overwriting would corrupt the lineage of anything already parsed from the old
    bytes."""
    engine = create_async_engine(migrated_pg_url)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    ref = "archive/revised.txt"

    async with session_maker() as session:
        old = await ingest_document(
            session, filename="revised.txt", data=b"version one\n", storage_ref=ref
        )
        new = await ingest_document(
            session, filename="revised.txt", data=b"version two\n", storage_ref=ref
        )
        await session.commit()
        assert old.document.id != new.document.id
        assert old.document.sha256 != new.document.sha256
    await engine.dispose()


@pytest.mark.asyncio
async def test_a_racing_insert_of_the_same_file_does_not_poison_the_session(
    migrated_pg_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The race path (``ingest._insert``'s ``IntegrityError`` branch), and the
    half-updated concurrency story 3.1 had to finish.

    The old handler called ``session.rollback()`` — which rolls back the CALLER'S whole
    transaction, throwing away every other document the caller had staged in it. In a
    batch ingest committing every 200 files, one lost race would discard up to 199
    other files' work and report success. The conflicting INSERT is therefore wrapped
    in a SAVEPOINT (``session.begin_nested()``), so losing the race costs exactly one
    row.

    ⚠️ **This test used to be THEATRE, and a reviewer caught it by mutation.** It had
    the racer ``commit()`` first and then simply called ``ingest_document`` on the
    writer — but the writer's *pre-check* (``_existing``) then finds the committed row
    and returns early, so ``_insert`` is never called and the ``IntegrityError`` branch
    is never reached. It asserted the staged row survived while **nothing ever
    threatened it**: swapping the SAVEPOINT for 3.1's verbatim naked-``rollback()`` bug
    left the whole suite green.

    The real race is a *window*: the winner commits **between** the loser's pre-check
    and its INSERT. Real concurrency reaches it by interleaving; here it is forced
    deterministically by making the pre-check miss exactly once — which is precisely
    what a concurrent committer does to it. (Same pattern as
    ``test_parse_and_store.py``'s racing-parse test.)
    """
    engine = create_async_engine(migrated_pg_url)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    data = b"Position Summary: raced.\n"
    ref = "archive/raced.txt"

    # The winner commits the row first, behind the loser's back.
    async with session_maker() as racer:
        won = await ingest_document(
            racer, filename="raced.txt", data=data, storage_ref=ref
        )
        await racer.commit()
        winner_id = won.document.id

    async with session_maker() as writer:
        # The writer stages OTHER work FIRST — before the patch, so this call's own
        # pre-check is the real one.
        earlier = await ingest_document(
            writer,
            filename="earlier.txt",
            data=b"unrelated, staged before the race\n",
            storage_ref="archive/earlier.txt",
        )
        earlier_id = earlier.document.id

        real_existing = ingest_mod._existing
        calls = {"n": 0}

        async def _blind_once(
            session: AsyncSession, **kwargs: Any
        ) -> SourceDocument | None:
            """Miss on the pre-check (the race window), then behave normally — which is
            what `_insert`'s IntegrityError handler needs to find the winner."""
            calls["n"] += 1
            if calls["n"] == 1:
                return None
            return await real_existing(session, **kwargs)

        monkeypatch.setattr(ingest_mod, "_existing", _blind_once)

        # ...then loses the race: pre-check misses, INSERT hits uq_source_ref_sha256.
        lost = await ingest_document(
            writer, filename="raced.txt", data=data, storage_ref=ref
        )
        assert calls["n"] >= 2  # the IntegrityError branch really did re-select
        assert lost.document.id == winner_id  # the winner's row, not a crash
        assert lost.text is None  # a row this call did not create carries no text
        await writer.commit()

    monkeypatch.undo()

    async with session_maker() as session:
        # The staged, unrelated document SURVIVED the race — a naked rollback()
        # would have discarded it. THIS is the assertion that had nothing behind it.
        survived = await session.get(SourceDocument, earlier_id)
        assert survived is not None
        assert survived.filename == "earlier.txt"

        count = await session.scalar(
            select(func.count())
            .select_from(SourceDocument)
            .where(SourceDocument.storage_ref == ref)
        )
        assert count == 1
    await engine.dispose()


@pytest.mark.asyncio
async def test_unsupported_format_routed_to_manual(migrated_pg_url: str) -> None:
    engine = create_async_engine(migrated_pg_url)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)

    async with session_maker() as session:
        outcome = await ingest_document(
            session,
            filename="scan_only.tif",
            data=b"\x00\x01\x02fake-image-bytes",
            storage_ref="archive/scan_only.tif",
        )
        await session.commit()
        assert outcome.document.fmt == DocumentFormat.OTHER
        assert outcome.document.ingest_metadata["status"] == "unsupported"
        assert outcome.document.normalization_report == {}
        assert outcome.text is None
    await engine.dispose()


@pytest.mark.asyncio
async def test_corrupt_supported_format_routed_to_failed(migrated_pg_url: str) -> None:
    """A .docx that won't parse must not crash the worker — it gets a ``failed``
    row for manual triage (DoS hardening)."""
    engine = create_async_engine(migrated_pg_url)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)

    async with session_maker() as session:
        outcome = await ingest_document(
            session,
            filename="20200101_broken.docx",
            data=b"PK\x03\x04 not really a docx zip",
            storage_ref="archive/20200101_broken.docx",
        )
        await session.commit()
        assert outcome.document.fmt == DocumentFormat.DOCX
        assert outcome.document.ingest_metadata["status"] == "failed"
        assert "reason" in outcome.document.ingest_metadata
        assert outcome.document.normalization_report == {}
        assert outcome.text is None
    await engine.dispose()

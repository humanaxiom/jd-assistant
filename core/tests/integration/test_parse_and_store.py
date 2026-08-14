"""Integration test — ``parse_and_store`` against the real Alembic schema.

Applies the actual migration to a fresh Postgres (testcontainers), ingests a
source document, then parses a fixture and persists a ``parsed_jds`` row.
Asserts: the FK back to ``source_documents``, a JSONB round-trip of the
``SFUJobDescription`` (rehydrates via the pydantic model), the ``parser_version``
stamp, and a plausible ``parse_confidence``.

**And its IDEMPOTENCY, directly** (Phase 3.2a, LANDMINE 1, migration ``0003``). The
two tests at the bottom of this file exist because a reviewer proved the first cut of
3.2a did not have them: reverting ``parse_and_store`` to its old unconditional
``session.add`` left the WHOLE suite green — the driver's own
``test_running_the_driver_twice_changes_nothing`` was carried entirely by the driver's
``_already_parsed()`` guard, which short-circuits before ``parse_and_store`` is ever
called a second time. The function's idempotency and its ``IntegrityError``/SAVEPOINT
branch were untested, and with the driver guard also gone the constraint raised an
unhandled ``IntegrityError`` that escaped ``run_archive_ingest`` and killed the run.
Pin the unit, not just its caller.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from testcontainers.postgres import PostgresContainer

from src.jd_bank.db.models import ParsedJDRow, SourceDocument
from src.jd_bank.ingest.ingest import ingest_document
from src.jd_bank.ingest.parse_store import parse_and_store
from src.jd_core.models.parsed_jd import SFUJobDescription
from src.jd_core.parser import parse_jd

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
        source = (
            await ingest_document(
                session,
                filename="sfu_new_template.txt",
                data=text.encode("utf-8"),
                storage_ref="archive/sfu_new_template.txt",
            )
        ).document
        row = await parse_and_store(session, source, text)
        await session.commit()
        row_id = row.id
        source_id = source.id

    async with session_maker() as session:
        stored = await session.get(ParsedJDRow, row_id)
        assert stored is not None
        # FK lineage back to the source document.
        assert stored.source_document_id == source_id
        assert stored.parser_version == "jd_segmenter_v4"
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
        source = (
            await ingest_document(
                session,
                filename="19820219_00001211Systems_consultantII.doc",
                data=data,
                storage_ref="archive/19820219_00001211Systems_consultantII.doc",
            )
        ).document
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
        source = (
            await ingest_document(
                session,
                filename="sfu_old_template.txt",
                data=text.encode("utf-8"),
                storage_ref="archive/sfu_old_template.txt",
            )
        ).document
        row = await parse_and_store(session, source, text)
        assert row.id is not None
        assert row.source_document_id == source.id
        await session.rollback()

    await engine.dispose()


@pytest.mark.asyncio
async def test_parsing_the_same_document_twice_returns_the_same_row(
    migrated_pg_url: str,
) -> None:
    """**LANDMINE 1, pinned on the FUNCTION** (not on the driver that calls it).

    The parse is a pure function of ``(source bytes, parser_version)``, so re-parsing
    the same document at the same parser version must return the row that already
    exists — never insert a second one. Before migration ``0003`` + the idempotent
    rewrite, a re-run of the archive driver produced 29,130 ``parsed_jds`` rows instead
    of 14,565, each with a fresh UUID, orphaning every Phase-3.2b vector keyed off
    them.

    **The mutation this detects:** revert ``parse_and_store`` to its old body — the
    unconditional ``session.add`` + ``flush``, with **no** pre-check and **no**
    ``IntegrityError``/SAVEPOINT handler. Then the second call's INSERT hits
    ``uq_parsed_source_parser`` and escapes as an unhandled ``UniqueViolationError``.

    **The mutation it does NOT detect, stated so nobody trusts it to:** deleting *only*
    the select-by-key pre-check, while keeping the SAVEPOINT handler, leaves this test
    **green** — the handler catches the ``IntegrityError`` and returns the winner, so
    one row and the same id still come back. (It is wasteful, not wrong: it re-parses
    and burns a savepoint per call.) The pre-check is the fast path; the handler is the
    correctness guarantee. This test pins the *contract* (one row, same id); the
    handler itself is pinned by
    ``test_a_racing_parse_of_the_same_document_does_not_poison_the_session``, which
    reds when the SAVEPOINT is swapped for a naked ``rollback()``.
    """
    engine = create_async_engine(migrated_pg_url)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    text = (FIXTURES / "sfu_new_template.txt").read_text(encoding="utf-8")
    ref = "archive/parse_twice.txt"

    async with session_maker() as session:
        source = (
            await ingest_document(
                session,
                filename="parse_twice.txt",
                data=text.encode("utf-8"),
                storage_ref=ref,
            )
        ).document
        first = await parse_and_store(session, source, text)
        await session.commit()
        first_id = first.id

    # ...and again, in a fresh transaction, exactly as a re-run of the driver would.
    async with session_maker() as session:
        source_again = await session.get(SourceDocument, source.id)
        assert source_again is not None
        second = await parse_and_store(session, source_again, text)
        await session.commit()
        assert second.id == first_id  # the SAME row came back, not a new one

        count = await session.scalar(
            select(func.count())
            .select_from(ParsedJDRow)
            .where(ParsedJDRow.source_document_id == source.id)
        )
        assert count == 1

    await engine.dispose()


@pytest.mark.asyncio
async def test_a_racing_parse_of_the_same_document_does_not_poison_the_session(
    migrated_pg_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The SAVEPOINT branch — the sibling of ``test_ingest_document.py``'s
    ``test_a_racing_insert_of_the_same_file_does_not_poison_the_session``, and the bug
    Phase 3.1 spent a whole migration learning.

    A bare ``session.rollback()`` in the ``IntegrityError`` handler rolls back the
    CALLER'S WHOLE TRANSACTION — silently discarding every other document staged in it.
    In a batch ingest committing every 200 files, one lost race would throw away up to
    199 other files' work and report success. ``parse_and_store`` therefore does its
    INSERT inside ``session.begin_nested()``, so losing the race costs exactly the one
    row.

    Forcing the race deterministically: the loser's pre-check must miss the row that
    the winner has *already committed*. Real concurrency gets there by interleaving; we
    get there by making the pre-check return ``None`` exactly once, which is precisely
    the window a concurrent committer opens.
    """
    engine = create_async_engine(migrated_pg_url)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    text = (FIXTURES / "sfu_new_template.txt").read_text(encoding="utf-8")

    async with session_maker() as setup:
        contested = (
            await ingest_document(
                setup,
                filename="raced.txt",
                data=text.encode("utf-8"),
                storage_ref="archive/raced_parse.txt",
            )
        ).document
        await setup.commit()
        contested_id = contested.id

    # The winner parses it and commits, behind the loser's back.
    async with session_maker() as winner:
        won = await parse_and_store(winner, contested, text)
        await winner.commit()
        winner_row_id = won.id

    import src.jd_bank.ingest.parse_store as store

    real_existing = store._existing
    calls = {"n": 0}

    async def _blind_once(session: AsyncSession, **kwargs: Any) -> ParsedJDRow | None:
        """Miss on the pre-check (the race window), then behave normally."""
        calls["n"] += 1
        if calls["n"] == 1:
            return None
        return await real_existing(session, **kwargs)

    monkeypatch.setattr(store, "_existing", _blind_once)

    async with session_maker() as loser:
        # The loser has ALREADY staged other work in its transaction...
        staged = (
            await ingest_document(
                loser,
                filename="earlier.txt",
                data=b"unrelated, staged before the race\n",
                storage_ref="archive/earlier_parse.txt",
            )
        ).document
        staged_id = staged.id

        # ...then loses the race on the parse.
        contested_row = await loser.get(SourceDocument, contested_id)
        assert contested_row is not None
        lost = await parse_and_store(loser, contested_row, text)
        assert lost.id == winner_row_id  # the winner's row came back, not a crash
        await loser.commit()

    monkeypatch.undo()

    async with session_maker() as check:
        # The staged, unrelated document SURVIVED the race — a naked rollback() in the
        # IntegrityError handler would have discarded it.
        survived = await check.get(SourceDocument, staged_id)
        assert survived is not None
        assert survived.filename == "earlier.txt"

        # ...and the contested document still has exactly ONE parse.
        count = await check.scalar(
            select(func.count())
            .select_from(ParsedJDRow)
            .where(ParsedJDRow.source_document_id == contested_id)
        )
        assert count == 1

    await engine.dispose()

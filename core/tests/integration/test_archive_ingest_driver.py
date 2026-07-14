"""Integration tests — the Phase 3.2a archive -> Postgres ingest driver, against the
real Alembic schema (testcontainers).

Pins the two landmines the driver exists to close:

1. **Idempotency** (LANDMINE 1) — running the driver twice over the same archive must
   not double ``parsed_jds``. This was RED before migration ``0003`` +
   ``jd_core.parser.store``'s idempotent rewrite: ``parse_and_store`` did an
   unconditional insert and the table carried no unique constraint at all.
2. **No incumbent names cross into ``parsed_jds``** (LANDMINE 2) — the obvious driver
   (parse the raw extracted text) would have handed the parser text `ingest_document`
   had already scrubbed and then discarded. This was RED before ``ingest_document``
   started returning the incumbent-normalized text via ``IngestOutcome``.

Plus: an unextractable file gets a ``failed`` row and no parse (no silent drops), and
a resumed/partial run (ingested earlier, never parsed) extracts on demand rather than
silently doing nothing.
"""

from __future__ import annotations

import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from testcontainers.postgres import PostgresContainer

from src.jd_bank.db.models import ParsedJDRow, SourceDocument
from src.jd_bank.ingest.driver import run_archive_ingest
from src.jd_bank.ingest.ingest import compute_sha256, ingest_document

CORE_DIR = Path(__file__).resolve().parents[2]
ALEMBIC_INI = CORE_DIR / "alembic.ini"
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"

#: The incumbent identity that must NEVER reach ``parsed_jds`` — on ANY path.
_PII = ("Jane Doe", "John Q. Public", "jane@example.com", "604-555-0199")


def _incumbent_laced_jd() -> str:
    """``sfu_new_template.txt`` with an incumbent's name, incumbent field and contact
    details spliced into POSITION SUMMARY.

    Two properties make this the right fixture, and both were arrived at the hard way:

    * It **trips the scrubber** — ``NAME OF EMPLOYEE:`` / ``INCUMBENT:`` are the exact
      field-label shapes ``test_ingest_scrub.py`` pins, and the email/phone matchers
      catch the rest.
    * It **reaches the parsed row when unscrubbed** — POSITION SUMMARY is stored close
      to verbatim on the parsed model (``segmenter._clean`` only collapses whitespace).
      An earlier cut of this fixture put the same lines in IDENTIFICATION, where the
      segmenter simply *discards* lines it does not recognise as labelled fields — so
      the PII never reached ``parsed`` whether it was scrubbed or not, and the test
      passed against a driver that fed the parser RAW text. A test that cannot fail is
      not a test.
    """
    base = (FIXTURES / "sfu_new_template.txt").read_text(encoding="utf-8")
    laced = base.replace(
        "POSITION SUMMARY\n",
        "POSITION SUMMARY\n"
        "NAME OF EMPLOYEE: Jane Doe\n"
        "INCUMBENT: John Q. Public\n"
        "Contact: jane@example.com or 604-555-0199.\n",
        1,
    )
    assert laced != base  # the splice actually landed
    return laced


def _assert_scrubbed(parsed: object) -> None:
    """No incumbent identity anywhere in the parsed JSONB — and the JD itself survived.

    From Phase 3.2b this content is embedded on ``aria-gb10-2`` across a private
    network. These are SFU HR records; FIPPA applies. The parsed row is the thing that
    gets embedded, so it is the thing that must be clean.
    """
    blob = str(parsed)
    for secret in _PII:
        assert secret not in blob, f"{secret!r} leaked into parsed_jds.parsed"
    # ...and the scrub did not simply eat the document.
    assert "Manager, Special Projects" in blob


@pytest.fixture(scope="module")
def migrated_pg_url() -> Iterator[str]:
    with PostgresContainer("postgres:16-alpine") as pg:
        url = pg.get_connection_url().replace("psycopg2", "asyncpg")
        cfg = Config(str(ALEMBIC_INI))
        cfg.set_main_option("sqlalchemy.url", url)
        command.upgrade(cfg, "head")
        yield url


async def _counts(session: AsyncSession, root: Path) -> tuple[int, int]:
    """``(source_documents, parsed_jds)`` rows scoped to files under ``root`` — so
    tests sharing the module-scoped Postgres container cannot see each other's rows."""
    prefix = f"{root.as_posix()}%"
    doc_count = await session.scalar(
        select(func.count())
        .select_from(SourceDocument)
        .where(SourceDocument.storage_ref.like(prefix))
    )
    parsed_count = await session.scalar(
        select(func.count())
        .select_from(ParsedJDRow)
        .join(SourceDocument, ParsedJDRow.source_document_id == SourceDocument.id)
        .where(SourceDocument.storage_ref.like(prefix))
    )
    return int(doc_count or 0), int(parsed_count or 0)


@pytest.mark.asyncio
async def test_running_the_driver_twice_changes_nothing(
    migrated_pg_url: str, tmp_path: Path
) -> None:
    """**LANDMINE 1.** Before migration ``0003`` + the idempotent ``parse_and_store``,
    a second run over the same archive doubled every row: 2 files in would become 4
    ``source_documents`` and 4 ``parsed_jds`` rows, each with a fresh UUID."""
    root = tmp_path / "archive"
    root.mkdir()
    (root / "20240101_00000001_new.txt").write_text(
        (FIXTURES / "sfu_new_template.txt").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (root / "20050101_00000002_old.txt").write_text(
        (FIXTURES / "sfu_old_template.txt").read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    engine = create_async_engine(migrated_pg_url)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)

    async with session_maker() as session:
        first = await run_archive_ingest(session, root)
    assert first.files_seen == 2
    assert first.ingested == 2
    assert first.parsed == 2
    assert first.already_done == 0
    assert first.failed == 0

    async with session_maker() as session:
        docs_after_first, parsed_after_first = await _counts(session, root)
    assert docs_after_first == 2
    assert parsed_after_first == 2

    # Run again over the SAME archive, same files, same bytes.
    async with session_maker() as session:
        second = await run_archive_ingest(session, root)
    assert second.files_seen == 2
    assert second.ingested == 0  # nothing newly ingested — both rows already existed
    assert second.parsed == 0  # THE pin: no newly-parsed rows on the re-run
    assert second.already_done == 2
    assert second.failed == 0

    async with session_maker() as session:
        docs_after_second, parsed_after_second = await _counts(session, root)
    assert docs_after_second == docs_after_first == 2
    assert parsed_after_second == parsed_after_first == 2

    await engine.dispose()


@pytest.mark.asyncio
async def test_an_incumbent_name_never_reaches_the_parsed_row(
    migrated_pg_url: str, tmp_path: Path
) -> None:
    """**LANDMINE 2, the FRESH path** (the row is created by this very run, so
    ``IngestOutcome.text`` carries the freshly-scrubbed text).

    The obvious driver — parse the RAW extracted text — would hand the incumbent's
    name straight to the parser and, from Phase 3.2b, across the private network to
    be embedded. This is RED until the driver parses ``IngestOutcome.text``.

    The RESUME path is a separate hole and has its own test below; it is not covered
    by this one, and a reviewer proved as much by deleting the resume path's scrub
    with this test still green.
    """
    root = tmp_path / "archive"
    root.mkdir()
    path = root / "20200101_00000003_incumbent.txt"
    path.write_text(_incumbent_laced_jd(), encoding="utf-8")

    engine = create_async_engine(migrated_pg_url)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)

    async with session_maker() as session:
        result = await run_archive_ingest(session, root)
        assert result.parsed == 1

        parsed_row = await session.scalar(
            select(ParsedJDRow)
            .join(SourceDocument, ParsedJDRow.source_document_id == SourceDocument.id)
            .where(SourceDocument.storage_ref == path.as_posix())
        )
        assert parsed_row is not None
        _assert_scrubbed(parsed_row.parsed)

    await engine.dispose()


@pytest.mark.asyncio
async def test_an_unextractable_file_gets_a_failed_row_and_no_parse(
    migrated_pg_url: str, tmp_path: Path
) -> None:
    """No silent drops: a corrupt ``.docx`` (a supported format whose bytes are
    garbage) gets a ``SourceDocument(status=failed)``, ZERO ``ParsedJDRow``s, and
    appears in the run's skip ledger."""
    root = tmp_path / "archive"
    root.mkdir()
    (root / "20210101_00000004_broken.docx").write_bytes(
        b"PK\x03\x04 not really a docx zip"
    )

    engine = create_async_engine(migrated_pg_url)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)

    async with session_maker() as session:
        result = await run_archive_ingest(session, root)
    assert result.files_seen == 1
    assert result.failed == 1
    assert result.ingested == 0
    assert result.parsed == 0
    assert len(result.skipped) == 1
    ref = (root / "20210101_00000004_broken.docx").as_posix()
    assert result.skipped[0].storage_ref == ref

    async with session_maker() as session:
        doc = await session.scalar(
            select(SourceDocument).where(SourceDocument.storage_ref == ref)
        )
        assert doc is not None
        assert doc.ingest_metadata["status"] == "failed"

        parsed_count = await session.scalar(
            select(func.count())
            .select_from(ParsedJDRow)
            .where(ParsedJDRow.source_document_id == doc.id)
        )
        assert parsed_count == 0

    await engine.dispose()


@pytest.mark.asyncio
async def test_a_failed_rows_reason_is_reproducible_in_the_ledger_and_in_postgres(
    migrated_pg_url: str, tmp_path: Path
) -> None:
    """**The persisted reason must be STABLE.** A legacy ``.doc`` antiword cannot read
    fails with a message naming the random ``NamedTemporaryFile`` it was handed
    (``antiword failed: /tmp/tmp0k444cks.doc is not a Word Document``).

    ``ingest_document`` PERSISTS that string into
    ``source_documents.ingest_metadata["reason"]``, and that row is the audit trail —
    so the scrub has to happen at the source, not merely on its way into the driver's
    in-memory ledger. Left raw, re-ingesting the *same unchanged file* writes a
    *different* reason every run, and a grouped triage report shatters identical
    failures into N groups of 1. MEASURED on the real archive: 11 files carry a temp
    path, 1 a heap address — and two of them sort inside the first 200 files, so even
    the `--limit 200` smoke run wrote per-run noise into Postgres before this fix.
    """
    root = tmp_path / "archive"
    root.mkdir()
    ref = (root / "20030101_00007777_corrupt.doc").as_posix()
    (root / "20030101_00007777_corrupt.doc").write_bytes(b"not a word document at all")

    engine = create_async_engine(migrated_pg_url)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)

    async with session_maker() as session:
        result = await run_archive_ingest(session, root)
    assert result.failed == 1
    ledger_reason = result.skipped[0].reason

    async with session_maker() as session:
        doc = await session.scalar(
            select(SourceDocument).where(SourceDocument.storage_ref == ref)
        )
        assert doc is not None
        persisted_reason = str(doc.ingest_metadata["reason"])

    # The DB row and the run ledger agree — one reason, one home.
    assert ledger_reason == persisted_reason
    # Scrubbed: no random temp path anywhere, in EITHER.
    assert "<tmpfile>" in persisted_reason
    assert tempfile.gettempdir() not in persisted_reason
    # ...and the substance of antiword's complaint survives verbatim.
    assert "antiword failed" in persisted_reason

    await engine.dispose()


@pytest.mark.asyncio
async def test_an_oversized_file_is_never_read_into_memory(
    migrated_pg_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """**The DoS guard on the driver's path — AND the ledger row it must not cost us.**

    Two properties, and they are independent:

    1. **The bytes never reach the extractor.** ``extract_text`` enforces the 50 MiB cap
       — but only *after* the bytes are in memory, so a driver calling
       ``path.read_bytes()`` hands the guard a document it has already loaded. Pinned by
       making ``read_bytes`` **explode**: the only way to pass is never to call it.
    2. **The file still gets a ``source_documents`` row.** Too big to *extract* is not
       too big to *record*. The first cut of this driver dropped the row entirely,
       reasoning "no bytes read -> no sha256 -> the (storage_ref, sha256) key is
       unsatisfiable". The premise was false: ``stream_sha256`` hashes any file in
       CONSTANT memory. ``source_documents`` is one row per FILE (Phase 3.1) and
       provenance is non-negotiable #6 — a file in the archive with no row breaks the
       ledger, and the run's in-memory skip list is not the audit trail; the DB is.

    **Not hypothetical.** The archive's 89,397,431-byte ``.rtf`` sorts inside the
    **first 200 files** of the walk, so even a ``--limit 200`` smoke test hits it.
    """
    monkeypatch.setattr(
        "src.jd_bank.ingest.extract.MAX_DOCUMENT_BYTES", 10, raising=True
    )

    def _explode(self: Path) -> bytes:  # pragma: no cover - must never be called
        raise AssertionError(f"{self} was read despite exceeding the size cap")

    root = tmp_path / "archive"
    root.mkdir()
    path = root / "19980120_00000293_huge.rtf"
    content = b"an oversized document, well past the patched 10-byte cap"
    path.write_bytes(content)
    ref = path.as_posix()
    expected_sha = compute_sha256(content)

    monkeypatch.setattr(Path, "read_bytes", _explode)

    engine = create_async_engine(migrated_pg_url)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)

    async with session_maker() as session:
        result = await run_archive_ingest(session, root)

    assert result.files_seen == 1
    assert result.failed == 1  # a FINDING, not a drop
    assert result.ingested == 0  # it was never EXTRACTED...
    assert result.parsed == 0
    assert result.skipped[0].storage_ref == ref
    assert "exceeds the extractor's cap" in result.skipped[0].reason

    monkeypatch.undo()
    async with session_maker() as session:
        doc = await session.scalar(
            select(SourceDocument).where(SourceDocument.storage_ref == ref)
        )
        # ...but it IS in the ledger.
        assert doc is not None
        assert doc.ingest_metadata["status"] == "failed"
        assert doc.ingest_metadata["reason"] == result.skipped[0].reason
        # The hash is REAL — the same digest `compute_sha256` gives for these bytes, so
        # Tier-1 dedup sees this file like any other, and the (storage_ref, sha256)
        # idempotency key works normally on a re-run.
        assert doc.sha256 == expected_sha
        assert doc.byte_size == len(content)

        # ...and it was never parsed.
        parses = await session.scalar(
            select(func.count())
            .select_from(ParsedJDRow)
            .where(ParsedJDRow.source_document_id == doc.id)
        )
        assert parses == 0

    await engine.dispose()


@pytest.mark.asyncio
async def test_an_unreadable_file_is_counted_and_ledgered_with_no_row(
    migrated_pg_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The ``OSError`` branch — the ONE case that legitimately gets no row, and the
    boundary of the reviewer's "too big to extract is not too big to record" ruling.

    An oversized file can be hashed (``stream_sha256``, constant memory), so it gets a
    row. A file whose bytes cannot be read **at all** (permissions, a file that
    vanished mid-walk) cannot be hashed — so ``(storage_ref, sha256)`` is genuinely
    unsatisfiable, and the alternatives (a sentinel hash, a nullable key) would be
    provenance *lies*: a fake digest would collide in Tier-1 dedup with every other
    unreadable file.

    So it is counted and named in the skip ledger, and it is never silently dropped.
    Empirically a zero-file case: nothing in the 2.5 archive ledger hits it.
    """
    root = tmp_path / "archive"
    root.mkdir()
    path = root / "20120101_00000009_locked.docx"
    path.write_bytes(b"bytes we will pretend we cannot read")
    ref = path.as_posix()

    def _denied(_path: Path) -> bytes:
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr("src.jd_bank.ingest.driver.read_document_bytes", _denied)

    engine = create_async_engine(migrated_pg_url)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)

    async with session_maker() as session:
        result = await run_archive_ingest(session, root)

    assert result.files_seen == 1
    assert result.failed == 1  # counted...
    assert result.ingested == 0
    assert result.parsed == 0
    assert len(result.skipped) == 1  # ...and ledgered, with a reproducible reason
    assert result.skipped[0].storage_ref == ref
    assert "PermissionError" in result.skipped[0].reason

    monkeypatch.undo()
    async with session_maker() as session:
        rows = await session.scalar(
            select(func.count())
            .select_from(SourceDocument)
            .where(SourceDocument.storage_ref == ref)
        )
        assert rows == 0  # nothing to hash -> no row is the HONEST answer here

    await engine.dispose()


@pytest.mark.asyncio
async def test_re_running_over_an_oversized_file_does_not_double_its_row(
    migrated_pg_url: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The oversized row obeys the SAME idempotency key as every other row — which is
    the whole point of hashing it rather than skipping it. Two runs, one row."""
    monkeypatch.setattr(
        "src.jd_bank.ingest.extract.MAX_DOCUMENT_BYTES", 10, raising=True
    )
    root = tmp_path / "archive"
    root.mkdir()
    path = root / "19980120_00000294_huge_again.rtf"
    path.write_bytes(b"another oversized document, comfortably past the 10-byte cap")
    ref = path.as_posix()

    engine = create_async_engine(migrated_pg_url)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)

    async with session_maker() as session:
        first = await run_archive_ingest(session, root)
    async with session_maker() as session:
        second = await run_archive_ingest(session, root)

    assert first.failed == second.failed == 1
    # `failed` is re-reported every run (an unrecoverable file is worth re-surfacing),
    # but the ROW is not re-created.
    async with session_maker() as session:
        rows = await session.scalar(
            select(func.count())
            .select_from(SourceDocument)
            .where(SourceDocument.storage_ref == ref)
        )
        assert rows == 1

    await engine.dispose()


@pytest.mark.asyncio
async def test_a_resumed_run_parses_a_document_ingested_but_not_yet_parsed(
    migrated_pg_url: str, tmp_path: Path
) -> None:
    """The partial-run path a naive implementation gets wrong — and **LANDMINE 2's
    second, deadlier half**.

    A file already ingested (a prior, interrupted run got as far as
    ``source_documents`` but not ``parsed_jds``) must be picked up and parsed. Because
    ``IngestOutcome.text`` is ``None`` for a row that already existed, the driver has
    to extract on demand — and it MUST re-run ``normalize_incumbent_names`` on what it
    extracts. Dropping that scrub and parsing the raw text is invisible to the
    fresh-path test above, and this is the path a real interrupted 14,565-file run
    takes on *every* subsequent invocation. So the fixture here is the
    **incumbent-laced** one: this test is what stands between a resumed run and raw
    incumbent names crossing the network to ``aria-gb10-2``.
    """
    root = tmp_path / "archive"
    root.mkdir()
    path = root / "20100101_00000005_resumed.txt"
    path.write_text(_incumbent_laced_jd(), encoding="utf-8")

    engine = create_async_engine(migrated_pg_url)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)

    # Simulate the interrupted run: ingest happened, parse never did.
    async with session_maker() as session:
        pre_outcome = await ingest_document(
            session,
            filename=path.name,
            data=path.read_bytes(),
            storage_ref=path.as_posix(),
        )
        await session.commit()
        assert pre_outcome.text is not None  # freshly ingested by THIS call
        pre_doc_id = pre_outcome.document.id

    async with session_maker() as session:
        parsed_before = await session.scalar(
            select(func.count())
            .select_from(ParsedJDRow)
            .where(ParsedJDRow.source_document_id == pre_doc_id)
        )
    assert parsed_before == 0

    # Now run the driver over the same archive. `ingest_document` returns text=None
    # (the row exists), so this exercises the on-demand extract + scrub branch.
    async with session_maker() as session:
        result = await run_archive_ingest(session, root)
    assert result.files_seen == 1
    assert result.ingested == 0  # the row already existed — nothing re-ingested
    assert result.parsed == 1  # ...but it WAS parsed, via on-demand extraction
    assert result.already_done == 0
    assert result.failed == 0

    async with session_maker() as session:
        parsed_row = await session.scalar(
            select(ParsedJDRow).where(ParsedJDRow.source_document_id == pre_doc_id)
        )
        assert parsed_row is not None
        # THE PIN: the resume path scrubbed too. Delete the `normalize_incumbent_names`
        # call in driver.py's resume branch and this goes red.
        _assert_scrubbed(parsed_row.parsed)

    await engine.dispose()

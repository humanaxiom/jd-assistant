"""The archive -> Postgres ingest driver (Phase 3.2a).

**Why this exists.** Before this module, ``ingest_document`` and ``parse_and_store``
were called from integration tests only — nothing walked the real archive and
persisted it. So ``parsed_jds`` had no rows, and Phase 3.2b (embeddings) had nothing to
embed and nowhere to hang a ``source_document_id`` back-reference. This driver is the
prerequisite: walk the archive, ingest every file, parse every ingestible one, commit
in batches, and account for every file that could not make it through.

The chain per file, reusing exactly what :mod:`src.jd_bank.baseline.runner` already
uses for the archive walk (HANDOFF: "do not hand-roll a second path")::

    walk_archive -> read bytes -> ingest_document (idempotent)
                 -> parse_and_store (idempotent), using the INCUMBENT-NORMALIZED text

**LANDMINE 2, closed.** ``ingest_document`` used to compute and then discard the
incumbent-normalized text; the obvious driver would have re-extracted RAW text
(containing incumbent names) to hand to the parser, which is what Phase 3.2b embeds on
``aria-gb10-2`` across the private network. This driver only ever parses
:attr:`~src.jd_bank.ingest.ingest.IngestOutcome.text` — the freshly-scrubbed text when
this call did the extraction, or a fresh on-demand extract+scrub (never the raw bytes
handed straight to the parser) when the row already existed but had not yet been
parsed (a resumed/partial run — see :attr:`IngestResult.parsed`).

**Resumability comes from two idempotency keys, not from driver-side bookkeeping.**
``ingest_document``'s is ``(storage_ref, sha256)`` (migration ``0002``);
``parse_and_store``'s is ``(source_document_id, parser_version)`` (migration ``0003``,
LANDMINE 1). The driver commits every ``commit_every`` files rather than once for the
whole archive, so a failure partway through loses at most one open batch — and
re-running from the top is safe and cheap precisely because both steps are no-ops on
already-done work.

**No silent drops.** Every file the walk selects lands in exactly one of:
:attr:`IngestResult.ingested` (+ usually :attr:`~IngestResult.parsed`),
:attr:`IngestResult.already_done`, or :attr:`IngestResult.failed` (with a ledger
entry) — see :class:`~src.jd_bank.ingest.models.IngestResult` for the precise counting
rules.

**...and no silent drops from the DATABASE either.** Every file whose bytes we can read
*at all* gets a ``source_documents`` row — including the ones we refuse to extract. An
oversized document is hashed with
:func:`~src.jd_bank.ingest.extract.stream_sha256` (constant memory) and persisted with a
``failed`` status via
:func:`~src.jd_bank.ingest.ingest.ingest_unreadable_document`, because
``source_documents`` is **one row per FILE** (Phase 3.1) and the DB — not this run's
in-memory ledger — is the audit trail. The cap protects the *extractor*; it was never a
reason to forget that a file exists.
"""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.jd_bank.db.models import ParsedJDRow
from src.jd_bank.ingest.extract import (
    DocumentTooLargeError,
    ExtractionError,
    extract_text,
    read_document_bytes,
    stream_sha256,
)
from src.jd_bank.ingest.ingest import (
    ingest_document,
    ingest_unreadable_document,
    walk_archive,
)
from src.jd_bank.ingest.models import IngestResult, SkipEntry
from src.jd_bank.ingest.scrub import normalize_incumbent_names
from src.jd_bank.stable_reason import stable_reason
from src.jd_core.parser import PARSER_VERSION, parse_and_store

#: A source document's ``ingest_metadata["status"]`` that means "extracted cleanly and
#: is eligible to be parsed". The other two statuses (``unsupported``, ``failed``) are
#: never eligible — see the module + ``ingest_document`` docstrings.
_INGESTED_STATUS = "ingested"


async def _already_parsed(
    session: AsyncSession, *, source_document_id: uuid.UUID
) -> bool:
    row_id = await session.scalar(
        select(ParsedJDRow.id).where(
            ParsedJDRow.source_document_id == source_document_id,
            ParsedJDRow.parser_version == PARSER_VERSION,
        )
    )
    return row_id is not None


def _select_paths(root: Path, *, limit: int | None) -> list[Path]:
    """The files to ingest, deterministically. A plain (sync) function so the
    filesystem walk + stat can run off the event loop via ``asyncio.to_thread`` —
    ``root.is_dir()`` is a blocking call, and this driver, unlike the baseline
    runner, is async."""
    if not root.is_dir():
        raise FileNotFoundError(f"archive root {root} is not a directory")
    paths = list(walk_archive(root))
    if not paths:
        raise FileNotFoundError(
            f"archive root {root} contains no files — point --archive-root / "
            f"JD_ARCHIVE_PATH at the SFU JD archive root"
        )
    return paths[:limit] if limit is not None else paths


async def run_archive_ingest(
    session: AsyncSession,
    archive_root: str | Path,
    *,
    limit: int | None = None,
    commit_every: int = 200,
) -> IngestResult:
    """Walk ``archive_root``, ingest + parse every file, and commit in batches.

    ``limit`` takes the first N files of the deterministic sorted walk (smoke-testing
    a real run without scoring the whole archive — mirrors
    :func:`~src.jd_bank.baseline.runner.select`'s ``limit``, but this driver has no
    ``sample`` mode: a resumable, idempotent ingest is meant to be run to completion,
    not sampled).

    ``commit_every`` bounds how much work a mid-run failure can lose. The whole
    archive is NOT one transaction — a failure at file 14,000 must not discard files
    1 through 13,999 (HANDOFF: this is the entire point of committing in batches
    rather than once at the end).

    Raises:
        ValueError: ``commit_every`` is not positive.
        FileNotFoundError: ``archive_root`` is not a directory, or holds no files —
            mirrors :func:`~src.jd_bank.baseline.runner.run_baseline`'s guard, so an
            unset/misconfigured archive path fails loudly instead of committing a
            confident, empty run.
    """
    if commit_every <= 0:
        raise ValueError(
            f"commit_every must be a positive number of files, got {commit_every}"
        )

    root = Path(archive_root)
    paths = await asyncio.to_thread(_select_paths, root, limit=limit)

    files_seen = 0
    ingested = 0
    parsed = 0
    already_done = 0
    failed = 0
    skipped: list[SkipEntry] = []

    for path in paths:
        files_seen += 1
        storage_ref = path.as_posix()

        try:
            # STAT BEFORE READ — the shared guard `read_document_bytes`, the same one
            # `baseline/runner.py` uses. `ingest_document` -> `extract_text` enforces
            # the 50 MiB cap too, but only AFTER the bytes are in memory, so calling
            # `path.read_bytes()` here would hand the guard a document it has already
            # loaded. The archive's 89,397,431-byte `.rtf` sorts inside the FIRST 200
            # files, so even a `--limit 200` smoke test hits it on every run.
            data = await asyncio.to_thread(read_document_bytes, path)
        except DocumentTooLargeError as exc:
            # TOO BIG TO EXTRACT IS NOT TOO BIG TO RECORD. The file still gets its
            # `source_documents` row: `source_documents` is one row per FILE (Phase
            # 3.1) and provenance is non-negotiable #6, so a file in the archive with
            # no row breaks the ledger — and "the run ledger mentions it" is no
            # substitute, because the run ledger is ephemeral and the DB is the audit
            # trail. `stream_sha256` hashes it in CONSTANT memory (1 MiB chunks), so
            # the `(storage_ref, sha256)` key works normally and a re-run is a no-op.
            # The bytes never reach a backend — which is the only thing the cap ever
            # guarded.
            reason = stable_reason(exc)
            sha256, byte_size = await asyncio.to_thread(stream_sha256, path)
            await ingest_unreadable_document(
                session,
                filename=path.name,
                storage_ref=storage_ref,
                sha256=sha256,
                byte_size=byte_size,
                reason=reason,
            )
            failed += 1
            skipped.append(SkipEntry(storage_ref=storage_ref, reason=reason))
            if files_seen % commit_every == 0:
                await session.commit()
            continue
        except OSError as exc:
            # The bytes cannot be read AT ALL (permissions, a vanished file). There is
            # nothing to hash, so unlike the oversized case there is no row to write —
            # it is counted and named in the skip ledger.
            failed += 1
            skipped.append(
                SkipEntry(storage_ref=storage_ref, reason=stable_reason(exc))
            )
            if files_seen % commit_every == 0:
                await session.commit()
            continue

        outcome = await ingest_document(
            session, filename=path.name, data=data, storage_ref=storage_ref
        )
        status = outcome.document.ingest_metadata.get("status")

        if status != _INGESTED_STATUS:
            failed += 1
            # Already `stable_reason`-scrubbed by `ingest_document` — the row and this
            # ledger carry the SAME string (must-fix 3).
            persisted = outcome.document.ingest_metadata.get("reason", status)
            skipped.append(SkipEntry(storage_ref=storage_ref, reason=str(persisted)))
            if files_seen % commit_every == 0:
                await session.commit()
            continue

        if outcome.text is not None:
            # Freshly ingested THIS call — this is the row's first appearance.
            ingested += 1

        if await _already_parsed(session, source_document_id=outcome.document.id):
            already_done += 1
        else:
            clean_text = outcome.text
            if clean_text is None:
                # The row already existed (a resumed/partial run: ingested earlier,
                # never parsed) — `ingest_document` only returns the text on the path
                # that actually extracted it, so it must be re-extracted here. NEVER
                # fall back to the raw bytes: that would be LANDMINE 2 again, this
                # time from the driver instead of from `ingest_document`.
                try:
                    raw_text = await asyncio.to_thread(
                        extract_text, data, outcome.document.fmt
                    )
                except ExtractionError as exc:
                    # The format/bytes extracted fine at first-ingest time but no
                    # longer do (defensive; not expected on a read-only archive) —
                    # this file cannot be parsed this run either.
                    failed += 1
                    skipped.append(
                        SkipEntry(storage_ref=storage_ref, reason=stable_reason(exc))
                    )
                    if files_seen % commit_every == 0:
                        await session.commit()
                    continue
                scrubbed, _report = await asyncio.to_thread(
                    normalize_incumbent_names, raw_text
                )
                clean_text = scrubbed

            await parse_and_store(session, outcome.document, clean_text)
            parsed += 1

        if files_seen % commit_every == 0:
            await session.commit()

    await session.commit()

    return IngestResult(
        files_seen=files_seen,
        ingested=ingested,
        parsed=parsed,
        already_done=already_done,
        failed=failed,
        skipped=tuple(skipped),
    )

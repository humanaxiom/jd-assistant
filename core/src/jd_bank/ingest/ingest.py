"""Archive ingestion — walk, hash, detect, extract, normalize, persist.

The first stage of the pipeline (plan §2): each archive file is hashed
(SHA-256, the Tier-1 dedup key), its format detected by extension, its text
extracted (:mod:`src.jd_bank.ingest.extract`) and incumbent-normalized
(:mod:`src.jd_bank.ingest.scrub`), and a :class:`~src.jd_bank.db.models.
SourceDocument` row persisted with the format, byte size, ingest metadata, and
the normalization report.

**ONE ROW PER FILE** (Phase 3.1). A duplicate SHA-256 gets its **own row**: two archive
files that are byte-identical are two archive files, and ``source_documents`` is a
faithful ledger of the archive. Duplication is a *finding* — :mod:`src.jd_bank.dedup`
records it as ``DedupEdge`` rows — never a silent write-time collapse. Before 3.1 the
hash was ``UNIQUE`` and this function returned the existing row, which discarded the
filenames of 1,972 of the archive's 14,565 files.

The idempotency key is therefore ``(storage_ref, sha256)``: *this exact content, at
this exact location, is one ledger row*. See :data:`_IDEMPOTENCY_KEY`.

Extraction/scrub are CPU/subprocess-bound and run off the event loop via
``asyncio.to_thread`` so the async caller is never blocked.
"""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Iterator
from pathlib import Path
from typing import Final

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.jd_bank.db.models import DocumentFormat, SourceDocument
from src.jd_bank.ingest.extract import ExtractionError, extract_text
from src.jd_bank.ingest.scrub import normalize_incumbent_names

# Extension -> format. ``.docm`` is OOXML like ``.docx`` (python-docx reads
# both). Everything unlisted (``.pdf``/``.tif``/``.serv``/``.dot`` …) is OTHER
# and routed to manual triage rather than crashing.
_EXT_MAP: dict[str, DocumentFormat] = {
    "docx": DocumentFormat.DOCX,
    "docm": DocumentFormat.DOCX,
    "doc": DocumentFormat.DOC,
    "rtf": DocumentFormat.RTF,
    "txt": DocumentFormat.TXT,
}

# Extensions we intentionally ingest (or skip) — a walk filter. Non-document
# junk (e.g. ``.db``/``.ini``) is excluded; unknown doc-like files still get a
# row so nothing is silently dropped.
_KNOWN_EXTS = frozenset({*_EXT_MAP, "dot", "docx", "pdf", "tif", "serv"})


def detect_format(filename: str) -> DocumentFormat:
    """Map a filename to its :class:`DocumentFormat` by its final extension.

    Stacked extensions (``...doc.doc``) resolve by the *last* suffix. Unknown or
    unsupported extensions map to :data:`DocumentFormat.OTHER`.
    """
    ext = Path(filename).suffix.lower().lstrip(".")
    return _EXT_MAP.get(ext, DocumentFormat.OTHER)


def compute_sha256(data: bytes) -> str:
    """Deterministic SHA-256 hex digest of raw bytes (the Tier-1 dedup key)."""
    return hashlib.sha256(data).hexdigest()


def walk_archive(root: str | Path) -> Iterator[Path]:
    """Yield document files under ``root`` (recursively), sorted for determinism.

    The SFU archive is a single flat directory, but ``rglob`` also tolerates a
    nested layout. Only regular files are yielded; hidden/dotfiles are skipped.
    """
    root_path = Path(root)
    for path in sorted(root_path.rglob("*")):
        if path.is_file() and not path.name.startswith("."):
            yield path


#: **The idempotency key**, and the thing that replaced ``UNIQUE(sha256)``.
#:
#: Dropping the unique hash (migration ``0002``) removed what used to make a re-run of
#: ingestion safe, so the key had to be *replaced*, not deleted. ``(storage_ref,
#: sha256)`` reads as: *this exact content, at this exact location, is one ledger row.*
#:
#: Why not ``storage_ref`` alone — the obvious "one row per file" key? Because it forces
#: a decision the moment the bytes at a path ever change, and both of its answers are
#: bad: UPDATE the row in place, which silently re-points every ``parsed_jds`` /
#: ``validation_reports`` row already hanging off it at bytes that did not produce them
#: (a provenance lie, and precisely what non-negotiable #6 forbids); or raise, which
#: makes a routine re-scan of a corrected archive fail. Keying on the pair means a
#: changed file simply gets a **new** row and the old one keeps its lineage intact.
#:
#: Why not ``sha256`` alone? That is the bug being fixed: it is a key over *content*,
#: and it discards filenames.
#:
#: The archive is read-only, so in practice the two keys behave identically on it. This
#: is a deliberate choice about which one is *safe when the assumption breaks*.
_IDEMPOTENCY_KEY: Final[str] = "(storage_ref, sha256)"


async def _existing(
    session: AsyncSession, *, storage_ref: str, sha256: str
) -> SourceDocument | None:
    """The row for THIS file, if the archive has already been ingested."""
    row: SourceDocument | None = await session.scalar(
        select(SourceDocument).where(
            SourceDocument.storage_ref == storage_ref,
            SourceDocument.sha256 == sha256,
        )
    )
    return row


async def ingest_document(
    session: AsyncSession,
    *,
    filename: str,
    data: bytes,
    storage_ref: str,
) -> SourceDocument:
    """Ingest one document into ``source_documents`` and return its row.

    Hashes ``data``, detects the format, extracts + incumbent-normalizes the
    text, and inserts a row carrying the format, byte size, ingest metadata, and
    the (PII-free) normalization report. Unsupported formats
    (:data:`DocumentFormat.OTHER`) are persisted with an ``unsupported`` status
    for manual triage instead of raising.

    **A duplicate SHA-256 gets its own row** — see the module docstring. Re-ingesting
    the *same file* (:data:`_IDEMPOTENCY_KEY`) returns the already-stored row, so a
    re-run of the archive walk is a no-op rather than a second copy of it.
    """
    sha256 = compute_sha256(data)

    existing = await _existing(session, storage_ref=storage_ref, sha256=sha256)
    if existing is not None:
        return existing

    fmt = detect_format(filename)
    original_ext = Path(filename).suffix.lower().lstrip(".")

    ingest_metadata: dict[str, object]
    normalization_report: dict[str, object]
    if fmt is DocumentFormat.OTHER:
        ingest_metadata = {
            "status": "unsupported",
            "reason": "no extraction backend for this format",
            "original_extension": original_ext,
        }
        normalization_report = {}
    else:
        try:
            text = await asyncio.to_thread(extract_text, data, fmt)
        except ExtractionError as exc:
            # A corrupt/oversized/timed-out document must not crash the worker
            # (DoS hardening) — persist a failed row for manual triage instead,
            # consistent with the unsupported-format routing above.
            ingest_metadata = {
                "status": "failed",
                "reason": str(exc),
                "original_extension": original_ext,
            }
            normalization_report = {}
        else:
            clean_text, report = await asyncio.to_thread(
                normalize_incumbent_names, text
            )
            ingest_metadata = {
                "status": "ingested",
                "original_extension": original_ext,
                "char_count": len(clean_text),
            }
            normalization_report = report.to_dict()

    doc = SourceDocument(
        storage_ref=storage_ref,
        filename=filename,
        sha256=sha256,
        fmt=fmt,
        byte_size=len(data),
        ingest_metadata=ingest_metadata,
        normalization_report=normalization_report,
    )
    # The insert goes in a SAVEPOINT so that losing the race costs exactly this one
    # row. The old handler called `session.rollback()` — which rolls back the CALLER'S
    # WHOLE TRANSACTION, silently discarding every other document staged in it. That is
    # the half-updated concurrency story 3.1 had to finish: a batch ingest of 14,565
    # files, hitting one duplicate storage_ref, would have thrown away everything since
    # its last commit and reported success.
    try:
        async with session.begin_nested():
            session.add(doc)
            await session.flush()
    except IntegrityError:
        # A concurrent insert of the SAME FILE (`_IDEMPOTENCY_KEY`) beat us to it. The
        # savepoint is already rolled back; the caller's other work is untouched.
        winner = await _existing(session, storage_ref=storage_ref, sha256=sha256)
        if winner is None:  # pragma: no cover — defensive; the unique row must exist
            raise
        return winner

    return doc

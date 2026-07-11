"""Archive ingestion — walk, hash, detect, extract, normalize, persist.

The first stage of the pipeline (plan §2): each archive file is hashed
(SHA-256, the Tier-1 dedup key), its format detected by extension, its text
extracted (:mod:`src.jd_bank.ingest.extract`) and incumbent-normalized
(:mod:`src.jd_bank.ingest.scrub`), and a :class:`~src.jd_bank.db.models.
SourceDocument` row persisted with the format, byte size, ingest metadata, and
the normalization report. Duplicate SHA-256 is handled gracefully (the column
is unique): a re-ingest returns the existing row rather than raising.

Extraction/scrub are CPU/subprocess-bound and run off the event loop via
``asyncio.to_thread`` so the async caller is never blocked.
"""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Iterator
from pathlib import Path

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
    for manual triage instead of raising. A duplicate SHA-256 returns the
    already-stored row (the column is unique).
    """
    sha256 = compute_sha256(data)

    existing = await session.scalar(
        select(SourceDocument).where(SourceDocument.sha256 == sha256)
    )
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
    session.add(doc)
    try:
        await session.flush()
    except IntegrityError:
        # Concurrent insert of the same sha256 raced us — return the winner.
        await session.rollback()
        winner = await session.scalar(
            select(SourceDocument).where(SourceDocument.sha256 == sha256)
        )
        if winner is None:  # pragma: no cover — defensive; unique row must exist
            raise
        return winner

    return doc

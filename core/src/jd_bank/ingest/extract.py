"""Text extraction for the real SFU archive formats.

Ported and slimmed from hris ``pipeline/parsing/extract.py`` (reuse map #14).
What is kept: the tolerant decode ladder, the DOCX (python-docx) and RTF
(striprtf) backends, and the NUL-stripping sanitiser that keeps Postgres happy.
What is dropped: the PDF/PyMuPDF path and the page/block structure — the JD
corpus is near-zero PDF (census §3) and downstream stages want a flat text
stream, not positioned blocks. What is *added*: an ``antiword`` backend for the
legacy binary ``.doc`` corpus (4,577 files; python-docx cannot read binary
``.doc``), which the census validated as the offline extraction path.

The public entry point is :func:`extract_text` — ``bytes + DocumentFormat`` in,
plain ``str`` out. Unsupported formats raise :class:`UnsupportedFormatError`.
"""

from __future__ import annotations

import hashlib
import subprocess
import tempfile
from io import BytesIO
from pathlib import Path

from docx import Document

from src.jd_bank.db.models import DocumentFormat

# antiword ships in the ingestion image (Dockerfile). Overridable for tests.
ANTIWORD_BIN = "antiword"

# DoS hardening. The archive is ~14,565 files processed by shared workers, so a
# single corrupt/crafted document must not hang a worker or exhaust its memory.
# A crafted binary .doc can send antiword into a pathological loop -> hard wall
# clock cap; and no legitimate SFU JD approaches 50 MiB (the largest golden file
# is ~5 MiB) -> reject oversized inputs before loading them into a backend.
#
# NB what the cap protects is THE EXTRACTOR — antiword / python-docx, which allocate
# proportional to their input and are the actual hazard. It does NOT forbid us from
# *hashing* bytes we never parse: see `stream_sha256`, which reads any file in constant
# memory. An oversized file is still a file, and it still gets a `source_documents` row.
ANTIWORD_TIMEOUT_SECONDS = 30
MAX_DOCUMENT_BYTES = 50 * 1024 * 1024  # 50 MiB

#: Chunk size for :func:`stream_sha256`. Bounds the memory a hash of ANY file costs.
_HASH_CHUNK_BYTES = 1024 * 1024  # 1 MiB


class ExtractionError(RuntimeError):
    """Text could not be extracted from an otherwise-supported document."""


class UnsupportedFormatError(ExtractionError):
    """The document format has no extraction backend (route to manual triage)."""


class DocumentTooLargeError(ExtractionError):
    """Input exceeds :data:`MAX_DOCUMENT_BYTES` — rejected before extraction."""


def _strip_nul(text: str) -> str:
    """Remove NUL (U+0000). Postgres ``text``/``jsonb`` cannot store U+0000 (it
    raises ``UntranslatableCharacterError`` at write time), and some legacy
    binaries carry embedded NULs. Cheap unconditional pass — the common clean
    case is a no-op."""
    return text.replace("\x00", "") if "\x00" in text else text


def _decode(blob: bytes) -> str:
    """Tolerant byte decode: UTF-8 BOM -> UTF-8 -> latin-1 (never raises).
    Same ladder as hris so text inputs decode predictably across eras."""
    for codec in ("utf-8-sig", "utf-8"):
        try:
            return blob.decode(codec)
        except UnicodeDecodeError:
            continue
    return blob.decode("latin-1")


def _extract_docx(blob: bytes) -> str:
    """python-docx — flat paragraph stream. Handles ``.docx`` and macro-enabled
    ``.docm`` (both OOXML)."""
    try:
        doc = Document(BytesIO(blob))
    except Exception as exc:  # noqa: BLE001 — normalise any python-docx failure
        raise ExtractionError(f"docx parse failed: {exc}") from exc
    return "\n".join(p.text for p in doc.paragraphs if p.text)


def _extract_rtf(blob: bytes) -> str:
    """striprtf — pure-Python RTF -> plain text. Imported lazily so a process
    that never touches RTF need not hard-require the optional dependency."""
    from striprtf.striprtf import rtf_to_text  # noqa: PLC0415 — optional dep, lazy

    try:
        text: str = rtf_to_text(_decode(blob))  # type: ignore[no-untyped-call]
        return text.strip()
    except Exception as exc:  # noqa: BLE001
        raise ExtractionError(f"rtf parse failed: {exc}") from exc


def _extract_txt(blob: bytes) -> str:
    """Plain text — tolerant decode, no structure to recover."""
    return _decode(blob).strip()


def _extract_doc(blob: bytes) -> str:
    """Legacy binary ``.doc`` (Word 97-2003) via the ``antiword`` subprocess.

    python-docx cannot read binary ``.doc``; the census validated antiword as
    the offline path (0 failures across the sample). antiword needs a file on
    disk, so the bytes are written to a temp file, extracted, and cleaned up.
    """
    tmp_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".doc", delete=False) as tmp:
            tmp.write(blob)
            tmp_path = tmp.name
        try:
            proc = subprocess.run(
                [ANTIWORD_BIN, tmp_path],
                capture_output=True,
                check=True,
                timeout=ANTIWORD_TIMEOUT_SECONDS,
            )
        except FileNotFoundError as exc:  # antiword not installed
            raise ExtractionError(
                "antiword binary not found — required for legacy .doc extraction"
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise ExtractionError(
                f"antiword timed out after {ANTIWORD_TIMEOUT_SECONDS}s "
                "(possible corrupt or crafted .doc)"
            ) from exc
        except subprocess.CalledProcessError as exc:
            detail = _decode(exc.stderr or b"").strip()
            raise ExtractionError(f"antiword failed: {detail}") from exc
        return _decode(proc.stdout).strip()
    finally:
        if tmp_path is not None:
            Path(tmp_path).unlink(missing_ok=True)


_BACKENDS = {
    DocumentFormat.DOCX: _extract_docx,
    DocumentFormat.DOC: _extract_doc,
    DocumentFormat.RTF: _extract_rtf,
    DocumentFormat.TXT: _extract_txt,
}


def extract_text(data: bytes, fmt: DocumentFormat) -> str:
    """Extract plain text from ``data`` for the detected ``fmt``.

    ``.docx``/``.docm`` via python-docx, legacy ``.doc`` via antiword, ``.rtf``
    via striprtf, ``.txt`` via a tolerant decode ladder. NUL characters are
    stripped so the result is safe to persist in Postgres. Formats without a
    backend (:data:`DocumentFormat.OTHER` — e.g. ``.pdf``/``.tif``/``.serv``)
    raise :class:`UnsupportedFormatError` for routing to manual triage.
    """
    if len(data) > MAX_DOCUMENT_BYTES:
        raise DocumentTooLargeError(
            f"input is {len(data)} bytes, exceeds cap of {MAX_DOCUMENT_BYTES} bytes"
        )
    backend = _BACKENDS.get(fmt)
    if backend is None:
        raise UnsupportedFormatError(f"no extraction backend for format: {fmt.value}")
    return _strip_nul(backend(data))


def read_document_bytes(path: str | Path) -> bytes:
    """Read a document's bytes, **stat-ing first** so an oversized file is never
    loaded into memory.

    THE ONE HOME OF THE STAT-BEFORE-READ GUARD. :func:`extract_text` also enforces
    :data:`MAX_DOCUMENT_BYTES` — but only *after* the bytes are already in memory, so
    a caller that reads first hands a 50 MiB+ document straight past the DoS guard the
    extractor deliberately added. Every archive walker (the Phase 2.5 baseline runner,
    the Phase 3.2a ingest driver) must go through here rather than calling
    ``path.read_bytes()`` itself.

    **Not hypothetical. MEASURED:** exactly one archive file exceeds the cap —
    ``19980120_19980120_00000293_Asst_to_Director,_Rec_Services.rtf``, **89,397,431
    bytes** — and it sorts inside the FIRST 200 files of the walk, so even a
    ``--limit 200`` smoke test hits it.

    Raises:
        DocumentTooLargeError: the file exceeds :data:`MAX_DOCUMENT_BYTES`. The bytes
            are never read.
        OSError: the file could not be stat-ed or read.
    """
    p = Path(path)
    size = p.stat().st_size
    if size > MAX_DOCUMENT_BYTES:
        raise DocumentTooLargeError(
            f"{size} bytes exceeds the extractor's cap of {MAX_DOCUMENT_BYTES} bytes "
            f"(not read)"
        )
    return p.read_bytes()


def stream_sha256(path: str | Path) -> tuple[str, int]:
    """``(sha256 hex, byte size)`` for a file of ANY size, in **constant memory**.

    The counterpart to :func:`read_document_bytes`, and the thing that lets an
    oversized file still be a *ledger row*. SHA-256 is a streaming digest: the file is
    read in :data:`_HASH_CHUNK_BYTES` chunks and the digest updated per chunk, so the
    89 MB archive ``.rtf`` costs 1 MiB of memory to hash, not 89.

    **Why this exists** (Phase 3.2a, reviewer ruling). The first cut of the ingest
    driver gave an oversized file *no* ``source_documents`` row at all, reasoning: the
    bytes are never read -> there is no sha256 -> the ``(storage_ref, sha256)``
    idempotency key is unsatisfiable. The premise was false. Phase 3.1 made
    ``source_documents`` **one row per FILE — a real ledger** (it took a migration and
    a dropped UNIQUE to get there), and CLAUDE.md non-negotiable #6 is provenance: a
    file that exists in the archive and has no row breaks that property. Today that is
    one file; the property is what matters.

    Hashing is NOT what :data:`MAX_DOCUMENT_BYTES` guards against — the extractor is
    (see the constant). This function never hands a byte to a backend.

    The digest is identical to :func:`~src.jd_bank.ingest.ingest.compute_sha256` over
    the same content (same algorithm, same bytes); ``test_ingest_extract.py`` pins that
    equivalence, because the two must agree or the Tier-1 dedup key would split.
    """
    digest = hashlib.sha256()
    size = 0
    with Path(path).open("rb") as handle:
        while chunk := handle.read(_HASH_CHUNK_BYTES):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def extract_text_from_path(path: str | Path) -> str:
    """Convenience wrapper: read a file and extract using its detected format.

    Format detection is by extension (see :func:`src.jd_bank.ingest.ingest.
    detect_format`), imported lazily to avoid a package import cycle.
    """
    from src.jd_bank.ingest.ingest import detect_format  # noqa: PLC0415

    p = Path(path)
    try:
        data = read_document_bytes(p)
    except DocumentTooLargeError as exc:
        # Re-raise NAMING THE FILE. This wrapper's message is human-facing, and it
        # carried the filename before the guard was consolidated.
        #
        # The name is added HERE rather than inside `read_document_bytes` on purpose:
        # that function's message is what the Phase 2.5 baseline writes into its skip
        # ledger, and `docs/baseline/errors.jsonl` is a COMMITTED artifact that must
        # stay byte-identical across runs. Changing the shared message would silently
        # churn it. (The path is already in the ledger's `path` field anyway — it is
        # this wrapper, which callers use without a surrounding row, that needs it in
        # the message.)
        raise DocumentTooLargeError(f"{p.name}: {exc}") from exc
    return extract_text(data, detect_format(p.name))

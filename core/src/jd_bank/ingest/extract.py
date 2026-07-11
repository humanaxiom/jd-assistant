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
ANTIWORD_TIMEOUT_SECONDS = 30
MAX_DOCUMENT_BYTES = 50 * 1024 * 1024  # 50 MiB


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


def extract_text_from_path(path: str | Path) -> str:
    """Convenience wrapper: read a file and extract using its detected format.

    Format detection is by extension (see :func:`src.jd_bank.ingest.ingest.
    detect_format`), imported lazily to avoid a package import cycle.
    """
    from src.jd_bank.ingest.ingest import detect_format  # noqa: PLC0415

    p = Path(path)
    # Check the on-disk size before reading so an oversized file is never loaded.
    size = p.stat().st_size
    if size > MAX_DOCUMENT_BYTES:
        raise DocumentTooLargeError(
            f"{p.name} is {size} bytes, exceeds cap of {MAX_DOCUMENT_BYTES} bytes"
        )
    return extract_text(p.read_bytes(), detect_format(p.name))

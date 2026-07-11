"""Unit tests for text extraction across the real SFU archive formats.

Covers each backend (txt / rtf / docx / legacy .doc via antiword), the
NUL-strip guard, and the unsupported-format error. The .docx fixture is built
in-process with python-docx (available in the ingestion image) so no binary
blob need be committed; the .doc fixture is one small real archive file
committed under ``tests/fixtures/`` (``.gitattributes`` marks ``*.doc`` binary).
"""

from __future__ import annotations

import subprocess
from io import BytesIO
from pathlib import Path

import pytest
from docx import Document

from src.jd_bank.db.models import DocumentFormat
from src.jd_bank.ingest import extract as extract_mod
from src.jd_bank.ingest.extract import (
    MAX_DOCUMENT_BYTES,
    DocumentTooLargeError,
    ExtractionError,
    UnsupportedFormatError,
    extract_text,
    extract_text_from_path,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def _docx_bytes(paragraphs: list[str]) -> bytes:
    doc = Document()
    for line in paragraphs:
        doc.add_paragraph(line)
    buf = BytesIO()
    doc.save(buf)
    return buf.getvalue()


def test_extract_txt_tolerant_decode() -> None:
    text = extract_text("Café résumé — Analyst\n".encode(), DocumentFormat.TXT)
    assert "Café résumé" in text
    assert "Analyst" in text


def test_extract_txt_latin1_fallback() -> None:
    # 0xE9 is 'é' in latin-1 but invalid as a lone UTF-8 byte — the ladder falls
    # through to latin-1 rather than raising.
    text = extract_text(b"Caf\xe9 Analyst", DocumentFormat.TXT)
    assert "Analyst" in text


def test_extract_txt_strips_nul() -> None:
    text = extract_text(b"Research\x00 Analyst\x00", DocumentFormat.TXT)
    assert "\x00" not in text
    assert "Research Analyst" in text


def test_extract_rtf_fixture() -> None:
    text = extract_text((FIXTURES / "sample.rtf").read_bytes(), DocumentFormat.RTF)
    assert "Research Analyst" in text
    assert "\\rtf" not in text  # control words stripped


def test_extract_docx_roundtrip() -> None:
    blob = _docx_bytes(["POSITION SUMMARY", "The Research Analyst compiles data."])
    text = extract_text(blob, DocumentFormat.DOCX)
    assert "POSITION SUMMARY" in text
    assert "Research Analyst compiles data." in text


def test_extract_docx_bad_bytes_raises() -> None:
    with pytest.raises(ExtractionError):
        extract_text(b"not a real docx zip", DocumentFormat.DOCX)


def test_extract_legacy_doc_via_antiword() -> None:
    blob = (FIXTURES / "sample_legacy.doc").read_bytes()
    text = extract_text(blob, DocumentFormat.DOC)
    # Stable substrings from the 1982 Systems Analyst II JD (antiword output).
    assert "Systems Analyst" in text
    assert "Computing Centre" in text
    assert "\x00" not in text


def test_unsupported_format_raises() -> None:
    with pytest.raises(UnsupportedFormatError):
        extract_text(b"\x00\x01\x02", DocumentFormat.OTHER)


def test_extract_text_from_path_txt(tmp_path: Path) -> None:
    p = tmp_path / "jd.txt"
    p.write_text("Position Summary: Research Analyst.", encoding="utf-8")
    assert "Research Analyst" in extract_text_from_path(p)


def test_extract_text_from_path_unsupported(tmp_path: Path) -> None:
    p = tmp_path / "scan.tif"
    p.write_bytes(b"\x00\x01")
    with pytest.raises(UnsupportedFormatError):
        extract_text_from_path(p)


# ── DoS hardening ────────────────────────────────────────────────────────────


def test_default_cap_is_50_mib() -> None:
    assert MAX_DOCUMENT_BYTES == 50 * 1024 * 1024


def test_oversized_input_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    # Patch the cap small so the test needn't allocate 50 MiB.
    monkeypatch.setattr(extract_mod, "MAX_DOCUMENT_BYTES", 8, raising=True)
    with pytest.raises(DocumentTooLargeError):
        extract_text(b"x" * 9, DocumentFormat.TXT)


def test_at_cap_input_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    # Exactly at the cap is permitted (boundary is strictly greater-than).
    monkeypatch.setattr(extract_mod, "MAX_DOCUMENT_BYTES", 8, raising=True)
    assert extract_text(b"A" * 8, DocumentFormat.TXT).startswith("A")


def test_extract_text_from_path_oversized(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    p = tmp_path / "huge.txt"
    p.write_bytes(b"small on disk")
    # Report an over-cap size without writing a 50 MiB file to disk.
    monkeypatch.setattr(extract_mod, "MAX_DOCUMENT_BYTES", 4, raising=True)
    with pytest.raises(DocumentTooLargeError):
        extract_text_from_path(p)


def test_antiword_timeout_raises_extraction_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _raise_timeout(*args: object, **kwargs: object) -> None:
        raise subprocess.TimeoutExpired(cmd="antiword", timeout=1)

    monkeypatch.setattr(extract_mod.subprocess, "run", _raise_timeout)
    with pytest.raises(ExtractionError, match="timed out"):
        extract_text(b"fake .doc bytes", DocumentFormat.DOC)

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
from docx.oxml import parse_xml
from docx.oxml.ns import nsdecls

from src.jd_bank.db.models import DocumentFormat
from src.jd_bank.ingest import extract as extract_mod
from src.jd_bank.ingest.extract import (
    MAX_DOCUMENT_BYTES,
    DocumentTooLargeError,
    ExtractionError,
    UnsupportedFormatError,
    extract_text,
    extract_text_from_path,
    stream_sha256,
)
from src.jd_bank.ingest.ingest import compute_sha256

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def test_stream_sha256_agrees_with_compute_sha256(tmp_path: Path) -> None:
    """The two hashers MUST agree, or Tier-1 dedup splits.

    ``compute_sha256`` hashes bytes already in memory (the normal ingest path);
    ``stream_sha256`` hashes a file in chunks (the oversized path, which must never load
    it). They are the same digest over the same content — a file grouped one way by one
    and another way by the other would silently break exact-duplicate detection.
    """
    content = b"a" * (3 * 1024 * 1024 + 7)  # spans several chunks, ends mid-chunk
    path = tmp_path / "big.rtf"
    path.write_bytes(content)

    digest, size = stream_sha256(path)
    assert digest == compute_sha256(content)
    assert size == len(content)


def test_stream_sha256_never_loads_the_whole_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Constant memory is the entire reason this function exists: it is what lets an
    89 MB document be a ledger row without ever being loaded. ``read_bytes`` explodes,
    so the only way to pass is to stream."""
    path = tmp_path / "huge.rtf"
    path.write_bytes(b"streamed, never slurped")

    def _explode(self: Path) -> bytes:  # pragma: no cover - must never be called
        raise AssertionError(f"{self} was slurped into memory instead of streamed")

    monkeypatch.setattr(Path, "read_bytes", _explode)
    digest, size = stream_sha256(path)
    assert len(digest) == 64
    assert size == len(b"streamed, never slurped")


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


# ── table / content-control recovery (the .docx extraction defect) ──────────
#
# `doc.paragraphs` (python-docx's high-level API) returns only body-level
# `<w:p>` elements — it skips text inside `<w:tbl>` (tables) and `<w:sdt>`
# (Word content controls). Measured on the real archive: 2,596 of 9,947
# `.docx` lose >40% of their text this way, 24 lose everything. These tests
# pin the fix (a document-order walk of `doc.element.body` that descends into
# both) and the blast-radius guard (plain-paragraph docs are unaffected).


def _old_extract_docx_paragraphs_only(blob: bytes) -> str:
    """The OLD (buggy) extractor, kept here as an oracle: paragraphs only, no
    table/SDT descent. Used both to prove the defect (table/SDT text is
    genuinely absent from its output) and as the literal expression the
    byte-identical guard must match on plain documents."""
    doc = Document(BytesIO(blob))
    return "\n".join(p.text for p in doc.paragraphs if p.text)


def _docx_bytes_with_table(rows: list[list[str]]) -> bytes:
    doc = Document()
    doc.add_paragraph("before-table")
    table = doc.add_table(rows=len(rows), cols=len(rows[0]))
    for r, row in enumerate(rows):
        for c, cell_text in enumerate(row):
            table.cell(r, c).text = cell_text
    doc.add_paragraph("after-table")
    buf = BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _sdt_paragraph_xml(text: str) -> str:
    """A `<w:sdt>` (content control) wrapping a single paragraph run — the
    shape python-docx has no high-level API for, built directly as OOXML."""
    return (
        f'<w:sdt {nsdecls("w")}><w:sdtContent>'
        f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p>"
        "</w:sdtContent></w:sdt>"
    )


def _docx_bytes_with_sdt(text: str = "sdt-content-text") -> bytes:
    doc = Document()
    doc.add_paragraph("before-sdt")
    sdt = parse_xml(_sdt_paragraph_xml(text))
    doc.element.body.insert(1, sdt)  # between the two paragraphs, before sectPr
    doc.add_paragraph("after-sdt")
    buf = BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _docx_bytes_plain_with_tab_break_and_blank_paragraphs() -> bytes:
    """A plain-paragraph doc — no table, no SDT — with the edge cases the
    guard must reproduce exactly: a tab and a line break inside one run's
    text, an empty paragraph, and a whitespace-only paragraph."""
    doc = Document()
    p = doc.add_paragraph()
    run = p.add_run("before-tab")
    run.add_tab()
    run2 = p.add_run("after-tab")
    run2.add_break()
    p.add_run("after-break")
    doc.add_paragraph("")
    doc.add_paragraph("   ")
    doc.add_paragraph("Trailing paragraph.")
    buf = BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _docx_bytes_with_nested_table_and_sdt_in_cell() -> bytes:
    """Table-in-cell (nested table) and SDT-in-cell (nested content control) —
    the recursion the fix must apply to arbitrary nesting depth."""
    doc = Document()
    outer = doc.add_table(rows=1, cols=1)
    outer_cell = outer.cell(0, 0)
    outer_cell.paragraphs[0].text = "outer-cell-text"
    inner = outer_cell.add_table(rows=1, cols=1)
    inner.cell(0, 0).text = "inner-table-text"

    sdt_table = doc.add_table(rows=1, cols=1)
    sdt_cell = sdt_table.cell(0, 0)
    sdt = parse_xml(_sdt_paragraph_xml("sdt-in-cell-text"))
    sdt_cell._tc.append(
        sdt
    )  # noqa: SLF001 — test-only oxml construction, no public API

    buf = BytesIO()
    doc.save(buf)
    return buf.getvalue()


def test_extract_docx_table_text_is_missed_by_paragraphs_only() -> None:
    """Pins the DEFECT: the old paragraphs-only join genuinely cannot see
    table cell text. If this goes red, the oracle below is not testing what
    it claims to."""
    blob = _docx_bytes_with_table([["cell00", "cell01"], ["cell10", "cell11"]])
    old = _old_extract_docx_paragraphs_only(blob)
    assert "cell00" not in old
    assert "cell11" not in old


def test_extract_docx_table_recovered_in_row_column_order() -> None:
    blob = _docx_bytes_with_table([["cell00", "cell01"], ["cell10", "cell11"]])
    text = extract_text(blob, DocumentFormat.DOCX)
    assert "before-table" in text
    assert "after-table" in text
    for cell_text in ("cell00", "cell01", "cell10", "cell11"):
        assert cell_text in text
    assert (
        text.index("cell00")
        < text.index("cell01")
        < text.index("cell10")
        < text.index("cell11")
    )


def test_extract_docx_content_control_text_is_missed_by_paragraphs_only() -> None:
    """Pins the DEFECT: SDT content is invisible to `doc.paragraphs` — this is
    the `Registered_Nurse.docx` case (~6k chars of real JD text, recovered vs 0
    today, its whole body sitting inside a content control)."""
    blob = _docx_bytes_with_sdt("sdt-content-text")
    old = _old_extract_docx_paragraphs_only(blob)
    assert "sdt-content-text" not in old


def test_extract_docx_content_control_recovered() -> None:
    blob = _docx_bytes_with_sdt("sdt-content-text")
    text = extract_text(blob, DocumentFormat.DOCX)
    assert "before-sdt" in text
    assert "sdt-content-text" in text
    assert "after-sdt" in text


def test_extract_docx_plain_paragraphs_byte_identical_to_old_output() -> None:
    """THE BLAST-RADIUS GUARD. A .docx with no <w:tbl> and no <w:sdt> must
    extract to EXACTLY what the old paragraphs-only expression produced —
    tabs/breaks inside a run, an empty paragraph, and a whitespace-only
    paragraph included. This bounds the fix to only the affected files."""
    blob = _docx_bytes_plain_with_tab_break_and_blank_paragraphs()
    doc = Document(BytesIO(blob))
    old_expression = "\n".join(p.text for p in doc.paragraphs if p.text)

    text = extract_text(blob, DocumentFormat.DOCX)
    assert text == old_expression


def test_extract_docx_nested_table_and_sdt_in_cell_recovered_once_each() -> None:
    """Nesting: table-in-cell and SDT-in-cell must both be recovered, and
    neither double-counted."""
    blob = _docx_bytes_with_nested_table_and_sdt_in_cell()
    text = extract_text(blob, DocumentFormat.DOCX)
    assert text.count("outer-cell-text") == 1
    assert text.count("inner-table-text") == 1
    assert text.count("sdt-in-cell-text") == 1


def test_extract_docx_document_order_preserved() -> None:
    """paragraph, then table, then paragraph -> output preserves that order."""
    blob = _docx_bytes_with_table([["table-cell"]])
    text = extract_text(blob, DocumentFormat.DOCX)
    before, cell, after = (
        text.index("before-table"),
        text.index("table-cell"),
        text.index("after-table"),
    )
    assert before < cell < after


def test_extract_docx_empty_document_extracts_to_empty_string() -> None:
    doc = Document()
    buf = BytesIO()
    doc.save(buf)
    text = extract_text(buf.getvalue(), DocumentFormat.DOCX)
    assert text == ""


def test_extract_docx_excludes_headers_and_footers() -> None:
    """BODY ONLY — a hard invariant. HANDOFF records that for this corpus the
    territorial acknowledgement lives in the document *body* (``document.xml``),
    NOT in ``footer*.xml``, and that the whole validation/HR baseline reads body
    text — so pulling header/footer text in would silently MOVE HR numbers.

    The walk is over ``doc.element.body``, which structurally cannot reach the
    header/footer parts, so no mutation is needed to make this meaningful: it is
    a guard against a future well-meaning change that adds ``doc.sections``
    traversal. Both sentinels round-trip into the saved file (asserted via the
    parts) but must be absent from the extracted text.
    """
    doc = Document()
    doc.add_paragraph("BODY_SENTINEL")
    section = doc.sections[0]
    section.header.is_linked_to_previous = False
    section.header.paragraphs[0].text = "HEADER_SENTINEL"
    section.footer.is_linked_to_previous = False
    section.footer.paragraphs[0].text = "FOOTER_SENTINEL"
    buf = BytesIO()
    doc.save(buf)
    blob = buf.getvalue()

    # The sentinels really are in the document (guards the test itself).
    reloaded = Document(BytesIO(blob))
    assert reloaded.sections[0].header.paragraphs[0].text == "HEADER_SENTINEL"
    assert reloaded.sections[0].footer.paragraphs[0].text == "FOOTER_SENTINEL"

    text = extract_text(blob, DocumentFormat.DOCX)
    assert "BODY_SENTINEL" in text
    assert "HEADER_SENTINEL" not in text
    assert "FOOTER_SENTINEL" not in text


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

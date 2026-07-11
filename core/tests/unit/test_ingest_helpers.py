"""Unit tests for the format-detection, hashing, and archive-walk helpers."""

from __future__ import annotations

from pathlib import Path

from src.jd_bank.db.models import DocumentFormat
from src.jd_bank.ingest.ingest import compute_sha256, detect_format, walk_archive


def test_detect_format_known_extensions() -> None:
    assert detect_format("20191128_JDFN_APSA.docx") == DocumentFormat.DOCX
    assert detect_format("20090701_Clerk.docm") == DocumentFormat.DOCX
    assert detect_format("19820219_Systems.doc") == DocumentFormat.DOC
    assert detect_format("note.rtf") == DocumentFormat.RTF
    assert detect_format("20040301_06983.txt") == DocumentFormat.TXT


def test_detect_format_stacked_extension_uses_last() -> None:
    assert detect_format("Rec_Services.doc.doc") == DocumentFormat.DOC
    assert detect_format("Manager.doc.doc.doc") == DocumentFormat.DOC


def test_detect_format_unsupported_is_other() -> None:
    for name in ("scan.tif", "weird.serv", "resume.pdf", "template.dot", "noext"):
        assert detect_format(name) == DocumentFormat.OTHER


def test_detect_format_case_insensitive() -> None:
    assert detect_format("FILE.DOCX") == DocumentFormat.DOCX


def test_compute_sha256_is_deterministic() -> None:
    a = compute_sha256(b"identical bytes")
    b = compute_sha256(b"identical bytes")
    assert a == b
    assert len(a) == 64
    assert a != compute_sha256(b"different bytes")


def test_walk_archive_yields_files_sorted(tmp_path: Path) -> None:
    (tmp_path / "b.docx").write_bytes(b"b")
    (tmp_path / "a.doc").write_bytes(b"a")
    sub = tmp_path / "nested"
    sub.mkdir()
    (sub / "c.txt").write_bytes(b"c")
    (tmp_path / ".hidden").write_bytes(b"x")

    names = [p.name for p in walk_archive(tmp_path)]
    assert names == sorted(names)
    assert {"a.doc", "b.docx", "c.txt"} <= set(names)
    assert ".hidden" not in names

"""Pure HRIS grade-export parsing (Phase C scaffold). The DB apply lives in
``scripts/import_grades.py``; only the parse is unit-tested here."""

from __future__ import annotations

from src.jd_bank.grade_import import parse_grade_csv

_CSV = """position_number,scheme,grade
90012345,apsa,11
00456789,apsa,7
,apsa,9
00000001,apsa,
00000002,,4
"""


def test_parse_maps_position_number_to_hris_classification() -> None:
    mapping = parse_grade_csv(_CSV)
    assert set(mapping) == {"90012345", "00456789", "00000002"}
    got = mapping["90012345"]
    assert got.scheme == "apsa" and got.value == "11" and got.source == "hris"


def test_rows_missing_position_or_grade_are_skipped() -> None:
    mapping = parse_grade_csv(_CSV)
    assert "" not in mapping  # blank position number dropped
    assert "00000001" not in mapping  # blank grade dropped


def test_blank_scheme_falls_back_to_unknown() -> None:
    mapping = parse_grade_csv(_CSV)
    assert mapping["00000002"].scheme == "unknown"


def test_later_duplicate_wins() -> None:
    mapping = parse_grade_csv("position_number,scheme,grade\n42,apsa,3\n42,apsa,9\n")
    assert mapping["42"].value == "9"


def test_empty_export_is_empty_mapping() -> None:
    assert parse_grade_csv("position_number,scheme,grade\n") == {}

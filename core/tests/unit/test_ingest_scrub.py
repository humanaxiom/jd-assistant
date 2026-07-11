"""Unit tests for incumbent-name normalization (the job-not-person quality step).

Asserts that incumbent field values, emails, and phone numbers are removed and
counted, that ordinary prose survives untouched, and that the report carries no
PII (only tallies).
"""

from __future__ import annotations

from pathlib import Path

from src.jd_bank.ingest.scrub import ScrubReport, normalize_incumbent_names

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def test_removes_name_of_employee_field() -> None:
    clean, report = normalize_incumbent_names(
        "JOB TITLE: Analyst\nNAME OF EMPLOYEE: Jane Doe\nDEPARTMENT: IT\n"
    )
    assert "Jane Doe" not in clean
    assert "NAME OF EMPLOYEE: [name redacted]" in clean
    assert "JOB TITLE: Analyst" in clean  # label preserved, other fields intact
    assert report.names_removed == 1


def test_removes_incumbent_field() -> None:
    clean, report = normalize_incumbent_names("INCUMBENT: John Q. Public")
    assert "John Q. Public" not in clean
    assert report.names_removed == 1


def test_blank_or_placeholder_incumbent_not_counted() -> None:
    clean, report = normalize_incumbent_names("INCUMBENT:\nNAME OF EMPLOYEE: Vacant")
    assert report.names_removed == 0
    assert "Vacant" in clean  # placeholder left as-is


def test_removes_email_and_phone() -> None:
    clean, report = normalize_incumbent_names(
        "Reach the incumbent at jane@example.com or 604-555-0199 today."
    )
    assert "jane@example.com" not in clean
    assert "604-555-0199" not in clean
    assert "[contact redacted]" in clean
    assert report.emails_removed == 1
    assert report.phones_removed == 1


def test_short_digit_runs_survive() -> None:
    # A year range has only 8 digits — below the 10-digit phone threshold.
    clean, report = normalize_incumbent_names("Employed 2002-2007 in the unit.")
    assert "2002-2007" in clean
    assert report.phones_removed == 0


def test_ordinary_text_untouched() -> None:
    src = "The Analyst coordinates priorities and reports progress to the Director."
    clean, report = normalize_incumbent_names(src)
    assert clean == src
    assert not report.changed
    assert report.total_removed == 0


def test_empty_input() -> None:
    clean, report = normalize_incumbent_names("")
    assert clean == ""
    assert isinstance(report, ScrubReport)
    assert report.total_removed == 0


def test_report_is_pii_free_dict() -> None:
    _, report = normalize_incumbent_names(
        "NAME OF EMPLOYEE: Jane Doe\nEmail: jane@example.com\nPhone: 604-555-0199"
    )
    d = report.to_dict()
    assert d == {
        "names_removed": 1,
        "emails_removed": 1,
        "phones_removed": 1,
        "total_removed": 3,
    }
    # No PII string anywhere in the serialized report.
    blob = str(d)
    assert "Jane" not in blob and "example.com" not in blob and "604" not in blob


def test_incumbent_fixture_file() -> None:
    text = (FIXTURES / "incumbent_sample.txt").read_text(encoding="utf-8")
    clean, report = normalize_incumbent_names(text)
    assert "Jane Doe" not in clean
    assert "John Q. Public" not in clean
    assert "jane@example.com" not in clean
    assert report.names_removed == 2
    assert report.emails_removed == 1
    assert report.phones_removed >= 1
    # Real JD content is preserved.
    assert "POSITION SUMMARY" in clean

"""Group-aware grade/classification extraction (Phase A of the grade-capture plan).

The legacy ``grade`` free string is noise; ``extract_classification`` replaces it with a
structured, provenance-carrying :class:`JobClassification`, conservatively:
CUPE prints a numeric pay grade (~64% recoverable), JDFN almost never carries one (it is
assigned post-authoring / in the HRIS), so the extractor returns ``None`` rather than
manufacture a grade. See ``docs/audit/data-state-and-grade-2026-08-01.md``.
"""

from __future__ import annotations

import pytest

from src.jd_core.models.parsed_jd import JobClassification
from src.jd_core.parser.classification import extract_classification

# --- CUPE: the pay grade IS printed on the JD ---------------------------------------


@pytest.mark.parametrize(
    "text,expected",
    [
        ("116902 Secretary, grade 8 Current Position Classification:", "8"),
        ("Classification: Technician GRADE 10", "10"),
        ("Clerk Gr. 6", "6"),
        ("Position: Accounts Clerk, Grade: 7", "7"),
    ],
)
def test_cupe_numeric_grade_is_extracted(text: str, expected: str) -> None:
    got = extract_classification(text, "cupe")
    assert got == JobClassification(scheme="cupe", value=expected, source="parsed")


def test_cupe_without_a_grade_returns_none() -> None:
    assert extract_classification("Guest Services Clerk", "cupe") is None


# --- JDFN: grade is usually ABSENT — do not manufacture it --------------------------


def test_jdfn_blank_grade_approved_returns_none() -> None:
    # The template's field label with no value (the common JDFN case).
    assert (
        extract_classification(
            "Classification & Grade Approved: Position Number:", "apsa"
        )
        is None
    )


def test_jdfn_garbage_after_grade_label_is_not_a_grade() -> None:
    # The exact failure mode of the legacy extractor — "Grade:" grabbing adjacent text.
    assert extract_classification("Department Name/Section: Grade:", "apsa") is None


def test_jdfn_filled_grade_approved_is_captured_with_group_scheme() -> None:
    got = extract_classification("Classification & Grade Approved: 8", "apex")
    assert got == JobClassification(scheme="apex", value="8", source="parsed")


def test_jdfn_pg_prefixed_grade_is_captured() -> None:
    got = extract_classification("Grade Approved: PG 6", "poly")
    assert got == JobClassification(scheme="poly", value="PG 6", source="parsed")


def test_unknown_group_filled_grade_uses_unknown_scheme() -> None:
    got = extract_classification("Grade Approved: 5", None)
    assert got is not None and got.scheme == "unknown" and got.value == "5"


def test_jdfn_does_not_match_a_bare_grade_mention() -> None:
    # A JDFN doc mentioning "grade 12 students" in a duty must NOT become a grade.
    assert (
        extract_classification("Supports grade 12 students in the program", "apsa")
        is None
    )


def test_empty_text_returns_none() -> None:
    assert extract_classification("", "cupe") is None


def test_classification_model_round_trips() -> None:
    c = JobClassification(scheme="cupe", value="8", source="parsed")
    assert JobClassification.model_validate(c.model_dump()) == c

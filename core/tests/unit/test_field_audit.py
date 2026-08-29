"""Unit — reading a labelled identification field out of a raw JD (P3b).

`title` and `employee_group` are the only two fields ever compared against the SOURCE
FILES, and each produced defects on first contact. This is the probe for the ones nobody
has checked, and it answers the question the database cannot:

    the parser stored nothing for this field — does the DOCUMENT say nothing,
    or did the parser fail to read it?

🔴 **The tests that matter here are the ones about the probe's own scope.** The first
version of this probe searched only the registered `wjq.id_labels` spellings and said
"no label found" for 129 of 129 APSA documents while the parser held a department for
52 of them. That is a probe contradicting the parser *in the parser's favour* — broken,
not a finding — and the identification labels having TWO provenances is why.
"""

from __future__ import annotations

import pytest

from src.jd_bank.field_audit import (
    FieldSpec,
    Readability,
    ValuePlacement,
    probe_field,
)
from src.jd_core.parser import headings as hd

#: `department` as the parser really sees it: a WJQ label list AND a modern regex.
_DEPARTMENT = FieldSpec(
    key_words=("department",),
    wjq_labels=("Department Name",),
    modern_rx=hd.DEPARTMENT_LABEL_RX,
)

#: `title` — the CONTROL. Its answer is already known: P3a recovered 805 of them.
_TITLE = FieldSpec(
    key_words=("title",),
    wjq_labels=("Department's Position Title", "Position Title"),
    modern_rx=hd.TITLE_LABEL_RX,
)


# --- the scope defect this probe was rebuilt around --------------------------------


def test_the_modern_templates_bare_label_is_readable_not_a_finding() -> None:
    """🔴 The defect that made the first run of this audit worthless.

    `Department:` is not in `wjq.id_labels` — whose only spelling is `Department Name` —
    so a probe testing that list alone calls it unreadable. But the modern template does
    not use that list at all: `parser/headings.py` reads it with a hardcoded regex, and
    reads it fine. Reporting it as a defect contradicted the parser on 129 of 129 APSA
    documents while the parser plainly held the value.
    """
    hit = probe_field("Department: Graduate Studies", _DEPARTMENT)

    assert hit is not None
    assert hit.readability is Readability.MODERN
    assert hit.value == "Graduate Studies"


def test_a_registered_wjq_spelling_is_readable() -> None:
    """The other provenance. Same field, different mechanism, both registered."""
    hit = probe_field("Department Name: Financial Services", _DEPARTMENT)

    assert hit is not None
    assert hit.readability is Readability.WJQ
    assert hit.value == "Financial Services"


def test_a_name_no_mechanism_can_read_is_the_finding() -> None:
    """🔴 The only column that is a defect.

    `Department Name/Section` is not a `wjq.id_labels` spelling (that match is
    whole-name), and the modern regex allows only a `/unit` suffix — so neither reads
    it, while the document plainly states the department.
    """
    hit = probe_field("Department Name/Section: Financial Services", _DEPARTMENT)

    assert hit is not None
    assert hit.readability is Readability.UNREADABLE
    assert hit.field_name == "Department Name/Section"
    assert hit.value == "Financial Services"


def test_prose_mentioning_the_word_is_not_a_field() -> None:
    """A term list is a hypothesis, and the way this one fails is prose.

    "...liaising with other university departments, or..." must never read as a stated
    department. A field is a LABEL: line-anchored, short, and colon-terminated.
    """
    text = "Researching and liaising with other departments, or universities: various"

    assert probe_field(text, _DEPARTMENT) is None


# --- the value, and the blank-template trap ----------------------------------------


def test_a_label_with_no_value_anywhere_is_not_a_stated_field() -> None:
    """🔴 The trap that made the FIRST P3a fix recover exactly zero.

    A label in the form's blank template header has nothing after it. Counting that as
    "the document states a department" would report a defect where there is only an
    empty form field — a mistake that already cost one released fix that passed its own
    tests and moved nothing.
    """
    hit = probe_field("Department Name:", _DEPARTMENT)

    assert hit is not None
    assert hit.placement is ValuePlacement.NONE
    assert hit.value == ""
    assert not hit.states_a_value


def test_a_value_in_the_next_cell_is_found() -> None:
    """python-docx's render, and antiword's table render: label in one cell, value in
    the next. Both are in the archive and both are real."""
    hit = probe_field(
        "|Department Name:     |Health & Counselling  |", _DEPARTMENT, cells=True
    )

    assert hit is not None
    assert hit.placement is ValuePlacement.NEXT_CELL
    assert hit.value == "Health & Counselling"


def test_a_label_whose_next_cell_is_another_label_has_no_value() -> None:
    """Two labels side by side in the fixed-width render is an EMPTY field, not a
    department called "Classification & Grade Approved"."""
    hit = probe_field(
        "|Department Name: |Classification & Grade Approved: |",
        _DEPARTMENT,
        cells=True,
    )

    assert hit is not None
    assert hit.placement is ValuePlacement.NONE


def test_an_inline_value_stops_at_the_next_label() -> None:
    """antiword prints the NEXT field's label beside this one, in the same cell. Keeping
    it would store "Financial Services Classification & Grade Approved" as a department
    — a confident wrong value, which is worse than an honest blank."""
    hit = probe_field(
        "Department Name/Section: Financial Services Classification & Grade Approved:",
        _DEPARTMENT,
    )

    assert hit is not None
    assert hit.value == "Financial Services"


# --- the control arm ---------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "Department's Position Title: Secretary",
        "Position Title: Secretary",
    ],
)
def test_the_title_spellings_recovered_by_p3a_are_readable(text: str) -> None:
    """`title` is the CONTROL for this whole audit: its answer is already known.

    P3a added the possessive spellings and recovered 805 titles. A probe reporting those
    same documents as unreadable would be measuring its own matching rule rather than
    the archive — the 92%-vs-49% failure in a new costume.
    """
    hit = probe_field(text, _TITLE)

    assert hit is not None
    assert hit.readability is not Readability.UNREADABLE


def test_the_first_label_in_the_document_wins() -> None:
    """Matches `_extract_label`, which returns the FIRST match. A probe that took the
    last would disagree with the parser for a reason that has nothing to do with the
    archive."""
    hit = probe_field("Department: First\nDepartment: Second", _DEPARTMENT)

    assert hit is not None
    assert hit.value == "First"


# --- the probe's own false positives, found by reading its output -------------------


def test_a_key_word_matches_on_word_boundaries_not_substrings() -> None:
    """🔴 The lesson this project already wrote down, and this probe broke anyway.

    `lan` as a substring once matched 1,568 of 2,493 roles — *plan*, *Langara* — and 63%
    is not obviously absurd. Here the key word `grade` matched **upgrade**, so
    "technicians to upgrade and install new software (eg:" was reported four times as
    a document stating a GRADE the parser could not read. A wrong sweep looks exactly
    like a finding.
    """
    spec = FieldSpec(key_words=("grade",), wjq_labels=(), modern_rx=hd.GRADE_LABEL_RX)

    assert (
        probe_field("technicians to upgrade and install software (eg: x", spec) is None
    )
    assert probe_field("Book Chute upgrade: done", spec) is None
    assert probe_field("Grade: 8", spec) is not None


def test_another_fields_label_is_not_this_field() -> None:
    """`Department Position Title` is the TITLE field. It contains "department", so a
    naive key word claimed it as a department the parser could not read — 31 times.

    It is excluded explicitly rather than by ranking key words, because the exclusion is
    the honest statement: this name belongs to another field, and this field says
    nothing about it.
    """
    spec = FieldSpec(
        key_words=("department",),
        wjq_labels=("Department Name",),
        modern_rx=hd.DEPARTMENT_LABEL_RX,
        exclude=("title",),
    )

    assert probe_field("Department Position Title: Clerk", spec) is None
    assert probe_field("Department Name: Registrar", spec) is not None


def test_a_repeated_space_in_a_label_is_a_real_unreadable_name() -> None:
    """The finding the false positives were hiding.

    `_extract_label` strips and lower-cases but never COLLAPSES internal whitespace, so
    `Position  Title` (two spaces) is not `Position Title` and matches nothing. The
    archive carries these across every field — `Department  Name`,
    `Classification  & Grade Approved`, `IDENTIFICATION   Position Number`.
    """
    spec = FieldSpec(
        key_words=("title",),
        wjq_labels=("Position Title",),
        modern_rx=None,
    )
    hit = probe_field("Position  Title: Secretary", spec)

    assert hit is not None
    assert hit.readability is Readability.UNREADABLE
    assert hit.field_name == "Position  Title", "the verbatim name is the evidence"
    assert hit.value == "Secretary"


def test_a_key_word_ending_in_punctuation_still_matches() -> None:
    """🔴 The regression the word-boundary fix CAUSED, caught by re-measuring.

    `\b` asserts a word/non-word transition, so `\bposition #\b` cannot match
    `Position #:` — `#` is not a word character and neither is the `:` after it. The fix
    for one substring bug silently created a boundary bug on punctuation-terminated
    terms, and APSA `position_number` fell from 4,836 readable to 310 while the parser
    still held 4,753. **A probe that suddenly disagrees with the parser by 4,443 is
    reporting its own defect.**

    The rule wanted is "not adjacent to an alphanumeric", which is what the substring
    trap was really about — not the `\b` transition specifically.
    """
    spec = FieldSpec(
        key_words=("position number", "position #"),
        wjq_labels=("Position Number(s)",),
        modern_rx=hd.POSITION_NO_LABEL_RX,
    )

    assert probe_field("Position #: 00110757", spec) is not None
    assert probe_field("Position Number(s): 01167", spec) is not None
    # ...and the substring trap stays closed.
    assert probe_field("Superposition numbers: many", spec) is None

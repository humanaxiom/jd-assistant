"""Parser v9 — a wrapped content line is not a section heading (HR-298, HR-299).

antiword hard-wraps a legacy ``.doc`` at its column width, so a sentence's last word can
land alone on its own physical line. When that word is a heading's word, the segmenter's
``fullmatch`` read it as the heading and opened a section mid-sentence. MEASURED over
all 14,522 extracted archive files (2026-10-27): 38 heading matches in the JDFN/legacy
reader are all-lower-case lines, and all 38 are wraps — 21 of them the Decision Making
prompt "Decisions the incumbent is expected to make in carrying out / duties", which
filed every decision (made AND referred) under DUTIES and left Decision Making holding
the prompt alone. The rest open RELATIONSHIPS or QUALIFICATIONS halfway through a
qualification ("… effective collegial / relationships"; "… combination of / education
and experience"), so every later qualification moved section.

The shapes below are copied from the archive files named on each test — except the
qualification heading: those files write ``H. Entrance Qualifications``, which matches
NO heading pattern (a separate gap, 4,678 documents; plan §18), so the fixtures use
``Qualifications`` to put the wrap inside a Qualifications section. The must-not-
demote cases are the real headings the guard sits next to: an enumerated lower-case
heading (``1. position identification`` after ``JOB DESCRIPTION``, in two files), upper-
and mixed-case headings after an unpunctuated line (``Entrance`` / ``Qualifications``,
``Primary Working Relationships``), and any heading after a blank line or a closed line.
"""

from __future__ import annotations

import pytest

from src.jd_core.parser import parse_jd
from src.jd_core.parser.headings import SectionKey
from src.jd_core.parser.segmenter import _segment
from src.jd_core.rules import get_rules

_HEAD = (
    "SIMON FRASER UNIVERSITY\n"
    "POSITION DESCRIPTION\n"
    "A. IDENTIFICATION\n"
    "Position Title: Marketing and Outreach Coordinator\n"
    "B. POSITION SUMMARY\n"
    "Coordinates outreach for career and learning services.\n"
    "C. DUTIES AND RESPONSIBILITIES\n"
    "      •    Maintains the HCC Self-help Library and coordinates a regular\n"
    "         review of resources (print and electronic)\n"
    "      •    Performs other duties as requested\n"
    "\n"
)


def _seg() -> object:
    return get_rules().segmentation


# ── The Decision Making prompt (20061205_697.doc, 20030609_00001661 …) ──────────────

_DM_WRAP = _HEAD + (
    "D.         DECISION MAKING\n"
    "\n"
    "      i)    Decisions the incumbent is expected to make in carrying out\n"
    "      duties\n"
    "\n"
    "      •     Coordinates scheduling and the assignment of career and learning\n"
    "      skills peer educators.\n"
    "      •     Develops procedures to guide operations of Outreach Services.\n"
    "\n"
    "      ii) Types of decisions the incumbent would refer to his/her\n"
    "      supervisor.\n"
    "\n"
    "      •     Budget requests\n"
    "      •     Space allocations\n"
    "\n"
    "E. SUPERVISION EXERCISED\n"
    "None.\n"
)


def test_the_wrapped_dm_prompt_keeps_its_decisions_in_decision_making() -> None:
    jd = parse_jd(_DM_WRAP).jd

    assert jd.decision_making[0] == (
        "Decisions the incumbent is expected to make in carrying out duties"
    )
    assert (
        "Coordinates scheduling and the assignment of career and learning skills "
        "peer educators." in jd.decision_making
    )
    assert "Budget requests" in jd.decision_making
    assert "Space allocations" in jd.decision_making
    statements = [d.statement for d in jd.duties]
    assert not any("Coordinates scheduling" in s for s in statements)
    assert not any("Budget requests" in s for s in statements)
    assert any("Self-help Library" in s for s in statements)


def test_a_wrapped_dm_prompt_with_a_colon_and_square_bullets() -> None:
    """20060906__00001664_…Bus_Admin.doc, 20220414_00101778_JDFN_APSA_20220411.doc."""
    text = _HEAD + (
        "D. DECISION MAKING\n"
        "i) Decisions the incumbent is expected  to  make  in  carrying  out\n"
        "duties:\n"
        "▪ Decides on content, design and delivery of workshops, mock\n"
        "  interviews and networking events\n"
        "E. SUPERVISION EXERCISED\n"
        "None.\n"
    )
    jd = parse_jd(text).jd

    assert any("Decides on content" in d for d in jd.decision_making)
    assert not any("Decides on content" in d.statement for d in jd.duties)


# ── Qualifications that wrap onto a heading word ─────────────────────────────────────


def test_a_wrapped_relationships_word_does_not_take_the_qualifications() -> None:
    """20050623_00076018Program_director.doc and 13 more files."""
    text = _HEAD + (
        "H.     Qualifications\n"
        "    •    Master's degree in an appropriate discipline\n"
        "    •    Demonstrated ability to develop and maintain effective collegial\n"
        "    relationships\n"
        "    •    Demonstrated knowledge of the curricular area\n"
        "    •    Excellent leadership and educational innovation skills\n"
    )
    jd = parse_jd(text).jd
    quals = [q.text for q in jd.qualifications]

    assert (
        "Demonstrated ability to develop and maintain effective collegial relationships"
        in quals
    )
    assert "Demonstrated knowledge of the curricular area" in quals
    assert "Excellent leadership and educational innovation skills" in quals
    assert jd.relationships is None


def test_a_wrapped_education_and_experience_stays_inside_its_qualification() -> None:
    """20050929_00097103Systems_consultantI.doc: the wrap leaves "of" alone above it."""
    text = _HEAD + (
        "H. QUALIFICATIONS\n"
        "       • Bachelor's degree in Computing Science or an equivalent combination\n"
        "         of\n"
        "         education and experience\n"
        "       • Three years related experience\n"
    )
    quals = [q.text for q in parse_jd(text).jd.qualifications]

    assert quals[0] == (
        "Bachelor's degree in Computing Science or an equivalent combination of "
        "education and experience"
    )
    assert "Three years related experience" in quals


# ── Real headings the guard must never demote ───────────────────────────────────────


@pytest.mark.parametrize(
    ("prev", "line", "section"),
    [
        # Enumerated lower-case headings (20010823_00062087Secretary.doc, 20011004_…).
        ("JOB DESCRIPTION", "1.  position identification", SectionKey.IDENTIFICATION),
        (
            "Office hours vary",
            "12. additional information",
            SectionKey.ADDITIONAL_CONTEXT,
        ),
        ("Office hours vary", "c) duties", SectionKey.DUTIES),
        # Upper / mixed case after an unpunctuated line (19820219_00001211 …, JDFN).
        ("Minimum Entrance", "Qualifications", SectionKey.QUALIFICATIONS),
        (
            "approving leaves of absence",
            "Primary Working Relationships",
            SectionKey.RELATIONSHIPS,
        ),
        (
            "strategy to meet those needs",
            "D.     Decision Making",
            SectionKey.DECISION_MAKING,
        ),
        ("Hiring external suppliers and resources", "DUTIES", SectionKey.DUTIES),
        # Lower case, but the line above it is CLOSED: a heading, not a wrap.
        ("Reports to the Director.", "duties", SectionKey.DUTIES),
        ("Key areas:", "qualifications", SectionKey.QUALIFICATIONS),
        # The first line of a document has nothing to wrap from.
        ("", "qualifications", SectionKey.QUALIFICATIONS),
    ],
)
def test_a_real_heading_is_never_demoted(
    prev: str, line: str, section: SectionKey
) -> None:
    lines = [prev, line, "Some content."] if prev else [line, "Some content."]
    sections, heading_lines = _segment(lines, _seg())  # type: ignore[arg-type]

    assert section in sections
    assert lines.index(line) in heading_lines


def test_a_lower_case_heading_after_a_blank_line_is_a_heading() -> None:
    lines = ["Works under general direction", "", "duties", "Some content."]
    sections, heading_lines = _segment(lines, _seg())  # type: ignore[arg-type]

    assert SectionKey.DUTIES in sections
    assert 2 in heading_lines


def test_a_wrapped_word_is_content_of_the_section_above_it() -> None:
    lines = [
        "D. DECISION MAKING",
        "i) Decisions the incumbent is expected to make in carrying out",
        "duties",
        "• Approves expenses",
    ]
    sections, heading_lines = _segment(lines, _seg())  # type: ignore[arg-type]

    assert heading_lines == {0}
    assert set(sections) == {SectionKey.DECISION_MAKING}
    assert (
        "carrying out\nduties\n• Approves expenses"
        in sections[SectionKey.DECISION_MAKING]
    )


# ── The rule is rulebook data ────────────────────────────────────────────────────────


def test_the_wrap_guard_is_rulebook_data(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.jd_core import rules as rules_mod

    real = get_rules()

    def tuned(**update: object) -> None:
        r = real.model_copy(
            update={"segmentation": real.segmentation.model_copy(update=update)}
        )
        monkeypatch.setattr(rules_mod, "get_rules", lambda: r)

    tuned(wrapped_heading_guard=False)
    off = parse_jd(_DM_WRAP).jd
    assert any("Coordinates scheduling" in d.statement for d in off.duties)

    # The prompt line ends "carrying out": make "t" a closer and that line counts as
    # CLOSED, so "duties" is read as a heading again.
    tuned(wrapped_heading_line_closers=".:;?!t")
    closed = parse_jd(_DM_WRAP).jd
    assert any("Coordinates scheduling" in d.statement for d in closed.duties)

    tuned()
    on = parse_jd(_DM_WRAP).jd
    assert not any("Coordinates scheduling" in d.statement for d in on.duties)

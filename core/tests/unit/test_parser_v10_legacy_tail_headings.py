"""Parser v10 — the old APSA form's lettered tail headings (HR-300, 301, 305 … 308).

The pre-2024 APSA position description ends ``F. Supervision Received`` /
``G. Unusual Working Conditions`` / ``H. Entrance Qualifications`` /
``I. Organizational Relationships`` / ``J. Approvals``. Only ``F`` was a heading the
segmenter knew, so everything after it ran into Relationships and was cut at the
600-character supervisory ceiling. MEASURED over all 14,522 extracted archive files
(2026-10-27): ``ENTRANCE QUALIFICATIONS`` heads 4,666 lettered files (+87 unlettered),
and in 4,649 of the 4,678 JDFN documents carrying it the qualifications reached the
parse only as far as that cut — 38 of them had any qualifications at all. Owner
rulings 2026-10-27: recognise H/I/J before the one full rebuild; DROP G (the 2024
template has no slot for working conditions) but RECORD the drop, never silently.

The shapes below are the archive's own (named on each test).
"""

from __future__ import annotations

import pytest

from src.jd_core.models.parsed_jd import SFUJobDescription
from src.jd_core.parser import parse_jd
from src.jd_core.rules import get_rules

_HEAD = (
    "SIMON FRASER UNIVERSITY\n"
    "POSITION DESCRIPTION\n"
    "A. IDENTIFICATION\n"
    "Position Title: Co-op Education Coordinator\n"
    "B. POSITION SUMMARY\n"
    "Coordinates the co-op program for Applied Sciences.\n"
    "C. DUTIES AND RESPONSIBILITIES\n"
    "      •    Develops co-op placements with employers.\n"
    "D. DECISION MAKING\n"
    "      •    Decides which students to refer to employers.\n"
    "E. SUPERVISION EXERCISED\n"
    "      Number of employees reporting directly to the position: 0\n"
    "F.    SUPERVISION RECEIVED\n"
    "      Works under the general direction of the Co-op Education Director.\n"
    "\n"
)

#: 20060327_00064771Coop_educ_coordinator.doc / 20061029_1661.doc: the whole tail.
_TAIL = _HEAD + (
    "G.    UNUSUAL WORKING CONDITIONS\n"
    "      Some evening and weekend work is required\n"
    "\n"
    "H.    ENTRANCE QUALIFICATIONS\n"
    "      What combination of experience, training and/or formal education do you\n"
    "      believe is the minimum required to perform the duties of this position?\n"
    "\n"
    "      •    Master's degree in an appropriate discipline\n"
    "      •    Four years' successful related experience\n"
    "\n"
    "I.    ORGANIZATIONAL RELATIONSHIPS\n"
    "      Indicate in the appropriate blocks the title of the position to which\n"
    "      this position reports and the titles of positions reporting directly\n"
    "      to it. If more detail is required, add additional blocks.\n"
    "                               Co-op Education Director\n"
    "                        Co-op Education Coordinators (this position)\n"
    "\n"
    "J.    APPROVALS\n"
    "Incumbent's Signature:                       Date:\n"
    "Supervisor's Signature:                            Date:\n"
    "SHOULD YOU REQUIRE FURTHER ASSISTANCE IN COMPLETING THIS POSITION\n"
    "DESCRIPTION, PLEASE FEEL FREE TO REFER TO YOUR SUPERVISOR.\n"
)


def _quals(jd: SFUJobDescription) -> list[str]:
    return [q.text for q in jd.qualifications]


def test_entrance_qualifications_opens_the_qualifications() -> None:
    jd = parse_jd(_TAIL).jd

    assert "Master's degree in an appropriate discipline" in _quals(jd)
    assert "Four years' successful related experience" in _quals(jd)


def test_the_forms_printed_question_is_set_aside_not_a_qualification() -> None:
    jd = parse_jd(_TAIL).jd
    prompts = [b for b in jd.set_aside if b.kind == "form_prompt"]

    assert not any(q.startswith("What combination") for q in _quals(jd))
    assert prompts[0].text.startswith("What combination of experience, training")
    assert prompts[0].text.endswith("duties of this position?")


def test_an_unbulleted_answer_no_longer_fuses_onto_the_question() -> None:
    """3,131 legacy files: the answer under the question has no bullets, so it ran on
    from the question as ONE item and was cut at 400 characters (MEASURED: 2,329 of the
    4,957 items over 400 started with the question)."""
    text = _HEAD + (
        "H. ENTRANCE QUALIFICATIONS\n"
        "What combination of experience, training and/or formal education do you\n"
        "believe is the minimum required to perform the duties of this position?\n"
        "Undergraduate degree and three years of related experience.\n"
    )
    assert _quals(parse_jd(text).jd) == [
        "Undergraduate degree and three years of related experience."
    ]


def test_an_over_long_qualification_is_split_at_sentences_not_cut() -> None:
    """20060307_00001390IT_coordinator.doc: unbulleted requirements run together; the
    400-character cut (HR-308) dropped "…without formal authority" and everything after.
    """
    reqs = [
        "Undergraduate degree and three years work experience or a combination of "
        "equivalent education and experience.",
        "Demonstrated ability to provide leadership to IT staff and successfully help "
        "the team reach creative and productive solutions.",
        "Effective communications and interpersonal skills.",
        "Ability to achieve objectives working with a range of "
        "Management/Faculty/Staff without formal authority.",
        "Working knowledge of Microsoft desktop systems, TCP/IP networking, LAN and "
        "server security.",
    ]
    text = _HEAD + "H. ENTRANCE QUALIFICATIONS\n" + "\n".join(reqs) + "\n"
    quals = _quals(parse_jd(text).jd)

    assert " ".join(quals) == " ".join(reqs)
    assert all(
        len(q) <= get_rules().segmentation.qualification_max_chars for q in quals
    )


def test_the_decision_making_make_prompt_is_set_aside_not_a_decision() -> None:
    """20061205_697.doc and 26 more: "i) Decisions the incumbent is expected to make in
    carrying out / duties" is the form's question, never a decision. The deterministic
    (--no-llm) draft carried it into 6 v9 merge drafts."""
    text = _HEAD.replace(
        "D. DECISION MAKING\n"
        "      •    Decides which students to refer to employers.\n",
        "D. DECISION MAKING\n"
        "      i)    Decisions the incumbent is expected to make in carrying out\n"
        "      duties\n"
        "\n"
        "      •     Coordinates scheduling of peer educators.\n",
    )
    jd = parse_jd(text).jd
    prompts = [b.text for b in jd.set_aside if b.kind == "form_prompt"]

    assert jd.decision_making == ["Coordinates scheduling of peer educators."]
    assert prompts == [
        "i) Decisions the incumbent is expected to make in carrying out duties"
    ]


def test_the_long_decision_question_is_not_cut_in_half() -> None:
    """The longer edition ("Give some typical examples of the most important decisions
    the incumbent is expected to make …") CONTAINS the short one; it is the rewrite's to
    strip (HR-275), and the parser must not leave "Give some typical examples of the
    most important" behind."""
    q = (
        "Give some typical examples of the most important decisions the incumbent is "
        "expected to make in carrying out the duties and responsibilities of the "
        "position."
    )
    text = _HEAD.replace("D. DECISION MAKING\n", f"D. DECISION MAKING\n      i)  {q}\n")
    assert parse_jd(text).jd.decision_making[0] == q


def test_the_tail_never_runs_into_the_supervisory_text() -> None:
    sup = parse_jd(_TAIL).jd.relationships.supervisory or ""  # type: ignore[union-attr]

    assert "Co-op Education Director." in sup  # F, as before
    for foreign in (
        "Master's degree",
        "evening and weekend",
        "Signature",
        "ASSISTANCE",
    ):
        assert foreign not in sup


def test_organizational_relationships_is_relationships() -> None:
    sup = parse_jd(_TAIL).jd.relationships.supervisory or ""  # type: ignore[union-attr]

    assert "Co-op Education Coordinators (this position)" in sup


def test_unusual_working_conditions_is_set_aside_and_recorded() -> None:
    jd = parse_jd(_TAIL).jd
    kept = {b.kind: b for b in jd.set_aside}

    assert kept["legacy_working_conditions"].text == (
        "Some evening and weekend work is required"
    )
    assert kept["legacy_working_conditions"].heading == "UNUSUAL WORKING CONDITIONS"
    assert "evening and weekend" not in (jd.position_summary or "")
    assert not any("evening" in q for q in _quals(jd))


def test_the_approvals_block_is_set_aside_never_content() -> None:
    jd = parse_jd(_TAIL).jd
    kept = {b.kind: b for b in jd.set_aside}

    assert "Incumbent's Signature" in kept["form_approvals"].text
    assert not any("Signature" in q for q in _quals(jd))


def test_approvals_right_after_the_qualifications_does_not_join_them() -> None:
    """Some files have no I. block: J follows H directly."""
    text = _HEAD + (
        "H. ENTRANCE QUALIFICATIONS.\n"
        "• Bachelor's degree\n"
        "J. APPROVALS\n"
        "Incumbent's Signature: Date:\n"
    )
    assert _quals(parse_jd(text).jd) == ["Bachelor's degree"]


@pytest.mark.parametrize(
    ("heading", "kind"),
    [
        ("H. ENTRANCE QUALIFICATIONS.", "q"),  # 11 files carry the full stop
        ("ENTRANCE QUALIFICATIONS", "q"),  # 87 files, unlettered
        ("H.\tEntrance Qualifications:", "q"),
        ("I. ORGANISATIONAL RELATIONSHIPS", "r"),  # 16 files
        ("I. ORGANIZATIONAL RELATIONSIPS", "r"),  # 11 files (sic)
        ("ORGANIZATIONAL RELATIONSHIPS", "r"),  # 311 files, unlettered
        ("G. UNUSUAL WORKING CONDITIONS (CONTINUED)", "g"),  # 13 files
        ("UNUSUAL WORKING CONDITIONS", "g"),  # 141 files, unlettered
        ("J. APPROVAL", "j"),  # 5 files
        ("APPROVALS", "j"),  # 341 files, unlettered
        # The 16 files the 2026-10-29 review found with their qualifications set
        # aside as working conditions (docs/audit/2026-10-29-parser-v10-review.md §2):
        ("H. QUALIFICATIONS REQUIRED", "q"),  # 6 files (5 coach JDs)
        ("H         ENTRANCE QUALIFICATIONS", "q"),  # 4 files: letter, no period
        ("ENTRANCE OUALIFICATIONS", "q"),  # 2 files, OCR O for Q
        ("H. ENTRANCE QUALIFIACTIONS", "q"),  # 2 files
        ("H. ENTRANCE OUALIFICIATIONS", "q"),  # 1 file
        ("H. ENTRANCE QUALIFICATIONS TO BE REVIEWED", "q"),  # 1 file
        ("G\tUNUSUAL WORKING CONDITIONS", "g"),  # letter + tab, no period
        ("J         APPROVALS", "j"),  # letter + spaces, no period
    ],
)
def test_the_archive_spellings(heading: str, kind: str) -> None:
    text = _HEAD + f"{heading}\n• Payload line here\n"
    jd = parse_jd(text).jd
    sup = jd.relationships.supervisory or ""  # type: ignore[union-attr]
    aside = [b.text for b in jd.set_aside]

    if kind == "q":
        assert _quals(jd) == ["Payload line here"]
    elif kind == "r":
        assert "Payload line here" in sup
    else:
        assert any("Payload line here" in t for t in aside)
        assert "Payload line here" not in sup


def test_a_misspelled_qualifications_heading_is_not_working_conditions() -> None:
    """20010201_00000224Head_men_s_soccer_coach.doc and 15 others: with the H heading
    unrecognised, the G block ran on through the whole qualifications section, which
    was set aside as working conditions and the JD got 0 qualifications."""
    text = _HEAD + (
        "G. UNUSUAL WORKING CONDITIONS\n"
        "Evening and week-end hours during the season.\n"
        "H. QUALIFICATIONS REQUIRED\n"
        "• University degree in kinesiology, physical education, coaching\n"
        "• Minimum of 5 years coaching experience\n"
    )
    jd = parse_jd(text).jd
    aside = [b.text for b in jd.set_aside if b.kind == "legacy_working_conditions"]

    assert _quals(jd) == [
        "University degree in kinesiology, physical education, coaching",
        "Minimum of 5 years coaching experience",
    ]
    assert aside == ["Evening and week-end hours during the season."]


def test_a_plain_qualifications_heading_is_still_the_jdfn_one() -> None:
    """The widened legacy pattern must not claim the modern form's own heading or
    ordinary content: `QUALIFICATIONS` alone keeps its JDFN reading."""
    jd = parse_jd(_HEAD + "QUALIFICATIONS\n• Bachelor's degree\n").jd
    assert _quals(jd) == ["Bachelor's degree"]
    assert not [b for b in jd.set_aside if b.kind == "legacy_working_conditions"]


def test_a_wrapped_approval_word_stays_content() -> None:
    """20060809_00031727_Faculty_Assistant.doc: "…subject to / approval." wraps."""
    text = _HEAD + (
        "H. ENTRANCE QUALIFICATIONS\n"
        "• Experience preparing budget submissions for Dean's\n"
        "   approval.\n"
        "• Excellent communication skills\n"
    )
    jd = parse_jd(text).jd

    assert "Excellent communication skills" in _quals(jd)
    assert jd.set_aside == []


def test_the_four_documents_the_wrap_guard_cost_are_whole_again() -> None:
    """20050929_00097103Systems_consultantI.doc (and 20051013_00099004,
    20060315_00099045, 20090123_00105512): their only Qualifications heading was the
    wrapped "education and experience" the v10 wrap guard demoted."""
    text = _HEAD + (
        "H. ENTRANCE QUALIFICATIONS\n"
        "\n"
        "       • Bachelor's degree in Computing Science or an equivalent combination\n"
        "         of\n"
        "         education and experience\n"
        "       • Three years related experience\n"
    )
    assert _quals(parse_jd(text).jd) == [
        "Bachelor's degree in Computing Science or an equivalent combination of "
        "education and experience",
        "Three years related experience",
    ]


def test_set_aside_is_left_out_of_a_dump_when_empty() -> None:
    """Every modern parse, and every draft, serializes byte-identically to before."""
    assert "set_aside" not in SFUJobDescription(title="X").model_dump()
    assert "set_aside" not in parse_jd(_HEAD).jd.model_dump()


def test_the_legacy_headings_are_rulebook_data(monkeypatch: pytest.MonkeyPatch) -> None:
    import re

    from src.jd_core import rules as rules_mod

    real = get_rules()
    never = re.compile(r"(?!)")
    tuned = real.model_copy(
        update={
            "segmentation": real.segmentation.model_copy(
                update={
                    "legacy_qualifications_heading_pattern": never,
                    "legacy_working_conditions_heading_pattern": never,
                }
            )
        }
    )
    monkeypatch.setattr(rules_mod, "get_rules", lambda: tuned)
    jd = parse_jd(_TAIL).jd

    assert _quals(jd) == []
    assert "legacy_working_conditions" not in {b.kind for b in jd.set_aside}

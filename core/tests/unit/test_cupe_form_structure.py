"""Track J, PR J2 — the CUPE form's STRUCTURE, authored and exported.

J1 printed HR's "WJQ Custom — Part 1" form with blank cells where the model had
no field. J2 gives the Builder those fields and the export fills them:

* the **major / minor function split** survives answers -> model -> export -> clone, and
  the silent "merge and cut at twelve" is gone — a limit the author is TOLD about
  replaces it (``cupe_form.function_limits``, HR-246);
* each major function carries HR's **(D)/(W)/(M)/(S)** frequency, not a % of time
  (HR-247 — "Annual" is an HR-source contradiction, registered ``open``, not offered);
* sections **5, 6, 7, 12** are HR's fixed levels, ticked; **8, 10, 11** are tables with
  duration / frequency / hours;
* qualifications carry certification, a NUMBER of years, and the equivalency choice
  with its "not acceptable because" rationale (HR-252);
* identification asks the author for the CURRENT classification, the evaluating
  supervisor's title, the date and who completed it — never HR's approved grade, whose
  box stays blank (HR-240);
* Q9 (owner, 2026-10-19, option C): ONE "Occupational Skills" list with optional
  "Knowledge of / Ability to" helpers (HR-251), and a separate Occupational
  Requirement(s) box. Older CUPE drafts holding knowledge / skills / abilities fold into
  the one list on load and on clone — in code, no data migration.

The round trip through the Bank's OWN parser stays the oracle (``tests/export_roundtrip
.py``). Where the parser cannot carry something (its twelve-duty ceiling; equivalency
lines it drops as instructions), the test says so instead of weakening the oracle.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from src.jd_bank.composer.wjq_answers import (
    ContactAnswer,
    EffortAnswer,
    ExposureAnswer,
    FunctionAnswer,
    LocationAnswer,
    MinorFunctionAnswer,
    SkillAnswer,
    WJQAnswers,
)
from src.jd_bank.composer.wjq_assemble import assemble_wjq_jd, wjq_answers_from_jd
from src.jd_bank.db.models import DocumentFormat
from src.jd_bank.ingest.extract import extract_text
from src.jd_core.models.parsed_jd import (
    SFUDuty,
    SFUJobDescription,
    SFUQualification,
    SFURelationships,
    WJQForm,
)
from src.jd_core.parser.segmenter import _MAX_DUTIES, parse_jd
from src.jd_core.rules import CupeForm, Rules, get_rules
from src.jd_core.rules.loader import check_cupe_frequencies_are_parser_readable
from src.jd_export import render_sfu_docx
from tests.export_roundtrip import cupe_export_text_losses, cupe_round_trip_losses
from tests.unit.retuned_rules import raw_cupe_form, retuned_cupe_form


@pytest.fixture(scope="module")
def rules() -> Rules:
    return get_rules()


# HR's own Dec-2024 sample (fixtures/hr/cupe/, S20): 11 major + 3 minor functions, the
# last minor being the catch-all. Trimmed to the shape; the count is the point.
_SAMPLE_MAJORS: list[tuple[str, str, str]] = [
    ("Responds", "Responds to requests for information", "daily"),
    ("Types", "Types letters, reports and general correspondence", "daily"),
    ("Processes", "Processes a variety of forms and documents", "daily"),
    ("Creates", "Creates and maintains system and paper based records", "daily"),
    ("Responds", "Responds to routine and general problems", "daily"),
    ("Provides", "Provides secretarial support for travel and events", "weekly"),
    ("Conducts", "Conducts preliminary reviews of information", "weekly"),
    ("Coordinates", "Coordinates meetings and arranges appointments", "weekly"),
    ("Maintains", "Maintains office files", "weekly"),
    ("Processes", "Processes mail outs", "semester"),
    ("Maintains", "Maintains the integrity of information databases", "semester"),
]
_SAMPLE_MINORS: list[tuple[str, str]] = [
    ("Purges", "Purges and archives records"),
    ("Conducts", "Conducts simple information system and database searches"),
    (
        "Performs",
        "Performs other related duties and responsibilities consistent with the job "
        "description and classification on request",
    ),
]


def _structured(**update: Any) -> WJQAnswers:
    """A CUPE questionnaire with EVERY J2 structure filled in."""
    data: dict[str, Any] = {
        "title": "Department Secretary",
        "department": "Department of History",
        "position_number": "40001",
        "current_classification": "Secretary Grade 6",
        "supervisor_title": "Department Manager",
        "date_completed": dt.date(2026, 10, 19),
        "completed_by": "supervisor",
        "position_summary": "Provides secretarial support to the department.",
        "major_functions": [
            FunctionAnswer(action_verb=v, statement=s, frequency=f)
            for v, s, f in _SAMPLE_MAJORS
        ],
        "minor_functions": [
            MinorFunctionAnswer(action_verb=v, statement=s) for v, s in _SAMPLE_MINORS
        ],
        "level_of_independence_levels": ["B"],
        "level_of_independence": "Works from general instructions.",
        "training_exercised_levels": ["B", "C"],
        "direction_exercised_levels": ["A"],
        "continuing_education_levels": ["B", "D"],
        "contacts": [
            ContactAnswer(
                contact="Students",
                scope="internal",
                duration="< 1 hour",
                frequency="Frequent",
            ),
            ContactAnswer(
                contact="General public",
                scope="external",
                duration="1-2 hours",
                frequency="Occasional",
            ),
        ],
        "impact_of_errors": "Typing errors are caught by the reader.",
        "effort_rows": [
            EffortAnswer(effort="Visual", duration="1-2 hours", frequency="Frequent")
        ],
        "location_rows": [LocationAnswer(location="General office", hours="35 / 35")],
        "uncomfortable_rows": [
            ExposureAnswer(condition="Distracting noise", frequency="Occasional")
        ],
        "hazard_rows": [
            ExposureAnswer(condition="Dealing with complaints", frequency="Occasional")
        ],
        "education": ["High school graduation"],
        "certification": ["Office administration certificate"],
        "experience_years": 2,
        "experience": ["Related office experience"],
        "equivalency": "acceptable",
        "occupational_skills": [
            SkillAnswer(helper="Ability to", text="use standard office applications"),
            SkillAnswer(text="55 wpm keyboarding skill"),
        ],
        "occupational_requirements": ["Valid driver's licence"],
    }
    data.update(update)
    return WJQAnswers(**data)


def _reparse(data: bytes) -> SFUJobDescription:
    result = parse_jd(extract_text(data, DocumentFormat.DOCX))
    assert result.template == "wjq", "the export is not recognised as a WJQ form"
    return result.jd


def _lines(data: bytes) -> list[str]:
    return [ln for ln in extract_text(data, DocumentFormat.DOCX).splitlines()]


# ── 1. the major / minor split, and no silent cap ─────────────────────────────────


def test_hrs_fourteen_function_sample_is_assembled_without_dropping_any() -> None:
    """``wjq_assemble.py`` merged majors and minors and cut the list at twelve, so HR's
    own Dec-2024 sample lost its last two minor functions — the catch-all included."""
    jd = assemble_wjq_jd(_structured())
    assert [d.statement for d in jd.duties] == [s for _, s, _ in _SAMPLE_MAJORS]
    assert jd.wjq_form is not None
    assert [d.statement for d in jd.wjq_form.minor_functions] == [
        s for _, s in _SAMPLE_MINORS
    ]


def test_over_the_limit_the_author_is_told_and_nothing_is_cut(rules: Rules) -> None:
    """The limit is visible: past it the assembler REFUSES with the number, the knob
    and the register id — it never truncates."""
    tight = retuned_cupe_form(
        rules, function_limits={"major_functions": 12, "minor_functions": 2}
    )
    with pytest.raises(ValueError) as excinfo:
        assemble_wjq_jd(_structured(), rules=tight)
    message = str(excinfo.value)
    assert "3" in message and "2" in message
    assert "HR-246" in message
    assert "Nothing was removed" in message


def test_a_limit_above_the_models_own_ceiling_is_refused_at_load() -> None:
    raw = raw_cupe_form()
    raw["function_limits"] = {"major_functions": 13, "minor_functions": 12}
    with pytest.raises(ValidationError):
        CupeForm.model_validate(raw)


# ── 2. (D)/(W)/(M)/(S), not % of time ─────────────────────────────────────────────


def test_each_major_function_carries_hrs_frequency_code() -> None:
    jd = assemble_wjq_jd(_structured())
    assert [d.frequency for d in jd.duties] == [f for _, _, f in _SAMPLE_MAJORS]
    # No "(NN%)" is written onto a CUPE function the author did not give one.
    assert not any("%" in d.statement for d in jd.duties)


def test_a_frequency_hrs_template_does_not_offer_is_refused() -> None:
    """ "Annual" is in the writing guide (S14) but not on the template (S13): an HR
    contradiction, registered open (HR-247) — so it is not offered, and a crafted post
    of it is refused visibly rather than stored."""
    bad = _structured(
        major_functions=[
            FunctionAnswer(
                action_verb="Audits", statement="Audits files", frequency="annual"
            )
        ]
    )
    with pytest.raises(ValueError, match="HR-247"):
        assemble_wjq_jd(bad)
    assert "annual" not in get_rules().cupe_form.function_frequencies


def test_every_offered_frequency_is_one_the_parser_reads_back(rules: Rules) -> None:
    """A frequency the WJQ parser has no ``(X)`` marker for could be authored and
    exported but would come back as None — so the rulebook refuses it at load."""
    check_cupe_frequencies_are_parser_readable(rules.cupe_form, rules.wjq)
    tuned = retuned_cupe_form(
        rules, function_frequencies=["daily", "weekly", "monthly", "semester", "annual"]
    )
    with pytest.raises(ValueError, match="annual"):
        check_cupe_frequencies_are_parser_readable(tuned.cupe_form, rules.wjq)


# ── 3. checkbox levels and tables ─────────────────────────────────────────────────


def test_the_checkbox_sections_store_hrs_levels() -> None:
    jd = assemble_wjq_jd(_structured())
    form = jd.wjq_form
    assert form is not None
    assert form.level_of_independence == ["B"]
    assert form.training_exercised == ["B", "C"]
    assert form.direction_exercised == ["A"]
    assert form.continuing_education == ["B", "D"]


def test_level_of_independence_takes_one_box_only() -> None:
    """HR's form: "Check ONE box" for section 5; the other three say "check each"."""
    with pytest.raises(ValueError, match="one"):
        assemble_wjq_jd(_structured(level_of_independence_levels=["A", "B"]))


def test_a_level_the_form_does_not_have_is_refused() -> None:
    with pytest.raises((ValueError, ValidationError)):
        assemble_wjq_jd(_structured(direction_exercised_levels=["F"]))


def test_a_duration_off_hrs_scale_is_refused() -> None:
    bad = _structured(
        effort_rows=[
            EffortAnswer(effort="Visual", duration="all day", frequency="Frequent")
        ]
    )
    with pytest.raises(ValueError, match="HR-248"):
        assemble_wjq_jd(bad)


def test_contact_rows_keep_their_duration_and_frequency() -> None:
    jd = assemble_wjq_jd(_structured())
    assert jd.relationships is not None
    assert jd.relationships.internal == ["Students"]
    assert jd.relationships.external == ["General public"]
    assert jd.wjq_form is not None
    assert [(r.item, r.duration, r.frequency) for r in jd.wjq_form.contacts] == [
        ("Students", "< 1 hour", "Frequent"),
        ("General public", "1-2 hours", "Occasional"),
    ]


# ── 4. qualifications ─────────────────────────────────────────────────────────────


def test_not_acceptable_equivalency_needs_its_rationale() -> None:
    """S14 §13: "If you make this choice, you must describe the rationale" (HR-252)."""
    with pytest.raises(ValueError, match="HR-252"):
        assemble_wjq_jd(_structured(equivalency="not_acceptable"))
    jd = assemble_wjq_jd(
        _structured(
            equivalency="not_acceptable",
            equivalency_rationale="The certificate is a legal requirement.",
        )
    )
    assert jd.wjq_form is not None
    assert jd.wjq_form.equivalency_acceptable is False
    assert (
        jd.wjq_form.equivalency_rationale == "The certificate is a legal requirement."
    )


def test_occupational_skills_are_one_list_with_their_helpers_applied() -> None:
    jd = assemble_wjq_jd(_structured())
    skills = [q.text for q in jd.qualifications if q.kind == "skill"]
    assert skills == [
        "Ability to use standard office applications",
        "55 wpm keyboarding skill",
    ]
    assert not [q for q in jd.qualifications if q.kind in {"knowledge", "ability"}]
    assert jd.wjq_form is not None
    assert jd.wjq_form.occupational_requirements == ["Valid driver's licence"]
    assert jd.wjq_form.certification == ["Office administration certificate"]
    assert jd.wjq_form.experience_years == 2


def test_a_helper_that_is_not_hrs_phrase_is_refused() -> None:
    with pytest.raises(ValueError, match="HR-251"):
        assemble_wjq_jd(
            _structured(
                occupational_skills=[SkillAnswer(helper="Mastery of", text="x")]
            )
        )


# ── 5. identification ─────────────────────────────────────────────────────────────


def test_the_author_gives_the_current_classification_not_hrs_approved_grade() -> None:
    assert "grade" not in WJQAnswers.model_fields
    jd = assemble_wjq_jd(_structured())
    assert jd.wjq_form is not None
    assert jd.wjq_form.current_classification == "Secretary Grade 6"
    assert jd.wjq_form.supervisor_title == "Department Manager"
    assert jd.wjq_form.date_completed == dt.date(2026, 10, 19)
    assert jd.wjq_form.completed_by == "supervisor"
    # Nothing is asserted as HR's approved classification (HR-240).
    assert jd.classification is None


# ── the export fills the form ─────────────────────────────────────────────────────


def test_the_export_fills_every_structured_part_of_hrs_form(rules: Rules) -> None:
    jd = assemble_wjq_jd(_structured())
    assert cupe_export_text_losses(jd, _lines(render_sfu_docx(jd)), rules) == []


def test_the_export_ticks_only_the_chosen_levels(rules: Rules) -> None:
    jd = assemble_wjq_jd(_structured())
    lines = _lines(render_sfu_docx(jd))
    form = rules.cupe_form
    ticked = [ln for ln in lines if ln.startswith(form.checkbox_ticked_glyph)]
    # 1 + 2 + 1 + 2 levels, one completed-by box, one equivalency box.
    assert len(ticked) == 8, ticked
    independence = form.checkbox_options["level_of_independence"]
    assert f"{form.checkbox_ticked_glyph} {independence[1]}" in lines
    assert f"{form.checkbox_glyph} {independence[0]}" in lines


def test_the_hr_box_stays_blank_even_with_a_current_classification(
    rules: Rules,
) -> None:
    jd = assemble_wjq_jd(_structured())
    lines = _lines(render_sfu_docx(jd))
    for label in rules.cupe_form.hr_box_labels:
        i = lines.index(label)
        # HR's label is followed by the next label or a draft row, never a value.
        assert lines[i + 1] not in {"Secretary Grade 6", "6"}


def test_the_oracle_catches_a_dropped_tick(rules: Rules) -> None:
    """The export-text oracle must be able to fail."""
    jd = assemble_wjq_jd(_structured())
    lines = _lines(render_sfu_docx(jd))
    glyph = rules.cupe_form.checkbox_ticked_glyph
    blank = rules.cupe_form.checkbox_glyph
    damaged = [ln.replace(glyph, blank) for ln in lines]
    assert cupe_export_text_losses(jd, damaged, rules)


# ── the round trip through the Bank's own parser ──────────────────────────────────


def test_a_structured_cupe_draft_round_trips_within_the_parsers_ceiling(
    rules: Rules,
) -> None:
    """Twelve functions or fewer: every field the parser can read comes back — the
    minors in order after the majors, the ticks in their sections, the table rows'
    words, the certification and the requirements."""
    answers = _structured(
        major_functions=[
            FunctionAnswer(action_verb=v, statement=s, frequency=f)
            for v, s, f in _SAMPLE_MAJORS[:9]
        ]
    )
    jd = assemble_wjq_jd(answers)
    back = _reparse(render_sfu_docx(jd))
    assert cupe_round_trip_losses(jd, back, rules) == []


def test_fourteen_functions_lose_exactly_the_parsers_ceiling_and_nothing_else(
    rules: Rules,
) -> None:
    """🔴 PARSER BOUNDARY, stated rather than hidden. The Builder keeps and exports all
    fourteen; the Bank's WJQ parser stops reading at its own twelve
    (``segmenter._MAX_DUTIES``) — raising it is a parser change (PARSER_VERSION and a
    re-parse), out of scope for J2. So the only loss on re-read is that count."""
    jd = assemble_wjq_jd(_structured())
    data = render_sfu_docx(jd)
    assert cupe_export_text_losses(jd, _lines(data), rules) == []
    back = _reparse(data)
    assert len(back.duties) == _MAX_DUTIES
    assert cupe_round_trip_losses(jd, back, rules) == [
        f"duties: 14 exported, {_MAX_DUTIES} re-read"
    ]


# ── clone: the split, the frequencies and the structure come back ─────────────────


def test_cloning_an_authored_cupe_draft_gives_back_the_same_answers() -> None:
    answers = _structured()
    again = wjq_answers_from_jd(assemble_wjq_jd(answers))
    assert again == answers


def test_cloning_a_parsed_cupe_role_keeps_every_duty_and_its_frequency() -> None:
    """A parsed role has no split (the parser merges §3 and §4), so every duty comes
    back as a major function — with its (D)/(W)/(M)/(S) now, which the clone used to
    drop."""
    jd = SFUJobDescription(
        title="Clerk",
        employee_group="cupe",
        duties=[
            SFUDuty(action_verb="Files", statement="Files records", frequency="daily"),
            SFUDuty(action_verb="Orders", statement="Orders supplies", frequency=None),
        ],
    )
    answers = wjq_answers_from_jd(jd)
    assert [(f.statement, f.frequency) for f in answers.major_functions] == [
        ("Files records", "daily"),
        ("Orders supplies", None),
    ]
    assert answers.minor_functions == []


# ── existing CUPE drafts: K/S/A fold into the one list (Q9, option C) ─────────────


def test_a_legacy_cupe_draft_with_ksa_clones_into_the_one_skills_list() -> None:
    """The 627 live CUPE roles carry knowledge / skill / ability kinds (measured
    2026-10-19: 1,285 / 3,093 / 3,552 lines). None may be lost. Knowledge + skill land
    in the one Occupational Skills list ("Knowledge of" only before a bare topic,
    HR-253); ability lines go to Occupational Requirement(s) — owner ruling
    2026-10-19, "Abilities → Requirements" (HR-251)."""
    jd = SFUJobDescription(
        title="Clerk",
        employee_group="cupe",
        qualifications=[
            SFUQualification(text="High school graduation", kind="education"),
            SFUQualification(text="Health terminology", kind="knowledge"),
            SFUQualification(text="Good knowledge of accounting", kind="knowledge"),
            SFUQualification(text="Keyboarding", kind="skill", modifier="intermediate"),
            SFUQualification(text="Exercise mature judgment", kind="ability"),
            SFUQualification(text="Ability to follow instructions", kind="ability"),
        ],
    )
    answers = wjq_answers_from_jd(jd)
    assert answers.occupational_skills == [
        SkillAnswer(helper="Knowledge of", text="Health terminology"),
        SkillAnswer(text="Good knowledge of accounting"),
        SkillAnswer(text="intermediate Keyboarding"),
    ]
    assert answers.occupational_requirements == [
        "Exercise mature judgment",
        "Ability to follow instructions",
    ]
    # ...and it assembles back without losing a line.
    rebuilt = assemble_wjq_jd(answers)
    assert len([q for q in rebuilt.qualifications if q.kind == "skill"]) == 3
    assert rebuilt.wjq_form is not None
    assert len(rebuilt.wjq_form.occupational_requirements) == 2


def test_a_live_sized_legacy_role_with_38_ksa_lines_still_clones() -> None:
    """MEASURED 2026-10-19: the most knowledge + skill lines on one live CUPE role is
    38 (the old lists held 20 each), and the most ability lines 20 (the requirements
    box holds 20). Both extremes must still clone and reassemble."""
    jd = SFUJobDescription(
        title="Clerk",
        employee_group="cupe",
        qualifications=[
            *(
                SFUQualification(text=f"Line {i}", kind=("knowledge", "skill")[i % 2])
                for i in range(38)
            ),
        ],
    )
    answers = wjq_answers_from_jd(jd)
    assert len(answers.occupational_skills) == 38
    assert len(assemble_wjq_jd(answers).qualifications) == 38
    abilities = SFUJobDescription(
        title="Clerk",
        employee_group="cupe",
        qualifications=[
            SFUQualification(text=f"Can do {i}", kind="ability") for i in range(20)
        ],
    )
    rebuilt = assemble_wjq_jd(wjq_answers_from_jd(abilities))
    assert rebuilt.wjq_form is not None
    assert len(rebuilt.wjq_form.occupational_requirements) == 20


def test_a_role_with_a_long_point_factor_section_still_clones(rules: Rules) -> None:
    """MEASURED 2026-10-19: 8 of 627 live CUPE roles hold a section longer than the
    4,000 characters each answer field allowed (pre-J2 too), so they could not be
    cloned. A section now takes the model's own context ceiling — and a context over
    THAT is refused with a message, never sliced (the old silent ``[:20000]``)."""
    heading = rules.wjq.section_headings["working_conditions"][0]
    jd = SFUJobDescription(
        title="Clerk",
        employee_group="cupe",
        additional_context=f"{heading}\n" + "word " * 1500,
    )
    answers = wjq_answers_from_jd(jd)
    assert len(answers.working_conditions or "") > 4000
    assert assemble_wjq_jd(answers).additional_context == jd.additional_context.strip()
    too_long = answers.model_copy(
        update={"effort": "x" * 19000, "impact_of_errors": "y" * 19000}
    )
    with pytest.raises(ValueError, match="Nothing was removed"):
        assemble_wjq_jd(too_long)


def test_a_legacy_answers_payload_still_loads() -> None:
    """``answers_json`` written by the pre-J2 page (hidden field in an open browser):
    ``grade``, ``knowledge`` / ``skills`` / ``abilities``, ``internal`` / ``external``
    and a %-allocation must all still load — and nothing in them is dropped."""
    legacy = {
        "title": "Clerk",
        "grade": "CUPE 6",
        "major_functions": [
            {"action_verb": "Files", "statement": "Files records", "allocation": 40}
        ],
        "minor_functions": [{"action_verb": "Purges", "statement": "Purges files"}],
        "internal": ["Faculty"],
        "external": ["Vendors"],
        "knowledge": [{"text": "office procedures", "modifier": "working"}],
        "skills": [{"text": "keyboarding", "modifier": None}],
        "abilities": ["Work occasional evenings"],
    }
    answers = WJQAnswers.model_validate(legacy)
    assert answers.current_classification == "CUPE 6"
    assert answers.major_functions[0].allocation == 40
    assert [(c.contact, c.scope) for c in answers.contacts] == [
        ("Faculty", "internal"),
        ("Vendors", "external"),
    ]
    assert [s.text for s in answers.occupational_skills] == [
        "working office procedures",
        "keyboarding",
    ]
    # Abilities -> Occupational Requirement(s) (owner ruling 2026-10-19, HR-251).
    assert answers.occupational_requirements == ["Work occasional evenings"]
    jd = assemble_wjq_jd(answers)
    assert "(40%)" in jd.duties[0].statement  # the old allocation is not dropped


def test_a_jd_saved_before_j2_still_validates() -> None:
    """``canonical_jds.content`` written before ``wjq_form`` existed."""
    content = SFUJobDescription(title="Clerk", employee_group="cupe").model_dump(
        mode="json"
    )
    content.pop("wjq_form", None)
    assert SFUJobDescription.model_validate(content).wjq_form is None


# ── rulebook wiring ───────────────────────────────────────────────────────────────


def test_the_j2_knobs_are_rulebook_data(rules: Rules) -> None:
    form = rules.cupe_form
    assert dict(form.function_limits) == {"major_functions": 12, "minor_functions": 12}
    assert list(form.function_frequencies) == ["daily", "weekly", "monthly", "semester"]
    assert dict(form.occupational_skills_helpers) == {
        "knowledge": "Knowledge of",
        "ability": "Ability to",
    }
    assert form.equivalency_rationale_required is True
    assert form.single_choice_sections == ("level_of_independence",)


def test_the_model_carries_the_cupe_form_block_untouched_by_the_parser() -> None:
    """The parser never fills ``wjq_form`` (no PARSER_VERSION move): a parsed CUPE
    document has none, which is also how the clone knows a role predates J2."""
    text = (
        "SIMON FRASER UNIVERSITY & C.U.P.E., LOCAL 3338\nWEIGHTED JOB QUESTIONNAIRE "
        "(WJQ) CUSTOM\n1.  POSITION IDENTIFICATION\nDepartment Position Title:\nClerk\n"
    )
    assert parse_jd(text).jd.wjq_form is None
    assert WJQForm().minor_functions == []


def test_the_review_edit_keeps_the_cupe_form_block() -> None:
    """The reviewer's structured editor rebuilds EVERY field; ``wjq_form`` has no
    editor there, so it must ride through unchanged rather than be wiped by an edit."""
    import src.api.main  # noqa: F401 — the routes import back from it
    from src.api.routes.ui import _content_from_form

    jd = assemble_wjq_jd(_structured())
    payload = jd.wjq_form.model_dump_json() if jd.wjq_form else ""
    content = _content_from_form([("title", "Clerk"), ("wjq_form_json", payload)])
    rebuilt = SFUJobDescription.model_validate(content)
    assert rebuilt.wjq_form == jd.wjq_form


def test_the_review_page_carries_the_cupe_form_block_through_an_edit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The other half of the pin above, on the RENDERED page: the reviewer's edit form
    carries ``wjq_form`` as a hidden field whose value reads back to the same block."""
    import html as html_lib
    import json
    import re
    import uuid
    from unittest.mock import AsyncMock

    from tests.unit.test_review_ui import FakeSession, _packet, make_client, ui

    jd = assemble_wjq_jd(_structured())
    canonical_id = uuid.uuid4()
    packet = _packet(canonical_id=canonical_id).model_copy(
        update={"content": jd.model_dump(mode="json")}
    )
    monkeypatch.setattr(ui.service, "get_review_packet", AsyncMock(return_value=packet))
    body = make_client(FakeSession()).get(f"/jd-bank/ui/review/{canonical_id}").text
    match = re.search(r"name=\"wjq_form_json\" value='([^']*)'", body)
    assert match is not None, "the review edit form drops the CUPE form block"
    carried = json.loads(html_lib.unescape(match.group(1)))
    assert WJQForm.model_validate(carried) == jd.wjq_form


def test_relationships_are_still_what_the_validator_reads() -> None:
    jd = assemble_wjq_jd(_structured())
    assert jd.relationships == SFURelationships(
        supervisory=None, internal=["Students"], external=["General public"]
    )


def test_raw_cupe_form_helper_matches_the_shipped_file() -> None:
    assert (
        raw_cupe_form()["version"]
        == yaml.safe_load(
            (
                __import__("pathlib").Path(__file__).resolve().parents[2]
                / "src/jd_core/rules/cupe_form.yaml"
            ).read_text(encoding="utf-8")
        )["version"]
    )

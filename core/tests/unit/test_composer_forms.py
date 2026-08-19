"""The Phase-E routing seam: one form spec per SFU form, selected once.

The measurement behind this design is in
``docs/decisions/cupe-phase-e-routing-seam-2026-08-17.md`` — ~84% of the composer is
already form-blind, and the whole divergence between the two forms is *declarations*.
These tests pin the declarations against each other and against the parser, because a
declaration that drifts is the failure a registry is supposed to make impossible.
"""

from __future__ import annotations

from typing import get_args

import pytest
from pydantic import ValidationError

from src.jd_bank.composer.answers import ComposerAnswers, DutyAnswer, ModifiedQual
from src.jd_bank.composer.forms import (
    FORMS,
    FormSpec,
    form_for,
    form_for_template,
    form_from_request,
    render_kind,
)
from src.jd_bank.composer.questions import load_question_set
from src.jd_bank.composer.wjq_answers import WJQ_CONTEXT_TARGETS, WJQAnswers
from src.jd_bank.composer.wjq_assemble import assemble_wjq_jd, wjq_answers_from_jd
from src.jd_core.models.parsed_jd import SFUJobDescription
from src.jd_core.models.quality import JDTemplate, SFUSection
from src.jd_core.quality.validators import evaluate_jd_rules, template_of
from src.jd_core.rules import get_rules

# --- the registry is complete, and each form produces what it claims -----------------


def test_every_template_has_a_form() -> None:
    """Enumerated from the live ``JDTemplate`` literal, not a hand-written list — the
    ``_SECTION_ANCHORS`` move. Adding a template without deciding how it is authored
    should fail the build, not 500 a route the first time someone picks it."""
    assert set(FORMS) == set(get_args(JDTemplate))
    for template, spec in FORMS.items():
        assert spec.template == template


def test_a_form_that_assembles_the_other_templates_draft_cannot_be_registered() -> None:
    """🔴 THE PROPERTY THAT MAKES THE SEAM SAFE.

    ``template_of`` derives a draft's template from its own ``employee_group``, and the
    validator then judges it by that template's rules (Phase B) and numbers (Phase C).
    So a form spec whose assembler emits a different group than the key it is registered
    under would hand its author a draft scored against **the other form's bar** — the
    exact category error Phases B, C and D removed.

    The guard ASSEMBLES and asks ``template_of``, rather than trusting the assembler's
    docstring, so it cannot be satisfied by a comment.
    """
    with pytest.raises(ValidationError):
        FormSpec(
            template="wjq",
            label="Mislabelled",
            description="claims WJQ, assembles JDFN",
            answers_model=WJQAnswers,
            question_set="composer_questions_wjq_v1",
            # A JDFN-shaped assembler under the wjq key.
            assemble=lambda answers: SFUJobDescription(
                title="x", employee_group="apsa"
            ),
            sections=("identification",),
        )


def test_each_forms_question_set_targets_its_own_answer_contract() -> None:
    """Every question fills a field its form's assembler reads. A target that is not a
    field of THAT form's model would collect an author's answer and silently drop it —
    which is why the check lives at load and takes the model as an argument."""
    for spec in FORMS.values():
        question_set = load_question_set(spec.question_set, spec.answers_model)
        assert question_set.questions
        fields = set(spec.answers_model.model_fields)
        assert {q.target for q in question_set.questions} <= fields


def test_a_question_set_loaded_against_the_wrong_contract_is_refused() -> None:
    """The mutation that proves the check above is doing work: the WJQ set has no
    ``decision_making``/``problem_solving`` and the JDFN model has no
    ``level_of_independence``, so each set must be rejected against the other's model.
    """
    from src.jd_bank.composer.answers import ComposerAnswers
    from src.jd_bank.composer.questions import QuestionSetError

    with pytest.raises(QuestionSetError, match="level_of_independence"):
        load_question_set("composer_questions_wjq_v1", ComposerAnswers)


def test_a_form_is_never_asked_for_a_section_its_instrument_lacks() -> None:
    """The panel-level equivalent of ``applies_to``. 0.0% of CUPE JDs have a Problem
    Solving section and 3.1% an Impact of Decision Making one, because the WJQ does not
    ask — so a CUPE author must not be shown either as unfinished work, and must not be
    asked for SFU boilerplate the form does not carry (HR-201)."""
    wjq = form_for_template("wjq")
    assert "problem_solving" not in wjq.sections
    assert "decision_making" not in wjq.sections
    assert "edi_footer" not in wjq.sections
    # ...while the JDFN form still walks all of them — the untouched control.
    jdfn = form_for_template("jdfn")
    for section in ("problem_solving", "decision_making", "edi_footer"):
        assert section in jdfn.sections
    valid: set[SFUSection] = set(get_args(SFUSection))
    for spec in FORMS.values():
        assert set(spec.sections) <= valid


def test_an_unknown_form_name_falls_back_to_a_page_not_a_422() -> None:
    """The 8.3a lesson: a ``Literal`` path param answers an unknown value with a raw 422
    JSON blob on a surface a person is using, which is the P0.0 defect class. An
    unrecognised form starts the JDFN flow."""
    assert form_from_request("wjq").template == "wjq"
    assert form_from_request("jdfn").template == "jdfn"
    for junk in ("", None, "  ", "WJQ!!", "cupe", 7):
        assert form_from_request(junk).template in {"jdfn", "wjq"}
    assert form_from_request("nonsense").template == "jdfn"


# --- render kinds are DERIVED, and derive to what the JDFN Builder already did -------


def test_the_derived_render_kinds_match_the_shipped_jdfn_builder_exactly() -> None:
    """⚠ THE REGRESSION GUARD FOR A REFACTOR ON A LIVE SURFACE.

    ``render_kind`` replaced four hand-written sets of field names in ``compose_ui``.
    The JDFN Builder is in use, so the derivation has to reproduce the old map field for
    field — this is that map, transcribed from the code it replaced, asserted against
    what the contract now derives. If a future change to the answer model moves a field
    between kinds, this goes red and says which one.
    """
    expected = {
        "title": "text",
        "department": "text",
        "grade": "text",
        "supervisory": "text",  # 600 chars — a text input, as before
        "employee_group": "select",
        "include_sfu_boilerplate": "checkbox",
        "position_summary": "textarea",
        "additional_context": "textarea",
        "duties": "duties",
        "knowledge": "modified",
        "skills": "modified",
        "decision_making": "list",
        "problem_solving": "list",
        "internal": "list",
        "external": "list",
        "education": "list",
        "experience": "list",
        "abilities": "list",
        "cloned_from_cluster_id": "hidden",
    }
    for target, kind in expected.items():
        assert render_kind(ComposerAnswers, target) == kind, target
    # ...and every field of the contract is covered, so the map cannot rot quietly.
    assert set(expected) == set(ComposerAnswers.model_fields)


def test_an_unknown_target_raises_rather_than_rendering_as_a_line_list() -> None:
    """🔴 THE DEFECT THE DERIVATION REMOVES. The old ``_kind_for`` ended in
    ``return "list"``, so a target missing from every set silently became a
    one-item-per-line textarea. Invisible with one form; with two it would have chopped
    the WJQ's point-factor sections into lines and stripped ``major_functions`` of its
    verb and %-allocation columns, with nothing going red."""
    with pytest.raises(KeyError, match="drifted"):
        render_kind(ComposerAnswers, "level_of_independence")


def test_the_wjq_fields_render_as_the_form_needs_rather_than_as_lines() -> None:
    """What the fallback would have got wrong, stated positively."""
    assert render_kind(WJQAnswers, "major_functions") == "duties"
    assert render_kind(WJQAnswers, "minor_functions") == "duties"
    assert render_kind(WJQAnswers, "level_of_independence") == "textarea"
    assert render_kind(WJQAnswers, "working_conditions") == "textarea"
    assert render_kind(WJQAnswers, "title") == "text"
    assert render_kind(WJQAnswers, "internal") == "list"
    assert render_kind(WJQAnswers, "knowledge") == "modified"
    # The WJQ never asks for the employee group — the assembler fixes it.
    assert "employee_group" not in WJQAnswers.model_fields


def test_every_question_in_every_set_has_a_render_kind() -> None:
    """The completeness pin: walk the live question sets, not a list. A question whose
    target cannot be rendered would reach an author as a missing field."""
    for spec in FORMS.values():
        for question in load_question_set(
            spec.question_set, spec.answers_model
        ).questions:
            assert render_kind(spec.answers_model, question.target)


# --- the WJQ assembler mirrors the PARSER --------------------------------------------


def _filled() -> WJQAnswers:
    return WJQAnswers(
        title="Departmental Assistant",
        department="Chemistry",
        grade="9",
        position_summary="Provides administrative support to the department.",
        major_functions=[
            DutyAnswer(action_verb="Processes", statement="Processes purchase orders")
        ],
        minor_functions=[
            DutyAnswer(action_verb="Maintains", statement="Maintains the supply room")
        ],
        internal=["Department chair"],
        external=["Vendors"],
        education=["High school graduation"],
        knowledge=[ModifiedQual(text="Working knowledge of purchasing", modifier=None)],
        level_of_independence="Works under general supervision.",
        impact_of_errors="Delays in ordering.",
        working_conditions="Standard office environment.",
    )


def test_the_point_factor_sections_land_where_the_parser_reads_them() -> None:
    """The round trip this design rests on. ``parser/wjq.py`` stores the point-factor
    sections verbatim in ``additional_context`` under their headings; the Builder writes
    the same sections, under the same heading vocabulary, into the same field — so an
    authored CUPE JD and a parsed one are the same shape."""
    jd = assemble_wjq_jd(_filled())
    context = jd.additional_context or ""
    headings = get_rules().wjq.section_headings

    for target in ("level_of_independence", "impact_of_errors", "working_conditions"):
        assert headings[target][0] in context
    # A section the author left blank prints no empty heading.
    assert headings["effort"][0] not in context


def test_the_context_targets_are_the_rulebooks_own_list() -> None:
    """⚠ THE DRIFT THIS PREVENTS. The parser reads ``wjq.context_sections`` to decide
    which sections belong in ``additional_context``. If the authoring side kept its own
    copy and the two diverged, a section the Builder collected would land somewhere the
    parser never looks — breaking the round trip silently, in the one direction no
    existing test exercises."""
    assert WJQ_CONTEXT_TARGETS == get_rules().wjq.context_sections


def test_a_cupe_draft_claims_no_boilerplate_and_no_hay_prose() -> None:
    """Three things the WJQ form does not contain, so three things an authored CUPE JD
    must not assert: SFU's boilerplate blocks (HR-201), and the Hay
    decision-making/problem-solving prose that ``wjq.yaml`` records must stay empty
    rather than be force-mapped from IMPACT OF ERRORS."""
    jd = assemble_wjq_jd(_filled())
    assert jd.about_sfu_present is False
    assert jd.territorial_acknowledgement_present is False
    assert jd.employment_equity_present is False
    assert jd.decision_making == []
    assert jd.problem_solving == []
    # ...and the impact text is not lost — it is in the section the parser puts it in.
    assert "Delays in ordering" in (jd.additional_context or "")


def test_major_and_minor_functions_truncate_the_way_the_parser_truncates() -> None:
    """The two function sections can carry 24 answers against a 12-duty model, so
    something must give. ``parser/wjq._structure_duties`` takes majors first and stops
    at twelve; matching it means an authored CUPE JD and a parsed one drop the same
    functions, rather than the Builder inventing a second truncation rule."""
    answers = WJQAnswers(
        title="Clerk",
        major_functions=[
            DutyAnswer(action_verb="Does", statement=f"Major function {i}")
            for i in range(12)
        ],
        minor_functions=[
            DutyAnswer(action_verb="Does", statement="Minor function") for _ in range(5)
        ],
    )
    jd = assemble_wjq_jd(answers)

    assert len(jd.duties) == 12
    assert all("Major function" in d.statement for d in jd.duties)


def test_a_cupe_draft_is_judged_by_the_wjq_bar_with_no_further_wiring() -> None:
    """The payoff of fixing ``employee_group`` in the assembler rather than asking for
    it: the draft IS a WJQ document to ``template_of``, so Phase B's rules and Phase C's
    numbers apply to it automatically. Nothing in the Builder, the validator or the
    review path needed a second decision about which form this is."""
    jd = assemble_wjq_jd(_filled())
    assert template_of(jd) == "wjq"
    assert form_for(jd).template == "wjq"

    # The JDFN-only rules are structurally unable to fire on it (Phase B).
    rule_ids = {i.rule_id for i in evaluate_jd_rules(jd, jd.title)}
    assert "SFU-COMP-PROBLEM" not in rule_ids
    assert "SFU-COMP-TERRITORIAL" not in rule_ids


def test_an_empty_wjq_draft_assembles_rather_than_raising() -> None:
    """A draft is filled incrementally, so the assembler must survive an empty answer
    set — the same property the JDFN one has, and what the registry's own validator
    relies on to check each form at construction."""
    jd = assemble_wjq_jd(WJQAnswers())
    assert jd.title == "Untitled role"
    assert jd.employee_group == "cupe"
    assert jd.additional_context is None


# --- the clone transform round-trips a CUPE role (CUPE Phase E) ----------------------


def test_a_cupe_draft_clones_back_into_the_answers_that_built_it() -> None:
    """🔴 THE ROUND TRIP THE WHOLE DESIGN RESTS ON.

    The assembler writes each point-factor section under the heading the PARSER matches;
    the clone transform reads them back by the same vocabulary. If those two ever
    disagree, cloning a CUPE role would silently return blank point-factor sections —
    the author would see an empty form where the role has content, and nothing would
    error. Asserted field by field rather than "it is not empty".
    """
    original = _filled()
    cloned = wjq_answers_from_jd(assemble_wjq_jd(original))

    assert cloned.title == original.title
    assert cloned.department == original.department
    assert cloned.grade == original.grade
    assert cloned.position_summary == original.position_summary
    assert cloned.level_of_independence == original.level_of_independence
    assert cloned.impact_of_errors == original.impact_of_errors
    assert cloned.working_conditions == original.working_conditions
    assert cloned.internal == original.internal
    assert cloned.external == original.external
    assert cloned.education == original.education
    assert [q.text for q in cloned.knowledge] == [q.text for q in original.knowledge]


def test_cloning_returns_every_duty_as_a_major_function() -> None:
    """⚠ The major/minor split is a property of the FORM, and both the assembler and the
    parser merge them into one ``duties`` list — so by the time a JD exists the
    distinction is gone. Guessing a split would put the author's minor functions
    somewhere they did not choose; returning them all as majors keeps every duty, in
    order, where the author can move any of them. Nothing dropped, nothing invented."""
    original = _filled()
    cloned = wjq_answers_from_jd(assemble_wjq_jd(original))

    statements = [d.statement for d in cloned.major_functions]
    assert statements == [
        "Processes purchase orders",
        "Maintains the supply room",  # the MINOR function, kept — not lost
    ]
    assert cloned.minor_functions == []


def test_a_cupe_role_clones_into_the_wjq_contract_not_the_jdfn_one() -> None:
    """The dispatch: `form_for(jd).clone_from_jd` picks the contract from the JD itself.
    Read through the JDFN contract instead, a CUPE role would lose every section that
    form does not ask about — silently, because a missing field is just a blank answer.
    """
    cupe_jd = assemble_wjq_jd(_filled())
    jdfn_jd = SFUJobDescription(title="Analyst", employee_group="apsa")

    assert isinstance(form_for(cupe_jd).clone_from_jd(cupe_jd), WJQAnswers)
    assert isinstance(form_for(jdfn_jd).clone_from_jd(jdfn_jd), ComposerAnswers)


def test_unrecognised_context_text_is_kept_rather_than_dropped() -> None:
    """A JD parsed from a real `.doc` may carry a heading VARIANT the assembler does not
    write. Its context then arrives as one unsplit block — which must land somewhere the
    author can see and edit, never be discarded. Splitting a parsed document perfectly
    is the parser's job; this function's guarantee is Builder → JD → Builder.

    ⚠ **This test used to assert the opposite of its own name** (P0-2 of the
    2026-08-19 review): it pinned ``all(... is None)`` — that the text WAS dropped —
    under a docstring promising it was kept, so fixing the defect would have turned it
    red. It is reachable on live data: ``template_of`` routes on ``employee_group ==
    "cupe"`` alone, so a JDFN document that merely mentions CUPE clones through here
    with ordinary prose in ``additional_context`` and no WJQ heading anywhere in it.
    """
    jd = assemble_wjq_jd(_filled()).model_copy(
        update={"additional_context": "SOME UNKNOWN HEADING\nreal content here"}
    )
    cloned = wjq_answers_from_jd(jd)

    # It landed in the FIRST section — visible to the author, editable, and not lost.
    first = WJQ_CONTEXT_TARGETS[0]
    assert getattr(cloned, first) == "SOME UNKNOWN HEADING\nreal content here"
    assert all(getattr(cloned, t) is None for t in WJQ_CONTEXT_TARGETS[1:])


def test_context_with_no_recognised_heading_at_all_survives_the_clone() -> None:
    """The live shape, not the synthetic one: ordinary prose with no heading of any
    kind. It was discarded ENTIRELY — the loop only kept lines once a canonical heading
    had been seen, and none ever was."""
    jd = assemble_wjq_jd(_filled()).model_copy(
        update={"additional_context": "Works with the registrar during peak periods."}
    )

    cloned = wjq_answers_from_jd(jd)

    assert (
        getattr(cloned, WJQ_CONTEXT_TARGETS[0])
        == "Works with the registrar during peak periods."
    )


def test_a_preamble_before_the_first_heading_is_kept_and_sections_still_split() -> None:
    """The mixed case, which is the one a real `.doc` produces: a header block the
    parser did not strip, then the recognised sections. Keeping the preamble must not
    cost the split — every heading after it still lands in its own field."""
    headings = get_rules().wjq.section_headings
    context = "\n".join(
        [
            "Position Number 12345",
            headings["effort"][0],
            "Sustained keyboarding.",
            headings["working_conditions"][0],
            "Open office.",
        ]
    )
    jd = assemble_wjq_jd(_filled()).model_copy(update={"additional_context": context})

    cloned = wjq_answers_from_jd(jd)

    assert cloned.effort == "Sustained keyboarding."
    assert cloned.working_conditions == "Open office."
    # The preamble went to the first section rather than into the void...
    assert getattr(cloned, WJQ_CONTEXT_TARGETS[0]) == "Position Number 12345"


def test_the_ordinary_round_trip_puts_nothing_extra_in_the_first_section() -> None:
    """The control for the three above: on context this module WROTE, the first
    section holds its own text and nothing else. A "keep the preamble" rule that
    quietly prepended stray lines to every clone would be a new silent corruption."""
    original = _filled()

    cloned = wjq_answers_from_jd(assemble_wjq_jd(original))

    first = WJQ_CONTEXT_TARGETS[0]
    assert getattr(cloned, first) == getattr(original, first)


# --- S-1: the author does not choose the bar their draft is judged against -----------


def test_a_jdfn_author_cannot_move_their_draft_onto_the_cupe_bar() -> None:
    """🔴 S-1 of the 2026-08-19 review, and the runtime twin of
    ``_assembles_its_own_template``.

    Since Phase B ``employee_group`` selects the RULESET, and since Phase C the numeric
    PROFILE. The JDFN Builder passed the posted value straight into the contract with no
    check, and the page's dropdown is not a control — anyone can post a body. Measured
    on identical content: ``apsa`` → 59.38, grade D, blocked on four gates; ``cupe`` →
    89.05, grade B, **approved with zero blocking gates**. One of those gates,
    ``SFU-APPROVE-EDI-FOOTER``, is overridable *with a written reason in the audit log*
    (NN #1) — so a dropdown value was a silent, unaudited override of it.

    The check is ``template_of``, not a list of group names, because ``template_of`` is
    what the validator itself asks. ``excluded`` and an unset group are JDFN documents
    and stay assemblable — refusing them would break cloning the 36 ``excluded``
    documents in the archive for no security gain.
    """
    jdfn = form_for_template("jdfn")

    with pytest.raises(ValueError, match="wjq"):
        jdfn.assemble_checked(ComposerAnswers(title="Analyst", employee_group="cupe"))

    for group in ("apsa", "apex", "poly", "excluded", None):
        jd = jdfn.assemble_checked(
            ComposerAnswers(title="Analyst", employee_group=group)
        )
        assert template_of(jd) == "jdfn"


def test_the_wjq_form_assembles_through_the_same_guard() -> None:
    """The control: the WJQ assembler FIXES the group, so its drafts pass the same
    check unchanged. The guard is on the seam, not on one form."""
    wjq = form_for_template("wjq")

    jd = wjq.assemble_checked(WJQAnswers(title="Departmental Assistant"))

    assert template_of(jd) == "wjq"
    assert jd.employee_group == "cupe"

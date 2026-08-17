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
from src.jd_bank.composer.wjq_assemble import assemble_wjq_jd
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

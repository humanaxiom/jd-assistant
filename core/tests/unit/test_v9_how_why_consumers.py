"""Parser v9 fills ``SFUDuty.how_why`` (owner ruling 2026-10-20, Q1) — every consumer
that read only ``statement`` must now READ it, or the sub-bullets of SFU's "ACTION VERB
… WHAT by" duties vanish one step after the parser recovered them.

One test per consumer changed on this branch (merge, rewrite input + guard; embed text
is in ``test_embed_text.py``); ``docs/plans/PARSER-V9-LISTS-AND-CAPS.md`` §5 has the
full inventory, including the consumers that already read ``how_why``.
"""

from __future__ import annotations

import pytest

from src.jd_bank.jd_text import flatten_jd, outline_jd
from src.jd_bank.rewrite.harmonize import _apply_anti_fabrication
from src.jd_core.bank.merge import duty_text, merge_cluster
from src.jd_core.models.bank import MergedRole, MergeProvenance
from src.jd_core.models.parsed_jd import SFUDuty, SFUJobDescription, SFUQualification
from src.jd_core.rules import get_rules

_GROUPED = SFUDuty(
    action_verb="Manages",
    statement="Manages proposal processes by",
    how_why=["tracking grant deadlines", "preparing project budgets"],
)
_FLAT = SFUDuty(
    action_verb="Manages",
    statement="Manages proposal processes by tracking grant deadlines and preparing "
    "project budgets",
)


def _jd(*duties: SFUDuty, title: str = "Grants Advisor") -> SFUJobDescription:
    return SFUJobDescription(
        title=title,
        position_summary="Supports research funding applications.",
        duties=list(duties),
        qualifications=[SFUQualification(text="Degree in a related field")],
    )


def test_duty_text_is_the_statement_plus_its_clauses() -> None:
    assert duty_text(_GROUPED) == (
        "Manages proposal processes by tracking grant deadlines "
        "preparing project budgets"
    )
    assert duty_text(_FLAT) == _FLAT.statement


def test_merge_matches_a_grouped_duty_with_its_flat_twin() -> None:
    """One source writes the duty as headline + clauses, another as one sentence. On
    the headline alone (3 of 9 tokens) they are two duties; on the whole duty they are
    one — and the representative is the richer, grouped one."""
    merged = merge_cluster([_jd(_GROUPED), _jd(_FLAT, title="Grants Advisor II")])

    assert len(merged.draft.duties) == 1
    assert merged.draft.duties[0].how_why == _GROUPED.how_why


def test_the_rewrite_input_keeps_each_duty_shape() -> None:
    text = outline_jd(_jd(_GROUPED, _FLAT))

    assert (
        "- Manages proposal processes by\n"
        "    - tracking grant deadlines\n"
        "    - preparing project budgets\n"
        f"- {_FLAT.statement}"
    ) in text
    # scanning/evidence text is unchanged: same words, no outline markup
    assert "    - " not in flatten_jd(_jd(_GROUPED))


def test_the_rewrite_cannot_silently_drop_a_duty_s_clauses() -> None:
    """The model returns the duty reworded but WITHOUT its clauses: they are source
    content, so the guard carries the merge's back (as it does for frequency)."""
    merged = MergedRole(
        draft=_jd(_GROUPED),
        provenance=MergeProvenance(member_count=2, skill_frequency=()),
    )
    llm = _jd(
        SFUDuty(action_verb="Manages", statement="Manages the proposal processes by")
    )
    out, _record = _apply_anti_fabrication(llm, merged, get_rules())

    assert out.duties[0].how_why == _GROUPED.how_why


def test_the_rewrite_keeps_clauses_the_model_did_return() -> None:
    merged = MergedRole(
        draft=_jd(_GROUPED),
        provenance=MergeProvenance(member_count=2, skill_frequency=()),
    )
    reworded = ["by tracking deadlines for grants", "by preparing budgets"]
    llm = _jd(
        SFUDuty(
            action_verb="Manages",
            statement="Manages proposal processes",
            how_why=reworded,
        )
    )
    out, _record = _apply_anti_fabrication(llm, merged, get_rules())

    assert out.duties[0].how_why == reworded


def test_clauses_the_model_folded_into_the_statement_are_not_restored_twice() -> None:
    """Review finding (v9): the model returns the duty with its clauses moved INTO the
    statement and an empty ``how_why`` — exactly the case the restore keys on. Carrying
    the merge's clauses back would state every clause twice (once in the statement,
    once under it). The words are already there, so nothing is restored."""
    merged = MergedRole(
        draft=_jd(_GROUPED),
        provenance=MergeProvenance(member_count=2, skill_frequency=()),
    )
    llm = _jd(
        SFUDuty(
            action_verb="Manages",
            statement="Manages proposal processes by tracking grant deadlines and "
            "preparing project budgets",
        )
    )
    out, _record = _apply_anti_fabrication(llm, merged, get_rules())

    assert out.duties[0].how_why == []


def test_one_source_duty_s_clauses_are_restored_onto_one_rewritten_duty() -> None:
    """Review finding (v9): the model splits one grouped duty into two clause-less
    duties that both match it. Restoring onto both would duplicate the clauses in the
    draft; they go back once, onto the first match."""
    merged = MergedRole(
        draft=_jd(_GROUPED),
        provenance=MergeProvenance(member_count=2, skill_frequency=()),
    )
    llm = _jd(
        SFUDuty(action_verb="Manages", statement="Manages the proposal processes by"),
        SFUDuty(action_verb="Manages", statement="Manages proposal processes"),
    )
    out, _record = _apply_anti_fabrication(llm, merged, get_rules())

    assert [d.how_why for d in out.duties] == [_GROUPED.how_why, []]


def test_an_invented_how_why_clause_is_dropped_and_recorded() -> None:
    """Review M2: prompt v3 forbids inventing clauses, but the guard only matched the
    WHOLE duty (Jaccard >= 0.2), so a reworded duty could smuggle in a clause no source
    states. Each clause must now be grounded in its source duty's own text
    (``rewrite.how_why_grounding_threshold``, HR-267); an ungrounded one is dropped and
    recorded — never kept."""
    merged = MergedRole(
        draft=_jd(_GROUPED),
        provenance=MergeProvenance(member_count=2, skill_frequency=()),
    )
    llm = _jd(
        SFUDuty(
            action_verb="Manages",
            statement="Manages proposal processes by",
            how_why=[
                "tracking the grant deadlines",
                "negotiating overseas vendor leases",
            ],
        )
    )
    out, record = _apply_anti_fabrication(llm, merged, get_rules())

    # Review round 2: the model also DROPPED "preparing project budgets". Keeping only
    # its grounded clause would lose that source clause silently. Since 2026-10-20
    # (HR-271) the lost clause is folded back after the model's grounded one, instead
    # of the source's clauses replacing the model's — nothing invented, nothing lost.
    assert out.duties[0].how_why == [
        "tracking the grant deadlines",
        "preparing project budgets",
    ]
    assert record.scrubbed_how_why == ("negotiating overseas vendor leases",)
    assert record.folded_duty_content == ("preparing project budgets",)


def test_when_every_clause_is_invented_the_source_clauses_come_back() -> None:
    merged = MergedRole(
        draft=_jd(_GROUPED),
        provenance=MergeProvenance(member_count=2, skill_frequency=()),
    )
    llm = _jd(
        SFUDuty(
            action_verb="Manages",
            statement="Manages proposal processes by",
            how_why=["negotiating overseas vendor leases"],
        )
    )
    out, record = _apply_anti_fabrication(llm, merged, get_rules())

    assert out.duties[0].how_why == _GROUPED.how_why
    assert record.scrubbed_how_why == ("negotiating overseas vendor leases",)


def test_the_clause_grounding_threshold_is_rulebook_data() -> None:
    assert 0.0 < get_rules().rewrite.how_why_grounding_threshold <= 1.0


def test_a_v9_draft_with_a_long_duty_clones_into_the_builder() -> None:
    """A v9 draft can carry a duty longer than 400 characters (HR-261). Cloning it into
    the Builder must not raise — `DutyAnswer.statement` was narrower than the JD it is
    cloned from."""
    from src.jd_bank.composer.assemble import jd_to_answers

    long_duty = SFUDuty(action_verb="Coordinates", statement="Coordinates " + "x" * 900)
    answers = jd_to_answers(_jd(long_duty))

    assert answers.duties[0].statement == long_duty.statement


_CLAUSES_36 = [f"by doing measured thing number {i}" for i in range(36)]


def test_a_v9_duty_with_36_how_why_points_clones_and_reassembles_whole() -> None:
    """MEASURED on the v9 Bank copy: 1,107 duties in 992 documents carry more than 12
    how/why points (max 36). J4's Builder row held twelve, so cloning such a role into
    the Builder raised. Its limit is the parser's own (HR-265), and the round trip
    clone -> assemble drops and refuses nothing."""
    from src.jd_bank.composer.assemble import assemble_jd, jd_to_answers

    duty = SFUDuty(
        action_verb="Manages",
        statement="Manages complex proposal processes by",
        how_why=_CLAUSES_36,
    )
    answers = jd_to_answers(_jd(duty))
    assert answers.duties[0].how_why == _CLAUSES_36

    back = assemble_jd(answers)
    assert back.duties[0].how_why == _CLAUSES_36


def test_an_archive_document_with_twenty_duties_clones_into_the_builder() -> None:
    """The Builder also clones RAW archive documents (`load_clone_answers`). A v9 parse
    keeps up to `segmentation.duty_max_count` (HR-262) duties — measured max 93, with
    ~1,470 APSA/APEX/POLY documents over twelve — and `ComposerAnswers.duties` held
    twelve, so the clone raised. It now holds what the parser keeps."""
    from src.jd_bank.composer.assemble import jd_to_answers

    duties = [
        SFUDuty(action_verb="Does", statement=f"Does thing {i}") for i in range(20)
    ]
    answers = jd_to_answers(_jd(*duties))
    assert [d.statement for d in answers.duties] == [d.statement for d in duties]


def test_a_draft_with_fifty_decision_points_clones_into_the_builder() -> None:
    """A draft's Decision Making is a UNION over its members, cut at the model ceiling
    (60). The Builder row held 20, so a clone of such a draft would raise."""
    from src.jd_bank.composer.assemble import jd_to_answers

    jd = _jd(_FLAT).model_copy(
        update={"decision_making": [f"Decides matter {i}." for i in range(50)]}
    )
    assert len(jd_to_answers(jd).decision_making) == 50


def test_a_v9_cupe_role_with_a_long_function_clones_into_the_j2_form() -> None:
    """FOUND by smoke on the v9 Bank: 378 of 635 CUPE roles failed to clone with
    ``FunctionAnswer statement: String should have at most 400 characters`` — J2's
    function rows kept the pre-v9 400 while a v9 duty can run to HR-261's 1,200."""
    from src.jd_bank.composer.wjq_assemble import assemble_wjq_jd, wjq_answers_from_jd

    long = "Processes requisitions and invoices, " * 25
    jd = SFUJobDescription(
        title="Clerk",
        employee_group="cupe",
        duties=[
            SFUDuty(action_verb="Processes", statement=long.strip(), frequency="daily")
        ],
    )
    answers = wjq_answers_from_jd(jd)
    assert answers.major_functions[0].statement == long.strip()
    assert assemble_wjq_jd(answers).duties[0].statement.startswith("Processes")


def test_a_cupe_draft_with_30_ability_lines_clones_and_reassembles() -> None:
    """FOUND on the v9 Bank: deterministic CUPE drafts carry up to 30 ability lines
    (the merge's qualification union, held to the model's 40). J2 sends abilities to
    Occupational Requirement(s), whose model held 20 — so reassembling refused 2 roles.
    A Builder field narrower than the draft it clones from refuses the Bank's own data.
    """
    from src.jd_bank.composer.wjq_assemble import assemble_wjq_jd, wjq_answers_from_jd

    abilities = [
        SFUQualification(text=f"Ability to handle situation {i}", kind="ability")
        for i in range(30)
    ]
    jd = SFUJobDescription(
        title="Clerk",
        employee_group="cupe",
        duties=[
            SFUDuty(action_verb="Files", statement="Files records", frequency="daily")
        ],
        qualifications=abilities,
    )
    answers = wjq_answers_from_jd(jd)
    assert len(answers.occupational_requirements) == 30
    back = assemble_wjq_jd(answers)
    assert back.wjq_form is not None
    assert len(back.wjq_form.occupational_requirements) == 30


def test_a_draft_with_24_knowledge_lines_clones_into_the_builder() -> None:
    """FOUND on the v9 Bank: JDFN drafts carry up to 24 knowledge / 23 ability lines
    (qualifications are split since v9), and the Builder's K/S/A rows held 20 each."""
    from src.jd_bank.composer.assemble import jd_to_answers

    quals = [
        SFUQualification(text=f"Knowledge of subject area {i}", kind="knowledge")
        for i in range(24)
    ]
    jd = _jd(_FLAT).model_copy(update={"qualifications": quals})
    assert len(jd_to_answers(jd).knowledge) == 24


def test_the_builder_how_why_limit_is_the_rulebook_s(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Retune HR-265 and the Builder row follows — no second constant to drift."""
    from pydantic import ValidationError

    from src.jd_bank.composer.answers import JDFNDutyAnswer
    from src.jd_core import rules as rules_mod

    real = get_rules()
    tuned = real.model_copy(
        update={
            "segmentation": real.segmentation.model_copy(
                update={"duty_how_why_max_count": 5}
            )
        }
    )
    monkeypatch.setattr(rules_mod, "get_rules", lambda: tuned)

    JDFNDutyAnswer(statement="Manages things by", how_why=_CLAUSES_36[:5])
    with pytest.raises(ValidationError, match="HR-265"):
        JDFNDutyAnswer(statement="Manages things by", how_why=_CLAUSES_36[:6])


def test_a_clause_the_model_dropped_comes_back_even_with_nothing_invented() -> None:
    """Review round 2: the model returns one of the duty's two clauses (the other
    dropped, nothing invented). Prompt v3 says not to drop clauses; the guard now
    checks it — every source clause must still be covered by the rewritten duty
    (same token rule, HR-267, asked from the other end) or it comes back — since
    2026-10-20 (HR-271) folded in after the model's own clauses."""
    merged = MergedRole(
        draft=_jd(_GROUPED),
        provenance=MergeProvenance(member_count=2, skill_frequency=()),
    )
    llm = _jd(
        SFUDuty(
            action_verb="Manages",
            statement="Manages proposal processes by",
            how_why=["tracking the grant deadlines"],
        )
    )
    out, record = _apply_anti_fabrication(llm, merged, get_rules())

    assert out.duties[0].how_why == [
        "tracking the grant deadlines",
        "preparing project budgets",
    ]
    assert record.scrubbed_how_why == ()
    assert record.folded_duty_content == ("preparing project budgets",)


def test_a_fully_reworded_and_complete_clause_list_is_kept() -> None:
    merged = MergedRole(
        draft=_jd(_GROUPED),
        provenance=MergeProvenance(member_count=2, skill_frequency=()),
    )
    reworded = [
        "by tracking the grant deadlines",
        "by preparing budgets for the project",
    ]
    llm = _jd(
        SFUDuty(
            action_verb="Manages",
            statement="Manages proposal processes",
            how_why=reworded,
        )
    )
    out, record = _apply_anti_fabrication(llm, merged, get_rules())

    assert out.duties[0].how_why == reworded
    assert record.scrubbed_how_why == ()


def test_an_invented_clause_cannot_hide_in_a_long_duty_s_vocabulary() -> None:
    """Review round 2: grounded against the WHOLE source duty, a clause stitched from
    words scattered across many source clauses passed (on a real 14-clause archive duty
    two invented clauses were kept, unrecorded). A clause is now grounded against the
    headline plus ONE source clause — the closest — so it must come from somewhere."""
    source = SFUDuty(
        action_verb="Ensures",
        statement="Ensures the strategic success of the Centre by",
        how_why=[
            "Monitoring and forecasting operational budgets and variance",
            "Liaising with University stakeholders on evolving issues",
            "Developing educational programs that serve students",
            "Evaluating vendor services and annual program outcomes",
        ],
    )
    merged = MergedRole(
        draft=_jd(source),
        provenance=MergeProvenance(member_count=2, skill_frequency=()),
    )
    invented = "Negotiating annual vendor budgets with University students"
    llm = _jd(source.model_copy(update={"how_why": [*source.how_why, invented]}))
    out, record = _apply_anti_fabrication(llm, merged, get_rules())

    assert invented not in out.duties[0].how_why
    assert record.scrubbed_how_why == (invented,)

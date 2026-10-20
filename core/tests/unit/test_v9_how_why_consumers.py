"""Parser v9 fills ``SFUDuty.how_why`` (owner ruling 2026-10-20, Q1) — every consumer
that read only ``statement`` must now READ it, or the sub-bullets of SFU's "ACTION VERB
… WHAT by" duties vanish one step after the parser recovered them.

One test per consumer changed on this branch (merge, rewrite input + guard; embed text
is in ``test_embed_text.py``); ``docs/plans/PARSER-V9-LISTS-AND-CAPS.md`` §5 has the
full inventory, including the consumers that already read ``how_why``.
"""

from __future__ import annotations

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


def test_a_v9_draft_with_a_long_duty_clones_into_the_builder() -> None:
    """A v9 draft can carry a duty longer than 400 characters (HR-261). Cloning it into
    the Builder must not raise — `DutyAnswer.statement` was narrower than the JD it is
    cloned from."""
    from src.jd_bank.composer.assemble import jd_to_answers

    long_duty = SFUDuty(action_verb="Coordinates", statement="Coordinates " + "x" * 900)
    answers = jd_to_answers(_jd(long_duty))

    assert answers.duties[0].statement == long_duty.statement

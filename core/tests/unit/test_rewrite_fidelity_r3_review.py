"""Rewrite fidelity round 3, REVIEW (2026-10-21). Cases the reviewer found over the
archive (14,522 parses; the coder's per-document Decision Making dump of the 4,115
documents carrying the refer prompt) and by adversarial input. Each asserts the merge's
or the guard's post-state (non-negotiable #3).

* The referral run ended at ANY item ``rewrite.fragment_pattern`` matches — including a
  list item ending ";" or "," — so in 136 archive documents the referred decisions after
  "Major equipment purchases;" were left reading as decisions the incumbent MAKES.
* The answer to the MAKE question fused in front of the refer prompt ("Sets own
  priorities… (ii) Give some examples… supervisor.") was labelled referred.
* "Refers decisions regarding X to the Director." — a complete referral, not a lead-in —
  started a run that labelled every following made decision "Refers to the supervisor:".
* The rewrite let an inverted decision through if it shared ONE word with the label
  ("Approves expenditures…, informing the supervisor").
* HR-284's restored-sentence test ignored the sentence's names (HR-272): a two-word
  sentence "opportunities in Cooperative Education" counted as covered by a just-folded
  sentence sharing only "opportunities". (The PIECE test still ignores names — measured,
  requiring them there lists 98 more sentences, mostly member unit names; see HR-284.)
* A list item ending ";" ("Hiring of staff;") was a FRAGMENT, never restored.
"""

from __future__ import annotations

import pytest

from src.jd_bank.rewrite.fidelity import is_fragment
from src.jd_bank.rewrite.harmonize import _apply_anti_fabrication
from src.jd_core.bank.merge import label_referred_decisions
from src.jd_core.models.bank import MergedRole, MergeProvenance
from src.jd_core.models.parsed_jd import SFUDuty, SFUJobDescription
from src.jd_core.rules import Rules, get_rules

_REFER_PROMPT = (
    "Give some examples of the types of decisions the incumbent would refer to "
    "his/her supervisor."
)


@pytest.fixture(scope="module")
def rules() -> Rules:
    return get_rules()


def _label(rules: Rules) -> str:
    return rules.harmonization.referred_decision_label


def test_a_semicolon_list_of_referred_decisions_is_labelled_throughout(
    rules: Rules,
) -> None:
    """20001028_00000975Departmental_assistant.doc, as parsed."""
    out = label_referred_decisions(
        [
            _REFER_PROMPT,
            "Major equipment purchases;",
            "Academic related decisions;",
            "Student discipline",
        ],
        rules,
    )
    label = _label(rules)
    assert out == [
        f"{label} Major equipment purchases;",
        f"{label} Academic related decisions;",
        f"{label} Student discipline",
    ]


def test_a_made_decision_fused_before_the_refer_prompt_stays_made(
    rules: Rules,
) -> None:
    """20021025_00030783Departmental_asst_LTI.doc, as parsed."""
    made = (
        "Sets own priorities and determines own work methods necessary to meet "
        "objectives."
    )
    out = label_referred_decisions(
        [f"{made} (ii) {_REFER_PROMPT}", "Non-budgeted expenses."], rules
    )
    assert out[0].startswith(made[:40])
    assert not out[0].startswith(_label(rules))
    assert out[1] == f"{_label(rules)} Non-budgeted expenses."


def test_a_complete_referral_does_not_label_the_decisions_after_it(
    rules: Rules,
) -> None:
    items = [
        "Refers decisions regarding major budget changes to the Director.",
        "Makes decisions regarding daily scheduling of staff.",
        "Approves leave requests.",
    ]
    assert label_referred_decisions(items, rules) == items


def test_a_refers_lead_in_still_labels_the_decisions_under_it(rules: Rules) -> None:
    out = label_referred_decisions(
        ["Refers decisions regarding:", "Major budget changes.", "Hiring."], rules
    )
    assert out == [f"{_label(rules)} Major budget changes.", f"{_label(rules)} Hiring."]


@pytest.mark.parametrize("who", ["her/his", "his or her", "his/ her"])
def test_a_spelling_variant_of_the_refer_prompt_is_a_marker(
    rules: Rules, who: str
) -> None:
    prompt = (
        "Give some examples of the types of decisions the incumbent would refer to "
        f"{who} supervisor."
    )
    out = label_referred_decisions([prompt, "Major equipment purchases."], rules)
    assert out == [f"{_label(rules)} Major equipment purchases."]


def _jd(dm: list[str], duties: list[SFUDuty] | None = None) -> SFUJobDescription:
    return SFUJobDescription(
        title="Coordinator",
        position_summary="Supports the unit.",
        duties=duties or [],
        decision_making=dm,
    )


def test_one_shared_word_with_the_label_does_not_keep_the_referral(
    rules: Rules,
) -> None:
    source = [
        "Determines session schedules for orientation.",
        f"{_label(rules)} Expenditures of University funds over budget.",
    ]
    inverted = (
        "Approves expenditures of University funds over budget, informing the "
        "supervisor."
    )
    merged = MergedRole(draft=_jd(source), provenance=MergeProvenance(member_count=2))

    out, record = _apply_anti_fabrication(_jd([source[0], inverted]), merged, rules)

    assert ("decision_making", inverted) in record.scrubbed_items
    assert source[1] in out.decision_making


def test_a_restored_sentence_covers_another_only_with_its_names(
    rules: Rules,
) -> None:
    folded_first = "Identifies opportunities to provide leads to Media Relations."
    lost = "opportunities in Cooperative Education"
    source = SFUDuty(
        action_verb="Promotes",
        statement="Promotes the programs to students by",
        how_why=[folded_first, lost],
    )
    model = SFUDuty(
        action_verb="Promotes",
        statement="Promotes the programs to students",
        how_why=["Visits high schools to present the programs"],
    )
    merged = MergedRole(
        draft=_jd([], [source]), provenance=MergeProvenance(member_count=2)
    )

    _out, record = _apply_anti_fabrication(_jd([], [model]), merged, rules)

    accounted = {*record.folded_duty_content, *record.dropped_duty_content}
    assert folded_first in accounted
    assert lost in accounted


@pytest.mark.parametrize(
    "item", ["Hiring of staff;", "Signing authority up to $5,000;"]
)
def test_a_list_item_ending_in_a_semicolon_is_not_a_fragment(
    rules: Rules, item: str
) -> None:
    assert not is_fragment(item, rules)


@pytest.mark.parametrize(
    "item", ["(e.g. lab power supplies, curve tracers,", "Makes decisions regarding"]
)
def test_continuations_and_lead_ins_are_still_fragments(
    rules: Rules, item: str
) -> None:
    assert is_fragment(item, rules)

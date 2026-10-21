"""Rewrite fidelity, round 3 — the second pilot on the v9 Bank (2026-10-21).

Each test is built from the round-2 pilot's own case: the merge draft the pilot recorded
(``input_json``) and the model's recorded reply, cut down to the items that show the
defect (``tests/fixtures/rewrite_fidelity/r2_*.json``, every string verbatim), or — for
the merge — Decision Making lists parsed from real archive documents.

Non-negotiable #3: these assert what the GUARD (or the merge) kept, dropped, restored
and recorded, never the quality of model text; the model reply is a fixed input.
The plan: ``docs/plans/PARSER-V9-LISTS-AND-CAPS.md`` §16.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.jd_bank.rewrite.fidelity import sentences
from src.jd_bank.rewrite.harmonize import _apply_anti_fabrication
from src.jd_core.bank.merge import merge_cluster
from src.jd_core.models.bank import MergedRole, MergeProvenance
from src.jd_core.models.parsed_jd import SFUJobDescription
from src.jd_core.rules import Rules, get_rules

_FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "rewrite_fidelity"


def _case(name: str) -> tuple[MergedRole, SFUJobDescription]:
    raw = json.loads((_FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
    return (
        MergedRole.model_validate(raw["merged"]),
        SFUJobDescription.model_validate(raw["model"]),
    )


def _clauses(jd: SFUJobDescription) -> list[str]:
    return [clause for duty in jd.duties for clause in duty.how_why]


@pytest.fixture(scope="module")
def rules() -> Rules:
    return get_rules()


# --- 1. budget ----------------------------------------------------------------------

#: Round-2 pilot at max_tokens 4096: 4 of 20 first calls stopped on `length` with an
#: empty reply, all in the REASONING phase (22.7k–25.1k reasoning characters). Re-run at
#: 8192 all four stopped first call; peak content 3,742 tokens (7f45b048).
_LARGEST_R2_REPLY = 3742


def test_the_rewrite_budget_has_headroom_over_round_2s_largest_reply(
    rules: Rules,
) -> None:
    assert rules.rewrite.max_tokens >= 2 * _LARGEST_R2_REPLY


# --- 2. decisions the incumbent REFERS are not decisions it MAKES --------------------

_REFER_PROMPT = (
    "Give some examples of the types of decisions the incumbent would refer to "
    "his/her supervisor."
)
_MAKE_PROMPT = (
    "Give some typical examples of the most important decisions the incumbent is "
    "expected to make in carrying out the duties and responsibilities of the position. "
    "To what extent can the incumbent rely on established policies or advice from "
    "others in making these decisions?"
)
#: 20150713_00117524_Student_Recruiter.docx — Decision Making as parsed (cb73e45c's
#: member): the referred decisions are the items AFTER the refer prompt.
_SEPARATE = [
    _MAKE_PROMPT,
    "Recruits prospective students to the French Cohort Program and to the University.",
    _REFER_PROMPT,
    "Decisions that may lead to contact with upper levels of administration at the "
    "University or involve consultation amongst officers outside OFFA.",
    "Decisions regarding the expenditure of University funds.",
]
#: 20120214_00100993_Student_Recruiter.doc — the answer FUSED into the prompt's item.
_FUSED = [
    _MAKE_PROMPT,
    _REFER_PROMPT + " Decisions regarding the expenditure of University funds.",
]


def _member(dm: list[str]) -> SFUJobDescription:
    return SFUJobDescription(
        title="Student Recruiter",
        position_summary="Recruits students.",
        decision_making=dm,
    )


@pytest.mark.parametrize("dm", [_SEPARATE, _FUSED], ids=["separate", "fused"])
def test_the_merge_keeps_a_referred_decision_marked_as_referred(
    rules: Rules, dm: list[str]
) -> None:
    """cb73e45c: the merge pools and SORTS Decision Making, so the refer prompt lost its
    position, the rewrite stripped the prompt (HR-275), and "Decisions regarding the
    expenditure of University funds" read as a decision the incumbent MAKES. The
    referred items are labelled per member, while the order still says which they are.
    """
    draft = merge_cluster([_member(dm), _member(dm)], rules=rules).draft
    label = rules.harmonization.referred_decision_label

    referred = [i for i in draft.decision_making if i.startswith(label)]
    assert (
        f"{label} Decisions regarding the expenditure of University funds." in referred
    )
    assert not any(_REFER_PROMPT in i for i in draft.decision_making)
    # a decision stated BEFORE the prompt is the incumbent's own
    if dm is _SEPARATE:
        assert (
            "Recruits prospective students to the French Cohort Program and to the "
            "University." in draft.decision_making
        )


def test_a_referred_decision_cannot_come_back_as_one_the_incumbent_makes(
    rules: Rules,
) -> None:
    """Grounded in a referred item, a rewritten decision must keep the referral; the
    pilot's model wrote "Makes decisions regarding the expenditure of University funds"
    from exactly this source."""
    draft = merge_cluster([_member(_SEPARATE), _member(_SEPARATE)], rules=rules).draft
    merged = MergedRole(draft=draft, provenance=MergeProvenance(member_count=2))
    makes = "Makes decisions regarding the expenditure of University funds"
    refers = (
        "Refers decisions regarding the expenditure of University funds to the "
        "supervisor"
    )
    model = draft.model_copy(update={"decision_making": [makes, refers]})

    out, record = _apply_anti_fabrication(model, merged, rules)

    assert ("decision_making", makes) in record.scrubbed_items
    assert refers in out.decision_making


# --- 3. lost duty content must be recorded -------------------------------------------

_LOST_ON_CB73 = (
    "careers as they relate to academic programs",
    "opportunities in Cooperative Education",
)


def test_duty_content_the_model_lost_is_folded_or_listed_never_counted_covered(
    rules: Rules,
) -> None:
    """cb73e45c: both sentences are absent from the output and were in no record.
    "careers…" was "covered" by a duty's words PLUS text the guard itself had just
    folded in ("academic offerings"); "…Cooperative Education" by two generic words,
    without the name. Restored text now covers only its near-duplicate sentence, and a
    covering duty must state the sentence's named terms."""
    merged, model = _case("r2_offa_cb73e45c")
    _out, record = _apply_anti_fabrication(model, merged, rules)
    accounted = {*record.folded_duty_content, *record.dropped_duty_content}
    for sentence in _LOST_ON_CB73:
        assert sentence in accounted, sentence


# --- 4. fold-back must not duplicate what the model reworded -------------------------

_REWORDED_ON_MUSEUM = (
    # model: "…, monitor copyright issues, …"
    "Monitors possible copyright infringement.",
    # model: "Manage revenue streams from cash donations, grant funding and sale of
    # image use rights while protecting SFU copyright"
    "Manages a revenue stream of funds through the sale of use rights for images from "
    "web sites to third party organizations, companies, and individuals, taking care "
    "not to compromise SFU's copyright of the materials.",
)


def test_a_sentence_the_model_reworded_is_not_also_folded_back(rules: Rules) -> None:
    merged, model = _case("r2_museum_1d68c603")
    _out, record = _apply_anti_fabrication(model, merged, rules)
    for sentence in _REWORDED_ON_MUSEUM:
        assert sentence not in record.folded_duty_content, sentence[:40]


def test_detail_the_model_dropped_is_still_folded_back(rules: Rules) -> None:
    """The boundary: "liaise with Risk Management for insurance" keeps 3 of the source
    sentence's 12 content words and drops "borrowed objects valued in excess of $1 M" —
    a fact, so the source sentence still comes back."""
    merged, model = _case("r2_museum_1d68c603")
    _out, record = _apply_anti_fabrication(model, merged, rules)
    assert any(
        s.startswith("Liaises with the Office of Risk Management")
        for s in record.folded_duty_content
    )


# --- 5. the sentence splitter --------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "Collaborates with V. P. Advancement on fundraising initiatives.",
        "Uses web software (e.g. HTML, Adobe) at a basic level.",
        "Tracks inquiries (i.e. phone and email) daily.",
        "Advises on potential student transfers from B.C. institutions.",
    ],
)
def test_an_abbreviation_or_initial_does_not_end_a_sentence(text: str) -> None:
    assert sentences(text) == [text]


def test_two_sentences_still_split() -> None:
    assert sentences("Serves on committees. Hosts events.") == [
        "Serves on committees.",
        "Hosts events.",
    ]


def test_no_initial_is_folded_back_as_a_sentence_of_its_own(rules: Rules) -> None:
    merged, model = _case("r2_museum_1d68c603")
    out, record = _apply_anti_fabrication(model, merged, rules)
    assert "Collaborates with V." not in record.folded_duty_content
    assert "Collaborates with V." not in _clauses(out)


# --- 6. restored fragments ------------------------------------------------------------


def test_a_lead_in_is_not_restored_as_a_decision(rules: Rules) -> None:
    merged, model = _case("r2_museum_1d68c603")
    out, record = _apply_anti_fabrication(model, merged, rules)
    assert "Makes decisions regarding" not in out.decision_making
    assert ("decision_making", "Makes decisions regarding") in record.uncovered_items


def test_an_item_the_parser_cut_comes_back_whole_sentences_only(rules: Rules) -> None:
    """The museum's internal-contacts item is exactly 400 characters — the parser's own
    cap — so its last sentence ("Partners with a wide circle of contacts and involves")
    is a cut-off. Restored at the item's boundary, minus the cut, never as bullets of
    single sentences."""
    merged, model = _case("r2_museum_1d68c603")
    out, record = _apply_anti_fabrication(model, merged, rules)
    assert out.relationships is not None
    internal = out.relationships.internal
    assert not any(c.rstrip().endswith("involves") for c in internal)
    assert (
        "Sets objectives necessary for obtaining feedback and assistance."
        not in internal
    )
    assert any(
        c.startswith("Internal Connections/External Connections")
        and c.endswith(
            "Sets objectives necessary for obtaining feedback and assistance."
        )
        for c in internal
    )
    assert any(t.endswith("and involves") for _s, t in record.uncovered_items)


def test_a_dangling_continuation_line_is_not_restored_as_a_qualification(
    rules: Rules,
) -> None:
    merged, model = _case("r2_wjq_tech_0a75edf1")
    out, record = _apply_anti_fabrication(model, merged, rules)
    texts = [q.text for q in out.qualifications]
    assert not any(t.startswith("(e.g. lab power supplies") for t in texts)
    assert not any(t.rstrip().endswith(",") for t in texts)


# --- 7. relationships ----------------------------------------------------------------


def test_a_contact_kept_with_its_duration_and_frequency_is_grounded(
    rules: Rules,
) -> None:
    """14163329 (WJQ): the source table is three items per row — "Graduate Students",
    "< 1 hour", "Frequent" — and prompt v4 asks the model to keep each contact's
    duration and frequency WITH it. Grounded one item at a time, every such contact
    was scrubbed. A contact is grounded against a source ROW (the item and the cells
    after it, HR-288)."""
    merged, model = _case("r2_wjq_14163329")
    out, record = _apply_anti_fabrication(model, merged, rules)
    assert out.relationships is not None
    assert "Graduate Students – < 1 hour, Frequent" in out.relationships.internal
    assert not [i for i in record.scrubbed_items if "Graduate Students" in i[1]]


def test_a_window_of_one_restores_the_item_only_rule(rules: Rules) -> None:
    merged, model = _case("r2_wjq_14163329")
    one = rules.model_copy(
        update={
            "rewrite": rules.rewrite.model_copy(update={"relationships_row_window": 1})
        }
    )
    _out, record = _apply_anti_fabrication(model, merged, one)
    assert (
        "relationships",
        "Graduate Students – < 1 hour, Frequent",
    ) in record.scrubbed_items

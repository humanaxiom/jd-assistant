"""Rewrite fidelity (owner ruling 2026-10-20: "fix the rewrite first", before the v9
producer pass). The size-stratified pilot on the v9 Bank found six ways the 4.2a rewrite
lost or invented content that the anti-fabrication guard let through. Each test below is
built from the pilot's OWN case: the merge draft rebuilt from the v9 Bank and the
model's recorded reply, cut down to the items that show the defect
(``tests/fixtures/rewrite_fidelity/*.json``; every string in them is verbatim).

Non-negotiable #3: these assert the GUARD's post-state — what it kept, dropped, restored
and recorded — never the quality of model text. The model reply is a fixed input here.
The plan: ``docs/plans/PARSER-V9-LISTS-AND-CAPS.md`` §15.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.jd_bank.jd_text import flatten_jd
from src.jd_bank.rewrite.fidelity import is_fragment
from src.jd_bank.rewrite.harmonize import _apply_anti_fabrication, rewrite_merged_role
from src.jd_core.bank.merge import duty_text
from src.jd_core.models.bank import MergedRole
from src.jd_core.models.parsed_jd import SFUJobDescription
from src.jd_core.rules import Rules, get_rules

_FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "rewrite_fidelity"


def _case(name: str) -> tuple[MergedRole, SFUJobDescription]:
    raw = json.loads((_FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
    return (
        MergedRole.model_validate(raw["merged"]),
        SFUJobDescription.model_validate(raw["model"]),
    )


def _with(rules: Rules, **rewrite: object) -> Rules:
    return rules.model_copy(
        update={"rewrite": rules.rewrite.model_copy(update=rewrite)}
    )


def _clauses(jd: SFUJobDescription) -> list[str]:
    return [clause for duty in jd.duties for clause in duty.how_why]


class _Replay:
    """Returns the pilot's recorded reply; records the prompt it was handed."""

    def __init__(self, jd: SFUJobDescription) -> None:
        self._jd = jd
        self.prompts: list[str] = []
        self.max_tokens: list[int] = []

    async def chat_json(
        self,
        messages: object,
        model_cls: type[SFUJobDescription],
        *,
        max_tokens: int,
        max_retries: int,
    ) -> SFUJobDescription:
        self.prompts.extend(m["content"] for m in messages)  # type: ignore[attr-defined]
        self.max_tokens.append(max_tokens)
        return self._jd.model_copy(deep=True)


@pytest.fixture(scope="module")
def rules() -> Rules:
    return get_rules()


# --- 1. the token budget -----------------------------------------------------------

#: Measured in the pilot (2026-10-20, v9 Bank, gpt-oss:120b). Ollama caps the reasoning
#: stream and the content SEPARATELY at `max_tokens`: at 2048, 4 of 22 first rewrite
#: calls stopped on `length` with an EMPTY reply (saved only by the one repair retry),
#: and one success used 1,912 of 2,048 content tokens. At 4096 every call stopped on
#: the first attempt; the largest reply was 2,025 content tokens (57db4a16).
_LARGEST_PILOT_REWRITE_REPLY = 2025
#: The audit at 1024: 2 of 22 calls stopped on `length`; both retries then used
#: 1,003 and 965 of 1,024.
_LARGEST_PILOT_AUDIT_REPLY = 1003


def test_the_rewrite_budget_has_headroom_over_the_pilot_s_largest_reply(
    rules: Rules,
) -> None:
    assert rules.rewrite.max_tokens >= 2 * _LARGEST_PILOT_REWRITE_REPLY


def test_the_audit_budget_has_headroom_over_the_pilot_s_largest_reply(
    rules: Rules,
) -> None:
    assert rules.quality.max_tokens >= 2 * _LARGEST_PILOT_AUDIT_REPLY


@pytest.mark.asyncio
async def test_the_rewrite_call_is_given_the_rulebook_budget(rules: Rules) -> None:
    merged, model = _case("ethics_22994d3a")
    client = _Replay(model)
    await rewrite_merged_role(merged, client=client, rules=rules)  # type: ignore[arg-type]
    assert client.max_tokens == [rules.rewrite.max_tokens]


# --- 2. duty areas dropped to fit the cap -------------------------------------------

#: 1d68c603 (Director, Museum of Archaeology and Ethnology): the merge had twelve
#: duties, the JDFN cap is five (HR policy, untouched), and the model met it by dropping
#: whole areas — "Community Liaison & Committee Representation" and "Research & Museum
#: Career Skills Training" — recorded in `removed_duties` and gone from the draft.
_DROPPED_AREA = "Research & Museum Career Skills Training"


def test_a_duty_area_dropped_to_meet_the_cap_is_folded_back(rules: Rules) -> None:
    merged, model = _case("museum_1d68c603")
    area = next(d for d in merged.draft.duties if d.statement == _DROPPED_AREA)

    out, record = _apply_anti_fabrication(model, merged, rules)

    # The cap holds (HR policy). This fixture's reply kept ONE duty, so since HR-279 an
    # area no kept duty matches comes back as a duty of its own rather than under an
    # unrelated one — and the form still has room for it.
    assert len(model.duties) < len(out.duties) <= rules.thresholds.duties_max
    folded = record.folded_duty_content
    assert folded and set(folded) <= {
        piece for d in out.duties for piece in (*d.how_why, d.statement)
    }
    # verbatim source text, and the dropped area is part of what came back
    source = " ".join(duty_text(d) for d in merged.draft.duties)
    assert all(piece in source for piece in folded)
    assert any(piece in " ".join(area.how_why) for piece in folded)
    assert record.dropped_duty_content == ()


def test_record_only_lists_the_dropped_area_instead_of_folding_it(
    rules: Rules,
) -> None:
    merged, model = _case("museum_1d68c603")
    area = next(d for d in merged.draft.duties if d.statement == _DROPPED_AREA)

    out, record = _apply_anti_fabrication(
        model, merged, _with(rules, duty_coverage_policy="record_only")
    )

    assert record.folded_duty_content == ()
    assert any(piece in " ".join(area.how_why) for piece in record.dropped_duty_content)
    assert not set(record.dropped_duty_content) & set(_clauses(out))


def test_a_faithful_clause_merged_from_another_source_duty_is_kept(
    rules: Rules,
) -> None:
    """The model merged two source duties into one and kept a clause from the SECOND.
    Grounded only against the duty it was matched to, the pilot scrubbed it (8 such
    clauses on this cluster). Each clause is now grounded against every source duty's
    headline + one clause — still one source unit, never their union."""
    merged, model = _case("museum_1d68c603")
    moved = next(
        c for c in model.duties[0].how_why if c.startswith("Research, develop")
    )

    out, record = _apply_anti_fabrication(model, merged, rules)

    assert moved in out.duties[0].how_why
    assert moved not in record.scrubbed_how_why


# --- 3. decision making / problem solving / relationships, per item -----------------

_INVENTED_DM = (
    "Approves acquisition, deaccession and loan decisions.",
    "Allocates budgetary resources and approves funding proposals.",
)
_INVENTED_PS = "Navigates funding constraints while maintaining program quality."


def test_a_decision_no_decision_making_item_states_is_scrubbed(rules: Rules) -> None:
    merged, model = _case("museum_1d68c603")
    out, record = _apply_anti_fabrication(model, merged, rules)

    for item in _INVENTED_DM:
        assert item not in out.decision_making
        assert ("decision_making", item) in record.scrubbed_items
    assert _INVENTED_PS not in out.problem_solving
    assert ("problem_solving", _INVENTED_PS) in record.scrubbed_items


def test_decision_items_the_rewrite_lost_are_restored(rules: Rules) -> None:
    merged, model = _case("museum_1d68c603")
    out, record = _apply_anti_fabrication(model, merged, rules)

    lost = [t for s, t in record.uncovered_items if s == "decision_making"]
    back = [t for s, t in record.restored_items if s == "decision_making"]
    assert lost  # 13 grounded decisions came back as five
    assert back and all(t in out.decision_making for t in back)
    # Round 3 (HR-287): what is lost and NOT put back is a fragment or a parser
    # cut-off — listed for the reviewer, never inserted as a decision of its own.
    for text in set(lost) - set(back):
        assert is_fragment(text, rules) or not text.rstrip().endswith("."), text


def test_restoring_is_a_rulebook_choice_and_the_loss_stays_recorded(
    rules: Rules,
) -> None:
    merged, model = _case("museum_1d68c603")
    out, record = _apply_anti_fabrication(
        model, merged, _with(rules, restore_uncovered_items_in=("qualifications",))
    )

    lost = [t for s, t in record.uncovered_items if s == "decision_making"]
    assert lost
    assert not set(lost) & set(out.decision_making)
    assert not [i for i in record.restored_items if i[0] == "decision_making"]


def test_contacts_lifted_from_another_section_do_not_replace_the_real_ones(
    rules: Rules,
) -> None:
    """0a75edf1 (WJQ, BPK electronics technician): the model replaced the section's
    Biomedical Physiology and Kinesiology contacts with "Engineering Science" ones the
    relationships section never names. Each contact is now grounded against the
    merge's OWN relationships, and the BPK contacts it dropped come back."""
    merged, model = _case("wjq_tech_0a75edf1")
    out, record = _apply_anti_fabrication(model, merged, rules)

    assert out.relationships is not None
    contacts = [*out.relationships.internal, *out.relationships.external]
    assert not any("Engineering Science" in c for c in contacts)
    assert ("relationships", "Engineering Science Researchers") in record.scrubbed_items
    assert "Biomedical Physiology and Kinesiology Researchers" in contacts
    # the WJQ's duration / frequency cells are source content too
    assert "Frequent" in contacts


# --- 4. qualifications dropped invisibly --------------------------------------------


def test_a_qualification_the_rewrite_dropped_is_recorded_and_restored(
    rules: Rules,
) -> None:
    merged, model = _case("wjq_tech_0a75edf1")
    out, record = _apply_anti_fabrication(model, merged, rules)

    lost = [t for s, t in record.uncovered_items if s == "qualifications"]
    back = [t for s, t in record.restored_items if s == "qualifications"]
    assert lost  # 40 -> 15 in the pilot; most was dedup, not all
    texts = [q.text for q in out.qualifications]
    assert back and all(t in texts for t in back)
    # Round 3 (HR-287): a continuation line ("(e.g. lab power supplies, …,") is listed,
    # not restored as a qualification of its own.
    for text in set(lost) - set(back):
        assert is_fragment(text, rules), text
    assert len(out.qualifications) <= 40


# --- 5. recombination from boilerplate; an expanded acronym -------------------------

_FROM_BOILERPLATE = (
    "Commitment to employment equity and respect for Indigenous territories and "
    "cultures"
)
_EXPANDED_ACRONYM = (
    "Familiarity with international museum standards and conventions "
    "(e.g., ICOM Code of Ethics, CITES)"
)


def test_boilerplate_words_cannot_ground_a_qualification(rules: Rules) -> None:
    """The merge carried the EE statement and the territorial acknowledgement as
    qualification lines (a parser artefact); the model fused them into a commitment
    no source states, and their words grounded it."""
    merged, model = _case("museum_1d68c603")
    out, record = _apply_anti_fabrication(model, merged, rules)

    assert _FROM_BOILERPLATE in record.scrubbed_skills
    texts = [q.text for q in out.qualifications]
    assert _FROM_BOILERPLATE not in texts
    # the boilerplate itself is not "restored" as a lost qualification either
    assert not any("Employment Equity" in t for t in texts)
    assert not any("acknowledge" in t.lower() for t in texts)


def test_a_named_term_no_source_states_cannot_ride_on_grounded_words(
    rules: Rules,
) -> None:
    """ "ICOM Code of Ethics" where the source says "International Council on Museums":
    5 of 9 tokens are grounded, so the 0.5 bar passed it. A named term (an acronym or
    a capitalized word mid-item) must itself be in the source."""
    merged, model = _case("museum_1d68c603")
    out, record = _apply_anti_fabrication(model, merged, rules)
    assert _EXPANDED_ACRONYM in record.scrubbed_skills
    # ...and the source's own wording comes back, so nothing is lost
    texts = [q.text for q in out.qualifications]
    assert any("International Council on Museums" in t for t in texts)

    _out, lax = _apply_anti_fabrication(
        model, merged, _with(rules, named_terms_must_be_grounded=False)
    )
    assert _EXPANDED_ACRONYM not in lax.scrubbed_skills


# --- 6. the APSA questionnaire's own instructions -----------------------------------

_INSTRUCTIONS = (
    "Starting with those you consider the most important",
    "For each item start with an action verb",
    "Give some examples of the types of decisions",
    "To what extent can the incumbent rely",
    "Briefly describe the primary function and purpose",
    "Explain the nature of guidance received",
    "Indicate the number of continuing employees",
)


@pytest.mark.asyncio
async def test_form_instructions_never_reach_the_prompt_or_the_draft(
    rules: Rules,
) -> None:
    merged, model = _case("ethics_22994d3a")
    assert all(i in flatten_jd(merged.draft) for i in _INSTRUCTIONS)
    client = _Replay(model)

    result = await rewrite_merged_role(merged, client=client, rules=rules)  # type: ignore[arg-type]

    prompt = "\n".join(client.prompts)
    final = flatten_jd(result.draft)
    for instruction in _INSTRUCTIONS:
        assert instruction not in prompt
        assert instruction not in final
        assert any(
            instruction in s for s in result.anti_fabrication.stripped_source_text
        )


def test_faithful_clauses_survive_a_source_duty_that_was_a_parser_blob(
    rules: Rules,
) -> None:
    """22994d3a: every source duty is a run-on blob (with the form's instructions at its
    head), the model's five duties matched none closely, and all 15 of its clauses were
    scrubbed although they restate the blob. Grounded per clause against every source
    duty, the faithful ones stay."""
    merged, model = _case("ethics_22994d3a")
    out, record = _apply_anti_fabrication(model, merged, rules)

    # Review round 1 (HR-277): 8 of 15, was 6. The two newly scrubbed clauses had
    # grounded only through "the"/"and"/"for": "prepare the annual REB activity report
    # for Senate" (the source states it in the SUMMARY, not a duty) and "approve
    # minimal-risk applications and document rationale" (no stemming: "approves") —
    # whose source sentence is folded back verbatim, so nothing is lost.
    assert len(record.scrubbed_how_why) <= 8 < len(_clauses(model))
    assert "ensure compliance with SFU Policy R20.01 and TCPS‑2" in _clauses(out)
    assert any(
        "Approves applications that are minimal-risk" in c for c in _clauses(out)
    )


def test_wrapped_instruction_fragments_are_not_contacts(rules: Rules) -> None:
    """3a2f8ee5 (WJQ): the questionnaire's contact instruction, hard-wrapped by the
    .doc converter, reached the relationships lists one line per item. Restoring
    "lost" contacts must not put it back."""
    fragments = [
        "(i.e. specific positions within own department, other departments;",
        "contact (i.e. less than 1 hour at a time; 1-2 hours at a time; more than 2",
        "hours at a time) and the frequency of each contact (occasional; frequent;",
        "continuous).",
    ]
    merged, model = _case("wjq_tech_0a75edf1")
    rel = merged.draft.relationships
    assert rel is not None
    draft = merged.draft.model_copy(
        update={
            "relationships": rel.model_copy(
                update={"internal": [*fragments, *rel.internal[:6]]}
            )
        }
    )
    out, record = _apply_anti_fabrication(
        model, merged.model_copy(update={"draft": draft}), rules
    )

    assert out.relationships is not None
    assert not set(fragments) & set(out.relationships.internal)
    assert set(fragments) <= set(record.stripped_source_text)
    assert "Student" in rel.internal[:6]


# --- found while replaying the pilot through the new guard --------------------------

_PAGE_HEADER_DUTY = (
    "Position Number(s): ______01598________________ Continued Assesses functionality "
    "of undergraduate experimental setups currently in use by inspecting them daily "
    "and makes repairs as necessary, referring unusual problems to supervisor for "
    "assistance in decision making. Prepares documentation and ships equipment for "
    "repair, and verifies equipment ready for use on return"
)


def test_a_sentence_with_a_template_placeholder_is_never_folded_back(
    rules: Rules,
) -> None:
    """0a75edf1: a WJQ page header ("Position Number(s): ______01598______ Continued")
    is fused into a source duty. Folding that sentence back put "____" into the draft —
    the non-overridable no-placeholders gate (HR-047). It is listed, not restored."""
    merged, model = _case("wjq_tech_0a75edf1")
    source = merged.draft.duties[0].model_copy(update={"statement": _PAGE_HEADER_DUTY})
    draft = merged.draft.model_copy(update={"duties": [source]})
    llm = model.model_copy(update={"duties": [model.duties[1]]})

    out, record = _apply_anti_fabrication(
        llm, merged.model_copy(update={"draft": draft}), rules
    )

    assert not any("____" in c for c in _clauses(out))
    assert any("____" in d for d in record.dropped_duty_content)


def test_a_short_heading_inside_the_about_sfu_words_is_not_boilerplate(
    rules: Rules,
) -> None:
    """1d68c603's duty heading "Community Engagement." — both its words are in the
    About SFU paragraph, so a one-way match stripped it as boilerplate. A sentence must
    reproduce the passage, not just sit inside it."""
    merged, model = _case("museum_1d68c603")
    _out, record = _apply_anti_fabrication(model, merged, rules)
    assert "Community Engagement." not in record.stripped_source_text
    assert any("Employment Equity" in s for s in record.stripped_source_text)

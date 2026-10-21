"""Rewrite fidelity, review round 1 (2026-10-20). Four holes the reviewer's
adversarial cases and independent replay check found in the 2026-10-20 guard. Each
asserts the GUARD's post-state (non-negotiable #3), never model text quality.

* Function words counted as grounding evidence (HR-277): ``comparison.skill_stopwords``
  is a 20-word noise list for SKILL bags and keeps "and", "the", "for", "such" as
  content tokens, so they "grounded" an invented Decision Making item at exactly 0.5 and
  "covered" a lost source duty sentence at exactly 0.5 (pilot, b13e6321 — "Marketing
  services on the Web and in print media…" left the draft and no record listed it).
* A changed NUMBER was invisible (HR-278): a one- or two-digit token is below
  ``skill_min_token_len``, so "2 staff" -> "12 staff" changed nothing the guard saw.
* HR-272 did not read duty STATEMENTS: an acronym no source states passed unflagged.
"""

from __future__ import annotations

import pytest

from src.jd_bank.rewrite.harmonize import _apply_anti_fabrication
from src.jd_core.models.bank import MergedRole, MergeProvenance
from src.jd_core.models.parsed_jd import SFUDuty, SFUJobDescription, SFUQualification
from src.jd_core.rules import Rules, get_rules


@pytest.fixture(scope="module")
def rules() -> Rules:
    return get_rules()


def _with(rules: Rules, **rewrite: object) -> Rules:
    return rules.model_copy(
        update={"rewrite": rules.rewrite.model_copy(update=rewrite)}
    )


_DUTIES = (
    SFUDuty(
        action_verb="Coordinates",
        statement="Coordinates the student orientation program",
        how_why=["booking rooms for sessions", "preparing welcome packages"],
    ),
    SFUDuty(
        action_verb="Supervises",
        statement="Supervises two staff in the advising office",
        how_why=["assigning daily caseloads"],
    ),
)


def _jd(
    duties: tuple[SFUDuty, ...] = _DUTIES, decision_making: tuple[str, ...] = ()
) -> SFUJobDescription:
    return SFUJobDescription(
        title="Orientation Coordinator",
        position_summary="Supports new students.",
        duties=list(duties),
        decision_making=list(decision_making),
        qualifications=[SFUQualification(text="Degree in a related field")],
    )


def _merged(draft: SFUJobDescription) -> MergedRole:
    return MergedRole(
        draft=draft, provenance=MergeProvenance(member_count=2, skill_frequency=())
    )


_SOURCE_DECISION = (
    "Determines the order of the sessions and the rooms for the orientation."
)
#: Shares only "the", "and", "for", "orientation" with the source item — 4 of 8.
_INVENTED_DECISION = (
    "Terminates the employment of the staff and the volunteers for the orientation."
)


def test_function_words_cannot_ground_an_invented_decision(rules: Rules) -> None:
    merged = _merged(_jd(decision_making=(_SOURCE_DECISION,)))
    llm = _jd(decision_making=(_SOURCE_DECISION, _INVENTED_DECISION))

    out, record = _apply_anti_fabrication(llm, merged, rules)

    assert out.decision_making == [_SOURCE_DECISION]
    assert record.scrubbed_items == (("decision_making", _INVENTED_DECISION),)


def test_without_the_grounding_stopwords_the_padding_passes(rules: Rules) -> None:
    """The knob is the cause: emptied, the invented decision grounds at 0.5 again."""
    merged = _merged(_jd(decision_making=(_SOURCE_DECISION,)))
    llm = _jd(decision_making=(_SOURCE_DECISION, _INVENTED_DECISION))

    out, _record = _apply_anti_fabrication(
        llm, merged, _with(rules, grounding_stopwords=frozenset())
    )

    assert _INVENTED_DECISION in out.decision_making


#: b13e6321 (pilot): this source sentence left the draft and was "covered" at exactly
#: 0.5 by a duty sharing "and", "the", "such", "other", "services", "university", …
_MARKETING = (
    "Marketing services on the Web and in print media, with posters and brochures, "
    "in university publications such as the SFU Calendar, and in other ways, in "
    "order to reach the broader university community."
)


def test_function_words_cannot_cover_a_lost_duty_sentence(rules: Rules) -> None:
    source = SFUDuty(
        action_verb="Promotes",
        statement="Promotes the services of the Office.",
        how_why=[_MARKETING],
    )
    rewritten = SFUDuty(
        action_verb="Delivers",
        statement="Delivers education and outreach on the services of the Office "
        "across the university community, such as brochures and other media for SFU",
    )
    merged = _merged(_jd(duties=(source,)))

    out, record = _apply_anti_fabrication(_jd(duties=(rewritten,)), merged, rules)

    assert _MARKETING in out.duties[0].how_why
    assert _MARKETING in record.folded_duty_content


def test_a_changed_number_is_not_grounded(rules: Rules) -> None:
    source = "Decides daily work assignments for 2 staff in the advising office."
    changed = "Decides daily work assignments for 12 staff in the advising office."
    merged = _merged(_jd(decision_making=(source,)))

    out, record = _apply_anti_fabrication(
        _jd(decision_making=(changed,)), merged, rules
    )

    assert out.decision_making == [source]  # scrubbed, and the source's comes back
    assert record.scrubbed_items == (("decision_making", changed),)
    unchecked, _ = _apply_anti_fabrication(
        _jd(decision_making=(changed,)),
        merged,
        _with(rules, numbers_must_be_grounded=False),
    )
    assert changed in unchecked.decision_making


def test_a_duty_statement_with_an_ungrounded_acronym_is_flagged(rules: Rules) -> None:
    invented = "Coordinates the student orientation program under FIPPA"
    llm = _jd(
        duties=(
            _DUTIES[0].model_copy(update={"statement": invented}),
            _DUTIES[1],
        )
    )

    out, record = _apply_anti_fabrication(llm, _merged(_jd()), rules)

    assert invented in record.flagged_duties  # flagged, never dropped (HR-184)
    assert out.duties[0].statement == invented
    _out, unchecked = _apply_anti_fabrication(
        llm, _merged(_jd()), _with(rules, named_terms_must_be_grounded=False)
    )
    assert invented not in unchecked.flagged_duties

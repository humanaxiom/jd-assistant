"""The pure drift metric — how far a posting has diverged from its canonical role.

Ported from hris ``tests/unit/test_jd_bank_drift.py`` (15 tests), which is the
behavioural spec for the port (ADR-005: the hris tests ARE the specification).

On top of the port, the JD Bank suite pins the *decisions* hris hardcoded. Every
threshold, ladder and cue below now lives in ``rules/comparison.yaml``, so each is
asserted **by value** here (HR moving a number must turn a test red, not merely
change a branch) and its behavioural consequence is exercised through a patched
rulebook — proof the module reads the YAML rather than a Python constant.
"""

from __future__ import annotations

import pytest

from src.jd_core.bank import (
    compute_drift,
    education_level_from_text,
    education_ordinal,
    experience_years_from_text,
    supervisory_reports_from_text,
)
from src.jd_core.rules import Rules, get_rules
from tests.unit.retuned_rules import retuned as _retuned


@pytest.fixture
def rules() -> Rules:
    return get_rules()


# --- the hris spec (verbatim behaviour) ---------------------------------------


def test_identical_sets_are_aligned() -> None:
    d = compute_drift({"python", "sql"}, {"python", "sql"})
    assert d.level == "aligned"
    assert d.drift_score == 0.0
    assert d.added == []
    assert d.dropped == []
    assert d.shared_count == 2


def test_minor_drift_one_added() -> None:
    # 3 shared, 1 added -> Jaccard distance 1 - 3/4 = 0.25 -> minor (boundary).
    d = compute_drift({"python", "sql", "aws"}, {"python", "sql", "aws", "kafka"})
    assert d.level == "minor"
    assert d.added == ["kafka"]
    assert d.dropped == []


def test_major_drift_mostly_disjoint() -> None:
    d = compute_drift({"python", "sql"}, {"java", "spring"})
    assert d.level == "major"
    assert d.drift_score == 1.0
    assert d.added == ["java", "spring"]
    assert d.dropped == ["python", "sql"]
    assert d.shared_count == 0


def test_added_and_dropped_are_sorted() -> None:
    d = compute_drift({"c", "a"}, {"a", "z", "m"})
    assert d.added == ["m", "z"]
    assert d.dropped == ["c"]


def test_two_empty_sets_are_aligned() -> None:
    d = compute_drift(set(), set())
    assert d.level == "aligned"
    assert d.drift_score == 0.0


# --- the technical-knowledge escalation ---------------------------------------


def test_education_change_escalates_aligned_to_major() -> None:
    # Identical skills (aligned on skill churn) but the degree bar moved -> major.
    d = compute_drift(
        {"python"},
        {"python"},
        canonical_education=2,
        job_education=3,  # bachelors -> masters
    )
    assert d.level == "major"
    assert d.drift_score == 0.0  # the skill metric itself is unchanged
    assert any("education" in r for r in d.reasons)


def test_material_experience_change_escalates() -> None:
    d = compute_drift({"python"}, {"python"}, canonical_years=5, job_years=2)  # d3 >= 2
    assert d.level == "major"
    assert any("experience" in r for r in d.reasons)


def test_small_experience_change_does_not_escalate() -> None:
    d = compute_drift({"python"}, {"python"}, canonical_years=5, job_years=4)  # d1 < 2
    assert d.level == "aligned"
    assert d.reasons == []


def test_missing_side_never_manufactures_drift() -> None:
    # Only one side supplies a signal -> no escalation (conservative).
    d = compute_drift({"python"}, {"python"}, canonical_education=3, job_education=None)
    assert d.level == "aligned"
    assert d.reasons == []


def test_education_ordinal_maps_enum() -> None:
    assert education_ordinal("bachelors") == 2
    assert education_ordinal("phd") == 4
    assert education_ordinal(None) is None
    assert education_ordinal("nonsense") is None


def test_education_level_from_text_is_senior_first() -> None:
    assert education_level_from_text("Master's degree in CS or related discipline") == 3
    assert education_level_from_text("Bachelor's degree or equivalent") == 2
    assert education_level_from_text("PhD in a relevant field") == 4
    assert education_level_from_text("Diploma in office administration") == 1
    assert education_level_from_text("Strong communication skills") is None


def test_experience_years_from_text() -> None:
    assert experience_years_from_text("5 years of progressive experience") == 5
    assert experience_years_from_text("3+ years in a similar role") == 3
    assert experience_years_from_text("experience preferred") is None


def test_supervisory_reports_from_text() -> None:
    assert supervisory_reports_from_text("Supervises 4 coordinators.") == 4
    assert supervisory_reports_from_text("Manages a team of 8 staff") == 8
    assert supervisory_reports_from_text("Supervises the communications team") is None
    assert supervisory_reports_from_text("") is None


def test_supervisory_change_over_five_escalates() -> None:
    # delta 7 > 5
    d = compute_drift({"python"}, {"python"}, canonical_reports=2, job_reports=9)
    assert d.level == "major"
    assert any("supervisory" in r for r in d.reasons)


def test_supervisory_change_within_five_does_not_escalate() -> None:
    d = compute_drift({"python"}, {"python"}, canonical_reports=2, job_reports=6)  # d4
    assert d.level == "aligned"
    assert d.reasons == []


# --- the escalation reasons name what moved -----------------------------------


def test_a_reason_names_the_education_rungs_it_moved_between(rules: Rules) -> None:
    """The reason is HR-facing copy: it must say *bachelors -> masters*, not *2 -> 3*.
    The rung NAMES come from the ladder in the YAML, not a second Python dict."""
    d = compute_drift({"python"}, {"python"}, canonical_education=2, job_education=3)
    assert d.reasons == ["education requirement changed (bachelors → masters)"]
    assert rules.comparison.education_ladder[2:4] == ("bachelors", "masters")


def test_every_escalation_reason_can_fire_at_once() -> None:
    d = compute_drift(
        {"python"},
        {"python"},
        canonical_education=2,
        job_education=4,
        canonical_years=2,
        job_years=9,
        canonical_reports=1,
        job_reports=12,
    )
    assert d.level == "major"
    assert len(d.reasons) == 3


# --- the decisions, pinned BY VALUE (rules-as-data, CLAUDE.md §2) --------------


def test_the_drift_levels_are_data_pinned_by_value(rules: Rules) -> None:
    """Jaccard-distance cutoffs. `hris_calibration` (HR-098/HR-099): SFU publishes
    no skill-churn metric at all, so these are ours-by-inheritance, not a standard."""
    assert rules.comparison.drift_minor_at == 0.25
    assert rules.comparison.drift_major_at == 0.50


def test_the_material_deltas_are_data_pinned_by_value(rules: Rules) -> None:
    """>= 2 years, > 5 direct reports. hris cited the second to "SFU Toolkit p26"; the
    shipped rulebook (docs/rulebook/sfu-jd-standards.txt) contains **no**
    re-evaluation criteria at all — see HR-100/HR-101. Registered `hris_calibration`."""
    assert rules.comparison.material_years_delta == 2
    assert rules.comparison.material_reports_delta == 5


def test_the_education_ladder_is_data_pinned_by_value(rules: Rules) -> None:
    """ONE ladder for the whole rulebook: drift's ordinals and similarity's ordinal
    closeness both index THIS tuple. hris held it twice (``_EDU_ORDINAL`` and
    ``_EDU_ORDER``) with nothing keeping them in step."""
    assert rules.comparison.education_ladder == (
        "high_school",
        "associate",
        "bachelors",
        "masters",
        "phd",
    )


def test_the_education_cues_are_tried_most_senior_first(rules: Rules) -> None:
    """ "Master's degree" must map to masters, not to the generic "degree" -> bachelors
    rung. hris held the try-order as a hand-written sequence *next to* the ladder; here
    it is DERIVED from the ladder (senior first), so the two cannot disagree."""
    order = [rung for rung, _cues in rules.comparison.education_text_rules]
    assert order == list(reversed(rules.comparison.education_ladder))
    assert "degree" in rules.comparison.education_text_cues["bachelors"]
    assert "master" in rules.comparison.education_text_cues["masters"]


# --- and the module reads the YAML, not a constant -----------------------------


def test_moving_the_minor_cutoff_moves_the_verdict(rules: Rules) -> None:
    retuned = _retuned(rules, drift_minor_at=0.30)
    # the 0.25-distance case that is `minor` on the shipped rulebook...
    canonical, job = {"python", "sql", "aws"}, {"python", "sql", "aws", "kafka"}
    assert compute_drift(canonical, job).level == "minor"
    # ...is `aligned` once HR raises the bar. No code change.
    assert compute_drift(canonical, job, rules=retuned).level == "aligned"


def test_moving_the_material_years_delta_moves_the_escalation(rules: Rules) -> None:
    retuned = _retuned(rules, material_years_delta=4)
    assert compute_drift({"a"}, {"a"}, canonical_years=5, job_years=2).level == "major"
    assert (
        compute_drift({"a"}, {"a"}, canonical_years=5, job_years=2, rules=retuned).level
        == "aligned"
    )


def test_moving_the_reports_delta_moves_the_escalation(rules: Rules) -> None:
    retuned = _retuned(rules, material_reports_delta=10)
    assert (
        compute_drift({"a"}, {"a"}, canonical_reports=2, job_reports=9).level == "major"
    )
    assert (
        compute_drift(
            {"a"}, {"a"}, canonical_reports=2, job_reports=9, rules=retuned
        ).level
        == "aligned"
    )


def test_reordering_the_ladder_moves_the_ordinals(rules: Rules) -> None:
    """The ladder is the ordinal scale: education_ordinal is its index, and the rung
    names in a reason come back out of it."""
    retuned = _retuned(
        rules,
        education_ladder=["high_school", "associate", "bachelors", "phd", "masters"],
    )
    assert education_ordinal("masters", rules=retuned) == 4
    assert education_ordinal("phd", rules=retuned) == 3


def test_teaching_the_parser_a_new_education_cue(rules: Rules) -> None:
    cues = {
        rung: list(vals) for rung, vals in rules.comparison.education_text_cues.items()
    }
    cues["masters"] = [*cues["masters"], "llm"]
    retuned = _retuned(rules, education_text_cues=cues)
    assert education_level_from_text("An LLM in tax law") is None
    assert education_level_from_text("An LLM in tax law", rules=retuned) == 3

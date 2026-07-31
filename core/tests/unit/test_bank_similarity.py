"""The pure job-to-job similarity scorer + clone-vs-new verdict.

Ported from hris ``tests/unit/test_jd_bank_similarity.py`` (18 tests) — the
behavioural spec (ADR-005). Plus the JD Bank half: every weight, threshold,
stop-word and default hris hardcoded is now ``rules/comparison.yaml``, so each is
pinned **by value** and its effect is exercised through a retuned rulebook.

Nothing here is wired to anything (see ``bank/similarity.py``): the ontology
families and the idf corpus these functions take are injected by the caller, and
JD Bank has neither yet. The maths is landed, tested and registered; Phase 3 gets
to supply the inputs.
"""

from __future__ import annotations

import pytest

from src.jd_core.bank import (
    clone_verdict,
    normalize_title,
    score_job_similarity,
    seniority_closeness,
    skill_overlap,
)
from src.jd_core.rules import Comparison, Rules, get_rules
from tests.unit.retuned_rules import raw_comparison
from tests.unit.retuned_rules import retuned as _retuned


@pytest.fixture
def rules() -> Rules:
    return get_rules()


def test_sim_version(rules: Rules) -> None:
    """hris kept the formula's version stamp as a module constant; here it is a field
    of the file that holds the formula's calibration, so bumping it is a data edit."""
    assert rules.comparison.sim_version == "jd_sim_v2"


# --- title normalization (title-agnostic grouping) ----------------------------


def test_normalize_title_strips_seniority_and_levels() -> None:
    assert normalize_title("Senior Software Developer II") == "software developer"
    assert normalize_title("Sr. Developer") == "developer"
    assert normalize_title("Developer") == "developer"


def test_title_variants_normalize_equal() -> None:
    assert normalize_title("Lead Engineer III") == normalize_title("Engineer")


# --- skill overlap ------------------------------------------------------------


def test_skill_overlap_exact_subset() -> None:
    a = {"python", "sql"}
    b = {"python", "sql", "go"}
    # exact intersection 2, union 3 -> 0.666...
    assert round(skill_overlap(a, b, {}), 3) == 0.667


def test_skill_overlap_identical_sets_is_one() -> None:
    a = {"python", "sql"}
    assert skill_overlap(a, a, {}) == 1.0


def test_skill_overlap_empty_side_is_zero() -> None:
    assert skill_overlap(set(), {"python"}, {}) == 0.0
    assert skill_overlap({"python"}, set(), {}) == 0.0


def test_skill_overlap_family_partial_credit() -> None:
    # postgresql vs mysql: no exact overlap, but same family -> family credit.
    a = {"postgresql"}
    b = {"mysql"}
    families = {
        "postgresql": frozenset({"relational-db"}),
        "mysql": frozenset({"relational-db"}),
    }
    # exact 0 + family_weight 0.5, union 2 -> 0.25
    assert skill_overlap(a, b, families) == 0.25


def test_skill_overlap_non_matchable_family_grants_no_credit() -> None:
    a = {"x"}
    b = {"y"}
    families = {"x": frozenset({"other"}), "y": frozenset({"other"})}
    assert skill_overlap(a, b, families) == 0.0


# --- seniority closeness ------------------------------------------------------


def test_seniority_closeness_same_is_high() -> None:
    assert seniority_closeness(5, 5, "bachelors", "bachelors") == 1.0


def test_seniority_closeness_far_years_lower() -> None:
    assert seniority_closeness(2, 12, "bachelors", "bachelors") < 0.6


def test_seniority_closeness_unknown_is_neutral() -> None:
    assert seniority_closeness(None, None, None, None) == 0.7


# --- overall score ------------------------------------------------------------


def test_score_weights_components() -> None:
    # vector 1.0, skill 0.0, seniority 0.0 -> 0.45 (vector weight)
    assert score_job_similarity(1.0, 0.0, 0.0) == 0.45
    # skill alone carries equal weight to the embedding
    assert score_job_similarity(0.0, 1.0, 0.0) == 0.45
    # all 1.0 -> 1.0
    assert score_job_similarity(1.0, 1.0, 1.0) == 1.0
    # vector clamps above 1
    assert score_job_similarity(1.5, 0.0, 0.0) == 0.45


def test_idf_downweights_generic_skills() -> None:
    # Two jobs share only a ubiquitous skill (low idf) plus each has a distinct
    # rare skill (high idf). idf-weighted overlap is much lower than plain.
    a = {"communication", "prolog"}
    b = {"communication", "haskell"}
    idf = {"communication": 0.1, "prolog": 5.0, "haskell": 5.0}
    weighted = skill_overlap(a, b, {}, idf=idf)
    plain = skill_overlap(a, b, {})  # 1 shared / 3 union = 0.333
    assert weighted < plain
    assert weighted < 0.05  # 0.1 / (0.1+5+5) ~ 0.0098


def test_idf_keeps_distinctive_shared_skills_high() -> None:
    # Sharing a rare skill scores high even with idf.
    a = {"kubernetes"}
    b = {"kubernetes"}
    idf = {"kubernetes": 6.0}
    assert skill_overlap(a, b, {}, idf=idf) == 1.0


# --- clone-vs-new verdict -----------------------------------------------------


def test_verdict_clone_when_near_identical_same_title_dept() -> None:
    verdict, basis = clone_verdict(0.95, same_title=True, same_department=True)
    assert verdict == "clone"
    assert "same title" in basis
    assert "same department" in basis


def test_verdict_new_job_when_strong_but_different_title() -> None:
    verdict, _ = clone_verdict(0.80, same_title=False, same_department=True)
    assert verdict == "new_job"


def test_verdict_new_job_when_strong_but_different_department() -> None:
    verdict, _ = clone_verdict(0.80, same_title=True, same_department=False)
    assert verdict == "new_job"


def test_verdict_uncertain_below_threshold() -> None:
    verdict, _ = clone_verdict(0.50, same_title=False, same_department=False)
    assert verdict == "uncertain"


# --- the decisions, pinned BY VALUE (rules-as-data, CLAUDE.md §2) --------------


def test_the_similarity_weights_are_data_pinned_by_value(rules: Rules) -> None:
    """0.45 / 0.45 / 0.10. `prior_calibration` (HR-084..HR-086) — SFU has never
    published a similarity formula, let alone its weights. The rebalance that gave
    skills equal weight to the embedding was an hris judgement call about *its* corpus,
    on a skill graph JD Bank does not have."""
    comparison = rules.comparison
    assert comparison.weight_vector == 0.45
    assert comparison.weight_skill == 0.45
    assert comparison.weight_seniority == 0.10


def test_the_weights_must_sum_to_one(rules: Rules) -> None:
    """Not decoration: it is what makes the score a 0-1 number the thresholds below
    can be compared against. The loader refuses a rulebook whose weights do not."""
    comparison = rules.comparison
    assert (
        comparison.weight_vector + comparison.weight_skill + comparison.weight_seniority
    ) == pytest.approx(1.0)
    with pytest.raises(ValueError, match="must sum to 1.0"):
        Comparison.model_validate({**raw_comparison(), "weight_seniority": 0.2})


def test_the_similarity_thresholds_are_data_pinned_by_value(rules: Rules) -> None:
    comparison = rules.comparison
    assert comparison.sim_threshold == 0.60  # the "show me similar" noise floor
    assert comparison.clone_threshold == 0.92  # near-identical -> a true clone
    assert comparison.min_cluster_skill_overlap == 0.30  # distinctive-skill edge gate


def test_the_skill_overlap_knobs_are_data_pinned_by_value(rules: Rules) -> None:
    comparison = rules.comparison
    assert comparison.family_weight == 0.5
    assert comparison.non_matchable_families == frozenset({"other", "domain"})


def test_the_seniority_defaults_are_data_pinned_by_value(rules: Rules) -> None:
    """The two numbers hris buried inside ``seniority_closeness``: what an unknown
    signal is worth (0.7 — a *guess*, and it is neutral-ish by construction), and how
    many years apart two roles must be before experience closeness bottoms out (10)."""
    comparison = rules.comparison
    assert comparison.unknown_signal_closeness == 0.7
    assert comparison.experience_span_years == 10.0


def test_the_title_stopwords_are_data_pinned_by_value(rules: Rules) -> None:
    """The whole list, not a spot-check: dropping `principal` (or adding `head`)
    silently re-groups every title in the archive."""
    assert rules.comparison.title_stopwords == frozenset(
        {
            "senior",
            "sr",
            "junior",
            "jr",
            "lead",
            "principal",
            "staff",
            "associate",
            "assistant",
            "intern",
            "trainee",
            "i",
            "ii",
            "iii",
            "iv",
            "v",
            "1",
            "2",
            "3",
            "4",
            "5",
        }
    )


# --- and the module reads the YAML, not a constant -----------------------------


def test_reweighting_the_score_changes_it(rules: Rules) -> None:
    retuned = _retuned(rules, weight_vector=0.8, weight_skill=0.1, weight_seniority=0.1)
    assert score_job_similarity(1.0, 0.0, 0.0) == 0.45
    assert score_job_similarity(1.0, 0.0, 0.0, rules=retuned) == 0.8


def test_moving_the_clone_threshold_moves_the_verdict(rules: Rules) -> None:
    retuned = _retuned(rules, clone_threshold=0.97)
    assert clone_verdict(0.95, same_title=True, same_department=True)[0] == "clone"
    verdict, _ = clone_verdict(
        0.95, same_title=True, same_department=True, rules=retuned
    )
    assert verdict == "uncertain"  # no longer a clone, and same title+dept -> not new


def test_moving_the_sim_threshold_moves_the_verdict(rules: Rules) -> None:
    retuned = _retuned(rules, sim_threshold=0.85)
    assert clone_verdict(0.80, same_title=False, same_department=True)[0] == "new_job"
    verdict, _ = clone_verdict(
        0.80, same_title=False, same_department=True, rules=retuned
    )
    assert verdict == "uncertain"


def test_retuning_the_family_weight_changes_the_partial_credit(rules: Rules) -> None:
    families = {
        "postgresql": frozenset({"relational-db"}),
        "mysql": frozenset({"relational-db"}),
    }
    retuned = _retuned(rules, family_weight=1.0)
    assert skill_overlap({"postgresql"}, {"mysql"}, families) == 0.25
    assert skill_overlap({"postgresql"}, {"mysql"}, families, rules=retuned) == 0.5


def test_a_family_declared_non_matchable_grants_no_credit(rules: Rules) -> None:
    families = {"a": frozenset({"soft-skills"}), "b": frozenset({"soft-skills"})}
    assert skill_overlap({"a"}, {"b"}, families) == 0.25
    retuned = _retuned(rules, non_matchable_families=["other", "domain", "soft-skills"])
    assert skill_overlap({"a"}, {"b"}, families, rules=retuned) == 0.0


def test_dropping_a_title_stopword_stops_collapsing_the_variant(
    rules: Rules,
) -> None:
    kept = sorted(rules.comparison.title_stopwords - {"senior"})
    retuned = _retuned(rules, title_stopwords=kept)
    assert normalize_title("Senior Developer") == "developer"
    assert normalize_title("Senior Developer", rules=retuned) == "senior developer"


def test_widening_the_experience_span_softens_the_years_penalty(
    rules: Rules,
) -> None:
    """The `/10.0` divisor: two roles 10 years apart score 0 on experience closeness
    today. Widen the span to 20 and they score 0.5."""
    retuned = _retuned(rules, experience_span_years=20.0)
    assert seniority_closeness(2, 12, "phd", "phd") == 0.5  # (0.0 + 1.0) / 2
    assert seniority_closeness(2, 12, "phd", "phd", rules=retuned) == 0.75


def test_an_unknown_education_level_falls_back_to_the_unknown_default(
    rules: Rules,
) -> None:
    """A level that is not a rung of the ladder is *unknown*, not maximally distant —
    the same 0.7 an absent value gets. (hris reached this branch via a ValueError.)"""
    assert seniority_closeness(5, 5, "sommelier", "bachelors") == 0.85  # (1 + 0.7) / 2
    retuned = _retuned(rules, unknown_signal_closeness=0.0)
    assert seniority_closeness(5, 5, "sommelier", "bachelors", rules=retuned) == 0.5


def test_two_identical_off_ladder_levels_are_identical_not_unknown() -> None:
    """hris checks ``a == b`` BEFORE it indexes the ladder. So two roles stating the
    same unrecognised level are identical on education (1.0), not mutually unknown
    (0.7). Ported deliberately — reordering those two lines is a silent behaviour
    change that no other test in the suite would catch."""
    assert seniority_closeness(5, 5, "sommelier", "sommelier") == 1.0
    assert seniority_closeness(5, 5, "sommelier", "barista") == 0.85  # (1 + 0.7) / 2


def test_education_closeness_walks_the_shared_ladder(rules: Rules) -> None:
    """Ordinal closeness over the ONE ladder (``comparison.education_ladder``) that
    drift's ordinals also index — 5 rungs, so adjacent rungs are 1 - 1/4 = 0.75 apart
    and the extremes score 0."""
    assert seniority_closeness(5, 5, "bachelors", "masters") == 0.875  # (1 + .75) / 2
    assert seniority_closeness(5, 5, "high_school", "phd") == 0.5  # (1 + 0.0) / 2

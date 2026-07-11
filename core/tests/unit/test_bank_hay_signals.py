"""Advisory Hay-factor signal estimation (ported from hris).

The behavioural spec is hris ``tests/unit/test_jd_bank_hay_signals.py``. Every case
there is reproduced here — with **one deliberate exception**, called out because it
is the whole point of the port:

    hris's ``test_advisory_contract_never_a_grade`` asserts
    ``sig.grade_mapped is False``. JD Bank's :class:`HaySignals` has **no
    ``grade_mapped`` field**, on purpose: SFU publishes no Hay point charts, so a
    graded signal is made *unrepresentable* rather than merely left False (see the
    source-gate note in ``models/bank.py``). "Unmapped" is not a state to render —
    it is the only state there is. The assertion is therefore replaced by a
    *stronger* one: the estimator's output cannot carry a grade at all.

The other thing this port adds is rulebook-as-data. hris hardcoded five keyword
lexicons AND every weight and cutoff (``score += 3``, ``_level(score, mod=3,
hi=5)``) in Python. Those numbers decide whether a role reads as low or high on a
Hay factor — they are exactly the "non-trivial metric" CLAUDE.md §2 forbids
hardcoding. They now live in ``rules/hay_signals.yaml``, are registered `open`
(HR-066 … HR-081), and the tests below prove the estimator reads them.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from src.jd_core.bank import estimate_hay_signals
from src.jd_core.models.bank import HAY_SIGNALS_VERSION, HaySignals
from src.jd_core.models.parsed_jd import (
    SFUDuty,
    SFUJobDescription,
    SFUQualification,
    SFURelationships,
)
from src.jd_core.rules import RULE_FILES, Rules, RulesError, get_rules, load_rules


def _senior_jd() -> SFUJobDescription:
    """A senior role: graduate education, expert skills, broad autonomy + reports."""
    return SFUJobDescription(
        title="Director, Information Services",
        duties=[SFUDuty(statement="Leads the unit.")],
        decision_making=[
            "Approves the annual budget without prior approval.",
            "Holds final decision authority on strategic technology direction.",
        ],
        problem_solving=[
            "Resolves novel, ambiguous, complex problems requiring independent "
            "judgment.",
            "Interprets and evaluates unprecedented situations.",
        ],
        relationships=SFURelationships(
            supervisory="Manages a team of 8 analysts.",
            internal=["Registrar"],
            external=["Vendors", "Government", "Peer institutions"],
        ),
        qualifications=[
            SFUQualification(
                text="Master's degree in a relevant discipline", kind="education"
            ),
            SFUQualification(
                text="Cloud architecture", kind="skill", modifier="expert"
            ),
            SFUQualification(text="Data governance", kind="skill", modifier="advanced"),
            SFUQualification(
                text="Security frameworks", kind="skill", modifier="advanced"
            ),
            SFUQualification(
                text="Public-sector policy", kind="knowledge", modifier="excellent"
            ),
            SFUQualification(text="10 years experience", kind="experience"),
        ],
    )


def _junior_jd() -> SFUJobDescription:
    """A routine role: no autonomy, closely-supervised, defined procedures."""
    return SFUJobDescription(
        title="Office Assistant",
        duties=[SFUDuty(statement="Files documents.")],
        decision_making=["Follows clearly defined procedures under supervision."],
        problem_solving=[
            "Handles routine issues using established procedure, under close "
            "supervision."
        ],
        relationships=SFURelationships(
            supervisory=None, internal=["Team lead"], external=[]
        ),
        qualifications=[
            SFUQualification(text="High school diploma", kind="education"),
            SFUQualification(text="Data entry", kind="skill", modifier="basic"),
        ],
    )


# --- the hris spec ------------------------------------------------------------


def test_senior_role_signals_high() -> None:
    sig = estimate_hay_signals(_senior_jd())
    assert sig.know_how.level == "high"
    assert sig.accountability.level == "high"
    assert sig.problem_solving.level in ("moderate", "high")
    # Every factor cites the phrases that drove it.
    assert sig.accountability.evidence
    assert sig.know_how.evidence


def test_junior_role_signals_low() -> None:
    sig = estimate_hay_signals(_junior_jd())
    assert sig.know_how.level == "low"
    assert sig.problem_solving.level == "low"
    assert sig.accountability.level == "low"


def test_advisory_contract_never_a_grade() -> None:
    """hris asserted ``grade_mapped is False``. Here the field does not exist —
    the source-gate is structural, not a flag someone could flip."""
    sig = estimate_hay_signals(_senior_jd())
    assert sig.version == HAY_SIGNALS_VERSION
    for factor in (sig.know_how, sig.problem_solving, sig.accountability):
        assert factor.level in ("low", "moderate", "high")
        assert "not a grade" in factor.rationale.lower()

    # The replacement for hris's `grade_mapped is False`: unrepresentable, not False.
    assert not hasattr(sig, "grade_mapped")
    assert not hasattr(sig, "grade")
    assert {"grade", "grade_mapped"}.isdisjoint(HaySignals.model_fields)
    assert {"grade", "grade_mapped"}.isdisjoint(sig.model_dump())


def test_empty_sections_are_low_and_noted() -> None:
    sig = estimate_hay_signals(SFUJobDescription(title="Bare"))
    assert sig.problem_solving.level == "low"
    assert sig.accountability.level == "low"
    assert any("no " in e.lower() for e in sig.problem_solving.evidence)
    assert any("no " in e.lower() for e in sig.accountability.evidence)


def test_evidence_is_deduped_and_capped() -> None:
    jd = SFUJobDescription(
        title="Repetitive",
        decision_making=["independently " * 20, "authority authority authority"],
    )
    sig = estimate_hay_signals(jd)
    assert len(sig.accountability.evidence) <= 12
    assert len(sig.accountability.evidence) == len(set(sig.accountability.evidence))


# --- the middle branches: registered numbers nothing else exercises -----------
#
# The senior fixture matches `master` and takes the "many advanced skills" branch;
# the junior one says "High school diploma" and has no advanced skills at all. So
# BOTH middle branches of Know-How — `education_undergraduate` (HR-073 = 2.0, via
# the HR-067 lexicon) and `some_advanced_skills` (HR-073 = 1.0) — were never
# executed. HR could have moved either number and nothing would have gone red, on
# parameters this very change registered. CLAUDE.md #4 says every rule gets a test.


@pytest.mark.parametrize("degree", ["bachelor", "undergraduate", "degree"])
def test_an_undergraduate_degree_takes_the_middle_education_branch(
    degree: str,
) -> None:
    """Each HR-067 cue scores `education_undergraduate` (2.0) — NOT the graduate
    3.0, and not zero."""
    jd = SFUJobDescription(
        title="Advisor",
        qualifications=[
            SFUQualification(text=f"A {degree} in a relevant field", kind="education")
        ],
    )
    signal = estimate_hay_signals(jd).know_how
    assert signal.evidence == ["undergraduate degree required"]
    # 2.0 is below the shipped `moderate` cutoff of 3.0 that a graduate degree clears
    assert signal.level == "low"


def test_the_undergraduate_branch_is_worth_what_hr_073_says(tmp_path: Path) -> None:
    """Pin the *number*, not just the branch: raise `education_undergraduate` to the
    `moderate` cutoff and the same JD moves a level. Move it in YAML and this
    fails."""
    jd = SFUJobDescription(
        title="Advisor",
        qualifications=[SFUQualification(text="Bachelor's degree", kind="education")],
    )
    assert estimate_hay_signals(jd).know_how.level == "low"

    def _raise(data: dict[str, Any]) -> None:
        data["know_how_points"]["education_undergraduate"] = 3.0  # == moderate cutoff

    tuned = _rules_with_hay(tmp_path, _raise)
    assert estimate_hay_signals(jd, rules=tuned).know_how.level == "moderate"


def test_a_graduate_degree_beats_the_undergraduate_branch() -> None:
    """The two education branches are exclusive and graduate wins — "Master's
    degree" contains `degree` (an HR-067 cue) too, so order matters here as well."""
    jd = SFUJobDescription(
        title="Analyst",
        qualifications=[
            SFUQualification(text="Master's degree in statistics", kind="education")
        ],
    )
    assert estimate_hay_signals(jd).know_how.evidence == [
        "graduate-level education required"
    ]


def test_one_advanced_skill_takes_the_some_not_the_many_branch() -> None:
    """`some_advanced_skills` (HR-073 = 1.0) fires below HR-074's
    `advanced_skills_for_many` cliff of 3. The singular-plural wording is how a
    reviewer tells the two branches apart in a report."""

    def _jd(count: int) -> SFUJobDescription:
        return SFUJobDescription(
            title="Specialist",
            qualifications=[
                SFUQualification(text=f"Skill {i}", kind="skill", modifier="advanced")
                for i in range(count)
            ],
        )

    assert estimate_hay_signals(_jd(1)).know_how.evidence == [
        "1 advanced/expert skill(s)"
    ]
    assert estimate_hay_signals(_jd(2)).know_how.evidence == [
        "2 advanced/expert skill(s)"
    ]
    # one more crosses HR-074's cliff into the `many` branch
    assert estimate_hay_signals(_jd(3)).know_how.evidence == [
        "3 advanced/expert skills"
    ]


def test_the_many_advanced_skills_cliff_is_data(tmp_path: Path) -> None:
    """HR-074 says three advanced skills is "many". Move the cliff and two is."""
    jd = SFUJobDescription(
        title="Specialist",
        qualifications=[
            SFUQualification(text=f"Skill {i}", kind="skill", modifier="expert")
            for i in range(2)
        ],
    )
    assert estimate_hay_signals(jd).know_how.evidence == ["2 advanced/expert skill(s)"]

    def _lower(data: dict[str, Any]) -> None:
        data["know_how_counts"]["advanced_skills_for_many"] = 2

    tuned = _rules_with_hay(tmp_path, _lower)
    assert estimate_hay_signals(jd, rules=tuned).know_how.evidence == [
        "2 advanced/expert skills"
    ]


def test_evidence_is_capped_when_a_jd_really_does_trip_everything() -> None:
    """hris's cap test never actually reaches the cap (it produces 2 phrases). This
    one does: every autonomy cue at once, plus supervisory scope and external
    breadth, is 17 pieces of evidence — and the signal must still be constructible."""
    rules = get_rules()
    cap = rules.hay_signals.evidence_cap
    every_cue = ". ".join(rules.hay_signals.acc_autonomy)
    jd = SFUJobDescription(
        title="Maximal",
        decision_making=[every_cue],
        relationships=SFURelationships(
            supervisory="Manages everyone.", external=["a", "b", "c"]
        ),
    )
    sig = estimate_hay_signals(jd)
    assert len(rules.hay_signals.acc_autonomy) + 2 > cap  # the cap really bites
    assert len(sig.accountability.evidence) == cap
    assert sig.accountability.level == "high"


# --- rulebook-as-data: the lexicons AND the calibration live in YAML ----------

_PKG_DIR = Path(__file__).resolve().parents[2] / "src" / "jd_core" / "rules"


def _rules_with_hay(directory: Path, mutate: Any) -> Rules:
    """The shipped rulebook, with ``hay_signals.yaml`` mutated. Nothing else moves."""
    for name in RULE_FILES:
        (directory / name).write_text(
            (_PKG_DIR / name).read_text(encoding="utf-8"), encoding="utf-8"
        )
    path = directory / "hay_signals.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    mutate(data)
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return load_rules(directory)


def test_the_level_cutoffs_are_data_not_a_python_default(tmp_path: Path) -> None:
    """hris hardcoded ``_level(score, mod=3, hi=5)``. Raise the Know-How cutoffs in
    YAML and the *same* senior JD stops reading as high — with no code change. This
    is the number HR has to be able to move."""
    senior = _senior_jd()
    assert estimate_hay_signals(senior).know_how.level == "high"

    def _raise_the_bar(data: dict[str, Any]) -> None:
        data["know_how_levels"] = {"moderate": 9.0, "high": 20.0}

    tuned = _rules_with_hay(tmp_path, _raise_the_bar)
    assert estimate_hay_signals(senior, rules=tuned).know_how.level == "low"


def test_the_lexicons_are_data(tmp_path: Path) -> None:
    """Teach the rulebook a new autonomy cue and the estimator scores it."""
    jd = SFUJobDescription(
        title="Steward", decision_making=["Exercises stewardship over the endowment."]
    )
    assert not estimate_hay_signals(jd).accountability.evidence

    def _teach(data: dict[str, Any]) -> None:
        data["acc_autonomy"].append("stewardship")

    tuned = _rules_with_hay(tmp_path, _teach)
    taught = estimate_hay_signals(jd, rules=tuned)
    assert '"stewardship"' in taught.accountability.evidence


def test_routine_language_subtracts_and_the_weight_is_data(tmp_path: Path) -> None:
    """A negative weight is a policy statement ("routine language means *less*
    problem-solving"). Neutralise it in YAML and the junior JD stops being penalised
    for it."""
    junior = _junior_jd()
    shipped = estimate_hay_signals(junior).problem_solving
    assert any("routine" in e.lower() for e in shipped.evidence)

    def _neutralise(data: dict[str, Any]) -> None:
        data["problem_solving_points"]["routine_hit"] = 0.0
        data["problem_solving_levels"] = {"moderate": 0.5, "high": 3.0}

    tuned = _rules_with_hay(tmp_path, _neutralise)
    assert estimate_hay_signals(junior, rules=tuned).problem_solving.level == "moderate"


def test_the_advanced_skill_modifiers_are_data(tmp_path: Path) -> None:
    jd = SFUJobDescription(
        title="Specialist",
        qualifications=[
            SFUQualification(text=f"Skill {i}", kind="skill", modifier="intermediate")
            for i in range(3)
        ],
    )
    assert not estimate_hay_signals(jd).know_how.evidence

    def _promote(data: dict[str, Any]) -> None:
        data["advanced_skill_modifiers"].append("intermediate")

    tuned = _rules_with_hay(tmp_path, _promote)
    evidence = estimate_hay_signals(jd, rules=tuned).know_how.evidence
    assert any("advanced/expert skills" in e for e in evidence)


# --- the rulebook cannot ship an unusable Hay table ---------------------------


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        # a points key the estimator reads, deleted
        (
            lambda d: d["know_how_points"].pop("supervisory_scope"),
            "know_how_points",
        ),
        # a points key the estimator never reads, added (a knob wired to nothing)
        (
            lambda d: d["accountability_points"].__setitem__("vibes", 3.0),
            "accountability_points",
        ),
        # a level with no cutoff could never be awarded
        (
            lambda d: d["know_how_levels"].pop("moderate"),
            "know_how_levels",
        ),
        # `low` is the floor — it must not carry a cutoff
        (
            lambda d: d["accountability_levels"].__setitem__("low", 0.0),
            "accountability_levels",
        ),
        # more evidence than HayFactorSignal.evidence will hold
        (lambda d: d.__setitem__("evidence_cap", 50), "evidence_cap"),
        # a count that would make min(len, 0) silently score nothing
        (
            lambda d: d["problem_solving_counts"].__setitem__(
                "section_items_scored", 0
            ),
            "section_items_scored",
        ),
    ],
)
def test_an_unusable_hay_table_fails_to_load(
    tmp_path: Path, mutation: Any, expected: str
) -> None:
    """The estimator indexes these tables by name. A missing key would be a
    ``KeyError`` in the middle of a JD; an unknown key would be a knob HR thinks
    they turned that is wired to nothing. Both are load errors."""
    with pytest.raises(RulesError) as exc:
        _rules_with_hay(tmp_path, mutation)
    assert expected in str(exc.value)


# --- the modifier vocabulary is qualifications.yaml's, not ours ---------------


def test_the_hay_modifiers_are_a_subset_of_the_rulebooks_own_scales() -> None:
    """``hay_signals.yaml`` does not get its own private copy of SFU's modifier
    scales. It names modifiers FROM them (rulebook Parts 5.2 / 5.1), and the loader
    holds the two files together."""
    rules = get_rules()
    assert (
        rules.hay_signals.advanced_skill_modifiers
        <= rules.qualifications.skill_modifiers
    )
    assert (
        rules.hay_signals.excellent_knowledge_modifiers
        <= rules.qualifications.knowledge_modifiers
    )


def test_a_hay_modifier_that_is_not_on_the_rulebooks_scale_fails_to_load(
    tmp_path: Path,
) -> None:
    with pytest.raises(RulesError) as exc:
        _rules_with_hay(
            tmp_path, lambda d: d["advanced_skill_modifiers"].append("wizardly")
        )
    assert "wizardly" in str(exc.value)
    assert "skill_modifiers" in str(exc.value)


def test_renaming_a_modifier_in_qualifications_yaml_breaks_the_build(
    tmp_path: Path,
) -> None:
    """**The landmine this guard exists for.** ``skill_modifiers`` and
    ``advanced_skill_modifiers`` are two files naming the same SFU vocabulary. Before
    the cross-file check, re-casing or renaming one of them left the OTHER pointing
    at a modifier that no longer exists: the Know-How signal would quietly stop
    scoring advanced skills for every JD at SFU, with no load error, no failing test
    and green gates. (Same shape as the `max_listed` duplicate knob on the backlog —
    but on a *registered* decision parameter.) Now it does not load."""
    for name in RULE_FILES:
        (tmp_path / name).write_text(
            (_PKG_DIR / name).read_text(encoding="utf-8"), encoding="utf-8"
        )
    path = tmp_path / "qualifications.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["skill_modifiers"] = [m for m in data["skill_modifiers"] if m != "expert"] + [
        "mastery"
    ]
    path.write_text(yaml.safe_dump(data), encoding="utf-8")

    with pytest.raises(RulesError) as exc:
        load_rules(tmp_path)
    assert "expert" in str(exc.value)

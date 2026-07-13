"""Unit tests for the JD approval gate runner (Phase 2.3).

``evaluate_gates`` is what stands between a draft JD and an HR reviewer's approve
button. It never approves *for* a human (CLAUDE.md non-negotiable #1: nothing
auto-publishes) — it decides whether approval is even **permitted**, and when it
is not, says why in rulebook terms.

Two invariants drive this suite:

* **#2 RULEBOOK AS DATA.** Every parameter that participates in the decision —
  the blocking rule-id set, the severity floor, the score floor, the grade floor,
  each gate's overridability, its reason copy, its ``source_part`` — is versioned
  YAML (``rules/gates.yaml``). The headline tests here load a *modified* policy
  and show the decision flip with **no code change**.
* **#4 TDD + GATES.** Every gate in the shipped policy gets a failing fixture (a
  JD that trips it, blocked, with the right reason) **and** a passing fixture (a
  JD that does not). ``test_every_gate_has_a_failing_fixture`` /
  ``..._passing_fixture`` break the build if a new gate ships without its pair.

Assertions are on the decision post-state (``gate_id``, ``approved``,
``rule_ids``, ``overridable``) — never on verbatim prose (#3).
"""

from __future__ import annotations

import datetime as dt
import math
from pathlib import Path
from typing import Any, get_args
from uuid import uuid4

import pytest
import yaml
from pydantic import ValidationError

from src.jd_core.models.parsed_jd import (
    SFUDuty,
    SFUJobDescription,
    SFUQualification,
    SFURelationships,
)
from src.jd_core.models.quality import (
    GateDecision,
    GateOverride,
    GateReason,
    JDGrade,
    JDIssueSeverity,
    JDQualityIssue,
    JDQualityReport,
)
from src.jd_core.quality import (
    GateOverrideError,
    apply_overrides,
    build_report,
    evaluate_gates,
    evaluate_jd_rules,
    score_issues,
)
from src.jd_core.rules import (
    RULE_FILES,
    GatePolicy,
    Rules,
    RulesError,
    Scoring,
    get_rules,
    load_rules,
)

# --- the shipped policy, transcribed (an oracle independent of the YAML) ------

#: gate_id -> (type, source_part, overridable). Hand-transcribed from the policy
#: this task shipped; if gates.yaml drifts, this table is what catches it.
EXPECTED_GATES: dict[str, tuple[str, str, bool]] = {
    # non-overridable: nothing an override could reasonably say
    "SFU-APPROVE-MANDATORY-SECTIONS": ("blocking_rules", "Part 2", False),
    "SFU-APPROVE-NO-PLACEHOLDERS": ("blocking_rules", "Part 2", False),
    # SFU "never approve" conditions — the bar stands, a reviewer may waive it
    # with a written reason
    "SFU-APPROVE-DUTY-ALLOCATION": ("blocking_rules", "Part 11.6", True),
    "SFU-APPROVE-QUAL-MINIMUM": ("blocking_rules", "Part 2H", True),
    "SFU-APPROVE-EDI-FOOTER": ("blocking_rules", "Part 2", True),
    "SFU-APPROVE-SUMMARY-CONDITIONS": ("blocking_rules", "Part 2B", True),
    "SFU-APPROVE-SUMMARY-INCUMBENT": ("blocking_rules", "Part 2B", True),
    "SFU-APPROVE-SUMMARY-LENGTH": ("blocking_rules", "Part 2B", True),
    "SFU-APPROVE-KSA-ORDER": ("blocking_rules", "Part 5.4", True),
    "SFU-APPROVE-QUAL-EQUIVALENT": ("blocking_rules", "Part 2H", True),
    "SFU-APPROVE-SENIOR-TITLE": ("blocking_rules", "Part 3.5", True),
    # roll-up floors
    "SFU-APPROVE-SEVERITY-FLOOR": ("severity_floor", "Part 11.6", True),
    "SFU-APPROVE-SCORE-FLOOR": ("score_floor", "Part 11.6", True),
    "SFU-APPROVE-GRADE-FLOOR": ("grade_floor", "Part 11.6", True),
}

#: The "never approve if this rule fired" set the shipped policy blocks on.
EXPECTED_BLOCKING_RULE_IDS: frozenset[str] = frozenset(
    {
        "SFU-COMP-SUMMARY",
        "SFU-COMP-DUTIES",
        "SFU-COMP-QUALS",
        "SFU-COMP-TERRITORIAL",
        "SFU-COMP-EDI",
        "SFU-STRUCT-PLACEHOLDER",
        "SFU-STRUCT-SUMMARY-TOO-LONG",
        "SFU-GATE-DUTY-PCT",
        "SFU-GATE-KSA-ORDER",
        "SFU-GATE-SENIOR-TITLE",
        "SFU-QUAL-BANNED-PHRASE",
        "SFU-QUAL-EQUIVALENT",
        "SFU-AUTH-SUMMARY-CONDITIONS",
        "SFU-AUTH-SUMMARY-INCUMBENT",
    }
)

#: Deterministic rules the policy deliberately does NOT gate. Every one is named
#: with its reason in gates.yaml's "FOR HR TO DECIDE" block — the point of this
#: table is that the omissions are a *choice on the record*, not an oversight.
EXPECTED_NON_BLOCKING_RULE_IDS: frozenset[str] = frozenset(
    {
        "SFU-LANG-CODED",  # over-fires on boilerplate (tension #4)
        "SFU-AUTH-TITLE-EXEC-DIR",  # unverifiable from the JD alone (tension #5)
        "SFU-AUTH-TITLE-REGISTRAR",
        "SFU-AUTH-TITLE-HR",
        "SFU-STRUCT-SUMMARY-TOO-SHORT",  # not an SFU condition (tension #1)
        "SFU-STRUCT-DUTIES-TOO-FEW",  # authoring judgement (tension #2)
        "SFU-STRUCT-DUTIES-TOO-MANY",
        "SFU-COMP-DECISION",  # incomplete but reviewable — HR to ratify
        "SFU-COMP-PROBLEM",
        "SFU-COMP-RELATIONSHIPS",
        "SFU-COMP-ABOUT",
        "SFU-GATE-REL-HEADER",
        "SFU-STRUCT-ACTION-VERB",  # `low` drafting nudges: they feed the score
        "SFU-STRUCT-HOW-WHY",
        "SFU-QUAL-SKILL-MODIFIER",
        "SFU-QUAL-MODIFIER-VOCAB",
        "SFU-QUAL-DEGREE-DISCIPLINE",
        "SFU-AUTH-ABILITIES-OBSERVABLE",
    }
)


@pytest.fixture(scope="module")
def rules() -> Rules:
    return get_rules()


@pytest.fixture(scope="module")
def policy() -> GatePolicy:
    return get_rules().gates


# --- JD fixtures (the same clean baseline the 2.2 validator suite uses) -------


def _summary(words: int = 120) -> str:
    return " ".join(["word"] * words)


def _duty(verb: str = "Manages", *, how: bool = True) -> SFUDuty:
    return SFUDuty(
        action_verb=verb,
        statement=f"{verb} the program",
        how_why=["by coordinating stakeholders"] if how else [],
    )


_CLEAN_RAW = (
    "Bachelor's degree in Computer Science or other relevant discipline, plus "
    "five years of related experience or an equivalent combination of education, "
    "training and experience. Establishes and maintains relationships and "
    "alliances. The team values collaboration and clear writing."
)


def _clean_quals() -> list[SFUQualification]:
    return [
        SFUQualification(
            text="Bachelor's degree or an equivalent combination of experience",
            kind="education",
        ),
        SFUQualification(
            text="Excellent knowledge of databases",
            kind="knowledge",
            modifier="excellent",
        ),
        SFUQualification(text="Python", kind="skill", modifier="advanced"),
        SFUQualification(text="Ability to work cooperatively", kind="ability"),
    ]


def _quals_with_desired_extras() -> list[SFUQualification]:
    """Qualifications that advertise a DESIRED extra — SFU-QUAL-BANNED-PHRASE's fixture.

    The phrase lives in the QUALIFICATIONS, because that is where SFU bans it and, since
    Phase 2.6, that is where the rule looks (HR-120). Putting it in the raw document was
    what the 2.5 baseline exposed: the whole-document scan drove all 104
    SFU-APPROVE-QUAL-MINIMUM blocks on the current-practice cohort, most of them from
    "assets" / "may include" sitting harmlessly in DUTIES prose.

    Inserted BEFORE the ability, so the JD still runs Knowledge -> Skills -> Abilities
    and this fixture trips one gate rather than also tripping SFU-APPROVE-KSA-ORDER.
    """
    quals = _clean_quals()
    extra = SFUQualification(
        text="Other certifications are assets", kind="skill", modifier="advanced"
    )
    return [*quals[:-1], extra, quals[-1]]


def _clean_jd() -> SFUJobDescription:
    return SFUJobDescription(
        title="Software Developer",
        about_sfu_present=True,
        position_summary=_summary(120),
        duties=[_duty("Manages"), _duty("Coordinates"), _duty("Provides")],
        decision_making=["Approves expenditures up to $5k"],
        problem_solving=["Resolves scheduling conflicts independently"],
        relationships=SFURelationships(
            supervisory="Supervises 2 staff",
            internal=["Finance"],
            external=["Vendors"],
        ),
        qualifications=_clean_quals(),
        territorial_acknowledgement_present=True,
        employment_equity_present=True,
    )


def _jd(**update: object) -> SFUJobDescription:
    return _clean_jd().model_copy(update=update)


#: The whole pipeline a reviewer's screen shows: JD -> issues -> score -> decision.
def _decide(
    jd: SFUJobDescription, raw: str, *, gates: GatePolicy | None = None
) -> GateDecision:
    issues = evaluate_jd_rules(jd, raw)
    score, grade = score_issues(issues)
    return evaluate_gates(issues, score, grade, gates=gates)


def _blocked_ids(decision: GateDecision) -> set[str]:
    return {reason.gate_id for reason in decision.blocking}


def _reason_for(decision: GateDecision, gate_id: str) -> GateReason:
    hits = [r for r in decision.blocking if r.gate_id == gate_id]
    assert hits, f"{gate_id} did not block; blocked: {sorted(_blocked_ids(decision))}"
    return hits[0]


def _issue(severity: JDIssueSeverity, *, rule_id: str | None = None) -> JDQualityIssue:
    return JDQualityIssue(
        category="clarity",
        severity=severity,
        source="llm" if rule_id is None else "rule",
        message="m",
        rule_id=rule_id,
    )


def _scored(score: float) -> tuple[float, JDGrade]:
    """A (score, grade) pair that is internally consistent with the rulebook."""
    return score, get_rules().scoring.grade_for(score)


# --- the shipped policy is well-formed data ----------------------------------


def test_gates_yaml_ships_and_carries_the_rulebook_version(
    rules: Rules, policy: GatePolicy
) -> None:
    assert "gates.yaml" in RULE_FILES
    # the file's DECLARED version; `rules.version` is now that plus a content digest
    # (see test_rules_version.py — the string used to track nothing).
    assert policy.version == rules.declared_version


def test_shipped_gates_match_the_expected_policy(policy: GatePolicy) -> None:
    actual = {
        gate.gate_id: (gate.type, gate.source_part, gate.overridable)
        for gate in policy.gates
    }
    assert actual == EXPECTED_GATES


def test_every_blocking_rule_id_is_catalogued(rules: Rules, policy: GatePolicy) -> None:
    """The loader's cross-reference, asserted from the outside."""
    assert policy.blocking_rule_ids == EXPECTED_BLOCKING_RULE_IDS
    catalogued = set(rules.rule_catalog.by_id)
    assert policy.blocking_rule_ids <= catalogued


def test_every_catalogued_rule_is_gated_or_explicitly_not(
    rules: Rules, policy: GatePolicy
) -> None:
    """No SILENT omissions. Every deterministic rule is either in a blocking set or
    named in the "FOR HR TO DECIDE" list — a rule that is neither means someone
    added a rule and never decided whether it blocks approval."""
    catalogued = set(rules.rule_catalog.by_id)
    accounted = policy.blocking_rule_ids | EXPECTED_NON_BLOCKING_RULE_IDS
    assert catalogued == accounted, sorted(catalogued ^ accounted)
    assert not (policy.blocking_rule_ids & EXPECTED_NON_BLOCKING_RULE_IDS)


def test_severity_and_grade_orders_cover_every_literal(policy: GatePolicy) -> None:
    assert set(policy.severity_order) == set(get_args(JDIssueSeverity))
    assert set(policy.grade_order) == set(get_args(JDGrade))
    assert policy.severity_rank("high") > policy.severity_rank("info")
    assert policy.grade_rank("A") > policy.grade_rank("F")


def test_grade_order_agrees_with_the_scoring_bands(rules: Rules) -> None:
    """A better score must never rank as a worse grade."""
    gates = rules.gates
    ranked = [gates.grade_rank(rules.scoring.grade_for(float(s))) for s in range(101)]
    assert ranked == sorted(ranked)


def test_the_lexicon_is_deliberately_not_a_blocking_gate(policy: GatePolicy) -> None:
    """Policy call (see gates.yaml's header): the coded-term lexicon over-fires on
    ordinary JD boilerplate, so a lexicon hit must not block a JD from *review*.
    It still costs score, and can be promoted to blocking by a YAML edit."""
    assert "SFU-LANG-CODED" not in policy.blocking_rule_ids


# --- no false blocks ---------------------------------------------------------


def test_a_clean_jd_is_permitted() -> None:
    decision = _decide(_clean_jd(), _CLEAN_RAW)
    assert decision.approved is True
    assert decision.blocking == ()
    assert decision.overridden == ()


def test_info_only_issues_are_permitted() -> None:
    """A JD whose only findings are advisory (info) is permitted: info costs no
    score and sits below the severity floor."""
    issues = [_issue("info", rule_id="SFU-AUTH-TITLE-REGISTRAR") for _ in range(5)]
    score, grade = score_issues(issues)
    decision = evaluate_gates(issues, score, grade)
    assert (score, grade) == (100.0, "A")
    assert decision.approved is True


def test_a_noisy_but_reviewable_jd_is_permitted() -> None:
    """Tensions #1/#2/#4/#5: a two-sided summary/duty-count nudge, a coded-term
    lexicon hit and an unparsed-group title advisory must not block review."""
    jd = _jd(
        title="Executive Director, Advancement",
        employee_group=None,
        position_summary=_summary(40),
        duties=[_duty("Manages"), _duty("Coordinates")],
    )
    raw = _CLEAN_RAW + " The team is compassionate and honours every agreement."
    issues = evaluate_jd_rules(jd, raw)
    ids = {i.rule_id for i in issues}
    assert {
        "SFU-STRUCT-SUMMARY-TOO-SHORT",
        "SFU-STRUCT-DUTIES-TOO-FEW",
        "SFU-LANG-CODED",
    } <= ids
    assert _decide(jd, raw).approved is True


def test_evaluate_gates_is_pure_and_repeatable() -> None:
    jd, raw = _jd(duties=[]), _CLEAN_RAW
    assert _decide(jd, raw) == _decide(jd, raw)


# --- fixture pairs: EVERY gate gets one of each (invariant #4) ----------------

# (gate_id, label, issues, score, grade)
GateCase = tuple[str, str, list[JDQualityIssue], float, JDGrade]


def _case(
    jd: SFUJobDescription, raw: str
) -> tuple[list[JDQualityIssue], float, JDGrade]:
    issues = evaluate_jd_rules(jd, raw)
    score, grade = score_issues(issues)
    return issues, score, grade


_FLOOR_SCORE = 60.0  # the shipped score floor; the boundary cases pin it as data


FAILING_GATE_FIXTURES: list[GateCase] = [
    ("SFU-APPROVE-MANDATORY-SECTIONS", "no-duties", *_case(_jd(duties=[]), _CLEAN_RAW)),
    (
        "SFU-APPROVE-MANDATORY-SECTIONS",
        "no-position-summary",
        *_case(_jd(position_summary=None), _CLEAN_RAW),
    ),
    (
        "SFU-APPROVE-MANDATORY-SECTIONS",
        "no-qualifications",
        *_case(_jd(qualifications=[]), _CLEAN_RAW),
    ),
    (
        "SFU-APPROVE-NO-PLACEHOLDERS",
        "leftover-template-text",
        *_case(_clean_jd(), _CLEAN_RAW + " ACTION VERB... WHAT by"),
    ),
    (
        "SFU-APPROVE-DUTY-ALLOCATION",
        "allocations-do-not-total-100",
        *_case(
            _clean_jd(),
            _CLEAN_RAW + " Plans events (60%). Manages the budget (30%).",
        ),
    ),
    (
        "SFU-APPROVE-QUAL-MINIMUM",
        "desired-extras-in-quals",
        *_case(_jd(qualifications=_quals_with_desired_extras()), _CLEAN_RAW),
    ),
    (
        "SFU-APPROVE-EDI-FOOTER",
        "no-territorial-acknowledgement",
        *_case(_jd(territorial_acknowledgement_present=False), _CLEAN_RAW),
    ),
    (
        "SFU-APPROVE-EDI-FOOTER",
        "no-employment-equity-statement",
        *_case(_jd(employment_equity_present=False), _CLEAN_RAW),
    ),
    (
        "SFU-APPROVE-SUMMARY-CONDITIONS",
        "working-conditions-in-the-summary",
        *_case(
            _jd(position_summary=_summary(110) + " Requires on-call weekend parking."),
            _CLEAN_RAW,
        ),
    ),
    (
        "SFU-APPROVE-SUMMARY-INCUMBENT",
        "first-person-summary",
        *_case(
            _jd(position_summary=_summary(110) + " In this role my focus is delivery."),
            _CLEAN_RAW,
        ),
    ),
    (
        "SFU-APPROVE-SUMMARY-LENGTH",
        "summary-over-the-maximum",
        *_case(_jd(position_summary=_summary(200)), _CLEAN_RAW),
    ),
    (
        "SFU-APPROVE-KSA-ORDER",
        "skill-before-knowledge",
        *_case(
            _jd(
                qualifications=[
                    SFUQualification(text="Python", kind="skill", modifier="advanced"),
                    SFUQualification(
                        text="Knowledge of X", kind="knowledge", modifier="working"
                    ),
                    SFUQualification(text="Ability to Y", kind="ability"),
                ]
            ),
            _CLEAN_RAW,
        ),
    ),
    (
        "SFU-APPROVE-QUAL-EQUIVALENT",
        "no-equivalent-combination-path",
        *_case(
            _jd(
                qualifications=[
                    SFUQualification(text="A degree", kind="education"),
                    *_clean_quals()[1:],
                ]
            ),
            "Bachelor's degree in Computer Science or other relevant discipline. "
            "Establishes and maintains relationships and alliances.",
        ),
    ),
    (
        "SFU-APPROVE-SENIOR-TITLE",
        "senior-without-supervisory-scope",
        *_case(
            _jd(title="Senior Developer", relationships=SFURelationships()), _CLEAN_RAW
        ),
    ),
    (
        "SFU-APPROVE-SEVERITY-FLOOR",
        "a-high-severity-llm-finding",
        [_issue("high")],
        *_scored(80.0),
    ),
    (
        "SFU-APPROVE-SCORE-FLOOR",
        "one-below-the-score-floor",
        [_issue("medium")],
        *_scored(_FLOOR_SCORE - 1.0),
    ),
    (
        "SFU-APPROVE-GRADE-FLOOR",
        "one-grade-band-below-the-floor",
        [_issue("medium")],
        *_scored(59.9),  # D — one band below the C floor
    ),
]

PASSING_GATE_FIXTURES: list[GateCase] = [
    ("SFU-APPROVE-MANDATORY-SECTIONS", "clean-jd", *_case(_clean_jd(), _CLEAN_RAW)),
    (
        "SFU-APPROVE-MANDATORY-SECTIONS",
        "a-non-blocking-section-is-still-missing",
        # Decision-making is a *medium* completeness finding: it is deliberately
        # NOT in the blocking set — a reviewer decides, the runner does not.
        *_case(_jd(decision_making=[]), _CLEAN_RAW),
    ),
    ("SFU-APPROVE-NO-PLACEHOLDERS", "clean-jd", *_case(_clean_jd(), _CLEAN_RAW)),
    (
        "SFU-APPROVE-DUTY-ALLOCATION",
        "allocations-total-100",
        *_case(
            _clean_jd(),
            _CLEAN_RAW + " Plans events (60%). Manages the budget (40%).",
        ),
    ),
    (
        "SFU-APPROVE-QUAL-MINIMUM",
        "quals-state-the-minimum",
        *_case(_clean_jd(), _CLEAN_RAW),
    ),
    (
        "SFU-APPROVE-EDI-FOOTER",
        "both-footer-statements-present",
        *_case(_clean_jd(), _CLEAN_RAW),
    ),
    (
        "SFU-APPROVE-SUMMARY-CONDITIONS",
        "summary-states-the-role-not-its-conditions",
        *_case(_clean_jd(), _CLEAN_RAW),
    ),
    (
        "SFU-APPROVE-SUMMARY-INCUMBENT",
        "summary-describes-the-position",
        *_case(_clean_jd(), _CLEAN_RAW),
    ),
    (
        "SFU-APPROVE-SUMMARY-LENGTH",
        "summary-at-the-maximum",
        *_case(_jd(position_summary=_summary(150)), _CLEAN_RAW),
    ),
    (
        # Tension #1 made concrete: SFU names only the MAXIMUM, so an UNDER-long
        # summary trips the advisory rule but must NOT block approval.
        "SFU-APPROVE-SUMMARY-LENGTH",
        "an-under-length-summary-does-not-block",
        *_case(_jd(position_summary=_summary(40)), _CLEAN_RAW),
    ),
    (
        "SFU-APPROVE-KSA-ORDER",
        "knowledge-skills-abilities-in-order",
        *_case(_clean_jd(), _CLEAN_RAW),
    ),
    (
        "SFU-APPROVE-QUAL-EQUIVALENT",
        "equivalent-combination-offered",
        *_case(_clean_jd(), _CLEAN_RAW),
    ),
    (
        "SFU-APPROVE-SENIOR-TITLE",
        "senior-with-supervisory-scope",
        *_case(_jd(title="Senior Developer"), _CLEAN_RAW),
    ),
    (
        "SFU-APPROVE-SEVERITY-FLOOR",
        "one-below-the-severity-floor",
        [_issue("medium"), _issue("low"), _issue("info")],
        *_scored(85.0),
    ),
    (
        "SFU-APPROVE-SCORE-FLOOR",
        "exactly-at-the-score-floor",
        [_issue("medium")],
        *_scored(_FLOOR_SCORE),
    ),
    (
        "SFU-APPROVE-SCORE-FLOOR",
        "one-above-the-score-floor",
        [_issue("medium")],
        *_scored(_FLOOR_SCORE + 1.0),
    ),
    (
        "SFU-APPROVE-GRADE-FLOOR",
        "exactly-at-the-grade-floor",
        [_issue("medium")],
        *_scored(_FLOOR_SCORE),  # C — the floor grade itself
    ),
]


def test_every_gate_has_a_failing_fixture(policy: GatePolicy) -> None:
    """Invariant #4: no gate ships without a JD/state that trips it."""
    covered = {gate_id for gate_id, *_ in FAILING_GATE_FIXTURES}
    expected = {gate.gate_id for gate in policy.gates}
    assert covered == expected, sorted(expected - covered)


def test_every_gate_has_a_passing_fixture(policy: GatePolicy) -> None:
    """Invariant #4: no gate ships without a JD/state it must NOT block."""
    covered = {gate_id for gate_id, *_ in PASSING_GATE_FIXTURES}
    expected = {gate.gate_id for gate in policy.gates}
    assert covered == expected, sorted(expected - covered)


@pytest.mark.parametrize(
    ("gate_id", "issues", "score", "grade"),
    [(g, i, s, gr) for g, _, i, s, gr in FAILING_GATE_FIXTURES],
    ids=[f"{g}::{label}" for g, label, *_ in FAILING_GATE_FIXTURES],
)
def test_failing_fixture_blocks_approval(
    gate_id: str,
    issues: list[JDQualityIssue],
    score: float,
    grade: JDGrade,
    policy: GatePolicy,
) -> None:
    decision = evaluate_gates(issues, score, grade)

    assert decision.approved is False
    reason = _reason_for(decision, gate_id)
    spec = policy.by_id[gate_id]
    assert reason.source_part == spec.source_part
    assert reason.overridable is spec.overridable
    assert reason.reason  # rendered, non-empty (content is rulebook copy, not tone)
    # every rule_id it cites actually fired on this JD
    fired = {i.rule_id for i in issues}
    assert set(reason.rule_ids) <= fired


@pytest.mark.parametrize(
    ("gate_id", "issues", "score", "grade"),
    [(g, i, s, gr) for g, _, i, s, gr in PASSING_GATE_FIXTURES],
    ids=[f"{g}::{label}" for g, label, *_ in PASSING_GATE_FIXTURES],
)
def test_passing_fixture_does_not_trip_its_gate(
    gate_id: str, issues: list[JDQualityIssue], score: float, grade: JDGrade
) -> None:
    assert gate_id not in _blocked_ids(evaluate_gates(issues, score, grade))


# --- blocked decisions explain themselves in rulebook terms ------------------


def test_a_blocking_rule_gate_names_the_offending_rules_and_cites_evidence() -> None:
    decision = _decide(_jd(qualifications=_quals_with_desired_extras()), _CLEAN_RAW)
    reason = _reason_for(decision, "SFU-APPROVE-QUAL-MINIMUM")
    assert reason.rule_ids == ("SFU-QUAL-BANNED-PHRASE",)
    assert reason.evidence  # the verbatim JD span the validator quoted
    assert reason.overridable is True


def test_a_gate_lists_every_offending_rule_it_fired_on() -> None:
    decision = _decide(_jd(position_summary=None, duties=[]), _CLEAN_RAW)
    reason = _reason_for(decision, "SFU-APPROVE-MANDATORY-SECTIONS")
    assert set(reason.rule_ids) == {"SFU-COMP-SUMMARY", "SFU-COMP-DUTIES"}


def test_the_score_floor_reason_carries_no_rule_ids() -> None:
    decision = evaluate_gates([_issue("medium")], *_scored(10.0))
    reason = _reason_for(decision, "SFU-APPROVE-SCORE-FLOOR")
    assert reason.rule_ids == ()
    assert reason.source_part


def test_a_totally_broken_jd_trips_many_gates_at_once() -> None:
    jd = _jd(position_summary=None, duties=[], qualifications=[])
    raw = "ACTION VERB what by. Duties may include travel. Plans (60%). Runs (30%)."
    decision = _decide(jd, raw)
    blocked = _blocked_ids(decision)
    assert decision.approved is False
    assert {
        "SFU-APPROVE-MANDATORY-SECTIONS",
        "SFU-APPROVE-NO-PLACEHOLDERS",
        "SFU-APPROVE-DUTY-ALLOCATION",
        "SFU-APPROVE-SEVERITY-FLOOR",
        "SFU-APPROVE-SCORE-FLOOR",
        "SFU-APPROVE-GRADE-FLOOR",
    } <= blocked

    # ...and NOT on qualifications, because this JD HAS NO QUALIFICATIONS. Since HR-120
    # the banned-phrase rule reads the Qualifications section, so an empty one cannot
    # trip it — the "may include" in this JD's duties prose is exactly the false block
    # the 2.5 baseline caught. Nothing escapes: SFU-COMP-QUALS fires instead, and
    # SFU-APPROVE-MANDATORY-SECTIONS is NON-OVERRIDABLE, so this JD is un-waivably
    # blocked where QUAL-MINIMUM would merely have been waivable.
    assert "SFU-APPROVE-QUAL-MINIMUM" not in blocked
    assert (
        "SFU-APPROVE-MANDATORY-SECTIONS" in get_rules().gates.non_overridable_gate_ids
    )


def test_the_runner_never_raises_on_a_pathological_jd(policy: GatePolicy) -> None:
    """The gate runner is a pure function over JD state: it must NEVER raise (2.2
    shipped a crash exactly like this). Hundreds of findings, and the cited
    rule-id / evidence lists stay bounded by the policy's ``max_listed``."""
    raw = _CLEAN_RAW + " " + " ".join("Does a thing (1%)." for _ in range(200))
    jd = _jd(position_summary=None, duties=[], qualifications=[])
    decision = _decide(jd, raw)
    for reason in decision.blocking:
        assert len(reason.rule_ids) <= policy.max_listed
        assert len(reason.evidence) <= policy.max_listed


@pytest.mark.parametrize("score", [0.0, 0.1, 59.9, 60.0, 99.9, 100.0])
def test_the_runner_never_raises_across_the_whole_score_range(score: float) -> None:
    decision = evaluate_gates([], *_scored(score))
    assert isinstance(decision.approved, bool)


def test_the_score_floor_fails_closed_on_an_uncomparable_score() -> None:
    """``nan < floor`` is False — a naive comparison would let an unscoreable JD
    sail past the floor. An approval bar must never be opened by a value it cannot
    compare. Unreachable from ``score_issues`` today; guarded anyway."""
    decision = evaluate_gates([], math.nan, "F")
    assert decision.approved is False
    assert "SFU-APPROVE-SCORE-FLOOR" in _blocked_ids(decision)


# --- MF-1 regression: the non-overridable placeholder gate actually fires -----


@pytest.mark.parametrize(
    ("raw", "label"),
    [
        ("[insert department] runs the unit.", "bracket-at-position-0"),
        ("Reports to the [insert department] lead.", "bracket-after-a-space"),
        ("Department:\n[insert unit]\n", "bracket-after-a-newline"),
        ("Incumbent: _____", "five-underscores"),
        ("Incumbent: ________________", "sixteen-underscores"),
    ],
)
def test_an_unfinished_draft_cannot_be_approved(raw: str, label: str) -> None:
    """SFU-APPROVE-NO-PLACEHOLDERS is one of only two NON-OVERRIDABLE gates — it is
    the "nothing unfinished gets published" guarantee. hris's ``\\b``-wrapping made
    the two markers a real unfinished draft actually contains (``[insert …`` and a
    run of underscores) impossible to match, so the gate silently never fired: a
    reviewer trusting it would approve a JD reading "[insert department]".
    """
    decision = _decide(_clean_jd(), _CLEAN_RAW + " " + raw)
    assert decision.approved is False, label
    reason = _reason_for(decision, "SFU-APPROVE-NO-PLACEHOLDERS")
    assert reason.rule_ids == ("SFU-STRUCT-PLACEHOLDER",)
    assert reason.overridable is False  # and no override can waive it


# --- CONFIGURABILITY: the decision flips with a YAML edit, not a code edit ----


def _tuned(policy: GatePolicy, mutate: Any) -> GatePolicy:
    """The shipped policy, re-validated after an edit — exactly what a YAML change
    produces, with no code change anywhere."""
    data = policy.model_dump(mode="json")
    mutate(data)
    return GatePolicy.model_validate(data)


def _gate(data: dict[str, Any], gate_id: str) -> dict[str, Any]:
    return next(g for g in data["gates"] if g["gate_id"] == gate_id)


def test_raising_the_score_floor_blocks_a_previously_permitted_jd(
    policy: GatePolicy,
) -> None:
    jd, raw = (
        _jd(duties=[_duty("Manages"), _duty("Leads")]),
        _CLEAN_RAW,
    )  # 1 medium -> 90
    assert _decide(jd, raw).approved is True

    strict = _tuned(
        policy,
        lambda d: _gate(d, "SFU-APPROVE-SCORE-FLOOR").__setitem__("min_score", 95.0),
    )
    decision = _decide(jd, raw, gates=strict)
    assert decision.approved is False
    assert _blocked_ids(decision) == {"SFU-APPROVE-SCORE-FLOOR"}


def test_removing_a_gate_permits_a_previously_blocked_jd(policy: GatePolicy) -> None:
    jd, raw = _jd(qualifications=_quals_with_desired_extras()), _CLEAN_RAW
    assert _blocked_ids(_decide(jd, raw)) == {"SFU-APPROVE-QUAL-MINIMUM"}

    relaxed = _tuned(
        policy,
        lambda d: d.__setitem__(
            "gates",
            [g for g in d["gates"] if g["gate_id"] != "SFU-APPROVE-QUAL-MINIMUM"],
        ),
    )
    assert _decide(jd, raw, gates=relaxed).approved is True


def test_dropping_a_rule_id_from_a_blocking_set_permits_a_previously_blocked_jd(
    policy: GatePolicy,
) -> None:
    """The finest-grained knob: the "never approve if this rule fired" set."""
    jd, raw = _clean_jd(), _CLEAN_RAW + " Plans events (60%). Manages (30%)."
    assert "SFU-APPROVE-DUTY-ALLOCATION" in _blocked_ids(_decide(jd, raw))

    relaxed = _tuned(
        policy,
        lambda d: _gate(d, "SFU-APPROVE-DUTY-ALLOCATION").__setitem__(
            "rule_ids", ["SFU-STRUCT-PLACEHOLDER"]
        ),
    )
    assert _decide(jd, raw, gates=relaxed).approved is True


def test_adding_a_rule_id_to_a_blocking_set_blocks_a_previously_permitted_jd(
    policy: GatePolicy,
) -> None:
    """The other direction, and the answer to the lexicon tension: if HR decides a
    coded term MUST block, that is a one-line YAML edit."""
    jd, raw = _clean_jd(), _CLEAN_RAW + " We want an aggressive self-starter."
    assert _decide(jd, raw).approved is True

    strict = _tuned(
        policy,
        lambda d: _gate(d, "SFU-APPROVE-QUAL-MINIMUM").__setitem__(
            "rule_ids", ["SFU-QUAL-BANNED-PHRASE", "SFU-LANG-CODED"]
        ),
    )
    decision = _decide(jd, raw, gates=strict)
    assert decision.approved is False
    assert _reason_for(decision, "SFU-APPROVE-QUAL-MINIMUM").rule_ids == (
        "SFU-LANG-CODED",
    )


def test_lowering_the_severity_floor_blocks_a_previously_permitted_jd(
    policy: GatePolicy,
) -> None:
    issues = [_issue("low")]
    score, grade = score_issues(issues)
    assert evaluate_gates(issues, score, grade).approved is True

    strict = _tuned(
        policy,
        lambda d: _gate(d, "SFU-APPROVE-SEVERITY-FLOOR").__setitem__(
            "min_severity", "low"
        ),
    )
    decision = evaluate_gates(issues, score, grade, gates=strict)
    assert _blocked_ids(decision) == {"SFU-APPROVE-SEVERITY-FLOOR"}


def test_raising_the_grade_floor_blocks_a_previously_permitted_jd(
    policy: GatePolicy,
) -> None:
    issues = [_issue("medium"), _issue("medium")]
    score, grade = score_issues(issues)  # 100 - (10 + 7) = 83 -> B, above the C floor
    assert grade == "B"
    assert evaluate_gates(issues, score, grade).approved is True

    strict = _tuned(
        policy,
        lambda d: _gate(d, "SFU-APPROVE-GRADE-FLOOR").__setitem__("min_grade", "A"),
    )
    decision = evaluate_gates(issues, score, grade, gates=strict)
    assert _blocked_ids(decision) == {"SFU-APPROVE-GRADE-FLOOR"}


def test_making_a_gate_overridable_is_a_yaml_edit(policy: GatePolicy) -> None:
    jd, raw = _clean_jd(), _CLEAN_RAW + " ACTION VERB... WHAT by"
    assert _reason_for(_decide(jd, raw), "SFU-APPROVE-NO-PLACEHOLDERS").overridable is (
        False
    )

    relaxed = _tuned(
        policy,
        lambda d: _gate(d, "SFU-APPROVE-NO-PLACEHOLDERS").__setitem__(
            "overridable", True
        ),
    )
    decision = _decide(jd, raw, gates=relaxed)
    assert _reason_for(decision, "SFU-APPROVE-NO-PLACEHOLDERS").overridable is True


def test_a_policy_edited_on_disk_changes_the_decision(tmp_path: Path) -> None:
    """The end-to-end configurability proof: edit gates.yaml, load it, decide."""
    _write_valid_rules(tmp_path)
    jd, raw = _jd(duties=[_duty("Manages"), _duty("Leads")]), _CLEAN_RAW

    assert _decide(jd, raw, gates=load_rules(tmp_path).gates).approved is True

    _patch(
        tmp_path,
        "gates.yaml",
        lambda d: _gate(d, "SFU-APPROVE-SCORE-FLOOR").__setitem__("min_score", 95.0),
    )
    tuned = load_rules(tmp_path).gates
    assert _decide(jd, raw, gates=tuned).approved is False


# --- boundaries on every floor ------------------------------------------------


@pytest.mark.parametrize(
    ("score", "blocked"),
    [(59.9, True), (60.0, False), (60.1, False)],
)
def test_score_floor_boundary(score: float, blocked: bool) -> None:
    decision = evaluate_gates([], *_scored(score))
    assert ("SFU-APPROVE-SCORE-FLOOR" in _blocked_ids(decision)) is blocked


@pytest.mark.parametrize(
    ("grade", "blocked"),
    [("F", True), ("D", True), ("C", False), ("B", False), ("A", False)],
)
def test_grade_floor_boundary(grade: JDGrade, blocked: bool) -> None:
    # score held at 100 so ONLY the grade floor can fire
    decision = evaluate_gates([], 100.0, grade)
    assert ("SFU-APPROVE-GRADE-FLOOR" in _blocked_ids(decision)) is blocked


@pytest.mark.parametrize(
    ("severity", "blocked"),
    [("info", False), ("low", False), ("medium", False), ("high", True)],
)
def test_severity_floor_boundary(severity: JDIssueSeverity, blocked: bool) -> None:
    decision = evaluate_gates([_issue(severity)], 100.0, "A")
    assert ("SFU-APPROVE-SEVERITY-FLOOR" in _blocked_ids(decision)) is blocked


# --- overrides: a written reason, or nothing ---------------------------------


def _blocked_on_quals() -> GateDecision:
    return _decide(_jd(qualifications=_quals_with_desired_extras()), _CLEAN_RAW)


@pytest.mark.parametrize("reason", ["", "   ", "\t\n"])
def test_an_unreasoned_override_cannot_even_be_constructed(reason: str) -> None:
    """Invariant #1: an override REQUIRES a written reason. Not 'is checked for' —
    an override without one is unrepresentable."""
    with pytest.raises(ValidationError):
        GateOverride(
            gate_id="SFU-APPROVE-QUAL-MINIMUM", reviewer="hr.reviewer", reason=reason
        )


def test_a_validation_bypassed_override_is_still_refused_at_the_gate() -> None:
    """``model_construct`` skips validation on ANY pydantic model, so the type's
    guarantee is not enough on its own: ``apply_overrides`` is the last checkpoint
    before the Phase-4 audit-log write, and the written reason IS the override
    (CLAUDE.md #1). A blank-reasoned waiver must not flip ``approved`` to True with
    nothing recorded."""
    decision = _blocked_on_quals()
    forged = GateOverride.model_construct(
        gate_id="SFU-APPROVE-QUAL-MINIMUM", reviewer="", reason=""
    )
    with pytest.raises(GateOverrideError, match="written reason"):
        apply_overrides(decision, [forged])

    whitespace = GateOverride.model_construct(
        gate_id="SFU-APPROVE-QUAL-MINIMUM", reviewer="hr", reason="   "
    )
    with pytest.raises(GateOverrideError, match="written reason"):
        apply_overrides(decision, [whitespace])


def test_an_override_requires_a_named_reviewer() -> None:
    with pytest.raises(ValidationError):
        GateOverride(
            gate_id="SFU-APPROVE-QUAL-MINIMUM", reviewer="  ", reason="Verified by HR."
        )


def test_an_overridable_gate_is_waived_by_a_written_reason() -> None:
    decision = _blocked_on_quals()
    assert decision.approved is False

    override = GateOverride(
        gate_id="SFU-APPROVE-QUAL-MINIMUM",
        reviewer="hr.reviewer",
        reason='"capital assets" here is a duty, not a desired qualification.',
    )
    after = apply_overrides(decision, [override])

    assert after.approved is True
    assert after.blocking == ()
    assert [o.gate_id for o in after.overridden] == ["SFU-APPROVE-QUAL-MINIMUM"]
    assert after.overridden[0].reason  # carried through for the Phase-4 audit log


def test_a_non_overridable_gate_cannot_be_overridden_at_all() -> None:
    decision = _decide(_clean_jd(), _CLEAN_RAW + " ACTION VERB... WHAT by")
    override = GateOverride(
        gate_id="SFU-APPROVE-NO-PLACEHOLDERS",
        reviewer="hr.reviewer",
        reason="We are in a hurry.",
    )
    with pytest.raises(GateOverrideError, match="not overridable"):
        apply_overrides(decision, [override])


def test_overriding_a_gate_that_is_not_blocking_is_an_error() -> None:
    decision = _decide(_clean_jd(), _CLEAN_RAW)
    override = GateOverride(
        gate_id="SFU-APPROVE-SCORE-FLOOR", reviewer="hr", reason="Looks fine."
    )
    with pytest.raises(GateOverrideError, match="not blocking"):
        apply_overrides(decision, [override])


def test_overriding_an_unknown_gate_is_an_error() -> None:
    decision = _blocked_on_quals()
    override = GateOverride(gate_id="SFU-NOT-A-GATE", reviewer="hr", reason="Because.")
    with pytest.raises(GateOverrideError):
        apply_overrides(decision, [override])


def test_a_duplicate_override_is_an_error() -> None:
    decision = _blocked_on_quals()
    override = GateOverride(
        gate_id="SFU-APPROVE-QUAL-MINIMUM", reviewer="hr", reason="Checked."
    )
    with pytest.raises(GateOverrideError, match="twice|duplicate"):
        apply_overrides(decision, [override, override])


def test_a_partial_override_still_blocks() -> None:
    jd = _jd(qualifications=_quals_with_desired_extras())
    raw = _CLEAN_RAW + " Plans (60%). Runs (30%)."
    decision = _decide(jd, raw)
    assert {
        "SFU-APPROVE-QUAL-MINIMUM",
        "SFU-APPROVE-DUTY-ALLOCATION",
    } <= _blocked_ids(decision)

    after = apply_overrides(
        decision,
        [
            GateOverride(
                gate_id="SFU-APPROVE-QUAL-MINIMUM",
                reviewer="hr",
                reason="Duty text, not a qualification.",
            )
        ],
    )
    assert after.approved is False
    assert "SFU-APPROVE-DUTY-ALLOCATION" in _blocked_ids(after)
    assert len(after.overridden) == 1


def test_overriding_nothing_leaves_the_decision_untouched() -> None:
    decision = _blocked_on_quals()
    assert apply_overrides(decision, []) == decision


def test_an_approved_decision_with_blockers_is_unrepresentable() -> None:
    reason = GateReason(
        gate_id="SFU-APPROVE-QUAL-MINIMUM",
        source_part="Part 2H",
        reason="blocked",
        rule_ids=("SFU-QUAL-BANNED-PHRASE",),
        overridable=True,
    )
    with pytest.raises(ValidationError):
        GateDecision(approved=True, blocking=(reason,))
    with pytest.raises(ValidationError):
        GateDecision(approved=False, blocking=())


def test_a_decision_is_immutable() -> None:
    decision = _blocked_on_quals()
    with pytest.raises(ValidationError):
        decision.approved = True  # type: ignore[misc]


# --- the assembled report -----------------------------------------------------


def test_build_report_assembles_issues_score_grade_checklist_gates_and_version(
    rules: Rules,
) -> None:
    job_id = uuid4()
    jd, raw = _jd(qualifications=_quals_with_desired_extras()), _CLEAN_RAW
    issues = evaluate_jd_rules(jd, raw)
    generated_at = dt.datetime(2026, 7, 10, tzinfo=dt.UTC)

    report = build_report(
        job_id=job_id,
        issues=issues,
        model="deterministic",
        prompt_version="none",
        generated_at=generated_at,
    )

    assert report.job_id == job_id
    assert report.issues == issues
    assert report.issue_count == len(issues)
    assert (report.overall_score, report.grade) == score_issues(issues)
    assert report.rules_version == rules.version
    assert report.generated_at == generated_at
    # the section-grouped checklist covers every template section
    assert [s.section for s in report.checklist][
        : len(rules.rule_catalog.section_order)
    ] == list(rules.rule_catalog.section_order)
    # ...and the decision the reviewer's approve button obeys
    assert report.gate_decision is not None
    assert report.gate_decision.approved is False
    assert _blocked_ids(report.gate_decision) == {"SFU-APPROVE-QUAL-MINIMUM"}


def test_build_report_of_a_clean_jd_permits_approval() -> None:
    report = build_report(
        job_id=uuid4(),
        issues=evaluate_jd_rules(_clean_jd(), _CLEAN_RAW),
        model="deterministic",
        prompt_version="none",
    )
    assert report.overall_score == 100.0
    assert report.grade == "A"
    assert report.gate_decision is not None
    assert report.gate_decision.approved is True


def test_report_round_trips_through_json() -> None:
    report = build_report(
        job_id=uuid4(),
        issues=evaluate_jd_rules(_jd(duties=[]), _CLEAN_RAW),
        model="deterministic",
        prompt_version="none",
    )
    assert JDQualityReport.model_validate(report.model_dump()) == report


# --- loader validation: a bad policy is a LOAD error, never a bad decision ----


def _write_valid_rules(directory: Path) -> None:
    pkg_dir = Path(__file__).resolve().parents[2] / "src" / "jd_core" / "rules"
    for name in RULE_FILES:
        (directory / name).write_text(
            (pkg_dir / name).read_text(encoding="utf-8"), encoding="utf-8"
        )


def _patch(directory: Path, name: str, mutate: Any) -> None:
    data = yaml.safe_load((directory / name).read_text(encoding="utf-8"))
    mutate(data)
    (directory / name).write_text(yaml.safe_dump(data), encoding="utf-8")


def test_missing_gates_file_raises(tmp_path: Path) -> None:
    _write_valid_rules(tmp_path)
    (tmp_path / "gates.yaml").unlink()
    with pytest.raises(RulesError, match="gates.yaml"):
        load_rules(tmp_path)


def test_malformed_gates_yaml_raises(tmp_path: Path) -> None:
    _write_valid_rules(tmp_path)
    (tmp_path / "gates.yaml").write_text("version: [unclosed\n", encoding="utf-8")
    with pytest.raises(RulesError, match="gates.yaml"):
        load_rules(tmp_path)


def test_a_blocking_rule_id_absent_from_the_catalog_raises(tmp_path: Path) -> None:
    _write_valid_rules(tmp_path)
    _patch(
        tmp_path,
        "gates.yaml",
        lambda d: _gate(d, "SFU-APPROVE-QUAL-MINIMUM").__setitem__(
            "rule_ids", ["SFU-NOT-A-RULE"]
        ),
    )
    with pytest.raises(RulesError, match="rule_catalog"):
        load_rules(tmp_path)


def test_an_unknown_severity_floor_raises(tmp_path: Path) -> None:
    _write_valid_rules(tmp_path)
    _patch(
        tmp_path,
        "gates.yaml",
        lambda d: _gate(d, "SFU-APPROVE-SEVERITY-FLOOR").__setitem__(
            "min_severity", "catastrophic"
        ),
    )
    with pytest.raises(RulesError, match="severity"):
        load_rules(tmp_path)


def test_an_unknown_grade_floor_raises(tmp_path: Path) -> None:
    _write_valid_rules(tmp_path)
    _patch(
        tmp_path,
        "gates.yaml",
        lambda d: _gate(d, "SFU-APPROVE-GRADE-FLOOR").__setitem__("min_grade", "E"),
    )
    with pytest.raises(RulesError, match="grade"):
        load_rules(tmp_path)


def test_an_unknown_gate_type_raises(tmp_path: Path) -> None:
    _write_valid_rules(tmp_path)
    _patch(
        tmp_path,
        "gates.yaml",
        lambda d: _gate(d, "SFU-APPROVE-SCORE-FLOOR").__setitem__("type", "vibes"),
    )
    with pytest.raises(RulesError, match="type"):
        load_rules(tmp_path)


def test_a_duplicate_gate_id_raises(tmp_path: Path) -> None:
    _write_valid_rules(tmp_path)
    _patch(
        tmp_path,
        "gates.yaml",
        lambda d: d["gates"].append(dict(d["gates"][0])),
    )
    with pytest.raises(RulesError, match="duplicate gate_id"):
        load_rules(tmp_path)


def test_an_incomplete_severity_order_raises(tmp_path: Path) -> None:
    _write_valid_rules(tmp_path)
    _patch(
        tmp_path,
        "gates.yaml",
        lambda d: d.__setitem__("severity_order", ["info", "low"]),
    )
    with pytest.raises(RulesError, match="severity_order"):
        load_rules(tmp_path)


def test_an_incomplete_grade_order_raises(tmp_path: Path) -> None:
    _write_valid_rules(tmp_path)
    _patch(tmp_path, "gates.yaml", lambda d: d.__setitem__("grade_order", ["F", "A"]))
    with pytest.raises(RulesError, match="grade_order"):
        load_rules(tmp_path)


def test_a_reason_template_with_an_unknown_placeholder_raises(tmp_path: Path) -> None:
    """A gate whose copy names a placeholder the runner cannot supply is rulebook
    drift: it must fail at LOAD, so the runner itself can never raise mid-decision."""
    _write_valid_rules(tmp_path)
    _patch(
        tmp_path,
        "gates.yaml",
        lambda d: _gate(d, "SFU-APPROVE-SCORE-FLOOR").__setitem__(
            "reason", "Blocked because {nonexistent_placeholder}."
        ),
    )
    with pytest.raises(RulesError, match="placeholder"):
        load_rules(tmp_path)


def test_an_empty_blocking_rule_set_raises(tmp_path: Path) -> None:
    _write_valid_rules(tmp_path)
    _patch(
        tmp_path,
        "gates.yaml",
        lambda d: _gate(d, "SFU-APPROVE-QUAL-MINIMUM").__setitem__("rule_ids", []),
    )
    with pytest.raises(RulesError):
        load_rules(tmp_path)


def test_a_gates_version_mismatch_raises(tmp_path: Path) -> None:
    _write_valid_rules(tmp_path)
    _patch(tmp_path, "gates.yaml", lambda d: d.__setitem__("version", "other_v9"))
    with pytest.raises(RulesError, match="version"):
        load_rules(tmp_path)


def test_the_loaded_policy_is_frozen(policy: GatePolicy) -> None:
    with pytest.raises(ValidationError):
        policy.max_listed = 99  # type: ignore[misc]


# --- the scoring baseline is data too (the last hardcoded constant) -----------


def test_the_score_baseline_is_rulebook_data(rules: Rules) -> None:
    assert rules.scoring.max_score == 100.0
    assert rules.scoring.min_score == 0.0


def test_changing_the_score_baseline_rescales_the_score(rules: Rules) -> None:
    """``100.0`` was the last calibration constant in Python. It is data now: move
    the baseline and every score follows."""
    shipped = rules.scoring
    rescaled = Scoring.model_validate(
        {
            "version": shipped.version,
            "max_score": 50.0,  # a 50-point scale instead of a 100-point one
            "min_score": shipped.min_score,
            "severity_penalty": dict(shipped.severity_penalty),
            "severity_decay": shipped.severity_decay,
            "grade_bands": [
                {"min_score": 45.0, "grade": "A"},
                {"min_score": 20.0, "grade": "D"},
            ],
            "fallback_grade": "F",
        }
    )
    score, grade = score_issues([_issue("medium")], scoring=rescaled)
    assert score == 40.0  # 50 - 10, not 100 - 10
    assert grade == "D"


def test_a_grade_band_above_the_max_score_raises(tmp_path: Path) -> None:
    _write_valid_rules(tmp_path)
    _patch(tmp_path, "scoring.yaml", lambda d: d.__setitem__("max_score", 50.0))
    with pytest.raises(RulesError, match="max_score"):
        load_rules(tmp_path)


def test_an_inverted_score_range_raises(tmp_path: Path) -> None:
    _write_valid_rules(tmp_path)
    _patch(tmp_path, "scoring.yaml", lambda d: d.__setitem__("min_score", 100.0))
    with pytest.raises(RulesError, match="min_score"):
        load_rules(tmp_path)

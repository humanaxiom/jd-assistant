"""Unit tests for the SFU-aligned deterministic JD-quality validators (Phase 2.2).

``evaluate_jd_rules`` is the pure heart of JD Bank: given a JD parsed into the SFU
template (:class:`SFUJobDescription`) plus its raw text, it returns rule-based
issues — same input, same issues, no model call. ``score_issues`` rolls those into
the transparent score (100 minus a severity-weighted penalty with per-severity
diminishing returns).

The suite is the behavioural spec, ported from hris
``tests/unit/test_jd_quality_rules.py`` and extended to CLAUDE.md invariant #4:
**every one of the 27 catalogued rules gets a failing fixture (a JD that trips it)
and a passing fixture (a clean JD that does not).** Assertions are on the
validator post-state — ``rule_id`` + severity + section + evidence presence
(invariant #3) — not on incidental prose; the few message assertions that remain
pin *computed* content (a word count, a percentage total), never tone.

The expected catalog metadata is transcribed in ``sfu_rules_expected`` — an
oracle independent of both the shipped YAML and the validator code.
"""

from __future__ import annotations

import pytest

from src.jd_core.models.parsed_jd import (
    SFUDuty,
    SFUJobDescription,
    SFUQualification,
    SFURelationships,
)
from src.jd_core.models.quality import JDIssueSeverity, JDQualityIssue
from src.jd_core.quality import evaluate_jd_rules, score_issues, section_for_issue
from src.jd_core.rules import Scoring, get_rules
from tests.unit.sfu_rules_expected import (
    EVIDENCE_RULES,
    EXPECTED_CATALOG,
    EXPECTED_DECAY,
    EXPECTED_PENALTY,
)

# --- the clean baseline ------------------------------------------------------


def _summary(words: int = 120) -> str:
    return " ".join(["word"] * words)


def _duty(verb: str = "Manages", *, how: bool = True) -> SFUDuty:
    return SFUDuty(
        action_verb=verb,
        statement=f"{verb} the program",
        how_why=["by coordinating stakeholders"] if how else [],
    )


# A clean raw JD: carries the "equivalent combination" path, a degree naming a
# discipline + "relevant discipline", and the standardized Relationships header;
# no coded terms, banned qualification phrases, or template placeholders.
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


def _ids(issues: list[JDQualityIssue]) -> set[str | None]:
    return {i.rule_id for i in issues}


def _hits(issues: list[JDQualityIssue], rule_id: str) -> list[JDQualityIssue]:
    return [i for i in issues if i.rule_id == rule_id]


# --- no false positives ------------------------------------------------------


def test_clean_jd_has_no_issues_and_scores_100() -> None:
    issues = evaluate_jd_rules(_clean_jd(), _CLEAN_RAW)
    assert issues == [], [(i.rule_id, i.message) for i in issues]
    score, grade = score_issues(issues)
    assert score == 100.0
    assert grade == "A"


@pytest.mark.parametrize("rule_id", sorted(EXPECTED_CATALOG))
def test_clean_jd_is_a_passing_fixture_for_every_rule(rule_id: str) -> None:
    """Passing fixture, per rule: the conformant JD trips none of the 27."""
    assert rule_id not in _ids(evaluate_jd_rules(_clean_jd(), _CLEAN_RAW))


def test_evaluate_is_pure_and_repeatable() -> None:
    jd, raw = _jd(about_sfu_present=False), _CLEAN_RAW
    first = evaluate_jd_rules(jd, raw)
    second = evaluate_jd_rules(jd, raw)
    assert [i.model_dump() for i in first] == [i.model_dump() for i in second]


# --- failing fixtures: one (or more) per catalogued rule ----------------------

# (rule_id, label, jd, raw_text, expected_severity). The severity is transcribed
# from the hris call site — for SFU-LANG-CODED it comes from the coded-term tier,
# for every other rule it is the catalog default.
FailingCase = tuple[str, str, SFUJobDescription, str, JDIssueSeverity]

_NO_HEADER_RAW = (
    "Bachelor's degree in Computer Science or other relevant discipline, plus "
    "five years of related experience or an equivalent combination of education, "
    "training and experience."
)

FAILING_FIXTURES: list[FailingCase] = [
    # --- completeness ---
    ("SFU-COMP-SUMMARY", "no-summary", _jd(position_summary=None), _CLEAN_RAW, "high"),
    ("SFU-COMP-DUTIES", "no-duties", _jd(duties=[]), _CLEAN_RAW, "high"),
    (
        "SFU-COMP-DECISION",
        "no-decision-making",
        _jd(decision_making=[]),
        _CLEAN_RAW,
        "medium",
    ),
    (
        "SFU-COMP-PROBLEM",
        "no-problem-solving",
        _jd(problem_solving=[]),
        _CLEAN_RAW,
        "medium",
    ),
    (
        "SFU-COMP-RELATIONSHIPS",
        "no-relationships",
        _jd(relationships=None),
        _CLEAN_RAW,
        "low",
    ),
    (
        "SFU-COMP-RELATIONSHIPS",
        "empty-relationships",
        _jd(relationships=SFURelationships()),
        _CLEAN_RAW,
        "low",
    ),
    ("SFU-COMP-QUALS", "no-quals", _jd(qualifications=[]), _CLEAN_RAW, "high"),
    ("SFU-COMP-ABOUT", "no-about-sfu", _jd(about_sfu_present=False), _CLEAN_RAW, "low"),
    (
        "SFU-COMP-TERRITORIAL",
        "no-territorial-ack",
        _jd(territorial_acknowledgement_present=False),
        _CLEAN_RAW,
        "low",
    ),
    (
        "SFU-COMP-EDI",
        "no-employment-equity",
        _jd(employment_equity_present=False),
        _CLEAN_RAW,
        "low",
    ),
    # --- structure ---
    (
        "SFU-STRUCT-SUMMARY-LENGTH",
        "summary-too-short",
        _jd(position_summary=_summary(40)),
        _CLEAN_RAW,
        "low",
    ),
    (
        "SFU-STRUCT-SUMMARY-LENGTH",
        "summary-too-long",
        _jd(position_summary=_summary(200)),
        _CLEAN_RAW,
        "low",
    ),
    (
        "SFU-STRUCT-DUTIES-COUNT",
        "too-few-duties",
        _jd(duties=[_duty("Manages"), _duty("Leads")]),
        _CLEAN_RAW,
        "medium",
    ),
    (
        "SFU-STRUCT-DUTIES-COUNT",
        "too-many-duties",
        _jd(duties=[_duty("Manages") for _ in range(6)]),
        _CLEAN_RAW,
        "medium",
    ),
    (
        "SFU-STRUCT-ACTION-VERB",
        "unapproved-verb",
        _jd(duties=[_duty("Synergizes"), _duty("Coordinates"), _duty("Provides")]),
        _CLEAN_RAW,
        "low",
    ),
    (
        "SFU-STRUCT-HOW-WHY",
        "duty-without-how-why",
        _jd(
            duties=[
                _duty("Manages", how=False),
                _duty("Coordinates"),
                _duty("Provides"),
            ]
        ),
        _CLEAN_RAW,
        "low",
    ),
    (
        "SFU-STRUCT-PLACEHOLDER",
        "leftover-template-text",
        _clean_jd(),
        _CLEAN_RAW + " ACTION VERB... WHAT by",
        "medium",
    ),
    # --- qualification standards ---
    (
        "SFU-QUAL-SKILL-MODIFIER",
        "skill-without-modifier",
        _jd(
            qualifications=[
                *_clean_quals()[:2],
                SFUQualification(text="Python", kind="skill", modifier=None),
                _clean_quals()[3],
            ]
        ),
        _CLEAN_RAW,
        "low",
    ),
    (
        "SFU-QUAL-MODIFIER-VOCAB",
        "non-standard-skill-modifier",
        _jd(
            qualifications=[
                *_clean_quals()[:2],
                SFUQualification(text="Excel", kind="skill", modifier="wizard"),
                _clean_quals()[3],
            ]
        ),
        _CLEAN_RAW,
        "low",
    ),
    (
        "SFU-QUAL-MODIFIER-VOCAB",
        "non-standard-knowledge-modifier",
        _jd(
            qualifications=[
                _clean_quals()[0],
                SFUQualification(
                    text="Knowledge of databases", kind="knowledge", modifier="deep"
                ),
                *_clean_quals()[2:],
            ]
        ),
        _CLEAN_RAW,
        "low",
    ),
    (
        "SFU-QUAL-EQUIVALENT",
        "no-equivalent-combination",
        _jd(
            qualifications=[
                SFUQualification(text="A degree", kind="education"),
                *_clean_quals()[1:],
            ]
        ),
        "Bachelor's degree in Computer Science or other relevant discipline. "
        "Establishes and maintains relationships and alliances.",
        "low",
    ),
    (
        "SFU-QUAL-BANNED-PHRASE",
        "assets-in-quals",
        _clean_jd(),
        _CLEAN_RAW + " Other certifications are assets.",
        "medium",
    ),
    (
        "SFU-QUAL-DEGREE-DISCIPLINE",
        "degree-without-discipline",
        _clean_jd(),
        "Master's degree required, or an equivalent combination of education, "
        "training and experience. Establishes and maintains relationships and "
        "alliances.",
        "low",
    ),
    # --- inclusive language ---
    (
        "SFU-LANG-CODED",
        "coded-term-medium",
        _clean_jd(),
        _CLEAN_RAW + " We want an aggressive self-starter.",
        "medium",
    ),
    (
        "SFU-LANG-CODED",
        "coded-term-low",
        _clean_jd(),
        _CLEAN_RAW + " Works with each individual to build trust.",
        "low",
    ),
    # --- quality gates (Part 11.6) ---
    (
        "SFU-GATE-DUTY-PCT",
        "allocations-do-not-total-100",
        _clean_jd(),
        _CLEAN_RAW + " Plans events (60%). Manages the budget (30%).",
        "medium",
    ),
    (  # one below the rounding tolerance's lower bound (99)
        "SFU-GATE-DUTY-PCT",
        "allocations-total-98-below-tolerance",
        _clean_jd(),
        _CLEAN_RAW + " Plans events (60%). Manages the budget (38%).",
        "medium",
    ),
    (  # one above the rounding tolerance's upper bound (101)
        "SFU-GATE-DUTY-PCT",
        "allocations-total-102-above-tolerance",
        _clean_jd(),
        _CLEAN_RAW + " Plans events (60%). Manages the budget (42%).",
        "medium",
    ),
    (
        "SFU-GATE-KSA-ORDER",
        "skill-before-knowledge",
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
        "low",
    ),
    (
        "SFU-GATE-SENIOR-TITLE",
        "senior-without-supervisory",
        _jd(title="Senior Developer", relationships=SFURelationships()),
        _CLEAN_RAW,
        "low",
    ),
    (
        "SFU-GATE-REL-HEADER",
        "missing-relationships-header",
        _clean_jd(),
        _NO_HEADER_RAW,
        "low",
    ),
    # --- authoring gates (Parts 2-3) ---
    (
        "SFU-AUTH-SUMMARY-CONDITIONS",
        "working-conditions-in-summary",
        _jd(position_summary=_summary(110) + " Requires on-call and weekend parking."),
        _CLEAN_RAW,
        "medium",
    ),
    (
        "SFU-AUTH-SUMMARY-INCUMBENT",
        "first-person-summary",
        _jd(position_summary=_summary(110) + " In this role my focus is delivery."),
        _CLEAN_RAW,
        "low",
    ),
    (
        "SFU-AUTH-ABILITIES-OBSERVABLE",
        "ability-not-observable",
        _jd(
            qualifications=[
                *_clean_quals()[:3],
                SFUQualification(text="Strong team player", kind="ability"),
            ]
        ),
        _CLEAN_RAW,
        "low",
    ),
    (
        "SFU-AUTH-TITLE-EXEC-DIR",
        "exec-director-outside-apex",
        _jd(title="Executive Director, Advancement", employee_group="apsa"),
        _CLEAN_RAW,
        "low",
    ),
    (
        "SFU-AUTH-TITLE-REGISTRAR",
        "registrar-title",
        _jd(title="Associate Registrar"),
        _CLEAN_RAW,
        "info",
    ),
    (
        "SFU-AUTH-TITLE-HR",
        "human-resources-title",
        _jd(title="Human Resources Assistant"),
        _CLEAN_RAW,
        "info",
    ),
]


def test_every_catalogued_rule_has_a_failing_fixture() -> None:
    """Invariant #4: no rule ships without a fixture that trips it."""
    covered = {rule_id for rule_id, *_ in FAILING_FIXTURES}
    assert covered == set(EXPECTED_CATALOG), sorted(set(EXPECTED_CATALOG) - covered)


@pytest.mark.parametrize(
    ("rule_id", "jd", "raw", "severity"),
    [(r, jd, raw, sev) for r, _, jd, raw, sev in FAILING_FIXTURES],
    ids=[f"{r}::{label}" for r, label, *_ in FAILING_FIXTURES],
)
def test_failing_fixture_trips_its_rule(
    rule_id: str, jd: SFUJobDescription, raw: str, severity: JDIssueSeverity
) -> None:
    issues = evaluate_jd_rules(jd, raw)
    hits = _hits(issues, rule_id)
    assert hits, f"{rule_id} not raised; got {sorted(str(i) for i in _ids(issues))}"

    expected = EXPECTED_CATALOG[rule_id]
    for issue in hits:
        assert issue.source == "rule"
        assert issue.severity == severity
        assert issue.category == expected.category
        assert section_for_issue(issue) == expected.section
        assert issue.message
        assert issue.suggestion, f"{rule_id} must carry a recommendation"
        if rule_id in EVIDENCE_RULES:
            assert issue.evidence, f"{rule_id} must cite evidence"


# --- passing fixtures: near-miss JDs that must NOT trip a rule ---------------

PassingCase = tuple[str, str, SFUJobDescription, str]

PASSING_FIXTURES: list[PassingCase] = [
    (
        "SFU-STRUCT-DUTIES-COUNT",
        "exactly-three-duties",
        _jd(duties=[_duty("Manages"), _duty("Leads"), _duty("Provides")]),
        _CLEAN_RAW,
    ),
    (
        "SFU-STRUCT-DUTIES-COUNT",
        "exactly-five-duties",
        _jd(duties=[_duty("Manages") for _ in range(5)]),
        _CLEAN_RAW,
    ),
    (
        "SFU-STRUCT-SUMMARY-LENGTH",
        "summary-at-lower-bound",
        _jd(position_summary=_summary(100)),
        _CLEAN_RAW,
    ),
    (
        "SFU-STRUCT-SUMMARY-LENGTH",
        "summary-at-upper-bound",
        _jd(position_summary=_summary(150)),
        _CLEAN_RAW,
    ),
    (
        "SFU-LANG-CODED",
        "coded-term-only-inside-a-longer-word",
        _clean_jd(),
        _CLEAN_RAW + " The market is uncompetitiveness aside.",
    ),
    (
        "SFU-GATE-DUTY-PCT",
        "allocations-total-100",
        _clean_jd(),
        _CLEAN_RAW + " Plans events (60%). Manages the budget (40%).",
    ),
    (  # the rounding tolerance's lower bound (99) is INSIDE the window
        "SFU-GATE-DUTY-PCT",
        "allocations-total-99-at-tolerance",
        _clean_jd(),
        _CLEAN_RAW + " Plans events (60%). Manages the budget (39%).",
    ),
    (  # ...as is its upper bound (101)
        "SFU-GATE-DUTY-PCT",
        "allocations-total-101-at-tolerance",
        _clean_jd(),
        _CLEAN_RAW + " Plans events (60%). Manages the budget (41%).",
    ),
    (
        "SFU-GATE-DUTY-PCT",
        "single-allocation-is-not-a-total",
        _clean_jd(),
        _CLEAN_RAW + " Plans events (60%).",
    ),
    (
        # A zero-duty JD is a COMPLETENESS failure (SFU-COMP-DUTIES), not a count
        # failure: the `0 < n` guard stops it being reported twice ("no duties
        # listed" AND "only 0 main duties").
        "SFU-STRUCT-DUTIES-COUNT",
        "zero-duties-is-completeness-not-count",
        _jd(duties=[]),
        _CLEAN_RAW,
    ),
    (
        "SFU-GATE-SENIOR-TITLE",
        "senior-with-supervisory-scope",
        _jd(title="Senior Developer"),
        _CLEAN_RAW,
    ),
    (
        "SFU-AUTH-TITLE-EXEC-DIR",
        "exec-director-in-apex",
        _jd(title="Executive Director, Advancement", employee_group="apex"),
        _CLEAN_RAW,
    ),
    (
        "SFU-AUTH-TITLE-EXEC-DIR",
        "exec-director-with-unknown-group",
        _jd(title="Executive Director, Advancement", employee_group=None),
        _CLEAN_RAW,
    ),
    (
        "SFU-AUTH-ABILITIES-OBSERVABLE",
        "able-to-prefix-is-observable",
        _jd(
            qualifications=[
                *_clean_quals()[:3],
                SFUQualification(text="Able to lead a team", kind="ability"),
            ]
        ),
        _CLEAN_RAW,
    ),
    (
        "SFU-QUAL-EQUIVALENT",
        "equivalent-combination-only-in-the-qualifications",
        _clean_jd(),
        _NO_HEADER_RAW.replace(
            "or an equivalent combination of education, training and experience", ""
        )
        + " Establishes and maintains relationships and alliances.",
    ),
]


@pytest.mark.parametrize(
    ("rule_id", "jd", "raw"),
    [(r, jd, raw) for r, _, jd, raw in PASSING_FIXTURES],
    ids=[f"{r}::{label}" for r, label, *_ in PASSING_FIXTURES],
)
def test_passing_fixture_does_not_trip_its_rule(
    rule_id: str, jd: SFUJobDescription, raw: str
) -> None:
    assert rule_id not in _ids(evaluate_jd_rules(jd, raw))


# --- computed message/evidence content (not tone) ----------------------------


def test_summary_length_message_reports_the_count_and_the_template_range() -> None:
    issues = _hits(
        evaluate_jd_rules(_jd(position_summary=_summary(40)), _CLEAN_RAW),
        "SFU-STRUCT-SUMMARY-LENGTH",
    )
    assert "40" in issues[0].message
    assert "100-150" in issues[0].message


def test_duties_count_message_reports_the_template_range() -> None:
    issues = _hits(
        evaluate_jd_rules(_jd(duties=[_duty("Manages")]), _CLEAN_RAW),
        "SFU-STRUCT-DUTIES-COUNT",
    )
    assert "3-5" in issues[0].message


def test_duty_allocation_message_and_evidence_report_the_total() -> None:
    raw = _CLEAN_RAW + " Plans events (60%). Manages the budget (30%)."
    issues = _hits(evaluate_jd_rules(_clean_jd(), raw), "SFU-GATE-DUTY-PCT")
    assert len(issues) == 1
    assert "90%" in issues[0].message
    assert issues[0].evidence == "60% + 30%"


def test_zero_duties_is_reported_once_as_completeness_not_twice() -> None:
    """The `0 < n` guard: a JD with no duties is a missing SECTION, not a JD with
    'only 0 main duties'. Regression for a double-reported finding."""
    ids = _ids(evaluate_jd_rules(_jd(duties=[]), _CLEAN_RAW))
    assert "SFU-COMP-DUTIES" in ids
    assert "SFU-STRUCT-DUTIES-COUNT" not in ids


def test_a_document_with_hundreds_of_allocations_does_not_crash_the_validator() -> None:
    """Regression (deviation from hris): hris joins EVERY parsed allocation into
    the evidence, which blows ``JDQualityIssue.evidence``'s 500-char cap and makes
    the validator raise a pydantic ValidationError. A table-heavy or badly
    extracted archive document does exactly this — and the validator is a pure
    function that must never raise on JD text. The evidence is a bounded sample,
    capped by the rulebook's ``thresholds.max_listed``; the reported *total* still
    counts every allocation.
    """
    max_listed = get_rules().thresholds.max_listed
    raw = _CLEAN_RAW + " " + " ".join("Does a thing (1%)." for _ in range(200))

    issues = _hits(evaluate_jd_rules(_clean_jd(), raw), "SFU-GATE-DUTY-PCT")

    assert len(issues) == 1
    evidence = issues[0].evidence or ""
    assert len(evidence) <= 500  # the JDQualityIssue cap that hris breached
    assert evidence.endswith("…")  # truncation is marked, not silent
    assert evidence.count("%") == max_listed
    assert "200%" in issues[0].message  # the TOTAL still sums all 200


def test_action_verb_finding_names_the_offending_verbs() -> None:
    jd = _jd(duties=[_duty("Synergizes"), _duty("Ideates"), _duty("Provides")])
    issues = _hits(evaluate_jd_rules(jd, _CLEAN_RAW), "SFU-STRUCT-ACTION-VERB")
    assert len(issues) == 1
    assert "synergizes" in issues[0].message
    assert "ideates" in issues[0].message


def test_action_verb_finding_caps_how_many_verbs_it_names() -> None:
    max_listed = get_rules().thresholds.max_listed
    verbs = ["Alpha", "Bravo", "Charlie", "Delta", "Echo", "Foxtrot", "Golf"]
    jd = _jd(duties=[_duty(v) for v in verbs])
    issues = _hits(evaluate_jd_rules(jd, _CLEAN_RAW), "SFU-STRUCT-ACTION-VERB")
    named = [v for v in verbs if v.lower() in issues[0].message]
    assert len(named) == max_listed < len(verbs)


def test_leading_verb_falls_back_to_the_statement_when_action_verb_is_blank() -> None:
    jd = _jd(
        duties=[
            SFUDuty(action_verb="", statement="Synergizes the team", how_why=["by x"]),
            _duty("Coordinates"),
            _duty("Provides"),
        ]
    )
    assert "SFU-STRUCT-ACTION-VERB" in _ids(evaluate_jd_rules(jd, _CLEAN_RAW))


def test_leading_verb_ignores_trailing_punctuation() -> None:
    punctuated = SFUDuty(
        action_verb="Manages,", statement="Manages, the team", how_why=["x"]
    )
    jd = _jd(duties=[punctuated, _duty("Coordinates"), _duty("Provides")])
    assert "SFU-STRUCT-ACTION-VERB" not in _ids(evaluate_jd_rules(jd, _CLEAN_RAW))


def test_placeholder_reports_at_most_one_finding() -> None:
    raw = _CLEAN_RAW + " ACTION VERB ... how and why ... [insert department]"
    issues = _hits(evaluate_jd_rules(_clean_jd(), raw), "SFU-STRUCT-PLACEHOLDER")
    assert len(issues) == 1


def test_banned_phrase_reports_one_finding_per_phrase() -> None:
    raw = _CLEAN_RAW + " Duties may include travel. Certifications are assets."
    issues = _hits(evaluate_jd_rules(_clean_jd(), raw), "SFU-QUAL-BANNED-PHRASE")
    assert len(issues) == 2
    evidence = " ".join(i.evidence or "" for i in issues)
    assert "may include" in evidence
    assert "assets" in evidence


def test_coded_terms_report_one_finding_per_term_with_evidence() -> None:
    raw = _CLEAN_RAW + " We want an aggressive, ambitious self-starter."
    issues = _hits(evaluate_jd_rules(_clean_jd(), raw), "SFU-LANG-CODED")
    assert len(issues) == 2  # aggressive + ambitious
    assert all(i.evidence for i in issues)
    assert all(i.severity == "medium" for i in issues)


def test_gendered_occupational_nouns_are_medium() -> None:
    raw = _CLEAN_RAW + " Acts as spokesman and salesman, coordinating manpower."
    issues = _hits(evaluate_jd_rules(_clean_jd(), raw), "SFU-LANG-CODED")
    assert len(issues) == 3
    assert {i.severity for i in issues} == {"medium"}


def test_generic_pronouns_are_low() -> None:
    raw = _CLEAN_RAW + " The incumbent uses his/her judgement; s/he decides."
    issues = _hits(evaluate_jd_rules(_clean_jd(), raw), "SFU-LANG-CODED")
    assert len(issues) == 2
    assert {i.severity for i in issues} == {"low"}


def test_evidence_snippet_is_windowed_around_the_match() -> None:
    window = get_rules().thresholds.evidence_context_window
    raw = _CLEAN_RAW + " We want an aggressive self-starter."
    issue = _hits(evaluate_jd_rules(_clean_jd(), raw), "SFU-LANG-CODED")[0]
    evidence = issue.evidence or ""
    assert "aggressive" in evidence
    assert evidence.startswith("…")  # truncated on the left
    assert len(evidence) <= 2 * window + len("aggressive") + 2


# --- scoring -----------------------------------------------------------------


def _issues(severity: JDIssueSeverity, n: int) -> list[JDQualityIssue]:
    return [
        JDQualityIssue(
            category="structure", severity=severity, source="rule", message="m"
        )
        for _ in range(n)
    ]


def test_first_of_each_severity_is_full_weight() -> None:
    # Diminishing returns only kicks in on REPEATS: a single finding per severity
    # still costs the full base penalty (the worst issues count fully).
    score, grade = score_issues(_issues("high", 1) + _issues("low", 1))
    assert score == 100.0 - EXPECTED_PENALTY["high"] - EXPECTED_PENALTY["low"]
    assert grade == "B"


def test_info_severity_costs_nothing() -> None:
    score, grade = score_issues(_issues("info", 10))
    assert score == 100.0
    assert grade == "A"


def test_repeated_severity_diminishes() -> None:
    # 6 medium findings cost the geometric sum, not 6 * 10 = 60.
    score, _ = score_issues(_issues("medium", 6))
    base = EXPECTED_PENALTY["medium"]
    expected = base * (1 - EXPECTED_DECAY**6) / (1 - EXPECTED_DECAY)
    assert score == pytest.approx(100.0 - expected)
    assert expected < 6 * base  # strictly dampened


def test_pile_of_low_findings_cannot_force_f0() -> None:
    # A wall of minor (low) nudges is bounded (the tier caps at
    # base / (1 - decay) = 5 / 0.3 ≈ 16.7), so it cannot sink a JD to F alone.
    score, grade = score_issues(_issues("low", 30))
    assert score > 80.0
    assert grade in ("A", "B")


def test_high_severity_still_drives_a_low_grade() -> None:
    _, grade = score_issues(_issues("high", 5))
    assert grade in ("D", "F")


def test_score_floors_at_zero_for_a_saturating_pile() -> None:
    issues = _issues("high", 20) + _issues("medium", 20) + _issues("low", 20)
    score, grade = score_issues(issues)
    assert score == 0.0
    assert grade == "F"


def test_grade_boundaries_come_from_the_rulebook_bands() -> None:
    # One medium finding: 100 - 10 = 90 -> the A band's lower cutoff.
    assert score_issues(_issues("medium", 1)) == (90.0, "A")
    # Two high findings: 100 - (20 + 14) = 66 -> C.
    score, grade = score_issues(_issues("high", 2))
    assert score == pytest.approx(66.0)
    assert grade == "C"


def test_scoring_calibration_is_overridable() -> None:
    """The scoring table is data: hand the scorer a different one and it obeys."""
    tuned = Scoring.model_validate(
        {
            "version": get_rules().version,
            "severity_penalty": {
                "high": 20.0,
                "medium": 30.0,
                "low": 5.0,
                "info": 0.0,
            },
            "severity_decay": 0.7,
            "grade_bands": [
                {"min_score": 80.0, "grade": "A"},
                {"min_score": 60.0, "grade": "B"},
                {"min_score": 40.0, "grade": "C"},
                {"min_score": 20.0, "grade": "D"},
            ],
            "fallback_grade": "F",
        }
    )
    score, grade = score_issues(_issues("medium", 1), scoring=tuned)
    assert score == pytest.approx(70.0)
    assert grade == "B"


def test_decay_of_one_turns_diminishing_returns_off() -> None:
    shipped = get_rules().scoring
    linear = Scoring.model_validate(
        {
            "version": shipped.version,
            "severity_penalty": dict(shipped.severity_penalty),
            "severity_decay": 1.0,
            "grade_bands": [
                {"min_score": b.min_score, "grade": b.grade}
                for b in shipped.grade_bands
            ],
            "fallback_grade": shipped.fallback_grade,
        }
    )
    score, _ = score_issues(_issues("medium", 3), scoring=linear)
    assert score == pytest.approx(70.0)  # 3 x 10, no decay

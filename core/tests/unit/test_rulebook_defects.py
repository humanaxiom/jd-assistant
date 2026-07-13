"""Phase 2.6 — the three OUR-SIDE defects the archive baseline exposed.

The 2.5 baseline (``docs/baseline/``) put the approval bar on trial against all 14,565
archive files. It survived — but it also showed that three of the things it was
measuring were **our bugs, not SFU's JDs**. All three move the numbers HR would be
ratifying, so all three are fixed and re-baselined *before* HR is asked anything, and
each lands as a registered decision with the measured before/after — never a quiet
patch (CLAUDE.md standing rule).

This suite is the behavioural spec of the three fixes. Every pin here is **behavioural**
— the mutation bar (HANDOFF): change the shipped YAML *and* update the register so the
drift alarm goes silent, and a test in here must still go red.

1. ``SFU-QUAL-BANNED-PHRASE`` scanned the WHOLE document (HR-041 / HR-120). Its own
   catalog text says the Toolkit bans these phrases *from Qualifications*, so
   `"Responsibilities may include arranging catering…"` in **duties** prose tripped a
   Qualifications gate. Measured: this one rule drove **all 104**
   ``SFU-APPROVE-QUAL-MINIMUM`` blocks on the current-practice cohort — the #2 operative
   gate in the whole approval bar. The scope is now rulebook data
   (``qualifications.banned_phrase_scope``), and it ships scoped to Qualifications.

2. ``SFU-STRUCT-HOW-WHY`` was UNFALSIFIABLE (HR-119 / HR-121). ``segmenter.py`` never
   populates ``SFUDuty.how_why`` — "left empty", by construction — so
   ``not d.how_why`` was true for every duty of every JD. It fired on **628 of the 628
   JDs we would approve (100%)**: a constant subtracted from every score, with zero
   discriminating power. The rule is now catalogued but **not evaluable**
   (``rule_catalog.SFU-STRUCT-HOW-WHY.evaluable: false``): the deterministic engine does
   not raise it, and reinstating it when an extractor populates the field is a one-line
   YAML flip with no code change.

3. The era model conflated TWO rollouts (HR-109/110/111 / HR-122). The JDFN *template*
   landed in 2019; the territorial/EDI *footer* only crossed 50% adoption in **2024**.
   Classing everything from 2019 as ``new`` and then judging it with a blocking gate
   only 2024+ JDs satisfy produced a 7x artefact (10.0% vs 71.9%). There is now a
   fourth era, ``current`` (2024+), keyed on ``segmentation.era_new_max_year``.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

import pytest
import yaml

from src.jd_bank.baseline.facets import file_facets
from src.jd_core.models.parsed_jd import (
    SFUDuty,
    SFUJobDescription,
    SFUQualification,
    SFURelationships,
)
from src.jd_core.models.quality import JDQualityIssue
from src.jd_core.quality import evaluate_gates, evaluate_jd_rules, score_issues
from src.jd_core.rules import (
    RULE_FILES,
    Qualifications,
    RuleCatalog,
    Rules,
    RulesError,
    Segmentation,
    check_register,
    decision_surface,
    get_rules,
    live_value,
    load_rules,
)

_PKG_DIR = Path(__file__).resolve().parents[2] / "src" / "jd_core" / "rules"


@pytest.fixture
def rules() -> Rules:
    return get_rules()


# --- fixtures: a JD that produces no findings at all --------------------------


def _raw(*extra: str) -> str:
    """A clean JD body — the equivalency path, a related discipline, the standardized
    Relationships header — plus whatever the test adds to it."""
    body = (
        "Bachelor's degree in Computer Science or other relevant discipline, plus "
        "five years of related experience or an equivalent combination of education, "
        "training and experience. Establishes and maintains relationships and "
        "alliances. The team values collaboration and clear writing."
    )
    return " ".join((body, *extra))


def _quals(*extra: SFUQualification) -> list[SFUQualification]:
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
        *extra,
        SFUQualification(text="Ability to work cooperatively", kind="ability"),
    ]


def _jd(**update: Any) -> SFUJobDescription:
    """A JD that, against :func:`_raw`, produces exactly zero findings."""
    duties = [
        SFUDuty(
            action_verb=verb,
            statement=f"{verb} the program",
            how_why=["by coordinating stakeholders"],
        )
        for verb in ("Manages", "Coordinates", "Provides")
    ]
    fields: dict[str, Any] = {
        "title": "Software Developer",
        "about_sfu_present": True,
        "position_summary": " ".join(["word"] * 120),
        "duties": duties,
        "decision_making": ["Approves expenditures up to $5k"],
        "problem_solving": ["Resolves scheduling conflicts independently"],
        "relationships": SFURelationships(
            supervisory="Supervises 2 staff",
            internal=["Finance"],
            external=["Vendors"],
        ),
        "qualifications": _quals(),
        "territorial_acknowledgement_present": True,
        "employment_equity_present": True,
    }
    return SFUJobDescription(**{**fields, **update})


def _ids(issues: list[JDQualityIssue]) -> set[str]:
    return {issue.rule_id for issue in issues if issue.rule_id}


def _retuned(base: Rules, name: str, **fields: Any) -> Rules:
    """``base`` with one rule FILE re-validated from the shipped YAML, ``fields``
    overridden — the mutation bar's "what if HR moved it" fixture.

    Built from the real file and run through the real model, so a retuning the rulebook
    would reject fails here exactly as it would at load.
    """
    models: dict[str, type[Qualifications] | type[RuleCatalog] | type[Segmentation]] = {
        "qualifications": Qualifications,
        "rule_catalog": RuleCatalog,
        "segmentation": Segmentation,
    }
    raw: dict[str, Any] = yaml.safe_load(
        (_PKG_DIR / f"{name}.yaml").read_text(encoding="utf-8")
    )
    return base.model_copy(
        update={name: models[name].model_validate({**raw, **fields})}
    )


def _write_rules(directory: Path) -> None:
    for name in RULE_FILES:
        (directory / name).write_text(
            (_PKG_DIR / name).read_text(encoding="utf-8"), encoding="utf-8"
        )


def _patch(directory: Path, name: str, mutate: Any) -> None:
    data = yaml.safe_load((directory / name).read_text(encoding="utf-8"))
    mutate(data)
    (directory / name).write_text(yaml.safe_dump(data), encoding="utf-8")


# =============================================================================
# DEFECT 1 — SFU-QUAL-BANNED-PHRASE scanned the whole document (HR-041 / HR-120)
# =============================================================================

_BANNED_IN_DUTIES = "Responsibilities may include arranging catering and events."
_BANNED_IN_QUALS = SFUQualification(
    text="Professional certifications are assets", kind="skill", modifier="advanced"
)


def test_a_banned_phrase_in_duties_prose_no_longer_raises_a_qualifications_finding(
    rules: Rules,
) -> None:
    """THE BUG, and the #2 operative gate in the approval bar.

    The rule's own catalog text: "phrases the Toolkit bans from **Qualifications**".
    It scanned the whole raw document, so a duty that merely mentions "capital assets"
    or "responsibilities may include…" raised a QUALIFICATIONS finding and blocked
    approval through ``SFU-APPROVE-QUAL-MINIMUM``.
    """
    issues = evaluate_jd_rules(_jd(), _raw(_BANNED_IN_DUTIES), rules=rules)
    assert "SFU-QUAL-BANNED-PHRASE" not in _ids(issues)


def test_a_banned_phrase_in_the_qualifications_still_raises_the_finding(
    rules: Rules,
) -> None:
    """...and narrowing the scope must not blind the rule where it belongs."""
    jd = _jd(qualifications=_quals(_BANNED_IN_QUALS))
    issues = evaluate_jd_rules(jd, _raw(), rules=rules)
    hits = [i for i in issues if i.rule_id == "SFU-QUAL-BANNED-PHRASE"]

    assert len(hits) == 1
    assert hits[0].evidence  # it still quotes the JD's own words
    assert "assets" in (hits[0].evidence or "")


def test_the_banned_phrase_scan_scope_is_rulebook_data_not_a_code_decision(
    rules: Rules,
) -> None:
    """The mutation bar. The scope is the decision (HR-120), so it is a YAML key: set it
    back to ``document`` — with the register updated in step, so the drift alarm is
    silent — and the whole-document behaviour comes straight back. A validator that had
    the scope hardcoded would pass every other test in this file and fail this one."""
    whole_document = _retuned(rules, "qualifications", banned_phrase_scope="document")

    issues = evaluate_jd_rules(_jd(), _raw(_BANNED_IN_DUTIES), rules=whole_document)

    assert "SFU-QUAL-BANNED-PHRASE" in _ids(issues)


def test_a_jd_with_no_parseable_qualifications_still_cannot_be_approved(
    rules: Rules,
) -> None:
    """The failure mode a section-scoped rule invites — and why it does not exist here.

    Scope the scan to a section and the section can be MISSING: no Qualifications parsed
    -> nothing to scan -> ``SFU-QUAL-BANNED-PHRASE`` can never fire -> the JD sails
    through ``SFU-APPROVE-QUAL-MINIMUM``. "A gate that cannot fire is a false safety
    guarantee" is this rulebook's standing rule (the Phase-2.3 reviewer's finding), so
    the escape has to be closed by something.

    It is: a JD with no qualifications trips ``SFU-COMP-QUALS``, which is a member of
    ``SFU-APPROVE-MANDATORY-SECTIONS`` — and that gate is **non-overridable**. So such a
    JD is not merely blocked, it is un-waivably blocked, which is strictly HARDER than
    the overridable QUAL-MINIMUM gate it escapes. Nothing gets through.
    """
    jd = _jd(qualifications=[])
    issues = evaluate_jd_rules(jd, _raw(_BANNED_IN_DUTIES), rules=rules)
    score, grade = score_issues(issues, scoring=rules.scoring)
    decision = evaluate_gates(issues, score, grade, gates=rules.gates)

    assert "SFU-QUAL-BANNED-PHRASE" not in _ids(issues)  # it genuinely cannot fire
    assert "SFU-COMP-QUALS" in _ids(issues)
    assert decision.approved is False
    blocked = {reason.gate_id for reason in decision.blocking}
    assert "SFU-APPROVE-QUAL-MINIMUM" not in blocked
    assert "SFU-APPROVE-MANDATORY-SECTIONS" in blocked
    assert "SFU-APPROVE-MANDATORY-SECTIONS" in rules.gates.non_overridable_gate_ids


def test_the_equivalency_path_is_still_accepted_anywhere_in_the_document(
    rules: Rules,
) -> None:
    """A deliberate asymmetry, not an oversight.

    ``SFU-QUAL-EQUIVALENT`` checks the whole document *or* the qualifications, and stays
    that way: it is a LENIENT check (finding the equivalency path anywhere means the JD
    has it), and leniency in a blocking gate errs toward letting a human look at the JD.
    ``SFU-QUAL-BANNED-PHRASE`` is the opposite — a whole-document scan there is a
    *stricter* bar than the rule says, and it blocks. Scope narrows the punitive rule;
    it does not narrow the forgiving one.
    """
    jd = _jd(qualifications=[SFUQualification(text="A degree", kind="education")])
    issues = evaluate_jd_rules(jd, _raw(), rules=rules)

    assert "SFU-QUAL-EQUIVALENT" not in _ids(issues)


# =============================================================================
# DEFECT 2 — SFU-STRUCT-HOW-WHY could not NOT fire (HR-119 / HR-121)
# =============================================================================


def test_the_deterministic_engine_does_not_raise_how_why(rules: Rules) -> None:
    """``segmenter.py`` line 21: ``how_why`` is "left empty". The deterministic parser
    NEVER populates it, so ``not d.how_why`` was true for every duty of every JD and the
    rule fired on 100% of the 628 JDs we would approve. A finding present on every
    approvable JD distinguishes nothing — it is a constant subtracted from every score.
    """
    duties = [
        SFUDuty(action_verb=verb, statement=f"{verb} the program", how_why=[])
        for verb in ("Manages", "Coordinates", "Provides")
    ]
    issues = evaluate_jd_rules(_jd(duties=duties), _raw(), rules=rules)

    assert "SFU-STRUCT-HOW-WHY" not in _ids(issues)
    assert issues == []  # ...and it was the ONLY thing wrong with this JD


def test_the_how_why_rule_is_still_catalogued_and_is_reinstated_by_one_yaml_line(
    rules: Rules,
) -> None:
    """Retired, not deleted. The rule text, its severity and its rulebook citation all
    still ship — SFU's Part 2C expectation is real — and the register keeps the record
    (HR-119/HR-121) of why it is not raised and what would reinstate it. When an
    extractor populates ``how_why`` (Phase 4), ``evaluable: true`` is the whole change.
    """
    spec = rules.rule_catalog.spec("SFU-STRUCT-HOW-WHY")
    assert spec.evaluable is False
    assert spec.default_severity == "low"  # unchanged: this is not a severity mute
    assert rules.rule_catalog.unevaluable_rule_ids == ("SFU-STRUCT-HOW-WHY",)

    catalog: dict[str, Any] = yaml.safe_load(
        (_PKG_DIR / "rule_catalog.yaml").read_text(encoding="utf-8")
    )
    for entry in catalog["rules"]:
        if entry["rule_id"] == "SFU-STRUCT-HOW-WHY":
            entry["evaluable"] = True
    reinstated = _retuned(rules, "rule_catalog", rules=catalog["rules"])
    duties = [
        SFUDuty(action_verb=verb, statement=f"{verb} the program", how_why=[])
        for verb in ("Manages", "Coordinates", "Provides")
    ]
    issues = evaluate_jd_rules(_jd(duties=duties), _raw(), rules=reinstated)

    assert "SFU-STRUCT-HOW-WHY" in _ids(issues)


def test_muting_the_severity_would_not_have_been_the_fix(rules: Rules) -> None:
    """The tempting non-fix, RUN rather than reasoned about (as the change plan asked).

    Build the rulebook we would have shipped had we demoted the rule to ``info`` instead
    of retiring it, and score a JD with it. Both halves of the claim are then observed,
    not asserted from config:

    * the score IS identical to a clean JD's (``severity_penalty.info`` is 0.0) — so
      muting really would have lifted every score, which is why it looks like a fix;
    * and the finding is STILL EMITTED, on a JD the parser can never clear. A rule that
      cannot NOT fire is still in every report, on every reviewer's checklist, and at
      100% of every ``rule_frequency`` table. Muting hides the constant; it does not
      remove it — and the reviewer would be reading a finding nobody can act on.
    """
    catalog: dict[str, Any] = yaml.safe_load(
        (_PKG_DIR / "rule_catalog.yaml").read_text(encoding="utf-8")
    )
    for entry in catalog["rules"]:
        if entry["rule_id"] == "SFU-STRUCT-HOW-WHY":
            entry["evaluable"] = True  # not retired…
            entry["default_severity"] = "info"  # …merely muted
    muted = _retuned(rules, "rule_catalog", rules=catalog["rules"])

    duties = [
        SFUDuty(action_verb=verb, statement=f"{verb} the program", how_why=[])
        for verb in ("Manages", "Coordinates", "Provides")
    ]
    issues = evaluate_jd_rules(_jd(duties=duties), _raw(), rules=muted)
    score, grade = score_issues(issues, scoring=muted.scoring)

    assert (score, grade) == score_issues([], scoring=muted.scoring)  # costs nothing…
    assert "SFU-STRUCT-HOW-WHY" in _ids(issues)  # …and is reported anyway
    # Which is the whole point: the shipped rulebook emits nothing at all here.
    assert evaluate_jd_rules(_jd(duties=duties), _raw(), rules=rules) == []


def test_a_blocking_gate_may_not_name_a_rule_the_engine_never_raises(
    tmp_path: Path,
) -> None:
    """The other half of "a gate that cannot fire is a false safety guarantee".

    An unevaluable rule inside a blocking gate is a gate that can never block — a policy
    that silently does nothing. The rulebook refuses to load rather than ship it.
    """
    _write_rules(tmp_path)

    def _gate_on_it(data: dict[str, Any]) -> None:
        for gate in data["gates"]:
            if gate["gate_id"] == "SFU-APPROVE-SUMMARY-LENGTH":
                gate["rule_ids"].append("SFU-STRUCT-HOW-WHY")

    _patch(tmp_path, "gates.yaml", _gate_on_it)
    with pytest.raises(RulesError, match="never raises|can never fire|unevaluable"):
        load_rules(tmp_path)


def test_a_severity_floor_may_not_block_on_a_rule_the_engine_never_raises(
    tmp_path: Path,
) -> None:
    """THE SECOND ROUTE TO BLOCKING — and the hole the first version of the guard had.

    ``gates.blocking_rule_ids`` is derived from the ``blocking_rules`` gates ONLY, so a
    guard that checks against it leaves ``SFU-APPROVE-SEVERITY-FLOOR`` — which blocks on
    *any* finding at or above ``high``, named in no gate's ``rule_ids`` — wide open.

    This is the reviewer's exploit, verbatim, and it needed no code at all:

    1. ``titles.yaml`` — put ``SFU-AUTH-TITLE-REGISTRAR`` at ``high``. It is a free
       ``JDIssueSeverity`` data field and ``gates.yaml`` deliberately gates these rules
       with nothing. The rule now blocks, through the severity floor.
    2. ``rule_catalog.yaml`` — mark the same rule ``evaluable: false``.

    Before the fix the rulebook loaded happily, the finding disappeared, and a JD that
    was BLOCKED became APPROVABLE — with a live gate left in the register that nothing
    could trip. Two YAML words, an approval flipped, and no test went red. Now it does
    not load.
    """
    _write_rules(tmp_path)

    def _promote(data: dict[str, Any]) -> None:
        for title in data["restricted"]:
            if title["rule_id"] == "SFU-AUTH-TITLE-REGISTRAR":
                title["severity"] = "high"

    def _retire(data: dict[str, Any]) -> None:
        for entry in data["rules"]:
            if entry["rule_id"] == "SFU-AUTH-TITLE-REGISTRAR":
                entry["evaluable"] = False

    _patch(tmp_path, "titles.yaml", _promote)
    # Step 1 alone is a policy change, not a defect: the rule is still RAISED, so the
    # floor it now reaches can still fire. The rulebook must load.
    assert load_rules(tmp_path).rule_catalog.spec("SFU-AUTH-TITLE-REGISTRAR")

    _patch(tmp_path, "rule_catalog.yaml", _retire)
    with pytest.raises(RulesError, match="SEVERITY-FLOOR|min_severity|never raises"):
        load_rules(tmp_path)


def test_the_reachable_severity_of_a_rule_is_not_just_its_catalog_default(
    rules: Rules,
) -> None:
    """...and the guard above is only as good as this, so it is pinned on its own.

    Two validators override the catalog's ``default_severity`` **from other rule
    files**, which is why a guard reading only the default would have a second hole:
    ``SFU-LANG-CODED`` is raised at the ``coded_terms.yaml`` tier of the term that
    matched, and a restricted title at the ``severity`` its ``titles.yaml`` row carries.
    """
    reachable = rules._reachable_severities()

    assert reachable["SFU-LANG-CODED"] >= {"medium", "low"}  # the lexicon's tiers
    for title in rules.titles.restricted:
        assert title.severity in reachable[title.rule_id]
    assert set(reachable) == set(rules.rule_catalog.by_id)  # every rule, no exceptions


def test_an_unevaluable_rule_must_be_catalogued(tmp_path: Path) -> None:
    """...and the flag is per-rule, so it cannot name a rule that does not exist."""
    _write_rules(tmp_path)
    rules = load_rules(tmp_path)
    assert rules.rule_catalog.unevaluable_rule_ids == ("SFU-STRUCT-HOW-WHY",)
    assert set(rules.rule_catalog.unevaluable_rule_ids) <= set(rules.rule_catalog.by_id)


# =============================================================================
# DEFECT 3 — the era model conflated two rollouts (HR-109/110/111 / HR-122)
# =============================================================================


@pytest.fixture
def config(rules: Rules) -> Segmentation:
    return rules.segmentation


@pytest.mark.parametrize(
    ("name", "era"),
    [
        ("19980101_00012345_clerk.doc", "old"),
        ("20150101_00012345_clerk.doc", "transition"),
        ("20190101_00012345_analyst.docx", "new"),
        ("20231231_00012345_analyst.docx", "new"),
        # 2024 is the year footer adoption crossed 50% (11% in 2023 -> 63% in 2024).
        ("20240101_00012345_analyst.docx", "current"),
        ("20260401_00012345_analyst.docx", "current"),
    ],
)
def test_the_fourth_era_starts_where_the_second_rollout_did(
    config: Segmentation, name: str, era: str
) -> None:
    """Two transitions, four years apart: the JDFN TEMPLATE (2019) and the
    territorial/EDI FOOTER (2023-24). The old three-band model had a rung for the first
    only, then judged the whole ``new`` era with a blocking gate that only the second
    satisfies — a 7x artefact (10.0% vs 71.9% approval), all date and no quality."""
    assert file_facets(Path("/archive") / name, config).era == era


def test_the_template_token_promotes_an_old_file_but_cannot_demote_a_current_one(
    config: Segmentation,
) -> None:
    """The token override (HR-109) survives the fourth band, in the one direction it was
    ever for: a pre-2019 file carrying ``JDFN`` was authored on the current form and is
    judged as ``new``. It must not *cap* a 2025 file at ``new`` — which is what a naive
    "token wins" rule would do, since every current JD carries the token."""
    old_but_on_the_new_form = "20170301_00012345_analyst_JDFN_APSA_20170301.docx"
    todays_jd = "20250301_00012345_analyst_JDFN_APSA_20250301.docx"

    assert file_facets(Path("/archive") / old_but_on_the_new_form, config).era == "new"
    assert file_facets(Path("/archive") / todays_jd, config).era == "current"


def test_a_file_with_no_readable_date_is_still_era_unknown(
    config: Segmentation,
) -> None:
    assert file_facets(Path("/archive/Clerk.doc"), config).era == "unknown"
    dated_wrong = "20211301_00012345_clerk.doc"  # month 13 — a real risk over 14,565
    assert file_facets(Path("/archive") / dated_wrong, config).era == "unknown"


def test_the_era_bands_must_stay_ordered(tmp_path: Path) -> None:
    """A band nothing can land in is a segment that silently reports nothing — the
    segmentation form of "a gate that cannot fire". Now three boundaries, not two."""
    _write_rules(tmp_path)
    _patch(
        tmp_path,
        "segmentation.yaml",
        lambda d: d.update(era_transition_max_year=2025, era_new_max_year=2023),
    )
    with pytest.raises(RulesError, match="era_transition_max_year|era_new_max_year"):
        load_rules(tmp_path)


def test_adding_the_fourth_era_does_not_churn_rules_version(
    tmp_path: Path, rules: Rules
) -> None:
    """``segmentation.yaml`` is in ``_UNHASHED_FILES``: it decides which FILES a
    baseline is computed over, never what any JD SCORES. Re-band an era and not one JD's
    score, grade or gate decision changes — so invalidating the stamp on every report
    ever produced would be a lie about what actually changed. It is still registered and
    drift-checked (unhashed is not unwatched); it carries its own stamp instead."""
    _write_rules(tmp_path)
    _patch(tmp_path, "segmentation.yaml", lambda d: d.update(era_new_max_year=2022))
    rebanded = load_rules(tmp_path)

    assert rebanded.version == rules.version  # the rulebook did not move
    assert rebanded.segmentation.era_new_max_year == 2022  # ...but the file really did
    assert rebanded.segmentation.stamp != rules.segmentation.stamp  # ...and it says so


# =============================================================================
# All three are decision parameters — so all three are on the register
# =============================================================================


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("qualifications.banned_phrase_scope", "qualifications"),
        ("rule_catalog.unevaluable_rule_ids", ["SFU-STRUCT-HOW-WHY"]),
        ("segmentation.era_new_max_year", 2023),
    ],
)
def test_every_defect_fix_is_a_registered_decision_parameter(
    rules: Rules, path: str, expected: Any
) -> None:
    """Each fix CHANGES THE APPROVAL BAR, so none may be a quiet patch: the knob is on
    the decision surface, its shipped default is pinned by the register, and moving it
    without telling HR breaks the build (``check_register``)."""
    assert path in decision_surface(rules)
    assert live_value(rules, path) == expected

    registered = {d.config.path: d for d in rules.decision_register.decisions}
    assert path in registered, f"{path} is on the surface but nobody registered it"
    assert registered[path].status == "open"  # SFU HR has ratified nothing
    assert check_register(rules) == ()


def test_the_register_records_the_measured_impact_of_each_fix(rules: Rules) -> None:
    """A register entry that says "we changed the scope" and not "and it moved approval
    from 71.9% to X" is provenance theatre. All three changed the bar, and the number
    is in the entry."""
    by_id = rules.decision_register.by_id
    for decision_id in ("HR-041", "HR-119", "HR-109", "HR-110", "HR-111"):
        entry = by_id[decision_id]
        prose = f"{entry.why_it_matters} {entry.impact_if_changed}"
        assert "MEASURED" in prose
        assert "2.6" in prose, f"{decision_id} does not record the 2.6 re-measurement"


def test_no_decision_is_ratified_without_a_decider(rules: Rules) -> None:
    """The three fixes are OURS, not HR's — they are defects, not policy calls. Fixing
    them does not license flipping anything to `ratified`: that requires a human at SFU.
    """
    for decision in rules.decision_register.decisions:
        if decision.status == "ratified":
            assert (
                decision.decided_by and decision.decided_on and decision.decision_note
            )
            assert isinstance(decision.decided_on, dt.date)
        else:
            assert decision.decided_by is None

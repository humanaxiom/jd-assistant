"""Unit tests for the rules-as-data loader (Phase 2.1).

The SFU rulebook tables (thresholds, action-verb glossary, gender-coded lexicon,
KSA modifiers, markers, restricted titles, scoring) live in versioned YAML under
``src/jd_core/rules/`` — never hardcoded in logic. These tests are the fidelity
oracle for that port:

* every shipped YAML parses into the expected typed structure;
* the loaded values match the hris ``jd_rules.py`` originals **exactly** (the
  expected values are encoded here, not imported — hris is not on the container
  path);
* malformed / invalid rule data fails loudly with a typed error;
* ``get_rules()`` is cached and returns immutable structures;
* the grade bands cover every score 0-100 with exactly one grade.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, get_args

import pytest
import yaml
from pydantic import ValidationError

from src.jd_core.models.quality import JDGrade, JDIssueSeverity
from src.jd_core.rules import RULE_FILES, Rules, RulesError, get_rules, load_rules

# --- expected values, transcribed from hris jd_rules.py (RULES_VERSION v3) ----

EXPECTED_VERSION = "jd_rules_sfu_v3"

# _APPROVED_ACTION_VERBS — the complete SFU Toolkit glossary, transcribed
# verbatim. Pinned by exact set equality: a count-only assertion would let a
# typo'd verb (e.g. "researchs") swap in undetected.
EXPECTED_ACTION_VERBS: frozenset[str] = frozenset(
    {
        "accomplishes",
        "accountable",
        "accounts",
        "acknowledges",
        "acts",
        "adapts",
        "administers",
        "advises",
        "allocates",
        "analyzes",
        "applies",
        "approves",
        "arranges",
        "assemble",
        "assembles",
        "assesses",
        "assigns",
        "assists",
        "assures",
        "attends",
        "audits",
        "authorizes",
        "calculates",
        "carries",
        "checks",
        "collaborates",
        "communicates",
        "compiles",
        "composes",
        "computes",
        "conducts",
        "constructs",
        "contributes",
        "controls",
        "coordinates",
        "corrects",
        "counsels",
        "creates",
        "decides",
        "delegates",
        "demonstrates",
        "designs",
        "determines",
        "develops",
        "directs",
        "disciplines",
        "distributes",
        "drafts",
        "enforces",
        "ensures",
        "establishes",
        "estimates",
        "evaluates",
        "examines",
        "exercises",
        "facilitates",
        "forecasts",
        "formulates",
        "guides",
        "handles",
        "identifies",
        "implements",
        "initiates",
        "inspects",
        "instructs",
        "integrates",
        "interprets",
        "interviews",
        "investigates",
        "leads",
        "maintains",
        "manages",
        "measures",
        "monitors",
        "motivates",
        "negotiates",
        "observes",
        "operates",
        "organizes",
        "outlines",
        "oversees",
        "participates",
        "performs",
        "plans",
        "prepares",
        "processes",
        "programs",
        "promotes",
        "proposes",
        "provides",
        "purchases",
        "receives",
        "recommends",
        "records",
        "repairs",
        "reports",
        "represents",
        "requisitions",
        "researches",
        "resolves",
        "responsible",
        "reviews",
        "revises",
        "schedules",
        "screens",
        "selects",
        "services",
        "sorts",
        "suggests",
        "supervises",
        "tests",
        "trains",
        "transcribes",
        "transfers",
        "troubleshoots",
        "verifies",
    }
)

EXPECTED_ACTION_VERB_COUNT = 116

# _CODED_TERMS — term -> replacement copy, transcribed verbatim (31 entries).
EXPECTED_CODED_MEDIUM: dict[str, str] = {
    "aggressive": '"rapid", "intense", or "large"',
    "ambitious": '"motivated"',
    "championing": '"advocating" or "promoting"',
    "competitive": '"tough" or "intense"',
    "confidential": '"restricted"',
    "dominant": '"top"',
    "foreman": '"foreperson"',
    "persistent": '"tenacious" or "continuing"',
    "compassionate": '"caring"',
    "agreement": '"contract" or "partnership"',
    "in-kind": '"non-monetary"',
    "rockstar": '"skilled"',
    "ninja": '"expert"',
    "guru": '"specialist"',
    "chairman": '"chair" or "chairperson"',
    "policeman": '"police officer"',
    "fireman": '"firefighter"',
    "salesman": '"sales representative"',
    "businessman": '"business person" or "executive"',
    "spokesman": '"spokesperson"',
    "craftsman": '"artisan" or "craftsperson"',
    "workman": '"worker"',
    "middleman": '"intermediary" or "go-between"',
    "repairman": '"technician" or "repairer"',
    "waitress": '"server"',
    "actress": '"actor"',
    "stewardess": '"flight attendant"',
    "manpower": '"workforce" or "staffing"',
    "man-hours": '"work hours"',
    "mankind": '"humankind"',
    "manmade": '"artificial", "manufactured", or "synthetic"',
}

# _CODED_TERMS_LOW (6 entries).
EXPECTED_CODED_LOW: dict[str, str] = {
    "individual": '"single"/"lone", or "position"/"role" (as "this individual")',
    "honest": '"candid"',
    "trust": '"reliable"',
    "he/she": '"they" or "the incumbent"',
    "s/he": '"they" or "the incumbent"',
    "his/her": '"their" or "the incumbent\'s"',
}

EXPECTED_PLACEHOLDER_MARKERS = (
    "action verb",
    "how and why",
    "what by",
    "spell out acronyms",
    "provide a high level summary",
    "____",
    "[insert",
)

EXPECTED_WORKING_CONDITION_MARKERS = (
    "on-call",
    "on call",
    "shift work",
    "evenings and weekends",
    "evening and weekend",
    "weekends and holidays",
    "standby",
    "stand-by",
    "housing",
    "parking",
    "relocation",
)

EXPECTED_RELATIONSHIPS_HEADER = "establishes and maintains relationships and alliances"


@pytest.fixture(scope="module")
def rules() -> Rules:
    return get_rules()


# --- shipped data: structure + version --------------------------------------


def test_all_rule_files_ship_and_parse(rules: Rules) -> None:
    assert isinstance(rules, Rules)
    assert rules.version == EXPECTED_VERSION


def test_every_yaml_file_carries_the_same_version(rules: Rules) -> None:
    versions = {
        rules.thresholds.version,
        rules.action_verbs.version,
        rules.coded_terms.version,
        rules.qualifications.version,
        rules.markers.version,
        rules.patterns.version,
        rules.titles.version,
        rules.scoring.version,
        rules.rule_catalog.version,
    }
    assert versions == {EXPECTED_VERSION}


def test_rule_files_are_all_present_in_the_package() -> None:
    pkg_dir = Path(__file__).resolve().parents[2] / "src" / "jd_core" / "rules"
    for name in RULE_FILES:
        assert (pkg_dir / name).is_file(), name


# --- fidelity: thresholds ----------------------------------------------------


def test_thresholds_match_hris(rules: Rules) -> None:
    t = rules.thresholds
    assert t.duties_min == 3
    assert t.duties_max == 5
    assert t.summary_min_words == 100
    assert t.summary_max_words == 150
    assert t.max_listed == 5
    assert t.evidence_context_window == 40
    assert t.duty_allocation_min_count == 2
    assert t.duty_allocation_total_min == 99
    assert t.duty_allocation_total_max == 101


# --- fidelity: action-verb glossary -----------------------------------------


def test_action_verb_glossary_matches_hris_exactly(rules: Rules) -> None:
    verbs = rules.action_verbs.approved
    assert isinstance(verbs, frozenset)
    # exact-equality pin: no verb may be added, dropped, or typo'd.
    assert verbs == EXPECTED_ACTION_VERBS
    assert len(verbs) == EXPECTED_ACTION_VERB_COUNT
    # the two non-3rd-person entries hris carries verbatim, and the doubled
    # "assemble"/"assembles", are deliberate — call them out.
    assert {"accountable", "responsible", "assemble", "assembles"} <= verbs
    for absent in ("manage", "supporting", "do", "handle"):
        assert absent not in verbs
    assert all(v == v.lower() and v.strip() == v for v in verbs)


# --- fidelity: gender-coded lexicon -----------------------------------------


def test_coded_terms_medium_matches_hris(rules: Rules) -> None:
    # full mapping pin — keys AND the remediation copy.
    assert dict(rules.coded_terms.medium) == EXPECTED_CODED_MEDIUM
    assert len(rules.coded_terms.medium) == 31


def test_coded_terms_low_matches_hris(rules: Rules) -> None:
    assert dict(rules.coded_terms.low) == EXPECTED_CODED_LOW
    assert len(rules.coded_terms.low) == 6


def test_supporting_is_deliberately_not_a_coded_term(rules: Rules) -> None:
    # SFU marks "supporting" as "vague, clarify" — not a hard replace.
    assert "supporting" not in rules.coded_terms.medium
    assert "supporting" not in rules.coded_terms.low


def test_coded_term_tiers_do_not_overlap(rules: Rules) -> None:
    assert not (set(rules.coded_terms.medium) & set(rules.coded_terms.low))


# --- fidelity: KSA / qualifications -----------------------------------------


def test_ksa_modifiers_and_rank_match_hris(rules: Rules) -> None:
    q = rules.qualifications
    assert q.knowledge_modifiers == frozenset({"excellent", "working", "none"})
    assert q.skill_modifiers == frozenset(
        {"basic", "intermediate", "advanced", "expert"}
    )
    assert dict(q.ksa_rank) == {"knowledge": 0, "skill": 1, "ability": 2}


def test_qualification_phrases_match_hris(rules: Rules) -> None:
    q = rules.qualifications
    assert q.banned_phrases == ("may include", "assets", "preferences")
    assert q.equivalent_combination == "equivalent combination"
    assert q.ability_prefixes == ("ability to", "able to")


# --- fidelity: markers -------------------------------------------------------


def test_markers_match_hris(rules: Rules) -> None:
    m = rules.markers
    assert m.placeholder == EXPECTED_PLACEHOLDER_MARKERS
    assert m.working_conditions == EXPECTED_WORKING_CONDITION_MARKERS
    assert m.relationships_header == EXPECTED_RELATIONSHIPS_HEADER


# --- fidelity: restricted titles ---------------------------------------------


def test_restricted_titles_match_hris(rules: Rules) -> None:
    by_key = {t.key: t for t in rules.titles.restricted}
    assert set(by_key) == {"executive_director", "registrar", "human_resources"}
    assert by_key["executive_director"].phrase == "executive director"
    assert by_key["executive_director"].reserved_for_employee_group == "apex"
    assert by_key["registrar"].reserved_for_employee_group is None
    assert by_key["human_resources"].phrase == "human resources"
    # per-title severities, ported from hris _authoring_gates (so 2.2 never has
    # to hardcode "low"/"info").
    assert by_key["executive_director"].severity == "low"
    assert by_key["registrar"].severity == "info"
    assert by_key["human_resources"].severity == "info"
    assert all(t.severity in get_args(JDIssueSeverity) for t in rules.titles.restricted)


def test_unknown_title_severity_raises(tmp_path: Path) -> None:
    _write_valid_rules(tmp_path)
    _patch(
        tmp_path,
        "titles.yaml",
        lambda d: d["restricted"][0].__setitem__("severity", "catastrophic"),
    )
    with pytest.raises(RulesError, match="severity"):
        load_rules(tmp_path)


# --- fidelity: patterns (compiled once) --------------------------------------


def test_patterns_are_precompiled_and_behave_like_hris(rules: Rules) -> None:
    p = rules.patterns
    assert isinstance(p.incumbent, re.Pattern)
    # _INCUMBENT_RE = r"\bmy\b|\bmyself\b|\bi am\b", IGNORECASE
    assert p.incumbent.search("I am responsible for X")
    assert p.incumbent.search("This is MY desk")
    assert p.incumbent.search("myself")
    assert p.incumbent.search("The incumbent manages the team") is None
    assert p.incumbent.flags & re.IGNORECASE

    # _DUTY_ALLOCATION: r"\((\d{1,3})\s*%\)" — parenthesized percentages only.
    found = p.duty_allocation.findall("Leads x (40%) and y (60 %) — 15% elsewhere")
    assert [int(n) for n in found] == [40, 60]

    assert p.degree_mention.search("Bachelor's degree in Communications")
    assert p.related_discipline.search("or a relevant discipline")
    assert p.related_discipline.search("or other relevant field of study")
    assert p.senior_title.search("Senior Analyst")
    assert p.senior_title.search("Seniority") is None


def test_patterns_are_compiled_once(rules: Rules) -> None:
    assert rules.patterns.incumbent is get_rules().patterns.incumbent


# --- fidelity: scoring -------------------------------------------------------


def test_severity_penalties_match_hris(rules: Rules) -> None:
    penalties = rules.scoring.severity_penalty
    assert dict(penalties) == {
        "high": 20.0,
        "medium": 10.0,
        "low": 5.0,
        "info": 0.0,
    }
    assert set(penalties) == set(get_args(JDIssueSeverity))


def test_severity_decay_matches_hris(rules: Rules) -> None:
    assert rules.scoring.severity_decay == 0.7


def test_grade_bands_match_hris(rules: Rules) -> None:
    bands = [(b.min_score, b.grade) for b in rules.scoring.grade_bands]
    assert bands == [(90.0, "A"), (75.0, "B"), (60.0, "C"), (40.0, "D")]
    assert rules.scoring.fallback_grade == "F"


def test_every_score_maps_to_exactly_one_grade(rules: Rules) -> None:
    valid = set(get_args(JDGrade))
    seen: set[str] = set()
    for score in range(0, 101):
        grade = rules.scoring.grade_for(float(score))
        assert grade in valid
        seen.add(grade)
    assert seen == valid  # every grade is reachable; every score is covered


def test_grade_band_boundaries(rules: Rules) -> None:
    grade_for = rules.scoring.grade_for
    assert grade_for(100.0) == "A"
    assert grade_for(90.0) == "A"
    assert grade_for(89.9) == "B"
    assert grade_for(75.0) == "B"
    assert grade_for(74.9) == "C"
    assert grade_for(60.0) == "C"
    assert grade_for(59.9) == "D"
    assert grade_for(40.0) == "D"
    assert grade_for(39.9) == "F"
    assert grade_for(0.0) == "F"


# --- caching + immutability --------------------------------------------------


def test_get_rules_is_cached() -> None:
    assert get_rules() is get_rules()


def test_loaded_rules_are_frozen(rules: Rules) -> None:
    with pytest.raises(ValidationError):
        rules.thresholds.duties_min = 4  # type: ignore[misc]
    with pytest.raises(TypeError):
        rules.coded_terms.medium["ninja"] = "nope"  # type: ignore[index]
    with pytest.raises(AttributeError):
        rules.action_verbs.approved.add("frobnicates")  # type: ignore[attr-defined]


# --- validation: malformed / invalid rule data -------------------------------


def _write_valid_rules(directory: Path) -> None:
    """Copy the shipped YAML into ``directory`` so a test can corrupt one file."""
    pkg_dir = Path(__file__).resolve().parents[2] / "src" / "jd_core" / "rules"
    for name in RULE_FILES:
        (directory / name).write_text(
            (pkg_dir / name).read_text(encoding="utf-8"), encoding="utf-8"
        )


def _patch(directory: Path, name: str, mutate: Any) -> None:
    data = yaml.safe_load((directory / name).read_text(encoding="utf-8"))
    mutate(data)
    (directory / name).write_text(yaml.safe_dump(data), encoding="utf-8")


def test_load_rules_from_an_explicit_directory(tmp_path: Path) -> None:
    _write_valid_rules(tmp_path)
    loaded = load_rules(tmp_path)
    assert loaded.version == EXPECTED_VERSION
    assert len(loaded.action_verbs.approved) == EXPECTED_ACTION_VERB_COUNT


def test_missing_file_raises_rules_error(tmp_path: Path) -> None:
    _write_valid_rules(tmp_path)
    (tmp_path / "scoring.yaml").unlink()
    with pytest.raises(RulesError, match="scoring.yaml"):
        load_rules(tmp_path)


def test_malformed_yaml_raises_rules_error(tmp_path: Path) -> None:
    _write_valid_rules(tmp_path)
    (tmp_path / "thresholds.yaml").write_text("version: [unclosed\n", encoding="utf-8")
    with pytest.raises(RulesError, match="thresholds.yaml"):
        load_rules(tmp_path)


def test_non_mapping_yaml_raises_rules_error(tmp_path: Path) -> None:
    _write_valid_rules(tmp_path)
    (tmp_path / "markers.yaml").write_text("- just\n- a\n- list\n", encoding="utf-8")
    with pytest.raises(RulesError, match="markers.yaml"):
        load_rules(tmp_path)


def test_version_mismatch_across_files_raises(tmp_path: Path) -> None:
    _write_valid_rules(tmp_path)
    _patch(tmp_path, "scoring.yaml", lambda d: d.__setitem__("version", "other_v9"))
    with pytest.raises(RulesError, match="version"):
        load_rules(tmp_path)


def test_unordered_grade_bands_raise(tmp_path: Path) -> None:
    _write_valid_rules(tmp_path)
    _patch(
        tmp_path,
        "scoring.yaml",
        lambda d: d.__setitem__(
            "grade_bands",
            [
                {"min_score": 40.0, "grade": "D"},
                {"min_score": 90.0, "grade": "A"},
            ],
        ),
    )
    with pytest.raises(RulesError, match="descending"):
        load_rules(tmp_path)


def test_duplicate_grade_bands_raise(tmp_path: Path) -> None:
    _write_valid_rules(tmp_path)
    _patch(
        tmp_path,
        "scoring.yaml",
        lambda d: d.__setitem__(
            "grade_bands",
            [
                {"min_score": 90.0, "grade": "A"},
                {"min_score": 75.0, "grade": "A"},
            ],
        ),
    )
    with pytest.raises(RulesError):
        load_rules(tmp_path)


def test_fallback_grade_may_not_repeat_a_band_grade(tmp_path: Path) -> None:
    _write_valid_rules(tmp_path)
    _patch(tmp_path, "scoring.yaml", lambda d: d.__setitem__("fallback_grade", "D"))
    with pytest.raises(RulesError):
        load_rules(tmp_path)


def test_missing_severity_key_raises(tmp_path: Path) -> None:
    _write_valid_rules(tmp_path)
    _patch(tmp_path, "scoring.yaml", lambda d: d["severity_penalty"].pop("info"))
    with pytest.raises(RulesError, match="severity"):
        load_rules(tmp_path)


def test_unknown_severity_key_raises(tmp_path: Path) -> None:
    _write_valid_rules(tmp_path)
    _patch(
        tmp_path,
        "scoring.yaml",
        lambda d: d["severity_penalty"].__setitem__("catastrophic", 99.0),
    )
    with pytest.raises(RulesError, match="severity"):
        load_rules(tmp_path)


def test_empty_coded_term_key_raises(tmp_path: Path) -> None:
    _write_valid_rules(tmp_path)
    _patch(tmp_path, "coded_terms.yaml", lambda d: d["medium"].__setitem__("  ", "x"))
    with pytest.raises(RulesError):
        load_rules(tmp_path)


def test_empty_coded_term_replacement_raises(tmp_path: Path) -> None:
    _write_valid_rules(tmp_path)
    _patch(tmp_path, "coded_terms.yaml", lambda d: d["medium"].__setitem__("ninja", ""))
    with pytest.raises(RulesError):
        load_rules(tmp_path)


def test_coded_term_in_both_tiers_raises(tmp_path: Path) -> None:
    _write_valid_rules(tmp_path)
    _patch(tmp_path, "coded_terms.yaml", lambda d: d["low"].__setitem__("ninja", '"x"'))
    with pytest.raises(RulesError, match="both"):
        load_rules(tmp_path)


def test_inverted_thresholds_raise(tmp_path: Path) -> None:
    _write_valid_rules(tmp_path)
    _patch(tmp_path, "thresholds.yaml", lambda d: d.__setitem__("duties_min", 9))
    with pytest.raises(RulesError, match="duties"):
        load_rules(tmp_path)


def test_inverted_summary_word_range_raises(tmp_path: Path) -> None:
    _write_valid_rules(tmp_path)
    _patch(
        tmp_path, "thresholds.yaml", lambda d: d.__setitem__("summary_max_words", 10)
    )
    with pytest.raises(RulesError, match="summary"):
        load_rules(tmp_path)


def test_uppercase_action_verb_raises(tmp_path: Path) -> None:
    _write_valid_rules(tmp_path)
    _patch(tmp_path, "action_verbs.yaml", lambda d: d["approved"].append("Manages"))
    with pytest.raises(RulesError):
        load_rules(tmp_path)


def test_bad_regex_raises(tmp_path: Path) -> None:
    _write_valid_rules(tmp_path)
    _patch(
        tmp_path,
        "patterns.yaml",
        lambda d: d["incumbent"].__setitem__("pattern", "[unclosed"),
    )
    with pytest.raises(RulesError):
        load_rules(tmp_path)


def test_unknown_field_in_yaml_raises(tmp_path: Path) -> None:
    _write_valid_rules(tmp_path)
    _patch(tmp_path, "thresholds.yaml", lambda d: d.__setitem__("bogus_key", 1))
    with pytest.raises(RulesError):
        load_rules(tmp_path)


def test_out_of_range_decay_raises(tmp_path: Path) -> None:
    _write_valid_rules(tmp_path)
    _patch(tmp_path, "scoring.yaml", lambda d: d.__setitem__("severity_decay", 1.5))
    with pytest.raises(RulesError):
        load_rules(tmp_path)


def test_invalid_ksa_rank_raises(tmp_path: Path) -> None:
    _write_valid_rules(tmp_path)
    _patch(
        tmp_path,
        "qualifications.yaml",
        lambda d: d["ksa_rank"].__setitem__("knowledge", 5),
    )
    with pytest.raises(RulesError, match="ksa_rank"):
        load_rules(tmp_path)


def test_empty_ksa_rank_raises(tmp_path: Path) -> None:
    _write_valid_rules(tmp_path)
    _patch(tmp_path, "qualifications.yaml", lambda d: d.__setitem__("ksa_rank", {}))
    with pytest.raises(RulesError, match="ksa_rank"):
        load_rules(tmp_path)


def test_uppercase_coded_term_key_raises(tmp_path: Path) -> None:
    _write_valid_rules(tmp_path)
    _patch(tmp_path, "coded_terms.yaml", lambda d: d["medium"].__setitem__("Guru", "x"))
    with pytest.raises(RulesError, match="lowercase"):
        load_rules(tmp_path)


def test_empty_action_verb_raises(tmp_path: Path) -> None:
    _write_valid_rules(tmp_path)
    _patch(tmp_path, "action_verbs.yaml", lambda d: d["approved"].append(""))
    with pytest.raises(RulesError, match="non-empty"):
        load_rules(tmp_path)


def test_inverted_duty_allocation_tolerance_raises(tmp_path: Path) -> None:
    _write_valid_rules(tmp_path)
    _patch(
        tmp_path,
        "thresholds.yaml",
        lambda d: d.__setitem__("duty_allocation_total_max", 90),
    )
    with pytest.raises(RulesError, match="duty_allocation_total"):
        load_rules(tmp_path)


def test_duplicate_restricted_title_keys_raise(tmp_path: Path) -> None:
    _write_valid_rules(tmp_path)
    _patch(
        tmp_path,
        "titles.yaml",
        lambda d: d["restricted"].append(dict(d["restricted"][0])),
    )
    with pytest.raises(RulesError, match="unique"):
        load_rules(tmp_path)


# --- rule catalog (Phase 2.2 — the catalog is rule data too) ------------------


def test_duplicate_rule_ids_raise(tmp_path: Path) -> None:
    _write_valid_rules(tmp_path)
    _patch(
        tmp_path,
        "rule_catalog.yaml",
        lambda d: d["rules"].append(dict(d["rules"][0])),
    )
    with pytest.raises(RulesError, match="duplicate rule_id"):
        load_rules(tmp_path)


def test_unknown_rule_category_raises(tmp_path: Path) -> None:
    _write_valid_rules(tmp_path)
    _patch(
        tmp_path,
        "rule_catalog.yaml",
        lambda d: d["rules"][0].__setitem__("category", "vibes"),
    )
    with pytest.raises(RulesError, match="category"):
        load_rules(tmp_path)


def test_unknown_rule_section_raises(tmp_path: Path) -> None:
    _write_valid_rules(tmp_path)
    _patch(
        tmp_path,
        "rule_catalog.yaml",
        lambda d: d["rules"][0].__setitem__("section", "nowhere"),
    )
    with pytest.raises(RulesError, match="section"):
        load_rules(tmp_path)


def test_message_and_recommendation_variants_must_agree(tmp_path: Path) -> None:
    _write_valid_rules(tmp_path)
    _patch(
        tmp_path,
        "rule_catalog.yaml",
        lambda d: d["rules"][0]["messages"].__setitem__("extra", "unmatched variant"),
    )
    with pytest.raises(RulesError, match="variant keys"):
        load_rules(tmp_path)


def test_general_may_not_be_a_template_section(tmp_path: Path) -> None:
    _write_valid_rules(tmp_path)
    _patch(
        tmp_path,
        "rule_catalog.yaml",
        lambda d: d["section_order"].append("general"),
    )
    with pytest.raises(RulesError, match="general"):
        load_rules(tmp_path)


def test_incomplete_category_fallback_map_raises(tmp_path: Path) -> None:
    _write_valid_rules(tmp_path)
    _patch(
        tmp_path,
        "rule_catalog.yaml",
        lambda d: d["category_fallback_section"].pop("clarity"),
    )
    with pytest.raises(RulesError, match="JDIssueCategory"):
        load_rules(tmp_path)


def test_incomplete_section_labels_raise(tmp_path: Path) -> None:
    _write_valid_rules(tmp_path)
    _patch(
        tmp_path,
        "rule_catalog.yaml",
        lambda d: d["section_labels"].pop("general"),
    )
    with pytest.raises(RulesError, match="section_labels"):
        load_rules(tmp_path)


def test_restricted_title_naming_an_uncatalogued_rule_raises(tmp_path: Path) -> None:
    _write_valid_rules(tmp_path)
    _patch(
        tmp_path,
        "titles.yaml",
        lambda d: d["restricted"][0].__setitem__("rule_id", "SFU-NOT-A-RULE"),
    )
    with pytest.raises(RulesError, match="rule_catalog"):
        load_rules(tmp_path)


def test_unknown_message_variant_raises(rules: Rules) -> None:
    spec = rules.rule_catalog.spec("SFU-COMP-SUMMARY")
    with pytest.raises(RulesError, match="variant"):
        spec.render("nope", {})


def test_unsupplied_placeholder_raises(rules: Rules) -> None:
    spec = rules.rule_catalog.spec("SFU-STRUCT-SUMMARY-TOO-SHORT")
    with pytest.raises(RulesError, match="placeholder"):
        spec.render("default", {})


def test_spec_lookup_of_an_unknown_rule_raises(rules: Rules) -> None:
    with pytest.raises(RulesError, match="unknown rule_id"):
        rules.rule_catalog.spec("SFU-NOT-A-RULE")


def test_coded_term_tiers_are_named_by_their_severity(rules: Rules) -> None:
    tiers = rules.coded_terms.tiers
    assert [severity for severity, _ in tiers] == ["medium", "low"]
    assert dict(tiers[0][1]) == EXPECTED_CODED_MEDIUM
    assert dict(tiers[1][1]) == EXPECTED_CODED_LOW


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda d: d.__setitem__("incumbent", "just a string"), "mapping"),
        (lambda d: d["incumbent"].__setitem__("flags", "i"), "unknown regex-rule key"),
        (lambda d: d["incumbent"].__setitem__("pattern", "   "), "non-empty string"),
        (lambda d: d["incumbent"].__setitem__("ignore_case", "yes"), "boolean"),
        # ignore_case IS rule data (patterns.yaml sets it on every entry): it must
        # be declared, never silently defaulted in Python (invariant #2).
        (lambda d: d["incumbent"].pop("ignore_case"), "missing regex-rule key"),
        (lambda d: d["incumbent"].pop("pattern"), "missing regex-rule key"),
    ],
)
def test_malformed_regex_rule_raises(
    tmp_path: Path, mutation: Any, message: str
) -> None:
    _write_valid_rules(tmp_path)
    _patch(tmp_path, "patterns.yaml", mutation)
    with pytest.raises(RulesError, match=message):
        load_rules(tmp_path)

"""Unit tests for the JD rule catalog (as data) + the section-grouped checklist.

Three things are pinned here:

* **The catalog is rulebook data** — the 27 ``RuleSpec`` entries, the SFU section
  labels, the template section order and the category->section fallback map are
  loaded from ``rules/rule_catalog.yaml``, not hardcoded in Python. Their content
  is checked against ``sfu_rules_expected`` (transcribed from hris).
* **Catalog and validators stay in sync** — every deterministic issue carries a
  ``rule_id`` that exists in the catalog, and the issue's category matches the
  catalog's (the catalog is the single source of truth for category).
* **build_checklist** regroups a flat issue list into the guide's 10 SFU sections
  (in template order, clean ones marked ``ok``) plus a cross-cutting ``general``
  bucket that appears only when it has findings.
"""

from __future__ import annotations

from pathlib import Path
from typing import get_args

import pytest
import yaml

from src.jd_core.models.parsed_jd import (
    SFUDuty,
    SFUJobDescription,
    SFUQualification,
    SFURelationships,
)
from src.jd_core.models.quality import (
    JDIssueCategory,
    JDIssueSeverity,
    JDIssueSource,
    JDQualityIssue,
    SFUSection,
)
from src.jd_core.quality import build_checklist, evaluate_jd_rules, section_for_issue
from src.jd_core.rules import RULE_FILES, RuleCatalog, get_rules
from tests.unit.sfu_rules_expected import (
    EXPECTED_CATALOG,
    EXPECTED_CATEGORY_FALLBACK,
    EXPECTED_SECTION_LABELS,
    EXPECTED_SECTION_ORDER,
)

_RULES_DIR = Path(__file__).resolve().parents[2] / "src" / "jd_core" / "rules"


@pytest.fixture(scope="module")
def catalog() -> RuleCatalog:
    return get_rules().rule_catalog


def _issue(
    category: JDIssueCategory = "structure",
    *,
    rule_id: str | None = None,
    source: JDIssueSource = "rule",
    severity: JDIssueSeverity = "low",
    message: str = "m",
) -> JDQualityIssue:
    return JDQualityIssue(
        category=category,
        severity=severity,
        source=source,
        message=message,
        rule_id=rule_id,
    )


def _flawed_jd() -> SFUJobDescription:
    # Trips a spread of gates across many sections: too few duties, missing
    # decision-making, out-of-order KSAs, a restricted title, coded language.
    return SFUJobDescription(
        title="Senior Registrar",  # Senior w/o supervisory + Registrar (info)
        about_sfu_present=False,
        position_summary="short",  # word-count structure
        duties=[
            SFUDuty(action_verb="Synergizes", statement="Synergizes things", how_why=[])
        ],
        decision_making=[],
        problem_solving=[],
        relationships=SFURelationships(),  # no supervisory -> Senior flagged
        qualifications=[
            SFUQualification(text="Python", kind="skill", modifier=None),
            SFUQualification(
                text="Knowledge of X", kind="knowledge", modifier="working"
            ),
        ],
        territorial_acknowledgement_present=False,
        employment_equity_present=False,
    )


_FLAWED_RAW = "Ability to lead. Assets are nice."


# --- the catalog ships as YAML (rulebook as data) -----------------------------


def test_rule_catalog_is_a_versioned_yaml_file_in_the_rules_package() -> None:
    assert "rule_catalog.yaml" in RULE_FILES
    path = _RULES_DIR / "rule_catalog.yaml"
    assert path.is_file()
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert raw["version"] == get_rules().version
    assert len(raw["rules"]) == len(EXPECTED_CATALOG)


def test_catalog_matches_hris_exactly(catalog: RuleCatalog) -> None:
    assert set(catalog.by_id) == set(EXPECTED_CATALOG)
    for rule_id, expected in EXPECTED_CATALOG.items():
        spec = catalog.by_id[rule_id]
        assert spec.rule_id == rule_id
        assert spec.category == expected.category, rule_id
        assert spec.section == expected.section, rule_id
        assert spec.source_part == expected.source_part, rule_id
        assert spec.default_severity == expected.default_severity, rule_id
        assert spec.owner == expected.owner, rule_id
        assert spec.title, rule_id


def test_every_rule_carries_message_and_recommendation_copy(
    catalog: RuleCatalog,
) -> None:
    for rule_id, spec in catalog.by_id.items():
        assert spec.messages, rule_id
        assert set(spec.messages) == set(spec.recommendations), rule_id
        assert all(m.strip() for m in spec.messages.values()), rule_id
        assert all(r.strip() for r in spec.recommendations.values()), rule_id


def test_section_labels_and_order_match_hris(catalog: RuleCatalog) -> None:
    assert catalog.section_order == EXPECTED_SECTION_ORDER
    assert dict(catalog.section_labels) == EXPECTED_SECTION_LABELS
    # "general" is a bucket, not a template section: labelled but not ordered.
    assert "general" not in catalog.section_order
    assert "general" in catalog.section_labels


def test_category_fallback_map_matches_hris(catalog: RuleCatalog) -> None:
    assert dict(catalog.category_fallback_section) == EXPECTED_CATEGORY_FALLBACK


def test_catalog_ids_are_unique_and_self_consistent(catalog: RuleCatalog) -> None:
    ids = [spec.rule_id for spec in catalog.rules]
    assert len(set(ids)) == len(ids)
    for spec in catalog.rules:
        assert spec.section in set(catalog.section_order) | {"general"}
        assert spec.owner in ("deterministic", "llm")


def test_restricted_titles_reference_catalogued_rules() -> None:
    rules = get_rules()
    for title in rules.titles.restricted:
        assert title.rule_id in rules.rule_catalog.by_id, title.key


# --- catalog / validator consistency ------------------------------------------


def test_every_deterministic_issue_is_catalogued_and_category_matches() -> None:
    issues = evaluate_jd_rules(_flawed_jd(), _FLAWED_RAW)
    rule_issues = [i for i in issues if i.source == "rule"]
    assert rule_issues, "expected the flawed JD to trip several deterministic gates"
    catalog = get_rules().rule_catalog
    for issue in rule_issues:
        assert issue.rule_id is not None
        assert issue.rule_id in catalog.by_id, issue.rule_id
        # The catalog owns the category — the emitted category must agree.
        assert issue.category == catalog.by_id[issue.rule_id].category, issue.rule_id


def test_every_emitted_issue_is_rule_sourced() -> None:
    issues = evaluate_jd_rules(_flawed_jd(), _FLAWED_RAW)
    assert {i.source for i in issues} == {"rule"}


# --- build_checklist ----------------------------------------------------------


def test_clean_jd_checklist_is_all_ten_sections_ok() -> None:
    checklist = build_checklist([])
    assert [s.section for s in checklist] == list(EXPECTED_SECTION_ORDER)
    assert all(s.status == "ok" and s.issues == [] for s in checklist)
    assert all(s.section != "general" for s in checklist)


def test_checklist_labels_come_from_the_catalog() -> None:
    checklist = build_checklist([])
    assert {s.section: s.label for s in checklist} == {
        section: EXPECTED_SECTION_LABELS[section] for section in EXPECTED_SECTION_ORDER
    }


def test_checklist_groups_issue_into_its_rule_section() -> None:
    issues = [_issue("completeness", rule_id="SFU-COMP-SUMMARY", severity="high")]
    checklist = build_checklist(issues)
    summary = next(s for s in checklist if s.section == "position_summary")
    assert summary.status == "issues"
    assert summary.issues[0].rule_id == "SFU-COMP-SUMMARY"
    assert all(s.status == "ok" for s in checklist if s.section != "position_summary")


def test_checklist_general_bucket_holds_llm_and_crosscutting_findings() -> None:
    issues = [
        _issue("clarity", source="llm", rule_id=None),  # LLM finding, no rule_id
        _issue("inclusive_language", rule_id="SFU-LANG-CODED", severity="medium"),
    ]
    checklist = build_checklist(issues)
    general = [s for s in checklist if s.section == "general"]
    assert len(general) == 1
    assert general[0].status == "issues"
    assert len(general[0].issues) == 2
    # general is appended AFTER the 10 ordered sections.
    assert checklist[-1].section == "general"
    assert general[0].label == EXPECTED_SECTION_LABELS["general"]


def test_checklist_preserves_every_issue_exactly_once() -> None:
    issues = evaluate_jd_rules(_flawed_jd(), _FLAWED_RAW)
    checklist = build_checklist(issues)
    regrouped = [i for s in checklist for i in s.issues]
    assert len(regrouped) == len(issues)
    assert {id(i) for i in regrouped} == {id(i) for i in issues}


def test_section_for_issue_falls_back_by_category_when_uncatalogued() -> None:
    # An LLM seniority_mismatch finding (no rule_id) maps via the category
    # fallback to identification, not the general bucket.
    assert section_for_issue(_issue("seniority_mismatch", source="llm")) == (
        "identification"
    )
    # A cross-cutting category with no rule_id -> general.
    assert section_for_issue(_issue("clarity", source="llm")) == "general"


def test_section_for_issue_ignores_an_unknown_rule_id() -> None:
    unknown = _issue("qualification_standard", rule_id="SFU-NOT-A-RULE")
    assert section_for_issue(unknown) == "qualifications"  # category fallback


def test_every_sfu_section_is_labelled(catalog: RuleCatalog) -> None:
    assert set(catalog.section_labels) == set(get_args(SFUSection))

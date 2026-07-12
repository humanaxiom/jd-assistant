"""Unit tests for the JD quality schemas (ported from hris `jd_quality.py`).

Covers: round-trip, enum coverage (category/severity/source/grade/section),
extra="forbid" behaviour, score bounds, and the findings/checklist/corpus
schema defaults.
"""

from __future__ import annotations

import datetime as dt
from uuid import uuid4

import pytest
from pydantic import ValidationError

from src.jd_core.models.quality import (
    JDChecklistSection,
    JDGrade,
    JDIssueCategory,
    JDIssueSeverity,
    JDIssueSource,
    JDQualityCorpusRow,
    JDQualityCorpusSummary,
    JDQualityFinding,
    JDQualityFindings,
    JDQualityIssue,
    JDQualityReport,
    SFUSection,
)
from src.jd_core.rules import get_rules


def _issue() -> JDQualityIssue:
    return JDQualityIssue(
        category="completeness",
        severity="high",
        source="rule",
        message="Position summary is missing.",
        suggestion="Add a 100-150 word summary.",
        evidence=None,
        rule_id="SFU-COMP-SUMMARY",
    )


def _report() -> JDQualityReport:
    return JDQualityReport(
        job_id=uuid4(),
        overall_score=82.5,
        grade="B",
        issue_count=1,
        issues=[_issue()],
        model="qwen2.5",
        prompt_version="jd_quality_v1",
        # The stamp's real shape: declared version + a digest of the rule CONTENT (see
        # test_rules_version.py). A bare `jd_rules_sfu_v3` here would advertise a
        # format that no longer identifies any rulebook.
        rules_version=get_rules().version,
        generated_at=dt.datetime(2026, 7, 10, tzinfo=dt.UTC),
    )


# ---------- round trip ----------


def test_issue_round_trip() -> None:
    issue = _issue()
    assert JDQualityIssue.model_validate(issue.model_dump()) == issue


def test_report_round_trip() -> None:
    report = _report()
    assert JDQualityReport.model_validate(report.model_dump()) == report


def test_corpus_summary_round_trip() -> None:
    summary = JDQualityCorpusSummary(
        total_parsed=10,
        evaluated=6,
        not_evaluated=4,
        grade_counts={"A": 2, "B": 4},
        rows=[
            JDQualityCorpusRow(
                job_id=uuid4(),
                title="Analyst",
                department="IT",
                overall_score=90.0,
                grade="A",
                issue_count=0,
                generated_at=dt.datetime(2026, 7, 1, tzinfo=dt.UTC),
            )
        ],
    )
    assert JDQualityCorpusSummary.model_validate(summary.model_dump()) == summary


# ---------- defaults ----------


def test_issue_optional_defaults() -> None:
    issue = JDQualityIssue(
        category="clarity",
        severity="low",
        source="llm",
        message="Vague requirement.",
    )
    assert issue.suggestion == ""
    assert issue.evidence is None
    assert issue.rule_id is None


def test_findings_default_empty() -> None:
    assert JDQualityFindings().issues == []


def test_finding_default_severity_medium() -> None:
    finding = JDQualityFinding(category="clarity", message="unclear")
    assert finding.severity == "medium"
    assert finding.suggestion == ""
    assert finding.evidence is None


def test_report_default_checklist_empty() -> None:
    report = _report()
    assert report.checklist == []


def test_checklist_section() -> None:
    section = JDChecklistSection(
        section="duties",
        label="Duties & Responsibilities",
        status="issues",
        issues=[_issue()],
    )
    assert JDChecklistSection.model_validate(section.model_dump()) == section


# ---------- validation ----------


def test_issue_forbids_extra() -> None:
    with pytest.raises(ValidationError):
        JDQualityIssue.model_validate(
            {
                "category": "clarity",
                "severity": "low",
                "source": "llm",
                "message": "x",
                "bogus": 1,
            }
        )


def test_report_forbids_extra() -> None:
    with pytest.raises(ValidationError):
        JDQualityReport.model_validate({**_report().model_dump(), "bogus": 1})


def test_score_bounds_enforced() -> None:
    with pytest.raises(ValidationError):
        JDQualityReport.model_validate({**_report().model_dump(), "overall_score": 101})
    with pytest.raises(ValidationError):
        JDQualityReport.model_validate({**_report().model_dump(), "overall_score": -1})


def test_issue_count_non_negative() -> None:
    with pytest.raises(ValidationError):
        JDQualityReport.model_validate({**_report().model_dump(), "issue_count": -1})


def test_message_min_length() -> None:
    with pytest.raises(ValidationError):
        JDQualityIssue.model_validate(
            {"category": "clarity", "severity": "low", "source": "llm", "message": ""}
        )


# ---------- enum coverage ----------


@pytest.mark.parametrize(
    "category",
    [
        "completeness",
        "structure",
        "qualification_standard",
        "matchability",
        "over_specification",
        "keyword_stuffing",
        "seniority_mismatch",
        "inclusive_language",
        "clarity",
    ],
)
def test_issue_categories(category: str) -> None:
    issue = JDQualityIssue(
        category=category,  # type: ignore[arg-type]
        severity="info",
        source="rule",
        message="m",
    )
    assert issue.category == category


@pytest.mark.parametrize("severity", ["info", "low", "medium", "high"])
def test_issue_severities(severity: str) -> None:
    issue = JDQualityIssue(
        category="clarity",
        severity=severity,  # type: ignore[arg-type]
        source="rule",
        message="m",
    )
    assert issue.severity == severity


@pytest.mark.parametrize("source", ["rule", "llm"])
def test_issue_sources(source: str) -> None:
    issue = JDQualityIssue(
        category="clarity",
        severity="info",
        source=source,  # type: ignore[arg-type]
        message="m",
    )
    assert issue.source == source


@pytest.mark.parametrize("grade", ["A", "B", "C", "D", "F"])
def test_grades(grade: str) -> None:
    report = JDQualityReport.model_validate({**_report().model_dump(), "grade": grade})
    assert report.grade == grade


def test_invalid_grade_rejected() -> None:
    with pytest.raises(ValidationError):
        JDQualityReport.model_validate({**_report().model_dump(), "grade": "E"})


@pytest.mark.parametrize(
    "section",
    [
        "about_sfu",
        "identification",
        "position_summary",
        "duties",
        "decision_making",
        "problem_solving",
        "relationships",
        "qualifications",
        "edi_footer",
        "additional_context",
        "general",
    ],
)
def test_sfu_sections(section: str) -> None:
    checklist = JDChecklistSection(
        section=section,  # type: ignore[arg-type]
        label="l",
        status="ok",
    )
    assert checklist.section == section


def test_type_aliases_importable() -> None:
    # Exercise the Literal aliases as annotations so mypy --strict checks them.
    category: JDIssueCategory = "completeness"
    severity: JDIssueSeverity = "high"
    source: JDIssueSource = "rule"
    grade: JDGrade = "A"
    section: SFUSection = "duties"
    assert (category, severity, source, grade, section) == (
        "completeness",
        "high",
        "rule",
        "A",
        "duties",
    )

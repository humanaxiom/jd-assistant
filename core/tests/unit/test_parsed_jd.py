"""Unit tests for the ParsedJD contract (ported from hris `sfu_jd.py`).

Covers: round-trip (model_validate(model_dump())), the JSON null->[] list
coercion, enum/section coverage, required-vs-optional field behaviour, and the
presence-boolean defaults.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.jd_core.models.parsed_jd import (
    KnowledgeModifier,
    QualificationKind,
    SFUDuty,
    SFUEmployeeGroup,
    SFUJobDescription,
    SFUQualification,
    SFURelationships,
    SkillModifier,
)


def _full_jd() -> dict[str, object]:
    return {
        "title": "Manager, Financial Operations",
        "position_number": "E1234",
        "department": "Finance",
        "grade": "10",
        "employee_group": "apsa",
        "about_sfu_present": True,
        "position_summary": "Leads the financial operations team.",
        "duties": [
            {
                "action_verb": "Manages",
                "statement": "the financial operations team",
                "how_why": ["by setting priorities", "to ensure accuracy"],
            }
        ],
        "decision_making": ["Approves budgets up to $50k"],
        "problem_solving": ["Resolves reconciliation discrepancies"],
        "relationships": {
            "supervisory": "Supervises 3 analysts",
            "internal": ["Payroll", "Procurement"],
            "external": ["Auditors"],
        },
        "qualifications": [
            {"text": "Bachelor's degree in accounting", "kind": "education"},
            {
                "text": "Advanced Excel",
                "kind": "skill",
                "modifier": "advanced",
            },
        ],
        "territorial_acknowledgement_present": True,
        "employment_equity_present": True,
        "additional_context": "Hybrid work.",
    }


def test_full_round_trip() -> None:
    jd = SFUJobDescription.model_validate(_full_jd())
    assert SFUJobDescription.model_validate(jd.model_dump()) == jd


def test_duty_round_trip() -> None:
    duty = SFUDuty(action_verb="Leads", statement="the team", how_why=["daily"])
    assert SFUDuty.model_validate(duty.model_dump()) == duty


def test_qualification_round_trip() -> None:
    qual = SFUQualification(text="Excellent knowledge of GAAP", kind="knowledge")
    assert SFUQualification.model_validate(qual.model_dump()) == qual


# ---------- null -> [] coercion ----------


def test_jd_null_lists_coerced_to_empty() -> None:
    jd = SFUJobDescription.model_validate(
        {
            "title": "Analyst",
            "duties": None,
            "decision_making": None,
            "problem_solving": None,
            "qualifications": None,
        }
    )
    assert jd.duties == []
    assert jd.decision_making == []
    assert jd.problem_solving == []
    assert jd.qualifications == []


def test_duty_null_how_why_coerced() -> None:
    duty = SFUDuty.model_validate({"statement": "does things", "how_why": None})
    assert duty.how_why == []


def test_relationships_null_lists_coerced() -> None:
    rel = SFURelationships.model_validate({"internal": None, "external": None})
    assert rel.internal == []
    assert rel.external == []


# ---------- defaults ----------


def test_presence_booleans_default_false() -> None:
    jd = SFUJobDescription(title="Coordinator")
    assert jd.about_sfu_present is False
    assert jd.territorial_acknowledgement_present is False
    assert jd.employment_equity_present is False


def test_optional_fields_default_none_and_lists_empty() -> None:
    jd = SFUJobDescription(title="Coordinator")
    assert jd.position_number is None
    assert jd.department is None
    assert jd.employee_group is None
    assert jd.relationships is None
    assert jd.duties == []
    assert jd.qualifications == []


def test_qualification_defaults() -> None:
    qual = SFUQualification(text="Attention to detail")
    assert qual.kind == "ability"
    assert qual.modifier is None


def test_duty_action_verb_defaults_empty() -> None:
    duty = SFUDuty(statement="does the work")
    assert duty.action_verb == ""
    assert duty.how_why == []


# ---------- required / validation ----------


def test_title_is_required() -> None:
    with pytest.raises(ValidationError):
        SFUJobDescription.model_validate({})


def test_title_min_length_enforced() -> None:
    with pytest.raises(ValidationError):
        SFUJobDescription.model_validate({"title": ""})


def test_duty_statement_required_and_min_length() -> None:
    with pytest.raises(ValidationError):
        SFUDuty.model_validate({"statement": ""})


def test_qualification_text_min_length() -> None:
    with pytest.raises(ValidationError):
        SFUQualification.model_validate({"text": ""})


def test_extra_fields_ignored() -> None:
    jd = SFUJobDescription.model_validate({"title": "Analyst", "unknown": "x"})
    assert not hasattr(jd, "unknown")


# ---------- enum / section coverage ----------


@pytest.mark.parametrize("group", ["apsa", "apex", "poly", "cupe", "excluded"])
def test_employee_group_values(group: str) -> None:
    jd = SFUJobDescription(title="X", employee_group=group)  # type: ignore[arg-type]
    assert jd.employee_group == group


def test_invalid_employee_group_rejected() -> None:
    with pytest.raises(ValidationError):
        SFUJobDescription.model_validate({"title": "X", "employee_group": "faculty"})


@pytest.mark.parametrize(
    "kind",
    ["education", "experience", "knowledge", "skill", "ability", "security"],
)
def test_qualification_kinds(kind: str) -> None:
    qual = SFUQualification(text="requirement", kind=kind)  # type: ignore[arg-type]
    assert qual.kind == kind


def test_invalid_qualification_kind_rejected() -> None:
    with pytest.raises(ValidationError):
        SFUQualification.model_validate({"text": "x", "kind": "language"})


def test_ten_sections_present_on_model() -> None:
    # Sanity: the 10 SFU template sections all map to model fields.
    fields = set(SFUJobDescription.model_fields)
    for section_field in (
        "title",  # 1. identification
        "about_sfu_present",  # 2. about SFU
        "position_summary",  # 3. position summary
        "duties",  # 4. duties
        "decision_making",  # 5. impact of decision making
        "problem_solving",  # 6. problem solving
        "relationships",  # 7. relationships
        "qualifications",  # 8. qualifications
        "employment_equity_present",  # 9. boilerplate/footer
        "additional_context",  # 10. additional context
    ):
        assert section_field in fields


def test_type_aliases_importable() -> None:
    # The Literal aliases are part of the ported contract surface; exercise them
    # as annotations so mypy --strict validates the membership too.
    group: SFUEmployeeGroup = "apsa"
    know: KnowledgeModifier = "excellent"
    skill: SkillModifier = "advanced"
    kind: QualificationKind = "education"
    assert (group, know, skill, kind) == ("apsa", "excellent", "advanced", "education")

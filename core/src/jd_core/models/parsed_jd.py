"""Structured job description mirroring SFU's official APSA/APEX/POLY template
(`APSA_APEX_POLY_JD Template_20240530.docx`).

Ported near-verbatim from hris `packages/schemas/src/schemas/sfu_jd.py`
(reuse-map #1). This is the JD Bank's universal ParsedJD contract: the SFU
template's 10 sections in template order, with the Toolkit's knowledge/skills
modifiers. It is the input to the SFU-aware quality auditor and the harmonizer.

Scope: APSA/APEX/POLY (Hay-graded). CUPE uses a different template + the WJQ
instrument — `employee_group` keeps the two from cross-applying.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _null_to_empty(v: object) -> object:
    """Coerce a JSON ``null`` to ``[]`` — small local LLMs routinely emit
    ``null`` for an empty list field, which would otherwise fail validation."""
    return [] if v is None else v


SFUEmployeeGroup = Literal["apsa", "apex", "poly", "cupe", "excluded"]
# Toolkit knowledge modifiers (Qualifications §B). "none" = the "no modifier"
# case (the position only needs to *use a source to find* information).
KnowledgeModifier = Literal["excellent", "working", "none"]
# Toolkit skills modifiers (Qualifications §C).
SkillModifier = Literal["basic", "intermediate", "advanced", "expert"]
QualificationKind = Literal[
    "education", "experience", "knowledge", "skill", "ability", "security"
]


class SFUDuty(BaseModel):
    """One Duties & Responsibilities entry in the template's
    "ACTION VERB … WHAT *by* / how and why" shape."""

    model_config = ConfigDict(extra="ignore")

    action_verb: str = Field(default="", max_length=60)
    statement: str = Field(min_length=1, max_length=400)
    how_why: list[str] = Field(default_factory=list, max_length=12)

    _how_why_null = field_validator("how_why", mode="before")(_null_to_empty)


class SFUQualification(BaseModel):
    """One Qualifications entry. ``modifier`` carries the Toolkit modifier when
    present (knowledge: excellent/working/none; skill: basic/…/expert)."""

    model_config = ConfigDict(extra="ignore")

    text: str = Field(min_length=1, max_length=400)
    kind: QualificationKind = "ability"
    modifier: str | None = Field(default=None, max_length=20)


class SFURelationships(BaseModel):
    """The Relationships section: supervisory scope + internal/external
    connections."""

    model_config = ConfigDict(extra="ignore")

    supervisory: str | None = Field(default=None, max_length=600)
    internal: list[str] = Field(default_factory=list, max_length=30)
    external: list[str] = Field(default_factory=list, max_length=30)

    _rel_null = field_validator("internal", "external", mode="before")(_null_to_empty)


class SFUJobDescription(BaseModel):
    """The SFU template's 10 sections, in order. Extraction target for
    ``sfu_jd_extract_v1``; LLM-validated via ``LLMClient.chat_json``."""

    model_config = ConfigDict(extra="ignore")

    # 1. Identification
    title: str = Field(min_length=1, max_length=200)
    position_number: str | None = Field(default=None, max_length=50)
    department: str | None = Field(default=None, max_length=200)
    grade: str | None = Field(default=None, max_length=50)
    employee_group: SFUEmployeeGroup | None = None
    # 2. About SFU (boilerplate - presence only)
    about_sfu_present: bool = False
    # 3. Position Summary (template: 100-150 words)
    position_summary: str | None = Field(default=None, max_length=4000)
    # 4. Duties & Responsibilities (template: 3-5 major)
    duties: list[SFUDuty] = Field(default_factory=list, max_length=12)
    # 5. Impact of Decision Making (-> Hay Accountability)
    decision_making: list[str] = Field(default_factory=list, max_length=20)
    # 6. Problem Solving & Level of Supervision (-> Hay Problem-Solving)
    problem_solving: list[str] = Field(default_factory=list, max_length=20)
    # 7. Relationships
    relationships: SFURelationships | None = None
    # 8. Qualifications
    qualifications: list[SFUQualification] = Field(default_factory=list, max_length=40)
    # 9. Boilerplate (presence only)
    territorial_acknowledgement_present: bool = False
    employment_equity_present: bool = False
    # 10. Additional Contextual Information
    additional_context: str | None = Field(default=None, max_length=4000)

    _lists_null = field_validator(
        "duties", "decision_making", "problem_solving", "qualifications", mode="before"
    )(_null_to_empty)

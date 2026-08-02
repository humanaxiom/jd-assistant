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
#: Where a :class:`JobClassification` value came from — its trustworthiness follows.
GradeSource = Literal["parsed", "entered", "hris"]


class JobClassification(BaseModel):
    """The position's pay grade / classification, structured with provenance.

    Pay is set from this, and **each employee group has its OWN scale** (CUPE numeric
    pay grades; APSA/APEX/POLY their own), so ``scheme`` — the employee-group scale — is
    carried alongside the ``value``; a CUPE grade 8 is not an APSA grade 8. ``source``
    records where the grade came from, because it is **absent from most JDFN JD
    documents** (assigned post-authoring, held in the HRIS): ``parsed`` from the JD
    text, ``entered`` by an author/reviewer, or ``hris`` from an authoritative import.

    Advisory metadata — NOT a scored field and NOT a publish gate. ``value`` is a free
    string until HR ratifies each group's scale (then a validator can constrain it).
    This SUPERSEDES the legacy free-string ``SFUJobDescription.grade`` (parser noise).
    See ``docs/audit/data-state-and-grade-2026-08-01.md``.
    """

    model_config = ConfigDict(extra="ignore")

    scheme: str = Field(min_length=1, max_length=32)
    value: str = Field(min_length=1, max_length=50)
    source: GradeSource = "parsed"


class SFUDuty(BaseModel):
    """One Duties & Responsibilities entry in the template's
    "ACTION VERB … WHAT *by* / how and why" shape.

    ``frequency`` is populated only by the CUPE/WJQ template (Phase 3.4): the WJQ
    "MAJOR FUNCTIONS" section tags each duty with how often it is performed —
    ``(D)`` Daily / ``(W)`` Weekly / ``(M)`` Monthly / ``(S)`` Semester, either as a
    per-duty marker or as a group heading. It is **additive and optional**: the
    APSA/APEX/POLY (JDFN) template has no such tag, so every JDFN duty leaves it
    ``None``, and an existing v1 ``parsed`` JSONB (written before this field existed)
    deserializes unchanged (missing key -> default ``None``). The marker itself is
    stripped from :attr:`statement`; this field carries the meaning. Registered
    (HR-142)."""

    model_config = ConfigDict(extra="ignore")

    action_verb: str = Field(default="", max_length=60)
    statement: str = Field(min_length=1, max_length=400)
    how_why: list[str] = Field(default_factory=list, max_length=12)
    #: WJQ frequency of performance (``daily`` / ``weekly`` / ``monthly`` /
    #: ``semester``), or ``None`` for a JDFN duty. Additive; see the class docstring.
    frequency: str | None = Field(default=None, max_length=20)

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
    #: Structured pay grade / classification with provenance — supersedes the legacy
    #: free-string ``grade`` (extraction filled it with noise). ``None`` until captured
    #: (the common case for JDFN, whose grade lives in the HRIS). See JobClassification.
    classification: JobClassification | None = None
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

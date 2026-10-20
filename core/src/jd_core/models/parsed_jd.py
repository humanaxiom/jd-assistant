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

import datetime as dt
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SerializerFunctionWrapHandler,
    field_validator,
    model_serializer,
)


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


#: Who filled in Part 1 of a CUPE form ("Part 1 is being completed by: ☐ Employee
#: ☐ Evaluating Supervisor") — it decides how a re-evaluation is routed (CUPE 3338
#: Art. 17.03).
WJQCompletedBy = Literal["employee", "supervisor"]


class WJQRow(BaseModel):
    """One row of a CUPE form table: §8 contacts and §10 effort (item, duration,
    frequency), §11 locations (item, hours) and §11 exposures (item, frequency).

    The values are HR's own scale words as printed (``cupe_form.table_durations`` /
    ``table_frequencies``); the Builder checks them, the model just carries them."""

    model_config = ConfigDict(extra="ignore")

    item: str = Field(min_length=1, max_length=400)
    duration: str | None = Field(default=None, max_length=40)
    frequency: str | None = Field(default=None, max_length=40)
    hours: str | None = Field(default=None, max_length=40)


class WJQForm(BaseModel):
    """The parts of HR's CUPE "WJQ Custom — Part 1" form that the APSA-shaped model has
    no field for (Track J, PR J2). **Authored drafts only.**

    ⚠ The parser NEVER fills this — ``parser/wjq.py`` is unchanged, so no
    ``PARSER_VERSION`` move and no re-parse. A CUPE JD parsed from the archive has
    ``wjq_form is None``, and that is also how the clone transform knows a draft is
    pre-J2 (its knowledge / skill / ability kinds then fold into the one
    Occupational Skills list — Q9, option C).

    Why a block rather than more top-level fields: everything here is ONE form's
    structure, and the validators, the rewrite pass and the merge all read the top-level
    sections. Minor functions in particular are kept OUT of ``duties``, so the twelve-
    duty ceiling every pipeline relies on is untouched and nothing has to be merged and
    cut to fit it — the defect J2 removes (HR's own Dec-2024 sample has 11 + 3).

    The four checkbox sections hold HR's level LETTERS, A first, in the order HR prints
    the options (``cupe_form.checkbox_options``); the free text of those sections stays
    in ``additional_context`` under its heading, exactly where the parser keeps it.
    """

    model_config = ConfigDict(extra="ignore")

    # 1. Position identification (the author's half; HR's box is never modelled)
    current_classification: str | None = Field(default=None, max_length=100)
    supervisor_title: str | None = Field(default=None, max_length=200)
    date_completed: dt.date | None = None
    completed_by: WJQCompletedBy | None = None
    # 4. Minor functions (3. Major functions are `SFUJobDescription.duties`)
    minor_functions: list[SFUDuty] = Field(default_factory=list, max_length=20)
    # 5, 6, 7, 12 — the ticked levels
    level_of_independence: list[str] = Field(default_factory=list, max_length=5)
    training_exercised: list[str] = Field(default_factory=list, max_length=5)
    direction_exercised: list[str] = Field(default_factory=list, max_length=5)
    continuing_education: list[str] = Field(default_factory=list, max_length=5)
    # 8, 10, 11 — the tables. `contacts` carries each contact's duration / frequency;
    # WHICH contacts there are stays `relationships` (what the validator reads), and
    # the export matches the two by text, so a reviewer's edit of the contacts wins.
    contacts: list[WJQRow] = Field(default_factory=list, max_length=60)
    effort: list[WJQRow] = Field(default_factory=list, max_length=20)
    locations: list[WJQRow] = Field(default_factory=list, max_length=10)
    uncomfortable: list[WJQRow] = Field(default_factory=list, max_length=10)
    hazards: list[WJQRow] = Field(default_factory=list, max_length=10)
    # 13. Qualifications — the parts that are not a qualification line
    certification: list[str] = Field(default_factory=list, max_length=10)
    experience_years: int | None = Field(default=None, ge=0, le=60)
    #: ``True`` = "an equivalent combination … is acceptable"; ``False`` = "is not
    #: acceptable because:" (``equivalency_rationale``); ``None`` = not answered.
    equivalency_acceptable: bool | None = None
    equivalency_rationale: str | None = Field(default=None, max_length=1000)
    occupational_requirements: list[str] = Field(default_factory=list, max_length=20)

    _lists_null = field_validator(
        "minor_functions",
        "level_of_independence",
        "training_exercised",
        "direction_exercised",
        "continuing_education",
        "contacts",
        "effort",
        "locations",
        "uncomfortable",
        "hazards",
        "certification",
        "occupational_requirements",
        mode="before",
    )(_null_to_empty)


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
    #: The position this one reports to — its title and position # (Track J4). Asked
    #: by the Toolkit (Part 11.1, "supervisor title") and the JAQ ("Position # of
    #: Supervisor"); NOT on the 2024 APSA template, so the export prints them after the
    #: template's own header rows. Authored in the Builder only: the parser never fills
    #: them (no ``PARSER_VERSION`` change — a stored ``parsed`` row without the keys
    #: deserializes to ``None``, exactly what a fresh parse writes).
    supervisor_title: str | None = Field(default=None, max_length=200)
    supervisor_position_number: str | None = Field(default=None, max_length=50)
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
    #
    # ⚠ The ceiling is 20,000, NOT the 4,000 it shared with `position_summary`, because
    # for a CUPE/WJQ document this field carries the seven point-factor sections
    # verbatim — the whole point-factor half of that instrument. At 4,000, 81.4% of CUPE
    # JDs were truncated (0% of APSA), and because the cut falls in document order the
    # tail of the form disappeared.
    #
    # This is the CONTRACT ceiling — the outer bound of what the type permits. The
    # OPERATIVE cap the parser trims to is rulebook data
    # (`segmentation.additional_context_max_chars`, HR-200) and must stay under it; a
    # configured cap above this ceiling would turn a lossy parse into a parse *failure*.
    additional_context: str | None = Field(default=None, max_length=20000)
    # The CUPE form's own structure (Track J2) — authored CUPE drafts only; ``None`` for
    # every JDFN JD, every parsed document and every draft written before J2 (missing
    # key -> default), so existing ``content`` JSONB deserializes unchanged.
    wjq_form: WJQForm | None = None

    @model_serializer(mode="wrap")
    def _omit_absent_wjq_form(self, handler: SerializerFunctionWrapHandler) -> Any:
        """``wjq_form`` is left OUT of a dump when it is ``None`` — so every JDFN JD,
        every parsed document and every pre-J2 draft serializes byte-identically to
        before J2. The parser's golden fixtures pin exactly that (a parse output with a
        new ``"wjq_form": null`` key would be a changed parse in all but name), and a
        reviewer edit's "changed sections" diff would otherwise report a section that
        did not change. Missing key -> ``None`` on the way back in."""
        data = handler(self)
        if isinstance(data, dict) and data.get("wjq_form") is None:
            data.pop("wjq_form", None)
        return data

    _lists_null = field_validator(
        "duties", "decision_making", "problem_solving", "qualifications", mode="before"
    )(_null_to_empty)

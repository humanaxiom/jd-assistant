"""The structured input a guided JD-authoring flow collects (Phase 5.2).

:class:`ComposerAnswers` is what the guided question set (``composer_questions_
v1.yaml``) fills in and what :func:`~src.jd_bank.composer.assemble.assemble_jd`
turns into an :class:`~src.jd_core.models.parsed_jd.SFUJobDescription`. It is the
authoring-side contract: everything optional (a draft is filled incrementally),
duties and modified qualifications carried as small typed rows so the assembler
can place them in template order without re-parsing free text.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from src.jd_core.models.parsed_jd import SFUEmployeeGroup


class DutyAnswer(BaseModel):
    """One primary function as authored: an action verb, the statement, and an
    optional percentage-of-time allocation (the template's ``(60%)`` style)."""

    model_config = ConfigDict(extra="forbid")

    action_verb: str = Field(default="", max_length=60)
    statement: str = Field(min_length=1, max_length=400)
    #: Percentage of the role's time (0-100), or ``None`` if not yet allocated. The
    #: assembler renders it into the duty as ``(NN%)`` (Part 10.1) so the validator's
    #: allocation gate can read it.
    allocation: int | None = Field(default=None, ge=0, le=100)


class ModifiedQual(BaseModel):
    """A knowledge or skill qualification carrying its Toolkit modifier
    (knowledge: excellent/working; skill: basic/intermediate/advanced/expert)."""

    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=400)
    modifier: str | None = Field(default=None, max_length=20)


class ComposerAnswers(BaseModel):
    """Everything the guided flow collects for one JDFN draft. All optional — the
    Builder validates live as the author fills it in (Phase 5.1)."""

    model_config = ConfigDict(extra="forbid")

    # 1. Identification
    title: str = Field(default="", max_length=200)
    department: str | None = Field(default=None, max_length=200)
    employee_group: SFUEmployeeGroup | None = None
    #: The pay grade / classification VALUE the author enters (e.g. "8"). Its scheme is
    #: the ``employee_group`` scale; the assembler builds a ``JobClassification`` with
    #: ``source="entered"``. Blank -> no classification (grade lives in the HRIS for
    #: most JDFN roles — see docs/decisions/grade-scales.md).
    grade: str | None = Field(default=None, max_length=50)
    # 3. Position Summary
    position_summary: str | None = Field(default=None, max_length=4000)
    # 4. Duties
    duties: list[DutyAnswer] = Field(default_factory=list, max_length=12)
    # 5. Decision Making
    decision_making: list[str] = Field(default_factory=list, max_length=20)
    # 6. Problem Solving
    problem_solving: list[str] = Field(default_factory=list, max_length=20)
    # 7. Relationships
    supervisory: str | None = Field(default=None, max_length=600)
    internal: list[str] = Field(default_factory=list, max_length=30)
    external: list[str] = Field(default_factory=list, max_length=30)
    # 8. Qualifications — kept split by kind so the assembler can honour the
    #    Education -> Experience -> Knowledge -> Skills -> Abilities order (Part 5).
    education: list[str] = Field(default_factory=list, max_length=10)
    experience: list[str] = Field(default_factory=list, max_length=10)
    knowledge: list[ModifiedQual] = Field(default_factory=list, max_length=20)
    skills: list[ModifiedQual] = Field(default_factory=list, max_length=20)
    abilities: list[str] = Field(default_factory=list, max_length=20)
    # 2./9. SFU mandated boilerplate (About-SFU + territorial ack + EE footer) — the
    #       do-not-edit blocks the Builder inserts; required for approval.
    include_sfu_boilerplate: bool = True
    # 10. Additional Contextual Information (optional; dropped if blank)
    additional_context: str | None = Field(default=None, max_length=4000)
    #: The harmonized role this draft was CLONED from, when it was (Phase 5.9). Not
    #: content — provenance the Builder carries so the near-duplicate authoring guard
    #: can exclude it (:func:`~src.jd_bank.composer.duplicates.find_related_roles`'s
    #: ``exclude_cluster_id``): cloning a role must not immediately warn you that you
    #: duplicated the very role you cloned. Additive and optional, so every
    #: ``answers_json`` written before it existed still validates under
    #: ``extra="forbid"``, and :func:`~src.jd_bank.composer.assemble.assemble_jd`
    #: ignores it — it never reaches the JD, the validator or the review queue.
    cloned_from_cluster_id: UUID | None = None

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

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.jd_core.models.parsed_jd import SFUDuty, SFUEmployeeGroup, SFUJobDescription

#: ``SFUJobDescription.decision_making``' ceiling (problem_solving shares it).
_BULLETS_CEILING: int = next(
    int(meta.max_length)
    for meta in SFUJobDescription.model_fields["decision_making"].metadata
    if getattr(meta, "max_length", None) is not None
)

#: ``SFUJobDescription.duties``' contract ceiling, read off the model (parser v9).
_DUTIES_CEILING: int = next(
    int(meta.max_length)
    for meta in SFUJobDescription.model_fields["duties"].metadata
    if getattr(meta, "max_length", None) is not None
)

#: ``SFUDuty.how_why``'s contract ceiling, read off the model (parser v9).
_HOW_WHY_CEILING: int = next(
    int(meta.max_length)
    for meta in SFUDuty.model_fields["how_why"].metadata
    if getattr(meta, "max_length", None) is not None
)


class DutyAnswer(BaseModel):
    """One primary function as authored: an action verb, the statement, and an
    optional percentage-of-time allocation (the template's ``(60%)`` style)."""

    model_config = ConfigDict(extra="forbid")

    action_verb: str = Field(default="", max_length=60)
    #: Held at `SFUDuty.statement`'s own ceiling (parser v9). At 400 it was narrower
    #: than the JD it is cloned FROM: a v9 draft can carry a 1,200-character duty
    #: (HR-261), and `jd_to_answers` would raise instead of opening the Builder.
    statement: str = Field(min_length=1, max_length=4000)
    #: Percentage of the role's time (0-100), or ``None`` if not yet allocated. The
    #: assembler renders it into the duty as ``(NN%)`` (Part 10.1) so the validator's
    #: allocation gate can read it.
    allocation: int | None = Field(default=None, ge=0, le=100)


class JDFNDutyAnswer(DutyAnswer):
    """A JDFN (APSA/APEX/Poly) duty: the template's "ACTION VERB… WHAT by" statement
    plus its "How and why" sub-bullets (Track J4) — ``SFUDuty.how_why``, which the
    Builder could not fill before, so ``SFU-STRUCT-HOW-WHY`` could only be met by
    cramming the clauses into the statement.

    A subclass, not a new field on :class:`DutyAnswer`, because the WJQ form shares
    that row and its assembler has nowhere to put a clause list: a field it silently
    ignored is exactly the drop this track exists to remove. ``answers_json`` written
    before J4 has no ``how_why`` key and still validates (defaults to ``[]``)."""

    #: The model's own ceiling is the hard bound; the OPERATIVE limit is the parser's
    #: (`segmentation.duty_how_why_max_count`, HR-265) — checked below, never restated.
    #: It was a constant 12, and 1,107 duties in 992 documents of the v9 re-parse carry
    #: more (max 36), so cloning those roles into the Builder RAISED. A Builder that can
    #: hold less than the parser reads is a Builder that refuses the archive.
    how_why: list[str] = Field(default_factory=list, max_length=_HOW_WHY_CEILING)

    @field_validator("how_why")
    @classmethod
    def _within_the_parser_s_limit(cls, value: list[str]) -> list[str]:
        from src.jd_core.rules import get_rules  # noqa: PLC0415 — rules import models

        limit = get_rules().segmentation.duty_how_why_max_count
        if len(value) > limit:
            raise ValueError(
                f"{len(value)} how/why points on one duty; the limit is {limit} "
                "(segmentation.duty_how_why_max_count, HR-265)"
            )
        return value


class ModifiedQual(BaseModel):
    """A knowledge or skill qualification carrying its Toolkit modifier
    (knowledge: excellent/working; skill: basic/intermediate/advanced/expert)."""

    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=400)
    modifier: str | None = Field(default=None, max_length=20)


class AnswerContract(BaseModel):
    """What EVERY form's answer contract carries, whatever SFU instrument it models.

    One field so far, and it is here rather than duplicated because the Builder's
    form-blind half reads it (Phase E): the near-duplicate authoring guard needs to know
    which role a draft was cloned from in order to exclude it, and that code must not
    have to ask which form it is holding. A second form declaring its own copy would
    type-check and then quietly diverge.
    """

    model_config = ConfigDict(extra="forbid")

    #: The harmonized role this draft was CLONED from, when it was (Phase 5.9). Not
    #: content — provenance the Builder carries so the near-duplicate authoring guard
    #: can exclude it (:func:`~src.jd_bank.composer.duplicates.find_related_roles`'s
    #: ``exclude_cluster_id``): cloning a role must not immediately warn you that you
    #: duplicated the very role you cloned. Additive and optional, so every
    #: ``answers_json`` written before it existed still validates under
    #: ``extra="forbid"``, and the assemblers ignore it — it never reaches the JD, the
    #: validator or the review queue.
    cloned_from_cluster_id: UUID | None = None


class ComposerAnswers(AnswerContract):
    """Everything the guided flow collects for one JDFN draft. All optional — the
    Builder validates live as the author fills it in (Phase 5.1)."""

    model_config = ConfigDict(extra="forbid")

    # 1. Identification
    title: str = Field(default="", max_length=200)
    #: The template header's "Position #:" (Track J4).
    position_number: str | None = Field(default=None, max_length=50)
    department: str | None = Field(default=None, max_length=200)
    employee_group: SFUEmployeeGroup | None = None
    #: The position this one reports to (Toolkit Part 11.1; the JAQ). Track J4.
    supervisor_title: str | None = Field(default=None, max_length=200)
    supervisor_position_number: str | None = Field(default=None, max_length=50)
    #: The pay grade / classification VALUE the author enters (e.g. "8"). Its scheme is
    #: the ``employee_group`` scale; the assembler builds a ``JobClassification`` with
    #: ``source="entered"``. Blank -> no classification (grade lives in the HRIS for
    #: most JDFN roles — see docs/decisions/grade-scales.md).
    grade: str | None = Field(default=None, max_length=50)
    # 3. Position Summary
    position_summary: str | None = Field(default=None, max_length=4000)
    # 4. Duties
    #: Held to what the parser keeps (`segmentation.duty_max_count`, HR-262), checked
    #: below, under the model's ceiling. It was a constant 12, and the Builder also
    #: clones RAW archive documents — ~1,470 v9 APSA/APEX/POLY parses carry more, so
    #: cloning them raised. More than five still draws SFU-STRUCT-DUTIES-TOO-MANY
    #: (HR-022): the Builder holds the document, the validator judges it.
    duties: list[JDFNDutyAnswer] = Field(
        default_factory=list, max_length=_DUTIES_CEILING
    )

    @field_validator("duties")
    @classmethod
    def _duties_within_the_parser_s_limit(
        cls, value: list[JDFNDutyAnswer]
    ) -> list[JDFNDutyAnswer]:
        from src.jd_core.rules import get_rules  # noqa: PLC0415 — rules import models

        limit = get_rules().segmentation.duty_max_count
        if len(value) > limit:
            raise ValueError(
                f"{len(value)} duties; the limit is {limit} "
                "(segmentation.duty_max_count, HR-262)"
            )
        return value

    # 5. Decision Making / 6. Problem Solving — held to the MODEL's ceiling (60 since
    # parser v9; it was a constant 20 on both sides). Not the parser's HR-268 cap: a
    # role's draft is a UNION over its members, which the merge cuts at the model
    # ceiling, so a Builder row narrower than the model would refuse to clone a draft
    # the Bank itself wrote.
    decision_making: list[str] = Field(
        default_factory=list, max_length=_BULLETS_CEILING
    )
    problem_solving: list[str] = Field(
        default_factory=list, max_length=_BULLETS_CEILING
    )
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
    #: E. Security credentials (Track J4). The criminal record check is a yes/no — the
    #: sentence is HR's (``apsa_form.security_check_sentence``, HR-257), never typed.
    criminal_record_check: bool = False
    #: Any OTHER security credential, verbatim — what a cloned role carried that is not
    #: the rulebook's sentence. Pre-J4 the clone transform dropped these outright.
    security: list[str] = Field(default_factory=list, max_length=10)
    # 2./9. SFU mandated boilerplate (About-SFU + territorial ack + EE footer) — the
    #       do-not-edit blocks the Builder inserts; required for approval.
    include_sfu_boilerplate: bool = True
    # 10. Additional Contextual Information (optional; dropped if blank)
    additional_context: str | None = Field(default=None, max_length=4000)

    @field_validator("duties", mode="before")
    @classmethod
    def _plain_duties_are_jdfn_duties(cls, value: object) -> object:
        """A plain :class:`DutyAnswer` (no how/why) is a valid JDFN duty — accept it,
        so every caller that built one before J4 keeps working unchanged."""
        if isinstance(value, list):
            return [
                (
                    item.model_dump()
                    if isinstance(item, DutyAnswer)
                    and not isinstance(item, JDFNDutyAnswer)
                    else item
                )
                for item in value
            ]
        return value

"""Assemble guided-authoring answers into an SFU JD draft (Phase 5.2).

:func:`assemble_jd` is the deterministic bridge from what the guided flow collects
(:class:`~src.jd_bank.composer.answers.ComposerAnswers`) to the JD contract
(:class:`~src.jd_core.models.parsed_jd.SFUJobDescription`) the validator, live
panel (5.1) and review queue speak. Pure — no I/O, no LLM, no DB; same answers ->
same draft.

Two Toolkit rules are enforced here, in the structure rather than in prose:

* **KSA order** (Part 5): qualifications are emitted Education -> Experience ->
  Knowledge -> Skills -> Abilities, whatever order the answers arrived in, so the
  draft never trips ``SFU-APPROVE-KSA-ORDER`` on assembly.
* **Percentage allocations** (Part 10.1): a duty's allocation is rendered into its
  statement as ``(NN%)``, the form the validator's allocation gate reads.

A sparse answer set assembles a partial draft (missing sections simply empty) —
the live panel then shows what is still to author (5.1). Nothing here approves or
publishes (NN #1); the output is an explicit draft.
"""

from __future__ import annotations

from src.jd_bank.composer.answers import ComposerAnswers, DutyAnswer, ModifiedQual
from src.jd_core.models.parsed_jd import (
    QualificationKind,
    SFUDuty,
    SFUJobDescription,
    SFUQualification,
    SFURelationships,
)


def _duty(answer: DutyAnswer) -> SFUDuty:
    statement = answer.statement.strip()
    if answer.allocation is not None:
        statement = f"{statement} ({answer.allocation}%)"
    return SFUDuty(action_verb=answer.action_verb.strip(), statement=statement)


def _qualifications(answers: ComposerAnswers) -> list[SFUQualification]:
    """Every qualification, in the Toolkit's Education -> Experience -> Knowledge ->
    Skills -> Abilities order — built by emitting the kinds in that fixed order."""
    quals: list[SFUQualification] = []
    quals += [
        SFUQualification(text=t.strip(), kind="education")
        for t in answers.education
        if t.strip()
    ]
    quals += [
        SFUQualification(text=t.strip(), kind="experience")
        for t in answers.experience
        if t.strip()
    ]
    quals += [_modified(q, "knowledge") for q in answers.knowledge if q.text.strip()]
    quals += [_modified(q, "skill") for q in answers.skills if q.text.strip()]
    quals += [
        SFUQualification(text=t.strip(), kind="ability")
        for t in answers.abilities
        if t.strip()
    ]
    return quals


def _modified(qual: ModifiedQual, kind: QualificationKind) -> SFUQualification:
    modifier = (qual.modifier or "").strip() or None
    return SFUQualification(text=qual.text.strip(), kind=kind, modifier=modifier)


def _relationships(answers: ComposerAnswers) -> SFURelationships | None:
    supervisory = (answers.supervisory or "").strip() or None
    internal = [c.strip() for c in answers.internal if c.strip()]
    external = [c.strip() for c in answers.external if c.strip()]
    if not (supervisory or internal or external):
        return None
    return SFURelationships(
        supervisory=supervisory, internal=internal, external=external
    )


def assemble_jd(answers: ComposerAnswers) -> SFUJobDescription:
    """Turn guided-authoring answers into an SFU JDFN draft (template order, KSA
    order, allocations rendered). Pure and deterministic."""
    boilerplate = answers.include_sfu_boilerplate
    return SFUJobDescription(
        title=answers.title.strip() or "Untitled role",
        department=(answers.department or "").strip() or None,
        employee_group=answers.employee_group,
        about_sfu_present=boilerplate,
        position_summary=(answers.position_summary or "").strip() or None,
        duties=[_duty(d) for d in answers.duties],
        decision_making=[d.strip() for d in answers.decision_making if d.strip()],
        problem_solving=[p.strip() for p in answers.problem_solving if p.strip()],
        relationships=_relationships(answers),
        qualifications=_qualifications(answers),
        territorial_acknowledgement_present=boilerplate,
        employment_equity_present=boilerplate,
        additional_context=(answers.additional_context or "").strip() or None,
    )

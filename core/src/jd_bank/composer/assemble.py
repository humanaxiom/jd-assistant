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
from src.jd_core.rules import Rules, get_rules

#: SFURelationships.supervisory's own max length, read from the model so the header
#: overflow guard below can never drift from the schema it must not violate.
_SUPERVISORY_MAX: int = next(
    meta.max_length
    for meta in SFURelationships.model_fields["supervisory"].metadata
    if getattr(meta, "max_length", None) is not None
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


def _standard_relationships_header(rules: Rules) -> str:
    """SFU's mandated Relationships opener (HR-056), cased into a sentence from the
    rulebook marker — the composer inserts the SAME phrase the validator scans for
    (``SFU-GATE-REL-HEADER``), so it comes from the rulebook, not a hardcoded string."""
    marker = rules.markers.relationships_header
    return f"{marker[0].upper()}{marker[1:]}."


def _has_header(supervisory: str | None, header: str) -> bool:
    """Does the relationships prose already open with the standard header? Keeps the
    insert idempotent — a cloned JD that already carries it is not double-prefixed.
    Matches case-insensitively on the header's phrase (its trailing period aside),
    the same fold the gate applies."""
    if not supervisory:
        return False
    return header.rstrip(".").lower() in supervisory.lower()


def _relationships(
    answers: ComposerAnswers, *, header: str | None
) -> SFURelationships | None:
    supervisory = (answers.supervisory or "").strip() or None
    internal = [c.strip() for c in answers.internal if c.strip()]
    external = [c.strip() for c in answers.external if c.strip()]
    if header is not None and not _has_header(supervisory, header):
        # Open the Relationships section with SFU's mandated header (HR-056) so a
        # composed JD can satisfy SFU-GATE-REL-HEADER — the author never types
        # boilerplate. IDEMPOTENT: a cloned JD whose supervisory already opens with the
        # header is left as-is (no double insert). Bounded to the field limit so a long
        # supervisory answer + the ~54-char header can't overflow the model (the
        # author's text is kept whole; only the theoretical overflow tail is trimmed).
        supervisory = f"{header} {supervisory}" if supervisory else header
        supervisory = supervisory[:_SUPERVISORY_MAX]
    if not (supervisory or internal or external):
        return None
    return SFURelationships(
        supervisory=supervisory, internal=internal, external=external
    )


def assemble_jd(
    answers: ComposerAnswers, *, rules: Rules | None = None
) -> SFUJobDescription:
    """Turn guided-authoring answers into an SFU JDFN draft (template order, KSA
    order, allocations rendered). Pure and deterministic given ``rules`` (defaults to
    the shipped rulebook, like :func:`~src.jd_bank.composer.assess_draft`), which is
    read only for the mandated Relationships-header boilerplate (HR-056)."""
    rulebook = rules if rules is not None else get_rules()
    boilerplate = answers.include_sfu_boilerplate
    # SFU's mandated boilerplate: About-SFU / territorial / EE are presence booleans
    # the gates read directly; the Relationships header is checked IN THE TEXT, so it
    # must be inserted here — else a composed JD trips SFU-GATE-REL-HEADER unfixably.
    rel_header = _standard_relationships_header(rulebook) if boilerplate else None
    return SFUJobDescription(
        title=answers.title.strip() or "Untitled role",
        department=(answers.department or "").strip() or None,
        employee_group=answers.employee_group,
        about_sfu_present=boilerplate,
        position_summary=(answers.position_summary or "").strip() or None,
        duties=[_duty(d) for d in answers.duties],
        decision_making=[d.strip() for d in answers.decision_making if d.strip()],
        problem_solving=[p.strip() for p in answers.problem_solving if p.strip()],
        relationships=_relationships(answers, header=rel_header),
        qualifications=_qualifications(answers),
        territorial_acknowledgement_present=boilerplate,
        employment_equity_present=boilerplate,
        additional_context=(answers.additional_context or "").strip() or None,
    )

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
    JobClassification,
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


def _classification(answers: ComposerAnswers) -> JobClassification | None:
    """The author-entered grade as a structured classification, or ``None`` when blank.
    The scheme is the ``employee_group`` scale (``"unknown"`` if unset); ``source`` is
    ``"entered"`` — the author is the authority for a composed draft's grade."""
    value = (answers.grade or "").strip()
    if not value:
        return None
    return JobClassification(
        scheme=answers.employee_group or "unknown", value=value, source="entered"
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
        classification=_classification(answers),
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


# --- the clone transform: an existing JD back into JDFN answers ----------------------
#
# Moved here from `search.py` in Phase E. It is the INVERSE of `assemble_jd`, so it
# belongs beside it — and, concretely, the form registry needs it: `forms.py` is
# declarations, and having it import a 700-line service module (with its DB and Neo4j
# dependencies) to reach one pure function was both a circular import and the wrong
# direction.


def jd_to_answers(jd: SFUJobDescription) -> ComposerAnswers:
    """Turn an existing JD back into guided-authoring answers, so the Builder can be
    pre-filled from it (the inverse of :func:`assemble_jd`).

    Qualifications are split back out by kind into the answer fields; ``security``
    qualifications have no Builder field and are dropped (the guided flow does not
    collect them — a v1 limitation, recorded). The SFU boilerplate flag is set iff the
    source carries all three mandated presence booleans.
    """
    rel = jd.relationships
    return ComposerAnswers(
        title=jd.title,
        department=jd.department,
        employee_group=jd.employee_group,
        grade=jd.classification.value if jd.classification is not None else None,
        position_summary=jd.position_summary,
        duties=[
            DutyAnswer(action_verb=d.action_verb, statement=d.statement)
            for d in jd.duties
        ],
        decision_making=list(jd.decision_making),
        problem_solving=list(jd.problem_solving),
        supervisory=rel.supervisory if rel is not None else None,
        internal=list(rel.internal) if rel is not None else [],
        external=list(rel.external) if rel is not None else [],
        education=[q.text for q in jd.qualifications if q.kind == "education"],
        experience=[q.text for q in jd.qualifications if q.kind == "experience"],
        knowledge=[
            ModifiedQual(text=q.text, modifier=q.modifier)
            for q in jd.qualifications
            if q.kind == "knowledge"
        ],
        skills=[
            ModifiedQual(text=q.text, modifier=q.modifier)
            for q in jd.qualifications
            if q.kind == "skill"
        ],
        abilities=[q.text for q in jd.qualifications if q.kind == "ability"],
        include_sfu_boilerplate=(
            jd.about_sfu_present
            and jd.territorial_acknowledgement_present
            and jd.employment_equity_present
        ),
        additional_context=jd.additional_context,
    )

"""Assemble CUPE (WJQ) answers into an SFU JD draft — Phase E.

:func:`assemble_wjq_jd` is the WJQ counterpart of
:func:`~src.jd_bank.composer.assemble.assemble_jd`: the deterministic bridge from what
the WJQ guided flow collects to the :class:`~src.jd_core.models.parsed_jd.
SFUJobDescription` contract every downstream service already speaks. Pure — no I/O, no
LLM, no DB.

**It is written against the PARSER, not against the JDFN assembler.** ``parser/wjq.py``
turns a real CUPE questionnaire into an ``SFUJobDescription`` a particular way; this
turns authored answers into one *the same* way, so an authored CUPE JD and a parsed one
are the same shape. Three consequences, each of which is why some JDFN behaviour is
deliberately absent here:

* **The point-factor sections go to ``additional_context`` under their own headings** —
  the rulebook's ``wjq.section_headings`` vocabulary, so the text this writes is text
  the parser would read back. Not ``decision_making`` / ``problem_solving``: the WJQ has
  no Hay Accountability or Problem-Solving prose, and ``wjq.yaml`` records that
  force-mapping IMPACT OF ERRORS onto ``decision_making`` would feed the Hay signals a
  bogus input. Empty is honest.
* **No SFU boilerplate is asserted.** The JDFN assembler sets ``about_sfu_present`` /
  ``territorial_acknowledgement_present`` / ``employment_equity_present`` and inserts
  the mandated Relationships header. The WJQ form has none of those blocks — the
  measured fact behind HR-201 — so asserting them would state something untrue about the
  document, in exactly the fields a reviewer takes at face value (the same correction
  Phase D made to the rewrite pass). It costs no score either: ``applies_to`` (Phase B)
  withholds all four rules from the WJQ.
* **``employee_group`` is fixed to ``cupe``**, not asked. It is what makes the draft a
  WJQ document to ``template_of`` — and therefore what makes the validator judge it by
  the WJQ rules (Phase B) and numbers (Phase C) with no other wiring. Letting an author
  set it would let them silently change which bar their own draft is scored against.

Nothing here approves or publishes (NN #1); the output is an explicit draft.
"""

from __future__ import annotations

from src.jd_bank.composer.answers import DutyAnswer, ModifiedQual
from src.jd_bank.composer.wjq_answers import WJQ_CONTEXT_TARGETS, WJQAnswers
from src.jd_core.models.parsed_jd import (
    JobClassification,
    QualificationKind,
    SFUDuty,
    SFUJobDescription,
    SFUQualification,
    SFURelationships,
)
from src.jd_core.models.quality import WJQ_EMPLOYEE_GROUP
from src.jd_core.parser.segmenter import _MAX_DUTIES
from src.jd_core.rules import Rules, WjqSection, get_rules

__all__ = ["assemble_wjq_jd", "wjq_answers_from_jd"]

#: ``additional_context``'s own ceiling, read off the model so the block builder below
#: cannot write a draft the contract refuses. (HR-200 raised the PARSER's cap to 16,000
#: after 81.4% of CUPE JDs were found stored truncated; this is the model's field limit,
#: a different number for a different reason, and reading it beats restating it.)
_CONTEXT_MAX: int = next(
    meta.max_length
    for meta in SFUJobDescription.model_fields["additional_context"].metadata
    if getattr(meta, "max_length", None) is not None
)

#: The model's own duty ceiling. Imported from the PARSER rather than restated, because
#: this assembler's whole contract is "produce what the parser would produce": a real
#: CUPE questionnaire with more than twelve functions is truncated there
#: (``parser/wjq._structure_duties``, majors first), so an authored one must be too. If
#: that cap ever moves, both sides move together or the round trip stops holding.
_MAX_DUTIES_TOTAL: int = _MAX_DUTIES


def _duty(answer: DutyAnswer) -> SFUDuty:
    """One authored function. Allocation is rendered as ``(NN%)`` exactly as the JDFN
    assembler does — ``SFU-GATE-DUTY-PCT`` reads that form, and although the gate is
    withheld from the WJQ today (Phase B), writing the number in a shape the validator
    would not recognise would be a trap for whoever un-withholds it."""
    statement = answer.statement.strip()
    if answer.allocation is not None:
        statement = f"{statement} ({answer.allocation}%)"
    return SFUDuty(action_verb=answer.action_verb.strip(), statement=statement)


def _modified(qual: ModifiedQual, kind: QualificationKind) -> SFUQualification:
    modifier = (qual.modifier or "").strip() or None
    return SFUQualification(text=qual.text.strip(), kind=kind, modifier=modifier)


def _qualifications(answers: WJQAnswers) -> list[SFUQualification]:
    """Education -> Experience -> Knowledge -> Skills -> Abilities, the Toolkit's KSA
    order. Kept even though ``SFU-APPROVE-KSA-ORDER`` is JDFN-only: the order is how a
    reader expects to find them, and emitting them in answer-arrival order instead would
    make an authored CUPE JD read differently from a parsed one for no reason."""
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


def _relationships(answers: WJQAnswers) -> SFURelationships | None:
    """The form's INTERNAL AND EXTERNAL CONTACTS section.

    ``supervisory`` stays ``None`` and SFU's mandated Relationships header is NOT
    inserted: the header exists to satisfy ``SFU-GATE-REL-HEADER``, which is one of the
    seven rules Phase B withholds from the WJQ *because the form has no Relationships
    section to head*. Writing the JDFN's header onto a CUPE contacts list would put
    boilerplate from another form into a document that never asked for it.
    """
    internal = [c.strip() for c in answers.internal if c.strip()]
    external = [c.strip() for c in answers.external if c.strip()]
    if not (internal or external):
        return None
    return SFURelationships(supervisory=None, internal=internal, external=external)


def _classification(answers: WJQAnswers) -> JobClassification | None:
    """The author-entered CUPE grade. ``scheme`` is ``cupe`` — the WJQ's identification
    block prints "Classification & Grade Approved", so unlike most JDFN roles the value
    is on the form in front of the author rather than only in the HRIS."""
    value = (answers.grade or "").strip()
    if not value:
        return None
    return JobClassification(scheme=WJQ_EMPLOYEE_GROUP, value=value, source="entered")


def _additional_context(answers: WJQAnswers, rules: Rules) -> str | None:
    """The point-factor sections, each under the heading the PARSER matches.

    The heading text comes from ``wjq.section_headings`` — the first (canonical) variant
    of each — so this writes what ``parser/wjq.py`` reads. That is the round trip: an
    authored CUPE JD, exported and re-ingested, lands its point-factor content back in
    the same sections it was authored into.
    """
    headings = rules.wjq.section_headings
    blocks: list[str] = []
    for target in WJQ_CONTEXT_TARGETS:
        body = (getattr(answers, target) or "").strip()
        if not body:
            continue
        heading = headings[target][0]
        blocks.append(f"{heading}\n{body}")
    if not blocks:
        return None
    return "\n\n".join(blocks)[:_CONTEXT_MAX]


def assemble_wjq_jd(
    answers: WJQAnswers, *, rules: Rules | None = None
) -> SFUJobDescription:
    """Turn WJQ guided-authoring answers into a CUPE draft.

    Pure and deterministic given ``rules`` (defaults to the shipped rulebook, like the
    JDFN assembler), which is read only for the WJQ heading vocabulary.

    Major and minor functions both assemble into ``duties`` — that is where the parser
    puts them and where the validator reads them from — **majors first, then truncated
    at the model's twelve**, which is precisely what ``parser/wjq._structure_duties``
    does to a real questionnaire that overflows. The two forms can together carry 24
    answers against a 12-duty model, so something must give; matching the parser means
    an authored CUPE JD and a parsed one drop the same functions in the same order,
    rather than the Builder inventing a second truncation rule.
    """
    rulebook = rules if rules is not None else get_rules()
    duties = [_duty(d) for d in (*answers.major_functions, *answers.minor_functions)]
    duties = duties[:_MAX_DUTIES_TOTAL]
    return SFUJobDescription(
        title=answers.title.strip() or "Untitled role",
        department=(answers.department or "").strip() or None,
        position_number=(answers.position_number or "").strip() or None,
        classification=_classification(answers),
        # Fixed, never asked — this is what makes it a WJQ document to `template_of`,
        # and therefore what selects the bar it is judged against.
        employee_group=WJQ_EMPLOYEE_GROUP,
        about_sfu_present=False,
        position_summary=(answers.position_summary or "").strip() or None,
        duties=duties,
        decision_making=[],
        problem_solving=[],
        relationships=_relationships(answers),
        qualifications=_qualifications(answers),
        territorial_acknowledgement_present=False,
        employment_equity_present=False,
        additional_context=_additional_context(answers, rulebook),
    )


# --- the clone transform: a CUPE JD back into WJQ answers -----------------------------


def _split_context_blocks(context: str | None, rules: Rules) -> dict[WjqSection, str]:
    """Read ``additional_context`` back into its point-factor sections.

    The exact inverse of :func:`_additional_context`, and it is what makes cloning a
    CUPE role possible: the assembler writes each block under the heading the parser
    matches, so the clone can find them again by the SAME heading vocabulary. A block
    whose heading is not recognised is left where it is (the tail of the preceding
    section) rather than dropped — a cloned role's text must never vanish because a
    heading moved.

    ⚠ Matches on the CANONICAL heading only (``section_headings[...][0]``), because that
    is the one the assembler writes. A JD parsed from a real ``.doc`` may carry a
    different heading VARIANT, in which case its context arrives here as one unsplit
    block and lands in the first section — visible to the author, editable, and not
    silently lost. Splitting a parsed document perfectly is the parser's job, not this
    function's; the round trip this guarantees is Builder → JD → Builder.

    🔴 **That last paragraph described an intention, not the code, until 2026-08-19**
    (P0-2). The walk started with no current section and kept a line only once a
    canonical heading had been seen, so anything BEFORE the first heading was dropped —
    and a context with no recognised heading at all was dropped entirely. It is
    reachable: ``template_of`` routes on ``employee_group == "cupe"`` alone, so a JDFN
    document that merely mentions CUPE clones through here carrying ordinary prose. The
    preamble now opens the first section, which is what the docstring always claimed.
    """
    if not context:
        return {}
    headings = rules.wjq.section_headings
    canonical = {headings[target][0]: target for target in WJQ_CONTEXT_TARGETS}

    blocks: dict[WjqSection, list[str]] = {}
    # Text before any recognised heading belongs to the first section rather than to
    # nowhere. Assigned as the starting section rather than buffered separately so the
    # ordinary case — context that OPENS with that heading — is unchanged: the heading
    # line re-selects the same target and `setdefault` keeps the (empty) list.
    current: WjqSection = WJQ_CONTEXT_TARGETS[0]
    for line in context.splitlines():
        stripped = line.strip()
        if stripped in canonical:
            current = canonical[stripped]
            blocks.setdefault(current, [])
            continue
        blocks.setdefault(current, []).append(line)
    return {
        target: "\n".join(lines).strip()
        for target, lines in blocks.items()
        if "\n".join(lines).strip()
    }


def wjq_answers_from_jd(
    jd: SFUJobDescription, *, rules: Rules | None = None
) -> WJQAnswers:
    """A CUPE JD as WJQ guided-authoring answers — the clone transform (Phase E).

    ⚠ **Every duty comes back as a MAJOR function.** The WJQ's major/minor split is a
    property of the FORM, and the assembler — like the parser — merges both into one
    ``duties`` list, so by the time a JD exists the distinction is gone. Guessing a
    split (say, by position) would put the author's minor functions somewhere they did
    not choose; putting them all in the majors keeps every duty, in order, where the
    author can move any of them down. **Nothing is dropped, and nothing is invented.**

    ``security`` qualifications have no Builder field and are dropped, matching the
    JDFN clone transform's own documented limitation.
    """
    rulebook = rules if rules is not None else get_rules()
    rel = jd.relationships
    context = _split_context_blocks(jd.additional_context, rulebook)
    return WJQAnswers(
        title=jd.title,
        department=jd.department,
        position_number=jd.position_number,
        grade=jd.classification.value if jd.classification is not None else None,
        position_summary=jd.position_summary,
        major_functions=[
            DutyAnswer(action_verb=d.action_verb, statement=d.statement)
            for d in jd.duties
        ],
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
        **context,
    )

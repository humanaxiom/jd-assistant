"""Assemble CUPE (WJQ) answers into an SFU JD draft — Phase E, restructured in J2.

:func:`assemble_wjq_jd` is the WJQ counterpart of
:func:`~src.jd_bank.composer.assemble.assemble_jd`: the deterministic bridge from what
the WJQ guided flow collects to the :class:`~src.jd_core.models.parsed_jd.
SFUJobDescription` contract every downstream service already speaks. Pure — no I/O, no
LLM, no DB.

**It is written against the PARSER, not against the JDFN assembler.** ``parser/wjq.py``
turns a real CUPE questionnaire into an ``SFUJobDescription`` a particular way; this
turns authored answers into one *the same* way where the parser can see it, so an
authored CUPE JD and a parsed one share their shape. Three consequences, each of which
is why some JDFN behaviour is deliberately absent here:

* **The point-factor sections' TEXT goes to ``additional_context`` under their own
  headings** — the rulebook's ``wjq.section_headings`` vocabulary, so the text this
  writes is text the parser would read back. Not ``decision_making`` /
  ``problem_solving``: the WJQ has no Hay Accountability or Problem-Solving prose.
* **No SFU boilerplate is asserted.** The WJQ form has none of the About-SFU /
  territorial / equity blocks (HR-201), so asserting them would state something untrue
  about the document. ``applies_to`` (Phase B) withholds all four rules from the WJQ.
* **``employee_group`` is fixed to ``cupe``**, not asked. It is what makes the draft a
  WJQ document to ``template_of`` — and therefore what makes the validator judge it by
  the WJQ rules (Phase B) and numbers (Phase C). Letting an author set it would let
  them silently change which bar their own draft is scored against.

**J2: the form's STRUCTURE goes on ``wjq_form``** (:class:`~src.jd_core.models.
parsed_jd.WJQForm`) — minor functions, ticked levels, table rows, certification,
years, equivalency, requirements, the author's identification fields. Minor functions
stay OUT of ``duties`` (which the validator, rewrite and merge read, and which holds
twelve), so nothing has to be merged and cut to fit: the old silent "majors + minors,
truncated at twelve" is replaced by ``cupe_form.function_limits`` (HR-246), which
REFUSES — with the count, the limit and the id — rather than drops.

Every closed choice (frequency, level, duration, helper …) is checked against
``cupe_form.yaml`` here, and an answer outside it raises :class:`ValueError` naming the
register entry — which every Builder handler renders as the page's error, with the
author's rows still on it.

Nothing here approves or publishes (NN #1); the output is an explicit draft.
"""

from __future__ import annotations

from collections.abc import Iterable

from pydantic import BaseModel

from src.jd_bank.composer.answers import QUAL_INPUT_CEILING
from src.jd_bank.composer.wjq_answers import (
    WJQ_CONTEXT_TARGETS,
    WJQ_LEVEL_TARGETS,
    ContactAnswer,
    EffortAnswer,
    ExposureAnswer,
    FunctionAnswer,
    LocationAnswer,
    MinorFunctionAnswer,
    SkillAnswer,
    WJQAnswers,
    fold_legacy_quals,
)
from src.jd_core.models.parsed_jd import (
    SFUDuty,
    SFUJobDescription,
    SFUQualification,
    SFURelationships,
    WJQForm,
    WJQRow,
)
from src.jd_core.models.quality import WJQ_EMPLOYEE_GROUP
from src.jd_core.rules import CupeForm, Rules, WjqSection, get_rules
from src.jd_core.wjq_form_check import (
    CupeFormError,
    check_cupe_form,
    check_function_counts,
)

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


def _ceiling(model: type[BaseModel], field: str) -> int:
    """A field's ``max_length``, read off the model rather than restated."""
    return next(
        int(meta.max_length)
        for meta in model.model_fields[field].metadata
        if getattr(meta, "max_length", None) is not None
    )


#: The draft model's own ceilings the answer counts are checked against (review L2).
#: A qualification line has none since HR-308 was ruled null (2026-10-29), so the
#: joined helper + text is held to the form's own input ceiling instead.
_QUAL_MAX: int = QUAL_INPUT_CEILING
_QUALS_MAX: int = _ceiling(SFUJobDescription, "qualifications")
_REQUIREMENTS_MAX: int = _ceiling(WJQForm, "occupational_requirements")
_CONTACTS_MAX: int = _ceiling(SFURelationships, "internal")


def _duty(
    answer: FunctionAnswer | MinorFunctionAnswer, frequency: str | None
) -> SFUDuty:
    """One authored function. A pre-J2 %-allocation is still rendered as ``(NN%)``
    exactly as the JDFN assembler does — never dropped — but J2 no longer asks for one
    (HR's form asks how OFTEN, which is ``frequency``)."""
    statement = answer.statement.strip()
    if answer.allocation is not None:
        statement = f"{statement} ({answer.allocation}%)"
    return SFUDuty(
        action_verb=answer.action_verb.strip(), statement=statement, frequency=frequency
    )


def _check_counts(answers: WJQAnswers, form: CupeForm) -> None:
    """Every count the draft model has a ceiling for, checked on the ANSWERS — before a
    model is built — so the author reads the limit and its register id, never
    pydantic's raw "at most 12 items" (review L1), and a pre-J2 answer set that folds
    into more lines than a draft holds still LOADS and is refused here (review L2).
    Nothing is ever cut."""
    problems = check_function_counts(
        len(answers.major_functions), len(answers.minor_functions), form
    )
    quals = (
        len([t for t in answers.education if t.strip()])
        + len([t for t in answers.experience if t.strip()])
        + len(answers.occupational_skills)
    )
    for what, count, ceiling in (
        (
            "Section 13 (education, experience and Occupational Skills)",
            quals,
            _QUALS_MAX,
        ),
        (
            "Occupational Requirement(s)",
            len(answers.occupational_requirements),
            _REQUIREMENTS_MAX,
        ),
        (
            "Contacts inside SFU",
            len([c for c in answers.contacts if c.scope == "internal"]),
            _CONTACTS_MAX,
        ),
        (
            "Contacts outside SFU",
            len([c for c in answers.contacts if c.scope == "external"]),
            _CONTACTS_MAX,
        ),
    ):
        if count > ceiling:
            problems.append(
                f"{what} lists {count} lines; a draft holds at most {ceiling}. "
                f"Nothing was removed — combine or delete {count - ceiling} of them"
            )
    if problems:
        raise CupeFormError("CUPE form: " + "; ".join(problems) + ".")


def _levels(answers: WJQAnswers) -> dict[str, list[str]]:
    """Each checkbox section's ticked letters, de-duplicated and in HR's order. Whether
    they are HR's levels is :func:`check_cupe_form`'s question, asked of the draft."""
    return {
        section: sorted(dict.fromkeys(getattr(answers, target)))
        for section, target in WJQ_LEVEL_TARGETS.items()
    }


def _blank_to_none(value: str | None) -> str | None:
    return (value or "").strip() or None


def _skill_text(skill: SkillAnswer, form: CupeForm) -> str:
    """An Occupational Skills line: the lead phrase (HR-251) joined to the text. The
    phrase is not stored on its own, so it is checked HERE, at the one point it exists
    as a choice."""
    text = skill.text.strip()
    helper = _blank_to_none(skill.helper)
    helpers = tuple(form.occupational_skills_helpers.values())
    if helper is not None and helper not in helpers:
        raise CupeFormError(
            f"Occupational Skills lead phrase {helper!r} is not one the form offers "
            f"({', '.join(helpers)}; cupe_form.occupational_skills_helpers, HR-251)"
        )
    if helper is None or text.lower().startswith(f"{helper.lower()} "):
        return text
    joined = f"{helper} {text}"
    if len(joined) > _QUAL_MAX:
        raise ValueError(
            f"the Occupational Skills line {text[:40]!r}… is too long once "
            f"{helper!r} is added ({len(joined)} of {_QUAL_MAX} characters) — shorten "
            "it or leave the lead phrase blank"
        )
    return joined


def _qualifications(answers: WJQAnswers, form: CupeForm) -> list[SFUQualification]:
    """Education -> Experience -> Occupational Skills, HR's section 13 order. Every
    Occupational Skills line is ``skill`` (Q9, option C — one list); requirements and
    certification live on ``wjq_form``, not here."""
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
    quals += [
        SFUQualification(text=_skill_text(s, form), kind="skill")
        for s in answers.occupational_skills
        if s.text.strip()
    ]
    return quals


def _relationships(answers: WJQAnswers) -> SFURelationships | None:
    """The form's INTERNAL AND EXTERNAL CONTACTS, as the relationships the validator and
    search read. ``supervisory`` stays ``None`` and SFU's mandated Relationships header
    is NOT inserted — the WJQ has no Relationships section to head (Phase B)."""
    internal = [c.contact.strip() for c in answers.contacts if c.scope == "internal"]
    external = [c.contact.strip() for c in answers.contacts if c.scope == "external"]
    if not (internal or external):
        return None
    return SFURelationships(supervisory=None, internal=internal, external=external)


def _rows(
    items: Iterable[tuple[str, str | None, str | None, str | None]],
) -> list[WJQRow]:
    """``(item, duration, frequency, hours)`` table rows, blanks as ``None``. The scale
    values are :func:`check_cupe_form`'s to judge (HR-248 / HR-249)."""
    return [
        WJQRow(
            item=item.strip(),
            duration=_blank_to_none(duration),
            frequency=_blank_to_none(frequency),
            hours=_blank_to_none(hours),
        )
        for item, duration, frequency, hours in items
        if item.strip()
    ]


def _wjq_form(answers: WJQAnswers) -> WJQForm:
    rationale = _blank_to_none(answers.equivalency_rationale)
    levels = _levels(answers)
    return WJQForm(
        current_classification=(answers.current_classification or "").strip() or None,
        date_completed=answers.date_completed,
        completed_by=answers.completed_by,
        minor_functions=[_duty(m, None) for m in answers.minor_functions],
        level_of_independence=levels["level_of_independence"],
        training_exercised=levels["training_exercised"],
        direction_exercised=levels["direction_exercised"],
        continuing_education=levels["continuing_education"],
        contacts=_rows(
            (c.contact, c.duration, c.frequency, None) for c in answers.contacts
        ),
        effort=_rows(
            (e.effort, e.duration, e.frequency, None) for e in answers.effort_rows
        ),
        locations=_rows(
            (loc.location, None, None, loc.hours) for loc in answers.location_rows
        ),
        uncomfortable=_rows(
            (x.condition, None, x.frequency, None) for x in answers.uncomfortable_rows
        ),
        hazards=_rows(
            (x.condition, None, x.frequency, None) for x in answers.hazard_rows
        ),
        certification=[c.strip() for c in answers.certification if c.strip()],
        experience_years=answers.experience_years,
        equivalency_acceptable=(
            None if answers.equivalency is None else answers.equivalency == "acceptable"
        ),
        equivalency_rationale=rationale,
        occupational_requirements=[
            r.strip() for r in answers.occupational_requirements if r.strip()
        ],
    )


def _additional_context(answers: WJQAnswers, rules: Rules) -> str | None:
    """The point-factor sections' free text, each under the heading the PARSER matches.

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
    context = "\n\n".join(blocks)
    if len(context) > _CONTEXT_MAX:
        # Was a silent `[:_CONTEXT_MAX]` slice — it cut the TAIL of the form (section
        # 12 first). Refused visibly instead; nothing is dropped (J2).
        raise ValueError(
            f"sections 5-12 hold {len(context):,} characters together; a draft holds "
            f"at most {_CONTEXT_MAX:,}. Nothing was removed — shorten a section, then "
            "check again."
        )
    return context


def assemble_wjq_jd(
    answers: WJQAnswers, *, rules: Rules | None = None
) -> SFUJobDescription:
    """Turn WJQ guided-authoring answers into a CUPE draft.

    Pure and deterministic given ``rules`` (defaults to the shipped rulebook, like the
    JDFN assembler). Raises :class:`ValueError` — never truncates — when an answer is
    outside ``cupe_form.yaml`` (a function limit, a frequency, a level, a scale value, a
    lead phrase, or a "not acceptable" with no reason).

    Major functions are ``duties`` (with their (D)/(W)/(M)/(S) frequency); minor
    functions go on ``wjq_form`` and are NOT merged in — the split survives export and
    clone, and nothing is cut to fit twelve.
    """
    rulebook = rules if rules is not None else get_rules()
    form = rulebook.cupe_form
    _check_counts(answers, form)
    duties = [_duty(f, _blank_to_none(f.frequency)) for f in answers.major_functions]
    jd = SFUJobDescription(
        title=answers.title.strip() or "Untitled role",
        department=(answers.department or "").strip() or None,
        position_number=(answers.position_number or "").strip() or None,
        # The ONE supervisor title (Track J4's top-level field; review M2) — the field
        # the review editor writes, so an edit reaches the CUPE export too.
        supervisor_title=_blank_to_none(answers.supervisor_title),
        # HR's "Classification & Grade Approved" is HR's box (HR-240): the Builder
        # asserts no classification. The author's CURRENT one is on `wjq_form`.
        classification=None,
        # Fixed, never asked — this is what makes it a WJQ document to `template_of`,
        # and therefore what selects the bar it is judged against.
        employee_group=WJQ_EMPLOYEE_GROUP,
        about_sfu_present=False,
        position_summary=(answers.position_summary or "").strip() or None,
        duties=duties,
        decision_making=[],
        problem_solving=[],
        relationships=_relationships(answers),
        qualifications=_qualifications(answers, form),
        territorial_acknowledgement_present=False,
        employment_equity_present=False,
        additional_context=_additional_context(answers, rulebook),
        wjq_form=_wjq_form(answers),
    )
    # The ONE check of HR's closed lists — the same one the review edit and the clone
    # run (review M1), so no door stores what another refuses.
    check_cupe_form(jd, rulebook)
    return jd


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
    silently lost.

    🔴 Text BEFORE the first recognised heading opens the first section (P0-2,
    2026-08-19): it used to be dropped, and a context with no recognised heading at all
    was dropped entirely.
    """
    if not context:
        return {}
    headings = rules.wjq.section_headings
    canonical = {headings[target][0]: target for target in WJQ_CONTEXT_TARGETS}

    blocks: dict[WjqSection, list[str]] = {}
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


def _norm(text: str) -> str:
    return " ".join(text.lower().split())


def _contacts_back(jd: SFUJobDescription) -> list[ContactAnswer]:
    """The contacts as rows: WHICH contacts is ``relationships`` (a reviewer edits it);
    each one's duration / frequency comes from ``wjq_form.contacts``, matched by text
    (first unused match), so an edited contact keeps no stale duration."""
    rel = jd.relationships
    pool = list(jd.wjq_form.contacts) if jd.wjq_form is not None else []
    out: list[ContactAnswer] = []
    for scope, lines in (
        ("internal", rel.internal if rel else []),
        ("external", rel.external if rel else []),
    ):
        for line in lines:
            if not line.strip():
                continue
            match = next((r for r in pool if _norm(r.item) == _norm(line)), None)
            if match is not None:
                pool.remove(match)
            out.append(
                ContactAnswer(
                    contact=line.strip(),
                    scope=scope,
                    duration=match.duration if match else None,
                    frequency=match.frequency if match else None,
                )
            )
    return out


def _skills_back(jd: SFUJobDescription, form: CupeForm) -> list[SkillAnswer]:
    """Every knowledge / skill line as the ONE Occupational Skills list (Q9, option C —
    HR-251), in order. A J2 draft's lines are ``skill`` and split back into phrase +
    text; an older line gets "Knowledge of" only when it is a bare topic (HR-253).
    ``ability`` lines are not here — see :func:`_requirements_back`."""
    lines = [
        (q.kind, q.text, q.modifier)
        for q in jd.qualifications
        if q.kind in {"knowledge", "skill"}
    ]
    return fold_legacy_quals(
        lines,
        form.occupational_skills_helpers,
        form.occupational_skills_full_phrase_pattern,
    )


def _requirements_back(jd: SFUJobDescription) -> list[str]:
    """Occupational Requirement(s): every ``ability`` line, then the CUPE form block's
    own requirements. Owner ruling 2026-10-19 ("Abilities → Requirements"; HR-239 /
    HR-251): on a parsed role ``ability`` IS what the parser read from the Occupational
    Requirement(s) block, and the export prints ability lines there today — so a clone
    puts them back where the role came from, and where its own export puts them."""
    abilities = [q.text.strip() for q in jd.qualifications if q.kind == "ability"]
    stored = list(jd.wjq_form.occupational_requirements) if jd.wjq_form else []
    return [line for line in (*abilities, *stored) if line]


def wjq_answers_from_jd(
    jd: SFUJobDescription, *, rules: Rules | None = None
) -> WJQAnswers:
    """A CUPE JD as WJQ guided-authoring answers — the clone transform.

    For a draft authored on the J2 Builder (``wjq_form`` present) this is the exact
    inverse of :func:`assemble_wjq_jd`: the split, the frequencies, the ticks, the rows,
    the qualifications and the identification fields all come back.

    For a role parsed from the archive, or a draft written before J2 (no ``wjq_form``):
    every duty comes back as a MAJOR function with its frequency — the parser merged
    sections 3 and 4, and guessing a split would put the author's minor functions
    somewhere they did not choose; knowledge / skill fold into the one Occupational
    Skills list (HR-251) and ability lines go to Occupational Requirement(s) (owner
    ruling 2026-10-19). **Nothing is dropped, and nothing is invented.**

    Raises :class:`~src.jd_core.wjq_form_check.CupeFormError` when the stored CUPE form
    block holds a value outside HR's lists — the Builder routes render it as a refusal.

    Not carried over, by design: the role's grade (a harmonized role's grade is a
    cluster-level value, not this position's current classification — HR-240), and
    ``security`` lines (no WJQ Builder field; the JDFN clone transform keeps them since
    Track J4).
    """
    rulebook = rules if rules is not None else get_rules()
    form = rulebook.cupe_form
    # Stored data outside HR's lists (review M1) is refused HERE with its register id,
    # rather than surfacing as a raw ValidationError from the answer contract below.
    check_cupe_form(jd, rulebook)
    context = _split_context_blocks(jd.additional_context, rulebook)
    extra = jd.wjq_form
    levels = (
        {
            target: list(getattr(extra, section))
            for section, target in WJQ_LEVEL_TARGETS.items()
        }
        if extra is not None
        else {}
    )
    return WJQAnswers(
        title=jd.title,
        department=jd.department,
        position_number=jd.position_number,
        current_classification=extra.current_classification if extra else None,
        supervisor_title=jd.supervisor_title,
        date_completed=extra.date_completed if extra else None,
        completed_by=extra.completed_by if extra else None,
        position_summary=jd.position_summary,
        major_functions=[
            FunctionAnswer(
                action_verb=d.action_verb, statement=d.statement, frequency=d.frequency
            )
            for d in jd.duties
        ],
        minor_functions=[
            MinorFunctionAnswer(action_verb=d.action_verb, statement=d.statement)
            for d in (extra.minor_functions if extra else [])
        ],
        contacts=_contacts_back(jd),
        effort_rows=[
            EffortAnswer(effort=r.item, duration=r.duration, frequency=r.frequency)
            for r in (extra.effort if extra else [])
        ],
        location_rows=[
            LocationAnswer(location=r.item, hours=r.hours)
            for r in (extra.locations if extra else [])
        ],
        uncomfortable_rows=[
            ExposureAnswer(condition=r.item, frequency=r.frequency)
            for r in (extra.uncomfortable if extra else [])
        ],
        hazard_rows=[
            ExposureAnswer(condition=r.item, frequency=r.frequency)
            for r in (extra.hazards if extra else [])
        ],
        education=[q.text for q in jd.qualifications if q.kind == "education"],
        certification=list(extra.certification) if extra else [],
        experience_years=extra.experience_years if extra else None,
        experience=[q.text for q in jd.qualifications if q.kind == "experience"],
        equivalency=(
            None
            if extra is None or extra.equivalency_acceptable is None
            else ("acceptable" if extra.equivalency_acceptable else "not_acceptable")
        ),
        equivalency_rationale=extra.equivalency_rationale if extra else None,
        occupational_skills=_skills_back(jd, form),
        occupational_requirements=_requirements_back(jd),
        **levels,
        **context,
    )

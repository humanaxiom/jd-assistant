"""The harmonize REWRITE pass (Phase 4.2a) — the LLM's first Phase-4 consumer.

:func:`rewrite_merged_role` takes the deterministic Phase-4.1
:class:`~src.jd_core.models.bank.MergedRole` draft (already a valid
``SFUJobDescription``) and has a self-hosted LLM reword it into cleaner,
template-faithful prose, then scores the result with the validator (the oracle).

**We differ from hris deliberately.** hris fed the LLM the raw member JDs and let it
free-associate; we feed the GROUNDED 4.1 merge draft and forbid new content. The rewrite
may REPHRASE the draft but may not INTRODUCE skills/duties/qualifications the draft did
not contain — a deterministic **anti-fabrication guard** (the heart of this task) scrubs
ungrounded qualifications and flags no-overlap duties after the model replies. The
prompt instruction is advisory; the guard + validator are what actually bound the output
(validator-as-oracle, non-negotiable #3).

The result is a frozen ``RewrittenDraft`` with no approval, canonical or published
field: it is a DRAFT (non-negotiable #1). Nothing here publishes
anything, and ``jd_core`` is never imported the other way round.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any, Final

from src.jd_bank.jd_text import flatten_jd as _flatten_jd
from src.jd_bank.llm.client import ChatClient
from src.jd_bank.llm.prompts import load_prompt
from src.jd_core.models.bank import (
    AntiFabricationRecord,
    MergedRole,
    RewrittenDraft,
)
from src.jd_core.models.parsed_jd import SFUJobDescription, SFUQualification
from src.jd_core.models.quality import DEFAULT_TEMPLATE
from src.jd_core.quality.scoring import score_issues
from src.jd_core.quality.validators import evaluate_jd_rules, template_of
from src.jd_core.rules import Comparison, Rewrite, Rules, get_rules

#: A content token: a maximal run of lowercase letters/digits — the same alphabet the
#: signals / similarity / merge modules tokenize with. Kept local (as those do) so
#: retuning one cannot silently move the grounding check.
_TOKEN = re.compile(r"[a-z0-9]+")

#: The ONLY fields the rewrite may change. Everything else on the draft is restored from
#: the grounded 4.1 merge, which derived it from the source JDs.
#:
#: 🔴 **THIS IS AN ALLOW-LIST BECAUSE A DENY-LIST FAILED THREE TIMES.** The pass was
#: written as "the model returns a JD, we scrub what it ADDED" — the anti-fabrication
#: guard — and nothing at all policed what it REMOVED. Each time a field turned out to
#: matter, it was patched individually, and the next one was found the same way (by
#: probing the live Bank, never by a test):
#:
#: 1. ``employee_group`` — nulled on ~95% of CUPE drafts, silently moving each one to
#:    the JDFN bar, because that field is what ``template_of`` reads.
#: 2. ``classification`` / ``position_number`` — facts about the posting a language
#:    model has no way to know, added to the patch pre-emptively.
#: 3. ``additional_context`` — nulled likewise, which on a CUPE draft is **seven of the
#:    WJQ's fourteen sections**: the merge had just been fixed to carry them (HR-207)
#:    and the rewrite threw them away again on the very next run.
#:
#: The prompt's own schema literally shows ``"additional_context": null``, so the model
#: is doing what it was asked. The defect is the contract, not the model: **a rewrite
#: that may return any field can delete any field**, and "reword this draft" does not
#: license dropping content the sources stated. Inverting the default makes the next
#: such field safe by construction rather than after someone notices it missing.
#:
#: The boilerplate presence booleans are deliberately absent here too — they are set
#: explicitly further down, per template, and restoring them first makes that the only
#: place they are decided.
_REWRITABLE_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "title",
        "position_summary",
        "duties",
        "decision_making",
        "problem_solving",
        "relationships",
        "qualifications",
    }
)

#: The sections the guard will not let the rewrite CREATE from nothing. Each is a whole
#: SFU-template section that a JDFN document has and a WJQ one structurally does not, so
#: on a CUPE draft an invented one is not embellishment — it is an answer to a question
#: the source document was never asked. Duties and qualifications are deliberately NOT
#: here: those are policed per item, by grounding, above.
_SECTIONS_NEVER_INVENTED: Final[tuple[str, ...]] = (
    "decision_making",
    "problem_solving",
    "relationships",
)

#: The qualification kinds the anti-fabrication guard scrubs when ungrounded. Education,
#: experience and security are structural BARS derived by the 4.1 merge from member
#: signals, not free-text skills the model could invent, so they pass through — the
#: guard polices the "skill/knowledge/ability content" the task names.
_GROUNDED_KINDS = frozenset({"knowledge", "skill", "ability"})


def _content_tokens(text: str, comparison: Comparison) -> frozenset[str]:
    """The content tokens of ``text`` — lowercase ``[a-z0-9]+`` runs, minus stopwords
    and short tokens (the SAME filter ``signals._skill_bag`` applies), so grounding
    lines up with how skills are compared everywhere else."""
    return frozenset(
        token
        for token in _TOKEN.findall(text.lower())
        if len(token) >= comparison.skill_min_token_len
        and token not in comparison.skill_stopwords
    )


def _jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    """Token-Jaccard. Two empty sets are identical (1.0)."""
    union = a | b
    if not union:
        return 1.0
    return len(a & b) / len(union)


def _skill_frequency_lines(freq: Sequence[tuple[str, int]]) -> str:
    """``skill_frequency`` provenance as the prompt's ``skill_frequency`` slot."""
    if not freq:
        return "(none extracted)"
    return "\n".join(f"- {name}: {count}" for name, count in freq)


def _draft_vocabulary(merged: MergedRole, comparison: Comparison) -> frozenset[str]:
    """The allowed vocabulary a rewritten qualification must be grounded in: the merge
    draft's own content tokens PLUS its member-derived skill-frequency names. Generous
    by design — a rephrasing reuses the draft's words; a wholly new skill does not."""
    vocab: set[str] = set(_content_tokens(_flatten_jd(merged.draft), comparison))
    for name, _count in merged.provenance.skill_frequency:
        vocab |= _content_tokens(name, comparison)
    return frozenset(vocab)


def _is_grounded(
    text: str, vocab: frozenset[str], rewrite: Rewrite, comparison: Comparison
) -> bool:
    """Whether ``text`` is grounded in ``vocab`` under the policy (HR-182/183).

    ``token_overlap``: grounded iff at least ``skill_grounding_threshold`` of its
    content tokens are in ``vocab``. ``all_grounded``: grounded only if EVERY token is
    (the threshold is inert). A qualification with no content tokens (all stopwords) is
    grounded — there is nothing to fabricate.
    """
    tokens = _content_tokens(text, comparison)
    if not tokens:
        return True
    grounded = tokens & vocab
    if rewrite.skill_grounding_policy == "all_grounded":
        return grounded == tokens
    return len(grounded) / len(tokens) >= rewrite.skill_grounding_threshold


def _apply_anti_fabrication(
    llm_jd: SFUJobDescription, merged: MergedRole, rules: Rules
) -> tuple[SFUJobDescription, AntiFabricationRecord]:
    """Scrub ungrounded qualifications, flag no-overlap duties (HR-181…HR-184).

    Returns the scrubbed JD + the audit record. When the guard is disabled
    (``rewrite.anti_fabrication_enabled = false``) the model's output is returned
    UNSCRUBBED and the record is empty-but-``enabled=False`` — so a disabled guard is
    visible, never invisible.
    """
    rewrite = rules.rewrite
    if not rewrite.anti_fabrication_enabled:
        return llm_jd, AntiFabricationRecord(enabled=False)

    comparison = rules.comparison
    vocab = _draft_vocabulary(merged, comparison)

    kept: list[SFUQualification] = []
    scrubbed: list[str] = []
    for qual in llm_jd.qualifications:
        if qual.kind in _GROUNDED_KINDS and not _is_grounded(
            qual.text, vocab, rewrite, comparison
        ):
            scrubbed.append(qual.text)
        else:
            kept.append(qual)

    draft_duty_tokens = [
        _content_tokens(duty.statement, comparison) for duty in merged.draft.duties
    ]
    flagged: list[str] = []
    for duty in llm_jd.duties:
        tokens = _content_tokens(duty.statement, comparison)
        best = max(
            (_jaccard(tokens, draft) for draft in draft_duty_tokens), default=0.0
        )
        if best < rewrite.duty_flag_threshold:
            flagged.append(duty.statement)

    # A SECTION the grounded draft does not have cannot be written by the rewrite
    # (CUPE Phase D). The guard above polices the CONTENT of a section; this polices
    # its existence, which is the coarser and — since the producer began drafting CUPE
    # roles — the likelier fabrication: 0.0% of CUPE JDs have a Problem Solving section
    # and 3.1% an Impact of Decision Making one, because the WJQ form does not ask. A
    # model handed a schema listing both will fill them in, and the token-overlap guard
    # cannot object, because it only reads qualifications and duties.
    #
    # ⚠ EMPTY-TO-EMPTY only. A section the draft HAS is left entirely to the rewrite —
    # rewording is the pass's whole job. This drops nothing a source document stated.
    emptied: dict[str, Any] = {}
    for section in _SECTIONS_NEVER_INVENTED:
        if not getattr(merged.draft, section) and getattr(llm_jd, section):
            emptied[section] = None if section == "relationships" else []

    scrubbed_jd = llm_jd.model_copy(update={"qualifications": kept, **emptied})
    return scrubbed_jd, AntiFabricationRecord(
        enabled=True,
        scrubbed_skills=tuple(scrubbed),
        flagged_duties=tuple(flagged),
        scrubbed_sections=tuple(sorted(emptied)),
    )


async def rewrite_merged_role(
    merged: MergedRole, *, client: ChatClient, rules: Rules | None = None
) -> RewrittenDraft:
    """Reword a 4.1 merge draft with the LLM, scrub fabrication, and score it.

    Pure of persistence: no DB, no publish. Returns a frozen ``RewrittenDraft`` — a
    DRAFT (non-negotiable #1), the validator's score/grade/issues, the anti-fab record,
    and the model / prompt / rules provenance.
    """
    active = rules if rules is not None else get_rules()
    rewrite = active.rewrite

    # The prompt states the DRAFT'S OWN FORM's numbers (CUPE Phase D). They used to be
    # inlined in the template as SFU's JDFN guidance — "3–5 major duties", "100–150
    # words" — which was a rulebook fact hardcoded in a prompt, and harmless only for
    # as long as JDFN was the one form the producer ever drafted.
    #
    # 🔴 On a CUPE draft that inlined "3–5" is DESTRUCTIVE, not merely wrong. The WJQ
    # form has twelve duty slots and 77.4% of CUPE JDs fill all twelve, so a rewrite
    # asked for three-to-five duties deletes most of the role — and the anti-fabrication
    # guard cannot catch it, because the guard exists to stop the model ADDING content.
    # Nothing downstream would have flagged the loss: the WJQ profile's `duties_min` is
    # 3, so a five-duty CUPE draft passes its own bar while missing seven duties the
    # source documents actually stated.
    thresholds = active.thresholds_for(template_of(merged.draft))

    # We feed the GROUNDED 4.1 draft into the `member_jds` slot, not the raw members.
    prompt = load_prompt(
        rewrite.prompt_version,
        member_count=merged.provenance.member_count,
        skill_frequency=_skill_frequency_lines(merged.provenance.skill_frequency),
        member_jds=_flatten_jd(merged.draft),
        duties_min=thresholds.duties_min,
        duties_max=thresholds.duties_max,
        summary_min_words=thresholds.summary_min_words,
        summary_max_words=thresholds.summary_max_words,
    )
    # Loose JSON mode + repair retry (the default; NOT constrained decoding). Handing
    # Ollama's structured-output builder the large nested SFUJobDescription grammar 500s
    # it live (`failed to load model vocabulary required for format`), which would drop
    # every rewrite to the deterministic fallback. Loose mode is the ~99% pre-4.6 path;
    # only the audit's small schema opts into `constrain_to_schema` — see
    # ChatClient.chat_json.
    llm_jd = await client.chat_json(
        prompt.messages,
        SFUJobDescription,
        max_tokens=rewrite.max_tokens,
        max_retries=rewrite.max_retries,
    )

    scrubbed_jd, record = _apply_anti_fabrication(llm_jd, merged, active)

    # 🔴 THE MODEL MAY REWORD A DRAFT. IT MAY NOT DELETE FROM IT.
    #
    # Everything outside `_REWRITABLE_FIELDS` comes back from the GROUNDED merge draft,
    # which derived it from the source JDs. This is the anti-fabrication guard's posture
    # applied in the other direction: that guard stops the model ADDING, and until now
    # nothing stopped it REMOVING — which it did, silently, to three different fields in
    # one weekend (see `_REWRITABLE_FIELDS` for the list and how each was found).
    #
    # An ALLOW-LIST rather than another patch, because the deny-list version was wrong
    # three times running: the failure mode is "a field nobody thought about", so only
    # inverting the default makes the next one safe before someone notices it missing.
    scrubbed_jd = merged.draft.model_copy(
        update={field: getattr(scrubbed_jd, field) for field in _REWRITABLE_FIELDS}
    )

    # Boilerplate sections (About SFU, territorial acknowledgement, employment equity)
    # are template-provided, not authored by the rewrite — mark them present so the
    # grade reflects role CONTENT, as hris `jd_bank_task.harmonize_cluster` does. (This
    # differs on purpose from the 4.1 merge draft, which keeps them honest-OR because it
    # is not asserting authored compliance; the rewrite is graded on the wording made.)
    #
    # ⚠ "TEMPLATE-PROVIDED" IS A CLAIM ABOUT A TEMPLATE, so it is only true of the
    # template that provides them (CUPE Phase D). The WJQ form contains no About SFU
    # block, no territorial acknowledgement and no EDI statement — that is the measured
    # fact behind HR-201 — so asserting all three on a CUPE draft would state something
    # about the document that is not so, in the three fields a reviewer is likeliest to
    # take at face value. On a WJQ draft the merge's honest OR stands.
    #
    # It costs no score either way: `applies_to` (Phase B) already withholds the three
    # rules that read these fields from the WJQ, so the assertion was never buying the
    # CUPE cohort anything — it was only making the draft say something untrue.
    if template_of(scrubbed_jd) == DEFAULT_TEMPLATE:
        final_jd = scrubbed_jd.model_copy(
            update={
                "about_sfu_present": True,
                "territorial_acknowledgement_present": True,
                "employment_equity_present": True,
            }
        )
    else:
        final_jd = scrubbed_jd

    issues = evaluate_jd_rules(final_jd, _flatten_jd(final_jd), rules=active)
    score, grade = score_issues(issues, scoring=active.scoring)

    return RewrittenDraft(
        draft=final_jd,
        score=score,
        grade=grade,
        issues=tuple(issues),
        anti_fabrication=record,
        model=rewrite.model,
        prompt_version=prompt.version,
        rules_version=active.version,
    )

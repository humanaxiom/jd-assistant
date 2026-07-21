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

from src.jd_bank.jd_text import flatten_jd as _flatten_jd
from src.jd_bank.llm.client import ChatClient
from src.jd_bank.llm.prompts import load_prompt
from src.jd_core.models.bank import (
    AntiFabricationRecord,
    MergedRole,
    RewrittenDraft,
)
from src.jd_core.models.parsed_jd import SFUJobDescription, SFUQualification
from src.jd_core.quality.scoring import score_issues
from src.jd_core.quality.validators import evaluate_jd_rules
from src.jd_core.rules import Comparison, Rewrite, Rules, get_rules

#: A content token: a maximal run of lowercase letters/digits — the same alphabet the
#: signals / similarity / merge modules tokenize with. Kept local (as those do) so
#: retuning one cannot silently move the grounding check.
_TOKEN = re.compile(r"[a-z0-9]+")

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

    scrubbed_jd = llm_jd.model_copy(update={"qualifications": kept})
    return scrubbed_jd, AntiFabricationRecord(
        enabled=True,
        scrubbed_skills=tuple(scrubbed),
        flagged_duties=tuple(flagged),
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

    # We feed the GROUNDED 4.1 draft into the `member_jds` slot, not the raw members.
    prompt = load_prompt(
        rewrite.prompt_version,
        member_count=merged.provenance.member_count,
        skill_frequency=_skill_frequency_lines(merged.provenance.skill_frequency),
        member_jds=_flatten_jd(merged.draft),
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

    # Boilerplate sections (About SFU, territorial acknowledgement, employment equity)
    # are template-provided, not authored by the rewrite — mark them present so the
    # grade reflects role CONTENT, as hris `jd_bank_task.harmonize_cluster` does. (This
    # differs on purpose from the 4.1 merge draft, which keeps them honest-OR because it
    # is not asserting authored compliance; the rewrite is graded on the wording made.)
    final_jd = scrubbed_jd.model_copy(
        update={
            "about_sfu_present": True,
            "territorial_acknowledgement_present": True,
            "employment_equity_present": True,
        }
    )

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

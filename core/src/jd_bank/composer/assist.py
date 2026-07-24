"""LLM authoring assist for the JD Builder (Phase 5.5).

Decision-support, not decision-making. :func:`suggest_summary` asks a self-hosted
LLM to reword a draft's Position Summary to the SFU 100-150-word standard, grounded
in the draft's own content, then **re-validates the result and returns it as a
suggestion** — the author accepts or discards it, and either way the draft still
goes through the review queue (NN #1). Nothing here auto-applies or publishes.

**Reuses the Phase-4.2 scaffolding, adds no new rulebook decision:**

* the injectable :class:`~src.jd_bank.llm.client.ChatClient` (egress-guarded at
  construction — NN #5, build-enforced), bound to ``rules.rewrite.model`` /
  ``max_tokens`` / ``max_retries`` (already-registered decisions HR-176…);
* the versioned prompt template ``jd_compose_summary_v1`` (jd_bank-LOCAL data, like
  the harmonize/quality templates — the ``_v1`` suffix IS its version, stamped onto
  the suggestion for provenance);
* the 100-150-word target read from ``thresholds`` (``summary_min_words`` /
  ``summary_max_words``) — the SAME numbers the validator gates on, so the assist
  aims at exactly what the oracle checks.

**Validator-as-oracle (NN #3).** The suggestion carries the FRESH
:class:`~src.jd_bank.composer.models.DraftAssessment` of the draft *with the
suggested summary applied* — so the Builder shows the author the real compliance
delta, computed by the validator, never the model's own claim about its output.
A ``grounded_fraction`` is reported (advisory): how much of the suggestion's
vocabulary comes from the draft, a fabrication smell the author can weigh.
"""

from __future__ import annotations

import re
from typing import Final

from pydantic import BaseModel, ConfigDict, Field

from src.jd_bank.composer.models import DraftAssessment
from src.jd_bank.composer.validate import assess_draft
from src.jd_bank.jd_text import flatten_jd
from src.jd_bank.llm.client import ChatClient
from src.jd_bank.llm.prompts import load_prompt
from src.jd_core.models.parsed_jd import SFUJobDescription
from src.jd_core.rules import Comparison, Rules, get_rules

#: The versioned prompt template for the summary assist (jd_bank-local data). The
#: ``_v1`` suffix is the version; ``load_prompt`` returns it and it is stamped onto the
#: suggestion for provenance — no rulebook field needed for advisory, never-published
#: decision-support (the model/limits come from ``rules.rewrite``, the word range from
#: ``thresholds`` — both already registered).
_SUMMARY_PROMPT: Final[str] = "jd_compose_summary_v1"

#: A content token: a maximal run of lowercase letters/digits — the same alphabet the
#: signals / merge / rewrite modules tokenize with. Kept local (as those do) so retuning
#: one cannot silently move the grounding measure.
_TOKEN: Final[re.Pattern[str]] = re.compile(r"[a-z0-9]+")


class _SummaryReply(BaseModel):
    """The strict JSON shape the model must return for the summary assist."""

    model_config = ConfigDict(extra="ignore")

    summary: str = Field(min_length=1, max_length=4000)


class SummarySuggestion(BaseModel):
    """An LLM-suggested Position Summary + the validator's verdict on the draft it
    would produce. The author accepts or discards it; nothing auto-applies (NN #1)."""

    model_config = ConfigDict(extra="forbid")

    suggested_summary: str
    word_count: int = Field(ge=0)
    #: Fraction of the suggestion's content tokens that appear in the draft — advisory
    #: fabrication smell (1.0 = every meaningful word came from the draft).
    grounded_fraction: float = Field(ge=0.0, le=1.0)
    #: The draft WITH this summary applied, freshly re-validated (validator-as-oracle):
    #: the real compliance delta the author sees before accepting.
    assessment: DraftAssessment
    model: str
    prompt_version: str


def _content_tokens(text: str, comparison: Comparison) -> frozenset[str]:
    """Lowercase ``[a-z0-9]+`` runs minus stopwords / short tokens — the same filter the
    rewrite grounding and the skill bag use, so "grounded" means the same thing here."""
    return frozenset(
        token
        for token in _TOKEN.findall(text.lower())
        if len(token) >= comparison.skill_min_token_len
        and token not in comparison.skill_stopwords
    )


def _grounded_fraction(summary: str, jd: SFUJobDescription, rules: Rules) -> float:
    """How grounded the suggested summary is in the draft: the fraction of its content
    tokens present in the draft's vocabulary. A summary with no content tokens is
    vacuously grounded (1.0) — there is nothing that could be fabricated."""
    comparison = rules.comparison
    summary_tokens = _content_tokens(summary, comparison)
    if not summary_tokens:
        return 1.0
    draft_vocab = _content_tokens(flatten_jd(jd), comparison)
    return len(summary_tokens & draft_vocab) / len(summary_tokens)


async def suggest_summary(
    jd: SFUJobDescription, *, client: ChatClient, rules: Rules | None = None
) -> SummarySuggestion:
    """Ask the LLM for an improved Position Summary, re-validate the resulting draft,
    and return it as a suggestion. Injected ``client`` (mockable + egress-guarded);
    pure of persistence — nothing is saved or published."""
    active = rules if rules is not None else get_rules()
    prompt = load_prompt(
        _SUMMARY_PROMPT,
        title=jd.title,
        jd_text=flatten_jd(jd),
        min_words=active.thresholds.summary_min_words,
        max_words=active.thresholds.summary_max_words,
    )
    reply = await client.chat_json(
        prompt.messages,
        _SummaryReply,
        max_tokens=active.rewrite.max_tokens,
        max_retries=active.rewrite.max_retries,
    )
    suggested = reply.summary.strip()
    candidate = jd.model_copy(update={"position_summary": suggested})
    return SummarySuggestion(
        suggested_summary=suggested,
        word_count=len(suggested.split()),
        grounded_fraction=_grounded_fraction(suggested, jd, active),
        assessment=assess_draft(candidate, rules=active),
        model=active.rewrite.model,
        prompt_version=prompt.version,
    )

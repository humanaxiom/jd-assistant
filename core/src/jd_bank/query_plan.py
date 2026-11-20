"""Query understanding for both search boxes (Track I, PR I3) — an OPTIONAL, guarded,
self-hosted LLM read of what the person typed, in front of the title + vector passes.

    understanding = await try_understand_query("AP clerk", client_factory=ChatClient)
    # -> semantic_query "accounts payable clerk", title_keywords ("AP clerk",
    #    "accounts payable clerk", "accounts payable assistant"), nothing filtered

Three things make it safe to put a model in front of a search page, and none of them
is a knob:

1. **The guard is deterministic** (:func:`guard_plan`). Measured 2026-10-19: unguarded,
   the model invented an employee-group filter on 75–85% of queries and emptied pages.
   So an employee group is honoured only when the person TYPED it; a unit only when it
   is one of ``org_units.yaml``'s keys, and then as a *suggestion* the page offers,
   never a filter; the words as typed are always the first title keyword, so exact-title
   findability is never worse than without the model. What the guard dropped is listed
   on ``discarded`` and shown — the person sees what the model wanted and did not get.
2. **It can only add.** A plan widens the candidate set (more title keywords, a better
   phrasing for the vector pass). Nothing is removed from what the plain search finds.
3. **Any failure is "no plan".** Disabled, timed out, host down, invalid JSON: the page
   is rendered from the words as typed, and when the feature is OFF no client is even
   constructed (``test_disabled_search_makes_no_chat_call`` pins that).

Rank only: the plan carries no score, and nothing downstream shows one.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Callable
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from src.jd_bank.llm.client import ChatClient
from src.jd_bank.llm.prompts import load_prompt
from src.jd_core.rules import Rules, get_rules

logger = logging.getLogger(__name__)

#: The employee-group tokens a person can TYPE to ask for a group. ``union`` is how
#: people say CUPE; nothing else is an alias.
_TYPED_GROUPS: dict[str, str] = {
    "apsa": "apsa",
    "apex": "apex",
    "cupe": "cupe",
    "poly": "poly",
    "union": "cupe",
}
_WORD = re.compile(r"[a-z0-9]+")
#: A keyword longer than this is a sentence, not a title fragment.
_MAX_KEYWORD_CHARS = 60


class QueryPlan(BaseModel):
    """What the model returns — the schema the request is CONSTRAINED to. Small and
    flat on purpose: constrained decoding worked on all 44 spike calls."""

    model_config = ConfigDict(extra="forbid")

    semantic_query: str = Field(min_length=1, max_length=300)
    title_keywords: list[str] = Field(default_factory=list, max_length=16)
    employee_group: Literal["apsa", "apex", "cupe", "poly"] | None = None
    unit_key: str | None = Field(default=None, max_length=80)


class QueryUnderstanding(BaseModel):
    """The GUARDED plan: what the search will actually use, and what it will show."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    raw_query: str
    #: What the vector pass embeds instead of the words as typed.
    semantic_query: str
    #: Title scans, in order. ``raw_query`` is ALWAYS first.
    title_keywords: tuple[str, ...]
    #: Honoured only when the person typed it; ``None`` otherwise.
    employee_group: str | None = None
    #: A rulebook unit the person named — offered as a link, never applied.
    unit_key: str | None = None
    unit_label: str | None = None
    unit_slug: str | None = None
    #: What the guard refused, in words a person can read.
    discarded: tuple[str, ...] = ()
    model: str
    prompt_version: str

    @property
    def extra_keywords(self) -> tuple[str, ...]:
        """The keywords the model ADDED (everything but the words as typed)."""
        return self.title_keywords[1:]


def typed_group(query: str) -> str | None:
    """The employee group the person TYPED, or ``None``."""
    for word in _WORD.findall(query.lower()):
        if word in _TYPED_GROUPS:
            return _TYPED_GROUPS[word]
    return None


def guard_plan(
    query: str, plan: QueryPlan, rules: Rules | None = None
) -> QueryUnderstanding:
    """Turn the model's plan into what the search may use. Pure; see the module doc."""
    active = rules if rules is not None else get_rules()
    search = active.search
    discarded: list[str] = []
    raw = query.strip()

    keywords: list[str] = [raw]
    seen = {raw.casefold()}
    for candidate in plan.title_keywords:
        word = " ".join(candidate.split())
        key = word.casefold()
        if not word or key in seen or len(word) > _MAX_KEYWORD_CHARS:
            continue
        if len(keywords) >= search.query_max_title_keywords:
            discarded.append(
                "more title keywords than the "
                f"{search.query_max_title_keywords} allowed"
            )
            break
        keywords.append(word)
        seen.add(key)

    group: str | None = None
    typed = typed_group(raw)
    if plan.employee_group is not None:
        if typed == plan.employee_group:
            group = typed
        else:
            discarded.append(
                f"the model wanted only {plan.employee_group.upper()} roles; "
                "you did not type that, so nothing is filtered"
            )

    unit_key = unit_label = unit_slug = None
    if plan.unit_key:
        unit = active.org_units.units.get(plan.unit_key)
        if unit is not None:
            unit_key, unit_label, unit_slug = plan.unit_key, unit.label, unit.slug
        else:
            discarded.append(
                f"the model named a unit ({plan.unit_key}) that is not one the "
                "rulebook knows; ignored"
            )

    semantic = " ".join(plan.semantic_query.split()) or raw
    return QueryUnderstanding(
        raw_query=raw,
        semantic_query=semantic,
        title_keywords=tuple(keywords),
        employee_group=group,
        unit_key=unit_key,
        unit_label=unit_label,
        unit_slug=unit_slug,
        discarded=tuple(discarded),
        model=search.query_model,
        prompt_version=search.query_prompt_version,
    )


async def understand_query(
    query: str, *, client: ChatClient, rules: Rules | None = None
) -> QueryUnderstanding:
    """One schema-constrained plan call, then the guard. Raises on any failure; the
    caller bounds it (:func:`try_understand_query`)."""
    active = rules if rules is not None else get_rules()
    search = active.search
    prompt = load_prompt(
        search.query_prompt_version,
        query=query.strip(),
        max_keywords=max(0, search.query_max_title_keywords - 1),
        unit_keys=", ".join(sorted(active.org_units.units)) or "(none)",
    )
    plan = await client.chat_json(
        prompt.messages,
        QueryPlan,
        max_tokens=search.query_max_tokens,
        max_retries=search.query_max_retries,
        constrain_to_schema=True,
    )
    return guard_plan(query, plan, active)


async def try_understand_query(
    query: str,
    *,
    client_factory: Callable[[], ChatClient],
    rules: Rules | None = None,
) -> QueryUnderstanding | None:
    """The plan for ``query``, or ``None`` — never raises, never blocks past the
    rulebook budget. With the feature OFF, ``client_factory`` is never called, so no
    client is built and no network is touched. ``client_factory`` is called with the
    rulebook's model / temperature / effort already applied when it is the real
    :class:`ChatClient`; a test passes a fake."""
    active = rules if rules is not None else get_rules()
    search = active.search
    if not search.query_understanding_enabled or not query.strip():
        return None
    client: ChatClient | None = None
    try:
        client = client_factory()
        return await asyncio.wait_for(
            understand_query(query, client=client, rules=active),
            timeout=search.query_timeout_seconds,
        )
    except Exception:  # noqa: BLE001 — any failure is "no plan"; the page still renders
        logger.info("search query understanding unavailable", exc_info=True)
        return None
    finally:
        if client is not None:
            try:
                await client.close()
            except Exception:  # noqa: BLE001
                logger.debug(
                    "closing the query-understanding client failed", exc_info=True
                )


def rulebook_chat_client(rules: Rules | None = None) -> ChatClient:
    """The real client, built with THIS pass's knobs (HR-316–318) — never the rewrite's
    model and never ``settings.agent_model``."""
    active = rules if rules is not None else get_rules()
    search = active.search
    return ChatClient(
        rules=active,
        model=search.query_model,
        temperature=search.query_temperature,
        reasoning_effort=search.query_reasoning_effort,
    )


__all__ = [
    "QueryPlan",
    "QueryUnderstanding",
    "guard_plan",
    "rulebook_chat_client",
    "try_understand_query",
    "typed_group",
    "understand_query",
]

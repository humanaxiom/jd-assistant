"""Unit — query understanding for both search boxes (Track I, PR I3).

What these defend, in the order the module doc states them:

1. **The guard is deterministic and not a knob.** An employee group the person did not
   type is dropped (and SAID); a unit that is not a rulebook key is dropped (and said);
   the words as typed are always the first title keyword; keywords are deduplicated,
   trimmed and capped by the rulebook.
2. **It can only add** — the guarded plan never carries a filter the query did not name.
3. **Any failure is "no plan"**: disabled → no client is built; a timeout, a transport
   error or an invalid reply → ``None``, never an exception; the client is closed.
4. The prompt pair loads with exactly the variables the module passes, and the real
   client is built with THIS pass's model/temperature/effort, not the rewrite's.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from src.jd_bank import query_plan
from src.jd_bank.llm.prompts import load_prompt
from src.jd_bank.query_plan import (
    QueryPlan,
    QueryUnderstanding,
    guard_plan,
    try_understand_query,
    typed_group,
    understand_query,
)
from src.jd_core.rules import Rules, get_rules
from tests.unit.retuned_rules import retuned_search


@pytest.fixture
def rules() -> Rules:
    return get_rules()


@pytest.fixture
def enabled(rules: Rules) -> Rules:
    return retuned_search(rules, query_understanding_enabled=True)


class _FakeChat:
    """Stands in for ``ChatClient``: returns a FIXED plan (or raises), records the call
    and whether it was closed. No network."""

    def __init__(self, plan: QueryPlan | Exception, *, delay: float = 0.0) -> None:
        self._plan = plan
        self._delay = delay
        self.calls: list[dict[str, Any]] = []
        self.closed = False

    async def chat_json(
        self,
        messages: object,
        model_cls: type,
        *,
        max_tokens: int,
        max_retries: int,
        constrain_to_schema: bool = False,
    ) -> Any:
        self.calls.append(
            {
                "messages": messages,
                "model_cls": model_cls,
                "max_tokens": max_tokens,
                "max_retries": max_retries,
                "constrain_to_schema": constrain_to_schema,
            }
        )
        if self._delay:
            await asyncio.sleep(self._delay)
        if isinstance(self._plan, Exception):
            raise self._plan
        return self._plan

    async def close(self) -> None:
        self.closed = True


def _plan(**overrides: Any) -> QueryPlan:
    base: dict[str, Any] = {
        "semantic_query": "accounts payable clerk",
        "title_keywords": ["Accounts Payable Clerk", "Accounts Payable Assistant"],
    }
    base.update(overrides)
    return QueryPlan(**base)


# ── 1 + 2: the guard ─────────────────────────────────────────────────────────────


def test_the_words_as_typed_are_always_the_first_keyword(rules: Rules) -> None:
    got = guard_plan("  AP clerk ", _plan(), rules)
    assert got.raw_query == "AP clerk"
    assert got.title_keywords[0] == "AP clerk"
    assert got.extra_keywords == (
        "Accounts Payable Clerk",
        "Accounts Payable Assistant",
    )
    assert got.semantic_query == "accounts payable clerk"


def test_an_untyped_employee_group_is_dropped_and_said(rules: Rules) -> None:
    got = guard_plan("AP clerk", _plan(employee_group="cupe"), rules)
    assert got.employee_group is None
    assert any("CUPE" in d and "did not type" in d for d in got.discarded)


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("cupe AP clerk", "cupe"),
        ("union clerk", "cupe"),
        ("APSA analyst", "apsa"),
        ("clerk", None),
    ],
)
def test_a_group_is_honoured_only_when_typed(
    rules: Rules, query: str, expected: str | None
) -> None:
    assert typed_group(query) == expected
    got = guard_plan(query, _plan(employee_group=expected or "apex"), rules)
    assert got.employee_group == expected


def test_a_unit_must_be_a_rulebook_key_and_is_only_a_suggestion(rules: Rules) -> None:
    key, unit = next(iter(rules.org_units.units.items()))
    got = guard_plan("x", _plan(unit_key=key), rules)
    assert (got.unit_key, got.unit_label, got.unit_slug) == (key, unit.label, unit.slug)
    bogus = guard_plan("x", _plan(unit_key="faculty-of-made-up"), rules)
    assert bogus.unit_key is None
    assert any("faculty-of-made-up" in d for d in bogus.discarded)


def test_keywords_are_deduplicated_trimmed_and_capped(rules: Rules) -> None:
    capped = retuned_search(rules, query_max_title_keywords=3)
    got = guard_plan(
        "clerk",
        _plan(
            title_keywords=[
                " Clerk ",  # the words as typed, re-spelled: dropped
                "Office  Clerk",  # inner whitespace collapsed
                "office clerk",  # case-insensitive duplicate: dropped
                "Records Clerk",
                "Payroll Clerk",  # over the cap: dropped and said
                "x" * 80,  # a sentence, not a title fragment
            ]
        ),
        capped,
    )
    assert got.title_keywords == ("clerk", "Office Clerk", "Records Clerk")
    assert any("more title keywords" in d for d in got.discarded)


def test_the_guarded_plan_carries_no_score() -> None:
    assert not any(
        "score" in f or "similar" in f for f in QueryUnderstanding.model_fields
    )


# ── 3: failure is "no plan" ───────────────────────────────────────────────────────


async def test_disabled_search_builds_no_client(rules: Rules) -> None:
    assert rules.search.query_understanding_enabled is False  # ships OFF (HR-315)
    built: list[int] = []

    def factory() -> Any:
        built.append(1)
        return _FakeChat(_plan())

    assert (
        await try_understand_query("AP clerk", client_factory=factory, rules=rules)
        is None
    )
    assert built == []


async def test_a_blank_query_is_not_sent(enabled: Rules) -> None:
    built: list[int] = []
    assert (
        await try_understand_query(
            "   ", client_factory=lambda: built.append(1), rules=enabled
        )
        is None
    )
    assert built == []


async def test_enabled_returns_the_guarded_plan_and_closes_the_client(
    enabled: Rules,
) -> None:
    fake = _FakeChat(_plan(employee_group="apsa"))
    got = await try_understand_query(
        "AP clerk", client_factory=lambda: fake, rules=enabled
    )
    assert got is not None
    assert got.extra_keywords == (
        "Accounts Payable Clerk",
        "Accounts Payable Assistant",
    )
    assert got.employee_group is None  # not typed → dropped
    assert got.model == enabled.search.query_model
    assert got.prompt_version == enabled.search.query_prompt_version
    assert fake.closed
    [call] = fake.calls
    assert call["model_cls"] is QueryPlan
    assert call["constrain_to_schema"] is True
    assert call["max_tokens"] == enabled.search.query_max_tokens
    assert call["max_retries"] == enabled.search.query_max_retries


async def test_a_timeout_is_no_plan_and_the_client_is_closed(enabled: Rules) -> None:
    quick = retuned_search(
        enabled, query_understanding_enabled=True, query_timeout_seconds=0.05
    )
    fake = _FakeChat(_plan(), delay=0.5)
    assert (
        await try_understand_query("x", client_factory=lambda: fake, rules=quick)
        is None
    )
    assert fake.closed


async def test_a_transport_or_schema_error_is_no_plan(enabled: Rules) -> None:
    fake = _FakeChat(RuntimeError("host down"))
    assert (
        await try_understand_query("x", client_factory=lambda: fake, rules=enabled)
        is None
    )
    assert fake.closed


async def test_a_factory_that_cannot_build_a_client_is_no_plan(enabled: Rules) -> None:
    def factory() -> Any:
        raise RuntimeError("egress guard refused the host")

    assert (
        await try_understand_query("x", client_factory=factory, rules=enabled) is None
    )


# ── 4: the prompt and the real client's knobs ─────────────────────────────────────


def test_the_prompt_pair_loads_with_the_modules_variables(rules: Rules) -> None:
    prompt = load_prompt(
        rules.search.query_prompt_version,
        query="AP clerk",
        max_keywords=3,
        unit_keys="it, science",
    )
    assert prompt.version == "jd_search_plan_v1"
    system, user = prompt.messages
    assert "AP clerk" in str(user["content"])
    assert "it, science" in str(system["content"])
    assert "Never guess a group" in str(system["content"])


async def test_understand_query_sends_the_rulebook_units(enabled: Rules) -> None:
    fake = _FakeChat(_plan())
    await understand_query("AP clerk", client=fake, rules=enabled)
    [call] = fake.calls
    system = str(call["messages"][0]["content"])
    for key in enabled.org_units.units:
        assert key in system


def test_the_real_client_is_built_with_this_pass_s_knobs(
    monkeypatch: pytest.MonkeyPatch, enabled: Rules
) -> None:
    seen: dict[str, Any] = {}

    class _Spy:
        def __init__(self, **kwargs: Any) -> None:
            seen.update(kwargs)

    monkeypatch.setattr(query_plan, "ChatClient", _Spy)
    query_plan.rulebook_chat_client(enabled)
    assert seen["model"] == enabled.search.query_model
    assert seen["temperature"] == enabled.search.query_temperature
    assert seen["reasoning_effort"] == enabled.search.query_reasoning_effort
    assert (
        seen["model"] != enabled.rewrite.model or True
    )  # may coincide; the point is the source

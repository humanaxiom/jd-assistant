"""The generalized ``ChatClient`` (Phase 4.2b): the audit pass binds the chat model /
temperature to ``rules.quality.*`` (a SEPARATE rulebook decision from the rewrite),
while every existing rewrite call-site — which passes neither override — still falls
back to ``rules.rewrite.*`` byte-identically.

The model source is pinned BY MUTATION (acceptance #4): ``rules.quality.model``,
``rules.rewrite.model`` and ``settings.agent_model`` are driven to THREE DISTINCT
strings, so a client that read the wrong source goes red immediately. The fake
``AsyncOpenAI`` is content-keyed on ``choice.index``, never by position.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.jd_bank.llm.client import ChatClient
from src.jd_core.models.parsed_jd import SFUJobDescription
from src.jd_core.rules import get_rules
from src.settings import get_settings

_VALID_JSON = '{"title": "Financial Analyst"}'


def _fake_openai(create: AsyncMock) -> SimpleNamespace:
    return SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create)),
        close=AsyncMock(),
    )


def _response(items: list[tuple[int, str | None]]) -> SimpleNamespace:
    choices = [
        SimpleNamespace(index=i, message=SimpleNamespace(content=content))
        for i, content in items
    ]
    return SimpleNamespace(choices=choices)


async def _drive(client: ChatClient) -> None:
    await client.chat_json(
        [{"role": "user", "content": "go"}],
        SFUJobDescription,
        max_tokens=256,
        max_retries=0,
    )


# --- back-compatible: no override -> rewrite.* (existing call-sites unchanged) ----


@pytest.mark.asyncio
async def test_without_overrides_the_client_falls_back_to_rewrite_knobs() -> None:
    """A ``ChatClient`` constructed with neither ``model`` nor ``temperature`` binds to
    ``rules.rewrite.*`` as before — so every 4.2a rewrite call-site is unmoved."""
    create = AsyncMock(return_value=_response([(0, _VALID_JSON)]))
    rules = get_rules()
    client = ChatClient(client=_fake_openai(create), rules=rules)

    await _drive(client)

    assert create.call_args.kwargs["model"] == rules.rewrite.model
    assert create.call_args.kwargs["temperature"] == rules.rewrite.temperature


# --- the audit override: model/temperature come from rules.quality.* -------------


@pytest.mark.asyncio
async def test_overrides_win_over_the_rewrite_fallback() -> None:
    """The audit constructs ``ChatClient(model=rules.quality.model,
    temperature=rules.quality.temperature)`` — the explicit overrides must WIN over the
    ``rewrite.*`` fallback, or the audit would silently run on the rewrite's model."""
    create = AsyncMock(return_value=_response([(0, _VALID_JSON)]))
    rules = get_rules()
    client = ChatClient(
        client=_fake_openai(create),
        rules=rules,
        model="an-explicit-audit-model",
        temperature=0.42,
    )

    await _drive(client)

    assert create.call_args.kwargs["model"] == "an-explicit-audit-model"
    assert create.call_args.kwargs["temperature"] == 0.42


@pytest.mark.asyncio
async def test_the_audit_model_source_is_quality_not_rewrite_nor_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Acceptance #4, pinned by mutation: ``rules.quality.model``,
    ``rules.rewrite.model`` and ``settings.agent_model`` are THREE DISTINCT strings. The
    audit binds the client to ``rules.quality.model``; a client that read the rewrite
    model or the harness setting goes red here."""
    quality_model = "a-distinct-quality-audit-model"
    rewrite_model = "a-distinct-rewrite-model"
    harness_model = "a-distinct-harness-coder-agent-model"

    settings = get_settings().model_copy(update={"agent_model": harness_model})
    monkeypatch.setattr("src.jd_bank.llm.client.get_settings", lambda: settings)
    rules = get_rules()
    retuned = rules.model_copy(
        update={
            "quality": rules.quality.model_copy(update={"model": quality_model}),
            "rewrite": rules.rewrite.model_copy(update={"model": rewrite_model}),
        }
    )
    # the three sources are genuinely distinct, so the assertion can actually fail
    assert len({quality_model, rewrite_model, harness_model}) == 3

    create = AsyncMock(return_value=_response([(0, _VALID_JSON)]))
    client = ChatClient(
        client=_fake_openai(create),
        rules=retuned,
        model=retuned.quality.model,
        temperature=retuned.quality.temperature,
    )

    await _drive(client)

    assert create.call_args.kwargs["model"] == quality_model
    assert create.call_args.kwargs["model"] != rewrite_model
    assert create.call_args.kwargs["model"] != harness_model

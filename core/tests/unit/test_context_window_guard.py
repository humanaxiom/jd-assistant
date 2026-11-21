"""The inference host's context window is checked, not assumed (HR-341).

MEASURED 2026-11-21: ``aria-gb10-2`` served ``gpt-oss:120b`` at a 4,096-token context
(the model's own is 131,072). A ~6k-token probe came back ``prompt_tokens: 4096`` — cut,
with no error — while a rewrite needs the prompt (~1k system + the parse, p99 ~7–8k
tokens) AND up to ``max_tokens`` 8,192 of reasoning + JSON in the same window. Drafts do
not record token usage, so a rewrite of a truncated prompt is indistinguishable in the
Bank from a good one. The v11 full pass sat 61 minutes on its first cluster before it
was stopped.

The guard: before a pass (and at every checkpoint) the client sends ONE probe prompt of
at least ``min_context_tokens`` words, asks for one token back, and reads the server's
own ``usage.prompt_tokens``. A host that cut it — or reports no usage at all, so the cut
cannot be ruled out — refuses the pass.

The ``AsyncOpenAI`` is a plain fake (ADR-003): no live endpoint.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from src.jd_bank.canonical.__main__ import _check_context_windows
from src.jd_bank.llm.client import (
    ChatClient,
    ContextWindowTooSmallError,
    LLMOutputInvalidError,
)
from src.jd_core.models.parsed_jd import SFUJobDescription
from src.jd_core.rules import Rules, get_rules


def _fake_openai(create: AsyncMock) -> SimpleNamespace:
    return SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create)),
        close=AsyncMock(),
    )


def _response(
    content: str | None = "{}",
    *,
    prompt_tokens: int | None,
    finish_reason: str = "stop",
) -> SimpleNamespace:
    usage = (
        None if prompt_tokens is None else SimpleNamespace(prompt_tokens=prompt_tokens)
    )
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                index=0,
                message=SimpleNamespace(content=content),
                finish_reason=finish_reason,
            )
        ],
        usage=usage,
    )


def _sent_prompt(create: AsyncMock) -> str:
    messages: list[dict[str, Any]] = create.await_args.kwargs["messages"]
    return "".join(str(m["content"]) for m in messages)


# --- the knob ----------------------------------------------------------------------


def test_the_minimum_window_is_rulebook_data_and_ships_32768() -> None:
    """32,768 = the measured rewrite need (prompt p99 ~8k + HR-178's 8,192 output,
    whose reasoning alone peaked ~5,900) with headroom, rounded to the power of two
    Ollama's ``OLLAMA_CONTEXT_LENGTH`` is normally set to."""
    assert get_rules().rewrite.min_context_tokens == 32768


# --- the probe ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_host_that_keeps_the_whole_probe_passes() -> None:
    create = AsyncMock(return_value=_response(prompt_tokens=36_100))
    client = ChatClient(client=_fake_openai(create), rules=get_rules())

    kept = await client.assert_context_window(32_768)

    assert kept == 36_100
    kwargs = create.await_args.kwargs
    assert kwargs["max_tokens"] == 1  # the probe costs prompt processing, not output
    # A tokenizer gives every space-separated word AT LEAST one token, so a probe of
    # >= minimum words is >= minimum tokens: a kept count below it can only be a cut.
    assert len(_sent_prompt(create).split()) >= 32_768


@pytest.mark.asyncio
async def test_a_host_that_cut_the_probe_refuses_the_pass() -> None:
    """THE 2026-11-21 shape: the server answered, no error, ``prompt_tokens`` 4096."""
    create = AsyncMock(return_value=_response(prompt_tokens=4096))
    client = ChatClient(client=_fake_openai(create), rules=get_rules())

    with pytest.raises(ContextWindowTooSmallError) as caught:
        await client.assert_context_window(32_768)

    message = str(caught.value)
    assert "4096" in message and "32768" in message
    assert "OLLAMA_CONTEXT_LENGTH" in message  # says what to change, not just "no"
    assert caught.value.kept_tokens == 4096
    assert caught.value.required_tokens == 32_768


@pytest.mark.asyncio
async def test_a_host_that_reports_no_usage_refuses_the_pass() -> None:
    """No ``usage`` means the cut cannot be ruled out. Refusing is the only honest
    answer — assuming a big window is exactly the assumption that failed."""
    create = AsyncMock(return_value=_response(prompt_tokens=None))
    client = ChatClient(client=_fake_openai(create), rules=get_rules())

    with pytest.raises(ContextWindowTooSmallError, match="no token usage"):
        await client.assert_context_window(32_768)


# --- before a pass: which clients are probed ---------------------------------------


def _client_with(create: AsyncMock, rules: Rules, *, model: str) -> ChatClient:
    return ChatClient(client=_fake_openai(create), rules=rules, model=model)


@pytest.mark.asyncio
async def test_a_pass_probes_the_rewrite_model_once_when_the_audit_shares_it() -> None:
    rules = get_rules()
    rewrite_create = AsyncMock(return_value=_response(prompt_tokens=40_000))
    audit_create = AsyncMock(return_value=_response(prompt_tokens=40_000))
    rewrite = _client_with(rewrite_create, rules, model="gpt-oss:120b")
    audit = _client_with(audit_create, rules, model="gpt-oss:120b")

    await _check_context_windows(rewrite, audit, rules)

    assert rewrite_create.await_count == 1
    assert audit_create.await_count == 0  # same model, same loaded runner


@pytest.mark.asyncio
async def test_a_pass_probes_a_different_audit_model_too() -> None:
    """A separately-loaded model has its own window: the audit's small window must
    not hide behind the rewrite's big one."""
    rules = get_rules()
    rewrite = _client_with(
        AsyncMock(return_value=_response(prompt_tokens=40_000)),
        rules,
        model="gpt-oss:120b",
    )
    audit = _client_with(
        AsyncMock(return_value=_response(prompt_tokens=4096)),
        rules,
        model="gpt-oss:20b",
    )

    with pytest.raises(ContextWindowTooSmallError):
        await _check_context_windows(rewrite, audit, rules)


@pytest.mark.asyncio
async def test_a_no_llm_pass_probes_nothing() -> None:
    await _check_context_windows(None, None, get_rules())  # no client, no call


# --- per call: a length stop says so ------------------------------------------------


@pytest.mark.asyncio
async def test_a_rewrite_that_stopped_on_length_says_so_in_its_failure() -> None:
    """P6 records WHY a rewrite failed. A reply cut by ``max_tokens`` / the window
    fails validation like any bad JSON; the reason must name the stop, or a full
    window reads as a model mistake."""
    create = AsyncMock(
        return_value=_response("", prompt_tokens=3000, finish_reason="length")
    )
    client = ChatClient(client=_fake_openai(create), rules=get_rules())

    with pytest.raises(LLMOutputInvalidError, match="stopped on length"):
        await client.chat_json(
            [{"role": "user", "content": "go"}],
            SFUJobDescription,
            max_tokens=8192,
            max_retries=1,
        )
    assert create.await_count == 2  # the repair retry is unchanged (HR-178/HR-179)

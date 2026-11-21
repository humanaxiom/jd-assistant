"""The inference host's context window is checked, not assumed (HR-341).

MEASURED 2026-11-21: ``aria-gb10-2`` served ``gpt-oss:120b`` at a 4,096-token context
(the model's own is 131,072). A ~6k-token probe came back ``prompt_tokens: 4096`` — cut,
with no error — while a rewrite needs the prompt (~1k system + the parse, p99 ~7–8k
tokens) AND up to ``max_tokens`` 8,192 of reasoning + JSON in the same window. Drafts do
not record token usage, so a rewrite of a truncated prompt is indistinguishable in the
Bank from a good one. The v11 full pass sat 61 minutes on its first cluster before it
was stopped.

The guard reads ``context_length`` for the LOADED model from Ollama's ``/api/ps`` (a
metadata call), loading the model with a one-token request first if it is not running.
A smaller window, or none readable, refuses the pass. A full-window test prompt was the
first design; on the shared host a ~33k-token probe did not finish in 15 minutes.

The ``AsyncOpenAI`` and the ``/api/ps`` reader are plain fakes (ADR-003).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from src.jd_bank.canonical.__main__ import _check_context_windows
from src.jd_bank.llm.client import (
    ChatClient,
    ContextWindowTooSmallError,
    LLMOutputInvalidError,
    _ollama_root,
)
from src.jd_core.models.parsed_jd import SFUJobDescription
from src.jd_core.rules import Rules, get_rules

_MODEL = "gpt-oss:120b"


def _fake_openai(create: AsyncMock) -> SimpleNamespace:
    return SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create)),
        close=AsyncMock(),
    )


def _response(
    content: str | None = "{}", *, finish_reason: str = "stop"
) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                index=0,
                message=SimpleNamespace(content=content),
                finish_reason=finish_reason,
            )
        ],
        usage=None,
    )


def _ps(*listings: Sequence[Mapping[str, Any]]) -> AsyncMock:
    """A fake ``/api/ps``: successive calls return successive listings."""
    return AsyncMock(side_effect=list(listings))


def _client(
    ps: AsyncMock, create: AsyncMock | None = None, *, model: str = _MODEL
) -> tuple[ChatClient, AsyncMock]:
    create = create or AsyncMock(return_value=_response())
    client = ChatClient(
        client=_fake_openai(create),
        rules=get_rules(),
        model=model,
        loaded_models=ps,
    )
    return client, create


# --- the knob ----------------------------------------------------------------------


def test_the_minimum_window_is_rulebook_data_and_ships_32768() -> None:
    """32,768 = the measured rewrite need (prompt p99 ~8k + HR-178's 8,192 output,
    whose reasoning alone peaked ~5,900) with headroom, rounded to the power of two
    Ollama's ``OLLAMA_CONTEXT_LENGTH`` is normally set to."""
    assert get_rules().rewrite.min_context_tokens == 32768


# --- the check ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_loaded_model_with_a_big_enough_window_passes_without_inference() -> (
    None
):
    ps = _ps(
        [
            {"name": "gemma4:26b", "context_length": 4096},
            {"name": _MODEL, "context_length": 32768},
        ]
    )
    client, create = _client(ps)

    assert await client.assert_context_window(32768) == 32768
    assert create.await_count == 0  # metadata only: the shared host does no work


@pytest.mark.asyncio
async def test_a_host_serving_a_4096_window_refuses_the_pass() -> None:
    """THE 2026-11-21 shape."""
    client, _ = _client(_ps([{"name": _MODEL, "context_length": 4096}]))

    with pytest.raises(ContextWindowTooSmallError) as caught:
        await client.assert_context_window(32768)

    message = str(caught.value)
    assert "4096" in message and "32768" in message and _MODEL in message
    assert "OLLAMA_CONTEXT_LENGTH" in message  # says what to change, not just "no"
    assert caught.value.window_tokens == 4096


@pytest.mark.asyncio
async def test_another_models_window_does_not_vouch_for_ours() -> None:
    """A big window on a DIFFERENT loaded model says nothing about ours: ours is not
    loaded, so it is loaded with one token and read again."""
    ps = _ps(
        [{"name": "gemma4:26b", "context_length": 131072}],
        [
            {"name": "gemma4:26b", "context_length": 131072},
            {"name": _MODEL, "context_length": 4096},
        ],
    )
    client, create = _client(ps)

    with pytest.raises(ContextWindowTooSmallError):
        await client.assert_context_window(32768)
    assert create.await_count == 1
    assert create.await_args.kwargs["max_tokens"] == 1  # the load costs one token


@pytest.mark.asyncio
async def test_a_model_that_is_not_loaded_is_loaded_then_read() -> None:
    ps = _ps([], [{"name": _MODEL, "context_length": 32768}])
    client, create = _client(ps)

    assert await client.assert_context_window(32768) == 32768
    assert create.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "listing",
    [[], [{"name": _MODEL}], [{"name": _MODEL, "context_length": "32768"}]],
    ids=["never-loads", "no-context-length", "not-a-number"],
)
async def test_a_window_that_cannot_be_read_refuses_the_pass(
    listing: list[dict[str, Any]],
) -> None:
    """Assuming a big window is exactly the assumption that failed."""
    client, _ = _client(_ps(listing, listing))

    with pytest.raises(ContextWindowTooSmallError, match="no context length"):
        await client.assert_context_window(32768)


def test_the_native_api_root_is_the_openai_base_without_v1() -> None:
    assert _ollama_root("http://aria-gb10-2:11434/v1") == "http://aria-gb10-2:11434"
    assert _ollama_root("http://aria-gb10-2:11434/v1/") == "http://aria-gb10-2:11434"
    assert _ollama_root("http://localhost:11434") == "http://localhost:11434"


# --- before a pass: which clients are checked --------------------------------------


@pytest.mark.asyncio
async def test_a_pass_checks_the_rewrite_model_once_when_the_audit_shares_it() -> None:
    rules = get_rules()
    rewrite_ps = _ps([{"name": _MODEL, "context_length": 32768}])
    audit_ps = _ps([{"name": _MODEL, "context_length": 32768}])
    rewrite, _ = _client(rewrite_ps)
    audit, _ = _client(audit_ps)

    await _check_context_windows(rewrite, audit, rules)

    assert rewrite_ps.await_count == 1
    assert audit_ps.await_count == 0  # same model, same loaded runner


@pytest.mark.asyncio
async def test_a_pass_checks_a_different_audit_model_too() -> None:
    """A separately-loaded model has its own window: the audit's small window must
    not hide behind the rewrite's big one."""
    rules: Rules = get_rules()
    rewrite, _ = _client(_ps([{"name": _MODEL, "context_length": 32768}]))
    audit, _ = _client(
        _ps([{"name": "gpt-oss:20b", "context_length": 4096}]), model="gpt-oss:20b"
    )

    with pytest.raises(ContextWindowTooSmallError):
        await _check_context_windows(rewrite, audit, rules)


@pytest.mark.asyncio
async def test_a_no_llm_pass_checks_nothing() -> None:
    await _check_context_windows(None, None, get_rules())  # no client, no call


# --- per call: a length stop says so ------------------------------------------------


@pytest.mark.asyncio
async def test_a_rewrite_that_stopped_on_length_says_so_in_its_failure() -> None:
    """P6 records WHY a rewrite failed. A reply cut by ``max_tokens`` / the window
    fails validation like any bad JSON; the reason must name the stop, or a full
    window reads as a model mistake."""
    create = AsyncMock(return_value=_response("", finish_reason="length"))
    client, _ = _client(_ps(), create)

    with pytest.raises(LLMOutputInvalidError, match="stopped on length"):
        await client.chat_json(
            [{"role": "user", "content": "go"}],
            SFUJobDescription,
            max_tokens=8192,
            max_retries=1,
        )
    assert create.await_count == 2  # the repair retry is unchanged (HR-178/HR-179)

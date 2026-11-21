"""The Ollama chat client (Phase 4.2a): JSON-mode completions, index-safe choice
selection, the retry policy that must never retry a 400, and the invalid-JSON repair
budget.

The client's ``AsyncOpenAI`` is replaced with a plain fake (a ``SimpleNamespace``
standing in for ``.chat.completions.create`` / ``.close``) — ADR-003: unit tests mock
the client, they never touch a live endpoint. The fake is CONTENT-KEYED where it matters
(the choice-index test returns a decoy at position 0 whose ``index`` is wrong, so a
positional read is a writable bug).
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from openai import BadRequestError

from src.jd_bank.llm.client import (
    ChatBadRequestError,
    ChatClient,
    LLMOutputInvalidError,
)
from src.jd_core.models.parsed_jd import SFUJobDescription
from src.jd_core.rules import get_rules
from src.settings import get_settings

_VALID_JSON = '{"title": "Financial Analyst"}'
_GARBAGE = "this is not json at all"


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


def _bad_request_error() -> BadRequestError:
    request = httpx.Request("POST", "http://aria-gb10-2:11434/v1/chat/completions")
    response = httpx.Response(status_code=400, request=request, json={"error": "bad"})
    return BadRequestError(message="bad request", response=response, body=None)


# --- index-safe choice selection ------------------------------------------------


@pytest.mark.asyncio
async def test_the_reply_is_read_from_the_intended_choice_not_by_position() -> None:
    """THE mutation this test exists to catch: a server returning choices out-of-order
    must not have us parse the wrong one. Reading ``choices[0]`` positionally would take
    the decoy garbage at position 0 whose ``index`` is 1 — and fail — but reassembly is
    by ``choice.index``, so index 0 (the valid JSON) is what is parsed."""
    create = AsyncMock(return_value=_response([(1, _GARBAGE), (0, _VALID_JSON)]))
    client = ChatClient(client=_fake_openai(create), rules=get_rules())

    result = await client.chat_json(
        [{"role": "user", "content": "go"}],
        SFUJobDescription,
        max_tokens=256,
        max_retries=0,
    )

    assert result.title == "Financial Analyst"


@pytest.mark.asyncio
async def test_a_response_missing_the_intended_choice_raises() -> None:
    create = AsyncMock(return_value=_response([(1, _VALID_JSON)]))  # no index 0
    client = ChatClient(client=_fake_openai(create), rules=get_rules())

    with pytest.raises(LLMOutputInvalidError, match="index 0"):
        await client.chat_json(
            [{"role": "user", "content": "go"}],
            SFUJobDescription,
            max_tokens=256,
            max_retries=0,
        )


# --- request parameters: temperature, JSON mode, model come from the rulebook ---


@pytest.mark.asyncio
async def test_temperature_from_rules_and_loose_json_mode_are_passed_to_the_api() -> (
    None
):
    """The rewrite is a transform, not a brainstorm — the temperature is a rulebook knob
    (HR-177) and must actually flow through, and the response format must be LOOSE JSON
    mode. The rewrite deliberately does NOT opt into constrained decoding: Ollama's
    structured-output builder 500s on the large nested ``SFUJobDescription`` grammar
    (verified live), so ``chat_json`` defaults to ``{"type": "json_object"}`` and the
    rewrite keeps that default. Only the audit's small schema constrains.
    """
    create = AsyncMock(return_value=_response([(0, _VALID_JSON)]))
    rules = get_rules()
    retuned = rules.model_copy(
        update={"rewrite": rules.rewrite.model_copy(update={"temperature": 0.7})}
    )
    client = ChatClient(client=_fake_openai(create), rules=retuned)

    await client.chat_json(
        [{"role": "user", "content": "go"}],
        SFUJobDescription,
        max_tokens=256,
        max_retries=0,
    )

    assert create.call_args.kwargs["temperature"] == 0.7
    assert create.call_args.kwargs["max_tokens"] == 256
    # loose JSON mode — NOT the schema-constrained form (the rewrite never opts in)
    assert create.call_args.kwargs["response_format"] == {"type": "json_object"}


@pytest.mark.asyncio
async def test_the_model_comes_from_the_rulebook_not_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`get_rules().rewrite.model` (HR-176) — NEVER `settings.agent_model`, the
    harness's OWN coder-agent model. The two are driven to DISTINCT strings so the
    assertion can only pass if the code reads the rulebook: point `client.py` at
    `settings.agent_model` and this goes red immediately."""
    jd_bank_model = "a-distinct-jd-bank-chat-model"
    harness_model = "a-distinct-harness-coder-agent-model"

    settings = get_settings().model_copy(update={"agent_model": harness_model})
    monkeypatch.setattr("src.jd_bank.llm.client.get_settings", lambda: settings)
    rules = get_rules()
    retuned = rules.model_copy(
        update={"rewrite": rules.rewrite.model_copy(update={"model": jd_bank_model})}
    )
    assert retuned.rewrite.model != settings.agent_model  # the test can now fail

    create = AsyncMock(return_value=_response([(0, _VALID_JSON)]))
    client = ChatClient(client=_fake_openai(create), rules=retuned)

    await client.chat_json(
        [{"role": "user", "content": "go"}],
        SFUJobDescription,
        max_tokens=256,
        max_retries=0,
    )

    assert create.call_args.kwargs["model"] == jd_bank_model
    assert create.call_args.kwargs["model"] != harness_model


# --- retry policy: transient retried, a 400 never is ----------------------------


@pytest.mark.asyncio
async def test_a_bad_request_is_never_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    sleep = AsyncMock()
    monkeypatch.setattr("src.jd_bank.llm.client.asyncio.sleep", sleep)
    create = AsyncMock(side_effect=_bad_request_error())
    client = ChatClient(client=_fake_openai(create), rules=get_rules())

    with pytest.raises(ChatBadRequestError):
        await client.chat_json(
            [{"role": "user", "content": "go"}],
            SFUJobDescription,
            max_tokens=256,
            max_retries=1,
        )

    assert create.await_count == 1  # NEVER retried — permanent property of the request
    sleep.assert_not_called()


@pytest.mark.asyncio
async def test_a_transient_error_is_retried_then_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("src.jd_bank.llm.client.asyncio.sleep", AsyncMock())
    create = AsyncMock(
        side_effect=[TimeoutError("reset"), _response([(0, _VALID_JSON)])]
    )
    client = ChatClient(client=_fake_openai(create), rules=get_rules())

    result = await client.chat_json(
        [{"role": "user", "content": "go"}],
        SFUJobDescription,
        max_tokens=256,
        max_retries=0,
    )

    assert result.title == "Financial Analyst"
    assert create.await_count == 2


@pytest.mark.asyncio
async def test_a_persistent_transient_error_is_raised_after_the_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("src.jd_bank.llm.client.asyncio.sleep", AsyncMock())
    create = AsyncMock(side_effect=TimeoutError("still down"))
    client = ChatClient(client=_fake_openai(create), rules=get_rules())

    with pytest.raises(TimeoutError):
        await client.chat_json(
            [{"role": "user", "content": "go"}],
            SFUJobDescription,
            max_tokens=256,
            max_retries=0,
        )

    assert create.await_count == 3  # the full transient budget, then it gives up


# --- invalid JSON: repaired up to max_retries, then LLMOutputInvalidError -------


@pytest.mark.asyncio
async def test_invalid_json_is_retried_up_to_max_retries_then_raises() -> None:
    create = AsyncMock(return_value=_response([(0, _GARBAGE)]))
    client = ChatClient(client=_fake_openai(create), rules=get_rules())

    with pytest.raises(LLMOutputInvalidError):
        await client.chat_json(
            [{"role": "user", "content": "go"}],
            SFUJobDescription,
            max_tokens=256,
            max_retries=1,
        )

    assert create.await_count == 2  # first attempt + one repair retry, then it gives up


@pytest.mark.asyncio
async def test_invalid_json_then_valid_json_succeeds_on_the_repair_retry() -> None:
    create = AsyncMock(
        side_effect=[_response([(0, _GARBAGE)]), _response([(0, _VALID_JSON)])]
    )
    client = ChatClient(client=_fake_openai(create), rules=get_rules())

    result = await client.chat_json(
        [{"role": "user", "content": "go"}],
        SFUJobDescription,
        max_tokens=256,
        max_retries=1,
    )

    assert result.title == "Financial Analyst"
    assert create.await_count == 2
    # the repair nudge was actually appended to the second call's conversation
    second_messages = create.call_args_list[1].kwargs["messages"]
    assert any(m["role"] == "assistant" for m in second_messages)


#: A reply that IS valid JSON but breaks the schema the way FINDINGS §13 class A did:
#: the mandated equivalency sentence filed as a qualification's ``modifier`` (≤ 20).
_EQUIVALENCY = "or an equivalent combination of education, training and experience"
_MODIFIER_TOO_LONG = json.dumps(
    {
        "title": "Financial Analyst",
        "qualifications": [
            {"text": "Bachelor's degree", "kind": "education", "modifier": _EQUIVALENCY}
        ],
    }
)


@pytest.mark.asyncio
async def test_the_repair_nudge_names_the_field_that_failed_validation() -> None:
    """P6 (FINDINGS §13c): the nudge used to say only "not valid JSON matching the
    required schema", so a model that put 67 characters in a 20-character field was
    never told which field — and missed twice, identically. The re-ask must name it."""
    create = AsyncMock(
        side_effect=[
            _response([(0, _MODIFIER_TOO_LONG)]),
            _response([(0, _VALID_JSON)]),
        ]
    )
    client = ChatClient(client=_fake_openai(create), rules=get_rules())

    await client.chat_json(
        [{"role": "user", "content": "go"}],
        SFUJobDescription,
        max_tokens=256,
        max_retries=1,
    )

    nudge = create.call_args_list[1].kwargs["messages"][-1]
    assert nudge["role"] == "user"
    assert "qualifications.0.modifier" in nudge["content"]
    assert "at most 20 characters" in nudge["content"]


@pytest.mark.asyncio
async def test_the_invalid_output_error_says_what_was_wrong_without_the_text() -> None:
    """The raised error is what the producer records as the failure reason, so it must
    name the field and the rule — and must NOT carry the offending value, which is JD
    text (pydantic's own message would print it as ``input_value``)."""
    create = AsyncMock(return_value=_response([(0, _MODIFIER_TOO_LONG)]))
    client = ChatClient(client=_fake_openai(create), rules=get_rules())

    with pytest.raises(LLMOutputInvalidError) as caught:
        await client.chat_json(
            [{"role": "user", "content": "go"}],
            SFUJobDescription,
            max_tokens=256,
            max_retries=0,
        )

    message = str(caught.value)
    assert "qualifications.0.modifier" in message
    assert "at most 20 characters" in message
    assert _EQUIVALENCY not in message
    assert caught.value.problems == (
        "qualifications.0.modifier: String should have at most 20 characters",
    )


@pytest.mark.asyncio
async def test_zero_max_retries_makes_the_first_invalid_reply_fatal() -> None:
    create = AsyncMock(return_value=_response([(0, _GARBAGE)]))
    client = ChatClient(client=_fake_openai(create), rules=get_rules())

    with pytest.raises(LLMOutputInvalidError):
        await client.chat_json(
            [{"role": "user", "content": "go"}],
            SFUJobDescription,
            max_tokens=256,
            max_retries=0,
        )

    assert create.await_count == 1


@pytest.mark.asyncio
async def test_close_delegates_to_the_underlying_openai_client() -> None:
    fake = _fake_openai(AsyncMock())
    client = ChatClient(client=fake, rules=get_rules())

    await client.close()

    fake.close.assert_awaited_once()

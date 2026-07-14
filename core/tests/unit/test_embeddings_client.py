"""The Ollama embedding client (Phase 3.2b): batching, index-safe reassembly, and
the retry policy that must never retry a 400.

The client's ``AsyncOpenAI`` is replaced with a plain fake (a ``SimpleNamespace``
standing in for ``.embeddings.create`` / ``.close``) — ADR-003: unit tests mock the
client, they never touch a live endpoint.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from openai import BadRequestError

from src.jd_bank.embeddings.client import EmbedClient, EmbeddingBadRequestError
from src.jd_core.rules import get_rules
from src.settings import get_settings


def _fake_openai(create: AsyncMock) -> SimpleNamespace:
    return SimpleNamespace(embeddings=SimpleNamespace(create=create), close=AsyncMock())


def _response(items: list[tuple[int, list[float]]]) -> SimpleNamespace:
    data = [SimpleNamespace(index=i, embedding=vec) for i, vec in items]
    return SimpleNamespace(data=data)


def _bad_request_error() -> BadRequestError:
    request = httpx.Request("POST", "http://aria-gb10-2:11434/v1/embeddings")
    response = httpx.Response(
        status_code=400,
        request=request,
        json={"error": "the input length exceeds the context length"},
    )
    return BadRequestError(
        message="the input length exceeds the context length",
        response=response,
        body=None,
    )


# --- index-safe reassembly ------------------------------------------------------


@pytest.mark.asyncio
async def test_embed_batch_reassembles_by_index_not_position() -> None:
    """THE mutation this test exists to catch: a server returning results
    out-of-order must not silently swap vectors between texts. Zipping the
    response positionally would pass this test if, and only if, the server never
    reorders — which is precisely the assumption we must not make."""
    create = AsyncMock(
        return_value=_response([(2, [0.2, 0.2]), (0, [0.0, 0.0]), (1, [0.1, 0.1])])
    )
    client = EmbedClient(client=_fake_openai(create), rules=get_rules())

    result = await client.embed_batch(["zero", "one", "two"])

    assert result == [[0.0, 0.0], [0.1, 0.1], [0.2, 0.2]]


@pytest.mark.asyncio
async def test_a_response_missing_an_index_raises_rather_than_guessing() -> None:
    create = AsyncMock(return_value=_response([(0, [0.0])]))  # index 1 never arrives
    client = EmbedClient(client=_fake_openai(create), rules=get_rules())

    with pytest.raises(RuntimeError, match="missing index"):
        await client.embed_batch(["a", "b"])


@pytest.mark.asyncio
async def test_an_empty_batch_never_calls_the_server() -> None:
    create = AsyncMock()
    client = EmbedClient(client=_fake_openai(create), rules=get_rules())

    assert await client.embed_batch([]) == []
    create.assert_not_called()


# --- encoding_format is explicit, and the model comes from the rulebook --------


@pytest.mark.asyncio
async def test_encoding_format_float_is_passed_explicitly() -> None:
    """The SDK may default to base64 — this must never be left implicit."""
    create = AsyncMock(return_value=_response([(0, [0.0])]))
    client = EmbedClient(client=_fake_openai(create), rules=get_rules())

    await client.embed_batch(["only"])

    assert create.call_args.kwargs["encoding_format"] == "float"


@pytest.mark.asyncio
async def test_the_model_comes_from_the_rulebook_not_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`get_rules().embeddings.model` (HR-124) — NEVER `settings.embed_model`, the
    harness's OWN agent-memory model (`GraphMemory`'s `artifact_embeddings` index).

    ⚠ **The first version of this test proved nothing.** It asserted
    `call.kwargs["model"] == rules.embeddings.model` — and since both sources hold
    `"nomic-embed-text"` today, swapping `client.py` to read `settings.embed_model`
    left it GREEN. It pinned a coincidence, not the invariant, and it was the only
    guard on a layering fact `client.py`'s own header spends a paragraph on.

    So the two sources are now driven to THREE distinct values: the rulebook says one
    thing, `settings.embed_model` says another, and the assertion names the rulebook's.
    Point `client.py` at settings and this goes red immediately.
    """
    jd_bank_model = "a-distinct-jd-bank-model"
    harness_model = "a-distinct-harness-agent-memory-model"

    settings = get_settings().model_copy(update={"embed_model": harness_model})
    monkeypatch.setattr("src.jd_bank.embeddings.client.get_settings", lambda: settings)
    rules = get_rules()
    retuned = rules.model_copy(
        update={
            "embeddings": rules.embeddings.model_copy(update={"model": jd_bank_model})
        }
    )
    assert retuned.embeddings.model != settings.embed_model  # the test can now fail

    create = AsyncMock(return_value=_response([(0, [0.0])]))
    client = EmbedClient(client=_fake_openai(create), rules=retuned)

    await client.embed_batch(["only"])

    assert create.call_args.kwargs["model"] == jd_bank_model
    assert create.call_args.kwargs["model"] != harness_model


# --- retry policy: transient errors retried, a 400 never is --------------------


@pytest.mark.asyncio
async def test_a_bad_request_is_never_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    sleep = AsyncMock()
    monkeypatch.setattr("src.jd_bank.embeddings.client.asyncio.sleep", sleep)
    create = AsyncMock(side_effect=_bad_request_error())
    client = EmbedClient(client=_fake_openai(create), rules=get_rules())

    with pytest.raises(EmbeddingBadRequestError):
        await client.embed_batch(["an input over the context length"])

    assert create.await_count == 1  # NEVER retried — a permanent property of the input
    sleep.assert_not_called()


@pytest.mark.asyncio
async def test_a_transient_error_is_retried_then_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("src.jd_bank.embeddings.client.asyncio.sleep", AsyncMock())
    create = AsyncMock(
        side_effect=[TimeoutError("connection reset"), _response([(0, [0.5, 0.5])])]
    )
    client = EmbedClient(client=_fake_openai(create), rules=get_rules())

    result = await client.embed_batch(["retry me"])

    assert result == [[0.5, 0.5]]
    assert create.await_count == 2


@pytest.mark.asyncio
async def test_a_persistent_transient_error_is_raised_after_the_retry_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("src.jd_bank.embeddings.client.asyncio.sleep", AsyncMock())
    create = AsyncMock(side_effect=TimeoutError("still down"))
    client = EmbedClient(client=_fake_openai(create), rules=get_rules())

    with pytest.raises(TimeoutError):
        await client.embed_batch(["never works"])

    assert create.await_count == 3  # the full retry budget, then it gives up


# --- close() delegates ----------------------------------------------------------


@pytest.mark.asyncio
async def test_close_delegates_to_the_underlying_openai_client() -> None:
    fake = _fake_openai(AsyncMock())
    client = EmbedClient(client=fake, rules=get_rules())

    await client.close()

    fake.close.assert_awaited_once()

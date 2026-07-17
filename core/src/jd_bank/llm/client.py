"""Ollama chat client (Phase 4.2a) — ``AsyncOpenAI`` chat completions in JSON mode.

Same client shape and discipline as :class:`~src.jd_bank.embeddings.client.EmbedClient`
(ADR-003): the OpenAI-compatible ``/v1`` surface, ``api_key="ollama"`` (ignored),
transient errors retried with exponential backoff, and a **400 never retried** — an
over-length or malformed request is a permanent property of the request, not a blip.

**The model comes from ``get_rules().rewrite.model`` — NEVER ``settings.agent_model``.**
``settings.agent_model`` is the harness's OWN coder-agent model (``core/src/agents``);
``rules.rewrite.model`` is JD Bank's *rulebook* decision (HR-176), stamped onto
every :class:`~src.jd_core.models.bank.RewrittenDraft`. Reading the harness setting
here would make a JD Bank rewrite silently follow a change nobody made to the JD Bank
rulebook — the two must be free to diverge. (This is the exact invariant the embed
client's header spends a paragraph on; the mutation-proof test drives a rules model that
is a DISTINCT string from ``settings.agent_model`` so the two can be told apart.)
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import Final, TypeVar

from openai import AsyncOpenAI, BadRequestError
from openai.types.chat import ChatCompletion, ChatCompletionMessageParam
from openai.types.shared_params import ResponseFormatJSONObject
from pydantic import BaseModel, ValidationError

from src.jd_core.rules import Rules, get_rules
from src.settings import get_settings

#: Transient-error retry budget (network blips, 5xx, timeouts) — NOT for a 400, which is
#: a permanent property of the request and is never retried (mirrors the embed client).
_MAX_ATTEMPTS: Final[int] = 3
_BACKOFF_SECONDS: Final[float] = 1.0

#: JSON mode — the model returns a single JSON object (the SFU schema). Typed once so
#: mypy --strict accepts it against the SDK's ``response_format`` union.
_JSON_OBJECT: Final[ResponseFormatJSONObject] = {"type": "json_object"}

#: The terse repair nudge appended when a reply does not validate — one more chance to
#: return clean JSON before :class:`LLMOutputInvalidError`.
_REPAIR_NUDGE: Final[str] = (
    "Your previous reply was not valid JSON matching the required schema. Reply again "
    "with ONLY the JSON object — no prose, no commentary, no markdown fences."
)

_M = TypeVar("_M", bound=BaseModel)


class ChatBadRequestError(RuntimeError):
    """The server 400'd on a chat request — bad params or an over-length prompt.

    A PERMANENT property of the request, never a transient fault, so it is never
    retried: re-sending the same request cannot make it valid.
    """


class LLMOutputInvalidError(RuntimeError):
    """The model never returned JSON that validates into the requested schema.

    Raised after the ``max_retries`` repair budget is spent (or immediately if the
    response is structurally unusable — no choice at the intended index).
    """


class ChatClient:
    """Thin wrapper: JSON-mode completion, retry transient errors (never a 400), and
    validate the reply into a pydantic model with a bounded repair retry."""

    def __init__(
        self, *, client: AsyncOpenAI | None = None, rules: Rules | None = None
    ) -> None:
        settings = get_settings()
        self._client = client or AsyncOpenAI(
            base_url=settings.ollama_base_url, api_key="ollama"
        )
        rewrite = (rules if rules is not None else get_rules()).rewrite
        # Rulebook decision (HR-176) — see docstring. NEVER settings.agent_model.
        self._model = rewrite.model
        self._temperature = rewrite.temperature

    async def close(self) -> None:
        await self._client.close()

    async def _create(
        self, messages: Sequence[ChatCompletionMessageParam], max_tokens: int
    ) -> ChatCompletion:
        """One completion, transient errors retried. A 400 is never retried."""
        last_exc: Exception | None = None
        for attempt in range(_MAX_ATTEMPTS):
            try:
                return await self._client.chat.completions.create(
                    model=self._model,
                    messages=list(messages),
                    temperature=self._temperature,
                    max_tokens=max_tokens,
                    response_format=_JSON_OBJECT,
                )
            except BadRequestError as exc:
                # Permanent — re-sending an invalid/over-length request cannot fix it.
                raise ChatBadRequestError(str(exc)) from exc
            except Exception as exc:  # noqa: BLE001 - genuinely "anything transient"
                last_exc = exc
                if attempt == _MAX_ATTEMPTS - 1:
                    raise
                await asyncio.sleep(_BACKOFF_SECONDS * (2**attempt))
        raise RuntimeError(  # pragma: no cover - loop always returns or raises
            "chat request never completed"
        ) from last_exc

    @staticmethod
    def _content_of(response: ChatCompletion) -> str:
        """The intended completion's text — selected by ``choice.index``, NEVER by
        position. A server that reorders ``choices`` (the OpenAI spec allows it; nothing
        here assumes Ollama never will) would otherwise have us parse the wrong reply.
        """
        by_index = {choice.index: choice for choice in response.choices}
        if 0 not in by_index:
            raise LLMOutputInvalidError(
                f"chat response has no choice at index 0 (got indices "
                f"{sorted(by_index)}) — refusing to guess which completion was intended"
            )
        content = by_index[0].message.content
        if content is None:
            raise LLMOutputInvalidError("the intended choice carried no content")
        return content

    async def chat_json(
        self,
        messages: Sequence[ChatCompletionMessageParam],
        model_cls: type[_M],
        *,
        max_tokens: int,
        max_retries: int,
    ) -> _M:
        """Complete ``messages`` and validate the JSON reply into ``model_cls``.

        On invalid JSON / a schema mismatch, re-ask up to ``max_retries`` times with a
        terse repair nudge, then raise :class:`LLMOutputInvalidError`. The MODEL id is
        the rulebook's ``rewrite.model``, never ``settings.agent_model``.
        """
        convo: list[ChatCompletionMessageParam] = list(messages)
        last_error: Exception | None = None
        for attempt in range(max_retries + 1):
            response = await self._create(convo, max_tokens)
            content = self._content_of(response)
            try:
                return model_cls.model_validate_json(content)
            except ValidationError as exc:
                last_error = exc
                if attempt == max_retries:
                    break
                convo = [
                    *convo,
                    {"role": "assistant", "content": content},
                    {"role": "user", "content": _REPAIR_NUDGE},
                ]
        raise LLMOutputInvalidError(
            f"the model did not return valid JSON for {model_cls.__name__} after "
            f"{max_retries + 1} attempt(s)"
        ) from last_error

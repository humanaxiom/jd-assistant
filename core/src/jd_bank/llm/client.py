"""Ollama chat client (Phase 4.2a) — ``AsyncOpenAI`` **schema-constrained** completions.

Since Phase 4.6 the request carries the caller's pydantic JSON Schema as the
``response_format`` (OpenAI "structured outputs" / Ollama native ``format``), not loose
JSON mode, so the server constrains generation to the schema — enums and required keys
included — instead of merely to valid JSON. A per-pass ``reasoning_effort`` knob
(HR-191/HR-192) rides the same rulebook path as ``model``/``temperature``; when unset it
is omitted, leaving the request identical to the pre-4.6 one. See :func:`
_schema_response_format`.

Same client shape and discipline as :class:`~src.jd_bank.embeddings.client.EmbedClient`
(ADR-003): the OpenAI-compatible ``/v1`` surface, ``api_key="ollama"`` (ignored),
transient errors retried with exponential backoff, and a **400 never retried** — an
over-length or malformed request is a permanent property of the request, not a blip.

**The model comes from the RULEBOOK — NEVER ``settings.agent_model``.** Which section
of the rulebook is the CALLER's choice: the 4.2a rewrite constructs the client on
``rules.rewrite.model`` (HR-176, the default fallback), and the 4.2b nuanced quality
audit passes ``model=rules.quality.model`` /
``temperature=rules.quality.temperature`` (HR-185/HR-186) — a SEPARATE decision, so a
rewrite-policy change cannot silently move the audit model. ``settings.agent_model`` is
the harness's OWN coder-agent model (``core/src/agents``) and is never read here: doing
so would make a JD Bank pass silently follow a change nobody made to the JD Bank
rulebook — the two must be free to diverge.
(This is the exact invariant the embed client's header spends a paragraph on; the
mutation-proof tests drive rewrite / quality / agent models as three DISTINCT strings so
they can be told apart.)
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import Final, TypeVar

from openai import AsyncOpenAI, BadRequestError, Omit, omit
from openai.types import ReasoningEffort
from openai.types.chat import ChatCompletion, ChatCompletionMessageParam
from openai.types.shared_params import ResponseFormatJSONSchema
from pydantic import BaseModel, ValidationError

from src.jd_bank.security.egress import assert_inference_host_allowed
from src.jd_core.rules import Rules, get_rules
from src.settings import get_settings

#: Transient-error retry budget (network blips, 5xx, timeouts) — NOT for a 400, which is
#: a permanent property of the request and is never retried (mirrors the embed client).
_MAX_ATTEMPTS: Final[int] = 3
_BACKOFF_SECONDS: Final[float] = 1.0

#: The terse repair nudge appended when a reply does not validate — one more chance to
#: return clean JSON before :class:`LLMOutputInvalidError`.
_REPAIR_NUDGE: Final[str] = (
    "Your previous reply was not valid JSON matching the required schema. Reply again "
    "with ONLY the JSON object — no prose, no commentary, no markdown fences."
)

_M = TypeVar("_M", bound=BaseModel)


def _schema_response_format(model_cls: type[BaseModel]) -> ResponseFormatJSONSchema:
    """The **constrained-decoding** response format for ``model_cls``.

    Instead of loose JSON mode (``{"type": "json_object"}``, which lets the model return
    syntactically-valid JSON that still violates the schema — a Title-Case enum value, a
    missing required key — and fails ``model_validate_json``), we hand the server the
    model's own JSON Schema and ask it to constrain generation to it
    (OpenAI "structured outputs" / Ollama native ``format``). Verified live against
    ``aria-gb10-2`` (gpt-oss:120b): a reply that returns ``"Inclusive Language"`` under
    JSON mode is coerced to the enum member ``"inclusive_language"`` under this form, so
    the audit no longer drops ~24% of JDs to a schema mismatch. The bounded repair retry
    in :meth:`ChatClient.chat_json` stays as the fallback for anything still missed.

    ``strict=True`` asks for exact adherence; ``name`` is the model's class name (a-z /
    0-9 / ``_`` / ``-``, ≤64 chars — every SFU model qualifies).
    """
    return {
        "type": "json_schema",
        "json_schema": {
            "name": model_cls.__name__,
            "schema": model_cls.model_json_schema(),
            "strict": True,
        },
    }


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
        self,
        *,
        client: AsyncOpenAI | None = None,
        rules: Rules | None = None,
        model: str | None = None,
        temperature: float | None = None,
        reasoning_effort: ReasoningEffort | None = None,
    ) -> None:
        settings = get_settings()
        if client is None:
            # NN #5 (build-enforced): never construct a content client against a
            # cloud/third-party host. Runs BEFORE the AsyncOpenAI client exists, so no
            # JD content can leak. An injected client (the test-fake path) is not built
            # from settings and so is not re-checked. See jd_bank.security.egress.
            assert_inference_host_allowed(
                settings.ollama_base_url,
                allowed_hosts=settings.allowed_inference_hosts,
            )
            self._client = AsyncOpenAI(
                base_url=settings.ollama_base_url, api_key="ollama"
            )
        else:
            self._client = client
        rewrite = (rules if rules is not None else get_rules()).rewrite
        # The model / temperature are a RULEBOOK decision — of the pass that
        # constructs the client. When an explicit ``model`` / ``temperature`` is given
        # they WIN (the 4.2b audit binds them to ``rules.quality.*``, HR-185/HR-186);
        # otherwise they fall back to ``rules.rewrite.*`` (HR-176/HR-177) so every 4.2a
        # rewrite call-site is byte-identical. NEVER ``settings.agent_model`` — see the
        # class docstring.
        self._model = model if model is not None else rewrite.model
        self._temperature = (
            temperature if temperature is not None else rewrite.temperature
        )
        # Reasoning effort is the SAME per-pass, unhashed decision shape as model /
        # temperature (HR-191 rewrite, HR-192 audit): an explicit value WINS (the 4.2b
        # audit binds it to ``rules.quality.reasoning_effort`` = ``low``), else it falls
        # back to ``rules.rewrite.reasoning_effort`` (``null`` today) so the rewrite
        # call-sites are byte-identical. ``None`` means "send nothing" — the model's own
        # default, i.e. the pre-4.6 request — and is honoured in :meth:`_create`.
        self._reasoning_effort: ReasoningEffort | None = (
            reasoning_effort
            if reasoning_effort is not None
            else rewrite.reasoning_effort
        )

    async def close(self) -> None:
        await self._client.close()

    async def _create(
        self,
        messages: Sequence[ChatCompletionMessageParam],
        max_tokens: int,
        response_format: ResponseFormatJSONSchema,
    ) -> ChatCompletion:
        """One completion, transient errors retried. A 400 is never retried.

        ``response_format`` carries the schema constraint built from the caller's
        ``model_cls`` (:func:`_schema_response_format`). ``reasoning_effort`` is sent
        only when the rulebook set one; ``None`` -> :data:`openai.omit`, so the request
        is byte-identical to the pre-4.6 one (the model runs at its own default effort).
        """
        effort: ReasoningEffort | Omit = (
            self._reasoning_effort if self._reasoning_effort is not None else omit
        )
        last_exc: Exception | None = None
        for attempt in range(_MAX_ATTEMPTS):
            try:
                return await self._client.chat.completions.create(
                    model=self._model,
                    messages=list(messages),
                    temperature=self._temperature,
                    max_tokens=max_tokens,
                    response_format=response_format,
                    reasoning_effort=effort,
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

        The request is **schema-constrained** to ``model_cls`` (:func:`
        _schema_response_format`), so the server forces the reply to the schema —
        enums, required keys and all — rather than merely to valid JSON. On anything
        constrained decoding still misses (invalid JSON / a schema mismatch), re-ask up
        to ``max_retries`` times with a terse repair nudge, then raise
        :class:`LLMOutputInvalidError`. The MODEL id is the rulebook's ``rewrite.model``
        (or the caller's override), never ``settings.agent_model``.
        """
        response_format = _schema_response_format(model_cls)
        convo: list[ChatCompletionMessageParam] = list(messages)
        last_error: Exception | None = None
        for attempt in range(max_retries + 1):
            response = await self._create(convo, max_tokens, response_format)
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

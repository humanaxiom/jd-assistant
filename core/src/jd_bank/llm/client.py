"""Ollama chat client (Phase 4.2a) — ``AsyncOpenAI`` JSON completions.

Two request shapes, chosen PER CALL by ``chat_json(..., constrain_to_schema=...)``:

* **loose JSON mode** (``{"type": "json_object"}``, the default) — the pre-4.6
  behaviour: the model returns a JSON object and the reply is validated into the
  pydantic model with a bounded repair retry. The 4.2a **rewrite** uses this: its target
  (``SFUJobDescription``) is a large nested schema, and — verified live against
  ``aria-gb10-2`` (gpt-oss:120b) — handing that grammar to Ollama's structured-output
  builder 500s (``failed to load model vocabulary required for format``), which would
  make every rewrite fall back to the deterministic draft. Loose mode rewrites at ~99%.
* **schema-constrained decoding** (``constrain_to_schema=True``) — the request carries
  the caller's own JSON Schema (:func:`_schema_response_format`), so the server
  constrains generation to it (enums and required keys included), not merely to valid
  JSON. The 4.2b **audit** uses this: its target (``JDQualityFindings``) is a small flat
  schema that the builder handles cleanly, and it is what stops gpt-oss returning a
  Title-Case ``"Inclusive Language"`` where ``JDIssueCategory`` wants the enum member —
  the ~24% schema-mismatch that used to drop audits.

A per-pass ``reasoning_effort`` knob (HR-191/HR-192) rides the same rulebook path as
``model``/``temperature``; when unset it is omitted, leaving the request identical to
the pre-4.6 one.

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
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any, Final, TypeVar

import httpx
from openai import AsyncOpenAI, BadRequestError, Omit, omit
from openai.types import ReasoningEffort
from openai.types.chat import ChatCompletion, ChatCompletionMessageParam
from openai.types.shared_params import (
    ResponseFormatJSONObject,
    ResponseFormatJSONSchema,
)
from pydantic import BaseModel, ValidationError

from src.jd_bank.security.egress import assert_inference_host_allowed
from src.jd_core.rules import Rules, get_rules
from src.settings import get_settings

#: Transient-error retry budget (network blips, 5xx, timeouts) — NOT for a 400, which is
#: a permanent property of the request and is never retried (mirrors the embed client).
_MAX_ATTEMPTS: Final[int] = 3
_BACKOFF_SECONDS: Final[float] = 1.0

#: Loose JSON mode — the model returns a single JSON object (validated + repaired
#: client-side). Typed once so mypy --strict accepts it against the SDK's
#: ``response_format`` union. The DEFAULT ``chat_json`` shape and the rewrite's, for the
#: reason in the module docstring (constrained decoding 500s on the big rewrite schema).
_JSON_OBJECT: Final[ResponseFormatJSONObject] = {"type": "json_object"}

#: The terse repair nudge appended when a reply does not validate — one more chance to
#: return clean JSON before :class:`LLMOutputInvalidError`.
_REPAIR_NUDGE: Final[str] = (
    "Your previous reply was not valid JSON matching the required schema. Reply again "
    "with ONLY the JSON object — no prose, no commentary, no markdown fences."
)

_M = TypeVar("_M", bound=BaseModel)


def _schema_response_format(model_cls: type[BaseModel]) -> ResponseFormatJSONSchema:
    """The **constrained-decoding** response format for ``model_cls`` — opt-in, small
    flat schemas only.

    Hands the server the model's own JSON Schema so it constrains generation to it
    (OpenAI "structured outputs" / Ollama native ``format``) rather than merely to valid
    JSON. Verified live against ``aria-gb10-2`` (gpt-oss:120b): a reply that returns
    ``"Inclusive Language"`` under loose JSON mode is coerced to the enum member
    ``"inclusive_language"`` under this form, so the audit no longer drops ~24% of JDs
    to a schema mismatch. The bounded repair retry in :meth:`ChatClient.chat_json` stays
    as the fallback for anything still missed.

    **Small schemas only.** Ollama's builder 500s on a LARGE nested grammar
    (``SFUJobDescription``: ``failed to load model vocabulary required for format``), so
    this is opt-in via ``chat_json(constrain_to_schema=True)`` and used ONLY by the
    audit (``JDQualityFindings`` — 1 def, flat). The rewrite keeps loose mode. See the
    module docstring.

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


#: How many schema problems a repair nudge / error message names. A reply can break
#: dozens of fields at once; the first few tell the model (and the reader of a failure
#: reason) what kind of mistake it was. A diagnostic bound — no JD is judged by it.
_MAX_PROBLEMS_NAMED: Final[int] = 5


def describe_validation_error(exc: ValidationError) -> tuple[str, ...]:
    """``field.path: what is wrong`` lines for a failed validation — P6, FINDINGS §13c.

    Built with ``include_input=False`` on purpose: pydantic's own ``str(exc)`` prints
    each offending value, and on a rewrite that value is JD text. The field path and the
    rule are what the model needs to repair, and what a failure reason needs to say."""
    problems = [
        f"{'.'.join(str(part) for part in err['loc']) or '(the reply)'}: {err['msg']}"
        for err in exc.errors(include_url=False, include_input=False)
    ]
    if len(problems) > _MAX_PROBLEMS_NAMED:
        more = len(problems) - _MAX_PROBLEMS_NAMED
        problems = [*problems[:_MAX_PROBLEMS_NAMED], f"... and {more} more"]
    return tuple(problems)


def _stopped_on_length(response: ChatCompletion) -> bool:
    """Whether the intended choice (index 0) stopped on ``length``. Read defensively:
    a server that omits ``finish_reason`` is treated as not having said so."""
    for choice in getattr(response, "choices", ()):
        if getattr(choice, "index", None) == 0:
            return getattr(choice, "finish_reason", None) == "length"
    return False


def _repair_nudge(problems: Sequence[str]) -> str:
    """The terse nudge plus WHAT failed. Before P6 it said only "not valid JSON
    matching the required schema", so a model that filed a 67-character sentence in a
    20-character field was never told which field — and repeated it identically."""
    if not problems:
        return _REPAIR_NUDGE
    named = "\n".join(f"- {problem}" for problem in problems)
    return f"{_REPAIR_NUDGE}\nWhat did not match the schema:\n{named}"


class LLMOutputInvalidError(RuntimeError):
    """The model never returned JSON that validates into the requested schema.

    Raised after the ``max_retries`` repair budget is spent (or immediately if the
    response is structurally unusable — no choice at the intended index). ``problems``
    names what failed validation on the last reply (field path + rule, never the value);
    it is empty when the response was unusable before validation.
    """

    def __init__(self, message: str, *, problems: Sequence[str] = ()) -> None:
        super().__init__(message)
        self.problems: tuple[str, ...] = tuple(problems)


class ContextWindowTooSmallError(RuntimeError):
    """The inference host serves the chat model with too small a window (HR-341).

    ``window_tokens`` is the ``context_length`` Ollama reports for the LOADED model
    (``/api/ps``), or ``None`` when it could not be read — then a cut cannot be ruled
    out, and assuming a big window is exactly what failed on 2026-11-21 (4,096, every
    longer prompt cut with no error)."""

    def __init__(
        self, *, model: str, window_tokens: int | None, required_tokens: int
    ) -> None:
        self.model = model
        self.window_tokens = window_tokens
        self.required_tokens = required_tokens
        if window_tokens is None:
            what = (
                f"reported no context length for {model}, so a cut cannot be ruled out"
            )
        else:
            what = (
                f"serves {model} with a {window_tokens}-token context: it would "
                f"truncate prompts"
            )
        super().__init__(
            f"the inference host {what}. A rewrite needs a {required_tokens}-token "
            f"window (rewrite.min_context_tokens, HR-341). Raise the model's context "
            f"on the host (Ollama: OLLAMA_CONTEXT_LENGTH) and re-run. Nothing was "
            f"written after the last checkpoint."
        )


#: What a loaded-model listing is: Ollama's ``/api/ps`` ``models`` array.
LoadedModels = Callable[[], Awaitable[Sequence[Mapping[str, Any]]]]

#: Bound on the metadata read. ``/api/ps`` answers from memory; it does not queue
#: behind inference, so a slow answer is a dead host, not a busy one.
_PS_TIMEOUT_SECONDS: Final[float] = 30.0


def _ollama_root(base_url: str) -> str:
    """``http://host:11434/v1`` -> ``http://host:11434`` (the native API's root)."""
    root = base_url.rstrip("/")
    return root[: -len("/v1")] if root.endswith("/v1") else root


async def _ollama_loaded_models() -> Sequence[Mapping[str, Any]]:
    """Ollama's own list of loaded models — ``GET /api/ps`` — with each one's
    ``context_length``. Egress-checked like every inference call (NN #5)."""
    settings = get_settings()
    assert_inference_host_allowed(
        settings.ollama_base_url, allowed_hosts=settings.allowed_inference_hosts
    )
    url = f"{_ollama_root(settings.ollama_base_url)}/api/ps"
    async with httpx.AsyncClient(timeout=_PS_TIMEOUT_SECONDS) as http:
        response = await http.get(url)
        response.raise_for_status()
        body = response.json()
    models = body.get("models") if isinstance(body, dict) else None
    return models if isinstance(models, list) else []


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
        loaded_models: LoadedModels | None = None,
    ) -> None:
        settings = get_settings()
        self._loaded_models: LoadedModels = (
            loaded_models if loaded_models is not None else _ollama_loaded_models
        )
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

    @property
    def model(self) -> str:
        """The model id this client sends — what a window check is a check OF."""
        return self._model

    async def _window_of_loaded_model(self) -> int | None:
        for entry in await self._loaded_models():
            if self._model in (entry.get("name"), entry.get("model")):
                window = entry.get("context_length")
                return window if isinstance(window, int) else None
        return None

    async def assert_context_window(self, minimum_tokens: int) -> int:
        """Prove the host serves this model with at least ``minimum_tokens`` of context
        (HR-341), and return the window.

        Reads ``context_length`` for the LOADED model from Ollama's ``/api/ps`` — a
        metadata call, not inference. If the model is not loaded, one ONE-token request
        loads it first (a server only reports the window of a running model). Raises
        :class:`ContextWindowTooSmallError` when the window is smaller, or cannot be
        read at all.

        It is deliberately not a full-window test prompt. That was the first design,
        and on 2026-11-21 a ~33k-token probe did not finish in 15 minutes on the shared
        host, which processes prompts slowly. Repeated at every checkpoint, it would
        have cost the pass, and everyone else on the host, far more than it protected.
        """
        window = await self._window_of_loaded_model()
        if window is None:
            await self._create(
                [{"role": "user", "content": "Reply with {}."}], 1, _JSON_OBJECT
            )
            window = await self._window_of_loaded_model()
        if window is None or window < minimum_tokens:
            raise ContextWindowTooSmallError(
                model=self._model, window_tokens=window, required_tokens=minimum_tokens
            )
        return window

    async def _create(
        self,
        messages: Sequence[ChatCompletionMessageParam],
        max_tokens: int,
        response_format: ResponseFormatJSONObject | ResponseFormatJSONSchema,
    ) -> ChatCompletion:
        """One completion, transient errors retried. A 400 is never retried.

        ``response_format`` is loose JSON mode (the default / rewrite) or the
        schema-constrained form (the audit's opt-in), chosen by the caller in
        :meth:`chat_json`. ``reasoning_effort`` is sent only when the rulebook set one;
        ``None`` -> :data:`openai.omit`, so the request is byte-identical to the pre-4.6
        one (the model runs at its own default effort).
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
        constrain_to_schema: bool = False,
    ) -> _M:
        """Complete ``messages`` and validate the JSON reply into ``model_cls``.

        ``constrain_to_schema`` picks the request shape (see the module docstring):

        * ``False`` (default) — **loose JSON mode**: the model returns a JSON object,
          validated into ``model_cls`` with the bounded repair retry below. The 4.2a
          rewrite uses this; constraining its large ``SFUJobDescription`` grammar 500s
          Ollama's builder, so loose mode is the safe, ~99% path.
        * ``True`` — **schema-constrained decoding**: the request carries the schema of
          ``model_cls`` (:func:`_schema_response_format`) so the server forces the reply
          to it (enums, required keys and all). The 4.2b audit uses this on its small
          ``JDQualityFindings`` schema; it is what fixes the ~24% enum mismatch.

        On invalid JSON / a schema mismatch, re-ask up to ``max_retries`` times with a
        terse repair nudge, then raise :class:`LLMOutputInvalidError`. The MODEL id is
        the rulebook's ``rewrite.model`` (or the caller's override), never
        ``settings.agent_model``.
        """
        response_format: ResponseFormatJSONObject | ResponseFormatJSONSchema = (
            _schema_response_format(model_cls) if constrain_to_schema else _JSON_OBJECT
        )
        convo: list[ChatCompletionMessageParam] = list(messages)
        last_error: Exception | None = None
        problems: tuple[str, ...] = ()
        stopped_on_length = False
        for attempt in range(max_retries + 1):
            response = await self._create(convo, max_tokens, response_format)
            stopped_on_length = _stopped_on_length(response)
            content = self._content_of(response)
            try:
                return model_cls.model_validate_json(content)
            except ValidationError as exc:
                last_error = exc
                problems = describe_validation_error(exc)
                if attempt == max_retries:
                    break
                convo = [
                    *convo,
                    {"role": "assistant", "content": content},
                    {"role": "user", "content": _repair_nudge(problems)},
                ]
        # A reply cut by max_tokens / the window fails validation like any bad JSON; the
        # reason must say so, or a full window reads as a model mistake (P6, HR-341).
        stop = (
            f" — the last reply stopped on length (max_tokens {max_tokens}, or the "
            f"host's context window)"
            if stopped_on_length
            else ""
        )
        raise LLMOutputInvalidError(
            f"the model did not return valid JSON for {model_cls.__name__} after "
            f"{max_retries + 1} attempt(s){stop}: {'; '.join(problems)}",
            problems=problems,
        ) from last_error

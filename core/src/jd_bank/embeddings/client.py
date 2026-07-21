"""Ollama embedding client (Phase 3.2b) — ``AsyncOpenAI`` pointed at ``aria-gb10-2``.

Same client shape as :class:`~src.memory.graph.GraphMemory` (ADR-003): the
OpenAI-compatible ``/v1`` surface, ``api_key="ollama"`` (Ollama ignores it).

**The model comes from ``get_rules().embeddings.model`` — NEVER
``settings.embed_model``.** Those are two different facts that happen to coincide
today (both ``nomic-embed-text``): ``settings.embed_model`` is the harness's OWN
agent-memory model (:class:`~src.memory.graph.GraphMemory`'s
``artifact_embeddings`` index — lineage-graph retrieval, nothing to do with JD
content), while ``rules.embeddings.model`` is JD Bank's *rulebook* decision
(HR-124), registered and stamped onto every node. Reading the harness setting here
would make a JD Bank re-embed silently follow a change nobody made to the JD Bank
rulebook — the two must be free to diverge.

⚠ That invariant is untestable while the two values *coincide*, and the first cut of
its test proved exactly nothing: it asserted ``call.kwargs["model"] ==
rules.embeddings.model``, which is ``"nomic-embed-text"`` — and so is
``settings.embed_model``. Swapping this line to ``settings.embed_model`` left the
whole suite green. The test now drives a rulebook whose model is a **distinct**
string and a ``settings.embed_model`` that is a **third** one, so the two sources can
actually be told apart.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import Final

from openai import AsyncOpenAI, BadRequestError

from src.jd_bank.security.egress import assert_inference_host_allowed
from src.jd_core.rules import Rules, get_rules
from src.settings import get_settings

#: Transient-error retry budget (network blips, 5xx, timeouts) — NOT for a 400,
#: which is a permanent property of the input and is never retried (see
#: :meth:`EmbedClient.embed_batch`).
_MAX_ATTEMPTS: Final[int] = 3
_BACKOFF_SECONDS: Final[float] = 1.0


class EmbeddingBadRequestError(RuntimeError):
    """The server 400'd — "the input length exceeds the context length" or similar.

    A PERMANENT property of the input (over-length text), never a transient fault,
    so it is never retried. ``embeddings.max_chars`` (HR-126) should prevent this
    on real archive text, but the runner must survive one regardless: a batch that
    400s is caught and recorded as a skip, never a crash.
    """


class EmbedClient:
    """Thin wrapper: batch, reassemble by index, retry transient errors, never a 400."""

    def __init__(
        self, *, client: AsyncOpenAI | None = None, rules: Rules | None = None
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
        self._model = (rules if rules is not None else get_rules()).embeddings.model

    async def close(self) -> None:
        await self._client.close()

    async def embed_batch(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed ``texts``, returned in the SAME order they were given.

        Reassembled by ``data[i].index`` — **never by zipping the response
        positionally.** A server that reorders a batch (the OpenAI spec allows it;
        nothing here assumes Ollama never will) would otherwise put every vector on
        the wrong JD, silently, with every gate green.

        Raises:
            EmbeddingBadRequestError: the server 400'd — see the class docstring. Every
                other exception (network, timeout, 5xx) is retried up to
                :data:`_MAX_ATTEMPTS` times with a linear backoff, then re-raised.
        """
        if not texts:
            return []

        response = None
        last_exc: Exception | None = None
        for attempt in range(_MAX_ATTEMPTS):
            try:
                response = await self._client.embeddings.create(
                    model=self._model,
                    input=list(texts),
                    encoding_format="float",  # explicit: the SDK may default to base64
                )
                break
            except BadRequestError as exc:
                # Permanent — retrying an over-length input cannot make it fit.
                raise EmbeddingBadRequestError(str(exc)) from exc
            except Exception as exc:  # noqa: BLE001 - genuinely "anything transient"
                last_exc = exc
                if attempt == _MAX_ATTEMPTS - 1:
                    raise
                await asyncio.sleep(_BACKOFF_SECONDS * (2**attempt))

        if response is None:  # pragma: no cover - loop always returns or raises
            raise RuntimeError("embedding request never completed") from last_exc

        by_index = {item.index: item.embedding for item in response.data}
        missing = sorted(set(range(len(texts))) - set(by_index))
        if missing:
            raise RuntimeError(
                f"embedding response is missing index(es) {missing} for a batch of "
                f"{len(texts)} texts — refusing to guess which vector belongs where"
            )
        return [list(by_index[i]) for i in range(len(texts))]

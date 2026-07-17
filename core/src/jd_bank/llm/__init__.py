"""Reusable self-hosted-LLM scaffolding for JD Bank (Phase 4.2a).

A thin chat client (:class:`~src.jd_bank.llm.client.ChatClient`) and a minimal,
versioned prompt loader (:func:`~src.jd_bank.llm.prompts.load_prompt`) over the
OpenAI-compatible Ollama surface on ``aria-gb10-2`` (ADR-003). Mirrors the embedding
client's discipline: the model is a RULEBOOK decision (``rewrite.model``, never
``settings.agent_model``), transient errors are retried, a 400 never is, and JSON is
validated into a pydantic model before it is trusted.

``jd_core`` must not import ``jd_bank``; this package lives in ``jd_bank`` and imports
``jd_core`` freely (models/rules/validator), never the reverse.
"""

from __future__ import annotations

from src.jd_bank.llm.client import (
    ChatBadRequestError,
    ChatClient,
    LLMOutputInvalidError,
)
from src.jd_bank.llm.prompts import PromptError, RenderedPrompt, load_prompt

__all__ = [
    "ChatBadRequestError",
    "ChatClient",
    "LLMOutputInvalidError",
    "PromptError",
    "RenderedPrompt",
    "load_prompt",
]

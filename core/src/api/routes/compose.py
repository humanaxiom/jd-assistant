"""JD Builder — compose routes (Phases 5.1 + 5.5).

Two stateless endpoints under ``/jd-bank/compose``:

* ``POST /validate`` (5.1) — score an in-progress draft and return its
  :class:`~src.jd_bank.composer.DraftAssessment` (the live compliance panel).
* ``POST /assist/summary`` (5.5) — ask the self-hosted LLM to improve the Position
  Summary and return a :class:`~src.jd_bank.composer.SummarySuggestion` (decision
  support; the author accepts or discards it).

**Nothing publishes here (NN #1);** authoring is read-only until a draft is submitted
to the review queue (5.6). ``/validate`` is pure and DB-free. ``/assist/summary``
constructs a :class:`~src.jd_bank.llm.client.ChatClient` via an injectable factory
(so tests substitute a fake and no network is hit) — the client is egress-guarded at
construction (NN #5) and closed after the call.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from src.jd_bank.composer import (
    DraftAssessment,
    SummarySuggestion,
    assess_draft,
    suggest_summary,
)
from src.jd_bank.llm.client import ChatClient
from src.jd_core.models.parsed_jd import SFUJobDescription

router: APIRouter = APIRouter(prefix="/jd-bank/compose")


def get_chat_client() -> ChatClient:
    """The LLM client for the assist route, as a FastAPI dependency so a test can
    override it with :attr:`app.dependency_overrides` (no network). The real client is
    egress-guarded at construction (NN #5) and bound to ``rules.rewrite.model``."""
    return ChatClient()


@router.post("/validate", response_model=DraftAssessment)
async def validate_draft(jd: SFUJobDescription) -> DraftAssessment:
    """Score an in-progress draft against the SFU rulebook and return the live
    compliance assessment (findings split into guidance vs fix-these)."""
    return assess_draft(jd)


@router.post("/assist/summary", response_model=SummarySuggestion)
async def assist_summary(
    jd: SFUJobDescription,
    client: ChatClient = Depends(get_chat_client),
) -> SummarySuggestion:
    """Suggest an improved Position Summary (LLM, self-hosted), re-validated. The
    author decides whether to accept it; nothing auto-applies or publishes (NN #1)."""
    try:
        return await suggest_summary(jd, client=client)
    finally:
        await client.close()

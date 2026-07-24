"""JD Builder — compose routes (Phases 5.1 + 5.5 + 5.7).

Stateless endpoints under ``/jd-bank/compose``:

* ``POST /validate`` (5.1) — score an in-progress draft and return its
  :class:`~src.jd_bank.composer.DraftAssessment` (the live compliance panel).
* ``POST /assist/summary`` (5.5) — ask the self-hosted LLM to improve the Position
  Summary and return a :class:`~src.jd_bank.composer.SummarySuggestion` (decision
  support; the author accepts or discards it).
* ``POST /export`` (5.7) — render a draft to the official SFU ``.docx`` for download.

**Nothing publishes here (NN #1);** authoring is read-only until a draft is submitted
to the review queue (5.6). ``/validate`` and ``/export`` are pure and DB-free.
``/assist/summary`` constructs a :class:`~src.jd_bank.llm.client.ChatClient` via an
injectable factory (so tests substitute a fake and no network is hit) — the client is
egress-guarded at construction (NN #5) and closed after the call.
"""

from __future__ import annotations

import re

from fastapi import APIRouter, Depends
from fastapi.responses import Response

from src.jd_bank.composer import (
    DraftAssessment,
    SummarySuggestion,
    assess_draft,
    suggest_summary,
)
from src.jd_bank.llm.client import ChatClient
from src.jd_core.models.parsed_jd import SFUJobDescription
from src.jd_export import render_sfu_docx

router: APIRouter = APIRouter(prefix="/jd-bank/compose")

#: The OOXML ``.docx`` media type.
_DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _filename(title: str) -> str:
    """A safe download filename from the JD title (lowercase, hyphenated)."""
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return f"{slug or 'job-description'}.docx"


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


@router.post("/export")
async def export_docx(jd: SFUJobDescription) -> Response:
    """Render a draft to the official SFU ``.docx`` and return it as a download.
    Pure rendering — nothing is validated or published (NN #1)."""
    content = render_sfu_docx(jd)
    return Response(
        content=content,
        media_type=_DOCX_MIME,
        headers={
            "Content-Disposition": f'attachment; filename="{_filename(jd.title)}"'
        },
    )

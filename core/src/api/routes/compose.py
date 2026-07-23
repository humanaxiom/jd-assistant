"""JD Builder — live-compliance route (Phase 5.1).

A single stateless endpoint: ``POST /jd-bank/compose/validate`` takes a structured
draft JD and returns its :class:`~src.jd_bank.composer.DraftAssessment` — the
validator's honest verdict plus the draft-mode split the live authoring panel
draws from.

**Transport only, and stateless.** Unlike the review routes there is no DB session
and no service to mutate: authoring is read-only until a draft is submitted to the
review queue (Phase 5.6). The endpoint just validates the request body into an
``SFUJobDescription`` (FastAPI does that) and calls the pure
:func:`~src.jd_bank.composer.assess_draft`. Nothing publishes here (NN #1); a
draft is never approved by being validated.
"""

from __future__ import annotations

from fastapi import APIRouter

from src.jd_bank.composer import DraftAssessment, assess_draft
from src.jd_core.models.parsed_jd import SFUJobDescription

router: APIRouter = APIRouter(prefix="/jd-bank/compose")


@router.post("/validate", response_model=DraftAssessment)
async def validate_draft(jd: SFUJobDescription) -> DraftAssessment:
    """Score an in-progress draft against the SFU rulebook and return the live
    compliance assessment (findings split into guidance vs fix-these)."""
    return assess_draft(jd)

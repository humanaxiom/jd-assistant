"""Thin FastAPI transport over the Phase-4.4b review service.

**Transport ONLY.** Every invariant — NN #1 (nothing publishes unless the gate decision
permits it), validator-as-oracle, override-needs-a-reason, append-only audit, legal-
transitions-only — lives in :mod:`src.jd_bank.review.service`. A handler here does
exactly one thing: unpack the request, call exactly one service function, commit on
success, serialize the result. The only logic a route owns is the error -> HTTP status
mapping below; nothing here decides whether a JD may publish.

The route COMMITS; the service only ``flush``es (the caller owns the transaction, per
the service's own docstring). On a service error, nothing is committed — the mapped
``HTTPException`` propagates and the session is left uncommitted for the caller
(``get_session``) to close out.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.main import get_session
from src.jd_bank.db.models import CanonicalJD, CanonicalStatus
from src.jd_bank.review import (
    CanonicalNotFoundError,
    GateOverrideError,
    IllegalTransitionError,
    MissingReasonError,
    NotApprovableError,
    ReviewPacket,
    ReviewQueueItem,
    service,
)
from src.jd_core.models.quality import GateOverride

router: APIRouter = APIRouter(prefix="/jd-bank")


# --- request / response schemas -------------------------------------------------------


class ApproveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reviewer_id: str
    overrides: list[GateOverride] = Field(default_factory=list)


class RejectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reviewer_id: str
    reason: str


class EditRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reviewer_id: str
    new_content: dict[str, Any]
    reason: str


class CanonicalOut(BaseModel):
    """The mutation response — a summary, never the full ORM row."""

    model_config = ConfigDict(extra="forbid")

    canonical_id: UUID
    cluster_id: UUID
    version: int
    status: CanonicalStatus


def _canonical_out(canonical: CanonicalJD) -> CanonicalOut:
    return CanonicalOut(
        canonical_id=canonical.id,
        cluster_id=canonical.cluster_id,
        version=canonical.version,
        status=canonical.status,
    )


# --- error -> HTTP status mapping (the ONLY logic these routes own) -------------------
#
# Per docs/tasks/phase-4.4c-review-routes.md's table. Kept in one place so every
# mutation handler maps identically.

_ERROR_STATUS: tuple[tuple[type[Exception], int], ...] = (
    (CanonicalNotFoundError, 404),
    (IllegalTransitionError, 409),
    (NotApprovableError, 409),
    (GateOverrideError, 422),
    (MissingReasonError, 422),
    (ValidationError, 422),
)


def _map_error(exc: Exception) -> HTTPException:
    for exc_type, status_code in _ERROR_STATUS:
        if isinstance(exc, exc_type):
            return HTTPException(status_code=status_code, detail=str(exc))
    raise exc  # pragma: no cover - not one of the service's typed errors


_SERVICE_ERRORS: tuple[type[Exception], ...] = tuple(
    exc_type for exc_type, _ in _ERROR_STATUS
)


# --- routes -----------------------------------------------------------------------
#
# NB: the literal "/review/queue" route MUST be declared before "/review/{canonical_id}"
# so "queue" is never captured as a canonical_id path param.


@router.get("/review/queue", response_model=list[ReviewQueueItem])
async def list_queue(
    limit: int | None = None,
    session: AsyncSession = Depends(get_session),
) -> list[ReviewQueueItem]:
    items = await service.list_review_queue(session, limit=limit)
    return list(items)


@router.get("/review/{canonical_id}", response_model=ReviewPacket)
async def get_packet(
    canonical_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> ReviewPacket:
    packet = await service.get_review_packet(session, canonical_id)
    if packet is None:
        raise HTTPException(status_code=404, detail="canonical JD not found")
    return packet


@router.post("/review/{canonical_id}/approve", response_model=CanonicalOut)
async def approve_canonical(
    canonical_id: UUID,
    body: ApproveRequest,
    session: AsyncSession = Depends(get_session),
) -> CanonicalOut:
    try:
        canonical = await service.approve(
            session,
            canonical_id,
            reviewer_id=body.reviewer_id,
            overrides=body.overrides,
        )
    except _SERVICE_ERRORS as exc:
        raise _map_error(exc) from exc
    await session.commit()
    return _canonical_out(canonical)


@router.post("/review/{canonical_id}/reject", response_model=CanonicalOut)
async def reject_canonical(
    canonical_id: UUID,
    body: RejectRequest,
    session: AsyncSession = Depends(get_session),
) -> CanonicalOut:
    try:
        canonical = await service.reject(
            session,
            canonical_id,
            reviewer_id=body.reviewer_id,
            reason=body.reason,
        )
    except _SERVICE_ERRORS as exc:
        raise _map_error(exc) from exc
    await session.commit()
    return _canonical_out(canonical)


@router.post("/review/{canonical_id}/edit", response_model=CanonicalOut)
async def edit_canonical(
    canonical_id: UUID,
    body: EditRequest,
    session: AsyncSession = Depends(get_session),
) -> CanonicalOut:
    try:
        canonical = await service.edit(
            session,
            canonical_id,
            reviewer_id=body.reviewer_id,
            new_content=body.new_content,
            reason=body.reason,
        )
    except _SERVICE_ERRORS as exc:
        raise _map_error(exc) from exc
    await session.commit()
    return _canonical_out(canonical)

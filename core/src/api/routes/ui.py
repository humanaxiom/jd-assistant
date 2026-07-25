"""Server-rendered review UI — a thin HTML transport over the Phase-4.4b review service.

**Transport ONLY**, exactly like ``src.api.routes.jd_bank`` (4.4c): a handler unpacks
the request, calls exactly ONE service function, commits on success, and renders the
result. On a service error it re-renders the SAME detail page with the error and does
**not** commit. No gate/publish/validation logic lives here — the service
(:mod:`src.jd_bank.review.service`) is the only authority (NN #1). A UI handler cannot
approve a blocked draft any more than the JSON route can — the service raises.

**No new runtime dependency.** POST bodies are ``application/x-www-form-urlencoded``
(the default HTML form enctype — no file uploads) and are parsed from the RAW body
with the stdlib :func:`urllib.parse.parse_qsl`, never FastAPI's ``Form(...)`` params.
NB: on the installed Starlette (1.3.x) even ``await request.form()`` asserts
``python-multipart`` is present — its ``_get_form`` requires ``parse_options_header``
regardless of content type — so ``request.form()`` is deliberately NOT used here;
``parse_qsl`` on ``await request.body()`` keeps this handler dependency-free (see the
module deviation note in the 4.4d task report).

**Escaping.** Jinja2 autoescape is on by default for ``.html`` templates
(:class:`~fastapi.templating.Jinja2Templates`); every JD text field the templates
render — draft, issues, removed content — goes through the normal ``{{ }}`` escaping.
Nothing here uses the ``|safe`` filter on draft content (it is untrusted archive text).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import parse_qsl
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.db.models import User
from src.api.main import get_session
from src.api.routes.auth import require_ui_user
from src.jd_bank.review import (
    CanonicalNotFoundError,
    GateOverrideError,
    IllegalTransitionError,
    MissingReasonError,
    NotApprovableError,
    ReviewPacket,
    service,
)
from src.jd_core.models.quality import GateOverride

router: APIRouter = APIRouter(prefix="/jd-bank/ui")

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

# The typed errors a review-service mutation can raise (mirrors
# ``src.api.routes.jd_bank._SERVICE_ERRORS``) PLUS pydantic's ``ValidationError`` — the
# service reconstructs ``SFUJobDescription`` from an edit's ``new_content`` and raises
# it directly (no service-owned wrapper). None of these ever leave anything committed.
_SERVICE_ERRORS: tuple[type[Exception], ...] = (
    CanonicalNotFoundError,
    IllegalTransitionError,
    NotApprovableError,
    GateOverrideError,
    MissingReasonError,
    ValidationError,
)

#: The naming convention a filled override textarea uses on the approve form:
#: ``override_reason__<gate_id>``. Only fields matching this prefix are read as
#: overrides; every other field is ignored.
_OVERRIDE_PREFIX = "override_reason__"


# --- helpers ---------------------------------------------------------------------


async def _read_form(request: Request) -> list[tuple[str, str]]:
    """Parse the ``application/x-www-form-urlencoded`` POST body into ``(key, value)``
    pairs from the RAW body — no ``request.form()`` (which asserts ``python-multipart``
    on Starlette 1.3.x) and so no new runtime dependency. ``keep_blank_values`` so an
    empty override textarea is still SEEN as blank (and then skipped), never silently
    dropped before it can be recognized as an unfilled field."""
    body = await request.body()
    return parse_qsl(body.decode("utf-8"), keep_blank_values=True)


def _first(pairs: list[tuple[str, str]], key: str, default: str = "") -> str:
    """The first value for ``key`` in the form pairs (an HTML form's scalar field
    appears once), or ``default`` if absent."""
    for k, v in pairs:
        if k == key:
            return v
    return default


def _parse_overrides(
    pairs: list[tuple[str, str]], *, reviewer_id: str
) -> list[GateOverride]:
    """Build one :class:`GateOverride` per FILLED override textarea on the form.

    A blank (or missing) textarea contributes nothing — never a synthesized reason.
    Which gates are legally overridable is enforced by the service (via
    ``apply_overrides``), not here; this only reads what the reviewer wrote.
    """
    overrides: list[GateOverride] = []
    for key, value in pairs:
        if not key.startswith(_OVERRIDE_PREFIX):
            continue
        gate_id = key[len(_OVERRIDE_PREFIX) :]
        text = value.strip()
        if not text:
            continue
        overrides.append(
            GateOverride(gate_id=gate_id, reviewer=reviewer_id, reason=text)
        )
    return overrides


def _detail_context(
    packet: ReviewPacket, *, error: str | None = None
) -> dict[str, Any]:
    """The template context shared by the GET detail page and every POST re-render."""
    diff = (packet.change_log or {}).get("harmonization_diff") or {}
    return {
        "packet": packet,
        "error": error,
        "rendered_draft": diff.get("rendered_draft", ""),
        "removed": diff.get("removed", []),
        "content_json": json.dumps(packet.content, indent=2, sort_keys=True),
    }


async def _rerender_detail_with_error(
    request: Request,
    session: AsyncSession,
    canonical_id: UUID,
    exc: Exception,
) -> HTMLResponse:
    """Re-render the detail page (200) with ``exc`` shown, after a mutation raised and
    NOTHING was committed. Re-fetches the packet fresh (validator-as-oracle) so the
    blocking-gate list a NotApprovableError describes is visible on the page, not just
    in the error text. If the canonical has vanished (CanonicalNotFoundError), the 404
    page is shown instead — there is nothing left to re-render."""
    packet = await service.get_review_packet(session, canonical_id)
    if packet is None:
        return templates.TemplateResponse(
            request,
            "review_not_found.html",
            {"canonical_id": canonical_id},
            status_code=404,
        )
    return templates.TemplateResponse(
        request,
        "review_detail.html",
        _detail_context(packet, error=str(exc)),
        status_code=200,
    )


# --- routes ------------------------------------------------------------------------
#
# NB: the literal "/queue" route MUST be declared before "/review/{canonical_id}" so
# "queue" is never captured as a canonical_id path param (same rule as 4.4c's routes).


@router.get("/queue", response_class=HTMLResponse)
async def queue_view(
    request: Request,
    limit: int | None = None,
    session: AsyncSession = Depends(get_session),
) -> HTMLResponse:
    items = await service.list_review_queue(session, limit=limit)
    return templates.TemplateResponse(request, "review_queue.html", {"items": items})


@router.get("/review/{canonical_id}", response_class=HTMLResponse)
async def detail_view(
    request: Request,
    canonical_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> HTMLResponse:
    packet = await service.get_review_packet(session, canonical_id)
    if packet is None:
        return templates.TemplateResponse(
            request,
            "review_not_found.html",
            {"canonical_id": canonical_id},
            status_code=404,
        )
    return templates.TemplateResponse(
        request, "review_detail.html", _detail_context(packet)
    )


@router.post("/review/{canonical_id}/approve")
async def approve_action(
    request: Request,
    canonical_id: UUID,
    actor: Annotated[User, Depends(require_ui_user)],
    session: AsyncSession = Depends(get_session),
) -> Response:
    pairs = await _read_form(request)
    # The reviewer is the AUTHENTICATED user (NN #1 attribution), not a form field.
    reviewer_id = actor.cas_username
    try:
        overrides = _parse_overrides(pairs, reviewer_id=reviewer_id)
        await service.approve(
            session, canonical_id, reviewer_id=reviewer_id, overrides=overrides
        )
    except _SERVICE_ERRORS as exc:
        return await _rerender_detail_with_error(request, session, canonical_id, exc)
    await session.commit()
    return RedirectResponse(url="/jd-bank/ui/queue", status_code=303)


@router.post("/review/{canonical_id}/reject")
async def reject_action(
    request: Request,
    canonical_id: UUID,
    actor: Annotated[User, Depends(require_ui_user)],
    session: AsyncSession = Depends(get_session),
) -> Response:
    pairs = await _read_form(request)
    reviewer_id = actor.cas_username
    reason = _first(pairs, "reason")
    try:
        await service.reject(
            session, canonical_id, reviewer_id=reviewer_id, reason=reason
        )
    except _SERVICE_ERRORS as exc:
        return await _rerender_detail_with_error(request, session, canonical_id, exc)
    await session.commit()
    return RedirectResponse(url="/jd-bank/ui/queue", status_code=303)


@router.post("/review/{canonical_id}/edit")
async def edit_action(
    request: Request,
    canonical_id: UUID,
    actor: Annotated[User, Depends(require_ui_user)],
    session: AsyncSession = Depends(get_session),
) -> Response:
    pairs = await _read_form(request)
    reviewer_id = actor.cas_username
    reason = _first(pairs, "reason")
    raw_content = _first(pairs, "content")
    try:
        new_content = json.loads(raw_content)
    except json.JSONDecodeError as exc:
        return await _rerender_detail_with_error(request, session, canonical_id, exc)
    try:
        edited = await service.edit(
            session,
            canonical_id,
            reviewer_id=reviewer_id,
            new_content=new_content,
            reason=reason,
        )
    except _SERVICE_ERRORS as exc:
        return await _rerender_detail_with_error(request, session, canonical_id, exc)
    await session.commit()
    return RedirectResponse(url=f"/jd-bank/ui/review/{edited.id}", status_code=303)

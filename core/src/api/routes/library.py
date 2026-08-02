"""Server-rendered content library — the browsable JD Bank.

The answer to "where is the actual content?": read-only pages that render archive
source JDs and harmonized roles as readable text, so HR can *read* a JD rather than only
see a filename, a count, or a dashboard. Four surfaces:

* ``GET /jd-bank/ui/library`` — browse/search the harmonized roles (the primary unit).
* ``GET /jd-bank/ui/role/{cluster_id}`` — one role: its canonical content + the source
  JDs it was distilled from, each opening to its full text.
* ``GET /jd-bank/ui/jd/{source_document_id}`` — one archive source JD, rendered.
* ``GET /jd-bank/ui/archive`` — the flat "all the .docx files" browser.

**Read-only (NN #1).** Every handler calls exactly one :mod:`src.jd_bank.library` read
function and renders it — nothing here mutates a row, publishes, or overrides a gate.
The review service stays the sole approval authority; from a role page a reviewer
*links* to the review queue, which is where approval happens (its own gate applies).

Jinja autoescape is on; no ``|safe`` on JD text (archive/canonical prose is untrusted).
"""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.main import get_session
from src.jd_bank.library import (
    get_role,
    get_source_jd,
    list_roles,
    list_source_jds,
)

router: APIRouter = APIRouter(prefix="/jd-bank/ui")

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


def _pagination(*, total: int, limit: int, offset: int, q: str) -> dict[str, object]:
    """Prev/next offsets + a human "showing N–M of TOTAL" line for a list page."""
    shown_from = offset + 1 if total else 0
    shown_to = min(offset + limit, total)
    return {
        "shown_from": shown_from,
        "shown_to": shown_to,
        "prev_offset": max(0, offset - limit) if offset > 0 else None,
        "next_offset": offset + limit if offset + limit < total else None,
        "limit": limit,
        "q": q,
    }


@router.get("/library", response_class=HTMLResponse)
async def library_view(
    request: Request,
    q: str = "",
    limit: int | None = None,
    offset: int = 0,
    session: AsyncSession = Depends(get_session),
) -> HTMLResponse:
    """Browse/search the harmonized roles — HR's home for the JD content."""
    page = await list_roles(session, q=q, limit=limit, offset=offset)
    return templates.TemplateResponse(
        request,
        "library.html",
        {
            "page": page,
            "pagination": _pagination(
                total=page.total, limit=page.limit, offset=page.offset, q=page.q
            ),
        },
    )


@router.get("/role/{cluster_id}", response_class=HTMLResponse)
async def role_view(
    request: Request,
    cluster_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> HTMLResponse:
    """One harmonized role: its content rendered readable + the source JDs behind it."""
    role = await get_role(session, cluster_id)
    if role is None:
        return templates.TemplateResponse(
            request,
            "library_not_found.html",
            {"what": "role", "id": cluster_id},
            status_code=404,
        )
    return templates.TemplateResponse(request, "role_detail.html", {"role": role})


@router.get("/jd/{source_document_id}", response_class=HTMLResponse)
async def source_jd_view(
    request: Request,
    source_document_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> HTMLResponse:
    """One archive source JD, rendered readable — the actual content of a .docx."""
    view = await get_source_jd(session, source_document_id)
    if view is None:
        return templates.TemplateResponse(
            request,
            "library_not_found.html",
            {"what": "source JD", "id": source_document_id},
            status_code=404,
        )
    return templates.TemplateResponse(request, "jd_view.html", {"view": view})


@router.get("/archive", response_class=HTMLResponse)
async def archive_view(
    request: Request,
    q: str = "",
    limit: int | None = None,
    offset: int = 0,
    session: AsyncSession = Depends(get_session),
) -> HTMLResponse:
    """The flat source-archive browser — every ingested .docx, each opening its text."""
    page = await list_source_jds(session, q=q, limit=limit, offset=offset)
    return templates.TemplateResponse(
        request,
        "archive.html",
        {
            "page": page,
            "pagination": _pagination(
                total=page.total, limit=page.limit, offset=page.offset, q=page.q
            ),
        },
    )

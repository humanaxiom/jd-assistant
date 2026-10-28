"""Server-rendered content library — the browsable JD Bank.

The answer to "where is the actual content?": read-only pages that render archive
source JDs and harmonized roles as readable text, so HR can *read* a JD rather than only
see a filename, a count, or a dashboard. Six surfaces:

* ``GET /jd-bank/ui/library`` — browse/search the harmonized roles (the primary unit).
* ``GET /jd-bank/ui/role/{cluster_id}`` — one role: its canonical content + the source
  JDs it was distilled from, each opening to its full text.
* ``GET /jd-bank/ui/jd/{source_document_id}`` — one archive source JD, rendered.
* ``GET /jd-bank/ui/archive`` — the flat "all the .docx files" browser.
* ``GET /jd-bank/ui/collection/{slug}`` — one functional family (Phase A2): its roles,
  the compression behind them, and — under ``?queue=1`` — the ranked candidates a human
  has yet to rule on.
* ``GET /jd-bank/ui/funnel`` — the LIVE archive → published funnel + facets
  (Phase A4/A5), for a scope (``?scope=it``) or the whole Bank.
* ``GET`` / ``POST /jd-bank/ui/role/{cluster_id}/comp-requisition`` — SFU's
  Compensation Requisition Form, prefilled from the role (Track K, K3): the page
  offers the requester's choices (request type, which ONE position, the Word
  attachment); the POST streams the filled PDF. It persists nothing — it is a POST
  because it carries choices, not because it writes.

**Read-only (NN #1).** Every handler calls exactly one :mod:`src.jd_bank.library` read
function (or, for the CRF, the :mod:`src.jd_bank.forms` prefill read) and renders
it — nothing here mutates a row, publishes, or overrides a gate.
The review service stays the sole approval authority; from a role page a reviewer
*links* to the review queue, which is where approval happens (its own gate applies).

Jinja autoescape is on; no ``|safe`` on JD text (archive/canonical prose is untrusted).
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from neo4j import AsyncDriver
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import may_review
from src.api.main import get_session
from src.api.routes._forms import first_value, read_form_pairs
from src.api.routes.compose import (
    get_optional_embed_client,
    get_optional_neo4j_driver,
)
from src.jd_bank.embeddings.client import EmbedClient
from src.jd_bank.forms import REQUEST_TYPE_LABELS, prefill_from_role
from src.jd_bank.library import (
    build_facets,
    build_funnel,
    build_gap,
    collection_stats,
    family_for,
    get_role,
    get_source_jd,
    list_roles,
    list_source_jds,
    membership_coverage,
    rank_candidates,
    resolve_members,
    scope_for,
)
from src.jd_bank.library.service import SEMANTIC_UNAVAILABLE_BANNER
from src.jd_bank.library.units import resolve_unit, unit_for
from src.jd_export.comp_requisition import (
    CompReqPrefill,
    fill_compensation_requisition,
)

logger = logging.getLogger(__name__)

router: APIRouter = APIRouter(prefix="/jd-bank/ui")


async def _close_quietly(*clients: EmbedClient | AsyncDriver | None) -> None:
    """Close each injected client independently; a failed close can't fail the page."""
    for client in clients:
        if client is None:
            continue
        try:
            await client.close()
        except Exception:  # noqa: BLE001
            logger.exception("failed to close an injected client")


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
    sort: str = "",
    dir: str = "asc",
    session: AsyncSession = Depends(get_session),
    embed_client: EmbedClient | None = Depends(get_optional_embed_client),
    neo4j_driver: AsyncDriver | None = Depends(get_optional_neo4j_driver),
) -> HTMLResponse:
    """Browse/search/sort the harmonized roles — HR's home for the JD content.

    A search is hybrid (title matches, then roles found by meaning). The embedding
    clients are the OPTIONAL factories, so a misconfigured or unreachable inference host
    costs the meaning pass and shows a banner — it never takes the library down.
    """
    try:
        page = await list_roles(
            session,
            q=q,
            limit=limit,
            offset=offset,
            sort=sort,
            direction=dir,
            embed_client=embed_client,
            neo4j_driver=neo4j_driver,
        )
    finally:
        await _close_quietly(embed_client, neo4j_driver)
    if page.q and (embed_client is None or neo4j_driver is None):
        # A client could not even be constructed: same degraded state, same notice.
        page = page.model_copy(update={"banner": SEMANTIC_UNAVAILABLE_BANNER})
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
    # Whether to OFFER the review-queue link. The role page rendered it to everyone, and
    # an `author` (the default new-user role) following it got a raw 403 — the same
    # defect as the nav's Review queue link, one page further in (P0.0).
    return templates.TemplateResponse(
        request,
        "role_detail.html",
        {"role": role, "may_review": may_review(request)},
    )


# ── The Compensation Requisition Form (Track K, K3) ─────────────────────────────


def _crf_filename(title: str | None) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (title or "").lower()).strip("-")[:60]
    return f"compensation-requisition-{slug or 'role'}.pdf"


def _render_crf(
    request: Request,
    cluster_id: UUID,
    prefill: CompReqPrefill,
    *,
    selected: dict[str, object],
    error: str | None,
) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "comp_requisition.html",
        {
            "title": prefill.position_title or "untitled role",
            "cluster_id": cluster_id,
            "prefill": prefill,
            "request_types": list(REQUEST_TYPE_LABELS.items()),
            "selected": selected,
            "error": error,
        },
    )


def _crf_not_found(request: Request, cluster_id: UUID) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "library_not_found.html",
        {"what": "role", "id": cluster_id},
        status_code=404,
    )


@router.get("/role/{cluster_id}/comp-requisition", response_class=HTMLResponse)
async def comp_requisition_view(
    request: Request,
    cluster_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> HTMLResponse:
    """The requester's choices before the download: which section of the form,
    which ONE of the role's positions, whether the Word JD is attached — and what
    the Bank will type in, each marked *confirm*. Reads only; chooses nothing: with
    no request type the Bank fills no section and offers every position."""
    try:
        prefill = await prefill_from_role(session, cluster_id)
    except LookupError:
        return _crf_not_found(request, cluster_id)
    return _render_crf(request, cluster_id, prefill, selected={}, error=None)


@router.post("/role/{cluster_id}/comp-requisition")
async def comp_requisition_download(
    request: Request,
    cluster_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Stream SFU's own Compensation Requisition Form, filled with the role's facts
    and the requester's choices. Pure rendering — nothing is validated, persisted or
    published (NN #1). A choice the role cannot honour (a position it does not hold,
    a request type the form does not have) re-renders the page with the error rather
    than 500 — the page is one a person is standing on."""
    pairs = await read_form_pairs(request)
    request_type = first_value(pairs, "request_type") or None
    position = first_value(pairs, "position_number") or None
    attached = first_value(pairs, "jd_in_word_attached") != ""
    selected: dict[str, object] = {
        "request_type": request_type or "",
        "position_number": position or "",
        "jd_in_word_attached": attached,
    }
    if request_type is not None and request_type not in REQUEST_TYPE_LABELS:
        try:
            prefill = await prefill_from_role(session, cluster_id)
        except LookupError:
            return _crf_not_found(request, cluster_id)
        return _render_crf(
            request,
            cluster_id,
            prefill,
            selected=selected,
            error=f"{request_type!r} is not a request type on the form",
        )
    try:
        prefill = await prefill_from_role(
            session,
            cluster_id,
            request_type,
            jd_in_word_attached=attached,
            position_number=position,
        )
    except LookupError:
        return _crf_not_found(request, cluster_id)
    except ValueError as exc:
        # Re-read without the pick so the page can still offer the picker.
        prefill = await prefill_from_role(session, cluster_id)
        return _render_crf(
            request, cluster_id, prefill, selected=selected, error=str(exc)
        )
    pdf = fill_compensation_requisition(prefill)
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": (
                f'attachment; filename="{_crf_filename(prefill.position_title)}"'
            )
        },
    )


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


@router.get("/collection/{slug}", response_class=HTMLResponse)
async def collection_view(
    request: Request,
    slug: str,
    limit: int | None = None,
    offset: int = 0,
    sort: str = "title",
    dir: str = "asc",
    queue: bool = False,
    session: AsyncSession = Depends(get_session),
) -> HTMLResponse:
    """One functional family as a browsable collection (Phase A2) — the IT demo screen.

    Shows the family's **resolved membership** (SFU's own classification family plus the
    reviewed overrides), the compression behind it, and the family's own recall note.
    ``?queue=1`` switches to the ranked CANDIDATE list — roles that might belong, for a
    human to rule on.

    The two lists are deliberately separate surfaces rather than one filtered list. A
    member is in the family; a candidate is a question. Blending them would put a
    term-score verdict in front of a stakeholder as though it were membership, and that
    verdict was measured to be wrong at every cutoff — 98% recall costs 46% of the
    archive, and a plausible-looking cohort keeps only half the roles SFU itself
    classifies as IT.
    """
    family = family_for(slug)
    if family is None:
        return templates.TemplateResponse(
            request,
            "library_not_found.html",
            {"what": "collection", "id": slug},
            status_code=404,
        )
    stats = await collection_stats(session, family)
    coverage = await membership_coverage(session, family)
    candidates = await rank_candidates(session, family) if queue else ()
    members = await resolve_members(session, family)
    page = await list_roles(
        session,
        limit=limit,
        offset=offset,
        sort=sort,
        direction=dir,
        cluster_ids=members,
    )
    return templates.TemplateResponse(
        request,
        "collection.html",
        {
            "stats": stats,
            "coverage": coverage,
            "page": page,
            "candidates": candidates,
            "showing_queue": queue,
            "pagination": _pagination(
                total=page.total, limit=page.limit, offset=page.offset, q=page.q
            ),
        },
    )


@router.get("/funnel", response_class=HTMLResponse)
async def funnel_view(
    request: Request,
    scope: str | None = None,
    session: AsyncSession = Depends(get_session),
) -> HTMLResponse:
    """The LIVE archive → published funnel and facets for a scope (Phase A4/A5).

    Read from the database at request time. Every other archive-side dashboard renders a
    committed JSON artifact written by a batch run, which is why they drift the moment
    anything is reprocessed — two sources of truth that disagree, and the wrong one gets
    quoted.

    The ``scope`` query parameter selects the set of roles; absent means the whole Bank.
    An unknown scope is a 404 rather than a silent fallback, because a mistyped scope
    showing all 2,493 roles under a unit's name is worse than an error page.
    """
    resolved = await scope_for(session, scope)
    if resolved is None:
        return templates.TemplateResponse(
            request,
            "library_not_found.html",
            {"what": "scope", "id": scope},
            status_code=404,
        )
    return templates.TemplateResponse(
        request,
        "funnel.html",
        {
            "funnel": await build_funnel(session, resolved),
            "facets": await build_facets(session, resolved),
            "gap": (
                await build_gap(session, resolved) if resolved.is_whole_bank else None
            ),
            "scope": resolved,
        },
    )


@router.get("/unit/{slug}", response_class=HTMLResponse)
async def unit_view(
    request: Request,
    slug: str,
    limit: int | None = None,
    offset: int = 0,
    sort: str = "title",
    dir: str = "asc",
    session: AsyncSession = Depends(get_session),
) -> HTMLResponse:
    """One ORG UNIT as a rollup (Track E / MVP-2) — VPFA, Facilities, and their
    children.

    A unit is not a functional family. ``/collection/{slug}`` resolves membership from
    SFU's classification codes in source filenames; a vice-presidency has no code, so
    this resolves on ``department`` against an exact, human-assigned list.

    🔴 **The page publishes THREE numbers** — in the unit, not in it, and department
    unrecorded — because 27.1% of roles state no department and are invisible to any
    rollup. Reporting only the first is how a page reads as complete while being blind
    to
    a quarter of the Bank, which is the defect the IT collection shipped with once.

    It also renders every department assigned to NO unit, commonest first. That list is
    the question the rulebook has not answered, put where somebody can answer it —
    deliberately, rather than inferring a rollup and being confidently wrong about a
    vice-president's own portfolio.
    """
    found = await unit_for(slug)
    if found is None:
        return templates.TemplateResponse(
            request,
            "library_not_found.html",
            {"what": "unit", "id": slug},
            status_code=404,
        )
    unit_key, unit = found
    rollup = await resolve_unit(session, unit, unit_key=unit_key)
    page = await list_roles(
        session,
        limit=limit,
        offset=offset,
        sort=sort,
        direction=dir,
        cluster_ids=rollup.member_cluster_ids,
    )
    return templates.TemplateResponse(
        request,
        "unit.html",
        {
            "rollup": rollup,
            "page": page,
            "pagination": _pagination(
                total=page.total, limit=page.limit, offset=page.offset, q=""
            ),
        },
    )

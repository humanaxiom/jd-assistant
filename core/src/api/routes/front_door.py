"""The front door: the addresses a person types, and the two a browser asks for (P0.0).

``http://localhost:25800`` answered ``{"detail":"Not Found"}``. So did ``/jd-bank`` and
``/jd-bank/ui``. The shallowest address that worked was ``/jd-bank/ui/library``, so
anyone who typed the host — or bookmarked it — landed on a raw JSON error.

**A redirect, not a landing page.** A bespoke home page would duplicate the library's
own introduction and be one more surface to keep true; the library already *is* the home
(``🏦 JD Bank`` is the first nav item). Signed out, the chain is
``/`` → ``/jd-bank/ui/library`` → ``/jd-bank/ui/login?next=…`` → back to the library
after CAS, which is the right landing for a first-time visitor and needs nothing built.

**Public, deliberately.** These routes must answer *before* anyone can sign in — they
are how a visitor reaches the login page at all. They disclose nothing: each one is a
``Location`` header pointing at a route with its own gate.
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse, RedirectResponse, Response

router: APIRouter = APIRouter()

#: Where the front door leads. One constant, so the redirect targets, the error pages'
#: escape link and the nav cannot drift apart.
HOME_PATH = "/jd-bank/ui/library"

#: A 🏦 as an SVG document, small enough to inline. Served at ``/favicon.ico`` AND
#: referenced by ``_base.html`` as a ``data:`` URI, because a browser asks for the .ico
#: on every page load whether or not a page declares an icon — and each of those was a
#: 404 in the log, on the surface whose whole job is having no 404s.
FAVICON_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16">'
    '<text y="14" font-size="14">\U0001f3e6</text></svg>'
)

#: An internal HR system holding unpublished draft job descriptions. It is now reachable
#: by DNS name (see P0.3), so say so to anything that asks.
ROBOTS_TXT = "User-agent: *\nDisallow: /\n"


def _to_home() -> RedirectResponse:
    """A **relative** redirect: the ``Location`` carries no scheme, so it cannot send a
    browser that arrived over https back over http (see :mod:`src.api.errors`)."""
    return RedirectResponse(url=HOME_PATH, status_code=303)


@router.get("/")
async def root() -> RedirectResponse:
    """The bare host — the one address a first-time visitor is most likely to type."""
    return _to_home()


@router.get("/jd-bank")
async def jd_bank_prefix() -> RedirectResponse:
    """The prefix every JD Bank address starts with, which served nothing itself."""
    return _to_home()


@router.get("/jd-bank/ui")
async def jd_bank_ui_prefix() -> RedirectResponse:
    """The UI prefix. ``/jd-bank/ui/`` reaches this through the slash rescue in
    :func:`src.api.errors.slash_variant_redirect` — before these routes existed there
    was nothing for a slash redirect to match, which is why it 404'd instead.
    """
    return _to_home()


@router.get("/favicon.ico", response_class=Response)
async def favicon() -> Response:
    """The tab icon, so the request a browser makes unprompted is not an error."""
    return Response(
        content=FAVICON_SVG,
        media_type="image/svg+xml",
        headers={"cache-control": "public, max-age=86400"},
    )


@router.get("/robots.txt", response_class=PlainTextResponse)
async def robots() -> PlainTextResponse:
    """Refuse indexing outright — nothing in this system belongs in a search engine."""
    return PlainTextResponse(ROBOTS_TXT)

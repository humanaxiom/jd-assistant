"""Errors written for whoever asked, and the slash rescue that replaced a bad redirect.

**The rule, in one sentence:** *a caller whose ``Accept`` includes ``text/html`` gets a
page in the app's own chrome; every other caller keeps the JSON body it has always had.*

That is a property of **the request**, like the CSRF rule next door and for the same
reason: a hardcoded list of UI path prefixes is a list that drifts. ``/jd-bank/ui`` is
not the boundary anyway — a browser can be pointed at a JSON route (it was: a bookmarked
``/jd-bank/review/queue`` is one keystroke away) and an SDK can call a UI one.

── Why this module exists at all ────────────────────────────────────────────────────

The authorization matrix distinguishes a JSON surface from a UI surface for the **status
code**, and nothing distinguished them for the **body**. So every 404, 403, 405, 422 and
500 on a page reached the reader as ``{"detail":"Not Found"}`` — including the stale-tab
CSRF 403 that P0.1b-i made a routine event, whose whole remedy is *reload and submit
again* and whose rendered word was "Forbidden". A reviewer who hits a JSON blob does not
file a bug; they lose confidence.

── The slash rescue, and why it is not ``redirect_slashes`` ─────────────────────────

Starlette's built-in slash redirect builds an **absolute** URL from the request URL, so
behind a TLS-terminating proxy ``/library/`` answered ``307 http://…/library`` — a
downgrade — because uvicorn runs without ``--proxy-headers``. Turning that flag on is a
decision about *trusting a forwarded header*, which is exactly what P0.2 refuses in
production and what P0.3 exists to make safe; it is not a navigability decision, and it
would be the wrong way to buy this. So ``redirect_slashes`` is off and
:func:`slash_variant_redirect` answers instead, with a **relative** ``Location`` that
carries no scheme to get wrong. It resolves the alternate path against the **live
routing table** rather than a list of paths, so it can never rescue an address the app
does not actually serve.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from fastapi import FastAPI, Request
from fastapi.exception_handlers import (
    http_exception_handler as _json_http_exception_handler,
)
from fastapi.exception_handlers import (
    request_validation_exception_handler as _json_validation_handler,
)
from fastapi.exceptions import RequestValidationError
from fastapi.responses import (
    HTMLResponse,
    PlainTextResponse,
    RedirectResponse,
    Response,
)
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.routing import Match

from src.api.csrf import CsrfError
from src.api.deps import resolve_user
from src.settings import Settings, get_settings

_TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

#: The login page, for the "you are not signed in" affordance on a 401/403 page.
LOGIN_PATH = "/jd-bank/ui/login"
#: Where every error page offers to send the reader.
HOME_PATH = "/jd-bank/ui/library"

#: The headline of the 403 a reviewer will actually meet — a tab left open long enough
#: that the CSRF token it carries no longer matches the session it is posting from.
#: Named so the test asserting the copy cannot drift from the copy itself.
STALE_TAB_HEADLINE = "This page was open too long"

#: status -> (headline, what to do about it). Every status the app can hand a browser
#: has a sentence here; a status with no entry falls back to a generic pair, which
#: ``tests/unit/test_navigability.py`` refuses to accept for the ones we actually serve.
COPY: dict[int, tuple[str, str]] = {
    400: (
        "That request could not be read",
        "Something in the address or the form was malformed. Try again from the page "
        "you started on.",
    ),
    401: (
        "Please sign in",
        "This page needs an SFU sign-in before it can show you anything.",
    ),
    403: (
        "You do not have access to that page",
        "Your account is signed in but does not hold the role this page requires. If "
        "you need it, ask an administrator to grant it.",
    ),
    404: (
        "There is nothing at that address",
        "The link may be out of date, or the address may have a typo in it.",
    ),
    405: (
        "That address does not work on its own",
        "It is reached by a button inside the app rather than by typing or bookmarking "
        "it.",
    ),
    422: (
        "That link or form had a value this page could not read",
        "An identifier in the address is not in the form this page expects — most "
        "often a truncated or hand-edited link.",
    ),
    500: (
        "Something went wrong at our end",
        "The problem has been logged. Nothing you were reading has been changed.",
    ),
}

_GENERIC = (
    "Something went wrong",
    "The page could not be shown. Try again from the JD Bank home page.",
)


def wants_html(request: Request) -> bool:
    """Did this caller ask for a page?

    ``text/html`` appears in what every browser sends when a person types an address or
    clicks a link, and in what no SDK sends by default — ``*/*`` (curl, httpx, every
    generated client) is deliberately NOT html: it expresses no preference, and the
    established contract for those callers is JSON.
    """
    return "text/html" in request.headers.get("accept", "")


def _path_is_served(request: Request, path: str) -> bool:
    """Does the **live routing table** serve ``path`` for this request's method?

    Matched the way the router itself matches — every route object in ``app.routes``
    answers ``matches(scope)``, which is how the request would have been dispatched — so
    this cannot drift from what the app serves. ``Match.PARTIAL`` (the path exists but
    not for this method) counts: the address is real, and the honest answer for it is a
    405 page, not a 404.
    """
    scope = dict(request.scope)
    scope["path"] = path
    for route in request.app.routes:
        match, _ = route.matches(scope)
        if match is not Match.NONE:
            return True
    return False


def slash_variant_redirect(request: Request) -> RedirectResponse | None:
    """A **relative** ``307`` to the same address with the trailing slash added or
    removed, when — and only when — that variant is a route the app really serves.

    307, not 303: the method and body must survive, or a form posted to the slashed
    variant would silently become a GET.
    """
    path = request.url.path
    if path == "/":
        return None
    alternate = path[:-1] if path.endswith("/") else f"{path}/"
    if not alternate or not _path_is_served(request, alternate):
        return None
    query = request.url.query
    return RedirectResponse(
        url=f"{alternate}?{query}" if query else alternate, status_code=307
    )


def _settings_for(request: Request) -> Settings:
    """The settings **this app** is running under.

    An exception handler runs outside dependency injection, so ``get_settings()`` alone
    would ignore an override the app has installed — and an error page that disagrees
    with the app about who is reading it is its own defect (it rendered a full admin nav
    to an anonymous visitor while the app itself refused them).
    """
    override = request.app.dependency_overrides.get(get_settings)
    return cast("Settings", override() if override is not None else get_settings())


async def _attach_user(request: Request) -> None:
    """Best-effort identity for the error page's nav, so a signed-in reader who mistypes
    an address still gets their own chrome (and their sign-out button's CSRF token).

    Deliberately swallowing: this runs while already handling an error, on a request
    that may have no session, no DB and — in a unit test — no ``app.state`` at all. An
    error page that raises is the one failure this module may not have.
    """
    if getattr(request.state, "user", None) is not None:
        return
    try:
        await resolve_user(request, _settings_for(request))
    except Exception:  # noqa: BLE001 — an error page must never raise a second error
        return


async def error_page(
    request: Request,
    status_code: int,
    *,
    headline: str | None = None,
    message: str | None = None,
    headers: dict[str, str] | None = None,
) -> HTMLResponse:
    """Render one error as a page in the app's own chrome.

    The requested path is echoed so the reader can see the typo — and it is rendered
    through Jinja's autoescape like any other untrusted string, because an address is
    attacker-controlled text.
    """
    fallback_headline, fallback_message = COPY.get(status_code, _GENERIC)
    await _attach_user(request)
    context: dict[str, Any] = {
        "status_code": status_code,
        "headline": headline or fallback_headline,
        "message": message or fallback_message,
        "path": request.url.path,
        "home_path": HOME_PATH,
        "login_path": LOGIN_PATH,
        # A 401 (and a 403 with nobody signed in) is answered by signing in; a 403 for a
        # user who IS signed in is answered by asking for a role, not another login.
        "offer_sign_in": status_code in (401, 403)
        and getattr(request.state, "user", None) is None,
    }
    return templates.TemplateResponse(
        request,
        "error.html",
        context,
        status_code=status_code,
        headers=headers,
    )


async def http_exception_handler(
    request: Request, exc: Exception
) -> Response:  # pragma: no cover - signature is Starlette's
    """Every ``HTTPException`` in the app — including the 404 and 405 Starlette itself
    raises when nothing matched — answered in the medium the caller asked for."""
    assert isinstance(exc, StarletteHTTPException)
    if exc.status_code == 404:
        rescue = slash_variant_redirect(request)
        if rescue is not None:
            return rescue
    if not wants_html(request):
        return await _json_http_exception_handler(request, exc)
    headline, message = None, None
    if isinstance(exc, CsrfError):
        # The 403 with a specific, actionable cause — see STALE_TAB_HEADLINE.
        headline = STALE_TAB_HEADLINE
        message = (
            "For your security this page carries a token that matches your "
            "sign-in, and the one it submitted no longer does — which is what "
            "happens when a tab has been open for a long time. Reload the page "
            "and submit it again. Nothing was changed."
        )
    return await error_page(
        request,
        exc.status_code,
        headline=headline,
        message=message,
        headers=getattr(exc, "headers", None),
    )


async def validation_exception_handler(
    request: Request, exc: Exception
) -> Response:  # pragma: no cover - signature is Starlette's
    """A 422 for a browser is almost always a hand-edited or truncated link, and the
    pydantic error dump tells its reader nothing. API callers keep the dump — it is the
    contract every client of this app parses."""
    assert isinstance(exc, RequestValidationError)
    if not wants_html(request):
        return await _json_validation_handler(request, exc)
    return await error_page(request, 422)


async def unhandled_exception_handler(request: Request, exc: Exception) -> Response:
    """The 500 page. **Never renders the exception** — a stack trace is not for the
    reader, and it discloses internals; the log already has it."""
    if not wants_html(request):
        return PlainTextResponse("Internal Server Error", status_code=500)
    return await error_page(request, 500)


def install_error_handlers(app: FastAPI) -> None:
    """Wire the handlers, and turn off the redirect that could not name its own scheme.

    Called from :mod:`src.api.main` at import time, beside the router mounts, so the
    behaviour is part of the app rather than of a deployment.
    """
    app.router.redirect_slashes = False
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)

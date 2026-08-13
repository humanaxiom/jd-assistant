"""CAS auth routes + the UI login gate (ADR-008).

Mounted under ``/jd-bank/ui``:

* ``GET  /login``        — the login page (a "Sign in with SFU CAS" button).
* ``GET  /cas/login``    — 302 to the SFU CAS server (or the dev-fake / dev-disabled
  short-circuits).
* ``GET  /cas/validate`` — the ticket consumer: validate -> provision -> session ->
  set cookie -> redirect back into the app.
* ``POST /logout``       — revoke the session, clear the cookie, back to the login page.

In dev (``cas_enabled=False``) every leg short-circuits to the synthetic anonymous user;
nothing reaches ``cas.sfu.ca``. ``require_ui_user`` is the redirect gate the UI routers
use: an unauthenticated visitor is bounced to ``/login`` (a 401 would be wrong for a
browser page); it is transparent in dev mode.
"""

from __future__ import annotations

import logging
import secrets
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Annotated
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.db.models import Role, User
from src.api.deps import NotAuthenticated, resolve_user
from src.api.main import get_session
from src.api.service_origin import resolve_service_origin
from src.api.services import cas_service, session_service, user_service
from src.settings import Settings, get_settings

router: APIRouter = APIRouter(prefix="/jd-bank/ui")
_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

logger = logging.getLogger(__name__)

#: Sentinel ticket only honoured by /cas/validate when cas_dev_fake_user is set. Kept
#: distinctive so it shows loud in logs if it ever appears in a real CAS deployment.
_CAS_DEV_FAKE_TICKET = "DEV-FAKE-CAS-TICKET"

#: Where a visitor goes when they have not asked for anywhere in particular. The library
#: rather than the review queue: `author` is `default_new_user_role`, and the queue is
#: reviewer-or-admin, so the old default landed an ordinary new user on a refusal
#: (P0.0).
DEFAULT_NEXT = "/jd-bank/ui/library"

#: The cookie that binds a CAS round trip to the browser that started it (P0.1b-ii).
#:
#: **This cookie is the entire login-CSRF control**, so it is worth being precise about
#: why. An attacker can always obtain a `state` of their own — `/cas/login` is public —
#: and a `state` echoed only through the URL therefore proves nothing. What they cannot
#: do is set a cookie in the victim's browser. The comparison of the two is the control;
#: the randomness only stops guessing.
LOGIN_STATE_COOKIE = "jdbank_login_state"

#: How long a half-finished login stays valid. Long enough to type a password and clear
#: an MFA prompt, short enough that an abandoned one does not linger.
_LOGIN_STATE_TTL_SECONDS = 15 * 60


def safe_next(value: str | None) -> str:
    """``value`` if it is a path **inside this app**, else :data:`DEFAULT_NEXT`.

    ``next`` is where the browser is sent *after* authenticating, so an off-site value
    is a post-login open redirect: the victim has just typed their SFU credentials into
    a real ``cas.sfu.ca`` page, and whatever they land on inherits that trust. Measured
    before the fix: ``/cas/login?next=https://evil.example/steal`` carried that URL all
    the way through the CAS service parameter.

    **A local path, not an allowlist of hosts** — there is no other host this app should
    ever hand a user to, so the narrower rule is also the simpler one.

    Three spellings a scheme check alone misses, and all three are refused here:

    * ``//evil.example`` — protocol-relative; a browser reads it as an absolute URL.
    * ``\\evil.example`` — several browsers' URL parsers treat a backslash as a slash,
      whatever the RFC says.
    * ``  https://evil.example`` — leading whitespace, stripped by the same parsers.
    """
    candidate = (value or "").strip()
    # Backslashes are normalised to slashes by real parsers, so decide on the normalised
    # form rather than on the bytes that were sent.
    normalised = candidate.replace("\\", "/")
    if not normalised.startswith("/"):
        return DEFAULT_NEXT
    if normalised.startswith("//"):
        return DEFAULT_NEXT
    return candidate


class RedirectToLogin(Exception):  # noqa: N818 — control-flow signal, not an error
    """Raised by :func:`require_ui_user` for an unauthenticated UI request; the app's
    handler turns it into a 303 redirect to the login page (see ``src.api.main``)."""

    def __init__(self, next_path: str) -> None:
        self.next_path = next_path


async def require_ui_user(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
) -> User:
    """UI dependency: the current user, or a redirect to ``/login`` if unauthenticated
    (browsers get a login page, not a 401 JSON body). Transparent in dev mode."""
    try:
        return await resolve_user(request, settings)
    except NotAuthenticated as exc:
        raise RedirectToLogin(request.url.path) from exc


def require_ui_roles(*roles: Role) -> Callable[..., Awaitable[User]]:
    """UI RBAC gate: redirect an unauthenticated visitor to ``/login`` (via
    :func:`require_ui_user`), then 403 an authenticated user who lacks every one of
    ``roles``. Use as a router/route dependency, e.g. the review queue is
    reviewer-or-admin only (NN #1)."""
    allowed = frozenset(roles)

    async def _dep(user: Annotated[User, Depends(require_ui_user)]) -> User:
        if allowed and not (allowed & user.role_names):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"requires one of: {sorted(r.value for r in allowed)}",
            )
        return user

    return _dep


def _set_login_state_cookie(
    response: RedirectResponse, settings: Settings, state: str
) -> None:
    """Bind this round trip to this browser. ``SameSite=Lax`` deliberately, not
    ``Strict``: the CAS return leg is a top-level cross-site GET navigation, which is
    exactly what ``Lax`` allows and ``Strict`` withholds — a Strict cookie here would
    make every real login fail the check it exists to pass."""
    response.set_cookie(
        key=LOGIN_STATE_COOKIE,
        value=state,
        max_age=_LOGIN_STATE_TTL_SECONDS,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
        path="/",
    )


def _service_url(
    settings: Settings, request: Request, next_path: str, state: str = ""
) -> str:
    """The service URL CAS is given — the origin the browser used, **if the deployment
    allows it**, else the static one (P0.3; see :mod:`src.api.service_origin`).

    Login and validate build it identically, because CAS requires the service string to
    match byte-for-byte across the two legs — which is why ``state`` is a parameter here
    rather than being appended by the caller: the validate leg must be able to rebuild
    the *same* string, ``state`` included, from what it received.
    """
    base = resolve_service_origin(request, settings).rstrip("/")
    query = {"next": next_path}
    if state:
        query["state"] = state
    return f"{base}/jd-bank/ui/cas/validate?{urlencode(query)}"


def _set_session_cookie(
    response: RedirectResponse, settings: Settings, sid: str
) -> None:
    response.set_cookie(
        key=settings.session_cookie_name,
        value=sid,
        max_age=settings.session_ttl_hours * 3600,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite=settings.session_cookie_samesite,  # type: ignore[arg-type]
        path="/",
    )


@router.get("/login", response_class=HTMLResponse)
async def login_page(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    next: str = DEFAULT_NEXT,
) -> HTMLResponse:
    """The login page. Its button starts the CAS dance at ``/cas/login``.

    ``next`` is sanitised **here**, not only on the legs that redirect: this page puts
    it into the sign-in link, so an unsanitised value starts the redirect chain before
    CAS is ever involved.
    """
    return templates.TemplateResponse(
        request,
        "login.html",
        {
            "request": request,
            "cas_enabled": settings.cas_enabled,
            "next": safe_next(next),
        },
    )


@router.get("/cas/login")
async def cas_login(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    next: str = DEFAULT_NEXT,
) -> RedirectResponse:
    """Start the CAS dance: 302 to the SFU CAS server (or short-circuit in dev).

    **This is where the round trip is bound to the browser** (P0.1b-ii): a random
    ``state`` is minted, set as an HttpOnly cookie, and echoed to CAS in the service URL
    so it comes back on the other leg. :func:`cas_validate` refuses a mismatch.
    """
    target = safe_next(next)
    if not settings.cas_enabled:
        return RedirectResponse(url=target, status_code=302)

    state = secrets.token_urlsafe(32)
    if settings.cas_dev_fake_user:
        # Skip the SFU round-trip: straight to our own validate with the sentinel — and
        # carrying the same state, so the dev path exercises the real check rather than
        # a bypass around it.
        query = urlencode(
            {"ticket": _CAS_DEV_FAKE_TICKET, "next": target, "state": state}
        )
        response = RedirectResponse(
            url=f"/jd-bank/ui/cas/validate?{query}", status_code=302
        )
        _set_login_state_cookie(response, settings, state)
        return response

    service_url = _service_url(settings, request, target, state)
    login_url = (
        f"{settings.cas_server_url.rstrip('/')}/login?"
        f"{urlencode({'service': service_url})}"
    )
    response = RedirectResponse(url=login_url, status_code=302)
    _set_login_state_cookie(response, settings, state)
    return response


def _refuse_unless_this_browser_started_the_login(
    request: Request, state: str, next_path: str
) -> RedirectResponse | None:
    """``None`` to continue; a redirect back to the start when the round trip was not
    begun by this browser (P0.1b-ii — login CSRF).

    **Why a cookie comparison and not a stored token.** An attacker can obtain a valid
    ``state`` whenever they like — ``/cas/login`` is public — so a state the server
    merely
    *recognises* proves nothing about who holds it. What an attacker cannot do is set a
    cookie in the victim's browser. The comparison of query-to-cookie is the
    control; the randomness only stops guessing, and the ``compare_digest`` only stops
    timing.

    The answer is a **redirect back to login**, not a 403: the honest reading of "no
    state for this round trip" is usually a bookmarked callback, a browser that dropped
    the cookie, or a login left open past the TTL — all answered by starting again, and
    the attacker learns nothing from it either way.
    """
    presented = request.cookies.get(LOGIN_STATE_COOKIE, "")
    if (
        presented
        and state
        and secrets.compare_digest(presented.encode(), state.encode())
    ):
        return None
    logger.warning(
        "refusing a CAS callback with no matching login state (cookie %s, state %s) — "
        "either a stale/bookmarked callback, or a login this browser did not start",
        "present" if presented else "absent",
        "present" if state else "absent",
    )
    response = RedirectResponse(
        url=f"/jd-bank/ui/cas/login?{urlencode({'next': next_path})}", status_code=303
    )
    response.delete_cookie(LOGIN_STATE_COOKIE, path="/")
    return response


@router.get("/cas/validate")
async def cas_validate(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    ticket: str | None = Query(default=None),
    next: str = DEFAULT_NEXT,
    state: str = Query(default=""),
) -> RedirectResponse:
    """Consume the CAS ticket: validate, provision the user, mint a session, set the
    cookie, and redirect into the app. Restarts the dance on a lost ticket.

    **This route mutates on a GET** — it provisions a user, may grant ADMIN through
    ``bootstrap_admins``, mints a session and commits — so it is the one state change
    the app-wide CSRF guard cannot cover (no token can exist before the session it
    belongs
    to). :func:`_refuse_unless_this_browser_started_the_login` is its equivalent, and it
    runs **before the ticket is sent to CAS**: the round trip must not happen on a
    stranger's say-so, and a validated ticket is a decision about who the caller is.
    """
    target = safe_next(next)
    if not settings.cas_enabled:
        return RedirectResponse(url=target, status_code=302)
    if not ticket:
        return RedirectResponse(
            url=f"/jd-bank/ui/cas/login?{urlencode({'next': target})}", status_code=302
        )

    refusal = _refuse_unless_this_browser_started_the_login(request, state, target)
    if refusal is not None:
        return refusal

    if ticket == _CAS_DEV_FAKE_TICKET and settings.cas_dev_fake_user:
        cas_username = settings.cas_dev_fake_user
    else:
        # SFU CAS often needs verify=False — see Settings.cas_verify_tls (prod caveat).
        async with httpx.AsyncClient(verify=settings.cas_verify_tls) as http:
            try:
                cas_username = await cas_service.validate_ticket(
                    cas_server_url=settings.cas_server_url,
                    validate_route=settings.cas_validate_route,
                    # The SAME string the login leg sent, `state` included. CAS compares
                    # the service parameter byte-for-byte across the two legs, so
                    # omitting `state` here would make every real login fail ticket
                    # validation — the control breaking the flow it protects.
                    service_url=_service_url(settings, request, target, state),
                    ticket=ticket,
                    http=http,
                )
            except cas_service.CasValidationError as exc:
                raise NotAuthenticated(f"cas validation failed: {exc}") from exc

    user = await user_service.provision_or_get(
        db,
        cas_username=cas_username,
        default_role=Role(settings.default_new_user_role),
    )
    # First-admin bootstrap: configured usernames are always granted admin on login.
    if cas_username in settings.bootstrap_admins:
        await user_service.ensure_role(db, user, Role.ADMIN)
    session = await session_service.create_session(
        db,
        user_id=user.id,
        ttl_seconds=settings.session_ttl_hours * 3600,
        user_agent=request.headers.get("user-agent"),
        ip=(request.client.host if request.client else None),
    )
    await db.commit()

    response = RedirectResponse(url=target, status_code=302)
    _set_session_cookie(response, settings, session.id)
    # Single-use by intent: the state has done its job, and one left set is one that can
    # be replayed against a later callback.
    response.delete_cookie(LOGIN_STATE_COOKIE, path="/")
    return response


@router.post("/logout")
async def logout(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> RedirectResponse:
    """Revoke the current session, clear the cookie, and return to the login page.

    Deliberately ungated so an *expired* session can still log out rather than be told
    to sign in first. It needs no CSRF exemption either: an authenticated logout revokes
    a session row, so it is a cookie-authenticated state change and takes a token like
    everything else (the button in ``_base.html`` carries one); a logout with no live
    session revokes nothing, so it is not a state change and passes.

    **The session-less path must emit no ``Set-Cookie`` at all** (P0.1b-i). ``SameSite``
    governs which requests *carry* a cookie, not which responses may *set* one — so a
    cross-site ``POST`` here arrives with no cookie (Lax), skips the token check for
    want of a session, and, while this route cleared the cookie unconditionally, still
    achieved a **forced logout without ever holding the victim's cookie**. Nothing is
    lost by not clearing it: the cookie left behind is expired or revoked,
    :func:`~src.api.deps.resolve_user` refuses it, and the next login overwrites it.
    """
    token = request.cookies.get(settings.session_cookie_name)
    live = await session_service.get_active_session(db, token) if token else None
    if token is None or live is None:
        # Nothing to revoke, so nothing to clear — and no header for a cross-site POST
        # to weaponise. Still a 303 to the login page: the escape hatch is intact.
        return RedirectResponse(url="/jd-bank/ui/login", status_code=303)
    await session_service.revoke_session(db, token)
    await db.commit()
    response = RedirectResponse(url="/jd-bank/ui/login", status_code=303)
    response.delete_cookie(settings.session_cookie_name, path="/")
    return response

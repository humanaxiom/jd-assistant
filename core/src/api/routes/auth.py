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
from src.api.services import cas_service, session_service, user_service
from src.settings import Settings, get_settings

router: APIRouter = APIRouter(prefix="/jd-bank/ui")
_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

#: Sentinel ticket only honoured by /cas/validate when cas_dev_fake_user is set. Kept
#: distinctive so it shows loud in logs if it ever appears in a real CAS deployment.
_CAS_DEV_FAKE_TICKET = "DEV-FAKE-CAS-TICKET"


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


def _service_base(settings: Settings, request: Request) -> str:
    """The external base URL CAS redirects back to. With ``cas_service_from_request``,
    derive it from ``X-Forwarded-Host``/-Proto (multi-host / proxied deploys) so login
    works from whatever host the browser used; else the static ``cas_service_base_url``.
    Login and validate derive it identically — CAS requires the service URL to match
    byte-for-byte across the two legs."""
    if settings.cas_service_from_request:
        fwd_host = request.headers.get("x-forwarded-host")
        if fwd_host:
            host = fwd_host.split(",", 1)[0].strip()
            proto = request.headers.get("x-forwarded-proto", "http")
            proto = proto.split(",", 1)[0].strip()
            return f"{proto}://{host}"
    return settings.cas_service_base_url.rstrip("/")


def _service_url(settings: Settings, request: Request, next_path: str) -> str:
    base = _service_base(settings, request).rstrip("/")
    return f"{base}/jd-bank/ui/cas/validate?{urlencode({'next': next_path})}"


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
    next: str = "/jd-bank/ui/queue",
) -> HTMLResponse:
    """The login page. Its button starts the CAS dance at ``/cas/login``."""
    return templates.TemplateResponse(
        request,
        "login.html",
        {
            "request": request,
            "cas_enabled": settings.cas_enabled,
            "next": next,
        },
    )


@router.get("/cas/login")
async def cas_login(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
    next: str = "/jd-bank/ui/queue",
) -> RedirectResponse:
    """Start the CAS dance: 302 to the SFU CAS server (or short-circuit in dev)."""
    if not settings.cas_enabled:
        return RedirectResponse(url=next or "/jd-bank/ui/queue", status_code=302)
    if settings.cas_dev_fake_user:
        # Skip the SFU round-trip: post straight to our own validate with the sentinel.
        query = urlencode({"ticket": _CAS_DEV_FAKE_TICKET, "next": next})
        return RedirectResponse(
            url=f"/jd-bank/ui/cas/validate?{query}", status_code=302
        )
    service_url = _service_url(settings, request, next)
    login_url = (
        f"{settings.cas_server_url.rstrip('/')}/login?"
        f"{urlencode({'service': service_url})}"
    )
    return RedirectResponse(url=login_url, status_code=302)


@router.get("/cas/validate")
async def cas_validate(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    ticket: str | None = Query(default=None),
    next: str = "/jd-bank/ui/queue",
) -> RedirectResponse:
    """Consume the CAS ticket: validate, provision the user, mint a session, set the
    cookie, and redirect into the app. Restarts the dance on a lost ticket."""
    if not settings.cas_enabled:
        return RedirectResponse(url=next or "/jd-bank/ui/queue", status_code=302)
    if not ticket:
        return RedirectResponse(
            url=f"/jd-bank/ui/cas/login?{urlencode({'next': next})}", status_code=302
        )

    if ticket == _CAS_DEV_FAKE_TICKET and settings.cas_dev_fake_user:
        cas_username = settings.cas_dev_fake_user
    else:
        # SFU CAS often needs verify=False — see Settings.cas_verify_tls (prod caveat).
        async with httpx.AsyncClient(verify=settings.cas_verify_tls) as http:
            try:
                cas_username = await cas_service.validate_ticket(
                    cas_server_url=settings.cas_server_url,
                    validate_route=settings.cas_validate_route,
                    service_url=_service_url(settings, request, next),
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

    response = RedirectResponse(url=next or "/jd-bank/ui/queue", status_code=302)
    _set_session_cookie(response, settings, session.id)
    return response


@router.post("/logout")
async def logout(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> RedirectResponse:
    """Revoke the current session, clear the cookie, and return to the login page."""
    token = request.cookies.get(settings.session_cookie_name)
    if token:
        await session_service.revoke_session(db, token)
        await db.commit()
    response = RedirectResponse(url="/jd-bank/ui/login", status_code=303)
    response.delete_cookie(settings.session_cookie_name, path="/")
    return response

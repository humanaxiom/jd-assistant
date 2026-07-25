"""User-management admin UI (ADR-008, phase 3) — admin-only.

Under ``/jd-bank/ui/admin``:

* ``GET  /users``               — the user table (roles + status, editable inline).
* ``POST /users/{id}/roles``    — replace a user's roles.
* ``POST /users/{id}/status``   — activate / disable a user (disable also revokes their
  live sessions).

The whole router is gated to ``admin`` (registered with ``require_ui_roles(Role.ADMIN)``
in :mod:`src.api.main`). Two self-lockout guards mirror HRIS: an admin cannot strip its
own admin role, nor disable itself — else a one-admin deployment could brick its own
access. Dependency-free forms (stdlib ``parse_qsl``), like the rest of the UI.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated
from urllib.parse import parse_qsl
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.db.models import Role, User, UserStatus
from src.api.main import get_session
from src.api.routes.auth import require_ui_user
from src.api.services import session_service, user_service

router: APIRouter = APIRouter(prefix="/jd-bank/ui/admin")
_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

#: The roles the admin form offers, in display order.
_ALL_ROLES = (Role.AUTHOR, Role.REVIEWER, Role.ADMIN)


async def _render_users(
    request: Request, db: AsyncSession, *, error: str | None = None
) -> HTMLResponse:
    users = await user_service.list_users(db)
    return templates.TemplateResponse(
        request,
        "admin_users.html",
        {
            "request": request,
            "users": users,
            "all_roles": _ALL_ROLES,
            "error": error,
        },
    )


@router.get("/users", response_class=HTMLResponse)
async def users_page(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_session)],
) -> HTMLResponse:
    """The user-management table."""
    return await _render_users(request, db)


@router.post("/users/{user_id}/roles")
async def set_user_roles(
    request: Request,
    user_id: UUID,
    db: Annotated[AsyncSession, Depends(get_session)],
    actor: Annotated[User, Depends(require_ui_user)],
) -> Response:
    """Replace ``user_id``'s roles with the checked ones. An admin cannot remove their
    OWN admin role (self-lockout guard)."""
    pairs = parse_qsl((await request.body()).decode("utf-8"))
    roles = {Role(value) for key, value in pairs if key == "roles"}
    if actor.id == user_id and Role.ADMIN not in roles:
        return await _render_users(
            request, db, error="You cannot remove your own admin role."
        )
    await user_service.set_roles(db, user_id, roles)
    await db.commit()
    return RedirectResponse(url="/jd-bank/ui/admin/users", status_code=303)


@router.post("/users/{user_id}/status")
async def set_user_status(
    request: Request,
    user_id: UUID,
    db: Annotated[AsyncSession, Depends(get_session)],
    actor: Annotated[User, Depends(require_ui_user)],
) -> Response:
    """Activate or disable a user. Disabling revokes their live sessions. An admin
    cannot disable themselves (self-lockout guard)."""
    values = dict(parse_qsl((await request.body()).decode("utf-8")))
    status = (
        UserStatus.DISABLED if values.get("status") == "disabled" else UserStatus.ACTIVE
    )
    if actor.id == user_id and status is UserStatus.DISABLED:
        return await _render_users(
            request, db, error="You cannot disable your own account."
        )
    await user_service.set_status(db, user_id, status)
    if status is UserStatus.DISABLED:
        await session_service.revoke_user_sessions(db, user_id)
    await db.commit()
    return RedirectResponse(url="/jd-bank/ui/admin/users", status_code=303)

"""User-management admin UI (ADR-008, phase 3) — admin-only.

Under ``/jd-bank/ui/admin``:

* ``GET  /users``               — the user table (roles + status, editable inline).
* ``POST /users/{id}/roles``    — replace a user's roles.
* ``POST /users/{id}/status``   — activate / disable a user (disable also revokes their
  live sessions).

The whole router is gated to ``admin`` (registered with ``require_ui_roles(Role.ADMIN)``
in :mod:`src.api.main`). Two self-lockout guards mirror HRIS: an admin cannot strip its
own admin role, nor disable itself — else a one-admin deployment could brick its own
access. Dependency-free forms, read through the ONE shared parser
(:func:`src.api.routes._forms.read_form_pairs`), like the rest of the UI — this module
had its own copy and it had drifted, dropping ``keep_blank_values``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.db.models import Role, User, UserStatus
from src.api.main import get_session
from src.api.routes._forms import first_value, read_form_pairs
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
    pairs = await read_form_pairs(request)
    # `if value` because the shared parser keeps blank values (this module's private
    # copy silently dropped them): an empty `roles` field is an unchecked box, not the
    # empty-string role, and `Role("")` would 500 rather than mean anything.
    roles = {Role(value) for key, value in pairs if key == "roles" and value}
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
    pairs = await read_form_pairs(request)
    # NB this is NOT a pure refactor, and the diff should not be read as one. The old
    # `dict(parse_qsl(...)).get("status")` was LAST-wins and dropped blanks; this is
    # FIRST-wins and keeps them. Nothing reachable from the UI submits `status` twice
    # (the form emits one hidden field) and the router is admin-gated, so there is no
    # behaviour change in practice — but a duplicated field would now resolve the other
    # way, and first-wins is the safer of the two for a crafted body.
    status = (
        UserStatus.DISABLED
        if first_value(pairs, "status") == "disabled"
        else UserStatus.ACTIVE
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

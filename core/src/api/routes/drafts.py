"""My drafts — where an author lands after submitting, and can come back to (P0.0).

The defect this closes was the **first-run experience**. ``default_new_user_role`` is
``author``; the Builder's Submit committed the draft, redirected to
``/jd-bank/ui/review/{id}`` — reviewer-or-admin only — and left the author on a raw
``403`` JSON blob **with no sign that their work had saved**. Moving the redirect alone
would not have been enough: the nav also offered them a Review queue link that answered
the same blob, which is why the nav became role-aware in the same change.

**Read-only, and scoped by identity rather than by parameter.** The listing is filtered
by the authenticated user's CAS username, taken from the session
(:func:`~src.api.routes.auth.require_ui_user`) — there is no author parameter to edit,
so this cannot be turned into a reader of someone else's unpublished drafts.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.db.models import User
from src.api.deps import may_review
from src.api.main import get_session
from src.api.routes.auth import require_ui_user
from src.jd_bank.composer import list_authored_drafts

router: APIRouter = APIRouter(prefix="/jd-bank/ui")

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

#: A draft's stored status -> what it means to the person who wrote it. ``archived`` is
#: deliberately not called "rejected": a reviewer's rejection archives the row, and so
#: does approving a NEWER version of the same role, and the row cannot tell them apart.
STATUS_LABEL: dict[str, str] = {
    "draft": "Waiting for HR review",
    "published": "Approved and published",
    "archived": "Closed — either rejected, or replaced by a newer version",
}
STATUS_BADGE: dict[str, str] = {
    "draft": "muted",
    "published": "ok",
    "archived": "warn",
}


@router.get("/my-drafts", response_class=HTMLResponse)
async def my_drafts(
    request: Request,
    actor: Annotated[User, Depends(require_ui_user)],
    submitted: UUID | None = None,
    session: AsyncSession = Depends(get_session),
) -> HTMLResponse:
    """The JDs this author has submitted, newest first.

    ``submitted`` is the canonical id the Builder just created; it is used only to show
    a confirmation line and to mark that row, so a wrong or invented value renders a
    plain list rather than an error — it grants nothing and reveals nothing.
    """
    drafts = await list_authored_drafts(session, author_id=actor.cas_username)
    return templates.TemplateResponse(
        request,
        "my_drafts.html",
        {
            "drafts": drafts,
            "submitted": submitted,
            "status_label": STATUS_LABEL,
            "status_badge": STATUS_BADGE,
            # Whether to offer the review-queue link at all. Offering a link that
            # answers 403 is the defect this page exists to fix, so it is not repeated
            # one line further down.
            "may_review": may_review(request),
        },
    )

"""Serve the rendered operator guide in-app — the "📖 Guide" nav link.

Streams the self-contained ``docs/operator-guide.html`` (built by ``make guide`` from
``docs/OPERATOR-GUIDE.md``, mounted at ``/docs`` in the api container). Gated to any
signed-in user (registered with ``require_ui_user`` in :mod:`src.api.main`). A friendly
404 page if it hasn't been rendered yet.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from src.settings import Settings, get_settings

router: APIRouter = APIRouter(prefix="/jd-bank/ui")


@router.get("/guide", response_class=HTMLResponse)
def operator_guide(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
) -> HTMLResponse:
    """The rendered operator & user guide (a self-contained page). A plain ``def`` route
    so the (blocking) file read runs in the threadpool, not the event loop."""
    try:
        html = Path(settings.operator_guide_path).read_text(encoding="utf-8")
    except OSError:
        return HTMLResponse(
            "<h1>Guide not available</h1><p>Run <code>make guide</code> to render "
            "<code>docs/operator-guide.html</code>.</p>",
            status_code=404,
        )
    return HTMLResponse(html)

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
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse

from src.api.errors import error_page
from src.settings import Settings, get_settings

router: APIRouter = APIRouter(prefix="/jd-bank/ui")


@router.get("/guide", response_class=HTMLResponse)
async def operator_guide(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
) -> HTMLResponse:
    """The rendered operator & user guide (a self-contained page).

    The not-yet-rendered case used to answer a bare ``<h1>`` fragment with no
    ``<html>``, no nav and no way back — a dead end for the reader and a broken
    document for the browser. It now uses the app's own error page like every other
    miss (P0.0). The (blocking) file read is pushed to the threadpool explicitly,
    which is what the route got for free while it was a plain ``def``.
    """
    try:
        html = await run_in_threadpool(
            Path(settings.operator_guide_path).read_text, encoding="utf-8"
        )
    except OSError:
        return await error_page(
            request,
            404,
            headline="The guide has not been rendered yet",
            message=(
                "The operator guide is built from its Markdown source by "
                "`make guide`, and this deployment has not run it (or docs/ is not "
                "mounted into the container)."
            ),
        )
    return HTMLResponse(html)

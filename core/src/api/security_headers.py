"""Response security headers — the ones that keep the CSRF control worth having.

**Why this ships with P0.1b-i rather than on a hardening backlog.** Token CSRF stops a
cross-site page *making* the request. It does nothing about a cross-site page *framing*
ours: put ``/jd-bank/ui/review/{id}`` in an invisible iframe over a decoy button and the
reviewer clicks Approve on our own page, which carries its own perfectly valid token and
posts same-origin. Clickjacking does not bypass the token — it borrows it, and fully
defeats the control. Three response headers preserve the value of the whole feature, so
they belong in the same change.

* ``X-Frame-Options: DENY`` — the legacy header, still what older browsers honour.
* ``Content-Security-Policy: frame-ancestors 'none'`` — the modern replacement, and the
  only directive set. A single-directive CSP is deliberate: adding ``script-src`` or
  ``style-src`` here would break the inline ``<style>`` block every page renders, and
  a broken page is how a CSP gets deleted. Tightening it further is a separate change
  with its own testing.

Implemented as **raw ASGI middleware, not ``BaseHTTPMiddleware``** — the same reasoning
that made the CSRF check a dependency (see :mod:`src.api.csrf`). ``BaseHTTPMiddleware``
re-wraps the request stream, which is exactly what must not happen upstream of handlers
that read their body twice. This only decorates the response-start message and never
touches ``receive``.

``setdefault``, not assignment: a route that deliberately sets its own value keeps it.
"""

from __future__ import annotations

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

#: header -> value, applied to every HTTP response.
SECURITY_HEADERS: dict[str, str] = {
    "x-frame-options": "DENY",
    "content-security-policy": "frame-ancestors 'none'",
}


class SecurityHeadersMiddleware:
    """Add :data:`SECURITY_HEADERS` to every HTTP response."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def _send(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in SECURITY_HEADERS.items():
                    headers.setdefault(name, value)
            await send(message)

        await self.app(scope, receive, _send)

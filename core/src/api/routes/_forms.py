"""The ONE reader of an ``application/x-www-form-urlencoded`` request body.

Every browser surface in this app posts a plain URL-encoded form (no file uploads), and
every one of them used to carry its own two-line copy of the same parser. Three copies
had already drifted — :mod:`src.api.routes.admin` dropped ``keep_blank_values``, so a
field submitted empty vanished before the handler could recognise it as *unfilled*
rather than *absent* — and the CSRF check (P0.1b-i) would have added a fifth. One
function, called by all of them.

**No ``request.form()``, and no ``python-multipart``.** On the installed Starlette
(1.3.x) ``Request.form()`` asserts ``python-multipart`` is importable *regardless of
content type* — its ``_get_form`` needs ``parse_options_header`` before it looks at the
enctype — so using it would add a runtime dependency to read a body the stdlib already
parses. :func:`urllib.parse.parse_qsl` over the raw body keeps this dependency-free.

**Re-reading the body is safe, and this module depends on that.** The CSRF dependency
runs before the handler and reads the body to find the token; the handler then reads it
again to build its answers. Starlette caches the consumed body on ``Request._body`` and
FastAPI hands every dependency and the handler the *same* ``Request`` object, so the
second read is a dict lookup, not a second drain of the stream. (This is precisely why
the CSRF check is a dependency and not a ``BaseHTTPMiddleware``: middleware sees a
different ``Request``, consumes the stream, and has to re-inject it.)
"""

from __future__ import annotations

from urllib.parse import parse_qsl

from fastapi import Request


async def read_form_pairs(request: Request) -> list[tuple[str, str]]:
    """The POST body as ordered ``(key, value)`` pairs.

    ``keep_blank_values=True`` on purpose, and it is not a nicety: the structured
    duty/qualification editors post index-aligned parallel arrays, and a blank cell that
    disappeared would shift every later row onto the wrong record. It is also what lets
    an empty gate-override textarea be *seen* as unfilled and skipped rather than
    silently dropped.

    Raises :class:`UnicodeDecodeError` for a body that is not UTF-8 — a crafted request,
    not something a browser sends. Callers that must not 500 on one (the CSRF check)
    catch it; the existing handlers keep the behaviour they already had.
    """
    body = await request.body()
    return parse_qsl(body.decode("utf-8"), keep_blank_values=True)


def first_value(pairs: list[tuple[str, str]], key: str, default: str = "") -> str:
    """The first value submitted for ``key`` (an HTML form's scalar field appears once),
    or ``default`` when the field is absent."""
    for name, value in pairs:
        if name == key:
            return value
    return default

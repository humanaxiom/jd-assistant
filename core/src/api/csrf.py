"""CSRF protection for cookie-authenticated state changes (P0.1b-i).

**The rule, in one sentence:** *any state-changing request that was authenticated by a
session cookie must carry that session's CSRF token.*

It is deliberately a property of **the request**, not of a route. There is therefore no
per-route allow-list to drift and nothing for the author of the next ``POST`` to
remember: :func:`enforce_csrf` is installed once, as an application-wide dependency in
:mod:`src.api.main`, and a route added tomorrow is covered the moment it exists.

── Why a dependency and not ``BaseHTTPMiddleware`` ──────────────────────────────────

Middleware receives a *different* ``Request`` object from the handler, so reading the
body there consumes the stream and obliges the middleware to re-inject it — a
well-known source of hangs and truncated bodies. A dependency is handed the *same*
``Request`` the handler will get, and Starlette caches the body on it, so the handler's
later ``await request.body()`` is a dict lookup. See :mod:`src.api.routes._forms`.

── Two ways a check like this fails OPEN, both closed here ──────────────────────────

* **It must resolve the session itself.** Reading a token another dependency stashed on
  ``request.state`` looks equivalent and is not: dependency order is not guaranteed to
  put the identity dependency first, and if this one runs first the attribute is simply
  absent — which reads as "no session", i.e. *skip*, i.e. a bypass. So this module does
  the cookie -> session-row lookup itself, exactly as :func:`src.api.deps.resolve_user`
  does, and never trusts a value someone else left behind.
* **The comparison is constant-time** (:func:`secrets.compare_digest`). A token is a
  secret compared against attacker-supplied input; a byte-at-a-time ``==`` leaks its
  prefix through timing.

── Why "no session" is a skip and not a hole ────────────────────────────────────────

A request with no live session has no ambient authority to borrow, so there is nothing
for a cross-site page to abuse — an attacker who does not need the victim's cookie does
not need the victim. Two cases produce it:

* ``cas_enabled=False`` (dev/CI): :func:`~src.api.deps.resolve_user` short-circuits
  before reading any cookie, so no cookie confers anything and no session row exists to
  hold a token. That posture is one ``Settings`` **refuses to load in production**.
* CAS on with no/expired/revoked cookie: every state-changing UI route except ``logout``
  is gated, so authorization refuses the request anyway — and ``logout`` without a live
  session revokes nothing, which is why it needs no exemption written down for it.

Both halves are pinned in ``tests/unit/test_csrf_protection.py``; the token's existence
as a real column on a real row is pinned in
``tests/integration/test_csrf_session_token.py``.

── The JSON API is IN scope, and the header is how it complies ──────────────────────

An earlier draft of this module said ``/jd-bank/review/*`` and ``/jd-bank/compose/*``
were out of scope because a cross-site HTML form cannot express a request they accept
(their bodies are Pydantic models, and the three enctypes a form may send all arrive as
raw bytes that fail validation). **That reasoning is sound for those eight routes and
was the wrong conclusion for the app**, because it does not hold for every JSON route:
``POST /gates/run`` takes ``branch`` as a **query parameter and declares no body at
all**, so a plain ``<form method="POST" action="…/gates/run?branch=x">`` with an admin's
cookie enqueued an arq job. A mount scoped to the browser surface would have left that
open; the app-wide mount closes it, and it is the reason the mount is app-wide.

The consequence is that a cookie-authenticated JSON request must be able to comply, and
a JSON body cannot carry a form field — so :data:`CSRF_HEADER` is that request's ONLY
satisfying path, not a convenience. Deleting it makes every cookie-authenticated call to
those eight routes a permanent 403.

The header is safe because a cross-site page cannot set it: an HTML form has no
mechanism to, and a cross-origin ``fetch`` that does is preflighted — which is only true
while **no CORS middleware is installed**. That is a global property of the app, not of
this module, so it is pinned as one
(``test_csrf_protection.py::test_no_cors_middleware_is_installed``).

**Not register-bearing.** Transport security, not a rulebook metric or an HR policy: no
``decision_register.yaml`` entry, and ``rules_version`` does not move.

── Known gap, deliberately not closed here ──────────────────────────────────────────

Login itself (the ``GET /jd-bank/ui/cas/validate`` leg) is unprotected: it mutates
(see :data:`STATE_CHANGING`), and login CSRF — forcing a victim's browser to sign in as
the attacker — is a real class of attack. It needs the CAS state/``next`` round trip
reworked, which is a change to the login flow rather than to this guard, so it is
recorded for the P0.1b follow-up rather than bolted on here.
"""

from __future__ import annotations

import secrets
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status

from src.api.db.models import Session
from src.api.routes._forms import first_value, read_form_pairs
from src.api.services import session_service
from src.settings import Settings, get_settings

#: The hidden form field the token rides in. Rendered by the ``_csrf.html`` macro and
#: read back here — one name, defined once.
CSRF_FIELD = "csrf_token"

#: The header a JSON client presents its token in — the **only** way the eight
#: Pydantic-bodied JSON routes can comply, since a JSON body cannot carry a form field
#: (see the module docstring). A cross-site HTML form cannot set a header, and a
#: cross-origin ``fetch`` that sets one is preflighted, so this adds no exposure while
#: no CORS middleware is installed — which is pinned as its own test.
CSRF_HEADER = "x-csrf-token"

#: The methods that may change state.
#:
#: ``GET``/``HEAD``/``OPTIONS`` are excluded because requiring a token on a read would
#: break every link and bookmark in the app. **This is a method convention, not a claim
#: that no GET in this service mutates** — one does: ``GET /jd-bank/ui/cas/validate``
#: provisions a user, may grant ADMIN via ``bootstrap_admins``, inserts a session row,
#: sets the cookie and commits. It is unreachable by this guard on purpose (a token
#: cannot exist before the session it belongs to) and the login-CSRF gap it leaves is
#: recorded in the module docstring for the follow-up.
STATE_CHANGING: frozenset[str] = frozenset({"POST", "PUT", "PATCH", "DELETE"})


class CsrfError(HTTPException):
    """403 — a cookie-authenticated state change with no valid token for its session."""

    def __init__(self, detail: str) -> None:
        super().__init__(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


async def expected_csrf_token(request: Request, settings: Settings) -> str | None:
    """The CSRF token of the live session this request is authenticated by, or ``None``
    when the request is **not** cookie-authenticated at all.

    The two are distinct on purpose: ``None`` means *skip the check*, while ``""`` means
    *there is a session and it has no usable token* — which must be refused, not waved
    through.

    Mirrors :func:`src.api.deps.resolve_user`'s cookie leg deliberately, including the
    ``cas_enabled`` short-circuit: with CAS off ``resolve_user`` never reads the cookie,
    so a stale cookie confers nothing and must not be treated as authority here either.
    Opens its own short-lived session off ``app.state`` (a pure read) rather than taking
    a request-scoped one, so an ordinary ``GET`` — including ``/health`` and ``/ready``
    — never checks a connection out of the pool on this path.
    """
    if not settings.cas_enabled:
        return None
    cookie = request.cookies.get(settings.session_cookie_name)
    if not cookie:
        return None
    async with request.app.state.sessionmaker() as db:
        session: Session | None = await session_service.get_active_session(db, cookie)
        if session is None:
            return None
        # Read inside the block: the row is detached the moment the session closes.
        return session.csrf_token or ""


async def _submitted_token(request: Request) -> str:
    """The token the request presents: the hidden form field, else the header.

    **The form field wins, and the order matters.** The other way round, a stray or
    stale ``X-CSRF-Token`` — from an injecting proxy, a browser extension, or a
    half-migrated client — would *shadow* a perfectly good form field and 403 every form
    in the app. There is no security cost to this order: the header exists so a JSON
    request (which has no form field at all) can comply, and a body that carries a field
    has already proved it is not a cross-site form, since one cannot know the token.

    A body that is not valid UTF-8 cannot contain the field, so it counts as *no token*
    rather than a 500 — this runs before the handler, and a crafted body should be
    refused, not crash the app.
    """
    try:
        pairs = await read_form_pairs(request)
    except UnicodeDecodeError:
        pairs = []
    return first_value(pairs, CSRF_FIELD) or request.headers.get(CSRF_HEADER, "")


async def enforce_csrf(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
) -> None:
    """The application-wide guard. Installed once in :mod:`src.api.main`.

    Refuses with **403 before the handler runs** — a rejection after the effect is not a
    fix — and passes everything that is not a cookie-authenticated state change straight
    through.
    """
    if request.method not in STATE_CHANGING:
        return
    expected = await expected_csrf_token(request, settings)
    if expected is None:
        return

    submitted = await _submitted_token(request)
    if not expected or not secrets.compare_digest(
        submitted.encode("utf-8"), expected.encode("utf-8")
    ):
        raise CsrfError(
            "this request changes state and was authenticated by a session cookie, so "
            f"it must carry that session's {CSRF_FIELD!r}. Reload the page and submit "
            "the form again."
        )

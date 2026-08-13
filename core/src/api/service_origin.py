"""The origin CAS returns an authenticated browser to — derived, then **validated**.

CAS is told a "service" URL at the start of the login dance and must be told the
byte-identical one when the ticket is validated. That URL carries an origin, and the
origin used to be a single static setting — which broke the moment the app became
reachable two ways at once (`localhost:25800` on the dev box, `sfuai.ca:7000` through a
forward): repointing the setting fixed one and broke the other. See
``docs/tasks/P0.3-deployment-origins.md``.

── The one thing to understand before changing this file ────────────────────────────

**Deriving the origin from the request is not the mechanism; the allowlist is.** The
code this replaces (``cas_service_from_request``) derived it from ``X-Forwarded-Host``
and used it unchecked, which means a caller chose where an authenticated user — holding
a live CAS ticket — was sent. P0.2 refuses that flag in production, which left the two
available options as *rigid* (one static origin) and *exploitable* (any header).

So: read the origin the browser actually used, and return it **only** if the deployment
has listed it (:attr:`~src.settings.Settings.allowed_service_origins`). Anything else
falls back to the static ``cas_service_base_url`` — never to the header. Every property
that makes this safe lives in that sentence, and
``tests/unit/test_service_origin.py`` pins it from both directions.

``Host`` is read as well as ``X-Forwarded-Host``, and is *equally* untrusted: the case
that actually happened was a plain TCP port-forward, which adds no proxy headers at all,
so the browser's own ``Host`` is the only evidence of the origin it used. Both are
client-supplied; both are worth exactly as much as the allowlist says they are.

**This does not read ``X-Forwarded-Proto`` to decide anything else.** The scheme it
contributes is part of the candidate origin and is subject to the same exact match — an
https deployment does not accept the http spelling of itself.
"""

from __future__ import annotations

from fastapi import Request

from src.settings import Settings, normalise_origin


def _first(value: str | None) -> str:
    """The first entry of a comma-accumulated forwarded header (the client's hop)."""
    return value.split(",", 1)[0].strip() if value else ""


def request_origin(request: Request) -> str | None:
    """The origin this request appears to have been made to, canonically spelled.

    ``None`` when there is nothing usable to derive one from — a crafted or absent
    ``Host`` must fall back, never raise: this runs on the login route, which is the
    first thing an unauthenticated stranger can reach.
    """
    forwarded_host = _first(request.headers.get("x-forwarded-host"))
    if forwarded_host:
        scheme = _first(request.headers.get("x-forwarded-proto")) or request.url.scheme
        return normalise_origin(f"{scheme}://{forwarded_host}")
    host = _first(request.headers.get("host"))
    if not host:
        return None
    return normalise_origin(f"{request.url.scheme}://{host}")


def resolve_service_origin(request: Request, settings: Settings) -> str:
    """The origin to hand CAS for this request: the derived one if it is allowed, else
    the static ``cas_service_base_url``.

    Both legs of the dance (``/cas/login`` and ``/cas/validate``) call this, so a user
    who starts and finishes on the same host gets the same string both times, which is
    what CAS requires. A user who *changes* origin mid-dance is refused by CAS itself —
    inherent to the protocol, not something this function can paper over.
    """
    allowed = settings.normalised_service_origins()
    if allowed:
        candidate = request_origin(request)
        if candidate is not None and candidate in allowed:
            return candidate
    return settings.cas_service_base_url.rstrip("/")

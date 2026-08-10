"""The authorization matrix — one table saying who may reach every route (P0.1a).

**Read ``EXPECTED_ACCESS`` as the access-control policy of this service.** It is the
durable artifact of P0.1a: the JSON API shipped with no gate at all (an unauthenticated
``POST /jd-bank/review/{id}/approve`` reached the review *service* and, on a gate-clean
DRAFT, would have **published** — a breach of NN #1, with ``actor`` taken from the
request body, so the append-only audit chain would have recorded a forged identity,
NN #6). That regressed silently because **no test pinned it**. This is that test.

Three properties are asserted:

1. **Completeness** — every route the app actually serves appears in the table (the
   served set is built by walking ``app.routes``, so a newly added route with no entry
   fails here and the author must classify it), and the table has no stale entries.
   The walk is **fail-closed and cross-checked**: it resolves every route to its
   *effective* path (include prefixes applied), it *raises* on anything it cannot
   reduce to ``(METHOD, full path)`` rather than skipping it, and its result is
   asserted equal to the app's own OpenAPI path table. A safety net whose only failure
   mode is silence is not a safety net.
2. **Refusal** — with CAS **on** and no credentials, every non-public route refuses.
   A ``json`` route must answer **401/403 and never a redirect** (a 3xx would mean a UI
   gate leaked onto a JSON route, sending an API client an HTML login page); a ``ui``
   route must answer **303 to the login page** (a browser gets a login page, not a JSON
   401) or 401/403. Public routes must NOT be refused — the table is checked in both
   directions, so over-gating is caught too.
3. **Authorization, not just authentication** — a signed-in user holding only ``author``
   (the default new-user role) gets **403** from every privileged route, JSON *and* UI,
   and is *not* refused by the shared ones. Without this row a route protected by mere
   authentication would look correct: gating a JSON router with bare ``current_user``,
   or downgrading a UI router from ``require_ui_roles`` to ``require_ui_user``, would
   leave every other test here green.
4. **No unauthenticated writes** — no POST/PUT/PATCH/DELETE is ``public``, except the
   few explicitly listed in :data:`PUBLIC_STATE_CHANGES`, each of which must carry a
   written reason in the table.

These are unit tests: with ``cas_enabled=True`` and no cookie, the identity dependency
raises 401 before any DB or service call, so nothing here needs Postgres.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterator, Sequence
from enum import StrEnum
from typing import NamedTuple

import pytest
from fastapi.testclient import TestClient
from starlette.routing import BaseRoute

from src.api.db.models import Role
from src.api.main import app
from tests.unit.auth_fakes import cas_on, signed_in_as, signed_in_ui_as, user_holding


class Access(StrEnum):
    """Who may reach a route."""

    PUBLIC = "public"
    ANY_AUTHENTICATED = "any_authenticated"
    REVIEWER_OR_ADMIN = "reviewer_or_admin"
    ADMIN = "admin"


class Surface(StrEnum):
    """How a refusal must be *shaped* — an API client and a browser need different
    answers, and confusing the two is its own defect."""

    JSON = "json"  # unauthenticated -> 401 (NEVER a redirect)
    UI = "ui"  # unauthenticated -> 303 to /jd-bank/ui/login


class Rule(NamedTuple):
    access: Access
    surface: Surface
    why: str = ""


_LOGIN_PATH = "/jd-bank/ui/login"

#: State-changing routes that are deliberately reachable without credentials. Any
#: addition to this set is a policy decision and must be argued in review — which is
#: why the set is asserted exactly, not merely allowed to grow.
PUBLIC_STATE_CHANGES: frozenset[tuple[str, str]] = frozenset(
    {("POST", "/jd-bank/ui/logout")}
)

#: route (METHOD, path) -> who may reach it. THE access policy; read it top to bottom.
EXPECTED_ACCESS: dict[tuple[str, str], Rule] = {
    # ── FastAPI's own docs surface ────────────────────────────────────────────────
    # Public today. Note this discloses the full API shape to anyone who can reach the
    # host; gating or disabling it in production is a separate decision (not P0.1a).
    ("GET", "/openapi.json"): Rule(Access.PUBLIC, Surface.JSON, "API schema, no data"),
    ("GET", "/docs"): Rule(Access.PUBLIC, Surface.JSON, "Swagger UI, no data"),
    ("GET", "/docs/oauth2-redirect"): Rule(Access.PUBLIC, Surface.JSON, "docs helper"),
    ("GET", "/redoc"): Rule(Access.PUBLIC, Surface.JSON, "ReDoc UI, no data"),
    # ── Legacy harness API (src/api/main.py) ─────────────────────────────────────
    # /health is a liveness probe: it must answer before anyone can sign in.
    ("GET", "/health"): Rule(Access.PUBLIC, Surface.JSON, "liveness probe, no data"),
    # The rest write, enqueue work, or expose agent memory. None of that belongs to an
    # unauthenticated caller in an HR service.
    ("POST", "/tasks"): Rule(Access.ADMIN, Surface.JSON),
    ("GET", "/tasks/{task_id}"): Rule(Access.ADMIN, Surface.JSON),
    ("GET", "/tasks/{task_id}/lineage"): Rule(Access.ADMIN, Surface.JSON),
    ("GET", "/memory/similar"): Rule(Access.ADMIN, Surface.JSON),
    ("POST", "/gates/run"): Rule(Access.ADMIN, Surface.JSON),
    # ── Auth routes (src/api/routes/auth.py) ─────────────────────────────────────
    # Necessarily public: the login page and the CAS dance must be reachable by a
    # visitor who has no session yet — that is the point of them.
    ("GET", "/jd-bank/ui/login"): Rule(Access.PUBLIC, Surface.UI, "the login page"),
    ("GET", "/jd-bank/ui/cas/login"): Rule(Access.PUBLIC, Surface.UI, "starts CAS"),
    ("GET", "/jd-bank/ui/cas/validate"): Rule(Access.PUBLIC, Surface.UI, "CAS reply"),
    ("POST", "/jd-bank/ui/logout"): Rule(
        Access.PUBLIC,
        Surface.UI,
        "state-changing but public by design: it only revokes the caller's OWN "
        "session (identified by their cookie), and an expired session must still be "
        "able to log out rather than be told to sign in first.",
    ),
    # ── JSON review API (src/api/routes/jd_bank.py) — NN #1 approval surface ─────
    # Same access as the review UI: reviewer or admin. Read included — a review packet
    # is unpublished draft JD content.
    ("GET", "/jd-bank/review/queue"): Rule(Access.REVIEWER_OR_ADMIN, Surface.JSON),
    ("GET", "/jd-bank/review/{canonical_id}"): Rule(
        Access.REVIEWER_OR_ADMIN, Surface.JSON
    ),
    ("POST", "/jd-bank/review/{canonical_id}/approve"): Rule(
        Access.REVIEWER_OR_ADMIN, Surface.JSON, "publishes a canonical JD (NN #1)"
    ),
    ("POST", "/jd-bank/review/{canonical_id}/reject"): Rule(
        Access.REVIEWER_OR_ADMIN, Surface.JSON
    ),
    ("POST", "/jd-bank/review/{canonical_id}/edit"): Rule(
        Access.REVIEWER_OR_ADMIN, Surface.JSON
    ),
    # ── JSON compose API (src/api/routes/compose.py) ─────────────────────────────
    # Read-only (nothing publishes here), but it discloses archive content and drives
    # the GPU — so, like the compose UI, any signed-in user and no one else.
    ("POST", "/jd-bank/compose/validate"): Rule(Access.ANY_AUTHENTICATED, Surface.JSON),
    ("POST", "/jd-bank/compose/assist/summary"): Rule(
        Access.ANY_AUTHENTICATED, Surface.JSON, "drives the self-hosted LLM"
    ),
    ("POST", "/jd-bank/compose/export"): Rule(Access.ANY_AUTHENTICATED, Surface.JSON),
    ("GET", "/jd-bank/compose/search"): Rule(
        Access.ANY_AUTHENTICATED, Surface.JSON, "searches archive JD content"
    ),
    ("GET", "/jd-bank/compose/clone/{source_document_id}"): Rule(
        Access.ANY_AUTHENTICATED, Surface.JSON, "returns archive JD content"
    ),
    # ── Review UI (src/api/routes/ui.py) — reviewer or admin ─────────────────────
    ("GET", "/jd-bank/ui/queue"): Rule(Access.REVIEWER_OR_ADMIN, Surface.UI),
    ("GET", "/jd-bank/ui/review/{canonical_id}"): Rule(
        Access.REVIEWER_OR_ADMIN, Surface.UI
    ),
    ("GET", "/jd-bank/ui/review/{canonical_id}/diff"): Rule(
        Access.REVIEWER_OR_ADMIN, Surface.UI
    ),
    ("POST", "/jd-bank/ui/review/{canonical_id}/approve"): Rule(
        Access.REVIEWER_OR_ADMIN, Surface.UI, "publishes a canonical JD (NN #1)"
    ),
    ("POST", "/jd-bank/ui/review/{canonical_id}/reject"): Rule(
        Access.REVIEWER_OR_ADMIN, Surface.UI
    ),
    ("POST", "/jd-bank/ui/review/{canonical_id}/edit"): Rule(
        Access.REVIEWER_OR_ADMIN, Surface.UI
    ),
    # ── Content library UI — read-only, any signed-in user ───────────────────────
    ("GET", "/jd-bank/ui/library"): Rule(Access.ANY_AUTHENTICATED, Surface.UI),
    ("GET", "/jd-bank/ui/role/{cluster_id}"): Rule(
        Access.ANY_AUTHENTICATED, Surface.UI
    ),
    ("GET", "/jd-bank/ui/jd/{source_document_id}"): Rule(
        Access.ANY_AUTHENTICATED, Surface.UI
    ),
    ("GET", "/jd-bank/ui/archive"): Rule(Access.ANY_AUTHENTICATED, Surface.UI),
    # ── Dashboards + guide — any signed-in user ──────────────────────────────────
    ("GET", "/jd-bank/ui/dashboard"): Rule(Access.ANY_AUTHENTICATED, Surface.UI),
    ("GET", "/jd-bank/ui/dashboard/baseline"): Rule(
        Access.ANY_AUTHENTICATED, Surface.UI
    ),
    ("GET", "/jd-bank/ui/dashboard/dedup"): Rule(Access.ANY_AUTHENTICATED, Surface.UI),
    ("GET", "/jd-bank/ui/dashboard/clusters"): Rule(
        Access.ANY_AUTHENTICATED, Surface.UI
    ),
    ("GET", "/jd-bank/ui/guide"): Rule(Access.ANY_AUTHENTICATED, Surface.UI),
    # ── Builder UI (compose) — any signed-in user ────────────────────────────────
    ("GET", "/jd-bank/ui/compose/new"): Rule(Access.ANY_AUTHENTICATED, Surface.UI),
    ("POST", "/jd-bank/ui/compose/new"): Rule(Access.ANY_AUTHENTICATED, Surface.UI),
    ("POST", "/jd-bank/ui/compose/assist"): Rule(Access.ANY_AUTHENTICATED, Surface.UI),
    ("GET", "/jd-bank/ui/compose/search"): Rule(Access.ANY_AUTHENTICATED, Surface.UI),
    ("GET", "/jd-bank/ui/compose/clone-role/{cluster_id}"): Rule(
        Access.ANY_AUTHENTICATED, Surface.UI
    ),
    ("GET", "/jd-bank/ui/compose/clone/{source_document_id}"): Rule(
        Access.ANY_AUTHENTICATED, Surface.UI
    ),
    ("POST", "/jd-bank/ui/compose/submit"): Rule(
        Access.ANY_AUTHENTICATED, Surface.UI, "creates a DRAFT for the review queue"
    ),
    ("POST", "/jd-bank/ui/compose/export"): Rule(Access.ANY_AUTHENTICATED, Surface.UI),
    # ── User administration — admin only ─────────────────────────────────────────
    ("GET", "/jd-bank/ui/admin/users"): Rule(Access.ADMIN, Surface.UI),
    ("POST", "/jd-bank/ui/admin/users/{user_id}/roles"): Rule(Access.ADMIN, Surface.UI),
    ("POST", "/jd-bank/ui/admin/users/{user_id}/status"): Rule(
        Access.ADMIN, Surface.UI
    ),
}

_STATE_CHANGING = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_PATH_PARAM = re.compile(r"\{[^}]+\}")

#: Methods a route may declare. ``HEAD``/``OPTIONS`` are dropped where they appear:
#: Starlette adds them automatically alongside ``GET`` and they carry the same gate.
_HTTP_METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE", "TRACE"})
_IMPLICIT_METHODS = frozenset({"HEAD", "OPTIONS"})

#: FastAPI's own docs routes. They are ``include_in_schema=False``, so they are the one
#: thing the OpenAPI table cannot describe and must be added to it by hand. If FastAPI
#: ever changes them, the cross-check below goes RED and someone looks — which is the
#: point.
_DOCS_ROUTES: frozenset[tuple[str, str]] = frozenset(
    {
        ("GET", "/openapi.json"),
        ("GET", "/docs"),
        ("GET", "/docs/oauth2-redirect"),
        ("GET", "/redoc"),
    }
)


class UnwalkableRouteError(RuntimeError):
    """A route this walk cannot reduce to ``(METHOD, full path)``.

    Raised, never skipped. A surface the walk cannot see is a surface the matrix cannot
    protect, and an earlier version of this file *skipped* such routes: an
    ``app.mount()`` sub-app and a ``@app.websocket`` route were silently invisible and
    anonymously reachable while every test stayed green.
    """


def _http_pairs(
    route: object, path: object, methods: object
) -> Iterator[tuple[str, str]]:
    """``(METHOD, path)`` for one HTTP route, or :class:`UnwalkableRouteError`."""
    if not isinstance(path, str) or not isinstance(
        methods, (set, frozenset, list, tuple)
    ):
        raise UnwalkableRouteError(
            f"{route!r} exposes no (path, methods) pair — a mount, a websocket, or a "
            "route type this walk does not understand. Extend the walk so it resolves "
            "to (METHOD, full path) and classify it in EXPECTED_ACCESS; do not skip it."
        )
    declared = {str(method).upper() for method in methods}
    unknown = declared - _HTTP_METHODS - _IMPLICIT_METHODS
    if unknown:
        raise UnwalkableRouteError(
            f"{route!r} declares unknown method(s) {sorted(unknown)}"
        )
    real = declared - _IMPLICIT_METHODS
    if not real:
        raise UnwalkableRouteError(f"{route!r} declares no real HTTP method")
    for method in sorted(real):
        yield (method, path)


def _iter_routes(routes: Sequence[BaseRoute]) -> Iterator[tuple[str, str]]:
    """Every ``(METHOD, full path)`` the app actually serves.

    Walks the real routing table rather than a hand-written list, so a route added
    without a matrix entry fails :func:`test_every_route_is_classified`.

    **Effective paths only.** FastAPI wraps each ``include_router`` call in a lazy
    router object; its *contexts* carry the path as mounted (``prefix=`` applied),
    while the wrapped ``original_router.routes`` carry the path as originally declared.
    Reading the latter was this walk's original defect: a router included under
    ``prefix="/x"`` was enumerated as ``/foo`` while the app served ``/x/foo``, so the
    matrix could be green with an open route — and if the inner path happened to match
    one the table already classifies, completeness passed outright. Never read
    ``original_router`` here; if the effective paths cannot be obtained, raise.
    """
    for route in routes:
        contexts = getattr(route, "effective_route_contexts", None)
        if callable(contexts):
            for ctx in contexts():
                yield from _http_pairs(
                    ctx, getattr(ctx, "path", None), getattr(ctx, "methods", None)
                )
            continue
        if getattr(route, "original_router", None) is not None:
            raise UnwalkableRouteError(
                f"{route!r} is an included router whose EFFECTIVE paths this walk "
                "cannot resolve (no `effective_route_contexts`). Its inner paths do "
                "not carry the include prefix, so enumerating them would understate "
                "what the app serves."
            )
        yield from _http_pairs(
            route, getattr(route, "path", None), getattr(route, "methods", None)
        )


def _app_routes() -> frozenset[tuple[str, str]]:
    return frozenset(_iter_routes(app.routes))


def _openapi_routes() -> frozenset[tuple[str, str]]:
    """The served table according to the app's **own** OpenAPI generation — a second,
    independent opinion on what is mounted where (FastAPI applies include prefixes
    itself when it builds it). The cached schema is discarded first so this can never
    describe an app that has since grown a route."""
    app.openapi_schema = None
    paths: dict[str, dict[str, object]] = app.openapi()["paths"]
    return frozenset(
        (method.upper(), path)
        for path, operations in paths.items()
        for method in operations
        if method.upper() in _HTTP_METHODS
    )


def _concrete(path: str) -> str:
    """A requestable URL: path params filled with a UUID (every param in this app is
    one). The gate must refuse before the id is ever looked up."""
    return _PATH_PARAM.sub(lambda _: str(uuid.uuid4()), path)


#: Access levels that mean "signed in is not enough".
PRIVILEGED: frozenset[Access] = frozenset({Access.REVIEWER_OR_ADMIN, Access.ADMIN})


def _routes_where(
    *, public: bool, surface: Surface | None = None, privileged: bool | None = None
) -> list[str]:
    """Matrix keys as ``"METHOD path"`` ids, for parametrization."""
    return [
        f"{method} {path}"
        for (method, path), rule in sorted(EXPECTED_ACCESS.items())
        if (rule.access is Access.PUBLIC) is public
        and (surface is None or rule.surface is surface)
        and (privileged is None or (rule.access in PRIVILEGED) is privileged)
    ]


def _split(route_id: str) -> tuple[str, str]:
    method, path = route_id.split(" ", 1)
    return method, path


@pytest.fixture
def anonymous_client() -> Iterator[TestClient]:
    """A client with **CAS on** and no credentials — the attacker's view.

    ``raise_server_exceptions=False`` so that an *ungated* route which blows up inside
    its handler is reported as a status code (500) rather than a raised exception: the
    failure message then reads "expected 401, got 500", which is still the correct
    diagnosis — the request reached the handler, so no gate ran.
    """
    cas_on()
    yield TestClient(app, follow_redirects=False, raise_server_exceptions=False)
    app.dependency_overrides.clear()


@pytest.fixture
def author_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """Signed in, holding **only** ``author`` — the second row of the matrix.

    ``default_new_user_role`` is ``author``, so this is the ordinary pilot user: they
    may use the Builder, and they may NOT reach the review or admin surfaces. Without
    this row, "gated" and "gated to the right role" are indistinguishable — a route
    protected by mere authentication would look correct, and downgrading
    ``require_ui_roles(Role.ADMIN)`` to ``require_ui_user`` on the admin router would
    pass every other test in this file.

    Both surfaces need feeding, by different means: JSON routes resolve their identity
    through the ``current_user`` dependency, UI routes call ``resolve_user`` directly
    (see :func:`tests.unit.auth_fakes.signed_in_ui_as`).
    """
    cas_on()
    author = user_holding(Role.AUTHOR, username="author-1")
    signed_in_as(author)
    signed_in_ui_as(monkeypatch, author)
    yield TestClient(app, follow_redirects=False, raise_server_exceptions=False)
    app.dependency_overrides.clear()


def test_the_anonymous_client_really_has_cas_enabled(
    anonymous_client: TestClient,
) -> None:
    """Guard against the easiest false green in this file.

    With ``cas_enabled=False`` (the shipped default) every request resolves to a
    transient **admin** and every refusal test below would pass vacuously. ``/jd-bank/
    ui/queue`` is gated today, so under a working fixture it must redirect to login —
    if this test ever returns 200, the fixture is broken and nothing else here means
    anything.
    """
    resp = anonymous_client.get("/jd-bank/ui/queue")

    assert resp.status_code == 303, (
        "CAS is not actually enabled for this client — every other test in this file "
        "is a false green until that is fixed"
    )
    assert resp.headers["location"].startswith(_LOGIN_PATH)


def test_the_route_walk_agrees_with_the_apps_own_openapi_table() -> None:
    """The walk is only as good as its view of the app, so check it against a source
    it does not share: FastAPI's own OpenAPI path table, which applies include prefixes
    itself. A disagreement means the walk is describing a different app from the one
    being served — exactly the condition under which completeness can be green while a
    route is open — so it must fail here even though no gate is involved.

    ``_DOCS_ROUTES`` is the documented difference: those four are
    ``include_in_schema=False``, so OpenAPI omits them by design.
    """
    walked = _app_routes()
    described = _openapi_routes() | _DOCS_ROUTES

    assert walked == described, (
        "the route walk and the app's OpenAPI table disagree.\n"
        f"  walk saw but OpenAPI did not: {sorted(walked - described)}\n"
        f"  OpenAPI serves but walk missed: {sorted(described - walked)}\n"
        "A route the walk cannot see is a route this matrix cannot protect — fix "
        "_iter_routes, do not adjust the expectation."
    )


def test_every_route_is_classified() -> None:
    """A route with no entry in ``EXPECTED_ACCESS`` fails here — that is the whole
    point of walking the routing table instead of listing routes by hand."""
    served = _app_routes()
    classified = frozenset(EXPECTED_ACCESS)

    unclassified = sorted(served - classified)
    assert not unclassified, (
        "These routes are served but not classified in EXPECTED_ACCESS: "
        f"{unclassified}. Add an entry saying who may reach each one "
        "(public / any_authenticated / reviewer_or_admin / admin) and gate it in "
        "main.py to match — a new route must not ship without an access decision."
    )

    stale = sorted(classified - served)
    assert not stale, (
        f"EXPECTED_ACCESS classifies routes the app no longer serves: {stale}. "
        "Delete the stale entries so the table stays an honest description of the app."
    )


def test_no_state_changing_route_is_unauthenticated() -> None:
    """A write that anyone on the network can make is a breach, not a feature. The one
    documented exception (logout) is asserted exactly, so a second one cannot slip in
    without this test failing and someone arguing for it."""
    public_writes = {
        (method, path)
        for (method, path), rule in EXPECTED_ACCESS.items()
        if method in _STATE_CHANGING and rule.access is Access.PUBLIC
    }

    assert public_writes == set(PUBLIC_STATE_CHANGES), (
        "State-changing routes reachable without authentication changed: "
        f"{sorted(public_writes)} vs the reviewed set {sorted(PUBLIC_STATE_CHANGES)}."
    )
    for key in sorted(public_writes):
        assert EXPECTED_ACCESS[key].why, (
            f"{key} is a public write with no written justification in the table — "
            "state a reason a reviewer can weigh, or gate it."
        )


@pytest.mark.parametrize(
    "route_id", _routes_where(public=False, surface=Surface.JSON), ids=lambda x: x
)
def test_unauthenticated_json_route_is_refused_with_401_not_a_redirect(
    route_id: str, anonymous_client: TestClient
) -> None:
    """A JSON client with no session must get a real 401/403 — never a 2xx, and never
    a 3xx (a redirect means a *UI* gate leaked onto an API route: the caller would get
    an HTML login page with a success-shaped status)."""
    method, path = _split(route_id)

    resp = anonymous_client.request(method, _concrete(path))

    assert resp.status_code in (401, 403), (
        f"{route_id} answered {resp.status_code} to an unauthenticated request; "
        "expected 401 (no session) or 403 (wrong role). A 2xx, a body-validation 422 "
        "or a 500 all mean the same thing: the request got past authentication into "
        "the route's own dependencies, i.e. no auth gate ran."
    )


@pytest.mark.parametrize(
    "route_id", _routes_where(public=False, surface=Surface.UI), ids=lambda x: x
)
def test_unauthenticated_ui_route_is_refused_or_sent_to_login(
    route_id: str, anonymous_client: TestClient
) -> None:
    """A browser with no session gets the login page (303), not a JSON 401 — and an
    authenticated-but-unauthorized visitor gets 403 (covered by the UI suites)."""
    method, path = _split(route_id)

    resp = anonymous_client.request(method, _concrete(path))

    assert resp.status_code in (303, 401, 403), (
        f"{route_id} answered {resp.status_code} to an unauthenticated request; "
        "expected a 303 to the login page (or 401/403)."
    )
    if resp.status_code == 303:
        assert resp.headers["location"].startswith(_LOGIN_PATH), (
            f"{route_id} redirected an unauthenticated visitor to "
            f"{resp.headers['location']!r}, not the login page."
        )


@pytest.mark.parametrize(
    "route_id",
    _routes_where(public=False, privileged=True),
    ids=lambda x: x,
)
def test_signed_in_author_is_forbidden_from_a_privileged_route(
    route_id: str, author_client: TestClient
) -> None:
    """Authenticated is not authorized. An ordinary pilot user (role ``author``) must
    be turned away with **403** — not 401 (they are signed in), not a redirect (they
    have nowhere better to be sent), and certainly not let through to a review or admin
    surface. Both surfaces are covered: this is what would fail if a JSON router were
    gated with bare ``current_user``, or a UI router downgraded from
    ``require_ui_roles`` to ``require_ui_user``."""
    method, path = _split(route_id)

    resp = author_client.request(method, _concrete(path))

    assert resp.status_code == 403, (
        f"{route_id} answered {resp.status_code} to a signed-in user holding only "
        "'author'; expected 403. Authenticating the route is not enough — it must "
        "check the role the table names."
    )


@pytest.mark.parametrize(
    "route_id",
    _routes_where(public=False, privileged=False),
    ids=lambda x: x,
)
def test_signed_in_author_may_use_a_shared_route(
    route_id: str, author_client: TestClient
) -> None:
    """The other direction: a route classified ``any_authenticated`` must not be
    over-gated to reviewer/admin — the Builder is what an author signs in to use."""
    method, path = _split(route_id)

    resp = author_client.request(method, _concrete(path))

    assert resp.status_code not in (401, 403), (
        f"{route_id} refused a signed-in author with {resp.status_code}, but the table "
        "says any authenticated user may reach it."
    )


@pytest.mark.parametrize("route_id", _routes_where(public=True), ids=lambda x: x)
def test_public_route_is_not_gated(route_id: str, anonymous_client: TestClient) -> None:
    """The table is checked in both directions: a route classified public must stay
    reachable. Over-gating the login page or the liveness probe locks everyone out."""
    method, path = _split(route_id)

    resp = anonymous_client.request(method, _concrete(path))

    assert resp.status_code not in (401, 403), (
        f"{route_id} is classified public but answered {resp.status_code}. Either the "
        "gate is wrong or the classification is."
    )

"""No dead ends: the front door, and errors written for the person reading them (P0.0).

Three defects met at the front door and this file pins all three shut:

1. **Nothing answered at the root.** ``http://localhost:25800`` returned
   ``{"detail":"Not Found"}`` in a browser, minutes before an HR demo. So did
   ``/jd-bank`` and ``/jd-bank/ui``.
2. **Every error was JSON on an HTML surface.** The authorization matrix already
   distinguishes a JSON surface from a UI one for the **status code**; nothing did so
   for the **body**, so a 403, a 404 and a 500 all reached a reviewer as a raw blob —
   the stale-tab CSRF 403 included, which is the one they will actually meet.
3. **Redirects were absolute and scheme-blind.** ``/library/`` answered ``307`` to an
   absolute ``http://`` URL even behind TLS, because Starlette builds its slash redirect
   from the request URL and uvicorn runs without ``--proxy-headers``. Fixed by *not
   trusting a header at all*: the redirect is relative, so it cannot name the wrong
   scheme (the header-trust question itself belongs to P0.3).

The negotiation rule under test is deliberately about **what the caller asked for**, not
about a hardcoded list of path prefixes: a caller whose ``Accept`` includes
``text/html`` gets a page, everything else keeps the JSON body it has always had.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from src.api.csrf import CsrfError
from src.api.db.models import Role
from src.api.main import app
from tests.unit.auth_fakes import cas_on, signed_in_ui_as, user_holding

#: What a browser sends when a person types an address or clicks a link.
BROWSER = {"accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}
#: What an API client sends. ``*/*`` (curl, httpx, TestClient's default) is included in
#: the "not a browser" case on purpose: it did not ask for HTML.
API_CLIENT = {"accept": "application/json"}

LIBRARY = "/jd-bank/ui/library"


@pytest.fixture
def client() -> Iterator[TestClient]:
    """The app with no lifespan and no credentials — CAS off, the ``make gates``
    posture, in which every request resolves to the synthetic dev user."""
    yield TestClient(app, follow_redirects=False, raise_server_exceptions=False)
    app.dependency_overrides.clear()


# ── 1. The front door ────────────────────────────────────────────────────────────


def _follow(client: TestClient, path: str, *, limit: int = 5) -> tuple[str, int]:
    """Walk the redirect chain by hand and return where it ended up. Hand-walked rather
    than ``follow_redirects=True`` so the test can also assert the chain TERMINATES —
    "it redirects" is not the property that matters, "it arrives" is."""
    for _ in range(limit):
        resp = client.get(path, headers=BROWSER)
        if resp.status_code not in (301, 302, 303, 307, 308):
            return path, resp.status_code
        path = resp.headers["location"]
    raise AssertionError(f"redirect loop: {path} never settled in {limit} hops")


@pytest.mark.parametrize(
    "path",
    ["/", "/jd-bank", "/jd-bank/", "/jd-bank/ui", "/jd-bank/ui/"],
    ids=lambda p: p,
)
def test_the_bare_host_and_its_near_misses_reach_the_app(
    path: str, client: TestClient
) -> None:
    """Typing the host, or any of the three prefixes a person would guess, arrives at
    the Bank rather than at a JSON error. The slashed variants take two hops (the slash
    rescue, then the front door) and both must land in the same place."""
    landed, status = _follow(client, path)

    assert landed.startswith(LIBRARY), f"{path} ended at {landed!r}, not the library."
    assert status != 404, f"{path} reached {landed!r} and it 404'd."


def test_every_redirect_is_relative_so_it_cannot_name_the_wrong_scheme(
    client: TestClient,
) -> None:
    """The TLS defect, pinned. A ``Location`` with no scheme is served back on whatever
    scheme the browser used, so a proxy terminating TLS cannot be downgraded to ``http``
    — and we reach that without trusting ``X-Forwarded-Proto``, which is the header
    P0.2 refuses in production and P0.3 exists to make safe."""
    for path in ("/", "/jd-bank", f"{LIBRARY}/"):
        location = client.get(
            path, headers={**BROWSER, "x-forwarded-proto": "https"}
        ).headers["location"]

        assert location.startswith("/"), (
            f"{path} redirected to {location!r} — an absolute URL pins the scheme, and "
            "the scheme it pins is the one uvicorn sees, not the one the browser used."
        )


def test_a_trailing_slash_on_a_real_page_still_works(client: TestClient) -> None:
    """``redirect_slashes`` is off (it is what built the absolute URL), so the rescue
    has to be ours — and it must keep the query string, or a bookmarked search silently
    loses its terms."""
    resp = client.get(f"{LIBRARY}/?q=analyst", headers=BROWSER)

    assert resp.status_code == 307
    assert resp.headers["location"] == f"{LIBRARY}?q=analyst"


def test_a_slash_variant_that_is_not_a_real_page_is_still_a_404(
    client: TestClient,
) -> None:
    """The rescue must not become a way to make any address look like a page."""
    resp = client.get("/jd-bank/ui/librar/", headers=BROWSER)

    assert resp.status_code == 404


# ── 2. Errors, written for whoever asked ─────────────────────────────────────────


def test_a_browser_gets_an_html_404_in_the_apps_own_chrome(client: TestClient) -> None:
    resp = client.get("/no-such-page", headers=BROWSER)

    assert resp.status_code == 404
    assert resp.headers["content-type"].startswith("text/html")
    assert "<!DOCTYPE html>" in resp.text
    # The app's own chrome, so there is a way out of the dead end.
    assert LIBRARY in resp.text


def test_an_api_client_still_gets_json(client: TestClient) -> None:
    """The other direction, which is just as important: nothing about this change may
    turn a JSON API refusal into an HTML page."""
    resp = client.get("/no-such-page", headers=API_CLIENT)

    assert resp.headers["content-type"].startswith("application/json")
    assert resp.json() == {"detail": "Not Found"}


def test_a_client_that_asked_for_nothing_in_particular_gets_json(
    client: TestClient,
) -> None:
    """``Accept: */*`` — curl, httpx, every SDK — did not ask for HTML."""
    resp = client.get("/no-such-page", headers={"accept": "*/*"})

    assert resp.headers["content-type"].startswith("application/json")


@pytest.mark.parametrize("status_code", [400, 401, 403, 404, 405, 422, 500])
def test_every_error_status_has_copy_a_person_can_act_on(status_code: int) -> None:
    """Each status this app can hand a browser says what happened and what to do about
    it — not a number and a shrug. The generic fallback exists for the statuses nothing
    here raises; it is not an acceptable answer for the ones that reach real readers."""
    from src.api.errors import COPY

    assert (
        status_code in COPY
    ), f"{status_code} has no human copy, so it would render the generic fallback."
    headline, message = COPY[status_code]
    assert headline and message
    assert str(status_code) not in headline, (
        "the headline is the sentence, not the status code — the code is shown "
        "separately, in small print, for whoever is reporting the problem."
    )


def test_the_stale_tab_403_says_reload_rather_than_forbidden(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The 403 a reviewer will actually meet. After P0.1b-i a tab left open past its
    session posts with a token the server no longer expects; "Forbidden" tells them
    nothing, and the honest instruction is *reload and submit again*."""
    from src.api import errors

    @app.get("/_test/stale-tab", include_in_schema=False)
    async def _stale() -> None:  # pragma: no cover - registered for this test only
        raise CsrfError("this request changes state and was authenticated by a cookie")

    try:
        resp = client.get("/_test/stale-tab", headers=BROWSER)

        assert resp.status_code == 403
        assert "reload" in resp.text.lower()
        assert "forbidden" not in resp.text.lower()
        assert errors.STALE_TAB_HEADLINE in resp.text
    finally:
        app.router.routes = [
            r for r in app.router.routes if getattr(r, "path", "") != "/_test/stale-tab"
        ]
        app.openapi_schema = None


def test_a_bookmarked_logout_gets_a_page_not_a_405_blob(client: TestClient) -> None:
    """``GET /jd-bank/ui/logout`` is a real bookmark; the form itself is a POST."""
    resp = client.get("/jd-bank/ui/logout", headers=BROWSER)

    assert resp.status_code == 405
    assert resp.headers["content-type"].startswith("text/html")


def test_a_malformed_id_gets_a_page_not_a_pydantic_dump(client: TestClient) -> None:
    """``/role/not-a-uuid`` raised a raw 422 validation dump while a *missing* UUID
    already rendered a friendly page — two idioms for the same reader.

    The session override is scaffolding, not the subject: without a lifespan the route's
    own DB dependency raises before the validation error is ever reported, and a 500
    would hide the very thing under test.
    """
    from src.api.main import get_session

    async def _session() -> object:
        yield object()

    app.dependency_overrides[get_session] = _session

    resp = client.get("/jd-bank/ui/role/not-a-uuid", headers=BROWSER)

    assert resp.status_code == 422
    assert resp.headers["content-type"].startswith("text/html")
    assert "uuid_parsing" not in resp.text


def test_a_500_on_a_ui_path_is_branded_html(client: TestClient) -> None:
    @app.get("/_test/unhandled", include_in_schema=False)
    async def _boom() -> None:  # pragma: no cover - registered for this test only
        raise RuntimeError("boom")

    try:
        resp = client.get("/_test/unhandled", headers=BROWSER)

        assert resp.status_code == 500
        assert resp.headers["content-type"].startswith("text/html")
        # Never the exception text: a stack trace is not for the reader, and it leaks.
        assert "boom" not in resp.text
        assert "RuntimeError" not in resp.text
    finally:
        app.router.routes = [
            r for r in app.router.routes if getattr(r, "path", "") != "/_test/unhandled"
        ]
        app.openapi_schema = None


def test_the_error_page_never_echoes_the_address_back_as_markup(
    client: TestClient,
) -> None:
    """The 404 page names the address, so the address is attacker-controlled text."""
    resp = client.get("/<script>alert(1)</script>", headers=BROWSER)

    assert "<script>alert(1)</script>" not in resp.text


# ── 3. What a browser asks for on every page load ────────────────────────────────


def test_favicon_is_served_rather_than_404ing_on_every_page_load(
    client: TestClient,
) -> None:
    resp = client.get("/favicon.ico")

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("image/")


def test_robots_refuses_indexing(client: TestClient) -> None:
    """This is an internal HR system that may be reachable by DNS name (P0.3); nothing
    in it belongs in a search index."""
    resp = client.get("/robots.txt")

    assert resp.status_code == 200
    assert "Disallow: /" in resp.text


# ── 4. Refusals still refuse ─────────────────────────────────────────────────────


def test_an_html_refusal_is_still_a_refusal(monkeypatch: pytest.MonkeyPatch) -> None:
    """Rendering a 403 as a page must not soften it into a 200 — the status code is what
    the authorization matrix asserts, and this is the change most likely to erode it."""
    cas_on()
    signed_in_ui_as(monkeypatch, user_holding(Role.AUTHOR, username="author-1"))
    client = TestClient(app, follow_redirects=False, raise_server_exceptions=False)
    try:
        resp = client.get("/jd-bank/ui/queue", headers=BROWSER)

        assert resp.status_code == 403
        assert resp.headers["content-type"].startswith("text/html")
    finally:
        app.dependency_overrides.clear()


def test_an_unauthenticated_browser_is_still_sent_to_login() -> None:
    """The login redirect predates this work and must survive it."""
    cas_on()
    client = TestClient(app, follow_redirects=False, raise_server_exceptions=False)
    try:
        resp = client.get(LIBRARY, headers=BROWSER)

        assert resp.status_code == 303
        assert resp.headers["location"].startswith("/jd-bank/ui/login")
    finally:
        app.dependency_overrides.clear()


def test_a_uuid_that_does_not_exist_keeps_its_friendly_library_page(
    monkeypatch: pytest.MonkeyPatch, client: TestClient
) -> None:
    """The pattern the audit said to copy — four routes already render a real page for a
    valid-but-missing id. This pins that the generic handler did not replace it."""
    from unittest.mock import AsyncMock

    from src.api.main import get_session
    from src.api.routes import library as library_route

    async def _session() -> object:
        yield object()

    app.dependency_overrides[get_session] = _session
    monkeypatch.setattr(library_route, "get_role", AsyncMock(return_value=None))

    resp = client.get(f"/jd-bank/ui/role/{uuid.uuid4()}", headers=BROWSER)

    assert resp.status_code == 404
    assert "Back to the library" in resp.text


def test_a_json_route_that_raises_404_keeps_its_json_body(client: TestClient) -> None:
    """``HTTPException`` is how every JSON route says "not found"; that contract is
    unchanged for a caller who did not ask for HTML."""

    @app.get("/_test/json-404", include_in_schema=False)
    async def _missing() -> None:  # pragma: no cover - registered for this test only
        raise HTTPException(status_code=404, detail="task not found")

    try:
        resp = client.get("/_test/json-404", headers=API_CLIENT)

        assert resp.json() == {"detail": "task not found"}
    finally:
        app.router.routes = [
            r for r in app.router.routes if getattr(r, "path", "") != "/_test/json-404"
        ]
        app.openapi_schema = None

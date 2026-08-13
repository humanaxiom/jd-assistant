"""The CAS login round trip: where it sends you, and who started it (P0.1b-ii).

Two findings from the 2026-08-07 architecture review, recorded then and closed here.
They are one fix because they are one code path — the ``/cas/login`` → ``cas.sfu.ca`` →
``/cas/validate`` round trip — and fixing either alone leaves the other standing.

── 1. The open redirect on ``next`` ─────────────────────────────────────────────────

Measured against the running system before anything was written::

    GET /jd-bank/ui/cas/login?next=https://evil.example/steal
    -> 302 https://cas.sfu.ca/cas/login?service=…%2Fcas%2Fvalidate%3Fnext%3Dhttps…evil.example…

So an attacker-authored link to **our own login page** authenticates the victim, sets
their session cookie, and *then* hands them to the attacker's site. Post-authentication,
which is the part that makes it worth phishing with: the victim has just typed their SFU
credentials into a real ``cas.sfu.ca`` page, so what they land on inherits that trust.

The fix is that ``next`` is only ever a **local path**. Not an allowlist of hosts —
there is no other host this app should ever hand a user to.

── 2. Login CSRF on ``/cas/validate`` ───────────────────────────────────────────────

``GET /cas/validate?ticket=…`` mutates: it provisions a user, may grant ADMIN through
``bootstrap_admins``, mints a session and commits. The app-wide CSRF guard cannot cover
it — ``GET`` is not a state-changing method by convention, and more fundamentally *no
token can exist before the session it belongs to*.

So an attacker signs in as themselves, keeps their own single-use CAS ticket, and gets a
victim's browser to fetch ``/cas/validate?ticket=<attacker's>``. The victim is now
signed in **as the attacker**, in their own browser, with no sign anything happened —
and every
JD they go on to write lands in the attacker's account.

The fix is the standard one, and the reason it works is worth stating exactly: a random
``state`` is minted when *we* start the round trip and set as an **HttpOnly cookie**,
and ``/cas/validate`` refuses unless the ``state`` echoed back through CAS matches that
cookie. An attacker can obtain a state of their own — ``/cas/login`` is public — but
**they cannot set a cookie in the victim's browser**, and that is the whole of the
protection. A state
carried only in the URL would prove nothing.
"""

from __future__ import annotations

from collections.abc import Iterator
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, unquote, urlsplit

import pytest
from fastapi.testclient import TestClient

from src.api.db.models import Role
from src.api.main import app
from src.api.routes import auth as auth_routes
from src.api.routes.auth import LOGIN_STATE_COOKIE, safe_next
from src.settings import Settings, get_settings
from tests.unit.auth_fakes import user_holding

HOME = "/jd-bank/ui/library"

#: Values a caller might supply for `next` that must never be redirected to. The last
#: two are what a scheme-only check misses: `//host` is protocol-relative (a browser
#: reads it as an absolute URL), and a backslash is treated as a slash by several
#: browsers'
#: URL parsers even though the RFC disagrees.
HOSTILE_NEXT = [
    "https://evil.example/steal",
    "http://evil.example",
    "//evil.example/steal",
    "\\\\evil.example",
    "https:evil.example",
    "javascript:alert(1)",
    "  https://evil.example",
]


class _FakeDb:
    """Enough of ``AsyncSession`` for a transport-level test: ``/cas/validate`` takes a
    session from the pool before it does anything, and without a lifespan there is no
    pool. Nothing here is the subject — the state check happens before any DB use."""

    def __init__(self) -> None:
        self.commit = AsyncMock()

    def add(self, obj: object) -> None:
        return None

    async def flush(self) -> None:
        return None


@pytest.fixture
def cas_client() -> Iterator[TestClient]:
    """CAS genuinely on, no dev fake user — the real round trip."""
    from src.api.main import get_session

    settings = Settings(cas_enabled=True, cas_dev_fake_user="")
    app.dependency_overrides[get_settings] = lambda: settings

    async def _session() -> Iterator[_FakeDb]:
        yield _FakeDb()

    app.dependency_overrides[get_session] = _session
    yield TestClient(app, follow_redirects=False)
    app.dependency_overrides.clear()


def _stub_successful_login(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    """Everything downstream of the state check, faked at the service boundary — the
    ticket validation, the user provisioning and the session row. None of it is the
    subject here; it just has to not be ``None`` for the route to reach its redirect."""
    monkeypatch.setattr(
        auth_routes.cas_service, "validate_ticket", AsyncMock(return_value="real-user")
    )
    provision = AsyncMock(return_value=user_holding(Role.AUTHOR, username="real-user"))
    monkeypatch.setattr(auth_routes.user_service, "provision_or_get", provision)
    monkeypatch.setattr(auth_routes.user_service, "ensure_role", AsyncMock())
    monkeypatch.setattr(
        auth_routes.session_service,
        "create_session",
        AsyncMock(return_value=SimpleNamespace(id="a-session-id")),
    )
    return provision


def _service_next(location: str) -> str:
    """The `next` the app asked CAS to come back to, dug out of the service URL."""
    service = parse_qs(urlsplit(location).query)["service"][0]
    return parse_qs(urlsplit(unquote(service)).query).get("next", [""])[0]


# ── 1. The open redirect ─────────────────────────────────────────────────────────


@pytest.mark.parametrize("hostile", HOSTILE_NEXT, ids=lambda v: v.strip()[:24])
def test_a_hostile_next_never_reaches_the_cas_service_url(
    hostile: str, cas_client: TestClient
) -> None:
    """The measured defect. What we hand CAS is what the browser is sent to after
    authenticating, so an off-site value here is the whole attack."""
    resp = cas_client.get(f"/jd-bank/ui/cas/login?next={hostile}")

    assert (
        _service_next(resp.headers["location"]) == HOME
    ), f"next={hostile!r} survived into the CAS service URL"


@pytest.mark.parametrize("hostile", HOSTILE_NEXT, ids=lambda v: v.strip()[:24])
def test_the_login_page_never_renders_a_link_to_a_hostile_next(
    hostile: str, cas_client: TestClient
) -> None:
    """The page a victim actually clicks. It rendered the value straight into the
    sign-in link, so the redirect chain began before CAS was even involved."""
    body = cas_client.get(f"/jd-bank/ui/login?next={hostile}").text

    assert "evil.example" not in body
    assert "javascript:" not in body


@pytest.mark.parametrize("hostile", HOSTILE_NEXT, ids=lambda v: v.strip()[:24])
def test_a_hostile_next_is_not_honoured_on_the_way_back(
    hostile: str, cas_client: TestClient
) -> None:
    """The last leg, which is where the browser is actually sent. Belt to the braces:
    even if a hostile value somehow reached this route, it is refused here too."""
    resp = cas_client.get(f"/jd-bank/ui/cas/validate?next={hostile}")

    assert "evil.example" not in resp.headers.get("location", "")


def test_a_local_next_still_works(cas_client: TestClient) -> None:
    """The other direction: this must not break returning a user to where they were."""
    resp = cas_client.get("/jd-bank/ui/cas/login?next=/jd-bank/ui/queue")

    assert _service_next(resp.headers["location"]) == "/jd-bank/ui/queue"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("/jd-bank/ui/queue", "/jd-bank/ui/queue"),
        ("/jd-bank/ui/role/abc?q=x", "/jd-bank/ui/role/abc?q=x"),
        ("", HOME),
        ("relative/path", HOME),
        ("/", "/"),
    ],
)
def test_safe_next_keeps_local_paths_and_replaces_everything_else(
    value: str, expected: str
) -> None:
    assert safe_next(value) == expected


# ── 2. Login CSRF ────────────────────────────────────────────────────────────────


def test_starting_a_login_issues_a_state_cookie_and_echoes_it_to_cas(
    cas_client: TestClient,
) -> None:
    resp = cas_client.get("/jd-bank/ui/cas/login")

    state = resp.cookies.get(LOGIN_STATE_COOKIE)
    assert state, "no login-state cookie was set, so validate has nothing to check"
    service = parse_qs(urlsplit(resp.headers["location"]).query)["service"][0]
    assert f"state={state}" in unquote(
        service
    ), "the state was not echoed to CAS, so it cannot come back to be compared"
    cookie_header = resp.headers["set-cookie"]
    assert "HttpOnly" in cookie_header, (
        "the state cookie must be HttpOnly — script-readable state is state an "
        "attacker can copy into their own request"
    )


def test_a_ticket_with_no_state_cookie_is_refused(
    cas_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """**The attack, exactly.** The attacker holds a valid CAS ticket for their own
    account and gets the victim's browser to fetch this URL. The victim's browser has no
    state cookie for a round trip it never started."""
    validate = AsyncMock(return_value="attacker")
    monkeypatch.setattr(auth_routes.cas_service, "validate_ticket", validate)

    resp = cas_client.get("/jd-bank/ui/cas/validate?ticket=ST-attacker&state=whatever")

    assert resp.status_code in (303, 400, 403)
    assert not resp.cookies.get(
        "jdbank_session"
    ), "a session was minted for a login this browser never started"
    validate.assert_not_awaited(), (
        "the ticket was sent to CAS before the state was checked — the check must come "
        "first, or the round trip happens on an attacker's say-so"
    )


def test_a_state_that_does_not_match_the_cookie_is_refused(
    cas_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The attacker CAN get a state of their own — ``/cas/login`` is public. What they
    cannot do is put it in the victim's browser, so the comparison is what protects."""
    validate = AsyncMock(return_value="attacker")
    monkeypatch.setattr(auth_routes.cas_service, "validate_ticket", validate)
    cas_client.cookies.set(LOGIN_STATE_COOKIE, "the-victims-own-state")

    resp = cas_client.get(
        "/jd-bank/ui/cas/validate?ticket=ST-attacker&state=the-attackers-state"
    )

    assert resp.status_code in (303, 400, 403)
    validate.assert_not_awaited()


def test_the_state_comparison_is_not_merely_presence(
    cas_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A guard that only checked "is there a cookie" would pass the attack above."""
    validate = AsyncMock(return_value="attacker")
    monkeypatch.setattr(auth_routes.cas_service, "validate_ticket", validate)
    cas_client.cookies.set(LOGIN_STATE_COOKIE, "abc")

    refused = cas_client.get("/jd-bank/ui/cas/validate?ticket=T&state=abcd")

    assert refused.status_code in (303, 400, 403)
    validate.assert_not_awaited()


def test_a_login_this_browser_started_completes(
    cas_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The whole point of the control is that it does not break the real flow: start at
    ``/cas/login``, come back with the state that was issued, and sign in."""
    start = cas_client.get("/jd-bank/ui/cas/login")
    state = start.cookies[LOGIN_STATE_COOKIE]
    service = parse_qs(urlsplit(start.headers["location"]).query)["service"][0]
    query = urlsplit(unquote(service)).query

    provision = _stub_successful_login(monkeypatch)

    resp = cas_client.get(f"/jd-bank/ui/cas/validate?ticket=ST-real&{query}")

    assert f"state={state}" in query
    assert provision.await_count == 1, (
        "a browser completing the round trip it started was refused; the control has "
        "broken the flow it exists to protect"
    )
    assert resp.status_code == 302
    assert resp.headers["location"] == HOME


def test_the_state_cookie_is_cleared_once_used(
    cas_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """It is single-use by intent: leaving it set makes a stale state reusable, and it
    is worthless after the round trip completes."""
    start = cas_client.get("/jd-bank/ui/cas/login")
    service = parse_qs(urlsplit(start.headers["location"]).query)["service"][0]
    query = urlsplit(unquote(service)).query
    _stub_successful_login(monkeypatch)

    resp = cas_client.get(f"/jd-bank/ui/cas/validate?ticket=ST-real&{query}")

    set_cookie = resp.headers.get("set-cookie", "")
    assert LOGIN_STATE_COOKIE in set_cookie and (
        "Max-Age=0" in set_cookie or "expires=Thu, 01 Jan 1970" in set_cookie.lower()
    ), "the login-state cookie outlived the round trip it belongs to"

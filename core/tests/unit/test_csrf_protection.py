"""CSRF for cookie-authenticated state changes (P0.1b-i) — the table of record.

**The rule this file pins, in one sentence:**

    *Any state-changing request that was authenticated by a session cookie must carry
    that session's CSRF token.*

That is the whole contract. It is deliberately stated as a property of **the request**,
not of a route, so there is no per-route allow-list to drift and no author who has to
remember anything: a new ``POST`` anywhere in the app is protected the moment it exists,
and :func:`test_the_table_covers_every_state_changing_route` turns red if it is not in
this file's table.

**Why this is needed at all.** P0.1a made the actor server-derived and P0.2 made the
production posture enforceable. Neither stops a page on another origin from causing a
signed-in reviewer's browser to POST ``/jd-bank/ui/review/{id}/approve`` — the browser
attaches the session cookie, the app derives a perfectly genuine reviewer identity from
it, and the append-only audit chain records a real person approving a JD they never
looked at. NN #1 (human approval) is not satisfied by a human's *browser*.

**Defence in depth on top of ``SameSite=Lax``, not a replacement for it.** Every
mutation in this app is a POST, and ``Lax`` already withholds the cookie from a
cross-site POST — so today's exposure is smaller than "no defence at all" suggests. It
is not zero: ``Lax`` is a *browser* behaviour (an old or non-conforming client does not
apply it), it does not apply between same-site subdomains, and a cookie policy is not
something this service can verify at runtime. A token the server issues and checks is
something it *can* verify. Both, therefore. See ``test_production_posture.py``
§``session_cookie_samesite`` for the cookie half and the ruling behind it.

── What "the request was authenticated by a session cookie" means, and why the
   converse is not a bypass ──────────────────────────────────────────────────────────

A request with **no live session** is skipped, because there is nothing to protect: an
attacker who does not need a victim's cookie does not need a victim. Two cases:

* ``cas_enabled=False`` (the dev/CI posture) — ``resolve_user`` short-circuits before
  reading any cookie and returns a transient admin, so there is no ambient cookie
  authority to borrow and no session row to hold a token. Anyone who can reach the port
  can already POST directly with ``curl``. **This is the one shape of exemption that
  burned this repo before** (P0.1a's gates only bound with CAS on), so it is nailed down
  twice: the exemption is a property of the *request* rather than a config branch, and
  the posture that produces it is one ``Settings`` **refuses to load in production**
  (``test_production_posture.py::VIOLATIONS['cas_disabled']``). It cannot be the
  posture of a real deployment.
* CAS on, no/expired/revoked cookie — every state-changing UI route except ``logout``
  is gated, so the authorization layer refuses the request anyway.
  :func:`test_a_state_change_with_no_session_never_reaches_the_service` pins exactly
  that, so "skip when there is no session" can never become "skip and proceed".

── ``logout``: the ruling (contract item E) ─────────────────────────────────────────

``POST /jd-bank/ui/logout`` is deliberately ungated so an expired session can still log
out. It needs **no exemption at all**, because the rule above already covers it
correctly:

* An **authenticated** logout is a cookie-authenticated state change (it revokes a
  session row), so it requires the token, exactly like every other route. Forced logout
  is low severity, but the fix costs one hidden field in ``_base.html`` and a uniform
  rule is worth more than a saved line.
* A logout carrying **no live session** revokes nothing, so it is not a state change and
  is allowed through — which preserves the documented escape hatch (an expired session
  must be able to log out rather than be told to sign in first) without adding a
  route-specific carve-out.

One thing the second bullet forces, and it is the reason this is a ruling rather than a
restatement: **an unauthenticated logout must not clear the cookie either.**
``SameSite`` restricts which requests *carry* a cookie; it does not restrict which
responses may *set* one. So a cross-site ``POST /jd-bank/ui/logout`` arrives with no
session cookie (Lax), skips the token check (no session), and — as the route stands —
still answers with a ``Set-Cookie`` that deletes the victim's session cookie. A forced
logout, achieved without ever holding the cookie. Dropping the cookie-clearing from the
*unauthenticated* path closes it, and costs nothing: the cookie left behind is expired
or revoked, ``resolve_user`` rejects it, and the next successful login overwrites it.
See :func:`test_an_unauthenticated_logout_does_not_clear_the_session_cookie`.

``logout`` therefore stays ``public`` in ``test_authorization_matrix.py``'s
``PUBLIC_STATE_CHANGES``: it is still reachable without credentials, and that table
stays an honest description of the app.

── The JSON API is IN scope. An earlier version of this file said otherwise ─────────

This section used to read *"the JSON API is out of scope"*, on the grounds that a
cross-site HTML form cannot drive ``/jd-bank/review/*`` or ``/jd-bank/compose/*``: a
form may only send ``application/x-www-form-urlencoded``, ``multipart/form-data`` or
``text/plain``, FastAPI hands a non-JSON body to a Pydantic model as raw bytes and it
fails validation, and anything that *could* set ``Content-Type: application/json``
(``fetch``/XHR) is preflighted with no CORS middleware installed.

**That argument is still true for those eight routes, and it was the wrong conclusion
for the app.** It generalises to "a JSON route needs no protection", and one JSON route
has no body at all: ``POST /gates/run`` takes ``branch`` as a **query parameter**, so a
plain ``<form method="POST" action="…/gates/run?branch=x">`` with an admin's cookie
enqueued an arq job — measured, before the fix: ``200``, ``enqueue_job`` awaited once.
So the guard is mounted app-wide and this file's table covers **every** state-changing
route the app serves, not only the browser ones.

Two consequences are pinned rather than described:

* The Pydantic-bodied routes still cannot be driven by a form body — that reasoning is
  load-bearing for *why the header is safe*, so it stays a test:
  :func:`test_a_cross_site_shaped_form_post_cannot_drive_the_json_review_api`.
* A JSON body cannot carry a hidden form field, so for those routes ``X-CSRF-Token`` is
  the **only** way to comply, not a convenience. Its safety rests on one global property
  of the app — that no CORS middleware is installed — which nothing else pins:
  :func:`test_no_cors_middleware_is_installed`.

── Framing defeats this control, so the headers that prevent it are pinned here ─────

A token stops a cross-site page *making* the request. It does nothing about one
*framing* ours: an invisible iframe over ``/jd-bank/ui/review/{id}`` and a decoy button
gets the reviewer to click Approve on our own page, which carries its own valid token
and posts same-origin. Clickjacking borrows the control rather than bypassing it, which
is why :func:`test_a_page_cannot_be_framed_by_another_origin` lives in this file and not
on a hardening backlog.

── Not register-bearing ─────────────────────────────────────────────────────────────

Transport security, not a rulebook metric or an HR policy: no ``decision_register.yaml``
entry, and ``rules_version`` does not move.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from src.api import csrf
from src.api import main as api_main
from src.api.db.models import Role
from src.api.main import app, get_session
from src.api.routes import admin as admin_routes
from src.api.routes import auth as auth_routes
from src.api.routes import compose as compose_routes
from src.api.routes import compose_ui, ui
from src.api.routes import jd_bank as jd_bank_routes
from src.jd_bank.composer import ComposerAnswers, assemble_jd, assess_draft
from src.jd_bank.composer.assist import SummarySuggestion
from tests.unit import test_authorization_matrix as authz
from tests.unit.auth_fakes import (
    cas_on,
    signed_in_as,
    signed_in_with_session,
    user_holding,
)

#: The hidden form field the token rides in. One name, used by the macro that renders it
#: and by the check that reads it.
CSRF_FIELD = "csrf_token"

#: The header a JSON client presents the same token in — its only option, since a JSON
#: body cannot carry a form field. Read off the implementation so the two cannot drift.
CSRF_HEADER = csrf.CSRF_HEADER

#: Everything mounted under here is a cookie-authenticated browser surface.
UI_PREFIX = "/jd-bank/ui"

SESSION_ID = "the-live-session-cookie-value"
SESSION_CSRF = "the-live-sessions-csrf-token"
#: A token that is well-formed and valid — for somebody else's session. The interesting
#: negative: a check that merely asks "is this a token we ever issued?" passes it.
ANOTHER_SESSIONS_CSRF = "a-different-sessions-csrf-token"

#: A minimal valid ``ComposerAnswers`` payload — the hidden field submit/export rebuild
#: the draft from. Every field is optional, so a title is enough.
ANSWERS_JSON = '{"title": "Analyst"}'

_TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "src" / "api" / "templates"


# ── The table: every state-changing UI route, and how to prove its effect ────────────


@dataclass(frozen=True)
class StateChange:
    """One state-changing route: how to drive it, and an installer that replaces the
    thing it *does* with a mock, so a test can assert that a refused request never
    reached it. A rejection AFTER the effect is not a fix (contract D).

    ``token_in`` is not decoration. A browser form carries the token as a hidden field;
    a JSON route's body is a Pydantic model that cannot hold one, so its **only**
    satisfying path is the ``X-CSRF-Token`` header. Writing that per route is what makes
    the accepted-case test prove the right thing for each surface — and what would turn
    red if someone deleted the header branch believing it to be unused.
    """

    install: Callable[[pytest.MonkeyPatch], Any]
    #: form-encoded body (browser surfaces).
    form: dict[str, str] | None = None
    #: JSON body (the Pydantic-bodied JSON routes). Must be VALID: FastAPI decodes the
    #: body before it solves dependencies, so a form body on a JSON route 422s before
    #: the CSRF check ever runs and would prove nothing about it.
    json: dict[str, Any] | None = None
    #: query parameters (``POST /gates/run`` declares no body at all — the shape that
    #: made an app-wide mount necessary).
    query: dict[str, str] | None = None
    #: "form" or "header" — where a compliant client puts the token.
    token_in: str = "form"

    def send(
        self, client: TestClient, method: str, path: str, token: str | None = None
    ) -> Any:
        """Issue this request, optionally carrying ``token`` the way this route's
        clients have to."""
        headers: dict[str, str] = {}
        data = dict(self.form) if self.form is not None else None
        if token is not None:
            if self.token_in == "header":
                headers[CSRF_HEADER] = token
            else:
                data = {**(data or {}), CSRF_FIELD: token}
        return client.request(
            method,
            path,
            data=data,
            json=self.json,
            params=self.query,
            headers=headers or None,
        )


class _FakeClose:
    """An injected client whose only obligation here is to be closeable."""

    async def close(self) -> None:
        return None


class _FakeChat(_FakeClose):
    """Stands in for ``ChatClient`` so ``/assist`` can resolve its dependency without
    constructing a real (egress-guarded, network-capable) one."""


def _review_effect(name: str) -> Callable[[pytest.MonkeyPatch], Any]:
    def install(monkeypatch: pytest.MonkeyPatch) -> Any:
        mock = AsyncMock(return_value=SimpleNamespace(id=uuid.uuid4()))
        monkeypatch.setattr(ui.service, name, mock)
        return mock

    return install


def _admin_effect(name: str) -> Callable[[pytest.MonkeyPatch], Any]:
    def install(monkeypatch: pytest.MonkeyPatch) -> Any:
        mock = AsyncMock(return_value=None)
        monkeypatch.setattr(admin_routes.user_service, name, mock)
        return mock

    return install


def _logout_effect(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Revoking the session row IS logout's state change."""
    mock = AsyncMock(return_value=None)
    monkeypatch.setattr(auth_routes.session_service, "revoke_session", mock)
    return mock


def _check_effect(monkeypatch: pytest.MonkeyPatch) -> Any:
    """``POST /compose/new`` persists nothing, but it does run the validator over an
    attacker-supplied draft and render it back. ``wraps`` the real function so the
    accepted case still produces a real page."""
    mock = MagicMock(side_effect=assess_draft)
    monkeypatch.setattr(compose_ui, "assess_draft", mock)
    return mock


def _assist_effect(monkeypatch: pytest.MonkeyPatch) -> Any:
    """``POST /compose/assist`` drives the self-hosted LLM — a cross-site page must not
    be able to spend GPU time on our behalf."""
    assessment = assess_draft(assemble_jd(ComposerAnswers(title="Analyst")))
    mock = AsyncMock(
        return_value=SummarySuggestion(
            suggested_summary="A summary.",
            word_count=2,
            grounded_fraction=1.0,
            assessment=assessment,
            model="test-model",
            prompt_version="test",
        )
    )
    monkeypatch.setattr(compose_ui, "suggest_summary", mock)
    return mock


def _submit_effect(monkeypatch: pytest.MonkeyPatch) -> Any:
    mock = AsyncMock(return_value=SimpleNamespace(id=uuid.uuid4()))
    monkeypatch.setattr(compose_ui, "submit_composed_draft", mock)
    return mock


def _export_effect(monkeypatch: pytest.MonkeyPatch) -> Any:
    mock = MagicMock(return_value=b"PK\x03\x04")
    monkeypatch.setattr(compose_ui, "render_sfu_docx", mock)
    return mock


# ── The non-browser surfaces (the eight JSON routes + the two harness ones) ──────────


def _json_review_effect(name: str) -> Callable[[pytest.MonkeyPatch], Any]:
    """The JSON review API's mutations — the same NN #1 publish surface as the UI."""

    def install(monkeypatch: pytest.MonkeyPatch) -> Any:
        mock = AsyncMock(
            return_value=SimpleNamespace(
                id=uuid.uuid4(), cluster_id=uuid.uuid4(), version=1, status="published"
            )
        )
        monkeypatch.setattr(jd_bank_routes.service, name, mock)
        return mock

    return install


def _json_validate_effect(monkeypatch: pytest.MonkeyPatch) -> Any:
    mock = MagicMock(side_effect=assess_draft)
    monkeypatch.setattr(compose_routes, "assess_draft", mock)
    return mock


def _json_assist_effect(monkeypatch: pytest.MonkeyPatch) -> Any:
    assessment = assess_draft(assemble_jd(ComposerAnswers(title="Analyst")))
    mock = AsyncMock(
        return_value=SummarySuggestion(
            suggested_summary="A summary.",
            word_count=2,
            grounded_fraction=1.0,
            assessment=assessment,
            model="test-model",
            prompt_version="test",
        )
    )
    monkeypatch.setattr(compose_routes, "suggest_summary", mock)
    return mock


def _json_export_effect(monkeypatch: pytest.MonkeyPatch) -> Any:
    mock = MagicMock(return_value=b"PK\x03\x04")
    monkeypatch.setattr(compose_routes, "render_sfu_docx", mock)
    return mock


def _enqueue_effect(monkeypatch: pytest.MonkeyPatch) -> Any:
    """``app.state.arq.enqueue_job`` — what ``POST /tasks`` and ``POST /gates/run`` do.

    ``/gates/run`` is the route that settled the app-wide-mount question: ``branch`` is
    a **query parameter and it declares no body**, so nothing about a JSON content type
    stood between a cross-site form and this call.
    """
    mock = AsyncMock(return_value=SimpleNamespace(job_id="job-1"))
    monkeypatch.setattr(
        api_main.app.state, "arq", SimpleNamespace(enqueue_job=mock), raising=False
    )
    return mock


#: A minimal VALID ``SFUJobDescription`` body for the JSON compose routes. Built through
#: the real composer so it stays valid if the model changes.
JD_JSON: dict[str, Any] = assemble_jd(ComposerAnswers(title="Analyst")).model_dump(
    mode="json"
)


#: (METHOD, route template) -> how to drive it and how to see whether it fired.
#: Asserted EQUAL to the live routing table below — this is not a hand-kept list that
#: may lag; it is a list the routing table refuses to let lag. **Every** state-changing
#: route, not only the browser ones: see the module docstring on ``/gates/run``.
STATE_CHANGES: dict[tuple[str, str], StateChange] = {
    # ── Browser surface: the token rides in a hidden form field ──────────────────
    ("POST", "/jd-bank/ui/logout"): StateChange(_logout_effect, form={}),
    ("POST", "/jd-bank/ui/review/{canonical_id}/approve"): StateChange(
        _review_effect("approve"), form={}
    ),
    ("POST", "/jd-bank/ui/review/{canonical_id}/reject"): StateChange(
        _review_effect("reject"), form={"reason": "not compliant"}
    ),
    ("POST", "/jd-bank/ui/review/{canonical_id}/edit"): StateChange(
        _review_effect("edit"),
        form={"title": "Software Developer", "reason": "fixed a typo"},
    ),
    ("POST", "/jd-bank/ui/compose/new"): StateChange(
        _check_effect, form={"title": "Analyst"}
    ),
    ("POST", "/jd-bank/ui/compose/assist"): StateChange(
        _assist_effect, form={"title": "Analyst"}
    ),
    ("POST", "/jd-bank/ui/compose/submit"): StateChange(
        _submit_effect, form={"answers_json": ANSWERS_JSON}
    ),
    ("POST", "/jd-bank/ui/compose/export"): StateChange(
        _export_effect, form={"answers_json": ANSWERS_JSON}
    ),
    ("POST", "/jd-bank/ui/admin/users/{user_id}/roles"): StateChange(
        _admin_effect("set_roles"), form={"roles": "reviewer"}
    ),
    ("POST", "/jd-bank/ui/admin/users/{user_id}/status"): StateChange(
        _admin_effect("set_status"), form={"status": "active"}
    ),
    # ── JSON review API: same NN #1 publish surface, header-only compliance ──────
    ("POST", "/jd-bank/review/{canonical_id}/approve"): StateChange(
        _json_review_effect("approve"), json={}, token_in="header"
    ),
    ("POST", "/jd-bank/review/{canonical_id}/reject"): StateChange(
        _json_review_effect("reject"),
        json={"reason": "not compliant"},
        token_in="header",
    ),
    ("POST", "/jd-bank/review/{canonical_id}/edit"): StateChange(
        _json_review_effect("edit"),
        json={"new_content": {"title": "Analyst"}, "reason": "fixed a typo"},
        token_in="header",
    ),
    # ── JSON compose API: no publish, but it discloses content and drives the GPU ─
    ("POST", "/jd-bank/compose/validate"): StateChange(
        _json_validate_effect, json=JD_JSON, token_in="header"
    ),
    ("POST", "/jd-bank/compose/assist/summary"): StateChange(
        _json_assist_effect, json=JD_JSON, token_in="header"
    ),
    ("POST", "/jd-bank/compose/export"): StateChange(
        _json_export_effect, json=JD_JSON, token_in="header"
    ),
    # ── Legacy harness API. `/gates/run` is the one with NO body at all ──────────
    ("POST", "/tasks"): StateChange(
        _enqueue_effect,
        json={"title": "a task", "spec": "do the thing please"},
        token_in="header",
    ),
    ("POST", "/gates/run"): StateChange(
        _enqueue_effect, query={"branch": "agent/attacker"}, token_in="header"
    ),
}


def _live_state_changing_routes() -> frozenset[tuple[str, str]]:
    """Every state-changing route the app **actually serves**, on any surface.

    Derived from the live routing table (via the authorization matrix's walk, which is
    itself cross-checked against FastAPI's OpenAPI table and *raises* rather than skips
    anything it cannot resolve) — so a newly added ``POST`` appears here on the day it
    is written, with no one having to remember this file exists.
    """
    return frozenset(
        (method, path)
        for method, path in authz._iter_routes(app.routes)
        if method in authz._STATE_CHANGING
    )


def _live_state_changing_ui_routes() -> frozenset[tuple[str, str]]:
    """The browser subset of :func:`_live_state_changing_routes` — still needed on its
    own, because it is one of the two independent opinions
    :func:`test_the_prefix_and_the_matrix_agree_on_what_a_browser_write_is` compares."""
    return frozenset(
        (method, path)
        for method, path in _live_state_changing_routes()
        if path.startswith(UI_PREFIX)
    )


def _route_ids() -> list[str]:
    return [f"{method} {path}" for method, path in sorted(STATE_CHANGES)]


def _split(route_id: str) -> tuple[str, str]:
    method, path = route_id.split(" ", 1)
    return method, path


# ── Fixtures ─────────────────────────────────────────────────────────────────────────


@dataclass
class SignedIn:
    client: TestClient
    session_id: str
    csrf_token: str


class _FakeDb:
    """Enough of ``AsyncSession`` for a transport-level test.

    Almost every handler here calls a mocked service, but ``POST /tasks`` does its own
    add/flush/commit inline and its response model needs the ``id`` a real INSERT would
    have filled in from the column default — so ``flush`` stamps one, which is the only
    behaviour of a real flush these tests depend on.
    """

    def __init__(self) -> None:
        self.commit = AsyncMock()
        self._pending: list[Any] = []

    def add(self, obj: Any) -> None:
        self._pending.append(obj)

    async def flush(self) -> None:
        for obj in self._pending:
            if getattr(obj, "id", None) is None:
                obj.id = uuid.uuid4()


@pytest.fixture
def signed_in(monkeypatch: pytest.MonkeyPatch) -> Iterator[SignedIn]:
    """A browser signed in **for real**: CAS on, a session cookie, and a live session
    row (faked at the service boundary) carrying a CSRF token.

    Roles are reviewer AND admin so one fixture can reach every route in the table; the
    role checks themselves are the authorization matrix's job, not this file's.
    """
    settings = cas_on()
    user = user_holding(Role.REVIEWER, Role.ADMIN, username="reviewer-1")
    signed_in_with_session(
        monkeypatch, user, session_id=SESSION_ID, csrf_token=SESSION_CSRF
    )

    db = _FakeDb()

    async def _override_session() -> AsyncIterator[_FakeDb]:
        yield db

    app.dependency_overrides[get_session] = _override_session
    # The Builder's injected clients: `/compose/new` resolves the optional pair and
    # `/assist` the chat client. Wired so the ACCEPTED case can complete; a rejected
    # request must not reach them at all.
    app.dependency_overrides[compose_routes.get_optional_embed_client] = _FakeClose
    app.dependency_overrides[compose_routes.get_optional_neo4j_driver] = _FakeClose
    app.dependency_overrides[compose_routes.get_chat_client] = _FakeChat

    client = TestClient(app, follow_redirects=False, raise_server_exceptions=False)
    client.cookies.set(settings.session_cookie_name, SESSION_ID)
    yield SignedIn(client=client, session_id=SESSION_ID, csrf_token=SESSION_CSRF)
    app.dependency_overrides.clear()


@pytest.fixture
def anonymous(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """CAS on, no cookie — the cross-site attacker's view once ``Lax`` has done its job
    and withheld the victim's cookie."""
    cas_on()
    user = user_holding(Role.REVIEWER, Role.ADMIN)
    signed_in_with_session(
        monkeypatch, user, session_id=SESSION_ID, csrf_token=SESSION_CSRF
    )

    db = _FakeDb()

    async def _override_session() -> AsyncIterator[_FakeDb]:
        yield db

    app.dependency_overrides[get_session] = _override_session
    app.dependency_overrides[compose_routes.get_optional_embed_client] = _FakeClose
    app.dependency_overrides[compose_routes.get_optional_neo4j_driver] = _FakeClose
    app.dependency_overrides[compose_routes.get_chat_client] = _FakeChat
    yield TestClient(app, follow_redirects=False, raise_server_exceptions=False)
    app.dependency_overrides.clear()


# ── 0. The safety nets that stop everything below being a false green ────────────────


def test_the_table_covers_every_state_changing_route() -> None:
    """The fail-closed enumerator, and the most valuable test in this file.

    The two previous safety nets in this repo were each green while a hole existed, so
    the set under test is derived from the routing table rather than typed out: add a
    ``POST`` **anywhere** and this goes red until it is classified and covered by the
    four cases below.

    This deliberately spans every surface, not just ``/jd-bank/ui``. Scoping it to the
    browser prefix is what hid ``POST /gates/run`` — a query-parameter route with no
    body, drivable by an ordinary cross-site form — and a table that describes only part
    of the app is the shape of safety net that has already been green over a hole twice
    in this repo.
    """
    served = _live_state_changing_routes()
    covered = frozenset(STATE_CHANGES)

    uncovered = sorted(served - covered)
    assert not uncovered, (
        f"these state-changing routes have no CSRF coverage: {uncovered}. Add a "
        "STATE_CHANGES entry (how to drive it, where its clients put the token, and "
        "the mock that proves its effect) — a new write must not ship without one."
    )
    stale = sorted(covered - served)
    assert not stale, (
        f"STATE_CHANGES covers routes the app no longer serves: {stale}. Delete them "
        "so this table stays an honest description of the app."
    )


def test_the_prefix_and_the_matrix_agree_on_what_a_browser_write_is() -> None:
    """A second, independent opinion on the same set.

    This file selects browser writes by mount path (``/jd-bank/ui``); the authorization
    matrix classifies every route's surface by hand (``Surface.UI``). If those two ever
    disagree, one of them is describing a different app — for example a UI router
    mounted outside the prefix, or a JSON route that quietly acquired a redirecting
    gate — and the CSRF set would be silently wrong either way.
    """
    by_prefix = _live_state_changing_ui_routes()
    by_matrix = frozenset(
        key
        for key, rule in authz.EXPECTED_ACCESS.items()
        if key[0] in authz._STATE_CHANGING and rule.surface is authz.Surface.UI
    )

    assert by_prefix == by_matrix, (
        "the two definitions of 'state-changing browser route' disagree.\n"
        f"  under {UI_PREFIX} but not Surface.UI: {sorted(by_prefix - by_matrix)}\n"
        f"  Surface.UI but not under {UI_PREFIX}: {sorted(by_matrix - by_prefix)}"
    )


def test_the_signed_in_fixture_really_resolves_a_live_session(
    signed_in: SignedIn, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Guard against the easiest false green here.

    If the fixture's cookie did NOT resolve to a session, every "403 without a token"
    test below would pass for the wrong reason — the authorization gate refusing an
    unauthenticated request — and would keep passing against an app with no CSRF check
    at all. A gated UI read must therefore answer 200, not a redirect to login.
    """
    monkeypatch.setattr(ui.service, "list_review_queue", AsyncMock(return_value=[]))

    resp = signed_in.client.get("/jd-bank/ui/queue")

    assert resp.status_code == 200, (
        f"the signed-in fixture is not signed in (got {resp.status_code} from a gated "
        "read) — every CSRF test in this file is meaningless until that is fixed"
    )


# ── 1. Refusal: missing, wrong, and another session's token (contracts C + D) ────────


@pytest.mark.parametrize("route_id", _route_ids(), ids=lambda x: x)
def test_a_state_change_without_a_csrf_token_is_refused(
    route_id: str, signed_in: SignedIn, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The base case: the cross-site form as an attacker would write it — the victim's
    cookie, the right fields, no token. 403, and the effect never happens."""
    method, path = _split(route_id)
    change = STATE_CHANGES[(method, path)]
    effect = change.install(monkeypatch)

    resp = change.send(signed_in.client, method, authz._concrete(path))

    assert resp.status_code == 403, (
        f"{route_id} answered {resp.status_code} to a cookie-authenticated request "
        f"carrying no {CSRF_FIELD!r}. Expected 403: this is exactly the request a page "
        "on another origin can make."
    )
    assert not effect.called, (
        f"{route_id} refused the request but had ALREADY done the thing. A rejection "
        "after the effect is not a fix — the check must run before the handler."
    )


@pytest.mark.parametrize("route_id", _route_ids(), ids=lambda x: x)
def test_a_state_change_with_a_wrong_csrf_token_is_refused(
    route_id: str, signed_in: SignedIn, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A guessed / stale / attacker-chosen value must not pass — the check compares
    against the session's token, it does not merely require the field to be present."""
    method, path = _split(route_id)
    change = STATE_CHANGES[(method, path)]
    effect = change.install(monkeypatch)

    resp = change.send(
        signed_in.client, method, authz._concrete(path), "not-the-right-token"
    )

    assert resp.status_code == 403, (
        f"{route_id} accepted a wrong {CSRF_FIELD!r} with {resp.status_code} — the "
        "presence of the field is not the control; matching the session's token is."
    )
    assert not effect.called, f"{route_id} acted on a request with a wrong token"


@pytest.mark.parametrize("route_id", _route_ids(), ids=lambda x: x)
def test_another_sessions_csrf_token_is_refused(
    route_id: str, signed_in: SignedIn, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The token must be bound to **this** session, not merely be a token this service
    issued. An attacker can always obtain a valid token — for their own session, by
    signing in — so a global or per-process token is no protection at all."""
    method, path = _split(route_id)
    change = STATE_CHANGES[(method, path)]
    effect = change.install(monkeypatch)

    resp = change.send(
        signed_in.client, method, authz._concrete(path), ANOTHER_SESSIONS_CSRF
    )

    assert resp.status_code == 403, (
        f"{route_id} accepted another session's token with {resp.status_code}. The "
        "token must be per-session; an attacker can mint one for their own session."
    )
    assert not effect.called, f"{route_id} acted on another session's token"


@pytest.mark.parametrize("route_id", _route_ids(), ids=lambda x: x)
def test_the_sessions_own_csrf_token_is_accepted(
    route_id: str, signed_in: SignedIn, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The other direction, and the reason the three tests above mean anything: with
    the right token the request goes through. A control that refuses everything is a
    brick, and every test above would be green against one.

    For the JSON routes the token can only travel in ``X-CSRF-Token`` — a Pydantic body
    has nowhere to put a form field — so this is also the test that goes red if the
    header branch is deleted as "unused code with no client".
    """
    method, path = _split(route_id)
    change = STATE_CHANGES[(method, path)]
    effect = change.install(monkeypatch)

    resp = change.send(
        signed_in.client, method, authz._concrete(path), signed_in.csrf_token
    )

    assert resp.status_code != 403, (
        f"{route_id} refused a request carrying its own session's token. The CSRF "
        "check has become a brick — reviewers cannot approve anything."
    )
    assert effect.called, (
        f"{route_id} did not refuse (status {resp.status_code}) but never reached its "
        "effect either, so this test proves nothing about the token being accepted."
    )


# ── 2. The skip-when-there-is-no-session branch is not a bypass ──────────────────────


@pytest.mark.parametrize(
    "route_id",
    [r for r in _route_ids() if r != "POST /jd-bank/ui/logout"],
    ids=lambda x: x,
)
def test_a_state_change_with_no_session_never_reaches_the_service(
    route_id: str, anonymous: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The CSRF check is skipped when there is no session — this is what makes that
    safe, and it is asserted here rather than left to another file, because the two
    halves are only a control when they hold together.

    ``logout`` is excluded on purpose: it is ``public`` by design (see the module
    docstring, contract item E) and has its own tests below.
    """
    method, path = _split(route_id)
    change = STATE_CHANGES[(method, path)]
    effect = change.install(monkeypatch)

    resp = change.send(anonymous, method, authz._concrete(path))

    assert resp.status_code in (303, 401, 403), (
        f"{route_id} answered {resp.status_code} to a request with no session — "
        "expected a login redirect or a refusal. If CSRF is skipped for want of a "
        "session AND authorization lets the request through, there is no control left."
    )
    assert not effect.called, f"{route_id} acted on a request with no session at all"


def test_a_cookie_that_resolves_to_no_session_is_not_a_bypass(
    signed_in: SignedIn, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The *other* way to have no session, and the one the test above cannot reach.

    ``anonymous`` sends no cookie at all, so it leaves the guard at the "no cookie"
    line. This sends a cookie that the session lookup does not resolve — expired,
    revoked, or simply invented — which is the separate branch the guard's own docstring
    names as how a check like this fails open. Nothing pinned it, and deleting that
    ``return None`` left the suite green.

    The request must still be refused, by *authorization*: skipping CSRF for want of a
    session is only safe while the thing that made the session absent also makes the
    request unauthenticated.
    """
    change = STATE_CHANGES[("POST", "/jd-bank/ui/review/{canonical_id}/approve")]
    effect = change.install(monkeypatch)
    signed_in.client.cookies.set("jdbank_session", "not-a-session-this-server-issued")

    resp = change.send(
        signed_in.client,
        "POST",
        authz._concrete("/jd-bank/ui/review/{canonical_id}/approve"),
    )

    assert resp.status_code in (303, 401, 403), (
        f"a cookie that resolves to no live session answered {resp.status_code}. The "
        "CSRF check skips it (correctly — there is no session to protect), so "
        "authorization is the only thing left, and it must refuse."
    )
    assert not effect.called, "an unresolvable session cookie reached the service"


def test_a_body_that_is_not_utf8_is_refused_rather_than_crashing(
    signed_in: SignedIn, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A crafted body must be a 403, not a 500.

    The guard reads the body before the handler, so a body that is not valid UTF-8
    raises inside the *check*. Without the ``except UnicodeDecodeError`` it becomes an
    unhandled 500 on a cookie-authenticated POST — a self-inflicted error surface, and
    an implementation detail leaked to whoever sent the bytes. Deleting that branch also
    left the suite green.
    """
    effect = _review_effect("approve")(monkeypatch)

    resp = signed_in.client.post(
        authz._concrete("/jd-bank/ui/review/{canonical_id}/approve"),
        content=b"\xff\xfe not utf-8 at all",
        headers={"content-type": "application/x-www-form-urlencoded"},
    )

    assert resp.status_code == 403, (
        f"a non-UTF-8 body answered {resp.status_code}; expected 403. A body the check "
        "cannot read carries no token, which is a refusal, not a crash."
    )
    assert not effect.called


# ── 3. logout (contract item E) ──────────────────────────────────────────────────────


def test_an_authenticated_logout_without_a_token_is_refused_and_revokes_nothing(
    signed_in: SignedIn, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A logout that carries a live session IS a cookie-authenticated state change, so
    the uniform rule applies and no exemption is written down for it."""
    revoke = _logout_effect(monkeypatch)

    resp = signed_in.client.post("/jd-bank/ui/logout")

    assert resp.status_code == 403
    revoke.assert_not_awaited()


def test_an_authenticated_logout_with_the_right_token_still_works(
    signed_in: SignedIn, monkeypatch: pytest.MonkeyPatch
) -> None:
    """And the button on every page keeps working."""
    revoke = _logout_effect(monkeypatch)

    resp = signed_in.client.post(
        "/jd-bank/ui/logout", data={CSRF_FIELD: signed_in.csrf_token}
    )

    assert resp.status_code == 303
    assert resp.headers["location"] == "/jd-bank/ui/login"
    revoke.assert_awaited_once()


def test_a_logout_with_no_live_session_is_still_allowed(
    anonymous: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The escape hatch the matrix documents — an expired session must be able to log
    out rather than be told to sign in first — survives, because a session-less logout
    revokes nothing and so is not a state change."""
    revoke = _logout_effect(monkeypatch)

    resp = anonymous.post("/jd-bank/ui/logout")

    assert resp.status_code == 303
    assert resp.headers["location"] == "/jd-bank/ui/login"
    revoke.assert_not_awaited()


def test_an_unauthenticated_logout_does_not_clear_the_session_cookie(
    anonymous: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The one thing a cross-site POST could still accomplish, closed.

    ``SameSite`` governs which requests *carry* a cookie; it does not govern which
    responses may *set* one. So a cross-site ``POST /logout`` arrives with no cookie
    (Lax), skips the token check (no session) — and, as the route is written today,
    answers with a ``Set-Cookie`` that deletes the victim's session anyway. An
    unauthenticated logout must therefore emit no ``Set-Cookie`` at all. Nothing is
    lost: the cookie left behind is expired or revoked, ``resolve_user`` refuses it, and
    the next login overwrites it.
    """
    _logout_effect(monkeypatch)

    resp = anonymous.post("/jd-bank/ui/logout")

    assert "set-cookie" not in {k.lower() for k in resp.headers}, (
        "an unauthenticated logout cleared a cookie. That is a state change an "
        "attacker can cause without ever holding the victim's cookie: "
        f"{resp.headers.get('set-cookie')!r}"
    )


def test_logout_is_still_reachable_without_credentials() -> None:
    """``PUBLIC_STATE_CHANGES`` must keep telling the truth: this ruling protects the
    *authenticated* logout and leaves the route itself public, so the authorization
    matrix's public-write exception is unchanged and still argued in one place."""
    assert ("POST", "/jd-bank/ui/logout") in authz.PUBLIC_STATE_CHANGES


# ── 3b. `X-CSRF-Token`: the JSON surface's only way to comply ────────────────────────
#
# The header branch was very nearly deleted as untested code with no client. It is not
# optional: eight JSON routes have a Pydantic body that cannot hold a form field, so the
# header is the ONLY thing that lets a cookie-authenticated call to them ever succeed —
# without it they are a permanent 403. The parametrized cases above already exercise it
# for those eight; these four pin the properties the parametrized run does not: that it
# also works on a form route, that it is *checked* rather than merely accepted, that it
# cannot shadow a valid form field, and the global invariant that makes it safe at all.


_HEADER_ROUTE = "/jd-bank/ui/review/{canonical_id}/approve"


def test_the_sessions_token_in_the_csrf_header_is_accepted(
    signed_in: SignedIn, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A same-origin script may present the token in the header instead of a field."""
    effect = _review_effect("approve")(monkeypatch)

    resp = signed_in.client.post(
        authz._concrete(_HEADER_ROUTE),
        headers={CSRF_HEADER: signed_in.csrf_token},
    )

    assert resp.status_code != 403, (
        f"a request carrying its own session's token in {CSRF_HEADER!r} was refused "
        f"({resp.status_code}). Every cookie-authenticated call to the eight JSON "
        "routes uses exactly this path and would be a permanent 403."
    )
    assert effect.called


def test_a_wrong_csrf_header_value_is_refused(
    signed_in: SignedIn, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The header is *checked*, not merely accepted — the failure mode that would make
    the whole control cosmetic for the JSON surface."""
    effect = _review_effect("approve")(monkeypatch)

    resp = signed_in.client.post(
        authz._concrete(_HEADER_ROUTE),
        headers={CSRF_HEADER: ANOTHER_SESSIONS_CSRF},
    )

    assert resp.status_code == 403, (
        f"a wrong {CSRF_HEADER!r} was accepted with {resp.status_code} — presence of "
        "the header is not the control; matching the session's token is."
    )
    assert not effect.called


def test_a_stray_header_does_not_shadow_a_valid_form_field(
    signed_in: SignedIn, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Precedence, and it is an availability property rather than a security one.

    If the header were consulted FIRST, a stale or injected ``X-CSRF-Token`` — from a
    proxy, a browser extension, a half-migrated client — would override a perfectly good
    hidden field and 403 every form in the app, with nothing on the page to explain it.
    The body wins. There is no security cost: a body that carries the right field has
    already proved it is not a cross-site form, because one cannot know the token.
    """
    effect = _review_effect("approve")(monkeypatch)

    resp = signed_in.client.post(
        authz._concrete(_HEADER_ROUTE),
        data={CSRF_FIELD: signed_in.csrf_token},
        headers={CSRF_HEADER: "a stale header from some proxy"},
    )

    assert resp.status_code != 403, (
        f"a stray {CSRF_HEADER!r} shadowed a valid form field ({resp.status_code}). "
        "Read the body first: the header exists for requests that have no field, not "
        "to override the ones that do."
    )
    assert effect.called


def test_no_cors_middleware_is_installed() -> None:
    """The global invariant the header rests on, pinned where the header is used.

    A cross-site page cannot set a request header: an HTML form has no mechanism, and a
    cross-origin ``fetch`` that sets one is preflighted — and the preflight is only
    refused while this app installs no CORS middleware. Add one permissively and
    ``X-CSRF-Token`` stops being unforgeable, silently, with every test in this file
    still green. That is exactly the kind of assumption that has to be a test.
    """
    installed = [middleware.cls.__name__ for middleware in app.user_middleware]

    assert not any("CORS" in name.upper() for name in installed), (
        f"a CORS middleware is installed ({installed}). The CSRF header's safety "
        "depends on a cross-origin request never reaching this app without a preflight "
        "it cannot pass — re-derive the header's threat model before allowing this."
    )


# ── 3c. Framing, which borrows this control rather than bypassing it ─────────────────


@pytest.mark.parametrize(
    "path",
    ["/jd-bank/ui/queue", "/jd-bank/ui/compose/new"],
    ids=["review-queue", "builder"],
)
def test_a_page_cannot_be_framed_by_another_origin(
    path: str, signed_in: SignedIn, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Clickjacking fully defeats token CSRF, so the headers that prevent it belong to
    this feature.

    An invisible iframe of ``/jd-bank/ui/review/{id}`` over a decoy button gets a
    signed-in reviewer to click Approve on **our** page: it renders with its own valid
    token and posts same-origin, so every check in this file passes and a JD publishes.
    The token cannot see that; ``X-Frame-Options``/``frame-ancestors`` can. Both are
    asserted — the legacy header for older browsers, the CSP directive for current ones.
    """
    monkeypatch.setattr(ui.service, "list_review_queue", AsyncMock(return_value=[]))

    resp = signed_in.client.get(path)

    assert resp.headers.get("x-frame-options") == "DENY", (
        f"{path} can be framed: X-Frame-Options is "
        f"{resp.headers.get('x-frame-options')!r}. A framed review page carries its "
        "own valid CSRF token, so this defeats the whole control."
    )
    assert "frame-ancestors 'none'" in resp.headers.get(
        "content-security-policy", ""
    ), (
        f"{path} has no `frame-ancestors 'none'` directive "
        f"({resp.headers.get('content-security-policy')!r}) — X-Frame-Options alone is "
        "the legacy half."
    )


# ── 4. The token itself ──────────────────────────────────────────────────────────────


def test_the_session_cookie_value_is_never_rendered_into_the_page(
    signed_in: SignedIn, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The obvious shortcut — use the session id as the CSRF token — is forbidden, and
    this is the half of it a unit test can see: the cookie is ``httponly`` for a reason,
    and the token is written into HTML (and from there into ``Referer`` headers and any
    log that records a form body) for a reason. They cannot be the same secret.

    That the two values genuinely differ *as minted* is asserted against a real session
    row in ``tests/integration/test_csrf_session_token.py`` — here they are both
    fixture constants, so asserting they differ would prove nothing.
    """
    monkeypatch.setattr(ui.service, "list_review_queue", AsyncMock(return_value=[]))

    html = signed_in.client.get("/jd-bank/ui/queue").text

    assert signed_in.session_id not in html, (
        "the session cookie's value was rendered into the page — an httponly cookie "
        "that appears in HTML is no longer httponly in any meaningful sense"
    )


def test_a_rendered_page_carries_this_sessions_token(
    signed_in: SignedIn, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The value in the form must be the live session's token, not a placeholder — the
    end of the loop the refusal tests open."""
    monkeypatch.setattr(ui.service, "list_review_queue", AsyncMock(return_value=[]))

    html = signed_in.client.get("/jd-bank/ui/queue").text

    assert f'name="{CSRF_FIELD}"' in html, (
        "no CSRF field on a rendered page — every form would be refused, which is a "
        "brick, not a control"
    )
    assert signed_in.csrf_token in html


def test_a_page_rendered_without_a_session_still_renders(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Dev/CI (``cas_enabled=False``) has no session and therefore no token. The
    field-rendering helper must degrade to an empty value rather than raise — otherwise
    the whole UI 500s in the posture ``make gates`` runs in."""
    resp = TestClient(app).get("/jd-bank/ui/compose/new")

    assert resp.status_code == 200
    assert f'name="{CSRF_FIELD}"' in resp.text


# ── 5. Every form carries the field (the "define once, call at ~10 sites" risk) ──────


_FORM_OPEN = re.compile(r"<form\b[^>]*>", re.IGNORECASE)
#: ``method=post`` however it is written — quoted either way, or bare. The first version
#: of this matched only the double-quoted spelling, so switching a form to single quotes
#: would have dropped it out of the scan silently.
_METHOD_POST = re.compile(r"""method\s*=\s*['"]?post['"]?""", re.IGNORECASE)


class UnclosedFormError(RuntimeError):
    """A ``<form>`` in a template with no ``</form>``.

    Raised, not tolerated. The first version of this scanner sliced an unclosed form to
    end-of-file, which meant *anything* later in the file satisfied the assertion — and
    that is not hypothetical: ``_csrf.html``'s own doc-comment contained a form tag, so
    this suite reported a green on the very file that defines the macro, for entirely
    the wrong reason. Both ends are closed now: the comment no longer spells out a form
    tag, and an unclosed one is an error rather than a free pass.
    """


def _post_forms(html: str) -> list[str]:
    """Each posting form's source, opening tag to ``</form>``."""
    forms: list[str] = []
    for match in _FORM_OPEN.finditer(html):
        if not _METHOD_POST.search(match.group(0)):
            continue
        end = html.lower().find("</form>", match.end())
        if end == -1:
            raise UnclosedFormError(
                f"a posting form has no </form>: {match.group(0)!r}. Close it — an "
                "unclosed form makes this scan pass on the rest of the file."
            )
        forms.append(html[match.start() : end])
    return forms


@pytest.mark.parametrize(
    "template", sorted(p.name for p in _TEMPLATES_DIR.glob("*.html")), ids=lambda x: x
)
def test_every_post_form_in_every_template_carries_the_csrf_field(
    template: str,
) -> None:
    """A Jinja ``{% block %}`` cannot inject into a child template's form, so "define
    once" means a macro **called at every site**. That is exactly the kind of thing an
    author forgets on form eleven — and the symptom (one broken button) is easy to
    misread as a bug in the route. This scans the template SOURCE, so a form on a page
    no test happens to render is covered too.
    """
    source = (_TEMPLATES_DIR / template).read_text(encoding="utf-8")

    for form in _post_forms(source):
        assert CSRF_FIELD in form, (
            f"a posting form in {template} does not carry the {CSRF_FIELD!r} field, so "
            f"its button will 403. Call the shared macro inside it.\n{form[:300]}"
        )


def test_the_form_scanner_finds_the_forms_it_claims_to() -> None:
    """The scanner is the only thing standing between "ten call sites" and "nine", so
    its own arithmetic is checked: the ten forms are in four templates, and every one of
    them is found. A scanner that silently matched nothing would report every template
    clean."""
    found = {
        path.name: len(_post_forms(path.read_text(encoding="utf-8")))
        for path in _TEMPLATES_DIR.glob("*.html")
    }

    assert {name: n for name, n in found.items() if n} == {
        "_base.html": 1,  # sign out
        "admin_users.html": 2,  # roles, status
        "review_detail.html": 4,  # approve x2, reject, edit
        "compose_new.html": 3,  # export, submit, check
    }, f"the form scan no longer sees the forms this feature covers: {found}"


# ── 6. Reads are untouched ───────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "path",
    ["/jd-bank/ui/queue", "/jd-bank/ui/compose/new"],
    ids=["review-queue", "builder"],
)
def test_a_get_is_never_refused_for_lack_of_a_token(
    path: str, signed_in: SignedIn, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CSRF applies to state changes. Requiring a token on a GET would break every link
    in the app and every bookmark, and protects nothing — a GET must not mutate."""
    monkeypatch.setattr(ui.service, "list_review_queue", AsyncMock(return_value=[]))

    resp = signed_in.client.get(path)

    assert resp.status_code != 403, f"{path} refused an ordinary read"


# ── 7. The second, independent reason the Pydantic-bodied routes are hard to drive ───


def test_a_cross_site_shaped_form_post_cannot_drive_the_json_review_api(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A cross-site HTML form physically cannot express a request the JSON review API
    will accept: the three enctypes a form may use all produce a body FastAPI hands to
    the Pydantic model as raw bytes, which fails validation, and setting
    ``application/json`` requires ``fetch``, which is preflighted (no CORS middleware is
    installed — pinned by :func:`test_no_cors_middleware_is_installed`).

    **This is no longer the reason those routes are unprotected — they ARE protected**
    (the guard is app-wide, and the table above drives all eight with the token in
    ``X-CSRF-Token``). It is kept because the property is still load-bearing twice over:
    it is why the header cannot be forged from another origin, and it is the second,
    independent barrier standing in front of the publish surface. If a future change
    makes these routes accept a form body, this goes red and someone re-derives both
    arguments — which is exactly what should have happened before "a form cannot drive
    a JSON route" was generalised into "JSON routes need no CSRF", the reasoning that
    left ``POST /gates/run`` (query parameters, no body) wide open.
    """
    cas_on()
    signed_in_as(user_holding(Role.REVIEWER))
    approve = AsyncMock(return_value=SimpleNamespace(id=uuid.uuid4()))
    monkeypatch.setattr(jd_bank_routes.service, "approve", approve)

    db = _FakeDb()

    async def _override_session() -> AsyncIterator[_FakeDb]:
        yield db

    app.dependency_overrides[get_session] = _override_session
    try:
        client = TestClient(app, follow_redirects=False, raise_server_exceptions=False)
        resp = client.post(
            f"/jd-bank/review/{uuid.uuid4()}/approve",
            data={"reason": "cross-site"},
        )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code >= 400, (
        f"the JSON review API accepted a form-encoded body ({resp.status_code}) — a "
        "cross-site HTML form can send exactly that, so this surface now needs CSRF "
        "protection of its own and the scope of P0.1b-i is wrong."
    )
    approve.assert_not_awaited()

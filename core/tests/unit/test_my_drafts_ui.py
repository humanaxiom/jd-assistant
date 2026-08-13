""" "My drafts", and the affordance rule the rest of the UI now follows (P0.0).

The first-run experience was: sign in as the default new-user role (``author``), write a
JD in the Builder, press Submit — and get a **raw 403 JSON blob**, because the redirect
target was the reviewer-only review page. The draft *had* saved; nothing said so.

Two things are pinned here, and the second matters more than the first:

* the page exists, shows this author their own drafts, and confirms a submission;
* **no page offers a link its reader may not follow.** That is checked against the
  authorization matrix itself rather than against a hand-written list of "reviewer
  links" — the matrix is the app's access policy, so a link that outruns it fails here
  even if nobody remembers this rule exists.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from src.api.db.models import Role
from src.api.main import app, get_session
from src.api.routes import drafts as drafts_route
from src.api.routes import library as library_route
from src.jd_bank.composer import AuthoredDraft
from src.jd_bank.library import RoleView
from tests.unit.auth_fakes import cas_on, signed_in_ui_as, user_holding
from tests.unit.test_authorization_matrix import EXPECTED_ACCESS, PRIVILEGED
from tests.unit.test_template_links import concrete_path, extract_links

MY_DRAFTS = "/jd-bank/ui/my-drafts"


class FakeSession:
    pass


@pytest.fixture(autouse=True)
def _clear_overrides() -> Iterator[None]:
    yield
    app.dependency_overrides.clear()


def client_as(monkeypatch: pytest.MonkeyPatch, *roles: Role) -> TestClient:
    """A signed-in browser holding exactly ``roles`` — with CAS genuinely on, so a role
    check is real rather than the CAS-off posture's blanket admin."""
    cas_on()
    signed_in_ui_as(monkeypatch, user_holding(*roles, username="author-1"))

    async def _session() -> AsyncIterator[FakeSession]:
        yield FakeSession()

    app.dependency_overrides[get_session] = _session
    return TestClient(app, follow_redirects=False)


def a_draft(**update: object) -> AuthoredDraft:
    base: dict[str, object] = {
        "canonical_id": uuid.uuid4(),
        "cluster_id": uuid.uuid4(),
        "title": "Research Coordinator",
        "status": "draft",
        "version": 1,
        "score": 84.25,
        "grade": "B",
        "created_at": datetime(2026, 8, 12, tzinfo=UTC),
    }
    base.update(update)
    return AuthoredDraft(**base)  # type: ignore[arg-type]


# ── The page ─────────────────────────────────────────────────────────────────────


def test_an_author_sees_the_draft_they_submitted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    draft = a_draft()
    monkeypatch.setattr(
        drafts_route, "list_authored_drafts", AsyncMock(return_value=[draft])
    )

    resp = client_as(monkeypatch, Role.AUTHOR).get(MY_DRAFTS)

    assert resp.status_code == 200
    assert "Research Coordinator" in resp.text
    assert "Waiting for HR review" in resp.text
    assert "84.2" in resp.text


def test_the_listing_is_scoped_to_the_signed_in_user_not_a_parameter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unpublished draft JD content is what P0.1a was about. The filter must be the
    session's identity, so there is nothing in the URL to edit."""
    listing = AsyncMock(return_value=[])
    monkeypatch.setattr(drafts_route, "list_authored_drafts", listing)

    client_as(monkeypatch, Role.AUTHOR).get(f"{MY_DRAFTS}?author_id=someone-else")

    listing.assert_awaited_once()
    assert listing.await_args.kwargs["author_id"] == "author-1"


def test_submitting_shows_a_confirmation_for_the_draft_just_created(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """What the author gets instead of the 403: proof the work saved."""
    draft = a_draft()
    monkeypatch.setattr(
        drafts_route, "list_authored_drafts", AsyncMock(return_value=[draft])
    )

    resp = client_as(monkeypatch, Role.AUTHOR).get(
        f"{MY_DRAFTS}?submitted={draft.canonical_id}"
    )

    assert resp.status_code == 200
    assert "Submitted for review" in resp.text
    assert "just submitted" in resp.text


def test_an_unknown_submitted_id_renders_the_plain_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``submitted`` is display-only: it grants nothing and cannot raise."""
    monkeypatch.setattr(
        drafts_route, "list_authored_drafts", AsyncMock(return_value=[a_draft()])
    )

    resp = client_as(monkeypatch, Role.AUTHOR).get(
        f"{MY_DRAFTS}?submitted={uuid.uuid4()}"
    )

    assert resp.status_code == 200
    assert "just submitted" not in resp.text


def test_an_empty_page_still_leads_somewhere(monkeypatch: pytest.MonkeyPatch) -> None:
    """An empty state that loses every link it had is a dead end wearing a 200."""
    monkeypatch.setattr(
        drafts_route, "list_authored_drafts", AsyncMock(return_value=[])
    )

    resp = client_as(monkeypatch, Role.AUTHOR).get(MY_DRAFTS)

    assert resp.status_code == 200
    assert "/jd-bank/ui/compose/new" in resp.text
    assert "/jd-bank/ui/library" in resp.text


def test_a_rejected_draft_is_not_called_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A rejection archives the row — and so does approving a newer version of the same
    role. The row cannot tell them apart, so the page must not claim to."""
    monkeypatch.setattr(
        drafts_route,
        "list_authored_drafts",
        AsyncMock(return_value=[a_draft(status="archived")]),
    )

    resp = client_as(monkeypatch, Role.AUTHOR).get(MY_DRAFTS)

    assert "Closed" in resp.text
    assert "replaced by a newer version" in resp.text


# ── Affordance: no page offers a door its reader cannot open ─────────────────────


def test_an_author_is_not_offered_a_review_link_on_their_own_drafts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    draft = a_draft()
    monkeypatch.setattr(
        drafts_route, "list_authored_drafts", AsyncMock(return_value=[draft])
    )

    resp = client_as(monkeypatch, Role.AUTHOR).get(MY_DRAFTS)

    assert f"/jd-bank/ui/review/{draft.canonical_id}" not in resp.text
    # …but the draft is still readable by the person who wrote it.
    assert f"/jd-bank/ui/role/{draft.cluster_id}" in resp.text


def test_a_reviewer_is_offered_the_review_link(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The other direction: hiding the link from an author must not hide it from the
    person whose job it is."""
    draft = a_draft()
    monkeypatch.setattr(
        drafts_route, "list_authored_drafts", AsyncMock(return_value=[draft])
    )

    resp = client_as(monkeypatch, Role.REVIEWER).get(MY_DRAFTS)

    assert f"/jd-bank/ui/review/{draft.canonical_id}" in resp.text


def _role_view(cluster_id: uuid.UUID, canonical_id: uuid.UUID) -> RoleView:
    return RoleView(
        cluster_id=cluster_id,
        canonical_id=canonical_id,
        title="Research Coordinator",
        status="draft",
        version=1,
        score=84.2,
        grade="B",
        classification=None,
        source_count=0,
        rendered_text="Coordinates research administration.",
        members=[],
    )


def test_a_role_page_hides_the_review_link_from_an_author(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The same defect one page further in: ``role_detail.html`` rendered "open in the
    review queue" to everybody."""
    cluster_id, canonical_id = uuid.uuid4(), uuid.uuid4()
    monkeypatch.setattr(
        library_route,
        "get_role",
        AsyncMock(return_value=_role_view(cluster_id, canonical_id)),
    )

    resp = client_as(monkeypatch, Role.AUTHOR).get(f"/jd-bank/ui/role/{cluster_id}")

    assert resp.status_code == 200
    assert f"/jd-bank/ui/review/{canonical_id}" not in resp.text
    assert "draft awaiting HR review" in resp.text  # the STATUS still shows


def test_a_role_page_keeps_the_review_link_for_a_reviewer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cluster_id, canonical_id = uuid.uuid4(), uuid.uuid4()
    monkeypatch.setattr(
        library_route,
        "get_role",
        AsyncMock(return_value=_role_view(cluster_id, canonical_id)),
    )

    resp = client_as(monkeypatch, Role.REVIEWER).get(f"/jd-bank/ui/role/{cluster_id}")

    assert f"/jd-bank/ui/review/{canonical_id}" in resp.text


# ── The nav ──────────────────────────────────────────────────────────────────────


def test_the_nav_does_not_offer_an_author_the_review_queue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``author`` is ``default_new_user_role``, so this link was the first thing a new
    user could click — and it answered 403 raw JSON at them."""
    monkeypatch.setattr(
        drafts_route, "list_authored_drafts", AsyncMock(return_value=[])
    )

    body = client_as(monkeypatch, Role.AUTHOR).get(MY_DRAFTS).text

    assert "/jd-bank/ui/queue" not in body
    assert "/jd-bank/ui/admin/users" not in body
    assert "/jd-bank/ui/library" in body  # the links they CAN follow are all there
    assert "/jd-bank/ui/compose/new" in body


@pytest.mark.parametrize(
    ("role", "expected"),
    [(Role.REVIEWER, True), (Role.ADMIN, True), (Role.AUTHOR, False)],
    ids=["reviewer", "admin", "author"],
)
def test_the_review_queue_link_follows_the_role_that_gates_it(
    role: Role, expected: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        drafts_route, "list_authored_drafts", AsyncMock(return_value=[])
    )

    body = client_as(monkeypatch, role).get(MY_DRAFTS).text

    assert ("/jd-bank/ui/queue" in body) is expected


def test_the_admin_link_is_still_admin_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        drafts_route, "list_authored_drafts", AsyncMock(return_value=[])
    )

    body = client_as(monkeypatch, Role.ADMIN).get(MY_DRAFTS).text

    assert "/jd-bank/ui/admin/users" in body


def test_the_login_page_offers_no_menu_at_all() -> None:
    """It rendered the full authenticated nav — five links that all came back here."""
    cas_on()
    client = TestClient(app, follow_redirects=False)

    body = client.get("/jd-bank/ui/login").text

    assert "<nav" not in body, "the login page still renders a menu"
    assert "/jd-bank/ui/compose/new" not in body
    assert "Sign in with SFU CAS" in body


def test_a_signed_out_reader_is_offered_the_one_link_that_helps() -> None:
    """An error page reached with no session still needs a way forward, and there is
    exactly one that works."""
    cas_on()
    client = TestClient(app, follow_redirects=False)

    body = client.get("/no-such-page", headers={"accept": "text/html"}).text

    assert "/jd-bank/ui/login" in body


# ── The rule, checked against the access policy itself ───────────────────────────


def _privileged_matchers() -> list[tuple[str, re.Pattern[str], str]]:
    """Every route the access policy says an ``author`` may not reach, as
    ``(method, path regex, the policy key)``.

    A regex over the matrix's own path templates, rather than asking a matched route
    object for its path: the app's top-level route objects are lazy include-wrappers
    whose ``.path`` is not the effective path, and reading it would silently match
    nothing — the exact failure the matrix's own walk documents.
    """
    matchers = []
    for (method, path), rule in EXPECTED_ACCESS.items():
        if rule.access not in PRIVILEGED:
            continue
        pattern = re.escape(path)
        pattern = re.sub(r"\\\{[^}]+\\\}", "[^/]+", pattern)
        matchers.append((method, re.compile(f"^{pattern}$"), f"{method} {path}"))
    return matchers


def test_no_page_an_author_can_reach_links_to_a_route_they_may_not(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The rule, enforced from the **authorization matrix** rather than from a list of
    reviewer links someone has to maintain: render the pages an ordinary author lands
    on, extract every link the way the crawl does, and refuse any that resolves to a
    route the matrix says they cannot reach.

    This is the check that would have caught the original defect on the day it shipped —
    both the nav's Review queue link and the role page's "open in the review queue".
    """
    monkeypatch.setattr(
        drafts_route, "list_authored_drafts", AsyncMock(return_value=[a_draft()])
    )
    cluster_id, canonical_id = uuid.uuid4(), uuid.uuid4()
    monkeypatch.setattr(
        library_route,
        "get_role",
        AsyncMock(return_value=_role_view(cluster_id, canonical_id)),
    )
    client = client_as(monkeypatch, Role.AUTHOR)
    matchers = _privileged_matchers()
    assert matchers, "no privileged routes found — this test would prove nothing"

    offences: list[str] = []
    for page in (MY_DRAFTS, f"/jd-bank/ui/role/{cluster_id}"):
        body = client.get(page).text
        for link in extract_links(page, body):
            if not link.raw.startswith("/"):
                continue
            path = concrete_path(link.raw)
            for method, pattern, key in matchers:
                if link.method == method and pattern.match(path):
                    offences.append(f"{page} offers {link.raw} -> {key}")

    assert not offences, (
        "an author is shown links they will be refused from:\n  "
        + "\n  ".join(offences)
        + "\nHide the link, or change the gate — a door that opens onto a 403 is the "
        "defect P0.0 exists to remove."
    )

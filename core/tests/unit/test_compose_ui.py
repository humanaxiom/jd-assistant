"""Phase 5.3 — the guided-authoring Builder UI (server-rendered).

Drives ``TestClient(app)`` WITHOUT the lifespan (no DB/Redis touched) — the Builder
UI is read-only and stateless, exactly like the compose JSON route. Pins: the empty
form renders the guided questions; a POST re-renders with the live compliance panel
reflecting the submitted draft; submitted values repopulate; and the author's own
text is HTML-escaped (autoescape on, no ``|safe``).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterator
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from src.api.main import app, get_session
from src.api.routes import compose, compose_ui


def _client() -> TestClient:
    return TestClient(app)  # no `with`: lifespan not entered, no engine/pool


class _FakeSession:
    def __init__(self) -> None:
        self.commit = AsyncMock()


class _FakeChat:
    """Stands in for the whole ``ChatClient`` (as in ``test_composer_assist``): returns
    a FIXED summary and records that it was closed. No network; the client's own
    discipline (retry/egress-guard/JSON repair) is proved in the 4.2 client tests."""

    def __init__(self, summary: str) -> None:
        self._summary = summary
        self.closed = False

    async def chat_json(
        self,
        messages: object,
        model_cls: type,
        *,
        max_tokens: int,
        max_retries: int,
    ) -> object:
        return model_cls(summary=self._summary)

    async def close(self) -> None:
        self.closed = True


@pytest.fixture(autouse=True)
def _clear_overrides() -> Iterator[None]:
    yield
    app.dependency_overrides.clear()


def _client_with_session(session: _FakeSession) -> TestClient:
    async def override() -> AsyncIterator[_FakeSession]:
        yield session

    app.dependency_overrides[get_session] = override
    return TestClient(app)


def test_get_renders_the_guided_form() -> None:
    resp = _client().get("/jd-bank/ui/compose/new")
    assert resp.status_code == 200
    html = resp.text
    # A couple of the guided prompts and their form fields are present.
    assert "overall purpose of this role" in html
    assert 'name="title"' in html
    assert 'name="duties"' in html
    # No compliance panel until the author checks.
    assert "Live compliance" not in html


def test_employee_group_options_come_from_the_rulebook_and_exclude_cupe() -> None:
    """The Builder's employee-group dropdown is rulebook DATA (HR-194), not a hardcoded
    tuple: it must equal ``segmentation.jdfn_employee_groups`` and must NOT offer CUPE —
    there is no CUPE bar for the validator to score against (HR-143). A regression that
    re-hardcodes the list, or slips CUPE in, turns this red."""
    from src.jd_core.rules import get_rules

    served = get_rules().segmentation.jdfn_employee_groups
    assert served == ("apsa", "apex", "poly")
    assert "cupe" not in served

    html = _client().get("/jd-bank/ui/compose/new").text
    for group in served:
        assert f'value="{group}"' in html
    # CUPE must never be an authorable option in the Builder.
    assert 'value="cupe"' not in html


def test_post_shows_the_live_panel_for_an_empty_draft() -> None:
    resp = _client().post("/jd-bank/ui/compose/new", data={"title": "New Role"})
    assert resp.status_code == 200
    html = resp.text
    assert "Live compliance" in html
    assert "not approvable yet" in html
    assert "Still to write" in html  # guidance for the un-authored sections
    assert "Summary: 0 words" in html


def test_post_reflects_the_submitted_summary_and_repopulates() -> None:
    summary = " ".join(["word"] * 40)
    resp = _client().post(
        "/jd-bank/ui/compose/new",
        data={"title": "Software Developer", "position_summary": summary},
    )
    assert resp.status_code == 200
    html = resp.text
    assert "Summary: 40 words" in html
    # The submitted summary is echoed back into the textarea for continued editing.
    assert summary in html


def test_author_text_is_escaped() -> None:
    resp = _client().post(
        "/jd-bank/ui/compose/new",
        data={"title": "<script>alert(1)</script>"},
    )
    assert resp.status_code == 200
    assert "<script>alert(1)</script>" not in resp.text
    assert "&lt;script&gt;" in resp.text


def test_check_offers_a_submit_form_carrying_the_answers() -> None:
    resp = _client().post("/jd-bank/ui/compose/new", data={"title": "New Role"})
    html = resp.text
    assert 'action="/jd-bank/ui/compose/submit"' in html
    assert 'name="answers_json"' in html


def test_submit_persists_and_redirects_to_review(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _FakeSession()
    canonical_id = uuid.uuid4()
    persisted = type("C", (), {"id": canonical_id})()
    submit_mock = AsyncMock(return_value=persisted)
    monkeypatch.setattr(compose_ui, "submit_composed_draft", submit_mock)

    resp = _client_with_session(session).post(
        "/jd-bank/ui/compose/submit",
        data={"answers_json": '{"title": "Role"}', "author_id": "hm-1"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == f"/jd-bank/ui/review/{canonical_id}"
    submit_mock.assert_awaited_once()
    session.commit.assert_awaited_once()


def test_submit_with_malformed_answers_rerenders_and_does_not_commit() -> None:
    session = _FakeSession()
    resp = _client_with_session(session).post(
        "/jd-bank/ui/compose/submit",
        data={"answers_json": "{not json", "author_id": "x"},
        follow_redirects=False,
    )
    assert resp.status_code == 200
    session.commit.assert_not_awaited()


def test_check_offers_an_export_form_carrying_the_answers() -> None:
    """After a compliance check the page offers a download of the official SFU
    ``.docx``, carrying the same ``answers_json`` the submit form uses so the export
    rebuilds the identical draft (no fragile per-field round-trip)."""
    resp = _client().post("/jd-bank/ui/compose/new", data={"title": "New Role"})
    html = resp.text
    assert 'action="/jd-bank/ui/compose/export"' in html
    # It is its own form (a GET/POST to export, not the submit-for-review form).
    assert html.count('name="answers_json"') >= 2


def test_export_returns_the_official_docx_download() -> None:
    """The UI export wrapper rebuilds the draft from ``answers_json`` and streams the
    official SFU ``.docx`` — no python-multipart, no JSON body (the form is urlencoded),
    nothing persisted (NN #1)."""
    resp = _client().post(
        "/jd-bank/ui/compose/export",
        data={"answers_json": '{"title": "Financial Analyst"}'},
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"] == (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    assert "financial-analyst.docx" in resp.headers["content-disposition"]
    assert resp.content[:2] == b"PK"  # a .docx is a zip archive


def test_export_with_malformed_answers_rerenders_and_does_not_500() -> None:
    """A tampered hidden field must not crash — re-render the form with the error,
    exactly as the submit path does (the field is produced by our own check step)."""
    resp = _client().post(
        "/jd-bank/ui/compose/export",
        data={"answers_json": "{not json"},
    )
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert resp.content[:2] != b"PK"


# ── 5.8b — the LLM summary-assist button ─────────────────────────────────────


def test_the_guided_form_offers_the_assist_button() -> None:
    """The guided form has a second submit that routes to the assist endpoint (a
    ``formaction`` override), so the author can ask the LLM to improve the summary
    from the same in-progress answers."""
    html = _client().get("/jd-bank/ui/compose/new").text
    assert 'formaction="/jd-bank/ui/compose/assist"' in html


def test_assist_prefills_the_suggested_summary_and_shows_the_panel() -> None:
    """The assist route asks the (faked) LLM for a better Position Summary, applies it
    to the summary textarea for the author to review, shows the assist panel (word
    count + grounding), and re-scores via the validator (validator-as-oracle, NN #3).
    The injected client is always closed."""
    suggested = "Leads the modernization of finance systems across the university."
    fake = _FakeChat(suggested)
    app.dependency_overrides[compose.get_chat_client] = lambda: fake

    resp = _client().post(
        "/jd-bank/ui/compose/assist",
        data={"title": "Financial Analyst", "position_summary": "Too short."},
    )
    assert resp.status_code == 200
    html = resp.text
    # The suggestion is applied to the summary textarea for review (not auto-published).
    assert suggested in html
    # An assist panel is shown, distinct from the plain live-compliance panel.
    assert "Summary assist" in html
    assert "grounded" in html.lower()
    # The client the route built was closed (no leak).
    assert fake.closed is True


def test_assist_carries_the_applied_summary_into_submit_and_export() -> None:
    """After accepting the assist, the hidden ``answers_json`` reflects the applied
    summary so the submit/export forms rebuild the identical (improved) draft."""
    suggested = "Directs enterprise financial planning and reporting for the campus."
    app.dependency_overrides[compose.get_chat_client] = lambda: _FakeChat(suggested)
    resp = _client().post(
        "/jd-bank/ui/compose/assist",
        data={"title": "Financial Analyst", "position_summary": "Too short."},
    )
    assert resp.status_code == 200
    # answers_json (hidden field feeding submit + export) carries the suggested summary.
    assert 'action="/jd-bank/ui/compose/submit"' in resp.text
    assert suggested in resp.text


def test_assist_with_invalid_answers_rerenders_and_closes_client() -> None:
    """A field that fails validation (title > 200 chars) must re-render with the error
    and still close the injected client — never 500, never leak, never call the LLM
    against a draft that could not assemble."""
    fake = _FakeChat("unused")
    app.dependency_overrides[compose.get_chat_client] = lambda: fake
    resp = _client().post(
        "/jd-bank/ui/compose/assist",
        data={"title": "x" * 201},
    )
    assert resp.status_code == 200
    assert "Summary assist" not in resp.text
    assert fake.closed is True

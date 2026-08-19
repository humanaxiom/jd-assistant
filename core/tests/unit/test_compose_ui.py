"""Phase 5.3 — the guided-authoring Builder UI (server-rendered).

Drives ``TestClient(app)`` WITHOUT the lifespan (no DB/Redis touched) — the Builder
UI is read-only and stateless, exactly like the compose JSON route. Pins: the empty
form renders the guided questions; a POST re-renders with the live compliance panel
reflecting the submitted draft; submitted values repopulate; and the author's own
text is HTML-escaped (autoescape on, no ``|safe``).
"""

from __future__ import annotations

import asyncio
import html as html_lib
import json
import re
import uuid
from collections.abc import AsyncIterator, Iterator
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from src.api.main import app, get_session
from src.api.routes import compose, compose_ui
from src.jd_bank.composer import DuplicateGuard, RelatedRole
from src.jd_bank.embeddings import client as embed_client_mod
from src.jd_core.rules import get_rules
from tests.unit.retuned_rules import (
    retuned_dedup,
    retuned_embeddings,
    retuned_rewrite,
)
from tests.unit.template_scan import action_of, post_forms


def _post_form(
    client: TestClient,
    url: str,
    pairs: list[tuple[str, str]],
    *,
    follow_redirects: bool = True,
):
    """POST an ``application/x-www-form-urlencoded`` body built from ORDERED pairs
    (so repeated keys like the structured ``duties_statement`` columns survive) — this
    httpx version does not accept a list-of-tuples via ``data=``."""
    from urllib.parse import urlencode

    return client.post(
        url,
        content=urlencode(pairs),
        headers={"content-type": "application/x-www-form-urlencoded"},
        follow_redirects=follow_redirects,
    )


def _answers_json_from(html_text: str) -> str:
    """Pull the hidden ``answers_json`` field out of a rendered Builder page and
    HTML-unescape it, so a test can rebuild the exact ``ComposerAnswers`` the
    submit/export forms would (the authoritative round-trip carrier)."""
    match = re.search(r'name="answers_json" value="([^"]*)"', html_text)
    assert match is not None, "no answers_json hidden field on the page"
    return html_lib.unescape(match.group(1))


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


@pytest.fixture(autouse=True)
def _default_related_roles_deps() -> None:
    """Phase 5.9: ``check_draft`` (POST /new) now also runs the near-duplicate
    authoring guard, which needs a DB session + embed client + Neo4j driver. Wired
    here, AUTOUSE, for every test in this file — the same way ``_clear_overrides``
    already resets ``app.dependency_overrides`` after each test — so a plumbing
    change to an existing route (a new ``Depends``) does not break the ~20 existing
    tests in this file that only ever cared about the live-compliance panel and
    never touched a session/embed/Neo4j fake. Any test that cares about the guard
    itself overrides these again (last-write-wins) or monkeypatches
    ``compose_ui.find_related_roles`` directly."""

    async def override_session() -> AsyncIterator[object]:
        yield object()

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[compose.get_embed_client] = lambda: _FakeClose()
    app.dependency_overrides[compose.get_neo4j_driver] = lambda: _FakeClose()
    # `check_draft` takes the OPTIONAL factories (a client that cannot be constructed
    # must not 500 the compliance panel — see `get_optional_embed_client`), so those
    # are the hooks it actually resolves. Both pairs are wired: `/search` still uses
    # the strict ones. A test that wants the real degrade path pops these two.
    app.dependency_overrides[compose.get_optional_embed_client] = lambda: _FakeClose()
    app.dependency_overrides[compose.get_optional_neo4j_driver] = lambda: _FakeClose()


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
    # Duties are now a structured row (verb / statement / %), not a bare textarea.
    assert 'name="duties_statement"' in html
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


def test_inclusive_language_meter_flags_a_coded_term() -> None:
    """The live panel surfaces coded/gendered language in a prominent 'Inclusive
    language' meter (pulled out of the generic Fix-these list), with the count."""
    summary = "The chairman leads the team. " + " ".join(["word"] * 40)
    html = (
        _client()
        .post(
            "/jd-bank/ui/compose/new",
            data={"title": "Analyst", "position_summary": summary},
        )
        .text
    )
    assert "Inclusive language" in html
    assert "1 flagged" in html  # exactly the one coded term ("chairman")


def test_inclusive_language_meter_is_clear_when_no_coded_terms() -> None:
    summary = " ".join(["collaborates"] * 40)
    html = (
        _client()
        .post(
            "/jd-bank/ui/compose/new",
            data={"title": "Analyst", "position_summary": summary},
        )
        .text
    )
    assert "Inclusive language" in html
    assert "clear" in html


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


def test_section_table_explains_why_a_section_needs_attention() -> None:
    """A flagged section must say WHAT to fix, not just badge the raw enum
    'needs_attention'. The per-section issues render in the Sections table, and the
    enum is shown as a human label."""
    summary = " ".join(["word"] * 40)  # authored but below the 100-word floor
    html = (
        _client()
        .post(
            "/jd-bank/ui/compose/new",
            data={"title": "Analyst", "position_summary": summary},
        )
        .text
    )
    # Human label in the table, not the snake_case enum.
    assert "Needs attention" in html
    assert "needs_attention" not in html
    # The specific reason renders WITHIN the Sections table (which follows the
    # "Sections" heading) — not only in the global "Fix these" list above it.
    sections_block = html.split("<h3>Sections</h3>", 1)[1]
    assert "the template asks for" in sections_block


def _approvable_assessment_with_a_low_finding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Patch the Builder's assessment to the reported state: a draft the gates PERMIT
    ("ready for review") that still carries an advisory ``low`` finding.

    Reproduces cloning an approved harmonized role — the clone of the published "AV
    Systems Analyst" scores 89.05/B/ready-for-review with three ``[low]`` nits, and the
    panel headed them "Fix these" and painted the section red, which reads as a broken
    clone. Patched rather than form-built so the test pins the PRESENTATION rule (the
    thing being changed) and not the rulebook's severity assignments.
    """
    from src.jd_bank.composer.validate import assess_draft as real_assess

    def _approvable(*args: object, **kwargs: object) -> object:
        assessment = real_assess(*args, **kwargs)  # type: ignore[arg-type]
        low_only = [
            issue for issue in assessment.report.issues if issue.severity == "low"
        ]
        report = assessment.report.model_copy(
            update={
                "issues": low_only,
                "gate_decision": assessment.report.gate_decision.model_copy(
                    update={"approved": True, "blocking": []}
                ),
            }
        )
        sections = tuple(
            (
                section.model_copy(
                    update={
                        "state": "needs_attention" if section.issues else section.state,
                        "issues": tuple(
                            i for i in section.issues if i.severity == "low"
                        ),
                    }
                )
                if any(i.severity == "low" for i in section.issues)
                else section.model_copy(update={"state": "ok", "issues": ()})
            )
            for section in assessment.sections
        )
        return assessment.model_copy(
            update={
                "report": report,
                "sections": sections,
                "guidance": (),
                "findings": tuple(low_only),
                "approvable": True,
            }
        )

    monkeypatch.setattr(compose_ui, "assess_draft", _approvable)


def test_an_approvable_draft_frames_findings_as_suggestions_not_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A draft the gates already PERMIT must not be shouted at.

    "Fix these" plus a red badge on a draft the same panel calls "ready for review" is
    a contradiction, and it is how a perfectly good clone of an approved role reads as
    broken. When nothing blocks, the remaining findings are advisory by definition."""
    _approvable_assessment_with_a_low_finding(monkeypatch)
    summary = " ".join(["word"] * 40)
    html = (
        _client()
        .post(
            "/jd-bank/ui/compose/new",
            data={"title": "AV Systems Analyst", "position_summary": summary},
        )
        .text
    )

    assert "ready for review" in html
    assert "Fix these" not in html
    assert "Suggested improvements" in html
    assert "do not block review" in html
    # The section flag is advisory, not the red "blocked" badge.
    assert "Suggestion" in html
    assert "badge blocked" not in html


def test_a_blocked_draft_still_says_fix_these(monkeypatch: pytest.MonkeyPatch) -> None:
    """Blast-radius guard: when a gate really does block, the panel keeps the
    imperative and the red badge. Softening THAT would be the actual bug."""
    summary = " ".join(["word"] * 40)  # a bare draft: no duties, no qualifications
    html = (
        _client()
        .post(
            "/jd-bank/ui/compose/new",
            data={"title": "Analyst", "position_summary": summary},
        )
        .text
    )

    assert "not approvable yet" in html
    assert "Fix these" in html
    assert "Suggested improvements" not in html


def test_section_rows_link_down_to_their_form_fields() -> None:
    """Each section in the panel links to its fields in the form (anchor jump), so an
    author can go straight from a flagged section to where they fix it."""
    html = _client().post("/jd-bank/ui/compose/new", data={"title": "Analyst"}).text
    # The form heading carries the anchor target...
    assert 'id="section-position_summary"' in html
    # ...and the Sections panel links to it.
    assert 'href="#section-position_summary"' in html


def test_fix_these_and_still_to_write_items_link_to_their_section() -> None:
    """The top 'Fix these' / 'Still to write' findings each link to the section they
    belong to — even though the finding objects don't carry a section, the panel
    recovers it from the section grouping."""
    summary = " ".join(["word"] * 40)  # authored-but-short -> a 'Fix these' finding
    html = (
        _client()
        .post(
            "/jd-bank/ui/compose/new",
            data={"title": "Analyst", "position_summary": summary},
        )
        .text
    )
    # The 'Fix these' block (between its heading and the Sections table) links the
    # too-short-summary finding to the Position Summary fields.
    fix_block = html.split("Fix these", 1)[1].split("<h3>Sections</h3>", 1)[0]
    assert 'href="#section-position_summary"' in fix_block
    # The 'Still to write' block (unauthored sections) links its items too.
    still_block = html.split("Still to write", 1)[1].split("Fix these", 1)[0]
    assert 'href="#section-' in still_block


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


def test_submit_persists_and_lands_the_author_on_their_own_drafts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The destination is the fix, not a preference (P0.0).

    This used to redirect to ``/jd-bank/ui/review/{id}`` — reviewer-or-admin only —
    while ``default_new_user_role`` is ``author``. So the ordinary case was: the draft
    commits, and the person who wrote it is bounced onto a raw 403 with no sign that
    their work saved. ``/my-drafts`` is reachable by whoever just submitted, by
    construction, and carries the new id so the page can confirm it.
    """
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
    assert resp.headers["location"] == f"/jd-bank/ui/my-drafts?submitted={canonical_id}"
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


# ── Structured per-field editors — duty verb/% and KSA modifiers ─────────────
#
# The guided form used to collect duties and knowledge/skills as one-item-per-line
# textareas, silently dropping the fields the models already carry: a duty's
# ``action_verb`` (what the action-verb gate checks) and ``allocation`` (the ``(NN%)``
# the allocation gate reads), and a knowledge/skill ``modifier`` (the Toolkit
# proficiency scale). These pin that the structured rows now CAPTURE those fields,
# round-trip them through the answers the submit/export forms rebuild from, and
# repopulate them on re-render / clone. Modifier vocab is rulebook DATA (NN #2).


def test_get_renders_structured_duty_and_ksa_rows() -> None:
    """⚠ The duty columns are named for their TARGET (``duties_*``), not with a fixed
    ``duty_*`` prefix — changed in Phase E, and not cosmetically. The WJQ form has TWO
    duty-shaped sections (major and minor functions), so a fixed prefix would post both
    into one column and lose which is which. Knowledge/skills were already keyed this
    way; duties now match them."""
    html = _client().get("/jd-bank/ui/compose/new").text
    # A duty row exposes its verb, statement, and %-allocation as separate controls.
    assert 'name="duties_verb"' in html
    assert 'name="duties_statement"' in html
    assert 'name="duties_allocation"' in html
    # Knowledge/skills rows expose the qualification text and its proficiency modifier.
    assert 'name="knowledge_text"' in html
    assert 'name="knowledge_modifier"' in html
    assert 'name="skills_text"' in html
    assert 'name="skills_modifier"' in html


def test_post_captures_structured_duty_verb_and_allocation() -> None:
    resp = _post_form(
        _client(),
        "/jd-bank/ui/compose/new",
        [
            ("title", "Analyst"),
            ("duties_verb", "Manages"),
            ("duties_statement", "Manages the general ledger"),
            ("duties_allocation", "60"),
        ],
    )
    assert resp.status_code == 200
    html = resp.text
    answers = compose_ui.ComposerAnswers.model_validate_json(_answers_json_from(html))
    assert len(answers.duties) == 1
    assert answers.duties[0].action_verb == "Manages"
    assert answers.duties[0].statement == "Manages the general ledger"
    assert answers.duties[0].allocation == 60
    # Repopulated into the row for continued editing.
    assert 'value="Manages"' in html
    assert 'value="60"' in html


def test_post_aligns_multiple_duty_rows_and_drops_blank_rows() -> None:
    """Parallel duty columns stay index-aligned (verb[i]/statement[i]/allocation[i]),
    a row with no statement is dropped, and a blank verb is a real empty verb — not a
    misalignment that shifts allocations onto the wrong duty."""
    resp = _post_form(
        _client(),
        "/jd-bank/ui/compose/new",
        [
            ("title", "Analyst"),
            ("duties_verb", "Manages"),
            ("duties_statement", "Manages the general ledger"),
            ("duties_allocation", "60"),
            ("duties_verb", ""),
            ("duties_statement", "Prepares monthly reports"),
            ("duties_allocation", "40"),
            ("duties_verb", ""),
            ("duties_statement", ""),
            ("duties_allocation", ""),
        ],
    )
    answers = compose_ui.ComposerAnswers.model_validate_json(
        _answers_json_from(resp.text)
    )
    assert [d.statement for d in answers.duties] == [
        "Manages the general ledger",
        "Prepares monthly reports",
    ]
    assert [d.allocation for d in answers.duties] == [60, 40]
    assert answers.duties[1].action_verb == ""


def test_post_captures_knowledge_and_skill_modifiers() -> None:
    resp = _post_form(
        _client(),
        "/jd-bank/ui/compose/new",
        [
            ("title", "Analyst"),
            ("knowledge_text", "Knowledge of GAAP"),
            ("knowledge_modifier", "excellent"),
            ("skills_text", "Financial modelling in Excel"),
            ("skills_modifier", "advanced"),
        ],
    )
    assert resp.status_code == 200
    html = resp.text
    answers = compose_ui.ComposerAnswers.model_validate_json(_answers_json_from(html))
    assert answers.knowledge[0].text == "Knowledge of GAAP"
    assert answers.knowledge[0].modifier == "excellent"
    assert answers.skills[0].text == "Financial modelling in Excel"
    assert answers.skills[0].modifier == "advanced"
    # The chosen modifier is selected in the dropdown on re-render.
    assert '<option value="excellent" selected' in html
    assert '<option value="advanced" selected' in html


def test_a_blank_modifier_means_no_modifier() -> None:
    """An unset modifier dropdown maps to ``modifier=None`` (the qualification carries
    no proficiency), never the empty-string that would fail the vocabulary check."""
    resp = _post_form(
        _client(),
        "/jd-bank/ui/compose/new",
        [
            ("title", "Analyst"),
            ("knowledge_text", "Knowledge of university finance policy"),
            ("knowledge_modifier", ""),
        ],
    )
    answers = compose_ui.ComposerAnswers.model_validate_json(
        _answers_json_from(resp.text)
    )
    assert answers.knowledge[0].modifier is None


def test_ksa_modifier_options_come_from_the_rulebook() -> None:
    """The proficiency dropdowns are rulebook DATA (qualifications.yaml Parts 5.1/5.2),
    not a hardcoded list: every rulebook modifier (bar the ``none`` sentinel, which is
    the blank default) is offered, and no extra option is invented."""
    from src.jd_core.rules import get_rules

    quals = get_rules().qualifications
    html = _client().get("/jd-bank/ui/compose/new").text
    for modifier in quals.knowledge_modifiers | quals.skill_modifiers:
        if modifier == "none":
            continue
        assert f'value="{modifier}"' in html


def test_clone_repopulates_structured_duty_and_ksa_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cloning repopulates the structured rows — verb, %-allocation and modifier — not
    just the free-text statement, so nothing the source carried is lost in the form."""
    from src.jd_bank.composer import ComposerAnswers, DutyAnswer, ModifiedQual

    answers = ComposerAnswers(
        title="Cloned Analyst",
        position_summary=" ".join(["word"] * 120),
        duties=[
            DutyAnswer(action_verb="Leads", statement="Leads the team", allocation=70)
        ],
        knowledge=[ModifiedQual(text="Knowledge of GAAP", modifier="excellent")],
        skills=[ModifiedQual(text="Excel modelling", modifier="advanced")],
    )

    async def fake_load(session: object, sid: object) -> ComposerAnswers:
        return answers

    monkeypatch.setattr(compose_ui, "load_clone_answers", fake_load)
    _override_session_object()

    html = _client().get(f"/jd-bank/ui/compose/clone/{uuid.uuid4()}").text
    assert 'value="Leads"' in html
    assert 'value="Leads the team"' in html
    assert 'value="70"' in html
    assert '<option value="excellent" selected' in html
    assert '<option value="advanced" selected' in html


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


# ── 5.8c — search + clone (start from an existing JD) ─────────────────────────


class _FakeClose:
    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


def _override_session_object() -> None:
    async def override() -> AsyncIterator[object]:
        yield object()

    app.dependency_overrides[get_session] = override


def test_the_builder_offers_a_search_box() -> None:
    """The Builder links to semantic search so an author can start from an existing
    JD instead of a blank form (5.4 wired in)."""
    html = _client().get("/jd-bank/ui/compose/new").text
    assert 'action="/jd-bank/ui/compose/search"' in html
    assert 'name="q"' in html


def test_search_renders_hits_with_clone_links(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The UI search route transports the (faked) hits into a results page, each
    linking to the clone route, and closes the embed + Neo4j clients it built."""
    from src.jd_bank.composer import SearchHit

    hit = SearchHit(
        source_document_id=uuid.uuid4(),
        title="Financial Analyst",
        employee_group="apsa",
        score=0.91,
    )

    async def fake_search(query: str, **kwargs: object) -> list[SearchHit]:
        return [hit]

    async def no_cluster(session: object, sid: object) -> None:
        return (
            None  # a singleton — no harmonized role, so raw-JD clone is the only link
        )

    monkeypatch.setattr(compose_ui, "search_similar_jds", fake_search)
    monkeypatch.setattr(compose_ui, "cluster_id_for_source", no_cluster)
    embed, neo = _FakeClose(), _FakeClose()
    app.dependency_overrides[compose.get_embed_client] = lambda: embed
    app.dependency_overrides[compose.get_neo4j_driver] = lambda: neo
    _override_session_object()

    resp = _client().get("/jd-bank/ui/compose/search?q=analyst")
    assert resp.status_code == 200
    html = resp.text
    assert "Financial Analyst" in html
    assert f"/jd-bank/ui/compose/clone/{hit.source_document_id}" in html
    assert embed.closed is True
    assert neo.closed is True


def test_search_prefers_the_harmonized_role_clone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When a hit's source belongs to a harmonized role, "Start from this" clones the
    role's canonical (``clone-role/{cluster_id}``), NOT the raw archive JD — the archive
    is transitional, so a new JD starts from the reviewed harmonized version."""
    from src.jd_bank.composer import SearchHit

    hit = SearchHit(
        source_document_id=uuid.uuid4(),
        title="Financial Analyst",
        employee_group="apsa",
        score=0.91,
    )
    cluster_id = uuid.uuid4()

    async def fake_search(query: str, **kwargs: object) -> list[SearchHit]:
        return [hit]

    async def has_cluster(session: object, sid: object) -> uuid.UUID:
        return cluster_id

    monkeypatch.setattr(compose_ui, "search_similar_jds", fake_search)
    monkeypatch.setattr(compose_ui, "cluster_id_for_source", has_cluster)
    app.dependency_overrides[compose.get_embed_client] = lambda: _FakeClose()
    app.dependency_overrides[compose.get_neo4j_driver] = lambda: _FakeClose()
    _override_session_object()

    html = _client().get("/jd-bank/ui/compose/search?q=analyst").text
    assert f"/jd-bank/ui/compose/clone-role/{cluster_id}" in html
    # and NOT the raw-source clone for a doc that has a harmonized role
    assert f"/jd-bank/ui/compose/clone/{hit.source_document_id}" not in html


def test_search_without_a_query_prompts_and_does_not_search(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An empty query shows the search page without calling the embed/vector stack —
    no wasted round-trip, no crash."""
    called = False

    async def fake_search(query: str, **kwargs: object) -> list[object]:
        nonlocal called
        called = True
        return []

    monkeypatch.setattr(compose_ui, "search_similar_jds", fake_search)
    app.dependency_overrides[compose.get_embed_client] = lambda: _FakeClose()
    app.dependency_overrides[compose.get_neo4j_driver] = lambda: _FakeClose()
    _override_session_object()

    resp = _client().get("/jd-bank/ui/compose/search?q=")
    assert resp.status_code == 200
    assert called is False


def test_clone_prefills_the_guided_form(monkeypatch: pytest.MonkeyPatch) -> None:
    """Cloning an existing JD pre-fills the guided form (title + duties visible) and
    lands the author on a scored, ready-to-edit draft."""
    from src.jd_bank.composer import ComposerAnswers, DutyAnswer

    # A source that PREDATES the boilerplate (include_sfu_boilerplate=False) — like most
    # archive JDs — must still clone with boilerplate ON, since cloning starts a new
    # compliant JD (otherwise About-SFU/territorial/EE land "missing" on arrival).
    answers = ComposerAnswers(
        title="Cloned Analyst",
        position_summary=" ".join(["word"] * 120),
        duties=[DutyAnswer(statement="Manage the general ledger")],
        include_sfu_boilerplate=False,
    )

    async def fake_load(session: object, sid: object) -> ComposerAnswers:
        return answers

    monkeypatch.setattr(compose_ui, "load_clone_answers", fake_load)
    _override_session_object()

    resp = _client().get(f"/jd-bank/ui/compose/clone/{uuid.uuid4()}")
    assert resp.status_code == 200
    html = resp.text
    assert "Cloned Analyst" in html  # title prefilled into the form
    assert "Manage the general ledger" in html  # duty prefilled
    assert 'action="/jd-bank/ui/compose/new"' in html  # it IS the guided form
    # Boilerplate defaulted ON despite the source lacking it: the checkbox is checked
    # and the About-SFU/territorial "missing" guidance is absent.
    assert "checkbox" in html and "checked" in html
    assert "'About SFU' boilerplate is missing" not in html


def test_clone_404_when_no_parsed_jd(monkeypatch: pytest.MonkeyPatch) -> None:
    """A source document with no parsed JD to clone returns 404, not 500."""

    async def fake_load(session: object, sid: object) -> None:
        return None

    monkeypatch.setattr(compose_ui, "load_clone_answers", fake_load)
    _override_session_object()

    resp = _client().get(f"/jd-bank/ui/compose/clone/{uuid.uuid4()}")
    assert resp.status_code == 404


def test_clone_role_prefills_from_the_harmonized_canonical(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cloning a ROLE pre-fills the Builder from its harmonized canonical (the reviewed
    version), lands on the guided form, and defaults boilerplate ON.

    It also CARRIES THE LINEAGE into the form as a hidden field: without that, the
    author's first Check forgets which role they cloned and the guard warns them they
    duplicated it — the exact thing ``exclude_cluster_id`` exists to prevent."""
    from src.jd_bank.composer import ComposerAnswers, DutyAnswer

    cluster_id = uuid.uuid4()
    answers = ComposerAnswers(
        title="Harmonized Analyst",
        position_summary=" ".join(["word"] * 120),
        duties=[DutyAnswer(statement="Own the quarterly forecast")],
        include_sfu_boilerplate=True,
        cloned_from_cluster_id=cluster_id,
    )

    async def fake_role_load(session: object, cluster_id: object) -> ComposerAnswers:
        return answers

    monkeypatch.setattr(compose_ui, "load_role_clone_answers", fake_role_load)
    _override_session_object()

    resp = _client().get(f"/jd-bank/ui/compose/clone-role/{cluster_id}")
    assert resp.status_code == 200
    html = resp.text
    assert "Harmonized Analyst" in html
    assert "Own the quarterly forecast" in html
    assert 'action="/jd-bank/ui/compose/new"' in html
    assert (
        f'name="cloned_from_cluster_id" value="{cluster_id}"' in html
    ), "the clone page must carry its lineage into the form"


def test_clone_role_404_when_cluster_has_no_canonical(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A cluster with no harmonized canonical returns 404, not 500."""

    async def fake_role_load(session: object, cluster_id: object) -> None:
        return None

    monkeypatch.setattr(compose_ui, "load_role_clone_answers", fake_role_load)
    _override_session_object()

    resp = _client().get(f"/jd-bank/ui/compose/clone-role/{uuid.uuid4()}")
    assert resp.status_code == 404


# ── 5.9 — the near-duplicate authoring guard ──────────────────────────────────
#
# ``check_draft`` (POST /new) now also runs ``find_related_roles`` (Phase 5.9) to
# show a RANKED, SCORE-FREE list of harmonized roles that look like the draft, so an
# author clones one instead of authoring SFU's 10th "Academic Advisor" (NN #1:
# advisory only — it never blocks submission). See ``test_composer_duplicates.py``
# for the function's own behaviour; these pin the UI WIRING: the panel renders, links
# to the right routes, never a percentage, and survives the guard blowing up.


def _related_guard(
    *,
    title_collisions: tuple[RelatedRole, ...] = (),
    related: tuple[RelatedRole, ...] = (),
    same_title_count: int = 0,
    departments: tuple[str, ...] = (),
) -> DuplicateGuard:
    return DuplicateGuard(
        checked=True,
        title_collisions=list(title_collisions),
        related=list(related),
        same_title_count=same_title_count,
        departments=list(departments),
    )


def _override_related_roles_guard_deps() -> None:
    """The guard's own deps — a session plus closable embed/Neo4j fakes, exactly
    like the search+clone deps above (kept separate on purpose: those tests assert
    on THEIR OWN fakes being closed, and reusing the same names would blur that)."""
    _override_session_object()
    app.dependency_overrides[compose.get_embed_client] = lambda: _FakeClose()
    app.dependency_overrides[compose.get_neo4j_driver] = lambda: _FakeClose()
    app.dependency_overrides[compose.get_optional_embed_client] = lambda: _FakeClose()
    app.dependency_overrides[compose.get_optional_neo4j_driver] = lambda: _FakeClose()


def test_check_renders_the_related_roles_panel_with_working_links(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each row — title-collision or semantic-related — links to the role's own
    library page AND to the route that clones it, so an author can go straight from
    "this looks like a duplicate" to "start from that one instead"."""
    collision_id, related_id = uuid.uuid4(), uuid.uuid4()
    guard = _related_guard(
        title_collisions=(
            RelatedRole(
                cluster_id=collision_id,
                title="Academic Advisor",
                department="Student Advising",
                status="published",
                reason="title_collision",
            ),
        ),
        related=(
            RelatedRole(
                cluster_id=related_id,
                title="Advising Coordinator",
                department="Faculty of Science",
                status="published",
                reason="related",
            ),
        ),
        same_title_count=1,
        departments=("Student Advising",),
    )

    async def fake_find_related(*args: object, **kwargs: object) -> DuplicateGuard:
        return guard

    monkeypatch.setattr(compose_ui, "find_related_roles", fake_find_related)
    _override_related_roles_guard_deps()

    resp = _client().post(
        "/jd-bank/ui/compose/new",
        data={
            "title": "Academic Advisor",
            "position_summary": " ".join(["word"] * 120),
        },
    )
    assert resp.status_code == 200
    html = resp.text
    for cluster_id in (collision_id, related_id):
        assert f"/jd-bank/ui/role/{cluster_id}" in html
        assert f"/jd-bank/ui/compose/clone-role/{cluster_id}" in html


def _related_roles_panel_html(html: str) -> str:
    """The WHOLE rendered panel, heading to closing tag.

    Scoped to the panel rather than the page because the page legitimately carries a
    ``%`` elsewhere (``width:100%`` in the base stylesheet), and scoped to the whole
    panel rather than a window around one row because a window is not a check: at the
    shipped ``max_matches`` of 5 the panel runs to ~2,700 characters and row 5's link
    sits ~1,500 characters from row 1, so a ±400 window covers under a third of it and
    a "94% similar" badge on rows 2-5, in the closing note, or in the same-title
    sentence would sail straight through."""
    start = html.index("Roles SFU already has")
    end = html.index("</div>", html.index("</ul>", start))
    return html[start:end]


def test_related_roles_panel_shows_no_percentage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """NO similarity number, anywhere in the panel — the measured finding this whole
    feature is shaped around (an unrelated role out-scores a genuine twin, so any
    figure would look precise and mean nothing). Rendered with MULTIPLE rows and both
    kinds of row, so the assertion covers every part of the panel a number could be
    added to."""
    collision_id, related_ids = uuid.uuid4(), [uuid.uuid4() for _ in range(3)]
    guard = _related_guard(
        title_collisions=(
            RelatedRole(
                cluster_id=collision_id,
                title="Advising Coordinator",
                department="Student Advising",
                status="published",
                reason="title_collision",
            ),
        ),
        related=tuple(
            RelatedRole(
                cluster_id=cluster_id,
                title=f"Advising Coordinator {i}",
                department="Faculty of Science",
                status="draft",
                reason="related",
            )
            for i, cluster_id in enumerate(related_ids)
        ),
        same_title_count=1,
        departments=("Student Advising",),
    )

    async def fake_find_related(*args: object, **kwargs: object) -> DuplicateGuard:
        return guard

    monkeypatch.setattr(compose_ui, "find_related_roles", fake_find_related)
    _override_related_roles_guard_deps()

    resp = _post_form(
        _client(),
        "/jd-bank/ui/compose/new",
        [
            ("title", "Advising Coordinator"),
            ("position_summary", " ".join(["word"] * 120)),
            ("duties_verb", "Manages"),
            ("duties_statement", "Manages a caseload of first-year students"),
            ("duties_allocation", "60"),
        ],
    )
    assert resp.status_code == 200
    html = resp.text
    panel = _related_roles_panel_html(html)

    # Every row really is inside the slice being checked (otherwise the assertion
    # below could pass by covering nothing).
    for cluster_id in [collision_id, *related_ids]:
        assert f"/jd-bank/ui/role/{cluster_id}" in panel
    assert "%" not in panel


def test_title_collision_sentence_states_the_real_counts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Three roles already carry this exact title, across two distinct departments
    — the sentence must state THOSE two numbers, not placeholders, and the two
    numbers must not be interchangeable (picked deliberately unequal)."""
    collisions = tuple(
        RelatedRole(
            cluster_id=uuid.uuid4(),
            title="Academic Advisor",
            department=dept,
            status="published",
            reason="title_collision",
        )
        for dept in ("Student Advising", "Faculty of Science", "Student Advising")
    )
    guard = _related_guard(
        title_collisions=collisions,
        same_title_count=3,
        departments=("Student Advising", "Faculty of Science"),
    )

    async def fake_find_related(*args: object, **kwargs: object) -> DuplicateGuard:
        return guard

    monkeypatch.setattr(compose_ui, "find_related_roles", fake_find_related)
    _override_related_roles_guard_deps()

    html = (
        _client()
        .post(
            "/jd-bank/ui/compose/new",
            data={
                "title": "Academic Advisor",
                "position_summary": " ".join(["word"] * 120),
            },
        )
        .text
    )
    assert "3 existing role" in html  # same_title_count
    assert "2 department" in html  # len(departments) — distinct, not 3


def test_check_survives_a_raising_duplicate_guard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The Builder must never lose the score/grade/blocking-gates panel it exists
    for because the (best-effort, advisory) near-duplicate guard blew up outright —
    the same "GPU down must not cost the compliance panel" invariant
    ``test_composer_duplicates.py`` proves one layer down, proven here at the route
    that actually wires it in."""

    async def raising_find_related(*args: object, **kwargs: object) -> DuplicateGuard:
        raise RuntimeError("aria-gb10-2 unreachable")

    monkeypatch.setattr(compose_ui, "find_related_roles", raising_find_related)
    _override_related_roles_guard_deps()

    summary = " ".join(["word"] * 40)  # a bare draft: no duties -> blocking gates fire
    resp = _client().post(
        "/jd-bank/ui/compose/new",
        data={"title": "Analyst", "position_summary": summary},
    )
    assert resp.status_code == 200
    html = resp.text
    assert "Live compliance" in html
    assert "Score:" in html
    assert "Grade:" in html
    assert "Blocking gates" in html
    assert "Fix these" in html


def test_check_survives_clients_that_cannot_even_be_constructed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A misconfigured environment must not take the Builder down.

    Both real factories raise at CONSTRUCTION on a misconfiguration — ``EmbedClient``
    runs the egress guard (NN #5) in ``__init__``, and the Neo4j driver rejects a bad
    URI scheme — and FastAPI solves dependencies BEFORE the route body, so a route-body
    ``try/except`` cannot see it: the request 500s and the author loses the compliance
    panel over a wrong environment variable.

    So this drives the REAL factory chain end to end — every override for these two
    deps is popped — and trips the actual construction-time failures: the egress guard
    (NN #5) rejecting the configured host, and the Neo4j driver rejecting its URI.

    It has to reach that far down to be a real pin. Rebinding the factory FUNCTIONS
    would not do it: FastAPI captures the callable named in ``Depends(...)`` when the
    route is defined, so a patched ``compose.get_embed_client`` is never consulted and
    this test passed against the very defect it exists to catch (measured — twice: the
    dependency overrides also had to go, or the fakes answered instead). With the
    strict factories wired back onto this route, this goes red."""

    def _boom(*args: object, **kwargs: object) -> object:
        raise RuntimeError("OLLAMA_BASE_URL points outside the allow-list")

    _override_related_roles_guard_deps()
    for hook in (
        compose.get_embed_client,
        compose.get_neo4j_driver,
        compose.get_optional_embed_client,
        compose.get_optional_neo4j_driver,
    ):
        app.dependency_overrides.pop(hook, None)  # no fakes: reach the real factories
    monkeypatch.setattr(embed_client_mod, "assert_inference_host_allowed", _boom)
    monkeypatch.setattr(compose, "AsyncGraphDatabase", SimpleNamespace(driver=_boom))

    resp = _client().post(
        "/jd-bank/ui/compose/new",
        data={"title": "Analyst", "position_summary": " ".join(["word"] * 40)},
    )
    assert resp.status_code == 200
    html = resp.text
    assert "Live compliance" in html
    assert "Score:" in html
    assert "Blocking gates" in html
    # ...and the advisory panel is ABSENT, never a falsely reassuring "no matches".
    assert "Roles SFU already has" not in html


def test_check_survives_a_guard_that_never_returns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The failure a ``try/except`` cannot catch: an inference host that ACCEPTS and
    then stalls. Without a bound, the embedding client would read for 600s with
    retries while holding this request AND its checked-out database session, and a
    handful of concurrent Checks would exhaust the pool and stop the Builder serving.

    ``dedup.authoring_guard.timeout_seconds`` (HR-197) bounds it — retuned to a tiny
    value here so the test is fast, which also proves the budget is READ FROM THE
    RULEBOOK rather than hardcoded (at the shipped 5.0s this test would hang)."""
    started = asyncio.Event()

    async def never_returns(*args: object, **kwargs: object) -> DuplicateGuard:
        started.set()
        await asyncio.sleep(30)
        raise AssertionError("the guard should have been abandoned long before this")

    monkeypatch.setattr(compose_ui, "find_related_roles", never_returns)
    monkeypatch.setattr(
        compose_ui,
        "get_rules",
        lambda: retuned_dedup(
            get_rules(),
            authoring_guard={
                "max_matches": 5,
                "min_draft_chars": 500,
                "timeout_seconds": 0.05,
            },
        ),
    )
    _override_related_roles_guard_deps()

    resp = _client().post(
        "/jd-bank/ui/compose/new",
        data={"title": "Analyst", "position_summary": " ".join(["word"] * 40)},
    )
    assert resp.status_code == 200
    assert started.is_set(), "the guard never ran, so nothing was actually bounded"
    assert "Live compliance" in resp.text
    assert "Roles SFU already has" not in resp.text


def test_check_closes_its_clients_even_when_it_fails_before_the_guard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every path, including the ones that never reach the guard at all.

    A body that is not valid UTF-8 fails at ``decode`` — before the answers are read,
    before anything is assembled — and that used to be outside every ``try``, so the
    injected clients were dropped un-closed. Low impact (neither has opened a socket
    yet) but the module's own contract says they are closed on every path, and a
    contract that is false in one corner is not a contract.

    The second half of the same fix: a ``close()`` that RAISES must not swallow the
    other client's close, which two bare sequential awaits did."""
    embed, neo = _FakeClose(), _FakeClose()

    async def _angry_close() -> None:
        raise RuntimeError("connection already reset")

    monkeypatch.setattr(embed, "close", _angry_close)
    _override_session_object()
    app.dependency_overrides[compose.get_optional_embed_client] = lambda: embed
    app.dependency_overrides[compose.get_optional_neo4j_driver] = lambda: neo

    # `raise_server_exceptions=False` so the 500 is observed as a RESPONSE rather than
    # re-raised into the test: the point is what the handler did on its way out, not
    # that a malformed body is an error.
    resp = TestClient(app, raise_server_exceptions=False).post(
        "/jd-bank/ui/compose/new",
        content=b"\xff\xfe title=x",
        headers={"content-type": "application/x-www-form-urlencoded"},
    )
    assert resp.status_code == 500  # the decode failure itself is not swallowed...
    assert neo.closed is True  # ...and the driver was still closed, despite the
    #                            embed client's own close() blowing up first.


def test_check_passes_the_cloned_from_role_to_the_guard_as_the_exclusion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """THE feature's headline behaviour: cloning a role must not immediately warn you
    that you duplicated the role you cloned. Every other route-level fake here
    discards ``**kwargs``, so this captures what the route actually passes — change
    the call to ``exclude_cluster_id=None`` and only this test notices."""
    recorded: dict[str, object] = {}

    async def recording_find_related(*args: object, **kwargs: object) -> DuplicateGuard:
        recorded.update(kwargs)
        return _related_guard()

    monkeypatch.setattr(compose_ui, "find_related_roles", recording_find_related)
    _override_related_roles_guard_deps()

    cluster_id = uuid.uuid4()
    resp = _post_form(
        _client(),
        "/jd-bank/ui/compose/new",
        [("title", "Academic Advisor"), ("cloned_from_cluster_id", str(cluster_id))],
    )
    assert resp.status_code == 200
    assert recorded["exclude_cluster_id"] == cluster_id


def test_a_draft_that_was_not_cloned_excludes_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The other half — otherwise the assertion above would pass on a route that
    always excluded the same thing."""
    recorded: dict[str, object] = {}

    async def recording_find_related(*args: object, **kwargs: object) -> DuplicateGuard:
        recorded.update(kwargs)
        return _related_guard()

    monkeypatch.setattr(compose_ui, "find_related_roles", recording_find_related)
    _override_related_roles_guard_deps()

    resp = _client().post("/jd-bank/ui/compose/new", data={"title": "Academic Advisor"})
    assert resp.status_code == 200
    assert recorded["exclude_cluster_id"] is None


def test_cloned_from_cluster_id_round_trips_through_answers_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Set when the author starts the Builder from a harmonized role (and passed as
    ``exclude_cluster_id`` to the guard, so cloning a role never immediately warns
    you that you duplicated the very role you cloned) — must survive a Check, so a
    later Submit/Export rebuilds a draft that still remembers where it came from."""

    async def fake_find_related(*args: object, **kwargs: object) -> DuplicateGuard:
        return _related_guard()

    monkeypatch.setattr(compose_ui, "find_related_roles", fake_find_related)
    _override_related_roles_guard_deps()

    cluster_id = uuid.uuid4()
    resp = _post_form(
        _client(),
        "/jd-bank/ui/compose/new",
        [
            ("title", "Academic Advisor"),
            ("cloned_from_cluster_id", str(cluster_id)),
        ],
    )
    assert resp.status_code == 200
    answers = compose_ui.ComposerAnswers.model_validate_json(
        _answers_json_from(resp.text)
    )
    assert answers.cloned_from_cluster_id == cluster_id


# --- a stalled inference host must not pin an interactive request ---------------
#
# The 5.9 guard was fixed for this in `cadfc30`'s review: `connect=5.0` means a
# REFUSED connection fails fast, so "Ollama is down" was never the risk — a host
# that ACCEPTS and then stalls is. Read 600s x 2 SDK retries x 3 attempts is ~90
# minutes of a held request, and `/compose/search` holds a checked-out AsyncSession
# for all of it. The guard got `asyncio.wait_for`; `/compose/search` and `/assist`
# were left with the same defect, recorded as open ever since. This closes them.


class _Stalls:
    """An inference client that ACCEPTS and never answers — the real failure mode.
    Sleeps far past any sane budget rather than raising, which is exactly what a
    `try`/`except` cannot catch."""

    def __init__(self) -> None:
        self.closed = False

    async def chat_json(self, *args: object, **kwargs: object) -> object:
        await asyncio.sleep(3600)
        raise AssertionError("unreachable")  # pragma: no cover

    async def embed(self, *args: object, **kwargs: object) -> object:
        await asyncio.sleep(3600)
        raise AssertionError("unreachable")  # pragma: no cover

    async def close(self) -> None:
        self.closed = True


def test_assist_gives_up_on_a_stalled_model_and_keeps_the_authors_draft(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The author gets their page back with an explanation — and, critically, with
    the words they had already typed. Losing a half-written JD to a wedged GPU is a
    worse outcome than not getting a suggestion."""
    monkeypatch.setattr(
        compose_ui,
        "get_rules",
        lambda: retuned_rewrite(get_rules(), interactive_timeout_seconds=0.05),
    )
    stalled = _Stalls()
    app.dependency_overrides[compose.get_chat_client] = lambda: stalled

    resp = _client().post(
        "/jd-bank/ui/compose/assist",
        data={"title": "Financial Analyst", "position_summary": "My own words here."},
    )

    assert resp.status_code == 200, "a stalled model must not 500 the Builder"
    assert "My own words here." in resp.text, "the author's draft was lost"
    assert "took too long" in resp.text
    assert stalled.closed is True, "the client leaked when the call timed out"


def test_search_gives_up_on_a_stalled_embedding_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Same defect, and worse consequence: this route holds a checked-out
    AsyncSession out of a small pool, so a few stalled searches take the whole
    Builder down with them."""

    async def stalls(query: str, **kwargs: object) -> list[object]:
        await asyncio.sleep(3600)
        raise AssertionError("unreachable")  # pragma: no cover

    monkeypatch.setattr(compose_ui, "search_similar_jds", stalls)
    monkeypatch.setattr(
        compose_ui,
        "get_rules",
        lambda: retuned_embeddings(get_rules(), interactive_timeout_seconds=0.05),
    )
    embed, neo = _FakeClose(), _FakeClose()
    app.dependency_overrides[compose.get_embed_client] = lambda: embed
    app.dependency_overrides[compose.get_neo4j_driver] = lambda: neo
    _override_session_object()

    resp = _client().get("/jd-bank/ui/compose/search?q=analyst")

    assert resp.status_code == 200, "a stalled embedding host must not 500 the page"
    assert "took too long" in resp.text
    assert "analyst" in resp.text, "the author's query was thrown away"
    assert embed.closed is True and neo.closed is True, "a client leaked on timeout"


def test_submit_carries_the_clone_lineage_into_the_persist_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The ROUTE's half of the lineage fix, pinned separately from the persist layer's.

    This repo has been bitten by exactly this gap before: `exclude_cluster_id` was the
    headline behaviour of the 5.9 guard and went unasserted, because every route-level
    fake took `**kwargs` and quietly discarded them. So assert the KEYWORD, not just
    that the call happened — deleting the argument from the route must turn this red.
    """
    session = _FakeSession()
    parent = uuid.uuid4()
    submit_mock = AsyncMock(return_value=type("C", (), {"id": uuid.uuid4()})())
    monkeypatch.setattr(compose_ui, "submit_composed_draft", submit_mock)

    answers = json.dumps({"title": "Role", "cloned_from_cluster_id": str(parent)})
    resp = _client_with_session(session).post(
        "/jd-bank/ui/compose/submit",
        data={"answers_json": answers},
        follow_redirects=False,
    )

    assert resp.status_code == 303
    assert submit_mock.await_args is not None
    assert submit_mock.await_args.kwargs["cloned_from_cluster_id"] == parent


def test_submit_of_an_original_draft_passes_no_parent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The other half: a draft written from scratch must not acquire a parent."""
    session = _FakeSession()
    submit_mock = AsyncMock(return_value=type("C", (), {"id": uuid.uuid4()})())
    monkeypatch.setattr(compose_ui, "submit_composed_draft", submit_mock)

    _client_with_session(session).post(
        "/jd-bank/ui/compose/submit",
        data={"answers_json": '{"title": "Role"}'},
        follow_redirects=False,
    )

    assert submit_mock.await_args is not None
    assert submit_mock.await_args.kwargs["cloned_from_cluster_id"] is None


# --- the WJQ form is reachable and round-trips (CUPE Phase E) -------------------------


def test_the_wjq_form_renders_its_own_questions_and_not_the_jdfn_ones() -> None:
    """``?form=wjq`` walks the CUPE questionnaire. The negative assertions matter more
    than the positive ones: an author on the WJQ must not be asked for Problem Solving
    or Impact of Decision Making (0.0% and 3.1% of CUPE JDs have them, because the form
    does not ask), nor for SFU boilerplate the form does not carry (HR-201)."""
    html = _client().get("/jd-bank/ui/compose/new?form=wjq").text

    assert 'name="level_of_independence"' in html
    assert 'name="impact_of_errors"' in html
    assert 'name="major_functions_statement"' in html
    assert 'name="minor_functions_statement"' in html
    # The form's OWN section names, not the JDFN labels.
    assert "5 · Level of Independence" in html
    assert 'name="decision_making"' not in html
    assert 'name="problem_solving"' not in html
    assert 'name="include_sfu_boilerplate"' not in html
    # ...and the hidden field that keeps every POST back on this form.
    assert 'name="form" value="wjq"' in html


def test_the_jdfn_form_is_unchanged_by_the_existence_of_the_wjq_one() -> None:
    """The control. Every Phase-D/E change kept JDFN identical, and the Builder is in
    use — so the default form still asks for the JDFN sections and nothing else."""
    html = _client().get("/jd-bank/ui/compose/new").text

    assert 'name="decision_making"' in html
    assert 'name="problem_solving"' in html
    assert 'name="include_sfu_boilerplate"' in html
    assert 'name="level_of_independence"' not in html
    assert 'name="form" value="jdfn"' in html


def test_an_unknown_form_starts_the_jdfn_flow_rather_than_422ing() -> None:
    """The 8.3a lesson on a page a person is using: a ``Literal`` query param would
    answer a typo with a raw 422 JSON blob."""
    resp = _client().get("/jd-bank/ui/compose/new?form=nonsense")

    assert resp.status_code == 200
    assert 'name="form" value="jdfn"' in resp.text


def test_a_wjq_check_assembles_a_cupe_draft_judged_by_the_wjq_bar() -> None:
    """End to end through the POST: the answers are read through the WJQ contract, the
    WJQ assembler builds the draft, and the live panel judges it as a CUPE document —
    so the JDFN-only rules cannot appear in it (Phase B)."""
    resp = _client().post(
        "/jd-bank/ui/compose/new",
        data={
            "form": "wjq",
            "title": "Departmental Assistant",
            "position_summary": "Provides administrative support to the department.",
            "major_functions_verb": "Processes",
            "major_functions_statement": "Processes purchase orders for the unit",
            "major_functions_allocation": "40",
            "level_of_independence": "Works under general supervision.",
        },
    )

    assert resp.status_code == 200
    html = resp.text
    # The live panel ran — so the body was read through the WJQ contract, assembled by
    # the WJQ assembler, and validated. (That the point-factor text lands under the
    # parser's own heading is the ASSEMBLER's property, pinned in test_composer_forms;
    # `additional_context` is assembled rather than an answer field, so it is correctly
    # absent from the form this page re-renders.)
    assert "Live compliance" in html
    # The author's answers came back, so nothing was dropped by the round trip.
    assert "Works under general supervision." in html
    assert "Processes purchase orders for the unit" in html
    # JDFN-only findings are structurally unable to appear on a CUPE draft (Phase B).
    assert "SFU-COMP-PROBLEM" not in html
    assert "SFU-COMP-TERRITORIAL" not in html
    # ...and the form has no section to fill for what the WJQ does not ask. Asserted on
    # the section ANCHOR, not the prose: the phrase "Impact of Decision Making" is in
    # the form's own description ("it has no Problem Solving or Impact of Decision
    # Making section"), which is the page correctly explaining itself.
    assert 'id="section-decision_making"' not in html
    assert 'id="section-problem_solving"' not in html


# ── P0-1: the page, not the handler ──────────────────────────────────────────────────
#
# Four WJQ UI tests above pass while a CUPE author cannot finish a draft, because each
# synthesises its own POST body and supplies the hidden ``form`` field the PAGE forgets
# to emit. Hidden inputs do not cross ``<form>`` boundaries, and Export and Submit are
# separate forms from Check. These drive the round trip from the RENDERED HTML — the
# pairs a browser would actually send — so a field missing from one form of three is a
# red test rather than a pydantic error page that wipes everything the author typed.

_COMPOSE = "/jd-bank/ui/compose"
_INPUT_TAG = re.compile(r"<input\b[^>]*>", re.IGNORECASE)
_ATTR = r"""{}\s*=\s*["']([^"']*)["']"""

#: A minimal but real WJQ questionnaire, as the fields the page names them.
_WJQ_ANSWERS: list[tuple[str, str]] = [
    ("form", "wjq"),
    ("title", "Departmental Assistant"),
    ("position_summary", "Provides administrative support to the department."),
    ("major_functions_verb", "Processes"),
    ("major_functions_statement", "Processes purchase orders for the unit"),
    ("major_functions_allocation", "40"),
    ("level_of_independence", "Works under general supervision."),
]


def _browser_pairs(html_text: str, action: str) -> list[tuple[str, str]]:
    """Exactly what a browser sends when the button in the form posting to ``action``
    is pressed: every named ``<input>`` INSIDE THAT ``<form>``, and nothing else."""
    forms = [f for f in post_forms(html_text) if action_of(f) == action]
    assert len(forms) == 1, (
        f"expected one form posting to {action}, found {len(forms)} — the page changed "
        "shape, so this test is no longer driving the round trip it claims to"
    )
    pairs: list[tuple[str, str]] = []
    for tag in _INPUT_TAG.finditer(forms[0]):
        name = re.search(_ATTR.format("name"), tag.group(0))
        if name is None:
            continue
        value = re.search(_ATTR.format("value"), tag.group(0))
        pairs.append(
            (
                html_lib.unescape(name.group(1)),
                html_lib.unescape(value.group(1)) if value else "",
            )
        )
    return pairs


def _checked_wjq_page() -> str:
    """The Builder page a CUPE author is looking at after pressing Check."""
    resp = _post_form(_client(), "/jd-bank/ui/compose/new", _WJQ_ANSWERS)
    assert resp.status_code == 200
    return resp.text


def test_a_wjq_author_can_export_from_the_page_the_builder_renders() -> None:
    """P0-1. Posted with the export form's OWN fields — no synthesised ``form``. Before
    the fix this answered 200 ``text/html``: a pydantic error page, not a ``.docx``."""
    page = _checked_wjq_page()
    action = "/jd-bank/ui/compose/export"

    resp = _post_form(_client(), action, _browser_pairs(page, action))

    assert resp.status_code == 200
    assert resp.headers["content-type"] == (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    assert resp.content[:2] == b"PK"  # a .docx is a zip archive


def test_a_wjq_author_can_submit_from_the_page_the_builder_renders(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """P0-1, the other half. Before the fix this returned 200 (the error page) with
    nothing persisted, and the author's whole questionnaire gone from the page."""
    page = _checked_wjq_page()
    action = "/jd-bank/ui/compose/submit"
    session = _FakeSession()
    submit_mock = AsyncMock(return_value=type("C", (), {"id": uuid.uuid4()})())
    monkeypatch.setattr(compose_ui, "submit_composed_draft", submit_mock)

    resp = _post_form(
        _client_with_session(session),
        action,
        _browser_pairs(page, action),
        follow_redirects=False,
    )

    assert resp.status_code == 303, (
        "the CUPE author's Submit did not persist — a 200 here is the error page that "
        "ends the Phase E journey"
    )
    submit_mock.assert_awaited_once()
    # ...and it was assembled through the WJQ contract, not silently re-read as JDFN.
    submitted = submit_mock.await_args
    assert submitted is not None
    assert submitted.args[1].employee_group == "cupe"


@pytest.mark.parametrize("form_name", ["jdfn", "wjq"])
def test_every_posting_form_on_the_builder_page_carries_the_form_field(
    form_name: str,
) -> None:
    """The generalised guard, and the durable one: the CSRF scan asks this question of
    ``csrf_token`` on every template; ``form`` is the second field with the same
    property — required by every handler the page posts to, and defaulting silently to
    JDFN when absent. A field on the page is not a field on the form."""
    page = _post_form(
        _client(),
        "/jd-bank/ui/compose/new",
        _WJQ_ANSWERS if form_name == "wjq" else [("form", "jdfn"), ("title", "Role")],
    ).text

    # The Builder's own forms — not the base template's sign-out, which is every
    # page's and carries no draft.
    forms = [f for f in post_forms(page) if action_of(f).startswith(_COMPOSE)]
    assert len(forms) == 3, f"expected check + export + submit, found {len(forms)}"
    for form in forms:
        assert f'name="form" value="{form_name}"' in form, (
            f"the form posting to {action_of(form)!r} does not carry the SFU form the "
            f"author is filling ({form_name}), so its handler falls back to JDFN and "
            f"reads their answers through the wrong contract.\n{form[:300]}"
        )


# ── S-1: the dropdown is not the control ─────────────────────────────────────────────


def test_a_posted_employee_group_cannot_move_a_jdfn_draft_onto_the_cupe_bar() -> None:
    """S-1. The page offers apsa/apex/poly; the handler took whatever was posted. A
    body is not a dropdown, so this is the path that matters: same content, one field,
    and the draft was scored by the other form's rules and numbers.

    The author gets the error page, not a CUPE-scored panel — and specifically not the
    approvable one, because ``SFU-APPROVE-EDI-FOOTER`` does not apply to the WJQ."""
    resp = _post_form(
        _client(),
        "/jd-bank/ui/compose/new",
        [
            ("form", "jdfn"),
            ("title", "Financial Analyst"),
            ("employee_group", "cupe"),
            ("position_summary", "Analyses budgets for the faculty."),
        ],
    )

    assert resp.status_code == 200
    body = resp.text
    assert "cupe" in body.lower()  # the error names the group it refused
    # It did NOT quietly become a CUPE draft judged by the CUPE bar.
    assert "Live compliance" not in body


def test_a_tampered_answers_json_cannot_submit_onto_the_other_forms_bar(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The same hole through the OTHER door. ``/submit`` and ``/export`` rebuild from
    ``answers_json`` rather than from the guided fields, so a check on the form parse
    alone would have left this path open — which is why the guard sits on the assemble
    seam every one of them crosses."""
    session = _FakeSession()
    submit_mock = AsyncMock(return_value=type("C", (), {"id": uuid.uuid4()})())
    monkeypatch.setattr(compose_ui, "submit_composed_draft", submit_mock)

    resp = _post_form(
        _client_with_session(session),
        "/jd-bank/ui/compose/submit",
        [
            ("form", "jdfn"),
            ("answers_json", '{"title": "Analyst", "employee_group": "cupe"}'),
        ],
        follow_redirects=False,
    )

    assert resp.status_code == 200  # the error page, not a 303
    submit_mock.assert_not_awaited()
    session.commit.assert_not_awaited()

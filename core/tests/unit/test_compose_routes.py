"""Phase 5.1 — the ``POST /jd-bank/compose/validate`` route (thin, stateless).

Mirrors ``test_review_routes``'s harness: drive ``TestClient(app)`` WITHOUT the
lifespan (no startup/shutdown, so no DB/Redis is touched). This route has no
session dependency at all — it validates the body into an ``SFUJobDescription``
and calls the pure ``assess_draft`` — so nothing needs to be overridden; the test
just posts a JD and asserts the transported assessment.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from src.api.main import app


def _client() -> TestClient:
    # No `with` block -> lifespan is not entered -> no engine/pool created.
    return TestClient(app)


def test_validate_empty_draft_returns_guidance_and_not_approvable() -> None:
    resp = _client().post("/jd-bank/compose/validate", json={"title": "New Role"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["approvable"] is False
    assert body["report"]["gate_decision"]["approved"] is False
    assert body["guidance"], "an empty draft should carry authoring guidance"
    assert body["summary_word_count"] == 0
    # position_summary is present in the section list and marked empty.
    summary = next(s for s in body["sections"] if s["section"] == "position_summary")
    assert summary["state"] == "empty"


def test_validate_weak_summary_surfaces_a_fixit_finding() -> None:
    jd = {
        "title": "Software Developer",
        "position_summary": " ".join(["word"] * 40),
        "duties": [{"action_verb": "Manages", "statement": "Manages the program"}],
    }
    resp = _client().post("/jd-bank/compose/validate", json=jd)
    assert resp.status_code == 200
    body = resp.json()
    assert body["summary_word_count"] == 40
    finding_rule_ids = {f["rule_id"] for f in body["findings"]}
    assert "SFU-STRUCT-SUMMARY-TOO-SHORT" in finding_rule_ids


def test_validate_rejects_a_malformed_body() -> None:
    # `title` is required (min_length=1); FastAPI returns 422 on the bad body.
    resp = _client().post("/jd-bank/compose/validate", json={"title": ""})
    assert resp.status_code == 422

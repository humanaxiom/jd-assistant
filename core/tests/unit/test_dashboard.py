"""Unit tests for the Phase-4.6c read-only "Archive Baseline" dashboard.

The whole point of this page (task 4.6c slice 1) is that it renders values READ FROM
``docs/baseline/summary.json`` — never a hardcoded headline number. So the load-bearing
test points the loader at a FIXTURE summary with DISTINCT sentinel numbers and asserts
the page shows THOSE numbers: if anyone re-introduces a literal ``78.6`` / ``14565``
into a template, ``test_baseline_page_renders_numbers_from_the_file`` fails.

Mirrors ``test_review_ui.py``: drive ``TestClient(app)`` WITHOUT the lifespan, and
override the ``get_baseline_summary_path`` dependency to point at a fixture (or at a
missing path, to prove the empty-state) — no DB, no real ``docs/`` (which is invisible
inside the gates container anyway; see the Makefile).
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.api.main import app
from src.api.routes.dashboard import get_baseline_summary_path

_FIXTURE = Path(__file__).resolve().parent.parent / "fixtures"
_SENTINEL = _FIXTURE / "baseline_summary_sentinel.json"


@pytest.fixture(autouse=True)
def _clear_overrides() -> Iterator[None]:
    yield
    app.dependency_overrides.clear()


def _client(summary_path: Path) -> TestClient:
    def override_path() -> Path:
        return summary_path

    app.dependency_overrides[get_baseline_summary_path] = override_path
    return TestClient(app, follow_redirects=False)


# --- GET /jd-bank/ui/dashboard (index) -----------------------------------------------


def test_index_renders_and_links_to_baseline_page() -> None:
    # The index is static; it does not need the artifact at all.
    client = _client(_SENTINEL)

    resp = client.get("/jd-bank/ui/dashboard")

    assert resp.status_code == 200
    assert "/jd-bank/ui/dashboard/baseline" in resp.text


# --- GET /jd-bank/ui/dashboard/baseline (the read-only baseline dashboard) -----------


def test_baseline_page_renders_numbers_from_the_file() -> None:
    """The anti-hardcode guarantee: every figure below is a sentinel that appears ONLY
    in the fixture, so a passing assertion proves the value was read from the artifact
    and not typed into a template."""
    client = _client(_SENTINEL)

    resp = client.get("/jd-bank/ui/dashboard/baseline")

    assert resp.status_code == 200
    body = resp.text

    # Totals (top-level artifact keys).
    assert "91237" in body  # file_count
    assert "90111" in body  # scored
    assert "1126" in body  # skipped

    # Provenance stamp — the reader must know exactly which run produced these numbers.
    assert "SENTINEL_RULES_vZ+deadbeef1234" in body  # rules_version
    assert "SENTINEL_PARSER_vZ" in body  # parser_version
    assert "SENTINEL_CONFIG+cafef00d5678" in body  # config_stamp
    assert "2099" in body  # generated_at year

    # Whole-archive headline figures (all/all segment).
    assert "41.4" in body  # median score 41.4159
    assert "1.9" in body  # approval_rate 0.019073 -> 1.9%
    # Grade distribution A/B/C/D/F for the whole archive.
    for count in ("111", "222", "333", "444", "555"):
        assert count in body

    # The current-practice COHORT headline (Phase 4.6c) — read from the cohort segment,
    # never hardcoded. Distinct sentinels that appear only on that segment.
    assert "863" in body  # cohort n_scored
    assert "79.3" in body  # cohort median 79.3111
    assert "79.0" in body  # cohort approval 0.790266 -> 79.0%
    assert "682" in body  # cohort approved

    # Era bands — the current band's distinctive median + approval%.
    assert "87.6" in body  # era=current median 87.6111
    assert "65.3" in body  # era=current approval 0.652629 -> 65.3%
    assert "4488" in body  # era=current n_files

    # Template facet — WJQ must be visible as its own facet (no JDFN bar).
    assert "48.9" in body  # wjq median 48.9111
    assert "30000" in body  # wjq n_files


def test_baseline_page_headlines_the_cohort_as_the_bars_real_trial() -> None:
    """The cohort must be framed as the population the bar is ratified against, and it
    must appear BEFORE the whole-archive 'category error' block."""
    client = _client(_SENTINEL)

    resp = client.get("/jd-bank/ui/dashboard/baseline")

    body = resp.text
    lower = body.lower()
    assert "the bar's real trial" in lower
    assert "the population hr ratifies against" in lower
    # Ordering: the cohort headline number precedes the whole-archive 'category error'.
    assert body.index("79.0") < body.index("category error")


def test_baseline_page_without_cohort_segment_shows_regenerate_hint(
    tmp_path: Path,
) -> None:
    """An OLDER summary.json generated before the cohort segment existed must still
    render 200 — the rest of the page intact and a regenerate hint where the cohort
    headline would be — never a crash."""
    import json

    data = json.loads(_SENTINEL.read_text(encoding="utf-8"))
    data["segments"] = [seg for seg in data["segments"] if seg["dimension"] != "cohort"]
    older = tmp_path / "summary.json"
    older.write_text(json.dumps(data), encoding="utf-8")
    client = _client(older)

    resp = client.get("/jd-bank/ui/dashboard/baseline")

    assert resp.status_code == 200
    body = resp.text
    assert "predates the current-practice cohort" in body
    # The rest of the page still renders from the remaining segments.
    assert "4488" in body  # era=current n_files is unaffected


def test_baseline_page_labels_current_band_as_a_date_band() -> None:
    """README framing must be reflected: the ``current`` ERA band is a date band, not
    the 874-JD current-practice cohort — so the page must not present the band's number
    as "the bar's approval rate"."""
    client = _client(_SENTINEL)

    resp = client.get("/jd-bank/ui/dashboard/baseline")

    body = resp.text.lower()
    assert "date band" in body or "not the cohort" in body
    # And the whole-archive number carries its "do not quote" warning.
    assert "category error" in body


def test_baseline_page_missing_artifact_is_graceful_empty_state_not_500() -> None:
    missing = _FIXTURE / "does_not_exist_baseline.json"
    assert not missing.exists()
    client = _client(missing)

    resp = client.get("/jd-bank/ui/dashboard/baseline")

    assert resp.status_code == 200
    assert "make baseline" in resp.text


def test_baseline_page_unreadable_artifact_is_graceful(tmp_path: Path) -> None:
    """A present-but-corrupt artifact must also degrade to the empty-state, not 500."""
    broken = tmp_path / "summary.json"
    broken.write_text("{ this is not valid json", encoding="utf-8")
    client = _client(broken)

    resp = client.get("/jd-bank/ui/dashboard/baseline")

    assert resp.status_code == 200
    assert "make baseline" in resp.text

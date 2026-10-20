"""Track J, PR J2 — the CUPE (WJQ) Builder page collects HR's form structure.

Driven through the real routes (``TestClient(app)``, no lifespan, no DB), like the rest
of the Builder UI suite. What a CUPE author must be able to do on the PAGE: give each
major function its (D)/(W)/(M)/(S) code, tick HR's levels, fill the duration / frequency
/ hours tables, use the Occupational Skills helpers — and be TOLD, not silently cut,
when a section is over its limit.
"""

from __future__ import annotations

import html as html_lib
import json

import pytest

from src.api.main import app  # noqa: F401 — the routes import back from it
from src.api.routes import compose_ui
from src.jd_bank.composer import wjq_assemble
from src.jd_bank.composer.forms import FORMS
from src.jd_bank.composer.wjq_answers import (
    FunctionAnswer,
    MinorFunctionAnswer,
    WJQAnswers,
)
from src.jd_bank.db.models import DocumentFormat
from src.jd_bank.ingest.extract import extract_text
from src.jd_core.rules import get_rules
from tests.unit.retuned_rules import retuned_cupe_form
from tests.unit.test_compose_ui import (  # noqa: F401 — the two fixtures are autouse
    _answers_json_from,
    _browser_pairs,
    _clear_overrides,
    _client,
    _default_related_roles_deps,
    _post_form,
)

_NEW = "/jd-bank/ui/compose/new"

#: A CUPE questionnaire as a browser posts it, using every J2 control.
_PAIRS: list[tuple[str, str]] = [
    ("form", "wjq"),
    ("title", "Department Secretary"),
    ("current_classification", "Secretary Grade 6"),
    ("supervisor_title", "Department Manager"),
    ("date_completed", "2026-10-19"),
    ("completed_by", "employee"),
    ("position_summary", "Provides secretarial support to the department."),
    ("major_functions_action_verb", "Types"),
    ("major_functions_statement", "Types letters and reports"),
    ("major_functions_frequency", "daily"),
    ("major_functions_action_verb", "Maintains"),
    ("major_functions_statement", "Maintains office files"),
    ("major_functions_frequency", "weekly"),
    ("minor_functions_action_verb", "Purges"),
    ("minor_functions_statement", "Purges and archives records"),
    ("level_of_independence_levels", "B"),
    ("training_exercised_levels", "A"),
    ("direction_exercised_levels", "A"),
    ("continuing_education_levels", "B"),
    ("continuing_education_levels", "C"),
    ("contacts_contact", "Students"),
    ("contacts_scope", "internal"),
    ("contacts_duration", "< 1 hour"),
    ("contacts_frequency", "Frequent"),
    ("effort_rows_effort", "Visual"),
    ("effort_rows_duration", "1-2 hours"),
    ("effort_rows_frequency", "Frequent"),
    ("location_rows_location", "General office"),
    ("location_rows_hours", "35 / 35"),
    ("uncomfortable_rows_condition", "Distracting noise"),
    ("uncomfortable_rows_frequency", "Occasional"),
    ("hazard_rows_condition", "Dealing with complaints"),
    ("hazard_rows_frequency", "Occasional"),
    ("education", "High school graduation"),
    ("certification", "None"),
    ("experience_years", "2"),
    ("equivalency", "acceptable"),
    ("occupational_skills_helper", "Ability to"),
    ("occupational_skills_text", "use standard office applications"),
    ("occupational_skills_helper", ""),
    ("occupational_skills_text", "55 wpm keyboarding skill"),
    ("occupational_requirements", "None"),
]


def _checked(pairs: list[tuple[str, str]] = _PAIRS) -> str:
    resp = _post_form(_client(), _NEW, pairs)
    assert resp.status_code == 200
    return resp.text


def test_the_cupe_page_asks_hrs_questions_not_the_approved_grade() -> None:
    html = _client().get(f"{_NEW}?form=wjq").text
    assert "approved classification" not in html.lower()
    for name in (
        "current_classification",
        "supervisor_title",
        "date_completed",
        "completed_by",
        "major_functions_frequency",
        "level_of_independence_levels",
        "contacts_duration",
        "effort_rows_frequency",
        "location_rows_hours",
        "hazard_rows_frequency",
        "certification",
        "experience_years",
        "equivalency",
        "equivalency_rationale",
        "occupational_skills_helper",
        "occupational_requirements",
    ):
        assert f'name="{name}"' in html, f"the CUPE page has no {name!r} control"
    # The % of time is a JDFN concept; HR's CUPE form asks (D)/(W)/(M)/(S). (A pre-J2
    # allocation rides through as a HIDDEN field — kept, never asked.)
    assert 'aria-label="Percentage of time"' not in html
    assert 'type="hidden" name="major_functions_allocation"' in html
    # HR's own level wording is what the author ticks.
    option = get_rules().cupe_form.checkbox_options["direction_exercised"][2]
    assert html_lib.escape(option) in html or option in html
    # The limit is shown, not discovered.
    assert "up to 12" in html.lower()


def test_the_cupe_hints_follow_hrs_wording() -> None:
    """Gap analysis §4 P2: four hints contradicted S13/S14."""
    html = html_lib.unescape(_client().get(f"{_NEW}?form=wjq").text)
    assert "percentage of time" not in html
    assert "incidental" not in html
    assert "annually and periodically" in html
    assert "Certifications to maintain" not in html
    assert "shift or on-call patterns" not in html
    assert "Performs other duties and responsibilities" in html  # the catch-all


def test_a_check_carries_every_structured_answer_into_the_draft() -> None:
    answers = WJQAnswers.model_validate_json(_answers_json_from(_checked()))
    assert [(f.statement, f.frequency) for f in answers.major_functions] == [
        ("Types letters and reports", "daily"),
        ("Maintains office files", "weekly"),
    ]
    assert [f.statement for f in answers.minor_functions] == [
        "Purges and archives records"
    ]
    assert answers.level_of_independence_levels == ["B"]
    assert answers.continuing_education_levels == ["B", "C"]
    assert [(c.contact, c.duration, c.frequency) for c in answers.contacts] == [
        ("Students", "< 1 hour", "Frequent")
    ]
    assert answers.location_rows[0].hours == "35 / 35"
    assert answers.experience_years == 2
    assert answers.equivalency == "acceptable"
    assert [(s.helper, s.text) for s in answers.occupational_skills] == [
        ("Ability to", "use standard office applications"),
        (None, "55 wpm keyboarding skill"),
    ]
    assert answers.completed_by == "employee"
    assert str(answers.date_completed) == "2026-10-19"


def test_the_page_repopulates_every_structured_answer() -> None:
    html = _checked()
    assert 'value="Purges and archives records"' in html
    assert 'value="35 / 35"' in html
    # The chosen level is ticked again on the re-rendered page.
    assert 'name="level_of_independence_levels" value="B" checked' in html


def test_over_the_limit_the_author_is_told_and_every_row_is_kept(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tight = retuned_cupe_form(
        get_rules(), function_limits={"major_functions": 1, "minor_functions": 12}
    )
    monkeypatch.setattr(wjq_assemble, "get_rules", lambda: tight)
    monkeypatch.setattr(compose_ui, "get_rules", lambda: tight)
    html = _checked()
    assert "HR-246" in html
    # Both majors are still on the page for the author to combine — none dropped.
    assert 'value="Types letters and reports"' in html
    assert 'value="Maintains office files"' in html


def test_export_from_the_rendered_page_carries_the_ticks_and_rows() -> None:
    page = _checked()
    action = "/jd-bank/ui/compose/export"
    resp = _post_form(_client(), action, _browser_pairs(page, action))
    assert resp.status_code == 200
    text = extract_text(resp.content, DocumentFormat.DOCX)
    form = get_rules().cupe_form
    chosen = form.checkbox_options["level_of_independence"][1]
    assert f"{form.checkbox_ticked_glyph} {chosen}" in text
    assert "Purges and archives records" in text
    assert "< 1 hour" in text
    assert "35 / 35" in text


def test_a_clone_lands_minor_functions_in_the_minor_rows() -> None:
    spec = FORMS["wjq"]
    answers = WJQAnswers(
        title="Clerk",
        major_functions=[
            FunctionAnswer(
                action_verb="Files", statement="Files records", frequency="daily"
            )
        ],
        minor_functions=[MinorFunctionAnswer(action_verb="Purges", statement="Purges")],
    )
    rows = compose_ui._structured_rows_from_answers(spec, answers)
    assert [r["statement"] for r in rows["minor_functions"]] == ["Purges"]
    assert [r["frequency"] for r in rows["major_functions"]] == ["daily"]


def test_answers_json_round_trips_through_submit_and_export_unchanged() -> None:
    raw = _answers_json_from(_checked())
    assert WJQAnswers.model_validate_json(raw).model_dump_json() == json.dumps(
        json.loads(raw), separators=(",", ":")
    )

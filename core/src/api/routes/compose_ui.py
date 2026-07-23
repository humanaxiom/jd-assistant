"""JD Builder — guided-authoring UI (Phase 5.3).

A server-rendered page under ``/jd-bank/ui/compose/new`` that renders the Phase-5.2
question set as a guided form and shows the Phase-5.1 live compliance panel. Extends
the same Jinja UI that already lives inside the FastAPI ``api`` service (the 4.4d /
4.6c pattern) — no new service, no new runtime dependency.

**Dependency-free, like the review UI** (:mod:`src.api.routes.ui`): the POST body is
``application/x-www-form-urlencoded`` and is parsed from the RAW body with the stdlib
:func:`urllib.parse.parse_qsl` — never FastAPI's ``Form(...)`` / ``request.form()``,
which assert ``python-multipart`` on the installed Starlette.

**Read-only authoring.** Nothing here persists or publishes (NN #1): the page assembles
the answers into a draft (:func:`~src.jd_bank.composer.assemble_jd`), assesses it
(:func:`~src.jd_bank.composer.assess_draft`), and renders the result. Submitting a draft
to the review queue is Phase 5.6. Jinja autoescape is on; no ``|safe`` on the author's
own text.

**Known MVP simplification** (recorded, not hidden): the form collects list sections as
one-item-per-line textareas and does not yet capture per-duty percentage allocations or
per-qualification KSA modifiers — a structured per-field editor is a later task, exactly
as the review-queue edit view (a raw-JSON textarea) is. The live panel honestly surfaces
whatever the validator makes of the current draft.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError

from src.jd_bank.composer import (
    ComposerAnswers,
    DraftAssessment,
    DutyAnswer,
    ModifiedQual,
    assemble_jd,
    assess_draft,
    load_question_set,
)
from src.jd_core.models.quality import SFUSection

router: APIRouter = APIRouter(prefix="/jd-bank/ui/compose")

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

#: Human labels for the sections the question set walks, in ask order. Kept local to
#: the UI (presentation copy), not read from the scoring rulebook.
_SECTION_LABELS: dict[SFUSection, str] = {
    "identification": "1 · Identification",
    "position_summary": "3 · Position Summary",
    "duties": "4 · Duties & Responsibilities",
    "decision_making": "5 · Impact of Decision Making",
    "problem_solving": "6 · Problem Solving",
    "relationships": "7 · Relationships",
    "qualifications": "8 · Qualifications",
    "edi_footer": "9 · SFU boilerplate",
    "additional_context": "10 · Additional context",
}

#: How each ``ComposerAnswers`` target is rendered as a form control and read back.
_SCALAR_TARGETS = {"title", "department", "supervisory"}
_TEXTAREA_TARGETS = {"position_summary", "additional_context"}
_STRING_LIST_TARGETS = {
    "decision_making",
    "problem_solving",
    "internal",
    "external",
    "education",
    "experience",
    "abilities",
}
_MODIFIED_LIST_TARGETS = {"knowledge", "skills"}
_EMPLOYEE_GROUPS = ("apsa", "apex", "poly")

#: state -> the badge class defined in ``_base.html``.
_STATE_BADGE = {"ok": "ok", "needs_attention": "blocked", "empty": "muted"}


def _kind_for(target: str) -> str:
    if target == "employee_group":
        return "select"
    if target == "include_sfu_boilerplate":
        return "checkbox"
    if target in _SCALAR_TARGETS:
        return "text"
    if target in _TEXTAREA_TARGETS:
        return "textarea"
    return "list"  # duties + the string/modified list targets: one item per line


def _lines(value: str) -> list[str]:
    return [line.strip() for line in value.splitlines() if line.strip()]


def _first_values(pairs: list[tuple[str, str]]) -> dict[str, str]:
    values: dict[str, str] = {}
    for key, value in pairs:
        values.setdefault(key, value)
    return values


def _answers_from_form(values: dict[str, str]) -> ComposerAnswers:
    """Build ``ComposerAnswers`` from the submitted form (keyed by answer target).

    May raise :class:`pydantic.ValidationError` (e.g. an over-long field) — the caller
    re-renders the page with the error and assembles nothing."""
    data: dict[str, Any] = {}
    for target in _SCALAR_TARGETS | _TEXTAREA_TARGETS:
        text = values.get(target, "").strip()
        if text:
            data[target] = text
    group = values.get("employee_group", "").strip()
    if group:
        data["employee_group"] = group
    duties = [DutyAnswer(statement=line) for line in _lines(values.get("duties", ""))]
    if duties:
        data["duties"] = duties
    for target in _STRING_LIST_TARGETS:
        items = _lines(values.get(target, ""))
        if items:
            data[target] = items
    for target in _MODIFIED_LIST_TARGETS:
        quals = [ModifiedQual(text=line) for line in _lines(values.get(target, ""))]
        if quals:
            data[target] = quals
    data["include_sfu_boilerplate"] = values.get("include_sfu_boilerplate") == "on"
    return ComposerAnswers(**data)


def _grouped_questions(values: dict[str, str]) -> list[dict[str, Any]]:
    """The question set as ordered section groups, each question carrying its render
    kind and current value (for repopulation on POST)."""
    groups: list[dict[str, Any]] = []
    for question in load_question_set().questions:
        if not groups or groups[-1]["section"] != question.section:
            groups.append(
                {
                    "section": question.section,
                    "label": _SECTION_LABELS.get(question.section, question.section),
                    "questions": [],
                }
            )
        groups[-1]["questions"].append(
            {
                "prompt": question.prompt,
                "hint": question.hint,
                "target": question.target,
                "kind": _kind_for(question.target),
                "value": values.get(question.target, ""),
            }
        )
    return groups


def _context(
    request: Request,
    *,
    values: dict[str, str],
    assessment: DraftAssessment | None,
    error: str | None,
    boilerplate_checked: bool,
) -> dict[str, Any]:
    return {
        "request": request,
        "groups": _grouped_questions(values),
        "employee_groups": _EMPLOYEE_GROUPS,
        "assessment": assessment,
        "error": error,
        "boilerplate_checked": boilerplate_checked,
        "state_badge": _STATE_BADGE,
    }


@router.get("/new", response_class=HTMLResponse)
async def new_draft(request: Request) -> HTMLResponse:
    """The empty guided form (boilerplate defaulted on — required for approval)."""
    return templates.TemplateResponse(
        request,
        "compose_new.html",
        _context(
            request,
            values={},
            assessment=None,
            error=None,
            boilerplate_checked=True,
        ),
    )


@router.post("/new", response_class=HTMLResponse)
async def check_draft(request: Request) -> HTMLResponse:
    """Assemble the submitted answers and re-render the form with the live compliance
    panel. Read-only — nothing is persisted (NN #1)."""
    body = await request.body()
    values = _first_values(parse_qsl(body.decode("utf-8"), keep_blank_values=True))
    checked = values.get("include_sfu_boilerplate") == "on"
    try:
        answers = _answers_from_form(values)
    except ValidationError as exc:
        return templates.TemplateResponse(
            request,
            "compose_new.html",
            _context(
                request,
                values=values,
                assessment=None,
                error=str(exc),
                boilerplate_checked=checked,
            ),
        )
    assessment = assess_draft(assemble_jd(answers))
    return templates.TemplateResponse(
        request,
        "compose_new.html",
        _context(
            request,
            values=values,
            assessment=assessment,
            error=None,
            boilerplate_checked=checked,
        ),
    )

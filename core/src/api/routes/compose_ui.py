"""JD Builder — guided-authoring UI (Phase 5.3).

A server-rendered page under ``/jd-bank/ui/compose/new`` that renders the Phase-5.2
question set as a guided form and shows the Phase-5.1 live compliance panel. Extends
the same Jinja UI that already lives inside the FastAPI ``api`` service (the 4.4d /
4.6c pattern) — no new service, no new runtime dependency.

**Dependency-free, like the review UI** (:mod:`src.api.routes.ui`): the POST body is
``application/x-www-form-urlencoded`` and is read through the ONE shared parser,
:func:`src.api.routes._forms.read_form_pairs` (stdlib :func:`urllib.parse.parse_qsl`
over the raw body) — never FastAPI's ``Form(...)`` / ``request.form()``, which assert
``python-multipart`` on the installed Starlette.

**Read-only authoring.** Nothing here persists or publishes (NN #1): the page assembles
the answers into a draft (:func:`~src.jd_bank.composer.assemble_jd`), assesses it
(:func:`~src.jd_bank.composer.assess_draft`), and renders the result. Submitting a draft
to the review queue is Phase 5.6. Jinja autoescape is on; no ``|safe`` on the author's
own text.

**Structured per-field editors.** Duties and knowledge/skills are STRUCTURED repeatable
rows, not one-item-per-line textareas: a duty row captures its ``action_verb`` (what the
action-verb gate checks) + ``allocation`` (the ``(NN%)`` the allocation gate reads), and
a knowledge/skill row captures its Toolkit proficiency ``modifier`` — the fields the
``ComposerAnswers`` model always carried but a flat textarea dropped. The rows post as
index-aligned parallel arrays (``duty_verb`` × N, …); "add a row" is dependency-free
(a few blank rows padded in), matching the no-client-JS posture of the rest of this UI.
The remaining list sections (decision-making, relationships, education, …) stay
one-item-per-line textareas. The live panel honestly surfaces whatever the validator
makes of the current draft.
"""

from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from neo4j import AsyncDriver
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.db.models import User
from src.api.main import get_session
from src.api.routes._forms import read_form_pairs
from src.api.routes.auth import require_ui_user
from src.api.routes.compose import (
    get_chat_client,
    get_embed_client,
    get_neo4j_driver,
    get_optional_embed_client,
    get_optional_neo4j_driver,
)
from src.jd_bank.composer import (
    ComposerAnswers,
    DraftAssessment,
    DuplicateGuard,
    DutyAnswer,
    ModifiedQual,
    SearchHit,
    SummarySuggestion,
    assemble_jd,
    assess_draft,
    cluster_id_for_source,
    find_related_roles,
    load_clone_answers,
    load_question_set,
    load_role_clone_answers,
    search_similar_jds,
    submit_composed_draft,
    suggest_summary,
)
from src.jd_bank.embeddings.client import EmbedClient
from src.jd_bank.llm.client import ChatClient
from src.jd_core.models.parsed_jd import SFUJobDescription
from src.jd_core.models.quality import SFUSection
from src.jd_core.rules import get_rules
from src.jd_export import render_sfu_docx

logger = logging.getLogger(__name__)

router: APIRouter = APIRouter(prefix="/jd-bank/ui/compose")

#: The OOXML ``.docx`` media type (shared with the JSON export route).
_DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _docx_filename(title: str) -> str:
    """A safe download filename from the JD title (lowercase, hyphenated)."""
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return f"{slug or 'job-description'}.docx"


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
_SCALAR_TARGETS = {"title", "department", "grade", "supervisory"}
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
#: Targets rendered as STRUCTURED repeatable rows (not one-item-per-line textareas),
#: so the fields the models carry but a flat textarea drops are captured: a duty's
#: ``action_verb`` (what the action-verb gate checks) + ``allocation`` (the ``(NN%)``
#: the allocation gate reads), and a knowledge/skill proficiency ``modifier``.
_MODIFIED_LIST_TARGETS = {"knowledge", "skills"}

#: How many structured rows to show: the filled rows plus a few blanks to add more,
#: capped at the model's list max (dependency-free "add a row" without client JS).
_DUTY_MIN_ROWS, _DUTY_MAX_ROWS = 5, 12
_KSA_MIN_ROWS, _KSA_MAX_ROWS = 5, 20
_ROW_SPARE = 3

#: Display order for the Toolkit proficiency scales (a natural progression). The SET
#: of options is still rulebook DATA (``qualifications.yaml`` Parts 5.1/5.2, NN #2) —
#: this only sequences them; any modifier the rulebook adds that is not listed here is
#: appended (sorted) rather than silently dropped (see :func:`_ordered_modifiers`).
_KNOWLEDGE_MODIFIER_ORDER = ("excellent", "working")
_SKILL_MODIFIER_ORDER = ("basic", "intermediate", "advanced", "expert")

#: state -> the badge class defined in ``_base.html``.
_STATE_BADGE = {"ok": "ok", "needs_attention": "blocked", "empty": "muted"}

#: The same map for a draft the gates already PERMIT. When nothing blocks, every
#: remaining finding is advisory BY DEFINITION — so a red "blocked" badge and a "Fix
#: these" imperative on a draft the same panel calls "ready for review" contradict each
#: other, and that contradiction is how a good clone of an approved role reads as
#: broken. (Reported case: cloning the published "AV Systems Analyst" — 89.05/B/ready
#: for review, three `low` nits, all of them present on the JD when HR approved it.)
_APPROVABLE_STATE_BADGE = {"ok": "ok", "needs_attention": "warn", "empty": "muted"}
_APPROVABLE_STATE_LABEL = {
    "ok": "OK",
    "needs_attention": "Suggestion",
    "empty": "Not started",
}

#: A canonical role's lifecycle status -> the label the related-roles panel shows. A
#: DRAFT role is not an approved one, and the panel offers to clone both (the role
#: library already lists drafts, and 1,800-odd roles are drafts today), so it must say
#: which is which rather than let "Start from this role" imply HR signed it off (NN #1).
#: An unmapped/unknown status is labelled as unknown, never guessed — see
#: :data:`~src.jd_bank.composer.duplicates.UNKNOWN_STATUS`.
_ROLE_STATUS_LABEL = {
    "draft": "draft — not yet approved",
    "published": "published",
    "archived": "archived",
}
_ROLE_STATUS_UNKNOWN = "status unavailable"

#: How much of a role title the related-roles panel renders. 21 of the 1,802 canonical
#: titles are whole prose paragraphs ("We are Canada's engaged university…") — a known
#: upstream parser-v3 residue that is cosmetic here but would wreck the panel's layout.
#: DISPLAY ONLY: the data is not touched, and fixing it is not this feature's job.
_ROLE_TITLE_MAX_CHARS = 80

#: state -> a human label for the section table. The raw enum ``needs_attention`` is
#: jargon that tells the author nothing; the panel pairs this with the section's own
#: ``issues`` (rendered underneath) so "what to fix" is right next to the flag.
_STATE_LABEL = {
    "ok": "OK",
    "needs_attention": "Needs attention",
    "empty": "Not started",
}


def _kind_for(target: str) -> str:
    if target == "employee_group":
        return "select"
    if target == "include_sfu_boilerplate":
        return "checkbox"
    if target in _SCALAR_TARGETS:
        return "text"
    if target in _TEXTAREA_TARGETS:
        return "textarea"
    if target == "duties":
        return "duties"  # structured verb / statement / % rows
    if target in _MODIFIED_LIST_TARGETS:
        return "modified"  # structured text + proficiency-modifier rows
    return "list"  # the remaining string-list targets: one item per line


def _lines(value: str) -> list[str]:
    return [line.strip() for line in value.splitlines() if line.strip()]


def _first_values(pairs: list[tuple[str, str]]) -> dict[str, str]:
    values: dict[str, str] = {}
    for key, value in pairs:
        values.setdefault(key, value)
    return values


def _column(pairs: list[tuple[str, str]], key: str) -> list[str]:
    """Every value submitted for ``key``, in document order — the structured rows post
    parallel arrays (``duty_verb`` × N, ``duty_statement`` × N, …) that stay index-
    aligned because ``parse_qsl`` preserves order and each row emits one of each."""
    return [value for k, value in pairs if k == key]


def _at(items: list[str], index: int) -> str:
    return items[index] if index < len(items) else ""


def _ordered_modifiers(available: frozenset[str], order: tuple[str, ...]) -> list[str]:
    """The rulebook's proficiency modifiers in display order — the ``none`` sentinel
    (an ABSENT modifier) dropped, and any modifier the rulebook defines but the display
    order omits appended (sorted) so nothing is ever silently unofferable."""
    known = [m for m in order if m in available and m != "none"]
    extra = sorted(m for m in available if m not in order and m != "none")
    return known + extra


def _duty_row_dicts(pairs: list[tuple[str, str]]) -> list[dict[str, str]]:
    """The submitted duty rows as raw ``{verb, statement, allocation}`` dicts (kept as
    strings so they repopulate the form even when a value fails validation)."""
    verbs = _column(pairs, "duty_verb")
    statements = _column(pairs, "duty_statement")
    allocations = _column(pairs, "duty_allocation")
    count = max(len(verbs), len(statements), len(allocations))
    return [
        {
            "verb": _at(verbs, i),
            "statement": _at(statements, i),
            "allocation": _at(allocations, i),
        }
        for i in range(count)
    ]


def _modified_row_dicts(
    pairs: list[tuple[str, str]], target: str
) -> list[dict[str, str]]:
    """The submitted knowledge/skills rows as raw ``{text, modifier}`` dicts."""
    texts = _column(pairs, f"{target}_text")
    modifiers = _column(pairs, f"{target}_modifier")
    count = max(len(texts), len(modifiers))
    return [
        {"text": _at(texts, i), "modifier": _at(modifiers, i)} for i in range(count)
    ]


def _structured_rows_from_pairs(
    pairs: list[tuple[str, str]],
) -> dict[str, list[dict[str, str]]]:
    return {
        "duties": _duty_row_dicts(pairs),
        "knowledge": _modified_row_dicts(pairs, "knowledge"),
        "skills": _modified_row_dicts(pairs, "skills"),
    }


def _structured_rows_from_answers(
    answers: ComposerAnswers,
) -> dict[str, list[dict[str, str]]]:
    return {
        "duties": [
            {
                "verb": d.action_verb,
                "statement": d.statement,
                "allocation": "" if d.allocation is None else str(d.allocation),
            }
            for d in answers.duties
        ],
        "knowledge": [
            {"text": q.text, "modifier": q.modifier or ""} for q in answers.knowledge
        ],
        "skills": [
            {"text": q.text, "modifier": q.modifier or ""} for q in answers.skills
        ],
    }


def _pad_rows(
    rows: list[dict[str, str]],
    blank: dict[str, str],
    *,
    min_rows: int,
    max_rows: int,
) -> list[dict[str, str]]:
    """The filled rows plus blank rows to add more, capped at the model's list max."""
    padded = list(rows)
    target = min(max_rows, max(min_rows, len(rows) + _ROW_SPARE))
    while len(padded) < target:
        padded.append(dict(blank))
    return padded


def _duty_answers(pairs: list[tuple[str, str]]) -> list[DutyAnswer]:
    """Structured duty rows -> ``DutyAnswer`` list, dropping rows with no statement.

    Raises :class:`ValueError` for a non-numeric allocation (a crafted body — the
    form uses ``<input type=number>``); the caller re-renders with the error."""
    duties: list[DutyAnswer] = []
    for row in _duty_row_dicts(pairs):
        statement = row["statement"].strip()
        if not statement:
            continue
        allocation_text = row["allocation"].strip()
        allocation = int(allocation_text) if allocation_text else None
        duties.append(
            DutyAnswer(
                action_verb=row["verb"].strip(),
                statement=statement,
                allocation=allocation,
            )
        )
    return duties


def _modified_quals(pairs: list[tuple[str, str]], target: str) -> list[ModifiedQual]:
    """Structured knowledge/skills rows -> ``ModifiedQual`` list, dropping empty rows.
    A blank modifier dropdown maps to ``modifier=None`` (an absent proficiency)."""
    quals: list[ModifiedQual] = []
    for row in _modified_row_dicts(pairs, target):
        text = row["text"].strip()
        if not text:
            continue
        quals.append(ModifiedQual(text=text, modifier=row["modifier"].strip() or None))
    return quals


def _answers_from_form(
    values: dict[str, str], pairs: list[tuple[str, str]]
) -> ComposerAnswers:
    """Build ``ComposerAnswers`` from the submitted form: scalar/textarea/string-list
    targets from the collapsed ``values``; duties and knowledge/skills from the
    STRUCTURED parallel-array rows in ``pairs``.

    May raise :class:`pydantic.ValidationError` (e.g. an over-long field) or
    :class:`ValueError` (a non-numeric %-allocation) — the caller re-renders the page
    with the error and assembles nothing."""
    data: dict[str, Any] = {}
    for target in _SCALAR_TARGETS | _TEXTAREA_TARGETS:
        text = values.get(target, "").strip()
        if text:
            data[target] = text
    group = values.get("employee_group", "").strip()
    if group:
        data["employee_group"] = group
    duties = _duty_answers(pairs)
    if duties:
        data["duties"] = duties
    for target in _STRING_LIST_TARGETS:
        items = _lines(values.get(target, ""))
        if items:
            data[target] = items
    for target in _MODIFIED_LIST_TARGETS:
        quals = _modified_quals(pairs, target)
        if quals:
            data[target] = quals
    data["include_sfu_boilerplate"] = values.get("include_sfu_boilerplate") == "on"
    # Not content: the role this draft was cloned from, carried through the form as a
    # hidden field so a Check keeps it (the guard excludes it, and submit/export
    # rebuild from the same answers). A tampered value fails UUID validation and
    # re-renders with the error, like any other bad field.
    cloned_from = values.get("cloned_from_cluster_id", "").strip()
    if cloned_from:
        data["cloned_from_cluster_id"] = cloned_from
    return ComposerAnswers(**data)


def _values_from_answers(answers: ComposerAnswers) -> dict[str, str]:
    """The SCALAR / textarea / string-list form-field view of ``ComposerAnswers`` (the
    inverse of :func:`_answers_from_form` for those targets), so the guided form
    repopulates when the Builder is cloned from an existing JD. The structured sections
    (duties, knowledge, skills) repopulate separately from
    :func:`_structured_rows_from_answers` — verbs, %-allocations and modifiers included,
    nothing dropped."""
    values: dict[str, str] = {}
    for target, scalar in (
        ("title", answers.title),
        ("department", answers.department),
        ("grade", answers.grade),
        ("employee_group", answers.employee_group),
        ("position_summary", answers.position_summary),
        ("supervisory", answers.supervisory),
        ("additional_context", answers.additional_context),
    ):
        if scalar:
            values[target] = scalar
    if answers.cloned_from_cluster_id is not None:
        values["cloned_from_cluster_id"] = str(answers.cloned_from_cluster_id)
    for target, items in (
        ("decision_making", answers.decision_making),
        ("problem_solving", answers.problem_solving),
        ("internal", answers.internal),
        ("external", answers.external),
        ("education", answers.education),
        ("experience", answers.experience),
        ("abilities", answers.abilities),
    ):
        values[target] = "\n".join(items)
    return values


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


def _inclusive_meter(assessment: DraftAssessment | None) -> dict[str, Any]:
    """A live "inclusive language" meter for the panel: the coded / gendered /
    exclusionary findings the validator raised (category ``inclusive_language``), pulled
    OUT of the generic "Fix these" list into a prominent, always-visible check with each
    term's suggested replacement. Deterministic + advisory — it reflects the same
    rulebook lexicon the oracle scores on (``coded_terms.yaml``); it never blocks and
    adds no new decision. ``checked`` is False only before the author runs a check."""
    if assessment is None:
        return {"checked": False, "count": 0, "terms": []}
    terms = [
        {"message": issue.message, "suggestion": issue.suggestion}
        for issue in assessment.report.issues
        if issue.category == "inclusive_language"
    ]
    return {"checked": True, "count": len(terms), "terms": terms}


def _context(
    request: Request,
    *,
    values: dict[str, str],
    assessment: DraftAssessment | None,
    error: str | None,
    boilerplate_checked: bool,
    answers_json: str = "",
    suggestion: SummarySuggestion | None = None,
    structured_rows: dict[str, list[dict[str, str]]] | None = None,
    related_roles: DuplicateGuard | None = None,
) -> dict[str, Any]:
    groups = _grouped_questions(values)
    rules = get_rules()
    rows = structured_rows or {}
    # Filled rows + a few blank rows to add more (capped at each model list max), so the
    # structured editors work without client JS — the same no-dependency posture as the
    # rest of this UI. Repopulation rows come from the caller (raw form pairs on a POST,
    # so they survive a validation error; the source answers on a clone).
    padded_rows = {
        "duties": _pad_rows(
            rows.get("duties", []),
            {"verb": "", "statement": "", "allocation": ""},
            min_rows=_DUTY_MIN_ROWS,
            max_rows=_DUTY_MAX_ROWS,
        ),
        "knowledge": _pad_rows(
            rows.get("knowledge", []),
            {"text": "", "modifier": ""},
            min_rows=_KSA_MIN_ROWS,
            max_rows=_KSA_MAX_ROWS,
        ),
        "skills": _pad_rows(
            rows.get("skills", []),
            {"text": "", "modifier": ""},
            min_rows=_KSA_MIN_ROWS,
            max_rows=_KSA_MAX_ROWS,
        ),
    }
    # The proficiency-scale options — rulebook DATA (qualifications.yaml Parts 5.1/5.2,
    # NN #2), ordered for display; a rulebook change flows straight through here.
    modifier_options = {
        "knowledge": _ordered_modifiers(
            rules.qualifications.knowledge_modifiers, _KNOWLEDGE_MODIFIER_ORDER
        ),
        "skills": _ordered_modifiers(
            rules.qualifications.skill_modifiers, _SKILL_MODIFIER_ORDER
        ),
    }
    # Tag each guidance/finding with the section it belongs to, so the "Still to write"
    # and "Fix these" lists can each link to the offending section's fields. The issue
    # objects in `guidance`/`findings` are the SAME objects held in `sections[].issues`
    # (both come from one checklist entry), so an identity map recovers the section the
    # flat lists dropped. `general`-bucket findings map to a section with no form fields
    # and stay unlinked (filtered by `form_sections` in the template).
    guidance_items: list[dict[str, Any]] = []
    findings_items: list[dict[str, Any]] = []
    if assessment is not None:
        section_of = {
            id(issue): section.section
            for section in assessment.sections
            for issue in section.issues
        }
        guidance_items = [
            {"issue": issue, "section": section_of.get(id(issue))}
            for issue in assessment.guidance
        ]
        findings_items = [
            {"issue": issue, "section": section_of.get(id(issue))}
            for issue in assessment.findings
        ]
    return {
        "request": request,
        "groups": groups,
        "guidance_items": guidance_items,
        "findings_items": findings_items,
        # Section values that have a form anchor below, so the Sections panel only
        # links a section the author can actually jump to (the cross-cutting `general`
        # bucket and pure-boilerplate `about_sfu` have no editable fields).
        "form_sections": {group["section"] for group in groups},
        # The bargaining units the Builder authors — rulebook DATA, not a hardcoded
        # tuple (CLAUDE.md §2). CUPE/WJQ is deliberately absent (HR-194/HR-143): no
        # ratified CUPE bar, so nothing here can score it.
        "employee_groups": rules.segmentation.jdfn_employee_groups,
        # The structured duty/KSA rows (padded with blanks) + their modifier options.
        "structured_rows": padded_rows,
        "modifier_options": modifier_options,
        "assessment": assessment,
        # A prominent, always-visible "inclusive language" meter (coded/gendered terms
        # the validator flagged, with suggestions) — deterministic + advisory.
        "inclusive_meter": _inclusive_meter(assessment),
        # The near-duplicate authoring guard (5.9): the harmonized roles that already
        # look like this draft, RANKED and deliberately score-free (see
        # `composer/duplicates.py` for the measurement that rules a number out).
        # Advisory — it never blocks the submit button.
        #
        # `checked` is False on the paths where nothing was ASKED: before the author's
        # first check, and when `_related_roles_panel` gave up (a client that could not
        # be constructed, a timeout, an outright failure). It is True whenever
        # `find_related_roles` ran to completion — including when its own internal
        # degrade path emptied one half, in which case the panel renders whatever the
        # other half found, or nothing at all if both are empty. Either way an empty
        # panel does not render, so the author is never shown an unverified "all clear".
        "related_roles": (
            related_roles if related_roles is not None else DuplicateGuard()
        ),
        "role_status_label": _ROLE_STATUS_LABEL,
        "role_status_unknown": _ROLE_STATUS_UNKNOWN,
        "role_title_max_chars": _ROLE_TITLE_MAX_CHARS,
        # Provenance carried through the form as a hidden field, so a Check does not
        # forget which role the draft was cloned from (it is what the guard excludes).
        "cloned_from_cluster_id": values.get("cloned_from_cluster_id", ""),
        "error": error,
        "boilerplate_checked": boilerplate_checked,
        # `assessment` is None before the author's first check — no panel renders, so
        # either map is unused; fall back to the strict one rather than assert.
        "state_badge": (
            _APPROVABLE_STATE_BADGE
            if assessment is not None and assessment.approvable
            else _STATE_BADGE
        ),
        "state_label": (
            _APPROVABLE_STATE_LABEL
            if assessment is not None and assessment.approvable
            else _STATE_LABEL
        ),
        # The exact answers this assessment was built from, JSON-encoded, so the
        # "Submit for review" form can carry them in one hidden field and /submit
        # rebuilds the identical draft (no fragile per-field round-trip).
        "answers_json": answers_json,
        # An LLM Position-Summary suggestion (5.5), when the author asked for one — the
        # author reviews it in the prefilled textarea before accepting (NN #1).
        "suggestion": suggestion,
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


async def _close_quietly(*clients: EmbedClient | AsyncDriver | None) -> None:
    """Close every injected client, independently. ``None`` is skipped (the optional
    factories return it when construction failed), and one client's ``close()``
    blowing up must not leak the next — which it did while this was two bare awaits."""
    for client in clients:
        if client is None:
            continue
        try:
            await client.close()
        except Exception:  # noqa: BLE001 — a failed close must not fail the response
            logger.exception("failed to close an injected client")


async def _related_roles_panel(
    jd: SFUJobDescription,
    *,
    session: AsyncSession,
    embed_client: EmbedClient | None,
    neo4j_driver: AsyncDriver | None,
    exclude_cluster_id: UUID | None,
) -> DuplicateGuard:
    """The near-duplicate authoring guard for one Check — best effort, bounded in time,
    and it never costs the compliance panel.

    Three separate ways this is allowed to come back empty, and all of them render the
    panel as ABSENT rather than as a reassuring "no duplicates found":

    * a client could not be CONSTRUCTED (``None`` — see
      :func:`~src.api.routes.compose.get_optional_embed_client`);
    * something raised — :func:`find_related_roles` already absorbs the ordinary
      failures itself, so reaching that ``except`` means something more fundamental
      broke;
    * it took too long. That is the case a ``try``/``except`` cannot cover, and it is
      the dangerous one: the embedding client connects in 5s but then reads for 600s
      with retries, so a host that ACCEPTS and stalls (a wedged GPU, a firewall DROP
      after accept) would pin this request — and the ``AsyncSession`` it has checked
      out of a small pool — for the better part of an hour. A few concurrent Checks
      would then stop the Builder serving at all. ``timeout_seconds`` (HR-197) bounds
      it. Note that ``/compose/search`` and ``/assist`` share the underlying
      no-read-timeout property; those are pre-existing and deliberately NOT changed
      here, as is :class:`EmbedClient`'s global default (the archive embedding runs
      batch thousands of documents and may legitimately want a long read budget).

    Closing the clients is the CALLER's job — this may be cancelled mid-flight, which
    is no place to be awaiting a socket teardown.
    """
    budget = get_rules().dedup.authoring_guard.timeout_seconds
    try:
        return await asyncio.wait_for(
            find_related_roles(
                jd,
                session=session,
                embed_client=embed_client,
                neo4j_driver=neo4j_driver,
                exclude_cluster_id=exclude_cluster_id,
            ),
            timeout=budget,
        )
    except TimeoutError:
        logger.warning(
            "the near-duplicate guard exceeded its %.1fs budget; omitting the panel",
            budget,
        )
        return DuplicateGuard()
    except Exception:  # noqa: BLE001 — advisory: never lose the compliance panel
        logger.exception("the near-duplicate guard failed; omitting the panel")
        return DuplicateGuard()


@router.post("/new", response_class=HTMLResponse)
async def check_draft(
    request: Request,
    embed_client: EmbedClient | None = Depends(get_optional_embed_client),
    neo4j_driver: AsyncDriver | None = Depends(get_optional_neo4j_driver),
    session: AsyncSession = Depends(get_session),
) -> HTMLResponse:
    """Assemble the submitted answers and re-render the form with the live compliance
    panel, plus the advisory near-duplicate guard (5.9). Read-only — nothing is
    persisted (NN #1), and the guard never blocks the submit button.

    The whole body sits under one ``finally`` so the injected clients are closed on
    EVERY path, including the ones that raise before the guard is ever reached (a body
    that is not valid UTF-8 fails at ``decode``, before any ``try`` used to start).
    The clients are OPTIONAL: this route must render its compliance verdict even when
    the embedding/vector stack cannot be constructed at all — see
    :func:`~src.api.routes.compose.get_optional_embed_client`.
    """
    try:
        pairs = await read_form_pairs(request)
        values = _first_values(pairs)
        checked = values.get("include_sfu_boilerplate") == "on"
        # Repopulation rows come from the RAW submitted pairs, so a validation error
        # still shows the author what they typed (never a silently emptied section).
        rows = _structured_rows_from_pairs(pairs)
        try:
            answers = _answers_from_form(values, pairs)
        except (ValidationError, ValueError) as exc:
            return templates.TemplateResponse(
                request,
                "compose_new.html",
                _context(
                    request,
                    values=values,
                    assessment=None,
                    error=str(exc),
                    boilerplate_checked=checked,
                    structured_rows=rows,
                ),
            )
        jd = assemble_jd(answers)
        assessment = assess_draft(jd)
        guard = await _related_roles_panel(
            jd,
            session=session,
            embed_client=embed_client,
            neo4j_driver=neo4j_driver,
            exclude_cluster_id=answers.cloned_from_cluster_id,
        )
        return templates.TemplateResponse(
            request,
            "compose_new.html",
            _context(
                request,
                values=values,
                assessment=assessment,
                error=None,
                boilerplate_checked=checked,
                answers_json=answers.model_dump_json(),
                structured_rows=rows,
                related_roles=guard,
            ),
        )
    finally:
        await _close_quietly(embed_client, neo4j_driver)


@router.post("/assist", response_class=HTMLResponse)
async def assist_draft(
    request: Request,
    client: ChatClient = Depends(get_chat_client),
) -> HTMLResponse:
    """Ask the self-hosted LLM to improve the Position Summary (5.5) from the same
    in-progress guided-form answers, APPLY the suggestion to the summary textarea for
    the author to review, and re-render with the assist panel + the re-scored live
    compliance (validator-as-oracle, NN #3). Decision-support only — nothing
    auto-applies or publishes (NN #1); the author still Checks/Submits. The injected
    client is egress-guarded at construction (NN #5) and always closed."""
    pairs = await read_form_pairs(request)
    values = _first_values(pairs)
    checked = values.get("include_sfu_boilerplate") == "on"
    rows = _structured_rows_from_pairs(pairs)
    try:
        answers = _answers_from_form(values, pairs)
    except (ValidationError, ValueError) as exc:
        await client.close()
        return templates.TemplateResponse(
            request,
            "compose_new.html",
            _context(
                request,
                values=values,
                assessment=None,
                error=str(exc),
                boilerplate_checked=checked,
                structured_rows=rows,
            ),
        )
    # Bound the wait (HR-199). The failure this covers is the one a try/except cannot:
    # a model host that ACCEPTS the request and then stalls, holding this page for the
    # better part of an hour. On giving up the author gets their OWN draft back — the
    # values they typed, not a blank form — because losing half-written work to a
    # wedged GPU is a worse outcome than not getting a suggestion.
    budget = get_rules().rewrite.interactive_timeout_seconds
    try:
        suggestion = await asyncio.wait_for(
            suggest_summary(assemble_jd(answers), client=client), timeout=budget
        )
    except TimeoutError:
        logger.warning(
            "the summary assist exceeded its %.1fs budget; returning the draft", budget
        )
        return templates.TemplateResponse(
            request,
            "compose_new.html",
            _context(
                request,
                values=values,
                assessment=None,
                error=(
                    "The writing assistant took too long to answer, so your draft is "
                    "unchanged. Your work is safe — try Suggest again, or carry on "
                    "and Check compliance without it."
                ),
                boilerplate_checked=checked,
                structured_rows=rows,
            ),
        )
    finally:
        await client.close()
    # Apply the suggestion to the summary the author sees, and carry it in the answers
    # the submit/export forms rebuild from — so accepting is one Check away and the
    # improved draft round-trips intact. The author can still edit it before Checking.
    values["position_summary"] = suggestion.suggested_summary
    applied = answers.model_copy(
        update={"position_summary": suggestion.suggested_summary}
    )
    return templates.TemplateResponse(
        request,
        "compose_new.html",
        _context(
            request,
            values=values,
            assessment=suggestion.assessment,
            error=None,
            boilerplate_checked=checked,
            answers_json=applied.model_dump_json(),
            suggestion=suggestion,
            structured_rows=rows,
        ),
    )


@router.get("/search", response_class=HTMLResponse)
async def search_page(
    request: Request,
    q: str = "",
    embed_client: EmbedClient = Depends(get_embed_client),
    neo4j_driver: AsyncDriver = Depends(get_neo4j_driver),
    session: AsyncSession = Depends(get_session),
) -> HTMLResponse:
    """Semantic search over the embedded archive for a JD to start from (5.4). Renders
    the hits, each linking to :func:`clone_draft`. An empty query just shows the search
    box — no embed/vector round-trip. JDFN-scoped (CUPE/WJQ excluded, HR-143); the
    injected embed + Neo4j clients are closed after use."""
    query = q.strip()
    hits: list[SearchHit] = []
    message: str | None = None
    if query:
        # Bound the wait (HR-198). This route holds a checked-out AsyncSession out of a
        # small pool for the whole call, so an embedding host that ACCEPTS and stalls
        # takes the Builder down with it after only a handful of searches — the failure
        # `connect=5.0` does NOT cover, because the connection succeeds.
        budget = get_rules().embeddings.interactive_timeout_seconds
        try:
            hits = await asyncio.wait_for(
                search_similar_jds(
                    query,
                    embed_client=embed_client,
                    neo4j_driver=neo4j_driver,
                    session=session,
                ),
                timeout=budget,
            )
        except TimeoutError:
            logger.warning(
                "archive search exceeded its %.1fs budget; rendering without hits",
                budget,
            )
            message = (
                "The search took too long to answer, so no results are shown. "
                "Try again in a moment — your search term has been kept."
            )
        finally:
            await embed_client.close()
            await neo4j_driver.close()
    # Prefer cloning the HARMONIZED role: map each hit's source doc to its cluster (if
    # any) so the template links "Start from this" to the reviewed canonical, not the
    # raw archive JD. A singleton (no cluster) keeps the raw-source clone as its option.
    # A `role_title` hit already IS a role and carries its own cluster_id — only the
    # document hits need the lookup.
    role_clusters: dict[UUID, UUID] = {}
    for hit in hits:
        if hit.source_document_id is None:
            continue
        cluster_id = await cluster_id_for_source(session, hit.source_document_id)
        if cluster_id is not None:
            role_clusters[hit.source_document_id] = cluster_id
    return templates.TemplateResponse(
        request,
        "compose_search.html",
        {
            "request": request,
            "query": query,
            "hits": hits,
            "role_clusters": role_clusters,
            "message": message,
        },
    )


def _render_clone(request: Request, answers: ComposerAnswers) -> HTMLResponse:
    """Land the author on a scored, ready-to-edit Builder draft pre-filled from
    ``answers`` (the faithful clone rides in ``answers_json`` so submit/export keep the
    verbs/modifiers the lossy form view drops). Read-only — nothing persists (NN #1).

    Cloning STARTS A NEW compliant JD, so default SFU boilerplate ON regardless of
    whether the source carried it — many archive JDs predate the territorial-footer
    rollout, so inheriting the source's flag would land the author on a draft with
    About-SFU / territorial / EE / the Relationships header all "missing". The author
    can still uncheck it."""
    answers = answers.model_copy(update={"include_sfu_boilerplate": True})
    return templates.TemplateResponse(
        request,
        "compose_new.html",
        _context(
            request,
            values=_values_from_answers(answers),
            assessment=assess_draft(assemble_jd(answers)),
            error=None,
            boilerplate_checked=answers.include_sfu_boilerplate,
            answers_json=answers.model_dump_json(),
            structured_rows=_structured_rows_from_answers(answers),
        ),
    )


@router.get("/clone-role/{cluster_id}", response_class=HTMLResponse)
async def clone_role(
    request: Request,
    cluster_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> HTMLResponse:
    """Pre-fill the Builder from a role's HARMONIZED canonical — the preferred clone
    source now that the archive is transitional (start from the reviewed, cleaned-up
    role, not a raw archive member that may fail the current template).

    404 if the cluster has no canonical — an HTML page for a browser, which this
    docstring already claimed while the route raised a bare ``HTTPException`` and its
    reader got ``{"detail":"no harmonized JD for this role"}``. It is true now because
    :mod:`src.api.errors` made it true for every route at once, rather than because this
    one grew a template of its own."""
    answers = await load_role_clone_answers(session, cluster_id)
    if answers is None:
        raise HTTPException(status_code=404, detail="no harmonized JD for this role")
    return _render_clone(request, answers)


@router.get("/clone/{source_document_id}", response_class=HTMLResponse)
async def clone_draft(
    request: Request,
    source_document_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> HTMLResponse:
    """Pre-fill the Builder from a RAW archive JD (5.4) — the fallback for a singleton
    with no harmonized role (prefer :func:`clone_role` when a role exists). 404 (an HTML
    page for a browser — see :func:`clone_role`) if the document has no parsed JD to
    clone. Read-only — nothing persists (NN #1)."""
    answers = await load_clone_answers(session, source_document_id)
    if answers is None:
        raise HTTPException(status_code=404, detail="no parsed JD to clone")
    return _render_clone(request, answers)


@router.post("/submit")
async def submit_draft(
    request: Request,
    actor: Annotated[User, Depends(require_ui_user)],
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Submit the composed draft into the review queue and land the author on **their
    own** drafts page with a confirmation.

    The answers ride in one hidden ``answers_json`` field (written by the check step);
    this rebuilds the identical draft, persists it as a DRAFT ``canonical_jds`` row
    (:func:`~src.jd_bank.composer.submit_composed_draft`), and commits. Nothing
    publishes (NN #1) — it enters the same queue as any draft.

    **The redirect target is the fix, not a preference** (P0.0). It used to be
    ``/jd-bank/ui/review/{id}``, which is reviewer-or-admin only, while
    ``default_new_user_role`` is ``author`` — so the ordinary case was: the draft
    commits, and its author is bounced onto a raw ``403`` JSON blob with no sign their
    work had saved. ``/my-drafts`` is reachable by whoever just submitted, by
    construction.
    """
    pairs = await read_form_pairs(request)
    values = _first_values(pairs)
    # The author is the AUTHENTICATED user, not a form field.
    author_id = actor.cas_username
    try:
        answers = ComposerAnswers.model_validate_json(values.get("answers_json", ""))
    except ValidationError as exc:
        # The hidden field was produced by our own check step, so this is unexpected;
        # re-render the empty form with the error rather than 500.
        return templates.TemplateResponse(
            request,
            "compose_new.html",
            _context(
                request,
                values={},
                assessment=None,
                error=str(exc),
                boilerplate_checked=True,
            ),
        )
    canonical = await submit_composed_draft(
        session, assemble_jd(answers), author_id=author_id
    )
    await session.commit()
    return RedirectResponse(
        url=f"/jd-bank/ui/my-drafts?submitted={canonical.id}", status_code=303
    )


@router.post("/export")
async def export_draft(request: Request) -> Response:
    """Render the composed draft to the official SFU ``.docx`` and stream it as a
    download. The answers ride in the same hidden ``answers_json`` field the check step
    writes (the submit form uses it too), so the export rebuilds the identical draft.
    Pure rendering — nothing is validated, persisted, or published (NN #1). A tampered
    hidden field re-renders the form with the error rather than 500 (mirrors submit)."""
    values = _first_values(await read_form_pairs(request))
    try:
        answers = ComposerAnswers.model_validate_json(values.get("answers_json", ""))
    except ValidationError as exc:
        return templates.TemplateResponse(
            request,
            "compose_new.html",
            _context(
                request,
                values={},
                assessment=None,
                error=str(exc),
                boilerplate_checked=True,
            ),
        )
    jd = assemble_jd(answers)
    content = render_sfu_docx(jd)
    return Response(
        content=content,
        media_type=_DOCX_MIME,
        headers={
            "Content-Disposition": f'attachment; filename="{_docx_filename(jd.title)}"'
        },
    )

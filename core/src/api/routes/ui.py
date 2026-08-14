"""Server-rendered review UI — a thin HTML transport over the Phase-4.4b review service.

**Transport ONLY**, exactly like ``src.api.routes.jd_bank`` (4.4c): a handler unpacks
the request, calls exactly ONE service function, commits on success, and renders the
result. On a service error it re-renders the SAME detail page with the error and does
**not** commit. No gate/publish/validation logic lives here — the service
(:mod:`src.jd_bank.review.service`) is the only authority (NN #1). A UI handler cannot
approve a blocked draft any more than the JSON route can — the service raises.

**No new runtime dependency.** POST bodies are ``application/x-www-form-urlencoded``
(the default HTML form enctype — no file uploads) and are read through the ONE shared
parser, :func:`src.api.routes._forms.read_form_pairs` — stdlib
:func:`urllib.parse.parse_qsl` over the raw body, never FastAPI's ``Form(...)`` params.
NB: on the installed Starlette (1.3.x) even ``await request.form()`` asserts
``python-multipart`` is present — its ``_get_form`` requires ``parse_options_header``
regardless of content type — so ``request.form()`` is deliberately NOT used here (see
the module deviation note in the 4.4d task report). This module carried its own copy of
that parser until P0.1b-i; the copies had already drifted.

**Structured edit, not raw JSON.** The reviewer edit view is a per-field editor (a
reviewer cannot be asked to hand-edit JSON). :func:`_content_from_form` reconstructs
the COMPLETE :class:`~src.jd_core.models.parsed_jd.SFUJobDescription` content dict from
the form — EVERY field, so editing one section never silently drops another (the failure
that makes a partial editor worse than JSON, incl. per-duty ``how_why``/``frequency``).
The dict is handed to ``service.edit`` unchanged; the service re-validates it
(validator-as-oracle, NN #3) and raises for a bad edit — this module validates nothing.

**Escaping.** Jinja2 autoescape is on by default for ``.html`` templates
(:class:`~fastapi.templating.Jinja2Templates`); every JD text field the templates
render — draft, issues, removed content, and the prefilled edit fields — goes through
the normal ``{{ }}`` escaping. Nothing here uses ``|safe`` on draft text (untrusted).
"""

from __future__ import annotations

import logging
from functools import partial
from pathlib import Path
from typing import Annotated, Any, NamedTuple, get_args
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.db.models import User
from src.api.main import get_session
from src.api.routes._forms import first_value, read_form_pairs
from src.api.routes.auth import require_ui_user
from src.jd_bank.review import (
    CanonicalNotFoundError,
    GateOverrideError,
    IllegalTransitionError,
    MissingReasonError,
    NotApprovableError,
    ReviewPacket,
    StructuralContext,
    service,
)
from src.jd_core.models.bank import MergeProvenance
from src.jd_core.models.parsed_jd import QualificationKind, SFUEmployeeGroup
from src.jd_core.models.quality import GateOverride, GateReason
from src.jd_core.rules import Rules, get_rules

logger = logging.getLogger(__name__)

router: APIRouter = APIRouter(prefix="/jd-bank/ui")

#: The qualification kinds + employee groups the edit dropdowns offer — read off the
#: model's own ``Literal`` types so a schema change flows through automatically.
_QUAL_KINDS: tuple[str, ...] = get_args(QualificationKind)
_EMPLOYEE_GROUPS: tuple[str, ...] = get_args(SFUEmployeeGroup)

#: How many structured rows to show in the edit form: the filled rows plus a few blanks
#: to add more, capped at the model list maxima (dependency-free "add a row", no JS).
_DUTY_MIN_ROWS, _DUTY_MAX_ROWS = 5, 12
_QUAL_MIN_ROWS, _QUAL_MAX_ROWS = 8, 40
_ROW_SPARE = 3

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

# The typed errors a review-service mutation can raise (mirrors
# ``src.api.routes.jd_bank._SERVICE_ERRORS``) PLUS pydantic's ``ValidationError`` — the
# service reconstructs ``SFUJobDescription`` from an edit's ``new_content`` and raises
# it directly (no service-owned wrapper). None of these ever leave anything committed.
_SERVICE_ERRORS: tuple[type[Exception], ...] = (
    CanonicalNotFoundError,
    IllegalTransitionError,
    NotApprovableError,
    GateOverrideError,
    MissingReasonError,
    ValidationError,
)

#: Phase 8.3c — where each SFU template section lives in the Edit form.
#:
#: ⚠ **This map is COMPLETE by test, walked from the ``SFUSection`` literal itself.**
#: Add a section to the model without deciding where it lives here and the build fails —
#: rather than rendering a "fix this ↓" link that jumps nowhere, which is the kind of
#: silently dead control this repo has shipped before and now enumerates from the live
#: artifact.
#:
#: ``general`` is declared ``None`` rather than omitted: it means *the whole document*,
#: so there is no field to jump to. Declaring it makes that an argued decision instead
#: of a gap (the same reason P1.3 gave ``tier`` no default).
#:
#: Only the ANCHOR is a UI concern. Which section a rule belongs to, what that section
#: is called, and the order sections come in are all rulebook data
#: (``rule_catalog.yaml``: ``section``, ``section_labels``, ``section_order``).
_SECTION_ANCHORS: dict[str, str | None] = {
    "about_sfu": "edit-boilerplate",
    "identification": "edit-identification",
    "position_summary": "edit-position_summary",
    "duties": "edit-duties",
    "decision_making": "edit-decision_making",
    "problem_solving": "edit-problem_solving",
    "relationships": "edit-relationships",
    "qualifications": "edit-qualifications",
    # The employment-equity footer is a checkbox in the boilerplate block.
    "edi_footer": "edit-boilerplate",
    "additional_context": "edit-additional_context",
    "general": None,
}


class GateJumpTarget(NamedTuple):
    """One "fix this ↓" link: the rulebook's label for a section, and where it is."""

    label: str
    anchor: str


def gate_jump_targets(gate: GateReason, rules: Rules) -> tuple[GateJumpTarget, ...]:
    """Where a reviewer goes to fix ``gate`` — one link per implicated template section.

    Rulebook-driven end to end: the gate carries the ``rule_ids`` that tripped it, the
    catalog owns each rule's ``section`` and its label, and ``section_order`` fixes the
    order so the same gate never reshuffles its links between drafts.

    Returns ``()`` when there is nothing honest to point at, and a link landing on an
    arbitrary field would misstate what is wrong. Measured over the whole archive, that
    is exactly the two roll-up gates: ``SFU-APPROVE-SCORE-FLOOR`` and
    ``SFU-APPROVE-GRADE-FLOOR`` (15 occurrences each, **zero** carrying ``rule_ids``).
    Every other blocking gate in the archive carries them — 505 of 535 occurrences, so
    the links are the common case, not the exception.

    ``SFU-APPROVE-SEVERITY-FLOOR`` is deliberately NOT in that list even though it reads
    like a roll-up: it names the offending rules, and all 12 live occurrences carry
    them. It exists to catch high-severity findings with **no** ``rule_id`` (the Phase-5
    LLM pass), and in that case it falls out here with no link — which is correct: an
    uncatalogued finding has no section to point at.

    An uncatalogued rule id is skipped rather than raised: a navigation aid never takes
    down the decision page.
    """
    catalog = rules.rule_catalog
    sections = {
        catalog.by_id[rule_id].section
        for rule_id in gate.rule_ids
        if rule_id in catalog.by_id
    }
    return tuple(
        GateJumpTarget(label=catalog.label(section), anchor=anchor)
        for section in catalog.section_order
        if section in sections and (anchor := _SECTION_ANCHORS.get(section))
    )


#: The naming convention a filled override textarea uses on the approve form:
#: ``override_reason__<gate_id>``. Only fields matching this prefix are read as
#: overrides; every other field is ignored.
_OVERRIDE_PREFIX = "override_reason__"


# --- helpers ---------------------------------------------------------------------


def _column(pairs: list[tuple[str, str]], key: str) -> list[str]:
    """Every value submitted for ``key``, in document order — the structured edit rows
    post parallel arrays (``duty_statement`` × N, ``qual_text`` × N, …) that stay
    index-aligned because ``parse_qsl`` (with ``keep_blank_values``) preserves order and
    each row emits one of each."""
    return [v for k, v in pairs if k == key]


def _at(items: list[str], index: int) -> str:
    return items[index] if index < len(items) else ""


def _lines(value: str) -> list[str]:
    return [line.strip() for line in value.splitlines() if line.strip()]


def _scalar_or_none(pairs: list[tuple[str, str]], key: str) -> str | None:
    """A trimmed scalar field, or ``None`` when blank — so clearing an optional field
    really clears it (not stored as an empty string the model would misrepresent)."""
    return first_value(pairs, key).strip() or None


def _duty_dicts(pairs: list[tuple[str, str]]) -> list[dict[str, Any]]:
    """Structured duty rows -> ``SFUDuty``-shaped dicts, dropping statement-less rows.
    ``how_why`` (a per-duty textarea, one item per line) and ``frequency`` round-trip —
    the detail a flat editor would silently drop is preserved."""
    verbs = _column(pairs, "duty_verb")
    statements = _column(pairs, "duty_statement")
    frequencies = _column(pairs, "duty_frequency")
    how_whys = _column(pairs, "duty_how_why")
    count = max(len(verbs), len(statements), len(frequencies), len(how_whys))
    duties: list[dict[str, Any]] = []
    for i in range(count):
        statement = _at(statements, i).strip()
        if not statement:
            continue
        duties.append(
            {
                "action_verb": _at(verbs, i).strip(),
                "statement": statement,
                "how_why": _lines(_at(how_whys, i)),
                "frequency": _at(frequencies, i).strip() or None,
            }
        )
    return duties


def _qual_dicts(pairs: list[tuple[str, str]]) -> list[dict[str, Any]]:
    """Structured qualification rows -> ``SFUQualification``-shaped dicts, dropping
    text-less rows. An invalid ``kind``/``modifier`` is left for the model + validator
    to reject (validator-as-oracle) rather than silently coerced here."""
    texts = _column(pairs, "qual_text")
    kinds = _column(pairs, "qual_kind")
    modifiers = _column(pairs, "qual_modifier")
    count = max(len(texts), len(kinds), len(modifiers))
    quals: list[dict[str, Any]] = []
    for i in range(count):
        text = _at(texts, i).strip()
        if not text:
            continue
        quals.append(
            {
                "text": text,
                "kind": _at(kinds, i).strip() or "ability",
                "modifier": _at(modifiers, i).strip() or None,
            }
        )
    return quals


def _relationships_dict(pairs: list[tuple[str, str]]) -> dict[str, Any] | None:
    """The Relationships section, or ``None`` when the whole section is empty (matching
    the model's ``relationships: None`` default)."""
    supervisory = _scalar_or_none(pairs, "supervisory")
    internal = _lines(first_value(pairs, "rel_internal"))
    external = _lines(first_value(pairs, "rel_external"))
    if not (supervisory or internal or external):
        return None
    return {"supervisory": supervisory, "internal": internal, "external": external}


def _classification_from_form(pairs: list[tuple[str, str]]) -> dict[str, Any] | None:
    """The reviewer-entered grade as a structured classification dict, or ``None`` when
    blank. The scheme is the ``employee_group`` scale (``"unknown"`` if unset); a
    reviewer setting a grade is the authority, so ``source="entered"``. Returned as a
    plain dict — ``service.edit`` re-validates it via ``SFUJobDescription`` (NN #3)."""
    value = first_value(pairs, "grade").strip()
    if not value:
        return None
    group = _scalar_or_none(pairs, "employee_group")
    return {"scheme": group or "unknown", "value": value, "source": "entered"}


def _content_from_form(pairs: list[tuple[str, str]]) -> dict[str, Any]:
    """Reconstruct the COMPLETE ``SFUJobDescription`` content dict from the structured
    edit form. EVERY field is rebuilt, so editing one section never silently drops
    another (the failure mode that makes a partial editor worse than raw JSON). The dict
    is handed to ``service.edit``, which re-validates it via ``SFUJobDescription`` —
    an empty title, a bad enum, an over-long field, etc. raise there (caught by the
    handler), keeping the service the sole validator-as-oracle authority (NN #3)."""
    return {
        "title": first_value(pairs, "title").strip(),
        "position_number": _scalar_or_none(pairs, "position_number"),
        "department": _scalar_or_none(pairs, "department"),
        # The legacy free-string ``grade`` is deprecated (parser noise); the Grade field
        # now drives the STRUCTURED classification (Phase B), so it is cleared here.
        "grade": None,
        "classification": _classification_from_form(pairs),
        "employee_group": _scalar_or_none(pairs, "employee_group"),
        "about_sfu_present": first_value(pairs, "about_sfu_present") == "on",
        "position_summary": _scalar_or_none(pairs, "position_summary"),
        "duties": _duty_dicts(pairs),
        "decision_making": _lines(first_value(pairs, "decision_making")),
        "problem_solving": _lines(first_value(pairs, "problem_solving")),
        "relationships": _relationships_dict(pairs),
        "qualifications": _qual_dicts(pairs),
        "territorial_acknowledgement_present": first_value(
            pairs, "territorial_acknowledgement_present"
        )
        == "on",
        "employment_equity_present": (
            first_value(pairs, "employment_equity_present") == "on"
        ),
        "additional_context": _scalar_or_none(pairs, "additional_context"),
    }


def _parse_overrides(
    pairs: list[tuple[str, str]], *, reviewer_id: str
) -> list[GateOverride]:
    """Build one :class:`GateOverride` per FILLED override textarea on the form.

    A blank (or missing) textarea contributes nothing — never a synthesized reason.
    Which gates are legally overridable is enforced by the service (via
    ``apply_overrides``), not here; this only reads what the reviewer wrote.
    """
    overrides: list[GateOverride] = []
    for key, value in pairs:
        if not key.startswith(_OVERRIDE_PREFIX):
            continue
        gate_id = key[len(_OVERRIDE_PREFIX) :]
        text = value.strip()
        if not text:
            continue
        overrides.append(
            GateOverride(gate_id=gate_id, reviewer=reviewer_id, reason=text)
        )
    return overrides


def _pad_rows(
    rows: list[dict[str, str]],
    blank: dict[str, str],
    *,
    min_rows: int,
    max_rows: int,
) -> list[dict[str, str]]:
    """Filled rows + blank rows to add more, capped at the model's list max."""
    padded = list(rows)
    target = min(max_rows, max(min_rows, len(rows) + _ROW_SPARE))
    while len(padded) < target:
        padded.append(dict(blank))
    return padded


def _edit_view(content: dict[str, Any]) -> dict[str, Any]:
    """The structured edit form's prefill view of a draft's ``content``: scalars and
    joined lists for direct binding, plus padded duty/qualification rows and the
    dropdown option lists. Renders faithfully from the stored dict (missing keys default
    to empty) so the form reflects exactly what is stored — and the reconstruction on
    submit (:func:`_content_from_form`) is its inverse over EVERY field."""
    rel = content.get("relationships") or {}
    duty_rows = [
        {
            "verb": d.get("action_verb", ""),
            "statement": d.get("statement", ""),
            "frequency": d.get("frequency") or "",
            "how_why": "\n".join(d.get("how_why", []) or []),
        }
        for d in content.get("duties", []) or []
    ]
    qual_rows = [
        {
            "text": q.get("text", ""),
            "kind": q.get("kind", "ability"),
            "modifier": q.get("modifier") or "",
        }
        for q in content.get("qualifications", []) or []
    ]
    quals = get_rules().qualifications
    return {
        "content": content,
        "duty_rows": _pad_rows(
            duty_rows,
            {"verb": "", "statement": "", "frequency": "", "how_why": ""},
            min_rows=_DUTY_MIN_ROWS,
            max_rows=_DUTY_MAX_ROWS,
        ),
        "qual_rows": _pad_rows(
            qual_rows,
            {"text": "", "kind": "ability", "modifier": ""},
            min_rows=_QUAL_MIN_ROWS,
            max_rows=_QUAL_MAX_ROWS,
        ),
        "qual_kinds": _QUAL_KINDS,
        "employee_groups": _EMPLOYEE_GROUPS,
        # The proficiency modifiers offered across all kinds — rulebook DATA (NN #2),
        # ``none`` (an ABSENT modifier) dropped in favour of the blank default.
        "modifier_options": sorted(
            (quals.knowledge_modifiers | quals.skill_modifiers) - {"none"}
        ),
        "decision_making": "\n".join(content.get("decision_making", []) or []),
        "problem_solving": "\n".join(content.get("problem_solving", []) or []),
        "rel_internal": "\n".join(rel.get("internal", []) or []),
        "rel_external": "\n".join(rel.get("external", []) or []),
        "supervisory": rel.get("supervisory") or "",
    }


#: How many rows of skill/duty provenance the panel shows before it stops. A reading
#: limit on a display list — not a decision parameter, and it changes no verdict, so
#: it is deliberately not a rulebook knob (contrast HR-195, which bounds what the
#: Builder *retrieves*).
_PROVENANCE_ROWS: int = 8


def _provenance_view(change_log: dict[str, Any] | None) -> MergeProvenance | None:
    """The 4.1 merge provenance for the reviewer, or ``None`` if this draft has none.

    ⚠ **This packet has been computed and persisted since Phase 4.1 and was read by
    NOTHING until P1.2** — not this page, not the library. So a reviewer approving a
    harmonized draft could not see which sources fed it, how many members required a
    skill, or that the education bar came from one member out of ten
    (``seniority_bar_policy: max``, HR-175). The human is the NN #1 control and
    cannot rule on what they cannot see.

    Returns ``None`` for a composed (Builder-authored) draft, which has no merge
    behind it, and for a packet written before a field existed — the model's own
    defaults absorb that, and a malformed packet degrades to "no panel" rather than
    500ing a page whose real job is the approve/reject decision.
    """
    raw = (change_log or {}).get("merge_provenance")
    if not isinstance(raw, dict):
        return None
    try:
        return MergeProvenance.model_validate(raw)
    except ValidationError:
        return None


def _detail_context(
    packet: ReviewPacket,
    *,
    error: str | None = None,
    structure: StructuralContext | None = None,
) -> dict[str, Any]:
    """The template context shared by the GET detail page and every POST re-render.

    ``structure`` (Phase 8.3b) is optional and defaults to ``None``: a POST re-render
    is answering a reviewer's action and must not be delayed or *failed* by a
    navigation aid. The sidebar is simply absent there.
    """
    diff = (packet.change_log or {}).get("harmonization_diff") or {}
    return {
        "packet": packet,
        "error": error,
        "rendered_draft": diff.get("rendered_draft", ""),
        "removed": diff.get("removed", []),
        "provenance": _provenance_view(packet.change_log),
        "provenance_rows": _PROVENANCE_ROWS,
        "edit": _edit_view(packet.content or {}),
        "structure": structure,
        # Bound to the loaded rulebook here so the template never reaches for rules
        # itself — a template is a renderer, not a place decisions are looked up.
        "gate_jump_targets": partial(gate_jump_targets, rules=get_rules()),
    }


def _friendly_error(exc: Exception) -> str:
    """A plain-language message a reviewer can act on, in place of the raw exception
    dump. The page still shows the blocking gates + the Approve/Edit affordances that
    say HOW to resolve it; this is the one-line "what happened + what to do" banner."""
    if isinstance(exc, NotApprovableError):
        return (
            "This draft cannot be published yet — a required gate still blocks it. "
            "Fix the draft in the Edit section below, or (for a gate marked "
            "overridable) waive it with a written reason in the Approve section, then "
            "click Approve again."
        )
    if isinstance(exc, MissingReasonError):
        return (
            "This action requires a written reason — it is recorded in the audit log. "
            "Please add one and try again."
        )
    if isinstance(exc, IllegalTransitionError):
        return (
            "This version is settled, so that action no longer applies to it. A "
            "published JD cannot be approved or rejected again — but it CAN be "
            "updated: use the Edit section to propose a new draft version. An "
            "archived version (rejected, or superseded by a newer one) is kept for "
            "provenance only; open the current version of this role to change it."
        )
    if isinstance(exc, GateOverrideError):
        return f"That override can't be applied: {exc}"
    if isinstance(exc, ValidationError):
        return f"The draft couldn't be saved — a field is invalid: {exc}"
    return str(exc)


async def _rerender_detail_with_error(
    request: Request,
    session: AsyncSession,
    canonical_id: UUID,
    exc: Exception,
) -> HTMLResponse:
    """Re-render the detail page (200) with a plain-language message for ``exc``, after
    a mutation raised and NOTHING was committed. Re-fetches the packet fresh (validator-
    as-oracle) so the blocking-gate list a NotApprovableError describes is visible on
    the page, not just in the banner. If the canonical has vanished, the 404 page shows
    instead — there is nothing left to re-render."""
    packet = await service.get_review_packet(session, canonical_id)
    if packet is None:
        return templates.TemplateResponse(
            request,
            "review_not_found.html",
            {"canonical_id": canonical_id},
            status_code=404,
        )
    return templates.TemplateResponse(
        request,
        "review_detail.html",
        _detail_context(packet, error=_friendly_error(exc)),
        status_code=200,
    )


# --- routes ------------------------------------------------------------------------
#
# NB: the literal "/queue" route MUST be declared before "/review/{canonical_id}" so
# "queue" is never captured as a canonical_id path param (same rule as 4.4c's routes).


@router.get("/queue", response_class=HTMLResponse)
async def queue_view(
    request: Request,
    limit: int | None = None,
    session: AsyncSession = Depends(get_session),
) -> HTMLResponse:
    items = await service.list_review_queue(session, limit=limit)
    return templates.TemplateResponse(request, "review_queue.html", {"items": items})


@router.get("/review/{canonical_id}", response_class=HTMLResponse)
async def detail_view(
    request: Request,
    canonical_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> HTMLResponse:
    packet = await service.get_review_packet(session, canonical_id)
    if packet is None:
        return templates.TemplateResponse(
            request,
            "review_not_found.html",
            {"canonical_id": canonical_id},
            status_code=404,
        )
    return templates.TemplateResponse(
        request,
        "review_detail.html",
        _detail_context(
            packet, structure=await _structure_or_none(session, canonical_id)
        ),
    )


async def _structure_or_none(
    session: AsyncSession, canonical_id: UUID
) -> StructuralContext | None:
    """The 8.3b sidebar, or ``None`` if it could not be built.

    ⚠ **The sidebar must never cost the page.** This route is where a human approves or
    rejects a JD; a *navigation aid* that raises would take that decision surface down
    with it. Found the honest way — adding the call turned 13 unrelated review tests red
    because the page now had a second reason to fail. Degrading to absent (and saying so
    in the log) keeps the failure visible to an operator without hiding the Approve
    button from a reviewer. Same rule as P1.2's assembly panel.
    """
    try:
        return await service.get_structural_context(session, canonical_id)
    except Exception:  # noqa: BLE001 — a navigation aid never breaks the decision page
        logger.warning(
            "could not build the structural context for %s; the review page renders "
            "without the sidebar",
            canonical_id,
            exc_info=True,
        )
        return None


@router.get("/review/{canonical_id}/diff", response_class=HTMLResponse)
async def diff_view(
    request: Request,
    canonical_id: UUID,
    view: str = "split",
    session: AsyncSession = Depends(get_session),
) -> HTMLResponse:
    """Side-by-side "what changed since last approved" for one draft, with word-level
    highlighting (Phase 8.3a) and a ``?view=unified`` whole-JD toggle. 404 if the id is
    unknown; a friendly empty-state (not an error) when the cluster has no earlier
    PUBLISHED version to diff against (``get_version_diff`` returns ``None``).

    ``view`` is a plain ``str`` normalized here, deliberately NOT a ``Literal``: on a UI
    surface a validation failure would answer a raw ``422`` JSON blob, which is the
    P0.0 defect class — a human handed a machine error. An unrecognised value falls back
    to the split view instead.
    """
    packet = await service.get_review_packet(session, canonical_id)
    if packet is None:
        return templates.TemplateResponse(
            request,
            "review_not_found.html",
            {"canonical_id": canonical_id},
            status_code=404,
        )
    diff = await service.get_version_diff(session, canonical_id)
    return templates.TemplateResponse(
        request,
        "review_diff.html",
        {
            "request": request,
            "packet": packet,
            "diff": diff,
            "unified": view == "unified",
        },
    )


@router.post("/review/{canonical_id}/approve")
async def approve_action(
    request: Request,
    canonical_id: UUID,
    actor: Annotated[User, Depends(require_ui_user)],
    session: AsyncSession = Depends(get_session),
) -> Response:
    pairs = await read_form_pairs(request)
    # The reviewer is the AUTHENTICATED user (NN #1 attribution), not a form field.
    reviewer_id = actor.cas_username
    try:
        overrides = _parse_overrides(pairs, reviewer_id=reviewer_id)
        await service.approve(
            session, canonical_id, reviewer_id=reviewer_id, overrides=overrides
        )
    except _SERVICE_ERRORS as exc:
        return await _rerender_detail_with_error(request, session, canonical_id, exc)
    await session.commit()
    return RedirectResponse(url="/jd-bank/ui/queue", status_code=303)


@router.post("/review/{canonical_id}/reject")
async def reject_action(
    request: Request,
    canonical_id: UUID,
    actor: Annotated[User, Depends(require_ui_user)],
    session: AsyncSession = Depends(get_session),
) -> Response:
    pairs = await read_form_pairs(request)
    reviewer_id = actor.cas_username
    reason = first_value(pairs, "reason")
    try:
        await service.reject(
            session, canonical_id, reviewer_id=reviewer_id, reason=reason
        )
    except _SERVICE_ERRORS as exc:
        return await _rerender_detail_with_error(request, session, canonical_id, exc)
    await session.commit()
    return RedirectResponse(url="/jd-bank/ui/queue", status_code=303)


@router.post("/review/{canonical_id}/edit")
async def edit_action(
    request: Request,
    canonical_id: UUID,
    actor: Annotated[User, Depends(require_ui_user)],
    session: AsyncSession = Depends(get_session),
) -> Response:
    pairs = await read_form_pairs(request)
    reviewer_id = actor.cas_username
    reason = first_value(pairs, "reason")
    # Reconstruct the FULL JD dict from the structured fields; the service re-validates
    # it via SFUJobDescription (validator-as-oracle, NN #3) and raises a ValidationError
    # for a bad edit (empty title, bad enum, over-long field) — caught below, nothing
    # committed. No raw-JSON parsing: a reviewer never hand-edits JSON.
    new_content = _content_from_form(pairs)
    try:
        edited = await service.edit(
            session,
            canonical_id,
            reviewer_id=reviewer_id,
            new_content=new_content,
            reason=reason,
        )
    except _SERVICE_ERRORS as exc:
        return await _rerender_detail_with_error(request, session, canonical_id, exc)
    await session.commit()
    return RedirectResponse(url=f"/jd-bank/ui/review/{edited.id}", status_code=303)

"""Server-rendered, READ-ONLY dashboards over committed pipeline artifacts.

Phase 4.6c slice 1: the "Archive Baseline" page — the first of several read-only
dashboards. It is kept in its OWN router module, separate from the mutation UI
(:mod:`src.api.routes.ui`), precisely because it has no authority: it does not touch the
DB, calls no service that mutates, runs no gate/publish/validation logic. It reads one
committed JSON artifact and renders it.

**Never a hardcoded headline number.** Every figure the templates show — file counts,
approval rates, medians, grade distributions, era bands — is read out of
``docs/baseline/summary.json`` at request time via :func:`load_baseline_summary`. The
value of this page is that it replaces "trust my claims" with "here is the artifact's
own number"; a literal ``78.6`` in a template would defeat its entire purpose (and
``tests/unit/test_dashboard.py`` pins the numbers to a fixture to prove it).

**Graceful when the artifact is absent.** If the summary is missing or unreadable (for
instance the baseline has not been generated, or ``docs/`` is not mounted into this
container), the page renders a clean empty-state — HTTP 200, never an unhandled 500.

**The 874-JD current-practice cohort is the HEADLINE.** As of Phase 4.6c the aggregator
emits it as a single cross-cutting segment (``dimension="cohort",
value="current_practice"``; see ``baseline.aggregate.summarise`` /
``current_practice_cohort``), so its numbers — n, approval rate, median, grades — are IN
the committed ``summary.json`` and this page reads them like any other figure, never
hardcodes them. This is the population the approval bar is actually ratified against
(``docs/baseline/README.md``: "the bar's actual trial"), so it renders FIRST; the
whole-archive number is demoted below it under its "category error, never quote"
warning, and the ``current`` ERA band stays labelled a *date* band, not the cohort. An
older ``summary.json`` generated before the cohort segment existed simply has no such
segment — the page then shows a "regenerate with ``make baseline``" hint, not a crash.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError

from src.jd_bank.baseline.models import BaselineSummary, SegmentStats
from src.jd_core.models.quality import JDGrade
from src.settings import get_settings

router: APIRouter = APIRouter(prefix="/jd-bank/ui/dashboard")

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

#: Grades in report order, so an empty cell renders as 0 rather than vanishing.
_GRADES: tuple[JDGrade, ...] = ("A", "B", "C", "D", "F")

#: Era bands in chronological order (``summary.json`` stores them alphabetically).
_ERA_ORDER: tuple[str, ...] = ("old", "transition", "new", "current")

#: Template facets in report order; ``unknown`` (never-parsed) last.
_TEMPLATE_ORDER: tuple[str, ...] = ("jdfn", "wjq", "unknown")


# --- loader ------------------------------------------------------------------------


def get_baseline_summary_path() -> Path:
    """Where the committed baseline summary lives, as a FastAPI dependency so a test can
    override it with :attr:`app.dependency_overrides` (as the review UI overrides
    ``get_session``). Defaults to the configured path; the app is expected to bind
    ``docs/`` read-only into the container at that location."""
    return Path(get_settings().baseline_summary_path)


def load_baseline_summary(path: Path) -> BaselineSummary | None:
    """Parse ``summary.json`` into the SAME validated model the baseline runner writes.

    Returns ``None`` — never raises — when the artifact is absent or unreadable (missing
    file, unmounted ``docs/``, truncated/corrupt JSON, or a schema that no longer
    validates). The caller renders the empty-state for ``None``. Read-only: this opens
    the file, nothing else.
    """
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        return BaselineSummary.model_validate_json(raw)
    except ValidationError:
        return None


# --- view helpers ------------------------------------------------------------------


def _segment(
    summary: BaselineSummary, *, dimension: str, value: str, population: str = "all"
) -> SegmentStats | None:
    """The one (population x dimension x value) slice, or ``None`` if the artifact has
    no such segment (e.g. a format/era absent from this run)."""
    for seg in summary.segments:
        if (
            seg.population == population
            and seg.dimension == dimension
            and seg.value == value
        ):
            return seg
    return None


def _segment_view(seg: SegmentStats | None) -> dict[str, Any] | None:
    """A flat, template-friendly view of one segment — every number lifted straight from
    the artifact. Grade bars are expressed as a percentage of the segment's own graded
    total so the template needs no arithmetic (and cannot divide by zero)."""
    if seg is None:
        return None
    grades = dict(seg.grades)
    grade_total = sum(grades.values())
    grade_rows = [
        {
            "grade": g,
            "count": grades.get(g, 0),
            "pct": (grades.get(g, 0) / grade_total * 100.0) if grade_total else 0.0,
        }
        for g in _GRADES
    ]
    return {
        "value": seg.value,
        "n_files": seg.n_files,
        "n_scored": seg.n_scored,
        "n_skipped": seg.n_skipped,
        "approved": seg.approved,
        "approval_rate": seg.approval_rate,
        "median": seg.score.median if seg.score is not None else None,
        "mean": seg.score.mean if seg.score is not None else None,
        "grade_rows": grade_rows,
        "grade_total": grade_total,
    }


def _dashboard_context(summary: BaselineSummary) -> dict[str, Any]:
    eras = [
        view
        for value in _ERA_ORDER
        if (view := _segment_view(_segment(summary, dimension="era", value=value)))
    ]
    templates_facet = [
        view
        for value in _TEMPLATE_ORDER
        if (view := _segment_view(_segment(summary, dimension="template", value=value)))
    ]
    return {
        "summary": summary,
        # The current-practice cohort is the HEADLINE — the population the approval bar
        # is actually ratified against (README: "the bar's actual trial"). One single
        # cross-cutting segment (Phase 4.6c). ``None`` when read from an OLDER
        # summary.json that predates the cohort segment — the template then shows a
        # regenerate hint rather than crashing.
        "cohort": _segment_view(
            _segment(summary, dimension="cohort", value="current_practice")
        ),
        "overall": _segment_view(_segment(summary, dimension="all", value="all")),
        "eras": eras,
        "templates": templates_facet,
    }


# --- routes ------------------------------------------------------------------------


@router.get("", response_class=HTMLResponse)
async def dashboard_index(request: Request) -> HTMLResponse:
    """The read-only dashboard index. A static list today (baseline only); dedup and
    cluster dashboards slot in beside it as later slices land."""
    pages = [
        {
            "href": "/jd-bank/ui/dashboard/baseline",
            "title": "Archive baseline",
            "blurb": "The Phase-2.5 quality baseline over all 14,565 archived JDs — "
            "scores, grades, approval rates and provenance, straight from "
            "docs/baseline/summary.json.",
        },
    ]
    return templates.TemplateResponse(request, "dashboard_index.html", {"pages": pages})


@router.get("/baseline", response_class=HTMLResponse)
async def baseline_dashboard(
    request: Request,
    summary_path: Path = Depends(get_baseline_summary_path),
) -> HTMLResponse:
    """Render the archive baseline from the committed artifact, or a clean empty-state
    when it is absent/unreadable (HTTP 200 either way — never a 500)."""
    summary = load_baseline_summary(summary_path)
    if summary is None:
        return templates.TemplateResponse(
            request, "dashboard_baseline.html", {"summary": None}
        )
    return templates.TemplateResponse(
        request, "dashboard_baseline.html", _dashboard_context(summary)
    )

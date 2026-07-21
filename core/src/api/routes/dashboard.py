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

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError

from src.jd_bank.baseline.models import BaselineSummary, SegmentStats
from src.jd_bank.cluster.report import ClusterSummary
from src.jd_bank.dedup.models import DedupReport
from src.jd_bank.dedup.near.report import NearDupSummary
from src.jd_bank.dedup.role.report import RoleEquivSummary
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

#: Percentile keys in ascending order (the artifacts store them unordered).
_PCTL_ORDER: tuple[str, ...] = ("p10", "p50", "p90", "p99", "max")


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
        {
            "href": "/jd-bank/ui/dashboard/dedup",
            "title": "Deduplication (Tier 1/2/3)",
            "blurb": "Exact, near-duplicate and role-equivalence findings over the "
            "archive — redundancy, edges, thresholds and provenance, from "
            "docs/dedup/{summary,near-dup-summary,role-equiv-summary}.json.",
        },
        {
            "href": "/jd-bank/ui/dashboard/clusters",
            "title": "Role clusters",
            "blurb": "The Phase-3.5 role-clustering report — cluster count, coverage, "
            "size distribution, tier contribution and cross-department reach, from "
            "docs/cluster/cluster-summary.json.",
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


# --- dedup (Tier 1/2/3) + clusters: paths, loaders, views (Phase 4.6c slices 2+3) ---
#
# Same discipline as the baseline page above: one committed artifact per finding, read
# into the SAME validated model its runner writes, at request time — never a hardcoded
# number — and a clean HTTP-200 empty-state (never a 500) when an artifact is
# absent/corrupt. Each path is its own FastAPI dependency so a unit test overrides it to
# a fixture; the dedup page loads three INDEPENDENTLY so a missing tier degrades that
# tier alone and never blanks the whole page.


def get_dedup_summary_path() -> Path:
    """Where the committed Tier-1 exact-dedup summary lives (``make dedup``)."""
    return Path(get_settings().dedup_summary_path)


def get_near_dup_summary_path() -> Path:
    """Where the committed Tier-2 near-dup summary lives (``make near-dup``)."""
    return Path(get_settings().near_dup_summary_path)


def get_role_equiv_summary_path() -> Path:
    """Where the committed Tier-3 role-equiv summary lives (``make dedup-role``)."""
    return Path(get_settings().role_equiv_summary_path)


def get_cluster_summary_path() -> Path:
    """Where the committed clustering summary lives (``make cluster``)."""
    return Path(get_settings().cluster_summary_path)


def load_dedup_summary(path: Path) -> DedupReport | None:
    """Parse ``docs/dedup/summary.json`` into the same model the Tier-1 report writes.
    ``None`` (never raises) when absent/unreadable/corrupt — the caller empty-states."""
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        return DedupReport.model_validate_json(raw)
    except ValidationError:
        return None


def load_near_dup_summary(path: Path) -> NearDupSummary | None:
    """Parse ``near-dup-summary.json`` into the Tier-2 report model, or ``None``."""
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        return NearDupSummary.model_validate_json(raw)
    except ValidationError:
        return None


def load_role_equiv_summary(path: Path) -> RoleEquivSummary | None:
    """Parse ``role-equiv-summary.json`` into the Tier-3 report model, or ``None``."""
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        return RoleEquivSummary.model_validate_json(raw)
    except ValidationError:
        return None


def load_cluster_summary(path: Path) -> ClusterSummary | None:
    """Parse ``cluster-summary.json`` into the clustering report model, or ``None``."""
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        return ClusterSummary.model_validate_json(raw)
    except ValidationError:
        return None


def _bar_rows(items: list[tuple[str, int]]) -> list[dict[str, Any]]:
    """CSS-width bar rows: ``label``, ``count`` and ``pct`` of the LARGEST count (so the
    biggest bar is full width and the template needs no arithmetic / cannot divide by
    zero). Order is preserved from ``items``."""
    top = max((count for _, count in items), default=0)
    return [
        {"label": label, "count": count, "pct": (count / top * 100.0) if top else 0.0}
        for label, count in items
    ]


def _size_bars(dist: Mapping[int, int]) -> list[dict[str, Any]]:
    """A size distribution (int size -> count) as bars, smallest size first."""
    return _bar_rows([(str(size), dist[size]) for size in sorted(dist)])


def _count_bars(dist: Mapping[str, int]) -> list[dict[str, Any]]:
    """A labelled distribution (family/tier -> count) as bars, biggest count first."""
    items = sorted(dist.items(), key=lambda kv: (-kv[1], kv[0]))
    return _bar_rows(items)


def _pctl_rows(pctl: Mapping[str, float]) -> list[dict[str, Any]]:
    """Percentile rows (p10..max) in order — each a 0..1 score, so ``pct`` = value * 100
    drives a CSS-width bar and ``value`` is shown alongside."""
    return [
        {"label": key, "value": pctl[key], "pct": pctl[key] * 100.0}
        for key in _PCTL_ORDER
        if key in pctl
    ]


def _tier1_view(report: DedupReport) -> dict[str, Any]:
    return {"r": report, "size_bars": _size_bars(report.group_size_distribution)}


def _tier2_view(report: NearDupSummary) -> dict[str, Any]:
    return {"r": report, "jaccard_rows": _pctl_rows(report.jaccard_percentiles)}


def _tier3_view(report: RoleEquivSummary) -> dict[str, Any]:
    return {
        "r": report,
        "score_rows": _pctl_rows(report.score_percentiles),
        "family_bars": _count_bars(report.family_distribution),
    }


def _cluster_view(report: ClusterSummary) -> dict[str, Any]:
    return {
        "r": report,
        "size_bars": _size_bars(report.size_distribution),
        "family_bars": _count_bars(report.family_distribution),
        "tier_bars": _count_bars(report.tier_contribution),
    }


@router.get("/dedup", response_class=HTMLResponse)
async def dedup_dashboard(
    request: Request,
    tier1_path: Path = Depends(get_dedup_summary_path),
    tier2_path: Path = Depends(get_near_dup_summary_path),
    tier3_path: Path = Depends(get_role_equiv_summary_path),
) -> HTMLResponse:
    """The three dedup tiers on one page (Tier 1 exact / Tier 2 near-dup / Tier 3
    role-equivalence), each read from its own committed artifact. HTTP 200 always: a
    missing/corrupt tier shows that tier's empty-state, the others still render."""
    tier1 = load_dedup_summary(tier1_path)
    tier2 = load_near_dup_summary(tier2_path)
    tier3 = load_role_equiv_summary(tier3_path)
    context: dict[str, Any] = {
        "tier1": _tier1_view(tier1) if tier1 is not None else None,
        "tier2": _tier2_view(tier2) if tier2 is not None else None,
        "tier3": _tier3_view(tier3) if tier3 is not None else None,
    }
    return templates.TemplateResponse(request, "dashboard_dedup.html", context)


@router.get("/clusters", response_class=HTMLResponse)
async def clusters_dashboard(
    request: Request,
    summary_path: Path = Depends(get_cluster_summary_path),
) -> HTMLResponse:
    """The Phase-3.5 role-clustering report from its committed artifact, or a clean
    empty-state when it is absent/unreadable (HTTP 200 either way — never a 500)."""
    summary = load_cluster_summary(summary_path)
    context: dict[str, Any] = {
        "cluster": _cluster_view(summary) if summary is not None else None
    }
    return templates.TemplateResponse(request, "dashboard_clusters.html", context)

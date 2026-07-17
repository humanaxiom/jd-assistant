"""The committed Phase-3.5 artifacts: ``cluster-summary.json`` (counts + stamps, never
document text), ``cluster-report.csv`` (one row per cluster, the ones needing HR eyes
FIRST) and ``cluster-members.csv`` (one row per cluster member). All three carry counts,
labels and archive filenames ONLY — the same class of data ``docs/dedup/`` commits
— never a line of JD body text.

The report is an "eyeball pass": it ships the clusters an HR reviewer should look at,
ordered so the risky ones (a cohesion-cap violation, a cross-group or cross-department
merge, high drift, sheer size, a restricted title) surface at the top, and it leaves an
empty ``human_verdict`` column for the reviewer to fill. It prejudges nothing.
"""

from __future__ import annotations

import csv
import datetime as dt
import json
from collections.abc import Mapping, Sequence
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from src.jd_bank.cluster.models import ClusteringResult, ClusterRecord
from src.jd_core.models.bank import DriftLevel

#: Total order over drift levels, for the "high drift first" report ordering.
_DRIFT_RANK: Mapping[DriftLevel, int] = {"aligned": 0, "minor": 1, "major": 2}

#: How multi-valued cells (departments, bands, tiers, violations) are joined in a CSV.
_CELL_SEP = "|"


class ClusterSummary(BaseModel):
    """The committed clustering finding — counts and stamps. Filenames + per-cluster
    detail live in the two CSVs; this artifact never carries document content."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source: str
    generated_at: dt.datetime
    rules_version: str
    cluster_stamp: str
    edge_method_stamps: tuple[str, ...]

    documents_seen: int = Field(ge=0)
    documents_signed: int = Field(ge=0)
    documents_unsignable: int = Field(ge=0)
    documents_with_vector: int | None = None

    singletons: int = Field(ge=0)
    clustered_documents: int = Field(ge=0)
    coverage_rate: float = Field(ge=0.0, le=1.0)

    edges_considered: int = Field(ge=0)
    edges_admitted: int = Field(ge=0)
    tier_excluded: int = Field(ge=0)
    role_below_min: int = Field(ge=0)
    band_vetoed: int = Field(ge=0)
    group_vetoed: int = Field(ge=0)
    exact_synthesized: int = Field(ge=0)

    cluster_count: int = Field(ge=0)
    largest_cluster: int = Field(ge=0)
    size_distribution: Mapping[int, int] = Field(default_factory=dict)
    cross_department_clusters: int = Field(ge=0)
    cross_group_clusters: int = Field(ge=0)
    restricted_touching_clusters: int = Field(ge=0)
    flagged_clusters: int = Field(ge=0)
    violation_counts: Mapping[str, int] = Field(default_factory=dict)
    tier_contribution: Mapping[str, int] = Field(default_factory=dict)

    cluster_tiers: tuple[str, ...]
    cluster_role_equiv_min: float = Field(ge=0.0, le=1.0)
    cluster_max_band_spread: int = Field(ge=0)
    cluster_group_homogeneous: bool
    cluster_max_size: int = Field(gt=0)
    cluster_representative_policy: str

    family_distribution: Mapping[str, int] = Field(default_factory=dict)


def build_cluster_summary(
    result: ClusteringResult,
    *,
    source: str,
    rules_version: str,
    generated_at: dt.datetime | None = None,
) -> ClusterSummary:
    """The committed summary from one :func:`~src.jd_bank.cluster.runner.run_clustering`
    result. Pure — no I/O."""
    return ClusterSummary(
        source=source,
        generated_at=generated_at or dt.datetime.now(dt.UTC),
        rules_version=rules_version,
        cluster_stamp=result.cluster_stamp,
        edge_method_stamps=result.edge_method_stamps,
        documents_seen=result.documents_seen,
        documents_signed=result.documents_signed,
        documents_unsignable=result.documents_unsignable,
        documents_with_vector=result.documents_with_vector,
        singletons=result.singletons,
        clustered_documents=result.clustered_documents,
        coverage_rate=result.coverage_rate,
        edges_considered=result.edges_considered,
        edges_admitted=result.edges_admitted,
        tier_excluded=result.tier_excluded,
        role_below_min=result.role_below_min,
        band_vetoed=result.band_vetoed,
        group_vetoed=result.group_vetoed,
        exact_synthesized=result.exact_synthesized,
        cluster_count=result.cluster_count,
        largest_cluster=result.largest_cluster,
        size_distribution=result.size_distribution,
        cross_department_clusters=result.cross_department_clusters,
        cross_group_clusters=result.cross_group_clusters,
        restricted_touching_clusters=result.restricted_touching_clusters,
        flagged_clusters=result.flagged_clusters,
        violation_counts=result.violation_counts,
        tier_contribution=result.tier_contribution,
        cluster_tiers=result.cluster_tiers,
        cluster_role_equiv_min=result.cluster_role_equiv_min,
        cluster_max_band_spread=result.cluster_max_band_spread,
        cluster_group_homogeneous=result.cluster_group_homogeneous,
        cluster_max_size=result.cluster_max_size,
        cluster_representative_policy=result.cluster_representative_policy,
        family_distribution=result.family_distribution,
    )


def write_summary(summary: ClusterSummary, path: Path) -> Path:
    """Write ``summary`` as pretty, sorted JSON, creating parent dirs as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(summary.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def report_sort_key(record: ClusterRecord) -> tuple[object, ...]:
    """Order clusters so the ones needing HR eyes surface FIRST: a cohesion violation,
    then a cross-group merge, then cross-department, then high drift, then sheer size,
    then a restricted title — ties broken by ``cluster_id`` for determinism."""
    return (
        not record.constraint_violations,
        not record.cross_group,
        not record.cross_department,
        -_DRIFT_RANK[record.drift_level_max],
        -record.member_count,
        not record.has_restricted,
        str(record.cluster_id),
    )


def ordered_records(result: ClusteringResult) -> list[ClusterRecord]:
    """The clusters in report order (needs-eyes-first)."""
    return sorted(result.clusters, key=report_sort_key)


_REPORT_COLUMNS = [
    "cluster_id",
    "label",
    "member_count",
    "distinct_titles",
    "departments",
    "cross_department",
    "employee_groups",
    "cross_group",
    "family_band_spread",
    "bands",
    "has_restricted",
    "drift_level_max",
    "drift_major_count",
    "tiers",
    "min_edge_score",
    "constraint_violations",
    "representative_filename",
    "human_verdict",
]

_MEMBER_COLUMNS = [
    "cluster_id",
    "filename",
    "title",
    "department",
    "employee_group",
    "family",
    "band",
    "restricted",
    "is_representative",
    "drift_vs_representative",
]


def write_report_csv(records: Sequence[ClusterRecord], path: Path) -> Path:
    """One row per cluster, needs-eyes-first, with an EMPTY ``human_verdict`` column for
    the reviewer. ``records`` must already be in report order (:func:`ordered_records`).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(_REPORT_COLUMNS)
        for r in records:
            writer.writerow(
                [
                    str(r.cluster_id),
                    r.label,
                    r.member_count,
                    r.distinct_titles,
                    _CELL_SEP.join(r.departments),
                    str(r.cross_department),
                    _CELL_SEP.join(r.employee_groups),
                    str(r.cross_group),
                    "" if r.family_band_spread is None else r.family_band_spread,
                    _CELL_SEP.join(str(b) for b in r.bands),
                    str(r.has_restricted),
                    r.drift_level_max,
                    r.drift_major_count,
                    _CELL_SEP.join(r.tiers),
                    f"{r.min_edge_score:.4f}",
                    _CELL_SEP.join(r.constraint_violations),
                    r.representative_filename or "",
                    "",
                ]
            )
    return path


def write_members_csv(records: Sequence[ClusterRecord], path: Path) -> Path:
    """One row per (cluster, member). ``records`` in report order; members in each
    record's own canonical order."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(_MEMBER_COLUMNS)
        for r in records:
            for m in r.members:
                writer.writerow(
                    [
                        str(r.cluster_id),
                        m.filename or "",
                        m.title,
                        m.department or "",
                        m.employee_group or "",
                        m.family,
                        "" if m.band is None else m.band,
                        str(m.restricted),
                        str(m.is_representative),
                        m.drift_vs_representative,
                    ]
                )
    return path

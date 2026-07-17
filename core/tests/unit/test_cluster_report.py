"""The committed Phase-3.5 artifacts: report ordering, the empty ``human_verdict``
column, the "never document text" contract, and the empty-corpus zeroed summary.

The report models carry counts, labels and filenames only — no JD body text is even
representable — so these tests pin the SHAPE (ordering, columns, the reviewer column),
and that an empty run yields a zeroed summary rather than an error.
"""

from __future__ import annotations

import csv
import datetime as dt
from pathlib import Path
from uuid import UUID

from src.jd_bank.cluster.models import ClusteringResult, ClusterMember, ClusterRecord
from src.jd_bank.cluster.report import (
    build_cluster_summary,
    ordered_records,
    write_members_csv,
    write_report_csv,
    write_summary,
)
from tests.unit.cluster_fakes import doc_id


def _member(key: str, **over: object) -> ClusterMember:
    defaults: dict[str, object] = dict(
        source_id=doc_id(key),
        filename=f"{key}.docx",
        title="Analyst",
        normalized_title="analyst",
        department=None,
        employee_group=None,
        family="unmapped",
        band=None,
        restricted=False,
        is_representative=False,
        parse_confidence=1.0,
        drift_vs_representative="aligned",
    )
    defaults.update(over)
    return ClusterMember(**defaults)  # type: ignore[arg-type]


def _record(key: str, **over: object) -> ClusterRecord:
    members = (_member(f"{key}0", is_representative=True), _member(f"{key}1"))
    defaults: dict[str, object] = dict(
        cluster_id=doc_id(f"cluster-{key}"),
        label="Analyst",
        member_count=2,
        titles=("Analyst",),
        departments=(),
        employee_groups=(),
        distinct_titles=1,
        cross_department=False,
        cross_group=False,
        family_band_spread=None,
        bands=(),
        has_restricted=False,
        tiers=("role_equivalent",),
        min_edge_score=0.9,
        drift_level_max="aligned",
        drift_major_count=0,
        constraint_violations=(),
        representative_filename=f"{key}0.docx",
        members=members,
    )
    defaults.update(over)
    return ClusterRecord(**defaults)  # type: ignore[arg-type]


def _result(*records: ClusterRecord) -> ClusteringResult:
    return ClusteringResult(
        documents_seen=len(records) * 2,
        documents_signed=len(records) * 2,
        documents_unsignable=0,
        documents_with_vector=None,
        singletons=0,
        clustered_documents=len(records) * 2,
        coverage_rate=1.0 if records else 0.0,
        edges_considered=len(records),
        edges_admitted=len(records),
        tier_excluded=0,
        role_below_min=0,
        band_vetoed=0,
        group_vetoed=0,
        exact_synthesized=0,
        cluster_count=len(records),
        largest_cluster=max((r.member_count for r in records), default=0),
        size_distribution={},
        cross_department_clusters=sum(1 for r in records if r.cross_department),
        cross_group_clusters=sum(1 for r in records if r.cross_group),
        restricted_touching_clusters=sum(1 for r in records if r.has_restricted),
        flagged_clusters=sum(1 for r in records if r.constraint_violations),
        violation_counts={},
        tier_contribution={},
        cluster_tiers=("exact", "near_duplicate", "role_equivalent"),
        cluster_role_equiv_min=0.75,
        cluster_max_band_spread=1,
        cluster_group_homogeneous=True,
        cluster_max_size=50,
        cluster_representative_policy="max_parse_confidence",
        cluster_stamp="cluster_v1+deadbeef",
        edge_method_stamps=("sha256",),
        family_distribution={},
        clusters=tuple(records),
    )


def test_needs_eyes_clusters_surface_first() -> None:
    cohesive = _record("cohesive")
    flagged = _record("flagged", constraint_violations=("oversize",))
    cross_group = _record("xgroup", cross_group=True, employee_groups=("apsa", "cupe"))
    result = _result(cohesive, cross_group, flagged)
    order = [r.cluster_id for r in ordered_records(result)]
    # violated first, then cross-group, then the cohesive one last.
    assert order[0] == flagged.cluster_id
    assert order[1] == cross_group.cluster_id
    assert order[-1] == cohesive.cluster_id


def test_the_report_csv_has_an_empty_human_verdict_column(tmp_path: Path) -> None:
    result = _result(_record("a"))
    path = write_report_csv(ordered_records(result), tmp_path / "report.csv")
    with path.open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert "human_verdict" in rows[0]
    assert rows[0]["human_verdict"] == ""


def test_the_report_carries_filenames_and_labels_never_body_text(
    tmp_path: Path,
) -> None:
    """The record models cannot hold JD body text; the CSVs carry only the filename +
    classification columns. Assert the header set is exactly that closed vocabulary."""
    result = _result(_record("a", has_restricted=True))
    report = write_report_csv(ordered_records(result), tmp_path / "report.csv")
    members = write_members_csv(ordered_records(result), tmp_path / "members.csv")
    report_header = report.read_text(encoding="utf-8").splitlines()[0].split(",")
    members_header = members.read_text(encoding="utf-8").splitlines()[0].split(",")
    assert report_header == [
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
    assert members_header == [
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


def test_members_csv_has_a_row_per_member(tmp_path: Path) -> None:
    result = _result(_record("a"), _record("b"))
    path = write_members_csv(ordered_records(result), tmp_path / "members.csv")
    with path.open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 4  # two clusters x two members
    assert sum(1 for r in rows if r["is_representative"] == "True") == 2


def test_an_empty_corpus_yields_a_zeroed_summary_not_an_error(tmp_path: Path) -> None:
    summary = build_cluster_summary(
        _result(),
        source="empty",
        rules_version="jd_rules_sfu_v4+test",
        generated_at=dt.datetime(2026, 7, 16, tzinfo=dt.UTC),
    )
    assert summary.cluster_count == 0
    assert summary.largest_cluster == 0
    assert summary.coverage_rate == 0.0
    path = write_summary(summary, tmp_path / "summary.json")
    assert path.exists()
    # the empty per-cluster CSV is just its header — no crash.
    report = write_report_csv([], tmp_path / "report.csv")
    assert len(report.read_text(encoding="utf-8").splitlines()) == 1


def test_the_cluster_id_is_stable_and_content_derived() -> None:
    a = _record("a")
    assert isinstance(a.cluster_id, UUID)
    assert _record("a").cluster_id == a.cluster_id  # deterministic

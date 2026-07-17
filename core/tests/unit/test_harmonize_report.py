"""The committed Phase-4.1 measurement artifacts: ``summary.json`` (aggregates, the
per-cluster records EXCLUDED) and ``clusters.csv`` (one row per harmonized cluster). No
JD text ever — counts/labels/stamps only."""

from __future__ import annotations

import csv
import datetime as dt
import json
import uuid
from pathlib import Path

from src.jd_bank.harmonize.models import ClusterHarmonization, HarmonizationResult
from src.jd_bank.harmonize.report import (
    _CLUSTER_COLUMNS,
    build_summary,
    write_clusters_csv,
    write_summary,
)

_ZERO_COUNTS = {
    name: 0
    for name in (
        "documents_seen",
        "documents_signed",
        "documents_unsignable",
        "singletons",
        "clusters_recomputed",
        "wjq_members_dropped",
        "wjq_members_frequency_confirmed",
        "clusters_fully_wjq_excluded",
        "clusters_mixed_jdfn_wjq",
        "member_rows_dropped_unvalidatable",
        "harmonized_clusters",
        "multi_member_clusters",
        "single_member_clusters",
        "jdfn_members_merged",
        "summary_in_range_available_clusters",
        "summary_no_in_range_clusters",
        "education_max_differs_from_modal",
        "experience_max_differs_from_modal",
        "jdfn_members_with_context",
        "clusters_with_multi_context",
        "clusters_with_any_security",
    )
}


def _record() -> ClusterHarmonization:
    return ClusterHarmonization(
        cluster_id=uuid.UUID("00000000-0000-0000-0000-0000000000cc"),
        jdfn_member_count=3,
        wjq_members_dropped=1,
        deduped_duty_count=6,
        distinct_normalized_titles=2,
        modal_group_fraction=0.6666,
        core_skill_count=1,
        security_qual_count=0,
        members_with_context=1,
        summary_in_range_available=True,
        chosen_summary_words=120,
        education_bar_spread=1,
        experience_bar_spread=None,
        flags=("duties_over_max",),
    )


def _result() -> HarmonizationResult:
    return HarmonizationResult(
        flag_counts={"duties_over_max": 1},
        title_policy="modal_normalized",
        summary_policy="within_target_then_central",
        additional_context_policy="drop",
        boilerplate_presence_policy="or_across_members",
        duty_dedup_jaccard_min=0.7,
        max_duties=10,
        core_skill_min_fraction=0.5,
        security_policy="union",
        seniority_bar_policy="max",
        harmonize_stamp="harmonize_v1+deadbeef1234",
        clusters=(_record(),),
        **{**_ZERO_COUNTS, "harmonized_clusters": 1},
    )


def test_summary_excludes_the_per_cluster_records_and_never_carries_text(
    tmp_path: Path,
) -> None:
    summary = build_summary(
        _result(),
        source="test",
        rules_version="jd_rules_sfu_v4+abc",
        generated_at=dt.datetime(2026, 7, 17, tzinfo=dt.UTC),
    )
    out = write_summary(summary, tmp_path / "summary.json")
    payload = json.loads(out.read_text(encoding="utf-8"))
    # The per-cluster records live in the CSV, not the JSON overview.
    assert "clusters" not in payload["result"]
    assert payload["result"]["flag_counts"] == {"duties_over_max": 1}
    assert payload["rules_version"] == "jd_rules_sfu_v4+abc"
    # Sorted + trailing newline (stable diff).
    assert out.read_text(encoding="utf-8").endswith("}\n")


def test_clusters_csv_is_one_row_per_cluster(tmp_path: Path) -> None:
    out = write_clusters_csv([_record()], tmp_path / "clusters.csv")
    rows = list(csv.DictReader(out.read_text(encoding="utf-8").splitlines()))
    assert len(rows) == 1
    assert rows[0]["jdfn_member_count"] == "3"
    assert rows[0]["experience_bar_spread"] == ""  # None renders empty, not "None"
    assert rows[0]["flags"] == "duties_over_max"


# --- artifact hygiene: no JD-derived text may leak into an HR record ----------------

#: Fields the parser sources (directly or via `cluster_label`) from JD BODY text — the
#: modal member `title` is frequently a mis-extracted prose paragraph. NONE of these may
#: appear as a `clusters.csv` column: the committed artifact carries counts + the
#: content-derived `cluster_id` only.
_JD_TEXT_DERIVED_COLUMNS = frozenset(
    {
        "label",
        "title",
        "normalized_title",
        "summary",
        "position_summary",
        "duty",
        "duties",
    }
)


def test_clusters_csv_has_no_jd_title_or_text_derived_column() -> None:
    """Pin the leak the reviewer caught: `cluster_label` is the modal member `title`,
    which the parser often fills with a whole prose paragraph, so a title-derived column
    would smuggle verbatim JD body text into an HR record. Re-adding one goes red."""
    assert not (set(_CLUSTER_COLUMNS) & _JD_TEXT_DERIVED_COLUMNS), (
        f"clusters.csv exposes a JD-text-derived column: "
        f"{set(_CLUSTER_COLUMNS) & _JD_TEXT_DERIVED_COLUMNS}"
    )
    # And the model itself carries no free-text title/label field to source one from.
    assert not (set(ClusterHarmonization.model_fields) & _JD_TEXT_DERIVED_COLUMNS)


def test_no_clusters_csv_cell_echoes_a_members_prose_title(tmp_path: Path) -> None:
    """A record built from a cluster whose modal `title` is a long prose paragraph (the
    real mis-extraction) must produce NO cell containing that prose — the behavioural
    proof the artifact is title-free."""
    prose = (
        "Reporting to the Director, this position provides confidential administrative "
        "support and coordinates the annual budget cycle across the faculty units."
    )
    rec = _record()  # ClusterHarmonization has no title/label field to hold `prose`
    out = write_clusters_csv([rec], tmp_path / "clusters.csv")
    text = out.read_text(encoding="utf-8")
    assert prose not in text
    # Belt and braces: no cell holds any long free-text run at all.
    for cell in text.replace("\r\n", "\n").split("\n")[1].split(","):
        assert " " not in cell.strip(), f"unexpected free-text cell: {cell!r}"

"""The committed Phase-4.1 measurement artifacts: ``summary.json`` (aggregate
distributions + counts + stamps) and ``clusters.csv`` (one row per harmonized JDFN
cluster). Both carry counts + the content-derived ``cluster_id`` ONLY — never JD-derived
text. In particular ``clusters.csv`` has NO title/summary/duty-sourced column: the modal
member ``title`` (``cluster_label``) is frequently a mis-extracted prose paragraph, so a
title-derived column would smuggle verbatim JD body text into an HR record. These are HR
records, the same class of data ``docs/cluster/`` commits.

``summary.json`` is what the human calibrates the nine knobs on; it deliberately does
NOT embed the per-cluster records (they go to the CSV) so it stays a readable overview.
"""

from __future__ import annotations

import csv
import datetime as dt
import json
from collections.abc import Sequence
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from src.jd_bank.harmonize.models import ClusterHarmonization, HarmonizationResult

_CELL_SEP = "|"


class HarmonizationSummary(BaseModel):
    """The committed measurement finding — its provenance meta + the aggregate result.
    The per-cluster records live in ``clusters.csv``; neither artifact carries
    JD-derived text (counts + the content-derived ``cluster_id`` only).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    source: str
    generated_at: dt.datetime
    rules_version: str
    result: HarmonizationResult


def build_summary(
    result: HarmonizationResult,
    *,
    source: str,
    rules_version: str,
    generated_at: dt.datetime | None = None,
) -> HarmonizationSummary:
    """The committed summary from one ``run_harmonization`` result. Pure — no I/O."""
    return HarmonizationSummary(
        source=source,
        generated_at=generated_at or dt.datetime.now(dt.UTC),
        rules_version=rules_version,
        result=result,
    )


def write_summary(summary: HarmonizationSummary, path: Path) -> Path:
    """Write ``summary`` as pretty, sorted JSON (the per-cluster records excluded —
    they go to the CSV), creating parent dirs as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = summary.model_dump(mode="json", exclude={"result": {"clusters"}})
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return path


_CLUSTER_COLUMNS = [
    "cluster_id",
    "jdfn_member_count",
    "wjq_members_dropped",
    "deduped_duty_count",
    "distinct_normalized_titles",
    "modal_group_fraction",
    "core_skill_count",
    "security_qual_count",
    "members_with_context",
    "summary_in_range_available",
    "chosen_summary_words",
    "education_bar_spread",
    "experience_bar_spread",
    "flags",
]


def write_clusters_csv(records: Sequence[ClusterHarmonization], path: Path) -> Path:
    """One row per harmonized JDFN cluster (counts + the content-derived ``cluster_id``
    only — NO title/summary/duty-sourced column). ``records`` in the runner's
    deterministic order (by ``cluster_id``)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(_CLUSTER_COLUMNS)
        for r in records:
            writer.writerow(
                [
                    str(r.cluster_id),
                    r.jdfn_member_count,
                    r.wjq_members_dropped,
                    r.deduped_duty_count,
                    r.distinct_normalized_titles,
                    f"{r.modal_group_fraction:.4f}",
                    r.core_skill_count,
                    r.security_qual_count,
                    r.members_with_context,
                    str(r.summary_in_range_available),
                    "" if r.chosen_summary_words is None else r.chosen_summary_words,
                    "" if r.education_bar_spread is None else r.education_bar_spread,
                    "" if r.experience_bar_spread is None else r.experience_bar_spread,
                    _CELL_SEP.join(r.flags),
                ]
            )
    return path

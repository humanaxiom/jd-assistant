"""The committed Tier-2 artifacts: ``near-dup-summary.json`` (counts + stamps only —
**never document text**, mirroring ``docs/dedup/summary.json`` and
``docs/embeddings/summary.json``) and ``near-dup-adjudication-sample.csv`` (the
candidate pairs a human should actually look at).

**Why an adjudication sample, not a precision/recall gate against the label set.**
`fixtures/labels/pairs.csv` cannot referee `jaccard_min` — see ``dedup.yaml``'s header
and HR-138: same-position "negative" pairs measure at HIGHER median Jaccard than
cross-position LSH "candidate" pairs on this corpus. The honest fix is not a better
threshold search against a bad oracle; it is generating real candidates and asking a
human who can actually read a JD. This module produces exactly the input that
adjudication needs and none of it prejudges the answer — the ``human_label`` column
ships empty.
"""

from __future__ import annotations

import csv
import datetime as dt
import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Final

from pydantic import BaseModel, ConfigDict, Field

from src.jd_bank.dedup.near.models import PairRecord, Tier2Result

#: The (band_index) count the adjudication sample stratifies Jaccard into, above
#: `jaccard_min` — crossed with same/cross/unknown position, for
#: :func:`sample_for_adjudication`.
_JACCARD_BAND_COUNT: Final[int] = 4

#: Default adjudication sample size — "~200 candidate pairs" per the Phase 3.3 spec.
DEFAULT_ADJUDICATION_TARGET: Final[int] = 200


def _percentiles(values: Sequence[float], points: Sequence[int]) -> dict[str, float]:
    """Nearest-rank percentiles of ``values`` — ``0.0`` for every point when
    ``values`` is empty (a run with no qualifying pairs has "zero" percentiles, not
    an absence)."""
    if not values:
        return {f"p{p}": 0.0 for p in points} | {"max": 0.0}
    ordered = sorted(values)

    def _at(point: int) -> float:
        index = min(len(ordered) - 1, max(0, int(len(ordered) * point / 100)))
        return ordered[index]

    result = {f"p{point}": _at(point) for point in points}
    result["max"] = ordered[-1]
    return result


class NearDupSummary(BaseModel):
    """The committed Tier-2 finding — counts, percentiles and stamps. Filenames live
    only in the separate adjudication CSV; this artifact never carries document
    content."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source: str
    generated_at: dt.datetime
    rules_version: str
    dedup_stamp: str
    s_curve_threshold: float = Field(ge=0.0, le=1.0)

    documents_seen: int = Field(ge=0)
    distinct_contents: int = Field(ge=0)
    documents_unreadable: int = Field(ge=0)
    documents_below_min_shingles: int = Field(ge=0)
    documents_signed: int = Field(ge=0)
    #: ``documents_signed / distinct_contents`` — ``0.0`` when ``distinct_contents``
    #: is ``0``. The denominator is DISTINCT CONTENTS, never ``documents_seen``
    #: (FILES): Tier-2 runs over one signature per distinct ``sha256``
    #: (``edge_scope: content``), and ``documents_unreadable`` +
    #: ``documents_below_min_shingles`` + ``documents_signed`` partition
    #: ``distinct_contents`` EXACTLY — they do not partition ``documents_seen``,
    #: which double-(under-)counts every byte-identical duplicate Tier-1 already
    #: folded away. Dividing by ``documents_seen`` instead (the first cut's bug) is a
    #: unit error, not a rounding difference: on the real archive it reported 85.8%
    #: coverage against a true 99.2% (12,494 / 12,593). NOT the same claim as "WJQ
    #: files recovered" (that requires comparing a `raw_clean` run against a
    #: `serialized` run of the SAME corpus, which this single run's numbers cannot
    #: establish on their own — see HR-131's measured basis for that specific
    #: comparison, done once, offline, against the real archive).
    coverage_rate: float = Field(ge=0.0, le=1.0)

    candidate_pairs: int = Field(ge=0)
    qualifying_pairs: int = Field(ge=0)
    cosine_vetoed: int = Field(ge=0)

    edges_written: int = Field(ge=0)
    edges_updated: int = Field(ge=0)
    edges_unchanged: int = Field(ge=0)
    edges_pruned: int = Field(ge=0)

    text_source: str
    edge_scope: str
    jaccard_min: float = Field(ge=0.0, le=1.0)
    cosine_confirm_min: float | None = None

    #: Nearest-rank p10/p50/p90/p99/max EXACT Jaccard over qualifying pairs this run.
    jaccard_percentiles: Mapping[str, float] = Field(default_factory=dict)

    same_position_edges: int = Field(ge=0)
    cross_position_edges: int = Field(ge=0)
    unknown_position_edges: int = Field(ge=0)


def build_near_dup_summary(
    result: Tier2Result,
    *,
    source: str,
    rules_version: str,
    generated_at: dt.datetime | None = None,
) -> NearDupSummary:
    """The committed summary derived from one :func:`~src.jd_bank.dedup.near.runner.
    run_tier2` result. Pure — no I/O."""
    qualifying_scores = [record.jaccard for record in result.pairs if record.qualifies]
    same = sum(1 for r in result.pairs if r.qualifies and r.same_position is True)
    cross = sum(1 for r in result.pairs if r.qualifies and r.same_position is False)
    unknown = sum(1 for r in result.pairs if r.qualifies and r.same_position is None)
    coverage_rate = (
        result.documents_signed / result.distinct_contents
        if result.distinct_contents
        else 0.0
    )
    return NearDupSummary(
        source=source,
        generated_at=generated_at or dt.datetime.now(dt.UTC),
        rules_version=rules_version,
        dedup_stamp=result.dedup_stamp,
        s_curve_threshold=result.s_curve_threshold,
        documents_seen=result.documents_seen,
        distinct_contents=result.distinct_contents,
        documents_unreadable=result.documents_unreadable,
        documents_below_min_shingles=result.documents_below_min_shingles,
        documents_signed=result.documents_signed,
        coverage_rate=coverage_rate,
        candidate_pairs=result.candidate_pairs,
        qualifying_pairs=result.qualifying_pairs,
        cosine_vetoed=result.cosine_vetoed,
        edges_written=result.edges_written,
        edges_updated=result.edges_updated,
        edges_unchanged=result.edges_unchanged,
        edges_pruned=result.edges_pruned,
        text_source=result.text_source,
        edge_scope=result.edge_scope,
        jaccard_min=result.jaccard_min,
        cosine_confirm_min=result.cosine_confirm_min,
        jaccard_percentiles=_percentiles(qualifying_scores, (10, 50, 90, 99)),
        same_position_edges=same,
        cross_position_edges=cross,
        unknown_position_edges=unknown,
    )


def write_summary(summary: NearDupSummary, path: Path) -> Path:
    """Write ``summary`` as pretty JSON, creating parent directories as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(summary.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def _band_for(jaccard: float, jaccard_min: float) -> str:
    """Which of :data:`_JACCARD_BAND_COUNT` equal-width bands above ``jaccard_min``
    ``jaccard`` falls into — a label, not a number, so it groups cleanly as a
    stratification key."""
    span = 1.0 - jaccard_min
    if span <= 0:
        return "single"
    width = span / _JACCARD_BAND_COUNT
    index = min(_JACCARD_BAND_COUNT - 1, int((jaccard - jaccard_min) / width))
    lo = jaccard_min + index * width
    hi = jaccard_min + (index + 1) * width
    return f"{lo:.3f}-{hi:.3f}"


def _position_bucket(same_position: bool | None) -> str:
    if same_position is True:
        return "same_position"
    if same_position is False:
        return "cross_position"
    return "unknown_position"


def sample_for_adjudication(
    pairs: Sequence[PairRecord],
    *,
    jaccard_min: float,
    target: int = DEFAULT_ADJUDICATION_TARGET,
) -> list[PairRecord]:
    """~``target`` QUALIFYING pairs, stratified by Jaccard band x
    (same-position | cross-position | unknown), so an adjudicator sees the full shape
    of what Tier-2 found rather than only its most confident (highest-Jaccard) edges.

    Deterministic (evenly-spaced picks within each stratum, sorted by filename) —
    NOT randomly sampled, so the same run produces the same sample: this artifact is
    an audit trail, and a random sample would make "did the algorithm change?" and
    "did the sample change?" indistinguishable on re-run.
    """
    qualifying = [pair for pair in pairs if pair.qualifies]
    if not qualifying:
        return []

    strata: dict[tuple[str, str], list[PairRecord]] = defaultdict(list)
    for pair in qualifying:
        band = _band_for(pair.jaccard, jaccard_min)
        bucket = _position_bucket(pair.same_position)
        strata[(band, bucket)].append(pair)

    per_stratum = max(1, target // max(1, len(strata)))
    sample: list[PairRecord] = []
    for key in sorted(strata):
        members = sorted(
            strata[key], key=lambda r: (r.filename_a or "", r.filename_b or "")
        )
        step = max(1, len(members) // per_stratum)
        sample.extend(members[::step][:per_stratum])
    return sample[:target]


def write_adjudication_csv(rows: Sequence[PairRecord], path: Path) -> Path:
    """Write the adjudication sample: filenames, scores, and an EMPTY
    ``human_label`` column — this is how a real label set finally gets built (the
    existing ``fixtures/labels/pairs.csv`` is bad precisely because nobody ever
    generated candidates to adjudicate)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "filename_a",
                "filename_b",
                "jaccard",
                "cosine",
                "same_position",
                "human_label",
            ]
        )
        for row in rows:
            writer.writerow(
                [
                    row.filename_a or "",
                    row.filename_b or "",
                    f"{row.jaccard:.4f}",
                    "" if row.cosine is None else f"{row.cosine:.4f}",
                    "" if row.same_position is None else str(row.same_position),
                    "",
                ]
            )
    return path

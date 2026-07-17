"""The committed Tier-3 artifacts (Phase 3.4b): ``role-equiv-summary.json`` (counts,
score percentiles and stamps — **never document text**) and
``role-equiv-adjudication-sample.csv`` (the candidate pairs a human should actually look
at, so the real role-equivalence label set finally gets built).

**Why an adjudication sample, not a precision/recall gate.** There is no honest oracle
for "same role, different text" — the SAME lesson as Tier-2's ``jaccard_min``
(HR-138/HR-158): the only labelled positives are Tier-2 near-dup weak labels, which are
vector-dominated and say nothing about genuinely-different-text same-role pairs. So this
module ships the input to adjudication (stratified by score band × same/cross-function)
and prejudges nothing — ``human_label`` ships empty.
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

from src.jd_bank.dedup.role.models import RolePairRecord, Tier3Result

#: How many equal-width score bands the adjudication sample stratifies into, crossed
#: with same/cross-function.
_SCORE_BAND_COUNT: Final[int] = 5

#: Default adjudication sample size — "~200 candidate pairs" per the Phase 3.4b spec.
DEFAULT_ADJUDICATION_TARGET: Final[int] = 200


def _percentiles(values: Sequence[float], points: Sequence[int]) -> dict[str, float]:
    """Nearest-rank percentiles — ``0.0`` for every point when ``values`` is empty (a
    run
    with no qualifying pairs has "zero" percentiles, not an absence)."""
    if not values:
        return {f"p{p}": 0.0 for p in points} | {"max": 0.0}
    ordered = sorted(values)

    def _at(point: int) -> float:
        index = min(len(ordered) - 1, max(0, int(len(ordered) * point / 100)))
        return ordered[index]

    result = {f"p{point}": _at(point) for point in points}
    result["max"] = ordered[-1]
    return result


class RoleEquivSummary(BaseModel):
    """The committed Tier-3 finding — counts, percentiles and stamps. Filenames live
    only
    in the separate adjudication CSV; this artifact never carries document content."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source: str
    generated_at: dt.datetime
    rules_version: str
    dedup_stamp: str
    idf_stamp: str
    idf_skills: int = Field(ge=0)

    documents_seen: int = Field(ge=0)
    documents_signed: int = Field(ge=0)
    documents_unsignable: int = Field(ge=0)
    documents_with_vector: int = Field(ge=0)
    documents_without_vector: int = Field(ge=0)

    candidate_pairs: int = Field(ge=0)
    band_vetoed: int = Field(ge=0)
    group_vetoed: int = Field(ge=0)
    admissible_pairs: int = Field(ge=0)
    qualifying_pairs: int = Field(ge=0)
    restricted_flagged: int = Field(ge=0)

    edges_written: int = Field(ge=0)
    edges_updated: int = Field(ge=0)
    edges_unchanged: int = Field(ge=0)
    edges_pruned: int = Field(ge=0)

    role_equiv_threshold: float = Field(ge=0.0, le=1.0)
    max_band_gap: int = Field(ge=0)
    candidate_k: int = Field(gt=0)
    seed_from_near_dup: bool
    group_conflict_veto: bool

    #: Nearest-rank p10/p50/p90/p99/max blended score over QUALIFYING pairs this run.
    score_percentiles: Mapping[str, float] = Field(default_factory=dict)
    same_function_edges: int = Field(ge=0)
    cross_function_edges: int = Field(ge=0)
    #: title family -> how many signed JDs classify onto it.
    family_distribution: Mapping[str, int] = Field(default_factory=dict)


def build_role_equiv_summary(
    result: Tier3Result,
    *,
    source: str,
    rules_version: str,
    generated_at: dt.datetime | None = None,
) -> RoleEquivSummary:
    """The committed summary derived from one :func:`~src.jd_bank.dedup.role.runner.
    run_tier3` result. Pure — no I/O."""
    qualifying = [record for record in result.pairs if record.qualifies]
    scores = [record.score for record in qualifying]
    return RoleEquivSummary(
        source=source,
        generated_at=generated_at or dt.datetime.now(dt.UTC),
        rules_version=rules_version,
        dedup_stamp=result.dedup_stamp,
        idf_stamp=result.idf_stamp,
        idf_skills=result.idf_skills,
        documents_seen=result.documents_seen,
        documents_signed=result.documents_signed,
        documents_unsignable=result.documents_unsignable,
        documents_with_vector=result.documents_with_vector,
        documents_without_vector=result.documents_without_vector,
        candidate_pairs=result.candidate_pairs,
        band_vetoed=result.band_vetoed,
        group_vetoed=result.group_vetoed,
        admissible_pairs=result.admissible_pairs,
        qualifying_pairs=result.qualifying_pairs,
        restricted_flagged=result.restricted_flagged,
        edges_written=result.edges_written,
        edges_updated=result.edges_updated,
        edges_unchanged=result.edges_unchanged,
        edges_pruned=result.edges_pruned,
        role_equiv_threshold=result.role_equiv_threshold,
        max_band_gap=result.max_band_gap,
        candidate_k=result.candidate_k,
        seed_from_near_dup=result.seed_from_near_dup,
        group_conflict_veto=result.group_conflict_veto,
        score_percentiles=_percentiles(scores, (10, 50, 90, 99)),
        same_function_edges=sum(1 for r in qualifying if r.same_function),
        cross_function_edges=sum(1 for r in qualifying if not r.same_function),
        family_distribution=result.family_distribution,
    )


def write_summary(summary: RoleEquivSummary, path: Path) -> Path:
    """Write ``summary`` as pretty, sorted JSON, creating parent directories as
    needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(summary.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def _score_band(score: float) -> str:
    """Which of :data:`_SCORE_BAND_COUNT` equal-width [0, 1] bands ``score`` falls into
    —
    a label, so it groups cleanly as a stratification key."""
    width = 1.0 / _SCORE_BAND_COUNT
    index = min(_SCORE_BAND_COUNT - 1, int(score / width))
    lo = index * width
    hi = (index + 1) * width
    return f"{lo:.2f}-{hi:.2f}"


def sample_for_adjudication(
    pairs: Sequence[RolePairRecord],
    *,
    target: int = DEFAULT_ADJUDICATION_TARGET,
) -> list[RolePairRecord]:
    """~``target`` candidate pairs, stratified by score band × (same-function |
    cross-function), so an adjudicator sees the FULL shape of what Tier-3 found — not
    only its most confident edges, and crucially including below-threshold candidates
    (the ones that decide whether ``role_equiv_threshold`` is in the right place).

    Deterministic (evenly-spaced picks within each stratum, sorted by filename) — this
    is an audit trail, and a random sample would make "did the algorithm change?" and
    "did the
    sample change?" indistinguishable on re-run."""
    if not pairs:
        return []
    strata: dict[tuple[str, bool], list[RolePairRecord]] = defaultdict(list)
    for pair in pairs:
        strata[(_score_band(pair.score), pair.same_function)].append(pair)

    per_stratum = max(1, target // max(1, len(strata)))
    sample: list[RolePairRecord] = []
    for key in sorted(strata, key=lambda k: (k[0], k[1])):
        members = sorted(
            strata[key], key=lambda r: (r.filename_a or "", r.filename_b or "")
        )
        step = max(1, len(members) // per_stratum)
        sample.extend(members[::step][:per_stratum])
    return sample[:target]


def write_adjudication_csv(rows: Sequence[RolePairRecord], path: Path) -> Path:
    """Write the adjudication sample: the two filenames, the blended score + its three
    components, both families, the ``restricted`` flag, and an EMPTY ``human_label``
    column — how the real role-equivalence label set finally gets built."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "filename_a",
                "filename_b",
                "score",
                "vector_score",
                "skill_overlap",
                "seniority",
                "family_a",
                "family_b",
                "same_function",
                "restricted",
                "human_label",
            ]
        )
        for row in rows:
            writer.writerow(
                [
                    row.filename_a or "",
                    row.filename_b or "",
                    f"{row.score:.4f}",
                    f"{row.vector_score:.4f}",
                    f"{row.skill_overlap:.4f}",
                    f"{row.seniority:.4f}",
                    row.family_a,
                    row.family_b,
                    str(row.same_function),
                    str(row.restricted),
                    "",
                ]
            )
    return path

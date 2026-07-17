"""Edge admission for Phase-3.5 clustering — the pure gate over the mixed-tier graph.

A single scalar threshold over the three tiers is WRONG: EXACT=1.0, NEAR∈[0.85,1.0]
and ROLE∈[0.5,1.0], and ROLE is BIMODAL (41% skill-empty pairs floor ~0.52). So
admission is tiered, not scalar:

* the edge's tier must be in ``cluster_tiers`` (HR-161) — else ``tier_excluded``;
* a ROLE edge must additionally clear ``cluster_role_equiv_min`` (HR-162, 0.75, the
  measured knee where the archive-wide blob breaks) — else ``role_below_min``.
  EXACT/NEAR are NOT re-thresholded: they are strong, well-scaled evidence already;
* the family-band conflict veto and the employee-group veto (the SAME pure predicates
  Tier-3 uses, HR-155/HR-157) drop a clearly-cross-ladder or cross-group pair. An
  endpoint with NO signals (unsignable → UNKNOWN) is never a veto — it needs both sides.

The survivors go to ``build_clusters(threshold=0.0)``: the tier gate + the ROLE gate did
the thresholding here, so the union-find must NOT re-threshold on the incomparable raw
score. Pure — no I/O, no rulebook lookup beyond the passed ``comparison``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from uuid import UUID

from src.jd_bank.cluster.models import ClusterEdge
from src.jd_bank.db.models import DedupTier
from src.jd_bank.dedup.role.runner import band_vetoes, group_vetoes
from src.jd_core.models.bank import JobSignals
from src.jd_core.rules import Comparison

#: The tier whose edges are additionally gated by ``cluster_role_equiv_min``.
_ROLE_TIER = DedupTier.ROLE_EQUIVALENT


@dataclass(frozen=True, slots=True)
class DropCounts:
    """Why admission dropped a candidate edge — one bucket per reason, in order."""

    tier_excluded: int = 0
    role_below_min: int = 0
    band_vetoed: int = 0
    group_vetoed: int = 0


def admit_edges(
    edges: Sequence[ClusterEdge],
    signals: Mapping[UUID, JobSignals],
    *,
    comparison: Comparison,
) -> tuple[list[ClusterEdge], DropCounts]:
    """The admitted subset of ``edges``, plus a count of why each drop happened.

    Checks are ordered — an edge is charged to the FIRST reason it fails, and is never
    re-tested after a drop. An endpoint absent from ``signals`` (unsignable) makes the
    vetoes unevaluable, which is treated as "no conflict" (an unknown is not a "no"), so
    such an edge survives the veto stage.
    """
    admitted: list[ClusterEdge] = []
    tier_excluded = 0
    role_below_min = 0
    band_vetoed = 0
    group_vetoed = 0

    for edge in edges:
        if edge.tier.value not in comparison.cluster_tiers:
            tier_excluded += 1
            continue
        if edge.tier == _ROLE_TIER and edge.score < comparison.cluster_role_equiv_min:
            role_below_min += 1
            continue
        sig_a = signals.get(edge.a)
        sig_b = signals.get(edge.b)
        if sig_a is not None and sig_b is not None:
            if band_vetoes(sig_a, sig_b, comparison):
                band_vetoed += 1
                continue
            if group_vetoes(sig_a, sig_b, comparison):
                group_vetoed += 1
                continue
        admitted.append(edge)

    return admitted, DropCounts(
        tier_excluded=tier_excluded,
        role_below_min=role_below_min,
        band_vetoed=band_vetoed,
        group_vetoed=group_vetoed,
    )

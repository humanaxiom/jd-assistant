"""Corpus clustering — group near-duplicate JDs into role clusters (pure).

Ported from hris ``packages/pipeline/src/pipeline/bank/clustering.py`` (reuse-map,
ADR-005). Builds an undirected similarity graph from job-to-job edges (score >= a
conservative cluster threshold) and returns its connected components of size >=
``min_cluster_size`` — a singleton job has no redundancy, so it is not a cluster.
Title-agnostic metrics (distinct titles, departments spanned, a representative
label) are derived per cluster.

Connected components is the deliberate Iteration-1 choice: simple and explainable.
If it over-merges on the real archive (one giant blob), Louvain community detection
is the documented fallback — and both the algorithm stamp and the threshold are data
(``rules/comparison.yaml``, HR-095 / HR-097), so switching is not a code change.

**The cluster threshold is derived, not stored.** hris wrote ``CLUSTER_THRESHOLD =
max(SIM_THRESHOLD, 0.80)``. Only the two decided numbers are data — the per-JD noise
floor (``sim_threshold``) and the cluster floor (``cluster_threshold_floor``) — and
:attr:`~src.jd_core.rules.Comparison.cluster_threshold` computes the ``max`` at read
time. Shipping the answer as a third key would be two knobs holding one value with
nothing keeping them in step (the ``max_listed`` landmine on the backlog).

⚠ **NOT WIRED TO ANYTHING, DELIBERATELY.** ``build_clusters`` takes edges the caller
computed; nothing in JD Bank computes them yet (the skill ontology and idf corpus the
similarity score needs do not exist here — see ``bank/similarity.py``). The two
clustering rules the plan calls for and this module does **not** implement, because
they are Phase 3 / 3.5 work and not part of the hris module being ported: the
employee-group / level **hard constraints**, and the cluster **diameter cap**. Do not
add them here on the way past.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from uuid import UUID

from src.jd_core.bank.similarity import normalize_title
from src.jd_core.rules import Comparison, Rules, get_rules


def _comparison(rules: Rules | None) -> Comparison:
    return (rules if rules is not None else get_rules()).comparison


def build_clusters(
    edges: Iterable[tuple[UUID, UUID, float]],
    *,
    threshold: float | None = None,
    rules: Rules | None = None,
) -> list[list[UUID]]:
    """Union-find over the edges at or above ``threshold``.

    ``threshold`` defaults to the rulebook's *derived* cluster threshold
    (``max(sim_threshold, cluster_threshold_floor)``); a caller may still pass its
    own, as hris's signature allowed.

    Returns the connected components with at least ``min_cluster_size`` members, each
    member list sorted for determinism, the clusters ordered largest-first and then by
    smallest member id.
    """
    comparison = _comparison(rules)
    cutoff = comparison.cluster_threshold if threshold is None else threshold
    parent: dict[UUID, UUID] = {}

    def find(x: UUID) -> UUID:
        parent.setdefault(x, x)
        root = x
        while parent[root] != root:
            root = parent[root]
        while parent[x] != root:  # path compression
            parent[x], x = root, parent[x]
        return root

    def union(a: UUID, b: UUID) -> None:
        root_a, root_b = find(a), find(b)
        if root_a != root_b:
            parent[root_a] = root_b

    for a, b, score in edges:
        if score >= cutoff:
            union(a, b)

    components: dict[UUID, list[UUID]] = {}
    for node in parent:
        components.setdefault(find(node), []).append(node)

    clusters = [
        sorted(members, key=str)
        for members in components.values()
        if len(members) >= comparison.min_cluster_size
    ]
    clusters.sort(key=lambda members: (-len(members), str(members[0])))
    return clusters


def cluster_metrics(
    titles: list[str], departments: list[str | None], *, rules: Rules | None = None
) -> tuple[int, int, bool]:
    """``(distinct_titles, department_count, cross_department)`` for one cluster.

    ``distinct_titles`` counts *normalized* titles, so "Developer" and "Developer II"
    are one title (:func:`~src.jd_core.bank.similarity.normalize_title`).
    """
    distinct_titles = len(
        {normalize_title(title, rules=rules) for title in titles if title}
    )
    departments_present = {department for department in departments if department}
    return (
        distinct_titles,
        len(departments_present),
        len(departments_present) > 1,
    )


def cluster_label(titles: list[str]) -> str:
    """A representative label for a cluster: the most common title (ties broken by the
    shortest, then alphabetically), or ``""`` when there are no titles."""
    present = [title for title in titles if title]
    if not present:
        return ""
    counts = Counter(present)
    top = max(counts.values())
    candidates = sorted(title for title, count in counts.items() if count == top)
    return min(candidates, key=lambda title: (len(title), title))

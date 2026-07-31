"""The pure corpus-clustering primitives.

Ported from hris ``tests/unit/test_jd_bank_clustering.py`` (9 tests) — the
behavioural spec (ADR-005). Plus the JD Bank half: the cluster threshold, the
algorithm stamp and the minimum cluster size are data.

**The derived threshold.** hris wrote ``CLUSTER_THRESHOLD = max(SIM_THRESHOLD,
0.80)``. Shipping *that number* (0.80) as a second, independent knob is the
``max_listed`` landmine on the backlog — two knobs holding one value with nothing
keeping them in step. So the rulebook holds only the two things that are actually
decided (``sim_threshold``, ``cluster_threshold_floor``) and ``cluster_threshold``
stays **derived**: ``Comparison.cluster_threshold`` computes the ``max`` at read
time. Raise the noise floor above the cluster floor and the cluster threshold
follows, exactly as in hris — see ``test_the_cluster_threshold_follows_the_sim_
threshold_when_it_overtakes_it``.
"""

from __future__ import annotations

from uuid import UUID

import pytest

from src.jd_core.bank import build_clusters, cluster_label, cluster_metrics
from src.jd_core.bank.clustering import CLUSTER_ALGORITHMS
from src.jd_core.rules import Rules, RulesError, get_rules
from tests.unit.retuned_rules import retuned as _retuned

_A = UUID("00000000-0000-0000-0000-00000000000a")
_B = UUID("00000000-0000-0000-0000-00000000000b")
_C = UUID("00000000-0000-0000-0000-00000000000c")
_D = UUID("00000000-0000-0000-0000-00000000000d")
_E = UUID("00000000-0000-0000-0000-00000000000e")


@pytest.fixture
def rules() -> Rules:
    return get_rules()


# --- the hris spec (verbatim behaviour) ---------------------------------------


def test_transitive_edges_form_one_cluster() -> None:
    # A-B and B-C (both strong) -> {A,B,C} is one component.
    clusters = build_clusters([(_A, _B, 0.9), (_B, _C, 0.8)], threshold=0.72)
    assert len(clusters) == 1
    assert set(clusters[0]) == {_A, _B, _C}


def test_weak_edges_excluded() -> None:
    # A-B strong, C-D weak -> only {A,B} clusters; C,D drop (singletons).
    clusters = build_clusters([(_A, _B, 0.9), (_C, _D, 0.5)], threshold=0.72)
    assert [set(c) for c in clusters] == [{_A, _B}]


def test_separate_components() -> None:
    clusters = build_clusters([(_A, _B, 0.9), (_C, _D, 0.8)], threshold=0.72)
    assert {frozenset(c) for c in clusters} == {
        frozenset({_A, _B}),
        frozenset({_C, _D}),
    }


def test_clusters_ordered_largest_first() -> None:
    clusters = build_clusters(
        [(_A, _B, 0.9), (_B, _C, 0.9), (_D, _E, 0.9)], threshold=0.72
    )
    assert len(clusters[0]) == 3  # {A,B,C} before {D,E}
    assert len(clusters[1]) == 2


def test_empty_edges_no_clusters() -> None:
    assert build_clusters([], threshold=0.72) == []


def test_cluster_metrics_distinct_titles_and_departments() -> None:
    # "Developer" and "Developer II" normalise to one title; two departments.
    distinct, dept_count, cross = cluster_metrics(
        ["Developer", "Developer II", "Programmer"], ["Eng", "Data", "Eng"]
    )
    assert distinct == 2  # {"developer", "programmer"}
    assert dept_count == 2
    assert cross is True


def test_cluster_metrics_single_department_not_cross() -> None:
    _, dept_count, cross = cluster_metrics(["A", "B"], ["Eng", "Eng"])
    assert dept_count == 1
    assert cross is False


def test_cluster_label_most_common_title() -> None:
    assert cluster_label(["Developer", "Developer", "Programmer"]) == "Developer"


def test_cluster_label_empty() -> None:
    assert cluster_label([]) == ""


# --- the default threshold is the rulebook's, not an argument's ----------------


def test_the_default_threshold_is_the_rulebooks_cluster_threshold(
    rules: Rules,
) -> None:
    """Called with no ``threshold``, ``build_clusters`` uses the *derived* cluster
    threshold — 0.80 today. An 0.79 edge is not a cluster; an 0.80 edge is."""
    assert rules.comparison.cluster_threshold == 0.80
    assert build_clusters([(_A, _B, 0.79)]) == []
    assert build_clusters([(_A, _B, 0.80)]) == [[_A, _B]]


def test_the_cluster_floor_is_data_pinned_by_value(rules: Rules) -> None:
    """`prior_calibration` (HR-095): "cluster only on strong edges" — a precision call
    nobody at SFU made. It is the number that decides how much of the archive gets
    merged, and Phase 3 will have to justify it against the real corpus."""
    assert rules.comparison.cluster_threshold_floor == 0.80


def test_the_cluster_threshold_is_derived_not_stored(rules: Rules) -> None:
    """The landmine, closed: one value, two knobs, no duplicate. ``cluster_threshold``
    is a property over ``max(sim_threshold, cluster_threshold_floor)`` — there is no
    third YAML key holding 0.80 that could silently fall out of step."""
    comparison = rules.comparison
    assert comparison.cluster_threshold == max(
        comparison.sim_threshold, comparison.cluster_threshold_floor
    )
    assert "cluster_threshold" not in type(comparison).model_fields


def test_the_cluster_threshold_follows_the_sim_threshold_when_it_overtakes_it(
    rules: Rules,
) -> None:
    """hris's ``max()``, transcribed. Raise the "show me similar" noise floor above
    the cluster floor and clustering tightens with it — automatically, because the
    threshold is derived rather than copied."""
    strict = _retuned(rules, sim_threshold=0.90)
    assert strict.comparison.cluster_threshold == 0.90
    assert build_clusters([(_A, _B, 0.85)]) == [[_A, _B]]  # a cluster today...
    assert build_clusters([(_A, _B, 0.85)], rules=strict) == []  # ...but not then


def test_raising_the_cluster_floor_dissolves_a_cluster(rules: Rules) -> None:
    loose = _retuned(rules, cluster_threshold_floor=0.95)
    assert loose.comparison.cluster_threshold == 0.95
    assert build_clusters([(_A, _B, 0.90)], rules=loose) == []


def test_the_minimum_cluster_size_is_data_pinned_by_value(rules: Rules) -> None:
    """A singleton has no redundancy, so it is not a cluster (hris: ``>= 2``). Whether
    a *pair* is worth harmonizing is an HR call, not a definition — HR-097."""
    assert rules.comparison.min_cluster_size == 2
    big = _retuned(rules, min_cluster_size=3)
    edges = [(_A, _B, 0.9), (_C, _D, 0.9), (_D, _E, 0.9)]
    assert len(build_clusters(edges)) == 2  # {A,B} and {C,D,E}
    assert [set(c) for c in build_clusters(edges, rules=big)] == [{_C, _D, _E}]


def test_the_algorithm_stamp_is_data(rules: Rules) -> None:
    """Connected components is the deliberate Iteration-1 choice (simple, explainable);
    Louvain is the documented fallback if it over-merges on the real corpus. The stamp
    that says which one produced a cluster is data, not a Python constant."""
    assert rules.comparison.cluster_algo == "connected_components"


def test_an_explicit_threshold_still_overrides_the_rulebook() -> None:
    """The hris signature is preserved: a caller may pass its own threshold (every
    ported test above does). The rulebook only supplies the *default*."""
    assert build_clusters([(_A, _B, 0.5)], threshold=0.4) == [[_A, _B]]


# --- the stamp cannot lie (backlog: "`comparison.cluster_algo` can lie") -------
#
# It used to be `str = Field(min_length=1)`. So setting it to `louvain` STAMPED every
# cluster `louvain` while `build_clusters` went right on running connected components
# — a provenance falsehood (CLAUDE.md non-negotiable #6) in whatever Phase 3 persists.
# HANDOFF: "fix before Phase 3 writes a cluster row." Two independent locks, because
# either alone leaves a hole:
#   1. the LOADER rejects an algorithm nobody implemented (a data-only switch cannot
#      even be spelled), and
#   2. `build_clusters` DISPATCHES on the stamp, so the stamp genuinely SELECTS the
#      algorithm instead of merely describing it. Add Louvain and the stamp starts
#      choosing it; forget to add it and (1) already stopped you.


def test_naming_an_unimplemented_algorithm_fails_the_rulebook_to_load(
    rules: Rules,
) -> None:
    """The landmine, disarmed: `louvain` is not implemented, so it may not be said."""
    with pytest.raises(ValueError):
        _retuned(rules, cluster_algo="louvain")
    with pytest.raises(ValueError):
        _retuned(rules, cluster_algo="anything_at_all")


def test_the_stamp_selects_the_algorithm_rather_than_merely_describing_it(
    rules: Rules,
) -> None:
    """`build_clusters` looks the algorithm UP by its stamp. A rulebook naming one we
    do not implement cannot reach here (the loader stops it) — but if it ever did, the
    run fails loudly instead of silently mislabelling clusters."""
    assert set(CLUSTER_ALGORITHMS) == {"connected_components"}
    assert rules.comparison.cluster_algo in CLUSTER_ALGORITHMS

    rogue = rules.model_copy(
        update={
            "comparison": rules.comparison.model_copy(
                update={"cluster_algo": "louvain"}
            )
        }
    )
    with pytest.raises(RulesError, match="louvain"):
        build_clusters([(_A, _B, 0.9)], rules=rogue)

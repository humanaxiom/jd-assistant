"""``comparison.yaml`` (Phase 3.5) — the rulebook side of role clustering.

The six clustering knobs (HR-161…HR-166) live in the HASHED ``comparison.yaml`` beside
the similarity/clustering maths they configure, so moving one churns ``rules_version``.
Each is proved on the decision surface, registered, and pinned BY MUTATION; and the
``cluster_tiers`` value is proved to be DATA the admit gate actually reads.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from src.jd_core.rules import (
    RULE_FILES,
    Rules,
    RulesError,
    check_register,
    decision_surface,
    get_rules,
    load_rules,
)

_PKG_DIR = Path(__file__).resolve().parents[2] / "src" / "jd_core" / "rules"

_CLUSTER_PATHS = (
    "comparison.cluster_tiers",
    "comparison.cluster_role_equiv_min",
    "comparison.cluster_max_band_spread",
    "comparison.cluster_group_homogeneous",
    "comparison.cluster_max_size",
    "comparison.cluster_representative_policy",
    "comparison.singleton_role_policy",
)


@pytest.fixture(scope="module")
def rules() -> Rules:
    return get_rules()


def _write_valid_rules(directory: Path) -> None:
    for name in RULE_FILES:
        (directory / name).write_text(
            (_PKG_DIR / name).read_text(encoding="utf-8"), encoding="utf-8"
        )


def _patch(directory: Path, name: str, mutate: Any) -> None:
    data = yaml.safe_load((directory / name).read_text(encoding="utf-8"))
    mutate(data)
    (directory / name).write_text(yaml.safe_dump(data), encoding="utf-8")


def test_the_cluster_knobs_ship_with_their_measured_values(rules: Rules) -> None:
    c = rules.comparison
    assert set(c.cluster_tiers) == {"exact", "near_duplicate", "role_equivalent"}
    assert c.cluster_role_equiv_min == 0.75
    assert c.cluster_max_band_spread == 1
    assert c.cluster_group_homogeneous is True
    assert c.cluster_max_size == 50
    assert c.cluster_representative_policy == "max_parse_confidence"


def test_every_cluster_knob_is_on_the_surface_and_registered(rules: Rules) -> None:
    register = rules.decision_register
    accounted = register.registered_paths | register.exempt_paths
    surface = decision_surface(rules)
    for path in _CLUSTER_PATHS:
        assert path in surface, path
        assert path in accounted, path


def test_the_shipped_register_is_in_step(rules: Rules) -> None:
    assert check_register(rules) == ()


def test_moving_the_role_equiv_min_moves_rules_version(tmp_path: Path) -> None:
    baseline = get_rules().version
    _write_valid_rules(tmp_path)
    _patch(
        tmp_path,
        "comparison.yaml",
        lambda d: d.__setitem__("cluster_role_equiv_min", 0.6),
    )
    assert load_rules(tmp_path).version != baseline


def test_moving_the_role_equiv_min_without_the_register_breaks_the_build(
    tmp_path: Path,
) -> None:
    _write_valid_rules(tmp_path)
    _patch(
        tmp_path,
        "comparison.yaml",
        lambda d: d.__setitem__("cluster_role_equiv_min", 0.6),
    )
    problems = check_register(load_rules(tmp_path))
    assert any("HR-162" in problem for problem in problems), problems


def test_an_unimplemented_representative_policy_fails_to_load(tmp_path: Path) -> None:
    """A closed set like ``cluster_algo``: a data-only switch to an unimplemented policy
    is a LOAD error, not a silent report of an anchor the runner never used."""
    _write_valid_rules(tmp_path)
    _patch(
        tmp_path,
        "comparison.yaml",
        lambda d: d.__setitem__("cluster_representative_policy", "louvain"),
    )
    with pytest.raises(RulesError):
        load_rules(tmp_path)


def test_the_dead_knob_resolution_is_registered(rules: Rules) -> None:
    """``cluster_threshold`` / ``cluster_threshold_floor`` are RETIRED for the cluster
    path (``build_clusters(threshold=0.0)`` bypasses them). That resolution must be on
    HR-095/HR-096 so the dead knob is not left silently dead."""
    by_id = {d.id: d for d in rules.decision_register.decisions}
    for hid in ("HR-095", "HR-096"):
        text = (by_id[hid].impact_if_changed + by_id[hid].why_it_matters).lower()
        assert "retired" in text and "cluster_role_equiv_min" in (
            by_id[hid].impact_if_changed + by_id[hid].why_it_matters
        )


# ── HR-223: what the Bank does with a job that has no twin ───────────────────


def test_the_singleton_role_policy_ships_as_drop(rules: Rules) -> None:
    """Today a one-of-a-kind job produces NOTHING, and that is now stated as data.

    Measured by ``make singletons`` against the live Bank (2026-08-29, v7): 1,222 parsed
    documents carry no ``dedup_edges`` row at either end and 1,204 of them are in no
    role, so clustering — which takes EDGES as its only input — never considers them.
    462 of those carry a title appearing exactly once in the archive. The behaviour is
    deliberate and unratified, so it is registered rather than patched (HR-223).

    ⚠ The numbers live in :mod:`src.jd_bank.singletons`, not here. This asserts the
    POLICY, because a test that pinned the counts would go red on every re-parse — and
    the first measurement of this population was stale within a day.
    """
    assert rules.comparison.singleton_role_policy == "drop"


def test_an_unimplemented_singleton_policy_fails_to_load(tmp_path: Path) -> None:
    """A closed set like ``cluster_algo``: naming a policy nothing implements is a LOAD
    error, not a silently ignored setting.

    ``mint_role`` and ``queue_for_authoring`` are the two alternatives HR-223 puts to
    HR. Neither is built, so neither may be selectable — a data-only switch to an
    unimplemented policy would drop every one-of-a-kind job exactly as ``drop`` does
    while *reporting* that it had minted roles.
    """
    _write_valid_rules(tmp_path)
    _patch(
        tmp_path,
        "comparison.yaml",
        lambda d: d.__setitem__("singleton_role_policy", "mint_role"),
    )
    with pytest.raises(RulesError):
        load_rules(tmp_path)


def test_dropping_a_singleton_is_enforced_by_the_models_not_only_the_policy(
    rules: Rules,
) -> None:
    """The WHY behind ``drop``: two independent ``ge=2`` floors, not one knob.

    ``comparison.min_cluster_size`` (HR-097) is validated ``ge=2`` in the loader and
    ``ClusterRecord.member_count`` is validated ``ge=2`` in the cluster models. So
    flipping HR-097 to 1 does NOT make a one-of-a-kind job into a role — it fails to
    load. Enacting HR-223 is a code change in both places, which is precisely why the
    decision is registered before anything is built.
    """
    from pydantic import ValidationError

    from src.jd_bank.cluster.models import ClusterRecord

    assert rules.comparison.min_cluster_size == 2
    with pytest.raises(ValidationError):
        ClusterRecord.model_validate(
            {
                "cluster_id": "00000000-0000-0000-0000-000000000001",
                "label": "a job with no twin",
                "member_count": 1,
                "titles": (),
                "departments": (),
                "employee_groups": (),
                "distinct_titles": 0,
                "cross_department": False,
                "cross_group": False,
            }
        )

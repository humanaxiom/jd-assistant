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

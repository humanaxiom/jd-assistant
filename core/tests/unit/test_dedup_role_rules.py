"""``comparison.yaml`` (Phase 3.4b) — the rulebook side of Tier-3 role-equivalence.

The six new knobs (HR-155…HR-160) live in the HASHED ``comparison.yaml`` (unlike
Tier-2's unhashed ``dedup.yaml``): they sit beside the similarity maths they configure,
so moving one churns ``rules_version``. Every knob is proved on the decision surface,
registered, and pinned BY MUTATION — and the family->band ladder is proved to be DATA,
never hardcoded in the runner.
"""

from __future__ import annotations

import re
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
_ROLE_DIR = Path(__file__).resolve().parents[2] / "src" / "jd_bank" / "dedup" / "role"

#: The HR-059 seniority ladder rungs that ``family_band_ladder`` maps to bands. If one
#: of these appears as a whole word in the Tier-3 source, the map is not DATA.
_FAMILY_NAMES = ("vp", "chief", "director", "manager", "lead", "associate", "assistant")


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


def test_the_role_equiv_knobs_ship_with_their_measured_values(rules: Rules) -> None:
    c = rules.comparison
    assert c.role_equiv_threshold == 0.5
    assert c.max_band_gap == 1
    assert c.group_conflict_veto is True
    assert c.candidate_k == 25
    assert c.seed_from_near_dup is True
    assert dict(c.family_band_ladder) == {
        "vp": 6,
        "chief": 5,
        "director": 4,
        "manager": 3,
        "lead": 2,
        "associate": 1,
        "assistant": 0,
    }


def test_every_role_equiv_knob_is_on_the_surface_and_registered(rules: Rules) -> None:
    register = rules.decision_register
    accounted = register.registered_paths | register.exempt_paths
    for path in (
        "comparison.role_equiv_threshold",
        "comparison.family_band_ladder",
        "comparison.max_band_gap",
        "comparison.group_conflict_veto",
        "comparison.candidate_k",
        "comparison.seed_from_near_dup",
    ):
        assert path in decision_surface(rules), path
        assert path in accounted, path


def test_the_shipped_register_is_in_step(rules: Rules) -> None:
    assert check_register(rules) == ()


def test_moving_role_equiv_threshold_moves_rules_version(tmp_path: Path) -> None:
    """``comparison.yaml`` is HASHED, so a role-equiv retune churns ``rules_version`` —
    unlike Tier-2's ``dedup.yaml``, whose knobs cannot move a JD's score. That is why
    these knobs live in comparison.yaml, and it is pinned here."""
    baseline = get_rules().version
    _write_valid_rules(tmp_path)
    _patch(
        tmp_path,
        "comparison.yaml",
        lambda d: d.__setitem__("role_equiv_threshold", 0.75),
    )
    assert load_rules(tmp_path).version != baseline


def test_moving_role_equiv_threshold_without_the_register_breaks_the_build(
    tmp_path: Path,
) -> None:
    _write_valid_rules(tmp_path)
    _patch(
        tmp_path,
        "comparison.yaml",
        lambda d: d.__setitem__("role_equiv_threshold", 0.75),
    )
    problems = check_register(load_rules(tmp_path))
    assert any("HR-158" in problem for problem in problems), problems


def test_the_family_band_ladder_is_data_not_hardcoded_in_the_runner() -> None:
    """The family->band map is rulebook DATA (non-negotiable #2). No band-ladder family
    name may appear as a whole word anywhere in the Tier-3 logic — the runner reads
    bands from ``comparison.family_band_ladder``, so renaming a family is a data edit.
    """
    pattern = re.compile(r"\b(" + "|".join(_FAMILY_NAMES) + r")\b", re.IGNORECASE)
    for source in _ROLE_DIR.glob("*.py"):
        text = source.read_text(encoding="utf-8")
        assert not pattern.search(text), f"{source.name} hardcodes a family name"


def test_giving_unmapped_a_band_fails_to_load(tmp_path: Path) -> None:
    """``unmapped`` is 70% of titles and carries no seniority signal; a band FOR it
    would silently veto them all — the "gate that fires when it must not". A load error.
    """
    _write_valid_rules(tmp_path)
    _patch(
        tmp_path,
        "comparison.yaml",
        lambda d: d["family_band_ladder"].__setitem__("unmapped", 7),
    )
    with pytest.raises(RulesError, match="unmapped"):
        load_rules(tmp_path)

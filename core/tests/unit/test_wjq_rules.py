"""``wjq.yaml`` (Phase 3.4) — the rulebook side of the CUPE/WJQ template map.

The MIRROR IMAGE of ``test_dedup_rules.py`` / ``test_embeddings_rules.py``: those files
are registered but UNHASHED (retuning them cannot move a JD's score). ``wjq.yaml`` is
the opposite — it decides which text becomes a WJQ JD's summary/duties/qualifications,
so it IS hashed, and editing a heading MUST move ``rules_version``. Every knob is on the
decision surface, and the hash move is proved by MUTATION, not by reading a value back.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from src.jd_core.rules import (
    RULE_FILES,
    Rules,
    Wjq,
    check_register,
    decision_surface,
    get_rules,
    load_rules,
    loader,
)

_PKG_DIR = Path(__file__).resolve().parents[2] / "src" / "jd_core" / "rules"


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


def test_wjq_yaml_ships_and_loads(rules: Rules) -> None:
    assert "wjq.yaml" in RULE_FILES
    assert (_PKG_DIR / "wjq.yaml").is_file()
    assert isinstance(rules.wjq, Wjq)
    assert rules.wjq.version == rules.declared_version


def test_the_shipped_wjq_defaults(rules: Rules) -> None:
    w = rules.wjq
    assert w.marker_primary == ("WEIGHTED JOB QUESTIONNAIRE",)
    assert set(w.marker_corroborating) == {"LOCAL 3338", "C.U.P.E"}
    assert w.corroborating_min == 2
    assert w.employee_group == "cupe"
    assert set(w.section_headings) == {
        "position_identification",
        "position_summary",
        "major_functions",
        "minor_functions",
        "level_of_independence",
        "training_exercised",
        "direction_exercised",
        "internal_external_contacts",
        "impact_of_errors",
        "effort",
        "working_conditions",
        "continuing_education",
        "qualifications",
        "approval_review",
    }
    assert w.frequency_markers == {
        "D": "daily",
        "W": "weekly",
        "M": "monthly",
        "S": "semester",
    }
    # decision_making / problem_solving get no WJQ section — they stay empty by design.
    assert "impact_of_errors" in w.context_sections


# --- HASHED, unlike segmentation/embeddings/dedup -------------------------------


def test_wjq_is_hashed_not_in_the_unhashed_set(rules: Rules) -> None:
    assert "wjq.yaml" not in loader._UNHASHED_FILES
    assert "wjq" in loader._HASHED_FIELDS


def test_editing_a_wjq_heading_moves_rules_version(
    tmp_path: Path, rules: Rules
) -> None:
    """**THE property that distinguishes ``wjq.yaml`` from the unhashed files.** A
    heading decides which text becomes a JD's summary/duties/qualifications, so changing
    one changes what the validator computes about a WJQ JD — and ``rules_version`` MUST
    move. (For ``dedup.yaml`` the equivalent mutation deliberately does NOT move it.)"""
    _write_valid_rules(tmp_path)

    def _mutate(data: dict[str, Any]) -> None:
        data["section_headings"]["major_functions"] = ["PRIMARY FUNCTIONS"]

    _patch(tmp_path, "wjq.yaml", _mutate)
    retuned = load_rules(tmp_path)
    assert retuned.version != rules.version
    assert retuned.content_hash != rules.content_hash


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("marker_primary", ["WJQ CUSTOM"]),
        # keep two corroborating markers so `corroborating_min: 2` stays reachable —
        # the reachability validator has its own load-error test below.
        ("marker_corroborating", ["LOCAL 3338", "CUPE 3338"]),
        ("corroborating_min", 1),
        ("employee_group", "excluded"),
        ("continued_marker", "(CONT'D)"),
        ("frequency_markers", {"D": "daily"}),
        ("frequency_headings", {"DAILY": "daily"}),
        ("instruction_markers", ["check one"]),
    ],
)
def test_changing_any_scalar_wjq_knob_moves_the_stamp(
    tmp_path: Path, rules: Rules, field: str, value: object
) -> None:
    """Every simple knob, individually: change it and both ``Wjq.stamp`` AND
    ``rules_version`` move (it is a hashed file)."""
    _write_valid_rules(tmp_path)
    _patch(tmp_path, "wjq.yaml", lambda d: d.__setitem__(field, value))
    retuned = load_rules(tmp_path)
    assert retuned.wjq.stamp != rules.wjq.stamp
    assert retuned.version != rules.version


def test_changing_a_mapping_wjq_knob_moves_the_stamp(
    tmp_path: Path, rules: Rules
) -> None:
    _write_valid_rules(tmp_path)
    _patch(
        tmp_path,
        "wjq.yaml",
        lambda d: d["id_labels"].__setitem__("title", ["Job Title"]),
    )
    retuned = load_rules(tmp_path)
    assert retuned.wjq.stamp != rules.wjq.stamp
    assert retuned.version != rules.version


# --- on the decision surface + registered ---------------------------------------


def test_every_wjq_field_is_on_the_decision_surface(rules: Rules) -> None:
    surface = decision_surface(rules)
    for field in type(rules.wjq).model_fields:
        if field == "version":
            continue
        assert f"wjq.{field}" in surface, field


def test_the_shipped_register_is_in_step(rules: Rules) -> None:
    assert check_register(rules) == ()


# --- load-time invariants -------------------------------------------------------


def test_section_headings_must_cover_all_14(tmp_path: Path) -> None:
    _write_valid_rules(tmp_path)
    _patch(tmp_path, "wjq.yaml", lambda d: d["section_headings"].pop("approval_review"))
    with pytest.raises(loader.RulesError):
        load_rules(tmp_path)


def test_employee_group_must_be_a_known_group(tmp_path: Path) -> None:
    _write_valid_rules(tmp_path)
    _patch(tmp_path, "wjq.yaml", lambda d: d.__setitem__("employee_group", "teamsters"))
    with pytest.raises(loader.RulesError):
        load_rules(tmp_path)


def test_corroborating_min_must_be_reachable(tmp_path: Path) -> None:
    """Needing more corroborating markers than exist is a detection path that can never
    fire — a load error, not a silent miss."""
    _write_valid_rules(tmp_path)
    _patch(tmp_path, "wjq.yaml", lambda d: d.__setitem__("corroborating_min", 3))
    with pytest.raises(loader.RulesError):
        load_rules(tmp_path)

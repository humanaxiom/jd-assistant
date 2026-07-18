"""``quality.yaml`` (Phase 4.2b) — the rulebook side of the LLM nuanced quality-audit
pass.

Mirrors ``test_rewrite_rules.py`` / ``test_dedup_rules.py``: registered but UNHASHED (a
quality-AUDIT-policy change decides how a JD is *audited* — advisory — not how it is
*scored/approved*), every knob on the decision surface, and the unhashed property proved
BY MUTATION — flip a value in the shipped YAML and reload, never merely read it back.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from src.jd_core.rules import (
    RULE_FILES,
    QualityAuditRules,
    Rules,
    check_register,
    decision_surface,
    get_rules,
    live_value,
    load_rules,
    loader,
)

_PKG_DIR = Path(__file__).resolve().parents[2] / "src" / "jd_core" / "rules"

_KNOBS = (
    "model",
    "temperature",
    "max_tokens",
    "max_retries",
    "prompt_version",
    "anti_fabrication_enabled",
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


def test_quality_yaml_ships_and_loads(rules: Rules) -> None:
    assert "quality.yaml" in RULE_FILES
    assert (_PKG_DIR / "quality.yaml").is_file()
    assert isinstance(rules.quality, QualityAuditRules)
    assert rules.quality.version == rules.declared_version


def test_the_provisional_defaults_are_what_the_yaml_ships(rules: Rules) -> None:
    q = rules.quality
    assert q.model == "gpt-oss:120b"
    assert q.temperature == 0.0
    assert q.max_tokens == 1024
    assert q.max_retries == 1
    assert q.prompt_version == "jd_quality_v1"
    assert q.anti_fabrication_enabled is True


# --- registered, on the surface, unhashed ---------------------------------------


def test_quality_is_an_unhashed_file(rules: Rules) -> None:
    assert "quality.yaml" in loader._UNHASHED_FILES
    assert "quality" not in loader._HASHED_FIELDS


def test_every_quality_knob_is_on_the_decision_surface(rules: Rules) -> None:
    surface = decision_surface(rules)
    for knob in _KNOBS:
        assert f"quality.{knob}" in surface


def test_every_quality_knob_is_registered_and_in_step(rules: Rules) -> None:
    """The shipped register accounts for every quality knob and none has drifted."""
    assert check_register(rules) == ()
    registered = rules.decision_register.registered_paths
    for knob in _KNOBS:
        assert f"quality.{knob}" in registered
        live_value(rules, f"quality.{knob}")  # per-knob drift check


def test_retuning_a_quality_knob_leaves_rules_version_untouched(
    tmp_path: Path, rules: Rules
) -> None:
    """**THE property this arrangement exists for.** Retuning a quality-audit knob
    changes how a JD is AUDITED (advisory), never how a JD is SCORED, so it must NOT
    move ``Rules.version``. Proved by mutating the shipped YAML and reloading."""
    _write_valid_rules(tmp_path)
    _patch(tmp_path, "quality.yaml", lambda d: d.__setitem__("max_tokens", 4096))
    retuned = load_rules(tmp_path)

    assert retuned.version == rules.version
    assert retuned.content_hash == rules.content_hash
    assert retuned.quality.max_tokens == 4096


def test_editing_a_real_rule_file_still_moves_rules_version(
    tmp_path: Path, rules: Rules
) -> None:
    """The other half — else the test above would pass on a hash tracking nothing."""
    _write_valid_rules(tmp_path)
    _patch(tmp_path, "thresholds.yaml", lambda d: d.__setitem__("duties_max", 9))
    assert load_rules(tmp_path).version != rules.version


def test_a_smuggled_quality_knob_is_rejected(tmp_path: Path) -> None:
    """`quality.yaml` is flat + ``extra="forbid"``: a tunable cannot be added without
    the loader seeing it (and the surface coverage check demanding registration)."""
    _write_valid_rules(tmp_path)
    _patch(tmp_path, "quality.yaml", lambda d: d.__setitem__("fudge_factor", 1.5))
    with pytest.raises(loader.RulesError):
        load_rules(tmp_path)


def test_an_out_of_range_temperature_is_rejected(tmp_path: Path) -> None:
    _write_valid_rules(tmp_path)
    _patch(tmp_path, "quality.yaml", lambda d: d.__setitem__("temperature", 9.0))
    with pytest.raises(loader.RulesError):
        load_rules(tmp_path)

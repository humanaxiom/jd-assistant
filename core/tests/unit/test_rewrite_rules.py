"""``rewrite.yaml`` (Phase 4.2a) — the rulebook side of the LLM rewrite pass.

Mirrors ``test_dedup_rules.py`` / ``test_embeddings_rules.py``: registered but UNHASHED
(a rewrite-policy change decides how a draft is WORDED, not how a JD is SCORED), every
knob on the decision surface, and the unhashed property proved BY MUTATION — flip a
value in the shipped YAML and reload, never merely read the number back.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from src.jd_core.rules import (
    RULE_FILES,
    Rewrite,
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
    "skill_grounding_policy",
    "skill_grounding_threshold",
    "duty_flag_threshold",
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


def test_rewrite_yaml_ships_and_loads(rules: Rules) -> None:
    assert "rewrite.yaml" in RULE_FILES
    assert (_PKG_DIR / "rewrite.yaml").is_file()
    assert isinstance(rules.rewrite, Rewrite)
    assert rules.rewrite.version == rules.declared_version


def test_the_provisional_defaults_are_what_the_yaml_ships(rules: Rules) -> None:
    r = rules.rewrite
    assert r.model == "gpt-oss:120b"
    assert r.temperature == 0.0
    assert r.max_tokens == 2048
    assert r.max_retries == 1
    # v2 since CUPE Phase D: v1 inlined SFU's JDFN duty count and summary band as prompt
    # TEXT, which on a CUPE draft asks for 3–5 duties against a twelve-slot form. v1 is
    # kept on disk unedited — every draft in the archive carries its stamp.
    assert r.prompt_version == "jd_harmonize_v2"
    assert r.anti_fabrication_enabled is True
    assert r.skill_grounding_policy == "token_overlap"
    assert r.skill_grounding_threshold == 0.5
    assert r.duty_flag_threshold == 0.2


# --- registered, on the surface, unhashed ---------------------------------------


def test_rewrite_is_an_unhashed_file(rules: Rules) -> None:
    assert loader._UNHASHED_FILES == {
        "decision_register.yaml",
        "segmentation.yaml",
        "embeddings.yaml",
        "dedup.yaml",
        "harmonization.yaml",
        "rewrite.yaml",
        # 4.2b added `quality.yaml` — the seventh unhashed file (test_quality_rules).
        "quality.yaml",
    }
    assert "rewrite" not in loader._HASHED_FIELDS


def test_every_rewrite_knob_is_on_the_decision_surface(rules: Rules) -> None:
    surface = decision_surface(rules)
    for knob in _KNOBS:
        assert f"rewrite.{knob}" in surface


def test_every_rewrite_knob_is_registered_and_in_step(rules: Rules) -> None:
    """The shipped register accounts for every rewrite knob and none has drifted."""
    assert check_register(rules) == ()
    registered = rules.decision_register.registered_paths
    for knob in _KNOBS:
        assert f"rewrite.{knob}" in registered
        # ...and its current_default matches the live value (drift check, per knob)
        live_value(rules, f"rewrite.{knob}")


def test_retuning_a_rewrite_knob_leaves_rules_version_untouched(
    tmp_path: Path, rules: Rules
) -> None:
    """**THE property this arrangement exists for.** Retuning a rewrite knob rewords a
    draft; it cannot move a single JD's score, so it must NOT move ``Rules.version``.
    Proved by mutating the shipped YAML and reloading, never by reading the list."""
    _write_valid_rules(tmp_path)
    _patch(
        tmp_path,
        "rewrite.yaml",
        lambda d: d.__setitem__("skill_grounding_threshold", 0.9),
    )
    retuned = load_rules(tmp_path)

    assert retuned.version == rules.version
    assert retuned.content_hash == rules.content_hash
    assert retuned.rewrite.skill_grounding_threshold == 0.9


def test_editing_a_real_rule_file_still_moves_rules_version(
    tmp_path: Path, rules: Rules
) -> None:
    """The other half — else the test above would pass on a hash tracking nothing."""
    _write_valid_rules(tmp_path)
    _patch(tmp_path, "thresholds.yaml", lambda d: d.__setitem__("duties_max", 9))
    assert load_rules(tmp_path).version != rules.version


def test_a_smuggled_rewrite_knob_is_rejected(tmp_path: Path) -> None:
    """`rewrite.yaml` is flat + ``extra="forbid"``: a tunable number cannot be added to
    it without the loader seeing it (and the surface coverage check demanding it be
    registered)."""
    _write_valid_rules(tmp_path)
    _patch(tmp_path, "rewrite.yaml", lambda d: d.__setitem__("fudge_factor", 1.5))
    with pytest.raises(loader.RulesError):
        load_rules(tmp_path)


def test_an_out_of_range_threshold_is_rejected(tmp_path: Path) -> None:
    _write_valid_rules(tmp_path)
    _patch(
        tmp_path,
        "rewrite.yaml",
        lambda d: d.__setitem__("skill_grounding_threshold", 1.5),
    )
    with pytest.raises(loader.RulesError):
        load_rules(tmp_path)

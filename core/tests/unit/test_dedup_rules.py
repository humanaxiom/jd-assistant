"""``dedup.yaml`` (Phase 3.3) — the rulebook side of Tier-2 near-duplicate detection.

Mirrors ``test_embeddings_rules.py``: registered but unhashed, its own content
identity (``Dedup.stamp``), and every knob proved pinned by MUTATION — flip a value
in the shipped YAML and reload, never merely read the number back.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import BaseModel

from src.jd_core.rules import (
    RULE_FILES,
    Dedup,
    Rules,
    check_register,
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


def test_dedup_yaml_ships_and_loads(rules: Rules) -> None:
    assert "dedup.yaml" in RULE_FILES
    assert (_PKG_DIR / "dedup.yaml").is_file()
    assert isinstance(rules.dedup, Dedup)
    assert rules.dedup.version == rules.declared_version


def test_the_measured_defaults_are_what_the_yaml_ships(rules: Rules) -> None:
    """The values HANDOFF measured, not re-derived here — just pinned."""
    d = rules.dedup
    assert d.text_source == "raw_clean"
    assert d.shingle_size == 5
    assert d.redact_boilerplate is True
    assert d.min_shingles == 20
    assert d.num_perm == 128
    assert d.bands == 16
    assert d.rows == 8
    assert d.jaccard_min == 0.85
    assert d.cosine_confirm_min is None
    assert d.edge_scope == "content"
    assert d.max_candidate_pairs == 250_000


def test_s_curve_threshold_matches_the_shipped_bands_and_rows(rules: Rules) -> None:
    assert rules.dedup.s_curve_threshold == pytest.approx((1 / 16) ** (1 / 8))


# --- unhashed, but registered ---------------------------------------------------


def test_dedup_is_the_fourth_unhashed_file(rules: Rules) -> None:
    assert loader._UNHASHED_FILES == {
        "decision_register.yaml",
        "segmentation.yaml",
        "embeddings.yaml",
        "dedup.yaml",
        # Phase 4.1 added a fifth: the harmonization merge engine's knobs.
        "harmonization.yaml",
        # Phase 4.2a added a sixth: the LLM rewrite pass's knobs.
        "rewrite.yaml",
        # Phase 4.2b added a seventh: the LLM quality-audit pass's knobs.
        "quality.yaml",
        # Phase A2 added an eighth: which roles a named FUNCTION gathers, for browsing.
        "functional_families.yaml",
    }
    assert "dedup" not in loader._HASHED_FIELDS


def test_retuning_jaccard_min_leaves_rules_version_untouched(
    tmp_path: Path, rules: Rules
) -> None:
    """**THE property this arrangement exists for.** Retuning the Tier-2 similarity
    threshold cannot move a single JD's score, so it must not move ``Rules.version``
    — but it DOES move ``Dedup.stamp``, which is what ``DedupEdge.method`` embeds,
    and that is what makes a stale edge visible in the row itself."""
    _write_valid_rules(tmp_path)
    _patch(tmp_path, "dedup.yaml", lambda d: d.__setitem__("jaccard_min", 0.9))
    retuned = load_rules(tmp_path)

    assert retuned.version == rules.version
    assert retuned.content_hash == rules.content_hash
    assert retuned.dedup.jaccard_min == 0.9
    assert retuned.dedup.stamp != rules.dedup.stamp


def test_editing_a_real_rule_file_still_moves_rules_version(
    tmp_path: Path, rules: Rules
) -> None:
    """The other half — otherwise the test above would pass on a hash tracking
    nothing at all."""
    _write_valid_rules(tmp_path)
    _patch(tmp_path, "thresholds.yaml", lambda d: d.__setitem__("duties_max", 9))
    assert load_rules(tmp_path).version != rules.version


#: knob (dotted for a nested leaf) -> a value to retune it to. Named rather than
#: inlined so the closed-world check below can assert against the LIST ITSELF, not
#: against a hand-kept copy of it that could drift out of step with it.
_STAMP_MUTATIONS: list[tuple[str, object]] = [
    ("text_source", "serialized"),
    ("shingle_size", 4),
    ("redact_boilerplate", False),
    ("min_shingles", 5),
    ("num_perm", 64),
    ("bands", 32),
    ("rows", 2),
    ("jaccard_min", 0.9),
    ("cosine_confirm_min", 0.9),
    ("edge_scope", "file"),
    ("max_candidate_pairs", 1000),
    # Phase 5.9's NESTED block, one LEAF at a time — a block mutated wholesale would
    # pass with only one of its fields actually pinned.
    ("authoring_guard.max_matches", 3),
    ("authoring_guard.min_draft_chars", 250),
    ("authoring_guard.timeout_seconds", 2.5),
]


@pytest.mark.parametrize(("field", "value"), _STAMP_MUTATIONS)
def test_changing_any_dedup_knob_moves_the_stamp(
    tmp_path: Path, rules: Rules, field: str, value: object
) -> None:
    """Every field, individually: change it and ``Dedup.stamp`` moves — the identity
    that rides in ``DedupEdge.method`` and forces a Tier-2 reconcile."""
    _write_valid_rules(tmp_path)

    def _mutate(data: dict[str, Any]) -> None:
        if "." in field:  # a leaf inside a nested block, e.g. `authoring_guard.x`
            block, leaf = field.split(".", 1)
            data[block][leaf] = value
            return
        data[field] = value
        if field in ("bands", "rows"):
            # keep bands*rows == num_perm so the mutation exercises ONLY the field
            # under test, not the cross-validator (that has its own test below).
            other = "rows" if field == "bands" else "bands"
            data[other] = data["num_perm"] // value
        if field == "num_perm":
            # keep bands*rows == num_perm — pick a banding that still divides it.
            data["bands"] = 16
            data["rows"] = value // 16

    _patch(tmp_path, "dedup.yaml", _mutate)
    retuned = load_rules(tmp_path)
    assert retuned.dedup.stamp != rules.dedup.stamp
    # ...and it still does not move the rulebook's own identity.
    assert retuned.version == rules.version


def _declared_knob_paths(model: type[BaseModel], prefix: str = "") -> set[str]:
    """Every LEAF of a rule model, dotted. Walks nested blocks: a knob added inside
    ``authoring_guard`` is a knob, and a top-level-only view would not see it."""
    paths: set[str] = set()
    for name, field in model.model_fields.items():
        if name == "version":
            continue
        annotation = field.annotation
        if isinstance(annotation, type) and issubclass(annotation, BaseModel):
            paths |= _declared_knob_paths(annotation, f"{prefix}{name}.")
        else:
            paths.add(f"{prefix}{name}")
    return paths


def test_every_dedup_knob_is_in_the_stamp_parametrize_list() -> None:
    """The guard on the guard: the parametrize list above says "every field", so a
    knob added to ``dedup.yaml`` tomorrow must be added to it — or this fails.

    Enumerated to the LEAF, so a knob added inside the nested ``authoring_guard``
    block trips this too. A top-level ``set(Dedup.model_fields)`` would have been
    satisfied by the block's mere existence and let a new field inside it ship with
    nothing proving it moves the stamp."""
    covered = {
        "text_source",
        "shingle_size",
        "redact_boilerplate",
        "min_shingles",
        "num_perm",
        "bands",
        "rows",
        "jaccard_min",
        "cosine_confirm_min",
        "edge_scope",
        "max_candidate_pairs",
        # Phase 5.9 — the Builder's authoring guard. This test firing is exactly how
        # these got here.
        "authoring_guard.max_matches",
        "authoring_guard.min_draft_chars",
        "authoring_guard.timeout_seconds",
    }
    declared = _declared_knob_paths(Dedup)
    assert declared == covered, sorted(declared.symmetric_difference(covered))
    # ...and "covered" means covered by the parametrize list above, not by this set.
    assert covered == {field for field, _ in _STAMP_MUTATIONS}


# --- the bands*rows == num_perm cross-validator ----------------------------------


def test_bands_times_rows_not_equal_num_perm_refuses_to_load(tmp_path: Path) -> None:
    _write_valid_rules(tmp_path)
    _patch(tmp_path, "dedup.yaml", lambda d: d.__setitem__("bands", 33))  # 33*4 != 128
    with pytest.raises(loader.RulesError, match="bands.*rows.*must equal num_perm"):
        load_rules(tmp_path)


def test_bands_times_rows_equal_num_perm_loads_fine(tmp_path: Path) -> None:
    _write_valid_rules(tmp_path)

    def _mutate(data: dict[str, Any]) -> None:
        data["bands"] = 16
        data["rows"] = 8  # 16*8 == 128, still matches num_perm

    _patch(tmp_path, "dedup.yaml", _mutate)
    retuned = load_rules(tmp_path)
    assert retuned.dedup.bands == 16
    assert retuned.dedup.rows == 8


# --- registered, and drift-checked -----------------------------------------------


def test_retuning_jaccard_min_without_the_register_breaks_the_build(
    tmp_path: Path,
) -> None:
    _write_valid_rules(tmp_path)
    _patch(tmp_path, "dedup.yaml", lambda d: d.__setitem__("jaccard_min", 0.5))
    problems = check_register(load_rules(tmp_path))
    assert any("HR-138" in problem for problem in problems), problems


def test_flipping_edge_scope_without_the_register_breaks_the_build(
    tmp_path: Path,
) -> None:
    _write_valid_rules(tmp_path)
    _patch(tmp_path, "dedup.yaml", lambda d: d.__setitem__("edge_scope", "file"))
    problems = check_register(load_rules(tmp_path))
    assert any("HR-140" in problem for problem in problems), problems


def test_max_candidate_pairs_is_a_trivial_exemption_not_a_registered_decision(
    rules: Rules,
) -> None:
    register = rules.decision_register
    assert "dedup.max_candidate_pairs" in register.exempt_paths
    assert "dedup.max_candidate_pairs" not in register.registered_paths


def test_the_dedup_defaults_are_registered_as_nobodys_standard(rules: Rules) -> None:
    """Provenance honesty (the HR-029 / HR-059 lesson). SFU publishes no
    near-duplicate policy, and hris had none either — Tier-2 dedup is new work."""
    entries = [
        d for d in rules.decision_register.decisions if d.config.file == "dedup.yaml"
    ]
    # 10 Tier-2 knobs (HR-131…HR-140) + the 3 Phase-5.9 authoring-guard knobs
    # (HR-195/HR-196/HR-197). `max_candidate_pairs` is the one trivial exemption.
    assert len(entries) == 13, "dedup.yaml should have exactly 13 registered fields"
    for decision in entries:
        assert decision.provenance == "our_invention", decision.id
        assert decision.source_part is None, decision.id
        assert decision.status == "open", decision.id


def test_register_is_clean_on_the_shipped_rulebook(rules: Rules) -> None:
    assert check_register(rules) == ()


# --- Phase 5.9: the near-duplicate AUTHORING GUARD's own knobs -------------------
#
# `dedup.authoring_guard` (`max_matches` / `min_draft_chars`) is new surface for the
# JD Builder's advisory "roles that look like this one" panel (see
# `jd_bank/composer/duplicates.py`). It lives INSIDE `dedup.yaml` — not a new file —
# so it inherits the same unhashed/registered treatment this whole file exists to
# pin: retuning how MANY matches the Builder shows, or how long a draft must be
# before it bothers embedding, cannot move a single JD's ValidationReport score.


def test_authoring_guard_defaults_load(rules: Rules) -> None:
    guard = rules.dedup.authoring_guard
    assert guard.max_matches == 5
    assert guard.min_draft_chars == 500
    # The bound on how long the Builder waits for the panel (HR-197). It exists
    # because the guard's degrade path can catch a RAISE but not a HANG.
    assert guard.timeout_seconds == 5.0


@pytest.mark.parametrize("field", ["max_matches", "min_draft_chars", "timeout_seconds"])
@pytest.mark.parametrize("value", [0, -1])
def test_authoring_guard_non_positive_values_are_rejected(
    tmp_path: Path, field: str, value: int
) -> None:
    _write_valid_rules(tmp_path)

    def _mutate(data: dict[str, Any]) -> None:
        data["authoring_guard"][field] = value

    _patch(tmp_path, "dedup.yaml", _mutate)
    with pytest.raises(loader.RulesError):
        load_rules(tmp_path)


def test_retuning_the_authoring_guard_leaves_rules_version_untouched(
    tmp_path: Path, rules: Rules
) -> None:
    """Mirrors ``test_retuning_jaccard_min_leaves_rules_version_untouched`` for the
    new nested block: the authoring guard's knobs cannot move a single JD's score,
    so they must not move ``Rules.version`` either — only ``Dedup.stamp`` (which
    IS expected to move, exactly like retuning ``jaccard_min`` above)."""
    _write_valid_rules(tmp_path)
    _patch(
        tmp_path,
        "dedup.yaml",
        lambda d: d["authoring_guard"].__setitem__("max_matches", 3),
    )
    retuned = load_rules(tmp_path)

    assert retuned.version == rules.version
    assert retuned.content_hash == rules.content_hash
    assert retuned.dedup.authoring_guard.max_matches == 3
    assert retuned.dedup.stamp != rules.dedup.stamp

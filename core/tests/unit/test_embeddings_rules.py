"""``embeddings.yaml`` (Phase 3.2b) — the rulebook side of the embedding pipeline.

Mirrors the ``segmentation.yaml`` suite in ``test_decision_register.py``: registered
but unhashed, its own content identity (``Embeddings.stamp``), and every knob proved
pinned by MUTATION — flip a value in the shipped YAML and reload, never merely read
the number back.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from src.jd_core.rules import (
    RULE_FILES,
    Embeddings,
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


def test_embeddings_yaml_ships_and_loads(rules: Rules) -> None:
    assert "embeddings.yaml" in RULE_FILES
    assert (_PKG_DIR / "embeddings.yaml").is_file()
    assert isinstance(rules.embeddings, Embeddings)
    assert rules.embeddings.version == rules.declared_version


def test_the_measured_defaults_are_what_the_yaml_ships(rules: Rules) -> None:
    """The values HANDOFF measured, not re-derived here — just pinned."""
    e = rules.embeddings
    assert e.model == "nomic-embed-text"
    assert e.dimensions == 768
    assert e.max_chars == 10_000
    assert e.max_chars_fallback == (8_000, 6_000, 4_000)
    assert e.min_section_chars == 40
    assert e.include_title_in_document is False
    assert e.section_vectors == ("position_summary", "duties", "qualifications")
    assert set(e.section_vectors) <= set(e.document_sections)


# --- unhashed, but registered ---------------------------------------------------


def test_embeddings_is_unhashed(rules: Rules) -> None:
    """``embeddings.yaml`` was the THIRD file added to this category (after
    ``decision_register.yaml`` / ``segmentation.yaml``); ``dedup.yaml`` (Phase 3.3)
    is the fourth — see ``test_dedup_rules.py::test_dedup_is_the_fourth_unhashed_file``
    for the full, current set. This test only pins embeddings' OWN membership."""
    assert "embeddings.yaml" in loader._UNHASHED_FILES
    assert "embeddings" not in loader._HASHED_FIELDS


def test_retuning_max_chars_leaves_rules_version_untouched(
    tmp_path: Path, rules: Rules
) -> None:
    """**THE property this arrangement exists for.** Retuning how much text is sent
    to the embedding model cannot move a single JD's score, so it must not move
    ``Rules.version`` — but it DOES move ``Embeddings.stamp``, which is what a
    Neo4j node is actually written with, and that is what forces the re-embed."""
    _write_valid_rules(tmp_path)
    _patch(tmp_path, "embeddings.yaml", lambda d: d.__setitem__("max_chars", 5_000))
    retuned = load_rules(tmp_path)

    assert retuned.version == rules.version
    assert retuned.content_hash == rules.content_hash
    assert retuned.embeddings.max_chars == 5_000
    assert retuned.embeddings.stamp != rules.embeddings.stamp


def test_editing_a_real_rule_file_still_moves_rules_version(
    tmp_path: Path, rules: Rules
) -> None:
    """The other half — otherwise the test above would pass on a hash tracking
    nothing at all."""
    _write_valid_rules(tmp_path)
    _patch(tmp_path, "thresholds.yaml", lambda d: d.__setitem__("duties_max", 9))
    assert load_rules(tmp_path).version != rules.version


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("model", "a-different-model"),
        ("dimensions", 1024),
        ("max_chars", 4_000),
        ("max_chars_fallback", [7_000, 5_000]),
        ("min_section_chars", 10),
        ("include_title_in_document", True),
        ("document_sections", ["position_summary"]),
        # `section_vectors` was the one field this list was MISSING while the
        # docstring claimed "every field, individually" — the claim was false of the
        # test even though it was true of the code. It is the knob HR-130 explicitly
        # invites HR to change, so it is the last one that should have gone unpinned.
        ("section_vectors", ["position_summary"]),
    ],
)
def test_changing_any_embedding_knob_moves_the_stamp(
    tmp_path: Path, rules: Rules, field: str, value: object
) -> None:
    """Every field, individually: change it and ``Embeddings.stamp`` moves — the
    identity that forces a re-embed. (``document_sections`` is retuned to a
    strict subset here, with ``section_vectors`` narrowed in step, so the
    loader's subset cross-check still holds.)"""
    _write_valid_rules(tmp_path)

    def _mutate(data: dict[str, Any]) -> None:
        data[field] = value
        if field == "document_sections":
            data["section_vectors"] = ["position_summary"]

    _patch(tmp_path, "embeddings.yaml", _mutate)
    retuned = load_rules(tmp_path)
    assert retuned.embeddings.stamp != rules.embeddings.stamp
    # ...and it still does not move the rulebook's own identity.
    assert retuned.version == rules.version


def test_every_embedding_knob_is_in_the_stamp_parametrize_list() -> None:
    """The guard on the guard: the parametrize list above says "every field", so a
    knob added to ``embeddings.yaml`` tomorrow must be added to it — or this fails.
    (``section_vectors`` was silently missing from the first cut, and nothing said so.)
    """
    covered = {
        "model",
        "dimensions",
        "max_chars",
        "max_chars_fallback",
        "min_section_chars",
        "include_title_in_document",
        "document_sections",
        "section_vectors",
    }
    declared = set(Embeddings.model_fields) - {"version"}
    assert declared == covered, sorted(declared.symmetric_difference(covered))


# --- registered, and drift-checked -----------------------------------------------


def test_retuning_max_chars_without_the_register_breaks_the_build(
    tmp_path: Path,
) -> None:
    _write_valid_rules(tmp_path)
    _patch(tmp_path, "embeddings.yaml", lambda d: d.__setitem__("max_chars", 4_000))
    problems = check_register(load_rules(tmp_path))
    assert any("HR-126" in problem for problem in problems), problems


def test_retuning_the_fallback_ladder_without_the_register_breaks_the_build(
    tmp_path: Path,
) -> None:
    """HR-193 is drift-checked exactly like every other embeddings knob."""
    _write_valid_rules(tmp_path)
    _patch(
        tmp_path,
        "embeddings.yaml",
        lambda d: d.__setitem__("max_chars_fallback", [9_000, 5_000]),
    )
    problems = check_register(load_rules(tmp_path))
    assert any("HR-193" in problem for problem in problems), problems


# --- the fallback ladder validates: descending, positive, below max_chars --------


def test_an_empty_fallback_ladder_loads_and_means_no_backoff(tmp_path: Path) -> None:
    """`[]` is legal — it restores the pre-HR-193 behavior (write off a 400), so the
    knob's alternative is real, not decorative."""
    _write_valid_rules(tmp_path)
    _patch(
        tmp_path, "embeddings.yaml", lambda d: d.__setitem__("max_chars_fallback", [])
    )
    assert load_rules(tmp_path).embeddings.max_chars_fallback == ()


@pytest.mark.parametrize(
    "ladder",
    [
        [6_000, 8_000],  # not descending
        [8_000, 8_000],  # not STRICTLY descending
        [8_000, 4_000, 6_000],  # descends then rises
    ],
)
def test_a_non_descending_ladder_fails_to_load(
    tmp_path: Path, ladder: list[int]
) -> None:
    _write_valid_rules(tmp_path)
    _patch(
        tmp_path,
        "embeddings.yaml",
        lambda d: d.__setitem__("max_chars_fallback", ladder),
    )
    with pytest.raises(loader.RulesError, match="strictly descend"):
        load_rules(tmp_path)


def test_a_fallback_rung_at_or_above_max_chars_loads_decoupled(tmp_path: Path) -> None:
    """The ladder is NOT coupled to ``max_chars`` — tuning one must not force the
    other. A rung ≥ ``max_chars`` is harmless (the runner skips it at re-cut time), so
    it loads; only order/positivity are enforced."""
    _write_valid_rules(tmp_path)
    _patch(
        tmp_path,
        "embeddings.yaml",
        lambda d: d.__setitem__("max_chars_fallback", [12_000, 8_000]),  # 12k > max
    )
    assert load_rules(tmp_path).embeddings.max_chars_fallback == (12_000, 8_000)


def test_a_non_positive_fallback_rung_fails_to_load(tmp_path: Path) -> None:
    _write_valid_rules(tmp_path)
    _patch(
        tmp_path,
        "embeddings.yaml",
        lambda d: d.__setitem__("max_chars_fallback", [8_000, 0]),
    )
    with pytest.raises(loader.RulesError, match="non-positive"):
        load_rules(tmp_path)


def test_flipping_include_title_in_document_without_the_register_breaks_the_build(
    tmp_path: Path,
) -> None:
    _write_valid_rules(tmp_path)
    _patch(
        tmp_path,
        "embeddings.yaml",
        lambda d: d.__setitem__("include_title_in_document", True),
    )
    problems = check_register(load_rules(tmp_path))
    assert any("HR-128" in problem for problem in problems), problems


def test_a_section_with_no_producer_fails_to_load(tmp_path: Path) -> None:
    """The loader-level guard, exercised through the full YAML load path (not just
    direct model construction — see ``test_embed_text.py`` for that half)."""
    _write_valid_rules(tmp_path)
    _patch(
        tmp_path,
        "embeddings.yaml",
        lambda d: d["document_sections"].append("about_sfu"),
    )
    with pytest.raises(loader.RulesError, match="no embeddable content"):
        load_rules(tmp_path)


def test_the_embeddings_defaults_are_registered_as_nobodys_standard(
    rules: Rules,
) -> None:
    """Provenance honesty (the HR-029 / HR-059 lesson). SFU publishes no embedding
    policy, and hris had none either — Tier-3 dedup and search are new work."""
    entries = [
        d
        for d in rules.decision_register.decisions
        if d.config.file == "embeddings.yaml"
    ]
    assert len(entries) == 8, "embeddings.yaml should have exactly 8 registered fields"
    for decision in entries:
        assert decision.provenance == "our_invention", decision.id
        assert decision.source_part is None, decision.id
        assert decision.status == "open", decision.id

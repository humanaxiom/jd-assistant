"""The HR decision register — and the enforcement that keeps it honest.

The register (``rules/decision_register.yaml``) records every policy call JD Bank
makes *by default* because SFU HR has not made it. A prose register would rot
silently, and a rotted register is worse than none: it makes an unratified default
look ratified. So the register is **data**, and this suite is what stops it rotting.

Four build-breaking properties, each with a fixture that proves it breaks:

1. **Every ``config`` path resolves** against the real loaded rules — enforced at
   *load* (:class:`RulesError`). Rename a config key and nothing starts.
2. **Every ``current_default`` equals the live value.** Tune a threshold in YAML
   without telling HR and the build fails. *This is what makes "review the config
   against the register later" real.*
3. **Coverage: every parameter on the decision surface is registered or explicitly
   exempted.** The surface is enumerated *from the rules themselves*, so a gate,
   threshold, penalty, band, lexicon tier, restricted title or rule severity added
   later with neither → build fails. (Mirrors 2.3's
   ``test_every_catalogued_rule_is_gated_or_explicitly_not``.)
4. **The register cannot lie about itself:** ``ratified`` requires who/when/why,
   ``open`` forbids it, ids are unique, and a malformed register is a clear
   ``RulesError``.

Plus: nobody may quietly *shrink* the decision surface to make (3) pass — the
surface's own completeness is asserted against the rules, family by family.
"""

from __future__ import annotations

import datetime as dt
import io
from pathlib import Path
from typing import Any, Final, get_args

import pytest
import yaml
from pydantic import BaseModel, ValidationError

from src.jd_core.rules import (
    REGISTER_FILE,
    RULE_FILES,
    DecisionProvenance,
    DecisionStatus,
    DecisionTier,
    Rules,
    RulesError,
    SeverityFloorGate,
    assert_register_in_step,
    check_register,
    decision_surface,
    get_rules,
    live_value,
    load_rules,
    loader,
    normalize_config_value,
    resolve_config_path,
)
from src.jd_core.rules.render import (
    _PROVENANCE_HEADING,
    _TIER_HEADING,
    check_markdown,
    main,
    render_register,
)

# --- fixtures / helpers -------------------------------------------------------

_PKG_DIR = Path(__file__).resolve().parents[2] / "src" / "jd_core" / "rules"


@pytest.fixture
def rules() -> Rules:
    return get_rules()


def _write_valid_rules(directory: Path) -> None:
    """Copy the shipped YAML into ``directory`` so a test can corrupt one file."""
    for name in RULE_FILES:
        (directory / name).write_text(
            (_PKG_DIR / name).read_text(encoding="utf-8"), encoding="utf-8"
        )


def _patch(directory: Path, name: str, mutate: Any) -> None:
    data = yaml.safe_load((directory / name).read_text(encoding="utf-8"))
    mutate(data)
    (directory / name).write_text(yaml.safe_dump(data), encoding="utf-8")


def _decision(register: dict[str, Any], decision_id: str) -> dict[str, Any]:
    for entry in register["decisions"]:
        if entry["id"] == decision_id:
            return dict(entry)
    raise AssertionError(f"no decision {decision_id}")  # pragma: no cover


def _patch_decision(directory: Path, decision_id: str, mutate: Any) -> None:
    def _mutate(data: dict[str, Any]) -> None:
        for entry in data["decisions"]:
            if entry["id"] == decision_id:
                mutate(entry)
                return
        raise AssertionError(f"no decision {decision_id}")  # pragma: no cover

    _patch(directory, REGISTER_FILE, _mutate)


def _gate(data: dict[str, Any], gate_id: str) -> dict[str, Any]:
    """The LIVE gate dict inside ``data`` — callers mutate it in place."""
    for gate in data["gates"]:
        if gate["gate_id"] == gate_id:
            gate_dict: dict[str, Any] = gate
            return gate_dict
    raise AssertionError(f"no gate {gate_id}")  # pragma: no cover


# --- 1. every config path points at a live config key (enforced at LOAD) -------


def test_the_register_ships_and_is_a_versioned_rule_file(rules: Rules) -> None:
    assert REGISTER_FILE in RULE_FILES
    assert (_PKG_DIR / REGISTER_FILE).is_file()
    assert rules.decision_register.version == rules.declared_version


def test_every_config_path_resolves_against_the_live_rules(rules: Rules) -> None:
    register = rules.decision_register
    for decision in register.decisions:
        resolve_config_path(rules, decision.config.path)  # raises if it does not
    for exemption in register.trivial:
        resolve_config_path(rules, exemption.config.path)


def test_a_register_entry_naming_a_dead_config_key_fails_to_load(
    tmp_path: Path,
) -> None:
    """The headline load-time guarantee: rename or delete a config key (or fat-finger
    the register) and the process does not start."""
    _write_valid_rules(tmp_path)
    _patch_decision(
        tmp_path,
        "HR-001",
        lambda d: d["config"].__setitem__(
            "path", "gates.SFU-APPROVE-SCORE-FLOOR.minimum_score"
        ),
    )
    with pytest.raises(RulesError, match="does not resolve"):
        load_rules(tmp_path)


def test_a_config_path_naming_an_unknown_gate_fails_to_load(tmp_path: Path) -> None:
    _write_valid_rules(tmp_path)
    _patch_decision(
        tmp_path,
        "HR-001",
        lambda d: d["config"].__setitem__("path", "gates.SFU-APPROVE-NOPE.min_score"),
    )
    with pytest.raises(RulesError, match="does not resolve"):
        load_rules(tmp_path)


def test_a_config_path_must_be_rooted_in_the_file_it_names(tmp_path: Path) -> None:
    _write_valid_rules(tmp_path)
    _patch_decision(
        tmp_path, "HR-001", lambda d: d["config"].__setitem__("file", "scoring.yaml")
    )
    with pytest.raises(RulesError, match="must start with"):
        load_rules(tmp_path)


def test_a_config_file_must_be_a_real_rule_file(tmp_path: Path) -> None:
    _write_valid_rules(tmp_path)

    def _mutate(entry: dict[str, Any]) -> None:
        entry["config"] = {"file": "invented.yaml", "path": "invented.thing"}

    _patch_decision(tmp_path, "HR-001", _mutate)
    with pytest.raises(RulesError, match="config.file"):
        load_rules(tmp_path)


def test_the_register_may_not_point_at_itself(tmp_path: Path) -> None:
    """A register entry about the register would be circular — and meaningless."""
    _write_valid_rules(tmp_path)

    def _mutate(entry: dict[str, Any]) -> None:
        entry["config"] = {
            "file": REGISTER_FILE,
            "path": "decision_register.version",
        }

    _patch_decision(tmp_path, "HR-001", _mutate)
    with pytest.raises(RulesError, match="config.file"):
        load_rules(tmp_path)


# --- 2. every current_default equals the live value ---------------------------


def test_every_current_default_equals_the_live_config_value(rules: Rules) -> None:
    """THE point of the register. If someone tunes a threshold in YAML and does not
    update the register, this fails and the build stops."""
    for decision in sorted(rules.decision_register.decisions, key=lambda d: d.id):
        actual = live_value(rules, decision.config.path)
        assert actual == decision.current_default, (
            f"{decision.id} ({decision.config}) says the default is "
            f"{decision.current_default!r}, but the live value is {actual!r}. "
            f"Update decision_register.yaml — SFU HR was told the other number."
        )


def test_the_shipped_register_is_in_step_with_the_shipped_rules(rules: Rules) -> None:
    assert check_register(rules) == ()
    assert_register_in_step(rules)


def test_tuning_the_score_floor_without_the_register_breaks_the_build(
    tmp_path: Path,
) -> None:
    """The scenario this whole task exists to prevent: someone quietly raises the
    approval bar. The rules still *load* (a scratch policy may be explored), but the
    register check — which `get_rules()` and `make gates` run — refuses it."""
    _write_valid_rules(tmp_path)
    _patch(
        tmp_path,
        "gates.yaml",
        lambda d: _gate(d, "SFU-APPROVE-SCORE-FLOOR").__setitem__("min_score", 70.0),
    )
    tuned = load_rules(tmp_path)
    assert tuned.gates.by_id["SFU-APPROVE-SCORE-FLOOR"].min_score == 70.0

    problems = check_register(tuned)
    assert any("HR-001" in problem for problem in problems), problems
    with pytest.raises(RulesError, match="out of step"):
        assert_register_in_step(tuned)


def test_updating_the_register_alongside_the_config_is_accepted(
    tmp_path: Path,
) -> None:
    """...and the fix is a data edit, not a code change: update both YAML files and
    the same tuned policy is accepted."""
    _write_valid_rules(tmp_path)
    _patch(
        tmp_path,
        "gates.yaml",
        lambda d: _gate(d, "SFU-APPROVE-SCORE-FLOOR").__setitem__("min_score", 70.0),
    )
    _patch_decision(
        tmp_path,
        "HR-001",
        lambda d: d.update(
            current_default=70.0,
            status="ratified",
            decided_by="SFU HR (Total Compensation)",
            decided_on=dt.date(2026, 7, 10),
            decision_note="Raised to 70 against the archive baseline.",
        ),
    )
    tuned = load_rules(tmp_path)
    assert check_register(tuned) == ()
    assert tuned.decision_register.by_id["HR-001"].status == "ratified"


def test_demoting_a_coded_term_without_the_register_breaks_the_build(
    tmp_path: Path,
) -> None:
    """A lexicon tier is pinned by its key set: adding SFU's "supporting" (HR-029
    records why it is omitted) cannot happen silently."""
    _write_valid_rules(tmp_path)
    _patch(
        tmp_path,
        "coded_terms.yaml",
        lambda d: d["medium"].__setitem__("supporting", '"clarify"'),
    )
    problems = check_register(load_rules(tmp_path))
    assert any("HR-029" in problem for problem in problems), problems


def test_promoting_a_rule_to_blocking_without_the_register_breaks_the_build(
    tmp_path: Path,
) -> None:
    """The most important drift case: making a rule block approval. `blocking_rule_ids`
    is a derived view of the WHOLE policy, so it does not matter which gate the rule is
    added to — HR-004 catches it."""
    _write_valid_rules(tmp_path)

    def _promote(data: dict[str, Any]) -> None:
        _gate(data, "SFU-APPROVE-KSA-ORDER")["rule_ids"].append("SFU-LANG-CODED")

    _patch(tmp_path, "gates.yaml", _promote)
    problems = check_register(load_rules(tmp_path))
    assert any("HR-004" in problem for problem in problems), problems


def test_making_a_gate_un_waivable_without_the_register_breaks_the_build(
    tmp_path: Path,
) -> None:
    """Taking away a reviewer's discretion is a policy change (CLAUDE.md §1)."""
    _write_valid_rules(tmp_path)
    _patch(
        tmp_path,
        "gates.yaml",
        lambda d: _gate(d, "SFU-APPROVE-SCORE-FLOOR").__setitem__("overridable", False),
    )
    problems = check_register(load_rules(tmp_path))
    assert any("HR-005" in problem for problem in problems), problems


# --- 3. coverage: nothing on the decision surface is unaccounted for -----------


def test_every_decision_surface_parameter_is_registered_or_explicitly_trivial(
    rules: Rules,
) -> None:
    """No SILENT defaults. Every parameter that can change what the system decides
    about a JD is either a decision SFU HR must make, or is explicitly declared not
    to be one — with a reason. Mirrors 2.3's
    ``test_every_catalogued_rule_is_gated_or_explicitly_not``."""
    register = rules.decision_register
    surface = decision_surface(rules)
    accounted = register.registered_paths | register.exempt_paths
    assert surface <= accounted, sorted(surface - accounted)


def test_no_stale_trivial_exemptions(rules: Rules) -> None:
    """A `trivial:` entry for something no longer on the surface is dead weight that
    would silently absorb a future real decision at the same path."""
    register = rules.decision_register
    assert register.exempt_paths <= decision_surface(rules), sorted(
        register.exempt_paths - decision_surface(rules)
    )


def test_a_new_gate_with_no_register_entry_fails_the_coverage_check(
    tmp_path: Path,
) -> None:
    """Add a gate, forget to decide whether HR must ratify it → the build fails."""
    _write_valid_rules(tmp_path)

    def _add_gate(data: dict[str, Any]) -> None:
        data["gates"].append(
            {
                "gate_id": "SFU-APPROVE-INVENTED",
                "type": "score_floor",
                "title": "An invented floor nobody registered",
                "source_part": "Part 11.6",
                "overridable": True,
                "min_score": 88.0,
                "reason": "The score {score:.1f} is below {min_score:.1f}.",
            }
        )

    _patch(tmp_path, "gates.yaml", _add_gate)
    problems = check_register(load_rules(tmp_path))
    assert any("SFU-APPROVE-INVENTED.min_score" in p for p in problems), problems
    assert any("SFU-APPROVE-INVENTED.overridable" in p for p in problems), problems


def test_a_new_catalogued_rule_with_no_registered_severity_fails_coverage(
    tmp_path: Path,
) -> None:
    """A rule's severity drives both the score and the severity floor — a new rule
    must have its severity accounted for."""
    _write_valid_rules(tmp_path)

    def _add_rule(data: dict[str, Any]) -> None:
        data["rules"].append(
            {
                "rule_id": "SFU-INVENTED-RULE",
                "category": "structure",
                "section": "duties",
                # Required with no default (CUPE Phase B) — a rule cannot be filed
                # against a template by omission, so even a throwaway fixture must
                # state one. This test is about SEVERITY registration; the value here
                # is incidental.
                "applies_to": ["jdfn"],
                "source_part": "Part 2C",
                "default_severity": "high",
                "title": "An invented rule nobody registered",
                "owner": "deterministic",
                "messages": {"default": "Something is wrong."},
                "recommendations": {"default": "Fix it."},
            }
        )

    _patch(tmp_path, "rule_catalog.yaml", _add_rule)
    problems = check_register(load_rules(tmp_path))
    assert any("SFU-INVENTED-RULE.default_severity" in p for p in problems), problems


def test_a_path_that_is_both_registered_and_trivial_fails_to_load(
    tmp_path: Path,
) -> None:
    """A parameter is a decision or it is not — declaring it both ways would let the
    exemption quietly neutralise the entry."""
    _write_valid_rules(tmp_path)

    def _add_exemption(data: dict[str, Any]) -> None:
        data["trivial"].append(
            {
                "config": {
                    "file": "thresholds.yaml",
                    "path": "thresholds.duties_max",
                },
                "reason": "This path is registered as HR-022, so this is a stale copy.",
            }
        )

    _patch(tmp_path, REGISTER_FILE, _add_exemption)
    with pytest.raises(RulesError, match="both registered and declared trivial"):
        load_rules(tmp_path)


def test_a_trivial_exemption_off_the_surface_is_reported(tmp_path: Path) -> None:
    """...and an exemption for a real-but-not-decision-surface path is dead weight."""
    _write_valid_rules(tmp_path)

    def _add_exemption(data: dict[str, Any]) -> None:
        data["trivial"].append(
            {
                # resolvable (it is a real key) but pure copy, so not on the surface
                "config": {
                    "file": "gates.yaml",
                    "path": "gates.SFU-APPROVE-SCORE-FLOOR.title",
                },
                "reason": "Not on the decision surface at all — a stale exemption.",
            }
        )

    _patch(tmp_path, REGISTER_FILE, _add_exemption)
    problems = check_register(load_rules(tmp_path))
    assert any("SFU-APPROVE-SCORE-FLOOR.title" in p for p in problems), problems


# --- the surface itself cannot be quietly shrunk ------------------------------


def test_the_decision_surface_walks_every_rule_file(rules: Rules) -> None:
    """EVERY rule file is on the surface. An earlier version walked only six,
    leaving patterns.yaml, qualifications.yaml, action_verbs.yaml and markers.yaml
    invisible to the register — including three matchers that feed BLOCKING gates."""
    surface = decision_surface(rules)
    files_touched = {path.split(".")[0] for path in surface}
    assert files_touched == {
        "gates",
        "thresholds",
        "scoring",
        "coded_terms",
        "titles",
        "boilerplate",
        "hay_signals",
        "comparison",
        "rule_catalog",
        "patterns",
        "qualifications",
        "action_verbs",
        "markers",
        "textnorm",
        # `segmentation.yaml` / `embeddings.yaml` / `dedup.yaml` are ORDINARY rule
        # files — loaded, validated, registered, drift-checked. They are merely not
        # part of `rules_version` (`_UNHASHED_FILES`), exactly as
        # `decision_register.yaml` is not. No second config subsystem.
        "segmentation",
        "embeddings",
        "dedup",
        # `wjq.yaml` (Phase 3.4) — the CUPE/WJQ template map. Unlike the three above it
        # IS hashed (it decides which text becomes a WJQ JD's summary/duties/quals).
        "wjq",
        # `harmonization.yaml` (Phase 4.1) — the deterministic merge engine's knobs.
        # Unhashed like segmentation/embeddings/dedup: it decides HOW JDs are merged
        # into a draft, never how a JD is scored/approved.
        "harmonization",
        # `rewrite.yaml` (Phase 4.2a) — the LLM rewrite pass's knobs. Unhashed like
        # harmonization: it decides how a draft is WORDED (and how fabrication is
        # scrubbed), never how a JD is scored/approved.
        "rewrite",
        # `quality.yaml` (Phase 4.2b) — the LLM nuanced quality-audit pass's knobs.
        # Unhashed like rewrite: it decides how a JD is AUDITED (advisory), never how a
        # JD is scored/approved.
        "quality",
        # `functional_families.yaml` (Phase A2) — which roles are gathered into a named
        # FUNCTION ("the IT roles"). Unhashed like the rest: it decides what a BROWSE
        # surface shows, never how a JD is scored/approved. Its knobs reach the surface
        # through a per-family enumerator, the way each gate reaches it by gate id — so
        # a family added later is on the surface the moment it is declared.
        "functional_families",
    }
    # ...and that is every rule file there is, bar the register itself.
    described = {name.removesuffix(".yaml") for name in RULE_FILES}
    assert files_touched == described - {REGISTER_FILE.removesuffix(".yaml")}


# --- segmentation.yaml: on the register, deliberately NOT in rules_version ---------


def test_the_unhashed_files_are_the_ones_that_cannot_change_a_jds_score() -> None:
    """The rulebook already had this category before Phase 2.5 — it just had one member.

    ``_HASHED_FIELDS`` is derived by EXCLUDING files, and the exclusion encodes exactly
    one idea: *"this file is on the register's surface, but it does not change what the
    rules decide about a JD."* ``decision_register.yaml`` describes the rules;
    ``segmentation.yaml`` decides which FILES a baseline number is computed over;
    ``embeddings.yaml`` (Phase 3.2b) decides what text a JD becomes for an embedding
    model; ``dedup.yaml`` (Phase 3.3) decides which DOCUMENTS are similar to each
    other; ``harmonization.yaml`` (Phase 4.1) decides HOW a cluster is merged into a
    draft; ``rewrite.yaml`` (Phase 4.2a) decides how a draft is WORDED; ``quality.yaml``
    (Phase 4.2b) decides how a JD is AUDITED (advisory); ``functional_families.yaml``
    (Phase A2) decides which roles are gathered into a named FUNCTION for browsing. None
    of them can move a score, a grade or a gate.
    """
    assert loader._UNHASHED_FILES == {
        REGISTER_FILE,
        "segmentation.yaml",
        "embeddings.yaml",
        "dedup.yaml",
        "harmonization.yaml",
        "rewrite.yaml",
        "quality.yaml",
        "functional_families.yaml",
    }
    hashed = set(loader._HASHED_FIELDS)
    assert "segmentation" not in hashed
    assert "decision_register" not in hashed
    # ...and everything else IS hashed: an exclusion list cannot quietly grow.
    assert hashed == {
        field
        for name, field, _ in loader._FILE_MODELS
        if name not in loader._UNHASHED_FILES
    }


def test_a_config_path_resolves_into_the_segmentation_file(rules: Rules) -> None:
    """No new path language was needed: ``resolve_config_path`` walks ``Rules``, and
    ``segmentation`` is a ``Rules`` field like any other."""
    assert resolve_config_path(rules, "segmentation.era_old_max_year") == 2009
    assert live_value(rules, "segmentation.era_template_token") == "JDFN"
    assert live_value(rules, "segmentation.keep_files_without_position_id") is True
    # a regex compares as its pattern source, exactly as `patterns.yaml` does
    assert live_value(rules, "segmentation.position_id_pattern") == (
        r"(?<![0-9])(0[0-9]{7})(?![0-9])"
    )


def test_editing_the_segmentation_file_leaves_rules_version_untouched(
    tmp_path: Path, rules: Rules
) -> None:
    """**THE property this whole arrangement exists for.**

    ``Rules.version`` is ``jd_rules_sfu_v4+<digest of the rule content>`` and it means
    exactly one thing: *the rules that produced this report* (PR #16). Segmentation
    decides which FILES a baseline number is computed over — it cannot move any JD's
    score, grade or gate decision. If it were hashed, re-banding an era would invalidate
    the stamp on every report ever produced while no rule had moved at all, and
    ``rules_version`` would stop meaning what it says.

    Proved by MUTATING THE SHIPPED YAML and reloading — never by reading the list.
    """
    _write_valid_rules(tmp_path)
    _patch(tmp_path, "segmentation.yaml", lambda d: d.update(era_old_max_year=2005))
    retuned = load_rules(tmp_path)

    # the rulebook's identity does not move...
    assert retuned.version == rules.version
    assert retuned.content_hash == rules.content_hash
    # ...but the segmentation's own identity does, so an artifact can still say which
    # population it describes.
    assert retuned.segmentation.era_old_max_year == 2005
    assert retuned.segmentation.stamp != rules.segmentation.stamp


def test_editing_a_real_rule_file_does_move_rules_version(
    tmp_path: Path, rules: Rules
) -> None:
    """The other half — otherwise the test above would pass on a hash that tracks
    nothing."""
    _write_valid_rules(tmp_path)
    _patch(tmp_path, "thresholds.yaml", lambda d: d.__setitem__("duties_max", 9))
    assert load_rules(tmp_path).version != rules.version


def test_retuning_the_segmentation_without_the_register_breaks_the_build(
    tmp_path: Path,
) -> None:
    """It is unhashed, but it is still REGISTERED — so it cannot move silently. Re-band
    the eras (the call that decides which population the approval bar is ratified
    against) and the build fails until HR is told."""
    _write_valid_rules(tmp_path)
    _patch(
        tmp_path, "segmentation.yaml", lambda d: d.update(era_transition_max_year=2015)
    )
    problems = check_register(load_rules(tmp_path))
    assert any("HR-111" in problem for problem in problems), problems


def test_dropping_the_jdfn_era_token_without_the_register_breaks_the_build(
    tmp_path: Path,
) -> None:
    """HR-109: the token overrides the date band in BOTH directions, which is what makes
    50 pre-2019 files `new`. Retiring it is a one-word edit with no other symptom."""
    _write_valid_rules(tmp_path)
    _patch(
        tmp_path,
        "segmentation.yaml",
        lambda d: d.__setitem__("era_template_token", "X"),
    )
    problems = check_register(load_rules(tmp_path))
    assert any("HR-109" in problem for problem in problems), problems


def test_changing_how_a_bundled_position_is_grouped_breaks_the_build(
    tmp_path: Path,
) -> None:
    """HR-116: the census's own method, with the census's own admitted over/under-count.
    The alternative is implemented — so this is a default HR can really change, and
    changing it must tell them."""
    _write_valid_rules(tmp_path)
    _patch(
        tmp_path,
        "segmentation.yaml",
        lambda d: d.__setitem__("position_id_grouping", "all"),
    )
    problems = check_register(load_rules(tmp_path))
    assert any("HR-116" in problem for problem in problems), problems


def test_every_field_of_the_segmentation_file_is_on_the_surface(rules: Rules) -> None:
    """The flat-file guarantee (the ``hay_signals`` lesson): a knob added to
    ``segmentation.yaml`` tomorrow lands on the decision surface the moment it is
    declared, with no enumerator change — so ``check_register`` breaks the build until
    someone says whether HR must ratify it. ``Segmentation`` is ``extra="forbid"``, so
    the other half holds too: a YAML key with no field is rejected outright."""
    surface = decision_surface(rules)
    for field in type(rules.segmentation).model_fields:
        if field != "version":
            assert f"segmentation.{field}" in surface, field


def test_the_segmentation_defaults_are_registered_as_nobodys_standard(
    rules: Rules,
) -> None:
    """Provenance honesty (the HR-029 / HR-059 lesson). SFU publishes no era model, no
    template-era boundary and no dedup policy. Not one of these may claim a rulebook
    part, and not one of them is ratified."""
    entries = [
        d
        for d in rules.decision_register.decisions
        if d.config.file == "segmentation.yaml"
    ]
    assert len(entries) >= 10, "segmentation.yaml is barely registered"
    for decision in entries:
        assert decision.provenance == "our_invention", decision.id
        assert decision.source_part is None, decision.id
        assert decision.status == "open", decision.id


#: The ONE pre-existing ``jd_core -> jd_bank`` import, recorded so that a second one
#: cannot appear unnoticed. ``parser/store.py`` is a persistence adapter — it writes a
#: parsed JD into ``jd_bank``'s ORM rows. It is a real layering smell, it predates 2.5,
#: and it is a leaf that nothing in the rulebook imports — so it cannot form the cycle
#: below. Not fixed here (it is not this task's diff); pinned so it cannot grow.
_KNOWN_CORE_TO_BANK_IMPORTS: Final[frozenset[str]] = frozenset()


def test_the_rulebook_never_imports_jd_bank() -> None:
    """**The layering arrow, defended by a test rather than by a comment.**

    ``jd_bank`` (ingestion, the archive baseline) depends on ``jd_core`` (the rulebook
    and the validator). An earlier draft of this work put the segmentation policy in
    ``jd_bank`` and had ``jd_core.rules.loader`` import it *back* — a real import cycle
    that only failed **by luck of alphabetical test-collection order**, and that left
    ``get_rules()`` dead in a way an API smoke test would not have caught.

    A constraint enforced by an empty ``__init__.py`` and a comment is not enforced.
    This reads the source. ``src/jd_core/rules/`` is the load-bearing case: everything
    imports it (validators, gates, the API, the worker), so an edge OUT of it into a
    higher layer is precisely what becomes a cycle.
    """
    rulebook = Path(__file__).resolve().parents[2] / "src" / "jd_core" / "rules"
    offenders = [
        module.name
        for module in sorted(rulebook.rglob("*.py"))
        if "src.jd_bank" in module.read_text(encoding="utf-8")
    ]
    assert not offenders, (
        f"the rulebook must not import jd_bank — that is the cycle. "
        f"Offending module(s): {offenders}"
    )


def test_no_new_core_to_bank_import_appears() -> None:
    """The ratchet on the rest of ``jd_core``. One such import already exists
    (:data:`_KNOWN_CORE_TO_BANK_IMPORTS`). This fails if a second is added — and equally
    if the recorded one is removed — so the list cannot rot in either direction."""
    core = Path(__file__).resolve().parents[2] / "src" / "jd_core"
    found = {
        module.relative_to(core).as_posix()
        for module in core.rglob("*.py")
        if any(
            # `lstrip` on purpose: a lazy import *inside a function* is exactly the
            # escape hatch someone reaches for when this ratchet blocks them, and a
            # raw `startswith` would wave it through.
            line.lstrip().startswith(("from src.jd_bank", "import src.jd_bank"))
            for line in module.read_text(encoding="utf-8").splitlines()
        )
    }
    assert found == _KNOWN_CORE_TO_BANK_IMPORTS, sorted(
        found.symmetric_difference(_KNOWN_CORE_TO_BANK_IMPORTS)
    )


@pytest.mark.parametrize(
    "file_field",
    [
        "thresholds",
        "patterns",
        "qualifications",
        "action_verbs",
        "markers",
        "boilerplate",
        "hay_signals",
        "comparison",
        "embeddings",
    ],
)
def test_every_field_of_a_flat_rule_file_is_on_the_surface(
    rules: Rules, file_field: str
) -> None:
    """These files are flat tables of matchers, limits and weights — every key
    changes what the validators fire on or what the estimators score, so every key
    is a decision-surface parameter.

    A field holding a NESTED BLOCK contributes its **leaves** rather than itself
    (`thresholds.wjq.duties_max`, not `thresholds.wjq`) — the `dedup.authoring_guard`
    shape, and the same rule `_flat_file_paths` applies. A register entry must name the
    parameter that is actually decided, and `normalize_config_value` refuses a whole
    model outright, so the block's own path is one nothing could ever pin.

    ⚠ **The nested case is asserted, not skipped.** The obvious way to make this test
    pass when `thresholds` grew its per-template block (Phase C) was to drop
    `thresholds` from the list above, the way `dedup` is absent — which would have
    retired the guarantee for the whole file to accommodate one field. Requiring at
    least one leaf keeps every other key of `thresholds` pinned, and still fails if a
    nested block is added that contributes nothing.
    """
    surface = decision_surface(rules)
    rule_file = getattr(rules, file_field)
    for field in type(rule_file).model_fields:
        if field == "version":
            continue
        path = f"{file_field}.{field}"
        if isinstance(getattr(rule_file, field), BaseModel):
            leaves = {p for p in surface if p.startswith(f"{path}.")}
            assert leaves, f"nested block {path} puts no leaf on the decision surface"
        else:
            assert path in surface


#: Rule-file fields that are deliberately NOT decision-surface parameters *at their
#: own path*, and why. Two honest kinds, and no third (mirroring `TrivialExemption`):
#:
#:   "container" — the field holds the objects whose *members* are enumerated on
#:                 the surface individually (each gate, each band, each title).
#:                 Changing one still moves a surface path.
#:   "copy"      — presentation. Nothing about what the system DECIDES.
#:
#: This is the guard on the enumerator itself, and it is why the file exists: a
#: field added to ANY rule file must appear on the surface or be named here, with a
#: reason, in the SAME change. That is the hole through which four rule files once
#: went unregistered — and, before 2.4b, through which a whole new rule file could.
_OFF_SURFACE: Final[dict[str, dict[str, str]]] = {
    "titles": {
        "restricted": (
            "container: each title's severity + reserved group is on the surface"
        ),
        "family_labels": "copy: the human label a classifier renders",
        "function_labels": "copy: the Application Table's gloss",
    },
    "scoring": {
        "grade_bands": "container: each band's min_score is on the surface",
        "severity_penalty": "container: each severity's penalty is on the surface",
    },
    "rule_catalog": {
        "rules": "container: each rule's default_severity is on the surface",
        "section_order": "copy: the order sections are presented in the checklist",
        "section_labels": "copy: the human label of each section",
        "category_fallback_section": (
            "copy: where an UNCATALOGUED (LLM) finding is filed for display. It "
            "routes a finding to a section; it does not decide that the finding "
            "exists, its severity, or whether it blocks. Pre-existing; not "
            "introduced by 2.4b."
        ),
    },
    "gates": {"gates": "container: each gate is enumerated on the surface"},
    "decision_register": {
        "decisions": "the register describes the OTHER files; it is not itself policy",
        "trivial": "the register's own exemption list",
    },
}


@pytest.mark.parametrize("file_field", sorted(_OFF_SURFACE))
def test_no_rule_file_field_escapes_the_surface_unaccounted_for(
    rules: Rules, file_field: str
) -> None:
    """**The enumerator's own coverage check** — the hole this task was told to close.

    ``check_register`` only checks the paths ``decision_surface`` produces. So a new
    YAML file, or a new field in an existing one, that the enumerator never walks is
    invisible to the register AND THE BUILD STAYS GREEN with an unregistered policy
    default inside it. (Adding ``hay_signals.yaml`` in 2.4b would have done exactly
    that, silently, for sixteen invented Hay weights.)

    So: every top-level field of every rule file must be either ON the surface or
    named in ``_OFF_SURFACE`` with a reason. There is no third option, and the
    enumerator cannot be shrunk to dodge it — the flat files are enumerated from
    ``model_fields``, and this test fails the moment a field appears that nobody
    classified.

    **Which target enforces this: `make gates`, not `make register-check`.** They are
    different checks and it matters:

    * ``make register-check`` only diffs the committed Markdown against
      ``decision_register.yaml``. A field hidden from the enumerator passes it.
    * ``make gates`` runs this suite, which runs THIS test (and ``check_register``,
      via ``get_rules``). That is what catches a hidden field.

    Run both; do not read a green ``register-check`` as coverage.
    """
    surface = decision_surface(rules)
    rule_file = getattr(rules, file_field)
    for field in type(rule_file).model_fields:
        if field == "version":
            continue
        on_surface = any(
            path == f"{file_field}.{field}" or path.startswith(f"{file_field}.{field}.")
            for path in surface
        )
        excused = _OFF_SURFACE[file_field].get(field)
        assert on_surface or excused, (
            f"{file_field}.{field} is neither on the decision surface nor listed in "
            f"_OFF_SURFACE. Decide which it is — do not leave it invisible to the "
            f"HR decision register."
        )


def test_the_off_surface_list_has_no_stale_entries(rules: Rules) -> None:
    """The mirror image: an exemption for a field that no longer exists is dead
    weight that would silently absorb a real future decision at the same name."""
    for file_field, excused in _OFF_SURFACE.items():
        fields = set(type(getattr(rules, file_field)).model_fields)
        assert set(excused) <= fields, sorted(set(excused) - fields)


def test_the_flat_surface_files_are_exactly_the_ones_with_no_containers(
    rules: Rules,
) -> None:
    """A rule file is either flat (every field on the surface, automatically) or it
    has containers/copy and must be hand-enumerated. `hay_signals.yaml` was shaped
    flat ON PURPOSE so it lands in the first camp: a weight added to it tomorrow is
    on the surface with no enumerator change at all."""
    described = {name.removesuffix(".yaml") for name in RULE_FILES}
    hand_enumerated = set(_OFF_SURFACE) - {"decision_register"}
    flat = described - set(_OFF_SURFACE)
    assert "hay_signals" in flat
    # ...and `comparison.yaml` (2.4c) was shaped the same way, for the same reason:
    # ~22 similarity/clustering/drift decision parameters, every one of them visible
    # to `check_register` the moment it is declared, with no enumerator change.
    assert "comparison" in flat
    # ...and `boilerplate.yaml` (2.5-prep). A fourth mandated block added to it is a
    # data edit that lands on the surface — and in `Boilerplate.blocks` — with no code
    # change at all.
    assert "boilerplate" in flat
    # ...and `embeddings.yaml` (3.2b), for the same reason: a knob added to it lands
    # on the surface the moment it is declared, with no enumerator change.
    assert "embeddings" in flat
    assert flat.isdisjoint(hand_enumerated)


def test_a_weight_cannot_be_smuggled_into_a_flat_rule_file(tmp_path: Path) -> None:
    """The two halves of the flat-file guarantee, and why they close the loop:

    * a key in the YAML that the model does not declare is rejected outright
      (``extra="forbid"``) — proved here;
    * a key the model DOES declare is on the decision surface automatically —
      proved by ``test_every_field_of_a_flat_rule_file_is_on_the_surface``.

    So there is no way to add a tunable number to ``hay_signals.yaml`` that
    ``check_register`` cannot see. That is exactly the property the hand-enumerated
    files (titles, gates, scoring, rule_catalog) do NOT have for free, which is why
    ``_OFF_SURFACE`` above exists to guard them.
    """
    _write_valid_rules(tmp_path)
    _patch(tmp_path, "hay_signals.yaml", lambda d: d.__setitem__("fudge_factor", 1.5))
    with pytest.raises(RulesError):
        load_rules(tmp_path)


# --- the 2.4b parameters: proof each one actually breaks the build ------------


def test_shuffling_the_title_match_order_breaks_the_build(tmp_path: Path) -> None:
    """Order is a decision. Swapping `manager` and `director` reclassifies every
    Associate Director at SFU — and it is a two-line YAML edit that touches no
    threshold, no gate and no keyword. HR-060 pins the sequence itself."""
    _write_valid_rules(tmp_path)

    def _swap(data: dict[str, Any]) -> None:
        order = list(data["family_match_order"])
        i, j = order.index("manager"), order.index("director")
        order[i], order[j] = order[j], order[i]
        data["family_match_order"] = order

    _patch(tmp_path, "titles.yaml", _swap)
    problems = check_register(load_rules(tmp_path))
    assert any("HR-060" in problem for problem in problems), problems


def test_teaching_the_title_classifier_a_new_keyword_breaks_the_build(
    tmp_path: Path,
) -> None:
    _write_valid_rules(tmp_path)
    _patch(
        tmp_path,
        "titles.yaml",
        lambda d: d["family_keywords"]["lead"].append("principal"),
    )
    problems = check_register(load_rules(tmp_path))
    assert any("HR-061" in problem for problem in problems), problems


def test_retuning_a_hay_weight_breaks_the_build(tmp_path: Path) -> None:
    """The landmine this file exists for: hris hardcoded ``score += 3`` for a graduate
    degree. Now it is a number in YAML — and moving it tells HR."""
    _write_valid_rules(tmp_path)
    _patch(
        tmp_path,
        "hay_signals.yaml",
        lambda d: d["know_how_points"].__setitem__("education_graduate", 9.0),
    )
    problems = check_register(load_rules(tmp_path))
    assert any("HR-073" in problem for problem in problems), problems


def test_moving_a_hay_level_cutoff_breaks_the_build(tmp_path: Path) -> None:
    _write_valid_rules(tmp_path)
    _patch(
        tmp_path,
        "hay_signals.yaml",
        lambda d: d["accountability_levels"].__setitem__("high", 99.0),
    )
    problems = check_register(load_rules(tmp_path))
    assert any("HR-081" in problem for problem in problems), problems


def test_editing_a_hay_lexicon_breaks_the_build(tmp_path: Path) -> None:
    _write_valid_rules(tmp_path)
    _patch(tmp_path, "hay_signals.yaml", lambda d: d["acc_autonomy"].append("gravitas"))
    problems = check_register(load_rules(tmp_path))
    assert any("HR-070" in problem for problem in problems), problems


def test_the_hay_signal_defaults_are_registered_as_nobodys_standard(
    rules: Rules,
) -> None:
    """Provenance honesty (the HR-029 lesson). EVERY hay_signals parameter is
    `prior_calibration` — SFU publishes no Hay point charts and no scoring model, so
    not one of these words or weights may be presented as an SFU standard."""
    register = rules.decision_register
    hay = [d for d in register.decisions if d.config.file == "hay_signals.yaml"]
    assert hay, "hay_signals.yaml has no register entries at all"
    for decision in hay:
        assert decision.provenance == "prior_calibration", decision.id
        assert decision.source_part is None, decision.id
        assert decision.status == "open", decision.id


def test_the_title_dimensions_are_registered_with_honest_provenance(
    rules: Rules,
) -> None:
    """The seniority ladder and its keywords are NOT SFU's (HR-059/060/061/062); the
    functional Application Table and its words ARE (HR-063/065, Part 3.3). The
    register must say so, entry by entry — that distinction is the whole point of the
    provenance column."""
    by_path = {d.config.path: d for d in rules.decision_register.decisions}

    for path in (
        "titles.families",
        "titles.family_match_order",
        "titles.family_keywords",
        "titles.comma_supervisory_families",
        # the ORDER of the SFU table is still our tie-break, not SFU's
        "titles.function_match_order",
    ):
        assert by_path[path].provenance == "prior_calibration", path
        assert by_path[path].source_part is None, path

    for path in ("titles.functions", "titles.function_keywords"):
        assert by_path[path].provenance == "sfu_rulebook", path
        assert by_path[path].source_part == "Part 3.3", path


# --- the 2.4c parameters: similarity, clustering, drift -----------------------


def test_retuning_a_similarity_weight_breaks_the_build(tmp_path: Path) -> None:
    """hris hardcoded ``_W_VEC = 0.45``. Now it is a number in YAML — and moving it
    tells HR, because every threshold in the file is calibrated against this mix."""
    _write_valid_rules(tmp_path)
    _patch(
        tmp_path,
        "comparison.yaml",
        lambda d: d.update({"weight_vector": 0.8, "weight_skill": 0.1}),
    )
    problems = check_register(load_rules(tmp_path))
    assert any("HR-084" in problem for problem in problems), problems


def test_moving_the_clone_threshold_breaks_the_build(tmp_path: Path) -> None:
    """The number whose verdict goes to Compensation ("clone" = no re-evaluation)."""
    _write_valid_rules(tmp_path)
    _patch(
        tmp_path, "comparison.yaml", lambda d: d.__setitem__("clone_threshold", 0.85)
    )
    problems = check_register(load_rules(tmp_path))
    assert any("HR-093" in problem for problem in problems), problems


def test_moving_the_drift_escalation_thresholds_breaks_the_build(
    tmp_path: Path,
) -> None:
    """The two hris presented as SFU's re-evaluation criteria and the rulebook does not
    contain (HR-100 / HR-101). If SFU ever ratifies them, that is a register edit."""
    _write_valid_rules(tmp_path)
    _patch(
        tmp_path,
        "comparison.yaml",
        lambda d: d.update({"material_years_delta": 3, "material_reports_delta": 10}),
    )
    problems = check_register(load_rules(tmp_path))
    assert any("HR-100" in problem for problem in problems), problems
    assert any("HR-101" in problem for problem in problems), problems


def test_editing_the_education_ladder_breaks_the_build(tmp_path: Path) -> None:
    """The ladder is an ordinal scale shared by drift and similarity: inserting a rung
    re-scales both. One home, one register entry, one tripwire."""
    _write_valid_rules(tmp_path)

    def _insert_rung(data: dict[str, Any]) -> None:
        data["education_ladder"] = [
            "high_school",
            "certificate",
            "associate",
            "bachelors",
            "masters",
            "phd",
        ]
        data["education_text_cues"]["certificate"] = ["certificate"]

    _patch(tmp_path, "comparison.yaml", _insert_rung)
    problems = check_register(load_rules(tmp_path))
    assert any("HR-082" in problem for problem in problems), problems


def test_teaching_the_education_parser_a_new_cue_breaks_the_build(
    tmp_path: Path,
) -> None:
    _write_valid_rules(tmp_path)
    _patch(
        tmp_path,
        "comparison.yaml",
        lambda d: d["education_text_cues"]["masters"].append("llm"),
    )
    problems = check_register(load_rules(tmp_path))
    assert any("HR-083" in problem for problem in problems), problems


def test_dropping_a_title_stopword_breaks_the_build(tmp_path: Path) -> None:
    """A one-word edit that silently re-groups every title in the archive."""
    _write_valid_rules(tmp_path)
    _patch(
        tmp_path,
        "comparison.yaml",
        lambda d: d["title_stopwords"].remove("principal"),
    )
    problems = check_register(load_rules(tmp_path))
    assert any("HR-089" in problem for problem in problems), problems


def test_editing_the_supervisory_reports_regex_breaks_the_build(
    tmp_path: Path,
) -> None:
    """It feeds the > 5-direct-reports escalation, so its false positives are policy."""
    _write_valid_rules(tmp_path)
    _patch(
        tmp_path,
        "comparison.yaml",
        lambda d: d["supervisory_reports_pattern"].__setitem__(
            "pattern", r"\b(\d{1,2})\b"
        ),
    )
    problems = check_register(load_rules(tmp_path))
    assert any("HR-103" in problem for problem in problems), problems


def test_the_derived_cluster_threshold_is_pinned_and_cannot_drift(
    tmp_path: Path,
) -> None:
    """The ``max_listed`` landmine, closed and proved.

    ``cluster_threshold`` is DERIVED — ``max(sim_threshold, cluster_threshold_floor)``
    — so there is no second key holding 0.80 to fall out of step with. But the register
    still pins the *effective* number (HR-096), which means it also serves as the
    tripwire on the derivation itself: raise the noise floor above the cluster floor and
    the effective threshold moves even though ``cluster_threshold_floor`` did not, and
    the build says so. Two register entries move (HR-092, the knob; HR-096, the effect)
    — which is exactly the honest report.
    """
    _write_valid_rules(tmp_path)
    _patch(tmp_path, "comparison.yaml", lambda d: d.__setitem__("sim_threshold", 0.9))
    retuned = load_rules(tmp_path)
    assert retuned.comparison.cluster_threshold == 0.9  # followed the noise floor
    problems = check_register(retuned)
    assert any("HR-092" in problem for problem in problems), problems
    assert any("HR-096" in problem for problem in problems), problems


def test_the_comparison_defaults_are_registered_as_nobodys_standard(
    rules: Rules,
) -> None:
    """Provenance honesty, again (HR-029 / HR-059 / the Hay lesson). **NOT ONE**
    parameter in ``comparison.yaml`` is an SFU standard, and none may be dressed up as
    one: SFU publishes no similarity formula, no clone score, no cluster threshold and
    no drift metric. The two that come closest — the education-change and > 5-direct-
    reports escalations — were cited by hris to "SFU Toolkit p26", and the rulebook this
    repo ships contains no re-evaluation criteria at all.

    So the bar is: nothing here is ``sfu_rulebook``, and nothing here cites a
    ``source_part``.

    ⚠ It is **not** "everything here is ``prior_calibration``". That was true while
    ``comparison.yaml`` held only the 2.4c port, and Phase 3.1 made it false: HR-123
    (``exact_edge_topology``) is ``our_invention`` — hris had no Tier-1 dedup edges at
    all, so there is no hris number to have inherited, and claiming
    ``prior_calibration`` for it would be the *same* provenance lie in the opposite
    direction. Phase 3.4a
    added six more inventions (the ParsedJD -> JobSignals adapter knobs,
    HR-149..HR-154): hris had a skill ontology + idf corpus JD Bank does not, so its
    skill-bag / word-year / education- and experience-source defaults are ours, not
    inherited. Phase 3.4b added six more (the Tier-3 role-equivalence knobs,
    HR-155..HR-160): hris had no Tier-3 role-equivalence pass to inherit. Phase 3.5
    added six more (the clustering knobs, HR-161..HR-166): hris had no report-only
    clustering over a mixed-tier edge graph either. HR-223 (``singleton_role_policy``)
    is the newest: what becomes of a job with no near-duplicate anywhere is not an
    inherited number at all — it is what the pipeline DOES today, written down so it can
    be ruled on. The set below is what stops the 22 genuinely-inherited numbers from
    being quietly relabelled ``our_invention`` (or vice versa) on the way past.
    """
    register = rules.decision_register
    comparison = [d for d in register.decisions if d.config.file == "comparison.yaml"]
    assert len(comparison) >= 21, "comparison.yaml is barely registered"
    for decision in comparison:
        assert decision.provenance != "sfu_rulebook", decision.id
        assert decision.source_part is None, decision.id
        assert decision.status == "open", decision.id

    inherited = [d for d in comparison if d.provenance == "prior_calibration"]
    ours = [d for d in comparison if d.provenance == "our_invention"]
    assert len(inherited) >= 20, "the ported hris calibration was relabelled"
    # Everything in this file that is OURS, not hris's: the Tier-1 edge topology (3.1),
    # the six ParsedJD -> JobSignals adapter knobs (3.4a), the six Tier-3
    # role-equivalence knobs (3.4b) and the six clustering knobs (3.5). If this set
    # grows, a new invention was added to a file whose header must say so, or it is a
    # lie by omission — update the header in lockstep (ADR-007).
    assert {d.id for d in ours} == {
        "HR-123",
        "HR-149",
        "HR-150",
        "HR-151",
        "HR-152",
        "HR-153",
        "HR-154",
        "HR-155",
        "HR-156",
        "HR-157",
        "HR-158",
        "HR-159",
        "HR-160",
        "HR-161",
        "HR-162",
        "HR-163",
        "HR-164",
        "HR-165",
        "HR-166",
        "HR-223",
    }


def test_the_hay_and_comparison_education_cues_cannot_drift_apart(
    tmp_path: Path,
) -> None:
    """The duplicate-VOCABULARY guard (the 2.4b pattern, applied to 2.4c).

    ``hay_signals.yaml`` says which education reads as graduate (``edu_high``); the cues
    it names — ``master``, ``doctora`` — are the rulebook's education vocabulary, which
    now lives in ``comparison.yaml``. Rename one there and the Know-How signal would
    silently stop scoring a PhD: no load error, no failing test, gates green. So the
    subset relation is enforced at LOAD, exactly like the Hay modifiers against the
    rulebook's own KSA scales.
    """
    _write_valid_rules(tmp_path)
    _patch(
        tmp_path,
        "comparison.yaml",
        lambda d: d["education_text_cues"].__setitem__(
            "phd", ["phd", "ph.d", "doctoral", "dphil"]  # was "doctora"
        ),
    )
    with pytest.raises(RulesError, match="education ladder"):
        load_rules(tmp_path)


@pytest.mark.parametrize(
    "path",
    [
        "patterns.incumbent",  # -> SFU-AUTH-SUMMARY-INCUMBENT (blocking)
        "patterns.senior_title",  # -> SFU-GATE-SENIOR-TITLE   (blocking)
        "qualifications.ksa_rank",  # -> SFU-GATE-KSA-ORDER    (blocking)
    ],
)
def test_the_matchers_behind_blocking_gates_are_accounted_for(
    rules: Rules, path: str
) -> None:
    """These three feed BLOCKING gates: changing one changes the approval bar without
    touching gates.yaml. They were entirely invisible to the register before."""
    register = rules.decision_register
    assert path in decision_surface(rules)
    assert path in register.registered_paths | register.exempt_paths


def test_changing_a_blocking_gates_matcher_breaks_the_build(tmp_path: Path) -> None:
    _write_valid_rules(tmp_path)
    _patch(
        tmp_path,
        "patterns.yaml",
        lambda d: d["incumbent"].__setitem__("pattern", r"\bmy\b"),
    )
    problems = check_register(load_rules(tmp_path))
    assert any("HR-048" in problem for problem in problems), problems


def test_editing_the_action_verb_glossary_breaks_the_build(tmp_path: Path) -> None:
    """All 116 verbs are pinned: the glossary cannot be edited without HR being told."""
    _write_valid_rules(tmp_path)
    _patch(tmp_path, "action_verbs.yaml", lambda d: d["approved"].append("supports"))
    problems = check_register(load_rules(tmp_path))
    assert any("HR-055" in problem for problem in problems), problems


# --- the SECOND route to blocking: the severity floor -------------------------


def test_the_severity_floors_blocking_tiers_are_on_the_surface(rules: Rules) -> None:
    """A rule blocks if a gate names it (HR-004) OR if its severity reaches the
    severity floor (HR-003). The second route needs pinning too."""
    surface = decision_surface(rules)
    assert "rule_catalog.rules_by_severity.high" in surface
    # below the floor, tier membership only moves the score — not on the surface
    assert "rule_catalog.rules_by_severity.low" not in surface
    assert rules.decision_register.registered_paths >= {
        "rule_catalog.rules_by_severity.high"
    }


def test_promoting_a_nudge_to_the_severity_floor_breaks_the_build(
    tmp_path: Path,
) -> None:
    """The hole the reviewer found. Promoting the *exempted* SFU-STRUCT-ACTION-VERB
    from `low` to `high` used to leave the register clean — while making a
    non-approved verb block approval through SFU-APPROVE-SEVERITY-FLOOR, with no
    edit to gates.yaml at all."""
    _write_valid_rules(tmp_path)

    def _promote(data: dict[str, Any]) -> None:
        for spec in data["rules"]:
            if spec["rule_id"] == "SFU-STRUCT-ACTION-VERB":
                spec["default_severity"] = "high"
                return
        raise AssertionError("rule not found")  # pragma: no cover

    _patch(tmp_path, "rule_catalog.yaml", _promote)
    promoted = load_rules(tmp_path)
    # it really does now trip the severity floor...
    floor = promoted.gates.by_id["SFU-APPROVE-SEVERITY-FLOOR"]
    assert isinstance(floor, SeverityFloorGate)
    assert "SFU-STRUCT-ACTION-VERB" in promoted.rule_catalog.rules_by_severity["high"]
    # ...and the register now catches it
    problems = check_register(promoted)
    assert any("HR-057" in problem for problem in problems), problems


def test_lowering_the_severity_floor_widens_the_surface(tmp_path: Path) -> None:
    """The blocking tiers adjust themselves: drop the floor to `medium` and the
    `medium` tier becomes a blocking tier, appears on the surface, and the build
    fails until HR registers it."""
    _write_valid_rules(tmp_path)
    _patch(
        tmp_path,
        "gates.yaml",
        lambda d: _gate(d, "SFU-APPROVE-SEVERITY-FLOOR").__setitem__(
            "min_severity", "medium"
        ),
    )
    lowered = load_rules(tmp_path)
    surface = decision_surface(lowered)
    assert "rule_catalog.rules_by_severity.medium" in surface
    assert "rule_catalog.rules_by_severity.high" in surface
    problems = check_register(lowered)
    assert any("rules_by_severity.medium" in p for p in problems), problems


def test_the_decision_surface_enumerates_every_family_completely(
    rules: Rules,
) -> None:
    """The coverage check is only as good as the surface it checks. This asserts the
    surface is derived from the rules and complete — deleting a family from
    ``decision_surface`` to make coverage pass fails here instead."""
    surface = decision_surface(rules)

    # the two derived views of the whole policy
    assert "gates.blocking_rule_ids" in surface
    assert "gates.non_overridable_gate_ids" in surface

    # every gate: its overridability AND the parameter it measures
    for gate in rules.gates.gates:
        assert f"gates.{gate.gate_id}.overridable" in surface
        measured = {
            "blocking_rules": "rule_ids",
            "severity_floor": "min_severity",
            "score_floor": "min_score",
            "grade_floor": "min_grade",
        }[gate.type]
        assert f"gates.{gate.gate_id}.{measured}" in surface

    # every threshold — of every template profile. A per-template block
    # (`thresholds.wjq`, Phase C) is on the surface through its LEAVES, so each of its
    # fields is pinned individually: a form's numbers are as much a decision as the
    # shared ones, and giving a second form a bar nobody registered is exactly the
    # silent-calibration failure `applies_to` and this block exist to end.
    for field in type(rules.thresholds).model_fields:
        if field == "version":
            continue
        block = getattr(rules.thresholds, field)
        if isinstance(block, BaseModel):
            for sub in type(block).model_fields:
                assert f"thresholds.{field}.{sub}" in surface
        else:
            assert f"thresholds.{field}" in surface

    # the scoring calibration: penalties, decay, bands, scale
    for severity in rules.scoring.severity_penalty:
        assert f"scoring.severity_penalty.{severity}" in surface
    for band in rules.scoring.grade_bands:
        assert f"scoring.grade_bands.{band.grade}.min_score" in surface
    assert {
        "scoring.severity_decay",
        "scoring.max_score",
        "scoring.min_score",
        "scoring.fallback_grade",
    } <= surface

    # every coded-term severity tier
    for severity, _terms in rules.coded_terms.tiers:
        assert f"coded_terms.{severity}" in surface

    # every restricted title
    for title in rules.titles.restricted:
        assert f"titles.{title.key}.severity" in surface
        assert f"titles.{title.key}.reserved_for_employee_group" in surface

    # BOTH title dimensions, in full: the vocabulary, the keywords, and — the one a
    # port is most likely to lose — the ORDER the keywords are tried in.
    assert {
        "titles.families",
        "titles.family_match_order",
        "titles.family_keywords",
        "titles.comma_supervisory_families",
        "titles.functions",
        "titles.function_match_order",
        "titles.function_keywords",
    } <= surface

    # every Hay lexicon, weight, count and level cutoff (the flat-file mechanism)
    for field in type(rules.hay_signals).model_fields:
        if field != "version":
            assert f"hay_signals.{field}" in surface

    # every similarity weight, threshold, ladder, stop-word list and drift cutoff
    for field in type(rules.comparison).model_fields:
        if field != "version":
            assert f"comparison.{field}" in surface

    # SFU's mandated text, and the decision not to scan inside it (HR-104..HR-107).
    # The TEXT is on the surface because what counts as the mandated block decides
    # what is exempt; the EXEMPTION is on it because emptying the list re-penalises
    # every compliant JD in the archive.
    for field in type(rules.boilerplate).model_fields:
        if field != "version":
            assert f"boilerplate.{field}" in surface
    assert "boilerplate.coded_term_scan_exempt" in surface

    # every catalogued rule's severity
    for spec in rules.rule_catalog.rules:
        assert f"rule_catalog.{spec.rule_id}.default_severity" in surface


def test_the_surface_grows_when_the_rules_grow(tmp_path: Path) -> None:
    """The surface is enumerated FROM the rules, not from a hand-kept list."""
    _write_valid_rules(tmp_path)
    before = decision_surface(load_rules(tmp_path))

    def _add_gate(data: dict[str, Any]) -> None:
        data["gates"].append(
            {
                "gate_id": "SFU-APPROVE-INVENTED",
                "type": "grade_floor",
                "title": "An invented grade floor",
                "source_part": "Part 11.6",
                "overridable": True,
                "min_grade": "B",
                "reason": 'Grade "{grade}" is below "{min_grade}".',
            }
        )

    _patch(tmp_path, "gates.yaml", _add_gate)
    after = decision_surface(load_rules(tmp_path))
    assert after - before == {
        "gates.SFU-APPROVE-INVENTED.overridable",
        "gates.SFU-APPROVE-INVENTED.min_grade",
    }


# --- 4. the register cannot lie about itself ----------------------------------


def test_the_shipped_register_records_no_decision_as_made(rules: Rules) -> None:
    """The honest current state: SFU HR has ratified nothing yet. Every entry is
    `open`, and no entry claims a decider."""
    for decision in rules.decision_register.decisions:
        assert decision.status == "open", decision.id
        assert decision.decided_by is None
        assert decision.decided_on is None
        assert decision.decision_note is None
    assert rules.decision_register.by_status("ratified") == ()


def test_decision_ids_are_unique_and_well_formed(rules: Rules) -> None:
    ids = [d.id for d in rules.decision_register.decisions]
    assert len(set(ids)) == len(ids)
    assert all(d.startswith("HR-") and d[3:].isdigit() for d in ids)
    assert set(rules.decision_register.by_id) == set(ids)


def test_a_duplicate_decision_id_fails_to_load(tmp_path: Path) -> None:
    _write_valid_rules(tmp_path)

    def _duplicate(data: dict[str, Any]) -> None:
        clone = _decision(data, "HR-002")
        clone["id"] = "HR-001"
        clone["config"] = {
            "file": "thresholds.yaml",
            "path": "thresholds.evidence_context_window",
        }
        clone["current_default"] = 40
        data["decisions"].append(clone)

    _patch(tmp_path, REGISTER_FILE, _duplicate)
    with pytest.raises(RulesError, match="duplicate decision id"):
        load_rules(tmp_path)


def test_a_malformed_decision_id_fails_to_load(tmp_path: Path) -> None:
    _write_valid_rules(tmp_path)
    _patch_decision(tmp_path, "HR-001", lambda d: d.__setitem__("id", "SCORE_FLOOR"))
    with pytest.raises(RulesError, match="id"):
        load_rules(tmp_path)


def test_a_duplicate_config_path_fails_to_load(tmp_path: Path) -> None:
    _write_valid_rules(tmp_path)

    def _duplicate(data: dict[str, Any]) -> None:
        clone = _decision(data, "HR-002")
        clone["id"] = "HR-900"
        clone["config"] = dict(_decision(data, "HR-001")["config"])
        clone["current_default"] = 60.0
        data["decisions"].append(clone)

    _patch(tmp_path, REGISTER_FILE, _duplicate)
    with pytest.raises(RulesError, match="duplicate registered config path"):
        load_rules(tmp_path)


def test_a_ratified_decision_must_record_who_decided_and_when(tmp_path: Path) -> None:
    _write_valid_rules(tmp_path)
    _patch_decision(tmp_path, "HR-001", lambda d: d.__setitem__("status", "ratified"))
    with pytest.raises(RulesError, match="ratified decision must record"):
        load_rules(tmp_path)


def test_an_open_decision_may_not_claim_a_decider(tmp_path: Path) -> None:
    """An open decision carrying a decider is exactly the lie the register exists to
    prevent."""
    _write_valid_rules(tmp_path)
    _patch_decision(
        tmp_path, "HR-001", lambda d: d.__setitem__("decided_by", "somebody, probably")
    )
    with pytest.raises(RulesError, match="open decision must not record"):
        load_rules(tmp_path)


def test_a_deferred_decision_may_record_who_deferred_it(tmp_path: Path) -> None:
    """Deferring is itself a decision — it may (but need not) record who made it."""
    _write_valid_rules(tmp_path)
    _patch_decision(
        tmp_path,
        "HR-016",
        lambda d: d.update(
            status="deferred",
            decided_by="SFU HR",
            decided_on=dt.date(2026, 7, 10),
            decision_note="Revisit after the archive baseline.",
        ),
    )
    loaded = load_rules(tmp_path)
    assert loaded.decision_register.by_id["HR-016"].status == "deferred"
    assert loaded.decision_register.by_status("deferred")[0].id == "HR-016"


def test_rulebook_provenance_must_cite_a_source_part(tmp_path: Path) -> None:
    _write_valid_rules(tmp_path)
    _patch_decision(
        tmp_path,
        "HR-001",
        lambda d: d.__setitem__("provenance", "sfu_rulebook"),
    )
    with pytest.raises(RulesError, match="source_part"):
        load_rules(tmp_path)


def test_an_invented_default_may_not_claim_a_rulebook_source(tmp_path: Path) -> None:
    """Citing a rulebook part for a number SFU never published is the single most
    misleading thing this file could do."""
    _write_valid_rules(tmp_path)
    _patch_decision(
        tmp_path, "HR-001", lambda d: d.__setitem__("source_part", "Part 11.6")
    )
    with pytest.raises(RulesError, match="source_part"):
        load_rules(tmp_path)


def test_a_trivial_exemption_must_state_a_real_reason(tmp_path: Path) -> None:
    _write_valid_rules(tmp_path)
    _patch(
        tmp_path,
        REGISTER_FILE,
        lambda d: d["trivial"][0].__setitem__("reason", "n/a"),
    )
    with pytest.raises(RulesError, match="reason"):
        load_rules(tmp_path)


def test_a_dangling_covered_by_reference_fails_to_load(tmp_path: Path) -> None:
    _write_valid_rules(tmp_path)
    _patch(
        tmp_path,
        REGISTER_FILE,
        lambda d: d["trivial"][2].__setitem__("covered_by", "HR-999"),
    )
    with pytest.raises(RulesError, match="covered_by"):
        load_rules(tmp_path)


def test_every_covered_by_names_a_real_decision(rules: Rules) -> None:
    ids = set(rules.decision_register.by_id)
    for exemption in rules.decision_register.trivial:
        if exemption.covered_by is not None:
            assert exemption.covered_by in ids, exemption.config.path


def test_provenance_and_status_use_the_declared_vocabulary(rules: Rules) -> None:
    provenances = set(get_args(DecisionProvenance))
    statuses = set(get_args(DecisionStatus))
    for decision in rules.decision_register.decisions:
        assert decision.provenance in provenances
        assert decision.status in statuses


def test_the_register_is_frozen(rules: Rules) -> None:
    with pytest.raises(ValidationError):
        rules.decision_register.decisions[0].current_default = 1  # type: ignore[misc]


# --- the config-path language -------------------------------------------------


def test_a_path_resolves_a_scalar_field(rules: Rules) -> None:
    assert resolve_config_path(rules, "thresholds.duties_max") == 5


def test_a_path_resolves_a_gate_by_its_id(rules: Rules) -> None:
    assert resolve_config_path(rules, "gates.SFU-APPROVE-SCORE-FLOOR.min_score") == 60.0


def test_a_path_resolves_a_grade_band_by_its_grade(rules: Rules) -> None:
    assert resolve_config_path(rules, "scoring.grade_bands.C.min_score") == 60.0


def test_a_path_resolves_a_restricted_title_by_its_key(rules: Rules) -> None:
    assert resolve_config_path(rules, "titles.executive_director.severity") == "low"


def test_a_path_resolves_a_catalogued_rule_by_its_id(rules: Rules) -> None:
    path = "rule_catalog.SFU-COMP-DECISION.default_severity"
    assert resolve_config_path(rules, path) == "medium"


def test_a_path_resolves_a_mapping_entry(rules: Rules) -> None:
    assert resolve_config_path(rules, "scoring.severity_penalty.high") == 20.0


def test_a_path_resolves_set_membership(rules: Rules) -> None:
    """How a contested member of a 116-word glossary is pinned without inlining it."""
    assert resolve_config_path(rules, "action_verbs.approved.accountable") is True
    assert resolve_config_path(rules, "action_verbs.approved.zzz") is False


def test_a_path_resolves_a_derived_policy_view(rules: Rules) -> None:
    blocking = resolve_config_path(rules, "gates.blocking_rule_ids")
    assert blocking == rules.gates.blocking_rule_ids
    assert "SFU-COMP-SUMMARY" in blocking


@pytest.mark.parametrize(
    "path",
    [
        "thresholds.nope",
        "gates.SFU-APPROVE-NOPE.min_score",
        "scoring.severity_penalty.catastrophic",
        "scoring.grade_bands.Z.min_score",
        "thresholds.duties_max.nope",  # a scalar has no members
        "scoring._RuleFile",  # private
        "scoring.grade_for",  # a method is not a config value
        "qualifications.banned_phrases.0",  # a plain list is not addressable by key
    ],
)
def test_an_unresolvable_path_raises_a_clear_rules_error(
    rules: Rules, path: str
) -> None:
    with pytest.raises(RulesError, match="does not resolve"):
        resolve_config_path(rules, path)


def test_normalization_is_the_comparison_contract(rules: Rules) -> None:
    # a set -> its sorted members
    assert live_value(rules, "qualifications.knowledge_modifiers") == [
        "excellent",
        "none",
        "working",
    ]
    # a mapping -> the WHOLE mapping, keys AND values
    assert live_value(rules, "qualifications.ksa_rank") == {
        "knowledge": 0,
        "skill": 1,
        "ability": 2,
    }
    # a list -> file order
    assert live_value(rules, "qualifications.banned_phrases") == [
        "may include",
        "assets",
        "preferences",
    ]
    # a regex -> its pattern source
    assert live_value(rules, "patterns.duty_allocation") == r"\((\d{1,3})\s*%\)"
    # None survives
    assert live_value(rules, "titles.registrar.reserved_for_employee_group") is None


def test_a_mapping_pins_its_values_not_just_its_keys(tmp_path: Path) -> None:
    """The KSA order is a mapping whose VALUES are the policy a blocking gate
    enforces. A key-set comparison would let a permutation through."""
    _write_valid_rules(tmp_path)
    _patch(
        tmp_path,
        "qualifications.yaml",
        lambda d: d.__setitem__("ksa_rank", {"knowledge": 2, "skill": 1, "ability": 0}),
    )
    problems = check_register(load_rules(tmp_path))
    assert any("HR-052" in problem for problem in problems), problems


def test_a_path_that_stops_on_a_whole_object_is_rejected(rules: Rules) -> None:
    """A register entry must name the parameter that is decided, not the object that
    contains it — otherwise `current_default` could never be written down."""
    with pytest.raises(RulesError, match="must name the parameter"):
        normalize_config_value(
            resolve_config_path(rules, "gates.SFU-APPROVE-SCORE-FLOOR"),
            "gates.SFU-APPROVE-SCORE-FLOOR",
        )
    with pytest.raises(RulesError, match="list of objects"):
        normalize_config_value(
            resolve_config_path(rules, "scoring.grade_bands"), "scoring.grade_bands"
        )


# --- the human-readable view --------------------------------------------------


def test_the_rendered_register_names_every_decision(rules: Rules) -> None:
    markdown = render_register(rules)
    for decision in rules.decision_register.decisions:
        assert decision.id in markdown
        assert decision.config.path in markdown


def test_the_rendered_register_leads_with_what_nobody_ratified(rules: Rules) -> None:
    """Our-invention entries are what HR most needs to see, so they come first.

    Pinned against the heading *constants* rather than literal prose: the property
    is the ordering, and rewording a heading for readability should not have to
    touch this test. (It did once — the headings were rewritten after an HR reader
    could not decode "prior calibration".)
    """
    markdown = render_register(rules)
    ours = markdown.index(_PROVENANCE_HEADING["our_invention"])
    inherited = markdown.index(_PROVENANCE_HEADING["prior_calibration"])
    rulebook = markdown.index(_PROVENANCE_HEADING["sfu_rulebook"])
    assert ours < inherited < rulebook


def test_the_rendered_register_lists_every_trivial_exemption_with_its_reason(
    rules: Rules,
) -> None:
    markdown = render_register(rules)
    for exemption in rules.decision_register.trivial:
        assert exemption.config.path in markdown
    assert "deliberately not a decision" in markdown


def test_the_render_is_deterministic(rules: Rules) -> None:
    """It is committed and drift-checked in CI, so it must be byte-stable."""
    assert render_register(rules) == render_register(rules)


def test_the_render_refuses_to_print_a_drifted_register(tmp_path: Path) -> None:
    """The Markdown can never show HR a number that is not the one in force."""
    _write_valid_rules(tmp_path)
    _patch(
        tmp_path,
        "gates.yaml",
        lambda d: _gate(d, "SFU-APPROVE-SCORE-FLOOR").__setitem__("min_score", 70.0),
    )
    with pytest.raises(RulesError, match="out of step"):
        render_register(load_rules(tmp_path))


def test_the_render_main_writes_the_markdown_to_stdout(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main([]) == 0
    printed = capsys.readouterr().out
    assert printed.startswith("# SFU HR Decision Register")
    assert printed == render_register(get_rules())


# --- `make register-check`: the drift gate, run INSIDE the container ----------
#
# The `gates` service mounts only ./core, so docs/ is invisible to it — and the
# Windows shell `make` uses has no `diff`/`mkdir -p`/`rm -f`. So the committed
# Markdown is piped IN on stdin and compared here (ADR-006: the work is in the
# container; the host only redirects).


def test_check_markdown_accepts_a_freshly_rendered_document(rules: Rules) -> None:
    assert check_markdown(render_register(rules), rules) == ()


def test_check_markdown_reports_a_stale_document(rules: Rules) -> None:
    stale = render_register(rules).replace("60.0", "70.0")
    diff = check_markdown(stale, rules)
    assert diff
    assert any(line.startswith("-") for line in diff)


def test_main_check_passes_on_a_fresh_document(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO(render_register(get_rules())))
    assert main(["--check"]) == 0
    assert "in step" in capsys.readouterr().out


def test_main_check_fails_on_a_stale_document(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO("# not the register\n"))
    assert main(["--check"]) == 1
    captured = capsys.readouterr()
    assert "STALE" in captured.err
    assert "make register" in captured.err


def test_main_rejects_an_unknown_argument(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["--wat"]) == 2
    assert "usage" in capsys.readouterr().err


# --- readability: the register is read by HR, not only by engineers ------------------
#
# Two complaints from an HR reader, both about the SUMMARY TABLE (the part anyone
# actually reads; the detail blocks below it are for us):
#
#   1. "prior calibration" appeared as a bare label with nothing nearby saying what
#      it means. The phrase is not self-evident, and the sentence that defines it
#      sits in a section heading far below the table.
#   2. A regex was printed as a decision's value -- e.g. HR-117's
#      `JDFN_[A-Z]+_((?:19|20)\d{2})(\d{2})(\d{2})`. That is unreadable to the
#      audience the document names in its title, and it tells them nothing about
#      the decision they are being asked to make.
#
# The raw pattern is still shown in the entry's own detail block, where the
# engineer who needs it looks and where `why_it_matters` explains it.


def test_the_summary_table_explains_where_a_default_came_from(rules: Rules) -> None:
    """Every provenance label the table uses is defined right next to the table."""
    document = render_register(rules)
    legend = document.split("## Open —", 1)[0]
    for label in (
        "we chose it",
        "an earlier version of this tool",
        "SFU's published standard",
    ):
        assert label in legend, f"{label!r} is used in the table but never explained"

    # The reader must not have to guess, and must not be misled into thinking an
    # inherited value carries outside authority. It does not: nothing in the
    # register claims an industry basis, and the values were tuned to agree with
    # our own approval floor. Saying "industry standard" here would make an
    # unratified guess sound externally sanctioned — the exact failure this
    # register exists to prevent.
    assert "**not** an industry standard" in legend
    assert "nobody at SFU has agreed to this yet" in legend


def test_no_raw_regex_reaches_the_summary_table(rules: Rules) -> None:
    """A pattern is summarised in the table and shown in full in its detail block.

    The detail blocks are ``####`` sections inside the same status section, not a
    separate ``## Details`` heading — so "the table" is precisely the lines that
    are table rows, and nothing else.
    """
    document = render_register(rules)
    rows = [line for line in document.splitlines() if line.startswith("| [HR-")]
    assert rows, "no summary-table rows found — the table's shape must have changed"

    for row in rows:
        assert "(?:" not in row, f"a raw regex is shown to HR in the table: {row[:90]}"
        assert "[A-Z]" not in row, f"a raw regex is shown to HR: {row[:90]}"

    # HR-117 is the entry the complaint named: summarised in the table…
    hr117 = next(row for row in rows if row.startswith("| [HR-117]"))
    assert "a text pattern" in hr117
    # …and still recorded in full in its own detail block.
    assert r"JDFN_[A-Z]+_((?:19|20)\d{2})(\d{2})(\d{2})" in document


def test_a_pattern_valued_decision_is_still_fully_recorded(rules: Rules) -> None:
    """Summarising in the table must not lose the value anywhere in the document."""
    document = render_register(rules)
    for decision in rules.decision_register.decisions:
        if isinstance(decision.current_default, str) and (
            decision.config.path.endswith("_pattern")
            or decision.config.file == "patterns.yaml"
        ):
            assert decision.current_default in document, (
                f"{decision.id}'s pattern is summarised in the table but missing "
                "from its detail block"
            )


# --- 5. tiering: HR is asked to rule on the approval bar, not on plumbing -------
#
# The register conflated two incompatible jobs. It is simultaneously (a) the list
# of policy calls SFU HR must sign, and (b) the completeness ledger that stops an
# engineer tuning a threshold silently — and (b) requires registering embedding
# timeouts and MinHash band counts that HR must never be asked about. Handing an HR
# workshop the undifferentiated list is what makes the ask bounce.
#
# `tier` splits the two WITHOUT dropping a single entry: every parameter stays
# registered and every build-breaking check above still covers all of them. What
# changes is who is asked.


def test_every_decision_declares_a_tier(rules: Rules) -> None:
    tiers = get_args(DecisionTier)
    for decision in rules.decision_register.decisions:
        assert decision.tier in tiers, f"{decision.id} has no valid tier"


def test_a_decision_with_no_tier_fails_to_load(tmp_path: Path) -> None:
    """`tier` is REQUIRED and has no default — so a new entry cannot be added
    without someone deciding whether HR is asked about it. A default would silently
    file every future parameter into whichever tier we picked."""
    _write_valid_rules(tmp_path)
    _patch_decision(tmp_path, "HR-001", lambda entry: entry.pop("tier"))
    with pytest.raises(RulesError):
        load_rules(tmp_path)


def test_a_decision_with_an_unknown_tier_fails_to_load(tmp_path: Path) -> None:
    _write_valid_rules(tmp_path)
    _patch_decision(tmp_path, "HR-001", lambda entry: entry.update(tier="whenever"))
    with pytest.raises(RulesError):
        load_rules(tmp_path)


def test_the_approval_bar_is_hr_policy(rules: Rules) -> None:
    """Everything that decides whether a JD PASSES is HR's to rule on — the gates,
    every point and grade band, and SFU's own published wording. If any of these
    drifts out of `hr_policy`, the workshop ask has lost its subject."""
    must_be_policy = {"gates.yaml", "scoring.yaml", "boilerplate.yaml"}
    for decision in rules.decision_register.decisions:
        if (
            decision.config.file in must_be_policy
            and not decision.config.path.endswith(
                ".max_listed"  # a presentation limit, not the bar
            )
        ):
            assert decision.tier == "hr_policy", (
                f"{decision.id} ({decision.config}) decides whether a JD passes but "
                f"is tiered {decision.tier!r}"
            )


def test_the_derived_signal_adapters_are_never_hr_policy(rules: Rules) -> None:
    """ADR-007 disclaims comparison/hay_signals as NOT formal classification, and
    `models/bank.py` makes a Hay grade unrepresentable. Asking HR to ratify a
    similarity weight or a Know-How point value contradicts both — and these two
    files alone are why the undifferentiated ask was unanswerable."""
    for decision in rules.decision_register.decisions:
        if decision.config.file in {"comparison.yaml", "hay_signals.yaml"}:
            assert decision.tier != "hr_policy", (
                f"{decision.id} is a derived signal ADR-007 disclaims, but it is "
                "tiered hr_policy — HR would be asked to ratify a number that does "
                "not classify anything"
            )


def test_the_inference_knobs_are_technical(rules: Rules) -> None:
    """Model names, temperatures, token budgets, retries, embedding dimensions and
    timeouts. A wrong value here is an engineering bug, not a policy error."""
    for decision in rules.decision_register.decisions:
        leaf = decision.config.path.rsplit(".", 1)[-1]
        if leaf in {
            "model",
            "temperature",
            "max_tokens",
            "max_retries",
            "dimensions",
            "reasoning_effort",
            "timeout_seconds",
        }:
            assert decision.tier == "technical", (
                f"{decision.id} ({decision.config}) is an inference knob tiered "
                f"{decision.tier!r} — HR should never be asked about it"
            )


def test_tiering_asks_hr_a_materially_smaller_question(rules: Rules) -> None:
    """The whole point: the HR ask must be a fraction of the register, or nothing
    was gained. Not a target to tune the tiers against — a floor that fails loudly
    if a later batch of entries quietly lands in `hr_policy`."""
    register = rules.decision_register
    policy = register.by_tier("hr_policy")
    assert len(policy) < len(register.decisions) / 2, (
        f"{len(policy)} of {len(register.decisions)} entries are hr_policy — the "
        "ask is no smaller than the undifferentiated register was"
    )


def test_every_entry_survives_the_tiering(rules: Rules) -> None:
    """Nothing becomes unregistered. Tiering changes who is ASKED, never what is
    COVERED — the coverage check above still walks every decision."""
    register = rules.decision_register
    tiered = sum(len(register.by_tier(tier)) for tier in get_args(DecisionTier))
    assert tiered == len(register.decisions)


def test_the_rendered_register_groups_the_open_decisions_by_tier(
    rules: Rules,
) -> None:
    """HR opens the generated Markdown and must see their ~60 calls as a section,
    not as a colour of row in a 197-row table."""
    document = render_register(rules)
    for tier in get_args(DecisionTier):
        assert _TIER_HEADING[tier] in document, f"no section for the {tier} tier"

    policy_at = document.index(_TIER_HEADING["hr_policy"])
    technical_at = document.index(_TIER_HEADING["technical"])
    assert (
        policy_at < technical_at
    ), "the technical tier is rendered above the decisions HR must actually make"


def test_the_rendered_header_states_the_hr_policy_count(rules: Rules) -> None:
    """The count of record. CLAUDE.md forbids restating it anywhere else, so the
    generated header has to carry the tier breakdown or it is not stated at all."""
    document = render_register(rules)
    header = document.split("## What this is")[0]
    policy = len(rules.decision_register.by_tier("hr_policy"))
    assert (
        f"{policy} need an HR ruling" in header
    ), "the header does not state how many decisions HR is actually asked for"

"""``functional_families.yaml`` (Phase A2) — the rulebook side of functional job
families, plus the pure scoring the review queue ranks by.

Mirrors ``test_quality_rules.py`` / ``test_rewrite_rules.py``: registered but UNHASHED
(gathering roles into "the IT roles" decides what a BROWSE surface shows, never what a
JD scores), every knob on the decision surface, and the unhashed property proved BY
MUTATION — flip a value in the shipped YAML and reload, never merely read it back.

The scoring tests exist because two specific defects were measured on the real archive
and both looked like findings rather than bugs:

* ``lan`` matched as a substring hits "plan", "planning" and "Langara" — 1,568 of 2,493
  roles, 63% of the corpus, from one three-letter term;
* a single alternation counting distinct matched *strings* scores ``servers?`` twice for
  a JD that says both "server" and "servers" — one concept, two points.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from src.jd_bank.library.families import (
    postgres_patterns,
    python_patterns,
    score_text,
)
from src.jd_core.rules import (
    FUNCTIONAL_FAMILIES_FILE,
    RULE_FILES,
    FunctionalFamilies,
    Rules,
    check_register,
    decision_surface,
    get_rules,
    live_value,
    load_rules,
)

_PKG_DIR = Path(__file__).resolve().parents[2] / "src" / "jd_core" / "rules"

#: Every knob of the IT family that carries a policy judgement. `label`, `slug` and
#: `recall_note` are pure copy and deliberately absent — copy is not on the surface.
_FAMILY_KNOBS = (
    "classification_families",
    "include",
    "exclude",
    "duty_terms",
    "title_terms",
)


@pytest.fixture(scope="module")
def rules() -> Rules:
    return get_rules()


@pytest.fixture(scope="module")
def families(rules: Rules) -> FunctionalFamilies:
    return rules.functional_families


def _write_valid_rules(directory: Path) -> None:
    for name in RULE_FILES:
        (directory / name).write_text(
            (_PKG_DIR / name).read_text(encoding="utf-8"), encoding="utf-8"
        )


def _patch(directory: Path, name: str, mutate: Any) -> None:
    data = yaml.safe_load((directory / name).read_text(encoding="utf-8"))
    mutate(data)
    (directory / name).write_text(yaml.safe_dump(data), encoding="utf-8")


# --- the rule file ----------------------------------------------------------------


def test_functional_families_ships_and_loads(families: FunctionalFamilies) -> None:
    assert FUNCTIONAL_FAMILIES_FILE in RULE_FILES
    it = families.families["information_technology"]
    assert it.label == "Information Technology"
    assert it.slug == "it"
    assert "ITP" in it.classification_families
    assert it.duty_terms and it.title_terms
    assert it.recall_note.strip()


def test_by_slug_addresses_the_collection_url(families: FunctionalFamilies) -> None:
    assert families.by_slug("it") is families.families["information_technology"]
    assert families.by_slug("no-such-family") is None


def test_every_family_knob_is_on_the_decision_surface(rules: Rules) -> None:
    """A family added tomorrow must break the build until someone decides its knobs."""
    surface = decision_surface(rules)
    assert "functional_families.review_queue_min_score" in surface
    for key in rules.functional_families.families:
        for knob in _FAMILY_KNOBS:
            assert f"functional_families.{key}.{knob}" in surface


def test_pure_copy_is_not_on_the_decision_surface(rules: Rules) -> None:
    """`label` / `slug` / `recall_note` are copy. Registering copy is how a register
    fills with entries HR cannot act on, which is the failure the tiers exist to stop.
    """
    surface = decision_surface(rules)
    for copy_field in ("label", "slug", "recall_note"):
        assert f"functional_families.information_technology.{copy_field}" not in surface


def test_register_is_in_step_with_the_shipped_defaults(rules: Rules) -> None:
    assert check_register(rules) == ()
    it = "functional_families.information_technology"
    assert live_value(rules, "functional_families.review_queue_min_score") == 7
    assert live_value(rules, f"{it}.classification_families") == ["ITP"]
    assert live_value(rules, f"{it}.include") == []
    assert live_value(rules, f"{it}.exclude") == []


def test_retuning_a_term_list_does_not_move_rules_version(tmp_path: Path) -> None:
    """UNHASHED, proved BY MUTATION. A term list decides what a BROWSE page shows; it
    can never change a JD's score, so it must not invalidate the stamp on every report
    ever produced."""
    _write_valid_rules(tmp_path)
    before = load_rules(tmp_path).content_hash
    _patch(
        tmp_path,
        FUNCTIONAL_FAMILIES_FILE,
        lambda d: d["families"]["information_technology"]["duty_terms"].append("cobol"),
    )
    after = load_rules(tmp_path)
    assert after.content_hash == before
    assert (
        "cobol"
        in after.functional_families.families["information_technology"].duty_terms
    )


def test_a_new_family_knob_must_be_registered(tmp_path: Path) -> None:
    """The coverage check, proved by adding a family the register does not name."""
    _write_valid_rules(tmp_path)

    def add_family(data: dict[str, Any]) -> None:
        data["families"]["facilities"] = {
            "label": "Facilities",
            "slug": "facilities",
            "classification_families": [],
            "include": [],
            "exclude": [],
            "duty_terms": ["hvac"],
            "title_terms": ["trades"],
            "recall_note": "Unmeasured — not validated against any seed.",
        }

    _patch(tmp_path, FUNCTIONAL_FAMILIES_FILE, add_family)
    problems = check_register(load_rules(tmp_path))
    assert problems, "an unregistered family knob must break the build"
    assert any("facilities" in problem for problem in problems)


# --- the scoring: ordering only, and the two measured traps -----------------------


def test_lan_does_not_match_plan(families: FunctionalFamilies) -> None:
    """The 63%-of-the-corpus defect. `lan` is a real IT term AND a substring of
    "plan"/"planning"/"Langara" — matched loosely it pulled in 1,568 of 2,493 roles."""
    terms = families.families["information_technology"].duty_terms
    assert score_text("planning the annual plan for langara college", terms) == 0
    assert score_text("maintains the campus lan and wan links", terms) == 2


def test_one_term_scores_once_however_often_it_appears(
    families: FunctionalFamilies,
) -> None:
    """The score counts TERMS. `servers?` is one term whether a JD says "server",
    "servers" or both — under the first implementation both spellings scored 2, so a
    role outranked another for a spelling choice."""
    terms = families.families["information_technology"].duty_terms
    assert score_text("network network network", terms) == 1
    assert score_text("servers and a server and more servers", terms) == 1
    assert score_text("a server on the network", terms) == 2


def test_empty_term_list_matches_nothing(families: FunctionalFamilies) -> None:
    """An absent term list must score 0, never match everything — the direction of this
    failure decides whether an empty family is empty or is the whole archive."""
    assert score_text("any text whatsoever", []) == 0
    assert python_patterns([]) == ()
    assert postgres_patterns([]) == []


def test_score_is_case_insensitive(families: FunctionalFamilies) -> None:
    terms = families.families["information_technology"].duty_terms
    assert score_text("Maintains the LAN", terms) == score_text(
        "maintains the lan", terms
    )


def test_both_dialects_agree_on_the_lan_case(families: FunctionalFamilies) -> None:
    """Python and Postgres spell word boundaries differently (``\b`` vs ``\m``).
    Two dialects of one rule is exactly how a guard drifts, so the shapes are pinned."""
    terms = families.families["information_technology"].duty_terms
    assert len(postgres_patterns(terms)) == len(python_patterns(terms)) == len(terms)
    assert postgres_patterns(["lan"]) == [r"\m(lan)\M"]
    assert python_patterns(["lan"])[0].pattern == r"\b(?:lan)\b"


def test_review_queue_cutoff_is_documented_as_ordering_only(
    families: FunctionalFamilies,
) -> None:
    """The cutoff exists, is registered, and is a queue depth. The resolver must not
    read it — that is asserted against the real database in the integration suite."""
    assert families.review_queue_min_score >= 0

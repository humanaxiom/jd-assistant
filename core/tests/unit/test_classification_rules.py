"""``classification.yaml`` (Track P, P3f) — the rulebook side of pay-grade extraction.

The MIRROR IMAGE of ``test_wjq_rules.py``: ``wjq.yaml`` is hashed because a heading
decides what a WJQ JD's duties ARE, so editing one MUST move ``rules_version``. This
file is the opposite — nothing reads ``SFUJobDescription.classification`` to score,
gate or approve, so retuning a matcher here cannot move a JD's score, and it must NOT
move the stamp.

What it CAN do is make the parser write a grade the document never stated, which is why
every knob is on the decision surface (HR-233 … HR-236) and why the tests below prove
the extractor READS THE YAML — re-loading it retuned and watching the behaviour follow.
A module holding the old ``_CUPE_GRADE_RX`` constant would pass every value assertion
in this file and fail every mutation.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from src.jd_core.models.parsed_jd import SFUEmployeeGroup
from src.jd_core.parser.classification import extract_classification
from src.jd_core.rules import (
    RULE_FILES,
    Classification,
    Rules,
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


def _raw() -> dict[str, Any]:
    """The shipped ``classification.yaml``, as the loader sees it before validation."""
    data: dict[str, Any] = yaml.safe_load(
        (_PKG_DIR / "classification.yaml").read_text(encoding="utf-8")
    )
    return data


def retuned_classification(**fields: Any) -> Classification:
    """The shipped file re-validated with ``fields`` overridden — the "what if HR moved
    it" fixture, built from the REAL yaml text so a retuning the rulebook would reject
    (a pattern with no capturing group) fails here exactly as it would at load."""
    return Classification.model_validate({**_raw(), **fields})


# --- it ships, it loads, it is on the surface ---------------------------------------


def test_classification_yaml_ships_and_loads(rules: Rules) -> None:
    assert "classification.yaml" in RULE_FILES
    assert (_PKG_DIR / "classification.yaml").is_file()
    assert isinstance(rules.classification, Classification)
    assert rules.classification.version == rules.declared_version


def test_the_shipped_classification_defaults(rules: Rules) -> None:
    """The three matchers moved out of ``parser/classification.py`` CHARACTER FOR
    CHARACTER — P3f registered them, it did not retune them, which is why the parse is
    byte-identical and ``PARSER_VERSION`` did not bump."""
    c = rules.classification
    assert (
        c.cupe_grade_pattern.pattern == r"(?i)\b(?:gr\.?|grade)\s*[:#]?\s*(\d{1,2})\b"
    )
    assert (
        c.jdfn_grade_approved_pattern.pattern
        == r"(?i)grade\s+approved\s*[:#]?\s*((?:PG\s*)?\d{1,2})\b"
    )
    assert (
        c.jdfn_grade_field_pattern.pattern
        == r"(?im)^[ \t]*(?:pay )?grade[ \t]*[:#][ \t]*((?:PG[ \t]*)?\d{1,2})\b"
    )
    assert c.jdfn_schemes == ("apsa", "apex", "poly")


def test_every_classification_knob_is_on_the_decision_surface(rules: Rules) -> None:
    """FINDINGS §9e: `classification` was pulled by hardcoded regex, so the field audit
    could not see it at all and reported it UNEVALUATED rather than clean. The whole
    point of P3f is that each matcher is now a registered parameter."""
    surface = decision_surface(rules)
    assert {
        "classification.cupe_grade_pattern",
        "classification.jdfn_grade_approved_pattern",
        "classification.jdfn_grade_field_pattern",
        "classification.jdfn_schemes",
    } <= surface
    check_register(rules)  # every one of them is registered or explicitly exempted


# --- unhashed, but registered -------------------------------------------------------


def test_classification_is_the_tenth_unhashed_file(rules: Rules) -> None:
    assert "classification.yaml" in loader._UNHASHED_FILES
    assert "classification" not in loader._HASHED_FIELDS


def test_retuning_a_grade_matcher_leaves_rules_version_untouched(
    tmp_path: Path, rules: Rules
) -> None:
    """**THE property this arrangement exists for.** No validator reads
    `classification`, so retuning a matcher cannot move a single JD's score — and must
    not invalidate the stamp on every report ever produced. (For ``wjq.yaml`` the
    equivalent mutation deliberately DOES move it.)"""
    _write_valid_rules(tmp_path)
    _patch(
        tmp_path,
        "classification.yaml",
        lambda d: d.__setitem__(
            "cupe_grade_pattern",
            {"pattern": r"(?i)\bband\s*(\d{1,2})\b", "ignore_case": False},
        ),
    )
    retuned = load_rules(tmp_path)

    assert retuned.version == rules.version
    assert retuned.content_hash == rules.content_hash
    assert (
        retuned.classification.cupe_grade_pattern.pattern == r"(?i)\bband\s*(\d{1,2})\b"
    )


def test_editing_a_hashed_rule_file_still_moves_rules_version(
    tmp_path: Path, rules: Rules
) -> None:
    """The other half — otherwise the test above would pass on a hash tracking nothing
    at all."""
    _write_valid_rules(tmp_path)
    _patch(tmp_path, "thresholds.yaml", lambda d: d.__setitem__("duties_max", 9))
    assert load_rules(tmp_path).version != rules.version


# --- the extractor READS the data ---------------------------------------------------
# Each of these fails against the pre-P3f module, which held the pattern as a constant.


def test_cupe_grade_follows_the_yaml_not_a_constant() -> None:
    """Retune the CUPE matcher to read the word as "band"; the extractor follows."""
    retuned = retuned_classification(
        cupe_grade_pattern={
            "pattern": r"(?i)\bband\s*(\d{1,2})\b",
            "ignore_case": False,
        }
    )
    # The shipped spelling no longer matches...
    assert extract_classification("Secretary, grade 8", "cupe", retuned) is None
    # ...and the retuned one does.
    got = extract_classification("Secretary, band 8", "cupe", retuned)
    assert got is not None and got.scheme == "cupe" and got.value == "8"


def test_jdfn_grade_field_anchor_follows_the_yaml() -> None:
    """HR-235's ``(?m)^`` anchor is the rule. Retune it away and the "grade 12 students"
    prose the shipped matcher correctly refuses starts being read as a grade — which is
    the 430-garbage-grades defect, reproduced on demand."""
    unanchored = retuned_classification(
        jdfn_grade_field_pattern={
            "pattern": r"(?i)grade[ \t]*(\d{1,2})\b",
            "ignore_case": False,
        }
    )
    prose = "Supports grade 12 students in the program"
    assert extract_classification(prose, "apsa") is None  # shipped rules: refused
    got = extract_classification(prose, "apsa", unanchored)
    assert got is not None and got.value == "12"  # retuned: the defect is back


@pytest.mark.parametrize("group", ["apsa", "apex", "poly"])
def test_a_listed_group_records_its_own_scheme(group: SFUEmployeeGroup) -> None:
    got = extract_classification("Classification & Grade Approved: 8", group)
    assert got is not None and got.scheme == group


def test_dropping_a_group_from_jdfn_schemes_downgrades_it_to_unknown() -> None:
    """HR-236's honest failure: a group we cannot name a scale for keeps its GRADE and
    loses its SCHEME, rather than being attributed to the wrong pay ladder."""
    without_apex = retuned_classification(jdfn_schemes=["apsa", "poly"])
    got = extract_classification(
        "Classification & Grade Approved: 8", "apex", without_apex
    )
    assert got is not None and got.value == "8" and got.scheme == "unknown"


# --- the loader refuses rule data that cannot work ----------------------------------


def test_a_grade_pattern_with_no_capturing_group_is_a_load_error() -> None:
    """The grade is read from ``group(1)``. A pattern edited down to no capturing group
    still compiles and still matches, then raises ``IndexError`` inside a parser that is
    contractually total — on whichever archive document states a grade first."""
    with pytest.raises(Exception, match="no capturing group"):
        retuned_classification(
            cupe_grade_pattern={
                "pattern": r"(?i)\bgrade\s*\d{1,2}\b",
                "ignore_case": False,
            }
        )


def test_a_scheme_that_is_not_an_employee_group_is_a_load_error() -> None:
    with pytest.raises(Exception, match="not SFU employee groups"):
        retuned_classification(jdfn_schemes=["apsa", "faculty"])


def test_an_empty_scheme_table_is_a_load_error() -> None:
    """A table nothing can be parsed into is this rulebook's standing objection: a gate
    that can never fire is a false safety guarantee."""
    with pytest.raises(Exception, match="at least one employee group"):
        retuned_classification(jdfn_schemes=[])


def test_a_repeated_scheme_is_a_load_error() -> None:
    with pytest.raises(Exception, match="jdfn_schemes"):
        retuned_classification(jdfn_schemes=["apsa", "apsa"])

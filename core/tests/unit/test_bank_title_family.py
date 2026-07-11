"""Title classification on SFU's two title dimensions (ported from hris).

The behavioural spec is hris ``tests/unit/test_jd_bank_title_family.py`` — every
case there is reproduced here verbatim (imports rewritten). It is the oracle: the
port passes it or the port is wrong.

What this port *adds* is the rulebook-as-data half (CLAUDE.md §2). hris hardcoded
four Python tables — the seniority ladder, its keywords, the Application Table and
*its* keywords — and, critically, hardcoded the ORDER they are tried in. That order
is policy, not implementation: trying ``manager`` before ``director`` is the entire
reason "Associate Director" is a manager. So the tables and the order are now
``rules/titles.yaml``, and the tests below prove the classifier reads them —
including a test that SHUFFLES the match order in a scratch rulebook and watches the
classification change. If the order were cosmetic, that test could not exist.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from src.jd_core.bank import (
    classify_title,
    classify_title_family,
    classify_title_function,
    title_comma_supervisory,
)
from src.jd_core.rules import RULE_FILES, Rules, load_rules

# --- the hris spec: seniority family ------------------------------------------


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("VP Finance and Administration", "vp"),
        ("AVP Human Resources", "vp"),
        ("Associate Vice President, Students", "vp"),  # not "associate"
        ("Chief Information Officer", "chief"),
        ("CIO", "chief"),
        ("Director, Marketing and Communications", "director"),
        # SFU groups Associate Director under manager
        ("Associate Director, Advancement", "manager"),
        ("Manager, Communications", "manager"),
        ("Bookstore Supervisor", "manager"),
        ("Lead Athletic Therapist", "lead"),
        ("Service Desk Team Lead", "lead"),
        ("Communications Associate", "associate"),
        ("Sales Representative", "associate"),
        ("Administrative Assistant", "assistant"),
        ("Executive Assistant", "assistant"),
        ("PeopleSoft Developer", "unmapped"),  # no ladder keyword
    ],
)
def test_title_family_classification(title: str, expected: str) -> None:
    assert classify_title_family(title).family == expected


def test_result_carries_label_and_matched_keyword() -> None:
    r = classify_title_family("Manager, Residence Life")
    assert r.family == "manager"
    assert "Manager" in r.label
    assert r.matched_on == "manager"


def test_supervisory_signal_sharpens_rationale_only() -> None:
    with_sup = classify_title_family("Manager, Ops", has_supervisory=True)
    without = classify_title_family("Manager, Ops", has_supervisory=False)
    # never overrides the title
    assert with_sup.family == without.family == "manager"
    assert "supervises staff" in with_sup.rationale
    assert "supervises staff" not in without.rationale


def test_unmapped_is_explicit() -> None:
    r = classify_title_family("Widget Wrangler")
    assert r.family == "unmapped"
    assert r.matched_on is None
    assert "manually" in r.rationale.lower()


# --- the hris spec: functional title type (Application Table, Part 3.3) -------


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Data Analyst", "analyst"),  # family unmapped, but function analyst
        ("Communications Coordinator", "coordinator"),
        ("Procurement Officer", "officer"),
        ("HR Consultant", "consultant"),
        ("Learning Specialist", "specialist"),
        ("Associate Director, Advancement", "associate_director"),  # not "director"
        ("Director, Finance", "director"),
        ("Executive Director", "executive"),  # not "director"
        ("Manager, Communications", "manager"),
        ("Administrative Assistant", "assistant"),
        ("Widget Wrangler", "unmapped"),
    ],
)
def test_title_function_classification(title: str, expected: str) -> None:
    assert classify_title_function(title).function == expected


def test_function_is_independent_of_family() -> None:
    # "Data Analyst" has no ladder keyword (family unmapped) but a clear function.
    assert classify_title_family("Data Analyst").family == "unmapped"
    r = classify_title_function("Data Analyst")
    assert r.function == "analyst"
    assert r.matched_on == "analyst"


# --- the hris spec: comma-format supervisory signal (Part 3.4) ----------------


def test_comma_format_signals_supervision_for_role_word_first() -> None:
    assert title_comma_supervisory("Manager, Laboratory Operations") is True
    assert title_comma_supervisory("Director, Finance") is True
    assert title_comma_supervisory("Vice President, Finance") is True


def test_no_comma_or_non_role_prefix_is_not_supervisory() -> None:
    # no comma
    assert title_comma_supervisory("Laboratory Operations Manager") is False
    # prefix is not a role word
    assert title_comma_supervisory("Software Developer, Platform") is False


# --- the combined result -----------------------------------------------------


def test_classify_title_carries_both_dimensions_and_the_comma_signal() -> None:
    tc = classify_title("Manager, Laboratory Operations", has_supervisory=True)
    assert tc.family.family == "manager"
    assert tc.function.function == "manager"
    assert tc.comma_supervisory is True
    assert "supervises staff" in tc.family.rationale


def test_the_comma_format_is_itself_a_supervisory_signal() -> None:
    """hris ORs the two supervision signals before classifying::

        classify_title_family(title, has_supervisory=rel_supervisory or comma_sup)

    The caller supplies what it knows from the Relationships section; the title's
    own "Role, Descriptor" format supplies the rest. So a comma-format title earns
    the "(supervises staff)" rationale with ``has_supervisory`` **defaulted** —
    nobody has to tell it.

    An earlier version of this port passed ``has_supervisory`` straight through and
    dropped the OR. The test above could not see it: it sets the flag explicitly, so
    it passes either way. This one is the one that fails."""
    tc = classify_title("Manager, Laboratory Operations")  # NOT told about reports
    assert tc.comma_supervisory is True
    assert "supervises staff" in tc.family.rationale

    # ...and the two signals really are independent: the Relationships half alone
    # still works on a title whose FORMAT says nothing.
    trailing = classify_title("Laboratory Operations Manager", has_supervisory=True)
    assert trailing.comma_supervisory is False
    assert "supervises staff" in trailing.family.rationale

    # ...while a title with neither signal claims neither.
    silent = classify_title("Laboratory Operations Manager")
    assert silent.comma_supervisory is False
    assert "supervises staff" not in silent.family.rationale


def test_the_comma_signal_never_overrides_the_family() -> None:
    """The OR feeds the *rationale*, not the classification — same guarantee hris
    makes for the Relationships signal."""
    for title in ("Manager, Ops", "Director, Finance", "Software Developer, Platform"):
        assert (
            classify_title(title).family.family == classify_title_family(title).family
        )


def test_classify_title_on_a_title_with_neither_dimension() -> None:
    tc = classify_title("Widget Wrangler")
    assert tc.family.family == "unmapped"
    assert tc.function.function == "unmapped"
    assert tc.comma_supervisory is False


# --- rulebook-as-data: the tables and their ORDER live in titles.yaml ---------

_PKG_DIR = Path(__file__).resolve().parents[2] / "src" / "jd_core" / "rules"


def _rules_with_titles(directory: Path, mutate: Any) -> Rules:
    """The shipped rulebook, with ``titles.yaml`` mutated. Nothing else changes."""
    for name in RULE_FILES:
        (directory / name).write_text(
            (_PKG_DIR / name).read_text(encoding="utf-8"), encoding="utf-8"
        )
    path = directory / "titles.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    mutate(data)
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return load_rules(directory)


def test_the_classifier_reads_the_shipped_keywords_not_a_hardcoded_table(
    tmp_path: Path,
) -> None:
    """Teach the rulebook a new keyword and the classifier learns it — with no code
    change. That is the whole point of non-negotiable #2."""

    def _teach(data: dict[str, Any]) -> None:
        data["family_keywords"]["lead"].append("principal")

    tuned = _rules_with_titles(tmp_path, _teach)
    assert classify_title_family("Principal Engineer").family == "unmapped"
    assert classify_title_family("Principal Engineer", rules=tuned).family == "lead"


def test_shuffling_the_family_match_order_reclassifies_associate_director(
    tmp_path: Path,
) -> None:
    """**Order is semantic.** "Associate Director" carries BOTH a manager keyword
    ("associate director") and a director keyword ("director"); which one wins is
    decided purely by ``family_match_order``. Swap the two rungs in the YAML and
    the very same title becomes a *director*.

    If the YAML representation did not preserve sequence — a mapping, a set, an
    alphabetised list — this test could not fail, and the port would have silently
    dropped a rulebook decision. It fails. That is the proof."""
    shipped = classify_title_family("Associate Director, Advancement")
    assert shipped.family == "manager"
    assert shipped.matched_on == "associate director"

    def _try_director_first(data: dict[str, Any]) -> None:
        order = list(data["family_match_order"])
        i, j = order.index("manager"), order.index("director")
        order[i], order[j] = order[j], order[i]
        data["family_match_order"] = order

    shuffled = _rules_with_titles(tmp_path, _try_director_first)
    now = classify_title_family("Associate Director, Advancement", rules=shuffled)
    assert now.family == "director"
    assert now.matched_on == "director"


def test_shuffling_the_function_match_order_reclassifies_executive_director(
    tmp_path: Path,
) -> None:
    """The same proof on the functional dimension: "Executive Director" is an
    executive only because ``executive`` is tried before ``director``."""
    assert classify_title_function("Executive Director").function == "executive"

    def _try_director_first(data: dict[str, Any]) -> None:
        order = list(data["function_match_order"])
        order.remove("director")
        order.insert(0, "director")
        data["function_match_order"] = order

    shuffled = _rules_with_titles(tmp_path, _try_director_first)
    got = classify_title_function("Executive Director", rules=shuffled)
    assert got.function == "director"


def test_the_comma_supervisory_families_are_data(tmp_path: Path) -> None:
    """Which families read the "Role, Descriptor" comma as supervision is a policy
    call, not a set literal in a function body."""
    assert title_comma_supervisory("Lead, Athletic Therapy") is True

    def _drop_lead(data: dict[str, Any]) -> None:
        data["comma_supervisory_families"] = [
            f for f in data["comma_supervisory_families"] if f != "lead"
        ]

    tuned = _rules_with_titles(tmp_path, _drop_lead)
    assert title_comma_supervisory("Lead, Athletic Therapy", rules=tuned) is False
    # ...and the families still in the set are unaffected
    assert title_comma_supervisory("Manager, Ops", rules=tuned) is True


# --- the rulebook cannot ship an unusable title table -------------------------


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        # a rung on the ladder that nothing can ever match
        (lambda d: d["family_keywords"].pop("lead"), "family_keywords"),
        # keywords for a rung that is not on the ladder
        (
            lambda d: d["family_keywords"].__setitem__("czar", ["czar"]),
            "family_keywords",
        ),
        # a rung the classifier could match but could not label
        (lambda d: d["family_labels"].pop("lead"), "family_labels"),
        # a rung nothing tries
        (
            lambda d: d.__setitem__(
                "family_match_order",
                [f for f in d["family_match_order"] if f != "lead"],
            ),
            "family_match_order",
        ),
        # the no-match state is not a rung
        (lambda d: d["families"].append("unmapped"), "unmapped"),
        # a comma-supervisory family that does not exist
        (
            lambda d: d["comma_supervisory_families"].append("czar"),
            "comma_supervisory_families",
        ),
        # a function row nothing tries
        (
            lambda d: d.__setitem__(
                "function_match_order",
                [f for f in d["function_match_order"] if f != "analyst"],
            ),
            "function_match_order",
        ),
    ],
)
def test_an_inconsistent_title_table_fails_to_load(
    tmp_path: Path, mutation: Any, expected: str
) -> None:
    """A ladder and a classifier that disagree is a JD misclassified in silence.
    Every way they can disagree is a load error instead."""
    from src.jd_core.rules import RulesError

    with pytest.raises(RulesError) as exc:
        _rules_with_titles(tmp_path, mutation)
    assert expected in str(exc.value)

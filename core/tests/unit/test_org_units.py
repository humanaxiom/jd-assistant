"""The org-unit rollup (Track E / MVP-2) — the tree, the normaliser, and the three
numbers.

The rollup is the one setting that decides what a vice-president is told about their own
portfolio, and nothing downstream would notice it being wrong. So the tests here are
about the properties that make a wrong answer *impossible to ship quietly*: the tree
cannot name a unit that does not exist, membership cannot be a pattern, and the counts
must partition the whole population rather than reporting only the flattering third.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.jd_bank.library.models import UnitCandidate, UnitRollup
from src.jd_bank.library.units import normalize_department, unit_departments
from src.jd_core.rules import OrgUnit, OrgUnits, Rules, get_rules


@pytest.fixture(scope="module")
def rules() -> Rules:
    return get_rules()


def _units(**units: OrgUnit) -> OrgUnits:
    return OrgUnits(version="jd_rules_sfu_v4", units=units)


def _unit(
    slug: str, *, departments: tuple[str, ...] = (), children: tuple[str, ...] = ()
) -> OrgUnit:
    return OrgUnit(
        label=slug.upper(), slug=slug, departments=departments, children=children
    )


# --- the normaliser: mechanical only, and deliberately narrow ------------------------


def test_an_ampersand_and_the_word_and_are_the_same_department() -> None:
    """`Safety & Risk Services` (5 roles) and `Safety and Risk Services` (3) are one
    unit differing by a character. That is a SPELLING rule, so the normaliser owns
    it and the rulebook lists the department once."""
    assert normalize_department("Safety & Risk Services") == normalize_department(
        "Safety and Risk Services"
    )


def test_case_whitespace_and_unicode_dashes_are_normalised() -> None:
    """The archive mixes en dashes, em dashes and hyphens WITHIN one unit —
    `Facilities Management – SFU Surrey` beside `IT Services - Infrastructure`."""
    assert normalize_department("  IT   Services –  Infrastructure ") == (
        "it services - infrastructure"
    )


def test_word_order_is_not_normalised() -> None:
    """🔴 THE LINE BETWEEN MECHANICAL AND JUDGEMENT, and it is deliberate.

    `IT Services, Application Services` and `Application Services, IT Services` both
    appear in the archive. Deciding they name the same team is an ORGANISATIONAL claim,
    not a spelling rule — so the normaliser leaves them distinct and the rulebook lists
    both, where a human can see what was assumed.
    """
    assert normalize_department("IT Services, Application Services") != (
        normalize_department("Application Services, IT Services")
    )


def test_a_missing_department_normalises_to_empty() -> None:
    """27.1% of roles carry none. They must land in the unrecorded bucket, never be
    matched against a unit by accident."""
    assert normalize_department(None) == ""
    assert normalize_department("   ") == ""


# --- the tree: a rollup includes its children ---------------------------------------


def test_a_parents_departments_include_its_childrens() -> None:
    """What "rolls up into" MEANS. Facilities Services rolling up into VPFA is the case
    this was built for: a Facilities role is a VPFA role."""
    units = _units(
        parent=_unit("parent", departments=("finance",), children=("child",)),
        child=_unit("child", departments=("facilities services",)),
    )
    rules = get_rules().model_copy(update={"org_units": units})
    assert unit_departments("parent", rules) == {"finance", "facilities services"}
    # ...and the child does NOT inherit upward.
    assert unit_departments("child", rules) == {"facilities services"}


def test_the_shipped_tree_rolls_facilities_up_into_vpfa(rules: Rules) -> None:
    """The owner's ruling 2026-09-09, pinned against the shipped rulebook rather than
    described in a comment."""
    vpfa = unit_departments("vpfa", rules)
    facilities = unit_departments("facilities_services", rules)
    assert facilities, "precondition: Facilities has departments"
    assert facilities <= vpfa


def test_campus_security_is_in_facilities(rules: Rules) -> None:
    """The boundary call Track E flagged as open and the owner settled. Pinned because
    it is a decision, and a decision nobody can find is one that gets re-litigated."""
    assert "campus security" in unit_departments("facilities_services", rules)


def test_science_it_services_is_not_claimed_by_its(rules: Rules) -> None:
    """🔴 THE FALSE POSITIVE A PATTERN WOULD PRODUCE. `Science - IT Services` exists in
    the archive and may be a faculty's own IT. A phrase match on "IT Services" claims it
    for the central ITS either way; the exact list does not."""
    assert "science - it services" not in unit_departments("its", rules)
    assert "it services" in unit_departments("its", rules)


def test_human_resources_is_not_in_vpfa_because_nobody_placed_it(rules: Rules) -> None:
    """52 roles — the largest single candidate — deliberately NOT rolled up. It was not
    named, and inferring it is exactly what hands a vice-president a wrong number."""
    assert "human resources" not in unit_departments("vpfa", rules)


# --- the loader refuses a tree that cannot be resolved -------------------------------


def test_a_child_that_names_no_unit_is_refused() -> None:
    """A dangling child contributes nothing and looks like a configured rollup — the
    exact shape of a confidently wrong portfolio number. The rulebook fails to load."""
    with pytest.raises(ValidationError, match="not a unit"):
        _units(parent=_unit("parent", children=("ghost",)))


def test_a_cycle_is_refused() -> None:
    """A cycle would hang the resolver, and a rulebook that can hang a page should fail
    to load instead."""
    with pytest.raises(ValidationError, match="cycle"):
        _units(
            a=_unit("a", children=("b",)),
            b=_unit("b", children=("a",)),
        )


def test_a_unit_may_not_be_its_own_child() -> None:
    with pytest.raises(ValidationError, match="itself"):
        _units(a=_unit("a", children=("a",)))


# --- three numbers, always ----------------------------------------------------------


def test_the_three_numbers_partition_the_population() -> None:
    """🔴 THE PROPERTY THE PAGE DEPENDS ON. `in_unit` alone reads as complete while
    being blind to the roles whose department nobody recorded — 677 of 2,496 (27.1%)
    when this shipped. The IT collection went out without a could-not-evaluate bucket
    once already."""
    rollup = UnitRollup(
        label="VPFA",
        slug="vpfa",
        in_unit=54,
        not_in_unit=1765,
        department_unrecorded=677,
    )
    assert rollup.population == 2496
    assert rollup.in_unit + rollup.not_in_unit + rollup.department_unrecorded == (
        rollup.population
    )


def test_unrecorded_is_never_folded_into_not_in_unit() -> None:
    """Belongs-elsewhere and cannot-tell are different answers, and only one of them is
    a finding. A model carrying a single "other" count would make the distinction
    unavailable to the template."""
    fields = set(UnitRollup.model_fields)
    assert {"in_unit", "not_in_unit", "department_unrecorded"} <= fields


def test_a_candidate_carries_its_own_role_count() -> None:
    """The unassigned list is the question the rulebook has not answered. Without the
    count a reader cannot tell a 52-role omission from a 1-role one."""
    candidate = UnitCandidate(department="human resources", roles=52)
    assert (candidate.department, candidate.roles) == ("human resources", 52)


def test_campus_services_ships_empty_and_that_is_deliberate(rules: Rules) -> None:
    """🔴 THE EMPTINESS IS THE FINDING. Campus Services was named as a VPFA sub-unit and
    NO department string in the archive names it. It ships empty and renders "0 roles,
    and here is why" — because a unit that reports zero with its reason is answerable,
    while one quietly filled by inference is the confidently wrong number this whole
    track exists to avoid."""
    assert unit_departments("campus_services", rules) == frozenset()

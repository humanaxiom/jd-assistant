"""The Bank content audit — the READINGS, which is where its bugs were.

Every test here corresponds to a false or missing reading the audit produced on a real
run against the live Bank, because all three were the same class of mistake: a number
that was arithmetically fine and meant the wrong thing. The queries are exercised in
``tests/integration/test_bank_audit.py``; this file pins what the numbers MEAN.
"""

from __future__ import annotations

import pytest

from src.jd_bank.bank_audit.metrics import _group_sql
from src.jd_bank.bank_audit.models import CarryThrough, RewriteHealth
from src.jd_core.models.parsed_jd import SFUJobDescription
from src.jd_core.quality.validators import template_of


def _carry(**kw: object) -> CarryThrough:
    base: dict[str, object] = {"section": "relationships", "offered": 100, "kept": 100}
    base.update(kw)
    return CarryThrough(**base)  # type: ignore[arg-type]


# --- the form split must agree with the validator's, or the audit under-reports -------


@pytest.mark.parametrize("group", ["apsa", "apex", "poly", "cupe", None])
def test_the_audits_form_split_matches_the_validators(group: str | None) -> None:
    """🔴 THE AUDIT'S OWN FIRST BUG, caught by its own first run against the live Bank.

    ``_group_sql("jdfn")`` was an allow-list — ``IN ('apsa','apex','poly')`` — which
    silently omitted **1,300 drafts** whose ``employee_group`` is null. 31.9% of the
    archive does not state its group in a way the reader has recovered yet, and those
    documents are still parsed, still drafted and still scored. The audit reported 541
    JDFN drafts where the Bank holds 1,841 — an under-report of the exact cohort it
    exists to watch, in the tool built to stop under-reporting.

    ``template_of`` treats every non-CUPE document as JDFN. This pins the SQL to that,
    including the null case, which is the one that broke.
    """
    jd = SFUJobDescription(title="Analyst", employee_group=group)
    expected = template_of(jd)
    # The SQL predicate for the expected form must be the one that matches this group.
    if expected == "wjq":
        assert _group_sql("wjq") == "IN ('cupe',)".replace(",)", ")")
    else:
        # NULL-safe by construction: `IS DISTINCT FROM` is what makes a null group JDFN
        # rather than neither form. `<>` would evaluate NULL and drop the row.
        assert "IS DISTINCT FROM" in _group_sql("jdfn")


def test_the_jdfn_predicate_is_null_safe() -> None:
    """The specific SQL fact behind the 1,300 missing drafts: ``NULL <> 'cupe'`` is
    NULL, not true, so a plain inequality drops every unclassified row."""
    assert "<>" not in _group_sql("jdfn")
    assert "IS DISTINCT FROM" in _group_sql("jdfn")


# --- a reading is a VERDICT, and three things are not defects -------------------------


def test_content_the_sources_offered_and_the_bank_kept_is_not_a_shortfall() -> None:
    assert _carry(offered=473, kept=473).is_shortfall is False


def test_content_the_bank_dropped_is_a_shortfall() -> None:
    c = _carry(offered=473, kept=426)
    assert c.is_shortfall is True
    assert c.retention_pct == 90.1


def test_a_section_no_source_states_is_not_a_shortfall() -> None:
    """0/0. No CUPE source document states Problem Solving — a fact about the WJQ form,
    not a loss. The audit's first run rendered this as '0.0%' with a red flag, which is
    how a metric teaches people to ignore it."""
    c = _carry(offered=0, kept=0)
    assert c.is_shortfall is False
    assert c.retention_pct == 0.0


def test_a_section_the_rulebook_deliberately_drops_is_not_a_shortfall() -> None:
    """HR-169 sets JDFN ``additional_context`` to ``drop``, so 0% is the Bank doing
    what it was told. A metric that cannot tell a policy from a bug is noise."""
    assert (
        _carry(
            section="additional_context", offered=20, kept=0, policy="drop"
        ).is_shortfall
        is False
    )
    # ...and the same numbers under a carrying policy ARE a defect.
    assert (
        _carry(
            section="additional_context", offered=20, kept=0, policy="longest"
        ).is_shortfall
        is True
    )


# --- above 100% is the opposite failure, and must not be collapsed into "not 100%" ----


def test_more_drafts_than_sources_is_fabrication_not_a_shortfall() -> None:
    """🔴 THE FABRICATION DETECTOR, found by accident. The audit's first correct run
    reported JDFN ``problem_solving`` at **228.2% (1,084 / 475)** — which looks like an
    arithmetic bug and is not. A draft can only carry what its sources stated, so above
    100% means the Bank holds content **no source document ever wrote**: the S-5 defect
    (1,084 drafts carrying an invented section, scoring ~18 points higher for it) as one
    number instead of a five-page argument.

    Losing content and inventing it are opposite failures with opposite fixes, so they
    are separate readings. Collapsing both into 'not 100%' would hide the worse one.
    """
    c = _carry(section="problem_solving", offered=475, kept=1084)
    assert c.is_fabrication is True
    assert c.is_shortfall is False  # NOT a shortfall — the opposite failure
    assert c.retention_pct == 228.2


def test_exact_carry_through_is_neither_failure() -> None:
    c = _carry(offered=620, kept=620)
    assert (c.is_fabrication, c.is_shortfall) == (False, False)


# --- the rewrite's controlled comparison ---------------------------------------------


def test_the_merge_only_control_exposes_a_rewrite_that_destroys_a_field() -> None:
    """The natural experiment the Bank produces for free. A rewrite FAILURE falls back
    to the deterministic merge, so those drafts are the same pipeline with the model
    removed. Measured on the live CUPE cohort 2026-08-22 — 23.5% vs 75.0% — which is
    what turned 'frequencies are low' into 'the rewrite destroys them'."""
    r = RewriteHealth(
        rewritten_duties=7341,
        rewritten_with_frequency=1723,
        merge_only_duties=84,
        merge_only_with_frequency=63,
        duties_total=7425,
        duties_flagged=5068,
        drafts=649,
        drafts_with_a_flagged_duty=638,
    )
    assert r.rewritten_frequency_pct == 23.5
    assert r.merge_only_frequency_pct == 75.0
    assert r.merge_only_frequency_pct > r.rewritten_frequency_pct


def test_a_flag_on_nearly_every_draft_is_reported_as_a_share() -> None:
    """98.3% of CUPE drafts carry a flagged duty. A finding present on almost every
    draft is a constant, not a signal — the pathology this repo has now hit three
    times, and the share is the only form in which it is visible."""
    r = RewriteHealth(
        rewritten_duties=1,
        rewritten_with_frequency=0,
        merge_only_duties=0,
        merge_only_with_frequency=0,
        duties_total=7425,
        duties_flagged=5068,
        drafts=649,
        drafts_with_a_flagged_duty=638,
    )
    assert r.drafts_flagged_pct == 98.3
    assert r.flagged_duty_pct == 68.3


def test_an_empty_cohort_reports_zero_rather_than_dividing_by_zero() -> None:
    """A form with no drafts is a real state (a scoped run, a fresh Bank), and a report
    that raises on it is a report nobody can run before the first pass."""
    r = RewriteHealth(
        rewritten_duties=0,
        rewritten_with_frequency=0,
        merge_only_duties=0,
        merge_only_with_frequency=0,
        duties_total=0,
        duties_flagged=0,
        drafts=0,
        drafts_with_a_flagged_duty=0,
    )
    assert (r.rewritten_frequency_pct, r.drafts_flagged_pct) == (0.0, 0.0)

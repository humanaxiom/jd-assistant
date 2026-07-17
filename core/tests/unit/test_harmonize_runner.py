"""The Phase-4.1 harmonization MEASUREMENT pass — pure aggregation + WJQ proxy.

Fixtures are realistic JDFN members (title + summary + duties + quals), not degenerate
stubs — a fixture that makes a bug unwritable is a defect (HANDOFF). Every measurement
that a knob calibrates on is pinned by MUTATION: a threshold sweep goes red at the
boundary, the WJQ proxy's count moves when a member's group flips, member-order
invariance is pinned byte-identical, and the stamp moves when a knob moves.

The DB-bound behaviours (recompute-clusters, real WJQ drop, drop-not-crash, read-only,
determinism over a real corpus) are pinned in ``tests/integration/test_harmonize.py``.
"""

from __future__ import annotations

import random
import uuid

import pytest

from src.jd_bank.harmonize.models import ClusterHarmonization
from src.jd_bank.harmonize.runner import (
    _Agg,
    deduped_duty_count,
    harmonize_stamp,
    is_wjq_member,
    measure_cluster,
    member_has_frequency,
)
from src.jd_core.models.parsed_jd import (
    SFUDuty,
    SFUJobDescription,
    SFUQualification,
)
from src.jd_core.rules import Rules, get_rules

_NS = uuid.UUID("00000000-0000-0000-0000-0000000000aa")


@pytest.fixture(scope="module")
def rules() -> Rules:
    return get_rules()


def _with(rules: Rules, **harmon: object) -> Rules:
    return rules.model_copy(
        update={"harmonization": rules.harmonization.model_copy(update=harmon)}
    )


def _member(**overrides: object) -> SFUJobDescription:
    base: dict[str, object] = {
        "title": "Budget Analyst",
        "department": "Financial Services",
        "grade": "B80",
        "employee_group": "apsa",
        "position_summary": "Supports the annual operating budget cycle for faculty.",
        "duties": [
            SFUDuty(action_verb="Prepares", statement="the annual operating budget."),
            SFUDuty(action_verb="Reconciles", statement="monthly ledger variances."),
        ],
        "qualifications": [
            SFUQualification(
                text="a bachelor's degree in accounting", kind="education"
            ),
            SFUQualification(
                text="budget forecasting", kind="skill", modifier="advanced"
            ),
        ],
    }
    base.update(overrides)
    return SFUJobDescription(**base)  # type: ignore[arg-type]


# --- the WJQ proxy (template is not persisted) --------------------------------------


def test_wjq_proxy_is_the_cupe_employee_group() -> None:
    assert is_wjq_member(_member(employee_group="cupe")) is True
    assert is_wjq_member(_member(employee_group="apsa")) is False
    assert is_wjq_member(_member(employee_group=None)) is False


def test_frequency_marker_is_the_wjq_only_cross_signal() -> None:
    wjq_like = _member(
        employee_group="cupe",
        duties=[SFUDuty(statement="runs the mailroom.", frequency="daily")],
    )
    assert member_has_frequency(wjq_like) is True
    assert member_has_frequency(_member()) is False


# --- duty dedup count (the HR-171 knee) ---------------------------------------------


def test_deduped_duty_count_collapses_near_identical_statements() -> None:
    # Two statements sharing 6 of 8 union tokens -> exact Jaccard 0.75.
    stmts = [
        "prepares the annual operating budget for the faculty",
        "prepares the annual operating budget for the department",
    ]
    # BOUNDARY: 0.75 >= 0.7 collapses to one; 0.75 < 0.8 splits back to two.
    assert deduped_duty_count(stmts, 0.7) == 1
    assert deduped_duty_count(stmts, 0.8) == 2


def test_deduped_duty_count_keeps_distinct_statements_separate() -> None:
    stmts = ["writes grant applications", "maintains the vehicle fleet"]
    assert deduped_duty_count(stmts, 0.7) == 2


def test_deduped_duty_count_is_order_independent() -> None:
    stmts = [
        "prepares the annual operating budget for the faculty",
        "maintains the vehicle fleet",
        "prepares the annual operating budget for the department",
    ]
    assert deduped_duty_count(stmts, 0.7) == deduped_duty_count(
        list(reversed(stmts)), 0.7
    )


# --- per-cluster measurement + aggregation ------------------------------------------


def _cluster_of_four(rules: Rules) -> tuple[ClusterHarmonization, _Agg]:
    """Four realistic members: 'python' required by exactly 2 (fraction 0.5), six
    distinct duties spread across them, one member carrying additional_context."""
    m1 = _member(
        duties=[
            SFUDuty(statement="prepares the annual operating budget."),
            SFUDuty(statement="reconciles monthly ledger variances."),
        ],
        qualifications=[SFUQualification(text="python", kind="skill")],
    )
    m2 = _member(
        title="Senior Budget Analyst",
        duties=[
            SFUDuty(statement="audits departmental procurement records."),
            SFUDuty(statement="drafts the quarterly financial forecast."),
        ],
        qualifications=[SFUQualification(text="python", kind="skill")],
        additional_context="On-call during fiscal year-end close.",
    )
    m3 = _member(
        duties=[SFUDuty(statement="administers the research grant ledger.")],
        qualifications=[SFUQualification(text="tableau", kind="skill")],
    )
    m4 = _member(
        duties=[SFUDuty(statement="coordinates the vendor onboarding workflow.")],
        qualifications=[SFUQualification(text="excel", kind="skill")],
    )
    agg = _Agg()
    rec = measure_cluster(_NS, [m1, m2, m3, m4], 0, agg, rules=rules)
    return rec, agg


def test_measure_records_member_count_and_uncapped_duty_count(rules: Rules) -> None:
    rec, _agg = _cluster_of_four(rules)
    assert rec.jdfn_member_count == 4
    assert rec.deduped_duty_count == 6  # six distinct duties, none near-identical


def test_core_skill_fraction_is_a_boundary_the_knob_cuts(rules: Rules) -> None:
    # 'python' is required by 2 of 4 members -> fraction 0.5.
    rec_half, _ = _cluster_of_four(rules)
    assert rec_half.core_skill_count == 1  # python survives at the shipped 0.5

    agg = _Agg()
    stricter = _with(rules, core_skill_min_fraction=0.6)
    m1 = _member(qualifications=[SFUQualification(text="python", kind="skill")])
    m2 = _member(qualifications=[SFUQualification(text="python", kind="skill")])
    m3 = _member(qualifications=[SFUQualification(text="tableau", kind="skill")])
    m4 = _member(qualifications=[SFUQualification(text="excel", kind="skill")])
    rec_strict = measure_cluster(_NS, [m1, m2, m3, m4], 0, agg, rules=stricter)
    assert rec_strict.core_skill_count == 0  # 0.5 < 0.6 -> python drops out


def test_duties_over_cap_folds_the_max_duties_sweep(rules: Rules) -> None:
    _rec, agg = _cluster_of_four(rules)
    # Six deduped duties: over the cap of 5, not over 8/10/12.
    assert agg.duties_over_cap["5"] == 1
    assert "8" not in agg.duties_over_cap
    assert agg.deduped_count_hist[6] == 1


def test_threshold_sweep_is_folded_across_candidates(rules: Rules) -> None:
    _rec, agg = _cluster_of_four(rules)
    # All six duties are distinct, so every threshold yields 6.
    assert agg.total_deduped_by_threshold["0.7"] == 6
    assert agg.total_deduped_by_threshold["0.9"] == 6


def test_additional_context_presence_is_measured(rules: Rules) -> None:
    rec, agg = _cluster_of_four(rules)
    assert rec.members_with_context == 1
    assert agg.members_with_context == 1


def test_single_member_cluster_is_recorded_but_not_in_distributions(
    rules: Rules,
) -> None:
    agg = _Agg()
    rec = measure_cluster(_NS, [_member()], 0, agg, rules=rules)
    assert rec.jdfn_member_count == 1
    assert "single_member" in rec.flags
    # A single-member cluster must not swamp the multi-member distributions.
    assert agg.deduped_count_hist == {}
    assert agg.distinct_title_hist == {}
    # ...but its flag still counts.
    assert agg.flag_counts["single_member"] == 1


def test_measurement_is_member_order_invariant(rules: Rules) -> None:
    members = [
        _member(title="Budget Analyst"),
        _member(title="Senior Budget Analyst", additional_context="year-end close"),
        _member(title="Budget Officer"),
    ]
    agg_a = _Agg()
    rec_a = measure_cluster(_NS, members, 0, agg_a, rules=rules)
    shuffled = list(members)
    random.Random(7).shuffle(shuffled)
    agg_b = _Agg()
    rec_b = measure_cluster(_NS, shuffled, 0, agg_b, rules=rules)
    assert rec_a.model_dump() == rec_b.model_dump()
    assert agg_a == agg_b


def test_boilerplate_mix_is_measured(rules: Rules) -> None:
    agg = _Agg()
    members = [
        _member(territorial_acknowledgement_present=True),
        _member(territorial_acknowledgement_present=False),
    ]
    measure_cluster(_NS, members, 0, agg, rules=rules)
    assert agg.boilerplate["territorial"]["mixed"] == 1
    assert agg.boilerplate["about_sfu"]["all_false"] == 1


# --- the stamp ----------------------------------------------------------------------


def test_harmonize_stamp_moves_when_a_knob_moves(rules: Rules) -> None:
    base = harmonize_stamp(rules.harmonization)
    moved = harmonize_stamp(_with(rules, max_duties=7).harmonization)
    assert base != moved
    # ...and is stable for the same knobs.
    assert base == harmonize_stamp(rules.harmonization)

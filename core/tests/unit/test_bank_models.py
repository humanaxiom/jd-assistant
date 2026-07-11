"""Unit tests for the JD Bank value objects (ported from hris ``jd_bank.py``).

**The trim, pinned.** hris's schemas carry persistence/lifecycle fields that
duplicate JD Bank's own SQLAlchemy tables (``jd_bank/db/models.py``), and API
envelopes for a service layer this repo has not written. The port drops them, and
these tests fail if anyone silently re-adds one — every model is
``extra="forbid"``, so a re-added field is a construction error, not a smell.

Nothing from hris's ``tests/unit/test_jd_bank_governance.py`` transfers. Half of
it asserts ``api.services.jd_bank_service._APPROVE_TARGET`` (a REWRITE-tier
module that does not exist here); the other half exercises
``CanonicalMemberRequest``, which is an API request body hris only ever builds in
``apps/api`` — dropped under the same rule as every other envelope. Keeping it
would also have smuggled in an unregistered policy default
(``link_type="confirmed"``) for a membership table JD Bank does not have.
"""

from __future__ import annotations

from typing import get_args
from uuid import uuid4

import pytest
from pydantic import ValidationError

from src.jd_core.models.bank import (
    HAY_SIGNALS_VERSION,
    CanonicalRole,
    HayFactor,
    HayFactorSignal,
    HaySignalLevel,
    HaySignals,
    JDCloneVerdict,
    JDSimilarNeighbour,
    JobDriftReport,
    SkillFrequency,
    TitleClassification,
    TitleFamily,
    TitleFamilyResult,
    TitleFunction,
    TitleFunctionResult,
)
from src.jd_core.models.parsed_jd import SFUJobDescription
from src.jd_core.rules import get_rules

# ---------- similarity neighbours ----------


def test_similar_neighbour_round_trip() -> None:
    n = JDSimilarNeighbour(
        job_id=uuid4(),
        title="Applications Developer",
        department="ITS",
        score=0.91,
        vector_score=0.88,
        skill_overlap=0.95,
        same_department=True,
        same_title=False,
        clone_verdict="clone",
        verdict_basis=["identical duties"],
    )
    assert JDSimilarNeighbour.model_validate(n.model_dump()) == n
    assert n.verdict_basis == ["identical duties"]


@pytest.mark.parametrize("field", ["score", "vector_score", "skill_overlap"])
def test_similar_neighbour_scores_are_bounded_0_1(field: str) -> None:
    kwargs: dict[str, object] = {
        "job_id": uuid4(),
        "title": "Coordinator",
        "score": 0.5,
        "vector_score": 0.5,
        "skill_overlap": 0.5,
        "same_department": False,
        "same_title": False,
        "clone_verdict": "uncertain",
    }
    with pytest.raises(ValidationError):
        JDSimilarNeighbour(**{**kwargs, field: 1.5})  # type: ignore[arg-type]


def test_clone_verdict_vocabulary() -> None:
    assert set(get_args(JDCloneVerdict)) == {"clone", "new_job", "uncertain"}


# ---------- harmonization provenance + canonical role ----------


def test_skill_frequency_needs_at_least_one_member() -> None:
    assert SkillFrequency(name="python", members=1).members == 1
    with pytest.raises(ValidationError):
        SkillFrequency(name="python", members=0)


def test_canonical_role_is_a_proposal_not_a_db_row() -> None:
    role = CanonicalRole(
        title="Applications Developer",
        jd=SFUJobDescription(title="Applications Developer"),
        skill_frequency=[SkillFrequency(name="python", members=3)],
        member_job_ids=[uuid4(), uuid4()],
        grade="B",
        overall_score=82.5,
        issue_count=2,
    )
    assert role.jd.title == "Applications Developer"
    assert CanonicalRole.model_validate(role.model_dump()) == role


@pytest.mark.parametrize(
    "trimmed",
    [
        "id",  # canonical_jds.id
        "cluster_id",  # canonical_jds.cluster_id
        "status",  # canonical_jds.status (CanonicalStatus)
        "approved_by",  # review_actions.reviewer_id
        "approved_at",  # review_actions.created_at
        "model",  # canonical_jds.change_log
        "prompt_version",  # canonical_jds.change_log
        "rules_version",  # validation_reports.rules_version
        "sim_version",  # dedup_edges.method / clusters.constraint_metadata
        "generated_at",  # canonical_jds.created_at
    ],
)
def test_canonical_role_drops_the_persistence_fields(trimmed: str) -> None:
    """Each of these lives in ``jd_bank/db/models.py``; a value object that also
    carried it would be a second, drifting source of truth."""
    with pytest.raises(ValidationError):
        CanonicalRole(
            title="Applications Developer",
            jd=SFUJobDescription(title="Applications Developer"),
            grade="B",
            overall_score=82.5,
            issue_count=2,
            **{trimmed: "whatever"},  # type: ignore[arg-type]
        )


def test_canonical_role_score_is_bounded_0_100() -> None:
    with pytest.raises(ValidationError):
        CanonicalRole(
            title="X",
            jd=SFUJobDescription(title="X"),
            grade="A",
            overall_score=100.5,
            issue_count=0,
        )


# ---------- Hay signals (advisory — NEVER a grade) ----------


def _signal(factor: HayFactor, level: HaySignalLevel = "moderate") -> HayFactorSignal:
    return HayFactorSignal(
        factor=factor, level=level, rationale="because", evidence=["a phrase"]
    )


def test_hay_signals_round_trip_and_version_stamp() -> None:
    sig = HaySignals(
        know_how=_signal("know_how", "high"),
        problem_solving=_signal("problem_solving"),
        accountability=_signal("accountability", "low"),
    )
    assert sig.version == HAY_SIGNALS_VERSION == "hay_signals_v1"
    assert sig.know_how.level == "high"
    assert HaySignals.model_validate(sig.model_dump()) == sig


def test_hay_factor_and_level_vocabularies() -> None:
    assert set(get_args(HayFactor)) == {
        "know_how",
        "problem_solving",
        "accountability",
    }
    assert set(get_args(HaySignalLevel)) == {"low", "moderate", "high"}


@pytest.mark.parametrize("graded", ["grade", "grade_mapped"])
def test_hay_signals_cannot_carry_a_grade(graded: str) -> None:
    """Source-gated: SFU publishes no point charts, so nothing here may assign a
    Hay grade. ``HayGrade``/``HayGradeMapping`` are deliberately NOT ported —
    the signals are advisory and that is unrepresentable-by-construction."""
    with pytest.raises(ValidationError):
        HaySignals(
            know_how=_signal("know_how"),
            problem_solving=_signal("problem_solving"),
            accountability=_signal("accountability"),
            **{graded: "B80"},  # type: ignore[arg-type]
        )


def test_hay_factor_signal_evidence_is_capped() -> None:
    with pytest.raises(ValidationError):
        HayFactorSignal(
            factor="know_how",
            level="high",
            rationale="r",
            evidence=[f"phrase {i}" for i in range(13)],  # max_length=12
        )


# ---------- title classification (two SFU dimensions) ----------


def test_title_classification_carries_both_dimensions() -> None:
    tc = TitleClassification(
        family=TitleFamilyResult(
            family="manager",
            label="Manager / Supervisor",
            rationale="title contains 'manager'",
            matched_on="manager",
        ),
        function=TitleFunctionResult(
            function="analyst",
            label="Analyst — analysis & research",
            matched_on="analyst",
        ),
        comma_supervisory=True,
    )
    assert tc.family.family == "manager"
    assert tc.function.function == "analyst"
    assert TitleClassification.model_validate(tc.model_dump()) == tc


def test_title_classification_defaults_comma_supervisory_false() -> None:
    tc = TitleClassification(
        family=TitleFamilyResult(family="unmapped", label="Unmapped", rationale="—"),
        function=TitleFunctionResult(function="unmapped", label="Unmapped"),
    )
    assert tc.comma_supervisory is False
    assert tc.family.matched_on is None


def test_title_vocabularies_include_the_explicit_unmapped_state() -> None:
    assert "unmapped" in get_args(TitleFamily)
    assert "unmapped" in get_args(TitleFunction)


def test_the_seniority_ladder_is_rule_data_not_a_hardcoded_literal() -> None:
    """The ladder is a policy call (HR-059), NOT SFU's published rulebook — so the
    rungs live in ``rules/titles.yaml`` and this Literal only mirrors them. If the
    two ever disagree, the type is silently narrower or wider than the registered
    default and the register is a lie. (hris hardcoded it and mis-cited it to the
    SFU Toolkit; that is exactly how HR-029 happened.)"""
    ladder = tuple(get_rules().titles.families)
    assert get_args(TitleFamily) == (*ladder, "unmapped")


def test_the_application_table_is_rule_data_not_a_hardcoded_literal() -> None:
    """Same contract for the *functional* dimension. This table IS SFU's (rulebook
    Part 3.3) — which changes its provenance (HR-063), not its status as data: the
    classifier that reads it must read a versioned table, never a Python tuple. The
    Literal is the type mirror, and the two are pinned together here.

    ``Titles`` types the YAML field as ``tuple[TitleFunction, ...]``, so a row added
    to the YAML that the Literal does not know about is a *load* error. This test
    covers the other direction: a Literal widened without the YAML."""
    table = tuple(get_rules().titles.functions)
    assert get_args(TitleFunction) == (*table, "unmapped")


# ---------- drift (advisory) ----------


def test_drift_report_round_trip() -> None:
    report = JobDriftReport(
        job_id=uuid4(),
        canonical_role_id=uuid4(),
        canonical_title="Applications Developer",
        level="major",
        drift_score=0.62,
        added=["rust"],
        dropped=["cobol"],
        reasons=["education level changed"],
        shared_count=4,
    )
    assert JobDriftReport.model_validate(report.model_dump()) == report


def test_drift_score_is_bounded_0_1() -> None:
    with pytest.raises(ValidationError):
        JobDriftReport(
            job_id=uuid4(),
            canonical_role_id=uuid4(),
            canonical_title="X",
            level="minor",
            drift_score=1.2,
            shared_count=0,
        )

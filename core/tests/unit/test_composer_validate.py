"""Phase 5.1 — the JD Builder's live-compliance core (``assess_draft``).

The draft-mode contract, pinned three ways (mirrors the task doc's acceptance):

1. an EMPTY draft's missing sections are *guidance* ("what's left"), not failures,
   and it is honestly not approvable — draft mode never fakes approval (NN #3);
2. a section the author HAS filled in but filled in badly (a too-short summary) is
   a *finding* to fix, in ``needs_attention``, not guidance;
3. a fully-authored clean JD has no guidance and its authored sections read ``ok``.

The validator itself is the oracle — these assert the split over its real output,
never a re-derived score. The clean-JD fixture is the same one the 2.2/2.3 gate
suite uses (``test_jd_gates._clean_jd``), so "clean" means the shipped rulebook.
"""

from __future__ import annotations

from src.jd_bank.composer import assess_draft
from src.jd_core.models.parsed_jd import (
    SFUDuty,
    SFUJobDescription,
    SFUQualification,
    SFURelationships,
)


def _summary(words: int) -> str:
    return " ".join(["word"] * words)


def _clean_jd() -> SFUJobDescription:
    """A fully-authored JD the shipped rulebook is content with (the gate suite's
    clean baseline). Its qualifications carry the equivalency path and KSA order,
    so rendering it to text and re-validating keeps it clean end to end."""
    return SFUJobDescription(
        title="Software Developer",
        about_sfu_present=True,
        position_summary=_summary(120),
        duties=[
            SFUDuty(action_verb="Manages", statement="Manages the program"),
            SFUDuty(action_verb="Coordinates", statement="Coordinates the program"),
            SFUDuty(action_verb="Provides", statement="Provides the program"),
        ],
        decision_making=["Approves expenditures up to $5k"],
        problem_solving=["Resolves scheduling conflicts independently"],
        relationships=SFURelationships(
            supervisory="Supervises 2 staff",
            internal=["Finance"],
            external=["Vendors"],
        ),
        qualifications=[
            SFUQualification(
                text="Bachelor's degree or an equivalent combination of experience",
                kind="education",
            ),
            SFUQualification(
                text="Excellent knowledge of databases",
                kind="knowledge",
                modifier="excellent",
            ),
            SFUQualification(text="Python", kind="skill", modifier="advanced"),
            SFUQualification(text="Ability to work cooperatively", kind="ability"),
        ],
        territorial_acknowledgement_present=True,
        employment_equity_present=True,
    )


def _section(assessment, name):  # type: ignore[no-untyped-def]
    hits = [s for s in assessment.sections if s.section == name]
    assert hits, f"section {name!r} not in {[s.section for s in assessment.sections]}"
    return hits[0]


# --- 1. an empty draft is guidance, not failure ---------------------------------------


def test_empty_draft_is_guidance_and_not_approvable() -> None:
    assessment = assess_draft(SFUJobDescription(title="Some New Role"))

    # The gate decision is honest: an unfinished draft cannot be approved.
    assert assessment.approvable is False
    assert assessment.report.gate_decision is not None
    assert assessment.report.gate_decision.approved is False

    # Un-started sections read "empty" and their findings are GUIDANCE, never
    # counted among the present-but-wrong findings.
    summary = _section(assessment, "position_summary")
    assert summary.state == "empty"
    assert summary.issues, "an empty summary should raise at least a completeness item"
    guidance_ids = {id(i) for i in assessment.guidance}
    findings_ids = {id(i) for i in assessment.findings}
    for issue in summary.issues:
        assert id(issue) in guidance_ids
        assert id(issue) not in findings_ids

    assert assessment.guidance, "an empty draft is all guidance"
    assert assessment.summary_word_count == 0
    assert assessment.duty_count == 0


# --- 2. a present-but-bad section is a finding to fix ---------------------------------


def test_authored_but_weak_summary_is_a_finding_not_guidance() -> None:
    # A 40-word summary is authored but below the template's 100-word floor.
    jd = _clean_jd().model_copy(update={"position_summary": _summary(40)})
    assessment = assess_draft(jd)

    summary = _section(assessment, "position_summary")
    assert summary.state == "needs_attention"
    assert assessment.summary_word_count == 40

    finding_rule_ids = {i.rule_id for i in assessment.findings}
    assert "SFU-STRUCT-SUMMARY-TOO-SHORT" in finding_rule_ids
    # The too-short finding is a fix-this, not "still to write".
    guidance_rule_ids = {i.rule_id for i in assessment.guidance}
    assert "SFU-STRUCT-SUMMARY-TOO-SHORT" not in guidance_rule_ids


# --- 3. a clean, fully-authored JD has no guidance and reads ok -----------------------


def test_clean_jd_has_no_guidance_and_authored_sections_are_ok() -> None:
    assessment = assess_draft(_clean_jd())

    # Every section is authored, so nothing is "still to write".
    assert assessment.guidance == []
    assert all(s.state != "empty" for s in assessment.sections)
    assert _section(assessment, "position_summary").state == "ok"
    assert assessment.summary_word_count == 120
    assert assessment.duty_count == 3


def test_the_split_is_stable_across_calls() -> None:
    """Pure over the draft (the only non-determinism is the report's clock stamp,
    which the split does not read): the section states and the guidance/findings
    partition are identical run to run."""
    jd = _clean_jd().model_copy(update={"position_summary": _summary(40)})
    first, second = assess_draft(jd), assess_draft(jd)
    assert first.sections == second.sections
    assert first.guidance == second.guidance
    assert first.findings == second.findings
    assert first.approvable == second.approvable

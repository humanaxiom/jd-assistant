"""Phase 5.2 — assembling guided-authoring answers into an SFU JD draft.

The load-bearing test is the end-to-end one: a fully-filled answer set assembles
into a JD the live-compliance core (5.1) reports *approvable* — i.e. the guided
flow can actually produce a compliant JDFN JD. The rest pin the two Toolkit rules
the assembler enforces structurally (KSA order, percentage allocations) and that a
sparse draft assembles without crashing.
"""

from __future__ import annotations

from src.jd_bank.composer import (
    ComposerAnswers,
    DutyAnswer,
    ModifiedQual,
    assemble_jd,
    assess_draft,
)


def _full_answers() -> ComposerAnswers:
    return ComposerAnswers(
        title="Software Developer",
        department="Information Services",
        employee_group="apsa",
        position_summary=" ".join(["word"] * 120),
        duties=[
            DutyAnswer(
                action_verb="Manages", statement="Manages the program", allocation=50
            ),
            DutyAnswer(
                action_verb="Coordinates",
                statement="Coordinates delivery",
                allocation=30,
            ),
            DutyAnswer(
                action_verb="Provides",
                statement="Provides technical advice",
                allocation=20,
            ),
        ],
        decision_making=["Approves expenditures up to $5k"],
        problem_solving=["Resolves scheduling conflicts independently"],
        supervisory="Supervises 2 staff",
        internal=["Finance"],
        external=["Vendors"],
        education=["Bachelor's degree or an equivalent combination of experience"],
        knowledge=[
            ModifiedQual(text="Excellent knowledge of databases", modifier="excellent")
        ],
        skills=[ModifiedQual(text="Python", modifier="advanced")],
        abilities=["Ability to work cooperatively"],
        include_sfu_boilerplate=True,
    )


def test_a_full_answer_set_assembles_into_an_approvable_jd() -> None:
    jd = assemble_jd(_full_answers())
    assessment = assess_draft(jd)
    assert assessment.approvable is True, [
        r.gate_id for r in (assessment.report.gate_decision.blocking or ())
    ]
    assert assessment.guidance == []


def test_qualifications_are_emitted_in_ksa_order() -> None:
    # Answers arrive by field, but the assembler fixes the Toolkit order:
    # Education -> Experience -> Knowledge -> Skills -> Abilities.
    answers = ComposerAnswers(
        title="Role",
        abilities=["Ability to lead"],
        skills=[ModifiedQual(text="SQL", modifier="advanced")],
        knowledge=[ModifiedQual(text="Databases", modifier="working")],
        experience=["Three years related experience"],
        education=["Diploma"],
    )
    kinds = [q.kind for q in assemble_jd(answers).qualifications]
    assert kinds == ["education", "experience", "knowledge", "skill", "ability"]


def test_a_duty_allocation_renders_as_a_percentage() -> None:
    jd = assemble_jd(
        ComposerAnswers(
            title="Role",
            duties=[
                DutyAnswer(
                    action_verb="Leads", statement="Leads the team", allocation=60
                )
            ],
        )
    )
    assert jd.duties[0].statement == "Leads the team (60%)"


def test_a_sparse_draft_assembles_without_crashing() -> None:
    jd = assemble_jd(ComposerAnswers())
    # Falls back to a placeholder title (SFUJobDescription requires one) and leaves
    # every optional section empty; the live panel then shows what is still to write.
    assert jd.title == "Untitled role"
    assert jd.duties == []
    assert jd.qualifications == []
    # No boilerplate booleans unless asked — default answers keep it on, so flip it.
    bare = assemble_jd(ComposerAnswers(include_sfu_boilerplate=False))
    assert bare.territorial_acknowledgement_present is False
    assert assess_draft(bare).approvable is False


def test_boilerplate_flag_sets_the_mandated_presence_booleans() -> None:
    jd = assemble_jd(ComposerAnswers(title="Role", include_sfu_boilerplate=True))
    assert jd.about_sfu_present is True
    assert jd.territorial_acknowledgement_present is True
    assert jd.employment_equity_present is True

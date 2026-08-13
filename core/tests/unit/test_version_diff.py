"""Unit — the pure JD-to-JD version diff (draft vs last-approved).

Pins: identical JDs report no change; a change in any section (incl. the presence
booleans and per-duty how_why/frequency that ``render_sfu_jd_text`` drops) is caught
and localized to that section; and the diff judges nothing (no approval/score field).
"""

from __future__ import annotations

from src.jd_core.bank.version_diff import build_version_diff
from src.jd_core.models.parsed_jd import (
    SFUDuty,
    SFUJobDescription,
    SFUQualification,
    SFURelationships,
)


def _jd(**update: object) -> SFUJobDescription:
    jd = SFUJobDescription(
        title="Software Developer",
        department="Information Services",
        grade="J",
        employee_group="apsa",
        position_number="AP-1234",
        about_sfu_present=True,
        position_summary="Builds and maintains university systems.",
        duties=[
            SFUDuty(
                action_verb="Develops",
                statement="Develops applications",
                how_why=["to modernize services"],
            )
        ],
        decision_making=["Chooses the tech stack"],
        problem_solving=["Diagnoses incidents"],
        relationships=SFURelationships(
            supervisory="Reports to the Director.",
            internal=["Faculty IT"],
            external=["Vendors"],
        ),
        qualifications=[
            SFUQualification(text="Python", kind="skill", modifier="advanced")
        ],
        territorial_acknowledgement_present=True,
        employment_equity_present=True,
        additional_context="Occasional evening work.",
    )
    return jd.model_copy(update=update)


def _changed(diff: object) -> set[str]:
    return {s.section for s in diff.sections if s.changed}  # type: ignore[attr-defined]


def test_identical_jds_report_no_change() -> None:
    diff = build_version_diff(_jd(), _jd())
    assert diff.any_changes is False
    assert _changed(diff) == set()
    # Every section is still reported (so the UI can show "unchanged"), not flagged.
    assert len(diff.sections) == 10


def test_a_title_change_is_localized_to_the_title_section() -> None:
    diff = build_version_diff(_jd(), _jd(title="Senior Software Developer"))
    assert diff.any_changes is True
    assert _changed(diff) == {"Title"}
    title = next(s for s in diff.sections if s.section == "Title")
    assert title.before == "Software Developer"
    assert title.after == "Senior Software Developer"


def test_boolean_footer_flip_is_caught_though_render_would_drop_it() -> None:
    """A presence boolean toggled off is an approval-relevant change render_sfu_jd_text
    cannot show; the version diff catches it in the boilerplate section."""
    diff = build_version_diff(_jd(), _jd(territorial_acknowledgement_present=False))
    assert _changed(diff) == {"SFU boilerplate"}


def test_per_duty_how_why_change_is_caught() -> None:
    other = _jd(
        duties=[
            SFUDuty(
                action_verb="Develops",
                statement="Develops applications",
                how_why=["to modernize services", "under the CTO"],
            )
        ]
    )
    diff = build_version_diff(_jd(), other)
    assert _changed(diff) == {"Duties & Responsibilities"}


def test_clearing_an_optional_scalar_is_a_change() -> None:
    diff = build_version_diff(_jd(), _jd(grade=None, position_number=None))
    assert _changed(diff) == {"Identification"}


def test_multiple_section_changes_are_all_reported() -> None:
    diff = build_version_diff(
        _jd(),
        _jd(
            position_summary="A shorter summary.",
            decision_making=["Chooses the tech stack", "Sets the roadmap"],
        ),
    )
    assert _changed(diff) == {"Position Summary", "Impact of Decision Making"}


def test_a_changed_section_carries_a_word_level_inline_diff() -> None:
    """Phase 8.3a: the reviewer reads WHICH WORDS changed, not two walls of text."""
    diff = build_version_diff(_jd(), _jd(title="Senior Software Developer"))
    title = next(s for s in diff.sections if s.section == "Title")

    assert title.inline is not None
    inserted = "".join(s.text for s in title.inline.after if s.kind == "insert")
    assert inserted.strip() == "Senior"
    # Lossless on both sides — the page shows the stored text, never a reconstruction.
    assert "".join(s.text for s in title.inline.before) == title.before
    assert "".join(s.text for s in title.inline.after) == title.after


def test_an_unchanged_section_carries_no_inline_diff() -> None:
    """Computed only where there is something to show, so the collapsed
    "unchanged sections" list costs nothing."""
    diff = build_version_diff(_jd(), _jd(title="Senior Software Developer"))
    for section in diff.sections:
        if section.section != "Title":
            assert section.inline is None

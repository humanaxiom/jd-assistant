"""The minimal prompt loader (Phase 4.2a): versioned templates, ``{{ var }}`` rendering,
and the rule that a missing OR unknown variable RAISES rather than shipping a broken
prompt."""

from __future__ import annotations

import pytest

from src.jd_bank.llm.prompts import PromptError, RenderedPrompt, load_prompt
from src.jd_core.rules import get_rules


def _render() -> RenderedPrompt:
    return load_prompt(
        "jd_harmonize_v1",
        member_count=3,
        skill_frequency="- accounting: 3",
        member_jds="A grounded merge draft.",
    )


def test_the_harmonize_template_renders_system_and_user_messages() -> None:
    prompt = _render()

    roles = [message["role"] for message in prompt.messages]
    assert roles == ["system", "user"]
    system, user = prompt.messages
    # every provided variable was substituted; no placeholder survives
    assert "{{" not in system["content"]
    assert "{{" not in user["content"]
    # the values actually landed in the user prompt
    assert "3 job descriptions" in user["content"]
    assert "- accounting: 3" in user["content"]
    assert "A grounded merge draft." in user["content"]


def test_the_version_is_the_template_name_and_is_stable() -> None:
    """`RenderedPrompt.version` is the template name (its `_vN` suffix IS the version) —
    stamped onto `RewrittenDraft.prompt_version`, so a draft traces to exact wording."""
    assert _render().version == "jd_harmonize_v1"
    assert (
        load_prompt(
            "jd_harmonize_v1",
            member_count=1,
            skill_frequency="(none extracted)",
            member_jds="x",
        ).version
        == "jd_harmonize_v1"
    )


def test_a_missing_template_variable_raises_rather_than_leaving_a_placeholder() -> None:
    """The user template references `{{ member_jds }}`; omit it and the loader must
    RAISE, never ship a prompt with a literal `{{ member_jds }}` still in it."""
    with pytest.raises(PromptError, match="member_jds"):
        load_prompt(
            "jd_harmonize_v1",
            member_count=3,
            skill_frequency="- accounting: 3",
            # member_jds deliberately omitted
        )


def test_an_unknown_template_variable_raises() -> None:
    """A misspelled/stray variable is a caller bug, not a silent no-op."""
    with pytest.raises(PromptError, match="typo_variable"):
        load_prompt(
            "jd_harmonize_v1",
            member_count=3,
            skill_frequency="- accounting: 3",
            member_jds="x",
            typo_variable="oops",
        )


def test_an_unknown_template_name_raises() -> None:
    with pytest.raises(PromptError):
        load_prompt("no_such_prompt_v9", member_count=1)


# --- v2: the numbers are the DRAFTED FORM's, not JDFN's (CUPE Phase D) ---------------


def _render_v2(**overrides: object) -> RenderedPrompt:
    values: dict[str, object] = {
        "member_count": 3,
        "skill_frequency": "- accounting: 3",
        "member_jds": "A grounded merge draft.",
        "duties_min": 3,
        "duties_max": 5,
        "summary_min_words": 100,
        "summary_max_words": 150,
    }
    values.update(overrides)
    return load_prompt("jd_harmonize_v2", **values)


def test_v2_states_the_duty_count_and_summary_band_it_is_given() -> None:
    """🔴 THE DEFECT v2 EXISTS FOR. v1 inlined SFU's JDFN guidance as prompt TEXT —
    "Write 3–5 major duties", "Position Summary: 100–150 words". Those are rulebook
    numbers (HR-020…HR-022) hardcoded in a prompt, harmless only while JDFN was the one
    form the producer drafted. On a CUPE draft it DELETES CONTENT: the WJQ form
    has twelve duty slots, 77.4% of CUPE JDs fill all twelve, and a rewrite asked for
    three-to-five duties drops most of the role. The anti-fabrication guard cannot catch
    that — it exists to stop the model ADDING — and the WJQ profile's `duties_min` of 3
    means the mutilated draft passes its own bar.

    Asserted over BOTH profiles, because a test written only against the JDFN numbers
    would have passed against the hardcoded v1 text as well.
    """
    jdfn = _render_v2().messages[0]["content"]
    assert "3–5 major duties" in jdfn
    assert "100–150 words" in jdfn

    wjq = _render_v2(duties_min=3, duties_max=12).messages[0]["content"]
    assert "3–12 major duties" in wjq
    assert "3–5 major duties" not in wjq


def test_v2_is_the_shipped_prompt() -> None:
    """The rulebook points at v2 (HR-180). v1 stays on disk unedited — every draft in
    the archive carries its stamp, and a stamp that cannot be read back is not
    provenance — but nothing should be *loading* it."""
    assert get_rules().rewrite.prompt_version == "jd_harmonize_v2"


def test_v2_still_raises_on_a_missing_number_rather_than_guessing_one() -> None:
    """A prompt that shipped `{{ duties_max }}` verbatim, or quietly defaulted it to the
    JDFN value, would reintroduce exactly the bug v2 was made to fix."""
    with pytest.raises(PromptError, match="duties_max"):
        load_prompt(
            "jd_harmonize_v2",
            member_count=3,
            skill_frequency="- accounting: 3",
            member_jds="x",
            duties_min=3,
            summary_min_words=100,
            summary_max_words=150,
        )

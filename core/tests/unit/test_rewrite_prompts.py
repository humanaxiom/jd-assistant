"""The minimal prompt loader (Phase 4.2a): versioned templates, ``{{ var }}`` rendering,
and the rule that a missing OR unknown variable RAISES rather than shipping a broken
prompt."""

from __future__ import annotations

import pytest

from src.jd_bank.llm.prompts import PromptError, RenderedPrompt, load_prompt


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

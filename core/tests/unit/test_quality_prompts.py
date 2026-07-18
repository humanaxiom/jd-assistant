"""The quality-audit prompt templates (Phase 4.2b): ``jd_quality_v1`` renders its
single ``{{ jd_text }}`` slot, stamps its version, and a missing variable RAISES
(existing loader behaviour — reused, not re-implemented)."""

from __future__ import annotations

import pytest

from src.jd_bank.llm.prompts import PromptError, RenderedPrompt, load_prompt

_JD_TEXT = "A flattened SFU job description with an aggressive go-getter phrase."


def _render() -> RenderedPrompt:
    return load_prompt("jd_quality_v1", jd_text=_JD_TEXT)


def test_the_quality_template_renders_system_and_user_messages() -> None:
    prompt = _render()

    roles = [message["role"] for message in prompt.messages]
    assert roles == ["system", "user"]
    system, user = prompt.messages
    assert "{{" not in system["content"]
    assert "{{" not in user["content"]
    # the flattened JD actually landed in the user prompt (the auditor's haystack)
    assert _JD_TEXT in user["content"]


def test_the_version_is_the_template_name_and_is_stamped() -> None:
    """`RenderedPrompt.version` is the template name (its `_vN` suffix IS the version) —
    stamped onto `QualityAudit.prompt_version`, so an audit traces to exact wording."""
    assert _render().version == "jd_quality_v1"


def test_a_missing_jd_text_variable_raises() -> None:
    """The user template references `{{ jd_text }}`; omit it and the loader must RAISE,
    never ship a prompt with a literal `{{ jd_text }}` still in it."""
    with pytest.raises(PromptError, match="jd_text"):
        load_prompt("jd_quality_v1")

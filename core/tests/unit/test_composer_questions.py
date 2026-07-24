"""Phase 5.2 — the guided-authoring question set loads and stays coupled to the
answer contract.

The load-time guards (every ``target`` is a real ``ComposerAnswers`` field, ids
unique) are the point: a question that collects input nothing assembles, or a
duplicate id, must fail loudly rather than silently drop a hiring manager's answer.
"""

from __future__ import annotations

import pytest

from src.jd_bank.composer import (
    ComposerAnswers,
    QuestionSet,
    QuestionSetError,
    load_question_set,
)
from src.jd_bank.composer.questions import Question


def test_question_set_loads_and_is_versioned() -> None:
    qset = load_question_set()
    assert qset.version == "composer_questions_v1"
    assert qset.questions, "the shipped set must not be empty"


def test_every_target_is_a_real_answer_field() -> None:
    fields = set(ComposerAnswers.model_fields)
    for q in load_question_set().questions:
        assert q.target in fields, f"{q.id} targets unknown field {q.target!r}"


def test_the_set_walks_the_core_authored_sections() -> None:
    sections = {q.section for q in load_question_set().questions}
    # The sections a hiring manager actually authors on the JDFN template.
    assert {
        "identification",
        "position_summary",
        "duties",
        "qualifications",
        "relationships",
    } <= sections


def test_a_target_that_is_not_an_answer_field_is_rejected() -> None:
    with pytest.raises(ValueError, match="not a ComposerAnswers field"):
        Question(id="q", section="duties", prompt="p", target="not_a_field")


def test_duplicate_ids_are_rejected() -> None:
    q = Question(id="dup", section="duties", prompt="p", target="duties")
    with pytest.raises(ValueError, match="duplicate question id"):
        QuestionSet(version="v", questions=(q, q))


def test_load_question_set_is_cached() -> None:
    assert load_question_set() is load_question_set()


def test_question_set_error_is_exported() -> None:
    # It is the module's public failure type (mirrors PromptError).
    assert issubclass(QuestionSetError, RuntimeError)

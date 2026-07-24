"""Loader for the guided-authoring question set (Phase 5.2).

Reads the versioned ``composer_questions_v1.yaml`` (jd_bank-LOCAL authoring data,
not the scoring rulebook) into a typed, frozen :class:`QuestionSet`, mirroring the
LLM prompt loader (:mod:`src.jd_bank.llm.prompts`): versioned DATA loaded via
``importlib.resources`` so it is visible inside the ``gates`` container, which
mounts only ``./core``.

The set is UX content the Builder renders (Phase 5.3); each question's ``target``
names the :class:`~src.jd_bank.composer.answers.ComposerAnswers` field its answer
assembles into. The loader checks — at load, so a malformed set fails loudly
rather than silently — that every ``target`` is a real ``ComposerAnswers`` field
and that ids are unique, so a question can never collect input the assembler drops.
"""

from __future__ import annotations

import importlib.resources
from functools import lru_cache
from typing import Final

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.jd_bank.composer.answers import ComposerAnswers
from src.jd_core.models.quality import SFUSection

_PACKAGE: Final[str] = __package__ or "src.jd_bank.composer"
_QUESTION_SET_FILE: Final[str] = "composer_questions_v1.yaml"

#: The fields an answer may target — the ComposerAnswers contract, derived so a new
#: answer field is automatically a legal target and a removed one breaks the build.
_ANSWER_FIELDS: Final[frozenset[str]] = frozenset(ComposerAnswers.model_fields)


class QuestionSetError(RuntimeError):
    """The question set is missing, malformed, or names an unknown answer target."""


class Question(BaseModel):
    """One guided-authoring prompt: what to ask, the Toolkit hint to show, the SFU
    section it belongs to, and the ``ComposerAnswers`` field it fills."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    section: SFUSection
    prompt: str = Field(min_length=1)
    hint: str = ""
    target: str = Field(min_length=1)
    required: bool = False

    @model_validator(mode="after")
    def _target_is_a_real_answer_field(self) -> Question:
        if self.target not in _ANSWER_FIELDS:
            raise ValueError(
                f"question {self.id!r} targets {self.target!r}, which is not a "
                f"ComposerAnswers field ({sorted(_ANSWER_FIELDS)})"
            )
        return self


class QuestionSet(BaseModel):
    """The full guided-authoring flow, in ask order."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: str = Field(min_length=1)
    questions: tuple[Question, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _ids_are_unique(self) -> QuestionSet:
        ids = [q.id for q in self.questions]
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        if dupes:
            raise ValueError(f"duplicate question id(s): {dupes}")
        return self


@lru_cache
def load_question_set() -> QuestionSet:
    """Load + validate the shipped guided-authoring question set (cached)."""
    resource = importlib.resources.files(_PACKAGE).joinpath("data", _QUESTION_SET_FILE)
    try:
        raw = resource.read_text(encoding="utf-8")
    except OSError as exc:  # pragma: no cover - shipped file is always present
        raise QuestionSetError(
            f"cannot read question set {_QUESTION_SET_FILE!r}: {exc}"
        ) from exc
    try:
        data = yaml.safe_load(raw)
        return QuestionSet.model_validate(data)
    except Exception as exc:
        raise QuestionSetError(f"invalid question set: {exc}") from exc

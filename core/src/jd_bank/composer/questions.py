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

#: The question set the JDFN flow walks — the default, so every existing caller keeps
#: working unchanged now that a second form exists (Phase E).
DEFAULT_QUESTION_SET: Final[str] = "composer_questions_v1"


class QuestionSetError(RuntimeError):
    """The question set is missing, malformed, or names an unknown answer target."""


class Question(BaseModel):
    """One guided-authoring prompt: what to ask, the Toolkit hint to show, the SFU
    section it belongs to, and the answer field it fills."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    section: SFUSection
    #: The FORM's own name for the section this question sits in, for display — e.g.
    #: "5 · Level of Independence" on the WJQ. Presentation only, and separate from
    #: ``section`` on purpose (Phase E): ``section`` is the `SFUSection` the panel and
    #: the rulebook key on, and ten WJQ sections collapse onto `additional_context`
    #: there, which would otherwise show an author one undifferentiated bucket where
    #: their form has seven distinct questions. Empty -> the UI falls back to its own
    #: label for ``section``.
    group: str = ""
    prompt: str = Field(min_length=1)
    hint: str = ""
    target: str = Field(min_length=1)
    required: bool = False


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
def load_question_set(
    name: str = DEFAULT_QUESTION_SET,
    answers_model: type[BaseModel] = ComposerAnswers,
) -> QuestionSet:
    """Load + validate a guided-authoring question set (cached).

    ``answers_model`` is the contract every ``target`` must name a field of — passed in
    rather than hardcoded, because the WJQ flow (Phase E) fills a different one. The
    check stays HERE, at load, so a set that would collect input its assembler silently
    drops fails loudly on first use instead of quietly losing an author's answer.
    """
    filename = f"{name}.yaml"
    resource = importlib.resources.files(_PACKAGE).joinpath("data", filename)
    try:
        raw = resource.read_text(encoding="utf-8")
    except OSError as exc:
        raise QuestionSetError(f"cannot read question set {filename!r}: {exc}") from exc
    try:
        data = yaml.safe_load(raw)
        question_set = QuestionSet.model_validate(data)
    except Exception as exc:
        raise QuestionSetError(f"invalid question set: {exc}") from exc

    check_targets(question_set, answers_model, name=name)
    return question_set


def check_targets(
    question_set: QuestionSet, answers_model: type[BaseModel], *, name: str = "<set>"
) -> None:
    """Refuse a set whose questions fill fields ``answers_model`` does not have.

    Separate from :func:`load_question_set` so the rule can be tested without a file on
    disk, and so it reads as what it is: a target is only meaningful *against a
    particular answer contract*, and since Phase E there are two.
    """
    fields = frozenset(answers_model.model_fields)
    unknown = sorted(
        {q.target for q in question_set.questions if q.target not in fields}
    )
    if unknown:
        raise QuestionSetError(
            f"question set {name!r} targets {unknown}, which are not "
            f"{answers_model.__name__} fields ({sorted(fields)})"
        )

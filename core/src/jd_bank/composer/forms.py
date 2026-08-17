"""Which SFU FORM the Builder is authoring — the Phase E routing seam.

**The measurement this exists because of** (full evidence:
``docs/decisions/cupe-phase-e-routing-seam-2026-08-17.md``): about 84% of the composer
is already form-blind. ``duplicates.py``, ``persist.py``, ``assist.py``, ``drafts.py``,
``questions.py`` and ``models.py`` hold **zero** JDFN-shaped references — they speak
:class:`~src.jd_core.models.parsed_jd.SFUJobDescription`, and an
``SFUJobDescription`` is an ``SFUJobDescription`` whichever form produced it. The whole
divergence between the two forms is *what each one consists of*: an answer contract, an
assembler, a clone mapping, a question set, a section list, and some UI field
declarations.

**So the difference is DECLARATIONS, not BEHAVIOUR**, and that is what this module
encodes. A :class:`FormSpec` is the complete statement of one SFU form; ``FORMS`` is the
registry; and "which form am I authoring?" is answered **once**, where a draft starts.
Nothing downstream asks again.

That is the same shape the rules and the numbers already have — ``applies_to`` (Phase B)
says which rules can judge a form, ``thresholds_for`` (Phase C) says which numbers do,
and now :data:`FORMS` says what the form is made of. Three axes, one mechanism, keyed on
the same ``JDTemplate``.

⚠ **A form is registered by its template, and the template is not a free choice.**
``template_of`` derives it from the draft's own ``employee_group``, so a form spec whose
assembler emits a different group than the key it is registered under would produce
drafts judged by the *other* form's bar. :func:`FormSpec._assembles_its_own_template`
refuses that at construction rather than leaving it to be noticed in a score.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.jd_bank.composer.answers import ComposerAnswers
from src.jd_bank.composer.assemble import assemble_jd
from src.jd_bank.composer.wjq_answers import WJQAnswers
from src.jd_bank.composer.wjq_assemble import assemble_wjq_jd
from src.jd_core.models.parsed_jd import SFUJobDescription
from src.jd_core.models.quality import (
    DEFAULT_TEMPLATE,
    WJQ_TEMPLATE,
    JDTemplate,
    SFUSection,
)
from src.jd_core.quality.validators import template_of

__all__ = ["FORMS", "FormSpec", "form_for", "form_for_template"]


class FormSpec(BaseModel):
    """Everything that differs between one SFU form and another, in one place."""

    model_config = ConfigDict(extra="forbid", frozen=True, arbitrary_types_allowed=True)

    #: The template this form produces — the key `template_of` will derive from its
    #: drafts, and therefore the profile the validator will judge them by.
    template: JDTemplate
    #: What a person calls this form. Shown wherever the author picks or is told which
    #: form they are in.
    label: str = Field(min_length=1)
    #: One line on what the form IS, for the picker — an author choosing between two
    #: SFU instruments needs more than two acronyms.
    description: str = Field(min_length=1)
    #: The answer contract this form's guided flow collects into.
    answers_model: type[BaseModel]
    #: The versioned question-set file (``data/<name>.yaml``) that walks the author
    #: through it.
    question_set: str = Field(min_length=1)
    #: answers -> draft. The ONLY place a form's shape becomes a JD.
    assemble: Callable[..., SFUJobDescription]
    #: The sections this form HAS. The live authoring panel walks it, so a form is never
    #: told it is missing a section its instrument does not contain — the panel-level
    #: equivalent of `applies_to`, and the reason a CUPE author is not nagged for a
    #: Problem Solving section that 0.0% of CUPE JDs have.
    sections: tuple[SFUSection, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _assembles_its_own_template(self) -> FormSpec:
        """A form must produce drafts of the template it is registered under.

        Checked by ASSEMBLING an empty answer set and asking ``template_of`` what came
        out — the same question the validator will ask — rather than by trusting the
        assembler's docstring. A spec that failed this would hand its author a draft
        scored against the other form's rules and numbers, which is the exact category
        error Phases B, C and D removed; it should be impossible to register, not
        something to notice later in a grade.
        """
        produced = template_of(self.assemble(self.answers_model()))
        if produced != self.template:
            raise ValueError(
                f"form {self.template!r} assembles drafts of template {produced!r}; "
                "a form must produce the template it is registered under, or its "
                "drafts are judged by the other form's bar"
            )
        return self


#: The JDFN template's sections, in ask order — the sections the shipped Builder walks.
_JDFN_SECTIONS: tuple[SFUSection, ...] = (
    "identification",
    "position_summary",
    "duties",
    "decision_making",
    "problem_solving",
    "relationships",
    "qualifications",
    "edi_footer",
    "additional_context",
)

#: The WJQ's sections, expressed in `SFUSection` terms — the mapping the PARSER already
#: uses, not a new one. Ten of the WJQ's fourteen have no JDFN counterpart and land in
#: `additional_context` verbatim (``wjq.context_sections``), so the panel shows the four
#: that map plus that one. Notably ABSENT: `decision_making`, `problem_solving`,
#: `edi_footer` — sections the CUPE instrument does not have, and which the author must
#: therefore never be shown as unfinished work.
_WJQ_SECTIONS: tuple[SFUSection, ...] = (
    "identification",
    "position_summary",
    "duties",
    "relationships",
    "qualifications",
    "additional_context",
)

#: Every form the Builder can author, keyed by template.
FORMS: Mapping[JDTemplate, FormSpec] = {
    DEFAULT_TEMPLATE: FormSpec(
        template=DEFAULT_TEMPLATE,
        label="JDFN (APSA / APEX / POLY)",
        description=(
            "SFU's job-description form for APSA, APEX and Polyparty roles — the "
            "template the Toolkit, the validator and the approval gates were written "
            "against."
        ),
        answers_model=ComposerAnswers,
        question_set="composer_questions_v1",
        assemble=assemble_jd,
        sections=_JDFN_SECTIONS,
    ),
    WJQ_TEMPLATE: FormSpec(
        template=WJQ_TEMPLATE,
        label="CUPE (WJQ)",
        description=(
            "The CUPE 3338 Weighted Job Questionnaire — a 14-section point-factor "
            "instrument. A different form, not a variant: it has no Problem Solving or "
            "Impact of Decision Making section, and it carries none of SFU's "
            "boilerplate blocks."
        ),
        answers_model=WJQAnswers,
        question_set="composer_questions_wjq_v1",
        assemble=assemble_wjq_jd,
        sections=_WJQ_SECTIONS,
    ),
}


def form_for_template(template: JDTemplate) -> FormSpec:
    """The form spec for ``template``. Every ``JDTemplate`` has one — a test pins that,
    so adding a template without deciding how it is authored fails the build rather
    than 500-ing a route."""
    return FORMS[template]


def form_for(draft: SFUJobDescription) -> FormSpec:
    """The form spec a DRAFT belongs to, by the one separator the system uses. Lets a
    clone or a resumed draft find its own form without the caller having tracked it."""
    return form_for_template(template_of(draft))


def form_from_request(value: Any) -> FormSpec:
    """The form named by an untrusted request value, falling back to the JDFN default.

    A **normalized string, deliberately not a ``Literal`` path param** — the 8.3a
    lesson: a ``Literal`` answers an unknown value with a raw 422 JSON blob on a page a
    person is using, which is exactly the P0.0 defect class. An unrecognised form name
    starts the JDFN flow, which is a page rather than an error.
    """
    name = str(value or "").strip().lower()
    for spec in FORMS.values():
        if spec.template == name:
            return spec
    return FORMS[DEFAULT_TEMPLATE]

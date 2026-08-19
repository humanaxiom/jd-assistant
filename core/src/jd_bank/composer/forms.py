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

from src.jd_bank.composer.answers import AnswerContract, ComposerAnswers
from src.jd_bank.composer.assemble import assemble_jd, jd_to_answers
from src.jd_bank.composer.wjq_answers import WJQAnswers
from src.jd_bank.composer.wjq_assemble import assemble_wjq_jd, wjq_answers_from_jd
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
    answers_model: type[AnswerContract]
    #: The versioned question-set file (``data/<name>.yaml``) that walks the author
    #: through it.
    question_set: str = Field(min_length=1)
    #: answers -> draft. The ONLY place a form's shape becomes a JD.
    assemble: Callable[..., SFUJobDescription]
    #: draft -> answers, for cloning an existing role into this form. The inverse of
    #: `assemble`, and the reason cloning works across both: `form_for(jd)` picks the
    #: contract from the JD itself, so a CUPE role clones into the WJQ flow rather than
    #: being read through the JDFN one and losing every section that form does not ask.
    clone_from_jd: Callable[..., AnswerContract]
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

    def assemble_checked(self, answers: AnswerContract) -> SFUJobDescription:
        """``assemble``, then the same question asked of the ANSWERS — the runtime twin
        of :meth:`_assembles_its_own_template`.

        🔴 The construction-time guard proves the assembler is faithful for an *empty*
        answer set. It cannot see that the JDFN assembler passes ``employee_group``
        straight through, so a posted ``employee_group=cupe`` produced a draft that
        ``template_of`` calls WJQ — judged by the CUPE ruleset (Phase B) and the CUPE
        numbers (Phase C), on the JDFN form. Measured on identical content: 59.38 /
        grade D / four blocking gates as ``apsa``, **89.05 / grade B / none** as
        ``cupe``. ``SFU-APPROVE-EDI-FOOTER`` is *overridable with a written reason in
        the audit log* (NN #1); a dropdown value was overriding it with neither.

        Asks ``template_of`` rather than checking the group against a list, because
        ``template_of`` is the question the validator itself asks — so this cannot drift
        from it, and groups that do NOT move the bar (``excluded``, unset) keep working.
        That matters: 36 archive documents are ``excluded`` and 4,630 carry no group at
        all, and every one of them must stay clonable.

        Raises ``ValueError``, which every Builder handler already renders as the error
        page rather than a 500 — the author is told to switch forms, not 500'd.
        """
        jd = self.assemble(answers)
        produced = template_of(jd)
        if produced != self.template:
            raise ValueError(
                f"this is the {self.template!r} form, but these answers assemble a "
                f"{produced!r} draft (employee_group={jd.employee_group!r}), which "
                "would be judged by the other form's rules and numbers. Start the "
                "draft on that form instead of changing the group on this one."
            )
        return jd


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
        clone_from_jd=jd_to_answers,
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
        clone_from_jd=wjq_answers_from_jd,
        sections=_WJQ_SECTIONS,
    ),
}


#: A ``str`` field at or above this length is rendered as a textarea rather than a
#: single-line input.
#:
#: Chosen to REPRODUCE the shipped JDFN Builder exactly — its hand-written map made
#: ``position_summary`` and ``additional_context`` (4,000) textareas and ``supervisory``
#: (600) a text input, and a test asserts the derived kinds still equal that map field
#: for field. It is a rendering hint about how much someone is about to type, not a
#: rulebook number, which is why it lives here and not in the register.
_TEXTAREA_MIN_LENGTH: int = 1000


def render_kind(answers_model: type[AnswerContract], target: str) -> str:
    """How ``target`` is rendered and read back — DERIVED from the answer contract.

    ⚠ **This replaced four hand-written sets of field names, and the reason is a
    correctness one rather than a tidiness one.** The old ``_kind_for`` ended in
    ``return "list"``, so any target missing from all four sets silently rendered as a
    one-item-per-line textarea. With one form that was invisible — every JDFN target
    was in a set. With two it is a live defect: the WJQ's ``major_functions`` would
    have lost its action-verb and %-allocation columns, and its seven point-factor
    sections would have been chopped into lines, with nothing anywhere going red.

    Deriving from the model means a new form needs **no** UI declarations at all, and an
    unknown target raises rather than guessing.
    """
    field = answers_model.model_fields.get(target)
    if field is None:
        raise KeyError(
            f"{answers_model.__name__} has no field {target!r} to render — a question "
            "targets it, so the two have drifted"
        )
    if target == "employee_group":
        return "select"
    annotation = str(field.annotation)
    if "bool" in annotation:
        return "checkbox"
    if "UUID" in annotation:
        return "hidden"
    if "DutyAnswer" in annotation:
        return "duties"
    if "ModifiedQual" in annotation:
        return "modified"
    if annotation.startswith("list"):
        return "list"
    max_length = next(
        (
            meta.max_length
            for meta in field.metadata
            if getattr(meta, "max_length", None) is not None
        ),
        0,
    )
    return "textarea" if max_length >= _TEXTAREA_MIN_LENGTH else "text"


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

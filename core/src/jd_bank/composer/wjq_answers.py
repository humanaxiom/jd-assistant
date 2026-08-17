"""What the CUPE (WJQ) guided-authoring flow collects — Phase E.

The WJQ is the CUPE 3338 **Weighted Job Questionnaire**: a 14-section point-factor
instrument, not a variant of the JDFN job-description form. So it gets its own answer
contract rather than optional fields bolted onto
:class:`~src.jd_bank.composer.answers.ComposerAnswers` — the measured finding behind
Phase E is that the two forms differ in *what they consist of*, and a model with half
its fields inapplicable is that difference smeared across a type instead of stated once.

**It mirrors the PARSER, deliberately.** ``jd_core.parser.wjq`` stores the seven
point-factor sections verbatim in ``additional_context`` under their own headings
(``wjq.yaml`` ``context_sections`` / ``section_headings``), which is why Phase A's
truncation defect mattered so much. This flow collects the same sections into the same
place, so **a CUPE JD authored here and a CUPE JD parsed from a ``.doc`` have the same
shape**. That symmetry is the whole reason the rest of the Builder needs no changes: the
draft is an ordinary :class:`~src.jd_core.models.parsed_jd.SFUJobDescription` and every
downstream service already speaks it.

Everything is optional (a draft is filled incrementally) except what the model itself
requires — same rule as the JDFN contract.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from src.jd_bank.composer.answers import DutyAnswer, ModifiedQual
from src.jd_core.rules import WjqSection

__all__ = ["WJQ_CONTEXT_TARGETS", "WJQAnswers"]

#: The answer fields that assemble into ``additional_context`` under a WJQ heading, in
#: the form's own section order.
#:
#: ⚠ **This is the RULEBOOK's ``wjq.context_sections``, asserted equal to it by test**
#: (the ``_SECTION_ANCHORS`` pattern) rather than a second hand-written copy. The parser
#: reads that list to decide which sections go into ``additional_context``; if the
#: authoring side drifted from it, a section the Builder collected would land somewhere
#: the parser never looks — and the round trip this whole design rests on would be
#: broken silently, in the one direction no existing test exercises.
#:
#: It is a literal rather than a ``get_rules()`` call so that importing the answer
#: contract does not load the rulebook; the test is what keeps them the same. Typed as
#: ``WjqSection`` so a target that is not a real WJQ section fails **type-checking**,
#: not just the test — and so each name is provably a key of ``wjq.section_headings``,
#: which is what the assembler indexes to write the heading the parser reads back.
WJQ_CONTEXT_TARGETS: tuple[WjqSection, ...] = (
    "level_of_independence",
    "training_exercised",
    "direction_exercised",
    "impact_of_errors",
    "effort",
    "working_conditions",
    "continuing_education",
)


class WJQAnswers(BaseModel):
    """A CUPE (WJQ) job questionnaire as authored — the Builder's WJQ contract."""

    model_config = ConfigDict(extra="forbid")

    # --- 1. Position identification ---
    title: str = Field(default="", max_length=200)
    department: str | None = Field(default=None, max_length=200)
    position_number: str | None = Field(default=None, max_length=50)
    #: The CUPE classification & grade the form's identification block records. Unlike
    #: the JDFN flow this is a normal thing for an author to know: the WJQ prints
    #: "Classification & Grade Approved" on the form itself.
    grade: str | None = Field(default=None, max_length=50)

    # --- 2. Position summary ---
    position_summary: str | None = Field(default=None, max_length=4000)

    # --- 3/4. Major + minor functions ---
    #: The WJQ prints TWELVE major-function slots and 77.4% of CUPE JDs fill all twelve
    #: (HR-202) — hence the cap, which is also the model's own duty ceiling.
    major_functions: list[DutyAnswer] = Field(default_factory=list, max_length=12)
    #: Minor functions are a section the JDFN form has no counterpart for. They assemble
    #: into the same ``duties`` list as the major ones, because that is where the parser
    #: puts them and where the validator reads duties from.
    minor_functions: list[DutyAnswer] = Field(default_factory=list, max_length=12)

    # --- 8. Internal and external contacts (-> relationships) ---
    internal: list[str] = Field(default_factory=list, max_length=30)
    external: list[str] = Field(default_factory=list, max_length=30)

    # --- 13. Qualifications ---
    education: list[str] = Field(default_factory=list, max_length=10)
    experience: list[str] = Field(default_factory=list, max_length=10)
    knowledge: list[ModifiedQual] = Field(default_factory=list, max_length=20)
    skills: list[ModifiedQual] = Field(default_factory=list, max_length=20)
    abilities: list[str] = Field(default_factory=list, max_length=20)

    # --- 5,6,7,9,10,11,12: the point-factor sections -> additional_context ---
    level_of_independence: str | None = Field(default=None, max_length=4000)
    training_exercised: str | None = Field(default=None, max_length=4000)
    direction_exercised: str | None = Field(default=None, max_length=4000)
    impact_of_errors: str | None = Field(default=None, max_length=4000)
    effort: str | None = Field(default=None, max_length=4000)
    working_conditions: str | None = Field(default=None, max_length=4000)
    continuing_education: str | None = Field(default=None, max_length=4000)

    #: The harmonized role this draft was cloned from, when it was — provenance, not
    #: content, exactly as on the JDFN contract (the near-duplicate authoring guard
    #: excludes it, so cloning a role does not immediately warn you about that role).
    cloned_from_cluster_id: UUID | None = None

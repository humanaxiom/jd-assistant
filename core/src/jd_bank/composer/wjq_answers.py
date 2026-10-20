"""What the CUPE (WJQ) guided-authoring flow collects — Phase E, restructured in J2.

The WJQ is the CUPE 3338 **Weighted Job Questionnaire**: a 14-section point-factor
instrument, not a variant of the JDFN job-description form. So it gets its own answer
contract rather than optional fields bolted onto
:class:`~src.jd_bank.composer.answers.ComposerAnswers` — the measured finding behind
Phase E is that the two forms differ in *what they consist of*, and a model with half
its fields inapplicable is that difference smeared across a type instead of stated once.

**It mirrors the PARSER, deliberately.** ``jd_core.parser.wjq`` stores the seven
point-factor sections verbatim in ``additional_context`` under their own headings
(``wjq.yaml`` ``context_sections`` / ``section_headings``). This flow writes each
section's free text to the same place, so **a CUPE JD authored here and a CUPE JD parsed
from a ``.doc`` keep the same shape** where the parser can see it.

**Track J2 adds HR's form STRUCTURE** (``hr-gap-analysis.md`` §2a): the major / minor
split kept apart, a (D)/(W)/(M)/(S) code per major function (not a % of time), HR's
fixed levels for sections 5, 6, 7 and 12, the duration / frequency / hours tables of 8,
10 and 11, certification / years / equivalency in 13, and the author's half of the
identification block (current classification, evaluating supervisor's title, date,
completed by). HR's approved classification is NOT asked — that box is HR's (HR-240).
Q9 (owner, 2026-10-19, option C): ONE "Occupational Skills" list with optional
"Knowledge of / Ability to" helpers, and a separate Occupational Requirement(s) box.

**Every option list is rulebook data** (``cupe_form.yaml``, HR-246 … HR-252); this
module only declares shapes. The assembler checks each answer against the rulebook and
refuses one outside it with the register id — so importing the contract never loads the
rulebook, except to fold a pre-J2 answer set (see :meth:`WJQAnswers._fold_legacy`).

Everything is optional (a draft is filled incrementally) except what the model itself
requires — same rule as the JDFN contract.
"""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Mapping, Sequence
from typing import Any, ClassVar, Literal, NamedTuple

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.jd_bank.composer.answers import AnswerContract
from src.jd_core.models.parsed_jd import (
    SFUJobDescription,
    SFUQualification,
    WJQCompletedBy,
)
from src.jd_core.rules import WjqSection

__all__ = [
    "WJQ_CONTEXT_TARGETS",
    "WJQ_LEVEL_TARGETS",
    "Column",
    "ContactAnswer",
    "EffortAnswer",
    "ExposureAnswer",
    "FunctionAnswer",
    "LocationAnswer",
    "MinorFunctionAnswer",
    "SkillAnswer",
    "WJQAnswers",
    "fold_legacy_quals",
]

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

#: The four checkbox sections (HR's fixed levels) -> the answer field holding the
#: ticked LETTERS. The section's free text (e.g. section 5's "examples of project
#: work") stays in the section's own text field above.
WJQ_LEVEL_TARGETS: Mapping[WjqSection, str] = {
    "level_of_independence": "level_of_independence_levels",
    "training_exercised": "training_exercised_levels",
    "direction_exercised": "direction_exercised_levels",
    "continuing_education": "continuing_education_levels",
}

#: A qualification line's ceiling, read off the model rather than restated.
_QUAL_MAX: int = next(
    int(meta.max_length)
    for meta in SFUQualification.model_fields["text"].metadata
    if getattr(meta, "max_length", None) is not None
)

#: A point-factor section's text ceiling: the model's own ``additional_context``
#: ceiling, which all seven share. It was 4,000 per section — and MEASURED 2026-10-19,
#: 8 of the 627 live CUPE roles hold a section longer than that (archive forms store
#: their instructions flattened into it), so cloning them failed validation; that
#: predates J2 (the Phase E contract had the same cap). The assembler REFUSES a joined
#: context over the model's ceiling rather than cutting it.
_SECTION_MAX: int = next(
    int(meta.max_length)
    for meta in SFUJobDescription.model_fields["additional_context"].metadata
    if getattr(meta, "max_length", None) is not None
)

#: A request-size guard for the lists whose REAL limit is checked by the assembler
#: (function limits, the draft's qualification / requirement ceilings): high enough
#: that any over-limit answer reaches that check's message, bounded so a crafted body
#: cannot post an unbounded list.
_LIST_GUARD = 120

#: A level of a checkbox section, by the letter HR's form uses for it (A = the first
#: option printed). The rulebook decides how many each section has; five is the most.
Level = Literal["A", "B", "C", "D", "E"]


class Column(NamedTuple):
    """One column of a structured row editor on the Builder page.

    ``options`` names the ``cupe_form`` list a select draws its choices from (or
    ``"scope"`` for internal / external); ``None`` is a text input. ``hidden`` carries a
    value through the page without asking for it (a pre-J2 %-allocation). Declared on
    the row model, so the page, the form reader and the repopulation all walk ONE list
    — a column added here cannot be rendered but not read back."""

    field: str
    label: str
    options: str | None = None
    width: str = "1 1 auto"
    hidden: bool = False


class _Row(BaseModel):
    """A structured row. Subclasses declare their editor ``COLUMNS``; the FIRST column
    is the one a row needs to exist (a row with it blank is a spare, not an answer)."""

    model_config = ConfigDict(extra="forbid")

    COLUMNS: ClassVar[tuple[Column, ...]] = ()


class FunctionAnswer(_Row):
    """A MAJOR function (section 3): verb, statement and HR's frequency code.

    ``allocation`` is a pre-J2 field: the Builder used to ask CUPE authors for a % of
    time, which HR's form does not have. It is no longer asked, but an answer set that
    carries one still loads and still prints it — never dropped."""

    COLUMNS: ClassVar[tuple[Column, ...]] = (
        Column("statement", "Function (what + how + why)"),
        Column("action_verb", "Action verb", width="0 0 9rem"),
        Column("frequency", "How often", "function_frequencies", "0 0 9rem"),
        Column("allocation", "", hidden=True),
    )

    action_verb: str = Field(default="", max_length=60)
    statement: str = Field(min_length=1, max_length=400)
    #: A ``cupe_form.function_frequencies`` meaning (``daily`` …), or ``None``.
    frequency: str | None = Field(default=None, max_length=20)
    allocation: int | None = Field(default=None, ge=0, le=100)


class MinorFunctionAnswer(_Row):
    """A MINOR function (section 4) — work that occurs "annually and periodically
    throughout the year". HR's form gives these no frequency code."""

    COLUMNS: ClassVar[tuple[Column, ...]] = (
        Column("statement", "Function (what + how + why)"),
        Column("action_verb", "Action verb", width="0 0 9rem"),
        Column("allocation", "", hidden=True),
    )

    action_verb: str = Field(default="", max_length=60)
    statement: str = Field(min_length=1, max_length=400)
    allocation: int | None = Field(default=None, ge=0, le=100)


class ContactAnswer(_Row):
    """A row of section 8. ``scope`` is the Bank's need, not HR's column: the model's
    relationships are split internal / external (the validator and search read that),
    and the form does not say which — the parser can only guess by keyword."""

    COLUMNS: ClassVar[tuple[Column, ...]] = (
        Column("contact", "Type of contact"),
        Column("scope", "Inside / outside SFU", "scope", "0 0 9rem"),
        Column("duration", "Duration", "table_durations", "0 0 8rem"),
        Column("frequency", "Frequency", "table_frequencies", "0 0 8rem"),
    )

    contact: str = Field(min_length=1, max_length=400)
    scope: Literal["internal", "external"] = "internal"
    duration: str | None = Field(default=None, max_length=40)
    frequency: str | None = Field(default=None, max_length=40)


class EffortAnswer(_Row):
    """A row of section 10: a type of effort, its concentrated duration, frequency."""

    COLUMNS: ClassVar[tuple[Column, ...]] = (
        Column("effort", "Type of effort"),
        Column("duration", "Duration", "table_durations", "0 0 8rem"),
        Column("frequency", "Frequency", "table_frequencies", "0 0 8rem"),
    )

    effort: str = Field(min_length=1, max_length=400)
    duration: str | None = Field(default=None, max_length=40)
    frequency: str | None = Field(default=None, max_length=40)


class LocationAnswer(_Row):
    """A row of section 11's first table: a location and the hours spent there, as a
    share of the hours worked per week (HR's sample: "General office | 35 / 35")."""

    COLUMNS: ClassVar[tuple[Column, ...]] = (
        Column("location", "Location"),
        Column("hours", "Hours per week (e.g. 35 / 35)", width="0 0 12rem"),
    )

    location: str = Field(min_length=1, max_length=400)
    hours: str | None = Field(default=None, max_length=40)


class ExposureAnswer(_Row):
    """A row of section 11's second or third table: an uncomfortable condition or a
    potential hazard, and how often the incumbent is exposed to it."""

    COLUMNS: ClassVar[tuple[Column, ...]] = (
        Column("condition", "Condition"),
        Column("frequency", "Frequency of exposure", "table_frequencies", "0 0 10rem"),
    )

    condition: str = Field(min_length=1, max_length=400)
    frequency: str | None = Field(default=None, max_length=40)


class SkillAnswer(_Row):
    """One line of the ONE Occupational Skills list (Q9, option C). ``helper`` is an
    optional lead phrase from ``cupe_form.occupational_skills_helpers`` ("Knowledge of",
    "Ability to"); the assembler joins it to ``text``."""

    COLUMNS: ClassVar[tuple[Column, ...]] = (
        Column("text", "Occupational skill"),
        Column("helper", "Starts with", "occupational_skills_helpers", "0 0 10rem"),
    )

    #: The qualification line's own ceiling (``SFUQualification.text``); the assembler
    #: refuses — with a message — a phrase + text that would not fit in it.
    text: str = Field(min_length=1, max_length=_QUAL_MAX)
    helper: str | None = Field(default=None, max_length=20)


def _modified_text(text: str, modifier: str | None) -> str:
    """A legacy knowledge / skill line as the J1 export printed it: its Toolkit
    modifier prefixed when the text does not already carry it, so it is never lost
    (unless the two would overflow the line's ceiling — then the text alone, as
    stored, rather than a line the model refuses)."""
    mod = (modifier or "").strip()
    text = text.strip()
    if (
        mod
        and mod.lower() not in text.lower()
        and len(mod) + 1 + len(text) <= _QUAL_MAX
    ):
        return f"{mod} {text}"
    return text


def split_helper(text: str, helpers: Sequence[str]) -> tuple[str | None, str]:
    """``text`` as ``(helper, rest)`` when it opens with one of ``helpers`` followed by
    more words — so a line the Builder joined comes back to the same two inputs."""
    for helper in helpers:
        lead = f"{helper} "
        if text.lower().startswith(lead.lower()) and text[len(lead) :].strip():
            return helper, text[len(lead) :].strip()
    return None, text


def fold_legacy_quals(
    lines: Sequence[tuple[str, str, str | None]],
    helpers: Mapping[Any, str],
    full_phrase: re.Pattern[str],
) -> list[SkillAnswer]:
    """Older CUPE knowledge / skill lines as ONE Occupational Skills list (Q9, option
    C — HR-251), in the order given, NOTHING dropped. (``ability`` lines are not folded
    here: owner ruling 2026-10-19, "Abilities → Requirements" — the caller sends them
    to Occupational Requirement(s), where the parser read them and the export prints
    them, HR-239.)

    ``lines`` are ``(kind, text, modifier)``. A line that already opens with a lead
    phrase is split back into phrase + text. Otherwise a KNOWLEDGE line gets its kind's
    phrase ("Knowledge of") only when it is a bare topic — never when it carries a
    Toolkit modifier (kept as text: "working office procedures") or already reads as a
    phrase (``full_phrase``, HR-253: "Good knowledge of …", "Proficiency with …").
    """
    phrases = list(helpers.values())
    out: list[SkillAnswer] = []
    for kind, raw, modifier in lines:
        text = _modified_text(raw, modifier)
        if not text:
            continue
        helper, rest = split_helper(text, phrases)
        if helper is not None:
            out.append(SkillAnswer(helper=helper, text=rest))
            continue
        phrase = helpers.get(kind) if kind == "knowledge" else None
        if (
            phrase is not None
            and not (modifier or "").strip()
            and not full_phrase.search(text)
            and len(phrase) + 1 + len(text) <= _QUAL_MAX
        ):
            out.append(SkillAnswer(helper=phrase, text=text))
        else:
            out.append(SkillAnswer(text=text))
    return out


class WJQAnswers(AnswerContract):
    """A CUPE (WJQ) job questionnaire as authored — the Builder's WJQ contract."""

    model_config = ConfigDict(extra="forbid")

    # --- 1. Position identification (the author's half of it) ---
    title: str = Field(default="", max_length=200)
    department: str | None = Field(default=None, max_length=200)
    position_number: str | None = Field(default=None, max_length=50)
    #: The position's CURRENT classification ("Current Position Classification"). Not
    #: HR's "Classification & Grade Approved" — that box is HR's (HR-240).
    current_classification: str | None = Field(default=None, max_length=100)
    supervisor_title: str | None = Field(default=None, max_length=200)
    date_completed: dt.date | None = None
    completed_by: WJQCompletedBy | None = None

    # --- 2. Position summary ---
    position_summary: str | None = Field(default=None, max_length=4000)

    # --- 3/4. Major + minor functions, kept APART (J2) ---
    #: The limit the author is held to is ``cupe_form.function_limits`` (HR-246),
    #: checked — never truncated to — by the assembler, with the register id. These
    #: ``max_length`` values are only the request-size guard, set ABOVE any limit the
    #: model can hold, so a 13th function reaches that message rather than pydantic's
    #: raw "at most 12 items" (review L1).
    major_functions: list[FunctionAnswer] = Field(
        default_factory=list, max_length=_LIST_GUARD
    )
    minor_functions: list[MinorFunctionAnswer] = Field(
        default_factory=list, max_length=_LIST_GUARD
    )

    # --- 5, 6, 7: levels (ticked letters) + the section's own text ---
    level_of_independence_levels: list[Level] = Field(
        default_factory=list, max_length=5
    )
    level_of_independence: str | None = Field(default=None, max_length=_SECTION_MAX)
    training_exercised_levels: list[Level] = Field(default_factory=list, max_length=5)
    training_exercised: str | None = Field(default=None, max_length=_SECTION_MAX)
    direction_exercised_levels: list[Level] = Field(default_factory=list, max_length=5)
    direction_exercised: str | None = Field(default=None, max_length=_SECTION_MAX)

    # --- 8. Internal and external contacts (-> relationships + durations) ---
    contacts: list[ContactAnswer] = Field(default_factory=list, max_length=60)

    # --- 9. Impact of errors ---
    impact_of_errors: str | None = Field(default=None, max_length=_SECTION_MAX)

    # --- 10. Effort: the table + any further text ---
    effort_rows: list[EffortAnswer] = Field(default_factory=list, max_length=20)
    effort: str | None = Field(default=None, max_length=_SECTION_MAX)

    # --- 11. Working conditions: three tables + any further text ---
    location_rows: list[LocationAnswer] = Field(default_factory=list, max_length=10)
    uncomfortable_rows: list[ExposureAnswer] = Field(
        default_factory=list, max_length=10
    )
    hazard_rows: list[ExposureAnswer] = Field(default_factory=list, max_length=10)
    working_conditions: str | None = Field(default=None, max_length=_SECTION_MAX)

    # --- 12. Continuing education ---
    continuing_education_levels: list[Level] = Field(default_factory=list, max_length=5)
    continuing_education: str | None = Field(default=None, max_length=_SECTION_MAX)

    # --- 13. Qualifications, as HR's form lays them out ---
    education: list[str] = Field(default_factory=list, max_length=10)
    certification: list[str] = Field(default_factory=list, max_length=10)
    experience_years: int | None = Field(default=None, ge=0, le=60)
    experience: list[str] = Field(default_factory=list, max_length=10)
    equivalency: Literal["acceptable", "not_acceptable"] | None = None
    equivalency_rationale: str | None = Field(default=None, max_length=1000)
    #: Request-size guards only. The draft holds at most forty qualification lines and
    #: twenty requirements; the assembler checks those with a message (review L2), so a
    #: pre-J2 answer set that FOLDS into more lines than a draft holds still loads and
    #: is told, never crashed. (MEASURED 2026-10-19: 34 of the 627 live CUPE roles carry
    #: more than 20 knowledge / skill / ability lines; one carries 38.)
    occupational_skills: list[SkillAnswer] = Field(
        default_factory=list, max_length=_LIST_GUARD
    )
    occupational_requirements: list[str] = Field(
        default_factory=list, max_length=_LIST_GUARD
    )

    @model_validator(mode="before")
    @classmethod
    def _fold_legacy(cls, data: Any) -> Any:
        """An answer set written by the pre-J2 page (``answers_json`` in a browser tab
        that is still open) must still load, and lose nothing:

        * ``grade`` ("the approved classification and grade", which J2 stopped asking —
          HR-240) becomes the author's ``current_classification``;
        * ``internal`` / ``external`` lines become contact rows of that scope;
        * ``knowledge`` / ``skills`` fold into the ONE Occupational Skills list (Q9
          option C, HR-251) — the one place this reads the rulebook; ``abilities`` go to
          Occupational Requirement(s) (owner ruling 2026-10-19, "Abilities →
          Requirements"), as they do on clone.
        """
        if not isinstance(data, dict):
            return data
        legacy = {"grade", "internal", "external", "knowledge", "skills", "abilities"}
        if not legacy & set(data):
            return data
        data = dict(data)
        grade = data.pop("grade", None)
        if grade and not data.get("current_classification"):
            data["current_classification"] = grade
        contacts = list(data.get("contacts") or [])
        for scope in ("internal", "external"):
            for line in data.pop(scope, None) or []:
                if str(line).strip():
                    contacts.append({"contact": str(line).strip(), "scope": scope})
        if contacts:
            data["contacts"] = contacts
        abilities = [str(a).strip() for a in data.pop("abilities", None) or []]
        if any(abilities):
            data["occupational_requirements"] = [
                *(data.get("occupational_requirements") or []),
                *(a for a in abilities if a),
            ]
        lines: list[tuple[str, str, str | None]] = []
        for key, kind in (("knowledge", "knowledge"), ("skills", "skill")):
            for item in data.pop(key, None) or []:
                if isinstance(item, Mapping):
                    lines.append(
                        (kind, str(item.get("text") or ""), item.get("modifier"))
                    )
                else:
                    lines.append((kind, str(item), None))
        if lines:
            from src.jd_core.rules import get_rules  # noqa: PLC0415 — legacy path only

            form = get_rules().cupe_form
            folded = fold_legacy_quals(
                lines,
                form.occupational_skills_helpers,
                form.occupational_skills_full_phrase_pattern,
            )
            data["occupational_skills"] = [
                *(data.get("occupational_skills") or []),
                *(s.model_dump() for s in folded),
            ]
        return data

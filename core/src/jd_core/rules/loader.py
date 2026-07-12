"""Typed, validated loader for the versioned SFU rulebook data.

**Rulebook as data** (CLAUDE.md non-negotiable #2): every gate threshold, word
list, verb list, KSA modifier, lexicon entry, restricted title and scoring
constant lives in the YAML files shipped beside this module — never hardcoded in
Python logic. This module is the *only* thing that reads them.

What it does, and deliberately does not do:

* **Does** parse + validate the shipped YAML into frozen pydantic v2 models,
  precompile every regex exactly once, cross-check that all files carry the same
  ``version``, and fail loudly (:class:`RulesError`) on anything malformed —
  a missing file, bad YAML, an unknown key, out-of-order grade bands, a severity
  key that is not a :data:`~src.jd_core.models.quality.JDIssueSeverity`.
* **Does not** implement any validator or gate logic. Phase 2.2 (section
  validators) and 2.3 (gate runner) consume :func:`get_rules`; the rules
  themselves stay inert data here.

Resource loading goes through :mod:`importlib.resources`, so the package works
wherever it is importable — notably inside the ``gates`` container, which mounts
only ``./core``. Nothing outside the package is ever read.

Provenance for each table is in the header comment of its YAML file; the SFU
source extract is ``docs/rulebook/sfu-reference.md``, the rulebook itself is
``docs/rulebook/sfu-jd-standards.txt``, and the tables were ported from hris
``packages/pipeline/src/pipeline/quality/jd_rules.py`` (``RULES_VERSION =
"jd_rules_sfu_v3"``).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import importlib.resources
import itertools
import json
import re
from collections.abc import Iterable, Mapping, Sequence, Set
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType
from typing import Annotated, Any, Final, Literal, NamedTuple, TypeVar, cast, get_args

import yaml
from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    PlainValidator,
    ValidationError,
    field_validator,
    model_validator,
)

from src.jd_core.models.bank import (
    HayFactorSignal,
    HaySignalLevel,
    TitleFamily,
    TitleFunction,
)
from src.jd_core.models.quality import (
    JDGrade,
    JDIssueCategory,
    JDIssueSeverity,
    SFUSection,
)

_PACKAGE: Final = __package__ or "src.jd_core.rules"

_SEVERITIES: Final[frozenset[str]] = frozenset(get_args(JDIssueSeverity))
_CATEGORIES: Final[frozenset[str]] = frozenset(get_args(JDIssueCategory))
_SECTIONS: Final[frozenset[str]] = frozenset(get_args(SFUSection))
_GRADES: Final[frozenset[str]] = frozenset(get_args(JDGrade))

#: The explicit "no keyword matched" state of BOTH title dimensions. It is a
#: member of the :data:`TitleFamily` / :data:`TitleFunction` vocabularies but
#: never a *rung* of the ladder or a *row* of the Application Table — it is what
#: you get when none of them matched, so it is labelled but has no keywords.
UNMAPPED: Final[Literal["unmapped"]] = "unmapped"

#: The Hay level a factor sits at when it clears no cutoff. Every OTHER level in
#: :data:`~src.jd_core.models.bank.HaySignalLevel` must carry a score cutoff in
#: ``hay_signals.yaml`` (``*_levels``); this one is the floor and must not.
HAY_BASE_LEVEL: Final[HaySignalLevel] = "low"

#: The levels that need a cutoff — derived, so adding a level to the vocabulary
#: makes the rulebook demand a cutoff for it rather than silently ignoring it.
_HAY_CUTOFF_LEVELS: Final[frozenset[str]] = frozenset(get_args(HaySignalLevel)) - {
    HAY_BASE_LEVEL
}

#: Who raises a rule: a deterministic gate here, or the (Phase 5) LLM pass.
RuleOwner = Literal["deterministic", "llm"]

#: The cross-cutting checklist bucket — labelled, but not a template section.
GENERAL_SECTION: Final[SFUSection] = "general"

#: The HR decision register — a rule file that describes the *other* rule files.
REGISTER_FILE: Final[str] = "decision_register.yaml"


class RulesError(RuntimeError):
    """The rulebook data is missing, malformed, or internally inconsistent.

    Always fatal: a JD Bank process with unloadable rules has no oracle, so it
    must not start rather than silently validate against nothing.
    """


# --- reusable field types ----------------------------------------------------

_K = TypeVar("_K")
_V = TypeVar("_V")


def _freeze(mapping: Mapping[_K, _V]) -> Mapping[_K, _V]:
    """Return a read-only view, so loaded rule tables cannot be mutated."""
    return MappingProxyType(dict(mapping))


def _compile_regex(value: Any) -> re.Pattern[str]:
    """Compile a ``{pattern, ignore_case}`` YAML mapping into a regex, once."""
    if not isinstance(value, Mapping):
        raise ValueError("expected a mapping with keys 'pattern' and 'ignore_case'")
    unknown = set(value) - {"pattern", "ignore_case"}
    if unknown:
        raise ValueError(f"unknown regex-rule key(s): {sorted(unknown)}")
    missing = {"pattern", "ignore_case"} - set(value)
    if missing:
        raise ValueError(f"missing regex-rule key(s): {sorted(missing)}")
    pattern = value["pattern"]
    if not isinstance(pattern, str) or not pattern.strip():
        raise ValueError("'pattern' must be a non-empty string")
    ignore_case = value["ignore_case"]
    if not isinstance(ignore_case, bool):
        raise ValueError("'ignore_case' must be a boolean")
    try:
        return re.compile(pattern, re.IGNORECASE if ignore_case else 0)
    except re.error as exc:
        raise ValueError(f"invalid regex {pattern!r}: {exc}") from exc


FrozenStrMap = Annotated[Mapping[str, str], AfterValidator(_freeze)]
FrozenRankMap = Annotated[Mapping[str, int], AfterValidator(_freeze)]
FrozenPenaltyMap = Annotated[Mapping[JDIssueSeverity, float], AfterValidator(_freeze)]
FrozenLabelMap = Annotated[Mapping[SFUSection, str], AfterValidator(_freeze)]
FrozenFallbackMap = Annotated[
    Mapping[JDIssueCategory, SFUSection], AfterValidator(_freeze)
]
Regex = Annotated[re.Pattern[str], PlainValidator(_compile_regex)]


def _check_terms(terms: Mapping[str, str]) -> Mapping[str, str]:
    for term, replacement in terms.items():
        if not term.strip():
            raise ValueError("term keys must be non-empty")
        if term != term.strip().lower():
            raise ValueError(f"term {term!r} must be lowercase and stripped")
        if not replacement.strip():
            raise ValueError(f"term {term!r} has an empty replacement")
    return terms


# --- one model per YAML file -------------------------------------------------


class _RuleFile(BaseModel):
    """Base for every rules YAML: frozen, closed, and version-stamped."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: str = Field(min_length=1)


class Thresholds(_RuleFile):
    """Numeric gate thresholds (``thresholds.yaml``)."""

    duties_min: int = Field(gt=0)
    duties_max: int = Field(gt=0)
    summary_min_words: int = Field(gt=0)
    summary_max_words: int = Field(gt=0)
    max_listed: int = Field(gt=0)
    evidence_context_window: int = Field(gt=0)
    duty_allocation_min_count: int = Field(gt=0)
    duty_allocation_total_min: int = Field(ge=0)
    duty_allocation_total_max: int = Field(ge=0)

    @model_validator(mode="after")
    def _ranges_are_ordered(self) -> Thresholds:
        if self.duties_min > self.duties_max:
            raise ValueError("duties_min must not exceed duties_max")
        if self.summary_min_words > self.summary_max_words:
            raise ValueError("summary_min_words must not exceed summary_max_words")
        if self.duty_allocation_total_min > self.duty_allocation_total_max:
            raise ValueError(
                "duty_allocation_total_min must not exceed duty_allocation_total_max"
            )
        return self


class ActionVerbs(_RuleFile):
    """The SFU action-verb glossary (``action_verbs.yaml``)."""

    approved: frozenset[str] = Field(min_length=1)

    @field_validator("approved")
    @classmethod
    def _are_lowercase(cls, verbs: frozenset[str]) -> frozenset[str]:
        for verb in sorted(verbs):
            if not verb.strip():
                raise ValueError("action verbs must be non-empty")
            if verb != verb.strip().lower():
                raise ValueError(f"action verb {verb!r} must be lowercase and stripped")
        return verbs


class CodedTerms(_RuleFile):
    """The gender-coded lexicon, by severity tier (``coded_terms.yaml``)."""

    medium: FrozenStrMap
    low: FrozenStrMap

    @field_validator("medium", "low")
    @classmethod
    def _terms_are_well_formed(cls, terms: Mapping[str, str]) -> Mapping[str, str]:
        return _check_terms(terms)

    @model_validator(mode="after")
    def _tiers_are_disjoint(self) -> CodedTerms:
        overlap = sorted(set(self.medium) & set(self.low))
        if overlap:
            raise ValueError(f"coded term(s) {overlap} appear in both severity tiers")
        return self

    @property
    def tiers(self) -> tuple[tuple[JDIssueSeverity, Mapping[str, str]], ...]:
        """The lexicon's tiers, most severe first, as ``(severity, terms)`` pairs.

        Each tier's *name is its severity*: a validator never names a severity,
        it reads the one the YAML filed the term under (CLAUDE.md §2). Tier
        fields are declared worst-first, which is the order findings are emitted
        in.
        """
        return tuple(
            (cast(JDIssueSeverity, name), cast(Mapping[str, str], getattr(self, name)))
            for name in type(self).model_fields
            if name in _SEVERITIES
        )


class Qualifications(_RuleFile):
    """Qualification / KSA rules (``qualifications.yaml``)."""

    knowledge_modifiers: frozenset[str] = Field(min_length=1)
    skill_modifiers: frozenset[str] = Field(min_length=1)
    ksa_rank: FrozenRankMap
    banned_phrases: tuple[str, ...] = Field(min_length=1)
    equivalent_combination: str = Field(min_length=1)
    ability_prefixes: tuple[str, ...] = Field(min_length=1)

    @field_validator("ksa_rank")
    @classmethod
    def _ranks_are_contiguous(cls, ranks: Mapping[str, int]) -> Mapping[str, int]:
        if not ranks:
            raise ValueError("ksa_rank must not be empty")
        if sorted(ranks.values()) != list(range(len(ranks))):
            raise ValueError(
                f"ksa_rank values must be distinct and contiguous from 0, "
                f"got {sorted(ranks.values())}"
            )
        return ranks


class Markers(_RuleFile):
    """Literal (non-regex) text markers (``markers.yaml``)."""

    placeholder: tuple[str, ...] = Field(min_length=1)
    working_conditions: tuple[str, ...] = Field(min_length=1)
    relationships_header: str = Field(min_length=1)


#: ``boilerplate.yaml`` fields that are NOT a mandated block. Everything else in
#: the file is one — so adding a fourth mandated block is a data edit, and it
#: lands on the decision surface (and in ``blocks``) with no code change.
_NON_BLOCK_FIELDS: Final[frozenset[str]] = frozenset(
    {"version", "coded_term_scan_exempt"}
)


class Boilerplate(_RuleFile):
    """SFU's mandated, do-not-edit text — and what the scanners may not mark down
    inside it (``boilerplate.yaml``).

    The rulebook pre-populates the About-SFU paragraph (Part 1.5) and mandates the
    territorial acknowledgement + Employment Equity statements (Part 1.6) on *every*
    JD. Our own coded-term lexicon then fires inside SFU's own words:
    ``compassionate`` sits in the About-SFU block at ``medium``, so a JD that obeys
    SFU loses 10 points and a grade, and a JD that drops the paragraph to dodge that
    trips ``SFU-COMP-ABOUT`` instead. It cannot win (HR-058).

    So the mandated text lives here as data, and :attr:`coded_term_scan_exempt` says
    — in the rulebook, not in a validator — which blocks the coded-term scan does not
    look inside. Presence is untouched: ``SFU-COMP-ABOUT`` / ``-TERRITORIAL`` / ``-EDI``
    still fire when a block is genuinely absent.

    **The unit of exemption is a passage, not a section.** A span of a JD is skipped
    only when it is one of SFU's mandated sentences verbatim (modulo whitespace, case
    and typographic punctuation — see :mod:`src.jd_core.quality.boilerplate`). Coded
    language cannot be smuggled past the scan by wrapping it in something that *looks
    like* the boilerplate: an "About SFU" heading exempts nothing, a fragment of a
    mandated sentence exempts nothing, and words spliced into a mandated sentence make
    it a different sentence, which exempts nothing.
    """

    about_sfu: tuple[str, ...] = Field(min_length=1)
    territorial_acknowledgement: tuple[str, ...] = Field(min_length=1)
    employment_equity: tuple[str, ...] = Field(min_length=1)
    #: The blocks ``SFU-LANG-CODED`` does not scan inside. THE decision (HR-107) —
    #: empty it and HR-058's false positive comes straight back.
    coded_term_scan_exempt: tuple[str, ...] = Field(default=())

    @field_validator("about_sfu", "territorial_acknowledgement", "employment_equity")
    @classmethod
    def _passages_are_real_text(cls, passages: tuple[str, ...]) -> tuple[str, ...]:
        for passage in passages:
            if not passage.strip():
                raise ValueError("a mandated passage must not be blank")
        if len(set(passages)) != len(passages):
            raise ValueError("a mandated block must not repeat a passage")
        return passages

    @field_validator("coded_term_scan_exempt")
    @classmethod
    def _exemption_is_a_set(cls, names: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(names)) != len(names):
            raise ValueError("coded_term_scan_exempt must not repeat a block")
        return names

    @model_validator(mode="after")
    def _the_exemption_names_blocks_that_exist(self) -> Boilerplate:
        """An exemption for a block that is not in this file would silently exempt
        nothing — the same "a gate that can never fire" failure as an uncatalogued
        blocking rule_id, so it is a load error, not a quiet no-op."""
        unknown = sorted(set(self.coded_term_scan_exempt) - set(self.block_names))
        if unknown:
            raise ValueError(
                f"coded_term_scan_exempt names block(s) {unknown} that this file does "
                f"not define; known blocks: {list(self.block_names)}"
            )
        return self

    @property
    def block_names(self) -> tuple[str, ...]:
        """The mandated blocks, in file order — derived, never written down twice."""
        return tuple(
            name for name in type(self).model_fields if name not in _NON_BLOCK_FIELDS
        )

    @property
    def blocks(self) -> Mapping[str, tuple[str, ...]]:
        """block name -> its mandated passages."""
        return _freeze(
            {
                name: cast(tuple[str, ...], getattr(self, name))
                for name in self.block_names
            }
        )

    @property
    def coded_term_exempt_passages(self) -> tuple[str, ...]:
        """Every passage the coded-term scan must not look inside."""
        blocks = self.blocks
        return tuple(
            passage for name in self.coded_term_scan_exempt for passage in blocks[name]
        )


class Patterns(_RuleFile):
    """Regex rules, precompiled once at load (``patterns.yaml``)."""

    incumbent: Regex
    duty_allocation: Regex
    degree_mention: Regex
    related_discipline: Regex
    senior_title: Regex


class RestrictedTitle(BaseModel):
    """One SFU-reserved title phrase."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    key: str = Field(min_length=1)
    # The catalogued gate a match raises (cross-checked against the catalog).
    rule_id: str = Field(min_length=1)
    phrase: str = Field(min_length=1)
    # Non-null only when the restriction is checkable from the JD alone.
    reserved_for_employee_group: str | None = None
    # The severity a validator raises this restriction at (advisory -> "info").
    severity: JDIssueSeverity
    note: str = ""


class _TitleDimension(NamedTuple):
    """One title dimension's four tables, for the cross-consistency validator.

    The two mappings arrive as their KEY SETS: the validator asks only "do these
    four tables describe the same set of names?", and ``Mapping`` is invariant in
    its key type, so passing the mappings themselves would force both dimensions'
    Literal keys down to ``str`` and lose the very typing this file just gained.
    """

    label: str
    vocabulary: Sequence[str]
    match_order: Sequence[str]
    keyword_names: Set[str]
    label_names: Set[str]


def _no_repeats(label: str, names: Sequence[str]) -> None:
    if len(set(names)) != len(names):
        raise ValueError(f"{label} must not repeat a name; got {list(names)}")


def _keywords_are_well_formed(
    keywords: Mapping[str, tuple[str, ...]],
) -> Mapping[str, tuple[str, ...]]:
    """Every match keyword is a non-empty, lower-case cue.

    Leading/trailing spaces are *deliberately* significant (``" vp "`` matches a
    whole token in a space-padded title, ``"vp"`` would also match "development"),
    so they are NOT stripped here — only an all-whitespace keyword is rejected.
    """
    for name, cues in keywords.items():
        if not cues:
            raise ValueError(f"{name!r} has no match keywords")
        if len(set(cues)) != len(cues):
            raise ValueError(f"{name!r} repeats a match keyword")
        for cue in cues:
            if not cue.strip():
                raise ValueError(f"{name!r} has an empty match keyword")
            if cue != cue.lower():
                raise ValueError(f"match keyword {cue!r} ({name}) must be lowercase")
    return keywords


class Titles(_RuleFile):
    """Job-title rules (``titles.yaml``): the restricted phrases SFU reserves, and
    the two independent dimensions a title is classified onto.

    * **Seniority** — the ``families`` ladder, the ``family_match_order`` the
      keywords are tried in, and the ``family_keywords`` themselves. **Not**
      rulebook-sourced (see the warning in the YAML and HR-059): inherited hris
      calibration, held here as data so it can be changed without touching code,
      and pinned by the register so it cannot be changed without telling HR.
    * **Function** — SFU's Job-Title Application Table (Part 3.3). This one *is*
      rulebook-sourced.

    Both dimensions carry a ``*_match_order`` that is deliberately **not** the
    vocabulary order: first match wins, so trying ``manager`` before ``director``
    is what makes "Associate Director" a manager. Order is policy, so it is data,
    and it is registered.
    """

    restricted: tuple[RestrictedTitle, ...] = Field(min_length=1)
    #: Seniority ladder, senior -> junior. The vocabulary of
    #: :data:`~src.jd_core.models.bank.TitleFamily` (minus ``"unmapped"``).
    families: tuple[TitleFamily, ...] = Field(min_length=1)
    #: The families' keywords, in the order they are TRIED. Semantic — see above.
    family_match_order: tuple[TitleFamily, ...] = Field(min_length=1)
    #: family -> the title keywords that signal it (lower-cased substrings).
    family_keywords: Annotated[
        Mapping[TitleFamily, tuple[str, ...]], AfterValidator(_freeze)
    ]
    #: family -> human label. Copy, not a decision. Covers ``"unmapped"`` too.
    family_labels: Annotated[Mapping[TitleFamily, str], AfterValidator(_freeze)]
    #: The families for which the "Role, Descriptor" comma format (Part 3.4)
    #: signals supervision.
    comma_supervisory_families: frozenset[TitleFamily] = Field(min_length=1)

    #: The functional Application Table's vocabulary, in table order. The
    #: vocabulary of :data:`~src.jd_core.models.bank.TitleFunction` (minus
    #: ``"unmapped"``).
    functions: tuple[TitleFunction, ...] = Field(min_length=1)
    #: The functions' keywords, in the order they are TRIED. Semantic.
    function_match_order: tuple[TitleFunction, ...] = Field(min_length=1)
    function_keywords: Annotated[
        Mapping[TitleFunction, tuple[str, ...]], AfterValidator(_freeze)
    ]
    #: function -> the Application Table's gloss. Copy. Covers ``"unmapped"``.
    function_labels: Annotated[Mapping[TitleFunction, str], AfterValidator(_freeze)]

    @field_validator("restricted")
    @classmethod
    def _keys_are_unique(
        cls, titles: tuple[RestrictedTitle, ...]
    ) -> tuple[RestrictedTitle, ...]:
        keys = [t.key for t in titles]
        if len(set(keys)) != len(keys):
            raise ValueError("restricted title keys must be unique")
        return titles

    @field_validator("family_keywords", "function_keywords")
    @classmethod
    def _cues_are_well_formed(
        cls, keywords: Mapping[str, tuple[str, ...]]
    ) -> Mapping[str, tuple[str, ...]]:
        return _keywords_are_well_formed(keywords)

    @model_validator(mode="after")
    def _dimensions_are_internally_consistent(self) -> Titles:
        """Vocabulary, match order, keywords and labels describe the SAME set.

        This is what stops the ladder and the classifier drifting apart: a rung
        with no keywords could never be matched, a keyword list for a rung that is
        not on the ladder would classify a title into a family the type does not
        have, and a missing label would crash the classifier mid-JD. All three are
        load errors, not runtime surprises.
        """
        dimensions: tuple[_TitleDimension, ...] = (
            _TitleDimension(
                "family",
                self.families,
                self.family_match_order,
                set(self.family_keywords),
                set(self.family_labels),
            ),
            _TitleDimension(
                "function",
                self.functions,
                self.function_match_order,
                set(self.function_keywords),
                set(self.function_labels),
            ),
        )
        for label, vocabulary, match_order, keyword_names, label_names in dimensions:
            _no_repeats(f"{label} vocabulary", vocabulary)
            _no_repeats(f"{label}_match_order", match_order)
            if UNMAPPED in vocabulary:
                raise ValueError(
                    f"{UNMAPPED!r} is the explicit no-match state, not a {label} — "
                    f"it must not appear in the {label} vocabulary"
                )
            names = set(vocabulary)
            if set(match_order) != names:
                raise ValueError(
                    f"{label}_match_order must try every {label} exactly once; "
                    f"got {sorted(set(match_order))} for {sorted(names)}"
                )
            if set(keyword_names) != names:
                raise ValueError(
                    f"{label}_keywords must give keywords for every {label} and no "
                    f"other; got {sorted(keyword_names)} for {sorted(names)}"
                )
            if set(label_names) != names | {UNMAPPED}:
                raise ValueError(
                    f"{label}_labels must label every {label} plus {UNMAPPED!r}; "
                    f"got {sorted(label_names)}"
                )

        unknown = sorted(self.comma_supervisory_families - set(self.families))
        if unknown:
            raise ValueError(
                f"comma_supervisory_families names non-existent famil(ies) {unknown}"
            )
        return self

    @property
    def by_id(self) -> Mapping[str, RestrictedTitle]:
        """Every restricted title, keyed by its stable ``key``."""
        return _freeze({title.key: title for title in self.restricted})


# --- advisory Hay-factor signals (hay_signals.yaml) ---------------------------

FrozenPointsMap = Annotated[Mapping[str, float], AfterValidator(_freeze)]
FrozenCountsMap = Annotated[Mapping[str, int], AfterValidator(_freeze)]
FrozenLevelMap = Annotated[Mapping[HaySignalLevel, float], AfterValidator(_freeze)]

#: The contribution each factor's score is built from. These key sets are the
#: *schema* of the points tables — the estimator indexes them by these names, so a
#: missing or unknown key is a load error rather than a ``KeyError`` mid-JD. The
#: NUMBERS behind them are the calibration, and they are what HR decides.
_KNOW_HOW_POINTS: Final[frozenset[str]] = frozenset(
    {
        "education_graduate",
        "education_undergraduate",
        "many_advanced_skills",
        "some_advanced_skills",
        "excellent_knowledge",
        "supervisory_scope",
        "broad_qualifications",
    }
)
_KNOW_HOW_COUNTS: Final[frozenset[str]] = frozenset(
    {"advanced_skills_for_many", "qualification_kinds_for_broad"}
)
_PROBLEM_SOLVING_POINTS: Final[frozenset[str]] = frozenset(
    {"section_item", "challenge_hit", "routine_hit"}
)
_PROBLEM_SOLVING_COUNTS: Final[frozenset[str]] = frozenset({"section_items_scored"})
_ACCOUNTABILITY_POINTS: Final[frozenset[str]] = frozenset(
    {"section_item", "autonomy_hit", "supervisory_scope", "external_breadth"}
)
_ACCOUNTABILITY_COUNTS: Final[frozenset[str]] = frozenset(
    {"section_items_scored", "external_for_breadth"}
)


def _exactly(name: str, keys: Set[str], required: Set[str]) -> None:
    if set(keys) != set(required):
        missing = sorted(set(required) - set(keys))
        unknown = sorted(set(keys) - set(required))
        raise ValueError(
            f"{name} must define exactly {sorted(required)}; "
            f"missing {missing}, unknown {unknown}"
        )


class HaySignalRules(_RuleFile):
    """Calibration for the advisory Hay-factor signals (``hay_signals.yaml``).

    Every table and every number here is ``hris_calibration`` — invented in hris,
    never published by SFU (HR-066 … HR-081). They decide whether a JD reads as a
    low / moderate / high signal on each Hay factor, so they are on the decision
    surface, all of them.

    What is **not** here, and cannot be: a Hay grade or point score. The charts are
    proprietary and SFU publishes none; :class:`~src.jd_core.models.bank.HaySignals`
    has no field to hold one. Adding a "grade" key to this file would configure
    nothing.
    """

    #: How many evidence phrases one factor may cite. Presentation: the score is
    #: computed *before* evidence is capped, so this cannot move a level.
    evidence_cap: int = Field(gt=0)

    advanced_skill_modifiers: frozenset[str] = Field(min_length=1)
    excellent_knowledge_modifiers: frozenset[str] = Field(min_length=1)

    edu_high: tuple[str, ...] = Field(min_length=1)
    edu_mid: tuple[str, ...] = Field(min_length=1)
    ps_challenge: tuple[str, ...] = Field(min_length=1)
    ps_routine: tuple[str, ...] = Field(min_length=1)
    acc_autonomy: tuple[str, ...] = Field(min_length=1)

    know_how_points: FrozenPointsMap
    know_how_counts: FrozenCountsMap
    know_how_levels: FrozenLevelMap

    problem_solving_points: FrozenPointsMap
    problem_solving_counts: FrozenCountsMap
    problem_solving_levels: FrozenLevelMap

    accountability_points: FrozenPointsMap
    accountability_counts: FrozenCountsMap
    accountability_levels: FrozenLevelMap

    @field_validator(
        "advanced_skill_modifiers",
        "excellent_knowledge_modifiers",
        "edu_high",
        "edu_mid",
        "ps_challenge",
        "ps_routine",
        "acc_autonomy",
    )
    @classmethod
    def _cues_are_lowercase(cls, cues: Iterable[str]) -> Iterable[str]:
        for cue in cues:
            if not cue.strip():
                raise ValueError("lexicon cues must be non-empty")
            if cue != cue.strip().lower():
                raise ValueError(f"lexicon cue {cue!r} must be lowercase and stripped")
        return cues

    @model_validator(mode="after")
    def _tables_carry_exactly_the_keys_the_estimator_reads(self) -> HaySignalRules:
        _exactly("know_how_points", set(self.know_how_points), _KNOW_HOW_POINTS)
        _exactly("know_how_counts", set(self.know_how_counts), _KNOW_HOW_COUNTS)
        _exactly(
            "problem_solving_points",
            set(self.problem_solving_points),
            _PROBLEM_SOLVING_POINTS,
        )
        _exactly(
            "problem_solving_counts",
            set(self.problem_solving_counts),
            _PROBLEM_SOLVING_COUNTS,
        )
        _exactly(
            "accountability_points",
            set(self.accountability_points),
            _ACCOUNTABILITY_POINTS,
        )
        _exactly(
            "accountability_counts",
            set(self.accountability_counts),
            _ACCOUNTABILITY_COUNTS,
        )
        for name, counts in (
            ("know_how_counts", self.know_how_counts),
            ("problem_solving_counts", self.problem_solving_counts),
            ("accountability_counts", self.accountability_counts),
        ):
            for key, value in counts.items():
                if value < 1:
                    raise ValueError(f"{name}.{key} must be >= 1, got {value}")
        return self

    @model_validator(mode="after")
    def _every_level_above_the_floor_has_an_ordered_cutoff(self) -> HaySignalRules:
        """Each factor scores a cutoff for every level except the floor (``low``).

        Derived from :data:`~src.jd_core.models.bank.HaySignalLevel`, so adding a
        level to the vocabulary makes the rulebook *demand* a cutoff for it in all
        three factors rather than silently never awarding it.
        """
        for name, cutoffs in self.factor_levels.items():
            _exactly(name, set(cutoffs), _HAY_CUTOFF_LEVELS)
            ordered = sorted(cutoffs.values())
            if len(set(ordered)) != len(ordered):
                raise ValueError(f"{name}: two levels share a cutoff — {dict(cutoffs)}")
        return self

    @model_validator(mode="after")
    def _the_evidence_cap_fits_the_signal_it_caps(self) -> HaySignalRules:
        """A full evidence list is actually constructible.

        Proved by construction at load (the same trick as
        :meth:`GatePolicy._reason_templates_render`): raise ``evidence_cap`` above
        what :class:`~src.jd_core.models.bank.HayFactorSignal` accepts and the
        rulebook refuses to load, rather than every sufficiently-evidenced JD
        blowing up in a ``ValidationError`` mid-estimate.
        """
        try:
            HayFactorSignal(
                factor="know_how",
                level=HAY_BASE_LEVEL,
                rationale="load-time probe",
                evidence=[f"phrase {i}" for i in range(self.evidence_cap)],
            )
        except ValidationError as exc:
            raise ValueError(
                f"evidence_cap {self.evidence_cap} is more evidence than "
                f"HayFactorSignal.evidence accepts: {exc}"
            ) from exc
        return self

    @property
    def factor_levels(self) -> Mapping[str, Mapping[HaySignalLevel, float]]:
        """Each factor's score cutoffs, keyed by the YAML field they came from."""
        return _freeze(
            {
                "know_how_levels": self.know_how_levels,
                "problem_solving_levels": self.problem_solving_levels,
                "accountability_levels": self.accountability_levels,
            }
        )


# --- JD-to-JD comparison (comparison.yaml) -----------------------------------

FrozenCueMap = Annotated[Mapping[str, tuple[str, ...]], AfterValidator(_freeze)]


class Comparison(_RuleFile):
    """Calibration for similarity, clustering and drift (``comparison.yaml``).

    Every number here is ``hris_calibration`` (HR-082 … HR-103): SFU publishes no
    similarity formula, no clone score, no cluster threshold and no drift metric.
    See the YAML header for the two that come closest — the drift escalations and
    the cloning rule — and why they still do not clear the ``sfu_rulebook`` bar.

    Two structural decisions the shape of this file *enforces*, both of them the
    duplicate-knob landmine that ``max_listed`` is on the backlog for:

    * :attr:`cluster_threshold` is **derived**, never stored. hris wrote
      ``CLUSTER_THRESHOLD = max(SIM_THRESHOLD, 0.80)``; shipping the answer as a
      third key would be two knobs holding one value with nothing keeping them in
      step. Only the two things that are actually decided are data.
    * :attr:`education_ladder` is the rulebook's **one** education ladder. hris
      held it twice (``drift._EDU_ORDINAL``, ``similarity._EDU_ORDER``); a rung's
      ordinal is now simply its index here, so drift's ordinals and similarity's
      ordinal closeness cannot disagree. The order the free-text cues are TRIED in
      is derived from it too (:attr:`education_text_rules`).
    """

    #: What a persisted neighbour/cluster was produced BY — identity, not policy.
    sim_version: str = Field(min_length=1)
    cluster_algo: str = Field(min_length=1)

    #: Education levels, LOW -> HIGH. A rung's ordinal is its index (high_school 0).
    education_ladder: tuple[str, ...] = Field(min_length=2)
    #: rung -> the lower-cased substring cues that place a requirement on it.
    education_text_cues: FrozenCueMap

    #: sim = weight_vector*vector + weight_skill*skills + weight_seniority*seniority.
    #: The three must sum to 1.0 — that is what makes the score a 0-1 number.
    weight_vector: float = Field(ge=0.0, le=1.0)
    weight_skill: float = Field(ge=0.0, le=1.0)
    weight_seniority: float = Field(ge=0.0, le=1.0)

    #: Only surface a neighbour at or above this overall similarity (noise floor).
    sim_threshold: float = Field(ge=0.0, le=1.0)
    #: Near-identical -> reads as a true clone. Must sit at or above the noise floor.
    clone_threshold: float = Field(ge=0.0, le=1.0)
    #: Minimum idf-weighted skill overlap for two JDs to be CLUSTERED (Phase 3).
    min_cluster_skill_overlap: float = Field(ge=0.0, le=1.0)

    #: Partial credit when two skills share an ontology family but are not identical.
    family_weight: float = Field(ge=0.0, le=1.0)
    #: Catch-all families that grant NO family credit.
    non_matchable_families: frozenset[str] = Field(min_length=1)

    #: Seniority/level tokens dropped before two titles are compared.
    title_stopwords: frozenset[str] = Field(min_length=1)
    #: What an unknown signal (no experience bar, an off-ladder education) is worth.
    unknown_signal_closeness: float = Field(ge=0.0, le=1.0)
    #: Years apart at which experience closeness bottoms out (hris divided by 10.0).
    experience_span_years: float = Field(gt=0.0)

    #: The floor the DERIVED cluster threshold cannot go below.
    cluster_threshold_floor: float = Field(ge=0.0, le=1.0)
    #: Fewer members than this and it is not a redundancy cluster.
    min_cluster_size: int = Field(ge=2)

    #: Skill-set Jaccard-distance cutoffs for the drift level.
    drift_minor_at: float = Field(ge=0.0, le=1.0)
    drift_major_at: float = Field(ge=0.0, le=1.0)
    #: A material move of the experience bar, in years (>= this many).
    material_years_delta: int = Field(ge=1)
    #: A material change of supervisory scope, in direct reports (MORE than this).
    material_reports_delta: int = Field(ge=0)

    experience_years_pattern: Regex
    supervisory_reports_pattern: Regex

    @field_validator("non_matchable_families", "title_stopwords")
    @classmethod
    def _tokens_are_lowercase(cls, tokens: frozenset[str]) -> frozenset[str]:
        for token in sorted(tokens):
            if not token.strip():
                raise ValueError("tokens must be non-empty")
            if token != token.strip().lower():
                raise ValueError(f"token {token!r} must be lowercase and stripped")
        return tokens

    @field_validator("education_text_cues")
    @classmethod
    def _cues_are_well_formed(
        cls, cues: Mapping[str, tuple[str, ...]]
    ) -> Mapping[str, tuple[str, ...]]:
        return _keywords_are_well_formed(cues)

    @model_validator(mode="after")
    def _the_weights_are_a_weighted_average(self) -> Comparison:
        """The three weights sum to 1.0.

        Not decoration: ``score_job_similarity`` is compared against
        :attr:`sim_threshold` and :attr:`clone_threshold`, which are 0-1 numbers. A
        rulebook whose weights sum to 1.2 would silently move every threshold.
        """
        total = self.weight_vector + self.weight_skill + self.weight_seniority
        if abs(total - 1.0) > 1e-9:
            raise ValueError(
                f"weight_vector + weight_skill + weight_seniority must sum to 1.0, "
                f"got {total}"
            )
        return self

    @model_validator(mode="after")
    def _the_thresholds_are_ordered(self) -> Comparison:
        if self.drift_minor_at >= self.drift_major_at:
            raise ValueError(
                f"drift_minor_at ({self.drift_minor_at}) must be below drift_major_at "
                f"({self.drift_major_at}) — otherwise no JD can ever be 'minor'"
            )
        if self.clone_threshold < self.sim_threshold:
            raise ValueError(
                f"clone_threshold ({self.clone_threshold}) must not sit below "
                f"sim_threshold ({self.sim_threshold}) — a clone is, at minimum, a "
                f"similar JD"
            )
        return self

    @model_validator(mode="after")
    def _the_ladder_and_its_cues_describe_the_same_rungs(self) -> Comparison:
        """One ladder, one cue table. A rung with no cues could never be read out of
        free text; cues for a rung that is not on the ladder would yield an ordinal
        the ladder cannot name."""
        _no_repeats("education_ladder", self.education_ladder)
        for rung in self.education_ladder:
            if rung != rung.strip().lower():
                raise ValueError(f"education rung {rung!r} must be lowercase")
        rungs = set(self.education_ladder)
        if set(self.education_text_cues) != rungs:
            raise ValueError(
                f"education_text_cues must give cues for every rung of "
                f"education_ladder and no other; got "
                f"{sorted(self.education_text_cues)} for {sorted(rungs)}"
            )
        return self

    @property
    def cluster_threshold(self) -> float:
        """The edge score two JDs must clear to be clustered — **derived**.

        hris: ``CLUSTER_THRESHOLD = max(SIM_THRESHOLD, 0.80)``. Cluster only on
        strong edges (well above the per-JD "show me similar" floor) to favour
        precision — but never *below* that floor, whatever HR does to it. Computed,
        so the two knobs cannot fall out of step; there is no third key holding the
        answer.
        """
        return max(self.sim_threshold, self.cluster_threshold_floor)

    @property
    def education_text_rules(self) -> tuple[tuple[str, tuple[str, ...]], ...]:
        """``(rung, cues)`` in the order they are TRIED — most senior rung first.

        Derived from :attr:`education_ladder` (reversed), not written down a second
        time. It is what makes "Master's degree" a *masters* rather than the generic
        "degree" -> *bachelors* rung: first match wins, seniors go first.
        """
        return tuple(
            (rung, self.education_text_cues[rung])
            for rung in reversed(self.education_ladder)
        )

    def education_ordinal(self, rung: str | None) -> int | None:
        """``rung``'s position on the ladder, or ``None`` if it is not a rung."""
        if rung is None or rung not in self.education_ladder:
            return None
        return self.education_ladder.index(rung)


class GradeBand(BaseModel):
    """A grade's lower score cutoff (``score >= min_score`` -> ``grade``)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    min_score: float = Field(ge=0.0, le=100.0)
    grade: JDGrade


class Scoring(_RuleFile):
    """The score scale, severity penalties, decay, and grade bands
    (``scoring.yaml``)."""

    #: The perfect-JD baseline penalties are subtracted from, and the floor the
    #: score bottoms out at. Calibration, therefore data — hris hardcoded the
    #: baseline as a literal ``100.0`` in Python.
    max_score: float = Field(gt=0.0, le=100.0)
    min_score: float = Field(ge=0.0, lt=100.0)
    severity_penalty: FrozenPenaltyMap
    severity_decay: float = Field(ge=0.0, le=1.0)
    grade_bands: tuple[GradeBand, ...] = Field(min_length=1)
    fallback_grade: JDGrade

    @field_validator("severity_penalty")
    @classmethod
    def _covers_every_severity(
        cls, penalties: Mapping[JDIssueSeverity, float]
    ) -> Mapping[JDIssueSeverity, float]:
        missing = _SEVERITIES - set(penalties)
        if missing:
            raise ValueError(
                f"severity_penalty must define every JDIssueSeverity; "
                f"missing {sorted(missing)}"
            )
        return penalties

    @model_validator(mode="after")
    def _score_range_is_ordered(self) -> Scoring:
        if self.min_score >= self.max_score:
            raise ValueError("min_score must be less than max_score")
        unreachable = [
            b.grade for b in self.grade_bands if b.min_score > self.max_score
        ]
        if unreachable:
            raise ValueError(
                f"grade band(s) {unreachable} sit above max_score "
                f"({self.max_score}) and can never be awarded"
            )
        return self

    @model_validator(mode="after")
    def _bands_are_ordered_and_complete(self) -> Scoring:
        for upper, lower in itertools.pairwise(self.grade_bands):
            if upper.min_score <= lower.min_score:
                raise ValueError(
                    "grade_bands must be in strictly descending min_score order"
                )
        grades = [band.grade for band in self.grade_bands]
        if len(set(grades)) != len(grades):
            raise ValueError("grade_bands must not repeat a grade")
        if self.fallback_grade in grades:
            raise ValueError(
                f"fallback_grade {self.fallback_grade!r} must not also be a band grade"
            )
        return self

    def grade_for(self, score: float) -> JDGrade:
        """The grade for ``score`` — the first band it clears, else the fallback.

        Pure data lookup over the bands (no scoring logic); the bands are
        validated strictly descending, so every score maps to exactly one grade.
        """
        for band in self.grade_bands:
            if score >= band.min_score:
                return band.grade
        return self.fallback_grade


class RuleSpec(BaseModel):
    """One deterministic gate's catalogued metadata + copy.

    The catalog — not the validator — owns a rule's ``category``, ``section``,
    ``default_severity`` and its message / recommendation wording. Validators
    supply only the computed values a template interpolates.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    rule_id: str = Field(min_length=1, max_length=64)
    category: JDIssueCategory
    section: SFUSection
    source_part: str = Field(min_length=1)  # the guide part, e.g. "Part 2B"
    default_severity: JDIssueSeverity
    title: str = Field(min_length=1)
    owner: RuleOwner = "deterministic"
    #: variant name -> template (``default`` unless a gate has several phrasings)
    messages: FrozenStrMap
    recommendations: FrozenStrMap

    @model_validator(mode="after")
    def _copy_is_complete(self) -> RuleSpec:
        if not self.messages:
            raise ValueError(f"rule {self.rule_id!r} has no message templates")
        if set(self.messages) != set(self.recommendations):
            raise ValueError(
                f"rule {self.rule_id!r}: messages and recommendations must carry "
                f"the same variant keys, got {sorted(self.messages)} vs "
                f"{sorted(self.recommendations)}"
            )
        for key, template in {**self.messages, **self.recommendations}.items():
            if not template.strip():
                raise ValueError(f"rule {self.rule_id!r}: variant {key!r} is empty")
        return self

    def render(self, variant: str, context: Mapping[str, Any]) -> tuple[str, str]:
        """The ``(message, recommendation)`` for ``variant``, interpolated.

        Raises:
            RulesError: the variant is unknown, or a template names a placeholder
                the caller did not supply — both are rulebook/validator drift and
                must fail loudly rather than emit a half-rendered finding.
        """
        try:
            message = self.messages[variant]
            recommendation = self.recommendations[variant]
        except KeyError as exc:
            raise RulesError(
                f"rule {self.rule_id!r} has no message variant {variant!r}; "
                f"known: {sorted(self.messages)}"
            ) from exc
        try:
            return message.format(**context), recommendation.format(**context)
        except (KeyError, IndexError) as exc:
            raise RulesError(
                f"rule {self.rule_id!r} variant {variant!r}: template placeholder "
                f"{exc} was not supplied"
            ) from exc


class RuleCatalog(_RuleFile):
    """The rule catalog + checklist presentation data (``rule_catalog.yaml``)."""

    rules: tuple[RuleSpec, ...] = Field(min_length=1)
    #: the SFU template sections, in template order ("general" is not one of them)
    section_order: tuple[SFUSection, ...] = Field(min_length=1)
    section_labels: FrozenLabelMap
    #: where an *uncatalogued* (LLM) finding lands, by its category
    category_fallback_section: FrozenFallbackMap

    @model_validator(mode="after")
    def _catalog_is_consistent(self) -> RuleCatalog:
        ids = [spec.rule_id for spec in self.rules]
        duplicates = sorted({rid for rid in ids if ids.count(rid) > 1})
        if duplicates:
            raise ValueError(f"duplicate rule_id(s): {duplicates}")

        if GENERAL_SECTION in self.section_order:
            raise ValueError(
                f"{GENERAL_SECTION!r} is the cross-cutting bucket, not a template "
                f"section: it must not appear in section_order"
            )
        if len(set(self.section_order)) != len(self.section_order):
            raise ValueError("section_order must not repeat a section")

        unlabelled = _SECTIONS - set(self.section_labels)
        if unlabelled:
            raise ValueError(f"section_labels is missing {sorted(unlabelled)}")

        uncovered = _CATEGORIES - set(self.category_fallback_section)
        if uncovered:
            raise ValueError(
                f"category_fallback_section must cover every JDIssueCategory; "
                f"missing {sorted(uncovered)}"
            )
        return self

    @property
    def by_id(self) -> Mapping[str, RuleSpec]:
        """Every rule, keyed by ``rule_id`` (the lookup validators use)."""
        return _freeze({spec.rule_id: spec for spec in self.rules})

    @property
    def rules_by_severity(self) -> Mapping[str, tuple[str, ...]]:
        """The rule ids at each severity — the *second route to blocking*.

        A rule does not only block approval by being named in a gate's
        ``rule_ids``: :class:`SeverityFloorGate` blocks on *any* finding at or
        above its ``min_severity``, so raising a rule's ``default_severity`` to
        the floor silently promotes it to blocking. Membership of these tiers is
        therefore a policy fact, and the HR decision register pins the tiers that
        reach the floor — demote or promote any rule across it and the build
        fails.
        """
        by_severity: dict[str, list[str]] = {severity: [] for severity in _SEVERITIES}
        for spec in self.rules:
            by_severity[spec.default_severity].append(spec.rule_id)
        return _freeze(
            {
                severity: tuple(sorted(rule_ids))
                for severity, rule_ids in by_severity.items()
            }
        )

    def spec(self, rule_id: str) -> RuleSpec:
        """The rule ``rule_id``, or :class:`RulesError` if it is not catalogued."""
        try:
            return self.by_id[rule_id]
        except KeyError as exc:
            raise RulesError(f"unknown rule_id {rule_id!r}") from exc

    def section_for(self, category: JDIssueCategory, rule_id: str | None) -> SFUSection:
        """The SFU section a finding belongs to: its rule's section when
        catalogued, else the category fallback (an LLM finding)."""
        if rule_id is not None and rule_id in self.by_id:
            return self.by_id[rule_id].section
        return self.category_fallback_section.get(category, GENERAL_SECTION)

    def label(self, section: SFUSection) -> str:
        """The human label for ``section`` (validated to exist at load)."""
        return self.section_labels[section]


# --- approval gates (gates.yaml) ---------------------------------------------


class _GateBase(BaseModel):
    """What every approval gate carries, whatever it measures.

    ``reason`` is a ``str.format`` template — the copy a blocked decision explains
    itself with, in rulebook terms. It is validated against its gate type's
    placeholder set **at load**, so the gate runner (a pure function over JD state
    that must never raise) can always render it.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    gate_id: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1)
    source_part: str = Field(min_length=1)  # the rulebook part the gate enforces
    reason: str = Field(min_length=1)
    #: May a human reviewer waive this gate? Per CLAUDE.md §1 an override always
    #: requires a written reason; a non-overridable gate cannot be waived at all.
    overridable: bool

    def render(self, context: Mapping[str, Any]) -> str:
        """``reason``, interpolated with the values the runner computed.

        Raises:
            RulesError: the template names a placeholder the runner does not
                supply, or applies a format spec the value does not support. Both
                are policy drift and are caught at load (see
                :meth:`GatePolicy._reason_templates_render`), never mid-decision.
        """
        try:
            return self.reason.format(**context)
        except (KeyError, IndexError, ValueError) as exc:
            raise RulesError(
                f"gate {self.gate_id!r}: reason template placeholder {exc} is not "
                f"one this gate can supply ({sorted(context)})"
            ) from exc

    def probe_context(self) -> dict[str, Any]:  # pragma: no cover - overridden
        """A dummy context with exactly the placeholders this gate type supplies.

        The load-time proof that ``reason`` renders. Subclasses must override.
        """
        raise NotImplementedError


class BlockingRulesGate(_GateBase):
    """Never approve if any of these catalogued rules fired ("never approve if…").

    ``rule_ids`` is cross-checked against ``rule_catalog.yaml`` when the whole
    rulebook is assembled — an unknown rule_id is a load error, not a gate that
    silently never fires.
    """

    type: Literal["blocking_rules"]
    rule_ids: tuple[str, ...] = Field(min_length=1)

    @field_validator("rule_ids")
    @classmethod
    def _are_unique(cls, rule_ids: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(rule_ids)) != len(rule_ids):
            raise ValueError("rule_ids must not repeat a rule")
        return rule_ids

    def probe_context(self) -> dict[str, Any]:
        return {"count": 1, "rule_ids": "SFU-EXAMPLE"}


class SeverityFloorGate(_GateBase):
    """Never approve while any finding sits at ``min_severity`` or above.

    Unlike a blocking-rule gate this also catches findings with no ``rule_id`` at
    all — i.e. the Phase-5 LLM pass.
    """

    type: Literal["severity_floor"]
    min_severity: JDIssueSeverity

    def probe_context(self) -> dict[str, Any]:
        return {
            "count": 1,
            "rule_ids": "SFU-EXAMPLE",
            "min_severity": self.min_severity,
        }


class ScoreFloorGate(_GateBase):
    """Never approve below this ``overall_score``."""

    type: Literal["score_floor"]
    min_score: float = Field(ge=0.0, le=100.0)

    def probe_context(self) -> dict[str, Any]:
        return {"score": 0.0, "min_score": self.min_score}


class GradeFloorGate(_GateBase):
    """Never approve below this :data:`JDGrade` (ranked by ``grade_order``)."""

    type: Literal["grade_floor"]
    min_grade: JDGrade

    def probe_context(self) -> dict[str, Any]:
        return {"grade": self.min_grade, "min_grade": self.min_grade}


#: One gate, discriminated by its ``type`` — the set of things a policy can measure.
GateSpec = Annotated[
    BlockingRulesGate | SeverityFloorGate | ScoreFloorGate | GradeFloorGate,
    Field(discriminator="type"),
]


class GatePolicy(_RuleFile):
    """The approval policy (``gates.yaml``): "never approve if…", as data.

    Every parameter the gate runner uses to reach a decision is here — the
    blocking rule-id sets, the severity / score / grade floors, each gate's
    overridability, its reason copy and its rulebook ``source_part``. Nothing in
    :mod:`src.jd_core.quality.gates` decides anything this file does not say.
    """

    #: JDIssueSeverity, least severe first (the rank the severity floor uses).
    severity_order: tuple[JDIssueSeverity, ...] = Field(min_length=1)
    #: JDGrade, worst first (the rank the grade floor uses).
    grade_order: tuple[JDGrade, ...] = Field(min_length=1)
    #: How many rule_ids / evidence snippets one blocked reason may cite.
    max_listed: int = Field(gt=0)
    gates: tuple[GateSpec, ...] = Field(min_length=1)

    @field_validator("severity_order")
    @classmethod
    def _ranks_every_severity(
        cls, order: tuple[JDIssueSeverity, ...]
    ) -> tuple[JDIssueSeverity, ...]:
        if set(order) != _SEVERITIES or len(set(order)) != len(order):
            raise ValueError(
                f"severity_order must rank every JDIssueSeverity exactly once; "
                f"got {list(order)}"
            )
        return order

    @field_validator("grade_order")
    @classmethod
    def _ranks_every_grade(cls, order: tuple[JDGrade, ...]) -> tuple[JDGrade, ...]:
        if set(order) != _GRADES or len(set(order)) != len(order):
            raise ValueError(
                f"grade_order must rank every JDGrade exactly once; got {list(order)}"
            )
        return order

    @model_validator(mode="after")
    def _gate_ids_are_unique(self) -> GatePolicy:
        ids = [gate.gate_id for gate in self.gates]
        duplicates = sorted({gid for gid in ids if ids.count(gid) > 1})
        if duplicates:
            raise ValueError(f"duplicate gate_id(s): {duplicates}")
        return self

    @model_validator(mode="after")
    def _reason_templates_render(self) -> GatePolicy:
        """Every gate's copy renders with the placeholders its type supplies.

        Proving this at load is what lets the runner promise it never raises on a
        JD: a template that names something the runner cannot compute is caught
        here, not while deciding whether an HR reviewer may approve.
        """
        for gate in self.gates:
            gate.render(gate.probe_context())
        return self

    @property
    def by_id(self) -> Mapping[str, GateSpec]:
        """Every gate, keyed by ``gate_id``."""
        return _freeze({gate.gate_id: gate for gate in self.gates})

    @property
    def blocking_rule_ids(self) -> frozenset[str]:
        """Every rule the policy will refuse to approve over ("never approve if…").

        A *derived* view of the whole policy, and the single most reviewable thing
        in it: the HR decision register pins this set, so promoting or demoting
        ANY rule — in any gate — breaks the build until the register says so.
        """
        return frozenset(
            rule_id
            for gate in self.gates
            if isinstance(gate, BlockingRulesGate)
            for rule_id in gate.rule_ids
        )

    @property
    def non_overridable_gate_ids(self) -> frozenset[str]:
        """The gates NO reviewer may waive, even with a written reason.

        The other derived view the register pins: removing a reviewer's discretion
        (or handing it back) is a policy change, and this is the one value that
        moves whichever gate's ``overridable`` flag is flipped.
        """
        return frozenset(gate.gate_id for gate in self.gates if not gate.overridable)

    def severity_rank(self, severity: JDIssueSeverity) -> int:
        """``severity``'s rank — higher is worse. Total, by construction."""
        return self.severity_order.index(severity)

    def grade_rank(self, grade: JDGrade) -> int:
        """``grade``'s rank — higher is better. Total, by construction."""
        return self.grade_order.index(grade)


# --- the HR decision register (decision_register.yaml) -----------------------
#
# The register is DATA, not a document, for one reason: a prose register rots
# silently, and a rotted register is worse than none — it *looks* like the policy
# was ratified. As data it is cross-checked against the rules it describes:
# `resolve_config_path` proves every entry still points at a live config key (at
# load — a renamed key is a `RulesError`), and `check_register` proves every
# `current_default` still equals the live value and every parameter on the
# decision surface is either registered or explicitly exempted (at `get_rules`
# and in the gate suite). Tuning a threshold without telling HR breaks the build.


#: Where a shipped default came from. The single most useful column for HR: it
#: separates "SFU already decided this, we transcribed it" from "we made it up".
DecisionProvenance = Literal[
    # Transcribed from SFU's published rulebook / Toolkit. `source_part` required.
    "sfu_rulebook",
    # Inherited from the hris pipeline's calibration (RULES_VERSION
    # jd_rules_sfu_v3). Not an SFU-published number.
    "hris_calibration",
    # JD Bank's own default. Nobody has ratified it. These are what HR must look
    # at first.
    "our_invention",
]

#: Where a decision stands. `open` = we defaulted it; `ratified` = HR decided it;
#: `deferred` = HR consciously postponed it (a decision in its own right).
DecisionStatus = Literal["open", "ratified", "deferred"]

#: The field a list-of-models is addressed by in a config path, in priority order
#: — so a path names a gate/rule/title/grade by its stable id, never by a list
#: index (which reordering the YAML would silently re-point).
_IDENTITY_FIELDS: Final[tuple[str, ...]] = ("gate_id", "rule_id", "key", "grade")


class ConfigRef(BaseModel):
    """Where a decision is configured: the YAML file, and a dotted key path.

    ``path`` is rooted at the :class:`Rules` field of the same name as the file's
    stem (``gates.yaml`` -> ``gates.…``), and is resolved against the *real loaded
    rules* by :func:`resolve_config_path`. It is deliberately expressive enough to
    name the thing that is actually decided:

    * ``thresholds.duties_max``                    — a scalar field
    * ``gates.SFU-APPROVE-SCORE-FLOOR.min_score``  — a gate, by its ``gate_id``
    * ``scoring.grade_bands.C.min_score``          — a band, by its ``grade``
    * ``scoring.severity_penalty.high``            — a mapping entry
    * ``coded_terms.low``                          — a whole lexicon tier
    * ``action_verbs.approved.accountable``        — membership of a set (bool)
    * ``gates.blocking_rule_ids``                  — a *derived* view: the whole
      "never approve if…" set, so promoting or demoting ANY rule breaks the build
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    file: str = Field(min_length=1)
    path: str = Field(min_length=1)

    @field_validator("file")
    @classmethod
    def _is_a_rule_file(cls, name: str) -> str:
        if name not in RULE_FILES or name == REGISTER_FILE:
            raise ValueError(
                f"config.file must be one of the rule files "
                f"{sorted(set(RULE_FILES) - {REGISTER_FILE})}, got {name!r}"
            )
        return name

    @model_validator(mode="after")
    def _path_is_rooted_in_the_file(self) -> ConfigRef:
        root = self.file.removesuffix(".yaml")
        if self.path.split(".")[0] != root:
            raise ValueError(
                f"config path {self.path!r} must start with {root!r} — it names a "
                f"key in {self.file}"
            )
        if any(not segment for segment in self.path.split(".")):
            raise ValueError(f"config path {self.path!r} has an empty segment")
        return self

    def __str__(self) -> str:
        return f"{self.file} :: {self.path}"


class HRDecision(BaseModel):
    """One policy call SFU HR must make — and what we ship until they do."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=r"^HR-\d{3}$")
    #: The decision, in HR's language — not the parameter's name.
    question: str = Field(min_length=1)
    config: ConfigRef
    #: What we ship today. Cross-checked against the live value (`check_register`)
    #: — this is what makes "review the config against the register" real.
    current_default: Any = None
    provenance: DecisionProvenance
    #: The rulebook part the default is transcribed from. Required for — and only
    #: meaningful for — `sfu_rulebook` provenance.
    source_part: str | None = None
    why_it_matters: str = Field(min_length=1)
    impact_if_changed: str = Field(min_length=1)
    status: DecisionStatus = "open"
    decided_by: str | None = None
    decided_on: dt.date | None = None
    decision_note: str | None = None

    @model_validator(mode="after")
    def _provenance_cites_its_source(self) -> HRDecision:
        if self.provenance == "sfu_rulebook" and not (self.source_part or "").strip():
            raise ValueError(
                f"{self.id}: provenance 'sfu_rulebook' must cite a source_part"
            )
        if self.provenance != "sfu_rulebook" and self.source_part is not None:
            raise ValueError(
                f"{self.id}: source_part is only meaningful for 'sfu_rulebook' "
                f"provenance — {self.provenance!r} defaults are not in the rulebook"
            )
        return self

    @model_validator(mode="after")
    def _decision_fields_match_the_status(self) -> HRDecision:
        """A ratified entry carries who decided, when, and what they said; an open
        one must not (an open decision with a decider is a lie in the register)."""
        decided = {
            "decided_by": self.decided_by,
            "decided_on": self.decided_on,
            "decision_note": self.decision_note,
        }
        if self.status == "ratified":
            missing = sorted(k for k, v in decided.items() if v is None)
            if missing:
                raise ValueError(
                    f"{self.id}: a ratified decision must record {missing}"
                )
        elif self.status == "open":
            present = sorted(k for k, v in decided.items() if v is not None)
            if present:
                raise ValueError(
                    f"{self.id}: an open decision must not record {present} — "
                    f"set status to 'ratified' or 'deferred'"
                )
        return self


class TrivialExemption(BaseModel):
    """A decision-surface parameter that is NOT a policy call at this path, and why.

    The escape hatch that keeps the coverage check honest: it is explicit, it is
    reviewed, and it must say *why*. A parameter that is neither registered nor
    exempted breaks the build.

    Two honest kinds of exemption, and no third:

    * **not a decision at all** — presentation, or definitional given something
      else (``scoring.fallback_grade`` is F because F is what sits below the last
      band).
    * **decided elsewhere** — ``covered_by`` names the register entry that pins
      it. Each gate's ``overridable`` flag is a member of the un-waivable set that
      HR-005 pins as a whole, so flipping any one of them still breaks the build;
      registering all fourteen separately would only add noise.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    config: ConfigRef
    reason: str = Field(min_length=30)
    #: The HR-### entry that carries this decision, when it is decided elsewhere.
    #: Validated against the register's ids — a dangling reference is a load error.
    covered_by: str | None = Field(default=None, pattern=r"^HR-\d{3}$")


class DecisionRegister(_RuleFile):
    """The HR decision register (``decision_register.yaml``)."""

    decisions: tuple[HRDecision, ...] = Field(min_length=1)
    trivial: tuple[TrivialExemption, ...] = Field(default=())

    @model_validator(mode="after")
    def _ids_and_paths_are_unique(self) -> DecisionRegister:
        ids = [d.id for d in self.decisions]
        duplicates = sorted({i for i in ids if ids.count(i) > 1})
        if duplicates:
            raise ValueError(f"duplicate decision id(s): {duplicates}")

        registered = [d.config.path for d in self.decisions]
        exempt = [t.config.path for t in self.trivial]
        both = sorted(set(registered) & set(exempt))
        if both:
            raise ValueError(
                f"config path(s) {both} are both registered and declared trivial — "
                f"a parameter is a decision or it is not"
            )
        for label, paths in (("registered", registered), ("trivial", exempt)):
            repeats = sorted({p for p in paths if paths.count(p) > 1})
            if repeats:
                raise ValueError(f"duplicate {label} config path(s): {repeats}")

        dangling = sorted(
            {
                t.covered_by
                for t in self.trivial
                if t.covered_by is not None and t.covered_by not in set(ids)
            }
        )
        if dangling:
            raise ValueError(
                f"trivial exemption(s) name covered_by decision id(s) that do not "
                f"exist: {dangling}"
            )
        return self

    @property
    def by_id(self) -> Mapping[str, HRDecision]:
        return _freeze({d.id: d for d in self.decisions})

    @property
    def registered_paths(self) -> frozenset[str]:
        """Every config path the register pins a ``current_default`` for."""
        return frozenset(d.config.path for d in self.decisions)

    @property
    def exempt_paths(self) -> frozenset[str]:
        """Every config path explicitly declared not-a-decision."""
        return frozenset(t.config.path for t in self.trivial)

    def by_status(self, status: DecisionStatus) -> tuple[HRDecision, ...]:
        in_status = (d for d in self.decisions if d.status == status)
        return tuple(sorted(in_status, key=lambda d: d.id))


# --- the rules' content identity (what a ValidationReport is stamped with) ----

#: SemVer's build-metadata separator, between the declared version and the digest.
VERSION_SEPARATOR: Final[str] = "+"

#: How much of the digest the stamped version carries. A git short-sha: readable,
#: and 48 bits is far more than a rulebook of ~12 files needs.
CONTENT_HASH_LENGTH: Final[int] = 12


def _canonical(value: Any) -> Any:
    """``value`` as order-stable, JSON-encodable plain data.

    The canonical form is what makes the content hash an *identity* rather than a
    checksum of a file's bytes: a model is its sorted fields, a mapping its sorted
    keys, a set its sorted members (order is not policy), a sequence its items in
    order (order IS policy — ``family_match_order`` decides overlaps), and a compiled
    regex is its source plus its flags.
    """
    if isinstance(value, BaseModel):
        return {
            field: _canonical(getattr(value, field))
            for field in sorted(type(value).model_fields)
        }
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, re.Pattern):
        compiled = cast(re.Pattern[str], value)
        return {"pattern": compiled.pattern, "flags": compiled.flags}
    if isinstance(value, Mapping):
        return {str(key): _canonical(value[key]) for key in sorted(value, key=str)}
    if isinstance(value, Set):
        return sorted((_canonical(member) for member in value), key=repr)
    if isinstance(value, Sequence):
        return [_canonical(item) for item in value]
    raise RulesError(  # pragma: no cover - defensive
        f"rule data of type {type(value).__name__} cannot be canonicalised; the "
        f"content hash would silently stop tracking it"
    )


def _content_hash(rule_files: Mapping[str, _RuleFile]) -> str:
    """SHA-256 over the canonicalised rule files. Pure, portable, deterministic."""
    payload = json.dumps(
        {name: _canonical(rule_files[name]) for name in sorted(rule_files)},
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class Rules(BaseModel):
    """The whole validated rulebook — one frozen object, one ``version``.

    :attr:`version` is **derived from the rule content** (see
    :meth:`content_hash`), not declared. Before Phase 2.5 it was the literal string
    every YAML carried, and it tracked nothing: the rules under ``jd_rules_sfu_v3``
    changed materially across 2.2, 2.3 and 2.4 (new files, new gates, 45 new
    decisions) while the string every ``ValidationReport`` was stamped with stood
    still. Two reports stamped ``v3`` could have been produced by different
    rulebooks — a false audit trail (CLAUDE.md non-negotiable #6), about to have the
    archive baseline pinned to it.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    #: The human-readable version every rules YAML carries (``jd_rules_sfu_v4``).
    #: Bumped by hand when the rulebook changes in a way HR should be told about.
    declared_version: str = Field(min_length=1)
    thresholds: Thresholds
    action_verbs: ActionVerbs
    coded_terms: CodedTerms
    qualifications: Qualifications
    markers: Markers
    patterns: Patterns
    titles: Titles
    boilerplate: Boilerplate
    hay_signals: HaySignalRules
    comparison: Comparison
    scoring: Scoring
    rule_catalog: RuleCatalog
    gates: GatePolicy
    decision_register: DecisionRegister

    @property
    def content_hash(self) -> str:
        """SHA-256 over the canonicalised rule data — the rules' content identity.

        Deterministic and portable: computed from the *loaded models*, so YAML key
        order, comments, quoting and line wrapping cannot move it, and two machines
        with the same rules always agree. No clock, no file mtime, no
        ``PYTHONHASHSEED`` (sets are canonicalised sorted, mappings by sorted key).

        ``decision_register.yaml`` is deliberately **excluded**. It describes the
        rules; it does not change what the validator computes about a JD. Including
        it would mean a copy-edit to an ``why_it_matters`` paragraph invalidated
        every previously stamped report — and, since the register's own
        ``current_default`` values are already cross-checked against the live rules
        (:func:`check_register`), a real rule change is caught either way.

        Recomputed on access rather than cached: ``model_copy(update=...)`` (how the
        test suites retune a rulebook) must not be able to carry a stale identity
        into a report it stamps. It is ~1 ms.
        """
        return _content_hash({name: getattr(self, name) for name in _HASHED_FIELDS})

    @property
    def version(self) -> str:
        """What a ``ValidationReport`` is stamped with: ``<declared>+<short hash>``.

        Both halves earn their place. The declared half is what an HR reader can
        actually say out loud and look up; a bare digest is unreadable to them. The
        hash half is what makes the stamp *true* — it moves whenever any rule moves,
        so an HR reviewer holding an old report can settle the only question that
        matters ("was this produced by today's rules?") by comparing this one string
        against today's. ``+`` is SemVer's build-metadata separator, and 12 hex
        characters is a git short-sha: familiar, and 48 bits is far more than a
        rulebook needs.
        """
        return (
            f"{self.declared_version}"
            f"{VERSION_SEPARATOR}{self.content_hash[:CONTENT_HASH_LENGTH]}"
        )

    @model_validator(mode="after")
    def _restricted_titles_are_catalogued(self) -> Rules:
        catalogued = set(self.rule_catalog.by_id)
        unknown = sorted(
            t.rule_id for t in self.titles.restricted if t.rule_id not in catalogued
        )
        if unknown:
            raise ValueError(
                f"titles.yaml names rule_id(s) absent from rule_catalog.yaml: "
                f"{unknown}"
            )
        return self

    @model_validator(mode="after")
    def _blocking_gates_are_catalogued(self) -> Rules:
        """A gate that blocks on a rule nobody raises is a policy that silently
        does nothing — the worst failure mode for an approval bar."""
        catalogued = set(self.rule_catalog.by_id)
        unknown = sorted(self.gates.blocking_rule_ids - catalogued)
        if unknown:
            raise ValueError(
                f"gates.yaml blocks on rule_id(s) absent from rule_catalog.yaml: "
                f"{unknown}"
            )
        return self

    @model_validator(mode="after")
    def _hay_modifiers_exist_on_the_rulebooks_own_scales(self) -> Rules:
        """The Hay estimator may only read modifiers the rulebook actually defines.

        ``hay_signals.yaml`` names which Toolkit modifiers count as depth
        (``advanced``/``expert`` skills, ``excellent`` knowledge). The *scales* those
        names come from are SFU's and live in ``qualifications.yaml``
        (``skill_modifiers``, ``knowledge_modifiers`` — rulebook Parts 5.2/5.1). Two
        files, the same vocabulary, and nothing kept them in step: rename or re-case
        a modifier in ``qualifications.yaml`` and every Know-How signal would
        silently stop scoring — no load error, no failing test, gates green. Exactly
        the ``max_listed`` duplicate-knob problem, but on a *registered* decision
        parameter (HR-071 / HR-072).

        So the subset relation is enforced here, at load, like every other cross-file
        fact (a restricted title's ``rule_id`` must be catalogued; a blocking gate's
        rules must exist). ``qualifications.yaml`` stays the single source of the
        vocabulary; ``hay_signals.yaml`` only says which end of it means depth.
        """
        scales = (
            (
                "advanced_skill_modifiers",
                self.hay_signals.advanced_skill_modifiers,
                "skill_modifiers",
                self.qualifications.skill_modifiers,
            ),
            (
                "excellent_knowledge_modifiers",
                self.hay_signals.excellent_knowledge_modifiers,
                "knowledge_modifiers",
                self.qualifications.knowledge_modifiers,
            ),
        )
        for hay_field, chosen, qual_field, scale in scales:
            unknown = sorted(chosen - scale)
            if unknown:
                raise ValueError(
                    f"hay_signals.yaml {hay_field} names modifier(s) {unknown} that "
                    f"are not on the rulebook's own scale "
                    f"(qualifications.yaml {qual_field}: {sorted(scale)}). The Hay "
                    f"estimator would score nothing for them."
                )
        return self

    @model_validator(mode="after")
    def _hay_education_cues_are_on_the_rulebooks_own_education_ladder(self) -> Rules:
        """The Hay estimator's education cues come from the rulebook's ONE ladder.

        ``hay_signals.yaml`` says which education reads as *graduate* (``edu_high``)
        and which as *undergraduate* (``edu_mid``). Those are cues — ``master``,
        ``doctora``, ``bachelor``, ``degree`` — and the same cues appear again in
        ``comparison.yaml`` (``education_text_cues``), which is where the rulebook's
        education vocabulary now lives. Two files, one vocabulary, and nothing kept
        them in step: rename ``doctora`` to ``doctoral`` in one and the other silently
        stops reading a PhD — no load error, no failing test, gates green. The same
        duplicate-vocabulary shape as
        :meth:`_hay_modifiers_exist_on_the_rulebooks_own_scales` (2.4b), so it gets
        the same treatment.

        ``comparison.yaml`` owns the vocabulary; ``hay_signals.yaml`` only says which
        end of it reads as depth. (The *tiering* is genuinely Hay's own — the ladder
        has five rungs, Know-How scores two — so only the subset relation is enforced,
        not a mapping.)
        """
        ladder_cues = {
            cue for cues in self.comparison.education_text_cues.values() for cue in cues
        }
        for hay_field, chosen in (
            ("edu_high", self.hay_signals.edu_high),
            ("edu_mid", self.hay_signals.edu_mid),
        ):
            unknown = sorted(set(chosen) - ladder_cues)
            if unknown:
                raise ValueError(
                    f"hay_signals.yaml {hay_field} names education cue(s) {unknown} "
                    f"that are not on the rulebook's own education ladder "
                    f"(comparison.yaml education_text_cues: {sorted(ladder_cues)}). "
                    f"One of the two files has drifted."
                )
        return self

    @model_validator(mode="after")
    def _register_entries_point_at_live_config(self) -> Rules:
        """Every register entry still names a real key in the real rules.

        A renamed or deleted config key is caught **here**, at load — the register
        can never quietly come to describe a parameter that no longer exists.
        (Whether each ``current_default`` still *equals* the live value, and
        whether the whole decision surface is accounted for, is
        :func:`check_register` — enforced on the shipped rulebook by
        :func:`get_rules` and by the gate suite. It is deliberately not enforced
        here, so a scratch ``load_rules(directory)`` can still explore a tuned
        policy without having to hand-edit the register first.)
        """
        register = self.decision_register
        refs = [(d.id, d.config) for d in register.decisions] + [
            ("trivial", t.config) for t in register.trivial
        ]
        for owner, ref in refs:
            try:
                resolve_config_path(self, ref.path)
            except RulesError as exc:
                raise ValueError(f"decision_register.yaml [{owner}]: {exc}") from exc
        return self


# --- config paths: addressing the rules the register talks about --------------


def _identity_of(item: BaseModel) -> tuple[str, str] | None:
    """The ``(field, value)`` a list item is addressed by, if it has one."""
    for field in _IDENTITY_FIELDS:
        if field in type(item).model_fields:
            return field, str(getattr(item, field))
    return None


def _step(node: Any, segment: str, path: str, walked: str) -> Any:
    """Walk one ``.``-separated segment of a config path. Raises RulesError."""

    def fail(detail: str) -> RulesError:
        return RulesError(
            f"config path {path!r} does not resolve: {detail} (at {walked!r})"
        )

    if segment.startswith("_"):
        raise fail(f"segment {segment!r} is private")

    if isinstance(node, BaseModel):
        model = type(node)
        is_field = segment in model.model_fields
        is_property = isinstance(getattr(model, segment, None), property)
        if is_field or is_property:
            value = getattr(node, segment)
            if callable(value):
                raise fail(f"{segment!r} is a method, not a config value")
            return value
        # A model that keys its members (`GatePolicy`, `RuleCatalog`, `Titles`) is
        # addressable by them directly: `gates.SFU-APPROVE-SCORE-FLOOR.min_score`
        # reads as the policy does, and names the gate by its stable id rather
        # than by a list position the YAML could reorder.
        keyed = getattr(node, "by_id", None)
        if isinstance(keyed, Mapping):
            members = cast(Mapping[str, Any], keyed)
            if segment in members:
                return members[segment]
            raise fail(
                f"{model.__name__} has no field or member {segment!r}; members: "
                f"{sorted(members)}"
            )
        raise fail(
            f"{model.__name__} has no {segment!r}; known fields: "
            f"{sorted(model.model_fields)}"
        )

    if isinstance(node, Mapping):
        if segment not in node:
            raise fail(f"mapping has no key {segment!r}")
        return node[segment]

    # A set is addressed by MEMBERSHIP: `action_verbs.approved.accountable` is
    # True/False. That is what lets the register pin a contested member of a big
    # word list without inlining the whole list.
    if isinstance(node, Set):
        return segment in node

    if isinstance(node, Sequence) and not isinstance(node, str | bytes):
        items = list(node)
        if not all(isinstance(item, BaseModel) for item in items):
            raise fail("a list of plain values cannot be addressed by key")
        for item in items:
            identity = _identity_of(cast(BaseModel, item))
            if identity is not None and identity[1] == segment:
                return item
        known = sorted(
            i[1]
            for i in (_identity_of(cast(BaseModel, item)) for item in items)
            if i is not None
        )
        raise fail(f"no list item identified by {segment!r}; known: {known}")

    raise fail(f"{type(node).__name__} cannot be addressed by {segment!r}")


def resolve_config_path(rules: Rules, path: str) -> Any:
    """The live value at ``path`` in ``rules``.

    Raises:
        RulesError: the path does not resolve — a register entry naming a config
            key that no longer exists.
    """
    node: Any = rules
    walked: list[str] = []
    for segment in path.split("."):
        node = _step(node, segment, path, ".".join(walked) or "<rules>")
        walked.append(segment)
    return node


def normalize_config_value(value: Any, path: str) -> Any:
    """A config value in the plain form the register writes it down in.

    The comparison contract between ``current_default`` and the live rules:

    * scalars (and ``None``) compare as themselves;
    * a **set** compares as its sorted members (``["excellent","none","working"]``);
    * a **mapping** compares as the whole mapping — keys *and* values. It is
      tempting to compare only the key set (a lexicon "decision" looks like *which
      terms are flagged*), but the values carry policy too: ``ksa_rank`` is a
      mapping whose *values* are the Knowledge -> Skills -> Abilities order that a
      blocking gate enforces, and permuting them while keeping the keys would slip
      past a key-set comparison;
    * a list/tuple of plain values compares as a list, in file order;
    * a regex compares as its pattern source.

    Raises:
        RulesError: the path stops on a whole model (or a list of them) — the
            register must name the parameter that is decided, not the object that
            contains it.
    """
    if isinstance(value, BaseModel):
        raise RulesError(
            f"config path {path!r} names a whole {type(value).__name__}; a register "
            f"entry must name the parameter that is decided (e.g. "
            f"{path}.<field>)"
        )
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, re.Pattern):
        return cast(re.Pattern[str], value).pattern
    if isinstance(value, Set):
        return sorted(cast(Set[str], value))
    if isinstance(value, Mapping):
        entries = cast(Mapping[str, Any], value)
        return {key: normalize_config_value(entries[key], path) for key in entries}
    if isinstance(value, Sequence):
        items = list(value)
        if any(isinstance(item, BaseModel) for item in items):
            raise RulesError(
                f"config path {path!r} names a list of objects; address one of them "
                f"by its id (e.g. {path}.<id>.<field>)"
            )
        return items
    raise RulesError(  # pragma: no cover - defensive
        f"config path {path!r} resolves to an unsupported type "
        f"{type(value).__name__}"
    )


def live_value(rules: Rules, path: str) -> Any:
    """The normalized live value at ``path`` — what a ``current_default`` must equal."""
    return normalize_config_value(resolve_config_path(rules, path), path)


# --- the decision surface: what MUST be registered or explicitly exempted ------


#: Rule files whose EVERY field is a decision-surface parameter. These files are
#: flat tables of matchers, limits and weights — a word list, a regex, a
#: threshold, a points table — and every one of them changes what the system
#: decides about a JD. Enumerating them field-by-field means a new key in any of
#: them is on the surface the moment it is added, with no enumerator change.
#:
#: ``hay_signals`` is deliberately kept **flat** (``know_how_points`` rather than
#: ``know_how.points``) precisely so it can live here: a nested rule file would
#: have to be hand-enumerated below, and a field added to it later would be
#: invisible to :func:`check_register` — which is exactly how four rule files once
#: went unregistered. Any new rule file should be shaped to qualify for this list.
_FLAT_SURFACE_FILES: Final[tuple[str, ...]] = (
    "thresholds",
    "patterns",
    "qualifications",
    "action_verbs",
    "markers",
    "boilerplate",
    "hay_signals",
    "comparison",
)


def decision_surface(rules: Rules) -> frozenset[str]:
    """Every parameter of the loaded rules that carries a policy judgement.

    Enumerated **from the rules themselves**, not from a hand-kept list — so a
    gate, threshold, regex, word list, penalty, grade band, lexicon tier,
    restricted title or catalogued rule added later shows up here automatically,
    and the coverage check (:func:`check_register`) breaks the build until
    someone says whether HR must decide it.

    **All thirteen rule files are walked.** The surface is everything that can change
    what the system decides about a JD:

    * ``gates.yaml`` — the approval policy: each gate's overridability and the
      parameter it measures, plus two *derived* views of the policy as a whole
      (:attr:`GatePolicy.blocking_rule_ids`,
      :attr:`GatePolicy.non_overridable_gate_ids`).
    * ``boilerplate.yaml`` — SFU's mandated text, and which of it the coded-term
      scan does not look inside. The text is a decision because *what counts as the
      mandated block* decides what is exempt; the exemption list is a decision
      because emptying it re-penalises every compliant JD (HR-104 … HR-107).
    * ``thresholds`` / ``patterns`` / ``qualifications`` / ``action_verbs`` /
      ``markers`` / ``boilerplate`` / ``hay_signals`` / ``comparison`` — every field
      (:data:`_FLAT_SURFACE_FILES`). These are the matchers the validators fire on,
      the weights the Hay estimator scores with, and the thresholds the similarity /
      clustering / drift maths compares against: a regex, a banned phrase, an
      approved verb, a placeholder marker, a points table, a score cutoff. Three of
      them (``patterns.incumbent``, ``patterns.senior_title``,
      ``qualifications.ksa_rank``) feed *blocking* gates, so a change to them is a
      change to the approval bar.
    * ``scoring.yaml`` — the scale, the per-severity penalties, the decay, the
      grade bands.
    * ``coded_terms.yaml`` — each severity tier of the lexicon.
    * ``titles.yaml`` — each restricted title's severity and reserved group, and
      **both** title dimensions in full: the vocabulary (which rungs/rows exist
      *is* the classification policy), the keywords that land a title on each, and
      the **match order** that resolves the overlaps. The seniority ladder is not
      SFU's (HR-059); the functional Application Table is (Part 3.3).
    * ``rule_catalog.yaml`` — each rule's ``default_severity``, **and** the derived
      set of rules that sit at or above a severity floor
      (:attr:`RuleCatalog.rules_by_severity`). Severity is not merely a score
      weight: a rule promoted to the floor's severity starts blocking approval
      through :class:`SeverityFloorGate` without ever being named in a gate's
      ``rule_ids``. That is a second route to blocking, and it is on the surface.

    Pure copy (messages, recommendations, titles, notes, the ``*_labels`` a
    classifier renders) is not on the surface.
    """
    paths: set[str] = {
        # the two derived views of the whole policy: promoting/demoting ANY rule
        # moves the first, flipping ANY gate's overridability moves the second
        "gates.blocking_rule_ids",
        "gates.non_overridable_gate_ids",
        "gates.max_listed",
        "gates.severity_order",
        "gates.grade_order",
    }
    for gate in rules.gates.gates:
        paths.add(f"gates.{gate.gate_id}.overridable")
        if isinstance(gate, BlockingRulesGate):
            paths.add(f"gates.{gate.gate_id}.rule_ids")
        elif isinstance(gate, SeverityFloorGate):
            paths.add(f"gates.{gate.gate_id}.min_severity")
            # ...and the THIRD route to blocking: every rule whose default
            # severity already reaches this floor. Promote a `low` drafting nudge
            # to `high` and it starts blocking approval without appearing in any
            # gate's rule_ids — so the membership of each such tier is registered.
            floor = rules.gates.severity_rank(gate.min_severity)
            paths |= {
                f"rule_catalog.rules_by_severity.{severity}"
                for severity in rules.gates.severity_order
                if rules.gates.severity_rank(severity) >= floor
            }
        elif isinstance(gate, ScoreFloorGate):
            paths.add(f"gates.{gate.gate_id}.min_score")
        elif isinstance(gate, GradeFloorGate):
            paths.add(f"gates.{gate.gate_id}.min_grade")

    # thresholds / patterns / qualifications / action_verbs / markers: every field
    for file_field in _FLAT_SURFACE_FILES:
        rule_file = cast(_RuleFile, getattr(rules, file_field))
        paths |= {
            f"{file_field}.{field}"
            for field in type(rule_file).model_fields
            if field != "version"
        }

    paths |= {
        "scoring.max_score",
        "scoring.min_score",
        "scoring.severity_decay",
        "scoring.fallback_grade",
    }
    paths |= {
        f"scoring.severity_penalty.{sev}" for sev in rules.scoring.severity_penalty
    }
    paths |= {
        f"scoring.grade_bands.{band.grade}.min_score"
        for band in rules.scoring.grade_bands
    }

    paths |= {f"coded_terms.{severity}" for severity, _ in rules.coded_terms.tiers}

    for title in rules.titles.restricted:
        paths.add(f"titles.{title.key}.severity")
        paths.add(f"titles.{title.key}.reserved_for_employee_group")
    # Both title dimensions, in full. Which rungs/rows exist IS the classification
    # policy (a ladder without `lead` cannot classify a lead); the KEYWORDS decide
    # what lands on each; and the MATCH ORDER decides the overlaps — trying
    # `manager` before `director` is the whole reason "Associate Director" is a
    # manager. Shuffle the order and titles change family with no other edit, so
    # the order is on the surface, not just the contents. The seniority half is
    # not SFU's (HR-059); the functional half is (Part 3.3).
    paths |= {
        "titles.families",
        "titles.family_match_order",
        "titles.family_keywords",
        "titles.comma_supervisory_families",
        "titles.functions",
        "titles.function_match_order",
        "titles.function_keywords",
    }

    paths |= {
        f"rule_catalog.{spec.rule_id}.default_severity"
        for spec in rules.rule_catalog.rules
    }
    return frozenset(paths)


def check_register(rules: Rules) -> tuple[str, ...]:
    """Problems that make the register a lie. Empty tuple == in step.

    Three ways the register can rot, all of them build-breaking:

    1. **drift** — a ``current_default`` no longer equals the live value. Someone
       tuned a threshold in YAML and did not tell HR.
    2. **an unregistered parameter** — something on the decision surface is
       neither a register entry nor an explicit ``trivial:`` exemption. Someone
       added a gate/threshold/penalty and never decided whether HR must ratify it.
    3. **a stale exemption** — a ``trivial:`` entry for a path that is not (or is
       no longer) on the decision surface: dead weight that would silently absorb
       a future real decision at the same path.
    """
    problems: list[str] = []
    register = rules.decision_register

    for decision in sorted(register.decisions, key=lambda d: d.id):
        actual = live_value(rules, decision.config.path)
        if actual != decision.current_default:
            problems.append(
                f"{decision.id}: current_default {decision.current_default!r} != live "
                f"{actual!r} at {decision.config}. The config was changed without "
                f"updating the HR decision register."
            )

    surface = decision_surface(rules)
    accounted = register.registered_paths | register.exempt_paths
    for path in sorted(surface - accounted):
        problems.append(
            f"{path} is on the decision surface but is neither a register entry nor "
            f"an explicit `trivial:` exemption in decision_register.yaml."
        )
    for path in sorted(register.exempt_paths - surface):
        problems.append(
            f"{path} is declared trivial but is not on the decision surface — remove "
            f"the stale exemption."
        )
    return tuple(problems)


def assert_register_in_step(rules: Rules) -> None:
    """:func:`check_register`, as a hard failure. Raises :class:`RulesError`."""
    problems = check_register(rules)
    if problems:
        raise RulesError(
            "The HR decision register is out of step with the rules it describes:\n  - "
            + "\n  - ".join(problems)
        )


# --- loading -----------------------------------------------------------------

_FILE_MODELS: Final[tuple[tuple[str, str, type[_RuleFile]], ...]] = (
    ("thresholds.yaml", "thresholds", Thresholds),
    ("action_verbs.yaml", "action_verbs", ActionVerbs),
    ("coded_terms.yaml", "coded_terms", CodedTerms),
    ("qualifications.yaml", "qualifications", Qualifications),
    ("markers.yaml", "markers", Markers),
    ("patterns.yaml", "patterns", Patterns),
    ("titles.yaml", "titles", Titles),
    ("boilerplate.yaml", "boilerplate", Boilerplate),
    ("hay_signals.yaml", "hay_signals", HaySignalRules),
    ("comparison.yaml", "comparison", Comparison),
    ("scoring.yaml", "scoring", Scoring),
    ("rule_catalog.yaml", "rule_catalog", RuleCatalog),
    ("gates.yaml", "gates", GatePolicy),
    (REGISTER_FILE, "decision_register", DecisionRegister),
)

#: Every YAML file that makes up the rulebook, in load order.
RULE_FILES: Final[tuple[str, ...]] = tuple(name for name, _, _ in _FILE_MODELS)

#: The :class:`Rules` fields whose content identifies a validation result — every
#: rule file except the register. See :meth:`Rules.content_hash` for why the
#: register is out: it describes the rules, it does not change what they decide.
_HASHED_FIELDS: Final[tuple[str, ...]] = tuple(
    field for name, field, _ in _FILE_MODELS if name != REGISTER_FILE
)


def _read_text(name: str, directory: Path | None) -> str:
    """Raw YAML text for ``name`` — from the package by default (importlib.
    resources, so no path walking and nothing outside ``core/`` is read), or from
    ``directory`` when one is given (tests supply a scratch copy)."""
    source: Path | Any = (
        importlib.resources.files(_PACKAGE).joinpath(name)
        if directory is None
        else directory / name
    )
    try:
        text = source.read_text(encoding="utf-8")
    except OSError as exc:
        raise RulesError(f"Cannot read rule file {name!r}: {exc}") from exc
    if not isinstance(text, str):  # pragma: no cover - defensive
        raise RulesError(f"Rule file {name!r} did not yield text")
    return text


def _parse_yaml(name: str, text: str) -> dict[str, Any]:
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise RulesError(f"Malformed YAML in rule file {name!r}: {exc}") from exc
    if not isinstance(data, dict):
        raise RulesError(
            f"Rule file {name!r} must contain a YAML mapping, "
            f"got {type(data).__name__}"
        )
    return data


def load_rules(directory: Path | None = None) -> Rules:
    """Parse + validate the rulebook. Uncached — see :func:`get_rules`.

    ``directory`` overrides the packaged YAML (used by tests to exercise
    malformed/invalid data without touching the shipped rules).

    Raises:
        RulesError: a file is missing, its YAML is malformed, or the rule data
            fails validation (unknown key, bad regex, unordered grade bands,
            a severity outside ``JDIssueSeverity``, mismatched versions, ...).
    """
    parsed: dict[str, _RuleFile] = {}
    for name, field, model in _FILE_MODELS:
        raw = _parse_yaml(name, _read_text(name, directory))
        try:
            parsed[field] = model.model_validate(raw)
        except ValidationError as exc:
            raise RulesError(f"Invalid rule data in {name!r}: {exc}") from exc

    versions = {rule_file.version for rule_file in parsed.values()}
    if len(versions) != 1:
        raise RulesError(
            f"Rule files disagree on version: {sorted(versions)}. Every rules YAML "
            f"must be bumped together."
        )

    payload: dict[str, Any] = {"declared_version": versions.pop(), **parsed}
    try:
        return Rules.model_validate(payload)
    except ValidationError as exc:
        raise RulesError(f"Invalid rulebook: {exc}") from exc


@lru_cache(maxsize=1)
def get_rules() -> Rules:
    """The shipped rulebook — parsed once, cached, frozen.

    The single accessor every consumer (validators, gate runner, composer) uses.

    The **shipped** rulebook must also be in step with its HR decision register
    (:func:`assert_register_in_step`): every registered ``current_default`` still
    equals the live value, and no parameter on the decision surface is
    unaccounted for. A JD Bank process whose thresholds have drifted away from
    what HR was told they are is validating against a policy nobody agreed to, so
    it must not start.

    Raises:
        RulesError: the rulebook is malformed, or its register has drifted.
    """
    rules = load_rules()
    assert_register_in_step(rules)
    return rules

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

import importlib.resources
import itertools
import re
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType
from typing import Annotated, Any, Final, Literal, TypeVar, cast, get_args

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

#: Who raises a rule: a deterministic gate here, or the (Phase 5) LLM pass.
RuleOwner = Literal["deterministic", "llm"]

#: The cross-cutting checklist bucket — labelled, but not a template section.
GENERAL_SECTION: Final[SFUSection] = "general"


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


class Titles(_RuleFile):
    """Restricted job titles (``titles.yaml``)."""

    restricted: tuple[RestrictedTitle, ...] = Field(min_length=1)

    @field_validator("restricted")
    @classmethod
    def _keys_are_unique(
        cls, titles: tuple[RestrictedTitle, ...]
    ) -> tuple[RestrictedTitle, ...]:
        keys = [t.key for t in titles]
        if len(set(keys)) != len(keys):
            raise ValueError("restricted title keys must be unique")
        return titles


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
        """Every rule the policy will refuse to approve over ("never approve if…")."""
        return frozenset(
            rule_id
            for gate in self.gates
            if isinstance(gate, BlockingRulesGate)
            for rule_id in gate.rule_ids
        )

    def severity_rank(self, severity: JDIssueSeverity) -> int:
        """``severity``'s rank — higher is worse. Total, by construction."""
        return self.severity_order.index(severity)

    def grade_rank(self, grade: JDGrade) -> int:
        """``grade``'s rank — higher is better. Total, by construction."""
        return self.grade_order.index(grade)


class Rules(BaseModel):
    """The whole validated rulebook — one frozen object, one ``version``."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: str = Field(min_length=1)
    thresholds: Thresholds
    action_verbs: ActionVerbs
    coded_terms: CodedTerms
    qualifications: Qualifications
    markers: Markers
    patterns: Patterns
    titles: Titles
    scoring: Scoring
    rule_catalog: RuleCatalog
    gates: GatePolicy

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


# --- loading -----------------------------------------------------------------

_FILE_MODELS: Final[tuple[tuple[str, str, type[_RuleFile]], ...]] = (
    ("thresholds.yaml", "thresholds", Thresholds),
    ("action_verbs.yaml", "action_verbs", ActionVerbs),
    ("coded_terms.yaml", "coded_terms", CodedTerms),
    ("qualifications.yaml", "qualifications", Qualifications),
    ("markers.yaml", "markers", Markers),
    ("patterns.yaml", "patterns", Patterns),
    ("titles.yaml", "titles", Titles),
    ("scoring.yaml", "scoring", Scoring),
    ("rule_catalog.yaml", "rule_catalog", RuleCatalog),
    ("gates.yaml", "gates", GatePolicy),
)

#: Every YAML file that makes up the rulebook, in load order.
RULE_FILES: Final[tuple[str, ...]] = tuple(name for name, _, _ in _FILE_MODELS)


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

    payload: dict[str, Any] = {"version": versions.pop(), **parsed}
    try:
        return Rules.model_validate(payload)
    except ValidationError as exc:
        raise RulesError(f"Invalid rulebook: {exc}") from exc


@lru_cache(maxsize=1)
def get_rules() -> Rules:
    """The shipped rulebook — parsed once, cached, frozen.

    The single accessor every consumer (validators, gate runner, composer) uses.
    """
    return load_rules()

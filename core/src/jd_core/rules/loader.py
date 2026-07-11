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
import importlib.resources
import itertools
import re
from collections.abc import Mapping, Sequence, Set
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
    """Job-title rules (``titles.yaml``): the restricted phrases SFU reserves,
    and the seniority ladder a title is classified onto.

    ``families`` is **not** rulebook-sourced (see the warning in the YAML and
    HR-059) — it is inherited hris calibration, held here as data so it can be
    changed without touching code, and pinned by the register so it cannot be
    changed without telling HR.
    """

    restricted: tuple[RestrictedTitle, ...] = Field(min_length=1)
    #: Seniority ladder, senior -> junior. The vocabulary of
    #: :class:`~src.jd_core.models.bank.TitleFamily` (plus ``"unmapped"``).
    families: tuple[str, ...] = Field(min_length=1)

    @field_validator("restricted")
    @classmethod
    def _keys_are_unique(
        cls, titles: tuple[RestrictedTitle, ...]
    ) -> tuple[RestrictedTitle, ...]:
        keys = [t.key for t in titles]
        if len(set(keys)) != len(keys):
            raise ValueError("restricted title keys must be unique")
        return titles

    @property
    def by_id(self) -> Mapping[str, RestrictedTitle]:
        """Every restricted title, keyed by its stable ``key``."""
        return _freeze({title.key: title for title in self.restricted})


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
    decision_register: DecisionRegister

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
#: flat tables of matchers and limits — a word list, a regex, a threshold — and
#: every one of them changes what the validators fire on. Enumerating them
#: field-by-field means a new key in any of them is on the surface the moment it
#: is added, with no enumerator change.
_FLAT_SURFACE_FILES: Final[tuple[str, ...]] = (
    "thresholds",
    "patterns",
    "qualifications",
    "action_verbs",
    "markers",
)


def decision_surface(rules: Rules) -> frozenset[str]:
    """Every parameter of the loaded rules that carries a policy judgement.

    Enumerated **from the rules themselves**, not from a hand-kept list — so a
    gate, threshold, regex, word list, penalty, grade band, lexicon tier,
    restricted title or catalogued rule added later shows up here automatically,
    and the coverage check (:func:`check_register`) breaks the build until
    someone says whether HR must decide it.

    **All ten rule files are walked.** The surface is everything that can change
    what the system decides about a JD:

    * ``gates.yaml`` — the approval policy: each gate's overridability and the
      parameter it measures, plus two *derived* views of the policy as a whole
      (:attr:`GatePolicy.blocking_rule_ids`,
      :attr:`GatePolicy.non_overridable_gate_ids`).
    * ``thresholds`` / ``patterns`` / ``qualifications`` / ``action_verbs`` /
      ``markers`` — every field. These are the matchers the validators fire on: a
      regex, a banned phrase, an approved verb, a placeholder marker. Three of
      them (``patterns.incumbent``, ``patterns.senior_title``,
      ``qualifications.ksa_rank``) feed *blocking* gates, so a change to them is a
      change to the approval bar.
    * ``scoring.yaml`` — the scale, the per-severity penalties, the decay, the
      grade bands.
    * ``coded_terms.yaml`` — each severity tier of the lexicon.
    * ``titles.yaml`` — each restricted title's severity and reserved group, and
      the seniority ``families`` ladder (which rungs exist *is* the
      classification policy, and the ladder is not SFU's — HR-059).
    * ``rule_catalog.yaml`` — each rule's ``default_severity``, **and** the derived
      set of rules that sit at or above a severity floor
      (:attr:`RuleCatalog.rules_by_severity`). Severity is not merely a score
      weight: a rule promoted to the floor's severity starts blocking approval
      through :class:`SeverityFloorGate` without ever being named in a gate's
      ``rule_ids``. That is a second route to blocking, and it is on the surface.

    Pure copy (messages, recommendations, titles, notes) is not on the surface.
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
    # The seniority ladder: which rungs exist IS the classification policy (a
    # ladder without `lead` cannot classify a lead), and it is not SFU's — HR-059.
    paths.add("titles.families")

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
    ("scoring.yaml", "scoring", Scoring),
    ("rule_catalog.yaml", "rule_catalog", RuleCatalog),
    ("gates.yaml", "gates", GatePolicy),
    (REGISTER_FILE, "decision_register", DecisionRegister),
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

"""Shared pydantic schemas for the JD quality auditor.

Ported near-verbatim from hris `packages/schemas/src/schemas/jd_quality.py`
(reuse-map #2). The auditor evaluates a *job description* (not a candidate) and
emits evidence-backed improvement suggestions. Two contracts cross package
boundaries:

  - ``JDQualityFindings`` — the LLM output (passed to ``LLMClient.chat_json``)
    for the nuanced pass (subtle bias, clarity). Every finding must cite a
    verbatim quote from the JD, mirroring the Stage-3 evidence rule.
  - ``JDQualityReport`` — the merged, scored result the worker persists to
    ``jd_quality_evaluations`` and the API returns.

Deterministic ("rule") findings are produced in the quality pipeline — same
input, same issues, no model call.
"""

from __future__ import annotations

import datetime as dt
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# The quality dimensions the auditor reports against. ``rule``-sourced issues
# use the structural categories; the LLM pass owns ``inclusive_language`` and
# ``clarity`` (and may also flag ``seniority_mismatch``).
JDIssueCategory = Literal[
    "completeness",  # a mandatory SFU template section is missing
    "structure",  # SFU format: 3-5 action-verb duties, summary length, placeholders
    "qualification_standard",  # SFU quals: modifiers, banned words, equivalent-combo
    "matchability",  # the JD cannot be matched well (e.g. zero required skills)
    "over_specification",  # too many requirements / unrealistic experience bar
    "keyword_stuffing",  # required >> nice-to-have -> pushes literal matching
    "seniority_mismatch",  # implied-experience / JD-omission risk (charter)
    "inclusive_language",  # coded / gendered / exclusionary phrasing
    "clarity",  # vague, ambiguous, or undefined requirements
]
JDIssueSeverity = Literal["info", "low", "medium", "high"]
JDIssueSource = Literal["rule", "llm"]
JDGrade = Literal["A", "B", "C", "D", "F"]

# The two document templates in the SFU archive. They are different FORMS, not
# variants: `jdfn` is the APSA/APEX/POLY job-description form the validator was built
# against; `wjq` is the CUPE 3338 Weighted Job Questionnaire, a 14-section point-factor
# instrument with sections the other does not have (and lacking sections the other
# requires). A rule declares which of them it can judge — see `RuleSpec.applies_to`.
#
# ⚠ Measured over the live archive: four rules fired on 100% of CUPE documents purely
# because the WJQ form does not contain the sections they check. A rule that cannot NOT
# fire is a constant subtracted from every score, not a quality signal.
JDTemplate = Literal["jdfn", "wjq"]

#: The value of ``employee_group`` that designates a WJQ document. The WJQ segmenter
#: sets it unconditionally and ``ParseResult.template`` is not persisted, so this is the
#: JDFN/WJQ separator of record — with complete WJQ recall.
WJQ_EMPLOYEE_GROUP = "cupe"

#: The template a document is judged as when its group says nothing. JDFN is the older,
#: larger form and the one the shipped bar was calibrated on.
DEFAULT_TEMPLATE: JDTemplate = "jdfn"

# The SFU JD template's sections, in template order, plus a cross-cutting
# "general" bucket for whole-document findings (inclusive language, placeholders,
# LLM findings that don't map to one section). Drives the section-grouped
# checklist; labels + ordering + the rule->section map live in the rule catalog.
SFUSection = Literal[
    "about_sfu",
    "identification",
    "position_summary",
    "duties",
    "decision_making",
    "problem_solving",
    "relationships",
    "qualifications",
    "edi_footer",
    "additional_context",
    "general",
]


class JDQualityIssue(BaseModel):
    """One merged finding (rule- or LLM-sourced) on a job description."""

    model_config = ConfigDict(extra="forbid")

    category: JDIssueCategory
    severity: JDIssueSeverity
    source: JDIssueSource
    message: str = Field(min_length=1, max_length=500)
    suggestion: str = Field(default="", max_length=500)
    # A verbatim quote from the JD supporting the finding. None for derived
    # structural findings (e.g. "no responsibilities listed") that have no
    # single span to quote.
    evidence: str | None = Field(default=None, max_length=500)
    # Stable id of the deterministic gate that raised this (e.g. "SFU-COMP-SUMMARY").
    # None for LLM-sourced findings. Lets the UI and tests reference gates by id
    # and cite the guide section they enforce.
    rule_id: str | None = Field(default=None, max_length=64)


# ---------- LLM output schema (nuanced pass) ----------


class JDQualityFinding(BaseModel):
    """One issue as the LLM returns it. ``source`` is set to ``"llm"`` when
    merged into a :class:`JDQualityIssue`, so it is not part of the LLM
    contract here."""

    model_config = ConfigDict(extra="ignore")

    category: JDIssueCategory
    severity: JDIssueSeverity = "medium"
    message: str = Field(min_length=1, max_length=500)
    suggestion: str = Field(default="", max_length=500)
    evidence: str | None = Field(default=None, max_length=500)


class JDQualityFindings(BaseModel):
    """Strict schema the LLM must return for the nuanced quality pass.

    Drives ``LLMClient.chat_json`` — extras dropped, types coerced where
    sensible.
    """

    model_config = ConfigDict(extra="ignore")

    issues: list[JDQualityFinding] = Field(default_factory=list, max_length=20)


# ---------- section-grouped checklist ----------


class JDChecklistSection(BaseModel):
    """One SFU-template section's slice of the audit: its findings (possibly
    none) plus a rolled-up status. Derived from the flat ``issues`` list by the
    rule catalog's ``build_checklist`` — a presentation view, not a second
    source of truth, so it is not persisted separately."""

    model_config = ConfigDict(extra="forbid")

    section: SFUSection
    label: str
    status: Literal["ok", "issues"]
    issues: list[JDQualityIssue] = Field(default_factory=list)


# ---------- approval gates: "never approve if…" ----------


class GateReason(BaseModel):
    """One approval gate that is blocking, and why — in rulebook terms.

    Machine-readable (``gate_id``, ``rule_ids``, ``overridable``) so the UI and
    the audit log can act on it, and human-readable (``reason``, rendered from the
    gate's copy in ``rules/gates.yaml``) so a reviewer can see what to fix. The
    ``source_part`` cites the SFU guide part the gate enforces.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    gate_id: str = Field(min_length=1, max_length=64)
    source_part: str = Field(min_length=1)  # e.g. "Part 11.6"
    reason: str = Field(min_length=1)
    # The catalogued rules that tripped the gate. Empty for a gate measuring a
    # roll-up (score / grade), or one tripped only by rule-less LLM findings.
    rule_ids: tuple[str, ...] = ()
    # Verbatim JD spans the offending findings quoted, bounded by the policy's
    # ``max_listed``.
    evidence: tuple[str, ...] = ()
    # May an HR reviewer waive this gate (always: only with a written reason)?
    overridable: bool


class GateOverride(BaseModel):
    """A reviewer's waiver of one *overridable* blocking gate.

    CLAUDE.md non-negotiable #1: an override REQUIRES a written reason. That is
    not a check performed somewhere — an override without a reason (or with a
    whitespace one, or with no named reviewer) is **unrepresentable**: this model
    will not construct. Phase 4 persists these to the append-only audit log.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    gate_id: str = Field(min_length=1, max_length=64)
    reviewer: str = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=1, max_length=500)

    @field_validator("reviewer", "reason")
    @classmethod
    def _is_written(cls, value: str) -> str:
        written = value.strip()
        if not written:
            raise ValueError("must not be blank: an override requires a written reason")
        return written


class GateDecision(BaseModel):
    """Whether an HR reviewer may be shown the approve button, and why not.

    **This is not an approval.** ``approved=True`` means only that approval is
    *permitted* — nothing auto-publishes (CLAUDE.md #1); a human still decides.
    ``approved=False`` means the button is disabled, and every ``blocking`` reason
    says which rulebook part disabled it.

    The two states are kept in step by construction: an "approved" decision that
    still carries blockers — or a blocked one that carries none — cannot be built.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    approved: bool
    blocking: tuple[GateReason, ...] = ()
    # Gates a reviewer waived, each with its written reason (see GateOverride).
    overridden: tuple[GateOverride, ...] = ()

    @model_validator(mode="after")
    def _approval_means_nothing_is_blocking(self) -> GateDecision:
        if self.approved and self.blocking:
            raise ValueError(
                "a decision cannot be approvable while gates are still blocking: "
                f"{[r.gate_id for r in self.blocking]}"
            )
        if not self.approved and not self.blocking:
            raise ValueError("a blocked decision must say which gate(s) block it")
        return self


# ---------- persisted / API response ----------


class JDQualityReport(BaseModel):
    """The merged, scored auditor result for one job description.

    Persisted to ``jd_quality_evaluations`` (one row per run — history kept)
    and returned by ``GET /api/v1/jobs/{id}/quality``. The version stamps make
    every score reconcilable to the exact rules + prompt + model that produced
    it.
    """

    model_config = ConfigDict(extra="forbid")

    job_id: UUID
    overall_score: float = Field(ge=0, le=100)
    grade: JDGrade
    issue_count: int = Field(ge=0)
    issues: list[JDQualityIssue] = Field(default_factory=list)
    # The same findings regrouped into the SFU section-by-section checklist
    # (all 10 template sections, clean ones marked "ok"). Derived from ``issues``
    # at build/read time — default empty so old persisted rows (which store only
    # ``issues``) still parse; the read path recomputes it.
    checklist: list[JDChecklistSection] = Field(default_factory=list)
    # Whether the rulebook permits an HR reviewer to approve this JD at all, and
    # if not, which gates block it. Derived from ``issues`` + score + grade under
    # the versioned gate policy — like ``checklist``, recomputed on read, so it
    # defaults to None for rows written before the gate runner existed.
    gate_decision: GateDecision | None = None
    model: str
    prompt_version: str
    rules_version: str
    generated_at: dt.datetime


# ---------- corpus leaderboard ----------


class JDQualityCorpusRow(BaseModel):
    """One job's latest audit, for the corpus leaderboard. title/department are
    joined from ``jobs`` at read time (the source of truth — they can change
    since the run)."""

    model_config = ConfigDict(extra="forbid")

    job_id: UUID
    title: str
    department: str | None = None
    overall_score: float = Field(ge=0, le=100)
    grade: JDGrade
    issue_count: int = Field(ge=0)
    generated_at: dt.datetime


class JDQualityCorpusSummary(BaseModel):
    """Corpus-wide quality snapshot returned by ``GET /jd-quality/corpus``.

    ``rows`` is the latest audit per job, worst-first, capped by the request
    limit; the counts span the whole corpus so the dashboard's headline numbers
    are not truncated by the row cap.
    """

    model_config = ConfigDict(extra="forbid")

    total_parsed: int = Field(ge=0)  # jobs with an extracted JD (auditable)
    evaluated: int = Field(ge=0)  # jobs with >= 1 audit
    not_evaluated: int = Field(ge=0)  # parsed jobs never audited
    grade_counts: dict[JDGrade, int] = Field(default_factory=dict)
    rows: list[JDQualityCorpusRow] = Field(default_factory=list)

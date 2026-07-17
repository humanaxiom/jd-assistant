"""JD Bank value objects — similarity, harmonization, Hay signals, title, drift.

Ported from hris ``packages/schemas/src/schemas/jd_bank.py`` (reuse-map #3,
ADR-005: *"EXTRACT the value objects; trim hris-persistence fields to match JD
Bank's own tables"*). These are the pure in-memory contracts the bank pipeline
produces and consumes; nothing here is a row.

**What was trimmed, and why.** hris kept its DB lifecycle *in* the pydantic
models. JD Bank already models that lifecycle in SQLAlchemy
(``src/jd_bank/db/models.py``), so carrying it here too would be a second,
drifting source of truth:

* ``CanonicalRole.{id, cluster_id, status, approved_by, approved_at}`` → the
  ``canonical_jds`` row (id / cluster_id / ``CanonicalStatus``) and the
  ``review_actions`` row (reviewer_id / created_at). hris's status vocabulary
  (proposed/approved/retired) also *conflicts* with JD Bank's
  ``CanonicalStatus`` (draft/published/archived) — keeping it would make the
  approval state ambiguous, and approval is non-negotiable #1.
* ``CanonicalRole.{model, prompt_version, rules_version, sim_version,
  generated_at}`` → provenance belongs to the persisted row
  (``canonical_jds.change_log`` / ``.source_document_ids`` /
  ``.validation_report_id``, ``validation_reports.rules_version``) and the
  append-only ``audit_log``, not to a value object that is recomputed on every
  harmonization run. What is left is exactly the *proposal*: the drafted JD, its
  provenance-by-frequency, its members, and its quality roll-up.
* **The whole API layer.** The rule is about *shape*, not about where hris
  happened to call the constructor: *envelopes and read-models — types shaped by
  hris's own routes and tables — are dropped; the value objects the pipeline
  computes are kept.* (The narrower "constructed only in ``apps/api``" test would
  be wrong: by it, ``CanonicalRole`` — the harmonizer's headline output — would
  have to go too. Do not apply it.) That drops every request/response envelope
  and read-model in one stroke: ``JDSimilarResult``, ``JDCluster{Row,Report,Member,
  Detail}``, ``BankHealth``/``BankHealthSnapshot``, ``CanonicalMember``/
  ``CanonicalMembersResult``, ``JobCanonicalLink``, ``CanonicalApproveRequest``
  **and** ``CanonicalMemberRequest`` (+ ``CanonicalLinkType``). They are shaped
  by hris's tables and routes: JD Bank's equivalents are ``clusters`` /
  ``dedup_edges`` / ``canonical_jds``, its approval path is ``ReviewAction`` +
  :class:`~src.jd_core.models.quality.GateDecision` /
  :class:`~src.jd_core.models.quality.GateOverride`, and it has no membership-
  link table at all — so ``CanonicalMemberRequest``'s ``link_type`` (defaulting
  to ``"confirmed"``) would be an unregistered *policy default* describing a
  persistence model that does not exist. The envelopes belong to the
  REWRITE-tier service layer, and get written when it does.
* ``HayGrade`` / ``HayGradeMapping``, and ``HaySignals.{grade, grade_mapped}``
  → **source-gated**: SFU publishes no Hay point charts, and classification is a
  human Compensation decision. Nothing in this repo may assign a Hay grade, so a
  graded signal is made *unrepresentable* rather than merely unused.

Everything else is a faithful transcription of the hris field set (bounds,
defaults, ``extra="forbid"``) — same behaviour, same validation.

**Decision parameters.** Every *number* below is a bound on a value someone else
computes (0–1 scores, 0–100 quality score, list caps), not a threshold anyone
tunes. But two *vocabularies* here are policy calls wearing a type's clothes:
:data:`TitleFamily` (the seniority ladder, which hris passed off as SFU's and which
is not in the rulebook — HR-059) and :data:`TitleFunction` (SFU's Application
Table, which *is* — HR-063). Both are DATA (``rules/titles.yaml``); the Literals
below are only their type mirrors, and the loader + ``tests/unit/test_bank_models``
pin the two together in both directions. Read the warnings above them before
touching them. The keywords and the *match order* that drive the classification are
data too (HR-060 … HR-065) — see ``bank/title_family.py``.

The Hay *calibration* (lexicons, weights, level cutoffs) is likewise data
(``rules/hay_signals.yaml``, HR-066 … HR-081). What is deliberately absent from
this module is any way to express a Hay **grade** — see :class:`HaySignals`.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from src.jd_core.models.parsed_jd import SFUJobDescription
from src.jd_core.models.quality import JDGrade

# ---------- similarity: the "Similar roles" surface ----------

# clone     -> looks like a true clone (no re-evaluation needed)
# new_job   -> materially different (different title/department) -> needs Hay eval
# uncertain -> similar but not conclusive either way; a human should look
JDCloneVerdict = Literal["clone", "new_job", "uncertain"]


class JDSimilarNeighbour(BaseModel):
    """One JD that resembles the source role. title/department are joined from
    the JD's own record at read time (they can change)."""

    model_config = ConfigDict(extra="forbid")

    job_id: UUID
    title: str
    department: str | None = None
    score: float = Field(ge=0, le=1)  # overall similarity (0-1), title-agnostic
    vector_score: float = Field(ge=0, le=1)  # summary-embedding cosine component
    skill_overlap: float = Field(ge=0, le=1)  # ontology-aware skill-set component
    same_department: bool  # within-dept (overlap risk) vs across-dept redundancy
    same_title: bool  # exact (normalized) title match
    clone_verdict: JDCloneVerdict
    verdict_basis: list[str] = Field(default_factory=list)  # human-readable "why"


# ---------- harmonization: canonical roles ----------


class SkillFrequency(BaseModel):
    """How many of a cluster's members require a given skill (provenance)."""

    model_config = ConfigDict(extra="forbid")

    name: str
    members: int = Field(ge=1)


class CanonicalRole(BaseModel):
    """A harmonized, SFU-template-shaped JD *proposed* for a cluster of
    near-duplicate roles — the harmonizer's output, before anything is persisted
    or approved.

    Descriptive, never authoritative: a human approves it later (non-negotiable
    #1), and that approval, its lineage and its version stamps are recorded on
    the ``canonical_jds`` / ``review_actions`` / ``audit_log`` rows — see the
    trim notes in the module docstring. What travels here is only what the
    harmonization *computed*: the drafted JD, the skill frequencies that justify
    it, the members it was drawn from, and the SFU auditor's roll-up.
    """

    model_config = ConfigDict(extra="forbid")

    title: str
    jd: SFUJobDescription
    skill_frequency: list[SkillFrequency] = Field(default_factory=list)
    member_job_ids: list[UUID] = Field(default_factory=list)
    grade: JDGrade
    overall_score: float = Field(ge=0, le=100)
    issue_count: int = Field(ge=0)


# ---------- harmonization: the deterministic merge engine (Phase 4.1) ----------


class MergeProvenance(BaseModel):
    """Verifiable provenance for one harmonized draft — computed BEFORE any model
    touches the text (Phase 4.1). Frozen: it is an audit record, not a scratchpad.

    Every member index here is a position in the engine's OWN canonical member
    ordering (members sorted by content), never the caller's input order — that is
    what lets :func:`~src.jd_core.bank.merge.merge_cluster` promise a byte-identical
    draft + provenance for the same set of members in any order.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    #: How many member JDs fed this draft.
    member_count: int = Field(ge=1)
    #: ``(skill, members_requiring_it)`` most-common-first — from
    #: :func:`~src.jd_core.bank.provenance.skill_frequency`.
    skill_frequency: tuple[tuple[str, int], ...] = ()
    #: A deduped duty statement -> the number of distinct members it was drawn from.
    duty_coverage: tuple[tuple[str, int], ...] = ()
    #: Which member indices fed each chosen scalar/text section: ``(section, indices)``.
    section_contributors: tuple[tuple[str, tuple[int, ...]], ...] = ()
    #: HR-eyeball flags (never an auto-fix): ``grade_disagreement``,
    #: ``employee_group_disagreement``, ``duties_over_max``, ``no_core_skills``,
    #: ``single_member``, and ``sections_not_merged`` (a member carried content in a
    #: section 4.1 does not merge — decision_making / problem_solving / relationships /
    #: position_number — so the draft dropped it; the 4.4 reviewer is told, not
    #: surprised). Kept as an open, extensible tuple.
    flags: tuple[str, ...] = ()


class MergedRole(BaseModel):
    """A cluster harmonized into a single **draft** JD + its provenance.

    Non-negotiable #1: the draft is NOT approved and NOT canonical — it is the pure,
    attributable starting point a human reviewer (4.4) and the LLM rewrite pass (4.2)
    act on. Nothing here publishes anything.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    #: The harmonized draft (a plain ``SFUJobDescription`` — a draft, never canonical).
    draft: SFUJobDescription
    provenance: MergeProvenance


# ---------- Hay-factor signals (advisory — NEVER a grade) ----------

HAY_SIGNALS_VERSION = "hay_signals_v1"

HaySignalLevel = Literal["low", "moderate", "high"]
HayFactor = Literal["know_how", "problem_solving", "accountability"]


class HayFactorSignal(BaseModel):
    """One SFU-Hay factor's ADVISORY signal, estimated from JD text. A
    directional low/moderate/high signal to help Compensation *level* a role —
    NEVER a Hay grade or point score. The Hay charts are proprietary and
    classification is a human Compensation decision; this only surfaces what the
    JD's own sections imply, with the phrases that drove it."""

    model_config = ConfigDict(extra="forbid")

    factor: HayFactor
    level: HaySignalLevel
    rationale: str = Field(max_length=400)  # short, human-readable why
    evidence: list[str] = Field(default_factory=list, max_length=12)  # JD phrases


class HaySignals(BaseModel):
    """The three SFU-Hay factor signals for a JD / canonical role. Advisory only,
    version-stamped, with an explicit 'not a grade' contract.

    hris carried an ingested ``grade`` here (source-gated on an approved SFU
    value). SFU publishes no point charts, so JD Bank does not model a Hay grade
    at all: there is no field to put one in, and no code path that could infer
    one. 'Unmapped' is not a state to render — it is the only state there is.
    """

    model_config = ConfigDict(extra="forbid")

    know_how: HayFactorSignal
    problem_solving: HayFactorSignal
    accountability: HayFactorSignal
    version: str = HAY_SIGNALS_VERSION


# ---------- title-family mapping ----------

# The seniority ladder a title is classified onto, senior -> junior. "unmapped"
# is an explicit, visible state.
#
# ⚠ NOT SFU-PUBLISHED. hris's schema called this "SFU's official title ladder
# (Toolkit p18-19)"; that claim does not survive checking. There is no title
# ladder in docs/rulebook/sfu-jd-standards.txt — `chief` never appears in it, and
# the one "VP" (Part 3.5) is a RESTRICTED title, not a family. It is inherited
# hris calibration, nobody at SFU has ratified it, and it is registered `open` as
# **HR-059**. The rungs themselves are DATA (``rules/titles.yaml :: families``);
# this Literal is only the type vocabulary, and a test pins the two together.
TitleFamily = Literal[
    "vp", "chief", "director", "manager", "lead", "associate", "assistant", "unmapped"
]


class TitleFamilyResult(BaseModel):
    """The SFU title family a canonical role maps to, from its title (+ whether
    it supervises). Advisory — helps standardize titling + compare like roles;
    the numeric Hay grade stays out of scope (proprietary)."""

    model_config = ConfigDict(extra="forbid")

    family: TitleFamily
    label: str  # human-readable family name, e.g. "Manager / Supervisor"
    rationale: str = Field(max_length=300)
    matched_on: str | None = None  # the title keyword that drove the match


# The functional "Application Table" (Learning Series Part 3.3) — a SECOND
# dimension distinct from the seniority ladder: what the title *word* means.
#
# Unlike the ladder above, this table IS SFU's: it is transcribed from the rulebook
# (Part 3.3), so its provenance is `sfu_rulebook` (HR-063). That makes it *better
# sourced*, not less of a rule: the rows, their keywords and the order they are
# matched in are DATA (``rules/titles.yaml :: functions`` / ``function_keywords`` /
# ``function_match_order``) and this Literal is only their type mirror. `Titles`
# types the YAML field as `tuple[TitleFunction, ...]`, so a row in the YAML that
# this Literal does not know about fails to LOAD; `tests/unit/test_bank_models.py`
# pins the other direction.
TitleFunction = Literal[
    "assistant",
    "coordinator",
    "analyst",
    "officer",
    "specialist",
    "consultant",
    "manager",
    "associate_director",
    "director",
    "executive",
    "unmapped",
]


class TitleFunctionResult(BaseModel):
    """The functional title type a role maps to (SFU Job-Title Application
    Table). Complements the seniority family: e.g. "Data Analyst" -> family
    ``unmapped`` (no ladder keyword) but function ``analyst``. Advisory."""

    model_config = ConfigDict(extra="forbid")

    function: TitleFunction
    label: str  # e.g. "Analyst — analysis & research"
    matched_on: str | None = None


class TitleClassification(BaseModel):
    """A canonical role's title on both SFU dimensions: the seniority **family**
    (Titling Guide ladder) and the functional **function** (Application Table),
    plus whether the title's *format* signals supervision (the "Role, Descriptor"
    comma rule, Series Part 3.4). Advisory."""

    model_config = ConfigDict(extra="forbid")

    family: TitleFamilyResult
    function: TitleFunctionResult
    comma_supervisory: bool = False  # title format ("Manager, X") implies supervision


# ---------- comparison signals: the ParsedJD -> JobSignals adapter (Phase 3.4a) ----


class CanonicalTitle(BaseModel):
    """A title reduced to the comparison-ready anchors: its normalized stem, both SFU
    title dimensions, the comma-format supervision signal, and whether it uses an
    SFU-reserved phrase. Produced by :func:`~src.jd_core.bank.signals.canonical_title`
    from ``similarity.normalize_title`` + ``title_family.classify_title`` +
    ``titles.yaml :: restricted``. Advisory, like the classifiers it composes."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    raw: str
    normalized: str  # normalize_title stem — seniority/level markers dropped
    family: TitleFamily
    function: TitleFunction
    comma_supervisory: bool = False  # "Manager, X" format implies supervision
    restricted: bool = False  # uses an SFU-reserved title phrase (Part 3.5)


class JobSignals(BaseModel):
    """The single comparison-feature object Tier-3 / drift / clustering consume, derived
    from a parsed SFU JD by :func:`~src.jd_core.bank.signals.build_job_signals`.

    :attr:`skills` is a **keyword bag, not a canonical skill set** (ADR-007): lowercase
    tokens from the ``skill``/``knowledge``/``ability`` qualifications minus a measured
    stopword list, with idf-weighting deferred to Phase 3.4b. It is ``frozenset()`` for
    the ~41% of archive JDs that carry no qualifications at all — an honest, registered
    consequence, not a bug. The seniority signals (:attr:`education_ordinal`,
    :attr:`experience_years`, :attr:`supervisory_reports`) are ``None`` when the JD
    states no readable value; a missing signal never manufactures similarity/drift."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    skills: frozenset[str]  # keyword bag (NOT an ontology); empty when no quals
    education_ordinal: int | None  # index on comparison.education_ladder
    experience_years: int | None
    supervisory_reports: int | None
    title: str
    normalized_title: str
    family: TitleFamily
    function: TitleFunction
    comma_supervisory: bool
    restricted: bool
    employee_group: str | None = None
    department: str | None = None


# ---------- drift detection (advisory) ----------

DriftLevel = Literal["aligned", "minor", "major"]


class JobDriftReport(BaseModel):
    """How far a posting has diverged from the canonical role it is linked to
    (skill-set drift). Advisory — flags a posting worth a second look at review
    time; it blocks nothing."""

    model_config = ConfigDict(extra="forbid")

    job_id: UUID
    canonical_role_id: UUID
    canonical_title: str
    level: DriftLevel
    # skill-set Jaccard distance (0 identical, 1 disjoint)
    drift_score: float = Field(ge=0, le=1)
    added: list[str] = Field(default_factory=list)  # skills the posting added
    dropped: list[str] = Field(default_factory=list)  # canonical skills dropped
    reasons: list[str] = Field(default_factory=list)  # why "major" beyond churn
    shared_count: int = Field(ge=0)

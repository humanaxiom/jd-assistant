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
from src.jd_core.models.quality import JDGrade, JDQualityFinding, JDQualityIssue

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


class SeniorityBarChoice(BaseModel):
    """How ONE seniority bar — education or experience — was chosen for a cluster.

    **The reviewer problem this exists for.** ``seniority_bar_policy`` (HR-175,
    ``max`` today) raises a draft's education bar to the highest any single member
    stated. That is defensible and it is *invisible*: a reviewer reads "a master's
    degree" with nothing to say that nine of ten sources said bachelor's. The human
    is the NN #1 control and cannot rule on what they cannot see, so the merge
    records the choice rather than only making it.

    Advisory and descriptive: nothing here changes the draft, and no threshold is
    involved — ``disagreed`` is a property of the members' own statements, not a
    tunable. It therefore earns no register entry.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["education", "experience"]
    #: The live ``seniority_bar_policy`` this choice was made under, echoed so the
    #: record cannot drift from the policy actually applied.
    policy: str
    #: The chosen bar — an education ordinal, or a count of years.
    chosen: int
    #: What each member stated, in the engine's own canonical member order. ``None``
    #: means the member stated **no bar at all**, which is deliberately distinct from
    #: stating a lower one: silence is not dissent.
    member_bars: tuple[int | None, ...] = ()

    @property
    def agreeing(self) -> int:
        """How many members stated exactly the bar that was chosen."""
        return sum(1 for bar in self.member_bars if bar == self.chosen)

    @property
    def overruled(self) -> int:
        """How many members stated a DIFFERENT bar and were overruled by the policy.

        Members that stated nothing are excluded — they were not overruled, they
        simply said nothing, and counting them would overstate the disagreement the
        reviewer is being asked to weigh.
        """
        return sum(
            1 for bar in self.member_bars if bar is not None and bar != self.chosen
        )

    @property
    def disagreed(self) -> bool:
        """Did any member state a bar other than the one that was chosen?

        This is what decides whether the reviewer is shown a "sources disagreed"
        note. A count, not a threshold — there is nothing here to tune.
        """
        return self.overruled > 0


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
    #: ``single_member``, and ``sections_not_merged`` (a member carried member-level
    #: content the DRAFT did not keep, so the 4.4 reviewer is told rather than
    #: surprised). Since HR-210…HR-212 that is a diff against the draft, not a fixed
    #: section list: ``position_number`` is never merged and always counts, while
    #: ``decision_making`` / ``problem_solving`` / ``relationships`` count only what
    #: their policies dropped. Kept as an open, extensible tuple.
    flags: tuple[str, ...] = ()
    #: How the education / experience bars were chosen, and what the members actually
    #: stated (P1.2). Defaults to empty so a ``change_log`` packet written before this
    #: field existed still round-trips through this model.
    seniority_bars: tuple[SeniorityBarChoice, ...] = ()


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


# ---------- harmonization change-log / per-source diff (Phase 4.3) ----------

#: Why a piece of member content is absent from the harmonized draft. Every value is a
#: DROP the merge (or the optional rewrite scrub) actually made, never a policy verdict:
#: ``duty_deduplicated`` — a member duty folded onto another member's near-identical
#: representative; ``duty_dropped_over_max`` — a member duty the ``max_duties`` cap
#: dropped (only reachable when the ``duties_over_max`` flag is set);
#: ``section_not_merged`` — member-level section content the harmonized draft did not
#: keep (``position_number``, which 4.1 never merges, plus whatever the HR-210…HR-212
#: policies dropped for ``decision_making`` / ``problem_solving`` / ``relationships``);
#: and
#: ``qualification_scrubbed_ungrounded`` — a rewrite-stage qualification the guard
#: dropped as ungrounded (not tied to a member).
RemovedReason = Literal[
    "duty_deduplicated",
    "duty_dropped_over_max",
    "section_not_merged",
    "qualification_scrubbed_ungrounded",
    # The two REWRITE-stage removals (2026-08-19 review, S-2 / HR-208). The four above
    # are all things the deterministic MERGE did; these are the first the LLM pass did,
    # and their absence is why a rewrite that deleted nine of twelve duties produced a
    # change log reading `removed: []`.
    "duty_removed_by_rewrite",
    "qualification_bar_restored",
]


class RemovedContent(BaseModel):
    """One piece of member content the harmonization dropped, with the reason — so
    nothing vanishes silently (non-negotiable #6). Frozen: an audit artifact."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    #: The dropped content, verbatim.
    content: str
    #: Why it is not in the draft (see :data:`RemovedReason`).
    reason: RemovedReason
    #: The canonical member index it came from, or ``None`` for a rewrite-stage scrub
    #: not tied to any single member.
    member_index: int | None = None


class SourceContribution(BaseModel):
    """How ONE cluster member fed the harmonized draft: which scalar/text sections it
    contributed, and which of its duties survived vs were folded/dropped. Frozen.

    ``member_index`` is the merge's OWN canonical member index (the same order
    :class:`MergeProvenance.section_contributors` uses), never the caller's input
    order — so this and the provenance point at the same member.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    #: Position in the merge's canonical member ordering.
    member_index: int
    #: This member's own title (the source, not the merged draft's title).
    title: str
    #: Scalar/text sections this member fed (from ``section_contributors``).
    contributed_sections: tuple[str, ...] = ()
    #: This member's duty statements that survived VERBATIM as a draft duty.
    duties_kept: tuple[str, ...] = ()
    #: This member's duty statements that did NOT survive verbatim (folded onto another
    #: member's representative, or dropped by the ``max_duties`` cap).
    duties_folded_or_dropped: tuple[str, ...] = ()


class HarmonizationDiff(BaseModel):
    """The legibility artifact for one harmonized draft (Phase 4.3): the rendered
    draft, the per-source contribution breakdown, and the "removed content and why"
    change log.

    Descriptive, never a decision (non-negotiable #1): there is NO approval /
    canonical / published / score field. Pure + deterministic + order-invariant — the
    same cluster in any input order yields a byte-identical diff. Frozen: an audit
    artifact.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    #: The draft rendered to text for human display (``render_sfu_jd_text`` — display
    #: only, never re-parsed).
    rendered_draft: str
    #: One entry per member, in canonical order.
    per_source: tuple[SourceContribution, ...] = ()
    #: Every dropped piece of member content, with its reason.
    removed: tuple[RemovedContent, ...] = ()
    #: Rewrite-stage duties FLAGGED (low overlap) — kept in the draft, surfaced for the
    #: reviewer. Flagged ≠ removed: a flagged duty is NOT in :attr:`removed`.
    flagged_duties: tuple[str, ...] = ()


# ---------- LLM rewrite pass (Phase 4.2a) — still a DRAFT ----------


class AntiFabricationRecord(BaseModel):
    """What the rewrite's anti-fabrication guard scrubbed / flagged (Phase 4.2a).

    The rewrite may REPHRASE the grounded 4.1 draft but may not INTRODUCE skills, duties
    or qualifications the draft did not contain. This record is the audit trail of that
    guard: every ungrounded qualification it DROPPED, and every duty it FLAGGED
    (recorded, never dropped — a duty may rephrase, so a low-overlap duty is
    an HR eyeball). Frozen: it is evidence, not a scratchpad.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    #: Whether the guard ran (``rewrite.anti_fabrication_enabled``). When ``False`` the
    #: model's output ships unscrubbed and both lists below are empty — recorded so a
    #: disabled guard is visible in the draft's own provenance.
    enabled: bool = True
    #: The text of every rewritten qualification DROPPED as ungrounded in the draft.
    scrubbed_skills: tuple[str, ...] = ()
    #: The statement of every rewritten duty FLAGGED (no token overlap to a draft duty),
    #: kept in the draft, surfaced for the 4.4 human reviewer.
    flagged_duties: tuple[str, ...] = ()
    #: The statement of every duty DROPPED because the grounded draft had NO duties at
    #: all, so there was nothing to reword and every duty returned was an invention
    #: (HR-213). Distinct from :attr:`flagged_duties` on purpose: a flagged duty drifted
    #: from a real one and stays in the draft for a human to judge; these had no source
    #: to drift from. **Measured on the live Bank 2026-08-22: 1,219 such duties across
    #: 153 drafts**, 996 of them on the CUPE cohort, produced because the WJQ parser
    #: recovers no duties from 16.2% of CUPE documents and the rewrite filled the
    #: silence.
    invented_duties: tuple[str, ...] = ()
    #: The name of every SECTION emptied because the grounded draft did not have one —
    #: ``decision_making`` / ``problem_solving`` / ``relationships`` (CUPE Phase D).
    #: A whole section is a coarser unit than a skill, and the coarsest fabrication:
    #: the WJQ form has no Problem Solving section at all, so a rewrite that writes one
    #: is not embellishing a role, it is answering a question the source document was
    #: never asked. Recorded rather than silently dropped — like the other two lists,
    #: this is evidence a reviewer can see.
    scrubbed_sections: tuple[str, ...] = ()
    #: The statement of every MERGE-draft duty the rewrite did not return a counterpart
    #: for (2026-08-19 review, S-2). The three lists above all answer "what did the
    #: model ADD?"; this is the first that answers "what did it TAKE AWAY?", and it is
    #: the question that was never asked. Measured on a real 12-duty CUPE draft: the
    #: model returned three, and the result was grade B, 89.05, with zero duty findings
    #: and an empty record — most of a role gone, and the artifact whose entire purpose
    #: is "nothing vanishes silently" reporting nothing. A duty counts as removed when
    #: its best token-Jaccard against every rewritten duty falls below
    #: ``rewrite.duty_flag_threshold``, the same bar the flag direction uses.
    removed_duties: tuple[str, ...] = ()
    #: The text of every education / experience / security qualification the model
    #: returned and the guard DISCARDED, having restored the merge draft's own
    #: (HR-208). Those three kinds are structural hiring BARS the 4.1 merge derives from
    #: member signals, not free-text competencies — and an invented hiring bar is the
    #: highest-consequence fabrication an HR system can make, because it is the thing
    #: that screens a candidate out. Recorded so the swap is evidence, not a silent fix.
    restored_bars: tuple[str, ...] = ()
    #: The name of every SECTION the merge GROUNDED and the rewrite returned EMPTY,
    #: whose merge value was restored (HR-214). The exact mirror of
    #: :attr:`scrubbed_sections`: that answers "what did the model INVENT?", this one
    #: "what did it DELETE?" — and only the first question was ever asked.
    #: `_SECTIONS_NEVER_INVENTED` fired solely on empty -> non-empty, and its comment
    #: claimed the other direction "drops nothing a source document stated", which is
    #: false. **MEASURED 2026-08-23 over the 50 clusters the v5 producer pass processed
    #: before it was stopped: the merge grounded `relationships` for 43 and 11 drafts
    #: came back without it — 25.6% — while ZERO sections were created.** The guard was
    #: working perfectly, on the one direction that was not losing content.
    restored_sections: tuple[str, ...] = ()


class RewrittenDraft(BaseModel):
    """A 4.1 merge draft reworded by the LLM into cleaner prose — **still a DRAFT**.

    Non-negotiable #1: there is NO approval / canonical / published field here. The
    rewritten JD is an ordinary ``SFUJobDescription`` (a draft), scored by the validator
    (the oracle) and carrying the anti-fabrication record + the provenance that traces
    it to the model, prompt and rules that produced it. Nothing here publishes anything.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    #: The reworded draft (a plain ``SFUJobDescription`` — a draft, never canonical).
    draft: SFUJobDescription
    #: The validator's score of the reworded draft (the oracle — see ``score_issues``).
    score: float
    #: The validator's grade of the reworded draft.
    grade: JDGrade
    #: Every issue the validator raised on the reworded draft, in the engine's order.
    issues: tuple[JDQualityIssue, ...] = ()
    #: What the anti-fabrication guard scrubbed / flagged.
    anti_fabrication: AntiFabricationRecord
    #: The chat model that produced the rewrite (``rewrite.model``).
    model: str
    #: The prompt template version stamped from the loaded prompt (``prompt.version``).
    prompt_version: str
    #: The rulebook version the draft was scored under (``Rules.version``).
    rules_version: str


# ---------- LLM nuanced quality-audit pass (Phase 4.2b) — advisory only ----------


class QualityAudit(BaseModel):
    """The nuanced LLM quality audit of a JD — **advisory, never a score** (Phase 4.2b).

    A self-hosted LLM reports only the three dimensions a regex validator cannot judge —
    ``inclusive_language`` / ``clarity`` / ``seniority_mismatch`` — and every finding
    must cite a VERBATIM quote from the JD. The anti-fabrication guard drops any finding
    whose ``evidence`` is not found verbatim in the flattened JD
    (:func:`~src.jd_bank.jd_text.flatten_jd`), recording it in :attr:`dropped` so a
    fabricated citation is visible, not invisible.

    Non-negotiables #1 / #3: there is NO score / grade / approval / canonical /
    published / ``job_id`` / ``generated_at`` field here. The deterministic validator
    remains the scoring oracle; this pass never competes with it. It emits advisory
    *issues*, nothing persists (DB is 4.4), nothing publishes. Frozen: it is an audit
    record, not a scratchpad. (Same trim discipline the module docstring documents for
    ``CanonicalRole`` — the hris persistence/scoring fields are dropped.)
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    #: The surviving nuanced findings, each ``source="llm"`` and ``rule_id=None`` —
    #: their ``evidence`` is a verbatim substring of the flattened JD.
    issues: tuple[JDQualityIssue, ...] = ()
    #: The findings the scrub REMOVED (ungrounded / missing evidence). The audit trail;
    #: frozen evidence of what the guard dropped, not a scratchpad.
    dropped: tuple[JDQualityFinding, ...] = ()
    #: Whether the anti-fabrication scrub ran (``quality.anti_fabrication_enabled``).
    #: When ``False`` every finding ships unscrubbed and :attr:`dropped` is empty —
    #: recorded so a disabled guard is visible in the audit's own provenance.
    anti_fabrication_enabled: bool
    #: The chat model that produced the audit (``quality.model``).
    model: str
    #: The prompt template version stamped from the loaded prompt (``prompt.version``).
    prompt_version: str
    #: The rulebook version the audit ran under (``Rules.version``).
    rules_version: str


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

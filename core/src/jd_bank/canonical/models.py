"""What a Phase-4.4a canonical-producer run reports.

A frozen, COUNTS-ONLY result (plus the rules/prompt/model stamps): the producer's
headline is "how many DRAFT canonicals were persisted / refreshed / left untouched",
never the JD prose it wrote (that lives in the persisted ``canonical_jds`` rows, and the
committed ``summary.json`` carries only this object — never JD text, non-negotiable #6 +
the counts-only rule that governs committed artifacts).

Mirrors :class:`~src.jd_bank.harmonize.models.HarmonizationResult`: every field is an
OBSERVATION, and the class is frozen so a report cannot be edited after the fact.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class TemplateEvaluation(BaseModel):
    """How the drafts authored on ONE form scored — against THAT form's own bar.

    **The rule this class exists to enforce is that there is no blended number.** A CUPE
    draft is judged by the WJQ profile (Phases B + C) and a JDFN draft by the JDFN one,
    so a single mean over both is a mean over two different measurements — the category
    error the whole CUPE phase removed. Reporting per form makes the blended figure
    unavailable rather than merely discouraged: the producer never computes one.

    Counts only, like everything else the summary commits — the drafts themselves are
    the persisted ``canonical_jds`` rows.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    #: Clusters entered on this form (persisted + refreshed + skipped + failed).
    clusters: int = Field(ge=0)
    #: Drafts this run actually WROTE on this form — the denominator for everything
    #: below. A skipped (reviewer-touched) or failed cluster is scored by nobody here,
    #: because the producer never built a draft for it, and quietly folding those into
    #: the denominator would understate the cohort.
    drafts_scored: int = Field(ge=0)
    #: Mean validator score over ``drafts_scored`` (0 when none). Rounded to 2dp — the
    #: summary is a report, and more precision than that implies a stability the
    #: underlying bar (206 decisions, 0 ratified) does not have.
    mean_score: float = Field(ge=0, le=100)
    #: Drafts this form's OWN gates would approve. Never comparable across forms as a
    #: quality statement — the two cohorts are scored by different rules.
    approvable: int = Field(ge=0)
    #: Grade -> count, over ``drafts_scored``.
    grades: dict[str, int] = Field(default_factory=dict)


class CanonicalProducerResult(BaseModel):
    """What one canonical-producer pass did — counts + stamps only, no JD text.

    ``drafts_persisted`` (first time a cluster got a canonical) + ``drafts_refreshed``
    (an untouched DRAFT re-written in place) + ``skipped_reviewer_touched`` (a
    published/archived canonical, or a DRAFT with a review action — LEFT UNTOUCHED) +
    ``cluster_failures`` account for every JDFN cluster the run entered
    (``clusters_seen``). Re-running yields ``drafts_persisted == 0`` and the same rows.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    # --- corpus scope (echoed from the clustering recompute) ---
    documents_seen: int = Field(ge=0)
    documents_signed: int = Field(ge=0)
    documents_unsignable: int = Field(ge=0)
    clusters_recomputed: int = Field(ge=0)

    # --- WJQ accounting (never silent) ---
    #: WJQ members DROPPED from a merge — because the cluster was authored on another
    #: form (a mixed cluster), or because ``wjq`` is not in
    #: ``harmonization.templates_harmonized`` at all. It does NOT count a WJQ member
    #: that fed a WJQ draft; that is ``wjq_members_authored`` (HR-206, CUPE Phase D).
    wjq_members_excluded: int = Field(ge=0)
    #: WJQ members that FED a draft — the other half of the same population. Zero when
    #: ``wjq`` is not in ``templates_harmonized``, which is the pre-Phase-D behaviour.
    wjq_members_authored: int = Field(ge=0)
    #: WJQ members that ALSO carried a duty ``frequency`` marker — cross-confirms the
    #: ``employee_group == cupe`` proxy really is a WJQ questionnaire. Counted over
    #: EVERY WJQ member seen, authored or excluded, so it stays comparable across runs.
    wjq_members_frequency_confirmed: int = Field(ge=0)
    #: Clusters holding ONLY WJQ members that produced NO draft — non-zero only when
    #: ``wjq`` is absent from ``templates_harmonized``. It counts what was *excluded*,
    #: so the name stays true under both settings.
    clusters_fully_wjq_excluded: int = Field(ge=0)
    clusters_mixed_jdfn_wjq: int = Field(ge=0)
    member_rows_dropped_unvalidatable: int = Field(ge=0)

    # --- what the producer did, per cluster ---
    #: Clusters the run entered (persisted + refreshed + skipped + failed).
    clusters_seen: int = Field(ge=0)
    #: Clusters entered, by the FORM their draft was authored on — the per-group split
    #: that must never be blended into one number (CUPE Phase D). Sums to
    #: ``clusters_seen``.
    clusters_by_template: dict[str, int] = Field(default_factory=dict)
    #: How each form's drafts SCORED, against that form's own bar (CUPE Phase D). There
    #: is deliberately no overall score field anywhere on this result: a mean across two
    #: forms is a mean across two different measurements, so the producer does not
    #: compute one and no consumer can quote one.
    evaluation_by_template: dict[str, TemplateEvaluation] = Field(default_factory=dict)
    multi_member_clusters: int = Field(ge=0)
    single_member_clusters: int = Field(ge=0)
    #: A cluster's FIRST canonical DRAFT was written.
    drafts_persisted: int = Field(ge=0)
    #: An existing UNTOUCHED DRAFT was re-written in place (no new version row).
    drafts_refreshed: int = Field(ge=0)
    #: A published/archived canonical OR a DRAFT a reviewer acted on — LEFT UNTOUCHED.
    skipped_reviewer_touched: int = Field(ge=0)
    #: Per-cluster failures isolated (SAVEPOINT rolled back) — never abort the run.
    cluster_failures: int = Field(ge=0)

    # --- LLM best-effort accounting (advisory, never fatal) ---
    #: Clusters whose 4.2a rewrite raised — the deterministic merge draft was persisted.
    rewrite_failures: int = Field(ge=0)
    #: Clusters whose 4.2b audit raised — advisory audit omitted, the draft persisted.
    audit_failures: int = Field(ge=0)

    # --- provenance stamps (the run's identity — never JD text) ---
    rules_version: str
    #: Whether an LLM client was injected (``False`` -> deterministic merge draft only).
    llm_enabled: bool
    rewrite_model: str
    rewrite_prompt_version: str
    quality_model: str
    quality_prompt_version: str

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

from pydantic import BaseModel, ConfigDict, Field, model_validator


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

    **TWO PARTITIONS, ENFORCED BY THE VALIDATORS BELOW RATHER THAN DESCRIBED HERE.**

    Every cluster the run ENTERED lands in exactly one outcome bucket::

        clusters_seen == drafts_persisted + drafts_refreshed + skipped_reviewer_touched
                       + skipped_would_downgrade + skipped_already_llm_written
                       + cluster_failures

    ...and every cluster the CLUSTERING produced is either entered or explicitly
    declined::

        clusters_recomputed == clusters_seen + clusters_out_of_scope
                             + clusters_fully_wjq_excluded
                             + clusters_no_authorable_template
                             + clusters_no_members_loaded

    🔴 THE SECOND IDENTITY IS WHY THE FIRST IS ENFORCED AND NOT MERELY WRITTEN DOWN.
    The prose here used to read "persisted + refreshed + skipped + failed account for
    every cluster the run entered" — true when it was written, false by the time it was
    read: two skip counters (``skipped_would_downgrade`` and
    ``skipped_already_llm_written``) were added under it and the sentence was not, so it
    described a partition that no longer held. THREE cluster shapes also fell
    through every counter entirely — an all-JDFN cluster under
    ``templates_harmonized=("wjq",)``, and a cluster whose members all failed to load —
    so a run could decline work and report a total that looked complete. A docstring
    cannot go stale into a `ValidationError`; a model validator can, which is the point.

    Re-running yields ``drafts_persisted == 0`` and the same rows.
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
    #: Clusters holding members on MORE THAN ONE form. Counted by how many forms the
    #: cluster contains, NOT by which one won: the old test also required the winner to
    #: be non-WJQ, so re-ordering ``templates_harmonized`` to put ``wjq`` first made
    #: every mixed cluster report as un-mixed.
    clusters_mixed_jdfn_wjq: int = Field(ge=0)
    #: Member ROWS that failed to load or validate, corpus-wide. See
    #: ``members_unloadable`` in a cluster's snapshot for the per-cluster split.
    member_rows_dropped_unvalidatable: int = Field(ge=0)
    #: WJQ members in WJQ-authored clusters this run did NOT write (skipped or failed),
    #: so ``wjq_members_authored`` can mean what it says. Before this existed those
    #: members were counted as authored on the strength of the cluster's FORM, before
    #: the cluster was processed — so a resumed pass that skipped everything still
    #: reported thousands of members "authored".
    wjq_members_unwritten: int = Field(default=0, ge=0)

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
    #: An untouched DRAFT the full pipeline wrote, left alone by a DETERMINISTIC run
    #: because refreshing it would have discarded the rewrite pass. Zero on a full run,
    #: and zero on a `--no-llm` run over a Bank the full pipeline never touched — so a
    #: non-zero value means exactly "a cheap run declined to overwrite expensive work".
    skipped_would_downgrade: int = Field(default=0, ge=0)
    #: An untouched DRAFT that already HOLDS a landed rewrite, skipped by a RESUME run
    #: (``skip_llm_written``) because it owes no further work. This is what makes the
    #: ~44-hour LLM pass restartable instead of all-or-nothing. A draft whose rewrite
    #: FAILED is NOT counted here — it holds only the deterministic merge, so a resume
    #: retries it (see :func:`draft_has_rewritten_prose`).
    skipped_already_llm_written: int = Field(default=0, ge=0)
    #: Clusters the rulebook WOULD have authored, excluded from THIS INVOCATION by
    #: ``only_template`` (the CLI `--only-template`). An OPERATIONAL scope, not a
    #: rulebook outcome: zero on every unscoped run, so a non-zero value means exactly
    #: "this pass deliberately did not look at N clusters". Reported so a scoped run
    #: cannot be mistaken for a full one when its summary is read back later.
    clusters_out_of_scope: int = Field(default=0, ge=0)
    #: Clusters holding members, none of them on a form in ``templates_harmonized`` —
    #: excluding the all-WJQ shape, which keeps its own long-standing counter. Today
    #: this is only reachable by removing ``jdfn`` from the list; it is counted because
    #: "the run entered N clusters" must not be able to quietly mean "N minus the ones
    #: it had no form for".
    clusters_no_authorable_template: int = Field(default=0, ge=0)
    #: Clusters where EVERY member row failed to load or validate, so there was nothing
    #: to merge. Distinct from a cluster failure: nothing raised, there was simply no
    #: input — and a run that silently drops such a cluster reports a smaller archive
    #: than it was given.
    clusters_no_members_loaded: int = Field(default=0, ge=0)
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

    @model_validator(mode="after")
    def _every_entered_cluster_has_exactly_one_outcome(
        self,
    ) -> CanonicalProducerResult:
        """``clusters_seen`` is the sum of the six outcome buckets.

        A cluster that reaches ``_process_cluster`` sets exactly one of them, so this
        holds by construction — which is precisely what makes it worth asserting. The
        cost of it drifting is not a wrong number on a report: it is a run that
        declined to do work and said nothing, over a pass whose progress line reads
        identically whether it worked or not.
        """
        buckets = (
            self.drafts_persisted
            + self.drafts_refreshed
            + self.skipped_reviewer_touched
            + self.skipped_would_downgrade
            + self.skipped_already_llm_written
            + self.cluster_failures
        )
        if buckets != self.clusters_seen:
            raise ValueError(
                f"clusters_seen ({self.clusters_seen}) != the sum of the outcome "
                f"buckets ({buckets}): persisted={self.drafts_persisted} "
                f"refreshed={self.drafts_refreshed} "
                f"skipped_reviewer_touched={self.skipped_reviewer_touched} "
                f"skipped_would_downgrade={self.skipped_would_downgrade} "
                f"skipped_already_llm_written={self.skipped_already_llm_written} "
                f"cluster_failures={self.cluster_failures}"
            )
        return self

    @model_validator(mode="after")
    def _every_recomputed_cluster_is_entered_or_declined(
        self,
    ) -> CanonicalProducerResult:
        """``clusters_recomputed`` is the sum of the clusters entered and the four
        explicit reasons for not entering one.

        This is the identity the three fall-through shapes broke, and the reason
        ``clusters_no_authorable_template`` / ``clusters_no_members_loaded`` exist at
        all: without them a cluster could be skipped for a reason no field named, and
        the arithmetic would not object.
        """
        accounted = (
            self.clusters_seen
            + self.clusters_out_of_scope
            + self.clusters_fully_wjq_excluded
            + self.clusters_no_authorable_template
            + self.clusters_no_members_loaded
        )
        if accounted != self.clusters_recomputed:
            raise ValueError(
                f"clusters_recomputed ({self.clusters_recomputed}) != clusters "
                f"accounted for ({accounted}): seen={self.clusters_seen} "
                f"out_of_scope={self.clusters_out_of_scope} "
                f"fully_wjq_excluded={self.clusters_fully_wjq_excluded} "
                f"no_authorable_template={self.clusters_no_authorable_template} "
                f"no_members_loaded={self.clusters_no_members_loaded}"
            )
        return self

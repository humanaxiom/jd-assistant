"""What a Phase-4.1 harmonization MEASUREMENT pass works on and produces (report-only).

Mirrors :mod:`src.jd_bank.cluster.models`: plain constants + a pydantic result. This
pass drives the pure ``jd_core.bank.merge.merge_cluster`` engine over the real JDFN role
clusters and MEASURES the distributions the nine ``harmonization.yaml`` knobs (HR-167…
HR-175) cut on, so a human can calibrate them. It picks NO knob value and it persists
NOTHING — no ``Cluster``/``CanonicalJD`` row is written (Phase 4.4 owns that). A merge
is a deterministic function of the member set + the live knobs, so re-running is free +
byte-identical (modulo ``generated_at``).

**JDFN-only.** WJQ (CUPE) members are excluded — they over-cluster until boilerplate
redaction lands and their ``.doc`` titles are lost, and the nine knobs are being
calibrated for the APSA/APEX/POLY (JDFN) bar. ``ParseResult.template`` is NOT persisted
(``jd_core.parser.store`` drops it), so the runner identifies WJQ by the field the JD
model itself designates as the JDFN/WJQ separator — ``employee_group == "cupe"``, which
the WJQ segmenter sets UNCONDITIONALLY (so recall is complete). Every exclusion is
COUNTED, never silent (HANDOFF standing rule).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

#: Bump when this module's pure MEASUREMENT maths changes for the same knobs (a code
#: change, not data). Rides in the summary's ``harmonize_stamp``.
HARMONIZE_VERSION: Final[str] = "harmonize_v1"

#: The ``employee_group`` value the WJQ segmenter stamps on every CUPE questionnaire —
#: the JDFN/WJQ separator (the JD model's own documented mechanism). Since
#: ``ParseResult.template`` is not persisted, this is the WJQ proxy the runner filters.
WJQ_EMPLOYEE_GROUP: Final[str] = "cupe"

#: Candidate duty-dedup thresholds swept to expose the knee (the 3.3 pattern) for
#: ``duty_dedup_jaccard_min`` (HR-171, shipped 0.7).
DUTY_JACCARD_CANDIDATES: Final[tuple[float, ...]] = (0.5, 0.6, 0.7, 0.8, 0.9)

#: Candidate duty caps swept for ``max_duties`` (HR-172, calibrated to 12).
DUTY_CAP_CANDIDATES: Final[tuple[int, ...]] = (5, 8, 10, 12)

#: Candidate core-skill fractions swept for ``core_skill_min_fraction`` (HR-173, 0.5).
CORE_FRACTION_CANDIDATES: Final[tuple[float, ...]] = (0.3, 0.4, 0.5, 0.6, 0.7)

#: Statement cap per cluster for the O(d²) pairwise-Jaccard histogram ONLY — bounds the
#: 132-member cluster's ~1k statements. The threshold SWEEP uses every statement; this
#: cap keeps the supporting histogram deterministic + bounded (sorted-statement prefix).
PAIRWISE_STATEMENT_CAP: Final[int] = 200


class ClusterHarmonization(BaseModel):
    """One harmonized JDFN role cluster's measured scalars — counts + the
    content-derived ``cluster_id`` ONLY, never JD-derived text. NO title/summary/duty
    column:
    ``cluster_label`` is the modal member ``title``, which the parser frequently fills
    with mis-extracted prose (a whole summary/duty paragraph, or SFU boilerplate), so a
    title-derived column would smuggle verbatim JD body text into an HR record. The
    content-derived ``cluster_id`` joins to the 3.5 members CSV for a human who needs
    filenames."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    cluster_id: UUID
    #: Members merged (JDFN only, after the WJQ drop).
    jdfn_member_count: int = Field(ge=1)
    #: WJQ members dropped from this cluster before merging.
    wjq_members_dropped: int = Field(ge=0)
    #: Deduped duty count at the shipped 0.7 threshold, UNCAPPED (pre ``max_duties``).
    deduped_duty_count: int = Field(ge=0)
    #: Distinct ``normalized_title`` stems among the JDFN members.
    distinct_normalized_titles: int = Field(ge=0)
    #: Modal normalized-title group size / member count (how dominant the modal role).
    modal_group_fraction: float = Field(ge=0.0, le=1.0)
    #: Skills required by >= the shipped 0.5 fraction of members.
    core_skill_count: int = Field(ge=0)
    #: Distinct security qualifications (deduped) across members.
    security_qual_count: int = Field(ge=0)
    #: Members carrying non-empty ``additional_context``.
    members_with_context: int = Field(ge=0)
    #: Whether >=1 member summary already sits in SFU's published word range.
    summary_in_range_available: bool
    #: Word count of the summary the engine SELECTED (``None`` when no member had one).
    chosen_summary_words: int | None = None
    #: max−min education bar over members stating one (``None`` when <1 states it).
    education_bar_spread: int | None = None
    #: max−min experience bar over members stating one (``None`` when <1 states it).
    experience_bar_spread: int | None = None
    #: The merge engine's HR-eyeball flags for this cluster.
    flags: tuple[str, ...] = ()


class HarmonizationResult(BaseModel):
    """What one harmonization measurement pass found. Report-only: it writes no row and
    picks no knob value — every field is an OBSERVATION for a human to calibrate on."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    # --- corpus scope (echoed from the clustering recompute) ---
    documents_seen: int = Field(ge=0)
    documents_signed: int = Field(ge=0)
    documents_unsignable: int = Field(ge=0)
    #: Signed docs in NO cluster of size >= min_cluster_size (ALL templates — WJQ
    #: inflates it; harmonize trivially, measured only as a count).
    singletons: int = Field(ge=0)

    # --- WJQ exclusion accounting (never silent) ---
    clusters_recomputed: int = Field(ge=0)
    wjq_members_dropped: int = Field(ge=0)
    #: Members dropped that ALSO carried a duty ``frequency`` — the WJQ-only signal that
    #: cross-confirms the ``employee_group == cupe`` proxy really is WJQ.
    wjq_members_frequency_confirmed: int = Field(ge=0)
    clusters_fully_wjq_excluded: int = Field(ge=0)
    clusters_mixed_jdfn_wjq: int = Field(ge=0)
    member_rows_dropped_unvalidatable: int = Field(ge=0)

    # --- harmonized clusters ---
    harmonized_clusters: int = Field(ge=0)
    multi_member_clusters: int = Field(ge=0)
    single_member_clusters: int = Field(ge=0)
    jdfn_members_merged: int = Field(ge=0)

    # --- HR-171 duty dedup / HR-172 max_duties ---
    #: threshold -> total deduped duties summed across multi-member clusters (the knee).
    total_deduped_duties_by_threshold: Mapping[str, int] = Field(default_factory=dict)
    #: uncapped deduped-duty count (@0.7) -> # multi-member clusters.
    deduped_duty_count_histogram: Mapping[int, int] = Field(default_factory=dict)
    #: cap -> # multi-member clusters whose uncapped deduped count exceeds it.
    duties_over_cap: Mapping[str, int] = Field(default_factory=dict)
    #: 0.05-wide bin -> pairwise duty-statement Jaccard count (bounded per cluster).
    pairwise_duty_jaccard_histogram: Mapping[str, int] = Field(default_factory=dict)

    # --- HR-173 core_skill_min_fraction ---
    #: 0.1-wide bin -> count of (skill, member-fraction) observations across clusters.
    skill_fraction_histogram: Mapping[str, int] = Field(default_factory=dict)
    #: candidate fraction -> # multi-member clusters with NO core skill at it.
    no_core_skills_by_fraction: Mapping[str, int] = Field(default_factory=dict)

    # --- HR-168 summary_policy ---
    #: # clusters where >=1 member summary is already in the published word range.
    summary_in_range_available_clusters: int = Field(ge=0)
    #: # clusters where NO member summary is in range (the in-range preference can't
    #: engage and must fall back to most-central).
    summary_no_in_range_clusters: int = Field(ge=0)
    #: word-count bucket -> # selected summaries.
    chosen_summary_wordcount_buckets: Mapping[str, int] = Field(default_factory=dict)

    # --- HR-167 title_policy ---
    #: distinct normalized-title count -> # multi-member clusters.
    distinct_normalized_title_histogram: Mapping[int, int] = Field(default_factory=dict)
    #: 0.1-wide bin -> # multi-member clusters by modal-group fraction.
    modal_group_fraction_histogram: Mapping[str, int] = Field(default_factory=dict)

    # --- HR-175 seniority_bar_policy ---
    education_bar_spread_histogram: Mapping[int, int] = Field(default_factory=dict)
    experience_bar_spread_histogram: Mapping[int, int] = Field(default_factory=dict)
    #: # multi-member clusters where the max education bar differs from the modal one.
    education_max_differs_from_modal: int = Field(ge=0)
    experience_max_differs_from_modal: int = Field(ge=0)

    # --- HR-169 additional_context_policy ---
    jdfn_members_with_context: int = Field(ge=0)
    clusters_with_multi_context: int = Field(ge=0)

    # --- HR-170 boilerplate_presence_policy ---
    #: presence bool -> {all_true, all_false, mixed} cluster counts.
    boilerplate_agreement: Mapping[str, Mapping[str, int]] = Field(default_factory=dict)

    # --- HR-174 security_policy ---
    clusters_with_any_security: int = Field(ge=0)
    #: distinct security-qual count -> # clusters (only clusters with >=1).
    security_count_histogram: Mapping[int, int] = Field(default_factory=dict)

    # --- aggregate flag rates (over harmonized clusters) ---
    flag_counts: Mapping[str, int] = Field(default_factory=dict)

    # --- the live knobs this run measured under (echoed, NOT changed) ---
    title_policy: str
    summary_policy: str
    additional_context_policy: str
    boilerplate_presence_policy: str
    duty_dedup_jaccard_min: float
    max_duties: int
    core_skill_min_fraction: float
    security_policy: str
    seniority_bar_policy: str

    harmonize_stamp: str

    clusters: tuple[ClusterHarmonization, ...] = ()

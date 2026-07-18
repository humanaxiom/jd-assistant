"""jd_core.bank — JD Bank's pure harmonization primitives (no I/O).

Ported from hris ``packages/pipeline/src/pipeline/bank/`` (ADR-005, reuse-map
#11–12). Phase 2.4a landed the two mechanical pieces; 2.4b added the two advisory
classifiers; 2.4c adds the JD-to-JD comparison maths::

    from src.jd_core.bank import (
        build_clusters, classify_title, compute_drift, estimate_hay_signals,
        render_sfu_jd_text, score_job_similarity, skill_frequency,
    )

    freq = skill_frequency([{"python", "sql"}, {"python"}])  # provenance
    text = render_sfu_jd_text(canonical.jd)                  # canonical -> text
    title = classify_title("Manager, Research Services")     # seniority + function
    hay = estimate_hay_signals(canonical.jd)                 # advisory, NEVER a grade

Everything here is **advisory**: the title family/function anchors help standardize
titling and compare like roles, the Hay signals help Compensation *level* a role,
and the drift level flags a posting worth a second look. Nothing here decides
anything — no approval gate reads any of it — and nothing assigns a Hay grade (SFU
publishes no point charts, and :class:`~src.jd_core.models.bank.HaySignals` has no
field that could hold one).

Every table, weight and threshold they read is versioned YAML under
``jd_core/rules/`` (CLAUDE.md §2), down to the *order* the title keywords are tried
in — and every one of those numbers is an ``open`` entry in the HR decision register.

⚠ **The 2.4c trio — similarity, clustering, drift — is NOT WIRED TO ANYTHING**, on
purpose. Their inputs (a skill set per JD, a skill ontology, an idf corpus, a
structured education level and years bar) do not exist in JD Bank: a parsed JD has
none of them. The maths, its thresholds and its tests are landed and registered so
that **Phase 3** (dedup & clustering) — which will have the archive corpus needed to
compute an idf and build the edges — starts from declared numbers rather than
smuggling them in inside a feature PR. Read the module docstrings before assuming
otherwise; do not invent a skill source to make them callable.

Everything in here is pure and deterministic, so it is unit-tested in isolation.
"""

from src.jd_core.bank.change_log import build_harmonization_diff
from src.jd_core.bank.clustering import build_clusters, cluster_label, cluster_metrics
from src.jd_core.bank.drift import (
    DriftResult,
    compute_drift,
    education_level_from_quals,
    education_level_from_text,
    education_ordinal,
    experience_years_from_text,
    supervisory_reports_from_text,
)
from src.jd_core.bank.embed_text import (
    SERIALIZER_VERSION,
    SerializedText,
    serialize_document,
    serialize_section,
)
from src.jd_core.bank.hay_signals import estimate_hay_signals
from src.jd_core.bank.merge import (
    canonical_member_order,
    dropped_duty_occurrences,
    merge_cluster,
    unmerged_content,
)
from src.jd_core.bank.provenance import skill_frequency
from src.jd_core.bank.render import render_sfu_jd_text
from src.jd_core.bank.signals import (
    build_job_signals,
    canonical_title,
)
from src.jd_core.bank.similarity import (
    clone_verdict,
    normalize_title,
    score_job_similarity,
    seniority_closeness,
    skill_overlap,
)
from src.jd_core.bank.title_family import (
    classify_title,
    classify_title_family,
    classify_title_function,
    title_comma_supervisory,
)

__all__ = [
    "SERIALIZER_VERSION",
    "DriftResult",
    "SerializedText",
    "build_clusters",
    "build_harmonization_diff",
    "build_job_signals",
    "canonical_member_order",
    "canonical_title",
    "classify_title",
    "classify_title_family",
    "classify_title_function",
    "clone_verdict",
    "cluster_label",
    "cluster_metrics",
    "compute_drift",
    "dropped_duty_occurrences",
    "education_level_from_quals",
    "education_level_from_text",
    "education_ordinal",
    "estimate_hay_signals",
    "experience_years_from_text",
    "merge_cluster",
    "normalize_title",
    "render_sfu_jd_text",
    "score_job_similarity",
    "seniority_closeness",
    "serialize_document",
    "serialize_section",
    "skill_frequency",
    "skill_overlap",
    "supervisory_reports_from_text",
    "title_comma_supervisory",
    "unmerged_content",
]

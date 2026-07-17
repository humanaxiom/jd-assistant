"""What a Phase-3.5 clustering pass works on, and what it produces (report-only).

Mirrors the Tier-1/2/3 split: plain frozen dataclasses for the pure edge-admission +
graph maths, pydantic models for the committed report. Nothing here touches Postgres —
see :mod:`.runner` for the orchestration + I/O.

**This phase persists NOTHING.** A role cluster is a deterministic function of the
`dedup_edges` graph + the live cluster knobs, so it is recomputable at any time; and the
`Cluster` table's ``canonical_jds`` FK is ``ON DELETE CASCADE``, so a re-cluster
reconcile would DELETE approved canonical JDs once Phase 4 creates them. Clustering is
therefore an "eyeball pass" that emits a report and writes no row — persistence waits
for Phase 4, when
harmonization consumes a cluster and HR has ratified the config.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final
from uuid import UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field

from src.jd_bank.db.models import DedupTier
from src.jd_core.models.bank import DriftLevel, TitleFamily

#: Bump when this module's pure clustering/report maths changes for the SAME rulebook
#: knobs (a code change, not data — a data change already moves ``rules_version``
#: and the ``cluster_stamp``). Rides in the report's ``cluster_stamp``.
CLUSTER_VERSION: Final[str] = "cluster_v1"

#: A stable namespace so a cluster's id is a pure function of its sorted member
#: ``storage_ref``s — the SAME trick :meth:`DocumentRef.for_path` uses, and for the same
#: reason: a random id per run would make two runs incomparable cluster-for-cluster, the
#: opposite of an audit trail. Two runs over the same admitted graph produce identical
#: cluster ids, so an HR reviewer can diff one report against the next.
_CLUSTER_NAMESPACE: Final[UUID] = UUID("6ba7b813-9dad-11d1-80b4-00c04fd430c8")

#: The three cohesion-cap violation labels — a closed vocabulary the report emits.
BAND_SPREAD: Final[str] = "band_spread"
GROUP_MIX: Final[str] = "group_mix"
OVERSIZE: Final[str] = "oversize"


def cluster_id_for(member_storage_refs: list[str]) -> UUID:
    """A cluster's content-derived ``uuid5`` over its SORTED member ``storage_ref``s.

    Reproducibility rule (mirrors :meth:`DocumentRef.for_path`): stable across runs, so
    reports diff. The member set — not the order it was discovered in — is the identity.
    """
    payload = "\n".join(sorted(member_storage_refs))
    return uuid5(_CLUSTER_NAMESPACE, payload)


@dataclass(frozen=True, slots=True)
class ClusterEdge:
    """One admitted (or candidate) edge between two signed source documents, carrying
    the tier + method that produced it — kept beside the score so the report can
    attribute a cluster's internal edges to their tiers and echo their provenance
    stamps. ``a``/``b`` are unordered in intent; the graph is undirected.
    """

    a: UUID
    b: UUID
    tier: DedupTier
    score: float
    method: str


class ClusterMember(BaseModel):
    """One JD inside a role cluster — filenames, titles, the classification signals a
    reviewer needs, and its drift from the cluster representative. Never document TEXT
    (CLAUDE.md: committed artifacts carry counts, labels and the same class of filename
    data ``docs/dedup/`` already commits)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_id: UUID
    filename: str | None
    title: str
    normalized_title: str
    department: str | None
    employee_group: str | None
    family: TitleFamily
    #: Seniority band (``family_band_ladder``), ``None`` for an ``unmapped``
    #: family — 70% of the corpus, by design.
    band: int | None
    restricted: bool
    is_representative: bool
    parse_confidence: float = Field(ge=0.0, le=1.0)
    #: Skill-set drift level vs the cluster representative (``aligned`` for the rep).
    drift_vs_representative: DriftLevel


class ClusterRecord(BaseModel):
    """One role cluster — a connected component over the admitted edge graph, with the
    cohesion metrics and the "needs HR eyes" flags computed but NEVER acted on — a
    cluster is flagged, never split."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    cluster_id: UUID
    label: str
    member_count: int = Field(ge=2)
    #: Distinct raw titles present, sorted.
    titles: tuple[str, ...]
    #: Distinct KNOWN departments present, sorted.
    departments: tuple[str, ...]
    #: Distinct KNOWN employee groups present, sorted.
    employee_groups: tuple[str, ...]
    #: Distinct NORMALIZED titles (the ``cluster_metrics`` count).
    distinct_titles: int = Field(ge=0)
    cross_department: bool
    cross_group: bool
    #: max−min band over MAPPED members; ``None`` when fewer than one member maps.
    family_band_spread: int | None
    #: The distinct seniority bands present among mapped members, sorted.
    bands: tuple[int, ...]
    has_restricted: bool
    #: Which dedup tiers' edges are INTERNAL to this cluster (sorted enum values).
    tiers: tuple[str, ...]
    #: The weakest internal edge score — the thread the cluster hangs by.
    min_edge_score: float = Field(ge=0.0, le=1.0)
    drift_level_max: DriftLevel
    drift_major_count: int = Field(ge=0)
    #: The cohesion-cap flags this cluster trips (``band_spread`` / ``group_mix`` /
    #: ``oversize``), sorted. Empty when the cluster is cohesive.
    constraint_violations: tuple[str, ...]
    representative_filename: str | None
    members: tuple[ClusterMember, ...]


class ClusteringResult(BaseModel):
    """What one clustering pass found. Report-only: ``persisted``-row language is
    absent BY DESIGN — this pass writes no ``Cluster`` row and commits nothing."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    documents_seen: int = Field(ge=0)
    #: Parsed JDs turned into :class:`~src.jd_core.models.bank.JobSignals` — the cluster
    #: scope. An unsignable JD is UNKNOWN, out of scope, never clustered.
    documents_signed: int = Field(ge=0)
    documents_unsignable: int = Field(ge=0)
    #: Signed JDs with a document vector in Neo4j — ``None`` when this run did not read
    #: Neo4j (the ``cluster`` service runs Postgres-only; a reporting nicety,
    #: not a clustering input — clustering is over the edge graph).
    documents_with_vector: int | None = None

    #: Signed JDs that landed in NO cluster of size >= ``min_cluster_size``.
    singletons: int = Field(ge=0)
    #: Signed JDs that landed in a cluster (``documents_signed − singletons``).
    clustered_documents: int = Field(ge=0)
    coverage_rate: float = Field(ge=0.0, le=1.0)

    #: Candidate edges loaded/synthesized, BEFORE admission.
    edges_considered: int = Field(ge=0)
    #: ...and admitted after the tier gate + ROLE gate + vetoes.
    edges_admitted: int = Field(ge=0)
    tier_excluded: int = Field(ge=0)
    role_below_min: int = Field(ge=0)
    band_vetoed: int = Field(ge=0)
    group_vetoed: int = Field(ge=0)
    #: Synthesized EXACT star edges (sha256), added because Tier-2 structurally excludes
    #: byte-identical pairs (one signature per distinct content).
    exact_synthesized: int = Field(ge=0)

    cluster_count: int = Field(ge=0)
    largest_cluster: int = Field(ge=0)
    #: cluster size -> how many clusters are that size.
    size_distribution: Mapping[int, int] = Field(default_factory=dict)
    cross_department_clusters: int = Field(ge=0)
    cross_group_clusters: int = Field(ge=0)
    restricted_touching_clusters: int = Field(ge=0)
    flagged_clusters: int = Field(ge=0)
    #: violation label -> how many clusters trip it.
    violation_counts: Mapping[str, int] = Field(default_factory=dict)
    #: tier value -> how many clusters have an internal edge of that tier.
    tier_contribution: Mapping[str, int] = Field(default_factory=dict)

    #: The echoed cluster knobs (HR-161 … HR-166).
    cluster_tiers: tuple[str, ...]
    cluster_role_equiv_min: float = Field(ge=0.0, le=1.0)
    cluster_max_band_spread: int = Field(ge=0)
    cluster_group_homogeneous: bool
    cluster_max_size: int = Field(gt=0)
    cluster_representative_policy: str

    #: The clustering stamp (``CLUSTER_VERSION`` + a knob digest) and the distinct
    #: ``method`` stamps of the edges consumed — provenance for the report.
    cluster_stamp: str
    edge_method_stamps: tuple[str, ...]

    #: title family -> how many signed JDs classify onto it.
    family_distribution: Mapping[str, int] = Field(default_factory=dict)

    clusters: tuple[ClusterRecord, ...] = ()

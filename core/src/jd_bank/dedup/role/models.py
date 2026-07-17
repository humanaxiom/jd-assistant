"""What a Tier-3 role-equivalence pass works on, and what it produces (Phase 3.4b).

Mirrors the Tier-1 / Tier-2 split: plain frozen dataclasses for the pure
candidate-generation + scoring maths, a pydantic result for the counted run summary.
Nothing here touches Postgres or Neo4j — see :mod:`.runner` for the orchestration + I/O.

**Tier-3 edges are NOT additive** (like Tier-2, unlike Tier-1): a role-equivalence edge
is only true relative to a threshold, a veto ladder and an idf corpus, so the runner
RECONCILES (insert / update / prune), it does not merely MERGE. That is why every scored
pair carries its full component breakdown here — the reconcile keys on ``(score,
method)``, and the ``method`` stamp digests the config + idf so a retune re-reconciles.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from src.jd_bank.dedup.models import DocumentRef
from src.jd_core.models.bank import JobSignals

#: Bump when this module's pure maths changes for the SAME rulebook knobs (a code
#: change, not a data change — a data change already moves the Tier-3 stamp). Rides in
#: the edge ``method`` (``vec+skill@<ROLE_EQUIV_VERSION>+<digest>``).
ROLE_EQUIV_VERSION: Final[str] = "dedup_role_v1"


@dataclass(frozen=True, slots=True)
class RoleDoc:
    """One JD as Tier-3 sees it: its :class:`~src.jd_bank.dedup.models.DocumentRef` (for
    orientation + filenames), its 3.4a :class:`~src.jd_core.models.bank.JobSignals`, and
    its document embedding — ``None`` for the 118 empty-serialization + 11 token-limit
    JDs that never got a vector. A vector-less JD can still be a candidate (via a Tier-2
    near-dup seed) and scores with ``vector_score`` 0.0; it is NOT dropped."""

    ref: DocumentRef
    signals: JobSignals
    vector: tuple[float, ...] | None


@dataclass(frozen=True, slots=True)
class ScoredRolePair:
    """Two JDs that survived the hard vetoes, with the full component breakdown of their
    blended similarity — a candidate becomes an edge only once ``blended`` clears
    ``comparison.role_equiv_threshold``."""

    a: RoleDoc
    b: RoleDoc
    vector_score: float
    skill_overlap: float
    seniority: float
    blended: float
    #: Either side uses an SFU-reserved title phrase (``titles.yaml :: restricted``) —
    #: flagged for human review, never silently merged (carried into the edge
    #: ``method``).
    restricted: bool
    #: Both sides share a functional title ``function`` (same bucket) — a candidate
    #: seeded from a Tier-2 near-dup can be cross-function.
    same_function: bool


@dataclass(frozen=True, slots=True)
class RoleEdgeSpec:
    """One ``dedup_edges`` row at ``tier=ROLE_EQUIVALENT``, before it is a row. Oriented
    by :func:`~src.jd_bank.dedup.models.order_key` — the SAME total order Tier-1/Tier-2
    use, so ``uq_dedup_pair_tier`` never sees a mirrored pair from any tier."""

    source_a_id: UUID
    source_b_id: UUID
    score: float
    method: str


class RolePairRecord(BaseModel):
    """One reportable candidate pair — filenames, the blended score and its three
    components, both title families, the ``restricted`` flag, and the
    same/cross-function stratum. Never document TEXT (CLAUDE.md: committed artifacts are
    counts, stamps and
    the same class of filename data ``docs/dedup/`` already commits)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    filename_a: str | None
    filename_b: str | None
    score: float = Field(ge=0.0, le=1.0)
    vector_score: float = Field(ge=0.0, le=1.0)
    skill_overlap: float
    seniority: float = Field(ge=0.0, le=1.0)
    family_a: str
    family_b: str
    restricted: bool
    same_function: bool
    #: Did this candidate become an EDGE (blended >= ``role_equiv_threshold``)?
    qualifies: bool


class Tier3Result(BaseModel):
    """What one run of the Tier-3 pass did. ``edges_written == edges_updated ==
    edges_pruned == 0`` on a re-run over unchanged data + unchanged config is the
    idempotency guarantee, stated as a number — the same contract the Tier-1/Tier-2
    results carry."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    documents_seen: int = Field(ge=0)
    #: Parsed JDs turned into :class:`~src.jd_core.models.bank.JobSignals` — the PRUNE
    #: SCOPE (``read_ids``). An unsignable JD is UNKNOWN, not in scope, never pruned.
    documents_signed: int = Field(ge=0)
    #: Parsed JDs that failed to validate/sign — counted, never crashed on.
    documents_unsignable: int = Field(ge=0)
    documents_with_vector: int = Field(ge=0)
    documents_without_vector: int = Field(ge=0)

    #: Deduped candidate pairs (cosine k-NN + near-dup seeds), BEFORE the vetoes.
    candidate_pairs: int = Field(ge=0)
    #: Candidates dropped by the hard family-band conflict veto (both mapped, >max gap).
    band_vetoed: int = Field(ge=0)
    #: Candidates dropped by the soft employee-group veto (both known, differ).
    group_vetoed: int = Field(ge=0)
    #: Candidates that survived both vetoes and were scored.
    admissible_pairs: int = Field(ge=0)
    #: Scored pairs that cleared ``role_equiv_threshold`` — the content-level edges.
    qualifying_pairs: int = Field(ge=0)
    #: Qualifying edges where either side is a restricted title — flagged for review.
    restricted_flagged: int = Field(ge=0)

    edges_written: int = Field(ge=0)
    edges_updated: int = Field(ge=0)
    edges_unchanged: int = Field(ge=0)
    edges_pruned: int = Field(ge=0)

    role_equiv_threshold: float = Field(ge=0.0, le=1.0)
    max_band_gap: int = Field(ge=0)
    candidate_k: int = Field(gt=0)
    seed_from_near_dup: bool
    group_conflict_veto: bool
    idf_stamp: str
    idf_skills: int = Field(ge=0)
    dedup_stamp: str
    #: title family -> how many SIGNED JDs classify onto it (``unmapped`` included).
    family_distribution: Mapping[str, int] = Field(default_factory=dict)

    #: Reportable pair-level detail for ``report.py`` — filenames, scores, components,
    #: families and the restricted flag, never document text. EVERY admissible (scored)
    #: pair, qualifying or not — a below-threshold candidate is exactly what the
    #: adjudication sample exists to put in front of a human (HR-158).
    pairs: tuple[RolePairRecord, ...] = ()

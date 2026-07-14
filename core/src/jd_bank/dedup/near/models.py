"""What a Tier-2 pass works on, and what it produces.

Mirrors :mod:`src.jd_bank.dedup.models` (Tier-1)'s split: plain frozen dataclasses for
the pure grouping/candidate-generation maths, a pydantic result for the counted run
summary. Nothing here touches Postgres or Neo4j — see :mod:`.text` for the I/O
boundary and :mod:`.runner` for the orchestration.
"""

from __future__ import annotations

from array import array
from dataclasses import dataclass, field
from typing import Final
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from src.jd_core.rules import DedupEdgeScope, DedupTextSource


@dataclass(frozen=True, slots=True)
class Signature:
    """One DISTINCT CONTENT's Tier-2 fingerprint.

    ``id`` is the representative :class:`~src.jd_bank.dedup.models.DocumentRef` this
    content's text was actually read from and shingled — chosen by
    :func:`~src.jd_bank.dedup.models.order_key` over ``group_members``, the same total
    order Tier-1 uses. ``group_members`` is every ``source_documents`` row sharing this
    ``sha256`` (Tier-1's own duplicate group, INCLUDING singletons — a content that is
    nobody's duplicate is still one unit here), sorted the same way, so a caller can
    memoize by ``sha256`` (one text read, one shingle set, one MinHash signature per
    DISTINCT content — never per file) and, under ``edge_scope: file``, expand one
    qualifying content-pair into every cross-group file pair without re-reading or
    re-shingling anything.
    """

    id: UUID
    sha256: str
    filename: str | None
    storage_ref: str
    group_members: tuple[UUID, ...]
    #: Sorted, distinct 64-bit shingle hashes (empty when the text yielded fewer than
    #: ``dedup.min_shingles`` — see :mod:`.runner`, which never reaches this point for
    #: those; kept here so a defensively-constructed empty ``Signature`` is still valid
    #: data, never a special case a consumer must guard against separately).
    shingles: array[int] = field(default_factory=lambda: array("Q"))
    #: The MinHash signature over :attr:`shingles` — the LSH candidate-generation key,
    #: NEVER the score (see ``jd_core.bank.minhash``).
    minhash: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class CandidatePair:
    """Two DISTINCT CONTENTS that landed in the same LSH bucket at least once, scored
    by EXACT Jaccard (never the MinHash estimate) — a candidate becomes an edge only
    once its score clears ``dedup.jaccard_min`` (and, if configured, the cosine
    confirm)."""

    a: Signature
    b: Signature
    #: Exact Jaccard over ``a.shingles`` / ``b.shingles``.
    jaccard: float
    #: The document cosine confirm's verdict, or ``None`` when the confirm is OFF
    #: (``dedup.cosine_confirm_min`` is ``null``) or a vector was unavailable for
    #: either side — in both cases the pair is judged on Jaccard alone.
    cosine: float | None = None


#: One ``dedup_edges`` row, before it is a row. Oriented by
#: :func:`~src.jd_bank.dedup.models.order_key` — the SAME total order Tier-1 uses, so
#: the database's ``uq_dedup_pair_tier`` constraint (on the ORDERED triple) can never
#: see a mirrored pair from either tier.
@dataclass(frozen=True, slots=True)
class NearEdgeSpec:
    source_a_id: UUID
    source_b_id: UUID
    score: float
    method: str


class PairRecord(BaseModel):
    """One reportable candidate pair — filenames, scores, and a position-scope flag.
    Never document TEXT (CLAUDE.md: committed archive artifacts are counts and stamps,
    plus the same class of filename data ``docs/dedup/summary.json`` already
    commits)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    filename_a: str | None
    filename_b: str | None
    jaccard: float = Field(ge=0.0, le=1.0)
    cosine: float | None = Field(default=None, ge=-1.0, le=1.0)
    #: ``True``/``False`` when both sides' filenames yielded a position id
    #: (``segmentation.position_id_pattern``) and they can be compared; ``None`` when
    #: either side carries no readable position id.
    same_position: bool | None = None
    #: Did this candidate become an EDGE? ``False`` for a candidate that missed
    #: ``jaccard_min``, and for one the cosine confirm vetoed.
    #:
    #: ⚠ There is deliberately NO second "wrote_edge" flag beside this. The first cut
    #: had one, and it was a LIE and dead: it was set in ``_build_plan``, i.e. BEFORE
    #: the reconcile ran, so it read ``True`` for edges that the reconcile then found
    #: ``unchanged`` and did not write at all — and nothing consumed it. Whether a row
    #: was physically INSERTed this run is a property of the run
    #: (:attr:`Tier2Result.edges_written` / ``edges_updated`` / ``edges_unchanged``),
    #: not of the pair.
    qualifies: bool = True


#: Bump when this module's pure maths changes for the SAME rulebook knobs (a code
#: change, not a data change — a data change already moves ``Dedup.stamp``).
NEAR_DUP_VERSION: Final[str] = "dedup_near_v1"


class Tier2Result(BaseModel):
    """What one run of the Tier-2 pass did. ``edges_written == edges_updated ==
    edges_pruned == 0`` on a re-run over unchanged data + unchanged config is the
    idempotency guarantee, stated as a number — the same contract
    :class:`~src.jd_bank.dedup.models.Tier1Result` and ``EmbedRunResult`` carry."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    documents_seen: int = Field(ge=0)
    distinct_contents: int = Field(ge=0)
    #: Text could not be read/extracted for this content at all (:class:`.text.
    #: TextResult` with ``text=None``) — counted, never silently dropped.
    documents_unreadable: int = Field(ge=0)
    #: Fewer than ``dedup.min_shingles`` shingles resulted — no signature was built.
    #: Counted, never silently dropped.
    documents_below_min_shingles: int = Field(ge=0)
    #: Distinct contents an LSH signature WAS built for.
    documents_signed: int = Field(ge=0)

    #: Raw LSH candidate CONTENT pairs generated (before the Jaccard threshold).
    candidate_pairs: int = Field(ge=0)
    #: Candidate pairs that QUALIFIED — cleared ``dedup.jaccard_min`` **and** survived
    #: the cosine confirm. Exactly ``sum(1 for p in pairs if p.qualifies)``, which is
    #: the same predicate ``report.py``'s position split counts, so the two numbers in
    #: one artifact cannot disagree. (They did in the first cut: this counted
    #: ``jaccard >= jaccard_min`` while the split counted ``qualifies``, which is inert
    #: while the cosine confirm ships OFF and would have gone live and contradictory
    #: the day HR-139 flipped it.) Pairs that cleared Jaccard and were then vetoed are
    #: :attr:`cosine_vetoed`; ``qualifying_pairs + cosine_vetoed`` is "cleared Jaccard".
    qualifying_pairs: int = Field(ge=0)
    #: Jaccard-clearing pairs the cosine confirm VETOED (``0`` whenever it is off).
    cosine_vetoed: int = Field(ge=0)

    edges_written: int = Field(ge=0)
    edges_updated: int = Field(ge=0)
    edges_unchanged: int = Field(ge=0)
    edges_pruned: int = Field(ge=0)

    text_source: DedupTextSource
    edge_scope: DedupEdgeScope
    jaccard_min: float = Field(ge=0.0, le=1.0)
    cosine_confirm_min: float | None = None
    s_curve_threshold: float = Field(ge=0.0, le=1.0)
    dedup_stamp: str

    #: Reportable pair-level detail for ``report.py`` — filenames and scores, never
    #: document text. **EVERY LSH candidate pair**, qualifying or not — a candidate
    #: that missed ``jaccard_min`` is exactly what the adjudication sample exists to
    #: put in front of a human (HR-138), so it is reported, never silently discarded.
    #: :attr:`PairRecord.qualifies` says which became an edge.
    pairs: tuple[PairRecord, ...] = ()

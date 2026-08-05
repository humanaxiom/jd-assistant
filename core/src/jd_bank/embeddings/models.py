"""Value objects for the embedding runner (Phase 3.2b).

Same split as :mod:`src.jd_bank.dedup.models`: plain, DB-agnostic dataclasses the
store writes from, and a pydantic result the runner returns — nothing here imports
Neo4j or Postgres.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import NamedTuple
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class NodeKey(NamedTuple):
    """A node's CONTENT identity — what the store's skip-first pass compares.

    Two nodes with the same key were produced from the same text, by the same
    model, under the same rulebook stamp — so re-embedding one would produce a
    byte-identical result (measured: same text -> byte-identical vector, ADR-003),
    and skipping it costs nothing.
    """

    text_sha256: str
    model: str
    embed_stamp: str


@dataclass(frozen=True, slots=True)
class DocumentWrite:
    """One ``(:JDDocument)`` node, ready to MERGE — the embedding already computed."""

    source_document_id: UUID
    parsed_jd_id: UUID
    parser_version: str
    text_sha256: str
    text_chars: int
    truncated: bool
    embedding: list[float]
    model: str
    dimensions: int
    embed_stamp: str
    serializer_version: str


@dataclass(frozen=True, slots=True)
class RoleWrite:
    """One ``(:JDRole)`` node — a HARMONIZED role (a cluster), not an archive file.

    Keyed on ``cluster_id`` because that is the role's stable identity across
    versions: an edit mints ``version + 1`` but the role is the same role, and the
    Builder clones a role by cluster. ``status``/``version`` ride along so a hit can
    be labelled without a second Postgres round trip.
    """

    cluster_id: UUID
    canonical_jd_id: UUID
    version: int
    status: str
    title: str
    employee_group: str | None
    text_sha256: str
    text_chars: int
    truncated: bool
    embedding: list[float]
    model: str
    dimensions: int
    embed_stamp: str
    serializer_version: str


@dataclass(frozen=True, slots=True)
class SectionWrite:
    """One ``(:JDSection)`` node, ready to MERGE, plus the ``HAS_SECTION`` edge from
    its document."""

    source_document_id: UUID
    parsed_jd_id: UUID
    parser_version: str
    section: str
    text_sha256: str
    text_chars: int
    truncated: bool
    embedding: list[float]
    model: str
    dimensions: int
    embed_stamp: str
    serializer_version: str

    @property
    def section_id(self) -> str:
        """``<source_document_id>:<section>`` — the node's own ``id`` (Phase 3.2b
        spec). Keyed on ``source_document_id``, NOT ``parsed_jd_id``: Tier-3 dedup
        writes ``DedupEdge(source_a_id, source_b_id)`` against ``source_documents``
        ids, so a vector hit must join to that with no lookup table, and the id
        stays stable across a re-parse (``parsed_jd_id`` survives only as a
        property)."""
        return f"{self.source_document_id}:{self.section}"


class EmbedRunResult(BaseModel):
    """What one run of the embedding pass did. ``documents_embedded == 0`` (and
    ``embed_calls == 0``) on a re-run over an unchanged corpus is the idempotency
    guarantee, stated as a number — the same contract
    :class:`~src.jd_bank.dedup.models.Tier1Result` makes for Tier-1 dedup.

    Contains counts and stamps ONLY — never a vector. This is what
    ``docs/embeddings/summary.json`` is: embeddings are not guaranteed
    byte-reproducible across model-server versions (unlike the deterministic
    baseline/dedup artifacts), so no committed file may claim to reproduce one.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    documents_seen: int = Field(ge=0)
    documents_embedded: int = Field(ge=0)
    documents_unchanged: int = Field(ge=0)
    #: Parsed JDs whose configured document_sections are ALL empty (the 34.5% WJQ
    #: case) — never embedded as `""`, never given a node.
    documents_empty: int = Field(ge=0)
    sections_embedded: int = Field(ge=0)
    sections_unchanged: int = Field(ge=0)
    #: A section with no content, or fewer than `min_section_chars` — no unit, no
    #: node, counted but never a zero vector.
    sections_skipped_short: int = Field(ge=0)
    #: Nodes DELETED because the rulebook (or a re-parse) says they should no longer
    #: exist: a section dropped from `section_vectors`, one that fell under
    #: `min_section_chars`, or a whole document whose JD now serializes to nothing.
    #: A MERGE-only pass would leave these live in the queryable vector index — see
    #: `store.prune_sections`.
    nodes_pruned: int = Field(ge=0)
    #: Network round-trips actually MADE to the embedding server (batches, not
    #: texts) — including a batch that 400'd and each of the one-at-a-time retries it
    #: triggered, because those are real calls and this number is what a reader uses
    #: to reason about cost. Zero on a re-run over an unchanged corpus: that is the
    #: idempotency guarantee, and counting failures cannot weaken it (a failure
    #: implies there was something to embed).
    embed_calls: int = Field(ge=0)
    #: Node-slots that needed a FRESH embedding but reused one already computed
    #: earlier in THIS run, by `text_sha256` (byte-identical archive duplicates).
    embed_texts_reused_memo: int = Field(ge=0)
    #: Texts the server 400'd on at `max_chars` AND at every `max_chars_fallback`
    #: rung (a permanent property of the input, never retried) — the corresponding
    #: node(s) are skipped, not crashed past. With a non-empty fallback ladder this
    #: should be ~0: the ladder rescues the over-window texts into `texts_backed_off`.
    bad_requests: int = Field(ge=0)
    #: Over-long texts (`max_chars` output still 400'd) that a shorter
    #: `max_chars_fallback` rung DID embed — rescued to a best-effort backed-off
    #: vector instead of no vector at all (HR-193). Zero when the ladder is empty
    #: (the pre-HR-193 behavior) or nothing was over-window.
    texts_backed_off: int = Field(ge=0)
    model: str
    dimensions: int
    embed_stamp: str
    serializer_version: str

"""What a Tier-1 pass works on, and what it produces.

Two layers, deliberately separate:

* **The refs and groups** (:class:`DocumentRef`, :class:`DuplicateGroup`,
  :class:`EdgeSpec`) are plain frozen dataclasses over ``(id, sha256, storage_ref)``.
  They know nothing about Postgres, so the *same* grouping code runs against the DB
  (:func:`~src.jd_bank.dedup.tier1.run_tier1`) and against the baseline's
  ``rows.jsonl`` (:mod:`src.jd_bank.dedup.report`). That is the point: the report's
  numbers are not a second implementation that happens to agree — they are the edges
  the pass would write.
* **The report** (:class:`DedupReport`) is the pydantic artifact, in the same spirit as
  ``BaselineSummary``: stamped, committed, and readable without a database.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final
from uuid import UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field

from src.jd_core.rules import ExactEdgeTopology

#: A stable namespace, so a file's synthetic id is a pure function of its archive path.
#: The same trick the baseline runner uses for its synthetic ``job_id``, and for the
#: same reason: a random id per run would make two runs over the same corpus
#: incomparable row-for-row — the opposite of an audit trail.
_ARCHIVE_NAMESPACE: Final[UUID] = UUID("6ba7b811-9dad-11d1-80b4-00c04fd430c8")


@dataclass(frozen=True, slots=True, order=False)
class DocumentRef:
    """The minimum a Tier-1 pass needs to know about a source document.

    ``id`` is the ``source_documents`` primary key when the pass runs against the
    database, and a deterministic ``uuid5`` of the archive path when the *report* runs
    against ``rows.jsonl`` (:meth:`for_path`) — which the database has not seen.
    """

    id: UUID
    sha256: str
    storage_ref: str
    filename: str | None = None

    @classmethod
    def for_path(
        cls, storage_ref: str, *, sha256: str, filename: str | None = None
    ) -> DocumentRef:
        """A ref whose id is a pure function of ``storage_ref`` — reproducible on any
        machine, on any run, without a database."""
        return cls(
            id=uuid5(_ARCHIVE_NAMESPACE, storage_ref),
            sha256=sha256,
            storage_ref=storage_ref,
            filename=filename,
        )


#: The ONE total order over a duplicate group's members. It answers two questions that
#: are **deliberately kept separate** — conflating them was a bug:
#:
#: * **the orientation** of every edge — ``source_a`` is always the earlier endpoint.
#:   This holds for BOTH topologies, unconditionally, and it never consults the anchor.
#: * **the default representative** — ``members[0]``, for a group that has no edges yet.
#:   An *established* group keeps the rep it already has (:meth:`DuplicateGroup.
#:   representative_or`), which may well **not** be ``members[0]``.
#:
#: Because orientation does not depend on who the rep is, ``star`` is always exactly the
#: subset of ``clique`` incident on the representative, and neither the two settings nor
#: two successive passes can ever write ``(b, a)`` beside ``(a, b)`` — which
#: ``uq_dedup_pair_tier``, being on the *ordered* triple, **cannot catch for us**.
#:
#: ⚠ The first attempt at the anchor fix oriented star edges *from the anchor*. That is
#: backwards for every member sorting before it — precisely the case an anchor exists to
#: create. Measured: 4 of 5 star edges reversed, and a later flip to ``clique`` produced
#: 19 edges with 4 mirrored pairs (a clean clique on 6 is 15, with none).
#:
#: It is keyed on ``storage_ref`` — the archive path — and NOT on ``id``: a database id
#: is a ``uuid4`` assigned at ingest, so ordering by it would make the representative a
#: function of *when a file happened to be ingested* rather than of the archive. ``id``
#: only breaks a tie that ``(storage_ref, filename)`` cannot, which the
#: ``uq_source_ref_sha256`` constraint makes impossible within a group anyway.
def order_key(ref: DocumentRef) -> tuple[str, str, str]:
    return (ref.storage_ref, ref.filename or "", str(ref.id))


@dataclass(frozen=True, slots=True)
class DuplicateGroup:
    """N archive files with the same SHA-256 — i.e. N files, not one file."""

    sha256: str
    #: Every member, sorted by :func:`order_key`. Nothing is ever dropped: a group of 11
    #: identical files is 11 documents and 10 redundant copies.
    members: tuple[DocumentRef, ...]

    @property
    def size(self) -> int:
        return len(self.members)

    @property
    def representative(self) -> DocumentRef:
        """The member a ``star`` anchors on **when the group is new**. **Not** "the real
        one" — the other members are equally real files, and that is the whole point of
        3.1.

        ⚠ For an *established* group, do not use this: use :meth:`representative_or`
        with the anchor already in the database. Re-deriving the rep from ``members[0]``
        on every pass lets a late arrival that sorts first re-anchor the star, and since
        the pass never deletes an edge, the stars accumulate into the clique.
        """
        return self.members[0]

    def representative_or(self, anchor: UUID | None) -> DocumentRef:
        """The group's **stable** representative: the one it already has, if it has one.

        ``anchor`` is the member the group's existing EXACT edges **hub on** (recovered
        by ``tier1._anchors``) — *not* their ``source_a_id``, which is decided by
        :func:`order_key` and says nothing about who the rep is. A group keeps the
        representative it was first given for as long as that member is still in the
        archive, so the star stays a star (N-1 edges) whatever order the members are
        ingested in.

        Falls back to :attr:`representative` for a group with no edges yet, or whose
        anchor has since been deleted from the ledger.

        This decides only **which member is the hub**. It does **not** decide which way
        an edge points — that is always ``(earlier, later)``. Keeping the two apart is
        the whole correctness argument; see :func:`order_key`.
        """
        if anchor is not None:
            for member in self.members:
                if member.id == anchor:
                    return member
        return self.members[0]

    @property
    def redundant(self) -> int:
        """Copies that carry no content the group does not already have."""
        return len(self.members) - 1


@dataclass(frozen=True, slots=True)
class EdgeSpec:
    """One ``dedup_edges`` row, before it is a row. Oriented by :func:`order_key`."""

    source_a_id: UUID
    source_b_id: UUID


class Tier1Result(BaseModel):
    """What one run of the Tier-1 DB pass did. ``edges_written == 0`` on a re-run over
    unchanged data is the idempotency guarantee, stated as a number."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    documents: int = Field(ge=0)
    groups: int = Field(ge=0)
    files_in_groups: int = Field(ge=0)
    redundant_files: int = Field(ge=0)
    topology: ExactEdgeTopology
    #: Edges this run INSERTED.
    edges_written: int = Field(ge=0)
    #: Edges that were already there (the constraint held; nothing was rewritten).
    edges_existing: int = Field(ge=0)


class GroupSample(BaseModel):
    """One duplicate group, named — so a reader can go and open the files."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    sha256: str
    size: int = Field(ge=2)
    byte_size: int | None = None
    #: Every member's filename, in canonical order. These are archive filenames, not JD
    #: content — the same class of data ``docs/baseline/errors.jsonl`` already commits.
    filenames: tuple[str, ...] = ()


class DedupReport(BaseModel):
    """The Tier-1 finding over a whole corpus — the committed artifact.

    Deliberately reports the two populations the archive actually has, because they
    differ and the difference is a finding, not a rounding error: **every file the walk
    found** (14,565, one of which has no hash at all — the 89 MB ``.rtf`` whose bytes
    the extractor's cap means we never read) versus the **12,592 distinct contents**
    among them.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    #: What was measured (an archive root, or the baseline artifact it was read from).
    source: str
    generated_at: dt.datetime

    total_documents: int = Field(ge=0)
    #: Documents carrying a SHA-256 — the only ones that can be grouped.
    hashed: int = Field(ge=0)
    #: ...and the ones that cannot (bytes never read). Counted, never dropped.
    unhashed: int = Field(ge=0)
    distinct_sha256: int = Field(ge=0)

    group_count: int = Field(ge=0)
    files_in_groups: int = Field(ge=0)
    #: ``files_in_groups - group_count``: the copies that carry no new content — and
    #: exactly the rows the pre-3.1 unique-sha256 ingest would never have created.
    redundant_files: int = Field(ge=0)
    #: ``redundant_files / hashed``. 0.0 (never ``None``) when there is nothing to
    #: report — a corpus with no duplicates has a redundancy rate of zero, which is a
    #: fact, not an absence.
    redundancy_rate: float = Field(ge=0.0, le=1.0)

    #: group size -> how many groups are that size. The shape that decides whether a
    #: clique topology is affordable.
    group_size_distribution: Mapping[int, int] = Field(default_factory=dict)
    largest_group_size: int = Field(ge=0)
    biggest_groups: tuple[GroupSample, ...] = ()

    # --- what the duplicates ARE: re-saves, or distinct positions sharing one JD? ---
    #
    # The most useful thing in the report, and it is COMPUTED, not narrated. It was
    # prose only in the first cut of 3.1 — a headline number `make dedup` could not
    # reproduce, which is exactly the shape of defect this project keeps paying for.
    # Derived from `BaselineRow.position_ids`; a group's positions are the union over
    # its members.
    #: Groups whose members carry MORE THAN ONE distinct position id — i.e. different
    #: positions sharing one byte-identical JD. This is real role redundancy, and it is
    #: a Phase-3.5 role cluster with the similarity already pinned at 1.0.
    groups_spanning_multiple_positions: int = Field(ge=0)
    #: Groups confined to a single position id — genuine re-saves of one JD.
    groups_within_one_position: int = Field(ge=0)
    #: Groups no member of which carries a position id at all (the filename did not
    #: yield one). Reported, never folded into either of the above.
    groups_without_position_id: int = Field(ge=0)
    #: Files sitting in a multi-position group.
    files_in_multi_position_groups: int = Field(ge=0)

    #: What each topology WOULD write, both reported — so HR-123 can be read off the
    #: artifact rather than taken on trust.
    edges_star: int = Field(ge=0)
    edges_clique: int = Field(ge=0)
    #: The live rulebook setting, and what it costs.
    topology: ExactEdgeTopology
    edges_at_topology: int = Field(ge=0)

    #: The rulebook that chose the topology.
    rules_version: str

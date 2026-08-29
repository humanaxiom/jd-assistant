"""What the one-of-a-kind measurement reports (HR-223).

The shape is the argument. ``TitleBuckets`` has no ``total`` field — it is derived —
because a total that can disagree with its parts is how "3,653 de-duplicated" hid 1,204
unexplained documents for weeks. And ``title_unjudgeable`` is a *first-class bucket*,
not a residue: a document whose title the parser never recovered is a question nobody
has answered, and folding it into either answer is the mistake this module avoids.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class TitleBuckets(BaseModel):
    """One population split four ways by what its titles say about uniqueness.

    Mutually exclusive and exhaustive: every document in the population lands in exactly
    one, and :attr:`total` is their sum by construction rather than by a second query.
    """

    model_config = ConfigDict(frozen=True)

    #: The normalised title appears exactly ONCE in the whole current-version archive —
    #: a genuinely singular SFU job, and the population HR-223 is really about.
    unique_title: int = Field(ge=0)
    #: The title is shared with a document that DID reach a role. Evidence of a dedup
    #: recall miss (plan.md D3), NOT of a job that exists once: the role already exists.
    shares_title_with_role_document: int = Field(ge=0)
    #: The title is shared only with other documents that also reached no role: a group
    #: the dedup never linked, so minting one role per document would duplicate it.
    shares_title_with_other_orphan: int = Field(ge=0)
    #: 🔴 COULD NOT EVALUATE — the parser recovered no usable title (the placeholder, an
    #: empty string, or a stem that is nothing but seniority markers). Reported, never
    #: folded: a filter that cannot publish what it cannot see is unfalsifiable.
    title_unjudgeable: int = Field(ge=0)

    @property
    def total(self) -> int:
        return (
            self.unique_title
            + self.shares_title_with_role_document
            + self.shares_title_with_other_orphan
            + self.title_unjudgeable
        )


class BucketedDocuments(BaseModel):
    """The pool and its CONTROL, always together.

    A control is what tells a finding from a broken probe: a high
    ``title_unjudgeable`` rate in the pool means something only if the rate among
    documents that DID cluster is lower. Returning the pool alone would invite exactly
    the reading that a 92%-vs-49% token scan already earned once.
    """

    model_config = ConfigDict(frozen=True)

    #: Documents in NO role and carrying NO ``dedup_edges`` row: the one-of-a-kind pool.
    pool: TitleBuckets
    #: Documents that DID reach a role, split the same way. The control.
    control: TitleBuckets


class SingletonSummary(BaseModel):
    """The full HR-223 measurement over the live Bank, as written to JSON.

    Every population it names is a count the reader can re-derive; nothing here is a
    ratio computed from a number that appears nowhere.
    """

    model_config = ConfigDict(frozen=True)

    #: The parse the whole measurement is scoped to. A summary that does not stamp this
    #: is unreadable a version later — v6→v7 moved 805 titles in one day.
    parser_version: str
    #: Source documents with a parse at :attr:`parser_version`.
    parsed_documents: int
    #: ...of which appear in the ``source_document_ids`` of a current canonical JD.
    documents_in_a_role: int
    #: ...of which do not. (``parsed_documents`` = this + :attr:`documents_in_a_role`.)
    orphans: int
    #: Parsed documents carrying no ``dedup_edges`` row at either end, in a role or not.
    documents_with_no_edge: int
    #: ⚠ Documents with no edge that reached a role ANYWAY — via the Builder, which
    #: mints roles from no source documents at all. Non-zero here is not a defect; it is
    #: the reason the pool is no-edge AND no-role rather than the edge check alone.
    documents_with_no_edge_in_a_role: int
    #: The pool and its control.
    buckets: BucketedDocuments
    #: Mean parsed qualifications per document, pool vs documents that reached a role.
    #: ⚠ Not a forecast: a minted role still faces every approval gate.
    #: ``None`` when the population is empty — 0.0 would read as "these documents have
    #: no qualifications", which is a finding rather than the absence of one.
    mean_qualifications_pool: float | None
    mean_qualifications_in_role: float | None
    #: The median beside every mean. A mean over a thousand documents is an aggregate,
    #: and an aggregate is where this project keeps hiding things — one document with 40
    #: parsed qualifications drags a mean anywhere it likes.
    median_qualifications_pool: float | None
    median_qualifications_in_role: float | None
    #: A few unique titles verbatim, so the number can be eyeballed rather than trusted.
    unique_title_examples: tuple[str, ...] = ()

"""Neo4j writer for JD document/section embeddings (Phase 3.2b).

Schema (``core/db/migrations/002_jd_vectors.cypher`` — indexes and uniqueness
constraints already exist; this module never creates them)::

    (:JDDocument {id: <source_document_id>})
        -[:HAS_SECTION]->
    (:JDSection {id: "<source_document_id>:<section>"})

**Node identity keys on ``source_document_id``, NOT ``parsed_jd_id``.** Tier-3 dedup
writes ``DedupEdge(source_a_id, source_b_id)`` against ``source_documents`` ids
(:mod:`src.jd_bank.dedup`), so a vector hit has to join to that with no lookup table
in between — and it stays stable across a re-parse, because a document's identity in
the archive does not change when the parser version does. ``parsed_jd_id`` still
rides along as a property (the back-reference ``002``'s header asks for), it just
does not decide the node's ``id``.

**Skip-first, exactly like ``dedup.run_tier1``:** one pre-fetch query of every
existing node's content identity (:func:`fetch_existing_document_keys` /
:func:`fetch_existing_section_keys`), diffed in memory by the caller — this module
does not decide what to skip, it only fetches what exists and writes what it is
told to. A ``MERGE`` on the node's stable ``id`` means a re-embed overwrites
in place: same id, no orphan left behind.
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from neo4j import AsyncDriver

from src.jd_bank.embeddings.models import DocumentWrite, NodeKey, SectionWrite

_FETCH_DOCUMENT_KEYS = """
MATCH (d:JDDocument)
RETURN d.id AS id, d.text_sha256 AS text_sha256, d.model AS model,
       d.embed_stamp AS embed_stamp
"""

_FETCH_SECTION_KEYS = """
MATCH (s:JDSection)
RETURN s.id AS id, s.text_sha256 AS text_sha256, s.model AS model,
       s.embed_stamp AS embed_stamp
"""

# MERGE on `id` (the constrained, unique key from migration 002) — never on any
# other property — so a re-embed overwrites the SAME node rather than creating a
# second one beside it.
_WRITE_DOCUMENTS = """
UNWIND $rows AS row
MERGE (d:JDDocument {id: row.id})
SET d.embedding = row.embedding,
    d.model = row.model,
    d.dimensions = row.dimensions,
    d.text_sha256 = row.text_sha256,
    d.text_chars = row.text_chars,
    d.truncated = row.truncated,
    d.embed_stamp = row.embed_stamp,
    d.serializer_version = row.serializer_version,
    d.source_document_id = row.source_document_id,
    d.parsed_jd_id = row.parsed_jd_id,
    d.parser_version = row.parser_version
"""

_WRITE_SECTIONS = """
UNWIND $rows AS row
MERGE (s:JDSection {id: row.id})
SET s.embedding = row.embedding,
    s.model = row.model,
    s.dimensions = row.dimensions,
    s.text_sha256 = row.text_sha256,
    s.text_chars = row.text_chars,
    s.truncated = row.truncated,
    s.embed_stamp = row.embed_stamp,
    s.serializer_version = row.serializer_version,
    s.source_document_id = row.source_document_id,
    s.parsed_jd_id = row.parsed_jd_id,
    s.parser_version = row.parser_version,
    s.section = row.section,
    s.document_id = row.source_document_id
WITH s, row
MATCH (d:JDDocument {id: row.source_document_id})
MERGE (d)-[:HAS_SECTION]->(s)
"""


async def fetch_existing_document_keys(driver: AsyncDriver) -> dict[UUID, NodeKey]:
    """Every ``(:JDDocument)``'s content identity, keyed by its ``source_document_id``.

    ONE query for the whole corpus — the pre-fetch half of skip-first. A node with
    a null ``id`` (should not exist, given the migration's uniqueness constraint)
    is defensively skipped rather than raising ``UUID(None)``.
    """
    async with driver.session() as session:
        result = await session.run(_FETCH_DOCUMENT_KEYS)
        records = [record async for record in result]
    return {
        UUID(record["id"]): NodeKey(
            record["text_sha256"], record["model"], record["embed_stamp"]
        )
        for record in records
        if record["id"] is not None
    }


async def fetch_existing_section_keys(driver: AsyncDriver) -> dict[str, NodeKey]:
    """Every ``(:JDSection)``'s content identity, keyed by its own ``id`` string
    (``"<source_document_id>:<section>"`` — see :meth:`SectionWrite.section_id`)."""
    async with driver.session() as session:
        result = await session.run(_FETCH_SECTION_KEYS)
        records = [record async for record in result]
    return {
        record["id"]: NodeKey(
            record["text_sha256"], record["model"], record["embed_stamp"]
        )
        for record in records
        if record["id"] is not None
    }


def _document_payload(row: DocumentWrite) -> dict[str, object]:
    return {
        "id": str(row.source_document_id),
        "source_document_id": str(row.source_document_id),
        "parsed_jd_id": str(row.parsed_jd_id),
        "parser_version": row.parser_version,
        "text_sha256": row.text_sha256,
        "text_chars": row.text_chars,
        "truncated": row.truncated,
        "embedding": row.embedding,
        "model": row.model,
        "dimensions": row.dimensions,
        "embed_stamp": row.embed_stamp,
        "serializer_version": row.serializer_version,
    }


def _section_payload(row: SectionWrite) -> dict[str, object]:
    return {
        "id": row.section_id,
        "source_document_id": str(row.source_document_id),
        "parsed_jd_id": str(row.parsed_jd_id),
        "parser_version": row.parser_version,
        "section": row.section,
        "text_sha256": row.text_sha256,
        "text_chars": row.text_chars,
        "truncated": row.truncated,
        "embedding": row.embedding,
        "model": row.model,
        "dimensions": row.dimensions,
        "embed_stamp": row.embed_stamp,
        "serializer_version": row.serializer_version,
    }


#: Delete every ``JDSection`` hanging off a document that this run's plan does NOT
#: include. See :func:`prune_sections` for why a MERGE-only runner is not enough.
#:
#: ``collect`` drops the nulls an ``OPTIONAL MATCH`` produces for a document with no
#: doomed sections, so ``FOREACH`` over the collected list is a clean no-op there.
_PRUNE_SECTIONS = """
UNWIND $rows AS row
OPTIONAL MATCH (s:JDSection {document_id: row.id})
WHERE NOT s.section IN row.keep
WITH collect(s) AS doomed
FOREACH (n IN doomed | DETACH DELETE n)
RETURN size(doomed) AS pruned
"""

#: Delete a document AND its sections outright — for a JD that no longer serializes
#: to any text at all. Sections are matched on the ``document_id`` PROPERTY rather
#: than by traversing ``HAS_SECTION``, so a section left edgeless by a partial
#: earlier run is still reachable and still gets cleaned up.
_PRUNE_DOCUMENTS = """
UNWIND $ids AS id
OPTIONAL MATCH (d:JDDocument {id: id})
OPTIONAL MATCH (s:JDSection {document_id: id})
WITH collect(DISTINCT d) AS docs, collect(DISTINCT s) AS sections
FOREACH (n IN docs | DETACH DELETE n)
FOREACH (n IN sections | DETACH DELETE n)
RETURN size(docs) + size(sections) AS pruned
"""


async def write_documents(driver: AsyncDriver, rows: Sequence[DocumentWrite]) -> None:
    """``MERGE`` a batch of ``(:JDDocument)`` nodes. A no-op on an empty batch — the
    caller (the runner) is what decides batch size; this never re-batches."""
    if not rows:
        return
    async with driver.session() as session:
        await session.run(_WRITE_DOCUMENTS, rows=[_document_payload(r) for r in rows])


async def write_sections(driver: AsyncDriver, rows: Sequence[SectionWrite]) -> None:
    """``MERGE`` a batch of ``(:JDSection)`` nodes + their ``HAS_SECTION`` edge.

    Requires the owning ``(:JDDocument)`` to already exist — the runner always
    writes documents before sections within a batch. If the document is somehow
    missing, the ``MATCH`` half of the query simply finds nothing (a no-op, not an
    error): the section node is still written, but with no ``HAS_SECTION`` edge
    until a later pass writes the document too.
    """
    if not rows:
        return
    async with driver.session() as session:
        await session.run(_WRITE_SECTIONS, rows=[_section_payload(r) for r in rows])


async def prune_sections(
    driver: AsyncDriver, keep: Sequence[tuple[UUID, Sequence[str]]]
) -> int:
    """Delete every ``JDSection`` of these documents that is **not** in ``keep``.

    **A MERGE-only runner leaves stale vectors LIVE IN THE QUERYABLE INDEX**, and
    that is not a cosmetic leak: ``db.index.vector.queryNodes`` keeps returning the
    orphan, so Tier-3 dedup and search (3.3/3.4) would retrieve a section that the
    rulebook no longer says exists. The stamp forces a re-embed of what is
    *planned*; nothing else reconciles what is *no longer planned*. Three reachable
    paths get there, and none is hypothetical:

    * **a section is dropped from** ``embeddings.section_vectors`` — which HR-130's
      own ``impact_if_changed`` explicitly invites HR to do. The stamp moves and
      everything re-embeds, but the orphaned ``<doc>:qualifications`` nodes are
      simply never touched again;
    * **a re-parse pushes a section below** ``min_section_chars`` (or HR raises the
      threshold) — the section stops being planned while the document lives on;
    * a section's content disappears entirely from a re-parsed JD.

    ``keep`` is ``(source_document_id, the section names planned for it this run)``
    — so pruning is scoped to the documents this run actually looked at, and a
    ``--limit``ed run cannot delete nodes belonging to rows it never read.

    Returns the number of nodes deleted.
    """
    if not keep:
        return 0
    rows = [{"id": str(doc_id), "keep": list(sections)} for doc_id, sections in keep]
    async with driver.session() as session:
        result = await session.run(_PRUNE_SECTIONS, rows=rows)
        record = await result.single()
    return int(record["pruned"]) if record else 0


async def prune_documents(driver: AsyncDriver, ids: Sequence[UUID]) -> int:
    """Delete these documents **and all their sections** — for a JD that no longer
    serializes to any text at all.

    The other half of the reconcile (see :func:`prune_sections`): a JD that used to
    have content and now parses to nothing (a segmenter change, a re-ingest of
    corrected bytes) would otherwise keep its **stale** ``JDDocument`` vector in the
    index forever, because the runner's empty-text branch simply declines to write a
    node — it never went looking for one that was already there.

    Returns the number of nodes deleted.
    """
    if not ids:
        return 0
    async with driver.session() as session:
        result = await session.run(_PRUNE_DOCUMENTS, ids=[str(i) for i in ids])
        record = await result.single()
    return int(record["pruned"]) if record else 0

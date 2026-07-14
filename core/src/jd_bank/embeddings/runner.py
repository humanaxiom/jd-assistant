"""Postgres ``parsed_jds`` -> Neo4j embeddings runner (Phase 3.2b).

The chain, per candidate row::

    parsed_jds (Postgres) -> SFUJobDescription -> serialize_document / serialize_section
        -> skip-first diff against Neo4j's existing nodes -> embed the misses
        -> MERGE into Neo4j (document + section nodes, HAS_SECTION edges)

**Skip-first, exactly like ``dedup.run_tier1``:** one pre-fetch of every existing
node's content identity, diffed in memory, so a pass over an unchanged corpus
embeds nothing and calls Ollama zero times. **In-run memo by ``text_sha256``:**
1,972 archive files are byte-identical duplicates (Tier-1's own finding) and
serialize identically, so each distinct text is embedded once per run and written
to every node that wants it — a pure optimization, never a write-time collapse
(the 3.1 migration spent effort UN-doing exactly that shape for
``source_documents``, and this module must not re-introduce it for embeddings).

**Empty text -> no node, ever.** A JD whose configured ``document_sections`` are
all empty (the 34.5% WJQ-template case the segmenter cannot read) is counted as
``documents_empty``, never embedded as ``""``. Same for a section under
``min_section_chars``. Cosine similarity over a zero vector is undefined, and
Neo4j would index one without complaint — the guard is in
:mod:`src.jd_core.bank.embed_text`, not here, but this module is what must never
override it.

**MERGE is not enough: the pass also RECONCILES.** A node that should no longer
exist is not merely untidy — it stays **live in the queryable vector index**, so
Tier-3 dedup and search would retrieve a section the rulebook no longer says
exists. The stamp forces a re-embed of what is *planned*; nothing about a MERGE
reconciles what is *no longer planned*. So every run also prunes
(:func:`~src.jd_bank.embeddings.store.prune_sections` /
:func:`~src.jd_bank.embeddings.store.prune_documents`): a section dropped from
``section_vectors`` (which HR-130 explicitly invites HR to do), a section that
falls under ``min_section_chars``, and a JD that re-parses to empty all lose their
nodes rather than keeping a stale vector. Pruning is scoped to the documents this
run actually read, so a ``--limit``ed run cannot delete what it never looked at.

**One over-long text must not cost a whole batch its vectors.** A 400 is raised for
the *batch*, not the text — so a naive ``except: continue`` discards up to
``batch_size - 1`` innocent JDs, **and it never heals**: the sha-keyed plan is
rebuilt in the same deterministic order next run, so the same batch fails the same
way, forever, while the process exits 0. On a 400 the chunk is therefore retried
**one text at a time**, and only the genuinely over-long text is recorded in
``bad_requests``. HR-126's ``impact_if_changed`` leans on "the runner catches and
skips a 400" as the safety story for raising ``max_chars``; this is what makes that
story true at batch granularity rather than only at text granularity.

**Does not commit the Postgres session** — it only reads. Neo4j writes are
auto-commit per statement (the driver's normal ``session.run`` semantics) and are
issued in ``batch_size`` chunks, never one statement for the whole archive — the
same "commit in batches" discipline :func:`~src.jd_bank.ingest.driver.
run_archive_ingest` uses, adapted to Neo4j's transaction model.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import NamedTuple
from uuid import UUID

from neo4j import AsyncDriver
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.jd_bank.db.models import ParsedJDRow
from src.jd_bank.embeddings.client import EmbedClient, EmbeddingBadRequestError
from src.jd_bank.embeddings.models import (
    DocumentWrite,
    EmbedRunResult,
    NodeKey,
    SectionWrite,
)
from src.jd_bank.embeddings.store import (
    fetch_existing_document_keys,
    fetch_existing_section_keys,
    prune_documents,
    prune_sections,
    write_documents,
    write_sections,
)
from src.jd_core.bank.embed_text import (
    SERIALIZER_VERSION,
    SerializedText,
    serialize_document,
    serialize_section,
)
from src.jd_core.models.parsed_jd import SFUJobDescription
from src.jd_core.parser import PARSER_VERSION
from src.jd_core.rules import Rules, get_rules
from src.settings import get_settings


class _DocPlanItem(NamedTuple):
    source_document_id: UUID
    parsed_jd_id: UUID
    parser_version: str
    serialized: SerializedText


class _SectionPlanItem(NamedTuple):
    source_document_id: UUID
    parsed_jd_id: UUID
    parser_version: str
    section: str
    serialized: SerializedText


async def _candidate_rows(
    session: AsyncSession, *, limit: int | None
) -> Sequence[tuple[UUID, UUID, str, dict[str, object]]]:
    """Every ``parsed_jds`` row at the LIVE parser version — mirrors
    ``ingest.driver._already_parsed``'s filter, so a stale re-parse at an old
    ``parser_version`` is never (re-)embedded."""
    stmt = select(
        ParsedJDRow.source_document_id,
        ParsedJDRow.id,
        ParsedJDRow.parser_version,
        ParsedJDRow.parsed,
    ).where(ParsedJDRow.parser_version == PARSER_VERSION)
    if limit is not None:
        stmt = stmt.limit(limit)
    result = await session.execute(stmt)
    return [(row[0], row[1], row[2], row[3]) for row in result.all()]


def _mismatches(
    current: NodeKey | None, serialized: SerializedText, *, model: str, embed_stamp: str
) -> bool:
    """``True`` when ``current`` (the node's existing content identity, or ``None``
    if there is no node yet) does not match what ``serialized`` would produce —
    i.e. this slot needs a fresh embed."""
    return current != NodeKey(serialized.text_sha256, model, embed_stamp)


async def run_embeddings(
    pg_session: AsyncSession,
    neo4j_driver: AsyncDriver,
    *,
    rules: Rules | None = None,
    client: EmbedClient | None = None,
    limit: int | None = None,
    batch_size: int | None = None,
) -> EmbedRunResult:
    """Embed every eligible ``parsed_jds`` row that is not already up to date.

    Re-runnable, exactly like :func:`~src.jd_bank.dedup.tier1.run_tier1`: a pass
    over an unchanged corpus reports ``documents_embedded == sections_embedded ==
    embed_calls == 0`` and rewrites no node.
    """
    rulebook = rules if rules is not None else get_rules()
    embeddings_rules = rulebook.embeddings
    embed_client = client if client is not None else EmbedClient(rules=rulebook)
    # ONE home for the batch size (`settings.embed_batch_size`) — it was briefly held
    # here as a second constant with the same value 64, which is precisely the
    # `max_listed` duplicate-knob shape HANDOFF warns about: nothing keeps two copies
    # in step. It is OPERATIONAL, not a rulebook decision (measured: a batched call
    # returns identical vectors to one-at-a-time), which is why it lives in settings
    # and not in `embeddings.yaml`.
    batch = batch_size if batch_size is not None else get_settings().embed_batch_size

    embed_stamp = embeddings_rules.stamp
    model = embeddings_rules.model

    rows = await _candidate_rows(pg_session, limit=limit)
    existing_docs = await fetch_existing_document_keys(neo4j_driver)
    existing_sections = await fetch_existing_section_keys(neo4j_driver)

    documents_empty = 0
    sections_skipped_short = 0
    doc_plan: list[_DocPlanItem] = []
    section_plan: list[_SectionPlanItem] = []
    #: source_document_id -> the sections this run PLANS for it. The reconcile's
    #: keep-list: anything attached to the document and not in here gets pruned.
    planned_sections: dict[UUID, list[str]] = {}
    #: Documents that serialize to nothing at all — they get no node, and any node
    #: they already have (from a run before the JD lost its content) is deleted.
    empty_document_ids: list[UUID] = []

    for source_document_id, parsed_jd_id, parser_version, parsed in rows:
        jd = SFUJobDescription.model_validate(parsed)

        doc_text = serialize_document(jd, embeddings_rules)
        if not doc_text.text:
            documents_empty += 1
            empty_document_ids.append(source_document_id)
        else:
            doc_plan.append(
                _DocPlanItem(source_document_id, parsed_jd_id, parser_version, doc_text)
            )
            planned_sections.setdefault(source_document_id, [])

        for section in embeddings_rules.section_vectors:
            section_text = serialize_section(jd, embeddings_rules, section)
            if section_text is None:
                sections_skipped_short += 1
                continue
            section_plan.append(
                _SectionPlanItem(
                    source_document_id,
                    parsed_jd_id,
                    parser_version,
                    section,
                    section_text,
                )
            )
            if source_document_id in planned_sections:
                planned_sections[source_document_id].append(section)

    doc_misses = [
        item
        for item in doc_plan
        if _mismatches(
            existing_docs.get(item.source_document_id),
            item.serialized,
            model=model,
            embed_stamp=embed_stamp,
        )
    ]
    documents_unchanged = len(doc_plan) - len(doc_misses)

    section_misses = [
        item
        for item in section_plan
        if _mismatches(
            existing_sections.get(f"{item.source_document_id}:{item.section}"),
            item.serialized,
            model=model,
            embed_stamp=embed_stamp,
        )
    ]
    sections_unchanged = len(section_plan) - len(section_misses)

    # In-run memo by text_sha256: identical content (archive duplicates) embeds
    # ONCE and is written to every node that wants it.
    to_embed: dict[str, str] = {}
    for doc_item in doc_misses:
        to_embed.setdefault(doc_item.serialized.text_sha256, doc_item.serialized.text)
    for section_item in section_misses:
        to_embed.setdefault(
            section_item.serialized.text_sha256, section_item.serialized.text
        )

    total_slots = len(doc_misses) + len(section_misses)
    memo: dict[str, list[float]] = {}
    embed_calls = 0
    bad_requests = 0

    shas = list(to_embed)
    for start in range(0, len(shas), batch):
        chunk = shas[start : start + batch]
        texts = [to_embed[sha] for sha in chunk]
        embed_calls += 1  # counted BEFORE the call: a 400 is a round-trip too
        try:
            vectors = await embed_client.embed_batch(texts)
        except EmbeddingBadRequestError:
            # The server 400s the BATCH, not the offending text. Writing the whole
            # chunk off would discard up to `batch - 1` innocent JDs' vectors — and
            # it would never heal, because `to_embed` is a sha-keyed dict rebuilt in
            # the same deterministic order next run, so the identical batch fails
            # identically, forever, while the process exits 0. Isolate instead: only
            # the genuinely over-long text is skipped.
            for sha, text in zip(chunk, texts, strict=True):
                embed_calls += 1
                try:
                    single = await embed_client.embed_batch([text])
                except EmbeddingBadRequestError:
                    bad_requests += 1
                    continue
                memo[sha] = single[0]
            continue
        for sha, vector in zip(chunk, vectors, strict=True):
            memo[sha] = vector

    document_writes = [
        DocumentWrite(
            source_document_id=item.source_document_id,
            parsed_jd_id=item.parsed_jd_id,
            parser_version=item.parser_version,
            text_sha256=item.serialized.text_sha256,
            text_chars=item.serialized.text_chars,
            truncated=item.serialized.truncated,
            embedding=memo[item.serialized.text_sha256],
            model=model,
            dimensions=embeddings_rules.dimensions,
            embed_stamp=embed_stamp,
            serializer_version=SERIALIZER_VERSION,
        )
        for item in doc_misses
        if item.serialized.text_sha256 in memo
    ]
    section_writes = [
        SectionWrite(
            source_document_id=item.source_document_id,
            parsed_jd_id=item.parsed_jd_id,
            parser_version=item.parser_version,
            section=item.section,
            text_sha256=item.serialized.text_sha256,
            text_chars=item.serialized.text_chars,
            truncated=item.serialized.truncated,
            embedding=memo[item.serialized.text_sha256],
            model=model,
            dimensions=embeddings_rules.dimensions,
            embed_stamp=embed_stamp,
            serializer_version=SERIALIZER_VERSION,
        )
        for item in section_misses
        if item.serialized.text_sha256 in memo
    ]

    # Documents BEFORE sections in every batch: a section's HAS_SECTION edge needs
    # its document to already exist (store.write_sections' docstring).
    for start in range(0, len(document_writes), batch):
        await write_documents(neo4j_driver, document_writes[start : start + batch])
    for start in range(0, len(section_writes), batch):
        await write_sections(neo4j_driver, section_writes[start : start + batch])

    # THE RECONCILE — a MERGE-only pass leaves a stale vector live in the queryable
    # index (see the module docstring). Runs over the whole PLAN, not just the rows
    # that were re-embedded: a section can stop being planned (dropped from
    # `section_vectors`, or fallen under `min_section_chars`) while its document's
    # own text, and therefore its skip-first key, is completely unchanged.
    nodes_pruned = 0
    keep = list(planned_sections.items())
    for start in range(0, len(keep), batch):
        nodes_pruned += await prune_sections(neo4j_driver, keep[start : start + batch])
    for start in range(0, len(empty_document_ids), batch):
        nodes_pruned += await prune_documents(
            neo4j_driver, empty_document_ids[start : start + batch]
        )

    return EmbedRunResult(
        documents_seen=len(rows),
        documents_embedded=len(document_writes),
        documents_unchanged=documents_unchanged,
        documents_empty=documents_empty,
        sections_embedded=len(section_writes),
        sections_unchanged=sections_unchanged,
        sections_skipped_short=sections_skipped_short,
        nodes_pruned=nodes_pruned,
        embed_calls=embed_calls,
        embed_texts_reused_memo=max(0, total_slots - len(to_embed)),
        bad_requests=bad_requests,
        model=model,
        dimensions=embeddings_rules.dimensions,
        embed_stamp=embed_stamp,
        serializer_version=SERIALIZER_VERSION,
    )

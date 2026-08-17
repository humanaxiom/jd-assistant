"""Find an existing JD and start from it (Phase 5.4).

Two capabilities for the JD Builder's "start from an existing JD" flow:

* :func:`search_similar_jds` — semantic search. Embeds the query with the same
  self-hosted model the archive was embedded with (egress-guarded, NN #5), runs a
  top-k query over Neo4j's ``jd_document_embeddings`` vector index (the read side of
  Phase 3.2b — 3.2b only ever wrote), and joins each hit back to its parsed JD in
  Postgres for a title + facets.
* :func:`jd_to_answers` — the clone transform. Turns an existing
  :class:`~src.jd_core.models.parsed_jd.SFUJobDescription` back into
  :class:`~src.jd_bank.composer.answers.ComposerAnswers` so the guided Builder can be
  pre-filled from it. The inverse of
  :func:`~src.jd_bank.composer.assemble.assemble_jd`.

**Corpus.** Two vector stores, deliberately separate (``cadfc30``): the archive
**document** embeddings (``jd_document_embeddings`` over ``(:JDDocument)``, keyed on
``source_document_id``) and the **harmonized role** embeddings
(``jd_role_embeddings`` over ``(:JDRole)``, one node per cluster, migration ``003``,
written by ``make embed-roles``). A role is a different unit from an archive
document, and folding them into one index would quietly corrupt the next
``MATCH (d:JDDocument)`` corpus count. Both are **JDFN-scoped** (CUPE/WJQ excluded —
the Builder authors the JDFN template, HR-143).

The older note here — *"the only vectors that exist are the archive document
embeddings; published canonicals are not yet embedded"* — was true at v1 and is now
**false**: the Bank can search its own output. What is still deliberately absent is a
write-on-publish hook; ``make embed-roles`` is a manual, idempotent, skip-first runner
because publishing must never depend on the GPU being up.

**Four passes, ranked.** role-title → document-title (both plain Postgres ``ILIKE``)
→ role-semantic → archive-semantic. The title passes rank ABOVE the vector ones and
carry **no score**: the document vectors deliberately exclude the title
(``embeddings.yaml: include_title_in_document: false``), which is what makes
``bank/similarity`` title-agnostic for dedup — so a title query has nothing to match
on, and quoting a similarity for a title hit would invent one.

**Read-only.** Nothing here writes or publishes; cloning pre-fills a draft the author
still builds and submits through the review queue (NN #1).
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from typing import Any, Literal
from uuid import UUID

from neo4j import AsyncDriver
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.jd_bank.composer.answers import AnswerContract
from src.jd_bank.db.models import CanonicalJD, Cluster, ParsedJDRow
from src.jd_bank.embeddings.client import EmbedClient
from src.jd_core.models.parsed_jd import SFUJobDescription
from src.jd_core.rules import Rules, get_rules

logger = logging.getLogger(__name__)

#: The Neo4j vector index built in ``core/db/migrations/002_jd_vectors.cypher``.
_DOCUMENT_INDEX = "jd_document_embeddings"

#: The employee group whose JDs are NOT JDFN (CUPE uses the WJQ instrument, HR-143) —
#: excluded from Builder search results, which only ever start a JDFN draft.
_NON_JDFN_GROUP = "cupe"

#: Over-fetch factor: the vector index may return CUPE/WJQ hits or documents whose
#: parsed JD has since been pruned, so fetch more than ``limit`` and filter down.
_OVERFETCH = 3

#: The harmonized-role vector index (migration 003, written by
#: :mod:`src.jd_bank.embeddings.roles`). Separate from the document index because a
#: role and an archive file are different units — see that module's header.
_ROLE_INDEX = "jd_role_embeddings"

_NEAREST = """
CALL db.index.vector.queryNodes($index, $k, $vector)
YIELD node, score
RETURN node.id AS id, node.embed_stamp AS embed_stamp, score
ORDER BY score DESC
"""

_NEAREST_ROLES = """
CALL db.index.vector.queryNodes($index, $k, $vector)
YIELD node, score
RETURN node.id AS id, node.title AS title,
       node.employee_group AS employee_group,
       node.embed_stamp AS embed_stamp, score
ORDER BY score DESC
"""


def _comparable(
    records: Sequence[Mapping[str, Any]], *, live_stamp: str, what: str
) -> list[Mapping[str, Any]]:
    """The records whose vector was produced by the CONFIGURATION NOW IN FORCE.

    ⚠ **Why this filter exists at all.** ``embed_stamp`` is written onto every node
    (``make embed`` / ``make embed-roles``) and, until now, was never read back at
    query time. Retune an embedding knob — ``model``, ``max_chars``,
    ``include_title_in_document`` — and the query vector is produced by the new
    configuration while the stored vectors are still the old one. The cosines between
    them are not *worse*, they are **meaningless**, and nothing said so: the page
    rendered an arbitrary ordering as a similarity ranking.

    Both runners are idempotent and skip-first, so PARTIAL staleness is the realistic
    state — mid re-embed, some nodes are new and some are old. Dropping the stale ones
    keeps every hit that IS shown genuinely comparable to the query, which is the
    property a ranking needs; the shortfall is logged so an operator learns the index
    needs `make embed` rather than silently seeing thinner results.

    This is the Phase-5.9 rule applied to retrieval: never present a number the data
    cannot support.
    """
    comparable = [r for r in records if r["embed_stamp"] == live_stamp]
    dropped = len(records) - len(comparable)
    if dropped:
        logger.warning(
            "%d of %d %s vectors were embedded under a different configuration than "
            "the one in force (%s) and were excluded from the ranking — re-run the "
            "embedding pass to restore full coverage",
            dropped,
            len(records),
            what,
            live_stamp,
        )
    return comparable


class SearchHit(BaseModel):
    """One "start from this" candidate: the archive document, its role title and facets,
    and HOW it was found.

    ``match`` distinguishes two genuinely different measures, which is why they are
    not flattened into one number. A ``semantic`` hit carries a cosine ``score``; a
    ``title`` hit carries ``None``, because it was not found by distance and quoting a
    similarity for it would invent one. The UI renders them differently for that reason.
    """

    model_config = ConfigDict(extra="forbid")

    #: The archive document — ``None`` for a ``role_title`` hit, which is a harmonized
    #: ROLE (a cluster), not a document in the archive.
    source_document_id: UUID | None = None
    #: The harmonized role this hit starts from. Set for ``role_title``; resolved by the
    #: route for the document hits.
    cluster_id: UUID | None = None
    title: str
    #: What tells two same-titled roles apart. SFU genuinely has 9 distinct "Academic
    #: Advisor" roles across 6 departments — they are different roles, not duplicates,
    #: and without this the rows are indistinguishable. ``None`` when nothing is
    #: recorded anywhere (72 of 791 ambiguous roles); never fabricated.
    department: str | None = None
    employee_group: str | None = None
    #: Cosine similarity to the query — ``None`` for a title match (see above).
    score: float | None = Field(default=None, ge=-1.0, le=1.0)
    match: Literal["role_title", "title", "semantic"] = "semantic"


async def _nearest_source_ids(
    driver: AsyncDriver, vector: Sequence[float], k: int, *, live_stamp: str
) -> list[tuple[UUID, float]]:
    """Top-``k`` archive documents by cosine similarity to ``vector`` — the Neo4j
    vector-index read. Returns ``(source_document_id, score)`` best-first, and only
    for vectors embedded under the configuration now in force (see
    :func:`_comparable`)."""
    async with driver.session() as session:
        result = await session.run(
            _NEAREST, index=_DOCUMENT_INDEX, k=k, vector=list(vector)
        )
        records = [record async for record in result]
    usable = _comparable(records, live_stamp=live_stamp, what="archive document")
    return [
        (UUID(record["id"]), float(record["score"]))
        for record in usable
        if record["id"] is not None
    ]


async def _nearest_role_ids(
    driver: AsyncDriver, vector: Sequence[float], k: int, *, live_stamp: str
) -> list[tuple[UUID, str, str | None, float]]:
    """Top-``k`` harmonized ROLES by cosine similarity — ``(cluster_id, title,
    employee_group, score)`` best-first.

    Returns empty (not an error) when the role index does not exist yet: the index is
    created by migration 003 and populated by ``make embed-roles``, and search must
    keep working on a stack where neither has run.
    """
    try:
        async with driver.session() as session:
            result = await session.run(
                _NEAREST_ROLES, index=_ROLE_INDEX, k=k, vector=list(vector)
            )
            records = [record async for record in result]
    except Exception:  # noqa: BLE001 — no index yet: degrade, never break search
        return []
    usable = _comparable(records, live_stamp=live_stamp, what="harmonized role")
    return [
        (
            UUID(record["id"]),
            str(record["title"] or ""),
            record["employee_group"],
            float(record["score"]),
        )
        for record in usable
        if record["id"] is not None
    ]


async def _load_latest_parsed(
    session: AsyncSession, ids: Sequence[UUID]
) -> dict[UUID, SFUJobDescription]:
    """The most recent parsed JD for each source document id (empty for ids with no
    parse row — a pruned/unparsed document is simply skipped)."""
    if not ids:
        return {}
    rows = (
        await session.scalars(
            select(ParsedJDRow)
            .where(ParsedJDRow.source_document_id.in_(list(ids)))
            .order_by(ParsedJDRow.source_document_id, ParsedJDRow.created_at.desc())
        )
    ).all()
    latest: dict[UUID, SFUJobDescription] = {}
    for row in rows:
        if row.source_document_id not in latest:  # first = newest per the order_by
            latest[row.source_document_id] = SFUJobDescription.model_validate(
                row.parsed
            )
    return latest


def _title_rank(title: str, query: str) -> int:
    """Order among title matches: exact, then prefix, then contains. Lower is better."""
    lowered, wanted = title.strip().lower(), query.strip().lower()
    if lowered == wanted:
        return 0
    if lowered.startswith(wanted):
        return 1
    return 2


async def _with_departments(
    session: AsyncSession, hits: list[SearchHit]
) -> list[SearchHit]:
    """Label every role hit with its department, in one pass over the finished page.

    Done at the single exit point rather than inside each pass so the lookup happens
    once for the whole page regardless of which pass produced which hit.
    """
    role_ids = [h.cluster_id for h in hits if h.cluster_id is not None]
    if not role_ids:
        return hits
    departments = await _role_departments(session, role_ids)
    for hit in hits:
        if hit.department is None and hit.cluster_id is not None:
            hit.department = departments.get(hit.cluster_id)
    return hits


async def _role_departments(
    session: AsyncSession, cluster_ids: Sequence[UUID]
) -> dict[UUID, str]:
    """``{cluster_id: department}`` for the roles shown on one page of results.

    The canonical's own ``department`` first; where it is blank, the first department
    any of the role's SOURCE documents states. Measured over the 791 roles that share
    a title with another role: 570 carry one themselves, and 149 of the remaining 221
    are recoverable from sources — 91% together. The last 72 stay ``None``, because an
    invented department is worse than an unlabelled row.

    Resolved here rather than stored on the ``(:JDRole)`` node on purpose: this is
    display metadata, and folding it into the node would tie it to the vector's
    content identity, so a department correction would not refresh until the TEXT
    changed. A page shows at most ``limit`` roles, so this is two small queries.
    """
    if not cluster_ids:
        return {}
    wanted = list(dict.fromkeys(cluster_ids))
    current = (
        select(
            CanonicalJD.cluster_id,
            func.max(CanonicalJD.version).label("version"),
        )
        .where(CanonicalJD.cluster_id.in_(wanted))
        .group_by(CanonicalJD.cluster_id)
        .subquery()
    )
    rows = (
        await session.execute(
            select(CanonicalJD).join(
                current,
                (CanonicalJD.cluster_id == current.c.cluster_id)
                & (CanonicalJD.version == current.c.version),
            )
        )
    ).scalars()

    departments: dict[UUID, str] = {}
    fallback_sources: dict[UUID, list[UUID]] = {}
    for row in rows:
        content = row.content or {}
        stated = content.get("department")
        if stated:
            departments[row.cluster_id] = str(stated)
            continue
        member_ids = [
            UUID(str(entry["source_id"]))
            for entry in (row.source_document_ids or [])
            if isinstance(entry, dict) and entry.get("source_id")
        ]
        if member_ids:
            fallback_sources[row.cluster_id] = member_ids

    if fallback_sources:
        flat = [sid for ids in fallback_sources.values() for sid in ids]
        parsed = await _load_latest_parsed(session, flat)
        for cluster_id, member_ids in fallback_sources.items():
            for source_id in member_ids:
                jd = parsed.get(source_id)
                if jd is not None and jd.department:
                    departments[cluster_id] = jd.department
                    break
    return departments


async def _role_title_matches(
    session: AsyncSession, query_text: str, *, limit: int
) -> list[tuple[UUID, str, str | None]]:
    """Harmonized ROLES whose title contains ``query_text`` — ``(cluster_id, title,
    employee_group)``, best-first.

    Searching source documents alone cannot find most of the Bank's own roles:
    **746 of 1,222 harmonized role titles (61%) appear on NO source document**, because
    harmonization renames the role. The title an author types is frequently one that
    exists only on ``canonical_jds``.

    Reads the CURRENT version of each cluster (highest version), so a superseded title
    never resurfaces.
    """
    if not query_text.strip():
        return []
    pattern = f"%{query_text.strip()}%"
    current = (
        select(
            CanonicalJD.cluster_id,
            func.max(CanonicalJD.version).label("version"),
        )
        .group_by(CanonicalJD.cluster_id)
        .subquery()
    )
    rows = (
        await session.execute(
            select(CanonicalJD)
            .join(
                current,
                (CanonicalJD.cluster_id == current.c.cluster_id)
                & (CanonicalJD.version == current.c.version),
            )
            .where(CanonicalJD.content["title"].astext.ilike(pattern))
            .limit(limit * _OVERFETCH)
        )
    ).scalars()
    matches = [
        (
            row.cluster_id,
            str((row.content or {}).get("title") or ""),
            (row.content or {}).get("employee_group"),
        )
        for row in rows
    ]
    return sorted(matches, key=lambda item: _title_rank(item[1], query_text))


async def _title_matches(
    session: AsyncSession, query_text: str, *, limit: int
) -> dict[UUID, SFUJobDescription]:
    """Archive documents whose parsed TITLE contains ``query_text``, best-first.

    Deliberately a plain SQL ``ILIKE`` rather than another vector: the whole point is to
    find the title the vectors cannot see, so answering it with the same embedding that
    excludes titles would be circular. No extension needed, and an exact title match is
    a fact, not a distance.
    """
    if not query_text.strip():
        return {}
    pattern = f"%{query_text.strip()}%"
    rows = (
        await session.scalars(
            select(ParsedJDRow)
            .where(ParsedJDRow.parsed["title"].astext.ilike(pattern))
            .order_by(ParsedJDRow.source_document_id, ParsedJDRow.created_at.desc())
            .limit(limit * _OVERFETCH)
        )
    ).all()
    latest: dict[UUID, SFUJobDescription] = {}
    for row in rows:
        if row.source_document_id not in latest:  # first = newest per the order_by
            latest[row.source_document_id] = SFUJobDescription.model_validate(
                row.parsed
            )
    return dict(
        sorted(latest.items(), key=lambda item: _title_rank(item[1].title, query_text))
    )


async def search_similar_jds(
    query_text: str,
    *,
    embed_client: EmbedClient,
    neo4j_driver: AsyncDriver,
    session: AsyncSession,
    limit: int = 10,
    rules: Rules | None = None,
) -> list[SearchHit]:
    """Search for a JD to start from — **four passes, titles before vectors**.

    In order: (1) harmonized **role** titles, (2) source-**document** titles — both
    plain Postgres ``ILIKE`` — then (3) role vectors and (4) archive-document vectors.
    Role titles rank first because cloning the reviewed harmonized role is the preferred
    start, and because **61% of role titles appear on no source document**
    (harmonization renames the role), so no document pass can reach them.

    The title passes run before the vector passes because the document vectors
    EXCLUDE the title (``embeddings.yaml: include_title_in_document: false``, which is
    what makes :mod:`src.jd_core.bank.similarity` title-agnostic for dedup). Without it,
    typing a role's exact title cannot retrieve that role: measured against the live
    index, the top 25 for "AV Systems Analyst" contained none of the 12 documents with
    that title, and the whole top-25 spanned 0.8042–0.8176 — a 0.013 spread, flat noise,
    every row rendering as "81%". A short title query against whole-document vectors has
    no signal to work with.

    Fixed HERE rather than in the vector substrate on purpose: flipping
    ``include_title_in_document`` would make this query work by silently breaking the
    dedup/clustering guarantee that two JDs with different titles and identical duties
    are the same role.

    All four passes are JDFN-scoped (CUPE/WJQ excluded, HR-143 — the filtering happens
    here in Python; the indexes themselves DO hold CUPE nodes). Results are deduplicated
    by document **and** by cluster: a document is dropped when the role it was
    harmonized into is already on the page (``d71e333``), and a title match that is a
    neighbour is listed once, as the title match. Capped at ``limit``. Injected
    ``embed_client`` / ``neo4j_driver`` / ``session`` (all mockable).
    """
    rulebook = rules if rules is not None else get_rules()
    if not query_text.strip():
        return []

    hits: list[SearchHit] = []
    seen: set[UUID] = set()
    seen_clusters: set[UUID] = set()

    # 1. Harmonized ROLES by title — the preferred start (clone the harmonized role,
    #    not a raw archive parse), and the only pass that can find the 61% of role
    #    titles that exist on no source document at all.
    for cluster_id, role_title, group in await _role_title_matches(
        session, query_text, limit=limit
    ):
        if group == _NON_JDFN_GROUP:
            continue
        seen_clusters.add(cluster_id)
        hits.append(
            SearchHit(
                cluster_id=cluster_id,
                title=role_title,
                employee_group=group,
                score=None,
                match="role_title",
            )
        )
        if len(hits) >= limit:
            return await _with_departments(session, hits)

    # 2. Archive DOCUMENTS by title — COLLAPSED into the role they were harmonized
    #    into. Listing a role and then its own member documents underneath is how a
    #    correctly harmonized role reads as "nothing was combined": a search for
    #    "peoplesoft" showed the "PeopleSoft Developer" role and then, beneath it, the
    #    16 "Senior Developer, PeopleSoft" documents that ARE that role.
    titled = await _title_matches(session, query_text, limit=limit)
    doc_clusters = await _clusters_for_sources(session, list(titled))
    for source_id, jd in titled.items():
        if jd.employee_group == _NON_JDFN_GROUP:
            continue  # the title pass is under the SAME JDFN scope as the vector pass
        doc_cluster = doc_clusters.get(source_id)
        if doc_cluster is not None and doc_cluster in seen_clusters:
            continue  # already on the page as the harmonized role it belongs to
        if doc_cluster is not None:
            seen_clusters.add(doc_cluster)
        seen.add(source_id)
        hits.append(
            SearchHit(
                source_document_id=source_id,
                cluster_id=doc_cluster,
                title=jd.title,
                department=jd.department,
                employee_group=jd.employee_group,
                score=None,
                match="title",
            )
        )
        if len(hits) >= limit:
            return await _with_departments(session, hits)

    vector = (await embed_client.embed_batch([query_text]))[0]

    # 3. Semantic neighbours among the harmonized ROLES — the Bank searching its own
    #    output. Ranked above archive neighbours at equal footing because a reviewed
    #    role is a better seed for a clone than a raw archive parse.
    for cluster_id, role_title, group, score in await _nearest_role_ids(
        neo4j_driver, vector, limit * _OVERFETCH, live_stamp=rulebook.embeddings.stamp
    ):
        if group == _NON_JDFN_GROUP or cluster_id in seen_clusters:
            continue
        seen_clusters.add(cluster_id)
        hits.append(
            SearchHit(
                cluster_id=cluster_id,
                title=role_title,
                employee_group=group,
                score=score,
                match="semantic",
            )
        )
        if len(hits) >= limit:
            return await _with_departments(session, hits)

    # 4. Semantic neighbours in the ARCHIVE — collapsed by role the same way, so one
    #    role cannot fill the page with its own members.
    nearest = await _nearest_source_ids(
        neo4j_driver, vector, limit * _OVERFETCH, live_stamp=rulebook.embeddings.stamp
    )
    parsed = await _load_latest_parsed(session, [sid for sid, _ in nearest])
    near_clusters = await _clusters_for_sources(session, [sid for sid, _ in nearest])

    for source_id, score in nearest:
        neighbour = parsed.get(source_id)
        if (
            neighbour is None
            or neighbour.employee_group == _NON_JDFN_GROUP
            or source_id in seen
        ):
            continue  # pruned/unparsed, CUPE/WJQ, or already listed as a title match
        near_cluster = near_clusters.get(source_id)
        if near_cluster is not None and near_cluster in seen_clusters:
            continue  # its harmonized role is already on the page
        if near_cluster is not None:
            seen_clusters.add(near_cluster)
        hits.append(
            SearchHit(
                source_document_id=source_id,
                cluster_id=near_cluster,
                title=neighbour.title,
                department=neighbour.department,
                employee_group=neighbour.employee_group,
                score=score,
                match="semantic",
            )
        )
        if len(hits) >= limit:
            break
    return await _with_departments(session, hits)


async def load_clone_answers(
    session: AsyncSession, source_document_id: UUID
) -> AnswerContract | None:
    """The guided-authoring answers to pre-fill the Builder from an existing archive
    document, or ``None`` if it has no parsed JD.

    Routed through the FORM the source is on (Phase E): a CUPE document clones into the
    WJQ contract, not into the JDFN one. Reading it through the wrong contract would
    drop every section the other form does not ask about — silently, since a missing
    field is just an empty answer.
    """
    parsed = await _load_latest_parsed(session, [source_document_id])
    jd = parsed.get(source_document_id)
    if jd is None:
        return None
    return _clone_into_its_own_form(jd)


async def load_role_clone_answers(
    session: AsyncSession, cluster_id: UUID
) -> AnswerContract | None:
    """The guided-authoring answers to pre-fill the Builder from a role's HARMONIZED
    canonical (its current, highest-version content), or ``None`` if the cluster has no
    canonical. This is the preferred clone source: the archive is transitional, so a new
    JD should start from the reviewed, cleaned-up harmonized role — not a raw archive
    member that may fail the current template (a 177-word summary, one un-split duty).

    The answers record WHICH role they were cloned from
    (:attr:`~src.jd_bank.composer.answers.ComposerAnswers.cloned_from_cluster_id`), so
    the Phase-5.9 authoring guard can exclude it — cloning a role must not immediately
    warn the author that they duplicated the very role they cloned.
    """
    canonical = (
        await session.scalars(
            select(CanonicalJD)
            .where(CanonicalJD.cluster_id == cluster_id)
            .order_by(CanonicalJD.version.desc())
            .limit(1)
        )
    ).first()
    if canonical is None:
        return None
    answers = _clone_into_its_own_form(
        SFUJobDescription.model_validate(canonical.content)
    )
    return answers.model_copy(update={"cloned_from_cluster_id": cluster_id})


async def _clusters_for_sources(
    session: AsyncSession, ids: Sequence[UUID]
) -> dict[UUID, UUID]:
    """``{source_document_id: cluster_id}`` for the ids that belong to a cluster.

    One query for the whole result page, rather than :func:`cluster_id_for_source` per
    hit — and, more importantly, this is what lets the search COLLAPSE a document into
    the role it was harmonized into (see :func:`search_similar_jds`).
    """
    if not ids:
        return {}
    wanted = {str(i) for i in ids}
    rows = (
        await session.execute(
            select(Cluster.id, Cluster.members).where(
                or_(
                    *[
                        Cluster.members.contains([{"source_id": str(i)}])
                        for i in set(ids)
                    ]
                )
            )
        )
    ).all()
    mapping: dict[UUID, UUID] = {}
    for cluster_id, members in rows:
        for member in members or []:
            source_id = member.get("source_id")
            if source_id in wanted:
                mapping[UUID(source_id)] = cluster_id
    return mapping


async def cluster_id_for_source(
    session: AsyncSession, source_document_id: UUID
) -> UUID | None:
    """The cluster a source document belongs to, if any — so a search hit can offer to
    clone the harmonized role instead of the raw archive JD. ``None`` for a singleton /
    unclustered document (which has no harmonized version to prefer)."""
    return (
        await session.scalars(
            select(Cluster.id)
            .where(Cluster.members.contains([{"source_id": str(source_document_id)}]))
            .limit(1)
        )
    ).first()


def _clone_into_its_own_form(jd: SFUJobDescription) -> AnswerContract:
    """Read ``jd`` back into the answer contract of the FORM it is on (Phase E).

    Imported HERE rather than at module scope: ``forms.py`` imports the assemblers and
    the clone transforms, so a top-level import back into it from a service module is a
    cycle. The 8.3c ``get_session`` defect is the standing example of what that costs —
    an import order that works in every existing suite and raises the first time a new
    module imports the other one first.
    """
    from src.jd_bank.composer.forms import form_for

    return form_for(jd).clone_from_jd(jd)

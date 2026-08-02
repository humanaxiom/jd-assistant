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

**Corpus (v1).** The only vectors that exist are the archive **document** embeddings
(keyed on ``source_document_id``). Cluster representatives are archive documents and
so are searchable; **published canonicals are not yet embedded**, so searching them
semantically is a follow-up (it needs a small new write path — embed canonical
content into the index). v1 searches the embedded archive, **JDFN-scoped** (CUPE/WJQ
excluded — the Builder authors the JDFN template, HR-143), and is honest about it.

**Read-only.** Nothing here writes or publishes; cloning pre-fills a draft the author
still builds and submits through the review queue (NN #1).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal
from uuid import UUID

from neo4j import AsyncDriver
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.jd_bank.composer.answers import ComposerAnswers, DutyAnswer, ModifiedQual
from src.jd_bank.db.models import CanonicalJD, Cluster, ParsedJDRow
from src.jd_bank.embeddings.client import EmbedClient
from src.jd_core.models.parsed_jd import SFUJobDescription
from src.jd_core.rules import Rules, get_rules

#: The Neo4j vector index built in ``core/db/migrations/002_jd_vectors.cypher``.
_DOCUMENT_INDEX = "jd_document_embeddings"

#: The employee group whose JDs are NOT JDFN (CUPE uses the WJQ instrument, HR-143) —
#: excluded from Builder search results, which only ever start a JDFN draft.
_NON_JDFN_GROUP = "cupe"

#: Over-fetch factor: the vector index may return CUPE/WJQ hits or documents whose
#: parsed JD has since been pruned, so fetch more than ``limit`` and filter down.
_OVERFETCH = 3

_NEAREST = """
CALL db.index.vector.queryNodes($index, $k, $vector)
YIELD node, score
RETURN node.id AS id, score
ORDER BY score DESC
"""


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
    employee_group: str | None = None
    #: Cosine similarity to the query — ``None`` for a title match (see above).
    score: float | None = Field(default=None, ge=-1.0, le=1.0)
    match: Literal["role_title", "title", "semantic"] = "semantic"


def jd_to_answers(jd: SFUJobDescription) -> ComposerAnswers:
    """Turn an existing JD back into guided-authoring answers, so the Builder can be
    pre-filled from it (the inverse of :func:`assemble_jd`).

    Qualifications are split back out by kind into the answer fields; ``security``
    qualifications have no Builder field and are dropped (the guided flow does not
    collect them — a v1 limitation, recorded). The SFU boilerplate flag is set iff the
    source carries all three mandated presence booleans.
    """
    rel = jd.relationships
    return ComposerAnswers(
        title=jd.title,
        department=jd.department,
        employee_group=jd.employee_group,
        grade=jd.classification.value if jd.classification is not None else None,
        position_summary=jd.position_summary,
        duties=[
            DutyAnswer(action_verb=d.action_verb, statement=d.statement)
            for d in jd.duties
        ],
        decision_making=list(jd.decision_making),
        problem_solving=list(jd.problem_solving),
        supervisory=rel.supervisory if rel is not None else None,
        internal=list(rel.internal) if rel is not None else [],
        external=list(rel.external) if rel is not None else [],
        education=[q.text for q in jd.qualifications if q.kind == "education"],
        experience=[q.text for q in jd.qualifications if q.kind == "experience"],
        knowledge=[
            ModifiedQual(text=q.text, modifier=q.modifier)
            for q in jd.qualifications
            if q.kind == "knowledge"
        ],
        skills=[
            ModifiedQual(text=q.text, modifier=q.modifier)
            for q in jd.qualifications
            if q.kind == "skill"
        ],
        abilities=[q.text for q in jd.qualifications if q.kind == "ability"],
        include_sfu_boilerplate=(
            jd.about_sfu_present
            and jd.territorial_acknowledgement_present
            and jd.employment_equity_present
        ),
        additional_context=jd.additional_context,
    )


async def _nearest_source_ids(
    driver: AsyncDriver, vector: Sequence[float], k: int
) -> list[tuple[UUID, float]]:
    """Top-``k`` archive documents by cosine similarity to ``vector`` — the Neo4j
    vector-index read. Returns ``(source_document_id, score)`` best-first."""
    async with driver.session() as session:
        result = await session.run(
            _NEAREST, index=_DOCUMENT_INDEX, k=k, vector=list(vector)
        )
        records = [record async for record in result]
    return [
        (UUID(record["id"]), float(record["score"]))
        for record in records
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
    """Search the archive for JDs to start from — **by title first, then semantically**.

    A title pass runs before the vector pass because the document vectors deliberately
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

    Both passes are JDFN-scoped (CUPE/WJQ excluded, HR-143), deduplicated by document
    (a title match that is also a near neighbour is listed once, as the title match),
    and capped at ``limit``. Injected ``embed_client`` / ``neo4j_driver`` / ``session``
    (all mockable).
    """
    _ = rules if rules is not None else get_rules()
    if not query_text.strip():
        return []

    hits: list[SearchHit] = []
    seen: set[UUID] = set()

    # 1. Harmonized ROLES by title — the preferred start (clone the harmonized role,
    #    not a raw archive parse), and the only pass that can find the 61% of role
    #    titles that exist on no source document at all.
    for cluster_id, role_title, group in await _role_title_matches(
        session, query_text, limit=limit
    ):
        if group == _NON_JDFN_GROUP:
            continue
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
            return hits

    # 2. Archive DOCUMENTS by title.
    for source_id, jd in (
        await _title_matches(session, query_text, limit=limit)
    ).items():
        if jd.employee_group == _NON_JDFN_GROUP:
            continue  # the title pass is under the SAME JDFN scope as the vector pass
        seen.add(source_id)
        hits.append(
            SearchHit(
                source_document_id=source_id,
                title=jd.title,
                employee_group=jd.employee_group,
                score=None,
                match="title",
            )
        )
        if len(hits) >= limit:
            return hits

    vector = (await embed_client.embed_batch([query_text]))[0]
    nearest = await _nearest_source_ids(neo4j_driver, vector, limit * _OVERFETCH)
    parsed = await _load_latest_parsed(session, [sid for sid, _ in nearest])

    for source_id, score in nearest:
        neighbour = parsed.get(source_id)
        if (
            neighbour is None
            or neighbour.employee_group == _NON_JDFN_GROUP
            or source_id in seen
        ):
            continue  # pruned/unparsed, CUPE/WJQ, or already listed as a title match
        hits.append(
            SearchHit(
                source_document_id=source_id,
                title=neighbour.title,
                employee_group=neighbour.employee_group,
                score=score,
                match="semantic",
            )
        )
        if len(hits) >= limit:
            break
    return hits


async def load_clone_answers(
    session: AsyncSession, source_document_id: UUID
) -> ComposerAnswers | None:
    """The guided-authoring answers to pre-fill the Builder from an existing archive
    document, or ``None`` if it has no parsed JD."""
    parsed = await _load_latest_parsed(session, [source_document_id])
    jd = parsed.get(source_document_id)
    return jd_to_answers(jd) if jd is not None else None


async def load_role_clone_answers(
    session: AsyncSession, cluster_id: UUID
) -> ComposerAnswers | None:
    """The guided-authoring answers to pre-fill the Builder from a role's HARMONIZED
    canonical (its current, highest-version content), or ``None`` if the cluster has no
    canonical. This is the preferred clone source: the archive is transitional, so a new
    JD should start from the reviewed, cleaned-up harmonized role — not a raw archive
    member that may fail the current template (a 177-word summary, one un-split duty).
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
    return jd_to_answers(SFUJobDescription.model_validate(canonical.content))


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

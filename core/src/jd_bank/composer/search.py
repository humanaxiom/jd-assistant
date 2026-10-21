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

**Track I2.** The document-title pass reads the CURRENT parse only; both title passes
are served by trigram indexes (migration 0007) and fall back to a per-word spelling
match (HR-241) when no title contains the query; and the two vector passes are the only
part that needs the inference host — when it is down or stalled they are skipped, the
title hits are kept, and :class:`SearchOutcome` carries a notice saying so.

**Read-only.** Nothing here writes or publishes; cloning pre-fills a draft the author
still builds and submits through the review queue (NN #1).
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any, Literal, TypeVar
from uuid import UUID

from neo4j import AsyncDriver
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import (
    ColumnElement,
    Integer,
    Select,
    Text,
    and_,
    case,
    func,
    literal,
    literal_column,
    or_,
    select,
)
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from src.jd_bank.composer.answers import AnswerContract
from src.jd_bank.db.models import CanonicalJD, Cluster, ParsedJDRow
from src.jd_bank.embeddings.client import EmbedClient
from src.jd_core.models.parsed_jd import SFUJobDescription
from src.jd_core.models.quality import DEFAULT_TEMPLATE, WJQ_TEMPLATE, JDTemplate
from src.jd_core.parser import PARSER_VERSION
from src.jd_core.rules import Rules, get_rules

logger = logging.getLogger(__name__)

_T = TypeVar("_T")

#: Shown when the MEANING passes could not run — embedding host refused, stalled past
#: HR-198's budget, or a vector index unreachable — so the reader knows the list holds
#: title matches only. Never a silent downgrade, never a 500 (Track I2).
SEMANTIC_UNAVAILABLE_NOTICE = (
    "Search by meaning is unavailable right now, so only job descriptions whose title "
    "matches your search are shown. Try again in a few minutes."
)

# --- the title expressions (Track I2) -------------------------------------------------
#
# Spelled with a LITERAL key, ``->> 'title'``, and never as
# ``CanonicalJD.content["title"].astext`` — which renders the key as a bound parameter
# (``->> $1``). The trigram indexes of migration 0007 are on the literal expression, and
# a prepared statement's generic plan cannot match ``->> $1`` to them. Pinned by
# ``tests/integration/test_search_title_tiers.py``.

#: A harmonized role's title (``ix_canonical_jds_title_trgm``).
ROLE_TITLE: ColumnElement[str] = CanonicalJD.content.op("->>", return_type=Text)(
    literal_column("'title'")
)
#: An archive document's parsed title — the STORED ``parsed_jds.title`` column
#: (migration 0008; ``ix_parsed_jds_version_title_col_trgm`` with ``parser_version``),
#: never ``parsed ->> 'title'``. MEASURED on the v9 Bank: with one parse per document
#: the planner seq-scans, and the JSON expression then detoasts every row's whole
#: ``parsed`` — 650 ms a query, which put Builder search at p95 2.02 s against HR-242's
#: 1.0 s. A plain text column costs a seq scan nothing of the kind.
DOC_TITLE: ColumnElement[str] = ParsedJDRow.__table__.c.title

#: The words a typo query is matched by. Word characters only, so punctuation typed
#: between words ("co-op", "a/b") never becomes a word of its own.
_WORD = re.compile(r"\w+", re.UNICODE)


def like_pattern(query: str) -> str:
    """``%query%`` with the LIKE wildcards in the query itself neutralised — a ``%`` or
    ``_`` a reader types is a character, not a wildcard. Use with ``escape="\\\\"``."""
    escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _tier(title: ColumnElement[str], query: str) -> ColumnElement[int]:
    """The SQL twin of :func:`title_rank`: 0 exact, 1 prefix, 2 contains — so a page can
    be cut AFTER ranking, never before (the role pass used to LIMIT first)."""
    wanted = query.strip().lower()
    lowered = func.lower(func.btrim(title))
    return case(
        (lowered == wanted, literal(0, Integer)),
        (lowered.like(like_pattern(wanted)[1:], escape="\\"), literal(1, Integer)),
        else_=literal(2, Integer),
    )


def typo_words(query: str) -> list[str]:
    """The distinct lower-cased words of ``query`` the typo fallback must ALL match."""
    return list(dict.fromkeys(w.lower() for w in _WORD.findall(query)))


def _every_word_close(title: ColumnElement[str], words: Sequence[str]) -> Any:
    """``word <<% title`` for every word: ``strict_word_similarity(word, title)`` at or
    above ``pg_trgm.strict_word_similarity_threshold`` (set per transaction from
    HR-241). The operator, not the function, so the GIN trigram index can serve it.

    PER WORD and STRICT on purpose — measured over the live titles: whole-query
    ``word_similarity`` lets a partial word extent count, so "coop coord" scored 0.63
    against ~445 unrelated "...Coordinator" roles. Requiring each typed word to match a
    WHOLE title word keeps abbreviations out and lets single-letter typos through."""
    return and_(*[literal(w, Text).op("<<%")(title) for w in words])


async def _with_typo_floor(
    session: AsyncSession, floor: float, run: Callable[[], Awaitable[_T]], empty: _T
) -> _T:
    """Run a typo query with HR-241's floor in force, inside a SAVEPOINT.

    The savepoint is the difference between a degraded search and a dead one: on a
    database where migration 0007 has not run, ``<<%`` does not exist, the statement
    fails, and without it the whole request transaction would be aborted — every later
    query on the page would fail too. Here the fallback is simply skipped, loudly."""
    try:
        async with session.begin_nested():
            await session.execute(
                select(
                    func.set_config(
                        "pg_trgm.strict_word_similarity_threshold", str(floor), True
                    )
                )
            )
            return await run()
    except SQLAlchemyError:
        logger.warning(
            "title typo fallback unavailable (is migration 0007 / pg_trgm applied?); "
            "serving exact title matches only",
            exc_info=True,
        )
        return empty


#: The Neo4j vector index built in ``core/db/migrations/002_jd_vectors.cypher``.
_DOCUMENT_INDEX = "jd_document_embeddings"

#: RETIRED — the WJQ bargaining unit is `segmentation.wjq_employee_groups` (HR-225),
#: read through :func:`_scope_groups`. It was a CONSTANT here, excluded unconditionally,
#: which is why picking the CUPE form in the Builder still returned JDFN documents
#: (reported 2026-08-28). It was also mis-cited to HR-143, which governs the approval
#: COHORT and says nothing about search scope.

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
    #: A title hit found by the TYPO fallback (Track I2) rather than by the title
    #: containing the query. Ranked by closeness, and still carries no ``score``: a
    #: trigram similarity is a spelling distance, not a measure of the job.
    by_spelling: bool = False


class SearchOutcome(BaseModel):
    """A Builder search's hits, plus the notice to show when part of it could not run.

    ``notice`` is set when the meaning passes were skipped because the embedding host
    or a vector index failed (:data:`SEMANTIC_UNAVAILABLE_NOTICE`): the hits are then
    title matches only, and the page must say so rather than present them as complete.
    """

    model_config = ConfigDict(extra="forbid")

    hits: list[SearchHit]
    notice: str | None = None


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


async def semantic_role_neighbours(
    query_text: str,
    *,
    embed_client: EmbedClient,
    neo4j_driver: AsyncDriver,
    k: int,
    rules: Rules | None = None,
) -> list[tuple[UUID, str, str | None]]:
    """The role-semantic pass as a reusable unit: embed ``query_text`` and return the
    ``k`` nearest harmonized roles as ``(cluster_id, title, employee_group)``,
    best-first.

    This is the SAME pass :func:`search_similar_jds` runs as its third step — the same
    :func:`_nearest_role_ids` read under the same live embed stamp — shared with the
    library's search (Track I1) rather than forked. **No score is returned**: a role's
    cosine is meaningless as an absolute number (an unrelated role can outscore a true
    twin), so callers get the ORDER and nothing to threshold or display. A blank query
    is never embedded. Embedding errors propagate: the caller owns the degraded path.
    """
    if not query_text.strip():
        return []
    rulebook = rules if rules is not None else get_rules()
    vector = (await embed_client.embed_batch([query_text]))[0]
    near = await _nearest_role_ids(
        neo4j_driver, vector, k, live_stamp=rulebook.embeddings.stamp
    )
    return [(cluster_id, title, group) for cluster_id, title, group, _ in near]


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


def title_rank(title: str, query: str) -> int:
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
    never resurfaces. Ranked exact → prefix → contains IN SQL, before the page is cut.
    """
    if not query_text.strip():
        return []
    rows = (await session.execute(_role_title_statement(query_text, limit))).all()
    return [(cid, str(title or ""), group) for cid, title, group in rows]


def _current_roles() -> Any:
    """``(cluster_id, version)`` of each cluster's CURRENT (highest) version."""
    return (
        select(CanonicalJD.cluster_id, func.max(CanonicalJD.version).label("version"))
        .group_by(CanonicalJD.cluster_id)
        .subquery()
    )


def _current_role_rows(*where: Any) -> Select[UUID, str, str]:
    """``(cluster_id, title, employee_group)`` of current roles matching ``where``."""
    current = _current_roles()
    return (
        select(
            CanonicalJD.cluster_id,
            ROLE_TITLE.label("title"),
            CanonicalJD.content.op("->>", return_type=Text)(
                literal_column("'employee_group'")
            ).label("employee_group"),
        )
        .join(
            current,
            (CanonicalJD.cluster_id == current.c.cluster_id)
            & (CanonicalJD.version == current.c.version),
        )
        .where(*where)
    )


def _role_title_statement(query_text: str, limit: int | None) -> Select[UUID, str, str]:
    """Current roles whose title CONTAINS ``query_text``, tier-ranked, then cut."""
    query = query_text.strip()
    statement = _current_role_rows(
        ROLE_TITLE.ilike(like_pattern(query), escape="\\")
    ).order_by(_tier(ROLE_TITLE, query), ROLE_TITLE, CanonicalJD.cluster_id)
    return statement if limit is None else statement.limit(limit * _OVERFETCH)


def _role_typo_statement(
    words: Sequence[str], query_text: str, limit: int | None
) -> Select[UUID, str, str]:
    """Current roles whose title matches EVERY typed word by spelling, closest first.
    Run only under :func:`_with_typo_floor` (the ``<<%`` threshold)."""
    statement = _current_role_rows(_every_word_close(ROLE_TITLE, words)).order_by(
        func.strict_word_similarity(query_text.strip(), ROLE_TITLE).desc(),
        ROLE_TITLE,
        CanonicalJD.cluster_id,
    )
    return statement if limit is None else statement.limit(limit * _OVERFETCH)


async def role_title_typo_matches(
    session: AsyncSession, query_text: str, *, floor: float, limit: int | None
) -> list[tuple[UUID, str, str | None]]:
    """The TYPO fallback over harmonized role titles (Track I2, HR-241):
    ``(cluster_id, title, employee_group)``, closest spelling first. Shared by the
    Builder and the library. Empty — never an error — when nothing qualifies or the
    trigram operator is unavailable (see :func:`_with_typo_floor`)."""
    words = typo_words(query_text)
    if not words:
        return []

    async def run() -> list[tuple[UUID, str, str | None]]:
        statement = _role_typo_statement(words, query_text, limit)
        rows = (await session.execute(statement)).all()
        return [(cid, str(title or ""), group) for cid, title, group in rows]

    return await _with_typo_floor(session, floor, run, [])


def _doc_title_statement(query_text: str, limit: int) -> Select[Any]:
    """CURRENT-parse documents whose title CONTAINS ``query_text``, tier-ranked."""
    query = query_text.strip()
    return (
        select(ParsedJDRow)
        .where(
            ParsedJDRow.parser_version == PARSER_VERSION,
            DOC_TITLE.ilike(like_pattern(query), escape="\\"),
        )
        .order_by(_tier(DOC_TITLE, query), DOC_TITLE, ParsedJDRow.source_document_id)
        .limit(limit * _OVERFETCH)
    )


def _doc_typo_statement(
    words: Sequence[str], query_text: str, limit: int
) -> Select[Any]:
    """CURRENT-parse documents whose title matches every typed word by spelling."""
    return (
        select(ParsedJDRow)
        .where(
            ParsedJDRow.parser_version == PARSER_VERSION,
            _every_word_close(DOC_TITLE, words),
        )
        .order_by(
            func.strict_word_similarity(query_text.strip(), DOC_TITLE).desc(),
            DOC_TITLE,
            ParsedJDRow.source_document_id,
        )
        .limit(limit * _OVERFETCH)
    )


def _parsed_by_source(rows: Sequence[ParsedJDRow]) -> dict[UUID, SFUJobDescription]:
    """One parse per document, in the rows' (already ranked) order."""
    out: dict[UUID, SFUJobDescription] = {}
    for row in rows:
        if row.source_document_id not in out:
            out[row.source_document_id] = SFUJobDescription.model_validate(row.parsed)
    return out


async def _title_matches(
    session: AsyncSession, query_text: str, *, limit: int
) -> dict[UUID, SFUJobDescription]:
    """Archive documents whose CURRENT parse's TITLE contains ``query_text``,
    best-first (exact → prefix → contains, ranked in SQL before the page is cut).

    Deliberately a plain SQL ``ILIKE`` rather than another vector: the whole point is to
    find the title the vectors cannot see, so answering it with the same embedding that
    excludes titles would be circular. An exact title match is a fact, not a distance.

    **Current parse only** (``parser_version == PARSER_VERSION``, the codebase's own
    predicate — Track I2). It used to scan every parse of every document: 116,176 rows
    for 14,522 documents, a 2.7 s sequential scan that was most of the Builder's
    latency, and it matched titles the parser no longer produces (47 of 2,011
    "Coordinator" documents matched ONLY through a superseded parse). Served by
    ``ix_parsed_jds_version_title_col_trgm`` over the stored ``title`` column (0008).
    """
    if not query_text.strip():
        return {}
    rows = (await session.scalars(_doc_title_statement(query_text, limit))).all()
    return _parsed_by_source(rows)


async def _doc_title_typo_matches(
    session: AsyncSession, query_text: str, *, floor: float, limit: int
) -> dict[UUID, SFUJobDescription]:
    """The TYPO fallback over current-parse document titles (HR-241)."""
    words = typo_words(query_text)
    if not words:
        return {}

    async def run() -> dict[UUID, SFUJobDescription]:
        statement = _doc_typo_statement(words, query_text, limit)
        return _parsed_by_source((await session.scalars(statement)).all())

    return await _with_typo_floor(session, floor, run, {})


def _out_of_scope(
    group: str | None, wjq_groups: frozenset[str], form: JDTemplate
) -> bool:
    """Is a hit outside the scope the author's chosen FORM can clone into?

    The two directions are NOT symmetric, and that is the point:

    * **WJQ** is an INCLUDE list — only the WJQ bargaining unit(s) can seed a WJQ draft.
    * **JDFN** is "not the WJQ unit(s)" — NOT an include-list of
      ``jdfn_employee_groups``.
      ``employee_group`` is recorded on only ~48% of the archive, so an include-list
      would silently drop every document whose group was never parsed. Pinned by
      ``test_jdfn_search_still_keeps_documents_with_no_group_recorded``.
    """
    if form == WJQ_TEMPLATE:
        return group not in wjq_groups
    return group in wjq_groups


async def search_similar_jds(
    query_text: str,
    *,
    embed_client: EmbedClient,
    neo4j_driver: AsyncDriver,
    session: AsyncSession,
    limit: int = 10,
    form: JDTemplate = DEFAULT_TEMPLATE,
    rules: Rules | None = None,
) -> list[SearchHit]:
    """:func:`search_jds`' hits alone — for a caller that has nowhere to show its
    notice. Prefer :func:`search_jds` wherever a page is rendered."""
    outcome = await search_jds(
        query_text,
        embed_client=embed_client,
        neo4j_driver=neo4j_driver,
        session=session,
        limit=limit,
        form=form,
        rules=rules,
    )
    return outcome.hits


async def search_jds(
    query_text: str,
    *,
    embed_client: EmbedClient,
    neo4j_driver: AsyncDriver,
    session: AsyncSession,
    limit: int = 10,
    form: JDTemplate = DEFAULT_TEMPLATE,
    rules: Rules | None = None,
) -> SearchOutcome:
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
    # The author's chosen form decides the clone-source scope (HR-225).
    wjq_groups = frozenset(rulebook.segmentation.wjq_employee_groups)
    if not query_text.strip():
        return SearchOutcome(hits=[])

    hits: list[SearchHit] = []
    seen: set[UUID] = set()
    seen_clusters: set[UUID] = set()

    async def done(notice: str | None = None) -> SearchOutcome:
        return SearchOutcome(hits=await _with_departments(session, hits), notice=notice)

    def add_roles(
        rows: Sequence[tuple[UUID, str, str | None]], *, by_spelling: bool = False
    ) -> bool:
        """Append in-scope role title hits; ``True`` once the page is full."""
        for cluster_id, role_title, group in rows:
            if _out_of_scope(group, wjq_groups, form) or cluster_id in seen_clusters:
                continue
            seen_clusters.add(cluster_id)
            hits.append(
                SearchHit(
                    cluster_id=cluster_id,
                    title=role_title,
                    employee_group=group,
                    score=None,
                    match="role_title",
                    by_spelling=by_spelling,
                )
            )
            if len(hits) >= limit:
                return True
        return False

    async def add_docs(
        titled: Mapping[UUID, SFUJobDescription], *, by_spelling: bool = False
    ) -> bool:
        """Append in-scope document title hits, COLLAPSED into the role each was
        harmonized into. Listing a role and then its own member documents underneath
        is how a correctly harmonized role reads as "nothing was combined": a search
        for "peoplesoft" showed the "PeopleSoft Developer" role and then, beneath it,
        the 16 "Senior Developer, PeopleSoft" documents that ARE that role."""
        doc_clusters = await _clusters_for_sources(session, list(titled))
        for source_id, jd in titled.items():
            if _out_of_scope(jd.employee_group, wjq_groups, form):
                continue  # the title pass is under the SAME scope as the vector pass
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
                    by_spelling=by_spelling,
                )
            )
            if len(hits) >= limit:
                return True
        return False

    # 1. Harmonized ROLES by title — the preferred start (clone the harmonized role,
    #    not a raw archive parse), and the only pass that can find the 61% of role
    #    titles that exist on no source document at all.
    roles = await _role_title_matches(session, query_text, limit=limit)
    if add_roles(roles):
        return await done()

    # 2. Archive DOCUMENTS by title — the CURRENT parse only.
    titled = await _title_matches(session, query_text, limit=limit)
    if await add_docs(titled):
        return await done()

    # 2b. The TYPO fallback (Track I2, HR-241) — only when NO title contains the query.
    #     Measured: "adminstrative cordinator" and "labratory techician" reached the
    #     vectors with nothing, and the vectors returned unrelated roles.
    if not roles and not titled:
        floor = rulebook.embeddings.title_typo_min_similarity
        if add_roles(
            await role_title_typo_matches(
                session, query_text, floor=floor, limit=limit
            ),
            by_spelling=True,
        ):
            return await done()
        if await add_docs(
            await _doc_title_typo_matches(
                session, query_text, floor=floor, limit=limit
            ),
            by_spelling=True,
        ):
            return await done()

    # 3–4 need the embedding host and Neo4j. Every hit above is plain Postgres, so a
    # dead / stalled / refusing inference host costs ONLY these passes — never the
    # title hits already found, never the page (measured 2026-10-19: a refused host
    # raised APIConnectionError after 4.3 s and the route returned a 500). Bounded as
    # a whole by HR-198, the same budget the route used to put around everything.
    loop = asyncio.get_running_loop()
    deadline = loop.time() + rulebook.embeddings.interactive_timeout_seconds

    async def bounded(step: Awaitable[_T]) -> _T:
        return await asyncio.wait_for(step, timeout=max(0.0, deadline - loop.time()))

    try:
        vector = (await bounded(embed_client.embed_batch([query_text])))[0]
        near_roles = await bounded(
            _nearest_role_ids(
                neo4j_driver,
                vector,
                limit * _OVERFETCH,
                live_stamp=rulebook.embeddings.stamp,
            )
        )
    except Exception:  # noqa: BLE001 — any embed/index failure degrades, never raises
        logger.warning(
            "Builder meaning search unavailable; serving title matches only",
            exc_info=True,
        )
        return await done(SEMANTIC_UNAVAILABLE_NOTICE)

    # 3. Semantic neighbours among the harmonized ROLES — the Bank searching its own
    #    output. Ranked above archive neighbours at equal footing because a reviewed
    #    role is a better seed for a clone than a raw archive parse.
    for cluster_id, role_title, group, score in near_roles:
        if _out_of_scope(group, wjq_groups, form) or cluster_id in seen_clusters:
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
            return await done()

    # 4. Semantic neighbours in the ARCHIVE — collapsed by role the same way, so one
    #    role cannot fill the page with its own members.
    try:
        nearest = await bounded(
            _nearest_source_ids(
                neo4j_driver,
                vector,
                limit * _OVERFETCH,
                live_stamp=rulebook.embeddings.stamp,
            )
        )
    except Exception:  # noqa: BLE001 — the document index down degrades the same way
        logger.warning(
            "Builder archive-vector search unavailable; serving what was found",
            exc_info=True,
        )
        return await done(SEMANTIC_UNAVAILABLE_NOTICE)
    parsed = await _load_latest_parsed(session, [sid for sid, _ in nearest])
    near_clusters = await _clusters_for_sources(session, [sid for sid, _ in nearest])

    for source_id, score in nearest:
        neighbour = parsed.get(source_id)
        if (
            neighbour is None
            or _out_of_scope(neighbour.employee_group, wjq_groups, form)
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
    return await done()


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

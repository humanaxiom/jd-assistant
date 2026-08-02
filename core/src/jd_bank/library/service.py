"""Read-only queries behind the browsable JD Bank (the content library).

This is the read side of the "where is the actual content?" answer: given a source
document it returns the rendered archive JD; given a cluster it returns the harmonized
role plus the source JDs it was distilled from; and it lists roles / source documents
for browsing. It **only reads** ``source_documents`` / ``parsed_jds`` / ``clusters`` /
``canonical_jds`` and renders their stored ``SFUJobDescription`` content with
:func:`~src.jd_core.bank.render.render_sfu_jd_text` — nothing here mutates a row or
touches the publish path (NN #1). The review service stays the sole approval authority.

Score / grade shown in the roles list are the STORED ``change_log`` roll-up (what the
producer computed), display-only — the same roll-up the review queue shows, never a
fresh gate decision (that is the review packet's job).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import Float, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.jd_bank.db.models import (
    CanonicalJD,
    Cluster,
    ParsedJDRow,
    SourceDocument,
)
from src.jd_bank.library.models import (
    MemberJD,
    RoleListItem,
    RolePage,
    RoleRef,
    RoleView,
    SourceJDView,
    SourceListItem,
    SourcePage,
)
from src.jd_core.bank.render import render_sfu_jd_text
from src.jd_core.models.parsed_jd import SFUJobDescription

#: Default page size for the browsable lists (roles + source archive).
DEFAULT_PAGE_SIZE = 50
_MAX_PAGE_SIZE = 200

#: The sortable columns of the roles library, mapped to their ORDER BY expression. A
#: request for any other key falls back to ``title``. (No "level" facet: the archive has
#: no reliable job level — the APSA grade 1–15 is not extracted anywhere, and the title-
#: family ladder mis-fires on office names like "Office of the Vice-President".)
_ROLE_SORTS = {
    "title": CanonicalJD.content["title"].astext,
    "status": CanonicalJD.status,
    "sources": func.jsonb_array_length(CanonicalJD.source_document_ids),
    "score": CanonicalJD.change_log["validator"]["score"].astext.cast(Float),
    "grade": CanonicalJD.change_log["validator"]["grade"].astext,
}


def _clamp_limit(limit: int | None) -> int:
    if limit is None:
        return DEFAULT_PAGE_SIZE
    return max(1, min(limit, _MAX_PAGE_SIZE))


# --- shared loaders -------------------------------------------------------------------


async def _latest_parsed_map(
    session: AsyncSession, ids: Sequence[UUID]
) -> dict[UUID, SFUJobDescription]:
    """The most recent parsed JD for each source document id (source ids with no parse
    row are simply absent from the map)."""
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


async def _latest_canonical_for_cluster(
    session: AsyncSession, cluster_id: UUID
) -> CanonicalJD | None:
    """The current canonical for a cluster: the highest-version row. Edits archive the
    prior version and add ``version + 1``, so the max version is the live role."""
    return (
        await session.scalars(
            select(CanonicalJD)
            .where(CanonicalJD.cluster_id == cluster_id)
            .order_by(CanonicalJD.version.desc())
            .limit(1)
        )
    ).first()


async def _role_ref_for_source(
    session: AsyncSession, source_document_id: UUID
) -> RoleRef | None:
    """The harmonized role a source JD fed into, if any — the back-link from a source
    document to its cluster's canonical. ``None`` for a singleton / unclustered doc."""
    cluster = (
        await session.scalars(
            select(Cluster)
            .where(Cluster.members.contains([{"source_id": str(source_document_id)}]))
            .limit(1)
        )
    ).first()
    if cluster is None:
        return None
    canonical = await _latest_canonical_for_cluster(session, cluster.id)
    if canonical is None:
        return None
    title = (canonical.content or {}).get("title") or "(untitled)"
    return RoleRef(
        cluster_id=cluster.id,
        canonical_id=canonical.id,
        title=title,
        status=canonical.status.value,
    )


# --- the source-JD reader (the atom) --------------------------------------------------


async def get_source_jd(
    session: AsyncSession, source_document_id: UUID
) -> SourceJDView | None:
    """One archive source JD rendered readable, or ``None`` if the document is unknown
    or has no parse to render."""
    doc = await session.get(SourceDocument, source_document_id)
    if doc is None:
        return None
    parsed = await _latest_parsed_map(session, [source_document_id])
    jd = parsed.get(source_document_id)
    if jd is None:
        return None
    role = await _role_ref_for_source(session, source_document_id)
    parse_row = (
        await session.scalars(
            select(ParsedJDRow.parse_confidence)
            .where(ParsedJDRow.source_document_id == source_document_id)
            .order_by(ParsedJDRow.created_at.desc())
            .limit(1)
        )
    ).first()
    return SourceJDView(
        source_document_id=source_document_id,
        filename=doc.filename,
        title=jd.title,
        employee_group=jd.employee_group,
        department=jd.department,
        grade=jd.grade,
        position_number=jd.position_number,
        parse_confidence=parse_row if parse_row is not None else 0.0,
        rendered_text=render_sfu_jd_text(jd),
        role=role,
    )


# --- the role (roles → sources) -------------------------------------------------------


async def _member_views(
    session: AsyncSession, cluster: Cluster | None, canonical: CanonicalJD
) -> list[MemberJD]:
    """The source JDs a role was distilled from. Membership + filenames come from the
    cluster snapshot when present (it carries filenames); otherwise the canonical's own
    lineage list (no filenames). Each member's title/group is loaded from its latest
    parse; a member with no parse still lists (``parsed=False``)."""
    refs: list[dict[str, Any]] = []
    if cluster is not None and cluster.members:
        refs = list(cluster.members)
    elif canonical.source_document_ids:
        refs = list(canonical.source_document_ids)
    ids: list[UUID] = []
    for ref in refs:
        raw = ref.get("source_id")
        if raw:
            ids.append(UUID(str(raw)))
    parsed = await _latest_parsed_map(session, ids)
    views: list[MemberJD] = []
    for ref in refs:
        raw = ref.get("source_id")
        if not raw:
            continue
        sid = UUID(str(raw))
        jd = parsed.get(sid)
        views.append(
            MemberJD(
                source_document_id=sid,
                filename=ref.get("filename"),
                title=jd.title if jd is not None else None,
                employee_group=jd.employee_group if jd is not None else None,
                parsed=jd is not None,
            )
        )
    return views


async def get_role(session: AsyncSession, cluster_id: UUID) -> RoleView | None:
    """One harmonized role — the current canonical rendered readable plus the source JDs
    it was distilled from — or ``None`` if the cluster has no canonical."""
    canonical = await _latest_canonical_for_cluster(session, cluster_id)
    if canonical is None:
        return None
    cluster = await session.get(Cluster, cluster_id)
    jd = SFUJobDescription.model_validate(canonical.content)
    members = await _member_views(session, cluster, canonical)
    validator = (canonical.change_log or {}).get("validator") or {}
    return RoleView(
        canonical_id=canonical.id,
        cluster_id=cluster_id,
        title=jd.title,
        status=canonical.status.value,
        version=canonical.version,
        score=validator.get("score"),
        grade=validator.get("grade"),
        rendered_text=render_sfu_jd_text(jd),
        members=tuple(members),
        source_count=len(members),
    )


# --- the roles library (browse) -------------------------------------------------------


def _role_list_item(canonical: CanonicalJD) -> RoleListItem:
    content = canonical.content or {}
    validator = (canonical.change_log or {}).get("validator") or {}
    return RoleListItem(
        canonical_id=canonical.id,
        cluster_id=canonical.cluster_id,
        title=content.get("title") or "(untitled)",
        status=canonical.status.value,
        source_count=len(canonical.source_document_ids or []),
        score=validator.get("score"),
        grade=validator.get("grade"),
    )


async def list_roles(
    session: AsyncSession,
    *,
    q: str = "",
    limit: int | None = None,
    offset: int = 0,
    sort: str = "title",
    direction: str = "asc",
) -> RolePage:
    """A page of harmonized roles (one per cluster, the current version), optionally
    filtered by a title substring and sorted by a clickable column (``sort`` in
    :data:`_ROLE_SORTS`, ``direction`` asc/desc — anything else falls back to title
    asc). ``total`` is the pre-pagination count for the "showing N–M of TOTAL" line."""
    limit = _clamp_limit(limit)
    offset = max(0, offset)
    query = q.strip()
    sort_key = sort if sort in _ROLE_SORTS else "title"
    descending = direction == "desc"
    # The current canonical per cluster: DISTINCT ON (cluster_id) newest version first.
    latest_ids = (
        select(CanonicalJD.id)
        .distinct(CanonicalJD.cluster_id)
        .order_by(CanonicalJD.cluster_id, CanonicalJD.version.desc())
        .subquery()
    )
    base = select(CanonicalJD).join(latest_ids, CanonicalJD.id == latest_ids.c.id)
    if query:
        base = base.where(CanonicalJD.content["title"].astext.ilike(f"%{query}%"))
    total = await session.scalar(select(func.count()).select_from(base.subquery())) or 0
    column = _ROLE_SORTS[sort_key]
    ordering = (column.desc() if descending else column.asc()).nulls_last()
    # Stable, deterministic within the sort key: fall back to title then id.
    rows = (
        await session.scalars(
            base.order_by(
                ordering,
                CanonicalJD.content["title"].astext.asc(),
                CanonicalJD.id.asc(),
            )
            .limit(limit)
            .offset(offset)
        )
    ).all()
    return RolePage(
        items=tuple(_role_list_item(row) for row in rows),
        total=int(total),
        limit=limit,
        offset=offset,
        q=query,
        sort=sort_key,
        direction="desc" if descending else "asc",
    )


# --- the flat source archive (secondary browse) ---------------------------------------


async def list_source_jds(
    session: AsyncSession,
    *,
    q: str = "",
    limit: int | None = None,
    offset: int = 0,
) -> SourcePage:
    """A page of the flat source archive (every ingested .docx), filename-ordered,
    optionally filtered by a filename substring. Each row carries its latest parse's
    title/group when parsed."""
    limit = _clamp_limit(limit)
    offset = max(0, offset)
    query = q.strip()
    base = select(SourceDocument)
    if query:
        base = base.where(SourceDocument.filename.ilike(f"%{query}%"))
    total = await session.scalar(select(func.count()).select_from(base.subquery())) or 0
    docs = (
        await session.scalars(
            base.order_by(SourceDocument.filename.asc().nulls_last())
            .limit(limit)
            .offset(offset)
        )
    ).all()
    parsed = await _latest_parsed_map(session, [doc.id for doc in docs])
    items = [
        SourceListItem(
            source_document_id=doc.id,
            filename=doc.filename,
            title=parsed[doc.id].title if doc.id in parsed else None,
            employee_group=parsed[doc.id].employee_group if doc.id in parsed else None,
            parsed=doc.id in parsed,
        )
        for doc in docs
    ]
    return SourcePage(
        items=tuple(items),
        total=int(total),
        limit=limit,
        offset=offset,
        q=query,
    )

"""Searching by PeopleSoft position number (HR-339) — the Library and the Builder.

HR works from position numbers, and the archive's FILE NAMES carry them
(``<as-of date>_<position list>_JDFN_<group>_<date>``, read by
:mod:`src.jd_bank.positions`, HR-325 … HR-331). A search that is only a position
number is answered from those names: every file filed under it, newest first, each with
the role it was distilled into — and the roles themselves.

The FILES are listed, not only the roles, because measured on the live Bank 1,377 of
5,620 positions have files in no role at all; a roles-only answer would say "nothing"
about a position the archive plainly holds.

Read-only (NN #1).
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.jd_bank.db.models import SourceDocument
from src.jd_bank.library.models import PositionFile, PositionLookup, RoleRef
from src.jd_bank.positions import load_position_index, normalise_position_id
from src.jd_core.rules import Rules, get_rules

__all__ = ["find_position", "read_position_query", "role_ids"]


def read_position_query(query: str, rules: Rules | None = None) -> str | None:
    """The 8-digit position ``query`` names, or ``None`` if it is not ONLY a position
    number — or if position search is switched off (``search`` not among
    ``segmentation.filename_positions.consumers``, HR-331)."""
    resolved = rules if rules is not None else get_rules()
    reader = resolved.segmentation.filename_positions
    if "search" not in reader.consumers:
        return None
    match = resolved.search.position_query_pattern.fullmatch(query)
    if match is None:
        return None
    digits = match.group(1)
    if len(digits) == 8 and digits.startswith("0"):
        # The padded form, as `position_id_pattern` keeps it (no ceiling).
        return digits if digits != "00000000" else None
    return normalise_position_id(digits, max_position_id=reader.max_position_id)


#: The CURRENT version of every role that lists one of ``:ids`` among its sources.
_ROLES_OF_DOCS = text("""
    SELECT cur.cluster_id, cur.id, cur.content->>'title' AS title,
           cur.status::text AS status, s.value->>'source_id' AS source_id
    FROM (
      SELECT DISTINCT ON (cluster_id) cluster_id, id, content, status,
             source_document_ids
      FROM canonical_jds ORDER BY cluster_id, version DESC
    ) cur
    CROSS JOIN LATERAL jsonb_array_elements(cur.source_document_ids) s
    WHERE s.value->>'source_id' = ANY(CAST(:ids AS text[]))
    ORDER BY title, cur.cluster_id
""")


async def find_position(session: AsyncSession, position: str) -> PositionLookup:
    """Every archive file whose name carries ``position`` (8-digit), newest first,
    each with the role it went into."""
    index = await load_position_index(session)
    doc_ids = index.docs_for(position)
    if not doc_ids:
        return PositionLookup(position=position, files=())
    names = dict(
        (
            await session.execute(
                select(SourceDocument.id, SourceDocument.filename).where(
                    SourceDocument.id.in_(doc_ids)
                )
            )
        )
        .tuples()
        .all()
    )
    role_of: dict[str, RoleRef] = {}
    for row in await session.execute(
        _ROLES_OF_DOCS, {"ids": [str(d) for d in doc_ids]}
    ):
        # A file in two roles is rare; the first by title is shown, deterministically.
        role_of.setdefault(
            row.source_id,
            RoleRef(
                cluster_id=row.cluster_id,
                canonical_id=row.id,
                title=row.title or "(untitled)",
                status=row.status,
            ),
        )
    files = [
        PositionFile(
            source_document_id=doc_id,
            filename=names.get(doc_id),
            file_date=index.by_doc[doc_id].as_of_date,
            role=role_of.get(str(doc_id)),
        )
        for doc_id in doc_ids
    ]
    # Newest first; a name with no date last; ties by name.
    files.sort(
        key=lambda f: (
            f.file_date is None,
            -(f.file_date.toordinal() if f.file_date else 0),
            f.filename or "",
        )
    )
    return PositionLookup(position=position, files=tuple(files))


def role_ids(lookup: PositionLookup) -> tuple[UUID, ...]:
    """The distinct roles the position's files went into, in file order."""
    seen: dict[UUID, None] = {}
    for f in lookup.files:
        if f.role is not None:
            seen.setdefault(f.role.cluster_id, None)
    return tuple(seen)

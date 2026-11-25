"""Every document's filename positions, both ways round, computed on read.

Built from ``SELECT id, filename FROM source_documents`` — nothing is stored, so a
change to a ``filename_positions`` knob needs no migration and no re-parse. The
corroboration gate (HR-328) needs the WHOLE Bank (an id is vouched when it appears
zero-padded in any filename), which is why one document cannot be read alone.

Cached per process. The cache key is the table's row count PLUS a cheap checksum of
its ids and filenames, and the segmentation rules' own digest: a row count alone
cannot tell two different Banks of the same size apart (a test that empties and
refills the table, or one file renamed), and a retuned rulebook must not be served an
index read under the old one.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.jd_bank.positions.filename import FilenameFacets, read_filename
from src.jd_core.rules import Segmentation, get_rules

__all__ = ["PositionIndex", "load_position_index"]


@dataclass(frozen=True)
class PositionIndex:
    """doc -> its filename facts, and position -> the documents that name it."""

    by_doc: Mapping[UUID, FilenameFacets]
    by_position: Mapping[str, tuple[UUID, ...]]

    @classmethod
    def build(
        cls, rows: Iterable[tuple[UUID, str | None]], seg: Segmentation
    ) -> PositionIndex:
        named = [(doc_id, name) for doc_id, name in rows if name]
        vouched = frozenset(
            match.group(1) if match.re.groups else match.group(0)
            for _, name in named
            for match in seg.position_id_pattern.finditer(name)
        )
        by_doc: dict[UUID, FilenameFacets] = {}
        by_position: defaultdict[str, list[UUID]] = defaultdict(list)
        for doc_id, name in named:
            facets = read_filename(name, seg, vouched)
            by_doc[doc_id] = facets
            for position in facets.position_ids:
                by_position[position].append(doc_id)
        return cls(
            by_doc=MappingProxyType(by_doc),
            by_position=MappingProxyType(
                {pid: tuple(docs) for pid, docs in by_position.items()}
            ),
        )

    def positions_of(self, doc_id: UUID) -> tuple[str, ...]:
        """The positions ``doc_id``'s filename names; ``()`` if none / unknown."""
        facets = self.by_doc.get(doc_id)
        return facets.position_ids if facets is not None else ()

    def docs_for(self, position: str) -> tuple[UUID, ...]:
        """Every document whose filename names ``position`` (8-digit padded)."""
        return self.by_position.get(position, ())

    @property
    def files_with_positions(self) -> int:
        return sum(1 for facets in self.by_doc.values() if facets.positions)


_FINGERPRINT = text(
    "SELECT count(*), "
    "coalesce(sum(hashtext(id::text || ':' || coalesce(filename, ''))::bigint), 0) "
    "FROM source_documents"
)
_ROWS = text("SELECT id, filename FROM source_documents")

_cache: tuple[tuple[int, int, str], PositionIndex] | None = None


async def load_position_index(session: AsyncSession) -> PositionIndex:
    """The Bank's :class:`PositionIndex`, rebuilt only when the table changed."""
    global _cache
    seg = get_rules().segmentation
    count, checksum = (await session.execute(_FINGERPRINT)).one()
    key = (int(count), int(checksum), seg.digest)
    if _cache is not None and _cache[0] == key:
        return _cache[1]
    rows = (await session.execute(_ROWS)).all()
    index = PositionIndex.build(((row[0], row[1]) for row in rows), seg)
    _cache = (key, index)
    return index

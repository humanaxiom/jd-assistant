"""Persistence for the parse step — write a :class:`ParsedJDRow` from a
segmented JD.

Keeps the SQLAlchemy boundary out of :mod:`jd_core.parser.segmenter` (which is
pure/deterministic and unit-tested without a database): the segmenter produces a
:class:`ParseResult`, this module serialises it into the ``parsed_jds`` row
(``parsed`` = ``SFUJobDescription.model_dump(mode="json")`` — JSONB-safe — plus
``parser_version`` and ``parse_confidence``) with its FK back to the source
document.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from src.jd_bank.db.models import ParsedJDRow, SourceDocument
from src.jd_core.parser.segmenter import ParseResult, parse_jd


async def parse_and_store(
    session: AsyncSession, source_document: SourceDocument, text: str
) -> ParsedJDRow:
    """Segment ``text`` and insert a ``parsed_jds`` row for ``source_document``.

    Adds and flushes the row (so its PK is populated) but does **not** commit —
    the caller owns the transaction. Returns the persisted row.
    """
    result: ParseResult = parse_jd(text)
    row = ParsedJDRow(
        source_document_id=source_document.id,
        parsed=result.jd.model_dump(mode="json"),
        parser_version=result.parser_version,
        parse_confidence=result.parse_confidence,
    )
    session.add(row)
    await session.flush()
    return row

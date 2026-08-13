"""Persistence for the parse step — write a :class:`ParsedJDRow` from a
segmented JD.

Keeps the SQLAlchemy boundary out of :mod:`jd_core.parser.segmenter` (which is
pure/deterministic and unit-tested without a database): the segmenter produces a
:class:`ParseResult`, this module serialises it into the ``parsed_jds`` row
(``parsed`` = ``SFUJobDescription.model_dump(mode="json")`` — JSONB-safe — plus
``parser_version`` and ``parse_confidence``) with its FK back to the source
document.

**Idempotent on ``(source_document_id, parser_version)``** (Phase 3.2a, LANDMINE 1,
migration ``0003``). The parse is pure over ``(extracted text, parser_version)``
— NOT of the source bytes: the same bytes yield different text when the extractor
changes (the ``.docx`` table/content-control fix rewrote what python-docx returns; the
extension-sniff backlog item would reroute a mis-named file to a different backend). So
re-parsing the same document at the same parser version returns the existing row, not a
second one — otherwise a re-run of the archive ingest driver
(:mod:`src.jd_bank.ingest.driver`) would double (then triple, ...) every row in
``parsed_jds``, and Phase 3.2b keys vectors off these rows.

**The idempotency key is BLIND to the extractor** (backlog). An extractor-only change
(same ``parser_version``, different extracted text) does NOT bump ``parser_version``, so
it does NOT force a re-parse through this key — a caller that wants the new text
reflected must re-parse deliberately (as the orchestrator's re-parse does). A parser
change — like the Phase-3.4 WJQ router — DOES move ``parser_version``, and that is what
forces the archive re-parse. Folding the extractor identity into the key is a schema
change, deliberately not done here.

Mirrors :func:`~src.jd_bank.ingest.ingest.ingest_document`'s proven idiom exactly:
select-by-key first; if found, return it; else INSERT inside a SAVEPOINT
(``session.begin_nested()``), and on ``IntegrityError`` (lost the race to a concurrent
insert of the same key) re-select and return the winner. The SAVEPOINT is what makes
losing the race cost exactly this one row — a bare ``session.rollback()`` would roll
back the CALLER'S WHOLE TRANSACTION, silently discarding every other document staged in
a batch ingest.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.jd_bank.db.models import ParsedJDRow, SourceDocument
from src.jd_core.parser.segmenter import PARSER_VERSION, ParseResult, parse_jd


async def _existing(
    session: AsyncSession, *, source_document_id: uuid.UUID, parser_version: str
) -> ParsedJDRow | None:
    """The row for THIS (source document, parser version), if it has already been
    parsed."""
    row: ParsedJDRow | None = await session.scalar(
        select(ParsedJDRow).where(
            ParsedJDRow.source_document_id == source_document_id,
            ParsedJDRow.parser_version == parser_version,
        )
    )
    return row


async def parse_and_store(
    session: AsyncSession, source_document: SourceDocument, text: str
) -> ParsedJDRow:
    """Segment ``text`` and insert a ``parsed_jds`` row for ``source_document``, or
    return the row that already exists for this ``(source_document, parser_version)``.

    Flushes the row (so its PK is populated) but does **not** commit — the caller owns
    the transaction. Returns the persisted row.
    """
    existing = await _existing(
        session,
        source_document_id=source_document.id,
        parser_version=PARSER_VERSION,
    )
    if existing is not None:
        return existing

    result: ParseResult = parse_jd(text)
    row = ParsedJDRow(
        source_document_id=source_document.id,
        parsed=result.jd.model_dump(mode="json"),
        parser_version=result.parser_version,
        parse_confidence=result.parse_confidence,
    )
    # SAVEPOINT, exactly as `ingest_document` does — see the module docstring for why
    # a bare `session.rollback()` on the IntegrityError branch would be wrong.
    try:
        async with session.begin_nested():
            session.add(row)
            await session.flush()
    except IntegrityError:
        # Re-select on PARSER_VERSION — the SAME key the pre-check used. (`result.
        # parser_version` is that same constant today, but one key must have one
        # source, or a future parser that stamps a row differently from what it
        # selects on would look up the wrong row here and raise.)
        winner = await _existing(
            session,
            source_document_id=source_document.id,
            parser_version=PARSER_VERSION,
        )
        if winner is None:  # pragma: no cover — defensive; the unique row must exist
            raise
        return winner

    return row

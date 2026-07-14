"""Where Tier-2 gets a document's TEXT from — the injectable I/O boundary.

``run_tier2`` (:mod:`.runner`) never reads bytes or a database itself; it takes a
:class:`TextSource` and calls it once per DISTINCT content. That is what lets the
integration suite exercise the whole reconcile/prune/orient pipeline with a
**content-keyed fake** and no archive or parser on disk (HANDOFF: "fakes in this suite
must be content-keyed" — 3.2b's index-keyed fake made a whole class of bug
unwritable), and what lets the real runs choose between the two rulebook-configured
text sources (``dedup.text_source``, HR-131) without the runner caring which one it
got.

Two real implementations, both measured in HANDOFF 2026-07-13:

* :class:`ArchiveTextSource` — re-reads bytes from ``storage_ref`` and re-extracts +
  scrubs, because Postgres holds no text column (``ingest_document`` computes the
  clean text and the driver discards it — see ``jd_bank.ingest.driver``'s own
  docstring for why). Covers 14,452 of 14,565 files.
* :class:`SerializedTextSource` — the PARSED JD run through
  ``jd_core.bank.embed_text.serialize_document``, Phase 3.2b's own pipeline. Covers
  only 9,517 (34.5% of parsed JDs serialize to empty — the WJQ-template gap).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.jd_bank.db.models import ParsedJDRow
from src.jd_bank.dedup.models import DocumentRef
from src.jd_bank.ingest.extract import (
    DocumentTooLargeError,
    ExtractionError,
    extract_text,
    read_document_bytes,
)
from src.jd_bank.ingest.scrub import normalize_incumbent_names
from src.jd_bank.stable_reason import stable_reason
from src.jd_core.bank.embed_text import serialize_document
from src.jd_core.models.parsed_jd import SFUJobDescription
from src.jd_core.parser import PARSER_VERSION
from src.jd_core.rules import Embeddings, Rules


@dataclass(frozen=True, slots=True)
class TextResult:
    """A :class:`TextSource`'s answer for one document: the text, or ``None`` with a
    stable (per-run-reproducible) reason it could not be produced."""

    text: str | None
    reason: str | None = None

    def __post_init__(self) -> None:
        if self.text is None and self.reason is None:
            raise ValueError("a missing TextResult.text must carry a reason")


@runtime_checkable
class TextSource(Protocol):
    """What :func:`~src.jd_bank.dedup.near.runner.run_tier2` needs from a text
    provider — nothing more. It is called once per DISTINCT content (see
    :class:`~src.jd_bank.dedup.near.models.Signature`'s memoization contract), never
    once per file."""

    async def text_for(self, ref: DocumentRef) -> TextResult: ...


class ArchiveTextSource:
    """Re-reads ``ref.storage_ref`` from disk, re-extracts, and scrubs incumbent
    names — the ``raw_clean`` branch of ``dedup.text_source`` (HR-131).

    Reuses ``ingest/extract.py`` + ``ingest/scrub.py`` verbatim — this is
    deliberately NOT a second archive walker (HANDOFF: "do not hand-roll a second
    path"). Format detection is by filename extension, the same rule
    ``jd_bank.ingest.ingest.detect_format`` applies at ingest time.
    """

    async def text_for(self, ref: DocumentRef) -> TextResult:
        from src.jd_bank.ingest.ingest import (
            detect_format,  # noqa: PLC0415 - avoids a package import cycle, same reason extract.py's own lazy import does
        )

        path = Path(ref.storage_ref)
        try:
            data = await asyncio.to_thread(read_document_bytes, path)
        except (DocumentTooLargeError, OSError) as exc:
            return TextResult(text=None, reason=stable_reason(exc))

        fmt = detect_format(ref.filename or path.name)
        try:
            raw_text = await asyncio.to_thread(extract_text, data, fmt)
        except ExtractionError as exc:
            return TextResult(text=None, reason=stable_reason(exc))

        scrubbed, _report = await asyncio.to_thread(normalize_incumbent_names, raw_text)
        if not scrubbed.strip():
            return TextResult(text=None, reason="extracted to empty text")
        return TextResult(text=scrubbed)


class SerializedTextSource:
    """The PARSED JD, serialized exactly as Phase 3.2b embeds it — the
    ``serialized`` branch of ``dedup.text_source`` (HR-131).

    Reads the LIVE-parser-version ``parsed_jds`` row for ``ref.id`` and runs it
    through ``jd_core.bank.embed_text.serialize_document`` (never re-implements that
    pipeline — one rulebook fact, one home). A JD with no such row (unparsed, or
    parsed at a stale ``parser_version``) or whose configured sections all serialize
    to empty (the WJQ-template gap) is reported as unreadable, not silently skipped.
    """

    def __init__(self, session: AsyncSession, *, embeddings_rules: Embeddings) -> None:
        self._session = session
        self._embeddings_rules = embeddings_rules

    async def text_for(self, ref: DocumentRef) -> TextResult:
        row = await self._session.scalar(
            select(ParsedJDRow).where(
                ParsedJDRow.source_document_id == ref.id,
                ParsedJDRow.parser_version == PARSER_VERSION,
            )
        )
        if row is None:
            return TextResult(text=None, reason="no parsed_jds row at PARSER_VERSION")

        jd = SFUJobDescription.model_validate(row.parsed)
        serialized = serialize_document(jd, self._embeddings_rules)
        if not serialized.text:
            return TextResult(
                text=None, reason="serializes to empty (WJQ-template gap, HR-131)"
            )
        return TextResult(text=serialized.text)


def text_source_for(rules: Rules, session: AsyncSession) -> TextSource:
    """The :class:`TextSource` the rulebook's ``dedup.text_source`` (HR-131) SELECTS.

    **This is what makes ``text_source`` a real knob rather than a stamp.** HR-131's
    own defence is *"Both branches are IMPLEMENTED — a knob whose alternative does
    nothing is the ``cluster_algo`` landmine in a new place."* Implemented is not
    enough: the first cut selected the branch inline in ``__main__``, where nothing
    tested it, so flipping the knob moved only ``Dedup.stamp`` and no behaviour was
    pinned anywhere — HR-123's landmine with one extra step, not without it. Selecting
    here, in one exported function, is what lets
    ``test_dedup_near_text.py::test_the_text_source_knob_selects_the_source`` prove the
    flip actually changes which code runs.

    Exhaustive over :data:`~src.jd_core.rules.DedupTextSource` by construction: the
    ``Literal`` has two members and both are handled, so a third added to the rulebook
    without a branch here fails ``mypy --strict`` rather than silently falling through
    to a default.
    """
    if rules.dedup.text_source == "raw_clean":
        return ArchiveTextSource()
    return SerializedTextSource(session, embeddings_rules=rules.embeddings)

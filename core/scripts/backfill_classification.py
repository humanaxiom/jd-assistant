"""One-time backfill: populate ``parsed_jds.parsed['classification']`` on existing rows.

**SUPERSEDED (parser v3).** This ran once, against ``jd_segmenter_v2`` rows, and the
pinned version below is deliberately historical — v3 extracts ``classification`` during
the parse itself (including the APSA/APEX grades in the docx header that v2 could not
see), so a v3 archive re-parse needs no backfill. Kept as the audit trail of what was
written to the v2 rows; do not re-point it at a newer version.

Phase A wired ``extract_classification`` into the parsers, but the parse is idempotent on
``(source_document_id, parser_version)`` — existing rows are NOT re-parsed. This re-extracts
each source document, runs the current parser, and writes the freshly-computed
``classification`` back onto the stored parse **in place** (same ``parser_version``), so the
new field is populated without a version bump or any downstream re-run (nothing downstream
reads ``classification`` yet).

Additive + idempotent: it only sets the ``classification`` key (via ``jsonb_set``) and only
when a classification is found; re-running writes the same value. JDFN docs almost never
carry a grade, so most rows are left unchanged (``classification`` stays absent -> ``None``).

Run in the archive-mounted ``baseline`` service:
    JD_ARCHIVE_PATH=/path/to/SFU_JDs docker compose run --rm baseline \
        python scripts/backfill_classification.py
"""

from __future__ import annotations

import asyncio
import json
import sys

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.jd_bank.db.models import ParsedJDRow, SourceDocument
from src.jd_bank.ingest.extract import extract_text_from_path
from src.jd_core.parser import parse_jd
from src.settings import get_settings

_ARCHIVE = "/archive"
_PARSER_VERSION = "jd_segmenter_v2"
_COMMIT_EVERY = 500


def _log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


async def main() -> None:
    engine = create_async_engine(get_settings().database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    seen = updated = errors = 0
    async with maker() as session:
        # Every source document that has a current-version parse to update.
        rows = await session.stream(
            select(SourceDocument.id, SourceDocument.filename)
            .join(ParsedJDRow, ParsedJDRow.source_document_id == SourceDocument.id)
            .where(ParsedJDRow.parser_version == _PARSER_VERSION)
        )
        async for source_id, filename in rows:
            seen += 1
            if filename:
                try:
                    jd = parse_jd(extract_text_from_path(f"{_ARCHIVE}/{filename}")).jd
                except Exception:  # noqa: BLE001 — a bad file must not abort the backfill
                    errors += 1
                    jd = None
                if jd is not None and jd.classification is not None:
                    await session.execute(
                        text(
                            "UPDATE parsed_jds "
                            "SET parsed = jsonb_set(parsed, '{classification}', "
                            "cast(:cls as jsonb)) "
                            "WHERE source_document_id = cast(:sid as uuid) "
                            "AND parser_version = :pv"
                        ),
                        {
                            "cls": json.dumps(jd.classification.model_dump()),
                            "sid": str(source_id),
                            "pv": _PARSER_VERSION,
                        },
                    )
                    updated += 1
            if seen % _COMMIT_EVERY == 0:
                await session.commit()
                _log(f"  {seen} seen · {updated} updated · {errors} extract errors")
        await session.commit()
    await engine.dispose()
    _log(f"DONE: {seen} seen · {updated} classifications written · {errors} extract errors")


if __name__ == "__main__":
    asyncio.run(main())

"""Apply an HRIS grade export to canonical roles by position number (Phase C, scaffold).

Reads an HR-provided CSV (``position_number,scheme,grade``), parses it with
:func:`src.jd_bank.grade_import.parse_grade_csv`, and writes a ``source="hris"``
``classification`` onto each ``canonical_jds`` row whose ``content.position_number``
matches — via ``jsonb_set``, idempotent, downstream untouched.

**Do not run this for real without the HR export AND a FIPPA review** (grade is
compensation-adjacent data). ``position_number`` is only ~35% populated (see the data-state
review), so coverage is bounded by that join key.

    docker compose run --rm api python scripts/import_grades.py /path/to/grades.csv
"""

from __future__ import annotations

import asyncio
import json
import sys

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.jd_bank.db.models import CanonicalJD
from src.jd_bank.grade_import import parse_grade_csv
from src.settings import get_settings


def _log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


async def apply_import(csv_path: str) -> tuple[int, int]:
    """Apply the CSV to canonical roles; returns ``(matched, updated)``."""
    with open(csv_path, encoding="utf-8") as handle:
        mapping = parse_grade_csv(handle.read())
    _log(f"loaded {len(mapping)} grades from {csv_path}")
    matched = updated = 0
    engine = create_async_engine(get_settings().database_url)
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        rows = await session.stream(
            select(CanonicalJD.id, CanonicalJD.content["position_number"].astext)
        )
        async for canonical_id, position_number in rows:
            classification = mapping.get((position_number or "").strip())
            if classification is None:
                continue
            matched += 1
            await session.execute(
                text(
                    "UPDATE canonical_jds "
                    "SET content = jsonb_set(content, '{classification}', "
                    "cast(:cls as jsonb)) WHERE id = cast(:cid as uuid)"
                ),
                {
                    "cls": json.dumps(classification.model_dump()),
                    "cid": str(canonical_id),
                },
            )
            updated += 1
        await session.commit()
    await engine.dispose()
    return matched, updated


async def main() -> None:
    if len(sys.argv) != 2:
        _log("usage: python scripts/import_grades.py <grades.csv>")
        raise SystemExit(2)
    matched, updated = await apply_import(sys.argv[1])
    _log(f"DONE: {matched} matched, {updated} classifications written (source=hris)")


if __name__ == "__main__":
    asyncio.run(main())

"""``python -m src.jd_bank.ingest`` — the archive -> Postgres ingest driver.

Phase 3.2a. Docker-only (ADR-006). Unlike ``baseline``/``dedup`` (pure reads of the
archive that persist nothing), this one **needs Postgres** — it is what fills
``source_documents`` and ``parsed_jds`` for the first time::

    make ingest JD_ARCHIVE_PATH=/path/to/SFU_JDs
    make ingest JD_ARCHIVE_PATH=/path/to/SFU_JDs INGEST_ARGS="--limit 200"

Prints the run's :class:`~src.jd_bank.ingest.models.IngestResult` counts. Does not
write a committed artifact of its own — the ledger lives in the database (that is the
point of this phase), and the skip entries are printed for visibility.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Sequence
from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.jd_bank.ingest.driver import run_archive_ingest
from src.jd_bank.ingest.models import IngestResult
from src.settings import get_settings


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m src.jd_bank.ingest",
        description="Ingest + parse the SFU JD archive into Postgres.",
    )
    parser.add_argument(
        "--archive-root",
        type=Path,
        default=Path("/archive"),
        help="archive root (read-only bind; default: /archive)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="ingest only the first N files of the sorted walk (smoke test)",
    )
    parser.add_argument(
        "--commit-every",
        type=int,
        default=200,
        help="commit after this many files (default: 200) — bounds how much a "
        "mid-run failure can lose",
    )
    return parser.parse_args(argv)


async def _run(args: argparse.Namespace) -> IngestResult:
    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_maker() as session:
            return await run_archive_ingest(
                session,
                args.archive_root,
                limit=args.limit,
                commit_every=args.commit_every,
            )
    finally:
        await engine.dispose()


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(list(sys.argv[1:] if argv is None else argv))
    print(f"archive={args.archive_root}  limit={args.limit}", file=sys.stderr)

    try:
        result = asyncio.run(_run(args))
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(
        f"\n{result.files_seen} files seen: {result.ingested} newly ingested, "
        f"{result.parsed} newly parsed, {result.already_done} already done, "
        f"{result.failed} failed.",
        file=sys.stderr,
    )
    for entry in result.skipped:
        print(f"  skip: {entry.storage_ref} — {entry.reason}", file=sys.stderr)
    return 0


if __name__ == "__main__":  # pragma: no cover - module entry point
    raise SystemExit(main())

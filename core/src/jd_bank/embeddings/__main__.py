"""``python -m src.jd_bank.embeddings`` — embed ``parsed_jds`` into Neo4j (Phase 3.2b).

Docker-only (ADR-006). Unlike ``ingest`` (which needs only Postgres), this needs
**Postgres, Neo4j, AND a reachable Ollama** (``OLLAMA_BASE_URL`` — ``aria-gb10-2``,
ADR-003) — run `make up` + `make migrate` + `make ingest` first::

    make embed
    make embed EMBED_ARGS="--limit 200"

Writes ``docs/embeddings/summary.json`` — counts and stamps ONLY, **never a
vector** (embeddings are not guaranteed byte-reproducible across model-server
versions, so no committed file may claim to reproduce one).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from neo4j import AsyncGraphDatabase
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.jd_bank.embeddings.models import EmbedRunResult
from src.jd_bank.embeddings.runner import run_embeddings
from src.settings import get_settings


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m src.jd_bank.embeddings",
        description="Embed parsed_jds (Postgres) into Neo4j's vector index.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="embed only the first N parsed_jds rows (smoke test)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=None,
        help="override the operational batch size (default: settings.embed_batch_size)",
    )
    # `type=str`, NOT `type=Path`: argparse would turn `--summary-out ""` into
    # `Path('.')` — which is TRUTHY, so the documented "pass an empty string to skip"
    # fell straight through to `write_text` on a DIRECTORY and raised
    # IsADirectoryError. The empty string is decided here, before it becomes a Path.
    parser.add_argument(
        "--summary-out",
        type=str,
        default="/committed/summary.json",
        help="where the COMMITTED counts+stamps summary goes (bound to "
        "docs/embeddings/; default: /committed/summary.json). Pass an empty "
        "string to skip.",
    )
    return parser.parse_args(argv)


async def _run(args: argparse.Namespace) -> EmbedRunResult:
    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    driver = AsyncGraphDatabase.driver(
        settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password)
    )
    try:
        async with session_maker() as session:
            return await run_embeddings(
                session,
                driver,
                limit=args.limit,
                batch_size=args.batch_size or settings.embed_batch_size,
            )
    finally:
        await driver.close()
        await engine.dispose()


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(list(sys.argv[1:] if argv is None else argv))
    result = asyncio.run(_run(args))

    print(
        f"documents: {result.documents_seen} seen, {result.documents_embedded} "
        f"embedded, {result.documents_unchanged} unchanged, {result.documents_empty} "
        f"empty (skipped, never a zero vector)\n"
        f"sections: {result.sections_embedded} embedded, {result.sections_unchanged} "
        f"unchanged, {result.sections_skipped_short} skipped "
        f"(< min_section_chars)\n"
        f"nodes pruned (no longer planned): {result.nodes_pruned}\n"
        f"embed calls: {result.embed_calls}  reused-by-memo: "
        f"{result.embed_texts_reused_memo}  bad_requests: {result.bad_requests}\n"
        f"model={result.model} dimensions={result.dimensions} "
        f"embed_stamp={result.embed_stamp}",
        file=sys.stderr,
    )

    if args.summary_out:
        summary_out = Path(args.summary_out)
        summary_out.parent.mkdir(parents=True, exist_ok=True)
        summary_out.write_text(
            json.dumps(result.model_dump(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(f"wrote {summary_out}", file=sys.stderr)
    return 0


if __name__ == "__main__":  # pragma: no cover - module entry point
    raise SystemExit(main())

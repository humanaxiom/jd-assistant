"""Embed harmonized ROLES into Neo4j's ``jd_role_embeddings`` index.

Docker-only (ADR-006). Needs **Postgres, Neo4j, AND a reachable Ollama**
(``OLLAMA_BASE_URL`` — ``aria-gb10-2``, ADR-003), and migration 003 applied::

    make embed-roles
    make embed-roles EMBED_ROLES_ARGS="--limit 50"

Idempotent and skip-first: a re-run embeds only the roles whose text changed (a
reviewer's edit, a re-harmonization), and prunes role nodes whose cluster is gone.
Deliberately separate from ``approve`` — publishing must never depend on the GPU.

Writes ``docs/embeddings/roles-summary.json``: counts and stamps ONLY, never a vector.
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

from src.jd_bank.embeddings.client import EmbedClient
from src.jd_bank.embeddings.roles import RoleEmbeddingSummary, run_role_embedding
from src.settings import get_settings


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python scripts/embed_roles.py",
        description="Embed harmonized roles (canonical_jds) into Neo4j.",
    )
    parser.add_argument(
        "--limit", type=int, default=None, help="embed only the first N roles"
    )
    parser.add_argument(
        "--summary-out",
        type=str,
        default="/committed/roles-summary.json",
        help="where the COMMITTED counts+stamps summary goes. Empty string to skip.",
    )
    return parser.parse_args(argv)


async def _run(args: argparse.Namespace) -> RoleEmbeddingSummary:
    settings = get_settings()
    engine = create_async_engine(settings.database_url)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    driver = AsyncGraphDatabase.driver(
        settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password)
    )
    client = EmbedClient()
    try:
        async with session_maker() as session:
            return await run_role_embedding(
                session,
                embed_client=client,
                neo4j_driver=driver,
                limit=args.limit,
            )
    finally:
        await client.close()
        await driver.close()
        await engine.dispose()


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(list(sys.argv[1:] if argv is None else argv))
    summary = asyncio.run(_run(args))

    # ⚠ `roles_rejected` and `roles_backed_off` are PRINTED, not merely written to the
    # JSON. They were in the summary file and absent from this line, which is the same
    # defect in miniature as the one they exist to report: an operator watching the
    # terminal saw "seen / embedded / unchanged / empty" and had no way to learn that a
    # role had been dropped. A count nobody is shown is not a report.
    print(
        f"roles: {summary.roles_seen} seen, {summary.roles_embedded} embedded, "
        f"{summary.roles_unchanged} unchanged, {summary.roles_empty} empty "
        f"(skipped, never a zero vector)\n"
        f"over-long: {summary.roles_backed_off} embedded from a SHORTER re-cut "
        f"(HR-193 ladder), {summary.roles_rejected} refused even at the shortest rung"
        + (
            " <- THESE ROLES HAVE NO VECTOR and are invisible to Builder search"
            if summary.roles_rejected
            else ""
        )
        + f"\nnodes pruned (no longer planned): {summary.nodes_pruned}\n"
        f"model={summary.model} dimensions={summary.dimensions} "
        f"embed_stamp={summary.embed_stamp}",
        file=sys.stderr,
    )

    if args.summary_out:
        out = Path(args.summary_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps(summary.model_dump(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

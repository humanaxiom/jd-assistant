"""``python -m src.jd_bank.dedup.role`` — the Tier-3 role-equivalence pass (Phase 3.4b).

Docker-only (ADR-006). Needs Postgres (``parsed_jds`` at the live ``parser_version`` —
run ``make ingest`` first) and Neo4j (the document vectors Phase 3.2b wrote — run ``make
embed`` first). NO archive bind: Tier-3 reads signals from ``parsed_jds`` and vectors
from Neo4j, never the raw files::

    make dedup-role
    make dedup-role DEDUPROLE_ARGS="--limit 200"

Writes ``docs/dedup/role-equiv-summary.json`` (counts, percentiles, stamps — never
document text) and ``docs/dedup/role-equiv-adjudication-sample.csv`` (filenames + scores
+ an empty ``human_label`` column for a real reviewer).

**Commits once, after the full reconcile** — like Tier-2, the reconcile needs the WHOLE
plan before it can safely decide what to prune. ``--limit`` is a SMOKE TEST, not a
resumable partial run (the prune scope is what was read, so a limited run cannot prune
what it never looked at — harmless, but it is not how you build a real Tier-3 edge set).
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Sequence
from pathlib import Path

from neo4j import AsyncGraphDatabase
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.jd_bank.dedup.role.models import Tier3Result
from src.jd_bank.dedup.role.report import (
    DEFAULT_ADJUDICATION_TARGET,
    RoleEquivSummary,
    build_role_equiv_summary,
    sample_for_adjudication,
    write_adjudication_csv,
    write_summary,
)
from src.jd_bank.dedup.role.runner import run_tier3
from src.jd_core.rules import get_rules
from src.settings import get_settings


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m src.jd_bank.dedup.role",
        description="Tier-3 role-equivalence dedup: signals + idf-weighted skills + "
        "doc vectors, veto-constrained, DB-reconciled.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="consider only the first N parsed_jds rows (smoke test)",
    )
    parser.add_argument(
        "--summary-out",
        type=str,
        default="/committed/role-equiv-summary.json",
        help="where the COMMITTED summary goes (bound to docs/dedup/). Empty to skip.",
    )
    parser.add_argument(
        "--adjudication-out",
        type=str,
        default="/committed/role-equiv-adjudication-sample.csv",
        help="where the COMMITTED adjudication sample goes (bound to docs/dedup/). "
        "Empty to skip.",
    )
    parser.add_argument(
        "--adjudication-target",
        type=int,
        default=DEFAULT_ADJUDICATION_TARGET,
        help=f"approximate adjudication sample size (default: "
        f"{DEFAULT_ADJUDICATION_TARGET})",
    )
    return parser.parse_args(argv)


async def _run(args: argparse.Namespace) -> tuple[Tier3Result, RoleEquivSummary]:
    settings = get_settings()
    rules = get_rules()
    engine = create_async_engine(settings.database_url)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    driver = AsyncGraphDatabase.driver(
        settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password)
    )
    try:
        async with session_maker() as session:
            result = await run_tier3(
                session, neo4j_driver=driver, rules=rules, limit=args.limit
            )
            await session.commit()
    finally:
        await driver.close()
        await engine.dispose()

    summary = build_role_equiv_summary(
        result, source="parsed_jds + JDDocument vectors", rules_version=rules.version
    )
    return result, summary


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(list(sys.argv[1:] if argv is None else argv))
    result, summary = asyncio.run(_run(args))

    print(
        f"documents: {summary.documents_seen} seen -> "
        f"{summary.documents_signed} signed "
        f"({summary.documents_unsignable} unsignable, "
        f"{summary.documents_with_vector} with vector, "
        f"{summary.documents_without_vector} without)\n"
        f"candidates: {summary.candidate_pairs} -> {summary.band_vetoed} band-vetoed, "
        f"{summary.group_vetoed} group-vetoed -> {summary.admissible_pairs} admissible "
        f"-> {summary.qualifying_pairs} qualifying (>= "
        f"{summary.role_equiv_threshold}), "
        f"{summary.restricted_flagged} restricted-flagged\n"
        f"function split (qualifying): same={summary.same_function_edges} "
        f"cross={summary.cross_function_edges}\n"
        f"edges — written: {summary.edges_written}  updated: {summary.edges_updated}  "
        f"unchanged: {summary.edges_unchanged}  pruned: {summary.edges_pruned}\n"
        f"rules_version={summary.rules_version}  dedup_stamp={summary.dedup_stamp}  "
        f"idf_stamp={summary.idf_stamp} ({summary.idf_skills} skills)",
        file=sys.stderr,
    )

    if args.summary_out:
        written = write_summary(summary, Path(args.summary_out))
        print(f"wrote {written}", file=sys.stderr)

    if args.adjudication_out:
        sample = sample_for_adjudication(result.pairs, target=args.adjudication_target)
        written = write_adjudication_csv(sample, Path(args.adjudication_out))
        print(f"wrote {written} ({len(sample)} pairs)", file=sys.stderr)

    return 0


if __name__ == "__main__":  # pragma: no cover - module entry point
    raise SystemExit(main())

"""``python -m src.jd_bank.cluster`` — the Phase-3.5 clustering pass (report-only).

Docker-only (ADR-006). Needs Postgres (``parsed_jds`` at the live ``parser_version`` +
``dedup_edges`` — run ``make ingest``, ``make near-dup``, ``make dedup-role`` first).
It reads NEAR/ROLE edges from Postgres and synthesizes EXACT connectivity from
``source_documents.sha256``; NO archive bind. Neo4j is OPTIONAL — used only to count
how many signed JDs have a document vector (clustering itself is over the edge graph)::

    make cluster
    make cluster CLUSTER_ARGS="--limit 500"

Writes ``docs/cluster/cluster-summary.json`` (counts + stamps), ``cluster-report.csv``
(one row per cluster, needs-eyes-first, empty ``human_verdict``) and
``cluster-members.csv``.

**Persists NOTHING and commits NOTHING** — no ``Cluster`` row is written (Phase 4 owns
that). A role cluster is recomputable from the edge graph, so re-running is free + safe.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Sequence
from pathlib import Path

from neo4j import AsyncGraphDatabase
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.jd_bank.cluster.models import ClusteringResult
from src.jd_bank.cluster.report import (
    ClusterSummary,
    build_cluster_summary,
    ordered_records,
    write_members_csv,
    write_report_csv,
    write_summary,
)
from src.jd_bank.cluster.runner import run_clustering
from src.jd_core.rules import get_rules
from src.settings import get_settings


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m src.jd_bank.cluster",
        description="Phase-3.5 role clustering: connected components over the admitted "
        "Tier-1/2/3 edge graph, plus the HR eyeball report. Report-only.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="cluster only the first N parsed_jds rows (smoke test)",
    )
    parser.add_argument(
        "--no-vectors",
        action="store_true",
        help="skip the Neo4j vector count (documents_with_vector reported as null)",
    )
    parser.add_argument(
        "--summary-out",
        type=str,
        default="/committed/cluster-summary.json",
        help="where the COMMITTED summary goes (bound to docs/cluster/); empty to skip",
    )
    parser.add_argument(
        "--report-out",
        type=str,
        default="/committed/cluster-report.csv",
        help="where the per-cluster CSV goes (bound to docs/cluster/). Empty to skip.",
    )
    parser.add_argument(
        "--members-out",
        type=str,
        default="/committed/cluster-members.csv",
        help="where the per-member CSV goes (bound to docs/cluster/). Empty to skip.",
    )
    return parser.parse_args(argv)


async def _run(args: argparse.Namespace) -> tuple[ClusteringResult, ClusterSummary]:
    settings = get_settings()
    rules = get_rules()
    engine = create_async_engine(settings.database_url)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    driver = (
        None
        if args.no_vectors
        else AsyncGraphDatabase.driver(
            settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password)
        )
    )
    try:
        async with session_maker() as session:
            result = await run_clustering(
                session, rules=rules, limit=args.limit, neo4j_driver=driver
            )
            # Report-only: no commit. Roll back to make the read-only intent explicit.
            await session.rollback()
    finally:
        if driver is not None:
            await driver.close()
        await engine.dispose()

    summary = build_cluster_summary(
        result,
        source="parsed_jds + dedup_edges (+ synthesized EXACT)",
        rules_version=rules.version,
    )
    return result, summary


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(list(sys.argv[1:] if argv is None else argv))
    result, summary = asyncio.run(_run(args))

    print(
        f"documents: {summary.documents_seen} seen -> "
        f"{summary.documents_signed} signed "
        f"({summary.documents_unsignable} unsignable, "
        f"{summary.documents_with_vector} with vector)\n"
        f"edges: {summary.edges_considered} considered "
        f"({summary.exact_synthesized} synthesized EXACT) -> "
        f"{summary.edges_admitted} admitted "
        f"(tier-excluded {summary.tier_excluded}, role<min {summary.role_below_min}, "
        f"band-vetoed {summary.band_vetoed}, group-vetoed {summary.group_vetoed})\n"
        f"clusters: {summary.cluster_count} "
        f"(largest {summary.largest_cluster}, {summary.flagged_clusters} flagged, "
        f"{summary.cross_department_clusters} cross-dept, "
        f"{summary.cross_group_clusters} cross-group) -> "
        f"coverage {summary.coverage_rate:.3f} "
        f"({summary.singletons} singletons)\n"
        f"rules_version={summary.rules_version}  "
        f"cluster_stamp={summary.cluster_stamp}",
        file=sys.stderr,
    )

    records = ordered_records(result)
    if args.summary_out:
        written = write_summary(summary, Path(args.summary_out))
        print(f"wrote {written}", file=sys.stderr)
    if args.report_out:
        written = write_report_csv(records, Path(args.report_out))
        print(f"wrote {written} ({len(records)} clusters)", file=sys.stderr)
    if args.members_out:
        written = write_members_csv(records, Path(args.members_out))
        print(f"wrote {written}", file=sys.stderr)

    return 0


if __name__ == "__main__":  # pragma: no cover - module entry point
    raise SystemExit(main())

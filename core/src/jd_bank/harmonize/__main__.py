"""``python -m src.jd_bank.harmonize`` — the Phase-4.1 harmonization measurement pass.

Docker-only (ADR-006). Needs Postgres (``parsed_jds`` at the live ``parser_version`` +
``dedup_edges`` — run ``make ingest``, ``make near-dup``, ``make dedup-role`` first). It
recomputes the role clusters in-process (reuses the 3.5 clustering), reconstructs each
member JD, EXCLUDES WJQ (CUPE), drives ``merge_cluster`` over every JDFN cluster and
measures the nine knobs. Neo4j is NOT needed (clustering is over the edge graph)::

    make harmonize-measure
    make harmonize-measure HARMONIZE_ARGS="--limit 2000"

Writes ``docs/harmonize/summary.json`` (aggregate distributions + stamps) and
``clusters.csv`` (one row per harmonized cluster).

**Persists NOTHING, commits NOTHING, picks NO knob value** — the human calibrates the
knobs from the measured distributions.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Sequence
from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.jd_bank.harmonize.report import (
    HarmonizationSummary,
    build_summary,
    write_clusters_csv,
    write_summary,
)
from src.jd_bank.harmonize.runner import run_harmonization
from src.jd_core.rules import get_rules
from src.settings import get_settings


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m src.jd_bank.harmonize",
        description="Phase-4.1 harmonization measurement: drive merge_cluster over the "
        "real JDFN role clusters and measure the 9 harmonization knobs. Report-only.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="harmonize only over the first N parsed_jds rows (smoke test)",
    )
    parser.add_argument(
        "--summary-out",
        type=str,
        default="/committed/summary.json",
        help="where the COMMITTED summary goes (bound to docs/harmonize/); '' to skip",
    )
    parser.add_argument(
        "--clusters-out",
        type=str,
        default="/committed/clusters.csv",
        help="where the per-cluster CSV goes (bound to docs/harmonize/). '' to skip.",
    )
    return parser.parse_args(argv)


async def _run(args: argparse.Namespace) -> tuple[HarmonizationSummary, int]:
    settings = get_settings()
    rules = get_rules()
    engine = create_async_engine(settings.database_url)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_maker() as session:
            result = await run_harmonization(session, rules=rules, limit=args.limit)
            # Report-only: no commit. Roll back to make the read-only intent explicit.
            await session.rollback()
    finally:
        await engine.dispose()

    summary = build_summary(
        result,
        source="parsed_jds + dedup_edges (recomputed clusters; JDFN only)",
        rules_version=rules.version,
    )
    return summary, len(result.clusters)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(list(sys.argv[1:] if argv is None else argv))
    summary, n_clusters = asyncio.run(_run(args))
    r = summary.result

    print(
        f"clusters: {r.clusters_recomputed} recomputed -> "
        f"{r.harmonized_clusters} JDFN harmonized "
        f"({r.multi_member_clusters} multi-member, {r.single_member_clusters} single)\n"
        f"WJQ excluded: {r.wjq_members_dropped} members dropped "
        f"({r.wjq_members_frequency_confirmed} frequency-confirmed), "
        f"{r.clusters_fully_wjq_excluded} clusters fully-WJQ, "
        f"{r.clusters_mixed_jdfn_wjq} mixed; "
        f"{r.member_rows_dropped_unvalidatable} member rows unvalidatable\n"
        f"flags: {dict(r.flag_counts)}\n"
        f"rules_version={summary.rules_version}  "
        f"harmonize_stamp={r.harmonize_stamp}",
        file=sys.stderr,
    )

    if args.summary_out:
        written = write_summary(summary, Path(args.summary_out))
        print(f"wrote {written}", file=sys.stderr)
    if args.clusters_out:
        written = write_clusters_csv(r.clusters, Path(args.clusters_out))
        print(f"wrote {written} ({n_clusters} clusters)", file=sys.stderr)

    return 0


if __name__ == "__main__":  # pragma: no cover - module entry point
    raise SystemExit(main())

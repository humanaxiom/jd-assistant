"""``python -m src.jd_bank.dedup.near`` — the Tier-2 near-duplicate pass (Phase 3.3).

Docker-only (ADR-006). Needs Postgres (source_documents / parsed_jds must already be
populated — run `make ingest` first) and, when the shipped archive bind is present,
re-reads the archive for ``dedup.text_source: raw_clean`` (the default). Neo4j is
needed ONLY when ``dedup.cosine_confirm_min`` is set (it ships ``null`` — see
HR-139) — this module never constructs an embed client either way::

    make near-dup
    make near-dup NEARDUP_ARGS="--limit 200"

Writes ``docs/dedup/near-dup-summary.json`` (counts, percentiles, stamps — never
document text) and ``docs/dedup/near-dup-adjudication-sample.csv`` (filenames +
scores + an empty ``human_label`` column for a real reviewer).

**Commits once, after the full reconcile.** Unlike the ingest driver's per-file batch
commits, Tier-2's reconcile needs the WHOLE plan before it can safely decide what to
prune (:mod:`.runner`'s module docstring) — committing partway through would let a
later chunk's insert/update run against a `present` snapshot the earlier chunk's own
writes had already changed, and would let a `--limit`ed early chunk prune edges a
later chunk was about to re-imply. The write statements THEMSELVES are batched (bulk
insert / bulk update / bulk delete, never one row at a time) — that is where this
module's "batch, don't do it row-by-row" discipline actually lives.

⚠ **``--limit`` IS A SMOKE TEST, NOT A RESUMABLE PARTIAL RUN.** A content's
representative is ``members[0]`` *as seen by this run*, so a limited run that reads a
non-representative member of a duplicate group plans its edge on a DIFFERENT endpoint
than a full run would — and, because the reconcile is scoped to what was read, the
full run's edge is invisible to it and is not pruned. The result is a second,
duplicate edge for the same content pair. It is harmless and SELF-HEALING (the next
full run plans the canonical endpoint, sees the stray edge as ``present - plan``, and
prunes it), and ``--limit`` exists to smoke-test the wiring, not to shard the archive
— but do not use it to build a real Tier-2 edge set piecewise.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Sequence
from pathlib import Path

from neo4j import AsyncGraphDatabase
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.jd_bank.dedup.near.models import Tier2Result
from src.jd_bank.dedup.near.report import (
    DEFAULT_ADJUDICATION_TARGET,
    NearDupSummary,
    build_near_dup_summary,
    sample_for_adjudication,
    write_adjudication_csv,
    write_summary,
)
from src.jd_bank.dedup.near.runner import run_tier2
from src.jd_bank.dedup.near.text import text_source_for
from src.jd_core.rules import get_rules
from src.settings import get_settings


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m src.jd_bank.dedup.near",
        description="Tier-2 near-duplicate dedup: MinHash-candidate, "
        "exact-Jaccard-scored, DB-reconciled.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="consider only the first N source_documents rows (smoke test)",
    )
    parser.add_argument(
        "--summary-out",
        type=str,
        default="/committed/near-dup-summary.json",
        help="where the COMMITTED summary goes (bound to docs/dedup/; default: "
        "/committed/near-dup-summary.json). Pass an empty string to skip.",
    )
    parser.add_argument(
        "--adjudication-out",
        type=str,
        default="/committed/near-dup-adjudication-sample.csv",
        help="where the COMMITTED adjudication sample goes (bound to docs/dedup/; "
        "default: /committed/near-dup-adjudication-sample.csv). Pass an empty "
        "string to skip.",
    )
    parser.add_argument(
        "--adjudication-target",
        type=int,
        default=DEFAULT_ADJUDICATION_TARGET,
        help=f"approximate adjudication sample size (default: "
        f"{DEFAULT_ADJUDICATION_TARGET})",
    )
    return parser.parse_args(argv)


async def _run(args: argparse.Namespace) -> tuple[Tier2Result, NearDupSummary]:
    settings = get_settings()
    rules = get_rules()
    engine = create_async_engine(settings.database_url)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)

    driver = None
    if rules.dedup.cosine_confirm_min is not None:
        driver = AsyncGraphDatabase.driver(
            settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password)
        )
    try:
        async with session_maker() as session:
            # ONE home for "which text source does the rulebook select" — see
            # `text.text_source_for`. Branching inline here (the first cut) left
            # HR-131's knob with no behavioural pin anywhere.
            text_source = text_source_for(rules, session)
            source_label = (
                "source_documents (raw_clean)"
                if rules.dedup.text_source == "raw_clean"
                else "parsed_jds (serialized)"
            )

            result = await run_tier2(
                session,
                rules=rules,
                text_source=text_source,
                neo4j_driver=driver,
                limit=args.limit,
            )
            await session.commit()
    finally:
        if driver is not None:
            await driver.close()
        await engine.dispose()

    summary = build_near_dup_summary(
        result, source=source_label, rules_version=rules.version
    )
    return result, summary


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(list(sys.argv[1:] if argv is None else argv))
    result, summary = asyncio.run(_run(args))

    print(
        f"documents: {summary.documents_seen} seen -> {summary.distinct_contents} "
        f"distinct contents ({summary.documents_unreadable} unreadable, "
        f"{summary.documents_below_min_shingles} below min_shingles, "
        f"{summary.documents_signed} signed, {summary.coverage_rate:.1%} coverage)\n"
        f"candidates: {summary.candidate_pairs} LSH -> {summary.qualifying_pairs} "
        f"qualifying (>= {summary.jaccard_min}), "
        f"{summary.cosine_vetoed} cosine-vetoed\n"
        f"position split (qualifying): same={summary.same_position_edges} "
        f"cross={summary.cross_position_edges} "
        f"unknown={summary.unknown_position_edges}\n"
        f"edges — written: {summary.edges_written}  updated: {summary.edges_updated}  "
        f"unchanged: {summary.edges_unchanged}  pruned: {summary.edges_pruned}\n"
        f"text_source={summary.text_source} edge_scope={summary.edge_scope} "
        f"s_curve_threshold={summary.s_curve_threshold:.3f}\n"
        f"rules_version={summary.rules_version}  dedup_stamp={summary.dedup_stamp}",
        file=sys.stderr,
    )

    if args.summary_out:
        written = write_summary(summary, Path(args.summary_out))
        print(f"wrote {written}", file=sys.stderr)

    if args.adjudication_out:
        sample = sample_for_adjudication(
            result.pairs,
            jaccard_min=summary.jaccard_min,
            target=args.adjudication_target,
        )
        written = write_adjudication_csv(sample, Path(args.adjudication_out))
        print(f"wrote {written} ({len(sample)} pairs)", file=sys.stderr)

    return 0


if __name__ == "__main__":  # pragma: no cover - module entry point
    raise SystemExit(main())

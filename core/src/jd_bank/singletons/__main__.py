"""``make singletons`` — measure the one-of-a-kind population of the live Bank (HR-223).

Read-only. Prints the buckets and writes ``docs/singletons/singleton-summary.json``, so
the numbers in the decision register can be re-derived by a person, on the box, with no
assistant in the loop::

    make singletons

⚠ Every count is scoped to the CURRENT ``PARSER_VERSION``. That is not a detail: v6→v7
recovered 805 titles in a single day, and a title-based measurement taken across that
boundary would have compared two different archives.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.jd_bank.singletons.measure import measure_singletons
from src.jd_bank.singletons.models import SingletonSummary, TitleBuckets
from src.settings import get_settings

_DEFAULT_OUT = Path("/app/docs/singletons/singleton-summary.json")


def _render(summary: SingletonSummary) -> str:
    def block(name: str, buckets: TitleBuckets) -> list[str]:
        return [
            f"  {name} ({buckets.total})",
            f"    unique title in the archive           {buckets.unique_title:>7,}",
            "    shares a title with a role's document "
            f"{buckets.shares_title_with_role_document:>7,}",
            "    shares a title with another orphan    "
            f"{buckets.shares_title_with_other_orphan:>7,}",
            "    COULD NOT EVALUATE (no usable title)  "
            f"{buckets.title_unjudgeable:>7,}",
        ]

    lines = [
        f"HR-223 — the one-of-a-kind population, at {summary.parser_version}",
        "",
        f"  parsed documents            {summary.parsed_documents:>7,}",
        f"    in a role                 {summary.documents_in_a_role:>7,}",
        f"    in no role                {summary.orphans:>7,}",
        f"  no dedup edge at all        {summary.documents_with_no_edge:>7,}",
        f"    ...and in a role anyway   {summary.documents_with_no_edge_in_a_role:>7,}"
        "   (the Builder mints roles from no documents)",
        "",
        *block("POOL — no role, no edge", summary.buckets.pool),
        "",
        *block("CONTROL — documents that reached a role", summary.buckets.control),
        "",
        f"  parsed qualifications  pool  mean {summary.mean_qualifications_pool}"
        f" · median {summary.median_qualifications_pool}",
        f"                      in-role  mean {summary.mean_qualifications_in_role}"
        f" · median {summary.median_qualifications_in_role}",
        "  ⚠ not a forecast of published JDs — a minted role still faces every gate.",
    ]
    if summary.unique_title_examples:
        lines += ["", "  unique titles (sample, verbatim):"]
        lines += [f"    · {t}" for t in summary.unique_title_examples]
    return "\n".join(lines)


async def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        type=Path,
        default=_DEFAULT_OUT,
        help="where to write the JSON summary (default: %(default)s)",
    )
    parser.add_argument(
        "--examples",
        type=int,
        default=12,
        help=(
            "how many unique titles to print verbatim, sampled at an even stride "
            "across the sorted list (default: %(default)s)"
        ),
    )
    args = parser.parse_args(argv)

    engine = create_async_engine(get_settings().database_url)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            summary = await measure_singletons(session, examples=args.examples)
    finally:
        await engine.dispose()

    print(_render(summary), flush=True)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(summary.model_dump(mode="json"), indent=2) + "\n", encoding="utf-8"
    )
    print(f"\n✅ written to {args.out}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

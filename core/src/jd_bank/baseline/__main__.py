"""``python -m src.jd_bank.baseline`` — run the Phase 2.5 archive baseline.

Docker-only (ADR-006). The archive lives OUTSIDE the repo and is READ-ONLY, so the
``baseline`` compose service binds it at ``/archive:ro`` and an output dir at ``/out``::

    make baseline JD_ARCHIVE_PATH=/path/to/SFU_JDs
    make baseline JD_ARCHIVE_PATH=/path/to/SFU_JDs BASELINE_ARGS="--sample 30"

Writes three artifacts to ``--out``, all stamped with the ``rules_version`` that scored
them, the parser version that read them, and the segmentation stamp that says which
population they describe:

``rows.jsonl``     one line per file — scored or skipped. **Every** file, so the
                   "no silent drops" guarantee is checkable with ``wc -l``.
``errors.jsonl``   the skipped subset, for triage.
``summary.json``   the segmented dashboard data: score + grade distributions, per-rule
                   and per-gate frequency, and the approval rate — each broken down by
                   format, by era, and by dedup population.

It measures. It does not conclude: the read of these numbers ("does the archive ratify
the bar, or kill it?") is a separate, human step.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from src.jd_bank.baseline.aggregate import summarise
from src.jd_bank.baseline.config import get_baseline_config
from src.jd_bank.baseline.models import BaselineRow
from src.jd_bank.baseline.runner import run_baseline, write_artifacts
from src.jd_core.rules import get_rules

#: Files between progress lines. The full run is ~8-9 minutes; silence for that long is
#: indistinguishable from a hang.
_PROGRESS_EVERY: int = 250


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m src.jd_bank.baseline",
        description="Run the SFU JD validator + gate runner across the archive.",
    )
    parser.add_argument(
        "--archive",
        type=Path,
        default=Path("/archive"),
        help="archive root (read-only bind; default: /archive)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("/out"),
        help="working output directory, gitignored — gets all three artifacts "
        "(default: /out)",
    )
    parser.add_argument(
        "--commit-to",
        type=Path,
        default=Path("/committed"),
        help="where the COMMITTED audit trail goes: summary.json + errors.jsonl "
        "(bound to docs/baseline/; default: /committed). Pass an empty string to skip.",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--limit",
        type=int,
        help="score only the first N files of the sorted walk (smoke test)",
    )
    group.add_argument(
        "--sample",
        type=int,
        help="score N files spread EVENLY across the sorted walk. The archive sorts by "
        "its YYYYMMDD filename prefix, so this spans eras and formats — and it is "
        "deterministic, so the sample can be re-run and quoted.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(list(sys.argv[1:] if argv is None else argv))
    config = get_baseline_config()
    rules = get_rules()

    print(
        f"rules_version={rules.version}  segmentation={config.stamp}\n"
        f"archive={args.archive}  out={args.out}",
        file=sys.stderr,
    )

    rows: list[BaselineRow] = []
    try:
        for row in run_baseline(
            args.archive,
            config=config,
            rules=rules,
            limit=args.limit,
            sample=args.sample,
        ):
            rows.append(row)
            if len(rows) % _PROGRESS_EVERY == 0:
                print(f"  ... {len(rows)} files", file=sys.stderr)
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except ValueError as exc:  # a non-positive --limit/--sample
        print(f"error: {exc}", file=sys.stderr)
        return 2

    summary = summarise(rows, archive_root=str(args.archive), config=config)
    written = write_artifacts(
        args.out,
        rows=rows,
        summary=summary,
        commit_dir=args.commit_to if str(args.commit_to) else None,
    )

    overall = next(
        segment
        for segment in summary.segments
        if (segment.population, segment.dimension) == ("all", "all")
    )
    print(
        f"\n{summary.file_count} files: {summary.scored} scored, "
        f"{summary.skipped} skipped (all accounted for).",
        file=sys.stderr,
    )
    if overall.approval_rate is not None:
        print(
            f"approval rate (all files, current bar): {overall.approval_rate:.1%} "
            f"— SEGMENTED numbers are in summary.json; the blended one is a category "
            f"error on its own.",
            file=sys.stderr,
        )
    for path in written:
        print(f"wrote {path}", file=sys.stderr)
    return 0


if __name__ == "__main__":  # pragma: no cover - module entry point
    raise SystemExit(main())

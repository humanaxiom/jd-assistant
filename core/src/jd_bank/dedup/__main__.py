"""``python -m src.jd_bank.dedup`` — the Tier-1 exact-duplicate report.

Docker-only (ADR-006), and it does **not** walk the archive: it reads the Phase 2.5
baseline's ``rows.jsonl``, which already carries a ``sha256`` for every one of the
14,565 files, and groups it with the *same* code the database pass uses. HANDOFF: "do
not hand-roll a second path."

    make baseline JD_ARCHIVE_PATH=/path/to/SFU_JDs     # produces rows.jsonl
    make dedup                                         # reads it

Writes:

``/out/dedup-groups.jsonl``   every group, every member filename — the raw evidence,
                              gitignored (a bulk index of a read-only corpus).
``/committed/summary.json``   the counts, the size distribution, the biggest groups,
                              and what each edge topology would cost — committed to
                              ``docs/dedup/``, because an audit trail that only exists
                              in an ignored directory is not an audit trail.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from src.jd_bank.dedup.report import (
    build_dedup_report,
    positions_from_baseline_rows,
    read_baseline_rows,
    refs_from_baseline_rows,
    write_groups,
    write_report,
)
from src.jd_core.rules import get_rules


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m src.jd_bank.dedup",
        description="Tier-1 exact-duplicate finding over the archive baseline's rows.",
    )
    parser.add_argument(
        "--rows",
        type=Path,
        default=Path("/out/rows.jsonl"),
        help="the baseline's row dump (default: /out/rows.jsonl)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("/out"),
        help="working output dir, gitignored — gets the raw group dump (default: /out)",
    )
    parser.add_argument(
        "--commit-to",
        type=Path,
        default=Path("/committed"),
        help="where the COMMITTED summary goes (bound to docs/dedup/; "
        "default: /committed). Pass an empty string to skip.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(list(sys.argv[1:] if argv is None else argv))
    rules = get_rules()

    try:
        rows = read_baseline_rows(args.rows)
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    refs = refs_from_baseline_rows(rows)
    byte_sizes = {
        row.sha256: row.byte_size
        for row in rows
        if row.sha256 and row.byte_size is not None
    }
    report = build_dedup_report(
        refs,
        source=str(args.rows),
        rules=rules,
        byte_sizes=byte_sizes,
        positions=positions_from_baseline_rows(rows),
    )

    written = [write_groups(refs, args.out / "dedup-groups.jsonl")]
    if str(args.commit_to):
        written.append(write_report(report, args.commit_to / "summary.json"))

    print(
        f"rules_version={report.rules_version}  topology={report.topology}\n"
        f"{report.total_documents} documents ({report.hashed} hashed, "
        f"{report.unhashed} unhashed) -> {report.distinct_sha256} distinct contents\n"
        f"{report.group_count} duplicate groups holding {report.files_in_groups} "
        f"files; {report.redundant_files} are redundant copies "
        f"({report.redundancy_rate:.1%} of hashed files)\n"
        f"largest group: {report.largest_group_size} files\n"
        f"groups spanning >1 position: "
        f"{report.groups_spanning_multiple_positions} "
        f"({report.files_in_multi_position_groups} files) · "
        f"re-saves of one position: {report.groups_within_one_position} · "
        f"no position id: {report.groups_without_position_id}\n"
        f"edges — star: {report.edges_star}  clique: {report.edges_clique}  "
        f"(live: {report.edges_at_topology})",
        file=sys.stderr,
    )
    for path in written:
        print(f"wrote {path}", file=sys.stderr)
    return 0


if __name__ == "__main__":  # pragma: no cover - module entry point
    raise SystemExit(main())

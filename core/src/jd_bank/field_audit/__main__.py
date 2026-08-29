"""``make field-audit`` — P3b, the identification fields against the raw archive.

Read-only: it opens the archive and reads Postgres, and writes no Bank row::

    make field-audit JD_ARCHIVE_PATH=<SFU JDs>
    make field-audit JD_ARCHIVE_PATH=<SFU JDs> FIELD_AUDIT_ARGS="--sample 500"

⚠ ``--sample`` spreads evenly across the archive's date-sorted walk, so it spans eras
and formats by construction. It is stamped into the summary: a sample of the newest
files is not a sample of the corpus, and a report that forgets which it was is worse
than none.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.jd_bank.field_audit.audit import run_field_audit
from src.jd_bank.field_audit.models import FieldAuditSummary
from src.jd_core.rules import get_rules
from src.settings import get_settings

_DEFAULT_OUT = Path("/app/docs/field-audit/field-audit.json")


def _render(summary: FieldAuditSummary) -> str:
    scope = (
        f"sample of {summary.sampled}"
        if summary.sampled is not None
        else "the WHOLE archive"
    )
    lines = [
        f"P3b — identification fields vs the raw archive ({scope}), "
        f"at {summary.parser_version}",
        f"  documents read {summary.documents_read:,}   "
        "skipped (unreadable or not parsed at this version) "
        f"{summary.documents_skipped:,}",
        "",
        "  per group: parser_has / READABLE / 🔴 UNREADABLE / blank / no-label",
    ]
    for group, audit in summary.by_group.items():
        lines.append(f"\n  ── {group}  ({audit.documents:,} documents)")
        for field, outcome in audit.fields.items():
            flag = " 🔴" if outcome.unreadable_with_value else "   "
            lines.append(
                f"    {field:<16} {outcome.parser_has_value:>6,} "
                f"{outcome.readable_with_value:>7,} "
                f"{outcome.unreadable_with_value:>8,}{flag} "
                f"{outcome.label_present_no_value:>7,} {outcome.no_label_found:>8,}"
            )
    if any(summary.unreadable_examples.values()):
        lines += ["", "  UNREADABLE field names in the archive (verbatim):"]
        for field, examples in summary.unreadable_examples.items():
            for name, count in examples:
                lines.append(f"    {field:<16} {count:>6,}  {name!r}")
    if summary.gap_examples:
        lines += [
            "",
            "  🔴 THE GAP, file by file — the archive states it, the Bank does not:",
        ]
        for ex in summary.gap_examples:
            lines.append(
                f"    {ex.employee_group:<6} {ex.field:<14} {ex.filename[:44]:<44} "
                f"{ex.field_name!r} -> {ex.document_value[:50]!r}"
            )
    lines += ["", "  ⚠ NOT evaluated by this probe:"]
    for field, why in summary.not_evaluated.items():
        lines.append(f"    {field}: {' '.join(why.split())[:150]}…")
    return "\n".join(lines)


async def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, default=Path("/archive"))
    parser.add_argument("--out", type=Path, default=_DEFAULT_OUT)
    parser.add_argument(
        "--sample",
        type=int,
        default=None,
        help="audit N files spread evenly across the archive (default: all of it)",
    )
    parser.add_argument(
        "--evidence",
        type=int,
        default=0,
        help=(
            "print up to N documents where the archive states a READABLE value and the "
            "parser stored none — the gap, file by file (default: %(default)s)"
        ),
    )
    args = parser.parse_args(argv)

    engine = create_async_engine(get_settings().database_url)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            summary = await run_field_audit(
                session,
                args.archive,
                rules=get_rules(),
                sample=args.sample,
                evidence=args.evidence,
            )
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

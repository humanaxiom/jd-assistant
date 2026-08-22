"""``make bank-audit`` — what the live Bank actually contains, per form.

Read-only. Prints a carry-through report to stdout and, unless told otherwise, writes
the same thing as JSON so two runs can be diffed. Nothing here writes a Bank row.

    make bank-audit                       # the report
    make bank-audit AUDIT_ARGS="--json"   # machine-readable, for a diff

**Exit code is a verdict, not just a status.** ``2`` when any section's carry-through is
below ``--min-retention`` (default 100 — the only defensible target, since anything less
is content the archive stated and the Bank dropped). So this can gate a pipeline instead
of being read by someone who already suspects a problem.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.jd_bank.bank_audit.metrics import audit_bank
from src.jd_bank.bank_audit.models import BankAudit, FormAudit
from src.settings import get_settings


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m src.jd_bank.bank_audit",
        description="Audit the live Bank's content carry-through, per form.",
    )
    parser.add_argument(
        "--json", action="store_true", help="print the report as JSON instead of text"
    )
    parser.add_argument(
        "--out",
        default="/committed/bank-audit.json",
        help="where the JSON report goes ('' to skip); two of these diff cleanly",
    )
    parser.add_argument(
        "--min-retention",
        type=float,
        default=100.0,
        help="exit 2 if any section's carry-through falls below this percentage "
        "(default 100 — anything less is content the archive stated and we dropped)",
    )
    return parser.parse_args(list(argv))


def _render_form(form: FormAudit) -> list[str]:
    out = [
        f"\n── {form.template.upper()} ── {form.drafts} drafts · "
        f"mean score {form.mean_score} · {form.approvable} approvable · "
        f"mean {form.mean_duties} duties",
    ]
    if not form.drafts:
        return [*out, "   (no drafts on this form)"]

    out.append("   CARRY-THROUGH  (sources offered -> drafts keeping it)")
    for c in form.carry_through:
        flag = "🔴" if (c.is_shortfall or c.is_fabrication) else "  "
        if c.is_fabrication:
            # ABOVE 100%: more drafts carry it than had a source offering it. A draft
            # can only carry what its sources stated, so this is invented content.
            reading = (
                f"{c.retention_pct:>5}%  ⚠ FABRICATED — "
                f"{c.kept - c.offered} drafts carry it with no source"
            )
        elif not c.offered:
            # Nothing was offered, so nothing could be kept. Rendering that as "0.0%"
            # invented a failure on the audit's first run: no CUPE source document
            # states Problem Solving, which is a fact about the WJQ form, not a loss.
            reading = "     n/a  (no source states it)"
        elif c.policy == "drop":
            reading = f"{c.retention_pct:>5}%  (policy: drop — expected)"
        else:
            reading = f"{c.retention_pct:>5}%"
        out.append(
            f"   {flag} {c.section:<22} {c.kept:>5} / {c.offered:<5} = {reading}"
        )

    r = form.rewrite
    out.append("   REWRITE")
    out.append(
        f"      duty frequency kept — rewritten {r.rewritten_frequency_pct}% "
        f"({r.rewritten_with_frequency}/{r.rewritten_duties})"
    )
    # The control group. Printed on the same line pair on purpose: the two numbers are
    # only meaningful next to each other.
    control = (
        f"      duty frequency kept — merge-only (control) "
        f"{r.merge_only_frequency_pct}% "
        f"({r.merge_only_with_frequency}/{r.merge_only_duties})"
    )
    if r.merge_only_duties and r.merge_only_frequency_pct > r.rewritten_frequency_pct:
        control += "   🔴 the rewrite is destroying a field the merge preserves"
    out.append(control)
    out.append(
        f"      duties flagged {r.flagged_duty_pct}% "
        f"({r.duties_flagged}/{r.duties_total}) · drafts with any flag "
        f"{r.drafts_flagged_pct}%"
        + (
            "   🔴 a flag on nearly every draft is a constant, not a signal"
            if r.drafts_flagged_pct >= 90.0
            else ""
        )
    )

    if form.blocking_gates:
        out.append("   TOP BLOCKING GATES")
        for g in form.blocking_gates:
            out.append(f"      {g.gate_id:<34} {g.drafts}")
    return out


def _render(audit: BankAudit) -> str:
    lines = [
        "JD BANK — CONTENT AUDIT  (read-only; per form, never blended)",
        f"{audit.documents_parsed} documents parsed · {audit.published} published",
    ]
    for form in audit.forms:
        lines.extend(_render_form(form))
    return "\n".join(lines)


def _shortfalls(audit: BankAudit, minimum: float) -> list[str]:
    return [
        f"{form.template}/{c.section} at {c.retention_pct}%"
        for form in audit.forms
        for c in form.carry_through
        if c.is_shortfall and c.retention_pct < minimum
    ]


def _fabrications(audit: BankAudit) -> list[str]:
    """Sections where the Bank holds more than its sources offered — invented content.
    Always a verdict, at any `--min-retention`: there is no threshold at which making
    content up is acceptable."""
    return [
        f"{form.template}/{c.section} FABRICATED ({c.kept}/{c.offered})"
        for form in audit.forms
        for c in form.carry_through
        if c.is_fabrication
    ]


async def _run() -> BankAudit:
    engine = create_async_engine(get_settings().database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with maker() as session:
            return await audit_bank(session)
    finally:
        await engine.dispose()


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    audit = asyncio.run(_run())

    payload = audit.model_dump(mode="json")
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(_render(audit))

    if args.out:
        path = Path(args.out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        if not args.json:
            print(f"\nwrote {path}")

    shortfalls = _shortfalls(audit, args.min_retention) + _fabrications(audit)
    if shortfalls:
        print(
            "\n🔴 CARRY-THROUGH BELOW "
            f"{args.min_retention}%: {', '.join(shortfalls)}",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry
    raise SystemExit(main())

"""``python -m src.jd_bank.canonical`` — the Phase-4.4a canonical-draft PRODUCER.

Docker-only (ADR-006). WRITES to Postgres (``clusters`` / ``canonical_jds`` / audit_log)
— run ``make up``, ``make migrate``, then ``make ingest``, ``make near-dup``,
``make dedup-role`` first (it recomputes clusters in-process from ``dedup_edges``). No
Neo4j needed (clustering is over the edge graph). The full pipeline (with the 4.2a
rewrite + 4.2b audit) needs a reachable Ollama on ``aria-gb10-2`` (ADR-003) — so the
real run is **local-only**::

    make canonical-drafts                               # full pipeline (needs Ollama)
    make canonical-drafts CANONICAL_ARGS="--no-llm"     # deterministic-only (no Ollama)
    make canonical-drafts CANONICAL_ARGS="--limit 500"

``--no-llm`` persists the deterministic 4.1 merge draft only (the rewrite/audit are
recorded as skipped) and needs no model endpoint — the path ``make gates`` exercises via
a content-keyed fake, run here for real without Ollama.

Writes ``docs/canonical/summary.json`` (COUNTS + STAMPS only — never JD text, never a
member-id list that could reconstruct prose; that lives in the persisted rows).

**Nothing is published or approved** (non-negotiable #1): every row is a DRAFT a human
still has to approve.

⚠ SINGLE INJECTED CLIENT: the producer takes one ``ChatClient`` and passes it to BOTH
the 4.2a rewrite and the 4.2b audit, so this entrypoint binds it to the rewrite model.
If the audit must run under its own ``rules.quality.model`` (the two are separate
rulebook decisions — see ``llm/client.py``), that is a follow-up: split the producer's
``client`` into ``rewrite_client`` / ``audit_client``. Recorded, not silently carried.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.jd_bank.canonical.models import CanonicalProducerResult
from src.jd_bank.canonical.runner import run_canonical_producer
from src.jd_bank.llm.client import ChatClient
from src.jd_core.rules import get_rules
from src.settings import get_settings


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m src.jd_bank.canonical",
        description="Phase-4.4a canonical-draft producer: drive the Phase-4 pipeline "
        "over the JDFN clusters and persist DRAFT canonical_jds. Idempotent; never "
        "clobbers a reviewer-touched canonical; nothing publishes.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="produce over only the first N parsed_jds rows (smoke test)",
    )
    parser.add_argument(
        "--no-llm",
        action="store_true",
        help="deterministic-only: persist the 4.1 merge draft, no Ollama call",
    )
    parser.add_argument(
        "--summary-out",
        type=str,
        default="/committed/summary.json",
        help="where the COMMITTED summary goes (bound to docs/canonical/); '' to skip",
    )
    return parser.parse_args(argv)


def _write_summary(result: CanonicalProducerResult, *, path: Path, source: str) -> Path:
    """Write the counts-only summary (no JD text). Mirrors the other runners'
    ``summary.json`` — the persisted rows carry the prose, this carries the tally."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "source": source,
        "generated_at": dt.datetime.now(dt.UTC).isoformat(),
        "result": result.model_dump(mode="json"),
    }
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return path


async def _run(args: argparse.Namespace) -> CanonicalProducerResult:
    settings = get_settings()
    rules = get_rules()
    engine = create_async_engine(settings.database_url)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    client = None if args.no_llm else ChatClient(rules=rules)
    try:
        async with session_maker() as session:
            result = await run_canonical_producer(
                session, client=client, rules=rules, limit=args.limit
            )
            # The producer does not commit — the caller owns it. Persist the run.
            await session.commit()
    finally:
        if client is not None:
            await client.close()
        await engine.dispose()
    return result


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(list(sys.argv[1:] if argv is None else argv))
    result = asyncio.run(_run(args))

    print(
        f"clusters: {result.clusters_recomputed} recomputed -> "
        f"{result.clusters_seen} JDFN seen "
        f"({result.multi_member_clusters} multi, "
        f"{result.single_member_clusters} single)\n"
        f"drafts: {result.drafts_persisted} persisted, "
        f"{result.drafts_refreshed} refreshed, "
        f"{result.skipped_reviewer_touched} skipped (reviewer-touched), "
        f"{result.cluster_failures} cluster failures\n"
        f"LLM: enabled={result.llm_enabled}, "
        f"{result.rewrite_failures} rewrite failures, "
        f"{result.audit_failures} audit failures\n"
        f"WJQ excluded: {result.wjq_members_excluded} members "
        f"({result.wjq_members_frequency_confirmed} frequency-confirmed), "
        f"{result.clusters_fully_wjq_excluded} clusters fully-WJQ, "
        f"{result.clusters_mixed_jdfn_wjq} mixed\n"
        f"rules_version={result.rules_version}  llm_enabled={result.llm_enabled}",
        file=sys.stderr,
    )

    if args.summary_out:
        written = _write_summary(
            result,
            path=Path(args.summary_out),
            source="parsed_jds + dedup_edges (recomputed clusters; JDFN only)",
        )
        print(f"wrote {written}", file=sys.stderr)

    return 0


if __name__ == "__main__":  # pragma: no cover - module entry point
    raise SystemExit(main())

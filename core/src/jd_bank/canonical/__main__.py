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

TWO INJECTED CLIENTS: the producer takes a ``rewrite_client`` and an ``audit_client``,
each bound to its OWN rulebook model — the 4.2a rewrite to ``rules.rewrite.model`` and
the 4.2b audit to ``rules.quality.model`` (separate rulebook decisions — see
``llm/client.py``). :func:`_build_clients` binds them so that when ``quality.yaml`` is
retuned the audit actually runs under the quality model and ``QualityAudit.model``
cannot become a provenance lie (NN #6). ``--no-llm`` -> both are ``None``.
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
from src.jd_core.rules import Rules, get_rules
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
        "--commit-every",
        type=int,
        default=25,
        help="commit every N processed clusters (crash-safety on a long LLM run) and "
        "print a progress line to stderr at the same cadence; 0 disables (single final "
        "commit only). The final commit is always the backstop for the remainder.",
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


def _build_clients(
    rules: Rules, *, no_llm: bool
) -> tuple[ChatClient | None, ChatClient | None]:
    """The ``(rewrite_client, audit_client)`` pair, each bound to its own model.

    The rewrite client falls back to ``rules.rewrite.model`` /
    ``.temperature`` / ``.reasoning_effort`` (HR-176 / HR-177 / HR-191 — the
    ``ChatClient`` default, the last ``null``/unset); the audit client is bound
    EXPLICITLY to ``rules.quality.model`` / ``.temperature`` / ``.reasoning_effort``
    (HR-185 / HR-186 / HR-192 — the last ``low``) so both the ``QualityAudit.model``
    stamp and the audit's cheaper reasoning cannot silently follow the rewrite once the
    two YAMLs diverge (NN #6).
    ``--no-llm`` -> ``(None, None)``: the deterministic-only path, no Ollama needed.
    """
    if no_llm:
        return None, None
    rewrite_client = ChatClient(rules=rules)
    audit_client = ChatClient(
        rules=rules,
        model=rules.quality.model,
        temperature=rules.quality.temperature,
        reasoning_effort=rules.quality.reasoning_effort,
    )
    return rewrite_client, audit_client


async def _run(args: argparse.Namespace) -> CanonicalProducerResult:
    settings = get_settings()
    rules = get_rules()
    engine = create_async_engine(settings.database_url)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)
    rewrite_client, audit_client = _build_clients(rules, no_llm=args.no_llm)
    # 0 (or a negative) disables incremental commit -> a single final commit only.
    commit_every = (
        args.commit_every if args.commit_every and args.commit_every > 0 else None
    )
    try:
        async with session_maker() as session:
            result = await run_canonical_producer(
                session,
                rewrite_client=rewrite_client,
                audit_client=audit_client,
                rules=rules,
                limit=args.limit,
                commit_every=commit_every,
                progress_every=commit_every,
            )
            # The producer may checkpoint-commit between clusters (``--commit-every``);
            # this final commit is the backstop for the remainder after the last one.
            await session.commit()
    finally:
        for client in (rewrite_client, audit_client):
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

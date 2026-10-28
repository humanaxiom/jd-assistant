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
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.jd_bank.canonical.models import CanonicalProducerResult
from src.jd_bank.canonical.runner import (
    UnknownClusterIdsError,
    run_canonical_producer,
)
from src.jd_bank.llm.client import ChatClient
from src.jd_core.rules import Rules, get_rules
from src.settings import get_settings


def _utc_timestamp(value: str) -> dt.datetime:
    """An ISO-8601 instant, normalised to UTC — the ``--refreshed-since`` cutoff.

    A NAIVE value is rejected rather than assumed: this flag decides which clusters a
    multi-hour, GPU-priced pass re-does, and reading "04:04:58" as local time on a box
    whose Postgres records UTC is how a resume skips the wrong half of the corpus and
    reports success.
    """
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = dt.datetime.fromisoformat(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"{value!r} is not an ISO-8601 instant (e.g. 2026-09-11T04:04:58Z)"
        ) from exc
    if parsed.tzinfo is None:
        raise argparse.ArgumentTypeError(
            f"{value!r} has no timezone. Say it explicitly — 'Z' for UTC, which is "
            f"what the Bank's timestamps are in (e.g. 2026-09-11T04:04:58Z)."
        )
    return parsed.astimezone(dt.UTC)


#: Where the `canonical` compose service can see a file a person wrote on the host.
#: Kept beside the parser so the refusal below and docker-compose.yml cannot disagree
#: silently: `./docs/canonical` is bound at `/committed`, `./core` at `/app` (the cwd).
#: The COMMITTED record of the last full pass (bound to docs/canonical/).
_DEFAULT_SUMMARY_OUT = "/committed/summary.json"
#: Where a `--cluster-ids` run's summary goes when `--summary-out` is not given. Never
#: the full-pass file: a five-cluster tally written over it (review of bd0e0be) would
#: replace the committed record of a 2,446-cluster pass with a scoped one that does not
#: say it is scoped, and the next commit of docs/canonical/ would carry it.
_SCOPED_SUMMARY_OUT = "/committed/summary-cluster-ids.json"

_CONTAINER_MOUNTS_HINT = (
    "the producer runs inside the `canonical` container, which sees only "
    "docs/canonical/ (as /committed/) and core/ (as /app/, the working directory) — "
    "put the file in docs/canonical/ and pass /committed/<name>"
)


def _uuids(tokens: Sequence[str], *, where: str) -> frozenset[UUID]:
    """Parse cluster-id tokens, refusing a malformed one rather than dropping it."""
    ids: set[UUID] = set()
    for token in tokens:
        try:
            ids.add(UUID(token))
        except ValueError as exc:
            raise argparse.ArgumentTypeError(
                f"{token!r} ({where}) is not a cluster UUID"
            ) from exc
    if not ids:
        raise argparse.ArgumentTypeError(
            f"no cluster ids given ({where}) — refusing a run that would process "
            f"nothing and report success"
        )
    return frozenset(ids)


def _cluster_id_list(value: str) -> frozenset[UUID]:
    """``--cluster-ids a,b,c`` — comma-separated; surrounding blanks ignored, a blank
    ENTRY (``a,,b``) refused, because it is almost always a lost id."""
    tokens = [token.strip() for token in value.split(",")]
    if value.strip() and any(not token for token in tokens):
        raise argparse.ArgumentTypeError(
            f"{value!r} has an empty entry — an id seems to be missing"
        )
    return _uuids([t for t in tokens if t], where="--cluster-ids")


def _cluster_id_file(value: str) -> frozenset[UUID]:
    """``--cluster-ids-file PATH`` — ONE UUID per line. Blank lines and ``#`` comment
    lines are allowed (a re-run list deserves a note on why each id is in it); anything
    else that is not a single UUID is refused BY LINE NUMBER, never skipped."""
    path = Path(value)
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise argparse.ArgumentTypeError(
            f"cannot read {value!r} ({exc.strerror or exc}); {_CONTAINER_MOUNTS_HINT}"
        ) from exc
    tokens: list[str] = []
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        try:
            UUID(line)
        except ValueError as exc:
            raise argparse.ArgumentTypeError(
                f"{value}: line {number} is not one cluster UUID: {line!r}"
            ) from exc
        tokens.append(line)
    return _uuids(tokens, where=f"--cluster-ids-file {value}")


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
        "--allow-downgrade",
        action="store_true",
        help="let a --no-llm run OVERWRITE drafts the full pipeline wrote (default: it "
        "leaves them alone and counts them). Only pass this to deliberately "
        "re-baseline the Bank deterministically — it discards every row's rewrite.",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="skip clusters whose draft already HOLDS a landed rewrite — the resume "
        "for an interrupted LLM pass. A complete pass over this archive measures ~44 "
        "hours, so without it an interruption anywhere means paying for every cluster "
        "again. Same property `make embed` has had since Phase 3.2. A cluster whose "
        "rewrite FAILED holds only the deterministic merge, so a resume retries it.",
    )
    parser.add_argument(
        "--refreshed-since",
        type=_utc_timestamp,
        default=None,
        metavar="ISO8601",
        help="RESUME A RE-BASELINE: skip clusters whose draft was last refreshed AT OR "
        "AFTER this moment, and process everything else. Use the time the CURRENT "
        "baseline began, e.g. 2026-09-11T04:04:58Z. ⚠ `--resume` CANNOT do this: it "
        "skips on 'does the row hold prose', which is true of every row a re-baseline "
        "exists to replace — measured 2026-09-12, it would have processed 9 of the "
        "1,048 clusters still owing work and skipped 1,039, exiting green. No stamp "
        "substitutes, because a re-baseline triggered by a CODE fix leaves "
        "rules_version/prompt_version identical on both sides; time is the only honest "
        "discriminator, so the operator states it.",
    )
    parser.add_argument(
        "--only-template",
        choices=["jdfn", "wjq"],
        default=None,
        help="process ONLY the clusters the rulebook would author on this form, "
        "leaving every other cluster untouched — no row written, no model call paid "
        "for. Operational scoping for ONE run: repairing the CUPE cohort otherwise "
        "costs a full pass (649 clusters of work inside 2,493 clusters of cost, ~44 "
        "hours). It does NOT change which form a cluster authors on — that is "
        "harmonization.templates_harmonized, an HR-registered decision.",
    )
    parser.add_argument(
        "--only-undrafted",
        action="store_true",
        help="process ONLY clusters that have NO canonical row at all — draft what has "
        "no draft. Operational scoping in the same class as --only-template: it "
        "changes no rulebook decision. Written because the P1 repair left 24 clusters "
        "un-drafted and regenerating exactly those otherwise cost a full pass over "
        "2,493 clusters (~44 hours) to do minutes of work. Idempotent: a second run "
        "over a fully-drafted Bank writes nothing and pays for no model call.",
    )
    named = parser.add_mutually_exclusive_group()
    named.add_argument(
        "--cluster-ids",
        dest="cluster_ids",
        type=_cluster_id_list,
        default=None,
        metavar="ID,ID,...",
        help="process ONLY these clusters (comma-separated cluster UUIDs, as in "
        "clusters.id / canonical_jds.cluster_id) — re-run a handful after a fix lands "
        "instead of paying for a full pass. Operational scoping, like --only-template: "
        "a named cluster still goes through the reviewer-touched skip and the "
        "no-downgrade guard exactly as in a full run. An id the recomputed clustering "
        "does not contain REFUSES the run (exit 2, every such id listed) before "
        "anything is written. Combines with --no-llm / --allow-downgrade; refused with "
        "--resume, --limit, --refreshed-since, --only-template, --only-undrafted.",
    )
    named.add_argument(
        "--cluster-ids-file",
        dest="cluster_ids",
        type=_cluster_id_file,
        metavar="PATH",
        help="as --cluster-ids, read from a file: ONE UUID per line; blank lines and "
        "'#' comments allowed. The path is INSIDE the container: put the file in "
        "docs/canonical/ on the host and pass /committed/<name>.",
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
        default=None,
        help="where the COMMITTED summary goes (bound to docs/canonical/); '' to skip. "
        "Default /committed/summary.json — or, for --cluster-ids/--cluster-ids-file, "
        "/committed/summary-cluster-ids.json, so a scoped re-run never overwrites the "
        "full-pass record.",
    )
    return parser.parse_args(argv)


def _write_summary(
    result: CanonicalProducerResult,
    *,
    path: Path,
    source: str,
    scope: dict[str, Any] | None = None,
) -> Path:
    """Write the counts-only summary (no JD text). Mirrors the other runners'
    ``summary.json`` — the persisted rows carry the prose, this carries the tally.
    ``scope`` (a named run's cluster ids) is recorded IN the file, so a scoped tally can
    never be read back as a full pass; a full run's payload is unchanged."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "source": source,
        "generated_at": dt.datetime.now(dt.UTC).isoformat(),
        "result": result.model_dump(mode="json"),
    }
    if scope is not None:
        payload["scope"] = scope
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
                allow_downgrade=args.allow_downgrade,
                skip_llm_written=args.resume,
                skip_refreshed_since=args.refreshed_since,
                only_template=args.only_template,
                only_undrafted=args.only_undrafted,
                only_cluster_ids=args.cluster_ids,
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


def _reject_contradictory_flags(args: argparse.Namespace) -> str | None:
    """The message for a flag combination that cannot be honoured, or ``None``.

    🔴 ``--resume --allow-downgrade`` WAS A SILENT NO-OP that exited 0. The two flags
    ask for opposite things about the same rows: ``--resume`` says "skip every cluster
    that already holds a landed rewrite", and ``--allow-downgrade`` exists ONLY to let a
    cheap run overwrite exactly those clusters. Resume is tested first, so it won every
    time — the deliberate re-baseline never happened, and the run reported success.

    An operator reaching for ``--allow-downgrade`` is doing something destructive on
    purpose (it discards a ~44-hour pass) and is the last person who should have to
    infer from a summary that it did not happen. Refusing is the only honest answer:
    picking a winner would mean guessing which half of a contradiction was meant.
    """
    if args.resume and args.allow_downgrade:
        return (
            "--resume and --allow-downgrade contradict each other: --resume SKIPS the "
            "clusters holding a landed rewrite, which are the only clusters "
            "--allow-downgrade exists to overwrite. Resume is evaluated first, so this "
            "combination silently did nothing and exited 0. Drop --resume to "
            "re-baseline, or drop --allow-downgrade to continue an interrupted pass."
        )
    if args.cluster_ids is not None:
        # Every other scope would quietly NOT run some of the clusters a person named:
        # --limit shrinks the clustering so named ids go unknown; --resume and
        # --refreshed-since skip named clusters that already hold work; --only-template
        # and --only-undrafted count them out of scope. Naming a cluster and then not
        # running it is the exact outcome --cluster-ids exists to make impossible.
        clashing = [
            flag
            for flag, given in (
                ("--resume", args.resume),
                ("--limit", args.limit is not None),
                ("--refreshed-since", args.refreshed_since is not None),
                ("--only-template", args.only_template is not None),
                ("--only-undrafted", args.only_undrafted),
            )
            if given
        ]
        if clashing:
            return (
                f"--cluster-ids/--cluster-ids-file cannot be combined with "
                f"{', '.join(clashing)}: each would silently leave some NAMED clusters "
                f"un-run. Name exactly the clusters to re-run and drop the other "
                f"scope (--no-llm and --allow-downgrade do combine)."
            )
    return None


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(list(sys.argv[1:] if argv is None else argv))
    contradiction = _reject_contradictory_flags(args)
    if contradiction is not None:
        print(f"❌ {contradiction}", file=sys.stderr)
        return 2
    try:
        result = asyncio.run(_run(args))
    except UnknownClusterIdsError as exc:
        listed = "\n".join(f"  {cid}" for cid in exc.unknown)
        print(
            f"❌ {len(exc.unknown)} named cluster id(s) are not in the recomputed "
            f"clustering — nothing was written. A cluster id is derived from its "
            f"member set, so a typo OR a clustering that moved since the list was made "
            f"both land here:\n{listed}",
            file=sys.stderr,
        )
        return 2

    # Per FORM, never one blended number (CUPE Phase D) — a single "clusters seen"
    # across two different SFU forms is the category error the phase exists to remove.
    by_template = ", ".join(
        f"{template}={count}" for template, count in result.clusters_by_template.items()
    )
    # …and the same rule for how they SCORED. Each line names the form and its own bar,
    # because "62.9" means nothing without knowing which profile produced it. There is
    # no total line on purpose: a mean over two forms is a mean over two different
    # measurements, and printing one is how it gets quoted.
    evaluation = "\n".join(
        f"  {template}: {ev.drafts_scored} drafts scored on the {template} bar, "
        f"mean {ev.mean_score}, {ev.approvable} approvable, grades {ev.grades}"
        for template, ev in result.evaluation_by_template.items()
    )
    # A SCOPED run must never read back as a full one. Named first, before any count,
    # because the counts below are all counts of the scope and not of the Bank.
    scope = (
        f"⚠ SCOPED RUN — only clusters authoring on {args.only_template!r}; "
        f"{result.clusters_out_of_scope} clusters deliberately not looked at\n"
        if args.only_template
        else ""
    )
    if args.cluster_ids is not None:
        named = len(args.cluster_ids)
        scope += (
            f"⚠ SCOPED RUN — only {named} NAMED cluster(s); "
            f"{result.clusters_out_of_scope} other clusters deliberately not looked "
            f"at\n"
        )
        # Every named id was proven to exist, so a named cluster that was not ENTERED
        # was declined by the rulebook (no authorable form) or had no loadable member.
        # Both are counted below; this says so out loud rather than leaving the reader
        # to subtract.
        if result.clusters_seen != named:
            scope += (
                f"⚠ {named - result.clusters_seen} named cluster(s) were NOT entered — "
                f"no authorable form or no loadable member; see the counts below\n"
            )
    print(
        f"{scope}"
        f"clusters: {result.clusters_recomputed} recomputed -> "
        f"{result.clusters_seen} seen [{by_template or 'none'}] "
        f"({result.multi_member_clusters} multi, "
        f"{result.single_member_clusters} single)\n"
        f"drafts: {result.drafts_persisted} persisted, "
        f"{result.drafts_refreshed} refreshed, "
        f"{result.skipped_reviewer_touched} skipped (reviewer-touched), "
        f"{result.skipped_would_downgrade} skipped (would downgrade an LLM draft), "
        f"{result.skipped_already_llm_written} skipped (already LLM-written), "
        f"{result.clusters_out_of_scope} out of scope, "
        f"{result.cluster_failures} cluster failures\n"
        f"LLM: enabled={result.llm_enabled}, "
        f"{result.rewrite_failures} rewrite failures, "
        f"{result.audit_failures} audit failures\n"
        f"WJQ members: {result.wjq_members_authored} authored, "
        f"{result.wjq_members_excluded} excluded "
        f"({result.wjq_members_frequency_confirmed} frequency-confirmed), "
        f"{result.clusters_fully_wjq_excluded} clusters fully-WJQ with no draft, "
        f"{result.clusters_mixed_jdfn_wjq} mixed\n"
        f"evaluation, PER FORM (never blended — each is its own bar):\n"
        f"{evaluation or '  (no drafts scored)'}\n"
        f"rules_version={result.rules_version}  llm_enabled={result.llm_enabled}",
        file=sys.stderr,
    )

    summary_out = args.summary_out
    if summary_out is None:
        scoped = args.cluster_ids is not None
        summary_out = _SCOPED_SUMMARY_OUT if scoped else _DEFAULT_SUMMARY_OUT
    if summary_out:
        written = _write_summary(
            result,
            path=Path(summary_out),
            scope=(
                {"cluster_ids": sorted(str(cid) for cid in args.cluster_ids)}
                if args.cluster_ids is not None
                else None
            ),
            source=(
                "parsed_jds + dedup_edges (recomputed clusters; forms per "
                "harmonization.templates_harmonized — HR-206)"
            ),
        )
        print(f"wrote {written}", file=sys.stderr)

    return 0


if __name__ == "__main__":  # pragma: no cover - module entry point
    raise SystemExit(main())

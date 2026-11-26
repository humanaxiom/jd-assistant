"""READ-ONLY study: why are 0 of the v9 Bank's CUPE (WJQ) drafts approvable?

``docs/audit/2026-10-27-wjq-approvability.md`` is the write-up; this is its working.

For every WJQ-authored draft in the Bank it reads the stored draft (AFTER the rewrite)
and RECONSTRUCTS the deterministic ``--no-llm`` draft the producer would have written
(BEFORE the rewrite) — in process, with the producer's own ``merge_cluster`` over the
same members' current parses, and the producer's own validator + gate runner. It also
scores every member SOURCE parse, so "the gate fires at source" is a measurement and not
an impression.

🔴 It never writes. The engine is opened with ``default_transaction_read_only=on`` and
every statement runs inside an explicit ``READ ONLY`` transaction, so even a bug here
cannot change the Bank. Run it against the v9 Bank only via a ``--rm`` container on that
Bank's network (see the write-up for the exact command).

Outputs (``--out``): ``wjq-approvability.json`` — counts per gate (source / before /
after) plus, per gate, a deterministic sample of failing drafts with the fields the gate
reads, for reading by eye.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import re
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from src.jd_bank.dedup.signals_load import load_member_jds
from src.jd_bank.jd_text import flatten_jd
from src.jd_core.bank.merge import merge_cluster
from src.jd_core.models.parsed_jd import SFUJobDescription
from src.jd_core.quality.gates import evaluate_gates
from src.jd_core.quality.scoring import score_issues
from src.jd_core.quality.validators import evaluate_jd_rules
from src.jd_core.rules import Rules, get_rules

GATES = (
    "SFU-APPROVE-KSA-ORDER",
    "SFU-APPROVE-QUAL-EQUIVALENT",
    "SFU-APPROVE-NO-PLACEHOLDERS",
    "SFU-APPROVE-SUMMARY-CONDITIONS",
    "SFU-APPROVE-MANDATORY-SECTIONS",
    "SFU-APPROVE-SEVERITY-FLOOR",
)

#: The v9 WJQ drafts. `authored_template` is the producer's own record of the form.
_DRAFTS_SQL = """
SELECT c.cluster_id, c.content, c.change_log, k.members
FROM canonical_jds c JOIN clusters k ON k.id = c.cluster_id
WHERE k.constraint_metadata->>'authored_template' = 'wjq'
  AND c.status = 'DRAFT'
ORDER BY c.cluster_id
"""

_EQUIV_ANY = re.compile(r"equivalen", re.IGNORECASE)


def _evaluate(jd: SFUJobDescription, rules: Rules) -> dict[str, Any]:
    issues = evaluate_jd_rules(jd, flatten_jd(jd), rules=rules)
    score, grade = score_issues(issues, scoring=rules.scoring)
    decision = evaluate_gates(issues, score, grade, gates=rules.gates)
    return {
        "approved": decision.approved,
        "blocking": sorted(g.gate_id for g in decision.blocking),
        "score": score,
        "grade": str(grade),
        "issues": issues,
    }


def _kinds(jd: SFUJobDescription) -> list[str]:
    return [q.kind for q in jd.qualifications]


def _evidence(issues: Sequence[Any], rule_id: str) -> str | None:
    return next((i.evidence for i in issues if i.rule_id == rule_id), None)


def _gate_view(gate: str, jd: SFUJobDescription, ev: dict[str, Any]) -> dict[str, Any]:
    """The fields THIS gate reads — enough to judge it by eye, nothing more."""
    if gate == "SFU-APPROVE-KSA-ORDER":
        return {
            "kinds": _kinds(jd),
            "quals": [f"[{q.kind}] {q.text[:110]}" for q in jd.qualifications][:14],
        }
    if gate == "SFU-APPROVE-QUAL-EQUIVALENT":
        blob = flatten_jd(jd)
        hits = [
            blob[max(0, m.start() - 60) : m.end() + 60] for m in _EQUIV_ANY.finditer(blob)
        ][:3]
        return {
            "quals": [f"[{q.kind}] {q.text[:110]}" for q in jd.qualifications][:10],
            "equivalen_anywhere": hits,
        }
    if gate == "SFU-APPROVE-NO-PLACEHOLDERS":
        return {"evidence": _evidence(ev["issues"], "SFU-STRUCT-PLACEHOLDER")}
    if gate == "SFU-APPROVE-SUMMARY-CONDITIONS":
        return {
            "evidence": _evidence(ev["issues"], "SFU-AUTH-SUMMARY-CONDITIONS"),
            "summary": (jd.position_summary or "")[:400],
        }
    return {"blocking_rule_ids": sorted({i.rule_id for i in ev["issues"] if i.rule_id})}


async def _study(session: AsyncSession, rules: Rules, sample: int) -> dict[str, Any]:
    await session.execute(text("SET TRANSACTION READ ONLY"))
    rows = (await session.execute(text(_DRAFTS_SQL))).all()

    member_ids = {UUID(m["source_id"]) for r in rows for m in r.members}
    jds, dropped = await load_member_jds(session, member_ids)

    before_fail: Counter[str] = Counter()
    after_fail: Counter[str] = Counter()
    stored_fail: Counter[str] = Counter()
    # A cluster "fails at source" for a gate when EVERY member source fails it — the
    # merge could only have passed it by adding something no source had.
    source_all_fail: Counter[str] = Counter()
    source_any_fail: Counter[str] = Counter()
    member_fail: Counter[str] = Counter()
    members_scored = 0
    transitions: dict[str, Counter[str]] = {g: Counter() for g in GATES}
    approvable = {"before": 0, "after": 0, "stored": 0, "sources_any": 0}
    stored_mismatch = 0
    rules_versions: Counter[str] = Counter()
    failing: dict[str, list[dict[str, Any]]] = {g: [] for g in GATES}
    #: The exact SET of blocking gates per draft — what fixing one gate would unblock.
    sets_before: Counter[str] = Counter()
    sets_after: Counter[str] = Counter()

    for r in rows:
        ids = sorted((UUID(m["source_id"]) for m in r.members), key=str)
        members = [jds[i] for i in ids if i in jds]
        if not members:
            continue
        merged = merge_cluster(members, rules=rules)
        before = _evaluate(merged.draft, rules)
        after_jd = SFUJobDescription.model_validate(r.content)
        after = _evaluate(after_jd, rules)
        validator = (r.change_log or {}).get("validator") or {}
        rules_versions[str(validator.get("rules_version"))] += 1
        stored_gd = validator.get("gate_decision") or {}
        stored = sorted(g["gate_id"] for g in stored_gd.get("blocking", []))
        if stored != after["blocking"]:
            stored_mismatch += 1
        srcs = [_evaluate(m, rules) for m in members]
        members_scored += len(srcs)

        sets_before[" + ".join(before["blocking"]) or "(approvable)"] += 1
        sets_after[" + ".join(after["blocking"]) or "(approvable)"] += 1
        approvable["before"] += int(before["approved"])
        approvable["after"] += int(after["approved"])
        approvable["stored"] += int(bool(stored_gd.get("approved")))
        approvable["sources_any"] += int(any(s["approved"] for s in srcs))
        for gate in GATES:
            b, a = gate in before["blocking"], gate in after["blocking"]
            before_fail[gate] += int(b)
            after_fail[gate] += int(a)
            stored_fail[gate] += int(gate in stored)
            in_src = [gate in s["blocking"] for s in srcs]
            source_all_fail[gate] += int(all(in_src))
            source_any_fail[gate] += int(any(in_src))
            member_fail[gate] += sum(in_src)
            transitions[gate][f"{'F' if b else 'P'}->{'F' if a else 'P'}"] += 1
            if a:
                failing[gate].append(
                    {
                        "cluster_id": str(r.cluster_id),
                        "title": after_jd.title,
                        "members": len(members),
                        "fails_in_every_source": all(in_src),
                        "fails_before_rewrite": b,
                        "after": _gate_view(gate, after_jd, after),
                        "before": _gate_view(gate, merged.draft, before),
                        "source0": _gate_view(gate, members[0], srcs[0]),
                    }
                )

    rng = random.Random(20261027)  # a fixed seed: the sample is reproducible
    samples = {
        g: rng.sample(v, min(sample, len(v))) if v else [] for g, v in failing.items()
    }
    return {
        "drafts": len(rows),
        "members_loaded": len(jds),
        "members_dropped_unvalidatable": dropped,
        "members_scored": members_scored,
        "rules_version_now": rules.version,
        "rules_version_on_rows": dict(rules_versions),
        "stored_vs_recomputed_blocking_mismatch": stored_mismatch,
        "approvable": approvable,
        "blocking_sets_before": dict(sets_before.most_common()),
        "blocking_sets_after": dict(sets_after.most_common()),
        "gate_fail": {
            g: {
                "source_member_rows": member_fail[g],
                "source_all_members": source_all_fail[g],
                "source_any_member": source_any_fail[g],
                "before_rewrite": before_fail[g],
                "after_rewrite": after_fail[g],
                "stored": stored_fail[g],
                "transitions": dict(transitions[g]),
            }
            for g in GATES
        },
        "samples": samples,
    }


_SPACES = re.compile(r"\s+")
_EQUIV_PHRASE = "equivalent combination"


async def _archive_probe(
    session: AsyncSession, rules: Rules, sample: int
) -> dict[str, Any]:
    """Does the SOURCE FILE carry the WJQ equivalency choice that the parse lacks?

    Reads every WJQ member's original file from the read-only archive mount and asks
    one question per file: does its extracted text contain "equivalent combination"
    (whitespace folded, case-insensitive)? Then the same question of its PARSE. A file
    that has it and a parse that does not is the parser dropping the line — measured,
    not inferred from `wjq.instruction_markers`.
    """
    from src.jd_bank.ingest.extract import extract_text_from_path

    await session.execute(text("SET TRANSACTION READ ONLY"))
    rows = (await session.execute(text(_DRAFTS_SQL))).all()
    ids = sorted({UUID(m["source_id"]) for r in rows for m in r.members}, key=str)
    jds, _ = await load_member_jds(session, ids)
    refs = dict(
        (
            await session.execute(
                text("SELECT id, storage_ref FROM source_documents WHERE id = ANY(:i)"),
                {"i": ids},
            )
        ).all()
    )
    counts: Counter[str] = Counter()
    snippets: list[dict[str, Any]] = []
    for sid in ids:
        ref = refs.get(sid)
        if ref is None:
            counts["no_storage_ref"] += 1
            continue
        try:
            raw = _SPACES.sub(" ", extract_text_from_path(ref)).lower()
        except Exception:  # noqa: BLE001 - a file we cannot read is counted, not fatal
            counts["unreadable"] += 1
            continue
        counts["read"] += 1
        in_raw = _EQUIV_PHRASE in raw
        jd = jds.get(sid)
        in_parse = jd is not None and _EQUIV_PHRASE in (
            _SPACES.sub(" ", flatten_jd(jd)).lower()
        )
        counts[f"raw={'Y' if in_raw else 'N'} parse={'Y' if in_parse else 'N'}"] += 1
        if in_raw:
            at = raw.index(_EQUIV_PHRASE)
            snippets.append({"source_id": str(sid), "raw": raw[max(0, at - 160) : at + 220]})
    rng = random.Random(20261027)
    return {
        "counts": dict(counts),
        "samples": rng.sample(snippets, min(sample, len(snippets))),
    }


async def _main(args: argparse.Namespace) -> None:
    engine = create_async_engine(
        args.database_url,
        connect_args={"server_settings": {"default_transaction_read_only": "on"}},
    )
    try:
        async with engine.connect() as conn:
            async with AsyncSession(bind=conn) as session:
                if args.archive_probe:
                    probe = await _archive_probe(session, get_rules(), args.sample)
                    await session.rollback()
                    out = Path(args.out)
                    out.mkdir(parents=True, exist_ok=True)
                    path = out / "wjq-equivalency-archive.json"
                    path.write_text(json.dumps(probe, indent=2), encoding="utf-8")
                    print(json.dumps(probe["counts"], indent=2))
                    print(f"wrote {path}")
                    return
                result = await _study(session, get_rules(), args.sample)
                await session.rollback()  # nothing to undo — and nothing to commit
    finally:
        await engine.dispose()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    path = out / "wjq-approvability.json"
    path.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    summary = {k: v for k, v in result.items() if k != "samples"}
    print(json.dumps(summary, indent=2))
    print(f"wrote {path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--out", default="/out")
    parser.add_argument("--sample", type=int, default=10)
    parser.add_argument(
        "--archive-probe",
        action="store_true",
        help="instead: read each WJQ member's SOURCE FILE (archive mounted read-only "
        "at /archive) and check it for the equivalency wording the parse lacks",
    )
    asyncio.run(_main(parser.parse_args()))

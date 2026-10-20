"""Measure what a ``PARSER_VERSION`` bump changed — old vs new parse, per document.

READ-ONLY. It writes nothing to any database and calls no model. Docker-only
(ADR-006); needs only Postgres holding BOTH parser versions' ``parsed_jds`` rows::

    docker compose run --rm -T api python scripts/measure_parse_delta.py \
        --old jd_segmenter_v8 --new jd_segmenter_v9 --json-out /tmp/delta.json

Written for parser v9 (``docs/plans/PARSER-V9-LISTS-AND-CAPS.md``), where it was run
against a throwaway COPY of the live Bank; it is kept because the live re-parse owes
the same comparison afterwards ("check the Bank, not the counter"). Every number it
prints is computed with the code's OWN functions — ``template_of``,
``evaluate_jd_rules`` + ``score_issues`` + ``evaluate_gates`` (raw text =
``flatten_jd``, exactly as the canonical producer scores a draft),
``serialize_document`` / ``serialize_section`` (the embed runner's text identity),
``build_job_signals`` (Tier-3's input), and ``merge_cluster`` (the producer's
deterministic draft) — never a hand-written stand-in.

``--simulate-caps STMT JDFN WJQ`` re-applies duty caps to the NEW parse in memory
(statement ``[:STMT]``, then duties ``[:N]`` by template). That is exact, not an
approximation: the segmenters cut each statement and then stop counting, so a capped
parse is a pure function of an uncapped one. It is how candidate cap values were
compared without re-parsing the archive once per candidate.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from src.jd_bank.canonical.runner import authoring_template, partition_by_template
from src.jd_bank.jd_text import flatten_jd
from src.jd_core.bank.embed_text import serialize_document, serialize_section
from src.jd_core.bank.merge import merge_cluster
from src.jd_core.bank.signals import build_job_signals
from src.jd_core.models.parsed_jd import SFUJobDescription
from src.jd_core.quality.gates import evaluate_gates
from src.jd_core.quality.scoring import score_issues
from src.jd_core.quality.validators import evaluate_jd_rules, template_of
from src.jd_core.rules import Rules, get_rules
from src.settings import get_settings

_OLD_CAP = 400
_BUCKETS = ((0, 0), (1, 1), (2, 2), (3, 5), (6, 12), (13, 24), (25, 10_000))


def _bucket(n: int) -> str:
    for lo, hi in _BUCKETS:
        if lo <= n <= hi:
            return f"{lo}" if lo == hi else f"{lo}-{hi if hi < 10_000 else '+'}"
    raise AssertionError(n)


def _pct(values: Sequence[int], q: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(q * len(ordered)))]


def _caps(
    jd: SFUJobDescription, caps: tuple[int, int, int] | None
) -> SFUJobDescription:
    if caps is None:
        return jd
    stmt, jdfn_n, wjq_n = caps
    limit = wjq_n if template_of(jd) == "wjq" else jdfn_n
    duties = [
        d.model_copy(update={"statement": d.statement[:stmt]})
        for d in jd.duties[:limit]
    ]
    return jd.model_copy(update={"duties": duties})


def _score(jd: SFUJobDescription, rules: Rules) -> tuple[float, bool, frozenset[str]]:
    issues = evaluate_jd_rules(jd, flatten_jd(jd), rules=rules)
    score, grade = score_issues(issues, scoring=rules.scoring)
    approved = evaluate_gates(issues, score, grade, gates=rules.gates).approved
    return score, approved, frozenset(i.rule_id for i in issues)


def _embed_ids(jd: SFUJobDescription, rules: Rules) -> dict[str, tuple[str, bool]]:
    """Each embeddable unit's ``(text_sha256, truncated)`` — the embed runner's
    skip-first identity, so a changed sha is exactly one owed embed call."""
    emb = rules.embeddings
    out: dict[str, tuple[str, bool]] = {}
    doc = serialize_document(jd, emb)
    if doc.text:
        out["document"] = (doc.text_sha256, doc.truncated)
    for section in emb.section_vectors:
        ser = serialize_section(jd, emb, section)
        if ser is not None:
            out[section] = (ser.text_sha256, ser.truncated)
    return out


async def _load(url: str, version: str) -> dict[UUID, dict[str, Any]]:
    engine = create_async_engine(url)
    try:
        async with engine.connect() as conn:
            rows = await conn.execute(
                text(
                    "SELECT source_document_id, parsed FROM parsed_jds "
                    "WHERE parser_version = :v"
                ),
                {"v": version},
            )
            return {sid: parsed for sid, parsed in rows}
    finally:
        await engine.dispose()


async def _clusters(url: str) -> list[dict[str, Any]]:
    """Every cluster with its members and its LATEST canonical's status +
    review-action count (the producer's no-clobber inputs)."""
    sql = """
    SELECT c.id, c.members, cj.status::text AS status,
           (SELECT count(*) FROM review_actions ra WHERE ra.canonical_jd_id = cj.id)
             AS actions
    FROM clusters c
    LEFT JOIN LATERAL (
        SELECT * FROM canonical_jds x WHERE x.cluster_id = c.id
        ORDER BY x.version DESC LIMIT 1
    ) cj ON true
    """
    engine = create_async_engine(url)
    try:
        async with engine.connect() as conn:
            return [dict(r._mapping) for r in await conn.execute(text(sql))]
    finally:
        await engine.dispose()


def _summ(values: Iterable[int]) -> dict[str, float]:
    vals = list(values)
    if not vals:
        return {"n": 0}
    return {
        "n": len(vals),
        "mean": round(statistics.fmean(vals), 1),
        "p50": _pct(vals, 0.5),
        "p95": _pct(vals, 0.95),
        "p99": _pct(vals, 0.99),
        "max": max(vals),
    }


def measure(  # noqa: PLR0915 — one linear report, deliberately not split
    old_rows: dict[UUID, dict[str, Any]],
    new_rows: dict[UUID, dict[str, Any]],
    clusters: list[dict[str, Any]],
    caps: tuple[int, int, int] | None,
    rules: Rules,
    duties_only: bool = False,
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "documents": {"old": len(old_rows), "new": len(new_rows)},
        "caps_simulated": caps,
    }
    groups: dict[str, Counter[str]] = defaultdict(Counter)
    dist: dict[str, Counter[str]] = {"old": Counter(), "new": Counter()}
    stmt_lens: dict[str, list[int]] = {"old": [], "new": []}
    counts_new: dict[str, list[int]] = defaultdict(list)
    fields_changed: Counter[str] = Counter()
    rule_on: Counter[str] = Counter()
    rule_off: Counter[str] = Counter()
    embed_owed: Counter[str] = Counter()
    embed_trunc: dict[str, Counter[str]] = {"old": Counter(), "new": Counter()}
    changed_ids: set[UUID] = set()
    duty_changed_ids: set[UUID] = set()
    new_jds: dict[UUID, SFUJobDescription] = {}
    old_jds: dict[UUID, SFUJobDescription] = {}
    fewer_duties: list[str] = []
    invalid = 0
    for sid, old_raw in old_rows.items():
        new_raw = new_rows.get(sid)
        if new_raw is None:
            groups["_missing_in_new"]["docs"] += 1
            continue
        try:
            old = SFUJobDescription.model_validate(old_raw)
            new = _caps(SFUJobDescription.model_validate(new_raw), caps)
            if duties_only:
                new = old.model_copy(update={"duties": new.duties})
        except ValueError:
            invalid += 1
            continue
        old_jds[sid], new_jds[sid] = old, new
        group = new.employee_group or "none"
        g = groups[group]
        g["docs"] += 1
        no, nn = len(old.duties), len(new.duties)
        dist["old"][_bucket(no)] += 1
        dist["new"][_bucket(nn)] += 1
        counts_new[template_of(new)].append(nn)
        g["one_duty_old"] += no == 1
        g["one_duty_new"] += nn == 1
        g["stmts_old"] += no
        g["stmts_new"] += nn
        g["at_400_old"] += sum(len(d.statement) == _OLD_CAP for d in old.duties)
        g["over_400_new"] += sum(len(d.statement) > _OLD_CAP for d in new.duties)
        g["at_400_new"] += sum(len(d.statement) == _OLD_CAP for d in new.duties)
        if caps is not None:
            g["at_new_stmt_cap"] += sum(len(d.statement) == caps[0] for d in new.duties)
            limit = caps[2] if template_of(new) == "wjq" else caps[1]
            g["at_new_count_cap"] += nn == limit
        g["chars_old"] += sum(len(d.statement) for d in old.duties)
        g["chars_new"] += sum(len(d.statement) for d in new.duties)
        g["quals_at_400_new"] += sum(
            len(q.text) == _OLD_CAP for q in new.qualifications
        )
        g["quals_at_40_new"] += len(new.qualifications) == 40
        g["quals_at_40_old"] += len(old.qualifications) == 40
        g["bullets_at_400_new"] += sum(
            len(b) == _OLD_CAP for b in (*new.decision_making, *new.problem_solving)
        )
        g["bullets_at_400_old"] += sum(
            len(b) == _OLD_CAP for b in (*old.decision_making, *old.problem_solving)
        )
        stmt_lens["old"].extend(len(d.statement) for d in old.duties)
        stmt_lens["new"].extend(len(d.statement) for d in new.duties)
        if nn < no:
            g["fewer_duties"] += 1
            fewer_duties.append(f"{sid}\t{no}->{nn}")
        od, nd = old.model_dump(mode="json"), new.model_dump(mode="json")
        diff = {k for k in od if od[k] != nd.get(k)}
        if diff:
            changed_ids.add(sid)
            g["changed"] += 1
            fields_changed.update(diff)
            if "duties" in diff:
                duty_changed_ids.add(sid)
            # Validator: only documents whose parse changed can change score.
            so, ao, ro = _score(old, rules)
            sn, an, rn = _score(new, rules)
            g["score_delta_x10"] += round((sn - so) * 10)
            g["approvable_old"] += ao
            g["approvable_new"] += an
            rule_on.update(rn - ro)
            rule_off.update(ro - rn)
        eo, en = _embed_ids(old, rules), _embed_ids(new, rules)
        for unit, (sha, trunc) in en.items():
            if eo.get(unit, ("", False))[0] != sha:
                embed_owed[unit] += 1
            embed_trunc["new"][unit] += trunc
        for unit, (_sha, trunc) in eo.items():
            embed_trunc["old"][unit] += trunc
        if build_job_signals(old, rules=rules) != build_job_signals(new, rules=rules):
            g["signals_changed"] += 1

    totals: Counter[str] = Counter()
    for c in groups.values():
        totals.update(c)
    report["invalid_rows"] = invalid
    report["per_group"] = {k: dict(v) for k, v in sorted(groups.items())}
    report["totals"] = dict(totals)
    report["duty_count_distribution"] = {k: dict(v) for k, v in dist.items()}
    report["duty_count_new_by_template"] = {k: _summ(v) for k, v in counts_new.items()}
    report["statement_length"] = {k: _summ(v) for k, v in stmt_lens.items()}
    report["fields_changed"] = dict(fields_changed.most_common())
    report["rules_newly_firing"] = dict(rule_on.most_common(25))
    report["rules_cleared"] = dict(rule_off.most_common(25))
    report["embed_calls_owed"] = dict(embed_owed)
    report["embed_truncated"] = {k: dict(v) for k, v in embed_trunc.items()}
    report["fewer_duties_examples"] = fewer_duties[:40]

    # ── Downstream: clusters, drafts, the deterministic merge ────────────────
    by_status: Counter[str] = Counter()
    merge_changed = 0
    merged_chars: dict[str, list[int]] = {"old": [], "new": []}
    draft_scores: dict[str, list[float]] = {"old": [], "new": []}
    for cl in clusters:
        ids = [UUID(m["source_id"]) for m in cl["members"]]
        touched = any(i in changed_ids for i in ids)
        duty_touched = any(i in duty_changed_ids for i in ids)
        status = cl["status"] or "NO_CANONICAL"
        kind = (
            "reviewer_touched"
            if status != "DRAFT" or (cl["actions"] or 0) > 0
            else "untouched_draft"
        )
        if status == "NO_CANONICAL":
            kind = "no_canonical"
        by_status[f"{kind}:all"] += 1
        by_status[f"{kind}:any_member_changed"] += touched
        by_status[f"{kind}:any_member_duties_changed"] += duty_touched
        if not touched:
            continue
        pairs_old = [(i, old_jds[i]) for i in ids if i in old_jds]
        pairs_new = [(i, new_jds[i]) for i in ids if i in new_jds]
        form = authoring_template(partition_by_template(pairs_new), rules.harmonization)
        if form is None:
            continue
        mo = [jd for _i, jd in pairs_old if template_of(jd) == form]
        mn = [jd for _i, jd in pairs_new if template_of(jd) == form]
        if not mo or not mn:
            continue
        old_draft = merge_cluster(mo, rules=rules).draft
        new_draft = merge_cluster(mn, rules=rules).draft
        if old_draft != new_draft:
            merge_changed += 1
            by_status[f"{kind}:deterministic_draft_changed"] += 1
        merged_chars["old"].append(len(flatten_jd(old_draft)))
        merged_chars["new"].append(len(flatten_jd(new_draft)))
        draft_scores["old"].append(_score(old_draft, rules)[0])
        draft_scores["new"].append(_score(new_draft, rules)[0])
    report["clusters"] = dict(by_status)
    report["deterministic_drafts_changed"] = merge_changed
    report["merged_draft_chars_affected"] = {
        k: _summ(v) for k, v in merged_chars.items()
    }
    report["merged_draft_mean_score_affected"] = {
        k: round(statistics.fmean(v), 2) if v else None for k, v in draft_scores.items()
    }
    return report


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="python scripts/measure_parse_delta.py")
    p.add_argument("--old", required=True)
    p.add_argument("--new", required=True)
    p.add_argument("--simulate-caps", nargs=3, type=int, default=None)
    p.add_argument("--json-out", default="")
    p.add_argument(
        "--duties-only",
        action="store_true",
        help="take ONLY the duties from the new parse (every other field from the old)",
    )
    return p.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(list(sys.argv[1:] if argv is None else argv))
    url = get_settings().database_url
    rules = get_rules()

    async def _go() -> dict[str, Any]:
        old_rows = await _load(url, args.old)
        new_rows = await _load(url, args.new)
        clusters = await _clusters(url)
        caps = tuple(args.simulate_caps) if args.simulate_caps else None
        return measure(
            old_rows, new_rows, clusters, caps, rules, args.duties_only  # type: ignore[arg-type]
        )

    report = asyncio.run(_go())
    out = json.dumps(report, indent=2, default=str)
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as fh:
            fh.write(out)
    print(out)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

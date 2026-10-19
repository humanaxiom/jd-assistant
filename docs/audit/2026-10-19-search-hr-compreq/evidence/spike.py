"""Read-only search spike. Runs INSIDE jd-bank-api-1 (cd /app). Never writes.

Usage: python /tmp/spike.py <mode> [model]
  mode = baseline | nlp | rerank
"""
from __future__ import annotations

import asyncio
import json
import re
import sys
import time
from typing import Literal
from uuid import UUID

from neo4j import AsyncGraphDatabase
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.jd_bank.composer import search as S
from src.jd_bank.embeddings.client import EmbedClient
from src.jd_bank.library.service import list_roles
from src.jd_bank.llm.client import ChatClient
from src.jd_core.rules import get_rules
from src.settings import get_settings

SCI = re.compile(
    r"biolog|chemistry|mathemat|molecular biology|physics|statistics|earth sci|"
    r"faculty of science|science dean|dean of science|biomedical physiology|kinesiology|"
    r"science technical|science stores|\bscience,|^science\b",
    re.I,
)
NOT_SCI = re.compile(r"social|health|applied|political|computing|environment|engineering", re.I)


def T(p):
    rx = re.compile(p, re.I)
    return lambda t, d, g: bool(rx.search(t or ""))


SYSADMIN = r"system(s)?.{0,15}admin|sysadmin|systems (consultant|specialist|engineer)|infrastructure|unix|linux|devops|server"
COOP = r"(co-?op|co‑op|co-operative)( education)?( program)? (coordinator|career advisor)"
AP = r"accounts? (payable|receivable)|accounting|financ\w* (and administrative )?(assistant|clerk)|administrative and financial assistant|finance (assistant|clerk)|accounts? clerk|bookkeep"

Q = [
    ("E1", "exact", "Financial Assistant", "wjq", T(r"financ\w* (and administrative )?assistant|administrative and financial assistant")),
    ("E2", "exact", "Co-op Education Coordinator", "jdfn", T(COOP)),
    ("E3", "exact", "Research Grants Facilitator", "jdfn", T(r"research (grants?|facilitat)")),
    ("E4", "exact", "Laboratory Technician", "wjq", T(r"lab(oratory)? (technician|technologist|assistant)|research technician")),
    ("P1", "paraphrase", "someone who processes invoices and reconciles accounts", "wjq", T(AP)),
    ("P2", "paraphrase", "person who helps students plan their courses and meet degree requirements", "jdfn", T(r"(academic|undergraduate|graduate|program|student)( program)? advis")),
    ("P3", "paraphrase", "fundraiser who builds relationships with major donors", "jdfn", T(r"advancement|development (officer|coordinator|director|manager)|major gifts|gift|donor|fundrais|philanthrop")),
    ("P4", "paraphrase", "entry-level library job shelving books and helping patrons at the desk", "wjq", T(r"librar\w* (assistant|circulation)|circulation|loans")),
    ("D1", "duty", "maintain Linux servers, apply patches, run backups and manage user accounts", "jdfn", T(SYSADMIN)),
    ("D2", "duty", "plan and run conferences, convocation ceremonies and university events", "jdfn", T(r"event|ceremon|convocation|conference")),
    ("D3", "duty", "manage research grant applications and post-award budgets for faculty members", "jdfn", T(r"research (grants?|facilitat|finance|services|project)|grants? (officer|facilitator|coordinator|administrator)|post-award")),
    ("D4", "duty", "write news stories, manage social media and the department newsletter", "jdfn", T(r"communicat|marketing|writer|social media|content|editor")),
    ("C1", "constraint", "supervisory admin role in Faculty of Science, APSA", "jdfn",
     lambda t, d, g: bool(re.search(r"manager|director|administrator", t or "", re.I)) and bool(SCI.search(d or "")) and not NOT_SCI.search(d or "") and (g or "") in ("apsa", "")),
    ("C2", "constraint", "CUPE administrative assistant", "wjq",
     lambda t, d, g: bool(re.search(r"administrative assistant|office assistant|program assistant|secretary|admin\w* and \w+ assistant", t or "", re.I)) and g == "cupe"),
    ("C3", "constraint", "APSA communications officer", "jdfn",
     lambda t, d, g: bool(re.search(r"communications (officer|associate|coordinator|specialist|manager)|marketing (and|&) communications", t or "", re.I)) and (g or "") in ("apsa", "")),
    ("C4", "constraint", "academic advisor in the Beedie business school", "jdfn",
     lambda t, d, g: bool(re.search(r"advis", t or "", re.I)) and bool(re.search(r"beedie|business", d or "", re.I))),
    ("A1", "abbrev", "coop coord", "jdfn", T(COOP)),
    ("A2", "abbrev", "IT sysadmin", "jdfn", T(SYSADMIN)),
    ("A3", "abbrev", "AP clerk", "wjq", T(AP)),
    ("A4", "typo", "adminstrative cordinator", "jdfn", T(r"administrative co-?ordinator")),
    ("A5", "abbrev", "HR advisor labour relations", "jdfn", T(r"labou?r|employee relations|human resources")),
    ("A6", "abbrev", "web dev", "jdfn", T(r"web")),
]


class QueryPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    semantic_query: str = Field(description="2-3 sentences describing the role's duties in SFU job-description language")
    title_keywords: list[str] = Field(description="1-6 likely SFU job titles or title fragments, abbreviations expanded, typos fixed")
    employee_group: Literal["apsa", "cupe", "apex", "poly", "any"]
    department_keywords: list[str] = Field(description="department/faculty names ONLY if the query names one, else empty")
    supervisory: Literal["yes", "no", "unknown"]


PLAN_SYS = """You turn a hiring manager's search for a staff job description at Simon Fraser University (SFU) into a structured search plan. Return ONLY JSON.
- title_keywords: 1-6 short job-title strings as SFU writes them (e.g. "Accounts Payable Clerk", "Co-op Education Coordinator", "Systems Administrator"). Expand abbreviations (coop -> Co-op, AP -> Accounts Payable, sysadmin -> Systems Administrator, HR -> Human Resources), fix spelling. Prefer short fragments that would appear inside a title.
- semantic_query: 2-3 sentences describing the duties, written like a job description, no title.
- employee_group: "apsa" (administrative/professional staff), "cupe" (support/clerical/technical staff union), "apex", "poly", or "any" if the query does not say.
- department_keywords: only if the query names a faculty/department/unit; list the unit name and, for a faculty, its member departments as they would appear on a JD. Else [].
- supervisory: "yes" if the query asks for a supervisory/manager role, "no" if it says non-supervisory/entry-level, else "unknown".
Never invent constraints the query does not state."""


class Rerank(BaseModel):
    model_config = ConfigDict(extra="forbid")
    order: list[int]


RERANK_SYS = """You rank SFU job descriptions for a hiring manager's search. Given the query and numbered candidates (title | department | employee group | summary), return JSON {"order": [...]} listing the candidate numbers from most to least relevant. Include only candidates that plausibly match; omit clearly unrelated ones."""


async def role_meta(session):
    rows = (await session.execute(text(
        "select distinct on (cluster_id) cluster_id, content->>'title', coalesce(content->>'department',''), "
        "coalesce(content->>'employee_group',''), left(coalesce(content->>'position_summary',''),220) "
        "from canonical_jds order by cluster_id, version desc"))).all()
    return {r[0]: (r[1] or "", r[2], r[3], r[4]) for r in rows}


def judge(rel, rows):
    flags = [bool(rel(t, d, g)) for (t, d, g) in rows]
    return {
        "hit5": any(flags[:5]), "hit10": any(flags[:10]),
        "p10": sum(flags[:10]) / 10, "n": len(rows),
        "first_rel": (flags.index(True) + 1) if True in flags else None,
        "top": [f"{'*' if f else ' '} {t} | {d[:40]} | {g}" for f, (t, d, g) in zip(flags[:10], rows[:10])],
    }


async def library_baseline(session, meta, q):
    page = await list_roles(session, q=q, limit=10)
    rows = [meta.get(i.cluster_id, (i.title, "", ""))[:3] for i in page.items]
    return rows, page.total


STOP = {"school", "faculty", "of", "the", "and", "department", "office", "dean", "services", "centre", "center", "program"}


def guard(q, plan):
    """Deterministic guard on LLM output: a HARD filter survives only if the user typed it."""
    ql = q.lower()
    g = plan.employee_group if plan.employee_group != "any" and plan.employee_group in ql else "any"
    depts = [d for d in plan.department_keywords
             if any(tok in ql for tok in re.findall(r"[a-z]{4,}", d.lower()) if tok not in STOP)]
    kws = [q] + [k for k in plan.title_keywords if k.lower() != ql]
    return plan.model_copy(update={"employee_group": g, "department_keywords": depts, "title_keywords": kws})


async def library_vector(driver, embed, meta, semantic, group=None, kw=None, session=None, dept=None, limit=10, soft_dept=None):
    """Prototype: title-keyword ILIKE over roles first, then role-vector neighbours."""
    rules = get_rules()
    out, seen = [], set()

    def ok(cid):
        t, d, g, _ = meta[cid]
        if group and group != "any" and g not in (group, ""):
            return False
        if dept and not any(k.lower() in d.lower() for k in dept):
            return False
        return True

    for k in (kw or []):
        k = k.strip()
        if not k:
            continue
        hits = [(cid, m) for cid, m in meta.items() if k.lower() in m[0].lower()]
        hits.sort(key=lambda x: (S._title_rank(x[1][0], k), 0 if (group and x[1][2] == group) else 1, x[1][0]))
        for cid, _ in hits:
            if cid not in seen and ok(cid):
                seen.add(cid); out.append(cid)
    t0 = time.perf_counter()
    vec = (await embed.embed_batch([semantic]))[0]
    t_emb = time.perf_counter() - t0
    near = await S._nearest_role_ids(driver, vec, 100, live_stamp=rules.embeddings.stamp)
    for cid, *_ in near:
        if cid in meta and cid not in seen and ok(cid):
            seen.add(cid); out.append(cid)
    if soft_dept:
        pool = out[:60]
        m = [c for c in pool if any(k.lower() in meta[c][1].lower() for k in soft_dept)]
        ms = set(m)
        out = m + [c for c in out if c not in ms]
    return [meta[c][:3] for c in out[:limit]], [c for c in out[:20]], t_emb


async def builder_plan(session, driver, embed, plan, form, limit=10):
    """Prototype of search_similar_jds driven by a QueryPlan: title passes per keyword, then vectors on semantic_query."""
    rules = get_rules()
    wjq = frozenset(rules.segmentation.wjq_employee_groups)
    hits, seen, seen_c = [], set(), set()
    g = plan.employee_group

    def grp_ok(x):
        return g == "any" or (x or "") in (g, "")

    for kw in plan.title_keywords:
        for cid, t, grp in await S._role_title_matches(session, kw, limit=limit):
            if S._out_of_scope(grp, wjq, form) or not grp_ok(grp) or cid in seen_c:
                continue
            seen_c.add(cid); hits.append(S.SearchHit(cluster_id=cid, title=t, employee_group=grp, match="role_title"))
    for kw in plan.title_keywords:
        titled = await S._title_matches(session, kw, limit=limit)
        dc = await S._clusters_for_sources(session, list(titled))
        for sid, jd in titled.items():
            if S._out_of_scope(jd.employee_group, wjq, form) or not grp_ok(jd.employee_group):
                continue
            c = dc.get(sid)
            if (c and c in seen_c) or sid in seen:
                continue
            if c: seen_c.add(c)
            seen.add(sid)
            hits.append(S.SearchHit(source_document_id=sid, cluster_id=c, title=jd.title, department=jd.department, employee_group=jd.employee_group, match="title"))
    vec = (await embed.embed_batch([plan.semantic_query]))[0]
    for cid, t, grp, sc in await S._nearest_role_ids(driver, vec, limit * 3, live_stamp=rules.embeddings.stamp):
        if S._out_of_scope(grp, wjq, form) or not grp_ok(grp) or cid in seen_c:
            continue
        seen_c.add(cid); hits.append(S.SearchHit(cluster_id=cid, title=t, employee_group=grp, score=sc))
    near = await S._nearest_source_ids(driver, vec, limit * 3, live_stamp=rules.embeddings.stamp)
    parsed = await S._load_latest_parsed(session, [s for s, _ in near])
    nc = await S._clusters_for_sources(session, [s for s, _ in near])
    for sid, sc in near:
        jd = parsed.get(sid)
        if jd is None or S._out_of_scope(jd.employee_group, wjq, form) or not grp_ok(jd.employee_group) or sid in seen:
            continue
        c = nc.get(sid)
        if c and c in seen_c:
            continue
        if c: seen_c.add(c)
        hits.append(S.SearchHit(source_document_id=sid, cluster_id=c, title=jd.title, department=jd.department, employee_group=jd.employee_group, score=sc))
    # NOTE: no early cut at `limit` inside passes here (unlike prod) so keyword passes
    # don't starve the vector pass; cut at the end.
    hits = await S._with_departments(session, hits[:limit])
    return hits


def hit_rows(hits, meta):
    rows = []
    for h in hits:
        if h.cluster_id and h.cluster_id in meta:
            t, d, g, _ = meta[h.cluster_id]
            rows.append((h.title or t, h.department or d, h.employee_group if h.employee_group is not None else g))
        else:
            rows.append((h.title, h.department or "", h.employee_group or ""))
    return rows


async def main():
    mode = sys.argv[1]
    model = sys.argv[2] if len(sys.argv) > 2 else get_rules().rewrite.model
    st = get_settings()
    engine = create_async_engine(st.database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    driver = AsyncGraphDatabase.driver(st.neo4j_uri, auth=(st.neo4j_user, st.neo4j_password))
    embed = EmbedClient()
    out = {"mode": mode, "model": model, "queries": []}
    global PLANS
    if mode == "guarded":
        PLANS = {r["id"]: r["plan"] for r in json.load(open(sys.argv[3]))["queries"] if "plan" in r}
    async with maker() as session:
        await session.execute(text("SET TRANSACTION READ ONLY"))
        meta = await role_meta(session)
        chat = ChatClient(model=model, temperature=0.0, reasoning_effort="low") if mode in ("nlp", "rerank") else None
        for qid, kind, q, form, rel in Q:
            rec = {"id": qid, "kind": kind, "q": q, "form": form}
            if mode == "baseline":
                rows, total = await library_baseline(session, meta, q)
                rec["library"] = judge(rel, rows) | {"total": total}
                t0 = time.perf_counter()
                hits = await S.search_similar_jds(q, embed_client=embed, neo4j_driver=driver, session=session, limit=10, form=form)
                rec["builder_s"] = round(time.perf_counter() - t0, 3)
                rec["builder"] = judge(rel, hit_rows(hits, meta)) | {"matches": [h.match for h in hits]}
                rows, _, te = await library_vector(driver, embed, meta, q, kw=[q])
                rec["library_rawvec"] = judge(rel, rows)
            elif mode == "guarded":
                plan = QueryPlan.model_validate(PLANS[qid])
                plan = guard(q, plan)
                rec["plan"] = plan.model_dump()
                t1 = time.perf_counter()
                rows, pool, te = await library_vector(driver, embed, meta, plan.semantic_query, group=plan.employee_group, kw=plan.title_keywords, soft_dept=plan.department_keywords)
                rec["lib_s"] = round(time.perf_counter() - t1, 3)
                rec["library_guarded"] = judge(rel, rows)
                t1 = time.perf_counter()
                hits = await builder_plan(session, driver, embed, plan, form)
                rec["builder_nlp_s"] = round(time.perf_counter() - t1, 3)
                rec["builder_guarded"] = judge(rel, hit_rows(hits, meta))
            else:
                t0 = time.perf_counter()
                try:
                    plan = await chat.chat_json(
                        [{"role": "system", "content": PLAN_SYS}, {"role": "user", "content": q}],
                        QueryPlan, max_tokens=1200, max_retries=1, constrain_to_schema=True)
                    rec["plan_s"] = round(time.perf_counter() - t0, 3)
                    rec["plan"] = plan.model_dump()
                except Exception as exc:  # noqa: BLE001
                    rec["plan_s"] = round(time.perf_counter() - t0, 3)
                    rec["plan_error"] = repr(exc)[:300]
                    out["queries"].append(rec); print(json.dumps(rec)[:400], flush=True); continue
                rows, pool, te = await library_vector(driver, embed, meta, plan.semantic_query, group=plan.employee_group, kw=plan.title_keywords)
                rec["library_nlp"] = judge(rel, rows)
                if plan.department_keywords:
                    rows_d, _, _ = await library_vector(driver, embed, meta, plan.semantic_query, group=plan.employee_group, kw=plan.title_keywords, dept=plan.department_keywords)
                    rec["library_nlp_dept"] = judge(rel, rows_d)
                t1 = time.perf_counter()
                hits = await builder_plan(session, driver, embed, plan, form)
                rec["builder_nlp_s"] = round(time.perf_counter() - t1, 3)
                rec["builder_nlp"] = judge(rel, hit_rows(hits, meta))
                if mode == "rerank":
                    cands = pool[:20]
                    listing = "\n".join(f"{i}. {meta[c][0]} | {meta[c][1][:50]} | {meta[c][2] or '-'} | {meta[c][3][:160]}" for i, c in enumerate(cands))
                    t2 = time.perf_counter()
                    try:
                        rr = await chat.chat_json(
                            [{"role": "system", "content": RERANK_SYS}, {"role": "user", "content": f"Query: {q}\n\nCandidates:\n{listing}"}],
                            Rerank, max_tokens=1500, max_retries=1, constrain_to_schema=True)
                        rec["rerank_s"] = round(time.perf_counter() - t2, 3)
                        order = [cands[i] for i in rr.order if 0 <= i < len(cands)]
                        rec["library_nlp_rerank"] = judge(rel, [meta[c][:3] for c in order[:10]])
                    except Exception as exc:  # noqa: BLE001
                        rec["rerank_s"] = round(time.perf_counter() - t2, 3)
                        rec["rerank_error"] = repr(exc)[:300]
            out["queries"].append(rec)
            print(qid, json.dumps({k: v for k, v in rec.items() if k.endswith("_s")}), flush=True)
        await session.rollback()
    await embed.close(); await driver.close(); await engine.dispose()
    if chat: await chat.close()
    with open(f"/tmp/spike_{mode}_{model.replace(':','_').replace('/','_')}.json", "w") as f:
        json.dump(out, f, indent=1, default=str)


asyncio.run(main())

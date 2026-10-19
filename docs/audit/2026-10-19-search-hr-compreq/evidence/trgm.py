"""Emulate pg_trgm similarity()/word_similarity over current role titles (read-only)."""
import re, subprocess, sys, json
import asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from src.settings import get_settings


def trg(s):
    out = set()
    for w in re.findall(r"[a-z0-9]+", s.lower()):
        w = "  " + w + " "
        out |= {w[i:i + 3] for i in range(len(w) - 2)}
    return out


def sim(a, b):
    A, B = trg(a), trg(b)
    return len(A & B) / len(A | B) if A | B else 0.0


def wsim(q, t):
    """approx word_similarity: best over contiguous word spans of t."""
    Q = trg(q)
    words = re.findall(r"[a-z0-9]+", t.lower())
    best = 0.0
    for i in range(len(words)):
        for j in range(i + 1, len(words) + 1):
            S = trg(" ".join(words[i:j]))
            best = max(best, len(Q & S) / len(Q | S) if Q | S else 0)
    return best


async def main():
    eng = create_async_engine(get_settings().database_url)
    async with eng.connect() as c:
        rows = (await c.execute(text("select distinct on (cluster_id) content->>'title' from canonical_jds order by cluster_id, version desc"))).all()
    titles = sorted({r[0] or "" for r in rows})
    for q in sys.argv[1:]:
        ranked = sorted(titles, key=lambda t: -wsim(q, t))[:8]
        print("##", q)
        for t in ranked:
            print(f"   {wsim(q, t):.2f} {sim(q, t):.2f} {t}")
    await eng.dispose()

asyncio.run(main())

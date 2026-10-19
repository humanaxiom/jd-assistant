import json, sys, statistics as stt

def agg(recs, key):
    xs = [r[key] for r in recs if key in r]
    if not xs:
        return None
    return dict(n=len(xs), hit5=sum(x["hit5"] for x in xs), hit10=sum(x["hit10"] for x in xs),
                p10=round(sum(x["p10"] for x in xs) / len(xs), 3), empty=sum(1 for x in xs if x["n"] == 0))

for path in sys.argv[1:]:
    d = json.load(open(path))
    recs = d["queries"]
    print("=====", path, d["mode"], d["model"])
    keys = sorted({k for r in recs for k, v in r.items() if isinstance(v, dict) and "hit5" in v})
    for k in keys:
        print(k, agg(recs, k))
    for tk in ("builder_s", "plan_s", "builder_nlp_s", "rerank_s"):
        xs = sorted(r[tk] for r in recs if tk in r)
        if xs:
            p95 = xs[min(len(xs) - 1, int(round(0.95 * (len(xs) - 1))))]
            print(tk, "p50", round(stt.median(xs), 2), "p95", p95, "max", xs[-1], "min", xs[0])
    print("per-query: id | " + " | ".join(keys))
    for r in recs:
        cells = []
        for k in keys:
            v = r.get(k)
            cells.append("-" if v is None else f"{'H5' if v['hit5'] else ('h10' if v['hit10'] else '--')} p{v['p10']:.1f} n{v['n']}")
        print(r["id"], r["q"][:45].ljust(45), " | ".join(cells), r.get("plan_error", "")[:80])

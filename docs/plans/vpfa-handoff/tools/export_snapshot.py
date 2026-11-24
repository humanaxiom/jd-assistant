"""One-off, READ-ONLY export of a JD Bank snapshot for the VPFA spinoff.

Run it INSIDE a container built from the Bank's own checkout, so it uses that Bank's code
and settings. START-HERE.md Part A has the exact command; it is a throwaway
`docker compose run --rm` with no published ports.

It is the prototype of the parent's planned `make bank-snapshot` (VPFA-SPINOFF-PLAN §5.1).
It only SELECTs. Counts in the manifest are READ BACK from the files it wrote, and
checked against the database, so a short write cannot pass as complete (plan L-01).
"""

from __future__ import annotations

import asyncio
import dataclasses
import datetime as dt
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.jd_bank.library.funnel import build_facets, build_funnel, build_gap
from src.jd_bank.library.scopes import scope_for
from src.jd_bank.library.units import resolve_unit
from src.jd_core.parser.segmenter import PARSER_VERSION
from src.jd_core.rules import get_rules
from src.settings import get_settings

TABLES: dict[str, str] = {
    "clusters": "select * from clusters order by id",
    "canonical_jds": "select * from canonical_jds order by cluster_id, version",
    "source_documents": "select * from source_documents order by id",
    # Only the CURRENT parse of each document; older parser versions are history.
    "parsed_jds": (
        "select * from parsed_jds where parser_version = :pv order by source_document_id"
    ),
}


def _default(o: Any) -> Any:
    if dataclasses.is_dataclass(o) and not isinstance(o, type):
        return dataclasses.asdict(o)
    if hasattr(o, "model_dump"):
        return o.model_dump(mode="json")
    if isinstance(o, (dt.datetime, dt.date)):
        return o.isoformat()
    if isinstance(o, (set, frozenset, tuple)):
        return list(o)
    return str(o)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


async def main(out: Path, source_bank: str, parent_git_sha: str) -> int:
    out.mkdir(parents=True, exist_ok=True)
    rules = get_rules()
    engine = create_async_engine(get_settings().database_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    files: dict[str, dict[str, Any]] = {}
    async with maker() as s:
        # One REPEATABLE READ transaction: every file sees the same moment.
        await s.execute(text("set transaction isolation level repeatable read, read only"))
        for name, sql in TABLES.items():
            params = {"pv": PARSER_VERSION} if ":pv" in sql else {}
            db_count = (
                await s.execute(text(f"select count(*) from ({sql}) q"), params)
            ).scalar_one()
            path = out / f"{name}.jsonl"
            rows = (await s.execute(text(sql), params)).mappings()
            with path.open("w", encoding="utf-8") as f:
                for row in rows:
                    f.write(json.dumps(dict(row), default=_default, ensure_ascii=False))
                    f.write("\n")
            written = sum(1 for _ in path.open(encoding="utf-8"))
            if written != db_count:
                print(f"REFUSED: {name} wrote {written} rows, database holds {db_count}")
                return 1
            files[path.name] = {"rows": written, "sha256": _sha256(path)}

        whole = await scope_for(s, None, rules=rules)
        funnel = {
            "scope": "whole_bank",
            "funnel": await build_funnel(s, whole),
            "facets": await build_facets(s, whole),
            "gap": await build_gap(s, whole),
        }
        units = {}
        for key, unit in rules.org_units.units.items():
            r = await resolve_unit(s, unit, unit_key=key, rules=rules)
            units[key] = {
                "label": r.label,
                "slug": r.slug,
                "in_unit": r.in_unit,
                "not_in_unit": r.not_in_unit,
                "department_unrecorded": r.department_unrecorded,
                "departments": list(r.departments),
                "member_cluster_ids": [str(c) for c in r.member_cluster_ids],
            }
        status = (
            await s.execute(text("select status::text, count(*) from canonical_jds group by 1"))
        ).all()
    await engine.dispose()

    for name, payload in (("funnel.json", funnel), ("units.json", units)):
        p = out / name
        p.write_text(json.dumps(payload, default=_default, indent=1, ensure_ascii=False))
        files[name] = {"sha256": _sha256(p)}

    manifest = {
        "kind": "jd-bank-snapshot",
        "format_version": 1,
        "exported_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "source_bank": source_bank,
        "parent_git_sha": parent_git_sha,
        "parser_version": PARSER_VERSION,
        "rules_version": rules.version,
        "prompt_version": rules.rewrite.prompt_version,
        "canonical_status_counts": {k: v for k, v in status},
        "files": files,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1))
    print(json.dumps(manifest, indent=1))
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 4:
        print("usage: export_snapshot.py <out-dir> <source-bank-label> <parent-git-sha>")
        sys.exit(2)
    sys.exit(asyncio.run(main(Path(sys.argv[1]), sys.argv[2], sys.argv[3])))

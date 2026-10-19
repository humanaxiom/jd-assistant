"""Loader + judge for the ``search_eval_v1`` relevance fixture (Track I1).

Shared by the unit test that pins the fixture's shape and the live smoke that scores the
running library against it. The judge is a pure function of (title, department, group).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

FIXTURE = Path(__file__).parent / "fixtures" / "search_eval_v1.yaml"


@dataclass(frozen=True)
class EvalQuery:
    id: str
    kind: str
    query: str
    title_pattern: str
    department_pattern: str | None = None
    not_department_pattern: str | None = None
    groups: tuple[str, ...] | None = None

    def relevant(
        self, title: str | None, department: str | None, group: str | None
    ) -> bool:
        t, d, g = title or "", department or "", group or ""
        if not re.search(self.title_pattern, t, re.I):
            return False
        if self.department_pattern and not re.search(self.department_pattern, d, re.I):
            return False
        if self.not_department_pattern and re.search(
            self.not_department_pattern, d, re.I
        ):
            return False
        return self.groups is None or g in self.groups


def load_eval(path: Path = FIXTURE) -> tuple[int, list[EvalQuery]]:
    """``(recall_floor_hit_at_10, queries)``."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    queries = [
        EvalQuery(
            id=q["id"],
            kind=q["kind"],
            query=q["query"],
            title_pattern=q["title_pattern"],
            department_pattern=q.get("department_pattern"),
            not_department_pattern=q.get("not_department_pattern"),
            groups=tuple(q["groups"]) if "groups" in q else None,
        )
        for q in raw["queries"]
    ]
    return int(raw["recall_floor_hit_at_10"]), queries

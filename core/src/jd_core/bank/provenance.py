"""Harmonization provenance (pure).

Ported near-verbatim from hris ``packages/pipeline/src/pipeline/bank/
provenance.py`` (reuse-map #11).

Deterministic backbone for canonical-role drafting: how often each skill appears
across a cluster's member JDs. The composer drafts the canonical narrative; this
gives the verifiable provenance (a skill required by most members is core; a
one-off is likely incidental).

No decision parameter lives here — it counts, it does not judge. "How many
members make a skill core" is a harmonization threshold; when that is needed it
belongs in versioned YAML (non-negotiable #2), not in this module.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable


def skill_frequency(member_skills: Iterable[Iterable[str]]) -> list[tuple[str, int]]:
    """``[(skill, members_requiring_it), ...]`` over a cluster's members,
    most-common first (ties broken alphabetically). Each member counts a skill
    at most once."""
    counter: Counter[str] = Counter()
    for skills in member_skills:
        counter.update(set(skills))
    return sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))

"""Org-unit rollup (Track E / MVP-2) — resolving a unit to the roles inside it.

**A unit is not a family, and this is the resolver that difference required.**
``functional_families`` resolves membership from SFU's own classification codes in
source FILENAMES. A vice-presidency has no classification code, so a unit resolves on
``department`` instead. MEASURED: filtering ``department`` on VPFA's own name returns
**2 roles against a ~55+ portfolio**, because a vice-presidency is never the string
written on a JD — the whole reason a rollup exists rather than a filter.

🔴 **THREE NUMBERS, ALWAYS.** A unit page reports roles **in** the unit, roles **not**
in it, and roles whose **department is unrecorded** — measured 2026-09-09 at **677 of
2,496 (27.1%)**. The IT collection shipped without a could-not-evaluate bucket and
reported a confident number over a population it could not see; doing that again on a
surface a vice-president reads is the failure this module is shaped to prevent. A
rollup that cannot say "I cannot tell" is not honest, it is just quiet.

🔴 **MEMBERSHIP IS AN EXACT LIST, NEVER A PATTERN.** See ``org_units.yaml``. Matching
the phrase ``IT Services`` would claim ``Science - IT Services`` for ITS whether or not
it is a faculty's own IT — the term-list failure this repo has had four times. Anything
unassigned is REPORTED as a candidate, never guessed into a unit.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.jd_bank.db.models import CanonicalJD, CanonicalStatus
from src.jd_bank.library.models import UnitCandidate, UnitRollup
from src.jd_core.rules import OrgUnit, Rules, get_rules

#: Unicode dashes that mean the same thing as ``-`` in a department name. The archive
#: uses en/em dashes and a non-breaking hyphen interchangeably within the SAME unit
#: (``Facilities Management – SFU Surrey`` beside ``IT Services - Infrastructure``).
_DASHES = dict.fromkeys(map(ord, "‐‑‒–—―−"), "-")

_WS = re.compile(r"\s+")


def normalize_department(value: str | None) -> str:
    """A department string reduced to its comparable form.

    The MECHANICAL half of the alias problem, and deliberately only that half:
    case-folding, ``&`` -> ``and``, unicode dashes -> ``-``, collapsed whitespace and
    stripped trailing punctuation. ``Safety & Risk Services`` and ``Safety and Risk
    Services`` are the same unit by SPELLING, which is a rule; deciding that
    ``IT Services, Application Services`` and ``Application Services, IT Services`` are
    the same team is a JUDGEMENT, so word order and separators are left alone and both
    spellings are listed in the rulebook.
    """
    if not value:
        return ""
    text = unicodedata.normalize("NFKC", value).translate(_DASHES)
    text = text.replace("&", " and ")
    text = _WS.sub(" ", text).strip().casefold()
    return text.strip(" .,;:-/")


def unit_departments(unit_key: str, rules: Rules) -> frozenset[str]:
    """Every normalised department in ``unit_key`` INCLUDING its children's.

    A child's roles are the parent's roles — that is what "rolls up into" means, and
    Facilities Services rolling up into VPFA is the case this was built for. The loader
    has already refused a cycle, so this recursion terminates.
    """
    units = rules.org_units.units
    unit = units.get(unit_key)
    if unit is None:
        return frozenset()
    departments = {normalize_department(d) for d in unit.departments if d.strip()}
    for child in unit.children:
        departments |= unit_departments(child, rules)
    return frozenset(departments)


def _rows_by_department(
    rows: Iterable[tuple[UUID, str | None]],
) -> tuple[dict[str, list[UUID]], list[UUID]]:
    """Draft ids grouped by normalised department, plus the ids carrying none."""
    by_department: dict[str, list[UUID]] = {}
    unrecorded: list[UUID] = []
    for cluster_id, department in rows:
        key = normalize_department(department)
        if not key:
            unrecorded.append(cluster_id)
            continue
        by_department.setdefault(key, []).append(cluster_id)
    return by_department, unrecorded


async def _draft_departments(session: AsyncSession) -> list[tuple[UUID, str | None]]:
    """``(cluster_id, department)`` for every DRAFT canonical — the population a unit
    page is computed over. Read-only."""
    result = await session.execute(
        select(CanonicalJD.cluster_id, CanonicalJD.content["department"].astext).where(
            CanonicalJD.status == CanonicalStatus.DRAFT
        )
    )
    return [(cluster_id, department) for cluster_id, department in result]


async def resolve_unit(
    session: AsyncSession, unit: OrgUnit, *, unit_key: str, rules: Rules | None = None
) -> UnitRollup:
    """The rollup for one unit: its members, the two other numbers, and the candidates.

    ``candidates`` is every department string in the Bank that is assigned to NO unit at
    all, commonest first. It is the question the rulebook has not answered yet, rendered
    where somebody can answer it — the deliberate alternative to inferring a rollup and
    being confidently wrong.
    """
    active = rules if rules is not None else get_rules()
    rows = await _draft_departments(session)
    by_department, unrecorded = _rows_by_department(rows)

    mine = unit_departments(unit_key, active)
    assigned_anywhere = {
        d for key in active.org_units.units for d in unit_departments(key, active)
    }

    members: list[UUID] = []
    for department in sorted(mine):
        members.extend(by_department.get(department, ()))

    candidates = [
        UnitCandidate(department=department, roles=len(ids))
        for department, ids in by_department.items()
        if department not in assigned_anywhere
    ]
    candidates.sort(key=lambda c: (-c.roles, c.department))

    return UnitRollup(
        label=unit.label,
        slug=unit.slug,
        in_unit=len(members),
        # The other two numbers a unit page must carry. `not_in_unit` counts roles whose
        # department IS known and belongs elsewhere; `department_unrecorded` counts the
        # ones no rollup can see. Reporting only the first is how a page reads as
        # complete while being blind to 27.1% of the Bank.
        not_in_unit=sum(len(ids) for ids in by_department.values()) - len(members),
        department_unrecorded=len(unrecorded),
        member_cluster_ids=tuple(members),
        departments=tuple(sorted(mine)),
        candidates=tuple(candidates),
    )


async def unit_for(slug: str, rules: Rules | None = None) -> tuple[str, OrgUnit] | None:
    """``(unit_key, unit)`` for a URL slug, or ``None``."""
    active = rules if rules is not None else get_rules()
    for key, unit in active.org_units.units.items():
        if unit.slug == slug:
            return key, unit
    return None


def all_units(rules: Rules | None = None) -> Sequence[tuple[str, OrgUnit]]:
    """Every configured unit, for an index page."""
    active = rules if rules is not None else get_rules()
    return tuple(active.org_units.units.items())


__all__ = [
    "all_units",
    "normalize_department",
    "resolve_unit",
    "unit_departments",
    "unit_for",
]

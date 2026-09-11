"""Scopes — the set of roles a dashboard or facet is computed over (Phase A4/A5).

**The seam that stops the second unit being a rewrite.** Every aggregation takes a
:class:`Scope` — never a family, a classification code, or a hardcoded ``IT``.

There are TWO resolvers. A classification family (``functional_families.yaml``) is
recognised by SFU's own codes in source FILENAMES; an **org unit** (``org_units.yaml``
— VPFA, into which ITS rolls up) has **no classification code at all** and resolves on
``department`` instead. The argument every query accepts was made general *before* the
second one existed, which is why adding it was configuration. See ``FINDINGS.md §5``.

The measured reason, in one line: filtering ``department`` on VPFA's own name returns
**2 roles against a ~55+ portfolio**, because a vice-presidency is never the string
written on a JD.

A scope carries two things, and the second is what makes a funnel honest:

* :attr:`Scope.cluster_ids` — the roles in it. ``None`` means the whole Bank.
* :attr:`Scope.source_filename_pattern` — how its documents are recognised in the
  archive, before any of them reached a role.

Without the second, a scoped funnel can only start from documents that already made it
into a role — which hides the very drop-off the funnel exists to show. For IT that is
469 archive documents against 422 behind a role. An org-unit scope will have no such
pattern, because ``department`` is read from a parse rather than a filename, and the
funnel degrades honestly instead of inventing a number.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.jd_bank.library.families import (
    _classification_regex,
    family_for,
    resolve_members,
)
from src.jd_bank.library.units import resolve_unit, unit_for
from src.jd_core.rules import Rules


@dataclass(frozen=True)
class Scope:
    """A named set of roles. ``cluster_ids is None`` means the whole Bank."""

    key: str
    label: str
    cluster_ids: frozenset[UUID] | None = None
    #: Postgres regex recognising this scope's documents by FILENAME, when the scope has
    #: an archive-side definition at all. ``None`` for scopes that do not — an org unit
    #: is identified from parsed content, never from a filename.
    source_filename_pattern: str | None = None

    @property
    def is_whole_bank(self) -> bool:
        return self.cluster_ids is None


#: The unscoped view — every role in the Bank. The default everywhere.
WHOLE_BANK = Scope(key="all", label="The whole Bank")


async def scope_for(
    session: AsyncSession, key: str | None, *, rules: Rules | None = None
) -> Scope | None:
    """The scope a request names, or :data:`WHOLE_BANK` for ``None`` / ``"all"``.

    Returns ``None`` for a key that names nothing, so the caller renders a 404. A
    mistyped scope silently falling back to the whole Bank would show all 2,493 roles
    under a unit's name, which is worse than an error page.
    """
    if key is None or key == WHOLE_BANK.key:
        return WHOLE_BANK
    family = family_for(key, rules)
    if family is not None:
        return Scope(
            key=family.slug,
            label=family.label,
            cluster_ids=await resolve_members(session, family),
            source_filename_pattern=_classification_regex(family),
        )

    # An ORG UNIT (Track E) — the second resolver this seam was built for, and the one
    # this module's docstring predicted. A unit has no classification code, so it
    # resolves on `department` instead.
    #
    # 🔴 `source_filename_pattern` IS NONE, AND THAT IS THE HONEST ANSWER, NOT AN
    # OMISSION. The pattern exists so a scoped funnel can start from the ARCHIVE — the
    # documents that never reached a role — and `department` is read from a parse, not
    # from a filename, so no pattern can recognise a unit's documents before they are
    # parsed. Inventing one would fabricate the very drop-off the funnel exists to show.
    # The funnel degrades to "roles onward" for a unit and says so, which is what this
    # field being optional is for.
    found = await unit_for(key, rules)
    if found is None:
        return None
    unit_key, unit = found
    rollup = await resolve_unit(session, unit, unit_key=unit_key, rules=rules)
    return Scope(
        key=unit.slug,
        label=unit.label,
        cluster_ids=frozenset(rollup.member_cluster_ids),
        source_filename_pattern=None,
    )

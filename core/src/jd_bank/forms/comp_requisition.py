"""Build a :class:`~src.jd_export.comp_requisition.CompReqPrefill` from a current role.

Read-only. Reads ONLY what the Bank holds for the role's CURRENT canonical version:

* ``title`` / ``department`` / ``employee_group`` from the canonical content;
* the **position numbers** from the member source documents' FILENAMES, with the
  rulebook's ``segmentation.position_id_pattern`` — the join key the archive baseline
  uses (``baseline/facets.py``). The header ``position_number`` is NOT used: it is noisy
  (``Lab Coordinator``, ``Various``, ``702``) and is set on 1 of ~2,500 roles.

**Nothing is guessed.** A fact the Bank lacks stays ``None`` / empty. A role spans
several positions (2.4 on average, up to 73), so ``position_number`` is set only when
the role maps to exactly one position; choosing among several is the requester's call
(K3's picker). The Section A / B "based on" lists carry every member position;
which section applies depends on the request type, also the requester's call.
"""

from __future__ import annotations

from typing import Any, Literal, cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.jd_bank.db.models import CanonicalJD, SourceDocument
from src.jd_core.rules import get_rules
from src.jd_export.comp_requisition import CompReqPrefill, load_field_map


def _clean(value: Any) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


async def prefill_from_role(session: AsyncSession, role_id: UUID) -> CompReqPrefill:
    """The prefill for role (cluster) ``role_id``; ``LookupError`` if it has none."""
    current = (
        await session.execute(
            select(CanonicalJD)
            .where(CanonicalJD.cluster_id == role_id)
            .order_by(CanonicalJD.version.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if current is None:
        raise LookupError(f"no canonical role for cluster {role_id}")

    content = current.content or {}
    member_ids = [
        UUID(str(entry["source_id"]))
        for entry in (current.source_document_ids or [])
        if isinstance(entry, dict) and entry.get("source_id")
    ]
    filenames: list[str] = []
    if member_ids:
        filenames = [
            name
            for name in (
                await session.execute(
                    select(SourceDocument.filename).where(
                        SourceDocument.id.in_(member_ids)
                    )
                )
            ).scalars()
            if name
        ]

    pattern = get_rules().segmentation.position_id_pattern
    found = {pid for name in filenames for pid in pattern.findall(name)}
    positions = tuple(sorted(found))

    group_code = (_clean(content.get("employee_group")) or "").lower()
    group = load_field_map().employee_group_options.get(group_code)

    return CompReqPrefill(
        position_number=positions[0] if len(positions) == 1 else None,
        position_title=_clean(content.get("title")),
        department=_clean(content.get("department")),
        based_on_positions_a=positions,
        based_on_positions_b=positions,
        jd_in_word_attached=True,
        employee_group=cast(Literal["APSA", "APEX"] | None, group),
    )

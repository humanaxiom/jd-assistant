"""Build a :class:`~src.jd_export.comp_requisition.CompReqPrefill` from a current role.

Read-only. Reads ONLY what the Bank holds for the role's CURRENT canonical version:

* ``title`` / ``department`` / ``employee_group`` from the canonical content;
* the **position numbers** from the member source documents' FILENAMES, with the
  rulebook's ``segmentation.position_id_pattern`` — the join key the archive baseline
  uses (``baseline/facets.py``). The header ``position_number`` is NOT used: it is noisy
  (``Lab Coordinator``, ``Various``, ``702``) and is set on 1 of ~2,500 roles.

**What the Bank cannot know, it does not assert.**

* *Request type.* The Bank does not know which of the form's sections the requester is
  filling, so ``request_type=None`` (the default) fills NO position number and NO
  "based on" list; every position the role holds is offered on
  ``candidate_positions`` (never written to the PDF) for K3's picker. Given a type:
  ``new_based_on_existing`` fills Section A's list only and leaves ``Position #`` empty
  (the form says N/A if new); ``reevaluation`` fills Section B's list and
  ``Position #``;
  ``editorial`` / ``additional_duties`` / ``other_changes`` fill ``Position #`` only.
* *A single position.* A role spans several positions (2.4 on average, up to 73).
  ``position_number`` is set only when the role maps to exactly one position AND every
  member file names a position the pattern can read. The pattern reads only the PADDED
  ``0NNNNNNN`` form: **508 archive files lead with an UNPADDED id** (e.g.
  ``61,_30785,_208,_975_JDFN_APSA_20211117.docx``) and 993 carry none. A role with such
  a member may hold a position we cannot see, so it is flagged
  ``positions_incomplete=True`` and gets no ``position_number`` — it is never presented
  as a single-position role.
* *The Word attachment.* ``jd_in_word_attached`` is False unless the caller says it is
  bundling the .docx; the Bank renders that file but does not know it is attached.
* *The caller's pick (K3).* ``position_number=`` names the ONE position the form is
  for. It must be one of ``candidate_positions`` (``ValueError`` otherwise — the
  picker only offers those, so anything else is a tampered form), it is written
  only for the position-bearing request types (B–E), and for Section A it is
  ignored: the form says *N/A if new*.

A fact the Bank lacks stays ``None`` / empty.
"""

from __future__ import annotations

from typing import Any, Literal, cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.jd_bank.db.models import CanonicalJD, SourceDocument
from src.jd_core.rules import get_rules
from src.jd_export.comp_requisition import CompReqPrefill, load_field_map

#: The form's request types (A-E). ``new_based_on_existing`` is A with a source
#: position; a brand-new position based on nothing needs nothing from the Bank.
RequestType = Literal[
    "new_based_on_existing",
    "reevaluation",
    "editorial",
    "additional_duties",
    "other_changes",
]

#: The form's sections, in the order they appear on it, as a person reads them.
#: One table shared by the picker page and whatever else offers the choice.
REQUEST_TYPE_LABELS: dict[RequestType, str] = {
    "new_based_on_existing": "A — New position, based on an existing one",
    "reevaluation": "B — Re-evaluation of an existing position",
    "editorial": "C — Editorial changes",
    "additional_duties": "D — Additional duties (temporary)",
    "other_changes": "E — Other changes",
}

#: The request types whose section carries the position's own number.
_POSITION_BEARING: frozenset[str] = frozenset(
    {"reevaluation", "editorial", "additional_duties", "other_changes"}
)


def _clean(value: Any) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


async def prefill_from_role(
    session: AsyncSession,
    role_id: UUID,
    request_type: RequestType | None = None,
    *,
    jd_in_word_attached: bool = False,
    position_number: str | None = None,
) -> CompReqPrefill:
    """The prefill for role (cluster) ``role_id``; ``LookupError`` if it has none.

    ``position_number`` is the caller's pick among the role's positions (K3);
    ``ValueError`` if the role does not hold it.
    """
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
    member_ids = {
        UUID(str(entry["source_id"]))
        for entry in (current.source_document_ids or [])
        if isinstance(entry, dict) and entry.get("source_id")
    }
    names: dict[UUID, str | None] = {}
    if member_ids:
        names = {
            doc_id: name
            for doc_id, name in (
                await session.execute(
                    select(SourceDocument.id, SourceDocument.filename).where(
                        SourceDocument.id.in_(member_ids)
                    )
                )
            ).all()
        }

    pattern = get_rules().segmentation.position_id_pattern
    found: set[str] = set()
    incomplete = False
    for member in member_ids:
        ids = pattern.findall(names.get(member) or "")
        if not ids:
            incomplete = (
                True  # unpadded, absent, or no filename: a position we can't see
            )
        found.update(ids)
    positions = tuple(sorted(found))
    if position_number is not None and position_number not in positions:
        raise ValueError(
            f"position {position_number} is not one this role holds "
            f"({', '.join(positions) or 'none readable'})"
        )
    single = positions[0] if len(positions) == 1 and not incomplete else None
    chosen = position_number or single

    group_code = (_clean(content.get("employee_group")) or "").lower()
    group = load_field_map().employee_group_options.get(group_code)

    return CompReqPrefill(
        position_number=chosen if request_type in _POSITION_BEARING else None,
        position_title=_clean(content.get("title")),
        department=_clean(content.get("department")),
        based_on_positions_a=(
            positions if request_type == "new_based_on_existing" else ()
        ),
        based_on_positions_b=positions if request_type == "reevaluation" else (),
        jd_in_word_attached=jd_in_word_attached,
        employee_group=cast(Literal["APSA", "APEX"] | None, group),
        candidate_positions=positions,
        positions_incomplete=incomplete,
    )

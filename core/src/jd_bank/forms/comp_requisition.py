"""Build a :class:`~src.jd_export.comp_requisition.CompReqPrefill` from a current role.

Read-only. Reads what the Bank holds for the role's CURRENT canonical version:

* ``title`` / ``department`` / ``employee_group`` from the canonical content — and,
  where the canonical lacks a fact the rulebook lists
  (``comp_requisition.fill_from_sources_when_role_lacks``, HR-309), from the member
  source documents' CURRENT parse, when every source stating it agrees
  (``sources_must_agree``, HR-310). What came from the sources is named on
  ``filled_from_sources`` so the page can say so.
* the **position numbers** from the member source documents' FILENAMES, with the
  rulebook's ``segmentation.position_id_pattern`` — the join key the archive baseline
  uses (``baseline/facets.py``). The header ``position_number`` is NOT used: it is noisy
  (``Lab Coordinator``, ``Various``, ``702``) and is set on 1 of ~2,500 roles.
* the sources' **grades**, as ``reference_grades`` for the page only (HR-314). A grade
  is never written: proposing one is the evaluator's job (ADR-007).

**What the Bank cannot know, it does not assert.**

* *Request type.* The Bank does not know which of the form's sections the requester is
  filling, so ``request_type=None`` (the default) fills NO position number and NO
  "based on" list; every position the role holds is offered on
  ``candidate_positions`` (never written to the PDF) for K3's picker. Given a type:
  ``new_based_on_existing`` fills Section A's list only and leaves ``Position #`` empty
  (the form says N/A if new); ``reevaluation`` fills Section B's list and
  ``Position #``;
  ``editorial`` / ``additional_duties`` / ``other_changes`` fill ``Position #`` only.
  The chosen type's box is ticked (HR-311), and a written list ticks that section's
  "based off of an existing position? Yes" (HR-312).
* *A single position.* A role spans several positions (2.4 on average, up to 73).
  ``position_number`` is set only when the role maps to exactly one position AND every
  member file names a position the pattern can read. The pattern reads only the PADDED
  ``0NNNNNNN`` form: **508 archive files lead with an UNPADDED id** (e.g.
  ``61,_30785,_208,_975_JDFN_APSA_20211117.docx``) and 993 carry none. A role with such
  a member may hold a position we cannot see, so it is flagged
  ``positions_incomplete=True`` and gets no ``position_number`` — it is never presented
  as a single-position role.
* *The caller's pick (K3).* ``position_number=`` names the ONE position the form is
  for. It must be one of ``candidate_positions`` (``ValueError`` otherwise — the
  picker only offers those, so anything else is a tampered form), it is written
  only for the position-bearing request types (B–E), and for Section A it is
  ignored: the form says *N/A if new*.
* *The contact.* ``contact_name`` / ``contact_email`` are the REQUESTER — the signed-in
  person — passed in by the caller and written only while
  ``contact_from_requester`` is on (HR-313). Never an incumbent.
* *The Word attachment.* ``jd_in_word_attached`` is False unless the caller says it is
  bundling the .docx; the Bank renders that file but does not know it is attached.

A fact the Bank lacks stays ``None`` / empty.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Literal, cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.jd_bank.db.models import CanonicalJD, ParsedJDRow, SourceDocument
from src.jd_core.parser import PARSER_VERSION
from src.jd_core.rules import get_rules
from src.jd_export.comp_requisition import CompReqPrefill, RequestType, load_field_map

__all__ = ["REQUEST_TYPE_LABELS", "RequestType", "prefill_from_role"]

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


def _agreed(values: list[str], *, must_agree: bool) -> str | None:
    """One value the sources agree on: unanimous (case-insensitive) when
    ``must_agree``, else the most frequent. ``None`` when nothing, or no agreement."""
    if not values:
        return None
    by_key = Counter(v.casefold() for v in values)
    if must_agree and len(by_key) > 1:
        return None
    key = by_key.most_common(1)[0][0]
    spellings = [v for v in values if v.casefold() == key]
    # Deterministic whatever order the rows came back in: the most frequent exact
    # spelling, then the one with the most capitals (a title-cased name over a
    # lower-cased copy), then alphabetical.
    return max(
        spellings,
        key=lambda v: (spellings.count(v), sum(c.isupper() for c in v), v),
    )


async def prefill_from_role(
    session: AsyncSession,
    role_id: UUID,
    request_type: RequestType | None = None,
    *,
    jd_in_word_attached: bool = False,
    position_number: str | None = None,
    contact_name: str | None = None,
    contact_email: str | None = None,
) -> CompReqPrefill:
    """The prefill for role (cluster) ``role_id``; ``LookupError`` if it has none.

    ``position_number`` is the caller's pick among the role's positions (K3);
    ``ValueError`` if the role does not hold it. ``contact_*`` is the requester.
    """
    policy = get_rules().comp_requisition
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
    parsed: list[dict[str, Any]] = []
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
        parsed = [
            row or {}
            for row in (
                await session.execute(
                    select(ParsedJDRow.parsed).where(
                        ParsedJDRow.source_document_id.in_(member_ids),
                        ParsedJDRow.parser_version == PARSER_VERSION,
                    )
                )
            ).scalars()
        ]

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

    # The text facts: the role first; the sources only where the role is silent and
    # the rulebook allows it (HR-309 / HR-310).
    facts: dict[str, str | None] = {
        "department": _clean(content.get("department")),
        "employee_group": _clean(content.get("employee_group")),
    }
    from_sources: list[str] = []
    for fact in policy.fill_from_sources_when_role_lacks:
        if facts[fact] is not None:
            continue
        stated = [v for v in (_clean(p.get(fact)) for p in parsed) if v is not None]
        agreed = _agreed(stated, must_agree=policy.sources_must_agree)
        if agreed is not None:
            facts[fact] = agreed
            from_sources.append(fact)

    group_code = (facts["employee_group"] or "").lower()
    group = load_field_map().employee_group_options.get(group_code)

    grades: tuple[str, ...] = ()
    if policy.show_source_grades_for_reference:
        seen = [v for v in (_clean(p.get("grade")) for p in parsed) if v is not None]
        own = _clean(content.get("grade"))
        grades = tuple(sorted(set(seen) | ({own} if own else set())))

    list_a = positions if request_type == "new_based_on_existing" else ()
    list_b = positions if request_type == "reevaluation" else ()
    contact_on = policy.contact_from_requester
    return CompReqPrefill(
        position_number=chosen if request_type in _POSITION_BEARING else None,
        position_title=_clean(content.get("title")),
        department=facts["department"],
        based_on_positions_a=list_a,
        based_on_positions_b=list_b,
        jd_in_word_attached=jd_in_word_attached,
        employee_group=cast(Literal["APSA", "APEX"] | None, group),
        contact_name=_clean(contact_name) if contact_on else None,
        contact_email=_clean(contact_email) if contact_on else None,
        request_type=request_type if policy.tick_request_type else None,
        based_on_existing_a=policy.tick_based_on_existing and bool(list_a),
        based_on_existing_b=policy.tick_based_on_existing and bool(list_b),
        candidate_positions=positions,
        positions_incomplete=incomplete,
        reference_grades=grades,
        filled_from_sources=tuple(from_sources),
    )

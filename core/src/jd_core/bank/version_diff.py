"""JD-to-JD version diff (draft vs last-approved) — pure, deterministic.

:func:`build_version_diff` compares two :class:`~src.jd_core.models.parsed_jd.
SFUJobDescription` snapshots section by section and reports, per template section,
the before/after text and whether it changed. It answers the single most-asked
reclassification question for a reviewer: *what changed since this role was last
approved?*

**Complete, not re-parseable.** Unlike
:func:`~src.jd_core.bank.render.render_sfu_jd_text` (whose job is a re-parseable
document, so it deliberately drops the presence booleans and ``position_number``), this
serialization covers EVERY field — a footer toggled off or a grade cleared is exactly
the kind of change a reviewer must see. It is for human reading in a diff, never fed
back to the parser.

**Pure** (NN #2 / ADR-006): no I/O, no DB, no LLM; imports no ``jd_bank``.
**Descriptive, never a decision** (NN #1): it carries no approval/score field — it
reports what differs and judges nothing.
"""

from __future__ import annotations

from collections.abc import Callable

from pydantic import BaseModel, ConfigDict

from src.jd_core.models.parsed_jd import SFUJobDescription


class SectionChange(BaseModel):
    """One template section's before/after text and whether it differs."""

    model_config = ConfigDict(frozen=True)

    section: str
    before: str
    after: str
    changed: bool


class VersionDiff(BaseModel):
    """A section-by-section diff of two JD snapshots. ``any_changes`` is False when the
    two are identical across every serialized section."""

    model_config = ConfigDict(frozen=True)

    sections: tuple[SectionChange, ...]
    any_changes: bool


def _yn(present: bool) -> str:
    return "yes" if present else "no"


def _title(jd: SFUJobDescription) -> str:
    return jd.title


def _identification(jd: SFUJobDescription) -> str:
    return "\n".join(
        [
            f"Department: {jd.department or ''}",
            f"Grade: {jd.grade or ''}",
            f"Employee group: {jd.employee_group or ''}",
            f"Position number: {jd.position_number or ''}",
        ]
    )


def _boilerplate(jd: SFUJobDescription) -> str:
    return "\n".join(
        [
            f"About SFU present: {_yn(jd.about_sfu_present)}",
            f"Territorial acknowledgement present: "
            f"{_yn(jd.territorial_acknowledgement_present)}",
            f"Employment-equity footer present: {_yn(jd.employment_equity_present)}",
        ]
    )


def _position_summary(jd: SFUJobDescription) -> str:
    return jd.position_summary or ""


def _duties(jd: SFUJobDescription) -> str:
    lines: list[str] = []
    for d in jd.duties:
        head = (
            f"{d.action_verb} {d.statement}".strip() if d.action_verb else d.statement
        )
        extras: list[str] = []
        if d.how_why:
            extras.append("; ".join(d.how_why))
        if d.frequency:
            extras.append(f"freq={d.frequency}")
        suffix = f" ({' | '.join(extras)})" if extras else ""
        lines.append(f"- {head}{suffix}")
    return "\n".join(lines)


def _bullets(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items)


def _relationships(jd: SFUJobDescription) -> str:
    rel = jd.relationships
    if rel is None:
        return ""
    lines: list[str] = []
    if rel.supervisory:
        lines.append(f"Supervisory: {rel.supervisory}")
    lines += [f"Internal: {c}" for c in rel.internal]
    lines += [f"External: {c}" for c in rel.external]
    return "\n".join(lines)


def _qualifications(jd: SFUJobDescription) -> str:
    return "\n".join(
        f"- [{q.kind}] {(q.modifier + ' ') if q.modifier else ''}{q.text}"
        for q in jd.qualifications
    )


#: The template sections, in order, each with a COMPLETE text serialization for diffing
#: (every field — including the presence booleans render_sfu_jd_text drops).
_SECTIONS: tuple[tuple[str, Callable[[SFUJobDescription], str]], ...] = (
    ("Title", _title),
    ("Identification", _identification),
    ("SFU boilerplate", _boilerplate),
    ("Position Summary", _position_summary),
    ("Duties & Responsibilities", _duties),
    ("Impact of Decision Making", lambda jd: _bullets(jd.decision_making)),
    ("Problem Solving", lambda jd: _bullets(jd.problem_solving)),
    ("Relationships", _relationships),
    ("Qualifications", _qualifications),
    ("Additional context", lambda jd: jd.additional_context or ""),
)


def build_version_diff(
    previous: SFUJobDescription, current: SFUJobDescription
) -> VersionDiff:
    """Section-by-section diff of ``previous`` (e.g. the last-approved JD) vs
    ``current`` (the draft under review). Pure and deterministic: the same pair always
    yields the same diff. A section whose serialized text is unchanged is reported with
    ``changed=False`` so the UI can collapse it."""
    changes = [
        SectionChange(
            section=label,
            before=(before := serialize(previous)),
            after=(after := serialize(current)),
            changed=before != after,
        )
        for label, serialize in _SECTIONS
    ]
    return VersionDiff(
        sections=tuple(changes),
        any_changes=any(change.changed for change in changes),
    )

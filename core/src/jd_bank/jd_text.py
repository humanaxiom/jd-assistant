"""The one shared JD flattener — a single home for turning a structured
:class:`~src.jd_core.models.parsed_jd.SFUJobDescription` into the flat text blob its two
LLM consumers reason over.

**Why one home.** Phase 4.2a's must-fix was that a section dropped from the flattener is
invisible to whatever reads the flattened text — the rewrite feeds it to the model AND
gives it to the validator (the oracle), so an omitted section inflates the score; the
4.2b audit uses it as BOTH the ``jd_text`` prompt slot AND the anti-fabrication scrub's
haystack, so an omitted section would make a quote the model legitimately copied
un-findable and drop a real finding. Those two haystacks must never silently diverge, so
the flattener lives here and both :mod:`src.jd_bank.rewrite.harmonize` and
:mod:`src.jd_bank.quality.audit` import THIS function — there is only one.

This module imports only ``jd_core`` models, never the reverse (the layering ratchet).
"""

from __future__ import annotations

from collections.abc import Callable

from src.jd_core.models.parsed_jd import SFUDuty, SFUJobDescription


def _plain_duty(duty: SFUDuty) -> list[str]:
    return [duty.statement, *duty.how_why]


def _outlined_duty(duty: SFUDuty) -> list[str]:
    return [f"- {duty.statement}", *(f"    - {clause}" for clause in duty.how_why)]


def _parts(jd: SFUJobDescription, duty_lines: Callable[[SFUDuty], list[str]]) -> str:
    parts: list[str] = [jd.title, jd.position_summary or ""]
    for duty in jd.duties:
        parts.extend(duty_lines(duty))
    parts.extend(jd.decision_making)
    parts.extend(jd.problem_solving)
    if jd.relationships is not None:
        if jd.relationships.supervisory:
            parts.append(jd.relationships.supervisory)
        parts.extend(jd.relationships.internal)
        parts.extend(jd.relationships.external)
    parts.extend(qual.text for qual in jd.qualifications)
    if jd.additional_context:
        parts.append(jd.additional_context)
    return "\n".join(part for part in parts if part)


def flatten_jd(jd: SFUJobDescription) -> str:
    """Flatten a JD into a text blob covering EVERY content section the model may write.

    Mirrors hris ``_canonical_text`` but includes every free-text section the SFU schema
    lets a model populate — Relationships included (the LLM can write ``supervisory`` /
    ``internal`` / ``external`` prose, and a coded term there must still be scannable /
    quotable). A section omitted here is invisible to whatever reads the flattened text:
    the rewrite's validator scan (score inflation) and the audit's evidence scrub
    (a real finding silently dropped). Order is template order; empty parts are skipped.
    """
    return _parts(jd, _plain_duty)


def outline_jd(jd: SFUJobDescription) -> str:
    """:func:`flatten_jd` with each duty's SHAPE kept: the duty on a ``- `` line, each
    how/why clause indented under it. Same sections, same order, same words.

    For the rewrite prompt (``jd_harmonize_v3``): parser v9 fills ``how_why`` (owner
    ruling 2026-10-20, Q1), and a flat blob would hand the model a headline and its
    clauses as indistinguishable lines — it could not keep a structure it cannot see.
    Scanning and evidence keep using :func:`flatten_jd`'s plain text."""
    return _parts(jd, _outlined_duty)

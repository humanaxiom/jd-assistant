"""Render a structured SFU JD back to a plain-text job description.

Ported from hris ``packages/pipeline/src/pipeline/bank/render.py`` (reuse-map
#12): the inverse of extraction — the sections of an
:class:`~src.jd_core.models.parsed_jd.SFUJobDescription`, in the SFU template's
order, empty ones dropped. Pure + deterministic. Feeds the composer's "start a
new JD *from* a canonical role" flow.

**The headings are not ours.** They are read from
:data:`~src.jd_core.parser.headings.CANONICAL_HEADING` and emitted in
:data:`~src.jd_core.parser.headings.SECTION_ORDER` — the same versioned data the
deterministic parser matches against (CLAUDE.md #2: one rulebook fact, one home).
This module therefore cannot invent a heading the parser cannot read. It could
before: hris re-parsed its own output with an LLM, so its
``PROBLEM SOLVING & LEVEL OF SUPERVISION`` was harmless there; here the parser is
a regex that accepts only ``AND``, so that heading did not match and re-parsing a
rendered JD silently swallowed the whole Problem Solving section. The port was
faithful; the destination was not the same.

**What this output is NOT (yet).** Round-tripping ``render_sfu_jd_text`` through
:func:`~src.jd_core.parser.parse_jd` recovers every section it *writes* (the
suite proves it, section by section), but it is still **lossy on the document as
a whole**. No caller may assume a clean round trip:

* 8 of the 10 template sections are emitted. ``about_sfu`` and the territorial-
  acknowledgement / employment-equity ``footer`` are presence *booleans* on the
  model (the boilerplate text is not carried), so they cannot be rendered — and a
  re-parsed rendering therefore trips ``SFU-COMP-ABOUT`` and the footer gates.
* Identification is emitted as a human-readable line (``ITS · Grade B80 · APSA``),
  not as the ``Department:`` / ``Grade:`` labelled fields the segmenter reads — so
  ``department``, ``grade`` and ``position_number`` do not survive a round trip.
  (``employee_group`` does: the segmenter token-scans the identification block, so
  it still finds ``APSA``.)
* Two labels the segmenter does not strip come back *inside* the value:
  ``relationships.supervisory`` keeps its ``Supervisory: `` prefix, and a
  qualification's text keeps the ``[skill] advanced `` tag the renderer wrote. So
  render→parse is faithful, but parse→render→parse→render **compounds** those
  prefixes. Do not build a re-render loop on this until it is fixed.

Closing that gap (a template-faithful, re-parseable identification + footer, and
a label-stripping fix in the segmenter, both under a round-trip fixture) is
tracked in HANDOFF's backlog. It is deliberately NOT done here, where the job is
the port.

Not to be confused with ``src/jd_core/rules/render.py``, which renders the HR
decision register.
"""

from __future__ import annotations

from collections.abc import Callable

from src.jd_core.models.parsed_jd import SFUJobDescription
from src.jd_core.parser.headings import (
    CANONICAL_HEADING,
    CANONICAL_REL_LABEL,
    SECTION_ORDER,
    SectionKey,
)


def _heading(section: SectionKey) -> str:
    return CANONICAL_HEADING[section]


def _identification(jd: SFUJobDescription) -> str | None:
    """The identification line — deliberately *un*headed: it reads as a subtitle
    under the job title. (See the round-trip caveat in the module docstring.)"""
    bits = [
        jd.department,
        f"Grade {jd.grade}" if jd.grade else None,
        jd.employee_group.upper() if jd.employee_group else None,
    ]
    line = " · ".join(b for b in bits if b)
    return line or None


def _position_summary(jd: SFUJobDescription) -> str | None:
    if not jd.position_summary:
        return None
    return f"{_heading(SectionKey.POSITION_SUMMARY)}\n{jd.position_summary}"


def _duties(jd: SFUJobDescription) -> str | None:
    if not jd.duties:
        return None
    lines = []
    for d in jd.duties:
        head = (
            f"{d.action_verb} {d.statement}".strip() if d.action_verb else d.statement
        )
        how = f" ({'; '.join(d.how_why)})" if d.how_why else ""
        lines.append(f"- {head}{how}")
    return f"{_heading(SectionKey.DUTIES)}\n" + "\n".join(lines)


def _bullets(section: SectionKey, items: list[str]) -> str | None:
    if not items:
        return None
    return f"{_heading(section)}\n" + "\n".join(f"- {x}" for x in items)


def _decision_making(jd: SFUJobDescription) -> str | None:
    return _bullets(SectionKey.DECISION_MAKING, jd.decision_making)


def _problem_solving(jd: SFUJobDescription) -> str | None:
    return _bullets(SectionKey.PROBLEM_SOLVING, jd.problem_solving)


def _relationships(jd: SFUJobDescription) -> str | None:
    """Sub-labels come from :data:`CANONICAL_REL_LABEL`, and each connection is
    its own line — because that is what the segmenter reads back. hris joined the
    connections with commas under an ``Internal:`` label; the segmenter recognises
    neither, so every connection was refiled as supervisory prose on re-parse."""
    rel = jd.relationships
    if rel is None:
        return None
    lines: list[str] = []
    if rel.supervisory:
        lines.append(f"{CANONICAL_REL_LABEL['supervisory']}: {rel.supervisory}")
    lines += [f"{CANONICAL_REL_LABEL['internal']}: {x}" for x in rel.internal]
    lines += [f"{CANONICAL_REL_LABEL['external']}: {x}" for x in rel.external]
    if not lines:
        return None
    body = "\n".join(lines)
    return f"{_heading(SectionKey.RELATIONSHIPS)}\n{body}"


def _qualifications(jd: SFUJobDescription) -> str | None:
    if not jd.qualifications:
        return None
    lines = [
        f"- [{q.kind}] {(q.modifier + ' ') if q.modifier else ''}{q.text}"
        for q in jd.qualifications
    ]
    return f"{_heading(SectionKey.QUALIFICATIONS)}\n" + "\n".join(lines)


def _additional_context(jd: SFUJobDescription) -> str | None:
    if not jd.additional_context:
        return None
    return f"{_heading(SectionKey.ADDITIONAL_CONTEXT)}\n{jd.additional_context}"


#: How each template section is rendered. A section absent from this map is one
#: the model cannot render (``about_sfu`` / ``footer`` carry presence booleans,
#: not text — see the module docstring). Order comes from ``SECTION_ORDER``, never
#: from this dict.
_RENDERERS: dict[SectionKey, Callable[[SFUJobDescription], str | None]] = {
    SectionKey.IDENTIFICATION: _identification,
    SectionKey.POSITION_SUMMARY: _position_summary,
    SectionKey.DUTIES: _duties,
    SectionKey.DECISION_MAKING: _decision_making,
    SectionKey.PROBLEM_SOLVING: _problem_solving,
    SectionKey.RELATIONSHIPS: _relationships,
    SectionKey.QUALIFICATIONS: _qualifications,
    SectionKey.ADDITIONAL_CONTEXT: _additional_context,
}


def render_sfu_jd_text(jd: SFUJobDescription) -> str:
    """Compose an ``SFUJobDescription`` into a readable JD document in the SFU
    template's section order (:data:`SECTION_ORDER`). Empty sections are omitted;
    the title always leads. Lossy on re-parse — see the module docstring."""
    blocks: list[str] = [jd.title]
    for section in SECTION_ORDER:
        render = _RENDERERS.get(section)
        if render is None:
            continue  # about_sfu / footer: boilerplate the model does not carry
        block = render(jd)
        if block:
            blocks.append(block)
    return "\n\n".join(blocks)

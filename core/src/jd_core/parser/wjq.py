"""Deterministic segmenter for SFU's CUPE / Weighted Job Questionnaire (WJQ) Custom
template — the SECOND document template in the archive (Phase 3.4).

The base segmenter (:mod:`src.jd_core.parser.segmenter` + :mod:`.headings`) knows only
the APSA/APEX/POLY "JDFN" template. WJQ is a *different form* — a 14-section
point-factor questionnaire (CUPE 3338) — and reads as ~zero content through the JDFN
path. This module is dispatched by :func:`src.jd_core.parser.segmenter.parse_jd` when a
WJQ marker is present; the JDFN path is left byte-identical. MEASURED with the shipped
two-tier detection (:func:`is_wjq`): ~29% of the archive routes here; a bare union
mention in a JDFN duty does NOT (that is what the ``marker_corroborating`` tier guards —
see ``wjq.yaml``).

**Everything policy-shaped is data** (CLAUDE.md non-negotiable #2): the 14 section
headings, the POSITION IDENTIFICATION labels, the ``(D)/(W)/(M)/(S)`` frequency markers,
the qualification-block cues and the template-instruction ignore-list all live in
``wjq.yaml`` (:class:`src.jd_core.rules.Wjq`). The 14 section *keys* are structural
(:data:`~src.jd_core.rules.WjqSection`), like the JDFN :class:`SectionKey`.

The WJQ → SFU 10-section mapping:

* **1 POSITION IDENTIFICATION** → ``title`` / ``department`` / ``position_number`` /
  ``grade`` (inline labels) + ``employee_group = "cupe"`` (from the marker).
* **2 POSITION SUMMARY** → ``position_summary`` (falls back to the prose that trails the
  identification table when the form omits the heading — MEASURED to happen).
* **3 MAJOR FUNCTIONS + 4 MINOR FUNCTIONS** → ``duties``, with ``(D)/(W)/(M)/(S)``
  stripped to :attr:`SFUDuty.frequency` (per-duty marker OR ``DAILY``/``WEEKLY`` group
  heading). The lowercase ``(s)`` mid-word (``location(s)``, present in the archive) is
  never read as a frequency — detection is anchored to a standalone uppercase token.
* **8 INTERNAL AND EXTERNAL CONTACTS** → ``relationships.internal`` / ``.external``
  (best-effort keyword split; no supervisory signal exists in this template — **this is
  lossy** and does not invent one).
* **13 QUALIFICATIONS** → ``qualifications`` (``education`` / ``experience`` / ``skill``
  / ``ability`` by block cue).
* **5,6,7,9,10,11,12 (the Hay-factor sections)** → ``additional_context`` verbatim
  (PLAIN TEXT — the checkbox glyphs are unreliable, MEASURED in 280/2,553 `.docx`
  and 0/2,473 `.doc`). This is **lossless storage**; the embedding-quality concern
  (checkbox boilerplate diluting WJQ vectors) is an explicit Phase-3.5 follow-up
  (HR-145), NOT solved here.
* **``decision_making = []`` / ``problem_solving = []``** — left EMPTY. WJQ carries no
  Hay Accountability / Problem-Solving prose; force-mapping IMPACT OF ERRORS →
  ``decision_making`` would feed :mod:`src.jd_core.bank.hay_signals` a bogus signal. The
  text is preserved in ``additional_context``.
* **14 APPROVAL AND REVIEW** → dropped (sign-off metadata: names, signatures, dates).
* ``about_sfu_present`` / footer booleans → ``False`` (WJQ has no About-SFU /
  territorial footer by template).

Robustness contract is the JDFN path's: never raises; missing/garbled sections yield
empty fields and low confidence.
"""

from __future__ import annotations

import re

from src.jd_core.models.parsed_jd import (
    SFUDuty,
    SFUEmployeeGroup,
    SFUJobDescription,
    SFUQualification,
    SFURelationships,
)
from src.jd_core.parser.classification import extract_classification
from src.jd_core.parser.headings import SectionKey
from src.jd_core.parser.segmenter import (
    _FALLBACK_TITLE,
    _MAX_BULLET,
    _MAX_DUTIES,
    _MAX_DUTY_STMT,
    _MAX_QUAL,
    _MAX_QUALS,
    _MAX_SUMMARY,
    _MAX_TITLE,
    _PERCENT_RE,
    ParseResult,
    _clean,
    _detect_era,
    _detect_modifier,
    _leading_verb,
)
from src.jd_core.rules import Wjq, WjqSection, get_rules

# ── Line / heading normalisation ─────────────────────────────────────────────

#: A leading enumeration prefix on a WJQ heading cell (``1.`` / ``13)``).
_NUM_PREFIX = re.compile(r"^\s*\d{1,2}\s*[.)]\s*")

#: Any whitespace run, for comparing a heading cell to the vocabulary.
_COLLAPSE_WS = re.compile(r"\s+")

#: The COLUMN BOUNDARY in antiword's fixed-width rendering of a table it did not
#: recognise: two or more spaces, or the end of the cell. One space is running prose and
#: must NOT count, or a duty beginning with a heading's words would be taken for the
#: heading — see :func:`_match_heading`.
_COLUMN_GAP = re.compile(r"(\s{2,}|$)")
#: Bullet markers, including antiword's ``.`` bullet for legacy ``.doc``.
_WJQ_BULLET = re.compile(r"^\s*(?:[.\-–—•*·▪‣◦]|\(?\d{1,2}[.)])\s+")
#: A standalone, UPPERCASE ``(D)/(W)/(M)/(S)`` frequency token — line-start or line-end
#: of a duty, never mid-word (so ``location(s)`` can never match: lowercase ``s`` AND no
#: preceding word boundary).
_FREQ_INLINE = re.compile(r"(?:(?<=\s)|^)\(([DWMS])\)(?=$|\s|[.;,)])")
#: A duty line that ENDS with a frequency token — the marker sits at the end of the duty
#: (with optional trailing period/spaces), so the NEXT line begins a new duty.
_ENDS_FREQ = re.compile(r"\([DWMS]\)[\s.]*$")
#: A line that ends a sentence — used only in no-bullet blocks to tell a wrapped
#: continuation (no terminal punctuation) from a complete one-line duty.
_ENDS_SENTENCE = re.compile(r"[.;!?]\s*$")

#: The SFU 10-section confidence key each populated WJQ mapping corresponds to.
_WJQ_TO_SECTIONKEY: dict[WjqSection, SectionKey] = {
    "position_identification": SectionKey.IDENTIFICATION,
    "position_summary": SectionKey.POSITION_SUMMARY,
    "major_functions": SectionKey.DUTIES,
    "minor_functions": SectionKey.DUTIES,
    "internal_external_contacts": SectionKey.RELATIONSHIPS,
    "qualifications": SectionKey.QUALIFICATIONS,
}


def is_wjq(text: str, wjq: Wjq) -> bool:
    """True when the document is a WJQ questionnaire (whole-document, case-insensitive).

    Marker-based, never filename-based (``JDFN_CUPE`` covers only ~771 files). The rule
    is TWO-TIER: the definitive title phrase (``marker_primary``) alone routes; else at
    least ``corroborating_min`` of the looser union markers must co-occur. A bare
    ``LOCAL 3338`` no longer routes — a JDFN JD that merely CITES CUPE in a duty (HR,
    labour-relations, compensation roles) stays on the JDFN path (MEASURED: 69 such
    files misrouted, 11 of them in the HR-ratified ``new``-era cohort)."""
    haystack = (text or "").lower()
    if any(term.lower() in haystack for term in wjq.marker_primary):
        return True
    hits = sum(1 for term in wjq.marker_corroborating if term.lower() in haystack)
    return hits >= wjq.corroborating_min


def _cells(line: str) -> list[str]:
    """A physical line's antiword table cells (split on ``|``), or the whole line as one
    cell for a python-docx render (no pipes). Empty cells dropped."""
    return [c for c in (_clean(part) for part in line.split("|")) if c]


def _match_heading(line: str, wjq: Wjq) -> WjqSection | None:
    """The WJQ section a line is the heading for, or ``None``.

    A heading occupies its own table cell: ``N. PHRASE``. The cell is number-peeled and
    ``(CONTINUED)``-stripped, then matched against the heading vocabulary — either
    exactly, or as a prefix followed by a COLUMN GAP (below).

    🔴 THE COLUMN GAP, AND WHY AN EXACT MATCH ALONE LOST 16% OF THE CUPE ARCHIVE.
    ``_cells`` splits on ``|``, which is how antiword renders a table it recognises. It
    renders a MULTI-COLUMN layout it does not recognise as fixed-width text with **no
    pipes at all**, so a heading and the cell to its right land on one physical line::

        ' 1. POSITION IDENTIFICATION                        For Use by Human'
        '    Resources Only'

    Cleaned, that cell is ``1. POSITION IDENTIFICATION FOR USE BY HUMAN``, which equals
    no heading phrase — so the section never opened. MEASURED 2026-08-22: **719 of 4,440
    CUPE documents (16.2%) parsed to ZERO duties**, against 2.2% on the APSA form, and
    every non-recoverable one was a legacy ``.doc``. That silence is what the rewrite
    then filled with invented duties (HR-213): 1,219 of them across 153 drafts.

    A run of **two or more spaces** is the column boundary, and that is what keeps this
    from becoming the prefix match the original docstring rightly refused: running prose
    continues after one space, so ``Level of detail required…`` still cannot be taken
    for the ``LEVEL OF DETAIL`` heading, while a heading plus a column can.

    MEASURED both directions before shipping: over the failing CUPE population **78.8%
    (197/250) gain a duties block**, and over a random sample of 300 documents that
    already parse duties, **none loses them** (97.3% byte-identical, 8 gain more).
    """
    cont = wjq.continued_marker.upper()
    # NOT `_cells`: it collapses internal whitespace, which is the very signal that
    # tells a heading's own cell from the column printed beside it.
    for raw in line.split("|"):
        upper = raw.upper().replace(cont, "").strip()
        if not upper:
            continue
        peeled = _NUM_PREFIX.sub("", upper, count=1).strip()
        for section, phrases in wjq.section_headings.items():
            for phrase in phrases:
                target = phrase.upper()
                for candidate in (peeled, upper):
                    if _COLLAPSE_WS.sub(" ", candidate) == target:
                        return section
                    rest = candidate[len(target) :]
                    if candidate.startswith(target) and _COLUMN_GAP.match(rest):
                        return section
    return None


def _segment(text: str, wjq: Wjq) -> dict[WjqSection, str]:
    """``{section: content}`` — content between a heading and the next, with a repeated
    (``(CONTINUED)``) heading concatenated onto the same section."""
    lines = text.splitlines()
    hits: list[tuple[int, WjqSection]] = []
    for i, line in enumerate(lines):
        section = _match_heading(line, wjq)
        if section is not None:
            hits.append((i, section))
    sections: dict[WjqSection, str] = {}
    for idx, (line_no, section) in enumerate(hits):
        start = line_no + 1
        end = hits[idx + 1][0] if idx + 1 < len(hits) else len(lines)
        content = "\n".join(lines[start:end]).strip()
        sections[section] = (
            f"{sections[section]}\n{content}".strip()
            if section in sections
            else content
        )
    return sections


# ── Identification ───────────────────────────────────────────────────────────


def _ordered_cells(id_text: str) -> list[str]:
    """The identification TABLE as an ordered stream of cells — antiword pipes and
    python-docx paragraph-per-cell both flatten to the same stream.

    When the render has pipes (antiword), only the pipe-bearing lines are the table; the
    prose that trails it (a summary the form omitted a heading for) is deliberately
    excluded, so an empty ``Position Number(s):`` cannot swallow the first summary
    sentence as its value."""
    lines = id_text.splitlines()
    if any("|" in line for line in lines):
        lines = [line for line in lines if "|" in line]
    cells: list[str] = []
    for line in lines:
        cells.extend(_cells(line))
    return cells


def _is_label_cell(cell: str) -> bool:
    """A label cell ends with ``:`` (both renders label their id fields this way)."""
    return cell.rstrip().endswith(":")


def _extract_label(
    cells: list[str], labels: tuple[str, ...], *, cap: int
) -> str | None:
    """The value of the FIRST matching id label in the cell stream. Works for both
    renders: antiword puts the value in the next pipe-cell, python-docx on the next
    paragraph — either way it is the cell after the label. A field left blank (the next
    cell is itself a label) yields ``None``."""
    wanted = {label.rstrip(":").strip().lower() for label in labels}
    for i, cell in enumerate(cells):
        if cell.rstrip(":").strip().lower() not in wanted:
            continue
        if i + 1 >= len(cells) or _is_label_cell(cells[i + 1]):
            return None
        value = _clean(cells[i + 1])
        return value[:cap] if value else None
    return None


def _summary_text(block: str, wjq: Wjq) -> str | None:
    """The POSITION SUMMARY section's prose, with the form's instruction line ("A
    summary of the major functions … in three or four sentences.") dropped."""
    kept = [
        line.strip()
        for line in block.replace("|", " ").splitlines()
        if line.strip() and not _is_instruction(line, wjq)
    ]
    text = _clean(" ".join(kept))
    return text[:_MAX_SUMMARY] if text else None


def _summary_fallback(id_text: str) -> str | None:
    """The prose that trails the identification table when the form omits a
    ``2. POSITION SUMMARY`` heading (MEASURED to happen): the non-table (non-pipe) lines
    of the identification block, if they add up to a real paragraph."""
    prose = " ".join(
        line.strip()
        for line in id_text.splitlines()
        if line.strip() and "|" not in line
    )
    prose = _clean(prose)
    if len(prose) < 40:
        return None
    # CAP defensively, exactly as `_summary_text` does. Without a heading the fallback
    # can grab a whole (untruncated) identification block, which routinely exceeds
    # `position_summary`'s 4000-char ceiling — MEASURED to raise ValidationError on 568
    # heading-less WJQ `.doc` files, aborting the archive re-parse. `parse_jd` is total.
    return prose[:_MAX_SUMMARY]


# ── Duties (MAJOR + MINOR FUNCTIONS) ─────────────────────────────────────────


def _is_instruction(text: str, wjq: Wjq) -> bool:
    low = text.lower()
    return any(fragment.lower() in low for fragment in wjq.instruction_markers)


def _freq_heading(text: str, wjq: Wjq) -> str | None:
    """The frequency a bare group-heading line (``DAILY`` / ``WEEKLY:``) sets, or
    ``None``."""
    key = _clean(text).rstrip(":").strip().upper()
    return wjq.frequency_headings.get(key)


def _duty_items(text: str, wjq: Wjq) -> list[tuple[str, str | None]]:
    """``(statement, group_frequency)`` per duty, mode-aware because the two extractors
    render duties differently:

    * **bulleted** (antiword ``.`` bullets, numbered lists): a bullet or a prior duty
      that ended with a ``(D)`` marker starts a new duty; other lines are wrapped
      continuations that append (a multi-sentence bullet stays one duty).
    * **paragraph** (python-docx, and antiword paragraph blocks with no bullets): a line
      that ends a sentence completes the duty, so the next line starts a new one — a
      wrapped continuation (no terminal punctuation) still appends.

    A bare ``DAILY`` / ``WEEKLY`` group heading sets the frequency of the duties that
    follow it; instruction lines are dropped."""
    has_bullets = any(_WJQ_BULLET.match(ln.strip()) for ln in text.splitlines())
    items: list[tuple[str, str | None]] = []
    current: str | None = None
    group: str | None = None
    prev_ended_freq = False
    prev_ended_sentence = False

    def flush() -> None:
        nonlocal current
        if current is not None:
            items.append((current, group))
        current = None

    for raw in text.splitlines():
        stripped = raw.strip()
        if not stripped:
            flush()
            prev_ended_freq = prev_ended_sentence = False
            continue
        heading_freq = _freq_heading(stripped, wjq)
        if heading_freq is not None:
            flush()
            group = heading_freq
            prev_ended_freq = prev_ended_sentence = False
            continue
        if _is_instruction(stripped, wjq):
            flush()
            prev_ended_freq = prev_ended_sentence = False
            continue
        is_bullet = bool(_WJQ_BULLET.match(stripped))
        starts_new = (
            is_bullet
            or prev_ended_freq
            or current is None
            or (not has_bullets and prev_ended_sentence)
        )
        if starts_new:
            flush()
            current = _WJQ_BULLET.sub("", stripped, count=1) if is_bullet else stripped
        else:
            current = f"{current} {stripped}"
        prev_ended_freq = bool(_ENDS_FREQ.search(stripped))
        prev_ended_sentence = bool(_ENDS_SENTENCE.search(stripped))
    flush()
    return items


def _strip_frequency(statement: str, wjq: Wjq) -> tuple[str, str | None]:
    """Strip every standalone ``(D)/(W)/(M)/(S)`` token and return
    ``(clean_statement, frequency)`` — the first marker's meaning, or ``None``."""
    freq: str | None = None
    match = _FREQ_INLINE.search(statement)
    if match is not None:
        freq = wjq.frequency_markers.get(match.group(1))
    cleaned = _clean(_FREQ_INLINE.sub(" ", statement))
    return cleaned, freq


def _structure_duties(major: str, minor: str, wjq: Wjq) -> list[SFUDuty]:
    duties: list[SFUDuty] = []
    for block in (major, minor):
        for statement, group_freq in _duty_items(block, wjq):
            cleaned, inline_freq = _strip_frequency(statement, wjq)
            stmt = _clean(_PERCENT_RE.sub("", cleaned)).strip(" -–—•*.")
            if not stmt or stmt.endswith(":"):
                continue
            duties.append(
                SFUDuty(
                    action_verb=_leading_verb(stmt),
                    statement=stmt[:_MAX_DUTY_STMT],
                    frequency=inline_freq or group_freq,
                )
            )
            if len(duties) >= _MAX_DUTIES:
                return duties
    return duties


# ── Qualifications (section 13) ──────────────────────────────────────────────


def _qual_cue_kind(text: str, wjq: Wjq) -> str | None:
    """The qualification kind a cue line switches to, or ``None`` if it is not a cue."""
    low = text.lower()
    for kind, cues in wjq.qualification_cues.items():
        if any(cue.lower() in low for cue in cues):
            return kind
    return None


def _structure_quals(text: str, wjq: Wjq) -> list[SFUQualification]:
    quals: list[SFUQualification] = []
    current_kind = "ability"
    for raw in text.splitlines():
        line = _clean(raw.replace("|", " "))
        line = _WJQ_BULLET.sub("", line, count=1).strip(" -–—•*.")
        if not line:
            continue
        cue_kind = _qual_cue_kind(line, wjq)
        if cue_kind is not None:
            current_kind = cue_kind
        if _is_instruction(line, wjq):
            continue
        if line.endswith(":"):
            continue
        quals.append(
            SFUQualification(
                text=line[:_MAX_QUAL],
                kind=current_kind,
                modifier=_detect_modifier(line, current_kind),
            )
        )
        if len(quals) >= _MAX_QUALS:
            break
    return quals


# ── Relationships (section 8) ────────────────────────────────────────────────

_REL_HEADER_WORDS = {"type of contact", "duration", "frequency", "contact"}
_EXTERNAL_CUES = (
    "external",
    "off campus",
    "off-campus",
    "vendor",
    "public",
    "supplier",
)


def _structure_relationships(text: str, wjq: Wjq) -> SFURelationships | None:
    """Best-effort internal/external split of the contacts table. **Lossy**: the WJQ
    form does not label rows internal vs external, so this classifies by keyword and
    invents NO supervisory signal (the JDFN template's supervisory scope has no WJQ
    equivalent)."""
    internal: list[str] = []
    external: list[str] = []
    for raw in text.splitlines():
        cells = _cells(raw)
        if not cells:
            continue
        contact = cells[0]
        low = contact.lower()
        if low in _REL_HEADER_WORDS or _is_instruction(contact, wjq):
            continue
        target = external if any(cue in low for cue in _EXTERNAL_CUES) else internal
        if len(target) < 30:
            target.append(contact[:_MAX_BULLET])
    if not internal and not external:
        return None
    return SFURelationships(supervisory=None, internal=internal, external=external)


# ── Additional context (the Hay-factor sections) ─────────────────────────────


def _structure_context(sections: dict[WjqSection, str], wjq: Wjq) -> str | None:
    """The Hay-factor sections stored verbatim under their heading.

    ⚠ **This said "lossless" while cutting at 4,000 characters.** The cap was
    ``_MAX_SUMMARY``, inherited from ``position_summary`` — a field with entirely
    different semantics — and the cost was measured over the live archive: **81.4% of
    CUPE JDs (3,613 of 4,440) sat exactly at it**, against **0%** of APSA. Because the
    cut falls in document order it removed the *tail* of the instrument, so
    ``continuing_education`` — the last of the seven sections — survived in only
    **17.0%** of documents. The point-factor half of the WJQ form was being discarded
    for four CUPE JDs in five, and the docstring said otherwise.

    The cap is now its own registered rulebook value
    (``segmentation.additional_context_max_chars``, HR-200), chosen against the measured
    distribution of real WJQ documents rather than borrowed. It is still a bound.
    """
    blocks: list[str] = []
    for section in wjq.context_sections:
        content = sections.get(section)
        if not content:
            continue
        heading = wjq.section_headings[section][0]
        blocks.append(f"{heading}\n{_clean(content.replace('|', ' '))}")
    if not blocks:
        return None
    cap = get_rules().segmentation.additional_context_max_chars
    return "\n\n".join(blocks)[:cap]


# ── Public entry point ───────────────────────────────────────────────────────


def segment_wjq(text: str, wjq: Wjq) -> ParseResult:
    """Segment a WJQ-template document into a populated :class:`SFUJobDescription`.

    Deterministic and total — never raises."""
    text = text or ""
    sections = _segment(text, wjq)
    found = set(sections)

    id_text = sections.get("position_identification", "")
    cells = _ordered_cells(id_text)
    title = _extract_label(cells, wjq.id_labels["title"], cap=_MAX_TITLE)
    department = _extract_label(cells, wjq.id_labels["department"], cap=200)
    position_number = _extract_label(cells, wjq.id_labels["position_number"], cap=50)
    grade = _extract_label(cells, wjq.id_labels["grade"], cap=50)
    classification = extract_classification(id_text, _cast_group(wjq.employee_group))

    summary_block = sections.get("position_summary")
    position_summary = (
        _summary_text(summary_block, wjq)
        if summary_block
        else _summary_fallback(id_text)
    )

    duties = _structure_duties(
        sections.get("major_functions", ""), sections.get("minor_functions", ""), wjq
    )
    qualifications = _structure_quals(sections.get("qualifications", ""), wjq)
    relationships = _structure_relationships(
        sections.get("internal_external_contacts", ""), wjq
    )
    additional_context = _structure_context(sections, wjq)

    jd = SFUJobDescription(
        title=(title or _FALLBACK_TITLE)[:_MAX_TITLE],
        position_number=position_number,
        department=department,
        grade=grade,
        classification=classification,
        employee_group=_cast_group(wjq.employee_group),
        about_sfu_present=False,
        position_summary=position_summary,
        duties=duties,
        decision_making=[],
        problem_solving=[],
        relationships=relationships,
        qualifications=qualifications,
        territorial_acknowledgement_present=False,
        employment_equity_present=False,
        additional_context=additional_context,
    )

    confidence = _score_sections(
        found=found,
        title=title,
        department=department,
        position_number=position_number,
        position_summary=position_summary,
        duties=duties,
        relationships=relationships,
        qualifications=qualifications,
        additional_context=additional_context,
    )
    parse_confidence = round(sum(confidence.values()) / len(confidence), 4)

    return ParseResult(
        jd=jd,
        era=_detect_era(_clean(text), 0),
        section_confidence={k.value: v for k, v in confidence.items()},
        parse_confidence=parse_confidence,
        template="wjq",
        headings_found=frozenset(
            _WJQ_TO_SECTIONKEY[s] for s in found if s in _WJQ_TO_SECTIONKEY
        ),
    )


def _cast_group(group: str) -> SFUEmployeeGroup:
    # `wjq.employee_group` is validated against `SFUEmployeeGroup` at load time
    # (`Wjq._group_is_known`), so this narrowing is total.
    return group  # type: ignore[return-value]


def _score_sections(
    *,
    found: set[WjqSection],
    title: str | None,
    department: str | None,
    position_number: str | None,
    position_summary: str | None,
    duties: list[SFUDuty],
    relationships: SFURelationships | None,
    qualifications: list[SFUQualification],
    additional_context: str | None,
) -> dict[SectionKey, float]:
    """Per-section confidence over the SFU 10-section keys: 0.9 populated, 0.4 heading
    but empty, 0 absent. The four sections WJQ has no producer for (ABOUT_SFU, FOOTER,
    DECISION_MAKING, PROBLEM_SOLVING) score 0 — honestly, not as failures."""
    conf: dict[SectionKey, float] = {}

    id_conf = 0.0
    if "position_identification" in found:
        id_conf += 0.3
    if title:
        id_conf += 0.3
    if department:
        id_conf += 0.2
    if position_number:
        id_conf += 0.2
    conf[SectionKey.IDENTIFICATION] = min(id_conf, 0.95) if id_conf else 0.2

    conf[SectionKey.ABOUT_SFU] = 0.0
    conf[SectionKey.FOOTER] = 0.0
    conf[SectionKey.DECISION_MAKING] = 0.0
    conf[SectionKey.PROBLEM_SOLVING] = 0.0

    for key, section, populated in (
        (SectionKey.POSITION_SUMMARY, "position_summary", bool(position_summary)),
        (SectionKey.DUTIES, "major_functions", bool(duties)),
        (
            SectionKey.RELATIONSHIPS,
            "internal_external_contacts",
            relationships is not None,
        ),
        (SectionKey.QUALIFICATIONS, "qualifications", bool(qualifications)),
    ):
        if section in found or populated:
            conf[key] = 0.9 if populated else 0.4
        else:
            conf[key] = 0.0
    conf[SectionKey.ADDITIONAL_CONTEXT] = 0.9 if additional_context else 0.0
    return conf

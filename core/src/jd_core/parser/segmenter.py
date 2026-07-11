"""Deterministic JD segmenter — clean text in, a populated
:class:`~jd_core.models.parsed_jd.SFUJobDescription` + per-section confidence out.

This is the Phase-1.4 *parse* step (plan §2): a **no-LLM**, rule-based mapping
from the flat text produced by ingestion to the SFU 10-section contract. It is a
JD *segmenter* built for this template — deliberately **not** a port of the
résumé-shaped hris ``parsing/chunk.py`` (reuse-map #15).

Approach (all deterministic):

1. **Detect era** by counting the OLD/NEW heading signals in
   :mod:`jd_core.parser.headings` (lettered headings + incumbent markers vote
   OLD; the About-SFU banner, ``IMPACT OF DECISION MAKING`` and the EDI footer
   vote NEW).
2. **Segment** by scanning every line, ``fullmatch``-ing it against the
   versioned heading patterns (tolerant of case, whitespace and ``A.``/``1)``
   lettering), and assigning the text between two headings to the preceding
   section. Duplicate headings (e.g. ``SUPERVISION RECEIVED`` +
   ``SUPERVISION EXERCISED``) concatenate.
3. **Structure best-effort**: identification fields from inline labels; duties
   into :class:`SFUDuty` (leading ``action_verb`` heuristic, ``how_why`` left
   empty); qualifications into :class:`SFUQualification` (K/S/A ``kind`` +
   modifier classified heuristically); decision/problem bullets into ``list[str]``;
   relationships into supervisory / internal / external; presence-booleans from
   footer detection.
4. **Score confidence** per section: high when a heading matched *and* produced
   content, lower when a heading matched but the field is empty, ~0 when the
   section was never found. The overall ``parse_confidence`` is their mean.

Robustness contract: missing/garbled sections yield empty fields + low
confidence and **never raise** — an empty or junk document parses to an
``Untitled Position`` shell with a near-zero score.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from src.jd_core.models.parsed_jd import (
    SFUDuty,
    SFUEmployeeGroup,
    SFUJobDescription,
    SFUQualification,
    SFURelationships,
)
from src.jd_core.parser import headings as hd
from src.jd_core.parser.headings import Era, SectionKey

PARSER_VERSION = "jd_segmenter_v1"

# Field length ceilings mirrored from the pydantic contract, applied defensively
# so best-effort structuring never trips a validation error.
_MAX_TITLE = 200
_MAX_SUMMARY = 4000
_MAX_DUTY_STMT = 400
_MAX_VERB = 60
_MAX_QUAL = 400
_MAX_BULLET = 400
_MAX_SUPERVISORY = 600
_MAX_DUTIES = 12
_MAX_QUALS = 40
_MAX_BULLETS = 20

_FALLBACK_TITLE = "Untitled Position"

_BULLET_RE = re.compile(r"^\s*(?:[-•*·▪‣◦]|\(?\d{1,2}[.)]|[ivx]{1,4}[.)])\s+", re.I)
_PERCENT_RE = re.compile(r"\(\s*\d{1,3}\s*%\s*\)")
_REL_LABEL_RE = re.compile(
    r"(?i)^(?:internal connections?|external connections?|"
    r"supervision (?:received|exercised)|supervisory|primary working relationships)\b"
)
_BANNER_RE = re.compile(
    r"(?i)^(?:simon fraser university|position description|job description|"
    r"administrative and professional staff positions)\s*$"
)
_LABEL_LINE_RE = re.compile(r"(?i)^[ \t]*[A-Za-z][A-Za-z '/&.#-]{0,40}[ \t]*:")


@dataclass(frozen=True)
class ParseResult:
    """The segmenter's output: the populated contract plus provenance —
    detected era, per-section confidence, and the overall score."""

    jd: SFUJobDescription
    era: Era
    section_confidence: dict[str, float]
    parse_confidence: float
    parser_version: str = PARSER_VERSION
    headings_found: frozenset[SectionKey] = field(default_factory=frozenset)


# ── Low-level helpers ────────────────────────────────────────────────────────


def _collapse_spaces(text: str) -> str:
    """Collapse runs of spaces/tabs to one space, preserving line breaks — so a
    double-spaced legacy heading still matches its single-spaced signal."""
    return re.sub(r"[ \t]+", " ", text)


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _extract_field(text: str, label_rx: re.Pattern[str]) -> str | None:
    """First value for ``label_rx``, cut at the next inline label and cleaned."""
    m = label_rx.search(text)
    if not m:
        return None
    value = m.group(1)
    cut = hd.NEXT_LABEL_RX.search(value)
    if cut:
        value = value[: cut.start()]
    cleaned = _clean(value)
    return cleaned or None


def _logical_lines(block: str, starter: re.Pattern[str] | None = None) -> list[str]:
    """Merge wrapped continuation lines into their bullet/label parent.

    A new logical line starts on a bullet marker or (if given) a ``starter``
    label; other non-empty lines append to the current one. Bullet markers are
    stripped from the start of each item."""
    out: list[str] = []
    current: str | None = None
    for raw in block.splitlines():
        stripped = raw.strip()
        if not stripped:
            continue
        is_bullet = bool(_BULLET_RE.match(raw)) or bool(_BULLET_RE.match(stripped))
        is_start = is_bullet or (starter is not None and bool(starter.match(stripped)))
        if is_start or current is None:
            if current is not None:
                out.append(current)
            current = _BULLET_RE.sub("", stripped, count=1) if is_bullet else stripped
        else:
            current = f"{current} {stripped}"
    if current is not None:
        out.append(current)
    return [ln.strip() for ln in out if ln.strip()]


# ── Identification ───────────────────────────────────────────────────────────


def _extract_employee_group(id_text: str) -> SFUEmployeeGroup | None:
    m = hd.EMPLOYEE_GROUP_LABEL_RX.search(id_text)
    scan = m.group(1).lower() if m else id_text.lower()
    for token in hd.EMPLOYEE_GROUP_TOKENS:
        if re.search(rf"\b{token}\b", scan):
            return token  # type: ignore[return-value]
    return None


def _fallback_title(lines: list[str], heading_lines: set[int]) -> str:
    """First line that is not a heading, banner, or ``Label:`` field — used only
    when no title label was found."""
    for i, raw in enumerate(lines):
        s = raw.strip()
        if not s or i in heading_lines:
            continue
        if _BANNER_RE.match(s) or _LABEL_LINE_RE.match(s):
            continue
        return s[:_MAX_TITLE]
    return _FALLBACK_TITLE


# ── Duties / qualifications / bullets ────────────────────────────────────────


def _leading_verb(statement: str) -> str:
    m = re.match(r"[A-Za-z]+", statement)
    return m.group(0)[:_MAX_VERB] if m else ""


def _structure_duties(block: str) -> list[SFUDuty]:
    duties: list[SFUDuty] = []
    for item in _logical_lines(block):
        for part in _maybe_split_semicolons(item):
            stmt = _clean(_PERCENT_RE.sub("", part)).strip(" -–—•*")
            if not stmt or stmt.endswith(":"):
                continue
            duties.append(
                SFUDuty(
                    action_verb=_leading_verb(stmt),
                    statement=stmt[:_MAX_DUTY_STMT],
                )
            )
            if len(duties) >= _MAX_DUTIES:
                return duties
    return duties


def _maybe_split_semicolons(item: str) -> list[str]:
    """Legacy 'Typical Duties' are one run-on paragraph; split very long
    semicolon-separated runs into separate duty statements. Short items pass
    through unchanged."""
    if len(item) > 200 and item.count(";") >= 2:
        return [p for p in (p.strip() for p in item.split(";")) if p]
    return [item]


def _classify_qual(text: str) -> str:
    low = text.lower()
    if re.search(r"\bknowledge\b", low):
        return "knowledge"
    if re.search(r"\bskills?\b|\bproficien", low):
        return "skill"
    if re.search(r"\bability\b|\bable to\b", low):
        return "ability"
    if re.search(
        r"\bdegree\b|\bdiploma\b|bachelor|master|ph\.?d|doctorate|"
        r"\beducation\b|certification|designation",
        low,
    ):
        return "education"
    if re.search(r"\bexperience\b|\byears?\b", low):
        return "experience"
    return "ability"


def _detect_modifier(text: str, kind: str) -> str | None:
    low = text.lower()
    if kind == "knowledge":
        for mod in ("excellent", "working"):
            if re.search(rf"\b{mod}\b", low):
                return mod
    elif kind == "skill":
        for mod in ("basic", "intermediate", "advanced", "expert"):
            if re.search(rf"\b{mod}\b", low):
                return mod
    return None


def _structure_quals(block: str) -> list[SFUQualification]:
    quals: list[SFUQualification] = []
    for item in _logical_lines(block):
        text = _clean(item).strip(" -–—•*")
        if not text or text.endswith(":"):
            continue
        kind = _classify_qual(text)
        quals.append(
            SFUQualification(
                text=text[:_MAX_QUAL],
                kind=kind,
                modifier=_detect_modifier(text, kind),
            )
        )
        if len(quals) >= _MAX_QUALS:
            break
    return quals


def _structure_bullets(block: str) -> list[str]:
    """Decision-making / problem-solving → ``list[str]``, dropping the
    ``… regarding:`` / ``… related to:`` intro lines."""
    items: list[str] = []
    for item in _logical_lines(block):
        text = _clean(item).strip(" -–—•*")
        if not text or text.endswith(":"):
            continue
        items.append(text[:_MAX_BULLET])
        if len(items) >= _MAX_BULLETS:
            break
    return items


def _after_colon(line: str) -> str:
    _, sep, rest = line.partition(":")
    return _clean(rest if sep else line)


def _structure_relationships(block: str) -> SFURelationships | None:
    supervisory: str | None = None
    internal: list[str] = []
    external: list[str] = []
    for line in _logical_lines(block, starter=_REL_LABEL_RE):
        low = line.lower()
        if low.startswith("internal connection"):
            value = _after_colon(line)
            if value:
                internal.append(value[:_MAX_BULLET])
        elif low.startswith("external connection"):
            value = _after_colon(line)
            if value:
                external.append(value[:_MAX_BULLET])
        else:
            piece = _clean(line)
            supervisory = piece if supervisory is None else f"{supervisory} {piece}"
    if supervisory is None and not internal and not external:
        return None
    return SFURelationships(
        supervisory=(supervisory[:_MAX_SUPERVISORY] if supervisory else None),
        internal=internal[:30],
        external=external[:30],
    )


# ── Era + segmentation ───────────────────────────────────────────────────────


def _detect_era(collapsed: str, lettered_headings: int) -> Era:
    old, new = hd.era_signal_scores(collapsed, lettered_headings)
    if old == 0 and new == 0:
        return "unknown"
    return "old" if old >= new else "new"


def _segment(lines: list[str]) -> tuple[dict[SectionKey, str], set[int]]:
    """Return ``{section: content}`` and the set of line indices that were
    headings. Content between a heading and the next is assigned to it;
    duplicate sections concatenate."""
    hits: list[tuple[int, SectionKey]] = []
    heading_lines: set[int] = set()
    for i, line in enumerate(lines):
        matched = hd.match_heading(line)
        if matched is not None:
            hits.append((i, matched[0]))
            heading_lines.add(i)
    sections: dict[SectionKey, str] = {}
    for idx, (line_no, section) in enumerate(hits):
        start = line_no + 1
        end = hits[idx + 1][0] if idx + 1 < len(hits) else len(lines)
        content = "\n".join(lines[start:end]).strip()
        sections[section] = (
            f"{sections[section]}\n{content}".strip()
            if section in sections
            else content
        )
    return sections, heading_lines


# ── Public entry point ───────────────────────────────────────────────────────


def parse_jd(text: str) -> ParseResult:
    """Segment ``text`` into a populated :class:`SFUJobDescription` with
    per-section confidence. Deterministic and total: never raises."""
    text = text or ""
    collapsed = _collapse_spaces(text)
    lines = text.splitlines()

    lettered = sum(1 for ln in lines if hd.is_lettered_heading(ln))
    era = _detect_era(collapsed, lettered)
    sections, heading_lines = _segment(lines)
    found: set[SectionKey] = set(sections)

    # Identification — labels take priority; fall back to the first plain line.
    id_text = sections.get(SectionKey.IDENTIFICATION) or collapsed
    title_label = _extract_field(id_text, hd.TITLE_LABEL_RX) or _extract_field(
        collapsed, hd.TITLE_LABEL_RX
    )
    department = _extract_field(id_text, hd.DEPARTMENT_LABEL_RX) or _extract_field(
        collapsed, hd.DEPARTMENT_LABEL_RX
    )
    position_number = _extract_field(
        id_text, hd.POSITION_NO_LABEL_RX
    ) or _extract_field(collapsed, hd.POSITION_NO_LABEL_RX)
    grade = _extract_field(id_text, hd.GRADE_LABEL_RX)
    employee_group = _extract_employee_group(id_text)
    title = title_label or _fallback_title(lines, heading_lines)

    # Body sections.
    summary_block = sections.get(SectionKey.POSITION_SUMMARY)
    position_summary = _clean(summary_block)[:_MAX_SUMMARY] if summary_block else None
    duties = _structure_duties(sections.get(SectionKey.DUTIES, ""))
    decision_making = _structure_bullets(sections.get(SectionKey.DECISION_MAKING, ""))
    problem_solving = _structure_bullets(sections.get(SectionKey.PROBLEM_SOLVING, ""))
    relationships = _structure_relationships(sections.get(SectionKey.RELATIONSHIPS, ""))
    qualifications = _structure_quals(sections.get(SectionKey.QUALIFICATIONS, ""))
    context_block = sections.get(SectionKey.ADDITIONAL_CONTEXT)
    additional_context = _clean(context_block)[:_MAX_SUMMARY] if context_block else None

    # Presence booleans (footer + About SFU) from the whole document.
    about_sfu = hd.has_about_sfu(collapsed)
    territorial = hd.has_territorial_acknowledgement(collapsed)
    equity = hd.has_employment_equity(collapsed)

    jd = SFUJobDescription(
        title=title[:_MAX_TITLE] or _FALLBACK_TITLE,
        position_number=position_number,
        department=department,
        grade=grade,
        employee_group=employee_group,
        about_sfu_present=about_sfu,
        position_summary=position_summary,
        duties=duties,
        decision_making=decision_making,
        problem_solving=problem_solving,
        relationships=relationships,
        qualifications=qualifications,
        territorial_acknowledgement_present=territorial,
        employment_equity_present=equity,
        additional_context=additional_context,
    )

    confidence = _score_sections(
        found=found,
        title_from_label=bool(title_label),
        department=department,
        position_number=position_number,
        about_sfu=about_sfu,
        footer=territorial or equity,
        position_summary=position_summary,
        duties=duties,
        decision_making=decision_making,
        problem_solving=problem_solving,
        relationships=relationships,
        qualifications=qualifications,
        additional_context=additional_context,
    )
    parse_confidence = round(sum(confidence.values()) / len(confidence), 4)

    return ParseResult(
        jd=jd,
        era=era,
        section_confidence={k.value: v for k, v in confidence.items()},
        parse_confidence=parse_confidence,
        headings_found=frozenset(found),
    )


def _score_sections(
    *,
    found: set[SectionKey],
    title_from_label: bool,
    department: str | None,
    position_number: str | None,
    about_sfu: bool,
    footer: bool,
    position_summary: str | None,
    duties: list[SFUDuty],
    decision_making: list[str],
    problem_solving: list[str],
    relationships: SFURelationships | None,
    qualifications: list[SFUQualification],
    additional_context: str | None,
) -> dict[SectionKey, float]:
    """Per-section confidence: 0.9 when a heading matched and produced content,
    0.4 when a heading matched but the field is empty, ~0 when absent.
    Identification and presence-only sections score by evidence strength."""
    conf: dict[SectionKey, float] = {}

    id_conf = 0.0
    if SectionKey.IDENTIFICATION in found:
        id_conf += 0.3
    if title_from_label:
        id_conf += 0.3
    if department:
        id_conf += 0.2
    if position_number:
        id_conf += 0.2
    conf[SectionKey.IDENTIFICATION] = min(id_conf, 0.95) if id_conf else 0.2

    conf[SectionKey.ABOUT_SFU] = 0.9 if about_sfu else 0.0
    conf[SectionKey.FOOTER] = 0.9 if footer else 0.0

    for section, populated in (
        (SectionKey.POSITION_SUMMARY, bool(position_summary)),
        (SectionKey.DUTIES, bool(duties)),
        (SectionKey.DECISION_MAKING, bool(decision_making)),
        (SectionKey.PROBLEM_SOLVING, bool(problem_solving)),
        (SectionKey.RELATIONSHIPS, relationships is not None),
        (SectionKey.QUALIFICATIONS, bool(qualifications)),
        (SectionKey.ADDITIONAL_CONTEXT, bool(additional_context)),
    ):
        if section in found:
            conf[section] = 0.9 if populated else 0.4
        else:
            conf[section] = 0.0
    return conf

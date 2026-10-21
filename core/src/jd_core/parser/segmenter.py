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
   into :class:`SFUDuty` (leading ``action_verb`` heuristic; since v9 a "… by:"
   headline's items, or nested items, become its ``how_why``); qualifications
   into :class:`SFUQualification` (K/S/A ``kind`` +
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
from typing import TYPE_CHECKING, Literal

from src.jd_core.models.parsed_jd import (
    SFUDuty,
    SFUEmployeeGroup,
    SFUJobDescription,
    SFUQualification,
    SFURelationships,
)
from src.jd_core.parser import headings as hd
from src.jd_core.parser.classification import extract_classification
from src.jd_core.parser.headings import Era, SectionKey

if TYPE_CHECKING:  # the rules package imports the models; keep this module cycle-free
    from src.jd_core.rules import Segmentation

#: Bumped v1 -> v2 for the WJQ template router (Phase 3.4): ``parse_jd`` now classifies
#: a document ``wjq`` or ``jdfn`` and dispatches WJQ to :mod:`src.jd_core.parser.wjq`.
#: This is a genuine parser change — a WJQ file that read as ~empty under v1 now parses
#: to real content — so the version moves to force the archive re-parse the orchestrator
#: runs (``parsed_jds`` is keyed on ``(source_document_id, parser_version)``).
#:
#: Bumped v2 -> v3 for the identification-block fix: the modern SFU template keeps its
#: whole identification table in the docx *header*, which extraction excluded, so
#: :func:`_fallback_title` took the first body paragraph as the title. Extraction now
#: recovers that block (``jd_bank.ingest.extract._docx_identification_block``) and a
#: UTF-16 BOM decodes instead of falling through to latin-1. Measured over all 14,565
#: archive files, v2 -> v3: paragraph titles **4,986 -> 148**, ``position_number``
#: 34.8% -> 68.3%, ``employee_group`` 35.6% -> 68.1%, ``department`` 49.9% -> 60.8%,
#: structured ``classification`` 2,323 -> 3,049 (the first APSA/APEX grades the Bank
#: has ever parsed). The 874-JD baseline cohort is UNCHANGED by this (it scores content,
#: not identification); the only score-side movement is title-keyed gates finally seeing
#: a title. Same reasoning as v1 -> v2: the stored parse genuinely differs, so the
#: version moves to force the re-parse.
#: ⚠ Bumping this forces an archive re-parse, and the bump and the re-parse MUST ship
#: together: every layer filters `parsed_jds` on this literal, so a bump without a
#: re-parse leaves them querying a version with no rows — an apparently empty Bank.
#: v4 = `additional_context` keeps the whole WJQ point-factor block (HR-200); at v3's
#: borrowed 4,000-char cap, 81.4% of CUPE JDs were stored truncated.
#: v5 = the WJQ heading match tolerates antiword's fixed-width layout (#137). A heading
#: printed beside the next column, or with its own words stretched apart, was matching
#: nothing — so the section never opened. MEASURED: 719 of 4,440 CUPE documents (16.2%)
#: parsed to ZERO duties, and that silence is what the rewrite filled with 1,219
#: invented duties across 153 drafts (HR-213). The gap also let the form's checkbox
#: scaffolding bleed UPWARD into the duty list, so it was starving duties and polluting
#: them at once.
#: v6 = the employee-group read is evidence-ranked (HR-226). MEASURED against the raw
#: archive: 2.2% of the 4,440 `cupe` documents (~98) were never routed to the WJQ
#: segmenter — they are APSA managers who merely MENTION the word ("Directly supervises
#: CUPE employees"), and the label made `template_of` score them on the WJQ profile and
#: drop them from the JDFN cohort. Of 24 examined, ZERO declared "Employee Group: CUPE".
#: A bare token can no longer establish `cupe`; an explicit label still can. The same
#: change adds a whole-body fallback for the other groups, which the identification-only
#: scan was missing (~4% of the 4,630 ungrouped name their group outside that block).
#: v7 = the WJQ title label is read in the spellings the archive actually uses (HR-147).
#: MEASURED: 47.6% of CUPE documents (2,046 of 4,300) carried NO title — the
#: `Untitled Position` sentinel — against 0.0% for every other unit. The label
#: was not missing from the documents; it was spelled POSSESSIVELY ("Department's
#: Position Title") and `_extract_label` matches a cell exactly, so it matched nothing.
#: 1,395 of those placeholders were already inside drafts.
#: v9 = Word LIST paragraphs are items, and the duty caps are rulebook data. A Word
#: list carries its bullet as formatting (`numPr`), so the extractor returned bare
#: words and `_logical_lines` appended every item to the one before: 48.4% of JDFN
#: `.docx` with a Word-list duty section parsed to ONE duty (600-file sample,
#: 2026-10-19). The extractor now leads each list paragraph with `•`
#: (`jd_bank.ingest.extract.LIST_ITEM_MARKER`). Same bump: the 400-char statement cap
#: and the 12-duty cap (both templates) move to `segmentation.yaml` (HR-261 … HR-263).
#: Measured v8 -> v9 on a copy of the live Bank:
#: `docs/plans/PARSER-V9-LISTS-AND-CAPS.md`.
PARSER_VERSION = "jd_segmenter_v9"

#: Which SFU document template ``parse_jd`` read: the APSA/APEX/POLY "JDFN" form (the
#: original segmenter), the CUPE/WJQ questionnaire, or neither recognisably.
Template = Literal["jdfn", "wjq", "unknown"]

# Field length ceilings mirrored from the pydantic contract, applied defensively
# so best-effort structuring never trips a validation error.
#
# v9: the DUTY caps are no longer here. The statement length (was 400) and the duty
# count (was 12, both templates) are rulebook data — `segmentation.duty_statement_
# max_chars` / `duty_max_count` / `wjq_duty_max_count` (HR-261 … HR-263) — under the
# model's own, wider ceilings. MEASURED at v8: 25,095 of 96,784 duty statements sat at
# EXACTLY 400 characters, and every WJQ questionnaire with minor functions past the
# twelfth lost them.
_MAX_TITLE = 200
_MAX_POSITION_NO = 50
_MAX_SUMMARY = 4000
_MAX_VERB = 60
_MAX_QUAL = 400
_MAX_BULLET = 400
_MAX_SUPERVISORY = 600
_MAX_QUALS = 40


#: The title the parser writes when it recovered none. 🔴 **A PLACEHOLDER, NOT A
#: NULL** — `title <> ''` reports 100% coverage over documents that have no title
#: at all, and that false all-clear was produced during the very investigation that
#: then found 2,050 titleless documents. Exported so a reader counting titles checks
#: for the sentinel the writer actually uses rather than re-typing the string — it
#: had already been re-typed in two other modules.
FALLBACK_TITLE = "Untitled Position"

#: Internal alias; the segmenter refers to it throughout.
_FALLBACK_TITLE = FALLBACK_TITLE

#: A leading bullet: a typed glyph (the round-bullet family may touch its text:
#: "•Tracks" is a bullet; "-" and "*" need a space, so "-based" is not), or "1." /
#: "i)" numbering.
_BULLET_RE = re.compile(
    r"^\s*(?:[•·▪‣◦]\s*|[-*]\s+|\(?\d{1,2}[.)]\s+|[ivx]{1,4}[.)]\s+)", re.I
)
_PERCENT_RE = re.compile(r"\(\s*\d{1,3}\s*%\s*\)")
#: The bullet glyph the docx extractor leads a Word list paragraph with (v9).
_LIST_GLYPH_RE = re.compile(r"^[•◦]\s+")
#: The same glyph at the start of ANY line of a block (multiline).
_LIST_MARKER_LINE_RE = re.compile(r"(?m)^[ \t]*[•◦] ")
#: The glyph that marks a SUB-item — a nested Word list paragraph (the extractor's
#: ``SUB_ITEM_MARKER``) or a typed one. A how/why clause, never a duty of its own.
_SUB_GLYPH = "◦"
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
    #: Which template the router dispatched to (Phase 3.4). ``jdfn`` for the original
    #: APSA/APEX/POLY + legacy path (unchanged); ``wjq`` for a CUPE questionnaire.
    template: Template = "jdfn"
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


def _extract_employee_group(
    id_text: str, body: str = "", *, label_only: frozenset[str] = frozenset()
) -> SFUEmployeeGroup | None:
    """The bargaining unit this JD names, or ``None`` when it names none.

    Three passes, strongest evidence first: an explicit ``Employee Group:`` LABEL, then
    a bare token in the identification block, then a bare token in the whole ``body``.

    ``label_only`` names the groups a BARE TOKEN may never establish — they need the
    explicit label. 🔴 MEASURED 2026-08-29 against the raw archive: 2.2% of the 4,440
    documents labelled ``cupe`` (~98) were never routed to the WJQ segmenter at all;
    they are JDFN documents that merely MENTION the word — "Directly supervises CUPE
    employees", "administers the collective agreement between the University and CUPE,
    Local 3338". Of 24 examined, **0 declared** ``Employee Group: CUPE`` and 24 were
    passing mentions. They are APSA managers who supervise CUPE staff, and the label
    made ``template_of`` judge each one on the WJQ profile and drop it from the JDFN
    cohort. A job is not CUPE because its staff are — the same error as calling an
    Executive Assistant a VP (HR-224).

    The ``body`` fallback is the other half: the identification block is not always
    where the group is written, and a document that names its group in the summary was
    landing in the "no group recorded" bucket, which every surface then counted as JDFN
    by default.
    """
    for scope in (id_text, body):
        if not scope:
            continue
        m = hd.EMPLOYEE_GROUP_LABEL_RX.search(scope)
        if m:
            # An explicit label is a DECLARATION: every group is readable from it,
            # including the ones a bare mention may not establish.
            value = m.group(1).lower()
            for token in hd.EMPLOYEE_GROUP_TOKENS:
                if re.search(rf"\b{token}\b", value):
                    return token  # type: ignore[return-value]
        lowered = scope.lower()
        for token in hd.EMPLOYEE_GROUP_TOKENS:
            if token in label_only:
                continue
            if re.search(rf"\b{token}\b", lowered):
                return token  # type: ignore[return-value]
    return None


#: An id token (has a digit), then optionally more after commas — a bundled title line
#: names every position it covers ("… Position #: 00129644, 00130935"), and an RTF
#: table puts a "|" cell bar between the label and the value.
_ID_TOKEN = r"[A-Za-z0-9\-]*\d[A-Za-z0-9\-]*"
_INLINE_POSITION_NO_RX = re.compile(
    rf"(?i)\bposition[ \t]*(?:#|no\.?|number)s?[ \t]*:[ \t|]*"
    rf"({_ID_TOKEN}(?:[ \t]*,[ \t]*{_ID_TOKEN})*)"
)


def _position_number_on_title_line(text: str) -> str | None:
    """The position number written on the SAME line as the title label
    ("Position Title: Assistant Football Coach Position #: 204"). Since parser v9 the
    title is cut at that label (``NEXT_LABEL_RX`` could not match after "#" before), so
    the number must be read here or its words would vanish from the parse."""
    m = hd.TITLE_LABEL_RX.search(text)
    if not m:
        return None
    inline = _INLINE_POSITION_NO_RX.search(m.group(1))
    if not inline:
        return None
    value = re.sub(r"[ \t]*,[ \t]*", ", ", inline.group(1))
    # `position_number` holds 50 characters; a longer bundle keeps its whole ids.
    while len(value) > _MAX_POSITION_NO and ", " in value:
        value = value.rsplit(", ", 1)[0]
    return value[:_MAX_POSITION_NO]


def _fallback_title(lines: list[str], heading_lines: set[int]) -> str:
    """First line that is not a heading, banner, or ``Label:`` field — used only
    when no title label was found."""
    for i, raw in enumerate(lines):
        s = raw.strip()
        if not s or i in heading_lines:
            continue
        if _BANNER_RE.match(s) or _LABEL_LINE_RE.match(s):
            continue
        # v9: a Word list paragraph now arrives led by `•`. A fallback title is a
        # guess either way, but a bullet glyph is never part of one — MEASURED on the
        # v9 re-parse, 102 fallback titles gained a leading `• ` and nothing else.
        return _clean(_LIST_GLYPH_RE.sub("", s, count=1))[:_MAX_TITLE]
    return _FALLBACK_TITLE


# ── Duties / qualifications / bullets ────────────────────────────────────────


def _leading_verb(statement: str) -> str:
    m = re.match(r"[A-Za-z]+", statement)
    return m.group(0)[:_MAX_VERB] if m else ""


_SENTENCE_BREAK = re.compile(r"(?<=[.;!?])\s+(?=[A-Z])")


def _split_last_sentence(text: str) -> tuple[str, str]:
    """``(everything before the last sentence, the last sentence)`` — ``("", text)``
    when ``text`` is one sentence."""
    breaks = list(_SENTENCE_BREAK.finditer(text))
    if not breaks:
        return "", text
    last = breaks[-1]
    return text[: last.start()].strip(), text[last.end() :].strip()


def _sentence_chunks(text: str, max_chars: int) -> list[str]:
    """``text`` whole when it fits ``max_chars``; otherwise cut at sentence breaks into
    pieces that do (a single over-long sentence stays one piece and is capped later).
    Only for the run-on a "by:" headline arrives fused to — so the statement cap cannot
    cut words the pre-v9 reading stored (measured: 6 documents)."""
    if len(text) <= max_chars:
        return [text]
    chunks: list[str] = []
    current = ""
    start = 0
    for brk in [*_SENTENCE_BREAK.finditer(text), None]:
        end = brk.start() if brk is not None else len(text)
        sentence = text[start:end].strip()
        start = brk.end() if brk is not None else len(text)
        if current and len(current) + 1 + len(sentence) > max_chars:
            chunks.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current:
        chunks.append(current)
    return chunks


def _duty_lines(block: str) -> list[tuple[str, bool]]:
    """:func:`_logical_lines` for the DUTIES block, keeping one more fact per item:
    whether it was led by the SUB-item glyph ``◦`` — a nested Word list paragraph
    (the extractor's ``SUB_ITEM_MARKER``) or a typed one."""
    out: list[tuple[str, bool]] = []
    current: list[str] | None = None
    current_sub = False
    for raw in block.splitlines():
        stripped = raw.strip()
        if not stripped:
            continue
        if _BULLET_RE.match(stripped):
            if current is not None:
                out.append((" ".join(current), current_sub))
            current_sub = stripped.startswith(_SUB_GLYPH)
            current = [_BULLET_RE.sub("", stripped, count=1)]
        elif current is None:
            current, current_sub = [stripped], False
        else:
            current.append(stripped)
    if current is not None:
        out.append((" ".join(current), current_sub))
    return [(text.strip(), sub) for text, sub in out if text.strip()]


def _structure_duties(block: str, seg: Segmentation) -> list[SFUDuty]:
    """The DUTIES block as SFU's template shapes it: "ACTION VERB … WHAT by" + its
    how/why (owner ruling 2026-10-20, Q1).

    * A line matching ``segmentation.duty_headline_pattern`` (HR-264 — the template's
      "… by:") is a DUTY; the items after it become that duty's ``how_why`` until the
      next headline or the next other ``…:`` intro line. Until v9 such a headline was
      DROPPED (any item ending ``:`` was) — 18,583 major-duty headlines in 5,365 JDFN
      documents — and its sub-bullets became duties of their own.
    * An item led by the sub-item glyph (a nested list paragraph) is a how/why clause
      of the duty above it, headline or not — the J4 export's shape.
    * Anything else is a duty of its own, as before (semicolon runs split).

    Every cap is rulebook data: duty count and statement length (HR-261…263), how/why
    clauses per duty and characters per clause (HR-265/266)."""
    headline = seg.duty_headline_pattern
    max_chars = seg.duty_statement_max_chars
    raw: list[tuple[str, list[str]]] = []
    grouping = False
    nested_group = False  # this group's clauses arrived NESTED — the doc shows depth
    # Each item is first split exactly as before v9 (a long legacy semicolon run is
    # several duties), and EACH PART is then placed — so grouping never fuses what the
    # flat reading kept apart. MEASURED: deciding on the whole item instead lost duty
    # words in 148 documents on the Bank copy.
    for item, is_sub in _duty_lines(block):
        for part in _maybe_split_semicolons(item):
            stmt = _clean(_PERCENT_RE.sub("", part)).strip(" -–—•◦*")
            if not stmt:
                continue
            if headline.search(stmt):
                # A headline fused onto the run-on before it (unbulleted paragraphs)
                # keeps that run-on as its own duty: only the LAST sentence is the
                # headline. Otherwise the statement cap would cut the run-on's text.
                lead, head = _split_last_sentence(stmt)
                raw.extend(
                    (chunk, []) for chunk in _sentence_chunks(lead, max_chars) if chunk
                )
                raw.append((head.rstrip(" :"), []))
                grouping, nested_group = True, False
            elif stmt.endswith(":"):
                # Any other intro ("Duties include:", "Budget Management:") ends a group
                # and is KEPT as a line of its own. Until v9 it was dropped — but in a
                # Word-list document v8 had fused it into a run-on, so dropping it now
                # would lose words v8 stored (measured: 303 documents, 7,536 words).
                grouping = False
                raw.append((stmt.rstrip(" :"), []))
            elif raw and is_sub:
                raw[-1][1].append(stmt)
                nested_group = True
            elif grouping and not nested_group:
                # A flat list (typed bullets, or one Word level) cannot show depth, so
                # the headline owns what follows it until the next headline or intro.
                raw[-1][1].append(stmt)
            else:
                # A top-level item after NESTED clauses is the headline's sibling.
                grouping = False
                raw.append((stmt, []))
    duties: list[SFUDuty] = []
    for stmt, how_why in raw[: seg.duty_max_count]:
        duties.append(
            SFUDuty(
                action_verb=_leading_verb(stmt),
                statement=stmt[: seg.duty_statement_max_chars],
                how_why=[
                    clause[: seg.duty_how_why_max_chars]
                    for clause in how_why[: seg.duty_how_why_max_count]
                ],
            )
        )
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
        # A "…:" lead-in is KEPT, minus its colon (v9, review H1): it is often a whole
        # requirement ("Bachelor's degree … OR an equivalent combination of …:") that
        # v8 kept fused into a run-on and v9's list reading had started dropping.
        text = _clean(item).strip(" -–—•◦*").rstrip(" :")
        if not text:
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


def _structure_bullets(block: str, max_count: int) -> list[str]:
    """Decision-making / problem-solving → ``list[str]``.

    v9 (review H1): the ``… related to:`` lead-in is KEPT, minus its colon. Before v9
    it was dropped — harmless while Word lists fused it into a run-on that v8 kept, but
    once list items are read apart, dropping it lost words in 4,784 Decision Making and
    2,231 Problem Solving sections (measured vs v8). ``max_count`` is
    ``segmentation.bullet_max_count`` (HR-268; it was the code constant 20)."""
    items: list[str] = []
    for item in _logical_lines(block):
        text = _clean(item).strip(" -–—•◦*").rstrip(" :")
        if not text:
            continue
        items.append(text[:_MAX_BULLET])
        if len(items) >= max_count:
            break
    return items


def _after_colon(line: str) -> str:
    _, sep, rest = line.partition(":")
    return _clean(rest if sep else line)


def _structure_relationships(block: str) -> SFURelationships | None:
    supervisory: str | None = None
    internal: list[str] = []
    external: list[str] = []
    #: Which connections list a BULLETED line under an "Internal/External
    #: Connections" label belongs to (v9). Before v9 such a bullet was a logical line
    #: of its own that matched no label and so fell into `supervisory` — which a Word
    #: list made the common case: MEASURED on the v9 re-parse, 213 documents moved
    #: their whole contact list into `supervisory`. An unbulleted continuation still
    #: merges into the label's own line (`_logical_lines`), exactly as before.
    current: list[str] | None = None
    for line in _logical_lines(block, starter=_REL_LABEL_RE):
        low = line.lower()
        if low.startswith("internal connection"):
            current = internal
            value = _after_colon(line)
            if value:
                internal.append(value[:_MAX_BULLET])
        elif low.startswith("external connection"):
            current = external
            value = _after_colon(line)
            if value:
                external.append(value[:_MAX_BULLET])
        elif current is not None and not _REL_LABEL_RE.match(line):
            value = _clean(line)
            if value:
                current.append(value[:_MAX_BULLET])
        else:
            current = None
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
    per-section confidence. Deterministic and total: never raises.

    **Router (Phase 3.4).** Classifies the document from its body text: a CUPE/WJQ
    questionnaire (marker present) is dispatched to :mod:`src.jd_core.parser.wjq`;
    everything else takes the original JDFN/legacy path below, **byte-identical** to v1.
    The WJQ marker vocabulary is data (``wjq.yaml``), read via :func:`get_rules`."""
    text = text or ""

    # Import lazily so `segmenter` (which `wjq` imports for its helpers + `ParseResult`)
    # stays import-cycle-free. `get_rules` is imported here for the router AND for
    # `employee_group_label_only` (HR-226), which the identification pass below reads.
    from src.jd_core.parser.wjq import is_wjq, segment_wjq  # noqa: PLC0415
    from src.jd_core.rules import get_rules  # noqa: PLC0415

    wjq_rules = get_rules().wjq
    if is_wjq(text, wjq_rules):
        return segment_wjq(text, wjq_rules)

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
    position_number = (
        _extract_field(id_text, hd.POSITION_NO_LABEL_RX)
        or _extract_field(collapsed, hd.POSITION_NO_LABEL_RX)
        or _position_number_on_title_line(id_text)
        or _position_number_on_title_line(collapsed)
    )
    grade = _extract_field(id_text, hd.GRADE_LABEL_RX)
    employee_group = _extract_employee_group(
        id_text,
        collapsed,
        label_only=frozenset(get_rules().segmentation.employee_group_label_only),
    )
    classification = extract_classification(id_text, employee_group)
    title = title_label or _fallback_title(lines, heading_lines)

    # Body sections.
    summary_block = sections.get(SectionKey.POSITION_SUMMARY)
    # The summary is prose: the extractor's list glyphs (v9) are stripped before the
    # cap, or they would spend the 4,000 characters and push the tail out — MEASURED
    # over the archive, 40 summaries already at the cap lost 164 words to them.
    position_summary = (
        _clean(_LIST_MARKER_LINE_RE.sub("", summary_block))[:_MAX_SUMMARY]
        if summary_block
        else None
    )
    duties = _structure_duties(
        sections.get(SectionKey.DUTIES, ""), get_rules().segmentation
    )
    bullet_cap = get_rules().segmentation.bullet_max_count
    decision_making = _structure_bullets(
        sections.get(SectionKey.DECISION_MAKING, ""), bullet_cap
    )
    problem_solving = _structure_bullets(
        sections.get(SectionKey.PROBLEM_SOLVING, ""), bullet_cap
    )
    relationships = _structure_relationships(sections.get(SectionKey.RELATIONSHIPS, ""))
    qualifications = _structure_quals(sections.get(SectionKey.QUALIFICATIONS, ""))
    # `additional_context` has its own registered cap (HR-200), not the summary's.
    # Sharing `_MAX_SUMMARY` between the two is what truncated 81.4% of CUPE JDs; no
    # JDFN document in the archive reaches even the old 4,000, so this path is
    # unaffected in practice — but one field having one cap is the point.
    # Imported lazily for the same reason the router does it (see `parse_jd`): this
    # module must stay import-cycle-free with `jd_core.rules`.
    from src.jd_core.rules import get_rules  # noqa: PLC0415

    context_block = sections.get(SectionKey.ADDITIONAL_CONTEXT)
    _context_cap = get_rules().segmentation.additional_context_max_chars
    additional_context = _clean(context_block)[:_context_cap] if context_block else None

    # Presence booleans (footer + About SFU) from the whole document.
    about_sfu = hd.has_about_sfu(collapsed)
    territorial = hd.has_territorial_acknowledgement(collapsed)
    equity = hd.has_employment_equity(collapsed)

    jd = SFUJobDescription(
        title=title[:_MAX_TITLE] or _FALLBACK_TITLE,
        position_number=position_number,
        department=department,
        grade=grade,
        classification=classification,
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

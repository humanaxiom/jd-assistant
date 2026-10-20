"""Text extraction for the real SFU archive formats.

Ported and slimmed from hris ``pipeline/parsing/extract.py`` (reuse map #14).
What is kept: the tolerant decode ladder, the DOCX (python-docx) and RTF
(striprtf) backends, and the NUL-stripping sanitiser that keeps Postgres happy.
What is dropped: the PDF/PyMuPDF path and the page/block structure — the JD
corpus is near-zero PDF (census §3) and downstream stages want a flat text
stream, not positioned blocks. What is *added*: an ``antiword`` backend for the
legacy binary ``.doc`` corpus (4,577 files; python-docx cannot read binary
``.doc``), which the census validated as the offline extraction path.

The public entry point is :func:`extract_text` — ``bytes + DocumentFormat`` in,
plain ``str`` out. Unsupported formats raise :class:`UnsupportedFormatError`.
"""

from __future__ import annotations

import hashlib
import re
import subprocess
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import cast

from docx import Document
from docx import types as docx_types
from docx.blkcntnr import BlockItemContainer
from docx.document import Document as DocxDocument
from docx.oxml.ns import qn
from docx.oxml.xmlchemy import BaseOxmlElement
from docx.table import Table
from docx.text.paragraph import Paragraph

from src.jd_bank.db.models import DocumentFormat
from src.jd_core.parser.headings import (
    CANONICAL_HEADING,
    DEPARTMENT_LABEL_RX,
    EMPLOYEE_GROUP_LABEL_RX,
    GRADE_LABEL_RX,
    POSITION_NO_LABEL_RX,
    TITLE_LABEL_RX,
    SectionKey,
    match_heading,
)
from src.jd_core.parser.segmenter import _BULLET_RE as _SEGMENTER_BULLET_RE

# antiword ships in the ingestion image (Dockerfile). Overridable for tests.
ANTIWORD_BIN = "antiword"

# DoS hardening. The archive is ~14,565 files processed by shared workers, so a
# single corrupt/crafted document must not hang a worker or exhaust its memory.
# A crafted binary .doc can send antiword into a pathological loop -> hard wall
# clock cap; and no legitimate SFU JD approaches 50 MiB (the largest golden file
# is ~5 MiB) -> reject oversized inputs before loading them into a backend.
#
# NB what the cap protects is THE EXTRACTOR — antiword / python-docx, which allocate
# proportional to their input and are the actual hazard. It does NOT forbid us from
# *hashing* bytes we never parse: see `stream_sha256`, which reads any file in constant
# memory. An oversized file is still a file, and it still gets a `source_documents` row.
ANTIWORD_TIMEOUT_SECONDS = 30
MAX_DOCUMENT_BYTES = 50 * 1024 * 1024  # 50 MiB

#: Chunk size for :func:`stream_sha256`. Bounds the memory a hash of ANY file costs.
_HASH_CHUNK_BYTES = 1024 * 1024  # 1 MiB


class ExtractionError(RuntimeError):
    """Text could not be extracted from an otherwise-supported document."""


class UnsupportedFormatError(ExtractionError):
    """The document format has no extraction backend (route to manual triage)."""


class DocumentTooLargeError(ExtractionError):
    """Input exceeds :data:`MAX_DOCUMENT_BYTES` — rejected before extraction."""


def _strip_nul(text: str) -> str:
    """Remove NUL (U+0000). Postgres ``text``/``jsonb`` cannot store U+0000 (it
    raises ``UntranslatableCharacterError`` at write time), and some legacy
    binaries carry embedded NULs. Cheap unconditional pass — the common clean
    case is a no-op."""
    return text.replace("\x00", "") if "\x00" in text else text


#: UTF-16 byte-order marks (LE, BE). Checked explicitly rather than added to the
#: codec ladder: latin-1 decodes ANY byte sequence, so it can never fall through to a
#: later rung — a UTF-16 file must be recognised up front or it silently becomes
#: mojibake.
_UTF16_BOMS = (b"\xff\xfe", b"\xfe\xff")


def _decode(blob: bytes) -> str:
    """Tolerant byte decode: UTF-16 BOM -> UTF-8 BOM -> UTF-8 -> latin-1 (never
    raises). The UTF-8/latin-1 ladder is hris's, so text inputs decode predictably
    across eras; the UTF-16 rung is ours.

    **Measured defect it fixes:** the archive holds UTF-16LE ``.txt`` exports whose
    ``\\xff\\xfe`` BOM is invalid UTF-8, so the ladder fell through to latin-1 and
    every one of them decoded to ``ÿþP%P%P%…`` — the whole document, title included,
    turned to noise. Small (the archive is 24 ``.txt`` files) but total per file.
    """
    if blob[:2] in _UTF16_BOMS:
        try:
            return blob.decode("utf-16")
        except UnicodeDecodeError:  # truncated/odd-length — fall through
            pass
    for codec in ("utf-8-sig", "utf-8"):
        try:
            return blob.decode(codec)
        except UnicodeDecodeError:
            continue
    return blob.decode("latin-1")


#: The marker a Word LIST paragraph is emitted with (parser v9). A Word list carries its
#: bullet or number as FORMATTING (``<w:numPr>``), not as a glyph in the text, so
#: python-docx returns the bare words — and the segmenter, which starts a new item only
#: on a bullet marker, appended every list item to the one before it. MEASURED
#: 2026-10-19: 48.4% of JDFN ``.docx`` whose duties are a Word list parsed to ONE duty
#: (then cut at 400 characters); typed-bullet files almost never did. Emitting the
#: glyph the segmenter already reads (``_BULLET_RE`` / ``_WJQ_BULLET`` both accept
#: ``•``) makes a Word list read exactly as the typed list it looks like on the page.
#: Inert to Tier-2 near-dup: its tokenizer keeps ``[a-z0-9]+`` only (pinned by test).
LIST_ITEM_MARKER = "• "

#: The marker a NESTED Word list paragraph is emitted with — one indented beyond the
#: most recent top-level item. The JDFN segmenter reads a line led by it as a how/why
#: clause of the duty above it, which is the SFU template's own shape ("ACTION VERB …
#: WHAT by" + how/why sub-bullets) and exactly what the J4 export writes. Owner ruling
#: 2026-10-20 (Q1). Also inert to Tier-2 near-dup (not ``[a-z0-9]``).
SUB_ITEM_MARKER = "◦ "

_P = qn("w:p")
_TBL = qn("w:tbl")
_TR = qn("w:tr")
_TC = qn("w:tc")
_SDT = qn("w:sdt")
_SDT_CONTENT = qn("w:sdtContent")
_PPR = qn("w:pPr")
_NUMPR = qn("w:numPr")
_NUMID = qn("w:numId")
_PSTYLE = qn("w:pStyle")
_VAL = qn("w:val")
_STYLE = qn("w:style")
_STYLE_ID = qn("w:styleId")
_BASED_ON = qn("w:basedOn")
_ILVL = qn("w:ilvl")
_IND = qn("w:ind")
_LEFT = qn("w:left")
_START = qn("w:start")
_LVL = qn("w:lvl")
_ILVL_ATTR = qn("w:ilvl")
_NUM = qn("w:num")
_NUM_ID_ATTR = qn("w:numId")
_ABSTRACT_NUM = qn("w:abstractNum")
_ABSTRACT_NUM_ID = qn("w:abstractNumId")
_ABSTRACT_NUM_ID_ATTR = qn("w:abstractNumId")

#: ``numId="0"`` is Word's explicit "no numbering" — it switches a numbered style off.
_NO_NUMBERING = "0"

#: A paragraph that ALREADY leads with a typed bullet or number gets no second marker.
#: The segmenter's own bullet grammar, so "already marked" and "will split" agree.
_ALREADY_MARKED = _SEGMENTER_BULLET_RE


def _numbered_style_ids(doc: DocxDocument) -> frozenset[str]:
    """The paragraph style ids whose definition (or a ``basedOn`` ancestor's) numbers
    the paragraph — the older templates' shape, where nothing sits on the paragraph."""
    by_id = {
        style.get(_STYLE_ID): style
        for style in doc.styles.element.findall(_STYLE)
        if style.get(_STYLE_ID)
    }

    def numbered(style_id: str) -> bool:
        seen: set[str] = set()
        current: str | None = style_id
        while current is not None and current not in seen:
            seen.add(current)
            style = by_id.get(current)
            if style is None:
                return False
            ppr = style.find(_PPR)
            numpr = ppr.find(_NUMPR) if ppr is not None else None
            if numpr is not None:
                numid = numpr.find(_NUMID)
                if numid is not None:
                    return bool(numid.get(_VAL) != _NO_NUMBERING)
            based_on = style.find(_BASED_ON)
            current = str(based_on.get(_VAL)) if based_on is not None else None
        return False

    return frozenset(sid for sid in by_id if numbered(sid))


def _is_list_paragraph(p: BaseOxmlElement, numbered_styles: frozenset[str]) -> bool:
    """True when Word renders ``p`` as a list item: a direct ``numPr`` naming a real
    numbering (``numId`` != 0), or — when the paragraph names none — a numbered style.
    A direct ``numId=0`` wins over the style, exactly as it does in Word."""
    ppr = p.find(_PPR)
    if ppr is None:
        return False
    numpr = ppr.find(_NUMPR)
    if numpr is not None:
        numid = numpr.find(_NUMID)
        if numid is not None:
            return bool(numid.get(_VAL) != _NO_NUMBERING)
        # An `ilvl`-only numPr inherits its numbering from the style — fall through.
    pstyle = ppr.find(_PSTYLE)
    return pstyle is not None and str(pstyle.get(_VAL)) in numbered_styles


def _is_structural_line(text: str) -> bool:
    """A section heading (either template's vocabulary) or an identification label.

    Outline-numbered headings are list paragraphs too, and both heading matchers read
    the line from its first character — a marker in front would hide the heading and
    silently merge two sections. The identification regexes are line-anchored for the
    same reason."""
    # Lazy for the same reason `ingest.detect_format` is imported lazily elsewhere: the
    # parser package must stay import-cycle-free with this module.
    from src.jd_core.parser.wjq import is_wjq_heading  # noqa: PLC0415
    from src.jd_core.rules import get_rules  # noqa: PLC0415

    if match_heading(text) is not None or is_wjq_heading(text, get_rules().wjq):
        return True
    return any(rx.search(text) for rx in _ID_LABEL_RXS)


def _twips(ppr: BaseOxmlElement | None) -> int | None:
    """The left indent a ``<w:pPr>`` states directly (``w:left`` or ``w:start``)."""
    if ppr is None:
        return None
    ind = ppr.find(_IND)
    if ind is None:
        return None
    for attr in (_LEFT, _START):
        value = ind.get(attr)
        if value is not None:
            try:
                return int(value)
            except ValueError:
                return None
    return None


def _num_ref(numpr: BaseOxmlElement | None) -> tuple[str | None, int | None]:
    if numpr is None:
        return None, None
    numid = numpr.find(_NUMID)
    ilvl = numpr.find(_ILVL)
    return (
        str(numid.get(_VAL)) if numid is not None else None,
        int(str(ilvl.get(_VAL))) if ilvl is not None else None,
    )


@dataclass
class _ListContext:
    """What the docx walk needs to mark list paragraphs (parser v9), resolved once per
    document, plus the one piece of walk STATE: the left indent of the most recent
    top-level item, so a list paragraph indented beyond it reads as a SUB-item.

    Indentation, not ``ilvl``, is the depth signal because both shapes occur: the
    modern template nests with ``ilvl`` 1 (and a deeper indent), while a "List Bullet
    2" style is a separate numbering whose level 0 simply sits further in — which is
    exactly how the J4 export writes a duty's how/why sub-bullets."""

    numbered_styles: frozenset[str]
    #: style id -> (numId, ilvl) its chain numbers with; style id -> its chain's indent
    style_num: dict[str, tuple[str | None, int | None]]
    style_indent: dict[str, int]
    #: (numId, ilvl) -> the numbering level's own left indent
    num_indent: dict[tuple[str, int], int]
    top_indent: int | None = None

    def indent(self, p: BaseOxmlElement) -> int:
        """Word's precedence: direct indent, then the numbering level's, then the
        style chain's, else 0."""
        ppr = p.find(_PPR)
        direct = _twips(ppr)
        if direct is not None:
            return direct
        pstyle = ppr.find(_PSTYLE) if ppr is not None else None
        style_id = str(pstyle.get(_VAL)) if pstyle is not None else None
        num_id, ilvl = _num_ref(ppr.find(_NUMPR) if ppr is not None else None)
        s_num, s_ilvl = self.style_num.get(style_id or "", (None, None))
        num_id = num_id or s_num
        level = ilvl if ilvl is not None else (s_ilvl or 0)
        if num_id is not None and (num_id, level) in self.num_indent:
            return self.num_indent[(num_id, level)]
        return self.style_indent.get(style_id or "", 0)


def _list_context(doc: DocxDocument) -> _ListContext:
    styles = {
        str(s.get(_STYLE_ID)): s
        for s in doc.styles.element.findall(_STYLE)
        if s.get(_STYLE_ID)
    }

    def chain(style_id: str) -> Iterator[BaseOxmlElement]:
        seen: set[str] = set()
        current: str | None = style_id
        while current is not None and current not in seen and current in styles:
            seen.add(current)
            yield styles[current]
            based_on = styles[current].find(_BASED_ON)
            current = str(based_on.get(_VAL)) if based_on is not None else None

    style_num: dict[str, tuple[str | None, int | None]] = {}
    style_indent: dict[str, int] = {}
    for sid in styles:
        for style in chain(sid):
            ppr = style.find(_PPR)
            numpr = ppr.find(_NUMPR) if ppr is not None else None
            if numpr is not None and sid not in style_num:
                style_num[sid] = _num_ref(numpr)
            twips = _twips(ppr)
            if twips is not None and sid not in style_indent:
                style_indent[sid] = twips

    num_indent: dict[tuple[str, int], int] = {}
    try:
        numbering = doc.part.numbering_part.element
    except (KeyError, NotImplementedError):  # pragma: no cover - no numbering part
        numbering = None
    if numbering is not None:
        abstract: dict[str, dict[int, int]] = {}
        for absn in numbering.findall(_ABSTRACT_NUM):
            levels: dict[int, int] = {}
            for lvl in absn.findall(_LVL):
                twips = _twips(lvl.find(_PPR))
                if twips is not None:
                    levels[int(str(lvl.get(_ILVL_ATTR)))] = twips
            abstract[str(absn.get(_ABSTRACT_NUM_ID_ATTR))] = levels
        for num in numbering.findall(_NUM):
            ref = num.find(_ABSTRACT_NUM_ID)
            if ref is None:
                continue
            for level, twips in abstract.get(str(ref.get(_VAL)), {}).items():
                num_indent[(str(num.get(_NUM_ID_ATTR)), level)] = twips

    return _ListContext(
        numbered_styles=_numbered_style_ids(doc),
        style_num=style_num,
        style_indent=style_indent,
        num_indent=num_indent,
    )


def _paragraph_line(p: BaseOxmlElement, ctx: _ListContext | None) -> str:
    """``p``'s text, led by :data:`LIST_ITEM_MARKER` when Word shows it as a list item,
    or by :data:`SUB_ITEM_MARKER` when that item is indented beyond the most recent
    top-level item (never either when ``ctx`` is ``None`` — the unmarked, pre-v9
    reading).

    ``parent=None`` is safe here: `Paragraph.text` only reads ``self._p.text`` and
    never touches ``parent`` (verified against the installed python-docx).
    ``ProvidesStoryPart`` is a typing.Protocol python-docx uses for style/part lookups
    this call path never takes, so the cast is a documented "runtime-safe, type-only"
    gap rather than a blind ignore."""
    text = Paragraph(p, cast(docx_types.ProvidesStoryPart, None)).text
    if ctx is None or not text.strip():
        return text
    if _is_structural_line(text):
        ctx.top_indent = None
        return text
    if _ALREADY_MARKED.match(text):
        # A typed bullet is a top-level item whose depth still anchors what follows —
        # the J4 export's duty line is typed, its how/why sub-bullets are Word lists.
        ctx.top_indent = ctx.indent(p)
        return text
    if not _is_list_paragraph(p, ctx.numbered_styles):
        return text
    indent = ctx.indent(p)
    if ctx.top_indent is not None and indent > ctx.top_indent:
        return f"{SUB_ITEM_MARKER}{text.lstrip()}"
    ctx.top_indent = indent
    return f"{LIST_ITEM_MARKER}{text.lstrip()}"


def _iter_docx_block_text(
    el: BaseOxmlElement, ctx: _ListContext | None = None
) -> Iterator[str]:
    """Walk ``el``'s children in document order, yielding paragraph text.

    ``doc.paragraphs`` (python-docx's high-level API) returns only body-level
    ``<w:p>`` elements — it skips text inside tables (``<w:tbl>``) and Word
    content controls (``<w:sdt>``/``<w:sdtContent>``). This walk descends into
    both, recursively, so arbitrarily nested tables/SDTs (table-in-cell,
    SDT-in-cell, table-in-SDT) are all covered. Elements this loop does not
    recognise (e.g. the trailing ``<w:sectPr>``) are silently skipped — they
    carry no paragraph text.

    A Word LIST paragraph is led by :data:`LIST_ITEM_MARKER`, a nested one by
    :data:`SUB_ITEM_MARKER` (parser v9), using ``ctx`` (:func:`_list_context`).
    ``None`` disables marking altogether (see :func:`_extract_docx` for when).
    """
    for child in el.iterchildren():
        if child.tag == _P:
            yield _paragraph_line(child, ctx)
        elif child.tag == _TBL:
            for row in child.findall(_TR):
                for cell in row.findall(_TC):
                    yield from _iter_docx_block_text(cell, ctx)
        elif child.tag == _SDT:
            content = child.find(_SDT_CONTENT)
            if content is not None:
                yield from _iter_docx_block_text(content, ctx)


#: The heading the recovered header identification block is emitted under. Taken from
#: the parser's own heading vocabulary rather than spelled again here — the flat text
#: this function returns IS the segmenter's input, and its section markers are that
#: interface's structure channel, so a second copy of the word would be a second source
#: of truth for it (the drift `CANONICAL_HEADING` exists to prevent).
IDENTIFICATION_MARKER = CANONICAL_HEADING[SectionKey.IDENTIFICATION]

#: The SAME regexes the segmenter reads identification fields with, so "is this an
#: identification block?" and "can the parser use it?" can never answer differently.
_ID_LABEL_RXS = (
    TITLE_LABEL_RX,
    POSITION_NO_LABEL_RX,
    DEPARTMENT_LABEL_RX,
    EMPLOYEE_GROUP_LABEL_RX,
    GRADE_LABEL_RX,
)


def _is_identification_block(block: str) -> bool:
    """True when ``block`` is an identification table rather than page furniture.

    A title label, or any two distinct identification labels. One lone label is the
    *running* header — ``Position #: <numbers> <page no>`` — which admitting cost 15
    documents a position number of ``2`` (the page number). A real block always names
    the position or states several fields, even when some of them are blank.
    """
    if TITLE_LABEL_RX.search(block):
        return True
    return sum(1 for rx in _ID_LABEL_RXS if rx.search(block)) >= 2


def _collapse(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _row_lines(cells: list[str]) -> Iterator[str]:
    """Pair each ``Label:`` cell with the cell that follows it, one pair per line.

    The identification table is a grid of label/value cells, and the archive packs
    **two pairs onto one row** (measured — 874 of the 876 headers that state a
    grade look like ``Employee Group: | APSA | Grade: | 13``). Joining the whole
    row would leave ``Grade:`` mid-line, where the segmenter's line-anchored
    ``^grade[ \\t]*:`` regex cannot see it; splitting per cell would separate every
    label from its value. Pairing does both correctly.

    A label with no value (an unfilled field) and a value with no label (a banner
    cell) are each emitted alone rather than merged with a neighbour they do not
    belong to.
    """
    index = 0
    while index < len(cells):
        cell = cells[index]
        following = cells[index + 1] if index + 1 < len(cells) else None
        if cell.endswith(":") and following is not None and not following.endswith(":"):
            yield f"{cell} {following}"
            index += 2
        else:
            yield cell
            index += 1


def _iter_container_lines(container: BlockItemContainer) -> Iterator[str]:
    """Yield one line per paragraph, and per table row one line per label/value pair.

    Deliberately different from :func:`_iter_docx_block_text`, which yields each
    table cell on its own line: the segmenter's identification regexes are
    line-anchored (``^Position Title:[ \\t]*(.+)$``), so a label and its value must
    share a line. The body walk keeps cell-per-line because the CUPE/WJQ
    questionnaire parser reads cells as lines.

    Repeated cells from a horizontal merge are collapsed (``row.cells`` yields the
    same cell once per grid column it spans).
    """
    for item in container.iter_inner_content():
        if isinstance(item, Table):
            for row in item.rows:
                cells: list[str] = []
                for cell in row.cells:
                    value = _collapse(cell.text)
                    if value and (not cells or cells[-1] != value):
                        cells.append(value)
                yield from _row_lines(cells)
        else:
            yield _collapse(item.text)


def _docx_identification_block(doc: DocxDocument) -> str:
    """The identification block from a section's header part, or ``""``.

    **Why headers are read at all** (this is the one exception to body-only
    extraction — see ``test_extract_docx_excludes_header_prose_and_all_footers``).
    In the modern SFU template the entire identification table — ``Position
    Title:``, ``Position #:``, ``Department:``, ``Employee Group:``, ``Grade:`` —
    is in ``header*.xml``, not in the body. Measured over all 14,565 archive
    files: **4,968 of 9,948 ``.docx`` carry ``Position Title:`` in the header and
    in no body line**, which is precisely the set whose title parsed as a
    paragraph (the segmenter found no label and fell back to the first content
    line — the About-SFU banner or the Position Summary prose).

    Only a header that :func:`_is_identification_block` recognises is returned; page
    furniture (a running title, a page number) is left excluded, so the exception
    stays as narrow as the evidence. The first-page header is preferred because
    that is where the template puts the full table; the ordinary header usually
    holds just a running ``Position #: … <page>`` line.

    Footers stay excluded entirely: the corpus keeps only revision dates there,
    and there is no heading to file them under, so they would land in whichever
    body section happened to be last (7,171 ``.docx`` have footer text).
    """
    for section in doc.sections:
        for part in (section.first_page_header, section.header):
            lines = [line for line in _iter_container_lines(part) if line]
            if not lines:
                continue
            block = "\n".join(lines)
            if _is_identification_block(block):
                return block
    return ""


def _extract_docx(blob: bytes) -> str:
    """python-docx — document-order body walk. Handles ``.docx`` and
    macro-enabled ``.docm`` (both OOXML).

    Recovers text from tables and Word content controls, which
    ``doc.paragraphs`` alone misses (measured: 2,596 of 9,947 archive
    ``.docx`` lose >40% of their text, 24 lose everything).

    Walks ``doc.element.body``, plus — and only — a header part carrying the
    template's identification labels, which is emitted first under
    :data:`IDENTIFICATION_MARKER` (see :func:`_docx_identification_block`). Header
    prose and all footers remain excluded. A document with no such header extracts
    byte-identically to the body-only walk.
    """
    try:
        doc = Document(BytesIO(blob))
    except Exception as exc:  # noqa: BLE001 — normalise any python-docx failure
        raise ExtractionError(f"docx parse failed: {exc}") from exc
    identification = _docx_identification_block(doc)
    text = _join_docx(doc, identification, _list_context(doc))
    # 🔴 A CUPE/WJQ questionnaire keeps the UNMARKED (pre-v9) reading. The WJQ duty
    # reader switches into "bulleted" mode as soon as ONE bullet appears and then treats
    # every unbulleted line as a wrapped continuation — right for antiword's `.doc`
    # output, wrong for a `.docx` that mixes list and plain paragraphs. MEASURED over
    # the archive's 2,154 WJQ `.docx` with list paragraphs: markers gave MORE duties
    # on 318 but FEWER on 183 — up to 37 -> 5, whole functions fused into one — and
    # fewer duty words overall (1,678,349 vs 1,757,800). Net harm, so not shipped for
    # this form; see docs/plans/PARSER-V9-LISTS-AND-CAPS.md (open question).
    from src.jd_core.parser.wjq import is_wjq  # noqa: PLC0415
    from src.jd_core.rules import get_rules  # noqa: PLC0415

    marked = LIST_ITEM_MARKER in text or SUB_ITEM_MARKER in text
    if marked and is_wjq(text, get_rules().wjq):
        return _join_docx(doc, identification, None)
    return text


def _join_docx(doc: DocxDocument, identification: str, ctx: _ListContext | None) -> str:
    body = "\n".join(t for t in _iter_docx_block_text(doc.element.body, ctx) if t)
    if not identification:
        return body
    block = f"{IDENTIFICATION_MARKER}\n{identification}"
    return f"{block}\n{body}" if body else block


def _extract_rtf(blob: bytes) -> str:
    """striprtf — pure-Python RTF -> plain text. Imported lazily so a process
    that never touches RTF need not hard-require the optional dependency."""
    from striprtf.striprtf import rtf_to_text  # noqa: PLC0415 — optional dep, lazy

    try:
        text: str = rtf_to_text(_decode(blob))  # type: ignore[no-untyped-call]
        return text.strip()
    except Exception as exc:  # noqa: BLE001
        raise ExtractionError(f"rtf parse failed: {exc}") from exc


def _extract_txt(blob: bytes) -> str:
    """Plain text — tolerant decode, no structure to recover."""
    return _decode(blob).strip()


def _extract_doc(blob: bytes) -> str:
    """Legacy binary ``.doc`` (Word 97-2003) via the ``antiword`` subprocess.

    python-docx cannot read binary ``.doc``; the census validated antiword as
    the offline path (0 failures across the sample). antiword needs a file on
    disk, so the bytes are written to a temp file, extracted, and cleaned up.
    """
    tmp_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".doc", delete=False) as tmp:
            tmp.write(blob)
            tmp_path = tmp.name
        try:
            proc = subprocess.run(
                [ANTIWORD_BIN, tmp_path],
                capture_output=True,
                check=True,
                timeout=ANTIWORD_TIMEOUT_SECONDS,
            )
        except FileNotFoundError as exc:  # antiword not installed
            raise ExtractionError(
                "antiword binary not found — required for legacy .doc extraction"
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise ExtractionError(
                f"antiword timed out after {ANTIWORD_TIMEOUT_SECONDS}s "
                "(possible corrupt or crafted .doc)"
            ) from exc
        except subprocess.CalledProcessError as exc:
            detail = _decode(exc.stderr or b"").strip()
            raise ExtractionError(f"antiword failed: {detail}") from exc
        return _decode(proc.stdout).strip()
    finally:
        if tmp_path is not None:
            Path(tmp_path).unlink(missing_ok=True)


_BACKENDS = {
    DocumentFormat.DOCX: _extract_docx,
    DocumentFormat.DOC: _extract_doc,
    DocumentFormat.RTF: _extract_rtf,
    DocumentFormat.TXT: _extract_txt,
}


def extract_text(data: bytes, fmt: DocumentFormat) -> str:
    """Extract plain text from ``data`` for the detected ``fmt``.

    ``.docx``/``.docm`` via python-docx, legacy ``.doc`` via antiword, ``.rtf``
    via striprtf, ``.txt`` via a tolerant decode ladder. NUL characters are
    stripped so the result is safe to persist in Postgres. Formats without a
    backend (:data:`DocumentFormat.OTHER` — e.g. ``.pdf``/``.tif``/``.serv``)
    raise :class:`UnsupportedFormatError` for routing to manual triage.
    """
    if len(data) > MAX_DOCUMENT_BYTES:
        raise DocumentTooLargeError(
            f"input is {len(data)} bytes, exceeds cap of {MAX_DOCUMENT_BYTES} bytes"
        )
    backend = _BACKENDS.get(fmt)
    if backend is None:
        raise UnsupportedFormatError(f"no extraction backend for format: {fmt.value}")
    return _strip_nul(backend(data))


def read_document_bytes(path: str | Path) -> bytes:
    """Read a document's bytes, **stat-ing first** so an oversized file is never
    loaded into memory.

    THE ONE HOME OF THE STAT-BEFORE-READ GUARD. :func:`extract_text` also enforces
    :data:`MAX_DOCUMENT_BYTES` — but only *after* the bytes are already in memory, so
    a caller that reads first hands a 50 MiB+ document straight past the DoS guard the
    extractor deliberately added. Every archive walker (the Phase 2.5 baseline runner,
    the Phase 3.2a ingest driver) must go through here rather than calling
    ``path.read_bytes()`` itself.

    **Not hypothetical. MEASURED:** exactly one archive file exceeds the cap —
    ``19980120_19980120_00000293_Asst_to_Director,_Rec_Services.rtf``, **89,397,431
    bytes** — and it sorts inside the FIRST 200 files of the walk, so even a
    ``--limit 200`` smoke test hits it.

    Raises:
        DocumentTooLargeError: the file exceeds :data:`MAX_DOCUMENT_BYTES`. The bytes
            are never read.
        OSError: the file could not be stat-ed or read.
    """
    p = Path(path)
    size = p.stat().st_size
    if size > MAX_DOCUMENT_BYTES:
        raise DocumentTooLargeError(
            f"{size} bytes exceeds the extractor's cap of {MAX_DOCUMENT_BYTES} bytes "
            f"(not read)"
        )
    return p.read_bytes()


def stream_sha256(path: str | Path) -> tuple[str, int]:
    """``(sha256 hex, byte size)`` for a file of ANY size, in **constant memory**.

    The counterpart to :func:`read_document_bytes`, and the thing that lets an
    oversized file still be a *ledger row*. SHA-256 is a streaming digest: the file is
    read in :data:`_HASH_CHUNK_BYTES` chunks and the digest updated per chunk, so the
    89 MB archive ``.rtf`` costs 1 MiB of memory to hash, not 89.

    **Why this exists** (Phase 3.2a, reviewer ruling). The first cut of the ingest
    driver gave an oversized file *no* ``source_documents`` row at all, reasoning: the
    bytes are never read -> there is no sha256 -> the ``(storage_ref, sha256)``
    idempotency key is unsatisfiable. The premise was false. Phase 3.1 made
    ``source_documents`` **one row per FILE — a real ledger** (it took a migration and
    a dropped UNIQUE to get there), and CLAUDE.md non-negotiable #6 is provenance: a
    file that exists in the archive and has no row breaks that property. Today that is
    one file; the property is what matters.

    Hashing is NOT what :data:`MAX_DOCUMENT_BYTES` guards against — the extractor is
    (see the constant). This function never hands a byte to a backend.

    The digest is identical to :func:`~src.jd_bank.ingest.ingest.compute_sha256` over
    the same content (same algorithm, same bytes); ``test_ingest_extract.py`` pins that
    equivalence, because the two must agree or the Tier-1 dedup key would split.
    """
    digest = hashlib.sha256()
    size = 0
    with Path(path).open("rb") as handle:
        while chunk := handle.read(_HASH_CHUNK_BYTES):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def extract_text_from_path(path: str | Path) -> str:
    """Convenience wrapper: read a file and extract using its detected format.

    Format detection is by extension (see :func:`src.jd_bank.ingest.ingest.
    detect_format`), imported lazily to avoid a package import cycle.
    """
    from src.jd_bank.ingest.ingest import detect_format  # noqa: PLC0415

    p = Path(path)
    try:
        data = read_document_bytes(p)
    except DocumentTooLargeError as exc:
        # Re-raise NAMING THE FILE. This wrapper's message is human-facing, and it
        # carried the filename before the guard was consolidated.
        #
        # The name is added HERE rather than inside `read_document_bytes` on purpose:
        # that function's message is what the Phase 2.5 baseline writes into its skip
        # ledger, and `docs/baseline/errors.jsonl` is a COMMITTED artifact that must
        # stay byte-identical across runs. Changing the shared message would silently
        # churn it. (The path is already in the ledger's `path` field anyway — it is
        # this wrapper, which callers use without a surrounding row, that needs it in
        # the message.)
        raise DocumentTooLargeError(f"{p.name}: {exc}") from exc
    return extract_text(data, detect_format(p.name))

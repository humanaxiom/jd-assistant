"""Read a labelled identification field out of a raw JD — independently of the parser.

The question this answers is the one the database cannot: **the parser stored nothing
for this field — does the DOCUMENT say nothing, or did the parser fail to read it?**

── Discovery and readability are SEPARATE STEPS, and conflating them broke this ──────

The first version searched for the registered ``wjq.id_labels`` spellings and reported
``no label found`` for **129 of 129 APSA documents while the parser held a department
for 52 of them**. A probe contradicting the parser in the parser's favour is broken, and
the CONTROL is what showed it: ``title`` read clean over the same files.

The cause is that **identification labels have TWO provenances**, exactly as
``employee_group`` did (FINDINGS §7):

* the WJQ form reads ``wjq.id_labels`` — rulebook data, whole-cell exact match;
* the modern template reads **hardcoded regexes** in ``parser/headings.py``
  (``DEPARTMENT_LABEL_RX`` and friends), which are not rulebook data at all.

``Department:`` is unreadable by the first and read fine by the second. So this probe
**discovers** a field by a broad key word, then asks separately whether *either*
registered mechanism could read the name it found. Only a name **no mechanism can read**
is a finding.

⚠ **The probe's own blind spot, published rather than assumed:** discovery is by key
word, so a field stated under a name containing none of them is invisible here. Every
distinct field name found is printed verbatim so the key-word list can be checked by eye
rather than trusted — over-inclusion in a worklist is cheap, and this is a worklist.
"""

from __future__ import annotations

import enum
import re
from dataclasses import dataclass

from src.jd_core.parser.wjq import _NEXT_LABEL_RX

#: The longest a run of characters may be and still be a FIELD NAME rather than prose.
#: A label is short by nature; a sentence that happens to contain a colon is not. It is
#: what stops "liaising with other departments, or universities:" reading as a field.
#: MEASURED: at 60 it admitted duty prose ending in a colon ("Provides advanced
#: technical operation support for the unit by:"); no real label in the archive is
#: longer than "Evaluating Supervisor's Position Title" (38).
_MAX_FIELD_NAME = 45

#: Characters a field name may be built from. Excludes the sentence punctuation (comma,
#: semicolon, full stop) that separates a label from prose wearing one's clothes.
_FIELD_NAME_RX = re.compile(
    rf"^[|\s]*([A-Za-z][A-Za-z0-9 /()'’&#*-]{{0,{_MAX_FIELD_NAME}}}?)\s*:"
)

#: Trailing render noise on a recovered value — the fixed-width render pads with these.
_TRAILING_NOISE = " |_\t"


class Readability(enum.StrEnum):
    """Whether a registered mechanism could read the field name the document uses."""

    #: A ``wjq.id_labels`` spelling, matched whole-name as ``_extract_label`` does.
    WJQ = "wjq"
    #: Matched by the modern template's hardcoded regex in ``parser/headings.py``.
    MODERN = "modern"
    #: 🔴 NEITHER. The document states the field and no registered mechanism can read
    #: it. This is the only column that is a finding.
    UNREADABLE = "unreadable"


class ValuePlacement(enum.StrEnum):
    """Where the value sits relative to its label — both renders are in the archive."""

    #: ``Department Name: Financial Services`` — antiword's fixed-width render.
    INLINE = "inline"
    #: ``|Department Name: |Financial Services|`` — the table render, and python-docx's.
    NEXT_CELL = "next_cell"
    #: The label is present and EMPTY. A blank form field, not a defect: counting it as
    #: a stated value is the mistake that made the first P3a fix recover exactly zero.
    NONE = "none"


@dataclass(frozen=True)
class FieldHit:
    """One identification field found in a document, with what followed it."""

    #: The field name exactly as the document writes it. The evidence.
    field_name: str
    readability: Readability
    placement: ValuePlacement
    #: Empty when :attr:`placement` is ``NONE``.
    value: str

    @property
    def states_a_value(self) -> bool:
        return self.placement is not ValuePlacement.NONE


@dataclass(frozen=True)
class FieldSpec:
    """How to find one identification field, and who can already read it."""

    #: Broad, lower-case DISCOVERY terms. Over-inclusive on purpose.
    key_words: tuple[str, ...]
    #: The registered WJQ spellings (``wjq.id_labels``), matched whole-name.
    wjq_labels: tuple[str, ...]
    #: The modern template's hardcoded label regex, or ``None`` if it has none.
    modern_rx: re.Pattern[str] | None
    #: Terms that mean the name belongs to ANOTHER field. `Department Position Title`
    #: is the title field; it contains "department", and a naive key word claimed it as
    #: an unreadable department 31 times. Stated as an exclusion rather than settled by
    #: ranking key words, because the exclusion IS the honest claim: this name is not
    #: this field, and this field says nothing about it.
    exclude: tuple[str, ...] = ()


def _cells(text: str, *, cells: bool) -> list[str]:
    """The document as a cell stream, mirroring how the parser sees it.

    The fixed-width render separates cells with ``|`` and the paragraph render with
    newlines. Splitting on both is what lets one probe read both, exactly as
    ``_extract_label`` does over the cell list the segmenter hands it.
    """
    parts: list[str] = []
    for line in text.splitlines():
        parts.extend(line.split("|") if cells else [line])
    return parts


def _has_word(haystack: str, needle: str) -> bool:
    """Containment that is NOT adjacent to an alphanumeric. 🔴 Never a substring test.

    `lan` as a substring once matched 1,568 of 2,493 roles — *plan*, *Langara* — and
    this probe broke the same rule again: `grade` matched **upgrade**, reporting duty
    prose as a stated grade the parser could not read. A wrong sweep looks exactly like
    a finding.

    ⚠ **The first fix used ``\\b`` and caused a worse bug than it closed.** ``\\b``
    asserts a word/non-word *transition*, so ``\\bposition #\\b`` cannot match
    ``Position #:`` — ``#`` is not a word character and neither is the ``:`` after it.
    APSA ``position_number`` fell from 4,836 readable to 310 while the parser still held
    4,753, and a probe disagreeing with the parser by 4,443 is reporting its own defect.

    Lookarounds say what was actually meant: not *butted against* a letter or digit.
    """
    return (
        re.search(
            rf"(?<![A-Za-z0-9]){re.escape(needle)}(?![A-Za-z0-9])",
            haystack,
        )
        is not None
    )


def _is_label(cell: str) -> bool:
    return cell.rstrip().rstrip(_TRAILING_NOISE).endswith(":")


def _readability(field_name: str, value: str, spec: FieldSpec) -> Readability:
    """Could ANY registered mechanism read this field name?

    The modern regex is line-anchored, so it is tested against the reconstructed
    ``"name: value"`` line rather than the bare name — testing it against something it
    was never written to match would manufacture an ``UNREADABLE`` verdict.
    """
    wanted = {label.rstrip(":").strip().lower() for label in spec.wjq_labels}
    if field_name.lower() in wanted:
        return Readability.WJQ
    line = f"{field_name}: {value or 'x'}"
    if spec.modern_rx is not None and spec.modern_rx.search(line):
        return Readability.MODERN
    return Readability.UNREADABLE


def probe_field(text: str, spec: FieldSpec, *, cells: bool = False) -> FieldHit | None:
    """The FIRST field in ``text`` whose name contains a key word, or ``None``.

    First, not best: ``_extract_label`` returns the first match too, and a probe that
    took the last would disagree with the parser for a reason that has nothing to do
    with the archive.
    """
    stream = _cells(text, cells=cells)

    for index, cell in enumerate(stream):
        name_match = _FIELD_NAME_RX.match(cell)
        if name_match is None:
            continue
        field_name = name_match.group(1).strip()
        # Collapsed for MATCHING only. The verbatim name is kept as the evidence,
        # because a repeated space is exactly what makes a name unreadable —
        # `_extract_label` strips and lower-cases but never collapses.
        lowered = " ".join(field_name.lower().split())
        if not any(_has_word(lowered, word) for word in spec.key_words):
            continue
        if any(_has_word(lowered, word) for word in spec.exclude):
            continue

        # INLINE first: the fixed-width render puts label and value in ONE cell, and the
        # next field's label is printed beside it — so the value STOPS at that label.
        # Keeping the remainder would store "Financial Services Classification & Grade
        # Approved" as a department — a wrong value, worse than an honest blank.
        tail = cell[name_match.end() :]
        inline = (
            _NEXT_LABEL_RX.split(tail, maxsplit=1)[0].strip(_TRAILING_NOISE).strip()
        )
        if inline:
            return FieldHit(
                field_name,
                _readability(field_name, inline, spec),
                ValuePlacement.INLINE,
                inline,
            )

        # Otherwise the value is the next cell — unless that is itself a label, which
        # means the field was left blank.
        following = stream[index + 1] if index + 1 < len(stream) else ""
        value = following.strip(_TRAILING_NOISE).strip()
        placement = (
            ValuePlacement.NEXT_CELL
            if value and not _is_label(following)
            else ValuePlacement.NONE
        )
        return FieldHit(
            field_name,
            _readability(field_name, value, spec),
            placement,
            value if placement is ValuePlacement.NEXT_CELL else "",
        )

    return None

"""Redact SFU's mandated, do-not-edit text before a scanner marks it down.

The defect this closes (HR-058). SFU pre-populates the About-SFU paragraph
(rulebook Part 1.5, "do not edit") and mandates the territorial acknowledgement +
Employment Equity statements (Part 1.6) on every JD. SFU's own paragraph contains
``compassionate``, which *our* coded-term lexicon files at ``medium``. So a JD that
obeys SFU scores 91.5/A → 81.5/B, and a JD that drops the paragraph to dodge that
trips ``SFU-COMP-ABOUT``. It is penalised either way — on nearly every compliant JD
in the archive, systematically depressing the very baseline the score floor is meant
to be ratified against.

A scanner must not mark down text its own rulebook forbids the author to change. So
the coded-term scan (Part 6) runs over the JD **with the mandated passages cut out**.
Nothing else changes: presence is still checked (``SFU-COMP-ABOUT`` /
``-TERRITORIAL`` / ``-EDI`` fire on absence), and every other scan — placeholders,
banned qualification phrases, duty percentages — still reads the whole document.

**Rulebook as data (CLAUDE.md §2): not one character of SFU's text is here.** The
passages come from ``rules/boilerplate.yaml`` and the decision to exempt them is
``boilerplate.coded_term_scan_exempt`` (HR-107). This module is the matcher, and
only the matcher.

Scope — what counts as the mandated block, and why it cannot be gamed:

* The unit is a **passage** (one of SFU's mandated sentences), matched **verbatim**.
  A passage is cut only where the JD reproduces it in full.
* Matching is on normalized text — :func:`src.jd_core.textnorm.fold_text`, the ONE
  definition of invisible/typographic noise in this repo, plus case folding:
  whitespace collapsed (the archive line-wraps mid-sentence), zero-width characters
  and soft hyphens dropped, typographic quotes/dashes/NBSP folded to ASCII (a
  ``.docx`` yields "Canada’s", the rulebook yields "Canada's"). **Everything else
  must match character for character.**
* Therefore: an "About SFU" *heading* exempts nothing — only SFU's text does. A
  fragment ("…fearless, compassionate…") is not a passage, so it is still scanned.
  Words spliced into a mandated sentence make it a different sentence, which matches
  nothing and is scanned in full. Text before, after or between the passages is
  always scanned. The exemption is granted to SFU's words, never to a location.

Folding cannot widen the exemption. It deletes only characters a reader cannot see
and rewrites only characters onto their own ASCII spelling — so no amount of it turns
a sentence the JD's author wrote into a sentence SFU mandated, and every smuggling
route stays closed (``tests/unit/test_jd_boilerplate.py``).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Final

from src.jd_core.textnorm import fold_text

#: What a cut passage is replaced by. A space, not nothing: splicing the two sides
#: of the cut together could otherwise weld two words into a third that the scanner
#: would then match (``…work`` + ``man…``), inventing a finding out of a removal.
_CUT: Final[str] = " "


def normalize(text: str, *, join_paragraphs: bool) -> str:
    """``text`` in the form passages are compared in. See the module docstring.

    ``join_paragraphs`` is the rulebook's ``textnorm.collapse_across_paragraph_break``
    (HR-108), threaded in rather than defaulted: there is one home for that decision
    and it is not this module.
    """
    return fold_text(text, join_paragraphs=join_paragraphs, casefold=True).folded


def _spans(
    text: str, passages: Iterable[str], *, join_paragraphs: bool
) -> list[tuple[int, int]]:
    """Every ``[start, end)`` span of ``text`` occupied by a mandated passage.

    Every occurrence, not just the first: a JD that repeats the footer (the archive
    does) must have both copies exempted, or the fix would work on page 1 and not on
    page 2.

    Spans come back in the coordinates of the **original** ``text``
    (:meth:`~src.jd_core.textnorm.FoldedText.to_raw`), so a passage matched in folded
    space is cut out of the JD's own bytes — and the text that survives the cut, which
    is what a coded-term finding then quotes as evidence, is still the JD's own words
    rather than a lower-cased, whitespace-mangled rendering of them.
    """
    folded = fold_text(text, join_paragraphs=join_paragraphs, casefold=True)
    found: list[tuple[int, int]] = []
    for passage in passages:
        needle = normalize(passage, join_paragraphs=join_paragraphs)
        if not needle:
            continue
        at = folded.folded.find(needle)
        while at != -1:
            found.append(folded.to_raw(at, at + len(needle)))
            at = folded.folded.find(needle, at + len(needle))
    return found


def redact_passages(
    text: str, passages: Sequence[str], *, join_paragraphs: bool
) -> str:
    """``text`` with every verbatim occurrence of a mandated passage cut out.

    Pure. Returns ``text`` unchanged when no passage occurs in it (the common case
    for a legacy JD that carries none of the new template's boilerplate).
    """
    spans = _spans(text, passages, join_paragraphs=join_paragraphs)
    if not spans:
        return text

    kept: list[str] = []
    cursor = 0
    for start, end in sorted(spans):
        # Two mandated passages can overlap in the JD, and HR-104 explicitly invites
        # it: "if SFU has revised this paragraph, BOTH wordings belong in this list
        # until the archive is re-issued". Two wordings of one paragraph share most
        # of their text. So overlapping spans collapse into ONE cut — a second cut
        # from a cursor already past `start` would slice backwards and duplicate the
        # tail of the document.
        if start < cursor:
            cursor = max(cursor, end)  # nested span: keep the wider cut
            continue
        kept.append(text[cursor:start])
        kept.append(_CUT)
        cursor = end
    kept.append(text[cursor:])
    return "".join(kept)

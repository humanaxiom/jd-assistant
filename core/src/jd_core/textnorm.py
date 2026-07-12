"""One definition of "invisible and typographic noise" in a JD's text.

Every lexicon scan in :mod:`src.jd_core.quality.validators` anchors its term with
``(?<!\\w)term(?!\\w)`` over the JD's raw text, so the matcher only ever saw the
document byte-for-byte. This module is the one fold every scan now reads it through.
``quality/boilerplate.py`` already needed most of it to match SFU's mandated passages
(2.5-prep); its ``_FOLD`` table moved here so there is ONE definition of noise rather
than two that can drift apart.

**What this actually fixes, measured on the real archive — read this before quoting
the module anywhere (CLAUDE.md #6).** Two things fold, and their impact could hardly
be more different:

* **Invisible characters (zero-width spaces, soft hyphens, BOMs) and typographic
  characters (smart quotes, non-breaking hyphens, ligatures).** In *code* the defect
  was total: a single U+200B inside a word defeated the coded-term scan, the
  banned-phrase scan and the placeholder scan outright. **On the archive it moves
  almost nothing.** A sample of 600 ``.docx`` carries zero format characters, zero
  soft hyphens and zero ligatures, and not one of those documents' findings changes;
  seven ``.docx`` do carry ``<w:softHyphen/>`` at XML level, but ``python-docx`` drops
  the element form, so it never reaches a scanner. Only the legacy ``.doc`` corpus
  moves at all. This half is **correct hardening against a defect that is real in the
  code and rare in today's corpus** — it is not the reason the baseline moves.
* **Whitespace-run collapsing.** *This* is the behavioural change. ``antiword``
  hard-wraps the legacy ``.doc`` corpus, so a JD saying "…or an equivalent\\n
  combination of education…" was reported as **missing the equivalency path** it
  plainly contains. Measured on a random 400-document ``.doc`` sample:
  ``SFU-QUAL-EQUIVALENT`` **74 -> 35**, i.e. 39 false positives (9.75% of legacy JDs)
  removed; **+3** findings gained where the wrap had been *hiding* real text (all three
  verified genuine); 42/400 documents change. Same class of false positive as HR-058,
  and the real reason this landed before the 2.5 baseline.

What is folded, and why:

* **Every Unicode format character (general category ``Cf``)** is dropped — the
  zero-width space / non-joiner / joiner (U+200B-200D), the BOM (U+FEFF), the soft
  hyphen (U+00AD), the word joiner (U+2060), the bidi marks. By *category*, so a
  format character nobody thought of cannot walk past the scanner.
* **Whitespace runs collapse** — but see :data:`PARAGRAPH`: the SCOPE of that collapse
  is a policy decision (``textnorm.yaml``, HR-108), and it is the only part of this
  module that is.
* **Typographic punctuation folds to its unambiguous ASCII counterpart** — curly
  quotes and apostrophes, the six dashes and the minus sign (U+2011, the non-breaking
  hyphen, is what Word puts inside ``in-kind``).
* **Latin ligatures** (U+FB00-FB04) expand: ``conﬁdential`` is ``confidential``.

Deliberately **out** of scope, because folding it would make two genuinely different
words collide — the scan must catch *more*, never confuse two things:

* **Accents and combining marks are preserved.** ``trüst`` is not the coded term
  ``trust``; a fold that stripped diacritics would invent findings.
* **No NFKC/NFKD.** Compatibility normalization rewrites far more than noise.
* **Case is not folded here.** The rulebook's regexes carry a per-pattern
  ``ignore_case`` flag (``patterns.yaml``) that folding the case away would silently
  override; the validator's matchers use ``re.IGNORECASE``. Only
  :mod:`~src.jd_core.quality.boilerplate`, which compares plain strings, asks for it.
* **Line-break dehyphenation.** ``in-\\nkind`` becomes ``in- kind``, not ``inkind``.

**Is any of this rule DATA (CLAUDE.md §2)?** The character folding is not. §2 makes
*decisions* configurable — things HR could reasonably want set differently — and "a
zero-width space is invisible" is not one: there is no defensible rulebook in which
``comp<U+200B>assionate`` escapes a scan for ``compassionate``. It is the same kind of
mechanical text fact as ``str.casefold()``, which is likewise not registered.

**The SCOPE of whitespace collapsing IS a decision, and it is registered (HR-108).**
Deciding that *any* run of whitespace — a line wrap, but also a paragraph break, a
section break, a table-cell boundary — is one space for matching purposes has a
defensible alternative, and it changes findings: joined across a paragraph break, the
unrelated paragraphs "Decides what" / "By whom is set elsewhere." become the
placeholder marker ``what by``, which feeds a **non-overridable** gate (HR-047) — a
permanently un-approvable JD invented out of normalization. So the shipped default is
**paragraph-aware**: runs collapse *within* a paragraph (which is what fixes the
``antiword`` hard-wrap false positives) and a paragraph break is a boundary a term
cannot span. ``textnorm.collapse_across_paragraph_break`` flips it, and the behavioural
tests prove the flip. The boundary costs nothing measurable: on the 400-``.doc`` and
599-``.docx`` samples, the two settings produce **byte-identical** findings — no archive
document currently has a term straddling a paragraph break — so it is the whole win
plus insurance.

**Partial gap, stated rather than buried.** A paragraph break is detected as a *blank
line*. ``ingest/extract.py`` joins ``.docx`` paragraphs with a single ``\\n`` and drops
empty ones — but ``if p.text`` drops only the *truly* empty ones, so a whitespace-only
paragraph (``" "``) survives and yields ``"\\n \\n"``, which **is** a boundary.
Measured on 799 archive ``.docx``: 101 carry a literal blank line, 329 a
whitespace-only paragraph — **373 (47%) do get a boundary**. The gap is the other
~53%, whose adjacent paragraphs are separated by a single ``\\n`` and are still joined
for matching. The legacy ``.doc`` (antiword) corpus — where the wrapping problem
actually lives — is covered in full (498/498). Closing the ``.docx`` half means
changing the extractor's paragraph separator, which rewrites the stored raw text the
segmenter reads; that is its own change (recorded in the backlog).

This also means the byte-identical result above is **not vacuous**: the boundary is
genuinely exercised (100% of ``.doc``, 47% of ``.docx``) and *still* changes no
finding.

**Offsets.** :class:`FoldedText` keeps an origin map, so a match found in folded space
is reported in the coordinates of the ORIGINAL text. Every evidence snippet a finding
quotes is sliced from the JD's own bytes — never from this rendering of them.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Final

#: Unicode general category "format": invisible characters that carry no text.
#: Dropped wholesale — see the module docstring.
_FORMAT_CATEGORY: Final[str] = "Cf"

#: What a whitespace run that crosses a paragraph break folds to when the rulebook
#: says a paragraph is a boundary (the shipped default, HR-108). U+2029 PARAGRAPH
#: SEPARATOR earns the job three times over: no rule term contains it, so a multi-word
#: term cannot match across it; it *is* whitespace, so the rulebook's own ``\s``
#: patterns behave exactly as they do on the raw text; and it folds to itself, which
#: keeps the fold idempotent.
PARAGRAPH: Final[str] = " "

#: One line terminator. Counted to tell a WRAP (one break — collapse it; that is the
#: antiword artefact) from a PARAGRAPH break (a blank line, i.e. two or more).
_LINE_BREAK: Final[re.Pattern[str]] = re.compile(
    "\r\n|[\n\r\v\f\x1c\x1d\x1e\x85\u2028\u2029]"
)

#: Characters a ``.docx``/PDF extraction produces where the rulebook (and our rule
#: data) has ASCII. Folded so a JD is not scanned differently because Word gave it a
#: smart quote. NOT a general unicode normalization: every entry has an unambiguous
#: ASCII counterpart, and nothing here can make two different words collide.
_FOLD: Final[dict[str, str]] = {
    # curly / typographic quotes and apostrophes
    "‘": "'",
    "’": "'",
    "‚": "'",
    "‛": "'",
    "′": "'",
    "“": '"',
    "”": '"',
    "„": '"',
    "″": '"',
    # dashes and the minus sign (U+2011 is the non-breaking hyphen Word writes
    # inside "in-kind", a `medium` coded term)
    "‐": "-",
    "‑": "-",
    "‒": "-",
    "–": "-",
    "—": "-",
    "―": "-",
    "−": "-",
    # Latin ligatures: "confidential" written with one is still the coded term
    "ﬀ": "ff",
    "ﬁ": "fi",
    "ﬂ": "fl",
    "ﬃ": "ffi",
    "ﬄ": "ffl",
}


def _fold_char(char: str) -> str:
    """``char`` with its noise folded away — ``""`` when it is invisible.

    Whitespace is returned as-is (the caller collapses runs of it); a format character
    disappears; a typographic character becomes its ASCII counterpart.
    """
    if unicodedata.category(char) == _FORMAT_CATEGORY:
        return ""
    return _FOLD.get(char, char)


def _is_paragraph_break(run: str) -> bool:
    """Is this whitespace run a paragraph break rather than a line wrap?

    A blank line — two or more line terminators. ``antiword`` separates paragraphs
    that way and wraps *within* a paragraph with a single one, and that difference is
    the whole point of the distinction. U+2029 says so outright.
    """
    return PARAGRAPH in run or len(_LINE_BREAK.findall(run)) >= 2


@dataclass(frozen=True)
class FoldedText:
    """A JD's text in both the form it was written and the form it is READ in.

    :attr:`raw` is the original, untouched — it is what every evidence snippet is
    sliced from. :attr:`folded` is the same text with invisible and typographic noise
    gone, and it is what patterns are matched against. :attr:`origin` maps the second
    back onto the first: ``origin[i]`` is the index in :attr:`raw` of the character
    that folded character ``i`` came from.

    The map is the whole point. Without it, normalizing the text would silently
    corrupt every position, span and quoted snippet a finding reports — the finding
    would be right and its evidence would point somewhere else.
    """

    raw: str
    folded: str
    origin: tuple[int, ...]

    def to_raw(self, start: int, end: int) -> tuple[int, int]:
        """The ``[start, end)`` span of :attr:`folded` in :attr:`raw` coordinates.

        ``end`` is exclusive and the span must be non-empty (an empty match has no
        position to report). The returned end is one past the LAST original character
        that contributed to the match, so a fold that dropped a zero-width space just
        after the term leaves it outside the span rather than swallowing it.
        """
        if not 0 <= start < end <= len(self.origin):
            raise ValueError(  # pragma: no cover - defensive
                f"span [{start}, {end}) is not a non-empty span of the folded text"
            )
        return self.origin[start], self.origin[end - 1] + 1


def fold_text(
    text: str, *, join_paragraphs: bool, casefold: bool = False
) -> FoldedText:
    """``text`` paired with its folded form and the map back to the original.

    Pure. See the module docstring for exactly what is folded.

    ``join_paragraphs`` is the rulebook's ``textnorm.collapse_across_paragraph_break``
    (HR-108). It has **no default on purpose**: it is a policy value, and a default
    here would be a second home for it (the ``max_listed`` duplicate-knob lesson).
    ``False`` — what the rulebook ships — collapses a wrap but leaves :data:`PARAGRAPH`
    standing at a blank line, so a term cannot match across two unrelated paragraphs.
    Callers folding a single-line rule term, for which the setting cannot matter, say
    so at the call site.

    ``casefold`` also lower-cases the folded form, for callers that compare plain
    strings rather than running a case-insensitive regex.
    """
    out: list[str] = []
    origin: list[int] = []
    #: Where the pending whitespace run started, and what it holds. A run collapses to
    #: ONE character, whose origin is where the run STARTED — so `origin` never goes
    #: backwards and every folded character maps onto a character it came from.
    run_at: int | None = None
    run: list[str] = []
    for index, char in enumerate(text):
        folded = _fold_char(char)
        if not folded:
            continue
        if folded.isspace():
            if out:  # a LEADING run emits nothing
                run_at = index if run_at is None else run_at
                run.append(folded)
            continue
        if run_at is not None:
            crosses = not join_paragraphs and _is_paragraph_break("".join(run))
            out.append(PARAGRAPH if crosses else " ")
            origin.append(run_at)
            run_at, run = None, []
        piece = folded.casefold() if casefold else folded
        out.extend(piece)
        origin.extend([index] * len(piece))
    return FoldedText(raw=text, folded="".join(out), origin=tuple(origin))


def fold(text: str, *, join_paragraphs: bool, casefold: bool = False) -> str:
    """``text`` with its invisible and typographic noise folded away."""
    return fold_text(text, join_paragraphs=join_paragraphs, casefold=casefold).folded

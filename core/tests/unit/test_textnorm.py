"""The one fold: what counts as invisible / typographic noise in a JD's text.

:mod:`src.jd_core.textnorm` is the single definition every scanner reads a JD through.
This suite pins it from four sides:

* **What it folds** — a ``.docx``/``antiword`` artefact must not hide text from the
  scanner. Zero-width characters, soft hyphens, BOMs, non-breaking spaces, smart
  quotes, non-breaking hyphens and Latin ligatures all fold away. (In *code* the
  invisible-character defect is total; on today's archive that half moves almost
  nothing and the whitespace half moves everything — see the module docstring. Do not
  read this suite as evidence about the corpus.)
* **What it refuses to fold** — normalization that went further would make two
  genuinely different words collide, which is how a scanner acquires a false positive.
  Accents stay. Compatibility characters stay. Case stays.
* **The paragraph boundary** — the one policy call in the module (HR-108). A line WRAP
  collapses (that is the antiword artefact, and the real archive win); a PARAGRAPH
  break does not, because joining two unrelated paragraphs *invents* findings.
* **The origin map** — a match found in folded space must be reportable in the
  ORIGINAL text's coordinates, or every evidence snippet silently points elsewhere.
"""

from __future__ import annotations

import sys
import unicodedata

import pytest

from src.jd_core.textnorm import PARAGRAPH, FoldedText, fold, fold_text

#: Invisible characters a Word/`.docx` export can leave in a document. All Unicode
#: general category "Cf" (format) — the category the fold drops wholesale.
INVISIBLE = {
    "zero-width space": "​",
    "zero-width non-joiner": "‌",
    "zero-width joiner": "‍",
    "left-to-right mark": "‎",
    "right-to-left mark": "‏",
    "byte-order mark / zero-width no-break space": "﻿",
    "soft (discretionary) hyphen": "­",
    "word joiner": "⁠",
    "left-to-right embedding": "‪",
}

#: Whitespace an extraction produces where a plain document has a single space.
BLANKS = {
    "non-breaking space": " ",
    "narrow no-break space": " ",
    "figure space": " ",
    "thin space": " ",
    "em space": " ",
    "line feed": "\n",
    "carriage return + line feed": "\r\n",
    "tab": "\t",
    "line separator": " ",
    "ideographic space": "　",
}


# --- what folds ---------------------------------------------------------------


@pytest.mark.parametrize(("label", "char"), sorted(INVISIBLE.items()))
def test_an_invisible_character_disappears_from_the_folded_text(
    label: str, char: str
) -> None:
    """``comp<ZWSP>assionate`` is not the word ``compassionate`` to a regex, and it IS
    the word ``compassionate`` to a human."""
    assert unicodedata.category(char) == "Cf", label  # the rule the fold applies
    assert fold(f"comp{char}assionate", join_paragraphs=False) == "compassionate", label
    assert fold(f"{char}compassionate{char}", join_paragraphs=False) == "compassionate"


def test_the_fold_drops_format_characters_by_category_not_by_a_hand_written_list() -> (
    None
):
    """A format character nobody thought of must not walk past the scanner.

    Swept over all of Unicode: every ``Cf`` codepoint folds away, whether or not it is
    one of the nine :data:`INVISIBLE` ones we happened to name.
    """
    formats = [
        chr(cp) for cp in range(sys.maxunicode) if unicodedata.category(chr(cp)) == "Cf"
    ]
    assert len(formats) > len(INVISIBLE)  # the sweep is not vacuous
    assert fold("".join(formats), join_paragraphs=False) == ""
    assert fold("a" + "".join(formats) + "b", join_paragraphs=False) == "ab"


@pytest.mark.parametrize(("label", "blank"), sorted(BLANKS.items()))
def test_every_flavour_of_whitespace_collapses_to_one_plain_space(
    label: str, blank: str
) -> None:
    """The half of the fold that actually moves the archive: ``antiword`` hard-wraps
    the legacy corpus, so a two-word term like ``may include`` was missed across the
    wrap; and Word writes non-breaking spaces.

    Note what is NOT asserted: ``blank * 3`` for a line terminator is a BLANK LINE, and
    that is a paragraph break, not a wrap — it collapses to :data:`PARAGRAPH`, not to a
    space. See the HR-108 tests. A run of *mixed* whitespace with one line break in it
    is still a wrap, which is the shape ``antiword`` actually emits.
    """
    assert fold(f"may{blank}include", join_paragraphs=False) == "may include", label
    assert fold(f"may{blank} \t include", join_paragraphs=False) == "may include", label


def test_leading_and_trailing_whitespace_is_dropped() -> None:
    assert fold("  \n assets \t ", join_paragraphs=False) == "assets"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Canada’s", "Canada's"),  # right single quote — what a .docx writes
        ("Canada‘s", "Canada's"),
        ("“quoted”", '"quoted"'),
        ("in‑kind", "in-kind"),  # non-breaking hyphen: the coded term `in-kind`
        ("man–hours", "man-hours"),  # en dash
        ("man—hours", "man-hours"),  # em dash
        ("man−hours", "man-hours"),  # minus sign
        ("conﬁdential", "confidential"),  # ligature: the coded term
        ("staﬀ", "staff"),
        ("ﬂag", "flag"),
    ],
)
def test_typographic_characters_fold_to_their_unambiguous_ascii_spelling(
    raw: str, expected: str
) -> None:
    assert fold(raw, join_paragraphs=False) == expected


# --- the paragraph boundary: the one DECISION in this module (HR-108) ----------


def test_a_line_wrap_collapses_but_a_paragraph_break_does_not() -> None:
    """The shipped default, and the whole argument for it in three lines.

    A single line break is ``antiword`` wrapping a paragraph — collapse it; that is the
    fix that removes 39 false ``SFU-QUAL-EQUIVALENT`` findings from a 400-document
    legacy sample. A blank line is a real paragraph break: leave a boundary standing,
    because a term matched across it would have been assembled out of two unrelated
    paragraphs by our own text transform.
    """
    assert fold("equivalent\n     combination", join_paragraphs=False) == (
        "equivalent combination"
    )
    assert fold("Decides what\n\nBy whom", join_paragraphs=False) == (
        f"Decides what{PARAGRAPH}By whom"
    )


def test_collapsing_across_paragraphs_is_what_the_rulebook_switch_turns_on() -> None:
    """The other side of HR-108: flip it and the two paragraphs become one sentence —
    which is exactly how ``what by`` (a placeholder marker feeding a NON-OVERRIDABLE
    gate) gets invented out of "Decides what" + "By whom"."""
    assert fold("Decides what\n\nBy whom", join_paragraphs=True) == (
        "Decides what By whom"
    )


def test_the_paragraph_separator_is_whitespace_a_term_cannot_be_matched_across() -> (
    None
):
    """Why U+2029 and not a newline or a sentinel letter: no rule term contains it (so
    a multi-word term cannot span it), it IS whitespace (so the rulebook's own ``\\s``
    regexes behave exactly as they do on the raw text), and it folds to itself (so the
    fold stays idempotent)."""
    assert PARAGRAPH.isspace()
    assert unicodedata.category(PARAGRAPH) == "Zp"
    assert fold(f"a{PARAGRAPH}b", join_paragraphs=False) == f"a{PARAGRAPH}b"


@pytest.mark.parametrize("join", [True, False])
def test_folding_an_already_folded_text_changes_nothing(join: bool) -> None:
    text = "We want an agg​ressive﻿ self-starter.\n\nApply  now."
    once = fold(text, join_paragraphs=join)
    assert fold(once, join_paragraphs=join) == once


# --- what deliberately does NOT fold ------------------------------------------


@pytest.mark.parametrize("word", ["résumé", "trüst", "hönest"])
def test_accents_survive_the_fold(word: str) -> None:
    """The loophole a more aggressive fold would open. ``trust`` and ``honest`` are
    both coded terms; a fold that stripped diacritics would land ``trüst`` — a
    different word — on one of them, inventing a finding. Catch MORE, never confuse."""
    assert fold(word, join_paragraphs=False) == word


@pytest.mark.parametrize("text", ["½", "㎥", "①", "Ａ"])
def test_the_fold_is_not_nfkc(text: str) -> None:
    """Compatibility normalization rewrites far more than noise (½ -> 1⁄2, ㎥ -> m3,
    ① -> 1, fullwidth A -> A). An enumerated fold is auditable; NFKC is not."""
    assert fold(text, join_paragraphs=False) == text
    assert unicodedata.normalize("NFKC", text) != text  # ...and NFKC would have moved


def test_case_is_not_folded_unless_the_caller_asks() -> None:
    """The rulebook's regexes carry a per-pattern ``ignore_case`` flag
    (``patterns.yaml``); folding the case away here would silently override a rule that
    asked to be case-sensitive. Only the boilerplate matcher, which compares plain
    strings, asks for it."""
    assert fold("Compassionate", join_paragraphs=False) == "Compassionate"
    assert fold("Compassionate", join_paragraphs=False, casefold=True) == (
        "compassionate"
    )


def test_a_real_hyphen_and_a_real_space_are_left_alone() -> None:
    """The fold removes noise, it does not glue words together. ``man power`` must not
    become the coded term ``manpower``, and ``in-\\nkind`` must not become ``inkind``:
    rejoining across a real separator would weld distinct words."""
    assert fold("man power", join_paragraphs=False) == "man power"
    assert fold("in-\nkind", join_paragraphs=False) == "in- kind"


# --- the origin map: evidence must still point at the ORIGINAL text ------------


def test_the_origin_map_takes_a_folded_span_back_to_the_original_text() -> None:
    text = "We want an agg​ressive﻿ self-starter."
    folded = fold_text(text, join_paragraphs=False)
    assert folded.folded == "We want an aggressive self-starter."

    at = folded.folded.index("aggressive")
    start, end = folded.to_raw(at, at + len("aggressive"))
    # The span points at the JD's OWN bytes — zero-width space and all.
    assert text[start:end] == "agg​ressive"
    assert folded.raw is text


def test_every_folded_character_maps_back_to_the_character_it_came_from() -> None:
    """The invariant the whole offset story rests on, asserted per character."""
    text = " ​An ADVANCED­ skill:  Canada’s conﬁdential file.\n\nNext para. "
    folded = fold_text(text, join_paragraphs=False)
    assert len(folded.origin) == len(folded.folded)
    for index in range(len(folded.folded)):
        start, end = folded.to_raw(index, index + 1)
        assert 0 <= start < end <= len(text)
        source = text[start:end]
        # the original character behind this folded one folds to it (or, for a
        # ligature, to a piece containing it; a collapsed run maps to its own start)
        assert (
            folded.folded[index] in fold(source, join_paragraphs=False)
            or source.isspace()
        )


def test_the_empty_text_folds_to_nothing_and_has_no_spans() -> None:
    assert fold_text("", join_paragraphs=False) == FoldedText(
        raw="", folded="", origin=()
    )
    assert fold("​­﻿", join_paragraphs=False) == ""  # noise and nothing else

"""``jd_core.bank.shingles`` — the Tier-2 shingling pipeline (Phase 3.3).

Every pin here is against a LITERAL expected value, not merely a type or a
range — the exact failure mode this module exists to catch is someone reaching for
Python's salted ``hash()`` instead of ``blake2b``, which would still "work" (return an
int, still deterministic WITHIN one process) but disagree across processes. Only a
literal expected number goes red on that regression.
"""

from __future__ import annotations

from array import array

from src.jd_core.bank.shingles import (
    _TOKEN_RE,
    _hash_gram,
    shingle_hashes,
    tokenize,
)
from src.jd_core.quality.boilerplate import redact_passages
from src.jd_core.textnorm import PARAGRAPH, fold

_FOX = "The quick brown fox jumps over the lazy dog."

# Computed once via `hashlib.blake2b(gram.encode(), digest_size=8)`, big-endian —
# see the module docstring. If this ever changes, either the hash function changed
# (a deliberate SHINGLE_VERSION bump) or something started using a salted `hash()`.
_FOX_HASHES_K5 = array(
    "Q",
    sorted(
        [
            4800378933827958851,
            6573469244424666089,
            11033456989573087361,
            14029935466038595319,
            14540364934603910825,
        ]
    ),
)


def test_tokenize_splits_on_non_alnum() -> None:
    # tokenize() itself does not lower-case or fold anything — that is fold()'s job
    # upstream (shingle_hashes always folds+casefolds before calling this). Called
    # directly on already-lowercase text here, matching how shingle_hashes uses it.
    assert tokenize("hello, world! 123") == ("hello", "world", "123")


def test_shingle_hashes_is_a_literal_pinned_value_for_a_literal_input() -> None:
    """THE regression test for salted `hash()`: if `_hash_gram` ever used Python's
    built-in `hash()` instead of `blake2b`, this would still return 5 ints — just
    different ones, and different again on the next process. Pinning the literal
    values is what makes that regression visible."""
    hashes = shingle_hashes(_FOX, shingle_size=5, redact_boilerplate=False)
    assert hashes == _FOX_HASHES_K5


def test_shingle_hashes_is_deterministic_across_repeated_calls() -> None:
    """The same call, twice in the SAME process, must agree — necessary but not
    sufficient (see the literal-pin test above for the cross-process guarantee)."""
    first = shingle_hashes(_FOX, shingle_size=5, redact_boilerplate=False)
    second = shingle_hashes(_FOX, shingle_size=5, redact_boilerplate=False)
    assert first == second
    assert list(first) == sorted(first)  # sorted, as documented


def test_shingle_hashes_returns_distinct_hashes_only() -> None:
    """A repeated gram must not duplicate its hash — the array is a SET, expressed
    as a sorted array. "a b" repeated 4 times, k=2: 7 overlapping 2-grams total
    (indices 0..6), alternating "a b" / "b a" — only 2 DISTINCT grams."""
    repeated = "a b a b a b a b"
    hashes = shingle_hashes(repeated, shingle_size=2, redact_boilerplate=False)
    assert len(hashes) == 2
    assert len(set(hashes)) == len(hashes)


def test_a_doc_hard_wrapped_twin_and_a_docx_paragraph_twin_shingle_identically() -> (
    None
):
    """THE archetypal Tier-2 positive. `.doc` (antiword) never carries a blank-line
    paragraph break at all — the whole document is one wrapped stream. `.docx`
    (python-docx, joined by ``jd_bank.ingest.extract._extract_docx``) sometimes DOES
    carry one, wherever an empty paragraph survived. They must shingle to
    byte-for-byte identical sets.

    ⚠ The mechanism is the TOKENIZER, not `join_paragraphs=True` — see
    `test_the_tokenizer_is_what_makes_hr108_irrelevant` below, and the module
    docstring. THIS test's original docstring claimed the opposite ("if the shingler
    consulted HR-108 these two would NOT shingle identically"), which was false: the
    reviewer made `shingles.py` consult HR-108 and every test here stayed GREEN. The
    property is real; only the stated reason was invented, and it was pinned by
    nothing. The two tests below are what actually go red.
    """
    doc_style = (  # antiword: no blank line, just wrapped single newlines
        "The quick brown fox jumps over the lazy dog. It was a bright cold\n"
        "day in April."
    )
    docx_style = (  # python-docx: an actual paragraph break survived as "\n\n"
        "The quick brown fox jumps over the lazy dog.\n\nIt was a bright cold day "
        "in April."
    )
    assert doc_style != docx_style  # a real structural difference between the two

    doc_hashes = shingle_hashes(doc_style, shingle_size=5, redact_boilerplate=False)
    docx_hashes = shingle_hashes(docx_style, shingle_size=5, redact_boilerplate=False)
    assert doc_hashes == docx_hashes


def test_the_tokenizer_is_what_makes_hr108_irrelevant() -> None:
    """**THE pin the module's HR-108-independence actually rests on**, and the one the
    first cut was missing entirely.

    `textnorm.PARAGRAPH` is U+2029; `shingles._TOKEN_RE` is `[a-z0-9]+`, which does
    not match it. So `fold(..., join_paragraphs=...)` decides only whether a U+2029
    sits between two paragraphs in the folded string — and the tokenizer **discards it
    at either setting**. The token stream, and therefore every gram and every hash, is
    identical. That — not the `join_paragraphs=True` argument `shingle_hashes` passes
    — is why flipping HR-108 cannot re-shingle the archive.

    Goes red if the tokenizer ever starts treating the paragraph separator as
    something other than a discarded character (e.g. a token boundary that TERMINATES
    a gram), which is exactly the regression `shingles.py` exists to prevent.
    """
    text = "alpha beta gamma\n\ndelta epsilon zeta"
    joined = fold(text, join_paragraphs=True, casefold=True)
    split = fold(text, join_paragraphs=False, casefold=True)

    # The two FOLDS genuinely differ — this is not a vacuous comparison.
    assert joined != split
    assert PARAGRAPH in split
    assert PARAGRAPH not in joined

    # ...and the TOKENIZER erases that difference completely.
    assert tokenize(joined) == tokenize(split)
    assert not _TOKEN_RE.match(PARAGRAPH)


def test_a_gram_spans_a_paragraph_break() -> None:
    """The behavioural half of the same fact: a gram REACHES ACROSS a paragraph break.
    A shingler that respected paragraph structure (whatever mechanism it used to do
    so) could not produce this gram, so this goes red the moment one does."""
    text = "alpha beta gamma\n\ndelta epsilon zeta"
    hashes = shingle_hashes(text, shingle_size=3, redact_boilerplate=False)

    # "gamma delta epsilon" straddles the break. Recompute its hash independently,
    # from the literal gram, and demand it is in the set.
    crossing = _hash_gram("gamma delta epsilon")
    assert crossing in set(hashes)

    # 6 tokens, k=3 -> exactly 4 grams, i.e. the break costs us nothing.
    assert len(hashes) == 4


def test_paragraph_breaks_never_change_the_shingle_set_however_many_there_are() -> None:
    one_break = "alpha beta gamma delta epsilon zeta eta theta iota\n\nkappa lambda"
    many_breaks = (
        "alpha beta gamma delta epsilon zeta eta theta iota\n\n\n\nkappa lambda"
    )
    no_break = "alpha beta gamma delta epsilon zeta eta theta iota kappa lambda"
    assert (
        shingle_hashes(one_break, shingle_size=3, redact_boilerplate=False)
        == shingle_hashes(many_breaks, shingle_size=3, redact_boilerplate=False)
        == shingle_hashes(no_break, shingle_size=3, redact_boilerplate=False)
    )


def test_redaction_matches_a_passage_split_across_a_paragraph_break() -> None:
    """**The `join_paragraphs=True` that IS load-bearing** — the one passed to
    `redact_passages`, not the one passed to `fold`.

    Redaction matches SFU's mandated text BEFORE tokenization, in folded space. So a
    mandated passage that the extractor split across a paragraph break (a real `.docx`
    shape — python-docx emits paragraph-per-paragraph) is only cut at
    `join_paragraphs=True`. This is a DELIBERATE deviation from HR-108's shipped
    `False`, and the first cut pinned it with nothing (every redaction fixture was
    single-line, where the setting cannot matter).

    Goes red if `shingle_hashes` is ever changed to pass HR-108's value through to
    `redact_passages` — the passage would stop being cut, and its grams would come back.
    """
    passage = "Simon Fraser University is a public research university"
    # The JD carries the mandated sentence, but the extractor split it in two.
    doc = (
        "Simon Fraser University is\n\na public research university "
        "and here is some unrelated widget prose about turbines."
    )

    redacted = shingle_hashes(
        doc, shingle_size=4, redact_boilerplate=True, boilerplate_passages=(passage,)
    )
    unredacted = shingle_hashes(doc, shingle_size=4, redact_boilerplate=False)

    # The passage's own grams are GONE from the redacted set...
    passage_gram = _hash_gram("simon fraser university is")
    assert passage_gram in set(unredacted)
    assert passage_gram not in set(redacted)
    assert len(redacted) < len(unredacted)

    # ...and this only works because redaction folds with join_paragraphs=True. At
    # HR-108's shipped `False` the passage is NOT found across the break — proved
    # directly against the redactor, so the deviation is pinned rather than asserted.
    assert (
        redact_passages(doc, [passage], join_paragraphs=True) != doc
    ), "the passage should be cut when paragraphs are joined"
    assert redact_passages(doc, [passage], join_paragraphs=False) == doc, (
        "at HR-108's shipped False the split passage is NOT matched — "
        "the deviation is real"
    )


def test_redact_boilerplate_removes_shared_mandated_text_from_the_shingle_set() -> None:
    """Two JDs sharing ONLY SFU's mandated boilerplate, and NOTHING else, must
    shingle to (near-)zero overlap once redacted — and to a large positive overlap
    when redaction is off. Mutation-pinned: flip `redact_boilerplate` and the
    Jaccard swings from ~0 to a real number, not merely "the flag was read"."""
    passages = (
        "Simon Fraser University is a public research university that values "
        "engagement in local and global communities.",
    )
    doc_a = (
        passages[0] + " Widgets and gadgets manufacturing processes take priority "
        "over turbine efficiency logistics scheduling today."
    )
    doc_b = (
        passages[0] + " Turtles and rivers ecosystems research programs examine "
        "salmon migration patterns across watershed boundaries yearly."
    )

    redacted_a = shingle_hashes(
        doc_a, shingle_size=5, redact_boilerplate=True, boilerplate_passages=passages
    )
    redacted_b = shingle_hashes(
        doc_b, shingle_size=5, redact_boilerplate=True, boilerplate_passages=passages
    )
    unredacted_a = shingle_hashes(doc_a, shingle_size=5, redact_boilerplate=False)
    unredacted_b = shingle_hashes(doc_b, shingle_size=5, redact_boilerplate=False)

    shared_redacted = set(redacted_a) & set(redacted_b)
    shared_unredacted = set(unredacted_a) & set(unredacted_b)

    assert len(shared_redacted) == 0, "the mandated passage leaked past redaction"
    assert len(shared_unredacted) > 0, "the two docs should share the passage's grams"


def test_shingle_size_changes_the_shingle_set_not_just_its_size() -> None:
    """5 -> 4 must change WHICH hashes appear, not merely produce a different count
    by coincidence — a caller retuning `shingle_size` must re-shingle everything."""
    hashes_k5 = shingle_hashes(_FOX, shingle_size=5, redact_boilerplate=False)
    hashes_k4 = shingle_hashes(_FOX, shingle_size=4, redact_boilerplate=False)
    assert hashes_k5 != hashes_k4
    assert set(hashes_k5).isdisjoint(hashes_k4) or set(hashes_k5) != set(hashes_k4)


def test_text_shorter_than_shingle_size_yields_an_empty_array_not_an_error() -> None:
    hashes = shingle_hashes(
        "only three words", shingle_size=5, redact_boilerplate=False
    )
    assert hashes == array("Q")
    assert len(hashes) == 0


def test_redact_boilerplate_false_ignores_boilerplate_passages_entirely() -> None:
    """When the knob is off, passing passages must be a no-op — no accidental
    partial redaction from a stray truthy branch."""
    text = "Simon Fraser University is great and also widgets today extra words."
    with_passages = shingle_hashes(
        text,
        shingle_size=5,
        redact_boilerplate=False,
        boilerplate_passages=("Simon Fraser University is great",),
    )
    without_passages = shingle_hashes(text, shingle_size=5, redact_boilerplate=False)
    assert with_passages == without_passages

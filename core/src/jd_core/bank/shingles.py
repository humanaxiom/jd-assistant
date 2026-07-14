"""Word-shingle fingerprints for Tier-2 near-duplicate detection (Phase 3.3).

Pure — no I/O, no ``jd_bank`` import (the ``jd_core``/``jd_bank`` ratchet). Pipeline::

    clean text
      -> (if redact_boilerplate) redact SFU's mandated passages
      -> fold(join_paragraphs=True, casefold=True)
      -> tokenize [a-z0-9]+
      -> contiguous k-word grams
      -> blake2b(digest_size=8) 64-bit hash each
      -> frozen SORTED array('Q') of DISTINCT hashes

**Why shingle Jaccard, not document cosine.** MEASURED on the real archive (HANDOFF
2026-07-13): nearest-neighbour document cosine has median **0.988**, with 98% of docs
sitting at or above 0.92 — every SFU JD is written in the same register, the same
template, the same vocabulary, so cosine barely discriminates at all. Nearest-neighbour
word-5-gram Jaccard has median **0.126**; random-pair Jaccard has median 0.0022, p99.9
0.30. Jaccard is the signal that actually separates true near-duplicates from unrelated
JDs on this corpus; cosine does not.

**Boilerplate redaction reuses ``jd_core.quality.boilerplate.redact_passages`` — one
rulebook fact, one home.** A second redactor here would drift from HR-058's mechanism
(the ``max_listed`` duplicate-knob landmine). Callers pass the passages explicitly
(``rules.boilerplate.about_sfu + .territorial_acknowledgement + .employment_equity``)
rather than this module reading ``boilerplate.yaml`` itself.

**``hashlib.blake2b``, NEVER Python's ``hash()``.** ``hash()`` on ``str`` is salted per
process (``PYTHONHASHSEED``), so two runs of this pipeline over the SAME text would
disagree on every gram's hash — nothing would go red, the shingle sets would just
silently stop being comparable across processes. ``test_minhash.py`` /
``test_shingles.py`` pin a LITERAL expected hash for a literal input for exactly this
reason: a salted-``hash()`` regression changes the number, not just the type.

**This module is INDEPENDENT OF HR-108 (``textnorm.collapse_across_paragraph_break``),
and the mechanism is the TOKENIZER, not the ``join_paragraphs=True`` argument.** Read
this carefully, because the first cut of this file got the *reason* wrong while getting
the *behaviour* right, and shipped a test that could not fail.

The property that matters: flipping HR-108 — a *scanner* decision about whether a
coded-term match may reach across a blank line — must never silently re-shingle the
archive. It doesn't, and here is why it actually doesn't:
:data:`~src.jd_core.textnorm.PARAGRAPH` is **U+2029**, and :data:`_TOKEN_RE` is
``[a-z0-9]+``, which does not match it. So the fold's ``join_paragraphs`` argument
decides only whether the folded string carries a U+2029 between two paragraphs — and
the tokenizer **discards it either way**. The token stream, every gram (INCLUDING a
gram that spans a paragraph break), and therefore every hash, are byte-identical at
both settings. Pinned by ``test_shingles.py::
test_the_tokenizer_is_what_makes_hr108_irrelevant`` (the token streams are equal) and
``::test_a_gram_spans_a_paragraph_break`` (the cross-break gram exists).

⚠ The `join_paragraphs=True` we pass to :func:`~src.jd_core.textnorm.fold` below is
therefore **inert** for the shingles, and is passed only because the parameter has no
default (deliberately — HR-108 has one home, and a default here would be a second one).
The ORIGINAL claim in this docstring — *"joining paragraphs unconditionally is what
makes a `.doc` and its `.docx` twin produce identical shingles"* — was **FALSE**: they
produce identical shingles because the tokenizer throws the separator away. The twin
property is real and is still pinned; only the explanation was invented.

⚠ **The `join_paragraphs=True` passed to :func:`redact_passages` (below) is a
different argument and IS load-bearing** — redaction matches SFU's mandated text
*before* tokenization, in folded space, so a mandated passage that the extractor split
across a paragraph break is redacted at ``True`` and **not** at ``False``. That is a
deliberate deviation from HR-108's shipped ``False``, and it is pinned by
``test_shingles.py::test_redaction_matches_a_passage_split_across_a_paragraph_break``.

**``array('Q')`` sorted, not ``set[int]``.** MEASURED: storing the corpus's shingle
hashes as Python ``set[int]`` costs ~1.07 GB; as sorted ``array('Q')`` it costs
~0.14 GB. A sorted array also gives :func:`~src.jd_core.bank.minhash.exact_jaccard` a
linear merge-intersection instead of a hash-set intersection.
"""

from __future__ import annotations

import hashlib
import re
from array import array
from collections.abc import Sequence
from typing import Final

from src.jd_core.quality.boilerplate import redact_passages
from src.jd_core.textnorm import fold

#: Bump when this module's OUTPUT changes for the same input (a code change, not a
#: rulebook change — a rulebook change already moves ``Dedup.stamp``). Mirrors
#: ``embed_text.SERIALIZER_VERSION``.
SHINGLE_VERSION: Final[str] = "shingles_v1"

#: A "word" for shingling purposes: a maximal run of ASCII letters/digits. Applied
#: AFTER ``fold(..., casefold=True)``, so case and typographic noise are already gone —
#: this only decides where a word boundary falls.
_TOKEN_RE: Final[re.Pattern[str]] = re.compile(r"[a-z0-9]+")

#: blake2b output width in bytes. 8 bytes = 64 bits — plenty of headroom against
#: collision at corpus scale (~14.5k documents, tens of shingles each) while keeping
#: each hash small enough that ``array('Q')`` (unsigned 64-bit) holds it exactly.
_DIGEST_SIZE: Final[int] = 8


def tokenize(text: str) -> tuple[str, ...]:
    """``text`` split into lower-case ``[a-z0-9]+`` tokens.

    Pure. Callers normally hand this already-folded text (see :func:`shingle_hashes`),
    but it is exposed standalone because both the shingler and the fixture tests want
    to assert on the token stream directly, not just the hashes it produces.
    """
    return tuple(_TOKEN_RE.findall(text))


def _hash_gram(gram: str) -> int:
    """A gram's 64-bit fingerprint. ``blake2b``, NEVER ``hash()`` — see module
    docstring. Big-endian: an arbitrary but FIXED byte order, so the integer value is
    the same on every machine and every process (unlike ``hash()``, which is salted
    per-process for ``str``)."""
    digest = hashlib.blake2b(gram.encode("utf-8"), digest_size=_DIGEST_SIZE).digest()
    return int.from_bytes(digest, "big")


def shingle_hashes(
    text: str,
    *,
    shingle_size: int,
    redact_boilerplate: bool,
    boilerplate_passages: Sequence[str] = (),
) -> array[int]:
    """The frozen, SORTED, DISTINCT set of ``shingle_size``-word-gram hashes in
    ``text`` — an ``array('Q')`` (unsigned 64-bit), never a ``set[int]`` (see module
    docstring for the measured memory difference).

    Returns an EMPTY array (never raises, never ``None``) when ``text`` yields fewer
    than ``shingle_size`` tokens — there is nothing to gram. Whether that count also
    falls below the rulebook's ``min_shingles`` guard-rail (a policy decision, not a
    fact about this text) is for the caller to check; this function only reports what
    the text actually contains.

    ``redact_boilerplate`` cuts every verbatim occurrence of a passage in
    ``boilerplate_passages`` before shingling (via
    :func:`~src.jd_core.quality.boilerplate.redact_passages`). When ``False``,
    ``boilerplate_passages`` is ignored entirely (never even folded), so a caller need
    not assemble the passage list on the disabled path.
    """
    working = text
    if redact_boilerplate and boilerplate_passages:
        # `join_paragraphs=True` here IS load-bearing (unlike the identical argument on
        # the `fold` below, which the tokenizer renders inert — module docstring):
        # redaction matches SFU's mandated text BEFORE tokenization, so a passage the
        # extractor split across a paragraph break is only cut at `True`. A deliberate
        # deviation from HR-108's shipped `False`, pinned by
        # `test_redaction_matches_a_passage_split_across_a_paragraph_break`.
        working = redact_passages(working, boilerplate_passages, join_paragraphs=True)

    # `join_paragraphs=True` is INERT for the shingles — `_TOKEN_RE` ([a-z0-9]+) does
    # not match `textnorm.PARAGRAPH` (U+2029), so the token stream is identical at
    # either setting and this module is HR-108-independent BY THE TOKENIZER, not by
    # this argument. It has no default on purpose (one home for HR-108), so a value
    # must be passed. See the module docstring; pinned by
    # `test_the_tokenizer_is_what_makes_hr108_irrelevant`.
    folded = fold(working, join_paragraphs=True, casefold=True)
    tokens = tokenize(folded)
    if len(tokens) < shingle_size:
        return array("Q")

    grams = (
        " ".join(tokens[i : i + shingle_size])
        for i in range(len(tokens) - shingle_size + 1)
    )
    distinct = {_hash_gram(gram) for gram in grams}
    return array("Q", sorted(distinct))

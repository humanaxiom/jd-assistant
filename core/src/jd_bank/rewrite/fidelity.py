"""Rewrite fidelity (owner ruling 2026-10-20: "fix the rewrite first").

Two jobs the 4.2a anti-fabrication guard needs and did not have, kept here so
:mod:`src.jd_bank.rewrite.harmonize` reads as the guard's decisions rather than its
string handling:

* **The source view** (:func:`source_view`). The merge draft as the rewrite should SEE
  it: minus the old questionnaire's own instructions to the author (HR-275/276) and
  minus SFU's boilerplate sentences (HR-273/274). Neither is role content, and both
  reached the merge draft through the parser — the questionnaire instructions in 30% of
  the v9 drafts, the EE statement and territorial acknowledgement as *qualification
  lines* in ~20%. The view is the prompt's input, the ONLY text anything may be
  grounded in, and the only text a restore may put back. The draft the producer keeps
  when the rewrite fails is untouched: the real fix for the instructions is in the
  parser, and that moves ``PARSER_VERSION`` and the placeholder gate.
* **Tokens and named terms.** The same ``[a-z0-9]+`` / stopword / min-length filter the
  guard already used (:func:`content_tokens`), plus :func:`named_terms` — acronyms and
  mid-sentence capitalized words, which HR-272 requires to be in the source verbatim.

Everything that decides something is rulebook data (``rewrite.yaml``); this module is
the matcher. Pure, deterministic, no I/O.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Final

from src.jd_core.models.parsed_jd import SFUDuty, SFUJobDescription, SFUQualification
from src.jd_core.rules import Comparison, Rules
from src.jd_core.textnorm import fold_text

#: A content token — the guard's existing alphabet (see ``harmonize._TOKEN``).
_TOKEN: Final[re.Pattern[str]] = re.compile(r"[a-z0-9]+")
#: A word as written, case kept, for :func:`named_terms`.
_WORD: Final[re.Pattern[str]] = re.compile(r"[A-Za-z0-9]+")
#: A sentence boundary: terminal punctuation followed by whitespace, or a line break.
_SENTENCE: Final[re.Pattern[str]] = re.compile(r"(?<=[.!?])\s+|\n+")
#: What may precede a sentence-initial word (an opening quote, bracket or bullet).
_OPENERS: Final[str] = " \t\"'(“‘[•◦*-–—"
#: Punctuation after which the next word starts a sentence (or a list lead-in).
_SENTENCE_END: Final[str] = ".!?:;\n"
#: Whitespace runs, collapsed only in text the stripper actually changed.
_SPACES: Final[re.Pattern[str]] = re.compile(r"\s+")


def content_tokens(text: str, comparison: Comparison) -> frozenset[str]:
    """Lowercase ``[a-z0-9]+`` runs minus stopwords and short tokens — the filter
    ``signals._skill_bag`` applies, so grounding lines up with skill comparison.

    The rewrite passes :func:`grounding_comparison` here, whose stopwords add English
    function words (HR-277). A NUMBER is kept whatever its length (review round 1): a
    one- or two-digit token fell under ``skill_min_token_len``, so "2 staff" -> "12
    staff" changed nothing the guard could see (HR-278 then requires it grounded)."""
    return frozenset(
        token
        for token in _TOKEN.findall(text.lower())
        if (len(token) >= comparison.skill_min_token_len or token.isdigit())
        and token not in comparison.skill_stopwords
    )


def grounding_comparison(rules: Rules) -> Comparison:
    """``rules.comparison`` with the rewrite's ``grounding_stopwords`` (HR-277) added to
    its stopwords — the token filter every rewrite-grounding test uses.

    ``comparison.skill_stopwords`` is a 20-word noise list for SKILL bags (HR-150): it
    drops "management" and "training" and keeps "and", "the", "for", "such". MEASURED
    (review round 1, pilot replay): those function words grounded an invented Decision
    Making item at exactly 0.5 and "covered" a lost source duty sentence at exactly 0.5
    (b13e6321 — "Marketing services on the Web and in print media…" left the draft and
    no record listed it). Not changed at the source: HR-150 drives skill comparison."""
    extra = rules.rewrite.grounding_stopwords
    if not extra:
        return rules.comparison
    return rules.comparison.model_copy(
        update={"skill_stopwords": rules.comparison.skill_stopwords | extra}
    )


def named_terms(
    text: str, comparison: Comparison, *, numbers: bool = False
) -> frozenset[str]:
    """The tokens of ``text`` written as NAMES: a word with two or more capitals
    (``ICOM``, ``TAs``, ``SolidWorks``), or a capitalized word that does not start a
    sentence ("…of the Coast Salish…"). Same token filter as :func:`content_tokens`.

    Deliberately conservative about what starts a sentence (after ``.!?:;``, a line
    break, a bullet or a hyphen): a word wrongly taken as sentence-initial is merely not
    checked, while a word wrongly taken as a name could scrub a faithful item."""
    found: set[str] = set()
    for match in _WORD.finditer(text):
        word = match.group(0)
        capitals = sum(1 for ch in word if ch.isupper())
        before = text[: match.start()].rstrip(_OPENERS)
        initial = not before or before[-1] in _SENTENCE_END
        if capitals >= 2 or (word[0].isupper() and not initial):
            token = word.lower()
            if (
                len(token) >= comparison.skill_min_token_len
                and token not in comparison.skill_stopwords
            ):
                found.add(token)
    if numbers:
        # HR-278: every number is a named term — a changed count, amount or duration
        # is a changed claim however many of the line's words are grounded.
        found.update(token for token in _TOKEN.findall(text.lower()) if token.isdigit())
    return frozenset(found)


def sentences(text: str) -> list[str]:
    """``text`` cut at sentence ends and line breaks; blank pieces dropped."""
    return [part.strip() for part in _SENTENCE.split(text) if part.strip()]


@dataclass(frozen=True)
class _Matcher:
    """The compiled rulebook inputs for one rewrite (built per call; it is small)."""

    comparison: Comparison
    #: One regex per instruction: its words in order, any non-word run between them.
    instructions: tuple[re.Pattern[str], ...]
    #: Each instruction's full word sequence, space-padded, for fragment matching.
    instruction_words: tuple[str, ...]
    fragment_min_tokens: int
    #: The content-token set of each boilerplate passage.
    passages: tuple[frozenset[str], ...]
    boilerplate_threshold: float


def _matcher(rules: Rules) -> _Matcher:
    rewrite, boiler = rules.rewrite, rules.boilerplate
    comparison = grounding_comparison(rules)
    patterns: list[re.Pattern[str]] = []
    words: list[str] = []
    for instruction in rewrite.form_instructions:
        seq = _TOKEN.findall(instruction.lower())
        body = r"[^a-z0-9]+".join(re.escape(token) for token in seq)
        # whole words only; swallow the punctuation that closes the instruction
        patterns.append(
            re.compile(rf"(?<![a-z0-9]){body}(?![a-z0-9])[^\w\s]*", re.IGNORECASE)
        )
        words.append(f" {' '.join(seq)} ")
    passages = (
        *boiler.about_sfu,
        *boiler.territorial_acknowledgement,
        *boiler.employment_equity,
        *rewrite.grounding_extra_boilerplate,
    )
    return _Matcher(
        comparison=comparison,
        instructions=tuple(patterns),
        instruction_words=tuple(words),
        fragment_min_tokens=rewrite.form_instruction_fragment_min_tokens,
        passages=tuple(
            tokens
            for tokens in (content_tokens(p, comparison) for p in passages)
            if tokens
        ),
        boilerplate_threshold=rewrite.grounding_boilerplate_threshold,
    )


def _is_boilerplate(sentence: str, matcher: _Matcher) -> bool:
    """Whether ``sentence`` IS one boilerplate passage, give or take: at least the
    threshold of the sentence's tokens are the passage's AND at least the threshold of
    the passage's tokens are the sentence's. Both directions, because one is not enough:
    the pilot's "Community Engagement." (a duty heading) is two tokens, both in the
    About SFU paragraph — it is IN the passage, but it is not the passage."""
    tokens = content_tokens(sentence, matcher.comparison)
    if not tokens:
        return False
    threshold = matcher.boilerplate_threshold
    return any(
        len(tokens & passage) / len(tokens) >= threshold
        and len(tokens & passage) / len(passage) >= threshold
        for passage in matcher.passages
    )


def carries_placeholder(text: str, rules: Rules) -> bool:
    """Whether ``text`` holds one of the template's placeholder markers
    (``markers.placeholder``), folded exactly as the validator folds it.

    A restore must never put one back: ``SFU-STRUCT-PLACEHOLDER`` feeds the
    NON-OVERRIDABLE no-placeholders gate (HR-047), so restoring "Position Number(s):
    ______01598______ Continued Assesses…" (a WJQ page header the parser fused into a
    duty — pilot, 0a75edf1) would make the draft un-approvable to "keep" one sentence.
    Such a sentence is listed for the reviewer instead."""
    folded = fold_text(
        text,
        join_paragraphs=rules.textnorm.collapse_across_paragraph_break,
        casefold=True,
    ).folded
    return any(marker in folded for marker in rules.markers.placeholder)


def _clean(text: str, matcher: _Matcher, stripped: list[str]) -> str:
    """``text`` minus every form instruction and boilerplate sentence in it. Returned
    BYTE-IDENTICAL when nothing matched — a restore must put back the source's own
    words, not a re-spaced copy of them."""
    out = text
    for pattern in matcher.instructions:
        for match in pattern.finditer(out):
            stripped.append(match.group(0).strip())
        out = pattern.sub(" ", out)
    pieces = sentences(out)
    kept = [p for p in pieces if not _is_boilerplate(p, matcher)]
    stripped.extend(p for p in pieces if p not in kept)
    if out == text and len(kept) == len(pieces):
        return text
    # A partially-matched text is rebuilt from its surviving sentences.
    rebuilt = _SPACES.sub(" ", " ".join(kept)).strip(" \t,;:-–")
    return rebuilt if _TOKEN.search(rebuilt.lower()) else ""


def _is_fragment(text: str, matcher: _Matcher) -> int:
    """How many words ``text`` has if its whole word sequence is a contiguous piece of
    one instruction's, else 0."""
    seq = _TOKEN.findall(text.lower())
    if not seq:
        return 0
    probe = f" {' '.join(seq)} "
    return len(seq) if any(probe in words for words in matcher.instruction_words) else 0


def _clean_list(
    items: Sequence[str], matcher: _Matcher, stripped: list[str]
) -> list[str]:
    """A list section minus instructions, boilerplate and wrapped-instruction RUNS.

    A run is consecutive items each a piece of an instruction's word sequence, and it
    is dropped only if ONE of its items alone holds ``fragment_min_tokens`` words of
    it. So the WJQ's own table cells — "1 hour", "Occasional", "1 hour", "Occasional"
    — are never taken for the instruction they happen to echo, while a short tail
    ("continuous).") goes with the long wrapped line it belongs to."""
    cleaned = [_clean(item, matcher, stripped) for item in items]
    words = [_is_fragment(item, matcher) for item in cleaned]
    drop: set[int] = set()
    start = 0
    while start < len(cleaned):
        end = start
        while end < len(cleaned) and words[end]:
            end += 1
        if end > start and max(words[start:end]) >= matcher.fragment_min_tokens:
            drop.update(range(start, end))
        start = max(end, start + 1)
    stripped.extend(cleaned[i] for i in sorted(drop))
    return [item for i, item in enumerate(cleaned) if item and i not in drop]


def _clean_duty(
    duty: SFUDuty, matcher: _Matcher, stripped: list[str]
) -> SFUDuty | None:
    statement = _clean(duty.statement, matcher, stripped)
    clauses = _clean_list(duty.how_why, matcher, stripped)
    if not statement:
        if not clauses:
            return None
        statement, clauses = clauses[0], clauses[1:]
    if statement == duty.statement and clauses == duty.how_why:
        return duty
    return duty.model_copy(update={"statement": statement, "how_why": clauses})


def source_view(
    draft: SFUJobDescription, rules: Rules
) -> tuple[SFUJobDescription, tuple[str, ...]]:
    """The merge draft as the rewrite sees it, and every piece of text removed (each
    distinct piece once, in document order). See the module docstring."""
    matcher = _matcher(rules)
    stripped: list[str] = []
    summary = (
        _clean(draft.position_summary, matcher, stripped)
        if draft.position_summary
        else draft.position_summary
    )
    duties = [
        kept
        for duty in draft.duties
        if (kept := _clean_duty(duty, matcher, stripped)) is not None
    ]
    decision_making = _clean_list(draft.decision_making, matcher, stripped)
    problem_solving = _clean_list(draft.problem_solving, matcher, stripped)
    relationships = draft.relationships
    if relationships is not None:
        supervisory = (
            _clean(relationships.supervisory, matcher, stripped)
            if relationships.supervisory
            else relationships.supervisory
        )
        relationships = relationships.model_copy(
            update={
                "supervisory": supervisory or None,
                "internal": _clean_list(relationships.internal, matcher, stripped),
                "external": _clean_list(relationships.external, matcher, stripped),
            }
        )
    qualifications: list[SFUQualification] = []
    for qual in draft.qualifications:
        text = _clean(qual.text, matcher, stripped)
        if text:
            qualifications.append(
                qual if text == qual.text else qual.model_copy(update={"text": text})
            )
    context = (
        _clean(draft.additional_context, matcher, stripped) or None
        if draft.additional_context
        else draft.additional_context
    )
    view = draft.model_copy(
        update={
            "position_summary": summary,
            "duties": duties,
            "decision_making": decision_making,
            "problem_solving": problem_solving,
            "relationships": relationships,
            "qualifications": qualifications,
            "additional_context": context,
        }
    )
    return view, _distinct(piece for piece in stripped if piece)


def _distinct(pieces: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(pieces))

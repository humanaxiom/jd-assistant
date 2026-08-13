"""Word-level inline diff of two text snapshots — pure, deterministic (Phase 8.3a).

:func:`build_inline_diff` refines the section-level before/after of
:mod:`src.jd_core.bank.version_diff` into **spans**: runs of text marked ``equal``,
``delete`` (present in the previous version only) or ``insert`` (present in this draft
only). The review page renders each side as its own spans, so a reviewer reads *which
words* changed rather than two walls of text they must compare by eye.

**Spans are DATA, never markup.** Nothing here emits HTML. The template renders each
span's ``text`` through Jinja's autoescape like any other untrusted string — JD content
is authored by people and must never be trusted into a page as markup.

**Lossless by construction.** The tokenizer splits into runs of non-whitespace and runs
of whitespace, so every byte of the input lands in exactly one token and the spans of
each side reassemble that side's original text exactly. Pinned by a round-trip test over
newlines, tabs and unicode, because this text is what a human reads before deciding to
publish: a diff that drops a word shows them a JD that does not exist.

**⚠ ``autojunk=False`` is load-bearing, not a tidy-up.** ``difflib``'s default treats
any element appearing in more than 1% of a sequence of ≥200 elements as junk and
refuses to match on it. A JD duties list — many lines opening ``- Reviews …`` — is
precisely that shape. Measured on a 150-line repetitive block with ONE duty added, the
default reports **897 tokens deleted and 913 inserted**; the truth is **0 and 16**. The
page would tell the reviewer every duty changed. Pinned by two tests that fail if the
default returns.

**Pure** (NN #2 / ADR-006): no I/O, no DB, no LLM; imports no ``jd_bank``.
**Descriptive, never a decision** (NN #1): it carries no approval or score field — it
reports what differs and judges nothing.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Literal

from pydantic import BaseModel, ConfigDict

#: Runs of non-whitespace OR runs of whitespace. Every byte of the input is captured by
#: exactly one token, which is what makes the round trip exact.
_TOKEN = re.compile(r"\S+|\s+")

SpanKind = Literal["equal", "insert", "delete"]


class InlineSpan(BaseModel):
    """One run of text and how it differs. ``delete`` appears only on the before side,
    ``insert`` only on the after side."""

    model_config = ConfigDict(frozen=True)

    kind: SpanKind
    text: str


class InlineDiff(BaseModel):
    """One section's rendered forms. ``before`` carries ``equal``/``delete`` spans,
    ``after`` carries ``equal``/``insert``; ``unified`` interleaves all three into a
    single stream for the whole-JD unified view. ``any_changes`` is False when the two
    texts are identical.

    The three are consistent by construction, and pinned as such: dropping the inserts
    from ``unified`` reproduces ``before`` exactly, and dropping the deletes reproduces
    ``after``.
    """

    model_config = ConfigDict(frozen=True)

    before: tuple[InlineSpan, ...]
    after: tuple[InlineSpan, ...]
    unified: tuple[InlineSpan, ...]
    any_changes: bool


def _merge(kinds_and_text: list[tuple[SpanKind, str]]) -> tuple[InlineSpan, ...]:
    """Collapse consecutive same-kind runs into one span. Without this the page emits a
    separate highlight per word and a three-word edit is unreadable."""
    merged: list[tuple[SpanKind, str]] = []
    for kind, text in kinds_and_text:
        if not text:
            continue
        if merged and merged[-1][0] == kind:
            merged[-1] = (kind, merged[-1][1] + text)
        else:
            merged.append((kind, text))
    return tuple(InlineSpan(kind=kind, text=text) for kind, text in merged)


def build_inline_diff(before: str, after: str) -> InlineDiff:
    """Word-level spans for ``before`` (the last approved text) vs ``after`` (this
    draft). Pure and deterministic: the same pair always yields the same spans."""
    before_tokens = _TOKEN.findall(before)
    after_tokens = _TOKEN.findall(after)

    matcher = SequenceMatcher(a=before_tokens, b=after_tokens, autojunk=False)

    before_runs: list[tuple[SpanKind, str]] = []
    after_runs: list[tuple[SpanKind, str]] = []
    unified_runs: list[tuple[SpanKind, str]] = []
    for op, a_start, a_end, b_start, b_end in matcher.get_opcodes():
        old = "".join(before_tokens[a_start:a_end])
        new = "".join(after_tokens[b_start:b_end])
        if op == "equal":
            before_runs.append(("equal", old))
            after_runs.append(("equal", new))
            unified_runs.append(("equal", old))
        else:
            # 'replace' is a delete on the before side and an insert on the after side;
            # 'delete'/'insert' contribute to one side only (the other run is empty and
            # is dropped by _merge). Unified keeps both, removal first, so the stream
            # reads in document order.
            before_runs.append(("delete", old))
            after_runs.append(("insert", new))
            unified_runs.append(("delete", old))
            unified_runs.append(("insert", new))

    return InlineDiff(
        before=_merge(before_runs),
        after=_merge(after_runs),
        unified=_merge(unified_runs),
        any_changes=before != after,
    )

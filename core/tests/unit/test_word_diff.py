"""Unit — the pure word-level inline diff (Phase 8.3a).

Pins the two properties that make an inline diff safe to put in front of a reviewer:

1. **It is LOSSLESS.** The spans of each side reassemble that side's original text byte
   for byte. A review page is where a human decides whether to publish; a diff that
   silently drops a word shows them a JD that does not exist.
2. **It diffs the EDIT, not the block.** ``difflib``'s default ``autojunk=True`` treats
   any token appearing in >1% of a sequence of ≥200 elements as junk — which is exactly
   the shape of a JD duties list — and reports the whole section as rewritten. Measured
   on a repetitive duties block: 897 deleted / 913 inserted tokens under the default,
   versus 0 / 16 truthfully. A diff that cries "everything changed" is one a reviewer
   learns to ignore.
"""

from __future__ import annotations

import pytest

from src.jd_core.bank.word_diff import InlineSpan, build_inline_diff


def _join(spans: tuple[InlineSpan, ...]) -> str:
    return "".join(span.text for span in spans)


def _kinds(spans: tuple[InlineSpan, ...]) -> list[str]:
    return [span.kind for span in spans]


def _tokens(spans: tuple[InlineSpan, ...], kind: str) -> int:
    """Non-whitespace tokens carrying ``kind`` — the size of the reported change."""
    return sum(len(s.text.split()) for s in spans if s.kind == kind)


def test_identical_text_is_a_single_equal_span_on_both_sides() -> None:
    diff = build_inline_diff("Develops applications", "Develops applications")
    assert _kinds(diff.before) == ["equal"]
    assert _kinds(diff.after) == ["equal"]
    assert diff.any_changes is False


def test_a_changed_word_is_deleted_before_and_inserted_after() -> None:
    diff = build_inline_diff(
        "Develops and maintains applications",
        "Develops and supports applications",
    )
    assert _tokens(diff.before, "delete") == 1
    assert _tokens(diff.after, "insert") == 1
    assert "maintains" in "".join(s.text for s in diff.before if s.kind == "delete")
    assert "supports" in "".join(s.text for s in diff.after if s.kind == "insert")
    assert diff.any_changes is True


def test_pure_insertion_leaves_the_before_side_untouched() -> None:
    diff = build_inline_diff("Reviews documents", "Reviews incoming documents")
    assert _kinds(diff.before) == ["equal"]
    assert _tokens(diff.after, "insert") == 1


def test_pure_deletion_leaves_the_after_side_untouched() -> None:
    diff = build_inline_diff("Reviews incoming documents", "Reviews documents")
    assert _tokens(diff.before, "delete") == 1
    assert _kinds(diff.after) == ["equal"]


@pytest.mark.parametrize(
    ("before", "after"),
    [
        ("", ""),
        ("only before", ""),
        ("", "only after"),
        ("one line", "one line"),
        ("line one\nline two\n", "line one\nline TWO\n"),
        ("  leading and trailing  ", "  leading  and trailing  "),
        ("tabs\tand\tspaces", "tabs\tand spaces"),
        ("unicode — em dash · middot", "unicode — em dash · midpoint"),
        ("- Develops apps\n- Maintains apps\n", "- Develops apps\n"),
        ("Grade: J\nEmployee group: apsa", "Grade: K\nEmployee group: apsa"),
    ],
)
def test_the_spans_reassemble_each_side_byte_for_byte(before: str, after: str) -> None:
    """THE invariant. Whitespace, newlines and unicode all survive, so the rendered
    page shows exactly the stored JD text and never a lossy reconstruction of it."""
    diff = build_inline_diff(before, after)
    assert _join(diff.before) == before
    assert _join(diff.after) == after


def test_a_repetitive_section_diffs_the_edit_and_not_the_whole_block() -> None:
    """The ``autojunk`` pin — mutation-proved. Flip ``autojunk=False`` back to the
    ``difflib`` default and this fails with ~897 deleted / ~913 inserted tokens: the
    page would tell the reviewer every duty changed when one was added."""
    line = "- Reviews and processes incoming documents."
    before = "\n".join([line] * 150)
    after = "\n".join(
        [line] * 75 + ["- Trains new staff on the intake process."] + [line] * 75
    )

    diff = build_inline_diff(before, after)

    assert _tokens(diff.before, "delete") == 0
    assert _tokens(diff.after, "insert") == 8
    assert _join(diff.before) == before
    assert _join(diff.after) == after


def test_a_word_changed_inside_a_repetitive_block_is_localized() -> None:
    """Same trap, the other shape: an edit *inside* one of many identical lines. Under
    the ``difflib`` default this reports ~891 tokens changed on each side."""
    line = "- Reviews and processes incoming documents."
    before = "\n".join([line] * 150)
    after = "\n".join(
        [line] * 75 + ["- Reviews and processes outgoing documents."] + [line] * 74
    )

    diff = build_inline_diff(before, after)

    assert _tokens(diff.before, "delete") == 1
    assert _tokens(diff.after, "insert") == 1


def test_adjacent_spans_of_the_same_kind_are_merged() -> None:
    """Consecutive changed words are ONE span, not one per word — otherwise the page
    emits a separate highlight box per token and the change is unreadable."""
    diff = build_inline_diff(
        "Develops one two three applications", "Develops four five six applications"
    )
    for spans in (diff.before, diff.after):
        kinds = _kinds(spans)
        assert all(a != b for a, b in zip(kinds, kinds[1:], strict=False)), kinds


def test_the_diff_is_deterministic() -> None:
    """Pure and repeatable (NN #2): the same pair always yields the same spans, so a
    reviewer reloading the page never sees the change described differently."""
    args = ("Develops and maintains applications", "Develops and supports systems")
    assert build_inline_diff(*args) == build_inline_diff(*args)


def test_it_judges_nothing() -> None:
    """Descriptive, never a decision (NN #1) — no score, verdict or approval field."""
    diff = build_inline_diff("before text", "after text")
    forbidden = {"score", "verdict", "approved", "passed", "severity"}
    assert forbidden.isdisjoint(diff.model_dump().keys())


@pytest.mark.parametrize(
    ("before", "after"),
    [
        ("", ""),
        ("only before", ""),
        ("", "only after"),
        ("line one\nline two\n", "line one\nline TWO\n"),
        ("- Develops apps\n- Maintains apps\n", "- Develops apps\n"),
        ("Develops and maintains applications", "Develops and supports systems"),
    ],
)
def test_the_unified_stream_reproduces_both_sides(before: str, after: str) -> None:
    """The whole-JD unified view is the SAME diff, not a second one: drop its inserts
    and the previous version is back; drop its deletes and this draft is back. Without
    this the two views could disagree about what changed."""
    diff = build_inline_diff(before, after)
    assert "".join(s.text for s in diff.unified if s.kind != "insert") == before
    assert "".join(s.text for s in diff.unified if s.kind != "delete") == after


def test_the_unified_stream_reads_in_document_order() -> None:
    """A removal is shown immediately before its replacement, so the reviewer reads
    the change in place rather than hunting for its other half."""
    diff = build_inline_diff("Develops applications daily", "Develops systems daily")
    kinds = [s.kind for s in diff.unified]
    assert kinds == ["equal", "delete", "insert", "equal"]

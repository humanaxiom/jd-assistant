"""Reading a search box query as a PeopleSoft position number (HR-339).

A tester who has a position number from PeopleSoft (``00000061``, or ``61`` as the
archive's own file names write it) types it into the Library or the Builder search and
should get the files filed under that position — not a meaning search over the digits.
"""

from __future__ import annotations

import pytest

from src.jd_bank.library.positions import read_position_query
from src.jd_core.rules import get_rules


@pytest.mark.parametrize(
    ("query", "position"),
    [
        ("61", "00000061"),
        ("00000061", "00000061"),
        (" 61 ", "00000061"),
        ("#61", "00000061"),
        ("Pos 61", "00000061"),
        ("pos. 61", "00000061"),
        ("Position #61", "00000061"),
        ("POSN 128229", "00128229"),
        ("00128229", "00128229"),
    ],
)
def test_a_position_number_is_read(query: str, position: str) -> None:
    assert read_position_query(query, get_rules()) == position


@pytest.mark.parametrize(
    "query",
    [
        "analyst",
        "61 analyst",
        "Grade 7",
        "0",
        "00000000",
        "1234567",  # above the largest position (HR-327)
        "",
        "6 1",
    ],
)
def test_anything_else_is_not_a_position(query: str) -> None:
    assert read_position_query(query, get_rules()) is None


def test_the_pattern_is_rulebook_data_and_registered() -> None:
    rules = get_rules()
    assert rules.search.position_query_pattern.groups >= 1
    entry = next(
        d
        for d in rules.decision_register.decisions
        if d.config.path == "search.position_query_pattern"
    )
    assert entry.id == "HR-339"
    assert entry.status == "open"
    assert "search" in rules.segmentation.filename_positions.consumers


def test_without_search_in_consumers_nothing_is_read_as_a_position() -> None:
    rules = get_rules()
    seg = rules.segmentation
    off = rules.model_copy(
        update={
            "segmentation": seg.model_copy(
                update={
                    "filename_positions": seg.filename_positions.model_copy(
                        update={"consumers": frozenset({"crf", "source_page"})}
                    )
                }
            )
        }
    )
    assert read_position_query("61", off) is None

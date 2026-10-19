"""Pins the shape of ``fixtures/search_eval_v1.yaml`` and the judge's semantics, so the
live recall floor in ``make smoke`` cannot be quietly weakened by editing the data."""

from __future__ import annotations

from tests.search_eval import load_eval


def test_the_eval_set_is_the_22_query_spike_set_with_its_floor() -> None:
    floor, queries = load_eval()
    assert len(queries) == 22
    assert len({q.id for q in queries}) == 22
    assert (
        floor == 18
    ), "lowering the recall floor needs a reviewed decision, not an edit"
    assert {q.kind for q in queries} == {
        "exact",
        "paraphrase",
        "duty",
        "constraint",
        "abbrev",
        "typo",
    }
    assert all(q.query.strip() for q in queries)


def test_the_judge_applies_title_department_and_group() -> None:
    _, queries = load_eval()
    by_id = {q.id: q for q in queries}

    assert by_id["E2"].relevant("Co-op Education Coordinator", None, "apsa")
    assert not by_id["E2"].relevant("Library Clerk", None, "apsa")
    # C2: a CUPE constraint — the right title in the wrong group is NOT relevant.
    assert by_id["C2"].relevant("Administrative Assistant", None, "cupe")
    assert not by_id["C2"].relevant("Administrative Assistant", None, "apsa")
    # C3: APSA or group-not-recorded both count; CUPE does not.
    assert by_id["C3"].relevant("Communications Officer", None, "")
    assert not by_id["C3"].relevant("Communications Officer", None, "cupe")
    # C1: needs a Science department and excludes look-alikes.
    assert by_id["C1"].relevant("Department Manager", "Biological Sciences", "apsa")
    assert not by_id["C1"].relevant("Department Manager", "Applied Sciences", "apsa")
    assert not by_id["C1"].relevant("Department Manager", None, "apsa")

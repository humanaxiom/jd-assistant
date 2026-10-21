"""Rewrite provenance (2026-10-21) — the follow-ups to the 2026-10-20 fidelity guard.

* **Placement (HR-279/280).** Fold-back filed a lost source duty under whichever
  rewritten duty matched it best, reading each duty's text AS IT GREW: the first duty to
  take a fold attracted the next (1d68c603: one duty took 30 of 37), and a duty that
  matched nothing still landed somewhere.
* **What came back, and from where (NN #6).** Folded and restored text is recorded with
  its source duty, and the review page reads the stored record — no LLM re-run.
* **Why a strip happened (HR-281).** "form text" was the reason given for a duty that
  merely matches SFU's acknowledgement wording.

Each test asserts the guard's / the page's post-state (non-negotiable #3).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.jd_bank.rewrite.fidelity import (
    source_view,
)
from src.jd_bank.rewrite.harmonize import _apply_anti_fabrication
from src.jd_core.bank.change_log import build_harmonization_diff
from src.jd_core.bank.restoration import (
    REMOVED_REASON_LABELS,
    labels_for_unknown_reasons,
    mark_restored,
    removed_reason_label,
    restored_view,
    unlabelled_reasons,
)
from src.jd_core.models.bank import (
    AntiFabricationRecord,
    MergedRole,
    MergeProvenance,
)
from src.jd_core.models.parsed_jd import SFUDuty, SFUJobDescription, SFUQualification
from src.jd_core.rules import Rules, get_rules

_FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "rewrite_fidelity"


@pytest.fixture(scope="module")
def rules() -> Rules:
    return get_rules()


def _with(rules: Rules, **rewrite: object) -> Rules:
    return rules.model_copy(
        update={"rewrite": rules.rewrite.model_copy(update=rewrite)}
    )


def _case(name: str) -> tuple[MergedRole, SFUJobDescription]:
    raw = json.loads((_FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
    return (
        MergedRole.model_validate(raw["merged"]),
        SFUJobDescription.model_validate(raw["model"]),
    )


def _jd(*duties: SFUDuty, **fields: object) -> SFUJobDescription:
    return SFUJobDescription(
        title="Orientation Coordinator",
        position_summary="Supports new students.",
        duties=list(duties),
        qualifications=[SFUQualification(text="Degree in a related field")],
        **fields,  # type: ignore[arg-type]
    )


def _merged(draft: SFUJobDescription) -> MergedRole:
    return MergedRole(
        draft=draft, provenance=MergeProvenance(member_count=2, skill_frequency=())
    )


_ORIENTATION = SFUDuty(
    action_verb="Coordinates",
    statement="Coordinates the student orientation program",
    how_why=["booking rooms for orientation sessions"],
)
#: Shares no content word with the orientation duty: the review's own example.
_WEBSITE = SFUDuty(
    action_verb="Maintains",
    statement="Maintains the departmental website content",
    how_why=["updating news items weekly"],
)


def _filler(n: int) -> list[SFUDuty]:
    """``n`` rewritten duties that match neither source duty above."""
    topics = ("payroll audits", "lab safety", "grant budgets", "alumni events")
    return [
        SFUDuty(action_verb="Manages", statement=f"Manages the faculty {topic}")
        for topic in topics[:n]
    ]


# --- HR-279: placement reads what the MODEL wrote, with a floor ----------------------


def test_placement_never_snowballs_onto_the_first_duty_that_took_a_fold(
    rules: Rules,
) -> None:
    """A folded sentence goes under the rewritten duty that holds the most of its
    source duty's words IN WHAT THE MODEL WROTE. Placement used to read each duty as it
    grew, so the first duty to take a fold won the next source duty too: on the
    pilot's 1d68c603 one duty took 30 of 37 folds, and 89 of the 314 pilot folds sat
    under a duty that was not the best match.

    Here the first source duty's lost clause (catering, reception, rooms, staff) is
    folded under the orientation duty. The second source duty is about the welcome
    events — 4 of its words are in the events duty as written — but after that fold
    the orientation duty held 5 of them, and took its lost clause too."""
    first = SFUDuty(
        action_verb="Coordinates",
        statement="Coordinates student orientation sessions",
        how_why=["booking welcome reception rooms catering staff volunteers"],
    )
    second = SFUDuty(
        action_verb="Plans",
        statement="Plans welcome events with reception catering staff rooms",
        how_why=["arranging guest speakers and musicians"],
    )
    events = SFUDuty(action_verb="Plans", statement="Plans the welcome events catering")
    merged = _merged(_jd(first, second))

    out, record = _apply_anti_fabrication(_jd(_ORIENTATION, events), merged, rules)

    assert out.duties[0].how_why[-1] == first.how_why[0]
    assert out.duties[1].how_why == second.how_why
    assert (second.how_why[0], second.statement) in record.folded_duty_origins


def test_every_fold_names_its_source_duty(rules: Rules) -> None:
    merged, model = _case("museum_1d68c603")

    _out, record = _apply_anti_fabrication(model, merged, rules)

    statements = {d.statement for d in source_view(merged.draft, rules)[0].duties}
    assert record.folded_duty_content
    assert [s for s, _ in record.folded_duty_origins] == list(
        record.folded_duty_content
    )
    assert {origin for _, origin in record.folded_duty_origins} <= statements


def test_an_unrelated_lost_duty_comes_back_as_its_own_duty_when_there_is_room(
    rules: Rules,
) -> None:
    """The review's case: "Maintains the departmental website content" folded under
    "Coordinates the student orientation program". It shares no word with it, so it is
    put back under its own heading — the form allows five duties (HR policy)."""
    merged = _merged(_jd(_ORIENTATION, _WEBSITE))

    out, record = _apply_anti_fabrication(_jd(_ORIENTATION), merged, rules)

    assert [d.statement for d in out.duties] == [
        _ORIENTATION.statement,
        _WEBSITE.statement,
    ]
    assert out.duties[1].how_why == _WEBSITE.how_why
    assert out.duties[0].how_why == _ORIENTATION.how_why  # nothing misfiled
    assert {
        ("updating news items weekly", _WEBSITE.statement),
        (_WEBSITE.statement, _WEBSITE.statement),  # its heading is source text too
    } <= set(record.folded_duty_origins)


def test_with_no_floor_it_is_folded_under_the_best_match_as_before(
    rules: Rules,
) -> None:
    """The knob is the cause: at 0.0 the unrelated duty is filed under the only one."""
    merged = _merged(_jd(_ORIENTATION, _WEBSITE))

    out, _record = _apply_anti_fabrication(
        _jd(_ORIENTATION), merged, _with(rules, fold_back_relevance_min=0.0)
    )

    assert len(out.duties) == 1
    assert "updating news items weekly" in out.duties[0].how_why


def test_an_unrelated_lost_duty_is_listed_when_the_form_is_full(rules: Rules) -> None:
    """No room under the five-duty cap (HR policy, untouched): listed for the reviewer,
    never filed under an unrelated duty and never silent."""
    model = _jd(_ORIENTATION, *_filler(4))
    merged = _merged(_jd(_ORIENTATION, _WEBSITE, *_filler(4)))

    out, record = _apply_anti_fabrication(model, merged, rules)

    assert len(out.duties) == rules.thresholds.duties_max
    clauses = [c for d in out.duties for c in d.how_why]
    assert "updating news items weekly" not in clauses
    assert "updating news items weekly" in record.dropped_duty_content
    assert _WEBSITE.statement in record.dropped_duty_content


# --- HR-280: an optional limit per duty ----------------------------------------------

_RELATED = SFUDuty(
    action_verb="Coordinates",
    statement="Coordinates the student orientation program and welcome events",
    how_why=["recruiting volunteer orientation leaders", "ordering welcome event food"],
)


def test_a_per_duty_limit_passes_the_next_fold_to_the_next_best_duty(
    rules: Rules,
) -> None:
    second = SFUDuty(action_verb="Plans", statement="Plans the welcome events")
    merged = _merged(_jd(_RELATED))
    model = _jd(_ORIENTATION, second)

    unlimited, _ = _apply_anti_fabrication(model, merged, rules)
    limited, _ = _apply_anti_fabrication(
        model, merged, _with(rules, fold_back_max_per_duty=1)
    )

    assert unlimited.duties[0].how_why[-2:] == _RELATED.how_why
    assert limited.duties[0].how_why[-1] == "recruiting volunteer orientation leaders"
    assert limited.duties[1].how_why == ["ordering welcome event food"]


# --- HR-281: why a piece was set aside ----------------------------------------------

#: An Indigenous programs coordinator's duty that reproduces the acknowledgement.
_EVENTS = (
    "Organizes events that acknowledge the traditional territories of the Coast "
    "Salish peoples, on whose lands the SFU campuses reside."
)
_EE = "Simon Fraser University is committed to the principle of Employment Equity."
_INSTRUCTION = (
    "Give some examples of the types of decisions the incumbent would refer to "
    "his/her supervisor."
)


def _stripping_draft() -> SFUJobDescription:
    return _jd(
        SFUDuty(
            action_verb="Coordinates",
            statement="Coordinates Indigenous student programs",
            how_why=[_EVENTS],
        ),
        decision_making=[_INSTRUCTION, "Decides the program schedule."],
    ).model_copy(
        update={
            "qualifications": [
                SFUQualification(text="Degree in a related field"),
                SFUQualification(text=_EE),
            ]
        }
    )


def test_the_record_says_where_each_strip_came_from_and_why(rules: Rules) -> None:
    _view, texts, parts = source_view(_stripping_draft(), rules)

    assert set(texts) == {p.text for p in parts}
    got = {(p.section, p.kind, p.text) for p in parts}
    assert ("duties", "boilerplate", _EVENTS) in got
    assert ("qualifications", "boilerplate", _EE) in got
    assert any(s == "decision_making" and k == "form_instruction" for s, k, _t in got)


def test_boilerplate_in_a_duty_asks_the_reviewer_to_check_it(rules: Rules) -> None:
    merged = _merged(_stripping_draft())
    _out, record = _apply_anti_fabrication(_stripping_draft(), merged, rules)

    diff = build_harmonization_diff(merged, [merged.draft], rules=rules, rewrite=record)

    got = {(r.reason, r.section, r.content) for r in diff.removed}
    assert ("boilerplate_matched_in_role_content", "duties", _EVENTS) in got
    assert ("boilerplate_stripped", "qualifications", _EE) in got
    assert any(
        reason == "form_instruction_stripped" and section == "decision_making"
        for reason, section, _c in got
    )
    assert not any(reason == "form_text_stripped" for reason, _s, _c in got)


def test_which_sections_ask_for_a_check_is_a_rulebook_choice(rules: Rules) -> None:
    merged = _merged(_stripping_draft())
    _out, record = _apply_anti_fabrication(_stripping_draft(), merged, rules)
    wider = _with(rules, boilerplate_review_sections=("duties", "qualifications"))

    diff = build_harmonization_diff(merged, [merged.draft], rules=wider, rewrite=record)

    assert ("boilerplate_matched_in_role_content", "qualifications", _EE) in {
        (r.reason, r.section, r.content) for r in diff.removed
    }


def test_a_record_written_before_the_split_keeps_the_combined_reason(
    rules: Rules,
) -> None:
    """The ~59 h v9 pass writes records without `stripped_source_parts`. They do not
    say which kind a strip was, so nothing guesses: the old reason, in HR's words."""
    merged = _merged(_stripping_draft())
    record = AntiFabricationRecord(stripped_source_text=(_EVENTS,))

    diff = build_harmonization_diff(merged, [merged.draft], rules=rules, rewrite=record)

    assert ("form_text_stripped", None, _EVENTS) in {
        (r.reason, r.section, r.content) for r in diff.removed
    }


# --- labels -----------------------------------------------------------------------


def test_every_change_log_reason_has_a_plain_sentence() -> None:
    assert unlabelled_reasons() == frozenset()
    assert labels_for_unknown_reasons() == frozenset()
    for label in REMOVED_REASON_LABELS.values():
        assert "_" not in label and label.endswith(".")


def test_an_unknown_reason_reads_as_a_sentence_not_a_code() -> None:
    assert removed_reason_label("some_future_reason") == "Not in the draft."


# --- the review page's reading of a STORED record -----------------------------------


def _labels(section: str) -> str:
    return get_rules().rule_catalog.section_labels[section]  # type: ignore[index]


def test_restored_view_reads_an_old_record_without_origins() -> None:
    """A draft from the v9 pass (records without `folded_duty_origins`) still shows
    what was put back and under which duty — read from the stored content."""
    content = _jd(
        _ORIENTATION.model_copy(
            update={"how_why": ["booking rooms", "a folded point"]}
        ),
        decision_making=["Decides the program schedule."],
    ).model_dump(mode="json")
    change_log = {
        "anti_fabrication": {
            "folded_duty_content": ["a folded point", "a point an edit removed"],
            "restored_items": [["decision_making", "Decides the program schedule."]],
        }
    }

    view = restored_view(change_log, content, section_label=_labels)

    assert view is not None
    duties, decisions = view.groups
    assert duties.duty == "Coordinates the student orientation program"
    assert [i.text for i in duties.items] == ["a folded point"]  # still in the draft
    assert duties.items[0].source_duty is None
    assert decisions.label == "Impact of Decision Making"


def test_restored_view_is_absent_without_a_readable_record() -> None:
    assert restored_view({}, {}, section_label=_labels) is None
    bad = {"anti_fabrication": {"folded_duty_content": "not a list of text"}}
    assert restored_view(bad, {}, section_label=_labels) is None


def test_marks_fall_only_on_whole_items_of_their_own_section() -> None:
    rendered = (
        "Lab Tech\n\nDUTIES AND RESPONSIBILITIES\n"
        "- Runs the lab (1 hour; 1 hour checks)\n\n"
        "RELATIONSHIPS\nInternal: 1 hour\nInternal: Faculty 1 hours\n"
        "Internal: Lab 21 hour"
    )

    segments = mark_restored(rendered, [("relationships", "1 hour")])

    marked = [s for s in segments if s.restored]
    assert [s.text for s in marked] == ["1 hour"]
    assert "".join(s.text for s in segments) == rendered
    index = segments.index(marked[0])
    before = "".join(s.text for s in segments[:index])
    # the whole contact — not the duty's, not inside "1 hours" or "21 hour"
    assert before.endswith("RELATIONSHIPS\nInternal: ")
    assert segments[index + 1].text.startswith("\nInternal: Faculty 1 hours")


def test_a_restored_duty_never_repeats_text_already_folded_under_another(
    rules: Rules,
) -> None:
    """Review of 528f694: with a per-duty limit (HR-280) the source statement folded
    under the one related duty, the limit then sent the rest to a duty of its own — and
    that duty's heading was the same statement, so it stood in the draft TWICE."""
    model = _jd(
        SFUDuty(
            action_verb="Coordinates",
            statement="Coordinates the orientation program for new students",
        )
    )
    source = SFUDuty(
        action_verb="Plans",
        statement="Plans welcome receptions and campus tours for orientation students",
        how_why=["ordering catering for each reception", "booking the campus ballroom"],
    )

    out, record = _apply_anti_fabrication(
        model, _merged(_jd(source)), _with(rules, fold_back_max_per_duty=1)
    )

    placed = [
        piece
        for duty in out.duties
        for piece in (duty.statement, *duty.how_why)
        if piece in (source.statement, *source.how_why)
    ]
    assert sorted(placed) == sorted({source.statement, *source.how_why})
    assert len(record.folded_duty_content) == len(set(record.folded_duty_content))
    # The own duty is headed by a source CLAUSE, so the source verb is not put on it.
    assert out.duties[-1].action_verb == ""

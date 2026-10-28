"""The v9 Bank's full rewrite pass (2026-10-21…25): the post-pass defects, each pinned
by its own real case.

Fixtures ``tests/fixtures/rewrite_fidelity/v9pass_*.json``: ``merged`` is the cluster's
merge draft rebuilt in-process from its v9 parses (the same rebuild reproduced every one
of the pass's 50 fallback drafts byte for byte); ``model`` is the model's reply as far
as the stored record can say — the stored draft minus everything the guard itself put
back (the pass did not record replies). Every string is verbatim.

Non-negotiable #3: these assert what the GUARD (or the merge) kept, merged, restored
and recorded — never the quality of model text.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.jd_bank.composer.wjq_assemble import assemble_wjq_jd, wjq_answers_from_jd
from src.jd_bank.db.models import DocumentFormat
from src.jd_bank.ingest.extract import extract_text
from src.jd_bank.rewrite.fidelity import cut_off_tail, source_view
from src.jd_bank.rewrite.harmonize import (
    _REWRITABLE_FIELDS,
    _apply_anti_fabrication,
    form_duty_limit,
)
from src.jd_core.bank.change_log import build_harmonization_diff
from src.jd_core.bank.merge import label_referred_decisions, merge_cluster
from src.jd_core.models.bank import MergedRole
from src.jd_core.models.parsed_jd import SFUDuty, SFUJobDescription
from src.jd_core.parser.segmenter import parse_jd
from src.jd_core.rules import Rules, get_rules
from src.jd_export import render_sfu_docx

_FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "rewrite_fidelity"


def _case(name: str) -> tuple[MergedRole, SFUJobDescription]:
    raw = json.loads((_FIXTURES / f"v9pass_{name}.json").read_text(encoding="utf-8"))
    return (
        MergedRole.model_validate(raw["merged"]),
        SFUJobDescription.model_validate(raw["model"]),
    )


def _final(merged: MergedRole, guarded: SFUJobDescription) -> SFUJobDescription:
    """The draft the producer keeps: the merge with the rewritable fields replaced."""
    return merged.draft.model_copy(
        update={f: getattr(guarded, f) for f in _REWRITABLE_FIELDS}
    )


def _with(rules: Rules, **rewrite: object) -> Rules:
    return rules.model_copy(
        update={"rewrite": rules.rewrite.model_copy(update=rewrite)}
    )


@pytest.fixture(scope="module")
def rules() -> Rules:
    return get_rules()


# --- 1. the CUPE form's function limit (HR-290) ---------------------------------------


def test_a_rewrite_over_the_cupe_function_limit_is_merged_within_it(
    rules: Rules,
) -> None:
    """0cd5db26 (telephone billing clerk): the model returned 13 major functions for a
    12-duty merge; the Builder then refused to clone the role ("the form takes at most
    12", HR-246) and smoke's every-CUPE-role clone test failed. The guard now merges the
    two closest duties — nothing is dropped — and the role clones and reassembles."""
    merged, model = _case("0cd5db26")
    assert len(model.duties) == 13  # the real reply

    guarded, record = _apply_anti_fabrication(model, merged, rules)
    final = _final(merged, guarded)

    limit = form_duty_limit(merged.draft, rules)
    assert limit == rules.cupe_form.function_limits["major_functions"] == 12
    assert len(final.duties) == limit
    again = assemble_wjq_jd(wjq_answers_from_jd(final))
    assert len(again.duties) == len(final.duties)
    # merged, never dropped: the absorbed duty's headline is a clause of the one it
    # went under, and the record names both
    assert len(record.merged_duties) == 1
    absorbed, into = record.merged_duties[0]
    target = next(d for d in final.duties if d.statement == into)
    assert any(absorbed in clause for clause in target.how_why)
    assert absorbed not in {d.statement for d in final.duties}
    assert not record.over_form_limit


def test_with_the_old_rule_the_draft_stays_over_the_limit(rules: Rules) -> None:
    """The guard broken back to what the pass ran: 13 functions; the clone refuses."""
    merged, model = _case("0cd5db26")
    guarded, record = _apply_anti_fabrication(
        model, merged, _with(rules, duties_over_form_limit="keep")
    )
    assert len(guarded.duties) == 13 and not record.merged_duties
    with pytest.raises(ValueError, match="HR-246"):
        assemble_wjq_jd(wjq_answers_from_jd(_final(merged, guarded)))


def test_a_model_duty_with_more_clauses_than_the_parser_reads_is_cut_and_listed(
    rules: Rules,
) -> None:
    """The clause cap is a form limit too: the JDFN clone refuses a duty with more
    how/why points than `segmentation.duty_how_why_max_count` (the parser's own
    limit)."""
    cap = rules.segmentation.duty_how_why_max_count
    half = cap // 2 + 5  # two source duties, each within the cap
    clauses = [f"Maintains ledger{i} archive{i}." for i in range(2 * half)]
    sources = [
        SFUDuty(
            action_verb="Keeps", statement="Keeps the records", how_why=clauses[:half]
        ),
        SFUDuty(
            action_verb="Files", statement="Files the returns", how_why=clauses[half:]
        ),
    ]
    member = SFUJobDescription(title="Records Clerk", duties=sources)
    merged = merge_cluster([member, member], rules=rules)
    # the model merged both into ONE duty carrying every clause — over the cap
    model = SFUJobDescription(
        title="Records Clerk",
        duties=[
            SFUDuty(action_verb="Keeps", statement="Keeps the records", how_why=clauses)
        ],
    )
    guarded, record = _apply_anti_fabrication(model, merged, rules)
    assert all(len(d.how_why) <= cap for d in guarded.duties)
    assert list(record.over_form_limit) == clauses[cap:]
    # …and fold-back still accounts for every source clause: kept, folded or listed
    kept = {c for d in guarded.duties for c in (d.statement, *d.how_why)}
    for clause in clauses:
        assert clause in kept or clause in record.dropped_duty_content


# --- 2. a source page header is not role text (HR-291) --------------------------------


def test_a_page_header_never_comes_back_into_the_draft(rules: Rules) -> None:
    """23a58c9c: fold-back restored "Position Number 31160 (Continued) C. DUTIES AND
    RESPONSIBILITIES (continued) Participates as a member of the following university
    committees" as a clause; the export printed it at the start of a line, and the
    parser re-read it as the role's position number and split a duty in two."""
    merged, model = _case("23a58c9c")
    guarded, record = _apply_anti_fabrication(model, merged, rules)
    final = _final(merged, guarded)

    text = " ".join(c for d in final.duties for c in (d.statement, *d.how_why))
    assert "Position Number 31160" not in text
    assert any(
        p.kind == "page_header" and "31160" in p.text
        for p in record.stripped_source_parts
    )
    body = extract_text(render_sfu_docx(final), DocumentFormat.DOCX)
    again = parse_jd(body).jd
    assert final.position_number is None and again.position_number is None
    assert len(again.duties) == len(final.duties)


def test_without_the_header_rule_the_header_is_folded_back(rules: Rules) -> None:
    """The guard broken: the header returns as a clause, as on the pass."""
    merged, model = _case("23a58c9c")
    guarded, _ = _apply_anti_fabrication(
        model, merged, _with(rules, page_header_pattern=None)
    )
    assert any("Position Number 31160" in c for d in guarded.duties for c in d.how_why)


@pytest.mark.parametrize(
    ("text", "header"),
    [
        (
            "Prepares reports. Position Number 31160 (Continued) C. DUTIES AND "
            "RESPONSIBILITIES (continued) Participates in committees.",
            "Position Number 31160 (Continued) C. DUTIES AND RESPONSIBILITIES "
            "(continued)",
        ),
        (
            "Supervises staff. Administrative/Professional Position # ______ Page 2 "
            "Recruits employers.",
            "Administrative/Professional Position # ______ Page 2",
        ),
        ("Maintains the handbook. Position #: 00117368 2", "Position #: 00117368 2"),
        (
            "Decides upon appropriate technology. Position Number: 103154 Serves as "
            "the contact with outside technology services.",
            "Position Number: 103154",
        ),
    ],
)
def test_the_page_header_shapes_measured_on_the_pass_are_set_aside(
    rules: Rules, text: str, header: str
) -> None:
    jd = SFUJobDescription(title="T", decision_making=[text])
    view, _, parts = source_view(jd, rules)
    assert header not in " ".join(view.decision_making)
    assert [p.text for p in parts if p.kind == "page_header"] == [header]


def test_a_reference_to_another_position_is_role_text_and_stays(rules: Rules) -> None:
    """28 of the 198 "position #/number" occurrences in the merge drafts name ANOTHER
    position — those are the role's content."""
    item = (
        "Backs up the GET Front Counter Clerk (position #64841) for breaks, vacation "
        "and other absences."
    )
    jd = SFUJobDescription(title="T", decision_making=[item])
    view, _, parts = source_view(jd, rules)
    assert view.decision_making == [item] and not parts


# --- 3. referred decisions in the questionnaire's other wordings (HR-282) -------------

#: 20000505_00000840Operations_supervisor.doc (82e5c2d0), as parsed — verbatim.
_OPS_MADE = (
    "Makes annual budget recommendations for facility services; makes decisions to "
    "approve expenses within budget; evaluates the performance of contract staff and "
    "makes recommendations for progressive discipline to the contract supervisor; "
    "makes "
    "decisions regarding required revisions to service levels; makes recommendations "
    "for changes to the janitorial contract; hires continuing and temporary staff, t"
)
_OPS_REFERRED = (
    "Decisions the incumbent would refer to his/her supervisor: Matters falling "
    "outside "
    "established policies and procedures; serious contract infractions or significant "
    "revisions to contract service levels and staffing; staff terminations; etc."
)


def test_the_operations_supervisors_referred_decisions_are_labelled(
    rules: Rules,
) -> None:
    """82e5c2d0: "Decisions the incumbent would refer to his/her supervisor: …" is the
    refer question in another edition of the form; HR-282's markers missed it, and the
    rewrite returned "Staff terminations" as a decision the incumbent makes."""
    label = rules.harmonization.referred_decision_label
    out = label_referred_decisions([_OPS_MADE, _OPS_REFERRED], rules)
    assert out == [
        _OPS_MADE,
        f"{label} Matters falling outside established policies and procedures; "
        "serious contract infractions or significant revisions to contract service "
        "levels and staffing; staff terminations; etc.",
    ]


@pytest.mark.parametrize(
    ("items", "expected"),
    [
        # 19900126_00030435Micro_lab_fac_engineer.doc
        (
            [
                "Makes key recommendations for the allocation of the equipment budget.",
                "Examples of the types of decisions the incumbent would refer to "
                "his/her supervisor.",
                "Decisions that: contradict established lab policy; pertain to legal "
                "or major financial issues with other departments or outside vendors.",
            ],
            [
                "Makes key recommendations for the allocation of the equipment budget.",
                "{label} Decisions that: contradict established lab policy; pertain to "
                "legal or major financial issues with other departments or outside "
                "vendors.",
            ],
        ),
        # 20200928_00104324_JDFN_APSA_20190827.docx (b53e605d) — fused after a made one
        (
            [
                "Makes supervisory decisions such as hiring, performance evaluation, "
                "approval of leaves, handling grievances to the appropriate step, etc. "
                "Examples of decisions the incumbent would refer to his/her supervisor",
                "Allocation of staff to project teams.",
            ],
            [
                "Makes supervisory decisions such as hiring, performance evaluation, "
                "approval of leaves, handling grievances to the appropriate step, etc.",
                "{label} Allocation of staff to project teams.",
            ],
        ),
        # 20121203_00097115_Student_Life_Educator.docx (e11cabc0): the prompt followed
        # by the newer template's own lead-in — that lead-in is not a decision
        (
            [
                "Examples of the types of decisions the incumbent would refer to "
                "his/her supervisor Refers decisions regarding",
                "Decisions regarding University policy.",
            ],
            ["{label} Decisions regarding University policy."],
        ),
        # db90f0eb: "…would refer to his/her supervisor are" — "are" is not a decision
        (
            [
                "Determines staffing needs for the information systems team. Examples "
                "of decisions the incumbent would refer to his/her supervisor are",
                "Non-standard requests for security system access rights.",
            ],
            [
                "Determines staffing needs for the information systems team.",
                "{label} Non-standard requests for security system access rights.",
            ],
        ),
    ],
    ids=["examples-of-the-types", "fused-examples-of", "prompt-then-lead-in", "are"],
)
def test_the_other_editions_of_the_refer_question_start_a_referred_run(
    rules: Rules, items: list[str], expected: list[str]
) -> None:
    label = rules.harmonization.referred_decision_label
    assert label_referred_decisions(items, rules) == [
        e.format(label=label) for e in expected
    ]


# --- 4. a decision list the parser cut is restored up to the cut, never lost ----------


def test_a_cut_decision_list_comes_back_whole_up_to_its_cut_entry(
    rules: Rules,
) -> None:
    """82e5c2d0: the made-decisions item is a ";" list the parser cut at its 400-
    character cap ("…; hires continuing and temporary staff, t"). The whole item counted
    as the cut-off sentence, so a model that lost it had all six decisions LISTED and
    none put back. Now the five whole entries come back and only the cut one is listed.
    """
    merged, model = _case("82e5c2d0")
    label = rules.harmonization.referred_decision_label
    assert _OPS_MADE in merged.draft.decision_making
    referred_only = model.model_copy(
        update={
            "decision_making": [
                f"{label} Matters falling outside established policies and procedures"
            ]
        }
    )
    guarded, record = _apply_anti_fabrication(referred_only, merged, rules)

    head = _OPS_MADE[: _OPS_MADE.rfind(";")]
    assert head in guarded.decision_making
    assert ("decision_making", head) in record.restored_items
    assert ("decision_making", "hires continuing and temporary staff, t") in (
        record.uncovered_items
    )
    assert not any(i.endswith("staff, t") for i in guarded.decision_making)


def test_cut_off_tail_splits_a_cut_list_at_its_last_entry(rules: Rules) -> None:
    whole, tail = cut_off_tail(_OPS_MADE, len(_OPS_MADE), rules)
    assert tail == "hires continuing and temporary staff, t"
    assert whole == [_OPS_MADE[: _OPS_MADE.rfind(";")]]


# --- 5. a flagged CUPE duty that rewords one source duty keeps its frequency (HR-292) -


def test_a_flagged_duty_that_rewords_one_source_duty_carries_its_frequency(
    rules: Rules,
) -> None:
    """00d207d0: 10 of the merge's 12 duties carry a frequency, the rewritten draft 2.
    "Assign and supervise temporary staff, checking their work and providing guidance
    and training" is flagged (HR-184) against "Assigns and checks the work of temporary
    staff" (daily) — and covers every sentence of it."""
    merged, model = _case("00d207d0")
    # verb "Assign", statement as the model wrote it
    statement = (
        "and supervise temporary staff, checking their work and providing "
        "guidance and training"
    )
    # The pass's record scrubbed every clause of this reply (ungrounded), in reply
    # order; these three sit between the filing duty's and the database duty's. They
    # are what made the duty FLAGGED (HR-184 reads the model's whole duty).
    model = model.model_copy(
        update={
            "duties": [
                (
                    d.model_copy(
                        update={
                            "how_why": [
                                "delegate tasks according to priorities",
                                "review completed work for quality",
                                "provide on‑the‑job instruction as needed",
                            ]
                        }
                    )
                    if d.statement == statement
                    else d
                )
                for d in model.duties
            ]
        }
    )
    guarded, record = _apply_anti_fabrication(model, merged, rules)
    duty = next(d for d in guarded.duties if d.statement == statement)
    assert statement in record.flagged_duties
    assert duty.frequency == "daily"

    off, _ = _apply_anti_fabrication(
        model, merged, _with(rules, flagged_duty_frequency_min_coverage=0.0)
    )
    assert next(d for d in off.duties if d.statement == statement).frequency is None


# --- the review page names every new reason -----------------------------------


def test_the_change_log_names_a_page_header_and_an_over_limit_clause(
    rules: Rules,
) -> None:
    merged, model = _case("23a58c9c")
    guarded, record = _apply_anti_fabrication(model, merged, rules)
    from src.jd_core.models.bank import RewrittenDraft

    rewritten = RewrittenDraft(
        draft=_final(merged, guarded),
        score=0.0,
        grade="F",
        issues=(),
        anti_fabrication=record.model_copy(update={"over_form_limit": ("X clause.",)}),
        model="m",
        prompt_version="p",
        rules_version="r",
    )
    members = [merged.draft] * merged.provenance.member_count
    diff = build_harmonization_diff(merged, members, rewrite=rewritten, rules=rules)
    reasons = {r.reason for r in diff.removed}
    assert {"page_header_stripped", "rewrite_over_form_limit"} <= reasons


# --- 6. qualifications keep the form's order and the source's kinds (HR-293/294) ------


def _issue_ids(jd: SFUJobDescription, rules: Rules) -> set[str]:
    from src.jd_bank.jd_text import flatten_jd
    from src.jd_core.quality.validators import evaluate_jd_rules

    return {i.rule_id for i in evaluate_jd_rules(jd, flatten_jd(jd), rules=rules)}


@pytest.mark.parametrize("name", ["391c5ae6", "000cebb7"], ids=["cupe", "jdfn"])
def test_rewritten_qualifications_run_k_s_a_as_their_merge_does(
    rules: Rules, name: str
) -> None:
    """391c5ae6 (CUPE) and 000cebb7 (JDFN): each merge passes SFU-GATE-KSA-ORDER; the
    stored rewrites fail it (612 of 636 CUPE, 359 of 1,810 JDFN drafts) — the model's
    order kept, restored lines appended, the bars last, kinds relabelled."""
    merged, model = _case(name)
    assert "SFU-GATE-KSA-ORDER" not in _issue_ids(merged.draft, rules)
    guarded, record = _apply_anti_fabrication(model, merged, rules)
    final = _final(merged, guarded)
    assert "SFU-GATE-KSA-ORDER" not in _issue_ids(final, rules)
    bars = [q.text for q in merged.draft.qualifications if q.kind == "education"]
    assert [q.text for q in final.qualifications if q.kind == "education"] == bars
    # the ORDER alone (HR-293) holds the gate, whatever kinds the model wrote
    order_only = _with(rules, qualification_kind_from_source=False)
    guarded_order, _ = _apply_anti_fabrication(model, merged, order_only)
    assert "SFU-GATE-KSA-ORDER" not in _issue_ids(_final(merged, guarded_order), rules)

    old = _with(
        rules, qualification_order="model", qualification_kind_from_source=False
    )
    guarded_old, _ = _apply_anti_fabrication(model, merged, old)
    assert "SFU-GATE-KSA-ORDER" in _issue_ids(_final(merged, guarded_old), rules)


def test_a_cupe_rewrite_gets_no_knowledge_kind_its_merge_never_had(
    rules: Rules,
) -> None:
    merged, model = _case("391c5ae6")
    assert "knowledge" not in {q.kind for q in merged.draft.qualifications}
    assert "knowledge" in {q.kind for q in model.qualifications}  # the real reply
    guarded, record = _apply_anti_fabrication(model, merged, rules)
    assert "knowledge" not in {q.kind for q in guarded.qualifications}
    assert any(old == "knowledge" for _, old, _ in record.relabelled_qualifications)


# --- 7. no working conditions imported into the Position Summary (HR-295) -----------


def test_the_summary_does_not_gain_working_conditions_its_source_lacks(
    rules: Rules,
) -> None:
    """3af59608: the rewrite moved the WJQ's working conditions into the summary and the
    blocking SFU-AUTH-SUMMARY-CONDITIONS fired; the merge's summary does not."""
    merged, model = _case("3af59608")
    assert "SFU-AUTH-SUMMARY-CONDITIONS" in _issue_ids(_final(merged, model), rules)
    assert "SFU-AUTH-SUMMARY-CONDITIONS" not in _issue_ids(merged.draft, rules)

    guarded, record = _apply_anti_fabrication(model, merged, rules)
    final = _final(merged, guarded)
    assert "SFU-AUTH-SUMMARY-CONDITIONS" not in _issue_ids(final, rules)
    dropped = [t for s, t in record.scrubbed_items if s == "position_summary"]
    assert dropped
    assert all(d not in (final.position_summary or "") for d in dropped)
    assert final.position_summary  # the rest of the summary stays

    off = _with(rules, summary_conditions_must_be_grounded=False)
    guarded_off, _ = _apply_anti_fabrication(model, merged, off)
    assert "SFU-AUTH-SUMMARY-CONDITIONS" in _issue_ids(
        _final(merged, guarded_off), rules
    )

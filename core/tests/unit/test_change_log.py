"""The harmonization change-log / per-source diff generator (Phase 4.3).

The diff is a pure, deterministic, order-invariant view of what the Phase-4.1 merge
did: which member fed each section, which of a member's duties survived vs were
folded/dropped, and exactly what was removed and why. Its verdicts MUST agree with the
merge — this repo has been bitten repeatedly by "a second copy of the
tokenizer/ordering that silently disagrees", so the couplings are pinned by MUTATION:

* the deduped-vs-dropped verdict routes through the merge's SHARED
  ``dropped_duty_occurrences`` (the ACTUAL cap-drop group fate), monkeypatch it -> the
  verdict flips — NOT a Jaccard-to-draft proxy, which misreads a duty that folded into a
  surviving group but drifted below threshold from its representative as a cap-drop;
* that helper shares the merge's grouping (``_tokens`` / ``_jaccard`` /
  ``duty_dedup_jaccard_min``): monkeypatch the alphabet -> the grouping flips;
* ``member_index`` is the merge's canonical order (reversing input changes NO index;
  it aligns with ``MergeProvenance.section_contributors``).
"""

from __future__ import annotations

import pytest

from src.jd_core.bank import change_log, merge
from src.jd_core.bank.change_log import build_harmonization_diff
from src.jd_core.bank.merge import (
    canonical_member_order,
    dropped_duty_occurrences,
    merge_cluster,
)
from src.jd_core.bank.render import render_sfu_jd_text
from src.jd_core.models.bank import (
    AntiFabricationRecord,
    HarmonizationDiff,
    RewrittenDraft,
)
from src.jd_core.models.parsed_jd import (
    SFUDuty,
    SFUJobDescription,
    SFUQualification,
    SFURelationships,
)
from src.jd_core.rules import Rules, get_rules


@pytest.fixture(scope="module")
def rules() -> Rules:
    return get_rules()


def _with(rules: Rules, **harmon: object) -> Rules:
    return rules.model_copy(
        update={"harmonization": rules.harmonization.model_copy(update=harmon)}
    )


def _duty(statement: str) -> SFUDuty:
    return SFUDuty(action_verb="Performs", statement=statement)


def _member(**overrides: object) -> SFUJobDescription:
    base: dict[str, object] = {
        "title": "Budget Analyst",
        "department": "Financial Services",
        "grade": "B80",
        "employee_group": "apsa",
        "position_summary": "Supports the annual budget cycle for the faculty.",
        "duties": [_duty("the annual operating budget alpha beta gamma delta")],
        "qualifications": [
            SFUQualification(text="budget forecasting", kind="skill"),
        ],
    }
    base.update(overrides)
    return SFUJobDescription(**base)  # type: ignore[arg-type]


# Statements whose token-Jaccard is exactly 6/8 = 0.75 (merge at 0.7, split at 0.8).
_DUTY_ALPHA = "manage budget finance report staff schedule alpha"
_DUTY_OMEGA = "manage budget finance report staff schedule omega"
_DUTY_WRITE = "write quarterly compliance documentation reports"
_DUTY_COORD = "coordinate vendor procurement logistics operations"


def _dedup_and_cap_cluster() -> list[SFUJobDescription]:
    """A member A carrying a duty deduped against member B's near-identical duty, plus
    two singleton duties; under ``max_duties=2`` exactly one singleton is capped out.

    B's ``_DUTY_OMEGA`` is the representative (lexicographically > ``_DUTY_ALPHA`` at
    equal length, no how_why), so it lands in the draft verbatim; A's ``_DUTY_ALPHA``
    folds onto it (dedup); of A's two singletons ``_DUTY_COORD`` sorts first and is
    kept, ``_DUTY_WRITE`` is dropped by the cap.
    """
    return [
        _member(
            title="Analyst A",
            duties=[_duty(_DUTY_ALPHA), _duty(_DUTY_WRITE), _duty(_DUTY_COORD)],
        ),
        _member(title="Analyst B", duties=[_duty(_DUTY_OMEGA)]),
    ]


def _reason_for(diff: HarmonizationDiff, content: str) -> str | None:
    for r in diff.removed:
        if r.content == content:
            return r.reason
    return None


def _source_by_title(diff: HarmonizationDiff, title: str) -> object:
    return next(sc for sc in diff.per_source if sc.title == title)


# --- acceptance 1: the diff AGREES with the merge, pinned by mutation ---------------


def test_kept_deduped_dropped_agree_with_the_merge(rules: Rules) -> None:
    cluster = _dedup_and_cap_cluster()
    capped = _with(rules, max_duties=2)
    merged = merge_cluster(cluster, rules=capped)
    diff = build_harmonization_diff(merged, cluster, rules=capped)

    draft_statements = {d.statement for d in merged.draft.duties}
    assert _DUTY_OMEGA in draft_statements  # representative survived verbatim
    assert _DUTY_ALPHA not in draft_statements  # folded away
    assert "duties_over_max" in merged.provenance.flags

    src_a = _source_by_title(diff, "Analyst A")
    src_b = _source_by_title(diff, "Analyst B")
    # B is the representative for the shared duty: kept verbatim.
    assert src_b.duties_kept == (_DUTY_OMEGA,)
    assert src_b.duties_folded_or_dropped == ()
    # A's near-identical duty folds; A's capped duty drops; A's other singleton is kept.
    assert _DUTY_COORD in src_a.duties_kept
    assert _DUTY_ALPHA in src_a.duties_folded_or_dropped
    assert _DUTY_WRITE in src_a.duties_folded_or_dropped

    assert _reason_for(diff, _DUTY_ALPHA) == "duty_deduplicated"
    assert _reason_for(diff, _DUTY_WRITE) == "duty_dropped_over_max"


def test_drop_verdict_routes_through_the_group_fate_helper(
    rules: Rules, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The cap-drop verdict is the merge's ACTUAL group fate: if the diff re-derived it
    privately, monkeypatching ``dropped_duty_occurrences`` would not move it. It does —
    with 'nothing dropped', the genuinely capped duty reclassifies to deduplicated —
    proving the verdict routes through the shared helper, not a private copy."""
    cluster = _dedup_and_cap_cluster()
    capped = _with(rules, max_duties=2)
    merged = merge_cluster(cluster, rules=capped)

    baseline = build_harmonization_diff(merged, cluster, rules=capped)
    assert _reason_for(baseline, _DUTY_WRITE) == "duty_dropped_over_max"

    monkeypatch.setattr(
        change_log, "dropped_duty_occurrences", lambda *a, **k: frozenset()
    )
    mutated = build_harmonization_diff(merged, cluster, rules=capped)
    assert _reason_for(mutated, _DUTY_WRITE) == "duty_deduplicated"


def test_group_fate_helper_uses_the_merge_grouping_alphabet(
    rules: Rules, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``dropped_duty_occurrences`` shares the merge's ``_tokens`` grouping — a
    divergent alphabet changes which groups exist and therefore which the cap drops. A
    private copy in the diff would NOT track this monkeypatch."""
    ordered = canonical_member_order(_dedup_and_cap_cluster())
    harmon = _with(rules, max_duties=2).harmonization
    # Real tokenizer: the alpha/omega pair share a group (coverage 2, survives); only
    # the write singleton is cap-dropped.
    baseline = dropped_duty_occurrences(ordered, harmon)
    assert any(stmt == _DUTY_WRITE for _, stmt in baseline)
    assert not any(stmt == _DUTY_OMEGA for _, stmt in baseline)
    # Whole-string 'tokens' make every statement its own group -> a different fate.
    monkeypatch.setattr(merge, "_tokens", lambda text: frozenset({text}))
    assert dropped_duty_occurrences(ordered, harmon) != baseline


def test_group_fate_helper_honours_the_registered_threshold(rules: Rules) -> None:
    """The grouping shares ``duty_dedup_jaccard_min`` (HR-171), not a hardcoded number.
    The 0.75 pair, under ``max_duties=1``: at the shipped 0.7 it is ONE group (nothing
    cap-dropped); one step stricter (0.8) it splits into two and one is dropped."""
    ordered = canonical_member_order(
        [_member(duties=[_duty(_DUTY_ALPHA)]), _member(duties=[_duty(_DUTY_OMEGA)])]
    )
    shipped = _with(rules, max_duties=1).harmonization
    assert dropped_duty_occurrences(ordered, shipped) == frozenset()
    stricter = _with(rules, max_duties=1, duty_dedup_jaccard_min=0.8).harmonization
    assert dropped_duty_occurrences(ordered, stricter) != frozenset()


# --- MUST-FIX #1: a folded duty that drifts from its surviving group's rep ----------

# A 3-token drift: the group SEED `_DRIFT_SEED` is within 0.7 of both `_DRIFT_FOLDED`
# and `_DRIFT_REP` (5/7 each), but the two leaves are only 0.5 to each other. The rep is
# re-picked as `_DRIFT_REP` (richest how_why), so `jaccard(_DRIFT_FOLDED, draft_rep)` is
# 0.5 < 0.7 — a Jaccard-to-draft proxy would misread the folded duty as a cap-drop.
_DRIFT_SEED = "aaa mmm1 mmm2 mmm3 mmm4 mmm5"
_DRIFT_FOLDED = "mmm1 mmm2 mmm3 mmm4 mmm5 zzd"
_DRIFT_REP = "mmm2 mmm3 mmm4 mmm5 aaa zzr"
_DRIFT_DROPPED = "qqq1 qqq2 qqq3 unique singleton"


def _drift_cluster() -> list[SFUJobDescription]:
    return [
        _member(
            title="Seeded",
            duties=[
                _duty(_DRIFT_SEED),
                _duty(_DRIFT_FOLDED),
                _duty(_DRIFT_DROPPED),
            ],
        ),
        _member(
            title="Rep",
            duties=[
                SFUDuty(
                    action_verb="Performs",
                    statement=_DRIFT_REP,
                    how_why=["because it drives the strategy"],
                )
            ],
        ),
    ]


def test_a_folded_duty_that_drifts_from_its_rep_is_deduplicated_not_dropped(
    rules: Rules,
) -> None:
    """The reviewer's must-fix: with ``max_duties=1`` the seed/folded/rep collapse into
    ONE surviving group (coverage 2) and the ``_DRIFT_DROPPED`` singleton is the group
    the cap actually drops. ``_DRIFT_FOLDED`` folded into the SURVIVING group but
    drifted below threshold from its representative — it must read as
    ``duty_deduplicated`` (the group fate), NOT ``duty_dropped_over_max`` (which the old
    Jaccard-to-draft proxy gave).
    """
    cluster = _drift_cluster()
    capped = _with(rules, max_duties=1)
    merged = merge_cluster(cluster, rules=capped)

    # The merge kept the drifted group (coverage 2) and dropped the true singleton.
    assert [d.statement for d in merged.draft.duties] == [_DRIFT_REP]
    assert merged.provenance.duty_coverage[0] == (_DRIFT_REP, 2)
    assert "duties_over_max" in merged.provenance.flags

    diff = build_harmonization_diff(merged, cluster, rules=capped)
    # The drifted-but-folded duty: deduplicated, NOT a cap-drop (old proxy said drop).
    assert _reason_for(diff, _DRIFT_FOLDED) == "duty_deduplicated"
    # The genuinely capped singleton: still a real cap-drop.
    assert _reason_for(diff, _DRIFT_DROPPED) == "duty_dropped_over_max"


# --- acceptance 2: member_index aligns with provenance + order-invariance -----------


def _rich_cluster() -> list[SFUJobDescription]:
    return [
        _member(title="Budget Analyst", grade="B80", duties=[_duty(_DUTY_ALPHA)]),
        _member(
            title="Senior Budget Analyst", grade="B80", duties=[_duty(_DUTY_OMEGA)]
        ),
        _member(
            title="Aardvark Wrangler",
            grade="C90",
            position_summary="Wrangles the aardvarks across the western range daily.",
            duties=[_duty("wrangle the aardvarks across the range")],
        ),
    ]


def test_member_index_aligns_with_provenance_contributors(rules: Rules) -> None:
    cluster = _rich_cluster()
    merged = merge_cluster(cluster, rules=rules)
    diff = build_harmonization_diff(merged, cluster, rules=rules)

    # per_source is one entry per member, in canonical order 0..n-1.
    assert [sc.member_index for sc in diff.per_source] == list(range(len(cluster)))
    ordered = canonical_member_order(cluster)
    assert [sc.title for sc in diff.per_source] == [jd.title for jd in ordered]

    # A section's provenance contributor index and the diff's member_index point at the
    # SAME member: that member's SourceContribution lists the section it fed.
    for section, indices in merged.provenance.section_contributors:
        for i in indices:
            assert section in diff.per_source[i].contributed_sections


def test_diff_is_order_invariant_byte_identical(rules: Rules) -> None:
    cluster = _rich_cluster()
    merged_fwd = merge_cluster(cluster, rules=rules)
    merged_rev = merge_cluster(list(reversed(cluster)), rules=rules)
    fwd = build_harmonization_diff(merged_fwd, cluster, rules=rules)
    rev = build_harmonization_diff(merged_rev, list(reversed(cluster)), rules=rules)
    rot = build_harmonization_diff(
        merge_cluster(cluster[1:] + cluster[:1], rules=rules),
        cluster[1:] + cluster[:1],
        rules=rules,
    )
    assert fwd == rev == rot
    assert fwd.model_dump_json() == rev.model_dump_json() == rot.model_dump_json()


# --- acceptance 3: "removed content and why" is complete + correctly reasoned -------


def test_a_clean_cluster_removes_nothing(rules: Rules) -> None:
    diff = build_harmonization_diff(
        merge_cluster([_member(), _member()], rules=rules),
        [_member(), _member()],
        rules=rules,
    )
    assert diff.removed == ()


def test_sections_not_merged_lists_the_actual_content_not_just_a_flag(
    rules: Rules,
) -> None:
    cluster = [
        _member(title="Plain"),
        _member(
            title="Rich",
            problem_solving=["Resolves cross-team scheduling conflicts."],
            decision_making=["Approves vendor contracts up to $50k."],
            position_number="P-12345",
            relationships=SFURelationships(supervisory="Supervises 3 coordinators."),
        ),
    ]
    merged = merge_cluster(cluster, rules=rules)
    assert "sections_not_merged" in merged.provenance.flags
    diff = build_harmonization_diff(merged, cluster, rules=rules)

    rich_index = next(sc.member_index for sc in diff.per_source if sc.title == "Rich")
    section_removed = {
        r.content: r.member_index
        for r in diff.removed
        if r.reason == "section_not_merged"
    }
    for content in (
        "Resolves cross-team scheduling conflicts.",
        "Approves vendor contracts up to $50k.",
        "P-12345",
        "Supervises 3 coordinators.",
    ):
        assert content in section_removed
        assert section_removed[content] == rich_index


# --- acceptance 4: rewrite folding is optional + correct ----------------------------


def test_rewrite_none_is_a_merge_only_diff(rules: Rules) -> None:
    cluster = [_member(), _member()]
    diff = build_harmonization_diff(
        merge_cluster(cluster, rules=rules), cluster, rules=rules, rewrite=None
    )
    assert diff.flagged_duties == ()
    assert not any(
        r.reason == "qualification_scrubbed_ungrounded" for r in diff.removed
    )


def test_rewrite_record_folds_scrubbed_and_flagged(rules: Rules) -> None:
    cluster = [_member(), _member()]
    merged = merge_cluster(cluster, rules=rules)
    record = AntiFabricationRecord(
        scrubbed_skills=("an ungrounded qualification",),
        flagged_duties=("a flagged duty statement",),
    )
    diff = build_harmonization_diff(merged, cluster, rules=rules, rewrite=record)

    scrubbed = [
        r for r in diff.removed if r.reason == "qualification_scrubbed_ungrounded"
    ]
    assert [r.content for r in scrubbed] == ["an ungrounded qualification"]
    assert all(r.member_index is None for r in scrubbed)
    # flagged != removed: a flagged duty stays surfaced, not in `removed`.
    assert diff.flagged_duties == ("a flagged duty statement",)
    assert "a flagged duty statement" not in {r.content for r in diff.removed}


def test_rewrite_accepts_a_rewritten_draft(rules: Rules) -> None:
    cluster = [_member(), _member()]
    merged = merge_cluster(cluster, rules=rules)
    record = AntiFabricationRecord(scrubbed_skills=("scrubbed via rewrite",))
    rewritten = RewrittenDraft(
        draft=merged.draft,
        score=88.0,
        grade="B",
        anti_fabrication=record,
        model="test-model",
        prompt_version="v1",
        rules_version=rules.version,
    )
    diff = build_harmonization_diff(merged, cluster, rules=rules, rewrite=rewritten)
    assert any(
        r.content == "scrubbed via rewrite"
        and r.reason == "qualification_scrubbed_ungrounded"
        for r in diff.removed
    )


# --- acceptance 6: render is display-only -------------------------------------------


def test_rendered_draft_is_exactly_the_renderer_output(rules: Rules) -> None:
    cluster = _rich_cluster()
    merged = merge_cluster(cluster, rules=rules)
    diff = build_harmonization_diff(merged, cluster, rules=rules)
    assert diff.rendered_draft == render_sfu_jd_text(merged.draft)


# --- no approval / decision surface (non-negotiable #1) -----------------------------


def test_the_diff_has_no_approval_or_score_surface() -> None:
    fields = set(HarmonizationDiff.model_fields)
    assert not (
        fields & {"approved", "canonical", "published", "score", "grade", "approved_by"}
    )

"""The deterministic harmonization merge engine (Phase 4.1).

Every knob in ``harmonization.yaml`` (HR-167…HR-175) is pinned by MUTATION — a
behavioural test that goes red when the shipped value is changed via ``model_copy``
(the register drift alarm is proved separately in ``test_decision_register.py``). The
two threshold knobs (``duty_dedup_jaccard_min``, ``core_skill_min_fraction``) carry
BOUNDARY pins. Order-invariance is a real property, pinned to byte-identity.

Fixtures are realistic JDFN members (title + summary + duties + qualifications), not
degenerate stubs — a fixture that makes a bug unwritable is a defect.
"""

from __future__ import annotations

import pytest

from src.jd_core.bank.merge import canonical_member_order, merge_cluster
from src.jd_core.models.bank import MergedRole
from src.jd_core.models.parsed_jd import (
    SFUDuty,
    SFUJobDescription,
    SFUQualification,
    SFURelationships,
)
from src.jd_core.quality.validators import evaluate_jd_rules
from src.jd_core.rules import Rules, get_rules


@pytest.fixture(scope="module")
def rules() -> Rules:
    return get_rules()


def _with(rules: Rules, **harmon: object) -> Rules:
    """A rulebook with the merge knobs retuned (the mutation the register would
    record in step)."""
    return rules.model_copy(
        update={"harmonization": rules.harmonization.model_copy(update=harmon)}
    )


def _member(**overrides: object) -> SFUJobDescription:
    base: dict[str, object] = {
        "title": "Budget Analyst",
        "department": "Financial Services",
        "grade": "B80",
        "employee_group": "apsa",
        "position_summary": "Supports the annual budget cycle for the faculty.",
        "duties": [
            SFUDuty(action_verb="Prepares", statement="the annual operating budget."),
            SFUDuty(action_verb="Reconciles", statement="monthly ledger variances."),
        ],
        "qualifications": [
            SFUQualification(
                text="a bachelor's degree in accounting", kind="education"
            ),
            SFUQualification(
                text="budget forecasting", kind="skill", modifier="advanced"
            ),
        ],
    }
    base.update(overrides)
    return SFUJobDescription(**base)  # type: ignore[arg-type]


# --- basic shape + degenerate clusters ---------------------------------------------


def test_merge_returns_a_draft_plus_provenance(rules: Rules) -> None:
    merged = merge_cluster(
        [_member(), _member(title="Senior Budget Analyst")], rules=rules
    )
    assert isinstance(merged, MergedRole)
    assert isinstance(merged.draft, SFUJobDescription)
    assert merged.provenance.member_count == 2


def test_an_empty_cluster_is_a_value_error(rules: Rules) -> None:
    with pytest.raises(ValueError, match="empty cluster"):
        merge_cluster([], rules=rules)


def test_a_single_member_is_a_flagged_passthrough(rules: Rules) -> None:
    member = _member()
    merged = merge_cluster([member], rules=rules)
    assert merged.provenance.member_count == 1
    assert "single_member" in merged.provenance.flags
    assert merged.draft.title == member.title


# --- title selection (HR-167) ------------------------------------------------------


def _title_cluster() -> list[SFUJobDescription]:
    # modal `normalize_title` group is "budget analyst" (2 members); its shortest raw
    # representative is "Budget Analyst". The lexicographically-first RAW title is
    # "Aardvark Wrangler" — so the two policies disagree.
    return [
        _member(title="Budget Analyst"),
        _member(title="Senior Budget Analyst"),
        _member(title="Aardvark Wrangler"),
    ]


def test_title_is_the_modal_normalized_representative(rules: Rules) -> None:
    merged = merge_cluster(_title_cluster(), rules=rules)
    assert merged.draft.title == "Budget Analyst"


def test_title_policy_first_raw_is_pinned_by_mutation(rules: Rules) -> None:
    mutated = _with(rules, title_policy="first_raw")
    assert (
        merge_cluster(_title_cluster(), rules=mutated).draft.title
        == "Aardvark Wrangler"
    )
    # ...and the shipped default does NOT pick that one.
    assert merge_cluster(_title_cluster(), rules=rules).draft.title == "Budget Analyst"


# --- scalar selection + disagreement flags -----------------------------------------


def test_modal_scalars_and_disagreement_flags(rules: Rules) -> None:
    cluster = [
        _member(grade="B80", employee_group="apsa"),
        _member(grade="B80", employee_group="apsa"),
        _member(grade="C90", employee_group="poly"),
    ]
    merged = merge_cluster(cluster, rules=rules)
    assert merged.draft.grade == "B80"  # modal
    assert merged.draft.employee_group == "apsa"  # modal
    assert "grade_disagreement" in merged.provenance.flags
    assert "employee_group_disagreement" in merged.provenance.flags


def test_no_disagreement_flag_when_scalars_agree(rules: Rules) -> None:
    merged = merge_cluster([_member(), _member()], rules=rules)
    assert "grade_disagreement" not in merged.provenance.flags
    assert "employee_group_disagreement" not in merged.provenance.flags


# --- position summary (HR-168) -----------------------------------------------------

_LONG_SUMMARY = " ".join(f"word{i}" for i in range(120))  # in the 100–150 target


def _summary_cluster() -> list[SFUJobDescription]:
    # Two identical SHORT summaries (central to each other, OUT of range) and one long
    # IN-range summary (dissimilar). within_target_then_central picks the in-range one;
    # most_central picks a short one.
    return [
        _member(position_summary="manage the budget"),
        _member(position_summary="manage the budget"),
        _member(position_summary=_LONG_SUMMARY),
    ]


def test_summary_prefers_a_member_within_the_target_range(rules: Rules) -> None:
    merged = merge_cluster(_summary_cluster(), rules=rules)
    assert merged.draft.position_summary == _LONG_SUMMARY


def test_summary_policy_most_central_is_pinned_by_mutation(rules: Rules) -> None:
    mutated = _with(rules, summary_policy="most_central")
    assert merge_cluster(_summary_cluster(), rules=mutated).draft.position_summary == (
        "manage the budget"
    )
    assert merge_cluster(_summary_cluster(), rules=rules).draft.position_summary == (
        _LONG_SUMMARY
    )


# --- additional context (HR-169) ---------------------------------------------------


def _context_cluster() -> list[SFUJobDescription]:
    return [
        _member(additional_context="Occasional evening work."),
        _member(additional_context="Some travel across the region may be required."),
    ]


def test_additional_context_is_dropped_by_default(rules: Rules) -> None:
    assert (
        merge_cluster(_context_cluster(), rules=rules).draft.additional_context is None
    )


def test_additional_context_policy_longest_is_pinned_by_mutation(rules: Rules) -> None:
    mutated = _with(rules, additional_context_policy="longest")
    merged = merge_cluster(_context_cluster(), rules=mutated)
    assert merged.draft.additional_context == (
        "Some travel across the region may be required."
    )


# --- boilerplate presence + draft-is-a-draft (HR-170) ------------------------------


def _footerless_cluster() -> list[SFUJobDescription]:
    return [
        _member(about_sfu_present=False, territorial_acknowledgement_present=False),
        _member(about_sfu_present=False, territorial_acknowledgement_present=False),
    ]


def test_presence_booleans_or_across_members_by_default(rules: Rules) -> None:
    cluster = [
        _member(about_sfu_present=False),
        _member(about_sfu_present=True),
    ]
    assert merge_cluster(cluster, rules=rules).draft.about_sfu_present is True


def test_presence_default_does_not_silently_assert_a_missing_footer(
    rules: Rules,
) -> None:
    """The draft must not claim a footer nobody has (non-negotiable #1 / HR-170)."""
    merged = merge_cluster(_footerless_cluster(), rules=rules)
    assert merged.draft.territorial_acknowledgement_present is False
    assert merged.draft.about_sfu_present is False


def test_boilerplate_presence_policy_all_present_is_pinned_by_mutation(
    rules: Rules,
) -> None:
    mutated = _with(rules, boilerplate_presence_policy="all_present")
    draft = merge_cluster(_footerless_cluster(), rules=mutated).draft
    assert draft.territorial_acknowledgement_present is True
    assert draft.about_sfu_present is True
    assert draft.employment_equity_present is True


# --- duty union / dedup / reorder (HR-171, HR-172) ---------------------------------


def _duty(statement: str) -> SFUDuty:
    return SFUDuty(action_verb="Performs", statement=statement)


def _near_duty_cluster() -> list[SFUJobDescription]:
    # token-Jaccard of the two statements is exactly 6/8 = 0.75.
    return [
        _member(duties=[_duty("manage budget finance report staff schedule alpha")]),
        _member(duties=[_duty("manage budget finance report staff schedule omega")]),
    ]


def test_near_identical_duties_collapse_at_the_shipped_threshold(rules: Rules) -> None:
    merged = merge_cluster(_near_duty_cluster(), rules=rules)
    assert len(merged.draft.duties) == 1
    # the representative carries full coverage: both members contributed.
    assert merged.provenance.duty_coverage[0][1] == 2


def test_duty_dedup_jaccard_min_boundary_is_pinned_by_mutation(rules: Rules) -> None:
    """A pair that merges at the shipped 0.7 (Jaccard 0.75) splits one step past it."""
    stricter = _with(rules, duty_dedup_jaccard_min=0.8)
    assert len(merge_cluster(_near_duty_cluster(), rules=stricter).draft.duties) == 2
    assert len(merge_cluster(_near_duty_cluster(), rules=rules).draft.duties) == 1


def test_distinct_duties_are_preserved_and_coverage_ordered(rules: Rules) -> None:
    cluster = [
        _member(duties=[_duty("alpha beta gamma"), _duty("delta epsilon zeta")]),
        _member(duties=[_duty("alpha beta gamma")]),  # shared -> higher coverage
    ]
    merged = merge_cluster(cluster, rules=rules)
    assert len(merged.draft.duties) == 2
    # the duty two members share sorts first (coverage desc).
    assert merged.draft.duties[0].statement == "alpha beta gamma"
    assert merged.provenance.duty_coverage[0] == ("alpha beta gamma", 2)


def test_duties_over_max_keeps_top_by_coverage_and_flags(rules: Rules) -> None:
    cluster = [
        _member(
            duties=[
                _duty("alpha beta gamma"),
                _duty("delta epsilon zeta"),
                _duty("eta theta iota"),
            ]
        )
    ]
    # default cap (10): all three kept, no flag.
    default = merge_cluster(cluster, rules=rules)
    assert len(default.draft.duties) == 3
    assert "duties_over_max" not in default.provenance.flags
    # mutated cap (2): top two survive, flag fires.
    capped = merge_cluster(cluster, rules=_with(rules, max_duties=2))
    assert len(capped.draft.duties) == 2
    assert "duties_over_max" in capped.provenance.flags


def test_max_duties_boundary_at_the_shipped_twelve_is_pinned_by_mutation(
    rules: Rules,
) -> None:
    """The calibrated value is 12 — the model's own `SFUJobDescription.duties` cap
    (HR-172). A cluster that dedups to EXACTLY 12 distinct duties keeps all 12 and does
    not flag at the shipped default; lowering the cap to 11 forces a real drop and the
    flag. This makes 12 the oracle: reverting the YAML to 10 (register silenced) turns
    this red."""
    twelve = [_duty(f"duty statement number {i:02d} unique") for i in range(12)]
    cluster = [_member(duties=twelve)]

    # shipped default (12): all twelve survive, NO flag.
    default = merge_cluster(cluster, rules=rules)
    assert len(default.draft.duties) == 12
    assert "duties_over_max" not in default.provenance.flags

    # cap lowered to 11: exactly one real drop, flag fires.
    lowered = merge_cluster(cluster, rules=_with(rules, max_duties=11))
    assert len(lowered.draft.duties) == 11
    assert "duties_over_max" in lowered.provenance.flags


# --- KSA rebuild (HR-173, HR-174, HR-175) ------------------------------------------


def _skill(text: str) -> SFUQualification:
    return SFUQualification(text=text, kind="skill")


def _core_skill_cluster() -> list[SFUJobDescription]:
    # "kubernetes" is required by exactly 2 of 4 members (fraction 0.5).
    return [
        _member(qualifications=[_skill("kubernetes administration")]),
        _member(qualifications=[_skill("kubernetes administration")]),
        _member(qualifications=[_skill("excel spreadsheets")]),
        _member(qualifications=[_skill("python scripting")]),
    ]


def _skill_texts(draft: SFUJobDescription) -> str:
    return " ".join(q.text for q in draft.qualifications)


def test_a_core_skill_survives_and_a_one_off_is_dropped(rules: Rules) -> None:
    merged = merge_cluster(_core_skill_cluster(), rules=rules)
    texts = _skill_texts(merged.draft)
    assert "kubernetes" in texts  # 2/4 core, kept
    assert "python" not in texts  # 1/4 incidental, dropped
    assert "excel" not in texts


def test_core_skill_min_fraction_boundary_is_pinned_by_mutation(rules: Rules) -> None:
    """A skill in exactly 2 of 4 members is core at 0.5, dropped one step past it."""
    stricter = _with(rules, core_skill_min_fraction=0.6)
    assert "kubernetes" not in _skill_texts(
        merge_cluster(_core_skill_cluster(), rules=stricter).draft
    )
    assert "kubernetes" in _skill_texts(
        merge_cluster(_core_skill_cluster(), rules=rules).draft
    )


def test_no_core_skills_flag_on_the_skill_empty_case(rules: Rules) -> None:
    # members with only an education qualification carry no skill bag at all.
    cluster = [
        _member(qualifications=[SFUQualification(text="a diploma", kind="education")]),
        _member(qualifications=[SFUQualification(text="a diploma", kind="education")]),
    ]
    merged = merge_cluster(cluster, rules=rules)
    assert "no_core_skills" in merged.provenance.flags


def _education_cluster() -> list[SFUJobDescription]:
    return [
        _member(
            qualifications=[
                SFUQualification(text="a bachelor's degree", kind="education")
            ]
        ),
        _member(
            qualifications=[
                SFUQualification(text="a bachelor's degree", kind="education")
            ]
        ),
        _member(
            qualifications=[
                SFUQualification(text="a master's degree", kind="education")
            ]
        ),
    ]


def test_education_takes_the_max_bar(rules: Rules) -> None:
    merged = merge_cluster(_education_cluster(), rules=rules)
    edu = [q for q in merged.draft.qualifications if q.kind == "education"]
    assert edu and "master" in edu[0].text


def test_seniority_bar_policy_modal_is_pinned_by_mutation(rules: Rules) -> None:
    mutated = _with(rules, seniority_bar_policy="modal")
    merged = merge_cluster(_education_cluster(), rules=mutated)
    edu = [q for q in merged.draft.qualifications if q.kind == "education"]
    assert edu and "bachelor" in edu[0].text  # modal bar (2 of 3)


def _exp(text: str) -> SFUQualification:
    return SFUQualification(text=text, kind="experience")


def test_experience_takes_the_max_bar(rules: Rules) -> None:
    cluster = [
        _member(qualifications=[_exp("three years of experience")]),
        _member(qualifications=[_exp("three years of experience")]),
        _member(qualifications=[_exp("five years of experience")]),
    ]
    merged = merge_cluster(cluster, rules=rules)
    exp = [q for q in merged.draft.qualifications if q.kind == "experience"]
    assert exp and "five" in exp[0].text


def test_a_knowledge_blob_number_does_not_override_an_explicit_experience_qual(
    rules: Rules,
) -> None:
    """Regression: the experience bar is the per-member SIGNAL (which honours
    ``experience_source_kinds`` order — ``experience`` authoritative, ``knowledge``
    fallback), NOT a raw union. A bigger number in a member's ``knowledge`` blob must
    not inflate the emitted bar nor get relabelled ``kind='experience'``."""
    cluster = [
        _member(
            qualifications=[
                _exp("three years of experience"),
                # a knowledge blob with a BIGGER number — must be ignored for the bar
                SFUQualification(
                    text="ten years of strategic planning", kind="knowledge"
                ),
            ]
        ),
        _member(qualifications=[_exp("three years of experience")]),
        _member(qualifications=[_exp("two years of experience")]),
    ]
    merged = merge_cluster(cluster, rules=rules)
    exp = [q for q in merged.draft.qualifications if q.kind == "experience"]
    assert exp, "an experience qualification should be emitted"
    # the explicit 3-year bar wins; the 10-year knowledge blob is neither the bar
    # nor relabelled as experience.
    assert all("ten" not in q.text and "strategic" not in q.text for q in exp)
    assert any("three" in q.text for q in exp)


def test_sections_not_merged_flag_fires_when_a_member_has_unmerged_content(
    rules: Rules,
) -> None:
    cluster = [
        _member(),
        _member(problem_solving=["Resolves cross-team scheduling conflicts."]),
    ]
    # `problem_solving` IS merged by default since HR-211, so the flag has to be
    # provoked with the policy that actually drops it — the flag tracks what the
    # draft LOST, and under `union` this cluster loses nothing.
    merged = merge_cluster(cluster, rules=_with(rules, problem_solving_policy="drop"))
    assert "sections_not_merged" in merged.provenance.flags


def test_no_sections_not_merged_flag_when_those_sections_are_empty(
    rules: Rules,
) -> None:
    merged = merge_cluster([_member(), _member()], rules=rules)
    assert "sections_not_merged" not in merged.provenance.flags


def test_sections_not_merged_fires_on_a_relationships_object_with_content(
    rules: Rules,
) -> None:
    """A PRESENT relationships object CARRYING content trips the flag — pins the
    'present with content' direction (a check weakened to `rel is not None` still
    passes this, but the empty-object test below then fails)."""
    cluster = [
        _member(),
        _member(
            relationships=SFURelationships(supervisory="Supervises 3 coordinators.")
        ),
    ]
    # Under `drop` (HR-212's other option) the object's content really is lost, which
    # is the only policy where this distinction can still be observed.
    merged = merge_cluster(cluster, rules=_with(rules, relationships_policy="drop"))
    assert "sections_not_merged" in merged.provenance.flags


def test_sections_not_merged_ignores_a_present_but_empty_relationships_object(
    rules: Rules,
) -> None:
    """A PRESENT-but-empty relationships object is NOT content — pins the other
    direction, so a regression to `rel is not None` goes red here."""
    cluster = [_member(), _member(relationships=SFURelationships())]
    # Under `drop`, matching the test above — otherwise this passes for the wrong
    # reason (nothing is dropped under `longest`, so the flag would be silent
    # whatever the object held, and the assertion would pin nothing).
    merged = merge_cluster(cluster, rules=_with(rules, relationships_policy="drop"))
    assert "sections_not_merged" not in merged.provenance.flags


def _security_cluster() -> list[SFUJobDescription]:
    return [
        _member(
            qualifications=[
                SFUQualification(text="a valid criminal record check", kind="security")
            ]
        ),
        _member(qualifications=[_skill("budget forecasting")]),
        _member(qualifications=[_skill("budget forecasting")]),
    ]


def test_security_is_unioned_by_default(rules: Rules) -> None:
    merged = merge_cluster(_security_cluster(), rules=rules)
    assert any(q.kind == "security" for q in merged.draft.qualifications)


def test_security_policy_core_only_is_pinned_by_mutation(rules: Rules) -> None:
    mutated = _with(rules, security_policy="core_only")  # 1/3 < 0.5 -> dropped
    merged = merge_cluster(_security_cluster(), rules=mutated)
    assert not any(q.kind == "security" for q in merged.draft.qualifications)


# --- order-invariance (a real property, byte-identical) ----------------------------


def _rich_cluster() -> list[SFUJobDescription]:
    return [
        _member(
            title="Budget Analyst",
            grade="B80",
            duties=[_duty("manage budget finance report staff schedule alpha")],
            qualifications=[_skill("kubernetes administration"), _skill("excel")],
        ),
        _member(
            title="Senior Budget Analyst",
            grade="B80",
            duties=[_duty("manage budget finance report staff schedule omega")],
            qualifications=[_skill("kubernetes administration")],
        ),
        _member(
            title="Aardvark Wrangler",
            grade="C90",
            position_summary=_LONG_SUMMARY,
            duties=[_duty("wrangle the aardvarks")],
            qualifications=[
                SFUQualification(text="a master's degree", kind="education")
            ],
        ),
    ]


def test_merge_is_order_invariant_byte_identical(rules: Rules) -> None:
    cluster = _rich_cluster()
    forward = merge_cluster(cluster, rules=rules)
    reverse = merge_cluster(list(reversed(cluster)), rules=rules)
    rotated = merge_cluster(cluster[1:] + cluster[:1], rules=rules)
    assert forward == reverse == rotated
    assert (
        forward.model_dump_json()
        == reverse.model_dump_json()
        == rotated.model_dump_json()
    )


# --- validator-as-oracle: the draft is a DRAFT, honestly evaluated -----------------


def test_the_draft_is_not_approved_and_trips_the_boilerplate_gates(
    rules: Rules,
) -> None:
    """Running the real validator on the draft asserts the TRUE post-state: the draft
    carries presence booleans, not the mandated paragraphs, so a re-render trips the
    About / footer gates. We assert that honestly — never 'approved'."""
    from src.jd_core.bank.render import render_sfu_jd_text

    merged = merge_cluster(_footerless_cluster(), rules=rules)
    issues = evaluate_jd_rules(
        merged.draft, render_sfu_jd_text(merged.draft), rules=rules
    )
    rule_ids = {issue.rule_id for issue in issues}
    assert "SFU-COMP-ABOUT" in rule_ids


# --- provenance is populated and verifiable ----------------------------------------


def test_provenance_records_frequencies_coverage_and_contributors(rules: Rules) -> None:
    merged = merge_cluster(_rich_cluster(), rules=rules)
    prov = merged.provenance
    assert prov.skill_frequency  # (skill, members) pairs
    # most-common-first: counts are non-increasing.
    counts = [count for _, count in prov.skill_frequency]
    assert counts == sorted(counts, reverse=True)
    assert prov.duty_coverage
    sections = {name for name, _ in prov.section_contributors}
    assert "title" in sections
    # every contributor index is a real member position.
    for _, indices in prov.section_contributors:
        assert all(0 <= i < prov.member_count for i in indices)


# --- P1.2: the reviewer can see WHY the bar is what it is ----------------------
#
# `seniority_bar_policy: max` (HR-175) raises a cluster's education bar to the
# highest any single member stated. That is defensible, and it is invisible: a
# reviewer reading the draft sees "a master's degree" with nothing to say that two
# of the three sources said bachelor's. The human is the NN #1 control and cannot
# rule on what they cannot see — so the merge must RECORD the choice, not just make
# it.


def test_the_seniority_bar_choice_is_recorded_in_provenance(rules: Rules) -> None:
    merged = merge_cluster(_education_cluster(), rules=rules)
    bars = {choice.kind: choice for choice in merged.provenance.seniority_bars}
    assert "education" in bars, "the education bar was chosen but not recorded"

    education = bars["education"]
    assert education.policy == "max"
    # Two members said bachelor's, one said master's; `max` took the master's.
    assert education.member_bars.count(education.chosen) == 1
    assert len(education.member_bars) == 3
    assert education.disagreed, "a 2-vs-1 split must read as a disagreement"
    assert education.agreeing == 1
    assert education.overruled == 2


def test_an_agreed_bar_is_recorded_but_not_flagged_as_disagreement(
    rules: Rules,
) -> None:
    """No disagreement, nothing for the reviewer to weigh — the record still exists
    (so the panel can state the bar's basis) but must not cry wolf."""
    cluster = [
        _member(
            qualifications=[
                SFUQualification(text="a bachelor's degree", kind="education")
            ]
        )
        for _ in range(3)
    ]
    merged = merge_cluster(cluster, rules=rules)
    bars = {choice.kind: choice for choice in merged.provenance.seniority_bars}
    assert bars["education"].agreeing == 3
    assert bars["education"].overruled == 0
    assert not bars["education"].disagreed


def test_a_member_stating_no_bar_is_not_counted_as_disagreeing(
    rules: Rules,
) -> None:
    """`None` means the member stated no education bar AT ALL, which is different
    from stating a lower one. Counting silence as dissent would overstate the
    disagreement the reviewer is being asked to weigh."""
    cluster = [
        _member(
            qualifications=[
                SFUQualification(text="a master's degree", kind="education")
            ]
        ),
        _member(qualifications=[SFUQualification(text="be organised", kind="skill")]),
    ]
    merged = merge_cluster(cluster, rules=rules)
    education = {c.kind: c for c in merged.provenance.seniority_bars}["education"]
    # One member stated a bar, the other stated nothing — asserted by shape rather
    # than by the ladder's ordinal, which is `education_ladder`'s to define (HR-082).
    assert sorted(education.member_bars, key=lambda b: b is not None) == [
        None,
        education.chosen,
    ]
    assert education.agreeing == 1
    assert education.overruled == 0, "a silent member is not an overruled one"
    assert not education.disagreed


def test_the_recorded_bar_matches_the_policy_actually_applied(rules: Rules) -> None:
    """Mutation pin: flip the policy and the RECORD must follow the draft. A
    provenance record that keeps saying `max` while `modal` was applied is worse
    than none — it is a confident lie in the audit packet."""
    mutated = _with(rules, seniority_bar_policy="modal")
    merged = merge_cluster(_education_cluster(), rules=mutated)
    education = {c.kind: c for c in merged.provenance.seniority_bars}["education"]
    assert education.policy == "modal"
    assert education.agreeing == 2  # the modal bachelor's
    assert education.overruled == 1


def test_the_experience_bar_is_recorded_too(rules: Rules) -> None:
    cluster = [
        _member(qualifications=[_exp("three years of experience")]),
        _member(qualifications=[_exp("three years of experience")]),
        _member(qualifications=[_exp("five years of experience")]),
    ]
    merged = merge_cluster(cluster, rules=rules)
    bars = {choice.kind: choice for choice in merged.provenance.seniority_bars}
    assert bars["experience"].chosen == 5
    assert bars["experience"].overruled == 2


# --- the WJQ's point-factor sections survive the merge (CUPE Phase E, HR-207) --------


def test_a_cupe_clusters_point_factor_sections_are_not_dropped() -> None:
    """🔴 THE DEFECT, FOUND ON THE LIVE BANK 2026-08-17.

    ``additional_context`` means different things on the two forms. On a JDFN JD it is
    an optional trailing note, so ``drop`` (HR-169) is right. On the WJQ it is where the
    parser stores SEVEN OF THE FOURTEEN SECTIONS — and the harmonizer was applying the
    JDFN policy to it, discarding half of every CUPE form at merge time.

    Measured: 95.4% of CUPE sources carry it (avg 5,524 chars); **0 of 553 CUPE drafts
    had any**. A reviewer would have seen a CUPE role with no Level of Independence, no
    Impact of Errors and no Working Conditions, with nothing saying they ever existed.
    """
    members = [
        SFUJobDescription(
            title="Postal Clerk",
            employee_group="cupe",
            additional_context="LEVEL OF INDEPENDENCE\nWorks under supervision.",
        ),
        SFUJobDescription(
            title="Postal Clerk",
            employee_group="cupe",
            additional_context=(
                "LEVEL OF INDEPENDENCE\nWorks under general supervision, referring "
                "unusual cases upward.\n\nEFFORT\nSustained standing and lifting."
            ),
        ),
    ]

    merged = merge_cluster(members)

    context = merged.draft.additional_context or ""
    assert "LEVEL OF INDEPENDENCE" in context
    assert "EFFORT" in context  # the longest member's blocks, carried whole


def test_a_jdfn_cluster_still_drops_its_additional_context() -> None:
    """The control. HR-169 is HR's registered decision for the JDFN form and Phase E
    does not touch it — the overlay applies only when EVERY member is a WJQ document,
    so a JDFN cluster merges exactly as it did before."""
    members = [
        SFUJobDescription(
            title="Analyst",
            employee_group="apsa",
            additional_context="A per-member note that JDFN policy drops.",
        ),
        SFUJobDescription(title="Analyst", employee_group="apsa"),
    ]

    assert merge_cluster(members).draft.additional_context is None


def test_a_mixed_cluster_uses_the_jdfn_policy() -> None:
    """Same tie-break as everywhere else in this phase: unanimity, else JDFN. A mixed
    cluster is authored on the JDFN form (HR-206), so it merges by the JDFN policy —
    the two decisions must not disagree about which form a cluster is."""
    members = [
        SFUJobDescription(
            title="Clerk", employee_group="cupe", additional_context="WJQ block"
        ),
        SFUJobDescription(
            title="Clerk", employee_group="apsa", additional_context="JDFN note"
        ),
    ]

    assert merge_cluster(members).draft.additional_context is None


# --- the three sections 4.1 now merges (HR-210 / HR-211 / HR-212) -------------------
#
# Until 2026-08-20 `merge_cluster` left decision_making / problem_solving /
# relationships at their model defaults for EVERY cluster of EVERY template, and the
# rewrite's `_SECTIONS_NEVER_INVENTED` guard then refused to let the model write them —
# correctly, since it had no source for a word of them. Measured consequence
# (`docs/baseline/jdfn-remeasure-2026-08-19.md`): 685 post-guard JDFN drafts, 0 with a
# Decision Making section, mean score 66.42, and all three completeness rules firing on
# 100% of drafts — a constant, not a signal. The content was in the sources all along
# (97.0% / 44.9% / 97.4%); the merge dropped it. Each section is now a registered knob.


def _dm(*statements: str) -> dict[str, object]:
    return {"decision_making": list(statements)}


def test_decision_making_union_pools_every_members_statements(rules: Rules) -> None:
    """The shipped default. A statement any member made survives into the draft —
    this is the section being merged at all, which is the whole point of HR-210."""
    merged = merge_cluster(
        [
            _member(**_dm("Approves expenditures up to $10,000.")),
            _member(**_dm("Selects the reporting cadence for the faculty.")),
        ],
        rules=rules,
    )
    assert set(merged.draft.decision_making) == {
        "Approves expenditures up to $10,000.",
        "Selects the reporting cadence for the faculty.",
    }


def test_decision_making_union_folds_near_identical_statements(rules: Rules) -> None:
    """Two members stating the same decision in near-identical words are ONE
    statement, at the same Jaccard the duty and qualification dedup already use
    (HR-171 - one Jaccard, one home). Without this a 132-member CUPE cluster returns
    the same sentence 132 times."""
    merged = merge_cluster(
        [
            _member(**_dm("Approves expenditures up to $10,000.")),
            _member(**_dm("Approves expenditures up to $10,000")),
        ],
        rules=rules,
    )
    assert len(merged.draft.decision_making) == 1


def test_decision_making_drop_restores_the_pre_2026_08_20_behaviour(
    rules: Rules,
) -> None:
    """MUTATION pin: `drop` is what shipped before HR-210 and empties the section."""
    tuned = _with(rules, decision_making_policy="drop")
    merged = merge_cluster([_member(**_dm("Approves expenditures."))], rules=tuned)
    assert merged.draft.decision_making == []


def test_decision_making_longest_takes_one_members_list_verbatim(
    rules: Rules,
) -> None:
    """MUTATION pin: `longest` is the representative-member shape HR-207 chose for
    additional_context - one member's list, verbatim, nothing pooled."""
    tuned = _with(rules, decision_making_policy="longest")
    merged = merge_cluster(
        [
            _member(**_dm("Approves expenditures up to $10,000.", "Sets the cadence.")),
            _member(**_dm("Signs off on travel claims.")),
        ],
        rules=tuned,
    )
    assert merged.draft.decision_making == [
        "Approves expenditures up to $10,000.",
        "Sets the cadence.",
    ]


def test_decision_making_union_respects_the_models_own_cap(rules: Rules) -> None:
    """`SFUJobDescription.decision_making` is capped at 20 by the model. A union over
    a large cluster must cut to the cap itself rather than raise a ValidationError in
    the middle of a 44-hour producer pass."""
    cluster = [_member(**_dm(f"Approves category {i} spending.")) for i in range(30)]
    merged = merge_cluster(cluster, rules=rules)
    assert len(merged.draft.decision_making) == 20


def test_problem_solving_merges_only_the_members_that_state_it(rules: Rules) -> None:
    """The 44.9% case named in the S-5 measurement: half the cluster carries the
    section. The union is over the members that HAVE it - a member's silence is not a
    statement, and nothing is invented to fill its place."""
    merged = merge_cluster(
        [
            _member(problem_solving=["Resolves cross-team scheduling conflicts."]),
            _member(),
        ],
        rules=rules,
    )
    assert merged.draft.problem_solving == ["Resolves cross-team scheduling conflicts."]


def test_relationships_longest_takes_the_richest_member_verbatim(
    rules: Rules,
) -> None:
    """The shipped default (HR-212). `relationships` is a STRUCTURED object whose
    `supervisory` is prose, so the representative-member shape is the one that cannot
    synthesize a reporting line no source wrote."""
    rich = SFURelationships(
        supervisory="Supervises 3 coordinators.",
        internal=["Dean Office", "Payroll"],
        external=["External auditors"],
    )
    merged = merge_cluster(
        [
            _member(relationships=SFURelationships(supervisory="Reports to the AD.")),
            _member(relationships=rich),
        ],
        rules=rules,
    )
    assert merged.draft.relationships == rich


def test_relationships_union_pools_the_contact_lists(rules: Rules) -> None:
    """MUTATION pin. `union` pools internal/external across members but still takes
    `supervisory` from a single member VERBATIM - a supervisory line is prose about
    one reporting structure, and concatenating two of them invents a third."""
    tuned = _with(rules, relationships_policy="union")
    merged = merge_cluster(
        [
            _member(
                relationships=SFURelationships(
                    supervisory="Supervises 3 coordinators.", internal=["Payroll"]
                )
            ),
            _member(
                relationships=SFURelationships(
                    internal=["Dean Office"], external=["External auditors"]
                )
            ),
        ],
        rules=tuned,
    )
    rel = merged.draft.relationships
    assert rel is not None
    assert rel.supervisory == "Supervises 3 coordinators."
    assert set(rel.internal) == {"Payroll", "Dean Office"}
    assert set(rel.external) == {"External auditors"}


def test_relationships_drop_leaves_the_section_absent(rules: Rules) -> None:
    """MUTATION pin: `drop` is the pre-HR-212 behaviour."""
    tuned = _with(rules, relationships_policy="drop")
    merged = merge_cluster(
        [_member(relationships=SFURelationships(supervisory="Supervises 3."))],
        rules=tuned,
    )
    assert merged.draft.relationships is None


def test_a_merged_section_is_no_longer_reported_as_not_merged(rules: Rules) -> None:
    """`sections_not_merged` must mean "content this draft DROPPED". Once a section
    is merged, flagging it warns a 4.4 reviewer about content that is sitting in the
    draft in front of them - the flag would become a constant and stop being read."""
    merged = merge_cluster(
        [
            _member(**_dm("Approves expenditures.")),
            _member(problem_solving=["Resolves conflicts."]),
        ],
        rules=rules,
    )
    assert merged.draft.decision_making, "precondition: the section IS merged"
    assert "sections_not_merged" not in merged.provenance.flags


def test_a_dropped_section_is_still_reported_as_not_merged(rules: Rules) -> None:
    """The other direction: under a `drop` policy the content really is lost, so the
    flag must still fire. This is what keeps the flag honest under every policy."""
    tuned = _with(rules, decision_making_policy="drop")
    merged = merge_cluster([_member(**_dm("Approves expenditures."))], rules=tuned)
    assert "sections_not_merged" in merged.provenance.flags


def test_position_number_is_still_not_merged_and_still_flagged(rules: Rules) -> None:
    """`position_number` stays out of scope - it identifies a POSITION, and a
    harmonized ROLE has no single one. It is now the only section that flags by
    default, which is why the flag survives at all."""
    merged = merge_cluster([_member(position_number="P-00412")], rules=rules)
    assert "sections_not_merged" in merged.provenance.flags


def test_the_three_merged_sections_are_order_invariant(rules: Rules) -> None:
    """Order-invariance is a property of the whole engine (module docstring) and the
    new sections must not be the hole in it."""
    a = _member(
        **_dm("Approves expenditures."),
        problem_solving=["Resolves conflicts."],
        relationships=SFURelationships(internal=["Payroll"]),
    )
    b = _member(
        **_dm("Sets the reporting cadence."),
        problem_solving=["Triages system outages."],
        relationships=SFURelationships(internal=["Dean Office"]),
    )
    assert merge_cluster([a, b], rules=rules) == merge_cluster([b, a], rules=rules)


def test_merged_sections_record_their_contributing_members(rules: Rules) -> None:
    """Provenance is non-negotiable #6: a merged section must say which members fed
    it, exactly as summary / additional_context / title already do."""
    cluster = [_member(), _member(**_dm("Approves expenditures."))]
    merged = merge_cluster(cluster, rules=rules)
    contributors = dict(merged.provenance.section_contributors)
    # Exactly one member stated it, so exactly one member fed it — and the index is a
    # position in `canonical_member_order`, NOT in the caller's input order (the whole
    # engine is order-invariant, so asserting the input position would be asserting
    # something the merge deliberately does not promise).
    (idx,) = contributors["decision_making"]
    assert canonical_member_order(cluster)[idx].decision_making == [
        "Approves expenditures."
    ]

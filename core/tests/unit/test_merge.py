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

from src.jd_core.bank.merge import merge_cluster
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
    merged = merge_cluster(cluster, rules=rules)
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
    merged = merge_cluster(cluster, rules=rules)
    assert "sections_not_merged" in merged.provenance.flags


def test_sections_not_merged_ignores_a_present_but_empty_relationships_object(
    rules: Rules,
) -> None:
    """A PRESENT-but-empty relationships object is NOT content — pins the other
    direction, so a regression to `rel is not None` goes red here."""
    cluster = [_member(), _member(relationships=SFURelationships())]
    merged = merge_cluster(cluster, rules=rules)
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

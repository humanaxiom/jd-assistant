"""The harmonize REWRITE consumer (Phase 4.2a): validator-as-oracle, the
anti-fabrication guard proved BY MUTATION, and the frozen draft-not-canonical contract.

The chat client is a content-keyed fake — it records the messages it was handed (so a
test can prove the GROUNDED draft was serialized into the prompt) and returns a FIXED
rewritten JD. Assertions read the validator's post-state (score / grade / issue ids) and
the anti-fabrication record — NEVER verbatim model text (non-negotiable #3).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.jd_bank.rewrite.harmonize import (
    _REWRITABLE_FIELDS,
    _flatten_jd,
    rewrite_merged_role,
)
from src.jd_core.bank.merge import merge_cluster
from src.jd_core.models.bank import MergedRole, MergeProvenance, RewrittenDraft
from src.jd_core.models.parsed_jd import (
    JobClassification,
    SFUDuty,
    SFUJobDescription,
    SFUQualification,
    SFURelationships,
)
from src.jd_core.quality.scoring import score_issues
from src.jd_core.quality.validators import evaluate_jd_rules, template_of
from src.jd_core.rules import Rules, get_rules

_INJECTED_SKILL = "Certified underwater basket weaving instructor"
_INVENTED_DUTY = "Waters the office plants every morning"


class _FakeChat:
    """Content-keyed fake: records the (system, user) it received and returns a FIXED
    rewritten JD. Stands in for the whole ``ChatClient.chat_json`` — the client's own
    discipline is proved in ``test_rewrite_client.py``."""

    def __init__(self, jd: SFUJobDescription) -> None:
        self._jd = jd
        self.calls: list[tuple[tuple[str, ...], int, int]] = []

    async def chat_json(
        self,
        messages: object,
        model_cls: type[SFUJobDescription],
        *,
        max_tokens: int,
        max_retries: int,
    ) -> SFUJobDescription:
        assert model_cls is SFUJobDescription
        contents = tuple(m["content"] for m in messages)  # type: ignore[union-attr]
        self.calls.append((contents, max_tokens, max_retries))
        return self._jd.model_copy(deep=True)


@pytest.fixture(scope="module")
def rules() -> Rules:
    return get_rules()


def _draft() -> SFUJobDescription:
    return SFUJobDescription(
        title="Financial Analyst",
        position_summary="Supports the department's budgeting and financial reporting.",
        duties=[
            SFUDuty(
                action_verb="Prepares",
                statement="Prepares the annual budgeting reports for departments",
            ),
            SFUDuty(
                action_verb="Reviews",
                statement="Reviews financial forecasting and reconciliation statements",
            ),
        ],
        qualifications=[
            SFUQualification(
                text="Working knowledge of financial accounting", kind="knowledge"
            ),
        ],
    )


def _member_jd(**overrides: object) -> SFUJobDescription:
    """A cluster MEMBER — a source-shaped JD to feed the real 4.1 merge, as opposed to
    ``_draft()``, which is a merge OUTPUT."""
    return _draft().model_copy(update=overrides)


def _merged() -> MergedRole:
    return MergedRole(
        draft=_draft(),
        provenance=MergeProvenance(
            member_count=3,
            skill_frequency=(("accounting", 3), ("budgeting", 2)),
        ),
    )


# --- acceptance #1: validator-as-oracle -----------------------------------------


@pytest.mark.asyncio
async def test_the_returned_score_grade_and_issues_are_the_validators_verdict(
    rules: Rules,
) -> None:
    """The RewrittenDraft's numbers ARE the validator's verdict on the draft it returned
    — the consumer routed through the oracle, it did not invent a score. Asserted as a
    RELATION (re-evaluate the returned draft), never as a hardcoded score or model text.
    """
    result = await rewrite_merged_role(
        _merged(), client=_FakeChat(_draft()), rules=rules
    )

    issues = evaluate_jd_rules(result.draft, _flatten_jd(result.draft), rules=rules)
    score, grade = score_issues(issues, scoring=rules.scoring)
    assert result.score == score
    assert result.grade == grade
    assert tuple(i.rule_id for i in result.issues) == tuple(i.rule_id for i in issues)


@pytest.mark.asyncio
async def test_boilerplate_presence_is_marked_so_the_grade_reflects_content(
    rules: Rules,
) -> None:
    """The boilerplate sections are template-provided, not authored by the rewrite —
    marked present (exactly as hris `harmonize_cluster`) so the grade is about role
    content, not a footer the composer inserts later."""
    result = await rewrite_merged_role(
        _merged(), client=_FakeChat(_draft()), rules=rules
    )
    assert result.draft.about_sfu_present is True
    assert result.draft.territorial_acknowledgement_present is True
    assert result.draft.employment_equity_present is True


def _with_coded_term_only_in_relationships() -> SFUJobDescription:
    """A draft whose ONLY coded term ("aggressive", a MEDIUM term in coded_terms.yaml)
    sits in the Relationships section — nowhere else. If ``_flatten_jd`` omits
    Relationships, the content-scan rules (which read only the flattened text, not the
    structured object) never see it and the draft grades falsely clean."""
    draft = _draft()
    return draft.model_copy(
        update={
            "relationships": SFURelationships(
                supervisory="Leads an aggressive team of five analysts",
            )
        }
    )


@pytest.mark.asyncio
async def test_a_coded_term_in_relationships_is_scanned_by_the_oracle(
    rules: Rules,
) -> None:
    """The validator scans the flattened text, so EVERY content section the model may
    write must be flattened — Relationships included. A coded term the LLM writes into
    ``supervisory`` must still trip ``SFU-LANG-CODED``; otherwise the score is inflated
    relative to the draft's real content (the baseline scans the full document text).
    Pinned by mutation: drop the relationships branch from ``_flatten_jd`` and this goes
    red (the finding vanishes)."""
    # The merged draft must ALREADY have a Relationships section, or the Phase-D
    # empty-section guard correctly empties the model's — a section the grounded draft
    # does not have cannot be invented. Here the section exists and the rewrite rewords
    # it, which is the case this test is about.
    grounded = MergedRole(
        draft=_draft().model_copy(
            update={"relationships": SFURelationships(supervisory="Leads a team")}
        ),
        provenance=_merged().provenance,
    )
    result = await rewrite_merged_role(
        grounded,
        client=_FakeChat(_with_coded_term_only_in_relationships()),
        rules=rules,
    )
    assert "SFU-LANG-CODED" in {i.rule_id for i in result.issues}


@pytest.mark.asyncio
async def test_the_grounded_draft_and_rule_knobs_feed_the_prompt_and_call(
    rules: Rules,
) -> None:
    """We feed the GROUNDED 4.1 draft into the prompt (not raw members), and the token
    budget / repair budget come from the rulebook (HR-178/179)."""
    fake = _FakeChat(_draft())
    await rewrite_merged_role(_merged(), client=fake, rules=rules)

    contents, max_tokens, max_retries = fake.calls[0]
    user = contents[1]
    assert "Prepares the annual budgeting reports for departments" in user
    assert max_tokens == rules.rewrite.max_tokens
    assert max_retries == rules.rewrite.max_retries


@pytest.mark.asyncio
async def test_the_draft_is_stamped_with_model_prompt_and_rules_version(
    rules: Rules,
) -> None:
    result = await rewrite_merged_role(
        _merged(), client=_FakeChat(_draft()), rules=rules
    )
    assert result.model == rules.rewrite.model
    assert result.prompt_version == rules.rewrite.prompt_version
    assert result.rules_version == rules.version


# --- CUPE Phase D: the prompt, the sections, and the boilerplate claim ---------------


def _cupe_merged() -> MergedRole:
    """The same role as a CUPE (WJQ) draft. ``employee_group`` is the separator the
    whole system reads — Phase B for rules, Phase C for numbers, Phase D for both."""
    return MergedRole(
        draft=_draft().model_copy(update={"employee_group": "cupe"}),
        provenance=_merged().provenance,
    )


@pytest.mark.asyncio
async def test_the_prompt_states_the_drafted_forms_own_duty_count(
    rules: Rules,
) -> None:
    """🔴 THE DEFECT: the duty count was prompt TEXT, so every rewrite asked for JDFN's
    3–5 duties. On a CUPE draft that DELETES the role — the WJQ has twelve duty slots
    and 77.4% of CUPE JDs fill all twelve — and nothing downstream objects: the guard
    exists to stop the model ADDING content, and the WJQ profile's `duties_min` is 3, so
    the mutilated draft passes its own bar.

    Asserted over BOTH forms in one test: a WJQ-only assertion would also pass if the
    resolution were inverted, and a JDFN-only one passed against the hardcoded text.
    """
    jdfn_chat = _FakeChat(_draft())
    await rewrite_merged_role(_merged(), client=jdfn_chat, rules=rules)
    cupe_chat = _FakeChat(_draft().model_copy(update={"employee_group": "cupe"}))
    await rewrite_merged_role(_cupe_merged(), client=cupe_chat, rules=rules)

    jdfn_system = jdfn_chat.calls[0][0][0]
    cupe_system = cupe_chat.calls[0][0][0]
    assert f"{rules.thresholds.duties_max} major duties" in jdfn_system
    wjq = rules.thresholds_for("wjq")
    assert f"{wjq.duties_max} major duties" in cupe_system
    # And the two genuinely differ, so neither assertion can be passing by coincidence.
    assert rules.thresholds.duties_max != wjq.duties_max


@pytest.mark.asyncio
async def test_a_section_the_grounded_draft_lacks_cannot_be_invented(
    rules: Rules,
) -> None:
    """The guard above polices a section's CONTENT; this polices its EXISTENCE, which is
    the coarser fabrication and the one CUPE drafting makes likely. 0.0% of CUPE JDs
    have a Problem Solving section and 3.1% an Impact of Decision Making one — the form
    does not ask — so a model handed a schema listing both will fill them in, and the
    token-overlap guard cannot object because it reads only duties and qualifications.
    """
    invented = _draft().model_copy(
        update={
            "employee_group": "cupe",
            "problem_solving": ["Resolves escalated budgeting discrepancies"],
            "decision_making": ["Approves departmental expenditures"],
        }
    )
    result = await rewrite_merged_role(
        _cupe_merged(), client=_FakeChat(invented), rules=rules
    )

    assert result.draft.problem_solving == []
    assert result.draft.decision_making == []
    assert result.anti_fabrication.scrubbed_sections == (
        "decision_making",
        "problem_solving",
    )


@pytest.mark.asyncio
async def test_a_section_the_grounded_draft_has_is_left_to_the_rewrite(
    rules: Rules,
) -> None:
    """EMPTY-TO-EMPTY only. Rewording a section the draft HAS is the pass's whole job,
    so the guard must not touch it — else it would drop content the sources stated.

    🔴 THE GROUNDED DRAFT IS A REAL ``merge_cluster`` OUTPUT, and that is the point of
    this test rather than an incidental detail. Until HR-211 the merge populated
    ``problem_solving`` for NOBODY, so this protection was unreachable in production
    and could only be exercised by hand-building a ``MergedRole`` the engine could not
    emit — which is exactly how a green suite kept certifying a guard that never fired.
    Building the input through the real merge is what makes the assertion mean
    something; if the section stops being merged, the precondition below goes red.
    """
    grounded = merge_cluster(
        [
            _member_jd(problem_solving=["Original wording"]),
            _member_jd(problem_solving=["Original wording"]),
        ],
        rules=rules,
    )
    assert grounded.draft.problem_solving, (
        "precondition: the MERGE must produce this section, or the guard under test "
        "is unreachable in production and this test proves nothing"
    )
    result = await rewrite_merged_role(
        grounded,
        client=_FakeChat(_draft().model_copy(update={"problem_solving": ["Reworded"]})),
        rules=rules,
    )

    assert result.draft.problem_solving == ["Reworded"]
    assert result.anti_fabrication.scrubbed_sections == ()


@pytest.mark.asyncio
async def test_a_cupe_draft_does_not_claim_boilerplate_its_form_never_carries(
    rules: Rules,
) -> None:
    """ "Template-provided" is a claim about a TEMPLATE, so it holds only for the
    template that provides them. The WJQ form has no About SFU block, no territorial
    acknowledgement and no EDI statement — the fact behind HR-201 — so asserting
    all three on a CUPE draft states something untrue about the document, in the three
    fields a reviewer is likeliest to take at face value.

    It costs no score either way: `applies_to` already withholds the three rules that
    read these fields from the WJQ, so the assertion was never buying the CUPE cohort
    anything. It was only making the draft lie.
    """
    result = await rewrite_merged_role(
        _cupe_merged(),
        client=_FakeChat(_draft().model_copy(update={"employee_group": "cupe"})),
        rules=rules,
    )
    assert result.draft.about_sfu_present is False
    assert result.draft.territorial_acknowledgement_present is False
    assert result.draft.employment_equity_present is False


# --- acceptance #2: anti-fabrication, pinned by mutation ------------------------


def _with_injected_skill() -> SFUJobDescription:
    draft = _draft()
    return draft.model_copy(
        update={
            "qualifications": [
                *draft.qualifications,
                SFUQualification(text=_INJECTED_SKILL, kind="skill"),
            ]
        }
    )


@pytest.mark.asyncio
async def test_an_ungrounded_skill_is_scrubbed_and_recorded(rules: Rules) -> None:
    result = await rewrite_merged_role(
        _merged(), client=_FakeChat(_with_injected_skill()), rules=rules
    )
    texts = [q.text for q in result.draft.qualifications]
    assert _INJECTED_SKILL not in texts  # the fabricated skill is gone
    assert _INJECTED_SKILL in result.anti_fabrication.scrubbed_skills
    # ...and the grounded original survives — the guard scrubs, it does not gut.
    assert any("financial accounting" in t for t in texts)


@pytest.mark.asyncio
async def test_disabling_the_guard_ships_the_fabricated_skill_unscrubbed(
    rules: Rules,
) -> None:
    """THE mutation (acceptance #2): flip ``anti_fabrication_enabled`` (in reality the
    register is updated in step so the drift alarm stays silent) and the BEHAVIOURAL
    assertion — the injected skill is gone — goes red: it is now present, unscrubbed."""
    disabled = rules.model_copy(
        update={
            "rewrite": rules.rewrite.model_copy(
                update={"anti_fabrication_enabled": False}
            )
        }
    )
    result = await rewrite_merged_role(
        _merged(), client=_FakeChat(_with_injected_skill()), rules=disabled
    )
    texts = [q.text for q in result.draft.qualifications]
    assert _INJECTED_SKILL in texts  # NOT scrubbed — the guard was off
    assert result.anti_fabrication.scrubbed_skills == ()
    assert result.anti_fabrication.enabled is False


@pytest.mark.asyncio
async def test_a_no_overlap_duty_is_flagged_but_not_dropped(rules: Rules) -> None:
    draft = _draft()
    rewritten = draft.model_copy(
        update={
            "duties": [
                *draft.duties,
                SFUDuty(action_verb="Waters", statement=_INVENTED_DUTY),
            ]
        }
    )
    result = await rewrite_merged_role(
        _merged(), client=_FakeChat(rewritten), rules=rules
    )

    assert _INVENTED_DUTY in result.anti_fabrication.flagged_duties
    # flagged, NOT dropped — a duty may rephrase; the human reviewer decides.
    assert any(_INVENTED_DUTY == d.statement for d in result.draft.duties)


@pytest.mark.asyncio
async def test_disabling_the_guard_clears_the_duty_flags(rules: Rules) -> None:
    draft = _draft()
    rewritten = draft.model_copy(
        update={
            "duties": [
                *draft.duties,
                SFUDuty(action_verb="Waters", statement=_INVENTED_DUTY),
            ]
        }
    )
    disabled = rules.model_copy(
        update={
            "rewrite": rules.rewrite.model_copy(
                update={"anti_fabrication_enabled": False}
            )
        }
    )
    result = await rewrite_merged_role(
        _merged(), client=_FakeChat(rewritten), rules=disabled
    )
    assert result.anti_fabrication.flagged_duties == ()


def _with_half_grounded_skill() -> SFUJobDescription:
    """A skill whose content tokens are exactly half in the draft vocabulary:
    ``budgeting`` IS in the draft (a duty), ``zzzznovelterm`` is nowhere: fraction 0.5.
    """
    draft = _draft()
    return draft.model_copy(
        update={
            "qualifications": [
                *draft.qualifications,
                SFUQualification(text="budgeting zzzznovelterm", kind="skill"),
            ]
        }
    )


@pytest.mark.asyncio
async def test_grounding_threshold_boundary_keeps_then_scrubs(rules: Rules) -> None:
    """BOUNDARY mutation (HR-183): a qualification with grounded fraction exactly 0.5 is
    KEPT at the shipped threshold and SCRUBBED when the knob is raised past it."""
    kept = await rewrite_merged_role(
        _merged(), client=_FakeChat(_with_half_grounded_skill()), rules=rules
    )
    assert any("zzzznovelterm" in q.text for q in kept.draft.qualifications)

    strict = rules.model_copy(
        update={
            "rewrite": rules.rewrite.model_copy(
                update={"skill_grounding_threshold": 0.6}
            )
        }
    )
    scrubbed = await rewrite_merged_role(
        _merged(), client=_FakeChat(_with_half_grounded_skill()), rules=strict
    )
    assert not any("zzzznovelterm" in q.text for q in scrubbed.draft.qualifications)
    assert "budgeting zzzznovelterm" in scrubbed.anti_fabrication.scrubbed_skills


@pytest.mark.asyncio
async def test_all_grounded_policy_scrubs_a_partially_grounded_skill(
    rules: Rules,
) -> None:
    """POLICY mutation (HR-182): the same half-grounded qualification kept under
    ``token_overlap`` is scrubbed under ``all_grounded`` (every token must be grounded).
    """
    all_grounded = rules.model_copy(
        update={
            "rewrite": rules.rewrite.model_copy(
                update={"skill_grounding_policy": "all_grounded"}
            )
        }
    )
    result = await rewrite_merged_role(
        _merged(), client=_FakeChat(_with_half_grounded_skill()), rules=all_grounded
    )
    assert not any("zzzznovelterm" in q.text for q in result.draft.qualifications)


# --- acceptance #5: non-negotiable #1 — frozen, no approval field ---------------


def test_rewritten_draft_is_frozen_and_has_no_approval_field() -> None:
    assert RewrittenDraft.model_config["frozen"] is True
    fields = set(RewrittenDraft.model_fields)
    forbidden = {
        "approved",
        "approved_by",
        "approved_at",
        "canonical",
        "published",
        "publish",
        "status",
    }
    assert not (fields & forbidden), sorted(fields & forbidden)


@pytest.mark.asyncio
async def test_the_rewritten_draft_cannot_be_mutated(rules: Rules) -> None:
    result = await rewrite_merged_role(
        _merged(), client=_FakeChat(_draft()), rules=rules
    )
    with pytest.raises(ValidationError):
        result.score = 100.0  # type: ignore[misc]


# --- the model may reword a draft; it may not change WHAT DOCUMENT it is -------------


@pytest.mark.asyncio
async def test_the_rewrite_cannot_change_which_form_the_draft_is(
    rules: Rules,
) -> None:
    """🔴 FOUND BY PROBING THE LIVE BANK MID-RUN, 2026-08-17.

    Of ~100 CUPE drafts the rewrite had refreshed, **5** still carried
    ``employee_group == "cupe"``. The prompt's schema offers the field and the model
    returns ``null`` almost every time, so the pass was silently converting CUPE drafts
    into JDFN ones.

    That one field IS the form — ``template_of`` reads it — so a stripped draft loses
    Phase B's rule selection and Phase C's numbers in a single step and is judged by a
    bar it was never written for. Nothing downstream could catch it: the result is a
    perfectly well-formed JDFN document.

    The fake here returns exactly what the live model returned: good prose, no group.
    """
    stripped = _draft().model_copy(update={"employee_group": None})
    result = await rewrite_merged_role(
        _cupe_merged(), client=_FakeChat(stripped), rules=rules
    )

    assert result.draft.employee_group == "cupe"
    assert template_of(result.draft) == "wjq"


@pytest.mark.asyncio
async def test_the_rewrite_cannot_invent_a_grade_or_a_position_number(
    rules: Rules,
) -> None:
    """The same rule for the other two identity fields, and for a reason the model
    cannot argue with: a grade and a position number are facts about the posting that
    the merge derived from the sources. A language model has no way to know either, so
    whatever it writes there is invention — including inventing a value where the merge
    correctly had none."""
    invented = _draft().model_copy(
        update={
            "position_number": "P-99999",
            "classification": JobClassification(
                scheme="apsa", value="12", source="entered"
            ),
        }
    )
    result = await rewrite_merged_role(
        _merged(), client=_FakeChat(invented), rules=rules
    )

    assert result.draft.position_number is None
    assert result.draft.classification is None


@pytest.mark.asyncio
async def test_a_jdfn_drafts_own_group_survives_the_rewrite_too(
    rules: Rules,
) -> None:
    """The control: pinning identity restores what the MERGE said, not a constant. A
    JDFN draft keeps its own group, so the fix cannot be passing by defaulting
    everything to CUPE."""
    grounded = MergedRole(
        draft=_draft().model_copy(update={"employee_group": "apsa"}),
        provenance=_merged().provenance,
    )
    result = await rewrite_merged_role(
        grounded,
        client=_FakeChat(_draft().model_copy(update={"employee_group": "poly"})),
        rules=rules,
    )

    assert result.draft.employee_group == "apsa"


@pytest.mark.asyncio
async def test_the_rewrite_cannot_delete_the_wjq_point_factor_sections(
    rules: Rules,
) -> None:
    """🔴 THE THIRD INSTANCE, and the one that turned a patch into an allow-list.

    HR-207 had just fixed the MERGE to carry the WJQ's point-factor sections through
    `additional_context` — and on the very next production run the rewrite threw them
    away again, because the prompt's schema shows `"additional_context": null` and the
    model obligingly returns null. Seven of the WJQ's fourteen sections, deleted between
    one pass and the next.

    The model is doing what it was asked; the defect was the contract. A rewrite that
    may return any field can delete any field, and "reword this draft" does not license
    dropping content the sources stated.
    """
    grounded = MergedRole(
        draft=_draft().model_copy(
            update={
                "employee_group": "cupe",
                "additional_context": "LEVEL OF INDEPENDENCE\nWorks under supervision.",
            }
        ),
        provenance=_merged().provenance,
    )
    nulled = _draft().model_copy(update={"additional_context": None})

    result = await rewrite_merged_role(grounded, client=_FakeChat(nulled), rules=rules)

    assert result.draft.additional_context == (
        "LEVEL OF INDEPENDENCE\nWorks under supervision."
    )


def test_every_jd_field_is_either_rewritable_or_preserved() -> None:
    """⚠ THE COMPLETENESS PIN, walked from the live model rather than a list.

    Adding a field to ``SFUJobDescription`` without deciding whether the rewrite may
    change it turns this red. The safe default is already "preserved" — an unlisted
    field comes back from the grounded draft — but the decision should be ARGUED in a
    diff rather than made by omission, which is exactly how the three fields above came
    to be deletable in the first place.
    """
    fields = set(SFUJobDescription.model_fields)
    assert _REWRITABLE_FIELDS <= fields

    preserved = fields - _REWRITABLE_FIELDS
    assert preserved == {
        # identity: what document this is
        "employee_group",
        "position_number",
        "department",
        "grade",
        "classification",
        # source content the model is not asked to reword (7 of the WJQ's 14 sections)
        "additional_context",
        # set explicitly, per template, after the rewrite
        "about_sfu_present",
        "territorial_acknowledgement_present",
        "employment_equity_present",
    }


# --- S-2 / S-3 / S-4: the model may reword a draft, it may not silently REMOVE from it


def _merged_with(draft: SFUJobDescription) -> MergedRole:
    return MergedRole(
        draft=draft,
        provenance=MergeProvenance(
            member_count=3,
            skill_frequency=(("accounting", 3), ("budgeting", 2)),
        ),
    )


def _cupe_draft_with_frequencies() -> SFUJobDescription:
    """A CUPE merge draft as the WJQ parser produces one: every duty tagged with how
    often it is performed (Phase 3.4 / HR-142)."""
    return SFUJobDescription(
        title="Departmental Assistant",
        employee_group="cupe",
        position_summary="Provides administrative support to the department.",
        duties=[
            SFUDuty(
                action_verb="Processes",
                statement="Processes purchase orders and invoices for the unit",
                frequency="daily",
            ),
            SFUDuty(
                action_verb="Maintains",
                statement="Maintains the departmental filing and records system",
                frequency="weekly",
            ),
        ],
        qualifications=[
            SFUQualification(text="High school graduation", kind="education"),
            SFUQualification(text="Two years of office experience", kind="experience"),
            SFUQualification(
                text="Working knowledge of financial accounting", kind="knowledge"
            ),
        ],
    )


@pytest.mark.asyncio
async def test_a_duty_frequency_survives_the_rewrite(rules: Rules) -> None:
    """S-4. STRUCTURAL, 100%, not probabilistic: the prompt's duty schema has no
    ``frequency`` key, so the model cannot return one, and ``duties`` is a rewritable
    CONTAINER replaced wholesale. Every CUPE draft the producer wrote came out
    ``['daily', 'weekly'] -> [None, None]``.

    The ``_REWRITABLE_FIELDS`` completeness pin cannot see this: it walks
    ``SFUJobDescription.model_fields`` and ``frequency`` is a field of ``SFUDuty``.
    """
    draft = _cupe_draft_with_frequencies()
    # The model rewords both duties and, as the schema requires, returns no frequency.
    reworded = draft.model_copy(
        update={
            "duties": [
                SFUDuty(
                    action_verb="Processes",
                    statement="Processes purchase orders and invoices for the dept",
                ),
                SFUDuty(
                    action_verb="Maintains",
                    statement="Maintains the departmental records and filing system",
                ),
            ]
        }
    )

    result = await rewrite_merged_role(
        _merged_with(draft), client=_FakeChat(reworded), rules=rules
    )

    assert [d.frequency for d in result.draft.duties] == ["daily", "weekly"]
    # ...and the rewording itself was kept — this restores the FIELD, not the duty.
    assert "for the dept" in result.draft.duties[0].statement


@pytest.mark.asyncio
async def test_a_duty_the_rewrite_dropped_is_recorded_not_silently_gone(
    rules: Rules,
) -> None:
    """S-2. Measured on a real 12-duty CUPE draft: the model returned 3 and the result
    was grade B, 89.05, with **zero duty findings and an empty anti-fabrication
    record**. The guard was written as "scrub what the model ADDED"; nothing at all
    looked at what it REMOVED, so most of a role could vanish and the artifact whose
    whole purpose is "nothing vanishes silently" said nothing."""
    draft = _cupe_draft_with_frequencies()
    kept, dropped = draft.duties[0], draft.duties[1]
    reworded = draft.model_copy(update={"duties": [kept]})

    result = await rewrite_merged_role(
        _merged_with(draft), client=_FakeChat(reworded), rules=rules
    )

    assert dropped.statement in result.anti_fabrication.removed_duties
    assert kept.statement not in result.anti_fabrication.removed_duties


@pytest.mark.asyncio
async def test_an_ordinary_rewording_removes_nothing(rules: Rules) -> None:
    """The control for S-2, and the one that matters: rewording IS the pass's job. A
    removal detector that fired on a reworded duty would make the record noise, and a
    noisy record is read the same way an empty one is."""
    draft = _cupe_draft_with_frequencies()
    reworded = draft.model_copy(
        update={
            "duties": [
                SFUDuty(
                    action_verb="Processes",
                    statement="Processes purchase orders and invoices for the dept",
                ),
                SFUDuty(
                    action_verb="Maintains",
                    statement="Maintains the departmental records and filing system",
                ),
            ]
        }
    )

    result = await rewrite_merged_role(
        _merged_with(draft), client=_FakeChat(reworded), rules=rules
    )

    assert result.anti_fabrication.removed_duties == ()


@pytest.mark.asyncio
async def test_the_rewrite_cannot_invent_an_education_experience_or_security_bar(
    rules: Rules,
) -> None:
    """S-3. ``_GROUNDED_KINDS`` policed knowledge/skill/ability only, so the three kinds
    that are STRUCTURAL BARS — derived by the 4.1 merge from member signals, not free
    text — passed through unexamined. Measured: the grounded qualification discarded
    and ``PhD in Astrophysics required`` / ``Ten years of nuclear reactor experience`` /
    ``Enhanced Reliability security clearance`` inserted on a clerical CUPE draft, with
    an EMPTY anti-fabrication record.

    On an HR system an invented hiring bar is the highest-consequence fabrication there
    is: it is the thing that screens candidates out.
    """
    draft = _cupe_draft_with_frequencies()
    reworded = draft.model_copy(
        update={
            "qualifications": [
                SFUQualification(text="PhD in Astrophysics required", kind="education"),
                SFUQualification(
                    text="Ten years of nuclear reactor experience", kind="experience"
                ),
                SFUQualification(
                    text="Enhanced Reliability security clearance", kind="security"
                ),
            ]
        }
    )

    result = await rewrite_merged_role(
        _merged_with(draft), client=_FakeChat(reworded), rules=rules
    )

    texts = [q.text for q in result.draft.qualifications]
    assert "PhD in Astrophysics required" not in texts
    assert "Ten years of nuclear reactor experience" not in texts
    assert "Enhanced Reliability security clearance" not in texts
    # The merge's own bars came back — restored, not merely dropped.
    assert "High school graduation" in texts
    assert "Two years of office experience" in texts
    # ...and it is EVIDENCE, not a silent swap.
    assert "PhD in Astrophysics required" in result.anti_fabrication.restored_bars


@pytest.mark.asyncio
async def test_the_rewrite_may_still_reword_the_kinds_it_authors(rules: Rules) -> None:
    """The control for S-3: knowledge / skill / ability are the model's to reword, and
    a guard that froze every qualification would make the pass pointless."""
    draft = _cupe_draft_with_frequencies()
    reworded = draft.model_copy(
        update={
            "qualifications": [
                SFUQualification(text="High school graduation", kind="education"),
                SFUQualification(
                    text="Two years of office experience", kind="experience"
                ),
                SFUQualification(
                    text="Working knowledge of accounting and budgeting",
                    kind="knowledge",
                ),
            ]
        }
    )

    result = await rewrite_merged_role(
        _merged_with(draft), client=_FakeChat(reworded), rules=rules
    )

    knowledge = [q.text for q in result.draft.qualifications if q.kind == "knowledge"]
    assert knowledge == ["Working knowledge of accounting and budgeting"]
    assert result.anti_fabrication.restored_bars == ()


@pytest.mark.asyncio
async def test_a_disabled_guard_leaves_all_three_of_these_alone(rules: Rules) -> None:
    """The mutation that proves the three above are the GUARD doing work and not the
    plumbing: with ``anti_fabrication_enabled: false`` the model's output ships
    unscrubbed, and every one of these protections is off — visibly, via
    ``enabled=False``, which is the shape the existing escape hatch already has."""
    draft = _cupe_draft_with_frequencies()
    reworded = draft.model_copy(
        update={
            "duties": [draft.duties[0].model_copy(update={"frequency": None})],
            "qualifications": [
                SFUQualification(text="PhD in Astrophysics required", kind="education")
            ],
        }
    )
    disabled = rules.model_copy(
        update={
            "rewrite": rules.rewrite.model_copy(
                update={"anti_fabrication_enabled": False}
            )
        }
    )

    result = await rewrite_merged_role(
        _merged_with(draft), client=_FakeChat(reworded), rules=disabled
    )

    assert result.anti_fabrication.enabled is False
    assert result.anti_fabrication.removed_duties == ()
    assert result.anti_fabrication.restored_bars == ()
    assert [q.text for q in result.draft.qualifications] == [
        "PhD in Astrophysics required"
    ]
    assert [d.frequency for d in result.draft.duties] == [None]


def _with_duty_floor_policy(rules: Rules, policy: str) -> Rules:
    """The same rulebook with `rewrite.duty_floor_policy` swapped — so the OTHER policy
    is exercised by a test rather than merely existing in the YAML."""
    return rules.model_copy(
        update={
            "rewrite": rules.rewrite.model_copy(update={"duty_floor_policy": policy})
        }
    )


@pytest.mark.asyncio
async def test_the_prompt_asks_for_the_duties_the_merge_actually_grounded(
    rules: Rules,
) -> None:
    """🔴 THE DEFECT, measured against the live Bank on 2026-08-19 over the five largest
    all-CUPE clusters: **60 merge duties became 36 rewritten ones.** The merge fills all
    twelve WJQ slots; the rewrite returned six to eight.

    Phase D fixed the prompt to state the DRAFT'S OWN FORM's numbers, so a CUPE rewrite
    is correctly asked for ``3–12`` rather than JDFN's ``3–5``. That removed the
    destructive case and left a quieter one: **the floor of 3 licenses the model to
    compress twelve grounded duties into seven, and nothing objects.** The WJQ profile's
    own ``duties_min`` is 3 (HR-203), so a seven-duty CUPE draft passes its own bar
    while dropping five duties the source documents stated; the anti-fabrication guard
    is looking the other way, because it exists to stop the model ADDING.

    The floor the rewrite should state is not the form's — it is **what this particular
    merge actually grounded**. A rewrite is a rewording pass: it is handed twelve duties
    and its job is to reword twelve, not to choose how many a role has. The form's
    ``duties_min`` remains exactly right for the VALIDATOR, which judges a finished JD
    from any source; it is the wrong number to hand a pass whose input is already known.

    ``rewrite.duty_floor_policy`` (HR-209, `open`). Asserted over both policies, because
    an assertion on ``grounded`` alone would also pass if the resolution ignored the
    policy and always used the grounded count.
    """
    # A CUPE merge holding SIX grounded duties — fewer than the form's max, more than
    # its min, so neither bound can produce the expected number by coincidence.
    six = _cupe_merged()
    duties = tuple(
        SFUDuty(action_verb="Process", statement=f"Process records batch {i}.")
        for i in range(6)
    )
    six = MergedRole(
        draft=six.draft.model_copy(update={"duties": duties}),
        provenance=six.provenance,
    )

    grounded_chat = _FakeChat(six.draft)
    await rewrite_merged_role(six, client=grounded_chat, rules=rules)
    assert "6–12 major duties" in grounded_chat.calls[0][0][0]

    # The other policy is today's behaviour, and it is still reachable.
    form_rules = _with_duty_floor_policy(rules, "form_minimum")
    form_chat = _FakeChat(six.draft)
    await rewrite_merged_role(six, client=form_chat, rules=form_rules)
    wjq = rules.thresholds_for("wjq")
    assert f"{wjq.duties_min}–{wjq.duties_max} major duties" in form_chat.calls[0][0][0]
    # ...and the two genuinely differ, so neither assertion passes by coincidence.
    assert wjq.duties_min != len(duties)


@pytest.mark.asyncio
async def test_the_grounded_floor_never_asks_for_more_than_the_form_allows(
    rules: Rules,
) -> None:
    """The floor is a floor, not a target, and it must not become a ceiling-breaker: a
    merge that grounded more duties than the form has slots would otherwise ask the
    model for more duties than the form can hold, turning a content-preserving rule into
    an invitation to overflow it.

    It must also not round a SPARSE merge up to the form's minimum. A cluster that
    grounded two duties is a cluster with two duties; asking for three is asking the
    model to invent one, which is the exact failure the anti-fabrication guard exists to
    catch and the exact failure a floor should not manufacture. The validator will flag
    the under-run honestly (`SFU-STRUCT-DUTIES-TOO-FEW`), which is the right place for
    it to be noticed.
    """
    wjq = rules.thresholds_for("wjq")

    sparse = _cupe_merged()
    sparse = MergedRole(
        draft=sparse.draft.model_copy(
            update={"duties": (SFUDuty(action_verb="File", statement="File records."),)}
        ),
        provenance=sparse.provenance,
    )
    chat = _FakeChat(sparse.draft)
    await rewrite_merged_role(sparse, client=chat, rules=rules)
    system = chat.calls[0][0][0]
    assert f"1–{wjq.duties_max} major duties" in system
    assert f"{wjq.duties_min}–" not in system

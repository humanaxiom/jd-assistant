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

from src.jd_bank.rewrite.harmonize import _flatten_jd, rewrite_merged_role
from src.jd_core.models.bank import MergedRole, MergeProvenance, RewrittenDraft
from src.jd_core.models.parsed_jd import (
    SFUDuty,
    SFUJobDescription,
    SFUQualification,
    SFURelationships,
)
from src.jd_core.quality.scoring import score_issues
from src.jd_core.quality.validators import evaluate_jd_rules
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
    so the guard must not touch it — else it would drop content the sources stated."""
    grounded = MergedRole(
        draft=_draft().model_copy(update={"problem_solving": ["Original wording"]}),
        provenance=_merged().provenance,
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

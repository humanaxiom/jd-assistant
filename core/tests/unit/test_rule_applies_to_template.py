"""Unit — a rule declares which document TEMPLATE it can judge (CUPE Phase B).

**The defect this closes.** `evaluate_jd_rules` ran every catalogued rule over every JD,
and the archive holds **two** templates: the JDFN form (APSA/APEX/POLY) and the CUPE
3338 **WJQ**, a 14-section point-factor questionnaire. Measured live, four rules fired
on **100%** of CUPE documents — not because those JDs are poor, but because the WJQ
form does not contain the sections they check (**0.0%** have a Problem Solving section;
**3.1%** an Impact of Decision Making one).

⚠ **"Fires on 100%" is the motivating case, NOT the test for withholding a rule** — see
`_JDFN_ONLY_BY_MEASUREMENT`, where the per-rule rates run from 100.0% down to **0.0%**.
The question `applies_to` answers is whether the form carries what the rule reads. A
rule the WJQ gives nothing to read is withheld whether or not it was ever noisy, and a
rule the WJQ *does* feed is kept even if CUPE fails it often — that would be a finding
about the job descriptions, which is the thing being measured.

This rulebook already names that failure: `evaluable: false` exists because *a rule that
cannot NOT fire is a constant subtracted from every score, not a quality signal* — the
finding it emits is **unfalsifiable**. `applies_to` is the same principle applied per
template rather than per rule.

**Required, with NO default** — the P1.3 `tier` move. A rule cannot be filed against
a template by omission, which is how one undifferentiated ruleset came to be applied
to two forms.

⚠ **This is a statement of FACT about the form, not a policy.** Whether SFU's
boilerplate requirements should apply to a CUPE JD is a real policy question, registered
separately (HR-201) rather than settled here by a `applies_to` value.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.jd_core.models.parsed_jd import SFUJobDescription
from src.jd_core.models.quality import JDTemplate
from src.jd_core.quality.validators import evaluate_jd_rules, template_of
from src.jd_core.rules import get_rules

#: Withheld from the WJQ because that FORM does not carry what the rule reads.
#:
#: ⚠ THE RATES ARE PER-RULE AND ARE **NOT** ALL 100% — an earlier version of this file
#: said they were, and the archive does not agree. The four rules that genuinely fire on
#: 100% of CUPE are `SFU-COMP-TERRITORIAL` · `SFU-GATE-REL-HEADER` · `SFU-COMP-EDI` ·
#: `SFU-COMP-PROBLEM` — and two of those are the boilerplate rules that sit under HR-201
#: instead, so that set and this one are NOT the same four.
#:
#: Rates below are measured over **all 4,440 CUPE documents at `jd_segmenter_v4`**, not
#: over the 600-document sample in `docs/decisions/cupe-scope-measured-2026-08-14.md`
#: (which is `jd_segmenter_v3`). They differ in the first decimal — the sample put
#: `SFU-COMP-DECISION` at 96.0% against the corpus's 96.9% — which is the standing
#: baseline rule again: a sample estimates the middle well and the edges poorly.
#:
#: The justification for withholding is the FORM, and it does not require a high firing
#: rate: `SFU-GATE-DUTY-PCT` fires on **0.0%** of CUPE and is still correctly JDFN-only,
#: because the WJQ asks for (D)/(W)/(M)/(S) frequency markers rather than `(NN%)`
#: allocations — the rule has nothing to read. Keeping it here is a statement that the
#: form cannot be judged by it, not a claim that it was noisy.
_JDFN_ONLY_BY_MEASUREMENT = (
    # fires on 100.0% of CUPE — 0.0% of them have a Problem Solving section
    "SFU-COMP-PROBLEM",
    # fires on 100.0% — the JDFN Relationships header; the WJQ names it differently
    "SFU-GATE-REL-HEADER",
    # fires on 96.9%, NOT 100% — 3.1% do have an Impact of Decision Making section
    "SFU-COMP-DECISION",
    # fires on 0.0% — measured 2026-08-14 over all 4,440 CUPE docs at
    # `jd_segmenter_v4`: exactly 1 carries the >=2 `(NN%)` allocations the rule needs
    # before it can evaluate, and 0 would trip it. A form fact with no live effect.
    "SFU-GATE-DUTY-PCT",
)


#: 🔴 THE COMPLETE JDFN-ONLY SET. Every one of these is withheld from CUPE because the
#: WJQ form does not contain the section it reads — the four measured above, plus the
#: three boilerplate rules whose scope is a POLICY call registered as HR-201. Asserted
#: as an exact set so that narrowing a rule to one template can never be a quiet edit:
#: it turns this red and has to be argued in the diff.
_JDFN_ONLY = frozenset(
    _JDFN_ONLY_BY_MEASUREMENT
    + (
        "SFU-COMP-ABOUT",  # HR-201 — SFU-wide boilerplate, absent from the WJQ form
        "SFU-COMP-TERRITORIAL",  # HR-201
        "SFU-COMP-EDI",  # HR-201
    )
)


def _jd(**update: object) -> SFUJobDescription:
    return SFUJobDescription(title="Records Clerk", **update)  # type: ignore[arg-type]


#: Text carrying duty time-allocations that do NOT total 100 — what
#: ``SFU-GATE-DUTY-PCT`` reads. Held identical across both cohorts below so the ONLY
#: difference between the two runs is the template.
_TEXT = "Duties: processes records (30%), maintains files (40%), reports (20%)."


def test_every_rule_declares_the_templates_it_can_judge() -> None:
    """🔴 THE COMPLETENESS PIN. A rule with no `applies_to` cannot exist — the loader
    rejects it — so a new rule must state which form it judges."""
    catalog = get_rules().rule_catalog

    for spec in catalog.rules:
        assert spec.applies_to, f"{spec.rule_id} declares no template"
        for template in spec.applies_to:
            assert template in ("jdfn", "wjq"), f"{spec.rule_id}: {template!r}"


def test_applies_to_has_no_default() -> None:
    """Filed by omission is how the single undifferentiated ruleset happened. A rule
    without the field must fail to load, not quietly inherit one."""
    from src.jd_core.rules.loader import RuleSpec

    assert RuleSpec.model_fields["applies_to"].is_required()


def test_a_rule_cannot_declare_an_unknown_template() -> None:
    from src.jd_core.rules.loader import RuleSpec

    with pytest.raises(ValidationError):
        RuleSpec(
            rule_id="SFU-TEST",
            category="completeness",
            section="general",
            source_part="Part 1",
            default_severity="low",
            title="t",
            applies_to=("jdfn", "sharepoint"),  # type: ignore[arg-type]
            messages={"default": "m"},
            recommendations={"default": "r"},
        )


def test_the_measured_jdfn_only_rules_are_declared_jdfn_only() -> None:
    """Pins the four whose scope is a fact about the form. Add `wjq` to any of them and
    this goes red — which is the point: three would resume marking CUPE down for
    sections the WJQ never asks for (at 100.0%, 100.0% and 96.9%), and the fourth would
    be reading an allocation format the form does not use."""
    catalog = get_rules().rule_catalog

    for rule_id in _JDFN_ONLY_BY_MEASUREMENT:
        assert catalog.by_id[rule_id].applies_to == ("jdfn",), rule_id


def test_the_jdfn_only_set_is_exactly_the_seven_that_earned_it() -> None:
    """🔴 THE COMPLETENESS PIN, the other direction. `test_every_rule_declares_...`
    stops a rule having NO template; this stops one quietly losing a template.

    Enumerated from the live catalogue, not a hand-kept list. Withholding a rule from
    CUPE removes a finding from 4,440 documents, so it must be a visible edit here —
    every member is either measured (fires on 100% of CUPE) or registered (HR-201).
    """
    catalog = get_rules().rule_catalog
    jdfn_only = {s.rule_id for s in catalog.rules if s.applies_to == ("jdfn",)}

    assert jdfn_only == set(_JDFN_ONLY)


def test_no_rule_is_wjq_only() -> None:
    """Nothing has yet been written that only the WJQ form can be judged by — Phase C
    is where that changes. Stated so the day it does is a deliberate edit."""
    catalog = get_rules().rule_catalog

    assert not [s.rule_id for s in catalog.rules if s.applies_to == ("wjq",)]


def test_the_restricted_title_rules_judge_both_templates() -> None:
    """⚠ THE ONE PHASE B FIRST GOT WRONG, kept as a test because the argument is subtle.

    `SFU-AUTH-TITLE-EXEC-DIR` was briefly declared JDFN-only alongside its siblings'
    `[jdfn, wjq]`. It does not belong there. `applies_to` states a fact about the FORM,
    and the WJQ **has** a job title; scoping this rule by template would also be a
    SECOND employee-group filter on a rule that already carries its own
    (`reserved_for_employee_group: apex`), disabling the one restricted-title check
    that can fire on precisely the group it would catch.

    MEASURED over the live archive at `jd_segmenter_v4`: 5 CUPE documents carry
    "executive director" in the title, and JDFN-only would have suppressed all five.
    Three are a substring near-miss ("Assistant/Secretary **to the** Executive
    Director") — a matcher defect recorded under **HR-031**, not a template one, and
    not to be papered over with a template scope.
    """
    catalog = get_rules().rule_catalog

    for rule_id in (
        "SFU-AUTH-TITLE-EXEC-DIR",
        "SFU-AUTH-TITLE-REGISTRAR",
        "SFU-AUTH-TITLE-HR",
    ):
        assert catalog.by_id[rule_id].applies_to == ("jdfn", "wjq"), rule_id


def test_a_cupe_jd_is_resolved_as_wjq_and_a_jdfn_one_is_not() -> None:
    """`employee_group == "cupe"` is the JDFN/WJQ separator the model designates —
    `ParseResult.template` is not persisted, and the WJQ segmenter sets the group
    unconditionally, so this has complete WJQ recall."""
    assert template_of(_jd(employee_group="cupe")) == "wjq"
    assert template_of(_jd(employee_group="apsa")) == "jdfn"
    assert template_of(_jd()) == "jdfn"  # unknown group -> the default template


def test_jdfn_only_rules_do_not_fire_on_a_cupe_jd() -> None:
    """🔴 THE BEHAVIOUR. The whole point: a CUPE JD is no longer penalised for lacking
    sections its own official form never asks for."""
    rules = get_rules()
    cupe = _jd(employee_group="cupe")

    fired = {issue.rule_id for issue in evaluate_jd_rules(cupe, _TEXT, rules=rules)}

    for rule_id in _JDFN_ONLY_BY_MEASUREMENT:
        assert rule_id not in fired, f"{rule_id} still fires on a CUPE JD"


def test_the_same_rules_still_fire_on_a_jdfn_jd() -> None:
    """The other half of the proof. A filter that silenced a rule everywhere would pass
    the test above and be a much worse bug than the one it fixed."""
    rules = get_rules()
    jdfn = _jd(employee_group="apsa")

    fired = {issue.rule_id for issue in evaluate_jd_rules(jdfn, _TEXT, rules=rules)}

    for rule_id in _JDFN_ONLY_BY_MEASUREMENT:
        assert rule_id in fired, f"{rule_id} stopped firing on a JDFN JD"


def test_a_restricted_title_is_still_caught_on_a_cupe_jd() -> None:
    """🔴 THE BEHAVIOUR behind the declaration above — a real title from the archive.

    "Executive Director of Development" is one of the 2 genuine CUPE hits measured at
    `jd_segmenter_v4`. Declaring the rule JDFN-only silences it, and a CUPE JD titled
    Executive Director is exactly what the rule exists to surface — most likely a
    mis-parsed `employee_group`, which is a finding either way.
    """
    rules = get_rules()
    cupe = SFUJobDescription(
        title="Executive Director of Development", employee_group="cupe"
    )

    fired = {issue.rule_id for issue in evaluate_jd_rules(cupe, "", rules=rules)}

    assert "SFU-AUTH-TITLE-EXEC-DIR" in fired


def test_a_finding_with_no_rule_id_survives_the_filter() -> None:
    """LLM findings carry no `rule_id`, so there is no catalogue entry to consult. They
    must pass through rather than be dropped as "not applicable to this template"."""
    from src.jd_core.quality.validators import applies_to_template

    assert applies_to_template(None, "wjq", get_rules().rule_catalog) is True


@pytest.mark.parametrize("template", ["jdfn", "wjq"])
def test_at_least_one_rule_judges_each_template(template: JDTemplate) -> None:
    """A template with no rules at all would score every document perfectly — the
    failure mode opposite to the one this change fixes."""
    catalog = get_rules().rule_catalog
    applicable = [s for s in catalog.rules if template in s.applies_to]

    assert len(applicable) >= 5, f"only {len(applicable)} rules judge {template}"

"""Unit — a rule declares which document TEMPLATE it can judge (CUPE Phase B).

**The defect this closes.** `evaluate_jd_rules` ran every catalogued rule over every JD,
and the archive holds **two** templates: the JDFN form (APSA/APEX/POLY) and the CUPE
3338 **WJQ**, a 14-section point-factor questionnaire. Measured live, four rules fired
on **100%** of CUPE documents — not because those JDs are poor, but because the WJQ
form does not contain the sections they check (**0.0%** have a Problem Solving section;
**3.1%** an Impact of Decision Making one).

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

#: Fires on 100% of CUPE documents because the WJQ form lacks the section it checks.
_JDFN_ONLY_BY_MEASUREMENT = (
    "SFU-COMP-PROBLEM",  # 0.0% of CUPE JDs have a Problem Solving section
    "SFU-COMP-DECISION",  # 3.1% have an Impact of Decision Making section
    "SFU-GATE-REL-HEADER",  # the JDFN Relationships header; WJQ names it differently
    "SFU-GATE-DUTY-PCT",  # duty time-allocations; WJQ uses (D)/(W)/(M)/(S) instead
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
    """Pins the four the archive proved. Add `wjq` to any of them and this goes red —
    which is the point: they would then fire on 100% of CUPE JDs again."""
    catalog = get_rules().rule_catalog

    for rule_id in _JDFN_ONLY_BY_MEASUREMENT:
        assert catalog.by_id[rule_id].applies_to == ("jdfn",), rule_id


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

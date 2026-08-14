"""Unit — the numeric thresholds are per-template too (CUPE Phase C).

**The move, and it is deliberately the same one twice.** Phase B made *which rules
apply* per-template data (`applies_to`). This makes *the numbers those rules measure
against* per-template data as well, adding **no new concepts**: the same `template_of`,
the same "required, no default" discipline, the same registration.

**Why `duties_max` is the case that forces it.** `SFU-STRUCT-DUTIES-TOO-MANY` fires on
**82.3%** of WJQ documents against a `duties_max: 5` calibrated on the JDFN form. The
WJQ has **twelve** duty slots and 77.4% of CUPE JDs use exactly twelve — a property of
the FORM, not a writing defect. `SFUJobDescription.duties` is itself capped at 12,
which is the same fact recorded a third time.

⚠ **The message must quote the bar it actually applied.** `_base_context` feeds
`{duties_max}` into the finding's copy, so a WJQ finding rendered from the JDFN default
would tell a reviewer "the template allows a maximum of 5" while the rule fired at 12.
A finding that misquotes its own threshold is worse than no finding — pinned below.

Every WJQ value is registered `open`; HR swaps a YAML value, not code.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from src.jd_core.models.parsed_jd import SFUDuty, SFUJobDescription
from src.jd_core.models.quality import JDTemplate
from src.jd_core.quality.validators import evaluate_jd_rules
from src.jd_core.rules import get_rules
from src.jd_core.rules.loader import Thresholds

#: The WJQ's duty-slot count, measured: 77.4% of 4,440 CUPE JDs carry exactly this many.
_WJQ_DUTY_SLOTS = 12


def _duties(n: int) -> list[SFUDuty]:
    return [
        SFUDuty(action_verb="Reviews", statement=f"record type {i}") for i in range(n)
    ]


def _jd(template: JDTemplate, n_duties: int) -> SFUJobDescription:
    group = "cupe" if template == "wjq" else "apsa"
    return SFUJobDescription(
        title="Records Clerk", employee_group=group, duties=_duties(n_duties)
    )


def test_the_wjq_profile_is_required_with_no_default() -> None:
    """The `applies_to` / `tier` move again: a template's numbers cannot be filed by
    omission, because that is precisely how one form's calibration came to be applied
    to two forms."""
    assert Thresholds.model_fields["wjq"].is_required()


def test_the_shared_defaults_are_unchanged_so_jdfn_cannot_move_silently() -> None:
    """The top-level values ARE the JDFN profile, and the register entries HR already
    holds point at those paths (`thresholds.duties_max`). Introducing the WJQ block
    must not renumber or reword them."""
    t = get_rules().thresholds

    assert (t.duties_min, t.duties_max) == (3, 5)
    assert (t.summary_min_words, t.summary_max_words) == (100, 150)


def test_the_wjq_profile_allows_the_forms_twelve_duty_slots() -> None:
    t = get_rules().thresholds.wjq

    assert t.duties_max == _WJQ_DUTY_SLOTS


@pytest.mark.parametrize("template", ["jdfn", "wjq"])
def test_resolution_returns_the_profile_for_the_template(template: JDTemplate) -> None:
    rules = get_rules()

    resolved = rules.thresholds_for(template)
    expected = rules.thresholds.wjq.duties_max if template == "wjq" else 5

    assert resolved.duties_max == expected


def test_a_wjq_jd_using_all_twelve_slots_is_not_marked_down() -> None:
    """🔴 THE BEHAVIOUR. A CUPE JD that fills the form it was given is not defective."""
    rules = get_rules()

    fired = {
        i.rule_id
        for i in evaluate_jd_rules(_jd("wjq", _WJQ_DUTY_SLOTS), "", rules=rules)
    }

    assert "SFU-STRUCT-DUTIES-TOO-MANY" not in fired


def test_a_jdfn_jd_with_twelve_duties_still_is() -> None:
    """The control, and the half that matters — a change that relaxed the bar for
    everyone would pass the test above and be a far worse defect than the one it fixes.
    SFU's own never-approve list names the over-run for the JDFN form."""
    rules = get_rules()

    fired = {
        i.rule_id
        for i in evaluate_jd_rules(_jd("jdfn", _WJQ_DUTY_SLOTS), "", rules=rules)
    }

    assert "SFU-STRUCT-DUTIES-TOO-MANY" in fired


def _rules_with_wjq_summary_cap(cap: int) -> Any:
    """The shipped rules, with ONE WJQ value moved away from its JDFN twin.

    Needed because the shipped profiles agree on `summary_max_words` (150 both), and a
    test that asserts "the message quotes the resolved bar" against two identical
    numbers proves nothing whichever way the code behaves. Pinning the mechanism
    requires values that actually differ, so this makes them differ.
    """
    base = get_rules()
    data = base.thresholds.model_dump()
    data["wjq"] = {**data["wjq"], "summary_max_words": cap}
    return base.model_copy(update={"thresholds": Thresholds(**data)})


def test_the_finding_quotes_the_threshold_it_applied_not_the_shared_default() -> None:
    """⚠ THE HONESTY PIN, and the reason the profile is resolved into `rules` rather
    than only at the comparison.

    `_base_context` interpolates the thresholds into the COPY a reviewer reads. Resolve
    the trigger without resolving the message and a WJQ finding announces the JDFN bar
    — "the template allows a maximum of 150" about a bar of 400. **A finding that
    misquotes its own threshold is worse than one that never fired**, because it sends
    the author to change the wrong thing.

    ⚠ AN EARLIER VERSION OF THIS TEST WAS VACUOUS: it asserted against the shipped
    `summary_max_words`, which is 150 in BOTH profiles, so it passed no matter what the
    code did. Same trap as `test_a_decision_with_an_unknown_tier_fails_to_load` (P1.3).
    """
    rules = _rules_with_wjq_summary_cap(400)
    long_summary = "word " * 500

    def message_for(group: str) -> str:
        jd = SFUJobDescription(
            title="Records Clerk", employee_group=group, position_summary=long_summary
        )
        hits = [
            i
            for i in evaluate_jd_rules(jd, "", rules=rules)
            if i.rule_id == "SFU-STRUCT-SUMMARY-TOO-LONG"
        ]
        assert hits, f"the over-long summary rule did not fire for {group}"
        return hits[0].message

    assert "400" in message_for("cupe"), message_for("cupe")
    assert "150" in message_for("apsa"), message_for("apsa")


def test_a_wjq_only_threshold_change_leaves_the_jdfn_bar_alone() -> None:
    """The control for the mechanism above: moving a WJQ number must not move JDFN's.
    A resolution that mutated the shared block instead of overlaying a copy would pass
    the honesty pin and quietly re-bar every APSA document."""
    rules = _rules_with_wjq_summary_cap(400)

    assert rules.thresholds.summary_max_words == 150
    assert rules.thresholds_for("jdfn").summary_max_words == 150
    assert rules.thresholds_for("wjq").summary_max_words == 400


def test_a_wjq_profile_with_an_inverted_range_fails_to_load() -> None:
    """The shared block already refuses `min > max`; the per-template one must too, or
    the invariant holds in one profile and not the other."""
    from src.jd_core.rules.loader import TemplateThresholds

    with pytest.raises(ValidationError):
        TemplateThresholds(
            duties_min=9, duties_max=2, summary_min_words=100, summary_max_words=150
        )


def test_every_wjq_threshold_is_on_the_decision_surface() -> None:
    """🔴 THE GOVERNANCE PIN, and it is what makes this configuration-driven rather than
    a second hardcoding. Each WJQ value must be a registered parameter HR can change —
    enumerated from the live rules, so a knob added here tomorrow breaks the build until
    someone says whether HR must ratify it."""
    from src.jd_core.rules.loader import decision_surface

    surface = decision_surface(get_rules())

    for field in ("duties_min", "duties_max", "summary_min_words", "summary_max_words"):
        assert f"thresholds.wjq.{field}" in surface, field

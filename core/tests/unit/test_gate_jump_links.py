"""Unit — the Phase-8.3c gate → field jump-links.

A blocking gate tells a reviewer *what* is wrong; 8.3c tells them *where to fix it*.
The mapping is **rulebook-driven**: a gate carries the ``rule_ids`` that tripped it, the
rule catalog owns each rule's ``section``, and the catalog's own ``section_order`` and
``section_labels`` supply the order and the words. Nothing here re-states rulebook data.

The two properties that make it more than a convenience link:

1. **The anchor map is COMPLETE, derived from the ``SFUSection`` literal itself.** A new
   template section added to the model without an anchor would render a link that jumps
   nowhere — a silently dead control, which this repo has shipped before. The test walks
   ``get_args(SFUSection)``, not a hand-written list.
2. **A gate with nothing to point at offers NO link.** "Your score is too low" does not
   point at a field, and a "fix this ↓" link landing on an arbitrary section would be a
   lie. Measured over the whole archive, that is exactly ``SFU-APPROVE-SCORE-FLOOR`` and
   ``SFU-APPROVE-GRADE-FLOOR`` — 15 occurrences each, **zero** carrying ``rule_ids``,
   while 505 of 535 blocking-gate occurrences do carry them. ``SEVERITY-FLOOR`` reads
   like a roll-up but names its rules (12/12 live), so it *does* get links unless it was
   tripped by a rule-less LLM finding.
"""

from __future__ import annotations

from typing import get_args

import pytest

import src.api.main  # noqa: F401 — see below; must be imported before routes.ui
from src.api.routes.ui import _SECTION_ANCHORS, gate_jump_targets
from src.jd_core.models.quality import GateReason, SFUSection
from src.jd_core.rules import get_rules

# ⚠ THE IMPORT ABOVE IS LOAD-BEARING, and it is a live defect not a style choice.
# ``routes/ui.py`` imports ``get_session`` from ``src.api.main``, which imports
# ``routes.ui`` to mount the router — so importing ``routes.ui`` FIRST raises
# ``ImportError: cannot import name 'router' from partially initialized module``.
# Every other suite hides it by importing ``src.api.main`` first. Moving ``get_session``
# to ``api/deps.py`` is the open chore that fixes it (ROADMAP), and this line documents
# why it is worth doing rather than papering over it silently.


def _gate(gate_id: str, rule_ids: tuple[str, ...]) -> GateReason:
    return GateReason(
        gate_id=gate_id,
        source_part="Part 2",
        reason="something is wrong",
        rule_ids=rule_ids,
        overridable=False,
    )


def test_every_sfu_section_has_an_anchor_or_is_declared_to_have_none() -> None:
    """🔴 THE COMPLETENESS PIN, walked from the live literal. Add a section to
    ``SFUSection`` without deciding where it lives on the page and this fails — rather
    than shipping a link that jumps nowhere."""
    assert set(_SECTION_ANCHORS) == set(get_args(SFUSection))


def test_the_whole_document_section_deliberately_has_no_anchor() -> None:
    """``general`` is declared as ``None``, not omitted. An omission would be
    indistinguishable from a section someone forgot — the same reason P1.3 gave ``tier``
    no default."""
    assert _SECTION_ANCHORS["general"] is None


def test_a_gate_links_to_the_section_its_tripped_rules_belong_to() -> None:
    rules = get_rules()
    # SFU-COMP-SUMMARY is catalogued against the position summary.
    targets = gate_jump_targets(_gate("SFU-APPROVE-X", ("SFU-COMP-SUMMARY",)), rules)

    assert [t.anchor for t in targets] == ["edit-position_summary"]
    assert [t.label for t in targets] == [rules.rule_catalog.label("position_summary")]


def test_a_gate_spanning_several_sections_offers_one_link_each() -> None:
    """``SFU-APPROVE-MANDATORY-SECTIONS`` trips on summary, duties and quals. A reviewer
    should be sent to each, not to whichever one happened to sort first."""
    rules = get_rules()
    gate = _gate(
        "SFU-APPROVE-MANDATORY-SECTIONS",
        ("SFU-COMP-SUMMARY", "SFU-COMP-DUTIES", "SFU-COMP-QUALS"),
    )

    anchors = [t.anchor for t in gate_jump_targets(gate, rules)]

    assert anchors == ["edit-position_summary", "edit-duties", "edit-qualifications"]


def test_the_links_follow_the_rulebooks_own_section_order() -> None:
    """Ordered by ``section_order`` from the catalog — NOT by the order the rules
    happened to trip, which would reshuffle the same gate's links between drafts."""
    rules = get_rules()
    scrambled = _gate(
        "SFU-APPROVE-MANDATORY-SECTIONS",
        ("SFU-COMP-QUALS", "SFU-COMP-SUMMARY", "SFU-COMP-DUTIES"),
    )
    ordered = _gate(
        "SFU-APPROVE-MANDATORY-SECTIONS",
        ("SFU-COMP-SUMMARY", "SFU-COMP-DUTIES", "SFU-COMP-QUALS"),
    )

    assert gate_jump_targets(scrambled, rules) == gate_jump_targets(ordered, rules)


def test_a_gate_with_no_rules_offers_no_link() -> None:
    """The score and grade floors are roll-ups over the whole document — measured, they
    are the only two blocking gates in the archive that never carry ``rule_ids``. A
    "fix this ↓" link landing on an arbitrary field would be a lie about what is
    wrong."""
    rules = get_rules()
    assert gate_jump_targets(_gate("SFU-APPROVE-SCORE-FLOOR", ()), rules) == ()


def test_a_duplicate_section_is_listed_once() -> None:
    """Two tripped rules in the same section are one place to go, not two identical
    links."""
    rules = get_rules()
    gate = _gate("SFU-APPROVE-X", ("SFU-COMP-SUMMARY", "SFU-COMP-SUMMARY"))

    assert len(gate_jump_targets(gate, rules)) == 1


def test_an_uncatalogued_rule_id_is_skipped_not_raised() -> None:
    """A gate citing a rule the catalog does not know must not take down the review
    page — the page's job is the approve/reject decision. It simply offers no link for
    that rule."""
    rules = get_rules()
    gate = _gate("SFU-APPROVE-X", ("SFU-NOT-A-REAL-RULE", "SFU-COMP-DUTIES"))

    assert [t.anchor for t in gate_jump_targets(gate, rules)] == ["edit-duties"]


@pytest.mark.parametrize("section", [s for s in get_args(SFUSection) if s != "general"])
def test_every_anchored_section_is_reachable_from_the_rulebook_labels(
    section: str,
) -> None:
    """Each anchor pairs with a human label the rulebook already owns, so the link text
    and the checklist cannot drift apart."""
    rules = get_rules()
    assert rules.rule_catalog.label(section)  # type: ignore[arg-type]
    assert _SECTION_ANCHORS[section]  # type: ignore[index]

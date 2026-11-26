"""Parser v10 — the supervisory text is no longer cut (owner ruling 2026-10-29).

The 600-character supervisory cap was the code constant ``_MAX_SUPERVISORY``,
unregistered. MEASURED by the parser-v10 review over all 14,522 extracted archive
files (docs/audit/2026-10-29-parser-v10-review.md §4): 5,772 documents (58.8%) were
over it, 2.48 M characters cut; prompt-stripped p50 552 · p90 1,016 · p99 2,711. The
owner ruled "remove the cap". It is now rulebook data — ``segmentation.supervisory_
max_chars`` (HR-324), ``null`` = no cap — so a later HR ruling is a YAML edit, and the
parser, the rewrite's fidelity table, the model and the Builder contract all follow it.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

import src.jd_core.rules as rules_pkg
from src.jd_bank.composer.answers import ComposerAnswers
from src.jd_bank.rewrite.fidelity import field_cap
from src.jd_core.models.parsed_jd import SFURelationships
from src.jd_core.parser import parse_jd, segmenter
from src.jd_core.rules import Rules, Segmentation, get_rules, loader
from src.jd_core.rules.loader import SEGMENTATION_FILE

_HEAD = (
    "SIMON FRASER UNIVERSITY\n"
    "POSITION DESCRIPTION\n"
    "A. IDENTIFICATION\n"
    "Position Title: Executive Director\n"
    "B. POSITION SUMMARY\n"
    "Leads the unit.\n"
    "C. DUTIES AND RESPONSIBILITIES\n"
    "      •    Directs the unit's programs.\n"
)

#: 20090901_00006571_Executive_Director_LSG.docx lost 25 words at 600; this is longer
#: than every percentile the review measured except the p99 tail.
_LONG_SUPERVISORY = " ".join(
    f"Supervises the {role} and sets their annual objectives, reviews their work plans "
    "and approves their professional development."
    for role in (
        "Associate Director",
        "Program Managers",
        "Finance Officer",
        "Communications Coordinator",
        "Administrative Assistants",
        "Research Analysts",
        "Student Advisors",
        "Technical Lead",
        "Events Coordinator",
        "Data Steward",
    )
)
assert len(_LONG_SUPERVISORY) > 1200

_TEXT = _HEAD + "E. SUPERVISION EXERCISED\n" + _LONG_SUPERVISORY + "\n"


def _retuned_segmentation(rules: Rules, **fields: object) -> Rules:
    rules_dir = Path(loader.__file__).resolve().parent
    raw = yaml.safe_load((rules_dir / SEGMENTATION_FILE).read_text(encoding="utf-8"))
    seg = Segmentation.model_validate({**raw, **fields})
    return rules.model_copy(update={"segmentation": seg})


def test_the_shipped_rulebook_has_no_supervisory_cap() -> None:
    assert get_rules().segmentation.supervisory_max_chars is None


def test_a_long_supervisory_text_parses_whole() -> None:
    jd = parse_jd(_TEXT).jd
    assert jd.relationships is not None
    assert jd.relationships.supervisory == _LONG_SUPERVISORY


def test_the_cap_is_rulebook_data(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set the knob and the parser cuts there — proving it READS the YAML rather than
    keeping a constant in Python (the defect this replaces)."""
    capped = _retuned_segmentation(get_rules(), supervisory_max_chars=100)
    monkeypatch.setattr(rules_pkg, "get_rules", lambda: capped)
    jd = parse_jd(_TEXT).jd
    assert jd.relationships is not None
    assert jd.relationships.supervisory == _LONG_SUPERVISORY[:100]


def test_the_rewrite_fidelity_table_follows_the_knob() -> None:
    rules = get_rules()
    assert field_cap("supervisory", rules) == 0  # "a field the parser does not cut"
    capped = _retuned_segmentation(rules, supervisory_max_chars=100)
    assert field_cap("supervisory", capped) == 100


def test_the_model_and_the_builder_contract_hold_the_whole_text() -> None:
    assert (
        SFURelationships(supervisory=_LONG_SUPERVISORY).supervisory == _LONG_SUPERVISORY
    )
    answers = ComposerAnswers(title="Executive Director", supervisory=_LONG_SUPERVISORY)
    assert answers.supervisory == _LONG_SUPERVISORY


def test_no_supervisory_constant_survives_in_the_parser() -> None:
    assert not hasattr(segmenter, "_MAX_SUPERVISORY")

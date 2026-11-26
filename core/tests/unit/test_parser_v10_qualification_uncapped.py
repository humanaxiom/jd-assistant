"""Parser v10 — one qualification is no longer cut (owner ruling 2026-10-29).

The 400-character qualification cap was the code constant ``_MAX_QUAL``, then
``segmentation.qualification_max_chars: 400`` (HR-308) held at the ``SFUQualification
.text`` contract, with an over-cap item SPLIT at its sentence breaks. MEASURED by the
parser-v10 review over all 14,522 extracted archive files (docs/audit/2026-10-29-
parser-v10-review.md §4): 1,112 items still cut at 400 — 308 of them the "or an
equivalent combination of education and experience" clause. The owner ruled "remove
the 400 cap". The knob now ships ``null`` = no cap and no split: an unbulleted
paragraph is ONE item, whole. A number there restores the split-then-cut reading, and
the model, the Builder contracts, the rewrite's fidelity table and the WJQ reader all
follow it.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

import src.jd_core.rules as rules_pkg
from src.jd_bank.composer.answers import ModifiedQual
from src.jd_bank.composer.wjq_answers import SkillAnswer
from src.jd_bank.rewrite.fidelity import field_cap
from src.jd_core.models.parsed_jd import SFUQualification
from src.jd_core.parser import parse_jd, segmenter
from src.jd_core.rules import Rules, Segmentation, get_rules, loader
from src.jd_core.rules.loader import SEGMENTATION_FILE

_HEAD = (
    "SIMON FRASER UNIVERSITY\n"
    "POSITION DESCRIPTION\n"
    "A. IDENTIFICATION\n"
    "Position Title: IT Coordinator\n"
    "B. POSITION SUMMARY\n"
    "Coordinates the unit's systems.\n"
    "C. DUTIES AND RESPONSIBILITIES\n"
    "      •    Maintains the unit's systems.\n"
)

#: One sentence, far over 400: the "equivalent combination" clause the review found
#: cut 308 times, padded the way the old form's unbulleted requirements are.
_LONG_QUAL = (
    "Bachelor's degree in computer science, information systems or a related field "
    "and five years of progressively responsible experience administering networked "
    "desktop systems, servers and storage in a large and decentralised organisation, "
    "including experience leading technical staff, managing vendor relationships, "
    "planning and delivering infrastructure projects on time and on budget, and "
    "documenting operational procedures for a diverse user community, or an equivalent "
    "combination of education, training and experience"
)
assert len(_LONG_QUAL) > 400 and "." not in _LONG_QUAL

_TEXT = _HEAD + "H. ENTRANCE QUALIFICATIONS\n" + _LONG_QUAL + "\n"


def _quals(text: str) -> list[str]:
    return [q.text for q in parse_jd(text).jd.qualifications]


def _retuned_segmentation(rules: Rules, **fields: object) -> Rules:
    rules_dir = Path(loader.__file__).resolve().parent
    raw = yaml.safe_load((rules_dir / SEGMENTATION_FILE).read_text(encoding="utf-8"))
    seg = Segmentation.model_validate({**raw, **fields})
    return rules.model_copy(update={"segmentation": seg})


def test_the_shipped_rulebook_has_no_qualification_cap() -> None:
    assert get_rules().segmentation.qualification_max_chars is None


def test_a_long_single_sentence_qualification_parses_whole() -> None:
    assert _quals(_TEXT) == [_LONG_QUAL]


def test_an_unbulleted_paragraph_is_one_whole_item_when_uncapped() -> None:
    """With no cap there is nothing to split for: the paragraph the old form wrote is
    one item, every word kept. (A number in the knob restores the split.)"""
    paragraph = (
        "Undergraduate degree and three years work experience or a combination of "
        "equivalent education and experience. Demonstrated ability to provide "
        "leadership to IT staff and successfully help the team reach creative and "
        "productive solutions. Effective communications and interpersonal skills. "
        "Ability to achieve objectives working with a range of Management/Faculty/"
        "Staff without formal authority. Working knowledge of Microsoft desktop "
        "systems, TCP/IP networking, LAN and server security."
    )
    assert len(paragraph) > 400
    assert _quals(_HEAD + "H. ENTRANCE QUALIFICATIONS\n" + paragraph + "\n") == [
        paragraph
    ]


def test_the_cap_is_rulebook_data(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set the knob and the parser cuts there — proving it READS the YAML rather than
    keeping a constant in Python."""
    capped = _retuned_segmentation(get_rules(), qualification_max_chars=100)
    monkeypatch.setattr(rules_pkg, "get_rules", lambda: capped)
    assert _quals(_TEXT) == [_LONG_QUAL[:100]]


def test_the_rewrite_fidelity_table_follows_the_knob() -> None:
    rules = get_rules()
    assert field_cap("qualifications", rules) == 0  # "a field the parser does not cut"
    capped = _retuned_segmentation(rules, qualification_max_chars=100)
    assert field_cap("qualifications", capped) == 100


def test_the_model_and_the_builder_contracts_hold_the_whole_item() -> None:
    assert SFUQualification(text=_LONG_QUAL).text == _LONG_QUAL
    assert ModifiedQual(text=_LONG_QUAL).text == _LONG_QUAL
    assert SkillAnswer(text=_LONG_QUAL).text == _LONG_QUAL


def test_no_qualification_constant_survives_in_the_parser() -> None:
    assert not hasattr(segmenter, "_MAX_QUAL")

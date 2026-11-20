"""Parser v11 — a Decision Making / Problem Solving item or a contact is no longer cut
(owner ruling 2026-11-20, "remove the 400 cap").

Both readers cut every such item at the code constant ``segmenter._MAX_BULLET = 400``,
which was never registered. It was found by the v9 Bank smoke: a CUPE role's contact,
exported and read back, came back cut at 400 — and over the v9 Bank (parser v10) 4,668
documents carried 5,716 items at EXACTLY 400 characters against 160 at 390–399 (items:
4,226 Decision Making, 1,106 internal contacts, 304 external, 80 Problem Solving). It
is the third cap of the same family: HR-308 (one qualification) and HR-324 (the
supervisory text) were ruled ``null`` on 2026-10-29.

The cap is now rulebook data — ``segmentation.bullet_max_chars`` (HR-340) — and ships
``null`` = keep every item whole. A number there cuts at that length again, and the
rewrite's fidelity table and the export round-trip oracle follow it. The CUPE Builder's
contact row is bounded by a FORM ceiling instead, so a role cloned from the Bank with a
long contact still loads.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

import src.jd_core.rules as rules_pkg
from src.jd_bank.composer.wjq_answers import ContactAnswer
from src.jd_bank.rewrite.fidelity import field_cap
from src.jd_core.models.parsed_jd import WJQRow
from src.jd_core.parser import PARSER_VERSION, parse_jd, segmenter
from src.jd_core.parser import wjq as wjq_reader
from src.jd_core.rules import Rules, Segmentation, get_rules, loader
from src.jd_core.rules.loader import SEGMENTATION_FILE

#: One decision, far over 400 and with no sentence break — the shape the smoke found:
#: a long run-on item whose tail the cap dropped mid-word.
_LONG_ITEM = (
    "Makes decisions regarding the allocation of operating and project budgets across "
    "the unit's programs, the scheduling and prioritisation of competing service "
    "requests from faculty, staff and external partners, the selection of vendors and "
    "the negotiation of service levels within delegated signing authority, the hiring, "
    "training and day-to-day supervision of temporary staff, and the interpretation of "
    "university policy where the policy is silent or ambiguous, referring matters with "
    "financial, legal or reputational consequence to the Director"
)
assert len(_LONG_ITEM) > 400 and "." not in _LONG_ITEM

#: A contact as the CUPE questionnaire's contacts table writes it — one cell, long.
_LONG_CONTACT = (
    "Faculty, staff and students across the university, including department chairs, "
    "graduate program assistants, the Registrar's office, Financial Services, Human "
    "Resources and Facilities Services, to answer enquiries, resolve scheduling and "
    "registration problems, process forms and payments, and coordinate events, room "
    "bookings and the distribution of course materials throughout each semester of "
    "the academic year"
)
assert len(_LONG_CONTACT) > 400

_WJQ = (
    "SIMON FRASER UNIVERSITY & C.U.P.E., LOCAL 3338\n"
    "WEIGHTED JOB QUESTIONNAIRE (WJQ) CUSTOM\n"
    "PART 1: JOB DESCRIPTION\n"
    "1.  POSITION IDENTIFICATION\n"
    "Department Position Title:\n"
    "Program Assistant\n"
    "2.  POSITION SUMMARY\n"
    "Provides support to the Registrar.\n"
    "3.  MAJOR FUNCTIONS\n"
    "Answers enquiries about registration. (D)\n"
    "8.  INTERNAL AND EXTERNAL CONTACTS\n"
    "Type of Contact\n"
    f"{_LONG_CONTACT}\n"
    "14.  APPROVAL AND REVIEW\n"
)


def _retuned_segmentation(rules: Rules, **fields: object) -> Rules:
    rules_dir = Path(loader.__file__).resolve().parent
    raw = yaml.safe_load((rules_dir / SEGMENTATION_FILE).read_text(encoding="utf-8"))
    seg = Segmentation.model_validate({**raw, **fields})
    return rules.model_copy(update={"segmentation": seg})


def _jdfn(section: str, body: str) -> str:
    return f"{section}\n• {body}\n"


def test_the_shipped_rulebook_has_no_list_item_cap() -> None:
    assert get_rules().segmentation.bullet_max_chars is None


def test_a_long_decision_parses_whole() -> None:
    jd = parse_jd(_jdfn("IMPACT OF DECISION MAKING", _LONG_ITEM)).jd
    assert jd.decision_making == [_LONG_ITEM]


def test_a_long_problem_parses_whole() -> None:
    jd = parse_jd(_jdfn("PROBLEM SOLVING", _LONG_ITEM)).jd
    assert jd.problem_solving == [_LONG_ITEM]


@pytest.mark.parametrize("label", ["Internal Connections", "External Connections"])
def test_a_long_jdfn_contact_parses_whole(label: str) -> None:
    text = f"RELATIONSHIPS\n{label}: {_LONG_CONTACT}\n"
    rel = parse_jd(text).jd.relationships
    assert rel is not None
    side = rel.internal if label.startswith("Internal") else rel.external
    assert side == [_LONG_CONTACT]


def test_a_long_bulleted_contact_parses_whole() -> None:
    text = f"RELATIONSHIPS\nInternal Connections:\n• {_LONG_CONTACT}\n"
    rel = parse_jd(text).jd.relationships
    assert rel is not None
    assert rel.internal == [_LONG_CONTACT]


def test_a_long_wjq_contact_parses_whole() -> None:
    result = parse_jd(_WJQ)
    assert result.template == "wjq"
    rel = result.jd.relationships
    assert rel is not None
    assert [*rel.internal, *rel.external] == [_LONG_CONTACT]


def test_the_cap_is_rulebook_data(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set the knob and BOTH readers cut there — proving they read the YAML rather than
    keeping a constant in Python."""
    capped = _retuned_segmentation(get_rules(), bullet_max_chars=100)
    monkeypatch.setattr(rules_pkg, "get_rules", lambda: capped)
    monkeypatch.setattr(wjq_reader, "get_rules", lambda: capped)  # bound at import
    decisions = parse_jd(_jdfn("IMPACT OF DECISION MAKING", _LONG_ITEM)).jd
    assert decisions.decision_making == [_LONG_ITEM[:100]]
    rel = parse_jd(f"RELATIONSHIPS\nExternal Connections: {_LONG_CONTACT}\n").jd
    assert rel.relationships is not None
    assert rel.relationships.external == [_LONG_CONTACT[:100]]
    wjq_rel = parse_jd(_WJQ).jd.relationships
    assert wjq_rel is not None
    assert [*wjq_rel.internal, *wjq_rel.external] == [_LONG_CONTACT[:100]]


def test_the_rewrite_fidelity_table_follows_the_knob() -> None:
    rules = get_rules()
    fields = ("decision_making", "problem_solving", "internal", "external")
    assert [field_cap(f, rules) for f in fields] == [0, 0, 0, 0]
    capped = _retuned_segmentation(rules, bullet_max_chars=100)
    assert [field_cap(f, capped) for f in fields] == [100, 100, 100, 100]


def test_the_cupe_contact_row_holds_a_long_contact() -> None:
    """A CUPE role cloned from the Bank seeds the Builder's contact rows from its
    relationships; a 400-character row would refuse to load it."""
    assert ContactAnswer(contact=_LONG_CONTACT).contact == _LONG_CONTACT
    assert WJQRow(item=_LONG_CONTACT).item == _LONG_CONTACT


def test_no_list_item_constant_survives_in_the_parser() -> None:
    assert not hasattr(segmenter, "_MAX_BULLET")


def test_the_parser_version_moved() -> None:
    """Changing what a parse contains bumps the version: ``parsed_jds`` is idempotent
    per ``(source_document_id, parser_version)``, so a re-ingest at v10 would keep the
    cut parses and every reader would call them current."""
    assert PARSER_VERSION == "jd_segmenter_v11"

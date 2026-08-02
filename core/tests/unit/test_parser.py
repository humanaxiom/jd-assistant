"""Unit tests for the deterministic JD segmenter (Phase 1.4).

Drives the two annotated fixtures (``sfu_new_template.txt`` /
``sfu_old_template.txt``) plus the real legacy ``sample_legacy.doc`` (extracted
offline) to assert: era detection, section segmentation + **section recall**,
per-section confidence (high for explicitly-headed, ~0 for absent), best-effort
duty/qualification structuring, footer presence-booleans, and robustness on
empty/garbled input.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.jd_bank.ingest.extract import extract_text_from_path
from src.jd_core.parser import ParseResult, parse_jd
from src.jd_core.parser.headings import SectionKey, match_heading

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def _new() -> ParseResult:
    return parse_jd((FIXTURES / "sfu_new_template.txt").read_text(encoding="utf-8"))


def _old() -> ParseResult:
    return parse_jd((FIXTURES / "sfu_old_template.txt").read_text(encoding="utf-8"))


def _recall(result: ParseResult, expected: set[SectionKey]) -> float:
    located = {s for s in expected if result.section_confidence[s.value] > 0.0}
    return len(located) / len(expected)


# ── Era detection ────────────────────────────────────────────────────────────


def test_new_template_detected_as_new() -> None:
    assert _new().era == "new"


def test_old_template_detected_as_old() -> None:
    assert _old().era == "old"


def test_empty_input_era_unknown() -> None:
    assert parse_jd("").era == "unknown"


# ── Heading matcher (tolerant of lettering / case / whitespace) ──────────────


@pytest.mark.parametrize(
    ("line", "section"),
    [
        ("ABOUT SIMON FRASER UNIVERSITY", SectionKey.ABOUT_SFU),
        ("A. IDENTIFICATION", SectionKey.IDENTIFICATION),
        ("C. DUTIES AND RESPONSIBILITIES", SectionKey.DUTIES),
        ("  duties & responsibilities ", SectionKey.DUTIES),
        ("IMPACT OF DECISION MAKING", SectionKey.DECISION_MAKING),
        ("D. DECISION MAKING", SectionKey.DECISION_MAKING),
        ("PROBLEM SOLVING AND LEVEL OF SUPERVISION", SectionKey.PROBLEM_SOLVING),
        ("Minimum Entrance Qualifications", SectionKey.QUALIFICATIONS),
        ("Summary of Responsibility", SectionKey.POSITION_SUMMARY),
        ("Supervision Received", SectionKey.RELATIONSHIPS),
    ],
)
def test_match_heading(line: str, section: SectionKey) -> None:
    matched = match_heading(line)
    assert matched is not None
    assert matched[0] is section


def test_content_line_is_not_a_heading() -> None:
    assert match_heading("Responsible for solving problems related to:") is None
    assert match_heading("- Coordinates communication between investigators.") is None
    assert match_heading("The Manager processes grant applications.") is None


# ── NEW-era segmentation + recall ────────────────────────────────────────────


def test_new_template_full_section_recall() -> None:
    result = _new()
    all_ten = set(SectionKey)
    assert _recall(result, all_ten) == 1.0


def test_new_identification_fields() -> None:
    jd = _new().jd
    assert jd.title == "Manager, Special Projects"
    assert jd.department == "Office of the Vice-President Research"
    assert jd.position_number == "90012345"
    assert jd.employee_group == "apsa"


def test_new_position_summary_and_context() -> None:
    jd = _new().jd
    assert jd.position_summary is not None
    assert "identification, design and implementation" in jd.position_summary
    assert jd.additional_context is not None
    assert "travel" in jd.additional_context


def test_new_duties_structured() -> None:
    jd = _new().jd
    assert len(jd.duties) >= 3
    verbs = {d.action_verb for d in jd.duties}
    assert "Manages" in verbs
    assert all(d.statement for d in jd.duties)


def test_new_decision_and_problem_bullets() -> None:
    jd = _new().jd
    assert len(jd.decision_making) >= 2
    assert len(jd.problem_solving) >= 2
    # The `… regarding:` / `… related to:` intro lines are dropped.
    assert not any(b.endswith(":") for b in jd.decision_making)


def test_new_relationships_split() -> None:
    rel = _new().jd.relationships
    assert rel is not None
    assert rel.internal and "faculties" in rel.internal[0]
    assert rel.external and "associations" in rel.external[0]


def test_new_qualifications_classified() -> None:
    quals = _new().jd.qualifications
    assert len(quals) >= 4
    kinds = {q.kind for q in quals}
    assert {"education", "knowledge", "skill", "ability"} <= kinds
    knowledge = next(q for q in quals if q.kind == "knowledge")
    assert knowledge.modifier == "excellent"
    skill = next(q for q in quals if q.kind == "skill")
    assert skill.modifier == "advanced"


def test_new_footer_presence_booleans() -> None:
    jd = _new().jd
    assert jd.about_sfu_present is True
    assert jd.territorial_acknowledgement_present is True
    assert jd.employment_equity_present is True


def test_new_confidence_high_for_headed_sections() -> None:
    conf = _new().section_confidence
    for section in SectionKey:
        assert conf[section.value] >= 0.7, section
    assert _new().parse_confidence > 0.75


# ── OLD-era segmentation + recall ────────────────────────────────────────────


def test_old_template_section_recall() -> None:
    present = {
        SectionKey.IDENTIFICATION,
        SectionKey.POSITION_SUMMARY,
        SectionKey.DUTIES,
        SectionKey.DECISION_MAKING,
        SectionKey.PROBLEM_SOLVING,
        SectionKey.RELATIONSHIPS,
        SectionKey.QUALIFICATIONS,
    }
    assert _recall(_old(), present) == 1.0


def test_old_identification_fields() -> None:
    jd = _old().jd
    assert jd.title == "Research Grants Coordinator"
    assert jd.department == "Office of Research Services"
    assert jd.position_number == "00456789"


def test_old_absent_sections_zero_confidence() -> None:
    conf = _old().section_confidence
    assert conf[SectionKey.ABOUT_SFU.value] == 0.0
    assert conf[SectionKey.FOOTER.value] == 0.0
    assert conf[SectionKey.ADDITIONAL_CONTEXT.value] == 0.0


def test_old_footer_booleans_absent() -> None:
    jd = _old().jd
    assert jd.about_sfu_present is False
    assert jd.territorial_acknowledgement_present is False
    assert jd.employment_equity_present is False


def test_old_duties_and_quals() -> None:
    jd = _old().jd
    assert len(jd.duties) >= 3
    verbs = {d.action_verb for d in jd.duties}
    assert {"Processes", "Coordinates", "Maintains"} <= verbs
    kinds = {q.kind for q in jd.qualifications}
    assert {"education", "knowledge", "skill", "ability"} <= kinds
    knowledge = next(q for q in jd.qualifications if q.kind == "knowledge")
    assert knowledge.modifier == "working"


def test_old_relationships_supervisory() -> None:
    rel = _old().jd.relationships
    assert rel is not None
    assert rel.supervisory is not None
    assert "general direction" in rel.supervisory
    assert rel.internal and rel.external


def test_old_confidence_present_high_overall_moderate() -> None:
    result = _old()
    for section in (
        SectionKey.POSITION_SUMMARY,
        SectionKey.DUTIES,
        SectionKey.QUALIFICATIONS,
    ):
        assert result.section_confidence[section.value] >= 0.7
    # Three sections absent → an honest, moderate overall score.
    assert 0.4 < result.parse_confidence < 0.8


# ── Robustness ───────────────────────────────────────────────────────────────


def test_empty_input_does_not_crash() -> None:
    result = parse_jd("")
    assert result.jd.title == "Untitled Position"
    assert result.jd.duties == []
    assert result.parse_confidence < 0.2


def test_garbled_input_does_not_crash() -> None:
    result = parse_jd("!!!\n\n\x0c random ~~~ bytes ;;; no headings at all\n42 42 42")
    assert result.jd.title  # non-empty (min_length=1 satisfied)
    assert result.era == "unknown"
    assert result.parse_confidence < 0.3


def test_whitespace_only_input() -> None:
    result = parse_jd("   \n\t\n   ")
    assert result.jd.title == "Untitled Position"
    assert result.parse_confidence < 0.2


def test_parser_version_constant() -> None:
    """``parsed_jds`` is keyed on ``(source_document_id, parser_version)``, so this
    literal is what forces (or fails to force) an archive re-parse. v3 = the
    docx-header identification-block fix."""
    assert parse_jd("anything").parser_version == "jd_segmenter_v3"


# ── End-to-end on the real legacy .doc ───────────────────────────────────────


def test_legacy_doc_end_to_end() -> None:
    """Extract the real OLD-era Systems-Consultant .doc via ingestion, then
    parse it. The two-column layout is deliberately messy — assert robust
    extraction of identification + era, not perfect section recall."""
    text = extract_text_from_path(FIXTURES / "sample_legacy.doc")
    result = parse_jd(text)
    assert result.era == "old"
    assert result.jd.title == "Systems Analyst II"
    assert result.jd.department == "Computing Centre"
    assert result.jd.position_number == "01211"
    assert result.jd.about_sfu_present is False
    assert len(result.jd.duties) >= 1
    assert 0.0 < result.parse_confidence < 1.0

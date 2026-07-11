"""Expected SFU rule-catalog metadata — the independent oracle for Phase 2.2.

Transcribed by hand from the hris sources (read-only reference), **not** imported
from ``src`` and **not** derived from the shipped YAML:

* ``packages/pipeline/src/pipeline/quality/rule_catalog.py`` — the 27 ``RuleSpec``
  entries (category, section, source_part, default severity, owner), the section
  labels + template order, and the category->section fallback map;
* ``packages/pipeline/src/pipeline/quality/jd_rules.py`` — the severity each call
  site actually raises, and the scoring calibration (``_SEVERITY_PENALTY``,
  ``_SEVERITY_DECAY``, ``_GRADE_BANDS``).

If the ported catalog ever drifts from hris, these tables are what catches it.
Not a test module (no ``test_`` prefix) — pytest imports it, never collects it.
"""

from __future__ import annotations

from typing import NamedTuple


class Expected(NamedTuple):
    """One rule's catalogued metadata, as hris defines it."""

    category: str
    section: str
    source_part: str
    default_severity: str
    owner: str = "deterministic"


# --- the deterministic rules -------------------------------------------------
#
# hris catalogues 27. We carry 29: the two-sided summary-length and duty-count
# rules are each split into an over-run and an under-run rule_id (see below) so the
# Phase-2.3 approval policy can gate exactly the condition SFU's never-approve list
# names. Detection is unchanged — same triggers, same severities.

EXPECTED_CATALOG: dict[str, Expected] = {
    # completeness — mandatory template sections (Part 2)
    "SFU-COMP-SUMMARY": Expected("completeness", "position_summary", "Part 2B", "high"),
    "SFU-COMP-DUTIES": Expected("completeness", "duties", "Part 2C", "high"),
    "SFU-COMP-DECISION": Expected(
        "completeness", "decision_making", "Part 2D", "medium"
    ),
    "SFU-COMP-PROBLEM": Expected(
        "completeness", "problem_solving", "Part 2E", "medium"
    ),
    "SFU-COMP-RELATIONSHIPS": Expected(
        "completeness", "relationships", "Part 2F", "low"
    ),
    "SFU-COMP-QUALS": Expected("completeness", "qualifications", "Part 2H", "high"),
    "SFU-COMP-ABOUT": Expected("completeness", "about_sfu", "Part 2", "low"),
    "SFU-COMP-TERRITORIAL": Expected("completeness", "edi_footer", "Part 2", "low"),
    "SFU-COMP-EDI": Expected("completeness", "edi_footer", "Part 2", "low"),
    # structure — SFU format.
    # The summary-length and duty-count checks are two-sided; SFU's never-approve
    # list names only the MAXIMUM, so each is catalogued as two rules (over-run vs
    # under-run) and the approval policy can gate one without the other. Same
    # triggers, same severities as the single hris rules they split.
    "SFU-STRUCT-SUMMARY-TOO-SHORT": Expected(
        "structure", "position_summary", "Part 2B", "low"
    ),
    "SFU-STRUCT-SUMMARY-TOO-LONG": Expected(
        "structure", "position_summary", "Part 2B", "low"
    ),
    "SFU-STRUCT-DUTIES-TOO-FEW": Expected("structure", "duties", "Part 2C", "medium"),
    "SFU-STRUCT-DUTIES-TOO-MANY": Expected("structure", "duties", "Part 2C", "medium"),
    "SFU-STRUCT-ACTION-VERB": Expected("structure", "duties", "Glossary", "low"),
    "SFU-STRUCT-HOW-WHY": Expected("structure", "duties", "Part 2C", "low"),
    "SFU-STRUCT-PLACEHOLDER": Expected("structure", "general", "Part 2", "medium"),
    # qualification standards
    "SFU-QUAL-SKILL-MODIFIER": Expected(
        "qualification_standard", "qualifications", "Part 5", "low"
    ),
    "SFU-QUAL-MODIFIER-VOCAB": Expected(
        "qualification_standard", "qualifications", "Part 5", "low"
    ),
    "SFU-QUAL-EQUIVALENT": Expected(
        "qualification_standard", "qualifications", "Part 2H", "low"
    ),
    "SFU-QUAL-BANNED-PHRASE": Expected(
        "qualification_standard", "qualifications", "Part 2H", "medium"
    ),
    "SFU-QUAL-DEGREE-DISCIPLINE": Expected(
        "qualification_standard", "qualifications", "Part 2H", "low"
    ),
    # inclusive language (whole document)
    "SFU-LANG-CODED": Expected("inclusive_language", "general", "Part 6", "medium"),
    # quality gates (Part 11.6 "never approve")
    "SFU-GATE-DUTY-PCT": Expected("structure", "duties", "Part 11.6", "medium"),
    "SFU-GATE-KSA-ORDER": Expected(
        "qualification_standard", "qualifications", "Part 5.4", "low"
    ),
    "SFU-GATE-SENIOR-TITLE": Expected("structure", "identification", "Part 3.5", "low"),
    "SFU-GATE-REL-HEADER": Expected("completeness", "relationships", "Part 2F", "low"),
    # authoring gates (Parts 2-3)
    "SFU-AUTH-SUMMARY-CONDITIONS": Expected(
        "structure", "position_summary", "Part 2B", "medium"
    ),
    "SFU-AUTH-SUMMARY-INCUMBENT": Expected(
        "structure", "position_summary", "Part 2B", "low"
    ),
    "SFU-AUTH-ABILITIES-OBSERVABLE": Expected(
        "qualification_standard", "qualifications", "Part 5.3", "low"
    ),
    "SFU-AUTH-TITLE-EXEC-DIR": Expected(
        "structure", "identification", "Part 3.5", "low"
    ),
    "SFU-AUTH-TITLE-REGISTRAR": Expected(
        "structure", "identification", "Part 3.5", "info"
    ),
    "SFU-AUTH-TITLE-HR": Expected("structure", "identification", "Part 3.5", "info"),
}

#: Rules whose finding must carry an evidence snippet (hris passes ``evidence=``).
EVIDENCE_RULES: frozenset[str] = frozenset(
    {
        "SFU-STRUCT-PLACEHOLDER",
        "SFU-QUAL-BANNED-PHRASE",
        "SFU-LANG-CODED",
        "SFU-GATE-DUTY-PCT",
        "SFU-AUTH-SUMMARY-CONDITIONS",
    }
)

# --- section presentation ----------------------------------------------------

EXPECTED_SECTION_ORDER: tuple[str, ...] = (
    "about_sfu",
    "identification",
    "position_summary",
    "duties",
    "decision_making",
    "problem_solving",
    "relationships",
    "qualifications",
    "edi_footer",
    "additional_context",
)

EXPECTED_SECTION_LABELS: dict[str, str] = {
    "about_sfu": "About SFU",
    "identification": "Identification",
    "position_summary": "Position Summary",
    "duties": "Duties & Responsibilities",
    "decision_making": "Impact of Decision Making",
    "problem_solving": "Problem Solving & Level of Supervision",
    "relationships": "Relationships",
    "qualifications": "Qualifications",
    "edi_footer": "Territorial Acknowledgement & EDI",
    "additional_context": "Additional Contextual Information",
    "general": "General (whole document)",
}

EXPECTED_CATEGORY_FALLBACK: dict[str, str] = {
    "completeness": "general",
    "structure": "general",
    "qualification_standard": "qualifications",
    "matchability": "general",
    "over_specification": "qualifications",
    "keyword_stuffing": "qualifications",
    "seniority_mismatch": "identification",
    "inclusive_language": "general",
    "clarity": "general",
}

# --- scoring calibration (jd_rules_sfu_v3) -----------------------------------

EXPECTED_PENALTY: dict[str, float] = {
    "high": 20.0,
    "medium": 10.0,
    "low": 5.0,
    "info": 0.0,
}
EXPECTED_DECAY = 0.7
EXPECTED_GRADE_BANDS: tuple[tuple[float, str], ...] = (
    (90.0, "A"),
    (75.0, "B"),
    (60.0, "C"),
    (40.0, "D"),
)

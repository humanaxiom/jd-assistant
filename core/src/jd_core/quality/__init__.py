"""The SFU JD quality engine — deterministic validators, scoring, checklist.

Phase 2.2. The public surface every consumer (the Phase 2.3 gate runner, the
archive baseline, the API) uses::

    from src.jd_core.quality import build_checklist, evaluate_jd_rules, score_issues
    from src.jd_core.rules import get_rules

    issues = evaluate_jd_rules(parsed_jd, raw_text)   # list[JDQualityIssue]
    score, grade = score_issues(issues)               # (float, JDGrade)
    checklist = build_checklist(issues)               # list[JDChecklistSection]
    rules_version = get_rules().version               # stamp the report with it

Every rule datum — thresholds, verb glossary, coded-term lexicon, markers,
regexes, restricted titles, severities, grade bands, and the 27-rule catalog with
its message copy — is versioned YAML under ``jd_core/rules/`` (CLAUDE.md
non-negotiable #2). Nothing here is hardcoded rulebook content; the validator is
the oracle (#3), so tests assert its post-state, never model prose.
"""

from src.jd_core.quality.checklist import build_checklist, section_for_issue
from src.jd_core.quality.scoring import score_issues
from src.jd_core.quality.validators import evaluate_jd_rules

__all__ = [
    "build_checklist",
    "evaluate_jd_rules",
    "score_issues",
    "section_for_issue",
]

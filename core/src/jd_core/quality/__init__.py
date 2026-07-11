"""The SFU JD quality engine — deterministic validators, scoring, checklist, gates.

Phases 2.2 + 2.3. The public surface every consumer (the archive baseline, the
API, the composer) uses::

    from src.jd_core.quality import (
        build_checklist, build_report, evaluate_gates, evaluate_jd_rules, score_issues
    )

    issues = evaluate_jd_rules(parsed_jd, raw_text)   # list[JDQualityIssue]
    score, grade = score_issues(issues)               # (float, JDGrade)
    checklist = build_checklist(issues)               # list[JDChecklistSection]
    decision = evaluate_gates(issues, score, grade)   # may a human approve at all?

    report = build_report(job_id=..., issues=issues, model=..., prompt_version=...)

Every rule datum — thresholds, verb glossary, coded-term lexicon, markers,
regexes, restricted titles, severities, the score scale, grade bands, the 27-rule
catalog with its message copy, **and the whole approval policy** (which rules are
fatal, the severity / score / grade floors, what a reviewer may override) — is
versioned YAML under ``jd_core/rules/`` (CLAUDE.md non-negotiable #2). Not one
decision number is hardcoded here; the validator is the oracle (#3), so tests
assert its post-state, never model prose.

The gate runner never approves a JD — it decides whether a human may (#1).
"""

from src.jd_core.quality.checklist import build_checklist, section_for_issue
from src.jd_core.quality.gates import (
    GateOverrideError,
    apply_overrides,
    evaluate_gates,
)
from src.jd_core.quality.report import build_report
from src.jd_core.quality.scoring import score_issues
from src.jd_core.quality.validators import evaluate_jd_rules

__all__ = [
    "GateOverrideError",
    "apply_overrides",
    "build_checklist",
    "build_report",
    "evaluate_gates",
    "evaluate_jd_rules",
    "score_issues",
    "section_for_issue",
]

"""Section-grouped checklist — the way a recruiter actually reads a JD.

Regroups a flat issue list into the SFU guide's section-by-section checklist.
Ported from hris ``rule_catalog.build_checklist`` / ``section_for_issue``; the
section labels, the template order, and the category->section fallback map are
rulebook data (``rules/rule_catalog.yaml``), so this module is pure regrouping.

The checklist is a presentation view derived from ``issues``, not a second source
of truth — it is recomputed on read, never persisted alongside them.
"""

from __future__ import annotations

from src.jd_core.models.quality import JDChecklistSection, JDQualityIssue, SFUSection
from src.jd_core.rules import GENERAL_SECTION, RuleCatalog, get_rules


def _catalog(catalog: RuleCatalog | None) -> RuleCatalog:
    return catalog if catalog is not None else get_rules().rule_catalog


def section_for_issue(
    issue: JDQualityIssue, *, catalog: RuleCatalog | None = None
) -> SFUSection:
    """The SFU section an issue belongs to: its rule's section when the
    ``rule_id`` is catalogued, else the category fallback (an LLM finding), else
    the cross-cutting bucket."""
    return _catalog(catalog).section_for(issue.category, issue.rule_id)


def build_checklist(
    issues: list[JDQualityIssue], *, catalog: RuleCatalog | None = None
) -> list[JDChecklistSection]:
    """Regroup a flat issue list into the guide's section-by-section checklist.

    Every one of the SFU template sections is returned in template order — so a
    reviewer sees a complete pass, with clean sections marked ``ok`` — and the
    cross-cutting ``general`` bucket (inclusive language, placeholders, and any
    LLM finding that maps to no single section) is appended last, and only when
    it holds findings. Every issue lands in exactly one section.
    """
    rule_catalog = _catalog(catalog)
    grouped: dict[SFUSection, list[JDQualityIssue]] = {}
    for issue in issues:
        section = rule_catalog.section_for(issue.category, issue.rule_id)
        grouped.setdefault(section, []).append(issue)

    checklist = [
        JDChecklistSection(
            section=section,
            label=rule_catalog.label(section),
            status="issues" if grouped.get(section) else "ok",
            issues=grouped.get(section, []),
        )
        for section in rule_catalog.section_order
    ]
    general = grouped.get(GENERAL_SECTION, [])
    if general:
        checklist.append(
            JDChecklistSection(
                section=GENERAL_SECTION,
                label=rule_catalog.label(GENERAL_SECTION),
                status="issues",
                issues=general,
            )
        )
    return checklist

"""Versioned SFU rulebook, as data.

The YAML files in this package ARE the rulebook (CLAUDE.md non-negotiable #2:
gates, word lists, verb lists, KSA modifiers and restricted titles live in
versioned YAML, never hardcoded in logic). :mod:`.loader` is the only reader:
it validates them into frozen pydantic models and precompiles the regexes.

    from src.jd_core.rules import get_rules

    rules = get_rules()
    rules.thresholds.duties_max          # 5
    rules.scoring.grade_for(82.0)        # "B"

Bump ``version:`` in *every* YAML file together whenever a threshold, the
lexicon, the glossary, or the scoring changes — the loader rejects a split
version.
"""

from src.jd_core.rules.loader import (
    GENERAL_SECTION,
    RULE_FILES,
    ActionVerbs,
    CodedTerms,
    GradeBand,
    Markers,
    Patterns,
    Qualifications,
    RestrictedTitle,
    RuleCatalog,
    RuleOwner,
    Rules,
    RulesError,
    RuleSpec,
    Scoring,
    Thresholds,
    Titles,
    get_rules,
    load_rules,
)

__all__ = [
    "GENERAL_SECTION",
    "RULE_FILES",
    "ActionVerbs",
    "CodedTerms",
    "GradeBand",
    "Markers",
    "Patterns",
    "Qualifications",
    "RestrictedTitle",
    "RuleCatalog",
    "RuleOwner",
    "RuleSpec",
    "Rules",
    "RulesError",
    "Scoring",
    "Thresholds",
    "Titles",
    "get_rules",
    "load_rules",
]

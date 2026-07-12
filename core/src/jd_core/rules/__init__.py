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
    CONTENT_HASH_LENGTH,
    GENERAL_SECTION,
    HAY_BASE_LEVEL,
    REGISTER_FILE,
    RULE_FILES,
    SEGMENTATION_FILE,
    UNMAPPED,
    VERSION_SEPARATOR,
    ActionVerbs,
    BlockingRulesGate,
    Boilerplate,
    CodedTerms,
    Comparison,
    ConfigRef,
    DecisionProvenance,
    DecisionRegister,
    DecisionStatus,
    GatePolicy,
    GateSpec,
    GradeBand,
    GradeFloorGate,
    HaySignalRules,
    HRDecision,
    Markers,
    Patterns,
    PositionIdGrouping,
    Qualifications,
    RestrictedTitle,
    RuleCatalog,
    RuleOwner,
    Rules,
    RulesError,
    RuleSpec,
    ScoreFloorGate,
    Scoring,
    Segmentation,
    SeverityFloorGate,
    TextNorm,
    Thresholds,
    Titles,
    TrivialExemption,
    assert_register_in_step,
    check_register,
    decision_surface,
    get_rules,
    live_value,
    load_rules,
    normalize_config_value,
    resolve_config_path,
)

# NOTE: `src.jd_core.rules.render` is deliberately NOT re-exported here. It is the
# register's *view* (and a `python -m` entry point the Makefile runs); importing it
# from this package would make `-m` re-execute an already-imported module. Import it
# directly: `from src.jd_core.rules.render import render_register`.

__all__ = [
    "CONTENT_HASH_LENGTH",
    "GENERAL_SECTION",
    "HAY_BASE_LEVEL",
    "REGISTER_FILE",
    "RULE_FILES",
    "UNMAPPED",
    "VERSION_SEPARATOR",
    "ActionVerbs",
    "BlockingRulesGate",
    "Boilerplate",
    "CodedTerms",
    "Comparison",
    "ConfigRef",
    "PositionIdGrouping",
    "SEGMENTATION_FILE",
    "Segmentation",
    "DecisionProvenance",
    "DecisionRegister",
    "DecisionStatus",
    "GatePolicy",
    "GateSpec",
    "GradeBand",
    "GradeFloorGate",
    "HRDecision",
    "HaySignalRules",
    "Markers",
    "Patterns",
    "Qualifications",
    "RestrictedTitle",
    "RuleCatalog",
    "RuleOwner",
    "RuleSpec",
    "Rules",
    "RulesError",
    "ScoreFloorGate",
    "Scoring",
    "SeverityFloorGate",
    "TextNorm",
    "Thresholds",
    "Titles",
    "TrivialExemption",
    "assert_register_in_step",
    "check_register",
    "decision_surface",
    "get_rules",
    "live_value",
    "load_rules",
    "normalize_config_value",
    "resolve_config_path",
]

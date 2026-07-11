"""Transparent JD quality score: 100 minus a severity-weighted penalty.

Ported from hris ``jd_rules.score_issues`` (calibration ``jd_rules_sfu_v3``). The
calibration itself — the per-severity penalties, the decay factor, the grade bands
— is rulebook data in ``rules/scoring.yaml``; this module is only the arithmetic.

Why the decay: the old linear ``100 - Σpenalty`` floored a JD with many minor
nudges to 0 exactly like one with several fatal gaps — it measured issue *count*,
not the severity of the worst problems, so more than half the corpus collapsed to
an undifferentiated F0. Per-severity diminishing returns keeps each severity's
first (worst) finding at full weight and dampens the tail (a tier's total penalty
is bounded at ``penalty / (1 - decay)``), so a pile of advisory tone/clarity nudges
cannot alone force an F while genuine high-severity failures still drive a low
grade. Tiers do NOT decay against each other.
"""

from __future__ import annotations

from collections import Counter

from src.jd_core.models.quality import JDGrade, JDQualityIssue
from src.jd_core.rules import Scoring, get_rules


def score_issues(
    issues: list[JDQualityIssue], *, scoring: Scoring | None = None
) -> tuple[float, JDGrade]:
    """Score a flat issue list -> ``(overall_score, grade)``.

    Each severity tier's k-th (0-indexed) finding costs
    ``severity_penalty[tier] * severity_decay ** k``; the tier's total is the
    geometric sum ``base * (1 - decay**n) / (1 - decay)``. The score floors at 0.
    A ``decay`` of exactly 1.0 turns diminishing returns off (linear penalties).

    ``scoring`` defaults to the shipped calibration; pass a different
    :class:`~src.jd_core.rules.Scoring` (still validated rulebook data) to tune or
    to evaluate an alternative calibration. The grade is looked up by
    ``Scoring.grade_for`` — the bands live in the rulebook, never here.
    """
    table = scoring if scoring is not None else get_rules().scoring
    counts = Counter(issue.severity for issue in issues)
    decay = table.severity_decay

    penalty = 0.0
    for severity, n in counts.items():
        base = table.severity_penalty.get(severity, 0.0)
        if base == 0.0:
            continue
        if decay >= 1.0:
            penalty += base * n  # diminishing returns off -> linear
        else:
            # base * (1 + d + d^2 + ... + d^(n-1)) = base * (1 - d^n) / (1 - d)
            penalty += base * (1.0 - decay**n) / (1.0 - decay)

    score = max(0.0, 100.0 - penalty)
    return score, table.grade_for(score)

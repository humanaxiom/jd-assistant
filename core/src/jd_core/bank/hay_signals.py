"""Advisory Hay-factor signal estimation from an SFU JD (pure, deterministic).

Ported from hris ``packages/pipeline/src/pipeline/bank/hay_signals.py``
(reuse-map #12, ADR-005).

SFU classifies APSA/Excluded jobs with the Hay Guide Chart-Profile Method's three
factors — **Know-How**, **Problem-Solving**, **Accountability**. The point charts
are proprietary and SFU publishes none of them.

**This module never assigns a grade, and cannot.** It reads the JD's own structured
sections (which map onto the Hay factors: Qualifications + Relationships → Know-How,
Problem Solving → Problem-Solving, Impact of Decision Making → Accountability) and
emits a transparent low/moderate/high *signal* per factor, citing the exact phrases
that drove it, to help Compensation **level** a role. Classification stays a human
Compensation decision. hris's estimator built its result with ``grade_mapped=False``
— :class:`~src.jd_core.models.bank.HaySignals` has no such field here, and no
``grade`` either: the source-gate is structural, not a flag (see ``models/bank.py``).

Deterministic and explainable by design: no LLM, no hidden weights. hris hardcoded
the five keyword lexicons *and* every weight and cutoff (``score += 3``,
``_level(score, mod=3, hi=5)``). Those numbers decide the signal, so they are
rulebook data (CLAUDE.md §2): they live in ``rules/hay_signals.yaml``, are
registered `open` with HR (HR-066 … HR-081), and this module only executes them.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence

from src.jd_core.models.bank import (
    HayFactor,
    HayFactorSignal,
    HaySignalLevel,
    HaySignals,
)
from src.jd_core.models.parsed_jd import SFUJobDescription, SFUQualification
from src.jd_core.rules import HAY_BASE_LEVEL, HaySignalRules, Rules, get_rules


def _hits(texts: Iterable[str], cues: Iterable[str]) -> list[str]:
    """Which of ``cues`` appear (as substrings) anywhere in ``texts``, cue order.

    Each cue counts at most once however often it occurs: a JD that says
    "independently" twenty times is not twice as autonomous as one that says it
    once. (That is also what makes the evidence list naturally near-unique.)
    """
    blob = "\n".join(text.lower() for text in texts)
    return [cue for cue in cues if cue in blob]


def _level(score: float, cutoffs: Mapping[HaySignalLevel, float]) -> HaySignalLevel:
    """The highest level whose score cutoff ``score`` clears, else the floor.

    The loader guarantees ``cutoffs`` carries every level except
    :data:`~src.jd_core.rules.HAY_BASE_LEVEL`, each with a distinct cutoff — so
    this is a total function and the ladder itself is data, not an ``if/elif``.
    """
    for level, cutoff in sorted(cutoffs.items(), key=lambda kv: kv[1], reverse=True):
        if score >= cutoff:
            return level
    return HAY_BASE_LEVEL


def _capped(evidence: Sequence[str], *, cap: int) -> list[str]:
    """``evidence``, first occurrence of each phrase kept, truncated to ``cap``."""
    seen: set[str] = set()
    kept: list[str] = []
    for phrase in evidence:
        if phrase not in seen:
            seen.add(phrase)
            kept.append(phrase)
    return kept[:cap]


def _signal(
    factor: HayFactor,
    score: float,
    evidence: Sequence[str],
    *,
    cutoffs: Mapping[HaySignalLevel, float],
    rationale: str,
    cap: int,
) -> HayFactorSignal:
    """One factor's signal: the level its score earns, and the evidence, capped."""
    level = _level(score, cutoffs)
    return HayFactorSignal(
        factor=factor,
        level=level,
        rationale=rationale.format(level=level.capitalize()),
        evidence=_capped(evidence, cap=cap),
    )


def _section_points(
    texts: Sequence[str], points: Mapping[str, float], counts: Mapping[str, int]
) -> float:
    """Credit for *having* a section, capped: length is not depth."""
    scored = min(len(texts), counts["section_items_scored"])
    return scored * points["section_item"]


def _modifier(qualification: SFUQualification) -> str:
    return (qualification.modifier or "").lower()


def _know_how(jd: SFUJobDescription, hay: HaySignalRules) -> HayFactorSignal:
    """Practical/technical depth + managerial scope: required education level,
    advanced/expert skills, excellent-level knowledge, supervisory scope, and the
    breadth of qualification dimensions."""
    points = hay.know_how_points
    counts = hay.know_how_counts
    score = 0.0
    evidence: list[str] = []

    education = [q.text for q in jd.qualifications if q.kind == "education"]
    if _hits(education, hay.edu_high):
        score += points["education_graduate"]
        evidence.append("graduate-level education required")
    elif _hits(education, hay.edu_mid):
        score += points["education_undergraduate"]
        evidence.append("undergraduate degree required")

    advanced = [
        q
        for q in jd.qualifications
        if q.kind == "skill" and _modifier(q) in hay.advanced_skill_modifiers
    ]
    if len(advanced) >= counts["advanced_skills_for_many"]:
        score += points["many_advanced_skills"]
        evidence.append(f"{len(advanced)} advanced/expert skills")
    elif advanced:
        score += points["some_advanced_skills"]
        evidence.append(f"{len(advanced)} advanced/expert skill(s)")

    if any(
        q.kind == "knowledge" and _modifier(q) in hay.excellent_knowledge_modifiers
        for q in jd.qualifications
    ):
        score += points["excellent_knowledge"]
        evidence.append("excellent-level knowledge required")

    if _supervisory(jd):
        score += points["supervisory_scope"]
        evidence.append("supervisory scope")

    kinds = {q.kind for q in jd.qualifications}
    if len(kinds) >= counts["qualification_kinds_for_broad"]:
        score += points["broad_qualifications"]
        evidence.append(f"{len(kinds)} qualification dimensions")

    return _signal(
        "know_how",
        score,
        evidence,
        cutoffs=hay.know_how_levels,
        rationale=(
            "{level} Know-How signal from the depth of required "
            "education/expertise and managerial scope (advisory — not a grade)."
        ),
        cap=hay.evidence_cap,
    )


def _problem_solving(jd: SFUJobDescription, hay: HaySignalRules) -> HayFactorSignal:
    """Thinking challenge: how much independent analysis/judgement the Problem
    Solving section implies, net of routine/closely-supervised language."""
    points = hay.problem_solving_points
    texts = list(jd.problem_solving)
    score = _section_points(texts, points, hay.problem_solving_counts)
    evidence: list[str] = []

    challenge = _hits(texts, hay.ps_challenge)
    routine = _hits(texts, hay.ps_routine)
    score += len(challenge) * points["challenge_hit"]
    score += len(routine) * points["routine_hit"]

    evidence.extend(f'"{phrase}"' for phrase in challenge)
    if routine:
        evidence.append("routine/closely-supervised language present")
    if not texts:
        evidence.append("no Problem Solving section content")

    return _signal(
        "problem_solving",
        score,
        evidence,
        cutoffs=hay.problem_solving_levels,
        rationale=(
            "{level} Problem-Solving signal from the independence "
            "and complexity of the thinking described (advisory — not a grade)."
        ),
        cap=hay.evidence_cap,
    )


def _accountability(jd: SFUJobDescription, hay: HaySignalRules) -> HayFactorSignal:
    """Freedom to act + magnitude of impact: autonomy/impact language in the Impact
    of Decision Making section, supervisory scope, and external breadth."""
    points = hay.accountability_points
    counts = hay.accountability_counts
    texts = list(jd.decision_making)
    score = _section_points(texts, points, counts)
    evidence: list[str] = []

    autonomy = _hits(texts, hay.acc_autonomy)
    score += len(autonomy) * points["autonomy_hit"]
    evidence.extend(f'"{phrase}"' for phrase in autonomy)

    if _supervisory(jd):
        score += points["supervisory_scope"]
        evidence.append("supervises/manages staff")

    external = len(jd.relationships.external) if jd.relationships else 0
    if external >= counts["external_for_breadth"]:
        score += points["external_breadth"]
        evidence.append(f"{external} external relationships (breadth of impact)")

    if not texts:
        evidence.append("no Impact of Decision Making section content")

    return _signal(
        "accountability",
        score,
        evidence,
        cutoffs=hay.accountability_levels,
        rationale=(
            "{level} Accountability signal from the freedom to act "
            "and magnitude of impact described (advisory — not a grade)."
        ),
        cap=hay.evidence_cap,
    )


def _supervisory(jd: SFUJobDescription) -> bool:
    """Does the Relationships section name a supervisory scope at all?"""
    if jd.relationships is None:
        return False
    supervisory = jd.relationships.supervisory
    return bool(supervisory and supervisory.strip())


def estimate_hay_signals(
    jd: SFUJobDescription, *, rules: Rules | None = None
) -> HaySignals:
    """Advisory Hay-factor signals for a JD / canonical role.

    Deterministic, evidence-cited, and explicitly **not a grade** — there is no
    field on :class:`HaySignals` that could hold one.
    """
    hay = (rules if rules is not None else get_rules()).hay_signals
    return HaySignals(
        know_how=_know_how(jd, hay),
        problem_solving=_problem_solving(jd, hay),
        accountability=_accountability(jd, hay),
    )

"""Deterministic job-to-job similarity + clone-vs-new verdict (pure).

Ported from hris ``packages/pipeline/src/pipeline/bank/similarity.py`` (reuse-map,
ADR-005).

Title-agnostic **by construction**: titles are not a term of the score, so "Software
Engineer", "Developer II" and "Applications Programmer" can score as the same role.
Titles are used only to *report* the redundancy (the same-title flag) and to support
the clone verdict. The score combines a summary-embedding cosine, an ontology-aware
skill-set overlap, and a light seniority/education closeness::

    sim = weight_vector * vector
        + weight_skill  * skill_overlap
        + weight_seniority * seniority_closeness

Every weight, threshold, stop-word and fallback is data (``rules/comparison.yaml``,
HR-082 … HR-094) — hris hardcoded all of them. The scorer takes the cosine as a
plain ``float`` argument: it does no retrieval and knows nothing about Neo4j.

⚠ **NOT WIRED TO ANYTHING, DELIBERATELY.** Nothing in JD Bank calls these functions,
and two of them *cannot* be called here yet:

* :func:`skill_overlap` takes a skill-set pair, an **ontology family map** and an
  **idf corpus**. In hris those came from a Neo4j skill graph, a skill ontology
  (family weighting) and an idf table built from résumé matching. JD Bank has none
  of the three: :class:`~src.jd_core.models.parsed_jd.SFUJobDescription` carries no
  skill set at all.
* :func:`seniority_closeness` takes years-of-experience and an education level.
  Neither is a field of a parsed JD.

That is expected and accepted. The hris tests inject those inputs inline, so the
maths ports and tests cleanly, and the integration is deferred to **Phase 3** (dedup
& clustering) — the phase that will have an archive corpus to compute an idf against.
Landing the maths now, with its numbers registered as open HR decisions, is the
point. **Do not invent a skill source, do not scrape prose for an education level or
a years bar, and do not compute an idf corpus to make these callable.**

⚠ **PROVENANCE.** SFU publishes no similarity formula. The weights, the 0.60 noise
floor and the 0.92 clone score are ``hris_calibration``, ``open``. The Toolkit's
actual cloning rule (sfu-reference.md §4, citing Toolkit p10) is an *identity* check
— identical duties + supervisor + title + qualifications — and hris approximated it
with a cosine. A score is not an identity check; :func:`clone_verdict` is advisory
and says so.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

from src.jd_core.models.bank import JDCloneVerdict
from src.jd_core.rules import Comparison, Rules, get_rules

_TITLE_TOKEN = re.compile(r"[a-z0-9]+")


def _comparison(rules: Rules | None) -> Comparison:
    return (rules if rules is not None else get_rules()).comparison


def normalize_title(title: str, *, rules: Rules | None = None) -> str:
    """Lower-case a title and drop punctuation + seniority/level markers, so title
    variants of the same role collapse to one stem ("Senior Developer II" ->
    "developer"). The markers are ``comparison.title_stopwords`` (HR-089)."""
    stopwords = _comparison(rules).title_stopwords
    words = _TITLE_TOKEN.findall(title.lower())
    return " ".join(word for word in words if word not in stopwords)


def skill_overlap(
    source: set[str],
    candidate: set[str],
    families: Mapping[str, frozenset[str]],
    *,
    idf: Mapping[str, float] | None = None,
    rules: Rules | None = None,
) -> float:
    """Ontology-aware, idf-weighted Jaccard over two jobs' canonical skill sets.

    Exact matches score their idf weight; a source skill that only shares a *family*
    with a candidate skill earns ``family_weight`` of its idf (HR-087). Families
    listed in ``non_matchable_families`` grant no credit at all (HR-088) — being
    "some other skill" together is not evidence of anything.

    With ``idf`` supplied, ubiquitous skills (communication, MS Office) contribute
    little and distinctive skills dominate, so two JDs that overlap only on generic
    skills score low. Without it every skill weighs 1 (plain Jaccard). Returns 0 when
    either side has no skills.

    ``families`` and ``idf`` are the caller's to supply — see the module docstring on
    why nothing in JD Bank can supply them yet.
    """
    comparison = _comparison(rules)
    non_matchable = comparison.non_matchable_families
    family_weight = comparison.family_weight

    def weight(skill: str) -> float:
        return idf.get(skill, 1.0) if idf is not None else 1.0

    if not source or not candidate:
        return 0.0
    numerator = sum(weight(s) for s in source & candidate)
    for s in source - candidate:
        source_families = families.get(s, frozenset()) - non_matchable
        if not source_families:
            continue
        if any(
            source_families & (families.get(t, frozenset()) - non_matchable)
            for t in candidate - source
        ):
            numerator += family_weight * weight(s)
    denominator = sum(weight(s) for s in source | candidate)
    return min(1.0, numerator / denominator) if denominator else 0.0


def _education_closeness(a: str | None, b: str | None, comparison: Comparison) -> float:
    """Ordinal closeness of two education levels on the rulebook's one ladder.

    An absent level, or one that is not a rung, is *unknown* — worth
    ``unknown_signal_closeness`` (HR-090), not maximally distant.

    Order matters, and it is hris's: **equality is checked before the ladder**, so two
    roles that state the *same* off-ladder level ("sommelier") are identical on
    education (1.0) rather than mutually unknown (0.7).
    """
    if a is None or b is None:
        return comparison.unknown_signal_closeness
    if a == b:
        return 1.0
    a_ordinal = comparison.education_ordinal(a)
    b_ordinal = comparison.education_ordinal(b)
    if a_ordinal is None or b_ordinal is None:
        return comparison.unknown_signal_closeness
    rungs = len(comparison.education_ladder) - 1
    return max(0.0, 1.0 - abs(a_ordinal - b_ordinal) / rungs)


def seniority_closeness(
    a_years: int | None,
    b_years: int | None,
    a_edu: str | None,
    b_edu: str | None,
    *,
    rules: Rules | None = None,
) -> float:
    """How close two roles sit on experience + education (0-1).

    The two halves are averaged. An unknown experience bar is worth
    ``unknown_signal_closeness``; a known one decays to 0 over
    ``experience_span_years`` (HR-091) years of gap.
    """
    comparison = _comparison(rules)
    if a_years is None or b_years is None:
        years_closeness = comparison.unknown_signal_closeness
    else:
        gap = abs(a_years - b_years) / comparison.experience_span_years
        years_closeness = 1.0 - min(1.0, gap)
    education = _education_closeness(a_edu, b_edu, comparison)
    return (years_closeness + education) / 2.0


def score_job_similarity(
    vector_score: float,
    skill_ov: float,
    seniority: float,
    *,
    rules: Rules | None = None,
) -> float:
    """Combine the three components into the overall similarity (0-1).

    ``vector_score`` is a plain cosine the caller computed (Neo4j's vector index, in
    Phase 3); this function does no retrieval. It is clamped to [0, 1] — an
    out-of-range cosine cannot inflate the score past a threshold. The weights sum to
    1.0 (the loader enforces it), so the result is a 0-1 number the thresholds below
    are comparable against.
    """
    comparison = _comparison(rules)
    vector = max(0.0, min(1.0, vector_score))
    return round(
        comparison.weight_vector * vector
        + comparison.weight_skill * skill_ov
        + comparison.weight_seniority * seniority,
        4,
    )


def clone_verdict(
    score: float,
    *,
    same_title: bool,
    same_department: bool,
    rules: Rules | None = None,
) -> tuple[JDCloneVerdict, list[str]]:
    """Approximate the Toolkit's clone-vs-new decision from the available signals.

    Full identity (duties / supervisor / qualifications) is not known at this stage,
    so this is **advisory**: near-identical + same title + same department reads as a
    clone; a strong match under a different title or department reads as a new job
    that needs a Hay evaluation; anything else is uncertain and a human should look.

    Returns ``(verdict, basis)`` — the basis is the human-readable "why".
    """
    comparison = _comparison(rules)
    basis = [
        "same department" if same_department else "different department",
        "same title" if same_title else "different title",
    ]
    if score >= comparison.clone_threshold and same_title and same_department:
        basis.append("near-identical role - likely a true clone (no re-evaluation)")
        return "clone", basis
    if score >= comparison.sim_threshold and (not same_title or not same_department):
        basis.append(
            "same role under a different title/department - needs Hay evaluation"
        )
        return "new_job", basis
    return "uncertain", basis

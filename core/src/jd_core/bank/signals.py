"""The pure ``ParsedJD -> JobSignals`` adapter + the title normalizer (Phase 3.4a).

The 2.4c comparison trio — :mod:`~src.jd_core.bank.similarity`,
:mod:`~src.jd_core.bank.clustering`, :mod:`~src.jd_core.bank.drift` — landed as pure,
tested maths **deliberately not wired to anything**: their inputs (a skill set per JD,
a structured education level, a years bar, a supervisory count, a normalized title) do
not exist on a :class:`~src.jd_core.models.parsed_jd.SFUJobDescription`, which carries
only free-text qualifications. This module is the adapter that produces them, so 3.4b's
Tier-3 role-equivalence runner has a single feature object to consume.

**It is PURE** (ADR-006 / non-negotiable #2): it reads only the rulebook and the parsed
JD, does no I/O, no DB, no Neo4j, and imports no ``jd_bank`` (the layering ratchet). It
does not compute an idf corpus, generate candidates, apply a hard constraint or a Tier-3
threshold — all of that is 3.4b.

The two design calls it embodies are ADR-007 / HR-149…HR-153, and both are honest
degradations from hris's ontology-backed pipeline, registered as such:

* **skills are a keyword bag, not a canonical skill set.** SFU publishes no skill
  ontology and the archive's skill vocabulary is 5,584 free-text tokens; building an
  ontology is a project of its own. So ``JobSignals.skills`` is lowercase ``[a-z0-9]+``
  tokens from the ``skill``/``knowledge``/``ability`` quals minus a measured stopword
  list — and it is ``frozenset()`` for the ~41% of JDs with no qualifications.
  idf-weighting (what rescues the bag into signal) is 3.4b.
* **seniority is read from prose.** Education (over all qual text, because JDFN hides
  the degree in the ``knowledge`` blob), the experience bar (digits *and* spelled-out
  years), and the supervisory count come from the drift text helpers. Each is ``None``
  when the JD states nothing readable.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from src.jd_core.bank.drift import (
    education_level_from_quals,
    experience_years_from_text,
    supervisory_reports_from_text,
)
from src.jd_core.bank.similarity import normalize_title
from src.jd_core.bank.title_family import classify_title
from src.jd_core.models.bank import CanonicalTitle, JobSignals
from src.jd_core.models.parsed_jd import SFUJobDescription, SFUQualification
from src.jd_core.rules import Comparison, Rules, Titles, get_rules
from src.jd_core.textnorm import fold

#: A skill token: a maximal run of lowercase letters/digits, exactly the alphabet
#: ``similarity.normalize_title`` tokenizes titles with. Kept local (a keyword bag is a
#: different thing from a title stem) rather than shared, so retuning one cannot
#: silently move the other.
_SKILL_TOKEN = re.compile(r"[a-z0-9]+")


def _title_is_restricted(title: str, titles: Titles) -> bool:
    """Does ``title`` use one of SFU's reserved title phrases (``titles.yaml ::
    restricted``, Part 3.5)?

    Reuses the rulebook's restricted phrases and reads the title through the same fold
    the validators read a JD through (:mod:`src.jd_core.textnorm`), so a non-breaking
    space or typographic punctuation cannot hide a reserved phrase the title
    demonstrably carries. It does NOT re-implement the phrase catalog or apply the
    ``reserved_for_employee_group`` gate — that context-dependent check stays in the
    validators; here we report only whether a reserved phrase is present.

    Intended semantics: a substring match through the fold (folded needle in folded
    title), NOT a byte-identical copy of the validators' raw-or-folded union — for a
    title the two coincide on all three real reserved phrases; the simpler leaf wins."""
    folded_title = fold(title, join_paragraphs=True, casefold=True)
    return any(
        fold(restricted.phrase, join_paragraphs=True, casefold=True) in folded_title
        for restricted in titles.restricted
    )


def canonical_title(
    title: str, *, has_supervisory: bool = False, rules: Rules | None = None
) -> CanonicalTitle:
    """A title reduced to its comparison anchors — the normalized stem, both SFU title
    dimensions, the comma-format supervision signal, and the reserved-phrase flag.

    Composes ``similarity.normalize_title`` (the title-agnostic stem the similarity
    score uses), ``title_family.classify_title`` (seniority family + functional
    function + the "Manager, X" comma signal), and the ``titles.yaml :: restricted``
    presence check. ``has_supervisory`` is what the caller knows about the role's
    reports from outside the title; ``classify_title`` ORs it with the comma format.
    """
    active = rules if rules is not None else get_rules()
    classification = classify_title(
        title, has_supervisory=has_supervisory, rules=active
    )
    return CanonicalTitle(
        raw=title,
        normalized=normalize_title(title, rules=active),
        family=classification.family.family,
        function=classification.function.function,
        comma_supervisory=classification.comma_supervisory,
        restricted=_title_is_restricted(title, active.titles),
    )


def _skill_bag(
    quals: Iterable[SFUQualification], comparison: Comparison
) -> frozenset[str]:
    """The keyword bag: lowercase tokens of the registered skill-source quals, minus
    the measured stopwords and tokens below ``skill_min_token_len``. Empty when the JD
    has no quals of those kinds -- the honest, registered ~41%-of-archive case."""
    kinds = comparison.skill_source_kinds
    stopwords = comparison.skill_stopwords
    min_len = comparison.skill_min_token_len
    tokens: set[str] = set()
    for qual in quals:
        if qual.kind not in kinds:
            continue
        for token in _SKILL_TOKEN.findall(qual.text.lower()):
            if len(token) < min_len or token in stopwords:
                continue
            tokens.add(token)
    return frozenset(tokens)


def _experience_years(
    quals: list[SFUQualification], comparison: Comparison, *, rules: Rules
) -> int | None:
    """The experience bar, in years, over ``comparison.experience_source_kinds``
    (HR-154) IN ORDER: the first kind that yields any count wins — ``experience`` quals
    are authoritative and ``knowledge`` is the JDFN fallback (the years live in the same
    blob as the degree). Within the winning kind the heuristic is the MAX count, so a JD
    that states several bars is taken at its most senior. Which kinds, and their
    fallback order, are rulebook DATA — not a literal tuple here."""
    for kind in comparison.experience_source_kinds:
        found = [
            years
            for qual in quals
            if qual.kind == kind
            for years in (experience_years_from_text(qual.text, rules=rules),)
            if years is not None
        ]
        if found:
            return max(found)
    return None


def build_job_signals(
    jd: SFUJobDescription, *, rules: Rules | None = None
) -> JobSignals:
    """The single comparison-feature object for a parsed SFU JD (see the module + the
    :class:`~src.jd_core.models.bank.JobSignals` docstrings for the honest degradations
    this embodies). Pure and deterministic: same JD in, same signals out."""
    active = rules if rules is not None else get_rules()
    comparison = active.comparison
    quals = jd.qualifications

    supervisory_text = (
        jd.relationships.supervisory if jd.relationships is not None else None
    )
    has_supervisory = bool(supervisory_text)
    supervisory_reports = (
        supervisory_reports_from_text(supervisory_text, rules=active)
        if supervisory_text
        else None
    )
    title = canonical_title(jd.title, has_supervisory=has_supervisory, rules=active)

    return JobSignals(
        skills=_skill_bag(quals, comparison),
        education_ordinal=education_level_from_quals(quals, rules=active),
        experience_years=_experience_years(quals, comparison, rules=active),
        supervisory_reports=supervisory_reports,
        title=jd.title,
        normalized_title=title.normalized,
        family=title.family,
        function=title.function,
        comma_supervisory=title.comma_supervisory,
        restricted=title.restricted,
        employee_group=jd.employee_group,
        department=jd.department,
    )

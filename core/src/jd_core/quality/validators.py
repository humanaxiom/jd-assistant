"""Deterministic JD-quality validators, aligned to SFU's official standards.

The heart of JD Bank. These rules check a JD parsed into the SFU template
(:class:`~src.jd_core.models.parsed_jd.SFUJobDescription`) plus its raw text
against the **SFU Job Description Toolkit**: the mandatory template sections, the
3-5 action-verb duty format, the knowledge/skills modifiers, the
"minimum-not-desired" qualification rules, the official gender-neutral lexicon,
the Part-11.6 "never approve" gates, the Part 2-3 authoring gates, and
leftover-placeholder detection.

Ported faithfully from hris ``packages/pipeline/src/pipeline/quality/jd_rules.py``
(``RULES_VERSION = "jd_rules_sfu_v3"``), with one structural change: **not one
rule datum lives here.** Every threshold, verb, coded term, marker, regex,
severity, section and message string is read from :func:`~src.jd_core.rules.
get_rules` (CLAUDE.md non-negotiable #2). This module is pure logic over that
data — same input, same issues, no I/O, no model call. The LLM pass (Phase 5)
adds nuanced, cited findings *on top*; it never replaces these.

The rules version is ``get_rules().version`` — there is no constant here to drift.
"""

from __future__ import annotations

import itertools
import re
from collections.abc import Sequence
from typing import Any

from src.jd_core.models.parsed_jd import SFUJobDescription
from src.jd_core.models.quality import JDIssueSeverity, JDQualityIssue
from src.jd_core.rules import Rules, get_rules

_DEFAULT_VARIANT = "default"


def _context(text: str, term: str, *, window: int) -> str | None:
    """Short verbatim snippet of ``text`` around the first match of ``term``.

    Word-boundary match for a single word, plain substring for a multi-word term
    (mirroring hris). ``None`` when the term is absent. Ellipses mark truncation,
    so the snippet is never mistaken for the whole sentence.
    """
    pattern = re.escape(term)
    if " " not in term:
        pattern = rf"\b{pattern}\b"
    match = re.search(pattern, text, flags=re.IGNORECASE)
    if match is None:
        return None
    start = max(0, match.start() - window)
    end = min(len(text), match.end() + window)
    snippet = text[start:end].strip()
    return f"{'…' if start > 0 else ''}{snippet}{'…' if end < len(text) else ''}"


def _listed(items: Sequence[str], *, limit: int, separator: str = ", ") -> str:
    """Join at most ``limit`` items, marking truncation with an ellipsis.

    A finding names a bounded *sample* of the offenders, never the whole list.
    ``JDQualityIssue.message`` and ``.evidence`` are capped at 500 characters, and
    a table-heavy or badly-extracted archive document can yield hundreds of
    matches — hris joins the duty %-allocations unbounded, so such a document
    makes ``evaluate_jd_rules`` raise a pydantic ``ValidationError``. The
    validator is the oracle (CLAUDE.md #3) and is a pure function over JD text: it
    must never raise on one. ``limit`` is the rulebook's ``thresholds.max_listed``
    — the cap hris already applies to the action-verb list, applied here too.
    """
    head = separator.join(items[:limit])
    return f"{head}{separator}…" if len(items) > limit else head


def _base_context(rules: Rules) -> dict[str, Any]:
    """Placeholders every message template may interpolate (the thresholds)."""
    return rules.thresholds.model_dump()


def _issue(
    rules: Rules,
    rule_id: str,
    *,
    variant: str = _DEFAULT_VARIANT,
    severity: JDIssueSeverity | None = None,
    evidence: str | None = None,
    **values: Any,
) -> JDQualityIssue:
    """Build one finding from the catalog.

    The catalog is the single source of truth for the issue's ``category``, its
    wording, and — unless the call site knows better (only the coded-term tiers
    and the restricted titles do) — its ``severity``. The call site supplies just
    the computed values the template interpolates.
    """
    spec = rules.rule_catalog.spec(rule_id)
    message, recommendation = spec.render(variant, {**_base_context(rules), **values})
    return JDQualityIssue(
        category=spec.category,
        severity=severity if severity is not None else spec.default_severity,
        source="rule",
        message=message,
        suggestion=recommendation,
        evidence=evidence,
        rule_id=rule_id,
    )


def _completeness(sfu: SFUJobDescription, rules: Rules) -> list[JDQualityIssue]:
    """The mandatory SFU template sections are all present (Part 2)."""
    out: list[JDQualityIssue] = []
    if not (sfu.position_summary and sfu.position_summary.strip()):
        out.append(_issue(rules, "SFU-COMP-SUMMARY"))
    if not sfu.duties:
        out.append(_issue(rules, "SFU-COMP-DUTIES"))
    if not sfu.decision_making:
        out.append(_issue(rules, "SFU-COMP-DECISION"))
    if not sfu.problem_solving:
        out.append(_issue(rules, "SFU-COMP-PROBLEM"))
    rel = sfu.relationships
    if rel is None or not (rel.supervisory or rel.internal or rel.external):
        out.append(_issue(rules, "SFU-COMP-RELATIONSHIPS"))
    if not sfu.qualifications:
        out.append(_issue(rules, "SFU-COMP-QUALS"))
    if not sfu.about_sfu_present:
        out.append(_issue(rules, "SFU-COMP-ABOUT"))
    if not sfu.territorial_acknowledgement_present:
        out.append(_issue(rules, "SFU-COMP-TERRITORIAL"))
    if not sfu.employment_equity_present:
        out.append(_issue(rules, "SFU-COMP-EDI"))
    return out


def _leading_verb(duty_action_verb: str, statement: str) -> str:
    """The duty's leading word — its ``action_verb`` when set, else the first word
    of the statement — lowercased and stripped of trailing punctuation."""
    word = (duty_action_verb or statement).strip().split(" ", 1)[0]
    return word.strip(",.;:").lower()


def _structure(
    sfu: SFUJobDescription, raw_text: str, rules: Rules
) -> list[JDQualityIssue]:
    """The SFU format: summary length, 3-5 action-verb duties with how/why, and
    no leftover template instructional text."""
    out: list[JDQualityIssue] = []
    thresholds = rules.thresholds

    summary = (sfu.position_summary or "").strip()
    if summary:
        words = len(summary.split())
        if words < thresholds.summary_min_words or words > thresholds.summary_max_words:
            out.append(_issue(rules, "SFU-STRUCT-SUMMARY-LENGTH", words=words))

    n = len(sfu.duties)
    if 0 < n < thresholds.duties_min:
        out.append(_issue(rules, "SFU-STRUCT-DUTIES-COUNT", variant="too_few", count=n))
    elif n > thresholds.duties_max:
        out.append(
            _issue(rules, "SFU-STRUCT-DUTIES-COUNT", variant="too_many", count=n)
        )

    approved = rules.action_verbs.approved
    bad_verbs = [
        verb
        for d in sfu.duties
        if (verb := _leading_verb(d.action_verb, d.statement)) and verb not in approved
    ]
    if bad_verbs:
        named = ", ".join(sorted(set(bad_verbs))[: thresholds.max_listed])
        out.append(_issue(rules, "SFU-STRUCT-ACTION-VERB", verbs=named))

    missing_how_why = sum(1 for d in sfu.duties if not d.how_why)
    if missing_how_why:
        out.append(_issue(rules, "SFU-STRUCT-HOW-WHY", count=missing_how_why))

    for marker in rules.markers.placeholder:
        evidence = _context(raw_text, marker, window=thresholds.evidence_context_window)
        if evidence is not None:
            out.append(_issue(rules, "SFU-STRUCT-PLACEHOLDER", evidence=evidence))
            break  # one finding is enough

    return out


def _qualifications(
    sfu: SFUJobDescription, raw_text: str, rules: Rules
) -> list[JDQualityIssue]:
    """The Toolkit's qualification standards: proficiency modifiers from the
    approved vocabulary, an equivalent-combination path, the minimum (not the
    desired) bar, and a degree that names a discipline."""
    out: list[JDQualityIssue] = []
    quals = rules.qualifications
    window = rules.thresholds.evidence_context_window

    skills_no_modifier = sum(
        1 for q in sfu.qualifications if q.kind == "skill" and not q.modifier
    )
    if skills_no_modifier:
        out.append(_issue(rules, "SFU-QUAL-SKILL-MODIFIER", count=skills_no_modifier))

    bad_skill_mods = [
        q.modifier
        for q in sfu.qualifications
        if q.kind == "skill"
        and q.modifier
        and q.modifier.lower() not in quals.skill_modifiers
    ]
    bad_knowledge_mods = [
        q.modifier
        for q in sfu.qualifications
        if q.kind == "knowledge"
        and q.modifier
        and q.modifier.lower() not in quals.knowledge_modifiers
    ]
    if bad_skill_mods or bad_knowledge_mods:
        out.append(_issue(rules, "SFU-QUAL-MODIFIER-VOCAB"))

    haystack = raw_text.casefold()
    qual_text = " ".join(q.text for q in sfu.qualifications).casefold()
    equivalent = quals.equivalent_combination
    if equivalent not in haystack and equivalent not in qual_text:
        out.append(_issue(rules, "SFU-QUAL-EQUIVALENT"))

    for phrase in quals.banned_phrases:
        evidence = _context(raw_text, phrase, window=window)
        if evidence is not None:
            out.append(
                _issue(
                    rules,
                    "SFU-QUAL-BANNED-PHRASE",
                    evidence=evidence,
                    phrase=phrase,
                )
            )

    mentions_degree = rules.patterns.degree_mention.search(raw_text)
    allows_related = rules.patterns.related_discipline.search(raw_text)
    if mentions_degree and not allows_related:
        out.append(_issue(rules, "SFU-QUAL-DEGREE-DISCIPLINE"))

    return out


def _inclusive_language(raw_text: str, rules: Rules) -> list[JDQualityIssue]:
    """SFU's official gender-neutral lexicon (Part 6). The severity is the tier
    the term is filed under in ``coded_terms.yaml`` — never named here."""
    out: list[JDQualityIssue] = []
    window = rules.thresholds.evidence_context_window
    for severity, terms in rules.coded_terms.tiers:
        for term, fix in terms.items():
            evidence = _context(raw_text, term, window=window)
            if evidence is None:
                continue
            out.append(
                _issue(
                    rules,
                    "SFU-LANG-CODED",
                    severity=severity,
                    evidence=evidence,
                    term=term,
                    fix=fix,
                )
            )
    return out


def _quality_gates(
    sfu: SFUJobDescription, raw_text: str, rules: Rules
) -> list[JDQualityIssue]:
    """SFU "never approve" gates (Learning Series Part 11.6) not covered
    elsewhere: duty %-allocations that don't total 100, KSAs out of K->S->A order,
    a reserved "Senior" prefix without supervisory scope, and the missing
    standardized Relationships header."""
    out: list[JDQualityIssue] = []
    thresholds = rules.thresholds

    # (a) Per-duty time allocations use the template's "(NN%)" format and must sum
    # to 100. Only parenthesized percentages count (precise -> few false positives).
    allocations = [int(m) for m in rules.patterns.duty_allocation.findall(raw_text)]
    total = sum(allocations)
    if len(allocations) >= thresholds.duty_allocation_min_count and not (
        thresholds.duty_allocation_total_min
        <= total
        <= thresholds.duty_allocation_total_max
    ):
        out.append(
            _issue(
                rules,
                "SFU-GATE-DUTY-PCT",
                evidence=_listed(
                    [f"{a}%" for a in allocations],
                    limit=thresholds.max_listed,
                    separator=" + ",
                ),
                total=total,
            )
        )

    # (b) Qualifications must run Knowledge -> Skills -> Abilities (Part 5.4).
    ksa_rank = rules.qualifications.ksa_rank
    ranks = [ksa_rank[q.kind] for q in sfu.qualifications if q.kind in ksa_rank]
    if any(earlier > later for earlier, later in itertools.pairwise(ranks)):
        out.append(_issue(rules, "SFU-GATE-KSA-ORDER"))

    # (c) "Senior" is reserved for roles supervising junior peers (Part 3.5).
    rel = sfu.relationships
    supervises = bool(rel is not None and rel.supervisory and rel.supervisory.strip())
    if rules.patterns.senior_title.search(sfu.title) and not supervises:
        out.append(_issue(rules, "SFU-GATE-SENIOR-TITLE"))

    # (d) The standardized Relationships header boilerplate must be present.
    if rules.markers.relationships_header not in raw_text.casefold():
        out.append(_issue(rules, "SFU-GATE-REL-HEADER"))

    return out


def _authoring_gates(sfu: SFUJobDescription, rules: Rules) -> list[JDQualityIssue]:
    """SFU authoring gates (Learning Series Parts 2-3): the Position Summary
    carries neither working conditions nor incumbent-focused language, abilities
    read as observable behaviour, and restricted titles are used only in their
    reserved context.

    Conservative and high-signal: a restriction whose context the JD alone cannot
    settle is raised at the advisory severity ``titles.yaml`` files it under.
    """
    out: list[JDQualityIssue] = []
    summary = sfu.position_summary or ""
    window = rules.thresholds.evidence_context_window

    # Working conditions don't belong in the Position Summary (Part 2B / 11.6).
    marker = next(
        (m for m in rules.markers.working_conditions if m in summary.casefold()), None
    )
    if marker is not None:
        out.append(
            _issue(
                rules,
                "SFU-AUTH-SUMMARY-CONDITIONS",
                evidence=_context(summary, marker, window=window),
            )
        )

    # Position-not-incumbent: first-person signals incumbent-focused writing (2B).
    if rules.patterns.incumbent.search(summary):
        out.append(_issue(rules, "SFU-AUTH-SUMMARY-INCUMBENT"))

    # Abilities must read as observable behaviour (Part 5.3): "Ability to <verb>…".
    prefixes = tuple(rules.qualifications.ability_prefixes)
    bad_abilities = [
        q.text
        for q in sfu.qualifications
        if q.kind == "ability" and not q.text.strip().casefold().startswith(prefixes)
    ]
    if bad_abilities:
        out.append(
            _issue(rules, "SFU-AUTH-ABILITIES-OBSERVABLE", count=len(bad_abilities))
        )

    # Restricted titles (Part 3.5). A restriction with a `reserved_for_employee_group`
    # is checkable from the JD (and only fires when the group is known and wrong);
    # the rest need context we can't verify, so they are advisory.
    title_low = sfu.title.casefold()
    for title in rules.titles.restricted:
        if title.phrase not in title_low:
            continue
        group = title.reserved_for_employee_group
        if group is not None and (
            not sfu.employee_group or sfu.employee_group == group
        ):
            continue
        out.append(
            _issue(
                rules,
                title.rule_id,
                severity=title.severity,
                employee_group=sfu.employee_group,
            )
        )
    return out


def evaluate_jd_rules(
    sfu: SFUJobDescription, raw_text: str, *, rules: Rules | None = None
) -> list[JDQualityIssue]:
    """Run every SFU-aligned deterministic rule over a parsed JD + its raw text.

    Pure: no I/O, no model call, no mutation of ``sfu``. Same input -> same
    issues, in a stable order (completeness, structure, qualifications, inclusive
    language, quality gates, authoring gates). ``rules`` defaults to the shipped,
    cached rulebook; pass one to evaluate against a different rules version.
    """
    rules = rules if rules is not None else get_rules()
    issues: list[JDQualityIssue] = []
    issues += _completeness(sfu, rules)
    issues += _structure(sfu, raw_text, rules)
    issues += _qualifications(sfu, raw_text, rules)
    issues += _inclusive_language(raw_text, rules)
    issues += _quality_gates(sfu, raw_text, rules)
    issues += _authoring_gates(sfu, rules)
    return issues

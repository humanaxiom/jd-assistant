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

**Every scan reads the JD through the fold** (:mod:`src.jd_core.textnorm`) — the coded
terms, the banned qualification phrases, the placeholder markers, the
working-condition markers, the restricted titles, the Relationships header, the
equivalency path, the action-verb glossary, the modifier vocabulary and the rulebook's
own regexes. Each matches the JD *as a human reads it* as well as *as it was written*;
the union is deliberate (:func:`_find`), and **evidence is always sliced from the
original text**, so a finding's quoted context still points at the JD's own bytes.

Two very different things fold, and their impact on the real archive could hardly be
more different — do not conflate them (CLAUDE.md #6):

* **Invisible / typographic characters.** In code the hole was total: one U+200B
  inside a word and ``(?<!\\w)compassionate(?!\\w)`` matched nothing at all. **On the
  archive it moves ~nothing** — 600 sampled ``.docx`` carry zero format characters and
  not one changes its findings. Correct hardening; not the reason the baseline moves.
* **Whitespace-run collapsing.** This is the behavioural change: ``antiword`` hard-wraps
  the legacy ``.doc`` corpus, so ``SFU-QUAL-EQUIVALENT`` fired on 9.75% of legacy JDs
  that plainly contain the equivalency path (74 -> 35 on a 400-document sample; +3 real
  findings the wrap had hidden). Its SCOPE is a decision, and the one piece of the fold
  that is rule data (``textnorm.collapse_across_paragraph_break``, HR-108): a wrap
  collapses, a paragraph break does not, because joining unrelated paragraphs *invents*
  findings — including a trip of the non-overridable no-placeholders gate.

The rules version is ``get_rules().version`` — there is no constant here to drift.
"""

from __future__ import annotations

import itertools
import re
from collections.abc import Sequence
from typing import Any

from src.jd_core.models.parsed_jd import SFUJobDescription
from src.jd_core.models.quality import JDIssueSeverity, JDQualityIssue
from src.jd_core.quality.boilerplate import redact_passages
from src.jd_core.rules import Rules, get_rules
from src.jd_core.textnorm import FoldedText, fold, fold_text

_DEFAULT_VARIANT = "default"


def _anchor(term: str) -> str:
    """The search pattern for ``term`` — anchored only where anchoring means
    something.

    A multi-word term is a plain substring (mirroring hris). A single-word term is
    boundary-anchored so ``assets`` does not match inside ``reassessment`` — but
    **only at an edge that is alphanumeric**.

    DELIBERATE DEVIATION FROM hris: hris wraps every space-free marker in
    ``\\b…\\b``, which is simply wrong when the marker's edge is not a word
    character, and it silently kills two of the seven placeholder markers:

    * ``\\b\\[insert`` can only match when a *word* character precedes the ``[``,
      so ``[insert department]`` at the start of a line — the exact thing an
      unfinished draft contains — never fires;
    * ``____\\b`` requires a non-word character after the 4th underscore, but
      ``_`` *is* a word character, so any run of 5+ underscores (i.e. every real
      fill-in line) never fires.

    ``SFU-STRUCT-PLACEHOLDER`` feeds a **non-overridable** approval gate, so a
    marker that cannot fire is a false safety guarantee, not a cosmetic bug.
    ``(?<!\\w)x(?!\\w)`` is equivalent to ``\\bx\\b`` for an alphanumeric-edged
    term, so every alphabetic term (the coded lexicon, the banned qualification
    phrases, the working-condition markers) matches bit-identically to before.
    """
    pattern = re.escape(term)
    if " " in term:
        return pattern
    if term[:1].isalnum():
        pattern = rf"(?<!\w){pattern}"
    if term[-1:].isalnum():
        pattern = rf"{pattern}(?!\w)"
    return pattern


def _find(
    text: FoldedText, term: str, *, anchored: bool = True
) -> tuple[int, int] | None:
    """The earliest span of ``text`` where ``term`` occurs — ``None`` if it does not.

    **The span is in the coordinates of the ORIGINAL text**, never of the folded
    rendering of it, so every position and evidence snippet a finding reports still
    points at the JD's own bytes.

    ``term`` is looked for twice: once in the JD **as written**, once in the JD **as
    a human reads it** (:mod:`src.jd_core.textnorm` — zero-width characters and soft
    hyphens gone, whitespace collapsed, smart quotes and ligatures folded to ASCII).
    The result is the union, and the union is load-bearing in **both** directions:

    * The folded pass is the fix. ``(?<!\\w)compassionate(?!\\w)`` does not match
      ``comp<U+200B>assionate``, and ``may include`` does not match ``may\\ninclude``,
      which is how ``antiword`` renders half the legacy archive.
    * The raw pass is what makes THIS FUNCTION a **strict superset** of the old
      matcher. Folding away an invisible character can, in a contrived document,
      *remove* a match the raw text had: ``assets<U+200B>management`` contains the word
      ``assets`` bounded by a non-word character, but folds to ``assetsmanagement``,
      which does not. Scanning the raw text as well means nothing the old matcher
      caught can go missing here.

    Two honest limits on that "superset", both verified:

    * It is a property of **this matcher**, not of the report. With the HR-058
      exemption on, the widened fold correctly matches a mandated passage that carries
      an invisible character, which the old redactor could not — so ~26 exempted
      ``SFU-LANG-CODED`` findings *disappear* archive-wide. Correct, and not a superset.
    * The union still misses ``asse<U+200B>ts<U+200B>management``: the raw pass sees no
      bounded ``assets``, and the fold destroys the boundary. Arguably right (a reader
      sees ``assetsmanagement``), but it is not exhaustive and should not be sold as
      such.
    """
    spans: list[tuple[int, int]] = []
    pattern = _anchor if anchored else re.escape
    if term:
        written = re.search(pattern(term), text.raw, flags=re.IGNORECASE)
        if written is not None:
            spans.append((written.start(), written.end()))
    # A term that folds to nothing would match at every index; the rulebook cannot hold
    # one (the loader rejects it), and the matcher does not rely on that. A rule term is
    # one line, so HR-108 cannot change how it folds.
    needle = fold(term, join_paragraphs=True)
    if needle:
        read = re.search(pattern(needle), text.folded, flags=re.IGNORECASE)
        if read is not None:
            spans.append(text.to_raw(read.start(), read.end()))
    return min(spans) if spans else None


def _present(text: FoldedText, phrase: str) -> bool:
    """Does ``phrase`` occur in ``text``, as a plain case-insensitive substring?

    Unanchored, mirroring the ``phrase in text.casefold()`` checks this replaces (the
    equivalency path, the Relationships header, the working-condition markers, the
    restricted titles) — but read through the fold, so a non-breaking space or a
    line-wrap no longer hides text the JD demonstrably contains.
    """
    return _find(text, phrase, anchored=False) is not None


def _searches(text: FoldedText, pattern: re.Pattern[str]) -> bool:
    """Does the rulebook's compiled ``pattern`` match ``text``, written or read?

    The pattern keeps its own ``ignore_case`` flag (``patterns.yaml``) — which is why
    :func:`~src.jd_core.textnorm.fold_text` does **not** casefold: folding the case
    away here would silently override a rule that asked to be case-sensitive.
    """
    return (
        pattern.search(text.raw) is not None or pattern.search(text.folded) is not None
    )


def _context(text: FoldedText, term: str, *, window: int) -> str | None:
    """Short verbatim snippet of the ORIGINAL text around the first match of ``term``.

    ``None`` when the term is absent. Ellipses mark truncation, so the snippet is
    never mistaken for the whole sentence.

    The window is measured, and the snippet is cut, in the original text's own
    coordinates (:func:`_find`). A term found only in folded space therefore still
    quotes the JD verbatim — invisible characters and all — instead of a normalized
    paraphrase of it that no reviewer could locate in the document.
    """
    span = _find(text, term)
    if span is None:
        return None
    start = max(0, span[0] - window)
    end = min(len(text.raw), span[1] + window)
    snippet = text.raw[start:end].strip()
    return f"{'…' if start > 0 else ''}{snippet}{'…' if end < len(text.raw) else ''}"


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


def _join(rules: Rules) -> bool:
    """HR-108: may a term match across a paragraph break? One home, read from it."""
    return rules.textnorm.collapse_across_paragraph_break


def _fold_jd(text: str, rules: Rules) -> FoldedText:
    """A piece of the JD, folded under the rulebook's normalization policy."""
    return fold_text(text, join_paragraphs=_join(rules))


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


def _leading_verb(duty_action_verb: str, statement: str, rules: Rules) -> str:
    """The duty's leading word — its ``action_verb`` when set, else the first word
    of the statement — lowercased and stripped of trailing punctuation.

    Read through the fold, so ``Man<U+200B>ages`` is the approved verb ``manages``
    rather than an unrecognised word the JD gets marked down for. (Folding collapses
    whitespace too, so a statement that line-wraps immediately after its verb now
    yields the verb rather than ``verb\\nnext-word``.)
    """
    word = fold(duty_action_verb or statement, join_paragraphs=_join(rules))
    return word.split(" ", 1)[0].strip(",.;:").lower()


def _structure(
    sfu: SFUJobDescription, text: FoldedText, rules: Rules
) -> list[JDQualityIssue]:
    """The SFU format: summary length, 3-5 action-verb duties with how/why, and
    no leftover template instructional text."""
    out: list[JDQualityIssue] = []
    thresholds = rules.thresholds

    # Two-sided, but two DIFFERENT rules: SFU's never-approve list names only the
    # over-run (the maximum), so the over- and under-run carry distinct rule_ids and
    # the approval policy can gate one without the other. Same triggers, same
    # severities as the two-sided rules they replace.
    summary = (sfu.position_summary or "").strip()
    if summary:
        words = len(summary.split())
        if words < thresholds.summary_min_words:
            out.append(_issue(rules, "SFU-STRUCT-SUMMARY-TOO-SHORT", words=words))
        elif words > thresholds.summary_max_words:
            out.append(_issue(rules, "SFU-STRUCT-SUMMARY-TOO-LONG", words=words))

    n = len(sfu.duties)
    if 0 < n < thresholds.duties_min:
        out.append(_issue(rules, "SFU-STRUCT-DUTIES-TOO-FEW", count=n))
    elif n > thresholds.duties_max:
        out.append(_issue(rules, "SFU-STRUCT-DUTIES-TOO-MANY", count=n))

    approved = rules.action_verbs.approved
    bad_verbs = [
        verb
        for d in sfu.duties
        if (verb := _leading_verb(d.action_verb, d.statement, rules))
        and verb not in approved
    ]
    if bad_verbs:
        named = ", ".join(sorted(set(bad_verbs))[: thresholds.max_listed])
        out.append(_issue(rules, "SFU-STRUCT-ACTION-VERB", verbs=named))

    missing_how_why = sum(1 for d in sfu.duties if not d.how_why)
    if missing_how_why:
        out.append(_issue(rules, "SFU-STRUCT-HOW-WHY", count=missing_how_why))

    for marker in rules.markers.placeholder:
        evidence = _context(text, marker, window=thresholds.evidence_context_window)
        if evidence is not None:
            out.append(_issue(rules, "SFU-STRUCT-PLACEHOLDER", evidence=evidence))
            break  # one finding is enough

    return out


def _qualifications(
    sfu: SFUJobDescription, text: FoldedText, rules: Rules
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
        and fold(q.modifier, join_paragraphs=_join(rules)).lower()
        not in quals.skill_modifiers
    ]
    bad_knowledge_mods = [
        q.modifier
        for q in sfu.qualifications
        if q.kind == "knowledge"
        and q.modifier
        and fold(q.modifier, join_paragraphs=_join(rules)).lower()
        not in quals.knowledge_modifiers
    ]
    if bad_skill_mods or bad_knowledge_mods:
        out.append(_issue(rules, "SFU-QUAL-MODIFIER-VOCAB"))

    qual_text = _fold_jd(" ".join(q.text for q in sfu.qualifications), rules)
    equivalent = quals.equivalent_combination
    if not (_present(text, equivalent) or _present(qual_text, equivalent)):
        out.append(_issue(rules, "SFU-QUAL-EQUIVALENT"))

    for phrase in quals.banned_phrases:
        evidence = _context(text, phrase, window=window)
        if evidence is not None:
            out.append(
                _issue(
                    rules,
                    "SFU-QUAL-BANNED-PHRASE",
                    evidence=evidence,
                    phrase=phrase,
                )
            )

    mentions_degree = _searches(text, rules.patterns.degree_mention)
    allows_related = _searches(text, rules.patterns.related_discipline)
    if mentions_degree and not allows_related:
        out.append(_issue(rules, "SFU-QUAL-DEGREE-DISCIPLINE"))

    return out


def _inclusive_language(raw_text: str, rules: Rules) -> list[JDQualityIssue]:
    """SFU's official gender-neutral lexicon (Part 6). The severity is the tier
    the term is filed under in ``coded_terms.yaml`` — never named here.

    Scanned over the JD **minus SFU's own mandated passages** (HR-058): SFU's
    pre-populated, "do not edit" About-SFU paragraph contains ``compassionate``,
    which this lexicon files at ``medium``, so a JD was penalised for obeying SFU
    and penalised again (``SFU-COMP-ABOUT``) for leaving the paragraph out. Which
    passages are exempt is rulebook data, not a decision taken here
    (``boilerplate.coded_term_scan_exempt``, HR-107) — empty that list and every
    compliant JD is docked 10 points again.

    The exemption is granted to SFU's *text*, never to a section: only a verbatim
    mandated passage is cut, so coded language cannot be smuggled past this scan by
    dressing it up as boilerplate. See :mod:`src.jd_core.quality.boilerplate`.

    The redaction happens on the raw text and the **result** is folded, in that order:
    fold-then-redact would hand the scan a normalized rendering of the JD and every
    evidence snippet it quotes would be a paraphrase. This way a cut passage is cut out
    of the JD's own bytes and the surviving text is still the JD's own words.
    """
    out: list[JDQualityIssue] = []
    window = rules.thresholds.evidence_context_window
    scannable = _fold_jd(
        redact_passages(
            raw_text,
            rules.boilerplate.coded_term_exempt_passages,
            join_paragraphs=_join(rules),
        ),
        rules,
    )
    for severity, terms in rules.coded_terms.tiers:
        for term, fix in terms.items():
            evidence = _context(scannable, term, window=window)
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
    sfu: SFUJobDescription, text: FoldedText, title: FoldedText, rules: Rules
) -> list[JDQualityIssue]:
    """SFU "never approve" gates (Learning Series Part 11.6) not covered
    elsewhere: duty %-allocations that don't total 100, KSAs out of K->S->A order,
    a reserved "Senior" prefix without supervisory scope, and the missing
    standardized Relationships header."""
    out: list[JDQualityIssue] = []
    thresholds = rules.thresholds

    # (a) Per-duty time allocations use the template's "(NN%)" format and must sum
    # to 100. Only parenthesized percentages count (precise -> few false positives).
    # Counted on the folded text, which cannot LOSE an allocation the raw text has
    # (the fold touches no digit, bracket or `%`, and `\s*` still matches the space a
    # collapsed run becomes) and does find `(5<U+200B>0%)`, which the raw text does
    # not — so the total the gate checks is, if anything, more complete than before.
    allocations = [int(m) for m in rules.patterns.duty_allocation.findall(text.folded)]
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
    if _searches(title, rules.patterns.senior_title) and not supervises:
        out.append(_issue(rules, "SFU-GATE-SENIOR-TITLE"))

    # (d) The standardized Relationships header boilerplate must be present.
    if not _present(text, rules.markers.relationships_header):
        out.append(_issue(rules, "SFU-GATE-REL-HEADER"))

    return out


def _authoring_gates(
    sfu: SFUJobDescription, summary: FoldedText, title: FoldedText, rules: Rules
) -> list[JDQualityIssue]:
    """SFU authoring gates (Learning Series Parts 2-3): the Position Summary
    carries neither working conditions nor incumbent-focused language, abilities
    read as observable behaviour, and restricted titles are used only in their
    reserved context.

    Conservative and high-signal: a restriction whose context the JD alone cannot
    settle is raised at the advisory severity ``titles.yaml`` files it under.
    """
    out: list[JDQualityIssue] = []
    window = rules.thresholds.evidence_context_window

    # Working conditions don't belong in the Position Summary (Part 2B / 11.6).
    marker = next(
        (m for m in rules.markers.working_conditions if _present(summary, m)), None
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
    if _searches(summary, rules.patterns.incumbent):
        out.append(_issue(rules, "SFU-AUTH-SUMMARY-INCUMBENT"))

    # Abilities must read as observable behaviour (Part 5.3): "Ability to <verb>…".
    prefixes = tuple(
        fold(prefix, join_paragraphs=True).casefold()
        for prefix in rules.qualifications.ability_prefixes
    )
    bad_abilities = [
        q.text
        for q in sfu.qualifications
        if q.kind == "ability"
        and not fold(q.text, join_paragraphs=_join(rules))
        .casefold()
        .startswith(prefixes)
    ]
    if bad_abilities:
        out.append(
            _issue(rules, "SFU-AUTH-ABILITIES-OBSERVABLE", count=len(bad_abilities))
        )

    # Restricted titles (Part 3.5). A restriction with a `reserved_for_employee_group`
    # is checkable from the JD (and only fires when the group is known and wrong);
    # the rest need context we can't verify, so they are advisory.
    for restricted in rules.titles.restricted:
        if not _present(title, restricted.phrase):
            continue
        group = restricted.reserved_for_employee_group
        if group is not None and (
            not sfu.employee_group or sfu.employee_group == group
        ):
            continue
        out.append(
            _issue(
                rules,
                restricted.rule_id,
                severity=restricted.severity,
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

    One definition of noise (:mod:`src.jd_core.textnorm`), not N regexes each patched
    separately. The JD's raw text is nonetheless folded **three** times per evaluation,
    and that is where most of the 2.5x slowdown over the pre-fold validator lives —
    said plainly rather than papered over:

    1. here, for every scan that reads the whole document;
    2. in :func:`_inclusive_language`, over the text *minus* SFU's mandated passages
       (a different string, so it needs its own fold and its own origin map);
    3. inside :func:`~src.jd_core.quality.boilerplate.redact_passages`, which folds
       with ``casefold=True`` — its matcher compares plain strings, and a casefolded
       fold is a different string with different offsets, so it cannot reuse (1).

    Collapsing those would mean either giving :class:`FoldedText` a second casefolded
    view (whose indices can diverge from the first on non-ASCII) or folding before
    redaction (which would make every evidence snippet a normalized paraphrase). The
    cost is ~11 ms on a real archive JD — ~165 s for all 14,565 — and the baseline is a
    batch job. Deliberately not optimised.
    """
    rules = rules if rules is not None else get_rules()
    text = _fold_jd(raw_text, rules)
    summary = _fold_jd(sfu.position_summary or "", rules)
    title = _fold_jd(sfu.title, rules)
    issues: list[JDQualityIssue] = []
    issues += _completeness(sfu, rules)
    issues += _structure(sfu, text, rules)
    issues += _qualifications(sfu, text, rules)
    issues += _inclusive_language(raw_text, rules)
    issues += _quality_gates(sfu, text, title, rules)
    issues += _authoring_gates(sfu, summary, title, rules)
    return issues

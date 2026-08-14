"""Deterministic harmonization merge engine (Phase 4.1) — pure, no LLM.

Given the member JDs of a role cluster, :func:`merge_cluster` drafts a single
canonical :class:`~src.jd_core.models.parsed_jd.SFUJobDescription` **plus provenance**
using only deterministic functions — section selection, duty union/dedup/reorder, and
a KSA (Qualifications) rebuild from the cluster's skill/education/experience evidence.

**The output is a DRAFT** (CLAUDE.md non-negotiable #1): nothing here approves,
publishes, or marks anything canonical. It is the grounded, attributable starting
point a human reviewer (4.4) and the LLM rewrite pass (4.2) act on — provenance is
verifiable *before* any model touches the text.

**Pure** (ADR-006 / non-negotiable #2): no I/O, no DB, no Neo4j, no Ollama, and it
imports no ``jd_bank`` (the layering ratchet). Every knob it reads is versioned YAML —
``rules/harmonization.yaml``, HR-167…HR-175, all ``open`` and PROVISIONAL (to be
calibrated by a post-run measurement pass over the real clusters).

**Order-invariant by construction.** Members are first sorted into a canonical order
by their own content, and *every* downstream "member index" refers to that order — so
the same SET of members in any input order yields a byte-identical ``MergedRole``.

**Deliberately partial.** Only the sections the task enumerates are harmonized:
title / department / grade / employee-group / summary / additional-context / the
presence booleans, the duties, and the Qualifications. ``position_number``,
``decision_making``, ``problem_solving`` and ``relationships`` are left at their model
defaults — the deterministic engine does not merge them in 4.1 (a follow-up), rather
than inventing an unregistered merge policy for each. Duty statements are carried
**verbatim** on their representative: %-allocation rebalancing is explicitly out of
scope (its own follow-up).
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import cast

from src.jd_core.bank.drift import (
    education_level_from_text,
    experience_years_from_text,
)
from src.jd_core.bank.provenance import skill_frequency
from src.jd_core.bank.signals import build_job_signals
from src.jd_core.models.bank import (
    JobSignals,
    MergedRole,
    MergeProvenance,
    SeniorityBarChoice,
)
from src.jd_core.models.parsed_jd import (
    QualificationKind,
    SFUDuty,
    SFUEmployeeGroup,
    SFUJobDescription,
    SFUQualification,
)
from src.jd_core.models.quality import WJQ_TEMPLATE
from src.jd_core.quality.validators import template_of
from src.jd_core.rules import Comparison, Harmonization, Rules, get_rules

#: A skill/statement token: a maximal run of lowercase letters/digits — the same
#: alphabet ``signals``/``similarity`` tokenize with. Kept local (a third local copy,
#: exactly as those two modules keep their own) so retuning one cannot silently move
#: the merge dedup.
_TOKEN = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> frozenset[str]:
    """The token set of ``text`` (lowercase ``[a-z0-9]+`` runs)."""
    return frozenset(_TOKEN.findall(text.lower()))


def _jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    """Token-Jaccard of two token sets. Two empty sets are identical (1.0)."""
    union = a | b
    if not union:
        return 1.0
    return len(a & b) / len(union)


# --- shared couplings: the canonical member order + the actual duty-group fate -------
#
# These are PUBLIC so the change-log generator (``bank/change_log.py``) consumes the
# SAME ordering and the SAME duty grouping the merge does — one rulebook fact, one home.
# This repo has been bitten by a second copy of the tokenizer/ordering that silently
# disagrees; ``merge_cluster`` and the diff MUST route through exactly these.


def canonical_member_order(
    members: Sequence[SFUJobDescription],
) -> list[SFUJobDescription]:
    """The merge's canonical member ordering: members sorted by their own JSON content,
    so it is independent of the caller's input order. EVERY "member index" in a
    :class:`~src.jd_core.models.bank.MergeProvenance` (and in a
    :class:`~src.jd_core.models.bank.HarmonizationDiff`) is a position in THIS order."""
    return sorted(members, key=lambda jd: jd.model_dump_json())


def dropped_duty_occurrences(
    ordered: Sequence[SFUJobDescription], harmon: Harmonization
) -> frozenset[tuple[int, str]]:
    """The ``(member_index, statement)`` duty occurrences whose group the ``max_duties``
    cap DROPPED — the merge's ACTUAL group fate, not a re-derived Jaccard proxy.

    This is the authoritative "dropped vs merely folded" verdict for the change-log: an
    occurrence is here IFF its duty group is one of the low-coverage groups sliced off
    by the cap. A member duty that folded onto a SURVIVING group's representative is NOT
    here, even when that representative drifted below the dedup threshold from it (the
    greedy grouping matches the group SEED, but the representative is re-picked by
    richest ``how_why`` — so ``jaccard(member_duty, representative)`` cannot tell them
    apart; only the real group fate can). Shares :func:`_resolve_duty_groups` with
    :func:`_merge_duties`, so the diff and the draft can never disagree on which duties
    the cap cut.
    """
    resolved = _resolve_duty_groups(ordered, harmon)
    dropped = resolved[harmon.max_duties :]
    return frozenset(occ for group in dropped for occ in group.occurrences)


def unmerged_content(jd: SFUJobDescription) -> list[str]:
    """The actual content pieces a member carries in a section 4.1 does NOT merge —
    decision_making / problem_solving / relationships / position_number — verbatim and
    in a deterministic order. Empty iff the member has nothing in those sections; that
    emptiness is exactly the ``sections_not_merged`` trigger (see
    :func:`_has_unmerged_content`). Relationships count only when they carry a real
    value (a present-but-empty ``SFURelationships`` is not content)."""
    pieces: list[str] = list(jd.decision_making) + list(jd.problem_solving)
    rel = jd.relationships
    if rel is not None:
        if rel.supervisory:
            pieces.append(rel.supervisory)
        pieces += list(rel.internal)
        pieces += list(rel.external)
    if jd.position_number:
        pieces.append(jd.position_number)
    return pieces


# --- section selection: scalars / text ---------------------------------------------


def _select_title(
    ordered: Sequence[SFUJobDescription],
    sigs: Sequence[JobSignals],
    harmon: Harmonization,
) -> tuple[str, tuple[int, ...]]:
    """The canonical title + the member indices that fed it.

    ``modal_normalized``: the representative of the most-populous ``normalize_title``
    group, tie-broken SHORTEST-raw then lexicographic (then index). ``first_raw``: the
    lexicographically-first raw title, modality ignored.
    """
    raws = [jd.title for jd in ordered]
    if harmon.title_policy == "first_raw":
        chosen = min(raws)
        return chosen, tuple(i for i, r in enumerate(raws) if r == chosen)

    norms = [s.normalized_title for s in sigs]
    counts = Counter(norms)
    chosen_i = min(
        range(len(ordered)),
        key=lambda i: (-counts[norms[i]], len(raws[i]), raws[i], i),
    )
    chosen_norm = norms[chosen_i]
    idx = tuple(i for i in range(len(ordered)) if norms[i] == chosen_norm)
    return raws[chosen_i], idx


def _modal_non_null(
    values: Sequence[object | None],
) -> tuple[object | None, tuple[int, ...]]:
    """The modal non-null value + the indices carrying it. ``None`` when all null;
    ties broken lexicographically on ``str(value)``."""
    present = [(i, v) for i, v in enumerate(values) if v is not None]
    if not present:
        return None, ()
    counts: Counter[object] = Counter(v for _, v in present)
    chosen = min(counts, key=lambda v: (-counts[v], str(v)))
    return chosen, tuple(i for i, v in present if v == chosen)


def _modal_non_null_flagged(
    values: Sequence[object | None],
) -> tuple[object | None, tuple[int, ...], bool]:
    """:func:`_modal_non_null`, plus whether the members DISAGREE (>1 distinct
    non-null value) — the caller raises the disagreement flag."""
    chosen, idx = _modal_non_null(values)
    distinct = {v for v in values if v is not None}
    return chosen, idx, len(distinct) > 1


def _most_central(pool: Sequence[tuple[int, str]]) -> tuple[str, int]:
    """The most-central text (highest summed token-Jaccard to the others) + its index;
    ties broken by (shortest, lexicographic, index). ``pool`` is non-empty."""
    toks = {i: _tokens(text) for i, text in pool}

    def centrality(i: int) -> float:
        return round(sum(_jaccard(toks[i], toks[j]) for j, _ in pool if j != i), 6)

    best = min(pool, key=lambda it: (-centrality(it[0]), len(it[1]), it[1], it[0]))
    return best[1], best[0]


def _select_summary(
    ordered: Sequence[SFUJobDescription], rules: Rules, harmon: Harmonization
) -> tuple[str | None, int | None]:
    """A member's position summary, chosen VERBATIM (no rewrite — that is 4.2).

    ``within_target_then_central`` prefers a summary already inside SFU's published
    word range (``thresholds.summary_min_words``/``_max_words`` — one rulebook fact,
    one home), then the most-central; ``most_central`` skips the in-range preference.
    """
    cands = [
        (i, jd.position_summary)
        for i, jd in enumerate(ordered)
        if jd.position_summary and jd.position_summary.strip()
    ]
    if not cands:
        return None, None
    typed = [(i, s) for i, s in cands if s is not None]
    if harmon.summary_policy == "within_target_then_central":
        lo = rules.thresholds.summary_min_words
        hi = rules.thresholds.summary_max_words
        in_range = [(i, s) for i, s in typed if lo <= len(s.split()) <= hi]
        pool = in_range if in_range else typed
    else:
        pool = typed
    text, idx = _most_central(pool)
    return text, idx


def _select_additional_context(
    ordered: Sequence[SFUJobDescription], harmon: Harmonization
) -> tuple[str | None, int | None]:
    """``drop`` (default — a union of per-member context is noisy) or the ``longest``
    single member note, verbatim."""
    if harmon.additional_context_policy == "drop":
        return None, None
    cands = [
        (i, jd.additional_context)
        for i, jd in enumerate(ordered)
        if jd.additional_context and jd.additional_context.strip()
    ]
    typed = [(i, s) for i, s in cands if s is not None]
    if not typed:
        return None, None
    idx, text = min(typed, key=lambda it: (-len(it[1]), it[1], it[0]))
    return text, idx


def _presence(
    ordered: Sequence[SFUJobDescription], harmon: Harmonization
) -> tuple[bool, bool, bool]:
    """The three boilerplate presence booleans. ``or_across_members`` (default, honest:
    the draft carries no boilerplate TEXT, so a re-parse still trips the footer/About
    gates) or ``all_present`` (asserts present — only after HR ratifies footer
    auto-insert)."""
    if harmon.boilerplate_presence_policy == "all_present":
        return True, True, True
    return (
        any(jd.about_sfu_present for jd in ordered),
        any(jd.territorial_acknowledgement_present for jd in ordered),
        any(jd.employment_equity_present for jd in ordered),
    )


# --- duty union / dedup / reorder --------------------------------------------------


@dataclass
class _DutyGroup:
    items: list[tuple[int, SFUDuty]]
    members: set[int]
    rep_tokens: frozenset[str]


@dataclass
class _ResolvedDutyGroup:
    """A finalized duty group: its verbatim representative, its member-coverage, and the
    ``(member_index, statement)`` occurrences that fell into it. Ordered position in the
    resolved list is coverage-desc then statement — so ``[:max_duties]`` are the
    survivors and ``[max_duties:]`` are exactly the groups the cap drops."""

    representative: SFUDuty
    coverage: int
    occurrences: tuple[tuple[int, str], ...]


def _resolve_duty_groups(
    ordered: Sequence[SFUJobDescription], harmon: Harmonization
) -> list[_ResolvedDutyGroup]:
    """Union every duty, dedup near-identical STATEMENTS by token-Jaccard, pick a
    deterministic representative per group, and return the groups ordered by
    member-coverage (desc) then statement.

    The SINGLE home of the merge's duty grouping — :func:`_merge_duties` (the draft) and
    :func:`dropped_duty_occurrences` (the change-log's drop verdict) both consume this,
    so they can never disagree. Representative = richest ``how_why``, then longest
    statement, carried verbatim; %-rebalance is out of scope.
    """
    occ: list[tuple[int, SFUDuty]] = [
        (i, d) for i, jd in enumerate(ordered) for d in jd.duties
    ]
    occ.sort(key=lambda o: (o[1].statement, o[0]))

    groups: list[_DutyGroup] = []
    thr = harmon.duty_dedup_jaccard_min
    for i, duty in occ:
        toks = _tokens(duty.statement)
        for group in groups:
            if _jaccard(toks, group.rep_tokens) >= thr:
                group.items.append((i, duty))
                group.members.add(i)
                break
        else:
            groups.append(_DutyGroup(items=[(i, duty)], members={i}, rep_tokens=toks))

    resolved: list[_ResolvedDutyGroup] = []
    for group in groups:
        _, rep = max(
            group.items,
            key=lambda it: (
                len(it[1].how_why),
                len(it[1].statement),
                it[1].statement,
                it[0],
            ),
        )
        resolved.append(
            _ResolvedDutyGroup(
                representative=rep,
                coverage=len(group.members),
                occurrences=tuple((i, d.statement) for i, d in group.items),
            )
        )
    resolved.sort(key=lambda g: (-g.coverage, g.representative.statement))
    return resolved


def _merge_duties(
    ordered: Sequence[SFUJobDescription], harmon: Harmonization
) -> tuple[list[SFUDuty], tuple[tuple[str, int], ...], bool]:
    """Union every duty, dedup near-identical STATEMENTS by token-Jaccard, keep a
    deterministic representative per group, reorder by member-coverage.

    Returns ``(duties, coverage, over_max)``. Statements are carried verbatim on the
    representative (richest ``how_why``, then longest statement); %-rebalance is out of
    scope. If the deduped duties exceed ``max_duties`` the top-by-coverage survive and
    ``over_max`` is set (the caller flags ``duties_over_max`` — never a silent drop).
    """
    resolved = _resolve_duty_groups(ordered, harmon)
    over_max = len(resolved) > harmon.max_duties
    kept = resolved[: harmon.max_duties]
    duties = [
        SFUDuty(
            action_verb=group.representative.action_verb,
            statement=group.representative.statement,
            how_why=list(group.representative.how_why),
            frequency=group.representative.frequency,
        )
        for group in kept
    ]
    coverage = tuple((group.representative.statement, group.coverage) for group in kept)
    return duties, coverage, over_max


# --- KSA rebuild (Qualifications) --------------------------------------------------


@dataclass
class _QualGroup:
    quals: list[SFUQualification]
    members: set[int]
    rep_tokens: frozenset[str] = field(default=frozenset())


def _qual_skill_tokens(
    qual: SFUQualification, comparison: Comparison
) -> frozenset[str]:
    """A qualification's skill tokens — the same filter ``signals._skill_bag`` applies
    (stopwords + ``skill_min_token_len``), so membership lines up with the skill
    frequencies."""
    return frozenset(
        t
        for t in _TOKEN.findall(qual.text.lower())
        if len(t) >= comparison.skill_min_token_len
        and t not in comparison.skill_stopwords
    )


def _modal_modifier(quals: Sequence[SFUQualification]) -> str | None:
    """The modal ``modifier`` across a qual group (``None`` is a real value); ties
    prefer ``None`` then lexicographic — deterministic."""
    counts: Counter[str | None] = Counter(q.modifier for q in quals)
    return min(counts, key=lambda m: (-counts[m], "" if m is None else m))


def _group_quals(
    occ: Sequence[tuple[int, SFUQualification]], harmon: Harmonization
) -> list[_QualGroup]:
    """Group qualifications by near-identical text (the same Jaccard as duty dedup),
    deterministically, tracking each group's contributing members."""
    items = sorted(occ, key=lambda o: (o[1].text, o[0]))
    groups: list[_QualGroup] = []
    thr = harmon.duty_dedup_jaccard_min
    for i, qual in items:
        toks = _tokens(qual.text)
        for group in groups:
            if _jaccard(toks, group.rep_tokens) >= thr:
                group.quals.append(qual)
                group.members.add(i)
                break
        else:
            groups.append(_QualGroup(quals=[qual], members={i}, rep_tokens=toks))
    return groups


def _group_representative(
    group: _QualGroup, kind: QualificationKind
) -> SFUQualification:
    """The group's representative qualification: longest text (then lexicographic),
    modal modifier, at the given kind."""
    rep = max(group.quals, key=lambda q: (len(q.text), q.text))
    return SFUQualification(
        text=rep.text, kind=kind, modifier=_modal_modifier(group.quals)
    )


def _quals_of_kind(
    ordered: Sequence[SFUJobDescription],
    kind: str,
    parse: Callable[[str], int | None],
) -> list[tuple[int, SFUQualification, int]]:
    """``(member_index, qual, parsed_bar)`` for every ``kind`` qual whose text parses
    to a bar (``None`` bars dropped)."""
    return [
        (i, qual, bar)
        for i, jd in enumerate(ordered)
        for qual in jd.qualifications
        if qual.kind == kind
        for bar in (parse(qual.text),)
        if bar is not None
    ]


def _seniority_qual(
    ordered: Sequence[SFUJobDescription],
    member_bars: Sequence[int | None],
    kinds_by_priority: Sequence[str],
    parse: Callable[[str], int | None],
    out_kind: QualificationKind,
    harmon: Harmonization,
) -> tuple[SFUQualification | None, SeniorityBarChoice | None]:
    """The representative education/experience qualification at the cluster's chosen
    bar.

    ⚠ **The bar comes from ``member_bars`` — the per-member signal already computed by
    ``build_job_signals``** (``JobSignals.education_ordinal`` / ``.experience_years``) —
    NOT from a raw union of every source-kind qual. That is load-bearing: for
    experience, ``signals._experience_years`` honours ``experience_source_kinds`` ORDER
    (an explicit ``experience`` qual is authoritative; ``knowledge`` is only the JDFN
    fallback), so a member's bar deliberately ignores a bigger number sitting in its
    ``knowledge`` blob. Deriving the cluster target here means the engine never emits a
    bar (nor relabels a blob ``experience``) that no member's *signal* actually stated.

    The bar is chosen by ``seniority_bar_policy`` (``max`` — highest stated — or
    ``modal``). The representative qual is then located among ``kinds_by_priority`` in
    order (``experience`` before ``knowledge``): the first kind carrying a qual that
    parses to the target wins. If the target came from a multi-qual (concatenated)
    read that no single qual reproduces, we fall back to the highest-parsing single qual
    (same priority order) so a real bar is never silently dropped.
    """
    bars = [bar for bar in member_bars if bar is not None]
    if not bars:
        return None, None
    if harmon.seniority_bar_policy == "max":
        target = max(bars)
    else:
        counts: Counter[int] = Counter(bars)
        target = min(counts, key=lambda b: (-counts[b], b))

    # The record of the choice (P1.2). Built from the same `target` the draft is
    # assembled from and the same `member_bars` it was chosen out of, so it cannot
    # describe a decision other than the one actually made — and it echoes the live
    # policy rather than assuming `max`.
    choice = SeniorityBarChoice(
        kind=out_kind,
        policy=harmon.seniority_bar_policy,
        chosen=target,
        member_bars=tuple(member_bars),
    )

    for kind in kinds_by_priority:
        matching = [
            (i, qual)
            for i, qual, bar in _quals_of_kind(ordered, kind, parse)
            if bar == target
        ]
        if matching:
            return (
                _group_representative(_group_quals(matching, harmon)[0], out_kind),
                choice,
            )
    # No single qual reproduces the (possibly concatenated) target — emit the strongest
    # single qual we can, in kind-priority order, rather than drop a stated bar.
    for kind in kinds_by_priority:
        parsed = _quals_of_kind(ordered, kind, parse)
        if parsed:
            best = max(bar for _, _, bar in parsed)
            matching = [(i, qual) for i, qual, bar in parsed if bar == best]
            return (
                _group_representative(_group_quals(matching, harmon)[0], out_kind),
                choice,
            )
    return None, choice


def _security_quals(
    ordered: Sequence[SFUJobDescription], member_count: int, harmon: Harmonization
) -> list[SFUQualification]:
    """Security requirements. ``union``: every distinct one any member states.
    ``core_only``: only those required by >= ``core_skill_min_fraction`` of members.

    ⚠ COUPLING: under ``core_only`` this shares ``core_skill_min_fraction`` (HR-173)
    with the skill filter — so re-calibrating that knob later would move the security
    threshold too. Inert today (default ``union``); made visible here on purpose.
    """
    occ = [
        (i, qual)
        for i, jd in enumerate(ordered)
        for qual in jd.qualifications
        if qual.kind == "security"
    ]
    groups = _group_quals(occ, harmon)
    out: list[SFUQualification] = []
    for group in groups:
        if harmon.security_policy == "core_only" and (
            len(group.members) / member_count < harmon.core_skill_min_fraction
        ):
            continue
        out.append(_group_representative(group, "security"))
    return out


def _rebuild_ksa(
    ordered: Sequence[SFUJobDescription],
    sigs: Sequence[JobSignals],
    rules: Rules,
    harmon: Harmonization,
) -> tuple[list[SFUQualification], bool, tuple[SeniorityBarChoice, ...]]:
    """Rebuild Qualifications from the cluster's evidence. Returns
    ``(qualifications, no_core_skills, seniority_bars)`` — the third being the
    record of HOW each bar was chosen, for the 4.4 reviewer (P1.2).

    Core skills (required by >= ``core_skill_min_fraction`` of members) keep their
    representative qualification; incidental one-offs are dropped (SFU is
    minimum-not-desired). Education/experience take the chosen bar; security per
    ``security_policy``.
    """
    comparison = rules.comparison
    n = len(ordered)
    freq = dict(skill_frequency([s.skills for s in sigs]))
    core = {
        tok
        for tok, count in freq.items()
        if count / n >= harmon.core_skill_min_fraction
    }

    skill_occ = [
        (i, qual)
        for i, jd in enumerate(ordered)
        for qual in jd.qualifications
        if qual.kind in comparison.skill_source_kinds
        and _qual_skill_tokens(qual, comparison) & core
    ]
    ksa_rank = rules.qualifications.ksa_rank
    skill_quals: list[SFUQualification] = []
    for group in _group_quals(skill_occ, harmon):
        rep = max(group.quals, key=lambda q: (len(q.text), q.text))
        skill_quals.append(
            SFUQualification(
                text=rep.text, kind=rep.kind, modifier=_modal_modifier(group.quals)
            )
        )
    skill_quals.sort(key=lambda q: (ksa_rank.get(q.kind, len(ksa_rank)), q.text))

    # Education: the bar is the per-member signal (from `build_job_signals`); the
    # representative is located `education`-kind first, then the rest (the JDFN degree
    # often lives in a `knowledge` blob). `education_source_kinds` is a frozenset, so
    # the priority order is imposed deterministically here.
    edu_priority = sorted(
        comparison.education_source_kinds, key=lambda k: (k != "education", k)
    )
    edu, edu_choice = _seniority_qual(
        ordered,
        [s.education_ordinal for s in sigs],
        edu_priority,
        lambda text: education_level_from_text(text, rules=rules),
        "education",
        harmon,
    )
    # Experience: `experience_source_kinds` is an ORDERED tuple
    # ([experience, knowledge]) — `experience` is authoritative, `knowledge` the
    # fallback. The per-member bar (`sigs[i].experience_years`) already honours that
    # order, so a bigger number in a member's `knowledge` blob cannot inflate its bar.
    exp, exp_choice = _seniority_qual(
        ordered,
        [s.experience_years for s in sigs],
        comparison.experience_source_kinds,
        lambda text: experience_years_from_text(text, rules=rules),
        "experience",
        harmon,
    )
    seniority_bars = tuple(c for c in (edu_choice, exp_choice) if c is not None)
    security = _security_quals(ordered, n, harmon)

    ordered_quals = [q for q in (edu, exp) if q is not None] + skill_quals + security
    # Drop exact-text duplicates (a knowledge blob emitted as both an education bar and
    # a core skill), keeping the first — education, then experience, then skill.
    seen: set[str] = set()
    deduped: list[SFUQualification] = []
    for qual in ordered_quals:
        key = qual.text.strip().lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(qual)
    return deduped[:40], not core, seniority_bars


# --- the entry point ---------------------------------------------------------------


def merge_cluster(
    members: Sequence[SFUJobDescription], *, rules: Rules | None = None
) -> MergedRole:
    """Harmonize a role cluster's member JDs into a single **draft** + provenance.

    Pure, deterministic and **order-invariant**: the same set of members in any order
    yields a byte-identical :class:`~src.jd_core.models.bank.MergedRole`. A single
    member is a passthrough-with-provenance (flagged ``single_member``). An empty
    cluster raises :class:`ValueError` — there is no title to draft.

    The result is a DRAFT (non-negotiable #1): nothing here is approved or canonical.
    """
    active = rules if rules is not None else get_rules()
    if not members:
        raise ValueError("cannot merge an empty cluster: there is no title to draft")

    # Merge against the members' OWN form's numbers (CUPE Phase D), by the same one-line
    # profile swap `evaluate_jd_rules` makes for the same reason: `_select_summary`
    # prefers a member summary inside `thresholds.summary_min_words/_max_words`, and
    # picking a WJQ cluster's representative summary by the JDFN band would judge a CUPE
    # document against a form it was not written on — the category error Phases B and C
    # removed from the validator, in the last place it still lived.
    #
    # The two profiles agree on both summary bounds TODAY (100/150 — HR-204/205 held at
    # their JDFN twins and registered rather than inherited), so this changes no output
    # as shipped. It is wired anyway: the alternative is a correctness hole that opens
    # silently the day HR moves one value, which is precisely the failure mode a
    # registered-but-equal default exists to prevent.
    # UNANIMITY, not the first member: `merge_cluster` is documented order-invariant, so
    # reading the form off `members[0]` would make the same set in a different order
    # merge differently. A mixed set falls back to JDFN — the same tie-break
    # `templates_harmonized` ships (HR-206), and the conservative direction, since JDFN
    # is the profile every existing draft was built against.
    if all(template_of(jd) == WJQ_TEMPLATE for jd in members):
        active = active.model_copy(
            update={"thresholds": active.thresholds_for(WJQ_TEMPLATE)}
        )

    harmon = active.harmonization
    ordered = canonical_member_order(members)
    sigs = [build_job_signals(jd, rules=active) for jd in ordered]
    n = len(ordered)

    flags: set[str] = set()
    contributors: dict[str, tuple[int, ...]] = {}

    title, title_idx = _select_title(ordered, sigs, harmon)
    contributors["title"] = title_idx

    # Department is picked modal but NOT flagged on disagreement: a role cluster
    # legitimately spans departments (the same role in different units), so a mix is
    # EXPECTED, not a concern — unlike grade / employee_group, where a mix means the
    # cluster may weld distinct roles and an HR reviewer should look.
    department, dept_idx = _modal_non_null([jd.department for jd in ordered])
    if dept_idx:
        contributors["department"] = dept_idx

    grade, grade_idx, grade_conflict = _modal_non_null_flagged(
        [jd.grade for jd in ordered]
    )
    if grade_idx:
        contributors["grade"] = grade_idx
    if grade_conflict:
        flags.add("grade_disagreement")

    group, group_idx, group_conflict = _modal_non_null_flagged(
        [jd.employee_group for jd in ordered]
    )
    if group_idx:
        contributors["employee_group"] = group_idx
    if group_conflict:
        flags.add("employee_group_disagreement")

    summary, summary_idx = _select_summary(ordered, active, harmon)
    if summary_idx is not None:
        contributors["position_summary"] = (summary_idx,)

    additional_context, ac_idx = _select_additional_context(ordered, harmon)
    if ac_idx is not None:
        contributors["additional_context"] = (ac_idx,)

    about, territorial, equity = _presence(ordered, harmon)

    duties, duty_coverage, over_max = _merge_duties(ordered, harmon)
    if over_max:
        flags.add("duties_over_max")

    qualifications, no_core, seniority_bars = _rebuild_ksa(
        ordered, sigs, active, harmon
    )
    if no_core:
        flags.add("no_core_skills")

    if n == 1:
        flags.add("single_member")

    # 4.1 deliberately does NOT merge decision_making / problem_solving / relationships
    # / position_number (out of scope). If any member actually carried content in one of
    # them, the draft silently drops it — so tell the 4.4 human reviewer (non-negotiable
    # #6) rather than let it vanish.
    if any(_has_unmerged_content(jd) for jd in ordered):
        flags.add("sections_not_merged")

    draft = SFUJobDescription(
        title=title,
        department=department if isinstance(department, str) else None,
        grade=grade if isinstance(grade, str) else None,
        employee_group=_as_group(group),
        about_sfu_present=about,
        position_summary=summary,
        duties=duties,
        qualifications=qualifications,
        territorial_acknowledgement_present=territorial,
        employment_equity_present=equity,
        additional_context=additional_context,
    )

    provenance = MergeProvenance(
        member_count=n,
        skill_frequency=tuple(
            (skill, count) for skill, count in skill_frequency([s.skills for s in sigs])
        ),
        duty_coverage=duty_coverage,
        section_contributors=tuple(
            (name, contributors[name]) for name in sorted(contributors)
        ),
        flags=tuple(sorted(flags)),
        seniority_bars=seniority_bars,
    )
    return MergedRole(draft=draft, provenance=provenance)


def _as_group(value: object | None) -> SFUEmployeeGroup | None:
    """Narrow a modal employee-group value back to the ``SFUEmployeeGroup`` literal
    (it came off a parsed JD's own ``employee_group`` field, so it always is one)."""
    if value is None:
        return None
    return cast("SFUEmployeeGroup", value)


def _has_unmerged_content(jd: SFUJobDescription) -> bool:
    """Whether a member carries content in a section 4.1 does NOT merge — the trigger
    for the ``sections_not_merged`` provenance flag. The notion of "unmerged content"
    is :func:`unmerged_content` (one home): the flag fires iff that content is
    non-empty, so the change-log lists exactly what the flag warns about."""
    return bool(unmerged_content(jd))

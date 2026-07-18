"""Harmonization change-log / per-source diff (Phase 4.3) — pure, deterministic.

Given a harmonized :class:`~src.jd_core.models.bank.MergedRole` and the source
members it was drawn from, :func:`build_harmonization_diff` builds the two
legibility artifacts the plan promises alongside a draft (§2.3 step 5):

* a **per-source diff** — for each member, which scalar/text sections it fed and
  which of its duties survived verbatim vs were folded/dropped; and
* a **"removed content and why" change log** — every piece of member content the
  harmonization dropped, tagged with the reason.

So a 4.4 reviewer can see, for a draft, where each section came from and *exactly*
what was removed and why — nothing vanishes silently (non-negotiable #6).

**Scope of ``removed``.** It covers dropped *duties* (deduplicated / cap-dropped) and
the unmerged sections (decision_making / problem_solving / relationships /
position_number), plus the optional rewrite-stage qualification scrubs. It is NOT
exhaustive over the KSA rebuild's incidental non-core-skill drops — a one-off skill
required by too few members is deliberately outside :data:`RemovedReason`; that pruning
is visible instead via :attr:`MergeProvenance.skill_frequency` (the per-skill member
counts the rebuild kept vs dropped on).

**Pure** (ADR-006 / non-negotiable #2): no I/O, no DB, no Neo4j, no Ollama, no LLM,
and it imports no ``jd_bank`` (the layering ratchet). It introduces NO new decision
knob: it reuses the merge's already-registered ordering
(:func:`~src.jd_core.bank.merge.canonical_member_order`) and the merge's own group
fate (:func:`~src.jd_core.bank.merge.dropped_duty_occurrences`, derived from the same
grouping at ``duty_dedup_jaccard_min`` / ``max_duties``) — one rulebook fact, one
home, so the diff can never silently disagree with the merge it describes. A duty's
drop-vs-dedup verdict comes from whether its actual group was cap-dropped, never a
re-derived Jaccard proxy (a proxy mislabels a duty that folds into a surviving group
but drifts from that group's re-picked representative).

**Order-invariant by construction.** Every member index is a position in the merge's
own canonical order, so the same SET of members in any input order yields a
byte-identical :class:`~src.jd_core.models.bank.HarmonizationDiff`.

**Descriptive, never a decision** (non-negotiable #1): the diff carries no approval /
canonical / score field. It reports what the deterministic merge (and the optional
4.2a rewrite scrub) did; it approves nothing and merges nothing itself.

**Render is display-only.** ``rendered_draft`` is ``render_sfu_jd_text(merged.draft)``.
That text is lossy on re-parse (see ``bank/render.py``); this module renders it for a
human and STOPS — it builds no render->parse round trip.
"""

from __future__ import annotations

from collections.abc import Sequence

from src.jd_core.bank.merge import (
    canonical_member_order,
    dropped_duty_occurrences,
    unmerged_content,
)
from src.jd_core.bank.render import render_sfu_jd_text
from src.jd_core.models.bank import (
    AntiFabricationRecord,
    HarmonizationDiff,
    MergedRole,
    RemovedContent,
    RewrittenDraft,
    SourceContribution,
)
from src.jd_core.models.parsed_jd import SFUJobDescription
from src.jd_core.rules import Rules, get_rules


def build_harmonization_diff(
    merged: MergedRole,
    members: Sequence[SFUJobDescription],
    *,
    rewrite: AntiFabricationRecord | RewrittenDraft | None = None,
    rules: Rules | None = None,
) -> HarmonizationDiff:
    """Build the per-source diff + "removed content and why" change log for a draft.

    ``merged`` is the :func:`~src.jd_core.bank.merge.merge_cluster` output and
    ``members`` the SAME cluster members it was drawn from (any input order).
    ``rewrite`` optionally folds a 4.2a rewrite pass's anti-fabrication record in: its
    scrubbed qualifications become ``qualification_scrubbed_ungrounded`` removals and
    its flagged duties become
    :attr:`~src.jd_core.models.bank.HarmonizationDiff.flagged_duties` (flagged ≠
    removed).

    Pure, deterministic and order-invariant. ``rules`` defaults to the loaded
    rulebook; only the merge's already-registered ``harmonization`` knobs are read.
    """
    active = rules if rules is not None else get_rules()
    harmon = active.harmonization

    ordered = canonical_member_order(members)
    draft_statement_set = {d.statement for d in merged.draft.duties}
    # The merge's ACTUAL group fate — which member-duty occurrences the cap dropped —
    # not a re-derived Jaccard proxy (a folded duty can drift below threshold from its
    # surviving group's representative, so the proxy would wrongly call it a cap-drop).
    dropped_occ = dropped_duty_occurrences(ordered, harmon)

    # section -> the member indices that fed it (the merge's own provenance ordering).
    sections_by_member: dict[int, list[str]] = {i: [] for i in range(len(ordered))}
    for section, indices in merged.provenance.section_contributors:
        for i in indices:
            sections_by_member[i].append(section)

    per_source: list[SourceContribution] = []
    removed: list[RemovedContent] = []

    for i, member in enumerate(ordered):
        kept: list[str] = []
        folded: list[str] = []
        for duty in member.duties:
            statement = duty.statement
            if statement in draft_statement_set:
                # Survived VERBATIM as a draft duty — this member is its representative.
                kept.append(statement)
                continue
            folded.append(statement)
            # Not verbatim, so it did not survive as a representative. The merge's
            # actual group fate is authoritative: if this exact occurrence's group was
            # cap-dropped it is `duty_dropped_over_max`, otherwise it folded onto a
            # surviving group's representative -> `duty_deduplicated` (true even when
            # that representative drifted below the dedup threshold from this duty — the
            # group fate, not a Jaccard-to-draft proxy, tells the two apart).
            if (i, statement) in dropped_occ:
                reason = "duty_dropped_over_max"
            else:
                reason = "duty_deduplicated"
            removed.append(
                RemovedContent(content=statement, reason=reason, member_index=i)
            )

        # Content in the sections 4.1 does not merge, if the draft dropped it (the same
        # notion `merge` flags as `sections_not_merged`). Reported, not just flagged.
        for piece in unmerged_content(member):
            removed.append(
                RemovedContent(
                    content=piece, reason="section_not_merged", member_index=i
                )
            )

        per_source.append(
            SourceContribution(
                member_index=i,
                title=member.title,
                contributed_sections=tuple(sections_by_member[i]),
                duties_kept=tuple(kept),
                duties_folded_or_dropped=tuple(folded),
            )
        )

    flagged_duties: tuple[str, ...] = ()
    record = _anti_fabrication(rewrite)
    if record is not None:
        for skill in record.scrubbed_skills:
            removed.append(
                RemovedContent(
                    content=skill,
                    reason="qualification_scrubbed_ungrounded",
                    member_index=None,
                )
            )
        flagged_duties = tuple(record.flagged_duties)

    return HarmonizationDiff(
        rendered_draft=render_sfu_jd_text(merged.draft),
        per_source=tuple(per_source),
        removed=tuple(removed),
        flagged_duties=flagged_duties,
    )


def _anti_fabrication(
    rewrite: AntiFabricationRecord | RewrittenDraft | None,
) -> AntiFabricationRecord | None:
    """The anti-fabrication record to fold in, from either the record itself or the
    :class:`~src.jd_core.models.bank.RewrittenDraft` that carries it."""
    if rewrite is None:
        return None
    if isinstance(rewrite, RewrittenDraft):
        return rewrite.anti_fabrication
    return rewrite

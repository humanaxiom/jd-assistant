# Phase 4.3 — harmonization change-log / per-source diff (pure, deterministic)

## Goal
Give the 4.4 reviewer the two artifacts the plan (§2.3 step 5) promises alongside a
harmonized draft: a **per-source diff** (how the merged draft was drawn from each cluster
member) and a **"removed content and why" change log** (every piece of member content the
harmonization dropped, with the reason). Both **pure and deterministic** — NO LLM, NO DB,
NO network. The rendered draft text comes from the existing `bank/render.py`.

This makes the merge's decisions LEGIBLE: a reviewer must be able to see, for a draft, which
member each section came from, which of a member's duties survived vs were folded away, and
exactly what was removed and why — so nothing vanishes silently (non-negotiable #6).

**There is no hris analog** (hris has no merge change-log; its `drift.py` is skill-set drift,
a different thing). This is our own invention, derived entirely from data the Phase-4.1 merge
already computes (`MergeProvenance`) plus the source members.

## Key facts you MUST honour (the couplings — get these exact)
- **Member ordering is the merge's canonical order.** `merge_cluster` does
  `ordered = sorted(members, key=lambda jd: jd.model_dump_json())` and EVERY index in
  `MergeProvenance.section_contributors` references THAT order (`core/src/jd_core/bank/merge.py:536`).
  The diff's `member_index` MUST be that same index. **Do not re-derive a second ordering** —
  expose a shared `canonical_member_order(members)` helper in `merge.py` (or import the one
  ordering key) and use it in BOTH places, so the two can never drift ("one rulebook fact, one
  home"). Pin that the diff index and a provenance contributor index refer to the same member.
- **Duty matching is the merge's matching.** Duties are grouped by token-Jaccard ≥
  `harmonization.duty_dedup_jaccard_min`, representative = richest `how_why` then longest
  statement (`merge.py:_merge_duties`). To decide whether a member duty "survived" into the
  draft you MUST reuse the SAME tokenizer (`_tokens`), the SAME `_jaccard`, and the SAME
  threshold — NOT a re-implementation with a different alphabet. Extract a shared helper if
  needed (e.g. `duty_survives(statement, draft_statements, harmon) -> bool`). This repo has
  been bitten repeatedly by "a second copy of the tokenizer that silently disagrees" — pin
  that the diff's kept/dropped verdict AGREES with the merge's grouping on a cluster where a
  duty is genuinely deduped and one where a duty is genuinely dropped by the cap.
- **`bank/render.py` renders draft → text ONLY. Never re-parse it.** `render_sfu_jd_text` is
  lossy on re-parse (documented in its docstring + HANDOFF backlog). 4.3 renders the draft for
  human display and STOPS — build no render→parse loop, assume no round trip.
- **`jd_core` must not import `jd_bank`.** The generator is pure `jd_core` (it consumes only
  `MergedRole` / `SFUJobDescription`, both `jd_core` models) and belongs next to `merge.py`
  in `jd_core/bank/`. Keep the import ratchet green.
- **No new decision knobs unless genuinely required.** The diff reuses the merge's already-
  registered config (`duty_dedup_jaccard_min`, `max_duties`). It should introduce NONE. If a
  new threshold is truly unavoidable, it must be YAML-registered `open` in the SAME PR — but
  the expected outcome is zero new register entries. Do not hardcode a policy number.
- **Determinism + order-invariance, like `merge_cluster`.** The same cluster in any input
  order must yield a byte-identical diff. Pin it (the merge suite has this exact test to copy).

## Files in scope (new unless noted)
- `core/src/jd_core/bank/change_log.py` (NEW) — the pure generator:
  `build_harmonization_diff(merged, members, *, rewrite=None, rules=None) -> HarmonizationDiff`.
  - `rendered_draft = render_sfu_jd_text(merged.draft)`.
  - Re-order `members` by the shared canonical order; for each member build a
    `SourceContribution` (see model): the sections it fed (from `section_contributors`), and
    its duty statements split into `duties_kept` (match a draft duty) vs `duties_folded_or_dropped`.
  - Build the aggregate `removed` list (see `RemovedContent`): every member duty that did not
    survive verbatim as a draft duty, tagged `duty_deduplicated` (it matched a surviving draft
    duty but is not the representative) or `duty_dropped_over_max` (it matched NO draft duty —
    only possible when the `duties_over_max` flag is set); plus, when the `sections_not_merged`
    flag is set, each member's actual `decision_making` / `problem_solving` / `relationships` /
    `position_number` content tagged `section_not_merged`. Reuse `merge._has_unmerged_content`'s
    notion of "unmerged content" — do not invent a second definition.
  - **Optional rewrite folding:** when `rewrite: AntiFabricationRecord | RewrittenDraft | None`
    is passed, append its `scrubbed_skills` as `removed` entries tagged
    `qualification_scrubbed_ungrounded` and its `flagged_duties` as a separate
    `flagged` list (flagged ≠ removed — a flagged duty stays in the draft). Keep the merge path
    fully functional with `rewrite=None`.
  - Pure/deterministic/order-invariant. No I/O.
- `core/src/jd_core/bank/merge.py` (MODIFY, minimal) — expose the shared `canonical_member_order`
  (and, if you extract one, the duty-survival helper) as public functions; refactor
  `merge_cluster` to call them so there is a single source of the ordering + matching. The merge's
  behaviour and its provenance output must stay BYTE-IDENTICAL (its full suite stays green —
  prove it, don't assert it).
- `core/src/jd_core/models/bank.py` (MODIFY) — add frozen (`extra="forbid"`, `frozen=True`)
  value objects next to `MergedRole`:
  - `RemovedContent`: `content: str`, `reason: <Literal of the reasons above>`,
    `member_index: int | None` (None for a rewrite-stage scrub not tied to a member).
  - `SourceContribution`: `member_index: int`, `title: str`, `contributed_sections: tuple[str, ...]`,
    `duties_kept: tuple[str, ...]`, `duties_folded_or_dropped: tuple[str, ...]`.
  - `HarmonizationDiff`: `rendered_draft: str`, `per_source: tuple[SourceContribution, ...]`,
    `removed: tuple[RemovedContent, ...]`, `flagged_duties: tuple[str, ...] = ()`.
    NO approval/canonical/published/score field — it is a descriptive report, not a decision
    (non-negotiable #1). Frozen: it is an audit artifact.
- Tests under `core/tests/` (self-contained — `docs/` + repo-root fixtures NOT mounted).

## Acceptance (all via `make gates` in Docker)
1. **The diff agrees with the merge, pinned by MUTATION.** On a hand-built 2–3 member cluster
   where member A and member B share a near-identical duty (deduped) and a member carries a duty
   the `max_duties` cap drops: assert the surviving duty appears once in `duties_kept` for its
   representative's member and as `duty_deduplicated` for the other; the capped duty appears as
   `duty_dropped_over_max`. **Break the coupling** — make `change_log` tokenize with a different
   alphabet (or a different threshold) than `merge` — and a behavioural assertion goes RED (the
   kept/dropped verdict stops matching the actual draft). A green suite under a divergent
   tokenizer would mean the pin is worthless (HANDOFF's recurring lesson).
2. **`member_index` aligns with provenance.** A test that a section's `section_contributors`
   index and the `SourceContribution.member_index` for the same member point at the SAME member
   (not two orderings). Reversing the input order must not change any index (order-invariance).
3. **"Removed content and why" is complete and correctly reasoned.** Every dropped member duty
   is in `removed` with the right reason; a `sections_not_merged` cluster lists the actual
   decision_making/problem_solving/relationships/position_number content (not just a flag).
   A cluster with nothing removed yields `removed == ()`.
4. **Rewrite folding is optional and correct.** `rewrite=None` → merge-only diff. Passing a
   `RewrittenDraft`/`AntiFabricationRecord` with a scrubbed skill → it appears as
   `qualification_scrubbed_ungrounded`; a flagged duty → it appears in `flagged_duties`, NOT in
   `removed` (flagged ≠ removed).
5. **Determinism + order-invariance** — same cluster, any input order → byte-identical
   `HarmonizationDiff` (copy the merge suite's order-invariance test shape).
6. **Render is display-only** — `rendered_draft == render_sfu_jd_text(merged.draft)`; no code
   path re-parses it.
7. **Merge unchanged** — `merge_cluster`'s output + provenance are byte-identical after the
   refactor; its full existing suite stays green.
8. **No new knobs / register churn** — `make register-check` green with NO new entries (unless a
   knob was genuinely unavoidable and is registered `open` in this PR — justify it if so).
   Editing no rule YAML means `rules_version` is untouched.
9. **Import ratchet** — `jd_core` still does not import `jd_bank`; ruff/black/mypy --strict
   clean; coverage ≥ 80 (repo ~94%).

## Out of scope (do NOT do here)
- Any RUNNER that loads real clusters and writes a change-log artifact over the archive (that is
  a `jd_bank/` follow-up, exactly as the 4.1 merge engine landed before its measurement runner).
  4.3 is the pure generator + its unit tests only.
- The ValidationReport (already produced by the validator; the 4.4 queue assembles it).
- %-rebalance of duty allocations (4.1 follow-up #2), merging the un-merged sections (#4) — the
  change-log REPORTS that they were not merged; it does not merge them.
- The review queue / FastAPI / UI / audit-log / DB persistence (4.4), the composer, any publish.
- Re-parsing rendered text, or any render→parse round-trip (render.py is lossy — display only).

# Task 4.1 — Deterministic harmonization merge engine (pure, no LLM)

**Phase:** 4 (Harmonization & review) · **First task.** Plan §Phase 4.1.
**Type:** NEW build (not a port). hris harmonizes via an LLM prompt only; this is the
deterministic, LLM-free backbone that drafts a canonical role from a cluster's members.
**Model tier:** Opus coder **and** Opus reviewer — semantics-heavy (rulebook policy +
new decision parameters). Do **not** downgrade (subagent-model-strategy.md).

---

## Goal

Given the member JDs of a role cluster, produce a **single harmonized draft**
`SFUJobDescription` **plus provenance**, using pure deterministic functions:

- **section selection** — pick the canonical value for each scalar/text section,
- **duty union / dedup / reorder** — one deduped, coverage-ordered duty list,
- **KSA rebuild** — rebuild Qualifications from the cluster's skill/education/experience
  evidence, keeping what most members require and dropping one-offs.

The output is a **DRAFT** (non-negotiable #1): nothing here approves or publishes. No
DB, no I/O, no LLM. It is the input a human reviewer (4.4) and — later — an LLM rewrite
pass (4.2) act on.

## Why deterministic-first

Provenance must be verifiable before any model touches the text. `provenance.py`
already gives the backbone (`skill_frequency`): a skill most members require is *core*;
a one-off is *incidental*. The merge engine turns that backbone into a full draft so
the LLM pass has a grounded, attributable starting point rather than free-associating.

---

## Files in scope

**New**
- `core/src/jd_core/bank/merge.py` — the pure engine. Lives in `jd_core` (the pure core);
  **must not import `jd_bank`** (the layering ratchet enforces this — do not add a
  re-export that creates a cycle). No I/O, no DB, no Neo4j, no Ollama.
- `core/src/jd_core/rules/harmonization.yaml` — the merge knobs, **hashed digest EXCLUDED**
  (see "Rulebook wiring"). Every non-trivial default is a register entry.
- `core/tests/unit/test_merge.py` (+ split files if it grows) — TDD.

**Modified**
- `core/src/jd_core/models/bank.py` — add frozen value objects `MergedRole` and
  `MergeProvenance` (alongside `JobSignals`/`CanonicalTitle`). `extra="forbid"`.
- `core/src/jd_core/rules/loader.py` — add `Harmonization` rule-file model; register in
  `_FILE_MODELS`, add to `_UNHASHED_FILES`, add `Rules.harmonization`. Shape the file
  **FLAT** so it qualifies for `_FLAT_SURFACE_FILES` (decision-surface hole, see Gotchas).
- `core/src/jd_core/rules/decision_register.yaml` — **HR-167..HR-N**, all `status: open`,
  `provenance: our_invention` (SFU publishes no harmonization policy). Run `make register`.

**Do NOT touch** the approval bar, the parser, the validators, `parsed_jd.py` fields, or
any HASHED rule file. If a merge default seems to need one, STOP and escalate.

---

## Design contract

### Entry point (pure)
```python
def merge_cluster(
    members: Sequence[SFUJobDescription], *, rules: Rules | None = None
) -> MergedRole: ...
```
- `rules` defaults to `get_rules()`.
- **Order-invariant:** the same set of members in any order yields a byte-identical
  draft + provenance. This is a real property — pin it.
- Empty / single-member clusters are valid inputs (single → passthrough-with-provenance).

### `MergedRole` (models/bank.py, frozen, extra="forbid")
- `draft: SFUJobDescription` — the harmonized **draft** (NOT approved; NOT canonical).
- `provenance: MergeProvenance`.

### `MergeProvenance`
- `member_count: int`
- `skill_frequency: tuple[tuple[str, int], ...]` — from `provenance.skill_frequency`.
- `duty_coverage: tuple[tuple[str, int], ...]` — deduped duty → #members it came from.
- per-section contributor attribution (which member indices fed each chosen value).
- `flags: tuple[str, ...]` — HR-eyeball flags (see below). **FLAG, never silently fix.**

### What it computes

1. **Section selection (scalars/text).**
   - `title`: representative of the modal `normalized_title` (deterministic tie-break —
     define it, e.g. shortest raw then lexicographic). Knob `title_policy`.
   - `department` / `grade` / `employee_group`: modal non-null; deterministic tie-break.
     Members disagreeing → a `flag` (upstream veto should make this rare; do not assume).
   - `position_summary`: deterministic representative pick — the member summary best
     fitting SFU's 100–150-word target, most-central on ties. Knob `summary_policy`.
     **No rewrite** — that's 4.2.
   - `additional_context`: knob `additional_context_policy` (default: drop; noisy union).
   - presence booleans (`about_sfu_present`, `territorial_acknowledgement_present`,
     `employment_equity_present`): default **OR across members**, knob
     `boilerplate_presence_policy`. Register note: this flips to "always assert present"
     **iff** HR ratifies composer auto-insert of the footer (HR-pending) — do NOT
     pre-empt that ruling here.

2. **Duty union / dedup / reorder.**
   - Union all `SFUDuty` across members; dedup near-identical **statements** by
     token-Jaccard ≥ `duty_dedup_jaccard_min` (knob). On merge, keep a deterministic
     representative (define the rule — e.g. richest `how_why`, then longest statement)
     and record all contributing members in `duty_coverage`.
   - Reorder by member-coverage desc (core duties first), deterministic tie-break.
   - Respect the model cap (`max_length=12`). If deduped duties > `max_duties` (knob,
     informed by SFU's "3–5 major" guidance) → keep top-by-coverage and **flag**.
   - `frequency` (WJQ) and `how_why` carried on the representative.

3. **KSA rebuild (Qualifications).**
   - Skills/knowledge/abilities: use `build_job_signals(member).skills` +
     `provenance.skill_frequency`. A skill token required by ≥ `core_skill_min_fraction`
     of members is **core** → its representative qualification survives; below → dropped
     (SFU is *minimum-not-desired*, so incidental skills are not carried as "desired").
     Map core tokens back to a representative `SFUQualification` (dedup near-identical
     qual texts the same Jaccard way; modal `modifier`).
   - Education / experience: take the **max bar** across members
     (`education_ordinal` / `experience_years` via `signals`), emit the representative
     education/experience qualification whose parsed bar matches.
   - `security`: union (a security requirement any member states is kept). Register.

### Flags (HR eyeball, never auto-fix)
`grade_disagreement`, `employee_group_disagreement`, `duties_over_max`,
`no_core_skills` (KSA rebuild produced nothing — honest for the ~41% skill-empty case),
`single_member` (nothing to harmonize). Keep the list registered/extensible.

---

## Rulebook wiring (non-negotiable #2)

`harmonization.yaml` decides **how JDs are merged into a draft**, NOT how a JD is
**scored/approved**. So — exactly like `dedup.yaml` / `embeddings.yaml` /
`segmentation.yaml` — it is **registered but EXCLUDED from the `rules_version` digest**
(`_UNHASHED_FILES`). Rationale to state in the loader docstring: a merge-policy change
must not churn the digest that identifies *which rules scored a JD*.

Every knob:
- lives in YAML (never hardcoded),
- has an HR-1xx register entry, `status: open`, `provenance: our_invention`,
- is **mutation-pinned behaviourally** (see Acceptance).

Provisional defaults are fine and expected — they will be **calibrated by a post-run
measurement pass over the real clusters** (a follow-up, mirroring 3.5's measure-after
pattern). Say so in each register entry's `why_it_matters`. Do **not** guess a number
and present it as settled.

---

## Acceptance tests (TDD — failing first, `make gates` green in Docker)

The bar is this repo's hard standard: **a green suite proves nothing about a guard you
have not tried to break.** For every knob, the mutation test must change the shipped
YAML value **and** update the register so the drift alarm is silent — a **behavioural**
test must still go red (HANDOFF "Prove a decision is pinned by MUTATION").

Must cover:
1. **Section selection** — modal picks; deterministic tie-breaks; summary within-range
   policy; presence-boolean OR; disagreement flags fire.
2. **Duty dedup** — near-identical duties collapse, distinct preserved, coverage
   ordering correct; **boundary** mutation on `duty_dedup_jaccard_min` (a pair that
   merges at the shipped value splits one step past it → red).
3. **KSA rebuild** — core skill kept, one-off dropped; boundary mutation on
   `core_skill_min_fraction`; education/experience take the max bar; `no_core_skills`
   flag on the skill-empty case.
4. **Order-invariance** — shuffle members → byte-identical `MergedRole` (pin it; it is
   a real property, not a decoy — make the assertion fail if you sort non-deterministically).
5. **Draft is a draft** — nothing marks it approved/canonical; presence-boolean default
   does not silently satisfy the footer gate.
6. **Validator-as-oracle (honest):** running `evaluate_jd_rules` on the draft asserts
   the true post-state — it **will** trip `SFU-COMP-ABOUT`/footer gates (render/model
   carry booleans, not boilerplate text; see `bank/render.py` caveats). Assert that
   honestly; do **not** assert "approved."
7. **Purity** — the import ratchet stays green (no `jd_bank` import).
8. **Register** — `make register` clean; `make gates` (the `_OFF_SURFACE` surface guard)
   green. Run BOTH — a green `register-check` is not surface coverage.

Fakes/fixtures must be **content-keyed and realistic** (HANDOFF: a batch-index fake made
a whole bug class unwritable; synthetic fixtures hid real crashes in 3.4b). Build member
fixtures from realistic JDFN JDs.

---

## Out of scope (explicit — do NOT do here)

- **%-rebalance of duty allocations.** Allocations are free-text `(NN%)` inside duty
  statements (validator regex, Part-11.6 gate), not a structured field. Rebalancing them
  needs allocation extraction + gate interaction — its own follow-up task. Leave duty
  statements verbatim on the representative.
- **Any LLM rewrite / anti-fabrication guard** — Phase 4.2.
- **Change-log / diff generation** — 4.3. **Review queue / API / audit wiring** — 4.4.
- **Persisting a canonical, DB writes, cluster loading from Postgres** — 4.1 is pure
  functions over in-memory members. The `jd_bank` runner that loads real clusters and
  writes drafts is a separate task.
- **WJQ clusters.** WJQ over-clusters until boilerplate redaction lands (HANDOFF Phase-4
  priority); the engine is exercised on JDFN clusters. WJQ *harmonization* is BLOCKED
  until redaction + `.doc` title extraction land — do not special-case WJQ here.
- **Calibrating the defaults against the archive** — the post-run measurement follow-up.

## Deliverable summary for the reviewer

A pure `merge.py`, `MergedRole`/`MergeProvenance`, a registered+unhashed
`harmonization.yaml` (HR-167..N, all open), and a mutation-pinned test suite. `make
gates` green in Docker; `make register` clean. Report exact knob values + one line each
on why they are provisional and how the follow-up will calibrate them.

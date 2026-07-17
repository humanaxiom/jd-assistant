# Task 4.1-followup — Harmonization merge runner + knob calibration

**Phase:** 4 (Harmonization & review) · **4.1 follow-ups #3 (runner) + #1 (calibrate).**
**Type:** NEW build (a `jd_bank` driver) + a measurement/calibration pass.
**Model tier:** Opus coder **and** Opus reviewer. The runner is mechanical, but it feeds
a **decision-parameter calibration** (the 9 `harmonization.yaml` knobs) — semantics-heavy,
never downgrade (subagent-model-strategy.md). Tier-B escalation rule applies: **STOP and
escalate before moving any knob default; the coder MEASURES, the orchestrator DECIDES.**

---

## Goal

The 4.1 merge engine (`jd_core/bank/merge.py`) is pure in-memory functions with **9
provisional knobs** (`harmonization.yaml`, HR-167..175, all `open`). This task:

1. **Builds `jd_bank/harmonize/`** — a runner that loads the **real JDFN role clusters**,
   reconstructs each member `SFUJobDescription` from Postgres, drives `merge_cluster` at
   scale, and **measures the distributions the 9 knobs cut on**. Report-only; writes an
   artifact; persists nothing, commits nothing (mirror `jd_bank/cluster/`).
2. **Calibrates** the 9 defaults against those distributions and **registers the measured
   values** — killing "provisional default hardens by inertia" (the HR-093/HR-121 lesson).

This mirrors 3.5 exactly: ship the engine provisional, then measure-after and register the
real numbers.

---

## Files in scope

**New — `core/src/jd_bank/harmonize/`** (mirror `core/src/jd_bank/cluster/` module-for-module)
- `runner.py` — `async def run_harmonization(session, *, rules=None, limit=None) -> HarmonizationResult`.
  **Pure of connection management** (caller passes the `AsyncSession`, like `run_clustering`).
- `__main__.py` — DB wiring + CLI (copy `cluster/__main__.py`: `get_settings()` →
  `create_async_engine` → `async_sessionmaker`; **`await session.rollback()`** to make
  read-only intent explicit — no commit, ever).
- `report.py` — a pydantic `HarmonizationSummary` model + `write_summary` (pretty sorted
  JSON) and, if useful for adjudication, a per-cluster CSV. Same shape as `cluster/report.py`.
- `models.py` — result dataclasses (`HarmonizationResult`, per-cluster record).
- `__init__.py`.

**New tests** — `core/tests/unit/test_harmonize_runner.py` (+ integration if a real-PG
testcontainer path is warranted, mirroring the dedup/cluster runner tests).

**Modified**
- `core/src/jd_core/rules/harmonization.yaml` — **only** the knob values the measurement
  warrants moving. Each change mutation-pinned; leave a knob at its default if the data
  supports it (but still record the measurement in the register).
- `core/src/jd_core/rules/decision_register.yaml` — rewrite each of HR-167..175's
  `why_it_matters` to carry the **measured distribution** as evidence (not "provisional, to
  be measured"). Run `make register`.
- `Makefile` — target `harmonize-measure` (template below), `HARMONIZE_ARGS` var, `.PHONY`.
- `docker-compose.yml` — a `harmonize` service under `profiles: ["tools"]`, binding
  `./docs/harmonize:/committed` (create `docs/harmonize/.gitkeep`).
- `HANDOFF.md` — close follow-ups #1 and #3; record the measured numbers.

**Do NOT touch** the merge engine's *logic* (`merge.py`), the approval bar, any HASHED
rule file, the parser, or validators. If calibration seems to need a merge-logic change,
STOP and escalate — that is a new task, not a knob move.

---

## Design contract

### Cluster reconstruction — recompute, do NOT read the CSV
`docs/cluster/cluster-members.csv` keys members by **filename**, not `source_document_id`
— a lossy handoff. Reuse the 3.5 clustering in-process: call `run_clustering` (or its
internals in `jd_bank/cluster/runner.py`) to get `ClusterRecord.members[].source_id`
(UUIDs). Clusters are deterministically recomputable from the edge graph; this is cheap,
reproducible, and avoids a filename→UUID re-lookup.

### Member loading
For each cluster member `source_id`, load its `SFUJobDescription` via the established idiom
(`signals_load.py:89`): `SFUJobDescription.model_validate(ParsedJDRow.parsed)` filtered on
`parser_version == PARSER_VERSION`. `load_signed_corpus` returns `JobSignals`, not the JD
objects — so **extend it or add a sibling loader** that also retains the
`SFUJobDescription` keyed by `source_document_id`. A member whose row fails to validate is
**dropped from the cluster with a counter** (do not crash; the runner is a measurement).

### JDFN-only (WJQ is BLOCKED)
WJQ over-clusters until boilerplate redaction lands (HANDOFF Phase-4 priority) and its
`.doc` titles are lost. **Exclude WJQ from the measurement**: find where `template ∈
{jdfn,wjq,unknown}` lives for a parsed row and restrict to JDFN. A cluster containing any
WJQ member is either excluded whole or its WJQ members dropped — **pick one, state which in
the summary, and count what was excluded** (no silent truncation — HANDOFF standing rule).
Singletons are valid but harmonize trivially (`single_member`); measure them separately so
they do not swamp the multi-member distributions the knobs actually cut on.

### What the runner MEASURES (the whole point — this drives calibration)
Drive `merge_cluster` over every eligible cluster and aggregate. Per knob, surface the
distribution it cuts on so a human can *see* where the default should sit:

| Knob | Measure |
|---|---|
| `duty_dedup_jaccard_min` (0.7) | **Distribution of pairwise duty-statement token-Jaccards** within clusters; deduped-duty count as a function of candidate thresholds (e.g. 0.5/0.6/0.7/0.8/0.9). Find the knee (the 3.3 pattern). |
| `max_duties` (10) | Distribution of deduped-duty counts per cluster; `duties_over_max` rate at 10 vs alternative caps. |
| `core_skill_min_fraction` (0.5) | Distribution of skill-frequency fractions across clusters; #core-skills and `no_core_skills` rate as a function of the fraction. |
| `summary_policy` | Fraction of clusters with ≥1 summary in the 100–150 target; how often the in-range preference **engages** vs falls back to most-central; summary word-count distribution. |
| `title_policy` | Distinct `normalized_title` count per cluster; modal-group size fraction (how dominant the modal role is). |
| `seniority_bar_policy` (max) | Within-cluster education/experience **bar spread**; how often `max` and `modal` would diverge. |
| `additional_context_policy` (drop) | Fraction of members carrying `additional_context` (justifies drop vs longest). |
| `boilerplate_presence_policy` | Per-boolean member agreement/mix rate. |
| `security_policy` (union) | Fraction of clusters with any security qual; distinct-security-count distribution. |

Also aggregate the **flag rates**: `grade_disagreement`, `employee_group_disagreement`,
`duties_over_max`, `no_core_skills`, `single_member`, `sections_not_merged`.

### Determinism / reproducibility
The runner must be **single-process and byte-identical across two runs over the same DB**
(the baseline-reproducibility rule — HANDOFF: any per-run noise, e.g. a heap `repr()` or a
temp path, breaks the audit trail). No `Math.random`, no timestamps in the measured body
(a `generated_at` stamp is fine, like `cluster-summary.json`). Prove it by running twice —
do not assert it.

### The summary artifact
`docs/harmonize/summary.json` — a pydantic model, pretty sorted JSON. Counts + the
distributions above + the rules stamp (`rules_version` + the harmonization knob values it
ran under) + `generated_at`. **Never JD text** (the cluster/dedup artifacts carry
counts/labels/filenames only — hold that line; these are HR records).

---

## Calibration (the decision — orchestrator + reviewer, NOT the coder alone)

After the runner produces `summary.json` over the real archive:
- For each of the 9 knobs, read the measured distribution and decide: **keep** (record the
  measurement as the justification) or **move** (to the measured knee/value).
- **Every move is mutation-pinned**: change the shipped YAML value *and* update the register
  so the drift alarm is silent — a **behavioural** test in `test_merge.py` must still go red
  (HANDOFF "Prove a decision is pinned by MUTATION"). If the merge suite has no behavioural
  pin for a knob being moved, add one.
- Rewrite each HR-167..175 `why_it_matters` to state the measured evidence. `make register`
  clean; `make gates` (`_OFF_SURFACE`) green. Run **both**.

> The coder builds the runner and reports the measured numbers. It must **not** pick new
> knob values on its own — that is a decision-parameter change (Tier-B escalation rule).

---

## Acceptance tests (TDD — failing first, `make gates` green in Docker)

1. **Runner unit tests** with **content-keyed, realistic** fixtures (HANDOFF: a batch-index
   fake made a bug class unwritable; synthetic fixtures hid real 3.4b crashes). Build small
   in-memory clusters of realistic JDFN `SFUJobDescription`s and assert the aggregation is
   correct (a known duty-Jaccard distribution, a known core-skill fraction, a known
   `duties_over_max` count).
2. **JDFN filter** — a WJQ member in an otherwise-JDFN cluster is handled exactly as the
   summary claims (excluded whole or dropped), and the exclusion is **counted**, not silent.
   Pin it: flip the filter → the count changes.
3. **Drop-not-crash** — a member row that fails `model_validate` is dropped with a counter,
   the run completes. Pin the counter.
4. **Read-only** — the runner never commits (mirror the cluster runner's rollback intent);
   assert no write escapes. Mutation-verify: make it commit → a guard/test goes red.
5. **Determinism** — two runs over the same fixture DB produce a byte-identical summary body
   (modulo `generated_at`). Pin it against a member-order shuffle (the engine is
   order-invariant; the *runner's* cluster/member ordering must be too).
6. **Calibration pins** — for every knob whose default MOVES, a behavioural `test_merge.py`
   test goes red when the value is reverted-with-register-silenced.
7. **Register** — `make register` clean **and** `make gates` `_OFF_SURFACE` guard green.

---

## Runner Makefile template (verbatim shape — copy `dedup-role`)

```make
harmonize-measure:  ## Drive merge_cluster over real JDFN clusters; measure the 9 knobs (needs ingest + cluster deps)
	docker compose run --rm -T harmonize python -m src.jd_bank.harmonize $(HARMONIZE_ARGS)
	@echo "✅ harmonization measurement written to docs/harmonize/summary.json"
```
Register the `HARMONIZE_ARGS` var + `.PHONY` entry (HANDOFF records copy-pasting the wrong
`*_ARGS` name as a past bug). Compose `harmonize` service = the standard `profiles:
["tools"]` block: `build ./core`, `<<: *app_env`, `volumes: [./core:/app,
./docs/harmonize:/committed]`, `depends_on: postgres (+neo4j if the cluster recompute needs
it) healthy`, `command: ["python","-m","src.jd_bank.harmonize"]`.

---

## Out of scope (explicit — do NOT do here)

- **%-rebalance of duty allocations** (4.1 follow-up #2, its own task) — leave duty
  statements verbatim.
- **Merging `decision_making`/`problem_solving`/`relationships`/`position_number`** (follow-up
  #4) — the engine flags `sections_not_merged`; measure the flag rate, do not merge them.
- **Any LLM rewrite** (4.2), **diff/change-log** (4.3), **review queue/API** (4.4).
- **Persisting a `Cluster` row or any canonical** — report-only, like 3.5.
- **WJQ harmonization** — BLOCKED on redaction + `.doc` titles; JDFN only.
- **Changing merge.py logic** — if the data says the logic is wrong, escalate; don't patch.

## Deliverable summary for the reviewer

A new `jd_bank/harmonize/` runner (read-only, deterministic, JDFN-only), a
`docs/harmonize/summary.json` measured over the real archive, the 9 register entries
rewritten with measured evidence (and any warranted default moves, each mutation-pinned),
and a mutation-pinned test suite. `make gates` green in Docker; `make register` clean.
Report each knob: measured distribution → keep-or-move → the pin that proves it.

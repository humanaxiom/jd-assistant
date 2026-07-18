# Phase 4.4a — canonical-draft PRODUCER (clusters → persisted DRAFT canonical_jds)

## Goal
The first slice of the review queue (Phase 4.4): a runner that turns the real JDFN role
clusters into **persisted `canonical_jds` DRAFT rows** — the work-list the 4.4b review
service and the 4.4d UI will consume. Per cluster it drives the Phase-4 pipeline end to
end (4.1 merge → 4.2a rewrite → 4.2b audit → 4.3 change-log → validator) and persists the
result as a DRAFT. **Nothing is ever published or approved (non-negotiable #1).** Re-running
the producer is **idempotent** and must **never clobber a canonical a reviewer has already
acted on** (the 3.5 cascade-delete lesson + the 3.3 prune-deletes-data lesson).

## Reuse the harmonize-measure runner's cluster spine (one home)
`jd_bank/harmonize/runner.py::run_harmonization` already establishes the exact loading
spine — copy it, do not re-invent:
`run_clustering(session)` → `load_member_jds(member_ids)` → per cluster: sort members by
`source_id`, split JDFN vs WJQ via `is_wjq_member` (WJQ excluded + counted), JDFN-only.
Import `is_wjq_member` / `member_has_frequency` from the harmonize runner (don't fork them).
**WJQ stays excluded** (blocked on the WJQ boilerplate/title follow-ups — Phase 3).

## Key facts you MUST honour
- **The cluster id is content-derived and STABLE.** `run_clustering` sets each cluster's id
  via `cluster/models.py::cluster_id_for(sorted member storage_refs)` (a `uuid5`). Persist
  `clusters.id = that id` (NOT the table's random `uuid4` default) so a re-run maps to the
  SAME cluster row. This is the idempotency key.
- **`validation_reports` is parsed_jd-keyed and CANNOT hold a canonical's validation.**
  `validation_reports.parsed_jd_id` is a NON-nullable FK to `parsed_jds`; a canonical draft
  is not a parsed_jd. So persist the validator roll-up INSIDE the canonical row's
  `change_log` JSONB and leave `canonical_jds.validation_report_id = NULL`. (A dedicated
  canonical validation_reports row is a deliberate follow-up, noted below — do NOT widen the
  schema here.)
- **`canonical_jds` shape** (`jd_bank/db/models.py`): `id`, `cluster_id` (FK), `version`,
  `status` (`CanonicalStatus` — ALWAYS `DRAFT` here), `content` (JSONB = the final draft
  `SFUJobDescription`), `source_document_ids` (JSONB = the cluster members), `change_log`
  (JSONB = the structured provenance/review packet, see below), `validation_report_id`
  (NULL). `uq_canonical_version` = `(cluster_id, version)`.
- **The LLM passes are INJECTED and mockable.** `rewrite_merged_role` (4.2a) and
  `audit_quality` (4.2b) take a `ChatClient`. The producer accepts an injected
  `client: ChatClient | None`. **`None` → deterministic-only** (persist the 4.1 merge draft;
  rewrite/audit skipped and recorded). **Provided → full pipeline.** `make gates`/CI pass a
  content-keyed FAKE client (NEVER a live endpoint — ADR-003); the live run is opt-in/local.
- **The LLM passes are BEST-EFFORT.** A model failure on one cluster must NOT abort the run
  and must NOT lose the deterministic draft (mirror hris `evaluate_jd_quality`): on a rewrite
  failure, fall back to the merge draft; the audit is advisory, skip it on failure. Isolate +
  count per-cluster failures (the embed runner's isolate-and-skip pattern). Persist whatever
  you have.
- **Docker-only / Ollama on `aria-gb10-2`.** `make gates` must not depend on a live endpoint;
  live golden opt-in/local-only, deselected in pytest `addopts`, the Makefile, AND CI
  (`--strict-markers`) — mirror the embed/rewrite guards exactly.
- **`jd_core` must not import `jd_bank`** — the producer is `jd_bank` (it may import `jd_core`
  merge/rewrite-consumer/validator freely). Keep the ratchet green.

## The persistence contract (the invariant-critical core — the reviewer will hammer this)
Per JDFN cluster, in one transaction the CALLER owns (the runner does not commit unilaterally
mid-loop in a way that half-writes — follow the ingest driver's per-item SAVEPOINT discipline;
a per-cluster failure isolates that cluster, never corrupts the rest):
1. **Upsert the `clusters` row** keyed on the content-derived `cluster_id`: select-or-insert
   (its label/employee_group/level_band/members/constraint_metadata snapshot). Never a blind
   insert (that duplicates on re-run).
2. **No-clobber guard.** Look up the existing `canonical_jds` for this `cluster_id`. If one
   exists with `status != DRAFT` (published/archived) **OR** it has ANY `review_actions` rows,
   the producer LEAVES IT UNTOUCHED and records `skipped_reviewer_touched`. An approved/edited
   canonical is a human artifact — the producer must never overwrite or delete it (NN #1 + the
   append-only audit trail, NN #6). Only an untouched DRAFT may be refreshed.
3. **Persist / refresh the DRAFT.** For a cluster with no canonical, or only an untouched
   DRAFT: write (or update in place) a `canonical_jds` row with `status=DRAFT`,
   `content = final_draft`, `source_document_ids = members`, `change_log = <packet>`,
   `validation_report_id = NULL`. Idempotent: re-running with the same rules + members + client
   yields the same persisted DRAFT (the deterministic parts are byte-identical; do not create a
   second version row for an unchanged draft).
4. **Append to `audit_log`** (append-only, never update/delete): one row per draft
   persisted/refreshed (e.g. `event_type="canonical_draft.persisted"`, `entity_type="canonical_jd"`,
   `entity_id=<id>`, `actor="producer"`, `payload` = counts/flags, NEVER incumbent PII), and one
   for a `skipped_reviewer_touched`. This is the provenance trail (NN #6).

**The `change_log` packet** (JSONB) is what makes the row a self-contained reviewer packet —
store: the 4.3 `HarmonizationDiff` (per_source / removed / flagged_duties), the `MergeProvenance`
(flags / skill_frequency / duty_coverage), the 4.2a `AntiFabricationRecord` (if the rewrite ran),
the 4.2b `QualityAudit` advisory issues (if the audit ran), and the **validator roll-up**
(score, grade, issues, and the `GateDecision` — approvable-or-not + blocking gates). `content`
carries JD prose (that is its purpose — these are JDs, incumbent names already normalized at
ingestion; NOT the counts-only rule that governs committed CSV artifacts).

## Files in scope (new unless noted)
- `core/src/jd_bank/canonical/__init__.py`
- `core/src/jd_bank/canonical/runner.py` — `run_canonical_producer(session, *, client=None,
  rules=None, limit=None) -> CanonicalProducerResult`: the loop above. Deterministic + single-
  process for the deterministic parts; idempotent persistence.
- `core/src/jd_bank/canonical/models.py` — `CanonicalProducerResult` (COUNTS only: clusters
  seen / drafts persisted / drafts refreshed / skipped_reviewer_touched / rewrite_failures /
  audit_failures / wjq excluded / single vs multi, + the rules/prompt/model stamps). Frozen.
- `core/src/jd_bank/canonical/__main__.py` — the entrypoint (mirror
  `harmonize/__main__.py`); writes `docs/canonical/summary.json` (**counts + stamps only,
  never JD text / never a member id list that reconstructs prose**) + a `.gitkeep`-guarded dir.
- `Makefile` — `make canonical-drafts JD_ARCHIVE_PATH=...` (real run, needs Ollama — local-only)
  and the live golden marker deselected in addopts/Makefile/CI. A deterministic-only path
  (`client=None`) must be runnable without Ollama.
- `docker-compose.yml` — a `canonical` compose service (mirror `harmonize`).
- Tests under `core/tests/` — unit (pure per-cluster logic + no-clobber + idempotency with a
  fake session/client) AND integration (real Postgres via testcontainers — the `gates` service
  supports it; assert the actual rows + the no-clobber guard + append-only audit). Content-keyed
  fake `ChatClient` (never positional — the documented fake-hygiene landmine).

## Acceptance (all via `make gates` in Docker; live golden separate)
1. **DRAFT-only, pinned.** Every `canonical_jds` row the producer writes has `status=DRAFT`;
   assert it never writes `published`/`archived` and sets no approval field. A test that the
   producer, run over a cluster, produces a row a human still has to approve.
2. **No-clobber, pinned by MUTATION.** Seed a `canonical_jds` for a cluster with
   `status=PUBLISHED` (and separately: a DRAFT with a `review_actions` row). Re-run the producer
   → the seeded row is byte-identical afterwards and `skipped_reviewer_touched` is counted.
   **Break the guard** (let it overwrite) → a behavioural assertion goes RED (the published
   content changed / the count is wrong). This is the highest-risk property — a green suite with
   the guard removed means the pin is worthless.
3. **Idempotent.** Running the producer twice over the same corpus + rules + fake client yields
   the same rows (no duplicate clusters, no duplicate canonical versions, the second run reports
   0 newly-persisted / N refreshed-or-unchanged). Cluster rows keyed by the stable `cluster_id`.
4. **LLM best-effort + injected.** `client=None` → the deterministic merge draft is persisted
   (rewrite/audit recorded as skipped). A fake client that RAISES on rewrite → the merge draft
   is still persisted and `rewrite_failures` is counted (the run does not abort). A fake client
   that returns a valid rewrite → `content` is the rewritten draft and the `change_log` carries
   the anti-fab record. The audit failing → advisory audit omitted, draft still persisted.
5. **Append-only audit.** Each persisted/refreshed draft and each skip writes an `audit_log`
   row; the producer never updates/deletes an audit row. (Integration test asserts row counts.)
6. **Reviewer packet is reconstructable.** The `change_log` JSONB round-trips to the 4.3 diff +
   merge provenance + validator roll-up (score/grade/issues + `GateDecision`); assert the
   `GateDecision` is `approved=False` while boilerplate gates block (validator-as-oracle, NN #3
   — the draft is honestly un-approvable until a human acts).
7. **Cluster spine reused** — `is_wjq_member` etc. imported from the harmonize runner; WJQ
   excluded + counted; JDFN-only. No second copy of the WJQ proxy.
8. **Docker-only guards** — `make gates` never calls Ollama; the live golden is deselected in
   addopts + Makefile + CI; `make canonical-drafts` opt-in/local. `summary.json` is counts-only.
9. **Import ratchet** green; ruff/black/mypy --strict clean; coverage ≥ 80.

## Out of scope (do NOT do here)
- The review SERVICE (list-queue API / approve / reject / edit / override) → 4.4b. The producer
  only PRODUCES drafts; it applies no reviewer decision.
- FastAPI routes → 4.4c; the server-rendered UI → 4.4d.
- A dedicated canonical `validation_reports` row / schema change (roll-up lives in `change_log`
  for now) — record as a follow-up, do not widen the schema.
- %-rebalance (4.1 #2), merging the un-merged sections (4.1 #4), WJQ (blocked), the composer,
  any publish/approve path, any new decision knob (reuse the registered pipeline config; if one
  is genuinely unavoidable, register it `open` in this PR and justify).

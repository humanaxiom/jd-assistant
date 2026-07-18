# Phase 4.4b — the review SERVICE + audit (domain layer, no HTTP)

## Goal
The consumer half of the review queue: a domain service over the DRAFT `canonical_jds` rows
the 4.4a producer persists. It lists the queue, assembles a reviewer packet, and applies the
four reviewer decisions — **approve / reject / edit / override** — writing the `canonical_jds`
status transition + a `review_actions` row + an **append-only** `audit_log` row. **NO HTTP**
(routes are 4.4c; UI is 4.4d). This is where Phase 4's human-approval spine lives, so the
invariants below are the whole point of the task.

## The invariant spine (this is the task — everything else is plumbing)
- **NN #1 — nothing publishes without an explicit human approve of a PERMITTED decision.**
  `approve` may set `status=PUBLISHED` **only** when the gate decision permits it. A draft with
  a blocking, un-overridden gate CANNOT be approved — `approve` RAISES and publishes nothing.
  The service is the ONLY publish path; it never auto-publishes.
- **Validator-as-oracle on the CURRENT content (NN #3).** `approve` and `edit` RE-VALIDATE the
  canonical's actual `content` (reconstruct `SFUJobDescription`, flatten via the shared
  `jd_bank/jd_text.py::flatten_jd`, run `evaluate_jd_rules` + `score_issues` + `evaluate_gates`).
  **Never trust the roll-up stored in `change_log`** — a reviewer edit could have reintroduced a
  blocking issue, and a stale stored `GateDecision` would let it through. The stored roll-up is
  for DISPLAY only.
- **An override REQUIRES a written reason (NN #1).** Reuse `jd_core/quality/gates.py::apply_overrides`
  — it already raises `GateOverrideError` on an unreasoned override, a non-overridable gate, a
  not-blocking gate, or a double override. Every applied override is persisted as its own
  `review_actions` row with `action=OVERRIDE` and the NON-NULL `reason`; the `audit_log` records
  each waiver. A `GateOverride` cannot be constructed without a reason (structural), and the
  service re-checks — do not add a second, weaker path.
- **Append-only audit (NN #6).** Every decision writes exactly the `audit_log` rows it should and
  NEVER updates/deletes one. Payloads carry ids/counts/gate-ids/reasons — the reason IS the
  record — but no incumbent PII beyond what a JD legitimately contains.
- **Legal transitions only.** `approve`/`reject`/`edit` act only on a canonical that is still a
  live DRAFT; approving/rejecting an already-`PUBLISHED`/`ARCHIVED` canonical, or acting on a
  missing id, RAISES (a typed error), never silently no-ops or double-publishes. Pin the
  double-approve/stale-status case.

## Status + action mapping (JD Bank's own vocab — NOT hris's proposed/approved/retired)
- **approve** → `status=PUBLISHED`; `ReviewAction(APPROVE, reviewer_id)` + one
  `ReviewAction(OVERRIDE, reason)` per applied override; audit rows. Publishes iff the decision
  (after overrides) is `approved=True`.
- **reject** → `status=ARCHIVED`; `ReviewAction(REJECT, reviewer_id, reason)`; audit row.
- **edit** → creates a NEW `canonical_jds` **version** (`version+1`, `status=DRAFT`) with the
  reviewer's edited content, re-validated (fresh roll-up in `change_log`); the prior version is
  superseded (leave it or archive it — pick one, pin it, say why). `ReviewAction(EDIT, reviewer_id,
  reason, payload=<what changed>)`; audit row. **This is where a v2 first appears** — fold in the
  4.4a follow-up: the "latest version per cluster" lookup must `order_by(version desc)` so the
  producer's no-clobber and the packet both see the newest, not a stale v1.
- **override** is supplied TO `approve` (a list of `GateOverride`), not a standalone status change.
  (The `OVERRIDE` review-action rows are written by `approve` as above.)

## Files in scope (new unless noted)
- `core/src/jd_bank/review/__init__.py`
- `core/src/jd_bank/review/service.py` — the operations, each `async def ...(session, ...)`:
  - `list_review_queue(session, *, limit=None) -> tuple[ReviewQueueItem, ...]` — the live DRAFT
    canonicals needing eyes, ordered deterministically (needs-eyes-first is fine — e.g. by whether
    the stored decision is blocked, then created_at). Counts/labels only in the item; the full
    draft is fetched per-canonical.
  - `get_review_packet(session, canonical_id) -> ReviewPacket | None` — the draft `content` + the
    `change_log` packet (4.3 diff / `removed` / merge provenance / advisory audit) + a FRESHLY
    recomputed `GateDecision` (validator-as-oracle — do not surface a stale stored one as the
    authority). None if missing.
  - `approve(session, canonical_id, *, reviewer_id, overrides=()) -> CanonicalJD` — re-validate →
    `evaluate_gates` → `apply_overrides` → publish IFF permitted, else raise `ReviewError`. Writes
    the APPROVE + OVERRIDE review actions + audit. Caller owns the transaction (mirror the
    producer/ingest driver — the service does not commit unilaterally).
  - `reject(session, canonical_id, *, reviewer_id, reason) -> CanonicalJD` — archive + review action
    + audit. `reason` required (a reject with a blank reason raises — a rejection is a recorded
    decision).
  - `edit(session, canonical_id, *, reviewer_id, new_content, reason) -> CanonicalJD` — new DRAFT
    version, re-validated, + review action + audit.
- `core/src/jd_bank/review/models.py` — frozen (`extra="forbid"`) `ReviewQueueItem`,
  `ReviewPacket`, and a typed `ReviewError` / reuse of `GateOverrideError`. No approval field
  lives on a value object that isn't the DB row.
- Tests under `core/tests/` — UNIT for the pure decision logic where separable; INTEGRATION
  (testcontainers Postgres) for the transitions + append-only audit + the no-publish-while-blocking
  and override-needs-reason pins. Seed drafts via the 4.4a producer (with a fake `ChatClient`) or
  by direct insert — either is fine; prefer exercising the real producer for one end-to-end path.

## Acceptance (all via `make gates` in Docker)
1. **NN #1, pinned by MUTATION.** A draft whose fresh `GateDecision` blocks (e.g. the boilerplate
   gates, which a producer draft trips) CANNOT be approved: `approve` with no overrides RAISES and
   the row stays `DRAFT` (assert status unchanged, no APPROVE review action, no PUBLISH audit).
   **Break the guard** (let approve publish despite blocking) → a behavioural assertion goes RED.
   A draft that IS permitted (all gates clear, or every blocker overridden) → `PUBLISHED`.
2. **Override needs a written reason, pinned.** `approve` with a `GateOverride` for a real blocking
   overridable gate + a reason → publishes and writes an `OVERRIDE` review action carrying the
   reason + an audit row. An override of a NON-overridable gate, or a not-currently-blocking gate,
   RAISES (`GateOverrideError`) and publishes nothing. (A reasonless `GateOverride` can't even be
   constructed — assert that too.)
3. **Re-validate on approve/edit (validator-as-oracle).** Edit a permitted draft's content to
   REINTRODUCE a blocking issue → the subsequent `approve` RAISES (the service recomputed gates
   from the edited content, not the stale stored decision). Pin that the decision comes from the
   current content: a test where the stored `change_log` decision says approvable but the current
   content is not → approve refuses.
4. **Append-only audit + review actions.** Each of approve/reject/edit writes the right
   `review_actions` + `audit_log` rows; the service never updates/deletes an audit row (assert row
   counts accrue across a sequence). A reject archives; an edit mints `version=2, status=DRAFT`.
5. **Legal transitions.** Approving/rejecting a missing canonical → typed error; approving an
   already-PUBLISHED or ARCHIVED canonical → typed error (no double-publish). Pin the stale-status
   case.
6. **Latest-version lookup.** After an edit (v2), `get_review_packet` and the producer's no-clobber
   lookup resolve to v2 (`order_by(version desc)`), not v1. (This closes the 4.4a multi-version
   follow-up — do it here where v2 first exists.)
7. **No new decision knob / no register churn** (`make register-check` green; `rules_version`
   untouched). `jd_core` does not import `jd_bank`. ruff/black/mypy --strict clean; coverage ≥ 80.

## Out of scope (do NOT do here)
- FastAPI routes / HTTP (4.4c), the server-rendered UI (4.4d), auth / real reviewer identity
  (`reviewer_id` is a caller-supplied string — the pilot model).
- The producer (4.4a, done), the composer, %-rebalance, un-merged-section merging, WJQ.
- Any new rule/knob (reuse `evaluate_gates`/`apply_overrides`/the validator). A schema change to
  `canonical_jds`/`review_actions`/`audit_log` (the tables already model everything needed) — if
  you believe one is genuinely required, STOP and escalate rather than migrate.
- Re-opening a published/archived canonical (a later task if the pilot needs it) — record it, don't
  build it.

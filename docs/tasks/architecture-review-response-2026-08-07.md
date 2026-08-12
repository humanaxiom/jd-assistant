# Response to the external architecture review (CodeX, 2026-08-07)

**Status:** plan only — no code changed. **Inputs:** `CodeX/ARCHITECTURE_DESIGN_CRITIQUE.md`,
`CodeX/plan.md`, `CodeX/HR_DEMO_SCRIPT.md`. **Every claim below was re-verified against the code
before being planned around**; an unverified critique finding is worth no more than an unverified
subagent report. Verdicts and evidence are in §3.

## 1. Headline

The review is **substantially correct and worth acting on**. Of its eleven checkable claims, nine
are confirmed, two are partly true and none is false. It also **understates** its single most
serious finding, and it **misframes** the governance problem in a way that makes the HR ask look
impossible when it is merely large.

Two corrections to our own prior beliefs came out of this review, both recorded here because they
were load-bearing:

- **CI is NOT billing-blocked.** It has been green on every commit, including `main`
  (run `31199851819`, 9m34s). PR #81 **merged** to `main` as `f26b059`. Several docs still assert
  the block and instruct future sessions to "merge locally per ADR-006" — that instruction is now
  wrong and is corrected in this pass.
- **The README/Flask claim is real, and our suspicion that it was stale was wrong.** `3e32103`
  removed the Flask service, dependency and package but touched `README.md` by only four lines and
  never touched the Mermaid diagram. Eight live references remain across `README.md`,
  `DEVELOPER_GUIDE_1.md`, `harness-claude-code/CLAUDE.md`, `docs/adr/002`, and `.env.example`.

## 2. Priority order

Re-sequenced from `CodeX/plan.md`. The review's ordering is defensible; the changes below are
where evidence moved an item.

### P0 — before the pilot is exposed to anyone

**P0.1 — Close the JSON API authorization hole. This is a live breach of NN #1, not hardening.**
`jd_bank_router` (`/jd-bank`) and the legacy harness routes carry **no gate**, and there is no
middleware — verified: `grep add_middleware` finds nothing. With `CAS_ENABLED=true`, an
unauthenticated `POST /jd-bank/review/{id}/approve` reaches the review **service** and is turned
away only by *business* rules (wrong status / blank reason), never by auth. On a gate-clean DRAFT
it would **publish**.

The review missed the aggravator: `review/service.py` writes `actor=reviewer_id` — the
**attacker-supplied string** — into the hash-chained `audit_log`. The chain stays cryptographically
intact while attesting to a forged identity. So this reaches **NN #6 (provenance)** as well as
NN #1.

Scope: derive actor from the session on every state-changing route; delete body-supplied
`reviewer_id`; an automated authorization matrix over every route × method (today **no test pins
either behaviour**); CSRF for cookie-authenticated state changes. Also correct `main.py`'s note
that this is "ADR-008 phase 2" — ADR-008 records phase 2 as **DONE**, so the note has outlived its
accuracy and reads as a plan when it is a gap.

**P0.2 — Make the production-unsafe posture fail closed.** `settings.py` claims *"a startup check
refuses `cas_enabled` + a dev-fake user together"*. **That check does not exist** — no
`model_validator`, no `ValueError`, no hits outside the three files that read the flag. A comment
describes a control that was never built. Meanwhile `cas_enabled=False` short-circuits *before any
cookie is read* and returns a transient **admin** — every cookieless request from anywhere is a
full administrator. `.env.example` contains no auth keys at all, so an operator following it
deploys exactly that.

Scope: a real startup invariant refusing boot without CAS, secure cookies, non-default secrets and
an approved inference host; auth keys in `.env.example`; split liveness from dependency readiness.

> **Deliberately NOT P0:** committed dev-compose credentials, `--reload`, bind-mounted source,
> exposed data ports. All confirmed, all normal for a dev compose with no production overlay. The
> review lists them at the same weight as the CAS default; they are not the same severity.

### P1 — during the pilot

**P1.1 — The author submission dead-end.** Submit commits the draft, then redirects to a
reviewer-only page → **403**. No data loss, but `default_new_user_role` is `author`, so this is the
*default* first-time experience: work saved, user told they are forbidden, no way to see it again.
There is no author-scoped status route anywhere. Cheap, and the pilot's first impression.

**P1.2 — Per-draft harmonization provenance. Raised from the review's P2.** `seniority_bar_policy:
max` is registered (HR-175), configurable, and small in blast radius (~77 of ~1,801 clusters, ~4.3%).
That part is fine. The gap is that a reviewer reading one draft sees a master's requirement with
**no indication that 9 of 10 sources said bachelor's** — `RemovedReason` has no merge-stage
qualification-drop value and `MergeProvenance.flags` has no bar-disagreement flag. The divergence
is measured only at corpus level. The human reviewer is the NN #1 control; they cannot rule on what
they cannot see. **This is a review-integrity blocker, which is why it moves ahead of the
scalability work.**

**P1.3 — Tier the decision register before the HR workshop. This is our disagreement with the
review.** See §4.

### P2 — makes the pilot's result mean something

**P2.1 — The CUPE/WJQ scope packet** (§5), including the *unknown-group* gap that is ours to close,
not HR's.
**P2.2 — HR-adjudicated benchmark** (review #3, adopted as written). Inter-rater agreement,
per-rule precision/recall, false blocks, fairness slices. This is what converts "internally
consistent" into "useful and fair", and it is the only item that can retire the "tests prove
consistency, not validity" criticism.
**P2.3 — Documentation correctness sweep:** the 8 Flask references; the CI-blocked instruction; the
ADR-008 phase-2 note; `dashboard.py`'s "over all 14,565" where **14,522** were scored (43 skipped);
`settings.py`'s phantom startup-guard comment.

### P3 — production-grade operations

**P3.1 — Run manifests and observability** — adopted, but **scoped down from the review's #4.**
Its "non-atomic database-to-queue handoff" is real and narrow: there are exactly **two**
`enqueue_job` sites, both in the inherited harness API, and **no JD Bank pipeline stage uses arq at
all** (ingest/embed/dedup/cluster/harmonize are compose services). A transactional outbox is
therefore not the pressing need. The real need is run state, version manifests, resumability and
stage observability for the `make`-target pipeline.
**P3.2 — Extractor version in parse identity; logical source identity with current/superseded
state; persist EXACT dedup edges** (already on our backlog; `run_tier1()` exists with zero
non-test callers).
**P3.3 — Retrieval scalability** — tokenizer-aware chunking, ANN candidate generation for the
quadratic role-equivalence bucket, embed-stamp compatibility enforced at query time (a gap we
recorded ourselves in Phase 5.9).
**P3.4 — Composition/isolation** — `get_session` → `api/deps.py`; separate Neo4j agent-memory from
HR retrieval; audit tamper-*resistance* via least-privilege DB roles.

## 3. Verdicts on the review's claims

| # | Claim | Verdict |
|---|---|---|
| 1 | Incomplete API authorization | **CONFIRMED — exploitable; understated** |
| 2 | Author submit → 403 | **CONFIRMED** — no data loss |
| 3 | README describes a Flask frontend | **CONFIRMED, not stale** — 8 locations |
| 4 | Production config (7 sub-claims) | **All 7 CONFIRMED**; severity flattened |
| 5a | Health endpoint ignores dependencies | **CONFIRMED** |
| 5b | Live-model tests self-skip | **PARTLY TRUE — misframed** |
| 5c | Non-atomic DB→queue handoff | **CONFIRMED but narrow** |
| 5d | EXACT dedup edges synthesized | **CONFIRMED** — already on backlog |
| 5e | Stale hard-coded corpus counts | **PARTLY TRUE — not stale** |
| 5f | Late imports conceal a circular dep | **CONFIRMED as fact, wrong verb** |
| 6 | Harmonization inflates requirements | **CONFIRMED** — real gap is provenance |

### Where the review is off the mark

- **5b — "live-model tests do not function as operational canaries."** They were never claimed to
  be. They are deselected twice over (`pyproject.toml` `addopts`, plus `-m "not live"` in the
  Makefile and CI) and run only via opt-in targets. The residual risk is real but narrower: those
  opt-in targets **exit 0 when everything skipped**, so a green golden run is not evidence the
  model ran.
- **5c — the outbox.** Framed as pipeline-wide; it is legacy-harness-only. Priority drops
  accordingly.
- **5e — "stale hard-coded corpus counts."** Two literals reach a user and **both are correct**
  (`source_documents` = 14,565 verified live). The only defect is `dashboard.py` saying "over all
  14,565" when 14,522 were scored. Drift *risk*, not a wrong number.
- **5f — "conceal."** The cycle is documented in a comment at the import site and the fix is
  pre-scoped on our backlog. It is known debt, not concealment.
- **4 — severity flattening.** Committed dev credentials are listed alongside the CAS-off default.
  The first is unremarkable for a dev compose; the second grants anonymous admin.
- **§2 of its plan — the 197 framing.** See below.

### What the review missed

1. The **audit-chain actor forgery** consequence of P0.1.
2. The **startup guard that `settings.py` claims and does not have**.
3. **31.9% of the archive has no parsed `employee_group`** (§5).
4. The register's **policy-vs-plumbing conflation** (§4).

## 4. The "197 open decisions" finding — correct, but the wrong denominator

The review reports 197 open, 0 ratified, and proposes bundling all 197 into 12 HR approval
packages. The count is right and **iteration is not ratification** — `ratified` requires
`decided_by`/`decided_on`/`decision_note`, an actual SFU HR ruling. No amount of engineering moves
that counter, by design.

But the register **conflates HR policy with engineering plumbing**, and that is why the ask looks
impossible:

| provenance | count | | top config files | count |
|---|---|---|---|---|
| `our_invention` | **106** | | `comparison.yaml` | **41** |
| `prior_calibration` | 72 | | `hay_signals.yaml` | **16** |
| `sfu_rulebook` | 19 | | `segmentation.yaml` / `dedup.yaml` | 13 / 13 |

**57 of 197 (29%) sit in the comparison / Hay-signals adapter**, which ADR-007 defines as derived
signals and which the system itself disclaims as *not formal classification*. Another 8 are
`embeddings.yaml` retrieval knobs — the `max_matches: 5` and `timeout_seconds: 5.0` kind. **HR
should never be asked to rule on an embedding timeout.**

Roughly **55–60** entries actually touch the approval bar (`gates`, `scoring`, `thresholds`,
`qualifications`, `quality`, `coded_terms`, `boilerplate`, `titles`).

**Plan:** add a **tier** to each register entry before the workshop —
`hr_policy` (HR must rule) · `hr_informed` (HR should see, engineering owns) · `technical`
(engineering owns outright, no HR signature). Keep every entry and every ID; change only who is
asked. Then apply the review's 12 approval packages **to the `hr_policy` tier only**. HR sees ~60
real calls with measured impact, not 197 rows including vector-index tuning.

This does not weaken governance — nothing becomes unregistered, and the standing rule ("if a
default looks wrong, register it `open`, don't quietly patch it") is untouched. It makes
ratification *achievable*, which is the actual blocker.

## 5. CUPE — the review is right that it is out, and there is a third bucket

Measured over 14,522 current-parser JDs:

| group | JDs | share | status |
|---|---|---|---|
| JDFN (apsa/apex/poly) | 5,416 | 37.3% | **served** |
| **cupe** | **4,440** | **30.6%** | **excluded** — HR-194, `open` |
| **`employee_group` not parsed** | **4,630** | **31.9%** | **undeterminable** |

The exclusion is deliberate and defensible: the validator can only score the JDFN template, so
authoring or scoring a CUPE JD guarantees a category-error mis-score (HR-143/HR-194). Serving CUPE
is a real project — it needs an HR-defined WJQ quality bar *first*, then an oracle, then extraction
work (WJQ boilerplate and missing titles currently distort clusters; the two biggest flagged
clusters are template artifacts).

**The third bucket is ours, not HR's.** That 31.9% is exactly the parser's residual — v3 recovers
`employee_group` for 68.1%. For a third of the archive we cannot say which group a JD belongs to,
so "the Bank serves JDFN" is currently **unfalsifiable** for it. Closing that is engineering work
with no HR dependency, and it should precede the CUPE scope conversation — otherwise HR is asked to
rule on a boundary we cannot yet measure.

**What HR needs to see, in one sentence:** *the Bank today serves roughly a third of SFU's JD
archive, deliberately excludes another third, and cannot classify the rest.*

## 6. Execution breakdown — the iteration list

Each task is one gates-green PR. **Order matters**: nothing below P0 ships before P0 does, because
until P0.1 lands the system does not enforce the invariant the rest of the work assumes.

Working agreement for every task here: failing test first; `make gates` green before commit; a
Tier-A reviewer on anything touching auth, the rulebook, or a decision parameter; and the
orchestrator re-runs the gate rather than trusting the report. **CI is live again — use a normal
PR, not a local merge.**

> **ORDER AS OF 2026-08-11:** ~~P0.1a~~ ✅ (#82) → ~~P0.2~~ ✅ (#83) → ~~P0.1b-i CSRF~~ ✅ (#85) →
> **P0.0 NAVIGABILITY ⟵ NEXT** (`docs/tasks/P0.0-navigability.md`, absorbs P1.1) → P0.1b-ii →
> P1.2 → P1.3. P0.0 jumped the queue because it is what an unsupervised pilot user hits first, and
> it is a day's work.

### P0.1a — Authenticate the JSON API and derive the actor server-side  ✅ **DONE (#82)**
The breach. Split from CSRF so it can ship in hours, not days.
- Gate `jd_bank_router` and the legacy harness routes; decide per route whether the correct answer
  is a gate or **deletion** (the harness `POST /tasks` / `POST /gates/run` may simply not belong in
  an HR service).
- Delete `reviewer_id` from the approve/reject/edit request bodies; derive it from the session the
  way `ui.py` already does. The *service* signature keeps its `reviewer_id` parameter — it is
  transport-agnostic and correct; only the route may no longer let a caller choose it.
- **Authorization matrix test over every route × method** — the durable artifact. Today no test
  pins any of this, which is why it regressed silently.
- Correct `main.py`'s "ADR-008 phase 2" note and ADR-008's phase-2 status.
- **DoD:** an unauthenticated request to every state-changing route returns 401/403 *before*
  reaching a service; no state-changing route reads an actor from body or query; the matrix test
  fails if a new route is added without a gate; `audit_log` can only record an authenticated
  identity.
- **Risk to manage:** removing a body field is a breaking API change. Inventory callers first
  (tests are the known ones) and say so in the PR.

### P0.1b — CSRF for cookie-authenticated state changes
Follows P0.1a directly; separate because it touches every form template.
- **DoD:** a cross-site form POST with a valid session cookie is rejected; every UI form carries a
  token; the token check is pinned by test.

### P0.2 — Make the unsafe posture fail closed
- A **real** startup invariant (the one `settings.py` currently only claims): refuse boot unless
  CAS is on, cookies are secure, secrets are non-default, and the inference host is allow-listed.
  Provide an explicit, loudly-named dev opt-out — the goal is that production cannot *accidentally*
  be unsafe, not that development becomes painful.
- Auth keys in `.env.example`; split liveness from dependency readiness.
- **DoD:** a production-mode boot with CAS off exits non-zero with an actionable message; the dev
  path still works with one obvious flag; readiness reports Postgres/Neo4j/Redis honestly.

### P1.1 — Author submission status  ⟵ **MOVED INTO P0.0**
> **Reprioritised 2026-08-11.** A 51-route crawl showed this is not a P1 polish item: `author` is
> `default_new_user_role`, so a stranded submit is the **first-run experience**, and it is one of
> eight symptoms of a single class — the app answers a browser with JSON. Ship it inside
> **`docs/tasks/P0.0-navigability.md`** alongside the root redirect, the HTML error pages and the
> role-aware nav, because fixing the redirect target without fixing the nav that offered the link
> just moves the dead end. Kept here so the numbering does not drift.
- Author-visible confirmation + a `My drafts` route filtered to the signed-in author; remove the
  reviewer-page redirect.
- **DoD:** a user holding only `author` can submit and then see their draft and its status, with no
  403 anywhere in the flow.

### P1.2 — Harmonization provenance for the reviewer
- A merge-stage reason for dropped/superseded qualifications; a bar-disagreement flag on
  `MergeProvenance`; surface both on the review page — *"master's: stated by 1 of 10 sources; 9
  stated bachelor's"*.
- **DoD:** for any draft whose education/experience/security bar exceeds the modal source value,
  the review page states the divergence and its source counts. No rulebook default changes —
  HR-175 stays `open` and `max` stays the shipped policy until HR rules.

### P1.3 — Tier the decision register
- Add `tier: hr_policy | hr_informed | technical` to every entry; render it in the generated
  register; group the `hr_policy` tier by the review's 12 approval packages.
- **DoD:** `make register` emits per-tier counts; the HR-facing view shows only `hr_policy`; every
  existing ID and `status` is unchanged; `rules_version` unmoved (`decision_register.yaml` is
  unhashed).
- **Escalate, do not guess:** tiering is a judgement about who owns a decision. Draft the
  assignment, then have it reviewed — a knob mis-tiered as `technical` is a governance hole.

### P2.1 — Employee-group coverage
- Raise `employee_group` recovery above the current 68.1% so the JDFN/CUPE boundary is measurable;
  report the residual honestly rather than defaulting it.
- **DoD:** a measured coverage figure and a documented, non-guessing fallback for what remains.

### P2.2 — HR-adjudicated benchmark · P2.3 — Docs correctness sweep
As specified in §2. The docs sweep is small and can ride with any PR: 8 Flask references, the
phantom startup-guard comment, `dashboard.py`'s "all 14,565" → 14,522 scored.

### P3 — as listed in §2
Run manifests/observability (not an outbox); extractor version in parse identity; retrieval
scalability; composition and Neo4j isolation.

## 7. Adopted from the review without change

Its §"HR discussion and approval register" (12 approval packages) is a better workshop structure
than anything we had, and is adopted for the `hr_policy` tier. Its four-plane target architecture
(experience / decision / processing / data) is a sound frame. Its acceptance-evidence package —
pilot cohort, benchmark labels, false-positive tolerances, fairness slices, accessibility standard,
revalidation frequency — is adopted as the definition of done for P2.2.

Its bottom line stands and is worth repeating: **do not add more intelligence before adding
authority, measurement and operability.**

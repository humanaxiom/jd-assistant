# JD Bank — Session Handoff

Read this first every session. **Forward-looking only** — the 6-week build record lives in
[`docs/archive/HANDOFF-ARCHIVE-2026-07-10-to-08-24.md`](docs/archive/HANDOFF-ARCHIVE-2026-07-10-to-08-24.md)
and is not required reading. Rewritten 2026-08-24 after the re-evaluation in
[`docs/STATUS-2026-08-24.md`](docs/STATUS-2026-08-24.md).

---
## 🟢 CIO SUPPORT — 2026-08-27. The pilot is no longer the hard part.

The system was demoed to the CIO, who is **fully supportive** and asked for an **IT-services
subset** as the compelling showcase. That changes the situation this file has described
since 2026-08-24: the blocker was never engineering, it was a decision nobody had taken —
and it has now been taken.

**The demo cohort exists today and is healthy** (measured 2026-08-27):

| | |
|---|---:|
| ITP source documents | **368** |
| harmonized IT roles they produce | **45** |
| of those **approvable right now** | **32 (71%)** |

**368 documents → 45 roles** is the value proposition in one screen, and it needs no new
work to *show*. Plan: [`docs/plans/IT-SUBSET-DEMO-AND-FACETS.md`](docs/plans/IT-SUBSET-DEMO-AND-FACETS.md)
(design only, no code, deliberately additive — no schema change, nothing touching scoring).

**⚠ Answer this before the demo, not during it:** eight of the 45 roles are all titled
*"Information Technology Professional"*. Either they are genuinely distinct (levels /
specialisations under a generic SFU title) or they should have clustered. It is a
15-minute query, and "we don't know" in the room is the one avoidable outcome.

**⚠ The demo is still not the deliverable.** Published JDs are. A compelling showcase that
produces zero approvals has moved exactly as far as the six weeks before it. **The demo's
job is to get the pilot booked.**

---

## 🔴 THE ONE THING TO UNDERSTAND

**The system works. It has no output. The constraint was never engineering.**

| | |
|---|---:|
| Canonical drafts | 2,489 |
| **Approvable right now** | **1,292** |
| **Ever published** | **5** |
| Human review actions, ever | **8** (in six weeks) |
| HR decisions registered / ratified | 214 / **0** |

**1,292 JDFN drafts pass every gate today and not one has been shown to a reviewer.**
They are blocked on nothing we build.

**CUPE is 0.5% approvable (3 of 649) for reasons content cannot fix** —
`SFU-APPROVE-QUAL-EQUIVALENT` blocks 620 (95.5%) and `SFU-APPROVE-KSA-ORDER` blocks 564
(86.9%), both *unratified HR policy decisions*. A week of content fixes and 19.4
GPU-hours moved CUPE approvable **6 → 3**.

> **Before any engineering task, ask: does this change the number of PUBLISHED JDs?**
> If not, it is not next — however real the defect.

**Done is measured in published JDs. Today: 5. Next: 20. Then 100.**
Not carry-through, not scores, not test counts.

## ▶ WHAT TO WORK ON — full detail in [`docs/plan.md`](docs/plan.md)

**Track A (demo) and B1 (TLS) are ours and can run in parallel. B2–B4 are asks — make them
today, they have lead time.**

### 🟢 TRACK A — the demo
*1,420 IT source documents → ~166 roles (8.5:1), and 121 sit outside central IT.*

- **A1 — the duplicate-title question (15 min).** 8 of 45 ITP roles are all titled
  *"Information Technology Professional"*. Distinct levels, or a clustering miss?
  **It will be asked in the room.** Do this first.
- **A2 — IT functional family.** Duty-term sweep ∪ ITP family ∪ title terms.
  🔴 **Validate recall against the ITP seed and let it fail** — the first term list missed
  38 of 45 because it encoded "IT = desktop support".
- **A3 — collection page.** The screen the CIO sees. **A1–A3 alone are a complete demo.**
- **A4 — live funnel panel**, **A5 — facets** (each showing its own coverage).

⚠ **Function ≠ department, and it is measured.** IT is central *and* embedded across a dozen
faculties. No org chart gathers a function; the taxonomy is functional, from duty text.

⚠ **The archive-side dashboards are STATIC** (committed JSON, not the DB). That is why a
live one is needed, and why they should be retired rather than run alongside.

### 🔴 TRACK B — the pilot (the actual deliverable)

- **B1 — TLS at the edge.** `sfuai.ca:7000` is plain HTTP carrying CAS cookies. **Any demo
  or pilot puts a real person on it.** Ours alone; do it before either.
- **B2 — run the pilot.** ~20 approvable drafts reviewed for real.
  **Success = 20 PUBLISHED JDs + the reviewer's written objections.**
- **B3 — ratify two gates.** `SFU-APPROVE-QUAL-EQUIVALENT` (620 CUPE drafts) and
  `SFU-APPROVE-KSA-ORDER` (564). One ruling beats every engineering change made in August,
  at zero GPU cost.
- **B4 — book the HR ratification session.** 214 decisions, 0 ratified.

## ⛔ NOT NEXT — real, registered, and deliberately deferred

Each is a genuine finding. **None changes the published-JD count.** Detail and reasoning in
[`docs/plan.md`](docs/plan.md) Track C.

- **Duty-frequency matching** (27.7% vs 92.3% merge-only) — naive fix *measured* unsafe.
- **`classification` carry-through** — 21% of parses, 0% of drafts. Not on the demo path.
- **Document date at ingest** — unlocks the 1967–2026 era cut. Label it *derived*.
- **Department taxonomy** — 739 strings; demoted to a *filter*, no longer org-list blocked.
- **HR-214 compression question** — **do not close with a threshold**; HR's call.
- **JDFN `problem_solving`** — 228.2% fabricated (1,084 / 475).
- **Retire the static dashboards** — two sources of truth will disagree.
- **Phase F**, **Phase G**, **overlap graph** — unchanged.
- ⛔ **No further producer runs.** ~19 GPU-hours each; zero published JDs each.
- ⛔ **`make bank-audit` is not progress.** It measures draft FIDELITY, not DELIVERY.

## ▶ IF YOU ARE STARTING COLD

```bash
git fetch && git log --oneline origin/main -1
gh pr list                                        # never trust a table for this
docker ps --format '{{.Names}}' | grep jd-bank    # ⚠ the stack does NOT self-restart
docker compose up -d                              # ...if that came up empty
docker ps --filter "name=canonical"               # MUST be empty; do not start a run
```

⚠ **The box runs other Docker projects.** Random `postgres:16-alpine` /
`neo4j:5-community` containers are `recruiter-assistant`'s testcontainers, not ours.

**Current state:** `main` at the latest merge · gates **2,890 passing, 93.36%** · CI green ·
`PARSER_VERSION` `jd_segmenter_v5` · `rules_version` `jd_rules_sfu_v4+76baba29cfeb` ·
CUPE content chain **complete** (every WJQ carry-through 100%, fabricated duties 0).

---

## ▶ HOW WE WORK

- **Docker-only (ADR-006).** No host Python/venv/pip. `make gates` runs the full suite
  (incl. testcontainers integration) in the one-shot `gates` service — CI-identical.
- **TDD.** Failing test first. Every rulebook gate has a failing- and a passing-fixture test.
- **Rulebook as data.** Any non-trivial metric/rule is YAML-configurable **and registered
  in the same PR**. The build refuses to load an unregistered knob — this is enforced, not
  advisory. If a default looks wrong, register it `open`; never quietly patch it.
- **Branches and PRs:** see `CLAUDE.md` § *Change workflow* — code always via PR; most
  docs commit straight to `main`; **this file and `docs/plan.md` still go via PR.**
- **Re-run `make gates` yourself before committing.** A subagent's claim of green is not
  evidence of green; require the pasted command and its output.
- ⚠ **`make gates` bind-mounts `./core`.** Editing files mid-run invalidates the run.

## ▶ LESSONS THAT STILL BITE

Distilled from six weeks; the full set is in the archive.

- **Optimising a proxy can run forever.** Draft fidelity always has another defect at
  14,522 documents. Tie work to the deliverable or the loop never exits. *(This is the
  whole reason for the 2026-08-24 re-evaluation.)*
- **A green suite proves nothing about a guard you have not tried to break.** Three
  separate "correct fix pinned by nothing" defects. If a test's docstring explains *why*
  a property holds, break that why and watch it go red.
- **A wrong query returns 0 exactly as convincingly as a guard that never fired.** Before
  believing a zero, prove the query can produce a non-zero.
- **One sample cannot tell "working" from "stalled".** Take three. A single 38-second
  reading was misread as progress when the transaction was parked.
- **A flat metric is a question, not a verdict** — compare against a control (the
  not-yet-processed population) before acting on it. That is what caught HR-214.
- **A rising score is a question too.** Three separate defects this project made scores go
  *up*: invented sections, compressed duty lists, dropped point-factor content.
- **Verify state against the remote before trusting any doc.** `gh pr list` costs seconds;
  a handoff that records intent as outcome is worse than one merely out of date.
- **EVERY CLAIM ABOUT THE ARCHIVE MUST BE CHECKED AGAINST THE ARCHIVE.** A sample of the
  newest files is not a sample of the corpus. This rule has caught the Phase 0 census, two
  coders, a reviewer *and* the orchestrator.

---

## ▶ AUTHORITATIVE REFERENCES

| what | where |
|---|---|
| **The re-evaluation — read first** | [`docs/STATUS-2026-08-24.md`](docs/STATUS-2026-08-24.md) |
| **The IT demo + facets plan** | [`docs/plans/IT-SUBSET-DEMO-AND-FACETS.md`](docs/plans/IT-SUBSET-DEMO-AND-FACETS.md) |
| **Functional role taxonomy (the sweep)** | [`docs/plans/FUNCTIONAL-ROLE-TAXONOMY.md`](docs/plans/FUNCTIONAL-ROLE-TAXONOMY.md) |
| **Source-archive dashboard (the 14,565)** | [`docs/plans/SOURCE-ARCHIVE-DASHBOARD.md`](docs/plans/SOURCE-ARCHIVE-DASHBOARD.md) |
| Department taxonomy (a *filter*; demoted) | [`docs/plans/DEPARTMENT-TAXONOMY.md`](docs/plans/DEPARTMENT-TAXONOMY.md) |
| Remaining work | [`docs/plan.md`](docs/plan.md) |
| Project invariants | [`CLAUDE.md`](CLAUDE.md) |
| Onboarding, traps, `PARSER_VERSION` | [`DEVELOPER_GUIDE_1.md`](DEVELOPER_GUIDE_1.md) |
| Operating the system | [`docs/OPERATOR-GUIDE.md`](docs/OPERATOR-GUIDE.md) |
| What HR must decide | [`docs/decisions/HR-DECISION-MATRIX.md`](docs/decisions/HR-DECISION-MATRIX.md) |
| Every registered default (214) | [`docs/decisions/HR-DECISION-REGISTER.md`](docs/decisions/HR-DECISION-REGISTER.md) |
| Archive baseline (all 14,565) | [`docs/baseline/README.md`](docs/baseline/README.md) |
| Build record, phases 0–9 + A–G | [`docs/archive/BUILD-RECORD-phases-0-9-A-G.md`](docs/archive/BUILD-RECORD-phases-0-9-A-G.md) |
| Session history, Jul 10 – Aug 24 | [`docs/archive/HANDOFF-ARCHIVE-2026-07-10-to-08-24.md`](docs/archive/HANDOFF-ARCHIVE-2026-07-10-to-08-24.md) |

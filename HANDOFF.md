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
| source documents behind the IT roles | **451** |
| harmonized IT roles they produce | **45** |
| of those **approvable right now** | **32 (71%)** |
| ITP-named files in the archive (47 behind no role) | 469 |

**451 documents → 45 roles** (10.0:1) is the value proposition in one screen, and it needs
no new work to *show*. Plan: [`docs/plans/IT-SUBSET-DEMO-AND-FACETS.md`](docs/plans/IT-SUBSET-DEMO-AND-FACETS.md)
(design only, no code, deliberately additive — no schema change, nothing touching scoring).

**✅ The duplicate-title question is answered** —
[`docs/plans/IT-DUPLICATE-TITLE-ANSWER.md`](docs/plans/IT-DUPLICATE-TITLE-ANSWER.md).
**Twenty** roles (not eight) are titled *"Information Technology Professional"*, and they
are **distinct**: ITP is SFU's generic classification title, and the 20 resolve to **15
specialisation × ITP-level cells**, 18 of 20 level-homogeneous. No merge warranted.

🔴 **That pass also mis-stated two document counts** — ITP 368→**469**, APSA 3,351→**3,442** —
while the figures derived from them (45 roles, 32 approvable) were right. **Re-derive a
headline number before it is said out loud.**

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
| HR decisions **needing an HR ruling** / ratified | 79 / **0** |

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

**Track A (demo) is ours. B2–B4 are asks — make them today, they have lead time.**

⏸ **TLS is no longer here.** It moved to **BEFORE GOING LIVE** (BGL-1) by decision on
2026-08-27: suppressed until feature development is complete. It still blocks B2.

### 🟢 TRACK A — the demo
**Lead with the number that needs no review:** *451 IT source documents → 45 harmonized
roles (10.0:1), 32 approvable today* — the figure the collection page shows and a
stakeholder can click through. (469 ITP files exist in the archive; 47 sit behind no
current role, and 29 non-ITP files were clustered in. `469 → 45` does not reconcile.) Then the embedded finding as a **reviewed** claim —
IT roles sit in Library Systems, Linguistics, Facilities, Mechatronics, Earth Sciences,
Beedie, Education and Health Sciences.

🔴 **The old headline "1,420 documents → ~166 roles (8.5:1)" is NOT reproducible** and must
not be said in the room — it came from the term list measured to miss 38 of 45 seed roles.
The corrected sweep's ratio is a stable ~6.2:1 at every cut, and no cut yields 166/1,420.
See [`docs/plans/IT-FUNCTIONAL-SWEEP-MEASUREMENT.md`](docs/plans/IT-FUNCTIONAL-SWEEP-MEASUREMENT.md).

- ✅ **A1 — the duplicate-title question. DONE** —
  [`docs/plans/IT-DUPLICATE-TITLE-ANSWER.md`](docs/plans/IT-DUPLICATE-TITLE-ANSWER.md).
  **20** roles carry the title (not 8) and they are **distinct** — 15 specialisation ×
  ITP-level cells, 18 of 20 level-homogeneous, a 4.1% tail. No merge warranted.
- ✅ **A2 — IT functional family. BUILT** — `functional_families.yaml`, registered
  HR-215…HR-220 (`open`, `hr_informed`) and unhashed. Measured first, and the
  measurement changed the design:
  [`docs/plans/IT-FUNCTIONAL-SWEEP-MEASUREMENT.md`](docs/plans/IT-FUNCTIONAL-SWEEP-MEASUREMENT.md).
  **There is no threshold** — 98% recall costs 1,141 candidates (46% of the corpus), and
  at the ~166 the plan assumed recall is **48.9%**. So membership is SFU's own ITP
  classification ∪ reviewed `include` − reviewed `exclude`, and **the duty terms only
  rank a review queue**. An integration test pins it: a role stuffed with every IT term
  is *not* a member; a role with none of them but an ITP filename *is*.
  🔴 The bias failure recurred in the opposite direction — the corrected list nearly
  misses the **analyst** half, found only by the ITP family, so the union is load-bearing.
- ✅ **A3 — collection page. BUILT** — `/jd-bank/ui/collection/it`.
  **451 documents → 45 roles (10.0:1), 32 approvable**, each role clicking through to its
  JD and sources; `?queue=1` shows the **72** ranked candidates as a separate surface,
  labelled questions rather than members, with match **counts** — never a percentage.
  The page publishes the family's own recall note. **A1–A3 are a complete demo.**

🔴 **BEFORE THE ITS DIRECTOR SESSIONS — the collection answers a different question than
a director will ask.** It shows roles SFU *classifies* as IT (the ITP code). A director
asks which roles are in *their department*. Measured, those barely overlap:

| | |
|---|---:|
| roles in the collection (ITP-classified) | 45 |
| …with an ITS-looking department | 10 |
| …with **no department recorded at all** | 23 |
| ITS-department roles **not** ITP-classified | 47 |
| …of those, **surfaced nowhere** (not even as candidates) | 🔴 **45** |

✅ **FIXED** — `department_terms` (HR-222) now raises a role as a **candidate** when it
sits in an IT department, whatever its duty score. **The collection is unchanged (45
roles, 32 approvable)**; the queue went 72 → **129**, and **11 roles are visible only
because of this** — *Solutions Architect*, *Director, Infrastructure Services*, *Senior
Director, Application Services*, *Service Desk Team Lead*. Their duty text has no
technology vocabulary, so no ranking signal could have found them.
⚠ The 33-string alias list is exact-match and **provisional — the sessions are where it
gets vetted**. See [`docs/plans/SCOPES-AND-ORG-ROLLUP.md`](docs/plans/SCOPES-AND-ORG-ROLLUP.md) §9.

**Unit priority (set 2026-08-27):** 1. **ITS** (in flight) · 2. **VPFA** — ITS rolls up
into it · 3. **Facilities Services** (queued: 23 roles by exact name, 39 across 14
strings, 57 if security/grounds/parking are in — *where the unit ends is a curation call,
not a query*). **Units 2–3 change nothing about unit 1.**
- **A4 — live funnel panel**, **A5 — facets** (each showing its own coverage).
  🔴 **Both take a SCOPE, never a hardcoded family** —
  [`docs/plans/SCOPES-AND-ORG-ROLLUP.md`](docs/plans/SCOPES-AND-ORG-ROLLUP.md). The IT view
  is instance #1 of a general unit view; **VPFA is next, and ITS rolls up into it**. The IT
  collection resolves by CLASSIFICATION (the ITP code) and **VPFA has none**, so a unit
  needs a different resolver — the seam goes in now, the org data later. Measured: a naive
  filter on VPFA's own name returns **2 roles against a ~55+ portfolio**.

⚠ **Function ≠ department, and it is measured.** IT is central *and* embedded across a dozen
faculties. No org chart gathers a function; the taxonomy is functional, from duty text.

⚠ **The archive-side dashboards are STATIC** (committed JSON, not the DB). That is why a
live one is needed, and why they should be retired rather than run alongside.

### 🔴 TRACK B — the pilot (the actual deliverable)

- **B2 — run the pilot.** ~20 approvable drafts reviewed for real.
  **Success = 20 PUBLISHED JDs + the reviewer's written objections.**
  ⛔ **Blocked on BGL-1 (TLS)** — this is the step that puts other people's credentials
  on the wire.
- **B3 — ratify two gates.** `SFU-APPROVE-QUAL-EQUIVALENT` (620 CUPE drafts) and
  `SFU-APPROVE-KSA-ORDER` (564). One ruling beats every engineering change made in August,
  at zero GPU cost.
- **B4 — book the HR ratification session.** **79 decisions need an HR ruling**, 0 ratified.
  (The register holds more, but the rest are engineering settings or shape what a reviewer
  sees — they are not HR's to sign. The ask is 79, and that is a bookable meeting.)

## ⏸ BEFORE GOING LIVE — deferred until feature development is complete

**Decided 2026-08-27.** Not now, and not "soon" — these are held until the feature work is
done. They are listed here rather than in Track C because Track C items may never be built;
**these must be, before the system carries anyone but us.**

**The trigger is a person, not a date: BGL items must close before anyone outside the
development team signs in.** A demo we drive ourselves exposes only our own session, so it
is not the trigger. **B2 is.**

- **BGL-1 — TLS at the edge.** `sfuai.ca:7000` is plain HTTP carrying CAS session cookies.
  Anyone signing in over it hands their SFU session to whatever is on the path. Ours alone
  to close; no HR dependency. ⛔ **Blocks B2.**

⚠ **This is a suppression, not a resolution.** The exposure is unchanged and unmitigated —
what changed is only that we are not working on it yet. If a pilot, a hands-on session, or
any non-developer login gets scheduled, **BGL-1 comes back to the top of the list that day**.

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
- **A term list is a hypothesis, and it fails differently each time you rewrite it.** The
  first IT list missed the engineers (it encoded "IT = desktop support"); the corrected one
  nearly misses the **analysts** (they write about processes, not technologies). **Validate
  every functional definition against a known-good seed, and let it fail.**
- **Match on word boundaries, never substrings.** `lan` as a substring matched 1,568 of
  2,493 roles — *plan*, *planning*, *Langara* — and 63% is not obviously absurd when you
  are expecting "bigger than you think". A wrong sweep looks exactly like a finding.
- **A number derived from a wrong number can still be right — and that hides the error.**
  The IT plan quoted 368 ITP documents; the truth is 469. The 45 roles and 32 approvable it
  derived were correct, because they came from the right query and only the document count
  was mis-transcribed. **Re-derive a headline number before saying it out loud**, and keep
  the query next to it.
- **EVERY CLAIM ABOUT THE ARCHIVE MUST BE CHECKED AGAINST THE ARCHIVE.** A sample of the
  newest files is not a sample of the corpus. This rule has caught the Phase 0 census, two
  coders, a reviewer *and* the orchestrator.

---

## ▶ AUTHORITATIVE REFERENCES

| what | where |
|---|---|
| **The re-evaluation — read first** | [`docs/STATUS-2026-08-24.md`](docs/STATUS-2026-08-24.md) |
| **The IT demo + facets plan** | [`docs/plans/IT-SUBSET-DEMO-AND-FACETS.md`](docs/plans/IT-SUBSET-DEMO-AND-FACETS.md) |
| **A1 answered — the duplicate-title question** | [`docs/plans/IT-DUPLICATE-TITLE-ANSWER.md`](docs/plans/IT-DUPLICATE-TITLE-ANSWER.md) |
| **A2 measured — the sweep has no threshold** | [`docs/plans/IT-FUNCTIONAL-SWEEP-MEASUREMENT.md`](docs/plans/IT-FUNCTIONAL-SWEEP-MEASUREMENT.md) |
| **Scopes + org rollup (VPFA next)** | [`docs/plans/SCOPES-AND-ORG-ROLLUP.md`](docs/plans/SCOPES-AND-ORG-ROLLUP.md) |
| **The IT collection page (A3)** | `/jd-bank/ui/collection/it` · `core/src/jd_bank/library/families.py` |
| **Functional families rulebook** | `core/src/jd_core/rules/functional_families.yaml` (HR-215…HR-220) |
| **Functional role taxonomy (the sweep)** | [`docs/plans/FUNCTIONAL-ROLE-TAXONOMY.md`](docs/plans/FUNCTIONAL-ROLE-TAXONOMY.md) |
| **Source-archive dashboard (the 14,565)** | [`docs/plans/SOURCE-ARCHIVE-DASHBOARD.md`](docs/plans/SOURCE-ARCHIVE-DASHBOARD.md) |
| Department taxonomy (a *filter*; demoted) | [`docs/plans/DEPARTMENT-TAXONOMY.md`](docs/plans/DEPARTMENT-TAXONOMY.md) |
| Remaining work | [`docs/plan.md`](docs/plan.md) |
| Project invariants | [`CLAUDE.md`](CLAUDE.md) |
| Onboarding, traps, `PARSER_VERSION` | [`DEVELOPER_GUIDE_1.md`](DEVELOPER_GUIDE_1.md) |
| Operating the system | [`docs/OPERATOR-GUIDE.md`](docs/OPERATOR-GUIDE.md) |
| What HR must decide | [`docs/decisions/HR-DECISION-MATRIX.md`](docs/decisions/HR-DECISION-MATRIX.md) |
| Every registered default (the file's own header is the count of record) | [`docs/decisions/HR-DECISION-REGISTER.md`](docs/decisions/HR-DECISION-REGISTER.md) |
| Archive baseline (all 14,565) | [`docs/baseline/README.md`](docs/baseline/README.md) |
| Build record, phases 0–9 + A–G | [`docs/archive/BUILD-RECORD-phases-0-9-A-G.md`](docs/archive/BUILD-RECORD-phases-0-9-A-G.md) |
| Session history, Jul 10 – Aug 24 | [`docs/archive/HANDOFF-ARCHIVE-2026-07-10-to-08-24.md`](docs/archive/HANDOFF-ARCHIVE-2026-07-10-to-08-24.md) |

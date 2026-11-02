# Tracks I · J · K — NLP search, HR form conformance, Compensation Requisition Form

## ▶ Status at 2026-10-28

| PR | state |
|---|---|
| I1 | ✅ merged #213 |
| I2 | ✅ merged #215 |
| **I3** | ✅ PR #219, **flag OFF** (`search.yaml`, HR-315–323): `jd_bank/query_plan.py` — a schema-constrained plan (semantic query, ≤3 added title keywords, group, unit) from `gpt-oss:20b`, then the deterministic guard (group only if typed, unit only from `org_units.yaml` and only as a suggestion, the words as typed always first); both pages show "Read as: …" with what was ignored and a *search the words as typed* link (`?plain=1`). Built synchronously inside the request with a 6 s budget, not the htmx swap the design sketched. Rerank: not built, as designed. The Builder page also stopped showing "N% similar". Q8 still gates enabling it |
| J0 | ◐ the CUPE sources are vendored (`fixtures/hr/cupe/`). Whether the contradictions are registered has not been checked: verify before calling J0 done |
| J1 | ✅ merged #212 |
| J2 | ✅ merged #216 (Q9 = option C) |
| J3 | ❌ not started |
| J4 | ✅ merged #214 |
| J5 | ❌ not started |
| K0 | ❌ owner Q1 not formally recorded |
| K1 | ⏸ on hold (owner Q3: PeopleSoft export TBD) |
| K2 | ✅ the filler merged inside #213 (#211 closed as superseded) |
| **K3** | ✅ PR #219: `GET`/`POST /jd-bank/ui/role/{cluster_id}/comp-requisition` — request type A–E, which ONE position, requester as contact, Word attached; linked from the role page and the Builder's Export block. Fills title, department and group (from the role, or the source files when they agree — HR-309/310), ticks the type and the based-on Yes boxes (HR-311/312), names the requester (HR-313), shows source grades as reference (HR-314). Live smoke drives it. Q2 implemented as *the requester picks*; Q6 as a note, no block |

Order and gates: [`../plan.md`](../plan.md) § *NOW*. The precondition section below is the
2026-10-19 record; run `make smoke` for today's state.

---

Written 2026-10-19 as a plan only, from three read-only research
passes (Opus), each checked against the tree or the live Bank before being relied on.
The reports, queries and raw results are in
[`docs/audit/2026-10-19-search-hr-compreq/`](../audit/2026-10-19-search-hr-compreq/):

| Report | What it is |
|---|---|
| [`search-nlp-spike.md`](../audit/2026-10-19-search-hr-compreq/search-nlp-spike.md) | 22-query eval over both search boxes, live stack + Ollama on `aria-gb10-2`; latencies; LLM plan prototype |
| [`hr-gap-analysis.md`](../audit/2026-10-19-search-hr-compreq/hr-gap-analysis.md) | Every JD document on SFU HR's *Job Descriptions and Re-evaluation Requests* page (24 sources), field-by-field vs the Builder |
| [`comp-form-mapping.md`](../audit/2026-10-19-search-hr-compreq/comp-form-mapping.md) | `CompensationRequisitionForm_2024.pdf` (115 AcroForm fields) mapped to what the Bank holds, with measured coverage |

Origin (owner, 2026-10-19): *"The search should be NLP powered (LLM call?)"* — both
boxes; *"the CUPE form may be missing some things"* — check against HR's published
material for CUPE and APSA, new positions and re-evaluations; *"we will need to add
CompensationRequisitionForm — metadata from jd-bank"* (screenshots
`fixtures/hr/JD-Meta1.png`, `JD-Meta2.png`).

---

## 🔴 Precondition: smoke is RED today

`make smoke`, run 2026-10-19 while writing this plan: **1 failed, 7 passed** —
`test_the_role_vector_index_covers_every_current_role`: *"1 of 2494 embeddable roles
have NO vector"*. (The background task reported exit 0; the output says
`make: *** Error 1`. Read the output.) Fix: `make embed-roles` (idempotent, skip-first,
Neo4j is a derived index), then re-run smoke. **No PR in this plan merges until smoke is
green and covers that PR's change** (Directive #0).

---

## Facts this plan rests on (verified, not just reported)

| Claim | How checked |
|---|---|
| Library search is plain `ILIKE` on title / filename | [`library/service.py:291`](../../core/src/jd_bank/library/service.py#L291), [`:338`](../../core/src/jd_bank/library/service.py#L338) |
| Builder doc-title pass scans every parse: `parsed_jds` = 116,176 rows for 14,522 docs | `SELECT count(*), count(DISTINCT source_document_id) FROM parsed_jds` |
| Builder search UI catches only `TimeoutError` (embed host down → 500) | `compose_ui.py` `search_page` — the only `except` |
| One renderer for both forms; CUPE exports in the APSA layout + APSA footer | [`jd_export/render.py:126`](../../core/src/jd_export/render.py#L126) — no template branch; only two callers |
| CUPE majors+minors merged then cut at 12 | [`wjq_assemble.py:178-179`](../../core/src/jd_bank/composer/wjq_assemble.py#L178-L179) |
| "About SFU" is the old *"Canada's engaged university"* text | [`boilerplate.yaml:50`](../../core/src/jd_core/rules/boilerplate.yaml#L50) |
| A compensation requisition workflow is recorded **out of remit** | `docs/decisions/copilot-sfu-gap-triage-2026-08-13.md` row 6 |
| `import_grades.py` joins on role `position_number` (≈ none populated) | [`core/scripts/import_grades.py:42`](../../core/scripts/import_grades.py#L42) |

---

## Track I — NLP search, both boxes

### What was measured (22 queries, hit@5 / mean P@10, live)

| Variant | Library | Builder |
|---|---|---|
| Today | **5 / 0.20** | 20 / 0.72 |
| Title tiers + existing role vectors, **no LLM** | 20 / 0.67 | (already this) |
| LLM query plan, **guarded**, gpt-oss:20b | 21 / 0.84 | 20 / 0.87 |
| LLM plan, **unguarded** | 18–20 / 0.75–0.78 | 17–18, **2–3 empty pages** |
| LLM rerank top-20 | 21 / 0.77, **+6 s p50** | — |

Latency: LLM plan 3.3 s p50 / 6.1 s p95 (20b), 10 s cold; Builder today 2.9 s p50, of
which 2.7 s is the unindexed doc-title scan.

**The lesson:** the big win is *not* the LLM — it is giving the Library the vector search
the Builder already has. The LLM adds abbreviation/intent expansion ("coop coord",
"AP clerk", "IT sysadmin"), but **unguarded it invented an employee-group filter on
75–85% of queries** and emptied pages. It ships only behind a deterministic guard, off by
default.

### PRs

| PR | Scope | Writer → Checker | E2E (smoke) it must add |
|---|---|---|---|
| **I1** Library hybrid search | Title tiers (exact → prefix → contains) then role-vector pass, reusing `search.py`'s role pass. "Why it matched" label per row (title / meaning), **no scores** (memory: similarity has no threshold). Group + unit facets. Archive tab searches parsed titles, not only filenames. | Sonnet → **Opus** | Exact-title findability over a sample of live roles; 22-query recall floor ≥ 18/22 hit@10 (eval set → `fixtures/labels/search_eval_v1.yaml`, reviewed PR) through the **HTTP route** with CAS dependency overridden |
| **I2** GPU-down fallback + Builder speed | Both boxes: embed host unreachable → title results + banner, never 500 (catch connection errors, not only timeouts). Doc-title pass restricted to the **current** parse; `pg_trgm` extension + GIN trigram index (migration) → typo tolerance. | **Opus** (migration/SQL) → **Opus** | Search with a dead embed endpoint still returns title hits; no title hit comes from a superseded parse; Builder p95 under a registered budget |
| **I3** LLM query plan (flag **off**) | New `rules.search` YAML: `enabled`, model, temperature, reasoning effort, timeout, max keywords, prompt id `jd_search_plan_v1`; schema-constrained output (`ChatClient`, call site A). Guard: group kept only if the user typed it; unit chosen **only from the rulebook list**, as a boost not a filter; raw query always searched first. UI: Stage-1 results immediately, merged results swapped in if the plan returns inside the budget; the model's reading is shown and removable. Every knob registered **`open`**. Rerank: **not built**. | **Opus** → **Opus** | When enabled: one live plan call + guard property (no filter the query didn't name). When disabled: asserts no chat call is made. Docs: add row to `docs/LLM-CALLS.md` + `AI-USAGE.md` |

**Blocked on a person:** *"Faculty of Science"* fails in every variant — there is no
faculty → department mapping (`org_units.yaml` has no faculties). That list must come from
HR/the owner; a model must not invent it.

---

## Track J — HR form conformance (CUPE and APSA/APEX/Poly)

**Short version:** the CUPE form is missing much more than "some things", and neither form
supports a re-evaluation. Full field tables and sources in `hr-gap-analysis.md`.

### P1 gaps — HR returns the JD without these

**CUPE**
1. Exports in the **APSA layout** with the APSA territorial/equity footer. CUPE Art. 15.04:
   the standard form "cannot be revised without mutual agreement".
2. **No Part II questionnaire** (58 answers). HR: *"Both parts must be completed before
   positions can be evaluated and classified."*
3. **Duties silently dropped** — majors+minors merged and capped at 12; HR's own Dec-2024
   sample has 14, so *"Performs other duties…"* is lost.
4. Asks for **% of time**; HR's form tags each major function **(D)/(W)/(M)/(S)**
   (`SFUDuty.frequency` exists; the Builder can't set it).
5. Sections 5, 6, 7, 12 are **fixed checkbox levels** on HR's form; free text here.
6. Sections 8, 10, 11 are **tables** (duration / frequency / hours per week); free text here.
7. Missing: equivalency *"is / is not acceptable because…"*; **Occupational Requirements**.
8. Asks the author for *approved classification & grade* (an HR-only box); missing current
   classification, evaluating supervisor's title, date completed, completed-by choice.

**APSA / APEX / Poly**
1. **About SFU never exported**, and the YAML text predates the 2024 template (HR-104).
2. Territorial acknowledgement spelling differs from the 2024 template's official
   spellings (HR-105) — this answers the CLAUDE.md open flag *if HR confirms*.
3. No **Position #** field (the model supports it).

**Both** — no re-evaluation or editorial mode and no submission package (CRF, org chart
one level up/down, existing + revised JD with changes shown, CUPE: summary of differences +
Part II + 20-working-day / copy-to-CUPE rules).

P2/P3 (how/why sub-bullets, security-check sentence dropped on clone, supervisor title/#,
duty-overlap reminder, Common/Uncommon errors, hints contradicting HR wording, HR's 10
pre-classified CUPE JDs as clone sources, …) are listed with sources in the report.

### PRs

| PR | Scope | Writer → Checker | E2E (smoke) it must add |
|---|---|---|---|
| **J0** Sources + contradictions | Vendor the CUPE source docs into `fixtures/hr/cupe/` with sha256s (none are there today; live CUPE template revised 2026-05-12). **Decisions PR:** register the HR-source contradictions `open` (About SFU wording, CUPE "Annual" frequency, CUPE duty-slot count, APSA % allocation → HR-104/105/142/202/023). | Opus → Opus | — (docs/register; `make register-check`) |
| **J1** CUPE renderer | Separate CUPE export faithful to HR's form: its section order, checkboxes, tables, **no APSA footer**, blank signature lines (never pre-filled, NN #1). | **Opus** (faithful port) → Opus | Render a CUPE export from a **live** CUPE role, then re-parse it with the Bank's own WJQ parser: every field must survive (round-trip). Same for APSA |
| **J2** CUPE form structure | Persist major/minor split; replace the silent 12-cap with a visible limit (cap → YAML, registered `open`); D/W/M/S frequency; checkbox + table sections; equivalency; Occupational Requirements; identification fields fixed. Hints rewritten from HR's wording. | Opus (model/rules) → Opus; Sonnet for templates | Author a 14-function CUPE JD end to end through the HTTP routes → export → nothing dropped |
| **J3** CUPE Part II | The 58-answer questionnaire as rules-as-data (YAML question set), stored with the draft, exported as its own document. | Opus → Opus | Part II exported for a live CUPE draft and re-parsed |
| **J4** APSA fixes | About SFU block on export; boilerplate per HR's ruling on J0; Position #; how/why sub-bullets; security-check sentence (kept on clone); supervisor title/#. | Sonnet → Opus | APSA export from a live role contains About SFU + footer in the ruled wording |
| **J5** Re-evaluation mode | Pick the existing Bank version → revise → export package: existing + revised + summary of differences (the Bank's diff) + (CUPE) Part II + CRF (Track K). CRF p.4 *re-evaluation vs editorial* table as YAML (also the source `drift.py` says it lacks), registered `open`. Tracked-changes `.docx` only if the owner rules it in (Q5). | Opus → Opus | Re-evaluate a live published role: package contains every required part; the original stays published (NN #1) |

---

## Track K — Compensation Requisition Form (prefill + download)

**What the Bank can and cannot fill** (measured): of ~60 inputs, **~8 prefill** from the
Bank (position #, title, department name, the "existing position #" lists, *JD in Word*,
employee group), **~10 suggest-for-confirmation** (request type, what-changed checkboxes
from the diff, affects-other-positions, VPA/approver boxes, new title). The rest — dept
code, authoritative grade, position type, hours, supervisor position #, accounts, dates,
signatures — needs an **HRIS position export** or the requester. Measured per position
(5,541): title 93.5%, group 78.3%, dept name 49.5%, grade 19.4%, dept code ≈ 0. On the
screenshot record (00000061) the Bank has no dept and no grade; HRIS has 4510 / APSA 10.

**Join key found:** archive filename = HRIS *As-Of Date* + HRIS attachment name
(`20200601_61,_30785,_208,_975_JDFN_APSA_20211117.docx` ↔ the screenshot). Exact, and it
also covers 508 files whose unpadded ids the rulebook pattern misses.

### PRs

| PR | Scope | Writer → Checker | E2E (smoke) it must add |
|---|---|---|---|
| **K0** Scope ruling | **Decisions PR** narrowing triage row 6: *"prefill and download the SFU form; no request store, no workflow — HRIS stays the system of record."* Needs the owner (Q1). | — | — |
| **K1** HRIS position import | New `hris_positions` table (migration) + CSV importer, joined to source documents by As-Of + attachment filename; mapping YAML (AP00→APSA, CU00→CUPE, union 200/300, Regular→Continuing, VPA-approval-at-grade-≥9 trigger) registered `open`. Built and tested against a fixture shaped like the screenshots; **real data waits on the export** (Q3). Retire or fix `import_grades.py`. | **Opus** (schema/migration) → Opus | Smoke is live-only, so: once the real export is loaded, assert join coverage on the **live** table (registered floor) and that no incumbent name is stored. Until then the fixture test in `make gates` is the only cover — say so in the PR, do not claim smoke covers it |
| **K2** Form filler | Fill SFU's own AcroForm with `pypdf` (BSD, pure Python; add to `core/requirements.txt`, ships via `deploy/bundle.ps1`). Field map in YAML (the PDF's names are misleading: `Supervisor Position Title` = contact person, `OBJECT 4` = PROJECT). Template sha256 pinned; a test fails if SFU changes the field set. Signatures and incumbent names never filled. | Sonnet → **Opus** | Fill the form for a **live** role, read it back with pypdf, assert prefilled values = Bank values, signatures empty; `make deploy-check` green |
| **K3** Builder entry point | "Download Compensation Requisition Form" on a draft and in J5's package; position picker (a role spans 2.4 positions on average, up to 73 — Q2); suggested values visibly marked *confirm*. Linked from the Builder + Library (discoverable, Directive #1). | Sonnet → Opus | Through the HTTP route with CAS overridden: download returns a valid filled PDF |

---

## How it will be run (agentic, multiple models)

Per PR, in its own git worktree so independent PRs run in parallel:

1. **Tester** (Opus for rules/policy/migrations, Sonnet for wiring) writes the failing
   tests first, including the smoke extension.
2. **Coder** (tier per the tables above) makes them pass.
3. **Reviewer — always Opus**, adversarial: re-runs `make gates` itself, breaks the guard
   once to prove it goes red, reads the diff, and checks `make register-check` for any
   rules-YAML change.
4. **Orchestrator (me):** re-runs `make gates` + `make smoke` on the live stack, checks the
   Bank for the claimed property (not the counter), then branch + PR. **Merge only on
   green smoke that covers the change.**

Parallel lanes once Q-answers land: **I1 · J0/J1 · K2** have no file overlap and can start
together. I2 follows I1; I3 follows I2. J2→J3→J5. K1 needs the export; K3 needs K2 (+J5 for
the package).

## Decisions needed from the owner / HR

| # | Question | Blocks |
|---|---|---|
| Q1 | Narrow triage row 6 to "prefill + download, no request store"? | K0–K3 |
| Q2 | CRF is per position; a role spans many. Pick the position in the Builder? | K3 |
| Q3 | Who runs the PeopleSoft position export? Include reports-to, FTE, hours? Grade data's FIPPA review — started? **Owner, 2026-10-19: TBD — K1 on hold.** (K2 does not need it: dept code + grade stay blank.) | K1 real data |
| Q4 | Prefill *Anticipated grade* at all (outside true clones), or only show reference grades? | K2 |
| Q5 | Is a real Word **track-changes** `.docx` in scope for re-evaluations (CRF §B/§C ask for it)? | J5 |
| Q6 | CUPE: CRF only for request types A, C, D, E? (the form routes CUPE re-evals to a separate form) | K3 |
| Q7 | Faculty → department list for search | I1 facets / I3 |
| Q8 | LLM search model — gpt-oss:20b matched 120b at lower latency; ships **off** by default. HR/ITS ruling | I3 enable |
| Q9 | CUPE: keep K/S/A, or render only HR's "Occupational Skills"? ✅ **Owner, 2026-10-19: option C (hybrid)** — one "Occupational Skills" list as on HR's form, with optional "knowledge of / ability to" phrase helpers inside it; Occupational Requirement(s) a separate box. Applied in J2, which updates HR-239 (today: K+S → Occupational Skills, A → Occupational Requirement(s)) and migrates existing CUPE drafts' K/S/A into the one list. | J2 |
| Q10 | HR-023 % per duty — the 2024 APSA template doesn't ask for it | J4 |

# JD Bank — Roadmap & Backlog

**Updated:** 2026-07-28; **revised 2026-08-05** against the seven commits from `650828b` to
`46a9443` plus the Phase-5.9 authoring guard. Produced from a review of the repo backlog + main workflow and a
scan of peer-university JD/HR systems (UBC, Toronto, McGill; Workday, PageUp, Cornerstone,
PeopleAdmin/Unified Talent, JDXpert, Interfolio). Every item respects the six hard
invariants; conflicts are called out explicitly.

> **The governing reality:** the engineering pipeline is essentially built and has run over
> the real 14,565-file corpus end-to-end. What stands between it and daily HR use is
> **governance** (the approval bar is unsigned — **every** HR decision in the register is
> `open`; the register's own header carries the count, which is why no number is quoted here),
> **a first human pilot** (**4** canonical JDs are published out of **1,802** roles — the
> publish path has been driven, the pilot has not), and a handful of usability/scope gaps.
> So this roadmap is front-loaded with cheap surfacing work and the HR-ratification track,
> not net-new infrastructure. Ratification and the pilot are the real critical path:
> **almost everything of lasting value is cheap to build but expensive to _sign_** — so we
> sequence the engineering to make the signing possible, not to outrun it.

### The six invariants every item is checked against
1. **Self-hosted inference only** — no cloud/vendor LLM or embedding API (FIPPA / no vendor egress of JD text).
2. **Nothing auto-publishes** — a human reviewer approves; overrides need a written reason.
3. **Rulebook-as-data** — every gate/threshold in versioned YAML + the HR decision register.
4. **Validator is the oracle** — scores/approvability from the deterministic rulebook, not the LLM.
5. **Scope = JDFN** (APSA/APEX/Poly); CUPE/WJQ is out until HR defines a WJQ bar (HR-143/194).
6. **Canadian public university** — FIPPA privacy, WCAG accessibility, EDI, territorial acknowledgement.

---

## 1. Current backlog (by area)

Reconciled against `git log`, `docs/plan.md`, ADR-008, the Phase-5 task doc, and the HR
register. (HANDOFF.md's newest block predates the ADR-008 auth work, so its "STILL OPEN"
list omits the auth deferrals — captured here.)

| Area | Item | Status | Effort |
|---|---|---|---|
| Content | ~~Browsable content library — 🏦 JD Bank: roles → sources, source-JD reader, flat archive, click-to-sort; clone the harmonized role~~ **DONE (2026-08-01/02)** — HR can read the actual JD content | done | M |
| Grade | ~~Grade capture — structured `classification{scheme,value,source}` + group-aware parser + 2,323 CUPE backfill + Builder/review entry + HRIS-import scaffold + surfacing~~ **DONE (2026-08-02, Phase A + steps 1–5)**. **Blocked on HR:** per-group grade scales (`grade-scales-hr-ask.md`) + HRIS export/FIPPA | done / HR-blocked | M |
| Pipeline | ~~**Parser paragraph-title fix**~~ **DONE (2026-08-02, parser `v3`)** — the identification table lives in the docx *header*, which extraction skipped. Titles **34.3% → 1.0%** paragraph-shaped; `position_number` 35% → **68%**, `employee_group` 36% → **68%**, and the first **APSA/APEX grades** the Bank has ever parsed. Baseline cohort unchanged. **Follow-up: propagate to the harmonized roles** (needs the embed → cluster → canonical re-run) | done | M |
| Builder | ~~Gender-Decoder soft coded-language lexicon~~ **MEASURED AND DECLINED (2026-08-07)** — 99.50% of JDs trip both word lists; 38–77% of hits are stemming collisions and SFU's own template headings; the item's "fires on only 10/14,522" premise was `SFU-QUAL-BANNED-PHRASE`, not this rule (the real rate is **76.8%**). Evidence: `docs/decisions/coded-language-soft-lexicon.md`. **Redirected to HR-029**, which now carries measured firing rates | declined | — |
| Pipeline | **WJQ boilerplate redaction before harmonization** — WJQ over-clusters on template+seniority; the two biggest flagged clusters ("Untitled Position" n=132/108) are template artifacts. Blocks WJQ harmonization. | open (P4 priority) | L |
| Pipeline | ~~Embed **published canonicals** into the Neo4j index (search covers only the archive today)~~ **DONE (2026-08-04, `cadfc30`)** — shipped **wider and by a different mechanism** than planned: a separate `(:JDRole)` label + `jd_role_embeddings` index (migration `003`, `make embed-roles`), one vector per **cluster**, covering **every current-version role, drafts included** — not published-only, and not `kind=canonical` inside the document index (that would corrupt the `MATCH (d:JDDocument)` corpus count). Measured: **1,802 seen, 1,797 embedded, 5 empty**. **Deliberately not wired into `approve`** (see plan.md 8.2) | done | S/M |
| Pipeline | ~~Builder search can't find a JD by its title~~ **DONE (2026-08-03/04)** — four passes now: role-title → document-title (Postgres) ranked **above** semantic, because the document vectors deliberately exclude the title (`embeddings.yaml: include_title_in_document: false`, which is what makes dedup title-agnostic). `89d0c74` exact/near title · `3b6a71b` role titles (**61%** of harmonized role titles — 746/1,222 — appear on **no** source document; harmonization renames the role) · `d71e333` documents collapsed into their harmonized role, membership in **one** query per pass (was an N-query loop) · `46a9443` same-titled roles disambiguated by department (**791/1,802 roles, 44%**, share a title; department resolves **719/791, 91%**; the last 72 stay unlabelled rather than invented) | done | M |
| Review | ~~A **published** JD could not be edited at all~~ **DONE (2026-08-02, `802bff0`)** — editing a published version mints a new DRAFT; the prior version **stays published** through the review window and retires only when its replacement is approved (`approve` supersedes under `FOR UPDATE` + a `review.superseded` audit row). ARCHIVED stays refused. Also: advisory findings stopped being presented as errors ("Suggested improvements" + amber badge when nothing blocks; "Fix these" only when a gate blocks) | done | M |
| Pipeline | Tier-3 candidate-gen perf → Neo4j vector top-k (O(bucket²) on the 8.2k `unmapped` bucket) | open | M |
| Pipeline | %-rebalance of duty allocations (deferred from 4.1) | deferred | M |
| Pipeline | `jd_bank/` change-log runner over real clusters (4.3) | open | S |
| Builder | ~~**Structured per-field editors** (duty % / KSA modifiers) — form is lossy, reviewer edit is raw JSON~~ **DONE (2026-07-28, `feat/builder-structured-fields`)** — Builder rows capture verb/%/modifier; reviewer edit is a full per-field `SFUJobDescription` editor (no raw JSON). | done | M |
| Builder | Live-as-you-type validation (inline fetch to 5.1) instead of POST-re-render | open (opt-in) | S |
| Review | **4.5 HR pilot** — 5–10 clusters end-to-end with a real reviewer (external dependency) | open (next milestone) | L |
| Review | ~~Concurrent double-approve test (the `FOR UPDATE` lock is untested)~~ **DONE (2026-07-29, `7ce53db`)** — mutation-verified integration pin | done | S |
| Auth | `review_actions.reviewer_id → users.id` hard FK (currently CAS-username string) | open | S |
| Auth | Tamper-**prevention** via Postgres GRANT/REVOKE (audit is tamper-evident, not prevented) | open (hardening) | M |
| Auth | CAS production verification against the real `cas.sfu.ca` IdP (enabled, not yet driven end-to-end) | open (ops) | S/M |
| Dashboards | Standalone harmonization-diff dashboard (4.6c item 4 — renders only inside review detail today) | likely open | S |
| Rulebook | **HR ratification** of the decision register (**every entry `open`** — count in the generated register's header) — the actual critical path | open (external) | L |
| Rulebook | HR-041/120 banned-phrase completeness (fires on only 10/14,522 — guard-rail or gap?) | open (external) | S |
| Rulebook | HR-042 `QUAL-MINIMUM` overridable rationale evaporated — HR should decide on purpose | open (external) | S |
| Rulebook | Reinstate `SFU-STRUCT-HOW-WHY` (HR-119/121) once `how_why` can be populated | open | S–M |
| Rulebook | CUPE/WJQ authoring scope (HR-194) — a whole project, HR-gated | open | XL |
| Ops | Footer / territorial-acknowledgement wording sign-off (blocks external export) | open (external) | S |
| Ops | Backup + reindex runbooks; rate/size limits (Phase-6 hardening) | open | M |
| Ops | ~~GitHub Actions billing block~~ **RESOLVED (verified 2026-08-07)** — CI is green on every commit including `main` (run `31199851819`). **The "merge locally per ADR-006" instruction in older notes is now WRONG** — use normal PR + CI | done | — |
| Security | ~~🔴 **P0.1a — the JSON API (`/jd-bank`) and legacy harness routes carry NO auth gate**; an unauthenticated `POST /jd-bank/review/{id}/approve` reached the review service and on a gate-clean DRAFT would **publish** (NN #1), with the body-supplied `reviewer_id` written into the hash-chained audit log as the actor (NN #6)~~ **CLOSED (2026-08-07):** review JSON → `require_roles(reviewer, admin)`, compose JSON → `current_user`, harness routes → `require_roles(admin)`, `/health` public; `reviewer_id` **and** `overrides[].reviewer` removed from the request bodies and stamped from the session; `tests/unit/test_authorization_matrix.py` walks the live routing table so an unclassified route fails the build. See ADR-008 phase 4 | done | — |
| Security | 🟠 **P0.1b — CSRF for cookie-authenticated state changes.** Split from P0.1a; touches every UI form. A cross-site form POST carrying a valid session cookie is still accepted. Plan: `docs/tasks/architecture-review-response-2026-08-07.md` §6 | open | M |
| Security | 🔴 **P0 — the production startup guard `settings.py` claims does not exist**, and `cas_enabled=False` returns a transient **admin** before any cookie is read; `.env.example` has no auth keys | open | S/M |
| Governance | **Tier the decision register before the HR workshop** — 57 of 197 entries sit in the `comparison`/`hay_signals` adapter ADR-007 disclaims as *not* classification, and 8 are embedding knobs; only ~55–60 touch the approval bar. Add `hr_policy`/`hr_informed`/`technical` so HR sees ~60 real calls, not 197 | open | S/M |
| Pipeline | **31.9% of the archive (4,630 JDs) has no parsed `employee_group`** — the parser's residual — so "the Bank serves JDFN" is unfalsifiable for a third of the corpus. Close before the CUPE scope conversation; no HR dependency | open | M |
| UX | **Submit → 403.** The draft commits, then redirects to a reviewer-only page; the default new-user role is `author`, so this is the default first experience. No author-scoped status route exists | open | S |
| Review | **Harmonization provenance** — a reviewer sees a raised education/experience bar with no indication that most sources stated lower (`seniority_bar_policy: max`, HR-175; ~4.3% of clusters). The NN #1 control cannot rule on what it cannot see | open | M |
| Chore | `jd_core → jd_bank` import edge; `get_session` → `api/deps.py` shim | open | S |
| Docs | Refresh HANDOFF.md for the auth/RBAC + operator-guide work | open | S |
| Phase 7 | Role-duty overlap graph (Neo4j); Hay-readiness summaries; transposer service; M365/SharePoint | deferred | S–XL |

---

## 2. Quick wins (S effort, high value)

Mostly open backlog items or thin surfacings of machinery JD Bank already owns. **Several
unblock the pilot** — do them first.

- ~~**Embed published canonicals into the vector index.**~~ **DONE (2026-08-04, `cadfc30`).**
  The sentence this item was written around — *"The Bank can't search its own output"* — is
  now false: `make embed-roles` writes one `(:JDRole)` vector per cluster into
  `jd_role_embeddings` (migration `003`), reusing `serialize_document` verbatim so the cosines
  stay comparable. **Two deliberate departures from the plan.** (1) It indexes **every
  current-version role, drafts included**, not published-only — restricting to PUBLISHED would
  have indexed **4** roles instead of ~1,800 and made the feature useless until after the
  pilot; each node carries `status` so a hit is labelled honestly. (2) There is **no
  write-on-publish hook, on purpose** — publishing must not depend on the GPU, and network I/O
  inside the review transaction would hold the `SELECT … FOR UPDATE` lock. It is an idempotent,
  skip-first runner you run afterwards, exactly like `make embed`.
  *Invariant:* embeddings stay on self-hosted Ollama behind the egress guard.
- **Coded-language meter in the live Builder panel.** ~~Surface the coded/gendered findings
  prominently.~~ **DONE (2026-08-02, `19e76d3`)** — the validator's `inclusive_language`
  findings (`coded_terms.yaml`, `SFU-LANG-CODED`) are now pulled into a prominent "N flagged /
  clear" meter with suggestions, at the top of the 5.3 panel. ~~**Still open (the stretch):** a
  softer masculine/feminine/age-coded lexicon (Gender-Decoder pattern)…~~ **MEASURED AND
  DECLINED (2026-08-07)** — see [`docs/decisions/coded-language-soft-lexicon.md`](decisions/coded-language-soft-lexicon.md).
  **This item's own premise was a misattributed number.** It claimed the exact-match list "fires
  on only 10/14,522"; that is `SFU-QUAL-BANNED-PHRASE` (HR-041/120, the backlog row above).
  `SFU-LANG-CODED` fires on **11,160/14,522 — 76.8%** — confirmed across six commits of the
  committed baseline artifact. And the lexicon itself cannot be honest here: **99.50% of JDs trip
  BOTH the masculine and feminine lists**, 95.7% would get a lean verdict, and the split is
  decided by an unratified band (neutral 4.3% → 48.9% as it widens 0→5) and by single stems —
  dropping `decision`, the word inside SFU's mandated `IMPACT OF DECISION MAKING` heading, flips
  the corpus from 30/37 to 19/55. **38–77% of hits are not gendered lean at all** but stemming
  collisions (`confidential`→"confident" is 99.8% of that stem; `committee`→"commit" 84.5%),
  template headings, WJQ form labels and unit names. Same failure mode, same answer, as the
  Phase-5.9 similarity threshold. **Redirected:** the live defect is **HR-029** — three terms SFU
  never published (`confidential` 29.8%, `individual` 25.6%, `agreement` 11.6%) generate **83%**
  of today's findings, while 16 of 37 terms never fire. That entry now carries the measured
  evidence; it is an HR ruling, not an engineering change.
- ~~**Authoring-time "is this role already covered?" near-duplicate guard.**~~ **DONE
  (2026-08-05, Phase 5.9, `jd_bank/composer/duplicates.py`).** Shipped, but **not as this item
  described it**: the *"3 roles are ~87% similar — clone one?"* prompt this item originally
  proposed **cannot be built on this corpus**, and the measurement says so. Over the live 1,797-vector role index: same-title role
  pairs (genuine twins, n=2,618) have a median cosine of **0.9335**, while a role's nearest
  **unrelated** neighbour (n=200) medians **0.9604** — *the unrelated role scores higher*. Any
  cutoff is therefore a constant dressed as a measurement (at 0.90 the guard fires on **99.2%**
  of drafts at **22%** precision; a top1-vs-top2 margin rule fails identically). **Ranking is
  good** though — a true same-title sibling is top-5 for **76%** of roles — so the panel ships
  as a **ranked list with no score, no percentage and no threshold**, plus one honest non-vector
  fact ("SFU already has 9 roles titled 'Academic Advisor', across 6 departments"). Two
  independent passes: a Postgres title pass that always runs, and a semantic pass that degrades
  to empty if Ollama or the role index is unavailable. Config `dedup.authoring_guard`,
  registered **HR-195** (`max_matches`) / **HR-196** (`min_draft_chars`) / **HR-197** (timeout).
  *Invariant:* read-only, suggests-never-blocks, every knob registered.
- ~~**Concurrent double-approve test.**~~ **DONE (2026-07-29, `7ce53db`).** A mutation-verified
  integration test orchestrates two concurrent approves and proves the `FOR UPDATE` lock lets
  exactly one publish (the other → `IllegalTransitionError`).
- ~~**Side-by-side JD version diff (draft vs last-approved).**~~ **DONE (2026-07-29, `main`).**
  Pure `jd_core/bank/version_diff.py` (complete section serialization — catches the presence
  booleans `render_sfu_jd_text` drops) + `review.get_version_diff` (last PUBLISHED version of the
  cluster) + a standalone `/jd-bank/ui/review/{id}/diff` page linked from review detail.
- **Reinstate `SFU-STRUCT-HOW-WHY`** if the `how_why` field can be populated (retired only
  because the parser couldn't fill it; designed to return "with one YAML word").
- ~~**Refresh HANDOFF.md + reconcile the open GitHub PRs.**~~ **DONE (2026-08-05/07).** HANDOFF is
  current, and **the billing block is resolved** — CI is green on every commit including `main`,
  and PR #81 merged normally. **Older notes saying "Actions is billing-blocked, merge locally per
  ADR-006" are now WRONG; do not follow them.**
- **Footer / territorial-acknowledgement sign-off.** A single `boilerplate.yaml` constant that
  blocks any external `.docx`/posting export — a verification task, get it in front of the
  right person before the posting features can ship externally.

---

## 3. High-value features (M/L)

From peer research + backlog, each mapped to JD Bank's architecture, ordered roughly by leverage.

- ~~**Structured per-field editors (duty % / KSA modifiers) — the #1 usability blocker.**~~
  **DONE (2026-07-29).** The Builder form now captures per-duty action-verb + %-allocation and
  per-qualification KSA modifiers (structured rows, not lossy textareas), and the reviewer edit
  view is a full per-field `SFUJobDescription` editor — no raw-JSON `<textarea>` on either. Peers:
  JDXpert field-level editing (UC Berkeley, Auburn, UIC). Deterministic assembly, validator still
  the oracle.
- **JD-to-posting transform (internal JD → candidate-facing ad).** A deterministic "render as
  posting" over an approved canonical: strip internal-only content (reporting lines, Hay/level
  signals, %-allocations), reorder candidate-first, with an *optional* self-hosted LLM polish.
  Every peer stresses that pasting the compliance JD into the careers site is the common mistake.
  *Peers:* Workday "Job Posting Text"; the JD→posting split is standard in Ongig/Textio/JDXpert.
  *Fit:* deterministic base; LLM polish self-hosted + re-scored; posting is a derived draft still
  needing the human gate. JDFN-scoped. **Effort M.**
- **Configurable multi-step approval routing (sequential + parallel, delegation/escalation).**
  SFU's real lifecycle (Dept → Unit HR → Manager → Faculty/Dean, parallel Finance → Comp analyst)
  lives in email today; the review service is a flat queue. Now realistic given ADR-008 RBAC/CAS.
  *Peers:* U Illinois multi-step JD review; PeopleAdmin position-management routing. *Fit:* strong
  with human-at-every-gate; routing topology + escalation timers land as registered YAML; no LLM.
  **Effort L.**
- **Approved-position template library ("post from an existing position").** A faceted, browsable
  library over *published* canonicals as reusable templates — start from an approved role, not a
  blank form. Turns the **1,798** latent drafts into the recruiter's default starting point. *Peers:*
  PeopleAdmin "living library of PDs"; Workday requisition reuse. *Fit:* strong; its **vector
  prerequisite is now met** (`cadfc30` — roles are searchable, drafts included), so what remains is
  the faceted browse surface over *published* rows; clones re-enter the review queue. **Effort M.**
- **Plain-language / accessibility readability scoring (AODA/WCAG-aligned).** Deterministic
  reading-grade, over-long-sentence, undefined-acronym, passive-voice linting as per-section
  guidance. Complex JD language is both an accessibility and EDI barrier for a Canadian public
  university. Classic Flesch-Kincaid-style formulas — no model. *Fit:* deterministic metrics →
  validator-as-oracle; thresholds registered; advisory in draft mode. **Effort M.**
- **Required-vs-preferred qualification split + barrier/inflation check.** Split parsed
  qualifications into must-have / nice-to-have with an explicit flag, and flag degree/experience
  inflation and "nice-to-haves listed as musts" — measurably widens and diversifies the applicant
  pool and improves BFOR defensibility. Reuses `SFUQualification` + KSA→duty traceability. *Fit:*
  deterministic; modifiers registered. *Caveat:* the "unnecessary" judgment is capped by the
  keyword-bag skills limitation (HR-149) until a competency layer exists. **Effort M.**
- **HR operational analytics — cycle-time, coverage, reviewer workload.** Extend the read-only
  dashboards with median days-to-approve, queue aging, JDs by group/faculty, override
  frequency+reasons, per-reviewer throughput. The current dashboards analyze the *archive*, not
  the review *operation*. Source data (`review_actions`, `audit_log`, `canonical_jds`) already
  exists. *Fit:* clean read-only; every figure mutation-pinned. **Effort M.**
- **Bulk compliance review + remediation (assign / flag / export only).** An HR work-surface to
  select JDs by facet (unit / group / failing-gate), re-run the validator across the set, and
  batch-assign or flag. Remediating **1,798** drafts is a cohort job. *Fit:* **HARD FLAG — bulk
  _approve_ would violate "nothing auto-publishes."** Bulk stops at assign/flag/export; publish
  stays an individual human decision. **Effort M.**
- **Manager reclassification questionnaire (JDQ/JAQ) intake.** A rules-as-data questionnaire for
  "my duties materially changed" that red-lines a JD draft and routes it into classification
  review — the highest-volume manager HR workflow at a Canadian university. Reuses the Phase-5
  `assemble_jd(answers)` machinery. *Peers:* UBC JDQ → reclassification. *Fit:* questionnaire as
  versioned YAML; output a DRAFT into the human queue. JDFN-scoped (CUPE waits on HR-194). **Effort M.**

### Explicitly OUT / blocked (invariant conflicts)
- **Cloud skills extraction** (Lightcast / Workday Skills Cloud / Textkernel cloud endpoints) —
  vendor egress of JD content, **breaches invariant 1.** Adopt the *open taxonomy data* (ESCO,
  O*NET) and extract with our own Ollama embeddings instead.
- **Workday-style auto-post of an approved requisition** to job boards — **breaches invariant 2.**
  Keep an explicit human publish action.
- **LLM-computed EDI/quality scores or LLM-assigned classification grades** — score and
  approvability must come from the deterministic rulebook (invariants 3/4); the LLM may only
  advise, self-hosted. Proprietary Hay/WTW point charts must never be embedded (licensed).
- **Hosting/crawling a `schema.org` JobPosting careers page** — ATS territory, out of remit.
  Fine only as a deterministic export artifact of *approved* postings.

---

## 4. Strategic / bigger bets (L/XL) — mostly HR-gated

- **The 4.5 HR pilot — highest-value single action.** The publish spine (re-validation at
  approve, override-with-reason, tamper-evident audit) is machine-tested, and it has now been
  driven by hand: **4 canonical JDs are published** and `review_actions` holds **6** rows
  (measured 2026-08-04). *The earlier "zero canonical JDs are published" is false and has been
  corrected.* But **4 of 1,802 roles, against a rulebook whose every entry is still `open`, is a
  smoke test, not the pilot** — no reviewer has worked a cohort, and no ruling has been recorded.
  Run 5–10 clusters end-to-end; feedback becomes fixtures/rules and calibrates the provisional
  `open` rewrite/quality/reasoning-effort defaults (HR-176..192). The proving ground for everything else.
- **HR ratification of the decision register (Phase 2.7) — the actual critical path.** **Every**
  decision is `open`, including the bar itself; the baseline already proved the operative gate
  is a 100–150-word summary length masquerading as a quality bar. **An HR team cannot run a bar
  nobody has signed.** The three "our-defect" decisions (2, 5, 7) were already fixed + re-baselined
  in Phase 2.6, so HR is looking at corrected numbers; the remaining decisions (1, 1b, 2b, 3, 4, 6,
  8) are genuinely HR's to rule on. Governance, not code, is the bottleneck.
- **Standardized skills / competency layer against ESCO / O*NET (self-hosted).** The highest-
  leverage *technical* addition: skills today are an idf-less keyword bag, empty for ~41% of JDs
  (HR-149), weakening Tier-3 dedup, clustering, search, and every skills view. Load ESCO/O*NET as
  local rulebook data and extract with our own `nomic-embed-text` (or a locally-hosted JobBERT).
  Unlocks occupation codes for cluster naming, hybrid faceted search, the barrier/inflation check,
  and pay-equity comparators. *Fit:* fits invariant 1 *only if* extraction is self-hosted. **Effort L.**
- **CUPE / WJQ quality bar (HR-194) — the largest deferred scope question.** CUPE is ~29.5% of the
  archive (~4,300 WJQ files), parsed but deliberately unserved because there's no ratified WJQ bar.
  A third of the corpus being "come back later" is a real operational hole. **A whole project that
  starts with HR defining a WJQ ruleset + oracle**, then a `cupe` token in `segmentation.yaml`.
  Prerequisite: WJQ boilerplate redaction (the biggest flagged clusters are template artifacts).
  **Effort XL, HR-gated.**
- **BC Pay Transparency Act pay-range gate on postings.** Live BC law binding SFU: since 2023-11-01
  every publicly advertised posting must state a genuine expected pay/range. A posting surface with
  no pay-range gate would let SFU publish an *illegal* ad — exactly the jurisdiction-specific,
  high-consequence rule the gate+register machinery is built for. Needs a pay-band field on the
  canonical JD + band-source/"too-wide" decisions registered. *Fit:* deterministic gate blocking
  *export*; data internal. **Scope honesty:** the law covers ALL postings incl. CUPE, but JD Bank
  authors only JDFN — this protects JDFN postings, it does not make SFU org-wide compliant. **Effort M–L.**

---

## 5. Suggested sequencing (next 5 milestones)

The path interleaves cheap engineering that *enables* the pilot with the external governance
track only HR can advance.

1. **Make the pilot runnable** (weeks, mostly S) — ~~structured per-field editor (kills the
   raw-JSON blocker)~~ **DONE 2026-07-28** · ~~concurrent double-approve test~~ **DONE 2026-07-29** ·
   ~~version-diff view~~ **DONE 2026-07-29** · ~~embed the Bank's own roles so it can search its
   output~~ **DONE 2026-08-04 (`cadfc30`, as `make embed-roles` — no publish hook, by design)** ·
   ~~find a JD by its title~~ **DONE 2026-08-03/04** · ~~propose an update to a published JD~~
   **DONE 2026-08-02 (`802bff0`)** · refresh HANDOFF + reconcile PRs. *(The "three our-defect review-packet items + re-baseline" were **already done in
   Phase 2.6** — verified 2026-07-29 against the rulebook: HR-120 `banned_phrase_scope`, HR-121
   `evaluable:false`, HR-122 4th era band; POST-REVIEW-CHANGE-PLAN.md "steps 1–3 are DONE". Not
   pending.)* *A reviewer cannot pilot against a JSON textarea.*
2. **Run the 4.5 HR pilot + start ratification** (external, L) — drive 5–10 clusters with a real
   reviewer; convert judgment calls into fixtures/rules; put the six genuine HR decisions in front
   of HR. **This is the gate** — a signed bar + pilot fixtures precede any production rollout.
3. **Post-ratification hardening + author-facing EDI/accessibility** (M) — reinstate gates the
   ratification enables (HR-119/121); ship plain-language/accessibility scoring, the
   required-vs-preferred split, the soft coded-language lexicon (the meter itself and the
   ~~near-duplicate authoring guard~~ already shipped); plus the auth hardening
   (`review_actions → users.id` FK, tamper-*prevention* grants, CAS production verification).
4. **Operate at scale** (M/L) — multi-step approval routing (encode the real Dept→Faculty→Comp
   chain the pilot revealed), HR operational analytics, bulk assign/flag remediation, the approved-
   position template library. Start the skills/competency taxonomy here — the long pole that
   unlocks milestone 5's precision.
5. **External posting + scope expansion** (L/XL, HR- and law-gated) — JD→posting transform +
   `schema.org` export, gated behind the BC pay-range gate and the territorial-footer sign-off. In
   parallel, open the CUPE/WJQ track (boilerplate redaction first, then HR defines the WJQ
   ruleset/oracle) to finally serve the ~30% of the archive left on the shelf.

---

*Method:* generated 2026-07-28 by a multi-agent review (repo backlog + workflow map; web research
across candidate/posting, HR-workflow/classification, governance/EDI/accessibility, and
AI/skills/automation lenses) synthesized against the six invariants. Peer features are factual
summaries of what named systems/universities publicly offer, not endorsements. Related:
`HANDOFF.md`, `docs/plan.md`, `docs/decisions/HR-DECISION-MATRIX.md`, `docs/OPERATOR-GUIDE.md`.

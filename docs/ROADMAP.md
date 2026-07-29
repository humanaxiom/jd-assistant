# JD Bank — Roadmap & Backlog

**Updated:** 2026-07-28. Produced from a review of the repo backlog + main workflow and a
scan of peer-university JD/HR systems (UBC, Toronto, McGill; Workday, PageUp, Cornerstone,
PeopleAdmin/Unified Talent, JDXpert, Interfolio). Every item respects the six hard
invariants; conflicts are called out explicitly.

> **The governing reality:** the engineering pipeline is essentially built and has run over
> the real 14,565-file corpus end-to-end. What stands between it and daily HR use is
> **governance** (the approval bar is unsigned — all 192+ HR decisions are `open`), **a
> first human pilot** (nothing is published yet), and a handful of usability/scope gaps.
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
| Pipeline | **WJQ boilerplate redaction before harmonization** — WJQ over-clusters on template+seniority; the two biggest flagged clusters ("Untitled Position" n=132/108) are template artifacts. Blocks WJQ harmonization. | open (P4 priority) | L |
| Pipeline | Embed **published canonicals** into the Neo4j index (search covers only the archive today) | open | S/M |
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
| Rulebook | **HR ratification** of the decision register (all 192+ `open`) — the actual critical path | open (external) | L |
| Rulebook | HR-041/120 banned-phrase completeness (fires on only 10/14,522 — guard-rail or gap?) | open (external) | S |
| Rulebook | HR-042 `QUAL-MINIMUM` overridable rationale evaporated — HR should decide on purpose | open (external) | S |
| Rulebook | Reinstate `SFU-STRUCT-HOW-WHY` (HR-119/121) once `how_why` can be populated | open | S–M |
| Rulebook | CUPE/WJQ authoring scope (HR-194) — a whole project, HR-gated | open | XL |
| Ops | Footer / territorial-acknowledgement wording sign-off (blocks external export) | open (external) | S |
| Ops | Backup + reindex runbooks; rate/size limits (Phase-6 hardening) | open | M |
| Ops | GitHub Actions billing block — reconcile open PRs + re-run CI on `main` | open (external) | S |
| Chore | `jd_core → jd_bank` import edge; `get_session` → `api/deps.py` shim | open | S |
| Docs | Refresh HANDOFF.md for the auth/RBAC + operator-guide work | open | S |
| Phase 7 | Role-duty overlap graph (Neo4j); Hay-readiness summaries; transposer service; M365/SharePoint | deferred | S–XL |

---

## 2. Quick wins (S effort, high value)

Mostly open backlog items or thin surfacings of machinery JD Bank already owns. **Several
unblock the pilot** — do them first.

- **Embed published canonicals into the vector index.** The read side of search exists; the
  write-on-publish hook doesn't — so the moment HR publishes a canonical, it's invisible to
  the Builder's own "start from an existing JD." The Bank can't search its own output. Small
  write path; unblocks the template-library and near-duplicate-guard features below.
  *Invariant:* embeddings stay on self-hosted Ollama behind the egress guard.
- **Coded-language / gender-lean meter in the live Builder panel.** The exact-match banned-
  phrase gate fires on only 10/14,522 files (HR-041 suspects it misses what SFU authors
  actually write). A softer masculine/feminine/age-coded lexicon meter (Gender-Decoder
  pattern) catches lean the list misses and plugs into the existing 5.3 compliance panel.
  *Invariant:* pure-YAML deterministic scan, registered, advisory — keep it off the LLM.
- **Authoring-time "is this role already covered?" near-duplicate guard.** JD Bank *measured*
  that SFU's redundancy is heavy cross-position cloning (77% of Tier-1 groups). Turning 5.4
  search from opt-in into a proactive "3 roles are ~87% similar — clone one?" prompt prevents
  new duplicates at the source. *Invariant:* read-only, suggests-never-blocks, threshold registered.
- ~~**Concurrent double-approve test.**~~ **DONE (2026-07-29, `7ce53db`).** A mutation-verified
  integration test orchestrates two concurrent approves and proves the `FOR UPDATE` lock lets
  exactly one publish (the other → `IllegalTransitionError`).
- ~~**Side-by-side JD version diff (draft vs last-approved).**~~ **DONE (2026-07-29, `main`).**
  Pure `jd_core/bank/version_diff.py` (complete section serialization — catches the presence
  booleans `render_sfu_jd_text` drops) + `review.get_version_diff` (last PUBLISHED version of the
  cluster) + a standalone `/jd-bank/ui/review/{id}/diff` page linked from review detail.
- **Reinstate `SFU-STRUCT-HOW-WHY`** if the `how_why` field can be populated (retired only
  because the parser couldn't fill it; designed to return "with one YAML word").
- **Refresh HANDOFF.md + reconcile the open GitHub PRs.** The single-source-of-truth handoff
  predates ADR-008, and Actions is billing-blocked so several PRs are unmerged while work went
  to `main`. Accumulating confusion debt for every future session.
- **Footer / territorial-acknowledgement sign-off.** A single `boilerplate.yaml` constant that
  blocks any external `.docx`/posting export — a verification task, get it in front of the
  right person before the posting features can ship externally.

---

## 3. High-value features (M/L)

From peer research + backlog, each mapped to JD Bank's architecture, ordered roughly by leverage.

- **Structured per-field editors (duty % / KSA modifiers) — the #1 usability blocker.** Both
  the Builder form (lossy — drops action-verbs/modifiers) and the reviewer edit view fall back
  to a raw-JSON `<textarea>`. No reviewer can be asked to hand-edit JSON. *Peers:* JDXpert Job
  Builder field-level editing (UC Berkeley, Auburn, UIC). *Fit:* clean — deterministic assembly,
  validator still the oracle. **Effort M.**
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
  blank form. Turns the 1,801 latent drafts into the recruiter's default starting point. *Peers:*
  PeopleAdmin "living library of PDs"; Workday requisition reuse. *Fit:* strong; **depends on the
  embed-published-canonicals quick win**; clones re-enter the review queue. **Effort M.**
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
  batch-assign or flag. Remediating ~1,801 drafts is a cohort job. *Fit:* **HARD FLAG — bulk
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
  approve, override-with-reason, tamper-evident audit) is machine-tested but no human has ever
  driven a real judgment call, and **zero canonical JDs are published.** Run 5–10 clusters
  end-to-end; feedback becomes fixtures/rules and calibrates the provisional `open`
  rewrite/quality/reasoning-effort defaults (HR-176..192). The proving ground for everything else.
- **HR ratification of the decision register (Phase 2.7) — the actual critical path.** All 192+
  decisions are `open`, including the bar itself; the baseline already proved the operative gate
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
   ~~version-diff view~~ **DONE 2026-07-29** · embed-published-canonicals write path · refresh HANDOFF
   + reconcile PRs. *(The "three our-defect review-packet items + re-baseline" were **already done in
   Phase 2.6** — verified 2026-07-29 against the rulebook: HR-120 `banned_phrase_scope`, HR-121
   `evaluable:false`, HR-122 4th era band; POST-REVIEW-CHANGE-PLAN.md "steps 1–3 are DONE". Not
   pending.)* *A reviewer cannot pilot against a JSON textarea.*
2. **Run the 4.5 HR pilot + start ratification** (external, L) — drive 5–10 clusters with a real
   reviewer; convert judgment calls into fixtures/rules; put the six genuine HR decisions in front
   of HR. **This is the gate** — a signed bar + pilot fixtures precede any production rollout.
3. **Post-ratification hardening + author-facing EDI/accessibility** (M) — reinstate gates the
   ratification enables (HR-119/121); ship the coded-language meter, plain-language/accessibility
   scoring, required-vs-preferred split, near-duplicate authoring guard; plus the auth hardening
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
`HANDOFF.md`, `docs/plan.md`, `docs/decisions/HR-REVIEW-PACKET.md`, `docs/OPERATOR-GUIDE.md`.

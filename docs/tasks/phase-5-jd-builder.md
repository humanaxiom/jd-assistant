# Phase 5 — JD Builder (forward-looking JD Composer)

**Status:** PLANNED (2026-07-22). Refines `docs/plan.md` §Phase 5 (JD Composer) into
session-sized, TDD-driven tasks. This is the project's **first forward-looking, user-facing
product**: everything to date (baseline, dedup, cluster, harmonize, review queue) analyses the
*existing* archive; the Builder helps a hiring manager or recruiter **author a new SFU-compliant
JD from scratch**, with live compliance feedback, and routes the result into the same
human-approval review queue.

## Why this slots in now, and where

- **Parallel track to the 4.5 HR pilot.** 4.5 needs a real HR reviewer's calendar time (external
  dependency); the Builder is independent engineering that can proceed while we wait. Neither
  blocks the other — they meet at the review queue.
- **No GPU dependency for the MVP.** The compliance core is the **deterministic validator**
  (`evaluate_jd_rules` → `build_report`), which is pure and runs under `make gates` with no
  Ollama. The optional LLM-assist (5.5) reuses the existing injectable `ChatClient` and is fully
  testable with a mock client — so the full phase never contends with the in-flight full-archive
  run on `aria-gb10-2`.
- **Extends the existing surfaces, no new service plan** (same guardrail as 4.4d/4.6): the
  server-rendered Jinja UI inside the FastAPI `api` service (`/jd-bank/ui/...`), the review
  service as the sole publish authority.

## Invariants this phase inherits (do not re-decide)

1. **NN #1 — nothing auto-publishes.** A composed JD is a DRAFT; it enters the 4.4b review
   service and publishes only on explicit HR approval. The Builder never writes a published row.
2. **NN #3 — validator-as-oracle.** Live compliance is `evaluate_jd_rules` + `build_report`,
   never a bespoke or LLM-derived score. Any LLM-assist test asserts validator post-state, never
   verbatim model text.
3. **NN #2 — rules as data + HR register.** The authoring question set, any draft-mode leniency
   knob, and search thresholds are versioned YAML under `jd_core/rules/` (or `jd_bank`-local
   config) and registered `open` in the same PR. No hardcoded thresholds.
4. **NN #5 — self-hosted inference only.** LLM-assist and query-embedding go through the
   already-build-enforced egress guard (`security/egress.py`). No new sink escapes it.
5. **Scope = JDFN (APSA/APEX/POLY) template.** The validator/gates define a bar only for JDFN;
   CUPE/WJQ has no bar (HR-143). The Builder authors **JDFN-template** JDs and says so; a CUPE
   path is out of scope (Phase 7 at earliest).
6. **Docker-only, TDD, gates green** before every commit; each task = one session, reviewer +
   security merge-blocking per the subagent pipeline.

## Building blocks already in the repo (the leverage)

| Need | Reuse |
|---|---|
| Compliance engine | `jd_core.quality.validators.evaluate_jd_rules(sfu, raw_text)` → issues |
| Score / grade / gate decision / checklist | `jd_core.quality.report.build_report(...)` → `JDQualityReport` |
| Structured JD → raw text (feed the validator) | `jd_core.bank.render.render_sfu_jd_text(jd)` |
| JD contract | `jd_core.models.parsed_jd.SFUJobDescription` (10 sections, template order) |
| Approved action-verb list | `jd_core/rules/action_verbs.yaml` (already data) |
| LLM scaffolding + anti-fab guard + egress guard | `jd_bank/llm/ChatClient`, `rewrite/`, `quality/`, `security/egress.py` |
| Publish authority + queue | `jd_bank/review/service.py` (4.4b), `/jd-bank/ui` (4.4d) |
| Authoring question source | `docs/rulebook/jd-authoring-guide.docx`, `sfu-jd-standards.txt` |

**Confirmed build-new gaps:** no Neo4j vector *query* surface exists (3.2b only writes/upserts)
→ search (5.4) is genuinely new; no `jd_bank/composer/` package exists yet.

---

## Task breakdown

**Product decisions locked (2026-07-22, user):**
1. **Full guided builder first** — 5.1 + 5.2 + 5.3 ship as one MVP bundle (the first thing users see
   is the complete guided author→validate experience), not a standalone panel.
2. **Search corpus = cluster representatives + published canonicals** (5.4), labelled "reference,
   not approved".
3. **LLM authoring assist is IN the MVP** (5.5) — guard-permitted, anti-fab, validator-as-oracle.

**Revised MVP = {5.1 + 5.2 + 5.3} → 5.5 → 5.6** (guided author + live-validate + LLM-assist →
submit to review). **5.4** (search/clone) and **5.7** (export) layer on after.

> **GPU note (LLM-assist now in MVP):** development and `make gates` use the **injectable mock
> `ChatClient`** (every existing LLM path does), so the MVP is *built and tested* with no Ollama.
> Only the opt-in **live smoke test** of 5.5 needs `aria-gb10-2` — which the in-flight full-archive
> enrichment run currently holds. Build against the mock; run the live verification when the GPU
> frees (same posture as the HR-126 re-embed). No hard conflict, but 5.5's live sign-off waits.

### 5.1 — Live-compliance service + JSON endpoint  *(the core; do first)*

- **Goal:** given a (possibly partial) `SFUJobDescription`, return a live-compliance result: the
  full `JDQualityReport` (score, grade, gate decision, findings with evidence + recommendation)
  **plus** a per-section "draft status" that distinguishes *incomplete* (not authored yet →
  guidance) from *present-but-non-compliant* (a real finding). This is the design crux: the
  validator is built for a complete JD, so a half-finished draft would trip completeness gates —
  the panel must not read as "you failed" mid-authoring.
- **Files:** new `jd_bank/composer/__init__.py`, `composer/validate.py`
  (`assess_draft(jd) -> DraftAssessment`), `models` for `DraftAssessment` /
  `SectionStatus`; route `POST /jd-bank/compose/validate` (thin, transport-only) in
  `api/routes/`. Renders via `render_sfu_jd_text` then `evaluate_jd_rules` + `build_report`.
- **Register:** one `open` decision — the **draft-mode completeness policy** (which gates are
  surfaced as "incomplete guidance" vs "finding" while `status=DRAFT`). Keep it a YAML knob, not
  logic. No change to the scoring rules themselves (`rules_version` untouched).
- **Acceptance tests (TDD):** weak/short summary → `SUMMARY-LENGTH` finding surfaced with its
  recommendation (failing-fixture); a compliant complete JDFN JD → `gate_decision.approved` and
  zero blocking findings (passing-fixture); an *empty* draft → completeness items reported as
  guidance, **not** as a hard failure (pins the draft-mode split both directions).
- **Out of scope:** UI, LLM, persistence, search.

### 5.2 — Guided-authoring question set (rules-as-data) + draft assembly

- **Goal:** encode SFU's JAQ/Toolkit authoring flow as data, and deterministically assemble a
  filled question set into an `SFUJobDescription` in template order (KSA ordered K→S→A, duties in
  the action-verb shape, % allocation captured).
- **Files:** new `jd_core/rules/composer_questions.yaml` (question id → section → prompt text →
  inline authoring hint, e.g. "3–5 major duties, each starting with an approved action verb",
  "Position Summary 100–150 words") sourced from `jd-authoring-guide.docx`; typed loader entry;
  `jd_bank/composer/assemble.py` (`assemble_jd(answers) -> SFUJobDescription`, pure).
- **Register:** the question-set decisions `open` (which questions, which map to which section,
  the inline hints — these are authoring guidance, likely **unhashed** like `harmonization.yaml`
  since they don't change how a JD is *scored*).
- **Acceptance tests:** a fully-filled fixture assembles into an `SFUJobDescription` that the 5.1
  service reports as compliant; KSA-order and duty-shape assembly pinned; a sparse answer set
  assembles a partial draft (no crash, missing sections empty).
- **Out of scope:** UI rendering, LLM suggestions.

### 5.3 — Builder UI (server-rendered, extends `/jd-bank/ui`)

- **Goal:** a hiring manager opens `/jd-bank/ui/compose/new`, answers the guided questions, clicks
  "Check compliance", and sees the live panel (per-section status, word/%, KSA order, bias terms,
  footer presence, gate decision) rendered from the 5.1 result.
- **Files:** Jinja templates (`compose_new.html`, `compose_panel.html`) mirroring the dashboard
  theme; routes in `api/routes/ui.py` (or a sibling). **Dependency-free** POST-re-render first
  (the 4.4d pattern: `parse_qsl` on the raw body, no `python-multipart`); an inline `fetch` to the
  5.1 JSON endpoint for live-as-you-type is an optional follow-up, not MVP.
- **Register:** none (transport/presentation).
- **Acceptance tests (TestClient):** GET renders the form; POST with a weak summary re-renders with
  the `SUMMARY-LENGTH` guidance visible; autoescape verified on a user-supplied `<script>` title
  (no `|safe` on user text).
- **Out of scope:** persistence to the queue (5.6), search, LLM.

### 5.4 — Search + "start from an existing JD" (the Neo4j query gap)

- **Goal:** semantic + faceted search so a user can find a close existing JD and clone it as a
  starting draft.
- **Files:** new `jd_bank/composer/search.py` — embed the query via the guard-permitted embeddings
  client, run a **top-k Neo4j vector query** over the document index (the missing read side of
  3.2b), then Postgres facet filters (`employee_group`, band/grade, title family). Route
  `GET /jd-bank/compose/search`; a clone action prefills the builder.
- **Search corpus (DECIDED):** **cluster representatives + published canonicals**, every result
  clearly labelled "reference, not approved" until an HR-published canonical. Register the corpus
  choice `open`.
- **Register:** search top-k and any min-similarity floor, `open`.
- **Acceptance tests:** query-embedding path injectable/mockable (no live Ollama in `make gates`,
  same guard pattern as embeddings live-tests); facet filter pins; a known-neighbour fixture; the
  egress guard rejects a non-allowlisted embedding host (reuse the existing guard test shape).
- **Out of scope:** relevance tuning beyond the registered defaults.

### 5.5 — LLM authoring assist (optional, guard-permitted, decision-support)

- **Goal:** "improve this summary to 100–150 words", "suggest stronger action verbs", "flag
  gendered terms" — each a prompt + **anti-fabrication scrub** + **validator re-run**; drafts only,
  nothing bypasses review.
- **Files:** `jd_bank/composer/assist.py` reusing `jd_bank/llm/ChatClient` and the 4.2a/4.2b
  prompts; thin route(s). Injected/mockable client; egress-guarded.
- **Register:** any new prompt/model/effort knobs `open` (mirror HR-176..192 pattern), unhashed.
- **Acceptance tests:** assert **validator post-state** (e.g. summary now 100–150 words, gendered
  term gone), never the model's exact words (NN #3); anti-fab scrub drops a fabricated finding;
  guard rejects a cloud host.
- **Out of scope:** any auto-apply without the user accepting the suggestion.

### 5.6 — Composed draft → review queue integration  *(closes the MVP loop)*

- **Goal:** a completed Builder draft persists as a DRAFT `canonical_jds` row with provenance
  kind `composed` (vs `harmonized`) and enters the existing review queue; it publishes only on HR
  approval when gates pass (NN #1).
- **Files:** `jd_bank/composer/persist.py` (create the DRAFT via the same shapes the 4.4a producer
  uses; `cluster_id` nullable or a synthetic singleton; append-only audit row); a "Submit for
  review" action on the Builder UI. **No change** to the 4.4b service — it stays the sole publish
  authority.
- **Register:** the provenance-kind enum extension if needed, `open`.
- **Acceptance tests:** a composed draft appears in `/jd-bank/ui/queue`; it is **not approvable**
  until gates pass (reuse the service's `NotApprovableError` pin); approve publishes only when
  permitted; audit row written.
- **Out of scope:** notifications, reviewer assignment.

### 5.7 — Export to the SFU template (was plan §5.4)

- **Goal:** render an approved (or draft) JD to the official SFU `.docx` — TNR 10, bold headers,
  standard bullets, `(60%)`-style allocations, mandatory footer, empty sections dropped.
- **Files:** new `jd_export/` porting hris `bank/export.py` (#13) + styling; snapshot tests.
- **Open flag:** the **territorial-acknowledgement / EE footer wording** is the Phase-6 sign-off
  item — single config constant, verify against SFU's current official text **before external
  distribution** (blocks publish-for-distribution, not development).
- **Acceptance tests:** snapshot of a golden JD's rendered docx structure; footer sourced from the
  single constant; styling assertions.

---

## Sequencing summary

```
MVP:            { 5.1 + 5.2 + 5.3 } ─▶ 5.5 ─▶ 5.6      (guided author → live-validate → LLM-assist → submit to review)
Layer on:       5.4 (search/clone) · 5.7 (export)
Runs parallel:  4.5 HR pilot (external — HR reviewer time); they meet at the review queue.
```

Build order within the MVP bundle: **5.1 first** (the compliance engine everything else calls),
then **5.2** (question set / assembly), then **5.3** (UI over both), then **5.5** (LLM-assist,
mock-tested), then **5.6** (queue). Each still lands as its own reviewed PR.

## Product decisions — RESOLVED (2026-07-22, user)

1. **MVP shape** → full guided builder (5.1+5.2+5.3 bundle), not a standalone panel.
2. **Search corpus** (5.4) → cluster representatives + published canonicals.
3. **LLM-assist** (5.5) → **in the MVP** (mock-tested under gates; live sign-off waits for the GPU).

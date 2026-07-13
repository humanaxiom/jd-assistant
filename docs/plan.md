# JD Bank — Build Plan

**Project:** `jd-bank` — spin-off of the JD quality/harmonization capability from the SFU
Recruiter Assistant (`C:\repos\hris`) into a standalone JD Bank system: dedup + harmonization
+ composer over the SFU Job Description archive.

**Repo:** `C:\repos\JD-Assistant` — standalone project repo adopting v2 harness conventions
(ADR-004). Base harness rules are vendored at `harness-claude-code/CLAUDE.md`; project
invariants at root `CLAUDE.md`. Upstream harness: `C:\repos\agent-harnesses-v2`.

**Execution model:** Docker-only (ADR-006) — all code, tests, gates, and migrations run in
containers; only Ollama runs on host metal. Onboarding + workflow: `DEVELOPER_GUIDE_1.md`.

**Inputs:**
- JD archive: `C:\repos\hris\fixtures\SFU_JDs` — 14,565 documents, 1967→2026. Stratified
  golden sample in `fixtures/golden/`.
- Reusable code: `C:\repos\hris` — a Python 3.12 / pydantic-v2 monorepo. Per-module reuse
  verdicts in `docs/audit/hris-reuse-map.md` (16 EXTRACT / 8 REWRITE / 4 DISCARD, ADR-005).
- Rulebook: SFU HR JD standards (`docs/rulebook/`) — Position Summary rules, 3–5 duties,
  KSA order + modifiers, qualifications checklist, gender-neutral word list, restricted
  titles, quality gates, mandatory territorial-acknowledgement + Employment-Equity footer.

**Core deliverables:**
1. **Dedup engine** — exact, near-duplicate, and role-equivalent JDs across the archive.
2. **Harmonizer** — apply SFU HR guidelines to produce one canonical JD per role (human-approved).
3. **JD Composer** — recruiter tool to find existing JDs or compose new ones with live validation.

---

## 0. Design principles

- **Rulebook as tests.** SFU quality gates ("never approve a JD that…") translate 1:1 into
  pytest cases; every harmonization rule gets a failing test before implementation. The archive
  doubles as the fixture corpus. hris already embodies this — its 477-line per-gate test suite
  ports alongside the code.
- **Decision support, not decision making.** Canonical JDs are drafts until an HR reviewer
  approves them. The system never auto-publishes; overrides of blocking gates require a written
  reason.
- **Local-first.** All inference via Ollama on host metal; no JD content leaves the environment.
- **Job, not person.** SFU JDs describe the role, not the incumbent. Ingestion/harmonization
  normalizes incumbent names out of canonical JDs — a rulebook quality step, not a privacy gate
  (these are JDs, not resumes).
- **Provenance everywhere.** Every canonical JD traces to its source documents, cluster,
  validation reports, and reviewer decisions. Append-only audit log.
- **Extract, don't fork.** JD logic in hris is ported into `jd_core`. Because hris is already
  Python, EXTRACT is a near-verbatim port, not a re-derivation.

---

## 1. Target architecture

Standalone repo (ADR-004). Python packages live under the existing `core/src/` tree (package
`jd-bank-core`), alongside the vendored harness modules (`agents`, `gates`, `memory`,
`worker`, `api`, `models`). JD Bank adds:

```
core/src/
├── jd_core/            # ported from hris + new: parse, validate, bias, titles, KSA
│   ├── parser/         # docx/doc/rtf/txt → ParsedJD (pydantic)   [extract EXTRACT; JD segmenter NEW]
│   ├── rules/          # rulebook as DATA (YAML/JSON): gates, verb lists, coded-term lexicon, titles
│   ├── validators/     # section validators, quality gates, severity model   [jd_rules + rule_catalog EXTRACT]
│   ├── bias/           # gender-neutral checker + replacements   [part of jd_rules EXTRACT]
│   ├── bank/           # similarity, clustering, title_family, drift, provenance, render   [EXTRACT]
│   └── scrub/          # incumbent-name normalizer   [REWRITE from hris redaction primitives]
├── jd_bank/            # the new system
│   ├── ingest/         # archive walker, format detection, hashing, name-normalize
│   ├── dedup/          # tier 1–3 duplicate detection   [T1/T2 NEW; T3 from bank/similarity]
│   ├── cluster/        # role-equivalence clustering   [bank/clustering + hard constraints NEW]
│   ├── harmonize/      # canonical draft builder (deterministic merge NEW) + LLM rewrite [prompts EXTRACT]
│   ├── review/         # review queue, diffs, approvals, overrides
│   ├── composer/       # search + guided authoring + export
│   ├── api/            # FastAPI app   [route shapes from hris routes/jd_bank as reference]
│   └── workers/        # arq (Redis) jobs for pipeline stages
└── jd_export/          # SFU-template docx/pdf renderer   [export EXTRACT + styling NEW]
```

The precise placement (`core/src/` vs a top-level `src/`) is settled in Phase 1; the project
CLAUDE.md references `src/jd_core/rules/`, which resolves under `core/`.

**Stack:** Python 3.12, FastAPI, **PostgreSQL 16** (all relational/transactional SQL), **Neo4j**
(vector index — 768-dim cosine, `nomic-embed-text` — + graph memory), **Redis + arq** (queues),
Ollama (embedding + instruct models), pytest + ruff + black + mypy. Storage split per inherited
ADR-002: Postgres for SQL, Neo4j for vectors + graph, Redis for the queue. Everything runs in
Docker (ADR-006); Ollama on host metal (ADR-003).

**Data model (PostgreSQL — all relational/transactional data):**

| Table | Purpose |
|---|---|
| `source_documents` | raw file bytes ref, sha256, format, ingest metadata, normalization report |
| `parsed_jds` | ParsedJD JSONB per source doc, parser version, parse confidence |
| `validation_reports` | issues[] (code, severity, section, evidence), gate results, versioned |
| `dedup_edges` | doc↔doc similarity edges with tier + score + method |
| `clusters` | role clusters, membership, constraint metadata (employee group, level) |
| `canonical_jds` | canonical drafts + published versions, lineage to cluster/sources |
| `review_actions` | approvals, rejections, edits, override reasons, reviewer id, timestamps |
| `audit_log` | append-only event stream for everything above |

**Vectors (Neo4j):** per-document and per-section embeddings (768-dim cosine,
`nomic-embed-text`) live in Neo4j's vector index, each carrying a model tag for reindex safety
and a back-reference to its `parsed_jds` / `source_documents` row. Postgres holds no vectors.

**ParsedJD schema:** hris's `SFUJobDescription` (reuse map #1, EXTRACT — pure pydantic v2). SFU's
10-section template in order: identification, position summary, `duties: list[SFUDuty]`
(action_verb / statement / how_why), decision_making, problem_solving, `relationships`
(supervisory/internal/external), `qualifications: list[SFUQualification]`
(kind ∈ education/experience/knowledge/skill/ability/security, Toolkit modifier), plus
presence-booleans for About-SFU / territorial-ack / employment-equity. Coerces LLM `null`→`[]`.
This is the contract every stage speaks.

### Build-new gaps (not in hris — written fresh, on the critical path)

The reuse map is favourable — the pure rulebook/similarity/title/render engine ports nearly
verbatim — but three capabilities do not exist in hris:

1. **Dedup Tier-1 (SHA-256 exact) and Tier-2 (MinHash/5-gram near-dup).** hris has only the
   Tier-3 embedding+skill similarity signal. — Phase 3.
2. **Deterministic, LLM-free harmonization merge engine** (section selection, duty
   union/dedup/reorder, %-rebalance, KSA rebuild). hris harmonizes via an LLM prompt only. — Phase 4.
3. **Incumbent-name normalizer for JDs** (rulebook: job-not-person). hris redaction is
   résumé-oriented — reuse its name/contact primitives. — Phase 1.

---

## 2. Pipeline (end to end)

```
archive files
  → ingest (hash, format-detect, extract text [antiword/.doc + OOXML/.docx], name-normalize, store)
  → parse (docx/doc/rtf/txt → ParsedJD, JD section segmentation, confidence)
  → validate (rulebook → ValidationReport per JD)
  → embed (doc + section vectors via Ollama, stored in Neo4j vector index)
  → dedup  T1 exact | T2 near-dup | T3 role-equivalent
  → cluster (role groups under hard constraints)
  → harmonize (merge + rewrite → canonical draft + diff + report)
  → review queue (HR approves/edits/rejects; override reasons)
  → publish (canonical JD versioned; composer indexes it)
```

### 2.1 Dedup — three tiers

- **Tier 1 — exact (NEW):** SHA-256 over normalized text (lowercase, collapse whitespace, strip
  headers/footers/dates). The census measured ~13.5% exact-duplicate redundancy — immediate,
  quantified value.
- **Tier 2 — near-duplicate (NEW):** MinHash/Jaccard over 5-gram shingles for candidate pairs,
  confirmed by embedding cosine (`nomic-embed-text`, from the Neo4j vector index). Tuned on the
  Phase-0 label set (`fixtures/labels/pairs.csv`). ~56% of ID-bearing files are re-versions of
  an existing position, so this tier carries most of the collapse.
- **Tier 3 — role-equivalence (EXTRACT):** hris `bank/similarity.py` (#6) —
  `score = 0.45·vec + 0.45·skill + 0.10·seniority`, idf-weighted skill Jaccard, title
  normalization, clone verdict; pure math over a plain cosine float from Neo4j. **Hard
  constraints (NEW):** employee group and level-of-work band must match.

Output: `dedup_edges` + a reviewable duplicate report. Tier 1/2 groups collapse to a
representative; Tier 3 groups feed clustering.

### 2.2 Clustering → one canonical JD per role

hris `bank/clustering.py` (#7, union-find connected components over Tier-3 edges), **adding**
constraint partitioning (employee group × level band) and a max-diameter guard so chains don't
over-merge. Human-readable cluster labels from normalized titles (`bank/title_family.py`, #8).
Singleton clusters are fine — a role with one JD still gets a canonical version.

### 2.3 Harmonization → canonical draft

Per cluster:
1. **Score members** with the validator; rank sections individually (best Summary and best
   Qualifications may come from different docs). `bank/provenance.py` (#11) gives skill-frequency.
2. **Merge (NEW):** best-scoring section as base; duties = semantic-deduped union across members,
   reordered by significance, capped at 3–5 primary functions with % allocation rebalanced to
   100; qualifications rebuilt through the checklist with KSAs reordered K→S→A and every KSA
   traced to a duty (untraceable KSAs dropped and listed).
3. **Rewrite passes (LLM, rule-constrained):** hris `jd_harmonize_v1` / `jd_quality_v1` prompts
   (#17/#18). Summary → 100–150 words; weak verbs replaced from the approved list; gender-coded
   terms replaced; competency language stripped from Decision Making; working conditions stripped
   from Summary; supervisor names → "supervisor"; task detail lifted to duty level. Each pass =
   one prompt + deterministic post-check (validator re-runs). Port hris's **anti-fabrication
   guard**: drop any LLM finding whose evidence isn't a verbatim substring of the JD. Failed
   post-check → rejected and retried, never silently accepted.
4. **Footer:** inject the official territorial-acknowledgement + Employment-Equity statement from
   a single config constant (`bank/export.py`, #13). **Verify wording against SFU's current
   official text before first publish** (the source constant carries simplified orthography).
5. **Output:** canonical draft + full ValidationReport + per-source diff + "removed content and
   why" change log. `bank/render.py` (#12) renders ParsedJD → text.

### 2.4 Review queue

FastAPI + minimal UI: cluster view, draft-vs-sources diff, validation report with severities,
approve / edit / reject, mandatory reason on overrides of blocking gates. Nothing publishes
without approval; approval snapshots a versioned canonical JD. hris `routes/jd_bank.py` (17
endpoints) + `jd_bank_service.py` are the behavioral + API-shape reference — the Neo4j recall
Cypher ports directly (Neo4j is retained); the rewrite is re-wiring to JD Bank's own model.

### 2.5 JD Composer

- **Find:** semantic + faceted search over published canonicals (Neo4j vector search + Postgres
  facet filters). "Start from this JD" → clones a draft.
- **Create:** JAQ-style guided flow (SFU toolkit prompting questions) → assembles a draft in
  template order → live validation panel (word count, % totals, KSA order, bias terms, footer).
- **Export:** `jd_export` (from `bank/export.py`, #13) renders the SFU template — TNR 10, bold
  headers, standard bullets, (60%)-style allocations, mandatory footer, empty sections dropped.
  hris export is structurally correct but does not enforce the TNR-10 / bullet styling — that
  fidelity is new work on top of the port.
- Composer drafts enter the same review queue before becoming bank entries.

---

## 3. Phased delivery (harness epics)

Each phase is a harness epic; each task is sized for a single Claude Code session, tests first,
driven through the subagent pipeline (Planner→Tester→Coder(loop)→Reviewer→Security→Docs). CI
gates per harness defaults (ruff · black · mypy --strict · unit+coverage ≥ 80 · integration).

### Phase 0 — Discovery & audit ✅ COMPLETE
Delivered on `agent/p0-discovery`; awaiting human sign-off on ADR-005.
- **hris reuse map** → `docs/audit/hris-reuse-map.md` (30 modules; 16 EXTRACT / 8 REWRITE / 4 DISCARD).
- **Archive census** → `docs/audit/archive-census.md` + `fixtures/golden/` (44 stratified docs).
  14,565 docs; offline extraction solved (antiword for `.doc`, unzip for `.docx`, 0 failures;
  2 files unrecoverable); ~13.5% exact-dup + heavy revision chains.
- **ADRs** → ADR-004 (repo placement, ACCEPTED), ADR-005 (extract-vs-rewrite, PROPOSED),
  ADR-006 (Docker-only, ACCEPTED). ADRs 002/003 inherited.
- **Label set** → `fixtures/labels/pairs.csv` (101 stratified pairs, awaiting human verification).
- **Project CLAUDE.md** installed at root.

Human gate: approve ADR-005 before Phase 1.

### Phase 1 — Foundation: schema, ingest, parse
- **1.1** `ParsedJD` = port hris `SFUJobDescription` (#1) + `jd_quality.py` schemas (#2); JSON
  schema; property-based round-trip tests.
- **1.2** DB migrations (Postgres tables), Neo4j vector-index setup (768-dim cosine),
  docker-compose wiring, settings module.
- **1.3** Ingestion worker tuned to the real corpus: `.docx`/`.docm` via OOXML, **legacy `.doc`
  via antiword/LibreOffice in the ingestion image** (python-docx cannot read binary `.doc`),
  `.rtf` via striprtf, `.txt` direct; 2 outlier files (`.tif`, `.serv`) to a manual queue. Base
  on hris `parsing/extract.py` (#14). **Incumbent-name normalizer** from hris `redaction.py`
  primitives (#25) with a change report. Tests against golden sample.
- **1.4** Parser: JD section segmentation → ParsedJD, tolerant of old + new SFU templates (old
  heading map from `sfu-jd-standards.txt` Part 8 as fallback). hris `parsing/chunk.py` is
  résumé-shaped (#15) — build a JD segmenter, don't port it. Per-section confidence.

**Exit:** full archive ingests and parses with a metrics report (parse rate, confidence).

### Phase 2 — Validation engine (rulebook as code) — ✅ COMPLETE (2.1–2.5 all MERGED)
- **2.1** ✅ MERGED (PR #6, `43f29db`) — rules-as-data: 8 versioned YAML files under
  `core/src/jd_core/rules/` + typed loader (`get_rules()`), replacing hris `jd_rules.py` tables.
- **2.2** ✅ MERGED (PR #7, `9eaa39d`) — section validators (29 catalogued rules, each with a
  failing + passing fixture), porting hris `jd_rules.py` (#4) + `rule_catalog.py` (#5); emits
  `ValidationIssue{code, severity, section, evidence, recommendation}`.
- **2.3** ✅ MERGED (PR #8, `5b8d954`) — gate runner: "never approve if…" → 14 gates (12
  overridable, 2 non-overridable), boolean + reasons.
- **HR decision register** (added mid-phase, not in the original plan) — ✅ MERGED (PR #9,
  `c519bed`) — 58 decisions (all `open`) recording every non-trivial default for SFU HR to
  ratify; build-enforced against the live config. See `docs/decisions/HR-DECISION-REGISTER.md`.
- **2.4** ✅ MERGED — remaining EXTRACT modules landed into `jd_core` per ADR-005, keeping hris
  tests as the spec: **2.4a** bank value objects + provenance + render (PR #11, `43435a7`),
  **2.4b** title classifier + Hay signals (PR #12, `b71868a`), **2.4c** similarity + clustering
  + drift (PR #13, `58fc7d2`). Two new rule files (`hay_signals.yaml`, `comparison.yaml`) grew
  the decision register from 58 to 103 decisions (108 after 2.5-prep + scanner hardening). All 16
  EXTRACT-mapped hris modules are now
  ported or explicitly deferred (`export.py` → 5.4, prompt templates → 4.2, `jd_import_service`
  → 5). `similarity`/`clustering`/`drift` landed as pure, tested functions deliberately not yet
  wired to a `ParsedJD` — that adapter is Phase 3 work.
- **2.5-prep** ✅ MERGED (PR #16, `98c0add`) — two defects that would have corrupted the baseline.
  **HR-058**: the coded-term scan penalised `compassionate` inside SFU's own *mandated, do-not-edit*
  About-SFU paragraph — a compliant JD scored 91.5/A → 81.5/B, and omitting the paragraph tripped
  `SFU-COMP-ABOUT` instead. The scan now redacts SFU's mandated passages first; the exemption is
  granted to SFU's **text**, never to a **location** (verified against 11 adversarial JDs).
  **`rules_version`**: was the constant `jd_rules_sfu_v3` while the rules changed materially across
  2.2/2.3/2.4 — two reports stamped `v3` could come from different rulebooks. Now derived from rule
  content, so a stamped `ValidationReport` identifies the rules that produced it (non-negotiable #6).
- **Scanner hardening** ✅ MERGED (PR #17, `6b228d2`) — the scanners anchored terms against **raw**
  text, so they mis-fired on 13 rules in **both** directions (including `SFU-GATE-DUTY-PCT` silently
  finding *zero* allocations on a JD totalling 80%). Fixed with one shared fold (`textnorm.py`).
  Measured against the real archive: the zero-width-character defect moves **~nothing** (this corpus
  has none), while **line-wrapping** — antiword hard-wraps legacy `.doc` — was cutting
  `SFU-QUAL-EQUIVALENT` false positives by **~50%** (~10% of legacy JDs). **HR-108** registered
  (`open`): whitespace collapsing across a *paragraph break* would weld unrelated paragraphs and
  invent findings, including a non-overridable gate trip — so the default is paragraph-aware, and it
  costs zero of the win.
- **2.5** ✅ MERGED (PR #19, `7e75835`) — **the archive baseline: the approval bar met all 14,565
  real JDs and SURVIVED.** New `jd_bank/baseline/` package + `make baseline` (~9 min, single-process,
  archive bound read-only). 14,522 scored, 43 skipped, every file accounted for.
  **The bar is ratified by the data, not killed by it:** on the 874 JDs written under current
  practice, approval is **71.9%**, median score **77.3**, and **99.4% clear the score floor of 60**
  (it rejects 5). But the run overturned three things we believed:
  1. **A blended approval rate is a category error.** The whole-archive 4.3% and the "new"-era 10.0%
     both measure a *calendar*, not quality — `SFU-APPROVE-EDI-FOOTER` is a **date detector**,
     because the territorial acknowledgement is a rollout still in progress (0% in 2018 → 88.6% in
     2026). **Never quote them.**
  2. **Our era model is wrong** (HR-109/110/111): it assumes one transition; there are **two, four
     years apart** — the JDFN template (2019) and the footer (2023–24). A correctly-authored 2019 JD
     is un-approvable. 10.0% vs 71.9% is a **7× artefact of where we drew a line.**
  3. **The operative bar is not the score floor.** Of 246 current-practice blocks: summary word-count
     **134**, `QUAL-MINIMUM` **104**, score floor **5**. HR thinks it is ratifying a quality bar; it
     is ratifying a word count. And the #2 gate — all 104 `QUAL-MINIMUM` blocks — is
     `SFU-QUAL-BANNED-PHRASE`, **a scoping bug we had filed as a tidy-up**.
  Also: segmentation is rules-as-data (`segmentation.yaml`, registered but excluded from the
  `rules_version` digest); HR-047, expected to be the villain, blocks **zero** current-practice JDs;
  and HR-119 (new) records that `SFU-STRUCT-HOW-WHY` fires on **100% of the JDs we would approve**.
  **Deliverable: `docs/baseline/README.md`.**

Test suite at HEAD: **1114 passing**, coverage **97.37%**, all in Docker via `make gates`.
Decision register: **119**, all `open` — but see Phase 2.6 below: HR review is now unblocked.

**Exit: MET.** Validator passes the rulebook test suite; gate runner + decision register + 2.4
EXTRACT modules landed; the baseline is run and read.

### Phase 2.6 — HR ratification (NEW; added by the 2.5 result)

2.5 turned the register from a list of guesses into a list of **measured** decisions, which makes HR
review possible for the first time. Two documents drive it:
- **`docs/decisions/HR-REVIEW-PACKET.md`** — the 9 decisions that actually matter, written for a
  non-engineer, each with its measured impact and our recommendation.
- **`docs/decisions/POST-REVIEW-CHANGE-PLAN.md`** — for each possible ruling: which config key
  changes, what it moves, what test must go red.

**Sequencing is load-bearing.** Three of the nine are *our* defects, not HR questions, and they
distort the very numbers HR would be ratifying. Fix them and re-baseline **before** asking HR to
ratify anything:
1. `SFU-QUAL-BANNED-PHRASE` scoping (HR-041) — a bug, and the #2 operative gate.
2. `SFU-STRUCT-HOW-WHY` (HR-119) — fires on 100% of approvable JDs; likely a detection bug.
3. The era model (HR-109/110/111) — a modelling error.

Then take Decisions 1/3/4/6 to HR against the corrected baseline. The register already enforces the
ratification record: a `ratified` decision **must** carry `decided_by` / `decided_on` /
`decision_note`, or the rulebook fails to load.

> **Do not** hand HR the current numbers, collect 119 ratifications, and *then* fix the bugs — the
> register would record "HR ratified 60.0" against a distribution that no longer exists.

### Phase 3 — Dedup & clustering
- **3.1** Tier 1 exact-dup + report (NEW). Early quantified win — **2.5 already measured it**:
  14,522 → **12,557** after exact-content dedup, and **6,295** latest-version-per-position.
  `aggregate.population()` computes all three populations, and `rows.jsonl` carries `sha256` /
  `position_ids` / `version_date` per file. Much of 3.1 is done.
- **3.2** Embedding service (Ollama client, batching, upsert into Neo4j vector index; doc +
  section level, model tag).
- **3.3** Tier 2 near-dup (NEW): MinHash → cosine confirm; tune on the label set; precision/recall
  regression-gated in CI.
- **3.4** Title normalizer (#8) + Tier 3 role-equivalence (#6) + hard constraints (NEW).
- **3.5** Clustering (#7 + constraints NEW) + cluster report artifacts for HR eyeball pass.

**Exit:** duplicate + cluster reports over the full archive; metrics meet the agreed floor.

### Phase 4 — Harmonization & review
- **4.1** Merge engine (NEW): section selection, duty union/dedup/reorder, % rebalance, KSA
  rebuild — pure functions, heavy unit tests, no LLM. Uses `bank/provenance.py` (#11).
- **4.2** Rewrite passes: hris prompts (#17/#18); prompt + post-check + retry + anti-fabrication
  guard; validator-as-oracle snapshot tests.
- **4.3** Change-log / diff generator; render via `bank/render.py` (#12).
- **4.4** Review queue: FastAPI + minimal UI + audit-log wiring (hris routes/service as reference).
- **4.5** Pilot: 5–10 clusters end to end with a real HR reviewer; feedback becomes fixtures/rules.

**Exit:** first human-approved canonical JDs published; audit trail complete.

### Phase 5 — JD Composer
- **5.1** Search API: Neo4j vector semantic search + Postgres facet filters.
- **5.2** Guided authoring (JAQ question set → draft assembly) + live validation endpoint.
- **5.3** Composer UI (lean: server-rendered or small React app — decide via ADR).
- **5.4** `jd_export`: port `bank/export.py` (#13) + add SFU-template styling + snapshot tests.
- **5.5** Composer drafts → review queue integration.

**Exit:** recruiter can find, clone, compose, validate, and export a JD; drafts land in review.

### Phase 6 — Hardening & handover
Auth, rate/size limits, backup + reindex runbooks, ops docs, and the
**territorial-acknowledgement wording verification** sign-off before any external distribution.

### Phase 7 — Optional / later
Neo4j **domain** role-duty overlap graph (org-design queries — the only deferred Neo4j piece);
Hay-readiness summaries (port `bank/hay_signals.py`, #9, is cheap); transposer-as-a-service for
old-template uploads; M365/SharePoint surfacing.

---

## 4. Working agreements

- **One session = one task = tests first**, driven through the subagent pipeline; reviewer +
  security are merge-blocking. Task files: goal, files in scope, fixtures, acceptance tests, out-of-scope.
- **Validator is the universal oracle.** LLM-touching tests assert validator post-state, never
  verbatim model text.
- **Rulebook as data.** Gates/word-lists/verb-lists live in versioned YAML under `jd_core/rules/`
  — never hardcoded.
- **Docker-only (ADR-006).** All code, tests, gates, migrations run in containers; `make gates`
  runs the full suite (incl. testcontainers integration) in the one-shot `gates` service —
  self-contained and CI-identical. Only Ollama runs on host metal.
- **Fixtures are sacred.** `fixtures/golden/` + `fixtures/labels/` change only via reviewed PRs;
  every pilot bug becomes a fixture.
- **Human approval.** Canonical JDs are drafts until an HR reviewer approves; nothing auto-publishes.
- **No cross-phase leakage.** Composer work waits until canonical publishing works.

## 5. Risks & mitigations

| Risk | Mitigation |
|---|---|
| hris code more entangled than expected | Resolved by Phase 0: per-module verdicts (ADR-005); pure engine ports near-verbatim, coupling confined to hris's own schema/graph |
| Legacy `.doc` needs non-Python tooling | Census validated antiword + OOXML-unzip (0 failures); ship antiword/LibreOffice in the ingestion image — python-docx cannot read binary `.doc` |
| Old/scanned docs unparseable | Only 1 `.tif` + 1 `.serv` in 14,565; route to a manual-triage queue with confidence gating; the ancient `.doc` corpus parses cleanly |
| Incumbent names surface in canonical JDs | Normalizer strips them during ingestion/harmonization (rulebook: job-not-person); prioritize OLD/TRANSITION bands. Not a privacy blocker — JDs are not resumes |
| Three build-new gaps underestimated | Called out in §1; each is a bounded, dedicated task; the rest is port-and-rewire |
| Over-merging distinct roles (Tier 3 false positives) | Hard constraints (group × level band) + diameter cap (both NEW) + HR eyeball pass before harmonization |
| LLM rewrites drift from rules | Deterministic post-checks + validator re-run per pass + anti-fabrication guard; rejected passes retried, never accepted silently |
| Canonicals treated as approved when they aren't | Publishing requires explicit reviewer approval; UI labels drafts loudly; audit log |
| Footer wording incorrect | Single config constant + explicit Phase-6 verification; blocks external distribution, not development |

## 6. Success criteria

1. 100% of the archive ingested; parse rate and confidence reported.
2. Duplicate report with measured precision/recall against the label set.
3. One approved canonical JD per role cluster, each passing all blocking gates, with full lineage.
4. Recruiters can find or compose a JD in under ~10 minutes with live validation, and export it
   in the official SFU format.
5. Every rulebook gate exists as an automated test; CI green is the definition of "compliant."

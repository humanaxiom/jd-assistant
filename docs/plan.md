# JD Bank — Build Plan

> **Forward-looking roadmap + current backlog:** see [`docs/ROADMAP.md`](ROADMAP.md)
> (quick wins, high-value features grounded in peer-university systems, and sequencing).
> This file remains the phase-by-phase build record.

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

- **Find:** *(design corrected 2026-08-05 — what shipped is materially different from this line's
  original "semantic + faceted search over published canonicals".)* **Four ranked passes**, in
  order: (1) harmonized **role titles** in Postgres, (2) archive **document titles** in Postgres —
  collapsed into the role they were harmonized into — then (3) semantic neighbours among
  **roles** (`jd_role_embeddings`) and (4) semantic neighbours in the **archive**
  (`jd_document_embeddings`). **The title passes are Postgres-side because the vectors cannot see
  the title**: `embeddings.yaml: include_title_in_document: false`, which is exactly what makes
  dedup/clustering title-agnostic — flipping it would make title search work by silently breaking
  that guarantee. A title hit therefore carries **no similarity score**; it was not found by
  distance. Same-titled roles are disambiguated **by department** at the single exit point.
  "Start from this JD" → clones a draft. See `jd_bank/composer/search.py`.
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

*(The 2.5 figures above are the pre-2.6 rulebook, `…+2cb6723a5241`. Phase 2.6 corrected three
defects and moved them — see below.)*

**Exit: MET.** Validator passes the rulebook test suite; gate runner + decision register + 2.4
EXTRACT modules landed; the baseline is run and read.

### Phase 2.6 — ✅ MERGED — three rulebook defects the baseline exposed

2.5's most valuable output was not a score. It was the discovery that **three of our own rules were
broken and were distorting the very numbers SFU HR was about to ratify.** Fixed and re-baselined
**before** the HR packet went out — because handing HR figures we already knew were wrong, collecting
their ratification, and *then* correcting them would have made the sign-off meaningless.

1. **`SFU-STRUCT-HOW-WHY` was unevaluable** (HR-121). It counted duties lacking `how_why` — a field
   the parser **never populates** (`segmenter.py`: *"left empty"*). It fired on **100% of the JDs we
   would approve**: zero discriminating power, a constant subtracted from every score. **The same
   class as the 2.4 `render.py` bug — faithful to hris, wrong here**: in hris an LLM filled the
   field; our regex parser structurally cannot. Retired as **data** (`RuleSpec.evaluable`), so Phase 4
   reinstates it with one YAML word. Finding 8,593 → 0; scores rose on 9,217, unchanged on 5,305,
   **fell on 0**. *(Precisely: every score that carried the finding rose. NOT "every score rose".)*
2. **`SFU-QUAL-BANNED-PHRASE` scanned the whole document** (HR-120) though its rule text says
   *Qualifications only* — so *"Responsibilities may include arranging catering…"* in **duties** prose
   tripped a Qualifications gate. It drove **all 104** `QUAL-MINIMUM` blocks. Now a knob
   (`banned_phrase_scope`). Blocks 104 → 0, **+59 approvals — the entire gain.**
3. **The era model conflated two rollouts** (HR-122). 4th band `current` (2024+) added.

**Net: approval 71.9% → 78.6%, median 77.3 → 79.0, blocked 246 → 187, score-floor rejections 5 → 2.**

Test suite **at that point (Phase 2.6)**: **1143 passing**, coverage **97.40%**. Decision register:
**122**, all `open`. Rulebook: `jd_rules_sfu_v4+8c004c4dadd1`. *(Dated record, not a current
figure — the "at HEAD" wording was wrong the moment the next commit landed; for today's numbers
read the newest `make gates` line in `git log` and the register's own header.)*

### Phase 2.7 — ⏭ HR ratification (needs SFU, not us)

The register is now a list of **measured** decisions rather than guesses, so HR review is possible
for the first time. Two documents drive it:
- **`docs/decisions/HR-DECISION-MATRIX.md`** — the single consolidated HR review + decision matrix
  (system explainer + evidence + the eight settings that matter), written for a non-engineer, each
  with measured impact and our recommendation. (Folds in the former HR-REVIEW-PACKET / -REQUEST.)
- **`docs/decisions/POST-REVIEW-CHANGE-PLAN.md`** — for each possible ruling: which config key
  changes, what it moves, what test must go red.

Six decisions remain, and they are genuinely SFU's: the 100–150 word range that is the *real*
gatekeeper (134 of 187 blocks); the un-appealable no-placeholders gate; the footer gate blocking 94%
of the archive; the score/grade/severity floors (recommend ratify — they reject 2 of 874); whether
the banned-phrase list is missing the phrases SFU authors actually use; and whether "current" means a
date or the footer's presence.

The register enforces the record: a `ratified` decision **must** carry `decided_by` / `decided_on` /
`decision_note`, or the rulebook fails to load.

**P1.3 — the register is TIERED (2026-08-13).** Two HR complaints traced to one cause: the register
did **two incompatible jobs**. It is simultaneously the list of policy calls HR must sign *and* the
completeness ledger that stops an engineer tuning a threshold silently — and the second job requires
registering embedding dimensions, MinHash band counts and model temperatures, which HR must never be
handed. Undifferentiated, the ask was unanswerable. Every entry now carries a required
`tier` — `hr_policy` / `hr_informed` / `technical` — and the generated register leads with **"Your
decisions"**. Measured: **65 hr_policy · 49 hr_informed · 83 technical**, so the ask is 65 settings
rather than 197.

Three properties make it more than a label:
- **`tier` has no default.** A new parameter cannot be filed into a tier by omission — which is how
  197 undifferentiated entries accumulated in the first place.
- **Nothing became unregistered.** Every id survives and every build-breaking check still walks all
  197; tune a `technical` value without updating `current_default` and the build fails exactly as
  before. The tier changes the *audience*, never the coverage. Pinned by a test.
- **`comparison.yaml` and `hay_signals.yaml` may never be `hr_policy`** — ADR-007 disclaims them as
  *not* formal classification and `models/bank.py` makes a Hay grade unrepresentable, so asking HR to
  ratify a similarity weight would contradict both. Pinned by a test, and **proved by mutation**:
  promoting one comparison weight into `hr_policy` turns it red, as does demoting the score floor out
  of it.

`rules_version` **unmoved** — `decision_register.yaml` is unhashed and no default changed. The count
of record stays the generated register's own header; per CLAUDE.md it is **not** restated in code.

### Phase 3 — Dedup & clustering — ✅ COMPLETE (3.1–3.5 all MERGED and RUN)

- **3.1** ✅ **MERGED** (PR #21) — Tier-1 exact dedup, and a **schema correction that had to come
  first**. `source_documents.sha256` was `UNIQUE` and `ingest_document()` returned the existing row
  on a duplicate — so ~**1,972** archive files would have been ingested with their **filenames
  discarded entirely**, while `DedupEdge`/`DedupTier` sat in the schema as **dead code** (an edge
  needs two source ids; the duplicate never got one). A provenance bug against non-negotiable #6.
  **Now: one row per FILE, and dedup is a *finding* — `DedupEdge` rows — not a silent write-time
  collapse.** All three tiers write into one edge table. Migration `0002` drops the UNIQUE (keeps the
  index) and its **downgrade refuses** if duplicate hashes exist rather than deleting rows to make
  room for itself. Ingest is keyed `(storage_ref, sha256)` and its race path moved to a SAVEPOINT —
  the old `session.rollback()` rolled back the *caller's* whole transaction, silently discarding a
  batch ingest's uncommitted work.
  - **Measured (verified independently, `Get-FileHash`, zero shared code):** 1,037 groups · 3,009
    files in a group · **1,972 redundant** · largest group 11.
  - **The finding that pays for 3.5: 798 of the 1,037 groups (77%) span MORE THAN ONE
    `position_id`** — 2,463 files. Not re-saves: **distinct positions sharing a byte-identical JD.**
    Only 141 groups are genuine re-saves. **Tier-1 hands clustering a role cluster with similarity
    pinned at 1.0, for free, before a single embedding is computed.**
  - `comparison.cluster_algo` can **no longer lie** (the backlog landmine, *"fix before Phase 3
    writes a cluster row"* — done on schedule): a closed `Literal` **and** `build_clusters` genuinely
    dispatches on it.
- **3.2a** ✅ **MERGED** (PR #23) — archive→Postgres ingest driver. Two blocking defects fixed first:
  (1) **`parse_and_store` now idempotent** — migration `0003` adds `uq_parsed_source_parser` unique
  constraint; upgrade refuses rather than deleting rows. (2) **Incumbent names stay clean** — driver
  parses the normalized text, never raw bytes. Also: `_stable_reason` deduped to one home (extractor
  `read_document_bytes`), `stream_sha256` hashes in 1 MiB chunks so oversized files still get a row.
  **Result: full archive (14,565 files) in Postgres, every measured count independently reproduces.**
- **3.2b** ✅ **MERGED** (PR #24) — embedding service (Ollama client + Neo4j upsert). Doc + section
  level; model-stamped. New rule file `embeddings.yaml` (HR-124..HR-130, all `open`, all
  `our_invention`). Every default **measured** against live endpoint + all 14,522 parsed JDs:
  max_chars 10,000 (measured-truncates-nothing **at 3.2b**; the v2/post-WJQ corpus later falsified
  this — 1,400 docs exceed 10,000 and ~11 exceed the model's token window even truncated. Resolved by
  HR-126/HR-193: keep 10,000 + add a `max_chars_fallback` ladder that rescues the ~11 to a best-effort
  shorter vector. Re-embedded 2026-07-24: **`bad_requests` 11→0, 11 backed off**. See
  `docs/embeddings/max-chars-decision.md`), min_section_chars 40, title_excluded. Deterministic +
  content-keyed + idempotent; runner reconciles/prunes stale vectors. **ADR-003 live-test guard:**
  `make gates` reaches `aria-gb10-2`; CI never will. Live tests opt-in, local-only. **Gates: 1256
  passing, 95.55% coverage.**
  **⚠️ NEW: WJQ parser blocks 3.5, not 3.3/3.4.** 29% of the archive (4,226 files) is SFU's WJQ
  Custom form, not JDFN; 89% of WJQ parse to zero content (34.5% of all 14,522 JDs serialize empty).
  HR numbers unaffected (current-practice cohort has zero broken parses). Embeddings and clustering
  see ~65% of archive until WJQ parser lands. **File WJQ support as a task that BLOCKS 3.5 (clustering)** —
  a cluster report before it would silently cover 65% of the corpus.
- **3.3** ✅ **MERGED** (PR #27) — Tier-2 near-dup: MinHash/LSH candidates over word-5-gram shingles
  → **exact Jaccard** confirm → `DedupEdge(tier=NEAR_DUPLICATE)`. New rule file `dedup.yaml`,
  register entries **HR-131..HR-140**. **Gates: 1368 passing, 94.90% coverage.**

- **Extraction defects FIXED this session** — two silent data losses are resolved:
  - ✅ **`_extract_docx` table + content-control fix** (PR #30, #31): reads only `document.paragraphs`,
    losing all TABLES and Word content controls. Fixed with document-order body walk. **Recovery: 2,596
    files lose >40% → 1; 24 lose everything → 0; ~20.7M characters recovered.** Baseline regenerated
    (#31): **HR cohort byte-identical**; docx fix alone rescued **3,278 files from broken parse**.
  - ✅ **WJQ (CUPE 3338) template parser** (PR #32, #33): segmenter knew only JDFN/APSA template; WJQ
    is ~4,300 files (29.5% of archive). New marker-routed parser (`parser/wjq.py`) reads WJQ's 14-section
    template. Decisions: (1) duty frequency markers → `SFUDuty.frequency`; (2) **WJQ parse-only, excluded
    from approval-bar cohort** (HR-143) — bar is JDFN/APSA only. `PARSER_VERSION v1 → v2`;
    `ParseResult.template ∈ {jdfn,wjq,unknown}`. Register **HR-141..HR-148** (register now **148** entries).
    Baseline regenerated at v2 (#33): **HR cohort BYTE-IDENTICAL**. Template facet: jdfn 10,222 / wjq 4,300 / 43 skipped.
  - **The win:** archive-wide broken parses (parse_confidence < 0.10): **4,984 → 1,706 → 105 (99.3%
    parseable)**. Of 4,300 WJQ, only 43 broken. **Archive now 99.4% covered end-to-end** (parse → embed
    → dedup). Pipeline refreshed: documents with vectors 9,517 → 14,395; section vectors 22,922 → 36,174;
    edges 14,312 → 15,072 (candidate waste removed, no edge loss).
  - **Phase 3.5 clustering is now UNBLOCKED.** Both defects were outside the 874-JD current-practice cohort;
    HR numbers remain unaffected.
  - **Real-archive run:** 14,565 files → 12,593 distinct contents → **112,537 LSH candidates →
    14,312 near-duplicate edges** at `jaccard_min: 0.85`. Edge Jaccard: p10 0.88 · **median 0.966** ·
    p90 1.0. **Position split: same-position 3,980 · cross-position 8,251 · unknown 2,081 — 67.5% of
    near-dup edges span DIFFERENT positions.** Reconcile proven idempotent on the real corpus: a
    second pass wrote 0, updated 0, pruned 0.
  - **Measurement #1 — document cosine cannot do this job; shingle Jaccard can.** Nearest-neighbour
    cosine: median **0.988**, 98% of JDs have a neighbour ≥ 0.92 — a cosine bar confirms *everything*.
    Word-5-gram Jaccard on the same corpus: nearest-neighbour median **0.126**, random-pair median
    **0.0022** (p99.9 = 0.30). **Jaccard drives; `cosine_confirm_min` ships `null` (OFF).**
    **HR-093 (`clone_threshold: 0.92`, unratified) is amended with this measurement — it must be
    re-derived before Tier-3 uses it.**
  - **Measurement #2 — the obvious oracle is worse than no oracle.** "Same `position_id` ⇒ duplicate"
    fails completely: same-position pairs have median Jaccard **0.30**, cross-position LSH candidates
    have median **0.58** — the negatives are MORE similar than the positives. SFU's redundancy is
    cross-position CLONING, not within-position revision (consistent with Tier-1's 77% cross-position
    finding). No honest precision/recall CI gate exists on `fixtures/labels/pairs.csv` (12 near-dup
    positives, a `best_guess_label` column, authored against a census this repo later caught being
    wrong). Instead: a **pinned behavioural fixture** + the adjudication sample
    (`docs/dedup/near-dup-adjudication-sample.csv`, 192 stratified pairs, empty `human_label`), so a
    real label set can finally be built.
  - **Structural decisions carried forward:** Tier-2 edges are NOT additive (a Jaccard edge is only
    true relative to a threshold + shingle config) — the runner **reconciles: insert / update /
    prune**. The EXACT/NEAR ladder is closed **structurally** (candidates are generated over one
    signature per distinct `sha256`), pinned by a 6-member star-group test (a pair-sized test cannot
    catch the "10 of 15 pairs" undercount a naive "skip pairs with an EXACT edge" check would leave).
  - **🔴 NEW FINDING — a third silent extraction defect, blocks 3.5 alongside WJQ.** `_extract_docx`
    reads only `document.paragraphs`, never text inside TABLES or Word content controls
    (`<w:sdtContent>`). Measured over all 9,947 `.docx`: **2,596 files lose >40% of their text, 24
    lose EVERYTHING**, 561 (5.6%) contain a content control, ~20.7M characters never seen by any part
    of the system. **HR numbers are safe** (checked over the 864 `.docx` in the 874-JD current-practice
    cohort: zero lose >40%) — the losses concentrate in the same legacy/other-template population as
    WJQ. Also: 57 documents were `unreadable` to Tier-2 vs 43 in the 2.5 skip ledger — not a bug, the
    extra 14 are the content-control case (extracts to empty text); Tier-2's ledger is honest, the
    extractor is what is wrong. Real fix, big blast radius (moves `text_sha256`, re-parses/re-embeds/
    re-shingles) — safe by design since 3.2b/3.3 are content-keyed and idempotent, but its own
    deliberate task, not a drive-by.
- **3.4a** ✅ **MERGED** (PR #38) — ParsedJD → JobSignals adapter + title normalizer. Wired 2.4c's pure-but-uncalled `similarity`/`clustering`/`drift`. New `jd_core/bank/signals.py`: `build_job_signals(jd) -> JobSignals` (skills = idf-less keyword bag from `{skill,knowledge,ability}` quals minus stopwords — honestly degraded vs an ontology, empty for ~41% of JDs with no quals) + `canonical_title`. Frozen `JobSignals`/`CanonicalTitle` in `models/bank.py`. Two measured drift fixes: **word-number years** (1,116 → 5,573 derivable) and **education from `[education, knowledge]` quals** (JDFN's degree in `knowledge` blob → 1,161 false-positive "bachelors" reduced to 4 FPs). Register **HR-149..HR-154**; ADR-007. Reviewer-approved (Opus); the one defect (all-6-kinds education FP) caught by measuring against the archive.
- **3.4b** ✅ **MERGED** (PR #39) — Tier-3 role-equivalence runner. Writes `DedupEdge(tier=ROLE_EQUIVALENT)` blending doc-vector cosine + idf skill overlap + seniority via 2.4c's `score_job_similarity`. **Two user decisions:** skills = the idf keyword bag (`families={}`, ontology deferred; idf computed in-runner, floored at 0); the over-merge guard = **title-family-band CONFLICT veto** (bands >`max_band_gap`(1) apart never role-equivalent; `employee_group` soft veto both-known-and-differ; `grade` unused). **`role_equiv_threshold = 0.5`** — measured: 99.2% pos / 3.0% neg. **Honest limitations, all registered:** 70% of titles `family=="unmapped"` so band veto is partial (~30%); positives are Tier-2 weak labels (no honest P/R gate — ships pinned fixture + stratified adjudication sample); blended score bimodal (41% empty-skills pairs floor ~0.52). Register **HR-155..HR-160**; `make dedup-role` + compose service. Reviewer-approved (Opus) after one round; **two defects were real crashes on real data that synthetic fixtures hid** — near-identical 768-dim embeddings compute cosine >1.0 (16% of real pairs) → ValidationError; ubiquitous skill's negative idf. Both clamped + pinned with real-magnitude fixtures. **Perf follow-up (HR-159 note):** candidate gen O(bucket²) in 8,215-doc `unmapped` bucket (~1hr whole-archive; completes) — Neo4j vector-index top-k is the follow-up.
  - **Tier-3 archive run: IN PROGRESS.** `make dedup-role` running over full archive now; will write ROLE_EQUIVALENT edges + `docs/dedup/role-equiv-summary.json` + `role-equiv-adjudication-sample.csv` at completion. Edge count TBD (run in progress).
- **3.5** ✅ **MERGED** (PR #42) — Clustering (#7 + constraints NEW). **Report-only, not persistent** (re-cluster reconcile would cascade-delete approved canonicals; report suffices). **Per-tier edge admission, NOT scalar threshold** (🔴 **key landmine**: edge scores incomparable across tiers [EXACT=1.0, NEAR∈[0.85,1.0], ROLE bimodal ∈[0.5,1.0]]; naive 0.80 threshold silently discards every ROLE edge in [0.5,0.80)). **Synthesize EXACT connectivity in-runner from sha256** (Tier-2 structurally excludes byte-identical pairs). **Two-stage over-merge guard:** edge admissibility (reuse 3.4b band/group veto) pre-union-find + post-union-find band-spread/group-mix/oversize **cohesion cap that FLAGS (not auto-splits)** for HR eyeball pass. Register **HR-161..HR-166** (cluster_tiers, cluster_role_equiv_min, cluster_max_band_spread, cluster_group_homogeneous, cluster_max_size, cluster_representative_policy) all measured post-run. Reviewer-approved (Opus): the three safety properties (no-Cluster-write/no-commit, the blob guard, EXACT synthesis) verified by mutation against the real 150,879-edge DB. Tests **1518 / 94.02%**.

**Exit: MET.** Duplicate + cluster reports over the full archive; metrics delivered:
- Tier-1 exact: 1,037 groups, 1,972 redundant files, 798 groups (77%) cross-position
- Tier-2 near-dup: 15,072 edges, 67.5% cross-position, reconcile idempotent
- Tier-3 role-equiv: 133,842 edges at 0.75 threshold (measured knee of bimodal score distribution)
- Clusters: 2,458 clusters (largest 132), 75.1% coverage, 3,620 singletons, 9 flagged, 47,113 edges admitted
- Honest quality limit identified + documented: WJQ `.doc` artifacts over-cluster on template (Phase-4 follow-up)

### Phase 4 — Harmonization & review
**4.1–4.4 COMPLETE.** The full pipeline exists end to end — merge → rewrite → audit → change-log →
review queue (producer → service → routes → UI). **REPRIORITIZED (2026-07-20, user):** the codebase
is substantial but its only visible surface is the transport-only review queue — everything else
(baseline, dedup, clusters, harmonization diffs) exists only as DB rows and "gates pass" claims. So
**Phase 4.6 (Visibility & local-only assurance) was sequenced AHEAD of the 4.5 human pilot and is now
COMPLETE (shipped 2026-07-21)** — the work had to be *seen* and *proven local* before a real HR
reviewer is asked to trust it. **4.5 (the human pilot) is now the next milestone.**
- **4.1** ✅ **MERGED + calibrated** (PR #46). Deterministic merge engine (`bank/merge.py`): section
  selection, duty union/dedup/reorder, KSA rebuild — pure, no LLM, drafts only. 9 knobs in registered/
  unhashed `harmonization.yaml` (HR-167..175). Calibrated over 1,801 JDFN clusters via the
  `jd_bank/harmonize/` runner; one default moved (`max_duties` 10→12). **%-rebalance DEFERRED** (its
  own task — allocations are free-text, need extraction + the Part-11.6 gate interaction).
- **4.2** ✅ Rewrite passes (both LLM, self-hosted Ollama, anti-fabrication guards, validator-as-oracle).
  - **4.2a** ✅ **MERGED** (PR #49) — harmonize rewrite (`jd_harmonize_v1`): LLM scaffolding
    (`jd_bank/llm/` `ChatClient` + prompt loader) + `rewrite_merged_role` (grounded 4.1 draft →
    LLM → anti-fabrication scrub → validator → frozen `RewrittenDraft`, drafts only). `rewrite.yaml`
    registered+unhashed, HR-176..184 `open`.
  - **4.2b** ✅ **MERGED** (PR #51) — quality audit (`jd_quality_v1`): nuanced inclusive-language/
    clarity/seniority pass with verbatim-evidence anti-fab scrub; ADVISORY (no score/grade — validator
    stays oracle). `quality.yaml` registered+unhashed, HR-185..190 `open`. `flatten_jd` shared.
- **4.3** ✅ **MERGED** (PR #52). Change-log / per-source diff (`bank/change_log.py`): pure
  `build_harmonization_diff` → frozen `HarmonizationDiff` (rendered draft + per-source contributions +
  removed-content log + flagged duties). Drop-vs-dedup authoritative from the merge's cap-dropped groups.
- **4.4** ✅ Review queue (user-chosen slicing: producer → service → routes → UI).
  - **4.4a** ✅ **MERGED** (PR #53) — canonical-draft PRODUCER (`canonical/runner.py`): JDFN clusters →
    persisted DRAFT `canonical_jds`. Idempotent, no-clobber over human artifacts, append-only audit.
  - **4.4b** ✅ **MERGED** (PR #54) — review SERVICE (`review/service.py`): the human-approval spine.
    list/packet/approve/reject/edit/override; approve PUBLISHES only when the re-validated gate decision
    permits (NN #1, the only publish path); validator-as-oracle on current content; `FOR UPDATE` lock.
  - **4.4c** ✅ **MERGED** (PR #55) — thin FastAPI routes (`api/routes/jd_bank.py`) over the service;
    typed-error→status map; commit discipline pinned.
  - **4.4d** ✅ **MERGED locally** (PR #56 — GitHub Actions billing-blocked at merge, PR open/unmerged).
    Minimal server-rendered UI inside FastAPI (`api/routes/ui.py` + Jinja2 templates): queue → detail
    (draft + 4.3 diff + validation report) → approve/edit/reject/override. Transport only; no new
    dependency (stdlib form parsing). **Reconcile PR #56 + re-run CI once billing is restored.** ⚠️ **SUPERSEDED (2026-08-07): the billing block is
    RESOLVED and there is nothing left to reconcile — no PR below #81 is still open, and CI is
    green on every commit including `main`. Do NOT follow the "merge locally per ADR-006"
    guidance in older notes; use a normal PR + CI.**
  - **4.4a-followup** ✅ **MERGED locally** (PR #57 — GitHub Actions still billing-blocked, PR open/unmerged).
    Split the producer's single injected LLM client into `rewrite_client` (bound to `rules.rewrite.model`) +
    `audit_client` (bound EXPLICITLY to `rules.quality.model`), so the `QualityAudit.model` stamp — always
    taken from the RULES, not the client — stops being a latent NN #6 lie once `quality.yaml` retunes.
    `_build_clients` (both-or-neither) in `canonical/__main__.py`; pure wiring, nothing registered. Two pins
    (routing + binding), both proven RED under their regression. Gates 1734/93.89%; Opus-approved.
    **Reconcile PR #57 + re-run CI once billing is restored.** ⚠️ **SUPERSEDED (2026-08-07): the billing block is
    RESOLVED and there is nothing left to reconcile — no PR below #81 is still open, and CI is
    green on every commit including `main`. Do NOT follow the "merge locally per ADR-006"
    guidance in older notes; use a normal PR + CI.**
- **4.5** — Pilot: 5–10 clusters end to end with a real HR reviewer through the review UI; feedback
  becomes fixtures/rules (NN #7). Where the 4.2/4.3/4.4 provisional `open` defaults meet human judgment.
  **⬅ NEXT — 4.6 is complete AND the queue is now LLM-ENRICHED**: all 379 drafts were refreshed in place
  by a crash-safe ~10h `gpt-oss:120b` run (384 with real rewrite prose, 291 audited, 0 cluster failures),
  so the reviewer sees real prose, not deterministic merges. The dashboards are in place and the local-only
  guarantee is proven (4.6a egress guard).

**Pre-pilot follow-ups (engineering):** ~~split `rewrite_client`/`audit_client`~~ ✅ DONE (PR #57).
~~LLM-enrich the seed~~ ✅ DONE ([PR #58](https://github.com/humanaxiom/jd-assistant/pull/58)) — plus the
**producer crash-safety** (`commit_every`/`progress_every`, `--commit-every`; checkpoints a long run) and
**LLM robustness** it required: constrained decoding (`json_schema`) **scoped to the audit** (fixes a ~24%
enum-mismatch failure) while the **rewrite stays loose** (its large `SFUJobDescription` grammar 500s Ollama —
the live gate caught this pre-merge), and a per-pass `reasoning_effort` knob (**HR-191** rewrite=`null`,
**HR-192** quality=`low`; register 190→192). ~~concurrent double-approve test (4.4b)~~ ✅ DONE
(2026-07-29, mutation-verified integration pin). ~~Deferred product gap: the review-queue edit view is a
raw-JSON `<textarea>` — a structured per-field editor is a later task.~~ ✅ DONE (2026-07-29): the reviewer
edit view is now a full per-field `SFUJobDescription` editor, and the Builder captures duty verb/%-allocation
+ KSA modifiers (both surfaces off raw JSON / lossy textareas). Plus a **draft-vs-last-approved version diff**
(`GET /jd-bank/ui/review/{id}/diff`). Remaining: a **full-archive** enrichment on this improved code; a
`jd_bank/` change-log runner over real clusters (4.3); `get_session`→`api/deps.py` (drops the two routers'
circular-import shim).

**Exit:** first human-approved canonical JDs published; audit trail complete.

### Phase 4.6 — Visibility & local-only assurance — ✅ COMPLETE (shipped 2026-07-21)

**Why now:** we have built a large backend whose only evidence of working is "gates pass" — and the
proprietary archive's content must be provably local. This phase makes the pipeline's output *visible*
in a browser and makes the no-cloud-egress invariant *executable* rather than a claim. **Guardrails
the user set: NO service-plan change, NO major rewrites.** Extend the server-rendered Jinja UI that
already lives inside the FastAPI `api` service and runs under `make gates` (mypy --strict + coverage +
TestClient) — the deliberate 4.4d choice. All new UI pages are **read-only** over data the pipeline
already produced; the review queue stays the only mutation surface (the 4.4b service remains the sole
authority, NN #1). Everything content-analyzing stays on internal infra we control (NN #5 / ADR-003).

- **4.6a — Local-only egress guard (do FIRST; it is the trust foundation).** Turn NN #5 from prose
  into an executable, adversarially-pinned check. A single allowlist of permitted inference hosts
  (config, registered `open`) that **both** content network clients (`llm/client.py`,
  `embeddings/client.py`) resolve their `base_url` against at construction — a base_url whose host is
  not on the allowlist raises before any content is sent, and `make gates` fails if any client is
  wired to a non-allowlisted host. Pin BOTH directions (internal host → allowed; a cloud host like
  `api.openai.com` → rejected, test goes red if the guard is removed). Ship a short evidence artifact
  (`docs/security/egress-audit.md`) enumerating every content network sink and where it points.
  **Interpretation RATIFIED (2026-07-20, user):** "local" = *not cloud/third-party* — content may
  cross the private network to internal infra we control (`aria-gb10-2`), consistent with NN #5 /
  ADR-003. *Never leaves the dev box* was considered and **declined** (would move Ollama onto the dev
  box, an ADR-003 amendment). So the allowlist permits internal hosts and REJECTS any public/cloud
  host; register the allowlist as `open`, the interpretation as decided.
- **4.6b — Seed real data + live review queue.** Run `make dedup-role` → `make canonical` over the
  real archive so genuine DRAFT `canonical_jds` populate the queue, and drive the existing UI
  (`/jd-bank/ui/queue` → detail → approve/edit/reject) end to end against real drafts. Deliverable:
  the human-approval spine demonstrably working on real content, not fixtures. (This is also the 4.5
  pilot's prerequisite.)
- **4.6c — Read-only pipeline dashboards.** New Jinja pages under the same `api` service, each a thin
  read over data already in Postgres/Neo4j/the committed report artifacts — no new pipeline logic:
  (1) **Archive baseline** (parse rate, era bands, current-practice cohort, approval/score/grade
  distribution — from `docs/baseline/`); (2) **Dedup** (Tier-1 exact groups, Tier-2 near-dup, Tier-3
  role-equivalent — counts + drill-in to a group's members); (3) **Clusters** (the 2,458 role clusters,
  the 9 flagged, coverage); (4) **Harmonization diff** per cluster (reuse the 4.3 `HarmonizationDiff`
  the review detail already renders). Autoescape on; no `|safe` on archive text (untrusted). Sliced as
  separate tasks (baseline → dedup → clusters) so each is one session and lands independently.
- **4.6d — Remove the dead Flask `frontend` compose service. — DONE.** It ran the abandoned pre-4.4d
  harness scaffold dashboard (`core/frontend/`, a tasks/runs Flask app superseded by the FastAPI
  `/jd-bank/ui`) and published host port 25500 for nothing. Removed the compose service + its env/port,
  deleted the dead `core/frontend/` package, and scrubbed README/DEVELOPER_GUIDE references. Compose file
  is honest again.

**Exit:** a reviewer can open a browser and see the archive analysis, the dedup/cluster findings, and
real canonical drafts moving through approve/reject — and the no-cloud-egress invariant fails the build
if violated, rather than resting on a code read.

### Phase 5 — JD Builder (forward-looking JD Composer) — ✅ COMPLETE (2026-07-28)

> **Status:** all of Phase 5 shipped (5.1 live compliance · 5.2 answers/assemble · 5.3 guided UI ·
> 5.4 search/clone · 5.5 LLM assist · 5.6 submit-to-queue · 5.7 `.docx` export), the guided form
> wires every route (5.8a/b/c), the compliance panel explains each section and links findings to
> their fields, and correctness fixes landed (Relationships-header insertion; clone defaults
> boilerplate ON). **Also since shipped:** **5.9**, the near-duplicate authoring guard (2026-08-05,
> below), the four search fixes of 2026-08-03/04 (`89d0c74`/`3b6a71b`/`d71e333`/`46a9443`), and an
> **auth/RBAC layer (ADR-008)** — CAS SSO, sessions,
> author/reviewer/admin roles, the UI gate, user-management admin, authenticated actor on every
> review/compose action, and a tamper-evident hash-chained audit. **What's next is in
> [`ROADMAP.md`](ROADMAP.md)**, not here — the critical path is the 4.5 HR pilot + HR ratification.

**The project's first forward-looking, user-facing product**: everything to date analyses the
*existing* archive; the Builder helps a hiring manager/recruiter **author a new SFU-compliant JD**
with live compliance feedback, routed into the same human-approval review queue. **Detailed,
session-sized, TDD task breakdown: `docs/tasks/phase-5-jd-builder.md`.** Slots as a **parallel
track to the 4.5 HR pilot** (independent engineering; they meet at the review queue) and the **MVP
needs no GPU** (compliance = the deterministic `evaluate_jd_rules`; LLM-assist is optional and
mock-testable). Scope = **JDFN (APSA/APEX/POLY) template** — the validator defines a bar only there
(HR-143). Reuses the validator (NN #3), the review service as sole publish authority (NN #1), and
the build-enforced egress guard (NN #5); extends the server-rendered `/jd-bank/ui`, no new service
plan.

- **5.1** Live-compliance service + `POST /jd-bank/compose/validate` — `SFUJobDescription` →
  `evaluate_jd_rules`/`build_report`, with a draft-mode split (incomplete=guidance vs
  non-compliant=finding). *The core; do first.*
- **5.2** Guided-authoring question set as rules-as-data (`composer_questions.yaml` from
  `jd-authoring-guide.docx`) + deterministic `assemble_jd(answers) -> SFUJobDescription`.
- **5.3** Builder UI (server-rendered Jinja, dependency-free POST-re-render) — guided form + live
  compliance panel.
- **5.4** Search + "start from an existing JD" — **new Neo4j vector query** (the missing read side
  of 3.2b) + Postgres facets + clone-to-draft.
- **5.5** LLM authoring assist (optional, guard-permitted, decision-support) — reuse the 4.2
  `ChatClient`/prompts + anti-fab guard; asserts validator post-state, never model text.
- **5.6** Composed draft → review queue (DRAFT `canonical_jds`, provenance `composed`); the 4.4b
  service stays the sole publish path.
- **5.7** `jd_export`: port `bank/export.py` (#13) + SFU-template styling (TNR-10, footer) +
  snapshot tests. Footer wording = the Phase-6 sign-off flag.
- **5.9** **Near-duplicate authoring guard — ✅ SHIPPED (2026-08-05)**, `jd_bank/composer/duplicates.py`.
  *(Numbered 5.9 to match the code, which already carries that tag; 5.8a/b/c were the guided-form
  wiring. The role-vector index it reads is tagged 5.4b in migration `003`.)* While an author
  composes, show which existing harmonized roles look like the same role, so they clone one instead
  of authoring SFU's 10th "Academic Advisor". **Advisory only** (NN #1) — nothing blocks, nothing
  publishes, the validator remains the sole oracle.
  **It carries no similarity score, and that is the finding, not an omission.** Measured over the
  live 1,797-vector role index *before* the module was specified: same-title role pairs (genuine
  twins, n=2,618) median cosine **0.9335**, while a role's nearest **unrelated** neighbour (n=200)
  medians **0.9604** — *an unrelated role scores higher than a real twin*. So **a threshold cannot
  work on this corpus**: at 0.90 the guard fires on **99.2%** of drafts at **22%** precision, at
  0.97 it still fires on 24% and loses most true duplicates, and a top1-vs-top2 margin rule fails
  identically. **Ranking is good** (a same-title sibling is top-5 for **76%** of roles, top-10 for
  84%), so the panel is a **ranked list plus one honest non-vector fact** — *"SFU already has 9
  roles titled 'Academic Advisor', across 6 departments"* is true and needs no vector; *"your draft
  is 94% similar"* is not. `RelatedRole` has no score field and a test pins that absence.
  **Two independent passes:** a Postgres **title-collision** pass (no GPU, always runs, JDFN-scoped,
  ARCHIVED excluded) and a **semantic** pass that serializes the draft with the *same*
  `serialize_document` the role vectors used and degrades to empty on any failure — Ollama down, the
  role index not built — so the Builder never loses its compliance panel to a wedged GPU. An
  empty/whitespace serialization is refused **unconditionally and first** (Ollama embeds `""` into a
  constant vector that is a plausible nearest neighbour to everything — measured: every empty query
  returned the identical role at exactly 0.8038), separately from the length floor.
  **Register:** `dedup.authoring_guard` — **HR-195** `max_matches` (5), **HR-196** `min_draft_chars`
  (500), **HR-197** `timeout_seconds` (5.0), all `open`.

**MVP (user-decided 2026-07-22) = {5.1+5.2+5.3 guided builder} → 5.5 LLM-assist → 5.6 review queue**
(full guided author → live-validate → assist → submit). Search corpus = cluster reps + published
canonicals. LLM-assist is mock-tested under gates; its live sign-off waits for the GPU (held by the
full-archive run). 5.4 (search/clone) and 5.7 (export) layer on. *(Corrected 2026-08-05: the
shipped **search corpus** is the embedded **archive documents** plus **every current-version
harmonized role**, drafts included — not "cluster reps + published canonicals". Published-only
would be 4 roles; see 8.2.)*

**Exit:** recruiter/hiring-manager can find, compose, validate live, and export a JD; drafts land
in review.

### Phase 6 — Hardening & handover — **substantially delivered out of order, by Phase 9**
Auth, rate/size limits, backup + reindex runbooks, ops docs, and the
**territorial-acknowledgement wording verification** sign-off before any external distribution.

> **Most of this arrived early and under different names** (see Phase 9): auth is ADR-008 +
> P0.1a; the production posture, secrets and deployment file are P0.2/P0.4; the one "rate
> limit" the review actually found necessary is `/ready`'s single-flight bound (P0.1b-ii).
> ~~**Still owed from this phase:** backup + reindex runbooks~~ ✅ **DONE (2026-08-13)** —
> `docs/runbooks/backup-and-restore.md` + `docs/runbooks/reindex.md`, linked from the
> operator guide. **Every step was executed against the live stack before it was written
> down**, which is the only reason they are worth anything: an unrun runbook is a guess.
> **The remaining Phase 6 item is the territorial-acknowledgement sign-off, which blocks
> external distribution and is HR's, not ours.**

**✅ 6.1 — Backup + reindex runbooks. DONE (2026-08-13).**

- **The architectural finding that makes the backup small: only Postgres must be backed up.**
  Neo4j is a **derived index** — `make embed` rebuilds documents + sections from
  `parsed_jds`, `make embed-roles` rebuilds roles from `canonical_jds`. Measured: the
  harness agent-memory labels (`Agent`/`Artifact`/`Task`/`Subtask`) that are *not* derivable
  hold **0 nodes**, so nothing is at risk today — stated with the check that falsifies it if
  that ever changes.
- **🔴 THE TRAP, MEASURED ON A REAL DUMP: `pg_restore --data-only` into an already-migrated
  database silently destroys the data and exits `0`.** 1,804 canonical JDs → **0**, 12 user
  roles → **0**, 1,810 chained audit rows → **0**, `warning: errors ignored on restore: 7`,
  **exit code 0**, and the resulting database starts and accepts logins. An operator
  checking the exit code and signing in would conclude the restore worked. **Same class as
  reading a pipeline's exit status instead of its output.** The blessed path (full
  custom-format dump into an EMPTY database) was verified to restore the audit chain
  **byte-identical** — 1,810 rows, same `d8899dc8…` fingerprint, same tail hash.
- **Why the blessed path survives, because the mechanism is load-bearing:** the chain is
  maintained by a `BEFORE INSERT` trigger that overwrites `prev_hash`/`row_hash`
  unconditionally, and `pg_restore` loads table data **before** creating triggers. That
  ordering is a property of the custom format — which is why the runbook insists on `-Fc`
  rather than treating it as a preference.
- **Reindex resume proven, not asserted:** skip-first on `(text_sha256, model, embed_stamp)`
  makes an unchanged re-run cost **`embed calls: 0`** (measured), so an interrupted reindex
  is resumed by running it again.
- **A side effect found by running it: `make embed EMBED_ARGS="--limit N"` overwrites the
  COMMITTED `docs/embeddings/summary.json`**, rewriting `documents_seen` from 14,522 to the
  spot-check size. Recorded in the runbook with the `git checkout --` that undoes it.
- **One gap stated rather than guessed:** the wall-clock of a full *cold* rebuild is not
  measured, because every run available to measure was a skip-first no-op. The runbook says
  so and asks for the number the first time a real rebuild happens.

### Phase 7 — Optional / later
Neo4j **domain** role-duty overlap graph (org-design queries — the only deferred Neo4j piece);
Hay-readiness summaries (port `bank/hay_signals.py`, #9, is cheap); transposer-as-a-service for
old-template uploads; M365/SharePoint surfacing.

**Hay-readiness summaries are the ceiling here, and that is deliberate.** A summary says *which
factors a JD gives an evaluator something to read on*. It does **not** produce a factor-by-factor
point breakdown or a grade: the point charts are proprietary Hay/WTW material, SFU publishes none,
and classification is a human Compensation decision — which is why `HayGrade` and
`HaySignals.{grade, grade_mapped}` are **unrepresentable** in `models/bank.py` rather than merely
unused (ADR-007). Proposals to add "clearly labelled advisory" Hay scoring recur; a label is not a
control, and the answer is recorded in ROADMAP §Explicitly OUT.

**Re-evaluation request lifecycle (JDQ/JAQ) — scoped 2026-08-13.** SFU's published process is a
lifecycle, not a form: intake → reason/evidence → review → decision record → resolution. **Three
of those five stages already exist** — `review.edit()` demands a written reason and mints a new
version, `/jd-bank/ui/review/{id}/diff` renders before-vs-after, and `audit_log` is append-only and
hash-chained. What is missing is a **request object with a status** hanging off the existing review
queue; a second decision store beside the audit chain would be the defect, not the feature. JDFN
only until HR-194. Detail in ROADMAP §3 and
[`docs/decisions/copilot-sfu-gap-triage-2026-08-13.md`](decisions/copilot-sfu-gap-triage-2026-08-13.md).

**A compensation requisition / pay-transaction workflow is OUT of remit** — the HRIS is the system
of record for a pay transaction and JD Bank sits upstream of it. The seam is the planned HRIS
export of an approved canonical (HR-blocked on grade scales + FIPPA), not a requisition store here.

**CUPE / WJQ authoring — the biggest deferred scope question (HR-194, `open`).**

> **⚠ FIRST, THE THING THAT CONFUSES EVERY READER: why is CUPE singled out at all, when
> APSA is the same size?** (4,946 APSA vs 4,440 CUPE — comparable.) **It is not that CUPE is
> unusual. It is that CUPE uses a DIFFERENT FORM and we only ever built for the other one.**
>
> | | Form | Built for it? |
> |---|---|---|
> | APSA · APEX · POLY | the **JDFN** template | ✅ validator, 14 gates, thresholds, Builder |
> | CUPE 3338 | the **WJQ** — a 14-section point-factor questionnaire | ❌ a parser (Phase 3.4), and nothing since |
>
> Every "CUPE problem" is a consequence of that one fact, not a property of CUPE:
> the `additional_context` truncation only bit CUPE because that field is where the WJQ's
> seven point-factor sections land (for a JDFN JD it is nearly empty, so a 4,000-char cap
> never mattered); the four rules firing on 100% of CUPE fire because the WJQ form does not
> contain the sections they check. **JDFN-shaped tooling meeting a non-JDFN document.**
> So the honest one-liner is not "CUPE is a special concern" but **"CUPE got a parser and
> then stopped getting attention."**

The Builder and approval bar are JDFN-only (APSA/APEX/POLY). CUPE is ~29.5% of the archive (~4,300 WJQ-instrument
files) and is deliberately **not served** because there is no ratified CUPE quality bar — the
validator can only score the JDFN template, so authoring a CUPE JD would category-error-mis-score
it on the JDFN gates (HR-143). **Serving CUPE is a real project and it starts with HR, not code:**
define a CUPE quality bar (a WJQ ruleset + oracle) FIRST; only then does `segmentation.yaml ::
jdfn_employee_groups` gain a `cupe` token and the Builder support the WJQ 14-section instrument.

**MEASURED + DESIGNED 2026-08-14** — evidence in
[`docs/decisions/cupe-scope-measured-2026-08-14.md`](decisions/cupe-scope-measured-2026-08-14.md),
design in [`docs/tasks/cupe-support-design.md`](tasks/cupe-support-design.md). Three things the
prose above understated:
1. **Far more is already built than "not served" implies.** Parsing works (all 14 WJQ sections,
   since 3.4) and CUPE parses *richer* than JDFN — 9.7 duties vs 3.8, 19.5 quals vs 1.0 — and
   Tier-2/3 dedup is **done**: **49,448** role-equivalent edges, *more* than APSA's 49,008. What
   is missing is the bar, not the pipeline.
2. **🔴 A blocking defect that is OURS, not HR's: `additional_context` is capped at 4,000 chars
   and 81.4% of CUPE JDs sit at the cap** (0% of APSA). The seven WJQ point-factor sections are
   stored there verbatim, so the tail is silently truncated — `continuing_education`, the last
   one, survives in only **17.0%** of documents. **No bar can be designed over data that is
   discarded for four in five documents.** Fixing it needs a `parser_version` bump + full
   re-parse shipped together (#101 precedent).
3. **The category error is architectural, not incidental:** `evaluate_jd_rules` is
   **template-blind** — every rule runs over every JD. The fix is rulebook data, an
   `applies_to` on each catalog rule with no default (the P1.3 `tier` move), which is worth
   landing **even if HR rules against serving CUPE**.

**Phases: ~~A (fix the truncation)~~ ✅ · ~~B (`applies_to`)~~ ✅ both DONE 2026-08-14 ·
C (calibrate the WJQ bar) ⟵ NEXT · D (turn on harmonize/cluster for CUPE) · E (Builder
token).**

> **⚠️ AND THE HR-194 FRAMING WAS WRONG — CORRECTED 2026-08-14, because it changes the
> sequencing.** This plan said a CUPE bar must wait for HR to define one. **Measured: the
> JDFN bar is itself entirely unratified.** All **201** register entries are `open`; the
> approval bar that gates real publishes today is `our_invention` — `HR-001` score floor
> 60.0, `HR-002` grade floor `C`, `HR-004`'s 14 blocking rules, none of them signed by SFU.
>
> **So holding CUPE to "wait for HR" while shipping an unratified JDFN bar was never a
> consistent position.** The correct standard is the one APSA already got: **build the WJQ
> bar the same way — measured over the corpus, every value registered `open`, nothing
> auto-publishing, HR free to change any of it.** That is not going past the approval bar;
> it is applying the same discipline twice.
>
> What HR-194 still genuinely decides is **scope** — whether the Builder should *author*
> CUPE (Phase E) — not whether a measured bar may exist.

**✅ PHASE B — `applies_to`, SHIPPED 2026-08-14** (PR
[#110](https://github.com/humanaxiom/jd-assistant/pull/110)). Every rule in
`rule_catalog.yaml` now declares which template it can judge, **required with no default**
(the P1.3 `tier` move), and `evaluate_jd_rules` filters on it — inside the *existing*
central filter, whose comment already stated the principle: *a finding present on every
approvable JD is not a quality signal, it is a constant.* `applies_to` is that principle one
axis over.

**SEVEN rules are withheld from the WJQ**, and the test is *does the form carry what the
rule reads* — **not** *was the rule noisy*. ⚠ Those are not the same question and an early
draft of this work conflated them: the four rules that genuinely fire on **100%** of CUPE
are `-TERRITORIAL` · `-REL-HEADER` · `-EDI` · `-PROBLEM`, two of which sit under HR-201, so
that set and the withheld set are **different**. The clearest counter-example is
`SFU-GATE-DUTY-PCT`, which fires on **0.0%** of CUPE and is still correctly JDFN-only:
it needs ≥2 `(NN%)` allocations before it can evaluate and the WJQ asks for `(D)/(W)/(M)/(S)`
frequency markers instead, so the form gives it nothing to read. No scope changed when this
was caught — only the stated reason, **and a wrong reason on a rulebook pin is what the next
person builds on.**

**Measured same-document, toggling only the filter:**

| cohort | before | after |
|---|---|---|
| **JDFN** | mean 73.0 · 14.8% approvable | **73.0 · 14.8% — identical** |
| **CUPE** | mean 51.4 · 0.0% | **62.9 · 0.2%** |

**JDFN being untouched is the important half** — a filter that silenced rules everywhere
would have looked like success on the CUPE number alone. CUPE gains **+11.5 points** purely
by no longer being marked down for sections its form never asks for.

> **🔴 AND THE SENTENCE THAT USED TO END THIS PARAGRAPH WAS FALSE.** It read *"It is still
> ~0% approvable because the thresholds remain JDFN-calibrated, which is exactly Phase C."*
> That came from a 600-row spike over `parsed_jds` reporting 0.2%. **Measured over all
> 14,565 archive files via `make baseline`: WJQ went 0.0% → 59.0% approvable** (mean 51.8 →
> 63.2) while **JDFN held at exactly 6.7%**. The spike was wrong by ~300×, and Phase C had
> been scoped on top of it. Full evidence, including the Phase A confound this does not
> claim to have isolated: `docs/decisions/cupe-phase-b-measured-2026-08-14.md`.

**⚠ A methodology catch worth keeping:** the first before/after compared *different
documents* — `ORDER BY id` over v4 rows selects a different 600 than over v3 rows, because
each parse row carries its own UUID — and appeared to show JDFN improving too. That was
sampling noise. The table above toggles only `template_of`.

**🔴 Three of the seven JDFN-only rules are a POLICY call, not a fact — HR-201,
`hr_policy`, `open`.** `SFU-COMP-ABOUT` / `-TERRITORIAL` / `-EDI` check SFU-wide
commitments, not JDFN furniture; one could argue every SFU JD should carry them whatever
form it was written on. But the WJQ contains no such block, so applying them marks down all
4,440 CUPE JDs for a property of the *form*, while not applying them holds CUPE to a weaker
inclusion standard than APSA. Defaulted to JDFN-only and registered, with the view recorded
that **if HR rules the boilerplate is universal the honest fix is the FORM** — ask SFU to
add the block to the WJQ — not a rule every CUPE JD fails by construction.

**🔴 The set was briefly eight, and the eighth did not survive the phase's own test.**
`SFU-AUTH-TITLE-EXEC-DIR` was declared JDFN-only while neither measured nor registered.
`applies_to` states a fact about the **form**, and the WJQ has a job title — so the
justification that carries the other seven does not reach this one. It is also a *second*
employee-group filter on a rule that already carries its own
(`reserved_for_employee_group: apex`), and it disabled the one restricted-title check that
can fire on exactly the group it would catch; its two siblings were already `[jdfn, wjq]`.
Corrected, and **measuring it found a matcher defect worth more than the scope question**:
JDFN-only would have suppressed 5 live CUPE findings, 3 of them the substring near-miss
*"Assistant/Secretary **to the** Executive Director"* and 2 genuine hits that most likely
indicate a mis-parsed `employee_group`. Recorded on **HR-031** rather than fixed, because a
head-noun check changes what the rule catches. **A defect that is not template-shaped must
not be hidden behind a template scope.**

---

## ⚠️ 2026-08-14 — STEP BACK. The measuring is done. Build.

**The last six days found real defects, and then kept looking.** Phase B alone ran three
rounds of *check the claim behind the claim* — each found something true, none of it shipped
a capability. Name the failure mode and stop: **we began arguing about whether a bar was
philosophically correct instead of making the bar data and moving on.**

**The rule from here: measure ONCE to set a default, register it `open`, build.** If a
number is wrong, HR changes a YAML value — that is what the register has been for since
Phase 0. A default swappable in one line does not deserve a week of argument.

**Corollary: do not re-open a settled decision to re-justify it.** The 59%-vs-6.7%
inversion is recorded (`docs/decisions/cupe-phase-b-measured-2026-08-14.md`) and HR-201
carries its consequence. That is sufficient. **It does not block C, D or E.**

### The direction, in one sentence

**Two groups, two straightforward rule profiles, every measure configuration-driven so HR
can swap it — then build JDs for both groups and evaluate each against its own profile.**

### ✅ Phase C — SHIPPED 2026-08-14 ([#112](https://github.com/humanaxiom/jd-assistant/pull/112))

`thresholds.yaml` carries a `wjq:` block; `Rules.thresholds_for(template)` resolves it;
`evaluate_jd_rules` swaps the profile into a local copy of the rules so the trigger and
the finding's **copy** cannot disagree. `make gates` **2,737 passed, 94.06%**;
`rules_version` → **`+76baba29cfeb`**; register **205**, all `open`.

| knob | JDFN | WJQ | |
|---|---|---|---|
| `duties_max` | 5 | **12** | HR-202 |
| `duties_min` | 3 | 3 | HR-203 |
| `summary_max_words` | 150 | 150 | HR-204 |
| `summary_min_words` | 100 | 100 | HR-205 |

**Two things this phase settled that the plan below had only guessed at:**

1. **`gates.yaml` needed no per-template block.** Its gates key on `rule_ids`, and
   `applies_to` already withholds those rules from the WJQ — a gate whose rules cannot
   fire cannot block. Adding one would have been a second control on the same axis: the
   `SFU-AUTH-TITLE-EXEC-DIR` mistake again. **The plan said "thresholds and gates"; only
   thresholds was needed.**
2. **The three WJQ values equal to their JDFN twins are registered, not inherited** — a
   value that is the same by *decision* and one that is the same by *omission* look
   identical in YAML, and the omission is what the phase exists to end.

⚠ **HR-204 records a framing this plan itself carried and the corpus contradicts** — see
the table below: the summary band is skewed toward **under**-run, so the "raise the
ceiling" reading was backwards. Held at 150, registered for HR.

### Phase C as designed — per-template rule PROFILES (the `applies_to` move, one level down)

`applies_to` made *which rules apply* per-template data. Do exactly the same for *the
numbers*, adding **no new concepts**:

- `thresholds.yaml` and `gates.yaml` gain a per-template block (`jdfn:` / `wjq:`), resolved
  by the **`template_of` that already exists** — no new detection, no new plumbing.
- Defaults measured **once** per cohort, every value registered `open` with its `tier`.
- A template with no override inherits the shared default, so **nothing silently changes
  for JDFN** — the same property that made Phase B safe.

That is the whole of Phase C: a loader change, a YAML block, and a table of measured
defaults. Not a research project.

**Use the numbers already in hand — do not re-derive them.** All measured over the full
archive at `jd_segmenter_v4`; each becomes a `wjq:` default, registered `open`:

| knob | JDFN today | WJQ default to ship | why |
|---|---|---|---|
| `duties_max` | 5 | **12** | the WJQ form has 12 duty slots; 77.4% of CUPE JDs use exactly 12 (bimodal — the 9.7 mean describes no document) |
| `summary_min_words` | 100 | measure once | 39.9% of CUPE summaries are under 100 words; the band is skewed **opposite** to the old "168-word average" framing |
| `summary_max_words` | 150 | measure once | only 15.1% exceed 300 (max 671); the 168 mean is that tail pulling |
| qualification conventions | JDFN | WJQ-specific | `SFU-QUAL-SKILL-MODIFIER` 76.1% vs 5.1%; `SFU-AUTH-ABILITIES-OBSERVABLE` 32.2% vs 0.4% |

⚠ **Two traps, recorded so they are not walked into again:** the 16.2% of CUPE JDs parsing
to **zero** duties is a *parser* question and must not become a quality bar before it is
understood; and JDFN parses a **median of 1** qualification against WJQ's 21 — the JDFN
block landing as one blob — so any qualification-count threshold taken from JDFN would be
calibrated on a parser artifact.

### Phase D — harmonize + cluster CUPE, then evaluate per group ⟵ **NEXT**

The pipeline is **already done** for CUPE: 49,448 role-equivalent edges, *more* than APSA's
49,008 (Phase 3 measured). Turn it on, produce CUPE drafts, and evaluate each group against
its own profile. **Evaluation is per group from here — never blended**; a blended approval
rate over two forms is the category error this whole phase removed.

### ⚠ 2026-08-19 — PHASES B–E ARE BUILT AND UNDER REVIEW. TWO P0s.

**`docs/tasks/cupe-review-findings-2026-08-19.md` supersedes the optimism below.** Six
adversarial reviewers went over the whole CUPE diff — the work shipped in one weekend,
orchestrator-only, with no second reviewer. ~30 findings, two P0:

* **A CUPE author cannot submit or export.** The hidden `form` field is in the check form
  only; Submit and Export are separate `<form>` elements and fall back to JDFN. The
  author's content is wiped. The Phase E journey ends at an error box.
* **An inverted test certifies live data loss** — it asserts the dropped text *stays*
  dropped, and would go red if the bug were fixed.

Then: an author can pick their own approval bar; the rewrite can delete most of a role
while the change-log reports nothing removed; it can invent education/experience bars;
`SFUDuty.frequency` is destroyed on every CUPE draft.

**⚠ AND THE CONTROL CLAIM IN THIS PLAN IS FALSE.** "JDFN is the untouched control" is
asserted throughout Phases B–E. `_SECTIONS_NEVER_INVENTED` fires on **both** forms, so every
JDFN rewritten draft since Phase D carries findings it did not before. Re-measure before
quoting any JDFN number from this document.

**The producer run is STOPPED**, 237 of ~649 CUPE drafts rebuilt. Do not restart before the
content-loss fixes land.

**The durable lesson, and it is not about CUPE.** Four of this weekend's defects were found
by running things against the live Bank; the rest by reviewers reading code. **None was
caught by `make gates`, which was green throughout.** The repo already says every claim
about the archive must be checked against the archive — the corollary is that *a pipeline
change is a claim about the archive*, and *a green suite is a claim about the tests*.

### Phase E — the routing seam, MEASURED 2026-08-17 (and the answer is neither option)

A CUPE JD is a **different form**, not a variant: 14 WJQ sections against the JDFN's. Making
one builder emit both means every template, prompt, gate and export grows a conditional, and
every future change pays that tax twice.

**A separate WJQ builder over the same services** (search, assemble, validate, review,
export) is likely *less* code and makes "which form am I authoring?" a **routing** decision
made once, rather than a per-field one made everywhere. The shared half is already built and
template-agnostic. Decide it by trying the routing seam first, not by debating it.

> **✅ THE SEAM WAS TRIED — and the framing above is wrong in a useful way.** Full evidence:
> `docs/decisions/cupe-phase-e-routing-seam-2026-08-17.md`.
>
> **~84% of the composer is already form-blind.** Of 2,204 lines, `duplicates.py` (451),
> `persist.py` (152), `assist.py` (135), `drafts.py` (110), `questions.py` (94) and
> `models.py` (85) hold **zero** JDFN-shaped references. The whole divergence is
> **`answers.py`, `assemble.py`, one function in `search.py` (`_answers_from_jd`), one in
> `validate.py` (`_section_present`), the question-set YAML, and three declarative maps in
> `compose_ui.py`.**
>
> **So the difference between the forms is DECLARATIONS, not BEHAVIOUR** — and that makes
> both options in the paragraph above wrong. Conditionals would scatter one fact across
> seven places; two separate builders would duplicate the *wiring* of 1,500 lines that
> already do not care which form they hold. What the seam wants is a **form spec selected
> once** — the same shape `applies_to` (B) and `thresholds_for` (C) already give the rules
> and the numbers.
>
> **It holds structurally because everything downstream of assembly speaks
> `SFUJobDescription`.** A WJQ assembler returning one — `employee_group="cupe"`, the
> point-factor blocks in `additional_context` where the WJQ *parser* already puts them —
> needs no change to search, dedup, validation, review or export. Validation is correct for
> free: `evaluate_jd_rules` reads `template_of` and applies the WJQ profile.
>
> ⚠ **The one thing to settle FIRST: the WJQ's 14 sections do not map onto `SFUSection`.**
> Ten have no JDFN counterpart, and `SFUSection` is what `Question.section`, the rule
> catalog and 8.3c's `_SECTION_ANCHORS` completeness pin all key on. Extending it is a
> rulebook change with a register entry — decide it before the WJQ question set is written,
> not after.

Until HR rules on HR-194, "the Bank does not *author* CUPE" remains an explicit decision on
the register, not one made by omission — but **C and D need no HR ruling at all.**

**✅ PHASE A — SHIPPED AND VERIFIED OVER ALL 14,522 DOCUMENTS (2026-08-14).**
`additional_context` had inherited `position_summary`'s 4,000-character ceiling through a
shared `_MAX_SUMMARY` constant, and the WJQ parser's own docstring called the result
"verbatim — lossless" while cutting it. Now `segmentation.additional_context_max_chars`
(**HR-200**, `hr_informed`, `open`), `PARSER_VERSION` → **`jd_segmenter_v4`**, and the whole
archive re-parsed:

| | v3 | v4 |
|---|---|---|
| `continuing_education` present in CUPE JDs | **17.0%** | **85.8%** |
| `working_conditions` present | 79.0% | 95.3% |
| CUPE JDs truncated | **3,613 (81.4%)** | **0** |
| avg context chars | 3,738 | 5,272 (corpus max 13,379 < cap 16,000) |

**⚠ AND THE CAP WAS STILL WRONG AFTER THE FIRST MEASUREMENT — the lesson is about
sampling, and it is the durable part.** 12,000 was chosen from a 149-document sample whose
maximum was 9,916. Re-parsing all 14,522 files then put **two** documents at exactly the
cap; their true length is **13,379**. The sample **understated the corpus maximum by 35%**
while predicting the corpus **mean within 2%** (5,379 vs 5,272). *A sample is a good
estimator of the middle and a poor one of the tail — and a cap lives entirely in the tail.*
Raised to 16,000 against the whole-corpus maximum; zero documents truncated.

**⚠ Operational note worth carrying: bumping `PARSER_VERSION` changed what the RUNNING api
reported before anything had been re-parsed**, because the dev container bind-mounts the
repo with `--reload`. Batch consumers filter on the literal, so they briefly read zero rows;
user-facing pages were unaffected (they read the latest parse regardless of version). The
re-parse closes the window, and it is additive — v4 rows are inserted alongside v1–v3, so it
is reversible and the two versions can be compared, which is how the table above was
produced. Documented in DEVELOPER_GUIDE_1.md §9a.

### Phase 8 — The Published JD Bank (the final canonical library) + review-experience upgrades — 8.1 SHIPPED EARLY (2026-08-01), adapted; 8.2 GOAL MET by a different mechanism (2026-08-04); 8.3 open

> **P1.2 — HARMONIZATION PROVENANCE SHIPPED (2026-08-13).** The review page gains a **"How this
> draft was assembled"** panel: how many sources fed the draft, how each seniority bar was chosen
> and what the members actually stated, how many sources required each skill and stated each duty,
> and the HR-eyeball flags.
>
> **🔴 The backlog item understated the defect.** It named the education bar; the real finding is
> that **`merge_provenance` has been computed and persisted in `change_log` since Phase 4.1 and
> was read by NOTHING** — `grep` returned the producer and no consumer — so skill frequency, duty
> coverage, contributors and flags were *all* invisible. What genuinely did not exist is the bar
> record: `SeniorityBarChoice` (`models/bank.py`) now captures the policy actually applied, the
> chosen bar, and every member's stated bar.
>
> Three design points worth keeping:
> - **A silent member is not an overruled one.** `None` = stated no bar at all, which is not the
>   same as stating a lower one; counting silence as dissent would overstate the disagreement.
> - **No threshold anywhere, so no register entry is earned.** `disagreed` is a property of the
>   members' own statements. Inventing a "warn when ≥N disagree" knob would have manufactured a
>   decision HR then has to rule on — the standing rule bites on a *cutoff*, and there is none.
> - **The policy is described as itself** (*highest* / *most common*) from the recorded value,
>   never hardcoded, so the page cannot lie the day HR rules for `modal`.
>
> Advisory and read-only — it changes no verdict (NN #1/#3) — and a malformed packet costs the
> panel, never the page.

> **STATUS UPDATE (2026-08-05).** **8.1 was brought forward and shipped** in response to HR pilot
> feedback ("where are the actual JD files?"), but **adapted**: the browsable library
> (`jd_bank/library/` + `api/routes/library.py`, 🏦 JD Bank nav) covers the **DRAFT roles + their
> source JDs** — roles → sources → a **source-JD reader** + a flat `/archive` browser,
> click-to-sort, and **clone the harmonized role**. *The earlier wording — "since **zero canonicals
> are published yet**" — is now false: measured 2026-08-04, `canonical_jds` holds **1,798 DRAFT +
> 4 PUBLISHED** and `review_actions` holds **6** rows. Four published roles out of 1,802 is the
> publish path being exercised, not the 4.5 pilot; the library is still overwhelmingly a draft
> library.* Deltas vs. the 8.1 plan below: the planned **grade** facet is unavailable (measured
> absent — see the grade-capture thread + `docs/audit/data-state-and-grade-2026-08-01.md`);
> **provenance panel / version-history** on a *published* view are still open (the version-diff
> view already exists in review), and **"propose an update" SHIPPED (2026-08-02, `802bff0`)**.
> **8.2's goal is met (`cadfc30`) by a mechanism that supersedes the one specified below.**

**What it is.** Everything to date *produces* draft canonicals and moves them through a review queue;
approval sets `status=PUBLISHED` but there is **no destination surface** — the approved JDs have
nowhere to live. Phase 8 builds the **final JD Bank**: the browsable, searchable home for every
**approved** canonical JD, plus the forward actions off it (export, clone-to-new-draft, propose-an-
update). It also upgrades the **review experience** so a reviewer navigates the corpus structure
(cluster → versions → related roles) and reads a word-level diff, not just a flat form.

**Invariants inherited — do NOT re-decide.** NN #1 (nothing auto-publishes — the library is
**read-only** over rows a human already approved; the only writes are new DRAFTS into the existing
review queue). NN #3 (validator-as-oracle — the library never re-scores; it shows the approval-time
verdict). NN #5 (published-canonical embeddings run on the self-hosted model behind the egress
guard). NN #6 (provenance + append-only audit intact). Scope = JDFN (HR-143/194). Docker-only, TDD,
gates green; server-rendered `/jd-bank/ui`, no new service plan.

**8.1 — The published-canonical library (the "final bank").** *No GPU; the highest-value, most
self-contained first slice.*
- **Data:** no new store — the PUBLISHED `canonical_jds` rows ARE the bank. Add a read service
  (`list_published(filters, page)` + `get_published(id)`); latest PUBLISHED version per cluster is
  the canonical entry.
- **Browse UI** at `/jd-bank/ui/library` (nav: **🏦 JD Bank**): a faceted, paginated list of approved
  JDs — filters by `employee_group` / department·faculty / grade / title family, sort by title·date.
  Every headline count read from real rows and mutation-pinned (the dashboards discipline).
- **Published-JD view** (read-only): the rendered JD + a **provenance panel** (source documents,
  cluster, the approval record — who/when, overrides + their written reasons), **version history**
  (every version of the cluster; current = latest PUBLISHED), **export `.docx`** (reuse
  `render_sfu_docx`), and two forward actions — **"Start a new draft from this"** (clone into the
  Builder) and **"Propose an update"** (edit → a new DRAFT into the review queue). Nothing here
  publishes.
  - **"Propose an update" — ✅ SHIPPED (2026-08-02, `802bff0`), and the semantics are worth
    stating**, because they are not the obvious ones. Editing a PUBLISHED version mints a **new
    DRAFT** (it never mutates the published row — NN #1 still holds). The prior version
    **deliberately stays PUBLISHED** rather than being archived at edit time: archiving it then
    would leave the cluster with **no live approved JD for the whole review window**. It retires
    only when its replacement is approved — so `approve` now **supersedes** any other live
    published version of the cluster, under the same `SELECT … FOR UPDATE` lock, writing a
    `review.superseded` audit row; without that a cluster would carry two PUBLISHED rows and "the
    approved JD" would stop having one answer. **ARCHIVED stays refused**: rejected or superseded
    is settled, and editing one would fork a new version off dead history. The page followed — a
    published JD no longer offers Approve/Reject buttons the service can only refuse, an archived
    version offers no action, and advisory findings stopped being labelled as errors ("Suggested
    improvements" + amber badge when nothing blocks; "Fix these" only when a gate blocks).
- **Tests:** TestClient over a faked read service; empty-state (200, not a crash); JDFN-scoped;
  every figure mutation-pinned.

**8.2 — Embed the Bank's own output into the vector index.** **✅ GOAL MET (2026-08-04, `cadfc30`) —
by a mechanism that SUPERSEDES the one specified here. Adjudicated 2026-08-05; not to be re-opened.**

*The goal — "the Bank can search its own output" — is met.* `make embed-roles`
(`jd_bank/embeddings/roles.py`, `scripts/embed_roles.py`) writes one vector per **cluster** and
`search_similar_jds` reads it. Measured on the live corpus: **1,802 roles seen, 1,797 embedded,
5 empty** (`docs/embeddings/roles-summary.json`).

**What changed vs. the plan below, and why — three deliberate departures.**
1. **A separate `(:JDRole)` label and `jd_role_embeddings` index (migration `003`) — not
   `kind=canonical` inside `jd_document_embeddings`.** A role is a different **unit** from an
   archive document: one node distilled from many files, versus one node per source file. Folding
   them together would work today and **quietly corrupt the next `MATCH (d:JDDocument)` corpus
   count** — the "one index, two purposes" trap, which had already produced both the title-search
   and advisory-badge defects. Serialization is **not** re-invented: `serialize_document` is reused
   verbatim (same rulebook knobs, same `embed_stamp`, same title exclusion), so the cosines stay
   comparable and `rules_version` is untouched.
2. **Every current-version role, drafts included — not published-only.** The use is **seeding a
   clone, not publishing**: restricting to PUBLISHED would index **4** roles instead of ~1,800 and
   make the feature useful only after the pilot. Each node carries `status`, so a hit is labelled
   honestly, and only the **highest version per cluster** is embedded (a superseded version would
   put a second, competing vector in the index).
3. **NOT wired into `approve` — a decision, not a gap.** There is no embed-on-publish write path
   and there is not meant to be one: **publishing must not depend on the GPU** (a reviewer has to
   be able to approve with Ollama down), and network I/O inside the review transaction would hold
   the `SELECT … FOR UPDATE` lock across a slow call. Instead `make embed-roles` is an
   **idempotent, skip-first** runner — same `NodeKey` identity as documents, so a re-run costs
   nothing and an edited role re-embeds automatically, and `prune_roles` removes nodes whose
   cluster is gone. The cost is accepted and named: **a role approved after the last run is not
   searchable until the next one.** The "best-effort, non-fatal hook" the plan called for is
   strictly weaker than this — it would still open a socket inside the publish path.

*Still open from this slice:* labelling role hits **"approved" vs "reference"** in the UI beyond
the `status` the node already carries, and the library-side faceted browse over published output.
The `clone-from-canonical` path exists (library "Start from harmonized role").

**Register:** no new knob was needed — the role pass reuses the 5.4 search knobs and the
`embeddings.yaml` serialization decisions. The authoring guard that reads this index registered its
own (HR-195/196/197, see 5.9).

**8.3 — Review-experience upgrades.** *No GPU; parallelizable.*
- ✅ **8.3a Better diff — word/inline level. DONE (2026-08-13).** `src/jd_core/bank/word_diff.py`
  refines each changed section's before/after into `equal`/`insert`/`delete` **spans**, rendered
  side-by-side or as a `?view=unified` single stream. Pure, deterministic, no rulebook knob, so
  **no register entry and `rules_version` unmoved**.
  **⚠ THE FINDING, and it is why this needed measuring rather than writing: `difflib`'s default
  `autojunk=True` is catastrophically wrong for JD text.** It treats any element appearing in >1%
  of a sequence of ≥200 elements as junk — the exact shape of a duties list. Measured on a
  150-line repetitive block with ONE duty added, the default reports **897 tokens deleted and 913
  inserted**; the truth is **0 and 16**. It would have told every reviewer that every duty
  changed. `autojunk=False` is pinned by two tests, **mutation-proved** in both directions.
  Two more properties are pinned because a diff sits where a human decides to publish: it is
  **lossless** (the spans reassemble each side byte for byte, over newlines/tabs/unicode — a
  dropped word would show a JD that does not exist), and **spans are data, never markup** (a
  `|safe` on the span loop turns the XSS test red). The page **degrades to plain text** if the
  refinement is absent, and `?view=` is normalized rather than a `Literal` so a bad value cannot
  answer a raw `422` on a UI surface.
  **⚠ Reachability, stated honestly: it renders on ZERO live JDs today.** The diff needs a prior
  PUBLISHED version, and no cluster has more than one version (1,799 DRAFT · 4 PUBLISHED, each
  the only version of its cluster). The first edit of a published role is what creates the
  condition — so this is correct, gated and *waiting*, not yet exercised in production.
- ✅ **8.3b Structural sidebar (tree + related roles). DONE (2026-08-13).** The review detail page
  gains **"Where this role sits"**: a cluster → versions tree (current marked) and a ranked list of
  related roles. Read-only, server-rendered, no register entry. **Live-verified: 1,251 of 1,804
  canonical JDs (69.3%) show a non-empty list.**
  **⚠ THE PREMISE ABOVE WAS HALF WRONG, and measuring caught it.** This item said the list comes
  from "the **Tier-2/Tier-3** dedup edges". Only Tier-3 can work: `dedup_edges` joins **source
  documents** and those edges are what **formed the clusters**, so most are intra-cluster by
  construction. Measured — `NEAR_DUPLICATE`: 11,581 intra vs **16** cross-cluster (nothing, and by
  definition, since near-duplicates are clustered *together*); `ROLE_EQUIVALENT`: 29,034 intra vs
  **32,816** cross, giving 4,602 directed cluster pairs over 1,251 of 1,803 clusters.
  **⚠ AND "RELATED" UNDERSTATES WHAT THESE ARE.** A cross-cluster Tier-3 edge is a pair at or above
  the **pair** bar (0.5) but **below the merge bar** (`cluster_role_equiv_min` 0.75, HR-162) — **zero**
  of the 32,816 reach it. They are the near-misses clustering ruled on, so the page says exactly
  that and asks whether one of them *is* this role.
  **Ranked by a COUNT of connecting source documents, never by a score** — `RelatedRole` has no
  score field and a test fails if one is added (role similarity here has unrelated roles outscoring
  true twins). The only number is the display cap of 8, which is why no register entry is earned.
  Both DB guards are **mutation-proved against a real Postgres**: a one-sided edge lookup silently
  halves the list (Tier-3 edges are stored oriented, undirected in intent), and widening the tier
  filter re-admits near-duplicates. A heavyweight interactive graph viz remains out of scope (that
  is Phase 7's domain overlap graph; this is a lightweight review-time slice of it).
- ✅ **8.3c Gate → field jump-links. DONE (2026-08-13).** Each blocking gate now says *"Fix this
  in: Qualifications ↓"*, replacing the coarse whole-Edit `#edit` jump. **Rulebook-driven end to
  end and nothing is re-stated:** the gate carries the `rule_ids` that tripped it, the catalog owns
  each rule's `section`, and the catalog's own `section_order` and `section_labels` supply the order
  and the words. Only the section → HTML anchor is a UI concern. No register entry; `rules_version`
  unmoved.
  **⚠ THE COMPLETENESS PIN IS THE POINT:** `_SECTION_ANCHORS` is asserted equal to
  `get_args(SFUSection)` — enumerated from the live literal, not a hand-written list — so adding a
  template section without deciding where it lives fails the build instead of rendering a link that
  jumps nowhere. `general` is declared `None` (the whole document has no field), never omitted, for
  the same reason P1.3 gave `tier` no default. A second test walks the **rendered page** and asserts
  every `#edit-*` href has a matching `id`; a one-character typo in an anchor turns it red.
  **Measured over the whole archive before claiming coverage: 505 of 535 blocking-gate occurrences
  carry `rule_ids`**, so links are the common case. The only two that never do are
  `SCORE-FLOOR` and `GRADE-FLOOR` (15 each) — genuine roll-ups, where a link would misstate what is
  wrong. `SEVERITY-FLOOR` reads like a roll-up but names its rules (12/12 live), so it does get
  links unless tripped by a rule-less LLM finding. Live-verified on real blocked drafts:
  `KSA-ORDER → Qualifications`, `SUMMARY-CONDITIONS → Position Summary`.
  **🔴 P0.0's link crawl went red on this feature and was right to:** it reads template *source*,
  and a computed `href="#{{ target.anchor }}"` targets a set of *literal* ids rather than a
  matching dynamic `id=`. The link is declared in `OPAQUE_LINKS` (the mechanism P0.0 built for
  exactly this) and verified by walking `_SECTION_ANCHORS` against the template's ids —
  **stronger than the crawl could manage**, since it proves every value the link can take is a
  real anchor. **Blinding the crawl to Jinja fragments was the tempting fix and would have cost
  the net for every future template.**

**Sequencing:** ~~**8.1** (library) → **8.2** (embed + search) →~~ both landed 2026-08-01…04, out of
the order planned and partly ahead of it. **8.3** (review UX, no GPU) is what remains —
~~**8.3a**~~ ✅, ~~**8.3b**~~ ✅ and ~~**8.3c**~~ ✅ all landed 2026-08-13, so **Phase 8 is
complete**. 8.1 turned
the **1,798** latent drafts into a readable resource; 8.2 made them findable.

**Exit:** an approved JD has a permanent, browsable, searchable home; a reviewer navigates
cluster/version/related-role structure and reads a word-level diff; the Bank can search its own
output. *No separate `docs/tasks/phase-8-published-bank.md` was written and none is planned —
8.1/8.2 shipped directly and 8.3's three items are already session-sized as written above.*

**Relationship to earlier work:** 8.2 discharged the roadmap's *embed-published-canonicals* quick
win (goal met, mechanism changed) and supplied the vector prerequisite for the *approved-position
template library*; 8.3b is a lightweight review-time slice of Phase 7's org-design overlap graph;
8.1's "propose an update" reuses the review queue's edit path (`802bff0`).

---

### Phase 9 — Security, deployment and navigability (2026-08-07 → 08-13) — ✅ **COMPLETE**

**Not planned as a phase.** It came out of an **external architecture review** (2026-08-07)
whose claims were each re-verified against the code before being planned around — 9 of 11
confirmed, 2 partly true, none false — plus one defect found live minutes before an HR demo.
It is recorded here because a phase-by-phase build record that stops at Phase 8 would say
the last thing that happened was the published Bank, when the last week was spent making the
thing safe to put in front of a person. Ordered plan + triage:
`docs/tasks/architecture-review-response-2026-08-07.md` §6.

| | What | Shipped |
|---|---|---|
| **P0.1a** | The JSON API and the legacy harness routes carried **no auth gate**; an unauthenticated `POST /jd-bank/review/{id}/approve` reached the review *service* and on a gate-clean draft would have **published** (NN #1), writing the body-supplied `reviewer_id` into the hash-chained audit log as the actor (NN #6) | #82 · every router gated, the actor derived server-side, and an **authorization matrix** that walks the live routing table so a new route cannot ship ungated |
| **P0.2** | The production startup check `settings.py` claimed in a comment **did not exist**; the shipped default (`cas_enabled=False`) returned a transient **admin** to every cookieless request | #83 · `Settings` refuses to load an unsafe production posture. **Its own lesson:** the first implementation was correct and a complete no-op, because `ENVIRONMENT` reached zero of fourteen containers — found by *trying to deploy it* |
| **P0.1b-i** | Every UI mutation was a cookie-authenticated form POST with **no CSRF defence**; measured, an approve reached the service and published | #85 · a per-session token on the session row, enforced by an **app-wide dependency** over a rule stated about the *request*, not the route |
| **P0.0** | `http://localhost:25800` answered `{"detail":"Not Found"}` in a browser. Worse: `author` is `default_new_user_role`, and for an author **Submit committed the draft and stranded them on a raw 403** with no sign it saved | #88 · front door, HTML error pages negotiated on `Accept`, role-aware nav, **📝 My drafts**, and a **template link crawl** resolved against the live routing table |
| **P0.3** | The CAS return origin was one static value, so the app could not be reached two ways at once; the alternative already in the code took it from `X-Forwarded-Host`, **unvalidated** | #89 · an **origin allowlist**: derive the origin, honour it only if listed, else the static fallback — never the header. Data ports bound to loopback |
| **P0.4** | The deployment ran with `--reload` and the working tree mounted, so a settings refusal would have read `Up` while serving nothing | #90 · `docker-compose.prod.yml`, **verified by deploying it**; a standalone file because compose *merges* volume lists and an overlay cannot make the image be what runs |
| **P0.1b-ii** | Login CSRF on `GET /cas/validate` (it provisions users, may grant ADMIN, mints a session) and an **open redirect** on `next` that survived the whole CAS round trip | #91 · `next` pinned to a local path; an HttpOnly login-state cookie binds the round trip to the browser that started it |
| **P0.1b-ii** | `/ready` amplification (200 concurrent → 3.00s vs `/health` 0.43s; Postgres backends 1→13) and `GraphMemory` building an LLM client with no egress guard (NN #5) | #92 · single-flight + a 2s TTL (**peak backends under 300 concurrent: 2**), and the guard wired into the third construction path |

**What this phase changed about how we work**, beyond the fixes:

- **Enumerate from the live artifact, never a hand-maintained list.** The authorization
  matrix walks the routing table; the compose-delivery pin derives its required set from a
  real refusal message; the link crawl globs the template directory. Every one of those was
  written *after* a control shipped green over a hole.
- **Prove the net fails before trusting it.** Every safety net added here was mutated and
  observed red first.
- **Ask "is this offered?", not only "is this refused?"** The authorization matrix was
  correct on all 51 routes while a new user's very first click was a link to a 403. A
  correct gate on a link nobody should have been shown is still a defect.
- **A control is not shipped until it is reachable from the documented deployment path.**
  P0.2 and P0.4 were both found wanting by deploying them, not by reading them.

**Exit:** the system enforces the invariant everything else assumes — nothing publishes
without an authenticated, authorized human — and it can be deployed in a posture that
refuses to run unsafely. **Not delivered, and not a repo deliverable: TLS at the edge.**
The pilot host is internet-facing over plain http (P0.3 part 2), so sign-in cookies and CAS
tickets cross the network in the clear until a terminator is put in front of the app.

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

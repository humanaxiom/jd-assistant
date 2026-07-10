# hris Reuse Map — JD Bank Phase 0, Task 0.1

**Date:** 2026-07-10
**Author:** Phase 0 discovery session
**Scope:** Inventory every Job-Description-related module in `C:\repos\hris` and assign a reuse verdict (EXTRACT / REWRITE-FROM-SPEC / DISCARD) per module, to feed ADR-005 (extract-vs-rewrite strategy).

## What hris is

`hris` (package name `recruiter-assistant`) is a **local-first recruiter assistant** — graph+vector candidate matching, evidence-backed shortlists, and an SFU-aware JD quality/harmonization subsystem ("JD Bank"). JD Bank is the part JD Bank (this project) is spun off from.

**Method note (correction to a plan assumption).** The build plan (§Phase 0.1) hedged that "the original spec sketched TS interfaces; confirm what was actually built." **Confirmed: the JD logic is fully implemented in Python 3.12, not TypeScript.** hris is a `uv` workspace monorepo:

- **Python** (the real system): `apps/api` (FastAPI), `apps/worker` (arq), `packages/pipeline`, `packages/schemas`, `packages/prompts`. Stack: FastAPI, asyncpg/Postgres, Neo4j (vector index + skill graph), Redis/arq, Ollama via an OpenAI-compatible client, pydantic v2, `mypy --strict`, pytest + testcontainers.
- **TypeScript** (`apps/web`): a Next.js frontend only. Its `lib/schemas/*.ts` (`jdBank.ts`, `jdQuality.ts`, `sfuJd.ts`) are **zod mirrors** of the Python pydantic schemas for client-side form validation — not a second implementation. For a Python target project they are **API-contract reference only (DISCARD as code).**

**Method.** Static read-only inspection of `C:\repos\hris` (never executed). I read every JD-relevant Python module, its schemas, its prompts, the Alembic migrations, and the JD unit/integration tests, and traced each module's coupling to Postgres/Neo4j. I also confirmed the two rulebook specs in this repo (`docs/rulebook/recruiter-assistant-spec.docx`, `jd-authoring-guide.docx`) are **readable** (OOXML; extractable via unzip → `word/document.xml`) — the recruiter-assistant-spec is the same system-prompt content as `sfu-jd-standards.txt`.

**Architecture pattern that drives most verdicts.** hris cleanly separates **pure logic** (in `packages/pipeline/**` and `packages/schemas/**` — deterministic, no I/O, heavily unit-tested) from **orchestration/persistence** (in `apps/api/services/**` and `apps/worker/**` — coupled to Neo4j + Postgres). The pure packages are the high-value EXTRACT targets; the service/worker layer is REWRITE-FROM-SPEC because it is wired to hris's own graph model and DB schema. **Note (architecture, corrected 2026-07-10):** per inherited ADR-002, JD Bank **retains Neo4j** as its vector index (768-dim cosine, `nomic-embed-text`) + graph store; **Postgres** holds all relational/transactional data; **arq/Redis** runs the queues. There is **no pgvector**. So Neo4j is *not* a rewrite driver — hris's Neo4j recall code is an asset to port; the coupling that forces REWRITE is to hris's *specific* Job-node/skill-graph model and identity tables.

---

## Summary table

| # | Module (path) | Lang | What it does | Tests | Coupling | Verdict |
|---|---|---|---|---|---|---|
| 1 | `packages/schemas/src/schemas/sfu_jd.py` | Py | `SFUJobDescription` — the 10-section ParsedJD contract | `tests/unit/test_sfu_jd_schema.py` (56 L) | **Low** (pydantic only) | **EXTRACT** |
| 2 | `packages/schemas/src/schemas/jd_quality.py` | Py | Quality issue/report/checklist schemas + severity/category enums | `test_jd_quality_schema.py` (106 L) | Low | **EXTRACT** |
| 3 | `packages/schemas/src/schemas/jd_bank.py` | Py | Similarity/cluster/canonical/Hay/title/drift schemas | via bank unit tests | Low (some fields DB-shaped) | **EXTRACT** (trim persistence fields) |
| 4 | `packages/pipeline/src/pipeline/quality/jd_rules.py` | Py | Deterministic SFU quality gates + severity scoring/grading | `test_jd_quality_rules.py` (477 L) — thorough | **Low** (schemas + catalog) | **EXTRACT** ⭐ |
| 5 | `packages/pipeline/src/pipeline/quality/rule_catalog.py` | Py | Rule-id → SFU section/source-part metadata; section checklist builder | `test_jd_rule_catalog.py` (135 L) | Low | **EXTRACT** |
| 6 | `packages/pipeline/src/pipeline/bank/similarity.py` | Py | Job↔job similarity (vec+skill+seniority) + clone verdict | `test_jd_bank_similarity.py` (139 L) | Low (pure) | **EXTRACT** (maps to Tier 3 only) |
| 7 | `packages/pipeline/src/pipeline/bank/clustering.py` | Py | Union-find connected-components role clustering | `test_jd_bank_clustering.py` (65 L) | Low | **EXTRACT** |
| 8 | `packages/pipeline/src/pipeline/bank/title_family.py` | Py | SFU title ladder + Application-Table function + comma-format rule | `test_jd_bank_title_family.py` (103 L) | Low | **EXTRACT** |
| 9 | `packages/pipeline/src/pipeline/bank/hay_signals.py` | Py | Advisory low/mod/high Hay-factor signals w/ evidence | `test_jd_bank_hay_signals.py` (106 L) | Low | **EXTRACT** |
| 10 | `packages/pipeline/src/pipeline/bank/drift.py` | Py | Posting-vs-canonical skill/edu/experience/supervisory drift | `test_jd_bank_drift.py` (124 L) | Low | **EXTRACT** |
| 11 | `packages/pipeline/src/pipeline/bank/provenance.py` | Py | Skill-frequency across cluster members (harmonize backbone) | via bank tests | Low | **EXTRACT** |
| 12 | `packages/pipeline/src/pipeline/bank/render.py` | Py | `SFUJobDescription` → plain-text JD (template order) | `test_jd_bank_render.py` (51 L) | Low | **EXTRACT** |
| 13 | `packages/pipeline/src/pipeline/bank/export.py` | Py | Canonical JD → DOCX/PDF bytes + mandatory footer constants | `test_jd_bank_export.py` (66 L) | Low (`python-docx`/`reportlab`) | **EXTRACT** (verify footer wording) |
| 14 | `packages/pipeline/src/pipeline/parsing/extract.py` | Py | PDF/DOCX/RTF/TXT text extraction (PyMuPDF/python-docx) + NUL-scrub | `test_multiformat.py` (89 L) | Low | **EXTRACT** |
| 15 | `packages/pipeline/src/pipeline/parsing/chunk.py` | Py | Section-aware chunker — **résumé-shaped** | `test_resume_chunker.py` | Low but résumé-specific | **REWRITE-FROM-SPEC** |
| 16 | `packages/prompts/.../sfu_jd_extract_v1.{system,user}.j2` | Jinja | LLM extraction prompt → `SFUJobDescription` JSON | `tests/golden/test_jd_extract_golden.py` (125 L) | Low | **EXTRACT** |
| 17 | `packages/prompts/.../jd_harmonize_v1.{system,user}.j2` | Jinja | LLM prompt to merge a cluster → one canonical JD | `test_jd_bank.py` (integration) | Low | **EXTRACT** (prompt only; see gap) |
| 18 | `packages/prompts/.../jd_quality_v1.{system,user}.j2` | Jinja | LLM nuanced/cited quality pass (bias, clarity) | integration | Low | **EXTRACT** |
| 19 | `packages/prompts/.../jd_extract_v1.*` | Jinja | Matching-only JD skill extract (`JDExtracted`) | golden | Low | **DISCARD** (matching, not JD Bank) |
| 20 | `apps/worker/src/worker/jd_quality_task.py` | Py | Orchestrates rules + LLM merge, anti-fabrication guard, scoring | `test_jd_quality.py` (integration, 269 L) | **Med** (arq, asyncpg, LLMClient) | **REWRITE-FROM-SPEC** (keep the merge pattern) |
| 21 | `apps/worker/src/worker/jd_bank_task.py` | Py | Bank pipeline worker (similarity/cluster/harmonize triggers) | integration | **High** (arq, PG, Neo4j) | **REWRITE-FROM-SPEC** |
| 22 | `apps/api/src/api/services/jd_bank_service.py` (1170 L) | Py | Neo4j vector recall + PG persistence for all bank features | `test_jd_bank.py` (1124 L) | **High** (Neo4j `AsyncDriver` + asyncpg + hris schema) | **REWRITE-FROM-SPEC** |
| 23 | `apps/api/src/api/services/jd_quality_service.py` | Py | Append-only persistence + corpus leaderboard SQL | integration | **High** (asyncpg + hris tables) | **REWRITE-FROM-SPEC** |
| 24 | `apps/api/src/api/services/jd_import_service.py` | Py | Uploaded file (txt/json/pdf/docx) → JD text | (thin; via extract tests) | Low (wraps #14) | **EXTRACT** |
| 25 | `apps/api/src/api/services/redaction.py` | Py | Blind-review redaction (names, contacts, foreign locations) | `test_redaction.py` | Med (résumé-oriented) | **REWRITE-FROM-SPEC** (repurpose for incumbent scrub) |
| 26 | `apps/api/src/api/services/pii.py` | Py | pgcrypto session-keyed encryption of **résumé** PII | `test_pii_encryption.py` (integration) | High (pgcrypto, résumé cols) | **DISCARD** (not JD) |
| 27 | `apps/api/src/api/routes/jd_bank.py`, `routes/jd_quality.py` | Py | FastAPI endpoints (17 bank routes + quality) | integration | High (FastAPI deps, services) | **REWRITE-FROM-SPEC** (API-shape reference) |
| 28 | `packages/pipeline/src/pipeline/sources/taleo.py` (692 L) | Py | Taleo careers-site HTML scraper for live SFU postings | `test_taleo_parser.py` | Med (httpx, HTML) | **DISCARD** (live scrape, not archive ingest) |
| 29 | `apps/api/migrations/versions/0016–0024*.py` | Py | Alembic DDL: quality, similarity, clusters, canonical roles, Hay grades | — | High (hris DB) | **REWRITE-FROM-SPEC** (schema reference) |
| 30 | `docs/jd-harmonizer/sfu-reference.md` + `sources/sfu-total-comp-learning-series.md` | MD | Source-of-truth mapping of SFU rulebook → code constants | n/a | None | **EXTRACT** (reference asset) |
| — | `apps/web/lib/schemas/{sfuJd,jdBank,jdQuality}.ts` | TS | zod client mirrors of the Python schemas | `apps/web/lib/schemas/__tests__/*` | Low | **DISCARD** (frontend contract only) |

---

## Per-module detail

### jd_core candidates (pure logic + contracts — the high-value extractions)

**1. `sfu_jd.py` — `SFUJobDescription` (the ParsedJD contract).** Pydantic v2 model of SFU's 10-section template in order: identification, position summary, `duties: list[SFUDuty]` (action_verb / statement / how_why), decision_making, problem_solving, `relationships` (supervisory/internal/external), `qualifications: list[SFUQualification]` (kind ∈ education/experience/knowledge/skill/ability/security, Toolkit modifier), plus presence-booleans for About-SFU / territorial-ack / employment-equity. Includes LLM-robustness (`_null_to_empty` coerces JSON `null`→`[]`). **This is exactly the "port the `SFUParsedJD` structure" the plan (§1) names as the universal contract.** Coupling: none beyond pydantic. Verdict **EXTRACT** — port verbatim to `jd_core`; it is already Python, so this is a near-copy, not a re-derivation.

**2. `jd_quality.py`.** `JDQualityIssue{category, severity, source, message, suggestion, evidence, rule_id}`, `JDQualityReport` (score/grade/issues/checklist + version stamps), LLM-output schema `JDQualityFindings`, corpus-summary schemas. Severity scale `info/low/medium/high` and 9 issue categories. Maps 1:1 to the plan's `ValidationIssue{code, severity, section, evidence, recommendation}` (§2). Verdict **EXTRACT**; rename fields to the plan's vocabulary during port (e.g. `rule_id`→`code`).

**3. `jd_bank.py`.** Schemas for neighbours, clusters, canonical roles, governance (approve/member/link), Hay signals + source-gated `HayGrade`/`HayGradeMapping`, title-family/function results, and drift reports. Some fields are hris-persistence-shaped (`cluster_id`, `approved_by`, version stamps). Verdict **EXTRACT** the value objects (`CanonicalRole`, `HaySignals`, `TitleFamilyResult`, `DriftResult`-adjacent), trim the DB-lifecycle fields to match JD Bank's own `canonical_jds`/`clusters` tables.

**4. `quality/jd_rules.py` — ⭐ the crown jewel.** Pure, deterministic SFU quality auditor. `evaluate_jd_rules(sfu, raw_text)` runs six rule families: completeness (mandatory sections), structure (100–150-word summary, 3–5 duties, approved action-verb glossary of ~130 verbs, how/why presence, placeholder detection), qualifications (skill/knowledge modifier vocab, equivalent-combination, banned "may include/assets/preferences", degree-discipline), inclusive-language (SFU gender-coded lexicon w/ replacements, `_CODED_TERMS` + low-severity set), quality-gates (duty % totals 100, K→S→A order, "Senior" title needs supervision, standardized Relationships header), authoring-gates (no working-conditions/incumbent-language in summary, observable-ability phrasing, restricted titles Exec-Director/Registrar/HR). Plus `score_issues` (severity-weighted with per-tier diminishing-returns decay) and A–F grade bands. **These map directly onto the plan's "rulebook as tests" and the `sfu-jd-standards.txt` Part 11.6 "never approve" gates.** Test coverage is thorough (477-line test with failing- and passing-fixture cases per gate). Coupling: only `schemas` + `rule_catalog`. Verdict **EXTRACT** — but note the plan (§Phase 2.1) requires **rules-as-data (YAML/JSON), loaded not hardcoded**; hris keeps the lexicons/verb-lists/thresholds as Python `frozenset`/`dict` literals. So: EXTRACT the *logic and the exact values*, but externalize the data tables to versioned YAML during the port. `RULES_VERSION = "jd_rules_sfu_v3"`.

**5. `quality/rule_catalog.py`.** Every gate carries a stable `rule_id` (e.g. `SFU-COMP-SUMMARY`) mapped to its SFU template section, guide source-part ("Part 2B"), category, default severity, and owner. `build_checklist()` regroups a flat issue list into the 10-section recruiter checklist. This is the traceability spine — findings reference gates by id, not fragile message text. Verdict **EXTRACT**; pairs with #4.

**6. `bank/similarity.py`.** `score_job_similarity = 0.45·vec + 0.45·skill + 0.10·seniority`; idf-weighted ontology-aware skill Jaccard; `normalize_title` strips seniority tokens; `clone_verdict` approximates the Toolkit cloning rule. **Important scope note:** this is a **Tier-3 role-equivalence** signal (semantic + skill overlap). It is **not** the plan's Tier-1 (SHA-256 exact) or Tier-2 (MinHash/5-gram near-dup) — those do not exist in hris and must be **built new** (Phase 3.1/3.3). Verdict **EXTRACT** for Tier 3; the vector component here comes from Neo4j and the *scoring math is pure* (takes a plain cosine float), so it drops straight onto JD Bank's Neo4j vector index (ADR-002) — the same store hris already uses.

**7. `bank/clustering.py`.** Union-find connected components over edges ≥ `CLUSTER_THRESHOLD` (0.80), components ≥2, deterministic ordering; `cluster_metrics`/`cluster_label`. Documents Louvain as the fallback if it over-merges. Note: the plan wants **hard constraints (employee-group + level band) and a diameter cap** (§2.1–2.2) that this does not implement. Verdict **EXTRACT** the union-find core; add the constraint-partitioning per spec.

**8. `bank/title_family.py`.** Two-dimensional SFU title classifier: seniority ladder (vp→chief→director→manager→lead→associate→assistant) and the Application-Table *function* (analyst/officer/coordinator/…), plus `title_comma_supervisory` implementing the Part 3.4 "Manager, X" vs "X Manager" rule. Directly encodes rulebook Part 3. Verdict **EXTRACT** (needed for Tier-3 title normalization + composer facets).

**9. `bank/hay_signals.py`.** Advisory low/moderate/high per Hay factor (Know-How/Problem-Solving/Accountability) from JD sections, with cited evidence phrases; explicitly *never* a grade (grades are source-gated). Matches the plan's Phase-7 "Hay-readiness" option. Verdict **EXTRACT** (low priority — not MVP-critical, but clean and free).

**10. `bank/drift.py`.** Pure drift between a posting and its canonical: skill-set Jaccard distance + escalation to "major" on SFU re-evaluation triggers (education-level change, ≥2y experience shift, >5 direct-reports change), each with a human-readable reason. Verdict **EXTRACT** (feeds review-queue "worth a second look").

**11. `bank/provenance.py`.** `skill_frequency()` — how many cluster members require each skill (harmonization provenance). Tiny, pure. Verdict **EXTRACT**.

**12. `bank/render.py`.** Inverse of extraction: `SFUJobDescription` → readable plain-text JD in template order (drops empty sections). Feeds the composer "start from canonical" flow. Verdict **EXTRACT**.

**13. `bank/export.py`.** Canonical JD → DOCX (`python-docx`) / PDF (`reportlab`) bytes, all sections in template order **plus the two mandatory closing statements as hardcoded constants** (`_TERRITORIAL_ACKNOWLEDGEMENT`, `_EMPLOYMENT_EQUITY`). This is the plan's `jd_export`. ⚠️ **The footer text carries the simplified orthography flagged in the plan** — the plan's Phase-6 "verify territorial-acknowledgement wording" action item applies to this constant. Note: hris does **not** enforce Times-New-Roman-10 / bold-headers / `(60%)` bullet formatting that the plan's `jd_export` requires (§2.5) — that formatting fidelity must be added. Verdict **EXTRACT** the renderer + footer constant (then verify wording and add SFU-template styling).

**14. `parsing/extract.py`.** Text extraction for PDF (PyMuPDF/`fitz`, two-column reading-order, encrypted-PDF + low-text-density warnings), DOCX (`python-docx`), RTF (`striprtf`), TXT (tolerant decode ladder); strips NUL chars that break Postgres writes. OCR is stubbed/deferred (ADR 0007) — matches the plan's "OCR fallback" being a later concern. Verdict **EXTRACT**; note the plan prefers pdfplumber but PyMuPDF is fine and more robust.

**15. `parsing/chunk.py`.** Section-aware chunker labelling text as experience/education/skills — **built for résumés**, not JD section segmentation. The plan needs a JD section segmenter (Phase 1.4) tolerant of old+new SFU templates. Verdict **REWRITE-FROM-SPEC** (the chunking idea is useful; the section taxonomy must be JD/SFU-template, using the old-template heading map from `sfu-jd-standards.txt` Part 8 as the fallback).

### Prompts

**16–18. `sfu_jd_extract_v1`, `jd_harmonize_v1`, `jd_quality_v1`.** Jinja system/user prompt pairs. `sfu_jd_extract` defines the exact JSON contract for `SFUJobDescription` and has golden tests. `jd_harmonize` consolidates cluster members into one canonical JD with SFU rules embedded (neutral title, min-quals + equivalent-combination, 3–5 action-verb duties, no verbatim copying). `jd_quality` is the nuanced cited LLM pass. All run through the Ollama-backed `LLMClient.chat_json`. Verdict **EXTRACT** all three prompts (they encode rulebook constraints and are model-agnostic text).

**19. `jd_extract_v1`.** Extracts only matching-relevant skills (`JDExtracted`, `jobs.py`) — part of the résumé-matching pipeline, superseded for JD Bank by `sfu_jd_extract_v1`. Verdict **DISCARD**.

### Orchestration / persistence (coupled — rewrite, keep the pattern)

**20. `jd_bank_service.py` (1170 lines).** The big orchestrator: `compute_similarity` does **Neo4j vector recall** (`MATCH (j:Job {id})... summary_embedding`) + reads canonical skills/ontology families from the **skill graph** (`(:Job)-[:REQUIRES]->(:Skill)`), then applies the pure `pipeline.bank` scorers; `recompute_clusters`, canonical-role draft/approve/member governance, Hay-grade lookup, drift, bank-health snapshots. **High coupling: `neo4j.AsyncDriver` + `asyncpg` + hris's own tables.** JD Bank **retains Neo4j** for the vector index + graph and **Postgres** for relational data (ADR-002), so this file's Neo4j vector-recall Cypher and skill-graph queries are **directly reusable** — this is not a store swap. Verdict **REWRITE-FROM-SPEC** only because it is wired to hris's *own* Job-node model + relational tables; **adapt** it to JD Bank's graph/table model rather than rebuild from scratch (effort accordingly lower than a clean-room rewrite). Keep it as the definitive **behavioral reference** (its integration test, 1124 lines, documents expected end-to-end behavior).

**21. `jd_bank_task.py` / 23. `jd_quality_service.py`.** arq worker + append-only Postgres persistence (leaderboard/corpus SQL, `jd_quality_evaluations`). Coupled to hris tables and arq. Verdict **REWRITE-FROM-SPEC** (JD Bank uses its own `validation_reports`/`canonical_jds` tables and its own queue — arq or RQ per ADR).

**20b/22. `jd_quality_task.py` merge pattern.** Worth calling out: `_merge_llm_findings` **drops any LLM finding whose `evidence` is not a verbatim substring of the JD** (anti-fabrication guard), then merges with deterministic issues and re-scores. This is exactly the plan's "validator is the universal oracle / assert post-state" discipline (§4). Verdict **REWRITE-FROM-SPEC** but **port the merge+guard pattern faithfully**.

**24. `jd_import_service.py`.** Thin, clean: uploaded bytes (txt/json/pdf/docx, 10 MB cap, extension-first dispatch) → JD text, wrapping `parsing.extract`. Verdict **EXTRACT** (small; useful for the composer's upload path).

**25. `redaction.py`.** Display-time redaction: person-name pattern, email/phone patterns, employer/school label-mapping, foreign-location scrub (US-states/countries lists). Built for **résumé blind review**, but `_name_pattern` and the email/phone regexes are directly reusable for the plan's **incumbent-name PII scrub** (§0, §1.3). Verdict **REWRITE-FROM-SPEC** — repurpose the name/contact redaction primitives into `jd_core/scrub`; drop the résumé-specific foreign-location logic.

**26. `pii.py`.** pgcrypto session-keyed encryption of **résumé** PII columns (candidate emails). Not JD-related. Verdict **DISCARD**.

**27. `routes/jd_bank.py` (17 endpoints) + `routes/jd_quality.py`.** FastAPI route shapes for similar-roles, clusters, canonical approve/members, drift, health, quality corpus. Verdict **REWRITE-FROM-SPEC** — valuable as an **API-surface reference** for JD Bank's own FastAPI app.

### Not reusable for JD Bank

**28. `sources/taleo.py` (692 lines).** HTML scraper for SFU's live Taleo careers site (requisition discovery + field parsing, polite delays). JD Bank ingests a **fixed archive** (`fixtures/SFU_JDs`), not a live site. Verdict **DISCARD** (Phase-7 "transposer-as-a-service"/live surfacing might revisit, but not now).

**29. Migrations `0016–0024`.** Alembic DDL for `jd_quality_evaluations`, `jd_similarity_neighbours`, `jd_clusters`, `canonical_roles` (+ governance/durability), `bank_health_snapshots`, `job_sfu_parse`, `hay_grades`. Coupled to hris's identity/jobs tables. Verdict **REWRITE-FROM-SPEC** — excellent **schema reference** for JD Bank's `validation_reports`/`clusters`/`canonical_jds`/`dedup_edges` tables (§1 data model), but not directly runnable.

**30. `docs/jd-harmonizer/` (reference docs).** `sfu-reference.md` and `sources/sfu-total-comp-learning-series.md` are a **source-gated mapping of the SFU Toolkit/Hay guide to code constants** (page-cited, "do not invent values here"). Plus `GUIDE.md`, `HANDOVER.md`, `CHANGELOG.md`, and ADR `0025-jd-bank-taxonomy-title-family-and-hay-grade-blocker.md`. Verdict **EXTRACT as reference** — these directly support the plan's "rulebook as the spec" and should travel with the ported rules to preserve provenance.

---

## Verdict tally

| Verdict | Count | Modules |
|---|---:|---|
| **EXTRACT** | **16** | #1 sfu_jd, #2 jd_quality schema, #3 jd_bank schema, #4 jd_rules ⭐, #5 rule_catalog, #6 similarity, #7 clustering, #8 title_family, #9 hay_signals, #10 drift, #11 provenance, #12 render, #13 export, #14 extract, #16 sfu_jd_extract prompt, #24 jd_import + (#17,#18 prompts, #30 docs as reference assets) |
| **REWRITE-FROM-SPEC** | **8** | #15 chunk, #20 jd_bank_service, #21 jd_bank_task, #22/#23 jd_quality_task + jd_quality_service, #25 redaction→scrub, #27 routes, #29 migrations |
| **DISCARD** | **4** | #19 jd_extract prompt, #26 pii, #28 taleo, apps/web TS mirrors |

(Prompts #17/#18 and docs #30 are folded into EXTRACT; counting each prompt pair once, EXTRACT is the clear majority.)

**Headline:** the entire `packages/pipeline/pipeline/{quality,bank,parsing}` layer plus `packages/schemas` — the deterministic rulebook engine, the ParsedJD contract, the similarity/cluster/title/Hay/drift math, and the extractors — is **clean, pure, low-coupling, and well-tested → EXTRACT**. Because hris is already Python 3.12/pydantic v2, "EXTRACT" here is a **near-verbatim port**, not a re-derivation. The **coupled service/worker/route layer is REWRITE-FROM-SPEC**, but only because it is wired to hris's **own graph model + relational schema** — Neo4j itself is retained (ADR-002), so the vector store is not the blocker and hris's recall Cypher is an asset to port. The algorithms it calls are already in the extractable packages, so these "rewrites" are mostly re-wiring, not re-derivation.

---

## Risks & notes (feeds ADR-005 and later phases)

1. **Rules are hardcoded, not data.** `jd_rules.py` holds the action-verb glossary, gender-coded lexicon, thresholds, and grade bands as Python literals. Plan Phase 2.1 mandates **versioned YAML/JSON loaded at runtime**. EXTRACT the values, but externalize them during the port (and carry `docs/jd-harmonizer/sfu-reference.md` as their provenance).

2. **Dedup tiers 1 & 2 do not exist.** hris similarity is a single embedding+skill Tier-3 signal. The plan's **Tier-1 SHA-256 exact** and **Tier-2 MinHash/5-gram near-dup** must be **built new** (Phase 3.1/3.3). `similarity.py` covers Tier-3 only.

3. **No deterministic harmonization merge engine.** Harmonization in hris is an **LLM prompt** (`jd_harmonize_v1`) orchestrated in `jd_bank_service`. The plan's Phase 4.1 wants a **pure, LLM-free merge engine** (section selection, duty union/dedup/reorder, %-rebalance, KSA rebuild). hris gives you the *prompt* and `provenance.skill_frequency`, but the deterministic merge is a **build-new gap**.

4. **No incumbent-name PII scrub for JDs.** `redaction.py` is résumé-oriented and `pii.py` encrypts résumé emails. The plan's ingestion PII-scrub (incumbent names) must be assembled from `redaction.py`'s name/contact primitives (REWRITE).

5. **Clustering lacks hard constraints.** hris clustering has no employee-group/level-band partitioning or diameter cap (plan §2.2). Add during port to prevent over-merging Coordinator↔Manager roles.

6. **Neo4j is retained — it is *not* a rewrite driver (corrected).** Per inherited ADR-002, Neo4j remains JD Bank's vector index (768-dim cosine, `nomic-embed-text`) + graph store; **Postgres** holds all relational/transactional data; **arq/Redis** runs the queues. **There is no pgvector.** hris's Neo4j vector-recall and skill-graph Cypher are therefore an **asset to port**, not a liability. The real rewrite driver in the service layer is coupling to hris's *own* node/table schema (Job/identity tables) — bounded, mechanical re-wiring. (This supersedes an earlier draft of this doc that assumed a pgvector re-host.)

7. **Footer wording open flag confirmed.** `bank/export.py` hardcodes the territorial acknowledgement/employment-equity text with simplified orthography — matches the plan's known flag. Blocks external distribution (Phase 6), not development.

8. **SFU-template export formatting is partial.** `export.py` produces structurally-correct DOCX/PDF but does **not** enforce TNR-10 / bold headers / `(60%)` bullet styling the plan's `jd_export` requires. Add on port.

9. **Rulebook specs are readable.** `docs/rulebook/recruiter-assistant-spec.docx` and `jd-authoring-guide.docx` are valid OOXML and extract cleanly; `recruiter-assistant-spec.docx` mirrors `sfu-jd-standards.txt`. No blocker there.

10. **Test assets are a bonus.** The JD unit/integration tests (~3,000 lines total, e.g. `test_jd_quality_rules.py` at 477 lines with per-gate fixtures, `test_jd_bank.py` at 1,124 lines) are themselves a reusable **behavioral spec** — port the pure-module unit tests alongside the code to preserve the rulebook-as-tests guarantee.

# JD Assistant: Architecture and Design Critique

Date: 2026-08-07  
Scope: read-only review of the repository as it exists today. Existing code and documentation were not changed.

## Executive assessment

JD Assistant is best understood as a governed job-description bank, not as an autonomous writing tool. It ingests a historical archive, parses and evaluates documents, detects related roles, creates harmonized canonical drafts, supports guided authoring, and requires a human reviewer to publish. The strongest architectural choice is that deterministic rules—not an LLM—are the approval oracle, and that the only publication path passes through a fresh validation and human review.

The system is technically mature for a pilot: it has explicit provenance, versioned rules, typed models, extensive tests, source hashing, role-based UI access, versioned canonical JDs, and a tamper-evident audit chain. It is not yet ready to be represented as settled HR policy or as a production-hardened enterprise service. The decision register reports 197 decisions, all open and none ratified; only 4 of roughly 1,802 canonical roles are published. The principal critical path is therefore governance and pilot validation, followed closely by closing API authorization gaps and turning the operator-driven data pipeline into a durable, observable workflow.

## System purpose and boundaries

The system supports two paths into the same controlled review process:

1. Archive path: source files are extracted, parsed, evaluated, embedded, deduplicated, clustered, merged, optionally rewritten/audited by an internal LLM, and persisted as canonical drafts.
2. Authoring path: an author searches or clones an existing role, answers guided questions, validates the result, optionally uses bounded writing assistance, and submits a draft.

Both paths converge on a versioned `DRAFT` canonical JD. A reviewer then edits, rejects, approves, or explicitly overrides eligible gates with a reason. Approval is the only transition to `PUBLISHED`.

Out of scope by present design:

- CUPE Weighted Job Questionnaires are readable/searchable but are not evaluated or authored against the APSA/APEX/Polytechnic bar.
- The quality score is not a classification or compensation decision.
- Similarity is an advisory retrieval/ranking signal, not proof that two jobs are equivalent.
- LLM findings are advisory and do not decide publication.
- “Published” currently means approved within JD Bank; downstream HRIS authority and integration are not yet defined.

## Logical architecture

```text
Archive files                         Guided Builder
     |                                     |
extract -> parse -> deterministic scan     | search/clone -> assemble
     |                                     |          |
PostgreSQL source + parsed records         +-> deterministic validation
     |                                                |
embed -> Neo4j retrieval index                         |
     |                                                |
dedup -> cluster -> deterministic merge <-------------+
     |                                                |
optional grounded rewrite + advisory audit            |
     +---------------------> canonical DRAFT <---------+
                                      |
                         fresh validation at review
                                      |
                    edit / reject / reasoned override
                                      |
                              human approval only
                                      |
                                 PUBLISHED JD
```

## Runtime and storage design

- FastAPI serves JSON endpoints and server-rendered Jinja UI. The README diagram still describes a separate Flask frontend, but the current implementation is integrated into FastAPI; this documentation mismatch should be corrected in a future authorized docs pass.
- PostgreSQL is the authoritative transactional ledger for source documents, parsed JDs, validation reports, dedup edges, clusters, canonical versions, review actions, users, sessions, roles, and audit events.
- Neo4j is a derived/rebuildable graph and vector retrieval store. Separate indices represent archive documents and harmonized roles. It also hosts inherited agent-lineage memory, creating operational coupling between unrelated workloads.
- Redis/arq provides background task dispatch.
- Ollama is an OpenAI-compatible inference endpoint on trusted internal infrastructure and outside Docker Compose.
- Docker Compose runs the API, worker, data services, and many profile-gated batch jobs. Most archive processing is invoked by operators through `make` targets rather than through one durable workflow engine.

Key evidence: `README.md`; `docker-compose.yml`; `core/src/settings.py`; `core/src/api/main.py`; `core/src/jd_bank/db/models.py`; `core/db/migrations/`; `docs/adr/002-neo4j-memory-postgres-ledger.md`; `docs/adr/003-offline-inference-ollama.md`.

## Domain pipeline

### 1. Ingest and parse

Files are hashed, scrubbed, extracted from multiple legacy formats, segmented into SFU sections, and stored with parser provenance. Recent parser work correctly recovered identification fields held in DOCX headers. Strong idempotency constraints prevent duplicate source rows and duplicate parses for the same parser version.

Concern: extractor version is not part of the parse identity. An extractor-only change can therefore require a manual version bump or leave a logically stale parse appearing current. Changed bytes at the same storage path also create additional source rows without an explicit “current logical document” relationship.

### 2. Deterministic evaluation

Versioned YAML drives structural, language, title, qualification, boilerplate, scoring, and gate behavior. Validation creates evidence-bearing findings. Scoring and approvability are intentionally separate:

- Score starts at 100 and deducts severity-weighted penalties with decay for repeated issues.
- Grade bands map the score to A–F.
- Gates independently decide whether publication is allowed, including named blocking findings and score/grade/severity floors.

This separation is defensible, but difficult to explain because several mechanisms overlap. On the current-practice cohort, the numeric score floor rejects very few documents while the 150-word summary maximum is the dominant blocker. The UI and HR policy should therefore describe the score as a diagnostic summary, not imply it is the main control.

### 3. Retrieval, deduplication, and clustering

The system combines exact hashes, MinHash/Jaccard near-duplicate analysis, role-equivalence signals, embeddings, title families, seniority signals, and veto rules. Connected components form clusters used for harmonization. Search ranks exact titles ahead of semantic results and collapses source documents into their harmonized roles.

Strength: the repository repeatedly measures whether similarity supports an operational decision and avoids publishing misleading percentages or cutoffs where the corpus does not support them.

Concerns:

- Exact duplicate edges are synthesized for clustering rather than persisted alongside other dedup evidence.
- Role-equivalence candidate generation includes an expensive quadratic bucket.
- Character-based truncation can mishandle dense documents and creates unembedded outliers.
- WJQ boilerplate and missing titles distort embeddings and clusters.
- Similarity and harmonization parameters are still unratified policy inventions.

### 4. Harmonization and AI assistance

The deterministic merge selects and combines content with recorded kept/dropped provenance. An optional LLM rewrite is constrained by structured output, grounding checks, retry limits, and deterministic fallback. An optional LLM audit can surface nuanced language, clarity, or seniority findings, but these findings are advisory.

This is a good safety boundary. The risk is not autonomous publishing; it is quiet degradation. Best-effort LLM failures can result in a deterministic draft or omitted advisory audit without a sufficiently prominent reviewer-facing explanation. Harmonization defaults can also inflate requirements—for example, taking the maximum education/experience bar or unioning security requirements—unless HR deliberately approves those policies.

### 5. Review, versioning, and publication

The review service locks the current row, recomputes validation from current content, checks overrides, and publishes only if the resulting gate decision permits it. Reject and edit require reasons. Editing a published JD creates a new draft while the prior approved version remains live; approval of the replacement supersedes it. This is a strong model for continuity and provenance.

The important distinction is that the audit chain is tamper-evident, not yet tamper-resistant. Database-owner permissions can still update/delete records unless production roles, privileges, monitoring, and external anchoring make such changes operationally difficult and detectable.

## User-facing architecture

The global UI includes Library, Builder, Review queue, Dashboards, Guide, and administrator-only Users.

- Library: search/sort roles, inspect a harmonized role, see source provenance, or inspect raw archive documents.
- Builder: search/clone, answer structured questions, check compliance, receive advisory related-role warnings, use optional summary assistance, export, and submit.
- Review: triage drafts, inspect live findings and gates, compare with the last published version, view removed source content, edit, reject, override, or approve.
- Dashboards: baseline quality, deduplication, and cluster evidence from committed artifacts.
- Admin: grant/revoke roles and enable/disable accounts.

Material UX defect: a normal author may submit, but the success redirect targets a reviewer-only detail page, leading to a 403. There is no author-facing “my submissions” or confirmation/status page. Other notable gaps include limited review-queue triage, weak action confirmation, no visible CSRF token mechanism, limited accessibility semantics/responsive design, stale hard-coded corpus counts, and development-oriented error guidance exposed in dashboards.

Evidence: `core/src/api/routes/`; `core/src/api/templates/`; `docs/OPERATOR-GUIDE.md`.

## Architectural strengths

1. Human authority is structurally enforced: nothing auto-publishes.
2. The deterministic validator is reused in Builder, canonical generation, and review; review-time recomputation prevents stale results from becoming authoritative.
3. Rules-as-data, rule versions, source hashes, parser/model/prompt stamps, and change logs provide unusually strong reproducibility.
4. PostgreSQL is authoritative while graph/vector data is treated as derived retrieval state.
5. LLM use is downstream, bounded, schema-validated, grounded, and recoverable through deterministic fallback.
6. Review actions, version history, reasons, overrides, and provenance are preserved.
7. Transaction boundaries and row locks protect review transitions and published-version uniqueness.
8. The test suite is broad: strict lint/type gates, unit and real-store integration tests, migration tests, auth/audit tests, and optional live-model tests.
9. The project demonstrates good empirical discipline: it rejects thresholds and lexicons when corpus measurements do not support them.

## Principal risks and design debt

### Critical

1. Incomplete API authorization. UI routers have role gates, but legacy harness endpoints and some JD JSON/compose endpoints are not equivalently protected. Body-supplied actor identity is not an acceptable production trust boundary. Every endpoint must authenticate, authorize, and derive actor identity server-side.
2. Policy without legitimacy. All 197 registered decisions are open. The software faithfully enforces provisional settings, but tests cannot convert those settings into HR policy.
3. Production configuration is development-oriented. CAS defaults off, synthetic development identity is highly privileged, cookies are not secure by default, default service credentials are committed, API runs with reload, source is bind-mounted, and data ports are exposed.
4. Corpus correctness for WJQ. Known title/boilerplate problems can contaminate similarity and clustering. WJQ must remain excluded from evaluation/harmonization until a distinct HR-approved standard and extraction path exist.

### High

5. Manual batch choreography. Stage dependencies live across Make targets and long Compose comments; run state, retry, progress, manifests, and recovery are inconsistent.
6. Non-atomic database-to-queue handoff. A task may commit before enqueue, leaving stranded pending work. A transactional outbox and idempotent dispatcher are needed.
7. Incomplete data-version provenance. Extractor version, logical source version/current state, and complete downstream manifests are missing.
8. Audit hardening. Hash chaining detects mutation but database privileges do not yet prevent it; pre-chain history is outside the chain.
9. Thin observability. No clear SLOs, dependency readiness, queue-age metrics, correlation IDs, model fallback/latency telemetry, or pipeline-stage monitoring.
10. Governance-sensitive harmonization. Maximum requirement selection, security unions, context dropping, duty thresholds, and title selection can materially change a role.

### Medium

11. API composition debt: `api.main` owns app state, sessions, legacy endpoints, and router wiring; late imports conceal a circular dependency.
12. Dual-purpose Neo4j shares infrastructure and credentials between agent memory and HR retrieval.
13. Renderer/parser round-trip is lossy; exported documents should not be treated as a stable re-import format without a canonical serialization contract.
14. Health endpoint reports success without checking dependencies.
15. Live-model tests can self-skip on reachability errors and therefore do not function as operational canaries.
16. Tests prove deterministic consistency more strongly than HR validity, fairness, usability, or usefulness.
17. Deployment lacks an explicit production overlay, pinned artifacts/digests, backup/restore evidence, retention policy, and disaster-recovery drills.

## Target architecture direction

The next architecture should preserve the current deterministic/human-governed core while adding four explicit planes:

1. Experience plane: author, reviewer, administrator, and operator journeys with complete RBAC and author-visible status.
2. Decision plane: one versioned evaluation service, ratified policy bundles, decision provenance, override governance, and HR calibration evidence.
3. Processing plane: a durable pipeline-run state machine with idempotent stages, outbox dispatch, manifests, checkpoints, and observable degradation.
4. Data plane: PostgreSQL authoritative ledger, isolated derived retrieval stores, explicit source/version identities, rebuildable indices, least-privilege access, and retention/backup controls.

```text
CAS / session identity
        |
API gateway + uniform RBAC + server-derived actor
        |
+-------+----------------------+----------------------+
| Author experience           | Reviewer experience  | Admin/operator
| draft/status/history         | evidence/decision    | users/runs/policy
+---------------+-------------+----------+-----------+
                |                        |
       Versioned decision service        |
       deterministic rules + gates <-----+
                |
       Canonical/version ledger (PG)
                |
       outbox -> durable pipeline runs
                |
 ingest -> parse -> retrieve -> dedup -> cluster -> harmonize
                |
     derived Neo4j indices + internal LLM
```

## Recommended sequencing

- P0: complete authorization/server-derived identity; add production startup invariants; begin HR ratification; explicitly block unsupported WJQ decisions.
- P1: add a durable pipeline run ledger/outbox; full version manifests; readiness/metrics; author submission/status repair; HR-adjudicated benchmark.
- P2: improve WJQ extraction, token-aware retrieval and candidate scalability; harden audit/storage privileges; create production deployment/DR controls.
- P3: refactor the composition root and domain/adapters, isolate Neo4j workloads, formalize canonical serialization, and archive superseded measurements.

## HR discussion and approval register

The detailed 197-item register should remain the source of individual IDs. For an HR workshop, group decisions into these approval packages:

1. Approval authority: score/grade/severity floors, named blocking rules, non-waivable rules, who can override, reason quality, and segregation of author/reviewer duties.
2. Scoring meaning: severity costs, repeated-issue decay, grade bands, whether a score is appropriate for HR-facing use, and whether score/grade duplicate gate logic.
3. Template interpretation: summary range, duty count and allocation, required sections, exact boilerplate/current wording, and template-era handling.
4. Qualifications: ordering, equivalency wording variants, required degree/relevant-field patterns, wish-list phrases, ability prefixes, and waiver policy.
5. Inclusive language: approved lexicon, context/exceptions, replacement guidance, severity, and ongoing EDI/legal review.
6. Titles/classification signals: reserved titles, seniority families, supervision rules, Hay-like signals, and a clear disclaimer that signals are not formal classification.
7. Similarity and clustering: operational meaning of exact/near/role-equivalent, thresholds/weights, cross-group and cross-department review, and use of similarity in authoring.
8. Harmonization: title/summary selection, duty prevalence, dropped context, security union, and whether maximum education/experience is allowed to raise requirements.
9. AI policy: permitted models/infrastructure, prompt/model provenance, fallback behavior, human acceptance, advisory-only audit, retention, transparency, and monitoring.
10. Scope: APSA/APEX/Polytechnic only versus commissioning a separate CUPE/WJQ standard.
11. Publication/integration: what “published” authorizes, grade/classification ownership, HRIS/export authority, retention, audit visibility, and source-JD access.
12. Acceptance evidence: pilot cohort, benchmark labels, false-positive/negative tolerances, fairness slices, accessibility standard, and revalidation frequency.

## Bottom line

The architecture has the right safety centre: deterministic evidence, traceable drafts, and accountable human publication. The next phase should not add more intelligence before it adds authority, measurement, and operability. Ratify the rules, protect every API path, prove performance on an HR-adjudicated benchmark, and make every pipeline run observable and reproducible. Those changes turn a sophisticated pilot into a trustworthy HR service.


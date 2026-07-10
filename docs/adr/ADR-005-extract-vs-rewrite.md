# ADR-005: Extract vs. Rewrite Strategy for hris JD Modules

**Status:** Proposed — human approves before Phase 1
**Date:** 2026-07-10
**Source:** `docs/audit/hris-reuse-map.md` (Phase 0 task 0.1)

## Context

JD Bank is spun off from the JD subsystem inside `C:\repos\hris` (`recruiter-assistant`).
Contrary to the earlier plan assumption that hris only sketched TypeScript interfaces, the
JD logic is **fully implemented in Python 3.12 / pydantic v2**, with a clean split between
**pure deterministic logic** (`packages/pipeline/**`, `packages/schemas/**` — heavily
unit-tested, no I/O) and **coupled orchestration/persistence** (`apps/api/services/**`,
`apps/worker/**` — wired to Neo4j + Postgres + hris's own DB schema).

**Architecture (per inherited ADR-002 — corrected 2026-07-10):** JD Bank **retains Neo4j**
as its vector index (768-dim cosine, `nomic-embed-text`) + graph store, uses **Postgres for
all relational/transactional SQL**, and **arq/Redis** for queues. **There is no pgvector.**
An earlier draft of this ADR wrongly assumed a pgvector re-host (picked up from a stale
stack line in HANDOFF/plan that contradicted ADR-002); that is reversed here.

Because Neo4j is retained, the vector store is **not** a rewrite driver — hris's Neo4j
recall Cypher is an asset to port. What pushes the high-coupling modules to REWRITE is
coupling to hris's *own* graph model (Job nodes, skill graph) and relational schema
(identity/jobs tables); the pure packages remain near-verbatim EXTRACT ports.

This ADR records the per-module verdict, rationale, and a rough effort estimate. It is the
input contract for Phase 1+ build sequencing.

## Decision (per-module verdict table)

Effort scale: **S** ≤ ½ day · **M** ~1–2 days · **L** ~3–5 days (port + tests + gates green).

| # | Module | Verdict | Rationale | Effort |
|---|---|---|---|---|
| 1 | `schemas/sfu_jd.py` (`SFUJobDescription`) | EXTRACT | The ParsedJD contract; pure pydantic, near-copy port | S |
| 2 | `schemas/jd_quality.py` | EXTRACT | Maps 1:1 to plan `ValidationIssue`; rename fields on port | S |
| 3 | `schemas/jd_bank.py` | EXTRACT | Value objects reusable; trim hris-persistence fields | M |
| 4 | `pipeline/quality/jd_rules.py` ⭐ | EXTRACT | Deterministic SFU gate engine, thoroughly tested; **externalize data tables to YAML on port** | L |
| 5 | `pipeline/quality/rule_catalog.py` | EXTRACT | rule_id → section traceability spine; pairs with #4 | S |
| 6 | `pipeline/bank/similarity.py` | EXTRACT | Pure Tier-3 scorer; takes a plain cosine float from Neo4j's vector index (ADR-002) — no store change | M |
| 7 | `pipeline/bank/clustering.py` | EXTRACT | Union-find core; **add employee-group/level constraints + diameter cap** | M |
| 8 | `pipeline/bank/title_family.py` | EXTRACT | Encodes rulebook Part 3 title rules | S |
| 9 | `pipeline/bank/hay_signals.py` | EXTRACT | Clean, advisory-only; low priority (Phase 7) | S |
| 10 | `pipeline/bank/drift.py` | EXTRACT | Pure posting-vs-canonical drift; feeds review queue | S |
| 11 | `pipeline/bank/provenance.py` | EXTRACT | Tiny skill-frequency helper for harmonization | S |
| 12 | `pipeline/bank/render.py` | EXTRACT | ParsedJD → text; composer start-from-canonical | S |
| 13 | `pipeline/bank/export.py` | EXTRACT | DOCX/PDF + footer constants; **verify territorial-ack wording, add SFU styling** | M |
| 14 | `pipeline/parsing/extract.py` | EXTRACT | Robust multi-format text extraction; NUL-scrub | M |
| 15 | `pipeline/parsing/chunk.py` | REWRITE | Résumé-shaped; JD Bank needs SFU-template section segmenter | M |
| 16 | prompt `sfu_jd_extract_v1` | EXTRACT | Defines ParsedJD JSON contract; golden-tested | S |
| 17 | prompt `jd_harmonize_v1` | EXTRACT | Cluster→canonical merge prompt (prompt only; see gap #3) | S |
| 18 | prompt `jd_quality_v1` | EXTRACT | Nuanced cited LLM quality pass | S |
| 19 | prompt `jd_extract_v1` | DISCARD | Matching-only skill extract; superseded by #16 | — |
| 20 | `worker/jd_quality_task.py` | REWRITE | arq/asyncpg-coupled; **port anti-fabrication merge guard** | M |
| 21 | `worker/jd_bank_task.py` | REWRITE | High coupling (arq, PG, Neo4j); rebuild on JD Bank queue | M |
| 22 | `api/services/jd_bank_service.py` (1170 L) | REWRITE | Neo4j recall Cypher is directly reusable (Neo4j retained); rewrite is re-wiring to hris's own Job-node/skill-graph model + tables, not a store swap; algorithms already extracted (#6–11). Keep 1124-L test as behavioral reference | M–L |
| 23 | `api/services/jd_quality_service.py` | REWRITE | Append-only PG persistence tied to hris tables | M |
| 24 | `api/services/jd_import_service.py` | EXTRACT | Thin wrapper over #14; composer upload path | S |
| 25 | `api/services/redaction.py` | REWRITE | Repurpose name/contact primitives into `jd_core/scrub`; drop résumé-specific logic | M |
| 26 | `api/services/pii.py` | DISCARD | pgcrypto résumé-email encryption; not JD-related | — |
| 27 | `api/routes/jd_bank.py` + `routes/jd_quality.py` | REWRITE | API-shape reference for JD Bank's own FastAPI app | M |
| 28 | `pipeline/sources/taleo.py` (692 L) | DISCARD | Live careers-site scraper; JD Bank ingests a fixed archive | — |
| 29 | migrations `0016–0024` | REWRITE | Schema reference for JD Bank tables; not directly runnable | M |
| 30 | `docs/jd-harmonizer/` reference docs | EXTRACT | Source-gated rulebook→constant provenance; travels with #4 | S |
| — | `apps/web/lib/schemas/*.ts` | DISCARD | zod frontend mirrors; API-contract reference only | — |

**Tally:** EXTRACT 16 · REWRITE-FROM-SPEC 8 · DISCARD 4.

## Consequences

- **Phase 1 fast-start:** the ParsedJD contract (#1), quality engine (#4/#5), and extractors
  (#14) are near-verbatim ports — the foundation lands quickly.
- **Externalization work is real:** #4's rulebook data (verb glossary, coded-term lexicon,
  thresholds, grade bands) must be lifted from Python literals into versioned YAML under
  `src/jd_core/rules/` to satisfy the rules-as-data invariant. Do not skip this to save time.
- **Three genuine build-new gaps** (not in hris, must be written fresh):
  1. Dedup **Tier-1 (SHA-256 exact)** and **Tier-2 (MinHash/5-gram near-dup)** — Phase 3.
  2. **Deterministic LLM-free harmonization merge engine** — Phase 4 (hris only has a prompt).
  3. **Incumbent-name PII scrub** for JD ingestion — Phase 1 (assemble from #25 primitives).
- **No store migration:** Neo4j is retained (ADR-002), so the pure scorers keep taking plain
  cosine floats from the Neo4j vector index and hris's recall Cypher ports directly. The
  service-layer "rewrites" (#20–23, #27) are re-wiring to JD Bank's own graph/table model,
  not a swap to a new vector store — lower risk than the earlier pgvector framing implied.
- **Port the tests too:** ~3,000 lines of hris JD unit/integration tests are a reusable
  behavioral spec; porting the pure-module unit tests alongside the code preserves the
  rulebook-as-tests guarantee.

## Alternatives Considered

- **Rewrite everything from the rulebook spec, ignore hris code:** clean-room, but discards
  ~3,000 lines of tested, spec-faithful Python for no benefit; rejected.
- **Extract the service layer as-is (adopt hris's Job-node model wholesale):** keeps Neo4j
  (which is correct) but drags in hris's identity/jobs schema and app wiring that JD Bank
  does not need; rejected in favour of adapting the recall Cypher to JD Bank's own model.

## Open questions for the human reviewer

1. ~~Confirm the pgvector/Neo4j-deferral decision~~ — **RESOLVED 2026-07-10:** Neo4j is
   retained for vectors + graph, Postgres for all SQL, arq/Redis for queues, no pgvector
   (aligns with inherited ADR-002). Verdicts above reflect this.
2. Approve the effort estimates as Phase 1+ sequencing input, or request re-scoping.
3. Confirm the crown-jewel `jd_rules.py` (#4) should be ported **with** data externalized to
   YAML in the same phase, rather than as a follow-up.

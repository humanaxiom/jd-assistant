# JD Bank — Session Handoff

Read this first every session. Single source of truth for current state + how we work.
Last updated: 2026-07-10 (end of Phase 1).

Repo: **`C:\repos\JD-Assistant`** → GitHub **github.com/humanaxiom/jd-assistant**.

---

## Current state — Phase 1 COMPLETE ✅

The archive can flow end to end: **file → ingest (hash, extract text, scrub incumbent names)
→ `source_documents` → deterministic parse → `parsed_jds`**. All on `main`, all Docker-only,
all gate-green. Merged via PRs #1–#4.

| Phase | Landed | Location |
|---|---|---|
| 1.1 | ParsedJD + quality schemas (faithful hris port) | `core/src/jd_core/models/{parsed_jd,quality}.py` |
| 1.2 | 8-table Postgres schema + async Alembic + Neo4j vector indexes | `core/src/jd_bank/db/models.py`, `core/alembic/`, `core/db/migrations/002_jd_vectors.cypher` |
| 1.3 | Ingestion: multi-format extract (+antiword `.doc`) + incumbent-name scrub + store | `core/src/jd_bank/ingest/{extract,scrub,ingest}.py` |
| 1.4 | Deterministic template-tolerant parser/segmenter, honest per-section confidence | `core/src/jd_core/parser/{headings,segmenter,store}.py` |

8 tables: `source_documents, parsed_jds, validation_reports, dedup_edges, clusters,
canonical_jds, review_actions, audit_log` (+ harness `tasks/runs/gate_results`), all in the
single Alembic baseline `core/alembic/versions/0001_initial_schema.py`.

---

## How we work (KEEP DOING THIS — subagent flow)

Delegate implementation to subagents so the orchestrator's context stays lean. Per task:

1. **Tester+Coder subagent** (general-purpose): strict TDD (failing tests first → implement →
   `make gates` green in Docker), leaves changes uncommitted, reports a tight summary.
2. **Reviewer subagent** (merge-blocking): independently re-runs `make gates`, checks
   scope/port-fidelity/quality, returns APPROVED / CHANGES REQUIRED. **Add a Security lens**
   when the diff touches subprocess / file I/O / untrusted input / auth / network.
3. **Orchestrator (you)**: on APPROVED, commit → push branch → open PR → watch CI → merge
   (rebase). Route any must-fix back to the coder subagent (SendMessage continues it with its
   context) before PR. Keep briefs precise (paths, constraints, "don't commit").

Branch per task: `agent/pN.M-slug`. PRs rebase-merge to `main`. **User said: this is a brand-new
project — merge green, reviewed PRs without waiting** (offer a hold-for-review off-ramp).

---

## Non-negotiables (enforced)

- **Docker-only (ADR-006):** NO host Python/venv/pip. All code/tests/gates/migrations run in
  containers. `make gates` runs the FULL suite (ruff·black·mypy--strict·unit·integration·
  coverage≥80) in the one-shot `gates` compose service — self-contained, CI-identical. Only
  Ollama runs on host metal. Commands: `make gates` / `gates-fast` / `migrate` / `hook-install`.
- **Storage (ADR-002):** Neo4j = vectors (768-dim cosine, `nomic-embed-text`) + graph;
  Postgres = all relational/transactional SQL; Redis+arq = queue. **NO pgvector.**
- **Rulebook as tests / as data:** every SFU gate = a failing-fixture + passing-fixture test;
  gates/verb-lists/lexicons live in versioned YAML under `jd_core/rules/` (Phase 2), never
  hardcoded. Validator is the oracle (assert post-state, never verbatim LLM text).
- **Human approval:** canonical JDs are drafts until an HR reviewer approves; nothing auto-publishes.
- **Local-first / job-not-person:** Ollama only; incumbent names normalized out of canonical JDs
  as a RULEBOOK quality step — NOT a resume-grade privacy gate (these are JDs, not resumes).
- **Claude-only:** the Codex/Copilot harness layers were removed. Don't reintroduce them, pgvector,
  or `make use-*`.

---

## Gotchas learned (save yourself the pain)

- **The `gates` container mounts only `./core` at `/app`.** Tests must be self-contained under
  `core/tests/`; put fixtures in `core/tests/fixtures/` (repo-root `fixtures/golden/` and
  `docs/rulebook/` are NOT visible in the container). Encode rulebook-derived data (e.g. parser
  heading patterns) as code/data under `core/`, not by reading the rulebook at runtime.
- **testcontainers work in the `gates` service** (Docker socket mounted in compose +
  `TESTCONTAINERS_HOST_OVERRIDE=host.docker.internal` + `TESTCONTAINERS_RYUK_DISABLED=true`).
  Integration tests can `command.upgrade(cfg,"head")` the real Alembic migration against a fresh PG.
- **The upstream harness shipped NOT gate-green** — we fixed ruff/black/mypy, brought coverage
  57%→94%, stood up Alembic, and Docker-ized CI. Expect to fix upstream gaps, not assume clean.
- **`.gitattributes`** forces LF (so container shell scripts survive Windows) and marks binary
  fixtures (`*.doc` etc.) — don't let CRLF/text filters corrupt binaries.
- Deferred deps are OK when a task needs them (1.3 added antiword + python-docx + striprtf); most
  tasks should add NONE (tell the subagent to STOP + report if it thinks it needs a dep).
- `hris` (`C:\repos\hris`) is READ-ONLY reference for ports. `agent-harnesses-v2` is the live
  upstream harness this repo vendors (ADR-004). `C:\repos\jdbank` is STALE — ignore it.

---

## Next: Phase 2 — Validation engine (rulebook-as-code)

The heart of the system. Tasks (see `docs/plan.md` §3 Phase 2):
- **2.1** Rules-as-data: externalize hris `jd_rules.py` tables (verb glossary, gender-coded
  lexicon, modifiers, restricted titles, thresholds, grade bands) into versioned YAML under
  `core/src/jd_core/rules/`, loaded not hardcoded. Carry `docs/jd-harmonizer/sfu-reference.md`
  (reuse map #30) as provenance.
- **2.2** Section validators = port hris `jd_rules.py` (#4, the crown jewel) + `rule_catalog.py`
  (#5) → emit `ValidationIssue{code, severity, section, evidence, recommendation}`.
- **2.3** Gate runner: "never approve if…" → boolean + reasons. **Every gate: a failing-fixture
  AND a passing-fixture test.**
- **2.4** Land the EXTRACT modules per ADR-005; keep hris tests as the behavioral spec.
- **2.5** Archive baseline: run the validator over the parsed archive → quality dashboard data.

hris sources (read-only): `C:\repos\hris\packages\pipeline\src\pipeline\quality\{jd_rules,rule_catalog}.py`.

## Backlog (small follow-ups — fold into a cleanup PR)

- Tighten the legacy-`.doc` E2E test confidence upper bound (make "no false-high" explicit).
- Guard bare single-word heading patterns in `parser/headings.py`.
- docx zip-ratio (decompression-bomb) guard in `ingest/extract.py`.
- Wire the arq `run_ingest` worker task (ingestion orchestration; `ingest_document` is ready).

---

## Authoritative references

- `docs/plan.md` — full build plan, architecture, phase breakdown (current).
- `docs/adr/` — ADR-002 (PG/Neo4j), 003 (Ollama), 004 (repo placement), 005 (extract-vs-rewrite,
  Accepted), 006 (Docker-only).
- `docs/audit/hris-reuse-map.md` (16 EXTRACT / 8 REWRITE / 4 DISCARD) + `archive-census.md`.
- `docs/rulebook/sfu-jd-standards.txt` — the rulebook (Part 2 = new template, Part 8 = old).
- `DEVELOPER_GUIDE_1.md` — onboarding + Docker-only workflow. `CLAUDE.md` — project invariants.
- Persistent memories auto-load each session (storage-architecture, docker-only-execution,
  harness-upstream-subagents, jd-incumbent-names-not-pii, subagent-workflow).

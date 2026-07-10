# JD Bank — Project Status & Session Bootstrap

Read this at the start of every Claude Code session. It is the single source of truth for
current state, resolved decisions, and what to do next.

Authoritative references (read before acting):
- `DEVELOPER_GUIDE_1.md` — onboarding + workflow (Docker-only, subagent pipeline, gates)
- `docs/adr/ADR-006-docker-only-execution.md` — NO host Python; everything runs in Docker
- `docs/plan.md` — full build plan, architecture, phase breakdown
- `docs/rulebook/sfu-jd-standards.txt` — machine-readable SFU JD rulebook
- `docs/rulebook/jd-authoring-guide.docx` — human-readable companion
- `docs/rulebook/recruiter-assistant-spec.docx` — ParsedJD contract, governance model

Harness reference:
- `C:\repos\agent-harnesses-v2\harness-claude-code\CLAUDE.md` — base Claude Code rules
  (gates, git workflow, TDD order, code rules). Those rules apply here too. Read them.
- `C:\repos\agent-harnesses-v2\docs\adr\` — ADR-002 (Postgres/Neo4j split) and ADR-003
  (offline Ollama) are inherited decisions. Do not re-open them.

---

## Session start checklist

Before writing any code each session:

1. `docker compose ps` — stack must be healthy (api, worker, postgres, neo4j, redis)
2. `/memory-query <task description>` — search Neo4j for prior work on this task before implementing
3. Read the relevant ADR(s) in `docs/adr/`
4. Confirm you are on a feature branch, not `main`

---

## Current state

| Area | Status |
|---|---|
| Repo | `C:\repos\JD-Assistant` — standalone project repo, v2 harness conventions (ADR-004). `C:\repos\jdbank` is STALE (abandoned v1 attempt) |
| Harness | `C:\repos\agent-harnesses-v2` — Python-only, v2; live upstream. This repo vendors a copy of it; **subagents subsystem reconciled from upstream 2026-07-10** |
| Plan | `docs/plan.md` ✅ reviewed + updated post-Phase-0 (storage arch corrected, findings folded in) |
| Rulebook | `docs/rulebook/` ✅ all 3 files present |
| CLAUDE.md | root `CLAUDE.md` — jd-bank project invariants (installed Phase 0 task 0.5) |
| Phase 0 | ✅ **COMPLETE** — awaiting human sign-off (ADR-005 approval) |
| Phase 1+ | Ready once Phase 0 signed off |
| External source | `C:\repos\hris` — read-only in Phase 0 |
| JD archive | `C:\repos\hris\fixtures\SFU_JDs` — golden dataset |

---

## Resolved decisions

**Harness:** v2 at `C:\repos\agent-harnesses-v2`. Python-only. The TypeScript scaffold
inherited from v1 (`src/agents/`, `package.json`, `jest.config`, `.eslintrc`) is orphaned
and should be cleaned up — but do not do it mid-task. Schedule as a chore branch.

**Language:** Python 3.11+ only. No TypeScript in application code.

**Repo placement (ADR-004):** `C:\repos\jdbank` is the standalone project repo. It adopts
v2 harness conventions (gates, docker, code rules) without being a sub-folder of the harness
mono-repo. ADR-004 should record this formally in Phase 0.

**Infrastructure:** Docker Compose runs Postgres, Neo4j, Redis, and the API/worker.
Ollama runs on host metal at `host.docker.internal:11434/v1`. Never add cloud API calls.

**Neo4j — two distinct roles (do not conflate):**
- *Harness memory layer (day 1):* Neo4j stores agent lineage graph and vector-indexed
  artifacts from every session. The `/memory-query` slash command searches it.
  This is inherited from v2 and is active immediately via `docker compose up`.
- *JD Bank domain use (Phase 7, deferred):* a role/duty overlap graph for org-design
  queries. This is NOT in the MVP. Do not add it to the critical path.

**Extract-vs-rewrite (ADR-005):** Derived in Phase 0 from the hris reuse map. Placeholder.

**Human approval invariant:** Canonical JDs are drafts until an HR reviewer explicitly
approves. Nothing auto-publishes. Gate overrides require a written reason.

**FIPPA / local-first:** JD content never leaves this machine. Ollama only. PII scrubbed
at ingestion.

---

## V2 harness conventions (apply everywhere)

### Gates — non-negotiable

```bash
make gates        # full suite — run before every commit
make gates-fast   # pre-commit subset (no integration tests)
```

Gates: **ruff · black · mypy --strict · pytest unit · pytest integration · coverage ≥ 80% · branch-name**

A single red gate = the work is not done. Iterate until all green.
Max 5 self-iterations; if still red, stop and report to the human — never weaken a test or
lower the coverage floor to get green.

### Git workflow

```
git checkout -b agent/<task-id>-<slug>   # or feat|fix|chore/<slug>
# commit sequence: red: failing tests → green: implementation → refactor/docs
```

Never commit to `main`. Open a PR only when `make gates` is fully green locally.

### TDD order

1. Write failing tests first (`tests/unit/`, `tests/integration/`)
2. Run — confirm RED
3. Implement minimally until GREEN
4. Refactor with gates still green
5. Update `docs/adr/` if architecture changed

### Code rules

- Full type hints; `mypy --strict` clean; no unjustified `# type: ignore`
- Async everywhere (SQLAlchemy async, neo4j async driver, httpx)
- Config only via `src/settings.py` (pydantic-settings) — never `os.environ` scattered in code
- Postgres for transactional/relational data; Neo4j only for graph + vector; Redis only as arq broker
- All model calls via OpenAI-compatible client with `base_url=settings.ollama_base_url`
- Never modify a test to make the implementation pass (only if provably wrong — say so)

### Slash commands

| Command | Purpose |
|---|---|
| `/gates` | Run full gate suite, report results table |
| `/review-loop <task>` | Iterate-until-green on current branch |
| `/memory-query <text>` | Vector-search Neo4j for similar prior artifacts before implementing |

---

## Phase 0 — Discovery & audit (start here)

No production code. Documents, ADRs, and fixtures only.
Branch: `agent/p0-<task-slug>`. Commit after each task with prefix `jd-bank[p0]:`.
Stop after task 0.5 and present the Phase 0 summary for human review.

### 0.1 — hris reuse map
Output: `docs/audit/hris-reuse-map.md`

Walk `C:\repos\hris` (read-only). Inventory every JD-related module. For each:
- File path(s), language (spec sketched TS interfaces — verify what was actually built)
- Test coverage, coupling to hris internals
- Verdict: **EXTRACT** / **REWRITE-FROM-SPEC** / **DISCARD** + one-line rationale

### 0.2 — Archive census
Output: `docs/audit/archive-census.md` + `fixtures/golden/` (30–50 stratified docs)

Walk `C:\repos\hris\fixtures\SFU_JDs`. Report: file counts by format, template era (old vs
new — heading conventions in `sfu-jd-standards.txt` identify them), parse-ability sample,
PII incidence (rate only — no PII in the report), obvious duplicate rate. Copy a stratified
sample into `fixtures/golden/`.

### 0.3 — Label set scaffold
Output: `fixtures/labels/pairs.csv`

~100 doc pairs from the census, stratified across: exact-dup / near-dup / same-role /
different. Columns: `doc_a`, `doc_b`, `best_guess_label`, `confidence`, `notes`.
Human will hand-verify before Tier 2/3 tuning.

### 0.4 — ADRs
Output: `docs/adr/ADR-004-repo-placement.md`, `docs/adr/ADR-005-extract-vs-rewrite.md`

ADRs 002 and 003 are inherited from v2 harness. JD Bank ADRs start at 004.
Use `docs/adr/001-tdd-agent-strategy.md` (already in repo) as format template.

**ADR-004 — Repo placement:** Record that `C:\repos\jdbank` is a standalone project repo
adopting v2 harness conventions; not a sub-folder of the harness. Mark ACCEPTED.

**ADR-005 — Extract vs. rewrite:** One row per hris module from 0.1; verdict + rationale +
estimated effort. Mark PROPOSED — human approves before Phase 1.

### 0.5 — Install project CLAUDE.md
Output: `CLAUDE.md` at repo root

The existing `.claude/CLAUDE.md` carries v1 TypeScript defaults — it is superseded.
Install the project CLAUDE.md below at the repo root so every future session picks it up.

```markdown
# jd-bank — project invariants

## What this is
JD Bank: dedup + harmonization + composer over the SFU JD archive.
Repo: C:\repos\jdbank. Harness: C:\repos\agent-harnesses-v2 (v2, Python-only).
Plan: docs/plan.md. Rulebook: docs/rulebook/sfu-jd-standards.txt.

## Read on every session
C:\repos\agent-harnesses-v2\harness-claude-code\CLAUDE.md — base harness rules apply here.

## Non-negotiables
1. HUMAN APPROVAL: canonical JDs are drafts until an HR reviewer explicitly approves.
   Nothing auto-publishes. Gate overrides require a written reason in the audit log.
2. RULEBOOK AS DATA: gates, word lists, verb lists, KSA modifiers, restricted titles
   live in versioned YAML/JSON under src/jd_core/rules/ — never hardcoded in logic.
3. VALIDATOR AS ORACLE: tests on LLM-touching code assert validator post-state,
   never verbatim model text.
4. TDD + GATES: failing test first. Every rulebook gate has a failing-fixture test and
   a passing-fixture test. make gates must be green before any commit.
5. LOCAL-FIRST / FIPPA: inference via Ollama only. JD content never leaves this machine.
   PII (incumbent names) scrubbed at ingestion.
6. PROVENANCE: every canonical JD traces to sources, cluster, validation reports, and
   reviewer actions. Audit log is append-only.
7. FIXTURES ARE SACRED: fixtures/golden/ and fixtures/labels/ change only via reviewed
   PRs. Every pilot bug becomes a regression fixture.

## Neo4j — two roles, do not conflate
- Harness agent memory (day 1, via docker compose): lineage graph + vector artifact store.
  Query with /memory-query before implementing anything.
- JD Bank domain use (Phase 7, deferred): role/duty overlap graph. NOT in MVP.

## External read-only paths
- C:\repos\hris — extract modules from here; never modify
- C:\repos\hris\fixtures\SFU_JDs — JD archive; read-only during Phase 0

## Known open flags
- Territorial acknowledgement wording: verify against SFU's current official text before
  any external distribution. Phase 6 sign-off task — blocks publish, not development.
- Footer wording lives in a single config constant — never inline it.
- TS scaffold (src/agents/, package.json, etc.) is orphaned v1 artefact — clean up on a
  chore branch, not mid-feature.

## Stack
Python 3.11+ · FastAPI · PostgreSQL 16 (all SQL) · Neo4j (vectors 768-dim cosine + graph) · Redis + arq (queues) · Ollama · pytest / ruff / black / mypy --strict
(NOTE: an earlier draft said "PostgreSQL 16 + pgvector" — that was wrong and contradicted ADR-002. No pgvector; vectors live in Neo4j. See ADR-005 §Architecture.)
Infrastructure: docker compose (postgres, neo4j, redis, api, worker) + Ollama on host metal
```

---

## Phase 0 exit criteria (human review gate)

- [ ] `docs/audit/hris-reuse-map.md` — approved
- [ ] `docs/audit/archive-census.md` — reviewed
- [ ] `fixtures/golden/` — 30–50 stratified docs committed
- [ ] `fixtures/labels/pairs.csv` — pre-filled, awaiting human verification
- [ ] `docs/adr/ADR-004-repo-placement.md` — ACCEPTED
- [ ] `docs/adr/ADR-005-extract-vs-rewrite.md` — PROPOSED, awaiting approval
- [ ] `CLAUDE.md` at repo root — installed

Print Phase 0 summary when all outputs exist. **Do not begin Phase 1 until the human says go.**

---

## Phase roadmap (see docs/plan.md §3 for full task breakdown)

| Phase | What | Key output |
|---|---|---|
| 0 | Discovery & audit | Reuse map, census, ADRs, golden fixtures, labels |
| 1 | Foundation | `ParsedJD` schema, DB migrations, ingest worker, parser |
| 2 | Validation engine | Rulebook-as-data, section validators, gate runner, baseline report |
| 3 | Dedup & clustering | Tier 1–3 dedup, embeddings (Neo4j vector index), cluster report |
| 4 | Harmonization & review | Merge engine, LLM rewrite passes, review queue UI, pilot |
| 5 | JD Composer | Search API, guided authoring, live validation, export |
| 6 | Hardening & handover | Auth, ops docs, territorial acknowledgement sign-off |
| 7 | Optional | Neo4j domain graph, Hay summaries, M365 surfacing |

---

## Orphaned v1 artefacts (clean up on a chore branch, not mid-feature)

These files are from the v1 TypeScript harness and serve no purpose in v2:

- `src/` (entire folder — TypeScript agent stubs)
- `package.json`, `package-lock.json` (if present)
- `.eslintrc*`, `tsconfig.json`, `jest.config*` (if present)
- `.claude/CLAUDE.md` — superseded by `CLAUDE.md` at repo root (installed in Phase 0 task 0.5)

Do not delete them mid-task. One clean-up commit on `chore/remove-v1-ts-scaffold`.

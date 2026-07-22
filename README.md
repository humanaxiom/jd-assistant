# JD Bank

> Dedup + harmonization + composer over the SFU Job Description archive. Offline-first Python
> stack (FastAPI · Neo4j · Postgres · Redis/arq · Flask) driven by AI subagents through
> **Claude Code**. Inference runs on **Ollama on bare metal**; **everything else runs in Docker**.

Built on the v2 agent harness (upstream `C:\repos\agent-harnesses-v2`, vendored here — ADR-004).

**Start here:** [`DEVELOPER_GUIDE_1.md`](DEVELOPER_GUIDE_1.md) (onboarding + workflow) ·
[`docs/plan.md`](docs/plan.md) (build plan) · [`CLAUDE.md`](CLAUDE.md) (project invariants) ·
[`docs/adr/`](docs/adr/) (decisions).

---

## System architecture

```mermaid
graph TB
    subgraph Metal["🔩 Bare Metal (Host)"]
        OL[Ollama<br/>:11434]
    end
    subgraph Docker["🐳 Docker Compose"]
        subgraph AppTier["App Tier"]
            API[FastAPI<br/>:8000]
            FE[Flask Frontend<br/>:5000]
            WK[arq Worker]
        end
        subgraph DataTier["Data Tier"]
            PG[(PostgreSQL<br/>all SQL)]
            NEO[(Neo4j<br/>graph + vectors)]
            RD[(Redis<br/>arq queue)]
        end
    end
    FE -->|REST| API
    API --> PG
    API --> NEO
    API -->|enqueue| RD
    WK -->|dequeue| RD
    WK --> PG & NEO
    API & WK -->|host.docker.internal:11434| OL
    style Metal fill:#2D3436,color:#fff
    style AppTier fill:#1F6FEB,color:#fff
    style DataTier fill:#F59F00,color:#fff
```

**Storage (ADR-002):** PostgreSQL = all relational/transactional data; Neo4j = graph memory +
vector index (768-dim cosine, `nomic-embed-text`) — JD embeddings live here, **not** pgvector;
Redis = arq queue.

---

## Subagent pipeline

**planner → tester → coder(loop) → reviewer + security → docs**, implemented in
`core/src/agents/` and driven by Claude Code (`harness-claude-code/.claude/agents/`).

| Subagent | Python class | Claude Code def |
|---|---|---|
| Planner | `PlannerAgent` — JSON plan, TDD-order validated | `planner.md` |
| Tester | `TesterAgent` — failing tests only, `tests/` allowlist | `tester.md` |
| Coder | `CoderAgent` in `ReviewLoop` — iterate ≤5 then escalate | `coder.md` |
| Reviewer | `ReviewerAgent` — severity findings, **merge-blocking** | `reviewer.md` |
| Security | `SecurityAgent` — injection/secrets/traversal/egress audit, **merge-blocking** | `security.md` |
| Docs | `DocsAgent` — ADR + Mermaid, `docs/` allowlist | `docs.md` |

The **Orchestrator** (`core/src/agents/orchestrator.py`) resolves subtask dependencies
topologically, runs the coder inside the iterate-until-green loop, and hard-blocks on reviewer
rejection or security failure. Runs execute async via arq (`run_pipeline` job) and land lineage
in Neo4j.

```mermaid
sequenceDiagram
    participant O as Orchestrator
    participant P as Planner
    participant T as Tester
    participant C as Coder+ReviewLoop
    participant R as Reviewer
    participant S as Security
    participant D as Docs
    O->>P: task spec
    P-->>O: validated plan (tester before coder)
    O->>T: write failing tests
    T-->>O: RED confirmed
    O->>C: implement
    loop until gates green (max 5)
        C->>C: fix exact failures
    end
    C-->>O: GREEN
    par merge-blocking
        O->>R: review diff
        O->>S: security audit
    end
    R-->>O: APPROVED
    S-->>O: PASS
    O->>D: ADR + diagrams + README
    D-->>O: done → PR
```

---

## Gates (non-negotiable) — Docker-only (ADR-006)

`make gates` runs the full suite in the one-shot `gates` compose service (self-contained,
CI-identical — no host Python):

1. `ruff check` — lint
2. `black --check` — format
3. `mypy --strict` — types (no unjustified `# type: ignore`)
4. `pytest tests/unit` + `pytest tests/integration` (real Postgres + Neo4j via testcontainers)
5. Coverage ≥ **80%** (measured across the full suite)
6. Branch name matches `agent/<task-id>-<slug>` or `feat|fix|chore/<slug>`

A single red gate = the work is not done. Never weaken a test, add an unjustified
`# type: ignore`, or lower the coverage bar to get green.

---

## Git workflow

- Agents work on `agent/*` branches; `main` is protected (PR + green CI + human approval).
- Commit story: `red:` → `green:` → `refactor:` → `docs:`.
- Human approval is invariant: canonical JDs are drafts until an HR reviewer approves.

```mermaid
gitGraph
    commit id: "baseline"
    branch agent/p1-foundation
    commit id: "red: failing tests"
    commit id: "green: implementation"
    commit id: "docs: ADR + diagrams"
    checkout main
    merge agent/p1-foundation tag: "CI green"
```

---

## Repository layout

```
JD-Assistant/
├── core/                          # THE shared application (Python)
│   ├── src/
│   │   ├── jd_core/               # (Phase 1+) parse, validate, bias, titles, KSA, scrub
│   │   ├── jd_bank/               # (Phase 1+) ingest, dedup, cluster, harmonize, review, composer
│   │   ├── api/  agents/  memory/  models/  worker/  gates/   # harness core
│   │   │                          # review UI is server-rendered under api/ (/jd-bank/ui)
│   ├── db/migrations/             # Alembic (Postgres) + Cypher (Neo4j)
│   └── tests/{unit,integration}/
├── harness-claude-code/           # CLAUDE.md base rules + .claude/ (subagents, settings)
├── docs/{adr,audit,rulebook}/  docs/plan.md
├── fixtures/{golden,labels}/      # SFU JD golden sample + dedup label set
├── CLAUDE.md  HANDOFF.md  DEVELOPER_GUIDE_1.md
├── docker-compose.yml  Makefile  .pre-commit-config.yaml
```

---

## Quick start

```bash
# 0. Host prereq: Ollama on metal
OLLAMA_HOST=0.0.0.0 ollama serve &
ollama pull qwen2.5-coder:14b nomic-embed-text

# 1. Bring up the stack (everything but Ollama)
docker compose up -d          # postgres, neo4j, redis, api, worker

# 2. Migrations + git pre-commit hook
make migrate
make hook-install

# 3. Gates (runs in Docker; no host Python)
make gates

# 4. Dashboard → http://localhost:5000   ·   Neo4j → http://localhost:7474
```

Full workflow, first-feature walkthrough, and troubleshooting: [`DEVELOPER_GUIDE_1.md`](DEVELOPER_GUIDE_1.md).

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `OLLAMA_BASE_URL` | `http://host.docker.internal:11434/v1` | Local inference |
| `AGENT_MODEL` | `qwen2.5-coder:14b` | Coding model |
| `EMBED_MODEL` | `nomic-embed-text` | Embeddings for Neo4j vectors |
| `DATABASE_URL` | `postgresql+asyncpg://app:app@postgres:5432/harness` | Postgres |
| `NEO4J_URI` | `bolt://neo4j:7687` | Neo4j |
| `REDIS_URL` | `redis://redis:6379/0` | arq queue |
| `MAX_REVIEW_ITERATIONS` | `5` | Review-loop cap before escalation |
| `COVERAGE_THRESHOLD` | `80` | Gate coverage minimum |

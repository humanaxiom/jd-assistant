# JD Bank

> Dedup + harmonization + composer over the SFU Job Description archive. Offline-first Python
> stack (FastAPI · Neo4j · Postgres · Redis/arq), built with **Claude Code**. Inference runs
> on **Ollama on bare metal**; **everything else runs in Docker**.

Built on the v2 agent harness (upstream `C:\repos\agent-harnesses-v2`, vendored here — ADR-004).

⚠ The harness's **Claude Code subagent definitions are vendored, not installed**, so no
session dispatches them — see [`CLAUDE.md`](CLAUDE.md) § *Two different things are called
"agents" here*. The `core/src/agents/` **`run_pipeline`** pipeline is a separate thing,
and it is live.

**Start here:** 🥇 [`CURRENT.md`](CURRENT.md) — **the authoritative index: where every fact
lives and how to check it** · [`HANDOFF.md`](HANDOFF.md) (state + traps) ·
[`DEVELOPER_GUIDE_1.md`](DEVELOPER_GUIDE_1.md) (onboarding + workflow) ·
[`docs/plan.md`](docs/plan.md) (what we do next) · [`CLAUDE.md`](CLAUDE.md) (invariants) ·
[`docs/FINDINGS.md`](docs/FINDINGS.md) (everything measured) · [`docs/adr/`](docs/adr/).

🥇 **Live counts are at `/jd-bank/ui/funnel`**, computed from the database at request time.
No document here restates them — that is how five wrong numbers once agreed with each other.

New here? [`docs/ORAL-HISTORY.md`](docs/ORAL-HISTORY.md) tells how the project got to where
it is, and why its rules exist.

---

## What it does

SFU's archive of job descriptions — two different forms (APSA/APEX/Poly and the CUPE
Weighted Job Questionnaire), two decades, thousands of near-copies — is parsed,
de-duplicated, clustered into roles, and harmonized into **one draft per role**, each
scored against SFU's published standards by a deterministic validator. A self-hosted model
may reword a draft; it may not invent content. **Nothing publishes without an HR
reviewer.**

What people use, all in the browser behind SFU CAS sign-in (the 📖 Guide in the app,
[`docs/OPERATOR-GUIDE.md`](docs/OPERATOR-GUIDE.md), covers each one):

| | |
|---|---|
| 🏦 **JD Bank** (Library) | Search roles by title, by what the job does, or by PeopleSoft position number; read a role and every archive file it came from |
| 🧱 **Builder** | Write a JD on either form with live compliance feedback; start from an existing role; export SFU's Word template or HR's CUPE form |
| 📄 **Compensation Requisition Form** | SFU's own PDF, filled from a role: title, department, group, request type and position |
| 📋 **Review queue** | Reviewers approve, reject or edit drafts; every action goes to a hash-chained audit log |
| 📈 **Funnel** · collections · units | Where the archive stands, from the database at request time; the IT collection and the VPFA / Facilities rollups |

---

## System architecture

```mermaid
graph TB
    subgraph Metal["🔩 Bare Metal (aria-gb10-2, ADR-003)"]
        OL[Ollama<br/>:11434]
    end
    subgraph Docker["🐳 Docker Compose"]
        subgraph AppTier["App Tier"]
            API[FastAPI + Jinja UI<br/>host :25800]
            WK[arq Worker]
        end
        subgraph DataTier["Data Tier — bound to 127.0.0.1"]
            PG[(PostgreSQL<br/>all SQL · :25432)]
            NEO[(Neo4j<br/>graph + vectors · :25474/:25687)]
            RD[(Redis<br/>arq queue · :25379)]
        end
    end
    API --> PG
    API --> NEO
    API -->|enqueue| RD
    WK -->|dequeue| RD
    WK --> PG & NEO
    API & WK -->|OLLAMA_BASE_URL| OL
    style Metal fill:#2D3436,color:#fff
    style AppTier fill:#1F6FEB,color:#fff
    style DataTier fill:#F59F00,color:#fff
```

> **On the ports and the host, because both were wrong here until 2026-08-14.** This box runs
> many Docker projects, so jd-bank publishes on **25xxx** — never the upstream harness's
> `8000`/`7474`/`5000` defaults. Ollama runs on **`aria-gb10-2`**, a trusted internal host, not
> on the dev box (ADR-003) — `host.docker.internal` has not been the inference target since
> Phase 3.2. And there is **no Flask frontend**: the service, its dependency and its package
> were removed in `3e32103`; the UI is FastAPI + Jinja templates served by `api`. The same
> three errors were corrected in `DEVELOPER_GUIDE_1.md` §3 in an earlier pass, which is how
> they were found here.

**Storage (ADR-002):** PostgreSQL = all relational/transactional data; Neo4j = graph memory +
vector index (768-dim cosine, `nomic-embed-text`) — JD embeddings live here, **not** pgvector;
Redis = arq queue.

---

## Subagent pipeline (inherited from the harness)

**planner → tester → coder(loop) → reviewer + security → docs**, implemented in
`core/src/agents/` as the `run_pipeline` arq job. ⚠ The matching Claude Code definitions in
`harness-claude-code/.claude/agents/` are vendored and **not installed**, so no Claude Code
session dispatches them. Day-to-day work follows the same discipline by hand (see *Git
workflow*).

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

- Code, tests and rules YAML go on a `feat/…`, `fix/…` or `chore/…` branch and a PR; so do
  `HANDOFF.md`, `docs/plan.md`, `docs/decisions/**` and anything that changes how the
  project is built. Most other documentation commits straight to `main`. The exact list is
  [`CLAUDE.md`](CLAUDE.md) § *Change workflow*.
- **A failing test comes first**, and the guard is broken once to prove it can go red.
- 🔴 **Directive #0: nothing merges or deploys until `make smoke` is green** against the live
  Bank — not "green except", not "red for a known reason". `make gates` and CI run on
  fixtures and cannot see the live system.
- A rulebook change ships with its register entry and the regenerated register
  (`make register`); a guide change with its re-render (`make guide`).
- **The project owner merges.**
- Human approval is invariant: canonical JDs are drafts until an HR reviewer approves.

```mermaid
gitGraph
    commit id: "main"
    branch feat/a-change
    commit id: "test: failing first"
    commit id: "feat: make it pass"
    commit id: "test(smoke): live check"
    checkout main
    merge feat/a-change tag: "gates + smoke green; owner merges"
```

---

## Repository layout

```
JD-Assistant/
├── core/                          # THE application (Python)
│   ├── src/
│   │   ├── jd_core/               # parse, validate, rules (YAML rulebook + HR register), models
│   │   ├── jd_bank/               # ingest, dedup, cluster, harmonize, canonical, review,
│   │   │                          #   composer (Builder), library, forms, positions, audits
│   │   ├── jd_export/             # Word (APSA template, HR's CUPE form) + the CRF PDF
│   │   ├── api/                   # FastAPI + the server-rendered UI under /jd-bank/ui
│   │   ├── agents/  memory/  models/  worker/  gates/   # harness core
│   ├── alembic/  db/migrations/   # Postgres (alembic) + Neo4j (cypher)
│   └── tests/{unit,integration,live}/   # live = `make smoke`, against the real Bank
├── deploy/                        # offline bundle + install; second-Bank isolation
├── harness-claude-code/           # vendored harness base rules + agent definitions (not installed)
├── docs/                          # plan, findings, oral history, guide, ADRs, decisions, audits
├── fixtures/{golden,labels,hr}/   # golden sample, dedup labels, HR's own forms and guidance
├── CURRENT.md  CLAUDE.md  HANDOFF.md  DEVELOPER_GUIDE_1.md
├── build.ps1  launch.ps1  teardown.ps1  docker-compose.yml  Makefile
```

---

## Quick start

**One command, from a cold machine:**

Three scripts, one job each — **build → launch → teardown**:

```powershell
.\build.ps1                 # build the images, and prove they are deployable
.\launch.ps1                # start → wait for healthy → migrate → verify → status
.\launch.ps1 -NoCas         # ...and skip the SFU CAS login (dev-admin mode)
.\teardown.ps1              # stop; named volumes (your parsed rows) are KEPT
```

| | |
|---|---|
| `.\build.ps1 -NoCache` | after a `requirements*.txt` or Dockerfile change |
| `.\build.ps1 -Bundle` | ...and cut the offline deploy bundle (stack must be up) |
| `.\teardown.ps1 -Orphans` | also clear the one-shot containers compose leaves behind |
| `.\teardown.ps1 -Volumes` | also **discard the Bank** — asks first |

`quickstart.ps1` still works and forwards to `launch.ps1`, with a deprecation notice.

It starts postgres, neo4j, redis, api and worker, applies the Postgres (alembic) and
Neo4j (cypher) migrations, and then tells you what you actually woke up to: row counts
per parser version, whether CAS is on (read from the running container, not guessed),
and whether the inference host is reachable. `-Rebuild` forces a no-cache build — do
that after changing `core/requirements*.txt`, because `make gates` reuses a stale image
and will not catch a missing dependency that CI then fails on.

It deliberately does **not** start the `profiles: ["tools"]` services (`gates`,
`ingest`, `baseline`, `embed`, `cluster`, …) — those are one-shot job runners invoked
through `make`, not things that stay up.

<details><summary>The same thing by hand</summary>

```bash
docker compose up -d --wait   # postgres, neo4j, redis, api, worker
make migrate                  # alembic + the two cypher migrations
make hook-install             # git pre-commit → branch-name gate + gates-fast
make gates                    # full CI-identical suite, in Docker, no host Python
```
</details>

**Ollama is not part of this stack and must not be started here.** Inference runs on
metal on `aria-gb10-2`, a trusted internal host (ADR-003, non-negotiable #5). The app,
the dashboards and `make gates` all run without it; only the embedding and LLM jobs
(`make embed`, `make canonical-drafts`) need it up.

| | |
|---|---|
| App | <http://localhost:25800> (the bare host lands in the JD Bank library) |
| Neo4j browser | <http://localhost:25474> (`neo4j` / `harnesspass`) |
| Postgres · Redis | `localhost:25432` · `localhost:25379` |

> Host ports are the **25xxx** range on purpose, not the service defaults — this dev box
> runs several Docker projects and 5432/7474/7687 are already taken. In-container
> addressing (`postgres:5432`, `bolt://neo4j:7687`) is unchanged.

Full workflow, first-feature walkthrough, and troubleshooting: [`DEVELOPER_GUIDE_1.md`](DEVELOPER_GUIDE_1.md).

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `OLLAMA_BASE_URL` | `http://aria-gb10-2:11434/v1` | Self-hosted inference on the internal host (ADR-003) |
| `JD_API_PORT` | `25800` | Host port for the app |
| `CAS_ENABLED` | `false` | SFU sign-in. **Set `true` in `.env` on any box others can reach** — off makes every visitor an admin |
| `ALLOWED_SERVICE_ORIGINS` | — | Every address users reach the app on (scheme, host, port), for CAS — see `docs/NETWORK-SETUP.md` |
| `FEEDBACK_EMAIL` | — | Where "Report a problem with this page" sends; empty hides the link |
| `AGENT_MODEL` | `qwen2.5-coder:14b` | Coding model |
| `EMBED_MODEL` | `nomic-embed-text` | Embeddings for Neo4j vectors |
| `DATABASE_URL` | `postgresql+asyncpg://app:app@postgres:5432/harness` | Postgres |
| `NEO4J_URI` | `bolt://neo4j:7687` | Neo4j |
| `REDIS_URL` | `redis://redis:6379/0` | arq queue |
| `MAX_REVIEW_ITERATIONS` | `5` | Review-loop cap before escalation |
| `COVERAGE_THRESHOLD` | `80` | Gate coverage minimum |

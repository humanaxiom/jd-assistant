# AGENTS.md — Codex Instructions (Agent Harness v2)

Codex reads this file automatically. It applies to the whole repo.

---

## Stack

Python 3.11+ · FastAPI · Flask frontend · arq/Redis queue · **Postgres** (transactions, SQLAlchemy async) · **Neo4j** (graph memory + 768-dim vector index) · **Ollama on host metal** (`host.docker.internal:11434/v1`, OpenAI-compatible). Everything except Ollama is Docker. No cloud model calls, ever.

## Setup commands

```bash
docker compose up -d            # stack (requires Ollama running on host)
make migrate                    # alembic + cypher migrations
pip install -r core/requirements.txt -r core/requirements-dev.txt
```

## Testing — run before finishing ANY task

```bash
make gates
```

The suite (ruff, black, mypy --strict, unit, integration via testcontainers, coverage ≥ 80%, branch-name) must be entirely green. One red gate means the task is incomplete: iterate on the failures — max 5 attempts — then stop and report the failure output with analysis. Never weaken tests, skip gates, or lower coverage to pass.

## Git rules

- Never commit to `main`. Work on `agent/<task-id>-<slug>` (or `feat|fix|chore/<slug>`)
- Commit sequence: `red: failing tests` → `green: implementation` → `refactor`/`docs`
- Pre-commit hooks are installed (`pre-commit install`) and must pass

## TDD order (mandatory)

Write failing tests → confirm RED → implement to GREEN → refactor → docs/ADR. Never write implementation before its failing tests exist. Never modify tests to make code pass.

## Code conventions

- Full type hints, `mypy --strict` clean
- Async I/O everywhere (asyncpg, neo4j async, httpx, arq)
- Configuration only via `src/settings.py` — no scattered `os.environ`
- Postgres = transactional records; Neo4j = relationships + vector retrieval; Redis = queue only
- Model calls: `AsyncOpenAI(base_url=settings.ollama_base_url)` only
- Docstrings Google style; imports stdlib → third-party → local

## Before implementing

1. Vector-search memory for similar prior work: `GET /memory/similar?q=<task>`
2. Read `docs/adr/` for relevant decisions
3. Confirm containers healthy: `docker compose ps`

## Task files

Structured tasks live in `harness-codex/.codex/tasks/*.task.md` with goal, acceptance criteria, context files, and agent notes. Use them as the spec source of truth.

---

## Subagent roles (Codex must adopt these personas per pipeline stage)

The orchestration pipeline is: **planner → tester → coder(loop) → reviewer + security → docs**. When working a task, move through these roles explicitly, announcing each transition.

### planner
Decompose into a subtask table (id, agent, task, depends_on). tester before coder; reviewer after coder; security when auth/input/secrets/file-writes/network are touched; docs last. Query `GET /memory/similar?q=<task>` first.

### tester
Failing tests only, under `core/tests/`. Never touch `core/src/`. Run `pytest tests/unit -q` and confirm RED; if green, the tests are too weak. Commit `red: ...`.

### coder
Make the failing tests pass, then `make gates` — iterate on exact failures, max 5, then stop with the full report. Never modify tests, never add unjustified `# type: ignore`, never lower coverage. Commit `green: ...`.

### reviewer (merge-blocking)
Review `git diff main...HEAD` against: data placement (PG/Neo4j/Redis roles), type safety, async correctness, test integrity, config discipline, offline rule, migrations present. Verdict APPROVED or CHANGES REQUIRED with severity-tagged findings. Critical/major = not approved.

### security (merge-blocking when triggered)
Audit for SQL/Cypher injection, hardcoded secrets, missing Pydantic validation, path traversal in file-writing code, new external URLs (offline violation), unbounded resources. PASS/FAIL; critical or high = FAIL.

### docs
ADRs (`docs/adr/NNN-title.md` with Mermaid diagram), diagram updates, README — only `docs/` and `README.md`. Commit `docs: ...`.

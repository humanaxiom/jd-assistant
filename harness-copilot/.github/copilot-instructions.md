# GitHub Copilot Instructions — Agent Harness v2

Applies to all Copilot interactions in this repository.

---

## Stack (fixed — do not substitute)

- Python 3.11+ · FastAPI (API) · Flask (frontend dashboard) · arq + Redis (async task queue)
- **PostgreSQL**: all transactional data — SQLAlchemy 2.0 async + Alembic migrations
- **Neo4j**: agent graph memory + vector index (`artifact_embeddings`, 768-dim cosine)
- **Ollama on host metal** via `host.docker.internal:11434/v1` (OpenAI-compatible client). This is an offline-first codebase: never introduce cloud AI API dependencies.
- All services except Ollama run via `docker compose up -d`

## Non-negotiable gates

Every change must pass `make gates`: ruff · black · mypy --strict · pytest unit · pytest integration (testcontainers) · coverage ≥ 80% · branch-name check.

If any gate is red, the work is unfinished. Iterate on the exact failures (max 5 attempts), then escalate with the failure report. Never suggest weakening a test, adding `# type: ignore` without justification, or lowering the coverage threshold.

## Git workflow

- Branches only: `agent/<task-id>-<slug>` or `feat|fix|chore/<slug>`; `main` is protected
- Commit story: `red: failing tests` → `green: implementation` → `refactor`/`docs`
- Suggest opening PRs only when gates are green locally

## TDD (mandatory order)

1. Failing tests first — in `core/tests/unit/` or `core/tests/integration/`
2. Confirm RED, then implement minimally to GREEN
3. Refactor with gates green; update `docs/adr/` + Mermaid diagrams on architecture change

## Code conventions

- Full type annotations; `mypy --strict` clean
- Async I/O throughout (asyncpg, neo4j async driver, httpx, arq)
- Config exclusively through `core/src/settings.py` (pydantic-settings)
- Data placement: Postgres = transactions/ledger; Neo4j = relationships + vector retrieval; Redis = queue only
- External model calls only through `AsyncOpenAI(base_url=settings.ollama_base_url)`

## Skill invocations (Copilot Chat)

| Command | Effect |
|---|---|
| `@workspace /plan <issue>` | Decompose into subtask table with gate checklist |
| `@workspace /test <module>` | Write failing tests (must be RED before implement) |
| `@workspace /implement <task>` | Implement + iterate `make gates` until green |
| `@workspace /review` | Review diff against conventions + data-placement rules |

Detailed per-skill instructions: `.github/copilot-instructions/*.md`.

## Before implementing anything

1. Query graph memory for similar prior artifacts: `GET http://localhost:8000/memory/similar?q=<task>`
2. Read relevant ADRs in `docs/adr/`
3. Verify stack health: `docker compose ps`

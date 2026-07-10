# JD Bank / Agent Harness v2 — developer interface
# DOCKER-ONLY (ADR-006): no host Python. `make` is a task-runner that invokes Docker;
# all project code, tests, and linters run INSIDE the `api` container (source is
# bind-mounted at /app, so no rebuild is needed after edits). Run `make up` first.
.PHONY: up down gates gates-fast gates-integration migrate use-claude use-codex use-copilot logs shell hook-install

up:               ## Start the full stack (Ollama must be running on host)
	docker compose up -d

down:
	docker compose down

logs:
	docker compose logs -f api worker

shell:            ## Interactive shell inside the api container
	docker compose exec api bash

# ── Gates: THE non-negotiable suite — runs INSIDE the api container ─────────
# Static + unit need no Docker socket. `make up` must have run first.
# Full suite runs in the one-shot `gates` service (has the Docker socket for testcontainers);
# CI runs the exact same command. Self-contained: does not require `make up` first.
gates:            ## Full gate suite (what agents and CI run): static + unit+cov + integration
	docker compose run --rm gates sh -c '\
		ruff check src tests && \
		black --check src tests && \
		mypy src --strict && \
		pytest tests/unit --cov=src --cov-fail-under=80 --timeout=120 -q && \
		pytest tests/integration --timeout=300 -q'
	@echo "✅ ALL GATES GREEN"

gates-fast:       ## Pre-commit subset (static + unit, no integration) — quick edit-loop gate
	docker compose run --rm gates sh -c '\
		ruff check src tests && \
		black --check src tests && \
		mypy src --strict && \
		pytest tests/unit -q --timeout=120'
	@echo "✅ FAST GATES GREEN"

gates-integration: ## Integration tests only (testcontainers), in the gates runner
	docker compose run --rm gates pytest tests/integration --timeout=300 -q

# ── Migrations (already Docker) ────────────────────────────────────────────
migrate:          ## Postgres (alembic) + Neo4j (cypher)
	docker compose exec api alembic upgrade head
	docker compose exec neo4j cypher-shell -u neo4j -p harnesspass \
		-f /migrations/001_init.cypher || \
		cat core/db/migrations/001_init.cypher | \
		docker compose exec -T neo4j cypher-shell -u neo4j -p harnesspass

# ── Git pre-commit hook (Docker-only; replaces the host pre-commit framework) ─
hook-install:     ## Install a .git pre-commit hook that runs gates-fast in Docker
	@printf '#!/usr/bin/env bash\nset -e\nB=$$(git branch --show-current)\n[[ "$$B" =~ ^(agent|feat|fix|chore)/[a-zA-Z0-9._-]+$$ ]] || { echo "Branch $$B violates naming gate"; exit 1; }\nmake gates-fast\n' > .git/hooks/pre-commit
	@chmod +x .git/hooks/pre-commit
	@echo "Installed .git/hooks/pre-commit → branch-name gate + make gates-fast (Docker)"

# ── Harness selection: symlink the active tool's instruction layer ────────
use-claude:
	ln -sf harness-claude-code/CLAUDE.md CLAUDE.md
	@echo "Active harness: Claude Code (CLAUDE.md → harness-claude-code/)"

use-codex:
	ln -sf harness-codex/AGENTS.md AGENTS.md
	@echo "Active harness: Codex (AGENTS.md → harness-codex/)"

use-copilot:
	mkdir -p .github && ln -sf ../harness-copilot/.github/copilot-instructions.md .github/copilot-instructions.md
	@echo "Active harness: Copilot"

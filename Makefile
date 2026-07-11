# JD Bank / Agent Harness v2 — developer interface
# DOCKER-ONLY (ADR-006): no host Python. `make` is a task-runner that invokes Docker;
# all project code, tests, and linters run INSIDE the `api` container (source is
# bind-mounted at /app, so no rebuild is needed after edits). Run `make up` first.
.PHONY: up down gates gates-fast gates-integration migrate logs shell hook-install \
        register register-check

REGISTER_MD := docs/decisions/HR-DECISION-REGISTER.md

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
gates:            ## Full gate suite (what agents and CI run): static + unit + integration + coverage
	docker compose run --rm gates sh -c '\
		ruff check src tests && \
		black --check src tests && \
		mypy src --strict && \
		pytest tests/unit tests/integration --cov=src --cov-fail-under=80 --timeout=300 -q'
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

# ── HR decision register (rules/decision_register.yaml -> Markdown for HR) ──
# The register is DATA; the Markdown is a rendered VIEW of it, never hand-edited.
# The `gates` container mounts only ./core, so docs/ is invisible inside it — but
# ALL the work still happens in the container (ADR-006). The ONLY host-shell
# constructs used are `>` and `<` redirection, which work identically in POSIX sh
# and Windows cmd (no `mkdir -p` / `diff` / `rm`, which cmd does not have):
#   register       : container renders to stdout      -> host `>` writes the file
#   register-check : host `<` pipes the committed file -> container diffs it
# `make gates` already enforces that the register matches the live RULES; these
# targets keep the committed Markdown in step with the REGISTER.
register:         ## Render the HR decision register -> docs/decisions/HR-DECISION-REGISTER.md
	@docker compose run --rm -T gates python -m src.jd_core.rules.render > $(REGISTER_MD)
	@echo "✅ wrote $(REGISTER_MD)"

register-check:   ## Fail if the committed register Markdown is stale (CI drift gate)
	@docker compose run --rm -T gates python -m src.jd_core.rules.render --check < $(REGISTER_MD)

# ── Migrations (already Docker) ────────────────────────────────────────────
# Postgres schema via alembic (config at core/alembic.ini; cwd inside api is /app).
# Neo4j constraints + vector indexes via each cypher file piped into cypher-shell.
migrate:          ## Postgres (alembic) + Neo4j (cypher: 001 core, 002 JD vectors)
	docker compose exec api alembic upgrade head
	cat core/db/migrations/001_init.cypher | \
		docker compose exec -T neo4j cypher-shell -u neo4j -p harnesspass
	cat core/db/migrations/002_jd_vectors.cypher | \
		docker compose exec -T neo4j cypher-shell -u neo4j -p harnesspass

# ── Git pre-commit hook (Docker-only; replaces the host pre-commit framework) ─
hook-install:     ## Install a .git pre-commit hook that runs gates-fast in Docker
	@printf '#!/usr/bin/env bash\nset -e\nB=$$(git branch --show-current)\n[[ "$$B" =~ ^(agent|feat|fix|chore)/[a-zA-Z0-9._-]+$$ ]] || { echo "Branch $$B violates naming gate"; exit 1; }\nmake gates-fast\n' > .git/hooks/pre-commit
	@chmod +x .git/hooks/pre-commit
	@echo "Installed .git/hooks/pre-commit → branch-name gate + make gates-fast (Docker)"

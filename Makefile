# JD Bank — developer interface (built on Agent Harness v2)
# DOCKER-ONLY (ADR-006): no host Python. `make` is a task-runner that invokes Docker;
# all project code, tests, and linters run INSIDE the `api` container (source is
# bind-mounted at /app, so no rebuild is needed after edits). Run `make up` first.
.PHONY: up down gates gates-fast gates-integration migrate logs shell hook-install \
        register register-check baseline dedup ingest

REGISTER_MD := docs/decisions/HR-DECISION-REGISTER.md

# ── Archive baseline (Phase 2.5) ───────────────────────────────────────────
# The SFU JD archive lives OUTSIDE the repo and is READ-ONLY. Its path is NOT
# hardcoded: point JD_ARCHIVE_PATH at it. The default is a repo-relative `./archive`
# (machine-neutral); if it is empty the runner refuses to run rather than producing a
# confident baseline of nothing.
#
#   make baseline JD_ARCHIVE_PATH=C:/repos/hris/fixtures/SFU_JDs
#   make baseline JD_ARCHIVE_PATH=... BASELINE_ARGS="--sample 30"
#
# `export` (not a `VAR=x cmd` prefix) is what makes this work on Windows too: docker
# compose reads these from the environment, and cmd.exe has no inline env-var prefix.
JD_ARCHIVE_PATH ?= ./archive
JD_BASELINE_OUT ?= ./out/baseline
BASELINE_ARGS   ?=
DEDUP_ARGS      ?=
INGEST_ARGS     ?=
export JD_ARCHIVE_PATH
export JD_BASELINE_OUT

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

# ── Archive baseline (Phase 2.5) ───────────────────────────────────────────
# Full corpus is ~8-9 minutes single-process (measured: ~32 ms/file .doc, ~36 ms .docx).
# Deliberately NOT parallelised: it would trade determinism — what an audit trail is made
# of — for time this batch job does not need.
baseline:         ## Run the archive baseline (JD_ARCHIVE_PATH=<SFU JD archive>; BASELINE_ARGS="--sample 30")
	docker compose run --rm -T baseline python -m src.jd_bank.baseline $(BASELINE_ARGS)
	@echo "✅ baseline written to $(JD_BASELINE_OUT)"

# ── Tier-1 exact-duplicate report (Phase 3.1) ──────────────────────────────
# Reads the BASELINE's rows.jsonl (which already carries a sha256 per file) rather
# than walking the archive a second time — HANDOFF: "do not hand-roll a second path".
# Run `make baseline` first. Seconds, not minutes: no extraction, no parsing.
dedup:            ## Tier-1 exact-duplicate report over the baseline's rows -> docs/dedup/
	docker compose run --rm -T dedup python -m src.jd_bank.dedup $(DEDUP_ARGS)
	@echo "✅ dedup report written to docs/dedup/summary.json"

# ── Archive ingest driver (Phase 3.2a) ─────────────────────────────────────
# UNLIKE baseline/dedup, this WRITES to Postgres — run `make up` then `make migrate`
# first (the ingest service does not run migrations itself; it only opens the
# already-migrated schema). Idempotent: safe to re-run after a partial/failed pass.
#
#   make up && make migrate
#   make ingest JD_ARCHIVE_PATH=C:/repos/hris/fixtures/SFU_JDs
#   make ingest JD_ARCHIVE_PATH=... INGEST_ARGS="--limit 200"
ingest:           ## Ingest + parse the archive into Postgres (needs `make migrate` first)
	docker compose run --rm -T ingest python -m src.jd_bank.ingest --archive-root /archive $(INGEST_ARGS)

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

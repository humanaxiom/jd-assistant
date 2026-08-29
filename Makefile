# JD Bank — developer interface (built on Agent Harness v2)
# DOCKER-ONLY (ADR-006): no host Python. `make` is a task-runner that invokes Docker;
# all project code, tests, and linters run INSIDE the `api` container (source is
# bind-mounted at /app, so no rebuild is needed after edits). Run `make up` first.
.PHONY: up down gates gates-fast gates-integration gates-live smoke migrate logs shell \
        hook-install register register-check baseline dedup ingest embed embed-roles \
        near-dup dedup-role cluster harmonize-measure canonical-drafts rewrite-golden \
        quality-golden bank-audit singletons field-audit bundle deploy-check

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
EMBED_ARGS      ?=
EMBED_ROLES_ARGS ?=
NEARDUP_ARGS    ?=
DEDUPROLE_ARGS  ?=
CLUSTER_ARGS    ?=
HARMONIZE_ARGS  ?=
CANONICAL_ARGS  ?=
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
		pytest tests/unit tests/integration -m "not live" --cov=src --cov-fail-under=80 --timeout=300 -q'
	@echo "✅ ALL GATES GREEN"

gates-fast:       ## Pre-commit subset (static + unit, no integration) — quick edit-loop gate
	docker compose run --rm gates sh -c '\
		ruff check src tests && \
		black --check src tests && \
		mypy src --strict && \
		pytest tests/unit -m "not live" -q --timeout=120'
	@echo "✅ FAST GATES GREEN"

gates-integration: ## Integration tests only (testcontainers), in the gates runner
	docker compose run --rm gates pytest tests/integration -m "not live" --timeout=300 -q

# Opt-in, LOCAL-ONLY live golden tests against the real `aria-gb10-2` Ollama endpoint
# (ADR-003). NEVER part of `make gates` / CI — CI (ubuntu-latest) cannot route to a
# private internal host and never will. Self-skips per-test if the endpoint is
# unreachable (e.g. off-VPN), so it is honest in both environments.
gates-live:       ## Opt-in, LOCAL-ONLY live embedding golden tests (never in CI/gates)
	docker compose run --rm gates pytest tests/live -m live --timeout=300 -q

# END-TO-END SMOKE against the LIVE Bank (2026-08-28, after review). Asserts the four
# basics on the REAL data — parsing, dedup, categorize, filterable: every document is
# unreadable, behind a role, or in a named gap bucket (exactly); the gap buckets sum;
# collection membership is a true union of its signals (the filename-only regression
# cannot silently return); and a random sample is findable by exact filename through
# the archive browser query. Needs the live stack (`make up`); never CI.
smoke:            ## END-TO-END SMOKE against the LIVE Bank: parsing, dedup, categorize, filterable
	docker compose run --rm gates pytest tests/live/test_smoke_live_bank.py -m live --timeout=300 -q
	@echo "✅ SMOKE GREEN — every document in the live Bank is accounted for and findable"

# Opt-in, LOCAL-ONLY live LLM REWRITE golden (Phase 4.2a) against the real chat model on
# `aria-gb10-2` (ADR-003). NEVER part of `make gates` / CI — same live-endpoint guard as
# `gates-live`. Runs through the `rewrite` compose service (mirrors `embed` / `harmonize`);
# self-skips per-test if the endpoint is unreachable.
rewrite-golden:   ## Opt-in, LOCAL-ONLY live LLM rewrite golden (never in CI/gates)
	docker compose run --rm rewrite
	@echo "✅ rewrite golden complete"

# Opt-in, LOCAL-ONLY live LLM nuanced quality-AUDIT golden (Phase 4.2b) against the real
# chat model on `aria-gb10-2` (ADR-003). NEVER part of `make gates` / CI — same live-endpoint
# guard as `gates-live` / `rewrite-golden`. Runs through the `quality` compose service;
# self-skips per-test if the endpoint is unreachable.
quality-golden:   ## Opt-in, LOCAL-ONLY live LLM quality-audit golden (never in CI/gates)
	docker compose run --rm quality
	@echo "✅ quality golden complete"

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

# ── Operator guide (docs/OPERATOR-GUIDE.md is the source of truth) ──────────
# `guide` re-renders the branded HTML from the Markdown (run after every edit).
# `guide-check` is the drift gate (like register-check): fail if the committed HTML
# is stale. Container -> stdout, host `<`/`>` redirect (no docs mount needed).
guide:            ## Render docs/OPERATOR-GUIDE.md -> docs/operator-guide.html
	@docker compose run --rm -T gates python scripts/build_operator_guide.py \
		< docs/OPERATOR-GUIDE.md > docs/operator-guide.html
	@echo "✅ wrote docs/operator-guide.html"

guide-check:      ## Fail if docs/operator-guide.html is stale vs the Markdown (CI drift gate)
	@docker compose run --rm -T gates python scripts/build_operator_guide.py \
		< docs/OPERATOR-GUIDE.md | diff -q - docs/operator-guide.html >/dev/null \
		|| { echo "❌ docs/operator-guide.html is stale — run 'make guide'"; exit 1; }

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

# ── Embeddings (Phase 3.2b) ────────────────────────────────────────────────
# UNLIKE ingest, this needs Postgres AND Neo4j AND a reachable Ollama
# (`OLLAMA_BASE_URL` -> `aria-gb10-2`, ADR-003). Run `make ingest` first — this
# reads `parsed_jds`, it does not walk the archive.
#
#   make embed
#   make embed EMBED_ARGS="--limit 200"
embed:            ## Embed parsed_jds into Neo4j's vector index (needs `make ingest` first)
	docker compose run --rm -T embed python -m src.jd_bank.embeddings $(EMBED_ARGS)
	@echo "✅ embeddings summary written to docs/embeddings/summary.json"

embed-roles:      ## Embed HARMONIZED ROLES (canonical_jds) into Neo4j (needs `make migrate`)
	docker compose run --rm -T embed-roles python scripts/embed_roles.py $(EMBED_ROLES_ARGS)
	@echo "✅ role-embedding summary written to docs/embeddings/roles-summary.json"

# ── Tier-2 near-duplicate dedup (Phase 3.3) ────────────────────────────────
# MinHash-candidate, exact-Jaccard-scored, DB-reconciled — needs Postgres AND the
# archive bind (re-reads bytes via `dedup.text_source: raw_clean`). Run `make
# ingest` first. NB it is NEARDUP_ARGS, not EMBED_ARGS/DEDUP_ARGS — copying the
# wrong `*_ARGS` variable name here is the exact copy-paste bug HANDOFF already
# recorded once for `ingest`.
#
#   make near-dup
#   make near-dup NEARDUP_ARGS="--limit 200"
near-dup:         ## Tier-2 near-duplicate dedup into dedup_edges (needs `make ingest` first)
	docker compose run --rm -T near-dup python -m src.jd_bank.dedup.near $(NEARDUP_ARGS)
	@echo "✅ near-dup summary written to docs/dedup/near-dup-summary.json"

# ── Tier-3 role-equivalence dedup (Phase 3.4b) ─────────────────────────────
# Signals (`parsed_jds`) + idf-weighted skills + doc vectors (Neo4j), veto-constrained,
# DB-reconciled `dedup_edges` at `tier=ROLE_EQUIVALENT`. Needs Postgres AND Neo4j — NO
# archive bind (reads signals + vectors from the DB/store, never the raw files). Run
# `make ingest` then `make embed` first. NB it is DEDUPROLE_ARGS.
#
#   make dedup-role
#   make dedup-role DEDUPROLE_ARGS="--limit 200"
dedup-role:       ## Tier-3 role-equivalence dedup into dedup_edges (needs ingest + embed first)
	docker compose run --rm -T dedup-role python -m src.jd_bank.dedup.role $(DEDUPROLE_ARGS)
	@echo "✅ role-equiv summary written to docs/dedup/role-equiv-summary.json"

# ── Phase-3.5 role clustering (report-only) ────────────────────────────────
# Connected components over the ADMITTED Tier-1/2/3 edge graph + the HR eyeball report.
# Needs Postgres (parsed_jds + dedup_edges — run `make ingest`, `make near-dup`, `make
# dedup-role` first). Neo4j is OPTIONAL (the documents_with_vector column only); pass
# CLUSTER_ARGS="--no-vectors" to skip it. PERSISTS NOTHING — no `Cluster` row is written
# (Phase 4 owns that). NB it is CLUSTER_ARGS.
#
#   make cluster
#   make cluster CLUSTER_ARGS="--limit 500"
cluster:          ## Phase-3.5 role clustering report over dedup_edges (needs ingest + near-dup + dedup-role)
	docker compose run --rm -T cluster python -m src.jd_bank.cluster $(CLUSTER_ARGS)
	@echo "✅ cluster report written to docs/cluster/cluster-summary.json"

# ── Phase-4.1 harmonization measurement (report-only) ──────────────────────
# Drive the pure merge_cluster engine over the real JDFN role clusters and MEASURE the
# distributions the 9 harmonization.yaml knobs (HR-167..175) cut on. Recomputes clusters
# in-process (reuses 3.5), reconstructs each member JD, EXCLUDES WJQ (CUPE), and picks NO
# knob value (the coder MEASURES, the orchestrator DECIDES). Needs Postgres (parsed_jds +
# dedup_edges — run `make ingest`, `make near-dup`, `make dedup-role` first); no Neo4j.
# PERSISTS NOTHING. NB it is HARMONIZE_ARGS.
#
#   make harmonize-measure
#   make harmonize-measure HARMONIZE_ARGS="--limit 2000"
harmonize-measure:  ## Drive merge_cluster over real JDFN clusters; measure the 9 knobs (needs ingest + cluster deps)
	docker compose run --rm -T harmonize python -m src.jd_bank.harmonize $(HARMONIZE_ARGS)
	@echo "✅ harmonization measurement written to docs/harmonize/summary.json"

# ── Phase-4.4a canonical-draft producer (WRITES DRAFT canonical_jds) ───────
# Drive the Phase-4 pipeline (4.1 merge -> 4.2a rewrite -> 4.2b audit -> 4.3 change-log
# -> validator) over the real role clusters — BOTH forms since HR-206 — and PERSIST the
# result as DRAFT canonical_jds rows: the 4.4 review work-list. UNLIKE harmonize-measure
# this WRITES to Postgres (clusters / canonical_jds / audit_log). Idempotent + never
# clobbers a reviewer-touched canonical; NOTHING publishes (non-negotiable #1). Recomputes
# clusters in-process (reuses 3.5); needs Postgres (parsed_jds + dedup_edges — run
# `make up`, `make migrate`, `make ingest`, `make near-dup`, `make dedup-role`); no Neo4j.
#
# The FULL pipeline needs a reachable Ollama on `aria-gb10-2` (ADR-003) — so it is
# LOCAL-ONLY, exactly like `make embed` / `make rewrite-golden`. `--no-llm` persists the
# deterministic 4.1 merge draft only and needs NO model endpoint. NB it is CANONICAL_ARGS.
#
# ⚠ `--no-llm` IS NOT A CHEAPER WAY TO GET THE SAME THING, and on an already-populated
# Bank it used to take work away. It persists a deterministic merge draft, which is
# strictly poorer than an LLM-rewritten one — measured on the live Bank 2026-08-17, a
# `--no-llm` pass refreshed 1,763 untouched JDFN drafts and the cohort's mean score fell
# 73.0 -> 52.73 in 32 seconds, reported only as `drafts_refreshed`. The producer now
# REFUSES that overwrite by default (counted `skipped_would_downgrade`); pass
# `--allow-downgrade` to do it deliberately.
#
# ⏱ MEASURED 2026-08-17: a FULL LLM pass over this archive is ~44 HOURS — 2,456 clusters
# at 64.8s each (a rewrite call plus an advisory audit call per cluster). Use `--resume`
# to skip the clusters a previous pass already finished; without it an interruption
# anywhere means paying for every cluster again. `make embed` has had that property
# since Phase 3.2 and the reindex runbook cites it; this is the same idea.
#
#   make canonical-drafts                              # full pipeline (needs Ollama)
#   make canonical-drafts CANONICAL_ARGS="--resume"    # continue an interrupted pass
#   make canonical-drafts CANONICAL_ARGS="--no-llm"    # deterministic-only (no Ollama)
#   make canonical-drafts CANONICAL_ARGS="--limit 500"
#   make canonical-drafts CANONICAL_ARGS="--no-llm --allow-downgrade"  # re-baseline
canonical-drafts: ## Phase-4.4a: produce DRAFT canonical_jds over real clusters (local-only; --no-llm for no Ollama)
	docker compose run --rm -T canonical python -u -m src.jd_bank.canonical $(CANONICAL_ARGS)
	@echo "✅ canonical-producer summary written to docs/canonical/summary.json"

# ── Bank content audit (read-only) ─────────────────────────────────────────
# What the live Bank actually CONTAINS, per form: for each section, how many clusters'
# SOURCES offered it vs how many DRAFTS kept it. Run it BEFORE and AFTER any producer
# pass — a carry-through that falls is a content-loss defect, and this is the only view
# that shows one. `refreshed=649 failures=0` prints identically either way.
#
# Exits 2 if any section's carry-through is below --min-retention (default 100), so it
# can gate a pipeline rather than only inform a suspicious human.
#
#   make bank-audit
#   make bank-audit AUDIT_ARGS="--json"                 # machine-readable, diffable
#   make bank-audit AUDIT_ARGS="--min-retention 95"     # loosen the verdict
bank-audit:       ## Read-only: per-form content carry-through of the live Bank
	docker compose run --rm -T bank-audit python -u -m src.jd_bank.bank_audit $(AUDIT_ARGS)

# ── HR-223: the one-of-a-kind population (read-only) ───────────────────────
# How many SFU jobs exist exactly ONCE at SFU — the population governed by
# `comparison.singleton_role_policy`, which ships as `drop` because that is what the
# pipeline does today, NOT because anyone decided it. Postgres only; writes no Bank row.
#
# Reports FOUR buckets, never a total: a unique title, a title shared with a document
# that DID reach a role (a dedup recall miss, not a unique job), a title shared only with
# other orphans, and COULD-NOT-EVALUATE. Plus the same split over documents that did
# cluster, as a control.
#
#   make singletons
singletons:       ## Read-only: measure the one-of-a-kind population (HR-223)
	docker compose run --rm -T singletons python -u -m src.jd_bank.singletons $(SINGLETON_ARGS)
	@echo "✅ singleton summary written to docs/singletons/singleton-summary.json"

# ── P3b: identification fields vs the RAW ARCHIVE ──────────────────────────
# `title` and `employee_group` are the ONLY two fields ever compared against the source
# files, and each produced defects immediately. This audits the label-read fields —
# department, position_number, grade — with `title` as the CONTROL.
#
# Needs the archive AND Postgres. Reports exact / VARIANT / blank / no-label per field
# per bargaining unit — never one archive-wide percentage, because `title` was never a
# general problem and the aggregate hid that completely.
#
#   make field-audit JD_ARCHIVE_PATH=/path/to/SFU_JDs
#   make field-audit JD_ARCHIVE_PATH=... FIELD_AUDIT_ARGS="--sample 500"
field-audit:      ## Read-only: identification fields vs the raw archive (P3b)
	docker compose run --rm -T field-audit python -u -m src.jd_bank.field_audit $(FIELD_AUDIT_ARGS)
	@echo "✅ field audit written to docs/field-audit/field-audit.json"

# ── Migrations (already Docker) ────────────────────────────────────────────
# Postgres schema via alembic (config at core/alembic.ini; cwd inside api is /app).
# Neo4j constraints + vector indexes via each cypher file piped into cypher-shell.
migrate:          ## Postgres (alembic) + Neo4j (cypher: 001 core, 002 JD vectors, 003 role vectors)
	docker compose exec api alembic upgrade head
	cat core/db/migrations/001_init.cypher | \
		docker compose exec -T neo4j cypher-shell -u neo4j -p harnesspass
	cat core/db/migrations/002_jd_vectors.cypher | \
		docker compose exec -T neo4j cypher-shell -u neo4j -p harnesspass
	cat core/db/migrations/003_jd_role_vectors.cypher | \
		docker compose exec -T neo4j cypher-shell -u neo4j -p harnesspass

# ── Offline deployment (fresh box, no internet) ────────────────────────────
# GOAL: after any change, this repo can be deployed to a fresh box that has Docker and
# NO internet. `bundle` cuts the artifact on a connected box; `deploy/install.ps1` runs
# on the target and never touches the network (`--no-build --pull never`).
#
# A CODE change does not need a new bundle — api/worker bind-mount ./core, so copying
# the repo is enough. Re-cut only when requirements*.txt or the Dockerfile moves.
bundle:           ## Cut the offline deploy bundle (images + Postgres + Neo4j) -> dist/
	pwsh -NoProfile -File deploy/bundle.ps1 $(BUNDLE_ARGS)

deploy-check:     ## Prove the offline bundle would be COMPLETE (no network, no build)
	@bash deploy/deploy-check.sh

# ── Git pre-commit hook (Docker-only; replaces the host pre-commit framework) ─
hook-install:     ## Install a .git pre-commit hook that runs gates-fast in Docker
	@printf '#!/usr/bin/env bash\nset -e\nB=$$(git branch --show-current)\n[[ "$$B" =~ ^(agent|feat|fix|chore)/[a-zA-Z0-9._-]+$$ ]] || { echo "Branch $$B violates naming gate"; exit 1; }\nmake gates-fast\n' > .git/hooks/pre-commit
	@chmod +x .git/hooks/pre-commit
	@echo "Installed .git/hooks/pre-commit → branch-name gate + make gates-fast (Docker)"

# Developer Guide — JD Bank (on Agent Harness v2)

> From `git clone` to your first agent-built feature merged to `main`. Self-hosted Python
> stack (FastAPI · **Neo4j** · Postgres · Redis · arq), built with
> Claude Code. **Everything runs in Docker — there is no host Python.**
>
> **Two corrections to what this guide used to say, both verified against the running
> stack:** there is **no Flask** (the service, dependency and package went in `3e32103`;
> the UI is the FastAPI app's own server-rendered pages), and **the ports are 25xxx, not
> the harness defaults** — see §3.
>
> This guide is also the **golden-standard template** for new projects on this harness
> (see §13). JD Bank is the reference implementation.

**Read first:** root `CLAUDE.md` (project invariants), `docs/plan.md` (build plan), and the
ADRs — especially **ADR-002** (Neo4j=vectors/Postgres=SQL), **ADR-003** (offline Ollama),
and **ADR-006** (Docker-only execution). This guide operationalizes them.

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Clone and bootstrap](#2-clone-and-bootstrap)
3. [First-run verification](#3-first-run-verification)
4. [Pick your AI harness](#4-pick-your-ai-harness)
5. [Your first feature — end-to-end walkthrough](#5-your-first-feature--end-to-end-walkthrough)
6. [The subagent pipeline in practice](#6-the-subagent-pipeline-in-practice)
7. [The gate suite — what actually blocks you](#7-the-gate-suite--what-actually-blocks-you)
8. [Working with graph memory](#8-working-with-graph-memory)
9. [Async jobs (arq)](#9-async-jobs-arq)
9a. [The JD data layer — parser versions and the two templates](#9a-the-jd-data-layer--parser-versions-and-the-two-templates)
10. [Extending the harness](#10-extending-the-harness)
11. [Troubleshooting](#11-troubleshooting)
12. [Team conventions](#12-team-conventions)
13. [Golden standard — reusing this for new projects](#13-golden-standard--reusing-this-for-new-projects)

---

## 1. Prerequisites

**Docker-only rule (ADR-006): no host language runtimes or compilers.** You do **not** install
Python, pip, venv, or the `pre-commit` framework on the host. All project code, tests, linters,
and the type-checker run inside containers.

Install on the host (metal):

| Tool | Version | Why |
|---|---|---|
| Git | ≥ 2.40 | Branch workflow |
| Docker + Compose | Docker 24+, Compose v2 | Runs **everything** (app, tests, gates, tooling) |
| **Ollama** | latest | Inference — the ONLY non-Docker runtime; must run on host for GPU/Metal (ADR-003) |
| Node (optional) | 20+ | Only if you install the Claude Code CLI |
| `make` (optional) | any | Convenience task-runner that *invokes* Docker; commands also work raw |

`make` is not a code runtime — it just shells out to `docker compose`. If it's not installed
(common on Windows), use the raw `docker compose …` commands shown alongside each target.

Pull models once (on the host, into Ollama):

```bash
ollama pull qwen2.5-coder:14b     # AGENT_MODEL — the coding model in settings
ollama pull nomic-embed-text      # 768-dim embeddings matching the Neo4j vector index
OLLAMA_HOST=0.0.0.0 ollama serve &   # bind all interfaces so containers can reach it
```

Verify: `curl -s http://localhost:11434/v1/models | jq '.data[].id'` should list both.

Neo4j Browser is at `http://localhost:25474` once the stack is up (creds `neo4j` / `harnesspass`).

---

## 2. Clone and bootstrap

No venv, no `pip install` — the image already contains every Python dependency
(`core/requirements.txt` + `requirements-dev.txt`), and `./core` is bind-mounted into the
containers, so host edits take effect with no rebuild.

```bash
git clone <your-repo-url> JD-Assistant
cd JD-Assistant

cp .env.example .env               # edit only to override defaults

docker compose up -d               # build + start the stack (Ollama must be running on host)
make migrate                       # or: see the migrate recipe in the Makefile
make hook-install                  # Docker-only git pre-commit hook (branch gate + gates-fast)
```

`docker compose up -d` starts: `postgres`, `neo4j`, `redis`, `api` (FastAPI :8000),
`worker` (arq). The review UI is server-rendered inside `api` under `/jd-bank/ui` (there is no
separate frontend service). Containers reach Ollama on the host via
`host.docker.internal:11434` — preconfigured with `extra_hosts: host-gateway` so it works on
Linux too, not just Docker Desktop.

> **Legacy `.doc` note (JD Bank):** the SFU archive includes ~4,600 binary Word `.doc` files
> that python-docx cannot read. The ingestion image must include **antiword** (or a LibreOffice
> headless converter). This is a Phase-1 Dockerfile addition — see `docs/plan.md` §1.3.

---

## 3. First-run verification

Run these in order — each proves one layer works. **Everything here is Docker-side.**

> ⚠ **This project does NOT publish on the default ports.** The box runs many Docker
> projects, so jd-bank publishes on **25xxx** and the data stores bind to **loopback
> only**. Every command below uses the real ones; anything you read elsewhere quoting
> `8000` / `7474` / `5000` is the upstream harness's numbering, not this repo's.
>
> | Service | Host port | Notes |
> |---|---|---|
> | API | **25800** | the only one published on all interfaces |
> | Postgres | 25432 | `127.0.0.1` only |
> | Neo4j HTTP / Bolt | 25474 / 25687 | `127.0.0.1` only |
> | Redis | 25379 | `127.0.0.1` only |

```bash
# 3.1 Services healthy
docker compose ps
# Every service should show "healthy" or "running"

# 3.2 API responds
curl -s http://localhost:25800/health          # {"status":"ok"}

# 3.3 Neo4j vector indexes exist (this is where JD vectors live — NOT pgvector)
docker compose exec neo4j cypher-shell -u neo4j -p "$NEO4J_PASSWORD" \
  "SHOW INDEXES YIELD name, type WHERE type='VECTOR' RETURN name"
# Expect FOUR: jd_document_embeddings, jd_section_embeddings, jd_role_embeddings,
# artifact_embeddings. The first three are the JD Bank's; the last is agent memory.

# 3.4 Ollama reachable FROM INSIDE a container (the critical connectivity check)
docker compose exec api curl -s "$OLLAMA_BASE_URL/models" | jq -r '.data[].id'
# Ollama runs on `aria-gb10-2`, NOT on this box and NOT on localhost (ADR-003), so
# OLLAMA_BASE_URL is http://aria-gb10-2:11434/v1. Must list nomic-embed-text (the
# embedding model). If this fails, embedding and the LLM-touching paths cannot run (§11).

# 3.5 Gate suite — runs in the one-shot `gates` container (no host Python), incl. integration
make gates          # = docker compose run --rm gates sh -c '...'  (self-contained)
# Expect: ALL GATES GREEN — ruff, black, mypy, unit, integration, coverage ≥ 80%

# 3.6 The application itself — a browser, not a dashboard
#   open http://localhost:25800/            (redirects to a landing page)
#   open http://localhost:25800/jd-bank/ui/library
```

If any step fails, stop and fix it before continuing.

> **There is no Flask dashboard.** The service, its dependency and its package were
> removed in `3e32103`; references to `http://localhost:5000` elsewhere in this repo are
> stale. The UI is the FastAPI app's own server-rendered pages under
> `/jd-bank/ui/…`, and Neo4j Browser at `http://localhost:25474` is the graph view.

---

## 4. Claude Code

JD Bank is driven by **Claude Code** (the harness's Codex and Copilot layers were removed — this
is a Claude-only project).

```bash
npm install -g @anthropic-ai/claude-code   # if not installed
cd JD-Assistant && claude
```

The six subagents in `harness-claude-code/.claude/agents/` (planner, tester, coder, reviewer,
security, docs) plus `.claude/settings.json` (blocks commits to `main`; auto-runs
`ruff --fix` **in the api container** after every write) are the Claude Code layer.

> 🔴 **Activation note — STILL INERT, and the step is no longer a bare symlink (2026-08-29).**
> Claude Code loads subagents from `<repo>/.claude/agents/`, so nothing under
> `harness-claude-code/` is ever read. **A root `.claude/` now EXISTS** — holding only
> `settings.local.json` and a lock file — so `ln -s harness-claude-code/.claude .claude`
> would now fail on the existing directory rather than activate anything. To actually turn
> them on, symlink or copy the *contents* (`.claude/agents/`, and a `settings.json` for the
> hooks) into the existing root `.claude/`. **Confirm with `/agents` in a session** — do not
> assume. Today no session dispatches these, and the standing rule is not to dispatch any
> agent unless the user asks. (Do not run a `make use-*` symlink of
> `CLAUDE.md` — the root `CLAUDE.md` here is the project invariants file, not the harness base
> rules, which it references.)

---

## 5. Your first feature — end-to-end walkthrough

Goal: **port the `ParsedJD` pydantic model (Phase 1.1)** — the contract every pipeline stage
speaks. It's the natural first slice: pure, well-specified, and a near-verbatim EXTRACT of
hris's `SFUJobDescription` (reuse map #1). Real JD Bank work, small enough for one sitting.

### 5.1 Create the agent branch

```bash
git checkout main && git pull
git checkout -b agent/T-p1-parsedjd-schema
```

Branch must match `(agent|feat|fix|chore)/<slug>` — the pre-commit hook (installed in §2)
rejects anything else.

### 5.2 Write a spec

```
Port hris `SFUJobDescription` (see docs/audit/hris-reuse-map.md #1) into
core/src/jd_core/models/parsed_jd.py as pydantic v2 models. 10 sections in order:
identification, position_summary, duties[SFUDuty(action_verb, statement, how_why)],
decision_making, problem_solving, relationships(supervisory/internal/external),
qualifications[SFUQualification(kind ∈ education|experience|knowledge|skill|ability|security,
modifier)], plus presence-booleans about_sfu / territorial_ack / employment_equity.
- Coerce JSON null → [] for list fields (LLM robustness), mirroring hris.
- Full type hints; mypy --strict clean.
- Unit tests: round-trip serialization + null-coercion + section ordering.
```

### 5.3 Run the pipeline (Claude Code)

```
Use the planner subagent to plan this task, then execute the full pipeline through docs.
```

Claude Code delegates `planner → tester → coder (inside the ReviewLoop) → reviewer + security
→ docs`. The pipeline halts if the reviewer rejects or security fails. (See §6.)

### 5.4 Verify before opening a PR — all in Docker

```bash
make gates          # must be entirely green (runs in the api container)
git log --oneline   # expect: red: ... → green: ... → docs: ...
```

### 5.5 Open the PR

```bash
git push -u origin agent/T-p1-parsedjd-schema
gh pr create --fill
```

CI re-runs every gate (same in-container commands). Green → merge to `main`. That's the loop.

---

## 6. The subagent pipeline in practice

⚠ **Aspirational as of 2026-08-29 — the definitions are inert (see the activation note in
§5), so no session runs this today.** It is kept because the DISCIPLINE is the point and it
still binds when one model does every role: write the failing test first, break the guard to
prove it can go red, re-run the gates yourself, read the diff. The `run_pipeline` pipeline in
`core/src/agents/` is a DIFFERENT thing and IS live — see CLAUDE.md § *Two different things
are called "agents" here*.

This is the harness's core capability — use it for every non-trivial task.

```mermaid
sequenceDiagram
    participant You
    participant Planner
    participant Tester
    participant Coder as Coder + ReviewLoop
    participant Reviewer
    participant Security
    participant Docs

    You->>Planner: task spec
    Planner-->>You: validated plan (tester before coder enforced)
    You->>Tester: write failing tests
    Tester-->>You: RED confirmed
    You->>Coder: implement
    loop until all gates green (≤5)
        Coder->>Coder: fix exact failures
    end
    Coder-->>You: GREEN
    par merge-blocking
        You->>Reviewer: diff review
        You->>Security: audit
    end
    Reviewer-->>You: APPROVED (or CHANGES REQUIRED → back to Coder)
    Security-->>You: PASS (or FAIL → back to Coder)
    You->>Docs: ADR + Mermaid + README updates
    Docs-->>You: ready for PR
```

Under the hood: `PlannerAgent` decomposes → `Orchestrator` topologically dispatches subagents,
passing prior outputs as context; the coder runs inside the iterate-until-green `ReviewLoop`;
**reviewer approval + security pass are merge-blocking** (`core/src/agents/orchestrator.py`).
The whole run is the `run_pipeline` arq job and is recorded to the Neo4j lineage graph.

**When each subagent triggers**

- **Planner** — always first for anything non-trivial. Skip only for one-line fixes.
- **Tester** — always before Coder. The urge to skip is the signal you need it.
- **Coder** — inside the ReviewLoop (max 5 iterations). On escalation, read the failure report;
  the fix is usually a mis-scoped test or an ambiguous spec.
- **Reviewer** — always after Coder, before merge. Approval is blocking.
- **Security** — auth, input handling, secrets, file writes, subprocess, network egress. For
  JD Bank, also: any code touching JD content must respect local-first (no cloud calls).
- **Docs** — always last, after Reviewer approves. Updates ADRs + Mermaid + README.

**Reading pipeline output** — the worker returns a structured per-subtask result;
`GET /tasks/<id>/lineage` shows run lineage; Neo4j Browser
(`http://localhost:25474`) shows the graph:

```cypher
MATCH (t:Task)-[:DECOMPOSED_INTO]->(s:Subtask)-[:EXECUTED_BY]->(a:Agent)
OPTIONAL MATCH (s)-[:PRODUCED]->(ar:Artifact)
RETURN t, s, a, ar LIMIT 25
```

---

## 7. The gate suite — what actually blocks you

**All gates run inside Docker (ADR-006) — including integration. Testing is non-negotiable and
has no host fallback.** The full suite runs in a dedicated one-shot `gates` compose service:

```bash
make gates          # full: ruff · black · mypy --strict · unit(cov ≥ 80) · integration
make gates-fast     # subset: static + unit (no integration) — the quick edit-loop gate
```

Both are just `docker compose run --rm gates sh -c '…'`. The `gates` service (defined in
`docker-compose.yml`, `profile: tools`) carries everything the suite needs, so `make gates` is
**self-contained — you do not need `make up` first**: unit/static need no services, and the
**integration tests spin their own Postgres + Neo4j via testcontainers**. That works in Docker
because the `gates` service:

- mounts the Docker socket **in the compose file** (`/var/run/docker.sock`) — works identically
  on Linux and Docker Desktop (Windows/macOS), no host-path juggling;
- sets `TESTCONTAINERS_HOST_OVERRIDE=host.docker.internal` so the sibling test containers are
  reachable via the host gateway;
- sets `TESTCONTAINERS_RYUK_DISABLED=true` (the reaper is unreliable in Docker-in-Docker).

Run just the integration slice with `make gates-integration`. **CI runs the identical
`docker compose run --rm gates` command** — local and CI are byte-for-byte the same.

Enforced in three places: **pre-commit hook** (`gates-fast`, Docker) → **the ReviewLoop**
(gates run after Coder; failures feed back ≤5×) → **CI** (`.github/workflows/ci.yml`, same
`gates` service; `main` requires green).

**When a gate is red, iterate on that exact failure only.** Never: weaken/delete a failing
test, add `# type: ignore` without a justification, lower the coverage floor in
`pyproject.toml`, or comment a gate out. After 5 ReviewLoop iterations still red → the subagent
escalates with the full report. Read it; fix the spec or the test, never the gate.

---

## 8. Working with graph memory

Before implementing anything, check whether similar work already exists — the JD Bank
`/memory-query` discipline. Vectors live in **Neo4j** (ADR-002), not pgvector.

```bash
curl -s "http://localhost:25800/memory/similar?q=parsedjd%20schema&k=5" | jq
```

Subagents call this automatically via `_memory_context()` in `core/src/agents/base.py` before
completion. Task lineage:

```bash
curl -s "http://localhost:25800/tasks/<uuid>/lineage" | jq
```

Neo4j Browser (`http://localhost:25474`, neo4j / `$NEO4J_PASSWORD`):

```cypher
MATCH (t:Task)-[:DECOMPOSED_INTO]->(s:Subtask)-[:EXECUTED_BY]->(a:Agent)
OPTIONAL MATCH (s)-[:PRODUCED]->(ar:Artifact)
RETURN t.id, s.description, a.id, collect(ar.id) ORDER BY t.id DESC LIMIT 5
```

Memory is a corpus that compounds. Don't clear it unless you're testing. (JD *document*
embeddings — Phase 3 — also live in Neo4j's vector index, distinct from this agent-memory graph.)

---

## 9. Async jobs (arq)

**There is no dashboard to enqueue from** — that Flask service was removed in `3e32103`.
Post to the API directly. `POST /tasks` writes a `Task` row (Postgres), generates the
`agent/<uuid8>-<slug>` branch, and enqueues `run_pipeline` on arq. Watch it:

```bash
docker compose logs -f worker      # subagent transitions logged in order
```

From code (run inside a container, e.g. `make shell`) — note the **in-network** address is
`api:8000`; the 25800 mapping is host-side only:

```python
import httpx
r = httpx.post("http://api:8000/tasks", json={"title": "...", "spec": "...acceptance criteria..."})
print(r.json())
```

On-demand gates for a branch:
`curl -s -X POST "http://localhost:25800/gates/run?branch=agent/T-42-slug" | jq`.

⚠ **These legacy harness routes are admin-gated** (P0.1a) and, like every other
state-changing route, require a CSRF token when driven from a browser session (P0.1b-i).
`POST /gates/run` takes `branch` as a **query parameter** and declares no body — which is
exactly why the CSRF guard is mounted app-wide rather than only over the browser surface.

---

## 9a. The JD data layer — parser versions and the two templates

The harness sections above are generic. This one is JD Bank's, and it is where the traps
live.

**Two document templates, one model.** The archive is not one form:

| Template | Groups | Parser | Share of archive |
|---|---|---|---|
| **JDFN** | `apsa` · `apex` · `poly` | `parser/segmenter.py` | 5,416 (37.3%) |
| **WJQ** (CUPE 3338) | `cupe` | `parser/wjq.py` — a 14-section point-factor questionnaire | 4,440 (30.6%) |
| — | not stated in the document | — | 4,630 (31.9%) |

Both land in the same `SFUJobDescription`. The WJQ segmenter maps the questionnaire onto
the SFU 10-section model and stores the **seven point-factor sections verbatim** in
`additional_context` — deliberately *not* mapped onto `decision_making` /
`problem_solving`, because WJQ has no such prose and force-mapping would feed
`hay_signals.py` a bogus signal. **Empty is honest.**

**⚠ The validator WAS template-blind — it is not any more (CUPE Phases B–E, 2026-08).**
It used to run every rule over every JD, which meant four rules fired on **100%** of CUPE
documents: not because those JDs are poor, but because the CUPE form does not contain the
sections they check. That is now fixed on four axes, all keyed on the same `JDTemplate`
and all resolved from the document's own `employee_group` via `template_of`:

| axis | mechanism | where |
|---|---|---|
| which RULES may judge a form | `RuleSpec.applies_to` — required, no default | `rule_catalog.yaml` (Phase B) |
| which NUMBERS judge it | `Rules.thresholds_for(template)` — e.g. WJQ `duties_max: 12` | `thresholds.yaml` (Phase C) |
| which FORMS get harmonized into drafts | `harmonization.templates_harmonized` (HR-206), a PRIORITY order | `harmonization.yaml` (Phase D) |
| what a form CONSISTS of, for authoring | `composer.forms.FormSpec` + `FORMS` | `composer/forms.py` (Phase E) |

**The one thing to understand before changing any of it:** `employee_group` is what
`template_of` reads, so that single field decides which bar a document is judged by. Two
guards exist because it was got wrong twice — the WJQ Builder **fixes** it rather than
asking the author (`wjq_assemble`), and the LLM rewrite **restores** it from the grounded
merge draft (`_REWRITABLE_FIELDS`), after the model was found nulling it on ~95% of CUPE
drafts and silently moving them to the JDFN bar.

**Scope is still HR's**: all 207 register entries are `open`, including HR-194 (may the
Bank *author* CUPE?) and HR-201 (do SFU's boilerplate rules apply to a form that has no
such block?). The WJQ bar was built the way APSA's was — measured, registered, nothing
auto-publishing. Evidence: `docs/decisions/cupe-scope-measured-2026-08-14.md`,
`cupe-phase-b-measured-2026-08-14.md`, `cupe-phase-e-routing-seam-2026-08-17.md`.

### `parser_version` — the trap to know before you touch the parser

`parsed_jds` is keyed on `(source_document_id, parser_version)`, and every **batch**
consumer filters on the `PARSER_VERSION` literal:

```python
.where(ParsedJDRow.parser_version == PARSER_VERSION)
```

**So bumping the constant and not re-parsing leaves those consumers reading zero rows —
an apparently empty Bank.** The bump and the re-parse must ship together.

```bash
make ingest JD_ARCHIVE_PATH=/path/to/SFU_JDs    # skip-first; re-parses only what is missing
```

Two things that make this less alarming than it sounds, both worth knowing:

- **It is additive.** A re-parse *inserts* rows at the new version; v1/v2/v3 stay. So it is
  reversible by deleting the new rows, and you can compare versions directly — which is
  exactly how the v3→v4 fix was verified.
- **User-facing surfaces are unaffected.** The Builder, library and review pages read
  through `_load_latest_parsed`, which orders by `created_at` and is version-agnostic.

⚠ **The dev `api` container bind-mounts the repo and runs `--reload`**, so editing
`PARSER_VERSION` changes what the *running* service reports immediately — before you have
re-parsed anything. Expect that window and close it.

**Current version: `jd_segmenter_v8`** — the department label the archive actually uses.
`id_labels.department` held ONE spelling, `Department Name`, while **654 CUPE documents
say `Department Name/Section`**. Measured in the PARSER'S OWN scope, unreadable department
labels went **680 -> 16** and the Bank gained **+607 departments** (8,837 -> 9,444). The 16
left are the antiword line-wrap and two source typos — deliberately not encoded (HR-147,
#178).

**v7** — the WJQ identification labels. antiword's
fixed-width render puts a label and its VALUE in ONE cell while `_extract_label` read the
NEXT one, so **2,046 of 4,300 CUPE documents (47.6%) carried no title** — the `Untitled
Position` sentinel — against 0.0% for every other bargaining unit. **805 titles recovered
(placeholders 2,050 -> 1,245), position numbers +593** (HR-147, #166).

**v6** — the employee group. A job was called CUPE because it *mentioned* the word: APSA
managers who supervise CUPE staff. `employee_group` had TWO provenances — READ from the
text for APSA/APEX/POLY, SET by routing for CUPE — with nothing recording which (HR-226,
#165). The 24 drafts built from the mislabelled documents were deleted (#163).

⚠ **Each of v6 and v7 shipped WITH its re-parse**, as this constant's contract requires.

**v5** — the WJQ heading match tolerates antiword's
fixed-width layout (#137). A heading printed beside the next column, or with its own
words stretched apart, matched nothing, so the section never opened: **719 of 4,440 CUPE
documents (16.2%) parsed to ZERO duties**, against 2.2% on the APSA form. That silence is
what the rewrite filled with **1,219 invented duties across 153 drafts** (HR-213). The
same gap also let the form's checkbox scaffolding bleed *upward* into the duty list, so
it was starving duties and polluting them at once.

**v4** — `additional_context` keeps the whole WJQ point-factor block (HR-200). At v3's
borrowed 4,000-char cap, **81.4% of CUPE JDs were stored truncated**; after v4, **0%**
are, and `continuing_education` — the last of the seven sections, and so the first
casualty of a cut — went from **17.0% → 85.8%** present.

### ⚠ The second trap: `--no-llm` is not a cheaper way to get the same thing

`make canonical-drafts CANONICAL_ARGS="--no-llm"` reads like the fast path, and on an
**empty** Bank it is. On an **already-populated** one it used to take work away.

**Measured on the live Bank, 2026-08-17.** A `--no-llm` pass refreshed **1,763 untouched
JDFN drafts**, discarding the 4.2a rewrite on every one. The cohort's mean score fell
**73.0 → 52.73** in thirty-two seconds, and the run reported it as `drafts_refreshed` — a
word that reads like an improvement. Nothing said a capability had been *removed*.

Two things to carry from it:

- **The no-clobber rule protected human work and said nothing about pipeline work.** That
  was a fair place to stop while every run was a full run; it stopped being fair the
  moment the producer had a cheap mode. The producer now **refuses the overwrite by
  default** (`skipped_would_downgrade`, with an audit row saying why) and takes
  `--allow-downgrade` to do it deliberately.
- **A deterministic draft and an LLM draft are not the same artifact at different
  speeds.** The rewrite marks the boilerplate sections present — they are template-
  provided on the JDFN form — which is most of the score difference, and it produces the
  prose a reviewer actually reads.

**Before any producer run against the live Bank, take the `-Fc` dump**
(`docs/runbooks/backup-and-restore.md` §2). It cost nothing here and made the mistake a
choice rather than an incident.

---

## 10. Extending the harness

**Add a subagent** (e.g. a JD Bank `RulebookAgent` that checks rulebook-as-data invariants):
1. `core/src/agents/rulebook.py` extends `BaseAgent`; `agent_id = "rulebook"`.
2. Add to `VALID_AGENTS` in `planner.py`; register in `Orchestrator._agents`.
3. If merge-blocking, add the check in `Orchestrator.run` alongside reviewer/security.
4. Add the Claude Code definition: `harness-claude-code/.claude/agents/rulebook.md` (YAML frontmatter).
5. Unit-test the agent + orchestrator dispatch + planner acceptance.

**Add a gate** (e.g. `bandit`): add to `GATE_COMMANDS` in `core/src/gates/runner.py`, to the
`make gates` script (a `bandit …` line in the `gates`-service command), and to CI. Keep it
Docker-side — it runs in the `gates` service like every other gate.

**Add a store** — think twice. Postgres for transactions/relational, **Neo4j for graph +
vectors** (no pgvector — ADR-002), Redis for the queue. A fourth store needs an ADR + security
review (offline egress rule).

**Change the coding model** — edit `AGENT_MODEL` in `.env`; everything follows (OpenAI-compatible
client → Ollama). Re-run the full suite against a new model before defaulting to it.

---

## 11. Troubleshooting

**"python: command not found" / trying to `pip install` on the host** — that's the Docker-only
rule working as intended (ADR-006). Run tooling via `docker compose exec -T api …` or `make shell`.

**Ollama unreachable from containers** — `docker compose exec api curl http://host.docker.internal:11434/v1/models`
fails. Ensure `OLLAMA_HOST=0.0.0.0 ollama serve` and Docker 24+ (`host-gateway`). macOS/Windows
Docker Desktop Just Works.

**Neo4j vector index missing** — `similar_artifacts` errors "no such index". Re-run `make migrate`.

**Integration tests can't reach testcontainers** — the runner needs the Docker socket + host
override (§7). Check the socket path for your OS. Confirm `docker ps` works as your user.

**Gates green locally but red in CI** — usually the branch-name gate (CI checks
`GITHUB_HEAD_REF`) or integration networking. Read the CI logs before assuming code is wrong.

**Legacy `.doc` won't parse** — python-docx only reads `.docx`. Binary `.doc` needs antiword /
LibreOffice in the ingestion image (Phase 1.3). See the census, `docs/audit/archive-census.md`.

**Subagent emits wrong file-block format** — agents parse ```` ```python path=src/foo.py ````.
Use `qwen2.5-coder:14b` (tested) or adjust the agent's `_extract_*` regex.

---

## 12. Team conventions

**Branch naming** (enforced): `agent/<task-id>-<slug>` for AI work; `feat|fix|chore/<slug>` for
human work; never commit to `main`.

**Commit messages** (convention): `red:` → `green:` → `refactor:` → `docs:`.

**PR checklist** (paste into the PR):
```
- [ ] All gates green in Docker (`make gates`)
- [ ] Coverage ≥ 80% maintained
- [ ] Reviewer subagent approved
- [ ] Security subagent passed (or N/A with justification)
- [ ] ADR added if architecture changed; Mermaid diagrams updated
```

**JD Bank invariants** (from root `CLAUDE.md` — do not violate):
- **Human approval:** canonical JDs are drafts until an HR reviewer approves. Nothing auto-publishes.
- **Rulebook as data:** gates/word-lists/verb-lists live in versioned YAML under `jd_core/rules/` — never hardcoded.
- **Validator as oracle:** LLM-touching tests assert validator post-state, never verbatim model text.
- **Local-first:** Ollama only; JD content never leaves infrastructure we control — no cloud or
  third-party API; it may cross a private network to the internal host `aria-gb10-2` (NN #5 / ADR-003,
  enforced by the 4.6a egress guard). Incumbent names are
  normalized out of *canonical* JDs as a **rulebook quality step** (job-not-person) — not a
  resume-grade privacy gate (these are JDs, not resumes).
- **Storage:** Neo4j = vectors + graph; Postgres = all SQL; Redis/arq = queue. **No pgvector.**
- **Fixtures are sacred:** `fixtures/golden/` + `fixtures/labels/` change only via reviewed PRs.

**ADR-worthy decisions**: new store, orchestration-semantics change, gate-suite change,
offline-inference boundary, public-API break, **or a change to the Docker-only boundary**.

---

## 13. Golden standard — reusing this for new projects

JD Bank is the **reference project** for this harness; the setup here is meant to be copied.
For a new project:

1. **Start from `C:\repos\agent-harnesses-v2`** (the live upstream harness) — it carries the
   Dockerized stack, the subagent pipeline (`core/src/agents/`), gates, memory, and the three
   tool layers. Vendor a copy per **ADR-004** (standalone repo adopting harness conventions).
2. **Adopt Docker-only from day one (ADR-006).** Use the Docker-delegating `Makefile` and the
   `.claude/settings.json` hook from this repo — they are project overrides that should flow
   **upstream** so the harness is Docker-only by default. Record each sync (ADR-004).
3. **Install a project `CLAUDE.md`** at the root with your invariants (see this repo's as a
   template); keep the vendored `harness-claude-code/CLAUDE.md` as the base rules.
4. **Write ADRs early** — repo placement, extract-vs-rewrite (if spinning off code), storage,
   Docker-only. Number project ADRs from 004+ (002/003 are inherited).
5. **Drive every feature through the subagent pipeline** and keep gates green. The gate suite
   *is* the definition of "done."

Deltas from upstream this project introduced (candidates to upstream): Docker-only `Makefile`
gates, Docker-delegating editor hook, `hook-install` git pre-commit, ADR-006. Keep them listed
so the golden standard converges.

---

## Quick reference

| Task | Command (Docker-only) |
|---|---|
| Start stack | `docker compose up -d` (or `make up`) |
| Full gates (incl. integration) | `make gates` → `docker compose run --rm gates …` |
| Fast gates (static + unit) | `make gates-fast` |
| Integration only | `make gates-integration` |
| Migrations | `make migrate` |
| Install git hook | `make hook-install` |
| Shell in container | `make shell` (`docker compose exec api bash`) |
| Similar prior work | `curl "localhost:25800/memory/similar?q=..."` |
| Task lineage | `curl "localhost:25800/tasks/<id>/lineage"` |
| Worker logs | `docker compose logs -f worker` |
| The app / Neo4j Browser | `http://localhost:25800/jd-bank/ui/library` / `http://localhost:25474` |
| Ollama | runs on **`aria-gb10-2`**, not this box (ADR-003) |
| Re-parse the archive | `make ingest JD_ARCHIVE_PATH=/path/to/SFU_JDs` (skip-first on `parser_version`) |
| Rebuild vectors | `make embed` + `make embed-roles` — see `docs/runbooks/reindex.md` |
| Backup / restore | `docs/runbooks/backup-and-restore.md` (⚠ never `--data-only`) |

First PR: run the ParsedJD-schema task from §5 through the pipeline, merge it. Second PR:
Tier-1 exact-dup detection (Phase 3.1) — an early, quantified win over the archive.

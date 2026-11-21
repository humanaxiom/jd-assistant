# Developer Guide — JD Bank (on Agent Harness v2)

> From `git clone` to your first feature merged to `main`. Self-hosted Python
> stack (FastAPI · **Neo4j** · Postgres · Redis · arq), built with
> Claude Code. **Everything runs in Docker — there is no host Python.**
>
> **Revised 2026-11-20.** New to the project? Read [`docs/ORAL-HISTORY.md`](docs/ORAL-HISTORY.md)
> first for why things are the way they are, then [`CURRENT.md`](CURRENT.md) for where each
> fact lives. The working loop is §5.
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
4. [Claude Code](#4-claude-code)
5. [Your first feature — the working loop](#5-your-first-feature--the-working-loop)
6. [The subagent pipeline (inherited, not installed)](#6-the-subagent-pipeline-inherited-not-installed)
7. [The gate suite — what actually blocks you](#7-the-gate-suite--what-actually-blocks-you)
8. [Working with graph memory](#8-working-with-graph-memory)
9. [Async jobs (arq)](#9-async-jobs-arq)
9a. [The JD data layer — parser versions and the two templates](#9a-the-jd-data-layer--parser-versions-and-the-two-templates)
9b. [Adding a rule — or a whole rules file](#9b-adding-a-rule--or-a-whole-rules-file)
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
| PowerShell | Windows PowerShell or `pwsh` | `build.ps1` / `launch.ps1` / `teardown.ps1` and the deploy scripts |
| Node (optional) | 20+ | Only if you install the Claude Code CLI |
| `make` (optional) | any | Convenience task-runner that *invokes* Docker; commands also work raw |

`make` is not a code runtime — it just shells out to `docker compose`. If it's not installed
(common on Windows), use the raw `docker compose …` commands shown alongside each target.

**Inference is not on this box.** Ollama runs on metal on **`aria-gb10-2`**, a trusted
internal host (ADR-003), and the stack reaches it at `http://aria-gb10-2:11434/v1`. It must
serve `nomic-embed-text` (768-dim, matching the Neo4j vector indexes) and the chat model the
rewrite uses. You do **not** start Ollama here. The app, the dashboards and `make gates` all
run without it; only `make embed`, `make embed-roles`, `make canonical-drafts`, the Builder's
assist button and meaning search need it.

Neo4j Browser is at `http://localhost:25474` once the stack is up (creds `neo4j` / `harnesspass`).

---

## 2. Clone and bootstrap

No venv, no `pip install` — the image already contains every Python dependency
(`core/requirements.txt` + `requirements-dev.txt`), and `./core` is bind-mounted into the
containers, so host edits take effect with no rebuild.

```bash
git clone <your-repo-url> JD-Assistant
cd JD-Assistant

cp .env.example .env               # edit only to override defaults — and never commit it

.\build.ps1                        # build the images and prove they are deployable
.\launch.ps1                       # start → healthy → migrate → verify → status
make hook-install                  # Docker-only git pre-commit hook (branch gate + gates-fast)
```

`launch.ps1` starts `postgres`, `neo4j`, `redis`, `api` (FastAPI :8000, published on
25800) and `worker` (arq), applies the migrations, and reports row counts per parser
version, whether CAS is on (read from the running container), and whether the inference
host answers. It fails loudly if any service is not running. The UI is server-rendered
inside `api` under `/jd-bank/ui`; there is no separate frontend service. A fresh clone comes
up with **CAS off** (every request is a synthetic admin) — fine on your own box, never on
one other people can reach. `.\launch.ps1 -NoCas` makes that explicit.

> **A second Bank beside the live one.** A checkout with its own `.env` naming a different
> compose project, image tag and ports runs a fully isolated Bank — that is how the v9 Bank
> (`C:\repos\JD-Assistant-v9`, ports 26xxx) runs next to the live one. `make bank-target`
> prints which Bank the current checkout acts on. Runbook: `deploy/README.md` § *Running a
> second Bank*.

> **Legacy `.doc` files** (thousands in the SFU archive) are read with **antiword**, which is
> in the image (`core/Dockerfile`). python-docx reads only `.docx`.

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

## 5. Your first feature — the working loop

This is the loop every change since September has followed (#219–#224 are worked examples:
read one PR body end to end before your first change).

### 5.1 Branch

```bash
git checkout main && git pull
git checkout -b feat/<slug>          # or fix/<slug>, chore/<slug>
```

The branch must match `(agent|feat|fix|chore)/<slug>`; the pre-commit hook and CI reject
anything else. What may skip the branch (most docs) is listed in `CLAUDE.md` § *Change
workflow*.

### 5.2 Measure before you design

If the change involves a score, a threshold, a count or a verdict, **measure it over the
whole archive first**, in a container against the live Bank
(`docker exec -i jd-bank-api-1 python -I -`, or `make shell`). Twice an obvious design
proved undeliverable once measured. A sample of the newest files is not a sample of the
corpus. Every claim about the archive is checked against the archive.

### 5.3 Failing test first — and break the guard once

Write the test, watch it fail, make it pass, then **break the code it guards and watch it
go red again**. A test you have never seen fail is decoration. LLM-touching code asserts the
validator's verdict, never the model's words.

A new threshold or word list goes in a rules YAML and gets a register entry **in the same
change — the checklist is §9b. If a default looks wrong, register it `open` rather than
quietly changing it.

### 5.4 Gates, then smoke — both yourself

```bash
make gates            # ruff · black · mypy --strict · unit · integration · coverage ≥ 80%
make register-check   # if you touched a rules YAML or the register (CI runs it; `make gates` does not)
make guide-check      # if you touched docs/OPERATOR-GUIDE.md (re-render with `make guide`)
make smoke            # 🔴 the live Bank, end to end — and it must COVER your change
```

`make gates` runs on fixtures, and a fixture cannot be stale. **Add a live check for what you
changed** to `core/tests/live/test_smoke_live_bank.py`, and run it against the real Bank.
**Directive #0: nothing merges while smoke is red**, even when you are sure your change did
not cause it. Read the output, not an exit status; background-task notifications have
reported exit 0 on red runs.

Format with **black** (the gate), never `ruff format`, which rewrites unrelated files.

### 5.5 Open the PR, and let the owner merge

```bash
git push -u origin feat/<slug>
gh pr create
```

The PR body carries the evidence: the commands you ran and their real output, what smoke
covers, and the register ids you took (the next free one is in `HANDOFF.md`; re-check it).
**The project owner merges.** Every feature PR appends to the same smoke file, so after
another PR merges, rebase, keep both tests, and re-run gates **and** smoke before pushing.

### 5.6 Deploy and look

Merged code reaches users only through `.\launch.ps1`. Afterwards, confirm the running API
restarted after your change (`docker logs -t jd-bank-api-1 | grep "Started server"`), run
`make smoke` again, and open the page. Ask: *could the owner deploy and see this tomorrow,
without me?* If not, the task has one more step (Directive #1).

---

## 6. The subagent pipeline (inherited, not installed)

⚠ **Aspirational — the definitions are inert (see the activation note in §4), so no
session runs this today.** It is kept because the DISCIPLINE is the point and it
still binds when one model does every role: write the failing test first, break the guard to
prove it can go red, re-run the gates yourself, read the diff. The `run_pipeline` pipeline in
`core/src/agents/` is a DIFFERENT thing and IS live — see CLAUDE.md § *Two different things
are called "agents" here*.

What the harness designed, for the record; the loop in §5 is what is actually used.

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

| Template | Groups | Parser | Share of archive (measured 2026-08; check the funnel today) |
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

**Scope is still HR's**: almost every register entry is `open` (the register's own header
is the count; only HR-042 and HR-052 are ratified), including HR-194 (may the
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

**Read the version off the constant, not off this page:**
`grep '^PARSER_VERSION' core/src/jd_core/parser/segmenter.py`. At this revision (2026-11-20)
`main` and the live Bank are at v8. **v10** exists on `bank/v9` and the separate v9 Bank
only: it adds a wrapped-heading guard, maps the legacy lettered headings, sets aside (never
drops) working conditions and approvals, removes the qualification and supervisory caps
(HR-308, HR-324), and needs migration 0008. Its design is
`docs/plans/PARSER-V9-LISTS-AND-CAPS.md` **on that branch**. Shipping it to `main` owes the
live Bank a re-parse and a producer pass (`docs/plan.md` § NOW, V4).

**`jd_segmenter_v8`** — the department label the archive actually uses.
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

## 9b. Adding a rule — or a whole rules file

**A new knob in an existing YAML:**

1. Add the value to the YAML and its typed field in `core/src/jd_core/rules/loader.py`.
2. Add an entry to `core/src/jd_core/rules/decision_register.yaml`. Take the next free id
   (`HANDOFF.md` says where to check, on `main` **and** `origin/bank/v9`). Record what HR
   is asked, what ships meanwhile, and where the value came from. A set's
   `current_default` is listed in **sorted** order.
3. `make register`, then commit the regenerated `docs/decisions/HR-DECISION-REGISTER.md` in
   the same commit. CI's drift gate checks it; `make gates` does not.
4. 🔴 **A regex key must end in `_pattern`**, and its flags go **inline** (`(?i)`) with
   `ignore_case: false`. The `_pattern` suffix is how the HR-facing table knows to print
   *"a text pattern — see below"* instead of raw regex
   (`test_no_raw_regex_reaches_the_summary_table`).
5. The layering guard fails on the literal text `src.jd_bank` anywhere under
   `src/jd_core/rules/`, **comments included**.

**A whole new rules file** additionally needs:

- `version: jd_rules_sfu_v4` and a provenance header in the YAML;
- in `loader.py`: a `_RuleFile` subclass, a `<NAME>_FILE` constant, a `Rules` field, and
  entries in `_FILE_MODELS`, `_FLAT_SURFACE_FILES` and, if unhashed, `_UNHASHED_FILES`;
- `rules/__init__.py`: the import **and** `__all__`, in isort order.

**Hashed or not:** a file is hashed if and only if a validator reads it and can move a JD's
score. A parser input no validator reads is unhashed, but it moves `PARSER_VERSION` and
owes an archive re-parse, which is the heavier obligation. Say so in `impact_if_changed`.

**Closed-world guards that fail until you update them** (that is their job):
`test_decision_register.py::test_the_decision_surface_walks_every_rule_file`,
`::test_the_unhashed_files_are_the_ones_that_cannot_change_a_jds_score`,
`test_rewrite_rules.py::test_rewrite_is_an_unhashed_file` and
`test_dedup_rules.py::test_dedup_is_the_fourth_unhashed_file`.
`grep -rn -A1 '"apsa_form.yaml",' core/tests` finds every such list.

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

**Ollama unreachable from containers** — `docker compose exec api curl -s "$OLLAMA_BASE_URL/models"`
fails. Inference is on `aria-gb10-2`, not this box: check that host is up and on the
network, and that `ALLOWED_INFERENCE_HOSTS` lists it. The egress guard refuses any host not
on that list, deliberately. Do not add a host to it "to test"; a new inference host is an
ADR-003 decision.

**A change you merged does not show in the browser** — the dev API does not reliably
hot-reload on a Windows bind mount, and in-process smoke cannot tell. Run `.\launch.ps1`
(it recreates api and worker), then check
`docker logs -t jd-bank-api-1 | grep "Started server"` is newer than the change.

**`curl` against a page returns 303** — CAS is on, and every UI route sends you to sign
in. Verify through the suite, or probe inside the container
(`docker exec -i jd-bank-api-1 python -I -`).

**A junk `core/C:/` directory appeared** — Git Bash rewrote a container path. Delete it, and
prefix such commands with `MSYS_NO_PATHCONV=1`.

**Neo4j vector index missing** — `similar_artifacts` errors "no such index". Re-run `make migrate`.

**Integration tests can't reach testcontainers** — the runner needs the Docker socket + host
override (§7). Check the socket path for your OS. Confirm `docker ps` works as your user.

**Gates green locally but red in CI** — usually the branch-name gate (CI checks
`GITHUB_HEAD_REF`) or integration networking. Read the CI logs before assuming code is wrong.

**Legacy `.doc` won't parse** — python-docx only reads `.docx`; binary `.doc` goes through
antiword, which is in the image. A file antiword cannot read is counted as an extraction
failure on the funnel, never dropped silently. See `docs/audit/archive-census.md`.

---

## 12. Team conventions

**Branch naming** (enforced): `feat|fix|chore/<slug>` (or `agent/<task-id>-<slug>`).
What needs a branch and what may go straight to `main` is `CLAUDE.md` § *Change workflow*:
`core/`, `HANDOFF.md`, `docs/plan.md`, `docs/decisions/**` and build files always need a PR.

**Commit messages:** conventional (`feat(search): …`, `fix(review): …`, `docs: …`), saying
*what changed for whom*. End with the attribution line your tooling requires.

**PR checklist** (the evidence goes in the body, as pasted commands and their output):
```
- [ ] Failing test written first; the guard broken once to prove it can go red
- [ ] make gates green (full suite if Postgres/Neo4j behaviour is involved)
- [ ] make register-check / make guide-check, if a rules YAML or the guide changed
- [ ] make smoke GREEN — and it covers this change (a live check added to the smoke file)
- [ ] Reachable from the UI; ships through build.ps1 / launch.ps1 with no assistant
- [ ] New HR register ids named, and checked free on main and bank/v9
- [ ] ADR added if architecture changed
```
The project owner merges.

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
5. **Keep gates green, and add a live smoke check from the first feature.** The gate suite
   is the floor, not the definition of done. This project learned that a green suite on
   fixtures says nothing about the live system (see `docs/ORAL-HISTORY.md` §6 and
   `docs/HARNESS-LESSONS-DELIVERY-BLINDNESS.md`).

Deltas from upstream this project introduced (candidates to upstream): Docker-only `Makefile`
gates, Docker-delegating editor hook, `hook-install` git pre-commit, ADR-006. Keep them listed
so the golden standard converges.

---

## Quick reference

| Task | Command (Docker-only) |
|---|---|
| Build / start / stop | `.\build.ps1` · `.\launch.ps1` · `.\teardown.ps1` |
| Which Bank am I on? | `make bank-target` |
| **Live end-to-end check (gates shipping)** | `make smoke` |
| What drafts actually contain | `make bank-audit` (exits 2 while anything is off 100%) |
| HR register / guide | `make register` + `make register-check` · `make guide` + `make guide-check` |
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

First change: pick the top open item in `HANDOFF.md`, and work it through the loop in §5.

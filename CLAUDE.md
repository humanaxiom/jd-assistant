# jd-bank — project invariants

## What this is
JD Bank: dedup + harmonization + composer over the SFU JD archive.
Repo: C:\repos\JD-Assistant (standalone project repo — see docs/adr/ADR-004-repo-placement.md).
Plan: docs/plan.md. Rulebook: docs/rulebook/sfu-jd-standards.txt.

## Read on every session
harness-claude-code/CLAUDE.md — base harness rules (gates, git workflow, TDD order, code
rules) apply here in full. They are vendored in-repo; do not re-open inherited ADR-002
(Postgres/Neo4j split) or ADR-003 (offline Ollama).

Also read HANDOFF.md for current phase/state (it, not this file, tracks what is merged vs open).
Two docs to know:
- `docs/subagent-model-strategy.md` — which model tier (Opus/Sonnet/Haiku) to dispatch a
  subagent at. Reviewers are always Opus; never downgrade a faithful port, rulebook/policy
  semantics, a security-touching diff, or anything changing a decision parameter.
- `docs/decisions/HR-DECISION-REGISTER.md` — generated register of every non-trivial rulebook
  default — **all entries `open`**; SFU HR has ratified nothing yet. **Do not restate the entry
  count here: the generated register's own header is the count of record.** (This line used to
  hardcode "192 entries"; it went stale twice, and was behind both the register header and
  `decision_register.yaml` when it was removed on 2026-08-05.) **Standing rule: any
  non-trivial metric/rule must be YAML-configurable and registered in the same PR; if a default
  looks wrong, register it as `open`, don't quietly patch it.**
  A `ratified` entry **must** carry `decided_by` / `decided_on` / `decision_note` or the rulebook
  fails to load — that is how an HR ruling gets recorded. Never a side file.
- `docs/baseline/README.md` — **the archive baseline (Phase 2.5), measured over all 14,565 JDs.**
  **EVERY CLAIM ABOUT THE ARCHIVE MUST BE CHECKED AGAINST THE ARCHIVE** — this rule has already
  caught the Phase 0 census, two coders, a reviewer *and* the orchestrator. A sample of the newest
  files is not a sample of the corpus.
- `docs/decisions/HR-DECISION-MATRIX.md` (the single consolidated HR review + decision matrix — what
  HR must decide) + `POST-REVIEW-CHANGE-PLAN.md` (the engineering counterpart — what we change when
  they rule). **The three "our-defect" decisions were already fixed + re-baselined in Phase 2.6
  (HR-120/121/122), so HR is reading corrected numbers; the rest need HR.** The matrix is HR-facing —
  keep it free of internal codenames (no `hris`) and cite only official SFU resources (JD Toolkit,
  the APSA/APEX/Poly template).

Paths: `C:\repos\agent-harnesses-v2` is the **live upstream harness** — this repo vendors a copy
of it (kept in sync; subagents subsystem reconciled 2026-07-10, see ADR-004). `C:\repos\jdbank`
is STALE (abandoned v1 attempt). The live project repo is `C:\repos\JD-Assistant`.

## Change workflow — what needs a PR and what does not

**This OVERRIDES the vendored harness rule "NEVER commit to `main`" for the doc cases
below.** The harness rule assumes every change can break something; in this repo most
documentation cannot, and each PR costs two full CI runs (~20 min of Actions minutes) to
prove it. 53 of 60 CI runs in one four-day stretch were largely doc churn — that is the
abuse this section exists to stop.

**Commit straight to `main` (no branch, no PR):**
- Any file under `docs/` **except** `docs/plan.md` and `docs/decisions/**`
- `README.md`, `DEVELOPER_GUIDE_1.md`, `docs/OPERATOR-GUIDE.md`, status/audit write-ups
- Generated report artifacts (`docs/canonical/*.json`, `docs/baseline/*.json`)
- Typo / formatting / link fixes anywhere

**Still requires a branch + PR:**
- 🔴 **Anything under `core/`** — code, tests, rules YAML. No exceptions.
- 🔴 **`HANDOFF.md` and `docs/plan.md`** — the two source-of-truth documents. A PR is how a
  change to "what we are doing next" gets seen rather than absorbed.
- 🔴 **`docs/decisions/**`** — the HR register and matrix are the decision record; CI's
  register gate validates them and a hand-edit must be caught.
- 🔴 **`CLAUDE.md`, `.github/**`, `docker-compose*.yml`, `Makefile`** — anything that
  changes how the project is built, gated, or governed.

**Rules that do not relax:**
- `make gates` green before ANY commit that touches `core/` — direct-to-main or not.
- A doc commit still gets a real message. "docs: fix typo" is fine; empty is not.
- If a doc change and a code change belong together (a rulebook knob and its register
  entry), they ship in the SAME PR — never split to dodge a branch.

## Subagents subsystem (from the harness)
`core/src/agents/` provides a Planner→Tester→Coder(loop)→Reviewer→Security→Docs pipeline
(`orchestrator.py`, dispatched via the `run_pipeline` arq job). Reviewer approval + security
pass are merge-blocking. Claude Code subagent definitions live in
`harness-claude-code/.claude/agents/`. To activate them (and the `.claude/settings.json`
hooks: no-commit-to-main, ruff auto-fix) for sessions run from the repo root, a root
`.claude/` is required — not yet set up.

## Coordinating subagents — trust & verification (harness lessons; see docs/HARNESS_LESSONS.md)
- **A subagent's claim of green is not evidence of green.** Require the pasted command and its
  real output; if a report only summarizes a diff, treat the work as UNVERIFIED and re-run the
  gate yourself before committing. This is cheap and has already caught real defects.
- **Re-run `make gates` yourself before committing subagent work** — and pick the gate by what
  the diff touches, not by what is fastest. If correctness depends on how a real Postgres/Neo4j/
  driver behaves (schema, SQL, stores, embeddings, dedup, migrations), `make gates-fast` cannot
  prove it — run the full `make gates`. Pure functions / rules YAML / docs: `gates-fast` is enough.
- 🔴 **`make gates` is NOT the whole gate.** CI also runs the **HR register drift check**,
  which `make gates` does not. Edit `decision_register.yaml` or any rules YAML and you MUST
  run `make register` and commit the regenerated `docs/decisions/HR-DECISION-REGISTER.md` in
  the same commit — a green local suite says nothing about it, and that is exactly how a
  merge to `main` failed CI on 2026-08-27. `make register-check` verifies it locally.
- **Read the diff, don't just read the report.** A missing `DEFAULT` or foreign key is visible in
  a 50-line diff and invisible in a prose summary.
- **Check your prompt before blaming the agent.** A thin report usually means a thin instruction
  (asking for "a diff summary" and getting one is a prompt bug, not agent misbehaviour).
- **Prefer fixing the agent definition over re-explaining in the prompt.** A prompt fix helps one
  run; an edit to `harness-claude-code/.claude/agents/` helps every future run.
- **Verify state against the remote before trusting HANDOFF.md.** Local branches and handoff notes
  lag; `git fetch` + a PR status check costs seconds. Record ratified decisions in the register/ADR,
  not just in chat — conversation state is lost at session end.

## 🔴 DIRECTIVE #1 — TESTED, AND DEPLOYABLE WITHOUT THE ASSISTANT

**Set by the project owner, 2026-08-28. It outranks everything below it.**

> **Every step must leave the code TESTED and every feature DEPLOYABLE THROUGH THE
> SCRIPTS, by a person, with no assistant in the loop.**

A change is not done when it works on this box. It is done when:

1. **It is tested** — `make gates` green, the failing test written FIRST, and the guard
   broken once to prove it can go red. A subagent's claim of green is not evidence.
2. **It ships through the scripts** — `quickstart.ps1` (dev) and `deploy/bundle.ps1` +
   `deploy/install.ps1` (fresh, offline box). If a human needs a session with an
   assistant to reproduce it, the step is NOT finished.
3. **It is discoverable** — a feature nothing links to has not been delivered. That is
   not a slogan: the live funnel shipped 2026-08-27 with no nav entry and read as
   "still the old dashboard" for a day.
4. **`make deploy-check` is green** — enforced in CI as *"Gate: deployable offline"*, so
   this is a build failure, not a good intention.

⚠ **The trap this exists to stop:** work that is real, correct and green *here*, and
unreachable to anyone else. Ask at the end of every task: **"could the owner deploy and
see this, tomorrow, without me?"** If not, the task has one more step.

Runbook: [`deploy/README.md`](deploy/README.md).

## Non-negotiables
1. HUMAN APPROVAL: canonical JDs are drafts until an HR reviewer explicitly approves.
   Nothing auto-publishes. Gate overrides require a written reason in the audit log.
   Editing a PUBLISHED JD mints a **new DRAFT** and leaves the prior version published until
   its replacement is approved; `approve` then **supersedes** any other live published version
   of the cluster (`FOR UPDATE` + a `review.superseded` audit row), so **a cluster has exactly
   one live PUBLISHED version**. ARCHIVED is settled — editing it is refused (`802bff0`).
2. RULEBOOK AS DATA: gates, word lists, verb lists, KSA modifiers, restricted titles
   live in versioned YAML/JSON under src/jd_core/rules/ — never hardcoded in logic.
3. VALIDATOR AS ORACLE: tests on LLM-touching code assert validator post-state,
   never verbatim model text.
4. TDD + GATES: failing test first. Every rulebook gate has a failing-fixture test and
   a passing-fixture test. make gates must be green before any commit.
5. SELF-HOSTED INFERENCE ONLY: all inference runs on Ollama on infrastructure **we control**.
   **No third-party or cloud LLM API, ever — no vendor egress of JD content.** That is the
   real invariant; the older wording ("JD content never leaves this machine") is now
   **false in the letter**: Ollama runs on `aria-gb10-2`, a trusted internal host, so JD text
   **does** cross a private network to be embedded (Phase 3.2 onward). See ADR-003 for the
   topology and the trust assumption. **If the inference host ever moves off a trusted
   segment, this becomes a FIPPA question and must be re-decided, not silently carried.**
   Incumbent names are normalized out of canonical JDs at ingestion as a RULEBOOK quality
   step (describe the role, not the person) — NOT a resume-grade privacy gate. These are JDs,
   not resumes.
6. PROVENANCE: every canonical JD traces to sources, cluster, validation reports, and
   reviewer actions. Audit log is append-only.
7. FIXTURES ARE SACRED: fixtures/golden/ and fixtures/labels/ change only via reviewed
   PRs. Every pilot bug becomes a regression fixture.
8. DOCKER-ONLY (ADR-006): all code, tests, gates, linters, and migrations run in Docker.
   NO host Python/venv/pip/pre-commit. `make gates` runs the FULL suite (incl. integration
   via testcontainers) in the one-shot `gates` compose service — self-contained, CI-identical.
   Testing is non-negotiable and has no host fallback. The one exception is **Ollama**, which
   runs on metal — on `aria-gb10-2`, **not** on the dev box. The `gates` container **can** reach
   it (verified: `nomic-embed-text`, 768-dim, from inside `gates`), so an inference-touching
   test is NOT blocked by the container being self-contained. See DEVELOPER_GUIDE_1.md.

## Neo4j — roles, do not conflate
- Harness agent memory (day 1, via docker compose): lineage graph + vector artifact store.
  Query with /memory-query before implementing anything.
- **Archive document vectors** — `jd_document_embeddings` over `(:JDDocument)`, one node per
  **source file** (migration `002`, written by `make embed`). JD document + section embeddings,
  768-dim cosine; the retrieval store for dedup Tier-3, clustering, and archive search — NOT
  pgvector.
- **Harmonized role vectors** — `jd_role_embeddings` over `(:JDRole)`, one node per **cluster**
  (migration `003`, written by `make embed-roles`; read by Builder search and the near-duplicate
  authoring guard). **A separate label and index from `jd_document_embeddings` on purpose**
  (`cadfc30`): a role is a different unit from an archive document — one node distilled from many
  files — and folding them together would quietly corrupt the next `MATCH (d:JDDocument)` corpus
  count. Covers **every current-version role, drafts included** (the use is seeding a clone, not
  publishing); each node carries `status` so a hit is labelled honestly. **Deliberately NOT wired
  into `approve`** — publishing must not depend on the GPU, and network I/O inside the review
  transaction would hold the `SELECT … FOR UPDATE` lock. Run it after, like `make embed`.
- JD Bank domain overlap graph (Phase 7, deferred): role/duty overlap graph. NOT in MVP.

## External read-only paths
- C:\repos\hris — extract modules from here; never modify
- C:\repos\hris\fixtures\SFU_JDs — JD archive; read-only during Phase 0

## Known open flags
- Territorial acknowledgement wording: verify against SFU's current official text before
  any external distribution. Phase 6 sign-off task — blocks publish, not development.
- Footer wording lives in a single config constant — never inline it.
- ~~Stale `jdbank` path references linger in older notes — scrub on a chore branch.~~
  **SCRUBBED (verified 2026-07-21):** a repo-wide search found no reference that treats
  `C:\repos\jdbank` as authoritative. The only mentions are the intentional "jdbank is
  STALE — ignore it" notes in ADR-004 / HANDOFF / this file (keep those), plus the
  unrelated `jdBank.ts` hris TypeScript filename in `docs/audit/hris-reuse-map.md`.
  (`agent-harnesses-v2` is NOT stale — it is the live upstream harness.)

## Stack
Python 3.11+ · FastAPI · **PostgreSQL 16 (all relational/transactional SQL)** · **Neo4j
(two vector indexes — documents + roles, 768-dim cosine, `nomic-embed-text` — + graph
memory)** · **Redis + arq
(queues only)** · Ollama · pytest / ruff / black / mypy --strict
Infrastructure: docker compose (postgres, neo4j, redis, api, worker) + Ollama on host metal
**No pgvector.** Vectors live in Neo4j per inherited ADR-002. Postgres is the relational
ledger; Neo4j is the vector + graph store; Redis is the arq broker. Do not reintroduce
pgvector (older HANDOFF/plan stack lines that mention it are stale — see ADR-005 §Architecture).

# VPFA JD Bank: software engineering plan for a focused spinoff

**Status:** proposal, written 2026-11-24, with the owner's rulings of the same day in §0. Nothing in it is built yet. The Campus Services departments go into the **spinoff's** copy of `org_units.yaml` (§5.2); the parent's rulebook is deliberately not changed.
**Written for:** the engineer who will build and run the spinoff, a colleague or the owner's
second account working with Claude Code on a Claude Team (Premium seat) account, and the
Claude Code sessions they run. It assumes no access to this machine, to this machine's
assistant memory, or to the person who wrote it.
**Companion documents:**
- [`VPFA-SPINOFF-BRIEF.md`](VPFA-SPINOFF-BRIEF.md), the short version for policy and risk
  readers;
- [`../ORAL-HISTORY.md`](../ORAL-HISTORY.md), how the parent project got here and why its
  rules exist.

> **The one-paragraph version.** Build a small, separate application for the VPFA portfolio
> (VPFA office, IT Services, Safety & Risk Services, Facilities Services, Campus Services)
> with four surfaces: the **Bank** (read the harmonized JDs), the **Builder** (write a new
> JD against SFU's standards), the **funnel** (where the archive went, scoped to VPFA) and
> the **Compensation Requisition Form**. It does **not** re-run the parent's pipeline. It
> **imports a versioned snapshot** of the parent JD Bank, which stays the only producer.
> About half of the parent's code is copied, mostly unchanged. The pipeline half stays
> behind on purpose. Estimate: **6–9 weeks** to a pilot for one engineer working with Claude Code,
> then a 2-week pilot.

---

## 0. Decisions this plan needs from the owner

### ✅ Owner rulings, 2026-11-24

| # | ruling |
|---|---|
| **D1** | **Accepted:** import the whole Bank and show VPFA by default |
| **D2** | **Everything under VPFA is in scope**, so **Finance is included** |
| **D3** | **Residence and Housing** and **Bookstore** belong to Campus Services. Other spellings and neighbouring departments are listed in §2 as still to confirm |
| **D4** | **Accepted:** minimal review in the spinoff. **Reviewers:** Denise (VPFA office), Galib (Chief, Safety & Risk Services, or a designate), and two more for the other units, TBD |
| **D7** | **VPFA acts as HR's proxy.** VPFA rules on the register entries the spinoff inherits, and VPFA reviewers approve its JDs (§5.6, §7.1) |
| D5, D6 | Not yet ruled. The recommendations below stand |

⚠ **What D7 changes.** The parent's register entries are HR's to ratify. In the spinoff,
VPFA ratifies them as HR's proxy. Record each ratification in the spinoff's register with
`decided_by` naming the VPFA person, and a `decision_note` saying they acted as HR's
proxy. A value VPFA changes then **differs from the parent's** for the same HR id. Show
that difference on the spinoff's register page, so nobody reads a VPFA ruling as HR's.

The original recommendations follow, as the record of what was proposed.

| # | decision | recommendation | why | changes |
|---|---|---|---|---|
| **D1** | Which roles does the spinoff hold? | **Import the whole SFU Bank and show VPFA by default.** Builder search can widen to "all of SFU", and every result is labelled with its unit | Measured 2026-11-24 on the live Bank: **755 of 2,499 drafts record no department**, so no filter can say whether they belong to VPFA. A VPFA-only import silently drops VPFA roles whose files never named their department. The parent learned this as *a filter must publish what it cannot see* | §3, §5.2 |
| **D2** | Is Finance in scope? | **Yes**: it is a VPFA child unit in the parent's rulebook (`org_units.yaml`) | You listed ITS, VPFA, SRS, Facilities and Campus Services, but the rulebook rolls Finance up into VPFA. Leaving it out is a deliberate edit, not a default | §5.2 |
| **D3** | What is in Campus Services? | **An owner/VPFA list of departments, supplied before build.** Today the unit has **no departments assigned**, so it shows 0 roles | Candidates from the live Bank (not assigned to any unit today): Residence and Housing (25 roles), Bookstore (13), and the parent's open questions about Campus Security and Ancillary Services. **Never infer membership** | §5.2 |
| **D4** | Does the spinoff approve and publish? | **Yes, minimally.** A reviewer queue with approve and reject, with gate re-check and audit row | Non-negotiable #1 (nothing auto-publishes) needs a named human approver somewhere. Without it, a Builder draft has nowhere to go. A risk officer will ask who approves | §5.5 |
| **D5** | Where does it run? | **An SFU-managed VM with Docker**, behind TLS, CAS sign-in on, inference on `aria-gb10-2` or a successor host ITS controls | The parent ran on a desk box with CAS sometimes off, and that produced its one security incident (§9, L-17) | §4, §7 |
| **D6** | Repo name and home | `vpfa-jd-bank` (or similar) under the same GitHub organization, **private**, with the new owner as admin | A **new repo**, not a fork: the parent's history is ~300 commits of pipeline work the spinoff does not carry, and its CI gates things the spinoff does not have | §6 |
| **D7** | Who owns the HR decision register entries the spinoff inherits? | **The same HR owners as the parent.** The spinoff copies only the entries for rules it loads, and keeps their ids | A second, diverging register would let the two apps silently apply different standards to the same JD | §5.6 |

---

## 1. Scope

### In

| surface | what a user does | parent route it comes from |
|---|---|---|
| **Bank** (library) | browse roles by unit, read a role's harmonized JD, see its source files and positions, search by title, meaning or position number | `/jd-bank/ui/library`, `/role/{id}`, `/jd/{id}`, `/unit/{slug}` |
| **Builder** | start from a role or a blank form, answer guided questions, see live compliance against the JD Toolkit, get a suggested summary, see near-duplicate roles, export to HR's Word templates, submit a draft | `/jd-bank/ui/compose/*` |
| **Funnel** | see where the archive's files went, scoped to VPFA, with the three numbers on every facet: matched, not matched, could not evaluate | `/jd-bank/ui/funnel`, `/unit/{slug}` |
| **Compensation Requisition Form** | download SFU's CRF pre-filled from a role or a Builder draft, choosing request type A–E and one position | `/role/{id}/comp-requisition` |
| **Sign-in and roles** | SFU CAS; `author`, `reviewer`, `admin` | `routes/auth.py`, `routes/admin.py` |
| **Review** (per D4) | reviewer approves or rejects a submitted draft | `routes/ui.py` review pages, trimmed |
| **Guide** | the in-app operator/user guide | `/guide` |

### Out, deliberately

- **The pipeline:** ingest, parse, dedup, cluster, harmonize, the LLM rewrite and audit,
  baseline, field audit, singletons, bank audit. These stay in the parent, which remains
  the **only producer** of harmonized roles.
- **The static dashboards** (`/dashboard/baseline`, `/dedup`, `/clusters`). The parent
  already plans to retire them; the funnel replaces them.
- **The harness agent pipeline** (`core/src/agents/`, `core/src/memory/`) and the
  vendored `harness-claude-code/`. Application code with no user-facing purpose here.
- **The model-read query plan** (I3), which is switched off in the parent pending the
  model decision (Q8).
- Tracks F, G, H, J3, J5 and K1 from the parent plan. Each can be ported later once the
  parent ships it.

---

## 2. What the archive looks like through a VPFA lens

Measured on the live parent Bank, 2026-11-24, using the app's own unit code
(`resolve_unit` in `jd_bank/library/units.py`). **These are dated numbers; re-measure
before quoting them.**

| unit (parent `org_units.yaml`) | drafts in unit |
|---|---|
| VPFA, including all children | **128** |
| Facilities Services | 50 |
| IT Services | 41 |
| Finance | 22 |
| Safety & Risk Services | 9 |
| Campus Services | **0**: no departments assigned (D3). Owner-confirmed 2026-11-24: Residence and Housing (25), Bookstore (13) |
| **No department recorded** (any unit) | **755 of 2,499** |

What this means for the design:
1. **The VPFA slice is small, and that is fine.** A hundred-odd roles fit comfortably in
   one reading list. The value is in the Builder, which can draw on all of SFU's roles.
2. **A third of the Bank cannot be placed in any unit.** Every VPFA view must show the
   third number: *department not recorded*. Otherwise a vice-president is handed a
   confident wrong count of their own portfolio.
3. **Unit membership is people-work.** The parent has an exact list per unit, never a
   pattern, and six departments still unassigned. The spinoff inherits that list and that
   discipline.

**Campus Services: still to confirm** (live Bank, 2026-11-24; role counts by department as
written on the files):

| department string | roles | question |
|---|---|---|
| `bookstore/spirit shop`, `bookstore and spirit shop` | 4, 1 | the same unit as Bookstore? |
| `residences` | 2 | the same as Residence and Housing? |
| `ancillary services`, `ancillary services, meetings, event, conferences services`, `ancillary office administration` | 6, 1, 1 | Campus Services? |
| Meeting, Event and Conference Services (six spellings) | 6 | Campus Services? |
| `residence life`, `avp students and international, residence life` | 3, 1 | Student Services rather than Campus Services? |
| `parking services` | 1 | currently in **Facilities**; move? |

---

## 3. Architecture

### 3.1 Shape

```
                ┌──────────────────── PARENT: JD Bank (C:\repos\JD-Assistant) ─────────────────┐
 archive  ──►   │ ingest → parse → dedup → cluster → harmonize → LLM rewrite/audit → Bank      │
 (14,565 files) │                                                         │                    │
                │                                       make bank-snapshot (NEW, §5.1)         │
                └─────────────────────────────────────────────────────────┼────────────────────┘
                                                                          │  snapshot file:
                                                                          │  manifest + JSONL + sha256
                                                                          ▼
                ┌──────────────── SPINOFF: VPFA JD Bank (new repo) ──────────────────────────────┐
                │  make import-snapshot  →  Postgres (roles, sources, parses, drafts, audit)     │
                │                        →  make embed-roles → Neo4j (role vectors only)         │
                │                                                                                │
                │  FastAPI + Jinja (server-rendered, no JS build)                                │
                │   Bank · Builder · Funnel · CRF · Review · Guide        CAS sign-in, CSRF, CSP │
                │                                                                                │
                │  Ollama on an ITS-controlled host: nomic-embed-text (search, near-dup guard),  │
                │  gpt-oss:120b (Builder summary suggestion only)                               │
                └────────────────────────────────────────────────────────────────────────────────┘
```

### 3.2 Decisions, and the ADR each one needs

| | decision | rationale | ADR in the new repo |
|---|---|---|---|
| A1 | **The parent is the only producer; the spinoff imports snapshots** | One place decides what a harmonized JD says. The pipeline is roughly half of the parent's code, and every fidelity lesson in §9 came from it. A spinoff that re-ran it would re-learn them | ADR-001 |
| A2 | **Snapshot = a file, not a live database link** | No network path between the two apps, no shared credentials, an auditable artefact per import (sha256 + manifest), and the spinoff can be rebuilt from the file alone | ADR-001 |
| A3 | **Imported content is read-only; local work is new drafts** | Non-negotiable #1 carries over: editing a role mints a DRAFT, and a reviewer approves it. A re-import never overwrites a local draft, because local drafts are keyed by their own ids | ADR-002 |
| A4 | **Same stack as the parent:** Python 3.11, FastAPI, Jinja, PostgreSQL 16, Neo4j for vectors, **no Redis/arq** | Copying code across stacks is a rewrite; copying it within one is a port. Redis and arq served the pipeline and the harness agent jobs, and neither comes across | ADR-003 |
| A5 | **Neo4j holds role vectors only** (`jd_role_embeddings`). No document vectors | The Builder's search and near-duplicate guard read role vectors. Document vectors served dedup, which stays in the parent | ADR-003 |
| A6 | **Self-hosted inference only, on a host SFU controls** | The parent's invariant, ratified 2026-07-20: no cloud or third-party model API, ever. If the inference host moves off a trusted segment, that is a FIPPA question to re-decide, not to carry silently | ADR-004 |
| A7 | **Docker-only**: tests, gates, migrations and probes all run in containers | It is why CI and the dev box never disagreed about green in the parent | ADR-005 |
| A8 | **CAS on by default; the app refuses to start without it outside `ENV=dev`** | Fixes the parent's one incident at the design level (L-17) | ADR-006 |
| A9 | **Rulebook as data, with a register** | Every non-trivial threshold or list lives in YAML with a register entry; the build refuses an unregistered knob | ADR-007 |

### 3.3 Data model (spinoff)

| table | from | notes |
|---|---|---|
| `snapshots` | new | one row per import: parent commit, parser/prompt/rules versions, manifest sha256, counts, importer, imported_at |
| `clusters` | snapshot | role identity; stable content-derived ids from the parent |
| `canonical_jds` | snapshot + local | imported current versions, plus local Builder and edit drafts. `origin` = `imported` / `local` |
| `source_documents` | snapshot | metadata and filename only (filenames carry PeopleSoft position numbers); **no original files** |
| `parsed_jds` | snapshot | the current parse of each member source, used by the source-JD page and the CRF's fill-from-sources |
| `users`, `user_roles`, `sessions` | parent migration 0004/0006 | CAS identity, CSRF token per session |
| `audit_log` | parent migration 0005 | append-only with the hash chain; every import, submit, approve and reject writes a row |

Write **one fresh initial migration** for this schema. Do not replay the parent's seven
migrations: they record the parent's history, not the spinoff's.

---

## 4. Environments

| env | where | CAS | inference | data |
|---|---|---|---|---|
| dev | engineer's machine, Docker | off allowed, **loopback ports only** (`127.0.0.1`) | ITS host | a snapshot of the parent Bank |
| pilot | SFU VM, TLS at the edge | **on** (startup refuses otherwise) | ITS host | the same snapshot, re-imported on a schedule the owner sets |
| prod | as pilot, after sign-off | on | ITS host | as pilot |

Ports: use a non-default range (the parent uses 25xxx and 26xxx, Codex uses 27xxx); pick
28xxx. Every origin users reach the app on must be in `ALLOWED_SERVICE_ORIGINS` exactly,
including scheme and port, or CAS sign-in falls back silently (L-18).

---

## 5. Work breakdown

Each phase is done only when Directive #1 holds: tested (failing test first, the guard
broken once), deployable through the scripts by a person, reachable from the UI,
`deploy-check` green, and `make smoke` green **and covering the change**.

### 5.0 Phase 0: foundation (2–3 days)
- New repo (D6), branch protection, CI: lint (ruff), format (**black**), types
  (mypy --strict), unit + integration (testcontainers), register drift check, deploy-check.
- `CLAUDE.md`, `CURRENT.md`, `HANDOFF.md` and `docs/plan.md` in the parent's pattern (§8.3).
- ADR-001 to ADR-007 (§3.2), each half a page.
- `docker-compose.yml` (api, postgres, neo4j), `build.ps1` / `launch.ps1` /
  `teardown.ps1`, plus `.sh` equivalents if the host is Linux.
- **Exit:** an empty app answers `/health` in CI and on the dev box; `make gates` green.

### 5.1 Phase 1: the snapshot contract (4–6 days; half of it is in the PARENT)
- **Parent (a PR into the parent repo):** `make bank-snapshot` writes `snapshot-<date>/`:
  - `manifest.json`: parent git sha, `PARSER_VERSION`, prompt version, `rules_version`,
    row counts per file, a sha256 per file;
  - one JSONL each for clusters, current canonical versions, source documents (no file
    bodies) and current parses;
  - the funnel's archive-side counts as they stand, so the spinoff's funnel can show where
    the archive went without holding the archive.

  Every count in the manifest is computed with the parent's **own** predicates, not
  hand-written SQL (L-01).
- **Spinoff:** `make import-snapshot SNAPSHOT=<dir>`:
  - verifies every sha256;
  - imports in one transaction, upserting by the parent's stable ids;
  - writes a `snapshots` row and an audit row;
  - **refuses** a snapshot whose manifest counts do not match what landed, then reports
    the counts it found in the Bank, not the counts it intended (L-01).

  A second import of the same snapshot writes nothing.
- **Tests:**
  - a golden mini-snapshot fixture: 10 roles, both forms, one with no department, one
    "Untitled Position";
  - a tampered-hash test;
  - a count-mismatch test;
  - an idempotency test;
  - a test that a local draft survives a re-import.
- **Exit:** the dev box holds a full parent snapshot, and the spinoff's counts equal the
  manifest's.

### 5.2 Phase 2: the Bank (3–5 days)
- Port `jd_bank/library` (`service.py`, `units.py`, `models.py`, `positions.py`,
  `scopes.py`), `routes/library.py` (minus `/collection`), and the templates `library.html`,
  `role_detail.html`, `jd_view.html`, `unit.html`, `archive.html` and `_position_files.html`.
- **Default scope = VPFA and its children** (D1, D2), with a visible switch to all of SFU.
  Every unit view shows **in unit · not in unit · department not recorded** (L-09).
- `org_units.yaml` copied from the parent, plus the Campus Services list (D3).
- Search: title, trigram (parent migration 0007's indexes), meaning (role vectors) and
  position number (HR-339).
- **Exit:** a VPFA user signs in and lands on the VPFA library, with the three numbers on
  every unit.

### 5.3 Phase 3: the Builder (5–8 days)
- Port `jd_bank/composer` whole (search, clone, answers, questions, assemble, validate,
  persist, duplicates, assist, the WJQ path), `routes/compose_ui.py`, `routes/compose.py`,
  `routes/drafts.py`, and the templates `compose_new.html`, `compose_search.html` and
  `my_drafts.html`.
- Port `jd_core/models`, `jd_core/quality`, `jd_core/wjq_form_check` and `jd_export`
  (Word export on HR's 2024 APSA template and the WJQ form).
- **Clone from a source document:** the parent re-parses the file. The spinoff has no
  files, so it clones from the **imported parse**. Change `clone/{source_document_id}` to
  read `parsed_jds`. This is the one place a `jd_core.parser` import is cut.
- The Builder's summary suggestion uses `ChatClient` with the **context-window guard
  (HR-341)** and a registered request timeout (see L-21).
- **Exit:** a user clones a VPFA role, edits it, sees the compliance panel change, exports
  a .docx that reads back cleanly, and submits; the draft appears in My drafts labelled as
  a Builder draft.

### 5.4 Phase 4: the Compensation Requisition Form (2–3 days)
- Port `jd_bank/forms/comp_requisition.py`, `jd_export/comp_requisition.py` (pypdf),
  `jd_bank/positions` (the filename position reader, HR-325 … HR-331) and
  `comp_requisition.html`. Ship SFU's blank CRF PDF inside the image (the parent's copy
  sits in `fixtures/hr/`).
- Offer the CRF from a **Builder draft** as well as a role. The parent lists this as a
  follow-up that J5 needs.
- **Exit:** request types A–E each produce a PDF whose fields read back as expected; only
  the picked position is ever written (the parent's 58-ids defect, 2026-11-19).

### 5.5 Phase 5: review, and the funnel (4–6 days)
- **Review (D4):**
  - the queue (paged, title filter), the detail and diff pages, approve and reject;
  - approve re-checks the gates at that moment, takes `SELECT … FOR UPDATE`, supersedes
    the prior published version, and writes a `review.superseded` audit row;
  - porting `jd_bank/review` and the trimmed `routes/ui.py` review routes covers it.
- **Funnel:**
  - port `jd_bank/library/funnel.py` and `funnel.html`;
  - the archive stages come from the **snapshot manifest**, labelled with the snapshot's
    date;
  - the role stages come from the spinoff's own database;
  - scope defaults to VPFA;
  - every stage says what it counts.
- **Exit:**
  - a reviewer approves a Builder draft;
  - the funnel's published count moves by one;
  - the audit chain verifies.

### 5.6 Phase 6: rulebook and register (2–3 days, run alongside Phases 2–5)
- Copy only the rule files the ported code loads. Expect `gates`, `action_verbs`,
  `apsa_form`, `cupe_form`, `wjq`, `qualifications`, `titles`, `org_units`,
  `comp_requisition`, `search`, `embeddings`, `rewrite` (assist and HR-341 only),
  `scoring`, `thresholds`, `textnorm`, `markers`, `boilerplate`, `patterns`,
  `functional_families` and `rule_catalog`. **Let the loader tell you**: start with
  nothing, add each file when a test fails for want of it.
- Copy `decision_register.yaml` entries for exactly those knobs, **keeping their HR ids**
  (D7). Regenerate the register document; CI checks drift.
- **Exit:** the loader refuses an unregistered knob (break it once to prove it).

### 5.7 Phase 7: sign-in, security, deployment (4–6 days)
- Port `routes/auth.py`, `routes/admin.py`, `services/*`, `csrf.py`,
  `security_headers.py`, `service_origin.py`, `readiness.py` and `deps.py`.
- **Fail closed:** outside `ENV=dev`, startup refuses CAS off, an http or loopback
  service origin, or an empty `BOOTSTRAP_ADMINS` (L-17).
- **Deployment:**
  - `deploy/bundle.ps1` + `deploy/install.ps1` for an offline install;
  - `make deploy-check` in CI;
  - backup and restore as a full `-Fc` dump into an **empty** database, with the restore
    **rehearsed** (L-19).
- ITS tasks, tracked in §6.2: VM, DNS name, TLS certificate, CAS service registration,
  firewall to the inference host only.
- **Exit:** a person with no assistant installs the bundle on a clean VM, imports a
  snapshot, signs in through CAS, and sees the VPFA library.

### 5.8 Phase 8: smoke, docs, pilot (2 weeks pilot + 2–3 days docs)
- `make smoke` against the **running** system, which must:
  - sign in;
  - read a VPFA role;
  - search by title, meaning and position;
  - clone and export from the Builder;
  - download a CRF;
  - approve in review;
  - read the funnel;
  - check the plain-language rule (no internal ids, paths or pipeline words on any user
    page; the parent's #222 check);
  - check the inference host's context window (HR-341) **and** that the model sits in
    GPU memory (L-20).

  **One smoke file per surface** (L-23).
- The user guide (`docs/OPERATOR-GUIDE.md` → in-app `/guide`), written for a VPFA manager.
- **Pilot:**
  - two weeks with named users from each unit;
  - feedback through a footer link;
  - each fix lands as an ordinary PR with its own smoke check.

### 5.9 Estimate

| phase | engineer-days (with Claude Code) |
|---|---|
| 0 foundation | 2–3 |
| 1 snapshot contract (parent + spinoff) | 4–6 |
| 2 Bank | 3–5 |
| 3 Builder | 5–8 |
| 4 CRF | 2–3 |
| 5 review + funnel | 4–6 |
| 6 rulebook + register | 2–3 |
| 7 sign-in, security, deployment | 4–6 |
| 8 smoke + docs | 2–3 |
| **build total** | **28–43 days ≈ 6–9 weeks** |
| pilot | 2 weeks |
| contingency | +20%, mostly ITS lead times (VM, DNS, TLS, CAS registration) |

**Basis:**
- The parent built these surfaces from scratch:
  - the Builder landed 14 days after the project started (2026-07-10 → 07-24);
  - the content library landed on 2026-08-01;
  - the CRF was designed in late October and merged on 2026-11-20 (#219).

  All three kept being refined afterwards; the port inherits that refinement.
- A port with a known-good reference and its tests is faster. These figures assume ~60%
  of the original effort for ported code and full effort for the new snapshot contract.
- **What makes it slip:** ITS lead times for the VM, DNS, TLS and the CAS service
  registration, and the inference host being shared or slow. The parent's host was
  silently running on CPU, at a fraction of its GPU speed, for an unknown period (L-20).

---

## 6. Repo elements to clone

Paths are relative to the parent's `core/`. "Port" means copy, then cut imports of anything
in the "leave" column, until `make gates` is green.

### 6.1 What to copy

| area | copy | adapt | leave behind |
|---|---|---|---|
| **domain** | `src/jd_core/models`, `src/jd_core/quality`, `src/jd_core/wjq_form_check.py`, `src/jd_core/textnorm.py`; from `src/jd_core/bank` only what review and the library import (`render`, `word_diff`, `version_diff`, `change_log`, `provenance`; let the imports decide) | — | `src/jd_core/parser`; the dedup and clustering half of `src/jd_core/bank` (`shingles`, `minhash`, `similarity`, `clustering`, `signals`, `merge`, `title_family`, `drift`, `hay_signals`) |
| **rulebook** | `src/jd_core/rules/loader.py`, `render.py`, the YAML listed in §5.6, the matching register entries | `org_units.yaml`: Campus Services list (D3) | YAML only the pipeline reads (`dedup`, `harmonization`, `segmentation`, `classification`, `hay_signals`, `coded_terms`, `comparison`, `quality` audit prompts) |
| **Bank** | `src/jd_bank/library/{service,units,models,positions,scopes}.py`, `src/jd_bank/positions/` | `funnel.py`: archive stages from the manifest | `families.py` (the IT collection; port later if a unit wants it) |
| **Builder** | `src/jd_bank/composer/` whole, `src/jd_export/` whole | `clone` reads `parsed_jds` (§5.3) | `src/jd_bank/query_plan.py` (off in the parent) |
| **CRF** | `src/jd_bank/forms/`, `src/jd_export/comp_requisition.py`, the blank PDF | offer from a Builder draft too | — |
| **review** | `src/jd_bank/review/` | — | — |
| **LLM + vectors** | `src/jd_bank/llm/` (with HR-341), `src/jd_bank/embeddings/{client,roles}.py` | register the request timeout (L-21) | `embeddings/runner.py` (document vectors) |
| **web** | `src/api/{main,deps,csrf,errors,readiness,security_headers,service_origin}.py`, `src/api/services/`, routes `auth`, `admin`, `library`, `compose_ui`, `compose`, `drafts`, `front_door`, `guide`, `_forms`, review parts of `ui.py` + `jd_bank.py` | front door → VPFA library | `routes/dashboard.py`, templates `dashboard_*`, `collection.html` |
| **templates** | `_base`, `_csrf`, `_position_files`, `_snapshot_notice`, `admin_users`, `archive`, `comp_requisition`, `compose_new`, `compose_search`, `error`, `funnel`, `jd_view`, `library`, `library_not_found`, `login`, `my_drafts`, `review_*`, `role_detail`, `unit` | header: "VPFA JD Bank" | `dashboard_*`, `collection` |
| **tests** | each ported module's unit tests; integration tests for library, composer, review, auth; the live smoke checks for these surfaces | split smoke per surface (L-23) | pipeline tests |
| **ops** | `build/launch/teardown.ps1`, `deploy/bundle.ps1`, `install.ps1`, `deploy-check.sh`, the CI workflow's gate structure | drop the redis, worker and canonical services | `deploy/rtx`, parallel-Bank tooling |
| **docs pattern** | `CURRENT.md` (pointers, never facts), `CLAUDE.md` invariants, `HANDOFF.md` shape, the register generator, `docs/NETWORK-SETUP.md` | rewrite for this app | everything dated (`audit/`, `baseline/`, `archive/`) |
| **not code** | — | — | `harness-claude-code/`, `src/agents/`, `src/memory/`, `CodeX/` |

**Rough size, measured 2026-11-24:** the parent's `core/src` is ~48,500 lines of Python.
The copy column is roughly 22,000–26,000 lines: `api` 6.2k, `jd_core/rules` 5.5k (the
loader alone is 4.9k), `composer` 4.2k, `library` 2.8k, `jd_core` models and quality 2.6k,
`jd_export` 1.2k, review 1.2k, and small modules. So the spinoff starts at about **half**
of the parent. Most of the cut is the pipeline. The rules loader shrinks as rule files are
left out, but it is not worth rewriting.

### 6.2 What ITS has to provide (start in week 1; these are the long poles)

- a VM (Docker, 4 vCPU, 16 GB, 100 GB disk is ample for a few thousand roles);
- a DNS name and a TLS certificate;
- a CAS service registration for the new origin;
- network: inbound 443 from the campus network only; outbound to the inference host
  (11434/tcp) and the CAS server only, nothing else;
- backup target and retention.

---

## 7. Roles

### 7.1 People

| role | who (proposed) | responsibilities |
|---|---|---|
| **Product owner** | the parent's owner | scope, D1–D7, accepts each phase, merges or delegates merging, runs the Friday-style briefings |
| **Technical custodian** | the colleague, or the owner's second account | runs Claude Code, owns the repo, **reviews and merges** every PR, holds the `.env`, runs smoke before every merge. The single accountable engineer |
| **Policy owner, as HR's proxy** (D7) | VPFA | ratifies the register entries the spinoff inherits, recording each one as a proxy ruling; HR's own rulings in the parent still apply wherever VPFA has not ruled |
| **Reviewers** (D4) | **Denise** (VPFA office); **Galib** (Chief, Safety & Risk Services, or a designate); **two more, TBD**, covering ITS, Facilities, Finance and Campus Services | approve or reject submitted drafts; every action is audited under their CAS identity. The four of them are the first `reviewer` accounts |
| **VPFA unit champions** | one each from the VPFA office, ITS, SRS, Facilities, Finance and Campus Services (may be the reviewers) | supply and vet unit membership (D3); pilot users; first readers of the funnel |
| **ITS infrastructure** | ITS | VM, DNS, TLS, CAS registration, firewall, backups, the inference host |
| **Privacy and risk** | Chief Risk & Safety Officer's office; SFU privacy office | review the data flows (§10). A privacy impact assessment if the privacy office asks for one; the trigger to re-decide if inference moves |
| **Inference host owner** | whoever runs `aria-gb10-2` | keeps the model on the GPU with a ≥32k context window; announces maintenance |

### 7.2 The agent fleet

**Start with one Claude Code session per engineer, not a fleet.** In the parent, the six
vendored subagent definitions were never installed, and the work that mattered was done by
one session that verified its own claims. A fleet adds hand-offs where detail is lost.

| agent | use it for | model tier | rule |
|---|---|---|---|
| **Main session** (Claude Code) | everything; it is also the reviewer | Opus | it re-runs every gate itself; a claim of green, including its own, is not evidence until the command and its output are pasted |
| **Explore** subagent | read-only sweeps ("where does the parent read `department`?") | Sonnet or Haiku | conclusions only; verify anything it says before acting on it |
| **Parallel lanes** (general-purpose in git worktrees) | independent phases once Phase 1 lands: Bank, CRF and funnel can run side by side | Sonnet for mechanical ports, **Opus** for anything touching rulebook semantics, security or a decision parameter | pre-assign register ids per lane; one smoke file per surface; each lane runs its own smoke (L-23, L-24) |
| **Reviewer** | a second read of a security-touching or rulebook-touching diff | **Opus, always** | give it the diff, not your conclusion |

If you want the fleet as installed agents, put definitions in `<repo>/.claude/agents/`
and hooks in `<repo>/.claude/settings.json` (no-commit-to-main, black on save).
**A definition sitting in a vendored folder does nothing** (the parent's L-25).

---

## 8. Handover mechanics

### 8.1 What does not travel by itself

| thing | why it does not travel | how it travels |
|---|---|---|
| this machine's assistant memory | it lives in the owner's local Claude Code profile | **§9 of this plan carries it**; nothing else in the memory is needed |
| `.env` values (CAS, admins, origins, feedback email) | gitignored, secret | the custodian creates them on the VM; `.env.example` lists the names only |
| the archive | read-only, external, 14,565 files | it does not travel; the snapshot carries what the spinoff needs |
| the parent's live Bank | runs on the owner's desk box | snapshots (§5.1) |
| inference access | network-level | ITS firewall rule (§6.2) |

### 8.2 Day 1 for the custodian
1. Read this plan, [`VPFA-SPINOFF-BRIEF.md`](VPFA-SPINOFF-BRIEF.md), the parent's
   [`ORAL-HISTORY.md`](../ORAL-HISTORY.md) and its `CLAUDE.md`.
2. Get read access to the parent repo, which is the reference for every port.
3. Create the new repo (D6) and do Phase 0.
4. Open the ITS tickets (§6.2): they take the longest.
5. Ask the owner for D1–D7 in writing; record them as ADRs or register entries, never in
   chat (conversation state is lost at session end).

### 8.3 The new repo's `CLAUDE.md` should say, at minimum
- the four surfaces and the out-of-scope list (§1);
- **the parent is the only producer**; never add a pipeline step here;
- Directive #0 (ship only after a full end-to-end smoke test) and Directive #1 (tested,
  deployable by a person through the scripts, discoverable, deploy-check, smoke covering
  the change), verbatim;
- non-negotiables 1–8 from the parent, minus the ones about the archive;
- the change workflow: code, rules, CI, `CLAUDE.md` and `HANDOFF.md` go by PR; most docs
  can go straight to `main`;
- **check the Bank, not the counter** (§9, L-01).

---

## 9. Lessons learned: the ones that should shape the spinoff's design

The parent paid for each of these at least once. Ids are local to this plan. The full
narrative is in [`../ORAL-HISTORY.md`](../ORAL-HISTORY.md), and the harness-level set is in
[`../HARNESS_LESSONS.md`](../HARNESS_LESSONS.md).

### Truth and measurement
| | lesson | what the spinoff does about it |
|---|---|---|
| **L-01** | **Check the Bank, not the counter.** A run's summary says what it did; the database says what is true. `refreshed=95` was printed over 84 drafts that gained prose | the importer reports counts it reads back, with the app's own predicates, and refuses a mismatch |
| **L-02** | **Agreement between documents is a correlated failure, not corroboration.** Five wrong numbers agreed across four documents | `CURRENT.md` holds pointers and commands, never counts |
| **L-03** | **A fixture cannot be stale.** Green unit tests proved nothing while 703 roles were invisible to search | smoke runs against the running system and must cover the change |
| **L-04** | **A guard you have not broken is decoration**, and so is a one-directional one | every guard is broken once in its PR; assert both directions |
| **L-05** | **A placeholder is not a null.** `Untitled Position` passes `title <> ''` and reads as 100% coverage | the importer counts placeholders separately; the UI says "no title in the source" |
| **L-06** | **A zero from a wrong query looks like a zero from a guard that never fired.** `make near-dup` without the archive path signed 0 documents and exited 0 | every job that can legitimately produce nothing still fails when it processed nothing |
| **L-07** | **A probe must first reproduce a number the system already knows**, or its other numbers do not count | any new measurement starts by reproducing a funnel number |
| **L-08** | **Measure before designing a score.** Role similarity has no threshold: an unrelated role often outscores a true twin | rank similar roles; never show a percentage or add a cut-off |
| **L-09** | **Three numbers, never one:** matched, not matched, could not evaluate | every unit and funnel facet shows all three |

### People and audience
| | lesson | what the spinoff does about it |
|---|---|---|
| **L-10** | **HR wants to read JDs, not statistics.** Lead with content; every count clicks through | the landing page is the VPFA library, not a dashboard |
| **L-11** | **Ask what the audience will look for.** ITS directors look for their own department, not SFU's definition of "IT" | units are the first navigation level |
| **L-12** | **Plain language on every user page**: no internal ids, paths or pipeline words | a smoke check fails on them (parent #222) |
| **L-13** | **A feature nothing links to has not been delivered.** The live funnel shipped with no menu entry and read as the old dashboard for a day | "reachable from the UI" is in the definition of done |
| **L-14** | **The model may reword; it may not invent.** The rewrite invented ~1,000 duties and whole sections, and the inventions *raised* scores, so nobody reported them | the spinoff has no rewrite; the Builder's assist only suggests, and the validator is the oracle |
| **L-15** | **Membership is people-work.** Never infer which departments belong to a unit | an exact list per unit, supplied by the unit champions (D3) |
| **L-16** | **We build; HR decides.** Every undecided default is registered `open`, never quietly patched | the register comes across with the rules (§5.6, D7) |

### Operations
| | lesson | what the spinoff does about it |
|---|---|---|
| **L-17** | **CAS off + open ports = everyone on the LAN is admin.** The parent ran like that for 11 days in November | fail closed outside dev (A8); dev binds loopback only |
| **L-18** | **The port is part of the address.** CAS sign-in broke twice in a day on an origin spelled differently from the allowlist | the custodian reads `ALLOWED_SERVICE_ORIGINS` off the box and tests every origin users will type |
| **L-19** | **`pg_restore --data-only` wipes the Bank and exits 0.** | full `-Fc` dumps into an empty database; restore rehearsed before the pilot |
| **L-20** | **The inference host can fail silently.** In November 2026 it served the model with a **4,096-token** window, truncating prompts with no error, and then ran it **on CPU**: prompt reading at ~9–210 tokens/s against ~930 on the GPU, and output at ~1–9 tokens/s against ~44. A reboot did not fix it | before any model work and in smoke: check `/api/ps` for `context_length ≥ 32,768` **and** `size_vram == size`. Never "test" the host with large prompts; it is shared |
| **L-21** | **An unregistered timeout is a hidden decision.** The SDK's default 600 s read timeout, with up to nine attempts between the SDK's retries and ours, turned a slow host into over an hour per call with no error | register the request timeout and the retry budget; fail fast and say why |
| **L-22** | **The dev API does not hot-reload on a Windows bind mount**, so a running server can be hours staler than the code smoke just passed | after a deploy, check the server's start time is newer than the change |
| **L-23** | **One shared smoke file is a merge-conflict magnet.** Every parallel PR in the parent conflicted on it | one smoke file per surface from day one |
| **L-24** | **Parallel lanes collide on shared ids.** Two lanes took the same register id | pre-assign id ranges per lane |
| **L-25** | **Installed is not vendored.** The parent's subagent definitions and hooks sat in a vendored folder for months and never ran | if you want agents or hooks, install them under `<repo>/.claude/` and prove each one fires |
| **L-26** | **Long one-shot jobs are not restarted by anything.** A desk-box reboot killed a 19-hour pass | the spinoff has no long jobs by design (A1); imports are minutes and idempotent |
| **L-27** | **Ship only after a full end-to-end smoke test.** Eight PRs once merged with smoke red, each calling it "pre-existing and unrelated" | Directive #0 is in the new `CLAUDE.md` from day one |

---

## 10. Risk register (for the risk and policy readers)

| risk | likelihood | impact | mitigation |
|---|---|---|---|
| A JD is published that misstates a role | low | medium | human approval only (D4); gates re-checked at approval; full audit chain; the spinoff does not rewrite content |
| Content leaves SFU's control | low | high | self-hosted inference only (A6); no third-party API; the snapshot is a file moved by the custodian; egress firewalled to the inference host and CAS (§6.2) |
| Unauthorised access | low with A8 | high | CAS required outside dev; three roles; CSRF tokens; security headers; admin list from `.env` |
| Wrong unit counts reach a vice-president | medium | medium | three numbers on every unit view (L-09); membership from champions only (L-15) |
| Inference host slow, down or misconfigured | **observed** | medium | Bank, funnel, CRF and review need no model. Builder search falls back to title and trigram; assist degrades to off. Smoke checks the window and GPU placement (L-20) |
| Parent and spinoff drift apart | medium | medium | the parent is the only producer (A1); snapshots carry versions; register ids are shared (D7) |
| Key-person dependency | **high today** | high | this plan, the oral history, a custodian named in §7, and Directive #1's "deployable without the assistant" |
| Incumbent names in JD text | low | low | normalized out at ingestion in the parent as a rulebook quality step; JDs describe roles, not people |

---

## 11. Open questions to bring to Friday

1. ✅ Scope ruled (D1–D3): everything under VPFA, Finance included. Still open: the
   Campus Services neighbours in §2.
2. ✅ Reviewers named (D4): Denise and Galib, plus two TBD. **Who are the other two**, and
   which units do they cover? And is SRS's sign-off on behalf of VPFA acceptable to HR, given
   VPFA proxies for HR (D7)?
3. Does the privacy office want a privacy impact assessment before the pilot, given the
   data is job descriptions (not personal records) and inference stays on SFU-controlled
   hardware?
4. Who is the technical custodian, and on which account?
5. Pilot users: one or two names per unit.

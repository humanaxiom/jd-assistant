# VPFA JD Bank: software engineering plan for a focused spinoff

**Status:** proposal. **Revision 2, 2026-11-25**, after the owner's ruling **D8** (§0):
*the spinoff brings everything across as is; only the dashboards are removed.*
Revision 1 (2026-11-24) designed a smaller, read-only application that imported snapshots
and left the pipeline behind. **That was a misreading of the brief, and this revision
replaces it.** Revision 1 stays in git history (parent commit `2632bf1`) as the record.
Nothing here is built yet.

**Written for:**
- the engineer who will build and run the spinoff: a colleague, or the owner's second
  account, working with Claude Code on a Claude Team (Premium seat) account;
- the Claude Code sessions they run.

It assumes no access to this machine, to this machine's assistant memory, or to the person
who wrote it.

**Companion documents:**
- [`VPFA-SPINOFF-BRIEF.md`](VPFA-SPINOFF-BRIEF.md), the short version for policy and risk
  readers;
- [`../ORAL-HISTORY.md`](../ORAL-HISTORY.md), how the parent project got here and why its
  rules exist.

> **The one-paragraph version.** Copy the whole JD Bank, as is, into a new repo for the
> VPFA portfolio (VPFA office, IT Services, Safety & Risk Services, Facilities Services,
> Finance, Campus Services):
> - **all of it**: ingest, parse, dedup, clustering, harmonization, the LLM rewrite and
>   audit, the Bank, the Builder, the funnel, the Compensation Requisition Form, review,
>   the guide and the deploy scripts, plus the **v9 Bank's data** and the archive;
> - **removed:** the static dashboards, and nothing else;
> - **added:** a VPFA lens: VPFA is the default scope everywhere, Campus Services is
>   defined, VPFA reviewers approve, VPFA rules as HR's proxy, and sign-in fails closed.
>
> The copy keeps the parent's history and tracks it as an upstream, so pipeline
> improvements can still flow across. Estimate: **3–5 weeks** to a pilot for one engineer
> working with Claude Code, then a 2-week pilot.

---

## 0. Decisions

### ✅ Owner rulings

| # | ruling | when |
|---|---|---|
| **D1** | Hold the **whole SFU Bank**; show **VPFA by default** | 2026-11-24 |
| **D2** | **Everything under VPFA is in scope**, so **Finance is included** | 2026-11-24 |
| **D3** | **Residence and Housing** and **Bookstore** belong to Campus Services. Neighbouring departments are listed in §2 as still to confirm | 2026-11-24 |
| **D4** | Review stays. **Reviewers:** Denise (VPFA office), Galib (Chief, Safety & Risk Services, or a designate), and two more for the other units, TBD | 2026-11-24 |
| **D6** | The repo is **`https://github.com/sfu-aria/Vpfa-jda`**. ⚠ It is **public** today. It must be **private before any code is pushed** (§6.3) | 2026-11-24 |
| **D7** | **VPFA acts as HR's proxy.** VPFA rules on the register entries, and VPFA reviewers approve the JDs (§5.4) | 2026-11-24 |
| **D8** | **Bring everything in as is. Only the dashboards are removed.** The ingest, dedup, harmonization and every other pipeline stage come across | 2026-11-25 |
| D5 | **Open:** where it runs. Recommendation: an SFU-managed VM with Docker, TLS, CAS on, inference on `aria-gb10-2` or a successor ITS controls | — |
| D9 | **Open:** after day 1, who produces VPFA's roles? See §3.2 A3. Recommendation: the spinoff does, from its own copy | — |

⚠ **What D7 changes.**
- In the parent, register entries are HR's to ratify. In the spinoff, VPFA ratifies them
  as HR's proxy.
- Record each ratification in the spinoff's register: `decided_by` names the VPFA person,
  and `decision_note` says they acted as HR's proxy.
- A value VPFA changes then **differs from the parent's** for the same HR id. Show that
  difference on the spinoff's register page, so nobody reads a VPFA ruling as HR's.

⚠ **What D8 changes from revision 1.**

| revision 1 | revision 2 |
|---|---|
| a new, smaller app; about half the parent's code | the whole parent; one subtraction |
| the parent is the only producer; the spinoff imports JSONL snapshots | the spinoff runs the full pipeline itself; it starts from the v9 Bank via the parent's own offline bundle (`deploy/bundle.ps1` → `deploy/install.ps1`) |
| no archive on the new box | the archive (14,565 files, 2.1 GB) travels too, so the pipeline can re-run |
| a fresh repo with no history | the parent's history comes across, and the parent is tracked as `upstream` |
| no Redis, no worker, no document vectors | the parent's full compose stack: postgres, neo4j, redis, api, worker |
| a fresh initial migration | the parent's migrations, unchanged |
| 6–9 weeks | 3–5 weeks |

---

## 1. Scope

### In: everything the parent has, as is

| area | what it covers |
|---|---|
| **Pipeline** | ingest, parse, baseline, dedup (exact, near and role tiers), clustering, harmonization, the LLM rewrite and audit, singletons, field audit, bank audit, document and role embeddings |
| **Bank** | the content library: units, roles, source files and positions; search by title, meaning and position number |
| **Builder** | clone or start blank, guided questions, live compliance, the summary suggestion, near-duplicate guard, Word export, My drafts |
| **Funnel** | where the archive went, with matched, not matched and could not evaluate on every facet |
| **Compensation Requisition Form** | pre-filled from a role, request types A–E |
| **Review** | queue, diff, approve and reject, with supersede and the audit chain |
| **Sign-in and admin** | SFU CAS; `author`, `reviewer`, `admin` |
| **Guide, ops and deploy** | the in-app guide; `build/launch/teardown.ps1`; `deploy/bundle.ps1` and `install.ps1`; `make gates`, `smoke`, `deploy-check`; the HR decision register and its generator |
| **Governance** | `CLAUDE.md` with Directives #0 and #1, `CURRENT.md`, `HANDOFF.md`, the oral history, ADRs, and the vendored harness (still vendored; see L-25) |

### Out: the dashboards, and nothing else

| removed | detail |
|---|---|
| the dashboard pages | `routes/dashboard.py`; templates `dashboard_index`, `dashboard_baseline`, `dashboard_dedup` and `dashboard_clusters`; their unit tests |
| their entry points | the **📊 Dashboards** link in `_base.html`, plus every other link to `/jd-bank/ui/dashboard*` (the funnel, the review queue and the snapshot notice link there today) |

⚠ **Remove the pages, not their data.** The jobs that produce the baseline, dedup and
cluster reports **stay**. The funnel, `scopes.py`, `readiness.py` and the snapshot notice
reference the same artefacts, and the pipeline needs them. `grep -rn dashboard core/`
finds 31 files on `bank/v9`; most of them are the producers, which stay. Old dashboard URLs
**redirect to the funnel**, so bookmarks keep working.

---

## 2. What the archive looks like through a VPFA lens

Measured on the live parent Bank, 2026-11-24, using the app's own unit code
(`resolve_unit` in `jd_bank/library/units.py`). **These are dated numbers; re-measure on
the v9 Bank before quoting them.**

| unit (parent `org_units.yaml`) | drafts in unit |
|---|---|
| VPFA, including all children | **128** |
| Facilities Services | 50 |
| IT Services | 41 |
| Finance | 22 |
| Safety & Risk Services | 9 |
| Campus Services | **0**: no departments assigned yet. Ruled D3: Residence and Housing (25), Bookstore (13) |
| **No department recorded** (any unit) | **755 of 2,499** |

What this means for the design:
1. **The VPFA slice is small, and that is fine.** A hundred-odd roles fit in one reading
   list. The Builder can draw on all of SFU's roles, which is why D1 keeps the whole Bank.
2. **A third of the Bank cannot be placed in any unit.** Every VPFA view must show the
   third number: *department not recorded*. Otherwise a vice-president is handed a
   confident wrong count of their own portfolio.
3. **Unit membership is people-work.** The parent has an exact list per unit, never a
   pattern. The spinoff inherits that list and that discipline.

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
  PARENT: JD Bank (C:\repos\JD-Assistant, branch bank/v9 + main)
     │   git history ───────────────► pushed to sfu-aria/Vpfa-jda (private), kept as `upstream`
     │   v9 Bank ── deploy/bundle.ps1 ──► images.tar + postgres.dump + neo4j.dump + MANIFEST
     │   archive (14,565 files) ──────► copied by USB / temporary share
     ▼
  SPINOFF: VPFA JD Bank (sfu-aria/Vpfa-jda) = the parent, as is
     ┌──────────────────────────────────────────────────────────────────────────────┐
     │ archive → ingest → parse → dedup → cluster → harmonize → rewrite/audit → Bank │
     │ FastAPI + Jinja: Bank · Builder · Funnel · CRF · Review · Guide   (no dashboards)│
     │ VPFA lens: default scope, Campus Services, VPFA reviewers, proxy register       │
     │ postgres · neo4j (document + role vectors) · redis + arq worker                 │
     │ Ollama on an ITS-controlled host: nomic-embed-text, gpt-oss:120b                │
     └──────────────────────────────────────────────────────────────────────────────┘
```

### 3.2 Decisions, and the ADR each one needs

The parent's ADRs come across unchanged. These are the spinoff's own, numbered from
ADR-100 so they never collide with an inherited number.

| | decision | rationale | ADR |
|---|---|---|---|
| A1 | **A full copy with history, tracking the parent as `upstream`** | D8. Keeping history keeps every "why" reachable with `git log` and `git blame`, and makes merging the parent's later fixes an ordinary `git merge` | ADR-100 |
| A2 | **Keep the diff from the parent small and named.** The spinoff's changes are the dashboard removal and the VPFA lens (§5), each in its own commits and files where possible | Every line changed in a shared file is a future merge conflict. Prefer configuration (YAML, `.env`) over edits to shared code | ADR-100 |
| A3 | **Day 1 data is the v9 Bank, installed with the parent's offline bundle.** After that the spinoff's Bank is its own; it never re-imports a parent Bank over itself (D9) | A restore replaces the whole database, so a later re-import would wipe VPFA's own drafts, reviews and audit rows. Improvements arrive as **code** merged from `upstream`, then a pass re-run here | ADR-101 |
| A4 | **The parent's stack, unchanged:** Python 3.11, FastAPI, Jinja, PostgreSQL 16, Neo4j (document and role vectors), Redis + arq, Docker-only | "As is" (D8) | inherited ADR-002, ADR-005, ADR-006 |
| A5 | **The code must be the code that produced the data.** The spinoff starts from `bank/v9` (parser v11, prompt v5), with the parent's `main` merged in first | A Bank parsed by v11 under v8 code reads every parse as stale, and the Bank and the smoke checks disagree | ADR-101 |
| A6 | **Self-hosted inference only, on a host SFU controls** | The parent's invariant, ratified 2026-07-20. If the host moves off a trusted segment, that is a FIPPA question to re-decide | inherited ADR-003 |
| A7 | **CAS fails closed outside `ENV=dev`.** This is the one security change to shared code | Fixes the parent's one incident at design level (L-17). Offer it upstream as well, so it stops being a divergence | ADR-102 |
| A8 | **Rulebook as data, with a register**; VPFA's rulings recorded as proxy rulings (D7) | Inherited discipline | inherited |

### 3.3 Data model

The parent's schema and its migrations, unchanged. The restore brings `alembic_version`
with the data, so the box lands at head without running a migration (`deploy/README.md`).
Any VPFA table goes in a **new** migration on top, never as an edit to an inherited one.

---

## 4. Environments

| env | where | CAS | inference | data |
|---|---|---|---|---|
| dev | the custodian's machine, Docker | off allowed, **loopback ports only** (`127.0.0.1`) | ITS host | the v9 bundle + the archive |
| pilot | SFU VM, TLS at the edge | **on** (startup refuses otherwise, A7) | ITS host | the dev Bank, moved with `bundle.ps1` → `install.ps1` |
| prod | as pilot, after sign-off | on | ITS host | as pilot |

- **Ports:** use a non-default range. The parent uses 25xxx and 26xxx, and Codex uses
  27xxx, so pick **28xxx**.
- **Origins:** every origin users reach the app on must be in `ALLOWED_SERVICE_ORIGINS`
  exactly, including scheme and port, or CAS sign-in falls back silently (L-18).
- **The archive** is mounted read-only through `JD_ARCHIVE_PATH`. It is needed only to
  re-run the pipeline. The Bank, Builder, funnel, CRF and review run without it.
- **GPU time is shared.** A full redraft pass on the parent's v9 took about four days on
  `aria-gb10-2` (~150 s per role). The spinoff and the parent share that host. Agree a
  schedule with the host owner before a pass, and never run two at once.

---

## 5. Work breakdown

Each phase is done only when Directive #1 holds:
- tested: failing test first, and the guard broken once;
- deployable through the scripts by a person;
- reachable from the UI;
- `deploy-check` green;
- `make smoke` green **and covering the change**.

Directive #0 applies to every merge: **no merge with smoke red.**

### 5.0 Phase 0: stand up the copy (2–4 days)
- **Parent first (owner's box):**
  - finish the v9 pass;
  - merge `main` into `bank/v9`;
  - `make smoke` green on v9;
  - cut the v9 bundle with `deploy/bundle.ps1`.
- **The repo:**
  - **make `sfu-aria/Vpfa-jda` private** (§6.3);
  - push the parent's history to it: `bank/v9` (merged) as `main`, plus the parent's
    `main` as `upstream/main` for reference;
  - add the parent as the `upstream` remote;
  - keep the existing design docs on top.
- **The box:**
  - `deploy/install.ps1 -BundleDir <bundle>` installs the v9 Bank offline and checks row
    and vector counts against `MANIFEST.txt`;
  - put the archive in place and set `JD_ARCHIVE_PATH`;
  - check the inference host: `/api/ps` shows `context_length ≥ 32768` **and**
    `size_vram == size` (L-20).
- **CI:** the parent's workflow as is. GitHub Actions minutes now bill to `sfu-aria`.
- **Exit:**
  - `make gates` green on the new box;
  - `make smoke` green on the new box, **against the installed v9 Bank**;
  - CI green on the new repo.

### 5.1 Phase 1: remove the dashboards (1–2 days)
- Delete the four dashboard templates, `routes/dashboard.py` and its router registration,
  and the dashboard unit tests.
- Remove the **📊 Dashboards** nav link, and every link to `/jd-bank/ui/dashboard*`.
- `/jd-bank/ui/dashboard*` redirects to the funnel with a 301 and a test.
- **Keep** the producers (baseline, dedup and cluster reports) and the artefacts the funnel
  and readiness read (§1).
- `test_template_links.py` must still pass; it is the guard against a dangling link.
- **Exit:** no page links to a dashboard; old URLs land on the funnel; smoke asserts both.

### 5.2 Phase 2: the VPFA lens (3–5 days)
- **Default scope = VPFA and its children** (D1, D2) in the library, the funnel and
  Builder search, with a visible switch to all of SFU. Do it as configuration (a scope
  default in YAML or `.env`, registered per the standing rule), not a code fork.
- Every unit view shows **in unit · not in unit · department not recorded** (L-09).
- `org_units.yaml`: assign the Campus Services departments (D3), plus a register entry, in
  the same PR. The §2 neighbours stay unassigned until VPFA rules, and are registered
  `open`.
- The front door lands on the VPFA library. Header and title read "VPFA JD Bank".
- **Exit:** a VPFA user signs in, lands on the VPFA library, and sees the three numbers on
  every unit. Smoke checks the default scope.

### 5.3 Phase 3: sign-in fails closed (1–2 days)
- Outside `ENV=dev`, startup refuses CAS off, an http or loopback service origin, or an
  empty `BOOTSTRAP_ADMINS` (A7, L-17).
- Dev binds ports to `127.0.0.1` only.
- **Exit:** each refusal has a test that breaks once; smoke on dev still green.

### 5.4 Phase 4: VPFA as HR's proxy (2–3 days)
- **Reviewers:** Denise, Galib and the two TBD get the `reviewer` role through the admin
  page. Record who and when in `HANDOFF.md`, never only in chat.
- **Register:** every ratification VPFA makes records `decided_by`, `decided_on` and a
  `decision_note` saying "as HR's proxy". The register page marks each entry as **HR**,
  **VPFA proxy** or **open**, and flags any value that differs from the parent's.
- **Exit:** a test proves the register refuses a proxy ruling with no `decision_note`, and
  the register page shows a proxy ruling as such.

### 5.5 Phase 5: deployment on the SFU VM (4–6 days, mostly ITS lead time)
- ITS tasks (§6.2): VM, DNS name, TLS certificate, CAS service registration, firewall to
  the inference host only.
- Move the Bank with `bundle.ps1` → `install.ps1`. Rehearse a restore into an **empty**
  database before the pilot (L-19).
- **Exit:** a person with no assistant installs the bundle on the clean VM, signs in
  through CAS, and sees the VPFA library. `make smoke` green there.

### 5.6 Phase 6: docs and pilot (2–3 days + 2-week pilot)
- The in-app guide, rewritten for a VPFA manager. The operator guide keeps the pipeline
  runbooks as is.
- **Pilot:**
  - two weeks with named users from each unit;
  - feedback through a footer link;
  - each fix lands as an ordinary PR with its own smoke check.

### 5.7 Optional, once the pilot is running
- **The CRF from a Builder draft**, not only from a role (2–3 days). The parent lists it
  as a follow-up; build it upstream if possible, so both apps get it.
- **A VPFA-only re-run of the pipeline**, if VPFA wants fresher prose for its roles
  without a four-day full pass. It needs a scope option on the producer (an upstream
  change) and a GPU slot (§4).

### 5.8 Ongoing: keeping up with the parent
- `git fetch upstream` monthly, or when the parent announces a fix.
- Merge `upstream/main` on a branch. `make gates` and `make smoke` must be green before
  merging it into the spinoff's `main`.
- A merge that bumps `PARSER_VERSION` or the prompt version makes the Bank stale: plan a
  pass (§4) before merging it, or hold the merge.
- Fix shared problems **upstream first**, then merge; never patch the same bug twice.

### 5.9 Estimate

| phase | engineer-days (with Claude Code) |
|---|---|
| 0 stand up the copy | 2–4 |
| 1 remove the dashboards | 1–2 |
| 2 VPFA lens | 3–5 |
| 3 sign-in fails closed | 1–2 |
| 4 VPFA as HR's proxy | 2–3 |
| 5 deployment on the SFU VM | 4–6 |
| 6 docs | 2–3 |
| **build total** | **15–25 days ≈ 3–5 weeks** |
| pilot | 2 weeks |
| optional (§5.7) | +2–3 days for the CRF from a draft; the VPFA re-run is unscoped |
| contingency | +20%, mostly ITS lead times (VM, DNS, TLS, CAS registration) |

**Basis:**
- Nothing is ported. Every surface already runs, with its tests and its smoke checks, on
  the v9 Bank.
- The work is a subtraction, configuration and deployment.
- The offline install was verified end to end on 2026-08-28 (`deploy/README.md`).
- **What makes it slip:**
  - ITS lead times;
  - a red smoke on the new box from an environment difference: ports, origins, the archive
    path, or the inference host (L-18, L-20);
  - inference host contention if a pipeline pass is needed.

---

## 6. Repo elements

### 6.1 What comes across

Everything in the parent repo, from `bank/v9` with `main` merged in. The only deletions
are in §1 "Out". Size, measured 2026-11-24:
- **The git history packs to 1.38 GiB.** The largest single file is an 89 MB archive RTF
  in `fixtures/golden/`. That is under GitHub's 100 MB limit, but over its 50 MB warning.
- **The v9 deploy bundle is about 1.4 GB:** images ~650 MB, the Postgres dump, and the
  Neo4j dump.
- **The archive is 2.1 GB,** 14,565 files.

| thing | how it travels |
|---|---|
| source and history | git push to the private `sfu-aria/Vpfa-jda` (§6.3) |
| the v9 Bank | `deploy/bundle.ps1` → USB or a temporary share → `deploy/install.ps1` |
| the archive | USB or a temporary share; **never git** |
| HR reference files | `fixtures/hr/cupe/` is tracked and comes with the repo. The newer files beside it (the 2024 APSA template, the JD Toolkit, the CRF, the Hay material and others) are **untracked** in the parent, so they travel in the bundle folder; decide with the owner whether they belong in git |
| `.env` | never travels. The custodian creates it from `.env.example` |

### 6.2 What ITS has to provide (start in week 1; these are the long poles)

- a VM: Docker, 4 vCPU, 16 GB RAM, **200 GB** disk. That covers the archive, both
  databases, images and backups; the pipeline needs more than revision 1's 100 GB;
- a DNS name and a TLS certificate;
- a CAS service registration for the new origin;
- network:
  - inbound 443 from the campus network only;
  - outbound to the inference host (11434/tcp) and the CAS server only, nothing else;
- a backup target and retention.

### 6.3 ⚠ The repo must be private before any code goes in

The parent's history contains **real SFU job-description files** (41 archive files in
`fixtures/golden/`), archive filenames that carry position numbers (`fixtures/labels/`),
and names of internal hosts. Pushing it to a public repo publishes them.
So:
1. the owner switches `sfu-aria/Vpfa-jda` to private;
2. someone checks it on GitHub (`gh repo view sfu-aria/Vpfa-jda --json visibility`);
3. only then is the history pushed.

Commits made on the new box use the custodian's own identity. Bank data, the archive and
`.env` never go in git (`.gitignore` already covers `snapshot/`, `*.dump`, `*.zip` and
`.env`; add `dist/` and the archive folder).

---

## 7. Roles

### 7.1 People

| role | who (proposed) | responsibilities |
|---|---|---|
| **Product owner** | the parent's owner | scope, the D-rulings, accepts each phase, merges or delegates merging, runs the briefings |
| **Technical custodian** | the colleague, or the owner's second account | runs Claude Code, owns the repo, **reviews and merges** every PR, holds the `.env`, runs smoke before every merge, merges from `upstream`. The single accountable engineer |
| **Policy owner, as HR's proxy** (D7) | VPFA | ratifies register entries as proxy rulings; HR's own rulings still apply wherever VPFA has not ruled |
| **Reviewers** (D4) | **Denise** (VPFA office); **Galib** (Chief, Safety & Risk Services, or a designate); **two more, TBD**, covering ITS, Facilities, Finance and Campus Services | approve or reject drafts; every action is audited under their CAS identity |
| **VPFA unit champions** | one each from the VPFA office, ITS, SRS, Facilities, Finance and Campus Services (may be the reviewers) | supply and vet unit membership (D3); pilot users; first readers of the funnel |
| **ITS infrastructure** | ITS | VM, DNS, TLS, CAS registration, firewall, backups |
| **Privacy and risk** | Chief Risk & Safety Officer's office; SFU privacy office | review the data flows (§10); a privacy impact assessment if asked; the trigger to re-decide if inference moves |
| **Inference host owner** | whoever runs `aria-gb10-2` | keeps the model on the GPU with a ≥32k context window; schedules passes between the parent and the spinoff; announces maintenance |

### 7.2 The agent fleet

**Start with one Claude Code session per engineer, not a fleet.** In the parent, the six
vendored subagent definitions were never installed, and the work that mattered was done by
one session that verified its own claims. A fleet adds hand-offs where detail is lost.

| agent | use it for | model tier | rule |
|---|---|---|---|
| **Main session** (Claude Code) | everything; it is also the reviewer | Opus | it re-runs every gate itself; a claim of green, including its own, is not evidence until the command and its output are pasted |
| **Explore** subagent | read-only sweeps ("what links to the dashboards?") | Sonnet or Haiku | conclusions only; verify before acting |
| **Parallel lanes** (git worktrees) | Phases 1, 2 and 3 are independent once Phase 0 is green | Sonnet for mechanical edits; **Opus** for rulebook semantics, security, or a decision parameter | pre-assign register ids per lane; one smoke file per surface (L-23, L-24) |
| **Reviewer** | a second read of a security-touching or rulebook-touching diff, and of every `upstream` merge | **Opus, always** | give it the diff, not your conclusion |

If you want installed agents or hooks, put them in `<repo>/.claude/agents/` and
`<repo>/.claude/settings.json`. **A definition sitting in the vendored
`harness-claude-code/` does nothing** (L-25).

---

## 8. Handover mechanics

### 8.1 What does not travel by itself

| thing | how it travels |
|---|---|
| this machine's assistant memory | **§9 of this plan carries it**, together with the parent's `CLAUDE.md`, `CURRENT.md` and oral history, which come across with the repo |
| `.env` values (CAS, admins, origins, feedback email) | the custodian creates them; `.env.example` lists the names only |
| the archive and the v9 Bank | the handoff bundle (§6.1), by USB or a temporary share |
| inference access | the ITS firewall rule (§6.2) |

**The handoff kit:** [`vpfa-handoff/`](vpfa-handoff/). Its `START-HERE.md` is the single
instruction set. ⚠ **It is being revised for D8.** Until then, revision 1's snapshot
export and JSONL import steps in it are superseded by §5.0 here.

### 8.2 Day 1 for the custodian
1. Read this plan, the brief, the parent's oral history, and its `CLAUDE.md` (which comes
   across with the repo and binds the spinoff too).
2. Confirm the repo is private (§6.3), then push or clone the history.
3. Do Phase 0: install the v9 bundle, put the archive in place, and get `make smoke` green.
4. Open the ITS tickets (§6.2): they take the longest.
5. Record D5 and D9 as ADRs when the owner rules, never in chat.

### 8.3 The spinoff's `CLAUDE.md`
It is the parent's, as is, plus a short section at the top:
- what this repo is (the VPFA spinoff), and the `upstream` relationship (§5.8);
- the one subtraction (dashboards) and the VPFA lens;
- **the repo is private and must stay so** (§6.3);
- D7: VPFA rules as HR's proxy;
- A3: never restore a parent Bank over this one.

---

## 9. Lessons learned: the ones that should shape the spinoff

The parent paid for each of these at least once. Ids are local to this plan. The full
narrative is in [`../ORAL-HISTORY.md`](../ORAL-HISTORY.md), and the harness-level set is in
[`../HARNESS_LESSONS.md`](../HARNESS_LESSONS.md). Because the spinoff now carries the
pipeline, **all** of these apply to it directly.

### Truth and measurement
| | lesson | what the spinoff does about it |
|---|---|---|
| **L-01** | **Check the Bank, not the counter.** A run's summary says what it did; the database says what is true. `refreshed=95` was printed over 84 drafts that gained prose | after any pass or install, query the Bank with the code's own predicates |
| **L-02** | **Agreement between documents is a correlated failure, not corroboration.** Five wrong numbers agreed across four documents | `CURRENT.md` holds pointers and commands, never counts |
| **L-03** | **A fixture cannot be stale.** Green unit tests proved nothing while 703 roles were invisible to search | smoke runs against the running system and must cover the change |
| **L-04** | **A guard you have not broken is decoration**, and so is a one-directional one | every guard is broken once in its PR; assert both directions |
| **L-05** | **A placeholder is not a null.** `Untitled Position` passes `title <> ''` and reads as 100% coverage | count placeholders separately; the UI says "no title in the source" |
| **L-06** | **A zero from a wrong query looks like a zero from a guard that never fired.** `make near-dup` without the archive path signed 0 documents and exited 0 | check `JD_ARCHIVE_PATH` before any pipeline job; a job that processed nothing fails |
| **L-07** | **A probe must first reproduce a number the system already knows** | any new measurement starts by reproducing a funnel number |
| **L-08** | **Measure before designing a score.** Role similarity has no threshold | rank similar roles; never show a percentage or add a cut-off |
| **L-09** | **Three numbers, never one:** matched, not matched, could not evaluate | every unit and funnel facet shows all three |

### People and audience
| | lesson | what the spinoff does about it |
|---|---|---|
| **L-10** | **HR wants to read JDs, not statistics.** Lead with content; every count clicks through | the landing page is the VPFA library; removing the dashboards follows from this |
| **L-11** | **Ask what the audience will look for.** ITS directors look for their own department | units are the first navigation level |
| **L-12** | **Plain language on every user page**: no internal ids, paths or pipeline words | the parent's smoke check (#222) comes across |
| **L-13** | **A feature nothing links to has not been delivered**, and a link to a removed page is a broken promise | `test_template_links.py` guards both after Phase 1 |
| **L-14** | **The model may reword; it may not invent.** The rewrite invented ~1,000 duties, and the inventions *raised* scores | the rewrite comes across **with** its guards (the P6 prompt, the audit, the HR-341 context guard); never run it without them |
| **L-15** | **Membership is people-work.** Never infer which departments belong to a unit | an exact list per unit, from the champions (D3) |
| **L-16** | **We build; HR decides.** Every undecided default is registered `open` | VPFA rules as proxy (D7); everything else stays open |

### Operations
| | lesson | what the spinoff does about it |
|---|---|---|
| **L-17** | **CAS off + open ports = everyone on the LAN is admin.** The parent ran like that for 11 days in November | fail closed outside dev (A7); dev binds loopback only |
| **L-18** | **The port is part of the address.** CAS sign-in broke twice in a day on an origin spelled differently from the allowlist | test every origin users will type |
| **L-19** | **`pg_restore --data-only` wipes the Bank and exits 0** | use `install.ps1` (full `-Fc` dump into an empty database, refuses otherwise); rehearse restores |
| **L-20** | **The inference host can fail silently.** In November 2026 it served a **4,096-token** window, truncating prompts with no error, then ran **on CPU** at a fraction of GPU speed. A reboot did not fix it | before any pass and in smoke: `/api/ps` shows `context_length ≥ 32,768` **and** `size_vram == size`. Never "test" the host with large prompts; it is shared |
| **L-21** | **An unregistered timeout is a hidden decision.** The SDK's default 600 s read timeout, with up to nine attempts, turned a slow host into over an hour per call with no error | the parent's V3a (register the timeout) is worth doing upstream first |
| **L-22** | **The dev API does not hot-reload on a Windows bind mount** | after a deploy, check the server's start time is newer than the change |
| **L-23** | **One shared smoke file is a merge-conflict magnet** | one smoke file per surface for the spinoff's additions |
| **L-24** | **Parallel lanes collide on shared ids** | pre-assign register id ranges per lane; the spinoff's own entries use a range the parent will not reach (e.g. HR-900+) |
| **L-25** | **Installed is not vendored.** The parent's subagent definitions and hooks never ran | install under `<repo>/.claude/` and prove each fires, or treat them as documentation |
| **L-26** | **Long one-shot jobs are not restarted by anything.** A desk-box reboot killed a 19-hour pass; a full redraft takes days | run passes with `--resume`, on the VM rather than a desk box, with a watcher; check the Bank after a restart |
| **L-27** | **Ship only after a full end-to-end smoke test.** Eight PRs once merged with smoke red, each calling it "pre-existing and unrelated" | Directive #0 comes across in `CLAUDE.md` |
| **L-28** | **A restore replaces everything.** (New in revision 2.) | never restore a parent Bank over the spinoff's once VPFA has its own drafts and reviews (A3) |

---

## 10. Risk register (for the risk and policy readers)

| risk | likelihood | impact | mitigation |
|---|---|---|---|
| A JD is published that misstates a role | low | medium | human approval only (D4); gates re-checked at approval; full audit chain; the rewrite's invention guards (L-14) |
| Content leaves SFU's control | low | high | self-hosted inference only (A6); no third-party API; the bundle and archive move by USB or a temporary internal share; egress firewalled (§6.2) |
| **The repo is public when code is pushed** | medium until §6.3 is done | high | private first, checked, then push (§6.3) |
| Unauthorised access | low with A7 | high | CAS required outside dev; three roles; CSRF; security headers; admin list from `.env` |
| Wrong unit counts reach a vice-president | medium | medium | three numbers on every unit view (L-09); membership from champions only (L-15) |
| Inference host slow, down or misconfigured | **observed** | medium | Bank, funnel, CRF and review need no model; smoke checks the window and GPU placement (L-20) |
| **GPU contention with the parent** | medium | medium | one pass at a time on the shared host, scheduled with its owner (§4) |
| **Parent and spinoff drift apart** | medium | medium | keep the diff small (A2); merge `upstream` on a schedule (§5.8); fix shared bugs upstream first |
| A restore wipes VPFA's own work | low | high | A3 / L-28; `install.ps1` refuses a non-empty database without `-Force` |
| Key-person dependency | **high today** | high | this plan, the oral history, a named custodian, and Directive #1's "deployable without the assistant" |
| Incumbent names in JD text | low | low | normalized out at ingestion as a rulebook quality step; JDs describe roles, not people |

---

## 11. Open questions to bring to Friday

1. ✅ Scope ruled (D1–D3, D8): everything under VPFA, Finance included, the whole
   application as is minus the dashboards. Still open: the Campus Services neighbours in
   §2.
2. ✅ Reviewers named (D4): Denise and Galib, plus two TBD. **Who are the other two**, and
   which units do they cover? And is HR content for VPFA to act as its proxy (D7)?
3. **D9:** after day 1, does the spinoff produce VPFA's roles itself (recommended), or
   take periodic copies from the parent, which would replace VPFA's own drafts and reviews
   each time?
4. **D5:** hosting. Will ITS provide the VM, name, certificate and CAS registration (§6.2)?
5. Does the privacy office want a privacy impact assessment before the pilot? The data is
   job descriptions, not personal records, and inference stays on SFU-controlled hardware.
6. Who is the technical custodian, and on which account?
7. Pilot users: one or two names per unit.

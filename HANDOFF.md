# JD Bank — Session Handoff

🥇 **Read [`CURRENT.md`](CURRENT.md) first** — it says where every fact lives and how to
check it. This page is state and traps, **forward-looking only**; the build record lives in
[`docs/archive/`](docs/archive/). ⚠ Verify anything here against `gh pr list` and the
funnel before trusting it — a handoff that records intent as outcome is worse than one
merely out of date.

## 🔴 WHERE THE NUMBERS LIVE — read this before quoting any figure

This project has shipped wrong numbers that were **consistent across several documents**,
which is precisely why nobody caught them. Agreement between documents sharing one
unchecked source is a *correlated* failure, not corroboration. So:

| what | where |
|---|---|
| **Live counts** — documents, roles, approvable, published, the gap | 🥇 **`/jd-bank/ui/funnel`** — computed from the DB at request time |
| **Measured findings** — what we know about the archive and why | [`docs/FINDINGS.md`](docs/FINDINGS.md) |
| **What we do next** | [`docs/plan.md`](docs/plan.md) |

**This file restates no counts.** If you find a number here or in `plan.md`, it is a bug —
delete it and link instead.

⚠ **Documents and roles are different units.** The funnel labels the unit on every row
because a reader following 14,565 → 2,493 → 129 will take the last for documents. It is a
count of *roles*.

---

## 🔴 DIRECTIVE #1 — TESTED, AND DEPLOYABLE WITHOUT THE ASSISTANT

**Set by the project owner 2026-08-28. It applies to every task on this page.**

> **Every step must leave the code TESTED and every feature DEPLOYABLE THROUGH THE
> SCRIPTS, by a person, with no assistant in the loop.**

| | done means |
|---|---|
| **tested** | `make gates` green · failing test written FIRST · the guard broken once to prove it can go red |
| **deployable** | works via `build.ps1` / `launch.ps1` / `teardown.ps1` (dev) and `deploy/bundle.ps1` + `deploy/install.ps1` (fresh, offline box) |
| **discoverable** | reachable from the UI — *a feature nothing links to has not been delivered* |
| **smoke-tested** | 🔴 `make smoke` green **AND covering what you changed** — fixtures cannot be stale, so only a check against the LIVE system counts. ⚠ Smoke was database-only while calling itself "end to end"; it now checks the vector index too |
| **enforced** | `make deploy-check`, run in CI as *"Gate: deployable offline"* |

⚠ **Ask at the end of every task: "could the owner deploy and see this, tomorrow, without
me?"** If not, the task has one more step. This is not hypothetical — the live funnel
shipped 2026-08-27 with no nav entry, and for a day it read as "still the old dashboard".

Full statement in [`CLAUDE.md`](CLAUDE.md) · runbook in [`deploy/README.md`](deploy/README.md).

---

## 🔴 THE ONE THING TO UNDERSTAND

**Owner ruling, 2026-08-29 — this REPLACES the "published JDs" measure that stood here,
and that measure is now wrong. Do not restore it.**

> **Nothing is blocked on policy. Proceed with drafts. Publishing happens in the FINAL
> DEPLOYMENT, not in pilot / dev / MVP.**

**So the measure here is DRAFTS — their coverage and their fidelity.** Not published JDs.
`published` sits at 4 and is *expected* to: publishing is a deployment-phase activity and
the review queue is not the bottleneck this phase is judged on.

⚠ **What this voids, explicitly**, because it had accumulated into three documents and
several standing blocks:

- **"Done is measured in published JDs"** — gone. It made every correct engineering task
  look like a distraction, and it is what let three sessions run past the real work.
- **"Before any task, ask: does this change the number of PUBLISHED JDs?"** — gone. Ask
  instead: **does this give a role a draft, or make an existing draft truer to its
  sources?**
- **"B2/B3/B4 are the only work that matters"** — no. They are deployment-phase asks.
  B3 is ratified, and the rest do not gate anything built here.
- **⛔ "No further producer runs — zero published JDs each"** — the *reason* is void.
  The cost (~44 hours for a full pass) is real and unchanged, so scope the run
  (`--only-undrafted`, `--only-template`) rather than avoid it.
- **HR-223 `drop`** still ships, but it is no longer "the ceiling cannot move until HR
  rules". A one-of-a-kind job producing no draft is now an ENGINEERING gap (plan.md D1a).

**What has NOT changed:** a draft is still a draft. Nothing auto-publishes, human approval
still gates PUBLISHED, and the rulebook gates still say what they say. Ratifying B3 *as
shipped* did not move any gate — see the register.

---

## 🔴🔴 A JDFN PRODUCER PASS IS IN FLIGHT — started 2026-09-11 04:04:58 UTC

```
jd-canonical-jdfn-rerun
  python -u -m src.jd_bank.canonical --only-template jdfn --commit-every 25
```

**No `--resume` — it is a RE-BASELINE.** Check it BEFORE starting anything that writes
drafts.

🔴 **THE ~19-HOUR ESTIMATE IS WRONG. IT IS ~51 HOURS — MEASURED 2026-09-11 OVER FOUR
CHECKPOINTS.** The pass prints its own rate; don't estimate it, read it:

```
[canonical-producer]  25/2453 clusters | ... | elapsed=1802.1s
[canonical-producer]  50/2453 clusters | ... | elapsed=3673.5s
[canonical-producer]  75/2453 clusters | ... | elapsed=5558.9s
[canonical-producer] 100/2453 clusters | ... | elapsed=7460.8s
```

**Per-batch: 72.1 → 74.9 → 75.4 → 76.1 s/cluster.** The rate is NOT startup inflation —
every batch after the first is *slower* than it, and the trend creeps mildly upward. At
74.6 s/cluster overall, 2,453 clusters ≈ **51 hours**, landing ~**06:00–08:00 UTC on
2026-09-13** — not 23:00 on 2026-09-11. The ~19 hours was carried over from the CUPE pass;
this cohort is roughly 2.5× slower per cluster and nobody had re-measured it.

**Plan for more than two days, not one overnight**, and note what that implies: trap 5
below (the stack has **no `restart:` policy**) now has two extra days to bite, and a
Docker Desktop restart mid-pass is exactly how a 52-minute pass was lost on 2026-08-20.
If it does die, **`--resume` continues it safely (#126)** — starting it WITHOUT `--resume`
pays for every cluster again.

⚠ **Re-read the rate rather than trusting this line.** It is four checkpoints out of 98,
and the per-batch figure is still drifting up; the cohort could slow further.
`docker logs --tail 2 jd-canonical-jdfn-rerun` and divide.

⚠ And `refreshed=25 failures=0` is a COUNTER, not the Bank. It says what the run did, not
what is true — `make bank-audit` against `docs/canonical/bank-audit-before-jdfn.json` is
the verdict, and nothing else is.

```bash
docker ps --filter "name=canonical"          # non-empty => a pass is running
docker logs --tail 5 jd-canonical-jdfn-rerun # progress every 25 clusters
```

⚠ **Silence is not failure for the first ~40 minutes.** The first progress line and the
first commit both land at 25 clusters. Zero log lines and 0.00% CPU is what a HEALTHY
pass looks like while it waits on the model — a run was nearly killed as hung for exactly
this reason on 2026-08-20. To tell alive from stuck, ask something other than the log:

```bash
docker compose exec -T postgres psql -U app -d harness -c \
  "SELECT state, to_char(query_start,'HH24:MI:SS') FROM pg_stat_activity \
   WHERE datname='harness' AND pid<>pg_backend_pid() AND state<>'idle';"
```

`idle in transaction` on a `review_actions` count, with `query_start` ADVANCING every
1–3 minutes, is a working pass. It is not `--rm`, so if it dies the container survives
for `docker inspect`.

⚠ **Never `--remove-orphans`** while it runs: it is a compose one-off, so compose reports
it as an orphan and the flag deletes it mid-pass.

#### What it must produce, and the file to diff against

The BEFORE audit is committed at **`docs/canonical/bank-audit-before-jdfn.json`**.

| JDFN, before the run | |
|---|---|
| drafts | 1,872 · mean **78.2** · 1,321 approvable |
| relationships | 64.7% |
| decision_making | 64.6% |
| **problem_solving** | 🔴 **233.1% — 636 drafts carry it with NO source** |

```bash
make bank-audit          # then diff against the before file
```

**Success = `problem_solving` at or below 100%, and relationships / decision_making
rising toward it.** ⚠ **EXPECT THE JDFN MEAN SCORE TO FALL.** That is fabrication being
withdrawn — the S-5 argument — and a rising score has been the signature of three
separate content-loss defects here. Treat a rise as a question.

#### Why this pass was trusted to start (the ~90-second check, run first)

Cluster `a622f3cf`, 40 members — the defect caught on live data:

```
CURRENT draft: problem_solving=3   ...while 0 of 40 SOURCES state any
SOURCES: 40/40 state decision_making, 0/40 state problem_solving
MERGE  -> duties=5  dm=6  ps=0  rel=YES
REWRITE-> duties=5  dm=5  ps=0  rel=YES  score=74.29
         scrubbed_sections=()   invented_duties=0
```

Grounded decision-making comes through; problem_solving stays empty. **Do this check
before any future pass** — two passes were started on unverified fixes and both were
still wrong.

## 🔴 HANDING OVER THE BOXES — the state that is NOT in git

There are **TWO** machines and the system needs both.

| | |
|---|---|
| **this box** | the repo, Docker stack, the archive, the backups |
| **`aria-gb10-2`** | **Ollama.** Every embedding and every LLM pass calls it (ADR-003). No producer run, no `make embed`, no Builder assist without it. It is not in this repo and nothing here provisions it |

**A fresh `git clone` will not run.** These are real and invisible in a diff:

1. **`.env` is GITIGNORED and carries the auth posture.** Keys currently set:
   `CAS_ENABLED` (**true**), `CAS_SERVICE_BASE_URL` (`http://sfuai.ca:7000`),
   `ALLOWED_SERVICE_ORIGINS` (`http://localhost:25800,http://sfuai.ca:7000`),
   `CAS_VERIFY_TLS`, and **`BOOTSTRAP_ADMINS` — set to the owner's SFU id, which is WHO
   GETS ADMIN on first sign-in.** A new owner must set it to their own id or they cannot
   administer the app. The committed compose defaults are all safe/off, so a clone comes
   up with CAS disabled and no admin.
2. **`JD_ARCHIVE_PATH` is UNSET in the shell.** The Makefile falls back to `./archive`,
   which is empty, and the baseline runner then REFUSES rather than producing a confident
   baseline of nothing. The real archive is `C:\repos\hris\fixtures\SFU_JDs` —
   **external and read-only**, and not part of this repo. Pass it explicitly:
   `make baseline JD_ARCHIVE_PATH=C:/repos/hris/fixtures/SFU_JDs`.
3. **Backups live at `C:\Users\adam\jd-bank-backups\`**, outside the repo:
   `harness-pre-full-llm-run.dump` (81 MB), `harness-pre-cupe-rerun-20260819.dump` (82 MB),
   and `env.cas-enabled-20260909.bak`. ⚠ Back up **Postgres only** — Neo4j is a derived
   index, rebuilt with `make embed` / `make embed-roles`. ⚠ And `pg_restore --data-only`
   WIPES the Bank and exits 0; restore a full `-Fc` dump into an EMPTY database.
4. **The published port varies.** `${JD_API_PORT:-25800}` — it was 25900 and 25800 on this
   machine within a day. `docker port jd-bank-api-1` is the answer, not the docs.
5. **The stack does not self-restart.** No `restart:` policy, while every other project on
   this box has one. A Docker Desktop restart on 2026-08-20 killed a 52-minute producer
   pass and left the stack down for ~50 minutes with nothing saying so.
6. **Other projects share this box.** Stray `postgres:16-alpine` / `neo4j:5-community`
   containers are `recruiter-assistant`'s testcontainers, not ours.

7. ⚠ **Git Bash mangles container paths.** A `docker compose run ... sh -c '... /committed/ ...'`
   issued from Git Bash can have MSYS rewrite `/committed` to `C:/Program Files/Git/committed`,
   which silently creates a junk `core/C:/` directory in the repo. Delete it (`rm -rf "core/C:"`)
   and prefer PowerShell, or `MSYS_NO_PATHCONV=1`, for commands passing absolute container paths.
8. ⚠ **The `./docs/canonical` bind mount lags on Windows.** A file the container has just
   written may not appear to `ls` on the host for a few seconds — it is propagation delay,
   not a failed write. Re-check before concluding the run did not produce its artifact.

⚠ **With CAS ON you cannot `curl` a UI route to check it** — every one 303s to login.
Verify through the suite, or `launch.ps1 -NoCas`.

## ▶ WHAT IS OPEN, in the order I would take it

1. **Land the JDFN pass** — `make bank-audit`, diff the before file, confirm
   `problem_solving` ≤ 100%. If it did not finish, `--resume` continues it safely (#126);
   **do not** start it without `--resume` a second time or it pays for every cluster again.
2. **✅ ALL OF 2026-09-11's WORK IS MERGED.** Nothing from that session is left open.

   | PR | what |
   |---|---|
   | #186 | **P3f** — the grade matchers are rulebook data (HR-233 … HR-236), no value changed |
   | #187 | **P3g** — an over-long role gets a SHORTER vector, not a gap |
   | #191 | **P3c measured** — *do not build the detector*; diagnoses **P3h** (replaced #188) |
   | #189 | **funnel** — a false "Reliable." + 29 double-encoded characters |

   🔴 **TWO STACKED-PR TRAPS, BOTH HIT ON THE SAME DAY. Read this before stacking again.**

   - **#186 merged as a MERGE COMMIT**, so its branch survived, so GitHub did **not**
     retarget the PR stacked on it. #187 kept pointing at a branch already contained in
     `main` — and reported `MERGEABLE` throughout. Caught only by checking the base.
   - **#187 was then merged with `--delete-branch`, which CLOSED #188 outright.** GitHub
     does not retarget a PR whose base branch is deleted; it closes it. And a closed PR
     whose base is gone **cannot be reopened or retargeted** — both API calls refuse. The
     work was recovered by rebasing the two commits onto `main` and opening **#191**.

   ⚠ **So: retarget the child FIRST, then merge the parent.** Neither failure mode announces
   itself, and one of them silently closes work that was finished and green.

3. 🔴 **THE LESSON OF 2026-09-11, and it cost most of the session: THIS PAGE AND `plan.md`
   WERE STALE IN THREE PLACES, AND EACH STALE ROW HID THE REAL DEFECT.**

   - **P3g** said *"`embed-roles` is not resumable past a bad row"*. That was fixed in
     `ba196b9` **two weeks earlier**. The live defect was one row further on: an over-long
     role was isolated and **counted**, and still got **no vector** — counted is not
     embedded. Fixed in #187 by porting the HR-193 ladder the document runner already had.
   - **P2** said *"the next parse task"*. Its baseline half shipped **2026-08-29** (§7c says
     so). The live defect was on the FUNNEL, whose Form facet called itself **"Reliable."**
     while knowing the field for **48.0% of roles**. Fixed in #189.
   - **P3c** said *"needs a measurement"*. The measurement (#188) says **do not build the
     rule**: one case in 14,522, and every shape that catches it flags up to 1,429 correct
     titles. It also **diagnosed P3h**.

   **So: re-derive a row before working it.** Every one of these was answerable in minutes
   against the live Bank, and each stale row had already misdirected somebody.

4. **`P3h` — 53 titles are a PARAGRAPH, and it is BLOCKED until the pass lands.** The
   residual of the v2→v3 `_fallback_title` defect (**not** new — the first draft of that row
   said so and was wrong). Diagnosed in #188: **zero CUPE**, all 53 on the JDFN path, every
   one also carrying `department = None`, so the identification block was not recovered at
   all. 🔴 **It bumps `PARSER_VERSION`, whose contract requires the archive re-parse in the
   SAME change — and a re-parse must not run while a producer pass is reading
   `parsed_jds`.** Queue it behind the pass.

5. **When the pass lands, `make embed` + `make embed-roles` are OWED** — that is what turns
   `make smoke` green again, and it is the whole of P3g's remaining half. They need
   `aria-gb10-2`, which the pass holds, so **do not start them concurrently**.
6. **The six unassigned departments** — one-line edits to `org_units.yaml`, each already
   rendered as a candidate on its unit page: **Human Resources (52)**, Financial Aid &
   Awards (8), Procurement Services (7), Budget Office (4), Enterprise Risk & Resilience
   (3), Campus Public Safety (2). None was named by the owner; none may be inferred.
7. **`ITP/S` is legacy** — the IT collection (213) vs the ITS department (54) is with the
   **CIO and VPFA**. Both surfaces ship deliberately and the ITS page explains why. Do not
   "fix" one to match the other.
8. **Duty-frequency matching** — 28.5% rewritten vs 100% merge-only. The one-line fix is
   UNSAFE (the model reorders; argmax and positional agree 8–26%). Needs a design.
9. **677 roles (27.1%) carry no department** — every unit page says so. It is a
   parse-coverage gap, and it is the first thing a stakeholder asks about.

## ▶ CURRENT STATE — 2026-08-29

🔴 **`make smoke` is RED, deliberately, and that is the honest state** — see *What smoke
now checks* below. `make gates` (3,046 · 92%), `make deploy-check`, CI and the register
gate are green, `main` is clean and nothing is half-finished in the tree.

**Formerly:** `make gates` (3,040 · 92.18%), `make smoke`
(6), `make deploy-check`, CI, no open PRs. Nothing is half-finished in the tree.

**The measure is DRAFTS, and they moved:** every cluster now has one (the 24-gap closed by
`--only-undrafted`), 2,483 of 2,500 hold rewritten prose, and **approvable rose 1,299 →
1,327** off the v8 re-parse. Published stays at 4 — correct; that is deployment-phase.
⚠ Live counts: `/jd-bank/ui/funnel`. Never this page.

🔴 **THE DEV/TEST ITERATION IS CLOSED — the MVP run order is [`docs/plan.md`](docs/plan.md)
§ THE MVP RUN ORDER.** Read that before picking anything up; the track tables below it are
now slotted MVP-0 … MVP-4.

**The first HR ratifications landed 2026-08-29: HR-042 and HR-052** (B3 — the two approval
gates), ratified **AS SHIPPED** and logged by ITS. ⚠ **This did not unblock CUPE.** No
value changed and `rules_version` is unchanged, so nothing re-validates and no count moved;
what changed is that the bar is now signed, so a failing draft is non-compliant with a
standard rather than blocked by an open question. The remedy became content work. ⚠ The
two entries are **attribution-light by instruction** — they record THAT the ruling happened
and not its substance; the register says so in each `decision_note`.

**Track A (the demo) is COMPLETE.** Three live surfaces, all reading the DB at request time:

| | |
|---|---|
| `/jd-bank/ui/funnel` | 🥇 archive → published, scope-parameterised, full gap accounting |
| `/jd-bank/ui/collection/it` | the IT collection · `?queue=1` for the review queue |
| `/jd-bank/ui/compose/new` | the Builder — search, clone, live compliance |

`PARSER_VERSION` **`jd_segmenter_v8`** — bumped THREE times on 2026-08-29 (v6 = the
employee group, HR-226; v7 = the WJQ title; v8 = `Department Name/Section`, unreadable
department labels 680 -> 16, +607 in the Bank). **Each bump shipped WITH its re-parse**, as that
constant's contract requires: a bump without one leaves every layer querying a version
with no rows, i.e. an apparently empty Bank.



### ▶ CAS IS ON — and it is a box-local `.env` value, not a repo setting

**`CAS_ENABLED=true`** as of 2026-09-09, restored for the CIO AI task force demo. It
lives in the repo-root **`.env`, which is gitignored**; the committed compose default is
`false`, so this never shows in a diff and a fresh checkout does not inherit it.

Verified end to end rather than by the flag: a protected page 303s to login, `/cas/login`
302s to `https://cas.sfu.ca/cas/login?service=…`, and `cas.sfu.ca` answers 200. The
service URL resolves to **the origin the request arrived on**, so both
`http://localhost:25800` and `http://sfuai.ca:7000` work — that is `ALLOWED_SERVICE_ORIGINS`
(P0.3) doing its job, not a coincidence.

⚠ **With CAS on you cannot `curl` a page to check it** — every UI route 303s. Verify
through the suite, or `launch.ps1 -NoCas` / flip the one line. A copy of the CAS-enabled
file is at `C:\Users\adam\jd-bank-backups\env.cas-enabled-20260909.bak`.

⚠ **The published port varies by box** (`${JD_API_PORT:-25800}`). It has been 25900 and
25800 on this machine within a day. `docker port jd-bank-api-1` is the answer; the guide's
25800 is the committed default and is not wrong.

### ▶ CONTENT CARRY-THROUGH — `make bank-audit`, measured 2026-09-09

**The funnel counts DRAFTS; this counts CONTENT.** They answer different questions and
the second one has caught every content-loss defect this project has had. For each
section, per form: how many clusters' **sources offered** it vs how many **drafts keep
it**. A producer summary cannot see any of this — `refreshed=649 failures=0` prints
identically whether a run enriched every draft or gutted it.

```bash
make bank-audit                       # exits 2 on a verdict; run BEFORE and AFTER a pass
make bank-audit AUDIT_ARGS="--json"   # two runs diff cleanly
```

Two readings worth knowing before you read the output:

- **the merge-only CONTROL.** A rewrite *failure* falls back to the deterministic merge,
  so those drafts are the same pipeline with the model removed — a controlled comparison
  the Bank produces for free.
- **carry-through ABOVE 100% is FABRICATION**, not an arithmetic bug. A draft can only
  carry what its sources stated.

**✅ CUPE IS REPAIRED — and this is the closed loop worth knowing about.** The WJQ parser
recovered no duties from 16.2% of CUPE documents; the merge correctly produced nothing;
and the rewrite filled the silence with **996 invented duties across 101 drafts**. Fixed
end to end by the parser column-gap fix (#137) + HR-213 (`rewrite.duties_never_invented`)
+ the v8 re-parse + a producer pass. Measured today: **0 invented duties on CUPE**,
`additional_context` and `relationships` both **100%**.

🔴 **JDFN WAS NEVER RE-RUN, AND STILL CARRIES THE SAME DEFECT:**

| JDFN, measured 2026-09-09 | |
|---|---|
| `problem_solving` | **232.8% — 635 drafts carry it with NO source** |
| `relationships` / `decision_making` | **64.7% / 64.6%** — content the sources state, dropped |
| invented duties | **51 drafts, 218 duties** (38 unclassified + 13 apsa) |

A JDFN producer pass is what closes this, exactly as the CUPE one did. Until then **do not
quote a JDFN content figure** from anywhere.

⚠ **AND IT IS NOW DEMO-VISIBLE.** The Bank went in front of the CIO AI task force on
2026-09-10, and the unit pages link straight through to roles. A JDFN role opened from
VPFA or Facilities can show a Problem Solving section **no source document wrote**. The
CUPE cohort is clean; JDFN is not, and the difference is invisible on the page. The pass
takes roughly the 19 hours the CUPE one did (`--only-template jdfn`), so it is an
overnight job, not a pre-meeting one — but it should not keep slipping now that a
stakeholder audience can reach it.

🔴 **THE DUTY-FREQUENCY DEFECT IS OPEN, AND THE NAIVE FIX IS UNSAFE.** WJQ duty frequency
survives on **28.5% of rewritten duties against 100% of merge-only ones** — the rewrite
destroys a field the merge preserves, and frequency is an input to the CUPE point-factor
evaluation, so a dropped one is a missing evaluation signal and not just missing text.

The restore exists but sits *inside* the well-grounded branch, so a heavily-reworded duty
keeps nothing. **Do not simply move it out.** Measured over 120 real clusters: duty counts
align 91.7% of the time, but argmax and positional matching agree only **8–26%** — the
model reorders heavily — and **62.4%** of duties share under 0.2 Jaccard with any merge
duty. Both obvious rules would attach a **wrong** frequency, which is worse than a missing
one. This needs a matching design with evidence behind it.

⚠ **`flagged_duties` has become a constant** — 97.0% of JDFN drafts and 97.6% of WJQ ones
carry at least one. A finding on nearly every draft is not a signal; `duty_flag_threshold`
(HR-184) wants re-measuring rather than quietly re-tuning.

### ✅ MVP-2 (VPFA · Facilities) — SHIPPED 2026-09-09 (#183), live behind CAS

The org tree came from the owner, so the build is done and merged. Six units, each a
funnel collection like the IT one — **not** nav items, which was a correction: a unit is
a named subset of the Bank, and two portfolios in the menu imply a tree that is complete
when it is not.

| unit | roles | |
|---|---:|---|
| **VPFA** `/unit/vpfa` | **160** | the portfolio; Facilities, Finance, ITS, Safety & Risk and Campus Services roll up into it |
| **Facilities** `/unit/facilities` | 57 | incl. Campus Security — the boundary call Track E had open, settled by the owner |
| ITS `/unit/its` · Finance `/unit/finance` · Safety & Risk `/unit/safety-risk` | 54 · 31 · 10 | |
| Campus Services `/unit/campus-services` | **0** | named as a sub-unit; **no department string in the archive names it** |

Linked from the **funnel footer** beside "The IT collection". `?scope=<slug>` also works
on the funnel, but the footer deliberately links the LIST — the first cut led with the
scope and landed every reader on more statistics.

**Each page carries THREE numbers** — in the unit · not in it · **department unrecorded
(677, 27.1%)**. `UnitRollup` has no single "other" field, so a template cannot collapse
that distinction even by accident.

🔴 **MEMBERSHIP IS AN EXACT LIST, NEVER A PATTERN** (`org_units.yaml`, HR-227…HR-232, all
`open`). `Science - IT Services` is in the archive and may be a faculty's own IT; a phrase
match on "IT Services" claims it either way. Deliberately excluded, with a test. The
MECHANICAL half of aliasing IS automated (`&`/`and`, unicode dashes, case, whitespace);
word ORDER is not, because deciding two orderings name one team is a judgement.

⚠ **SIX DEPARTMENTS ARE DELIBERATELY UNASSIGNED**, each a one-line rulebook edit and each
rendered on the page as a candidate: **Human Resources (52)**, Procurement Services (7),
Financial Aid & Awards (8), Budget Office (4), Enterprise Risk & Resilience (3), Campus
Public Safety (2). None was named by the owner. "Financial" in a name is not evidence of
a reporting line — `Student Services - Student Accounts` is the counter-example in the
same data. 655 departments are unassigned in total.

⚠ **TWO SURFACES ANSWER "IT" ON PURPOSE.** ITS the department is **54**; the IT collection
is **213** — a strict SUPERSET (all 54 in both, 159 IT roles in faculties and schools,
none in the department but outside the family). Kept apart pending a **CIO / VPFA**
conversation, because the **ITP/S classification is legacy**. The ITS page renders the
comparison so nobody "fixes" one to match the other: rolling the portfolio up through the
family would add 159 faculty IT staff to a vice-president's total.

### 🔴 What `make smoke` now checks — and why it is RED

**Owner ruling 2026-08-29: only claim completion after an end-to-end smoke test**
(Directive #1 item 5). The rule exists because `make smoke: 6 passed` was quoted as
end-to-end evidence for days while smoke was **database-only** — six Postgres
reconciliation tests, no Neo4j, no HTTP, no search — under a docstring that called it
"end to end".

It now also checks the **derived index**, and fails on two real, open things:

| red | why | fix |
|---|---|---|
| document vectors at `jd_segmenter_v2` | six parser bumps stale; the vector query has no version filter, so it silently ranks on text the parser no longer produces | `make embed` (long; needs Ollama) |
| 1 embeddable role has no vector | the runner reports `2,500 seen = 8 empty + 2,491 unchanged` — which does not reconcile. A small accounting hole | plan.md **P3g** |

⚠ **Leave it red until those are fixed.** A green smoke that does not cover the change is
worse than a red one that does.

**What was fixed getting here:** `make embed-roles` used to ABORT — one
`EmbeddingBadRequestError` escaped the batch loop, stopping at 2,152 of 2,500 while the
make target said only `Error 1`. Now isolated and counted, and role vectors went
**1,797 → 2,491**. ⚠ The error named the symptom, not the cause: with isolation ZERO roles
are rejected, so no single role is over-length — the **batch** exceeded the context in
aggregate.

### ⚠ Before you demo or test: two things `launch.ps1` does NOT do

1. **The vector index is stale, and it is silent about it.** `(:JDDocument)` nodes carry
   `parser_version = jd_segmenter_v2` — **six bumps ago**. Search still WORKS (the query
   is `db.index.vector.queryNodes` with no version filter), so nothing errors; it is
   ranking on text the parser no longer produces. Refresh with `make embed`
   (skip-first; needs Ollama on `aria-gb10-2`).
2. ✅ **FIXED** — `(:JDRole)` held 1,797 vectors against 2,500 roles — 703 roles were INVISIBLE to
   Builder search**, with no error anywhere. Neo4j is a DERIVED index: nothing rebuilds it
   when the Bank grows, and no gate notices. `make embed-roles` after any producer run —
   The abort is fixed and it now reaches **2,491**; `make smoke` checks the coverage.

⚠ **The port is not fixed at 25800.** `launch.ps1` defaults to it, but `JD_API_PORT` in the
launching shell wins — this box has been running on **25900** for that reason.
`docker compose port api 8000` prints the truth.

### What changed on 2026-08-28/29, and what it left behind

- **The parse was the root problem, and it is fixed (HR-226).** A job was being called
  CUPE because it *mentioned* the word — APSA managers who supervise CUPE staff. Two more
  defects fell out of the same investigation: the title family called an Executive
  Assistant a VP (HR-224), and the Builder's CUPE form searched JDFN documents (HR-225).
  All measured against the **raw archive files**, not the database. [`FINDINGS.md`](docs/FINDINGS.md) §7.
- **The 24 drafts built from mislabelled documents were DELETED**, on the owner's ruling —
  a cluster with no draft reads as *un-drafted*; one with a wrong draft reads as finished.
  `core/db/repairs/001_drop_mislabelled_cupe_drafts.sql`. ⚠ **`audit_log` was deliberately
  not written**: it is hash-chained (`audit_chain_tail`) and forging an entry the app never
  made would corrupt it. **24 clusters now have no draft** and nothing regenerates them —
  that is plan.md **P4**.
- **The bargaining unit is now its own facet** with `(unrecorded)` named (P2). The
  "By template" table was being read as an APSA-vs-CUPE split and is not one — its `jdfn`
  bucket also held every document naming no unit. ⚠ Measured while fixing it: the
  unrecorded are **the OLD archive** (88% old/transition, **not one current-era
  document**), so counting them as JDFN blended thousands of modern APSA JDs with
  thousands of pre-2019 ones. §7c-i.
- **Half the CUPE archive had no title, and now does (P3a).** 47.6% of CUPE documents
  carried the `Untitled Position` sentinel against **0.0% everywhere else** — antiword's
  render puts the label and its value in ONE cell while the parser read the next one.
  **805 titles recovered, 47.6% → 28.9%**, position numbers +593. §8.
- **Offline deployment exists and was verified end to end** (bundle → install on separate
  volumes/ports → row counts matched). See below.
- **The operator scripts are now `build.ps1` → `launch.ps1` → `teardown.ps1`.**

### The three things that actually need a person

1. **B2 / B4 — the HR asks.** B3 is RATIFIED (see above). **B2, the pilot, is now the only
   work that moves the published count** — pure lead time, and nothing should be sequenced
   behind it. B4 is the remainder of the register; the count outstanding is in the
   register's own header, which now separates still-outstanding from ratified.
2. **A6 / A7 — the ITS director sessions.** Work the review queue and vet the department
   alias list; their rulings land in HR-217/218.
3. **D1 — rule on the one-of-a-kind job (HR-223).** The pipeline builds a role from a
   GROUP of near-duplicates, so a unique job produces nothing. **The only open item that
   raises the ceiling on what can ever be published.** The decision is now REGISTERED and
   the population MEASURED by code anyone can re-run — `make singletons`, four buckets and
   a control, [`docs/singletons/`](docs/singletons/). `drop` still ships, so nothing has
   changed until HR rules. [`docs/FINDINGS.md`](docs/FINDINGS.md) §2a.

### If you are picking up engineering, start here

| | |
|---|---|
| ~~**P3b**~~ ✅ | **AUDITED 2026-08-29 — the third field checked, the third to produce a defect.** `make field-audit`. 🔴 **726 CUPE departments the archive states and the Bank does not.** ⚠ Re-probed in the PARSER'S scope (`--identification-only`) the diagnosis INVERTED: it is not a read failure but **one unregistered label, `Department Name/Section`, ~667 of 680** (§9g — and §9b/§9c record the wrong turn). **P3d is now a bounded fix**; **E1 VPFA waits on it** — a rollup on this column today would be confidently wrong. |
| **P4** | **24 clusters have no draft** and nothing regenerates them. `src.jd_bank.canonical` has `--only-template` but no per-cluster filter, so re-drafting exactly those is not expressible; a full producer run is under a standing ⛔. Needs a ruling, not code. |
| **P3c** | ⚠ **One recovered title contains an incumbent's name** (`Leigh McGregor. Departmental Assistant`). Needs a measurement and a registered rule — NOT a name-shaped regex invented on a sample of one (NN #5). |
| ~~**D1**~~ | ✅ **Landed 2026-08-29 as HR-223** — the parked stash was recovered onto current `main` and its numbers RE-DERIVED before commit. ⚠ **They had not survived the week:** three of four buckets moved and the qualification comparison inverted outright (the draft called the pool qualification-poor at 1.46 vs 8.84; it measures 9.54 vs 8.89, with medians 0.0 and 1.0 that make both means meaningless). **The stale half was identified because the OTHER half reproduced exactly.** §2a. |
| **D1a** | **Enact whichever policy HR rules for.** Not before D3 — `mint_role` over the whole pool would also mint a role for each of the 497 recall misses. plan.md D1a. |

⚠ **The method is the finding.** Every defect this session came from reading the SOURCE
FILES and running a CONTROL first — never from the database, and never from an aggregate.
Three times the first answer was wrong: a probe whose scope did not match the parser's, a
tokenizer that could not split `00001726Clerk`, and a facet of my own that blurred "could
not evaluate" with "evaluated and found nothing". **Run the control before believing the
result.** [`FINDINGS.md`](docs/FINDINGS.md) §8c.

Everything else, including the rest of the archive gap, is in [`docs/plan.md`](docs/plan.md).

**Queued next features** — slotted in [`docs/plan.md`](docs/plan.md) § THE MVP RUN ORDER,
which is the order of record. It is **E → G → F**, and this page used to say E → F → G:

1. ~~**MVP-2 · Track E — the next units**~~ ✅ **SHIPPED 2026-09-09 (#183).** Six units,
   VPFA 160 · Facilities 57, as funnel collections. What is LEFT is not code: six named
   departments still unassigned (Human Resources at 52 the significant one), each a
   one-line edit to `org_units.yaml`, and each already rendered on the page as a
   candidate. See the MVP-2 section above.
2. **MVP-3 · Track G — upload a JD into the Builder**
   ([`docs/plans/BUILDER-UPLOAD-AND-CHECK.md`](docs/plans/BUILDER-UPLOAD-AND-CHECK.md)):
   upload a Word file or PDF → parse → compliance panel → optionally seed a draft, turning
   the Builder into a JD assistant anyone with a document can use. Designed 2026-08-29
   against the live code. **Mostly reuse** — a new front door onto the clone chain that
   already runs. ⚠ **Three things bite first, all verified against the code 2026-08-29:**
   `python-multipart` is *deliberately* absent and the CSRF check reads the body before the
   handler — which means an upload does not fail to parse, it is **refused with a 403**
   (`body.decode("utf-8")` raises on binary, the check catches it and finds no token); PDF
   has no extraction backend at all; and both fixes move `requirements*.txt`, which is
   exactly when the **offline bundle must be re-cut**. Does not move the published count —
   it changes *who can use the Bank*.
3. **MVP-4 · Track F — JD currency after publishing**
   ([`docs/plans/JD-CURRENCY-ATTESTATION.md`](docs/plans/JD-CURRENCY-ATTESTATION.md)):
   steward attestation on a cadence, REAFFIRM / REVISE / RETIRE, stale advisory on every
   axis, nothing auto-unpublishes. Designed 2026-08-28 against the verified base —
   `rules_version` is already stamped and publish dates derive from APPROVE rows, so
   drift detection needs no new fields; the genuinely new pieces are the `attestations`
   table, the RETIRE action (no retire path exists today), stewards, and `currency.yaml`.
   **Last on purpose:** with four published JDs a currency loop is ceremony; B2's twenty
   make it real.

---
## ▶ IF YOU ARE STARTING COLD

```bash
git fetch && git log --oneline origin/main -1
gh pr list                                        # never trust a table for this
docker ps --format '{{.Names}}' | grep jd-bank    # ⚠ the stack does NOT self-restart
.\launch.ps1                                      # ...if that came up empty or short
docker ps --filter "name=canonical"               # MUST be empty; do not start a run
```

**Three scripts, one job each — `build.ps1` → `launch.ps1` → `teardown.ps1`.**

| | |
|---|---|
| `.\build.ps1` | build the images **and prove they are deployable** (`-NoCache`, `-Bundle`) |
| `.\launch.ps1` | start → healthy → migrate → **verify** → status (`-NoCas`, `-Rebuild`) |
| `.\teardown.ps1` | stop, data KEPT (`-Orphans`, `-Volumes`, `-ProjectName jd-bank-test`) |

⚠ **`launch.ps1` now fails loudly if any service is not RUNNING.** `up --wait` only
proves the services it started came up; it says nothing about one that started and then
died. Editing `docker-compose.yml` makes the next `docker compose run` recreate
dependencies, which drops the worker's Redis connection and arq exits — on 2026-08-28
the worker sat `Exited (1)` for **nine hours** with the stack otherwise green and nobody
noticed. Do not read the status table; read the verdict under it.

⚠ **`teardown.ps1 -Orphans` clears what compose will not.** One-shot `docker run` jobs
are not compose services, so `down` leaves them forever — three sat exited for a week,
making every compose command print an orphan warning everyone had learned to ignore.
That is how a real warning gets missed.

`quickstart.ps1` still works; it forwards to `launch.ps1` with a deprecation notice.

⚠ **The box runs other Docker projects.** Random `postgres:16-alpine` /
`neo4j:5-community` containers are `recruiter-assistant`'s testcontainers, not ours.

**Then open `/jd-bank/ui/funnel`.** It is the fastest way to see the state of the archive,
and it is the only place those numbers are authoritative.

**Then run `make smoke`.** The end-to-end check against the live Bank — parsing, dedup,
categorize, filterable — fails if a single document is unaccounted for or unfindable.

**Then run `make bank-audit`.** Read-only, seconds, no GPU. The funnel says how many
drafts exist; this says what is IN them, per form — and it is the only view that shows
content being lost or invented. See *Content carry-through* above for what is currently
open.
Trust it over any document, including this one.

---

## ▶ DEPLOYING TO A FRESH BOX, OFFLINE

**Built and verified 2026-08-28.** The repo can be put on a box with Docker and **no
internet** and come up as a working Bank with the archive already in it.

```bash
make bundle                                          # on a CONNECTED box -> dist/ (~1.4 GB)
.\deploy\install.ps1 -BundleDir <bundle>             # on the TARGET — never touches the network
make deploy-check                                    # cheap standing check; run after compose/Dockerfile edits
```

Full runbook: [`deploy/README.md`](deploy/README.md).

- **A code change does NOT need a new bundle.** `api`/`worker` bind-mount `./core`, so
  copying the repo is enough. Re-cut only when `requirements*.txt` or the `Dockerfile`
  moves.
- **`install.ps1` passes `--no-build --pull never`**, so a missing image fails loudly
  instead of quietly pulling — an install that silently pulls has proved nothing about
  the offline box.
- **It refuses to restore over a populated database.** `pg_restore --data-only` into a
  migrated DB silently destroys the Bank and exits 0; the bundle carries a full `-Fc`
  dump and the target must be empty (or `-Force`).
- **Verification is part of the install** — row counts are compared against the bundle's
  manifest and the Neo4j vector nodes counted; it exits non-zero if anything disagrees.
- ⚠ **Only the internet is optional.** Ollama on `aria-gb10-2` is still needed for
  `make embed` and the LLM jobs; the app, funnel and dashboards do not touch it.

Validated by rehearsing a full install beside the live stack under a second project name
— all five row counts and both Neo4j labels matched, and the funnel rendered from the
restored database.

---

## ▶ HOW WE WORK

- **Docker-only (ADR-006).** No host Python/venv/pip. `make gates` runs the full suite
  (incl. testcontainers integration) in the one-shot `gates` service — CI-identical.
- **TDD.** Failing test first. Every rulebook gate has a failing- and a passing-fixture test.
- **Rulebook as data.** Any non-trivial metric/rule is YAML-configurable **and registered
  in the same PR**. The build refuses to load an unregistered knob — this is enforced, not
  advisory. If a default looks wrong, register it `open`; never quietly patch it.
- **Branches and PRs:** see `CLAUDE.md` § *Change workflow* — code always via PR; most
  docs commit straight to `main`; **this file and `docs/plan.md` still go via PR.**
- **Re-run `make gates` yourself before committing.** A subagent's claim of green is not
  evidence of green; require the pasted command and its output.
- ⚠ **`make gates` bind-mounts `./core`.** Editing files mid-run invalidates the run.

## ▶ LESSONS THAT STILL BITE

Distilled from six weeks; the full set is in the archive.

- **Optimising a proxy can run forever.** Draft fidelity always has another defect at
  14,522 documents. Tie work to the deliverable or the loop never exits. *(This is the
  whole reason for the 2026-08-24 re-evaluation.)*
- **A green suite proves nothing about a guard you have not tried to break.** Three
  separate "correct fix pinned by nothing" defects. If a test's docstring explains *why*
  a property holds, break that why and watch it go red.
- **A wrong query returns 0 exactly as convincingly as a guard that never fired.** Before
  believing a zero, prove the query can produce a non-zero.
- **One sample cannot tell "working" from "stalled".** Take three. A single 38-second
  reading was misread as progress when the transaction was parked.
- **A flat metric is a question, not a verdict** — compare against a control (the
  not-yet-processed population) before acting on it. That is what caught HR-214.
- 🔴 **A measurement has a shelf life, and a parked one has already expired.** The HR-223
  numbers were measured on 2026-08-28 and recovered from `git stash` on 2026-08-29. Three
  of four buckets had moved (513 could-not-evaluate → 82) because v6→v7 recovered 805
  titles and every bucket was title-based. **Recovering parked work means re-deriving its
  numbers, not just replaying its diff.**
- 🔴 **When two numbers disagree with their re-run, the one that REPRODUCES tells you
  which is broken.** The draft claimed the no-twin pool averages 1.46 qualifications
  against 8.84 in-role. The same probe returned 8.89 in-role — reproducing that half
  almost exactly — and 9.54 for the pool, so the pool figure was the broken one, not the
  probe. **A comparison is two measurements; check them separately before believing the
  contrast.** (And the medians, 0.0 and 1.0, then showed neither mean meant anything.)
- **Print the sample, and read it.** The unique-title count looked clean until the
  verbatim list showed `#01246` and `.....Televis` sitting in it. One case was
  definitional and fixed; the rest were published as an upper bound rather than
  classified away on a sample of sixty.
- 🔴 **A probe that disagrees with the parser IN THE PARSER'S FAVOUR is broken.** The
  field audit reported "no label found" for 129 of 129 APSA documents while the parser
  held a department for 52 of them — because identification labels have TWO provenances
  (rulebook `id_labels` for the WJQ form, hardcoded regexes for the modern one) and the
  probe knew only the first. Later, a `\b` fix made APSA `position_number` fall from
  4,836 to 310 against a parser holding 4,753. **Both times the direction of the
  disagreement was the tell**, long before the number was.
- **Fixing a substring bug with `\b` can be worse than the bug.** `\b` asserts a
  word/non-word *transition*, so `\bposition #\b` never matches `Position #:`. What was
  actually meant is "not butted against a letter or digit" — lookarounds, not `\b`.
- **Print the sample and READ it — the false positives are in the strings, not the
  counts.** `grade` matching *upgrade*, and the TITLE label `Department Position Title`
  being claimed as an unreadable DEPARTMENT 31 times, were both invisible in the totals
  and obvious in the verbatim list.
- ⚠ **`perl -0pi -e` turns `\b` in a replacement into a literal BACKSPACE byte.** It
  silently made every word-boundary match fail. Use the Edit tool for regex bodies.
- **A rising score is a question too.** Three separate defects this project made scores go
  *up*: invented sections, compressed duty lists, dropped point-factor content.
- 🔴 **A SAMPLE IS NOT EVIDENCE ABOUT A COHORT, AND THAT IS HOW A FIX GETS REPORTED AS
  LANDED WHEN IT DID NOT.** HR-209 measured duty-frequency retention over the five largest
  CUPE clusters and reported it rising 27.8% → 43.8%. Over all 649 it was **24.1% —
  *below* its own stated "before"**. The sample was not wrong about those five clusters; it
  was never evidence about the rest. `make bank-audit` exists to make the cohort answer
  cheap enough that nobody reaches for a sample again. **Quote the cohort or say
  "sampled".**
- **Measure before patching, even when the patch is one line.** The frequency restore looks
  like moving one call out of a branch. Measuring first showed the model reorders duties so
  heavily that both obvious matching rules would attach a **wrong** frequency to a field
  the point-factor evaluation reads — a worse outcome than the bug. Twice this session a
  confident one-line fix was refuted before it shipped: that one, and a whitespace
  hypothesis about WJQ headings that `_clean` already handled. **The near-miss is the
  useful part; write it down where the next person will look.**
- **Verify state against the remote before trusting any doc.** `gh pr list` costs seconds;
  a handoff that records intent as outcome is worse than one merely out of date.
- **A term list is a hypothesis, and it fails differently every time you rewrite it.**
  Four failures now, same list: it missed the **engineers** (it encoded "IT = desktop
  support"), then nearly missed the **analysts** (they write about processes, not
  technologies), then missed the **leadership** entirely (a Senior Director's duties carry
  no technology nouns at all), and separately it cannot see anyone whose JD simply does not
  describe the work in those words. **Validate every functional definition against a
  known-good seed, and let it fail.** Then assume the next rewrite fails somewhere new.
- 🔴 **Internal consistency is not corroboration — it is what hides the error.** Five
  numbers and names in the planning docs were wrong this session (8→20 ITP-titled roles,
  368→469 documents, the unreproducible "1,420 → 166", "Practitioner"→"Professional",
  214→79 as the real HR ask). Every one was consistent across two to four documents, and
  that is precisely why none had been caught: they all derived from a single unchecked
  source, so agreement between them was a **correlated** failure, not evidence. **Only the
  archive is a second opinion.**
- **Ask what the AUDIENCE will look for, not only what the system computes.** The IT
  collection was correct and complete on its own terms, and would still have failed in
  front of ITS directors: it lists roles SFU *classifies* as IT, while a director looks for
  their own department — 45 of their staff were surfaced nowhere. No test could have caught
  that, because nothing was broken. The question "what will they scan for first?" caught it.
- **Match on word boundaries, never substrings.** `lan` as a substring matched 1,568 of
  2,493 roles — *plan*, *planning*, *Langara* — and 63% is not obviously absurd when you
  are expecting "bigger than you think". A wrong sweep looks exactly like a finding.
- **A number derived from a wrong number can still be right — and that hides the error.**
  The IT plan quoted 368 ITP documents; the truth is 469. The 45 roles and 32 approvable it
  derived were correct, because they came from the right query and only the document count
  was mis-transcribed. **Re-derive a headline number before saying it out loud**, and keep
  the query next to it.
- 🔴 **A filter must publish what it CANNOT SEE, or it is unfalsifiable.** The IT
  collection defined membership by a code present on 35% of the archive and reported the
  result as the whole function — 45 roles against a true ~211. Nothing on the page let a
  reader tell a small set from a blind filter. **Report three numbers: matched, not
  matched, and could-not-evaluate.** ⚠ And note the trap: validating against a seed drawn
  from the same 35% scored 98% recall while missing two-thirds of the population.
- 🔴 **A PLACEHOLDER is not a null, and a null check will not find it.** The parser writes
  `Untitled Position` when it finds no title, so `title <> ''` reports **100% title
  coverage** — while 2,050 of 14,522 documents (14%) have no real title, 1,395 of them
  already inside drafts. That false all-clear was produced during the very investigation
  that then found it. **Check for the sentinel the writer uses, not for emptiness.**
- 🔴 **One aggregate can hide a real gap inside an expected one.** "3,653 de-duplicated"
  is a plausible, comfortable sentence. Split into its buckets it is 1,900 genuine
  near-duplicates, 549 duplicates of each other, and **1,204 documents with no duplicate
  link at all that nobody has explained** — 8% of the archive, invisible for as long as it
  was reported as one number. **Report the buckets, never the total, when the total is a
  difference.**
- **`make gates` is not the whole gate.** The HR-register drift check runs only in CI, so a
  green local suite said nothing about it and `a65e224` failed on a stale generated file.
  **Run `make register` whenever the register changes**; know which checks live only in CI.
- **Use the project's own formatter, not a similar one.** `ruff format` reformatted 29
  unrelated files in a style `black` — the actual gate — then rejected. And an
  auto-rewrapper for long lines mangled docstrings into orphan fragments. Both had to be
  reverted, and the second cost more than fixing 33 lines by hand would have.
- 🔴 **A PROBE AND THE THING IT AUDITS MUST ANSWER THE SAME QUESTION — and the way to
  check is to make the probe REPRODUCE the audited number.** The field audit read whole
  documents; the parser reads only the identification block. So it kept finding the WJQ
  cover page's readable `Department Name:`, which the parser never sees, and reported a
  726-document READ FAILURE. Re-scoped, `readable` (2,956) lands on `parser_has` (2,958)
  and the real defect is ONE unregistered label, `Department Name/Section`, on ~667.
  **The wrong diagnosis survived three probe fixes and a full write-up** because every
  number in it was internally consistent. `readable ≈ parser_has` was the check that
  would have caught it on day one, and it costs one query. Third time this project has
  been bitten by a probe scoped differently from the code it audits (P3a's first fix,
  the employee-group token scan, this).
- 🔴 **CHECK THE BANK, NOT THE COUNTER.** A run's counters report what the RUN DID; the
  Bank holds what is TRUE. They are not the same reading and they drift apart silently.
  The rewrite pass printed `refreshed=95`, and the Bank had gained prose on **84** — the
  other 11 rewrites had failed, kept their deterministic draft, and were still counted as
  refreshed. A progress line's `failures=` counted CLUSTER failures, not rewrite failures,
  so "0 failures" was reported four times while 11 were accumulating. **The counter was
  not lying; it was answering a different question.** Query the Bank with the code's own
  predicate (`draft_has_rewritten_prose`) and compare before/after — that is the receipt
  against the balance, and only the balance is money.
- **A watcher must match the signal, not a substring of the output.** A completion check
  looking for "passed" fired on ruff's *"All checks passed!"* and reported a test result
  that had not happened yet. Same shape as believing a zero.
- **In a REVIEW queue, over-inclusion is cheap and under-inclusion is not.** A wrong
  candidate costs one "no" in the room; a missing one costs the reviewer's confidence in
  the whole list. Bias a worklist wide — and only a worklist, never a membership rule.
- 🔴 **A one-directional guard is decoration.** The template-routing check asked only "is
  a CUPE document behind a non-CUPE draft?" and stayed green while the inverse — drafts
  claiming CUPE over documents that are not — accumulated. **Agreement in the direction
  you tested says nothing about the other.** Assert both ways, or do not claim the
  property is pinned.
- 🔴 **A field can have two provenances and admit to neither.** `employee_group` was READ
  from the text for APSA/APEX/POLY and SET by routing for CUPE — one column, two meanings,
  nothing recording which. That is what let a passing mention ("supervises CUPE staff")
  become a bargaining unit. **When a value can arrive two ways, the difference is data,
  not a footnote.**
- **A CONTROL is what tells a finding from a broken probe.** A token scan "proved" 92% of
  ungrouped documents name no group — and its control scored 49%, which should have read
  as *the probe cannot see groups*. Splitting the control by group explained it exactly
  (100% for the read-from-text groups, 2.5% for the routed one) and only then was the
  finding trustworthy. **Run the control before believing the result.**
- **Check the source, not the database, when the database is the thing in question.** Both
  employee-group defects were invisible in `parsed_jds` and obvious in the archive files.
- **EVERY CLAIM ABOUT THE ARCHIVE MUST BE CHECKED AGAINST THE ARCHIVE.** A sample of the
  newest files is not a sample of the corpus. This rule has caught the Phase 0 census, two
  coders, a reviewer *and* the orchestrator.

---


---

## ▶ AUTHORITATIVE REFERENCES

| what | where |
|---|---|
| 🥇 **Live counts — the system itself** | `/jd-bank/ui/funnel` |
| **Everything we have measured** | [`docs/FINDINGS.md`](docs/FINDINGS.md) |
| **What we do next** | [`docs/plan.md`](docs/plan.md) |
| Project invariants | [`CLAUDE.md`](CLAUDE.md) |
| Onboarding, traps, `PARSER_VERSION` | [`DEVELOPER_GUIDE_1.md`](DEVELOPER_GUIDE_1.md) |
| Operating the system | [`docs/OPERATOR-GUIDE.md`](docs/OPERATOR-GUIDE.md) |
| What HR must decide | [`docs/decisions/HR-DECISION-MATRIX.md`](docs/decisions/HR-DECISION-MATRIX.md) |
| Every registered default (the file's own header is the count of record) | [`docs/decisions/HR-DECISION-REGISTER.md`](docs/decisions/HR-DECISION-REGISTER.md) |
| Archive baseline | [`docs/baseline/README.md`](docs/baseline/README.md) |
| Portable harness lessons | [`docs/HARNESS_LESSONS.md`](docs/HARNESS_LESSONS.md) |
| The re-evaluation that reset priorities | [`docs/STATUS-2026-08-24.md`](docs/STATUS-2026-08-24.md) |
| Build record + full working for each finding | [`docs/archive/`](docs/archive/) |

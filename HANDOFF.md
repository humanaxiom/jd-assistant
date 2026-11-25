# JD Bank — Session Handoff

🥇 **Read [`CURRENT.md`](CURRENT.md) first.** It says where every fact lives and how to check
it. This page is **state, open work and traps, forward-looking only.** For the story of how
the project got here, read [`docs/ORAL-HISTORY.md`](docs/ORAL-HISTORY.md). Earlier handoffs
are kept verbatim in [`docs/archive/`](docs/archive/); the one this page replaced is
[`HANDOFF-ARCHIVE-2026-08-29-to-11-20.md`](docs/archive/HANDOFF-ARCHIVE-2026-08-29-to-11-20.md).

⚠ **Verify before trusting.** `git fetch && gh pr list`, `docker ps`, the funnel and
`make smoke` answer in minutes. A handoff that records intent as outcome is worse than one
that is merely out of date.

---

## ▶ START HERE: state at 2026-11-24

**Three things are in motion:**
- **HR testers are on the live Bank** (unchanged since 2026-11-20).
- **The v9 Bank is being fully redrafted** on `aria-gb10-2`, and has been since 2026-11-21.
  It is a one-shot job that nothing restarts.
- **A VPFA spinoff is planned**, to be built by a colleague or a second account:
  [`docs/plans/VPFA-SPINOFF-PLAN.md`](docs/plans/VPFA-SPINOFF-PLAN.md), with a policy/risk
  brief in [`VPFA-SPINOFF-BRIEF.md`](docs/plans/VPFA-SPINOFF-BRIEF.md). It needs owner
  decisions D1–D7 before Phase 0.

| | checked 2026-11-24 |
|---|---|
| `main` | `7430859`, no open PRs |
| `bank/v9` | `f0b207c` (#228), 60 commits ahead of `main` and 9 behind |
| **v9 drafting pass** | container `jd-bank-v9-fullpass-v11`, **running with `--resume` since 2026-11-22T14:16:35Z**. 1,625 of 2,260 clusters at 2026-11-24 18:37Z, 0 failed rewrites or audits **in the Bank**, ~150 s per cluster, so it should finish around **2026-11-25 20:00 UTC**. Progress: `docker logs jd-bank-v9-fullpass-v11 2>&1 \| grep 'clusters \|' \| tail -1`. Start times and interruptions: `docs/canonical/v11-fullpass-2026-11-20.log` in the v9 checkout |
| inference host | `aria-gb10-2`, Ollama 0.21.2, `gpt-oss:120b` at a **32,768** window and fully in GPU memory. Both were wrong until 2026-11-21 and both fail silently; check `/api/ps` before any model work (trap below) |
| live Bank | `C:\repos\JD-Assistant`, compose project `jd-bank`, ports 25xxx, **CAS on**. Deployed with `launch.ps1` after #224; the running API serves the merged code |
| parser | `jd_segmenter_v8` on `main` (`grep '^PARSER_VERSION' core/src/jd_core/parser/segmenter.py`) |
| `make smoke` on deployed `main` | **GREEN, 40 passed, 1 skipped** (the skip is the query-reading check, off by design). Shipping is open |
| testers | sign in with SFU CAS and get the **author** role: search, read, draft, export, download the CRF. **Submit** persists a draft that cannot be deleted |
| feedback | the "Report a problem with this page" link in every footer (`FEEDBACK_EMAIL`, set in `.env`) |
| backup before testing | `C:\repos\jd-bank-backups\harness-20261119-pre-uat.dump` (+ `.sha256`, `.fingerprint.txt`), a full `-Fc` dump; restore rehearsed into an empty database |

### What shipped on 2026-11-20

| PR | what testers get |
|---|---|
| #219 | **Compensation Requisition Form** (K3): download from a role or the Builder, with request type A–E, one position, and the requester as contact. Filename position reader (HR-325–331). Query reading (I3) built, **switched off** |
| #220 | The source JD page shows the position(s) from the **file name** beside the one typed in the document, and the file name's title when the text has none (HR-338) |
| #221 | The IT collection page loads in 0.7 s instead of 25.6 s, with identical numbers |
| #222 | Plain language on every tester page, guarded by a smoke check that fails on internal ids, repository paths and pipeline words |
| #223 | **Position-number search** (`61`, `00000061`, `Pos 61`) in the Library and the Builder (HR-339) |
| #224 | Review queue: 100 per page, title filter, "N archive files" instead of raw ids, scores to one decimal |

**HR register:** the next free id is **HR-342**. HR-340 (#227) and HR-341 (#228) are on
`bank/v9`; `main` tops out at HR-339. Re-check before you take one:
`grep -oE '^  - id: HR-[0-9]+' core/src/jd_core/rules/decision_register.yaml | sort -t- -k2 -n | tail -1`,
on `main` **and** on `origin/bank/v9`.

---

## ▶ WHAT IS OPEN, in order

1. **Support the HR testers.** Read what comes in through the feedback link, reproduce it on
   the live Bank, and fix it through ordinary PRs. Each fix gets its own live smoke check,
   the way #219–#224 did. Testers hold only `author`. The review queue is reviewer-only and
   its paging was not tester-driven.
2. **External access: deferred by the owner on 2026-11-20 ("will deal with external access
   later").** Do not start it unprompted. What is waiting:
   - `sfuai.ca:7000` is plain HTTP carrying CAS cookies (BGL-1, no TLS anywhere in the
     path);
   - the box has two LAN addresses: **`192.168.1.80`** (wired, reconnected by the owner on
     2026-11-20) and `192.168.1.73`. `ALLOWED_SERVICE_ORIGINS` lists `.80` and **not**
     `.73`, so CAS sign-in via `.73` falls back. The gateway's `:7000` forward targets
     `.80:25800` (NETWORK-SETUP §6), which answers again. Verify from a genuinely external
     network **and** in the app log; the gateway does not hairpin;
   - the network posture for the data-centre boxes ([`docs/NETWORK-SETUP.md`](docs/NETWORK-SETUP.md)).
3. **The v9 Bank: finish the pass, then ship it.** It is a separate Bank: checkout
   `C:\repos\JD-Assistant-v9`, branch `bank/v9`, project `jd-bank-v9`, ports 26xxx, parser
   **v11**, prompt **v5**, P6 failure reasons, and the HR-341 context-window guard. #226,
   #227 and #228 are merged into `bank/v9`. The `dev-anonymous` role was let go with the
   rebuild (owner, 2026-11-20); its record is in
   `C:\repos\jd-bank-backups\v9-pre-v11-rebuild-2026-11-20.dump`.

   **Done 2026-11-20/21:** wiped and rebuilt v9 at parser v11, up to clustering, following
   `docs/plans/PARSER-V9-LISTS-AND-CAPS.md` §10. The artefacts are on `bank/v9` at
   `55b1c8a`. ⚠ `make near-dup` needs `JD_ARCHIVE_PATH=C:/repos/hris/fixtures/SFU_JDs`; without it
   it writes 0 edges and exits 0. The runbook says so now.

   **Next, in order:**
   1. **Let the pass finish.** If it dies (exit code 255 means the box rebooted):
      - read its last checkpoint line;
      - check the Bank (`select count(*) from canonical_jds`);
      - check `/api/ps` (window ≥ 32,768 **and** `size_vram == size`);
      - from the v9 checkout:
        `docker rm jd-bank-v9-fullpass-v11 && docker compose run -d --name jd-bank-v9-fullpass-v11 canonical python -u -m src.jd_bank.canonical --resume`.

      `--resume` is right here, because this Bank held no prose before this pass. Record
      every restart in `docs/canonical/v11-fullpass-2026-11-20.log`.
   2. **Check the Bank, not the progress line.** Count drafts whose `change_log` has
      `pipeline.rewrite_failed = true`, `audit_failed = true` or `rewrite_error` set. Look at
      the empty ones: 7 at 1,625, all from source files the parser could not read
      ("Untitled Position").
   3. Run `make embed-roles`, `make bank-audit` and `make smoke`, **on v9**. Commit the
      pass's `docs/canonical/summary.json` and its log on `bank/v9`.
   4. Merge `main` into `bank/v9`, then run the duplicate-id check and
      `make register-check`.
   5. Ship through ordinary PRs (V4). Migration 0008 locks the live `parsed_jds` for about
      10 s, and the live Bank then needs its own re-parse and producer pass, scheduled
      outside tester hours, **after** the `/api/ps` check.
4. **Optional follow-ups from the v9 work.** None is started.
   - **Register the rewrite client's request timeout and stop the SDK's hidden retries.**
     Today the SDK's 600 s default and up to nine attempts are unregistered. That is how a
     CPU-bound host produced 80 minutes of nothing with no error. Core PR into `bank/v9`;
     the next free id is HR-342.
   - **Make `make near-dup` fail when it signs nothing.** The same silent-zero class as
     the archive-path bug.
   - **Unknown, worth knowing:** whether the live Bank's drafts were written while the host
     cut prompts at 4,096 tokens. Drafts do not record token counts, so the Bank cannot
     answer. Comparing a sample of live drafts against v9's re-drafts of the same clusters
     would.
5. **The VPFA spinoff.**
   - **The plan:** [`docs/plans/VPFA-SPINOFF-PLAN.md`](docs/plans/VPFA-SPINOFF-PLAN.md).
   - **Briefing for the owner's meeting** with the VPFA Senior Policy Advisor and the Chief
     Risk & Safety Officer:
     [`docs/plans/VPFA-SPINOFF-BRIEF.md`](docs/plans/VPFA-SPINOFF-BRIEF.md).
   - **Ruled 2026-11-24** (plan §0):
     - the whole Bank, VPFA by default;
     - everything under VPFA, Finance included;
     - Residence and Housing and Bookstore are Campus Services;
     - minimal review, with reviewers Denise (VPFA office), Galib (Chief SRS or designate)
       and two TBD;
     - **VPFA proxies for HR.**
   - **Waiting on:** D5 (hosting), D6 (repo), the Campus Services neighbours (plan §2), the
     two other reviewers, and a named technical custodian.
   - **The only work it puts in THIS repo:** `make bank-snapshot` (plan §5.1), a core PR
     that writes a versioned, hashed export of the Bank.
6. **Re-cut the offline bundle before any fresh-box install.** The owner reported it done
   on 2026-11-20, but `dist/jd-bank-bundle` (the default output) still dated from
   2026-08-28 at that check. Confirm where the new one went before relying on it. Since then `core/requirements.txt` has changed (#213, 2026-10-19) and
   alembic migration `0007_title_trigram_indexes` has been added (#215). `make deploy-check`
   proves the bundle *would be* complete, not that the one on disk is current. Run
   `.\build.ps1 -Bundle` with the stack up.
7. **Unbuilt tracks**, each designed and waiting:
   - **J3**, the CUPE Part II questionnaire;
   - **J5**, the re-evaluation package, which needs K3 (done) and Q5;
   - **K1**, the PeopleSoft position import, on hold because owner Q3 left the export TBD.
     The filename position is the join key it will use;
   - **Track G**, upload a JD into the Builder;
   - **Track F**, JD currency after publishing;
   - **Track H**, combine roles into a new JD.

   Order and gates: [`docs/plan.md`](docs/plan.md).
8. **Decisions that are not ours.** Don't work around them; keep them visible.
   - the VPFA spinoff's D5 and D6, the two other reviewers, and the Campus Services
     neighbours (plan §2);
   - **HR-105**, the territorial acknowledgement wording. Exports spell it without its
     special characters, and testers are told;
   - **Q8**, which model reads queries. Switching I3 on makes smoke place real model calls,
     so shipping then needs the GPU free;
   - Q2 and Q4–Q7 and Q10 from the tracks plan;
   - the stranded JDFN drafts, [`FINDINGS.md`](docs/FINDINGS.md) §12: delete, re-attach or
     keep;
   - six departments not yet assigned to a unit, Human Resources the largest;
   - the ITP/S classification, which sits with the CIO and VPFA;
   - HR-296/297 (WJQ equivalency) and HR-046/HR-284.

   The register's own header is the count of what HR still owes.
9. **Smaller follow-ups:**
   - a newly approved role is missing from Builder search until `make embed-roles` runs
     (deliberately not wired into approve);
   - **duty frequency** needs an *exclusive* matcher, not a threshold change (FINDINGS §10f);
   - the CRF page could also offer the Builder's current draft, which J5 needs;
   - "HR-175" is shown on the **reviewer's** draft page **on purpose**: it points HR at the
     decision behind the education and experience bar.

---

## ▶ TRAPS THAT STILL BITE

**Access and posture**
- **CAS is a box-local `.env` value** (gitignored); the compose default is off. **CAS off
  plus `0.0.0.0` ports means anyone on the LAN or tailnet is admin.** That was the
  2026-11-19 incident. Before handing the box over, `curl` the LAN IP's `/jd-bank/ui/queue`:
  you must get a 303 to login.
- With CAS on, `curl` against any UI route returns a 303. Verify through the suite, or with
  an in-container probe (`docker exec -i jd-bank-api-1 python -I -`).
- **Read `ALLOWED_SERVICE_ORIGINS` off the box, never off a page.** Scheme, host and port
  each matter; an unlisted spelling lands the user on a timeout holding a valid ticket.

**Running and deploying**
- 🔴 **The inference host fails silently in two ways. Check both before any model pass.**
  `curl -s http://aria-gb10-2:11434/api/ps`:
  - **`context_length` must be ≥ 32,768.** At 4,096, prompts were cut with no error. The
    producer now refuses below it (HR-341).
  - **`size_vram` must equal `size`.** `0` means the model is running on CPU. It still
    answers, but every rewrite then hits the 600 s client timeout, and nothing catches
    that yet.

  If no model is loaded, the list is empty; one tiny request loads it. **Never "test" the
  host with big prompts.** It is shared, slow requests keep running after you abandon them,
  and they block everyone.
- **This box reboots on its own** (2026-11-22, mid-pass). The stack comes back; one-shot
  producer runs do not (exit code 255). Restart with the right flag (item 3.1 above).
- **The dev API does not hot-reload** on a Windows bind mount. `launch.ps1` force-recreates
  api and worker. After a deploy, check that
  `docker logs -t jd-bank-api-1 | grep "Started server"` is newer than the change. In-process
  smoke cannot tell you this.
- **Long producer runs are one-shot `docker compose run` jobs, and nothing restarts them.**
  Record T0. Resume with `--refreshed-since <T0>` when the Bank already held prose, and
  with `--resume` only when it did not. FINDINGS and the archived handoff explain the
  difference, which once nearly turned a re-baseline into a 40-minute no-op.
- **Background-task notifications say "exit code 0" on red runs.** Read the output
  (`GATES_RC=`, `SMOKE_RC=`), never the status.
- `make bank-audit` exits 2 whenever any carry-through is below 100%. That is the gate
  firing, not a crash.
- **`pg_restore --data-only` wipes the Bank and exits 0.** Restore a full `-Fc` dump into an
  **empty** database. Back up Postgres only; Neo4j is a derived index, rebuilt by
  `make embed` / `make embed-roles` at no cost when nothing changed.
- **The port varies** (`JD_API_PORT`). Ask `docker port jd-bank-api-1`, never a document.
- Other projects share this box. Stray `postgres`/`neo4j` containers belong to
  `recruiter-assistant`'s testcontainers. Codex runs `jd-bank-codex-dev` on 27xxx, which is
  not ours.

**Git and PRs**
- **Every feature PR appends a test to `core/tests/live/test_smoke_live_bank.py`**, and
  #223/#224 also regenerate `docs/operator-guide.html`, so parallel PRs conflict there.
  After each merge, rebase the rest, keep both tests, and re-run gates **and** smoke before
  pushing.
- **The owner merges.** Auto mode blocks `gh pr merge`, and the standing rule is that the
  assistant does not merge.
- **Squash merges make the branch look unmerged**, and merging `main` back can silently
  **duplicate register entries**. After any merge touching `decision_register.yaml`, run
  `grep -oE "^  - id: HR-[0-9]+" core/src/jd_core/rules/decision_register.yaml | sort | uniq -d`
  (it must print nothing), then `make register-check`.
- **Stacked PRs:** retarget the child before merging the parent. `--delete-branch` on a
  parent **closes** the child for good.
- **The v9 checkout shares its git record with Codex's copy** (`C:\repos\GH-Versions\…`).
  Run `git -C C:/repos/JD-Assistant-v9 branch --show-current` before every v9 action; it
  must say `bank/v9`. Leave Codex's folder, branch, stack and `.git/worktrees` alone.
  Do not create a second v9 checkout.
- Worktrees under `.claude/worktrees/agent-*` and two detached scratchpad worktrees belong
  to **other sessions**. Do not remove them.

**Code and tooling**
- Format with **black**, never `ruff format`, which rewrites unrelated files.
- The layering guard fails on the literal text `src.jd_bank` anywhere under
  `src/jd_core/rules/`, **comments included**.
- A Jinja phrase split across two lines breaks a test asserting that phrase. Keep asserted
  sentences on one line.
- `make register` under a fresh compose project once wrote image-build output into the
  register. Build first, then grep the file before committing.
- In Git Bash, prefix commands that pass container paths with `MSYS_NO_PATHCONV=1`, or MSYS
  creates a junk `core/C:/` directory.
- The `./docs/canonical` bind mount lags on Windows. A file the container just wrote may
  take seconds to appear.

---

## ▶ IF YOU ARE STARTING COLD

```bash
git fetch && git status -sb && gh pr list           # never trust a table for this
docker ps --format '{{.Names}}\t{{.Status}}' | grep jd-bank
docker ps --filter "name=canonical"                 # a producer pass running? do not start another
.\launch.ps1                                        # if the stack is down or stale
make smoke                                          # the only evidence about the live system
```

Then open `/jd-bank/ui/funnel` for the counts and run `make bank-audit` for content
fidelity. Three scripts, one job each: `build.ps1` → `launch.ps1` → `teardown.ps1`. The
offline path is `deploy/bundle.ps1` + `deploy/install.ps1` ([`deploy/README.md`](deploy/README.md)).
A second Bank beside the live one: `deploy/README.md` § *Running a second Bank*, and
`make bank-target` tells you which Bank a checkout acts on.

### State that is not in git

| | |
|---|---|
| `.env` (gitignored) | `CAS_ENABLED`, `BOOTSTRAP_ADMINS` (who gets admin on first sign-in), `ALLOWED_SERVICE_ORIGINS`, `CAS_SERVICE_BASE_URL`, `FEEDBACK_EMAIL`. **Never print the values.** A fresh clone comes up CAS-off with no admin |
| the archive | `C:\repos\hris\fixtures\SFU_JDs`, read-only and external. Pass `JD_ARCHIVE_PATH=` explicitly; the default `./archive` is empty and the runners refuse it |
| backups | `C:\repos\jd-bank-backups\` (the 2026-11-19 pre-testing dump) and the older `C:\Users\adam\jd-bank-backups\` |
| inference | Ollama on **`aria-gb10-2`**: every embedding and model pass. Nothing in this repo provisions it. Its context window (`OLLAMA_CONTEXT_LENGTH=32768`) and GPU placement are host settings; check `/api/ps` |
| assistant memory | the owner's local Claude Code profile holds working notes. **Anything a successor needs is in this repo**: CLAUDE.md, this file, `docs/ORAL-HISTORY.md` and the VPFA plan's §9. Nothing else has to be recovered from it |

---

### If you are taking this project over

You need, in this order:
1. **access:** GitHub on this repo; the dev box (or a box built with `deploy/README.md`); a
   CAS-registered origin; the inference host on 11434/tcp;
2. **the box-local `.env`** from the owner, handed over directly, never through git or
   chat;
3. **reading:** CURRENT.md, then this file, then `docs/ORAL-HISTORY.md`, then CLAUDE.md;
4. **proof the system works:** run `make smoke` yourself, before anything else.

If you are building the **VPFA spinoff** rather than running this Bank, start from
[`docs/plans/VPFA-SPINOFF-PLAN.md`](docs/plans/VPFA-SPINOFF-PLAN.md) §8; you need read
access here, not the box.

## ▶ HOW WE WORK

- **Directive #0: ship only after a full end-to-end smoke test.** "Ship" means merge or
  deploy, and red blocks it even when your change did not cause the red. If you cannot make
  it green, stop, leave the work on a branch with its evidence, and say why.
- **Directive #1:** tested (failing test first, the guard broken once), deployable through
  the scripts by a person with no assistant, discoverable in the UI, `make deploy-check`
  green, and `make smoke` green **covering the change**.
- **Docker-only.** `make gates` (full) or `make gates-fast`. Pick by what the diff touches:
  anything Postgres- or Neo4j-shaped needs the full suite.
- **Rulebook as data.** Every non-trivial knob goes in YAML and is registered in the same
  PR. Run `make register` and commit the regenerated register; CI's drift gate is not part
  of `make gates`. If a default looks wrong, register it `open`; never patch it quietly.
- **Operator guide.** Edit `docs/OPERATOR-GUIDE.md`, then `make guide`, and commit both
  files. `make guide-check` fails on drift.
- **What needs a PR:** `CLAUDE.md` § *Change workflow*. In short: `core/`, this file,
  `docs/plan.md`, `docs/decisions/` and build files go by PR; most other docs go straight
  to `main`.

## ▶ AUTHORITATIVE REFERENCES

| what | where |
|---|---|
| 🥇 live counts | `/jd-bank/ui/funnel` |
| where every fact lives | [`CURRENT.md`](CURRENT.md) |
| what we do next | [`docs/plan.md`](docs/plan.md) |
| how we got here | [`docs/ORAL-HISTORY.md`](docs/ORAL-HISTORY.md) |
| everything measured | [`docs/FINDINGS.md`](docs/FINDINGS.md) · [`docs/audit/`](docs/audit/) |
| invariants and change workflow | [`CLAUDE.md`](CLAUDE.md) |
| onboarding and `PARSER_VERSION` | [`DEVELOPER_GUIDE_1.md`](DEVELOPER_GUIDE_1.md) |
| using and operating the system (in-app at 📖 Guide) | [`docs/OPERATOR-GUIDE.md`](docs/OPERATOR-GUIDE.md) |
| what HR must decide | [`docs/decisions/HR-DECISION-MATRIX.md`](docs/decisions/HR-DECISION-MATRIX.md) · [register](docs/decisions/HR-DECISION-REGISTER.md) (its header is the count of record) |
| deploying offline / a second Bank | [`deploy/README.md`](deploy/README.md) |
| network admins | [`docs/NETWORK-SETUP.md`](docs/NETWORK-SETUP.md) |
| the build record and earlier handoffs | [`docs/archive/`](docs/archive/) |

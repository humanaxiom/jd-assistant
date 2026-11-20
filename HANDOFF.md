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

## ▶ START HERE: state at 2026-11-20

**HR testers are using the live Bank.** Everything from the 2026-11-19 readiness review
([`docs/audit/2026-11-19-uat-readiness/`](docs/audit/2026-11-19-uat-readiness/)) is merged
and deployed.

| | checked 2026-11-20 |
|---|---|
| `main` | `6b332a4`, no open PRs |
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

**HR register:** the next free id is **HR-340**. `main` tops out at HR-339, and `bank/v9`
holds HR-267–308 and HR-324, below it. Re-check before you take one:
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
3. **The v9 Bank: finish it, then ship it.** It is a separate Bank: checkout
   `C:\repos\JD-Assistant-v9`, branch `bank/v9`, project `jd-bank-v9`, ports 26xxx, parser
   v10, hardened rewrite. As **measured 2026-11-19**:
   - the full pass finished all 2,258 clusters;
   - **641 drafts are `rewrite_failed`**. They all failed inside one window on 2026-11-05,
     which looks like the inference host going away;
   - one role was **published by `dev-anonymous`** while CAS was off. What to do with it is
     the owner's call;
   - the v9 **API container is stopped**. `docker start` would re-expose it with CAS off,
     so bind it to loopback first.

   🔴 **Blocked first on an owner ruling (found 2026-11-20): the parser's `_MAX_BULLET =
   400`.** It is an unregistered constant, also on `main` alongside a 20-item count cap
   (`_MAX_BULLETS`). It cuts decision-making, problem-solving and contact items at 400
   characters when the archive is read: **4,668 v9 parses** carry a cut item (4,226
   decision-making items sit at exactly 400). It is also why **v9 smoke is red** (one role's
   contact is cut on export and re-read). It is the same family as the caps removed on
   2026-10-29. "Remove it" means parser v11 and a v9 re-parse, which regenerates clusters,
   so **rule before the retry**, or the 26 h are wasted. Evidence: PR #226.

   Next, in order (after that ruling):
   1. Merge **P6** (PR #226 into `bank/v9`, open). Then retry the 641 with
      `CANONICAL_ARGS="--resume"`. That is correct *here*, because the v9
      Bank was rebuilt `--no-llm`, so no prose predates the pass. A `--refreshed-since`
      run would now skip everything.
   2. The retry takes about 26 h on `aria-gb10-2`. Do not run it while testers are on, and
      do not run it alongside another producer pass.
   3. Then run `make embed-roles`, `make bank-audit` and `make smoke`, **on v9**.
   4. Then merge `main` into `bank/v9`. It is 56 ahead and 7 behind; run the duplicate-id
      check and `make register-check`.
   5. Then ship through ordinary PRs. Migration 0008 locks the live `parsed_jds` for about
      10 s, and the live Bank then needs its own re-parse and producer pass, scheduled
      deliberately.
4. **P6: rewrite failures record their reason. Built 2026-11-20, PR #226 into `bank/v9`.**
   It records `rewrite_error` / `audit_error` on the draft, the exception type in the audit
   row and on stderr, and the failing field in the repair nudge. FINDINGS §13e **fix 3** (the
   prompt annotation) was left out on purpose: it changes the registered prompt version
   (HR-180), so the retried drafts would differ from the 1,616 that succeeded. That is
   the owner's call. `main` still swallows the reason (`runner.py:379`) until v9 ships (V4).
5. **Re-cut the offline bundle before any fresh-box install.** The owner reported it done
   on 2026-11-20, but `dist/jd-bank-bundle` (the default output) still dated from
   2026-08-28 at that check. Confirm where the new one went before relying on it. Since then `core/requirements.txt` has changed (#213, 2026-10-19) and
   alembic migration `0007_title_trigram_indexes` has been added (#215). `make deploy-check`
   proves the bundle *would be* complete, not that the one on disk is current. Run
   `.\build.ps1 -Bundle` with the stack up.
6. **Unbuilt tracks**, each designed and waiting:
   - **J3**, the CUPE Part II questionnaire;
   - **J5**, the re-evaluation package, which needs K3 (done) and Q5;
   - **K1**, the PeopleSoft position import, on hold because owner Q3 left the export TBD.
     The filename position is the join key it will use;
   - **Track G**, upload a JD into the Builder;
   - **Track F**, JD currency after publishing;
   - **Track H**, combine roles into a new JD.

   Order and gates: [`docs/plan.md`](docs/plan.md).
7. **Decisions that are not ours.** Don't work around them; keep them visible.
   - the v9 role published by `dev-anonymous`;
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
8. **Smaller follow-ups:**
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
| inference | Ollama on **`aria-gb10-2`**: every embedding and model pass. Nothing in this repo provisions it |

---

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

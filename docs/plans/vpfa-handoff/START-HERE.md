# VPFA JD Bank: start here

**The single instruction set for the VPFA spinoff.** Prepared 2026-11-24.

> ⚠ **WITHDRAWN 2026-11-25.** The instruction set now lives in the spinoff repo, `sfu-aria/Vpfa-jda`, at `docs/handoff/START-HERE.md` (revision 2: a full copy installed with `deploy/install.ps1`). What follows is revision 1, kept as the record.
>
> ⚠ **SUPERSEDED IN PART, 2026-11-25: being revised for ruling D8** ("bring everything in
> as is; only the dashboards are removed"). Do **not** follow A4 (snapshot export), A5 or
> B3's snapshot copy yet. The new data path is the parent's own offline bundle
> (`deploy/bundle.ps1` → `deploy/install.ps1`) plus the archive. See the plan, §5.0 and §6.1.

| part | where | who | when |
|---|---|---|---|
| **A** | **this box**, the parent JD Bank's dev box | the owner | when the v9 redraft finishes (expected around **2026-11-25 20:00 UTC**) |
| **T** | between the two machines | the owner | right after A |
| **B** | **the new machine**, with the Claude **Team** account | whoever builds the spinoff | after T |

The design being built is in the parent repo: `docs/plans/VPFA-SPINOFF-PLAN.md`, the
engineering plan, and `docs/plans/VPFA-SPINOFF-BRIEF.md`, the policy and risk briefing.

### What ends up in the bundle

| path | what |
|---|---|
| `START-HERE.md` | this file |
| `parent/jd-assistant.bundle` | the parent project as a git bundle: full history, branches `main` and `bank/v9`. It is the reference you port from, and it holds the plan. Added by A5 |
| `snapshot/v9-<date>/` | the **v9 JD Bank snapshot**: every role and draft, every source-file record, every current parse, plus the funnel and unit counts, with `manifest.json` hashing each file. Added by A5 |
| `tools/export_snapshot.py` | the read-only exporter (A4); it becomes the parent's `make bank-snapshot` later |
| `tools/package.ps1` | puts a snapshot in the bundle, refreshes the git bundle, hashes everything, zips (A5) |
| `reference/hr/` | SFU HR source material: JD Toolkit, the 2024 APSA/APEX/Poly template, the Compensation Requisition Form, the Hay method, the reorganization forms |
| `SHA256SUMS` | a hash for every file. Written by A5 |

---

# Part A: on this box, once v9 has finished

All commands are PowerShell. The v9 Bank lives in `C:\repos\JD-Assistant-v9` (branch
`bank/v9`, compose project `jd-bank-v9`). The bundle folder is
`C:\repos\vpfa-handoff-bundle-2026-11-24`.

### A1. Is the pass finished?

```powershell
docker ps -a --filter name=jd-bank-v9-fullpass-v11 --format "{{.Status}}"
docker logs jd-bank-v9-fullpass-v11 2>&1 | Select-String 'clusters \|' | Select-Object -Last 1
```

| you see | meaning | do |
|---|---|---|
| `Up …` | still running | wait |
| `Exited (0)` and `2260/2260` (or the final total) | finished | go to A2 |
| `Exited (255)` | this box rebooted mid-pass | resume, below, then wait again |
| any other exit | it failed | read `docker logs jd-bank-v9-fullpass-v11`; do not package |

Resume after a reboot:
1. Check the host: `curl.exe -s http://aria-gb10-2:11434/api/ps` must show
   `context_length` ≥ 32768 **and** `size_vram` equal to `size`. `0` means the model is on
   CPU; fix the host first.
2. Then:

```powershell
cd C:\repos\JD-Assistant-v9
git branch --show-current            # must print bank/v9
docker rm jd-bank-v9-fullpass-v11
docker compose run -d --name jd-bank-v9-fullpass-v11 canonical python -u -m src.jd_bank.canonical --resume
```

### A2. Check the Bank, not the progress line

```powershell
docker exec jd-bank-v9-postgres-1 sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "
select count(*) as drafts,
       (select count(*) from clusters) as clusters,
       count(*) filter (where (change_log->''pipeline''->>''rewrite_failed'')::boolean) as rewrite_failed,
       count(*) filter (where (change_log->''pipeline''->>''audit_failed'')::boolean)   as audit_failed,
       count(*) filter (where length(content::text) < 1000)                              as empty
from canonical_jds"'
```

What good looks like:
- `drafts` equals `clusters`;
- `rewrite_failed` and `audit_failed` are 0, or small and explained (the reason is in each
  draft's `change_log.pipeline.rewrite_error`);
- `empty` is single digits, all from files the parser could not read ("Untitled
  Position").

Anything else: stop and look before packaging.

### A3. Verify v9 end to end

```powershell
cd C:\repos\JD-Assistant-v9
make bank-target      # must say it acts on the v9 Bank
make embed-roles      # role vectors for Builder search
make bank-audit       # exit 2 means a carry-through gate fired: read the report, it is not a crash
make smoke            # must be GREEN
```

**Do not package a Bank whose smoke is red.** The new project would inherit a state nobody
has verified.

### A4. Export the snapshot (read-only, about 2 minutes)

```powershell
cd C:\repos\JD-Assistant-v9
$sha  = git rev-parse HEAD
$name = "v9-" + (Get-Date -Format yyyy-MM-dd)
docker compose run --rm -T --no-deps `
  -v "C:/repos/vpfa-handoff-bundle-2026-11-24/tools:/x:ro" `
  -v "C:/repos/jd-bank-snapshots:/out" `
  api python /x/export_snapshot.py "/out/$name" "v9 (compose project jd-bank-v9)" $sha
```

- It prints the manifest. Every `rows` figure was read back from the file it wrote and
  matched against the database. A mismatch prints `REFUSED` and exits non-zero.
- It runs in a throwaway container with no published ports, so it never starts the v9 API.
- The snapshot lands in `C:\repos\jd-bank-snapshots\<name>`.

### A5. Package

```powershell
C:\repos\vpfa-handoff-bundle-2026-11-24\tools\package.ps1 -Snapshot "C:\repos\jd-bank-snapshots\$name"
```

It does four things:
- copies the snapshot into the bundle and re-checks it against its manifest;
- rebuilds the parent git bundle with the current `main` and `bank/v9`;
- writes `SHA256SUMS`;
- writes `C:\repos\vpfa-handoff-bundle-2026-11-24-<name>.zip` and its `.sha256`.

It prints the zip's size and checksum; write the checksum down.

---

# Part T: transfer to the new machine

The zip is SFU job-description content (about 60–90 MB). Move it only between
SFU-managed machines, and never through an open web server, a public share or chat.

### Option 1: USB drive (simplest)

1. Copy `vpfa-handoff-bundle-2026-11-24-<name>.zip` and its `.zip.sha256` to the drive.
2. On the new machine, copy both into `C:\vpfa\`.
3. Check the zip:

```powershell
cd C:\vpfa
(Get-FileHash -Algorithm SHA256 .\vpfa-handoff-bundle-2026-11-24-*.zip).Hash.ToLower()
Get-Content .\vpfa-handoff-bundle-2026-11-24-*.zip.sha256
```

The two hashes must be identical. Wipe the copy from the USB drive afterwards.

### Option 2: over the LAN with a temporary Windows share

On **this box**, in an **administrator** PowerShell, share one folder **read-only, to one
account**:

```powershell
New-Item -ItemType Directory -Force C:\vpfa-share | Out-Null
Copy-Item C:\repos\vpfa-handoff-bundle-2026-11-24-*.zip* C:\vpfa-share\
New-SmbShare -Name vpfa-handoff -Path C:\vpfa-share -ReadAccess "$env:COMPUTERNAME\<local-user>"
# or -ReadAccess "SFU\<user>" if both machines are on the domain
```

If the new machine cannot see it, allow **File and Printer Sharing** on the *Private*
network profile in Windows Defender Firewall.

On the **new machine**, using this box's LAN address (`192.168.1.80` on the wired LAN;
confirm with `ipconfig`):

```powershell
New-Item -ItemType Directory -Force C:\vpfa | Out-Null
Copy-Item \\192.168.1.80\vpfa-handoff\* C:\vpfa\      # prompts for the account named above
```

Check the hash as in Option 1. Then, **on this box, remove the share straight away**:

```powershell
Remove-SmbShare -Name vpfa-handoff -Force
Remove-Item -Recurse -Force C:\vpfa-share
```

---

# Part B: on the new machine

### B1. Prepare the machine (about 30 minutes)

Install:
- **Git**;
- **Docker Desktop** (Windows or macOS) or Docker Engine with compose (Linux);
- **Claude Code**, signed in with the **Team** account.

`gh`, the GitHub CLI, is optional.

The repo `sfu-aria/Vpfa-jda` will be **private**, so this machine needs a GitHub account
with access to it. Git for Windows asks you to sign in in the browser on the first clone.
With `gh`, run `gh auth login` once beforehand.

If this machine has never committed with git:

```powershell
git config --global user.name  "Your Name"
git config --global user.email "you@sfu.ca"
```

Check the inference host is reachable:

```powershell
curl.exe -s http://aria-gb10-2:11434/api/version
```

If nothing comes back, ask ITS to open `11434/tcp` to `aria-gb10-2`. Everything except
meaning-based search and the summary suggestion works without it.

### B2. Unpack and verify (5 minutes)

```powershell
cd C:\vpfa
Expand-Archive .\vpfa-handoff-bundle-2026-11-24-*.zip -DestinationPath .
Rename-Item .\vpfa-handoff-bundle-2026-11-24 handoff
cd handoff
Get-Content SHA256SUMS | ForEach-Object {
  if ($_ -match '^([0-9a-f]{64}) [ *](.+)$') {
    if ((Get-FileHash -Algorithm SHA256 $Matches[2]).Hash.ToLower() -ne $Matches[1]) { "BAD: $($Matches[2])" }
  } else { "UNREADABLE LINE: $_" }
}
"verify done"
```

Only `verify done` should print.

### B3. Lay out the workspace (5 minutes)

```powershell
cd C:\vpfa
git clone -b main handoff\parent\jd-assistant.bundle jd-assistant-parent    # -b main is required
git -C jd-assistant-parent branch bank/v9 origin/bank/v9                    # the code that made the snapshot
git clone https://github.com/sfu-aria/Vpfa-jda.git vpfa-jd-bank             # the new project, already seeded
cd vpfa-jd-bank
mkdir snapshot | Out-Null
Copy-Item -Recurse (Get-ChildItem ..\handoff\snapshot -Directory)[0].FullName snapshot\
git status                                                                  # must say "nothing to commit": snapshot\ is ignored
```

If `git status` lists anything under `snapshot\`, **stop**. The `.gitignore` is missing or
damaged, and the data must not be committed.

You now have:

```
C:\vpfa\
  handoff\               the bundle as received, kept unchanged
  jd-assistant-parent\   the parent project, a read-only reference (branches main and bank/v9)
  vpfa-jd-bank\          the new project: the seeded repo, plus snapshot\v9-<date>\ (git-ignored)
```

The seeded repo already holds the design (`docs/design/`, copied from the parent), this
file and its tools (`docs/handoff/`), a `README.md` and the `.gitignore`.

**Port from `bank/v9`**, not `main`: it is the code that produced the snapshot's data (parser
v11, prompt v5). Once the parent merges v9 into `main` (its plan item V4), the two are the
same.

### B4. Read before starting (about 1 hour)

In `C:\vpfa\jd-assistant-parent\`, in this order:
1. `docs/plans/VPFA-SPINOFF-PLAN.md`, all of it. **§0 holds the owner's rulings**, §5 the
   phases, §6 what to copy, §9 the lessons.
2. `docs/ORAL-HISTORY.md`: why the rules are what they are.
3. `CLAUDE.md`: the parent's invariants. The new project adopts most of them (plan §8.3).

### B5. Start Claude Code and hand it the kickoff prompt

```powershell
cd C:\vpfa\vpfa-jd-bank
claude
```

Paste this as the first message:

> You are building **VPFA JD Bank**, a focused spinoff of SFU's JD Bank, in this repo. It
> holds only documentation so far. Its design is fixed in `docs\design\VPFA-SPINOFF-PLAN.md`
> (a copy; the parent's `docs\plans\` is the source of record): read it in full first, then
> `docs\design\PARENT-ORAL-HISTORY.md` and `..\jd-assistant-parent\CLAUDE.md`. The parent is a **read-only reference**. Port from its
> **`bank/v9`** branch, which produced our data; never edit the parent.
>
> **Owner rulings (plan §0):**
> - import the whole Bank and show VPFA by default;
> - everything under VPFA is in scope, Finance included;
> - Campus Services includes Residence and Housing and Bookstore;
> - a minimal review step, with VPFA reviewers;
> - VPFA acts as HR's proxy for the rulebook register.
>
> **The repo (D6):** `https://github.com/sfu-aria/Vpfa-jda`, which must stay **private**.
>
> **Still open, so ask me:** hosting (D5), the remaining Campus Services departments
> (plan §2), and two of the four reviewers.
>
> **The data:** `snapshot\v9-<date>\` is a snapshot of the parent's v9 Bank. Its format is
> the parent's own tables as JSONL: `clusters`, `canonical_jds` (every version; `status`
> DRAFT/PUBLISHED), `source_documents` (metadata and filename, no file bodies), `parsed_jds`
> (current parse only). There is also `funnel.json` and `units.json`, from the parent's own
> code. `manifest.json` gives a row count and sha256 per file. It is git-ignored and must
> stay that way. Do not read it in bulk; let the importer read it, and test against a small
> fixture cut from it.
>
> **How we work, from day one:**
> - Docker-only: no host Python, venv or pip.
> - The failing test comes first, and every guard is broken once to prove it can fail.
> - Format with black, never `ruff format`.
> - Every non-trivial threshold or list goes in rulebook YAML with a register entry.
> - **Ship only after a full end-to-end smoke test.**
> - Check the database, not a run's counters: after an import, report the counts you read
>   back, compared with the manifest.
>
> **Start with Phase 0 (plan §5.0), then Phase 1's spinoff side (§5.1):**
> `make import-snapshot`, which verifies the hashes, imports in one transaction, is
> idempotent, refuses a count mismatch, and never overwrites local drafts on a later
> import. The export side is `docs\handoff\tools\export_snapshot.py`; leave turning it into
> the parent's `make bank-snapshot` for later.
>
> Before you write code, write the new `CLAUDE.md`, `CURRENT.md` and `HANDOFF.md` (plan
> §8.3), and ADR-001 to ADR-007 (plan §3.2). Show me the list of D5 questions before
> Phase 0's CI work. Push to `origin` only after I confirm the repo is private.

### B6. Owner tasks in parallel (start in week 1; these are the long poles)

| task | who | why it is early |
|---|---|---|
| Decide **D5 hosting**: an SFU VM with Docker, TLS, CAS on | owner + ITS | ITS lead time |
| ✅ **D6**: `https://github.com/sfu-aria/Vpfa-jda`. **Make it private** (`gh repo edit sfu-aria/Vpfa-jda --visibility private --accept-visibility-change-consequences`) and give the Team account's GitHub user admin on it | owner | it was created **public** on 2026-11-24 |
| ITS tickets: VM, DNS name, TLS certificate, **CAS service registration** for the new address, firewall (inbound 443 campus-only; outbound to `aria-gb10-2:11434` and CAS only) | ITS | plan §6.2 |
| Name the **two other reviewers**, covering ITS, Facilities, Finance and Campus Services | owner | they become the first `reviewer` accounts |
| Confirm the **Campus Services neighbours**: Ancillary Services; Meeting, Event and Conference Services; Residence Life; Bookstore/Spirit Shop and Residences spellings; Parking | VPFA | plan §2 |
| Ask the privacy office whether they want a **privacy impact assessment** before the pilot | owner | brief §5 |

The repo was seeded on 2026-11-24 with documentation and tooling only. No Bank data, no
parent source and no HR documents are in it: those travel in the bundle. **Make it private
before the new session pushes any code.**

---

## Handling rules

- The snapshot is SFU job-description content. Keep it on SFU-managed machines, **out of
  git**, and out of chat. Claude Code sends what it reads to Anthropic under the Team
  account's terms, so let code read the data, not the conversation.
- The application's own AI calls go only to SFU's inference host. That is the project's
  standing rule (plan A6), and the new `CLAUDE.md` must carry it.
- No passwords or keys are in this bundle. The new `.env` (CAS settings, admin list,
  allowed origins, feedback address) is created on the server and never committed.

## If something does not match this file

Trust the files, not this page:
- `snapshot\*\manifest.json` has the counts and versions;
- `git -C C:\vpfa\jd-assistant-parent log -1 bank/v9` shows the code that made them.

Note any difference in the new repo's `HANDOFF.md`.

A **fallback snapshot** of the live Bank (parser v8, 2026-11-24) is kept on the parent box
at `C:\repos\jd-bank-snapshots\live-2026-11-24`. It is for an emergency only: v9 is the
one to build on.

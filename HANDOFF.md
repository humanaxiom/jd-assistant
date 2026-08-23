# JD Bank — Session Handoff

Read this first every session. Single source of truth for current state + how we work.

## ▶ START HERE (2026-08-22, latest) — the parser gap is CLOSED at the source layer; the drafts have not caught up yet

| | |
|---|---|
| `main` | `6411da7` — **#137 merged.** Verify with `gh pr list`, never from this table |
| Gates | **2,878 passing, 93.37%** — re-run on the bump, full suite incl. integration |
| `rules_version` | `+76baba29cfeb` — **still unmoved.** A parser change alters what is READ, never how a JD is SCORED |
| `PARSER_VERSION` | 🔴 **`jd_segmenter_v5` (was v4)** — bumped AND re-parsed in the same session, as the trap requires |
| Register | **213** decisions, **0 ratified**. No new entries: a reader defect is not a policy default |
| Live data | 2,490 DRAFT + 4 PUBLISHED · **drafts still built from v4 parses — this is the open work** |
| CI | 🔴 **STILL blocked on GitHub billing**, unchanged. Local `make gates` is the only evidence |

### 🔴 CI IS NOT BROKEN CODE — IT IS AN UNPAID BILL

Every run since 2026-08-21 fails in **2–4 seconds**, and the failing check is called
`Gate: branch-name`, which reads like a naming problem and is not:

```
The job was not started because recent account payments have failed
or your spending limit needs to be increased.
```

The job never starts; the two real gate jobs report `skipping`. It is repo-wide on
`humanaxiom` and fixable **only** in GitHub → Billing & plans. **Do not debug the
workflow file.** Until it is paid, a PR's evidence is a pasted local `make gates`.

### THE WJQ DUTY PARSER — queue item 1, DONE at the parse layer

`_match_heading` could not see a heading that antiword's fixed-width layout had either
printed **beside the next column** or **stretched apart internally**. #137 fixed the
first; review found it left the second, and a heading carrying BOTH matched neither rule:

```
'1. POSITION   IDENTIFICATION'                        -> ok
' 1. POSITION IDENTIFICATION      For Use by Human'   -> ok
'1. POSITION   IDENTIFICATION     For Use by Human'   -> None   <-- the variant
```

Both are now one rule: the vocabulary's words joined by `\s+`, then the column gap. An
exact match is just the gap's `$` branch, so all three shapes fall out of one pattern.

**MEASURED OVER ALL 4,440 CUPE DOCUMENTS, v4 vs v5 in the live database:**

| | v4 | v5 |
|---|---:|---:|
| parse to ZERO duties | **719 (16.2%)** | **120 (2.7%)** |
| carry exactly 12 duties | 3,436 | **4,008 (90.3%)** |
| total duties extracted | 43,147 | **50,228** |
| mean duties | 9.72 | **11.31** |

**2.7% against the APSA form's 2.2%** — the 7× reader gap that the whole fabrication
chain rested on is gone. 636 documents gained duties; 3,785 are unchanged.

### ⚠ THE 19 DOCUMENTS THAT LOST DUTIES ARE THE MOST INFORMATIVE RESULT

Nineteen went DOWN, one from 12 duties to 1. Every dropped item was checked, and not one
was a real duty:

```
(a) ___ Little or no opportunity for independent work. (b) x Some opportunity for…
TRAINING EXERCISED (If the position provides training, check each description…)
Type of Contact  Students  General Public  Tutor/markers & Course Supervisors…
< 1 hour  frequent  < 1 hour  frequent  < 1 hour  frequent…
```

**An unrecognised heading does not merely lose the section BELOW it — it lets the form's
own checkbox scaffolding bleed UPWARD into the duty list.** So the gap was starving
duties *and* polluting them, and HR would have read the pollution as authored content.
Count down, content up. The thin-duty bucket (1–3) barely moved, 69 → 72, so removing
boilerplate did not create a new population of hollow documents.

### 🔴 THE BANK HAS NOT CAUGHT UP — AND THE AUDIT NOW SAYS SO OUT LOUD

`make bank-audit` **before** the re-parse vs **after**:

| WJQ carry-through | before | after |
|---|---:|---:|
| `relationships` | 426 / 473 = 90.1% | 426 / **573** = **74.3%** |
| `additional_context` | 620 / 620 = 100% | 620 / **622** = 99.7% |

**The numerators did not move; the denominators did.** Drafts are still built from v4
parses while sources now offer v5 content — so ~100 more clusters have `relationships`
in their sources than any draft carries. **A carry-through that falls here is CORRECT
and is the measure of the pending work**, not a new defect. JDFN is byte-identical
across the two runs, which confirms the fix is WJQ-only with no cross-form leakage.

### ▶ THE QUEUE, IN ORDER

1. 🔴 **ONE producer pass over the CUPE clusters** — `--only-template wjq`. This is the
   step that converts 7,081 newly-read duties into drafts and clears the **1,219
   fabricated duties** in 153 drafts. `make bank-audit` before and after; WJQ
   `relationships` should climb back toward 100% and the invented-duty count go to zero.
   ⚠ ~19 h of GPU based on the last run. **Deliberately not started this session.**
2. ⚠ **Expect approvable counts to FALL, and say so before someone finds it.** HR-213
   means a draft that honestly reports no duties fails `SFU-COMP-DUTIES`. 599 documents
   just stopped being silent, but some drafts will now surface real gaps instead of
   fluent invention. That is the fix working.
3. **The duty-frequency matching design** — unchanged from the previous handoff; the
   model reorders duties so heavily that both obvious matching rules attach WRONG
   frequencies to a field feeding the CUPE point-factor evaluation. Needs evidence.
4. **Re-measure the JDFN cohort** — `problem_solving` still reads **228.2% FABRICATED**
   (1,084 / 475). Untouched by this work; it is a JDFN-side S-5 defect.
5. **Phase F**, **Phase G rulebook items**, 🔴 **TLS at the edge**, **HR ratification**
   (213 entries, 0 signed) — all unchanged.

### ▶ WHAT THIS SESSION LEARNED THAT IS NOT IN A DIFF

- **A green PR is a claim about the tests, not about the fix being complete.** #137 was
  green, correct, and measured — and still left a variant of its own defect standing,
  found by asking "what OTHER shape does this layout produce?" and checking against the
  archive rather than against the test suite.
- **A duplicated constant is how a measurement tool starts lying.** `bank_audit` held a
  hardcoded `"jd_segmenter_v4"` while every other consumer imported `PARSER_VERSION`.
  The v5 bump would have made it count the OLD corpus against the NEW Bank and report
  the difference as content loss — a false alarm in the one tool whose entire value is
  being believed when it cries loss. Found by grepping the literal before bumping it.
- **The metric moving the WRONG way can be the honest answer.** WJQ carry-through fell
  after the re-parse and that is exactly right: new content in sources that no draft
  carries yet. A tool that only ever reports improvement is not measuring anything.
- **Measure the fix in the direction it might do harm, not just the direction it helps.**
  The 19 documents that LOST duties were the finding of the session — they revealed the
  gap was polluting duty lists, which nothing had noticed and no count would show.

---

## ▶ PREVIOUS (2026-08-22, earlier) — the re-baseline finished, and the audit it exposed found fabricated duties

| | |
|---|---|
| `main` | `7ad9c9c` — **#133, #134, #135 all merged. Zero open PRs.** Verify with `gh pr list` |
| Gates | **2,873 passing, 93.36%** — re-run on MERGED main, full suite incl. integration |
| `rules_version` | `+76baba29cfeb` — **still unmoved.** Nothing merged changes how a JD is SCORED |
| Register | **213** decisions, **0 ratified**. HR-213 is new |
| Live data | 2,490 DRAFT + 4 PUBLISHED · **620 CUPE drafts carrying point-factor context** (was 237) |
| Producer run | ✅ **COMPLETE** — 649/649 refreshed, **0 cluster failures**, ~18.8 h |
| CI | 🔴 **GitHub Actions still blocked on billing.** Local `make gates` is the only evidence |

### The CUPE re-baseline finished, and it worked

```
clusters: 2456 recomputed -> 649 seen [wjq=649]
drafts:   0 persisted, 649 refreshed, 0 skipped, 0 cluster failures, 1807 out of scope
LLM:      10 rewrite failures (1.5%), 1 audit failure
wjq:      mean 76.38 · 6 approvable · grades {B: 307, C: 337, D: 5}
```

| | before | after |
|---|---:|---:|
| CUPE drafts with point-factor content (HR-207) | 237 | **620 of 620 possible** |
| CUPE drafts with Relationships (HR-212) | 0 | **426** |
| mean duties per CUPE draft (HR-209) | ~7 | **11.44** |

**620 is not a shortfall against 649**: 620 clusters have a source document carrying
point-factor content and 29 have none, so that is 100% carry-through. The `--only-template`
scoping worked and announced its own blind spot (1,807 clusters not looked at).

### 🔴 `make bank-audit` — THE NEW THING, AND THE REASON THE REST OF THIS SECTION EXISTS

**Read-only, per form, one command.** For each section: how many clusters' **sources
offered** it vs how many **drafts keep it**. That ratio is what nothing reported, and it
is why four content-loss defects in a row were found by hand-written SQL days after the
run that caused them. The producer's own summary counts CLUSTERS PROCESSED, not CONTENT
KEPT — `refreshed=649 failures=0` prints identically whether a run enriched every draft
or gutted it.

```bash
make bank-audit                              # the report; exits 2 on a verdict
make bank-audit AUDIT_ARGS="--json"          # machine-readable, two runs diff cleanly
```

**Run it BEFORE and AFTER every producer pass.** A carry-through that falls is a
content-loss defect; there is no other view that shows one.

Two readings it computes that are worth knowing about:

- **the merge-only CONTROL.** A rewrite *failure* falls back to the deterministic merge,
  so those drafts are the same pipeline with the model removed — a controlled comparison
  the Bank produces for free. It is what turned "frequencies are low" into "**the rewrite
  destroys a field the merge preserves**": rewritten **23.5%**, merge-only **75.0%**,
  sources 79.7%.
- **carry-through ABOVE 100% = fabrication.** A draft can only carry what its sources
  stated. JDFN `problem_solving` reads **228.2% (1,084 / 475)** — the S-5 invented
  sections as one number instead of a five-page argument.

⚠ The audit found **three bugs in itself** on its first runs, all "arithmetically fine,
meaning the wrong thing", each now a test. The worst: the JDFN filter was an allow-list
and silently omitted **1,300 drafts** whose `employee_group` is null (31.9% of the archive
is unclassified and still drafted and scored). It reported 541 JDFN drafts where the Bank
holds 1,841. If you extend this tool, that is the failure mode to expect.

### 🔴🔴 FABRICATED DUTIES — the most serious defect this project has found

**153 canonical drafts carry 1,219 duties that NO SOURCE DOCUMENT STATES.**

| cohort | drafts | invented duties |
|---|---:|---:|
| CUPE | **101 of 649 (15.6%)** | **996** |
| unclassified | 38 | 160 |
| APSA | 14 | 63 |

A role whose sources list **no duties at all** came back with twelve, including
*"verifies bibliographic records against the library online catalogue"*. Duties are the
core content of a job description; this is S-5 one field over, on the field that matters
most.

**The chain has three links and only the last is fixed:**

1. **the WJQ parser recovers NO duties from 719 of 4,440 CUPE documents (16.2%)** —
   against 2.2% on APSA, 2.1% APEX, 0% Poly. A reader gap, 7× the JDFN rate. ⟵ **NEXT**
2. `merge_cluster` correctly produces nothing from documents that state nothing.
3. the rewrite wrote 8–12 plausible duties into the silence. **CLOSED by #135** (HR-213,
   `rewrite.duties_never_invented`) — the same EMPTY-TO-EMPTY rule already applied to
   whole sections.

Nothing objected because the duty guard only ever **flagged** what the model added and
never removed it — right when the draft HAS duties to drift from, vacuous when it has none.

⚠ **#135 STOPS NEW FABRICATION; IT REPAIRS NOTHING.** The 1,219 duties already in the
Bank stay until the producer re-runs over those clusters — and that re-run should follow
the parser fix, not precede it, or it will simply re-derive empty duty lists.

⚠ **And it has a cost, stated rather than discovered later:** a draft that honestly
reports no duties fails `SFU-COMP-DUTIES` and cannot be approved until a human writes
them. That is intended — it is the parser gap becoming visible where someone will act on
it, instead of being papered over by text that reads well and describes nobody's job.

### The duty-frequency defect — MEASURED, NOT FIXED, and the naive fix is unsafe

Cohort-wide retention is **24.1%**, *below* the 27.8% HR-209 recorded as its "before" and
far below the 43.8% it predicted from five clusters. The restore exists but sits **inside**
the well-grounded branch, so a heavily-reworded duty hits `continue` and keeps nothing.

**Do not simply move the restore out of that branch.** Measured over 120 real CUPE
clusters:

| | |
|---|---|
| duty counts merge vs draft align | **91.7%** (HR-209 working) |
| argmax match == positional match | **8–26%** — the model REORDERS heavily |
| duties with Jaccard < 0.2 to ANY merge duty | **62.4%** |

So positional matching would attach a wrong frequency ~80% of the time, and low-confidence
argmax is noise. **A wrong frequency is worse than a missing one** — it feeds the CUPE
point-factor evaluation. This needs a real matching design, and it ranks **below** the
parser gap and the fabrication cleanup.

### ▶ ON PURGING AND STARTING FROM ZERO — asked 2026-08-22, answered with evidence

**A full purge + re-ingest would not help and would cost days.** `canonical_jds` is fully
derived and the producer already rebuilds it in place (this run: 649 refreshed, **0
persisted**). Re-ingesting re-derives the same drafts from the same parses with the same
code, reproducing the identical defect, at ~19 h (CUPE) or ~44 h (full) of GPU.

**But the instinct was half right, and the audit found where.** The break is at the
**parse** layer, not the ingest or the data: the WJQ duty extraction fails on 16.2% of
CUPE documents. **Re-parsing costs no GPU at all.** So the defensible version is: fix the
WJQ duty parser → re-parse CUPE → **one** producer pass. Hours, not days.

### ▶ IF YOU ARE STARTING COLD

```bash
git fetch && git log --oneline origin/main -1     # expect 7ad9c9c or later
gh pr list                                        # the table above lags; this does not
docker ps --format '{{.Names}}' | grep jd-bank    # ⚠ the stack does NOT self-restart
docker compose up -d                              # ...if that came up empty
docker ps --filter "name=canonical"               # MUST be empty before any producer work
make bank-audit                                   # ⟵ START HERE. What the Bank CONTAINS
```

⚠ **The box has other Docker projects on it** — a `docker ps` full of random-named
`postgres:16-alpine` containers is probably `recruiter-assistant`'s testcontainers.
⚠ **Never pass `--remove-orphans`** while a producer run is alive; compose reports the run
as an orphan and the flag would delete it mid-pass.

### The queue, in order

1. 🔴 **Fix the WJQ duty parser** — 719 of 4,440 CUPE documents (16.2%) yield no duties.
   This is the root of the fabrication chain and the reason 101 CUPE drafts have invented
   content. No GPU needed to fix or to re-parse.
2. **Re-parse CUPE, then ONE producer pass** over the affected clusters. `make bank-audit`
   before and after — the invented-duty count must go to zero and duty carry-through must
   rise.
3. **The duty-frequency matching design** — see above. Needs evidence, not a patch.
4. **Re-measure the JDFN cohort.** Every JDFN figure predates #130; the audit shows
   `relationships`/`decision_making` carry-through at **60.9%** and `problem_solving`
   FABRICATED at 228.2%. A JDFN pass should take the first two toward 100% and the third
   to at most 100%.
5. **Phase F** (`docs/tasks/phase-f-form-scoping-backlog.md`) — search is JDFN-only both
   ways; D3's per-form draft evaluation renders nowhere and it is the number HR will ask for.
6. **Phase G rulebook items** — `SFU-GATE-SENIOR-TITLE` unfalsifiable on the WJQ;
   `thresholds.wjq.duties_max: 12` structurally dead; **the stack should survive a Docker
   restart** (no `restart:` policy while every other project on the box has one).
7. 🔴 **TLS at the edge** — `sfuai.ca:7000` is a Telus NAT forward to plain HTTP.
8. **HR ratification** — 213 entries, 0 signed.

### ▶ ONE NUMBER HR WILL ASK ABOUT

**6 of 649 CUPE drafts are approvable**, blocked overwhelmingly by
`SFU-APPROVE-KSA-ORDER` (547) and `SFU-APPROVE-QUAL-EQUIVALENT` (503). Both are
deliberately `applies_to: [jdfn, wjq]` — registered decisions, not JDFN rules leaking onto
the WJQ. So it is a real finding about CUPE JDs and an HR question, not a bug. State it
before someone else discovers it.

### ▶ WHAT THIS SESSION LEARNED THAT IS NOT IN A DIFF

- **Build the measurement before the next fix, not after the next surprise.** Four
  content-loss defects were each found by hand-written SQL days late. `make bank-audit`
  cost an afternoon and immediately surfaced a defect (1,219 fabricated duties) that four
  rounds of review, a green suite and a completed 18-hour run had all missed.
- **A metric that cries wolf gets ignored, so a tool must know policy from bug.** The
  audit's first run flagged JDFN `additional_context` at 0% — which is exactly what HR-169
  asks for — and rendered "no source states it" as a 0% failure. Both are now readings, not
  alarms.
- **Above 100% is a different failure from below 100%.** Losing content and inventing it
  have opposite fixes, and a metric that collapses both into "not 100%" hides the worse one.
- **Measure before patching, even when the patch is one line.** The frequency restore looks
  like a one-line move. Measuring first showed the model reorders duties so heavily that
  both obvious matching rules would attach WRONG frequencies to a field that feeds the
  point-factor evaluation. The one-line fix would have been the fourth "fixed it" that
  wasn't.

---

## ▶ PREVIOUS (2026-08-21) — everything merged; the CUPE re-baseline was running

| | |
|---|---|
| `main` | `d68b202` — **#121, #130, #131 and #132 all merged. Zero open PRs.** Verify with `gh pr list`, never from this table |
| Gates | **2,854 passing, 94.26%** — re-run on MERGED main, full suite incl. integration. #130 and #132 both touch the producer and had never been tested together |
| `rules_version` | `+76baba29cfeb` — **still unmoved.** `harmonization.yaml` is unhashed; nothing merged changes how a JD is SCORED |
| Register | **212** decisions, **0 ratified**. Audience split: **77 HR · 50 reviewer-facing · 85 engineering** |
| Live data | 2,490 DRAFT + 4 PUBLISHED · **237 CUPE drafts carrying point-factor context — climbing, the run is rewriting them now** |
| Producer run | 🟢 **LIVE** — `jd-canonical-cupe-rerun`, started 2026-08-21 ~17:34 UTC |
| CI | 🔴 **GitHub Actions is blocked repo-wide on billing** — every job fails in ~2s with *"recent account payments have failed or your spending limit needs to be increased"*. **Local `make gates` is the only evidence right now.** Not a branch-name problem, despite what the failing check is called |

### ▶ THE RUN THAT IS IN FLIGHT

```
docker compose run -d --name jd-canonical-cupe-rerun -e PYTHONUNBUFFERED=1 canonical \
  python -m src.jd_bank.canonical --only-template wjq --commit-every 25
```

**No `--resume` — this is the re-baseline.** Two deliberate differences from the pass that
died on 2026-08-20:

- **`PYTHONUNBUFFERED=1`** (the Phase G legibility item). The previous run logged **zero lines
  in 52 minutes** and sat at 0.00% CPU, which reads exactly like a hang and was not — `python
  -m` without `-u` block-buffers stdout. Progress lines now appear as they happen, every 25
  clusters.
- **NOT `--rm`.** A dead container is how the last crash was diagnosed. Let it persist.

⚠ **Nothing commits until the first 25-cluster checkpoint** (~25 min at ~60 s/cluster), and
the first progress line lands at the same moment. Silence before that is expected.

**The health signal — the ONLY number that separates a good run from a ruined one**, because
`refreshed=50 failures=0` prints identically either way:

```bash
docker compose exec -T postgres psql -U app -d harness -t -c \
  "SELECT count(*) FROM canonical_jds WHERE status='DRAFT' \
   AND coalesce(content->>'additional_context','')<>'';"
```

**237 at launch; it should climb toward ~649.** If it stalls while the progress line advances,
stop the run — that is the shape of a pass that is "succeeding" while destroying content.

⚠ **Never pass `--remove-orphans`** to a compose command while this is alive: the run is a
`docker compose run` one-off in project `jd-bank`, so compose reports it as an orphan and the
flag would delete it mid-pass.

### The ~90-second pre-flight, run BEFORE this pass (2026-08-21)

Two earlier passes were started on unverified fixes and both were still wrong. One real
all-CUPE cluster driven through merge → rewrite:

```
cluster 88c49896 — 132 member JDs
  MERGE  -> group='cupe' template='wjq' context=6007 chars duties=12
            relationships=YES  decision_making=0  problem_solving=0
  REWRITE-> group='cupe' template='wjq' context=6007 chars duties=12  score=76.13
            scrubbed_sections=()
```

All three recent fixes confirmed on real data: context 6007 (HR-207), duties **12→12**
(HR-209 — it used to compress to 8), `relationships=YES` (HR-212 reaching CUPE).

**⚠ THE SCORE MOVED 85.29 → 76.13, AND THAT WAS WORTH 10 MINUTES BEFORE SPENDING 11 GPU-HOURS.**
Isolating #130 on the same cluster:

```
relationships=drop (pre-#130):   score=75.29  grade=B
relationships=longest (shipped): score=76.13  grade=B
delta = +0.84 · NEW findings: [] · REMOVED: ['SFU-COMP-RELATIONSHIPS']
```

So #130 **improves** the draft and introduces nothing. The drop is HR-209's intended trade —
twelve real duties instead of seven compressed ones give the rules more surface — which #129
predicted in as many words ("scores stayed in the 67–85 band, grades stayed at B"). **A more
complete draft scoring lower is the honest direction.**

> 🔴 **The pattern to carry: in three separate defects this phase, the bug made the score go
> UP.** Invented sections scored higher; compressed duty lists scored higher; dropped
> point-factor content scored higher. **Treat a rising score as a question, not a result.**

### ▶ IF YOU ARE STARTING COLD, DO THESE FIVE THINGS FIRST

```bash
git fetch && git log --oneline origin/main -1     # expect d68b202 or later
gh pr list                                        # the table above lags; this does not
docker ps --format '{{.Names}}' | grep jd-bank    # ⚠ the stack does NOT self-restart
docker compose up -d                              # ...bring it back if that came up empty
docker ps --filter "name=canonical"               # a run in flight? or MUST be empty before starting one
```

⚠ **The box has other Docker projects on it.** A `docker ps` full of random-named
`postgres:16-alpine` / `neo4j:5-community` containers is probably
`C:\repos\recruiter-assistant`'s testcontainers, not ours.

### What landed since the last handoff

- **#130 — HR-210/211/212.** The 4.1 merge now carries `decision_making` / `problem_solving` /
  `relationships`, each a registered knob (`drop` / `longest` / `union`). `relationships` ships
  `longest` deliberately, unlike the other two: it is a STRUCTURED object whose `supervisory`
  field is prose about one reporting structure, and pooling two of them states a third nobody
  wrote. **`sections_not_merged` is now a diff against the draft**, not a fixed section list.
- **#132 — Phase G producer items.** The `clusters` snapshot follows the draft (it was
  write-once, so re-ordering `templates_harmonized` left the Library showing **APSA documents
  as the sources of a CUPE draft**). Both counter identities are `model_validator`s now, so
  the partition cannot go stale into prose again. `--resume --allow-downgrade` exits 2 instead
  of silently doing nothing.
- **#132 also recorded a finding as NOT REACHABLE rather than closing it.** "A member dropped
  by `load_member_jds` is invisible per cluster" cannot happen: both loaders validate the same
  rows, but clustering must *also* build `JobSignals`, so it accepts a strict subset — a row
  that fails the member load already failed to sign. `member_rows_dropped_unvalidatable` is
  **structurally zero**, the same class of dead parameter as `thresholds.wjq.duties_max: 12`.
- **HR-facing docs refreshed** (this PR) — see below.

### 🔴 THE HR MATRIX HAD A DECISION THAT CONTRADICTED THE SHIPPED SYSTEM

`docs/decisions/HR-DECISION-MATRIX.md` **Decision 8** still asked HR to *"Confirm the scope:
APSA/APEX/Poly only, not CUPE"*, and recommended exactly that. Its option (b) — "commission a
CUPE quality bar, a separate project" — **is what Phases A–E built.** HR would have been
ratifying a boundary the system no longer has.

Decision 8 is rewritten: the question is now whether the WJQ bar we built is right, with three
options (ratify provisionally and pilot / turn CUPE back off / read-and-search only). The
matrix also gains **"What changed for the people writing JDs"** — the four content-loss
corrections stated for an HR reader, without internal codenames.

`docs/OPERATOR-GUIDE.md` gains a **fifth guardrail — "the model may reword; it may not
invent"** — with the four limits and what happens when a rewrite fails (fall back to the
deterministic merge; a draft is never lost, only less polished). That is the question a
recruiter using an AI-assisted tool asks first, and the guide had no answer to it.

### The queue, in order

1. **Watch the run to its first checkpoint**, then to completion (~649 clusters). Health
   signal above, not the progress line.
2. **Re-measure the JDFN cohort** once the CUPE pass is done. Every JDFN figure in `plan.md`
   and the baseline docs predates #130, and the S-5 write-up says so explicitly. The ~18
   points should come back **honestly** this time — from merged source content rather than
   invented sections. That measurement is the evidence for HR-210/211/212.
3. **Phase F** (`docs/tasks/phase-f-form-scoping-backlog.md`, on `main` since #121) — search is
   JDFN-only in both directions, the dashboards report a pre-CUPE world, and D3's per-form
   draft evaluation renders nowhere. **That last one is the number HR will ask for.**
4. **Phase G, the rest** — the remaining rulebook items:
   `SFU-GATE-SENIOR-TITLE` is unfalsifiable on the WJQ (it needs `relationships.supervisory`,
   which `parser/wjq.py` never populates by design — 71 of 4,300 CUPE documents carry the
   finding and it feeds a gate no CUPE author can clear), and `thresholds.wjq.duties_max: 12`
   is structurally dead. Plus: **the compose stack should survive a Docker restart** (it has no
   `restart:` policy while every other project on the box does), and **`python -u` belongs in
   the canonical service** rather than being passed per-run.
5. 🔴 **TLS at the edge** — still the only genuinely external item. `sfuai.ca:7000` is a Telus
   NAT forward to `192.168.1.80:25800`, plain HTTP on the public internet.
6. **HR ratification** — 212 entries, 0 signed, including the bar that gates publishing.

### ▶ WHAT THIS SESSION LEARNED THAT IS NOT IN A DIFF

- **Test the MERGE, not the branches.** #130 and #132 were each green alone and had never run
  together; both touch the producer. Re-running full gates on merged `main` before launching
  cost six minutes against an eleven-hour run. A green branch is a claim about that branch.
- **Investigate a moved number before spending on it.** The pre-flight score had dropped nine
  points. Ten minutes of isolation showed #130 was worth **+0.84** and the move belonged to a
  different, intended change. Launching without checking would have meant discovering it in
  hour nine; *not* checking and being right is indistinguishable from not checking and being
  wrong.
- **An HR-facing document can go stale in a direction that costs trust, not just accuracy.**
  Decision 8 did not merely lag — it asked SFU to ratify the opposite of what shipped. Docs
  that ask someone to *decide* need re-reading whenever the thing they describe changes, and
  nothing in `make gates` can catch that.
- **A finding can be closed by measuring that it is unreachable.** Two this session: the
  per-cluster member drop (#132) and the JDFN guard (#130, where the obvious fix was the wrong
  one). Recording *why it never fires* is worth more than a fix that changes nothing.

---

## ▶ PREVIOUS (2026-08-20) — the 4.1 merge carries three more sections; the producer run was killed by Docker

| | |
|---|---|
| `main` | `db45760` — **#127, #128 and #129 merged.** The previous START HERE said `033eac8` and was three commits stale within a day; trust `git log`, not this table |
| **Open PRs** | **[#130](https://github.com/humanaxiom/jd-assistant/pull/130)** the 4.1 merge sections (this session) · **[#121](https://github.com/humanaxiom/jd-assistant/pull/121)** Phase F backlog (docs). Verify with `gh pr list`, never from this table |
| Gates | **2,844 passing, 94.16% → 94.18%** on #130, full suite incl. integration. `register-check` exits 0 |
| `rules_version` | `+76baba29cfeb` — **still unmoved.** `harmonization.yaml` is unhashed; #130 changes how a draft is ASSEMBLED, never how one is SCORED |
| Register | **212** decisions, **0 ratified**. HR-210 / HR-211 / HR-212 are new and all `open` |
| Live data | 2,490 DRAFT + 4 PUBLISHED · 237 CUPE drafts with point-factor context — **unchanged, and verified after the crash below** |
| Producer run | 🔴 **STOPPED — killed mid-run by a Docker restart, 0 clusters committed.** Deliberately NOT restarted; see the decision below |
| Backup | ✅ unchanged: `C:\Users\adam\jd-bank-backups\harness-pre-full-llm-run.dump` (81,331,260 B) |

### 🔴 THE PRODUCER RUN DIED, AND NOTHING IN THE APPLICATION DID IT

A CUPE pass (`--only-template wjq --commit-every 25`) was started at **18:52:27 UTC**,
42 seconds after HR-209 (#129) merged — it picked the fix up through the `./core` bind
mount, not the image, which is 2026-07-21 and stale. It ran for 52 minutes and was
killed at **19:44:35 UTC**.

**It was not the code.** Every container in every project on the box exited **255 at the
same instant** — `jd-bank-{api,postgres,neo4j,redis}` and the run itself. Exit 255 across
an entire daemon is Docker Desktop / WSL2 going down, not an application fault. `OOMKilled`
is false. The other projects on the box came back on their own; **jd-bank did not, because
its compose services carry no `restart:` policy while `recruiter-assistant`, `azprograms`
and `bccb` all do.** So the stack sat down for ~50 minutes and nothing said so.

⚠ **Two things to take from this, neither of them "re-run it":**

1. **`--commit-every 25` did exactly its job.** The run died before its first checkpoint,
   so **zero** clusters were committed and nothing is half-written. Verified after
   bringing the stack back: **2,490 DRAFT / 4 PUBLISHED / 237 with context** — byte-for-byte
   the pre-run baseline. A partial commit here would have been much worse than a lost run.
2. **A silent producer is not a stopped producer, and a stopped one is not a broken one.**
   The container logged **zero lines in 52 minutes** and sat at **0.00% CPU**, which reads
   exactly like a hang. It was neither: `python -m` runs without `-u`, so stdout is
   block-buffered, and the process was in `epoll_wait` on the model socket. The way to
   tell is to ask something other than the log — `docker exec … /api/ps` on `aria-gb10-2`
   and watch `expires_at` roll forward, which only happens when a request completes.
   Consider adding `-u` to the canonical service's command so the next run is legible.

### ▶ THE DECISION THIS SESSION MADE — the re-run WAITS for #130

The obvious move was to restart the CUPE pass immediately. **Measured against the live
Bank first, and it was the wrong move:**

```sql
SELECT count(*) AS cupe_docs,
       count(*) FILTER (WHERE jsonb_array_length(coalesce(parsed->'decision_making','[]'::jsonb))>0),
       count(*) FILTER (WHERE parsed->'relationships' IS NOT NULL AND parsed->'relationships'<>'null'::jsonb)
FROM parsed_jds WHERE parser_version='jd_segmenter_v4' AND parsed->>'employee_group'='cupe';
--  4440 |  139 |  3147
```

**70.9% of CUPE source documents (3,147 of 4,440) carry `relationships`, and today's
merge drops every one.** #130 is not a JDFN-only change, as the S-5 write-up implied —
it changes what a CUPE draft contains too. Running the ~11-hour WJQ pass now would
produce a cohort that is stale for 70.9% of its own relationship content the moment #130
lands, and buy a second pass. So the queue below puts #130 first.

### ▶ IF YOU ARE STARTING COLD, DO THESE FIVE THINGS FIRST

```bash
git fetch && git log --oneline origin/main -1     # expect db45760 or later
gh pr list                                        # the table above lags; this does not
docker ps --format '{{.Names}}' | grep jd-bank    # ⚠ NEW: the stack does not self-restart
docker compose up -d                              # ...bring it back if that came up empty
docker ps --filter "name=canonical"               # MUST be empty before any producer work
docker compose exec -T postgres psql -U app -d harness -t -c \
  "SELECT count(*) FROM canonical_jds WHERE status='DRAFT' \
   AND coalesce(content->>'additional_context','')<>'';"
```

Verified 2026-08-20 **after** the crash and restart: **2,490 DRAFT · 4 PUBLISHED · 237
carrying point-factor context.** That last number is the health signal for a CUPE
producer pass and the ONLY one that distinguishes a good run from a ruined one —
`refreshed=50 failures=0` prints identically either way.

⚠ **The box has other Docker projects on it.** A `docker ps` full of random-named
`postgres:16-alpine` / `neo4j:5-community` containers is probably
`C:\repos\recruiter-assistant`'s testcontainers, not ours.

⚠ **Never pass `--remove-orphans`** to a compose command here while a producer run is
alive: the run is a `docker compose run` one-off in project `jd-bank`, so compose reports
it as an orphan and the flag would delete it mid-pass.

### What #130 does

Implements the S-5 conclusion (`docs/baseline/jdfn-remeasure-2026-08-19.md`), which had
been measured and argued but deliberately not shipped. `merge_cluster` now merges
`decision_making` / `problem_solving` / `relationships`, each under its own registered
policy — `drop` (the old behaviour) / `longest` (one member's section verbatim) / `union`
(pooled across the members that state it, folded at `duty_dedup_jaccard_min`).

| knob | ships | entry | why |
|---|---|---|---|
| `decision_making_policy` | `union` | HR-210 | a list of discrete statements — the shape duties already have |
| `problem_solving_policy` | `union` | HR-211 | same shape; **flagged as the likeliest-wrong knob** (44.9% source presence) |
| `relationships_policy` | `longest` | HR-212 | a STRUCTURED object; pooling two `supervisory` lines states a third nobody wrote |

Two consequences worth knowing before reading the diff:

- **`sections_not_merged` is now a DIFF AGAINST THE DRAFT**, not a hardcoded section
  list. With a policy per section only the draft knows what survived. `position_number`
  is still never merged and is now the only section that flags by default — which is what
  keeps the flag alive at all.
- **The EMPTY-TO-EMPTY guard is reachable in production for the first time.**
  `test_a_section_the_grounded_draft_has_is_left_to_the_rewrite` hand-built a `MergedRole`
  that `merge_cluster` could not emit — which is how a green suite kept certifying a guard
  that never fired. It now drives a real merge with an explicit precondition assertion.

### The queue, in order

1. **Review + merge [#130](https://github.com/humanaxiom/jd-assistant/pull/130).** It now
   gates item 2 — see the 70.9% measurement above.
2. **Re-run the producer over the CUPE cohort**, once, after #130 is on `main`:
   `make canonical-drafts CANONICAL_ARGS="--only-template wjq --commit-every 25"`.
   **Start WITHOUT `--resume`** — that is the re-baseline; `--resume` skips clusters that
   already hold a landed rewrite and is the flag for continuing an interrupted pass, not
   for opening one. Do the ~90-second single-cluster check below first.
3. **Phase F** (`docs/tasks/phase-f-form-scoping-backlog.md`) — search is JDFN-only in
   both directions and the dashboards report a pre-CUPE world. D3's per-form draft
   evaluation renders nowhere, and it is the number HR will ask for.
4. **Phase G** — the remaining producer + rulebook review items. The two resume items are
   closed; **counters do not partition**, the **write-once `clusters` snapshot**,
   `--resume --allow-downgrade --no-llm` as a **silent no-op**, and **per-cluster member
   drops being invisible** are still open. Add: **the canonical service should run
   `python -u`**, and **the compose stack should survive a Docker restart**.
5. 🔴 **TLS at the edge** — still the only genuinely external item. `sfuai.ca:7000` is a
   Telus NAT forward to `192.168.1.80:25800`, plain HTTP on the public internet.
6. **HR ratification** — 212 entries, 0 signed, including the bar that gates publishing.

### The ~90-second check that must precede ANY producer pass

Two passes were started on unverified fixes and both were still wrong. Drive one real
all-CUPE cluster through merge → rewrite and compare. Last clean result:

```
cluster 88c49896 — 132 member JDs
  MERGE  -> group='cupe' template=wjq context=6007 chars
  REWRITE-> group='cupe' template=wjq context=6007 chars  duties=8  score=85.29
```

⚠ After #130 this cluster should ALSO come back with a `relationships` section — that is
the cheapest confirmation the merge change reached the CUPE cohort.

### ▶ WHAT THIS SESSION LEARNED THAT IS NOT IN A DIFF

- **Measure the blast radius of your own fix before sequencing around it.** #130 was
  filed under "the JDFN cohort's missing 18 points" and the S-5 doc quotes JDFN
  percentages throughout. One query said 70.9% of CUPE sources carry `relationships` too.
  Had the CUPE pass been restarted on that assumption, ~11 GPU-hours would have produced
  a cohort needing a second pass.
- **A doc that says "not implemented here, and here is why" is worth more than the code
  it withholds.** `jdfn-remeasure-2026-08-19.md` made this a two-hour task instead of a
  two-day one: the measurement, the rejected fix (loosening the guard) *and the reason it
  is wrong* were already written down.
- **Edit in a worktree when a long run bind-mounts the repo.** `./core` is mounted `rw`
  into the producer container. Python imports at start, so an edit will not usually change
  a run in flight — but "usually" is doing real work in that sentence, and a lazily
  imported module would switch policy mid-pass and leave a Bank with two merge policies
  and no way to tell which draft got which. `git worktree add` costs seconds.
- **The name in the docstring outlives the code.** Three separate docstrings still
  enumerated the three sections as "sections 4.1 does not merge" after the merge started
  merging them. That sentence was the entire justification for the hardcoded list the PR
  removes; leaving it would have re-taught the next reader the thing being fixed. Found
  by reading the diff, not by a failing test — no test asserts a docstring.

---

## ▶ PREVIOUS (2026-08-19, later) — `--resume` fixed; the producer re-run is now restartable

| | |
|---|---|
| `main` | `033eac8` — **#125 and #126 both merged.** Nothing from this session is left unmerged |
| **Open PRs** | **[#121](https://github.com/humanaxiom/jd-assistant/pull/121)** Phase F backlog (docs) — the only one. Verify with `gh pr list`, never from this table |
| Gates | **2,825 passing, 94.16%** — locally and in CI on #126. `register-check` + `guide-check` exit 0 |
| `rules_version` | `+76baba29cfeb` — **still unmoved.** #126 touches no rulebook YAML; nothing changes how a JD is SCORED |
| Register | **208** decisions, **0 ratified**. #126 adds none — a predicate reading the wrong field is not a tunable default |
| Live data | 2,490 DRAFT + 4 PUBLISHED · **237 CUPE drafts rebuilt, the rest still wrong** — unchanged, #126 touched no data |
| Producer run | 🔴 **STILL STOPPED** — but it is now **restartable**, which it was not this morning |
| Backup | ✅ **out of temp.** `C:\Users\adam\jd-bank-backups\harness-pre-full-llm-run.dump` (81,331,260 B, verified byte-identical to the original) |

### What #126 fixes

The Phase G item that blocked item 1 from being resumable. `draft_was_llm_written` read
`change_log.pipeline.llm_enabled`, which records only that a rewrite **client was
injected**. A rewrite failure is isolated rather than fatal — the cluster keeps the
deterministic merge draft and the run continues — so a failed cluster was stamped
`llm_enabled: true` indistinguishably from one whose rewrite succeeded.

**Both callers of that predicate misread it, and the second one is not in the review
findings:**

| caller | question it thought it asked | what it actually skipped |
|---|---|---|
| `--resume` | "does an expensive run still owe this work?" | clusters whose rewrite **raised** |
| no-DOWNGRADE guard | "may a cheap run overwrite this?" | the same clusters, as though they held prose they do not hold |

So those rows were reachable by **no producer invocation that did not name them
individually** — and a ~44-hour pass could not repair the rows it had itself damaged.

Measured against the live Bank:

```
 llm_enabled | rewrite_ran | rewrite_failed | count
-------------+-------------+----------------+-------
 true        | true        | false          |  2021
 false       | false       | false          |   423
 true        | false       | true           |    44   <-- abandoned
             |             |                |     2
```

The resume's skip count over the current Bank moves **2,065 → 2,021** — exactly those 44
recovered. `rewrite_ran` / `rewrite_failed` had been in the same packet since Phase 4.2a;
nothing new is recorded, the wrong field was being read. The predicate is now
`draft_has_rewritten_prose`, because the old name was the bug stated out loud.

**Also closed:** a resume skip wrote no audit row — the only skip violating the module's
own invariant ("one `audit_log` row per persist/refresh and per skip"). Now
`canonical_draft.skipped_resume` / `reason=resume_rewrite_already_landed`.

⚠ **#126 makes the 44 drafts REACHABLE, not fixed.** They still hold a deterministic
merge with no rewrite. The producer re-run is what repairs them.

### 🔴 S-5 — MEASURED. The guard is not the defect; the 4.1 merge is.

**`docs/baseline/jdfn-remeasure-2026-08-19.md` has the numbers and the argument.** The
headline, measured against the live Bank:

| JDFN drafts | count | with `decision_making` | mean score |
|---|---:|---:|---:|
| written **before** the section guard | 1,156 | 1,084 (93.8%) | **84.61** |
| written **after** it | 685 | 0 | **66.42** |

**But loosening the guard would be wrong.** The rewrite is fed `_flatten_jd(merged.draft)`
and nothing else, and that draft's `decision_making` is always empty — so the 1,084
pre-guard sections were invented from *no source at all*. The 18.19 points are
fabrication being withdrawn, not a regression.

**The real defect is one layer up: 97.0% of JDFN source documents carry
`decision_making` and 97.4% carry `relationships`, and the 4.1 merge drops all of it as
"out of scope".** So no JDFN draft the pipeline produces can ever be complete. Merging
those three sections in 4.1 fixes the guard's *input* rather than the guard, makes the
EMPTY-TO-EMPTY protection reachable in production for the first time, and brings the
points back honestly. It needs a merge policy per section — an HR-207-shaped question,
so a register entry decided in the same PR.

### ▶ IF YOU ARE STARTING COLD, DO THESE FOUR THINGS FIRST

```bash
git fetch && git log --oneline origin/main -1     # expect 033eac8 or later
gh pr list                                        # the table above lags; this does not
docker ps --filter "name=canonical-run"           # MUST be empty before any producer work
docker compose exec -T postgres psql -U app -d harness -t -c \
  "SELECT count(*) FROM canonical_jds WHERE status='DRAFT' \
   AND coalesce(content->>'additional_context','')<>'';"
```

Verified 2026-08-19: **2,490 DRAFT · 4 PUBLISHED · 649 CUPE drafts · 237 of them carrying
point-factor context.** That last number is the health signal for a CUPE producer pass,
and it is the ONLY one that distinguishes a good run from a ruined one — `refreshed=50
failures=0` prints identically either way.

⚠ **The box has other Docker projects on it.** A `docker ps` full of random-named
`postgres:16-alpine` / `neo4j:5-community` containers is probably
`C:\repos\recruiter-assistant`'s testcontainers, not ours. Filter by
`label=org.testcontainers=true` and check the session id before concluding anything is
wrong here.

### The queue, in order

1. **Re-run the producer** over the CUPE cohort — the S-2/S-3/S-4 fixes are on `main`
   and no draft in the Bank has seen them. **`--resume` is now safe and correct (#126)**,
   so an interrupted pass is restartable. Check the health signal above, not the
   progress line. Read the ⚠ in ITEM 1 first: resume makes a pass *restartable*, it does
   not make a *re-baseline* happen.
2. **Merge `decision_making` / `problem_solving` / `relationships` in 4.1** — the S-5
   conclusion (`docs/baseline/jdfn-remeasure-2026-08-19.md`). Needs a per-section merge
   policy registered like HR-207. This is the JDFN cohort's missing 18 points, honestly.
3. **Phase F** (`docs/tasks/phase-f-form-scoping-backlog.md`) — search is JDFN-only in
   both directions, and the dashboards report a pre-CUPE world. D3's per-form draft
   evaluation renders nowhere, and it is the number HR will ask for.
4. **Phase G** — the remaining producer + rulebook items in the review findings. The two
   resume items are closed; **counters do not partition**, the **write-once `clusters`
   snapshot**, `--resume --allow-downgrade --no-llm` as a **silent no-op**, and
   **per-cluster member drops being invisible** are still open.
5. 🔴 **TLS at the edge** — still the only genuinely external item. `sfuai.ca:7000` is a
   Telus NAT forward to `192.168.1.80:25800`, plain HTTP on the public internet.
6. **HR ratification** — 208 entries, 0 signed, including the bar that gates publishing.

### The ~90-second check that must precede ANY producer pass

Two passes were started on unverified fixes and both were still wrong. Drive one real
all-CUPE cluster through merge → rewrite and compare. Last clean result:

```
cluster 88c49896 — 132 member JDs
  MERGE  -> group='cupe' template=wjq context=6007 chars
  REWRITE-> group='cupe' template=wjq context=6007 chars  duties=8  score=85.29
```

### ▶ ITEM 1 IN DETAIL — the producer re-run

The S-2/S-3/S-4 fixes are on `main` and **no draft in the Bank has seen them.** Until
this runs, every CUPE draft still loses its duty frequencies and may carry an invented
hiring bar. **Do the ~90-second check first.**

```bash
make canonical-drafts CANONICAL_ARGS="--commit-every 25"
```

⚠ **Start WITHOUT `--resume`, and add it only to continue that same pass after an
interruption.** This is the distinction that matters and it is easy to get backwards:

| | what it does |
|---|---|
| **no `--resume`** | rebuilds every cluster with the new rewrite — **this is the re-baseline you want** |
| **`--resume`** | skips clusters that already HOLD a landed rewrite — including the 2,021 the OLD rewrite wrote |

✅ `--resume` is now correct (#126): it asks whether the rewrite LANDED, so it retries
the 44 whose rewrite failed instead of abandoning them forever. That makes a ~44-hour
pass survivable. It still, correctly, declines to redo work that succeeded — which is
why it is the wrong flag to *open* a re-baseline with.

⚠ `--resume --allow-downgrade --no-llm` is still a silent no-op — resume fires first, the
deliberate re-baseline never happens, and the run exits 0. **Still open (Phase G).**

### ▶ ITEM 2 IN DETAIL — merging the three sections in 4.1

`docs/baseline/jdfn-remeasure-2026-08-19.md` is the argument and the evidence. The work:

1. `merge_cluster` (`core/src/jd_core/bank/merge.py` ~742) currently drops
   `decision_making` / `problem_solving` / `relationships` / `position_number` as "out
   of scope" and flags `sections_not_merged`. Merge the first three.
2. Each needs a POLICY — `drop` / `longest` / union — which is an HR-207-shaped question
   and therefore **a register entry decided in the same PR**, not a quiet default.
   `problem_solving` is the interesting one: only 44.9% of JDFN sources have it, so a
   cluster where half the members carry the section is a real question about what the
   harmonized role should say.
3. It should move `harmonization.yaml` (unhashed), so `rules_version` stays put.
4. Afterwards, `_SECTIONS_NEVER_INVENTED`'s EMPTY-TO-EMPTY rule becomes reachable in
   production for the first time — replace
   `test_a_section_the_grounded_draft_has_is_left_to_the_rewrite`'s hand-built
   `MergedRole` (which `merge_cluster` cannot produce) with a real merge.

### ▶ WHAT THIS SESSION LEARNED THAT IS NOT IN A DIFF

- **A predicate's NAME can be the bug, stated out loud.** `draft_was_llm_written` was
  read by two callers asking two different questions, and it answered a third one ("was
  a client injected"). The rename to `draft_has_rewritten_prose` is most of the fix;
  once the name states the question, the wrong field is visible.
- **A fix's blast radius is the set of its CALLERS, not the bug report.** The review
  found the resume half. The no-DOWNGRADE half — same predicate, opposite direction,
  and the reason the 44 rows were unreachable *at all* rather than merely un-resumable
  — only showed up by grepping for the callers.
- **Quantify against the live Bank before and after.** `2,065 → 2,021` is a claim a
  reviewer can check in one query; "resume now retries failed clusters" is not.
- **The backup was in a dead session's scratchpad and is now not.** A path under
  `AppData\Local\Temp\claude\<session-uuid>\` is unreachable from any other session by
  construction. Anything that must outlive a session goes somewhere durable, and the
  handoff carries the absolute path.

---

## ▶ PREVIOUS (2026-08-19, later) — six review findings fixed and MERGED, S-5 measured

| | |
|---|---|
| `main` | `0beda92` — **#122 and #124 both merged.** Nothing from this session is left unmerged |
| **Open PRs** | **[#121](https://github.com/humanaxiom/jd-assistant/pull/121)** Phase F backlog (docs) — the only one. Verify with `gh pr list`, never from this table |
| Gates | **2,822 passing, 94.16%** — locally and in CI on #124. `register-check` + `guide-check` exit 0. `rewrite-golden` + `gates-live` green against the real model |
| `rules_version` | `+76baba29cfeb` — **still unmoved.** Nothing in #124 changes how a JD is SCORED |
| Register | **208** decisions, **0 ratified** — HR-208 is new (which qualification kinds the rewrite may author) |
| Live data | 2,490 DRAFT + 4 PUBLISHED · **237 CUPE drafts rebuilt, the rest still wrong** |
| Producer run | 🔴 **STILL STOPPED.** The S-2/S-3/S-4 fixes are on `main` now but **have never been re-run**, so every draft in the Bank predates them — see below |

### What #124 fixes, and what it does NOT

`docs/tasks/cupe-review-findings-2026-08-19.md` remains the map. Six of its findings
are now closed:

| | what it was | how it is closed |
|---|---|---|
| **P0-1** | a CUPE author could not Submit or Export — the hidden `form` field was in the *check* form only, so both handlers fell back to JDFN and answered with a pydantic error page that wiped everything typed | the field is on all three forms; the CSRF template scanner moved to `tests/unit/template_scan.py` and now asks the same question of `form`; the round trip is driven **from the rendered HTML** (`_browser_pairs`), because every test that synthesises its own POST body supplies the field the page forgets |
| **P0-2** | `_split_context_blocks` dropped everything before the first canonical heading, and dropped a context with no recognised heading entirely — while its docstring claimed the opposite twice | the preamble opens the first section; the inverted test now tests what its name says, with the no-heading case, the mixed case and a control |
| **S-1** | a posted `employee_group` chose the ruleset AND the numeric profile: `apsa` → 59.38/D/four gates, `cupe` → 89.05/B/**approved** | `FormSpec.assemble_checked` — assemble, then ask `template_of`, the same question the validator asks. Every seam crosses it: check, assist, submit, export, clone |
| **S-2** | the rewrite could delete most of a role; the change log reported `removed: []` and `rendered_draft` showed the merge's twelve duties over a row holding three | `removed_duties` asks the other direction on the same threshold; the packet renders **the draft that will be stored** |
| **S-3** | the model could invent `PhD in Astrophysics required` on a clerical CUPE draft, with an empty record | `rewrite.rewritable_qualification_kinds` (HR-208, `open`). The bars come back from the merge; the swap is recorded in `restored_bars` |
| **S-4** | `SFUDuty.frequency` destroyed on every CUPE draft — structural, 100%, invisible to the top-level completeness pin | each rewritten duty is matched to its merge duty and carries the frequency back |

**None of this has reached the live Bank.** The code is on `main`, but the producer has
not re-run since — so all 237 rebuilt CUPE drafts were written by the OLD rewrite and
still lose duty frequencies and may carry invented bars. **Merging the fix is not the
same as fixing the data.** Re-running the producer is what makes them real.

### 🔴 S-5 — MEASURED. The guard is not the defect; the 4.1 merge is.

**`docs/baseline/jdfn-remeasure-2026-08-19.md` has the numbers and the argument.** The
headline, measured against the live Bank:

| JDFN drafts | count | with `decision_making` | mean score |
|---|---:|---:|---:|
| written **before** the section guard | 1,156 | 1,084 (93.8%) | **84.61** |
| written **after** it | 685 | 0 | **66.42** |

`SFU-COMP-DECISION` / `-PROBLEM` / `-RELATIONSHIPS` went from ~6% of JDFN drafts to
**100%**. Every grade-B JDFN draft in the Bank is a pre-guard one.

**But loosening the guard would be wrong.** The rewrite is fed `_flatten_jd(merged.draft)`
and nothing else, and that draft's `decision_making` is always empty — so the 1,084
pre-guard sections were invented from *no source at all*. The 18.19 points are
fabrication being withdrawn, not a regression. Re-permitting it on JDFN restores an
18-point lift made of invented content, on the surface where HR-208 was just closed for
exactly that.

**The real defect is one layer up: 97.0% of JDFN source documents carry
`decision_making` and 97.4% carry `relationships`, and the 4.1 merge drops all of it as
"out of scope".** So no JDFN draft the pipeline produces can ever be complete. Merging
those three sections in 4.1 fixes the guard's input rather than the guard, makes the
EMPTY-TO-EMPTY protection reachable in production for the first time, and brings the
points back honestly. It needs a merge policy per section — an HR-207-shaped question,
so a register entry decided in the same PR. **Not implemented: it changes the whole JDFN
cohort's output and it is a policy call.**

### The original S-5 framing, for reference

The review flags that "JDFN is the untouched control" is false. **Confirmed against the
code, not the commit message:** `merge_cluster` deliberately never populates
`decision_making` / `problem_solving` / `relationships` for *anyone*
(`bank/merge.py` ~line 742), so `_SECTIONS_NEVER_INVENTED`'s antecedent — "the grounded
draft does not have this section" — is **true on every real cluster of every template**.
The guard therefore empties those sections on JDFN drafts too, where the JDFN form
legitimately HAS them.

Two consequences, and the second is the one to decide:

1. Every JDFN rewritten draft since Phase D carries findings it did not before. **Do not
   quote any JDFN number until it is re-measured** (the 1,804-draft / mean 52.73 figures
   are pre-Phase-D and not comparable).
2. The guard is not template-scoped, and it should be — `FormSpec.sections` already
   declares which sections each form HAS, which is the same axis as `applies_to` and
   `thresholds_for`. Fixing it changes what a producer re-run produces for the **whole
   JDFN cohort**, so it is a decision to take deliberately, not a tidy-up.

⚠ The existing test `test_a_section_the_grounded_draft_has_is_left_to_the_rewrite`
hand-builds a `MergedRole` whose draft has `problem_solving`. `merge_cluster` cannot
produce that, so the "EMPTY-TO-EMPTY only" protection it pins is **unreachable in
production**. That is why the defect survived a green suite.

### ▶ IF YOU ARE STARTING COLD, DO THESE FOUR THINGS FIRST

```bash
git fetch && git log --oneline origin/main -1     # expect 0beda92 or later
gh pr list                                        # the table above lags; this does not
docker ps --filter "name=canonical-run"           # MUST be empty before any producer work
docker compose exec -T postgres psql -U app -d harness -t -c \
  "SELECT count(*) FROM canonical_jds WHERE status='DRAFT' \
   AND coalesce(content->>'additional_context','')<>'';"
```

Verified 2026-08-19 20:5x UTC: **2,490 DRAFT · 4 PUBLISHED · 649 CUPE drafts · 237 of
them carrying point-factor context.** That last number is the health signal for a CUPE
producer pass, and it is the ONLY one that distinguishes a good run from a ruined one —
`refreshed=50 failures=0` prints identically either way.

🔴 **THE BACKUP IS IN A DEAD SESSION'S SCRATCHPAD.** A fresh session's scratchpad is a
different directory, so it will not find it by convention. The verified `-Fc` dump of the
Bank (77.6 MiB, taken before the full LLM run) is at:

```
C:\Users\adam\AppData\Local\Temp\claude\c--repos-JD-Assistant\
  b59bc387-f7e3-451d-ae54-2a947281a9c6\scratchpad\harness-pre-full-llm-run.dump
```

**It is in a temp directory and nothing guarantees it survives.** Copy it somewhere
durable before touching the producer. And when restoring: a full `-Fc` dump into an
EMPTY database — `pg_restore --data-only` wipes the Bank and exits 0.

### The queue, in order

1. **Re-run the producer** over the CUPE cohort — the S-2/S-3/S-4 fixes are on `main`
   and no draft in the Bank has seen them. Check the health signal above, not the
   progress line. ⚠ 🕐 SUPERSEDED by #126 — see the current START HERE section.
2. **Merge `decision_making` / `problem_solving` / `relationships` in 4.1** — the S-5
   conclusion (`docs/baseline/jdfn-remeasure-2026-08-19.md`). Needs a per-section merge
   policy registered like HR-207. This is the JDFN cohort's missing 18 points, honestly.
3. **Phase F** (`docs/tasks/phase-f-form-scoping-backlog.md`) — search is JDFN-only in
   both directions, and the dashboards report a pre-CUPE world. D3's per-form draft
   evaluation renders nowhere, and it is the number HR will ask for.
4. **Phase G** — the producer and rulebook lists in the review findings. One of them
   (`--resume` abandoning rewrite-failed clusters) blocks item 1 from being resumable.
   🕐 **That one is CLOSED (#126).**
5. 🔴 **TLS at the edge** — still the only genuinely external item. `sfuai.ca:7000` is a
   Telus NAT forward to `192.168.1.80:25800`, plain HTTP on the public internet.
6. **HR ratification** — 208 entries, 0 signed, including the bar that gates publishing.

### The ~90-second check that must precede ANY producer pass

Two passes were started on unverified fixes and both were still wrong. Drive one real
all-CUPE cluster through merge → rewrite and compare. Last clean result:

```
cluster 88c49896 — 132 member JDs
  MERGE  -> group='cupe' template=wjq context=6007 chars
  REWRITE-> group='cupe' template=wjq context=6007 chars  duties=8  score=85.29
```

### ▶ ITEM 1 IN DETAIL — the producer re-run

The S-2/S-3/S-4 fixes are on `main` and **no draft in the Bank has seen them.** Until
this runs, every CUPE draft still loses its duty frequencies and may carry an invented
hiring bar.

**Do the ~90-second check first** (below) — two earlier passes were started on unverified
fixes and both produced garbage for half an hour before anyone noticed.

```bash
make canonical-drafts CANONICAL_ARGS="--commit-every 25"
```

> 🕐 **SUPERSEDED by #126 — historical record, do not follow.** The abandonment half of
> this warning is FIXED: `--resume` now keys on "the rewrite landed". The rest still
> holds — resume skips drafts the LLM already wrote, so it is still the wrong flag to
> OPEN a re-baseline with. See the current START HERE section.

⚠ **Do NOT add `--resume`.** It skips drafts the LLM already wrote — which is *every
corrupted one* — and it permanently abandons clusters whose rewrite failed, because it
keys on "a client was injected" (`pipeline.llm_enabled`) rather than "the rewrite
landed". The clusters that most need retrying are exactly the ones it can never retry.
Fixing that (key on `rewrite_ran` / `not rewrite_failed`) is a Phase G item and it is
what would make this pass resumable; a full pass is ~44 hours without it.

⚠ `--resume --allow-downgrade --no-llm` is a silent no-op — resume fires first, the
deliberate re-baseline never happens, and the run exits 0.

### ▶ ITEM 2 IN DETAIL — merging the three sections in 4.1

`docs/baseline/jdfn-remeasure-2026-08-19.md` is the argument and the evidence. The work:

1. `merge_cluster` (`core/src/jd_core/bank/merge.py` ~742) currently drops
   `decision_making` / `problem_solving` / `relationships` / `position_number` as "out
   of scope" and flags `sections_not_merged`. Merge the first three.
2. Each needs a POLICY — `drop` / `longest` / union — which is an HR-207-shaped question
   and therefore **a register entry decided in the same PR**, not a quiet default.
   `problem_solving` is the interesting one: only 44.9% of JDFN sources have it, so a
   cluster where half the members carry the section is a real question about what the
   harmonized role should say.
3. It should move `harmonization.yaml` (unhashed), so `rules_version` stays put.
4. Afterwards, `_SECTIONS_NEVER_INVENTED`'s EMPTY-TO-EMPTY rule becomes reachable in
   production for the first time — replace
   `test_a_section_the_grounded_draft_has_is_left_to_the_rewrite`'s hand-built
   `MergedRole` (which `merge_cluster` cannot produce) with a real merge.

### ▶ WHAT THIS SESSION LEARNED THAT IS NOT IN A DIFF

- **For a multi-form surface, test the PAGE, not the handler.** P0-1 survived four new
  tests because each built its own request body and supplied the field the page forgot.
  `core/tests/unit/template_scan.py` + `_browser_pairs` in `test_compose_ui.py` are the
  durable shape; the CSRF scanner had been asking exactly this question of one field
  since Phase 8 and nobody generalised it.
- **A guard's own test can be unreachable in production.** Two of them were: the
  EMPTY-TO-EMPTY section test hand-builds a `MergedRole` the merge cannot produce, and
  `test_unrecognised_context_text_is_kept_rather_than_dropped` asserted the opposite of
  its own name. Both were green. When a test constructs its own fixture rather than
  driving the real producer, ask whether the shape it built can actually occur.
- **Measure before accepting a review's fix.** S-5's stated remedy — scope the section
  guard to CUPE — would have restored an 18-point score lift made of content the model
  invented from nothing. The review's *finding* was right and its *fix* was backwards,
  and only the query told the difference.
- **`make gates` locally before every commit, and the live goldens after any rewrite or
  prompt change.** `make rewrite-golden` + `make gates-live` both ran green this session
  against `aria-gb10-2`; they are excluded from `make gates` by design and CI can never
  run them.

### One correction to the review findings doc

It states the v4 whole-archive run put the CUPE cohort at **4,300** and that 4,440 is the
v3 count. Measured directly against `parsed_jds` at `jd_segmenter_v4` on 2026-08-19:

```
apsa 4946 · (none) 4630 · cupe 4440 · apex 420 · poly 50 · excluded 36   (= 14,522)
```

So **4,440 is the v4 count**, and the register's population line (HR-202/204/205) may be
right after all. The "register population splice" item in the review needs re-checking
before anyone edits those entries — 4,300 is the number with no provenance here.

### Process notes worth keeping

- **The live goldens were silently skipping.** `make rewrite-golden` printed
  `✅ complete` having run nothing, because the probe attempted a completion with a 30s
  timeout and the GPU was busy. Fixed (`98f284a`) to probe `/api/tags` instead — the
  distinction is *unreachable* (skip correctly) vs *busy* (skipping is a lie). Nine live
  tests now genuinely run. Run them after any rewrite/prompt change; `make gates`
  excludes them by design. **#124 changes the rewrite pass, so run them before merging.**
- **For a multi-form surface, test the PAGE, not the handler.** P0-1 survived four new
  tests because each built its own request body. `tests/unit/template_scan.py` +
  `_browser_pairs` are the durable shape.
- **Multi-agent review is worth the tokens.** Six reviewers found two P0s, a security
  amplifier and a vacuous test in ~10 minutes each. Reviewers are always Opus (CLAUDE.md).
  Tell them to verify against the code, not the commit messages — this repo's docstrings
  are assertive and were wrong in at least six places, and one of those (the
  EMPTY-TO-EMPTY claim above) is still live.

---

## ▶ PREVIOUS (2026-08-19, earlier) — CUPE shipped, then six reviewers found what one pair of eyes missed

| | |
|---|---|
| `main` | `2143fb6` — Phases C, D, E and two rounds of fixes (#112 → #120) |
| **Open PRs** | **[#121](https://github.com/humanaxiom/jd-assistant/pull/121)** Phase F backlog (docs) · **[#122](https://github.com/humanaxiom/jd-assistant/pull/122)** the eval fix + user/architecture docs + the two review fixes. Verify with `gh pr list`, never from this table |
| Gates | **2,802 passing, 94.14%** on #122. `register-check` + `guide-check` exit 0 |
| `rules_version` | `+76baba29cfeb` — unmoved since Phase C |
| Register | **207** decisions, **0 ratified** |
| Live data | 2,490 DRAFT + 4 PUBLISHED · **237 CUPE drafts rebuilt, the rest still wrong** |
| Producer run | 🔴 **STOPPED DELIBERATELY.** Do not restart until P0/S fixes land — see below |

### 🔴 READ THIS FIRST — the CUPE Builder is broken, and the Bank is half-rebuilt

**`docs/tasks/cupe-review-findings-2026-08-19.md` is the most important document in the
repo right now.** Six adversarial reviewers went over Phases B–E, which shipped in one
weekend orchestrator-only with no second reviewer. They found ~30 issues. Two are P0:

1. **A CUPE author cannot submit or export.** The hidden `form` field is in the *check*
   form only; Submit and Export are separate `<form>` elements, so both fall back to JDFN
   and fail to parse the WJQ answers. The author's typed content is wiped from the page.
   **The whole Phase E journey ends at an error box.** Four new WJQ UI tests missed it
   because each synthesised its own POST body, supplying the field the page forgets.
2. **An inverted test certifies live data loss** —
   `test_unrecognised_context_text_is_kept_rather_than_dropped` asserts the text *was*
   dropped. It would go red if the bug were fixed.

Then, in order: an author can pick their own approval bar via `employee_group`; the rewrite
can delete most of a role with the change-log reporting nothing removed; it can invent
education/experience/security bars; `SFUDuty.frequency` is destroyed on every CUPE draft.

**⚠ And a claim made repeatedly in this repo is false: "JDFN is the untouched control."**
`_SECTIONS_NEVER_INVENTED` fires on both forms, so every JDFN rewritten draft since Phase D
carries findings it did not before. **Re-measure before quoting any JDFN number.**

### Before restarting the producer

```bash
docker ps --filter "name=canonical-run"     # must be empty
docker compose exec -T postgres psql -U app -d harness -t -c \
  "SELECT count(*) FROM canonical_jds WHERE status='DRAFT' \
   AND coalesce(content->>'additional_context','')<>'';"
```

That count is the health signal — **237** when the run was stopped, out of ~649 CUPE
drafts. A progress line reading `refreshed=50 failures=0` looks identical whether the drafts
are right or ruined; that is how two earlier passes ran for half an hour producing garbage.

**Do not restart until at least S-2/S-3/S-4 are fixed** — the run would otherwise keep
producing drafts that lose duty frequencies, can lose duties wholesale, and can carry
invented hiring bars. A verified `-Fc` backup is at
`…/scratchpad/harness-pre-full-llm-run.dump` (77.6 MB).

⚠ **`--resume` will not do what you want.** It skips drafts the LLM already wrote, which
includes every corrupted one, and it permanently abandons clusters whose rewrite failed
(it keys on "a client was injected", not "the rewrite landed").

### The ~90-second check that must precede ANY producer pass

Two passes were started on unverified fixes and both were still wrong. Drive one real
all-CUPE cluster through merge → rewrite and compare. Last clean result:

```
cluster 88c49896 — 132 member JDs
  MERGE  -> group='cupe' template=wjq context=6007 chars
  REWRITE-> group='cupe' template=wjq context=6007 chars  duties=8  score=85.29
```

### What landed, and what it cost

Phases C/D/E made the two SFU forms real on four axes — `applies_to` (which rules judge a
form), `thresholds_for` (which numbers), `templates_harmonized` (which forms get drafted,
HR-206), `FormSpec` (what a form consists of) — all keyed on `JDTemplate`, all resolved from
the document's own `employee_group` via `template_of`. **649 CUPE roles have drafts** where
they had none, and the Builder offers both forms.

The measured result, per form, never blended (from the deterministic pass — **stale, and
not comparable to any LLM-written figure**): jdfn 1,804 drafts, mean 52.73, 179 approvable ·
wjq 649 drafts, mean 71.69, 3 approvable.

**Four defects this weekend were found by running things against the live Bank, not by
reading or testing** — the `--no-llm` downgrade of 1,763 drafts (recovered from backup), and
three ways a CUPE draft stopped being a CUPE draft. Gates were green through every one.

### The queue, in order

1. **P0-1 and P0-2** from the review findings — the Builder cannot complete a draft.
2. **S-1 → S-4**, then re-measure JDFN (S-5).
3. **Phase F** (`docs/tasks/phase-f-form-scoping-backlog.md`) — search is JDFN-only in both
   directions, and the dashboards report a pre-CUPE world (`+90af5e27dc83` vs the shipped
   `+76baba29cfeb`). D3's per-form draft evaluation renders nowhere, and it is the number HR
   will ask for.
4. **Phase G** — the producer and rulebook lists in the review findings.
5. 🔴 **TLS at the edge** — still the only genuinely external item. `sfuai.ca:7000` is a
   Telus NAT forward to `192.168.1.80:25800`, plain HTTP on the public internet. It dropped
   once on 2026-08-19 and recovered; the app, the firewall and DNS were all verified healthy,
   so the fragility is the forward itself and the non-standard port through SFU VPN.
6. **HR ratification** — 207 entries, 0 signed, including the bar that gates publishing.

### Process notes worth keeping

- **The live goldens were silently skipping.** `make rewrite-golden` printed
  `✅ complete` having run nothing, because the probe attempted a completion with a 30s
  timeout and the GPU was busy. Fixed (`98f284a`) to probe `/api/tags` instead — the
  distinction is *unreachable* (skip correctly) vs *busy* (skipping is a lie). Nine live
  tests now genuinely run. Run them after any rewrite/prompt change; `make gates` excludes
  them by design.
- **Multi-agent review is worth the tokens.** Six reviewers found two P0s, a security
  amplifier and a vacuous test in ~10 minutes each. Reviewers are always Opus (CLAUDE.md).
  Tell them to verify against the code, not the commit messages — this repo's docstrings are
  assertive and were wrong in at least six places.

---

## ▶ PREVIOUS (2026-08-17) — CUPE Phases C, D and (half of) E

| | |
|---|---|
| `main` | `5cef633` — **#112** (Phase C) · **#113** (D1+D2) · **#114** (docs scrub) · **#115** (D3 + the guard + D5 + `--resume`) |
| **Open PRs** | **none merged-and-pending as of this write** — the Phase E branch `feat/cupe-phase-e-wjq-builder` is **pushed with 2 commits but its PR was NOT opened**: GitHub's API was 503ing. ⚠ **OPEN IT FIRST.** `git log origin/main` is the check, not a badge |
| Gates | **2,784 passing, 94.13%** on the E branch (`main` is 2,772). `register-check` in step |
| `rules_version` | `+76baba29cfeb` — **UNMOVED since Phase C.** D and E changed how drafts are *assembled* and *authored*, never how one is *scored*: `harmonization.yaml` and `rewrite.yaml` are unhashed, and the WJQ builder rides in `additional_context` rather than extending `SFUSection` |
| Register | **206** decisions, **0 ratified** — HR-206 (which FORMS the Bank drafts) is the new one. HR-180's default moved to `jd_harmonize_v2` |
| Live data | 14,565 files · 14,522 parsed at v4 · **2,494 canonical JDs** (was 1,804) · **4 published** · a **~12h LLM pass is RUNNING** — see below |

### 🔴 THE CUPE DRAFTS ARE BEING REBUILT RIGHT NOW (started 2026-08-18)

**A full producer pass is RUNNING** — all 2,456 clusters, ~43h, finishing Wednesday.
Until it completes the Bank holds a MIX of correct and known-wrong CUPE drafts.
**Do not show a CUPE draft to HR until it finishes**, and check before starting anything
else against this database:

```bash
docker ps --filter "name=canonical-run"          # is it still going?
docker compose exec -T postgres psql -U app -d harness -t -c \
  "SELECT count(*) FROM canonical_jds WHERE status='DRAFT' \
   AND coalesce(content->>'additional_context','')<>'';"
```

**That second number is the health check, not the cluster tally.** It was 0 when the run
started and climbs as CUPE clusters are rebuilt. A progress line reading
`refreshed=50 failures=0` looks identical whether the drafts are right or ruined — which
is exactly how two earlier passes ran for half an hour producing garbage.

Stopping the run is safe (`--resume` continues it, though see the caveat below).

#### What was wrong, and what fixed it

Three defects, all found by **probing the live Bank** — cloning one real CUPE role and
checking the result against its sources. None was reachable by reading the code; none
would have failed a test.

| | what was wrong | fixed in |
|---|---|---|
| the merge dropped **7 of the WJQ's 14 sections** | JDFN's `additional_context_policy: drop` was applied to the field where the WJQ keeps its point-factor blocks. 95.4% of CUPE sources carry it (avg 5,524 chars); **0 of 553 drafts had any** | [#117](https://github.com/humanaxiom/jd-assistant/pull/117) — HR-207, per-template policy |
| the rewrite **stripped the form** | the model returned `employee_group: null`, so the draft silently moved to the JDFN bar. Of ~100 refreshed, **5** kept their group | [#117](https://github.com/humanaxiom/jd-assistant/pull/117) |
| the rewrite **deleted the sections again** | the merge fix landed and the very next run threw the content away: the prompt's schema shows `"additional_context": null` | [#118](https://github.com/humanaxiom/jd-assistant/pull/118) |

**#118 is the one to read.** Three fields in three days meant the patch was the wrong
shape: the pass was built as *"the model returns a JD, we scrub what it ADDED"* and
nothing policed what it **REMOVED**. `_REWRITABLE_FIELDS` is now an ALLOW-LIST of the
seven prose fields; everything else is restored from the grounded merge draft, and a
completeness pin over `SFUJobDescription.model_fields` makes the next field an argued
decision instead of a silent one.

#### The verification to run before ANY future producer pass

Both earlier attempts were started on fixes that had not been checked end to end, and
both were still wrong. The check costs ~90 seconds: drive ONE real all-CUPE cluster
through merge → rewrite and compare. The last run of it, before this pass:

```
cluster 88c49896 — 132 member JDs
  MERGE  -> group='cupe' template=wjq context=6007 chars
  REWRITE-> group='cupe' template=wjq context=6007 chars  duties=8  score=85.29
  VERDICT: PASS — form and sections intact
```

⚠ **`--resume` asks the wrong question.** It skips drafts the LLM already wrote, when
what you usually want is "redo whatever predates the current merge policy". It cannot
ask that: `harmonization.yaml` is unhashed, so `rules_version` does not move when the
policy changes. The fix is to stamp the draft with the harmonization identity that built
it (`harmonize_stamp` already computes one) — **not built, and the reason resume was not
used for this pass.**

### 🔴 READ THIS BEFORE TOUCHING THE LIVE BANK

**A long LLM producer run may still be in flight.** It is resumable and crash-safe
(`--resume`, commits every 25 clusters), so **stopping it is safe** — but starting a
second producer against the same database is not. Check first:

```bash
docker ps --filter "name=canonical-run"
docker compose exec -T postgres psql -U app -d harness -t -c \
  "SELECT count(*) FROM canonical_jds WHERE status='DRAFT' AND COALESCE(change_log->'pipeline'->>'llm_enabled','false')<>'true';"
```

That count is **how much work is left**; it was 684 when the run started. When it reaches
~0 the pass is done. Re-run with `make canonical-drafts CANONICAL_ARGS="--resume"` to
continue after any interruption.

### 🔴 THE MISTAKE OF THIS SESSION, because the lesson generalizes

**`make canonical-drafts CANONICAL_ARGS="--no-llm"` was run against the populated live
Bank.** It produced the 649 CUPE drafts it was meant to — and it also **refreshed 1,763
untouched JDFN drafts**, discarding the 4.2a rewrite on every one. The cohort's mean score
fell **73.0 → 52.73 in thirty-two seconds**, reported only as `drafts_refreshed`, a word
that reads like an improvement.

- **Recovered in full.** A `-Fc` dump taken immediately before the run restored 1,746 of
  them exactly (the other 52 had already been re-upgraded); each carries a
  `canonical_draft.restored_from_backup` audit row. Nothing published or reviewer-touched
  was ever at risk — the no-clobber rule held throughout.
- **The lesson: the no-clobber rule protected HUMAN work and said nothing about PIPELINE
  work.** That was a fair place to stop while every run was a full run. It stopped being
  fair the moment the producer had a cheap mode, and nobody noticed because until CUPE
  there was no reason to run `--no-llm` on a full Bank.
- **Now guarded.** A deterministic run refuses to overwrite an LLM-written draft
  (`skipped_would_downgrade` + an audit row); `--allow-downgrade` does it deliberately.
- **And the standing rule that earned its keep: take the `-Fc` dump before ANY producer
  run against the live Bank** (`docs/runbooks/backup-and-restore.md` §2). It cost nothing
  and made a mistake a choice rather than an incident.

### What landed, in one screen

| | |
|---|---|
| **C** (#112) | The numeric thresholds are per-template. `duties_max` **12** for the WJQ (HR-202…205) |
| **D1** (#113) | **The Bank drafts CUPE roles** — HR-206, a PRIORITY list so a mixed cluster still authors JDFN. 657 clusters had been skipped entirely |
| **D2** (#113) | 🔴 The rewrite prompt inlined *"3–5 major duties"* — on a twelve-slot form that **deletes most of a CUPE role**, and nothing downstream objects (the guard stops *additions*, and `duties_min` is 3). Now `jd_harmonize_v2` reads the drafted form's own profile |
| **D3** (#115) | Per-form evaluation, and **no top-level score field exists at all** — the blended number is unavailable, not merely discouraged |
| **D5** (#115) | The review queue and detail page name the FORM, because the score beside it is not the same measurement for both |
| **E** (branch) | The `FormSpec` registry + the whole WJQ answer contract, assembler and question set. **UI wiring NOT done** — see below |

### The measured result — per form, never blended

| form | drafts | mean | approvable | grades |
|---|---|---|---|---|
| jdfn | 1,804 | 52.73 | 179 | C 848 · D 434 · F 522 |
| wjq | **649** | **71.69** | 3 | **B 351** · C 155 · D 137 · F 6 |

⚠ **Both cohorts were DETERMINISTIC when this was measured** (it is the `--no-llm` run's
own output), so the two are comparable *to each other* but **not** to the 73.0 in older
notes, which was LLM-rewritten. Re-measure after the LLM pass finishes; the producer
prints the table.

### Phase E — what is done and what is next

**Done** (`feat/cupe-phase-e-wjq-builder`): the spike measurement, `FormSpec` + the
registry, `WJQAnswers`, `assemble_wjq_jd`, the 14-section WJQ question set, and
`render_kind`.

**✅ ALSO DONE — the UI is wired** (`8af3932`): `/new?form=wjq` walks the CUPE
questionnaire, the picker names both forms, and every UI helper derives from the answer
contract instead of hand-written name sets. Duty columns are keyed by TARGET now
(`duties_verb`, not `duty_verb`) because the WJQ has two duty-shaped sections.

**✅ AND THE CLONE MAPPING IS DONE TOO** — `FormSpec.clone_from_jd`, so `form_for(jd)`
picks the contract from the JD itself and a CUPE role clones into the WJQ flow. The
point-factor sections round-trip through `additional_context` by the parser's own heading
vocabulary, pinned field by field.

**Phase E is complete.** Nothing on the CUPE track is outstanding except what is HR's.

⚠ **One thing to know if you touch the JSON clone route:** `response_model=None` on
`GET /jd-bank/compose/clone/{id}` is load-bearing. FastAPI derives the response model
from the RETURN ANNOTATION when none is given and filters the response down to it, so
annotating the shared `AnswerContract` base served every clone as just that base's one
field — the JDFN route silently lost `title`. Pinned by a test.

**Two things settled that the next session should not re-open:**

- **The WJQ sections ride in `additional_context`, mirroring the parser** — that is what
  makes an authored CUPE JD and a parsed one the same shape, and it is why `SFUSection`,
  the rule catalog and 8.3c's `_SECTION_ANCHORS` pin are all untouched.
- **`employee_group` is fixed by the assembler, never asked**, because it is what selects
  the bar the draft is judged against.

**Still HR's, not ours:** HR-194 (may the Builder *author* CUPE — this is scope, and the
branch ships the capability the way Phase B established, registered and unratified) and
HR-201 (does SFU's boilerplate apply to a form that has no such block).

---

## ▶ PREVIOUS (2026-08-13) — the state of the world in one screen

> **⚠️ A NOTE ON THE PREVIOUS VERSION OF THIS BLOCK, because the failure will recur.**
> It said *"Open PRs: none"* and marked `embed_stamp` parity **✅ CLOSED (#99)** while **#99 and
> #101 were both still OPEN**, and #101 did not even merge cleanly. The block was written when
> the PRs were *filed*, describing the intended end state as the actual one. **A handoff that
> records intent as outcome is worse than one that is merely out of date** — the next session
> reads "closed" and never checks. `gh pr list` costs seconds; this block is now written only
> from its output.

| | |
|---|---|
| `main` | `c203ad5` — **#110** (CUPE Phase B, `applies_to`) and **#111** (the STEP BACK reset + the commit #110's merge dropped) |
| **Open PRs** | **[#112](https://github.com/humanaxiom/jd-assistant/pull/112) — CUPE Phase C**, the per-template numeric profiles (HR-202…205). Gates green locally; merge before starting D so nothing stacks on an open branch |
| Gates | **2,737 passing, 94.06%** on the #112 branch (`main` itself was 2,726). `register-check` + `guide-check` exit 0 — ⚠ `guide-check` needs **Git Bash**; PowerShell has no POSIX `diff` and it fails `Error 255` there |
| `rules_version` | 🔔 **MOVED TWICE — `+90af5e27dc83` → `+a4c5e2d0f0f3` (B) → `+76baba29cfeb` (C)**, verified each time. `rule_catalog.yaml` and `thresholds.yaml` are both hashed. It had held still through **every** PR since P0.1b-i; B and C are the first changes that genuinely alter what the rulebook says |
| Register | **205** decisions, **0 ratified** — HR-200 context cap · HR-201 the CUPE boilerplate call (**which decides CUPE approvability outright, not score**) · **HR-202…205 the WJQ numeric profile**. 265 surface parameters, all accounted for |
| Live data | 14,565 files · **14,522 parsed at `jd_segmenter_v4`** (v1–v3 rows retained) · 1,803 roles · **4 published** · `review_actions` 6 · one cluster now has TWO versions (someone edited a published JD on 2026-08-13), which is what finally gave 8.3a live surface |

### What changed this session, in one paragraph

The system now **enforces the invariant everything else assumes** — nothing publishes
without an authenticated, authorized human — and it can be deployed in a posture that
refuses to run unsafely. A person can also now use it without hitting a dead end. The
phase record is `docs/plan.md` §Phase 9; the ordered triage it came from is
`docs/tasks/architecture-review-response-2026-08-07.md` §6.

### The four habits this session earned — they matter more than the fixes

1. **Enumerate from the live artifact, never a hand-maintained list.** The authorization
   matrix walks the real routing table; the compose-delivery pin derives its set from a real
   refusal message; the link crawl globs the template directory. Every one of those was
   written *after* a control shipped green over a hole.
2. **Prove the net fails before trusting it.** Every safety net added here was mutated and
   watched go red first. The link crawl, the loopback-port check, the CSRF stale-tab page,
   the `/ready` bound, both login-round-trip controls.
3. **Ask "is this *offered*?", not only "is this *refused*?"** The authorization matrix was
   correct on all 51 routes while a new user's very first click was a link to a `403`. **A
   correct gate on a link nobody should have been shown is still a defect, and no gate test
   can see it.**
4. **A control is not shipped until it is reachable from the documented deployment path.**
   P0.2's guard was a complete no-op (`ENVIRONMENT` reached zero of fourteen containers) and
   P0.4 had two defects — a mistyped Neo4j setting and a healthcheck reading a variable that
   does not exist inside its container — and **all three were found by deploying, not by
   reading.**

> ### ⚠️ And one about git: a merge went somewhere nobody looked
>
> **PR #87 was merged into `chore/hr-docs-and-backlog`, not into `main`.** It was opened
> against that branch deliberately (so its diff showed only P0.0 while #86 was still open),
> on the expectation that GitHub would retarget it when #86 merged. **It did not** — #86 was
> *squash*-merged, which leaves a dependent PR pointing at a branch that still exists. Both
> PRs then reported `MERGED` and **`main` had none of P0.0**. It was re-landed as #88
> (cherry-picked; `git diff` against the CI-green commit was empty).
>
> **The rule:** *`MERGED` names a base, not a destination.* After a merge, read
> `git log origin/main` — not the badge. **Do not stack a PR on a branch that will be
> squash-merged**; if you must, rebase onto `main` and retarget the base once it lands.

### ⚠️ Things about the RUNNING system you must know before touching it

1. ~~**`CAS_SERVICE_BASE_URL` points at `sfuai.ca:7000`, so localhost sign-in is broken.**~~
   ✅ **FIXED by P0.3.** The repo-root `.env` now carries
   `ALLOWED_SERVICE_ORIGINS=http://localhost:25800,http://sfuai.ca:7000` and **both origins
   sign in at once** — verified live against the running api. `CAS_SERVICE_BASE_URL` is
   untouched (still the forward) and is now only the *fallback*. A copy of the `.env` as
   it was before this line was added is at `/tmp/env.before-p03`.
2. **🔴 `sfuai.ca:7000` IS INTERNET-FACING — confirmed 2026-08-13.** So the app is served
   over **plain http at a public name**, and session cookies and CAS tickets — live
   credentials — cross the open internet in the clear. `environment=development`, so
   **P0.2's fail-closed guard is inactive on the one deployment that most needs it.**
   The data stores were on `0.0.0.0` with the committed `app`/`harnesspass` credentials;
   **they are now bound to `127.0.0.1`**, in compose and in the running containers.
   TLS at the edge is a deployment decision nothing in this repo can make.
   **P0.4 (#90) builds the production posture and proves it works — but the live demo is
   still the DEV stack.** Deploying `docker-compose.prod.yml` is a person's decision: it
   needs a certificate, real secrets, and a call on `JD_API_BIND`.
3. **`docker compose exec api pytest` is NOT a valid gate on this box.** The repo-root `.env` sets
   `CAS_ENABLED=true`, the `api` service inherits it, and 9 unit tests fail spuriously. The
   hermetic `gates` service pins the posture. **Always `make gates`.**
4. **The repo-root `.env` leaks into `gates` for anything not pinned.** P0.3 found this the
   hard way: a test asserting the CAS fallback origin failed on the dev box and would have
   passed in CI, because `.env` points `CAS_SERVICE_BASE_URL` at the live forward. Those two
   keys are pinned now; **if you write a test that reads a setting, check it is pinned in the
   `gates` service before trusting either colour.**

### The queue, in order

> ### ⟵ NEXT: Phase F — the two forms have to reach the SEARCH and the REPORTING
>
> Scoped 2026-08-19 from the Builder's own CUPE page:
> **`docs/tasks/phase-f-form-scoping-backlog.md`**. Needs no HR ruling.
>
> * **F1** — `composer/search.py` still excludes CUPE in FOUR places
>   (`_NON_JDFN_GROUP`), so an author in CUPE mode searching "start from an existing
>   JD" gets **zero CUPE results** and can only clone from the other form — which then
>   silently switches them into the JDFN Builder. Correct when the Builder was JDFN-only;
>   backwards since Phase E.
> * **F2** — the baseline + cluster dashboards were generated at `+90af5e27dc83`, which is
>   **pre-Phase-B**, so every WJQ number on them was scored against the JDFN bar. The page
>   still says CUPE has "no JDFN approval bar", which B and C made false. And **D3's
>   per-form draft evaluation renders nowhere** — `evaluation_by_template` lives only in
>   `docs/canonical/summary.json`, and it is the number HR will actually ask for.
>
> ⚠ Re-run `make baseline` AFTER the CUPE rebuild finishes — they contend for Postgres.


**Everything the 2026-08-07 review raised is now closed** (P0.1a #82 · P0.2 #83 ·
P0.1b-i #85 · P0.0 #88 · P0.3 #89 · P0.4 #90 · P0.1b-ii #91 + #92). What is left is what
was always the real critical path — and the first item is not a commit.

> ### ⚠️ 2026-08-14 — STEP BACK, and read this before picking up a CUPE task
>
> **The last six days found real defects, and then kept looking.** Phase B alone ran three
> rounds of *check the claim behind the claim*. Each found something true; none shipped a
> capability. **We started arguing whether a bar was philosophically correct instead of
> making the bar data and moving on.**
>
> **The rule from here: measure ONCE to set a default, register it `open`, build.** If a
> number is wrong HR changes a YAML value — that is what the register has been for since
> Phase 0. A default swappable in one line does not deserve a week of argument.
>
> **Do not re-open a settled decision to re-justify it.** The 59%-vs-6.7% inversion is
> recorded and HR-201 carries its consequence. **It does not block C, D or E.**
>
> **The direction:** two groups, two straightforward rule profiles, every measure
> configuration-driven so HR can swap it — then build JDs for both groups and evaluate each
> against its own profile. `docs/plan.md` §STEP BACK has the shape.

| | Task | Why it is here |
|---|---|---|
| **1** | **🔴 TLS at the edge — the last open exposure, and NOT a repo deliverable** | The pilot host is internet-facing over **plain http**, so sign-in cookies and CAS tickets cross the open internet in the clear. P0.4 makes the app correct *behind* a terminator (P0.3's allowlist reads `X-Forwarded-Proto` and validates the result) and refuses to run pretending otherwise — **someone has to put one in front.** It is also what unblocks actually *using* `docker-compose.prod.yml`, which needs an https origin. |
| ~~2~~ | ~~**P1.3 — Tier the register**~~ ✅ **DONE (PR [#94](https://github.com/humanaxiom/jd-assistant/pull/94))** | The ask is now **65 settings, not 197** (49 `hr_informed` · 83 `technical`), and the generated register leads with **"Your decisions"**. See the block below. |
| ~~2~~ | ~~**P1.2 — Harmonization provenance**~~ ✅ **DONE (PR [#95](https://github.com/humanaxiom/jd-assistant/pull/95))** | The review page now says how the draft was assembled — and the item **understated** the defect: the whole provenance packet had been computed since 4.1 and rendered nowhere. See the block below. |
| ~~2~~ | ~~**Phase 8.3 — review-experience upgrades**~~ ✅ **PHASE 8 IS COMPLETE** | 8.3a word-level diff (#102) · 8.3b structural sidebar (#105) · 8.3c gate→field jump-links. All three landed 2026-08-13; none earned a register entry. |
| ~~2~~ | ~~**Phase 6 leftovers**~~ ✅ **RUNBOOKS DONE** | `docs/runbooks/backup-and-restore.md` + `reindex.md`, both **executed against the live stack before being written**, linked from the operator guide. |
| ~~2~~ | ~~**CUPE Phase A — the `additional_context` truncation**~~ ✅ **DONE (#109)** | 81.4% of CUPE JDs were stored truncated; now 0%. `PARSER_VERSION` → `jd_segmenter_v4`, whole archive re-parsed, HR-200 registered. See the CUPE block below. |
| ~~2~~ | ~~**CUPE Phase B — `applies_to`**~~ ✅ **BUILT** ([#110](https://github.com/humanaxiom/jd-assistant/pull/110)) | **Seven** rules are withheld from the WJQ because that form does not carry what they read — *not* "the four that fire on 100%", which is a different set (see the block below). JDFN is byte-identical; CUPE mean 51.4 → **62.9**. |
| ~~2~~ | ~~**CUPE Phase C — per-template rule PROFILES**~~ ✅ **BUILT** ([#112](https://github.com/humanaxiom/jd-assistant/pull/112)) | `thresholds.wjq` — **`duties_max: 12`** (the form's slot count) plus three values held at their JDFN twins and **registered rather than inherited**. Resolved once into a local `rules` copy so the finding cannot misquote its own bar. `gates.yaml` needed **no** per-template block — `applies_to` already withholds the rules its gates key on. See the block below. |
| **2** | **Phase D — turn CUPE harmonize/cluster on, evaluate per group ⟵ NEXT, needs no HR** | The pipeline is already done: **49,448** role-equivalent edges, more than APSA's 49,008. Produce CUPE drafts and score each group against its own profile. **Never blend the two cohorts into one number.** Merge #112 first. |
| **4** | **Phase E — two builders, if simpler (probably)** | A CUPE JD is a different **form**, not a variant. One builder emitting both grows a conditional in every template, prompt, gate and export. A separate WJQ builder over the same services makes it a **routing** decision made once. Try the seam before debating it. Needs HR-194 for scope. |
| 5 | **🔴 What is genuinely external** | **TLS at the edge** (row 1) · **HR ratification** — 201 decisions, 0 signed, **including the JDFN bar that gates publishing today** · **HR-194**, which decides *scope* (may the Builder author CUPE — Phase E), not whether a measured bar may exist · **HR-201**, and it is now measured to be **much bigger than a score adjustment**: the boilerplate ruling decides whether CUPE JDs are approvable **at all** (59.0% vs 0.0%). |
| 6 | **Territorial-acknowledgement wording sign-off** | The last of Phase 6, and **HR's call, not ours** — it blocks external distribution, not development. *(This row used to also list the backup + reindex runbooks; they are done, and a backlog that lists closed work as open costs a re-investigation every time it is read.)* |

**Deliberately still open, recorded so their absence is not mistaken for completion:**
~~the missing timeout on `/compose/search` and `/assist`~~ ✅ **CLOSED (#97)** ·
~~`embed_stamp` parity is never verified at query time~~ ✅ **CLOSED (#99)** ·
~~`cloned_from_cluster_id` is dropped by `assemble_jd`, so clone lineage is lost at
submit~~ ✅ **CLOSED (#98)** ·
~~`docs/rulebook/rulebook/` is a byte-identical duplicate directory tracked since
Phase 0~~ ✅ **CLOSED (#100**, which also removed the last `jd_core → jd_bank` import
edge — the layering ratchet is now empty**)** ·
`docs/status/*` stops at 2026-07-24.

### 2026-08-13, last — 8.3a: the review diff is word-level, and difflib's default was a trap

`src/jd_core/bank/word_diff.py` + the `?view=unified` toggle on the diff page. Pure and
deterministic, **no rulebook knob, so no register entry and `rules_version` unmoved**.

- **⚠️ THE FINDING: `difflib`'s default `autojunk=True` is catastrophically wrong for JD
  text, and it is on by default.** It treats any element appearing in >1% of a sequence of
  ≥200 elements as junk and refuses to match on it — **the exact shape of a duties list**,
  where every line opens `- Reviews …`. Measured on a 150-line repetitive block with **one**
  duty added: the default reports **897 tokens deleted and 913 inserted**; the truth is
  **0 and 16**. It would have told every reviewer that every duty changed. **A diff that
  cries "everything changed" is one a reviewer learns to ignore** — the same failure as a
  stamp that cries wolf (#97). `autojunk=False`, pinned by two tests, mutation-proved.
- **This was found by measuring, not by reading the docs.** The first hypothesis — that a
  near-identical long text would degrade — was wrong and produced identical output under
  both settings. The trap only appears with **repetition plus an edit**, which is what the
  corpus actually looks like. Same lesson as 5.9 and the coded-language spike: *run it over
  realistic data before designing around what the library says it does.*
- **Two properties pinned because a diff is where a human decides to publish.** It is
  **lossless** — the spans reassemble each side byte for byte across newlines, tabs and
  unicode, so a dropped word can never show a JD that does not exist — and **spans are data,
  never markup**: adding `|safe` to the span loop turns the XSS test red. That test passed on
  the first run, so it was mutated before being trusted.
- **`?view=` is a normalized `str`, deliberately NOT a `Literal`.** A `Literal` answers a raw
  `422` JSON blob on a **UI** surface, which is precisely the P0.0 defect class. Unknown
  values fall back to the split view. The page also degrades to plain text if the word-level
  refinement is missing — the page's job is the approve/reject decision.
- ~~**⚠️ REACHABILITY: it renders on ZERO live JDs today.**~~ **✅ NO LONGER TRUE — and the
  way it stopped being true is the point.** It was accurate when written: the diff needs a
  prior PUBLISHED version and no cluster had more than one. **Then someone edited a
  published JD in the live app during this session** (2026-08-13 23:39 UTC), minting the
  archive's first `version = 2`, and the feature was **verified against that real pair**:
  2 changed sections, Title `-24 words / +0`, Identification `+4 / -0`.
  **The `-24 / +0` is worth understanding rather than glossing:** the published v1's title
  was a boilerplate *paragraph* (a parse defect — see below), and the corrected v2 title
  *"Multimedia Coordinator"* appears **inside** it, so the word diff holds that phrase as
  `equal` and marks only the surrounding prose deleted. That is the feature working, not
  a miscount.
- **🟠 A DATA DEFECT THE FEATURE SURFACED, recorded not fixed: 51 canonical JDs have a
  title longer than 80 characters** — boilerplate marketing prose parsed as the job title
  (*"We are Canada's engaged university, defined by…"*). Invisible until a list of related
  roles put several titles side by side. Not fixed here: a parser change needs a
  `parser_version` bump plus an immediate re-parse of all 14,565 files, which is the same
  ship-together constraint recorded for the `employee_group` residual (#101).

### CUPE PHASE C IS BUILT — the numbers are per-template too (#112)

**The `applies_to` move, one level down, and deliberately no new concepts:** same
`template_of`, same *required with no default*, same registration. `thresholds.yaml`
gains a `wjq:` block; `Rules.thresholds_for(template)` resolves it.

| knob | JDFN | WJQ | |
|---|---|---|---|
| `duties_max` | 5 | **12** | HR-202 |
| `duties_min` | 3 | 3 | HR-203 |
| `summary_max_words` | 150 | 150 | HR-204 |
| `summary_min_words` | 100 | 100 | HR-205 |

- **`duties_max: 12` is a FORM FACT, not a calibration.** `SFU-STRUCT-DUTIES-TOO-MANY`
  fired on **82.3%** of WJQ documents against a bar of 5. The WJQ has twelve duty slots,
  **77.4% of CUPE JDs fill exactly twelve**, and `SFUJobDescription.duties` is
  independently capped at 12 — the same fact recorded three ways. CUPE duty counts are
  **bimodal** (77.4% at twelve, 16.2% at zero), so **the "9.7 average" this project
  quoted for days describes no actual document.**
- **The three held at their JDFN twins are REGISTERED, not inherited.** A value that is
  the same *by decision* and one that is the same *by omission* look identical in the
  YAML — and the omission is exactly what this phase exists to end.
- **The top-level values stay put as the JDFN profile on purpose.** HR's existing entries
  name `thresholds.duties_max`; renaming a path HR has been asked to rule on would
  silently re-point the ask.
- **`gates.yaml` needed no per-template block, and that is worth knowing before someone
  adds one.** Its gates key on `rule_ids`, and `applies_to` already withholds those rules
  from the WJQ — so a gate whose rules cannot fire cannot block. Scoping the gates too
  would have been a second control on the same axis, the `EXEC-DIR` mistake again.
- **⚠ HR-204 RECORDS A FRAMING THE CORPUS CONTRADICTS.** *"CUPE averages 168 words against
  a 100–150 band"* reads as an argument to **raise** the ceiling. Measured over all 4,440:
  **39.9% fall UNDER 100 words**, only **15.1%** exceed 300, and the median is **108**
  against JDFN's 102. The mean is a thin tail pulling. Raising the ceiling would help ~15%
  and abandon ~40%. **Held at 150 and registered rather than acted on.**
- **Resolved ONCE into a local `rules` copy**, so every downstream `rules.thresholds` *and*
  every message context gets the right bar with no call-site change. That is the point:
  `_base_context` feeds `{duties_max}` into the finding's **copy**, so resolving the
  trigger without the message would make a WJQ finding announce *"maximum of 5"* about a
  bar of 12. **A finding that misquotes its own threshold is worse than one that never
  fired** — it sends the author to fix the wrong thing.
- **🔴 A TEST I WROTE WAS VACUOUS.** The honesty pin above first asserted against
  `summary_max_words` — **150 in both profiles** — so it passed regardless of what the
  code did. Same trap as P1.3's tier test. Rewritten against values that genuinely differ
  and mutation-proved: pointing `_base_context` at the unresolved globals now turns it
  red, and the original stayed **green** under that same mutation. *When a new test passes
  first time, find out which property it is actually asserting.*
- **⚠ TWO BUILD GUARDS WERE TAUGHT ABOUT NESTING RATHER THAN EXCUSED FROM IT.**
  `thresholds.wjq` reaches the decision surface through its **leaves** (the
  `dedup.authoring_guard` shape), and two register tests asserting "every top-level field
  is itself a surface path" went red. **The easy fix was to drop `thresholds` from the
  flat-surface list — exactly as `dedup` already is, for exactly this reason — which
  would have retired the guarantee for every key in the file to accommodate one field.**
  Both now assert a nested block contributes leaves. Mutation-proved: breaking the
  recursion stops the whole rulebook loading (76 errors).
- **The governance machinery worked unprompted, twice:** the rulebook **refused to load**
  until all four knobs were registered, and mutating `duties_max` without updating
  `current_default` broke the build via register drift.

### CUPE PHASE B IS BUILT — and the HR-194 framing was wrong

> **⚠️ THE CORRECTION THAT CHANGES THE SEQUENCING, and it came from checking rather than
> arguing.** Everything written before this said a CUPE quality bar must wait for HR.
> **Measured: the JDFN bar is itself entirely unratified.** All **201** register entries
> are `open`, and the bar that gates real publishes today is `our_invention` — `HR-001`
> score floor **60.0**, `HR-002` grade floor **C**, `HR-004`'s 14 blocking rules. **None
> signed by SFU.**
>
> **So "CUPE waits for HR" while shipping an unratified JDFN bar was never a consistent
> position.** The right standard is the one APSA already got: build the WJQ bar the same
> way — **measured over the corpus, every value registered `open`, nothing auto-publishing,
> HR free to change any of it.** What HR-194 genuinely decides is **scope** (should the
> Builder *author* CUPE — Phase E), not whether a measured bar may exist.

**Phase B: every rule now declares which template it can judge.** `applies_to` on all 32
catalogue rules, **required with no default** (the P1.3 `tier` move), filtered inside the
*existing* central filter in `evaluate_jd_rules` — the one whose comment already said *a
finding present on every approvable JD is not a quality signal, it is a constant*.
`applies_to` is that principle one axis over.

| cohort | before | after |
|---|---|---|
| **JDFN** | mean 73.0 · 14.8% approvable | **73.0 · 14.8% — identical** |
| **CUPE** | mean 51.4 · 0.0% | **62.9 · 0.2%** |

- **JDFN being untouched is the important half.** A filter that silenced rules everywhere
  would have looked like success on the CUPE number alone. CUPE gains **+11.5 points**
  purely by no longer being penalised for sections its own form never asks for.
- ~~**Still ~0% approvable, and that is expected**~~ **🔴 FALSE — MEASURED OVER THE WHOLE
  ARCHIVE, CUPE IS APPROVABLE AT 59.0%.** The 0.2% came from a 600-row spike over
  `parsed_jds`; `make baseline` over all 14,565 files says **0.0% → 59.0%** for the 4,300
  WJQ documents (mean 51.8 → 63.2) while **JDFN holds at exactly 6.7%** — the control, and
  the half that matters. The spike was wrong by ~300×, and Phase C had been planned on top
  of it. Evidence + the confound: `docs/decisions/cupe-phase-b-measured-2026-08-14.md`.
  **Fourth time in one day that a claim about the archive did not survive being checked
  against the archive.**
- **⚠ A METHODOLOGY CATCH: my first before/after compared DIFFERENT DOCUMENTS** and appeared
  to show JDFN improving too. `ORDER BY id` over v4 rows selects a different 600 than over
  v3 rows, because each parse row carries its own UUID. Sampling noise, not effect. The
  table above toggles only `template_of` over one document set.
- **🔴 THREE OF THE SEVEN JDFN-ONLY RULES ARE A POLICY CALL, NOT A FACT — HR-201,
  `hr_policy`, `open`.** `SFU-COMP-ABOUT` / `-TERRITORIAL` / `-EDI` check **SFU-wide
  commitments**, not JDFN furniture. Applying them marks down all 4,440 CUPE JDs for a
  property of the *form*; not applying them holds CUPE to a weaker inclusion standard than
  APSA. Defaulted to JDFN-only and registered — **with the view recorded that if HR rules
  the boilerplate is universal, the honest fix is the FORM** (ask SFU to add the block to
  the WJQ), not a rule every CUPE JD fails by construction.
- **🔴 IT WAS EIGHT, AND THE EIGHTH WAS WRONG — `SFU-AUTH-TITLE-EXEC-DIR`, corrected after
  `5a494ea`.** It was the one JDFN-only rule that was neither measured nor registered, and
  it does not survive the phase's own test. **`applies_to` states a fact about the FORM**
  — the WJQ has no Problem Solving section, so a rule reading one cannot judge it — **and
  the WJQ plainly has a job title.** Scoping this rule by template is also a *second*
  employee-group filter on a rule that already carries its own
  (`reserved_for_employee_group: apex`), and it disabled the one restricted-title check
  that **can** fire on exactly the group it would catch. Its two siblings were already
  `[jdfn, wjq]`. Now all three are, mutation-proved in both directions.
- **⚠ AND MEASURING IT FOUND A REAL MATCHER DEFECT — recorded on HR-031, deliberately not
  fixed here.** JDFN-only would have suppressed **5** live CUPE findings, not zero:
  `titles.restricted.executive_director.phrase` is matched as a **substring**, so **3** are
  roles that merely *report to* an Executive Director (*"Assistant to the Executive
  Director"*, *"Secretary to the Executive Director, Student Affairs …"* ×2). The other **2**
  (*"Executive Director of Development"*, *"…, Business Career Management"*) are genuine and
  most likely flag a **mis-parsed `employee_group`** — worth seeing either way. **The defect
  is not template-shaped, so it must not be papered over with a template scope**; the fix is
  a head-noun check, which changes what the rule catches and is therefore HR's to weigh.
  Advisory throughout — `gates.yaml` omission (b) keeps all three restricted titles out of
  every blocking set. **The cohort table above is unmoved and was not re-run:** 5 of 4,440
  CUPE documents (0.11%) at `low` (5 points) bounds the mean shift at ~0.006. Stated as a
  bound rather than re-measured, and said so.
- **⚠ AND THE "FIRES ON 100%" JUSTIFICATION DID NOT SURVIVE BEING CHECKED PER RULE.** The
  test set was labelled *"fires on 100% of CUPE"* for all four members. **It is not.**
  Measured over **all 4,440 CUPE documents at v4** (not the 600-doc v3 sample):
  `SFU-COMP-PROBLEM` **100.0%** · `SFU-GATE-REL-HEADER` **100.0%** ·
  `SFU-COMP-DECISION` **96.9%** · **`SFU-GATE-DUTY-PCT` 0.0%** — that last one *cannot*
  fire, because it needs ≥2 `(NN%)` allocations before it evaluates and **exactly 1 of
  4,440** CUPE documents carries them (0 would trip it). Worse, the four rules that *do*
  fire on 100% are a **different four** — `-TERRITORIAL` · `-REL-HEADER` · `-EDI` ·
  `-PROBLEM` — two of which sit under HR-201, not here. **No scope changed:** every one is
  still correctly withheld, because the real test is *does the form carry what the rule
  reads*, not *was the rule noisy*. Only the stated reason was wrong, and a wrong reason on
  a rulebook pin is what the next person builds on.
- **The JDFN-only set is now pinned as an exact set, enumerated from the live catalogue.**
  Narrowing any rule to one template turns `test_the_jdfn_only_set_is_exactly_the_seven_that_earned_it`
  red, so it has to be argued in the diff — withholding a rule silently removes a finding
  from 4,440 documents. Same shape as 8.3c's `_SECTION_ANCHORS` pin.

### CUPE (#109) — and FIRST, the question every reader asks

> **"Why is CUPE singled out when APSA is the same size?"** (4,946 APSA vs 4,440 CUPE.)
> **It is not that CUPE is unusual. It is that CUPE uses a DIFFERENT FORM and we only ever
> built for the other one.** APSA/APEX/POLY are the **JDFN** template — which the validator,
> the 14 gates, the thresholds and the Builder were all written against. CUPE 3338 uses the
> **WJQ**, a 14-section point-factor questionnaire. It got a parser in Phase 3.4 and nothing
> since.
>
> **Every "CUPE problem" is a consequence of that one fact, not a property of CUPE.** The
> truncation only bit CUPE because `additional_context` is where the WJQ's seven
> point-factor sections land — for a JDFN JD that field is nearly empty, so a 4,000-char cap
> never mattered. The four rules firing on 100% of CUPE fire because the WJQ form does not
> contain the sections they check. **JDFN-shaped tooling meeting a non-JDFN document.**

**#109 carries three things:** the measured evidence, the design, and Phase A shipped.

- **THE CATEGORY ERROR, MEASURED.** Scored through the shipped validator: **0 of 600** CUPE
  JDs are approvable (JDFN 11.3%), mean 51.7 vs 72.4, no CUPE JD reaching even a B. **Four
  rules fire on 100% of CUPE** — and this rulebook already has the principle that condemns
  them: `evaluable: false` exists because *a rule that cannot NOT fire is a constant
  subtracted from every score, not a quality signal*. The mechanism is the form: **0.0%** of
  CUPE JDs have a Problem Solving section, **3.1%** an Impact of Decision Making one.
- **AND CUPE PARSES *RICHER*, WHICH FLIPS THE COST ESTIMATE.** 9.7 duties vs JDFN's 3.8;
  19.5 qualifications vs 1.0. Tier-2/3 dedup is already **done** — 49,448 role-equivalent
  edges, *more* than APSA's 49,008. **The blocker was never the pipeline; it is the bar.**
  So a CUPE bar is a **rules** project, not a plumbing one.
- **✅ PHASE A SHIPPED — the truncation defect, which was OURS and not HR's.**
  `additional_context` had inherited `position_summary`'s 4,000-char ceiling and the WJQ
  parser called the result *"verbatim — lossless"* while cutting it. Now HR-200,
  `PARSER_VERSION` → **`jd_segmenter_v4`**, whole archive re-parsed:
  **`continuing_education` 17.0% → 85.8%**, `working_conditions` 79.0% → 95.3%, **truncated
  CUPE JDs 3,613 (81.4%) → 0**.
- **⚠ THE CAP WAS STILL WRONG AFTER THE FIRST MEASUREMENT.** 12,000 came from a
  149-document sample whose max was 9,916; the full re-parse put **two** documents at
  exactly the cap, true length **13,379** — the sample **understated the corpus maximum by
  35%** while predicting the **mean within 2%**. *A sample is a good estimator of the middle
  and a poor one of the tail, and a cap lives entirely in the tail.* Now 16,000; zero
  truncated.
- **⚠ AND I PUT THE LIVE BOX IN A HALF-MIGRATED STATE BY EDITING A CONSTANT.** The dev `api`
  bind-mounts the repo with `--reload`, so changing `PARSER_VERSION` made the *running*
  service report v4 against a v3-only database. Batch consumers filter on that literal and
  briefly read zero rows; user-facing pages were unaffected (they read the latest parse
  regardless of version). Found by checking, not by breakage. The re-parse closes it, and it
  is **additive** — v4 rows sit alongside v1–v3, so it is reversible and the versions can be
  compared, which is how the numbers above were produced. Now in DEVELOPER_GUIDE_1.md §9a.
- ~~**NEXT: Phase B — `applies_to` on the rule catalog.**~~ ✅ **DONE
  ([#110](https://github.com/humanaxiom/jd-assistant/pull/110))** — required, no default (the
  P1.3 `tier` move), so a withheld rule is **structurally unable** to fire on CUPE rather
  than conventionally excluded. ⚠ **It withholds SEVEN rules, not "those four"** — the
  justification is *does the form carry what the rule reads*, which is not the same question
  as *did the rule fire on 100%*. See the Phase B block at the top.

### Both technical guides were corrected in the same PR

`DEVELOPER_GUIDE_1.md` §3 "First-run verification" **would have failed at every step**: every
port was the upstream harness's default (`8000`/`7474`/`5000`) rather than this project's
**25800/25474**, the Ollama check pointed at `localhost` instead of `aria-gb10-2` (ADR-003),
and §9 was named after a Flask dashboard removed in `3e32103`. New **§9a** documents the JD
data layer — the two templates, the template-blind validator, and the `parser_version` trap.
`docs/OPERATOR-GUIDE.md` gains the parser-bump warning and the measured CUPE scope note,
including that **"not authorable" is not "not in the Bank"** — CUPE JDs are ingested, parsed
and searchable. **Still stale elsewhere:** HANDOFF records 8 live Flask references;
`README.md`, `harness-claude-code/CLAUDE.md`, `docs/adr/002` and `.env.example` still carry
some, deliberately out of scope for a two-guide pass.

### PHASE 6'S RUNBOOKS ARE DONE — and writing them found a silent data-destroying restore

`docs/runbooks/backup-and-restore.md` + `docs/runbooks/reindex.md`, linked from the operator
guide (§8). **Every step was executed against the live stack before it was written down.**
An unrun runbook is a guess, and this one proved the point within the hour.

- **Only Postgres needs backing up.** Neo4j is a **derived index** — `make embed` rebuilds
  documents + sections from `parsed_jds`, `make embed-roles` rebuilds roles from
  `canonical_jds`. The labels that are *not* derivable (harness agent memory:
  `Agent`/`Artifact`/`Task`/`Subtask`) hold **0 nodes**, so nothing is at risk — recorded
  with the query that falsifies it if that ever changes.
- **🔴 `pg_restore --data-only` INTO AN ALREADY-MIGRATED DATABASE SILENTLY DESTROYS THE DATA
  AND EXITS 0.** Measured on the real dump: **1,804 canonical JDs → 0**, **12 user roles →
  0**, **1,810 chained audit rows → 0**. It printed `warning: errors ignored on restore: 7`
  and returned **exit code 0**, and the restored database starts and accepts logins with all
  6 users present. **An operator who checked the exit code and signed in would conclude the
  restore worked and would have lost the entire Bank.** With `user_roles` empty, nobody can
  approve anything either — the app would look healthy and be unable to publish.
  **This is the `make gates | tail` lesson in a new place: a zero exit is not evidence.**
- **The blessed path was verified byte-identical:** a full `-Fc` dump restored into an
  **empty** database returns 1,810 chained rows, the same `d8899dc8…` audit fingerprint and
  the same `audit_chain_tail`. **It survives for a reason worth knowing:** the chain is
  written by a `BEFORE INSERT` trigger that overwrites `prev_hash`/`row_hash`
  unconditionally, and `pg_restore` loads data **before** creating triggers — an ordering
  guaranteed by the custom format, which is why `-Fc` is not a preference.
  `--data-only --disable-triggers` also works (superuser only; the compose `app` role is
  one — **that will stop being true when the production posture tightens the app role**).
- **Reindex resume proven rather than asserted:** `make embed EMBED_ARGS="--limit 50"` →
  *50 seen, 0 embedded, 49 unchanged, **embed calls: 0***. An interrupted reindex is resumed
  by running it again; there is no resume flag and none is needed.
- **⚠️ A side effect found by running it: `make embed` with `--limit` OVERWRITES the
  committed `docs/embeddings/summary.json`**, rewriting `documents_seen` from **14,522** to
  the spot-check size. Caught here and reverted; the runbook carries the
  `git checkout --` that undoes it. **A partial run must not become the repo's record of the
  last full pass.**
- **One gap stated instead of guessed:** the wall-clock of a full *cold* rebuild is unknown,
  because every run available to measure was a skip-first no-op. The runbook says so and
  asks for the number the first time a real rebuild happens.

### 8.3c IS DONE — and with it PHASE 8 IS COMPLETE

Each blocking gate now says *"Fix this in: **Qualifications ↓**"* instead of offering the
coarse whole-Edit jump. **Rulebook-driven end to end**, and nothing is re-stated: the gate
carries the `rule_ids` that tripped it, the catalog owns each rule's `section`, and the
catalog's own `section_order` / `section_labels` supply the order and the words. Only the
section → HTML anchor is a UI concern. No register entry; `rules_version` unmoved.

- **⚠️ THE COMPLETENESS PIN IS THE FEATURE.** `_SECTION_ANCHORS` is asserted equal to
  `get_args(SFUSection)` — **enumerated from the live literal, not a hand-written list** —
  so adding a template section without deciding where it lives on the page **fails the
  build** instead of rendering a link that jumps nowhere. `general` is declared `None` (the
  whole document has no field to jump to), never omitted, for the same reason P1.3 gave
  `tier` no default. A second test walks the **rendered page** and asserts every `#edit-*`
  href has a matching `id`; a one-character typo in an anchor turns it red.
- **Coverage measured over the whole archive before it was claimed: 505 of 535
  blocking-gate occurrences carry `rule_ids`**, so a link is the common case. The only two
  that never do are `SCORE-FLOOR` and `GRADE-FLOOR` (15 each) — genuine roll-ups where a
  link would misstate what is wrong.
- **A comment I had to correct: `SEVERITY-FLOOR` reads like a roll-up and is not.** It
  names the offending rules (12/12 live occurrences), so it *does* get links; it falls back
  to none only when tripped by a rule-less LLM finding, which has no section to point at.
  The first version of the docstring asserted it was a roll-up from its name alone.
- **Live-verified on real blocked drafts:** `KSA-ORDER → Qualifications`,
  `SUMMARY-CONDITIONS → Position Summary`.
- **🔴 P0.0'S LINK CRAWL CAUGHT THIS FEATURE, AND IT WAS RIGHT TO.** The full gates went
  **red** on `test_every_same_page_link_lands_on_an_anchor_that_exists`: the crawl reads
  template *source*, and `href="#{{ target.anchor }}"` is **computed**, so unlike every
  other fragment in this app it does not pair with a matching dynamic `id=` the scanner
  can see — it targets a set of **literal** ids. **The temptation was to make the crawl
  skip Jinja fragments. That would have blinded the net for every future template.**
  Instead the link is declared in `OPAQUE_LINKS` — the mechanism P0.0 already built for
  exactly this — and verified by walking `_SECTION_ANCHORS` against the ids in
  `review_detail.html`, which is **stronger than the crawl could manage**: it proves
  *every* value the link can take is a real anchor, not just the one a sample render
  produced. Mutation-proved: mistyping the `relationships` anchor turns it red even
  though no rendered-page test exercises that section.
  **The lesson: when a safety net fires on new work, the first question is what it knows
  that you do not — not how to quiet it.**
- **⚠️ IT ALSO PROVED THE `get_session` CHORE IS A LIVE DEFECT, NOT A LATENT ONE.** The
  ROADMAP row said an import cycle was *"waiting to be re-introduced"*; it **exists**, and
  it bit three times here. `routes/ui.py` imports `get_session` from `src.api.main`, which
  imports `routes.ui` to mount the router — so `import src.api.routes.ui` **first** raises
  `ImportError: cannot import name 'router' from partially initialized module`. Every
  existing suite hides it by importing `src.api.main` first, which is exactly why nobody
  had noticed. `test_gate_jump_links.py` carries the explicit import **with a comment
  saying why**, rather than papering over it. Row corrected.

### 8.3b IS BUILT — the sidebar shows the roles clustering REFUSED to merge

The review detail page gains **"Where this role sits"**: a versions tree (v1 → v2 …, current
marked) and a ranked list of the roles Tier-3 dedup paired this one with. Read-only and
advisory; it changes no verdict (NN #1). **Live-verified: 1,251 of 1,804 canonical JDs
(69.3%) show a non-empty list.**

- **⚠️ "Related" understates it — these are the near-misses the clustering step RULED ON.**
  A cross-cluster `ROLE_EQUIVALENT` edge exists exactly when a pair scored at or above the
  Tier-3 **pair** bar (0.5) but **below the merge bar** (`cluster_role_equiv_min` = 0.75,
  HR-162). **Zero** of the 32,816 cross-cluster edges reach 0.75. The rulebook states the
  design — *"Tier-3 edges are pairwise, clustering is transitive, so the bar to MERGE must
  be higher than the bar to record a single same-role pair"* — so the page says plainly
  that these were scored *below the bar to merge*, and asks the reviewer the useful
  question: **if one of them IS this role, that is a finding.**
- **It reads well on real data:** a *Business Systems Analyst* surfaces four separate
  *Business Analyst* clusters plus an *Organizational Change Consultant* — exactly the
  "should these be one role?" question a reviewer should see.
- **RANK, NEVER SCORE — pinned as a model SHAPE, not a template detail.** `RelatedRole` has
  no `score`/`similarity` field at all, and a test fails if one is added. The list is
  ordered by **how many source documents connect the two roles** — a count, a fact about
  the archive — because role similarity here has unrelated roles outscoring true twins.
  **The only number in the feature is the display cap (8), so no register entry is earned.**
- **⚠️ THE BUG I SHIPPED INTO MY OWN TESTS, and how it was caught.** Adding the service call
  to the detail route turned **13 unrelated review tests red** — the page now had a second
  way to fail. That was not a test problem, it was a **production** one: *a navigation aid
  could 500 the page where a human approves a JD.* `_structure_or_none` now degrades to
  absent and logs; removing it turns 14 tests red. **A new call on a decision surface is a
  new failure mode for that decision.**
- **Both DB guards mutation-proved against a real Postgres** (a fake session proves nothing
  here): restricting the edge lookup to one endpoint orientation turns the orientation test
  red — Tier-3 edges are stored **oriented** while undirected in intent, so a one-sided
  query **silently halves** the list, which looks exactly like a correct shorter one — and
  widening the tier filter to `NEAR_DUPLICATE` turns the tier test red.
- **`NEAR_DUPLICATE` is deliberately NOT consulted**, per the measurement below.

### The 8.3b measurements — and the plan's premise was half wrong

`docs/plan.md` says the related-roles list comes from "the **Tier-2/Tier-3** dedup edges
(near-duplicates / role-equivalents)". **Only one of those two tiers can work**, and the
reason is structural: `dedup_edges` joins **source documents**, and those edges are what
**formed the clusters**, so most are intra-cluster by construction. Measured live:

| Tier | Intra-cluster | **Cross-cluster** |
|---|---|---|
| `NEAR_DUPLICATE` | 11,581 | **16** |
| `ROLE_EQUIVALENT` | 29,034 | **32,816** |

- **`NEAR_DUPLICATE` gives 16 edges across 1,803 clusters — nothing.** That is not a defect,
  it is the definition: near-duplicates get clustered *together*, so a cross-cluster one is
  an **anomaly**. Those 16 are worth a look as anomalies; they are not a sidebar feature.
  **Build 8.3b on `ROLE_EQUIVALENT` only, and say so in the code.**
- **`ROLE_EQUIVALENT` has real surface: 4,602 directed cluster pairs covering 1,251 of 1,803
  clusters (69.4%).** Unlike 8.3a this renders on day one — but **~31% of roles will
  correctly show an empty related list**, which the page must state rather than look broken.
- **The versions tree is a single node for every role today** (1,803 versions / 1,803
  clusters), same caveat as 8.3a.
- **⚠️ RANK, NEVER SCORE.** Role similarity on this corpus was already measured: unrelated
  roles outscore true twins. The sidebar must **order** the list and never print a percentage
  or apply a `cosine_min` — that applies to `dedup_edges.score` too. Keep it that way and the
  only number in the feature is how many rows to list, so **no register entry is earned**
  (same shape as P1.2). Inventing a "show it above 0.8" knob would manufacture an HR decision.

### 2026-08-13, later still — the interactive timeouts are closed (#97)

`/compose/search` and `/assist` had the **same defect the 5.9 guard was fixed for** and it
had been recorded as open ever since: `connect=5.0` makes a *refused* host fail fast, so
"Ollama is down" was never the risk — a host that **accepts and then stalls** is, and read
600s × 2 SDK retries × 3 attempts is ~90 minutes of a held request. `/compose/search` holds
a checked-out `AsyncSession` out of a small pool for all of it, so a handful of searches
take the Builder down. Both now bounded, both mutation-proved, and **`/assist` returns the
author's own draft** — losing half-written work to a wedged GPU is worse than not getting a
suggestion.

- **Two new registered knobs, HR-198 / HR-199 — and BOTH landed `technical`, so HR never
  sees them.** That is P1.3 paying for itself within a day: before the tiering, two
  embedding timeouts would have gone into the same undifferentiated list HR was refusing to
  sign.
- **⚠️ THE TRAP, AND IT WAS NEARLY SHIPPED: `Embeddings.digest` hashes the WHOLE file, and
  it is what `embed_stamp` is built from.** Adding *any* key to `embeddings.yaml` therefore
  moves the stamp — which means "the archive is stale, re-embed ~14,500 documents" — for a
  wait budget that provably cannot change a single vector. `_NON_VECTOR_EMBEDDING_FIELDS`
  now excludes it, the digest is documented as covering *vector-affecting* content only, and
  the stamp was **verified byte-identical before and after** (`jd_rules_sfu_v4+b760ce00210a`)
  rather than reasoned about. **A stamp that cries wolf trains people to ignore it.**
- The existing "every knob is in the stamp list" guard still holds: the exclusion must be
  *declared*, so it is an argued decision and never an omission.
- **A process note worth keeping:** an unanchored `sed` mid-session corrupted three
  unrelated `current_default` values in the register. It was caught by reverting the file
  and re-applying the saved block — **on a 6,000-line generated-adjacent artifact, revert
  and re-apply beats patching a bad patch.**

### 2026-08-13, later — P1.2 IS DONE, and the defect was BIGGER than the backlog said

PR [#95](https://github.com/humanaxiom/jd-assistant/pull/95). `make gates` **2,627 passing,
93.91%**. `rules_version` **unmoved**; **no register entry earned** — see below, that is the
design, not an omission.

- **🔴 THE FINDING: `merge_provenance` has been computed and persisted in `change_log` since
  Phase 4.1, and was read by NOTHING.** Not the review page, not the library — `grep` returns
  the producer and no consumer. So the reviewer could not see which sources fed the draft, how
  many members required a skill, how many stated a duty, or the HR-eyeball flags. **The backlog
  item named one symptom (the education bar); the disease was the whole packet.**
- **The bar record did not exist at all** and is the new part: `SeniorityBarChoice` records the
  policy *actually applied*, the chosen bar, and **what every member stated** — so the page can
  say *"the sources disagreed — 1 of 10 stated the bar this draft uses, and 9 stated a
  different one."*
- **⚠️ A SILENT MEMBER IS NOT AN OVERRULED ONE.** `None` means the member stated **no bar at
  all**, which is categorically different from stating a lower one. Counting silence as dissent
  would overstate the disagreement the reviewer is being asked to weigh — and on this corpus,
  where a third of JDs do not even parse an `employee_group`, silence is common. Pinned by its
  own test.
- **No threshold, therefore no register entry — and that is deliberate.** `disagreed` is a
  property of the members' own statements, not a tunable. The standing rule ("any non-trivial
  metric must be YAML-configurable and registered") **bites on a cutoff**; inventing a
  "show it when ≥N disagree" knob would have manufactured a decision HR then has to rule on.
  The only number in the feature is how many rows the panel prints before it stops.
- **The policy is described as itself.** The panel says *highest* or *most common* from the
  recorded `policy`, never hardcoded — pinned by a test, because hardcoding "highest" would
  make the page lie the day HR rules for `modal`.
- **Proved by mutation**, and it degrades safely: a malformed provenance packet costs the
  panel, never the page — the page's job is the approve/reject decision.

### 2026-08-13 — P1.3 IS DONE: the HR ask is 65 settings, not 197

PR [#94](https://github.com/humanaxiom/jd-assistant/pull/94). `make gates` **2,616 passing,
93.90%** (was 2,606 / 93.89%). `rules_version` **unmoved** — `decision_register.yaml` is
unhashed and **no default changed**; the tier records *who is asked*, not what we ship.

- **The diagnosis was right, and the fix is one required field.** The register does **two
  incompatible jobs**: it is the list of policy calls HR must sign, *and* the completeness
  ledger that stops an engineer tuning a threshold silently. Job two forces embedding
  dimensions, MinHash band counts and model temperatures into the same list HR is handed.
  Every entry now carries `tier` — `hr_policy` / `hr_informed` / `technical`.
- **Measured: 65 · 49 · 83.** The pre-work estimate was "~55–60 touch the approval bar" and it
  held. The generated register leads with a section called **"Your decisions"**, each tier
  carrying its own summary table, so HR's table is 65 rows rather than 197.
- **⚠️ THE THREE PROPERTIES THAT MAKE IT MORE THAN A LABEL — a tier that is only a column is
  worth nothing:**
  1. **`tier` has NO DEFAULT.** A new parameter cannot be filed into a tier by omission —
     which is *exactly* how 197 undifferentiated entries accumulated. A new entry must state
     its audience or the rulebook does not load.
  2. **Nothing became unregistered.** Every id survives, and every build-breaking check still
     walks all 197 — tune a `technical` value without updating `current_default` and the build
     fails as before. **The audience changed; the coverage did not.** Pinned by a test.
  3. **`comparison.yaml` / `hay_signals.yaml` may NEVER be `hr_policy`.** ADR-007 disclaims
     them as *not* formal classification and `models/bank.py` makes a Hay grade
     unrepresentable — so asking HR to ratify a similarity weight would contradict both.
- **Both new nets were proved by mutation, in both directions** (this repo's standing habit):
  demoting the score floor out of `hr_policy` turns `test_the_approval_bar_is_hr_policy` red;
  promoting one comparison weight into it turns the ADR-007 test red. Neither was trusted
  until it had been watched failing.
- **A trap worth recording: one of the new tests passed before the feature existed.**
  `test_a_decision_with_an_unknown_tier_fails_to_load` was green against the *old* model —
  because `extra="forbid"` rejects an unknown key. It was a **vacuous pass**, and only became
  a real test of the `Literal` once the field shipped. **When a new test is green on the first
  run, find out which property it is actually asserting.**
- **`make gates` reported ✅ while black was failing.** The backgrounded `make gates | tail -25`
  exited 0 because that is the *pipeline's* status, not make's — and the real output said
  `1 file would be reformatted` / `Error 1`. **Read the output, never the exit code of a
  pipeline.** Same lesson as the subagent rule, one layer down.
- The HR-facing matrix carries the change (`HR-DECISION-MATRIX.md`), and says plainly that
  **the Part 4 ask of eight settings is unchanged** — the 65 are the wider set behind them.

### Also 2026-08-13 — an external gap analysis was triaged, and mostly did not survive

`GH-Copilot/sfu-site-gap-analysis.md` (+ three companion files) compares the repo to the public
SFU HR site and files nine issues. Verdict + evidence:
**`docs/decisions/copilot-sfu-gap-triage-2026-08-13.md`**. No code changed; ROADMAP and plan.md
absorbed what survived.

- **Both of its P0s assert a decision "has not been made" — and both decisions are made, written
  down and enforced.** CUPE/WJQ scope is explicit in **five** places, one of which is the HR ask
  it says is missing (HR-DECISION-MATRIX **Decision 8**), plus HR-194/HR-143 and the fact that the
  Builder's group list is rulebook data on purpose. Hay authority is enforced **structurally**:
  `HayGrade` / `HaySignals.{grade, grade_mapped}` are made **unrepresentable** in `models/bank.py`
  — and that file is the evidence the analysis itself cites.
- **Its issues 7–8 (change tracking, compensation audit trail) are largely already built.** Its
  acceptance criteria are, item for item, shipped behaviour: `review.edit()` requires a non-blank
  reason and records `changed_sections`, an edit mints `version = max+1`, `/review/{id}/diff`
  renders before-vs-after, `audit_log` is hash-chained. **The lesson is the familiar one:** an
  analysis that reads *docs* rather than *code* reports missing features that exist.
- **Two proposals are now recorded as Explicitly OUT rather than left as gaps** — a Hay
  factor-by-factor point breakdown (proprietary charts; a label is not a control) and a
  compensation requisition workflow (the HRIS is the system of record; the seam is the planned
  HRIS export). **Their absence should read as a decision, which is what that section is for.**
- **What genuinely survived:** the **re-evaluation lifecycle** — SFU's process is intake →
  evidence → review → decision → resolution, and only the intake half was planned. Three of the
  five stages already exist; the missing piece is **a request object with a status**, not a second
  decision store. Plus one small residue: the JDFN scope sentence is on the search page and the
  baseline dashboard but **not on the Builder**, the one place an author would ask.
- **⚠️ And its blind spot is the one worth carrying: none of the four documents mentions
  ratification.** It sequences CUPE authoring and Hay evaluation as "short term" while **every
  register entry is still `open`** — planning capability past an unsigned approval bar. It also
  lists "score and **grade** logic" as implemented; grade is missing/unreliable and HR-blocked.
  **An external review's priorities are not calibrated to our critical path; check them against
  it before adopting a sequence.**

### The evidence behind the four habits above

Kept because each is a *specific* thing that shipped green over a hole, and the pattern is
only convincing with the cases attached:

- **Three controls were green while a hole existed** — the authorization matrix (green
  while an open route was served), the compose-delivery pin (protected 1 of 12 services),
  and the CSRF guard's three untested branches. **Every one was found by mutation.**
- **P0.2 was a complete no-op while correct.** Nine conditions, no bypass, 2,218 tests
  green — and `ENVIRONMENT` reached zero of fourteen containers. Both reviewers found it
  by *trying to deploy*.
- **P0.0's defect lived in the gap between "refused" and "offered."** The matrix was right
  on all 51 routes while an author's first click was a link to a `403`.
- **P0.3 caught the harness, not the app:** a test asserting the CAS fallback origin
  **failed on the dev box and would have passed in CI**, because the repo-root `.env`
  reached the `gates` container for that setting — the suite was reading the developer's
  machine. `GATES_HERMETIC_PINS` is the list of what is pinned, asserted exactly so a new
  pin has to be argued for.
- **P0.4 had two defects invisible in review** — a stray underscore making a Neo4j setting
  one the server rejects, and a healthcheck reading a variable that exists in the compose
  environment but not inside that container. Both obvious on the first `up`.

---

**PRIOR (2026-08-11, later): 🔴 P0.0 NAVIGABILITY filed.**
Task: **`docs/tasks/P0.0-navigability.md`**.

- **Found live, minutes before an HR demo: `http://localhost:25800` answers
  `{"detail":"Not Found"}`.** So does `/jd-bank/ui`. The shallowest working path is
  `/jd-bank/ui/library`, so anyone who types or bookmarks the bare host lands on a raw JSON
  error.
- **It is not a missing redirect — it is three gaps meeting at the front door.** (1) No landing
  route. (2) **Errors are written for machines, not people**: every UI 404/403/500 is a JSON blob
  in the browser, *including the stale-tab CSRF 403* that now fires after P0.1b-i. (3) **Nothing
  anywhere tests that a rendered link resolves** — every `href` in every template is unverified,
  so a Jinja-built path with one wrong segment ships silently.
- **Fix the class, not the instances:** a landing route, HTML error pages in the app's own chrome
  (with copy for the stale-tab case that says *reload and try again*, not "Forbidden"), and a
  **crawl test that extracts every `href`/`form action` from every rendered page and fails when
  one 404s**. Build it the way the other nets in this repo had to be rebuilt — **enumerate from
  the live artifact**, as the authorization matrix walks the real routing table and the
  compose-delivery pin derives its set from a real refusal message — and **prove it fails** before
  trusting it.
- **Why P0:** the pilot is a person clicking around unsupervised. A reviewer who hits a JSON blob
  does not file a bug, they lose confidence. And it is cheap.
- **Cost, stated honestly:** any new route needs an entry in `test_authorization_matrix.py` (its
  completeness assertion fails otherwise, by design) and in the CSRF table if it changes state.
  ⚠️ **One trap:** mounting `StaticFiles` for `favicon.ico` turns the matrix **red** — its walk
  raises `UnwalkableRouteError` on a mount *by design*, so the walk must be extended first.
- **✅ THE CRAWL IS DONE and its inventory is in the task doc** — 51 routes, unauthenticated and as
  admin/reviewer/author, plus all 19 templates. **The worry that prompted it did not materialise:
  zero broken template links**, no route shadowing, trailing slashes work, and four routes already
  render a friendly HTML 404 — *that is the pattern to copy.*
- **🔴 IT FOUND SOMETHING WORSE THAN THE FRONT DOOR.** `author` is `default_new_user_role`, and for
  an author: the nav shows a **Review queue** link that answers **`403` raw JSON**, and **Submit
  commits the draft, redirects to a reviewer-only page, and strands them on a JSON blob** with no
  sign the work saved. **That is the first-run experience.** The organising defect behind all eight
  classes: the authorization matrix distinguishes JSON from UI surfaces **for the status code**,
  and nothing does so **for the body**.
- **➡️ P1.1 (author submission status) IS ABSORBED INTO P0.0** — fixing the redirect target without
  fixing the nav that offered the link just moves the dead end. Ship together: root redirect · HTML
  error pages (404/403/401/405/500) · role-aware nav · author "my drafts" landing · empty-state
  links · the crawl test.
- **Order:** ~~P0.1a~~ ✅ → ~~P0.2~~ ✅ → ~~P0.1b-i~~ ✅ → **P0.0 ⟵ NEXT** → **P0.3** → P0.1b-ii →
  P1.2 → P1.3.

- **🟠 NEW — P0.3 DEPLOYMENT ORIGINS (`docs/tasks/P0.3-deployment-origins.md`).** The system was
  reached from outside the dev box for the first time (`sfuai.ca:7000` → `25800`) and **sign-in
  broke**: CAS authenticated, issued a ticket, then returned the browser to
  **`http://localhost:25800/...`**, because the CAS return origin is a **single static setting**.
  Repointing `CAS_SERVICE_BASE_URL` fixed it live — **a workaround, not a design.** One value
  cannot serve localhost, the forward and a future hostname; while it points at the forward,
  **localhost sign-in does not work.** The existing alternative (`cas_service_from_request`, taken
  from `X-Forwarded-Host`) is the **header-injection vector P0.2 deliberately refuses in
  production**, so today's options are *rigid* or *exploitable*. Build the third: derive the
  origin, **validate it against an allowlist** (shape it like `allowed_inference_hosts`), force
  https in production, and fall back to the static value — **never** to the header. Note P0.2's
  refusal of that flag must be updated in the same change or it will refuse the new mechanism too.
  *Useful fact: SFU CAS accepted `http://localhost:25800` as a service and issued a ticket, so CAS
  is **not** validating service URLs for us.*
- **⚠️ P0.3 PART 2 — AN UNANSWERED QUESTION, AND IT IS THE BIGGER ONE.** The app is now reachable
  at a **public DNS name over plain http** while running `environment=development` — so **P0.2's
  fail-closed guard is inactive**, session cookies and CAS tickets cross the network in the clear,
  DB/Neo4j creds are the committed `app`/`harnesspass`, and the data stores publish on `0.0.0.0`
  (**25432 / 25474 / 25687 / 25379**). **If port 7000 reaches this host from outside, check whether
  those do too — that is a larger exposure than the CAS redirect that surfaced it.** Ask whether
  the forward is internet-facing or campus/VPN-only; bind the data ports to loopback either way.
  If internet-facing, the missing **production compose profile** (P0.1b-ii) stops being optional —
  `api` still runs `--reload`, so a refuse-to-boot would present as "Up but serving nothing".

---

**PRIOR (2026-08-11): P0.1b-i — CSRF FOR COOKIE-AUTHENTICATED STATE CHANGES — MERGED**
(PR [#85](https://github.com/humanaxiom/jd-assistant/pull/85), `591a3f3`, CI green).
`make gates` **2,433 passing, 93.63%**; `register-check` in step; `rules_version` **unmoved**
(`jd_rules_sfu_v4+90af5e27dc83`) — transport security, not a rulebook metric, so **no register
entry**.

- **What was open.** Every UI mutation was a cookie-authenticated form POST with no CSRF
  defence. P0.1a made the actor server-derived and P0.2 made the posture enforceable; neither
  stops a cross-site page causing a signed-in reviewer's browser to POST an approve. Measured
  before the fix: `POST /jd-bank/ui/review/{id}/approve` answered **303 — it reached the service
  and published**.
- **The rule, and why it is stated over the REQUEST and not the route:** *any state-changing
  request authenticated by a session cookie must carry that session's token.* No per-route
  allow-list, so nothing drifts, and a new `POST` is covered the day it is written.
  Implementation: a random per-session token on the **session row** (Alembic `0006`; **not** the
  session id — that is the `httponly` cookie value and this goes into HTML), checked by an
  **app-wide FastAPI dependency** (`src/api/csrf.py`), rendered by one Jinja macro called at all
  ten form sites. A dependency, **not `BaseHTTPMiddleware`** — middleware consumes the request
  stream and must re-inject it; a dependency is handed the same `Request` and Starlette caches
  the body.
- **⚠️ THE FINDING WORTH CARRYING: mounting it app-wide was right for a reason nobody predicted.**
  It was flagged in review as unrequested scope creep — a browser-surface mount would be tighter.
  Then the security reviewer found **`POST /gates/run` takes `branch` as a query parameter and
  declares no body at all**, so a plain `<form method=POST action=".../gates/run?branch=x">` with
  an admin's cookie enqueued an arq job (measured pre-fix: `200`, `enqueue_job` awaited once). The
  comfortable argument — *"a cross-site form cannot drive a JSON route, because a Pydantic body
  rejects a form-encoded one"* — is TRUE for the eight Pydantic-bodied routes and **generalises
  into a falsehood**. A scoped mount would have left it open. **When an argument for "out of
  scope" rests on a property of *most* members of a set, enumerate the set.** The table now covers
  all **18** state-changing routes, not 10.
- **Three more holes closed on the way.** (a) An **unauthenticated `/logout` still sent
  `Set-Cookie`** — `SameSite` governs which requests *carry* a cookie, not which responses may
  *set* one, so a cross-site POST forced a logout **without ever holding the victim's cookie**;
  it now emits no header at all when there is no live session to revoke. (b)
  `session_cookie_samesite` refuses `none` **in every spelling** (Starlette lower-cases, so a
  case-sensitive check would be a one-keystroke bypass) in production, and refuses an
  **unrecognised** value at load in *every* mode — otherwise Starlette's `assert` means the
  service starts clean, serves the login page and 500s the first sign-in (and under `python -O`
  the assert compiles out and the browser silently discards the attribute). (c) **Clickjacking
  fully defeats token CSRF** — a framed review page carries its own valid token and posts
  same-origin — so `X-Frame-Options: DENY` + CSP `frame-ancestors 'none'` ship with the feature,
  as raw ASGI middleware (never `BaseHTTPMiddleware` upstream of handlers that re-read a body).
- **`X-CSRF-Token` is not a convenience, and the two reviewers split on it.** A JSON body cannot
  carry a hidden form field, so for the eight Pydantic-bodied routes the header is the **only**
  satisfying path — delete it and every cookie-authenticated JSON call is a permanent 403.
  Kept, with all four of security's conditions: accepted-case test, wrong-value test, a test that
  **no CORS middleware is installed** (the global invariant the header's safety rests on, which
  nothing pinned), and **body-first precedence** so a stray header from a proxy or extension
  cannot shadow a valid form field and brick every form.
- **Parser consolidation done at the same time:** `src/api/routes/_forms.py::read_form_pairs` is
  now the one reader of a form body (`ui.py`, `compose_ui.py`, `admin.py` ×2, plus the guard).
  Three copies had already drifted — `admin.py` dropped `keep_blank_values`.
- **🔧 `docker compose exec api pytest` IS NOT A VALID GATE ON THIS BOX.** The repo-root `.env`
  sets `CAS_ENABLED=true`; the `api` service inherits it and **9 unit tests fail spuriously**.
  The hermetic `gates` service pins the posture and is the runner of record — always `make gates`.
- **Deploy note (migration `0006`):** no server default on `csrf_token`, so old-code+new-schema
  breaks login and new-code+old-schema breaks every request. **Not rolling-safe; it needs an
  atomic swap**, which is what `docker compose up` does. Stated in the migration docstring.
- **Recorded, deliberately NOT fixed here** (see ROADMAP): **login CSRF** — `GET /cas/validate`
  mutates (provisions a user, may grant ADMIN via `bootstrap_admins`, mints a session, commits),
  and no token can exist before the session it belongs to, so it needs the CAS `state`/`next`
  round trip reworked · the open redirect on `next` · `/ready` amplification · a production
  compose profile · `GraphMemory` egress.

---

**PRIOR (2026-08-07, later): EXTERNAL ARCHITECTURE REVIEW TRIAGED — it found a LIVE AUTH HOLE
THAT PUBLISHES JDs — and we are now EXECUTING the fixes.**
Plan + iteration list: **`docs/tasks/architecture-review-response-2026-08-07.md` §6.**
Every claim was re-verified against the code before being planned around; 9 of 11 confirmed,
2 partly true, none false.

- **✅➡️ WHERE WE ARE: BOTH P0 ITEMS ARE MERGED, AND P0.1b-i (CSRF) IS DONE ON A BRANCH — see
  the newest block above. What follows was written before it.**
  **P0.1a — PR [#82](https://github.com/humanaxiom/jd-assistant/pull/82), `4b4eed9`** (gated the
  JSON API, both identity-forgery paths closed, authorization matrix). **P0.2 — PR
  [#83](https://github.com/humanaxiom/jd-assistant/pull/83), `8d8df23`** (an unsafe production
  posture now refuses to boot). Both CI-green. They were **one security fix in two commits** and
  neither was sufficient alone: P0.1a's gates only bind when `cas_enabled=True`, and the shipped
  default was `False`, where `resolve_user` returns a transient **admin** before reading any
  cookie. `make gates` **2,282 passing, 93.41%**.
  **⚠️ THE LESSON WORTH CARRYING, because it will recur:** P0.2's implementation was correct on
  the first pass — nine conditions enforced, secret leakage genuinely prevented, no bypass, 2,218
  tests green across three independent runs — and it was a **complete no-op**, because
  `ENVIRONMENT` reached **zero of fourteen containers**. A test that constructs
  `Settings(environment="production")` directly can never see that; only trying to deploy it can.
  **Both reviewers found it independently, and neither found it by reading code.** The second-order
  trap is just as important: plumbing `ENVIRONMENT` through *without* making the hardcoded compose
  credentials `${VAR:-default}` would have turned "refuses to start" into "refuses to start and you
  cannot fix it." **When you build a control, prove it is reachable from the documented deployment
  path — not merely that its logic is right.**
  The durable answer is a test that derives its required set **from a real refusal message**
  (`test_compose_env_delivery.py`), so a new condition automatically demands a compose key — the
  same shape as the authorization matrix walking the live routing table. Note that pin ALSO needed
  a second pass: its first version protected only `api`, and a `worker` merge block pinning
  credentials back to literals sailed through 44/44 green.
  **➡️ NEXT — P0.1b**, now a coherent bundle rather than four odds and ends, all of the form *"the
  deployment posture is enforceable now, so make the runtime match it"*: **CSRF** for
  cookie-authenticated state changes · **`session_cookie_samesite: strict`**, deliberately deferred
  from P0.2 because `strict` suppresses the cookie on the **CAS cross-site return leg** and a
  fail-closed check that bricks production login is worse than the gap — it needs end-to-end
  testing, not an assertion · **`/ready` amplification** (measured: 200 concurrent → 3.00s vs
  `/health` 0.43s, Postgres backends 1→13; flooding it makes it self-report `degraded` and a load
  balancer pull healthy pods — needs a rate-limit/memoize decision) · **a production compose
  profile**, since there is none and `--reload` currently turns a refusal into "Up but serving
  nothing" · and `GraphMemory.__init__` building an `AsyncOpenAI` without the egress guard.
  The full ordered list is §6 of the plan doc — ~~P0.1a~~ → ~~P0.2~~ → P0.1b (CSRF)
  (fail-closed startup) → P1.1 (author status) → P1.2 (harmonization provenance) → P1.3 (tier the
  register) → P2 → P3. **Nothing below P0 ships before P0 does**, because until P0.1a lands the
  system does not enforce the invariant everything else assumes. Each task is one gates-green PR
  with a stated DoD; **use a normal PR + CI, the billing block is over.**

- **⚠️⚠️ TWO OF OUR OWN BELIEFS WERE WRONG — fix these in your head first.**
  1. **CI IS NOT BILLING-BLOCKED.** It is green on every commit including `main`
     (run `31199851819`, 9m34s). **PR #81 MERGED to `main` as `f26b059`.** Multiple docs still
     say Actions is blocked and instruct you to "merge locally per ADR-006" — **that instruction
     is now WRONG.** Use normal PR + CI. (Dated historical blocks below were true when written;
     the live guidance in ROADMAP/plan is corrected.)
  2. **The "README still describes a Flask frontend" claim is TRUE — I predicted it was stale and
     was wrong.** `3e32103` removed the service, dep and package but touched `README.md` by four
     lines and never touched the Mermaid diagram. **8 live references** across `README.md`,
     `DEVELOPER_GUIDE_1.md`, `harness-claude-code/CLAUDE.md`, `docs/adr/002`, `.env.example`.
- **✅ P0.1a — CLOSED (this session).** What follows is the defect as found; **it is fixed** —
  `jd_bank_router` now sits behind `require_roles(REVIEWER, ADMIN)` (401 unauthenticated, 403 wrong
  role, never a redirect — it is a JSON surface), the compose JSON router behind `current_user`,
  and the five legacy harness routes behind a shared admin dependency (`/health` stays public).
  `reviewer_id` is gone from all three request bodies and the actor is derived from the session;
  a route-local `GateOverrideRequest{gate_id, reason}` is stamped server-side so **`overrides[].reviewer`
  can no longer be chosen by a caller either**. `make gates` **2,132 passing, 93.26%**.
  **⚠️ BUT READ THE PARAGRAPH ABOVE: these gates only bind with `cas_enabled=True`.** Until P0.2
  lands, the shipped default still grants anonymous admin, so the breach is *not* fully closed in
  the default posture.
  **How it is pinned — and this is worth knowing precisely, because the first description of it was
  wrong:** removing the router gate alone does **not** re-open the breach (the mutating routes also
  carry `actor: CurrentUser`, which 401s on its own). Mutations are **double-locked**; reads are
  single-locked. The breach regression pins the **actor parameter**; the **authorization matrix**
  (`test_authorization_matrix.py`) is what pins the **router gate** — removing it turns 7 tests red,
  including anonymous read of unpublished draft JD content. The matrix walks the live routing table,
  so **a new route with no gate fails automatically** — that is the durable artifact, and nothing
  pinned any of this before.
  *(The defect as originally found:)* `jd_bank_router` (`/jd-bank`) and the legacy harness routes carried **no gate**,
  and there is **no middleware** (verified: `grep add_middleware` → nothing). Proven with
  `CAS_ENABLED=true`: an unauthenticated `POST /jd-bank/review/{id}/approve` reaches the review
  **service** and is refused only by *business* rules (wrong status / blank reason) — never by
  auth. **On a gate-clean DRAFT it would publish.** The UI router does this correctly
  (`actor: Depends(require_ui_user)`); the JSON router was never brought along.
  **The review missed the aggravator: `service.py` writes `actor=reviewer_id` — the
  ATTACKER-SUPPLIED string — into the hash-chained `audit_log`.** The chain stays cryptographically
  intact while attesting to a forged identity, so this reaches **NN #6** too. **Nothing pinned any
  of it** — now fixed, and the matrix is what stops it regressing. `main.py` called this "ADR-008
  phase 2" while ADR-008 recorded phase 2 as DONE; **both are corrected** — ADR-008 narrows phase 2
  to "the UI, and only the UI" and gains a **Phase 4** recording what was missed, rather than
  quietly flipping itself green.
- **🔴 P0.2 — the production startup guard `settings.py` claims DOES NOT EXIST.** The comment says
  "*a startup check refuses `cas_enabled` + a dev-fake user together*"; there is no
  `model_validator`, no `ValueError`, no hits outside the three files reading the flag. Meanwhile
  `cas_enabled=False` short-circuits **before any cookie is read** and returns a transient
  **admin** — every cookieless request from anywhere is a full administrator — and `.env.example`
  carries **no auth keys at all**, so an operator following it deploys exactly that. *(The other
  five config sub-claims — dev creds, `--reload`, bind mounts, exposed ports — are all true but are
  normal dev-compose defaults; the review flattens their severity against this one.)*
- **P1 — two more that block a MEANINGFUL pilot, not just a running one.** (a) **Submit → 403**:
  the draft commits, then redirects to a reviewer-only page; `default_new_user_role` is `author`,
  so that is the *default* first-time experience, with no author-scoped status route anywhere.
  (b) **Harmonization provenance** — `seniority_bar_policy: max` is registered (HR-175) and small
  (~77/1,801 clusters, ~4.3%), but a reviewer reading one draft sees a master's requirement with
  **no indication 9 of 10 sources said bachelor's**. The human is the NN #1 control and cannot rule
  on what they cannot see. **Raised above the scalability work for that reason.**
- **➡ THE "197 OPEN" FINDING IS RIGHT, BUT THE DENOMINATOR IS WRONG — and this is our main
  disagreement with the review.** Iteration is not ratification (`ratified` needs
  `decided_by`/`decided_on`/`decision_note`, an actual SFU ruling), so the counter cannot move by
  engineering effort. But the register **conflates HR policy with plumbing**: provenance is
  **106 `our_invention` / 72 `prior_calibration` / only 19 `sfu_rulebook`**, and **57 of 197 (29%)
  sit in `comparison.yaml` + `hay_signals.yaml`** — the derived-signals adapter ADR-007 explicitly
  disclaims as *not* formal classification — plus 8 `embeddings.yaml` retrieval knobs of the
  `max_matches: 5` / `timeout_seconds: 5.0` kind. **HR should never be asked to rule on an
  embedding timeout.** Only ~**55–60** entries touch the approval bar. **Plan: add a
  `hr_policy` / `hr_informed` / `technical` tier to every entry before the workshop**, keep every
  ID, and apply the review's 12 approval packages to the `hr_policy` tier only. Nothing becomes
  unregistered; ratification becomes *achievable*.
- **➡ CUPE IS DELIBERATELY OUT — and there is a THIRD bucket nobody was discussing.** Measured over
  14,522 current-parser JDs: **JDFN served 5,416 (37.3%)** · **cupe excluded 4,440 (30.6%)**
  (HR-194, `open`) · **`employee_group` not parsed at all: 4,630 (31.9%)**. The exclusion is
  defensible — the validator only scores the JDFN template, so scoring CUPE guarantees a
  category-error mis-score. ~~**But the third bucket is OURS, not HR's:** it is exactly the parser's
  residual (v3 recovers `employee_group` for 68.1%), so for a third of the archive "the Bank serves
  JDFN" is **unfalsifiable**. Close that BEFORE the CUPE scope conversation.~~
  **⚠️ CORRECTED 2026-08-13 — THE THIRD BUCKET IS NOT OURS AND NOT CLOSEABLE BY PARSING.** Measured
  over a 300-file random sample of the 4,630: **91.3% contain no group token anywhere in the text**,
  and **1 in 300** carries a label the parser missed. The documents do not state the fact. The
  filename recovers **193 of 4,630** and that is the ceiling. The 8.7% that mention a token are
  *"Supervises one full-time CUPE support staff person"* — JDFN roles supervising CUPE, so matching
  on them would manufacture the very category error the exclusion avoids. Closing it properly means
  the **HRIS**, i.e. the HR-blocked export/FIPPA thread. Evidence:
  `docs/decisions/employee-group-residual-2026-08-13.md`.
  **The one sentence for HR is unchanged and now fully earned: the Bank serves roughly a third of
  SFU's archive, deliberately excludes another third, and for the last third the documents
  themselves do not say.**
- **Where the review is off the mark** (detail in the plan doc): live-model tests were never
  claimed to be canaries and are deselected from gates twice over — the real residual is that the
  opt-in golden targets **exit 0 when everything skipped**; the DB→queue outbox is
  **legacy-harness-only** (exactly two `enqueue_job` sites, **no JD pipeline stage uses arq**), so
  it drops in priority; the "stale hard-coded corpus counts" are hardcoded but **correct** (only
  `dashboard.py` over-claims "all 14,565" where **14,522** were scored); and the circular import is
  documented at the import site with the fix pre-scoped, so "conceal" is the wrong verb.
- **Adopted unchanged:** the review's 12 HR approval packages (applied to the `hr_policy` tier),
  its four-plane target architecture, and its acceptance-evidence definition of done for the
  benchmark. Its bottom line stands: **do not add more intelligence before adding authority,
  measurement and operability.**

---

**PRIOR (2026-08-07): A ROADMAP QUICK WIN WAS MEASURED AND DECLINED — and its stated premise
turned out to be a misattributed number.** No feature shipped; the deliverable is evidence, a
corrected roadmap, and a redirect. Decision doc:
`docs/decisions/coded-language-soft-lexicon.md`. `rules_version` **unmoved**; register still
**197** (HR-029's prose gained measured evidence — no new entry, no changed default).

- **The item.** ROADMAP proposed expanding the shipped inclusive-language meter (`19e76d3`) with
  a **Gender-Decoder soft lexicon** (Gaucher et al. 2011 masculine/feminine stems) as a new
  unhashed rulebook file + register entries. Measured over all **14,522** current-parser JDs
  through the shipped scan path before building anything.
- **⚠ THE PREMISE WAS A MISATTRIBUTED NUMBER.** The item justified itself with *"the exact-match
  list … fires on only 10/14,522"*. That is **`SFU-QUAL-BANNED-PHRASE`** (HR-041/120 — the
  neighbouring backlog row). **`SFU-LANG-CODED` fires on 11,160/14,522 = 76.8%**, confirmed
  across six commits of the committed `docs/baseline/summary.json`. The premise was wrong by
  three orders of magnitude. **ROADMAP corrected in both places.**
- **AND THE LEXICON CANNOT BE HONEST ON THIS CORPUS.** **99.50% of JDs trip BOTH word lists**
  (masculine 99.52%, feminine 99.82%, neither 0.16%); median JD is 18 vs 18; 95.7% would receive
  a lean verdict. The verdict is an artefact of two free choices, not a property of the JD: the
  unratified neutral band (neutral **4.3% → 48.9%** as it widens 0→5), and **one stem** —
  dropping masculine `decision`, the word inside SFU's own mandated `IMPACT OF DECISION MAKING`
  heading, flips the corpus from 30/37 to **19/55**; dropping feminine `respon`
  (`DUTIES AND RESPONSIBILITIES`) flips it to 57/16.
- **38–77% of hits are not gendered lean at all** (two auditable bounds over 566,492 tokens):
  `confidential`/`confidentiality` is **99.8%** of the `confident` stem (literal "confident" = 6
  tokens); `committee` is **84.5%** of `commit`; plus verbatim template headings, WJQ form
  labels, the **Athletics** unit name, the job title *Practice Leader*, and surnames under `nag`.
  The published list also double-counts every "interpersonal". **Curating does not rescue it** —
  the median JD becomes 2 vs 2, 60% of the masculine side is `independently` and 61% of the
  feminine side is `collaboratively`, both words SFU's own template asks authors to write.
- **SAME FAILURE MODE, SAME ANSWER, AS PHASE 5.9.** Two features in a row have now been saved by
  measuring before designing: a similarity threshold could not separate duplicate roles from
  unrelated ones, and a coded-language verdict cannot separate a biased JD from the template.
  **Rank or flag individually; never publish a number the data cannot support.**
- **➡ REDIRECTED — the live defect is HR-029, and it is HR's call, not ours.** Three terms SFU
  never published generate **83%** of everything the rule says: `confidential` **4,320 docs
  (29.8%)**, `individual` **3,719 (25.6%)**, `agreement` **1,678 (11.6%)** — while **16 of the 37
  terms never fire at all** and the ones HR would expect to matter barely appear (`ambitious` 29,
  `aggressive` 22, `chairman` 14, `workman` 1). The one large signal that is both real and
  mechanically fixable is the generic pronoun **`his/her`, 8,344 docs (57.5%)**. HR-029 now
  carries these numbers so the call can be made on evidence; **per the standing rule nothing was
  patched** — dropping just `confidential` + `agreement` would remove ~30% of the rule's findings,
  which is the size of the decision.
- **Also recorded:** the soft lexicon is **complementary, not redundant** — **45.9%** of the
  shipped rule's findings are invisible to it (all the pronouns and gendered occupational nouns),
  which is what `coded_terms.yaml` is actually *for*. Its genuinely-new, genuinely-coded
  contribution is ~**0.4%** of coded tokens.
- **PR [#81](https://github.com/humanaxiom/jd-assistant/pull/81)** carries the Phase-5.9 guard +
  the docs refresh described in the block below (branch
  `feat/near-duplicate-authoring-guard`, pushed). CI is still billing-blocked, so it carries
  locally-verified gates instead.

---

**PRIOR (2026-08-05): THE BANK CAN SEARCH ITS OWN OUTPUT, AND THE BUILDER NOW WARNS BEFORE
YOU AUTHOR A DUPLICATE ROLE. Plus SIX shipped commits that never got a handoff entry, and a
docs refresh across the guide, `CLAUDE.md`, the plan and AI-USAGE.**
`make gates` **2,048 passing, 93.05%**. Register **197** decisions (all `open`).
`rules_version` **unmoved** — `jd_rules_sfu_v4+90af5e27dc83`, byte-identical to the previous
block. Live DB: `canonical_jds` = **1,798 DRAFT + 4 PUBLISHED**, `review_actions` = **6**.

- **⚠ FIRST, THE GAP THIS BLOCK CLOSES.** The block below was written at `57a54a8` and six
  commits shipped after it with **no handoff entry at all** — `docs/plan.md` and
  `docs/ROADMAP.md` were equally silent. If you read this file last session, you did not know
  any of the following had happened:
  - **`802bff0` — a PUBLISHED JD can be edited.** It mints a new DRAFT; the prior version
    **deliberately stays PUBLISHED** (archiving at edit time would leave the cluster with no
    live approved JD for the whole review window) and retires only when its replacement is
    approved — so `approve` now **supersedes** any other live published version of the
    cluster, under `FOR UPDATE` with a `review.superseded` audit row. **ARCHIVED stays
    refused.** Also: advisory findings stopped being presented as errors.
  - **`89d0c74` / `3b6a71b` / `d71e333` / `46a9443` — the search overhaul.** Exact-title
    lookup in Postgres ranked **above** semantic hits (the document vectors exclude the title
    by design, which is what makes dedup title-agnostic — so a title query had nothing to
    match on); a **role-title pass**, load-bearing because **61% of harmonized role titles
    appear on no source document**; source documents **collapsed into the role** they were
    harmonized into; and same-titled roles **disambiguated by department** (791 of 1,802 roles
    share a title; department resolves 719/791, and the last 72 stay unlabelled rather than
    get an invented one).
  - **`cadfc30` — `make embed-roles`.** One `(:JDRole)` vector per cluster in a new
    `jd_role_embeddings` index (Neo4j migration **003**), reusing `serialize_document`
    verbatim. **A separate label and index from `JDDocument` on purpose** — folding them
    together works today while quietly corrupting the next `MATCH (d:JDDocument)` corpus
    count. Covers every current-version role, **drafts included** (published-only would index
    4 roles). Measured 1,802 seen / 1,797 embedded / 5 empty. **Deliberately NOT wired into
    `approve`** — publishing must not depend on the GPU, and network I/O inside the review
    transaction would hold the row lock. This retires ROADMAP's "the Bank can't search its own
    output."
- **➡ NEW THIS SESSION — the near-duplicate authoring guard (Phase 5.9).** While an author
  composes, the Builder shows **"Roles SFU already has"**: existing harmonized roles that look
  like the one being written, each with *Start from this role →*, plus one non-vector fact —
  how many roles carry **exactly this title**, across how many departments. Advisory only: it
  never blocks submission and never touches the validator's verdict (NN #1/#3).
  `jd_bank/composer/duplicates.py`, config `dedup.authoring_guard`, registered **HR-195**
  (`max_matches: 5`), **HR-196** (`min_draft_chars: 500`), **HR-197**
  (`timeout_seconds: 5.0`), all `open` / `our_invention`. `dedup.yaml` is unhashed, so
  `rules_version` did not move.
- **🔴 THE DESIGN WAS DECIDED BY MEASUREMENT, AND THE OBVIOUS DESIGN IS WRONG. A SIMILARITY
  THRESHOLD CANNOT WORK ON THIS CORPUS.** Measured over the live index (1,797 role vectors)
  *before* anything was specified: same-title role pairs — genuine duplicates, n=2,618 —
  median cosine **0.9335**, while a role's nearest **unrelated** neighbour (n=200) medians
  **0.9604**. *The unrelated role scores HIGHER than a real twin.* Any cutoff is a constant: at
  0.90 the guard fires on **99.2%** of drafts at **22%** precision; at 0.97 it still fires on
  24% and loses most true duplicates. A top1−top2 **margin** rule fails identically (0.0065 vs
  0.0052). But **ranking works** — for the 790 roles with a same-title sibling it is top-5 for
  76%, top-10 for 84% — and a **500-char draft retrieves better than the full document**
  (14/20 vs 11/20 in top-5), which is where `min_draft_chars` comes from. **So the panel ranks
  and shows NO score, NO percentage, NO cutoff.** A number here would repeat the defect
  `89d0c74` already fixed, where a 0.013 spread rendered as "81%" on every row. The absence is
  pinned by a test; `dedup.yaml` and HR-196 carry the numbers so nobody re-proposes it.
- **A live trap, recorded:** Ollama embeds `""` into a **constant vector that is a plausible
  nearest neighbour to everything** — every empty query returned the identical role at exactly
  **0.8038**. `roles.py`'s "NEVER embed `''`" guard is load-bearing, and `retruncate_within`
  returns `""` when the first unit exceeds the target, so it is easy to reintroduce. The guard
  refuses empty/whitespace text **unconditionally**, separately from the length floor.
- **BOTH MERGE-BLOCKING REVIEWS RETURNED DEFECTS, AND THEY WERE REAL** (Opus correctness +
  Opus security; the model strategy's "downgrade the writer, never the checker" earned its
  keep again). The four worth remembering:
  1. **A hung Ollama could take the whole Builder down.** `EmbedClient` builds `AsyncOpenAI`
     with no `timeout=` → read 600 s × 2 SDK retries × `_MAX_ATTEMPTS 3` ≈ **90 minutes** of a
     held request *holding a checked-out DB session*. `connect=5.0` means a *refused*
     connection fails fast, so "Ollama down" was never the risk — a host that **accepts then
     stalls** is. The degrade path covered *raise* and never covered *hang*. Fixed with
     `asyncio.wait_for` at the guard's call site (HR-197). **`/compose/search` and
     `/assist` share the missing timeout — pre-existing, still open.**
  2. **`POST /new` 500'd when a client could not be *constructed*** — dependency solving runs
     before the route body, so the guard's `try/except` never saw it. Fixed with optional
     factories that `logger.exception` and return `None`, so the Builder survives while an
     egress misconfiguration is still recorded rather than silently normalised.
  3. **The no-percentage test — the one invariant the whole feature rests on — covered 29% of
     the panel** (a ±400-char window over 2,731 chars; row 5 sat at anchor+1520), and its
     stated justification was **factually false** (it claimed the page carries the duty's
     `60%`; measured, all 9 `%` are `width:100%` in the stylesheet). Now slices the whole panel.
  4. **`exclude_cluster_id` — the headline behaviour — was unasserted**: every route-level fake
     took `**kwargs` and discarded them, so wiring it to `None` kept the suite green.
- **DOCS REFRESHED (the six-commit gap above is why).**
  - **`docs/OPERATOR-GUIDE.md`** (+ re-rendered `operator-guide.html`; `make guide-check`
    green). Fixed a **falsehood** — it told reviewers "saving creates a new draft version; the
    prior is archived", untrue since `802bff0`. Added a whole **missing section: the content
    library** (`/library`, role detail, source-JD reader, `/archive`) — a user-facing surface
    with its own router and nav entry that the guide never mentioned. Added `make embed-roles`,
    migration `003`, and `make guide`/`guide-check` (never documenting how to re-render the
    guide is how it went stale).
  - **`CLAUDE.md`** — the "Neo4j — roles, do not conflate" block listed **one** vector index
    and never mentioned `jd_role_embeddings`, in the section whose entire job is preventing
    that conflation. Now names both. The register line hardcoded "192 entries" and had rotted
    twice; it now defers to the generated register's own header — **do not reintroduce a
    hardcoded count.**
  - **`docs/plan.md`** — Phase **8.2 adjudicated: goal met, mechanism superseded** (separate
    `(:JDRole)` index, not `kind=canonical` upserts), and no-embed-on-approve recorded as a
    **decision, not a gap**. Corrected "zero canonicals are published" (there are 4). New 5.9.
  - **`docs/AI-USAGE.md`** — second embedding path added, and the honest framing for an
    AI-usage doc: **the two highest-ranked search passes are plain Postgres `ILIKE`, so the
    top results are not AI-derived at all.** Mermaid verified by rendering (4/4).
- **⚠ STILL OPEN — the harmonized roles library and parser v3, and it is SMALLER than the
  block below claims.** That block prices propagating v3 into the roles at a ~44h LLM
  re-cluster. **Measured against the live DB this session: of 1,802 roles, 72 titles exceed 60
  chars, 21 are clearly prose, 1 is `Untitled Position` — ~4%, not the 34% archive-wide
  defect.** LLM harmonization already cleaned most of it. Re-clustering is still defensible
  for `title_family`/cluster quality, but **it is a ~4% cosmetic win, not a blocker** — price
  it accordingly, and note it still lands new drafts alongside the existing 1,802 (needs a
  prune) and that `review_actions = 6` means the no-clobber path is live.
- **Follow-ups this session deliberately did NOT do:** the missing timeout on `/compose/search`
  and `/assist` (pre-existing, same root cause as #1 above) · no rate limit on the embed path
  (authenticated + CAS-gated, so amplification not a hole) · `embed_stamp` parity is never
  verified at query time, so a stamp change would silently compare incomparable vectors
  (pre-existing, matches `search.py`) · `cloned_from_cluster_id` is dropped by `assemble_jd`,
  so clone lineage is lost at submit (an NN #6 opportunity) · `docs/status/*` stops at
  2026-07-24 · `docs/rulebook/rulebook/` is a byte-identical duplicate directory tracked since
  Phase 0.
- **THE CRITICAL PATH IS UNCHANGED AND STILL EXTERNAL:** HR has ratified **nothing** (all 197
  `open`), and **4 published JDs out of 1,802 roles is a smoke test, not the pilot.**
  Ratification · the 4.5 pilot · per-group grade scales · the HRIS export + FIPPA · footer /
  territorial-acknowledgement sign-off · GitHub Actions billing.

---

**PRIOR (2026-08-02, later): THE PARSER IDENTIFICATION FIX — parser `jd_segmenter_v3`. The
34% paragraph-title defect is GONE, and it was never a title bug: the modern SFU template
keeps its ENTIRE identification table in the docx HEADER, which extraction skipped.**
`make gates` **1,982 passing, 93.63%**. Archive re-parsed at v3 and re-baselined.

- **Root cause, measured over all 14,565 files (not sampled).** `Position Title:`,
  `Position #:`, `Department:`, `Employee Group:`, `Grade:` live in `header*.xml`;
  `_extract_docx` walked `doc.element.body` only. **4,968 of 9,948 `.docx` carry
  `Position Title:` in the header and in NO body line** — a clean partition, and exactly the
  set whose title parsed as a paragraph (`_fallback_title` took the first content line: the
  About-SFU banner or the Position Summary prose). 100% of sampled paragraph-titled docs
  took that path — zero came from a mis-parsed label.
- **The fix** (`jd_bank/ingest/extract.py`): a header part is read **only** when
  `_is_identification_block` recognises it (a title label, or ≥2 distinct identification
  labels), and is emitted first under the parser's own `IDENTIFICATION` heading — which is
  what finally SCOPES identification extraction to a real block instead of the whole
  document. Table rows are split **per label/value pair**, because the template packs two
  pairs on one row (`Employee Group: | APSA | Grade: | 13` — how 874 of 876 grade-bearing
  headers are written). **Header prose and ALL footers stay excluded**; the old body-only
  invariant test was NARROWED, not deleted, and now pins both halves.
- **Two more defects found by checking the re-parsed DATA, not the green run.** (a)
  `Position #s:` is a real spelling and the label regex's optional colon matched empty, so
  the capture took the plural `"s"` as the value — **243 rows** had `position_number = "s"`
  (213 of them pre-existing at v2; the header change amplified it). Fixed with `s?`, now 14.
  (b) With no first-page header, the **running** header (`Position #: … <page no>`) was
  admitted, giving 15 docs `position_number = 2` — the page number. Fixed by the ≥2-label
  gate. **The first baseline run was KILLED mid-flight** when these surfaced rather than
  commit HR-facing artifacts built by superseded code.
- **A third, unrelated defect the same measurement surfaced:** 24 UTF-16LE `.txt` files
  decoded to `ÿþP%P%P%…` — latin-1 accepts any bytes, so the ladder never reached a correct
  codec. `_decode` now checks the UTF-16 BOM up front.
- **Measured effect (v2 → v3, all 14,522 parsed rows):** paragraph titles **4,986 → 148**
  (and most of that residual is legitimately LONG titles, not defects) · `position_number`
  34.8% → **68.3%** · `employee_group` 35.6% → **68.1%** · `department` 49.9% → **60.8%** ·
  structured `classification` 2,323 → **3,049**.
- **⚠️ THE AUDIT WAS WRONG ABOUT APSA GRADES — corrected.**
  `docs/audit/data-state-and-grade-2026-08-01.md` concluded the APSA grade is "not extracted
  anywhere (0/600 in text)". It was looking at BODY text: **876 documents state a JDFN grade
  in the header**, and v3 parses **687 APSA + 34 APEX**. Both the audit and the HR-facing
  `docs/decisions/grade-scales-hr-ask.md` (which told HR these groups "almost never" state a
  grade) carry corrections. `classification.py` gained the bare `Grade:` field — trustworthy
  ONLY because a real bounded identification block now exists.
- **RE-BASELINED, and THE HR HEADLINE DID NOT MOVE.** The 874-JD cohort is byte-identical:
  approval **78.6%**, median **79.05**, **81A/551B/240C/2D**. Archive-wide median **58.47**
  unchanged. Expected — the validator scores CONTENT sections and this fixed IDENTIFICATION
  metadata. The one score-side movement is the fix working: title-keyed gates now see a
  title (`SFU-AUTH-TITLE-HR` 513→528, `SFU-GATE-SENIOR-TITLE` 81→86, REGISTRAR 35→37,
  EXEC-DIR 14→16; findings 148,131→148,155) — ~24 docs were evading title gates by being
  unreadable. `config_stamp` also moved, but **not from this run**: `segmentation.yaml`
  changed in `29a4c4e` (HR-194) after the previous baseline, so the artifact was stale.
- **NOT over-claimed:** the **2,053 `"Untitled Position"` rows are UNCHANGED** — CUPE/WJQ
  questionnaires keep identification in a body table, not a header (the separate WJQ
  workstream). Legacy `.doc` files still fall back to banner text or a bare position number
  (~135). Counting every failure mode, unusable titles went **~50% → ~16%**, and 2,053 of
  that 16% is the known WJQ gap. **`_fallback_title` was deliberately NOT hardened** — a
  prose heuristic would turn legitimate long titles ("Executive Secretary to the Associate
  Vice-President, Academic, and Chief Information Officer") into `Untitled Position`.
- **✅ `make embed` RUN — and it was a NO-OP, BY DESIGN. THE VECTORS WERE NEVER STALE.**
  Result: **`0 embedded, 14,404 unchanged, 0 embed calls`**. The reason is the point:
  `embeddings.yaml` sets **`include_title_in_document: false`** and restricts
  `document_sections` to the seven CONTENT sections — so the embedded text excludes title,
  position number, department, employee group and grade *on purpose* (it is what gives
  `bank/similarity` its "title-agnostic by construction" guarantee). v3 changed exactly that
  excluded metadata, so every `text_sha256` is identical and skip-first correctly did
  nothing. **This retires the "embed-published-canonicals / re-embed" worry for this change:
  search and dedup Tier-3 were never running on stale vectors, and there is no GPU debt.**
  Same root cause as the unchanged baseline cohort — the validator scores content, the
  embedder embeds content, and this fix repaired identification.
  - **`docs/embeddings/summary.json` was deliberately NOT updated.** The run wanted to write
    `documents_embedded: 0 … texts_backed_off: 0` over the full run's record (14,404 embedded,
    1,032 calls, **11 backed off — the HR-126 evidence**). That file is the committed audit
    trail of the CORPUS's embedding state, not of the last run, and zeros there read as
    "nothing is embedded" when 14,404/14,404 nodes verifiably carry a vector. Reverted.
  - **⚠️ Vector nodes still carry `parser_version = jd_segmenter_v2` and a `parsed_jd_id`
    pointing at v2 `parsed_jds` rows** (nothing was rewritten, so nothing restamped). Harmless
    today — the vector content is identical either way — but **do NOT prune the v1/v2
    `parsed_jds` rows without re-embedding first**, or that provenance link dangles (NN #6).
- **➡️ STILL OPEN — the harmonized roles library.** The fix reaches the **source-JD reader and
  archive browser** now (they read the newest parse), and **live-verified in the UI**: modern
  APSA docs render "Database Administrator" / "Legal Counsel, Research Services" where they
  showed "We are Canada's engaged university…". It does **NOT** reach the **roles library**,
  which reads `canonical_jds` and still holds v2-derived paragraph titles — the surface HR was
  told to read JD content on. That needs `near-dup`/`dedup-role` → `cluster` →
  `canonical-drafts` (**~44h** LLM run last time; the embed prerequisite is already satisfied,
  see above). Two complications: re-clustering changes membership and `cluster_id` is a uuid5
  OF that membership, so new drafts land **alongside** the existing 1,802 and need a prune
  (same as 2026-07-21); and **`review_actions` is now 6, not 0** as older notes say — a human
  HAS touched the queue, so the producer's no-clobber path is live. Better titles should
  genuinely improve `title_family` and therefore cluster quality, so it is worth doing —
  schedule it deliberately rather than as a side effect.
- **Note for the next session:** `parsed_jds` now holds v1 + v2 + v3 (43,566 rows). Nothing
  reads v1/v2 any more (everything selects on `PARSER_VERSION`) except the library's
  newest-by-`created_at` lookup, which correctly gets v3. Pruning v1/v2 is optional cleanup.

---

**PRIOR (2026-08-02): SESSION SUMMARY — content library, grade capture (end-to-end), + quick
wins. All on `main`, pushed; CI billing-blocked so merged locally per ADR-006. `make gates`
1972 passing, 93.61%.** This session was HR-usability-driven and shipped a lot; the detailed log
is in the PRIOR blocks below. What's new since 2026-07-31, at a glance:

- **The browsable JD Bank (content library).** HR can now READ the JD content, not just stats:
  🏦 JD Bank nav → `/jd-bank/ui/library` (all harmonized roles, searchable + **click-to-sort**) →
  role detail (harmonized JD + the source JDs it distills) → **source-JD reader** (`/jd/{id}`, the
  first content viewer the app ever had) + a flat **`/archive`** browser. All read-only (NN #1).
- **Clone the HARMONIZED role** (not the raw archive parse): `clone-role/{cluster_id}`; Builder
  search prefers it. Fixed the "cloning a green JD fails" report (was cloning the raw parse).
- **No reliable job-level facet exists → level column removed; A–D relabeled "Quality"; scores
  rounded.** (group empty, band mislabels, APSA grade absent — all measured.)
- **GRADE CAPTURE — Phase A + Steps 1–5 COMPLETE.** Structured
  `SFUJobDescription.classification{scheme,value,source}` + a group-aware parser extractor;
  **2,323 CUPE grades backfilled** onto `parsed_jds`; grade ENTRY in the Builder + reviewer edit
  (`source=entered`); an HRIS-import scaffold (`grade_import.py` + `scripts/import_grades.py`);
  and surfacing with provenance on the reader/role/archive. **Two external blockers:** the
  per-group grade SCALES (HR — see `docs/decisions/grade-scales-hr-ask.md`, the 15-min ask) and
  the HRIS export + FIPPA review. Config-level `grades.yaml`+register deferred until HR gives real
  scales (the drift-checked register can't hold guesses). Full audit: `docs/audit/data-state-and-grade-2026-08-01.md`.
- **Quick win — inclusive-language meter** in the Builder panel: the coded/gendered findings the
  validator already raises (`coded_terms.yaml`, `SFU-LANG-CODED`) pulled into a prominent
  "N flagged / clear" meter with suggestions. Deterministic, advisory, no new decision.
- **Docs:** `docs/AI-USAGE.md` (where LLMs/embeddings are used + guardrails, with mermaid diagrams);
  `docs/decisions/grade-scales*.md`.

**THE CRITICAL PATH IS STILL EXTERNAL** (nothing I can advance solo): HR ratification of the
register (all 192+ `open`) · the 4.5 HR pilot · the per-group grade scales · the HRIS export +
FIPPA · footer/territorial-acknowledgement sign-off · GitHub Actions billing. **Top UNBLOCKED
next items** (see `docs/ROADMAP.md`): the Gender-Decoder soft lexicon (register-bearing expansion
of the inclusive meter) · near-duplicate authoring guard · embed-published-canonicals write path
(post-pilot value) · the parser paragraph-title fix (the upstream cause behind titles/levels).

---

**PRIOR (2026-08-01, session detail): THE BROWSABLE JD BANK — HR can finally READ the content, not just stats;
+ clone the HARMONIZED role; + level-band facet.** Driven by HR pilot feedback ("the Builder is
better, but the dashboards are meaningless — where are the actual JD files? clusters just show
docx filenames I can't open"). All read-only (NN #1), no rulebook/GPU change, `make gates`
**1946 passing, 93.55%**. Live-verified over real full-run data (1,802 roles, 14,565 source docs).
- **Content library (`jd_bank/library/` + `api/routes/library.py`).** New **🏦 JD Bank** nav (first
  item). `/jd-bank/ui/library` = searchable/paginated home of all harmonized roles → `/role/{cluster_id}`
  (canonical rendered readable + the source JDs it was distilled from, each → `/jd/{source_document_id}`,
  the **source-JD reader** — the first content viewer the app has ever had). `/archive` = the flat
  14,565-file browser. Renders stored `SFUJobDescription` via `render_sfu_jd_text`; roles list reuses
  the stored `change_log["validator"]` roll-up (no recompute). Cross-links: search "Read →", review
  detail "→ this role & its source JDs".
- **Clone the HARMONIZED role, not the raw archive JD** ("archive is transitional until we harmonize
  all"). `composer.load_role_clone_answers(cluster_id)` + `cluster_id_for_source`; route
  `/jd-bank/ui/compose/clone-role/{cluster_id}`; "🧱 Start a new JD from this harmonized role" on the
  role page; Builder search "Start from this" now prefers the harmonized clone (raw-JD clone only for
  singletons). Fixes the "cloning a green JD fails" report — it was cloning the raw parse (177-word
  summary, 1 duty) vs. the harmonized canonical (compliant); **same validator both sides** (NN #3),
  different *content*.
- **No reliable job-level facet exists — column removed.** Chased a "level" column through group →
  band → seniority and each failed: employee group is empty (0/2000 filenames match), the stored
  `cluster.constraint_metadata.bands` is computed from the RAW (often paragraph-)title so it
  mislabels (coordinator → "VP"), classifying the CLEAN title only maps ~30% AND still mis-fires on
  office names ("Office of the Vice-President" → VP), and the **APSA grade 1–15 is not extracted
  anywhere** (0/600 in text, `content.grade`/`parsed.grade` all `None`). So the level column was
  **removed**; the group column was dropped from every screen. The A–D column was **relabeled
  "Quality"** (it's the validator quality grade, NOT a pay grade) and scores are rounded (1 dp).
  ⚠ The real upstream bug is the **parser: many titles parse as whole paragraphs** — fixing that
  would make titles/levels/the reader header all correct.
- **Roles library columns are now click-to-sort** (server-side, no JS): Role/Sources/Score/Quality/
  Status headers toggle asc/desc via `?sort=&dir=`; `list_roles` gained `sort`/`direction`
  (`_ROLE_SORTS` whitelist, unknown → title asc; nulls last; stable title+id tiebreak).
- **DATA-STATE REVIEW (grade/level) — `docs/audit/data-state-and-grade-2026-08-01.md`.** Measured
  the whole corpus + Neo4j + the source archive: grade/level (pay-mapped, per-group) is **missing
  and unreliable everywhere** — Postgres `grade` 3% and garbage, canonical roles ~0%, Neo4j has no
  domain metadata, source docs carry grade for **CUPE ~64% (parseable)** but **JDFN/APSA largely
  absent** (assigned post-authoring, lives in the HRIS). Also documented full field completeness
  (position_number 35%, department 50%, employee_group 36%, **34% paragraph titles**). The doc
  lays out a 4-phase capture plan (structured `grade{scheme,value,source}` + group-aware parser +
  register the scales → Builder/review entry where absent → optional HRIS import (FIPPA) → surface
  with provenance) and the HR decisions to register.
- **GRADE CAPTURE — Phase A (slice 1) LANDED.** New structured `JobClassification{scheme,value,source}`
  on `SFUJobDescription.classification` (ADD-only, `extra="ignore"` → backward-compatible with the
  29k existing rows; supersedes the noise `grade` string, which stays as legacy). New group-aware
  `jd_core/parser/classification.py::extract_classification` wired into BOTH parsers (segmenter +
  wjq), fed the identification block. Verified end-to-end over the real archive: **CUPE ~58%
  recovered clean (scheme=cupe, values 6/7/8/10/11), JDFN honestly None** (no manufactured grades).
  Extraction patterns live in the parser layer (code, like `headings.py`) — NOT a registered
  decision; `rules_version` untouched. Goldens updated (`classification: null`); the review
  `_content_from_form` reconstructs it as `None` (Phase B adds the editor). `make gates` **1961
  passing, 93.58%**.
- **Grade capture Steps 1–2 DONE.** (1) **Backfill complete** — `scripts/backfill_classification.py`
  re-extracted the archive and wrote `classification` in place onto v2 `parsed_jds`: **2,323 grades
  (2,322 CUPE + 1), values 3–12, 0 errors** (idempotent; parser_version + downstream untouched).
  (2) **Grade-scale decision recorded** for HR in `docs/decisions/grade-scales.md` (the config-level
  `grades.yaml` + register is deferred until HR fills the real per-group scales — encoding guessed
  scales into the drift-checked register would block the build).
- **Grade capture Step 3 (Phase B) DONE — grade ENTRY, both surfaces.** `ComposerAnswers.grade` +
  `assemble._classification` (scheme from `employee_group`, `source="entered"`) → the Builder gained
  a Grade question; `jd_to_answers` carries it on clone. Reviewer edit: the Grade field now drives
  the STRUCTURED `classification` (`ui._classification_from_form`), and the legacy free-string
  `grade` is deprecated (set None). `make gates` **1963 passing, 93.59%**.
- **Grade capture Steps 4–5 DONE — the whole 1–5 chain is complete.** (4) **HRIS importer scaffold**
  — pure `src/jd_bank/grade_import.py::parse_grade_csv` (position_number→`JobClassification`,
  `source="hris"`) + thin CLI `scripts/import_grades.py` (applies to `canonical_jds` by
  position_number). **A scaffold: the real run needs the HR export + a FIPPA review** (grade is
  compensation data; position_number is only 35% populated). (5) **Surfaced with provenance** —
  `classification` on the source reader + role detail (conditional line: value · scheme · source)
  and a **Grade column on the archive browser**; live-verified: CUPE source JDs show their backfilled
  grade (e.g. `7 · cupe · parsed`). Deliberately NO roles-library Grade column yet — JDFN roles carry
  no grade until reviewers enter them (an always-empty column would repeat the earlier UX complaint);
  add it once grades populate. `make gates` **1970 passing, 93.60%**.
- **On a branch, fast-forwarded to `main`** (CI still billing-blocked → local merge per ADR-006).
  Committed as ONE gates-green unit (the three parts interleave across shared templates/tests, so a
  per-part split would produce non-green intermediate commits — NN #4). Memories written:
  `hr-wants-content-not-stats`, `jd-bank-content-library`.

**PRIOR (2026-07-31): review-UX fixes shipped + NEXT PHASE planned (Phase 8 — the Published JD
Bank).** All on `main`, `make gates` **1921 passing, 93.45%**.
- **Review approve/fix UX fixed (`3efe837`).** A reviewer clicking Approve on a draft blocked by an
  *overridable* gate got a raw exception dump and no guidance. Now: a plain-language banner
  (`_friendly_error` maps every service error to an actionable sentence — no raw dump); the
  blocking-gates panel explains *overridable* (waive with a reason) vs *not overridable* (must Edit);
  the Approve panel is state-aware — approvable → a button; ANY non-overridable gate → "cannot be
  approved as it is" + names the gate + guides to Edit (no dead-end waiver form); all-overridable → a
  per-gate waiver field (`required`) beside each gate's reason. Transport/presentation only (service
  stays sole authority, NN #1/#3).
- **Jump-to-Edit link (later commit).** The blocking-gate guidance now links to an `#edit` anchor on
  the Edit form (coarse jump; per-gate→specific-field is Phase 8.3c). Both TDD'd.
- **➡ NEXT PHASE — Phase 8, planned in [`docs/plan.md`](docs/plan.md) §Phase 8.** The **final JD
  Bank**: a browsable/searchable home for every APPROVED canonical JD (`/jd-bank/ui/library` · 🏦 JD
  Bank nav), the published-JD view (provenance + version history + export + clone + propose-update),
  the **embed-published-canonicals** write path (so the Bank can search its own output — the
  prerequisite deferred on 2026-07-29), and **review-experience upgrades** (word-level diff · a
  cluster→versions + related-roles structural sidebar · per-gate→field jump-links). **Start with 8.1
  (the library — no GPU, self-contained).** Write `docs/tasks/phase-8-published-bank.md` when picking
  it up. Everything is read-only over already-approved rows (NN #1); embeddings stay self-hosted (NN
  #5). *(The 4.5 HR pilot + HR ratification remain the external critical path — Phase 8 is the
  engineering that makes an approved JD actually usable once the pilot starts publishing.)*

**PRIOR (2026-07-28, later): STRUCTURED PER-FIELD EDITORS — the raw-JSON/lossy-form blocker is
GONE, both surfaces.** This was ROADMAP milestone-1's first task ("Make the pilot runnable" — *a
reviewer cannot pilot against a JSON textarea*). Two focused slices, each TDD'd, full `make gates`
green, on branch **`feat/builder-structured-fields`** (commits `6e15c9a`, `f138f18`):
- **Slice A — Builder form (`6e15c9a`).** Duties and knowledge/skills are now STRUCTURED repeatable
  rows, not one-item-per-line textareas: a duty row captures its `action_verb` (what the action-verb
  gate checks) + `allocation` (the `(NN%)` the allocation gate reads); a knowledge/skill row captures
  its Toolkit proficiency `modifier` — the fields `ComposerAnswers` always carried but the flat
  textarea silently dropped. Rows post as index-aligned parallel arrays (`keep_blank_values`);
  "add a row" is blank-row padding (no client JS). Modifier options are rulebook DATA
  (`qualifications.yaml` 5.1/5.2, NN #2). Clone + validation-error re-renders repopulate the rows.
- **Slice B — reviewer edit view (`f138f18`).** Replaced the raw-JSON `<textarea name="content">` with
  a per-field editor over the FULL `SFUJobDescription`. `_content_from_form` reconstructs EVERY field
  (incl. per-duty `how_why`/`frequency`, `grade`, `position_number`, the presence booleans) — a
  partial editor that dropped any of those on save would be *worse* than JSON (silent corruption). A
  round-trip test feeds the reconstructed dict through the real model and asserts `model_dump` equals
  it. `service.edit` stays the sole authority + re-validates (validator-as-oracle NN #3).
- **Transport/presentation only:** no knob, **`rules_version` untouched**, nothing publishes (NN #1).
  Latest `make gates`: **1905 passing, 93.45%.** One reviewer nit (a dangling `<label for>`) fixed in
  Slice A. **Follow-up recorded:** `_column`/`_at`/`_lines`/`_pad_rows` are now duplicated across
  `ui.py` + `compose_ui.py` — consolidate into a shared `_forms.py`.
- **On `main`** (`74a31a7..51f8e5a`, pushed) — merged locally per the billing-blocked workflow below.
- **Concurrent double-approve test DONE (`7ce53db`, on `main`).** Milestone-1's next item: a
  mutation-verified integration test (`test_review_service.py::test_concurrent_approves_...`) proves
  the `SELECT ... FOR UPDATE` lock in `_get_for_update` serializes two concurrent approves of one
  DRAFT — exactly one publishes, the other gets `IllegalTransitionError`. The race is orchestrated
  (A holds the lock uncommitted, B blocks, then A commits) because a plain `asyncio.gather` is a
  false-green; verified RED with the lock flag flipped off. `make gates`: **1906 passing, 93.45%.**
- **Version-diff view DONE (`main`).** Pure `jd_core/bank/version_diff.py` (`build_version_diff` —
  a COMPLETE per-section serialization, so a toggled footer boolean or cleared grade that
  `render_sfu_jd_text` drops is still caught) + `review.get_version_diff` (diffs a canonical against
  the highest-version PUBLISHED canonical of the same cluster with a lower version) + a standalone
  `GET /jd-bank/ui/review/{id}/diff` page (side-by-side before/after per changed section, empty-state
  when there's no prior approved version) linked from review detail. `make gates`: **1919, 93.48%.**
- **Milestone-1 REMAINING:** embed-published-canonicals write path (S/M — and note it indexes an
  EMPTY set until the pilot publishes a canonical; needs live Neo4j/Ollama to verify, so its value is
  post-pilot) · refresh/reconcile the billing-blocked PRs.
- **⚠ STALE-DOC CORRECTION (verified 2026-07-29):** the roadmap/handoff line "fix the three
  'our-defect' review-packet items + re-baseline" was **already done in Phase 2.6** — confirmed
  against the rulebook: HR-120 `banned_phrase_scope: qualifications`, HR-121 `SFU-STRUCT-HOW-WHY
  evaluable: false`, HR-122 `era_new_max_year: 2023` (4th band); the 874-cohort baseline reflects the
  corrected numbers; `POST-REVIEW-CHANGE-PLAN.md` says "steps 1–3 are DONE". The REMAINING
  review-packet decisions (1, 1b, 2b, 3, 4, 6, 8) all **need HR** — external, not engineering. Per the
  standing rule ("until HR rules, we change nothing") there is **no legitimate code change** to make
  there without ratification, so do NOT pre-emptively flip gates (e.g. Decision 3's NO-PLACEHOLDERS)
  ahead of HR.

**PRIOR (2026-07-28): AUTH/RBAC + the whole Builder UI are DONE; the roadmap + operator guide are
written. The system is now credible as an app — the critical path is HR ratification + the first
human pilot, not more infrastructure.** Latest `make gates`: **1892 passing, 93.36%.** `main` is in
sync with `origin`, **no open PRs** (the old billing-blocked ones are closed). CI is still
billing-blocked, so everything below merged **locally per ADR-006** (`make gates` is CI-identical)
and was pushed straight to `main`.

**➡ START HERE for what to build next: [`docs/ROADMAP.md`](docs/ROADMAP.md)** — current backlog by
area, quick wins (S), high-value features grounded in peer-university systems (M/L), explicitly-OUT
items that would breach an invariant, strategic bets, and a 5-milestone sequence. The next milestone
is **"Make the pilot runnable"** — starting with the **structured per-field editor** (kills the
raw-JSON blocker in the Builder form + reviewer edit view).

**What landed since 2026-07-24 (all on `main`):**
- **HR-126 `max_chars` RESOLVED** (`729acb0`, was PR #80) — HR-193 fallback ladder `[8000,6000,4000]`;
  re-embedded on the freed GPU, `bad_requests` 11→0, `texts_backed_off` 11. `rules_version` untouched.
- **Phase-5 Builder UI fully wired** — Export `.docx` (`a9b85de`), LLM summary-assist (`5ad1cc6`),
  search+clone (`7b795ae`); **per-section "why" + human labels** replacing the raw `needs_attention`
  enum (`bbba094`); **findings clickable → jump to the offending field** (`b8f388b`, `a043222`).
- **Builder correctness fixes** — composer now inserts the mandated **Relationships header**
  (`SFU-GATE-REL-HEADER` was previously unsatisfiable in the Builder — `399c89e`); **clone defaults
  boilerplate ON** so a clone starts a compliant JD (`6a67a47`). Parser instruction-cruft on clone is
  flagged (the validator already surfaces it as `SFU-STRUCT-PLACEHOLDER`) — a parse-quality task, not
  band-aided.
- **HR review packet refreshed** (`4f38f57`) — counts/hash brought current; **CUPE scope (HR-194)
  surfaced as a decision** HR should see (the Bank scores/authors only ~70% of the archive).
- **AUTH / RBAC — the big one (ADR-008, `docs/adr/ADR-008-auth-cas-rbac.md`).** SFU **CAS SSO** (v2
  serviceValidate), server-side revocable **sessions**, roles **author/reviewer/admin** (M2M),
  `require_ui_user`/`require_ui_roles` gates (Builder+dashboards = any signed-in; review queue =
  reviewer/admin; user admin = admin), **login/logout in the nav**, **user-management admin** UI
  (list/roles/enable-disable, self-lockout guards), **first-admin bootstrap** via `BOOTSTRAP_ADMINS`.
  The review/compose actor is now the **authenticated user** (not a form field), and `audit_log` is
  **hash-chained tamper-evident** (`verify_audit_chain`; migration 0005). Migrations `0004`
  (identity) + `0005` (audit chain) applied to the dev DB. Commits `d55d797` / `64e9036` / `9333f77`.
- **CAS enabled for testing** (`aca0146`) — fixed a latent settings bug (`NoDecode` for comma-sep list
  env vars; `BOOTSTRAP_ADMINS=asalah` crashed startup otherwise). CAS config is in compose (OFF by
  default; set via the **gitignored `.env`**), and the `gates` service pins CAS off so tests stay
  hermetic. Live-verified: unauth → `/login`, `/cas/login` → `cas.sfu.ca` with the right service URL.
  **Untested in prod:** the real `serviceValidate` round-trip (localhost may not be a whitelisted CAS
  service; `CAS_VERIFY_TLS=false` if the container's cert chain rejects it; `CAS_DEV_FAKE_USER` is the
  fallback that exercises the session machinery without SFU).
- **Operator guide** — `docs/OPERATOR-GUIDE.md` is the source of truth; **`make guide`** renders the
  SFU-branded, print-friendly `docs/operator-guide.html` (`make guide-check` is the drift gate); the
  app serves it at the in-app **📖 Guide** nav link (`/jd-bank/ui/guide`). Features, personas, and
  admin/server-access indicators.
- **ROADMAP.md** (`d16d8ab`) — see the START HERE pointer above.

**Current live state:** app at `:25800`; **CAS is ON** in the running container (`.env`), so you sign
in via SFU CAS — set `CAS_ENABLED=false` in `.env` + `docker compose restart api` to return to the
frictionless dev-admin mode. 4 demo users seeded (mstanger/eleung/sza229/sofia_espana, author+reviewer)
— dev-DB data only, not committed.

**The critical path (from ROADMAP):** SFU HR has ratified **nothing** (all 192+ decisions `open`) and
**zero canonical JDs are published**. Ratification + the 4.5 pilot gate most downstream value; three of
the nine review-packet decisions are OUR defects to fix + re-baseline first. Everything of lasting
value is cheap to build but expensive to *sign* — sequence the engineering to make the signing possible.

---

**PRIOR (2026-07-24, latest+1): PHASE-5 BUILDER UI FOLLOW-UPS WIRED (5.8a/b/c) — the guided form
now calls the search/assist/export routes it only had JSON endpoints for.** Three dependency-free UI
wrappers on `main` (each TDD'd, full `make gates` green, merged locally — GitHub Actions still
billing-blocked, so these are **local commits pushed to `origin/main`, no PRs**):
- **5.8a Export .docx** (`a9b85de`) — `POST /jd-bank/ui/compose/export` rebuilds the draft from the
  same hidden `answers_json` the check step writes and streams the official SFU `.docx`; button added
  to the live-compliance panel. Pure rendering, nothing published (NN #1); a tampered field re-renders
  instead of 500.
- **5.8b LLM summary-assist** (`5ad1cc6`) — `POST /jd-bank/ui/compose/assist`, reached by an
  "✨ Improve summary" submit in the guided form (a `formaction` override carrying all in-progress
  fields). Asks the self-hosted, egress-guarded LLM (NN #5) for a better Position Summary, **applies it
  to the textarea for the author to review**, shows an assist panel (word count · grounding ·
  model/prompt provenance) + the validator's fresh verdict on the draft-with-suggestion (oracle, NN #3),
  and carries the applied summary in `answers_json`. Decision-support only, nothing auto-applies/publishes
  (NN #1); injected client always closed (happy AND error paths).
- **5.8c Search + clone** (this commit) — `GET /jd-bank/ui/compose/search?q=` renders semantic-search
  hits (JDFN-scoped, CUPE/WJQ excluded HR-143) each linking to `GET /jd-bank/ui/compose/clone/{sid}`,
  which pre-fills the guided form from an existing archive JD (faithful copy in `answers_json`; the lossy
  form view drops duty verbs/KSA modifiers, as the form already does) and lands the author on a scored
  draft. 404 (HTML) when a document has no parsed JD. Reuses the `compose.get_embed_client` /
  `get_neo4j_driver` deps (tests override them — no live infra); embed + Neo4j clients closed after use.

Latest `make gates`: **1856 passing, 94.02%.** No rulebook/knob change; `rules_version` untouched
(pure transport over existing composer functions). **Still open in Phase-5 UI:** embed *published
canonicals* into the vector index so 5.4 search covers them (not just the archive — needs a small new
write path; `docs/tasks/phase-5-jd-builder.md`); structured per-field editors (duty %/KSA modifiers) in
both the Builder and the review-queue edit view; verify the SFU footer wording before any external
export (Phase-6 sign-off, `boilerplate.yaml`).
> **Workflow note (billing block):** GitHub Actions cannot start (account payment/spending-limit), so
> this session merges to `main` **locally per ADR-006** (`make gates` is CI-identical) and pushes `main`
> directly — `git push` does not need Actions. Re-run CI on `main` once billing is restored.

**PRIOR (2026-07-24, latest): HR-126 `max_chars` RESOLVED + re-embedded — the last GPU-blocked
follow-up is done.** [PR #80](https://github.com/humanaxiom/jd-assistant/pull/80) lands the prepared
decision **(a) progressive backoff + (c) section-vector reliance**: keep `max_chars=10000`, add a
registered **`max_chars_fallback: [8000, 6000, 4000]`** ladder (**HR-193**, `open`, unhashed) so the
~11 dense-WJQ docs that exceed the model's 8,192-token window even after truncation get a best-effort
*shorter* document vector instead of a gap. Loader enforces strictly-descending+positive rungs (not
coupled to `max_chars`); the runner re-cuts on whole-line boundaries and keys the backed-off vector on
the ORIGINAL `max_chars` sha so **skip-first idempotency is intact**. **Verified against the archive,
not from memory:** `make gates` **1844 passing, 93.98%**; `make embed` over all 14,522 v2 parsed_jds on
the now-free `aria-gb10-2` (full re-embed — the knob moved `embeddings.stamp`) → **`bad_requests` 11→0,
`texts_backed_off` 11**, 14,404 docs + 36,174 sections embedded. `docs/embeddings/summary.json`
refreshed with the measured counts. `rules_version` UNCHANGED (`embeddings.yaml` is unhashed — a
retrieval-substrate knob, never the approval bar). Decision doc: `docs/embeddings/max-chars-decision.md`.
> **Branch hygiene:** this is a CLEAN rebuild (`feat/hr126-fallback-v2`) off current `main` of the old
> `feat/hr126-max-chars-fallback`. The old branch's two stale HANDOFF/plan progress commits (`run at
> ~800/2458`) were DROPPED, not rebased — only the additive impl + register + decision-doc delta was
> kept, and the register merge preserved BOTH HR-193 (this) and HR-194 (CUPE). The old branch and its
> reserved-HR-193 note in the prior handoff are now superseded.

**PRIOR (2026-07-24, later): PHASE 5 (the JD BUILDER) is FULLY ON `main` — all 7 tasks — plus
a UI nav, an explicit CUPE scope decision, and a merge-topology clean-up.** A hiring manager /
recruiter can now **find or compose a JD, validate it live against SFU standards, get an LLM assist
on the weakest section, export the official SFU `.docx`, and submit it into the HR review queue** —
nothing auto-publishes (NN #1), all inference self-hosted (NN #5), every LLM touch judged by the
validator (NN #3), JDFN-scoped (HR-143/HR-194). Latest `make gates`: **1830 passing, ~93.98%.**

**What landed on `main` THIS session (all squash-merged, CI green):**
- **5.7 export** ([#72](https://github.com/humanaxiom/jd-assistant/pull/72)) — `jd_export/`
  `render_sfu_docx` + `POST /compose/export`.
- **5.4 search** ([#74](https://github.com/humanaxiom/jd-assistant/pull/74)) — **re-landed after it
  was found STRANDED.** Its original PR (#71) had merged into the defunct `feat/phase-5-mvp-to-main`
  base branch ~37 s AFTER #70 put the MVP on `main`, so 5.4 never reached `main` (the
  stacked-PR-off-a-moving-`main` trap CLAUDE.md warns about — it bit us a SECOND time). Fixed by
  applying the exact 4-file additive delta on a fresh branch off current `main`.
- **Global UI nav** ([#75](https://github.com/humanaxiom/jd-assistant/pull/75)) — the server-rendered
  UI had a header but no navigation; added a nav bar in `_base.html` (every template extends it)
  linking **Builder · Review queue · Dashboards**. Pinned in `test_dashboard.py`.
- **CUPE scope made explicit — HR-194** ([#76](https://github.com/humanaxiom/jd-assistant/pull/76)).
  A design review found CUPE (~29.5% of the archive, ~4,300 WJQ files) was excluded *correctly but
  SILENTLY*: the Builder's in-scope groups were a hardcoded tuple in `compose_ui.py`. Lifted to
  `segmentation.yaml :: jdfn_employee_groups` (rulebook-as-data, NN #2), read by the UI dropdown, and
  registered **HR-194 (open)**: *should CUPE/exempt roles stay out until HR defines a bar for them?*
  The validator can only score the JDFN template, so authoring a CUPE JD would guarantee the
  category-error mis-score HR-143 already keeps out of the baseline cohort. **Serving CUPE requires HR
  to define a CUPE bar FIRST, then add a token here.** Register 192 → **193**; `rules_version` unchanged.

> **🔴 SAME MERGE-TOPOLOGY LESSON, TWICE.** 5.4 was stranded by the exact stacked-PR trap the prior
> handoff recorded. **Do not deep-stack PRs off a moving `main`.** And verify additive-ness with the
> tree diff (`git diff main..branch`), **not** `git diff main...branch` (the 3-dot form over-reports a
> stale base) — and remember `git diff` HIDES untracked files, so `git add -A` can sweep in working
> artifacts your diff never showed (it swept `.claude/settings.json` + `docs/canonical/summary.json`
> into #76 this session; the former is now `.gitignore`d and untracked, the latter kept as a real
> deliverable).

**⚠ STILL OPEN (unchanged by this session; pick by priority):**
- **HR-194 is `open`** — HR has not ruled on whether the Bank should ever serve CUPE. Until then the
  Builder is JDFN-only *on purpose*. If SFU wants CUPE authoring, that is a real project: define a CUPE
  quality bar (a WJQ ruleset with an oracle) BEFORE wiring it. Roadmapped under Phase 7.
- ~~**Prune the superseded `--limit 5000` seed.**~~ **DONE (2026-07-24).** The handoff's "389" was
  imprecise: **313 of the 389 seed drafts were REFRESHED in place by the full run** (they ARE its current
  drafts — deleting them would drop 313 live roles), so only the **76** truly-orphaned seed drafts
  (created & last-updated 07-21, never touched by the full run) were prunable. Verified before deleting:
  all 76 `DRAFT`, `review_actions=0`, cluster_ids disjoint from the kept set, and a coverage check proved
  **0 of their 530 source docs were orphaned** (every role stays covered by a kept full-run draft).
  Transactional delete → **queue 1,877 → 1,801** (== the full run's JDFN drafts), confirmed live at
  `:25800`. The 76 now-orphaned `clusters` rows (seed leftovers, no FK/role impact) were then also
  deleted, so `clusters` == `canonical_jds` == **1,801** (one draft per cluster; `audit_log` retained).
- ~~**HR-126 (`max_chars`/dense-WJQ embedding)**~~ **DONE (2026-07-24) — [PR #80](https://github.com/humanaxiom/jd-assistant/pull/80).**
  Rebuilt clean off current `main` (`feat/hr126-fallback-v2`, NOT the stale-base `feat/hr126-max-chars-fallback`),
  `make embed` re-measured on the freed GPU: **`bad_requests` 11→0, 11 backed off**. HR-193 is now FILLED
  (the fallback ladder); HR-194 (CUPE) preserved. See the NEWEST block above.
- **Phase-5 UI follow-ups** — wire search/clone + assist + export buttons into the Builder UI (the JSON
  routes exist; the guided form does not call them yet); embed published canonicals so 5.4 search covers
  them (not just the archive); structured per-field editors; **verify the SFU footer wording** before any
  external export (Phase-6 sign-off, `boilerplate.yaml`).

Detailed Phase-5 task doc: **`docs/tasks/phase-5-jd-builder.md`**. One-pager:
**`docs/status/2026-07-24-shipped.md`**.

---

**PRIOR (2026-07-21, latest): FULL-ARCHIVE enrichment run IN FLIGHT + 4.6 follow-ups MERGED
([PR #59](https://github.com/humanaxiom/jd-assistant/pull/59), CI green, rebase-merged).**
> The enrichment run has since COMPLETED — `jd-canonical-fullrun` Exited (0) 2026-07-23;
> `docs/canonical/summary.json`: 2,458 clusters recomputed, 1,801 JDFN clusters, 1,488 drafts
> persisted + 313 refreshed = 1,801 DRAFT `canonical_jds`, 0 failures, `gpt-oss:120b`. GPU is FREE.

**① The full-archive canonical enrichment is RUNNING** — the complete bank, LLM pipeline, on the
new constrained-decode/`reasoning_effort` code. Detached crash-safe container **`jd-canonical-fullrun`**
(`docker compose run -d ... canonical python -m src.jd_bank.canonical --commit-every 25`), full LLM
pipeline (rewrite `gpt-oss:120b` + audit) over **ALL 2458 recomputed clusters**. **Watch:**
`docker logs -f jd-canonical-fullrun` (stderr progress every 25 clusters). **Resume if it dies:** re-run
the same command — idempotent, refreshes/skips what already landed. Summary → `docs/canonical/summary.json`
on completion. As of this handoff: **150/2458, 0 failures, ~63 s/cluster steady-state, ETA ~44h (~2 days).**
Verified before launch: Ollama reachable on `aria-gb10-2`, `gpt-oss:120b` loaded, egress allow-list intact,
`review_actions=0` (nothing human-touched to clobber). **MUST run WITH the LLM** — a `--no-llm` full run
would refresh the existing enriched drafts back to deterministic prose (no no-clobber protection at
`review_actions=0`).

> **⚠ POST-RUN CLEANUP (record this):** the full-corpus clustering yields **different `cluster_id`s**
> than the earlier `--limit 5000` seed (membership differs → different `cluster_id_for` uuid5), so the run
> **PERSISTS NEW drafts alongside** the seed's 389 rather than refreshing them (only ~17% coincidental
> refresh: 26/150 at checkpoint 6). `canonical_jds` will grow to ~2000+. The **superseded seed drafts**
> (all `DRAFT`, `review_actions=0` → safe to delete) should be **pruned after the run** so the review
> queue doesn't show near-duplicate drafts of the same role. Do NOT prune mid-run.

**② [PR #59](https://github.com/humanaxiom/jd-assistant/pull/59) — three 4.6 follow-ups + a CI fix, MERGED**
(gates **1784 · 93.94%**; `rules_version` untouched — no rule/decision-param change):
- **4.6d dead Flask `frontend` REMOVED** — compose service + env/port, the `core/frontend/` scaffold
  package (superseded by the FastAPI `/jd-bank/ui`), the now-unused `flask` dep, and README/DEVELOPER_GUIDE
  refs. **Surfaced a latent bug:** `jinja2` (used directly by the FastAPI dashboards/review UI) was only
  installed **transitively via flask** — the clean CI build broke (`ModuleNotFoundError: jinja2`) while
  local `make gates` masked it (`docker compose run` reuses a stale image, doesn't rebuild on a
  requirements change). Fixed by declaring `jinja2>=3.1.0` explicitly; verified against a from-scratch
  `docker compose build gates`. **Lesson: `make gates` does NOT rebuild — `docker compose build gates`
  first when deps change, or CI will catch what you didn't.**
- **Two secondary cluster-KPI test pins tightened** — `largest_cluster` (`"133"`, which doubled as a
  `size_distribution` key) and `flagged_clusters` (`"11"`, a substring of 10911/150911/47111/1191) were
  collision-prone; replaced with collision-free `9092`/`4707`, `largest_cluster` decoupled from the size
  buckets so each pin uniquely guards its KPI.
- **jdbank-scrub open flag CLOSED** — repo-wide search found no reference treating `C:\repos\jdbank` as
  authoritative; every mention is an intentional "it's stale" note or the unrelated `jdBank.ts` hris TS
  filename. Nothing to scrub.

**STILL DEFERRED — and now BIGGER than it looked:** the **`max_chars`/dense-WJQ embedding** follow-up.
Re-measured over the v2 corpus this session (read-only, no Ollama), **HR-126 was falsified**: it is not
"11 docs" — **1,400 docs (~9.6%) are TRUNCATED** at `max_chars=10000` (the WJQ re-parse recovered dense
text; median 2,559→3,909, MAX 8,987→13,486), and the 11 `bad_requests` are just the densest subset where
even the truncated text still 400s past the 8,192-token limit. **There is no single `max_chars` that both
avoids truncation and avoids the 400** — it is now an OPEN DESIGN DECISION (progressive-backoff-on-400 /
chunk+pool / rely on section vectors / lower to a token-safe floor). HR-126 in the register carries the
corrected numbers + the four options ([PR #62](https://github.com/humanaxiom/jd-assistant/pull/62)). Needs
a design call AND the Ollama host (busy with the run) to re-embed + validate — do it AFTER `aria-gb10-2`
frees. Also still open: the 4.5 HR pilot; review-queue structured edit view.

**NEXT SESSION:** (1) check `docker logs jd-canonical-fullrun` — if done, read `docs/canonical/summary.json`,
**prune the superseded seed drafts** (full-run cluster_ids ≠ the 389 seed's → they coexist), re-baseline/
update docs; if dead, re-run the same command to resume. (2) then the `max_chars` DESIGN decision (read the
corrected HR-126 first). This session merged **PRs #59 (4.6 + jinja2), #61 (this handoff), #62 (HR-126)**.

---

**PRIOR (2026-07-21, later): review queue LLM-ENRICHED + producer/LLM hardening MERGED ([PR #58](https://github.com/humanaxiom/jd-assistant/pull/58), CI green).**
The 379-draft queue now carries REAL prose: a crash-safe ~10h `gpt-oss:120b` run refreshed all **379 in
place** (384 drafts have real rewrite prose, 291 audited; **0 cluster failures**). Two hardening features
landed on `main` to make that — and the future full-archive run — safe and observable:
- **Producer crash-safety + observability** — `run_canonical_producer` gained `commit_every`/`progress_every`
  (`--commit-every`, default 25): commits BETWEEN clusters (after the SAVEPOINT releases, never a partial),
  stderr progress line. Proven over the 10h run (zero lost work).
- **LLM robustness** — constrained decoding (`json_schema`) **scoped to the AUDIT** (`JDQualityFindings`;
  fixes a ~24% enum-mismatch failure); the **REWRITE stays loose** because `SFUJobDescription`'s large
  grammar 500s Ollama (`failed to load model vocabulary` — the deferred live gate caught this before it
  shipped a zero-prose regression). New per-pass `reasoning_effort` knob: **HR-191** rewrite=`null`,
  **HR-192** quality=`low`.
- **Register 190→192** (both new = `reasoning_effort`; all `open`, 0 ratified; surface 251→253);
  **`rules_version` unchanged** (unhashed). Gates **1784 · 93.94%**. Both live goldens execute+pass.

**NEXT: the 4.5 pilot** on the now real-prose queue (`:25800`), then optionally the full-archive enrichment
on this improved code (audit-complete + faster + rewrite-safe). Docs (HANDOFF/plan/register) brought current.

---

**Phase 4.6 (Visibility & local-only assurance) — COMPLETE, SHIPPED, PUSHED, CI GREEN.** User-reprioritized *ahead* of the 4.5 pilot (the backend was substantial but invisible beyond
"tests pass", and the proprietary archive had to be provably local). All merged to `main` and **pushed**;
CI is green (7m41s full Docker suite — first green run since the billing block); PRs #56/#57 reconciled
(auto-closed as MERGED). **1,773 tests · 93.94% · register in step · `rules_version` unchanged** (this
phase adds no scoring rule). One-pager: **`docs/status/2026-07-21-shipped.md`**. What shipped:

- **Three read-only dashboards** inside the FastAPI `api` service (server-rendered Jinja, under
  `make gates`, no new dep): `/jd-bank/ui/dashboard/{baseline,dedup,clusters}` render committed report
  artifacts (`docs/baseline/summary.json`, `docs/dedup/*.json`, `docs/cluster/cluster-summary.json`),
  reusing the existing `extra="forbid"` report models (verified in-container each REAL artifact
  validates). **Every headline figure is READ from the artifact and mutation-pinned** — hardcoding a
  number turns tests red (the answer to "no visibility besides test-pass claims"). Graceful empty-states
  (200, never 500), incl. per-tier degrade on dedup. The baseline aggregator now emits the **874-JD
  current-practice cohort** as a segment (`SegmentDimension += "cohort"`) so THE headline
  (874 · 78.6% · median 79.05 · A81/B551/C240/D2) lives in the committed artifact; whole-archive rate
  demoted with its "category error — never quote" warning.
- **Egress guard — NN #5 is now a BUILD FAILURE** (`core/src/jd_bank/security/egress.py`).
  `assert_inference_host_allowed(base_url)` raises for any host not on `settings.allowed_inference_hosts`
  (default `aria-gb10-2` + loopback/private; env `ALLOWED_INFERENCE_HOSTS`); BOTH content clients
  (`jd_bank/llm/client.py`, `embeddings/client.py`) call it before building `AsyncOpenAI`. Opus
  security-reviewed: fail-closed mutation-verified, every bypass trick rejected (`aria-gb10-2@api.openai.com`,
  `127.0.0.1.evil.com`, encoded IPs, case, trailing-dot, public IPv6). Evidence: `docs/security/egress-audit.md`.
  **Boundary RATIFIED: "local" = not cloud; internal `aria-gb10-2` OK** (NN #5/ADR-003); dev-box-only declined.
- **Review queue SEEDED (data, not a code merge):** `make canonical-drafts CANONICAL_ARGS="--no-llm
  --limit 5000"` persisted **379 DRAFT canonical_jds** (378 multi-member clusters + 1 singleton; 751
  clusters recomputed from the 133,842 role-equiv edges over the first 5,000 parsed_jds), each with an
  audit-log row. Live UI populated: `/jd-bank/ui/queue` → detail → approve/reject/edit/override. **These
  are DETERMINISTIC 4.1 merge drafts (`--no-llm`, zero egress)** — the 4.2 LLM rewrite/audit
  (`gpt-oss:120b`, guard-permitted) can REFRESH them in place. **`--limit` bounds INPUT parsed_jds rows,
  NOT output drafts** (a 3-row smoke test formed 0 clusters). Seed is DB data; `docs/canonical/summary.json`
  is a partial-run working artifact (not committed).

**NEXT: 4.5 pilot** (5–10 clusters with a real HR reviewer through the now-populated UI). **Open
follow-ups:** ~~LLM-enrich a batch~~ **DONE** — the full 379 seed is LLM-enriched (PR #58 producer
hardening made the 10h run crash-safe); a **full-archive** enrichment (the complete bank) is still open and
should run on the new constrained-decode/`reasoning_effort` code; tighten
2 secondary cluster-KPI pins (`largest_cluster`, `flagged_clusters`) to collision-free sentinels;
review-queue **edit** view is still a raw-JSON `<textarea>` (structured editor deferred); remove the dead
Flask `frontend` compose service (4.6d, not yet done). App runs at `:25800` (`docker compose up -d api`).

**Docs refreshed 2026-07-21 (this session):** `HR-DECISION-MATRIX.md` committed (plain-language HR
decision matrix, verified against `summary.json`) + cross-linked from `HR-REVIEW-PACKET.md` (was
orphaned). Repo-wide staleness swept: decision-register count corrected (now **192** after HR-191/192;
was 119/123/166 in various docs), the 874-cohort grade spread corrected to **81 A / 551 B** (was 82 A / 550 B)
in the packet, baseline README, change-plan, and the register source (regenerated; `register-check` green),
Phase 4.6 marked COMPLETE in `plan.md`, and the egress-guard "not cloud / internal host" wording aligned.

Last updated: 2026-07-20 (**4.4a follow-up DONE — the producer's injected LLM client is now SPLIT into
`rewrite_client`/`audit_client` so the `QualityAudit.model` stamp can't lie once `quality.yaml` retunes
(NN #6); MERGED LOCALLY (PR #57, git-only — GitHub CI still billing-blocked, see 4.4a-followup below).
Gates 1734, 93.89%. 4.5 HR pilot still next. The Phase-4.4 review queue is COMPLETE: producer → service
→ routes → UI.**
`core/src/api/routes/ui.py` is a MINIMAL server-rendered UI INSIDE the FastAPI app (`/jd-bank/ui`) —
chosen over the untested Flask `frontend/` so the human-approval surface stays under `make gates`
(mypy --strict + coverage + TestClient). `GET /queue` · `GET /review/{id}` (404 page on unknown) ·
`POST /review/{id}/{approve,reject,edit}` → 303 to the queue on success, RE-RENDER the detail page with
the error + NO commit on a service error (pinned both directions). Jinja2 templates (`_base`/`review_
queue`/`review_detail`/`review_not_found`) mirror the dashboard theme. TRANSPORT ONLY — the 4.4b service
keeps every invariant; override construction builds one `GateOverride` per FILLED overridable-gate reason
field (blanks skipped, never synthesized — service re-checks). **NO new runtime dependency:**
`request.form()` asserts `python-multipart` (absent) on the installed Starlette even for urlencoded
bodies, so POST bodies parse via stdlib `urllib.parse.parse_qsl` on the raw body. Autoescape on, no
`|safe` on archive text; the 4.3 diff renders from `change_log["harmonization_diff"]`. Reviewer (Opus)
APPROVED after one must-fix (a rendered-draft assertion that was TAUTOLOGICAL with the title — a wrong
`change_log` key would have passed silently, the recurring silent-empty trap; now asserts a draft-unique
string). Gates **1731, 93.67%** (`ui.py` 99%). No knob; `rules_version` untouched. **⚠ MERGED LOCALLY,
NOT via GitHub:** GitHub Actions was billing-blocked at merge time ("recent account payments have failed
/ spending limit") so CI could not run — `main` was fast-forwarded locally (`make gates` is CI-identical
per ADR-006). **PR #56 is open + unmerged on GitHub; re-run its CI and reconcile once billing is fixed.**
Follow-ups (out of scope): the edit view uses a raw JSON `<textarea>` (structured per-field editor
deferred); the pre-existing `jd_core→jd_bank` edge (`parser/store.py`) still open. Prior line — 4.4c
review ROUTES MERGED (PR #55).
`core/src/api/routes/jd_bank.py` is THIN HTTP over the 4.4b service — a `/jd-bank` router on the
harness app. Five endpoints: `GET review/queue?limit=` · `GET review/{id}` (404 on unknown) ·
`POST review/{id}/{approve,reject,edit}` (`reviewer_id` in the BODY, pilot model, no SSO). Routes add
ZERO invariants — the service keeps NN #1 publish gate / validator-as-oracle / override-needs-reason /
append-only audit; a handler unpacks → calls ONE service fn → COMMITS on success → serializes. The ONLY
route logic is the typed-error→status map: `CanonicalNotFound`/None-packet→404; `IllegalTransition`+
`NotApprovable`→409; `GateOverrideError`+`MissingReason`+malformed-edit `ValidationError`→422.
Commit-on-success / no-commit-on-error pinned BOTH directions; TestClient units monkeypatch the service.
Reviewer (Opus) APPROVED, no must-fix, re-ran gates. Gates **1716, 93.61%**. No schema/knob change.
**Two follow-ups (out of scope, recorded):** a pre-existing `jd_core→jd_bank` edge (`parser/store.py`
imports `jd_bank.db.models`) — its own chore; optional `get_session`→`api/deps.py` to drop the router's
bottom-of-file circular-import shim (`# noqa: E402`). Prior line — 4.4b review SERVICE MERGED (PR #54).
`jd_bank/review/service.py` is the human-approval spine (NN #1): list queue / assemble packet /
approve·reject·edit·override over the 4.4a DRAFT canonicals, writing status transition +
`review_actions` + append-only `audit_log`. **approve PUBLISHES only when the gate decision permits**
— it RE-VALIDATES current `content` (validator-as-oracle, NN #3; never trusts the stored `change_log`
roll-up), runs `evaluate_gates`→`apply_overrides`, else raises `NotApprovableError` (the ONLY publish
path). Override needs a written reason (reuses `apply_overrides`). `get_review_packet` surfaces a
FRESHLY recomputed `GateDecision` (stored roll-up display-only — pinned). edit → new `version+1` DRAFT
(prior ARCHIVED, EDIT action on v2); folded in the 4.4a follow-up (producer no-clobber now
`order_by(version desc)`). `FOR UPDATE` lock serializes approves. No schema change, no new knob.
Reviewer (Opus) APPROVED after one must-fix (unpinned packet recompute) + focused confirm. Gates
**1701, 93.54%**. Follow-up: a concurrent double-approve test (lock is real; backlog for the pilot).
Prior line — 4.4a canonical-draft
PRODUCER MERGED (PR #53); 4.4b next.** 4.4a is the first slice of the review queue:
`jd_bank/canonical/runner.py::run_canonical_producer` drives the full Phase-4 pipeline per JDFN
cluster (4.1→4.2a→4.2b→4.3→validator) and PERSISTS a DRAFT `canonical_jds` row — the work-list 4.4b/4.4d
consume. NOTHING publishes (NN #1; draft's `GateDecision.approved=False` while gates block). IDEMPOTENT
(clusters upserted on the stable `cluster_id_for` uuid5; canonical refreshed in place). **NO-CLOBBER**
(a canonical with `status!=DRAFT` OR any `review_actions` row is left byte-identical + counted
`skipped_reviewer_touched` — never overwrites/cascade-deletes a human artifact; mutation-pinned both
halves). APPEND-ONLY `audit_log` per persist/refresh/skip. Best-effort LLM INJECTED + mockable
(`client=None`→deterministic merge draft; per-cluster failure isolates via SAVEPOINT, pinned by
fault-injection). Roll-up + 4.3 diff + provenance live in `canonical_jds.change_log`;
`validation_report_id`=NULL (validation_reports is parsed_jd-keyed). No new knob. Reviewer (Opus)
APPROVED after one must-fix (untested SAVEPOINT branch) + focused confirm. Gates **1678, 93.41%**.
**Two follow-ups (see 4.4 Next-up):** split `rewrite_client`/`audit_client` before the two LLM YAMLs
diverge; multi-version no-clobber lookup for 4.4b. 4.4 slicing (user-chosen): producer→service→routes→
server-rendered UI. 4.3 is the harmonization CHANGE-LOG / per-source diff:
`jd_core/bank/change_log.py::build_harmonization_diff`
4.3 is the harmonization CHANGE-LOG / per-source diff: `jd_core/bank/change_log.py::build_harmonization_diff`
— pure/deterministic/order-invariant, no LLM/DB, gives the 4.4 reviewer a per-source diff (which
sections each member fed; duties kept vs folded/dropped) + a "removed content and why" change log.
Drop-vs-dedup is authoritative from the merge's ACTUAL cap-dropped groups (`merge.dropped_duty_occurrences`),
NOT a Jaccard proxy — the reviewer proved the proxy mislabels a duty that folds into a SURVIVING group
but drifts from its re-picked representative; fixed + mutation-pinned both directions. `merge.py`
exposes shared `canonical_member_order`/`dropped_duty_occurrences`/`unmerged_content` (one home);
`merge_cluster` byte-identical. Frozen `HarmonizationDiff`, no approval/score field (NN #1); NO new
knobs, `rules_version` untouched. Reviewer (Opus) APPROVED after one must-fix round + a focused
mutation-verified confirm. Gates **1655 passing, 93.84%**. Follow-up: a `jd_bank/` runner to produce
change-logs over real clusters (mirrors 4.1's measure-after runner). 4.2b is Phase 4's SECOND LLM pass:
`jd_bank/quality/audit.py::audit_quality` — the NUANCED audit (`inclusive_language`/`clarity`/
`seniority_mismatch`) with a **verbatim-evidence anti-fab scrub** (a finding whose `evidence` is not
found verbatim in the JD is dropped). **Advisory — computes NO score/grade** (validator stays the
oracle, NN #3); frozen `QualityAudit`, no approval field (NN #1). Reuses 4.2a's `ChatClient`
(generalized with optional model/temp overrides) + prompt loader; `flatten_jd` now SHARED in
`jd_bank/jd_text.py`. New **UNHASHED** `quality.yaml` (HR-185..190, all `open`, provisional). Reviewer
(Opus) APPROVED after breaking all four load-bearing mutation pins. Gates **1641 passing, 93.76%**.
Two follow-ups recorded (structural-bar inflation guard for the 4.2a rewrite; provenance-stamp/
category-filter note for 4.4 wiring). 4.2a is Phase 4's FIRST LLM pass: `jd_bank/rewrite/harmonize.py`
rewords the deterministic 4.1 merge draft into cleaner prose via self-hosted Ollama
(`gpt-oss:120b` on `aria-gb10-2`) under an **anti-fabrication guard** — output is an explicit DRAFT
scored by the validator, nothing auto-publishes. Reusable LLM scaffolding landed: `jd_bank/llm/`
`ChatClient` (JSON mode, deterministic temp 0.0, never-retry-400, model from `rules.rewrite.model`)
+ prompt loader (ported `jd_harmonize_v1`). New **UNHASHED** `rewrite.yaml` (HR-176..184, all `open`,
provisional — calibrate at 4.5 pilot). Reviewer (Opus) APPROVED after one must-fix: `_flatten_jd`
dropped the Relationships section from the validator's text so a coded term the LLM wrote there was
invisible to the oracle — fixed + mutation-pinned. Gates **1615 passing, 93.72%**.
4.1 follow-ups #1 (calibrate) + #3 (runner) DONE: the read-only `jd_bank/harmonize/`
runner measured the merge over **1,801 JDFN clusters**; the 9 `harmonization.yaml` knobs are now
registered with measured evidence — **one default moved (`max_duties` 10 → 12**, aligned to the
model's 12-duty cap; `duties_over_max` flag 20.8% → 4.8%), the other 8 kept as measured-well-placed.
Phase 3 complete (3.1–3.5). Archive **99.3% parseable**; **2,458 role clusters** over 14,522 signed
JDs; **133,842 ROLE_EQUIVALENT edges** (clustered at gate 0.75); **9 flagged** for HR review; 75.1%
coverage. Test suite **1577 passing, 93.60%**; HR decision register **175** (HR-167..175 all `open`,
unhashed `harmonization.yaml`; measured evidence written into each `why_it_matters`).)

**Catching up? Read [`docs/status/2026-07-21-shipped.md`](docs/status/2026-07-21-shipped.md) first** —
the current one-pager (Phase 4.6: the read-only dashboards + build-enforced egress guard + seeded review
queue — the backend made visible end to end). The prior
[`2026-07-19-shipped.md`](docs/status/2026-07-19-shipped.md) covers Phase 4.1–4.4 (the harmonization
pipeline + the human-approval review queue). Before that,
[`2026-07-15-shipped.md`](docs/status/2026-07-15-shipped.md) covers 3.2 / 3.3 + the extraction defects;
[`2026-07-13-shipped.md`](docs/status/2026-07-13-shipped.md) covers 2.5 / 2.6 / 3.1.

**PR stack all MERGED:** [#19](https://github.com/humanaxiom/jd-assistant/pull/19) (2.5 baseline)
→ [#22](https://github.com/humanaxiom/jd-assistant/pull/22) (2.6 defects, re-opened after #20 auto-closed)
→ [#21](https://github.com/humanaxiom/jd-assistant/pull/21) (3.1 dedup) → [#23](https://github.com/humanaxiom/jd-assistant/pull/23) (3.2a ingest) → [#24](https://github.com/humanaxiom/jd-assistant/pull/24) (3.2b embeddings)
→ [#26](https://github.com/humanaxiom/jd-assistant/pull/26) (nonstandard ports) → [#27](https://github.com/humanaxiom/jd-assistant/pull/27) (3.3 Tier-2 near-dup) → [#28](https://github.com/humanaxiom/jd-assistant/pull/28) (coverage-rate fix + docs)
→ [#30](https://github.com/humanaxiom/jd-assistant/pull/30) (extraction: docx tables/controls) → [#31](https://github.com/humanaxiom/jd-assistant/pull/31) (baseline refresh)
→ [#32](https://github.com/humanaxiom/jd-assistant/pull/32) (WJQ parser) → [#33](https://github.com/humanaxiom/jd-assistant/pull/33) (baseline at v2)
→ [#34](https://github.com/humanaxiom/jd-assistant/pull/34) (LSH retune) → [#35](https://github.com/humanaxiom/jd-assistant/pull/35) (pipeline refresh).

Repo: **`C:\repos\JD-Assistant`** → GitHub **github.com/humanaxiom/jd-assistant**.

---

## THE HEADLINE. Read this before you believe anything about the archive.

**The archive RATIFIES the approval bar. It does not kill it.** The 2.5 brief (written before the
run) predicted the opposite and told you to expect the bar to die. It didn't. Correcting that
expectation is the single most important thing on this page.

Full deliverable: **`docs/baseline/README.md`** + `summary.json` + `errors.jsonl`.
Regenerate: `make baseline JD_ARCHIVE_PATH=C:/repos/hris/fixtures/SFU_JDs` (~9 min, single-process).

Ran all **14,565** files → 14,522 scored, 43 skipped, every file accounted for.
**Numbers below are post-2.6** (rulebook `jd_rules_sfu_v4+8c004c4dadd1`).

| Population | Approval | |
|---|---|---|
| All scored | ~5% | **A category error. Never quote it.** |
| Era `new` (2019–2023) | 1.0% | **Also an artefact** — the footer gate is a date detector. |
| Era `current` (2024+) | 61.2% | A *date* band, not a practice band. |
| **Current practice** (n=874) | **78.6%** | The bar's real trial. |

On current practice: median **79.0**, **99.8% clear the score floor of 60**, grades 81 A / 551 B /
240 C / 2 D / **zero F**. **The score floor rejects 2 JDs out of 874.**

> ⚠️ **The cohort filter changed in 2.6.** It is now `era ∈ {new, current}` ∧ no
> `SFU-COMP-TERRITORIAL`. The pre-2.6 filter (`era == "new"` alone) now returns **79** JDs, not 874.
> If you get 79, this is why. Stated at the top of `docs/baseline/README.md`.

### 2.6 — three defects that were OURS, not the archive's

The most valuable thing 2.5 produced was not a score. It was finding that **three of our own rules
were broken and were distorting the numbers HR was about to ratify.** Fixed before HR saw anything.

1. **`SFU-STRUCT-HOW-WHY` could never *not* fire** (HR-121). It counted duties lacking `how_why` —
   but `segmenter.py` **never populates that field** ("left empty"). It fired on **100% of the JDs we
   would approve.** Zero discriminating power; a constant subtracted from every score. **Same class
   as the 2.4 `render.py` disaster: faithful to hris, wrong here** — in hris an LLM filled the field;
   our regex parser structurally cannot. Now marked **unevaluable** (data, not code — Phase 4
   reinstates it with one YAML word). Finding **8,593 → 0**. Scores rose on 9,217, unchanged on
   5,305, **fell on 0**. *(Say "every score that carried the finding rose" — NOT "every score rose".)*
2. **`SFU-QUAL-BANNED-PHRASE` scanned the whole document** (HR-120), though its rule text says
   *Qualifications only*. It drove **all 104** `QUAL-MINIMUM` blocks — every one a wrong-section
   match. Now a knob (`banned_phrase_scope`). Blocks **104 → 0**; **+59 approvals** (exactly the JDs
   it was the *sole* blocker of). **This is the entire 71.9% → 78.6% gain.**
3. **The era model conflated two rollouts** (HR-122) — 4th band `current` (2024+) added.

Net: approval **71.9% → 78.6%**, median **77.3 → 79.0**, blocked **246 → 187**, score-floor
rejections **5 → 2**.

### Why every other number lied: one gate is a DATE DETECTOR

`SFU-APPROVE-EDI-FOOTER` blocks 86% of the `new` era — not because those JDs are bad, but because
the **territorial acknowledgement is a rollout still in progress**: 0% (2018) → 0.2% (2019) → 1.4%
(2021) → 11% (2023) → 63% (2024) → 85% (2025) → **88.6% (2026)**. Approval rate tracks adoption
almost exactly, because a blocking gate keyed to the footer *is* an adoption detector.

**The validator is correct and this was checked**: cross-examined `SFU-COMP-TERRITORIAL` against a
raw-text scan of all 6,259 new-era JDs → **10 false positives (0.2%)**. The archive genuinely
doesn't have the paragraph yet.

### The era model was WRONG, and the baseline proved it (HR-109/110/111 → fixed in 2.6, HR-122)

It assumed **one** transition. There are **two, four years apart**: the JDFN *template* rolled out
in 2019; the *acknowledgement/EDI footer* became standard in **2023–24**. `new` captured the first
and was then judged by a gate only the second satisfies — so a 2019 JDFN doc, authored correctly
under the template of its day, was un-approvable. **A 7× gap, all date and no quality.**

Fixed: 4th band `current` (2024+). Bands: `old` 3,339 · `transition` 4,964 · `new` 5,228 ·
`current` 1,034. **A trap we nearly hit:** the `JDFN` token used to override the date band
*outright* — and every JD written today carries it, so a naive 4th band would have collapsed
instantly. The token now **promotes** an old file but never **demotes** a current one.

**Still open (HR's call):** the band is **not** the cohort. `current` (1,034) and current-practice
(874) agree on **795** — 239 JDs dated 2024+ still lack the footer; 79 that carry it predate 2024.
**Quote the cohort for claims about the bar, the band for claims about a date.** Defining "current"
by footer *presence* rather than date is the truer signal and remains HR's decision.

### What the bar ACTUALLY gates (HR-004/019/020/041/042)

Of the **187** current-practice JDs still blocked: `SUMMARY-LENGTH` **134**, `QUAL-EQUIVALENT` 42,
`EDI-FOOTER` 10 … `SCORE-FLOOR` **2**, `GRADE-FLOOR` **2**. (`QUAL-MINIMUM` was 104 → now **0**.)
**HR believes it is ratifying a quality bar. It is ratifying a 100–150 word range.** Say that before
anyone signs. (The one saving grace: that range is SFU's *own published number*, not ours.)

- **⚠️ New open question 2.6 created:** correctly scoped, the banned-phrase list now fires on **10
  files in 14,522**. Either it is a guard-rail nobody trips, or **it is missing the phrases SFU's
  authors actually write.** Needs an experienced JD reviewer, not an engineer. (HR-041)
- **`SFU-APPROVE-QUAL-MINIMUM`'s `overridable: true` rationale has evaporated.** It was justified by
  *"the phrase match spans the whole document"* — which is no longer true. Deliberately left
  overridable (hardening a gate off the back of a bug fix, unratified, is what the register exists
  to prevent), but HR should now decide it **on purpose**. (HR-042)
- **HR-047 blocks ZERO current-practice JDs** (29.4% of the whole archive, 23.4% of
  latest-per-position). A legacy-corpus menace, **not** a threat to what SFU writes today. This is
  the finding everyone expected to be the villain; the data says it isn't. Prioritise accordingly.
- **`evaluable` is a loaded gun — keep it registered.** 2.6 added `RuleSpec.evaluable` to retire
  `HOW-WHY`. It is a switch that can silently disable an inconvenient rule. The reviewer **exploited
  the first version of the guard**: promote a rule to `high` in `titles.yaml` (so it blocks via the
  **severity floor**, not a named gate), then set `evaluable: false` → finding vanishes, approval
  flips, rulebook loads clean. The guard now checks a rule's **maximum reachable severity** (which is
  *not* just `default_severity` — `coded_terms` tiers and `titles.restricted[].severity` override it).
  What stops abuse is that `evaluable` is **registered, on the decision surface, and mutation-pinned**.
  Keep it that way.

### The trap in the distribution — do not fall in it

The `new`-era histogram is bimodal and the floor of 60 sits in the valley. **This is not evidence
the floor is well-placed.** The two modes are "has the acknowledgement" / "doesn't" — the same
rollout again. Within current practice the distribution is **unimodal, centred 70–79**. The floor
is defensible because it is *nearly inert*, not because the data carved a threshold there.

---

## Current state — Phase 4 STARTED (4.1 merge engine MERGED); 4.2 next

**Phase 4.1 — the deterministic harmonization merge engine — is MERGED (PR #46).** A pure,
LLM-free `jd_core/bank/merge.py` (`merge_cluster(members) -> MergedRole`): section selection,
duty union/dedup/reorder, KSA rebuild, composing the existing `provenance`/`signals`/`similarity`
primitives. **The output is an explicit DRAFT — nothing auto-canonical** (non-negotiable #1);
`MergedRole`/`MergeProvenance` are frozen with no approval field. **9 knobs** in the new
**registered-but-UNHASHED** `harmonization.yaml` (HR-167..175, all `open`, `our_invention`) — a
merge-policy change decides how JDs are *merged*, not how a JD is *scored*, so it is excluded from
the `rules_version` digest (same pattern as dedup/embeddings/segmentation). Every knob
mutation-pinned; order-invariance pinned byte-identical; validator-as-oracle honest (the draft
trips the boilerplate gates, never "approved"). Reviewer-approved (Opus) after one round + a
focused confirm — the one real defect (experience-bar inflation: a `frozenset` dropped
`experience_source_kinds`' ordered fallback, so a `knowledge`-blob number could inflate the bar and
get relabeled `kind="experience"`) is fixed and pinned by a regression that goes red under the old
behaviour. **Two follow-ups this created (see Next up):** calibrate the 9 defaults against the real
clusters (a measurement pass, the 3.5 pattern), and the deferred **%-rebalance** of duty allocations.

**Phase 3 is done.** All of 3.1–3.5 are merged and have run over the real archive. The dedup engine (Tier-1 exact, Tier-2 near-dup, Tier-3 role-equivalence) is complete; the clustering runner generated a full cluster report; all core subsystems landed. **Archive is 99.3% parseable and 99.4% covered end-to-end** (parse → embed → dedup). The validation engine, HR decision register, all EXTRACT-eligible `jd_core` modules, the full archive in Postgres, the embedding service (14,395 doc + 36,174 section vectors in Neo4j), Tier-2 near-dup (15,072 edges), Tier-3 role-equivalence (133,842 edges), and role-clustering (2,458 clusters) are all landed.

| Phase | State | PR | Commit |
|---|---|---|---|
| 2.1 rules-as-data (8 versioned YAML + typed loader) | MERGED | [#6](https://github.com/humanaxiom/jd-assistant/pull/6) | `43f29db` |
| 2.2 section validators (29 rules, rulebook-as-code) | MERGED | [#7](https://github.com/humanaxiom/jd-assistant/pull/7) | `9eaa39d` |
| 2.3 gate runner ("never approve if…", 14 gates) | MERGED | [#8](https://github.com/humanaxiom/jd-assistant/pull/8) | `5b8d954` |
| HR decision register (58 decisions, build-enforced) | MERGED | [#9](https://github.com/humanaxiom/jd-assistant/pull/9) | `c519bed` |
| 2.4a bank value objects + provenance + render | MERGED | [#11](https://github.com/humanaxiom/jd-assistant/pull/11) | `43435a7` |
| 2.4b title classifier + Hay signals (tables as data) | MERGED | [#12](https://github.com/humanaxiom/jd-assistant/pull/12) | `b71868a` |
| 2.4c similarity + clustering + drift (pure functions) | MERGED | [#13](https://github.com/humanaxiom/jd-assistant/pull/13) | `58fc7d2` |
| 2.5-prep: HR-058 boilerplate exemption + content-derived `rules_version` | MERGED | [#16](https://github.com/humanaxiom/jd-assistant/pull/16) | `98c0add` |
| scanner hardening: invisible-char + line-wrap folding (HR-108) | MERGED | [#17](https://github.com/humanaxiom/jd-assistant/pull/17) | — |
| **2.5 THE ARCHIVE BASELINE** — trial of the approval bar | MERGED | [#19](https://github.com/humanaxiom/jd-assistant/pull/19) | `7e75835` |
| **2.6 three rulebook defects** — HOW-WHY unevaluable · banned-phrase scope · 4th era band | MERGED | [#22](https://github.com/humanaxiom/jd-assistant/pull/22) | — |
| **3.1 Tier-1 exact dedup** — one file per row; dedup a finding, not a silent collapse | MERGED | [#21](https://github.com/humanaxiom/jd-assistant/pull/21) | — |
| **3.2a archive→Postgres ingest driver** — all 14,565 files in the ledger | MERGED | [#23](https://github.com/humanaxiom/jd-assistant/pull/23) | — |
| **3.2b embedding service** — doc + section vectors on `aria-gb10-2` (Ollama + Neo4j) | MERGED | [#24](https://github.com/humanaxiom/jd-assistant/pull/24) | — |
| **3.3 Tier-2 near-dup** — MinHash/LSH → exact Jaccard; 14,312 edges; the reconcile | MERGED | [#27](https://github.com/humanaxiom/jd-assistant/pull/27) | — |

Test suite: **1518 passing**, coverage **94.02%**, all in Docker via `make gates`. Decision
register grew from 58 to **166 decisions** (3.2b added HR-124..HR-130 for embeddings; 3.3 added HR-131..HR-140 for `dedup.yaml` and amended HR-093; this session added HR-141..HR-148 for WJQ parsing; 3.4a added HR-149..HR-154 for JobSignals; 3.4b added HR-155..HR-160 for Tier-3 role-equivalence; 3.5 added HR-161..HR-166 for clustering).

All 16 EXTRACT-mapped hris modules are now ported or explicitly deferred: `export.py` → 5.4,
the 3 prompt templates (`sfu_jd_extract`/`jd_harmonize`/`jd_quality`) → 4.2, `jd_import_service`
→ 5 (see `docs/audit/hris-reuse-map.md` and Next up, below). 2.4c's `similarity`, `clustering`
and `drift` landed as pure, tested functions **deliberately not wired to anything yet** — the
`ParsedJD → signals` adapter is Phase 3 work (see Next up).

---

## This session: extraction defects FIXED + pipeline refreshed

**Two extraction defects that were silently shrinking the visible archive are BOTH FIXED and the pipeline has been refreshed end-to-end.** The wins are documented with data; HR numbers remain unaffected (the defects were outside the 874-JD current-practice cohort).

### Defect 1: docx table/content-control extraction (PR #30, #31)

`_extract_docx` read only `document.paragraphs`, silently losing all text in TABLES and Word CONTENT CONTROLS (`<w:sdt>`). Fixed with a document-order body walk that recurses into `<w:tbl>` cells and `<w:sdtContent>`. **Measured recovery: files losing everything 24 → 0; files losing >40% of their text 2,596 → 1; ~20.7M characters recovered.** Byte-identical on plain-paragraph docs (bounded blast radius, pinned). Reviewer-approved (Opus), every safety claim mutation-verified.

Baseline regenerated (PR #31): **HR cohort byte-identical** (874, 78.6%, median 79.0) — but the docx fix alone **rescued 3,278 files** from broken parse (parse_confidence <0.10: 4,984 → 1,706).

### Defect 2: WJQ template parser (PR #32, #33)

SFU's **Weighted Job Questionnaire (WJQ) Custom** form — **~4,300 files (29.5% of the archive)** — is a *different document template* the segmenter knew nothing about. A new **marker-routed** segmenter (`parser/wjq.py`) reads WJQ's 14-section template into `SFUJobDescription`; headings/labels/frequency-markers/instruction-cruft live as data in a new **hashed** `rules/wjq.yaml`. Two user decisions: **(1)** duty frequency markers `(D)/(W)/(M)/(S)` → a new additive `SFUDuty.frequency` (marker stripped); **(2)** **WJQ is parse-only and EXCLUDED from the approval-bar cohort** — the 874-JD current-practice cohort gains a `template != wjq` clause (HR-143). WJQ is CUPE; the bar was built only for JDFN/APSA and the rulebook defines no WJQ bar, so scoring WJQ under the JDFN gates is a category error.

`PARSER_VERSION jd_segmenter_v1 → v2`; `ParseResult.template ∈ {jdfn,wjq,unknown}`. Register **HR-141..HR-148** (which took the register to 148; it is **160** after 3.4). Reviewer-approved (Opus) after two rounds and **two real defects**, both proven on the archive and both the class gates-green hides: (a) an uncapped summary fallback that **raised on 568 real files**; (b) loose union markers that **misrouted 69 genuine JDFN JDs** into WJQ — fixed with two-tier detection, misroutes 69→3.

Baseline regenerated at v2 (PR #33): **HR cohort BYTE-IDENTICAL** (874, 78.6% approval / 687, median 79.0, grades 81A/551B/240C/2D) — the `template != wjq` exclusion did its job. Template facet: **jdfn 10,222 / wjq 4,300 / 43 skipped**.

### The combined coverage win

**Archive-wide broken parses (parse_confidence < 0.10): 4,984 → 1,706 (docx) → 105 (WJQ). The archive is now 99.3% parseable.** Of the 4,300 WJQ files, only 43 remain broken.

### The pipeline refresh (PR #34, #35)

`PARSER_VERSION v2` forced a full re-parse. Re-ran ingest → embed → near-dup with measured results:
- **Re-parse:** 14,522 fresh v2 `parsed_jds` rows.
- **Re-embed:** documents with a vector **9,517 → 14,395**; section vectors **22,922 → 36,174**; empty-serialization documents **5,005 → 118**. **11 documents hit `bad_requests`** — denser WJQ text still exceeds the model's 8192-token limit after truncation to `max_chars=10000`. Runner isolates+skips them (no crash), sections still embed — a 0.08% doc-vector gap + a `max_chars` follow-up.
- **near-dup LSH retune (PR #34):** the recovered text (WJQ boilerplate, nearly identical across ~4,300 files) blew candidate count past `max_candidate_pairs` at the old `bands=32/rows=4`. Retuned to **`bands=16/rows=8`** (midpoint 0.707): **candidates 98,193+ → 23,705, edges 15,082 → 15,080** (unchanged — the boilerplate was candidate waste that never became an edge at jaccard_min=0.85). HR-136/137 updated.
- **Re-near-dup:** **15,072 edges** (was 14,312 pre-fix), 99.6% coverage; reconcile updated 13,917 / wrote 1,155 / pruned 395. Cross-position still dominant (68%).
- **Archive now ~99.4% covered end-to-end (parse → embed → dedup).**

**The full archive is in Postgres.** Every measured count independently reproduces:

| PostgreSQL | Value | Validates against |
|---|---|---|
| `source_documents` (one row per file) | **14,565** | 3.1's ledger property |
| `parsed_jds` scored | **14,522** | 2.5 baseline "14,522 scored" |
| `parsed_jds` failed or unsupported | **43** | 2.5 baseline "43 skipped" |
| Distinct `sha256` | 12,593 | — |
| Duplicate files (1,972 redundant) | **1,972** | 3.1's measured count, exactly |

**Phase 3.2a — the ingest driver.** Two blocking defects had to be fixed first:
1. **`parse_and_store` was not idempotent** — unconditional INSERT, no unique constraint. Two runs
   doubled `parsed_jds`, each row a fresh UUID, orphaning every vector. Fixed: migration **`0003`**
   adds `uq_parsed_source_parser` on `(source_document_id, parser_version)` (parse is a pure
   function). `parse_and_store` now mirrors `ingest_document`'s select→SAVEPOINT-insert→re-select
   shape, and the upgrade **refuses** rather than deleting rows.
2. **Incumbent names would have crossed the network** to `aria-gb10-2`. `ingest_document` computed
   the clean text, persisted the report, and **discarded the text**. The obvious driver would parse
   RAW text carrying incumbent names, violating FIPPA. Fixed: it now returns `IngestOutcome(document, text)`
   and the driver parses the clean text on **every** path, including the resumed one. Also:
   `_stable_reason` extracted to a shared home; `stream_sha256` hashes in 1 MiB chunks so oversized
   files still get a row (3.1's ledger property holds; hashing bytes we refuse to parse was never
   the hazard the cap guards).

**New in the repo:** `make ingest JD_ARCHIVE_PATH=... [INGEST_ARGS=...]`, an `ingest` compose service,
`jd_bank/ingest/driver.py`.

**Phase 3.2b — the embedding service.** Document- **and** section-level embeddings on `aria-gb10-2`
(Ollama client, Neo4j upsert). New rule file `embeddings.yaml`; register entries **HR-124..HR-130**
(all `open`, all `our_invention` — SFU publishes no embedding policy). Every default **measured**
against the live endpoint + all 14,522 parsed JDs:
- Server hard-rejects `400: input length exceeds context length` (no silent truncation).
- Limit is **8192 tokens**; real JD text runs ~1.5 chars/token (legacy boilerplate-heavy `.doc`), so
  practical ceiling is ~12,000 chars.
- Serialized JD lengths over all 14,522: median 2,559 · p99 5,993 · p99.9 8,870 · **max 8,987** ·
  **zero exceed 10,000**. → **`max_chars: 10000`** truncates **nothing** in this archive.
- **`min_section_chars: 40`** excludes 1 summary + 6 duty-blocks in 14,522 — guard-rail, not a filter.
- **`include_title_in_document: false`** — `similarity.py` promises title-agnostic scoring; a title
  in the document vector silently voids that. Mutation-pinned.
- Embeddings **deterministic** (same text → identical vector) + **content-keyed** on `(text_sha256,
  model, embed_stamp)` → idempotent + unchanged corpus writes nothing, calls Ollama zero times.
- Runner **reconciles/prunes** stale vectors (a MERGE-only design would leave dead vectors live in
  the queryable index). The keep-list is derived *before* embedding, so a 400 or transient failure
  never triggers a delete.
- **ADR-003 live-test guard:** `make gates` CAN reach `aria-gb10-2`; **CI never will.** Live tests
  are deselected in pytest `addopts`, `Makefile`, **AND** `.github/workflows/ci.yml` (with
  `--strict-markers`). **`make embed`** runs them opt-in and local-only. New: `docs/embeddings/summary.json`
  (counts + stamps, **never vectors**).

**Gates: 3.2b 1256 passing / 95.55% · 3.3 1368 / 94.90% · after the WJQ parser + extraction fixes 1424 / 95.17%.**

---

## THE BIG NEW FINDING — record this prominently

**Our parser cannot read 29% of the archive.** SFU's **Weighted Job Questionnaire (WJQ) Custom**
form — a *different document template* from the JDFN one the segmenter knows, with headings like
`PART 1: JOB DESCRIPTION` — is **4,226 files (29.1% of the archive)**, and **89% of them (3,771)
parse to ZERO content sections.**

- **34.5% of all parsed JDs (5,005 of 14,522) serialize to zero characters** — nothing to embed.
  WJQ is **75%** of that.
- By era: `old` 34.3% empty · `transition` **52.7%** · `new` 21.5% · `current` **13.8%**. **NOT
  a legacy-only problem** — a 2024 CUPE `.docx` with 9,291 chars of real duties and summary comes
  back with `parse_confidence: 0.02`, zero sections, and a title misread.
- `docs/rulebook/sfu-reference.md` **already documents WJQ Custom** as SFU's point-factor instrument.
  The project knew the *instrument*; the **parser was never taught its document template.**

**Two things keep this from being a crisis, both checked against the archive:**

1. **The HR numbers are CLEAN.** The 874-JD current-practice cohort reproduces exactly from the
   committed baseline artifact, and **ZERO of those JDs have a broken parse** (median `parse_confidence`
   **0.74**). All 4,984 unparsed JDs grade **F, median score 19.0** — they sit entirely inside the
   archive-wide "~5% approval" figure HANDOFF already brands *a category error, never quote it*. **No
   re-baseline needed; the HR packet is unaffected.** In fact this **explains** that number for the
   first time: the archive-wide approval rate is low in large part because a third of the corpus is
   a template we never taught the parser to read.

2. **No rework for 3.2.** The embedding design is content-keyed and idempotent, so when a WJQ parser
   lands, those JDs re-parse to different text → `text_sha256` moves → they **re-embed automatically**.

**The consequence lands on Phase 3, not HR: embeddings and clustering see only ~65% of the archive
until WJQ is parsed.** **File WJQ parser support as a task that BLOCKS 3.5 (clustering)** — a
cluster report produced before it would silently cover 65% of the corpus, which is exactly the trap
2.6 taught (metrics computed on a corpus quietly missing a third of itself). It does **not** block
3.3/3.4.

---

## What 2.5-prep established about the archive — read before you trust any archive claim

Both pre-baseline fixes are merged. **The most valuable output was not the code — it was the
measurements**, because two of the three things we *believed* about the archive turned out to be
false, and only running against the real corpus revealed it.

**Measured on the real archive** (`C:\repos\hris\fixtures\SFU_JDs`, through this repo's own
`ingest/extract.py`; several independent random samples, all agreeing):

| Belief | Reality |
|---|---|
| "Zero-width chars are a routine `.docx` artefact" | **FALSE.** 600–799 `.docx` sampled: **zero** Cf chars, zero soft hyphens, zero ligatures. `<w:softHyphen/>` exists as an XML *element* in 7 files — python-docx drops it before the scanner sees it. The ZWSP fix is correct hardening but moves **~nothing** on this archive. |
| "HR-058 is the archive's highest-frequency false positive" | **Not the biggest one.** The real one was **line-wrapping**: antiword hard-wraps legacy `.doc`, so `"equivalent\n   combination"` read as *missing the equivalency path*. `SFU-QUAL-EQUIVALENT` drops **~50%** (74→35, 97→47, 72→34 across samples — ~10% of legacy JDs). |
| "The territorial-ack + equity footers have HR-058's bug too" | **FALSE.** With the exemption forced off, both produce zero coded terms, zero markers, zero restricted titles. Only `about_sfu` hits. |

**The lesson, and it is now a rule: every claim about the archive must be checked against the
archive.** Two coders and the orchestrator all reasoned confidently from "zero-width chars are
common in .docx". They are not, in this corpus. The reviewer was the only one who looked, and it
overturned the premise of an entire PR — a PR whose false narrative was about to be written into
2.5's provenance.

Also established: the JDs contain **real leftover template instructions** (e.g. *"For each item
start with an action verb and briefly describe WHAT is done…"*, still sitting in a live JD), which
the line-wrap had been hiding from the placeholder gate. Expect 2.5 to surface more of these.

---

## The decision register — read this before touching a rule

`docs/decisions/HR-DECISION-REGISTER.md` (generated by `make register` from
`core/src/jd_core/rules/decision_register.yaml`; `make register-check` fails the build on drift,
also wired into CI). **192 decisions, all `open` — SFU HR has ratified nothing yet, but the packet
is now written and the numbers in it are corrected: `docs/decisions/HR-REVIEW-PACKET.md`.**

Provenance (at 192 entries): **101 our-invention · 72 hris-calibration · 19 SFU-rulebook**. The entire approval
bar — score floor 60.0, grade floor C, the severity floor, the 14-rule blocking set, the 2
non-overridable gates — is **our invention, not an SFU number**. It must be ratified against the
Phase 2.5 archive baseline (see Next up, below).

**Standing rule for all future work:** any non-trivial metric or rule change must be
YAML-configurable — never a code change — and must land with a register entry in the *same* PR.
**If a default looks wrong, register it as `open`. Do not quietly patch it.**

Enforcement (the build fails if): a register config path doesn't resolve against live rules; a
`current_default` drifts from the live value; a param on the 253-item decision surface is
neither registered nor explicitly exempted with a stated reason; or the surface enumerator
itself is shrunk to dodge that check.

### Known false positives / landmines (registered `open`, behaviour deliberately unchanged)

| ID | Issue |
|---|---|
| HR-058 | **FIXED** (PR #16). SFU's mandated "do not edit" About SFU paragraph contains `compassionate`, a **medium** coded term — a compliant JD scored 91.5/A → 81.5/B, and omitting the paragraph tripped `SFU-COMP-ABOUT` instead. The coded-term scan now redacts SFU's mandated passages first. The exemption is granted to SFU's **TEXT** (verbatim, modulo folding), never to a **location** — so coded language cannot be smuggled through by wrapping it in boilerplate-shaped prose (verified against 11 adversarial JDs). |
| HR-108 | Whitespace-run collapsing treats a paragraph break as one space — which would weld two unrelated paragraphs and **invent** findings, including a non-overridable `SFU-STRUCT-PLACEHOLDER` gate trip (a permanently un-approvable JD, no waiver). Default is therefore **paragraph-aware** (`collapse_across_paragraph_break: false`). Measured: the safer default costs **zero** of the −50% `SFU-QUAL-EQUIVALENT` win — both settings give byte-identical findings on the real archive, with the boundary genuinely engaged (100% of `.doc`, 47% of `.docx`). Free insurance. |
| HR-119/121 | ~~`SFU-STRUCT-HOW-WHY` fires on 100% of approvable JDs~~ **FIXED (2.6)** — it was **unevaluable**: the parser never populates `how_why`, so it could never *not* fire. Retired as data; Phase 4 reinstates it with one YAML word once the parser extracts the field. |
| HR-041/120 | ~~`SFU-QUAL-BANNED-PHRASE` scans the whole document~~ **FIXED (2.6)** — blocks 104 → 0, **+59 approvals**. **New open question:** correctly scoped it now fires on **10 files in 14,522** — guard-rail nobody trips, or missing the phrases SFU authors actually write? |
| HR-047 | `action verb` / `how and why` / `what by` are placeholder markers feeding the **non-overridable** no-placeholders gate → a JD that merely discusses action verbs is permanently un-approvable, no waiver. **2.5 measured it: 29.4% of the archive, 23.4% of latest-per-position, but ZERO current-practice JDs — a legacy menace, not a threat to what SFU writes today.** |
| HR-046 | Working-condition markers include `housing`, `parking`, `relocation` → a Parking Services JD naming its own domain is blocked. |
| HR-025 | A single `(50%)` duty allocation escapes SFU's Part-11.6 duty-total gate. |
| HR-048 | The incumbent regex (`\bmy\b\|\bmyself\b\|\bi am\b`) is the whole of Part 2B and it blocks, yet "he is responsible for…" passes. |
| HR-055 | The action-verb glossary is a CLOSED list missing `supports`, `delivers`, `liaises`, `writes` → well-written duties penalised for word choice. |
| HR-029 | 9 of the 31 coded terms are hris additions SFU never published (relabelled `hris_calibration`). |
| HR-059 | The title **seniority ladder** (vp/chief/director/manager/lead/associate/assistant) was shipped by hris as "SFU's official ladder (Toolkit p18-19)" — it is **not in the rulebook** (`chief` appears zero times; the only "VP" is a *restricted* title, Part 3.5). Now data (`titles.yaml :: families`), registered `open`. HR-029 in the title dimension. The *functional* table (analyst/officer/…) IS rulebook-sourced (Part 3.3) and is not in question. |

---

## How we work (KEEP DOING THIS — subagent flow)

Delegate implementation to subagents so the orchestrator's context stays lean. Per task:

1. **Tester+Coder subagent**: strict TDD (failing tests first → implement → `make gates` green in
   Docker), leaves changes uncommitted, reports a tight summary.
2. **Reviewer subagent** (merge-blocking): independently re-runs `make gates`, adversarial audit
   of scope/port-fidelity/quality, returns APPROVED / CHANGES REQUIRED. Route any must-fix back to
   the coder subagent via SendMessage (keeps its context) before PR.
3. **Orchestrator (you)**: on APPROVED, commit → push branch → open PR → watch CI → merge (rebase).

### Model tiering — see `docs/subagent-model-strategy.md`

**Spend on judgment, not on typing. Reviewers are ALWAYS the strongest tier (Opus) — never
downgrade the checker.** Coders may drop to Sonnet/Haiku when the task is well-specified with a
strong mechanical oracle (wiring, transcription, renames, docs). Never downgrade: faithful ports,
rulebook/policy semantics, security-touching diffs, or anything changing a decision parameter.
Tier B/C subagents must STOP and escalate on any judgment call rather than guess.

Why the Reviewer stays expensive: across all four Phase 2 tasks it returned CHANGES REQUIRED
**every time**, and every finding was real — an unpinned 116-verb glossary, a validator that
**crashed** on real archive input, a non-overridable gate that could not fire, and a decision
surface silently missing 4 of 10 rule files. Coders were competent but consistently over-claimed.

---

## Non-negotiables (enforced)

- **Docker-only (ADR-006):** NO host Python/venv/pip. All code/tests/gates/migrations run in
  containers. `make gates` runs the FULL suite (ruff·black·mypy--strict·unit·integration·
  coverage≥80) in the one-shot `gates` compose service — self-contained, CI-identical. Only
  Ollama runs on host metal.
- **Storage (ADR-002):** Neo4j = vectors (768-dim cosine, `nomic-embed-text`) + graph;
  Postgres = all relational/transactional SQL; Redis+arq = queue. **NO pgvector.**
- **Rulebook as tests / as data:** every SFU gate = a failing-fixture + passing-fixture test;
  gates/verb-lists/lexicons live in versioned YAML under `jd_core/rules/`, never hardcoded.
  Validator is the oracle (assert post-state, never verbatim LLM text).
- **Human approval:** canonical JDs are drafts until an HR reviewer approves; nothing
  auto-publishes. Gate overrides require a written reason in the audit log.
- **Local-first / job-not-person:** Ollama only; incumbent names normalized out of canonical JDs
  as a RULEBOOK quality step — NOT a resume-grade privacy gate (these are JDs, not resumes).
- **Claude-only:** the Codex/Copilot harness layers were removed. Don't reintroduce them, pgvector,
  or `make use-*`.

---

## Gotchas learned (save yourself the pain)

- **A test whose docstring NAMES a mechanism must be run against that mechanism being broken —
  otherwise it is a decoy.** 3.3 shipped one: `shingles.py` passed `join_paragraphs=True` and its
  docstring claimed *that* was what made a `.doc` and its `.docx` twin shingle identically. It is
  **inert** — `textnorm.PARAGRAPH` is U+2029 and the tokenizer (`[a-z0-9]+`) discards it, so the token
  stream is identical either way. Making the shingler consult HR-108 — *exactly the regression the
  module exists to prevent* — left **all 20 tests green**, including the one whose docstring said it
  would go red. The property was true; the stated mechanism was false; the pin was worthless. This is
  the **third** appearance of "a correct fix pinned by nothing" (3.2a SAVEPOINT, 3.2b skip-predicate +
  sha→vector binding, 3.3 this). **A green suite proves nothing about a guard you have not tried to
  break — and if a test's docstring explains WHY it holds, break that why and watch it go red.**
- **The reconcile prune deleted DATA on a class the design forgot (3.3).** A transient read failure
  *pruned a document's real near-dup edges*, because the prune scope was derived from rows **fetched**
  rather than documents **read**. The rule: an **unreadable** document is an *unknown, not a "no"* — it
  must never prune. A **below-min-shingles** document is a deterministic function of config+text — it
  **must** (raising `min_shingles` has to delete). Any prune/reconcile you write (Tier-3, re-cluster)
  inherits this: derive the keep-list from what you *successfully processed*, and pin BOTH directions
  (unreadable → no prune; below-threshold → prune).
- **The reviewer paid for itself again: 10 real defects across 3 rounds on 3.2b, 6 on 3.2a, 4 on 3.3.**
  The two most dangerous on each were the **same class — a correct fix pinned by NOTHING**: (3.2a)
  the SAVEPOINT protecting a caller's uncommitted work — the exact bug 3.1 spent a migration fixing
  — had a race test whose racer *committed first*, so the pre-check short-circuited and the guarded
  branch was never reached. (3.2b) dropping `text_sha256` from the skip predicate (the whole
  content-identity guarantee) left all 1242 tests green; reversing the runner's sha→vector binding
  — **every vector on the wrong JD** — left all 12 integration tests green. **All now go red.** The
  standing lesson holds: **a green suite proves nothing about a guard you have not tried to break.**
- **A test fake can make a bug unwritable.** 3.2b's fake embed client keyed vectors on **batch
  index**, so two different texts at the same position got the *same* vector — which made the entire
  class of "this node got the vector of its own text" assertion silently impossible to write. **Fakes
  in this suite must be content-keyed.**
- **An `OSError`-unreadable file still gets no `source_documents` row** (zero such files in the 2.5
  ledger; every one of the 43 is extract-stage or the size cap). Unlike the oversized case, its bytes
  cannot be read *at all*, so `(storage_ref, sha256)` is genuinely unsatisfiable and a sentinel hash
  would collide in Tier-1 with every other unreadable file. Backlog line, not a hole to paper over.
- **`docs/embeddings/`** is bound by the `embed` compose service; keep the `.gitkeep` or Docker
  creates it root-owned.
- **The archive-claim rule caught the orchestrator itself in 2.5 — twice, in mirror image.** (a)
  The Phase 0 census (§8.2) says the territorial footer lives in `word/footer*.xml` and warns a
  body-only extractor will miss it. **That is FALSE for this corpus** — checked across 20 modern
  JDFN docs: it is in `word/document.xml`, and `footer*.xml` had it **zero** times. (b) Having
  verified that 17 of 20 *recent* JDFN docs carry the acknowledgement, the orchestrator nearly
  declared the 81% miss-rate a bug — but those 20 were the **newest 400 files**, the one slice
  where adoption is ~85%. The sample was worthless generalised to the era. It was only caught by
  cross-examining the validator against the raw text of **all 6,259** new-era JDs. **A sample
  drawn from the newest files is not a sample of the corpus. Check the claim against the whole
  archive, not against the slice that is easy to look at.**
- **OLLAMA IS ON `aria-gb10-2`, NOT ON THIS MACHINE — and the local/CI split is the whole story.**
  (ADR-003 amended 2026-07-13.) `docker-compose.yml` said `host.docker.internal` until someone
  checked; it is now `${OLLAMA_BASE_URL:-http://aria-gb10-2:11434/v1}`.
  **Verified from inside the `gates` container:** reachable, `nomic-embed-text` present, **768-dim**
  (matches the ADR-002 Neo4j index — checked, not assumed).

  | | Reaches `aria-gb10-2`? |
  |---|---|
  | **Local `make gates`** | ✅ **YES** |
  | **CI** (`runs-on: ubuntu-latest`, GitHub-hosted) | ❌ **NO, and never will** — a cloud runner cannot route to an internal host |

  So the old claim *"the `gates` container cannot reach host Ollama"* was **false locally and true in
  CI**, for a different reason than it gave — and it had been **deferring work** (the 4.2 prompts).
  **The rule it protected still stands, now enforced by topology rather than policy: `make gates`
  MUST NOT depend on a live model endpoint.** A test that calls Ollama passes on your machine and
  turns CI red — worse than not having the test, because it is intermittent and trains people to
  ignore CI. **Live golden tests are opt-in and local-only** (own make target, or a marker that
  *skips* when the endpoint is unreachable). Unit tests mock the client; integration tests mock the
  embedding call.

  ⚠️ **Data boundary changed.** Non-negotiable #5 no longer says "JD content never leaves this
  machine" — from 3.2, JD text crosses a private network to be embedded. The real invariant (**no
  third-party/cloud LLM API, no vendor egress**) is intact, and `aria-gb10-2` is a **trusted internal
  host**. These are SFU HR records, so **FIPPA applies**: if the inference host ever leaves a trusted
  segment, that is a **compliance decision to re-take, not a config value to edit.**
- **Any `repr()` in an exception message will break baseline reproducibility.** The runner is
  single-process *precisely* to guarantee two runs over the same archive produce byte-identical
  artifacts — that is what the audit trail is made of. Two things have already broken it: antiword's
  random **temp-file path**, and python-docx's **`<_io.BytesIO object at 0x7917...>`** — a heap
  address, straight into the skip ledger, from one real macro-enabled `.docx`. The second was missed
  when the first was fixed *and outlived a "verified byte-identical across two real runs" claim*.
  `_stable_reason` (`baseline/runner.py`) now scrubs both. **If you add an extractor backend, assume
  its exception messages carry per-run noise, and prove reproducibility by running the baseline
  twice — do not assert it.**
- **`segmentation.yaml` is registered but NOT hashed.** It is an ordinary rule file in
  `_FILE_MODELS`, excluded from the `rules_version` digest by `_UNHASHED_FILES = {REGISTER_FILE,
  SEGMENTATION_FILE}` — the exact mechanism `decision_register.yaml` already used. So editing it
  does **not** churn `rules_version` (which is right: it decides which *files* a baseline covers,
  never how a JD is *scored*). Reuse this pattern for any future "registered, but does not change
  what the rules decide about a JD" config. **Do not** give it a bespoke second-config-root
  subsystem — that was tried in 2.5, it forced a `jd_core → jd_bank` layering inversion, and the
  reviewer correctly demanded it be replaced by the one-line exclusion.
- **`jd_core` must not import `jd_bank`** — the rulebook is the pure core. Enforced by a ratchet
  (`test_no_new_core_to_bank_import_appears`, which `lstrip()`s so a lazy in-function import can't
  slip it) plus `test_the_rulebook_never_imports_jd_bank`. One pre-existing edge is pinned:
  `jd_core/parser/store.py` imports `jd_bank.db.models` (a persistence adapter; a genuine leaf, no
  cycle possible). **Backlog: move it.** If you add a re-export to `jd_bank/baseline/__init__.py`
  you will re-create a cycle that kills `get_rules()` — the ratchet is what stands between you and
  that.
- **`rules_version` is now content-derived, and that couples rule edits to `make register`.**
  Since 2.5-prep, `Rules.version` is `jd_rules_sfu_v4+<12-hex digest of the rule content>` — and
  `rules/render.py` renders it into the register Markdown header. So **any change to any rule
  YAML (except `decision_register.yaml`) now fails `make register-check` until you re-run
  `make register`**, even when no register prose changed. That is the intended forcing function
  (the committed register names the exact rulebook it describes), but it is new and it looks like
  a spurious CI failure the first time it bites. `decision_register.yaml` is deliberately excluded
  from the digest, so editing register prose does *not* churn the version.
- **The `gates` container mounts only `./core` at `/app`.** Tests must be self-contained under
  `core/tests/`; `docs/` and repo-root fixtures are NOT visible in it.
- **testcontainers work in the `gates` service** (Docker socket mounted + host-override env vars).
  Integration tests can run the real Alembic migration against a fresh PG.
- **`.gitattributes`** forces LF (so container shell scripts survive Windows) and marks binary
  fixtures — don't let CRLF/text filters corrupt binaries.
- `hris` (`C:\repos\hris`) is READ-ONLY reference for ports. `agent-harnesses-v2` is the live
  upstream harness this repo vendors (ADR-004). `C:\repos\jdbank` is STALE — ignore it.
- **Docker artifacts are now `jd-bank-*`** (compose project renamed from `agent-harness`, PR #14).
  `core/src/agents/` and `harness-claude-code/` keep harness naming — that IS the vendored harness,
  and the "built on agent-harnesses-v2" doc lines are true provenance, not stale names. The Neo4j
  password is still `harnesspass`: a **credential**, not a project name — renaming it is a
  behavioural change, not cosmetics.
- **"Faithful to hris" ≠ "correct here" — the most expensive lesson of Phase 2.4.** A *verified
  line-by-line faithful* port of `render.py` still shipped a data-corrupting bug: it emitted
  `PROBLEM SOLVING & LEVEL OF SUPERVISION`, which this repo's parser (`fullmatch`, ` AND ` only)
  cannot read — so re-parsing a rendered JD silently swallowed the entire Problem Solving section
  and the validators then misfired on a JD that was complete. It was harmless in hris because hris
  re-parsed **with an LLM**; here the reader is a regex. Gates were green throughout. **Every port
  lands in a repo whose consumers differ from hris's — check the consumer, not just the source.**
- **One rulebook fact, one home.** The `max_listed` duplicate-knob landmine turned out to be
  systemic: the same shape appeared three more times in 2.4 (Hay modifiers, the two education
  ladders, education cues). All are now closed with **load-time cross-file validators** — rename a
  term in one file and the rulebook *fails to load* instead of silently zeroing a score. Reuse that
  pattern (`loader.py`: `_hay_modifiers_exist_on_the_rulebooks_own_scales`) whenever a vocabulary
  is referenced from two files, and close the outstanding `max_listed` item the same way.
- **A green `make register-check` does NOT mean "everything is registered."** It only diffs the
  register *Markdown*. Surface coverage is enforced by **`make gates`** (the `_OFF_SURFACE` guard
  test in `tests/unit/test_decision_register.py`). Run both.
- **Prove a decision is pinned by MUTATION, not by reading the test.** The bar: change the shipped
  YAML value *and update the register in step so the drift alarm is silent* — a **behavioural** test
  must still go red. Tests that pin only the branch let HR move the number with nothing failing.

---

## Next up

### ⏭ Phase 4 — Harmonization & review. **4.1 merge engine MERGED + calibrated; 4.2 next.**

Task files now live under `docs/tasks/` (`phase-4.1-merge-engine.md` and
`phase-4.1-followup-merge-runner.md` are the templates — goal / files-in-scope / design contract /
acceptance / out-of-scope).

- **4.1 merge engine — DONE (PR #46).** See Current state. Pure `bank/merge.py`, drafts only.
- **4.1 calibration + runner — DONE (this session).** The `jd_bank/harmonize/` measurement runner and
  the knob calibration (follow-ups #1/#3). One default moved (`max_duties` 10 → 12), 8 kept with
  measured evidence in the register. `docs/harmonize/summary.json` is the measurement of record.
- **4.2a harmonize rewrite pass — DONE (PR #49).** LLM scaffolding (`jd_bank/llm/` `ChatClient` +
  prompt loader, ported `jd_harmonize_v1`) + the consumer `jd_bank/rewrite/harmonize.py::rewrite_merged_role`:
  feeds the GROUNDED 4.1 draft (not raw members), anti-fabrication guard scrubs ungrounded
  skill/knowledge/ability quals + flags invented duties, scores via the validator → frozen
  `RewrittenDraft` (no approval field, NN #1). `rewrite.yaml` REGISTERED + UNHASHED (wording ≠
  scoring; not in `rules_version`), HR-176..184 all `open`/`our_invention`, PROVISIONAL. Live golden
  opt-in/local-only (`make rewrite-golden`). Task file: `docs/tasks/phase-4.2a-harmonize-rewrite.md`.
- **4.2b quality audit pass — DONE (PR #51).** `jd_bank/quality/audit.py::audit_quality(jd)` — the
  nuanced LLM pass (`inclusive_language`/`clarity`/`seniority_mismatch`) with the **verbatim-evidence
  anti-fab scrub** (a finding whose `evidence` is not a casefold substring of the JD is DROPPED,
  ported from hris `_merge_llm_findings`). **Advisory: computes NO score/grade** — the deterministic
  validator stays the oracle (NN #3); frozen `QualityAudit` has no approval/canonical field (NN #1).
  Reuses 4.2a's `ChatClient` (now generalized with optional `model`/`temperature` overrides,
  back-compat) + prompt loader. `_flatten_jd` extracted to a SHARED `jd_bank/jd_text.py::flatten_jd`
  (the 4.2a Relationships must-fix made structural — audit haystack == rewrite serialization, one
  home). New `quality.yaml` REGISTERED + UNHASHED (7th unhashed file), HR-185..190 all
  `open`/`our_invention`, PROVISIONAL (calibrate at 4.5). `make quality-golden` opt-in/local-only.
  Reviewer (Opus) APPROVED — independently re-ran gates and broke all four load-bearing pins
  (guard-off ships the fabricated finding; flattener dropping a section reds the Relationships pin;
  wrong model source reds; un-hashing reds). Task file: `docs/tasks/phase-4.2b-quality-audit.md`.
  Gates **1641 passing, 93.76%**. Two follow-ups it created (see below).
- **4.3 change-log/diff — DONE (PR #52).** Pure `jd_core/bank/change_log.py::build_harmonization_diff(merged, members, *, rewrite=None)`
  → frozen `HarmonizationDiff` (`rendered_draft` via `render.py` display-only, `per_source`
  `SourceContribution`, `removed` `RemovedContent`, `flagged_duties`). Reuses the merge's exact
  ordering + group fate (shared public `merge.canonical_member_order`/`dropped_duty_occurrences`/
  `unmerged_content`; `merge_cluster` byte-identical). Optional 4.2a rewrite folding (scrubbed skills →
  `removed`; flagged duties → `flagged_duties`, not removed). NO new knobs; `rules_version` untouched.
  Task file: `docs/tasks/phase-4.3-change-log-diff.md`. **Follow-up:** a `jd_bank/` runner that loads
  real clusters and writes a change-log artifact over the archive (out of scope in 4.3 — the pure
  generator landed first, exactly as the 4.1 merge engine did before its measurement runner). **⚠ the
  `removed` list is NOT exhaustive over the KSA rebuild's incidental non-core-skill drops** — those are
  deliberately outside `RemovedReason`, visible instead via `MergeProvenance.skill_frequency` (noted in
  the `change_log.py` docstring); the runner/4.4 UI should surface skill_frequency alongside `removed`.
- **4.4 review queue — decomposed (user-chosen slicing): producer → service → routes → server-rendered UI.**
  - **4.4a canonical-draft PRODUCER — DONE (PR #53).** See header. Clusters → persisted DRAFT `canonical_jds`.
    Task file: `docs/tasks/phase-4.4a-canonical-draft-producer.md`.
  - **4.4b review SERVICE + audit — DONE (PR #54).** `jd_bank/review/service.py` — list_review_queue /
    get_review_packet / approve / reject / edit over the DRAFT canonicals; the human-approval spine (see
    header). Task file: `docs/tasks/phase-4.4b-review-service.md`. **Follow-up:** a concurrent double-approve
    test (the `FOR UPDATE` lock is real + the sequential stale-status guard is pinned, so the invariant holds;
    a true concurrency test is a pilot backlog line).
  - **4.4c FastAPI routes — DONE (PR #55).** See header. Thin `/jd-bank` router over the 4.4b service
    (`core/src/api/routes/jd_bank.py`), TestClient-tested, error→status map + commit discipline pinned.
    Task file: `docs/tasks/phase-4.4c-review-routes.md`. Two follow-ups (both out of scope, in header):
    pre-existing `jd_core→jd_bank` edge in `parser/store.py`; optional `get_session`→`api/deps.py`.
  - **4.4d server-rendered UI — DONE (PR #56, MERGED LOCALLY — GitHub CI billing-blocked, PR still open).**
    See header. Minimal `/jd-bank/ui` inside FastAPI (user-chosen: server-rendered, gated). Task file:
    `docs/tasks/phase-4.4d-review-ui.md`. **Reconcile PR #56 on GitHub once Actions billing is restored**
    (re-run CI; the branch `feat/4.4d-review-ui` is already ff-merged into local `main`). Follow-ups: the
    edit view's raw-JSON `<textarea>` → a structured per-field editor; surface
    `MergeProvenance.skill_frequency` alongside the 4.3 `removed` list (not exhaustive over incidental
    KSA-rebuild skill drops — 4.3 note) — neither built in 4.4d (minimal).
  - **4.5 — NEXT.** Pilot 5–10 clusters with a real HR reviewer over the now-complete review queue
    (producer → service → routes → UI); feedback → fixtures/rules. Every pilot bug becomes a regression
    fixture (NN #7). This is where the 4.2/4.3/4.4 provisional `open` defaults get calibrated against a
    human's judgment.
- **4.4a follow-up — DONE (PR #57, MERGED LOCALLY — GitHub CI still billing-blocked, PR open).** Split the
  injected LLM `client` into `rewrite_client` (bound to `rules.rewrite.model`, the `ChatClient` default) +
  `audit_client` (bound EXPLICITLY to `rules.quality.model`/`temperature`). `run_canonical_producer` /
  `_process_cluster` / `_run_llm_passes` take both; `llm_enabled = rewrite_client is not None`; the advisory
  audit runs only when an `audit_client` is provided; `rewrite_client=None` is the deterministic `--no-llm`
  path. New `__main__._build_clients(rules, *, no_llm)` constructs the pair (both-or-neither) and `_run`
  closes both. **Why it mattered:** `audit_quality` always stamps `QualityAudit.model = rules.quality.model`
  from the RULES, not the client — so with one rewrite-bound client the audit stamp becomes a lie the moment
  `quality.yaml` is retuned (NN #6). Today the two YAMLs are byte-identical so nothing lied yet; the split
  makes the audit follow `quality.yaml`. **Pure wiring — no rules/YAML/register/schema change** (registered
  nothing, as specified). Two pins, both proven RED by the Opus reviewer under their regression: routing
  (distinct fakes each see only their own schema — re-merging reds it) + binding (`_build_clients` forces
  the two models apart so identical defaults can't mask a regression). Gates **1734, 93.89%**. **Reconcile
  PR #57 on GitHub once Actions billing is restored** (branch `chore/4.4a-split-llm-clients` is ff-merged
  into local `main`; the "Gate: branch-name" failure is the billing block — the runner never starts — not a
  real gate failure, same as #56).

**Follow-ups 4.2b created:**
- **Structural-bar inflation guard (DEFERRED, its own task).** Decided in 4.2b, NOT implemented: the
  4.2a *rewrite* guard scrubs only `skill/knowledge/ability`, so an LLM inflating "Bachelor's → PhD"
  in a rewrite still passes (same class as the 4.1 experience-bar-inflation defect). 4.2b's audit is
  READ-ONLY and cannot inflate a bar, so the risk lives in 4.2a. Catching it needs a level-COMPARISON
  (education ordinal / experience years), not the token-grounding the guard does — a deliberate change
  with its own blast radius. Register `open` when added.
- **Provenance stamp can outrun the injected client (4.4 wiring note).** `audit_quality` stamps
  `QualityAudit.model = rules.quality.model`, but the `ChatClient` is injected and could be bound to a
  different model (faithful to 4.2a's `rewrite_merged_role` pattern — nothing asserts stamp == actual
  client model). When 4.4 wires the caller, bind `ChatClient(model=rules.quality.model, ...)` so the
  stamp cannot lie. Optional defense-in-depth: pin the scrub's accepted categories to the 3 nuanced
  ones (`JDQualityFinding.category` currently accepts all 9 `JDIssueCategory` values; only the system
  prompt, not code, constrains output — a model returning a structural category with grounded evidence
  passes through as an advisory `source="llm"` issue). Within contract today (audit is advisory), but
  worth closing.

**Follow-ups 4.1 created (do before/with the harmonization pilot):**
1. ✅ **DONE (this session) — calibrated the 9 `harmonization.yaml` defaults against the real
   clusters.** Built the runner (#3 below), ran the merge over **1,801 JDFN clusters**, measured the
   distributions each knob cuts on, and registered the measured evidence into HR-167..175 (so none
   hardens by inertia — the HR-093/HR-121 lesson). **Only ONE default moved: `max_duties` 10 → 12**
   (HR-172), aligned to the model's own `duties` cap (`parsed_jd.py:104`, `max_length=12`): at 10 the
   `duties_over_max` flag fired on 374/20.8% of clusters, 288 of which held 11–12 duties the model
   could keep; at 12 it fires only on the 86/4.8% where the cap forces a *real* drop. Mutation-pinned
   (reverting to 10 goes red on a behavioural assertion, not the drift alarm). The other 8 knobs are
   **well-supported as-is** and kept: `duty_dedup_jaccard_min` 0.7 sits at the pairwise-Jaccard
   **valley floor** (global min 0.70–0.75; outcome threshold-insensitive); `core_skill_min_fraction`
   0.5 sits in the sparse valley of a bimodal skill distribution; the title/summary/context/presence
   policies all match the measured shape. Artifacts: **`docs/harmonize/summary.json`** (the measured
   distributions) + `clusters.csv` (per-cluster scalars, counts-only). See Current state.
2. **%-rebalance of duty allocations — DEFERRED from 4.1, its own task.** Allocations are free-text
   `(NN%)` inside duty statements (validator regex, Part-11.6 duty-total gate), **not** a structured
   `SFUDuty` field. Merged drafts currently carry duty statements *verbatim*, so a merge of two
   members can produce allocations that don't sum to 100. Rebalancing needs allocation extraction +
   the Part-11.6 gate interaction — a deliberate change, not a drive-by.
3. ✅ **DONE (this session) — the `jd_bank/harmonize/` runner that loads real clusters and drives the
   merge.** Read-only (rollback, no `Cluster` row), deterministic (byte-identical over two runs),
   single-process. Recomputes clusters in-process via `run_clustering` (NOT the lossy filename-keyed
   3.5 CSV), reloads each member `SFUJobDescription` (`signals_load.load_member_jds`), JDFN-only.
   `make harmonize-measure` + a `harmonize` compose service. This is where #1's measurement ran.
4. **The un-merged sections** (`decision_making` / `problem_solving` / `relationships` /
   `position_number`) are left at model defaults by 4.1 and surfaced by the `sections_not_merged`
   provenance flag. Merging them each needs its own registered per-section policy — fold into 4.2/4.3
   or a dedicated task; the flag keeps the gap honest for the 4.4 reviewer meanwhile. **Measured: the
   flag fires on 1,762/1,801 (97.8%) of JDFN clusters** — nearly universal, so the un-merged sections
   are the norm, not an edge case. Prioritise a per-section merge policy accordingly.
5. **WJQ harmonization stays BLOCKED** on WJQ boilerplate redaction + `.doc` title extraction (the
   Phase-4-priority follow-ups from Phase 3) — the merge engine is exercised on JDFN clusters only.

**New follow-ups this calibration created:**
6. **Persist `ParseResult.template`.** `jd_core/parser/store.py` drops it, so the harmonize runner
   filters WJQ by the `employee_group == "cupe"` proxy — which conservatively **over-excludes ~189
   genuine JDFN docs that merely name CUPE** (safe direction for the JDFN bar, and *counted*, never
   silent — but imprecise). Persisting `template` makes WJQ filtering exact here and unblocks the WJQ
   work (#5). A schema/parse-key change, its own task.
7. **The 3.5 cluster artifacts leak JD prose the same way `clusters.csv` almost did** — `docs/cluster/
   cluster-report.csv` + `cluster-members.csv` commit `cluster_label` = the modal member `title`,
   which the parser frequently fills with a whole summary/boilerplate paragraph (~46% of rows). Same
   root cause the 4.1-followup reviewer caught and we fixed in `harmonize/clusters.csv` (dropped the
   `label` column; pinned by `test_clusters_csv_has_no_jd_title_or_text_derived_column`). **Scrub the
   3.5 artifacts on a chore branch** (drop/replace the prose label), NOT mid-feature. Artifact-hygiene,
   not a privacy breach (JD prose, not incumbent PII), but these are HR records and the rule is
   counts/labels/filenames only.
8. **`seniority_bar_policy` max-vs-modal is an HR policy call, not an engineering one.** Measured: bars
   rarely diverge (education spread 0 in 817/844; experience 0 in 756/843), but `max` differs from
   `modal` on ~77 clusters. Kept `max` (do not understate a stated requirement), registered HR-175 —
   but whether a harmonized role should take the **highest** or the **most-common** stated bar is a
   ruling for the 4.5 pilot, not a default to flip unilaterally.

### ⏭ HR ratification. **Read `docs/decisions/HR-DECISION-MATRIX.md` + `POST-REVIEW-CHANGE-PLAN.md`.**

**Phase 2.6 is done: the three defects that were distorting HR's numbers are fixed and the archive
is re-baselined.** So the packet HR reads now carries *corrected* figures — we fixed first, then
asked. **Keep doing it in that order.**

What remains is genuinely HR's (6 decisions): the 100–150 word range that is the *real* gatekeeper;
the un-appealable no-placeholders gate (recommend making it waivable); the footer gate that blocks
94% of the archive (recommend the composer auto-inserts the boilerplate instead of penalising
authors); the score/grade/severity floors (recommend ratify — they reject 2 of 874); whether the
banned-phrase list is missing the phrases SFU authors actually use; and whether "current" should mean
a date or the footer's presence.

Recording a ruling: flip `status: open` → `ratified` and set `decided_by` / `decided_on` /
`decision_note`. **The loader enforces all three** — a ratified entry without them fails to load. Use
it; do not invent a side file.

> ⛔ **Do not** hand HR a number, collect ratifications, and *then* fix a bug that moves it. The
> register would record "HR ratified 60.0" against a distribution that no longer exists.

⚠️ **If the footer gate is auto-inserted (recommended):** CLAUDE.md's standing open flag —
*"territorial acknowledgement wording: verify against SFU's current official text"* — **becomes
blocking**, because we would then be *generating* the wording, not merely checking for it. Get the
official text from HR in the same review.

- **Phase 3 — dedup & clustering. ✅ ALL COMPLETE (3.1–3.5 merged and run).** Cluster report generated with 2,458 clusters; 9 flagged for HR review. Phase 4 (harmonization & review) is next.**
  - **3.1 landed a schema change worth knowing:** `source_documents` is now **one row per FILE**
    (the UNIQUE on `sha256` is gone), and dedup is a **finding** — `DedupEdge` rows — not a silent
    write-time collapse. It was a **provenance bug**: `ingest_document()` returned the existing row
    on a duplicate SHA, so ~1,972 duplicate files would have been ingested with their filenames
    **discarded entirely**, while `DedupTier`/`DedupEdge` sat dead (an edge needs two source ids;
    the duplicate never got one). All three tiers now write into the same edge table.
  - **The 3.1 finding that matters for 3.5:** **798 of the 1,037 duplicate groups (77%) span more
    than one `position_id`** — 2,463 files. Those are **not re-saves**; they are *distinct positions
    sharing a byte-identical JD*. Only 141 groups are genuine re-saves. **Tier-1 hands clustering a
    role cluster with similarity pinned at 1.0, for free, before a single embedding is computed.**
  - **3.3 (Tier-2 near-dup) is DONE and RAN: 14,312 near-dup edges** over the archive (MinHash/LSH on
    word-5-gram shingles → **exact Jaccard** confirm, `jaccard_min: 0.85`). **67.5% of edges span
    different positions** — cross-position cloning again, consistent with 3.1's 77%. The reconcile is
    proven idempotent on the real corpus (2nd pass: 0 written / 0 updated / 0 pruned). Two measurements
    settled the design, both now in `dedup.yaml` + register HR-131..HR-140:
    - 🔴 **`clone_threshold: 0.92` IS MEANINGLESS ON THIS CORPUS, and now it is MEASURED, not
      predicted.** Nearest-neighbour document cosine: median **0.988**, **98% of JDs have a neighbour
      ≥ 0.92** — a cosine bar confirms *everything*. Word-5-gram Jaccard on the same corpus discriminates
      hugely: NN median **0.126**, random-pair median **0.0022** (p99.9 = 0.30). So **Jaccard drives and
      `cosine_confirm_min` ships `null` (OFF)** — the path is implemented and tested, but a filter that
      can never reject is HR-121's dead gate inverted. **HR-093 is amended with this measurement; it must
      be re-derived before Tier-3 uses it.** Never quote a document-cosine similarity as evidence two SFU
      JDs are the same role without stating the baseline neighbour cosine.
    - 🔴 **The obvious oracle is WORSE than no oracle.** "Same `position_id` ⇒ duplicate" fails: same-
      position pairs median Jaccard **0.30**; cross-position LSH candidates median **0.58** — *the
      negatives are more similar than the positives*. Tuning `jaccard_min` on it pushes the threshold the
      wrong way. `fixtures/labels/pairs.csv` (12 near-dup positives / 44 files / `best_guess_label` column
      / authored against a census this repo later caught being wrong) **cannot be a precision/recall CI
      gate** — one error swings recall 8 points. 3.3 ships a **pinned behavioural fixture** (exact
      candidates/Jaccards/edges — move a knob → red) + an **adjudication sample**
      (`docs/dedup/near-dup-adjudication-sample.csv`, 192 stratified pairs, empty `human_label`) so a real
      label set can finally be built. *The old one is bad precisely because nobody ever generated
      candidates to adjudicate.*
    - **Two structural decisions carried forward:** Tier-2 edges are **NOT additive** (a Jaccard edge is
      only true relative to a threshold + shingle config), so the runner **reconciles: insert / update /
      prune** — a MERGE-only design would leave the DB full of edges from a config that no longer exists.
      And the EXACT/NEAR ladder is closed **structurally** (candidates generated over one signature per
      distinct `sha256`), pinned by a 6-member star-group test — the naive "skip pairs with an EXACT edge"
      check is wrong under Tier-1's `star` topology (only 5 of a 6-group's 15 pairs carry an edge, so it
      would write the other 10).
  - ✅ **Both extraction defects DONE.** WJQ Custom template parser (#32, #33) and `_extract_docx`
    tables/controls fix (#30, #31) are merged. Archive-wide broken parses: 4,984 → 1,706 → 105 (99.3%).
    **3.5 clustering is now UNBLOCKED.** Plus: **WJQ boilerplate redaction** (14-section scaffolding
    near-identical across ~4,300 files) inflates their mutual similarity and is a **Phase-3.5 quality
    follow-up** — not a blocker, but WJQ files will over-cluster on shared template unless the scaffolding
    is redacted like JDFN's About-SFU/territorial/EDI passages.
  - ✅ **3.4a — ParsedJD → JobSignals adapter + title normalizer** (PR #38, MERGED). Wired 2.4c's pure-but-uncalled `similarity`/`clustering`/`drift`. New `jd_core/bank/signals.py`: `build_job_signals(jd) -> JobSignals` (skills = an **idf-less keyword bag** from `{skill,knowledge,ability}` quals minus stopwords — honestly degraded vs an ontology, empty for ~41% of JDs with no quals) + `canonical_title`. Frozen `JobSignals`/`CanonicalTitle` in `models/bank.py`. Two measured drift fixes: **word-number years** (1,116 → 5,573 derivable) and **education from `[education, knowledge]` quals** (JDFN's degree in `knowledge` blob → 1,161 false-positive "bachelors" reduced to 4 FPs). Register **HR-149..HR-154**; ADR-007. Reviewer-approved (Opus); the one defect (all-6-kinds education FP) caught by measuring against the archive.
  - ✅ **3.4b — Tier-3 role-equivalence runner** (PR #39, MERGED). Writes `DedupEdge(tier=ROLE_EQUIVALENT)` blending doc-vector cosine + idf skill overlap + seniority via 2.4c's `score_job_similarity`. **Two user decisions:** skills = the idf keyword bag (`families={}`, ontology deferred; idf computed in-runner, floored at 0); the over-merge guard = **title-family-band CONFLICT veto** (bands >`max_band_gap`(1) apart never role-equivalent; `employee_group` soft veto both-known-and-differ; `grade` unused). **`role_equiv_threshold = 0.5`** — measured: 99.2% pos / 3.0% neg. **Honest limitations, all registered:** 70% of titles `family=="unmapped"` so band veto is partial (~30%); positives are Tier-2 weak labels (no honest P/R gate — ships pinned fixture + stratified adjudication sample); blended score bimodal (41% empty-skills pairs floor ~0.52). Register **HR-155..HR-160**; `make dedup-role` + compose service. Reviewer-approved (Opus) after one round; **two defects were real crashes on real data that synthetic fixtures hid** — near-identical 768-dim embeddings compute cosine >1.0 (16% of real pairs) → ValidationError; ubiquitous skill's negative idf. Both clamped + pinned with real-magnitude fixtures. **Perf follow-up (HR-159 note):** candidate gen O(bucket²) in 8,215-doc `unmapped` bucket (~1hr whole-archive; completes) — Neo4j vector-index top-k is the follow-up.
  - ✅ **3.4b Tier-3 archive run** (PR #41) — **COMPLETE**. `make dedup-role` over full archive: **133,842 ROLE_EQUIVALENT edges** at the **0.75 threshold** (260,357 candidates → 4,248 vetoed → 256,109 admissible → 133,842 qualifying). Measured clustering knee: the measured bimodal score distribution (41% empty-skills pairs floor ~0.52; 59% floor ~0.68) collapses into a single **8,884-JD blob** at 0.5; breaks at gate 0.75. Per-tier edge admission strategy finalized: EXACT/NEAR always-in, ROLE gated at `cluster_role_equiv_min=0.75` (the measured knee). Writes `docs/dedup/role-equiv-summary.json` + `role-equiv-adjudication-sample.csv`.
  - ✅ **3.5 clustering runner** (PR #42, MERGED) — **report-only, not persistent** (re-cluster reconcile would cascade-delete approved canonicals; report suffices). **Per-tier edge admission, NOT scalar threshold** (🔴 **key landmine**: edge scores incomparable across tiers [EXACT=1.0, NEAR∈[0.85,1.0], ROLE bimodal ∈[0.5,1.0]]; naive 0.80 threshold silently discards every ROLE edge in [0.5,0.80)). **Synthesize EXACT connectivity in-runner from sha256** (Tier-2 structurally excludes byte-identical pairs). **Two-stage over-merge guard:** edge admissibility (reuse 3.4b band/group veto) pre-union-find + post-union-find band-spread/group-mix/oversize **cohesion cap that FLAGS (not auto-splits)** for HR eyeball pass. Register **HR-161..HR-166** (cluster_tiers, cluster_role_equiv_min, cluster_max_band_spread, cluster_group_homogeneous, cluster_max_size, cluster_representative_policy) all measured post-run. Reviewer-approved (Opus): the three safety properties (no-Cluster-write/no-commit, the blob guard, EXACT synthesis) verified by mutation against the real 150,879-edge DB. Tests **1518 / 94.02%**.
  - ✅ **The cluster report** (PR #43, Phase-3 EXIT deliverable) — **2,458 role clusters** over 14,522 signed JDs — largest 132, **9 flagged** for HR review, 75.1% coverage, 3,620 singletons. 47,113 edges admitted (103,723 dropped by the 0.75 ROLE gate, 43 by the veto, 1,965 EXACT synthesized). Committed to `docs/cluster/`: `cluster-summary.json`, `cluster-report.csv` (row per cluster, ordered needs-eyes-first, empty `human_verdict` column), `cluster-members.csv` (counts/labels/filenames only, never JD text).
  - 🔴 **Key finding — the report reveals honest clustering quality limits:** the two largest flagged clusters ("Untitled Position" n=132 and n=108, both CUPE) are **WJQ `.doc` template artifacts**. WJQ `.doc` title extraction falls back to "Untitled Position" (~94% of WJQ `.doc`), so those files share a title AND the 14-section template scaffolding → they over-cluster on template, not role. The cohesion cap FLAGS them (oversize), not merges — so the report is honest about it. **A trustworthy WJQ cluster report needs two follow-ups: (1) WJQ boilerplate redaction** (redact the 14-section scaffolding before embedding/Tier-3, then re-embed + re-Tier-3 + re-cluster) and **(2) better WJQ `.doc` title extraction** (antiword loses the title label). The report is trustworthy for the JDFN population today.
- ~~**Rulebook work the baseline made urgent**~~ **ALL THREE DONE IN 2.6** (banned-phrase scoping,
  `HOW-WHY` unevaluable, 4th era band). Scores are now trustworthy. What is left is HR's, not ours.
- **Extension-trust is silently losing recoverable JDs** (from the 2.5 skip ledger,
  `docs/baseline/errors.jsonl`, 43 files): **9 `.doc`-named files are actually RTF** — and we have
  an RTF backend — plus an 89 MB `.rtf` over the extractor's 50 MiB cap, and 22 `.docx`
  python-docx cannot open. Fix = content-sniff the magic bytes instead of trusting the extension.
  Deliberately NOT done in 2.5: it is a real change to the extractor with its own blast radius,
  and 10 files of 14,565 move no number in the baseline.
- **Move `jd_core/parser/store.py`'s import of `jd_bank.db.models`** — the one pinned
  `jd_core → jd_bank` edge (see Gotchas). Harmless today (a leaf, no cycle), but it is the
  exception that the import ratchet has to carry.
- **Deferred EXTRACT modules** (plan already assigns them): `export.py` → 5.4 (needs `reportlab`, a
  new dep, plus SFU styling hris never implemented, plus the open territorial-ack flag); prompts
  (`sfu_jd_extract` / `jd_harmonize` / `jd_quality`) → 4.2 (no LLM client or prompt loader exists;
  ~~the golden test needs host Ollama, which the self-contained `gates` container cannot reach~~ —
  **that reason was FALSE, see the Ollama gotcha below; the real reason is that CI cannot reach the
  inference host, so a live golden test must be opt-in and local-only**);
  `jd_import_service` → 5 (composer upload; would force PyMuPDF back after 1.3 dropped the PDF path).

---


## Backlog (real, recorded — fold into cleanup PRs as they come up)

- **`max_chars` is too high for WJQ text.** 11 documents exceed the 8192-token model limit after
  truncation to 10,000 chars (`max_chars` was measured on JDFN-only serialized text, which maxes at 8,987;
  WJQ Hay-factor prose is denser). They get sections but no document vector (runner isolates+skips, no
  crash). Fix: lower `max_chars`, or truncate by tokens not chars. Register HR-124-adjacent.
- **WJQ template boilerplate is not redacted for near-dup/clustering — NOW CONFIRMED by the cluster report.** `redact_boilerplate` only knows
  JDFN's About-SFU/territorial/EDI passages. WJQ's 14-section scaffolding (near-identical across ~4,300
  files) inflates their mutual similarity — the cluster report exposed this: the two largest flagged clusters ("Untitled Position" n=132 and n=108) are WJQ `.doc` artifacts that over-cluster on shared template+seniority, not role. Redaction (before embedding/Tier-3, then re-embed + re-Tier-3 + re-cluster) is now a **Phase-4 priority** — block WJQ harmonization until this lands, so the canonical report reflects true role equivalence.
- **Better WJQ `.doc` title extraction — now needed before WJQ harmonization.** Antiword loses the document title label (WJQ form: "WEIGHTED JOB QUESTIONNAIRE — [TITLE]"; antiword reads only body text). Current fallback: "Untitled Position" (~94% of WJQ `.doc` files) → 132/108-JD clusters flagged in Phase 3.5 report. Extract before parsing (patch the extractor, or pre-scan the `.doc` XML).
- **Tier-3 candidate-gen perf (3.4b follow-up).** O(bucket²) scan in the 8,215-doc `unmapped` title bucket completes in ~1hr whole-archive, but it is not scaling. Replace with Neo4j vector-index top-k (compute seniority delta over candidates only, not all pairs in the bucket). No blast radius (candidate gen is deterministic from config+vectors).
- **Wire `run_tier1` to persist EXACT edges.** Tier-1 currently **has no DB caller** — SHA-256 exact dedup runs but never writes to `dedup_edges`. Clustering must add EXACT connectivity or identical dups split. Cheap wiring task, no new logic.
- **The parse idempotency key is blind to the extractor.** `parse_and_store` keys on `(source_document_id,
  parser_version)`; an extractor-only change (like #30) changes the text but not the key, so it does NOT
  force a re-parse — the docx fix's re-parse only happened because the WJQ change bumped `PARSER_VERSION`.
  Fold an extractor version into the key, or content-key the parse.
- **The baseline stamp doesn't capture the extractor.** #31 regenerated the baseline with a byte-identical
  `parser_version`/`rules_version` but different numbers (extraction changed). Fold an extractor version
  into the baseline stamp.
- **`sections_skipped_short` is a misnomer and the committed artifact says something false** (found by
  the first real embed run, `docs/embeddings/summary.json`). It reports **20,644** — but only **7**
  sections in the whole archive are actually *short* (1 summary + 6 duty-blocks, below
  `min_section_chars: 40`). The other ~20,637 are **ABSENT**, not short: the counter is
  `3 × 14,522 candidate slots − 22,922 embedded`, so it silently folds "this JD has no qualifications
  section at all" into "this section was too short to embed". Anyone reading the artifact would
  conclude the guard-rail is doing 3,000× more work than it is. Split it into `sections_absent` vs
  `sections_skipped_short` — the guard-rail's real footprint (7) is one of the numbers that justifies
  its default, and it is currently invisible.
- **The embed run's first pre-fetch logs six Neo4j `property key does not exist` warnings** against an
  empty index (`text_sha256`, `model`, `embed_stamp`). Harmless — it is the skip-first query running
  before any node exists — but it is noise at the top of every fresh run's log and will train people
  to ignore warnings. Quiet it (or state in the runner why it is expected on a cold index).
- **CI enforces a branch-name gate: `^(agent|feat|fix|chore)/<slug>$`.** A bare topic branch like
  `phase-4.1-merge-engine` **fails** the `Gate: branch-name` job, and every other gate `skipping`s
  behind it (so it reads like a total CI stall, not a naming nit). GitHub cannot re-point a PR's head
  branch, so the fix is: `git branch -m feat/<slug>`, push, close the old PR + delete its branch,
  reopen. **Name the branch `feat/…` from the start** (4.1 hit this — cost a PR reopen, #45 → #46).
- **Stacked PR merge gotcha — record this in lore.** Merging #19 with `--delete-branch` deleted its
  base branch, which **auto-closed PR #20** (2.6). GitHub will not reopen a PR whose head was rebased
  after closing, so 2.6 was re-opened as a **fresh PR #22** linked back to #20 for review history.
  **In a stacked PR chain, do NOT `--delete-branch` on merge until the whole stack has landed.**
- **`_extract_docx` joins paragraphs with a single `\n`**, so HR-108's paragraph boundary only
  engages on **47% of `.docx`** (373/799 — those with a literal blank line, or a whitespace-only
  paragraph, which survives `if p.text` as `"\n \n"`). The other ~53% still join adjacent paragraphs
  for matching, so a term could match across a `.docx` paragraph break. `.doc` is covered in full
  (498/498), and that is where the wrapping problem actually lives, so this is not urgent. Fix =
  `"\n\n".join(...)` — but it **rewrites the stored raw text the segmenter reads**, so it is its own
  deliberate change, not a drive-by.
- ~~**`SFU-QUAL-BANNED-PHRASE` scans the whole document**~~ **DONE (2.6, HR-120)** — scoped to
  Qualifications via the `banned_phrase_scope` knob. Blocks 104 → 0; **+59 approvals**. It had been
  filed as a backlog tidy-up; the baseline showed it was the **#2 operative gate in the approval
  bar**, so it landed as a register entry with measured before/after, not a cleanup PR. **That
  promotion — tidy-up → bar change — is the lesson: measure before you classify a bug as minor.**
- **No "current version of this path" concept** (new, 3.1). `source_documents` is now one row per
  **file**, keyed `(storage_ref, sha256)` — so if the bytes at a path ever change, the path gets a
  **second** row and nothing marks which is current. `dedup/tier1.py :: _document_refs` selects all
  rows, so that path would be **double-counted** in `total_documents`. Harmless today: the archive
  is READ-ONLY, so no path's bytes change. The pair-key is still right (keying on `storage_ref`
  alone would force an in-place UPDATE, silently re-pointing the `parsed_jds` already hanging off
  that row at bytes that never produced them — a provenance lie). **Fix when ingestion becomes
  incremental, not before.**
- ~~**`comparison.cluster_algo` can lie**~~ **DONE (3.1)** — now a closed `Literal` **and**
  `build_clusters` genuinely dispatches on it, so the stamp selects the algorithm rather than merely
  naming it. Verified by mutation: `louvain` in YAML → the rulebook refuses to load; forced past the
  loader → `build_clusters` refuses to run. The landmine is disarmed before Phase 3 writes a cluster
  row, exactly as this backlog line demanded.
- **Boundary tests for the comparison cutoffs.** `clone_threshold` (0.92), `material_years_delta`
  (2) and individual `title_stopwords` are pinned *by value* but are behaviourally invisible — the
  ported hris tests probe far from the cutoff (clone at 0.95; a delta of 3 against a bar of 2). The
  "move the number → something goes red" standard holds via the by-value pins, but a boundary test
  (`clone_verdict(0.92)` is a clone, `clone_verdict(0.9199)` is not) would make *behaviour* the
  oracle rather than the assertion.
- **HR-082** should name the divergence it papers over: the rulebook (l.238) *does* enumerate
  education levels — "Diploma, Bachelor's, Master's, PhD" — a 4-item list that differs from our
  5-rung ladder (we add `high_school`; we say `associate` where SFU says `Diploma`). HR-083 already
  owns the diploma/associate mismatch; HR-082 should mention SFU's list is shorter and differently
  named, since an HR reviewer ratifying the ladder will want to know.

- **`bank/render.py` → `parse_jd` round trip is lossy** (documented in the module docstring and
  pinned by `test_render_to_parse_is_documented_lossy_exactly_where_it_says_it_is`). Every section
  the renderer *writes* now survives re-parse, but: (a) identification is a subtitle line, not the
  `Department:` / `Grade:` labelled fields the segmenter reads → `department`, `grade`,
  `position_number` are lost (`employee_group` survives, token-scanned); (b) About-SFU + the
  territorial-ack/employment-equity footer are presence *booleans* on the model, so there is no
  text to render → a rendered canonical trips `SFU-COMP-ABOUT` and the footer gates; (c) the
  segmenter does not strip the `Supervisory: ` and `[skill] advanced ` labels, so they come back
  *inside* the value and a re-render **compounds** them. **Do not build a render→parse→render loop
  (composer "start from canonical") until this is closed.** Fix = template-faithful identification
  + footer emission, a label-strip in `segmenter._structure_relationships` / `_structure_quals`,
  and a round-trip fixture.
- **Landmine for the 2.4b `hay_signals` port:** hris `pipeline/bank/hay_signals.py:229` constructs
  `HaySignals(..., grade_mapped=False)`. The ported `HaySignals` is `extra="forbid"` and that field
  is **deliberately gone** (SFU publishes no Hay point charts; a graded signal is unrepresentable
  by construction). The port MUST drop the kwarg. It must **not** "fix" the `ValidationError` by
  re-adding the field — that silently undoes the Hay source-gate.
- Remove 4 **dead config values** nothing reads: `rule_catalog.SFU-LANG-CODED.default_severity`
  and the three `SFU-AUTH-TITLE-*.default_severity` (validators always override them).
- `max_listed` exists **twice** as independent knobs holding the same value 5
  (`thresholds.max_listed`, `gates.max_listed`) — nothing keeps them in step. (2.4b hit the
  same shape between `hay_signals.advanced_skill_modifiers` and
  `qualifications.skill_modifiers` and **closed it with a `Rules`-level cross-file validator**
  — use that as the pattern when closing `max_listed`.)
- **Decision-surface enumerator, residual hole (narrow).** `_OFF_SURFACE` (in
  `tests/unit/test_decision_register.py`) now forces every field of every rule file to be
  either on the surface or exempted with a reason, and `_FLAT_SURFACE_FILES` puts flat files on
  it automatically. But `test_the_decision_surface_walks_every_rule_file` only requires **≥1
  path per file** — so a *new* partially-hand-enumerated rule file listed in neither
  `_FLAT_SURFACE_FILES` nor `_OFF_SURFACE` could still hide a field. All current files are
  covered; shape any new rule file **flat** so it qualifies for `_FLAT_SURFACE_FILES`.
- **`make register-check` ≠ surface coverage.** `register-check` only diffs the committed
  register Markdown against `decision_register.yaml`. The surface/coverage guarantees are
  enforced by **`make gates`** (the `_OFF_SURFACE` guard test + `check_register` via
  `get_rules`). Run both; never read a green `register-check` as "everything is registered".
- ~~**`rules_version` tracks nothing.**~~ **DONE (PR #16)** — now derived from rule content
  (`jd_rules_sfu_v4+<digest>`), so a stamped `ValidationReport` identifies the rules that produced
  it. ~~**HR-058**~~ **DONE (PR #16)** too. Both were prerequisites for the 2.5 baseline.
- **2.4a citation error (fold into a chore branch).** `models/bank.py` (the `TitleFamily`
  warning) and HR-059 both say the rulebook's lone "VP" is a Part **3.5** restricted title. It
  is actually Part **3.6**, in the working-titles "should not use" list. The *conclusion* (SFU
  publishes no title ladder) is unaffected — only the citation is wrong.
- `docs/rulebook/rulebook/` is a tracked **duplicate** of `docs/rulebook/` — scrub on a chore branch.
- Root `.claude/` is NOT set up (harness subagent defs + no-commit-to-main / ruff hooks). An
  auto-generated `.claude/settings.json` (a permission allowlist Claude Code wrote itself) sits
  untracked — it is NOT the harness config; keep it out of commits. Standing up the real root
  `.claude/` is its own deliberate PR.
- `.gitattributes`: consider `linguist-generated` for the rendered register Markdown.
- Carried from Phase 1: tighten the legacy-`.doc` E2E confidence upper bound; guard bare
  single-word heading patterns in `parser/headings.py`; docx zip-ratio (decompression-bomb) guard
  in `ingest/extract.py`; wire the arq `run_ingest` worker task.

---

## Authoritative references

- **`docs/status/2026-07-15-shipped.md` — the current one-pager.** 3.2 embeddings, 3.3 near-dup, and
  both extraction defects, for the team and as the basis of what we tell HR. **Start here if catching
  up.** (`2026-07-13-shipped.md` covers the earlier 2.5/2.6/3.1.)
- `docs/plan.md` — full build plan, architecture, phase breakdown (current).
- **`docs/baseline/README.md` — THE ARCHIVE BASELINE (2.5).** The measured read of all 14,565 JDs.
  Read before making any claim about the archive. Regenerate with `make baseline`.
- **`docs/decisions/HR-DECISION-MATRIX.md` — what SFU HR must decide** (the single consolidated HR
  review + decision matrix — system explainer, evidence, and the eight settings that matter — written
  for a non-engineer, each with measured impact + our recommendation; folds in the former
  HR-REVIEW-PACKET / HR-REVIEW-REQUEST, and is deliberately free of internal codenames).
- **`docs/decisions/POST-REVIEW-CHANGE-PLAN.md` — what we change once they rule** (per decision:
  config key, blast radius, what test must go red, sequencing).
- `docs/subagent-model-strategy.md` — model tiering rules for subagent dispatch.
- `docs/decisions/HR-DECISION-REGISTER.md` — generated register; `make register` / `make register-check`.
- `docs/adr/` — ADR-002 (PG/Neo4j), 003 (Ollama), 004 (repo placement), 005 (extract-vs-rewrite,
  Accepted), 006 (Docker-only).
- `docs/audit/hris-reuse-map.md` (16 EXTRACT / 8 REWRITE / 4 DISCARD) + `archive-census.md`.
- `docs/rulebook/sfu-jd-standards.txt` — the rulebook (Part 2 = new template, Part 8 = old).
- `DEVELOPER_GUIDE_1.md` — onboarding + Docker-only workflow. `CLAUDE.md` — project invariants.
- Persistent memories auto-load each session (storage-architecture, docker-only-execution,
  harness-upstream-subagents, jd-incumbent-names-not-pii, subagent-workflow, hr-decision-register).

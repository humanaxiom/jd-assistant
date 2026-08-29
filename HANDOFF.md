# JD Bank — Session Handoff

Read this first every session. **Forward-looking only** — the build record lives in
[`docs/archive/`](docs/archive/).

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

## 🔴 THE ONE THING TO UNDERSTAND

**The system works. It has no output. The constraint was never engineering.**

Thousands of drafts pass every gate today and a handful have ever been shown to a reviewer.
They are blocked on nothing we build — see [`docs/FINDINGS.md`](docs/FINDINGS.md) for the
current figures and `/jd-bank/ui/funnel` for the live ones.

**CUPE is near-zero approvable for reasons content cannot fix** — two *unratified HR policy
decisions* block almost all of it. A week of content fixes and 19.4 GPU-hours moved the CUPE
approvable count *down*.

> **Before any engineering task, ask: does this change the number of PUBLISHED JDs?**
> If not, it is not next — however real the defect.

**Done is measured in published JDs.** Not carry-through, not scores, not test counts.

---

## ▶ CURRENT STATE — 2026-08-28

**Track A (the demo) is COMPLETE.** A1–A5 built and merged; `make gates` green; CI green.

Two live surfaces, both reading the database at request time:

| | |
|---|---|
| `/jd-bank/ui/collection/it` | the IT collection · `?queue=1` for the review queue |
| `/jd-bank/ui/funnel` | archive → published, scope-parameterised, **with the full gap accounting** |

`PARSER_VERSION` `jd_segmenter_v5` · `rules_version` `jd_rules_sfu_v4+76baba29cfeb`
(unmoved — the A2/A4/A5 rule files are unhashed by design).

### The three things that actually need a person

1. **B3 / B4 — the HR asks.** The only work that moves the published count. Pure lead time.
2. **A6 / A7 — the ITS director sessions.** Work the review queue and vet the department
   alias list; their rulings land in HR-217/218.
3. **D1 — decide what happens to a one-of-a-kind job.** The pipeline builds a role from a
   GROUP of near-duplicates, so a unique job produces nothing. **The only open item that
   raises the ceiling on what can ever be published.** [`docs/FINDINGS.md`](docs/FINDINGS.md) §2a.

Everything else, including the rest of the archive gap, is in [`docs/plan.md`](docs/plan.md).

---
## ▶ IF YOU ARE STARTING COLD

```bash
git fetch && git log --oneline origin/main -1
gh pr list                                        # never trust a table for this
docker ps --format '{{.Names}}' | grep jd-bank    # ⚠ the stack does NOT self-restart
docker compose up -d                              # ...if that came up empty
docker ps --filter "name=canonical"               # MUST be empty; do not start a run
```

⚠ **The box runs other Docker projects.** Random `postgres:16-alpine` /
`neo4j:5-community` containers are `recruiter-assistant`'s testcontainers, not ours.

**Then open `/jd-bank/ui/funnel`.** It is the fastest way to see the state of the archive,
and it is the only place those numbers are authoritative.

**Then run `make smoke`.** The end-to-end check against the live Bank — parsing, dedup,
categorize, filterable — fails if a single document is unaccounted for or unfindable.
Trust it over any document, including this one.

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
- **A rising score is a question too.** Three separate defects this project made scores go
  *up*: invented sections, compressed duty lists, dropped point-factor content.
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
- **A watcher must match the signal, not a substring of the output.** A completion check
  looking for "passed" fired on ruff's *"All checks passed!"* and reported a test result
  that had not happened yet. Same shape as believing a zero.
- **In a REVIEW queue, over-inclusion is cheap and under-inclusion is not.** A wrong
  candidate costs one "no" in the room; a missing one costs the reviewer's confidence in
  the whole list. Bias a worklist wide — and only a worklist, never a membership rule.
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

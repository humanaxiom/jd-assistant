# Harness lessons II — a harness can be excellent and still ship nothing

**Audience:** whoever maintains the seed harness at
`adamsalah13/pmo-harness-template` (Claude Code + PMO control plane:
`register_run` / `submit_gate` / `submit_work_item` / `release_run`).

**Companion to** [`HARNESS_LESSONS.md`](HARNESS_LESSONS.md), which covers *agents failing to
run the gate*. This document covers the opposite and more expensive failure: **agents
running every gate perfectly, for six weeks, on work that did not move the deliverable.**

Written 2026-08-24 from a production project (`jd-bank`) built on a sibling harness. Every
number below is a query against that project's live database, not an impression.

---

## The thesis, stated once

> **The template gates whether a CHANGE is correct. Nothing in it asks whether the
> accumulated changes are producing the OUTCOME.** A project can satisfy all nine
> Definition-of-Done criteria on 223 consecutive commits and deliver nothing — and every
> agent, every gate and every judge verdict along the way will have been right.

This is not a hypothetical. It is what happened.

---

## 1. The evidence

Six weeks on a harness with merge-blocking gates, TDD enforcement, a judge, and a
registered-decision system that is genuinely excellent:

| built | |
|---|---:|
| commits | 223 |
| tests | 2,890 passing, 93% coverage |
| documents ingested + parsed | 14,565 |
| canonical drafts produced | 2,489 |
| **drafts passing every quality gate** | **1,292** |

| delivered | |
|---|---:|
| **artifacts actually published** | **5** |
| **human review actions, ever** | **8** |
| policy decisions registered / ratified | 214 / **0** |

**1,292 finished artifacts sat ready and nobody had been asked to look at one.** The
critical path had run through an external human decision since week two, and nobody had
booked the meeting — so work flowed to whatever could be done unilaterally. There is
always more fidelity to chase: at 14,522 documents there is always another defect.

**Every individual defect found was real.** Fabricated content, truncated fields, a
parser blind to 16% of one cohort. Each fix was correct, tested, measured and reviewed.
**The loop was still a loop**, because none of it had an exit condition tied to output.

---

## 2. The gap in the template, precisely

### `CLAUDE.md` — Prime Directives
All five are correctness directives: TDD, delegation by cost, judge-gates-merge,
deterministic core, governance profile. **All good. None asks what the work is for.**

### `docs/DOD.md` — nine criteria
Plan exists · tests first · lint/type pass · no new egress · provenance · migrations
reversible · judge APPROVE · CHANGELOG · PMO gate recorded.

**Every one is per-change.** There is no criterion a *project* can fail. DoD item 9 gets
closest — *"a ticket is not Done because the code is green if a gate it was supposed to
satisfy was never recorded"* — but it still measures **recording**, not **outcome**.

### `/retro`
Reviews CI health, flaky tests, coverage trend, recurring judge findings — **process
health**. A retro that only examines process makes the machine better at running. It
never asks whether the machine is producing anything.

---

## 3. Fix: add a delivery gate the project can fail

### 3a. A sixth Prime Directive

```markdown
6. **Every task names the outcome metric it moves.** This project's deliverable is
   `<the unit that counts — published artifacts, migrated accounts, closed tickets>`,
   tracked in `docs/HANDOFF.md`. A task that cannot state how it changes that number is
   not necessarily wrong, but it is **not next** — however real the defect. Correctness
   work that never reaches the deliverable is indistinguishable from wheel-spinning at
   the end of a quarter, and feels like progress the whole way through.
```

### 3b. A Part B in `docs/DOD.md`

Split the DoD in two. Part A is the existing nine (Done for a *change*). Add:

```markdown
## Part B — Done for the PROJECT (checked at every sprint boundary)

B1. `docs/HANDOFF.md` states the deliverable metric, its value today, and its value at
    the previous sprint boundary.
B2. **If that number did not move, the retro's first section explains why**, and the
    next sprint's top item is whatever unblocks it — not the next-most-interesting
    defect.
B3. If the blocker is outside the team (a decision, an approval, an access grant), it is
    named with a person and a date. **"Waiting on X" with no date is not a status, it is
    a stall**, and it is the specific failure this section exists to catch.
```

**B3 is the one that would have saved six weeks.** The blocker was known, written in the
plan on day one of week two — *"the human pilot is now the next milestone"* — and it had
no owner and no date, so it stayed a sentence in a document while the team built.

### 3c. `/retro` opens with delivery, not CI health

```diff
 Analyze the completed sprint $ARGUMENTS:
-1. Delegate to `test-runner` to summarize CI health over the sprint
+0. FIRST, from `docs/HANDOFF.md`: the deliverable metric now vs at the last sprint
+   boundary. If it did not move, that is the retro's headline and its first process
+   change must address it. Do not proceed to CI health until this is written.
+1. Delegate to `test-runner` to summarize CI health over the sprint
```

Order matters. A retro that opens with coverage trend has already framed the sprint as a
question about code quality.

### 3d. Use the control plane you already have

`submit_work_item` is the natural place for this. A work item that carries an
`outcome_metric` and its delta makes delivery-blindness visible **at the PMO level**,
across projects, without anyone having to notice it locally. The plumbing exists; only
the field is missing.

---

## 4. "Keep it live" without a pruning rule produces archaeology

The template says of `docs/HANDOFF.md`:

> *Update it when you finish a ticket or make a decision that would leave it materially
> stale — it should stay current enough that a fresh session can resume cold.*

**Correct, and incomplete.** "Update when you finish a ticket" is an *append* instruction.
Ours reached **4,410 lines** — ten dated session blocks, each written to be read, none
ever removed. The build plan reached 1,494 lines of ~95%-complete phase list. A fresh
session could technically resume cold; it just had to excavate.

**Add a shape rule:**

```markdown
`docs/HANDOFF.md` is FORWARD-LOOKING and capped at ~200 lines. It answers: where are we,
what is next, what must not be done, how do we work here. It is NOT a session log.

When a section becomes history, move it verbatim to `docs/archive/` and link it. A
handoff that has to be excavated is not current — and "I appended my session" is how a
living document becomes an archive nobody reads.
```

Ours went 5,904 lines → 293 across both documents. Nothing was deleted; it was
**relocated**, and the result is the first version in a month that a new session can act
on directly.

---

## 5. Branch-per-ticket is right for code and wasteful for docs

The template's convention — branch per ticket, PR, judge, merge — is correct for
anything that can break. Applied uniformly it also routes **every typo fix through the
full gate suite**.

Measured on our repo: **53 of 60 CI runs in one four-day stretch** were largely
documentation churn. Two contributing causes, one of which is a template-level trap:

1. **Ours had drifted to `on: push` with no branch filter** — so every PR ran the suite
   *twice*, once for the branch push and once for the PR, on the same commit.
   **The template already gets this right** (`push: branches: [main]`). Worth an explicit
   comment in the template so nobody "fixes" it back.
2. **No `paths-ignore`.** Documentation CI does not validate should not run it.

**Recommended template additions:**

```yaml
on:
  pull_request:
    paths-ignore: &doc_paths
      - '*.md'
      - 'docs/**'          # ⚠ carve out any docs a gate ACTUALLY validates
  push:
    branches: [main]
    paths-ignore: *doc_paths
```

⚠ **Do not use `!` negation in `paths-ignore`.** GitHub's semantics there are
order-dependent, and getting them subtly wrong means a gate silently stops running.
Protect a validated docs path by **omitting it from the ignore list**, not by negating it.
(We validate a generated decision register from `docs/decisions/`, so that directory is
absent from our list rather than negated.)

And a path-aware policy in `CLAUDE.md`:

```markdown
## Change workflow — what needs a PR and what does not
Straight to `main`: docs that no gate validates, generated report artifacts, typo/format
fixes. Still a PR: anything under `<source dir>/`; the source-of-truth documents
(`HANDOFF.md`, the plan); anything a gate validates; anything changing how the project is
built, gated or governed (`CLAUDE.md`, `.github/**`, build files).

Not relaxed: gates green before any commit touching source; a config knob and its
registry entry ship in the SAME PR — never split to dodge a branch.
```

---

## 6. What worked so well it should be templated

**A registry that the build refuses to run without.** Our project requires every
non-trivial policy default to be (a) config, not code, and (b) registered with rationale
and provenance. The rulebook **fails to load** if a knob exists that no registry entry
describes.

It caught me *during this session*: adding a new guard, the test suite refused to start —

```
RulesError: rewrite.sections_never_emptied is on the decision surface but is neither
a register entry nor an explicit `trivial:` exemption
```

I could not have shipped it unregistered even by accident. **214 decisions are documented
because the build would not start otherwise** — not because anyone was diligent.

**Template it as a first-class pattern.** The generalisation: *any category of thing your
project must not accumulate silently — policy defaults, feature flags, external
endpoints, PII fields — should have a registry the build validates, not a convention the
reviewer checks.* Conventions rot; build failures do not.

Pair it with a CI job that re-renders the human-readable registry and fails on drift, so
the document and the code cannot disagree.

---

## 7. Verification lessons that generalise

Reinforcing and extending [`HARNESS_LESSONS.md`](HARNESS_LESSONS.md) §3–5:

- **A green suite proves nothing about a guard you have not tried to break.** Three
  separate "correct fix pinned by nothing" defects. If a test's docstring explains *why* a
  property holds, break that *why* and watch it go red. Worth stating in the `test-writer`
  and `judge` agent definitions, not just in docs.
- **A wrong query returns 0 exactly as convincingly as a guard that never fired.** I
  queried a JSON path that did not exist, got `0`, and reported "the guard didn't need to
  fire" — plausible, reassuring, wrong. Dumping one raw record showed it firing. **Before
  believing a zero, prove the query can produce a non-zero.**
- **A fixture that silently produces empty values tests nothing.** A test helper invented
  a field shape the code did not read; every assertion passed against absent data.
- **One sample cannot distinguish "working" from "stalled".** Take three. A single
  38-second reading was read as progress when the process was parked.
- **A flat metric is a question, not a verdict.** Compare against a control before acting.
  Any partially-complete batch job gives you one free: **the not-yet-processed
  population**. That comparison (100% vs 74% carry-through) is what turned a suspicion
  into a defect worth stopping a 20-hour run for.
- **A rising score deserves the same suspicion as a falling one.** Three defects in this
  project made quality scores go *up*: invented sections, compressed lists, dropped
  content. Anything that makes the number better without making the artifact better is a
  metric you cannot trust.

---

## 8. Two operational patterns worth shipping in the template

**Measure over the full corpus before designing anything that scores or thresholds.**
Twice, an obvious design was undeliverable and only a full-population spike showed it.
A design validated on five examples is a claim about five examples.

**Long-running jobs need a "is it working or hung?" runbook, written before the job runs.**
Ours sat at 0.00% CPU with no output for an hour — indistinguishable from a hang, and on
an earlier run it *had* been one (block-buffered stdout). The distinguishing signal was
neither CPU nor logs but **database activity**: a transaction whose age resets is a work
cycle; one that only grows is a stall. Template a short section: *what this job's healthy
silence looks like, and the one query that tells the difference.*

---

## 9. Apply-to-template checklist

- [ ] **Prime Directive 6** — every task names the outcome metric it moves
- [ ] **`docs/DOD.md` Part B** — Done for the *project*; B3 (external blockers need a
      person and a date) is the one that matters most
- [ ] **`/retro` step 0** — delivery metric before CI health
- [ ] **`submit_work_item`** — carry an `outcome_metric` + delta to the control plane
- [ ] **Handoff shape rule** — forward-looking, ~200 lines, `docs/archive/` convention
- [ ] **`paths-ignore` in CI** — with the explicit no-`!`-negation warning
- [ ] **Path-aware PR policy** in `CLAUDE.md`
- [ ] **Registry-enforced-by-build** as a documented first-class pattern
- [ ] **Verification rules** into `test-writer` / `judge` agent definitions, not just docs
- [ ] **Long-running-job health runbook** section in the template

---

## 10. The sentence to carry

**A harness that enforces correctness and ignores delivery will produce high-quality
wheel-spinning, and everyone involved will be doing excellent work the entire time.**

The gates were never wrong. They were answering a question nobody had checked was the
right one.

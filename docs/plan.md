# JD Bank — Remaining Work

**Forward-looking only.** Everything built between 2026-07-10 and 2026-08-24 — Phases 0–9
and A–G — is in
[`docs/archive/BUILD-RECORD-phases-0-9-A-G.md`](archive/BUILD-RECORD-phases-0-9-A-G.md).
This file lists what is **actually left**, in the order it should be done.

Written 2026-08-24 from the evidence in [`STATUS-2026-08-24.md`](STATUS-2026-08-24.md).

---

## The state, in three numbers

**2,489 canonical drafts · 1,292 approvable today · 5 ever published.**

The system is built. It has not been used. **Every item in Part 1 below is worth more
than every item in Part 2**, and three of the four are not engineering.

---

# PART 1 — THE CRITICAL PATH

## 1. TLS at the edge 🔴 *(ours, and the only one that is)*

`sfuai.ca:7000` is a Telus NAT forward to `192.168.1.80:25800` — **plain HTTP on the
public internet, carrying CAS sign-in cookies.**

- **Why now:** the pilot puts a real SFU HR reviewer on that host. Today it is a demo
  forward; the moment a reviewer signs in it is a credential exposure.
- **Done when:** the pilot host serves HTTPS with a valid certificate, HTTP redirects,
  and the CAS return URL matches.
- **Blocks:** item 2. Do not schedule the pilot before this lands.

## 2. The 4.5 human pilot 🔴 *(needs an HR reviewer)*

Named as "the next milestone" on **2026-07-21**. It has not happened.

- **Scope:** ~20 of the 1,292 approvable JDFN drafts, reviewed for real — approve, reject
  or edit, through the review queue, by someone who writes SFU job descriptions.
- **Done when:** **20 PUBLISHED JDs** exist, and there is a written list of what the
  reviewer actually objected to.
- **Why it outranks everything:** that list is the only evidence we cannot generate
  ourselves. Every measurement so far has been us marking our own homework.
- **Prerequisite:** item 1. Nothing else.

## 3. Ratify the two gates that hold CUPE shut 🔴 *(needs HR)*

| gate | CUPE drafts blocked |
|---|---:|
| `SFU-APPROVE-QUAL-EQUIVALENT` | **620 of 649 (95.5%)** |
| `SFU-APPROVE-KSA-ORDER` | **564 of 649 (86.9%)** |

Both are registered, unratified policy decisions — **not defects**. The 1990s Weighted
Job Questionnaire had no reason to carry an "equivalent combination" clause.

- **Done when:** both carry `decided_by` / `decided_on` / `decision_note` in
  `decision_register.yaml`, or `applies_to` is narrowed by an HR ruling.
- **Payoff:** potentially 3 → several hundred approvable CUPE drafts, at **zero GPU cost**
  — more than every engineering change made in August, combined.

## 4. The HR ratification session *(needs a calendar invitation)*

214 decisions, **0 ratified**.
[`decisions/HR-DECISION-MATRIX.md`](decisions/HR-DECISION-MATRIX.md) has been HR-ready
since 2026-08-21 and covers the eight that matter.

- **Done when:** the eight matrix decisions are ruled on and recorded in the register
  (never a side file — a `ratified` entry without `decided_by`/`decided_on`/
  `decision_note` fails the rulebook load).
- **Note:** the matrix does not need another revision. It needs a meeting.

---

# PART 2 — DEFERRED ENGINEERING

**Real, registered, and none of it changes the published-JD count.** Do not start any of
this while Part 1 is open. Ordered by value once Part 1 moves.

## 2.1 Duty-frequency matching *(design needed, not a patch)*

27.7% retention on rewritten drafts vs **92.3% merge-only**. The naive fix is *measured*
unsafe: argmax==positional agrees on only 8–26% of duties, and 62.4% share Jaccard < 0.2
with any merge duty — so both obvious rules attach **wrong** frequencies to a field that
feeds the CUPE point-factor evaluation. **A wrong frequency is worse than a missing one.**
Needs a real matching design with evidence. Serves a cohort currently 99.5% blocked by
Part 1 §3.

## 2.2 JDFN cohort re-measure

`problem_solving` reads **228.2% FABRICATED** (1,084 / 475) — an S-5-class defect on the
JDFN side, untouched by the CUPE work. A JDFN producer pass would also carry HR-213 and
HR-214 to that cohort. ⚠ ~44 GPU-hours for the full archive; scope it.

## 2.3 HR-214's compression question *(HR's call, do not pre-empt)*

HR-214 restores a section the rewrite returned **empty**. It deliberately leaves alone one
returned **thinner** — a merge producing `internal=20` came back `internal=3`. Whether
that is acceptable editing or content loss is registered `open`. **Do not close it with a
threshold.**

## 2.4 Phase F — form scoping

Search is JDFN-only in both directions; dashboards report a pre-CUPE world; D3's per-form
draft evaluation renders nowhere. Backlog:
[`docs/tasks/phase-f-form-scoping-backlog.md`](tasks/phase-f-form-scoping-backlog.md).

## 2.5 Phase G — remaining rulebook items

- `SFU-GATE-SENIOR-TITLE` is unfalsifiable on the WJQ (needs `relationships.supervisory`,
  which `parser/wjq.py` never populates by design).
- `thresholds.wjq.duties_max: 12` is structurally dead.
- The compose stack has **no `restart:` policy** while every other project on the box does
  — it does not survive a Docker restart. *(Small, real, and it has cost a run before.)*

## 2.6 Phase 7 — role/duty overlap graph

Neo4j domain overlap graph. Explicitly **not** MVP. Deferred since the original plan.

---

# What is finished and must not be reopened

So no session re-litigates settled work:

- **Ingest / parse / extract** — 14,522 of 14,565, the 43 individually accounted for.
- **Dedup + clustering** — Tier 1/2/3, 2,456 clusters.
- **Two-form split** — JDFN and WJQ, each scored on its own bar (CUPE Phases A–E).
- **Harmonization** — 4.1 deterministic merge + 4.2a LLM rewrite, anti-fabrication guarded.
- **The CUPE content chain** — as of 2026-08-23 every WJQ carry-through reads **100%** and
  fabricated duties are **0**. `PARSER_VERSION` is `jd_segmenter_v5`, re-parsed.
- **Security / SSO / deployment / navigability** — Phase 9.
- **JD Builder** (Phase 5) · **Role Library** (Phase 8.1) · **`make bank-audit`** (the
  carry-through report).

---

## How "done" is measured

> **Published JDs in the Bank. Today: 5. Next milestone: 20. Then 100.**

Not carry-through percentages. Not mean scores. Not test counts. Those measure whether the
machine works — which it does. They do not measure whether SFU has job descriptions.

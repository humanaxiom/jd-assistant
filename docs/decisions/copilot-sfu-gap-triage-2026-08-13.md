# Triage — the Copilot "SFU site coverage vs. repo implementation" gap analysis

**Date:** 2026-08-13 · **Source:** `GH-Copilot/sfu-site-gap-analysis.md` (+ its three companion
files: `sfu-gap-backlog-issues.md`, `sfu-gap-status-matrix.md`, `sfu-gap-roadmap.md`).
**Outcome:** two of nine issues rejected as factually wrong, four already tracked, two recorded
as **explicitly OUT** with reasons, one carries genuine new work. Two small residues adopted.

This file exists so the same nine issues are not re-raised next quarter as if new. Same pattern
as [`coded-language-soft-lexicon.md`](coded-language-soft-lexicon.md): **check the claim against
the artifact before planning around it.**

---

## The one thing the analysis got right, and it is the framing

> *"The repo is not missing the core JD Bank pipeline. It is missing the full SFU JD lifecycle."*

That is correct and worth keeping. JD Bank is a **JDFN authoring + archive-harmonization** system,
not an HR ERP. Everything below is about where that boundary already sits and who owns the rest.

## The two things it got wrong, and they were its two P0s

Both P0s assert that a decision **has not been made**. Both decisions were made, are written
down, and are enforced in code.

### P0 #1 — "the CUPE/WJQ scope decision has not been made explicit" — **FALSE**

It is explicit in five places, one of which is the HR ask the issue says is missing:

| Where | What it says |
|---|---|
| `docs/decisions/HR-DECISION-MATRIX.md` §4 | **Decision 8 — "Confirm the scope: APSA/APEX/Poly only, not CUPE"** — an HR-facing ruling already drafted and waiting |
| `decision_register.yaml` **HR-194** | which bargaining units the Bank serves; `open`, with the ordering spelled out — **HR defines a CUPE bar first, then a token is added** |
| `decision_register.yaml` **HR-143** | WJQ excluded from the cohort the JDFN bar is ratified against |
| `docs/ROADMAP.md` invariant 5 · `docs/plan.md` Phase 7 | scope = JDFN; CUPE is the largest deferred scope question |
| `core/src/api/routes/compose_ui.py` | the Builder's group list is **rulebook data, not a hardcoded tuple** — precisely so this boundary is a visible decision rather than an omission |

**Adopted residue (small, real):** the scope sentence is rendered on `compose_search.html` and
`dashboard_baseline.html` but **not on the Builder page itself** — the one surface where an author
would ask the question. → ROADMAP §2 quick win.

**What the analysis missed, and it is bigger than what it raised:** **31.9% of the archive
(4,630 JDs) has no parsed `employee_group` at all.** That is the parser's residual, not HR's
call — so for a third of the corpus "the Bank serves JDFN" is *unfalsifiable*. Close that before
the CUPE scope conversation, or HR is asked to rule on a boundary we cannot measure. Already
tracked in ROADMAP §1.

### P0 #2 — "the Hay advisory-vs-formal policy needs a decision" — **FALSE**

Decided, and enforced *structurally* rather than by policy prose. `core/src/jd_core/models/bank.py`
drops `HayGrade` / `HayGradeMapping` / `HaySignals.{grade, grade_mapped}` from the faithful hris
port on the stated ground that *"SFU publishes no Hay point charts, and classification is a human
Compensation decision. Nothing in this repo may assign a Hay grade, so a graded signal is made
**unrepresentable** rather than merely unused."* ADR-007 disclaims the comparison/hay adapter as
**not** formal classification, and ROADMAP §3 already bans LLM-assigned grades and embedding the
licensed Hay/WTW point charts.

A gap analysis that reads the file it cites as evidence should not conclude the question is open.

---

## Issue-by-issue verdicts

| # | Copilot issue | Verdict | Where it lives |
|---|---|---|---|
| 1 | Define the CUPE/WJQ scope boundary | ❌ **Rejected — already explicit** (5 places incl. HR Decision 8) | small residue → ROADMAP §2 |
| 2 | Confirm Hay advisory-vs-formal authority | ❌ **Rejected — decided and structurally enforced** | `bank.py`, ADR-007 |
| 3 | CUPE/WJQ authoring support | ⏭ **Already tracked** — HR-194, ROADMAP §4 (XL, HR-gated), plan Phase 7. Copilot omits both the **ordering** (HR bar first) and the **prerequisite** (WJQ boilerplate redaction — the two biggest flagged clusters are template artifacts) | unchanged |
| 4 | Formal Hay evaluation workflow + factor breakdown | ⚠️ **Split.** The *factor breakdown* half needs the licensed Hay point chart → **explicitly OUT**. The *JAQ intake* half is already ROADMAP §3 / plan.md §2 | → Explicitly OUT + existing item |
| 5 | Re-evaluation request management | ✅ **Legit, partially new** — the JDQ/JAQ item covers the front door but not the lifecycle | → ROADMAP §3, sharpened |
| 6 | Compensation requisition workflow | ⚠️ **Out of remit** — the HRIS is the system of record for a pay transaction; JD Bank is upstream of it | → Explicitly OUT |
| 7 | Job-change / reorganization impact tracking | ❌ **Largely already built** | see below |
| 8 | Compensation decision audit trail tied to JD version | ❌ **Largely already built** | see below |
| 9 | Evolve to a full HR lifecycle platform | ⏭ **Vague; ≈ ROADMAP §5 milestones 4–5** (multi-step approval routing is already an item) | unchanged |

### Why 7 and 8 are already built

Copilot's acceptance criteria for both are, item for item, shipped behaviour:

- *"before/after role comparison"* → `jd_core/bank/version_diff.py` + `review.get_version_diff`
  + the standalone `/jd-bank/ui/review/{canonical_id}/diff` page (2026-07-29).
- *"impact rationale captured" / "reviewer rationale is stored"* → `review.edit()` **requires a
  non-blank `reason`** (`MissingReasonError`) and records `changed_sections` in `change_log`.
  Gate overrides likewise require a written reason.
- *"every decision linked to a specific JD version"* → an edit mints `version = max+1`; the EDIT
  action lands on the **new** version; approve supersedes under `FOR UPDATE` with a
  `review.superseded` row.
- *"audit log retained for HR review"* → `audit_log` is append-only and **hash-chained**.

The genuine residues in this area were already on the backlog before the analysis ran:
`review_actions.reviewer_id → users.id` hard FK, and tamper-**prevention** via Postgres
GRANT/REVOKE (the chain is tamper-*evident* today, not prevented).

### One over-claim on the credit side

The analysis lists *"score and grade logic"* under **implemented**. Score, yes. **Grade is not** —
pay-mapped grade is missing or unreliable across the archive (CUPE ~64% parseable, JDFN grade
largely in the HRIS), it is HR-blocked on per-group grade scales
(`docs/decisions/grade-scales-hr-ask.md`), and the capture plan is
`docs/audit/data-state-and-grade-2026-08-01.md`. Do not cite this document as evidence that grade
works.

---

## What was adopted

1. **Re-evaluation request lifecycle** (issue 5) — the existing *Manager reclassification
   questionnaire (JDQ/JAQ) intake* item is sharpened from an intake form into intake → evidence →
   decision record → resolution, reusing what already exists (edit-with-reason, version diff,
   audit chain) rather than inventing a second decision store. ROADMAP §3.
2. **A scope statement on the Builder page itself** (issue 1 residue) — ROADMAP §2 quick win.
3. **Two new "Explicitly OUT" entries** (issues 4 and 6), so their absence reads as a decision
   rather than an oversight — which is the whole point of that section.

## What was not adopted, and the rule behind it

Copilot's roadmap sequences **CUPE/WJQ authoring and a Hay evaluation workflow as "short term,
Phase 2"**. Both are wrong by this repo's own ordering rule: CUPE cannot start before HR defines
a WJQ bar (HR-194 is `open`), and a Hay factor breakdown cannot ship at all. Meanwhile the actual
critical path — **ratification of a register in which every entry is still `open`** — does not
appear anywhere in the four Copilot documents. A gap analysis that plans new capability past an
unsigned approval bar is optimising the wrong thing.

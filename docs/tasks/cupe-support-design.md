# CUPE / WJQ support — design

**Status: DESIGN. Nothing here is built, and one phase of it cannot be built by us.**
`jdfn_employee_groups` is still `[apsa, apex, poly]` and HR-194 is still `open`.

**Why design it now, when HR-194 is unsigned.** The Copilot triage's blind spot was
*planning capability past an unsigned approval bar*. This document is the opposite of that:
it exists to make HR-194 **answerable** by saying what a "yes" would cost, what it would
change, and which parts are not HR's to decide. Every measurement is over the live archive;
see [`docs/decisions/cupe-scope-measured-2026-08-14.md`](../decisions/cupe-scope-measured-2026-08-14.md)
for the scoring evidence.

CUPE is **4,440 of 14,522** current-parser JDs (**30.6%**) and the largest single bargaining
unit in the archive. (JDFN is 5,416 / 37.3%, spread across three groups.)

---

## 1. What is ALREADY built — considerably more than "not served" implies

The phrase "the Bank does not serve CUPE" reads like nothing exists. Measured, most of the
pipeline already does:

| Stage | CUPE state | Evidence |
|---|---|---|
| **Parsing** | ✅ **works** — `parser/wjq.py`, all 14 WJQ sections, since Phase 3.4 | 4,440 JDs parsed, `employee_group = cupe` |
| **Content richness** | ✅ **richer than JDFN** — 9.7 duties vs 3.8; 19.5 quals vs 1.0 | §2 of the decision doc |
| **Tier-2/3 dedup** | ✅ **done** — **49,448** role-equivalent + 3,274 near-duplicate edges, *more* than APSA's 49,008 | `dedup_edges` |
| **Embedding** | ✅ included — CUPE documents are in `jd_document_embeddings` | archive-wide `make embed` |
| **Clustering (persisted)** | ❌ **zero CUPE clusters** | `harmonize/runner.py` drops WJQ |
| **Harmonization → canonical** | ❌ excluded | `is_wjq_member()` |
| **Quality bar / gates** | ❌ **does not exist** | the real blocker |
| **Builder authoring** | ❌ excluded | `jdfn_employee_groups` (HR-194) |

**So the work is not "build a CUPE pipeline".** It is: fix one data defect, make the
validator template-aware, define a bar, then turn on the stages that are already written.

---

## 2. 🔴 The blocking defect, and it is OURS not HR's

**`additional_context` is capped at `max_length=4000`, and 81.4% of CUPE JDs are at the cap
— against 0% of APSA.**

| group | JDs | at the 4,000-char cap | % |
|---|---|---|---|
| `apsa` | 4,946 | 0 | **0.0%** |
| **`cupe`** | 4,440 | **3,613** | **81.4%** |

The WJQ instrument's **seven point-factor sections** — `level_of_independence`,
`training_exercised`, `direction_exercised`, `impact_of_errors`, `effort`,
`working_conditions`, `continuing_education` — are stored **verbatim in
`additional_context`** rather than mapped to model fields. That was a deliberate and correct
call (`wjq.yaml`: force-mapping IMPACT OF ERRORS onto `decision_making` would feed
`hay_signals.py` a bogus signal — *empty is honest*). **The truncation is not.**

The damage is measurable in the section-presence rates, which fall off in document order —
the tail is what gets cut:

| section (WJQ order) | present in CUPE `additional_context` |
|---|---|
| `impact_of_errors` (9) | 85.2% |
| `effort` (10) | 86.3% |
| `working_conditions` (11) | 79.0% |
| `level_of_independence` (5) | 78.1% |
| `direction_exercised` (7) | 76.1% |
| **`continuing_education` (12)** | **17.0%** ← last section, truncated away |

**You cannot build a quality bar over sections whose content is silently discarded for four
in five documents.** This is a data-fidelity defect, not a policy question, and it must be
fixed before any CUPE bar is designed against the data.

**Fixing it needs a `parser_version` bump**, and per the `employee_group` residual precedent
(#101) **the bump and a full re-parse of all 14,565 files must ship together** — bumping
without re-parsing leaves every layer querying a version with no rows, i.e. an apparently
empty Bank.

---

## 3. The architectural fix: the validator is template-blind

`evaluate_jd_rules(sfu, raw_text, *, rules)` runs **every** rule over **every** JD. Nothing
in the signature or the rulebook knows which template a document came from. That is the root
of the category error measured in the decision doc — four rules firing on 100% of CUPE JDs
because the CUPE form does not contain the sections they check.

**Proposal — make it rulebook data, not a code branch.** Each entry in `rule_catalog.yaml`
gains a required `applies_to` (e.g. `[jdfn]`, `[wjq]`, `[jdfn, wjq]`), exactly as P1.3 gave
every register entry a required `tier`:

- **Required, with NO default.** A new rule cannot be filed against a template by omission —
  which is precisely how one undifferentiated ruleset came to be applied to two templates.
- **The four 100%-firing rules become structurally unable to fire on CUPE** rather than
  conventionally excluded — the same move as making `HayGrade` unrepresentable (ADR-007)
  instead of merely unused.
- **`applies_to` is `technical`, not `hr_policy`.** *Which template a rule can judge* is a
  statement of fact about the form; *what the bar should be* is HR's. Keeping those apart is
  the point of the tier.
- Mutation-proof it in both directions, per house habit: adding `wjq` to a JDFN-only
  completeness rule turns a test red, and removing `jdfn` from one does too.

This is worth doing **even if HR rules against serving CUPE**, because it converts "we know
not to score CUPE" from a fact living in a runner's `if` into a property of the rulebook.

---

## 4. What HR must actually decide — and it is smaller than "should we do CUPE?"

HR-194 as written asks one large question. The design splits it into three answerable ones:

1. **Should the Bank serve CUPE at all?** The scope call. Everything else is conditional.
2. **If yes — what is the CUPE quality bar?** Which of the WJQ sections carry an expectation,
   and what it is. From §1's coverage, the candidates are: position summary, duties (with a
   count calibrated to WJQ, **not** `duties_max: 5`), internal/external contacts,
   qualifications, and the seven point-factor sections **once §2 is fixed**.
3. **Does the CUPE bar gate approval, or only inform?** A weaker answer is available and may
   be the right first step: **score and display, but do not gate** — the Bank would show CUPE
   roles in the library with an explicit "no ratified bar" label and refuse to *approve* them,
   which is honest and useful without asking HR to ratify a bar on day one.

**Every threshold that comes out of (2) is a new registered decision, `open`, `hr_policy`
tier.** None may be picked by an engineer, per the standing rule.

---

## 5. Phasing — what can be done now, and what cannot

| Phase | Work | Needs HR? | Notes |
|---|---|---|---|
| **A** | **Fix the `additional_context` truncation**: promote the seven WJQ point-factor sections to first-class structured fields on the model | ❌ **no** | A data-fidelity defect. Needs a `parser_version` bump + full re-parse **shipped together**. Do this first — everything downstream is measured against this data. |
| **B** | **`applies_to` on the rule catalog** + template-aware dispatch in `evaluate_jd_rules` | ❌ **no** | Worth doing even if CUPE is never served (§3). |
| **C** | **Define the CUPE bar** — a WJQ ruleset + gates + thresholds, each registered `open` | ✅ **YES — blocking** | This is HR-194 (2). Nothing here can be guessed by us. |
| **D** | **Turn on the pipeline**: stop dropping WJQ in `harmonize/runner.py`, cluster + harmonize CUPE into roles | ✅ after C | The dedup edges already exist (§1), so this is a pipeline *run*, not new retrieval work. Expect ~950-ish CUPE clusters by analogy with APSA's 955 from 4,014 members — **an estimate, not a measurement**. |
| **E** | **Builder authoring**: add `cupe` to `jdfn_employee_groups` | ✅ after C **and** D | **Last.** Adding the token before a bar exists surfaces the group with nothing behind it — the failure HR-194's `impact_if_changed` already warns about. |

**A and B are ours and can start today. C is HR's and blocks D and E.** The honest sequencing
statement: *we can make the data faithful and the rulebook template-aware without asking
anyone; we cannot invent a CUPE quality standard.*

---

## 6. Explicitly OUT of this design

- **A Hay factor-by-factor point breakdown of the WJQ point-factor sections.** The WJQ *is* a
  point-factor questionnaire, which makes this the obvious next thought and it is still
  refused: the point charts are proprietary Hay/WTW material, SFU publishes none, and
  classification is a human Compensation decision. `HayGrade` and
  `HaySignals.{grade, grade_mapped}` are **unrepresentable** in `models/bank.py` on purpose
  (ADR-007). Scoring WJQ sections for *completeness and quality* is in scope; converting them
  to *points or a grade* is not.
- **Reusing the JDFN gates on CUPE with adjusted thresholds.** Measured: four rules fire on
  100% of CUPE because the sections do not exist in the form. A threshold cannot fix a
  missing section.
- **Serving the unparsed third** (4,630 JDs, 31.9%). Separate and already settled — those
  documents do not state their group, and it is not closeable by parsing (#101).

---

## 7. What would make this concrete next

If HR-194 gets a "yes in principle", the first engineering step is **Phase A**, because every
subsequent measurement is invalid against truncated data. If it gets a "not yet", **Phase B**
is still worth landing on its own merits.

The one measurement this design could not make: **the wall-clock and GPU cost of re-parsing
14,565 files and clustering ~4,440 CUPE JDs.** Stated rather than estimated, per house rule.

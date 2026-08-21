# Phase F — the two forms have to reach the SEARCH and the REPORTING

**Status:** scoped, not started · **Raised:** 2026-08-19, from the Builder's own CUPE page
· **Needs HR:** no (HR-194 governs *authoring* scope, already registered; none of this
adds a decision)

Phases B–E made the two SFU forms real everywhere a JD is **judged** (`applies_to`),
**measured** (`thresholds_for`), **assembled** (`templates_harmonized`) and **authored**
(`FormSpec`). Two surfaces never got the same treatment, and both are now visibly wrong
to a person using the Builder in CUPE mode.

---

## F1 — "Start from an existing JD" is JDFN-only, in both directions

**Measured:** `composer/search.py` defines `_NON_JDFN_GROUP = "cupe"` and filters it out
in **four** places (lines ~462, ~485, ~515, ~542) — the title pass, the vector pass and
both cluster-collapse paths. It was correct when written: the Builder authored one form
(HR-143/HR-194), so offering a CUPE source would have handed the author a JD their
Builder could not represent.

**Now it is backwards.** With the WJQ Builder shipped (Phase E), an author who has picked
**CUPE (WJQ)** and searches the archive gets **zero CUPE results** — the only sources
offered are the ones from the *other* form.

**And the clone silently switches forms.** `_clone_into_its_own_form` routes on
`form_for(jd)`, i.e. the SOURCE's template. So cloning a JDFN result while in CUPE mode
drops the author into the JDFN Builder with no warning. That is correct behaviour for the
clone (reading a JDFN doc through the WJQ contract would lose content) and wrong
behaviour for the *flow* — the author asked for a CUPE JD.

### Scope

1. **Search takes the form as a parameter**, defaulting to the caller's current form.
   `SearchHit` already carries `employee_group`, so the data is there; only the filter
   is missing. Replace the four `_NON_JDFN_GROUP` exclusions with a single
   `template_of`-based predicate — the same separator everything else uses, not a fifth
   place that decides what CUPE means.
2. **The Builder passes its active form** to `/compose/search` and `clone-role`.
3. **Cross-form clones are OFFERED, not hidden, and never silent.** A CUPE author
   searching may legitimately want to see a JDFN role — the useful behaviour is to show
   it, labelled with its form, and say plainly that starting from it switches to the JDFN
   Builder. (The review queue already had to solve exactly this: two forms in one list
   where the number beside them is not the same measurement — see D5.)
4. **⚠ Do NOT convert answers across forms.** The two contracts do not ask the same
   questions; a "convert" would drop whatever the target form does not have, silently.
   Switching starts a fresh draft. This is already the picker's documented behaviour.

**Size:** small. One predicate, one parameter threaded through two routes, plus the
labelling. The tests exist to copy — `test_composer_forms.py` already pins form routing.

---

## F2 — The dashboards report a pre-CUPE world

**Measured, from the committed artifacts:**

| artifact | rules_version | generated |
|---|---|---|
| `docs/baseline/summary.json` | `+90af5e27dc83` | 2026-08-02 |
| `docs/cluster/cluster-summary.json` | `+90af5e27dc83` | 2026-07-17 |
| **shipped rulebook** | **`+76baba29cfeb`** | — |

`+90af5e27dc83` is **pre-Phase-B**. So every number the baseline dashboard renders for the
WJQ segment was computed by scoring CUPE documents **against the JDFN bar** — the exact
category error Phases B and C removed. The dashboard is honest about the consequence in
its own copy ("WJQ (CUPE) is a different template with **no JDFN approval bar**") and that
sentence is now false: the WJQ has its own applicable rules (B) and its own numbers (C).

Three separate problems, and they should not be conflated:

1. **Stale artifacts.** `make baseline` and `make cluster` must be re-run against the
   current rulebook. Mechanical; the dashboards then show per-form numbers computed on
   each form's own bar. ⚠ `make baseline` is a full pass over all 14,565 files — check
   `docs/baseline/README.md` before running, and expect the WJQ segment's numbers to move
   a long way (Phase B measured 0.0% → 59.0% approvable for the WJQ cohort).
2. **Stale copy.** The "no JDFN approval bar" paragraph in `dashboard_baseline.html`, and
   anything else asserting CUPE is unscoreable, needs rewriting to say what is now true:
   each form is scored against its own bar, and **the two numbers are not comparable**.
   That last clause is the one that matters — the same warning D5 put on the review queue.
3. **🔴 The per-form draft evaluation is rendered NOWHERE.** D3 added
   `CanonicalProducerResult.evaluation_by_template` — clusters, drafts scored, mean score,
   approvable and grade distribution, per form — and it lives only in
   `docs/canonical/summary.json`. There is no canonical/review dashboard at all (the index
   offers baseline, dedup, clusters). **This is the number HR will actually ask for** —
   "how good are the drafts?" — and today the only honest answer is a JSON file.

### Scope

- **F2a** — re-run `make baseline` + `make cluster`; commit the refreshed artifacts.
  *Do it AFTER the CUPE rebuild finishes*, so the two do not contend for Postgres.
- **F2b** — correct the dashboard copy that says CUPE cannot be scored.
- **F2c** — a **drafts dashboard** rendering `evaluation_by_template`: one block per form,
  each naming its own bar, with **no total row**. The producer deliberately computes no
  blended number (D3) and the dashboard must not invent one — a mean across two forms is
  a mean across two different measurements.

**Size:** F2a is a long batch job and nearly free in code. F2b is copy. F2c is a new page
over an artifact that already exists — the smallest of the three, and the highest value.

---

## What this does NOT include

- **No new HR decisions.** Nothing here picks a threshold or changes a bar; F1 and F2
  make existing decisions visible. If a knob appears, it is a sign the scope drifted.
- **No cross-form conversion** (see F1.4).
- **The near-duplicate authoring guard** already runs form-blind over harmonized roles and
  is out of scope until someone measures whether cross-form near-duplicates are a real
  category. Recorded so its absence is not mistaken for an oversight.

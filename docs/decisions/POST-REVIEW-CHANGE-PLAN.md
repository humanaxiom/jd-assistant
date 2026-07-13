# Post-Review Change Plan

**The engineering counterpart to [`HR-REVIEW-PACKET.md`](HR-REVIEW-PACKET.md).**
For each decision HR can hand back, this says *exactly* what changes: which file, which key, what
it moves, what test goes red, and what else must land in the same PR.

**Baseline this plan is measured against:** `jd_rules_sfu_v4+2cb6723a5241`, all 14,565 archive
files (`docs/baseline/`). Current-practice cohort n=874, approval 628 (71.9%).

---

## The rules of engagement (do not skip)

1. **No change lands without a register entry in the SAME PR.** Standing rule, build-enforced.
   Editing a shipped default without updating `decision_register.yaml` fails `make gates`; editing
   the register without re-rendering fails `make register-check`. Run **both**.
2. **Flip `status: open` → `ratified` for every decision HR rules on** — including the ones they
   ratify *unchanged*. "HR looked at this and kept it" is a different fact from "nobody has ever
   looked."
   **The machinery already exists and is enforced** (`loader.py :: DecisionEntry`): a `ratified`
   decision **must** record `decided_by`, `decided_on` and `decision_note`, and an `open` one must
   **not** — the rulebook fails to load otherwise. So a ruling cannot be recorded without saying
   *who* decided, *when*, and *why*. Use it; do not invent a parallel notes file.
3. **Re-run the baseline after every accepted change** and diff `summary.json`. A ruling whose
   measured effect we did not verify is just another unchecked claim.
4. **Editing a rule YAML churns `rules_version`.** That is intended — the stamp identifies the
   rulebook that produced a report. Expect `make register` to be required, and expect the
   committed baseline in `docs/baseline/` to become **stale the moment any rule changes**. Re-run
   it in the same PR, or the repo ships a baseline that describes a rulebook that no longer exists.
   (`segmentation.yaml` is the exception — it is excluded from the digest, so era changes do *not*
   churn `rules_version`.)

---

## Decision 1 — Summary word range (HR-019 / HR-020)

**Ruling expected:** ratify 100–150 unchanged. It is `sfu_rulebook` provenance — SFU's own number.

| | |
|---|---|
| Config | `thresholds.yaml :: thresholds.summary_min_words` = **100**, `summary_max_words` = **150** |
| Gate | `SFU-APPROVE-SUMMARY-LENGTH` ← `SFU-STRUCT-SUMMARY-TOO-LONG` (in `gates.blocking_rule_ids`) |
| Blocks now | **134** of 246 — the #1 operative gate |

**If ratified unchanged:** flip HR-019/HR-020 to `ratified`. No code change. **But** record in the
entry that this is the largest single determinant of approval — an HR reviewer must not ratify it
believing it is a formatting nicety.

**If HR widens the range** (e.g. 100–200): edit `summary_max_words`. Expect ~134 blocks to fall
sharply — re-measure, don't estimate. `rules_version` churns.

### 1b — the asymmetry (HR-019)

`SFU-STRUCT-SUMMARY-TOO-SHORT` fires on **340 of 874** current JDs but is **NOT** in
`gates.blocking_rule_ids` — so it costs score and never blocks. `TOO-LONG` (134) **is** in the set.
That asymmetry is `our_invention`.

⚠️ **If HR asks us to "make it symmetric": DO NOT just add `SFU-STRUCT-SUMMARY-TOO-SHORT` to
`blocking_rule_ids`.** It would instantly become **the largest blocker in the system** (340 > 134)
and approval would fall from 71.9% to roughly 40%. Model it first, show HR the number, and make
them ratify *that* figure, not the principle.

---

## Decision 2 — `SFU-QUAL-BANNED-PHRASE` scoping (HR-041) — **A BUG, DO THIS FIRST**

**This is not a policy question. It is a defect, and it is the #2 operative gate.**

| | |
|---|---|
| Config | `qualifications.yaml :: qualifications.banned_phrases` |
| Gate | `SFU-APPROVE-QUAL-MINIMUM` ← `SFU-QUAL-BANNED-PHRASE` |
| Blocks now | **104** of 246 — **all 104 are this rule** (verified: 104/104 carry it) |
| Defect | Rule text says *"phrases the Toolkit bans from **Qualifications**"*; the scan runs over the **whole document** |

**The fix:** scope the scan to the Qualifications section — `validators.py :: _qualifications`
already receives `sfu.qualifications`; the rule currently reads the full `FoldedText` instead.

**Why it must go through the register anyway:** narrowing the scope **changes who gets approved**.
That is a change to the approval bar, so it needs a register entry in the same PR with the measured
before/after, and a re-run baseline committed alongside.

**Measured ceiling (don't over-promise it):** of the 104 JDs this gate blocks, only **59** are
blocked by *nothing else* — the other 45 also trip `SUMMARY-LENGTH` or `QUAL-EQUIVALENT` and stay
blocked regardless. So fixing the scope moves approval from **71.9% → at most 78.6%** (628 → 687),
*not* to the ~84% a naive 628+104 would suggest. Re-measure after the fix; this is an upper bound
that assumes the section-scoped rule clears all 59.

**Sequencing: land this BEFORE HR ratifies anything else in the gate set.** Every other number in
the packet is measured on a corpus distorted by this bug. HR should be ratifying the corrected
figures.

---

## Decision 3 — The no-appeal set (HR-005 / HR-047)

| | |
|---|---|
| Config | `gates.yaml :: gates.non_overridable_gate_ids` = `[SFU-APPROVE-MANDATORY-SECTIONS, SFU-APPROVE-NO-PLACEHOLDERS]` |
| Markers | `markers.yaml :: markers.placeholder` (contains `action verb`, `how and why`, `what by`) |
| Reach | `NO-PLACEHOLDERS`: **29.4%** of the archive, **0%** of current practice. `MANDATORY-SECTIONS`: 65.2% / 0.8%. |

**Recommended ruling: remove `SFU-APPROVE-NO-PLACEHOLDERS` from `non_overridable_gate_ids`.**

**The change:** delete one line from `gates.non_overridable_gate_ids`. The gate still fires and
still blocks — it simply becomes waivable with a written reason (which is the audit trail we want
anyway, per non-negotiable #1).

**What must go red:** there is a test asserting the non-overridable set. Confirm it is a
*behavioural* pin (a JD tripping the gate cannot be overridden) and not just a by-value pin of the
list. If only the list is pinned, **add the behavioural test in the same PR** — this is exactly the
class of decision the mutation bar exists for.

**Do NOT also edit `markers.placeholder`** to remove `action verb` / `how and why`. That is a
*separate* decision (HR-047) about what a placeholder *is*, and the markers genuinely do catch real
leftover template text ("For each item start with an action verb…" exists in live JDs). Making the
gate waivable solves the harm without blinding the rule. Two rulings, two PRs.

---

## Decision 4 — The territorial / EDI footer (HR-004)

| | |
|---|---|
| Config | `gates.yaml :: gates.blocking_rule_ids` — contains `SFU-COMP-TERRITORIAL` and `SFU-COMP-EDI` |
| Gate | `SFU-APPROVE-EDI-FOOTER` (**overridable**) |
| Reach | Blocks **13,658 / 14,522 = 94.1%** of the archive. Only **10** current-practice JDs. |

The gate is already overridable, so this is not about un-blocking — it is about not demanding
~13,000 individual written waivers for a paragraph that didn't exist when the JDs were written.

**(a) HR accepts as-is** → flip HR-004 to `ratified`, change nothing. Record that the archive
requires ~13,000 waivers, so nobody is surprised later.

**(b) [recommended] Composer auto-inserts the footer** → **this is not a rules change at all.** It
is a Phase 5 composer feature: the footer is boilerplate, identical on every JD, and CLAUDE.md
already mandates it live in a single config constant. Remove `SFU-COMP-TERRITORIAL` /
`SFU-COMP-EDI` from `blocking_rule_ids` **only once the composer actually emits them** — otherwise
we drop the check without gaining the guarantee. **Ordering matters. Do not remove the gate first.**

> ⚠️ Cross-reference the standing open flag in CLAUDE.md: *"Territorial acknowledgement wording:
> verify against SFU's current official text before any external distribution."* If we start
> auto-inserting the text, **that flag becomes blocking** — we would be generating the wording, not
> merely checking for it. Get the official wording from HR in the same review.

**(c) Date-scope the rule** → needs a new decision + register entry (a rule that applies only after
a date is a new concept in the rulebook). Most complex option; only take it if HR rejects (b).

---

## Decision 5 — The era model (HR-109 / HR-110 / HR-111)

| | |
|---|---|
| Config | `segmentation.yaml :: era_template_token` (`JDFN`), `era_old_max_year` (2009), `era_transition_max_year` (2018) |
| Effect | 10.0% approval (our "new") vs 71.9% (actual current practice) — **7× distortion** |

**Not scoring config** — it decides which *files* a baseline covers, never how a JD is scored. So
**editing it does NOT churn `rules_version`** (it's in `_UNHASHED_FILES`). It does churn the
segmentation stamp, which is correct and is why there are two stamps.

**(a) [recommended] Add a fourth `current` era from 2024.** Adds an `ArchiveEra` literal
(`config.py`) + a new band key + a register entry. The loader validates era ordering, so a band
nothing can land in fails to load — good.

**(b) Define "current" by footer presence, not date.** Cleaner conceptually (it's the actual
signal), but it makes era depend on **document content**, not the filename — so `file_facets()`
stops being pure-and-never-raising over a filename and needs the extracted text. That is a real
architectural change to `facets.py`. Don't take it casually.

Either way: re-run the baseline, and **update `docs/baseline/README.md`'s cohort definition** —
the "current practice" cohort is currently defined ad-hoc (new-era ∧ no `SFU-COMP-TERRITORIAL`).
Once the era model is fixed, it should just be an era.

---

## Decision 6 — Score floor / grade floor / severity floor (HR-001 / 002 / 003)

| | Config | Default | Rejects |
|---|---|---|---|
| Score floor | `gates.yaml :: gates.SFU-APPROVE-SCORE-FLOOR.min_score` | **60.0** | 5 / 874 |
| Grade floor | `gates.yaml :: gates.SFU-APPROVE-GRADE-FLOOR.min_grade` | **C** | 5 / 874 |
| Severity floor | `gates.yaml :: gates.SFU-APPROVE-SEVERITY-FLOOR.min_severity` | **high** | 7 / 874 |

**Expected ruling: ratify all three unchanged.** No code change — flip `status` to `ratified` (see
rule 2 above; the schema needs the value first).

⚠️ **These numbers are only meaningful AFTER Decision 2 is fixed.** The score distribution is
depressed by `SFU-STRUCT-HOW-WHY` (Decision 7) firing on 100% of JDs; if that rule is retired,
**every score rises** and the floor of 60 becomes even more inert. Ratifying 60 before settling
Decision 7 means ratifying it against a distribution we are about to move.

**Recommendation: settle Decisions 2 and 7 first, re-baseline, then ask HR to ratify the floors
against the corrected numbers.** Otherwise HR ratifies a number whose meaning changes underneath
them.

---

## Decision 7 — `SFU-STRUCT-HOW-WHY` (HR-119)

| | |
|---|---|
| Config | `rule_catalog.yaml :: rule_catalog.SFU-STRUCT-HOW-WHY.default_severity` = **low** |
| Fires on | **77.7%** of new-era, **99.4%** of current practice, **628/628 (100%)** of JDs we would approve |
| Provenance | `hris_calibration` — **not** an SFU rule |

A finding on 100% of approvable JDs has **zero discriminating power**. It is a constant subtracted
from every score.

**If HR says the "how and why" expectation is NOT real:** the fix is *not* simply to set severity
to `info`. Investigate the rule's logic first — a rule that fires on literally every document is
more likely **matching wrongly** than describing a universal failure. Check `validators.py ::
_structure`. It may be a detection bug, in which case fixing it is worth far more than muting it.

**If HR says it IS a real expectation:** leave it, but say so in the register — because then we are
telling SFU that essentially none of its current JDs meet its own duty-writing standard, and that
is a finding HR needs to own explicitly rather than absorb silently.

**Either way, re-baseline.** This rule is the largest single depressant on the distribution; moving
it moves every score, and therefore the meaning of Decision 6.

---

## Recommended sequencing

The decisions are **not independent**. Ratifying the floors before fixing the rules that distort
the distribution would have HR ratify numbers that are about to move.

1. **Fix Decision 2** (`BANNED-PHRASE` scoping — a bug). Re-baseline.
2. **Settle Decision 7** (`HOW-WHY` — bug or real?). Re-baseline.
3. **Fix Decision 5** (era model). Re-baseline. → *Now the numbers are trustworthy.*
4. **Take Decisions 1, 3, 4, 6 to HR** for ratification against the corrected baseline.
5. Flip every ruled decision `open` → `ratified`, with the date and the ruling recorded.

Steps 1–3 are **ours** and need no HR input — they are defects and a modelling error. Step 4 is the
only part that genuinely needs HR.

> **The one thing not to do:** hand HR the current numbers, get 119 ratifications, and *then*
> discover the numbers moved. The register would then say "HR ratified 60.0" against a distribution
> that no longer exists — provenance theatre. Fix first, then ask.

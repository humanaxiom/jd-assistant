# Post-Review Change Plan

**The engineering counterpart to [`HR-REVIEW-PACKET.md`](HR-REVIEW-PACKET.md).**
For each decision HR can hand back, this says *exactly* what changes: which file, which key, what
it moves, what test goes red, and what else must land in the same PR.

**Baseline this plan is measured against:** `jd_rules_sfu_v4+67decdb6e9d3` (post-2.6), all 14,565
archive files (`docs/baseline/`). Current-practice cohort n=874, approval **687 (78.6%)**.

## Status — Phase 2.6 landed three of these

Decisions **2, 5 and 7** were **our defects, not HR questions.** Per the sequencing at the bottom of
this document, they were fixed and re-baselined **before** the packet went to HR — so HR is
ratifying corrected numbers, not distorted ones.

| # | Was | Status |
|---|---|---|
| 2 | `SFU-QUAL-BANNED-PHRASE` scanned the whole document | ✅ **DONE** (HR-120) — blocks 104 → 0; **+59 approvals** |
| 5 | Era model conflated two rollouts | ✅ **DONE** (HR-122) — 4th `current` band (2024+) |
| 7 | `SFU-STRUCT-HOW-WHY` was unevaluable | ✅ **DONE** (HR-121) — retired; median 77.3 → 79.0 |

Net: approval **71.9% → 78.6%**, median **77.3 → 79.0**, blocked **246 → 187**, score-floor
rejections **5 → 2**. Attribution is clean: **all +59 approvals are Decision 2's** (exactly the JDs
it was the sole blocker of). **Decision 7 moved zero approvals** — it changed what every JD is
*worth*, not what any JD is *permitted*.

**Decisions 1, 1b, 3, 4, 6 remain open and need HR.** Their sections below are still live.

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

## Decision 2 — ✅ DONE (HR-120) — `SFU-QUAL-BANNED-PHRASE` scoping

**Landed in Phase 2.6.** Shipped as a rulebook knob, `qualifications.yaml :: banned_phrase_scope`
(`Literal["qualifications","document"]`, shipping `qualifications`) — so HR can still choose the
whole document, and the change is mutation-testable rather than a silent variable swap.

Measured: `QUAL-MINIMUM` blocks **104 → 0**; archive-wide the finding **1,600 → 10**; **+59
approvals** (the 59 it was the *sole* blocker of; the other 45 were failing something else too).

**A hole worth knowing about, and why it is closed:** if the segmenter finds *no* Qualifications
section, the rule cannot fire — so the JD escapes `SFU-APPROVE-QUAL-MINIMUM`. That is the "gate that
cannot fire" bug class a previous reviewer caught. It is closed **by another gate, not by luck**:
such a JD trips `SFU-COMP-QUALS`, which sits inside the **non-overridable**
`SFU-APPROVE-MANDATORY-SECTIONS`. It is un-waivably blocked — strictly stricter than the gate it
escaped. Verified end-to-end through the real segmenter, and pinned by test.

**⚠️ New open question this created (HR-041):** correctly scoped, the banned-phrase list now matches
**10 files in 14,522**. Either it is a guard-rail nobody trips, or **it is missing the phrases SFU's
authors actually write.** That is now the live question, and it needs an experienced JD reviewer, not
an engineer.

**Also now stale:** `gates.yaml` justifies `SFU-APPROVE-QUAL-MINIMUM` being `overridable: true` on
the grounds that *"the phrase match spans the whole document."* It no longer does — so **the
rationale for the gate being waivable has evaporated.** Whether it should still be overridable is an
open HR question (HR-042).

<details>
<summary>Original brief (kept for provenance)</summary>

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

*(The predicted 78.6% ceiling was hit **exactly**.)*

</details>

---

## Decision 3 — The no-appeal set (HR-005 / HR-047) — **OPEN, needs HR**

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

## Decision 5 — ✅ DONE (HR-122) — the era model

**Landed in Phase 2.6.** Fourth band `current` (2024+) via `segmentation.era_new_max_year: 2023`.
Bands now: `old` 3,339 · `transition` 4,964 · `new` 5,228 · **`current` 1,034**.

**The trap we nearly walked into:** the `JDFN` token used to override the date band **outright**.
Since every JD written today carries it, a naive fourth band would have collapsed instantly — every
current JD would still have landed in `new`. The token now **promotes** an old file up the ladder
but never **demotes** a current one.

`segmentation.yaml` is in `_UNHASHED_FILES`, so this correctly did **not** churn `rules_version` —
only the segmentation stamp moved. Behaviourally asserted.

**⚠️ Still open, and it is HR's:** the band is **not** the cohort, and we did not force it to be.
`current` (1,034) and current-practice (874) agree on **795** — 239 JDs dated 2024+ still lack the
footer, and 79 that carry it predate 2024. Band reads 61.2%; cohort reads 78.6%. **The 17-point gap
is the rollout's remaining 37%.** Quote the cohort for claims about the bar, the band for claims
about a date. Option (b) below — era by footer *presence* — remains the truer signal.

<details>
<summary>Original brief (kept for provenance)</summary>

## Decision 5 (original) — The era model (HR-109 / HR-110 / HR-111)

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

</details>

> ⚠️ **The cohort filter changed and it bit us.** Adding the `current` band split the old `new`
> band, so the pre-2.6 filter (`era == "new"` ∧ no territorial) now returns **79** JDs, not 874. The
> correct filter is **`era ∈ {new, current}`** ∧ no territorial. This is now stated explicitly at the
> top of `docs/baseline/README.md` — the reviewer caught it applying the documented filter literally
> and getting 79.

---

## Decision 6 — Score floor / grade floor / severity floor (HR-001 / 002 / 003) — **OPEN, needs HR**

| | Config | Default | Rejects |
|---|---|---|---|
| Score floor | `gates.yaml :: gates.SFU-APPROVE-SCORE-FLOOR.min_score` | **60.0** | **2** / 874 |
| Grade floor | `gates.yaml :: gates.SFU-APPROVE-GRADE-FLOOR.min_grade` | **C** | **2** / 874 |
| Severity floor | `gates.yaml :: gates.SFU-APPROVE-SEVERITY-FLOOR.min_severity` | **high** | 7 / 874 |

**Expected ruling: ratify all three unchanged.** No code change — flip `status: open` → `ratified`
and record `decided_by` / `decided_on` / `decision_note` (the loader enforces all three).

✅ **These numbers are now safe to ratify.** Decisions 2 and 7 are landed and the archive is
re-baselined, so the distribution HR ratifies against is the one that will actually run. Post-2.6
the floors are *more* inert than before (5 → 2 rejections), which strengthens the case rather than
weakening it.

**Worth putting to HR explicitly:** at a median of **79** with 82 A-grades, a floor of 60 is a
formality. **A floor of 70 would be a real bar.** We are not recommending it — that is a policy
choice about how demanding SFU wants to be — but HR should know the option exists and is cheap
(one YAML value + a re-baseline).

---

## Decision 7 — ✅ DONE (HR-121) — `SFU-STRUCT-HOW-WHY`

**Landed in Phase 2.6.** The rule was **unfalsifiable**: the parser never populates `how_why`
(`segmenter.py` says so — *"left empty"*), so it fired on every duty of every JD. 628/628 of the JDs
we would approve.

**Muting the severity would have been the wrong fix, and we checked rather than assumed:**
`scoring.severity_penalty.info == 0.0`, so setting severity to `info` would have lifted scores
**while still emitting the finding on every JD** — hiding the constant rather than removing it.

**Actual fix:** `RuleSpec.evaluable: bool` + a derived, registered `RuleCatalog.unevaluable_rule_ids`
(same pattern as `gates.blocking_rule_ids`). `evaluate_jd_rules` drops rules the catalog says the
engine cannot evaluate. The rule stays catalogued (text, severity, Part 2C citation intact) and the
`_structure` branch stays standing — **Phase 4 reinstates it with one YAML word and zero code**, once
the parser extracts the field.

Measured: finding **8,593 → 0** archive-wide. Scores **rose on 9,217 files, unchanged on 5,305, fell
on 0**. (Precisely: *every score that carried the finding rose; none fell.* **Not** "every score
rose" — 36.5% of the archive never carried it.) **Zero approvals moved** — it changed what every JD
is *worth*, not what any JD is *permitted*.

**Guard:** a blocking gate may not name an unevaluable rule (else a gate that can never fire — the
exact landmine a previous reviewer caught). The first version of this guard covered only
`BlockingRulesGate`; the reviewer **exploited the gap via `SeverityFloorGate`** (promote a rule to
`high` in data, then mark it unevaluable → the finding vanishes, approval flips, rulebook loads
clean). The guard now also rejects an unevaluable rule whose **maximum reachable severity** meets any
severity floor.

> **The standing danger with `evaluable`:** it is a switch that can silently disable an inconvenient
> rule. What stops abuse is that it is **registered, on the decision surface, and mutation-pinned** —
> flipping it fails the build until someone records *why*. Keep it that way.

<details>
<summary>Original brief (kept for provenance)</summary>

## Decision 7 (original) — `SFU-STRUCT-HOW-WHY` (HR-119)

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

</details>

---

## Sequencing — steps 1–3 are DONE

The decisions are **not independent**. Ratifying the floors before fixing the rules that distort the
distribution would have had HR ratify numbers that were about to move.

1. ✅ **Decision 2** (`BANNED-PHRASE` scoping — a bug). Fixed, re-baselined.
2. ✅ **Decision 7** (`HOW-WHY` — it was a bug, not a real expectation). Fixed, re-baselined.
3. ✅ **Decision 5** (era model). Fixed, re-baselined. → *The numbers are now trustworthy.*
4. ⏭ **Take Decisions 1, 1b, 2b, 3, 4, 6 to HR** for ratification against the corrected baseline.
5. ⏭ Flip every ruled decision `open` → `ratified`, recording `decided_by` / `decided_on` /
   `decision_note` (the loader will not let you skip them).

Steps 1–3 were **ours** and needed no HR input — two defects and a modelling error. Step 4 is the
part that genuinely needs HR.

> **The one thing we did not do:** hand HR the pre-2.6 numbers, collect 122 ratifications, and *then*
> discover the numbers had moved. The register would now say "HR ratified 60.0" against a
> distribution that no longer exists — provenance theatre. **We fixed first, then asked.** Keep doing
> it in that order.

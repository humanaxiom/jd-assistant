# JD Bank — Decisions for SFU HR

**Status:** awaiting HR review. **Nothing in this system has been ratified by SFU.**
**Date:** 2026-07-13 · **Rulebook under review:** `jd_rules_sfu_v4+67decdb6e9d3`
**Evidence:** every number below is measured against all **14,565** JDs in the SFU archive
(`docs/baseline/README.md`).

> **Before you read on:** the first version of this packet was written against an earlier rulebook.
> Running it against your archive exposed **three defects in our own rules** — one of which could
> never *not* fire. We fixed those first and re-measured, so **you are reading corrected numbers.**
> Handing you figures we already knew were distorted, collecting your ratification, and *then*
> fixing them would have made your sign-off meaningless.

---

## What we are asking you to do

We built a tool that reads a job description and decides **whether an HR reviewer may approve
it**. It never approves anything itself — a human always decides. But it can *block* the approve
button, and it scores every JD out of 100.

To do that, we had to pick **119 numbers, word lists and rules**. Roughly a hundred of them come
from SFU's own JD Toolkit. **The rest we invented**, because the Toolkit doesn't say. Those
invented ones are now silently deciding which of your job descriptions are acceptable.

We have run all of them against your entire archive. **This document asks you to ratify or change
the nine that actually matter.** The other 110 are recorded in
[`HR-DECISION-REGISTER.md`](HR-DECISION-REGISTER.md) and can wait — the archive shows they change
almost nothing.

**You do not need to read any code.** Every one of these is a setting we can change in minutes.

---

## First, the headline

**The system, as configured, works.** On the job descriptions SFU writes *today*:

| | |
|---|---|
| JDs measured | **874** (those written under current practice) |
| **Would be approvable** | **687 — 78.6%** |
| Median quality score | **79 / 100** |
| Grades | 82 A · 550 B · 240 C · 2 D · **no F** |
| Rejected on quality score | **2** |

That is a healthy result. Nearly eight in ten of your current job descriptions would pass straight
through; the rest need edits, not rewrites. **No job description in your current corpus scores an
F.**

**But three things in it still need your ruling, and you need to know before you sign anything.**

---

## Decision 1 — ⚠️ The bar you think you're approving is not the bar that's operating

**You would assume the system blocks bad job descriptions on quality.** It doesn't. Here is what
*actually* blocked the 187 current JDs that failed:

| What blocked it | JDs | |
|---|---:|---|
| **Position Summary is outside 100–150 words** | **134** | ← the real gatekeeper |
| Missing "or an equivalent combination of education and experience" | 42 | |
| Missing part of the territorial/equity footer | 10 | |
| Summary describes working conditions, not the role | 9 | |
| Missing a mandatory section | 7 | |
| …*the actual quality score being too low* | **2** | |

**The quality score rejects two job descriptions out of 874.** It is almost inert. The thing doing
the real gatekeeping is **a word count.**

> **What we need from you:** simply to *know* this before you ratify. The 100–150 word range is
> **SFU's own published number**, not ours — so we recommend keeping it. But you should ratify it
> knowing it is the single largest determinant of whether a JD gets approved, not a minor
> formatting nicety.

**Related, and your call:** the Toolkit says a summary should be 100–150 words. We currently block
JDs that are **too long** (134 of them) but **not** JDs that are **too short** — even though 340
of your current JDs *are* too short. That asymmetry was our choice, not the Toolkit's. Enforcing
it "for consistency" would instantly make the under-run **the single biggest blocker in the
system**. We recommend leaving it as-is and flag it only so the inconsistency is a decision rather
than an accident.

*(Register: HR-004, HR-019, HR-020)*

---

## Decision 2 — ✅ FIXED: the second-biggest blocker was a bug on our side

**We are reporting this rather than quietly fixing it, because correcting it changed who gets
approved — and any change to the approval bar belongs to you.**

A rule was rejecting **104** of your job descriptions. It is supposed to catch "wish-list" language
in the **Qualifications** section — phrases like *"may include"* or *"an asset"* that turn a minimum
requirement into a nice-to-have.

**It was scanning the entire document instead of the Qualifications section.** So a JD that said, in
its *Duties*:

> *"Responsibilities **may include** arranging catering for departmental events…"*

…was blocked for a Qualifications problem it did not have. **All 104 blocks were this bug. Every
single one.**

**Now fixed.** Those blocks went 104 → **0**, and **59 job descriptions** became approvable (the
other 45 were also failing something else). This is the entire improvement from 71.9% to 78.6%.

> **What we now need from you — a real question the fix exposed.** Correctly scoped, that banned-
> phrase list now matches **10 files out of 14,522.** Either it is a guard-rail nobody trips, or
> **it is missing the phrases your authors actually write.** We would like a few minutes of an
> experienced JD reviewer's time to tell us which.

*(Register: HR-041, HR-120)*

---

## Decision 3 — ⚠️ Two rules can block a JD with **no appeal**, and one of them is wrong

Most blocks can be **waived** by a reviewer who writes down a reason. Two cannot. A JD that trips
these is **permanently un-approvable** — no override, no waiver, no human judgement.

| Non-overridable rule | Blocks | |
|---|---:|---|
| A mandatory section is missing | 65% of the archive · **0.8%** of current JDs | Defensible |
| **Contains a "placeholder"** | 29% of the archive · **0%** of current JDs | ⚠️ **Demonstrably wrong** |

The placeholder rule treats the phrases **"action verb"**, **"how and why"** and **"what by"** as
evidence that someone left template boilerplate in the document. But a job description that simply
*discusses* action verbs — as a **Communications or HR training role legitimately might** — is
permanently un-approvable. There is no waiver. A human reviewer who can see the JD is fine has no
way to say so.

Good news: it blocks **zero** of your current job descriptions. It is a problem for the historical
archive, not for what you write today.

> **Our recommendation:** **remove "no placeholders" from the no-appeal list.** Keep the rule — it
> genuinely catches real leftover template text, which *does* exist in live JDs — but let a
> reviewer waive it with a written reason. Taking human discretion away is only defensible when a
> rule is *never* wrong, and this one is provably wrong.

*(Register: HR-005, HR-047)*

---

## Decision 4 — 📅 One rule is silently measuring the calendar, not quality

The territorial acknowledgement and Employment Equity statement are mandatory. Our system blocks
any JD that lacks them — **94% of your entire archive.**

That looks alarming. It isn't. **SFU only began putting the acknowledgement into job descriptions
around 2023.** Here is the actual adoption:

| Year | JDs carrying the acknowledgement |
|---|---|
| 2018 | 0% |
| 2019 | 0.2% |
| 2021 | 1.4% |
| 2023 | 11% |
| 2024 | **63%** |
| 2025 | **85%** |
| 2026 | **89%** |

So this rule is not detecting a quality problem. **It is detecting a document's age.** Your staff
did nothing wrong; the paragraph simply did not exist yet.

The block *is* waivable — but on the historical archive that means a reviewer writing an
individual justification roughly **13,000 times.**

> **What we need from you — pick one:**
> - **(a)** Accept it. Old JDs stay blocked until someone adds the paragraph. *(Honest, but makes
>   the historical archive practically unusable without ~13,000 waivers.)*
> - **(b) [we recommend]** Treat the footer as something the **system adds automatically** when a
>   JD is composed, rather than something the *author* is penalised for omitting. It is boilerplate
>   — identical on every JD. Blocking a 2015 JD for lacking a paragraph invented in 2023 tells you
>   nothing you didn't already know.
> - **(c)** Only apply the rule to JDs written after a date you choose.

*(Register: HR-004 — `SFU-COMP-TERRITORIAL`, `SFU-COMP-EDI`)*

---

## Decision 5 — ✅ FIXED: we split your archive into "eras" and we got it wrong

To judge fairly, we sorted your JDs into OLD / TRANSITION / CURRENT, so we would not score a 1990
job description against a 2019 template. **Our era model assumed one changeover. There were two,
four years apart:**

- the **JD template** changed in **2019**;
- the **territorial/equity footer** became standard in **2023–24**.

We classed everything from 2019 as "current" — then judged it with a rule only the 2023+ JDs could
satisfy. The result: a **2019 job description, written perfectly correctly under the template of
its day, is un-approvable.**

The damage was large and purely artificial — **the same job descriptions, the same rules, a
sevenfold difference, entirely from where we drew a line.**

**Now fixed:** we added a fourth era, **"current" (2024 onwards)** — the year footer adoption crosses
50%.

> **One thing you should still rule on.** A date is a *proxy*. Of the JDs dated 2024+, **239 still
> lack the footer**; and **79 that have it predate 2024**. So the era band (1,034 JDs, 61% approval)
> and the true current-practice group (874 JDs, 79% approval) are not the same set — they overlap on
> 795. The gap *is* the rollout still finishing.
>
> **We recommend defining "current" by whether the JD actually carries the footer, rather than by
> its date.** That is the real signal. But it is a judgement about what "current practice" *means*
> at SFU, so it is yours, not ours.

*(Register: HR-109, HR-110, HR-111, HR-122)*

---

## Decision 6 — The quality score itself: **ratify**

| | Setting | Measured effect |
|---|---|---|
| Minimum score to approve | **60 / 100** | Rejects **2** of 874 |
| Minimum grade to approve | **C** | Rejects **2** of 874 |
| Maximum severity allowed | **high** | Rejects 7 of 874 |

These three numbers are **entirely our invention** — SFU publishes no such thresholds. They were the
numbers we were most worried about, precisely because we made them up.

**Your archive vindicated them.** 99.8% of your current JDs clear the score floor of 60.

> **Our recommendation: ratify all three as-is.** Two caveats, so nobody oversells this:
> - The floor is defensible because it is **nearly inert**, *not* because 60 is a magic number. It
>   rejects two job descriptions.
> - If you want a **more demanding** bar later, the data supports raising it — the median current JD
>   now scores **79**, and 82 of them score an A. A floor of 70 would be a real bar rather than a
>   formality. That is a policy choice, not a technical one, and it is yours.

*(Register: HR-001, HR-002, HR-003)*

---

## Decision 7 — ✅ FIXED: a rule that could never *not* fire

`SFU-STRUCT-HOW-WHY` was supposed to check that each duty explains *how* and *why*, not just *what*.
It fired on **100% of the job descriptions the system said were good enough to approve** — all 628
of them.

**It was measuring nothing.** The part of our software that reads a JD **never extracts that
information in the first place**, so the rule reported it "missing" on every duty of every job
description ever written. It was a fixed penalty subtracted from everyone's score — invisible,
because it applied to everyone equally.

**Now retired**, until our reader can actually extract the field. Every score that carried the
penalty went up (8,593 job descriptions); none went down. Your median rose from 77 to **79**.

> **What we need from you:** nothing today. But it is worth knowing that **we cannot currently
> check whether a duty explains "how and why"** — we can only check that the duty exists and starts
> with an action verb. If that check matters to SFU, tell us and we will build the extraction (it
> is scheduled work, not new research).

*(Register: HR-119, HR-121)*

---

## Summary — where each decision stands

**Three were our own defects. We fixed them and re-measured before bringing you this packet.**

| # | Decision | Status | Blocks today |
|---|---|---|---|
| 2 | Qualifications rule scanned the whole document | ✅ **Fixed** — freed 59 JDs | 104 → **0** |
| 7 | "How and why" rule could never *not* fire | ✅ **Fixed** — retired; median 77 → 79 | 0 |
| 5 | Our era model conflated two changeovers | ✅ **Fixed** — 4th "current" era added | *(was a 7× distortion)* |

**Six need your ruling:**

| # | Decision | Our recommendation | Blocks today |
|---|---|---|---|
| 1 | Summary 100–150 words is the **real** gatekeeper | **Ratify** (it's SFU's own number) — but ratify it *knowing* | **134** |
| 1b | Too-short summaries are *not* blocked (340 JDs) | **Leave as-is**, deliberately | 0 |
| 2b | The banned-phrase list now matches only 10 files | **Tell us if it's missing your real phrases** | 0 |
| 3 | "No placeholders" blocks with **no appeal** | **Make it waivable** | 0 now, 29% of archive |
| 4 | Territorial/equity footer blocks 94% of archive | **Auto-insert the boilerplate** instead of penalising | 10 |
| 6 | Score floor 60 / grade C / severity high | **Ratify all three** | **2** |

---

## What happens after you decide

Every item above is a **configuration value**, not code. Once you rule, we change the setting,
re-run the full 14,565-JD baseline, and show you the before/after. Nothing is hard-coded and
nothing requires a rebuild.

The exact change for each possible ruling — which file, which value, what it moves — is written up
in [`POST-REVIEW-CHANGE-PLAN.md`](POST-REVIEW-CHANGE-PLAN.md).

**Until you rule, we change nothing.** Every one of the 119 decisions stays flagged `open`, and
the system's own build fails if anyone quietly edits one without recording it.

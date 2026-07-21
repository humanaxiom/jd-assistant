# JD Bank — Decision Matrix for SFU HR

**Purpose:** everything SFU HR needs in order to sign off on how the JD Bank evaluates a job
description — the system, the process, the evidence, and the specific choices that are yours to make.

**Status:** awaiting HR review. Nothing in this system has been ratified by SFU. Until you rule,
the system's behaviour is provisional and unchanged.

**Evidence base:** every number in this document is measured against the **entire SFU JD archive —
14,565 files** (`docs/baseline/`). It is not a sample.

**You do not need to read any code.** Every decision below is a setting we change in minutes and
re-measure. This document is meant to be read on its own.

---

## 1 · What the system is

The JD Bank reads a job description and does three things:

1. **Reads it into sections** — Summary, Duties, Qualifications, and so on.
2. **Checks it against SFU's JD standards** — a rulebook of gates, word lists and thresholds drawn
   from SFU's JD Toolkit, plus a set of thresholds the Toolkit is silent on (those are the ones this
   document asks you to ratify).
3. **Produces a result** — a **score out of 100**, a **grade A–F**, and a **list of specific
   issues**, then decides **whether an HR reviewer is permitted to approve the JD**.

**The one rule that never bends: the system never approves anything. A human always does.** The
system can *recommend*, and it can *block the approve button*, but publishing a canonical JD is
always a deliberate human act, recorded in an audit log.

### How to read a result

| Element | What it means |
|---|---|
| **Score / 100** | Overall quality. Higher is better. |
| **Grade A–F** | A banded view of the score. |
| **Issues** | Specific, located findings ("Summary is 172 words; the range is 100–150"). |
| **Gates** | A subset of issues that can **block approval**. Most gates can be **overridden** by a reviewer who writes down a reason. A few cannot — see Decision 5. |

---

## 2 · How the process works

A JD moves through the bank in one direction, and a human stands at the only exit:

```
   Archive JD ──▶ Parse into sections ──▶ Check against rulebook ──▶ Score + grade + issues
                                                                              │
                                                                              ▼
                                                              DRAFT canonical JD (never published)
                                                                              │
                                                                    ┌─────────┴─────────┐
                                                                    ▼                   ▼
                                                          HR reviewer approves    edits / rejects
                                                          (gates permit, or       (new draft, or
                                                           override w/ reason)      sent back)
                                                                    │
                                                                    ▼
                                                            PUBLISHED canonical JD
```

Guarantees built into this flow (these are not up for debate — they are the safeguards the decisions
below sit inside):

- **Nothing auto-publishes.** Every canonical JD is a *draft* until a reviewer approves it.
- **Overrides require a written reason.** A reviewer can waive most gates, but the reason is recorded.
- **The audit log is append-only.** Every approve / reject / edit / override is traceable to a person.
- **Every canonical JD traces back to its sources** — which archive JDs fed it, and why content was kept or dropped.
- **All inference runs on SFU-controlled infrastructure.** No JD text is sent to any outside vendor.

---

## 3 · What we measured

The purpose of the baseline run was to put the proposed approval bar on trial against SFU's real
job descriptions — and to find out whether it is reasonable or too harsh.

### Read the right population

The archive spans decades and **two different JD templates**. Three figures matter, and only one of
them is a fair test of the bar:

| Population | Size | Approval | What it actually measures |
|---|---:|---:|---|
| Whole archive | 14,522 scored | ~5% | **Not meaningful.** Mixes 1990s JDs and a second template (WJQ/CUPE) that has no SFU rulebook bar at all. Do not quote. |
| JDs dated 2024+ | 1,034 | 61% | A *date* band — still partly measuring a rollout, not quality. |
| **Current practice** | **874** | **78.6%** | **The fair trial** — the JDs SFU writes today, under today's template and conventions. |

> **The WJQ/CUPE template (4,300 files, 29% of the archive)** is a *different form* with no rulebook
> bar defined. The system reads it, but does **not** score it against the JDFN gates — doing so would
> be a category error. It is excluded from every approval number above. (See Decision 7 area if SFU
> wants a bar built for it.)

### The headline: the bar is sound, and barely binding

On the 874 JDs SFU writes today:

| | |
|---|---|
| **Would be approvable** | **687 — 78.6%** |
| Median quality score | **79 / 100** |
| Grade spread | **81 A · 551 B · 240 C · 2 D · 0 F** |
| Clear the score floor of 60 | **99.8%** |
| Rejected because their score was too low | **2** |

Nearly eight in ten current JDs would pass straight through. The rest need **edits, not rewrites**.
**No current JD scores an F.**

### What actually blocks a JD

This is the single most important finding for HR, because it is **not** what most people assume.
Of the 187 current JDs that cannot yet be approved, here is what stops them:

| What blocks it | JDs | |
|---|---:|---|
| **Summary is outside 100–150 words** | **134** | ← the real gatekeeper |
| Missing "or an equivalent combination of education and experience" | 42 | |
| Missing part of the territorial / equity footer | 10 | |
| Summary describes working conditions, not the role | 9 | |
| Missing a mandatory section | 7 | |
| Severity of an issue too high | 7 | |
| **The quality score itself being too low** | **2** | |
| Grade too low | 2 | |
| Qualifications listed out of order | 1 | |

**The thing doing the real gatekeeping is a word count, not the quality score.** The quality score
rejects two JDs out of 874 — it is almost inert. That is not a flaw, but HR should ratify the bar
*knowing* this, not assuming the score is what protects quality. (Decisions 1 and 3 both turn on it.)

---

## 4 · The decision matrix

Seven decisions need SFU HR. Each is a **setting**, not a code change. Three kinds of ask appear:

- 🟢 **Ratify** — we recommend keeping it; we need you to *own* it knowingly.
- 🔵 **Choose** — a genuine policy fork; pick an option.
- 🟣 **Review** — needs an experienced JD reviewer's eye, not an engineer's.

| # | Decision | Type | Current | Our recommendation | If unchanged, affects | Your ruling |
|---|---|---|---|---|---|---|
| **1** | Summary must be **100–150 words** | 🟢 Ratify | 100–150 (SFU's own number) | **Ratify** — but knowing it is the #1 determinant of approval | Blocks **134** of 874 | ☐ |
| **2** | Too-**short** summaries are **not** blocked (only too-long) | 🔵 Choose | Asymmetric: long blocks, short only costs score | **Keep asymmetric** | Enforcing symmetry would block **340** (≈40% approval) | ☐ |
| **3** | Minimum quality bar: **score ≥ 60 · grade ≥ C · severity ≤ high** | 🟢 Ratify | 60 / C / high | **Ratify** (rejects 2 of 874); note 70 is available if SFU wants a real bar | Rejects **2** on score | ☐ |
| **4** | Territorial + Employment-Equity **footer** is mandatory | 🔵 Choose | Blocks any JD lacking it (94% of archive; a rollout artifact) | **Auto-insert** the footer at compose time instead of penalising omission | Blocks **10** current; ~13,000 legacy | ☐ |
| **5** | The **"placeholder" gate** blocks with **no appeal** | 🔵 Choose | Non-overridable — no waiver, ever | **Make it waivable** with a written reason | 0 current; 29% of legacy archive | ☐ |
| **6** | The **wish-list-language** ("may include", "an asset") word list | 🟣 Review | Matches only **10** files archive-wide | **A JD reviewer confirms the list is complete** | Guard-rail that almost never fires | ☐ |
| **7** | Should the wish-list gate be **overridable**? | 🔵 Choose | Overridable | **Confirm on purpose** (we default to keeping it waivable) | — | ☐ |

Details for each follow.

---

### Decision 1 — Ratify the 100–150 word summary range 🟢

**The question:** SFU's Toolkit says a Position Summary should be 100–150 words. We enforce that as a
gate. Do you ratify it?

**What you need to know before you do:** this single rule is **the largest determinant of whether a
JD is approvable** — it blocks 134 of the 187 current JDs that fail. It is not a formatting nicety;
it is the operative bar. The saving grace is that **100–150 is SFU's own published number**, not one
we invented.

**Recommendation: ratify as-is**, with eyes open. If you'd rather widen it (e.g. 100–200), we change
one value and re-measure — expect the 134 blocks to fall sharply.

---

### Decision 2 — Keep the short-summary asymmetry 🔵

**The question:** today, a summary that is **too long** is blocked, but one that is **too short** only
loses points — it is not blocked. The Toolkit's range is two-sided; our enforcement is one-sided.
Make it symmetric?

**What you need to know:** **340 of 874** current JDs have summaries that are *too short*. If we
blocked those too "for consistency," the under-run would instantly become **the single biggest
blocker in the system**, and approval would fall from ~79% to roughly **40%**.

**Recommendation: keep it as-is, deliberately.** We flag it only so the asymmetry is a decision you
made, not an accident. If you do want symmetry, we will show you the ~40% figure first and have you
ratify *that number*, not the principle.

---

### Decision 3 — Ratify the minimum quality bar 🟢

**The question:** a JD cannot be approved if its score is below **60**, its grade below **C**, or it
carries an issue of severity above **high**. These three thresholds are ours — SFU publishes no such
numbers. Ratify them?

**What the archive says:** they are nearly inert on current practice. 99.8% of today's JDs clear the
score floor; **it rejects two.** The bar survived its trial against real data.

**Recommendation: ratify all three.** Two honest caveats:

- The floor of 60 is defensible because it is **nearly inert**, not because 60 is a magic number.
- If SFU wants a **more demanding** bar later, the data supports it: the median current JD scores
  **79**, and 81 score an A. **A floor of 70 would be a real bar** rather than a formality. That is a
  policy choice, and it is cheap to make — one value and a re-measure. We are not recommending it,
  only telling you the option is there.

---

### Decision 4 — How to handle the territorial / equity footer 🔵

**The finding:** the mandated territorial acknowledgement and Employment-Equity statement are
required by the rulebook. **94% of the archive lacks them** — but this is **not** a quality problem.
SFU only began putting the acknowledgement into JDs around 2023:

| Year | JDs carrying the acknowledgement |
|---|---|
| 2019 | 0.2% |
| 2023 | 11% |
| 2024 | 63% |
| 2025 | 85% |
| 2026 | 89% |

So the rule is really detecting **a document's age**, not its quality. Staff did nothing wrong; the
paragraph simply did not exist yet. The gate *can* be waived — but on the legacy archive that means a
reviewer writing an individual justification roughly **13,000 times**.

**Choose one:**

- **(a)** Accept as-is. Old JDs stay blocked until someone adds the paragraph. *(Honest, but makes the
  historical archive practically unusable without ~13,000 waivers.)*
- **(b) [recommended]** Treat the footer as **boilerplate the system inserts automatically** when a JD
  is composed, rather than something the author is penalised for omitting. It is identical on every
  JD. *(Note: if we generate the wording, HR must give us the current official text to insert.)*
- **(c)** Apply the rule only to JDs written after a date you choose.

**Recommendation: (b).**

---

### Decision 5 — Make the "placeholder" gate appealable 🔵

**The finding:** most gates can be waived by a reviewer with a written reason. **Two cannot** — a JD
that trips them is permanently un-approvable, with no human override. One of those two is
demonstrably wrong.

The placeholder gate treats the phrases **"action verb," "how and why,"** and **"what by"** as
evidence that template boilerplate was left in the document. But a JD that legitimately *discusses*
action verbs — as a **Communications or HR training role might** — is then permanently un-approvable,
and no reviewer who can see the JD is fine has any way to say so.

Good news: it blocks **zero** current JDs. It is a legacy-archive problem (29% of old files), not a
threat to what SFU writes today.

**Recommendation: remove the placeholder gate from the no-appeal list.** Keep the rule — it does
catch real leftover template text — but let a reviewer waive it with a written reason. Removing human
discretion is only defensible when a rule is *never* wrong, and this one provably is. *(The other
no-appeal gate — "a mandatory section is missing" — is defensible and we recommend leaving it.)*

---

### Decision 6 — Review the wish-list-language word list 🟣

**The question:** the rulebook blocks "wish-list" phrasing in Qualifications — words like *"may
include"* or *"an asset"* that quietly turn a minimum requirement into a nice-to-have. Correctly
scoped to the Qualifications section, that list now matches **only 10 files in the entire archive.**

That leaves one open question that **an engineer cannot answer**: is the list a guard-rail that
authors rarely trip — or is it **missing the phrases SFU's authors actually write?**

**Recommendation: a few minutes of an experienced JD reviewer's time** to look at the list and tell
us whether it captures the wish-list language you see in practice. If it's missing phrases, we add
them.

---

### Decision 7 — Confirm the wish-list gate's override status 🔵

**The question:** the wish-list gate is currently **overridable** (a reviewer can waive it). We would
like you to confirm that on purpose rather than inherit it.

**Recommendation: keep it overridable** unless SFU considers wish-list phrasing a hard stop, in which
case we make it non-appealable. This is a small policy call bundled here so it isn't decided by
default.

---

## 5 · Recording your decisions, and what happens next

Every decision above is a **configuration value**. Once you rule:

1. We change the setting.
2. We **re-run the full 14,565-JD baseline** and show you the before/after — no decision lands on an
   estimate.
3. We record your ruling in the decision register with **who** decided, **when**, and **the reason** —
   the system will not accept a ratification without all three. That is how an HR ruling becomes part
   of the rulebook's provenance.

**A decision is recorded even when you keep a setting unchanged.** "HR reviewed this and kept it" is a
different, stronger fact than "nobody has looked yet" — and every one of the ~119 settings in the
rulebook currently sits at the second.

The seven above are the ones that **matter to the numbers**. The remaining ~110 settings are recorded
in [`HR-DECISION-REGISTER.md`](HR-DECISION-REGISTER.md); the archive shows they change almost nothing,
so they can be ratified in bulk or reviewed at your leisure.

**Until you rule, we change nothing.** The engineering counterpart to this document — exactly which
file and value each ruling moves — is in [`POST-REVIEW-CHANGE-PLAN.md`](POST-REVIEW-CHANGE-PLAN.md).

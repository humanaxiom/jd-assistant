# JD Bank — HR Review & Decision Matrix

**For:** SFU Human Resources.
**Purpose:** everything HR needs to sign off on how the JD Bank evaluates a job description — what
the system is, how it works, what we measured against your real job descriptions, and the specific
settings that are yours to rule on. This document is self-contained; **you do not need to read any
code**, and every decision below is a setting we change in minutes and re-measure.

**Status:** *awaiting HR review — nothing in this system has been ratified by SFU.* Until you rule,
the system's behaviour is provisional and unchanged.
**Last verified against the live system: 11 August 2026.**

> ⚠️ **`docs/HR-DECISION-MATRIX.pdf` is a manual export dated 31 July 2026 and is now out of
> date** — it predates the corrections below. Re-export it from this file before sending anything
> to HR, or delete it. **This Markdown file is the source of truth.**

**Evidence base:** every number here is measured against the **entire SFU job-description archive —
14,565 files.** It is not a sample.

> **What has changed since this document was first circulated (30 July 2026)**
>
> - **The headline numbers below are unchanged, and that was worth checking.** We fixed a
>   significant reading defect in August — the tool had been missing the identification block
>   (title, department, employee group, grade) on about half of all modern job descriptions,
>   because the SFU template keeps it in the document *header*, which our reader skipped. We
>   re-measured the entire archive afterwards. **The 874-JD result did not move** — because that
>   defect affected the identification fields, not the written content the quality bar actually
>   scores. Your ratification is being asked for on the same numbers as before.
> - **We can now read pay grades out of the documents** — 3,049 of them. That opens a new question
>   which is *not* one of the eight below; it is tracked separately (see the end of Part 4).
> - **Sign-in is now SFU single sign-on with proper roles**, and the pilot in Part 5 has been
>   updated accordingly.
> - **The settings count moved from 194 to 197.** No new rule was added to the approval bar; the
>   three additions govern an advisory feature in the authoring tool.
> - **The full settings register now says which settings are actually yours.** Feedback on the
>   first circulation was that the companion register
>   (`docs/decisions/HR-DECISION-REGISTER.md`) reads as an undifferentiated list of 197 items, so
>   it is impossible to tell a question about the approval bar from a search-index timeout. Every
>   entry now carries an audience, and the register leads with a section called **"Your
>   decisions"**: **65 settings change whether a job description passes** and are yours to rule
>   on; 49 shape what a reviewer *sees* without deciding anything; 83 are engineering settings you
>   should never be asked about. **Nothing was removed** — the same build check still covers all
>   197, so none of them can change quietly. **This does not change the ask in Part 4:** the eight
>   settings below are still what we need from you now, and the 65 are the wider set behind them.

**We are asking you for two things:**

1. **Rule on eight settings** (Part 4) that decide whether a job description can be approved.
2. **Do a short hands-on pilot** (Part 5) — walk a handful of real job descriptions through the
   tool the way a reviewer would, and tell us where it got the call wrong.

Together this is how the JD Bank moves from *built* to *trusted*. Budget about 60–90 minutes.

---

## 1 · What the system is

The JD Bank is a tool that helps SFU **standardise, quality-check, and author** APSA / APEX /
Polytechnic job descriptions against SFU's own JD standards. It does three jobs:

1. **Reads a job description into its sections** — Position Summary, Duties, Qualifications, and so on.
2. **Checks it against SFU's JD standards** — a rulebook of gates, word lists and thresholds. The
   parts SFU has published come from the **SFU JD Toolkit** and the official **APSA/APEX/POLY job
   description template**; the parts the Toolkit is silent on are settings we chose (and this
   document asks you to ratify the ones that matter).
3. **Produces a result** — a **score out of 100**, a **grade A–F**, a **list of specific, located
   issues**, and a decision on **whether an HR reviewer is permitted to approve the job description.**

It supports two ways of producing a job description, both ending at the same human-approval gate:

- **Harmonising the archive** — where several near-duplicate job descriptions describe the same role,
  the tool merges them into one clean **draft** canonical job description and shows exactly what each
  source contributed and what was dropped.
- **Authoring a new one** — a hiring manager or recruiter answers a guided set of questions (or starts
  from an existing role) and sees the JD scored live against SFU standards as they write.

> **The one rule that never bends: the system never approves anything — a human always does.** The
> tool can *recommend*, and it can *block the approve button*, but publishing a job description is
> always a deliberate human act, recorded in an audit log.

### Where the numbers in the rulebook come from

To evaluate a job description the system uses **197 settings** — numbers, word lists and rules.

| Source | Count | What it means |
|---|---:|---|
| **SFU's own JD Toolkit** | **19** | Published SFU standards (e.g. the 100–150-word Position Summary range). |
| **Our choices** | **178** | Settings we had to pick because the Toolkit does not specify them. |

**That 197 overstates what is actually yours to decide, and we would rather say so than let the
number do the arguing.** Most of it governs machinery — how duplicates are detected, how roles are
clustered, how the search index is tuned. Nearly a third sits in one comparison component that the
system itself labels as *not* a classification decision. Asking HR to ratify a search setting would
waste your time and dilute the decisions that matter.

**Roughly 60 of the 197 genuinely touch whether a job description passes.** The eight in Part 4 are
the ones that decide it today, on the evidence of the archive; the rest of that ~60 change almost
nothing measurable and can be ratified in bulk or at your leisure. We are separating the register
into *policy* and *engineering* tiers so that a future version of this document asks you about ~60
things and never about the other ~137.

### How to read a result

| Element | What it means |
|---|---|
| **Score / 100** | Overall quality. Higher is better. |
| **Grade A–F** | A banded view of the score. |
| **Issues** | Specific, located findings — e.g. "Summary is 172 words; the range is 100–150." |
| **Gates** | The subset of issues that can **block approval**. Most gates can be **overridden** by a reviewer who writes down a reason; a few cannot (see Decision 5). |

---

## 2 · How the process works

A job description moves through the bank in one direction, and a human stands at the only exit:

```
   Archive JDs ─┐
                ├─▶ Parse into sections ─▶ Check against rulebook ─▶ Score + grade + issues
   New JD  ─────┘                                                             │
   (Builder)                                                                  ▼
                                                          DRAFT canonical JD (never published)
                                                                             │
                                                                   ┌─────────┴─────────┐
                                                                   ▼                   ▼
                                                         HR reviewer approves     edits / rejects
                                                         (gates permit, or        (new draft, or
                                                          override with reason)    sent back)
                                                                   │
                                                                   ▼
                                                           PUBLISHED canonical JD
```

Five guarantees are built into this flow. They are **not** up for debate — they are the safeguards
the decisions in Part 4 sit inside:

- **Nothing auto-publishes.** Every canonical job description is a *draft* until a reviewer approves it.
- **Overrides require a written reason.** A reviewer can waive most gates, but the reason is recorded.
- **The audit log is append-only.** Every approve / reject / edit / override, and every sign-in, is
  traceable to a person and cannot be altered after the fact.
- **Every canonical job description traces back to its sources** — which archive JDs fed it, and why
  content was kept or dropped.
- **All processing runs on SFU-controlled infrastructure.** No job-description text is sent to any
  outside vendor.

---

## 3 · What we measured

The point of the baseline run was to put the proposed approval bar on trial against SFU's **real**
job descriptions — and find out whether it is reasonable or too harsh.

### Read the right population

The archive spans decades and **two different job-description forms**. Three figures matter, and only
one is a fair test of the bar:

| Population | Size | Approvable | What it actually measures |
|---|---:|---:|---|
| Whole archive | 14,522 scored | ~5% | **Not meaningful — do not quote.** Mixes 1990s JDs and a second form (the CUPE Weighted Job Questionnaire) that has no SFU quality bar at all. |
| JDs dated 2024+ | 1,034 | 61% | A *date* band — still partly measuring a rollout, not quality. |
| **Current practice** | **874** | **78.6%** | **The fair trial** — the job descriptions SFU writes today, under today's template and conventions. |

> **The CUPE form (4,300 files, ~30% of the archive)** is the Weighted Job Questionnaire — a
> *different instrument* with no SFU quality bar defined. The tool reads it, but does **not** score it
> against the APSA/APEX/Polytechnic rules; doing so would be a category error. It is excluded from
> every approval figure above. Decision 8 asks you to confirm this scope.

### The headline: the bar is sound, and barely binding

On the 874 job descriptions SFU writes today:

| | |
|---|---|
| **Would be approvable** | **687 — 78.6%** |
| Median quality score | **79 / 100** |
| Grade spread | **81 A · 551 B · 240 C · 2 D · 0 F** |
| Clear the score floor of 60 | **99.8%** |
| Rejected because their score was too low | **2** |

Nearly eight in ten current job descriptions would pass straight through. The rest need **edits, not
rewrites.** **No current job description scores an F.**

### What actually blocks a job description

This is the single most important finding for HR, because it is **not** what most people assume. Of
the 187 current job descriptions that cannot yet be approved, here is what stops them:

| What blocks it | JDs | |
|---|---:|---|
| **Position Summary is outside 100–150 words** | **134** | ← the real gatekeeper |
| Missing "or an equivalent combination of education and experience" | 42 | |
| Missing part of the territorial / equity footer | 10 | |
| Summary describes working conditions, not the role | 9 | |
| Missing a mandatory section | 7 | |
| An issue's severity is too high | 7 | |
| **The quality score itself being too low** | **2** | |
| Grade too low | 2 | |
| Qualifications listed out of order | 1 | |

**The thing doing the real gatekeeping is a word count, not the quality score.** The quality score
rejects two job descriptions out of 874 — it is almost inert. That is not a flaw, but HR should
ratify the bar *knowing* it, not assuming the score is what protects quality. (Decisions 1 and 3 both
turn on this.)

---

## 4 · The decisions

### First — three things we already corrected, so you are reading honest numbers

The first version of this review exposed **three defects in our own rules.** We fixed them and
re-measured **before** bringing you this document — handing you figures we already knew were
distorted, collecting your sign-off, and *then* fixing them would have made your ratification
meaningless. **No action is needed on these three; they are here so you know why the numbers look the
way they do.**

| Was | What it was | Now |
|---|---|---|
| A qualifications rule scanned the **whole document** | It blocked 104 JDs for "wish-list" phrasing found anywhere — even a duty that said "responsibilities *may include*…" | Scoped correctly to the Qualifications section: **104 → 0** wrong blocks; **59 JDs** became approvable. This is the entire improvement from 71.9% to 78.6%. |
| A "how and why" rule that **could never *not* fire** | It penalised every duty of every JD for missing detail the reader never extracts — an invisible constant subtracted from every score | Retired until the reader can extract that field. Median score rose **77 → 79**; **no** approval changed (it only affected scores, not the pass/fail line). |
| Our "era" model **conflated two rollouts** | It judged correctly-written 2019 JDs by a footer rule only 2023+ JDs could satisfy — a sevenfold distortion, all date and no quality | Added a fourth "current" band from 2024. The 78.6% figure is measured on the corrected model. |

### Now — the eight settings that need your ruling

Each is a **setting**, not a code change. Three kinds of ask appear:

- 🟢 **Ratify** — we recommend keeping it; we need you to *own* it knowingly.
- 🔵 **Choose** — a genuine policy fork; pick an option.
- 🟣 **Review** — needs an experienced JD reviewer's eye, not an engineer's.

| # | Decision | Type | Our recommendation | Blocks today | Your ruling |
|---|---|---|---|---:|---|
| **1** | Position Summary must be **100–150 words** | 🟢 Ratify | Ratify — it's SFU's own number, but know it is the #1 determinant of approval | **134** | ☐ |
| **2** | Too-**short** summaries are **not** blocked (only too-long) | 🔵 Choose | Keep the asymmetry, deliberately | 0 | ☐ |
| **3** | Minimum bar: **score ≥ 60 · grade ≥ C · severity ≤ high** | 🟢 Ratify | Ratify all three (they reject 2 of 874); 70 is available if you want a real bar | **2** | ☐ |
| **4** | Territorial + Employment-Equity **footer** is mandatory | 🔵 Choose | Auto-insert the footer at compose time instead of penalising omission | 10 | ☐ |
| **5** | The **"placeholder" gate** blocks with **no appeal** | 🔵 Choose | Make it waivable with a written reason | 0 | ☐ |
| **6** | The **wish-list-language** word list ("may include", "an asset") | 🟣 Review | A JD reviewer confirms the list is complete | 0 | ☐ |
| **7** | Should the wish-list gate be **overridable**? | 🔵 Choose | Confirm it stays waivable (decide on purpose) | 0 | ☐ |
| **8** | **Scope:** the tool scores/authors only APSA/APEX/Poly, **not CUPE** (~30% of the archive) | 🔵 Choose | Confirm APSA/APEX/Poly-only for now, or commission a CUPE bar (a separate project) | n/a | ☐ |

Details for each follow.

---

### Decision 1 — Ratify the 100–150-word summary range 🟢

**The question:** SFU's Toolkit says a Position Summary should be 100–150 words. We enforce that as a
gate. Do you ratify it?

**What you need to know first:** this single rule is **the largest determinant of whether a job
description is approvable** — it blocks 134 of the 187 current JDs that fail. It is not a formatting
nicety; it is the operative bar. The saving grace is that **100–150 is SFU's own published number.**

**Recommendation: ratify as-is, with eyes open.** If you'd rather widen it (e.g. 100–200), we change
one value and re-measure — expect the 134 blocks to fall sharply.

---

### Decision 2 — Keep the short-summary asymmetry 🔵

**The question:** today a summary that is **too long** is blocked, but one that is **too short** only
loses points — it is not blocked. The Toolkit's range is two-sided; our enforcement is one-sided.
Make it symmetric?

**What you need to know:** **340 of 874** current job descriptions have summaries that are *too
short*. If we blocked those too "for consistency," the under-run would instantly become **the single
biggest blocker in the system**, and approval would fall from ~79% to roughly **40%.**

**Recommendation: keep it as-is, deliberately.** We flag it only so the asymmetry is a decision you
made, not an accident. If you do want symmetry, we will show you the ~40% figure first and have you
ratify *that number*, not the principle.

---

### Decision 3 — Ratify the minimum quality bar 🟢

**The question:** a job description cannot be approved if its score is below **60**, its grade below
**C**, or it carries an issue of severity above **high**. These three thresholds are ours — SFU
publishes no such numbers. Ratify them?

**What the archive says:** they are nearly inert on current practice. 99.8% of today's JDs clear the
score floor; **it rejects two.** The bar survived its trial against real data.

**Recommendation: ratify all three.** Two honest caveats:

- The floor of 60 is defensible because it is **nearly inert**, not because 60 is a magic number.
- If SFU wants a **more demanding** bar later, the data supports it: the median current JD scores
  **79**, and 81 score an A. **A floor of 70 would be a real bar** rather than a formality. That is a
  policy choice, cheap to make — one value and a re-measure. We are not recommending it, only telling
  you the option is there.

---

### Decision 4 — How to handle the territorial / equity footer 🔵

**The finding:** the mandated territorial acknowledgement and Employment-Equity statement are
required by the rulebook. **94% of the archive lacks them** — but this is **not** a quality problem.
SFU only began putting the acknowledgement into job descriptions around 2023:

| Year | JDs carrying the acknowledgement |
|---|---|
| 2019 | 0.2% |
| 2023 | 11% |
| 2024 | 63% |
| 2025 | 85% |
| 2026 | 89% |

So the rule is really detecting **a document's age**, not its quality. Staff did nothing wrong; the
paragraph simply did not exist yet. The gate *can* be waived — but on the legacy archive that means a
reviewer writing an individual justification roughly **13,000 times.**

**Choose one:**

- **(a)** Accept as-is. Old JDs stay blocked until someone adds the paragraph. *(Honest, but makes the
  historical archive practically unusable without ~13,000 waivers.)*
- **(b) [recommended]** Treat the footer as **boilerplate the system inserts automatically** when a JD
  is composed, rather than something the author is penalised for omitting. It is identical on every
  JD. *(If we generate the wording, HR must give us the current official text to insert.)*
- **(c)** Apply the rule only to JDs written after a date you choose.

**Recommendation: (b).**

> **A related refinement, if you want it:** we currently call a JD "current practice" by its *date*
> (2024+). The truer signal is whether it actually *carries the footer*. The two nearly agree, and
> either is defensible — this is a definitional call about what "current practice" means at SFU, and
> it is yours. Not required to proceed.

---

### Decision 5 — Make the "placeholder" gate appealable 🔵

**The finding:** most gates can be waived by a reviewer with a written reason. **Two cannot** — a job
description that trips them is permanently un-approvable, with no human override. One of those two is
demonstrably wrong.

The placeholder gate treats the phrases **"action verb," "how and why,"** and **"what by"** as
evidence that template boilerplate was left in the document. But a job description that legitimately
*discusses* action verbs — as a **Communications or HR training role might** — is then permanently
un-approvable, and no reviewer who can see the JD is fine has any way to say so.

Good news: it blocks **zero** current job descriptions. It is a legacy-archive issue (29% of old
files), not a threat to what SFU writes today.

**Recommendation: remove the placeholder gate from the no-appeal list.** Keep the rule — it does catch
real leftover template text — but let a reviewer waive it with a written reason. Removing human
discretion is only defensible when a rule is *never* wrong, and this one provably is. *(The other
no-appeal gate — "a mandatory section is missing" — is defensible; we recommend leaving it.)*

---

### Decision 6 — Review the wish-list-language word list 🟣

**The question:** the rulebook blocks "wish-list" phrasing in Qualifications — words like *"may
include"* or *"an asset"* that quietly turn a minimum requirement into a nice-to-have. Correctly
scoped to the Qualifications section, that list now matches **only 10 files in the entire archive.**

That leaves one question **an engineer cannot answer**: is the list a guard-rail authors rarely trip —
or is it **missing the phrases SFU's authors actually write?**

**Recommendation: a few minutes of an experienced JD reviewer's time** to look at the list and tell us
whether it captures the wish-list language you see in practice. If it's missing phrases, we add them.

---

### Decision 7 — Confirm the wish-list gate's override status 🔵

**The question:** the wish-list gate is currently **overridable** (a reviewer can waive it). We would
like you to confirm that on purpose rather than inherit it.

**Recommendation: keep it overridable** unless SFU considers wish-list phrasing a hard stop, in which
case we make it non-appealable. A small policy call, bundled here so it isn't decided by default.

---

### Decision 8 — Confirm the scope: APSA/APEX/Poly only, not CUPE 🔵

**The finding:** everything above is measured on job descriptions written on SFU's **APSA/APEX/Poly
template.** **CUPE roles use a different form — the Weighted Job Questionnaire (WJQ)** — and they are
**4,440 of your 14,565 files (30.6%).** The tool *reads* them, but does **not** score them and will
**not** author them.

> **One caveat we owe you, because it changes how precisely we can state this boundary.** Of the
> whole archive, we can currently identify the employee group for about two thirds:
> **37% APSA/APEX/Poly · 31% CUPE · 32% we cannot yet classify.** That last third is **our gap, not
> a question for you** — those documents simply do not state their group in a way our reader has
> recovered yet, and we are fixing it. It does not affect the measured results above, which are
> drawn from job descriptions whose group *is* known. But it does mean that when we say "the Bank
> serves roughly 70% of the archive", the honest version is "the Bank serves everything on the
> APSA/APEX/Poly template, and we are still improving our ability to tell you exactly how many
> documents that is."

This is deliberate, not an oversight:

- The whole quality bar in this document was built from SFU's APSA/APEX/Poly standard. **There is no
  CUPE quality standard encoded** — the Toolkit does not define one for the WJQ form.
- Scoring a CUPE job description against these rules would be a **category error** — a number that
  looks like a quality grade but really measures "how much does this CUPE role resemble an
  APSA/APEX/Poly one." That is worse than no number.

**Choose one:**

- **(a) [recommended, for now]** Confirm the Bank is **APSA/APEX/Poly-only.** CUPE JDs remain
  readable/searchable but are neither scored nor authored, and this document's numbers cover ~70% of
  the archive **by design**, honestly labelled.
- **(b)** Commission a **CUPE quality bar** — a WJQ ruleset with its own thresholds and sign-off. That
  is a **separate project**: it needs SFU to define what "good" means for a WJQ role before we can
  build a checker for it. Once that exists, CUPE switches on with one setting.

Either way, decide it **on purpose** rather than inherit "the Bank ignores a third of SFU roles" as an
accident of which template we started with.

---

### Also open, and tracked separately — pay grade

**Not one of the eight**, because it is newer than this document and does not affect whether a job
description can be approved. Raised here so it is not a surprise.

The tool now reads the pay grade straight out of the document wherever one is stated — **3,049 job
descriptions: 2,322 CUPE, 687 APSA, 34 APEX.** *(An earlier version of our analysis said APSA
grades were essentially never recorded in the JD. That was wrong — it was the same header-reading
defect described at the top of this document, and it is corrected.)*

Two things we need, in `grade-scales-hr-ask.md`:

1. **The valid grade values for each employee group.** We can read grades but cannot tell a correct
   value from a typo, so grade entry is an unchecked free-text box. This is a fifteen-minute answer.
2. **Where grade comes from for the 11,473 job descriptions that state none.** There is no separate
   system holding them, so this is a question of method. Our suggestion: you supply the valid
   values, the reviewer sets the grade when they approve, and you spot-check a sample of the 3,049
   we already read — an afternoon of your time, and a fifth of the archive arrives already graded.

---

## 5 · Walk the system (the hands-on pilot)

**Where to go:** your JD Bank operator will confirm the address. Type it in full and bookmark it —
the system does not have a front page yet, so the bare hostname will show you an error rather than
the tool. **Sign in with your SFU account** (single sign-on); your operator will confirm you have
the **reviewer** role. Once in, use the navigation bar at the top.

**Start by reading, not reviewing.** Open **🏦 JD Bank** first and spend five minutes in the
library — search for a role you know, open it, and look at the source job descriptions it was
distilled from. If the harmonised version of a role you know well is wrong, that is worth more to
us than any number in Part 3.

Then exercise a reviewer's judgement on a handful of drafts:

1. **Open 📋 Review queue.** You'll see the drafts awaiting review, most-blocked first, each with its
   score and how many gates block it. Pick one to open.
2. **Read the draft page.** At the top: the **score, grade,** and whether it's *approvable* or how many
   gates block it. Below: the **blocking gates** (each says what tripped and whether it can be waived),
   the **draft text**, and a **"removed content" list** (what the tool folded out when it merged
   duplicate JDs, and why).
3. **Click "Changes since last approved version →."** If this role was approved before, you'll see a
   side-by-side of what changed. (First-time drafts say "no prior approved version" — expected.)
4. **Make a decision** on a few drafts, trying each action at least once:
   - **Approve** — if a gate is *waivable*, you'll be asked to type a reason before it lets you. A
     draft with a non-waivable blocking gate cannot be approved (by design).
   - **Reject** — requires a written reason.
   - **Edit** — change any field (title, summary, duties, qualifications, the footer flags…) and Save.
     This is a structured, field-by-field editor — no raw data. Saving creates a **new draft version**
     for review; it does **not** publish.
5. **Try editing an already-approved job description.** Open a published one and use *Propose an
   update.* This mints a **new draft** while **the approved version stays live** — a role is never
   left without an approved JD during the review window, and the old version retires only when its
   replacement is approved. Worth confirming that matches how you expect revisions to work.
6. **(Optional) Try 🧱 Builder.** Author a brand-new JD from the guided questions (or search an
   existing one and clone it), press **Check compliance**, and watch the live panel score it as you
   go. Once you've written a summary, a **"Roles SFU already has"** panel appears — the existing
   roles that look like the one you're writing, so nobody creates a tenth near-copy of a role that
   exists. It is advisory and never blocks you. Submit and it lands in the same review queue.
7. **Keep a short list as you go:** any JD where you *disagreed* with the tool — it blocked something
   fine, or passed something you'd reject. **That list is the most valuable thing you produce.**

> **Two things you may hit, neither of which is a fault in your work.** If a page you left open for
> a while says **"Forbidden"** when you submit, reload it and redo the action — a security control
> added in August expires idle pages. And a small number of roles still show a **whole sentence as
> their title** instead of a job title; that is a known reading defect on older documents, about
> one role in twenty-five, and it is on our list.

*(📊 Dashboards and 📖 Guide are there for context — the dashboards summarise the archive; the guide
is the full operator manual. Neither is required for this review.)*

---

## 6 · Recording your decisions, and what happens next

**What we need back:**

- **Your eight rulings** (Part 4) — keep or change, in a sentence each.
- **Your pilot notes** (Part 5) — which drafts you approved / rejected, and every case where you
  disagreed with the tool's call.

**What we do with them:**

1. We change the setting.
2. We **re-run the full 14,565-JD baseline** and show you the before/after — no decision lands on an
   estimate.
3. We record your ruling with **who** decided, **when**, and **the reason.** The system will not accept
   a ratification without all three — that is how an HR ruling becomes part of the rulebook's
   permanent provenance, and it cannot be recorded anonymously.
4. Every disagreement from your pilot becomes a **permanent test case**, so the tool never makes that
   mistake again.

**A decision is recorded even when you keep a setting unchanged.** "HR reviewed this and kept it" is a
different, stronger fact than "nobody has looked yet" — and every one of the 197 settings currently
sits at the second.

**Where we actually are:** **four** job descriptions have been approved through this system, by us,
as a test that the machinery works end to end. **No experienced reviewer has yet driven it.** That
is precisely what Part 5 is for, and it is the single thing most worth your time — the engineering
is built and measured; what it has never had is a professional's judgement applied to it.

**Until you rule, we change nothing.**

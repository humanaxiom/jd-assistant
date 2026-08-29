# Findings — everything we have measured about this archive

**One place for every measured claim.** Written 2026-08-28, consolidating eight separate
plan documents that had scattered the same numbers across ten files.

---

## 🔴 Where numbers are allowed to live

This project has repeatedly shipped wrong numbers that were **consistent across several
documents** — which is exactly why nobody caught them. Agreement between documents that
share one unchecked source is a *correlated* failure, not corroboration.

So, three places, and no others:

| what | where | authority |
|---|---|---|
| **Live counts** (documents, roles, approvable, the gap) | **`/jd-bank/ui/funnel`** | 🥇 **The system itself.** Computed from the database at request time. |
| **Measured findings** (this file) | `docs/FINDINGS.md` | Dated snapshots with the query that produced them. |
| **What we intend to do** | `docs/plan.md`, `HANDOFF.md` | Forward-looking only. **They must not restate a count** — they link here or to the page. |

**If a number appears in a fourth place, delete it.** The full working for each finding is
in `docs/archive/plans/`, kept for the reasoning, not as a source of numbers.

---

## 0. Check it yourself — do not take this file's word

```
make smoke
```

One command against the LIVE Bank: every document is unreadable, behind a role, or in a
named gap bucket (exactly); the gap buckets sum; collection membership is a true union of
its signals; and a random sample of documents is findable by exact filename in the
archive browser. **If any single document is unaccounted for, it fails.** The seeded
twin of the same chain runs inside `make gates`
(`tests/integration/test_smoke_end_to_end.py`).

## 1. The archive, end to end

**⚠ The live page is authoritative. These are the values on 2026-08-28.**

```
14,565  documents in the archive
    43  ├─ could not be parsed at all
14,522  └─ parsed
10,869    ├─ behind a role          → became the 2,493 roles
 3,653    └─ never reached a role   → see §2
 2,493  roles
 1,299  roles passing every gate today
     4  roles published right now
```

⚠ **Documents and roles are different units.** A reader following 14,565 → 2,493 → 129 will
take the last for documents; it is a count of *roles* in a review queue. The page labels the
unit on every row for this reason — the misreading happened in review.

⚠ **"Published" is 4 current versions, against 5 clusters ever published.** Editing a
published role mints a new draft. Both numbers are true; conflating them flatters the one
metric this project measures itself by.

## 2. The 3,653 that never reached a role — all of it accounted for

| bucket | count | verdict |
|---|---:|---|
| ✅ Near-duplicate of a document that IS in a role | 1,900 | working as intended — represented by its twin |
| 🔴 Near-duplicate only of other dropped documents | 549 | the whole group is absent rather than merged |
| 🔴 No title could be extracted | 385 | parser defect |
| 🔴 Header/separator captured as the title | 134 | parser defect |
| 🔴 **A one-of-a-kind job the pipeline cannot represent** | **378** | **structural — see §2a** |
| 🔴 Shares a title with documents that did cluster | 307 | near-duplicate recall miss |

Only the first is benign, and it is 52%. Reported as a single *"3,653 de-duplicated"* the
whole drop read as routine.

### 2a. 🔴 The structural one: a unique job produces no role at all

| | |
|---|---:|
| clusters with 2+ member documents | **2,489** of 2,493 |
| in-role documents with no near-duplicate edge | **18** of 10,869 |

**A document reaches a role only if it has a near-duplicate.** The pipeline builds roles out
of duplicate groups, so a job that is one of a kind never enters clustering. It is not
rejected by any rule — it is never considered.

> The Bank's contract is *"many documents become one role"*. It has no answer for *"one
> document is already the role"*, and that **caps what can ever be published**. It needs a
> registered decision, not a patch.

### 2b. ⚠ `Untitled Position` is a placeholder, not an empty string

`title <> ''` reports **100% title coverage** and is wrong. **2,050 of 14,522 documents
(14%)** carry the placeholder, and **1,395 of them are already in drafts** on the published
path — so this reaches far beyond the 3,653.

That false all-clear was produced *during the investigation that later found it*.

## 3. The IT cohort (the demo)

> 🔴 **CORRECTED 2026-08-28, and the correction was severe.** Membership was the
> classification code in the source FILENAME alone. **9,481 of 14,565 documents (65%)
> carry no code in their filename**, so that signal is structurally blind to two-thirds
> of the archive. The collection reported **45 roles** and presented it as "the IT
> function"; the archive holds **~211**. For an employer the size of ITS that is a
> credibility failure, not a rounding error — and it was caught in review, not by us.

**Membership now unions every direct signal**, minus reviewed exclusions:

| signal | roles it finds alone | roles it CANNOT judge at all |
|---|---:|---:|
| classification code in the filename | 45 | 2 |
| the role's title | 149 | 6 |
| the department | 73 | **692** |
| **union — the collection** | **211** | — |

| | |
|---|---:|
| documents behind those roles | **1,279** |
| approvable today | **118** |

**Headline: 1,279 documents → 211 roles, 118 approvable.**

⚠ **"Cannot judge at all" is not "looked and found nothing".** A department signal says
nothing whatever about a role with no department recorded — 692 of them. Reporting those
two as one number is exactly how a filter reports a third of a function and looks correct.

⚠ **Recall first.** A false positive is rejected in review; a false negative is invisible.
`duty_terms` remains excluded from membership — it is a score, and §4a measured that no
cut point of it works. A direct attribute is different evidence from a similarity score.

### 3a. The duplicate-title question: they are distinct

**20** roles are titled *"Information Technology Professional"* (not 8, as an earlier draft
said). They resolve to **15 distinct specialisation × ITP-level cells** — network/telecom,
applications, business analysis, consultative support, across levels I–IV — and 18 of 20 are
level-homogeneous. The 5 sharing a cell hold 13 of 315 documents (4.1%), and the two examined
are real sub-specialisations. **No merge warranted.**

### 3b. ITP is not ITS

- **ITP** = the **classification** (Information Technology *Professional*). 469 filenames.
- **ITS** = the **department** ("IT Services" 903 parses). **Zero filenames.**

They barely overlap: of the 45 ITP roles only 10 have an ITS-looking department and 23 have
no department at all, while **47 roles carry an ITS department without the ITP
classification**.
### 3c. 🔴 The filename signal is unusable as a primary identifier — audited

**And CUPE was traced document-by-document to confirm the blind spot does not leak**
(asked in review, measured 2026-08-28): of 4,440 CUPE documents, **3,446 sit behind
cupe-labelled drafts, 0 behind any other label, 0 behind ungrouped drafts**, 994 in the
known orphan gap. Template routing and every CUPE count read the PARSED
`employee_group`, never filenames. The ungrouped drafts hide only APSA/APEX/POLY
documents — all JDFN-template groups, so the default judges them correctly. **Pinned by
`make smoke`**: a single CUPE document behind a non-cupe draft fails the run.


⚠ **The document counts below are the v5 parse.** They were re-measured at v6 — see
§7, which supersedes them; the filename-coverage percentages are unaffected because
they are a property of the filenames, not of the group read.

Measured 2026-08-28 after the §3 correction, across every employee group:

| parsed group | documents (v5) | findable by a filename code | |
|---|---:|---:|---:|
| APSA | 4,946 | 3,289 | 66.5% |
| **CUPE** | 4,440 | 787 | **17.7%** |
| (no group recorded) | 4,630 | 596 | **12.9%** |
| APEX | 420 | 336 | 80.0% |
| POLY | 50 | 49 | 98.0% |

**A filename-code filter finds 17.7% of CUPE and 12.9% of the ungrouped population.** Any
future collection defined that way inherits the IT failure, worse.

✅ **Blast radius checked, and it is bounded.** Filename matching appears in exactly two
places — the family membership resolver and the funnel's scoped document stages, both added
2026-08-27/28. **Everything else segments on `employee_group` read from the parse**, which
is content-derived and unaffected. The archive baseline, the bank audit and the producer are
not implicated.

⚠ **Rule for the next family:** a signal may only be a *primary* identifier if its coverage
across the target population has been measured first. Coverage before use.


## 4. 🔴 There is no usable threshold — measured twice, two different mechanisms

### 4a. Duty-term scoring

Scored against the 45-role ITP seed:

| min score | candidates | recall |
|---:|---:|---:|
| 1 | 1,141 (46% of corpus) | **97.8%** |
| 5 | 153 | **48.9%** |
| 7 | 68 | 17.8% |

**98% recall costs nearly half the archive; a plausible-sized cohort keeps half the roles we
already know are IT.** No cut point is both precise and complete → the score **ranks a review
queue and never decides membership**.

### 4b. Role-vector similarity

Measured earlier on this corpus: **unrelated roles outscore true twins.** Rank, never
threshold, and never display a percentage.

### 4c. A term list fails differently every time you rewrite it — **four times now**

It missed the **engineers** ("IT = desktop support"), then nearly missed the **analysts**
(they write about processes, not technologies), then missed the **leadership** entirely (a
Senior Director's duties carry no technology nouns), and it cannot see anyone whose JD simply
does not use the vocabulary.

**Union the signals; never intersect them.** Fixes shipped: the ITP classification finds the
analysts, and a department match (HR-222) finds the leadership — **11 roles reach the review
queue by department alone**, including *Solutions Architect* and *Director, Infrastructure
Services*.

## 5. Function ≠ department, and a department is not a unit

**No org chart gathers a function.** The strongest non-ITP IT candidates sit in Library
Systems, Linguistics, Facilities, Mechatronics, Computing Science and Earth Sciences — **none
in a central IT department**.

And a unit's own name finds almost none of its people:

| unit | filter on its own name | actual portfolio |
|---|---:|---:|
| **VPFA** (Finance & Administration) | **2 roles** | ~55+ across Finance, Financial Services, Procurement, Budget Office, Student Accounts… |
| **ITS** | 11 | ~49 across 11+ spellings |
| **Facilities Services** | 23 | 39 across 14 strings · 57 including security/grounds/parking |

**A vice-presidency is never the string written on a JD.** A unit is a rollup or it is wrong.

⚠ **Where a unit ends is a curation call, not a query** — is Campus Security part of
Facilities? And `FACILITIES SERVICES` and `Facilities Services` are two distinct strings
today.

⚠ **`School of Computing Science` (13 roles) is an academic unit, not ITS** — it looks
identical to the real thing to any substring matcher.

### 5a. Department coverage

| | |
|---|---:|
| drafts with a department recorded | 1,801 of 2,493 (**72.2%**) |
| distinct department strings | **739** |
| mechanical normalisation collapses | only 7.4% |

**Any unit rollup is blind to 27.8% of the Bank**, however good the alias map becomes. Every
facet therefore publishes its own coverage.

## 6. Field reliability

| field | populated | usable? |
|---|---:|---|
| `title` | 100% | ⚠ **but 14% is the `Untitled Position` placeholder** (§2b) |
| `department` | 72.2% | ⚠ raw strings, 739 of them — filters, does not total a unit |
| `employee_group` | **68.8%** (v6) | ⚠ the other 31.2% is **unrecorded**, and defaults to JDFN — see §7 |
| `grade` / `status` | 100% | ✅ (quality grade A–D, **not** a pay grade) |
| `classification` | **0% of drafts** | 🔴 parsed on 21% of documents, lost before the draft |
| `position_number` | 1 of 2,489 | 🔴 unusable |

---


## 7. 🔴 The employee group had two provenances, and one of them was a mention

**Measured 2026-08-29 against the RAW ARCHIVE FILES** — not the database — after
"there should be more CUPE than APSA, the numbers don't add up". The instinct was right
that something was wrong; the fault was the opposite of what the page suggested.

### 7a. `cupe` could be established by a passing mention

Of the 4,440 documents the Bank labelled `cupe`, **2.2% of a 600-document sample were
never routed to the WJQ segmenter at all**. Of 24 examined, **ZERO declared
`Employee Group: CUPE`** and all 24 were passing mentions:

> *"Directly supervises CUPE employees"* · *"administers the collective agreement between
> the University and CUPE, Local 3338"* · *"supervises temporary CUPE staff and volunteers"*

They are **APSA managers who supervise CUPE staff** — `Manager`, `Director, Advancement`,
`Student Recruiter`. `template_of` reads this field, so each was scored on the **WJQ
profile instead of JDFN**, dropped from the JDFN current-practice cohort (HR-143), and
counted as CUPE everywhere. The same error as HR-224 inverted: a job is not a VP because
its boss is; **a job is not CUPE because its staff are.**

**The control is what made the fix safe** — does a document contain its own recorded token?

| group | sampled | token present | |
|---|---:|---:|---:|
| apsa · apex · poly · excluded | 326 | 326 | **100%** |
| **cupe** | 120 | 3 | **2.5%** |

`cupe` is set by **routing** (`is_wjq`), never by reading the word — so removing it from
the bare-token scan costs no genuine detection. An explicit label still establishes any
group. Registered as **HR-226**; fixed in `PARSER_VERSION` **v6**.

### 7b. The corrected split, and it reconciles exactly

| group | v5 | **v6** | Δ |
|---|---:|---:|---:|
| apsa | 4,946 | **5,121** | +175 |
| (none recorded) | 4,630 | **4,534** | −96 |
| **cupe** | 4,440 | **4,300** | **−140** |
| apex | 420 | **420** | 0 |
| poly | 50 | **76** | +26 |
| excluded | 36 | **71** | +35 |

373 documents changed group. apsa+poly+excluded gained 236 = cupe −140 + none −96.
**Nothing is unaccounted for.** Coverage rose 47.9% → **68.8%**.

> **Is CUPE bigger than APSA? No — and the correction widens the gap: 5,121 vs 4,300.**
> Re-running the real `is_wjq` detector over 500 ungrouped documents found **0 missed
> CUPE**, and 96.2% of the ungrouped carry a Decision Making section (CUPE documents are
> 96.9% *without* one). The remaining unknowns are JDFN-family, so APSA's true lead is
> larger still. ⚠ This is a count of **documents on file**, not of SFU headcount.

### 7c. The archive is silent on a third of its own documents

Reading the source files for 400 ungrouped documents: **92% contain no group token
anywhere**. This is not a parse failure — SFU did not record a bargaining unit on them.

🔴 **The defect is that the system presents that silence as JDFN.** `template_of` returns
`wjq` only for `cupe` and defaults everything else, so 4,534 documents with *no recorded
group* are counted as JDFN. That is the IT-collection failure again: **no
could-not-evaluate bucket.** Any facet over this field must report matched / not-matched /
**unrecorded**, never two numbers.

### 7d. 24 drafts claim a template their documents are not

61 of the corrected documents sit inside **24 DRAFT canonical JDs still labelled `cupe`**,
and **every one of those drafts is entirely stale** — not mixed. **None is PUBLISHED.**
They are CUPE roles built from APSA managers.

⚠ **`make smoke` did not catch this and is now RED because of it.** The old guard asked
only *"is a CUPE document behind a non-CUPE draft?"* and was structurally blind to the
inverse. `test_no_draft_claims_a_template_its_documents_do_not` now asserts both
directions. **Agreement in the direction you tested says nothing about the other.**

The repair is a **decision, not a cleanup**: `src.jd_bank.canonical` has `--only-template`
but no per-cluster filter, so re-composing exactly those 24 is not currently expressible,
and a producer run is under a standing ⛔ in `CLAUDE.md`.

---

## Full working

The original per-topic documents are in **`docs/archive/plans/`** — kept for the reasoning
and the reproduction SQL, **not as a source of numbers**:

| archived document | what it works through |
|---|---|
| `IT-DUPLICATE-TITLE-ANSWER.md` | §3a in full, with the cohort-definition sensitivity table |
| `IT-FUNCTIONAL-SWEEP-MEASUREMENT.md` | §4a in full, with the recall curve and reproduction SQL |
| `THE-1204-UNACCOUNTED-DOCUMENTS.md` | §2 in full, with the bucket queries |
| `SCOPES-AND-ORG-ROLLUP.md` | §5, and the scope/resolver design for VPFA and Facilities |
| `FUNCTIONAL-ROLE-TAXONOMY.md` | the method — seed, sweep, measure recall, review, publish |
| `DEPARTMENT-TAXONOMY.md` | §5a, the 739-string sweep |
| `IT-SUBSET-DEMO-AND-FACETS.md` | the original demo design |
| `SOURCE-ARCHIVE-DASHBOARD.md` | the case for a live dashboard — **now built** |

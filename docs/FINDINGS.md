# Findings — everything we have measured about this archive

**One place for every measured claim.** Written 2026-08-28, consolidating eight separate
plan documents that had scattered the same numbers across ten files.

🥇 **[`../CURRENT.md`](../CURRENT.md)** indexes where every fact lives and how to check it.
Each finding here names the command that produced it — **re-run it rather than quoting it**.

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

**Registered as HR-223, and the population is now measured by code you can re-run** —
`make singletons`, over all 14,522 current-version parses (2026-08-29, `jd_segmenter_v7`).
Numbers below and in `docs/singletons/`; the register entry is the decision.

#### The size of it — four buckets, never one total

1,222 documents carry no `dedup_edges` row at either end, and **1,204** of those are in no
role. (18 reached one anyway, through the Builder, which mints roles from no source
documents at all — which is why the pool is "no edge **and** no role", not the edge check
alone.) Split so the could-not-evaluate bucket is visible:

| the 1,204 | | what it means |
|---|---:|---|
| title appears exactly ONCE in the archive | **462** | a genuinely singular SFU job — the population HR-223 is about |
| shares a title with a document that DID reach a role | **497** | a dedup recall miss (**D3**), not a unique job — the role already exists |
| shares a title only with other orphans | **163** | a group the dedup never linked |
| 🔴 **could not evaluate** | **82** | the parser recovered no usable title; neither answer is available |

**The control** — the same split over the 10,808 documents that *did* reach a role — is
484 / 9,311 / 0 / 1,013. The could-not-evaluate rate is **6.8% in the pool against 9.4% in
the control**, so the probe is reading the archive rather than the parser. Separately the
clustering report calls **3,658** documents `singletons` (coverage 74.81%): a *different
unit*, counting every document that ends in a component of one, vetoed edges included.

⚠ **462 is an upper bound.** Only the definitional case is excluded — a title with no
letter in it (`#01246`) is not a title in any language SFU writes JDs in. A 60-title sample
read verbatim still contains banner text (`ADMINIISTRATIVE AND PROFESSIONAL STAFF
ASSOCIATION POSITION`), truncations (`Assistant to the Director, External Programs and`), a
label bleed (`Accreditation Manager Position#: 00110757`) and one incumbent's name
(`Leigh McGregor. Departmental Assistant`, §8d / plan.md P3c) — all counted as unique
because they *are* unique strings. A junk-title classifier invented on a 60-document sample
is the failure mode the register exists to prevent, so the bound is published instead.

#### ⚠ Two of our own numbers were wrong, and re-deriving them is what caught it

The first measurement of this population (2026-08-28, by hand, at `jd_segmenter_v6`) was
stale within a day. Every bucket here is title-based, and v6→v7 recovered 805 titles:

| | measured 08-28 | re-derived 08-29 |
|---|---:|---:|
| unique title | 386 | **462** |
| shares a title with a clustered document | 305 | **497** |
| could not evaluate | 513 | **82** |
| the clustering report's `singletons` | 3,620 | **3,658** |

🔴 **And the qualification comparison inverted.** The draft entry said the pool averages
**1.46** parsed qualifications against **8.84** for documents that reached a role, and used
it to discount the headline: most would mint a role and fail the gates anyway. Re-derived,
the same probe returns **8.89** for the in-role population — reproducing that half almost
exactly — and **9.54** for the pool. On this measure the one-of-a-kind documents are not
poorer at all.

The medians say why neither mean means much: **0.0 for the pool and 1.0 for the in-role
population.** Over half of *both* populations have no parsed qualifications, and the means
are driven by a minority carrying many. **The qualification evidence neither supports nor
discounts the 462, and must not be quoted as if it did.**

*One half of a two-number comparison reproducing exactly is what identified which half was
broken. A mean alone could not have.*

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

✅ **FIXED 2026-08-29 (P2).** The baseline now carries a `employee_group` facet read from
the document's **content** — deliberately not the existing `employee_group` row field,
which is FILENAME-derived (§3c: that signal finds 17.7% of CUPE). `(unrecorded)` is its
own bucket, on the dashboard, punctuated so it cannot read as a group SFU recognises:

| unit | files | scored | median | approval permitted |
|---|---:|---:|---:|---:|
| apsa | 5,121 | 5,121 | 70.3 | 11.9% |
| **(unrecorded)** | **4,577** | **4,534** | **42.4** | **0.1%** |
| cupe | 4,300 | 4,300 | 75.3 | 59.2% |
| apex | 420 | 420 | 70.3 | 17.1% |
| poly | 76 | 76 | 68.3 | 1.3% |
| excluded | 71 | 71 | 42.1 | 0.0% |

Files 14,565 = the whole archive; **files vs scored** separates the two silences (nothing
recorded, vs 43 files with no extractable text — *could not evaluate* is not *evaluated
and found nothing*).

### 7c-i. 🔴 The unrecorded are not a random third — they are the OLD archive

Measured over `rows.jsonl`, era by unit:

| unit | old | transition | new | current |
|---|---:|---:|---:|---:|
| apsa | 3% | 13% | **69%** | 15% |
| cupe | 37% | 41% | 19% | 3% |
| **(unrecorded)** | **35%** | **53%** | 12% | **0%** |

**Not one of the 4,577 unrecorded documents is `current`-era.** Recording the bargaining
unit is a property of the MODERN template; the silence is an artefact of age, not of
parsing.

⚠ **So folding them into `jdfn` was doubly wrong.** It did not merely mislabel them — it
mixed 5,121 modern APSA documents with 4,534 mostly pre-2019 ones (median 42.4 against
70.3) and reported the blend as the JDFN population. The era facet and the unit facet were
each individually fine; the harm was in reading one bucket as the other.

### 7d. 24 drafts claim a template their documents are not

61 of the corrected documents sit inside **24 DRAFT canonical JDs still labelled `cupe`**,
and **every one of those drafts is entirely stale** — not mixed. **None is PUBLISHED.**
They are CUPE roles built from APSA managers.

⚠ **`make smoke` did not catch this.** The old guard asked only *"is a CUPE document
behind a non-CUPE draft?"* and was structurally blind to the inverse.
`test_no_draft_claims_a_template_its_documents_do_not` now asserts both directions.
**Agreement in the direction you tested says nothing about the other.**

✅ **RESOLVED 2026-08-29 — the 24 drafts were DELETED**, on the project owner's ruling.
`core/db/repairs/001_drop_mislabelled_cupe_drafts.sql`: selects by the derived condition
rather than hardcoded ids, refuses to run if anything non-`DRAFT` or reviewer-touched is
in scope, and is idempotent (a second run deletes 0). `make smoke` is **green — 6 passed**.

**Deleted rather than re-composed, deliberately.** A cluster with no draft reads as
*un-drafted*, which the funnel already accounts for; a cluster with a WRONG draft reads as
a finished role. The next producer run regenerates them on the template their documents
actually are.

| after the repair | |
|---|---:|
| clusters | 2,493 |
| clusters with a current draft | **2,469** |
| clusters now un-drafted | **24** |
| drafts still claiming cupe (the genuine ones) | 625 |

⚠ **The `audit_log` was NOT written to.** It is hash-chained (`audit_chain_tail`), so
hand-forging an entry the application did not make would corrupt the chain. The repair is
recorded in git and here instead.

---


## 8. 🔴 Half the CUPE archive had no title, and it was one line of the WJQ parser

**Measured 2026-08-29 against the raw source files (P3).** `title` is the second field
ever checked this way; the first (`employee_group`, §7) produced two defects immediately.

### 8a. It was never a general title problem

| bargaining unit | documents | with NO title (`Untitled Position`) |
|---|---:|---:|
| **cupe** | 4,300 | **2,046 — 47.6%** |
| apsa · apex · poly · excluded | 5,688 | **0 — 0.0%** |

`Untitled Position` is a **sentinel, not an empty string**, so `title <> ''` reported 100%
coverage over all of it (§2b). 1,395 of those placeholders were already inside drafts.

### 8b. The cause: label and value in ONE cell

antiword's fixed-width render of the WJQ form puts them together, while `_extract_label`
reads the value from the **next** cell. Verbatim from the archive:

```
Department Position Title: Program Assistant
Department Position Title: Budget Assistant Department Name/Section:
```

**Result: 805 titles recovered · CUPE placeholders 47.6% → 28.9% · position numbers
2,416 → 3,009** (same code path). `PARSER_VERSION` v6 → v7.

### 8c. ⚠ Three corrections to our own work, in one investigation

1. **The first fix passed its tests and recovered ZERO.** It added the possessive
   spelling `Department's Position Title`, found by a probe that scanned the WHOLE
   document — but that occurrence is in the form's *blank template header*, and the
   parser reads only the identification section, where the spelling is the one already
   supported. **A probe whose scope does not match the parser's scope measures a
   different question and answers it confidently.**
2. **The risk assessment was wrong too.** The `'Lisa Buckley'` / `'Phil McCloy'` values
   that made us defer this came from the same whole-body scan. *Inside* the
   identification section the neighbouring text is other **labels**, which can be cut
   deterministically.
3. **A filename oracle nearly killed the fix.** It reported 73.7% of recoveries
   "suspect" — an artefact of a tokenizer that could not split `00001726Clerk`, so
   CORRECT recoveries scored as mismatches. With the tokenizer fixed and a CONTROL added,
   the oracle's ceiling is **40.4%** (agreement on titles the parser already accepts) and
   recoveries reach **45.1%** — *better than the status quo*. A flat metric is a question.

### 8d. What is refused, and what remains

Recovering more titles must not mean inventing them. A value whose last token is a
connector was cut off by the column width — `Housing &`, `Research and` — and is
**refused back to the sentinel**: a fragment is a confident wrong value, while the
sentinel announces its own failure and every surface already reports it as a gap. Form
furniture (the underscore fill-in rule, the `Approved by` sign-off column) is stripped.

Final residual on the 805: **0 dangling, 0 underscores, 0 sign-off bleed.**

⚠ **Known and NOT fixed: one recovered title contains an incumbent's name**
(`Leigh McGregor. Departmental Assistant`). Detecting a personal name needs a decision and
a measurement, not a regex invented on a sample of one — and NN #5 makes incumbent-name
removal a rulebook quality step. ✅ **That measurement is now done — §8e, and it says
DO NOT BUILD THE REGEX.**

### 8e. 🔴 P3c measured — the sample of one is a population of one, and every rule that would catch it is worse than the defect

**Measured 2026-09-11 over all 14,522 titled documents at `jd_segmenter_v8`** (3,835
distinct titles). The plan asked for a measurement before a rule. Here it is, and it
argues against the rule.

**First, the case is real and still live.** `Leigh McGregor. Departmental Assistant` is
present at `jd_segmenter_v1`, `v7` **and `v8`** — one document each. It was not fixed by a
re-parse and it has not gone away.

**Second, it is the ONLY one.** Each structural shape that would catch it was counted
against the whole corpus:

| shape | distinct titles | documents | how many are actually names |
|---|---:|---:|---|
| `Firstname Lastname. Title` — *the observed shape* | 2 | 2 | 🔴 **ZERO.** `Program Assistant. Gr. 7` and `Assistant Director. Graduate Studies _____` |
| `Firstname Lastname, Title` | 732 | **1,429** | zero — `Associate Director, Advancement`, `Senior Developer, PeopleSoft` … |
| `Title (Firstname Lastname)` | 18 | 34 | zero — `(Advisory Services)`, `(Desktop Support)` … |
| explicit cue (`incumbent`, `held by`) | 2 | 3 | zero — both are PROSE in the title field, see §8f |

⚠ **The two-capitalised-words shape is how SFU titles are normally written.** A comma rule
would flag **1,429 documents** to catch one, and the period rule catches the one real case
only by also taking two false positives — a 33% precision on a population of three. There
is no threshold to tune here: the signal and the noise are the same shape.

**So the honest recommendation is to NOT ship a detector.** A rulebook list that fires on
1,429 correct titles is not a quality gate, it is a new defect with a registered id. The
one document is better handled as what it is — a single bad value — than as a rule
pretending to generalise. ⚠ This is P3e's lesson a second time: *the defect was in the
sample, not in the corpus.*

### 8f. The defect the P3c probe tripped over — the RESIDUAL of `_fallback_title`, diagnosed

⚠ **First, a correction to this section's own first draft.** It called this a NEW defect
and blamed a pydantic `max_length`. **Both were wrong, and checking the code is what said
so** — the standing rule of this file, applied to it.

- It is **not new**. It is the measured residual of the v2→v3 `_fallback_title` defect,
  which `segmenter.py` records in full: the modern template keeps its identification table
  in the docx *header*, extraction excluded it, and *"`_fallback_title` took the first body
  paragraph as the title"*. `_docx_identification_block` fixed the bulk — **paragraph
  titles 4,986 → 148** at v3. What follows is what is left at v8.
- The 200-char cut is the **parser's own** `_MAX_TITLE = 200` (in `_fallback_title` and at
  the `SFUJobDescription` call), not a model-validation artefact. `title` also carries
  `max_length=200`, so the two agree — but the truncation happens in the parser first.

⚠ **148 (v3) and the numbers below are NOT comparable** — they count different things by
different definitions. Do not read a trend into the pair.

**Measured at `jd_segmenter_v8`, 2026-09-11:**

| | documents |
|---|---:|
| titles cut at exactly `_MAX_TITLE` (200) — unambiguously a paragraph | **53** (15 distinct) |
| titles opening with a prose word (`The`/`Reporting`/`Provides`/`Playing`/`Under`/`Working`/`Please`/`This position`) | **299** |
| titles over 120 chars | 130 |
| titles over 60 chars | 451 |

```
Reporting to the Manager, Linguistics, and supervised by both the Managers, Linguistics …
Provides comprehensive services to students, faculty, staff and external client of the a…
Please connect with Strategic Business Partner or Director, Strategic Business Partner. …
```

🔴 **And the diagnosis is decisive about WHICH parser is at fault.** Split by employee
group, the at-cap documents are:

| group | at the 200 cap | titled documents |
|---|---:|---:|
| `(unrecorded)` | **30** | 4,534 |
| `apsa` | **23** | 5,121 |
| `cupe` | **0** | 4,300 |
| `apex` / `poly` / `excluded` | 0 | 567 |

**Zero CUPE.** The WJQ path reads a labelled CELL (`wjq.id_labels`) and cannot pick up a
paragraph; every one of the 53 came through the JDFN identification-block path and fell
through to `_fallback_title`. Every sample also carries `department = None`, which is the
corroborating signal: the identification block was not recovered *at all*, so title and
department failed together rather than the title extractor misfiring on its own.

⚠ **53 is the hard floor** (at the cap) and **299 the upper bound** (a prose opener could
in principle be a real title). Unlike a personal name this needs no name detection —
"the title field contains a sentence" is decidable from length and shape. The fix belongs
in the **identification-block recovery for these ~53 `.docx` files**, not in a post-hoc
title trimmer: §8d's standing rule is to refuse back to the sentinel rather than ship a
fragment, and a truncated paragraph is a confident wrong value.

⚠ **The remaining ~1,241 CUPE placeholders are genuine gaps**, not a fixable parse: about
half the placeholder population has no title label anywhere in the document.

---

## 9. 🔴 The third field checked against the archive, and it produced a defect too

**P3b, 2026-08-29.** `make field-audit`, over all 14,565 files (14,518 read, 47 skipped —
unreadable, or not parsed at `jd_segmenter_v7`). `docs/field-audit/`.

`title` and `employee_group` were the only fields ever compared against the SOURCE FILES.
Each produced defects immediately. **So did the third.**

### 9a. The gap: 726 CUPE departments the archive states and the Bank does not

`readable − parser` per bargaining unit — the archive states a value under a name a
registered mechanism can read, and the parser stored nothing:

| group | field | parser | readable | gap |
|---|---|---:|---:|---:|
| **cupe** | **department** | 2,958 | 3,684 | **+726** |
| (unrecorded) | department | 3,923 | 4,173 | +250 |
| apsa | department | 1,780 | 1,854 | +74 |
| apsa | position_number | 4,753 | 4,817 | +64 |
| apex | position_number | 390 | 408 | +18 |

**The 726 is stable across three full runs** and every correction to the probe, which is
what makes it credible. It was verified by opening the files, not by trusting the count.

### 9b. Three causes, not one — and the value is usually on the COVER PAGE

> 🔴 **SUPERSEDED BY §9g (same day).** "Three causes, no single fix recovers all 726" is
> WRONG. Scoped to the parser's own reading, one label — `Department Name/Section` —
> accounts for ~667 of 680. Kept as the record of the wrong turn and what caused it.

Three documents from the gap, read at source. In **all three** the department is present
on the **cover page** under the exact registered spelling `Department Name:` — and the
parser reads only the **identification block**:

| document | in the identification block | cause |
|---|---|---|
| `20011001_00030128Clerk.doc` | `Department Name/Section:  Centre for Distance` | the **variant spelling** is unregistered, *and* the value is truncated by column width |
| `20000411_00031217Clerk.doc` | `Name/Section:   Bookstore` | the label is **wrapped across a line break** — `Department` ends the previous line |
| `19930519_00000991Library_assistant.doc` | *(no department label at all)* | the field exists **only on the cover page** |

```
  2 [   COVER]  Department Name: Bookstore
 20            1. POSITION IDENTIFICATION
 21 [ID-BLOCK]  Department Position Title:  Shipper/Receiver Department
 22 [ID-BLOCK]  Name/Section:        Bookstore
```

⚠ **`Department Name/Section` is genuinely unregistered** — `wjq.id_labels.department`
holds one spelling, `Department Name`, and `_extract_label` matches a whole cell. The
asymmetry was visible in the code before it was measured: `name/section` **is** in
`_NEXT_LABEL_RX`, so the parser already knows it is a label to *stop at* while having no
way to *read from* it. It is the top unreadable department name at 29.

### 9c. ⚠ 726 is an UPPER BOUND, and the reason is the P3a trap wearing new clothes

> 🔴 **SUPERSEDED BY §9g (same day).** The bound was right and the diagnosis below was
> wrong: re-probed in the parser's own scope the gap is not a read failure but ONE
> unregistered label. Read §9g before acting on anything in §9b or §9c.

**The probe reads the whole document; the parser reads only the identification block.**
So the gap counts "the archive states a department", not "the parser could have read one
from its own scope". Which of the three causes dominates is **not yet measured**, and no
single fix recovers all 726.

This is the same scope mismatch that made the *first* P3a fix pass its tests and recover
exactly zero — there the whole-document probe found the label in the blank template
header. It is not a false positive this time (the values are real, and they agree with
the identification block where that block has one), but the count still answers a
different question from "what would a fix recover". **Measure the scope-matched number
before choosing a fix.**

### 9d. ~~A second defect: repeated internal spaces~~ 🔴 NOT A DEFECT — probe artifact

> **RETRACTED 2026-08-29.** Everything below is the PROBE's view of the raw text. The
> parser never sees these labels stretched: `_ordered_cells` collapses runs of whitespace
> before `_extract_label` compares a cell, so `Department  Name:` reads fine today.
>
> I wrote a whitespace-collapsing normaliser for this (planned as P3e) — and **breaking it
> on purpose left the suite green**, which is what exposed it as a fix for nothing. It was
> reverted; the test now pins the collapse in `_ordered_cells` instead.
>
> ⚠ The general form: **a probe finding something the code already handles is a finding
> about the probe.** Kept as the record of the wrong turn.

`_extract_label` strips and lower-cases but never **collapses** internal whitespace, so
these match nothing at all:

`Position  Title` (8) · `Position   Title` (8) · `Position  Number(s)` (8) ·
`Department  Name` (7) · `IDENTIFICATION   Position Number` (3) ·
`Department's   Position Title` (3) · `Classification  &  Grade Approved`

Small, real, and it spans every field. One `.split()`/`join` in the label comparison.

### 9e. What this audit CANNOT see, and where the honest zeroes are

- **`classification` is not evaluated at all** — pulled by regex, not a label, so a label
  probe says nothing about it. ~~⚠ Those regexes being hardcoded is itself a
  rulebook-as-data gap.~~ ✅ **THE RULEBOOK HALF IS CLOSED (P3f, 2026-09-11.)** The three
  matchers now live in `rules/classification.yaml`, registered as **HR-233 … HR-236** (all
  `open`, all `technical`) and drift-checked, so a change to one breaks the build until
  the register is updated. ⚠ **No value moved in the migration** — verified over 78,384
  comparisons against real Bank text, 0 mismatches — so `PARSER_VERSION` did NOT bump and
  no re-parse was owed. ⚠ **The FIRST half of this bullet still stands:** the field audit
  reads LABELS, and a grade pulled by a matcher rather than a label is still invisible to
  it. Registering the matchers did not make the probe able to see them.
- **`grade` is under-counted for CUPE** (parser 465, readable 98): `classification.cupe_grade`
  (then `_CUPE_GRADE_RX`) finds grades in prose like `Secretary, Grade 6`. A negative gap is
  the probe's blind spot. ⚠ Probed from the other side during P3f, the matcher is loose in a
  second way the label probe cannot show either: the leading `\b` correctly refuses
  `upgrade 9` and `photograph 3`, but **no separator is required**, so the bare token `GR8`
  reads as grade 8. Registered as HR-233 rather than tightened on a sample — it wants a
  measurement over the archive first.
- **`grade` is genuinely absent almost everywhere**: 4,292 of 5,121 APSA and 4,517 of
  4,530 unrecorded documents carry no grade label. That corroborates the separate finding
  that grade is missing or unreliable across the archive.
- **2,604 CUPE `grade` and 1,260 CUPE `position_number` labels are present and EMPTY** —
  blank form fields, not defects, and counted separately for exactly that reason.

### 9f. The control, and why it is trusted

`title` is the control: its answer was already known. Parser 3,059 against readable 3,085
for CUPE and 5,121 against 5,085 for APSA — agreement, not a gap. And independently, the
probe finds **1,210 CUPE documents with no title available** (340 blank + 869 no label)
against P3a's separately-measured *"the remaining ~1,241 CUPE placeholders are GENUINE
gaps"*. **Two unrelated methods, the same answer.**

*The probe was wrong three times before it was right, and each time the CONTROL is what
said so — never the finding itself.* Full working in `docs/field-audit/README.md`.

### 9g. 🔴 Scoping the probe to the PARSER'S scope inverted the conclusion (P3d)

**Measured 2026-08-29, `make field-audit FIELD_AUDIT_ARGS="--identification-only"`.**
`docs/field-audit/field-audit-identification.json`.

The probe above reads the WHOLE document. The parser reads only the block after
`1. POSITION IDENTIFICATION`. Re-probing in the parser's own scope changes the answer
completely:

| CUPE `department` | whole document | identification block |
|---|---:|---:|
| parser has | 2,958 | 2,958 |
| readable | 3,684 | **2,956** |
| 🔴 unreadable | 35 | **680** |

**Inside its own scope the parser reads essentially everything it can** — readable 2,956
against 2,958 held. The gap is not a read failure at all.

**It is one unregistered label.** The verbatim names behind the 680:

| count | field name in the document |
|---:|---|
| **654** | `Department Name/Section` |
| 9 | `Department Name/ Section` |
| 3 | `Department Name /Section` |
| 1 | `Department name/Section` |
| 7 | prefixed — `Assistant Department Name/Section`, `Admissions …`, `BusinessPrograms …` |
| 2 | `Department Mane/Section` — a **typo in the source document** |

**667 of 680 are `Department Name/Section` in some spacing.** `id_labels.department` holds
one spelling, `Department Name`, and `_extract_label` compares the whole cell.

⚠ **The 7 prefixed names are the antiword line-wrap, not spellings** — the previous field's
VALUE runs into this label's cell. They need the wrap handled, not a label entry. And the
2 `Department Mane/Section` are a typo in the archive: **report it, never encode it.**
Adding a misspelling to a rulebook list is fitting the rule to noise.

### 9h. ⚠ The correction this forced to §9b, and why it matters

§9b named three causes and said "no single fix recovers all 726". **That was wrong, and it
was wrong because the probe's scope did not match the parser's** — exactly the trap §9c
warned about, committed while writing the warning. The whole-document probe kept finding
the *cover page's* readable `Department Name:`, which the parser never reads, and
attributed the shortfall to a read failure.

Scoped correctly, one cause dominates and the fix is bounded: **register the
`Department Name/Section` spelling (tolerating spacing around the slash) and expect up to
~667.** P3e's whitespace collapse is visible here too — `Department   Position Title` (6),
`Department  Position  Title` (4), `Position Number (s)` (10), `Classification  &  Grade
Approved`.

> **The lesson is not "scope the probe".** It is that a probe and the thing it audits must
> answer the SAME question, and the way to find out is to make the probe reproduce the
> parser's own number. Here that check is `readable ≈ parser_has` — and only in the
> identification scope does it hold.

⚠ **This scope covers WJQ only.** 4,226 documents carry a WJQ identification heading; the
rest are skipped as *could not scope*, not as *states nothing*.

## 10. 🔴 `flagged_duties` fires on 69.2% of all duties — HR-184 re-measured

**Measured 2026-09-11 over all 2,501 current drafts / 15,530 duties.** HANDOFF flagged this
as wanting re-measurement rather than quiet re-tuning; this is that measurement.

### 10a. The draft-level rate was right, and it was the wrong unit

| group | drafts | with ≥1 flag | draft % | duties | flagged | **duty %** | every duty flagged |
|---|---:|---:|---:|---:|---:|---:|---:|
| `(unrecorded)` | 1,298 | 1,258 | 96.9% | 5,654 | 4,273 | **75.6%** | 558 |
| `cupe` | 625 | 610 | **97.6%** | 7,290 | 4,570 | **62.7%** | 21 |
| `apsa` | 524 | 504 | 96.2% | 2,324 | 1,725 | **74.2%** | 201 |
| `apex` | 42 | 36 | 85.7% | 205 | 127 | 62.0% | 18 |
| `excluded` / `poly` | 12 | 12 | 100% | 57 | 48 | 84.2% | 7 |
| **ALL** | **2,501** | **2,420** | **96.8%** | **15,530** | **10,743** | **69.2%** | **805** |

The draft-level figures reproduce the handoff exactly (CUPE 97.6%; the JDFN side 96.2–96.9%
against the quoted 97.0%). **But a draft with five duties and one flag counted the same as a
draft where all five were flagged**, which is why the draft rate understates the problem:

- 🔴 **69.2% of every duty in the Bank is flagged.**
- 🔴 **805 drafts — 32% — have EVERY duty flagged.** Inside those, the flag distinguishes
  nothing at all.

A finding on two-thirds of the corpus is not a finding. `duty_flag_threshold` (HR-184,
`open`, provisional) is the knob, and this is the evidence for re-deciding it.

### 10b. It independently corroborates the 120-cluster sample

The duty-frequency work measured **"62.4% of duties share under 0.2 Jaccard with any merge
duty"** over 120 real clusters. Over the **whole** CUPE corpus the flag — which fires on
exactly that condition — hits **62.7%** (4,570 of 7,290). **Two different methods, two
different populations, the same answer**: the 120-cluster sample was representative, and
neither number needs re-deriving again.

### 10c. 🔴 It is ONE knob wearing two hats, and that is the real finding

`duty_flag_threshold` does not only flag. `rewrite/harmonize.py` reads the same number in
the other direction: a rewritten duty scoring **below** it is flagged **and gets no
`frequency` carried back** from its merge counterpart. So *"the flag fires too often"* and
*"frequency is destroyed"* are *one mechanism seen from two sides* — the handoff carries
them as two separate backlog items.

The arithmetic reconciles and explains the gap between them:

| CUPE | |
|---|---:|
| duties **not** flagged (so a frequency could be carried back) | 37.3% |
| duties that actually **kept** a frequency | 28.5% |
| **difference** | **8.8 points** |

Those 8.8 points are matched duties whose **merge counterpart had no frequency of its own**
— nothing was lost there; the source never had one. ⚠ This matters for design: lowering the
threshold to rescue frequency also floods the flag, and raising it to sharpen the flag
destroys more frequency. **They cannot be tuned independently, and the rulebook comment says
so on purpose** (*"answering it twice is how two thresholds drift apart"*).

### 10d. ~~What this measurement cannot answer~~ 🔴 WRONG — and the sweep is below

**This section said the sweep needed the merge re-run, because "only the boolean outcome at
the shipped 0.2 survives in `change_log`". That is false, and it was false when written.**
`change_log.merge_provenance.duty_coverage` stores **the merge duty TEXTS verbatim**, so
every per-duty Jaccard is recomputable from stored data alone — no re-run, no CPU budget,
seconds. Checking the column instead of asserting about it is what found this.

### 10e. 🔴 The sweep — and the shipped 0.2 sits on the steepest part of the curve

**Measured 2026-09-11 over 2,426 drafts** (72 skipped: no merge duties recorded). The
scoring functions are **imported from `rewrite/harmonize.py`** (`_content_tokens`,
`_closest`), never re-implemented — a sweep carrying its own copy of the arithmetic would
agree with itself rather than with the code that ships.

**The validation that makes it trustworthy:** at the shipped 0.2 the recomputation flags
**4,570** CUPE duties — *exactly* the 4,570 recorded in `change_log` (§10a). It reproduces
the pipeline's own answer before being asked anything new.

| threshold | CUPE flagged | `(unrecorded)` | `apsa` |
|---|---:|---:|---:|
| 0.05 | **2.7%** | 16.4% | 11.8% |
| 0.10 | **20.6%** | 36.5% | 33.1% |
| 0.15 | 45.3% | 59.8% | 57.4% |
| **0.20 (shipped)** | **62.7%** | **75.0%** | **73.9%** |
| 0.25 | 76.1% | 85.6% | 84.2% |
| 0.30 | 85.1% | 92.0% | 89.9% |
| 0.50 | 96.7% | 98.3% | 96.1% |

🔴 **Two numbers reframe the whole question:**

| CUPE | |
|---|---:|
| duties with **NO token overlap at all** (J = 0.0) | **0.8%** (55 of 7,290) |
| duties **identical** to a merge duty (J = 1.0) | **0.3%** (24) |

**The model rewords essentially everything and invents almost nothing.** A 0.2 token-Jaccard
bar is not separating "fabricated" from "grounded" — it is separating *lightly* reworded
from *heavily* reworded, and at 0.2 the heavy majority lands on the wrong side. Between 0.10
and 0.20 the CUPE flag rate triples (20.6% → 62.7%), so the shipped value sits exactly where
the curve is steepest and a small move changes the answer most.

⚠ **THIS IS EVIDENCE FOR A DECISION, NOT A RECOMMENDATION TO MOVE THE NUMBER.** HR-184 stays
`open` at 0.2. The sweep says how many duties each threshold *matches*; it says **nothing
about whether the match is the RIGHT merge duty** — and the separate 120-cluster measurement
found argmax and positional matching agree only **8–26%**, because the model reorders. Since
this one knob also carries `frequency` back (§10c), a lower threshold attaches **more**
frequencies from matches that may be wrong, and a wrong frequency is worse than a missing
one.

**So the genuinely open question is precision, not volume**, and it needs a labelled sample —
read N rewritten duties against their argmax merge duty and count how often it is the same
duty. That is the one piece this sweep does not supply. ✅ **§10f gets an upper bound on it
WITHOUT labelling.**

### 10f. 🔴 Precision, measured mechanically: 12.6% of matched CUPE duties COLLIDE

§10e said precision needed human labelling. **Part of it does not.** `_closest` is argmax
with **no exclusivity** — two rewritten duties can both claim the *same* merge duty, and
both then inherit that one duty's `frequency`. Collisions are therefore countable, and they
are exactly where the carry-back is unverified.

**Measured 2026-09-11, same import-the-shipped-scorer method as §10e, at the shipped 0.2:**

| group | drafts | matched duties | in a collision | **collide %** | drafts affected |
|---|---:|---:|---:|---:|---:|
| `cupe` | 612 | 2,720 | 342 | **12.6%** | 147 |
| `(unrecorded)` | 1,250 | 1,375 | 233 | **16.9%** | 108 |
| `apsa` | 510 | 594 | 79 | **13.3%** | 37 |
| `apex` | 42 | 78 | 10 | 12.8% | 4 |

**Roughly one matched duty in eight is in a contested match**, and 147 CUPE drafts (24% of
those with a match) contain at least one.

#### ⚠ A collision is not automatically an error — read the examples

Two readings, and both occur:

```
MERGE : To operate (11 x 17) offset press (2 colour heads)
rw #1 : Heidelberg Kord offset press to produce multicolour prints
rw #2 : 11 x 17 offset press for two-colour jobs
```
↑ plausibly a legitimate **1 → 2 split**; both inheriting the frequency may be right.

```
MERGE : Provides strategic operational leadership ... post-graduate (residency) programs
rw #1 : Strategic operational leadership ... undergraduate, graduate, postgraduate curricula
rw #2 : Work closely with faculty, senior leadership, and the Associate Dean, PGME ...
```
```
MERGE : Interprets Canadian immigration law and regulations to support recruitment ...
rw #1 : Canadian immigration law and regulations to support recruitment and retention ...
rw #2 : Immigration advising services through confidential appointments, group sessions ...
```
↑ **genuine mis-matches.** `rw #2` is a different duty in each case, matched on shared
vocabulary (*"PGME/leadership"*, *"immigration"*) rather than on being the same duty. Its
frequency is inherited from a duty it does not correspond to.

**So 12.6% is an upper bound on the collision-driven error, not the error itself** — some
share is legitimate splitting. Of the three examples surfaced, two are clearly wrong.

#### What this settles, and what it does not

- ✅ **A wrong frequency is not hypothetical.** The handoff's warning that a naive threshold
  move would attach wrong frequencies is now demonstrated on live data with readable cases.
- ✅ **The defect is in the MATCHER, not the threshold.** Collisions happen *above* the bar,
  so moving the bar cannot fix them — an exclusive assignment (each merge duty claimed at
  most once) would, and that is the "matching design with evidence behind it" the handoff
  asks for. The evidence is now here.
- ❌ **Still unmeasured: precision among NON-colliding matches.** A uniquely-claimed match
  can still be the wrong duty, and only labelling settles that.

⚠ **HR-184 stays `open` at 0.2, and nothing here argues for moving it.** It argues that the
knob is the wrong lever.

## 11. 🔴 The 27.1% department gap is NOT (only) a parse gap — 40% of it is STALE DRAFTS

**Measured 2026-09-11.** HANDOFF describes the department gap as *"a parse-coverage gap"*.
That is a claim about **cause**, and it is testable: a role is built from member documents,
so if a department-less role has members whose **parse does carry a department**, the parser
found it and the *role* lost it.

### 11a. The number reproduces; the cause does not

| | roles | |
|---|---:|---|
| roles with no department | **677** | **27.1%** — reproduces the handoff exactly |
| …of which **≥1 member document states one** | **268** | **39.6% of the gap is NOT a parse failure** |
| …of which no member states one | 409 | 60.4% — a genuine parse gap |

**268 roles could carry a department from data already in the Bank**, with no re-parse and
no GPU.

### 11b. The cause, established from the code and confirmed with a control

`merge.py` picks department with `_modal_non_null`, which returns `None` **only when every
member is null** — it takes any non-null value and does not flag disagreement (a role
legitimately spans departments). So the merge cannot drop a department it was shown.

That makes a deterministic prediction: a draft **refreshed after** the v8 re-parse would
have seen the recovered department and kept it, so **no post-v8 draft can be in this set.**

| the 268 | |
|---|---:|
| last refreshed **BEFORE** the v8 parse of the member that states a department | **268** |
| last refreshed **after** it | **0** |

**Zero counter-examples, against 151 post-v8 drafts available to be counter-examples.** The
cause is not the parser and not the merge — it is that **these drafts were never rebuilt
after v8 recovered their departments**.

### 11c. The systemic version: 94% of drafts predate the current parse

| form | roles | refreshed before v8 | stale % |
|---|---:|---:|---:|
| `(unrecorded)` | 1,297 | 1,243 | 95.8% |
| `cupe` | 625 | 625 | **100.0%** |
| `apsa` | 525 | 441 | 84.0% |
| **ALL** | **2,501** | **2,350** | **94.0%** |

🔴 **`PARSER_VERSION`'s contract — "a bump ships WITH its re-parse" — is satisfied at the
DOCUMENT layer and silently unsatisfied at the ROLE layer.** Nothing re-runs the drafts, so
every parser fix since a draft was last built is invisible in it: v8's departments, v7's
**805 recovered titles**, v6's employee-group correction. This is the same shape as P3g
(*"nothing rebuilds the vector index, nothing notices"*) one layer up, and neither errors.

⚠ CUPE is 100% stale because its repair pass ran **2026-08-19**, eleven days *before* v8.

### 11d. What the in-flight JDFN pass fixes, and what it leaves

The JDFN producer pass running since 2026-09-11 rebuilds JDFN drafts from current parses, so
it will pick up v8 departments for the forms it touches:

| form | recoverable roles | |
|---|---:|---|
| `(unrecorded)` | 164 | ✅ the in-flight pass rebuilds these |
| `apsa` | 4 | ✅ |
| `excluded` | 1 | ✅ |
| **`cupe`** | **99** | 🔴 **the JDFN pass does NOT touch these** |

**So ~169 of the 268 resolve for free when the pass lands, and 99 CUPE roles need their own
scoped run.** ⚠ Re-measure after the pass rather than assuming the split holds.

### 11e. ⚠ A correction made mid-analysis, recorded because it nearly shipped

The first pass of this measurement used `canonical_jds.created_at` and concluded **100%** of
drafts were stale — which made *"268 of 268 predate v8"* **automatically true and therefore
evidence of nothing.** `created_at` is the row's birth; a producer refresh updates content
**in place**, so `updated_at` is the column that tracks when a draft was last built. With
the right column the systemic figure is **94%**, the 268 result survives *because* 151
drafts were eligible to be counter-examples and none were, and the claim became a real test
instead of a tautology.

## 12. 🔴 The JDFN pass landed — and the fidelity defects it left are in drafts NO pass can reach

**Measured 2026-09-18, after the re-baseline (2026-09-12) and its audit (2026-09-15).** Two
findings, each a *check the Bank, not the counter* result, and the second is structural.

### 12a. "8 / 3 / 3" was a NET — the per-draft defect count is 21

`make bank-audit` renders `kept − offered` as *"N drafts carry it with no source"*. That is
a net across two opposite defects in the same cohort. Decomposed per draft, with the audit
module's own predicates (`bank_audit/metrics.py`: same `_group_sql`, same
`_PARSER_VERSION`, same JSON presence tests) and reproducing its totals exactly first
(486/478, 1816/1819, 1809/1812):

| JDFN section | fabricated (kept ∧ ¬offered) | shortfall (offered ∧ ¬kept) | net | audit said |
|---|---:|---:|---:|---|
| `problem_solving` | **13** | 5 | +8 | "8 drafts" |
| `relationships` | 4 | **7** | −3 | "3 drafts" |
| `decision_making` | 4 | **7** | −3 | "3 drafts" |

**21 distinct drafts** are defective; the relationships and decision_making sets are the
*same* 11 drafts. The audit's shortfall detector (`is_shortfall`) cannot fire while the
aggregate ratio sits above 100%, so the 5 problem_solving shortfalls are invisible in its
output today. 🔴 **Follow-up for the renderer:** report fabricated and shortfall as two
counts, never a net.

### 12b. 🔴 45 JDFN drafts sit under cluster ids the clustering no longer produces

The pass refreshed 1,825 of 1,872 JDFN drafts. Of the 47 it did not touch, **45 belong to
clusters that do not exist in the current recomputation**: 2 are Builder-minted roles
(zero members — never producer candidates, by design) and **43 are producer-made drafts
stranded under a superseded cluster id**. **19 of the 21 defective drafts are among the
45** — 18 stranded producer drafts plus Multimedia Coordinator, which is one of the two
Builder-minted, reviewer-touched roles. The remaining 2 defective drafts are §12c.

Proof per id, not by subtraction. Cluster ids are content-derived (`uuid5` of membership),
so when dedup/clustering changes, a cluster gets a *new* id and its old draft stays behind
under the old one. Intersecting the 47 untouched drafts' `cluster_id`s with the recomputed
cluster list (`docs/cluster/cluster-report.csv`, 2,454 ids):

```
untouched drafts                                   47
  present in the recomputed cluster list            2   (Human Resources Professional, Human Resources Coordinator)
  ABSENT                                           45   = 43 stranded producer drafts + 2 Builder-minted (zero members)
    with a refreshed same-title twin               22
    with no same-title twin                        23
control: refreshed drafts present (sample of 200)  200 / 200
```

The arithmetic agrees: `clusters` holds **2,501** rows (3 of them Builder-minted, zero
members), **2,497** clusters carry a DRAFT, and the producer recomputes **2,453**.

**Consequences.**

- **No producer flag reaches them.** `--only-template jdfn` was exactly what the pass ran;
  it walks the *recomputed* clusters, so a stranded draft is never a candidate. The 20
  defective drafts cannot be repaired by any re-run as the producer stands.
- **The library shows them.** `jd_bank/library/service.py` reads `canonical_jds` and has
  no notion of a superseded cluster, so a stranded draft renders like any other role.
  **22 of the 45** share a title with a draft the pass *did* refresh — `Executive
  Secretary` twice, `Director, Strategic Projects and Analysis` twice — which reads as
  duplicate roles to HR, one of them stale. ⚠ Title equality is a signal, not a proof of duplication; the
  member overlap has not been measured.
- **The audit's cohort includes them.** Every stranded draft counts toward the JDFN
  carry-through ratios, so the residual fabrication the pass "left" is mostly drafts the
  pass could never have touched. That is a different finding from "the pass missed 8".

**What this needs is a ruling, not a re-run.** The precedent is P1
(`core/db/repairs/001_drop_mislabelled_cupe_drafts.sql`): a derived, idempotent condition,
refusing anything non-DRAFT or reviewer-touched, owner-ruled *delete over re-compose*. The
same shape applies — "DRAFT whose `cluster_id` is not in the current recomputation" — but
**whether a stranded draft is deleted, re-attached to its successor cluster, or kept as a
role in its own right is the owner's call**, because **23 of the 45 have *no* same-title
twin** and may be the only draft of that job.

### 12c. ⚠ UNVERIFIED — the two untouched drafts the pass DID see

`Human Resources Professional` and `Human Resources Coordinator` are in the recomputed
list, are not reviewer-touched, both fabricate `problem_solving`, and both still carry
`updated_at = 2026-08-14`. Two explanations fit and the Bank cannot separate them:
`change_log` carries no run timestamp, and the recomputed list on disk is from 2026-08-29
(2,454 clusters) while the pass recomputed 2,453. Either the pass regenerated
byte-identical content (the documented `onupdate` exception — which would mean **the
current code reproduces the fabrication**), or those two clusters dropped out between the
two recomputations. Settle it by running the producer on those two clusters alone once a
per-cluster flag exists; do not assume either.

### Method note

Every number above came from `docker compose exec -T postgres psql` against the live Bank,
with the predicates copied from the code that produced the audit, and the audit's own
totals reproduced *before* any decomposition was trusted. The first agent that looked at
this reported the 21 correctly and proposed `--only-template jdfn` as the repair; §12b is
why that proposal is wrong, and it was caught by asking the one question the report did
not — *why did the pass not fix them?*

## 13. 🔴 The re-baseline's rewrite failures: 54, not 29 — and no reason was recorded anywhere

**Measured 2026-09-18.** HANDOFF item 1.3 carried the resume container's summary line —
*29 rewrite failures, 1 audit failure* — as the debt. The counter reconciles with the Bank
exactly, and it is scoped to one of two containers.

### 13a. Two containers, one baseline; the first one's failures were never revisited

```
pass                                   drafts  rewrite_failed  audit_failed
jd-canonical-jdfn-rerun   (09-11, killed)  824       25              1
jd-canonical-jdfn-resume  (09-12, exit 0) 1001       29              1
```

`--refreshed-since` did what it was built to do — skipped the 824 the killed run had
completed — and so also skipped its 25 failures. **The re-baseline owes 54 rewrite failures
and 2 audit failures.** A `rewrite_failed` draft keeps its deterministic prose and is
counted *refreshed*: mean score **71.5 vs 75.7**, approvable **5/29 (17%) vs 305/972 (31%)**
for the resume run's 29.

### 13b. The reason is not in the log, not in `change_log`, not in `audit_log`

`runner.py:379-381` catches bare `Exception`, sets `outcome.rewrite_failed = True`, and
records nothing else. The progress line is counts-only by design; the audit payload
carries the same booleans; the container log is 81 progress lines and a summary with no
cluster id or error string in it. **Every question below could only be answered by
re-running the rewrite today**, read-only (`rewrite_merged_role` is persistence-free; the
request is rebuildable from `content` + `change_log.merge_provenance`).

### 13c. Two classes reproduced — both are the prompt contradicting the schema

Every reproduced raise is `LLMOutputInvalidError` (`client.py:287`) wrapping a pydantic
error on `SFUQualification`:

| class | clusters | what the model did | why |
|---|---:|---|---|
| **A** — `modifier` > 20 chars | 2 (one failed 2/2 attempts, identically) | filed *"or an equivalent combination of education, training and experience"* as `modifier` | `jd_harmonize_v2.system.j2` rule 5 **orders** that phrase (gate `SFU-APPROVE-QUAL-EQUIVALENT` demands it) and the schema block says only `modifier: string|null` — never that it is a short Toolkit token capped at 20 (`parsed_jd.py:96`). The whole rewrite is then discarded |
| **B** — `kind` not in the enum | 1 | `"certification"` | the schema block does not list the literals |

**Timeouts ruled out by timing**: checkpoint batches containing a failure took +17 s over
batches with none (1,781 s vs 1,764 s); a single 600 s SDK-default hang would show as
~30 min. Not size-driven either — failed inputs span 407 → 8,035 chars.

The repair loop's nudge (`client.py:75`) says only *"not valid JSON matching the required
schema"* — it never tells the model **what** was wrong, although `str(exc)` is in hand at
the re-ask. That is why a 21-character `modifier` misses twice.

### 13d. What a scoped re-run reaches, measured — and what it cannot

`--resume` skips on `rewrite_ran AND NOT rewrite_failed`, which is false for every
failure. Against the Bank the predicate selects **60** JDFN drafts, **6 of them stranded**
(§12b — unreachable by any run), so `--only-template jdfn --resume` would process **54**
and skip ~1,770: roughly **65 minutes**, not 20 hours. Pinned by
`test_resume_retries_a_cluster_whose_rewrite_failed`. Blind retry recovered 14 of 17
re-run clusters; **class A is deterministic and will leave a residue** — check the Bank
afterwards with the same predicate, not the new summary line. It will not touch the 2 audit
failures (their rewrites succeeded, so `--resume` skips them; only `--refreshed-since` would).

The audit failure inspected (`92c1b4ba`, Director, Alumni & External Relations): rewrite
succeeded, only the advisory quality-audit packet is missing. Nothing is in a bad state.

### 13e. Three small code changes, none of which is a re-run

1. **Record the reason** — `runner.py:379-381`: `type(exc).__name__` + a bounded
   `str(exc)` into `change_log.pipeline.rewrite_error`. This whole section exists because
   that line was never written.
2. **Name the error in the repair nudge** — `client.py:75-78` / `:278`: include the
   validation message. One string.
3. **Give the mandated phrase a legal home** — `jd_harmonize_v2.system.j2`: annotate
   `modifier` (short token, ≤ 20) and `kind` (the six literals) in the schema block, and
   say the equivalency sentence belongs in `text`.

Constrained decoding already fixed a ~24% enum mismatch for the audit and is deliberately
off for the rewrite (Ollama 500s on the large grammar) — schema adherence here is the
prompt's job.

### 13f. ⚠ UNVERIFIED

- What each cluster raised **that night** — irrecoverable; the classes are from re-running
  today against a host whose state may differ.
- 12 of the resume run's 29 were not re-run; other classes may exist among them.
- The killed run's 25 were identified in the Bank but none re-run.
- The audit failures' cause (a separate `audit_quality` re-run; nothing recorded).
- `finish_reason` / server-side truncation on `aria-gb10-2` — not reachable from this box.
  Successful outputs taper smoothly to ~6,048 chars with no pile-up at the HR-178
  `max_tokens` ceiling, so there is no truncation *signature*, but it was not observed.

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

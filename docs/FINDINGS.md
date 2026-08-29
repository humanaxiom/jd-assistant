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
removal a rulebook quality step.

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

### 9d. A second defect, small and cross-cutting: repeated internal spaces

`_extract_label` strips and lower-cases but never **collapses** internal whitespace, so
these match nothing at all:

`Position  Title` (8) · `Position   Title` (8) · `Position  Number(s)` (8) ·
`Department  Name` (7) · `IDENTIFICATION   Position Number` (3) ·
`Department's   Position Title` (3) · `Classification  &  Grade Approved`

Small, real, and it spans every field. One `.split()`/`join` in the label comparison.

### 9e. What this audit CANNOT see, and where the honest zeroes are

- **`classification` is not evaluated at all** — pulled by hardcoded regex, not a label,
  so a label probe says nothing about it. ⚠ Those regexes being hardcoded is itself a
  rulebook-as-data gap.
- **`grade` is under-counted for CUPE** (parser 465, readable 98): `_CUPE_GRADE_RX` finds
  grades in prose like `Secretary, Grade 6`. A negative gap is the probe's blind spot.
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

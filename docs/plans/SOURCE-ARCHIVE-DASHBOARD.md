# Plan — the source-archive dashboard (the 14,565, before harmonization)

**Status:** design only, no code. Written 2026-08-27.
Companion to [`FUNCTIONAL-ROLE-TAXONOMY.md`](FUNCTIONAL-ROLE-TAXONOMY.md) and
[`IT-SUBSET-DEMO-AND-FACETS.md`](IT-SUBSET-DEMO-AND-FACETS.md).

---

## 1. Why this is the strongest thing in the demo

Everything the Bank shows today is **after** harmonization: 2,489 roles. The archive it came
from is invisible. **The gap between those two numbers is the product**, and right now
nobody can see it.
Measured for the IT function:

| | |
|---|---:|
| ITP **source documents** in the archive | **469** |
| ITP **harmonized roles** they become | **45** |
| compression | **10.4 : 1** |
| of those, approvable today | **32 (71%)** |

> *"Your central IT job descriptions are 469 documents. They are actually 45 roles, and 32
> can go to a reviewer today. And your IT function does not stop at your department — it is
> in Library Systems, Linguistics, Facilities, Mechatronics and Earth Sciences too."*

That sentence is the demo. It needs the source side to be visible to land.

🔴 **This section previously read "1,420 documents → ~166 roles (8.5:1)". That is not
reproducible** — it came from the term list measured to miss 38 of 45 known IT roles, and no
cut point of the corrected sweep yields either number (the real ratio is a stable ~6.1:1).
The figures above use the **ITP classification family**, which is authoritative and needs no
review. The embedded-IT claim stays, as a **reviewed ranked list rather than a total**. See
[`IT-FUNCTIONAL-SWEEP-MEASUREMENT.md`](IT-FUNCTIONAL-SWEEP-MEASUREMENT.md) §4–§5.
That sentence is the demo. It needs the source side to be visible to land.

## 2. What already exists, and what does not

| dashboard | data source | live? |
|---|---|---|
| `dashboard_baseline` | `docs/baseline/summary.json` | 🔴 **static file** from `make baseline` |
| `dashboard_clusters` | committed cluster artifacts | 🔴 static |
| `dashboard_dedup` | committed dedup artifacts | 🔴 static |
| the Bank / library / review queue | Postgres | ✅ live |

**The archive-side views are all file-backed snapshots.** They were right for a build
record — an audit trail of a measured run — and they are wrong for a demo, because they
cannot be filtered, cannot answer a follow-up question, and go stale silently the moment
anything is re-run.

**"Dynamic" is the actual requirement here**, not a nice-to-have.

⚠ **A consequence I introduced and should flag:** the pilot fork strips
`docs/baseline/summary.json` (regenerable run output), and `docs/runbooks/FROM-SCRATCH.md`
does **not** list `make baseline`. So on the pilot machine the existing baseline dashboard
renders empty. **Either add `make baseline` to the runbook or supersede that page with this
one** — the second is better, and this plan is the reason.

## 3. What the source layer supports — measured

| field | coverage of 14,522 parses | usable? |
|---|---:|---|
| duties (the functional signal) | **14,067 = 96.9%** | ✅ the sweep works at source level |
| `employee_group` | 9,892 = 68.1% | ⚠ partial |
| `department` | 8,830 = 60.8% | ⚠ partial, and fragmented (739 strings) |
| format / extension | 14,565 = 100% | ✅ |
| classification family (from filename) | ITP 368 · APSA 3,351 · APEX 345 · POLY 49 · CUPE 779 | ✅ where present |
| **date** | 🔴 **not stored** — `ingest_metadata` holds only `char_count`, `original_extension`, `reason`, `status` | see §5 |

## 4. The design

A **live, DB-backed archive dashboard**, mirroring the role-side views rather than
inventing a second idiom.

### 4.1 The funnel — the headline panel

For the current filter: **source documents → parsed → clustered → roles → approvable**,
each number clickable through to the list behind it.

⚠ **Every stage must reconcile.** If 14,565 documents yield 14,522 parses, the page states
where the 43 went (unsupported format, corrupt OLE, a `.tif` scan) rather than quietly
showing a smaller number. **A funnel that loses rows without saying so is the archive-claim
error in chart form**, and this project has made that error before.

### 4.2 Facets, shared with the role side

**Functional family** (the sweep) · classification family · employee group · department ·
format · era. Same vocabulary, same code path, so a filter means the same thing on both
sides — and the funnel can be filtered end-to-end by any of them.

### 4.3 Distribution panels

Documents per functional family · per classification family · per employee group · per
era · duplicate density (how many documents behind each role — the compression story) ·
the **43 unreadable** documents, listed and named.

### 4.4 Honest rendering, same rules as the role side

- Every facet shows its coverage (*"department known for 60.8% of documents"*).
- Permanent **`(not stated)`** buckets — 5,692 documents have no department, and that is
  larger than any single department in the corpus.
- **Never blend across forms.** A CUPE score and a JDFN score are not comparable, on either
  side of the funnel.

## 5. The one gap worth fixing first

🔴 **Document date is not stored.** `ingest_metadata` carries no date, so "by era" cannot be
computed live — the static baseline page has era bands only because the baseline runner
derived them at scan time.

**Filenames carry it** (`19920430_00000536Secretary.doc`, `20260702_00138231_JDFN_...`), and
the archive spans 1967–2026. Extracting it into a queryable column at ingest is small work
and unlocks the most persuasive cut of all: **how JD practice changed over sixty years.**

⚠ Filename dates are *evidence*, not truth — a file can be renamed or re-dated. Store it as
`file_date_from_filename` and label it as such on the page. **Do not silently present a
derived date as authoritative**, and do not let it become the corpus's official date without
someone deciding that it should be.

## 6. Sequence

| # | step | size |
|---|---|---|
| 1 | Live funnel panel (source → parsed → roles → approvable), unfiltered | small |
| 2 | Wire the functional-family + classification facets through it | small–medium |
| 3 | Distribution panels, incl. the 43 unreadable listed by name | small |
| 4 | Date at ingest (§5) → the era cut | small, needs a re-ingest or backfill |
| 5 | Supersede or retire the three static dashboards | small |

**1–2 are the demo.** 3–5 are the product.

## 7. Risks

- ⚠ **Cost of live aggregation.** These are counts over 14,522 parses with a duty-text sweep;
  a naive query per page load will be slow. **Measure it before building the page** — this
  project has twice designed something that measurement showed was undeliverable.
- ⚠ **Two sources of truth.** If the static baseline pages stay alongside this one they will
  disagree, and the wrong one will be quoted. **Retire them (step 5), do not leave both.**
- ⚠ **The funnel invites a "why so few?" question.** 469 → 45 is the *value*, but it can be
  misread as loss. Label it *compression*, and make one role's source list one click away so
  the answer is visible rather than argued.

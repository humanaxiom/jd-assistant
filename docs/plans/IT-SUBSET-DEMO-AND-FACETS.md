# Plan — the IT subset demo, and filtering by area / department / classification

**Status:** design only, no code. Written 2026-08-27 after CIO support.
**Constraint honoured:** no restructuring. Everything below is additive — no new tables, no
migration, no change to how a JD is scored.

Every number here is a query against the live Bank, run while writing this. **The design
follows the measurements, not the other way round** — the first draft of this plan assumed
a department dropdown would work, and the data says it would fail in front of the CIO.

---

## 1. The demo cohort exists, and it is good

SFU's IT job family is **ITP** (Information Technology Practitioner), identifiable today:

| | |
|---|---:|
| ITP source documents in the archive | **368** |
| harmonized roles they produce | **45** |
| of those, **approvable right now** | **32 (71%)** |
| departments they span | 15 |

The compression is the story: **368 documents → 45 roles.** Individual roles absorb 43, 36,
31, 30, 29 near-identical source JDs each. That is the value proposition in one screen, and
it is real today — no new work required to *show* it.

⚠ **One thing to resolve before the CIO sees it.** Eight of the 45 roles are all titled
*"Information Technology Professional"*. Someone will ask why. Either they are genuine
distinct roles (different levels/specialisations sharing a generic SFU title) or they
should have clustered together. **Answer this before the demo, not during it** — it is a
15-minute query, and "we don't know" in the room is the one avoidable outcome.

---

## 2. What the data supports — measured, not assumed

| dimension | drafts populated | verdict |
|---|---:|---|
| `title` | 2,489 / 2,489 = **100%** | ✅ usable |
| `department` | 1,799 / 2,489 = **72.3%** | ⚠ usable **after normalisation** — see §3 |
| `employee_group` | 1,194 / 2,489 = **48%** | ⚠ partial; the rest default to JDFN |
| `classification` | **0 / 2,489 = 0%** | 🔴 **unusable today** — see §3 |
| `position_number` | 1 / 2,489 | 🔴 unusable |

## 3. Three findings that shape the design

### 3a. `classification` is parsed but never reaches a draft — recorded, **not a blocker**

**21% of parses carry it (3,053 of 14,522). 0% of drafts do.** The field survives parsing
and is lost before the draft is written — the same class of carry-through gap the Bank
audit was built to catch, one field over, and invisible because nothing was looking at it.

**It does NOT block any of this work.** The classification dimension the demo and the
facets actually need — the **family** (ITP / APSA / APEX / POLY / CUPE) — is derivable
today from source filenames (§1, §4), with no code change and no merge fix:

```
ITP 368 · APSA 3,351 · APEX 345 · POLY 49 · CUPE 779   (of 14,565 documents)
```

So this is a **recorded defect to fix on its own merits, later** — worth doing because
losing a stated field is exactly what this project keeps being bitten by, but it buys the
CIO nothing that filenames do not already give us. Filed against the deferred list, not
the demo path.

⚠ **The one thing it does constrain:** a filter on the *finer* SFU classification (a
specific pay band or level within ITP) is not buildable until it lands. Say so if asked,
rather than implying the coarse family is the whole picture.

### 3b. ⚠ `department` is fragmented — the same unit under four names

```
Information Technology Services   11
Information Technology            10
IT Services                       10
IT Client Services                 3
Academic Computing Services        3
Library Systems                    3
```

A naive department dropdown gives the CIO **10 IT roles when there are ~40**, split across
spellings. Worse, a `LIKE '%IT%'` or "technology" match sweeps in academic units that teach
computing but are not IT Services:

```
School of Computing Science                  13
School of Interactive Arts and Technology     4
Faculty of Communication, Art and Technology  6
```

**A raw department facet is a demo that misleads.** What is needed is a small
**department → canonical unit** map: rulebook data, registered like every other non-trivial
default, reviewed by someone who knows SFU's org chart. Roughly 1,799 drafts across an
estimated 150–250 distinct department strings — an afternoon of curation, not a project.

### 3c. ✅ No schema change is required

Everything the dashboard needs is already queryable from `canonical_jds` (title,
department, group, gate decision, score, grade) joined to `clusters` and
`source_documents` (filename → ITP/APSA/APEX/POLY/CUPE). **No new tables, no migration.**

---

## 4. The design, in three layers

Deliberately staged so **Layer 1 alone is a complete demo.** If time runs out, stop after it.

### Layer 1 — a saved "collection" (the demo, and the smallest useful thing)

A **named, curated set of roles** — the IT collection is the first one.

- Defined by a rulebook-registered rule (`collections.yaml`): ITP filename family +
  an explicit canonical-unit allow-list, with **explicit include/exclude overrides** so a
  human can fix a mis-sort without a code change.
- Surfaces as: `/jd-bank/ui/library?collection=it` and a **collection landing page** — the
  screen the CIO actually sees.
- **Why a curated collection rather than a live facet:** it is honest about §3b. A
  collection is *reviewed*; a facet silently inherits whatever the department string says.
  For a demo, reviewed beats clever.

**Deliverable:** one page showing 45 IT roles, 32 approvable, 368 source documents behind
them, each role clicking through to the JD and its sources.

### Layer 2 — facets on the library

Add filters to the existing library list (which already paginates and sorts):

- **Form** (JDFN / CUPE) — reliable today
- **Canonical unit** (from the 3b map) — after the map exists
- **Classification family** (ITP / APSA / APEX / POLY / CUPE) — from filename today,
  from `classification` after 3a
- **Approvable / blocked** — reliable today

⚠ **Every facet must show its own coverage** — *"department known for 72% of roles"* — and a
`(not stated)` bucket. **A facet that silently drops 28% of the corpus is the archive-claim
error in UI form**, and this project has made that error before.

### Layer 3 — statistics by area

A dashboard panel per canonical unit: role count, source documents absorbed, approvable
share, mean score *per form* (never blended — a CUPE score and a JDFN score are not
comparable), and top blocking gates.

**Reuses the existing dashboard and `bank-audit` aggregation shapes.** The one genuinely
new thing is grouping by canonical unit, which Layer 2's map provides.

---

## 5. Sequence, with the reason for the order

| # | work | why here | rough size |
|---|---|---|---|
| 1 | **Answer the duplicate-title question** | it will be asked in the room | 15 min |
| 2 | **Layer 1 collection** | this *is* the demo — filename family, no dependencies | small–medium |
| 3 | **Department → canonical unit map** (3b) | needs human curation, not code; start early so it is not the long pole | afternoon of curation |
| 4 | **Layer 2 facets** | needs 3 | medium |
| 5 | **Layer 3 stats** | needs 3 | medium |
| — | **`classification` carry-through** (3a) | ⛔ **not on this path.** A real defect, fixed on its own merits, whenever | small, merge-layer |

**1–2 are the demo, and they have no blocking dependency.** 3–5 are the product.
**The critical path to the demo runs through one curation task and one page.**

---

## 6. Risks

- 🔴 **The duplicate-title question** (§1) — unanswered, and it is the obvious question.
- ⚠ **`department` at 72%** — a stakeholder who filters and finds their unit missing
  concludes the system does not have their JDs. Show coverage explicitly.
- ⚠ **Scope creep dressed as polish.** This plan is *additive*. If it starts requiring
  changes to how a JD is scored or clustered, stop — that is restructuring, and it puts the
  pilot at risk for a demo feature.
- ⚠ **The demo is not the deliverable.** Published JDs still are. A compelling IT demo that
  produces zero approvals has moved the same distance as the last six weeks. **The demo's
  job is to get the pilot booked** — see `docs/STATUS-2026-08-24.md`.

## 7. Explicitly out of scope

Free-text search over collections · per-user saved filters · export · org-chart hierarchy
(SFU has no machine-readable one here) · anything touching scoring, clustering or the
approval bar.

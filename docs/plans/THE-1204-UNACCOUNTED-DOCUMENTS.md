# The 1,204 unaccounted documents — what they actually are

**Investigated 2026-08-28 against the live Bank.** Surfaced by the A4 funnel, which refused
to report the archive's biggest drop as one number.

**Question asked in review: "sounds like a parsing issue?"**
**Answer: partly — 43% of it. The rest is two other defects, and one of them is structural.**

---

## 1. The short version

| | |
|---|---:|
| documents parsed, in no role, with **no near-duplicate link to anything** | **1,204** |
| **A** — no title extracted (`Untitled Position`) | **385** (32%) |
| **B** — a page header, separator or letterhead captured as the title | **134** (11%) |
| **C** — a real, clean title | **685** (57%) |
| …of C, title **unique** in the archive → a genuine one-off role | **378** |
| …of C, title shared with 2–116 other documents → **should have clustered** | **~307** |

**Three different defects, three different owners.** Treating them as one number is what
kept them invisible.

## 2. 🔴 Defect 1 — title extraction (519 documents, A + B)

The parser is capturing furniture as the job title:

| what it captured | documents |
|---|---:|
| `Untitled Position` (nothing found) | 385 |
| `HUMAN RESOURCES` | 75 |
| `--------------------------------- Job Profiles ---------------------------------` | 8 |
| `═════════════════════════════════ Job Profiles ═════════════════════════════════` | 7 |
| `SIMON FRASER UNIVERSITY HUMAN RESOURCES` | 6 |
| `[pic]` (an image placeholder) | 4 |

Mean parse confidence in bucket B is **0.287**, the lowest of the three — the parser
already knows these went badly.

⚠ **`Untitled Position` is a PLACEHOLDER, not an empty string.** A check for
`title <> ''` passes on all 385 of them and reports perfect title coverage. That check was
run during this investigation and gave exactly that false all-clear.

⚠ **This is not confined to the 1,204.** Archive-wide, **2,050 of 14,522 documents (14%)
are `Untitled Position`**, and 1,395 of them *did* reach a role — so they are sitting in
published-path drafts, not only in the unaccounted set.

## 3. 🔴 Defect 2 — a unique job produces no role at all (378 documents)

**This is structural, and it is the one worth fixing first.**

| | |
|---|---:|
| clusters with 2+ member documents | **2,489** |
| clusters with exactly 1 member | **2** |
| in-role documents with no near-duplicate edge | **18** of 10,869 |

**A document reaches a role only if it has a near-duplicate.** The pipeline builds roles
out of duplicate groups, so a job description that is one of a kind — no similar document
anywhere in the archive — produces nothing. It is not dropped by a rule anyone wrote; it
simply never enters clustering.

378 of the unaccounted documents have a title that appears **exactly once** in the whole
archive. Those are, on the evidence, real and singular SFU jobs.

> **The Bank's contract is "many documents become one role". It has no answer for "one
> document is already the role".** Every unique job in the university is invisible.

⚠ **This also caps the deliverable.** Those 378 can never become published JDs under the
current pipeline, however many gates they would pass.

## 4. ⚠ Defect 3 — near-duplicate recall miss (~307 documents)

The remaining bucket-C documents share a title with other documents that *did* cluster:

| title | in archive | failed to cluster |
|---|---:|---:|
| Administrative Coordinator | 116 | 9 |
| Systems Consultant I | 65 | 7 |
| Communications Officer | 64 | 6 |
| Administrative Assistant | 60 | 5 |
| Business Analyst | 66 | 4 |
| Manager, Academic & Administrative Services | 111 | 1 |

A document titled *Administrative Coordinator* in an archive holding 115 others, with **no
near-duplicate edge to any of them**, is a Tier-2 recall miss — not a unique role.

⚠ **A shared title is evidence, not proof.** Two *Administrative Coordinators* in different
faculties may legitimately be different jobs. This bucket needs the same treatment every
other threshold in this project has needed: **measure before tuning**, and validate against
a known-good set rather than adjusting `jaccard_min` until the number looks better.

## 5. What this is not

- **Not an ingest or timing gap.** All 1,204 carry parses under **all five** parser
  versions — they have been reprocessed every time, like everything else.
- **Not empty or junk content.** Bucket C averages **863 characters** of summary and
  **7.07 duties** — *more* than the documents that did reach a role (835 / 6.76).
- **Not one employee group.** 684 have no group recorded, 431 CUPE, 76 APSA, 10 excluded,
  2 APEX, 1 Poly.

## 6. Recommended order

1. **Defect 2 first (structural).** Decide whether a singleton document should mint a
   single-member role. It is the only one of the three that silently caps what the Bank can
   ever publish, and it needs a decision before it needs code — **register it, do not
   quietly patch it**.
2. **Defect 1 next (title extraction).** It is a parser fix with a clear test:
   `Untitled Position`, separator rows and letterhead must never survive as titles. Its
   reach is 2,050 documents, well beyond this set.
3. **Defect 3 last (dedup recall).** Real, but the smallest and the most likely to be made
   worse by tuning without measurement.

⚠ **None of the three changes the published-JD count today**, so none displaces the HR asks
(B3/B4). Defect 2 changes the *ceiling*, which is why it is first among these three rather
than first overall.

## 7. Reproduce it

    -- the unaccounted set: parsed, in no current role, and with no dedup edge at all
    CREATE TEMP TABLE cur AS
      SELECT DISTINCT ON (cluster_id) * FROM canonical_jds
      ORDER BY cluster_id, version DESC;
    CREATE TEMP TABLE indraft AS
      SELECT DISTINCT (s.value->>'source_id')::uuid sid
      FROM cur c, jsonb_array_elements(c.source_document_ids) s;

    SELECT count(DISTINCT p.source_document_id)
    FROM parsed_jds p
    WHERE p.source_document_id NOT IN (SELECT sid FROM indraft)
      AND NOT EXISTS (SELECT 1 FROM dedup_edges e
                      WHERE e.source_a_id = p.source_document_id
                         OR e.source_b_id = p.source_document_id);
    -- 1204

⚠ Bucket the result by `parsed->>'title' = 'Untitled Position'` **before** concluding
anything about title coverage — `title <> ''` reports 100% and is wrong.

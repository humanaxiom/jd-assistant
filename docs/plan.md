# JD Bank — Remaining Work

**Execution order.** Everything built 2026-07-10 → 08-24 is in
[`archive/BUILD-RECORD-phases-0-9-A-G.md`](archive/BUILD-RECORD-phases-0-9-A-G.md).
Rewritten 2026-08-27 to fold in the CIO demo work.

> **Done is measured in PUBLISHED JDs. Today: 5. First milestone: 20. Then 100.**
> Not carry-through, not scores, not test counts. Evidence:
> [`STATUS-2026-08-24.md`](STATUS-2026-08-24.md).

---

# TRACK A — THE DEMO (CIO asked for it; it is what gets the pilot booked)

Detail: [`plans/IT-SUBSET-DEMO-AND-FACETS.md`](plans/IT-SUBSET-DEMO-AND-FACETS.md) ·
[`plans/FUNCTIONAL-ROLE-TAXONOMY.md`](plans/FUNCTIONAL-ROLE-TAXONOMY.md) ·
[`plans/SOURCE-ARCHIVE-DASHBOARD.md`](plans/SOURCE-ARCHIVE-DASHBOARD.md)

**The story, measured:** *469 IT source documents → 45 harmonized roles (10.4:1), 32
approvable today* — the authoritative ITP family, no review needed. **Plus** IT roles
embedded in Library Systems, Linguistics, Facilities, Mechatronics, Earth Sciences, Beedie,
Education and Health Sciences, offered as a **reviewed** list rather than a computed total.

🔴 **The former headline "1,420 documents → ~166 roles (8.5:1)" is not reproducible** — it
came from the term list measured to miss 38 of 45 seed roles, the corrected sweep's ratio is
a stable ~6.1:1, and no cut point yields either number.
[`plans/IT-FUNCTIONAL-SWEEP-MEASUREMENT.md`](plans/IT-FUNCTIONAL-SWEEP-MEASUREMENT.md) §4.

| # | task | notes | size |
|---|---|---|---|
| ✅ **A1** | ~~Answer the duplicate-title question~~ **DONE** | **20** roles (not 8) are titled *"Information Technology Professional"* and they are **distinct** — 15 specialisation × ITP-level cells, 18 of 20 level-homogeneous, a 5-role / 13-document (4.1%) tail whose examined members are real sub-specialisations. **No merge warranted.** Also corrected: ITP 368→**469** docs, APSA 3,351→**3,442**. → [`plans/IT-DUPLICATE-TITLE-ANSWER.md`](plans/IT-DUPLICATE-TITLE-ANSWER.md) | — |
| 🟡 **A2** | **IT functional family** — ✅ **measured**, build remains | **The recall validation failed usefully: there is no threshold.** 98% recall costs 1,141 candidates (46% of the corpus); at ~166 candidates recall is **48.9%**, missing half the *known* IT roles. **The score ranks a review queue; it never decides membership.** 🔴 The bias failure recurred in the opposite direction — the new list nearly misses the **analyst** half, which only the ITP family catches, so the union is load-bearing. ⚠ Word boundaries are mandatory (`lan` as a substring hit **1,568 roles**). Remaining: `functional_families.yaml` (registered, `open`) + the ranked queue. → [`plans/IT-FUNCTIONAL-SWEEP-MEASUREMENT.md`](plans/IT-FUNCTIONAL-SWEEP-MEASUREMENT.md) | small–med |
| **A3** | **Collection page** | `/jd-bank/ui/library?collection=it` — seeded with the **45 authoritative ITP roles** (32 approvable, 469 documents, 422 of them behind a current draft), each clicking through to the JD and its sources. **The reviewed `members` list is the authority, never the term list** — and A2 measured why no computed total is defensible. | small–med |
| **A4** | **Live funnel panel** | source → parsed → clustered → roles → approvable, filterable, every stage reconciling (the 43 unreadable named, not dropped). | small–med |
| **A5** | **Facets** | functional family · classification family · form · approvable. **Each shows its own coverage + a `(not stated)` bucket.** | medium |

⚠ **A1–A3 alone are a complete demo.** If time runs short, stop there.

---

# TRACK B — THE PILOT (the actual deliverable)

| # | task | who | notes |
|---|---|---|---|
| **B1** | 🔴 **TLS at the edge** | eng | `sfuai.ca:7000` is plain HTTP carrying CAS cookies. **Any demo or pilot puts a real person on it.** The only critical-path item engineering closes alone. |
| **B2** | 🔴 **Run the pilot** | needs HR | ~20 of the 1,292 approvable drafts, reviewed for real. **Success = 20 PUBLISHED JDs + the reviewer's written objections.** |
| **B3** | 🔴 **Ratify two gates** | needs HR | `SFU-APPROVE-QUAL-EQUIVALENT` (blocks 620 CUPE) · `SFU-APPROVE-KSA-ORDER` (564). One ruling beats every engineering change made in August, at zero GPU cost. |
| **B4** | **Book HR ratification** | needs HR | 214 decisions, 0 ratified. The matrix needs a calendar invitation, not another revision. |

**B1 can run in parallel with Track A. B2–B4 are asks, not tasks — make them now.**

---

# TRACK C — DEFERRED

Real, registered, and **none of it changes the published-JD count.**

| item | note |
|---|---|
| **Duty-frequency matching** | 27.7% rewritten vs 92.3% merge-only. Naive fix *measured* unsafe. Needs a design. |
| **`classification` carry-through** | Parsed on 21% of documents, reaches 0% of drafts. Real defect; ⛔ **not on the demo path** — family comes from filenames. |
| **Document date at ingest** | Not stored; filenames carry it. Unlocks the 1967–2026 era cut. Store as `file_date_from_filename` and **label it derived**. |
| **Department taxonomy** | 739 strings, 65% singletons, mechanical normalisation collapses only 7.4%. **Demoted to a *filter*** — [`plans/DEPARTMENT-TAXONOMY.md`](plans/DEPARTMENT-TAXONOMY.md). No longer blocked on an org list. |
| **HR-214 compression question** | Registered `open`. **Do not close with a threshold** — HR's call. |
| **JDFN `problem_solving`** | 228.2% fabricated (1,084 / 475). Untouched by the CUPE work. |
| **Retire the static dashboards** | `dashboard_baseline/_clusters/_dedup` read committed JSON. Two sources of truth will disagree. |
| **Phase F / Phase G / overlap graph** | Unchanged. |
| ⛔ **No further producer runs** | ~19 GPU-hours each; zero published JDs each. |

---

# Rules that apply to all of it

- **Additive only.** No schema change, nothing touching scoring, clustering or the approval
  bar. If a task starts requiring that, stop — it is restructuring, and it risks the pilot
  for a demo feature.
- **Measure before designing** anything with a score, threshold or term list, over the full
  corpus. Twice the obvious design was undeliverable.
- **Rank, never threshold.** Role-vector similarity is measured-unreliable here; embeddings
  may order a review queue, never decide membership.
- **Registered decisions.** Any non-trivial default is YAML + a register entry in the same
  PR. The build enforces it.
- **Honest rendering.** Every facet shows coverage and a `(not stated)` bucket. A view that
  silently drops rows is the archive-claim error in UI form.
- **`make gates` green before any commit touching `core/`.**

# Finished — do not reopen

Ingest / parse / extract · dedup + clustering · the two-form split · harmonization · the
CUPE content chain (every WJQ carry-through 100%, fabricated duties 0, `jd_segmenter_v5`) ·
security / SSO / deployment · JD Builder · Role Library · `make bank-audit` · the pilot fork
+ archive release.

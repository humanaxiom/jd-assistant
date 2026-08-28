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

**The story, measured:** *451 IT source documents → 45 harmonized roles (10.0:1), 32
approvable today* — the authoritative ITP family, no review needed. **Plus** IT roles
embedded in Library Systems, Linguistics, Facilities, Mechatronics, Earth Sciences, Beedie,
Education and Health Sciences, offered as a **reviewed** list rather than a computed total.

🔴 **The former headline "1,420 documents → ~166 roles (8.5:1)" is not reproducible** — it
came from the term list measured to miss 38 of 45 seed roles, the corrected sweep's ratio is
a stable ~6.2:1, and no cut point yields either number.
[`plans/IT-FUNCTIONAL-SWEEP-MEASUREMENT.md`](plans/IT-FUNCTIONAL-SWEEP-MEASUREMENT.md) §4.

| # | task | notes | size |
|---|---|---|---|
| ✅ **A1** | ~~Answer the duplicate-title question~~ **DONE** | **20** roles (not 8) are titled *"Information Technology Professional"* and they are **distinct** — 15 specialisation × ITP-level cells, 18 of 20 level-homogeneous, a 5-role / 13-document (4.1%) tail whose examined members are real sub-specialisations. **No merge warranted.** Also corrected: ITP 368→**469** docs, APSA 3,351→**3,442**. → [`plans/IT-DUPLICATE-TITLE-ANSWER.md`](plans/IT-DUPLICATE-TITLE-ANSWER.md) | — |
| ✅ **A2** | ~~IT functional family~~ **BUILT** | `functional_families.yaml`, registered **HR-215…HR-220** (`open`, `hr_informed` — they change what a reviewer is *shown*, never whether a JD passes) and **unhashed**. Measured first, and the measurement changed the design: **there is no threshold** (98% recall = 1,141 candidates = 46% of the corpus; at ~166, recall is **48.9%**). Membership = SFU's ITP classification ∪ reviewed `include` − reviewed `exclude`; **duty terms only rank a review queue**. An integration test pins it — a role stuffed with every IT term is *not* a member. 🔴 The bias failure recurred in the opposite direction (the **analyst** half, found only by the ITP family), so the union is load-bearing. → [`plans/IT-FUNCTIONAL-SWEEP-MEASUREMENT.md`](plans/IT-FUNCTIONAL-SWEEP-MEASUREMENT.md) | — |
| ✅ **A3** | ~~Collection page~~ **BUILT** | `/jd-bank/ui/collection/it` — **451 documents → 45 roles (10.0:1), 32 approvable**, each clicking through to its JD and sources, and the family's own recall note published on the page. `?queue=1` shows the **72** ranked candidates as a **separate** surface, labelled questions rather than members, with match **counts** — never a percentage, because the sweep is wrong at every cutoff. | — |
| ✅ **A4** | ~~Live funnel panel~~ **BUILT** | `/jd-bank/ui/funnel` — live from the DB, **scope-parameterised**. Archive-wide: 14,565 → 14,522 readable → 10,869 behind a role → 2,493 roles → 1,299 approvable → 4 published. **Every stage names what it lost**, and that split the biggest drop into 1,900 genuine near-duplicates, 549 duplicates of each other, and 🔴 **1,204 with no duplicate link at all** (see Track C). Also surfaced: 21 of the 469 IT documents are unreadable. | — |
| ✅ **A5** | ~~Facets~~ **BUILT** | Form **47.9%** · department **72.2%** · grade and status **100%**, each publishing its own coverage with a `(not stated)` bucket that is never folded away. No `classification` facet — the field reaches 0% of drafts, so a facet over it would render an empty dimension as though the archive had none. | — |

🔴 **A4/A5 must be scope-parameterised — [`plans/SCOPES-AND-ORG-ROLLUP.md`](plans/SCOPES-AND-ORG-ROLLUP.md).**
The IT view is **instance #1 of a general unit view**; **VPFA is next, and ITS rolls up into
it**. The IT collection resolves by **classification** (the ITP code) and **VPFA has none** —
so a unit needs a different resolver, and the seam has to exist before two dashboards and an
API learn the wrong shape. Measured: filtering on VPFA's own name returns **2 roles against a
~55+ portfolio** (27× under), because a vice-presidency is never the string written on a JD.
**The seam goes in with A4/A5; the org tree and the 739-string alias map do not — they need a
person, and inferring them is how you hand a VP a confident wrong number.**

⚠ **A1–A3 alone are a complete demo.** If time runs short, stop there.

---

# TRACK B — THE PILOT (the actual deliverable)

| # | task | who | notes |
|---|---|---|---|
| **B2** | 🔴 **Run the pilot** | needs HR | ~20 of the 1,292 approvable drafts, reviewed for real. **Success = 20 PUBLISHED JDs + the reviewer's written objections.** |
| **B3** | 🔴 **Ratify two gates** | needs HR | `SFU-APPROVE-QUAL-EQUIVALENT` (blocks 620 CUPE) · `SFU-APPROVE-KSA-ORDER` (564). One ruling beats every engineering change made in August, at zero GPU cost. |
| **B4** | **Book HR ratification** | needs HR | **79 decisions need an HR ruling**, 0 ratified — the register holds more, but the rest are engineering settings or shape what a reviewer sees and are not HR's to sign. The matrix needs a calendar invitation, not another revision. |

**B2–B4 are asks, not tasks — make them now.**

---

# ⏸ BEFORE GOING LIVE — deferred until feature development is complete

**Decided 2026-08-27.** A separate category from Track C on purpose: **Track C items may
never be built; these must be**, before the system carries anyone but us.

**These items block NOTHING** (decided 2026-08-28) — not the pilot, not the demo, not any
other work. They are the known list to close before the system goes live in the ordinary
sense. The exposure is unchanged; what is recorded is that it is not being treated as a
stop.

| # | task | who | notes |
|---|---|---|---|
| **BGL-1** | 🔴 **TLS at the edge** *(was B1)* | eng | `sfuai.ca:7000` is plain HTTP carrying CAS session cookies — anyone signing in over it hands their SFU session to whatever is on the path. Ours alone to close, no HR dependency. **Blocks nothing.** |

⚠ **This is a suppression, not a resolution.** The exposure is unchanged and unmitigated;
what changed is that we are not working on it yet and it gates nothing. Recorded so that
when it is picked up, it is picked up deliberately rather than discovered.

---

# TRACK C — DEFERRED

Real, registered, and **none of it changes the published-JD count.**

| item | note |
|---|---|
| 🔴 **The 1,204 — DIAGNOSED, three defects** | **519** title-extraction failures (`Untitled Position` on 385; page headers, separator rows and `[pic]` captured as titles on 134). **378 genuine one-off roles the pipeline cannot represent at all** — 2,489 of 2,493 clusters have 2+ members, so a job with no near-duplicate produces no role; this **caps what the Bank can ever publish** and needs a registered decision, not a patch. **~307** share a title with documents that did cluster — a Tier-2 recall miss; measure before tuning. ⚠ `Untitled Position` is a PLACEHOLDER: `title <> ''` reports 100% coverage and is wrong, and 2,050 documents archive-wide carry it — 1,395 of them already in drafts. → [`plans/THE-1204-UNACCOUNTED-DOCUMENTS.md`](plans/THE-1204-UNACCOUNTED-DOCUMENTS.md) |
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

# Tier-1 — the exact duplicates

**The read of `summary.json`. How much of the SFU JD archive is byte-for-byte redundant,
and what shape is that redundancy?**

| | |
|---|---|
| Corpus | all **14,565** files of `C:\repos\hris\fixtures\SFU_JDs` (READ-ONLY) |
| Hashed | **14,564** — SHA-256 via this repo's own `ingest.compute_sha256` |
| Not hashed | **1** — the 89 MB `.rtf` whose bytes the extractor's 50 MiB cap means we never read. Counted, never dropped. |
| Rules | `jd_rules_sfu_v4+8c004c4dadd1` (`exact_edge_topology: star`) |
| Regenerate | `make baseline JD_ARCHIVE_PATH=<archive>` then `make dedup` |

> **This report does not walk the archive.** There is exactly one chain in this repo that
> does (the Phase 2.5 baseline), and HANDOFF says *"do not hand-roll a second path"*. The
> dedup report reads the baseline's `rows.jsonl` — which already carries a `sha256` for
> every file — and groups it with **the same `group_by_sha256` the database pass calls**.
> So the edge counts below are not a second implementation that happens to agree with the
> Tier-1 pass. They are the edges it would write.

---

## The headline

**1,037 groups. 3,009 files. 1,972 of them are redundant copies — 13.5% of the archive.**

| | |
|---|---:|
| Distinct contents | **12,592** |
| Duplicate groups (>1 file) | **1,037** |
| Files sitting in one | **3,009** |
| **Redundant copies** (`files_in_groups − group_count`) | **1,972** |
| Redundancy rate (of hashed files) | **13.5%** |
| Largest group | **11 files** |

### …and every one of those 1,972 filenames was being thrown away

This is the number that made 3.1 a **provenance fix** rather than a feature.

`source_documents.sha256` was `UNIQUE`, and `ingest_document()` **returned the existing
row** on a duplicate hash. So the table was a ledger of distinct *content* while every
consumer read it as a ledger of the *archive*. Ingest the corpus under that schema and
**1,972 real archive files get no row at all** — no id, no filename, no record they ever
existed. *"Which archive files produced this canonical JD?"* was unanswerable, which is
CLAUDE.md non-negotiable #6 failing in the first table of the pipeline.

It also made `DedupTier.EXACT` and `DedupEdge` **dead code**: an edge needs two
`source_id`s, and the duplicate never got one. The schema asserted a capability it
forbade — the same class of defect as `SFU-STRUCT-HOW-WHY`, the gate that could never
*not* fire.

Fixed in migration `0002`: **one row per file**, the `sha256` index kept (non-unique) as
the Tier-1 grouping key. Duplication is now a **finding**, written as edges. Nothing is
collapsed, at any setting, ever.

---

## The archive numbers were re-verified, not quoted

The Phase 0 census (§7a) reported **1,037** hash groups and **3,009** participating files
— but it measured them with `md5sum` + shell, **a different toolchain from ours**. Under
the standing rule (*every claim about the archive must be checked against the archive*),
those numbers were re-derived through this repo's own `compute_sha256` before being used.

**They match exactly.** 1,037 and 3,009, both. The census was right, and it is now right
*in our pipeline* rather than right in someone else's.

One number does need reconciling, and it is a **population difference, not a
discrepancy**:

| Population | Files | Distinct | Redundant |
|---|---:|---:|---:|
| **Scored** (what the 2.5 baseline quotes: 14,522 → 12,557) | 14,522 | 12,557 | **1,965** |
| **All hashed files** (what Tier-1 actually ingests) | 14,564 | 12,592 | **1,972** |

The gap is **7 files**, and it is worth stating the decomposition precisely rather than
hand-waving it — an earlier draft of this page said *"7 of those 42 are byte-identical to
something else"*, which is **false** (13 are), and it got 7 right by coincidence.

The 2.5 baseline's `14,522 → 12,557` counts only *scored* files. 42 of the 43 skipped
files are hashed too (only the oversized `.rtf` is not). Adding them back adds **42 files
but only 35 new distinct contents**, so redundancy grows by 42 − 35 = **7**:

| Among the 42 skipped-but-hashed files | Files | Redundant |
|---|---:|---:|
| **6 pairs** identical to *each other* | 12 | **6** |
| **1 file** identical to a *scored* file | 1 | **1** |
| Unique in the archive | 29 | 0 |
| | **42** | **7** |

So **13** of the 42 skipped files are byte-identical to something — but only **7** of them
are *redundant copies*, because a pair contributes one new content and one redundant file,
not two. Tier-1 sees all of them, because a JD we could not extract is still a file in the
archive. **Quote 1,972 for the ledger, 1,965 for the baseline's scored population.** Both
are true.

---

## The shape: it is a thin tail, and that is what makes the topology cheap

| Group size | Groups |
|---:|---:|
| 2 | 616 |
| 3 | 207 |
| 4 | 87 |
| 5 | 49 |
| 6 | 32 |
| 7 | 17 |
| 8 | 17 |
| 9 | 6 |
| 10 | 4 |
| **11** | **2** |

**No group is larger than 11.** So the feared clique explosion does not happen on this
corpus: `clique` would cost **4,068** edges against `star`'s **1,972** — 2.1x, not 100x.

**The topology was chosen anyway, and not on cost** (HR-123, `comparison.exact_edge_topology`,
default `star`):

* byte-identity is an **equivalence relation**, so the clique's extra 2,096 edges are all
  derivable from the star by transitivity — they state nothing new;
* `build_clusters` (connected components) recovers the **identical** group from either,
  so no downstream consumer can tell them apart;
* star grows **linearly** in group size, clique **quadratically** — and Tiers 2 and 3
  write into this same table, with far larger and far messier groups. A table whose
  *exact* tier is already quadratic sets the wrong precedent for the tiers that hurt.

> ⚠ **Two invariants hold this up, they are independent, and each one broke once.** Both
> are now pinned by tests that fail with the exact measured number if the fix is removed.
>
> **1. The representative must be stable.** The pass is additive (it never deletes an
> edge), so if the rep is re-derived as "first by sort order" on every run, a duplicate
> arriving with an earlier-sorting path **re-anchors the star** and the old star's edges
> stay behind. Measured on a group of 6 ingested in reverse order, a pass after each
> arrival: **15 edges — the full clique**, where a clean star is 5. The linearity claim
> above, quietly false. The rep is therefore pinned to the one a group's edges already
> **hub on**.
>
> **2. Orientation must NOT follow the representative.** The first fix for (1) oriented
> star edges *from the anchor* — which points backwards for every member sorting before
> it, i.e. in exactly the case an anchor exists to create. Measured on the same 6: **4 of
> the 5 star edges reversed**, and a subsequent flip to `clique` produced **19 edges with
> 4 mirrored pairs**, where a clean clique on 6 is 15 with none. `source_a` is now
> **always** the earlier archive path, in both topologies, and never consults the anchor.
>
> The second one matters more than it looks: **`uq_dedup_pair_tier` is on the *ordered*
> triple, so the database cannot catch a mirrored pair.** Only the orientation rule can.

`clique` is **implemented**, not merely named — a knob whose alternative does nothing is
the `cluster_algo` landmine in a new place (see below). Because both topologies orient
their edges by the *same* total order, a star's edges are a strict **subset** of the
clique's: flipping the knob and re-running Tier-1 simply **adds** the missing pairs, and
deletes nothing. Nobody has ratified either. HR-123 is `open`.

---

## The finding that matters for Phase 3: these are not re-saves

The obvious reading of "13.5% duplicates" is *someone kept re-saving the same JD*. **On
this archive that reading is wrong.** These four numbers are **computed by `make dedup`**
and live in `summary.json` — they are not prose. (In the first cut of 3.1 they *were* only
prose, which is the exact shape of defect this project keeps paying for: a headline number
no committed code could regenerate.)

| Duplicate groups… | Groups | |
|---|---:|---|
| …spanning **more than one position id** | **798** (77%) | **different positions sharing one JD** |
| …within a single position id | 141 | genuine re-saves |
| …with no position id at all | 98 | |

**2,463 of the 3,009 duplicate files are in a group that spans several positions.** The
two largest groups are eleven *distinct position numbers* — `00133744`, `00133745`,
`00122896`, … — carrying one byte-identical JD between them.

That is not a filesystem artefact. **It is exactly the redundancy JD Bank exists to
consolidate**, and Tier-1 finds it for free, before a single embedding is computed:
77% of the exact-duplicate groups are already a role cluster with the similarity score
pinned at 1.0.

The duplicates are also *not* a legacy problem — they are spread across every era
(`new` 1,282 · `transition` 1,174 · `old` 350 · `current` 203) and are mostly `.docx`
(2,407 of 3,009).

---

## What this run does NOT license anyone to say

- ❌ *"13.5% of the archive can be deleted."* Nothing is deleted, at any setting. These
  are 1,972 real files with real names, and the ledger keeps every one of them. What the
  number says is that they carry no content the archive does not already have.
- ❌ *"The archive has 1,037 duplicate JDs."* It has 1,037 duplicate **groups**, holding
  3,009 files. The two numbers get confused constantly and they differ by 3x.
- ❌ *"Exact duplicates are re-saves of the same position."* **77% of the groups span
  several positions.** That was checked, and it is the most useful thing in this report.
- ✅ *"1,037 groups of byte-identical files hold 3,009 of the archive's 14,565 files; 1,972
  are redundant copies; 798 of those groups span more than one position."* Stamped
  `jd_rules_sfu_v4+8c004c4dadd1`.

---

## Register consequences

* **HR-123 — the edge topology** (`star`), `our_invention`, `open`. The *one* parameter in
  `comparison.yaml` that is not `hris_calibration`: hris had no Tier-1 dedup edges, so
  there is no inherited number, and labelling it `hris_calibration` would be a provenance
  lie pointing the other way.
* **`comparison.cluster_algo` can no longer lie.** It was `str = Field(min_length=1)`, so
  setting it to `louvain` would have *stamped* every persisted cluster `louvain` while
  `build_clusters` went right on running connected components — a provenance falsehood in
  whatever Phase 3 persists. HANDOFF's deadline was *"fix before Phase 3 writes a cluster
  row."* It is now a closed set of the algorithms we implement, **and `build_clusters`
  dispatches on it**, so the stamp genuinely selects the algorithm. Naming Louvain is now
  a code change plus a data change, together, or the rulebook refuses to load.

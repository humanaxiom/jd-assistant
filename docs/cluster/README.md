# Phase 3.5 — role clusters (the HR eyeball pass)

**The read of `cluster-summary.json` + the two CSVs. Which JDs are the *same role*, grouped
into clusters over the Tier-1/2/3 edge graph — and, deliberately, nothing is persisted.**

| | |
|---|---|
| Input | `dedup_edges` (Tier-1 EXACT synthesized in-runner, Tier-2 NEAR, Tier-3 ROLE) ⋈ `parsed_jds` |
| Output | `cluster-summary.json` (counts + stamps), `cluster-report.csv` (one row per cluster), `cluster-members.csv` (one row per member) |
| Persists | **nothing** — no `Cluster` row is written |
| Regenerate | `make ingest` → `make near-dup` → `make dedup-role` → `make cluster` |

> **This phase writes no database row.** A role cluster is a deterministic function of the
> edge graph + the cluster knobs, so it is recomputable at any time; and the `Cluster`
> table's `canonical_jds` FK is `ON DELETE CASCADE`, so a re-cluster reconcile would delete
> approved canonical JDs once Phase 4 creates them. Clustering is an **eyeball pass**: it
> emits a report for an HR reviewer and defers persistence to Phase 4 (harmonization),
> once HR has ratified the config.

---

## Why a single scalar threshold over the tiers is WRONG

The three tiers do **not** share a score scale, and one of them is bimodal:

| Tier | Score range | Note |
|---|---|---|
| EXACT | `1.0` | byte-identity — an equivalence relation |
| NEAR | `[0.85, 1.0]` | MinHash/Jaccard confirm |
| ROLE | `[0.5, 1.0]` | **bimodal**: 41% skill-empty pairs floor ~0.52 |

Clustering NEAR+ROLE at the raw `0.5` bar collapses, via transitive closure, into **one
8,884-JD blob — 61% of the archive**. Measured sweep of the ROLE gate against the largest
resulting cluster:

| ROLE gate | Largest cluster |
|---:|---:|
| 0.50 | **8884** (the blob) |
| 0.60 | 1940 |
| 0.65 | 1302 |
| 0.70 | 696 |
| **0.75** | **132** |
| 0.80 | 61 |

`0.75` is the **knee** — the first gate at which no cluster exceeds ~200 members and the
archive-wide blob breaks apart. So:

- **EXACT + NEAR are always-in** — strong, well-scaled evidence.
- **ROLE is gated at `cluster_role_equiv_min` (0.75, HR-162)** — *above* the Tier-3
  `role_equiv_threshold` (0.5) by design: Tier-3 records a same-role **pair**, clustering
  takes the **transitive closure**, so the bar to *merge* must be higher than the bar to
  record one edge.
- Admission does the thresholding; the runner then calls `build_clusters(threshold=0.0)`
  on the admitted edges — it must **not** re-threshold on the incomparable raw score. The
  derived `cluster_threshold` / `cluster_threshold_floor` (HR-095/096) are **retired for
  this path** and registered as such.

## EXACT connectivity is synthesized in-runner

Tier-2 structurally keeps **one MinHash signature per distinct content**, so two
byte-identical files have **no** near-dup edge — and no EXACT edges are persisted either.
Left alone, two identical JDs would split into separate clusters. The runner reconstructs
EXACT connectivity from `source_documents.sha256` (a star per duplicate group, score 1.0,
using the same `group_by_sha256` Tier-1 uses — no DB write). Measured: ~1,965 synthetic
edges reunite the identical pairs the persisted graph misses.

## The cohesion cap FLAGS, it never splits

Post-union-find, each cluster is measured and flagged (in `constraint_violations`), never
broken up:

- `band_spread` — mapped members span more than `cluster_max_band_spread` seniority bands;
- `group_mix` — the cluster mixes more than one **known** employee group (with
  `cluster_group_homogeneous`);
- `oversize` — more than `cluster_max_size` members (at gate 0.75 the >50 clusters are
  `[132, 108, 74, 57, 52]`).

⚠ **The band/group cohesion checks are near-inert on this corpus.** 70% of titles are
`family = unmapped` (no band), 64% are group-null, and at the edge level the band/group
veto drops just **30 of 148,914** pairs. The **ROLE gate**, the **size cap** and the
**human eyeball** do the real work; the band/group checks are a cheap correctness backstop
that stops the clear director↔assistant / APSA↔CUPE cases, and no more.

## The report

`cluster-report.csv` is ordered so the clusters **needing HR eyes surface first**: a
cohesion violation, then a cross-group merge, then cross-department, then high drift, then
sheer size, then a restricted title. Every row carries an empty **`human_verdict`** column
for the reviewer to fill. `cluster-members.csv` lists each member with its family, band,
representative flag and drift-from-representative.

Columns are **counts, labels and archive filenames only** — never a line of JD body text
(the same class of data `docs/dedup/` already commits). Partial-coverage columns are
honest: `employee_group` is non-null on ~36% of JDs and `department` on ~50%, so the group
and department columns are blank where the JD did not state one.

## The knobs (HR-161 … HR-166)

| Knob | Default | What it does |
|---|---|---|
| `cluster_tiers` | `[exact, near_duplicate, role_equivalent]` | which tiers connect a cluster |
| `cluster_role_equiv_min` | `0.75` | the ROLE gate — the measured blob-breaking knee |
| `cluster_max_band_spread` | `1` | flag ladder-spanning clusters |
| `cluster_group_homogeneous` | `true` | flag clusters mixing known employee groups |
| `cluster_max_size` | `50` | flag oversize clusters |
| `cluster_representative_policy` | `max_parse_confidence` | the drift/report anchor |

All six are `our_invention`, `open` (SFU HR has ratified nothing), measured against the
live edge graph, and registered in `docs/decisions/HR-DECISION-REGISTER.md`.

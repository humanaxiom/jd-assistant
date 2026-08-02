# JD Bank — Data-State Review & Grade/Level Capture Plan

**Date:** 2026-08-01 · **Scope:** all job roles · **Stores reviewed:** PostgreSQL, Neo4j,
the on-disk source archive (`C:\repos\hris\fixtures\SFU_JDs`).

## Why this exists

Grade/level is a **pay-mapped** field: compensation is set from the position's
grade/classification. It is **cross-cutting** — CUPE, APSA, APEX and Polytechnic each have
their **own** grade scale (there is *no* single 1–15 scale across groups). The JD Bank
currently cannot show a job level anywhere because the data is missing. This documents the
measured state and plans capture.

> **Measured over the whole corpus, not sampled** (per the project rule that every claim
> about the archive is checked against the archive). Every number below is reproducible
> against the live DB / archive.

---

## 1. Store inventory

| Store | Contents | Count |
|---|---|---|
| `source_documents` | one row per archive file | **14,565** |
| `parsed_jds` | structured `SFUJobDescription` per (doc, parser version) | 29,044 (= 14,522 × **v1+v2**; current = **v2**, 14,522) |
| `canonical_jds` | harmonized roles (draft/published) | **1,802** |
| `clusters` | role clusters | 1,802 |
| Neo4j `JDDocument` / `JDSection` | embedding + provenance nodes | 14,404 / 36,174 |

---

## 2. Structured field completeness — `parsed_jds` (v2, n = 14,522)

| Field | Populated | % | Notes |
|---|---:|---:|---|
| `title` | 14,522 | **100%** | but **34.4% look like a paragraph**, not a title (parse defect) |
| `position_summary` | 11,573 | 79.7% | |
| duties ≥ 1 | 11,036 | 76.0% | |
| `relationships` | 10,861 | 74.8% | |
| decision_making ≥ 1 | 9,298 | 64.0% | |
| `department` | 7,245 | 49.9% | |
| qualifications ≥ 1 | 6,949 | 47.8% | |
| `employee_group` | 5,171 | **35.6%** | almost entirely CUPE (WJQ parser stamps it); JDFN groups mostly `None` |
| `position_number` | 5,049 | 34.8% | the natural HRIS join key — only ⅓ populated |
| `additional_context` | 2,348 | 16.2% | |
| problem_solving ≥ 1 | 2,459 | 16.9% | |
| **`grade`** | **430** | **3.0%** | **and mostly GARBAGE** (see §4) |

## 3. Harmonized roles — `canonical_jds` (n = 1,802)

- **`grade`: ~0%** (0 of a 400-role sample). Same broken field, so the roles carry no level.
- `employee_group` on the canonical content: **not set** (`None`) — the producer doesn't
  copy it onto the harmonized record.

## 4. The `grade` field is present *and wrong*

Of the 430 populated `grade` values, **428 are on CUPE docs** and the values are **adjacent
text the parser mis-captured**, not grades:

```
'Department Name/Section: ' ×37   'Effective Date: February ' ×14
'Assistant' ×23                   '_________________________' ×16
'Guest Services Clerk' ×14        'III (Digital Printing)' ×12
```

A handful are real (`'Clerk Gr. 6'`, `'Clerk, Grade 7'`). **Conclusion: the existing
`SFUJobDescription.grade` free-string field + its extraction are unusable** — effectively
empty and untrustworthy where non-empty.

## 5. Neo4j graph — no domain metadata

The graph is purely the **retrieval substrate**: `JDDocument` (14,404) and `JDSection`
(36,174) nodes joined by `HAS_SECTION`. Every property is an **embedding or a provenance
stamp** (`embedding`, `model`, `dimensions`, `text_sha256`, `embed_stamp`,
`source_document_id`, `parsed_jd_id`, `parser_version`, `section`). **There is no grade,
level, classification, or employee_group in the graph** — it was never a metadata store.

## 6. Is grade recoverable from the source documents?

Measured by extracting text from real archive files and searching for a grade:

| Population | Grade present in the document text | Implication |
|---|---:|---|
| **CUPE** (~16% of corpus, ~4,731 docs) | **64%** carry a parseable `Grade N` (e.g. Grade 6/7/8/10) | **parseable** — the JD prints the pay grade |
| **JDFN** (APSA/APEX/Poly + unstamped) | grade **largely absent** from the text | **not in the JD** — see below |

For JDFN, the SFU template has a *"Classification & Grade Approved:"* field that is
**typically blank in the document**: APSA/exempt grading is done **after authoring** by a
job-evaluation committee and recorded in the **HRIS**, not written back into the JD file.
So for most JDFN roles the grade is simply **not in the source** — it must be **entered** or
**imported from the authoritative HR system**.

---

## 7. Bottom line

Grade/level is **missing and unreliable in every store**:

- Postgres structured field: **3% populated, garbage**; canonical roles **~0%**.
- Neo4j: **none** (by design).
- Source documents: **CUPE ~64% parseable**, **JDFN largely absent** (lives in the HRIS).

There is no shortcut to "just show the grade" — it has to be **captured**, per group, with
**provenance** (parsed vs. entered vs. HRIS).

---

## 8. Capture plan

### Phase A — Model it properly + parse where available *(parse-first)*
1. **Replace the free-string `grade`** with a structured, validated value:
   `grade: { scheme: cupe|apsa|apex|poly, value: str, source: parsed|entered|hris } | None`.
   Register the **per-group grade schemes** (allowed values + ordering) as rulebook DATA —
   pay maps to them, so they are decision parameters and belong in the register (`open`
   until HR ratifies the scales; do **not** hardcode). *Correct the earlier "APSA 1–15"
   assumption — confirm each group's real scale with HR first.*
2. **Targeted, group-aware extractor** to replace the noise field:
   - CUPE: pull `Grade N` from the classification line (≈64% recoverable, measured).
   - JDFN: read the *"Classification & Grade Approved:"* field **only when filled**.
3. Re-parse to backfill; **measure** resulting coverage per group (add to the baseline).

### Phase B — Capture path where the JD has no grade *(enter-where-absent)*
For the JDFN majority with no grade in the document:
1. **Builder**: add a Grade field (scheme constrained by `employee_group` + value) to
   authoring; the author/HR enters it (`source=entered`).
2. **Reviewer edit view**: the same field, so HR can set/correct grade at review time.
3. Advisory only at first — **not a publish gate** (register `open`).

### Phase C — HRIS import *(authoritative, optional, best source)*
The definitive grade is in the HRIS, keyed by **position number**. An import that joins on
`position_number` would backfill grade at scale — but `position_number` is only **35%**
populated (improve extraction first), and grade is compensation data, so it needs an **HR
export + FIPPA review** before ingest (`source=hris`).

### Phase D — Surface it
Once captured with provenance, show **Grade** on the library / role / reader (the column
the review asked for), **labeled by scheme** and annotated with its **source** (parsed /
entered / HRIS), and `—` only when genuinely unknown.

### Decisions HR must make (register these)
- The **grade scheme + scale** for each employee group (values, order).
- Whether grade is ever a **publish gate** (recommend: no, advisory).
- Whether an **HRIS position→grade import** is in scope (FIPPA / compensation data).

---

## 9. Cross-cutting dependency: parser quality

The same defect behind the missing grade also produces **34.4% paragraph titles** and low
`position_number` / `department` completeness. A **parser-quality workstream** — reading
the JD's header/classification block into the right structured fields (title, position
number, department, grade) — is the common upstream fix and a prerequisite for both the
grade parse-path (Phase A) and the HRIS join key (Phase C).

## 10. Reproduce these numbers

- Postgres field completeness / grade values / group distribution: aggregate over
  `parsed_jds` where `parser_version='jd_segmenter_v2'` (see the queries used on 2026-08-01).
- Source-doc grade presence: `src.jd_bank.ingest.extract.extract_text_from_path` over a
  stratified archive sample (CUPE grade-in-text = 58/90 ≈ 64%).
- Graph: `MATCH (n) RETURN labels(n), count(*)` + `CALL db.propertyKeys()`.

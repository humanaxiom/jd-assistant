# A1 — the duplicate-title question, answered

**Measured 2026-08-27 against the live Bank.** Every number below is a query, and the
queries are in §5 so they can be re-run. This closes Track A1 in
[`docs/plan.md`](../plan.md) and the ⚠ block in [`../../HANDOFF.md`](../../HANDOFF.md).

---

## 1. The one-sentence answer for the room

> **They are distinct. "Information Technology Professional" is SFU's generic ITP
> classification title, not a job — the real differentiators are the ITP level (I–IV) and
> the specialisation, and the system clustered on duty content, which is the right axis.
> 20 roles resolve to 15 distinct specialisation × level cells. The 5 that share a cell
> are small (13 of 315 documents, 4.1%) and, on inspection, real sub-specialisations.**

**It was not a clustering miss.** No merge is warranted before the demo.

---

## 2. 🔴 Two numbers in the plan and handoff were wrong

| claim | was | **is** | why it was wrong |
|---|---:|---:|---|
| ITP-titled roles | 8 | **20** | wrong under *every* cohort definition tested — see §5 |
| ITP source documents | 368 | **469** | 368 was never consistent with its own derived figures |

**`45` roles and `32` approvable were right** — they reproduce exactly from
`filename ILIKE '%ITP%'`, which yields **469** documents, not 368. So the cohort was
correct and only the document count was mis-transcribed. Adopting that definition as
canonical keeps the demo headline stable:

> **451 IT source documents → 45 harmonized roles → 32 approvable today (71%).**

(Corrected again on 2026-08-27 while building the page: 469 is the count of ITP-named
files in the ARCHIVE, but 47 of them sit behind no current role and 29 non-ITP files were
clustered in, so `469 → 45` does not reconcile. **451** is the documents actually behind
the 45 roles, and it is what the collection page shows.)

⚠ **The compression ratio improves with the correction** (10.0:1, not 8.2:1). It was
understated, not overstated — but a number that cannot be reproduced is a number that
will be challenged in the room, which is the whole reason for this document.

⚠ **47 of the 469 ITP documents sit behind no current draft.** Say "469 documents, 422
behind a role today" rather than implying full coverage.

---

## 3. The evidence: specialisation × ITP level

20 cohort roles carry the title. Their sources' filenames carry the ITP level
(`..._ITP_III_...`), and the drafts' own `position_summary` separates four specialisations:

| specialisation | I | II | III | IV | mixed | roles | docs | approvable |
|---|---|---|---|---|---|---:|---:|---:|
| network / telecom | 20 + 3 | 30 | 43 + 2 | 12 | — | 6 | 110 | 5 |
| applications | 36 + 3 | 31 + 3 + 2 | — | 9 | 13, 5 | 8 | 102 | 5 |
| business analysis | 26 | 24 | 2 | 8 | — | 4 | 60 | 3 |
| consultative support / training | 29 | 14 | — | — | — | 2 | 43 | 1 |
| **total** | | | | | | **20** | **315** | **14** |

*(cell values are documents absorbed by each role in that cell)*

**18 of the 20 roles are level-homogeneous** — every source document in the cluster carries
the same ITP roman level. The two exceptions mix adjacent levels only (I/II and II/III),
which is what a genuine level boundary looks like, not a scrambled cluster.

**15 distinct cells hold the 20 roles.** That is the answer: the split is
specialisation × level, and it is legible.

## 4. The tail, stated honestly

Four cells hold more than one role. The smaller member of each is the tail:

| cell | roles | the smaller member(s) |
|---|---:|---|
| network / III | 2 | 2 docs |
| applications / I | 2 | 3 docs |
| applications / II | 3 | 3 docs, 2 docs |
| network / I | 2 | 3 docs |

**5 roles, 13 documents — 4.1% of the cohort.** Two were read directly rather than
assumed:

- **network / III:** the 43-document role is *enterprise network architecture*; the
  2-document role is *server & storage operations* (SUN Solaris, Red Hat, Microsoft OS,
  reporting to the Associate Director, Storage & Servers). **Different work.**
- **applications / I:** the 36-document role *builds* software; the 3-document role leads
  with *feasibility and cost-benefit studies, vendor proposals, specification review*.
  Closer, but a defensible analyst-vs-builder split.

⚠ **This is a spot check of 2 of the 5, not a proof about all 5.** The claim this document
supports is "the tail is small and the two examined are real", not "no two ITP roles
should ever merge". If asked, say that.

**Recommendation: change nothing.** A merge here touches clustering, which
[`IT-SUBSET-DEMO-AND-FACETS.md`](IT-SUBSET-DEMO-AND-FACETS.md) §6 puts explicitly out of
scope, and it would move 13 documents.

## 5. Reproduce it

Cohort definition sensitivity — **the ITP-titled count is 20 under all four**, so the
"8" was not a definition difference:

| definition | docs | roles | approvable | ITP-titled |
|---|---:|---:|---:|---:|
| `ILIKE '%ITP%'` ← **canonical, matches the plan's 45/32** | 469 | 45 | 32 | **20** |
| `ILIKE '%\_ITP\_%'` | 355 | 41 | 28 | **20** |
| `~ '(^\|[^A-Za-z])ITP([^A-Za-z]\|$)'` | 459 | 44 | 31 | **20** |
| `~ 'ITP[_ ]?(I\|II\|III\|IV\|V)'` | 458 | 42 | 29 | **20** |

```sql
-- current version per cluster; "approvable" is the gate decision the bank audit uses
CREATE TEMP VIEW cur AS
  SELECT DISTINCT ON (cluster_id) * FROM canonical_jds ORDER BY cluster_id, version DESC;
CREATE TEMP VIEW itpdoc AS
  SELECT id, filename FROM source_documents WHERE filename ILIKE '%ITP%';

SELECT (SELECT count(*) FROM itpdoc)                                    AS itp_docs,
       count(DISTINCT c.cluster_id)                                     AS roles,
       count(DISTINCT c.cluster_id) FILTER (WHERE
         (c.change_log->'validator'->'gate_decision'->>'approved')::boolean) AS approvable,
       count(DISTINCT c.cluster_id) FILTER (WHERE
         c.content->>'title' = 'Information Technology Professional')   AS itp_titled
FROM cur c, jsonb_array_elements(c.source_document_ids) s
JOIN itpdoc d ON d.id = (s.value->>'source_id')::uuid;
--  469 | 45 | 32 | 20
```

⚠ **`validation_reports` is empty (0 rows) and `canonical_jds.validation_report_id` is NULL
for every draft.** Approvability lives *only* in
`change_log->'validator'->'gate_decision'->>'approved'`. A query against
`validation_reports` returns 0 approvable and looks like a real answer — this is the
"a wrong query returns 0 exactly as convincingly" trap, hit while writing this document.

## 6. What this changes

- **A1 is closed.** The answer is defensible and the correction is in hand.
- **A2/A3 proceed unchanged.** The cohort is the same set of roles; only its document
  count was mis-stated.
- **Nothing here touches clustering, scoring or the approval bar.**

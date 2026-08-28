# A2 — the IT functional sweep, measured

**Measured 2026-08-27 against the live Bank (2,493 current-version roles).** This is the
step 3 the taxonomy plan demanded — *"measure recall against the seed, and let it fail"*
([`FUNCTIONAL-ROLE-TAXONOMY.md`](FUNCTIONAL-ROLE-TAXONOMY.md) §4). It failed usefully.

**Seed:** the 45 ITP-filename roles, which are unambiguously IT and need no review
([`IT-DUPLICATE-TITLE-ANSWER.md`](IT-DUPLICATE-TITLE-ANSWER.md)).

---

## 1. The headline: there is no threshold, and that is the finding

Scoring each role by **how many distinct IT terms its title + summary + duties contain**
(37 terms, word-boundary matched), against the 45-role seed:

| min score | candidates | seed found | **recall** |
|---:|---:|---:|---:|
| 1 | 1,141 (46% of corpus) | 44 | **97.8%** |
| 2 | 546 | 36 | 80.0% |
| 3 | 311 | 30 | 66.7% |
| 4 | 213 | 25 | 55.6% |
| **5** | **153** ← *the plan's ~166* | **22** | **48.9%** |
| 7 | 68 | 8 | 17.8% |
| 9 | 26 | 5 | 11.1% |

**At the candidate count the plan assumed (~166), the sweep misses more than half of the
roles we already know are IT.** To keep 98% recall it must return 46% of the entire archive.

> ⓘ **Re-measured 2026-08-27 when the score was implemented.** The first pass counted
> distinct matched *strings*; the shipped code counts distinct matched *terms*. Under the
> first definition `servers?` scored 2 for a JD saying both "server" and "servers" — one
> concept, two points — so a role that happened to use both spellings outranked one that
> did not. The table above is the corrected count. **Every conclusion is unchanged**: the
> 98%/1,141 and 48.9%-at-~166 endpoints are identical, because at those cutoffs the
> double-counting changes no role's side of the line. The middle and upper rows moved by
> 5–10% (at ≥7: 75→68 candidates, 22.2%→17.8% recall), which is why the rulebook and the
> register quote the corrected figures.
> 🔴 **No cut point is both precise and complete.** This is the same shape as the measured
> role-vector finding — *rank, never threshold*. It is now measured for duty terms too.

**Consequence:** the score is a **ranking signal for a review queue**, not a membership
test. That is what [`FUNCTIONAL-ROLE-TAXONOMY.md`](FUNCTIONAL-ROLE-TAXONOMY.md) §3.2
already specified; it is no longer a precaution but a measurement.

## 2. 🔴 The bias failure recurred — in the opposite direction

§2 of the taxonomy plan recorded a term list that missed 38 of 45 seed roles because it
encoded *IT = desktop support*. This list is far better (98% recall at score ≥ 1) but the
roles it **nearly** misses are not random:

| score | title | sources |
|---:|---|---:|
| 0 | Business Analyst | 4 |
| 1 | Business Analyst | 8 |
| 1 | Information Technology Business Analyst | 5 |
| 1 | Business Systems Analyst | 4 |
| 1 | Business Analyst | 3 |
| 1 | Information Security Analyst | 2 |
| 1 | Business Analyst, Human Resources | 2 |
| 1 | Service Management Applications Manager | 2 |

> **A duty-term sweep cannot see the analyst half of IT.** Analysts write duties about
> *processes, requirements and stakeholders*, not about *servers, networks and operating
> systems*. The technology vocabulary that identifies an engineer is absent from a genuine
> IT analyst's JD.

**This is the measured justification for "union, never intersect".** The classification
family (the ITP filename) is not a redundant convenience — for these nine roles it is the
*only* signal that works. An intersection design would delete the analyst half of the IT
function, and it would look precise while doing it.

⚠ **Expect this failure again in every family somebody defines.** It has now happened twice
in the same family, in two different directions, to two different term lists.

## 3. The ranking is good — and it proves the embedded-IT claim

The top non-seed candidates, with their departments:

| score | title | department | sources |
|---:|---|---|---:|
| 13 | Library Systems Technician | Library Systems | 4 |
| 13 | Technical Support Specialist | Linguistics | 3 |
| 13 | Facilities Technology Specialist | Facilities Management | 2 |
| 12 | Desktop and Network Support Technician | Faculty of Science | 3 |
| 12 | Computer Systems Technician | Mechatronic Systems Engineering | 2 |
| 11 | Systems Support Technician | Facilities Strategic Support | 7 |
| 11 | Computer Systems Administrator | Computing Science | 5 |
| 11 | Computer Systems Analyst | Mechatronics | 4 |
| 11 | Research Technician | FASS Office of the Dean | 2 |
| 11 | Technical Support Technician | Earth Sciences | 2 |
| 10 | Computer Support Technician | Learning & Teaching Technology | 6 |
| 10 | Information Technology Specialist | Faculty of Health Sciences | 2 |

**Not one is in a central IT department.** The taxonomy plan's §1 claim survives a much
better term list — **IT at SFU is embedded, and no org chart gathers it.**

⚠ *Research Technician (FASS)* is the false positive, and the taxonomy plan predicted that
exact role by name. **Candidates are candidates.**

## 4. 🔴 The "1,420 documents → ~166 roles (8.5:1)" headline is not reproducible

That figure is quoted in `HANDOFF.md` and `docs/plan.md` as Track A's story. It derives
from the **biased term list of §2** — the one measured to miss 38 of 45 seed roles — and no
cut point of the corrected sweep reproduces it:

| union (seed ∪ score ≥ k) | roles | documents | ratio |
|---:|---:|---:|---:|
| ≥ 3 | 326 | 1,837 | 5.6:1 |
| ≥ 4 | 233 | 1,433 | 6.2:1 |
| ≥ 5 | 176 | 1,085 | 6.2:1 |
| ≥ 6 | 133 | 823 | 6.2:1 |
| *claimed* | *166* | *1,420* | *8.5:1* |

**Neither the counts nor the ratio match any cut.** The measured ratio is stable at ~6.2:1,
not 8.5:1. **Do not say "1,420 → 166" in front of the CIO.**

## 5. What to say instead — and it is stronger

Lead with the number that is **authoritative and needs no review**:

> **451 IT source documents → 45 harmonized roles (10.0:1), 32 approvable today.**

Then the embedded finding, as a *reviewed* claim rather than a computed one:

> **And that is only central IT.** A duty-text sweep surfaces IT roles in Library Systems,
> Linguistics, Facilities, Mechatronics, Earth Sciences, Beedie, Education and Health
> Sciences — **the IT function is larger than the IT department, and we can show you the
> ranked list.**

**A ranked candidate list a human has reviewed is a stronger artefact than a computed total
nobody can defend** — and §1 says a computed total is not available at any threshold.

### 🔴 5a. Three document counts, and only one of them belongs in the headline

Building the page surfaced that "469 documents → 45 roles" mixes two different
quantities. All three reconcile, and all three were verified against the live Bank:

| | |
|---|---:|
| ITP-named documents in the archive | **469** |
| …of those, behind a current role | **422** |
| …of those, behind **no** current role | **47** |
| non-ITP documents clustered *into* these IT roles | **+29** |
| **documents actually behind the 45 roles** | **451** |

**The headline is `451 documents → 45 roles (10.0:1), 32 approvable.`** That is the one
a stakeholder can click through and check, because every one of the 451 is reachable
from a role page. `469 → 45` is not self-consistent: 47 of the 469 sit behind nothing,
so the arrow does not hold.

⚠ The collection page shows **451**, deliberately. If someone quotes 469 from an earlier
draft of this plan and the screen says 451, that gap is exactly the sort nobody notices
until it is on a projector.

## 6. What this means for the build

| | |
|---|---|
| **`members` is the authority** | exactly as [`FUNCTIONAL-ROLE-TAXONOMY.md`](FUNCTIONAL-ROLE-TAXONOMY.md) §3.3 specified. Now measured, not assumed. |
| **Seed the IT family with the 45 ITP roles** | authoritative from the filename family, reviewable in minutes, correct today. |
| **Ship the score as a review-queue ORDER** | never as a filter, never as a percentage, never displayed as a confidence. |
| **A review queue of ~60** | score ≥ 7 yields 68 roles of which 8 are already seed. That is a tractable human pass and it contains the whole top table of §3. |
| **No schema change** | scoring runs over `canonical_jds.content`; the reviewed list is rulebook YAML. |

⚠ **The score must be registered** as a non-trivial rulebook default (term list + the
review-queue ordering), `status: open`, per CLAUDE.md.

## 7. ⚠ A trap worth recording: `lan` matched 1,568 roles

The first sweep used `LIKE '%term%'` — the pattern the taxonomy plan's YAML sketch implies.
`lan` then matches **plan**, **planning**, **Langara**: **1,568 of 2,493 roles, 63% of the
corpus**, from one three-letter term.

**Word-boundary matching is mandatory, not an optimisation.** With it, `lan` matches 11
roles. A substring sweep would have produced a confident, wrong, and *plausible-looking* IT
cohort — 63% is not obviously absurd when you are expecting "IT is bigger than you think".

## 8. Reproduce it

The seed, and the score:

    CREATE TEMP TABLE seed AS
    SELECT DISTINCT c.cluster_id FROM
     (SELECT DISTINCT ON (cluster_id) * FROM canonical_jds
      ORDER BY cluster_id, version DESC) c,
     jsonb_array_elements(c.source_document_ids) s
    JOIN source_documents d ON d.id = (s.value->>'source_id')::uuid
    WHERE d.filename ILIKE '%ITP%';                              -- 45 roles

    CREATE TEMP TABLE scored AS
    WITH cur AS (SELECT DISTINCT ON (cluster_id) * FROM canonical_jds
                 ORDER BY cluster_id, version DESC),
    blob AS (SELECT c.cluster_id, c.content->>'title' AS title,
                    jsonb_array_length(c.source_document_ids) AS nsrc,
                    lower(coalesce(c.content->>'title','')           || ' ' ||
                          coalesce(c.content->>'position_summary','') || ' ' ||
                          coalesce(c.content->'duties','[]'::jsonb)::text) AS txt
             FROM cur c)
    SELECT b.cluster_id, b.title, b.nsrc,
      (SELECT count(*) FROM terms t WHERE b.txt ~ t.t)::int AS score,
      EXISTS(SELECT 1 FROM seed s WHERE s.cluster_id = b.cluster_id) AS in_seed
    FROM blob b;

    SELECT k, count(*) FILTER (WHERE score>=k) candidates,
              count(*) FILTER (WHERE score>=k AND in_seed) seed_found
    FROM scored, generate_series(1,9) k GROUP BY k ORDER BY k;

`terms` is **one row per term**, each wrapped in word boundaries — written literally as
backslash-m at the start and backslash-M at the end, e.g. `\m(servers?)\M`:

    CREATE TEMP TABLE terms(t text);
    INSERT INTO terms VALUES
    ('\m(network)\M'),('\m(servers?)\M'),('\m(hardware)\M'),('\m(software)\M'),
    ('\m(troubleshooting)\M'),('\m(troubleshoot)\M'),('\m(operating systems?)\M'),
    ('\m(architecture)\M'),('\m(identity management)\M'),
    ('\m(application development)\M'),('\m(data centre)\M'),('\m(databases?)\M'),
    ('\m(systems analyst)\M'),('\m(programming)\M'),('\m(programmer)\M'),
    ('\m(cybersecurity)\M'),('\m(information security)\M'),('\m(help ?desk)\M'),
    ('\m(workstations?)\M'),('\m(lan)\M'),('\m(wan)\M'),('\m(firewall)\M'),
    ('\m(virtualization)\M'),('\m(api)\M'),('\m(sql)\M'),('\m(linux)\M'),('\m(unix)\M'),
    ('\m(active directory)\M'),('\m(technical support)\M'),('\m(web application)\M'),
    ('\m(middleware)\M'),('\m(information technology)\M'),('\m(computing)\M'),
    ('\m(desktop)\M'),('\m(encryption)\M'),('\m(scripting)\M'),('\m(debugging)\M');

⚠ **One row per term, not one alternation over all of them** — the score is a count of
TERMS. Under a single alternation with `count(DISTINCT m[1])`, `servers?` scores 2 for a
JD saying both "server" and "servers": one concept, two points. That is the definition
this document was first measured under; see the note in §1.

⚠ The word boundaries are load-bearing (§7) — without them this returns a different and
wrong answer, not an error.

⚠ Approvability is `change_log->'validator'->'gate_decision'->>'approved'`.
`validation_reports` is empty and querying it returns a convincing 0.

# A2 — the IT functional sweep, measured

**Measured 2026-08-27 against the live Bank (2,493 current-version roles).** This is the
step 3 the taxonomy plan demanded — *"measure recall against the seed, and let it fail"*
([`FUNCTIONAL-ROLE-TAXONOMY.md`](FUNCTIONAL-ROLE-TAXONOMY.md) §4). It failed usefully.

**Seed:** the 45 ITP-filename roles, which are unambiguously IT and need no review
([`IT-DUPLICATE-TITLE-ANSWER.md`](IT-DUPLICATE-TITLE-ANSWER.md)).

---

## 1. The headline: there is no threshold, and that is the finding

Scoring each role by **how many distinct IT terms its title + summary + duties contain**
(45 terms, word-boundary matched), against the 45-role seed:

| min score | candidates | seed found | **recall** |
|---:|---:|---:|---:|
| 1 | 1,141 (46% of corpus) | 44 | **97.8%** |
| 2 | 598 | 36 | 80.0% |
| 3 | 354 | 30 | 66.7% |
| 4 | 226 | 25 | 55.6% |
| **5** | **162** ← *the plan's ~166* | **22** | **48.9%** |
| 7 | 75 | 10 | 22.2% |
| 9 | 31 | 5 | 11.1% |

**At the candidate count the plan assumed (~166), the sweep misses more than half of the
roles we already know are IT.** To keep 98% recall it must return 46% of the entire archive.

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
| ≥ 3 | 369 | 2,098 | 5.7:1 |
| ≥ 4 | 246 | 1,500 | 6.1:1 |
| ≥ 5 | 185 | 1,135 | 6.1:1 |
| ≥ 6 | 141 | 859 | 6.1:1 |
| *claimed* | *166* | *1,420* | *8.5:1* |

**Neither the counts nor the ratio match any cut.** The measured ratio is stable at ~6.1:1,
not 8.5:1. **Do not say "1,420 → 166" in front of the CIO.**

## 5. What to say instead — and it is stronger

Lead with the number that is **authoritative and needs no review**:

> **469 IT source documents → 45 harmonized roles (10.4:1), 32 approvable today.**

Then the embedded finding, as a *reviewed* claim rather than a computed one:

> **And that is only central IT.** A duty-text sweep surfaces IT roles in Library Systems,
> Linguistics, Facilities, Mechatronics, Earth Sciences, Beedie, Education and Health
> Sciences — **the IT function is larger than the IT department, and we can show you the
> ranked list.**

**A ranked candidate list a human has reviewed is a stronger artefact than a computed total
nobody can defend** — and §1 says a computed total is not available at any threshold.

## 6. What this means for the build

| | |
|---|---|
| **`members` is the authority** | exactly as [`FUNCTIONAL-ROLE-TAXONOMY.md`](FUNCTIONAL-ROLE-TAXONOMY.md) §3.3 specified. Now measured, not assumed. |
| **Seed the IT family with the 45 ITP roles** | authoritative from the filename family, reviewable in minutes, correct today. |
| **Ship the score as a review-queue ORDER** | never as a filter, never as a percentage, never displayed as a confidence. |
| **A review queue of ~65** | score ≥ 7 yields 75 roles of which 10 are already seed. That is a tractable human pass and it contains the whole top table of §3. |
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
      (SELECT count(DISTINCT m[1]) FROM regexp_matches(b.txt, TERMS_RE, 'g') m)::int
        AS score,
      EXISTS(SELECT 1 FROM seed s WHERE s.cluster_id = b.cluster_id) AS in_seed
    FROM blob b;

    SELECT k, count(*) FILTER (WHERE score>=k) candidates,
              count(*) FILTER (WHERE score>=k AND in_seed) seed_found
    FROM scored, generate_series(1,9) k GROUP BY k ORDER BY k;

`TERMS_RE` is the 45 terms as one alternation, wrapped in word boundaries — written
literally as backslash-m at the start and backslash-M at the end:

    \m(network|servers?|hardware|software|troubleshooting|troubleshoot|operating systems?
    |architecture|identity management|application development|data centre|databases?
    |systems analyst|programming|programmer|cybersecurity|information security|help ?desk
    |workstations?|lan|wan|firewall|virtualization|api|sql|linux|unix|active directory
    |technical support|web application|middleware|information technology|computing|desktop
    |encryption|scripting|debugging)\M

⚠ The word boundaries are load-bearing (§7) — without them this returns a different and
wrong answer, not an error.

⚠ Approvability is `change_log->'validator'->'gate_decision'->>'approved'`.
`validation_reports` is empty and querying it returns a convincing 0.

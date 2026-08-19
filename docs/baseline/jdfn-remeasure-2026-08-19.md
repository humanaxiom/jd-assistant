# S-5 — the JDFN re-measure, and what it says the fix is

**Measured 2026-08-19 against the live Bank and `parsed_jds` at `jd_segmenter_v4`.**
Every number below is a query, reproduced inline. This closes the measurement half of
S-5 in `docs/tasks/cupe-review-findings-2026-08-19.md`; it also argues that the *other*
half — "template-scope the guard" — is the wrong fix, and says what the right one is.

## Why any of this was needed

The review found that "JDFN is the untouched control" — a claim made repeatedly across
Phases B–E — is false. `_SECTIONS_NEVER_INVENTED` (CUPE Phase D) empties
`decision_making` / `problem_solving` / `relationships` when the grounded merge draft
does not have them. And `merge_cluster` **never populates those three for anyone**
(`core/src/jd_core/bank/merge.py` ~742: "4.1 deliberately does NOT merge
decision_making / problem_solving / relationships / position_number (out of scope)").

So the antecedent is true on every real cluster of every template. The guard was
argued, measured and tested for CUPE; it has been firing on the whole JDFN cohort since
Phase D, and the impact was never put in a diff.

## What it cost, exactly

The JDFN drafts split cleanly into pre-guard and post-guard by whether their
`change_log.anti_fabrication` carries a `scrubbed_sections` key at all.

```sql
SELECT (change_log->'anti_fabrication'->>'scrubbed_sections' IS NOT NULL) AS guarded,
       count(*),
       count(*) FILTER (WHERE jsonb_array_length(
         coalesce(content->'decision_making','[]'::jsonb)) > 0) AS with_decision,
       round(avg((change_log->'validator'->>'score')::numeric), 2) AS mean_score
FROM canonical_jds
WHERE status='DRAFT' AND coalesce(content->>'employee_group','') <> 'cupe'
GROUP BY 1;
```

| | drafts | with `decision_making` | mean score |
|---|---:|---:|---:|
| **before** the guard | 1,156 | 1,084 (93.8%) | **84.61** |
| **after** the guard | 685 | 0 (0.0%) | **66.42** |

**An 18.19-point mean drop**, and the grade distribution moves with it:

| | A | B | C | D | F |
|---|---:|---:|---:|---:|---:|
| before | 14 | **1,064** | 64 | 7 | 7 |
| after | 0 | 0 | **608** | 76 | 1 |

Every one of the 1,064 grade-B JDFN drafts is a pre-guard draft. And the three
completeness rules went from occasional to universal:

| rule | before | after |
|---|---:|---:|
| `SFU-COMP-DECISION` | 72 / 1,156 (6.2%) | **685 / 685 (100%)** |
| `SFU-COMP-PROBLEM` | 72 / 1,156 (6.2%) | **685 / 685 (100%)** |
| `SFU-COMP-RELATIONSHIPS` | 68 / 1,156 (5.9%) | **685 / 685 (100%)** |

That is the "a finding present on every draft is a constant, not a signal" pathology the
rulebook names elsewhere — now on the JDFN cohort, arrived at by accident.

**⚠ So: every JDFN figure quoted before 2026-08-19 describes the pre-guard population.**
"1,804 drafts, mean 52.73, 179 approvable" is from the deterministic pass and is a third
population again. Do not compare across these three.

## The fix is NOT to loosen the guard

The obvious reading of the table is that the guard cost the JDFN cohort 18 points and
should be scoped to CUPE. **The data says the opposite, and it matters.**

The rewrite prompt is fed `member_jds=_flatten_jd(merged.draft)` — the grounded merge
draft and nothing else. That draft's `decision_making` is *always empty*. So a model
writing a Decision Making section had **no source for a word of it**: pre-guard, 1,084
JDFN drafts carried a section the pipeline invented from nothing. The 84.61 was not a
better score, it was a fabricated one, and the 18.19 points are fabrication being
withdrawn.

Re-permitting it on JDFN would restore an 18-point lift made of invented content, on the
same surface where HR-208 was just closed for the same reason.

## What is actually broken is one layer up

The source documents have this content. Over the 5,416 JDFN (`apsa`/`apex`/`poly`)
documents parsed at v4:

```sql
SELECT count(*) FILTER (WHERE jsonb_array_length(
         coalesce(parsed->'decision_making','[]'::jsonb)) > 0) AS has_decision,
       count(*) FILTER (WHERE jsonb_array_length(
         coalesce(parsed->'problem_solving','[]'::jsonb)) > 0) AS has_problem,
       count(*) FILTER (WHERE parsed->'relationships' IS NOT NULL
         AND parsed->'relationships' <> 'null'::jsonb) AS has_rel,
       count(*)
FROM parsed_jds WHERE parser_version='jd_segmenter_v4'
  AND parsed->>'employee_group' IN ('apsa','apex','poly');
```

| section | documents carrying it |
|---|---:|
| `decision_making` | **5,254 / 5,416 (97.0%)** |
| `problem_solving` | 2,434 / 5,416 (44.9%) |
| `relationships` | **5,275 / 5,416 (97.4%)** |

The 4.1 merge discards all of it as out of scope, and says so honestly — that is what
the `sections_not_merged` flag and the `section_not_merged` change-log reason are for.
But the consequence, now visible, is that **no JDFN draft the pipeline produces can ever
be complete**, because the content that would complete it is dropped before the rewrite
ever sees it.

### So the fix is: merge those three sections in 4.1

It puts grounded content where the guard expects it, and everything downstream follows
without another special case:

- the rewrite gets real text to reword instead of a blank it is forbidden to fill;
- `_SECTIONS_NEVER_INVENTED`'s EMPTY-TO-EMPTY rule becomes **reachable in production**
  for the first time (today `test_a_section_the_grounded_draft_has_is_left_to_the_rewrite`
  hand-builds a `MergedRole` that `merge_cluster` cannot produce, which is exactly why a
  green suite kept certifying a protection that never fired);
- the three completeness rules go back to being signals;
- and the ~18 points come back **honestly**, on content the source JDs actually state.

It needs a merge policy per section, which is an HR-207-shaped question (`drop` /
`longest` / union) and therefore a register entry decided in the same PR — not a default
chosen quietly. `problem_solving` at 44.9% is the interesting one: a cluster where half
the members have the section and half do not is a genuine question about what the
harmonized role should say, not a mechanical merge.

**Not implemented here.** It changes what a producer re-run produces for the entire
JDFN cohort, and it is a policy call, so it is written down rather than shipped.

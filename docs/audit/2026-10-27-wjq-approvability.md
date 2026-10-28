# Why 0 of 636 CUPE (WJQ) drafts are approvable after the v9 rewrite

**Dated record, 2026-10-27.** Measured on the v9 Bank (`jd-bank-v9`, `jd_segmenter_v9`,
rulebook `jd_rules_sfu_v4+e59b1b5d62e3`) at branch `feat/v9-targeted-rerun` (from
`bank/v9` `e584c53`). **Read-only**: no Bank row was written, no gate was changed.
Two `open` register entries were added (HR-296, HR-297) to record questions this study
found that nobody had asked HR; they move no value and do not change `rules_version`.

## The question

`docs/canonical/bank-audit.json` on this branch shows **0 of 636** WJQ drafts approvable,
blocked by SFU-APPROVE-KSA-ORDER 612, SFU-APPROVE-QUAL-EQUIVALENT 610,
SFU-APPROVE-NO-PLACEHOLDERS 129, SFU-APPROVE-SUMMARY-CONDITIONS 49. For each gate: how
many drafts failed it **before** the rewrite and **after**, and is the gate right, did the
rewrite make it worse, or does the gate not fit the CUPE form?

## Method

`core/scripts/wjq_approvability_study.py` (committed with this note). For every
WJQ-authored DRAFT in the Bank (`clusters.constraint_metadata->>'authored_template' =
'wjq'`), using the producer's own code and no DB writes:

* **after** — the stored draft (`canonical_jds.content`), re-scored with
  `evaluate_jd_rules` → `score_issues` → `evaluate_gates`, and compared with the stored
  `change_log.validator.gate_decision`;
* **before** — the deterministic `--no-llm` draft, rebuilt in process with
  `merge_cluster` over the cluster's own members (`clusters.members`, sorted by id as the
  producer sorts them) at the current parser version, then scored the same way;
* **at source** — every member's own parse, scored the same way;
* **archive probe** (`--archive-probe`) — every member's ORIGINAL FILE, extracted with
  the ingest extractor from the read-only archive, checked for "equivalent combination".

### The probe reproduces numbers the system already knows (CURRENT.md)

| check | expected | probe |
|---|---|---|
| WJQ drafts | 636 (bank-audit) | 636 |
| after-rewrite fails, per gate | 612 / 610 / 129 / 49 (bank-audit) | 612 / 610 / 129 / 49 |
| re-scored vs stored gate decision | identical | **0 mismatches** of 636 |
| `rules_version` on every row | the live rulebook | all 636 = `jd_rules_sfu_v4+e59b1b5d62e3` |
| approvable before the rewrite | 2 (the brief) | **2** |
| member parses lacking "equivalent combination" | 3,328 member rows fail the gate at source | archive probe: parse lacks the phrase in **3,328** |

## Findings

| Gate | at source (member parses, n=3,563) | **before** rewrite (n=636) | **after** rewrite (n=636) | v8 live artefact (n=625, also rewritten) | class |
|---|---:|---:|---:|---:|---|
| SFU-APPROVE-KSA-ORDER | 475 (13.3%) | **0 (0.0%)** | **612 (96.2%)** — all 612 P→F | 563 (90.1%) | **(b)** rewrite; and (c) — see HR-297 |
| SFU-APPROVE-QUAL-EQUIVALENT | 3,328 (93.4%) | 610 (95.9%) | 610 (95.9%) — identical set | 596 (95.4%) | **(c)** form misfit |
| SFU-APPROVE-NO-PLACEHOLDERS | 537 (15.1%) | 141 (22.2%) | 129 (20.3%) — 12 F→P, 0 P→F | 111 (17.8%) | **(c)** mostly; some (a) |
| SFU-APPROVE-SUMMARY-CONDITIONS | 124 (3.5%) | 24 (3.8%) | 49 (7.7%) — 35 P→F, 10 F→P | 42 (6.7%) | **(b)** mostly; gate false positives |
| SFU-APPROVE-MANDATORY-SECTIONS / SEVERITY-FLOOR | 143 (4.0%) | 29 | 15 | 14 | (a) — the rewrite helps |
| SFU-APPROVE-SUMMARY-LENGTH | — | 68 | 0 | — | the rewrite FIXES this |
| **approvable** | — | **2** | **0** | 3 | |

`v8` = `git show origin/main:docs/canonical/bank-audit.json` (the live Bank's committed
artefact; the live DB was not queried). v8 is itself a rewritten Bank on an older parser,
so it is a cross-check of the *after* column, not a *before*.

### What would each fix unblock? (after-rewrite blocking sets, exact)

| blocking set | drafts |
|---|---:|
| KSA-ORDER + QUAL-EQUIVALENT | **447** |
| KSA-ORDER + NO-PLACEHOLDERS + QUAL-EQUIVALENT | 95 |
| KSA-ORDER + QUAL-EQUIVALENT + SUMMARY-CONDITIONS | 34 |
| KSA-ORDER + NO-PLACEHOLDERS + QUAL-EQUIVALENT + SUMMARY-CONDITIONS | 11 |
| QUAL-EQUIVALENT only | 11 |
| KSA-ORDER + NO-PLACEHOLDERS | 9 |
| KSA-ORDER only | 7 |
| 16 other sets (floors, mandatory sections, …) | 22 |

So: fixing KSA-ORDER alone unblocks **7**; resolving QUAL-EQUIVALENT alone unblocks **11**;
both together **465 (73%)**. The two gates are jointly the whole story; neither alone is.

## Per gate, by eye (10 failing drafts each, fixed seed `20261027`)

### SFU-APPROVE-KSA-ORDER — (b) the rewrite broke it; 10 of 10

Sampled clusters `391c5ae6 12f0ce26 33011ed5 49fb6961 48175dd8 ac7c6ba3 25b7f1b8 5c6db199
0a120f31 …`. In every one the **merge draft** reads `education, experience, skill × n,
ability × m` (the parser's order, which never inverts) and the **rewritten** draft reads
e.g. `skill, ability, ability, ability, skill, skill, ability, …, knowledge, knowledge,
skill, knowledge, …, education, experience`. Two things happen:

1. **The model relabels and re-orders lines.** "Ability to use word-processing …" is
   `skill` in one place and `ability` two lines later; `knowledge` lines appear mid-list
   (568 of 612 failing drafts carry a `knowledge` line; **0** merge drafts do).
2. **The reassembly appends, it does not order.** `rewrite/harmonize.py` keeps the
   model's list, appends restored lines (`kept = [*kept, *back]`), then puts the merge's
   bars last (`kept.extend(bars)`): education/experience end the list in 590 of 612.
   Nothing re-applies K → S → A afterwards.

At source the gate fires on 13.3% of member parses — the merge already orders those.
The content is not deficient; **the rewrite produces the inversion.** Separately, the WJQ's
section 13 is not written in K/S/A at all, so the labels being ordered are inferred, not
the author's — which is why this is also a form-fit question (HR-297).

### SFU-APPROVE-QUAL-EQUIVALENT — (c) the gate cannot be satisfied by a WJQ; 10 of 10

Sampled `d31a994a b4ebde8f b404b1a4 ede0133e 0f17b243 1c3a4fa7 b8d6e6f5 5eee30e7
d4fc9705 5047b809`. None contains "equivalent combination" in the draft, the merge or the
first source parse; the only "equivalen…" hits are the WJQ's own checkbox furniture
("one semester/equivalent") or "program equivalent". The rewrite changes nothing (610 →
610, the same drafts).

The **source files do carry it — 3,556 of 3,563 (99.8%)** — because the WJQ prints a
"Check one:" box with **both** options: *"An equivalent combination of formal education,
certificate/program of study and experience is acceptable."* and *"… is not acceptable
because: (please explain)"*. The parser drops both lines as form instructions
(`wjq.instruction_markers: "an equivalent combination of"`, exempt under HR-144), so the
phrase survives in 235 parses (where an author typed it in a qualification line). Of 10
raw snippets read, 4 show a visible tick on "acceptable" (`☒`, `x`, `X_`); 6 show none in
extracted text (a form-field tick does not extract).

Keeping the lines would not fix it: both options contain the phrase, so the gate would
pass every WJQ — including one ticked "not acceptable". The information is **which box is
ticked**, which the Builder records as `wjq_form.equivalency_acceptable` (J2, HR-252) and
which neither the parser nor the merge populates.

⚠ **This contradicts a number HR has already read, and both are right.** The committed
archive baseline (`docs/baseline/summary.json`, parser v6, 2026-08-29) has this gate
blocking **9 of 4,300** WJQ documents, and the CUPE Phase B measurement behind HR-201
reports WJQ **59.0% approvable**. That is not a different form or a parser regression: the
archive baseline scores each file against its **raw extracted text**
(`baseline/runner.py`: `evaluate_jd_rules(parsed.jd, text)`), which still holds both
check-one options, so the gate passes *vacuously* — exactly the "keeping the lines" case
above. The Bank scores a draft against **its own parse** (`flatten_jd`), from which both
lines are dropped. So the archive's 0.2% and the Bank's 95.9% are the same gate on the
same form reading two different texts; neither says the equivalency requirement is met.
**Read the archive baseline's CUPE approvability (and HR-201's 59.0%) as overstated by
this gate** until the tick is read (recommendation 3). Reviewer note, 2026-10-27.

### SFU-APPROVE-NO-PLACEHOLDERS — (c) mostly the WJQ's tick slots; some (a)

Sampled `82538e50 b99c83a0 532dad0d 61b4071b f6dc493e 9bb39bec c362260f 3d79db9b 843a51f3
b2fad6ff`: **8 of 10** are the WJQ's unticked checkbox slots — `(a) _____ Work is provided
with specific instructions…`, `___ Assigns work to other staff` — inside the
level-of-independence / training / direction blocks carried verbatim in
`additional_context`; **2 of 10** are the form's own fill-in underline
(`(specify):______`, `experience________`). **0 of 10** is template instructional text
left in the JD's own prose. Over all 129: 79 checkbox slots, 37 other blanks, 13 carry
real leftover instruction text ("identify the certificate or program of ____") — those
13 are (a). The marker that fires is `"____"` (`markers.placeholder`, HR-047). The rewrite
does not make it worse (12 drafts fixed, none broken). The gate is non-overridable
(HR-005), so these cannot be waived.

### SFU-APPROVE-SUMMARY-CONDITIONS — (b) mostly; the rest are marker false positives

Sampled `3af59608 0e7ca2a6 00883203 115ebb00 de1e5262 1bcc5b94 2804ca1f 374f1199 b71bc1bb
b404b1a4`: **7 of 10** are the rewrite moving the WJQ's working conditions into the
Position Summary ("…flexible hours, including evenings and weekends", "rotating day,
evening and weekend shifts", "on-call or shift schedules") — the merge summaries do not
say this. **3 of 10** are the marker matching a noun: "Parking Services Office", "animal
housing", "equipment relocation". Over all 49: 35 newly failing after the rewrite (~30
genuine conditions inserted by it, 5 noun matches); of the 14 failing both before and
after, ~9 are noun matches ("Residence and Housing department", "student housing",
"Parking & Sustainable Mobility Services"). The noun matches are not CUPE-specific — they
are exactly HR-046's open question.

## Governing register entries

| Gate | entry | what it governs | status |
|---|---|---|---|
| QUAL-EQUIVALENT | HR-042 | the phrase `equivalent combination` | **ratified as shipped** 2026-08-29 (attribution-light; measured on JDFN only) |
| | **HR-296 (new)** | `rule_catalog.SFU-QUAL-EQUIVALENT.applies_to` = `[jdfn, wjq]` — does the gate apply to the WJQ form at all? | **open** |
| | HR-144 | WJQ section mapping; `wjq.instruction_markers` exempt under it (drops the check-one lines) | open |
| | HR-252 | the structured equivalency choice + rationale (Builder only) | open |
| KSA-ORDER | HR-052 | the K → S → A ranks | **ratified as shipped** 2026-08-29 (attribution-light) |
| | **HR-297 (new)** | `rule_catalog.SFU-GATE-KSA-ORDER.applies_to` = `[jdfn, wjq]` — does the order bind CUPE? | **open** |
| NO-PLACEHOLDERS | HR-047 | `markers.placeholder` (incl. `"____"`) | open |
| | HR-007 / HR-005 | the gate's rule set / its non-overridability | open / open |
| SUMMARY-CONDITIONS | HR-046 | `markers.working_conditions` (incl. `housing`, `parking`, `relocation`) | open |
| all | HR-004 | the blocking set | open |

⚠ **Ratifying HR-042 and HR-052 did not settle whether they apply to CUPE.** HR-042's
recorded measurement (Phase 2.5, `087b3af`, 2026-07-12) predates the WJQ parser
(`8640daf`, 2026-07-15) and CUPE Phase B (`46ab875`, 2026-08-14); HR-052's entry carries
no measurement at all; and which forms a rule judges (`applies_to`) was an
engineering setting from CUPE Phase B that no entry recorded — the same shape as HR-201
(boilerplate on the WJQ), which *was* registered. HR-296/297 record that, `open`, with no
value moved.

## Recommendations (not implemented)

**Engineering — fix regardless of any HR ruling:**

1. **The rewrite must keep the qualification order.** After reassembly in
   `rewrite/harmonize.py`, re-order `qualifications` deterministically — the bars
   (education, experience) where the merge had them, then K → S → A by `ksa_rank` — and
   stop the model re-labelling a kind the merge assigned. The merge's order passes on all
   636, so the target is KSA blocks 612 → 0; from the blocking-set table, approvable 0 → 7
   if nothing else moves. Needs a failing test first and a
   targeted re-run of the 612 clusters (`--cluster-ids-file`, built in this same branch).
2. **Do not let the rewrite move working conditions into the Position Summary.** ~30 of
   the 35 new SUMMARY-CONDITIONS blocks are the model importing the WJQ's
   working-conditions block. A prompt or post-check fix; same re-run path.
3. **Read the WJQ equivalency tick into the structured field** the Builder already has
   (`wjq_form.equivalency_acceptable`), from the archive's check-one block, rather than
   dropping both option lines. This is what lets HR-296 be decided on real data either way.
4. **Do not feed the WJQ's unticked checkbox slots to the placeholder scan** — parse the
   tick (as the Builder does, HR-238) or keep only the ticked option in
   `additional_context`. A "____" tick slot is form furniture, not an unfinished JD; any
   change to the marker's scope is itself a rulebook change and must be registered.

**HR — must rule:**

5. **HR-296** — is the "equivalent combination" bar a CUPE requirement, and if so is the
   WJQ's own tick ("acceptable" / "not acceptable because …") the way a CUPE JD meets it?
   Today 95.9% of CUPE drafts fail it because of the form, not the job.
6. **HR-297** — does K → S → A bind a CUPE job description, whose form is not written in
   K/S/A? (Recommendation 1 should land first so HR is not reading a rewrite defect.)
7. **HR-046** — should a summary naming a *department* ("Residence and Housing",
   "Parking Services") be blocked? ~14 CUPE blocks are this; it affects JDFN too.
8. **HR-047 / HR-005** — note for HR: the un-waivable placeholder gate fires on CUPE tick
   slots; once (4) lands, the residual 13 drafts are genuine leftover instructions.

Expected order of effect: (1) alone → 7 approvable; (1) + an HR-296 ruling that the tick
satisfies the requirement (with (3)) → up to 465 (73%), before (2)/(4)/(7).

## Reproduce

Read-only throughout: the engine sets `default_transaction_read_only=on` and every
statement runs inside `SET TRANSACTION READ ONLY`. Run from a checkout of this branch,
against the v9 Bank's network only (never the live `jd-bank`):

```bash
# 1. counts per gate + blocking sets + 10 sampled failing drafts per gate
MSYS_NO_PATHCONV=1 docker run --rm --network jd-bank-v9_default \
  -v "$PWD/core:/app" -v "$PWD/out:/out" -w /app jd-bank-gates:latest \
  python -m scripts.wjq_approvability_study \
  --database-url postgresql+asyncpg://app:app@postgres:5432/harness   # writes out/wjq-approvability.json

# 2. the equivalency wording in the ORIGINAL files (archive mounted read-only)
MSYS_NO_PATHCONV=1 docker run --rm --network jd-bank-v9_default \
  -v "$PWD/core:/app" -v "C:/repos/hris/fixtures/SFU_JDs:/archive:ro" -v "$PWD/out:/out" \
  -w /app jd-bank-gates:latest python -m scripts.wjq_approvability_study \
  --database-url postgresql+asyncpg://app:app@postgres:5432/harness --archive-probe
```

```sql
-- the stored verdicts the probe must reproduce (psql, read-only)
SET default_transaction_read_only = on;
SELECT g->>'gate_id' AS gate, count(*)
FROM canonical_jds c JOIN clusters k ON k.id = c.cluster_id,
     jsonb_array_elements(c.change_log->'validator'->'gate_decision'->'blocking') g
WHERE k.constraint_metadata->>'authored_template' = 'wjq' AND c.status = 'DRAFT'
GROUP BY 1 ORDER BY 2 DESC;
```

Measured outputs (2026-10-27): archive probe `raw=Y parse=Y 234 · raw=Y parse=N 3,322 ·
raw=N parse=N 6 · raw=N parse=Y 1` over 3,563 files read.

**Not measured here:** the JDFN cohort's KSA-ORDER (359 of 1,810 after the rewrite) may
carry the same reassembly defect; this study did not reconstruct JDFN merge drafts, so it
makes no claim about them.

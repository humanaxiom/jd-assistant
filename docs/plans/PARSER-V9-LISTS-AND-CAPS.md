# Plan — parser v9: Word lists, the 400-character cut, the 12-duty cap

**Status: code on branch `feat/parser-v9-lists-and-caps` (not pushed, no PR), measured
on a throwaway COPY of the live Bank on 2026-10-20.** Owner ruling 2026-10-19: *"Plan +
measure first"* — **nothing in this document touched the live Bank.** The only live
operation was a read-only `pg_dump -Fc`.

> **Bottom line.** The fixes work and nothing regresses at the parse level (0 documents
> lose a duty, 0 parse failures added, 0 titles damaged). But **v9 as built changes
> 13,972 of 14,522 parses, owes ~32k embed calls, and touches 2,424 of 2,503 drafts** — it
> is a full re-baseline, ~45 hours of GPU. And it exposes two facts that need an owner
> decision **before** that run (§6): reading list items surfaces the template's
> *"ACTION VERB … by:"* shape (5,365 documents whose major-duty headline the parser has
> always **dropped**), and splitting qualifications trips the blocking KSA-order gate on
> thousands of archive documents. **Do not run the live re-baseline until Q1 and Q2 are
> answered.**

---

## 1. The three defects (as found 2026-10-19, re-measured here)

| # | defect | where | v8 measured |
|---|---|---|---|
| 1 | **Word list items invisible.** A Word list carries its bullet as formatting (`<w:numPr>`, directly or via style). python-docx returns bare words; `_logical_lines` starts an item only on a bullet glyph, so every list item was appended to the one before, and the run-on was then cut at 400. | `jd_bank/ingest/extract.py` → `jd_core/parser/segmenter.py::_logical_lines` | 4,069 one-duty parses (DOCX 3,417) |
| 2 | **Duty statement cut at 400 chars** — `_MAX_DUTY_STMT = 400` and `SFUDuty.statement max_length=400`; unregistered. | `segmenter.py`, `wjq.py`, `models/parsed_jd.py` | 25,095 of 96,784 statements at exactly 400 (26%) |
| 3 | **12-duty cap on both forms** — `_MAX_DUTIES = 12`, majors first, so every CUPE minor function past the 12th was dropped (HR's Dec-2024 sample has 14; the Builder writes up to 24). | `segmenter.py`, `wjq.py`, `SFUJobDescription.duties max_length=12`, `composer/wjq_assemble.py` | the "77.4% of CUPE JDs carry exactly 12" in HR-202 *was this cap* |

## 2. What the branch changes

| file | change |
|---|---|
| `core/src/jd_bank/ingest/extract.py` | A Word list paragraph (direct `numPr` with `numId≠0`, or a numbered style through `basedOn`; `numId=0` switches off) is emitted with a leading `• ` (`LIST_ITEM_MARKER`) — the glyph both segmenters already read. **Never** on a section heading (JDFN or WJQ vocabulary) or an identification label (outline-numbered headings are list paragraphs too), never doubled on a typed bullet. **A WJQ (CUPE) questionnaire keeps the unmarked v8 text** — see §4.3. |
| `core/src/jd_core/parser/segmenter.py` | `PARSER_VERSION = "jd_segmenter_v9"`. Duty caps read from `segmentation.yaml`. Fallback title strips the glyph. A bullet under an *Internal/External Connections* label stays in that list instead of falling into `supervisory`. |
| `core/src/jd_core/parser/wjq.py` | Duty caps read from `segmentation.yaml`; `is_wjq_heading()` exposed for the extractor. |
| `core/src/jd_core/models/parsed_jd.py` | Contract ceilings widened: `SFUDuty.statement` 400 → **4,000**, `SFUJobDescription.duties` 12 → **150**. Operative caps are rulebook data below them. |
| `core/src/jd_core/rules/segmentation.yaml` + `loader.py` | `duty_statement_max_chars: 1200` (HR-261), `duty_max_count: 120` (HR-262), `wjq_duty_max_count: 120` (HR-263). The loader **refuses** a value above the model ceiling (else a long duty becomes a parse failure, not a trim). |
| `core/src/jd_core/rules/decision_register.yaml` | HR-261…263 registered `open` with the measured numbers; HR-202's impact text corrected (it said raising the WJQ `duties_max` above 12 "has no effect" — no longer true). `HR-DECISION-REGISTER.md` regenerated. |
| `core/src/jd_bank/composer/wjq_assemble.py` | Truncates at `segmentation.wjq_duty_max_count` instead of importing the parser's deleted `_MAX_DUTIES` (keeps "authored == parsed"). ⚠ The J2 branch rewrites this function; trivial conflict — take J2's version. |
| `core/scripts/measure_parse_delta.py` | **New, read-only.** The v_old vs v_new measurement used below, using the code's own functions. Kept for the live verification step. |
| tests | `tests/unit/test_parser_v9_lists_and_caps.py` (17 tests, written first, each guard broken once and seen red); updated `test_parser.py`, `test_composer_forms.py`, `integration/test_parse_and_store.py`, `export_roundtrip.py`; two new **live smoke** tests (§7). |

**`rules_version` does NOT move** (`segmentation.yaml` and the model are unhashed —
verified: the register header still reads `jd_rules_sfu_v4+e59b1b5d62e3`).
`Segmentation.stamp` moves, and `PARSER_VERSION` moves, which is the stronger obligation
(re-parse shipped with the bump). Consequence for the producer: **no stamp distinguishes
a pre-v9 draft from a post-v9 one** — `--refreshed-since` is the only resume tool (as for
the JDFN re-baseline).

## 3. How it was measured (the copy)

```bash
# 1. read-only dump of the live Bank (throwaway container on the jd-bank network)
docker run --rm --name p9measure-dump --network jd-bank_default -e PGPASSWORD=app \
  -v <scratch>:/out postgres:16-alpine pg_dump -h postgres -U app -d harness -Fc -f /out/live.dump
# 2. NEW EMPTY postgres on an ISOLATED network + non-default port; full -Fc restore (never --data-only)
docker network create p9measure-net
docker run -d --name p9measure-pg --network p9measure-net -p 127.0.0.1:25999:5432 \
  -e POSTGRES_USER=app -e POSTGRES_PASSWORD=app -e POSTGRES_DB=harness postgres:16-alpine
docker exec p9measure-pg pg_restore -U app -d harness --exit-on-error /tmp/live.dump
#    verified against live: canonical_jds 2504, audit_log 18688, clusters 2503,
#    source_documents 14565, dedup_edges 148914, parsed_jds 14522 per version v1..v8
# 3. v9 re-parse INTO THE COPY (worktree code, archive read-only, network that cannot
#    reach the live Postgres by construction)
docker run --name p9measure-ingest --network p9measure-net \
  -e DATABASE_URL=postgresql+asyncpg://app:app@p9measure-pg:5432/harness \
  -v <worktree>/core:/app -v C:/repos/hris/fixtures/SFU_JDs:/archive:ro -w /app \
  jd-bank-api:latest python -u -m src.jd_bank.ingest --archive-root /archive
#    -> "14565 files seen: 0 newly ingested, 14522 newly parsed, 0 already done, 43 failed."
#       (43 = the same unreadable files as v8: 14565 - 14522); 4m42s wall clock
# 4. the measurement (read-only)
python scripts/measure_parse_delta.py --old jd_segmenter_v8 --new jd_segmenter_v9 [--duties-only]
```

**Neo4j was not copied** — it is a derived index; no measurement here needs a vector.
Embed cost is computed exactly from the embed runner's own identity key
(`text_sha256` of `serialize_document`/`serialize_section`), plus one 40-text timing
sample against `aria-gb10-2` (§5.4). Every container was named `p9measure-*` and removed
(§9).

Caps were chosen **measure-first** (HR-200's lesson: a sample understates the tail): run 1
with the caps lifted to the model ceilings (4,000 chars / 60 → then 150 duties) to see the
true distribution; values picked; final run at the shipped values. Two defects found by
the measurement were fixed between runs (§4.3, §4.4) — the table below is the **final**
code.

## 4. Results — v8 vs v9 on the copy

### 4.1 Parse level (`q_parse.sql`, appendix A)

| group (v9 `employee_group`) | docs | duties v8 → v9 | one-duty v8 → v9 | stmts at exactly 400, v8 → v9 | duty text chars v8 → v9 |
|---|---:|---:|---:|---:|---:|
| apsa | 5,121 | 19,998 → 106,835 | 2,303 → **175** | 9,438 → 19 | 5.02M → 16.26M |
| apex | 420 | 1,385 → 9,170 | 226 → **2** | 697 → 0 | 0.37M → 1.37M |
| poly | 76 | 332 → 1,769 | 36 → 5 | 117 → 2 | 0.07M → 0.22M |
| cupe | 4,300 | 49,188 → 111,122 | 1 → 1 | 7,411 → 122 | 11.23M → 23.97M |
| excluded | 71 | 391 → 521 | 15 → 12 | 137 → 0 | 0.08M → 0.16M |
| none (no group) | 4,534 | 25,490 → 44,820 | 1,488 → 1,282 | 7,295 → 17 | 5.06M → 11.76M |
| **all** | **14,522** | **96,784 → 274,237** | **4,069 → 1,477** | **25,095 → 160** | **21.8M → 53.7M (+31.9M)** |

Duty-count distribution (documents):

| duties | 0 | 1 | 2 | 3–5 | 6–12 | 13–24 | 25+ |
|---|---:|---:|---:|---:|---:|---:|---:|
| v8 | 455 | 4,069 | 116 | 2,142 | 7,740 | 0 | 0 |
| v9 | 454 | 1,477 | 51 | 889 | 1,838 | 5,249 | 4,564 |

v9 duties per document: JDFN path p50 16 · p95 37 · p99 46 · max 93; CUPE p50 24 · p95 49
· p99 63 · max 92. Statement length: v8 p50 213 (p95 = p99 = max = 400, the cut); v9 p50
146 · p95 497 · p99 1,200.

**What changed, per field** (documents): duties 13,894 · decision_making 5,756 ·
qualifications 4,297 · problem_solving 2,372 · relationships 214 · position_summary 63 ·
additional_context 8 · title **0**. **Any field: 13,972 of 14,522.**

**Regressions looked for, and found zero:** documents with FEWER duties than v8: **0**.
Parse failures: **43 = v8's 43**. Validation-invalid rows: **0**. The 63 summary changes are
summaries already at their 4,000 cap (whole-document bleed) whose cut point moved by the
added glyphs; the 8 context changes are glyphs; the 214 relationships changes all ADD
contacts (bullets now land in internal/external, 1 shorter `supervisory`).

By source format: DOCX 9,778 of 9,925 changed (one-duty 3,417 → 825); DOC 4,187 of 4,563
changed — **all from the caps** (antiword output carries no `numPr`; one-duty 651 → 651).

### 4.2 Validator (each changed document scored v8 and v9, raw text = `flatten_jd`, as the producer scores a draft)

| | full v9 (as built) | duties-only variant (§6 Q2) |
|---|---:|---:|
| approvable, among changed docs | **680 → 215** | 680 → **680** |
| summed score change | −61,183 pts (≈ −4.4/doc) | −49,845 pts |
| `SFU-STRUCT-DUTIES-TOO-MANY` newly firing (advisory) | 7,808 | 7,808 |
| `SFU-STRUCT-DUTIES-TOO-FEW` cleared | 2,657 | — |
| `SFU-GATE-KSA-ORDER` newly firing (**blocking**) | 2,773 | 0 |
| `SFU-QUAL-SKILL-MODIFIER` / `-AUTH-ABILITIES-OBSERVABLE` newly firing | 3,815 / 3,195 | 0 / 0 |
| `SFU-STRUCT-ACTION-VERB` newly firing | 2,111 | 2,111 |

**The whole approvability drop is the qualifications split**, not the duties: one fused
400-char "qualification" could not be out of K/S/A order; 10 separate ones can. That may
be a TRUE finding (the gate is HR policy) or a classifier artefact (`_classify_qual` is a
keyword heuristic that defaults to `ability`) — **not established here** (Q2). Archive
approvability is not this phase's measure (owner ruling 2026-08-29: drafts), but
`docs/baseline` and the funnel both report it.

### 4.3 Measured, then fixed before the final run

* **CUPE `.docx` with mixed list/plain paragraphs** — the WJQ duty reader goes "bulleted"
  on one bullet and fuses plain paragraphs into the previous duty. A/B over the 2,154 WJQ
  `.docx` with list paragraphs: markers gave MORE duties on 318, FEWER on 183 (up to
  37 → 5), and fewer duty words overall (1,678,349 vs 1,757,800). **Net harm → WJQ
  documents keep the unmarked text** (v9 still lifts their caps). Result: 0 documents lose
  duties. (Q4.)
* **Fallback titles** gained `• ` on 102 documents (About-SFU text was already their wrong
  title); stripped → 0 title changes.
* **Relationships**: bulleted contacts under "Internal Connections" fell into
  `supervisory` (213 documents) → routed to their list.

### 4.4 Residual defects v9 does NOT fix (measured)

* **Run-on duty sections with no list formatting** — older questionnaires and antiword
  `.doc` where the duties are plain paragraphs. 1,477 one-duty documents remain; **1,462**
  of them are a single statement at the 1,200 cap. Overall **4,498 statements in 3,381
  documents** are still cut at 1,200. No cap fixes this; it needs a paragraph-boundary
  rule for docx duty sections (Q3).
* **The "by:" headline is dropped.** `_structure_duties` skips any item ending in `:` —
  in SFU's template that is the MAJOR duty ("Manages complex proposal processes by:")
  with its how/why under it. Over the archive: **5,365 JDFN documents, 18,583 such
  headline lines dropped** (v8 dropped them too, or fused them into the run-on). (Q1.)
* **Qualifications count cap 40** bites the same **718** CUPE documents in v8 and v9;
  qualification lines at exactly 400 fell 5,241 → 1,544 (splitting, not a cap change).
  Not changed here; candidates for the same treatment.

## 5. Downstream — what depends on 400 / 12, and what this costs

### 5.1 Inventory

| consumer | depends on | must change? |
|---|---|---|
| Validator `duties_max` (JDFN 5, HR-022; WJQ 12, HR-202) | duty COUNT | No code change. But 7,808 sources newly draw the advisory TOO-MANY — mostly the "by:" sub-bullet shape (Q1). HR-202 text corrected. |
| Validator KSA / qualification rules (blocking `SFU-GATE-KSA-ORDER`) | qualification item boundaries | No code change; **behaviour changes a lot** (§4.2, Q2). |
| Merge `harmonization.max_duties` 12 (HR-172), `duty_dedup_jaccard_min` 0.7 (HR-171) | member duty statements | No change. Drafts stay ≤12 duties; dedup now sees shorter, real items. Deterministic draft mean score on the 2,424 affected clusters: 64.40 → 62.47 (duties-only: 64.51 → 63.52). |
| LLM rewrite (`rewrite.yaml`: `max_tokens 2048`, loose JSON, validates into `SFUJobDescription`) | draft size; model ceilings | No change required. Merged draft size p50 4,199 → 5,998 chars, p95 12,914 → 12,916, max 17,816 → 17,114 — the tail (already over a 2,048-token output) is unchanged, the middle grows ~40%. Watch rewrite-failure counts on the pass. The widened ceilings mean a rewrite with a >400-char statement no longer fails validation. |
| Embeddings `max_chars` 10,000 (HR-126), fallbacks (HR-193) | serialized text length | No change. Documents truncated at max_chars 3,179 → 4,539; duty-section vectors truncated 0 → 339. |
| Tier-1 exact dedup | file bytes | Unaffected. |
| Tier-2 near-dup (`text_source: raw_clean`) | raw extracted text | **Unaffected by construction**: the tokenizer keeps `[a-z0-9]+`, so `•` vanishes (pinned by `test_list_marker_is_invisible_to_tier2_near_dup_shingles`). Caps don't touch raw text. |
| Tier-3 role equivalence | `JobSignals` (quals) + document vectors | **Changes.** Signals change on 4,297 docs (all via qualifications; 0 in the duties-only variant); document vectors change on 13,972. Edge/cluster movement **not measurable without re-embedding** (§8). |
| Clusters / `cluster_id` (uuid5 of sorted member refs) | Tier-3 edges | A membership change mints a NEW cluster id → new draft; the old cluster keeps its canonical and still counts as a role in the funnel (`_CURRENT` = latest canonical per cluster). **Check before the producer runs** (runbook step 6). |
| CUPE Builder assembler (`wjq_assemble.py`) | parser's duty cap | Changed to read HR-263 (J2 supersedes). |
| Composer answer models (`DutyAnswer.statement ≤400`, 12 duties / 12+12 functions) | authoring limits | Not changed — authoring limits, separate decision. |
| Export / render, CUPE export (J1) | draft duties | Drafts stay ≤12; long statements render fine (round-trip test now reads HR-261). |
| `make bank-audit` | `PARSER_VERSION` (imported) | Follows automatically. |

### 5.2 Drafts and published JDs (NN #1)

| latest canonical per cluster | clusters | any member parse changed | deterministic draft changes |
|---|---:|---:|---:|
| untouched DRAFT | 2,498 | **2,421** | 2,421 |
| reviewer-touched (PUBLISHED, or any review action) | 5 | **3** | 3 |

The producer **never** rewrites a reviewer-touched or published canonical
(`canonical/runner.py::reviewer_touched`, counted `skipped_reviewer_touched`), so NN #1
holds mechanically: the 3 keep their text. But their **sources now read differently**
from what they were approved on — a steward should be shown that (the JD-currency plan's
"source drift" axis). Nothing auto-unpublishes.

### 5.3 Cost of the live run

| step | work | estimate |
|---|---|---|
| backup | `pg_dump -Fc` (157 MB today) | ~1 min |
| `make ingest` (re-parse) | 14,522 parses, no GPU | **~5 min** (measured 4m42s) |
| `make embed` | **32,226 calls** = 13,972 document + 13,894 duties + 4,297 qualifications + 63 summary vectors (duties-only variant: ~27.8k) | **~20–60 min** on `aria-gb10-2` (measured: 40 real texts, avg 6.4k chars, 0.11 s/text one-by-one, 0.04 s/text batched) |
| `make near-dup` | invariant; run to prove 0 change | minutes |
| `make dedup-role`, `make cluster` | re-score Tier-3 on new signals+vectors | minutes (no GPU) |
| `make canonical-drafts` | ~2,424 clusters × 64.8 s (HANDOFF) | **~44 h GPU** |
| `make embed-roles` | ~2,500 role texts | minutes |

## 6. Open questions — owner / HR, BEFORE the live run

1. **Q1 (owner, engineering — recommend doing it first): group "ACTION VERB … by:" duties.**
   Read the `…by:` line as the duty and the items under it as its `how_why` (the model
   field exists, is never filled, and SFU's template asks for exactly this shape).
   Measured: duty counts >5 would fall from **6,133 to 1,331** JDFN documents and 18,583
   dropped headlines would be kept. Cost: `how_why` is read by one validator rule and
   ignored by merge/embeddings/rewrite today — those consumers must be extended first or
   the sub-bullets disappear from drafts. Without it, v9 charges ~7,800 documents
   DUTIES-TOO-MANY for following the template.
2. **Q2 (HR + owner): split qualifications too, or duties only?** Full v9 drops archive
   approvability on the changed documents 680 → 215 via the blocking KSA-order gate;
   duties-only keeps 680. Before choosing, someone should read ~30 newly-failing documents
   and say whether the order finding is true or a `_classify_qual` artefact.
3. **Q3 (owner): fix run-on plain-paragraph duty sections?** 1,462 documents remain one
   statement at the cap. A docx paragraph inside a DUTIES block is an item, not a wrapped
   line — fixable at extraction like the list fix, but it touches every docx duty block.
4. **Q4 (owner): CUPE `.docx` list paragraphs.** Shipped unmarked (§4.3). Doing better
   needs the WJQ reader to stop treating plain lines as continuations in docx input.
5. **Q5 (HR, HR-261…263):** 1,200 characters per statement and 120 duties/functions per
   document are fidelity bounds with headroom, filed `hr_informed`. HR-202 (`wjq.duties_max
   = 12`) now bites re-parsed CUPE sources — is a CUPE source with 24 functions to be
   marked down?
6. **Q6 (owner): the 3 reviewer-touched clusters** whose sources changed — notify, or
   leave to the currency/attestation work?

## 7. Smoke additions (on the branch; red until the live re-parse lands)

* `test_a_word_list_archive_file_parses_to_separate_duties` — the real Word-list file
  `20260702_00138566_JDFN_APSA_20260626.docx` must parse to >5 duties at the current
  parser version (v8: 1, v9: 19).
* `test_no_current_parse_is_cut_at_the_old_400_char_cap` — <1% of current-parse duty
  statements at exactly 400 (v8: 26%, v9: 0.06%) and none above the configured cap.

Both passed against the v9 copy, together with the 7 database-only smoke tests
(accounted-for, role side, union, findable, template, draft-template, title search):
**9 passed** on the copy. The vector-index and HTTP smoke tests were not run (no Neo4j
copy, no API) — they are covered by the live `make smoke` in the runbook.
Already covered: a check that the DOCUMENT vectors are at the current parser version
(`test_the_document_vector_index_is_at_the_current_parser_version`), so a re-parse
without `make embed` cannot pass smoke.

## 8. Not measured, and why

* **Tier-3 edges, cluster membership, new/orphaned cluster ids** — need v9 document
  vectors, i.e. ~14k embed calls against `aria-gb10-2`; out of bounds for this ruling.
  First thing to read in the live run (runbook step 6).
* **LLM draft quality / rewrite failures under v9** — needs the 44 h pass.
* **The archive baseline (`make baseline`) at v9** — feasible offline (~15 min) but not
  run; §4.2 is the same validator over the same parses.

## 9. Runbook — doing it live (after Q1/Q2 are decided)

🔴 Directive #0: **ship = merge**. The live stack bind-mounts `C:\repos\JD-Assistant\core`,
so the run happens with the branch **checked out in the main repo**, and the PR is merged
only after step 9 is green. `--resume` is the wrong flag for a re-baseline (HANDOFF).

```bash
# 0. Preconditions: Q1/Q2 decided and built; gates + register-check green on the branch;
#    aria-gb10-2 reachable and NOT held by another producer pass; smoke green on main.
make smoke

# 1. BACKUP — full custom-format dump + fingerprint (docs/runbooks/backup-and-restore.md §1)
docker exec jd-bank-postgres-1 pg_dump -U app -d harness -Fc -f /tmp/harness.dump
docker cp jd-bank-postgres-1:/tmp/harness.dump C:/Users/adam/jd-bank-backups/harness-pre-parser-v9-$(date +%Y%m%d).dump
#    + record the audit fingerprint query beside it

# 2. Deploy the code: check out the branch in C:\repos\JD-Assistant (api/worker reload).
#    From here until step 4 the app queries v9 rows that do not exist: an EMPTY-looking
#    Bank. Keep steps 2-4 back to back.

# 3. Re-parse (~5 min). Expect: "14565 files seen ... 14522 newly parsed ... 43 failed."
make ingest JD_ARCHIVE_PATH=C:/repos/hris/fixtures/SFU_JDs

# 4. Verify the parse against the Bank, not the counter:
docker compose run --rm -T api python scripts/measure_parse_delta.py \
    --old jd_segmenter_v8 --new jd_segmenter_v9 --json-out /tmp/delta.json
#    expect the §4 numbers (changed ~13,972; fewer_duties 0; invalid 0)

# 5. Re-embed documents (~20-60 min GPU; skip-first, re-run to resume).
make embed            # expect embed calls ≈ 32,226; re-run -> 0

# 6. Dedup + clustering. near-dup must show no change (invariant); THEN compare the
#    recomputed cluster ids with the clusters table BEFORE the producer runs — a moved
#    member mints a new cluster id and orphans the old role (§5.1).
make near-dup
make dedup-role
make cluster

# 7. Producer re-baseline (~44 h). Note the start time T0 (UTC).
make bank-audit AUDIT_ARGS="--json" > before.json     # exits 2 below 100%: by design
make canonical-drafts                                  # NOT --resume
#    interrupted? resume with:
make canonical-drafts CANONICAL_ARGS="--refreshed-since <T0>"
make bank-audit AUDIT_ARGS="--json" > after.json      # carry-through must not fall

# 8. Role vectors follow the new draft text.
make embed-roles

# 9. Smoke — must be GREEN (includes the two v9 smoke tests), then merge the PR.
make smoke
```

**Rollback.** `parsed_jds` keeps the v8 rows (keyed by version), so checking `main` back
out makes the app read v8 parses again immediately. Drafts rewritten under v9 and the
vectors do not roll back with the code: restore the step-1 dump into an EMPTY database
(`backup-and-restore.md` §3 — **never `pg_restore --data-only`, it wipes the Bank and
exits 0**), verify counts + audit fingerprint, then `make embed` and `make embed-roles`
under the v8 code (≈ the same 32k calls back).

## 10. Containers created for this measurement (all removed)

`p9measure-dump`, `p9measure-pg` (127.0.0.1:25999, network `p9measure-net`),
`p9measure-ingest`, `p9measure-measure`, `p9measure-measure2`, `p9measure-bygroup`,
`p9measure-embedrate`, `p9measure-smoke`; network `p9measure-net`. The dump file lived
in the session scratchpad only.

---

## Appendix A — the parse-level queries (run on the copy)

```sql
-- per group (group read off the v9 parse), v8 vs v9
WITH d AS (
  SELECT p.source_document_id sid, p.parser_version v,
         coalesce(p.parsed->>'employee_group','none') grp,
         jsonb_array_length(p.parsed->'duties') n,
         (SELECT count(*) FROM jsonb_array_elements(p.parsed->'duties') e
            WHERE length(e->>'statement') = 400) at400,
         (SELECT count(*) FROM jsonb_array_elements(p.parsed->'duties') e
            WHERE length(e->>'statement') > 400) over400,
         (SELECT coalesce(sum(length(e->>'statement')),0)
            FROM jsonb_array_elements(p.parsed->'duties') e) chars
  FROM parsed_jds p WHERE p.parser_version IN ('jd_segmenter_v8','jd_segmenter_v9')
), g AS (SELECT sid, grp FROM d WHERE v='jd_segmenter_v9')
SELECT g.grp, d.v, count(*) docs, sum(n) duties, sum((n=0)::int) zero_duty,
       sum((n=1)::int) one_duty, sum((n>12)::int) over_12, sum(at400) stmts_at_400,
       sum(over400) stmts_over_400, sum(chars) duty_chars
FROM d JOIN g USING (sid) GROUP BY ROLLUP (g.grp), d.v ORDER BY 1 NULLS LAST, 2;

-- which fields changed
SELECT count(*) FILTER (WHERE a.parsed <> b.parsed) any_change,
       count(*) FILTER (WHERE a.parsed->'duties' <> b.parsed->'duties') duties_changed,
       count(*) FILTER (WHERE jsonb_array_length(b.parsed->'duties')
                            < jsonb_array_length(a.parsed->'duties')) fewer_duties,
       count(*) FILTER (WHERE a.parsed->>'title' <> b.parsed->>'title') title_changed
       -- (+ the same for qualifications, decision_making, problem_solving,
       --    position_summary, additional_context, relationships)
FROM parsed_jds a JOIN parsed_jds b USING (source_document_id)
WHERE a.parser_version='jd_segmenter_v8' AND b.parser_version='jd_segmenter_v9';

-- true distribution with caps lifted (run 1/2): percentiles of statement length and count
SELECT (parsed->>'employee_group'='cupe') wjq,
       percentile_disc(ARRAY[0.5,0.9,0.99,0.999,1.0])
         WITHIN GROUP (ORDER BY jsonb_array_length(parsed->'duties'))
FROM parsed_jds WHERE parser_version='jd_segmenter_v9' GROUP BY 1;

-- residual run-ons at the cap
SELECT count(*), count(DISTINCT p.id) FROM parsed_jds p,
       jsonb_array_elements(p.parsed->'duties') e
WHERE parser_version='jd_segmenter_v9' AND length(e->>'statement') = 1200;
```

Validator, embed-identity, signals, cluster and merge numbers: `core/scripts/measure_parse_delta.py`
(default = full v9; `--duties-only` = §4.2's second column).

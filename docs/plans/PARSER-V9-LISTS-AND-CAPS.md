# Plan — parser v9: Word lists, the 400-character cut, the 12-duty cap, "… by:" duties

**Status: code on branch `feat/parser-v9-lists-and-caps` (not merged, no PR), measured on
a throwaway COPY of the live Bank on 2026-10-20.** Owner ruling 2026-10-19: *"Plan +
measure first"*, so **nothing in this document touched the live Bank.** The only live
operations were two read-only `pg_dump -Fc` runs.

**Deployment ruling (owner, 2026-10-20 later):** v9 runs as a **NEW, SEPARATE Bank**,
seeded fresh from the archive in its own compose project with its own images (infra PR
in progress). **The live (v8) Bank is never re-parsed**, so the earlier live re-parse
runbook is superseded. See §10. The branch now carries main (I1, J1, K2, I2), J4 (#214)
and J2 (#216), merged in from `origin/feat/j2-cupe-form-structure` (§12).

## 0. Owner rulings, 2026-10-20

| | ruling | where it lands |
|---|---|---|
| **Q1** | **Group under the headline.** An "ACTION VERB … by:" headline IS the duty; the list items under it are that duty's `how_why`. The headline is not dropped, and the sub-bullets are not duties of their own. Typed-bullet and Word-list documents both group. A list with no headline above it stays as separate duties. The caps stay rulebook data. Every consumer that read only `statement` must read `how_why` before this ships. | §2, §5 (consumer inventory) |
| **Q2** | **Split qualifications too.** The owner accepts the drop in approvable documents (680 → 215 among changed documents, from the blocking `SFU-GATE-KSA-ORDER`). The split stays and the gate is not weakened. | §4.2, §6 (recommendation) |
| Q3–Q6 | still open | §7 |

> **Bottom line.** v9-grouped reads SFU's template the way it is written. Among the
> APSA/APEX/POLY documents, 18,245 duties now carry 111,858 how/why points, and APSA's
> median duty count is 4 (v8: 3 because of run-ons; v9-flat: 20). Grouping loses no
> word that v9-flat kept (0 documents). Against v8, 2 documents (the same position, two
> versions) lose words, both to the HR-261 statement cap on an unbulleted run-on (Q3).
> No document loses words to list reading or grouping. It is still a full re-baseline:
> 14,008 of 14,522 parses change, 2,428 drafts regenerate (~45 h of GPU), and ~32.3k
> document embed calls plus ~2.5k role embed calls are owed.
> ✅ **The J4 precondition is now met on the branch.** J4 and J2 are merged in. J4's
> `JDFNDutyAnswer.how_why` limit no longer has a constant of 12: it reads HR-265 (60),
> so a duty with 36 points clones and reassembles whole. Before this, cloning would
> have raised for 1,107 duties in 992 documents. The Builder's 12-duty
> `ComposerAnswers.duties` constant now reads HR-262, so cloning a raw archive
> document with 20 duties no longer raises.

---

## 1. The defects

| # | defect | v8 measured |
|---|---|---|
| 1 | **Word list items were invisible.** A Word list carries its bullet as formatting (`<w:numPr>`, directly or through its style). python-docx returns the bare words, and `_logical_lines` appended every item to the one before it. | 4,069 one-duty parses (DOCX 3,417) |
| 2 | **Duty statements were cut at 400 characters.** `_MAX_DUTY_STMT` and `SFUDuty.statement max_length=400`, unregistered. | 25,095 of 96,784 statements at exactly 400 (26%) |
| 3 | **The 12-duty cap applied to both forms**, majors first, so every CUPE minor function past the 12th was dropped. | HR-202's "77.4% carry exactly 12" *was this cap* |
| 4 | **"… by:" headlines were dropped.** Any duty item ending in `:` was skipped. Found while measuring #1. | 18,583 headline lines in 5,365 JDFN documents (92.6% end "by:") |

## 2. What the branch changes

| file | change |
|---|---|
| `core/src/jd_bank/ingest/extract.py` | A Word list paragraph (direct `numPr` with `numId≠0`, or a numbered style through `basedOn`) is emitted with `• `. A list paragraph **indented beyond the most recent top-level item** is emitted with `◦ ` (`SUB_ITEM_MARKER`). Depth is resolved from the direct indent, then the numbering level, then the style chain, because both shapes occur: `ilvl` 1 nesting, and "List Bullet 2" being a separate numbering whose level 0 sits further in, which is how **J4's export writes how/why**. No marker on headings (JDFN + WJQ vocabularies), identification labels or typed bullets. **CUPE/WJQ questionnaires keep the unmarked v8 text** (measured net-harmful there, Q4). |
| `core/src/jd_core/parser/segmenter.py` | `PARSER_VERSION = "jd_segmenter_v9"`. `_structure_duties` groups (algorithm below). Caps come from YAML. The fallback title strips the glyph. A bulleted contact stays in its connections list. |
| `core/src/jd_core/parser/wjq.py` | CUPE duty caps from YAML. `is_wjq_heading()` is exposed for the extractor. The WJQ reader does **not** group. |
| `core/src/jd_core/models/parsed_jd.py` | Contract ceilings: `statement` 400 → 4,000; `duties` 12 → 150; `how_why` 12 → 100. Operative caps sit below them in YAML, and the loader enforces that. |
| `segmentation.yaml` + `loader.py` | HR-261 `duty_statement_max_chars` 1,200 · HR-262 `duty_max_count` 120 · HR-263 `wjq_duty_max_count` 120 · **HR-264 `duty_headline_pattern` `(?i)\bby\s*:\s*$` · HR-265 `duty_how_why_max_count` 60 · HR-266 `duty_how_why_max_chars` 1,200**. All are registered `open`. |
| consumers | Six consumers changed (§5): merge, rewrite prompt v3 + input + guard, embed text, Builder clone, harmonize measurement, CUPE assembler. |
| `core/scripts/measure_parse_delta.py` | Read-only v_old vs v_new measurement. It now also reports how/why coverage and words lost per document, and has a `--duties-only` variant. Reused in the live runbook. |

**The grouping algorithm** (`segmenter._structure_duties`). Each item is first split
exactly as before (a long legacy semicolon run is several duties). Then each part is
placed:
1. A part matching `duty_headline_pattern` ("… by:") is a **duty**; it opens a group. If
   unbulleted paragraphs fused a run-on onto it, only the last sentence is the headline.
   The run-on before it stays as a duty of its own, cut at sentence breaks if it is
   longer than the cap.
2. Any other part ending in `:` ("Duties include:", "Budget Management:") closes the
   group and is **kept** as a line of its own. v8 had fused such lines into run-ons, so
   dropping them lost words in 303 documents (measured).
3. A `◦` (nested) part is a how/why clause of the duty above it, headline or not. This is
   J4's shape.
4. In a flat list (typed bullets, or one Word level), the parts after a headline are its
   how/why until the next headline or intro. After nested clauses, a top-level part is the
   headline's sibling.
5. Anything else is a duty of its own.

`rules_version` does **not** move: segmentation.yaml, rewrite.yaml and the model are
unhashed, and the register header still reads `jd_rules_sfu_v4+e59b1b5d62e3`.
`PARSER_VERSION` moves, as does the rewrite `prompt_version` (`jd_harmonize_v3`). That
gives the producer a stamp that distinguishes pre-v9 drafts from post-v9 drafts.

## 3. How it was measured

This run used a fresh copy, not the one from the earlier report. Steps:
1. `pg_dump -Fc` the live Bank (read-only).
2. Restore it into a new, empty `postgres:16-alpine` on an isolated network (`p9measure-net`, port 25999). Counts matched live: canonical_jds 2504 · audit_log 18688 · clusters 2503 · source_documents 14565 · dedup_edges 148914 · v8 parses 14522.
3. Re-parse the archive into the copy twice:
   - **v9-flat** (the f9054db code, re-labelled `jd_segmenter_v9flat`);
   - **v9-grouped** (this branch).
4. Run `scripts/measure_parse_delta.py` three ways:
   - v8 → v9-flat;
   - v8 → v9-grouped, full and `--duties-only`;
   - v9-flat → v9-grouped, the content-loss check.

Each ingest reported `14565 files seen … 14522 newly parsed … 43 failed`, the same 43
unreadable files as v8, in about 5 minutes. Neo4j was not copied (it is a derived index).
Embed cost is the embed runner's own `text_sha256` key, computed exactly.

**Measured, then fixed during this round.** Each fix has a regression test.
- Deciding on a whole semicolon run instead of each part lost duty words in 148 documents.
- Dropping non-headline intros lost words that v8 had fused into run-ons: 303 documents, 7,536 words.
- A "by:" headline fused to an over-cap run-on lost its tail in 4–6 documents.

## 4. Results — v8 / v9-flat / v9-grouped

### 4.1 Parse level (all 14,522 parses)

| | v8 | v9-flat | **v9-grouped** |
|---|---:|---:|---:|
| duties (total) | 96,784 | 274,237 | **181,563** |
| duty text, chars | 21.8M | 53.7M | **39.9M** (+ how/why below) |
| documents with > 5 duties | 7,740 | 11,651 | **7,486** |
| documents with 13+ duties | 0 | 9,813 | **5,368** (3,897 of them CUPE) |
| one-duty documents | 4,069 | 1,477 | **1,553** |
| statements at exactly 400 | 25,095 | 160 | **143** |
| statements at the 1,200 cap | — | 4,498 | **4,504** (run-ons, Q3) |
| duties with how/why | 0 | 0 | **18,245** in **5,127** documents |
| how/why points | 0 | 0 | **111,858** (p50 5 · p99 19 · max 36 per duty; 0 at the count cap; 120 points at the 1,200-char cap) |
| **documents losing duty words vs the column before** | — | 4,979 vs v8 (dropped "by:" headlines) | **0 vs v9-flat · 2 vs v8** (HR-261 cap on an unbulleted run-on, one position) |
| documents whose parse changed vs v8 | — | 13,972 | **14,008** |
| parse failures | 43 | 43 | 43 |

Duties per document, by group (p50 / p99):

| group | v8 | v9-flat | **v9-grouped** |
|---|---|---|---|
| apsa (5,121) | 3 / 12 | 20 / 46 | **4 / 25** |
| apex (420) | 1 / 12 | 21 / 45 | **3 / 11** |
| poly (76) | 3 / 12 | 21 / 82 | **5 / 82** |
| cupe (4,300) | 12 / 12 | 24 / 63 | **24 / 63** (CUPE does not group) |
| excluded (71) | 5 / 12 | 5 / 48 | **5 / 46** |
| none (4,534) | 5 / 12 | 6 / 49 | **5 / 49** |

Documents with > 5 duties, by group (v8 → flat → grouped): APSA 1,421 → 4,704 → **1,050**;
APEX 89 → 398 → **28**; POLY 21 → 70 → **21**; CUPE 4,131 → 4,131 → **4,131**; none
2,051 → 2,318 → **2,228**.

### 4.2 Validator (each changed document scored v8 and v9; raw text = `flatten_jd`, as the producer scores a draft)

| among changed documents | v9-flat | **v9-grouped, quals split (shipped, Q2)** | v9-grouped, duties only |
|---|---:|---:|---:|
| approvable, v8 → v9 | 680 → 215 | **680 → 215** | 680 → 680 |
| `SFU-STRUCT-DUTIES-TOO-MANY` newly firing | 7,808 | **4,622** | 4,622 |
| `SFU-STRUCT-DUTIES-TOO-FEW` cleared | 2,657 | **2,336** | 2,336 |
| `SFU-GATE-KSA-ORDER` (blocking) newly firing | 2,773 | **2,773** | 0 |
| `SFU-STRUCT-ACTION-VERB` newly firing | 2,111 | **978** | 978 |
| summed score change | −61,183 | **−34,143** | −20,452 |

The approvable drop is **entirely** the qualification split; grouping duties moves no
approval either way. Per group (v8 → grouped): APSA 593 → 182, APEX 65 → 15, POLY 1 → 0,
none 4 → 1, CUPE 17 → 17. **Recorded as accepted by the owner (Q2).**

## 5. Downstream — the consumer inventory (Q1: "downstream must READ `how_why`")

| # | consumer | read only `statement` before? | now |
|---|---|---|---|
| 1 | **Merge** — duty dedup/coverage (HR-171 Jaccard), `max_duties` 12 (HR-172) | yes: Jaccard on the statement alone | **Changed.** It compares the whole duty (`merge.duty_text` = statement + how/why), so a headline+clauses duty and its one-sentence twin group (test). The representative is the one with the most how/why (unchanged), and the draft carries that representative's how/why. The 12-duty draft cap is unchanged; drafts stay ≤ 12. HR-173 (core skills) reads qualifications, not duties: unaffected. |
| 2 | **Rewrite prompt + output contract** | the input was `flatten_jd`, so a headline and its clauses arrived as indistinguishable lines | **Changed.** New template `jd_harmonize_v3` (HR-180), input `jd_text.outline_jd` (duty `- `, clauses indented `    - `), and rule 3 now says keep the shape and do not drop clauses. The output schema already had `how_why`. The guard compares whole duties (statement + how/why), and **restores** a matched duty's clauses if the model returns it without them, as it does for `frequency` (test). v1/v2 stay on disk for read-back. |
| 3 | **Quality audit** (4.2b) | no: it reads `flatten_jd`, which already includes how/why | No change. |
| 4 | **Validators / gates** | `SFU-STRUCT-DUTIES-TOO-MANY/-FEW` count duties; `SFU-STRUCT-ACTION-VERB` reads the statement's leading verb; text scans use `flatten_jd` (includes how/why) | No code change. With grouping, the count is of template duties and the verb is the headline's verb: TOO-MANY 7,808 → 4,622 and ACTION-VERB 2,111 → 978 vs flat. ⚠ **`SFU-STRUCT-HOW-WHY` stays unevaluable** (HR-121): only 18,245 of 181,563 duties carry how/why, because only the template shape has it. Reinstating the rule moves `rules_version` and is an HR call (Q7). |
| 5 | **Embed text** (`embed_text._duties_units`) | yes: by design it never read how/why | **Changed.** One unit per duty = verb + statement + how/why, byte-identical for a duty without clauses. `SERIALIZER_VERSION` → `embed_text_v2`. **The embed stamp does not move** (no `embeddings.yaml` knob changed). The serializer version is not in the skip key `(text_sha256, model, embed_stamp)`, so only texts that actually changed re-embed. ⚠ **2,369 of 2,503 current roles already carry how/why** (the LLM rewrite writes it), so `make embed-roles` re-embeds those even before any new draft. |
| 6 | **Render / export** | before J4, `jd_export.render._duty_line` printed the statement only | **J4 (merged in) prints how/why as "List Bullet 2" sub-bullets, and v9 reads them back AS how/why.** Tests: `test_the_j4_export_shape_reads_back_as_duty_plus_how_why`; J4's own `test_how_why_clauses_stay_with_their_duty` and `test_builder_fields_reach_the_exported_docx` are updated from "fused into the statement" to "reads back as how_why". The round-trip oracle (`tests/export_roundtrip.py`) now compares each re-read duty's statement plus its how/why. |
| 7 | **Clone into the Builder** (`jd_to_answers`, `load_clone_answers` for raw archive documents) | yes, and it would have **raised** three ways | **Changed.** (a) `DutyAnswer.statement` ≤ 4,000 (it was 400). (b) J4's `JDFNDutyAnswer.how_why`: the hard bound is the model ceiling (100), and the operative limit is **HR-265 read from the rulebook** (it was a constant 12; 1,107 duties in 992 documents carry more). A duty with 36 points clones and reassembles whole (test written red first, below). (c) `ComposerAnswers.duties`: the operative limit is **HR-262** (it was a constant 12; ~1,470 APSA/APEX/POLY documents carry more), so a 20-duty archive document clones (test written red first). |
| 8 | **Dedup Tier-2** (near-dup, raw text) | n/a | Invariant: the tokenizer keeps `[a-z0-9]+`, so neither `•` nor `◦` moves a shingle (test). |
| 9 | **Dedup Tier-3 signals / clustering** | signals read qualifications; vectors read the embed text | The qualification split changes signals on 4,297 documents (0 with duties only). Document vectors now include how/why. Edge/cluster movement needs the re-embed (§8). |
| 10 | **CUPE assembler / J2 form** (`wjq_assemble`, `wjq_form`) | truncated at the parser's 12 | **J2's version taken whole.** It keeps majors and minors apart under the visible HR-246 limits (12 + 12; over a limit it refuses, never cuts). HR-263 stays because the WJQ **parser** still reads it. v9 does not group CUPE and never fills `wjq_form`, so nothing changed there. J2's "14 functions re-read as 12" boundary is **gone**: HR's 14-function sample now round-trips whole (J2's `test_fourteen_functions_survive_the_round_trip` and the live smoke assertion are updated). The CupeForm load check reads the duties ceiling off the model (now 150). ⚠ **Finding:** a re-parsed CUPE *archive* document with more than 12 functions clones with all of them as `major_functions` (the parser cannot tell majors from minors), so the Builder then **refuses** it with HR-246's message rather than cutting it. That is consistent with J2's design, but authors will see it on any large CUPE source. |
| 11 | change log, review editor, CUPE export, bank-audit, families | change log keys on statement identity; the review editor and CUPE export already read how/why; bank-audit and families read the whole duties JSON | No change needed. |
| 12 | harmonize measurement (`harmonize/runner.py`) | statement only | **Changed** to `duty_text`, so it measures what the merge does. |

### Drafts, published JDs, cost

| latest canonical per cluster | clusters | any member parse changed | deterministic draft changes |
|---|---:|---:|---:|
| untouched DRAFT | 2,498 | 2,425 | 2,425 |
| reviewer-touched / PUBLISHED | 5 | 3 | 3 (the producer **skips** them: NN #1 holds; their sources now read differently, Q6) |

The deterministic draft mean score on the affected clusters goes 64.38 → **63.80**
(duties-only: 64.48 → 64.94). Merged draft size grows from p50 4,195 to **7,373**
characters, p99 21.6k, max 36.6k. 🔴 **The rewrite's `max_tokens 2048` will be exceeded
for the larger drafts.** Expect more rewrite failures, which keep the deterministic draft.
Watch `rewrite_failed` in `bank-audit`; raising `max_tokens` is HR-registered (Q8).

| step | work | estimate |
|---|---|---|
| `make ingest` | 14,522 parses | ~5 min |
| `make embed` | **32,298** calls = 14,008 document + 13,930 duties + 4,297 qualifications + 63 summary | ~20–60 min (measured 0.04–0.11 s/text on aria-gb10-2) |
| `make canonical-drafts` | 2,428 clusters × ~65 s | **~44 h** |
| `make embed-roles` | ≤ 2,503 roles (2,369 change from the serializer alone) | minutes |

## 6. Q2 recommendation (not done): HR should read KSA-ORDER on real text

The 2,773 new `SFU-GATE-KSA-ORDER` findings come from qualifications that used to be one
fused 400-character blob, which cannot be out of order. **Recommend** that HR read about
30 newly-failing documents and say, for each, whether the order finding is true or an
artefact of `_classify_qual` (a keyword heuristic that defaults to `ability`). If it is
mostly artefact, the fix is the classifier (a parser change), never the gate. The gate
stays as it is (owner ruling).

## 7. Open questions (Q3–Q6 stay open; Q7–Q8 are new)

- **Q3** — Unbulleted run-ons: 4,504 statements in about 3,400 documents still sit at the 1,200 cap, and 2 documents lose v8 words to that cap. This needs a paragraph-boundary rule for docx duty blocks.
- **Q4** — CUPE `.docx` list paragraphs are left unmarked.
- **Q5** — HR on HR-261…266, and on HR-202 now applying to re-parsed CUPE sources.
- **Q6** — The 3 reviewer-touched roles whose sources changed.
- **Q7 (HR)** — Reinstate `SFU-STRUCT-HOW-WHY`? It is measurable now, but only on template-shaped documents; it would fire on most duties.
- **Q8 (owner)** — Rewrite `max_tokens` against the larger drafts.

## 8. Not measured

- **Tier-3 edges and cluster membership.** These need the v9 document vectors (~14k embed calls); that is the first thing to read in the live run (runbook step 6).
- **LLM rewrite quality and failure rate under v3.** This needs the producer pass.
- **The vector and HTTP smoke tests.** There was no Neo4j or API on the copy. The 9 database-only smoke tests passed on the grouped copy, including the 2 v9 tests.

## 9. Smoke: which tests are v9-only

These two tests are **v9-only**. They read the current parse (`PARSER_VERSION =
jd_segmenter_v9`), so they are **meant to fail against the live v8 Bank**. Run `make
smoke` against the **v9 Bank** only.
- `test_a_word_list_archive_file_parses_to_the_template_shape`: `20260702_00138566_JDFN_APSA_20260626.docx` must parse to exactly **4 duties carrying 19 how/why points**. v8 gave 1 duty; v9-flat gave 19 duties.
- `test_no_current_parse_is_cut_at_the_old_400_char_cap`: fewer than 1% of statements at exactly 400 characters, and none above the cap.

Run with v9 code against the v8 Bank, **every** smoke test that reads `parsed_jds` at
`PARSER_VERSION` would find no rows, and so would fail or report empty. The same goes
for the document-vector test, which expects vectors stamped v9. The v9 code is
therefore not judged on the live stack at all. J2's live CUPE round-trip assertion
changed from `["duties: 14 exported, 12 re-read"]` to `[]`. It parses in-process, so it
passes on either Bank when run with v9 code.

## 10. Runbook — build a SEPARATE v9 Bank fresh from the archive

**Owner ruling: the live (v8) Bank is untouched.** v9 is a second Bank in its own compose
project, with its own images, volumes and host ports. The infra PR provides that. All
commands run in the **v9 checkout**, whose `.env` sets the compose project name and its
ports. Nothing here backs up, migrates or writes the live Bank, so there is nothing to
roll back on it.

```bash
# 0. In the v9 checkout. Confirm `.env` targets the v9 project, NOT jd-bank:
docker compose config | grep -m1 '^name:'      # must NOT print "name: jd-bank"
#    aria-gb10-2 must be free (no other producer pass); the v9 Bank is shared with nobody yet

# 1. Stack + schema (empty Bank)
make up
make migrate

# 2. Ingest + parse the archive (read-only mount; ~5 min)
make ingest JD_ARCHIVE_PATH=C:/repos/hris/fixtures/SFU_JDs
#    expect "14565 files seen: 14522 newly ingested, 14522 newly parsed, 0 already done,
#    43 failed." Then check the Bank, not the counter: 14,522 rows at jd_segmenter_v9.

# 3. Document + section vectors: a fresh index embeds everything (~52k calls at v8's
#    14.4k documents + 37.7k sections; ~40–90 min on aria-gb10-2). Re-run = resume.
make embed

# 4. Dedup + clustering. Tier-1 EXACT is synthesised at cluster time from sha256.
make near-dup
make dedup-role
make cluster

# 5. Drafts for EVERY cluster (~2,500 × ~65 s ≈ 44 h GPU). Record T0 (UTC).
make canonical-drafts
#    interrupted? make canonical-drafts CANONICAL_ARGS="--refreshed-since <T0>"
#    (NOT --resume; on a fresh Bank every draft is v9's own, prompt jd_harmonize_v3)
make bank-audit                                  # carry-through per form; watch rewrite_failed (Q8)

# 6. Role vectors
make embed-roles

# 7. Smoke: run against THIS Bank. Both v9-only tests (§9) must pass here.
make smoke
```

**What the v9 Bank will NOT have.** There are no published or reviewer-touched JDs (the
5 in the live Bank, 3 of whose sources changed). There are no review actions, users,
roles or audit history from the live Bank, and no `--refreshed-since` history. Every
canonical starts as a fresh DRAFT (NN #1: nothing auto-publishes). Cluster ids are
content-derived (uuid5 of member refs), so where Tier-3 moves membership the v9 Bank's
roles do **not** line up one-to-one with the live Bank's. Comparing the two Banks is
therefore role-by-member, not by id.

**Comparing against v8** (optional, read-only). `measure_parse_delta.py` compares two
parser versions within ONE database. On a fresh v9 Bank there is no v8 row, so §4's
numbers come from the copy measurement in this document, not from the v9 Bank.

**Teardown / retry.** The v9 Bank is disposable until the owner adopts it. Use
`teardown.ps1` in the v9 checkout (or `docker compose down -v` for its project only),
then run from step 1 again.

## 12. Merge of J4 + J2 into this branch (2026-10-20)

`git merge origin/feat/j2-cupe-form-structure`, which carries main (I1, J1, K2, I2), J4
(#214) and J2 (#216). Conflicts and how each was resolved:

| file | resolution |
|---|---|
| `composer/wjq_assemble.py` | **J2's version taken whole.** HR-246 supersedes v9's use of HR-263 in the assembler. HR-263 is kept, because the WJQ parser reads it. Its register text now says "read by the WJQ parser only". |
| `rules/loader.py` | Import union (`SFUDuty` from v9, `WJQForm` from J2). |
| `tests/export_roundtrip.py` | J2's new `_MAX_LIST_ITEM` / `_MAX_SUPERVISORY` kept; `_MAX_DUTY_STMT` stays rulebook-read (HR-261). The JDFN oracle now reads statement + how_why on re-read. |
| `tests/unit/test_composer_forms.py` | J2's version (majors and minors kept apart). |
| `tests/live/test_smoke_live_bank.py` | Both appended blocks kept; every test appears exactly once (checked for duplicate names). |
| `docs/decisions/HR-DECISION-REGISTER.md` | `git checkout --theirs`, then `make register` (never hand-merged). |

Tests that pinned v8's 12-function or "fused into the statement" behaviour were updated:
- J2's `_MAX_DUTIES` imports (removed in v9) were updated.
- The CupeForm ceiling test now reads the ceiling off the model.
- J4's two how/why re-read tests were updated.
- HR-246's text no longer describes the parser's twelve as a current limit.

**Register IDs:** J2 HR-246…253 · J4 HR-256…259 · v9 HR-261…266. No collisions; checked
with `uniq -d` over every `id:`.

## 13. Review round 1 (CHANGES REQUIRED, 2026-10-20) — H1, M2 and the small items

**H1 — "…:" lead-ins outside DUTIES were dropped.** Reading Word lists exposed
lead-in lines in Decision Making, Problem Solving and Qualifications that v8 had kept
fused into run-ons. `_structure_bullets` and `_structure_quals` dropped them. Examples:
whole degree requirements (`20190808_00121712_Manager.docx`), and the template's own
"The <title> is responsible for making decisions regarding:". **Fix:** apply the
duty rule — keep the line, minus its colon. Separately, a summary already at its 4,000
cap was losing tail words to the extractor's glyphs, so the glyphs are now stripped
from the summary before the cap.

**Full-archive, in-process v8 vs v9.** The reviewer's
`parse_dump.py` / `full_measure.py` were extended to cover every section and every
template. All 14,565 files, archive mounted `:ro`, no DB.

| section | docs losing words vs v8 | words lost |
|---|---:|---:|
| title | 0 | 0 |
| position summary | 0 | 0 |
| **duties** | **2** | **38** (one position, two versions; the documented 1,200-char cap on an unbulleted run-on, Q3) |
| decision making | 0 (was 4,784) | 0 (was 39,101) |
| problem solving | 0 (was 2,231) | 0 (was 14,686) |
| relationships | 0 | 0 |
| qualifications | 0 | 0 |
| additional context | 0 | 0 |

⚠ The template's DM/PS lead-in ("Responsible for solving problems related to") is
now an item of its own on every template-shaped document, as the review asked. The two
JDFN goldens (`tests/fixtures/golden_jdfn/`) were regenerated for exactly that change
and nothing else (diff: one added lead-in per list, plus a key re-order).

**Validator re-measured** in-process: the validator needs no DB, and the raw text is
`flatten_jd`, as before. These are documents whose parse changed vs v8.

| | v9 (quals split — shipped, Q2) | v9 with v8's qualifications |
|---|---:|---:|
| documents changed | 14,038 | 14,038 |
| approvable, v8 → v9 | **680 → 215** | 680 → 680 |
| `SFU-GATE-KSA-ORDER` newly firing | **2,777** (was 2,773) | 0 |
| `SFU-STRUCT-DUTIES-TOO-MANY` newly firing | 4,623 | 4,623 |
| `SFU-STRUCT-ACTION-VERB` newly firing | 980 | 980 |
| summed score change | −34,208 | −21,108 |

Keeping the qualification lead-ins moves KSA-ORDER by 4 documents and approvability not
at all. The Q2 ruling stands on these numbers.

**M2 — the how/why clauses are grounded.** A rewritten clause must have at least
`rewrite.how_why_grounding_threshold` (**HR-267**, 0.5, the same token-overlap rule as
the qualification bar HR-183) of its content tokens in its *source duty's own text*.
A clause below that is **dropped and recorded** (`AntiFabricationRecord.scrubbed_how_why`).
If every clause of a duty is dropped, the source duty's clauses come back. A flagged
duty (no source match) keeps no clauses. An ungrounded clause is never kept.

**Small items.**
- A typed glyph with no space ("•Tracks") now splits; `-` and `*` still need a space.
- `_MAX_BULLETS` 20 is now `segmentation.bullet_max_count` (**HR-268**, 40). Measured: max 25 items, 11 sections over 20. The model ceiling for Decision Making / Problem Solving is 20 → 60.
- The Builder's Decision Making / Problem Solving rows hold the model ceiling, because a draft is a union the merge cuts there.

Register IDs now: v9 HR-261…268, all used. Red-first evidence is in the commit.

## 14. The v9 Bank's first smoke (2026-10-20): 28 passed, 3 failed — fixes

The v9 Bank is a separate project (`jd-bank-v9`), built with deterministic
`--no-llm` drafts. Smoke was run against it read-only.

| # | finding | class | fix |
|---|---|---|---|
| 1 | 378 / 635 CUPE roles refused to clone: `FunctionAnswer.statement ≤ 400` | **consumer** (J2 Builder row narrower than v9 data) | Function rows read `SFUDuty.statement`'s ceiling. Grep of every answer/model constant found two more: JDFN `knowledge/skills/abilities` rows held 20 each (v9 drafts carry up to 24 / 23) → qualifications ceiling (40); `WJQForm.occupational_requirements` held 20 (CUPE drafts carry up to 30 ability lines) → 40. Tests red first. |
| 2 | the J2 clone smoke found no role: selector required `kind = knowledge` | **smoke predicate** (encoded "drafts are LLM-rewritten") | The WJQ parser never emits `knowledge` (v8 = v9, measured). Only the LLM rewrite did, so 0 of 635 deterministic CUPE drafts carry it, while 538 carry `ability`. The selector now takes knowledge **or** skill (both feed the one Occupational Skills list) **and** an ability line, so M3's ability → Requirements is still exercised. |
| 3a | `decision_making: 50 exported, 40 re-read` (2 roles) | **rulebook mismatch** (my HR-268 = 40 vs the merge's model-ceiling cut 60) | HR-268 → **60**, the model ceiling. A draft's list is a union the merge cuts there, and its export must re-read whole. The archive max is 25, so the cap still cuts no source. |
| 3b | `8 duties exported, 13 re-read` (2 roles) | **v9 regression** (extractor) | A nested how/why clause that starts with a typed number ("2. Calculating leases…") was read as top-level, so every later clause became a duty. A nested list paragraph is now a sub-item whatever it starts with. |
| 3c | "… Position #:" in titles (2 roles; **80** archive parses, v8 = v9) | **pre-existing parser** | `NEXT_LABEL_RX` ended in `\b`, which cannot match after "#". It now ends in `(?!\w)`. The number on that line is read into `position_number` (bundled lists and RTF `|` cells too), so no word is lost. Covered by the named limit until the Bank is re-ingested. |
| 3d | WJQ banner title on a JDFN role (1 role, 3 sources) | **pre-existing parser** | antiword stretched "Weighted   Job   Questionnaire", so the primary marker missed. `is_wjq` now collapses whitespace: **9** archive documents route to the WJQ reader, which drops their form scaffolding by design. |
| 3e | whitespace collapsed on re-read (3 roles) | **pre-existing parser** (fallback titles were raw lines) | Fallback titles are now `_clean`ed. |
| 3f | `position_number None came back '00099544'` (1 role) | **pre-existing merge/data** (members disagree, so no id; a member's summary text carries "Position Number: 00099544") | **Named limit** in `jdfn_parser_limits`, with its reason. |

**Full-archive in-process v8 vs v9 after these fixes:**
- Decision Making, Problem Solving, relationships, qualifications: **0** documents lose words.
- Duties: 2 documents (the documented 1,200-character run-on cap).
- Title: 83 documents lose only the label word "Position" (its id is now in `position_number`). 5 lose only v8's partial last word at its own 200-character cut.
- Summary and context words lost all belong to the **9 re-routed** CUPE forms (their approval and instruction scaffolding).

**Smoke now: 30 passed, 1 failed.** The one failure is the APSA test, with 8 losses in 4 roles: 3d and 3e. Those drafts were built from the pre-fix parse, so they need the Bank re-ingested. The 4 roles' source files re-parse correctly in-process (verified). **The re-ingest is held** until the rewrite pilot that reads the v9 Bank reports (coordinator's instruction).

## 11. Containers (all removed at the end)

- **This round:** `p9measure-dump`, `p9measure-pg` (127.0.0.1:25999, network `p9measure-net`), `p9measure-ingest-flat`, `p9measure-ingest-grouped`, `p9measure-mA` / `-mB` / `-mD`, `p9measure-losscause`, `p9measure-smoke`, `p9measure-intro`, and the network `p9measure-net`.
- **First round:** `p9measure-ingest`, `p9measure-measure`, `p9measure-measure2`, `p9measure-bygroup`, `p9measure-embedrate`.
- The dump files lived in the session scratchpad only and were deleted.

---

## Appendix A — parse-level queries (run on the copy)

```sql
-- how/why distribution (v9-grouped)
SELECT percentile_disc(ARRAY[0.5,0.9,0.99,1.0])
         WITHIN GROUP (ORDER BY jsonb_array_length(e->'how_why'))
FROM parsed_jds p, jsonb_array_elements(p.parsed->'duties') e
WHERE parser_version = 'jd_segmenter_v9' AND jsonb_array_length(e->'how_why') > 0;

-- duties per document, by version
SELECT parser_version,
       percentile_disc(ARRAY[0.5,0.99]) WITHIN GROUP (ORDER BY jsonb_array_length(parsed->'duties')),
       count(*) FILTER (WHERE jsonb_array_length(parsed->'duties') > 5)  AS over5,
       count(*) FILTER (WHERE jsonb_array_length(parsed->'duties') >= 13) AS n13
FROM parsed_jds
WHERE parser_version IN ('jd_segmenter_v8','jd_segmenter_v9flat','jd_segmenter_v9')
GROUP BY 1;

-- duties carrying more than J4's 12 how/why points (clone risk)
SELECT count(*), count(DISTINCT p.id)
FROM parsed_jds p, jsonb_array_elements(p.parsed->'duties') e
WHERE parser_version = 'jd_segmenter_v9' AND jsonb_array_length(e->'how_why') > 12;

-- current roles already carrying how/why (role re-embed from the serializer alone)
WITH cur AS (SELECT DISTINCT ON (cluster_id) * FROM canonical_jds
             ORDER BY cluster_id, version DESC)
SELECT count(*) FILTER (WHERE EXISTS (
         SELECT 1 FROM jsonb_array_elements(content->'duties') e
         WHERE jsonb_array_length(coalesce(e->'how_why','[]')) > 0))
FROM cur;
```

The per-document numbers (validator, embed identity, signals, clusters, merge, words
lost) come from `core/scripts/measure_parse_delta.py`: `--old/--new` and
`--duties-only`. The earlier v8 → v9-flat per-group query is kept in this file's history
(commit f9054db).

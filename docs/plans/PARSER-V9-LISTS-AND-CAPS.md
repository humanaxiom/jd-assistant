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

## 15. Rewrite fidelity (owner ruling 2026-10-20: "fix the rewrite first")

Branch `feat/rewrite-fidelity`, on top of this branch. A size-stratified rewrite pilot
on the v9 Bank (20 clusters: 5 at or below p50, 10 between p50 and p90, 5 large; plus
the 2 largest WJQ and 6 re-runs at `max_tokens` 4096) had each reply recorded. **Every
number below comes from replaying those recorded replies offline through the old and
the new guard.** There were no new LLM calls and no Bank writes. The merge drafts were
rebuilt read-only, and all 22 matched the stored drafts. The "before" replay reproduces
the pilot's own recorded anti-fabrication record **28 of 28** times, which validates the
replay. Rulebook knobs HR-269…HR-276 are all `open`. `rules_version` does not move
(`rewrite.yaml` and `quality.yaml` are unhashed). Prompt `jd_harmonize_v4`.

| # | defect (pilot) | design | where |
|---|---|---|---|
| 1 | At 2048, 4 of 22 first calls truncated (`length`, empty reply); one success used 93% of the content budget. The audit hit `length` 2 of 22 times at 1024. | `rewrite.max_tokens` 4096 (HR-178). `quality.max_tokens` 2048 (HR-187). Both carry the measured evidence and stay `open`. | `rewrite.yaml`, `quality.yaml` |
| 2 | Duty areas were dropped to fit the five-duty cap. The cap is HR policy and is untouched. | **Fold back** (HR-271, `fold_back` \| `record_only`). Every *sentence* of every source duty must be covered (the HR-267 fraction) by ONE rewritten duty. If not, it is appended verbatim as a how/why clause of the duty that holds the rest of its source duty, so the cap holds and nothing is lost (`folded_duty_content`). With `record_only` it is listed instead (`dropped_duty_content`, shown on the review page). Clauses are now grounded against a unit from ANY source duty (one unit, never a union), so a merged duty keeps its faithful clauses. Prompt v4 says: merge, never drop. | `harmonize._fold_back` |
| 3 | Decision Making, Problem Solving and Relationships items were never grounded. | Per item against ONE item of the merge's **same** section, plus the named-term rule (HR-269). A failing item is dropped (`scrubbed_items`). Each source sentence the kept items no longer cover is recorded (`uncovered_items`). It is put back verbatim if the section is listed in HR-270 (`restored_items`). | `_reconcile_list`, `_reconcile_relationships` |
| 4 | Qualifications were dropped invisibly. | The HR-183 rule, read from the source's end, against ONE kept qualification. Lost ones are recorded, and restored when HR-270 lists `qualifications`. | `_apply_anti_fabrication` |
| 5 | Recombination: boilerplate grounded a claim, and "ICOM" was passed off as "International Council on Museums". | The **source view** drops SFU boilerplate sentences, matched both ways at 0.8 (HR-273), plus the Coast Salish wording (HR-274). Those words cannot ground anything and are never restored. **Named terms** (an acronym, or a capitalized word in mid-sentence) must appear in the grounding source (HR-272). | `rewrite/fidelity.py` |
| 6 | 22994d3a: all 15 clauses scrubbed. | Two defects. (a) The old questionnaire's **instructions** reach the merge draft. Measured on 2,446 v9 drafts, they appear in 139–745 drafts depending on the instruction. The source view strips them, matching on the word sequence; wrapped `.doc` lines are matched as runs (HR-275/276). (b) Clauses were grounded only against the one matched duty. Fixed in item 2. Grounding was **not** loosened, because each test is still one unit. | `rewrite/fidelity.py` |

**Found while replaying, and fixed (tests red first):**
- A restore must never put back a template placeholder. A WJQ page header ("Position
  Number(s): ______01598______ Continued") was fused into a source duty, and folding it
  back tripped the **non-overridable** no-placeholders gate (HR-047). Such a sentence is
  now listed, not restored.
- A one-way boilerplate match stripped the duty heading "Community Engagement.", because
  both of its words appear in the About SFU paragraph. The match is now required in both
  directions.
- On a contact list, using restored sentences as covering vocabulary hid distinct
  contacts that share a department name. Section losses are now judged against the
  model's kept items only.

**Replay, 22 pilot clusters, before → after (the guard's own records):**

| | before | after |
|---|---:|---:|
| how/why clauses scrubbed | 182 | 125 |
| source duty sentences folded back (`folded_duty_content`) | 0 | 190 |
| duty content dropped, listed (`dropped_duty_content`) | 0 | 1 (a placeholder sentence) |
| section items scrubbed as ungrounded (`scrubbed_items`) | 0 | 83 |
| source items lost / put back (`uncovered_items` / `restored_items`) | 0 / 0 | 208 / 208 |
| qualifications scrubbed | 1 | 4 |
| instruction / boilerplate pieces stripped from the input | 0 | 84 in 21 of 22 drafts |

Scores move by less than 2.0 on 19 of 22 clusters. 1d68c603 rises 67.7 → 74.7.
e2c6052d falls 87.3 → 69.1: the model had kept 1 of 19 qualifications, and the 15
restored source qualifications carry a medium coded-term finding and two low ones. That
is the source's own content scored honestly. The per-cluster table is in the commit
message.

**What remains uncatchable:**
- **Recombination inside the source's own vocabulary.** A claim built from words that
  each appear in the same section, with no new name, still passes the 0.5 token bar. An
  example would be "Approves loans" if the section says "loans" and "approves"
  separately.
- **Paraphrase vs. invention without stemming.** "loan" does not match "loans", so a
  faithful paraphrase can be dropped. The source's wording then comes back. This is
  conservative: it loses prose, never content.
- **Semantic loss inside a covered sentence.** Coverage is token-level, so a sentence
  half of whose words survive counts as covered even if its meaning changed.
- **Parser fragments come back verbatim.** Examples are wrapped qualification lines
  ("(e.g. lab power supplies, …") and WJQ duration/frequency cells as separate contacts.
  They were in the merge draft, and restoring them is faithful but untidy.
- **The deterministic draft still carries the questionnaire instructions.** That applies
  when the rewrite fails or runs with `--no-llm`. The real fix is in the parser: it
  moves `PARSER_VERSION` and the placeholder gate (HR-047 reads "action verb" / "how and
  why"). That is an owner/HR decision and is not done here.

### 15.1 Follow-ups from the review of 934425f/320b4f8 (branch `feat/rewrite-provenance`)

Everything below renders from the STORED record. The v9 pass on 320b4f8 needs no re-run
to show items 1 and 2; items 3 and 4 change the producer, so only drafts made after them.

1. **NN #6 — what was put back is visible.** The review page marks restored text inline
   (↩) and lists it in "Restored verbatim from the source documents", by section and by the
   duty it sits under (read from `content`). A new record field, `folded_duty_origins`,
   names the source duty, and the per-source diff names the document. `jd_core/bank/
   restoration.py`.
2. **Every change-log reason is one plain sentence** (`REMOVED_REASON_LABELS`; a test
   holds it to the `RemovedReason` set). Sections use the rule catalog's labels.
3. **Strips say why.** `stripped_source_parts` records section + kind (instruction /
   boilerplate). Boilerplate found in a role-content section (HR-281: duties, Decision
   Making, Problem Solving, Relationships) reads "matched SFU's standard wording … check
   it is not part of the role". Older records keep a combined reason.
4. **Fold-back placement.** Placement reads what the model wrote, not the duty as folds
   grew it (89 of 314 pilot folds were misplaced by that; now 0). A floor (HR-279, 0.11):
   below it the content becomes its own duty if the form has room, and is listed
   otherwise. A per-duty limit (HR-280) was measured and is shipped off (0). At 10 it
   moved 22 points to worse-matching duties and listed 19 more.

Replay of the 28 recorded pilot replies (offline, no LLM, no Bank): folds 314 → 323,
listed 2 → 17 (15 sentences from 8 source duties, all on full drafts). 84 folds moved to
a better-matching duty. The largest single-duty pile fell 36 → 27. Scores were unchanged
on 27 of 28. 1d68c603 (base) went 67.7 → 74.7.

## 16. Rewrite fidelity, round 3 (second pilot, 2026-10-21)

Branch `feat/rewrite-r3`, on `feat/rewrite-provenance` @ 24e0440. The second pilot ran at
23f092c on the rebuilt v9 Bank (20 clusters plus re-runs at 8192 and an "extra" set with
the museum draft). **Every number here comes from replaying the recorded replies offline,
with no LLM calls and no Bank access.** The replay reproduces the pilot's recorded record
and final draft **23 of 23** times at 23f092c (the merge provenance was not recorded; it
turned out not to matter). Register IDs are HR-282…288 and all are `open`.
`rules_version` does not move.

| # | finding (second pilot) | design | where |
|---|---|---|---|
| 1 | At 4096, 4 of 20 first calls truncated in the reasoning phase; one cluster failed both attempts. | `rewrite.max_tokens` **8192** (HR-178). At 8192 the peaks were 72% reasoning and 46% content. | `rewrite.yaml` |
| 2 | HR-275 stripped "…decisions the incumbent would refer to his/her supervisor". cb73e45c then listed "Decisions regarding the expenditure of University funds" as the incumbent's own decision. | The merge **pools and sorts** Decision Making (HR-210), so after merging no position says what is referred. The archive check covered **4,115 of 14,522** documents carrying the prompt: in 2,928 the answer is fused into the prompt's item, and 5,721 referred items follow it. Fix in the **merge**, per member, before pooling: each referred decision gets the label "Refers to the supervisor:" (HR-282 markers, HR-283 label). This also fixes the **deterministic draft**. In the rewrite, a decision grounded only in a referred item must keep the referral, or it is dropped and the source line comes back. | `merge.label_referred_decisions`, `harmonize._reconcile_list` |
| 3 | On cb73e45c, two lost sentences appeared in no record. | The coverage test (`_DutyCoverage`) was wrong in two ways. "careers…" was counted covered by the model's words **plus text fold-back had just restored** ("academic offerings"). "…Cooperative Education" was covered by two generic words without its name. Now restored text covers only as **one** restored sentence, never pooled. A covering duty must also state the sentence's **named terms** (HR-272; in a Title Case heading only acronyms count). | `harmonize._DutyCoverage` |
| 4 | Fold-back duplicated text the model had reworded. | A model **piece** (cut at ";" or a sentence end, or a comma part of one) covers a sentence if ≥ HR-267 of the piece's words are in the sentence and the piece keeps ≥ **0.4** of the sentence (HR-284). Stemming (HR-285) applies **only** to the piece and restored tests. Stemming the whole duty produced ~8 false covers in 30. For a how/why clause, the words it shares with its own headline do not count. | `harmonize._DutyCoverage` |
| 5 | "V. P." was split into its own sentence, giving the fold "Collaborates with V.". | Initials, dotted acronyms and a rulebook abbreviation list (HR-286) do not end a sentence. Every caller splits the same way. | `fidelity.sentences` |
| 6 | Fragments were restored: "Makes decisions regarding", "…and involves", "(e.g. … curve tracers,". | Fragments (HR-287) are **listed, never restored on their own**. An item at the parser's own character cap was cut by the parser, so its unterminated last sentence is listed. Section items are restored **whole**. | `fidelity.is_fragment` / `cut_off_tail`, `_ItemLog.losses` |
| 7 | 22 contact names grounded in duty text were scrubbed. | Measured on the replay: of 30 scrubbed contacts, 7 were WJQ contacts written *with* their duration and frequency (which prompt v4 asks for), 11 were another member's "Engineering Science" contacts, 8 were duty-derived, and 2 were summary-only. **Same-section grounding stays**, because one duty-derived "contact" was "First Nations territories…". A contact is now grounded against a **row** of up to 3 consecutive items (HR-288). | `_reconcile_relationships` |

Red first: 15 of 17 new tests failed on the base (`test_rewrite_fidelity_r3.py`). Every
guard, broken once, turns red (the mutation script is in the session scratchpad).

**Replay of the 23 round-2 replies, base (24e0440) → this branch:**

| | before | after |
|---|---:|---:|
| source duty sentences folded back | 120 | 130 |
| duty content listed, not restored | 5 | 23 (the 18 new ones are all lead-in headlines or table cut-offs) |
| section items restored | 191 | 112 (whole items now, and no fragments) |
| restored lead-ins / cut-offs / continuation lines | 32 | **0** |
| Relationships items scrubbed | 30 | 19 |
| scores | — | unchanged on all 23 |

The reviewer's exact-accounting check (every source duty sentence in exactly one bucket;
folded text verbatim and placed once; listed text absent; origins aligned; caps held)
gives **0 failures** with the guard's own coverage predicate, both on 912 sentences
(base + 8192) and on 1,105 (with the museum run). Run with its **original** coverage
definition, it reports 36 disagreements, which is the definition change itself:
- 16 sentences are now judged reworded. A hand check found 12 genuine, 3 partial and 1
  borderline.
- 20 sentences are now folded or listed that the old rule counted covered.

**What remains uncatchable, or is a trade-off:**
- "refers X" → "oversees X" inside a **duty**. Duties are flagged, never dropped
  (HR-184); cb73e45c's "Oversee budgetary decisions…" is flagged. Catching the inversion
  needs meaning, not token overlap.
- **Partial rewordings** above the 0.4 share count as covered (3 of 16 on the replay).
- On clusters with many near-duplicate members (c7d30688), more near-similar sentences
  come back (17 new folds). The earlier pooled vocabulary had hidden them, which is the
  item-3 defect.
- **The merge labelling moves the deterministic draft** for every cluster whose members
  carry a marker. The replay used the recorded merge drafts, so item 2 is proven by the
  merge test and the archive measurement, not by the replay.

## 17. Post-pass fixes (the v9 full pass, 2026-10-27; branch `feat/v9-postpass-fixes`)

The full pass (2,446 drafts, 50 fallbacks) left smoke at 29/31 and `bank-audit` red.
Everything below was measured read-only: the v9 Bank exported through `--rm` containers
on `jd-bank-v9_default` with `default_transaction_read_only=on`, merges rebuilt
in-process (the rebuild reproduces all 50 stored fallback drafts byte for byte), and an
offline guard replay over the 2,396 rewritten drafts (reply = stored draft minus the
guard's own restores; with the new rules off it reproduces the stored blocking set on
2,390). Register HR-290…295 (all `open`); HR-275/282/287 updated. `rules_version` does
not move. Tests: `core/tests/unit/test_rewrite_postpass_v9.py` (21 of 23 red on
`bank/v9`; each guard broken once in a scratch copy turns its test red).

| # | finding | cause | fix |
|---|---|---|---|
| 1 | 0cd5db26: 13 CUPE major functions, clone refused (HR-246) | the model's reply was never held to the form | HR-290: merge the closest pair until the form fits (never drop); clause cap too |
| 2 | 4 APSA roles re-read a position number; 23a58c9c also 5→6 duties | fold-back restored the source's PAGE HEADER ("Position Number 31160 (Continued) C. DUTIES…") as a clause; the export put it at a line start | HR-291: page headers set aside in the source view (170 of 198 occurrences in merge role text; the 28 left name another position) |
| 3 | JDFN decision_making carry-through 1752/1755 | **parser**, not the rewrite: in 21 antiword `.doc` files the wrapped prompt line "duties" is read as the DUTIES heading, so Decision Making holds only "…make in carrying out" and the decisions (made AND referred) land in duties. A candidate rule ("an all-lower-case heading line after a line with no closing punctuation is a wrapped line") hits 45 lines in 42 archive files — also "relationships"/"education and experience"/"qualifications:" mid-qualifications | **not fixed here**: it moves `PARSER_VERSION` and owes a re-ingest — an owner decision (as in §15). The gate stays red on 3 clusters (ca79961d, 5b0818e9, 4161bcd0) |
| 4 | referred decisions unlabelled (82e5c2d0 "Staff terminations") | 14 more wordings of the refer question | HR-282/275: markers + prompts; 154 documents, 457 decisions, 34 clusters' merge drafts. A cut ";" list now returns its whole entries (HR-287) |
| 5 | audit: "rewrite destroying frequency" (59.3% vs 59.5%) | the flag is noise (z = 0.03, different clusters); PAIRED against each draft's own merge the loss is real: 63.1% → 59.3%, all on flagged duties | HR-292: a flagged duty that covers every sentence of one source duty carries its frequency (19 in 18 drafts) |
| 6 | K→S→A: 612/636 CUPE, 359/1,810 JDFN fail after the rewrite, 0 before | reassembly kept the model's order, appended restores and bars; model relabelled kinds | HR-293 form order by `ksa_rank`; HR-294 kind from the source line. Replay: 612→0 and 359→0 |
| 7 | summary gains working conditions (~30 of 49 CUPE) | the model imported the WJQ's conditions block | HR-295: a summary sentence naming a condition marker its source summary lacks is dropped. Replay: 49→13 CUPE, 50→30 JDFN; of 64 sentences dropped, 20 are marker noun matches (HR-046, unchanged) |

Replay, all fixes together: approvable 0 → 7 CUPE, 452 → 742 JDFN.

**Review of 6000ba6 (CHANGES REQUIRED) — fixed, tests red first, each guard broken once:**
HR-294 is per form (`[wjq]`: on CUPE the kind is the form section; on JDFN it forced
93 lines in 79 drafts to a kind their own wording contradicts); a relabel needs HR-302's
overlap (0.5) and never contradicts a line's own lead word (HR-303) unless the source
line opens with the same word. HR-290 orders by similarity only and merges only above
HR-304's floor (0.2) — below it the surplus duty is listed; a merge keeps an agreeing
frequency and records a conflict; a flagged duty merged away is flagged by the duty it
went under. HR-291 also takes "Position number(s): __01110___Continued" and a trailing
"Position Number 07514". HR-295 keeps paragraph breaks. Replay after the review (mine
and the reviewer's agree): approvable unchanged at 7 CUPE / 742 JDFN, K→S→A 0 / 0,
summary conditions 13 / 30; relabels 6,546 CUPE (none under half overlap), 0 JDFN.
Still open: in 4 JDFN drafts the form order moves an "or an equivalent combination…"
continuation line away from the degree line it continues (it is kinded as a
competency by the parser).

**Round 2 (APPROVED, two follow-ups):** HR-303 is per form (`jdfn` only): on the WJQ
the kind is the form section, and the guard had kept `ability` on 65 CUPE lines whose
source is `skill` (and `knowledge` on 109 more). Replay: those 174 now take the
source's kind; 93 CUPE drafts change in qualification kind/order only; no blocking set
or approvable count moves. HR-290's register text now says what usually happens: 395 of
the 587 CUPE drafts with 12+ model duties have their closest pair below HR-304's 0.2,
so an overflow usually LISTS the model's last duty (fold-back protects the source
content). Listing the least-similar duty instead was not done (a choice, not a fix).

**Owner ruling (2026-10-27): ONE FULL PASS, not tiers.** The lists below stay as the
per-cluster record of WHY each draft changes; the re-run is all 2,446 (≈ 89 h at the
pass's own rate).

**Re-run list** (`docs/canonical/v9-postpass-rerun.json`, reasons per cluster):
tier 1 (a defect in the stored draft) 1,109 clusters (613 CUPE, 496 JDFN,
`v9-postpass-rerun-tier1.txt`); all 1,633 (`v9-postpass-rerun-all.txt`) adds every CUPE
draft and the JDFN drafts whose qualification order/kinds change. At the pass's own
rate (318,046 s / 2,446 ≈ 130 s per cluster): tier 1 ≈ 40 h, all ≈ 59 h of GPU.

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

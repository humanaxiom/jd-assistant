**Verdict: APPROVE WITH CHANGES.** The parser work holds up over the whole archive: no crashes, no lost headings, and all 38 demotions are correct. Two things need fixing before the full rebuild:

- **D1:** 16 documents have their real qualifications filed as "working conditions" and set aside.
- **D2:** the design doc says those headings are "not changed".

Separately, the 600-character supervisory cap (unregistered, and not touched by this branch) cuts 59% of supervisory texts and should be decided before the rebuild. Directive #0 still applies: I did not run `make smoke` (no live v10 Bank), so this is not clearance to merge.

Reviewed: `origin/feat/v9-parser-wrap` @ e547a74. My scope was the parser commits e05fe61 and 37c9f29. The postpass part (9d7b175) was approved earlier and was not re-reviewed. Parent for comparison: `bank/v9` @ e584c53 (`jd_segmenter_v9`). I also parsed the intermediate tree e05fe61 ("vw" below: wrap guard only, also `jd_segmenter_v10`), so each commit's effect can be seen separately. All runs used Docker image `jd-bank-api:v9` with the branch's code exported by `git archive` (nothing was checked out in the v9 checkout). The archive was mounted `:ro`. Scripts are in `<scratch>/scripts/` and raw outputs in `<scratch>/out/`, where `<scratch>` = `C:\Users\adam\AppData\Local\Temp\claude\c--repos-JD-Assistant\4cfbcd11-2bea-4032-81f9-014ebb9bff7b\scratchpad`.

---

## 1. Whole-archive check (all 14,565 files)

```
# extract once with the branch's own extractor (antiword / python-docx / striprtf)
docker run --rm -v <scratch>/v10/core:/app -v C:/repos/hris/fixtures/SFU_JDs:/archive:ro ... python -I /scripts/extract_all.py
  files 14565
  extracted 14522 errors 43          # .tif/.serv/.dot/the 89 MB .rtf etc. - the same 14,522 the branch cites
# parse every extracted text with each tree (same texts.jsonl for all three)
for t in v9 vw v10: docker run ... -v <scratch>/$t/core:/app ... python -I /scripts/parse_all.py $t
  v9  jd_segmenter_v9  rows 14565 parse_errors 0
  vw  jd_segmenter_v10 rows 14565 parse_errors 0
  v10 jd_segmenter_v10 rows 14565 parse_errors 0
docker run ... python -I /scripts/analyze.py v9 v10
```

**v9 -> v10 (the branch as a whole):**
```
docs parsed: 14522
docs whose parsed JD changed at all: 5924
fields changed (docs): {'qualifications': 5856, 'set_aside': 4806, 'relationships': 1524, 'duties': 59, 'decision_making': 44, 'position_summary': 17}
docs with >=1 qualification: [9401, 14127]  qualification words: [1911368, 2618721]
docs gaining qualifications from none: 4726
docs with relationship words: [13672, 13676]  gaining relationships from none: 4
docs that LOSE a heading they had: 0 {}
headings gained (docs): {'qualifications': 4727, 'relationships': 5}
set_aside: docs 4806 blocks by kind {'legacy_working_conditions': 4725, 'form_approvals': 3155, 'form_prompt': 3298}
```
**v9 -> vw (e05fe61 only):** 27 docs change: duties 21, decision_making 21, qualifications 6, relationships 2. 4 docs lose their Qualifications heading (the 4 the commit names). **vw -> v10 (37c9f29 only):** 5,924 docs change. 4,730 gain qualifications from none. Docs with qualifications go 9,397 -> 14,127. **0 docs lose a heading.**

**Crashes or exceptions:** 0 parse errors across 14,522 texts in all three trees. The 43 extraction errors come from the extractor, which this branch does not change.

**Words lost** (multiset of content words in A that are in neither B's content nor B's `set_aside`). I then removed single letters, heading words ("entrance", "qualifications"...) and old-cut word fragments (`realloss.py`):
```
v9->vw  real-loss words: 556 in 5 docs   (4 docs = the Systems_consultantI x3 + Web_Services_Developer the commit names; 1 doc 3 words)
vw->v10 real-loss words: 466 in 72 docs
v9->v10 real-loss words: 481 in 75 docs  (the 4 wrap-guard docs are whole again)
```
The largest v9->v10 losses are real requirements cut at the 400 qualification cap. Example: `20180301_00123117_Associate_Student_Recruiter.doc` has one 400-char item ending "...excellent interpersonal, communication (both oral and wri" and loses "public speaking, analytical reasoning..., valid driver's license". Smaller losses are supervisory text cut at 600 (e.g. `20090901_00006571_Executive_Director_LSG.docx`, 25 words of reporting-chart text). Without the cleanup filter, the raw multiset loss vw->v10 is 4,583 words in 2,151 docs, almost all heading words and fragments. The branch's 3,860 / 551 figures use a different tokenizer, so they are not directly comparable, but they are the same order of magnitude.

---

## 2. Set-aside text: random sample + targeted search

```
docker run ... python -I /scripts/sample_aside.py      # random.seed(20261029), 32 of 4,806 docs with set_aside
```
**Random sample of 32 docs, read in full (`out/aside_sample.txt`). 0 misfiled.**
- Every `legacy_working_conditions` block is working-conditions text. Typical blocks: "Requires some evening and weekend work", "...work outside of normal working hours to install, maintain, and support the system", "None.". Some include the form's own question "Describe unusual working conditions...". A few describe the unit, e.g. `20160607_00030115_Manager.docx` ("The School for the Contemporary Arts contains 6 constituent disciplinary areas..."). That is context, but the author put it under G.
- Every `form_approvals` block is signature and date lines. 8 of the 32 also carry the org-chart text box that antiword puts after it (e.g. "Associate Director, Financial Aid & Awards, APSA grade 10 #30262 Advising Assistant - CUPE Grade 7..."). That is chart scaffolding, not JD prose.
- Every `form_prompt` is exactly the printed question (143-179 chars; the longest in the whole archive is 179).

**Targeted search over all 7,900 G/J blocks (`aside.py`, `swallow.py`, `hidden.py`) found a real misfile.** In 16 documents the qualifications heading is spelled in a way HR-300 does not match. The G block then runs on through the whole qualifications section, so the qualifications are set aside as *working conditions* and never reach the JD:
```
set-aside blocks containing an unrecognised qualifications-type heading line: 16 docs 16
  'H. QUALIFICATIONS REQUIRED'         x6 (5 coach JDs + 20050302_00001157Marketing_coordinator.doc)
  'H         ENTRANCE QUALIFICATIONS'  x4 (letter with no '.'): 20030909_00030713, 20041031_00006706, 20060327_00000320, 20061016_00006706
  'H. ENTRANCE   OUALIFICATIONS'       x2 (OCR O for Q): 19980701_00031889, 20070523_00031889
  'H.    ENTRANCE QUALIFIACTIONS'      x2: 20050421_00006885Supervisor_NMR.doc, 20100624_00107935_Supervisor_NMR.docx
  'H.       ENTRANCE OUALIFICIATIONS'  x1: 20060315_00000794_Systems_consultantI.doc
  'H.\tENTRANCE QUALIFICATIONS TO BE REVIEWED' x1: 20120313_00000317_Mgr_Teaching_Learning_Prgms.docx
```
Quoted, `20010201_00000224Head_men_s_soccer_coach.doc`, block `[legacy_working_conditions]` (v10 qualifications: **0**):
> "...include a large number of evening and week-end hours... **H. QUALIFICATIONS REQUIRED** University degree in kinesiology, physical education, coaching, or related field. Or an equivalent combination of education, training and experience. National Coaching Certification Program - Level IV or Level III... Minimum of 5 years coaching experience..."

Also `20050421_00006885Supervisor_NMR.doc` (v10 qualifications: 0):
> "None. H. ENTRANCE QUALIFIACTIONS What combination of experience... Doctorate in Science and 4 years directly related experience... Excellent knowledge of scientific grant application procedures..."

Three G blocks (`19901029_00000063Laboratory_coordinator.doc` and 2 more) also contain the form's "A. BUDGET / B. SIZE OF DEPARTMENT" scope table. That is borderline and is not counted above.

**Approvals false positives: none found.** All 3,158 J headings are spellings of APPROVAL(S) (`J. APPROVALS` 2,686, bare `APPROVALS` 325, `I./K./L. APPROVALS`...). Only 11 blocks lack signature/date text, and those are empty or hold just "SHOULD YOU REQUIRE FURTHER ASSISTANCE..." or an org chart. No document from 2023 on has any set-aside (4,784 old-era, 21 "new", 1 unknown).

---

## 3. Headings demoted by the wrap guard (HR-298/299)

```
docker run ... python -I /scripts/demoted.py      # heading lines in v9's _segment minus v10's, JDFN reader
v9 heading lines that v10 reads as content: 38 in 36 docs
legacy-pattern lines demoted by the guard: 14
```
I classified **all 38** (more than the 30 asked for): **38 correct, 0 wrong.**
- 21 are `duties` / `duties:` under "i) Decisions the incumbent is expected to make in carrying out" (e.g. `20030609_00001661Career_account_manager.doc`, `20220414_00101778_JDFN_APSA_20220411.doc`).
- 12 are `relationships` under "...effective collegial" / "...long-term corporate" / "...nurture ongoing" (e.g. `20050623_00076018Program_director.doc`, `20090909_00001664_Mgr_MBA_Careers_Corp_Connect.doc`).
- 5 are `education and experience` under "...combination of" / "of" / "of equivalent" (`Systems_consultantI` x3, `20060307_00001390IT_coordinator.doc`, `20090123_00105512_Web_Services_Developer.doc`).

In every case the line above ends in a letter and the demoted line finishes its sentence. This matches the e05fe61 claim (38 in 36 files). The guard also correctly stopped 14 wrapped "approval." lines from opening a J block (e.g. "...presents to the Dean for / approval.").

Decision Making recovered (`misc.py`): `v9->vw docs whose decision_making changed: 21 items 21 -> 323`. Adding the 41 unchanged items of the other 6 of the 27 docs gives 62 -> 364, which **reproduces** the commit's figure.

---

## 4. The caps

`caps.py` patches the parser (single process: `capcontent3.py`) to record lengths before any cut, over all 14,522 texts under v10 segmentation.

**Supervisory, 600 chars (`_MAX_SUPERVISORY`, a code constant and NOT registered; it is also `SFURelationships.supervisory` max_length):**
```
SUPERVISORY (JDFN reader; raw pre-cap length, one per doc with a value)
  distribution: {50: 695, 75: 977, 90: 1221, 95: 1454, 99: 2711, 99.9: 4329, 'max': 5185, 'n': 9811}
  cap 600: 5772 docs over (58.83%), 2478976 chars cut
  cap 800: 4130 docs over (42.10%), 1499318 chars cut
  cap 1000: 2237 docs over (22.80%), 865980 chars cut
  cap 1200: 1042 docs over (10.62%), 555030 chars cut
  cap 1500: 446 docs over (4.55%), 353004 chars cut
  label/prompt text present in over-cap supervisory: {'indicate the number': 3421, 'describe the extent': 3358, 'supervision received': 238, 'primary working relationships': 72}
  with the two E/F form prompts removed:  over 600: 4162 | over 800: 2023 | over 1000: 1026 | over 1200: 618
  prompt-stripped p50/p75/p90/p95/p99: [552, 742, 1016, 1291, 2711]
```
`v10 supervisory exactly at 600: 5778` (vw: 6,793), which reproduces HR-301.

The cap cuts the majority of legacy supervisory texts. In 3,421 of the 5,772 over-cap texts, the form's printed E/F questions ("Indicate the number of employees for whom the position is responsible...", "Describe the extent to which the supervisor determines...") use up the budget first. Modern 2019+ forms lose their "Primary Working Relationships" prose (e.g. `20240213_111326_JDFN_APSA_20240312.docx` is cut at "...the Security Office, ").

**Recommendation: raise, in two steps.**
1. Extend HR-307's prompt stripping to the Relationships section's E/F/I questions. That alone takes 5,772 -> 4,162 over 600.
2. Move the cap into `segmentation.yaml` with its own register entry, and raise it to **1,200**. After prompt stripping that cuts 618 docs (6.3% of 9,811); 1,000 would cut 1,026 (10.5%).

Raising it also changes the `SFURelationships.supervisory` contract and the export form, so it is an owner/HR decision. It should be decided before the one full rebuild, because the rebuild bakes these cuts into every draft. As it stands the 600 number is an unregistered code constant that this branch's own HR-301 now depends on.

**Qualification, 400 chars (HR-308):**
```
JDFN qual pieces total: 93423  (after v10's sentence split)
  single-sentence pieces over 400: 1112 in 1053 docs, 201218 chars cut; equivalence clause cut: 308
  single-sentence pieces over 500: 507 in 492 docs, 127316 chars cut; equivalence clause cut: 45
  single-sentence pieces over 600: 306 in 304 docs, 88608 chars cut; equivalence clause cut: 14
  single-sentence pieces over 800: 131 in 131 docs, 44888 chars cut; equivalence clause cut: 1
  over-400 by file year: ... 2017 64, 2018 74, 2019 198, 2020 108, 2021 115, 2022 69, 2023 35, 2024 33, 2025 48, 2026 12
QUALIFICATION, JDFN reader, raw logical items (no split, no cut)
  distribution: {50: 88, 75: 132, 90: 270, 95: 468, 99: 1332, 99.9: 2052, 'max': 3179, 'n': 84517}   # reproduces HR-308 exactly
  raw over 400: 4713 items
QUALIFICATION, WJQ reader: p99 206, max 501; cap 400: 5 lines over in 5 docs, 179 chars cut
```
Splitting at sentences works for the run-together legacy answers. What is still cut is mostly the **modern** single-sentence education requirement ("Bachelor's degree in ... and N years of related experience in ..., or an equivalent combination of education, training, and experience."), which runs 404-700 chars. In **308** of these the cut removes the equivalency clause, which is the part HR relies on. **Recommendation: raise to 600** (306 pieces still cut, 14 equivalency clauses), or 800 (131 pieces, 1 clause). WJQ is unaffected at either value (max 501). This needs `SFUQualification.text` raised, which the loader enforces, and the Builder CUPE skill limit that shares it to be checked. Alternatively, also split at ";" inside a sentence. Keeping 400 knowingly drops the equivalency clause from ~300 documents.

---

## 5. `set_aside` plumbing

- **Model** (`core/src/jd_core/models/parsed_jd.py:136-150, 316-331`): `SetAsideSection(kind: Literal[3], heading 1..200, text <=20,000)`. `SFUJobDescription.set_aside: list = Field(default_factory=list, max_length=10)`, and the serializer drops it when empty. Defaults are present. The parser emits at most 4 blocks (2 G/J kinds + 2 prompt blocks), so 10 is safe.
- **Migration:** none needed and none present. The parse is stored as JSONB (`grep set_aside alembic db` returns nothing).
- **Never in a draft:** confirmed by reading the code. `merge_cluster` builds the draft field by field (`merge.py:1107`, no `set_aside`). The LLM rewrite returns a full `SFUJobDescription`, but `harmonize.py:1498` rebuilds from `merged.draft` plus an allow-list of rewritable fields, so a model-filled `set_aside` is discarded. `unmerged_content` lists explicit sections only, so no spurious `sections_not_merged`.
- **UI** (`core/src/api/templates/jd_view.html:39-50`): the panel renders only when non-empty. Jinja autoescape is on and `pre` is `white-space:pre-wrap`. Tested by `test_source_jd_shows_what_the_parser_set_aside` / `..._shows_no_panel`. *Readability issue:* the stored text is `_clean(body)` (`segmenter.py:719`), which collapses every newline, so signature blocks and org charts show as one run-on line.
- **Round trip** (`roundtrip.py`, all 4,806 set-aside docs):
  ```
  docs with set_aside: 4806 | JSON dump -> model_validate -> dump identical: 4806
  render -> re-parse: re-parse has set_aside in 0 docs; fewer qualifications in 0
  ```
- **Register drift and defaults:**
  ```
  docker run -i ... python -m src.jd_core.rules.render --check < docs/decisions/HR-DECISION-REGISTER.md
    docs/decisions/HR-DECISION-REGISTER.md is in step with the register.   exit=0
  regcheck.py: HR-298 MATCH, HR-299 MATCH, HR-300 MATCH, HR-301 MATCH, HR-305 MATCH, HR-306 MATCH, HR-307 MATCH, HR-308 MATCH
  ```
  (`current_default` was compared with the live loaded `Segmentation` value, string-equal including the full HR-307 regex.) The register text matches what the code does. HR-300's 9,397 -> 14,127 / 4,730, HR-305's 4,725 docs / longest 4,749, HR-306's 3,155 / longest 3,555, HR-307's 3,298 and HR-308's distribution all reproduced. Two knobs are not YAML: the "no 1./c) numbering" clause of HR-298 is the code regex `_ENUMERATED_RE` (`segmenter.py:647`), and the 600 supervisory cap is unregistered (see section 4).
- **Unit suite** (full branch tree, the gates service's mounts and env reproduced by hand):
  ```
  docker run --rm -v <scratch>/v10run/core:/app -v .../docker-compose.yml:/docker-compose.yml:ro -v .../docker-compose.prod.yml:/docker-compose.prod.yml:ro -v .../deploy/parallel-bank.env.example:/parallel-bank.env.example:ro -w /app -e CAS_ENABLED=false ... jd-bank-api:v9 -m pytest tests/unit -q
  3251 passed, 1 warning in 153.39s (0:02:33)        pytest exit=0
  ```
  (A first run without the compose mounts failed 20 tests in `test_production_compose.py` / `test_compose_parallel_bank.py` with FileNotFoundError, which is a mount artefact.) **Guards break red:** with `_is_wrapped_line` forced off, `9 failed, 33 passed` in the two parser test files. With the approvals pattern disabled, `5 failed, 20 passed`.

---

## Defects

| # | Severity | Where | What breaks | How to see it |
|---|---|---|---|---|
| D1 | **Medium** | `core/src/jd_core/rules/segmentation.yaml:321` (HR-300 pattern) + `core/src/jd_core/parser/headings.py:172` (`_LETTER_PREFIX` needs `[.)]`) | 16 docs: the G block swallows the real qualifications and labels them "working conditions"; the JD gets 0 qualifications. The heading variants missed are `QUALIFICATIONS REQUIRED` 6, unpunctuated `H   ENTRANCE QUALIFICATIONS` 4 (32 docs have unpunctuated G/H/I/J headings in all), `OUALIFICATIONS` 2, `QUALIFIACTIONS` 2, `OUALIFICIATIONS` 1, `... TO BE REVIEWED` 1. | `hidden.py` output in section 2; `20010201_00000224Head_men_s_soccer_coach.doc` |
| D2 | Medium (record) | `docs/plans/PARSER-V9-LISTS-AND-CAPS.md` section 19 heading-inventory row "typos ... `QUALIFICATIONS REQUIRED` 6 ... **not changed**" | Wrong since 37c9f29: those 6 docs moved from Relationships into a *set-aside* block, out of the JD. | same |
| D3 | Medium (decision, not code) | `core/src/jd_core/parser/segmenter.py:144` `_MAX_SUPERVISORY = 600`, `parsed_jd.py:120` | Cuts 5,772 / 9,811 (58.8%) supervisory texts, 2.48 M chars. Unregistered and not YAML, which breaks the standing rule now that HR-301 relies on it. The E/F form prompts fill it first. | section 4 |
| D4 | Low-Medium | `segmentation.qualification_max_chars` 400 / `parsed_jd.py:109`; cut at `segmenter.py:561` | 1,112 single-sentence qualifications cut in 1,053 docs, and 308 lose "or an equivalent combination of education, training and experience". | section 4 |
| D5 | Low | `segmenter.py:350` `_SENTENCE_BREAK` used by the HR-308 split | Splits inside parentheticals after "e.g." / "i.e." (and initials), giving fragments such as "...software (i.e." + "Word, Excel, Powerpoint) Ability to...". 215 split boundaries follow an abbreviation, in 197 docs (some are legitimate "etc." sentence ends). Before v10 these items were simply cut, so this is not a regression. | `splitq.py` |
| D6 | Low | `segmenter.py:719` `text=_clean(body)` | Set-aside text loses its line breaks; signature blocks and org charts read as one blob on the source page. | any J block in `out/aside_sample.txt` |
| D7 | Low | `segmenter.py:647` `_ENUMERATED_RE` | Part of HR-298's rule ("no 1. / c) numbering") is code, not YAML. | read |

The diff has no missing default, no off-by-one in `_sentence_chunks` (it checks `len(current)+1+len(sentence) > max`) and no over-matching approvals regex in the archive (section 2). The DM prompt regex is correctly line-anchored and does not cut the longer "Give some typical examples..." question.

## What I could not verify

- **`make smoke`** (Directive #0): not run. There is no v10 Bank and the v9 checkout belongs to another agent. Integration tests (testcontainers) were not run either.
- **Commit and design-doc claims I could not reproduce:**
  - "**4,865** docs change" (vw->v10): I measure **5,924**. 1,074 of them change only in `qualifications` (the HR-308 sentence split on documents with no legacy tail), which the branch may have counted differently.
  - "Items left at the cut: **1,225**": I measure **1,117** (1,112 JDFN + 5 WJQ).
  - "+604,599 qualification words / 421,346 set aside / 3,860 lost / 767 words in 7 docs": my tokenizer gives +707,992 / 427,218 (with headings) / 4,583 raw (466 after removing artefacts) / 556 real words in 5 docs. These are the same order of magnitude but not the same numbers.
- **Approve-gate counts** (MANDATORY-SECTIONS 4,783 -> 191, KSA-ORDER 58 -> 1,871, "Approvable unchanged"): not run.
- **Builder/CUPE UI** effects of changing the 400 contract: not checked.

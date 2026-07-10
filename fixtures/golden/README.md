# Golden Fixture Set — SFU JD Archive

**Created:** 2026-07-10 (Phase 0 · Task 0.2)
**Source (READ-ONLY):** `C:\repos\hris\fixtures\SFU_JDs` (14,565-doc corpus)
**Selection rationale:** `docs/audit/archive-census.md`
**Count:** 44 documents

This is a **stratified** sample of the SFU JD archive, curated to exercise every ingestion
and dedup edge case in one small, reviewable set. Per the `CLAUDE.md` invariant *"FIXTURES
ARE SACRED"*, this directory changes only via reviewed PRs, and every future pilot bug
should add a regression fixture here.

---

## Incumbent names — quality note, not a privacy blocker

**Decision (2026-07-10, project owner):** these are Job Descriptions, not resumes — there is
**no resume-grade PII concern** here. The raw docs are **safe to commit** in this local repo.

The census did find incumbent-name fields (`NAME OF EMPLOYEE:` / `INCUMBENT:`) in older
templates (~56% of sampled docs, up to ~80–90% OLD-era). Those are handled as a **rulebook
quality step**, not a privacy gate: SFU JDs describe *the role, not the person*, so the
ingestion/harmonization pipeline normalizes incumbent names out of **canonical** JDs. Source
fixtures keep them as-is — they're the input we test the normalizer against. Local-first /
Ollama-only inference still applies to all JD content.

---

## Stratification coverage

| Dimension | Coverage in this set |
|---|---|
| Era | OLD (1967–2009), TRANSITION (2010–2018), NEW (2019–2026) |
| Format | `.doc`, `.docx`, `.docm`, `.dot`, `.rtf`, `.txt`, `.tif`, `.serv` |
| Role families | Assistant, Analyst/Systems, Coordinator, Manager, Director, Clerk, Secretary, Technician, Officer, Specialist, Program/Project Manager, APEX/Executive, CUPE/Union |
| Employee groups | APSA, APEX, CUPE (new-era `JDFN` tags) |
| Dedup cases | 1 exact-dup cluster (pos `00000293`, Rec Services), 1 long revision chain (pos `00124799`, 4 versions incl. multi-ID bundle + caret-joined IDs) |
| Parse difficulty | Easy (`.docx`/`.txt`/`.rtf`), hard-legacy (`.doc`), unrecoverable (`.tif` OCR, `.serv` opaque) |

## Manifest (44 files)

Era legend: **OLD** = pre-2010 paper-derived template · **TRAN** = 2010–2018 transition ·
**NEW** = 2019+ standardized `JDFN` template.

| Filename | Era | Role family | Why included |
|---|---|---|---|
| `19670501_00006855Assistant_to_assoc_dean.doc` | OLD | Assistant | Oldest doc (1967); legacy `.doc`; NAME OF EMPLOYEE field |
| `19820219_00001211Systems_consultantII.doc` | OLD | Analyst/Systems | 1982 header variant, INCUMBENT field |
| `19820219_00001219Systems_consultantII.doc` | OLD | Analyst/Systems | Near-dup: same date, adjacent position ID |
| `19901029_00000063Laboratory_coordinator.doc` | OLD | Coordinator | 1990 old-era hard-parse `.doc` |
| `19900123_00030838Network_manager.doc` | OLD | Manager | 1990 old-era manager role |
| `19910121_00030393Administrative_assistant.doc` | OLD | Assistant | 1991 old-era |
| `19910419_00030834Director_pub_relation_HC.doc` | OLD | Director | 1991 old-era director |
| `19920428_00001201Clerk.doc` | OLD | Clerk | 1992 old-era clerical family |
| `19920430_00000536Secretary.doc` | OLD | Secretary | 1992 old-era clerical family |
| `19920501_00000981Technician_May1992.doc` | OLD | Technician | 1992 old-era technical family |
| `19920608_00006375Programmer_analyst.doc` | OLD | Analyst | 1992 old-era analyst |
| `19930630_00031708Traffic_park_enf_officer.doc` | OLD | Officer | 1993 old-era officer family |
| `19970808_00030273Dept_resource_specialist.doc` | OLD | Specialist | 1997 old-era specialist family |
| `19980120_00000293_Asst_to_Director,_Rec_Services.doc` | OLD | Assistant | Dup-cluster head (unique hash) |
| `19980120_00000293_Asst_to_Director,_Rec_Services.doc.doc` | OLD | Assistant | Exact-content dup, stacked `.doc.doc` |
| `19980120_00000293_Assistant_to_the_Director,_Rec_Services.doc.doc` | OLD | Assistant | Exact-content dup w/ title variant |
| `19980120_19980120_00000293_Asst_to_Director,_Rec_Services.rtf` | OLD | Assistant | Same position as `.rtf`, doubled-date name |
| `20040301_06983.txt` | OLD | (id-only) | `.txt` stub, id-only filename edge case |
| `20060327_Sec_to_Director_REM.txt` | OLD | Secretary | Tiny `.txt` oddity, no position ID |
| `20000601_00031286_Coord_Prof_Prog_Jun2000.rtf` | OLD | Coordinator | `.rtf` format, antiword-parseable |
| `20060716_Manager,_Acad___Admin.Serv,Public_Policy.doc.doc.doc` | OLD | Manager | Triple-stacked `.doc.doc.doc` accidental dup |
| `19920507_30411_PC.tif` | OLD | (scanned) | HARD: scanned image, needs OCR |
| `20060224_00000328_Manager,_A_183C39.serv` | OLD | Manager | HARD: non-standard `.serv` extension |
| `20090701_00102072_Clerk,_Gr_4.docm` | TRAN | Clerk | Macro-enabled `.docm`, only one in corpus |
| `20120827_Temp._Pos.__112172,_Faculty_of_Education,_Aug._24,_2012.dot` | TRAN | (template) | `.dot` Word template, free-form name |
| `20100515_00001604_JDFN_APSA_20100515.docx` | TRAN | APSA | Earliest `JDFN` new-template naming (2010) |
| `20110115_00100214_Admin_Coord.docx` | TRAN | Coordinator | Transition docx, pre-`JDFN` naming |
| `20110110_00001878_Dir_Ugrad_Programs.docx` | TRAN | Director | Transition docx, director family |
| `20140728_00115642_Program_Director.docx` | TRAN | Program Director | 2014 transition, name-field PII present |
| `20160104_00118493_Assoc_Dir_Venture_Cnctn.docx` | TRAN | Assoc Director | 2016 transition, no PII field (cleaner) |
| `20170310_00116227_Video_Journalist.docx` | TRAN | Specialist | 2017 transition, non-traditional role |
| `20181014_00124799_Research_Project_Manager.docx` | TRAN | Project Manager | Near-dup chain head: pre-`JDFN` version of pos `00124799` |
| `20200214_00124799_JDFN_APSA_20200219.docx` | NEW | Project Manager | Near-dup chain: `JDFN` re-save of pos `00124799` |
| `20201109_00124799,_00124800,_00124801_JDFN_APSA_20201109.docx` | NEW | Project Manager | Near-dup chain: multi-ID bundle file |
| `20240717_00124799^00136606_JDFN_APSA_20241223.docx` | NEW | Project Manager | Near-dup chain: caret-joined-ID later version |
| `20191128_00119031_JDFN_APSA_20191128.docx` | NEW | APSA | New-era APSA, 2019 mass-rollout year |
| `20200924_00001090_JDFN_APSA_20200101.docx` | NEW | APSA | New-era APSA, 2020 |
| `20210901_00131366_JDFN_APSA_20210910.docx` | NEW | APSA | New-era APSA, 2021 |
| `20231024_00112766_JDFN_APSA_20231220.docx` | NEW | APSA | New-era APSA, 2023 |
| `20260702_00138231_JDFN_APSA_20260615.docx` | NEW | APSA | Newest APSA (2026), confirmed territorial-ack footer |
| `20231027_00125977_JDFN_APEX_20231030.docx` | NEW | APEX/Executive | New-era executive template |
| `20260616_00134720_APEX_JDFN_20260616.docx` | NEW | APEX/Executive | APEX with token-order variant (`APEX_JDFN`) |
| `20210804_00129695_JDFN_CUPE_20210804.docx` | NEW | CUPE/Union | Distinct union template line |
| `20260626_00138568_JDFN_CUPE_20260624.docx` | NEW | CUPE/Union | CUPE variant lacking territorial-ack footer (template variance) |

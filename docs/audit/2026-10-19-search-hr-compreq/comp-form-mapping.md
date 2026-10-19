# Compensation Requisition Form (CRF) from the JD Bank: field mapping, coverage, import and render

Research date 2026-10-19. Read-only: no repo files edited, no DB writes. Every DB query below ran inside
`BEGIN READ ONLY; … ROLLBACK;` via `docker exec -i jd-bank-postgres-1 psql -U app -d harness`.
Current parser in the Bank: `jd_segmenter_v8` (`core/src/jd_core/parser/segmenter.py:96`).

---

## 0. Headline

* The CRF is a real AcroForm (115 fields, 4 pages, no XFA, no `NeedAppearances`). It fills cleanly with
  pypdf. Our fixture is byte-identical to the live SFU copy (sha256 `e3616b92…c6e790`, footer "Updated
  September 17, 2024").
* The form asks for very little JD content. It is mostly a **position-level transaction** form (position
  #, supervisor, accounting string, FTE, incumbents, approvals). Of about 60 meaningful inputs, the Bank can
  prefill about **8 directly** and **suggest about 10 more** (checkbox choices derived from a diff or
  rule). The rest has to come from an HRIS position export or from the requester.
* The Bank's best asset is the **position ↔ JD file link**. The archive filename is
  `<HRIS As-Of Date YYYYMMDD>_<HRIS "User File Name">`. Proven on the screenshot record: As-Of 2020/06/01 +
  `61,_30785,_208,_975_JDFN_APSA_20211117.docx` → Bank file `20200601_61,_30785,_208,_975_JDFN_APSA_20211117.docx`.
  That is an exact join key for an HRIS import, and it is better than the position number.
* The **existing grade importer cannot work as written**. `core/scripts/import_grades.py` joins on
  `canonical_jds.content.position_number`, which is set on **1 of 2,503** current roles, so it would
  match almost nothing. Roles are clusters of positions (an average of 2.4 positions each, up to 73).
  HRIS data has to land at the **position/source-document level** and roll up to roles.
* ⚠ **Recorded scope decision.** A "compensation requisition workflow" is marked **Explicitly OUT**
  in `docs/decisions/copilot-sfu-gap-triage-2026-08-13.md` (#6) and in
  `docs/archive/BUILD-RECORD-phases-0-9-A-G.md:817`, because the HRIS is the system of record for the
  pay transaction. A **prefilled PDF that the requester finishes and emails to Compensation@sfu.ca** is
  arguably not that workflow: there is no request store and no status. The owner should still say so
  explicitly, because the request touches a recorded decision under `docs/decisions/**`.

---

## 1. The form itself

**Source.** https://www.sfu.ca/content/dam/sfu/human-resources/forms-documents/Compensation/CompensationRequisitionForm_2024.pdf
is linked from the "Job descriptions and re-evaluation requests" page under "All Employee Groups". The
same section links the Reorganization Approval Form and the Impact Spreadsheet (both are already in
`fixtures/hr/`). The page gives no version number, so watch the filename and the "Updated" footer.
PDF metadata: title `CompensationRequisitionForm_20230801`, made with Acrobat PDFMaker 20, modified
2024-09-17.

**AcroForm facts** (pypdf + PyMuPDF in a throwaway `python:3.11-slim` container):
- 115 terminal fields: 64 checkboxes (`/Yes`/`/Off`), 4 combo boxes, 3 signature fields (`/Sig`), about 43 text fields, and 1 reset button.
- **No field has the Required flag set.** "Required" appears only in the printed headings: TYPE OF REQUEST, GENERAL INFORMATION, and APPROVALS/SIGNATURES.
- **Field names are unreliable.** Many are `Text NN` / `Check Box NN`, and several are actively misleading. The mapping below was made by drawing every widget rectangle on a render and reading the labels next to it. Renders and the per-widget label dump are in this folder: `out/p1.png`–`p3.png` and `widget_labels.txt`.
- Combo options:
  - `Dropdown77` (Position Type): `Continuing, Full-Time | Continuing, Part-Time | Temporary, Full-Time | Temporary, Part-Time | " "`
  - `Dropdown51` (Request initiated by): `University | Employee | " "`
  - `Employee Group` (VPA section): `" " | APSA | APEX`. CUPE and Poly are not options.
  - `Dropdown10` (VPA FT/PT): `" " | Full-Time | Part-Time`

**Misleading names to remember (the actual label is in brackets):**
`Supervisor Position Title` [**Contact** Name & Position Title] · `Accounting String if cost split…`
[Sec A **direct reports: list all position #**] · `OBJECT 4` [**PROJECT** p1] · `undefined` [OBJECT p1] ·
`undefined_2` [FUND p1] · `undefined_3` [DEPT p1] · `Text60` [PROGRAM p1] · `No If no specify…Row1`
[Sec B **list all position #** (based-off)] · `SECTION C Editorial Changes` [Sec C **incumbent names**] ·
`SECTION D Additional Duties TEMPORARY` [Sec D **incumbent names**] · `SUBMISSION CHECKLIST` [Sec D
**Effective Date**] · `Text18` / `OBJECT 4_2` / `FUND 2` / `please include secondary…` / `Text17` = p3
PROJECT / OBJECT / FUND / **DEPT** / PROGRAM.

**Instructions (p4, condensed).**
1. Tick the request type. CUPE re-evaluations do **not** use a CRF; they use the Position Re-evaluation Request Form instead.
2. Fill General Information from the **current** position.
3. Fill only the sections that match the ticked request types.
4. Get the approvals that request type needs:
   - VP approval for new continuing positions.
   - The VPA section for Faculties/VPA units creating continuing APSA/APEX positions at grade 9 or above.
   - Dean/AVP approval for new CUPE positions, and for APSA positions at grade 8 or below.
5. Email the form to Compensation@sfu.ca, cc'ing the Strategic Business Partner and the HR Specialist.

Request-type definitions:
- **A (new position):** includes clones. A clone is "same department, same grade, same org structure, same supervisor". It needs no evaluation.
- **B (re-evaluation):** a significant change.
- **C (editorial):** no change of level.
- **D (temporary additional duties).**
- **E (other system changes):** title, reporting, hours, de/reactivation, temp→continuing, department, accounting string.

---

## 2. What the Bank holds: measured coverage

### 2a. Per source document (parsed_jds at v8, n = 14,522 parsed of 14,565 files)
```sql
WITH cur AS (SELECT * FROM parsed_jds WHERE parser_version='jd_segmenter_v8')
SELECT count(*) n,
 count(*) FILTER (WHERE nullif(parsed->>'position_number','') IS NOT NULL) pos_no,
 count(*) FILTER (WHERE nullif(parsed->>'department','') IS NOT NULL) dept,
 count(*) FILTER (WHERE parsed->>'employee_group' IS NOT NULL) grp,
 count(*) FILTER (WHERE jsonb_typeof(parsed->'classification')='object') classif,
 count(*) FILTER (WHERE nullif(parsed->>'title','') IS NOT NULL AND parsed->>'title'<>'Untitled Position') title,
 count(*) FILTER (WHERE nullif(parsed->>'position_summary','') IS NOT NULL) summary,
 count(*) FILTER (WHERE jsonb_array_length(coalesce(parsed->'qualifications','[]'))>0) quals
FROM cur;
```
| field | docs | % |
|---|---:|---:|
| title (not "Untitled Position") | 13,277 | 91.4 |
| position_number (header text) | 10,505 | 72.3 |
| employee_group | 9,988 | 68.8 (apsa 5,121 · cupe 4,300 · apex 420 · poly 76 · excluded 71) |
| department (**name only**) | 9,444 | 65.0 |
| structured grade (`classification`) | 3,004 | 20.7 (cupe 2,277 · apsa 687 · apex 34 · unknown 6; all `source=parsed`) |
| position_summary | 14,219 | 97.9 |
| ≥1 qualification | 9,385 | 64.6 |

- Department **ID** (the 4-digit code, e.g. 4510): only **7** docs carry a 4-digit token in `department`. The Bank effectively has **no** Dept IDs.
- Header `position_number` is noisy. Only 5,601 values are the clean `0NNNNNNN` shape. Examples of junk: `Lab Coordinator`, `Various`, `702`.

### 2b. Per position (the CRF's unit): latest file per padded filename id
Filename ids use the rulebook pattern `segmentation.position_id_pattern` = `(?<![0-9])(0[0-9]{7})(?![0-9])`.
- **13,572 / 14,565** files carry at least one padded id.
- **5,541** distinct positions. This matches HR-114's "`all`" figure, which validates the probe.
- 662 files name 2 or more positions.
- 993 files carry no padded id. 508 of those lead with an unpadded id (e.g. the screenshot's `61,_30785,…`).
```sql
WITH pos AS (SELECT m[1] pid, s.id sid, s.filename, substring(s.filename from '^(\d{8})') d
  FROM source_documents s, regexp_matches(s.filename,'(?<![0-9])(0[0-9]{7})(?![0-9])','g') m),
latest AS (SELECT DISTINCT ON (pid) * FROM pos ORDER BY pid, d DESC, filename DESC),
j AS (SELECT l.pid, l.filename, p.parsed FROM latest l LEFT JOIN parsed_jds p
      ON p.source_document_id=l.sid AND p.parser_version='jd_segmenter_v8')
SELECT count(*), count(*) FILTER (WHERE …title…), … FROM j;
```
| per position (n = 5,541) | count | % |
|---|---:|---:|
| latest file parsed | 5,526 | 99.7 |
| latest file is JDFN-era / dated 2019+ | 3,077 / 3,520 | 55.5 / 63.5 |
| title | 5,182 | 93.5 |
| summary | 5,439 | 98.2 |
| employee group | 4,339 | 78.3 |
| department name | 2,745 | **49.5** |
| grade (structured) | 1,077 | **19.4** |
| header pos# = filename id | 2,257 | 40.7 (another 1,373 differ only by padding or bundling; 787 are truly different or junk) |

Spot checks against the screenshots:
- `00000075`: Bank `cupe` grade **8**, dept "VPR Animal Care". HRIS shows CU00 / 008 / dept 6110. ✔ grade.
- `00000061`: Bank title "Manager, Academic & Administrative Services", `apsa`, **no dept, no grade**. HRIS shows 4510 Biological Sciences, AP00 / 010.

These confirm the 2026-08-01 audit: the APSA grade is not in the JD; it lives in the HRIS.

### 2c. Per harmonized role (current version per cluster, n = 2,503: 2,499 DRAFT + 5 PUBLISHED rows)
```sql
WITH cur AS (SELECT DISTINCT ON (cluster_id) * FROM canonical_jds ORDER BY cluster_id, version DESC)
SELECT count(*), count(*) FILTER (WHERE nullif(content->>'position_number','') IS NOT NULL), …
```
| field | roles |
|---|---:|
| `content.position_number` | **1** |
| department | 1,746 (69.8%) |
| employee_group | 1,739 (69.5%) |
| structured `classification` | **0** (the key exists on 2,500 roles but is null) |
| legacy free-string `grade` | 540, with mixed formats `08`, `010`, `7` |
| roles with ≥1 member file carrying a padded position id | **2,450** (97.9%) |
| roles whose members map to exactly one position | 1,275 |
| average / max positions per role | 2.4 / 73 |

**Neo4j** holds no metadata (embeddings and provenance only), per the audit §5. It is not relevant here.

---

## 3. Field-by-field mapping

Legend for the **Source** column:
- **BANK**: prefill directly.
- **DERIVE**: Bank-computed suggestion that a human confirms.
- **HRIS**: needs the position export.
- **USER**: the requester types it.
- **NEVER**: must not be prefilled.

| CRF field (PDF field name) | Source | Where it lives / how | Coverage (measured) |
|---|---|---|---|
| Type of request A–E (`Check Box71/75/72/76/73`) | DERIVE | Builder action: compose new or clone → A; edit of an existing position's JD → B or C (human picks; the B/C line is an HR judgement); title/department change → also E | n/a |
| Position # (`Position  NA if new`) | BANK (+HRIS) | filename ids via `jd_bank/baseline/facets.py::file_facets().position_ids`; `N/A` for new | 5,541 positions; 2,450/2,503 roles reach ≥1 |
| Position Title (`Position Title`) | BANK / HRIS | `parsed.title` (archive) or the draft's title; HRIS `Title` is authoritative for the *current* title | 93.5% of positions |
| Department (`Department`) | BANK name / HRIS id | `parsed.department` (name only) | 49.5% of positions; Dept ID ≈ 0 |
| Supervisor Name & Title (`Supervisor Name`) | USER / HRIS | `relationships.supervisory` has a reports-to *title* in prose. Names are normalized out by the rulebook, so the Bank never holds them | title only, unmeasured |
| Email (`Email`), Contact name/title (`Supervisor Position Title`!), Contact email (`Email_2`) | USER (or CAS session) | requester identity could come from the CAS SSO session (memory says it is integrated; check what attributes it exposes) | — |
| Reason / additional info (`Reason for request…`) | USER, DERIVE assist | could seed from `jd_core/bank/version_diff.py` (summary of changes vs the archive JD) | — |
| A: clone? (`CB64/65`), position # to clone (`Text68`) | DERIVE | Builder "clone" (`cloned_from_cluster_id`) → candidate positions of that role. But an HR "clone" is position-level (same dept, grade and supervisor), so the user picks one | — |
| A: based on existing? (`CB66/67`), list all position # (`Text70`) | BANK | member positions of the source role: role → `source_document_ids` → filename ids | 97.9% of roles |
| A: Position Type (`Dropdown77`) | HRIS (part) + USER | HRIS `Reg/Temp` gives Continuing vs Temporary (needs the mapping Regular→Continuing ratified); FT/PT is not in the screenshots | — |
| A: Bi-weekly hours (`Hours`) | USER / HRIS | not in the Bank or the screenshots | — |
| A: Anticipated grade (`Proposed Grade`) | HRIS for clones; otherwise USER | for a clone, grade is equal by definition, so take the HRIS grade. Otherwise show the source positions' grades as **reference only**; do not propose a grade (that is the evaluator's job; see ADR-007 on Hay) | Bank-parsed grade 19.4% of positions; HRIS ~100% |
| A: Supervisor Position # (`Text61`) | HRIS / USER | the screenshots show no reports-to field; we would need `Reports To` in the export | — |
| A: direct reports Y/N (`CB62/63`) + list (`Accounting String…`!) | USER (DERIVE Y/N) | `relationships.supervisory` / duties could suggest Y/N; position #s need an HRIS reports-to | — |
| Accounting string ×5 (p1 `OBJECT 4`, `undefined`, `undefined_2`, `undefined_3`, `Text60`) | USER (+HRIS DEPT) | Finance data, not in the Bank. DEPT(4) could prefill from HRIS dept code; the form says it must match the Dept ID | — |
| Checklist: org chart (`CB78`) | USER | — | — |
| Checklist: JD in Word (`CB79`) | BANK | `jd_export/render.py::render_sfu_docx` produces the .docx; tick when attached | every draft |
| Checklist: VPA approval (`CB80`) | DERIVE (rule) | continuing AND group ∈ {APSA, APEX} AND grade ≥ 9. **This is a decision parameter: it must be YAML and registered** | needs a grade |
| B: occupied? (`CB53/54`), incumbent names (`Text52`) | NEVER from the Bank / HRIS-USER | the Bank strips incumbent names by design. An HRIS incumbent feed is a FIPPA question | — |
| B: incumbent already performing? (`CB57/58`), effective date (`Text86`) | USER | — | — |
| B: based on existing? (`CB55/56`), list (`No If no specify…Row1`!) | BANK | as for Section A | 97.9% of roles |
| B: anticipated grade (`Text50`) | USER | — | — |
| B: initiated by (`Dropdown51`) | USER | University / Employee | — |
| B: what changed (`CB41` duties, `CB42` direct reports, `CB43` min ed/exp, `CB44` reporting, `CB45` title, `CB46` other) | DERIVE | section-level diff of the draft vs the position's current archive JD (`version_diff.py`): duties changed / qualifications (education/experience) changed / supervisory changed / title changed | — |
| B: affects other positions? (`CB47/48`) + list (`Text49`) | DERIVE | **other position ids bundled in the same JD file** (662 multi-position files, e.g. 61/30785/208/975 share one JD) | 662 files |
| B checklist (`CB2`, `CB81`, `CB82`) | USER; `CB81` needs a **tracked-changes .docx**, which `render.py` does **not** produce today (a gap) | — | — |
| C: occupied / incumbents (`CB36/37`, `SECTION C Editorial Changes`!), impact (`CB38/39`), effective date (`Text87`) | USER / NEVER | as for Section B | — |
| C: what changed (`CB27` duties, `CB28` format/template, `CB29` quals, `CB30` other, `CB31` title, `CB32` dept name, `CB33` tools) | DERIVE | same diff. "Transposing to new template" is true whenever the archive source is pre-JDFN (era ≠ new/current via `file_facets().era`) | — |
| C checklist (`CB34/35`) | USER / tracked-changes gap | — | — |
| D: incumbents (`SECTION D…`!), effective (`SUBMISSION CHECKLIST`!), end (`End Date`), checklist `CB84/85` | USER | — | — |
| E: new title (`Effective Date`, `Text19`) | DERIVE | draft title ≠ HRIS title → prefill the new title; the date is USER | — |
| E: reporting / hours / de-re-activate / temp→cont / dept change (`Effective Date_2…_6`, `New Supervisor Position`, `New Biweekly Hours`, `CB25/26`, `New Dept ID`) | USER | — | — |
| E: new accounting string (p3 `Text18`, `OBJECT 4_2`, `FUND 2`, `please include…`, `Text17`) | USER | — | — |
| Approver role boxes (`CB11` VP, `CB16` Dean/AVP, `CB13` Mgr/Dir, `CB14` budget, `CB15` incumbent) | DERIVE (rule) | from request type + group + grade, per the p4 table. **Must be YAML and registered** | — |
| Print names / dates (`Print Name`, `Date`, `_2`) | USER | — | — |
| Signatures (`Signature`, `Signature_2`, `Signature3`) | **NEVER** | leave the `/Sig` fields empty so they can be signed in Acrobat | — |
| VPA: Employee Group (`Employee Group`) | BANK / HRIS | `employee_group`, or HRIS Sal Plan (AP00 → APSA per screenshot; the APEX plan code is unknown). Only APSA/APEX are valid | 78.3% of positions |
| VPA: FT/PT (`Dropdown10`), Proposed Grade (`Text8`), Annual cost (`Text9`), strategic plan (`Text4`), funding (`Text5`), Provost signature/name/date | USER (grade: as for Section A) | cost needs a salary scale the Bank does not hold | — |

**Tally:**
- BANK (direct): position #, title, department name, the based-on position lists (A and B), the JD .docx checkbox, and the VPA employee group.
- DERIVE: request type, the B and C change checkboxes, other affected positions, the VPA checkbox, the approver boxes, and the E new title.
- Everything else is HRIS or USER.

---

## 4. Getting HRIS position metadata into the Bank

**What exists.**
- Nothing in either repo.
  - `C:\repos\hris` (read-only) has no position export, only `SFU_JDs` and six JDFN docx in `fixtures/jobs`.
  - The only HRIS-import code is the grade scaffold: `core/src/jd_bank/grade_import.py` (CSV `position_number,scheme,grade` → `JobClassification(source="hris")`) plus `core/scripts/import_grades.py`.
- The scaffold is blocked on paper (an HR export plus a FIPPA review). It is also **structurally wrong**: it writes onto `canonical_jds` matched by `content.position_number`, which is set on 1 of 2,503 roles.
- The JD Database Cheat Sheet confirms the HRIS is PeopleSoft ("search for job descriptions database").

**Proposed import shape.** One row per (position, JD attachment row). That is a PeopleSoft query over position data plus the JD attachment record behind the screenshot:

```
position_number, position_descr, dept_id, dept_descr, job_code, sal_admin_plan, grade, grade_descr,
union_code, union_descr, reg_temp, position_status, jd_as_of_date, jd_title, under_reeval (Y/N),
docx_user_file_name, pdf_user_file_name, [reports_to_position, fte, std_hours]   ← ask for these too
```

The last three are optional, but they fill the CRF's supervisor position #, FT/PT and bi-weekly hours.

**Join (strongest first).**
1. **Exact filename:** `to_char(jd_as_of_date,'YYYYMMDD') || '_' || docx_user_file_name = source_documents.filename`. This is proven on the screenshot row, and it attaches HRIS metadata to the **exact archive file** (version), including the 508 unpadded-id files the rulebook pattern cannot read. The archive also holds padded re-uploads of the same JD (e.g. `20200601_00000061,_00030785,…`), so expect several Bank files per HRIS row. Match on `sha256` duplicates to fan out.
2. **Position id:** `position_number` ∈ `file_facets().position_ids` (13,572 files, 5,541 positions).
3. **Header fallback:** parsed `position_number` (noisy; padding normalization needed).

**Storage.** A new table, for example `hris_positions` (one row per position + as-of, with `imported_at`, `source_file`, a row hash and `source="hris"`), plus a link table to `source_documents`. Roles read it through their member documents. Do **not** write it into `canonical_jds.content`. A role is many positions, and putting HRIS data in the content blob repeats the importer's bug. This needs an alembic migration under `core/` (PR plus `make gates` and `make smoke`). Any mapping knobs must be rulebook YAML plus a register entry `open`: Sal Plan → group (AP00→APSA, CU00→CUPE), union code → group (200 APSA, 300 CUPE), Reg/Temp → Continuing/Temporary, and the VPA grade-9 threshold.

**Governance blockers.** Grade is compensation data, so the FIPPA review already noted in grade_import.py applies. The HR register already carries "whether an HRIS position→grade import is in scope". An incumbent-name feed would be a separate and harder FIPPA question; the CRF can live without it (USER input).

---

## 5. Rendering

| Option | Verdict |
|---|---|
| **Fill SFU's own AcroForm with pypdf** (recommended) | Output is the exact official form that Compensation expects, and it stays editable so the requester finishes it and signs in Acrobat. pypdf is BSD-3 and pure Python. **It is NOT in the api image today** (checked: no pypdf / pdfplumber / reportlab / fitz / pikepdf), so add `pypdf` to `core/requirements.txt`. Use `writer.set_need_appearances_writer(True)` and/or `auto_regenerate`, because the form has no `NeedAppearances`. Checkbox on-state is `/Yes`; combo values must equal the option strings exactly. Never touch `/Sig`. Keep a name→meaning map in YAML (the field names are misleading, §1). |
| Regenerate a lookalike PDF (reportlab/WeasyPrint) | Not recommended. It reproduces SFU's form and branding, drifts when SFU revises it, and is not the official document. |
| HTML "pre-fill sheet" only | Fallback if SFU objects to programmatic filling. It loses the "attach to email" convenience. |

**Template handling.** Vendor the PDF as a template asset with a pinned sha256. Write a test that fails if SFU's field set changes (compare `get_fields()` names against the YAML map). Watch the live URL for revisions, since the "2024" filename may be reused.

**Offline (Directive #1).**
- `deploy/bundle.ps1` ships images via `docker save`, so pypdf baked into the api image travels offline. The template PDF travels with the repo copy.
- No network or LLM is needed to fill. Rendering is pure, which also satisfies the validator-as-oracle rule.
- `make smoke` would need extending to render a CRF for a live role/position and assert that the filled fields read back. Otherwise smoke does not cover it (Directive #1 item 5).

**Discoverability (Directive #1 item 3).** A "Download Compensation Requisition Form" action on the draft/review page and on the library position view.

---

## 6. Open questions for the owner

1. **Scope.** The CRF workflow is recorded as Explicitly OUT (triage 2026-08-13 #6). Is "prefill and download, no request store" acceptable as a narrower re-scope? It needs a decisions PR either way.
2. **Unit of the form.** A CRF is for one position, while Bank roles are many-position clusters. For an edit or re-evaluation, does the user pick the position (from the role's member positions) in the Builder? For a new position, is "based on positions: <role members>" what HR wants listed, or only the one closest position?
3. **HRIS export.** Who can produce the PeopleSoft query in §4, and can it include reports-to, FTE and standard hours? Is the FIPPA review for grade (already flagged) going to be started? Is the incumbent name explicitly out?
4. **Grade on the form.** Should the Bank ever prefill "Anticipated/Proposed Grade" outside true clones, or only show reference grades? (Grade proposals risk reading as an evaluation; see ADR-007.)
5. **Tracked changes.** Sections B and C require "Track Changes on existing job description in Word format". `render_sfu_docx` emits a clean .docx only. Is a tracked-changes export (archive JD → draft) in scope?
6. **Rule ratification.** The VPA ≥ grade 9 trigger, the approver-by-request-type table, and the Sal Plan/union code → group mapping are all rules from the p4 table. Register them as `open` (the standing rule)?
7. **CUPE.** The form tells CUPE re-evaluations to use a different form (the Position Re-evaluation Request Form), and the VPA group dropdown only allows APSA/APEX. Should CUPE positions get the CRF only for A/C/D/E, and is the CUPE re-evaluation form a follow-on?

## Artifacts in this folder
`pdf_dump.txt` (full field + text dump) · `widget_labels.txt` (label next to each widget) ·
`out/p1-3.png` (field overlay renders) · `q1.sql`–`q7.sql` (every query, read-only) · `dl/` (live CRF +
JD Database Cheat Sheet downloads, untrusted).

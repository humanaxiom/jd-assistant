# Archive Census — SFU Job Description Historical Corpus

**Phase 0 · Task 0.2 ("Archive census")**
**Date:** 2026-07-10
**Source (READ-ONLY):** `C:\repos\hris\fixtures\SFU_JDs`
**Author:** JD Bank ingestion team

> **Privacy note (FIPPA):** This report contains **no personal information**. Legacy
> templates carry incumbent-name fields; wherever names appear in source documents they
> are reported here only as an **incidence rate**, never quoted.

---

## 1. Method

- The archive is a single flat directory (no subfolders) of 14,565 files.
- **File inventory** was taken by extension and by the `YYYYMMDD` date prefix encoded in
  each filename.
- **Text extraction** was performed with two toolchains already present on the machine
  (nothing was installed):
  - **Legacy binary `.doc` (Word 97-2003):** `antiword` (found at `/mingw64/bin/antiword`).
  - **`.docx` / `.docm` (OOXML):** `unzip -p <file> word/document.xml` piped through a
    tag-stripping `sed`. For territorial-acknowledgement detection the **full** `word/*.xml`
    set was scanned, because that footer text lives in `word/footer*.xml`, not in
    `document.xml`.
- **Era classification** combined (a) filename signals and (b) heading conventions read
  from documents actually opened, cross-referenced against
  `docs/rulebook/sfu-jd-standards.txt` (Part 2 template structure; Part 8 transposition).
- **Parse-ability** was measured on a deterministic 41-file spread (every ~355th file
  across the sorted listing) plus targeted opens of the oldest and oddest items.
- **Duplicate analysis** used exact-content `md5sum` grouping and normalized position-ID
  repetition.

### Environment / tooling caveats
- **No usable Python.** The `python`/`py` commands resolve to the Microsoft Store stub; no
  interpreter, `python-docx`, `textract`, `pywin32`, or `olefile` are available.
- **No LibreOffice** (`soffice` not on PATH) and **no standalone MS Office** — Office is
  present only as an AppX package (not COM-automatable from this shell without extra setup).
- Consequently the production ingestion pipeline should standardize on **antiword (or a
  LibreOffice `--headless --convert-to txt` step) for `.doc`** and **native OOXML unzip for
  `.docx`** rather than assuming a Python document stack.

---

## 2. Total document count

**14,565 files.**

---

## 3. File counts by format / extension

| Extension | Count | Notes |
|---|---:|---|
| `.docx` | 9,947 | OOXML; trivially parseable (zip + XML) |
| `.doc`  | 4,577 | Legacy binary Word 97-2003; needs antiword/LibreOffice |
| `.txt`  | 24 | Plain text; a few are id-only stubs |
| `.rtf`  | 11 | Rich Text; antiword handles most |
| `.dot`  | 3 | Word template files (incl. `.doc.dot` stacked) |
| `.docm` | 1 | Macro-enabled OOXML |
| `.serv` | 1 | Non-standard extension (opaque) |
| `.tif`  | 1 | Scanned image — **not text-extractable without OCR** |
| **Total** | **14,565** | |

### Naming pattern
The dominant convention is:

```
YYYYMMDD_<positionID>_<role-slug>.<ext>
```

- **`YYYYMMDD`** — a leading date (creation/effective/revision), spanning **1967 → 2026**.
- **`<positionID>`** — usually an 8-digit zero-padded PeopleSoft-style number
  (e.g. `00124799`); older items use shorter unpadded IDs; some filenames omit it.
- **`<role-slug>`** — a free-form human title fragment (`Network_manager`, `Clerk`,
  `Assoc_Dir_Venture_Cnctn`).
- **New-era addition (2019+):** a standardized token block
  `..._JDFN_<GROUP>_<revdate>` where `<GROUP>` ∈ {`APSA`, `APEX`, `CUPE`, `POLY`} and
  `<revdate>` is a second `YYYYMMDD`. `JDFN` = the current job-description form/template.
- **Irregularities:** stacked extensions (`...doc.doc`, `...doc.doc.doc`), doubled date
  prefixes (`YYYYMMDD_YYYYMMDD_...`), multi-ID bundles
  (`00124799,_00124800,_00124801`), and caret-joined IDs (`00124799^00136606`).

Filename-token counts of interest: **`JDFN` = 4,637 files**; group tags **APSA 3,442 /
CUPE 779 / APEX 345 / POLY 49** (tags overlap since some appear in body-less filenames).

---

## 4. Template-era distribution

Two independent signals agree that the corpus splits into an **OLD** paper-derived template
and a **NEW** standardized template, with a multi-year **transition band**.

### 4a. By format vs. year (proxy signal)

`.doc` dominates before 2010; `.docx` takes over from 2010 and is essentially the only
format by 2015.

| Era band | Years | Predominant format | Approx. share of corpus |
|---|---|---|---|
| OLD | 1967–2009 | `.doc` | ~30% (files skew heavily post-2000) |
| TRANSITION | 2010–2018 | `.docx`, pre-`JDFN` naming | ~30% |
| NEW | 2019–2026 | `.docx`, `JDFN_<GROUP>` naming | ~40% (2019 alone = 1,913 files) |

`JDFN`-named files by year confirm the new template's rollout: 1 (2010) → 20 (2017) →
25 (2018) → **332 (2019) → 1,131 (2020) → 1,024 (2021)** → steady ~450/yr thereafter.

### 4b. By heading convention (documents actually opened)

Reading a spread of files against the rulebook, three header regimes were observed:

- **OLD-era markers** (pre-~2006, mostly `.doc`):
  `SIMON FRASER UNIVERSITY / ADMINISTRATIVE & PROFESSIONAL STAFF / POSITION DESCRIPTION`,
  letter-prefixed sections (`A. IDENTIFICATION`, `B. POSITION SUMMARY`,
  `C. DUTIES & RESPONSIBILITIES`), and — critically — a **`NAME OF EMPLOYEE:` field** and
  a "reports to (Name)" line. A slightly older 1982 variant uses
  `JOB DESCRIPTION / Administrative and Professional Staff Positions` with `INCUMBENT:` and
  `DEPARTMENT:` fields.
- **NEW-era markers** (per rulebook Part 2 and confirmed in recent APSA `.docx`):
  `ABOUT SIMON FRASER UNIVERSITY`, the **territorial acknowledgement** ("respectfully
  acknowledges the … Musqueam …") and **"committed to the principle of Employment Equity"**
  footer, un-lettered section names, and an employee-group identification field. The
  territorial-acknowledgement footer was present in 5 of 6 recent APSA docs sampled.
- **AMBIGUOUS/hybrid:** the large 2008–2021 middle band frequently shows neither a strong
  OLD banner nor the full NEW footer in the body XML — content transposed into the new
  structure but without the boilerplate, or with boilerplate only in footers. **Era for
  this band is most reliably inferred from the `JDFN` filename token, not body headings.**

> **Template-variance caveat:** `CUPE` (unionized staff) documents are a distinct template
> line and do **not** always carry the APSA/APEX territorial-acknowledgement footer, so
> absence of that footer is not by itself proof of OLD era.

---

## 5. Parse-ability sample

Deterministic 41-file spread across all years/formats, plus targeted opens:

| Format | Attempted | Clean text | Garbled / empty | Tool |
|---|---:|---:|---:|---|
| `.doc` (legacy binary) | ~18 | 18 | 0 | antiword |
| `.docx` / `.docm` | ~22 | 22 | 0 | unzip + XML strip |
| `.txt` | opened | clean (some are 1-line stubs) | 0 | direct read |
| `.rtf` | opened | clean | 0 | antiword |
| `.tif` | 1 | **0 (image, no text layer)** | 1 | needs OCR |
| `.serv` | 1 | opaque / not a known doc format | 1 | none |

**Every `.doc` and `.docx` in the sample yielded clean, well-structured text (0 failures).**
antiword handled even the 1967 document faithfully (identification block, section
headers, and body all intact). Character yields ranged ~2,000 (short old stubs) to ~33,000
(long transition-era files) with no truncation or mojibake observed. The only genuinely
non-parseable items are the **`.tif` (scanned image)** and the **`.serv`** oddity — 2 files
total across the whole corpus.

**Bottom line:** the archive is **~99.99% text-recoverable** with the offline toolchain
already on the box; only 2 files need special handling (1 OCR, 1 manual triage).

---

## 6. PII incidence — RATE ONLY

- **Name-bearing field present in ~56% of parsed sample docs** (23 of 41): a populated or
  labelled `NAME OF EMPLOYEE:` / `INCUMBENT:` field, or a "reports to (Name)" line.
- Incidence is **strongly era-dependent**: near-universal in OLD-era `.doc` (the template
  literally includes an employee-name field and named reporting line), and **markedly lower
  in NEW-era `JDFN` docs**, which follow the rulebook's "evaluate jobs, not people"
  principle and drop the incumbent field.
- **Estimated header-PII incidence by band:** OLD ~80–90%, TRANSITION ~40–60%, NEW ~10–20%.
- **Implication for ingestion:** a **name-redaction / PII-scrubbing pass is mandatory before
  any document text is embedded or surfaced by retrieval**, and should be
  prioritized on the OLD/TRANSITION `.doc`/early-`.docx` bands.

*(No names are reproduced anywhere in this report or its working artifacts.)*

---

## 7. Duplicate rate

Two complementary methods:

### 7a. Exact-content duplicates (`md5sum`)
- **1,037 hash groups** contain more than one file; **3,009 files** participate in an
  exact-duplicate group.
- ⇒ roughly **~1,970 files (~13.5% of the corpus) are pure redundant byte-for-byte copies.**
- Cause is visible in filenames: stacked-extension re-saves (`...doc.doc`, `...doc.doc.doc`
  — 32 such files) and re-titled saves of an identical file.

### 7b. Position-ID revision sets (near-duplicates)
- 13,596 files carry a recognizable zero-padded position ID; **5,436 distinct IDs.**
- **3,101 position IDs have ≥2 dated versions**; summed, **~8,160 files are a non-first
  version of an already-seen position** (~56% of ID-bearing files).
- Example: position `00124799` (Research Project Manager) has **16 dated versions**
  2018→2024, including pre-JDFN `.docx`, JDFN re-saves, and multi-ID bundle files.

### Method / limits
- Exact-dup detection is authoritative (content hash). **Near-dup counting is filename-ID
  based**, so it (i) misses true near-dupes whose ID token was dropped or reformatted, and
  (ii) may over-count where one file legitimately bundles several positions
  (`00124799,_00124800,_00124801`). Body-level fuzzy/shingle dedup was **not** performed
  and is recommended before final golden-set curation.

**Summary rate:** ~13.5% exact redundancy on top of a heavy revision-chain structure where
the majority of ID-bearing files are re-versions of an existing position.

---

## 8. Key caveats

1. **Era for the 2008–2021 middle band is inferred primarily from the `JDFN` filename
   token**, because body headings are inconsistent there; treat as a heuristic, not ground
   truth.
2. **Footers matter:** territorial-acknowledgement / equity boilerplate lives in
   `word/footer*.xml`; a `document.xml`-only extractor will under-report NEW-era markers.
3. **CUPE template line differs** from APSA/APEX; don't classify it OLD merely for lacking
   the acknowledgement footer.
4. **No Python / Office / LibreOffice** on this machine — the pipeline must not assume them;
   antiword + OOXML-unzip is the validated offline path.
5. **2 files (1 `.tif`, 1 `.serv`) are not text-parseable** and need OCR / manual triage.
6. **PII is present and must be scrubbed pre-embedding**; figures here are incidence rates
   from a sample, not a full-corpus scan.

---

## 9. Golden sample

A stratified 44-file golden sample was selected from this census — see
`fixtures/golden/README.md` for the manifest, provenance, and the **PII handling decision
(pending human sign-off)**. It spans 1967→2026, 10+ role families, OLD/TRANSITION/NEW eras,
easy (`.docx`, `.txt`, `.rtf`) and hard (`.doc`, `.tif`, `.serv`, `.docm`, `.dot`) formats,
one exact-duplicate cluster (Rec Services, pos `00000293`) and one long revision/near-dup
chain (pos `00124799`).

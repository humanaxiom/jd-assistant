# JD Builder vs SFU HR published guidance: gap analysis (CUPE + APSA/APEX/Poly)

Date: 2026-10-19. Read-only research; no repo file changed.
Repo state read: `main` @ `2e3e6dc`.
Downloads: not retained in the repo (re-download from the URLs in §1).

Notation: **yes** = the Builder collects it and renders it faithfully. **partial** = it is collected, but in a different shape from the form, or it is lost on export. **no** = not collected.
File:line references are relative to `C:\repos\JD-Assistant\core\src\`.

---

## 1. Source inventory

All sources are linked from https://www.sfu.ca/human-resources/forms-resources/job-descriptions-and-re-evaluation-requests.html (fetched 2026-10-19), unless noted otherwise.
`B` = `https://www.sfu.ca/content/dam/sfu/human-resources/forms-documents`.

| # | Document | URL | Version / date (from file metadata or text) | Governs |
|---|---|---|---|---|
| S1 | Job description landing page | (above) | live | Index only. No prose on how to submit, timelines or who signs. Contact: 778 782 3237 |
| S2 | APSA_APEX_POLY JD Template | `B/Compensation/APSA_APEX_POLY_JD%20Template_20240530.docx` | modified 2024-05-30. **Byte-identical to `fixtures/hr/…(1).docx`** (sha256 1818649a…) | APSA/APEX/Poly. New and re-eval |
| S3 | Job Description Toolkit | `B/Compensation/JobDescriptionToolkit.pdf` | ModDate 2024-03-13. **Identical to the fixture** | APSA/Excluded. New and re-eval |
| S4 | Job Description Database Cheat Sheet | `B/Compensation/Job%20Description%20Cheatsheet_20201020.pdf` | 2020-10-23. Same text as Toolkit p.11 | APSA/Excluded |
| S5 | Hay Job Evaluation Method | `B/Compensation/Hay%20Job%20Evaluation%20Method.pdf` | 2021-03-18. **Identical to the fixture** | APSA/Excluded evaluation process |
| S6 | Job Evaluation Infographic | `B/Compensation/Job%20Evaluation%20Infographic.pdf` | 2021-04-27. **Identical to the fixture** | APSA/Excluded ("applies currently only to APSA and Excluded") |
| S7 | Job Analysis Questionnaire (JAQ) | `B/Compensation/Job%20Analysis%20Questionnaire%20form.pdf` | 2021-03-04 | APSA/Excluded: leader intake, "basis for job evaluation" |
| S8 | Compensation Requisition Form (CRF) | `B/Compensation/CompensationRequisitionForm_2024.pdf` | "Updated September 17, 2024". **Same size as the fixture**; hash not compared | APSA/APEX/Excluded new, re-eval, editorial and other changes. **CUPE re-evals use S12 instead** |
| S9 | Reorganization Approval Form v2 | `B/Compensation/Reorganization%20Approval%20Form_v2.pdf` | "Last updated: August 17, 2020". **Identical to the fixture** | Reorgs (all groups) |
| S10 | Reorganization Impact Spreadsheet | `B/Compensation/Reorganization%20Impact%20Spreadsheet.xlsx` | **Identical to the fixture** | Reorgs |
| S11 | About CUPE JD Forms (page) | https://www.sfu.ca/human-resources/forms-resources/about-cupe-jd-forms.html | live | CUPE. "Only the Job Questionnaire Answer Sheet should be submitted for evaluation with a completed Part I: Job Description form." |
| S12 | Position Re-evaluation Request Form (CUPE only) | `B/Compensation/ReevalRequestFormCUPE.pdf` | created 2017-09-18, mod 2020-03-05 | CUPE re-eval |
| S13 | WJQ Custom Part I: Job Description Template | `B/job-evaluation/CUPE_Job_Description_Template_Sept2013.docx` | **filename says Sept 2013, but the file was modified 2026-05-12** (author A. Shon). No copy in `fixtures/hr/` | CUPE. New and re-eval |
| S14 | CUPE JD Writing Guide & Glossary of JD Verbs | `B/Compensation/CUPE%20WJQ%20JD%20Writing%20Guide%20%26%20Glossary%20of%20JD%20Verbs.pdf` | March 2011 (14 pp) | CUPE Part I, section by section |
| S15 | WJQ Part II Job Questionnaire Booklet & Answer Sheet | `B/Compensation/CUPE%20WJQ%20Job%20Questionnaire%20Booklet%20and%20Answer%20Sheet%20May%202010.pdf` | Revised May 2010 | CUPE Part II (58 questions) |
| S16 | Helpful Hints Part II | `B/Compensation/CUPE-WJQ-Helpful-Hints-Job-Questionnaire-Guide.pdf` | dated Nov 5 1992 (PDF from 2000) | CUPE Part II |
| S17 | Part II Answer Sheet (DOCX) | `B/Compensation/CUPE%20Job%20Questionnaire%20Answer%20Sheet%20Form.docx` | 2011-03-23 ("Reformatted February 2007") | CUPE Part II plus its sign-off |
| S18 | Part II Answer Sheet (fillable PDF) | `B/Compensation/CUPE%20Job%20Questionnaire%20Answer%20Sheet%20Form%20FILLABLE%20Feb%2021%202007.pdf` | 2007 | Same as S17 |
| S19 | Use of Pre-classified JDs (CUPE) | https://www.sfu.ca/human-resources/managers-supervisors/pre-classified-job-descriptions/use-of-jd-cupe.html | live | CUPE clone path |
| S20 | Pre-classified Admin job family + sample | `…/office-technical/job-family-admin.html`. Sample read: `B/job-descriptions/CUPE_job_descriptions/CUPE_Sample_JobDescription_DepartmentSecretary(Secretary_grade6_Dec2024).doc` | Dec 2024 (10 samples, grades 4–8) | CUPE clone path. Shows a filled-in current form |
| S21 | Temporary Job Standards | `…/office-technical/temporary.html` | live | CUPE temp positions under 3 months |
| S22 | CUPE 3338 Collective Agreement | `B/agreements/CUPECACURRENT.pdf` (via collective-agreements page) | term Apr 1 2022 – Mar 31 2025, file 2024-05-08 | Art. 15 (JDs), Art. 17 (re-evaluation) |
| S23 | Job Posting Requisition | `B/Recruitment_Onboarding/Job_Posting_Requisition.pdf` | "Updated 9/2026" | Downstream posting. Shows what is not part of the JD |
| S24 | People Action Requisition page/PDF | https://www.sfu.ca/human-resources/forms-resources/people-action-requisitions.html, `B/forms/Revised_PAR_2025-08-01.pdf` | 2025-08-01 | CUPE pre-classified use requires a PAR (S19) |

**Could not read, so nothing below relies on them:**
- "How to Submit a Job Evaluation Request" (`B/Compensation/How%20to%20submit%20a%20JE%20-%2010Jun2020.pdf`, linked from the JPR page) returned **HTTP 404**.
- The Job Evaluation video page has no transcript.
- The Total Compensation Learning Series (Canvas, self-enrol) needs a login. Note that the repo's `docs/rulebook/sfu-jd-standards.txt` says it was captured from this series.
- Policies AD10.02 / AD10.06 / AD9.02 / AD9.06 (cited by Toolkit p.3 and p.27) were not fetched.
- The office-technical landing page lists no JDs itself. The Admin family page does.

**Owner-supplied context (not official guidance):** `fixtures/hr/JD-Meta1.png` and `JD-Meta2.png` are PeopleSoft screenshots. They show the system-of-record fields Position, Department, Job Code, Sal Plan, Grade, Union Code, Reg/Temp, Status, As-Of Date, "Under Re-evaluation" and a "Profile Challenger PDF" slot (Profile Challenger is the CUPE Part II scoring output; S22 17.09). `links.txt` is a YouTube link.

**Newer than our fixtures?**
- Every fixture in `fixtures/hr/` is the current live version: hashes match for S2, S3, S5, S6, S9 and S10, and S8 matches by size.
- **The CUPE material is not in `fixtures/hr/` at all.** The live CUPE Part I template (S13) was revised **2026-05-12**. The pre-classified samples (S20) date from Dec 2024.

**Discrepancies inside HR's own sources (for HR to resolve):**
- **About SFU text.** The template S2 (2024-05-30) reads: "We are a leading research university, advancing an inclusive and sustainable future. Our purpose – the essence of SFU – is to create and connect knowledge, learning and community for deeper understanding and meaningful impact. / We are committed to fostering excellence, innovation, belonging and community in all that we do." The Toolkit S3 (p.5) still quotes "We are Canada's engaged university…". The repo's `boilerplate.yaml` carries the **Toolkit (older) text**.
- **Territorial acknowledgement.** The template S2 carries the full orthography ("xʷməθkʷəy̓əm (Musqueam), Sḵwx̱wú7mesh Úxwumixw (Squamish), səlilwətaɬ (Tsleil-Waututh), q̓íc̓əy̓ (Katzie), kʷikʷəƛ̓əm (Kwikwetlem), Qayqayt, Kwantlen, Semiahmoo and Tsawwassen…"). The Toolkit p.10 has a short "Coast Salish peoples" version. `boilerplate.yaml` has an ASCII transliteration ("xwmethkweyem…"). This is direct evidence for HR-105 and for the CLAUDE.md open flag.
- **Percentage time per duty.** Neither S2 nor S3 asks for % allocations. The `(60%)` rule and "MUST total 100%" in `sfu-jd-standards.txt` (lines 128 and 131) trace to the Learning Series, which could not be checked here. HR-023 is already registered `open`.
- **CUPE major-function frequency.** The template S13 lists (D)(W)(M)(S). The writing guide S14 p.3 adds "Annual". The template puts annual work in Minor Functions.
- **"Twelve slots."** The **current** CUPE template S13 (rev. 2026-05) has **no numbered duty slots**: two blank paragraphs under section 3 and eleven under section 4. The "twelve slots" in `composer_questions_wjq_v1.yaml:87` and HR-202 describe older archive versions, not the form HR hands out today. The Dec-2024 sample S20 has **11 major + 3 minor = 14** functions.

---

## 2a. CUPE (WJQ Custom), field by field

Answer contract: `jd_bank/composer/wjq_answers.py:63-102`. Questions: `jd_bank/composer/data/composer_questions_wjq_v1.yaml`. Assembler: `jd_bank/composer/wjq_assemble.py`. Export: `jd_export/render.py:126-151`, the same renderer as JDFN.

HR's governing rule here is **S22 Art. 15.04: "The standard job description form cannot be revised without mutual agreement between the University and the Union."** Art. 15.01(b) adds: "Job descriptions must follow a standard format and use standard terminology."

| # | HR-required element | HR source | Builder? | Notes |
|---|---|---|---|---|
| 1a | Department Name | S13 §1, S14 §1 | **yes** `wjq_answers.py:65` | |
| 1b | Position Number(s), plural: one JD can cover several positions | S13 §1. S14 §1: "number of positions covered" | **partial** `:66` | A single string. Not rendered on export (`render.py` prints title only) |
| 1c | Current Position Classification | S13 §1, S17, S12 | **no** | Distinct from "Classification & Grade Approved". The re-eval form needs it too |
| 1d | Department Position Title | S13 §1 | **yes** `:64` | |
| 1e | Evaluating Supervisor's Title | S13 §1. S17 also asks the supervisor's **name** | **no** | |
| 1f | Date Completed | S13 §1 | **no** | |
| 1g | "Part 1 is being completed by: ☐ Employee ☐ Evaluating Supervisor" | S13 §1 | **no** | Matters for re-eval routing (S22 17.03) |
| 1h | HR-only box: Classification & Grade Approved / Effective Date / Approved by / Next Review | S13 §1. S14: "A staff member of the human resources department will indicate approval" | **inverted** `:70`, question `yaml:60-68` | The Builder asks the **author** for "the approved classification and grade". On the form that box is "FOR USE BY HUMAN RESOURCES". At most the author should give the *current* classification (1c) or a *suggested* one (S22 17.03(b)(vi)) |
| 2 | Position Summary: "three or four sentences" | S13 §2, S14 §2 | **yes** `:73` | The hint ("Purpose first, then scope") is fine. The 3–4 sentence length is not prompted. The CUPE form has no 100–150-word rule |
| 3 | Major Functions, each with a **frequency code (D)/(W)/(M)/(S)**, in frequency order, with what + how + why | S13 §3. S14 §3 steps 1–3 | **partial** `:78`; `answers.py:20-31` | `DutyAnswer` has **no frequency field**; it has a `%` allocation instead, which is a JDFN concept. The hint (`yaml:86-88`) tells CUPE authors to "give the percentage of time". `SFUDuty.frequency` already exists (`jd_core/models/parsed_jd.py:83`, HR-142) and the parser fills it, so authored and parsed CUPE JDs are not actually the same shape |
| 4 | Minor Functions: annual or periodic. The **last line must be the catch-all** "Performs other duties and responsibilities consistent with the job description and classification on request." | S13 §4. S14 §4 | **partial** `:82` | (i) Merged into `duties` with majors and **capped at 12 in total** (`wjq_assemble.py:178-179`, `_MAX_DUTIES=12` at `jd_core/parser/segmenter.py:111`). HR's own Dec-2024 sample has 14, so its last two minor functions, **including the catch-all**, would be silently dropped. (ii) The major/minor split is lost on assembly and clone (`wjq_assemble.py:259-264`). (iii) The catch-all is not prompted. (iv) The hint ("incidental") differs from HR's "annually and periodically" |
| 5 | Level of Independence: **pick ONE of 4 defined levels**. The 4th needs "examples of project work" | S13 §5. S15 E.1 Q1–2 | **partial** `:96` | Free text. The hint ("Who assigns and reviews the work…") is about supervision received, which S16 says E.1 "does not measure" |
| 6 | Training Exercised: **check each of 5 defined levels** | S13 §6. S15 E.2 Q3–4 | **partial** `:97` | Free text |
| 7 | Direction Exercised: **check each of 5 lettered levels (A–E)** | S13 §7. S15 E.3 Q5–6 | **partial** `:98` | Free text |
| 8 | Internal and External Contacts: a table of **Type of Contact / Duration (<1h, 1–2h, >2h) / Frequency (occasional, frequent, continuous)** | S13 §8. S14 §8 gives the definitions | **partial** `:85-86` | Plain lines split internal/external. No duration or frequency |
| 9 | Impact of Errors: **Common Errors** and **Uncommon Errors** (two lists), plus their impact | S13 §9. S14 §9 | **partial** `:99` | One free-text box. The hint asks "how it is normally caught" (S16 lists "likelihood of errors being caught by others"), so that part is fine |
| 10 | Effort: a table of **Type of Effort (auditory / visual / perceptual / physical-dexterity, incl. sitting, standing etc.) / Duration / Frequency** | S13 §10. S14 §10. Feeds S15 F.7, F.8 and G.10 Mobility | **partial** `:100` | Free text. The hint does not name the four effort types or the duration/frequency scale |
| 11a | Working Conditions: **Location / hours per week** (e.g. "General office 35 / 35 hours") | S13 §11 | **partial** `:101` | One free-text box covers 11a–c |
| 11b | **Uncomfortable conditions / frequency** | S13 §11 | **partial** | |
| 11c | **Potential health or safety hazards / frequency** | S13 §11. Feeds S15 G.9 Q25–32 | **partial** | The hint lists "shift or on-call patterns, travel between sites", which HR puts under **Occupational Requirements (13)**, not Working Conditions |
| 12 | Continuing Education: **check each of 5 defined levels** | S13 §12. S15 H.12 Q40–41 | **partial** `:102` | Free text. The hint ("Certifications to maintain…") does not match HR's levels ("learning new university/department procedures…") |
| 13a | Formal education: highest level required | S13 §13 | **yes** `:89` | |
| 13b | Certification or program of study required | S13 §13 | **partial** | No field. Authors would put it in education lines |
| 13c | Years of minimum experience (a **number**) | S13 §13 | **partial** `:90` | Free text |
| 13d | **Equivalency: ☐ acceptable / ☐ not acceptable because… (rationale required)** | S13 §13. S14 §13: "If you make this choice, you must describe the rationale" | **no** | `SFU-QUAL-EQUIVALENT` is a JDFN-style text check, not this choice |
| 13e | Occupational Skills (measurable; give a level where needed) | S13 §13. S14 §13 | **yes / partial** `:92` | The Builder also asks Knowledge (`:91`) and Abilities (`:93`) with APSA modifier vocabularies. Those are Toolkit (APSA) concepts, not CUPE form fields; the Dec-2024 sample puts everything under "Occupational Skills" |
| 13f | **Occupational Requirement(s)**: non-skill items such as shifts/on-call, travel, driver's licence, lifting over 10 kg | S13 §13. S14 §13 | **no** | No field. Feeds S15 G.10 Mobility and F.8 |
| 14 | Approval and Review: Evaluating Supervisor name/signature/date ("accurately reflects the requirements"); Employee name/signature/date ("read and understand") | S13 §14. S14 §14 | **no, by design** (`yaml:29-32`) | The Bank's own review trail is not the CUPE sign-off. See §3 |
| — | Form identity: banner "SIMON FRASER UNIVERSITY & C.U.P.E., LOCAL 3338 / WEIGHTED JOB QUESTIONNAIRE (WJQ) CUSTOM / PART 1: JOB DESCRIPTION", 14 numbered sections, no SFU boilerplate | S13. S22 15.04 | **no on export** | `render_sfu_docx` is form-blind. A CUPE draft exports in **JDFN layout** ("Duties and Responsibilities", "Relationships", "Additional Contextual Information" holding sections 5–12 as text). It **always appends the territorial acknowledgement and employment-equity footer** (`render.py:114-123, 147`), which the CUPE form does not carry. This contradicts the assembler's own reasoning (`wjq_assemble.py:21-27`) and HR-201 |
| — | **Part II: Job Questionnaire Answer Sheet (58 answers: E1–6, F7–8, G9–11, H12–19; primary and secondary per question)** | S11. S14 p.1: "**Both parts must be completed before positions can be evaluated and classified.**" S15 step 3. S12 Step 2. S22 17.03(b)(iv) | **no** | No Part II anywhere. S15 p.2 maps each Part I section to the questions it supports, so Part I prose can pre-fill Part II but cannot replace it |
| — | Part II sign-off: supervisor approves or notes changes; employee review; the employee gets a copy for a union/employee re-eval | S17 | **no** | |
| — | Writing rules: acronyms spelled out; no Canadian/SFU-specific requirements unless essential; gender- and culture-neutral; minimum requirements | S14 p.2 "Getting started" | **partial** | Acronym and coded-term rules exist in the rulebook. **No rule against Canadian- or SFU-specific requirements** was found in `rule_catalog.yaml` |
| — | Verb glossary (S14 appendix, ~170 verbs with definitions) | S14 pp.8–14 | **partial** | `action_verbs.yaml` exists. Not checked whether it holds the CUPE glossary |

## 2b. APSA / APEX / Poly (JDFN), field by field

Answer contract: `jd_bank/composer/answers.py:67-105`. Questions: `data/composer_questions_v1.yaml`. Assembler: `assemble.py`. Export: `jd_export/render.py`.

| # | HR-required element | HR source | Builder? | Notes |
|---|---|---|---|---|
| A1 | Header "Position #:" | S2 page header | **no** | `ComposerAnswers` has no `position_number`, though the model has one (`parsed_jd.py:120`) and the WJQ form asks it |
| A2 | Identification section ("title, and position identification number… Ensure each section is completed. Use the job titling guide") | S3 p.5 | **partial** | Title `answers.py:74`, department `:75`, group `:76`, grade `:81`. **No supervisor's title** (the rulebook's own Part 11.1 list, quoted in `composer_questions_v1.yaml:9-12`, asks for it; S7 asks "Position # of Supervisor"). No effective/revised dates. Export prints title only |
| A3 | Job title per the Titling Guide (S3 pp.18–19) | S3 | **partial** | `titles.yaml` / `SFU-GATE-SENIOR-TITLE` / restricted-title rules exist. Not checked against the Titling Guide table |
| A4 | About SFU (pre-populated) | S2. S3 p.5 | **partial** `:103` | The flag is set, but (i) **the export never renders an About SFU block** (`render.py:126-151`) and (ii) `boilerplate.yaml` holds the **older Toolkit text**, not the 2024 template text (HR-104) |
| A5 | Position Summary, 100–150 words: purpose, primary duties, "Spell out acronyms" | S2. S3 p.5 checklist | **yes** `:83` | Rules SFU-STRUCT-SUMMARY-TOO-SHORT/LONG and AUTH-SUMMARY-* exist |
| A6 | Duties & Responsibilities: 3–5 major responsibilities in descending importance, each "ACTION VERB… WHAT by" followed by **How and why** sub-bullets; no overlap with supervisor or direct reports | S2. S3 pp.5–6 | **partial** `:85`; `DutyAnswer` `answers.py:20-31` | `DutyAnswer` = verb + one statement + %. **No how/why sub-bullets.** `SFUDuty.how_why` exists (`parsed_jd.py:80`) but the Builder cannot fill it, so `SFU-STRUCT-HOW-WHY` can only be met by cramming them into the statement. The % allocation is **not on the 2024 template** (see §1). No overlap check with the supervisor's JD (S3 p.6, S9 pre-submission step 4c) |
| A7 | Impact of Decision Making: 2–3 examples of decisions made without approval; how they are reached; policies followed; effect on results | S2. S3 p.6 | **yes** `:87` | Prompt and hint fit |
| A8 | Problem Solving and Level of Supervision: typical problems, the role's part, independent thinking, known or unknown solutions, guidance received | S2. S7 §4 | **yes** `:89` | The single-line hint is thinner than the template's four prompts |
| A9 | Relationships: Supervisory (nature + titles supervised, as an approximate range); Internal (positions/departments + purpose); External (forums/organizations + purpose) | S2. S3 p.7 | **yes** `:91-93` | Standard header inserted (HR-056) |
| A10 | Qualifications A: education + credentials + years + equivalency wording; degree names a discipline "or related" | S3 pp.7–8 | **yes** `:96-97` | Rules QUAL-EQUIVALENT and QUAL-DEGREE-DISCIPLINE exist |
| A11 | B Knowledge (excellent / working / none) | S3 p.8 | **yes** `:98` | |
| A12 | C Skills (basic / intermediate / advanced / expert) | S3 p.8 | **yes** `:99` | |
| A13 | D Abilities (observable) | S3 pp.8–9 | **yes** `:100` | |
| A14 | **E Security credentials (if applicable)**: the criminal record check sentence when the BC criteria are met | S3 p.9: "The qualifications on the job description **must include** … E. Security credentials (if applicable)" | **no** | The model has `kind="security"` (`parsed_jd.py:33`), but the Builder has no field and **drops it on clone** (`assemble.py:176-179`) |
| A15 | No "may include", "assets", "preferences" | S3 p.9 | **yes** | SFU-QUAL-BANNED-PHRASE |
| A16 | Territorial acknowledgement + Employment Equity | S2. S3 pp.9–10 | **partial** | Rendered from `boilerplate.yaml`, whose territorial text is **not** the template's orthography (HR-105, CLAUDE.md open flag). S2 now supplies SFU's official wording |
| A17 | Additional Contextual Information (optional) | S2 | **yes** `:105` | |
| A18 | Format: Times New Roman 10, bold headers | S3 p.4 | **yes** `render.py:46-56` | |
| A19 | "Ensure track changes is on when editing an existing job description" | S3 pp.3, 11. S8 B/C | **no** | The Builder exports a clean `.docx`. `review_diff.html` diffs against the Bank's last approved version, not HR's file |
| A20 | Gender-bias check ("gender-decoder" tool cited) | S3 p.4 | **yes (own lexicon)** | SFU-LANG-CODED |

---

## 3. Process elements beyond the form

| Element | HR source | What HR requires | Builder today |
|---|---|---|---|
| **APSA/Excluded submission package** | S3 p.26, S5 p.3, S8 checklist | Compensation Requisition, Org Chart, "Job Description with Track Changes" in Word, approvals, sent to **compensation@sfu.ca** cc'ing the SBP and HR Specialist | Exports a `.docx` only. No CRF, no org chart, no checklist, no track changes, no routing |
| **CRF data (APSA)** | S8 | Request type (New / Re-eval / Editorial / Additional duties / Other); clone? and the position # cloned; "based off of existing position" #s; position type; bi-weekly hours; anticipated grade; supervisor position #; direct reports #s; accounting string; reason for request; contact | None. The Builder knows the cloned cluster (`answers.py:64`) but cannot express it as "clone of position #". (S8: a clone is "same department, same grade, and organizational structure… does not require a job evaluation") |
| **Re-evaluation specifics (APSA, CRF §B)** | S8 p.2 | Is the position occupied? incumbent name(s); is the incumbent already doing the revised duties (if not, effective date); what changed (Duties / Direct reports / Min. education & years / Reporting / Title / Other); do the changes affect other positions (#s); anticipated grade; initiated by | None. No "new vs re-evaluation vs editorial" mode in the Builder |
| **Editorial-change path (CRF §C)** | S8 p.2 | Minor edits: note "minor edits" and use track changes; Manager approval only | None |
| **What triggers a re-eval vs editorial** | S8 p.4 table. S3 p.23 / S5 p.3 ("more of the same… unlikely to result in a change") | Defined lists | `jd_core/bank/drift.py` has related escalation logic. Its own docstring (l.33-36) says the shipped rulebook has no re-evaluation criteria. **S8 p.4 is that missing official source** |
| **CUPE re-evaluation package** | S12 Step 2. S22 17.03(b) | Signed and dated by the initiator: (i) completed Re-evaluation Request Form; (ii) **existing AND revised** JDs in the standard format; (iii) **summary of substantive differences**; (iv) completed job questionnaire (Part II); (v) comparable positions if appropriate; (vi) **suggested classification**; (vii) funding if University-initiated | None. (ii) and (iii) are partly reachable: the Bank has prior versions and a diff (`review_diff.html`), but nothing produces "existing + revised + summary of differences" as a package |
| **CUPE re-eval approvals and routing** | S12 Step 3–4. S22 17.03(a) | Employee-initiated: supervisor approval, **forwarded to HR within 20 working days**, and **a copy to CUPE 3338 the same day**. University-initiated: Dean or Senior Administrative Director. HR may interview or visit the site. CUPE re-evals do **not** use a CRF | None |
| **CUPE timelines** | S22 15.02(b), 17.04–17.05, 17.09 | 30 working days for union/employee review of the revised JD; results within 30 working days; appeal within 30 working days; retro pay to the request date (17.06) | None. A tracker could record the request date, which drives retro pay |
| **CUPE pre-classified (clone) path** | S19, S20 | Use a pre-classified JD with editorial edits only (department, position #, supervisor title) plus a PAR naming the JD, to the HRBP. If responsibilities differ, a position-specific JD **plus a Part II answer sheet** plus a PAR | Cloning exists, but the Builder **does not know HR's 10 pre-classified CUPE JDs** (grades 4–8) or the 3 Temporary Job Standards (S21). It does not say "editorial edits only, so no re-evaluation" and does not produce the PAR note |
| **Org chart** | S3 pp.19–23 ("one level above and below"). S8, S9 | Required attachment | None. The Builder knows the supervisory text only |
| **Reorganization** | S9, S10, S3 pp.24–25 | Business case; current and future org charts; impact spreadsheet (current vs future: position #, title, grade, FT/PT, union, manager pos #, impact, accounting string); existing + updated JDs with track changes; VPA section for APSA/APEX ≥ 9; "requests with missing documents will not be placed in queue" | None (out of scope for one JD, but multi-JD batches are an HR expectation: "submit all of the jobs undergoing change together") |
| **Approvals** | S8 p.3–4 matrix. S9 | New continuing: VP (or Dean/AVP for CUPE and APSA ≤ 8 in VPA units); APSA/APEX ≥ 9: Provost/VPA with projected cost and funding plan; re-eval: Dean or Senior Administrative Director; editorial/temp: Manager/Leader; employee-initiated re-eval: incumbent signs | The Bank's review/approve is an internal HR-reviewer gate (NN #1), not these sign-offs. Correctly not faked |
| **Incumbent involvement** | S3 p.3 ("Where there is an existing incumbent… they should provide feedback… prior to its submission"). S13 §14. S17 | Employee review and signature (CUPE). Incumbent feedback (APSA) | None |
| **Periodic review** | S3 p.4 (APSA: at least every 4 years). S22 15.03 (CUPE: "At least once annually") | Review cadence; "Next Review" box on the CUPE form | None |
| **Posting hand-off** | S23 | The JPR takes "Top Qualifications (3–5)" from the JD and defaults the Role Summary to the JD position summary. The department description lives in the posting, **not the JD** (S3 p.5) | Not in scope. The Builder correctly keeps department info out of the summary (rules exist) |

---

## 4. Prioritised gap list

**P1** = HR would reject or return the submission without it. **P2** = HR expects it. **P3** = nice to have.
⚖ = a judgment call HR should rule on. Per the repo rule, put it in YAML and register it `open` in `decision_register.yaml`; do not assume.

### CUPE (WJQ)

| P | Gap | Evidence | Implementation idea |
|---|---|---|---|
| **P1** | **The export is not the CUPE standard form.** It uses JDFN layout and appends the territorial/EE footer | S22 15.01(b), 15.04. S13. `render.py` | A WJQ renderer keyed on `template_of(jd)` that reproduces S13's 14 numbered sections, banner and identification table (no SFU boilerplate). Better: fill HR's own S13 `.docx` so the layout is HR's. Add a smoke check that a CUPE export carries "WEIGHTED JOB QUESTIONNAIRE" and no territorial footer |
| **P1** | **No Part II Job Questionnaire answer sheet (58 answers)** | S14 p.1 "Both parts must be completed". S11. S12. S22 17.03(b)(iv) | A Part II step: 58 closed questions, primary and secondary, A–H letters, rendered onto S17. ⚖ Any **auto-suggestion** of answers from Part I text is a scoring-adjacent default: register it `open` and show it as a suggestion only |
| **P1** | **Duties over 12 are silently dropped, including the mandatory catch-all minor function** | `wjq_assemble.py:178-179`. HR sample S20 has 14. S14 §4 | Stop truncating authored WJQ input. Keep majors and minors as separate lists on the draft, or raise the authored cap. ⚖ HR-202 (count) is already `open`. Add the S20 sample as a regression fixture |
| **P1** | **No frequency (D/W/M/S) per major function; % allocation asked instead** | S13 §3. S14 §3. `yaml:86-88`. `SFUDuty.frequency` exists | Add `frequency` to the WJQ duty answer (a select driven by `wjq.frequency_markers`) and render "(D)". Drop the % prompt from the WJQ flow. ⚖ HR-142 is `open` ("Annual" appears in S14 but not in S13) |
| **P1** | **Checkbox sections (5, 6, 7, 12) are free text, not HR's defined levels** | S13. S22 15.04. S15 maps them to Part II Q1–6 and Q40–41 | Put the level texts in YAML (verbatim from S13) and render as radio (§5) or checkboxes (§6, 7, 12), plus an optional comment (§5 project examples). Keep `additional_context` as the storage target so the parser round-trip holds |
| **P1** | **Tables for §8 contacts, §10 effort, §11 working conditions (3 sub-tables) are free text without duration/frequency/hours** | S13 §8, §10, §11. S14 definitions | Row editors with duration (<1h, 1–2h, >2h) and frequency (occasional, frequent, continuous) enums from YAML. Hours per week per location. Render as tables |
| **P1** | **Equivalency choice + "not acceptable because" rationale missing; no Occupational Requirements field** | S13 §13. S14 §13 | Add `equivalency_acceptable: bool` + `equivalency_rationale` (required when false), `certification`, `experience_years: int` and `occupational_requirements: list[str]`. Move the "shift/on-call/travel" hint from §11 to here |
| **P1** | **Builder asks the author for the HR-only "approved classification & grade"; missing current classification, evaluating supervisor title, date completed, completed-by** | S13 §1 "FOR USE BY HUMAN RESOURCES". S17 | Rename the author field to "Current classification", and add a "Suggested classification" for re-evals (S22 17.03(b)(vi)). Add supervisor title, date completed, and an Employee/Supervisor radio. Leave the HR box blank on export |
| P1 (re-eval) | **No CUPE re-evaluation package** | S12. S22 17.03(b) | A "Re-evaluation" mode: pick the existing Bank version → author the revision → export existing JD + revised JD + generated "summary of substantive differences" (the Bank's diff) + Part II + a pre-filled S12 page. Show the **20-working-day** and **copy-to-CUPE-same-day** rules on screen. Not automated sending |
| P2 | Impact of Errors as two lists (Common / Uncommon) | S13 §9 | Split the field and render under both sub-headings |
| P2 | Major/minor split lost on clone | `wjq_assemble.py:259-264` | Follows from the P1 above (persist the split) |
| P2 | Hints contradict HR for §5 (supervision received), §11 (shift/travel), §12 (certifications), minor functions ("incidental") | S13. S14. S16 E.1 | Rewrite the hints from S13/S14 wording. The question set is authoring data, not a register entry |
| P2 | Knowledge/Abilities with APSA modifiers on the CUPE form | S13 has only "Occupational Skills" | ⚖ Whether to keep K/S/A for CUPE: render under Occupational Skills on export either way. Register `open` |
| P2 | Pre-classified CUPE JDs (10) and Temporary Job Standards (3) not offered as clone sources; no "editorial-only, no re-eval" guidance | S19, S20, S21 | Ingest the 10 Dec-2024 samples as a marked "HR pre-classified" source. When cloned with editorial-only edits, say "submit with a PAR to your HRBP; no Part II needed" |
| P2 | Missing writing rule: no Canadian- or SFU-specific requirements unless essential | S14 p.2, §13 | New rule in YAML (`applies_to: [wjq, jdfn]`?), ⚖ register `open` |
| P2 | Position Number(s) plural; not on export | S13 §1 | Accept a list and render it |
| P3 | Approval and Review block (§14) and Part II sign-off rendered as **blank** signature lines | S13 §14. S17 | Render empty lines on export. Never pre-fill (NN #1 reasoning stands) |
| P3 | Annual joint review reminder ("Next Review") | S22 15.03 | Optional date field, left blank for HR |
| P3 | Verb glossary parity with S14 | S14 appendix | Diff `action_verbs.yaml` against S14 and register any additions |

### APSA / APEX / Poly (JDFN)

| P | Gap | Evidence | Implementation idea |
|---|---|---|---|
| **P1** | **About SFU block is never rendered on export, and the stored text is the old wording** | S2. S3 p.5. `render.py`. `boilerplate.yaml` | Render `about_sfu` at the top of the export. ⚖ HR-104: S2 (2024-05-30) is newer than S3 (2024-03) and has the new wording. Update the YAML candidate and keep the entry `open` until HR confirms |
| **P1** | **Territorial acknowledgement is not SFU's official orthography** | S2 has the official text | ⚖ HR-105 / CLAUDE.md flag: replace with S2's exact Unicode text and keep it `open` for HR sign-off |
| **P1** | **No Position # field** (template header) | S2 header. S3 p.5 | Add `position_number` to `ComposerAnswers`; the model already has it. Render it in the header |
| **P1** | **No submission package: CRF data, org chart, track changes** | S3 p.26. S5 p.3. S8 | "Submission checklist" step: request type; clone/based-on position #s; supervisor position #; direct reports #s; anticipated grade; reason; reminders for the org chart and track changes; target address compensation@sfu.ca + SBP + HR Specialist. Generate a **pre-filled CRF summary page**, not a filled PDF signature. ⚖ None of this is a rulebook default |
| P1 (re-eval) | **No re-evaluation / editorial mode** (CRF §B, §C) | S8 | A mode switch that captures occupied?, incumbent already doing duties? / effective date, "what changed" checkboxes, other affected positions. Export **existing vs revised with a redline**: a real Word track-changes `.docx`, or at minimum a change summary. Use S8 p.4's re-eval vs editorial table as YAML data, ⚖ registered `open` |
| P2 | **Duties lack How/Why sub-bullets** | S2 "ACTION VERB… WHAT by / How and why". S3 p.6 | Add `how_why: list[str]` to the duty answer (the model already has it) and render as sub-bullets |
| P2 | **% allocation is required by our rules but absent from the 2024 template** | S2/S3 vs `sfu-jd-standards.txt:128,131` | ⚖ HR-023 is already `open`. Add a note that the current published template does not show percentages |
| P2 | Security credentials (criminal record check) missing; dropped on clone | S3 p.9 "must include … E" | A yes/no plus the verbatim sentence from YAML. Stop dropping `security` on clone |
| P2 | No supervisor title (and supervisor position #) | Rulebook Part 11.1. S7 §1. S8 | Add both. Use them for the overlap reminder |
| P2 | No duty-overlap check with the supervisor's or peers' JDs | S3 p.6. S9 step 4c | Where the supervisor's role is in the Bank, run the existing similarity search over duties (advisory only, rank not score, per memory) |
| P3 | Problem Solving hint thinner than the template's four prompts | S2 | Copy S2's prompts into the hint |
| P3 | Periodic review (4-year) and incumbent-feedback prompts | S3 pp.3–4 | Informational text on the export/checklist step |
| P3 | JAQ (S7) as an optional intake path for leaders | S7 | The JAQ maps 1:1 onto Builder sections. A "start from questions" mode could use its prompts |

### Judgment calls to register `open` (not to assume)

1. The About SFU wording (HR-104) and territorial orthography (HR-105): the template and the Toolkit disagree.
2. Whether "Annual" is a valid CUPE frequency (HR-142: S13 vs S14).
3. CUPE duty count / no slot limit on the current template (HR-202).
4. Whether CUPE drafts collect K/S/A with APSA modifiers or only "Occupational Skills".
5. Any Part II answer suggestion derived from Part I text.
6. The re-eval vs editorial classification table (S8 p.4) as data.
7. A new "no Canadian/SFU-specific requirement" rule.
8. Percentage allocations (HR-023), given the 2024 template omits them.

# SFU HR — CUPE 3338 job description sources (vendored)

Official SFU Human Resources documents for the CUPE (WJQ Custom) job description form,
vendored so the CUPE export (`core/src/jd_export/cupe.py`, wording in
`core/src/jd_core/rules/cupe_form.yaml`) can be checked against the exact file it was
transcribed from. **Read-only reference data — do not edit.** If HR publishes a new
version, add it alongside with its own row; do not overwrite.

Retrieved **2026-10-19** from the links on
<https://www.sfu.ca/human-resources/forms-resources/job-descriptions-and-re-evaluation-requests.html>
(inventory: `docs/audit/2026-10-19-search-hr-compreq/hr-gap-analysis.md` §1, rows S13, S14, S20).

`B` = `https://www.sfu.ca/content/dam/sfu/human-resources/forms-documents`

| File | Source URL | What it is | sha256 |
|---|---|---|---|
| `CUPE_Job_Description_Template_Sept2013.docx` | `B/job-evaluation/CUPE_Job_Description_Template_Sept2013.docx` | **S13** — "WJQ Custom Part I: Job Description" template. Filename says Sept 2013; the file was modified **2026-05-12**. The source of every string in `cupe_form.yaml` (HR-237). | `ff9608373f6cfa87547b0ce03842c14704a36420165117c557aae187e68e21b8` |
| `CUPE_WJQ_JD_Writing_Guide_and_Glossary_of_JD_Verbs.pdf` | `B/Compensation/CUPE%20WJQ%20JD%20Writing%20Guide%20%26%20Glossary%20of%20JD%20Verbs.pdf` | **S14** — CUPE JD Writing Guide & Glossary of JD Verbs (March 2011, 14 pp). Section-by-section guidance for Part I. | `941135a886bb1b8b94b339149fb87dbbfebc309f3e572fca3966d49b5c38f89d` |
| `CUPE_Sample_JobDescription_DepartmentSecretary(Secretary_grade6_Dec2024).doc` | `B/job-descriptions/CUPE_job_descriptions/CUPE_Sample_JobDescription_DepartmentSecretary(Secretary_grade6_Dec2024).doc` | **S20** — HR's pre-classified sample (Department Secretary, grade 6, Dec 2024): a filled-in current form (11 major + 3 minor functions). | `a49a262b18d03571555255534fcfc553229792d95fccbeec97896c9388b95159` |

Verify:

```bash
sha256sum fixtures/hr/cupe/*.docx fixtures/hr/cupe/*.pdf fixtures/hr/cupe/*.doc
```

Notes:

- The guide's filename was saved with `and` in place of `&` (the URL's `%26`).
- The gates container mounts only `core/`, so no gate test reads these files. The
  transcription was checked once, 2026-10-19, by extracting every paragraph of the
  template with python-docx (in Docker) and looking up each of the 96 fixed strings the
  export prints (`cupe_form.yaml` plus the 14 canonical `wjq.section_headings`), with
  whitespace collapsed: **96 found, 0 missing** — 82 equal a whole template paragraph,
  14 sit inside one (e.g. the headings, which the template prefixes with their number).
  HR still has to confirm the template is the form in force (HR-237).

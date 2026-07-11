# SFU official reference data (JD Harmonizer source of truth)

Structured extract of SFU's official HR guides, so the code's constants trace to
an authoritative source. **Do not invent values here** — everything is quoted
from one of:

- **JD Toolkit** — `Job Description - Toolkit.pdf` (28 pp; template, writing rules,
  action-verb glossary, gender-neutral lexicon, cloning rule, **Job Titling
  Guide** p18–19, re-evaluation criteria p23–24, reorganization triggers p24).
  Re-verified 2026-07-01 from the live SFU HR file (page numbers below are the
  Toolkit's printed footer numbers = the PDF page + 1).
- **Hay Job Evaluation Method** — `Hay Job Evaluation Method.pdf` (the 4 factors).
- **Organization-structure page** — SFU HR *Compensation Corner → Organization
  Structure* (`.../compensation-corner/organization-structure.html`). Names the
  method **Korn Ferry Hay** (Hay Group is now Korn Ferry), confirms that factor
  points total into job value, that job value is assigned to grade and salary
  structure, and that CUPE 3338 uses a **Point Factor (WJQ Custom)** instrument.
- **JD template** — `APSA_APEX_POLY_JD Template_20240530.pdf` (10 sections).

Scope: **APSA / APEX / POLY** (Korn Ferry Hay-graded) and **CUPE 3338**
(WJQ Custom point-factor). Faculty/others differ again — the Bank labels the
group and never cross-applies one group's instrument.

---

## 1. Hay factors (Hay guide, p2)

Four factors sum to **Total Hay Points → a Grade**:

| Factor | Weighs | Code signal source (our JD sections) |
|---|---|---|
| **Know-How** | practical/technical knowledge; managerial planning/organizing/integrating; communicating & influencing | Qualifications depth + supervisory scope |
| **Problem-Solving** | thinking environment + thinking challenge | Problem Solving & Level of Supervision |
| **Accountability** | freedom to act; nature of impact; area of impact (magnitude) | Impact of Decision Making + supervisory + external |
| **Working Conditions** | **same Hay points for ALL APSA & Excluded** | — (not a differentiator; no signal) |

**Numeric point/grade values are source-gated.** The Organization Structure page
publicly confirms the point-total-to-grade workflow, but code must only display a
numeric grade mapping after approved SFU-controlled values are loaded with source
metadata. `hay_signals` emits advisory low/moderate/high factor signals when no
verified mapping row exists.

**Why Hay (Toolkit p4, verified):** "We evaluate jobs not people" — all names and
identifying info are removed before evaluation (matches our no-PII stance exactly).
"The Hay Method is the only methodology deemed by Canadian courts to be **pay-equity
compliant**," used by 30+ post-secondary institutions plus the provincial & federal
governments. This is *why* the Bank anchors to Hay and to SFU's gender-neutral
lexicon + the gender-decoder tool — the bias checks are pay-equity aligned, not
ad-hoc.

**Grade ↔ salary (org-structure page, verified):** "A job's grade determines where
it lands on the salary scale," and SFU describes points for each Hay factor being
totaled to determine job value, then assigned to grade and salary structure. →
**Iteration 4b (numeric grade band) is source-identified but ingest-gated:** load
approved SFU-controlled point/grade values into `hay_grades` with source URL/file,
effective date, verifier, and mapping version. Title-family mapping is already
delivered.

## 1A. CUPE 3338 WJQ Custom factors (org-structure page)

SFU uses the **Weighted Job Questionnaire Custom (WJQ Custom)** point-factor
system for new and existing CUPE, Local 3338 positions. The Organization
Structure page describes the WJQ workflow as two parts: the job description
(Part I) and the job questionnaire (Part II). The questionnaire is aligned with
the JD and evaluates CUPE positions against four primary factors:

| CUPE/WJQ factor | Source handling |
|---|---|
| **Responsibilities** | CUPE role pack, not Hay Accountability |
| **Effort** | CUPE role pack |
| **Working Conditions** | CUPE role pack; unlike APSA/Excluded Hay handling, this is a CUPE factor |
| **Skill and Knowledge** | CUPE role pack, not Hay Know-How |

WJQ job value is expressed as a total point score, and the job's grade is
determined by where that total point score falls within the CUPE salary scale.
Numeric CUPE point/grade mapping is source-gated: load only approved
SFU-controlled values with source metadata.

## 2. Job Titling Guide — the title-family ladder (Toolkit p18–19)

The "Common SFU Job Titles" table. This is the **title-family taxonomy** for
Iteration 4b (title half). Ordered senior → junior:

| Family | Example titles | Defining criteria |
|---|---|---|
| `vp` | VP Finance & Administration, AVP Human Resources, AVP Students | reports to president / VP level |
| `chief` | Chief Information Officer (CIO) | org's main authority figure, internal + external |
| `director` | Director Marketing & Communications, Director Advancement, Director Finance | reports to a chief / VP / AVP; heads a department |
| `manager` | Manager Communications, Bookstore Supervisor, Manager Residence Life, Associate Director | manages a team (typically hire/terminate/discipline authority) OR manages a process/function |
| `lead` | Lead Athletic Therapist, Service Desk Team Lead | directs a team's duties, often **without** hire/fire authority |
| `associate` | Sales Representative, Communications Associate, Associate Student Recruiter | entry-level; **no** management responsibility |
| `assistant` | Administrative Assistant, Executive Assistant, Board Assistant, Compliance Assistant | provides assistance to the board or an executive |

Purpose (SFU): internal equity, easier comparison, career progression, accurate
job-search matching. SFU is "moving towards more standardized job titling".

**Mapping heuristic (title-agnostic-friendly):** match the normalized canonical
title against these families by keyword; use the supervisory-scope signal to
disambiguate `manager` (has reports) vs `lead` (directs, no hire/fire) vs
`associate`/`assistant` (no reports). Unmatched → `unmapped` (a visible state).
Implemented as `pipeline.bank.classify_title_family`.

**Second dimension — the functional Application Table** (what the title *word*
means: coordinator / analyst / officer / specialist / consultant / …) and the
**comma-format supervisory rule** ("Manager, X" = supervisory) come from the
Learning Series (Part 3.3 / 3.4) —
[sources/sfu-total-comp-learning-series.md §B](sources/sfu-total-comp-learning-series.md).
Implemented as `classify_title_function` + `title_comma_supervisory`.

## 3. Gender-neutral lexicon (Toolkit p17)

SFU's official replace-list (used with http://gender-decoder.katmatfield.com).
The auditor's `_CODED_TERMS` MUST cover all of these. **The Total Compensation
Learning Series (Part 6) extends this with gendered occupational nouns + generic
pronouns** — see
[sources/sfu-total-comp-learning-series.md §A](sources/sfu-total-comp-learning-series.md)
(both now wired into the auditor).

**Masculine words → replace with:**
| Term | Replace with |
|---|---|
| aggressive | rapid, intense, large |
| ambitious | motivated |
| championing | advocating, promoting |
| competitive | tough, intense |
| confidential | restricted |
| dominant | top |
| foreman | foreperson |
| individual | single, lone; or (as "this individual") position, role |
| persistent | tenacious, continuing |

**Feminine words → replace with:**
| Term | Replace with |
|---|---|
| agreement | contract, partnership |
| compassionate | caring |
| honest | candid |
| in-kind | non-monetary |
| supporting | (vague — get clarification / use context) |
| trust | reliable |

Note: `individual`, `honest`, `trust`, `supporting` are common words → the
auditor should flag them but at low severity / with care to limit false
positives. `supporting` is intentionally NOT auto-flagged (SFU says "clarify").

## 4. Cloning rule (Toolkit p10) — validates `clone_verdict`

- **CLONE (no re-evaluation):** identical duties + identical supervisor +
  identical position title + identical qualifications.
- **NEW JOB (needs evaluation):** supervisor / people-leader, APEX, **Grade 8 &
  above**, different title, different department.

## 5. Re-evaluation criteria (Toolkit p26) — official "material change" for DRIFT

**NO re-evaluation (minor):** formatting, new template, department name, leader,
updating tools/systems, adding/removing direct reports (**< 5**), work processes,
existing responsibilities that don't change problem-solving/technical-knowledge/
decision-making level, qualifications that don't change technical knowledge,
using a common JD, job enlargement/enrichment.

**RE-EVALUATION required (major):** re-writing a full JD; adding/removing
responsibilities that **significantly change problem-solving / technical
knowledge / decision-making**; adding/removing direct reports (**> 5**);
adding/removing a team with new/different functions; **qualifications that change
the technical knowledge required**.

→ Drift "major" should key on qualification/technical-knowledge change and
supervisory-scope change, not skill-set delta alone. **Status: implemented.**
`compute_drift` escalates on (a) an education-level or experience-bar change and
(b) a **> 5 direct-reports** change. The supervisory count is parsed from each
side's free-text `relationships.supervisory`; the posting's side comes from its
persisted `SFUJobDescription` (`jobs.description_sfu`), populated by the quality
auditor. When a posting hasn't been audited yet, the supervisory signal is simply
absent and drift falls back to the skill + qualification signals.

**Reorganization triggers (Toolkit p24, verified) — a structural superset of the
above.** A change in org structure "usually results from": creation of a new team
or department; a change in current reporting relationships; **creation of a new
leadership level or job**; creation of multiple new roles within a
department/faculty; **responsibilities that shift significantly between more than
one job**. These are department-level signals (cross-JD), beyond a single posting's
drift — a future "reorg detector" over a department's cluster set could surface
them; for now they inform *why* a supervisory/leadership-level change is "major".
Also verified: "**Minor edits don't need to be evaluated** but the comp team will
update our systems" — reinforces that drift is advisory, never a gate.

## 6. Qualification standards (Toolkit p7–9) — validates auditor v2

- **Minimum, not desired**; state the minimum to perform at the **full working
  level**. Ban "may include / assets / preferences".
- **"or an equivalent combination of education, training and experience"** —
  required path (pay-equity mitigation); the auditor enforces it via
  `SFU-QUAL-EQUIVALENT` (see `pipeline.quality.rule_catalog`).
- **Knowledge modifiers:** excellent / working / (no modifier).
- **Skill modifiers:** basic / intermediate / advanced / expert.
- Degree requirement must name a discipline **+ "or other relevant/related
  discipline"**.

## 7. Governance roles (Toolkit p27; Hay p5) — validates Iteration 3

**Leader** writes the JD → **Compensation** classifies (Hay) + owns the grade →
**HRSBP** is first point of contact + supports job/org design. Policies
**AD10.02 / AD9.02** (writing/submitting), **AD10.6** (APSA eval), **AD9.06**
(Excluded). The Bank prepares + de-duplicates inputs; it never replaces
Compensation's classification.

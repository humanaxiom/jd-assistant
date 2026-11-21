# JD Bank — Operator & User Guide

A practical guide to running and using JD Bank: what the system is, who does what, every
feature, and exactly where **admin rights** (or server/operator access) are required.

🥇 **Live counts are on 📈 Funnel (§5), never in this guide.** `CURRENT.md` in the repo
root indexes where every other fact lives and how to check it.

<!--
MAINTAINER NOTE (not rendered): this Markdown is the source of truth. Run `make guide`
after editing to re-render docs/operator-guide.html (the app serves it at the "📖 Guide"
nav link); `make guide-check` fails if it is stale. Do not hand-edit the HTML.
-->

> **Legend used throughout**
> - **[any]** — any signed-in user
> - **[author]** — a user holding the `author` role
> - **[reviewer]** — a user holding the `reviewer` role
> - **[admin]** 🔑 — a user holding the `admin` role (app-level)
> - **[operator]** 🖥️ — shell + Docker access on the server (deploy/ops), **not** an app
>   role. The app `admin` role and operator access are **different things** (see §3).

---

## Testing JD Bank — start here

**For HR colleagues trying JD Bank before it is in general use.** It takes about 30
minutes. What we most need to hear is where something is **wrong, confusing, or
missing**, not only what is broken.

**Sign in** with your SFU computing ID at the address you were sent. You start as an
**author**: you can search, read, draft and download. You cannot approve or publish
anything.

### Three things to try

1. **Find a job description.** Open 🏦 **JD Bank** and search the way you normally
   would, for example a title ("Program Assistant"), a short form ("AP clerk"), or a
   misspelling, or a **PeopleSoft position number** ("61" or "00000061") to list every
   archive file filed under it and the roles built from them. Open a role, then open one
   of its **source** job descriptions.
   *Ask yourself:* is the role I expected there? Are the job descriptions readable? Can I
   tell two roles with the same title apart?
2. **Download the Compensation Requisition Form.** On a role, choose **📄 Download SFU's
   Compensation Requisition Form**. Pick a request type and a position, check your
   contact line, and download the form. Open it in Acrobat.
   *Ask yourself:* is everything the JD Bank typed in correct? Is anything in the wrong
   box?
3. **Draft a job description in the Builder.** From a role, choose **Start a new JD from
   this harmonized role**. Change it, **Check** it, and **Export .docx**.
   *Ask yourself:* do the check's comments make sense? Does the Word file look like
   SFU's template?

### What is blank or rough on purpose

- **No grade, job code, union or department code, Reg/Temp or hours** on any form. They
  come from PeopleSoft, which is not connected yet. Grades shown on a role are what the
  old files said, for reference only.
- **Position numbers are read from the archive's file names.** For a handful of roles
  the list may be incomplete, and the page says so when it is.
- **The territorial acknowledgement** in exported Word files is spelled without its
  special characters. This is an open decision with HR. Please do not circulate exports
  as final.
- **Search "related by meaning"** ranks closest-first and can include unrelated roles
  when nothing matches your words. The page says when that happens.

### Before you press Submit in the Builder

**Submit** saves your draft into the JD Bank, where other testers can see it. It is
labelled as written in the Builder, and it cannot be deleted. Export and Check save
nothing, so use those freely. Submit only a draft you would really propose.

### Telling us what you found

Use **Report a problem with this page** at the bottom of any page. It opens an email
with the page address already filled in. Say what you expected and what you saw; a
screenshot helps.

---

## 1. What JD Bank is

JD Bank turns SFU's sprawling job-description archive into a clean, governed source of
truth, and helps staff **author new, standards-compliant JDs**. Two halves:

- **The pipeline (back office).** Every JD in the archive is parsed, de-duplicated
  (exact / near-duplicate / role-equivalent), clustered by role, and harmonized into one
  **draft canonical JD** per role — scored against SFU's published standards by a
  deterministic validator. This runs on the server via `make` tasks (§9).
- **The app (front office).** A web UI at **http://localhost:25800** (dev) where people
  **compose** a JD with live compliance feedback, **review & approve** drafts, browse
  **dashboards**, and (admins) **manage users**.

**Two forms, two bars.** SFU writes job descriptions on two different documents, and JD Bank
treats them as different: the **APSA/APEX/Poly** template, and the **CUPE Weighted Job
Questionnaire (WJQ)**. Each is scored against its own rules and its own thresholds — the WJQ
expects 3–12 duties where the APSA form expects 3–5, and carries point-factor blocks (Level
of Independence, Impact of Errors, Effort, Working Conditions) the APSA form has no concept
of. **The two are never averaged into one number**; the system does not compute a blended
score, so nobody can quote one by accident. ⚠ The WJQ bar is **provisional and unratified** —
SFU's JD Toolkit is silent on that form, so every WJQ setting is one we chose (HR Decision 8).

**Five guardrails the whole system is built on** — operators must not work around these:

1. **Nothing auto-publishes.** A canonical JD is a *draft* until a human **reviewer**
   explicitly approves it. Overriding a blocking gate requires a written reason, recorded.
2. **Self-hosted inference only.** All LLM/embedding calls go to SFU-controlled Ollama
   (`aria-gb10-2`). No JD text ever goes to a cloud/vendor API — this is build-enforced.
3. **The validator is the oracle.** Scores/approvability come from the rulebook validator,
   never from the LLM's own claims about its output.
4. **Append-only, tamper-evident audit.** Every review/approve/edit and every login is
   recorded in a hash-chained `audit_log` (alteration or deletion is detectable, §9).
5. **The model may reword; it may not invent.** See below — this is the guardrail an
   author or reviewer is most likely to be asked about, and the one with the most measured
   history behind it.

### What the AI will and will not do to a JD

When JD Bank harmonizes several similar job descriptions into one role, a self-hosted model
rewrites the merged result into cleaner prose. **Its job is rewording, not authorship.** Four
limits, each added after measuring the tool against the real archive — in three of the four
the defect made the *score go up*, which is why none of them was reported by a user:

| The model may not… | Why the limit exists |
|---|---|
| **write a section the sources never wrote** | It was writing *Impact of Decision Making* for roles whose sources said nothing about it — **1,084 drafts carried a section invented from no source at all**, and scored ~18 points higher for it |
| **write the hiring bar** | Education, experience and security clearance come back exactly as derived from the source JDs. A clerical CUPE draft once came back demanding **a PhD in Astrophysics and an Enhanced Reliability clearance**, with nothing flagged |
| **decide how many duties a role has** | Told the form's *minimum* instead of the number actually found, it treated twelve grounded duties as licence to write seven. Over the five largest CUPE roles: **60 duties in, 36 out** — now 48 in, 48 out |
| **drop the point-factor content** | **95.4% of CUPE documents carry** the WJQ point-factor blocks; a rule written for the APSA form was discarding all of it |

If the rewrite fails or is refused, the draft falls back to the **deterministic merge** — the
grounded text assembled from the source documents with no model involved. A draft is never
lost because the model had a bad day; it is only less polished.

**Everything the harmonizer dropped is listed for the reviewer**, per source document and with
a reason (deduplicated, over the duty cap, not merged). Nothing vanishes silently.

---

## 2. Personas & roles

The app has **three roles**, held in any combination (a person can be both reviewer and
admin). Roles are assigned in the **User management** screen (§8, admin-only).

| Persona | Role | Can do |
|---|---|---|
| Hiring manager / recruiter | **author** | Use the Builder: search/clone, author, get LLM assist, export `.docx`, submit a draft to the review queue. Browse dashboards. |
| HR reviewer | **reviewer** | Everything an author can, **plus** open the review queue and **approve / reject / edit / override** drafts (the human-approval gate). |
| System administrator | **admin** 🔑 | Everything above, **plus** manage users (assign roles, enable/disable accounts). |
| System operator / DevOps | **[operator]** 🖥️ | Run the data pipelines, migrations, deploys, and CAS configuration from the server shell. This is **infrastructure access**, not an app role. |

> New users are provisioned as **author** on their first sign-in. Reviewer and admin are
> granted deliberately by an admin. A person can be an app **admin** without server
> **operator** access, and vice-versa.

---

## 3. Access & sign-in

- **URL:** http://localhost:25800 (dev). Typing the bare address takes you to the JD Bank
  library; every UI page lives under `/jd-bank/ui/…`. ⚠ **That is the DEFAULT port** — the
  operator can override it with `JD_API_PORT`, and if the stack was launched with one set,
  the app is on that port instead. `docker compose port api 8000` prints the real one.
- **Sign-in:** SFU **CAS SSO**. Click **Sign in with SFU CAS** on the login page; you are
  redirected to `cas.sfu.ca` and back. Your identity is your SFU computing ID.
- **The nav bar** shows who you are and your primary controls, in menu order: **🏦 JD Bank ·
  🧱 Builder · 📝 My drafts · 📋 Review queue** *(reviewers and admins)* · **📈 Funnel ·
  📊 Dashboards · 📖 Guide · 👤 Users** *(admins only)* · *your name* · **Sign out**.
  **📈 Funnel comes before 📊 Dashboards deliberately** — see §5.
- **The menu only shows what your role can open.** If you do not hold `reviewer` or
  `admin`, the **📋 Review queue** link is not there — the page is not yours to open, and
  offering the link would only produce a refusal. Ask an admin (§8) if you need the role.
- **If something goes wrong**, the app says so in a page rather than a machine error: a
  mistyped address, a page you do not have access to, or a form submitted from a tab that
  has been open a long time (that last one says **reload the page and submit it again** —
  nothing is lost, and nothing was changed).
- **Dev / CI mode** **[operator]** 🖥️: when `CAS_ENABLED=false` (the default off-SFU),
  every request runs as a synthetic **admin** user with no login — so the app is usable
  and testable without reaching CAS. Turn this **off in production** (`CAS_ENABLED=true`).
  🔴 **Never leave it off on a box other people can reach.** The app port is published on
  every network interface, so CAS off makes **everyone on the network an administrator** —
  this happened on 2026-11-19. After any change to `.env`, open a protected page from
  another machine (or `curl` the box's network address's `/jd-bank/ui/queue`) and confirm
  it sends you to sign in.
- **First-admin bootstrap** **[operator]** 🖥️: set `BOOTSTRAP_ADMINS=<your-cas-id>` (comma-
  separated) before first login; those users are granted **admin** automatically on every
  login. This is how the very first administrator is created — after that, admins manage
  everyone else in the UI.

---

## 4. Browsing the archive — the content library  ·  [any] (any signed-in user)

**Where:** 🏦 JD Bank → `/jd-bank/ui/library`. **Who:** any signed-in user. **Admin
required:** no. **Read-only** — nothing on these pages publishes, edits, or overrides a
gate (guardrail #1); a reviewer approves/rejects/edits only from the Review queue (§7).

A reader finds and reads an existing JD before authoring a new one, so the library comes
before the Builder in this guide too.

| Task | How | Notes |
|---|---|---|
| Browse/search harmonized roles | Open **🏦 JD Bank**, optionally type into **Search roles by title or by what the job does** — a title, a description of the work ("someone who processes invoices"), a short form or a misspelling | Matches titles first (tolerating typos), then roles **related by meaning**. Lists every **harmonized role** the Bank has distilled from the source archive — each a draft awaiting HR review, or a published JD. The counts are on 📈 Funnel (§5). Each row shows the role's **Department** so same-titled roles can be told apart: the role's own department, or else one its source documents state (a role whose sources sit in several departments shows only one of them), blank when none states one. Drafts written in the Builder are left out until HR publishes them; the page says how many it is not showing, with a link to show them. A search that matched no title, only meaning, says so above the results — *"No titles match your words…"* — because the nearest-by-meaning list is never empty, however unrelated the words. |
| Look up a PeopleSoft position number | Type only the number into the **🏦 JD Bank** search or the Builder's **🔎 Search to clone** — `61`, `00000061`, `#61` or `Pos 61` | Lists every archive file whose **file name** carries that position (newest first, by the date the file name starts with), each with the role it went into — or *not part of a role* — and lists those roles below. In the Builder each file offers *Start from its role* or *Start from this file*. A number no file name carries says so and searches the words instead. The pattern is `search.yaml`'s `position_query_pattern` (HR-339); it needs `search` among `segmentation.filename_positions.consumers` (HR-331). |
| See drafts people wrote in the Builder | Tick **Include drafts written in the Builder** and search | Left out by default: they are authors' drafts, not roles distilled from the archive. Each is labelled **Written in the Builder (by …)**, and its page says so instead of listing source JDs. Your own are always in 📝 My drafts. |
| Let a model read your search (optional, **off** unless ITS/HR switch it on) | Type the search as usual | When `search.yaml`'s `query_understanding_enabled` is on, a self-hosted model reads what you typed first — expanding "AP clerk" to *accounts payable clerk* — and the page shows **🧠 Read as: …** with the extra title keywords it added (each a link), anything it wanted that was ignored, and a **search the words as typed instead** link. It can only add results, never filter them: an employee group counts only if *you* typed it, a unit is only a suggestion. If the model is slow or down you get the plain search. The same applies to the Builder's **🔎 Search to clone**. |
| Sort the list | Click a column heading (**Role · Sources · Score · Quality · Status**) | Toggles ascending/descending; sorting resets to the first page. **Score** and **Quality** are the automatic wording check (higher score, A grade = closer to SFU's JD writing standards) — not the job's level or pay grade; hover a heading for the same note. |
| Read a role | Click a role's title or **Open →** — `/jd-bank/ui/role/{cluster_id}` | Shows the harmonized JD text plus every source JD it was distilled from, each opening to its full text. |
| Read a single source JD | **Read →** next to a source file | Renders that one archive document as text — `/jd-bank/ui/jd/{source_document_id}`. Shows two position rows: **from the file name** (how PeopleSoft attached the file, `<as-of date>_<position list>_…`) and **typed in the document** (often copied from the JD it was based on, so it can differ). When the text has no title, the title is taken from the file name and the page says so. |
| Browse the flat archive | **source archive** link on the library page → `/jd-bank/ui/archive` | Every ingested file, one at a time, searchable — no clustering, no harmonization. |
| Start a new JD from a role | **🧱 Start a new JD from this harmonized role →** on a role page | Clones the **harmonized role's** content into the Builder — not a raw archive parse — because a reviewed role is a better starting point than an un-vetted archive member. |
| Get SFU's Compensation Requisition Form for a role | **📄 Download SFU's Compensation Requisition Form, prefilled from this role →** on a role page | Opens a short page of choices, then downloads **HR's own PDF form** (the September 2024 AcroForm, still editable) with the Position Title, Department and Employee Group typed in — from the role, or from its source files where the role is silent and every file agrees — plus the request-type box you picked (A–E) ticked, the **one position you pick** written (as *Position #* for B–E, as the *based on* position for A, with that section's *based off of an existing position? Yes* ticked), and the contact name, title and email you type on the page (prefilled from your sign-in) unless you untick it. When you pick a position for a request, its Department comes from that position's own files where they agree. A role with a single position has it picked for you; *Leave blank* leaves the box blank. Each value is shown with where it came from, marked *confirm*. The source files' grades are shown for reference only and never typed onto the form. You pick the **request type** (sections A–E; or leave it for the form) and **which one position** the form is for — a role is distilled from several positions and the Bank never picks for you; a list that may be missing a position says so. Nothing else is filled: no names, no grade, no supervisor, no signatures, and nothing is stored. CUPE roles get no Employee Group (the dropdown offers APSA and APEX only), and a CUPE re-evaluation uses HR's separate Position Re-evaluation Request Form. |

---

## 5. Seeing where the archive stands — the Funnel  ·  [any] (any signed-in user)

**Where:** 📈 Funnel → `/jd-bank/ui/funnel`. **Who:** any signed-in user. **Admin
required:** no. **Read-only.**

🥇 **This page is the only authoritative source of counts in the whole system.** It is
computed from the database *at the moment you load it*, so it cannot go stale. No
document — not this guide, not the plan, not a status report — restates these numbers,
because five figures that agreed with each other across four documents were all wrong
once, and they agreed precisely *because* they came from one unchecked source.

> **If a number you have been given disagrees with this page, this page is right.**

### What it shows

It follows the archive from end to end and **accounts for everything that drops out at
each stage** — the gaps are the point, not a footnote:

| stage | what it counts |
|---|---|
| **Documents** | every file in the source archive |
| **Parsed** | those the parser could read; the remainder are named, not dropped |
| **In a role** | documents a harmonized role actually cites as a source |
| **Roles** | the harmonized roles themselves |
| **Approvable** | roles whose draft currently passes every blocking gate |
| **Published** | roles a reviewer has approved |

⚠ **Documents and roles are different units, and the page labels the unit on every row**
— a reader following the funnel downward will otherwise take the last number for
documents. It is a count of *roles*.

**The orphan accounting is the most useful part.** Documents that reached no role are
split into *duplicate of a kept document*, *near-duplicate of another orphan*, and **no
near-duplicate link at all** — because reported as one total ("N de-duplicated") those
three are indistinguishable, and the third bucket was hiding documents nobody had
explained.

**Scope it** with the scope parameter to see the same funnel for one unit or cohort
rather than the whole archive.

### Collections and units — the funnel's footer links

Below the funnel are links to named subsets of the Bank, each read from the database at
request time like the funnel itself. **Read-only, any signed-in user.**

| Page | What it is | Notes |
|---|---|---|
| **The IT collection** — `/jd-bank/ui/collection/it` | Roles in SFU's IT job family: the family's own classification, plus the roles a reviewer has added or removed | The page states what the membership rule **cannot see** — roles none of its signals can judge — beside what it matched, so a small list cannot pass for a complete one. `?queue=1` shows a separate ranked list of **candidates**: roles that might belong, for a person to rule on. A candidate is a question, never a member. |
| **Units** — VPFA, Facilities, ITS, Finance, Safety & Risk, Campus Services — `/jd-bank/ui/unit/<name>` | One part of SFU's organisation, rolled up from the departments the roles state | Every unit page carries **three** numbers: roles in the unit, roles not in it, and roles whose **department is unrecorded**, which no unit can claim. Membership is an exact list of department names set by the owner, never a pattern. Departments not yet assigned to any unit are listed as candidates. **ITS the department and the IT collection differ on purpose**: the collection includes IT roles in faculties and schools, and the ITS page explains the difference. |

### ⚠ Funnel vs Dashboards — they are not the same kind of thing

Both are read-only and both are in the nav, and confusing them has already cost a day:

| | **📈 Funnel** | **📊 Dashboards** |
|---|---|---|
| Source | the **database, at request time** | committed JSON artifacts on disk |
| Freshness | always current | a **snapshot** from whenever the report was last generated |
| Use it for | *what is true now* | the detail behind a past measurement run |

**Prefer the Funnel for any question about the current state.** Dashboards render
committed artifacts, so they are as old as the last pipeline run that wrote them — when
the Funnel first shipped nothing linked to it, and for a day people clicked *Dashboards*
and read stale numbers as though they were current. That is why **📈 Funnel comes before
📊 Dashboards in the menu**, and why it should come first in your habits too.

### ⚠ A low "Published" count is expected right now

Publishing is a **final-deployment** activity, not a pilot/dev/MVP one (owner ruling,
2026-08-29). During this phase the system is measured on its **drafts** — how many roles
have one, and how faithful each is to its sources. A small published number on this page
is the current design, not a fault to report.

---

## 6. Authoring a JD — the Builder  ·  [author] (any signed-in user)

**Where:** 🧱 Builder → `/jd-bank/ui/compose/new`. **Who:** any signed-in user (authors by
default). **Admin required:** no.

| Task | How | Notes |
|---|---|---|
| Start from an existing JD | **🔎 Search to clone** → pick a match → *Start from this* | Finds **harmonized roles and source documents** on **the form you chose at the top of the page**: an APSA / APEX / Poly author sees APSA / APEX / Poly results, a CUPE (WJQ) author sees CUPE ones, so cloning never switches you to the other form (HR-225). An exact or near **title** ranks above matches by meaning — see the note below. Typing only a **position number** lists the archive files filed under it instead, each with *Start from its role* or *Start from this file* (§4). |
| Author from scratch | Fill the guided questions, then **Check compliance** | Live panel shows the score, grade, blocking gates, and "Still to write" — each finding links straight to the section that needs it. Remaining findings are headed **"Fix these"** when a gate still blocks the draft; once the gates already **permit** it, the same findings are headed **"Suggested improvements"** with an amber **Suggestion** badge, and a note that they do not block review. |
| See roles SFU already has | The **"Roles SFU already has"** panel, once enough of the draft is written | Existing harmonized roles that look like the one being written, each with **Start from this role →**, plus how many roles carry **exactly this title** and across how many **departments**. Advisory only — it never blocks submission and does not change the compliance verdict. |
| Improve the summary with AI | **✨ Improve summary (assist)** | A self-hosted LLM suggests a better Position Summary; you review and edit it (nothing auto-applies). |
| Download the official document | **Export .docx ↓** | Renders the SFU `.docx` on the draft's own form: the APSA/APEX/Poly template — laid out as HR's 2024 template, with the Position Title / Position # / Employee Group table in the page header (plus the supervisor's title and position # when given), the About SFU block, each duty's "how and why" sub-bullets, the criminal record check sentence when ticked, and the territorial acknowledgement and Employment Equity footer (the About SFU and acknowledgement wording is printed from the rulebook as it stands; HR is still to confirm it — HR-104/105) — or — for a CUPE draft — HR's CUPE "WJQ Custom — Part 1: Job Description" form, with its fourteen sections in HR's order and no APSA footer. A CUPE draft **written in the Builder** prints what its author entered: the major and minor functions, the ticked level in each checkbox section, the duration / frequency / hours tables, and section 13's certification, years, equivalency, **Occupational Skills** and Occupational Requirement(s). A CUPE role **distilled from the archive** prints every checkbox unticked and the tables blank, because a tick there would be a guess. Either way the Approval and Review lines and HR's own box are always blank, for the people who sign them, and no grade is printed. Rendering only — nothing is validated or published. |
| Get the Compensation Requisition Form | **📄 Download SFU's Compensation Requisition Form…** under *Export*, on a draft started from a role | Links to that role's form page (§4) — the PDF HR asks for alongside the Word JD when a position is new or re-evaluated. A from-scratch draft has no role and no positions to offer, so it shows no link. |
| Send for approval | **Submit for review →** | Persists a **draft** into the review queue, attributed to **you** (the signed-in user). It publishes nothing (guardrail #1). You land on **📝 My drafts** with a confirmation. |
| See what happened to what you sent | **📝 My drafts** → `/jd-bank/ui/my-drafts` | Every JD **you** have submitted, newest first, and where each one stands: *Waiting for HR review*, *Approved and published*, or *Closed*. Read any of them; you see only your own. |

> **Where a draft goes after you submit it.** Into the same review queue as every other
> draft — an HR reviewer approves, rejects or edits it (§7), and **nothing publishes
> without that** (guardrail #1). The score on **My drafts** is the check the Builder ran
> when you submitted; HR re-runs it before approving, so treat it as a guide rather than a
> decision. A row marked **Closed** means the draft was either rejected or replaced by a
> newer version of the same role — the record cannot tell those apart, so the page does
> not guess.

> **How search ranks.** An exact or near **title** is looked up in Postgres and ranked
> **above** the semantic hits, because the document vectors deliberately exclude the title —
> the same exclusion that makes dedup title-agnostic. Search also finds **harmonized roles by
> their own title**, not only source documents: **61%** of harmonized role titles appear on no
> source document, because harmonization renames the role. A source document is **collapsed
> into the harmonized role** it belongs to, so a role is never listed above its own members,
> and same-titled roles are told apart by **department** — SFU has 9 distinct "Academic
> Advisor" roles across 6 departments, which are different jobs, not duplicates. A title hit
> is labelled "harmonized role" and carries **no percentage**: it was not found by distance,
> and quoting a similarity for it would invent one.

> **Why the duplicate panel shows no percentage.** Measured over the live role index, a role's
> nearest *unrelated* neighbour scores **higher** (median 0.9604) than a genuine same-title
> twin (0.9335), so no cutoff separates the two. Ranking works; the absolute number does not,
> and a percentage would look precise while meaning nothing. The panel therefore ranks, and
> states the one fact that needs no vector at all — the title and department collision.

> ### The Builder authors BOTH SFU forms (new — CUPE Phases B–E, 2026-08)
>
> The page opens on a **Form** line, with a *switch to …* link for the other one:
>
> * **APSA / APEX / Poly** — SFU's job-description form, what the Toolkit, the
>   validator and the approval gates were written against.
> * **CUPE (WJQ)** — the CUPE 3338 Weighted Job Questionnaire, a **14-section
>   point-factor instrument**. A different *form*, not a variant: it has no Problem
>   Solving or Impact of Decision Making section, and it carries none of SFU's
>   boilerplate blocks.
>
> **Each draft is judged against its OWN form's bar.** A rule that reads a section the
> WJQ does not have is withheld from CUPE drafts entirely (Phase B), and the numbers
> differ where the form differs — the WJQ allows **12** duties because the instrument
> prints twelve slots and 77.4% of CUPE JDs fill all twelve (HR-202). **A CUPE score and
> a JDFN score are therefore not comparable numbers**, and every surface that shows both
> says so.
>
> **Switching form starts a fresh draft.** The two forms do not ask the same questions,
> so carrying answers across would silently drop whatever the other form does not have.
>
> *Search to clone* follows the form you are on (HR-225), so starting from a result
> keeps you on the same form.
>
> **What HR has and has not ruled.** Almost every register entry is still `open` —
> the register's own header gives the count, and only the two approval gates
> (HR-042, HR-052) are ratified — including every value in the WJQ profile. The bar CUPE drafts are measured against was
> built the way APSA's was — measured over the corpus, every value registered, nothing
> auto-publishing — and HR may change any of it. **HR-194** (may the Bank *author* CUPE?)
> and **HR-201** (do SFU's boilerplate requirements apply to a form that has no such
> block?) are the two that decide scope, and both are unsigned.
>
> **Why CUPE needed its own everything.** Measured before any of it was built: scored
> through the JDFN validator, **0 of 600** CUPE JDs were approvable, against 11.3% of
> JDFN ones — and the cause was the *form*, not the quality. Four rules fired on **100%**
> of CUPE documents because the WJQ does not contain the sections they check (**0.0%**
> have a Problem Solving section; **3.1%** an Impact of Decision Making one). Once each
> form is judged on its own terms the picture inverts: the CUPE cohort is approvable at
> **59.0%**. Evidence: `docs/decisions/cupe-scope-measured-2026-08-14.md` and
> `docs/decisions/cupe-phase-b-measured-2026-08-14.md`.

---

## 7. Reviewing & approving — the Review queue  ·  [reviewer] or [admin]

**Where:** 📋 Review queue → `/jd-bank/ui/queue`. **Who:** **reviewer or admin only** — an
author who is not a reviewer does not see this link in the menu at all, and is refused if
they reach the address another way. **Admin required:** no (reviewer suffices).

| Task | How | Notes |
|---|---|---|
| See what's awaiting review | Open the **Review queue** | Lists draft JDs 100 to a page (**← Prev / Next →**, "Showing 1–100 of N"), each with the SFU **form** it is on — APSA / APEX / Poly or CUPE (WJQ) — where it came from (*N archive files* or *written in the Builder*) and its version. **Find a draft by title** filters the whole queue. The queue holds both forms, and **the score beside a draft is not the same measurement for the two**: each is judged against its own form's bar. The page says so above the table. |
| Inspect a draft | Click a row → the review detail page | Names the **form** and the bar it was scored against, before the score. Shows the rendered draft, the harmonization change-log (what each source fed, what was dropped and why), **how the draft was assembled** (see below), and the live gate decision. |
| **See how the draft was assembled** | The **"How this draft was assembled"** panel | How many source JDs were harmonized into this draft; how many of them required each skill and stated each duty; anything flagged for your eye; and **how the education and experience bars were chosen**. |
| See what changed | **Changes since last approved version →** | A side-by-side, section-by-section diff of the draft against the last approved version of the same role. Says "no prior approved version" the first time a role is reviewed. |
| **Approve** | **Approve** (fill an override reason for any overridable blocking gate) | Publishes **only if** the validator's gates permit it, re-checked at approve time. A blocked draft cannot be approved without a valid override + written reason. Approving a draft also **supersedes** (archives) any other live published version of the same role, so a cluster never carries two published rows at once. |
| **Reject** | **Reject** + a reason | Only offered on a live **DRAFT**. |
| **Edit** | **Edit** the fields + a reason | A structured, field-by-field editor (title, summary, duties, qualifications, footer flags, …) — no raw JSON. Editing a **DRAFT** archives the prior version, as before. Editing a **PUBLISHED** JD instead mints a new **DRAFT** and the prior version **stays published** — archiving it immediately would leave the role with no live approved JD for the whole review window; it retires only when its replacement is **approved**. **ARCHIVED** is refused: rejected or superseded is settled, and editing one would fork a new version off dead history. |

> **Why the "how this draft was assembled" panel matters, and what to do with it.** When a
> role's source JDs disagree about the required education or experience, the draft takes the
> **highest** bar any one of them stated — so a single source asking for a master's raises the
> whole role to a master's. That is a setting SFU HR has not yet ratified (HR-175), and the
> panel now says so explicitly: *"the sources disagreed — 1 of 10 stated the bar this draft
> uses, and 9 stated a different one."* **When you see that, check the bar suits the role
> rather than just the strictest source** — lowering it is an ordinary Edit. A source that
> stated no bar at all is not counted as disagreeing. The panel is background for your
> decision: it never changes the draft, the score or the gates.

> A **published** JD's review page shows **no Approve/Reject buttons** (the service could
> only refuse them) and its Edit panel is reframed **"Propose an update"**. An
> **archived** version offers no action at all — open the current version of the role to
> make a change. The reviewer on every action is the **authenticated user** — there is no
> "type your id" field. Every action is written to the tamper-evident audit log
> (guardrail #4).

---

## 8. User management — assign roles, enable/disable  ·  [admin] 🔑 ONLY

**Where:** 👤 Users → `/jd-bank/ui/admin/users`. **Who:** **admin only.** **Admin required:
YES.** 🔑

| Task | How | Notes |
|---|---|---|
| See everyone | Open **Users** | Table of every user who has signed in (provisioned on first login), their roles, status, and last login. |
| Grant / change roles | Tick **author / reviewer / admin** → **Save roles** | e.g. make a hiring manager a **reviewer** so they can approve. |
| Disable an account | **Disable** | Blocks login **and revokes their live sessions** immediately (signs them out everywhere). |
| Re-enable | **Enable** | |

> **Self-lockout guards:** you cannot remove your **own** admin role, nor disable your
> **own** account — so a single-admin deployment can't brick itself.

---

## 9. Operator tasks — pipelines, deploy, config  ·  [operator] 🖥️

These run on the **server shell** (Docker), not in the UI. They need **operator access**,
not the app admin role. Everything runs in containers (Docker-only, ADR-006); the one
exception is Ollama, which runs on `aria-gb10-2`.

### Bring-up & schema
| Task | Command | Notes |
|---|---|---|
| Build the images | `.\build.ps1` | Builds and proves they are deployable. `-NoCache` after a `requirements*.txt` or Dockerfile change; `-Bundle` also cuts the offline bundle. |
| Start (or redeploy) the stack | `.\launch.ps1` | Start → wait for healthy → migrate → verify → status. It **recreates** api and worker, because the dev API does not reliably reload on a Windows bind mount, and it **fails loudly** if any service is not running. `-NoCas` skips sign-in (dev only — never on a box others can reach). `make up` still works, but does none of the verifying. |
| Stop | `.\teardown.ps1` | Data is kept. `-Orphans` clears leftover one-shot containers; `-Volumes` discards the Bank (asks first). |
| Apply DB migrations | `make migrate` | `launch.ps1` runs it for you. **Run before ingest.** Postgres (alembic): the auth tables (users/roles/sessions), the audit hash-chain, and the title search indexes. Also runs the Neo4j cypher migrations, including **`003`**, which creates the `jd_role_embeddings` vector index — `make embed-roles` cannot run before it. |
| Which Bank does this checkout act on? | `make bank-target` | Prints the compose project, image tag and ports. A second, isolated Bank can run beside the live one — see `deploy/README.md` § *Running a second Bank*. |
| Open a shell in the app | `make shell` | |
| Install on a fresh box with no internet | `.\deploy\install.ps1 -BundleDir <bundle>` | From a bundle cut on a connected box (`make bundle` or `.\build.ps1 -Bundle`). Re-cut the bundle whenever `requirements*.txt`, the Dockerfile or a migration changes. Runbook: `deploy/README.md`. |

### Deploying for real — the production file  **[operator]** 🖥️

`docker-compose.yml` is the **development** stack: it runs the API with a reloader, mounts
your working tree into the container, and carries credentials that are committed to this
repo. Do not deploy it.

```bash
docker compose -f docker-compose.prod.yml up -d
```

| It differs from the dev stack in exactly these ways | Why |
|---|---|
| No reloader | Measured: under `--reload` a refused start leaves the container reporting `Up` while serving nothing. Without it the process exits `3` and you can see it. |
| No source mount | The built image is what runs, not whatever is checked out on the box. |
| `restart: unless-stopped` + a healthcheck on the API | So `Up` means *answering*, and a crash comes back. |
| `ENVIRONMENT=production` pinned | Turns on the startup check that refuses an unsafe posture. |
| Credentials have **no defaults** | `docker compose` refuses to start until you set them, instead of quietly using the ones in git. |
| The API binds to **loopback** | TLS terminates in front of it. Set `JD_API_BIND=0.0.0.0` only if your TLS terminator is on another machine — that publishes the application itself. |

**You must supply**, or compose will not start (it names each one):
`DATABASE_URL` · `JD_PG_USER` · `JD_PG_PASSWORD` · `NEO4J_PASSWORD` ·
`CAS_SERVICE_BASE_URL` · `ALLOWED_SERVICE_ORIGINS`.

> **What this does NOT give you: TLS.** The production file will not serve https itself,
> and the startup check requires https origins — so you need a terminating proxy (or an
> external one) in front. Until that exists, sign-in cookies and CAS tickets travel in the
> clear. If a refusal message names a setting, it is telling you the truth about the
> deployment; fix the setting rather than the check.

> **A refused start looks like this** — the message names every unmet condition at once,
> and never prints a value, so it is safe to paste into a ticket:
> `refusing to load settings: 5 unsafe setting(s) for environment='production'.`
> The container will then read `Restarting (3)` and its health will stay `unhealthy`.

### The archive pipeline (run in order)
| Task | Command | Notes |
|---|---|---|
| Ingest + parse the archive | `make ingest JD_ARCHIVE_PATH=<SFU JDs>` | Loads all files into Postgres. Incumbent names are scrubbed at ingest. **Idempotent and skip-first** on `(document, parser_version)`, so a re-run only does what is missing — safe to re-run after a partial or failed pass. |
| Embed | `make embed` | Section + document vectors into Neo4j. Uses self-hosted Ollama (local-only). |
| Embed harmonized roles | `make embed-roles` | Embeds the **harmonized roles** (`canonical_jds`) as one `(:JDRole)` vector per cluster into the `jd_role_embeddings` index — a separate label and index from the archive's `JDDocument`, so the Bank can search its own output (§6's search row). Idempotent and skip-first: a re-run costs nothing, and an edited role re-embeds automatically. Deliberately **not** wired into `approve` — publishing never depends on the GPU being up. |
| Near-duplicate dedup | `make near-dup JD_ARCHIVE_PATH=<SFU JDs>` | Tier-2. **Reads the archive files**, so it needs the same `JD_ARCHIVE_PATH` as ingest. Without it, it reads an empty folder, finds **0 edges and still exits 0**: check the summary says the documents were *signed*, not *unreadable* (a full archive gives ~14.8k edges, coverage ~0.996). |
| Role-equivalence dedup | `make dedup-role` | Tier-3 (needs ingest + embed). |
| Cluster roles | `make cluster` | Phase-3.5 clustering report. |
| Produce draft canonicals | `make canonical-drafts CANONICAL_ARGS="…"` | One DRAFT per cluster, for both forms, into the review queue, with the model rewrite and audit when Ollama is free. A full pass takes days and holds the inference host, so **scope it**: `--only-template jdfn\|wjq`, `--only-undrafted` (clusters with no draft), `--limit N`. `--no-llm` is deterministic and **refuses to overwrite model prose** unless `--allow-downgrade`. Reviewer-touched drafts are never overwritten. **Resuming an interrupted pass:** `--refreshed-since <start time>` when the Bank already held prose before the pass began; `--resume` only when it did not — `--resume` skips every draft that already has prose. It is a one-shot job: nothing restarts it after a reboot. Afterwards run `make embed-roles`, `make bank-audit` and `make smoke`. |
| Archive baseline (measurement) | `make baseline JD_ARCHIVE_PATH=<SFU JDs>` | Scores the whole archive; writes `docs/baseline/`. |
| Identification fields vs the archive | `make field-audit JD_ARCHIVE_PATH=<SFU JDs>` | **P3b.** What the parser stored against what the SOURCE FILES say, per field per bargaining unit — five columns, never one percentage. `FIELD_AUDIT_ARGS="--sample 1200 --evidence 20"` prints the gap file by file. Needs the archive AND Postgres; writes no Bank row. Reports what it cannot see (`classification` is unevaluated). See `docs/field-audit/`. |
| One-of-a-kind jobs (measurement) | `make singletons` | How many SFU jobs exist exactly ONCE — the population `comparison.singleton_role_policy` drops today (HR-223). **Read-only, Postgres only**, safe at any time. Four buckets plus a control, never one total; writes `docs/singletons/`. Re-run it after any re-parse rather than quoting the last numbers — every bucket is title-based. |

> ### ⚠ If a release bumps `parser_version`, the re-parse is not optional
>
> `parsed_jds` is keyed on `(document, parser_version)` and every **batch** consumer
> filters on the version the code declares. **Deploying a bump without re-parsing leaves
> those consumers reading zero rows — a Bank that looks empty.** Run
> `make ingest JD_ARCHIVE_PATH=<SFU JDs>` as part of the same change, not afterwards.
>
> It is **additive and reversible**: a re-parse inserts rows at the new version and leaves
> the old ones, so you can compare versions and roll back by deleting the new rows. The
> **user-facing pages are unaffected** either way — they read the most recent parse
> regardless of version.
>
> **Which version is in force:** read the constant, not this guide —
> `grep '^PARSER_VERSION' core/src/jd_core/parser/segmenter.py`. When this guide was last
> revised (2026-11-20) the live Bank ran **`jd_segmenter_v8`**, and **v10** existed only on
> the separate v9 Bank (`bank/v9`), not yet shipped.
>
> Why the recent versions exist, each found by checking a field against the **source
> files** rather than the database:
>
> * **v8** — the department label most old CUPE forms actually print, `Department
>   Name/Section`, was not recognised; about six hundred departments came back.
> * **v7** — on the old CUPE form a label and its value sit in one cell, and the parser
>   read the next cell: about half of CUPE descriptions had no title. 805 came back.
> * **v6** — a job was called CUPE because it *mentioned* CUPE (an APSA manager who
>   supervises CUPE staff). The employee group is now read, not guessed (HR-226).
> * **v5** — a section heading printed beside the next column went unseen, so **16.2%
>   of CUPE descriptions had no duties at all**, and checkbox text could be read as a
>   duty.
> * **v4** — a 4,000-character cap silently truncated **81.4%** of CUPE descriptions'
>   point-factor block. The cap is now HR-200.
>
> The fuller account, with the measurements, is in `DEVELOPER_GUIDE_1.md` §9a and
> `docs/FINDINGS.md`.

### Governance & health
| Task | Command / where | Notes |
|---|---|---|
| Run the full test/gate suite | `make gates` | Static + unit + integration + coverage. What CI runs — on fixtures, so it says nothing about the live Bank. |
| **Check the live system end to end** | `make smoke` | Runs against **this checkout's live Bank**: every document accounted for and findable, the vector indexes current, and the pages and forms testers use. **Nothing merges or deploys while it is red** (Directive #0, `CLAUDE.md`). Run it again after any producer pass or reindex. |
| Check what drafts actually contain | `make bank-audit` | Read-only, seconds, no inference host. Per form and per section: how many roles' sources state it against how many drafts keep it. **Above 100% means the draft invented content**; below means it dropped some. Exits 2 while anything is off 100% — the check firing, not a crash. |
| Regenerate the HR decision register | `make register` (check: `make register-check`) | Any non-trivial rule/metric must be YAML-configurable and registered. |
| Re-render this guide | `make guide` (check: `make guide-check`) | Renders `docs/OPERATOR-GUIDE.md` → `docs/operator-guide.html`, the page served at 📖 Guide. `guide-check` byte-diffs the render against the committed HTML and fails if it is stale — run it, and commit both files together, after every edit to the Markdown. Never hand-edit the HTML. |
| Verify the audit chain | `verify_audit_chain()` in `src.api.services.audit` | Recomputes the hash chain; detects any altered/deleted `audit_log` row. |

### Backup, restore & reindex — the runbooks  **[operator]** 🖥️

Two procedures, both executed against the live stack before they were written down, with
the numbers they printed:

| Runbook | Covers |
|---|---|
| [`docs/runbooks/backup-and-restore.md`](runbooks/backup-and-restore.md) | What must be backed up (**Postgres only** — Neo4j is a derived index), how to dump, how to restore, and how to verify the restore kept the audit chain intact. |
| [`docs/runbooks/reindex.md`](runbooks/reindex.md) | Rebuilding the Neo4j vectors with `make embed` / `make embed-roles`, the skip-first resume behaviour, and what makes `embed_stamp` move. |

**Two things from those runbooks are worth knowing before you need them:**

- 🔴 **`pg_restore --data-only` into an already-migrated database silently destroys the
  data and exits `0`.** Measured on a real dump: 1,804 canonical JDs → **0**, 12 user
  roles → **0**, 1,810 chained audit rows → **0**, while the command reported success and
  the app still accepted logins. Restore a full custom-format dump into an **empty**
  database, and verify with the fingerprint query in the runbook. A zero exit is not
  evidence.
- **Re-running a reindex is free.** The runners are skip-first on
  `(text_sha256, model, embed_stamp)`; an unchanged corpus re-run makes **zero** inference
  calls (measured). So an interrupted reindex is resumed by running it again.

### Auth configuration (env)
| Setting | Purpose |
|---|---|
| `CAS_ENABLED` | `true` in production (require SFU sign-in); `false` for dev/CI. |
| `ALLOWED_SERVICE_ORIGINS` | **The origins CAS may return a signed-in browser to** — comma-separated, exact (scheme, host, port). This is what lets one deployment be reached more than one way; see the note below. |
| `CAS_SERVICE_BASE_URL` | The **fallback** origin, used when the origin a browser arrived on is not on the list above. |
| `BOOTSTRAP_ADMINS` | Comma-separated CAS ids granted `admin` on login (first-admin bootstrap). |
| `SESSION_COOKIE_SECURE` / `_SAMESITE` | `true` / `strict` in production (HTTPS). |
| `FEEDBACK_EMAIL` | Address for the **✉ Report a problem with this page** link in every page's footer (a mailto prefilled with the page, its address and the signed-in user); empty = no link. |

> **Reaching the app by more than one address** **[operator]** 🖥️. CAS is told a single
> "service" URL per sign-in, so a deployment reachable both on the box (`localhost:25800`)
> and through a forward or proxy (`https://jdbank.sfu.ca`) needs both listed:
>
> ```
> ALLOWED_SERVICE_ORIGINS=http://localhost:25800,https://jdbank.sfu.ca
> ```
>
> The app then returns each user to the address **they** came in on, with no config change
> to switch between them. An address that is **not** on the list falls back to
> `CAS_SERVICE_BASE_URL` — never to whatever the request's headers claimed, which is the
> whole point: without that check, anyone able to set a header could choose where a
> signed-in user (and their CAS ticket) was sent. In production every entry must be
> `https` at a real hostname, and the service refuses to start otherwise.
>
> `CAS_SERVICE_FROM_REQUEST` is **retired**. It did the same job without the check. The
> service now refuses to start while it is `true` rather than ignoring it, so nobody is
> left believing they enabled something they did not.

> **Seeding users** (demo/data) is an operator task done directly against the DB; real
> users appear automatically on first CAS login. Roles are then managed in the UI (§8).

---

## 10. "Who can do this?" — quick reference

| Task | any | author | reviewer | admin 🔑 | operator 🖥️ |
|---|:--:|:--:|:--:|:--:|:--:|
| Sign in / out | ✅ | ✅ | ✅ | ✅ | — |
| See live archive counts (**📈 Funnel**) | ✅ | ✅ | ✅ | ✅ | — |
| Browse dashboards (snapshots) | ✅ | ✅ | ✅ | ✅ | — |
| Browse/search the content library & archive (read-only) | ✅ | ✅ | ✅ | ✅ | — |
| Author / clone / assist / export a JD (Builder) | ✅¹ | ✅ | ✅ | ✅ | — |
| Submit a draft for review | ✅¹ | ✅ | ✅ | ✅ | — |
| See your own submitted drafts (**📝 My drafts**) | ✅¹ | ✅ | ✅ | ✅ | — |
| Approve / reject / edit / override in the queue | — | — | ✅ | ✅ | — |
| Manage users (roles, enable/disable) | — | — | — | ✅ | — |
| Run pipelines / migrations / deploy / CAS config | — | — | — | —² | ✅ |

> ¹ The Builder & dashboards require only that you are **signed in**; new users hold
> `author` by default. ² App admins do **not** get server/pipeline access from the admin
> role — that is separate **operator** access.

---

⚠ **Counts belong on 📈 Funnel, not in this guide.** If you find a figure here describing
the archive's current state, treat it as a bug and check the Funnel instead.

*Related docs:* `HANDOFF.md` (current state), `docs/ORAL-HISTORY.md` (how the system came
to be the way it is), `deploy/README.md` (offline install and a second Bank),
`docs/NETWORK-SETUP.md` (for network administrators), `docs/FINDINGS.md` (everything measured
about the archive, with its working), `docs/adr/ADR-008-auth-cas-rbac.md` (auth/RBAC
design), `docs/baseline/README.md` (the archive baseline),
`docs/decisions/HR-DECISION-MATRIX.md` (what SFU HR must decide), `CLAUDE.md`
(invariants).

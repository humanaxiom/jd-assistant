# Plan — what we do next

**Forward-looking only.** This file says what we intend to do. It deliberately **does not
restate counts**: live numbers are at **`/jd-bank/ui/funnel`**, measured findings are in
[`FINDINGS.md`](FINDINGS.md). Numbers repeated in a fourth place is how this project shipped
five wrong ones that agreed with each other.

> **Before any engineering task, ask: does this change the number of PUBLISHED JDs?**
> If not, it is not next — however real the defect.

## 🔴 DIRECTIVE #1 — applies to EVERY item on this page

**Set by the project owner 2026-08-28.** No task below is complete until it is:

1. **tested** — `make gates` green, failing test first, the guard broken once;
2. **deployable through the scripts** — `build.ps1` / `launch.ps1` / `teardown.ps1`, and `deploy/bundle.ps1` +
   `deploy/install.ps1` onto a fresh, offline box, **with no assistant in the loop**;
3. **discoverable** — reachable from the UI, because *a feature nothing links to has not
   been delivered*;
4. **green on `make deploy-check`** — CI gate *"Gate: deployable offline"*.

⚠ **"It works on the dev box" is not done.** Ask: *could the owner deploy and see this,
tomorrow, without me?* Full statement in [`CLAUDE.md`](../CLAUDE.md); runbook in
[`deploy/README.md`](../deploy/README.md).

---

# 🔴 TRACK P — the parse, and making archive → harmonized verifiable

**Opened 2026-08-29, and it still comes before new features**: they were being stacked on
a parse that could call a job CUPE because it *mentioned* the word. `PARSER_VERSION` is
now **v6** (HR-226), the archive has been re-parsed, and the drafts built from the
mislabelled documents are gone. The working is in [`FINDINGS.md`](FINDINGS.md) §7.

**P1 is done. P2 is the live one** — and it is the defect that made the CUPE/APSA numbers
look wrong in the first place: a third of the archive is *counted* as JDFN on no evidence.
Fixing the parse without fixing how the result is REPORTED leaves the misleading surface
in place.

| # | task | size | notes |
|---|---|---|---|
| ~~**P1**~~ | ✅ **The drafts claiming a template their documents are not — DELETED 2026-08-29** | done | Owner ruled delete over re-compose. `core/db/repairs/001_drop_mislabelled_cupe_drafts.sql` — derived condition not hardcoded ids, idempotent, refuses to touch anything non-`DRAFT` or reviewer-touched. `make smoke` **green**. §7d. |
| **P2** | ⚠ **Report `employee_group` as matched / not-matched / UNRECORDED** | small | **The next parse task.** `template_of` defaults every unknown to JDFN, so a third of the archive is *counted* as JDFN with no evidence — the funnel, the baseline "By template" facet and every CUPE/APSA comparison inherit it. Same defect as the IT collection: no could-not-evaluate bucket. Every facet over this field must publish all three numbers. §7c. |
| ~~**P3a**~~ | ✅ **`title` audited against the source files — 2026-08-29** | done | 47.6% of CUPE documents had NO title against 0.0% everywhere else; antiword's render puts label and value in ONE cell. **805 titles recovered, CUPE placeholders 47.6% → 28.9%**, position numbers +593. `PARSER_VERSION` v7. §8. |
| **P3b** | **Audit the fields nobody has checked yet** | med | `title` and `employee_group` are the ONLY two ever compared against the raw archive, and each produced defects immediately. `department` (72.2% populated), `grade`, `classification` (parsed on 21%, reaches 0% of drafts) and `position_number` have never been checked at all. |
| **P3c** | ⚠ **One recovered title contains an incumbent's name** | small, needs a decision | `Leigh McGregor. Departmental Assistant`. Detecting a personal name needs a measurement and a registered rule, not a regex invented on a sample of one — and NN #5 makes incumbent-name removal a rulebook quality step. §8d. |
| **P4** | ⚠ **24 clusters now have no draft** | small, after a decision | The consequence of P1, and it is the honest state — but nothing regenerates them today. `src.jd_bank.canonical` has `--only-template` and **no per-cluster filter**, so re-drafting just those is not expressible; a full producer run is under a standing ⛔. Either add the filter, or accept them as un-drafted until the next run. |

⚠ **The lesson that generalises:** the old routing guard asked one direction and stayed
green through ~140 mislabels. **Assert both directions, or the guard is decoration.**

**Tooling that landed alongside it (2026-08-29):** the operator scripts are now
`build.ps1` → `launch.ps1` → `teardown.ps1`, one job each, per Directive #1.
`launch.ps1` fails loudly when a service is not RUNNING — written because the worker sat
`Exited (1)` for nine hours behind an otherwise-green stack — and `teardown.ps1
-Orphans` clears the one-shot containers compose leaves behind, which had been making
every compose command print a warning everybody had learned to ignore.

---

# TRACK A — the demo ✅ COMPLETE

A1–A5 are built and merged. Two live surfaces, both reading the database at request time:

| | |
|---|---|
| `/jd-bank/ui/collection/it` | the IT collection, plus `?queue=1` for the review queue |
| `/jd-bank/ui/funnel` | archive → published, scope-parameterised, with the full gap accounting |

**What remains on this track is not engineering:**

| # | task | who |
|---|---|---|
| **A6** | **Work the IT review queue.** Candidates are questions; `include` / `exclude` (HR-217/218) hold the answers. Until a human rules, the collection is central IT only. | ITS directors |
| **A7** | **Vet the department alias list** (HR-222). Two calls to confirm: `School of Computing Science` is excluded as academic; `Library Systems` is included. One line each. | ITS directors |

---

# TRACK B — the pilot (the actual deliverable)

| # | task | who | notes |
|---|---|---|---|
| **B2** | 🔴 **Run the pilot** | needs HR | ~20 approvable drafts reviewed for real. **Success = 20 PUBLISHED JDs + the reviewer's written objections.** |
| **B3** | 🔴 **Ratify two gates** | needs HR | `SFU-APPROVE-QUAL-EQUIVALENT` and `SFU-APPROVE-KSA-ORDER` between them block most CUPE drafts. **One ruling beats every engineering change made in August, at zero GPU cost.** |
| **B4** | **Book HR ratification** | needs HR | **79 decisions need an HR ruling**, none ratified. The register holds more, but the rest are engineering settings or shape only what a reviewer sees. The matrix needs a calendar invitation, not another revision. |

**B2–B4 are asks, not tasks — make them now.** They are the only work that moves the
published-JD count, and they are pure lead time.

---

# TRACK D — the archive gap (new, and one item changes the ceiling)

From [`FINDINGS.md`](FINDINGS.md) §2. **None of these changes the published count today**,
so none displaces Track B — but D1 changes what the Bank can *ever* publish.

| # | task | size | notes |
|---|---|---|---|
| **D1** | 🔴 **Decide what happens to a one-of-a-kind job** | decision, then small | A role is built from a GROUP of near-duplicates, so a job with no duplicate anywhere produces nothing. **Register the decision; do not quietly patch it.** This is the only item that raises the ceiling. ⚠ **Measurement done and a draft HR-223 entry written 2026-08-28** — parked mid-flight in `git stash` (`WIP D1/HR-223…`) when Track P took priority. Recover it rather than re-deriving: the archive work is finished, the register entry is not. |
| **D2** | 🔴 **Fix title extraction** | small–med | The parser emits a placeholder or captures letterhead, banners, separator rows and `[pic]`. ⚠ Its reach is far wider than the gap — most affected documents are already in drafts. |
| **D3** | ⚠ **Near-duplicate recall miss** | med | Documents sharing a title with others that did cluster. **Measure before tuning** — adjusting `jaccard_min` until the number improves is how this gets worse. |

---

# TRACK E — the next units (queued, blocked on people not code)

The scope seam is built, so adding a unit is configuration rather than a rewrite. Order set
by review; see [`FINDINGS.md`](FINDINGS.md) §5 for why a unit is a rollup.

| # | unit | blocked on |
|---|---|---|
| **E1** | **VPFA** (Finance & Administration) — **ITS rolls up into it** | the org tree + curated alias map |
| **E2** | **Facilities Services** | same, plus a boundary call (is Campus Security in it?) |

⚠ **Do not seed the tree or the aliases by inference.** A wrong rollup hands a
vice-president a confident wrong number about their own portfolio.

---
---

# TRACK F — JD currency after publishing (designed, queued after E2)

*(Unrelated to the archived "Phase F" in Track C — the letters collide, the work does not.)*

**Design:** [`plans/JD-CURRENCY-ATTESTATION.md`](plans/JD-CURRENCY-ATTESTATION.md) —
written 2026-08-28 with the base system verified live, so the reuse/new split is fact,
not memory. A published JD currently has no owner, no review date and no re-validation;
this adds the **review / update / attestation loop**: due by cadence → steward attests →
**REAFFIRM** (row only) / **REVISE** (the existing edit→draft→approve path) / **RETIRE**
(new, reviewer-gated PUBLISHED → ARCHIVED).

| verified: reused from the base | genuinely new |
|---|---|
| publish/supersede lifecycle, untouched | `attestations` table (append-only) |
| `rules_version` already stamped on every draft → rulebook-drift flag needs no field | **RETIRE** review action (no retire path exists today) |
| publish date derivable from the APPROVE row → no `published_at` column | `role_stewards` (default = approver; by-unit lands on Track E's tree) |
| validator re-run (advisory), Scope seam, audit chain, queue UI pattern | `currency.yaml` + HR register entries, all `open` — **cadence is HR's number, not ours** |

**Sequencing:** after **E2 (Facilities)**; only worth *building* alongside **B2** — with a
handful of published JDs a currency loop is ceremony, the pilot's twenty make it real, and
the pilot reviewer is the first steward candidate. Stale is **advisory on every axis** —
nothing auto-unpublishes, mirroring NN #1.



# TRACK G — upload a JD into the Builder (designed, backlog)

**Design:** [`plans/BUILDER-UPLOAD-AND-CHECK.md`](plans/BUILDER-UPLOAD-AND-CHECK.md) —
written 2026-08-29 against the live code, so the reuse/new split is fact, not memory.

A manager with a JD in a Word file or a PDF cannot currently ask the Bank the one question
they have: *is this any good?* Upload → parse → compliance panel → optionally seed a draft.
It turns the Builder from an authoring form for people already inside the Bank into a **JD
assistant anyone with a document can use**.

**Mostly reuse.** Upload is a new front door onto the clone chain that already runs:
`extract_text → parse_jd → jd_to_answers → _render_clone → assess_draft` is exactly what
`compose/clone/{id}` does today, and the composer already persists drafts with no archive
lineage (`source_document_ids=[]` — one of the four PUBLISHED JDs is such a role).

| genuinely new | note |
|---|---|
| multipart intake | 🔴 `python-multipart` is **deliberately absent** (`routes/_forms.py`), and the CSRF check reads the body *before* the handler — which buffers the whole file. Settle this first. |
| PDF extraction | `DocumentFormat` routes PDF to `other` → `UnsupportedFormatError`. New dependency, and it must vendor into the **offline** image. |
| provenance + retention | an uploaded file has no `source_documents` row and must never inflate the archive counts |

**Sequencing:** **U1** the existing formats, in memory, no persistence (zero new extraction
code — the honest MVP) → **U2** PDF, text-layer only, **gated on a measured section-recall
number over real non-archive JDs** → **U3** persistence and draft creation.

⚠ **The risk to design against:** a confident wrong parse. `Untitled Position` is a
placeholder that reads as success, and parse quality varies wildly *on documents the
parser was tuned for*. The panel must report **matched / not-matched / could-not-evaluate**
— a silently empty parse that then gets scored is worse than a refusal.

⚠ **Does this move the published count? Not directly.** It changes *who can use the Bank*.
It does not displace B3/B4.

# ⏸ BEFORE GOING LIVE — blocks nothing

**Decided 2026-08-28.** The known list to close before the system goes live in the ordinary
sense. **These gate nothing** — not the pilot, not the demo, not any other work.

| # | task | notes |
|---|---|---|
| **BGL-1** | **TLS at the edge** | `sfuai.ca:7000` is plain HTTP carrying CAS session cookies. Ours alone to close, no HR dependency. |

⚠ **A suppression, not a resolution.** The exposure is unchanged; what is recorded is that
we are not working on it yet and it stops nothing.

---

# TRACK C — deferred

Real, registered, and **none of it changes the published-JD count.**

| item | note |
|---|---|
| **Duty-frequency matching** | Naive fix *measured* unsafe. Needs the measurement redone, not a retry. |
| **`classification` carry-through** | Parsed on a fifth of documents, reaches no draft. Real defect; not on the demo path. |
| **Document date at ingest** | Not stored; filenames carry it. Unlocks the era cut. Label it *derived*. |
| **Department taxonomy** | Curation against an authoritative org list we do not have. Demoted to a *filter* — see `FINDINGS.md` §5. |
| **HR-214 compression question** | Registered `open`. **Do not close with a threshold** — HR's call. |
| **JDFN `problem_solving`** | Fabrication rate measured well above 100%. Untouched by the CUPE work. |
| **Retire the static dashboards** | Two sources of truth will disagree, and the wrong one gets quoted. The live funnel replaces them. |
| **Phase F · Phase G · overlap graph** | Unchanged. |
| ⛔ **No further producer runs** | ~19 GPU-hours each; zero published JDs each. |
| ⛔ **`make bank-audit` is not progress** | It measures draft FIDELITY, not DELIVERY. |

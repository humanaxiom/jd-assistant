# Plan — what we do next

**Forward-looking only.** This file says what we intend to do. It deliberately **does not
restate counts**: live numbers are at **`/jd-bank/ui/funnel`**, measured findings are in
[`FINDINGS.md`](FINDINGS.md). Numbers repeated in a fourth place is how this project shipped
five wrong ones that agreed with each other.

> **Owner ruling 2026-08-29: nothing is blocked on policy, and publishing happens in the
> FINAL DEPLOYMENT — not here.** The measure in pilot/dev/MVP is **drafts**: their
> coverage and their fidelity. The old question ("does this change the number of PUBLISHED
> JDs?") is VOID — it made correct engineering look like a distraction. Ask instead:
> **does this give a role a draft, or make an existing draft truer to its sources?**

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
---

# ▶ THE MVP RUN ORDER — set 2026-08-29

**The dev/test iteration is closed.** The policy questions that gated it are ratified
(B3 — HR-042, HR-052), the parse defects that made the numbers untrustworthy are fixed
(Track P1–P3a), and the decision that caps the ceiling is registered (D1 → HR-223). What
follows is build order, not a backlog.

⚠ **One correction before anything is sequenced off it.** "The blockers are removed" is
true of the *process* and not of the *content*: B3 was ratified **as shipped**, so the two
gates block exactly what they blocked before. Nothing about CUPE approvability changed.
What is unblocked is that we are no longer waiting to be told where the bar sits.

| # | what | gate to start | why here |
|---|---|---|---|
| ~~**MVP-0**~~ | **B2 — the pilot: DEPLOYMENT PHASE, not this one** | — | Owner ruling 2026-08-29: publishing happens in the final deployment. It is not a gate on anything here and it is not the measure of this phase. |
| **MVP-0** | 🔴 **P4 — draft the 24 clusters that have none** | nothing — start now | The measure here is DRAFTS, and 24 roles have none. `--only-undrafted` makes it a scoped run of minutes. |
| **MVP-1** | **Core: finish Track P** | nothing — start now | ✅ **P3b is DONE** and produced a defect like the two audits before it — **726 CUPE departments the archive states and the Bank does not** (§9). Now **P3d** (fix the department read, scope-matched number FIRST), **P3e**, **P3f**, then **P3c**. (P4 moved up to MVP-0 — it is drafts, and it is unblocked.) E1 depends on `department` being trustworthy, and it is now measurably not — see the note below. |
| **MVP-2** | **E1 VPFA → E2 Facilities** | the org tree + curated alias map | The scope seam is built; adding a unit is configuration. The **people-work can start today** and does not wait for MVP-1. |
| **MVP-3** | **Track G — upload into the Builder** | MVP-1 landed | Changes *who can use the Bank*. Its two hard blockers are verified below, and one of them re-cuts the offline bundle. |
| **MVP-4** | **Track F — currency after publishing** | E2, and the deployment phase | A currency loop acts on PUBLISHED JDs, which is deployment-phase work by the owner ruling. Design is done; building it here would be ceremony. |

🔴 **MVP-1 before MVP-2, and this is not sequencing hygiene.** Track E defines a unit by
**department**, and `department` is one of the four fields **nobody has ever checked
against the source files**. The two fields that *have* been checked each produced defects
on first contact — `employee_group` two, `title` one. Seeding VPFA off an unaudited
`department` column is how a vice-president is handed a confident wrong number about their
own portfolio, and no test will catch it because nothing is broken.

⚠ **Do not seed the org tree or the aliases by inference** — that constraint is unchanged
and it is why MVP-2's gate is people, not code.


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
| ~~**P3b**~~ | ✅ **AUDITED 2026-08-29 — and it produced a defect, like the two before it** | done | `make field-audit`, all 14,518 parsed documents, five columns per field per unit. 🔴 **726 CUPE departments the archive states and the Bank does not.** Three causes, all read at source: the `Department Name/Section` variant is unregistered, antiword **wraps the label across a line break**, and some documents carry it only on the cover page. ⚠ **726 is an UPPER BOUND** — the probe reads the whole document, the parser reads only the identification block. [`FINDINGS.md`](FINDINGS.md) §9. |
| **P3d** | 🔴 **Fix the department read — but MEASURE THE SCOPE-MATCHED NUMBER FIRST** | med | The three causes need different fixes and no single one recovers all 726. **Do not add `Department Name/Section` to `id_labels` and call it done** — that addresses one cause, and the first P3a fix passed its tests and recovered exactly zero for precisely this reason. Register the label change; a parser bump ships WITH its re-parse. |
| **P3e** | **Collapse repeated internal spaces in the label match** | small | `_extract_label` strips and lower-cases but never collapses, so `Position  Title`, `Department  Name`, `IDENTIFICATION   Position Number` match nothing. Small, real, spans every field. §9d. |
| **P3f** | ⚠ **`classification` is read by HARDCODED REGEX, not rulebook data** | small, needs a register entry | `_CUPE_GRADE_RX` / `_JDFN_GRADE_APPROVED_RX` / `_JDFN_GRADE_FIELD_RX` in `parser/classification.py`. The field audit cannot see it at all, so it is reported unevaluated rather than clean. Same shape as the `employee_group` two-provenances defect. §9e. |
| **P3c** | ⚠ **One recovered title contains an incumbent's name** | small, needs a decision | `Leigh McGregor. Departmental Assistant`. Detecting a personal name needs a measurement and a registered rule, not a regex invented on a sample of one — and NN #5 makes incumbent-name removal a rulebook quality step. §8d. |
| **P4** | 🔴 **Draft the 24 clusters that have none — UNBLOCKED, and now expressible** | small | It needed a ruling and it has one: *nothing is blocked on policy*. `--only-undrafted` makes "draft what has no draft" a scoped run — minutes, not the ~44-hour full pass that made this impossible to justify. **Idempotent**: a second run over a fully-drafted Bank writes nothing and pays for no model call. Verified against the live Bank: **2,493 clusters, 2,469 with a version, 24 with none.** |

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

# TRACK B — the pilot ⏸ DEPLOYMENT PHASE, not this one

**Owner ruling 2026-08-29: publishing happens in the FINAL DEPLOYMENT.** Track B is not a
gate on anything built here, and it is not the measure of this phase. It is parked, not
abandoned.

| # | task | who | notes |
|---|---|---|---|
| **B2** | **Run the pilot** | deployment phase | ~20 approvable drafts reviewed for real. Still the right thing to do eventually; it gates nothing here. |
| ~~**B3**~~ | ✅ **RATIFIED 2026-08-29 — HR-042 + HR-052** | done | Ratified **as shipped**: no value changed, `rules_version` unmoved, nothing re-validated. It settled who is answerable for the bar, not where the bar sits. |
| **B4** | **Book the remaining ratifications** | deployment phase | The count outstanding is in the [register](decisions/HR-DECISION-REGISTER.md)'s own header, which now separates still-outstanding from ratified. ⚠ A count of the `hr_policy` tier is *not* a count of what HR still owes. |

> 🔴 **This track used to say "B2–B4 are the only work that moves the published-JD count,
> and that is the only measure".** That framing made every correct engineering task look
> like a distraction and is what let three sessions of real work read as avoidance. The
> measure here is **drafts** — coverage and fidelity.

---

# TRACK D — the archive gap (new, and one item changes the ceiling)

From [`FINDINGS.md`](FINDINGS.md) §2. **D1a is the largest DRAFT-COVERAGE gap in the
archive** — 462 singular jobs that produce nothing at all — and under the 2026-08-29
owner ruling that makes it engineering work, not a decision to wait on.

| # | task | size | notes |
|---|---|---|---|
| ~~**D1**~~ | ✅ **REGISTERED as HR-223 — 2026-08-29** | done, but the ruling is not | The decision is on the record and the population is measured by code anyone can re-run (`make singletons`, `docs/singletons/`). ⚠ **The parked draft's numbers did not survive re-derivation** — three buckets moved and the qualification comparison *inverted*; [`FINDINGS.md`](FINDINGS.md) §2a has the before/after. **`drop` still ships** and stays registered `open` — but under the 2026-08-29 owner ruling it no longer BLOCKS: closing the gap is D1a, and it is engineering. |
| **D1a** | 🔴 **Give the one-of-a-kind jobs a draft — an ENGINEERING gap now, not a ruling** | med | Owner ruling 2026-08-29: nothing is blocked on policy. **462 documents carry a title appearing exactly once** and produce no draft at all, because clustering takes EDGES as its only input. HR-223 still ships `drop` and is still registered `open` — but that is now a thing to BUILD past, not to wait on. `queue_for_authoring` is the cheaper route and needs NO clustering change — the Builder already mints roles from no source documents (`source_document_ids=[]`). `mint_role` needs two independent `ge=2` floors relaxed (`comparison.min_cluster_size`, `ClusterRecord.member_count`). ⚠ **Not before D3:** over the whole no-twin pool it would also mint a role for each of the **497 recall misses**, duplicating roles that already exist. |
| **D2** | 🔴 **Fix title extraction** | small–med | The parser emits a placeholder or captures letterhead, banners, separator rows and `[pic]`. ⚠ Its reach is far wider than the gap — most affected documents are already in drafts. |
| **D3** | ⚠ **Near-duplicate recall miss — now MEASURED at 497** | med | Documents sharing a title with others that did cluster: **497** of the 1,204 no-twin documents, from `make singletons` (§2a). That is the measurement D1 was waiting on, and it is larger than the 462 genuinely singular jobs beside it. **Measure again before tuning** — adjusting `jaccard_min` until the number improves is how this gets worse, and a shared title is evidence of a miss, not proof of one. |

---

# TRACK E — the next units (**MVP-2**, blocked on people not code)

The scope seam is built, so adding a unit is configuration rather than a rewrite. Order set
by review; see [`FINDINGS.md`](FINDINGS.md) §5 for why a unit is a rollup.

🔴 **Starts after MVP-1, and the reason is `department`.** A unit is defined by department,
and `department` is now MEASURED as unreliable: 726 CUPE documents state a department the
Bank does not hold (§9, P3b). That is no longer a precaution — a VPFA rollup built on this
column today would be wrong, and wrong confidently. The alias/org-tree work is people-work
and can begin now; the BUILD waits on P3d.

| # | unit | blocked on |
|---|---|---|
| **E1** | **VPFA** (Finance & Administration) — **ITS rolls up into it** | the org tree + curated alias map |
| **E2** | **Facilities Services** | same, plus a boundary call (is Campus Security in it?) |

⚠ **Do not seed the tree or the aliases by inference.** A wrong rollup hands a
vice-president a confident wrong number about their own portfolio.

---
---

# TRACK F — JD currency after publishing (**MVP-4**, designed)

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



# TRACK G — upload a JD into the Builder (**MVP-3**, designed)

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
| multipart intake | 🔴 VERIFIED 2026-08-29, and the failure mode is sharper than "it will not parse". `python-multipart` is **deliberately absent** — `routes/_forms.py` records why: on Starlette 1.3.x `Request.form()` asserts the module is importable *regardless of content type*, so the app hand-parses with `parse_qsl` to stay dependency-free. The CSRF dependency reads the body FIRST via `read_form_pairs`, which does `body.decode("utf-8")`; a multipart body carrying binary bytes raises `UnicodeDecodeError`, the CSRF check catches it, finds no token — and **an upload is refused with a 403**. It also buffers the whole file via `request.body()`. Settle this first. |
| PDF extraction | VERIFIED: `_EXTRACTORS` covers DOCX/DOC/RTF/TXT only, so PDF falls to `DocumentFormat.OTHER` with no backend at all. New dependency, and it must vendor into the **offline** image. |
| ⚠ an offline bundle re-cut | **Both fixes move `requirements*.txt`**, which per `deploy/README.md` is exactly when the bundle must be re-cut. Track G is NOT a code-only change, and Directive #1 makes that a delivery step, not an afterthought. |
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
| ~~⛔ **No further producer runs**~~ | **LIFTED 2026-08-29.** Its stated reason — "zero published JDs each" — is void under the owner ruling. The COST is unchanged and real (~44 hours for a full pass), so **scope the run**: `--only-undrafted`, `--only-template`, `--limit`. An unscoped pass still needs a reason. |
| ~~⛔ **`make bank-audit` is not progress**~~ | **LIFTED.** It measures draft FIDELITY — which is now half the measure, not a distraction from it. |

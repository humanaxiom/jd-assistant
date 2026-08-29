# Plan — JD currency after publishing: review / update / attestation

**Status: design only, no code.** Written 2026-08-28 while the base-system context is
loaded — the point of writing it now is §4 and §5: exactly what exists to reuse, and
exactly what must be added, verified against the live schema rather than remembered.
**Sequenced after the Facilities filter (Track E2).**

**The problem it solves:** publishing is currently the end of a JD's life in the Bank.
Nothing tracks whether a published JD still describes the job — no owner, no review date,
no re-validation. Today that is invisible (few published); at the pilot's target (20 →
100) it becomes the pile of stale JDs this whole project exists to replace.

---

## 1. What "current" means — three measurable axes, one deferred

A published JD goes stale in distinguishable ways, and they need separate treatment:

| axis | detected by | treatment |
|---|---|---|
| **A. Time** — nobody has looked at it since publication | last attestation (or approval) date vs a cadence | the attestation loop (§2) |
| **B. Rulebook drift** — published under an older `rules_version`; the standards moved | compare the stamp already in `change_log->validator->rules_version` against the live rulebook; optionally re-run the validator (advisory) | shown as a flag on the attestation packet, **never blocks, never unpublishes** |
| **C. Source drift** — the archive gained new documents that cluster with this role after it was published | new member documents newer than the publish date | shown on the packet: *"the world has produced N newer descriptions of this job"* |
| **D. Org/incumbent drift** — the job changed in HRIS, reporting lines moved | ⛔ needs HRIS data we do not ingest | **deferred**, recorded here so it is a decision and not an omission |

⚠ **Stale is advisory on every axis.** NN #1 says nothing auto-publishes; the mirror rule
here is **nothing auto-un-publishes**. A stale flag changes what a steward is shown, never
the JD's status.

## 2. The core loop

```
published JD ──(due by cadence, or flagged by B/C)──▶ CURRENCY QUEUE
                                                          │ steward opens packet
                                                          ▼
                        ┌────────────── one of three verdicts ──────────────┐
                        ▼                        ▼                          ▼
                   REAFFIRM                   REVISE                     RETIRE
              "still describes the      "needs changes" — mints     "job no longer
               job" — an attestation     a DRAFT via the EXISTING    exists" — NEW
               row, nothing else         edit path; prior version    action; PUBLISHED
               changes                   stays published until the   → ARCHIVED with a
                                         replacement is approved     written reason
```

- **REAFFIRM** writes an append-only attestation row and resets the clock. It never
  touches content, so it needs no gate run.
- **REVISE** is **not new machinery**: it is the existing edit-published path (edit mints
  a new DRAFT; approval supersedes with `FOR UPDATE` + `review.superseded`). The
  attestation row records the verdict and links the minted draft.
- **RETIRE** is the one genuinely new lifecycle transition (§5.2).

## 3. Who attests — stewardship

Every published JD needs an **owner** or the queue has no addressee. Verified: nothing in
the schema holds one today (`review_actions.reviewer_id` records who *acted*, not who is
*responsible*).

- **Default steward = the approver** (derivable from the APPROVE row today, zero new
  data). Honest and wrong-ish: approvers are HR reviewers, not the hiring unit.
- **Real steward = the unit**, which lands on the org rollup (Track E). A steward
  assignment by department string inherits the 72.2% coverage and the fragmentation —
  **coverage before use** applies to steward signals exactly as it did to membership.
- ⚠ **The steward panel must publish its own blind spot**: *"N published JDs have no
  steward"* is a first-class number, not a footnote. A queue that silently omits
  unowned JDs is the unfalsifiable-filter failure again.

## 4. What already exists and is REUSED — verified against the live system 2026-08-28

| need | already exists | verified how |
|---|---|---|
| publish lifecycle + supersession | `approve` supersedes under `FOR UPDATE`, one live PUBLISHED per cluster, `review.superseded` audit row | CLAUDE.md NN #1 + `review/service.py` |
| publish timestamp | derivable: the APPROVE row in `review_actions` (`created_at`) | queried; 5 APPROVE rows exist |
| rulebook-drift detection (axis B) | **`rules_version` already stamped** in `change_log->validator` on **all 2,493 current drafts incl. every published one** | queried |
| re-validation for the packet | validator is deterministic and rulebook-driven; can re-run against current rules on demand | NN #3/#4 |
| source-drift detection (axis C) | cluster membership + dedup edges; "member documents newer than publish date" is a query | the funnel/gap machinery |
| unit-scoped queues | the `Scope` seam — a currency queue takes a scope like every other surface | Track A4/A5 |
| audit trail | append-only `audit_log` + `audit_chain_tail` | schema |
| queue UI pattern | review queue + candidate queue templates | routes/templates |
| auth + roles | CAS, `reviewer_or_admin`, authorization matrix test forces a decision per route | `test_authorization_matrix.py` |

**Explicitly not needed:** a `published_at` column (derive it), a rules-version column
(stamped already), any change to scoring/clustering, any new vector work.

## 5. What is genuinely NEW — the capture-now list

### 5.1 `attestations` table (append-only)

```
attestations
  id                uuid PK
  cluster_id        uuid FK clusters      -- the role
  canonical_jd_id   uuid FK canonical_jds -- the EXACT published version attested
  verdict           enum: REAFFIRM | REVISE | RETIRE
  attested_by       varchar(128)          -- CAS user, like review_actions.reviewer_id
  as_steward        bool                  -- acted as assigned steward vs reviewer/admin
  rules_version_seen varchar(64)          -- live rulebook AT attestation time
  revalidation      jsonb                 -- advisory re-run result shown in the packet
  note              text                  -- required for REVISE and RETIRE, like reasons
  created_at        timestamptz
```

- Append-only like `review_actions`; a correction is a new row.
- ⚠ **`next_due` is DERIVED, never stored** — last attestation (else approval) +
  cadence. Storing it would rot the moment HR changes the cadence, and a stored-vs-derived
  mismatch is exactly the two-sources-of-truth failure. Same reasoning as resolving
  family membership live instead of freezing cluster ids.
- ⚠ **"Never attested" must render as its own bucket** — it is a state, not an old date.
  No sentinel dates (the `Untitled Position` lesson: a placeholder that looks like data
  defeats every "is it missing?" query anyone will write).

### 5.2 The RETIRE transition

Verified: `reviewactionkind` = APPROVE/REJECT/EDIT/OVERRIDE — **no retire**, and ARCHIVED
is reachable only by supersession. Retiring a role whose job ceased to exist currently
has no path at all.

- New review action `RETIRE`: PUBLISHED → ARCHIVED, **written reason required**, audit row
  (`review.retired`), same service and locking discipline as approve/supersede.
- Stays consistent with `802bff0`: ARCHIVED remains settled and un-editable. Un-retiring
  = the normal path (new draft, review, approve).
- 🔴 **Reviewer-gated like approve.** Retirement removes a published JD from circulation —
  it is the destructive direction, and a steward alone must not do it: steward files the
  RETIRE verdict, a reviewer confirms. (Mirror of "approval requires a human".)

### 5.3 `stewards` assignment

```
role_stewards: cluster_id FK · steward (CAS user) · assigned_by · assigned_at · note
```
Append-only history or current-row-with-audit — decide at build. **Blocked on nothing for
the approver-default; blocked on Track E org data for unit stewardship.**

### 5.4 `currency.yaml` — rulebook data, registered in the same PR

New rule file, unhashed (decides what a steward is shown/when — never how a JD scores),
flat, every knob on the decision surface. All entries ship `open`:

| knob | note |
|---|---|
| `cadence_months` per form | ⚠ **an HR policy, not ours to invent** — ship a default, register it open, and do not defend the number. CUPE JDs may have a collective-agreement answer; ask. |
| `grace_months` | overdue vs due-soon boundary |
| `who_may_attest` | steward only / any reviewer / either |
| `retire_requires_reviewer` | shipped `true`; registered so loosening it is HR's signature, not an edit |
| `revalidate_on_attest` | advisory re-run on/off |

### 5.5 Surfaces

- **Currency queue** `/jd-bank/ui/currency?scope=` — due/overdue/never-attested, scoped,
  each row carrying WHY it surfaced (cadence / rules drift / source drift — evidence
  shown, like the candidate queue's match counts).
- **Attestation packet** — the published JD + axis-B advisory revalidation + axis-C newer
  documents + attestation history. Three buttons, reason box.
- **Currency panel on the funnel page** — published N · with steward N (coverage %) ·
  current N · due N · overdue N · never-attested N, **buckets summing to published,
  units labelled**. Extend `make smoke`: currency buckets must sum to the published count.

## 6. Non-negotiables, applied

1. **NN #1** — attestation never publishes or unpublishes; REVISE rides the existing
   draft path; RETIRE requires a reviewer and a written reason; overrides logged.
2. **NN #2** — cadence and every knob in `currency.yaml`, registered, `open`.
3. **NN #3** — the packet's re-validation is the deterministic validator against current
   rules; advisory only.
4. **NN #6** — attestations are provenance: append-only, chained into the audit trail.
5. **Session lessons baked in:** derived-not-stored due dates; never-attested as a state;
   every panel reports its blind spot (stewardless count); buckets sum or the page says
   it is broken; no invented thresholds — cadence is HR's; coverage-before-use for any
   steward signal; smoke extended with the new invariant.

## 7. Sequencing and dependencies

1. **After Track E2 (Facilities)** — per direction. Nothing here blocks E1/E2.
2. **Worth building only alongside B2** — with 4 published JDs a currency loop is
   ceremony; the pilot's 20 make it real. Natural order: pilot produces publishes →
   currency loop starts on them. **The pilot's reviewer is also the first steward
   candidate — capture their reaction to that role in the pilot's written objections.**
3. Steward-by-unit lands after the org rollup exists (E1/E2's tree).
4. ⚠ BGL-1 note: attestation is another surface that puts named users on
   `sfuai.ca:7000`. Blocks nothing (decided); listed for the before-going-live sweep.

## 8. Open questions — HR's, not ours

- Cadence per form (any collective-agreement requirement for CUPE?)
- Who may attest — and may a steward attest their **own** approval?
- Is REAFFIRM an *attestation* in the formal/legal sense (wording matters; footer rule)?
- Does an OVERRIDE-published JD (2 exist) get a shorter first cadence?
- Retention: attestation history is provenance — presumably forever, confirm.

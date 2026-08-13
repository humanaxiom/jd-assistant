# SFU site coverage vs. repo implementation gap analysis

## Executive summary

The SFU HR job-description ecosystem is broader than the current JD Assistant implementation. The repo is strongest on the JDFN / APSA / APEX / Poly authoring and archive-analysis flow, but the official SFU site also covers CUPE / WJQ forms, Hay evaluation, compensation workflows, and re-evaluation processes that are not currently represented as first-class product capabilities.

The important nuance is that the repo is not missing the core JD Bank pipeline. It is missing the full SFU JD lifecycle. The current implementation is a transparent, rulebook-driven JD Bank for JDFN roles, with parse-only support for WJQ and advisory Hay signals rather than a formal compensation workflow.

---

## 1) Scope of the official SFU site

The SFU resources reviewed include:

- Job Description Template
- Job Description Toolkit
- Job Description Database Cheat Sheet
- Hay Job Evaluation Method
- Job Analysis Questionnaire (JAQ)
- CUPE / WJQ forms and re-evaluation resources
- compensation and job-change related forms

That broad set goes beyond the repo’s current product footprint.

---

## 2) What the repo actually implements well

### 2.1 JDFN authoring and validation
The project is clearly built around the JDFN authoring path.

Evidence in the repo:

- [docs/OPERATOR-GUIDE.md](../docs/OPERATOR-GUIDE.md#L152-L155)
- [core/src/api/routes/compose_ui.py](../core/src/api/routes/compose_ui.py#L539-L547)
- [core/src/jd_core/rules/gates.yaml](../core/src/jd_core/rules/gates.yaml)
- [core/src/jd_core/rules/scoring.yaml](../core/src/jd_core/rules/scoring.yaml)

This includes:

- structured JD drafting
- policy-based validation
- score and grade logic
- review queue and approval state
- duplicate / near-duplicate detection
- harmonization into a canonical draft

This is the project’s strongest and most mature surface.

### 2.2 Rulebook-as-data governance
The repo explicitly treats the rulebook as the source of truth.

Relevant files:

- [core/src/jd_core/rules/gates.yaml](../core/src/jd_core/rules/gates.yaml)
- [core/src/jd_core/rules/decision_register.yaml](../core/src/jd_core/rules/decision_register.yaml)
- [core/src/jd_core/rules/scoring.yaml](../core/src/jd_core/rules/scoring.yaml)
- [core/src/jd_core/rules/dedup.yaml](../core/src/jd_core/rules/dedup.yaml)
- [core/src/jd_core/rules/comparison.yaml](../core/src/jd_core/rules/comparison.yaml)

This is a major strength: thresholds, severities, and gate logic are explicit and inspectable rather than hidden in prose or one-off model behavior.

### 2.3 Duplicate detection and harmonization
The “JD bank” side of the repo is designed to group and compare role variants.

This includes:

- exact and near-duplicate detection
- similarity scoring
- cluster formation
- canonical draft generation
- reviewer workflow for approve / reject / request edits

This is a solid implementation for the archive and role-bank problem space.

---

## 3) The clearest gap: CUPE / WJQ is not implemented as an authoring path

The most obvious gap relative to the SFU site is CUPE / WJQ support.

The repo explicitly says the Builder authors JDFN roles only and that CUPE roles are deliberately excluded from authoring until there is a ratified quality bar.

Evidence:

- [docs/OPERATOR-GUIDE.md](../docs/OPERATOR-GUIDE.md#L152-L155)
- [core/src/api/routes/compose_ui.py](../core/src/api/routes/compose_ui.py#L539-L547)
- [core/src/jd_core/parser/wjq.py](../core/src/jd_core/parser/wjq.py#L1-L40)

This means:

- WJQ documents can be parsed for archive analysis
- WJQ content is recognized as a different template
- but the active authoring workflow is not available for CUPE/WJQ roles

This is a deliberate scope boundary, but it is still a missing product surface relative to the official SFU materials.

---

## 4) Hay evaluation is advisory, not a formal workflow

The site includes formal Hay evaluation materials, but the repo’s model explicitly avoids assigning a final Hay grade.

Evidence:

- [core/src/jd_core/models/bank.py](../core/src/jd_core/models/bank.py#L35-L48)
- [core/src/jd_core/rules/hay_signals.yaml](../core/src/jd_core/rules/hay_signals.yaml)

The code comments make the logic clear:

- Hay signals are treated as calibration data
- SFU publishes no final Hay point chart in this repo context
- classification is a human Compensation decision
- the system deliberately does not represent a final Hay grade in the model

This is a defensible design choice, but it means the repo is not yet a complete Hay evaluation system in the way the SFU site presents it.

### Why this matters

The repo supports “advisory signal generation,” but not a real compensation-decision workflow.

In practice, that means:

- a job can be evaluated for similarity and structure
- it can receive approximate Hay-related indicators
- but it cannot complete the formal SFU reclassification / compensation decision path in the current product surface

---

## 5) Compensation and re-evaluation workflows are absent

The SFU site includes additional operational resources such as:

- Compensation Requisition forms
- Re-evaluation Request forms
- job-change / reorganization flows
- compensation decision support materials

The repo does not appear to include a product workflow for any of these.

### Missing flows include

1. Compensation requisition tracking
2. Re-evaluation initiation and approval
3. Formal job change impact assessment
4. Compensation decision record tied to JD edit history
5. Review queue for HR compensation action, not just JD quality review

This is not a validator issue; it is a workflow coverage issue.

---

## 6) The repo is currently a JDFN-first system, not a full SFU JD platform

The cleanest framing is:

- implemented: JDFN JD authoring, validation, scoring, review, deduplication, harmonization
- implemented parse-only: WJQ archive analysis
- advisory only: Hay signals
- not implemented: formal compensation workflow, re-evaluation lifecycle, full CUPE/WJQ authoring support

That matches the repo’s design intent and the policy boundary described in the project docs.

---

## 7) Recommended gap classification

### Implemented

- JDFN template parsing
- validation gates and score logic
- review approval workflow
- archive deduplication and near-duplicate detection
- canonical harmonization for related JDs

### Parse-only / partial

- WJQ support
- Hay calibration signal generation

### Not implemented

- CUPE/WJQ authoring workflow
- compensation requisition flow
- re-evaluation request flow
- formal Hay-grade assignment
- full SFU compensation ecosystem support

---

## 8) Prioritized backlog

The gaps above can be turned into a concrete product backlog. The priorities below reflect both business value and implementation risk.

### P0 — Must define the product boundary and HR policy before expanding scope

#### 1. Formalize the approved scope statement for CUPE/WJQ
- Goal: decide whether CUPE/WJQ is in or out for the current product.
- Why this is first: it determines whether the Builder should remain JDFN-only or expand into a second authoring track.
- Deliverables:
  - explicit authoring policy for CUPE/WJQ
  - rulebook decision and approval status
  - user-visible scope statement in product docs
- Exit criteria:
  - clear statement of what is in-scope and what is intentionally excluded

#### 2. Clarify the HR decision boundary for Hay evaluation
- Goal: determine whether Hay scoring is an advisory tool, a formal workflow, or a future feature.
- Why this is first: it affects model contracts, role metadata, and UI expectations.
- Deliverables:
  - rulebook decision on whether final Hay grades are allowed
  - separation of advisory signals from formal compensation decisions
- Exit criteria:
  - repo behavior matches the approved HR process model

### P1 — Enable expansion beyond the current JDFN-first implementation

#### 3. Add CUPE/WJQ authoring support behind a ratified quality bar
- Goal: support the second SFU template family in the authoring layer.
- Why this is next: it is the most obvious missing capability relative to the SFU site.
- Deliverables:
  - WJQ parsing and validation rules aligned with HR requirements
  - authoring UI / form flow comparable to JDFN
  - approval gates and reviewer checks for CUPE/WJQ roles
- Exit criteria:
  - a CUPE/WJQ role can be authored and reviewed using the same governance model as JDFN

#### 4. Add a formal Hay evaluation workflow that is clearly non-binding until HR ratifies it
- Goal: provide an explicit evaluation assistant without conflating it with final compensation decisions.
- Why this is next: the site clearly exposes Hay as part of the official HR process.
- Deliverables:
  - evaluation questionnaire / JAQ path
  - score breakdown by Hay factors
  - visible distinction between advisory output and official HR decision
- Exit criteria:
  - users can generate a reviewable Hay evaluation record without claiming final HR authority

#### 5. Add re-evaluation request management
- Goal: support the formal process for re-reviewing a role after a job-change or updated template.
- Why this matters: the official SFU process includes re-evaluation flows and forms.
- Deliverables:
  - request intake
  - reason / evidence capture
  - review and decision record
- Exit criteria:
  - a re-evaluation request can be created, reviewed, and resolved within the system

### P2 — Strengthen the end-to-end operational workflow for broader HR coverage

#### 6. Add compensation requisition workflow
- Goal: support the operational transaction that follows job evaluation and classification.
- Why this is second-tier: it is beyond the core JD-quality engine and depends on HR policy and workflow design.
- Deliverables:
  - compensation request data model
  - approval path
  - linkage to JD version and review record
- Exit criteria:
  - requisition status is tracked and tied to the job description record

#### 7. Add job-change and reorganization impact tracking
- Goal: make it possible to record how a role changed and what impact led to a compensation or re-evaluation decision.
- Why this matters: the SFU site references these as formal process aids.
- Deliverables:
  - impact review fields
  - role comparison before/after change
  - approval trail
- Exit criteria:
  - HR can review role changes with context and evidence

#### 8. Add a compensation decision audit trail tied to JD version history
- Goal: make compensation decisions reviewable and auditable.
- Why this matters: auditability is crucial for any HR process that influences pay or classification.
- Deliverables:
  - JD version snapshots
  - decision records
  - override and reviewer rationale storage
- Exit criteria:
  - every compensation decision can be traced to a specific JD version and reviewer action

### P3 — Future-facing product evolution

#### 9. Broaden the system from “JD bank” to “full SFU HR lifecycle platform”
- Goal: connect JD authoring, validation, evaluation, compensation, and re-evaluation into one workflow.
- Why this is later: it requires a multi-stage rollout and clear operational policy.
- Deliverables:
  - product architecture for end-to-end HR workflows
  - permissions and role model
  - reporting and audit views
- Exit criteria:
  - a single consistent lifecycle from claim to approval to compensation action exists

---

## 9) Bottom line

The implementation is not incomplete in the JDFN path; it is intentionally narrower than the SFU HR ecosystem as a whole.

The priority order is clear:

1. lock the policy boundaries for CUPE/WJQ and Hay evaluation
2. expand the authoring and evaluation surface where HR has a ratified rulebook
3. add re-evaluation and compensation workflows only after the policy boundary is explicit
4. evolve into a broader HR lifecycle platform later, not as the immediate product scope

This is the practical backlog for closing the current gap between the repo’s JDFN-first implementation and the broader SFU official process set.

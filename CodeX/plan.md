# Seven High-Value Improvements

This plan preserves the system’s deterministic, human-governed centre. Priorities are ordered by risk reduction and value, not implementation convenience. No implementation changes were made as part of this analysis.

## 1. Complete authorization and create a production safety profile

Value: closes the most serious security boundary and makes role/audit claims true across UI and API.

Scope:

- Require authenticated identity on every HR, compose, legacy harness, gate-running, task, lineage, and memory endpoint.
- Derive actor/reviewer identity from the session; remove trust in body-supplied actor fields.
- Define endpoint-by-endpoint author/reviewer/admin/operator permissions and prevent self-approval if HR requires segregation of duties.
- Add CSRF protection for cookie-authenticated state changes.
- Add an explicit production mode that refuses startup unless CAS, secure cookies, trusted proxy/origin, non-default secrets, least-privilege database roles, and approved inference configuration are present.
- Split liveness from dependency readiness and add safe production Compose/deployment overlays.

Success measures:

- Automated authorization matrix covers every route and method.
- No state-changing request can choose its own actor identity.
- Production misconfiguration fails closed.
- Security review confirms CSRF/session/role boundaries.

Dependencies/approvals: HR segregation-of-duties policy; identity/security architecture approval.

## 2. Turn the open decision register into an HR ratification workflow

Value: converts technically enforced defaults into legitimate, traceable HR policy.

Scope:

- Bundle the 197 open decisions into approval packages: bar/scoring, template, qualifications, inclusive language, titles/classification signals, similarity, harmonization, AI, review governance, scope, and evidence.
- Assign owner, status, due date, rationale, evidence, impact simulation, and effective version.
- Provide before/after corpus results for every material threshold or lexicon change.
- Stamp each canonical decision with the effective ratified policy version.
- Support periodic review, supersession, and explicit deferral rather than treating silence as approval.

Success measures:

- No production policy value lacks an HR owner and disposition.
- The UI distinguishes provisional from ratified results.
- Every change links to measured impact and approver identity/date/reason.

Dependencies/approvals: HR policy owners, labour relations, classification/compensation, EDI/legal, privacy as applicable.

## 3. Build an HR-adjudicated benchmark and continuous calibration program

Value: tests whether the system is useful and fair, not merely internally consistent.

Scope:

- Create a de-identified, versioned benchmark stratified by employee group, family, department, era, seniority, and document quality.
- Collect independent judgments from multiple experienced reviewers and measure inter-rater agreement.
- Measure per-rule precision/recall, false blocks, missed issues, edit time, override rate, and disagreement reasons.
- Evaluate outcomes across relevant groups and templates for disparate impact.
- Add acceptance thresholds and regression tolerances for deterministic rules and bounded AI assistance.
- Run scheduled internal model/prompt canaries where live inference is reachable; do not silently skip reachability failure.

Success measures:

- HR approves benchmark composition and labels.
- Every blocking gate has measured performance.
- Releases report overall and sliced regression results.
- Pilot disagreements become ratified regression cases.

Dependencies/approvals: reviewer panel, privacy/de-identification rules, acceptable error/fairness thresholds.

## 4. Introduce a durable, observable pipeline-run ledger and transactional outbox

Value: replaces fragile operator choreography with repeatable, resumable, supportable processing.

Scope:

- Model each archive run and stage with inputs, complete version manifest, status, counts, errors, checkpoints, timestamps, and actor.
- Encode stage prerequisites and idempotency instead of relying on Makefile knowledge and comments.
- Use a transactional outbox for database-to-Redis dispatch and idempotent job keys.
- Add retry/resume/cancel controls, partial-failure semantics, and safe reconciliation for stranded work.
- Surface run progress, artifact freshness, deterministic fallback, LLM failure, and current data-through date in an operator UI.
- Add metrics for queue depth/age, stage throughput, errors, model latency/fallback, and review cycle time.

Success measures:

- A failed run resumes without duplicate authoritative records.
- No committed task can be silently lost before enqueue.
- Operators can answer what ran, with what versions, when, and why it failed.
- Alerts cover stale queues, broken dependencies, and audit-chain failures.

Dependencies/approvals: operational ownership, SLOs, retention for run logs and metrics.

## 5. Fix corpus/version correctness, especially WJQ and source lifecycle

Value: prevents misleading clusters, double counting, stale parses, and unsupported policy conclusions.

Scope:

- Add extractor version to parse identity and all downstream manifests.
- Model a stable logical source identity with versions, current/superseded state, and tombstones.
- Improve WJQ identification/title extraction and remove template scaffolding before retrieval or clustering.
- Keep WJQ evaluation/harmonization blocked until HR defines a distinct standard.
- Persist exact duplicate relationships or establish one authoritative computed relation used everywhere.
- Define and test a lossless canonical serialization contract before relying on export/re-import loops.

Success measures:

- Extractor changes deterministically invalidate affected derived records.
- Current corpus counts cannot double-count changed paths.
- WJQ retrieval quality passes an HR-approved sample.
- Every cluster member and canonical source is reproducible from a complete manifest.

Dependencies/approvals: CUPE/WJQ scope and standard; records-retention/source-version policy.

## 6. Improve retrieval scalability and requirement-safe harmonization

Value: makes related-role discovery faster and prevents harmonization from silently raising job requirements.

Scope:

- Replace character truncation with tokenizer-aware section chunking and record coverage/truncation.
- Replace quadratic role-equivalence candidate enumeration with ANN/top-k candidates followed by deterministic scoring and vetoes.
- Enforce embedding model/stamp compatibility at query time.
- Show member coverage for every retained duty and qualification.
- Distinguish core, local, optional, and conflicting requirements.
- Require explicit reviewer approval when harmonization raises education, experience, security, seniority, or supervisory requirements above the modal/source baseline.
- Preserve dropped/conflicting context as reviewer-visible evidence.

Success measures:

- Candidate generation meets an agreed runtime while preserving benchmark recall.
- No empty or incompatible embedding query is admitted.
- Every raised requirement is visibly sourced and explicitly accepted.
- HR benchmark shows reduced requirement inflation and preserved essential content.

Dependencies/approvals: HR harmonization policy, classification/EDI review, retrieval quality target.

## 7. Close the author/reviewer feedback loop and harden service operations

Value: fixes immediate usability gaps and turns real review behavior into governed improvement evidence.

Scope:

- Add author-visible submission confirmation, “My drafts/submissions,” status/history, and notifications; remove the current reviewer-page 403 after submit.
- Add review-queue search, filters, pagination, assignment/SLA indicators, action confirmations, and success receipts.
- Capture structured reason categories plus free text for edit/reject/override while preserving the original record.
- Create dashboards by gate, family, group, reviewer agreement, override, edit, and cycle time.
- Improve WCAG 2.2 AA semantics, keyboard/focus behavior, responsive layouts, plain language, and user testing.
- Harden audit with least-privilege immutable storage controls, verification/alerting, external anchoring, backups, restore drills, and retention policies.
- Separate/isolate Neo4j workloads and add dependency readiness, correlation IDs, logs, metrics, and documented incident procedures.

Success measures:

- Authors can track every submission without reviewer access.
- Reviewers can triage the pilot workload and receive unambiguous action receipts.
- Accessibility audit meets the approved standard.
- Backup restore and audit verification drills pass.
- Policy-change proposals are based on structured trends and require ratification before rules change.

Dependencies/approvals: accessibility standard, notification channel, review SLA, retention/privacy/security controls.

## Suggested delivery order

```text
Foundation: 1 Authorization + production safety
Governance: 2 Ratification + 3 benchmark
Operations: 4 pipeline ledger/outbox
Correctness: 5 corpus/version model
Quality/scale: 6 retrieval and harmonization
Adoption: 7 feedback loop, UX, accessibility, resilience
```

Workstreams 2 and 3 should begin immediately alongside improvement 1: they depend more on HR participation than code. Improvement 4 should precede any large reprocessing campaign. WJQ should remain explicitly out of evaluation scope until improvement 5 and an HR-approved CUPE standard are complete.


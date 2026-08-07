# JD Assistant HR Demonstration Script

Suggested length: 35–45 minutes plus discussion.  
Audience: HR policy owners, experienced JD reviewers, HR systems/privacy representatives, and pilot users.

## Demonstration objective

Show how JD Assistant helps people find, draft, assess, harmonize, and govern job descriptions while preserving HR authority. The demonstration should prove three points:

1. The tool explains its evidence; it does not silently decide.
2. Deterministic rules and human review—not the LLM—control publication.
3. Today’s policy settings are pilot defaults awaiting HR approval.

## Presenter preparation

- Start the stack and confirm sign-in, Library, Builder, Review queue, and dashboards load.
- Use one author account and one reviewer/admin account, or clearly narrate the role switch.
- Preselect one published harmonized role, one draft with a waivable blocker, one draft with a non-waivable blocker, and one draft with a prior published version.
- Avoid presenting whole-archive approval rate as a quality headline; historical formats and WJQ make that cohort misleading.
- State the artifact date and corpus/rules version shown by the system.
- Do not claim CUPE/WJQ evaluation, formal job classification, HRIS publication, or externally validated fairness.

## Opening narrative (2 minutes)

> JD Assistant is a governed job-description bank. It helps authors reuse good work, checks drafts consistently, shows evidence and provenance, and gives reviewers a structured approval process. It never publishes a job description automatically. The AI can help rewrite or flag nuance, but the deterministic rule engine and an accountable HR reviewer remain in control.

Show this workflow:

```text
Find or create -> Check -> Submit draft -> HR review -> Edit/override/reject -> Publish
                                      ^
                 evidence, provenance, and reasons retained throughout
```

Call out the current status:

- The repository’s decision register contains 197 open policy decisions and no ratified decisions.
- The current canonical bank has roughly 1,802 roles, but only 4 published roles; this is pilot evidence, not rollout completion.
- CUPE/WJQ is searchable but deliberately outside the current quality/authoring policy.

## Demo 1: Evidence dashboards (5 minutes)

1. Open **Dashboards**.
2. Show the current-practice baseline rather than the blended historical archive.
3. Explain the measured result: most current-practice documents clear the proposed bar; the dominant blocker is the summary length rule, not the numeric score.
4. Open the dedup and cluster views. Explain exact duplicate, near duplicate, and role-equivalent as progressively more interpretive evidence.
5. Point out that risky clusters are flagged for human review; the system does not automatically declare jobs equivalent.

Say:

> These are measurement artifacts, not live executive metrics. Every number needs a cohort date and rules version. Similarity ranks candidates; it is not a legal, classification, or bargaining-unit determination.

Discussion flag — HR approval required:

- What cohort may be used for official reporting?
- What freshness/date banner and sign-off must accompany metrics?
- What false-positive/false-negative tolerance is acceptable for quality and related-role findings?

## Demo 2: Search the role library and inspect provenance (5 minutes)

1. Open **Library**.
2. Search for a familiar position title.
3. Open a harmonized role.
4. Show status, version, quality summary, source documents, and provenance.
5. Open one source JD to contrast the historical source with the harmonized role.
6. Select **Start a new JD from this harmonized role**.

Say:

> The Bank keeps the difference between evidence and authority clear. Historical sources remain traceable. A harmonized role is a controlled draft or published bank entry; it does not erase its sources.

Discussion flag — HR approval required:

- Who may see raw source JDs, rejected versions, removed content, and reviewer reasons?
- How long should each artifact be retained?
- When cross-department or cross-employee-group sources appear together, what mandatory review is required?

## Demo 3: Guided authoring and compliance check (10 minutes)

1. In **Builder**, explain the structured sections: identity, About SFU/boilerplate, position summary, duties and allocations, decision-making, problem-solving, relationships, qualifications, and working context.
2. Change the cloned content or create a small sample duty.
3. Select **Check compliance**.
4. Walk through:
   - section completion;
   - findings with evidence and severity;
   - score and grade;
   - blocking gates and whether each is waivable;
   - advisory related roles/duplicate warnings.
5. If available, use summary assistance. Show that the suggestion is editable and is rechecked after acceptance.
6. Export a DOCX and state that export does not publish.
7. Submit the draft and explain that submission creates `DRAFT` only.

Say:

> The same input produces the same deterministic result. The LLM may suggest prose or flag nuance, but it cannot make the approval decision. Related-role results are suggestions to investigate, not confidence percentages or automatic merges.

Note for the live demo: the current submit redirect sends an author to a reviewer-only page and may produce a 403. Until corrected, switch to the reviewer account or navigate directly to the review queue; describe this honestly as a known pilot UX defect.

Discussion flag — HR approval required:

- Ratify or change the 100–150 word summary policy, especially the hard upper bound.
- Confirm duty count/allocation expectations.
- Approve exact official boilerplate and whether the system inserts it automatically.
- Approve qualification equivalency variants and the wish-list phrase list.
- Approve inclusive-language terms, contextual exceptions, and replacement guidance.
- Decide whether authors may use generated summaries and what disclosure/review is required.
- Confirm whether duplicate warnings remain advisory.

## Demo 4: Explain the core evaluation process (6 minutes)

Use this plain-language sequence:

### A. Structure and evidence

The parser/Builder converts the JD into known sections. Deterministic checks inspect required content, summary length, duties, allocations, qualifications, titles, language, working conditions, and required boilerplate. Each finding carries a rule identifier and evidence.

### B. Score and grade

The score begins at 100. Findings subtract severity-weighted points, with diminishing deductions for repeated findings in the same severity tier. The current defaults are high 20, medium 10, low 5, informational 0; grade bands are A at 90, B at 75, C at 60, D at 40, then F.

### C. Approval gates

Gates are separate from the score. They evaluate named hard-stop findings and the current score/grade/severity floors. This is why a document can have a reasonable score but still be blocked by a specific policy rule. Some gates may be waived with a written reason; missing core sections and selected placeholder rules are currently non-waivable.

### D. AI assistance

The optional rewrite follows the deterministic merge and is checked against source grounding. If it fails, the deterministic draft remains available. The optional AI audit can flag nuance, but its findings do not change score or approval.

### E. Fresh review decision

When a reviewer opens or approves a draft, the current content is evaluated again. Stored scores are display summaries, not authority. Approval succeeds only if all remaining blockers are cleared or validly overridden.

Say:

> A score is a summary of findings, not the final policy decision. The gates say why publication is blocked. HR must approve both the scoring model and the gate policy before either is called official.

Discussion flag — HR approval required:

- Are score and letter grade useful, or do they obscure the clearer gate explanation?
- Ratify score 60, grade C, and maximum-high severity floors, or replace them.
- Decide which gates can never be waived, which roles can waive, and what constitutes an adequate reason.
- Confirm the score is not used as a performance, compensation, classification, or employee-evaluation measure.

## Demo 5: Reviewer decision and version control (8 minutes)

1. Sign in as a reviewer and open **Review queue**.
2. Explain that blocked/unknown drafts are shown before readily approvable ones.
3. Open a draft and show current score/grade, blocking gates, issues, rendered content, and content removed during harmonization.
4. Open **Changes since last approved version** for a versioned role.
5. Demonstrate an edit. Explain that it creates a new draft and does not mutate the approved record.
6. Demonstrate rejection and its mandatory reason.
7. Demonstrate an eligible override with a specific reason.
8. Approve an approvable draft. Explain that approval is the sole publication path and supersedes the prior published version only at that point.

Say:

> Review is an accountable decision, not a button press. The system records who acted, what changed, what rule was waived, and why. The previously approved JD stays live while its replacement is being reviewed.

Discussion flag — HR approval required:

- May authors approve their own drafts, or is segregation of duties required?
- Who owns final grade/classification entry?
- What review SLA, secondary review, or sampling is required?
- What does “published” authorize downstream, and when may HRIS consume it?
- What override/rejection trends should trigger policy review?

## Demo 6: Administration, security, and audit (4 minutes)

1. Open **Users** as an administrator.
2. Show explicit reviewer/admin assignment and account disablement.
3. Explain SFU CAS sign-in, server-side sessions, internal inference, source provenance, canonical versioning, and the hash-chained audit trail.
4. Be precise: the hash chain is tamper-evident; production database privileges and external monitoring still need hardening.

Discussion flag — HR/privacy/security approval required:

- Is first sign-in provisioned as author by default?
- Who can grant reviewer/admin roles?
- What privacy classification, retention, backup, access review, and incident response applies?
- Is internal HTTP inference acceptable, or is TLS/mTLS required?
- What audit evidence must be exportable for review or investigation?

## Close and request decisions (3 minutes)

> The tool is ready to support a controlled HR pilot, but it should not be called policy-complete. We need HR to ratify the rules, conduct a representative adjudication exercise, and define operational authority. Every disagreement during the pilot is valuable: it should become a labeled case, a documented decision, and—only after approval—a regression test or rule change.

Ask HR to provide:

1. An owner and due date for each policy package.
2. Rulings on approval/gate/override rules.
3. Approved template and boilerplate wording.
4. Scope decision for CUPE/WJQ.
5. A representative reviewer panel and labeled pilot sample.
6. Roles, segregation-of-duties, privacy, retention, and HRIS authority decisions.
7. Acceptance thresholds for accuracy, consistency, fairness, accessibility, and usability.

## Suggested pilot exercise

- Select a stratified sample across employee group, job family, department, era, grade/seniority, and clean/problematic examples.
- Have at least two experienced reviewers independently judge each JD before seeing the tool result.
- Capture approve/reject, applicable blockers, severity, required edits, and confidence.
- Compare human agreement with tool findings, then discuss disagreements.
- Measure gate precision/recall, override rate, edit time, reviewer agreement, and differences across groups.
- Ratify or revise policy only after showing before/after archive impact.
- Promote every ratified disagreement into a permanent, de-identified regression case.


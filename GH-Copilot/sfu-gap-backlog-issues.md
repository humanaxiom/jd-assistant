# SFU gap backlog (GitHub-style issue list)

## Issue 1 — Define the official CUPE/WJQ scope boundary

**Priority:** P0  
**Status:** Open  
**Area:** Product scope / HR policy

### Problem
The repo currently treats the Builder as JDFN-only, while the official SFU job-description ecosystem also includes CUPE/WJQ processes and forms. The product decision on whether CUPE/WJQ belongs in the active authoring scope has not yet been made explicit.

### Evidence
- [docs/OPERATOR-GUIDE.md](../docs/OPERATOR-GUIDE.md#L152-L155)
- [core/src/api/routes/compose_ui.py](../core/src/api/routes/compose_ui.py#L539-L547)
- [core/src/jd_core/parser/wjq.py](../core/src/jd_core/parser/wjq.py#L1-L40)

### Acceptance criteria
- Product scope clearly states whether CUPE/WJQ is in or out of scope
- Authoring policy is documented and linked from product docs
- Engineering and HR reviewers agree on the boundary before expansion work starts

---

## Issue 2 — Confirm the HR policy for Hay evaluation and final grade authority

**Priority:** P0  
**Status:** Open  
**Area:** Policy / evaluation model

### Problem
The repo contains Hay calibration signals, but it intentionally avoids assigning a final Hay grade because that is treated as a human Compensation decision. The project needs a clear policy decision on whether Hay scoring is advisory only or can become a formal workflow.

### Evidence
- [core/src/jd_core/models/bank.py](../core/src/jd_core/models/bank.py#L35-L48)
- [core/src/jd_core/rules/hay_signals.yaml](../core/src/jd_core/rules/hay_signals.yaml)

### Acceptance criteria
- HR policy states whether Hay evaluation is advisory or formal
- Repo behavior matches the approved policy
- UI and rulebook terminology distinguish advisory signals from final HR authority

---

## Issue 3 — Add CUPE/WJQ authoring support behind a ratified quality bar

**Priority:** P1  
**Status:** Planned  
**Area:** Authoring workflow

### Problem
The SFU site includes CUPE/WJQ forms and questionnaires. The repo can parse WJQ documents, but does not support authoring them in the Builder workflow. This is the clearest feature gap versus the official site.

### Acceptance criteria
- WJQ form can be authored in the Builder
- Validation rules are specific to CUPE/WJQ requirements
- Review and approval flow exists for CUPE/WJQ roles
- JDFN and CUPE flows are clearly separated in UI and docs

---

## Issue 4 — Add a formal Hay evaluation workflow with explicit advisory labeling

**Priority:** P1  
**Status:** Planned  
**Area:** Evaluation / Compensation support

### Problem
The repo supports Hay-related calibration signals, but it has no user workflow for a formal evaluation record or factor breakdown. The official SFU site presents Hay evaluation as part of the HR process.

### Acceptance criteria
- User can generate a formal Hay evaluation record
- JAQ or factor breakdown is represented in the system
- All outputs clearly identify whether they are advisory or official HR decisions
- Review and audit trail is recorded

---

## Issue 5 — Add re-evaluation request management

**Priority:** P1  
**Status:** Planned  
**Area:** HR process workflow

### Problem
The official SFU process includes re-evaluation resources. The repo does not currently model a formal re-evaluation request lifecycle or decision record.

### Acceptance criteria
- Re-evaluation request can be created
- Reason and evidence are captured
- Assignee or reviewer can approve or reject the request
- Outcome is stored with audit trail

---

## Issue 6 — Add compensation requisition workflow

**Priority:** P2  
**Status:** Planned  
**Area:** Compensation operations

### Problem
The repo does not include a compensation requisition or related decision model, even though the SFU site includes compensation forms and job-change materials.

### Acceptance criteria
- Compensation request can be created and staged
- It links to the JD or role version being evaluated
- Approval path is documented and auditable
- Workflow supports role-change decisions with evidence

---

## Issue 7 — Add job-change and reorganization impact tracking

**Priority:** P2  
**Status:** Planned  
**Area:** HR operations / audit

### Problem
The official SFU ecosystem includes job-change and reorganization artifacts. The repo does not yet model the operational record of a role change and its business impact.

### Acceptance criteria
- Before/after role comparison is available
- Impact rationale is captured
- Decision record is linked to the JD change history
- Audit trail exists for reviewer decisions

---

## Issue 8 — Build a compensation decision audit trail tied to JD version history

**Priority:** P2  
**Status:** Planned  
**Area:** Auditability / governance

### Problem
Any formal compensation decision should be tied to the JD version in effect and to the reviewer or approver who made the call. The repo currently models JD validation and approval, but not a complete compensation audit trail.

### Acceptance criteria
- Every decision is linked to a specific JD version
- Reviewer rationale is stored
- Approval/override history is visible
- Audit log is retained for HR review

---

## Issue 9 — Evolve from JD Bank to full SFU HR lifecycle support

**Priority:** P3  
**Status:** Future  
**Area:** Product roadmap / architecture

### Problem
The repo is currently JDFN-first, but the broader SFU ecosystem spans authoring, validation, evaluation, re-evaluation, and compensation. A future-state vision should connect those workflows into one operational lifecycle.

### Acceptance criteria
- Lifecycle map includes JD authoring through compensation action
- Role permissions are modeled end-to-end
- Reporting and audit views exist for HR and administrators
- Scope is explicit for what remains advisory vs. official

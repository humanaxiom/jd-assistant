# HR Decision Request: Product Scope and Evaluation Authority for JD Bank

## Purpose

This memo requests HR guidance on two scope decisions that materially affect the JD Bank product direction and the rules used by the system.

The repository currently implements a JDFN-first JD authoring and review workflow, but the official SFU HR ecosystem includes additional templates, evaluation methods, and compensation processes that the project does not yet treat as first-class product capabilities.

The decisions requested below are intended to clarify the project boundary before further product expansion.

---

## Decision request 1: Confirm the authoring scope for CUPE/WJQ

### Background

The repo currently treats the Builder as operating on JDFN roles only. The project explicitly documents that CUPE roles are deliberately excluded from authoring because there is no ratified quality bar for the CUPE/WJQ process.

The SFU site, however, includes CUPE / WJQ forms, job questionnaire materials, and re-evaluation resources. That means the current repo scope is narrower than the broader SFU JD ecosystem.

### Decision needed

HR is requested to confirm one of the following:

1. The Builder should remain JDFN-only for the current product scope.
2. The Builder should expand to include CUPE/WJQ authoring and validation under a defined HR-approved quality bar.

### Why this matters

This decision directly affects:

- product scope and roadmap
- validation rules for the authoring workflow
- whether a second template family should be supported in the same way as JDFN
- user expectations for what the product is designed to do

### Proposed recommendation

If the product remains a JDFN-first system, the repo should explicitly document that CUPE/WJQ remains out of scope until a ratified quality bar is approved. If HR wants CUPE/WJQ support, the project should then formalize the required rulebook, validation gates, and reviewer process before release.

---

## Decision request 2: Confirm the authority boundary for Hay evaluation

### Background

The repo includes Hay calibration signals and related metadata, but it intentionally avoids assigning a final Hay grade because that is treated as a human Compensation decision. The project therefore treats Hay information as advisory rather than final authority.

The official SFU site presents Hay evaluation as part of the formal HR job-evaluation process, including method guidance and evaluation-support materials.

### Decision needed

HR is requested to confirm one of the following:

1. Hay evaluation is advisory only and should remain outside the repo’s formal decision authority.
2. Hay evaluation is a formal HR decision path that the product should eventually support with user workflows and audit capture.

### Why this matters

This decision affects:

- whether the repo can display Hay signals as a review assistant only
- whether a formal Hay evaluation workflow should be built
- how the product differentiates advisory output from final HR authority
- whether the system can support compensation-grade decisions without over-claiming authority

### Proposed recommendation

The safest product posture is to keep Hay output clearly advisory until HR confirms that a formal evaluation workflow is required and approved. This matches the current system architecture and avoids assigning final compensation authority to software that is designed to support review and evidence capture rather than replace human decisions.

---

## Decision request 3: Confirm whether compensation and re-evaluation workflows are in scope for the product

### Background

The official SFU site includes compensation resources, re-evaluation forms, and related HR operational processes. The current repo does not yet model these as product workflows.

The repo’s current implementation is focused on JD authoring, rulebook validation, archive deduplication, harmonization, and review approval.

### Decision needed

HR is requested to confirm whether the following are:

1. explicitly out of scope for this product phase, or
2. expected future product capabilities that should be planned in a staged roadmap.

The specific items are:

- compensation requisition workflow
- job-change / reorganization impact tracking
- re-evaluation request management
- compensation decision audit trail linked to JD version history

### Why this matters

These are operational HR workflows, not just JD quality checks. Without a clear decision, the system may be interpreted as broader than its actual maturity and legal / policy authority.

### Proposed recommendation

These workflows should be treated as staged future work unless HR explicitly says they are part of the approved product scope. The immediate product focus should remain on the JDFN review and approval journey, with explicit separation from compensation-grade workflows.

---

## Requested outcome

HR approval is requested on the following points:

1. Whether the Builder remains JDFN-only or expands into CUPE/WJQ authoring.
2. Whether Hay evaluation remains advisory or becomes a formal workflow.
3. Whether compensation and re-evaluation processes are out of scope for the current product phase or part of a planned future roadmap.

## Recommendation summary

The current repo should continue to operate as a JDFN-first JD Bank, with explicit documentation that:

- CUPE/WJQ is intentionally outside the active authoring workflow until an HR-approved quality bar is established;
- Hay outputs remain advisory unless HR authorizes a formal evaluation workflow;
- compensation and re-evaluation processes are treated as future roadmap work rather than current product scope.

This preserves product clarity, reduces over-claiming, and keeps the system aligned with the evidence-based rulebook and the documented review process.

---

## Decision status

This request is pending HR decision.

"""Live compliance for an in-progress JD draft (Phase 5.1).

:func:`assess_draft` is the JD Builder's compliance core. It renders the
structured draft to text, runs the **same deterministic validator the archive
baseline and the review queue use** (:func:`~src.jd_core.quality.
evaluate_jd_rules` → :func:`~src.jd_core.quality.build_report`), and regroups the
findings for a live authoring panel — distinguishing *what is still to write*
from *what is present but non-compliant*.

Three properties matter:

* **Validator-as-oracle (NN #3).** The score, grade and gate decision come
  straight from ``build_report``; this module computes none of them and fakes
  none of them. An unfinished draft is honestly *not approvable*
  (``report.gate_decision.approved is False``) — draft mode changes only how the
  findings are *presented*, never whether the JD may publish.
* **JDFN scope.** The validator defines a bar only for the APSA/APEX/POLY (JDFN)
  template (HR-143); the Builder authors JDFN JDs, and this assesses them under
  that bar.
* **Pure.** No I/O, no model call, no DB. Same draft → same assessment (but for
  the report's ``generated_at`` clock stamp, inherited from ``build_report``).

The draft-mode split is a presentation regrouping of ``report.checklist``, in the
same spirit as :func:`~src.jd_core.quality.checklist.build_checklist`: a finding
is *guidance* when it sits in a section the author has not filled in yet, and a
*finding* to fix otherwise. It introduces no threshold and no tunable — a
section's authored/empty state is a structural fact about the draft — so, like
``build_checklist``, it is not a registered decision.
"""

from __future__ import annotations

from uuid import UUID

from src.jd_bank.composer.models import (
    DraftAssessment,
    DraftSectionStatus,
    SectionState,
)
from src.jd_bank.jd_text import flatten_jd
from src.jd_core.models.parsed_jd import SFUJobDescription
from src.jd_core.models.quality import JDQualityIssue, SFUSection
from src.jd_core.quality import build_report, evaluate_jd_rules
from src.jd_core.rules import Rules, get_rules

#: A composer draft has not been persisted, so it has no ``job_id`` yet. The nil
#: UUID is the honest "unsaved draft" sentinel that ``build_report`` requires —
#: distinct from the archive baseline's per-file ``uuid5`` and from any real
#: ``canonical_jds`` row a submitted draft will later be given (Phase 5.6).
_UNSAVED_DRAFT: UUID = UUID(int=0)

#: What the report's ``model`` / ``prompt_version`` stamps say for a composer
#: live-check: no LLM ran, only the deterministic rulebook. Kept explicit rather
#: than blank, exactly as the archive baseline's ``DETERMINISTIC_ONLY`` is.
_DRAFT_DETERMINISTIC: str = "none (composer draft, deterministic rules only)"


def _section_authored(jd: SFUJobDescription, section: SFUSection) -> bool:
    """Has the author filled in ``section`` yet?

    Structural, not a policy: a list section is authored once it has an entry, a
    text section once it holds non-whitespace, a presence section once its
    boolean is set. ``identification`` keys off the (always-present, min-length-1)
    title. ``general`` is the cross-cutting finding bucket, not a section anyone
    authors, so it is treated as authored — its findings (placeholders, coded
    language) are always real, never "just unfinished".
    """
    if section == "identification":
        return bool(jd.title.strip())
    if section == "about_sfu":
        return jd.about_sfu_present
    if section == "position_summary":
        return bool((jd.position_summary or "").strip())
    if section == "duties":
        return bool(jd.duties)
    if section == "decision_making":
        return bool(jd.decision_making)
    if section == "problem_solving":
        return bool(jd.problem_solving)
    if section == "relationships":
        rel = jd.relationships
        return rel is not None and bool(
            (rel.supervisory or "").strip() or rel.internal or rel.external
        )
    if section == "qualifications":
        return bool(jd.qualifications)
    if section == "edi_footer":
        return jd.territorial_acknowledgement_present and jd.employment_equity_present
    if section == "additional_context":
        return bool((jd.additional_context or "").strip())
    # "general" (and any future non-template bucket): always "authored".
    return True


def assess_draft(
    jd: SFUJobDescription, *, rules: Rules | None = None
) -> DraftAssessment:
    """Run the deterministic rulebook over a draft and split findings for a live
    authoring panel. ``rules`` defaults to the shipped rulebook."""
    rulebook = rules if rules is not None else get_rules()
    # Flatten with the SAME flattener the review service re-validates a submitted
    # draft with (``flatten_jd`` — see review.service._recompute), so the live panel's
    # "ready for review" verdict matches what the reviewer sees once the draft reaches
    # the queue (5.6). A different serialization here could make a draft look approvable
    # in the Builder but blocked in the queue.
    text = flatten_jd(jd)
    issues = evaluate_jd_rules(jd, text, rules=rulebook)
    report = build_report(
        job_id=_UNSAVED_DRAFT,
        issues=issues,
        model=_DRAFT_DETERMINISTIC,
        prompt_version=_DRAFT_DETERMINISTIC,
        rules=rulebook,
    )

    sections: list[DraftSectionStatus] = []
    guidance: list[JDQualityIssue] = []
    findings: list[JDQualityIssue] = []
    for entry in report.checklist:
        authored = _section_authored(jd, entry.section)
        state: SectionState
        if entry.issues and not authored:
            # Unauthored AND the validator flagged its absence: still to write.
            # (An unauthored but OPTIONAL section — additional_context, say — raises
            # no finding, so it reads "ok", not a false "you left this blank" todo.)
            state = "empty"
            guidance.extend(entry.issues)
        elif entry.issues:
            state = "needs_attention"
            findings.extend(entry.issues)
        else:
            state = "ok"
        sections.append(
            DraftSectionStatus(
                section=entry.section,
                label=entry.label,
                state=state,
                issues=tuple(entry.issues),
            )
        )

    decision = report.gate_decision
    approvable = decision is not None and decision.approved
    return DraftAssessment(
        report=report,
        sections=sections,
        guidance=guidance,
        findings=findings,
        summary_word_count=len((jd.position_summary or "").split()),
        duty_count=len(jd.duties),
        approvable=approvable,
    )

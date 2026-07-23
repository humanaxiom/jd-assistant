"""Composer value objects — the shape a live-authoring surface draws from.

Phase 5.1. :class:`DraftAssessment` is the one object the JD Builder's live
compliance panel renders: the honest, full :class:`~src.jd_core.models.quality.
JDQualityReport` (score, grade, gate decision, findings) **plus** a draft-mode
regrouping of those same findings into *what is still to author* vs *what is
present but non-compliant*.

Nothing here is a second source of truth or a second oracle. The report is the
validator's verdict, untouched (CLAUDE.md non-negotiable #3); the split is a pure
presentation view over ``report.checklist`` — the same class of derived,
recompute-on-read regrouping as :func:`~src.jd_core.quality.checklist.
build_checklist`, and for the same reason it is **not** a registered decision: it
changes no JD's score, grade or gate.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from src.jd_core.models.quality import JDQualityIssue, JDQualityReport, SFUSection

#: A template section's authoring state, as the live panel shows it.
#:
#: * ``empty`` — a mandatory section the author has not filled in yet (unauthored
#:   *and* the validator raised a finding for its absence). Its findings are
#:   *guidance* ("what's left to do"), never failures: the whole point of draft
#:   mode is that an un-started section does not read as "you failed". An
#:   unauthored but OPTIONAL section (e.g. additional context) raises no finding
#:   and so reads ``ok``, not a false todo.
#: * ``needs_attention`` — authored, but it carries at least one finding: a real
#:   *present-but-non-compliant* issue to fix.
#: * ``ok`` — authored and clean.
SectionState = Literal["empty", "ok", "needs_attention"]


class DraftSectionStatus(BaseModel):
    """One SFU-template section's authoring state for the live panel.

    ``issues`` are the findings the validator raised in this section (empty when
    ``state == "ok"``); the panel colours the section by :attr:`state` and lists
    the issues underneath.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    section: SFUSection
    label: str = Field(min_length=1)
    state: SectionState
    issues: tuple[JDQualityIssue, ...] = ()


class DraftAssessment(BaseModel):
    """The live-compliance result for one in-progress JD draft.

    :attr:`report` is the validator's untouched verdict — ``report.gate_decision``
    is the honest answer to "may this be approved yet?" and is **never** faked to
    make an unfinished draft look approvable. :attr:`guidance` and :attr:`findings`
    partition the very same ``report.issues`` for presentation: guidance is
    everything raised in a not-yet-authored section, findings is everything raised
    in a section the author has actually filled in (plus the cross-cutting
    ``general`` bucket — placeholders, coded language — which is always a real
    finding, never "just unfinished").
    """

    model_config = ConfigDict(extra="forbid")

    report: JDQualityReport
    #: Every template section in template order, plus ``general`` when it carries
    #: findings — mirrors ``report.checklist``.
    sections: list[DraftSectionStatus] = Field(default_factory=list)
    #: Findings in sections not yet authored — "what's still to write".
    guidance: list[JDQualityIssue] = Field(default_factory=list)
    #: Findings in authored sections (+ general) — "what's present but wrong".
    findings: list[JDQualityIssue] = Field(default_factory=list)
    #: Word count of the position summary as authored (0 if absent) — the panel's
    #: live 100–150-word meter reads this without re-deriving it.
    summary_word_count: int = Field(ge=0)
    #: Number of duties authored (the template wants 3–5).
    duty_count: int = Field(ge=0)
    #: Convenience mirror of ``report.gate_decision.approved`` — whether the
    #: rulebook would let a reviewer approve this draft as it stands.
    approvable: bool

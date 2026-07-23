"""JD Builder — forward-looking JD Composer (Phase 5).

Helps a hiring manager / recruiter author a new SFU-compliant JD with live
compliance feedback, and routes the result into the same human-approval review
queue (nothing auto-publishes, NN #1). See ``docs/tasks/phase-5-jd-builder.md``.

Phase 5.1 — the live-compliance core::

    from src.jd_bank.composer import assess_draft, DraftAssessment

    assessment = assess_draft(jd)   # SFUJobDescription -> DraftAssessment
"""

from src.jd_bank.composer.models import (
    DraftAssessment,
    DraftSectionStatus,
    SectionState,
)
from src.jd_bank.composer.validate import assess_draft

__all__ = [
    "DraftAssessment",
    "DraftSectionStatus",
    "SectionState",
    "assess_draft",
]

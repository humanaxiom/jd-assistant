"""JD Builder — forward-looking JD Composer (Phase 5).

Helps a hiring manager / recruiter author a new SFU-compliant JD with live
compliance feedback, and routes the result into the same human-approval review
queue (nothing auto-publishes, NN #1). See ``docs/tasks/phase-5-jd-builder.md``.

Phase 5.1 — the live-compliance core::

    from src.jd_bank.composer import assess_draft, DraftAssessment

    assessment = assess_draft(jd)   # SFUJobDescription -> DraftAssessment
"""

from src.jd_bank.composer.answers import (
    ComposerAnswers,
    DutyAnswer,
    ModifiedQual,
)
from src.jd_bank.composer.assemble import assemble_jd
from src.jd_bank.composer.assist import SummarySuggestion, suggest_summary
from src.jd_bank.composer.models import (
    DraftAssessment,
    DraftSectionStatus,
    SectionState,
)
from src.jd_bank.composer.persist import COMPOSED_ORIGIN, submit_composed_draft
from src.jd_bank.composer.questions import (
    Question,
    QuestionSet,
    QuestionSetError,
    load_question_set,
)
from src.jd_bank.composer.validate import assess_draft

__all__ = [
    "COMPOSED_ORIGIN",
    "ComposerAnswers",
    "DraftAssessment",
    "DraftSectionStatus",
    "DutyAnswer",
    "ModifiedQual",
    "Question",
    "QuestionSet",
    "QuestionSetError",
    "SectionState",
    "SummarySuggestion",
    "assemble_jd",
    "assess_draft",
    "load_question_set",
    "submit_composed_draft",
    "suggest_summary",
]

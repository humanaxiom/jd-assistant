"""Assemble the one object a reviewer's screen is drawn from (Phase 2.3).

:func:`build_report` is the join: findings -> score + grade -> section checklist
-> approval decision, stamped with the ``rules_version`` that produced them. Every
part is recomputed from ``issues`` under the versioned rulebook, so a report is
always reconcilable to the exact rules that made it.

It does **not** persist anything: writing ``validation_reports`` rows is Phase 2.5.
Pure but for the clock — pass ``generated_at`` to make it fully deterministic.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from uuid import UUID

from src.jd_core.models.quality import JDQualityIssue, JDQualityReport
from src.jd_core.quality.checklist import build_checklist
from src.jd_core.quality.gates import evaluate_gates
from src.jd_core.quality.scoring import score_issues
from src.jd_core.rules import Rules, get_rules


def build_report(
    *,
    job_id: UUID,
    issues: Sequence[JDQualityIssue],
    model: str,
    prompt_version: str,
    generated_at: dt.datetime | None = None,
    rules: Rules | None = None,
) -> JDQualityReport:
    """Roll a JD's findings up into the persisted / API-returned report.

    ``issues`` is the merged finding list (deterministic today; plus the Phase-5
    LLM pass later). ``model`` / ``prompt_version`` stamp what produced the LLM
    half — a deterministic-only run should say so explicitly rather than leave
    them blank.

    ``rules`` defaults to the shipped rulebook; passing a different one scores,
    groups and gates the same findings under an alternative rules version (and the
    report's ``rules_version`` records which).
    """
    rulebook = rules if rules is not None else get_rules()
    findings = list(issues)

    score, grade = score_issues(findings, scoring=rulebook.scoring)
    return JDQualityReport(
        job_id=job_id,
        overall_score=score,
        grade=grade,
        issue_count=len(findings),
        issues=findings,
        checklist=build_checklist(findings, catalog=rulebook.rule_catalog),
        gate_decision=evaluate_gates(findings, score, grade, gates=rulebook.gates),
        model=model,
        prompt_version=prompt_version,
        rules_version=rulebook.version,
        generated_at=(
            generated_at if generated_at is not None else dt.datetime.now(dt.UTC)
        ),
    )

"""The approval gate runner — "never approve if…" (Phase 2.3).

What stands between a draft JD and an HR reviewer's approve button. Given the
deterministic findings, the score and the grade, it answers one question: **may a
human be shown the approve button at all?**

It never approves *for* a human (CLAUDE.md non-negotiable #1 — nothing
auto-publishes). ``GateDecision.approved`` is a *permission*, not an approval;
``approved=False`` disables the button and every reason cites the SFU rulebook
part that disabled it.

**Not one decision parameter lives here** (non-negotiable #2). Which rules are
fatal, the severity floor, the score floor, the grade floor, whether a gate is
overridable, and the copy each blocked decision explains itself with are all
versioned YAML in ``rules/gates.yaml``, loaded by :func:`~src.jd_core.rules.
get_rules`. Re-tuning the policy — "stop blocking on coded terms", "raise the
score floor to 70", "make the placeholder gate overridable" — is a YAML edit, not
a code edit. This module is only the arithmetic of comparing findings to it.

Pure: same input, same decision, no I/O, no model call — and it **never raises on
a JD**. Every way a gate's copy could fail to render is caught when the policy is
loaded (:meth:`~src.jd_core.rules.GatePolicy._reason_templates_render`), so no
JD, however malformed, can turn a decision into a traceback.

Overrides are the one place a human overrules the rulebook, and they are audited:
:class:`~src.jd_core.models.quality.GateOverride` cannot be constructed without a
written reason, and :func:`apply_overrides` refuses to waive a gate the policy
marks non-overridable. (The audit-log *write* is Phase 4; this module only makes
the decision it will record.)
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from src.jd_core.models.quality import (
    GateDecision,
    GateOverride,
    GateReason,
    JDGrade,
    JDQualityIssue,
)
from src.jd_core.rules import (
    BlockingRulesGate,
    GatePolicy,
    GateSpec,
    GradeFloorGate,
    ScoreFloorGate,
    SeverityFloorGate,
    get_rules,
)


class GateOverrideError(RuntimeError):
    """A proposed override is not one the policy allows.

    Raised when a reviewer tries to waive a gate that is not blocking, is not
    overridable (CLAUDE.md #1 — some bars are not the reviewer's to lower), or is
    waived twice. This is a caller/policy error, never JD data: no JD can provoke
    it, so the runner's never-raise guarantee is intact.
    """


def _listed(values: Sequence[str], *, limit: int, separator: str = ", ") -> str:
    """Join at most ``limit`` values, marking truncation with an ellipsis.

    A blocked reason names a bounded *sample* of the offenders. A badly-extracted
    archive document can fire one rule many times over; the reason must stay a
    sentence, and the runner must never blow a field cap and raise.
    """
    head = separator.join(values[:limit])
    return f"{head}{separator}…" if len(values) > limit else head


def _evidence_of(issues: Sequence[JDQualityIssue], *, limit: int) -> tuple[str, ...]:
    """The verbatim JD spans the offending findings quoted (bounded, deduped)."""
    seen: dict[str, None] = {}
    for issue in issues:
        if issue.evidence:
            seen.setdefault(issue.evidence, None)
    return tuple(seen)[:limit]


def _rule_ids_of(issues: Sequence[JDQualityIssue]) -> tuple[str, ...]:
    """The catalogued rules the offending findings raised (in order, deduped).

    Findings from the LLM pass carry no ``rule_id`` and simply contribute none.
    """
    seen: dict[str, None] = {}
    for issue in issues:
        if issue.rule_id is not None:
            seen.setdefault(issue.rule_id, None)
    return tuple(seen)


def _reason(
    gate: GateSpec,
    policy: GatePolicy,
    offenders: Sequence[JDQualityIssue],
    **context: object,
) -> GateReason:
    """One blocked gate, explained: its rulebook part, its copy, its evidence."""
    rule_ids = _rule_ids_of(offenders)
    return GateReason(
        gate_id=gate.gate_id,
        source_part=gate.source_part,
        reason=gate.render(
            {
                "count": len(offenders),
                "rule_ids": _listed(rule_ids, limit=policy.max_listed),
                **context,
            }
        ),
        rule_ids=rule_ids[: policy.max_listed],
        evidence=_evidence_of(offenders, limit=policy.max_listed),
        overridable=gate.overridable,
    )


def _check(
    gate: GateSpec,
    policy: GatePolicy,
    issues: Sequence[JDQualityIssue],
    score: float,
    grade: JDGrade,
) -> GateReason | None:
    """Does ``gate`` block this JD? The reason if so, ``None`` if it permits it."""
    if isinstance(gate, BlockingRulesGate):
        blocking = frozenset(gate.rule_ids)
        offenders = [i for i in issues if i.rule_id in blocking]
        if offenders:
            return _reason(gate, policy, offenders)
        return None

    if isinstance(gate, SeverityFloorGate):
        floor = policy.severity_rank(gate.min_severity)
        offenders = [i for i in issues if policy.severity_rank(i.severity) >= floor]
        if offenders:
            return _reason(gate, policy, offenders, min_severity=gate.min_severity)
        return None

    if isinstance(gate, ScoreFloorGate):
        # Fail CLOSED on a NaN score: `nan < floor` is False, so a naive comparison
        # would let an unscoreable JD sail past the floor. Unreachable from
        # `score_issues` today (the rulebook's penalties are finite), but an
        # approval bar must never be opened by a value it cannot compare.
        if math.isnan(score) or score < gate.min_score:
            return _reason(gate, policy, (), score=score, min_score=gate.min_score)
        return None

    if isinstance(gate, GradeFloorGate):
        if policy.grade_rank(grade) < policy.grade_rank(gate.min_grade):
            return _reason(gate, policy, (), grade=grade, min_grade=gate.min_grade)
        return None

    raise AssertionError(  # pragma: no cover - the union is closed + discriminated
        f"unhandled gate type {type(gate).__name__}"
    )


def evaluate_gates(
    issues: Sequence[JDQualityIssue],
    score: float,
    grade: JDGrade,
    *,
    gates: GatePolicy | None = None,
) -> GateDecision:
    """May this JD be approved? -> a boolean plus machine-readable reasons.

    Runs every gate in the policy (never short-circuits: a reviewer is shown
    *all* the reasons at once, not one at a time) and returns a
    :class:`~src.jd_core.models.quality.GateDecision`. ``approved`` is true only
    when nothing blocks — and even then it means "a human MAY approve", never
    "approved" (CLAUDE.md #1).

    ``gates`` defaults to the shipped policy; pass a different
    :class:`~src.jd_core.rules.GatePolicy` (still validated rulebook data) to
    decide under an alternative one — that is how the policy is tuned and tested,
    with no code change.

    Pure, total, and deterministic: it does not raise on any JD.
    """
    policy = gates if gates is not None else get_rules().gates
    blocking = tuple(
        reason
        for gate in policy.gates
        if (reason := _check(gate, policy, issues, score, grade)) is not None
    )
    return GateDecision(approved=not blocking, blocking=blocking)


def apply_overrides(
    decision: GateDecision, overrides: Sequence[GateOverride]
) -> GateDecision:
    """Waive blocking gates a reviewer has overridden — with their written reasons.

    The human escape hatch, and the only one (CLAUDE.md #1: a gate override
    requires a written reason, which
    :class:`~src.jd_core.models.quality.GateOverride` makes structurally
    mandatory). The returned decision carries every waiver, so Phase 4 can write
    them to the append-only audit log; a decision is permitted only once *every*
    blocking gate has been waived.

    Pure — ``decision`` is not mutated.

    Raises:
        GateOverrideError: the override names a gate that is not blocking this JD,
            a gate the policy marks non-overridable, or one already overridden.
            Never raised because of JD content.
    """
    blocking = {reason.gate_id: reason for reason in decision.blocking}
    waived: dict[str, GateOverride] = {}
    for override in overrides:
        # Re-check the written reason here rather than trust the model. This is the
        # last checkpoint before the Phase-4 audit-log write, and the reason IS the
        # override (CLAUDE.md #1) — `GateOverride.model_construct` skips validation,
        # as it does on every pydantic model, so a blank-reasoned waiver could
        # otherwise flip `approved` to True with nothing recorded.
        if not override.reason.strip() or not override.reviewer.strip():
            raise GateOverrideError(
                f"override of gate {override.gate_id!r} carries no written reason or "
                f"no named reviewer: an unreasoned override is not an override"
            )
        reason = blocking.get(override.gate_id)
        if reason is None:
            raise GateOverrideError(
                f"gate {override.gate_id!r} is not blocking this JD; "
                f"blocking: {sorted(blocking)}"
            )
        if not reason.overridable:
            raise GateOverrideError(
                f"gate {override.gate_id!r} is not overridable: the rulebook does "
                f"not permit a reviewer to waive it ({reason.source_part})"
            )
        if override.gate_id in waived:
            raise GateOverrideError(
                f"gate {override.gate_id!r} was overridden twice in one decision"
            )
        waived[override.gate_id] = override

    remaining = tuple(r for r in decision.blocking if r.gate_id not in waived)
    return GateDecision(
        approved=not remaining,
        blocking=remaining,
        overridden=decision.overridden + tuple(waived.values()),
    )

"""The nuanced quality-audit pass (Phase 4.2b) — the LLM's second Phase-4 consumer.

:func:`audit_quality` takes an already-parsed :class:`~src.jd_core.models.parsed_jd.
SFUJobDescription` (a 4.1 :class:`~src.jd_core.models.bank.MergedRole` draft or a 4.2a
``RewrittenDraft.draft``) and has a self-hosted LLM report only the three NUANCED
dimensions a deterministic validator cannot judge — ``inclusive_language`` /
``clarity`` / ``seniority_mismatch``. **Every finding must cite a verbatim quote from
the JD**; a finding whose ``evidence`` is not found verbatim in the flattened JD is
DROPPED — the anti-fabrication guard, the heart of this pass.

**We differ from hris deliberately.** hris audited ``description_raw`` and ran an
``sfu_jd_extract`` LLM pass first; we do neither — our input is already parsed (our
parser is regex, 4.2a), and structural/quantitative problems stay with the
deterministic validator (:mod:`src.jd_core`), the scoring oracle (non-negotiable #3).
hris merged + SCORED rule and LLM findings; **this pass computes NO score and no
grade** — it emits advisory :class:`~src.jd_core.models.quality.JDQualityIssue`s only.
The result is a frozen :class:`~src.jd_core.models.bank.QualityAudit`: nothing persists
(DB is 4.4), nothing publishes (non-negotiable #1), and ``jd_core`` is never imported
the other way round.
"""

from __future__ import annotations

from src.jd_bank.jd_text import flatten_jd
from src.jd_bank.llm.client import ChatClient
from src.jd_bank.llm.prompts import load_prompt
from src.jd_core.models.bank import QualityAudit
from src.jd_core.models.parsed_jd import SFUJobDescription
from src.jd_core.models.quality import (
    JDQualityFinding,
    JDQualityFindings,
    JDQualityIssue,
)
from src.jd_core.rules import QualityAuditRules, Rules, get_rules


def _to_issue(finding: JDQualityFinding) -> JDQualityIssue:
    """A surviving LLM finding as a merged issue: ``source="llm"``, ``rule_id=None`` (an
    LLM finding cites no deterministic gate)."""
    return JDQualityIssue(
        category=finding.category,
        severity=finding.severity,
        source="llm",
        message=finding.message,
        suggestion=finding.suggestion,
        evidence=finding.evidence,
        rule_id=None,
    )


def _scrub(
    findings: JDQualityFindings, jd_text: str, quality: QualityAuditRules
) -> tuple[list[JDQualityIssue], list[JDQualityFinding]]:
    """Apply the anti-fabrication guard (HR-189).

    With the guard ON, a finding is KEPT only if its ``evidence`` is a verbatim
    (``casefold`` substring) quote of the flattened JD — the SAME string that fed the
    prompt, so a quote the model copied from the prompt can be found. A finding with
    empty/None evidence quotes nothing and is dropped. With the guard OFF
    (``quality.anti_fabrication_enabled = false``) EVERY finding ships unscrubbed and
    nothing is recorded as dropped — so a disabled guard is visible, never invisible.
    """
    if not quality.anti_fabrication_enabled:
        return [_to_issue(f) for f in findings.issues], []

    haystack = jd_text.casefold()
    issues: list[JDQualityIssue] = []
    dropped: list[JDQualityFinding] = []
    for finding in findings.issues:
        if not finding.evidence or finding.evidence.casefold() not in haystack:
            dropped.append(finding)
            continue
        issues.append(_to_issue(finding))
    return issues, dropped


async def audit_quality(
    jd: SFUJobDescription, *, client: ChatClient, rules: Rules | None = None
) -> QualityAudit:
    """Audit ``jd`` for the three nuanced quality dimensions and return a frozen,
    advisory :class:`~src.jd_core.models.bank.QualityAudit`.

    Pure of persistence: no DB, no publish, NO score/grade. Flattens the JD with the
    SHARED :func:`~src.jd_bank.jd_text.flatten_jd` — the SAME string is both the
    ``jd_text`` prompt slot and the anti-fabrication scrub's haystack — sends it to the
    self-hosted LLM (``client`` is bound to ``rules.quality.model`` /
    ``rules.quality.temperature`` by the caller), scrubs ungrounded findings, and stamps
    the model / prompt / rules provenance.
    """
    active = rules if rules is not None else get_rules()
    quality = active.quality

    jd_text = flatten_jd(jd)
    prompt = load_prompt(quality.prompt_version, jd_text=jd_text)
    # Constrained decoding (opt-in): the audit's JDQualityFindings is a small flat
    # schema the Ollama builder handles cleanly, and forcing it stops gpt-oss returning
    # a Title-Case `"Inclusive Language"` where JDIssueCategory wants the enum member
    # (the ~24% schema-mismatch that dropped audits). The rewrite's large
    # SFUJobDescription grammar 500s the builder, so it stays on loose mode — see
    # ChatClient.chat_json.
    findings = await client.chat_json(
        prompt.messages,
        JDQualityFindings,
        max_tokens=quality.max_tokens,
        max_retries=quality.max_retries,
        constrain_to_schema=True,
    )

    issues, dropped = _scrub(findings, jd_text, quality)

    return QualityAudit(
        issues=tuple(issues),
        dropped=tuple(dropped),
        anti_fabrication_enabled=quality.anti_fabrication_enabled,
        model=quality.model,
        prompt_version=prompt.version,
        rules_version=active.version,
    )

"""The nuanced quality-audit consumer (Phase 4.2b): validator-as-oracle post-state,
the anti-fabrication (verbatim-evidence) guard proved BY MUTATION, the SHARED flattener
haystack, and the frozen advisory contract (no score/grade/approval).

The chat client is a content-keyed fake — it records the messages it was handed (so a
test can prove the flattened JD was serialized into the prompt) and returns FIXED
``JDQualityFindings``. Assertions read the audit's post-state (which findings survive
the scrub, their categories, ``source``, ``evidence``), NEVER verbatim model prose
(non-negotiable #3).
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from openai import BadRequestError
from pydantic import ValidationError

from src.jd_bank.jd_text import flatten_jd
from src.jd_bank.llm.client import ChatBadRequestError, ChatClient
from src.jd_bank.quality.audit import audit_quality
from src.jd_bank.rewrite.harmonize import _flatten_jd
from src.jd_core.models.bank import QualityAudit
from src.jd_core.models.parsed_jd import (
    SFUDuty,
    SFUJobDescription,
    SFUQualification,
    SFURelationships,
)
from src.jd_core.models.quality import JDQualityFinding, JDQualityFindings
from src.jd_core.rules import Rules, get_rules

# Evidence that IS a verbatim JD substring (from the position summary).
_GROUNDED_EVIDENCE = "strong attention to detail"
# Evidence that lives ONLY in the Relationships section (the 4.2a must-fix).
_RELATIONSHIPS_EVIDENCE = "aggressive go-getter"
# Evidence that is NOWHERE in the JD — the fabricated quote the guard must drop.
_FABRICATED_EVIDENCE = "unicorn ninja rockstar"


class _FakeChat:
    """Content-keyed fake: records the (system, user) messages it received and returns
    a FIXED ``JDQualityFindings``. Stands in for the whole ``ChatClient.chat_json`` —
    the client's own discipline is proved in ``test_quality_client.py``."""

    def __init__(self, findings: JDQualityFindings) -> None:
        self._findings = findings
        self.calls: list[tuple[tuple[str, ...], int, int]] = []

    async def chat_json(
        self,
        messages: object,
        model_cls: type[JDQualityFindings],
        *,
        max_tokens: int,
        max_retries: int,
        constrain_to_schema: bool = False,
    ) -> JDQualityFindings:
        assert model_cls is JDQualityFindings
        # The audit MUST opt into constrained decoding on its small findings schema —
        # that is what forces gpt-oss to the JDIssueCategory enum (the ~24% fix). Pinned
        # here so a caller that drops the flag (reverting to loose mode) goes red.
        assert constrain_to_schema is True
        contents = tuple(m["content"] for m in messages)  # type: ignore[union-attr]
        self.calls.append((contents, max_tokens, max_retries))
        return self._findings.model_copy(deep=True)


@pytest.fixture(scope="module")
def rules() -> Rules:
    return get_rules()


def _jd() -> SFUJobDescription:
    return SFUJobDescription(
        title="Financial Analyst",
        position_summary=(
            "Supports departmental budgeting and reporting with strong attention "
            "to detail."
        ),
        duties=[
            SFUDuty(
                action_verb="Prepares",
                statement="Prepares the annual budgeting reports for departments",
            ),
        ],
        qualifications=[
            SFUQualification(
                text="Working knowledge of financial accounting", kind="knowledge"
            ),
        ],
        relationships=SFURelationships(
            supervisory="Leads an aggressive go-getter team of analysts.",
        ),
    )


def _finding(evidence: str | None, category: str = "clarity") -> JDQualityFinding:
    return JDQualityFinding(
        category=category,  # type: ignore[arg-type]
        severity="medium",
        message="A nuanced quality concern the regex validator cannot judge.",
        suggestion="Reword the flagged span.",
        evidence=evidence,
    )


# --- acceptance #1: validator-as-oracle / post-state, not model text --------------


@pytest.mark.asyncio
async def test_a_grounded_finding_survives_as_an_llm_issue(rules: Rules) -> None:
    """A finding whose ``evidence`` is a verbatim JD substring survives, converted to a
    ``JDQualityIssue(source="llm", rule_id=None)``. Asserted as post-state (source,
    rule_id, evidence-is-a-substring), never as the model's prose."""
    findings = JDQualityFindings(
        issues=[_finding(_GROUNDED_EVIDENCE, category="inclusive_language")]
    )
    result = await audit_quality(_jd(), client=_FakeChat(findings), rules=rules)

    assert len(result.issues) == 1
    issue = result.issues[0]
    assert issue.source == "llm"
    assert issue.rule_id is None
    assert issue.category == "inclusive_language"
    # the surviving evidence is a verbatim substring of the flattened JD
    assert issue.evidence is not None
    assert issue.evidence.casefold() in flatten_jd(_jd()).casefold()
    assert result.dropped == ()


# --- acceptance #2: anti-fabrication guard, pinned BY MUTATION --------------------


@pytest.mark.asyncio
async def test_a_fabricated_finding_is_dropped_and_recorded(rules: Rules) -> None:
    """One grounded finding + one fabricated (evidence NOT in the JD): the grounded
    one survives in ``issues``, the fabricated one is dropped and recorded."""
    findings = JDQualityFindings(
        issues=[_finding(_GROUNDED_EVIDENCE), _finding(_FABRICATED_EVIDENCE)]
    )
    result = await audit_quality(_jd(), client=_FakeChat(findings), rules=rules)

    surviving = {i.evidence for i in result.issues}
    assert _GROUNDED_EVIDENCE in surviving
    assert _FABRICATED_EVIDENCE not in surviving
    dropped = {f.evidence for f in result.dropped}
    assert _FABRICATED_EVIDENCE in dropped


@pytest.mark.asyncio
async def test_a_finding_with_empty_evidence_is_dropped(rules: Rules) -> None:
    """Ungrounded by construction: an empty/None evidence cannot be verified, so it is
    dropped (it quotes nothing to check)."""
    findings = JDQualityFindings(issues=[_finding(None), _finding("")])
    result = await audit_quality(_jd(), client=_FakeChat(findings), rules=rules)

    assert result.issues == ()
    assert len(result.dropped) == 2


@pytest.mark.asyncio
async def test_disabling_the_guard_ships_the_fabricated_finding(rules: Rules) -> None:
    """THE mutation (acceptance #2): flip ``anti_fabrication_enabled`` (in reality the
    register is updated in step so the drift alarm stays silent) and the BEHAVIOURAL
    assertion — the fabricated finding is absent — goes red: it survives, unscrubbed.
    """
    disabled = rules.model_copy(
        update={
            "quality": rules.quality.model_copy(
                update={"anti_fabrication_enabled": False}
            )
        }
    )
    findings = JDQualityFindings(
        issues=[_finding(_GROUNDED_EVIDENCE), _finding(_FABRICATED_EVIDENCE)]
    )
    result = await audit_quality(_jd(), client=_FakeChat(findings), rules=disabled)

    surviving = {i.evidence for i in result.issues}
    assert _FABRICATED_EVIDENCE in surviving  # NOT scrubbed — the guard was off
    assert result.dropped == ()
    assert result.anti_fabrication_enabled is False


# --- acceptance #3: the scrub haystack is the SHARED flattener --------------------


def test_the_audit_and_rewrite_share_one_flattener() -> None:
    """The audit haystack and the rewrite prompt/oracle text are the SAME function
    object — one flattener, one home (the 4.2a Relationships must-fix cannot silently
    diverge). If they diverged, this identity check goes red."""
    assert _flatten_jd is flatten_jd


@pytest.mark.asyncio
async def test_a_relationships_only_quote_survives(rules: Rules) -> None:
    """A finding quoting text that lives ONLY in Relationships survives — proving the
    shared flattener includes that section. If ``flatten_jd`` dropped Relationships, the
    evidence would not be found verbatim and the finding would be scrubbed (red)."""
    findings = JDQualityFindings(
        issues=[_finding(_RELATIONSHIPS_EVIDENCE, category="inclusive_language")]
    )
    result = await audit_quality(_jd(), client=_FakeChat(findings), rules=rules)

    assert _RELATIONSHIPS_EVIDENCE in {i.evidence for i in result.issues}
    assert result.dropped == ()


# --- acceptance #7: prompt loader + provenance stamps ----------------------------


@pytest.mark.asyncio
async def test_the_audit_is_stamped_with_model_prompt_and_rules_version(
    rules: Rules,
) -> None:
    findings = JDQualityFindings(issues=[])
    result = await audit_quality(_jd(), client=_FakeChat(findings), rules=rules)

    assert result.model == rules.quality.model
    assert result.prompt_version == "jd_quality_v1"
    assert result.rules_version == rules.version


@pytest.mark.asyncio
async def test_the_flattened_jd_and_rule_knobs_feed_the_prompt_and_call(
    rules: Rules,
) -> None:
    """The flattened JD is the ``jd_text`` prompt slot, and the token/repair budgets
    come from the rulebook (HR-187/HR-188)."""
    fake = _FakeChat(JDQualityFindings(issues=[]))
    await audit_quality(_jd(), client=fake, rules=rules)

    contents, max_tokens, max_retries = fake.calls[0]
    user = contents[1]
    assert "Prepares the annual budgeting reports for departments" in user
    assert _RELATIONSHIPS_EVIDENCE in user  # the whole flattened haystack is in-prompt
    assert max_tokens == rules.quality.max_tokens
    assert max_retries == rules.quality.max_retries


# --- acceptance #5: non-negotiable #1 / #3 — advisory, frozen, no score ----------


def test_quality_audit_is_frozen_and_has_no_score_or_approval_field() -> None:
    assert QualityAudit.model_config["frozen"] is True
    fields = set(QualityAudit.model_fields)
    forbidden = {
        "overall_score",
        "score",
        "grade",
        "approved",
        "approved_by",
        "canonical",
        "published",
        "job_id",
        "generated_at",
    }
    assert not (fields & forbidden), sorted(fields & forbidden)


@pytest.mark.asyncio
async def test_the_audit_cannot_be_mutated(rules: Rules) -> None:
    result = await audit_quality(
        _jd(), client=_FakeChat(JDQualityFindings(issues=[])), rules=rules
    )
    with pytest.raises(ValidationError):
        result.model = "something-else"  # type: ignore[misc]


# --- acceptance #8: the audit path reuses the real client's 400 discipline --------


def _fake_openai(create: AsyncMock) -> SimpleNamespace:
    return SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create)),
        close=AsyncMock(),
    )


def _bad_request_error() -> BadRequestError:
    request = httpx.Request("POST", "http://aria-gb10-2:11434/v1/chat/completions")
    response = httpx.Response(status_code=400, request=request, json={"error": "bad"})
    return BadRequestError(message="bad request", response=response, body=None)


@pytest.mark.asyncio
async def test_an_over_length_audit_request_raises_and_is_not_retried(
    rules: Rules, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The audit path goes through the SAME ``ChatClient`` — an over-length (400)
    request raises ``ChatBadRequestError`` and is NEVER retried (a permanent property of
    request). Proves the audit reuses the client's discipline, not a second client."""
    monkeypatch.setattr("src.jd_bank.llm.client.asyncio.sleep", AsyncMock())
    create = AsyncMock(side_effect=_bad_request_error())
    client = ChatClient(
        client=_fake_openai(create),
        rules=rules,
        model=rules.quality.model,
        temperature=rules.quality.temperature,
    )

    with pytest.raises(ChatBadRequestError):
        await audit_quality(_jd(), client=client, rules=rules)

    assert create.await_count == 1  # never retried

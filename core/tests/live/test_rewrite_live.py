"""Live golden — the REAL chat model on ``aria-gb10-2`` rewrites a draft (ADR-003).

**Opt-in, LOCAL-ONLY.** ``make rewrite-golden``, never ``make gates`` / CI:

* ``core/pyproject.toml``'s ``addopts`` deselects ``-m live`` by default, and the
  Makefile / CI additionally pass ``-m "not live"`` — so even a bare ``pytest`` in the
  ``gates`` container cannot collect this (the same guard the embeddings golden uses).
* CI (``ubuntu-latest``) cannot route to ``aria-gb10-2`` and never will.
* Off-VPN, it self-skips (see :func:`_skip_if_unreachable`).

**Validator-as-oracle, applied live**: assertions are RELATIONS (the returned score is
the validator's own verdict on the returned draft; the anti-fabrication guard ran; the
grade is a real band) — never a hardcoded score or verbatim model text, which is not
portable across model-server versions anyway.
"""

from __future__ import annotations

import asyncio

import pytest

from src.jd_bank.llm.client import ChatClient
from src.jd_bank.rewrite.harmonize import _flatten_jd, rewrite_merged_role
from src.jd_core.models.bank import MergedRole, MergeProvenance
from src.jd_core.models.parsed_jd import SFUDuty, SFUJobDescription, SFUQualification
from src.jd_core.quality.scoring import score_issues
from src.jd_core.quality.validators import evaluate_jd_rules
from src.jd_core.rules import get_rules

pytestmark = pytest.mark.live


def _probe_reachable() -> bool:
    async def _try() -> bool:
        client = ChatClient(rules=get_rules())
        try:
            await asyncio.wait_for(
                client.chat_json(
                    [{"role": "user", "content": 'Reply with {"title": "x"}'}],
                    SFUJobDescription,
                    max_tokens=64,
                    max_retries=0,
                ),
                timeout=30.0,
            )
            return True
        except Exception:  # noqa: BLE001 - any failure means "not reachable right now"
            return False
        finally:
            await client.close()

    return asyncio.run(_try())


@pytest.fixture(autouse=True)
def _skip_if_unreachable() -> None:
    if not _probe_reachable():
        pytest.skip(
            "aria-gb10-2 (Ollama chat) is unreachable from this host — local-only, "
            "see ADR-003"
        )


def _merged() -> MergedRole:
    draft = SFUJobDescription(
        title="Financial Analyst",
        position_summary=(
            "Supports the department's annual budgeting and financial reporting, "
            "reconciling accounts and preparing forecasts for leadership review."
        ),
        duties=[
            SFUDuty(
                action_verb="Prepares",
                statement="Prepares the annual budgeting reports for departments",
            ),
            SFUDuty(
                action_verb="Reviews",
                statement="Reviews financial forecasting and reconciliation statements",
            ),
        ],
        qualifications=[
            SFUQualification(
                text="Working knowledge of financial accounting", kind="knowledge"
            ),
        ],
    )
    return MergedRole(
        draft=draft,
        provenance=MergeProvenance(
            member_count=3, skill_frequency=(("accounting", 3), ("budgeting", 2))
        ),
    )


@pytest.mark.asyncio
async def test_the_live_rewrite_is_a_scored_draft_not_a_publication() -> None:
    rules = get_rules()
    client = ChatClient(rules=rules)
    try:
        result = await rewrite_merged_role(_merged(), client=client, rules=rules)
    finally:
        await client.close()

    # a real draft came back, stamped with the rulebook that scored it
    assert result.draft.title.strip()
    assert result.rules_version == rules.version
    assert result.anti_fabrication.enabled is True

    # validator-as-oracle: the returned numbers ARE the validator's on that draft
    issues = evaluate_jd_rules(result.draft, _flatten_jd(result.draft), rules=rules)
    score, grade = score_issues(issues, scoring=rules.scoring)
    assert result.score == score
    assert result.grade == grade
    assert rules.scoring.min_score <= result.score <= rules.scoring.max_score

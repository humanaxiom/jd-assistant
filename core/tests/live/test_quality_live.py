"""Live golden — the REAL chat model on ``aria-gb10-2`` audits a JD (ADR-003).

**Opt-in, LOCAL-ONLY.** ``make quality-golden``, never ``make gates`` / CI:

* ``core/pyproject.toml``'s ``addopts`` deselects ``-m live`` by default, and the
  Makefile / CI additionally pass ``-m "not live"`` — so even a bare ``pytest`` in the
  ``gates`` container cannot collect this (the same guard the rewrite golden uses).
* CI (``ubuntu-latest``) cannot route to ``aria-gb10-2`` and never will.
* Off-VPN, it self-skips (see :func:`_skip_if_unreachable`).

**Validator-as-oracle, applied live**: the audit is ADVISORY — it computes no score.
The assertions are STRUCTURAL post-state (every surviving issue is ``source="llm"`` and
quotes the JD verbatim; the guard ran; the audit is stamped with the rulebook) — never
a hardcoded finding or verbatim model prose, which is not portable across model-server
versions anyway.
"""

from __future__ import annotations

import asyncio

import pytest

from src.jd_bank.jd_text import flatten_jd
from src.jd_bank.llm.client import ChatClient
from src.jd_bank.quality.audit import audit_quality
from src.jd_core.models.parsed_jd import SFUDuty, SFUJobDescription, SFUQualification
from src.jd_core.rules import get_rules

pytestmark = pytest.mark.live


def _probe_reachable() -> bool:
    async def _try() -> bool:
        rules = get_rules()
        client = ChatClient(
            model=rules.quality.model, temperature=rules.quality.temperature
        )
        try:
            await asyncio.wait_for(
                client.chat_json(
                    [{"role": "user", "content": 'Reply with {"issues": []}'}],
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


def _jd() -> SFUJobDescription:
    return SFUJobDescription(
        title="Financial Analyst",
        position_summary=(
            "We want an aggressive, young go-getter who can hit the ground running "
            "and works well under a fast-paced, high-pressure environment."
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
    )


@pytest.mark.asyncio
async def test_the_live_audit_is_advisory_and_every_issue_quotes_the_jd() -> None:
    rules = get_rules()
    client = ChatClient(
        rules=rules,
        model=rules.quality.model,
        temperature=rules.quality.temperature,
    )
    try:
        result = await audit_quality(_jd(), client=client, rules=rules)
    finally:
        await client.close()

    # stamped with the rulebook that produced it; the guard ran
    assert result.rules_version == rules.version
    assert result.prompt_version == "jd_quality_v1"
    assert result.anti_fabrication_enabled is True

    # anti-fabrication, applied live: EVERY surviving issue quotes the JD verbatim
    haystack = flatten_jd(_jd()).casefold()
    for issue in result.issues:
        assert issue.source == "llm"
        assert issue.rule_id is None
        assert issue.evidence is not None
        assert issue.evidence.casefold() in haystack

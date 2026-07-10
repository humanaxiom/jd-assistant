"""Unit tests for the subagents and BaseAgent shared machinery.

All external I/O (the AsyncOpenAI client, graph memory) is mocked — nothing
touches Ollama or a real store.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agents.base import AgentInput
from src.agents.coder import CoderAgent
from src.agents.docs import DocsAgent
from src.agents.reviewer import Review, ReviewerAgent, Severity
from src.agents.security import SecurityAgent, SecurityReport
from src.agents.tester import TesterAgent


def _fake_response(content: str | None, tokens: int | None) -> Any:
    usage = None if tokens is None else SimpleNamespace(total_tokens=tokens)
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=usage,
    )


def _fake_client(content: str | None = "out", tokens: int | None = 5) -> Any:
    client = MagicMock()
    client.chat.completions.create = AsyncMock(
        return_value=_fake_response(content, tokens)
    )
    return client


def _mem(similar: list[dict[str, Any]] | None = None) -> AsyncMock:
    m = AsyncMock()
    m.similar_artifacts = AsyncMock(return_value=similar or [])
    return m


# ── BaseAgent shared machinery (exercised through TesterAgent) ───────────────


@pytest.mark.asyncio
async def test_complete_returns_text_and_tokens() -> None:
    with patch("src.agents.base.AsyncOpenAI"):
        agent = TesterAgent()
    agent._client = _fake_client("hello", tokens=42)
    text, tokens = await agent._complete("prompt")
    assert text == "hello"
    assert tokens == 42


@pytest.mark.asyncio
async def test_complete_handles_missing_content_and_usage() -> None:
    with patch("src.agents.base.AsyncOpenAI"):
        agent = TesterAgent()
    agent._client = _fake_client(content=None, tokens=None)
    text, tokens = await agent._complete("prompt")
    assert text == ""
    assert tokens == 0


@pytest.mark.asyncio
async def test_memory_context_none_returns_empty() -> None:
    with patch("src.agents.base.AsyncOpenAI"):
        agent = TesterAgent(memory=None)
    assert await agent._memory_context("q") == ""


@pytest.mark.asyncio
async def test_memory_context_empty_similar_returns_empty() -> None:
    with patch("src.agents.base.AsyncOpenAI"):
        agent = TesterAgent(memory=_mem([]))
    assert await agent._memory_context("q") == ""


@pytest.mark.asyncio
async def test_memory_context_formats_blocks() -> None:
    similar = [{"kind": "code", "score": 0.87, "content": "def f(): ..."}]
    with patch("src.agents.base.AsyncOpenAI"):
        agent = TesterAgent(memory=_mem(similar))
    ctx = await agent._memory_context("q")
    assert "Similar prior work" in ctx
    assert "[code]" in ctx
    assert "0.87" in ctx


@pytest.mark.asyncio
async def test_record_noop_without_memory() -> None:
    with patch("src.agents.base.AsyncOpenAI"):
        agent = TesterAgent(memory=None)
    input_ = AgentInput(task_id="T", task="do")
    output = agent._ok(input_, result=None, reasoning="r", artifacts={"a.py": "x"})
    await agent._record(input_, output)  # must not raise


@pytest.mark.asyncio
async def test_record_persists_subtask_and_artifacts() -> None:
    mem = _mem()
    with patch("src.agents.base.AsyncOpenAI"):
        agent = TesterAgent(memory=mem)
    input_ = AgentInput(task_id="T", task="do the thing")
    output = agent._ok(
        input_, result=None, reasoning="r", artifacts={"tests/t.py": "code"}
    )
    await agent._record(input_, output)
    mem.record_subtask.assert_awaited_once()
    mem.record_artifact.assert_awaited_once()
    assert mem.record_subtask.await_args.kwargs["agent_id"] == "tester"


# ── TesterAgent ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_tester_success_extracts_test_files() -> None:
    text = "```python path=tests/unit/test_x.py\ndef test_x(): assert True\n```"
    with patch("src.agents.base.AsyncOpenAI"):
        agent = TesterAgent(memory=_mem())
    with patch.object(agent, "_complete", AsyncMock(return_value=(text, 12))):
        out = await agent.run(AgentInput(task_id="T", task="build x"))
    assert out.success is True
    assert out.result == ["tests/unit/test_x.py"]
    assert "tests/unit/test_x.py" in out.artifacts
    assert out.tokens_used == 12


@pytest.mark.asyncio
async def test_tester_no_files_fails() -> None:
    text = "```python path=src/x.py\nprint('nope')\n```"  # non-test path rejected
    with patch("src.agents.base.AsyncOpenAI"):
        agent = TesterAgent(memory=None)
    with patch.object(agent, "_complete", AsyncMock(return_value=(text, 1))):
        out = await agent.run(AgentInput(task_id="T", task="x"))
    assert out.success is False
    assert "no test files" in (out.error or "")


@pytest.mark.asyncio
async def test_tester_exception_becomes_failure() -> None:
    with patch("src.agents.base.AsyncOpenAI"):
        agent = TesterAgent(memory=None)
    with patch.object(agent, "_complete", AsyncMock(side_effect=RuntimeError("boom"))):
        out = await agent.run(AgentInput(task_id="T", task="x"))
    assert out.success is False
    assert out.error == "boom"


def test_tester_extract_rejects_non_test_and_traversal() -> None:
    with patch("src.agents.base.AsyncOpenAI"):
        agent = TesterAgent()
    text = (
        "```python path=tests/unit/test_a.py\nok\n```\n"
        "```python path=src/b.py\nno\n```\n"
        "```python path=tests/../evil.py\nno\n```"
    )
    files = agent._extract_test_files(text)
    assert set(files) == {"tests/unit/test_a.py"}


# ── DocsAgent ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_docs_success_uses_changes_summary() -> None:
    text = "```markdown path=docs/adr/001-x.md\n# ADR\nbody\n```"
    with patch("src.agents.base.AsyncOpenAI"):
        agent = DocsAgent(memory=_mem())
    complete = AsyncMock(return_value=(text, 7))
    with patch.object(agent, "_complete", complete):
        out = await agent.run(
            AgentInput(task_id="T", task="x", context={"changes_summary": "did stuff"})
        )
    assert out.success is True
    assert "docs/adr/001-x.md" in out.artifacts
    assert "did stuff" in complete.await_args.args[0]


@pytest.mark.asyncio
async def test_docs_rejects_non_doc_paths() -> None:
    text = "```python path=src/x.py\ncode\n```"
    with patch("src.agents.base.AsyncOpenAI"):
        agent = DocsAgent(memory=None)
    with patch.object(agent, "_complete", AsyncMock(return_value=(text, 1))):
        out = await agent.run(AgentInput(task_id="T", task="x"))
    assert out.success is True
    assert out.artifacts == {}


@pytest.mark.asyncio
async def test_docs_exception_becomes_failure() -> None:
    with patch("src.agents.base.AsyncOpenAI"):
        agent = DocsAgent(memory=None)
    with patch.object(agent, "_complete", AsyncMock(side_effect=ValueError("nope"))):
        out = await agent.run(AgentInput(task_id="T", task="x"))
    assert out.success is False
    assert out.error == "nope"


# ── SecurityAgent ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_security_no_target_fails() -> None:
    with patch("src.agents.base.AsyncOpenAI"):
        agent = SecurityAgent(memory=None)
    out = await agent.run(AgentInput(task_id="T", task="x", context={}))
    assert out.success is False
    assert "No diff/code" in (out.error or "")


@pytest.mark.asyncio
async def test_security_passes_clean() -> None:
    payload = {"passed": True, "findings": []}
    with patch("src.agents.base.AsyncOpenAI"):
        agent = SecurityAgent(memory=_mem())
    complete = AsyncMock(return_value=(json.dumps(payload), 3))
    with patch.object(agent, "_complete", complete):
        out = await agent.run(
            AgentInput(task_id="T", task="x", context={"diff": "safe code"})
        )
    assert out.success is True
    report: SecurityReport = out.result
    assert report.passed is True
    assert report.findings == []


@pytest.mark.asyncio
async def test_security_blocking_finding_overrides_passed() -> None:
    payload = {
        "passed": True,  # model claims pass but a high finding must block
        "findings": [
            {
                "category": "injection",
                "severity": "high",
                "file": "db.py",
                "message": "raw sql",
                "remediation": "parametrize",
            }
        ],
    }
    fenced = f"```json\n{json.dumps(payload)}\n```"
    with patch("src.agents.base.AsyncOpenAI"):
        agent = SecurityAgent(memory=None)
    with patch.object(agent, "_complete", AsyncMock(return_value=(fenced, 4))):
        out = await agent.run(
            AgentInput(task_id="T", task="x", context={"code": "bad"})
        )
    assert out.success is True
    report: SecurityReport = out.result
    assert report.passed is False
    assert len(report.findings) == 1


@pytest.mark.asyncio
async def test_security_invalid_json_fails() -> None:
    with patch("src.agents.base.AsyncOpenAI"):
        agent = SecurityAgent(memory=None)
    with patch.object(agent, "_complete", AsyncMock(return_value=("not json", 1))):
        out = await agent.run(AgentInput(task_id="T", task="x", context={"diff": "d"}))
    assert out.success is False
    assert "Invalid security report" in (out.error or "")


# ── ReviewerAgent ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reviewer_no_diff_fails() -> None:
    with patch("src.agents.base.AsyncOpenAI"):
        agent = ReviewerAgent(memory=None)
    out = await agent.run(AgentInput(task_id="T", task="x", context={}))
    assert out.success is False
    assert "No diff" in (out.error or "")


@pytest.mark.asyncio
async def test_reviewer_approves_clean_diff() -> None:
    payload = {"approved": True, "summary": "lgtm", "findings": []}
    with patch("src.agents.base.AsyncOpenAI"):
        agent = ReviewerAgent(memory=_mem())
    complete = AsyncMock(return_value=(json.dumps(payload), 2))
    with patch.object(agent, "_complete", complete):
        out = await agent.run(
            AgentInput(task_id="T", task="x", context={"diff": "diff"})
        )
    assert out.success is True
    review: Review = out.result
    assert review.approved is True
    assert review.summary == "lgtm"


@pytest.mark.asyncio
async def test_reviewer_blocking_finding_forces_rejection() -> None:
    payload = {
        "approved": True,  # inconsistent: a major finding must flip this to False
        "summary": "has issues",
        "findings": [
            {
                "severity": "major",
                "file": "x.py",
                "line": 10,
                "message": "blocking issue",
                "suggestion": "fix it",
            }
        ],
    }
    with patch("src.agents.base.AsyncOpenAI"):
        agent = ReviewerAgent(memory=None)
    complete = AsyncMock(return_value=(json.dumps(payload), 2))
    with patch.object(agent, "_complete", complete):
        out = await agent.run(
            AgentInput(task_id="T", task="x", context={"diff": "diff"})
        )
    assert out.success is True
    review: Review = out.result
    assert review.approved is False
    assert review.blocking[0].severity == Severity.MAJOR


@pytest.mark.asyncio
async def test_reviewer_invalid_json_fails() -> None:
    with patch("src.agents.base.AsyncOpenAI"):
        agent = ReviewerAgent(memory=None)
    with patch.object(agent, "_complete", AsyncMock(return_value=("{bad", 1))):
        out = await agent.run(AgentInput(task_id="T", task="x", context={"diff": "d"}))
    assert out.success is False
    assert "Invalid review JSON" in (out.error or "")


# ── CoderAgent ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_coder_iterate_writes_src_file(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    content = "```python path=src/foo.py\nprint('hi')\n```"
    with patch("src.agents.coder.AsyncOpenAI"):
        coder = CoderAgent(memory=None)
    coder._client = _fake_client(content)
    monkeypatch.chdir(tmp_path)
    msg = await coder.iterate("task", "failure report", 1)
    assert "Applied 1 file change(s) for iteration 1" == msg
    assert (tmp_path / "src" / "foo.py").read_text(encoding="utf-8") == "print('hi')\n"


@pytest.mark.asyncio
async def test_coder_iterate_refuses_outside_paths(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    content = "```python path=../evil.py\nboom\n```"
    with patch("src.agents.coder.AsyncOpenAI"):
        coder = CoderAgent(memory=None)
    coder._client = _fake_client(content)
    monkeypatch.chdir(tmp_path)
    msg = await coder.iterate("task", "report", 2)
    assert "Applied 0 file change(s)" in msg
    assert not (tmp_path / "evil.py").exists()


@pytest.mark.asyncio
async def test_coder_iterate_injects_memory_context(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    similar = [{"kind": "code", "score": 0.5, "content": "prior"}]
    content = "```python path=src/bar.py\nx = 1\n```"
    with patch("src.agents.coder.AsyncOpenAI"):
        coder = CoderAgent(memory=_mem(similar))
    coder._client = _fake_client(content)
    monkeypatch.chdir(tmp_path)
    await coder.iterate("task", "report", 1)
    sent = coder._client.chat.completions.create.await_args.kwargs["messages"]
    assert "Similar prior work from memory" in sent[1]["content"]


@pytest.mark.asyncio
async def test_coder_retrieve_context_empty_when_no_similar(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    content = "```python path=src/baz.py\ny = 2\n```"
    with patch("src.agents.coder.AsyncOpenAI"):
        coder = CoderAgent(memory=_mem([]))
    coder._client = _fake_client(content)
    monkeypatch.chdir(tmp_path)
    await coder.iterate("task", "report", 1)
    sent = coder._client.chat.completions.create.await_args.kwargs["messages"]
    assert "Similar prior work from memory" not in sent[1]["content"]

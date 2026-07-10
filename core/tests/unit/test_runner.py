"""Unit tests for the gate runner internals — command execution and suite build.

Subprocess creation is patched so no real linters/pytest are spawned.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from src.gates.runner import (
    GateResult,
    GateStatus,
    _run_command,
    run_all_gates,
    run_coverage_gate,
)


def _fake_proc(returncode: int, stdout: bytes) -> AsyncMock:
    proc = AsyncMock()
    proc.communicate = AsyncMock(return_value=(stdout, b""))
    proc.returncode = returncode
    return proc


@pytest.mark.asyncio
async def test_run_command_green() -> None:
    with patch(
        "src.gates.runner.asyncio.create_subprocess_exec",
        AsyncMock(return_value=_fake_proc(0, b"all good")),
    ):
        result = await _run_command("ruff", ["ruff", "check"])
    assert result.status == GateStatus.GREEN
    assert result.output == "all good"
    assert result.name == "ruff"


@pytest.mark.asyncio
async def test_run_command_red() -> None:
    with patch(
        "src.gates.runner.asyncio.create_subprocess_exec",
        AsyncMock(return_value=_fake_proc(1, b"failure")),
    ):
        result = await _run_command("mypy", ["mypy", "src"])
    assert result.status == GateStatus.RED
    assert "failure" in result.output


@pytest.mark.asyncio
async def test_run_coverage_gate_uses_threshold() -> None:
    captured: dict[str, list[str]] = {}

    async def fake(name: str, cmd: list[str]) -> GateResult:
        captured["cmd"] = cmd
        return GateResult(name, GateStatus.GREEN, "", 1)

    with patch("src.gates.runner._run_command", fake):
        result = await run_coverage_gate()

    assert result.name == "coverage"
    assert result.status == GateStatus.GREEN
    assert "--cov-fail-under=80" in captured["cmd"]


@pytest.mark.asyncio
async def test_run_all_gates_full_is_green() -> None:
    async def fake_cmd(name: str, cmd: list[str]) -> GateResult:
        return GateResult(name, GateStatus.GREEN, "ok", 1)

    async def fake_cov() -> GateResult:
        return GateResult("coverage", GateStatus.GREEN, "ok", 1)

    with (
        patch("src.gates.runner._run_command", fake_cmd),
        patch("src.gates.runner.run_coverage_gate", fake_cov),
    ):
        suite = await run_all_gates("agent/x-y", include_integration=True)

    names = {r.name for r in suite.results}
    assert "integration-tests" in names
    assert "coverage" in names
    assert suite.all_green is True


@pytest.mark.asyncio
async def test_run_all_gates_skips_integration() -> None:
    async def fake_cmd(name: str, cmd: list[str]) -> GateResult:
        return GateResult(name, GateStatus.GREEN, "ok", 1)

    async def fake_cov() -> GateResult:
        return GateResult("coverage", GateStatus.GREEN, "ok", 1)

    with (
        patch("src.gates.runner._run_command", fake_cmd),
        patch("src.gates.runner.run_coverage_gate", fake_cov),
    ):
        suite = await run_all_gates("agent/x-y", include_integration=False)

    by_name = {r.name: r.status for r in suite.results}
    assert by_name["integration-tests"] == GateStatus.SKIPPED
    assert by_name["branch-name"] == GateStatus.GREEN
    # SKIPPED is intentionally not GREEN, so the suite is not all-green.
    assert suite.all_green is False

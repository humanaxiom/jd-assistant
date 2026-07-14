"""``python -m src.jd_bank.embeddings`` — the CLI (Phase 3.2b).

The runner itself is exercised against real Postgres + Neo4j in
``tests/integration/test_embeddings_store.py``; this pins the CLI *around* it — the
argument parsing and the committed-summary write, which had no test at all and one
real bug (``--summary-out ""`` raised ``IsADirectoryError``).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from src.jd_bank.embeddings import __main__ as cli
from src.jd_bank.embeddings.models import EmbedRunResult


def _result() -> EmbedRunResult:
    return EmbedRunResult(
        documents_seen=3,
        documents_embedded=2,
        documents_unchanged=0,
        documents_empty=1,
        sections_embedded=4,
        sections_unchanged=0,
        sections_skipped_short=2,
        nodes_pruned=1,
        embed_calls=1,
        embed_texts_reused_memo=1,
        bad_requests=0,
        model="nomic-embed-text",
        dimensions=768,
        embed_stamp="jd_rules_sfu_v4+deadbeefcafe",
        serializer_version="embed_text_v1",
    )


@pytest.fixture
def _stub_run(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub the DB/Neo4j/Ollama half — this module is about the CLI, and a unit test
    may not open a connection to anything (ADR-003 / ADR-006)."""

    async def _fake_run(_args: Any) -> EmbedRunResult:
        return _result()

    monkeypatch.setattr(cli, "_run", _fake_run)


@pytest.mark.usefixtures("_stub_run")
def test_the_cli_writes_the_committed_summary(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "nested" / "summary.json"

    assert cli.main(["--summary-out", str(out)]) == 0

    written = json.loads(out.read_text(encoding="utf-8"))
    assert written["documents_embedded"] == 2
    assert written["nodes_pruned"] == 1
    assert written["embed_stamp"] == "jd_rules_sfu_v4+deadbeefcafe"
    # COUNTS AND STAMPS ONLY — never a vector. Embeddings are not guaranteed
    # byte-reproducible across model-server versions, so a committed artifact must
    # not claim to reproduce one.
    assert "embedding" not in json.dumps(written)
    assert "wrote" in capsys.readouterr().err


@pytest.mark.usefixtures("_stub_run")
def test_an_empty_summary_out_skips_the_write_instead_of_exploding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``--summary-out ""`` is documented as "skip". With ``type=Path`` argparse
    turned it into ``Path('.')`` — which is TRUTHY — so it fell through to
    ``write_text`` on a **directory** and raised ``IsADirectoryError``. It is decided
    as a string now, before it ever becomes a Path.
    """
    monkeypatch.chdir(tmp_path)

    assert cli.main(["--summary-out", ""]) == 0

    assert list(tmp_path.iterdir()) == []  # nothing written, nothing exploded


@pytest.mark.usefixtures("_stub_run")
def test_the_cli_prints_the_counts(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["--summary-out", ""]) == 0
    printed = capsys.readouterr().err
    assert "3 seen" in printed
    assert "nodes pruned" in printed
    assert "nomic-embed-text" in printed


def test_the_cli_rejects_an_unknown_argument(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit):
        cli.main(["--wat"])
    assert "usage" in capsys.readouterr().err

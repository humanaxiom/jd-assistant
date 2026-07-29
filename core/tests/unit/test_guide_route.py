"""The in-app operator-guide route (/jd-bank/ui/guide) — serves the rendered HTML file,
404s gracefully when it hasn't been built. Dev mode (cas_enabled=False) makes the gate
transparent, so no DB is needed."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.api.main import app
from src.settings import Settings, get_settings


@pytest.fixture(autouse=True)
def _clear() -> Iterator[None]:
    yield
    app.dependency_overrides.clear()


def _use(path: str) -> TestClient:
    app.dependency_overrides[get_settings] = lambda: Settings(operator_guide_path=path)
    return TestClient(app)


def test_serves_the_rendered_guide(tmp_path: Path) -> None:
    f = tmp_path / "operator-guide.html"
    f.write_text("<!doctype html><h1>Operator guide</h1>", encoding="utf-8")
    resp = _use(str(f)).get("/jd-bank/ui/guide")
    assert resp.status_code == 200
    assert "Operator guide" in resp.text
    assert "text/html" in resp.headers["content-type"]


def test_404_when_not_built(tmp_path: Path) -> None:
    resp = _use(str(tmp_path / "missing.html")).get("/jd-bank/ui/guide")
    assert resp.status_code == 404
    assert "make guide" in resp.text

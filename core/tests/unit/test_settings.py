"""Settings env parsing — comma-separated list env vars.

Regression: list[str] settings (bootstrap_admins, allowed_inference_hosts) must accept a
plain comma-separated env value. Without `NoDecode`, pydantic-settings JSON-decodes a
list field at the source (before validators), so BOOTSTRAP_ADMINS=asalah crashed startup
(the app failed to boot when CAS was first enabled).
"""

from __future__ import annotations

import pytest

from src.settings import Settings


def test_bootstrap_admins_parses_comma_separated_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BOOTSTRAP_ADMINS", "asalah, mstanger ,eleung")
    assert Settings().bootstrap_admins == ["asalah", "mstanger", "eleung"]


def test_bootstrap_admins_default_is_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("BOOTSTRAP_ADMINS", raising=False)
    assert Settings().bootstrap_admins == []


def test_allowed_inference_hosts_parses_comma_separated_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ALLOWED_INFERENCE_HOSTS", "aria-gb10-2, 10.0.0.5")
    assert Settings().allowed_inference_hosts == ["aria-gb10-2", "10.0.0.5"]


def test_cas_enabled_bool_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CAS_ENABLED", "true")
    assert Settings().cas_enabled is True

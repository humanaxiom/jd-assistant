"""UAT — "Report a problem with this page", on every page that extends ``_base.html``.

HR testers needed a way to report a problem from the page they were looking at. The
footer link is a ``mailto:`` built from the ``FEEDBACK_EMAIL`` setting (deployment
config, not an HR rule), prefilled with the page title, the page's path + query and
the signed-in username. No setting, no link — a link to nobody is worse than none.
Nothing is written anywhere.
"""

from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from src.api.main import app
from src.api.routes import library as library_route
from src.settings import Settings, get_settings
from tests.unit.test_library_ui import _role_page, make_client


@pytest.fixture(autouse=True)
def _clear() -> Iterator[None]:
    yield
    app.dependency_overrides.clear()


def _library(monkeypatch: pytest.MonkeyPatch, feedback_email: str) -> TestClient:
    monkeypatch.setattr(
        library_route, "list_roles", AsyncMock(return_value=_role_page(q="finance"))
    )
    client = make_client()
    settings = Settings(feedback_email=feedback_email)
    app.dependency_overrides[get_settings] = lambda: settings
    return client


def test_the_footer_offers_a_prefilled_problem_report(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _library(monkeypatch, "jdbank-uat@example.org")

    body = client.get("/jd-bank/ui/library", params={"q": "finance"}).text

    assert "Report a problem with this page" in body
    start = body.index('href="mailto:jdbank-uat@example.org?subject=')
    href = body[start : body.index('"', start + len('href="'))]
    # Subject: "JD Bank problem: <page title>".
    assert "subject=JD%20Bank%20problem%3A%20JD%20Bank%20" in href
    assert "the%20library" in href
    # Body: the page (path + query) and who was signed in.
    assert "&amp;body=" in href
    assert "/jd-bank/ui/library%3Fq%3Dfinance" in href
    assert "dev-anonymous" in href  # the CAS-off synthetic user `make gates` runs as


def test_no_feedback_address_means_no_link(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _library(monkeypatch, "")

    body = client.get("/jd-bank/ui/library").text

    assert "Report a problem" not in body
    assert "mailto:" not in body


def test_the_setting_reads_the_feedback_email_env_var(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FEEDBACK_EMAIL", "hr-uat@example.org")
    assert Settings().feedback_email == "hr-uat@example.org"
    monkeypatch.delenv("FEEDBACK_EMAIL")
    assert Settings().feedback_email == ""

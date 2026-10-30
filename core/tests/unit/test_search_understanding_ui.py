"""Unit — the LLM query read on BOTH search pages (Track I, PR I3), through the routes.

Drives ``TestClient(app)`` without the lifespan. The searches themselves are mocked
(``list_roles`` / ``search_jds``), the chat client is a fake handed in through the
``get_chat_client_factory`` dependency, and the rulebook is retuned per test. Pins:

* **Off (the shipped default): no client is ever built**, on either page, and the page
  shows no interpretation.
* **On:** the factory is called once; the search receives the GUARDED plan (words as
  typed first); the page shows the model's reading, the added keywords as links, what
  was ignored, and a "search the words as typed" link that carries ``plain=1``.
* **``plain=1`` switches it off for that search** — no client is built.
* The Builder's page shows no percentage for a meaning hit (rank only) and names the
  interpreted keyword a title hit came from.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterator
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from src.api.main import app, get_session
from src.api.routes import compose, compose_ui
from src.api.routes import library as library_route
from src.jd_bank import query_plan
from src.jd_bank.composer import SearchHit, SearchOutcome
from src.jd_bank.library import RoleListItem, RolePage
from src.jd_bank.query_plan import QueryPlan
from src.jd_core.rules import get_rules
from tests.unit.retuned_rules import retuned_search


@pytest.fixture(autouse=True)
def _clear_overrides() -> Iterator[None]:
    yield
    app.dependency_overrides.clear()


def _client() -> TestClient:
    async def override() -> AsyncIterator[object]:
        yield object()

    app.dependency_overrides[get_session] = override
    return TestClient(app)


class _FakeChat:
    def __init__(self, plan: QueryPlan) -> None:
        self._plan = plan
        self.closed = False

    async def chat_json(self, messages: object, model_cls: type, **_: Any) -> Any:
        return self._plan

    async def close(self) -> None:
        self.closed = True


class _FakeClose:
    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class _Factory:
    """Records how many clients the page asked for."""

    def __init__(self, plan: QueryPlan | None = None) -> None:
        self.plan = plan or QueryPlan(
            semantic_query="accounts payable clerk",
            title_keywords=["Accounts Payable Clerk"],
            employee_group="cupe",
        )
        self.built: list[_FakeChat] = []

    def __call__(self) -> _FakeChat:
        chat = _FakeChat(self.plan)
        self.built.append(chat)
        return chat


def _enable(monkeypatch: pytest.MonkeyPatch, **fields: Any) -> None:
    rules = retuned_search(get_rules(), query_understanding_enabled=True, **fields)
    monkeypatch.setattr(query_plan, "get_rules", lambda: rules)


def _role_item(title: str, matched_by: str | None = None) -> RoleListItem:
    return RoleListItem(
        canonical_id=uuid.uuid4(),
        cluster_id=uuid.uuid4(),
        title=title,
        status="draft",
        source_count=3,
        score=79.0,
        grade="B",
        matched_by=matched_by,  # type: ignore[arg-type]
    )


def _library(monkeypatch: pytest.MonkeyPatch, factory: _Factory) -> AsyncMock:
    """Mock the role search to echo the plan it was given, and install the factory."""

    async def fake_list_roles(session: object, **kwargs: Any) -> RolePage:
        plan = kwargs.get("plan")
        items = (
            _role_item("AP Clerk", "title"),
            _role_item("Accounts Payable Clerk", "keyword"),
        )
        return RolePage(
            items=items,
            total=2,
            limit=50,
            offset=0,
            q=kwargs["q"],
            sort="relevance",
            direction="asc",
            interpretation=plan,
        )

    mock = AsyncMock(side_effect=fake_list_roles)
    monkeypatch.setattr(library_route, "list_roles", mock)
    app.dependency_overrides[compose.get_chat_client_factory] = lambda: factory
    return mock


def _builder(monkeypatch: pytest.MonkeyPatch, factory: _Factory) -> AsyncMock:
    async def fake_search(query: str, **kwargs: Any) -> SearchOutcome:
        plan = kwargs.get("plan")
        hits = [
            SearchHit(
                cluster_id=uuid.uuid4(),
                title="Accounts Payable Clerk",
                employee_group="apsa",
                score=None,
                match="role_title",
                by_keyword="Accounts Payable Clerk",
            ),
            SearchHit(
                source_document_id=uuid.uuid4(),
                title="Payables Assistant",
                employee_group="apsa",
                score=0.91,
                match="semantic",
            ),
        ]
        return SearchOutcome(hits=hits, interpretation=plan)

    mock = AsyncMock(side_effect=fake_search)
    monkeypatch.setattr(compose_ui, "search_jds", mock)
    monkeypatch.setattr(
        compose_ui, "cluster_id_for_source", AsyncMock(return_value=None)
    )
    app.dependency_overrides[compose.get_embed_client] = lambda: _FakeClose()
    app.dependency_overrides[compose.get_neo4j_driver] = lambda: _FakeClose()
    app.dependency_overrides[compose.get_chat_client_factory] = lambda: factory
    return mock


# ── off: no client, no reading ──────────────────────────────────────────────────


def test_the_feature_ships_off() -> None:
    assert get_rules().search.query_understanding_enabled is False


def test_library_off_builds_no_client_and_shows_no_reading(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory = _Factory()
    mock = _library(monkeypatch, factory)
    html = _client().get("/jd-bank/ui/library?q=AP+clerk").text
    assert factory.built == []
    assert mock.await_args.kwargs["plan"] is None
    assert "Read as:" not in html


def test_builder_off_builds_no_client_and_shows_no_reading(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory = _Factory()
    mock = _builder(monkeypatch, factory)
    html = _client().get("/jd-bank/ui/compose/search?q=AP+clerk").text
    assert factory.built == []
    assert mock.await_args.kwargs["plan"] is None
    assert "Read as:" not in html


# ── on: one client, the guarded plan, the reading on the page ───────────────────


def test_library_on_reads_the_query_and_shows_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable(monkeypatch)
    factory = _Factory()
    mock = _library(monkeypatch, factory)
    html = _client().get("/jd-bank/ui/library?q=AP+clerk").text
    assert len(factory.built) == 1 and factory.built[0].closed
    plan = mock.await_args.kwargs["plan"]
    assert plan is not None
    assert plan.title_keywords == ("AP clerk", "Accounts Payable Clerk")
    assert plan.employee_group is None  # CUPE was not typed → dropped
    assert "Read as:" in html
    assert "accounts payable clerk" in html
    assert 'href="/jd-bank/ui/library?q=Accounts%20Payable%20Clerk"' in html
    assert "plain=1" in html and "search the words as typed" in html
    assert "ignored:" in html and "CUPE" in html
    assert "Interpreted title" in html
    assert "% similar" not in html and "similar" not in html.lower().replace(
        "similar spelling", ""
    )


def test_library_plain_switches_the_reading_off_for_that_search(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable(monkeypatch)
    factory = _Factory()
    mock = _library(monkeypatch, factory)
    html = _client().get("/jd-bank/ui/library?q=AP+clerk&plain=1").text
    assert factory.built == []
    assert mock.await_args.kwargs["plan"] is None
    assert "Read as:" not in html


def test_builder_on_reads_the_query_and_shows_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable(monkeypatch)
    factory = _Factory()
    mock = _builder(monkeypatch, factory)
    html = _client().get("/jd-bank/ui/compose/search?q=AP+clerk").text
    assert len(factory.built) == 1 and factory.built[0].closed
    plan = mock.await_args.kwargs["plan"]
    assert plan is not None and plan.title_keywords[0] == "AP clerk"
    assert "Read as:" in html
    assert "interpreted as “Accounts Payable Clerk”" in html
    assert "related by meaning" in html
    assert "% similar" not in html  # rank only, never a cosine as a percentage
    assert "plain=1" in html and "form=" in html


def test_builder_plain_switches_the_reading_off_for_that_search(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable(monkeypatch)
    factory = _Factory()
    mock = _builder(monkeypatch, factory)
    _client().get("/jd-bank/ui/compose/search?q=AP+clerk&plain=1")
    assert factory.built == []
    assert mock.await_args.kwargs["plan"] is None


def test_a_dead_model_still_renders_the_plain_search(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable(monkeypatch)

    def broken() -> Any:
        raise RuntimeError("inference host down")

    mock = _library(monkeypatch, _Factory())
    app.dependency_overrides[compose.get_chat_client_factory] = lambda: broken
    resp = _client().get("/jd-bank/ui/library?q=AP+clerk")
    assert resp.status_code == 200
    assert mock.await_args.kwargs["plan"] is None
    assert "AP Clerk" in resp.text

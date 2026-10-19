"""Track I1 — the library route's search transport: the optional embed clients are
injected and closed, a "why it matched" label is shown but never a similarity, and a
degraded meaning pass shows a banner (never a 500).

Same harness as ``test_library_ui.py``: ``list_roles`` is monkeypatched, real templates
render real view models.
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock

import pytest

from src.api.main import app
from src.api.routes import compose as compose_route
from src.api.routes import library as library_route
from src.jd_bank.library import RoleListItem
from tests.unit.test_library_ui import (  # noqa: F401
    _clear_overrides,
    _role_page,
    make_client,
)


class _Closable:
    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


def _item(title: str, matched_by: str | None) -> RoleListItem:
    return RoleListItem(
        canonical_id=uuid.uuid4(),
        cluster_id=uuid.uuid4(),
        title=title,
        status="draft",
        source_count=2,
        score=70.0,
        grade="B",
        matched_by=matched_by,  # type: ignore[arg-type]
    )


def _inject(embed: Any, driver: Any) -> None:
    app.dependency_overrides[library_route.get_optional_embed_client] = lambda: embed
    app.dependency_overrides[library_route.get_optional_neo4j_driver] = lambda: driver


def test_search_passes_clients_closes_them_and_labels_why(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = _role_page(
        items=(
            _item("Accounts Clerk", "title"),
            _item("Payables Assistant", "meaning"),
        ),
        total=2,
        q="accounts",
        sort="relevance",
    )
    mock = AsyncMock(return_value=page)
    monkeypatch.setattr(library_route, "list_roles", mock)
    embed, driver = _Closable(), _Closable()
    client = make_client()
    _inject(embed, driver)

    body = client.get("/jd-bank/ui/library", params={"q": "accounts"}).text

    assert mock.await_args.kwargs["embed_client"] is embed
    assert mock.await_args.kwargs["neo4j_driver"] is driver
    assert embed.closed and driver.closed
    assert "Why it matched" in body
    assert "Related by meaning" in body and ">Title<" in body
    assert "%" not in body.split("<table>")[1].split("</table>")[0].replace("%20", "")
    assert "Heads up" not in body


def test_default_sort_is_unset_so_a_search_is_rank_ordered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock = AsyncMock(return_value=_role_page())
    monkeypatch.setattr(library_route, "list_roles", mock)
    client = make_client()
    _inject(None, None)

    client.get("/jd-bank/ui/library", params={"q": "x"})

    assert mock.await_args.kwargs["sort"] == ""


def test_degraded_meaning_search_shows_the_banner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    page = _role_page(
        items=(_item("Accounts Clerk", "title"),),
        total=1,
        q="clerk",
        sort="relevance",
        banner="Search by meaning is unavailable right now.",
    )
    monkeypatch.setattr(library_route, "list_roles", AsyncMock(return_value=page))
    client = make_client()
    _inject(_Closable(), _Closable())

    resp = client.get("/jd-bank/ui/library", params={"q": "clerk"})

    assert resp.status_code == 200
    assert "Search by meaning is unavailable" in resp.text
    assert "Accounts Clerk" in resp.text


def test_a_client_that_cannot_be_built_still_renders_with_a_banner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The optional factory returns ``None`` on a misconfiguration; the library must
    stay up and say meaning search is off rather than silently dropping it."""
    page = _role_page(items=(_item("Accounts Clerk", "title"),), total=1, q="clerk")
    monkeypatch.setattr(library_route, "list_roles", AsyncMock(return_value=page))
    client = make_client()
    _inject(None, None)

    resp = client.get("/jd-bank/ui/library", params={"q": "clerk"})

    assert resp.status_code == 200
    assert "Search by meaning is unavailable" in resp.text


def test_no_banner_without_a_query_even_if_clients_are_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        library_route, "list_roles", AsyncMock(return_value=_role_page())
    )
    client = make_client()
    _inject(None, None)

    assert "Search by meaning" not in client.get("/jd-bank/ui/library").text


def test_the_route_reuses_the_composers_optional_factories() -> None:
    assert (
        library_route.get_optional_embed_client
        is compose_route.get_optional_embed_client
    )
    assert (
        library_route.get_optional_neo4j_driver
        is compose_route.get_optional_neo4j_driver
    )

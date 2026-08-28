"""Unit tests for the server-rendered content library (the browsable JD Bank) — a thin
read-only HTML transport over :mod:`src.jd_bank.library`.

Mirrors ``test_review_ui.py``: drive ``TestClient(app)`` without the lifespan, override
``get_session`` with a fake, and monkeypatch every ``src.api.routes.library.<fn>`` read
function so the route logic (param passthrough, the single service call, 404 mapping,
and HTML rendering through the real templates) is tested in isolation from the DB. Real
view models flow through so the templates are exercised, not stubbed.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterator
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from src.api.main import app, get_session
from src.api.routes import library as library_route
from src.jd_bank.library import (
    CollectionStats,
    FamilyCandidate,
    MemberJD,
    RoleListItem,
    RolePage,
    RoleRef,
    RoleView,
    SourceJDView,
    SourceListItem,
    SourcePage,
)
from src.jd_core.models.parsed_jd import JobClassification


class FakeSession:
    pass


@pytest.fixture(autouse=True)
def _clear_overrides() -> Iterator[None]:
    yield
    app.dependency_overrides.clear()


def make_client() -> TestClient:
    async def override_session() -> AsyncIterator[FakeSession]:
        yield FakeSession()

    app.dependency_overrides[get_session] = override_session
    return TestClient(app, follow_redirects=False)


# --- the source-JD reader -------------------------------------------------------------


def _source_view(**update: object) -> SourceJDView:
    base = dict(
        source_document_id=uuid.uuid4(),
        filename="analyst.docx",
        title="Financial Analyst",
        employee_group="apsa",
        department="Finance",
        grade="A1",
        position_number="P123",
        parse_confidence=0.87,
        rendered_text="Manages the annual budget cycle end to end.",
        role=None,
    )
    base.update(update)
    return SourceJDView(**base)


def test_source_jd_renders_readable_content(monkeypatch: pytest.MonkeyPatch) -> None:
    view = _source_view()
    monkeypatch.setattr(library_route, "get_source_jd", AsyncMock(return_value=view))
    client = make_client()

    resp = client.get(f"/jd-bank/ui/jd/{view.source_document_id}")

    assert resp.status_code == 200
    body = resp.text
    assert "Financial Analyst" in body
    assert "analyst.docx" in body
    # The actual content is rendered — not just a filename/metadata.
    assert "Manages the annual budget cycle end to end." in body


def test_source_jd_shows_role_back_link(monkeypatch: pytest.MonkeyPatch) -> None:
    cluster_id = uuid.uuid4()
    view = _source_view(
        role=RoleRef(
            cluster_id=cluster_id,
            canonical_id=uuid.uuid4(),
            title="Budget Analyst",
            status="draft",
        )
    )
    monkeypatch.setattr(library_route, "get_source_jd", AsyncMock(return_value=view))
    client = make_client()

    resp = client.get(f"/jd-bank/ui/jd/{view.source_document_id}")

    assert resp.status_code == 200
    assert f"/jd-bank/ui/role/{cluster_id}" in resp.text
    assert "Budget Analyst" in resp.text


def test_source_jd_shows_grade_with_provenance(monkeypatch: pytest.MonkeyPatch) -> None:
    view = _source_view(
        classification=JobClassification(scheme="cupe", value="8", source="parsed")
    )
    monkeypatch.setattr(library_route, "get_source_jd", AsyncMock(return_value=view))

    body = make_client().get(f"/jd-bank/ui/jd/{view.source_document_id}").text

    assert "8" in body and "cupe" in body and "parsed" in body  # value/scheme/source


def test_source_jd_unknown_returns_404(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(library_route, "get_source_jd", AsyncMock(return_value=None))
    client = make_client()

    resp = client.get(f"/jd-bank/ui/jd/{uuid.uuid4()}")

    assert resp.status_code == 404
    assert "Not found" in resp.text


# --- the role (roles → sources) -------------------------------------------------------


def test_role_renders_content_and_member_links(monkeypatch: pytest.MonkeyPatch) -> None:
    cluster_id, canonical_id = uuid.uuid4(), uuid.uuid4()
    member_a, member_b = uuid.uuid4(), uuid.uuid4()
    role = RoleView(
        canonical_id=canonical_id,
        cluster_id=cluster_id,
        title="Program Coordinator",
        status="draft",
        version=1,
        score=82.0,
        grade="A",
        rendered_text="Coordinates the program across departments.",
        members=(
            MemberJD(
                source_document_id=member_a,
                filename="a.docx",
                title="Coordinator A",
                employee_group="apsa",
                parsed=True,
            ),
            MemberJD(
                source_document_id=member_b,
                filename="b.docx",
                title=None,
                employee_group=None,
                parsed=False,
            ),
        ),
        source_count=2,
    )
    monkeypatch.setattr(library_route, "get_role", AsyncMock(return_value=role))
    client = make_client()

    resp = client.get(f"/jd-bank/ui/role/{cluster_id}")

    assert resp.status_code == 200
    body = resp.text
    assert "Program Coordinator" in body
    assert "Coordinates the program across departments." in body
    assert "distilled from" in body.lower()
    # a parsed member links to the reader; an unparsed one does not
    assert f"/jd-bank/ui/jd/{member_a}" in body
    assert f"/jd-bank/ui/jd/{member_b}" not in body
    # links back to the review queue for approval (the sole approval surface)
    assert f"/jd-bank/ui/review/{canonical_id}" in body


def test_role_unknown_returns_404(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(library_route, "get_role", AsyncMock(return_value=None))
    client = make_client()

    resp = client.get(f"/jd-bank/ui/role/{uuid.uuid4()}")

    assert resp.status_code == 404


# --- the roles library ----------------------------------------------------------------


def _role_item(title: str) -> RoleListItem:
    return RoleListItem(
        canonical_id=uuid.uuid4(),
        cluster_id=uuid.uuid4(),
        title=title,
        status="draft",
        source_count=3,
        score=79.0,
        grade="B",
    )


def _role_page(**update: object) -> RolePage:
    base = dict(
        items=(), total=0, limit=50, offset=0, q="", sort="title", direction="asc"
    )
    base.update(update)
    return RolePage(**base)


def test_library_lists_roles_and_passes_query(monkeypatch: pytest.MonkeyPatch) -> None:
    items = (_role_item("Finance Analyst"), _role_item("Finance Manager"))
    mock = AsyncMock(return_value=_role_page(items=items, total=2, q="finance"))
    monkeypatch.setattr(library_route, "list_roles", mock)
    client = make_client()

    resp = client.get("/jd-bank/ui/library", params={"q": "finance"})

    assert resp.status_code == 200
    body = resp.text
    assert "Finance Analyst" in body and "Finance Manager" in body
    assert f"/jd-bank/ui/role/{items[0].cluster_id}" in body
    # Quality-grade column labelled "Quality" (not a pay grade); no Seniority column.
    assert "Quality" in body and "Seniority" not in body
    mock.assert_awaited_once()
    assert mock.await_args.kwargs["q"] == "finance"


def test_library_columns_are_sortable(monkeypatch: pytest.MonkeyPatch) -> None:
    """Column headings link to the same list sorted by that column; the active column
    toggles direction and shows an arrow."""
    mock = AsyncMock(
        return_value=_role_page(
            items=(_role_item("Analyst"),), total=1, sort="score", direction="asc"
        )
    )
    monkeypatch.setattr(library_route, "list_roles", mock)
    client = make_client()

    body = client.get("/jd-bank/ui/library").text

    # A clickable heading for each sortable column.
    assert "sort=title" in body
    assert "sort=sources" in body
    # The ACTIVE column (score, asc) offers to flip to desc and shows the ▲ arrow.
    assert "sort=score&amp;dir=desc" in body
    assert "▲" in body


def test_library_sort_params_pass_through(monkeypatch: pytest.MonkeyPatch) -> None:
    mock = AsyncMock(return_value=_role_page())
    monkeypatch.setattr(library_route, "list_roles", mock)
    client = make_client()

    client.get("/jd-bank/ui/library", params={"sort": "grade", "dir": "desc"})

    assert mock.await_args.kwargs["sort"] == "grade"
    assert mock.await_args.kwargs["direction"] == "desc"


def test_library_next_link_only_when_more(monkeypatch: pytest.MonkeyPatch) -> None:
    items = tuple(_role_item(f"Role {i}") for i in range(2))
    mock = AsyncMock(return_value=_role_page(items=items, total=5, limit=2))
    monkeypatch.setattr(library_route, "list_roles", mock)
    client = make_client()

    resp = client.get("/jd-bank/ui/library", params={"limit": 2})

    assert resp.status_code == 200
    assert "Showing 1–2 of 5" in resp.text
    assert "offset=2" in resp.text  # a next page exists
    assert "← Prev" not in resp.text  # but not a prev on the first page


def test_library_empty_state(monkeypatch: pytest.MonkeyPatch) -> None:
    mock = AsyncMock(return_value=_role_page(q="zzz"))
    monkeypatch.setattr(library_route, "list_roles", mock)
    client = make_client()

    resp = client.get("/jd-bank/ui/library", params={"q": "zzz"})

    assert resp.status_code == 200
    assert "No roles match" in resp.text


# --- the flat source archive ----------------------------------------------------------


def test_archive_lists_source_files(monkeypatch: pytest.MonkeyPatch) -> None:
    sid = uuid.uuid4()
    items = (
        SourceListItem(
            source_document_id=sid,
            filename="finance-analyst.docx",
            title="Finance Analyst",
            employee_group="apsa",
            parsed=True,
        ),
    )
    mock = AsyncMock(
        return_value=SourcePage(items=items, total=1, limit=50, offset=0, q="finance")
    )
    monkeypatch.setattr(library_route, "list_source_jds", mock)
    client = make_client()

    resp = client.get("/jd-bank/ui/archive", params={"q": "finance"})

    assert resp.status_code == 200
    body = resp.text
    assert "finance-analyst.docx" in body
    assert f"/jd-bank/ui/jd/{sid}" in body
    assert mock.await_args.kwargs["q"] == "finance"


def test_nav_exposes_jd_bank(monkeypatch: pytest.MonkeyPatch) -> None:
    """The primary nav links to the library on every page (regression: the app used to
    surface only dashboards/queue, never the content)."""
    mock = AsyncMock(return_value=_role_page())
    monkeypatch.setattr(library_route, "list_roles", mock)
    client = make_client()

    resp = client.get("/jd-bank/ui/library")

    assert resp.status_code == 200
    assert 'href="/jd-bank/ui/library">🏦 JD Bank' in resp.text


# --- the collection page (Phase A2) ---------------------------------------------------


def _collection_stats(**update: object) -> CollectionStats:
    base = {
        "label": "Information Technology",
        "slug": "it",
        "roles": 45,
        "source_documents": 469,
        "approvable": 32,
        "recall_note": "Membership comes from the ITP classification family.",
    }
    return CollectionStats(**{**base, **update})


def _candidate(title: str, *, duty: int = 9, title_hits: int = 2) -> FamilyCandidate:
    return FamilyCandidate(
        cluster_id=uuid.uuid4(),
        canonical_id=uuid.uuid4(),
        title=title,
        status="DRAFT",
        source_count=4,
        department=None,
        duty_matches=duty,
        title_matches=title_hits,
    )


def test_collection_leads_with_the_compression_not_a_bare_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The two numbers must appear together: a document count alone reads as loss."""
    monkeypatch.setattr(
        library_route, "family_for", lambda slug: object() if slug == "it" else None
    )
    monkeypatch.setattr(
        library_route, "collection_stats", AsyncMock(return_value=_collection_stats())
    )
    monkeypatch.setattr(
        library_route, "resolve_members", AsyncMock(return_value=frozenset())
    )
    monkeypatch.setattr(
        library_route,
        "list_roles",
        AsyncMock(
            return_value=RolePage(
                items=(),
                total=0,
                limit=50,
                offset=0,
                q="",
                sort="title",
                direction="asc",
            )
        ),
    )
    response = make_client().get("/jd-bank/ui/collection/it")

    assert response.status_code == 200
    body = response.text
    assert "469" in body and "45" in body
    assert "32" in body
    # The family must publish how it under-recalls — see the measurement.
    assert "ITP classification family" in body


def test_unknown_collection_is_a_404_not_an_empty_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An empty page for a mistyped slug looks like a family with no roles."""
    monkeypatch.setattr(library_route, "family_for", lambda slug: None)
    response = make_client().get("/jd-bank/ui/collection/nope")
    assert response.status_code == 404


def test_queue_shows_match_counts_never_a_percentage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The score is a count of matched terms. Rendering it as a percentage or a
    confidence would present a verdict the measurement showed is wrong at every
    cutoff."""
    monkeypatch.setattr(library_route, "family_for", lambda slug: object())
    monkeypatch.setattr(
        library_route, "collection_stats", AsyncMock(return_value=_collection_stats())
    )
    monkeypatch.setattr(
        library_route, "resolve_members", AsyncMock(return_value=frozenset())
    )
    monkeypatch.setattr(
        library_route,
        "rank_candidates",
        AsyncMock(return_value=(_candidate("Library Systems Technician"),)),
    )
    monkeypatch.setattr(
        library_route,
        "list_roles",
        AsyncMock(
            return_value=RolePage(
                items=(),
                total=0,
                limit=50,
                offset=0,
                q="",
                sort="title",
                direction="asc",
            )
        ),
    )
    response = make_client().get("/jd-bank/ui/collection/it?queue=1")

    assert response.status_code == 200
    body = response.text
    assert "Library Systems Technician" in body
    assert "11" in body, "the matched-term count is the evidence shown"
    assert (
        "%" not in body.split("Candidates for review")[1].split("</table>")[0]
    ), "a match count must never be rendered as a percentage"
    # A candidate is a question, and the page must say so.
    assert "questions, not members" in body


def test_queue_names_an_unstated_department_rather_than_leaving_it_blank(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Department is known for ~72% of roles. A blank cell reads as "no home"; the
    facet must show its own coverage rather than silently dropping it."""
    monkeypatch.setattr(library_route, "family_for", lambda slug: object())
    monkeypatch.setattr(
        library_route, "collection_stats", AsyncMock(return_value=_collection_stats())
    )
    monkeypatch.setattr(
        library_route, "resolve_members", AsyncMock(return_value=frozenset())
    )
    monkeypatch.setattr(
        library_route,
        "rank_candidates",
        AsyncMock(return_value=(_candidate("Technical Support Specialist"),)),
    )
    monkeypatch.setattr(
        library_route,
        "list_roles",
        AsyncMock(
            return_value=RolePage(
                items=(),
                total=0,
                limit=50,
                offset=0,
                q="",
                sort="title",
                direction="asc",
            )
        ),
    )
    response = make_client().get("/jd-bank/ui/collection/it?queue=1")
    assert "(not stated)" in response.text

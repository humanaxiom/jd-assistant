"""Phase 5.4 — search for an existing JD + clone it into the Builder.

Three seams, all fully unit-testable (the Neo4j vector read and the Postgres join are
injected/monkeypatched, so no live infra):

1. ``jd_to_answers`` round-trips through ``assemble_jd`` — cloning preserves the JD.
2. ``search_similar_jds`` embeds the query once, filters CUPE/WJQ + unparsed hits, and
   caps at ``limit`` (the mapping/filter logic over faked I/O).
3. the ``/search`` and ``/clone`` routes transport the result and close their clients.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from src.api.main import app, get_session
from src.api.routes import compose
from src.jd_bank.composer import (
    ComposerAnswers,
    SearchHit,
    assemble_jd,
    jd_to_answers,
)
from src.jd_bank.composer import search as search_mod
from src.jd_core.models.parsed_jd import (
    SFUDuty,
    SFUJobDescription,
    SFUQualification,
    SFURelationships,
)


def _clean_jd() -> SFUJobDescription:
    return SFUJobDescription(
        title="Software Developer",
        department="Information Services",
        employee_group="apsa",
        about_sfu_present=True,
        position_summary=" ".join(["word"] * 120),
        duties=[
            SFUDuty(action_verb=v, statement=f"{v} the program")
            for v in ("Manages", "Coordinates", "Provides")
        ],
        decision_making=["Approves expenditures up to $5k"],
        problem_solving=["Resolves scheduling conflicts independently"],
        relationships=SFURelationships(
            supervisory="Supervises 2 staff", internal=["Finance"], external=["Vendors"]
        ),
        qualifications=[
            SFUQualification(text="Bachelor's degree", kind="education"),
            SFUQualification(
                text="Excellent knowledge of databases",
                kind="knowledge",
                modifier="excellent",
            ),
            SFUQualification(text="Python", kind="skill", modifier="advanced"),
            SFUQualification(text="Ability to work cooperatively", kind="ability"),
        ],
        territorial_acknowledgement_present=True,
        employment_equity_present=True,
    )


# --- 1. clone round-trip -------------------------------------------------------------


def test_jd_to_answers_round_trips_through_assemble() -> None:
    jd = _clean_jd()
    rebuilt = assemble_jd(jd_to_answers(jd))

    assert rebuilt.title == jd.title
    assert rebuilt.department == jd.department
    assert rebuilt.employee_group == jd.employee_group
    assert rebuilt.position_summary == jd.position_summary
    assert [d.statement for d in rebuilt.duties] == [d.statement for d in jd.duties]
    # Qualifications preserved, in the KSA order the assembler enforces.
    assert [(q.kind, q.text) for q in rebuilt.qualifications] == [
        (q.kind, q.text) for q in jd.qualifications
    ]
    assert rebuilt.relationships is not None
    assert rebuilt.relationships.supervisory == "Supervises 2 staff"
    # All three mandated boilerplate booleans survive the round-trip.
    assert rebuilt.about_sfu_present is True
    assert rebuilt.territorial_acknowledgement_present is True


# --- 2. search mapping / filtering ---------------------------------------------------


class _FakeEmbed:
    def __init__(self, vector: list[float]) -> None:
        self._vector = vector
        self.calls: list[list[str]] = []
        self.closed = False

    async def embed_batch(self, texts: Any) -> list[list[float]]:
        self.calls.append(list(texts))
        return [self._vector]

    async def close(self) -> None:
        self.closed = True


def _jd(title: str, group: str) -> SFUJobDescription:
    return SFUJobDescription(title=title, employee_group=group)  # type: ignore[arg-type]


async def test_search_embeds_once_filters_and_caps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    a, b_cupe, c_missing, d = (uuid.uuid4() for _ in range(4))
    nearest = [(a, 0.99), (b_cupe, 0.98), (c_missing, 0.97), (d, 0.96)]

    async def fake_nearest(driver: Any, vector: Any, k: int) -> list[Any]:
        return nearest

    parsed = {a: _jd("A", "apsa"), b_cupe: _jd("B", "cupe"), d: _jd("D", "poly")}

    async def fake_load(session: Any, ids: Any) -> dict[Any, Any]:
        return parsed

    monkeypatch.setattr(search_mod, "_nearest_source_ids", fake_nearest)
    monkeypatch.setattr(search_mod, "_load_latest_parsed", fake_load)

    embed = _FakeEmbed([0.1] * 768)
    hits = await search_mod.search_similar_jds(
        "budget analyst",
        embed_client=embed,  # type: ignore[arg-type]
        neo4j_driver=object(),  # type: ignore[arg-type]
        session=object(),  # type: ignore[arg-type]
        limit=10,
    )

    assert embed.calls == [["budget analyst"]]  # embedded once
    # B is CUPE (excluded — Builder is JDFN-only), C has no parsed JD (skipped).
    assert [h.source_document_id for h in hits] == [a, d]
    assert hits[0].score == 0.99


async def test_search_respects_the_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    ids = [(uuid.uuid4(), 0.9 - i * 0.01) for i in range(5)]
    parsed = {sid: _jd(f"role-{i}", "apsa") for i, (sid, _) in enumerate(ids)}

    async def fake_nearest(driver: Any, vector: Any, k: int) -> list[Any]:
        return ids

    async def fake_load(session: Any, sids: Any) -> dict[Any, Any]:
        return parsed

    monkeypatch.setattr(search_mod, "_nearest_source_ids", fake_nearest)
    monkeypatch.setattr(search_mod, "_load_latest_parsed", fake_load)

    hits = await search_mod.search_similar_jds(
        "x",
        embed_client=_FakeEmbed([0.0] * 768),  # type: ignore[arg-type]
        neo4j_driver=object(),  # type: ignore[arg-type]
        session=object(),  # type: ignore[arg-type]
        limit=2,
    )
    assert len(hits) == 2


async def test_blank_query_returns_nothing_without_embedding() -> None:
    embed = _FakeEmbed([0.0] * 768)
    hits = await search_mod.search_similar_jds(
        "   ",
        embed_client=embed,  # type: ignore[arg-type]
        neo4j_driver=object(),  # type: ignore[arg-type]
        session=object(),  # type: ignore[arg-type]
    )
    assert hits == []
    assert embed.calls == []  # never touched the model


# --- 3. routes -----------------------------------------------------------------------


class _FakeClose:
    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


@pytest.fixture(autouse=True)
def _clear_overrides() -> Iterator[None]:
    yield
    app.dependency_overrides.clear()


def _override_session() -> None:
    async def override() -> AsyncIterator[object]:
        yield object()

    app.dependency_overrides[get_session] = override


def test_clone_route_returns_answers(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_load(session: Any, sid: Any) -> ComposerAnswers:
        return ComposerAnswers(title="Cloned role")

    monkeypatch.setattr(compose, "load_clone_answers", fake_load)
    _override_session()

    resp = TestClient(app).get(f"/jd-bank/compose/clone/{uuid.uuid4()}")
    assert resp.status_code == 200
    assert resp.json()["title"] == "Cloned role"


def test_clone_route_404_when_no_parsed_jd(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_load(session: Any, sid: Any) -> None:
        return None

    monkeypatch.setattr(compose, "load_clone_answers", fake_load)
    _override_session()

    resp = TestClient(app).get(f"/jd-bank/compose/clone/{uuid.uuid4()}")
    assert resp.status_code == 404


def test_search_route_transports_hits_and_closes_clients(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hit = SearchHit(
        source_document_id=uuid.uuid4(),
        title="Financial Analyst",
        employee_group="apsa",
        score=0.91,
    )

    async def fake_search(query: str, **kwargs: Any) -> list[SearchHit]:
        return [hit]

    monkeypatch.setattr(compose, "search_similar_jds", fake_search)
    embed, neo = _FakeClose(), _FakeClose()
    app.dependency_overrides[compose.get_embed_client] = lambda: embed
    app.dependency_overrides[compose.get_neo4j_driver] = lambda: neo
    _override_session()

    resp = TestClient(app).get("/jd-bank/compose/search?q=analyst&limit=5")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["title"] == "Financial Analyst"
    assert embed.closed is True
    assert neo.closed is True

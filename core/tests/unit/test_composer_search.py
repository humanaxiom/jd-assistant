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
            # A compliant JD opens the Relationships section with SFU's mandated header
            # (HR-056) — so the clone round-trip is idempotent: re-assembling with
            # boilerplate on does not double-insert it.
            supervisory=(
                "Establishes and maintains relationships and alliances. "
                "Supervises 2 staff"
            ),
            internal=["Finance"],
            external=["Vendors"],
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
    # Idempotent: the header the source already carried is preserved, not doubled.
    assert rebuilt.relationships.supervisory == (
        "Establishes and maintains relationships and alliances. Supervises 2 staff"
    )
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


async def _no_clusters_fn(session: Any, ids: Any) -> dict[Any, Any]:
    """No cluster membership — a test that is not about role collapsing."""
    return {}


def _no_title_matches(monkeypatch: pytest.MonkeyPatch) -> None:
    """Silence both TITLE passes so a test can drive the SEMANTIC pass alone.

    ``search_similar_jds`` now queries Postgres for harmonized-role and source-document
    title matches before it embeds anything (the fix for "an exact title query returns
    unrelated roles"), so a test that only fakes the vector seams would otherwise reach
    a real ``session``."""

    async def _no_roles(session: Any, query: str, *, limit: int) -> list[Any]:
        return []

    async def _none(session: Any, query: str, *, limit: int) -> dict[Any, Any]:
        return {}

    async def _no_clusters(session: Any, ids: Any) -> dict[Any, Any]:
        return {}

    monkeypatch.setattr(search_mod, "_clusters_for_sources", _no_clusters)

    monkeypatch.setattr(search_mod, "_role_title_matches", _no_roles)
    monkeypatch.setattr(search_mod, "_title_matches", _none)


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

    _no_title_matches(monkeypatch)
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


async def test_an_exact_title_query_returns_that_title_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """THE REPORTED DEFECT. Typing a role's exact title returned unrelated roles.

    The document vectors deliberately EXCLUDE the title
    (``embeddings.yaml: include_title_in_document: false``) — that exclusion is what
    makes ``bank/similarity`` "title-agnostic by construction" for dedup/clustering —
    so a title query has nothing to match on. Measured against the live index: the top
    25 for "AV Systems Analyst" contained none of the 12 documents with that title, and
    the whole top-25 spanned 0.8042–0.8176 (a 0.013 spread — flat noise, all "81%").

    Fixed in the search layer, not the vector substrate: an exact/near TITLE match is
    looked up in Postgres and ranked ABOVE the semantic neighbours. Flipping
    ``include_title_in_document`` would have "fixed" this by breaking dedup."""
    titled, semantic = uuid.uuid4(), uuid.uuid4()

    async def fake_titles(session: Any, query: str, *, limit: int) -> dict[Any, Any]:
        assert query == "AV Systems Analyst"
        return {titled: _jd("AV Systems Analyst", "apsa")}

    async def fake_nearest(driver: Any, vector: Any, k: int) -> list[Any]:
        return [(semantic, 0.8176)]

    async def fake_load(session: Any, ids: Any) -> dict[Any, Any]:
        return {semantic: _jd("Associate Director, Advancement", "apsa")}

    async def _no_roles(session: Any, query: str, *, limit: int) -> list[Any]:
        return []

    monkeypatch.setattr(search_mod, "_role_title_matches", _no_roles)
    monkeypatch.setattr(search_mod, "_clusters_for_sources", _no_clusters_fn)
    monkeypatch.setattr(search_mod, "_title_matches", fake_titles)
    monkeypatch.setattr(search_mod, "_nearest_source_ids", fake_nearest)
    monkeypatch.setattr(search_mod, "_load_latest_parsed", fake_load)

    hits = await search_mod.search_similar_jds(
        "AV Systems Analyst",
        embed_client=_FakeEmbed([0.1] * 768),  # type: ignore[arg-type]
        neo4j_driver=object(),  # type: ignore[arg-type]
        session=object(),  # type: ignore[arg-type]
        limit=10,
    )

    assert [h.source_document_id for h in hits] == [titled, semantic]
    assert hits[0].title == "AV Systems Analyst"
    # The two are DIFFERENT measures and must not be conflated into one number: a
    # title match carries no cosine, and reporting one would invent a similarity.
    assert hits[0].match == "title"
    assert hits[0].score is None
    assert hits[1].match == "semantic"
    assert hits[1].score == 0.8176


async def test_a_harmonized_role_is_found_by_its_own_title(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Searching source documents alone cannot find most harmonized roles.

    MEASURED: **746 of 1,222 harmonized role titles (61%) appear on NO source
    document** — harmonization renames the role, so the title the author types exists
    only on ``canonical_jds``. A title pass over ``parsed_jds`` therefore misses the
    majority of the Bank's own roles, which is the deeper half of "searching for an
    exact title doesn't pull it".

    A role hit is the PREFERRED start (cloning the harmonized role, not a raw archive
    parse), so it outranks both source-document passes."""
    cluster, source = uuid.uuid4(), uuid.uuid4()

    async def fake_roles(session: Any, query: str, *, limit: int) -> list[Any]:
        return [(cluster, "Learning Space Technologist", "apsa")]

    async def fake_titles(session: Any, query: str, *, limit: int) -> dict[Any, Any]:
        return {}

    async def fake_nearest(driver: Any, vector: Any, k: int) -> list[Any]:
        return [(source, 0.81)]

    async def fake_load(session: Any, ids: Any) -> dict[Any, Any]:
        return {source: _jd("Something Else", "apsa")}

    monkeypatch.setattr(search_mod, "_role_title_matches", fake_roles)
    monkeypatch.setattr(search_mod, "_title_matches", fake_titles)
    monkeypatch.setattr(search_mod, "_clusters_for_sources", _no_clusters_fn)
    monkeypatch.setattr(search_mod, "_nearest_source_ids", fake_nearest)
    monkeypatch.setattr(search_mod, "_load_latest_parsed", fake_load)

    hits = await search_mod.search_similar_jds(
        "Learning Space Technologist",
        embed_client=_FakeEmbed([0.1] * 768),  # type: ignore[arg-type]
        neo4j_driver=object(),  # type: ignore[arg-type]
        session=object(),  # type: ignore[arg-type]
        limit=10,
    )

    assert hits[0].title == "Learning Space Technologist"
    assert hits[0].match == "role_title"
    assert hits[0].cluster_id == cluster
    # A role is not an archive document; it has no source_document_id to read.
    assert hits[0].source_document_id is None
    assert hits[0].score is None
    assert hits[1].match == "semantic"


async def test_role_title_matches_stay_jdfn_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The role pass is under the SAME JDFN scope as the other two (HR-143/194)."""

    async def fake_roles(session: Any, query: str, *, limit: int) -> list[Any]:
        return [(uuid.uuid4(), "Clerk", "cupe")]

    async def fake_titles(session: Any, query: str, *, limit: int) -> dict[Any, Any]:
        return {}

    async def fake_nearest(driver: Any, vector: Any, k: int) -> list[Any]:
        return []

    async def fake_load(session: Any, ids: Any) -> dict[Any, Any]:
        return {}

    monkeypatch.setattr(search_mod, "_role_title_matches", fake_roles)
    monkeypatch.setattr(search_mod, "_clusters_for_sources", _no_clusters_fn)
    monkeypatch.setattr(search_mod, "_title_matches", fake_titles)
    monkeypatch.setattr(search_mod, "_nearest_source_ids", fake_nearest)
    monkeypatch.setattr(search_mod, "_load_latest_parsed", fake_load)

    hits = await search_mod.search_similar_jds(
        "Clerk",
        embed_client=_FakeEmbed([0.1] * 768),  # type: ignore[arg-type]
        neo4j_driver=object(),  # type: ignore[arg-type]
        session=object(),  # type: ignore[arg-type]
        limit=10,
    )
    assert hits == []


async def test_documents_collapse_into_the_role_they_were_harmonized_into(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One role, one row. Listing a role and then its own member documents beneath it
    is how a CORRECTLY harmonized role reads as "nothing was combined".

    Reported case: searching "peoplesoft" showed the harmonized "PeopleSoft Developer"
    role (17 sources) and then, underneath, the 16 "Senior Developer, PeopleSoft"
    documents that ARE that role — verified against the DB: all 16 map to exactly one
    cluster, whose canonical is that role. Harmonization was right; the page was not.

    A document whose cluster is NOT already listed still appears — it carries new
    information."""
    cluster, member_a, member_b, other = (uuid.uuid4() for _ in range(4))

    async def fake_roles(session: Any, query: str, *, limit: int) -> list[Any]:
        return [(cluster, "PeopleSoft Developer", "apsa")]

    async def fake_titles(session: Any, query: str, *, limit: int) -> dict[Any, Any]:
        return {
            member_a: _jd("Senior Developer, PeopleSoft", "apsa"),
            member_b: _jd("Senior Developer, PeopleSoft", "apsa"),
            other: _jd("PeopleSoft Systems Engineer", "apsa"),
        }

    async def fake_clusters(session: Any, ids: Any) -> dict[Any, Any]:
        # The two members belong to the role above; `other` is unclustered.
        return {member_a: cluster, member_b: cluster}

    async def fake_nearest(driver: Any, vector: Any, k: int) -> list[Any]:
        return []

    async def fake_load(session: Any, ids: Any) -> dict[Any, Any]:
        return {}

    monkeypatch.setattr(search_mod, "_role_title_matches", fake_roles)
    monkeypatch.setattr(search_mod, "_title_matches", fake_titles)
    monkeypatch.setattr(search_mod, "_clusters_for_sources", fake_clusters)
    monkeypatch.setattr(search_mod, "_nearest_source_ids", fake_nearest)
    monkeypatch.setattr(search_mod, "_load_latest_parsed", fake_load)

    hits = await search_mod.search_similar_jds(
        "peoplesoft",
        embed_client=_FakeEmbed([0.1] * 768),  # type: ignore[arg-type]
        neo4j_driver=object(),  # type: ignore[arg-type]
        session=object(),  # type: ignore[arg-type]
        limit=10,
    )

    assert [h.title for h in hits] == [
        "PeopleSoft Developer",  # the harmonized role
        "PeopleSoft Systems Engineer",  # unclustered — genuinely new information
    ]
    # Neither member of the already-listed role is repeated underneath it.
    assert member_a not in [h.source_document_id for h in hits]
    assert member_b not in [h.source_document_id for h in hits]


async def test_a_title_match_is_not_duplicated_by_the_semantic_pass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A document can be both an exact title match and a near neighbour. It is one
    candidate, listed once, as the stronger (title) match."""
    both = uuid.uuid4()

    async def fake_titles(session: Any, query: str, *, limit: int) -> dict[Any, Any]:
        return {both: _jd("AV Systems Analyst", "apsa")}

    async def fake_nearest(driver: Any, vector: Any, k: int) -> list[Any]:
        return [(both, 0.93)]

    async def fake_load(session: Any, ids: Any) -> dict[Any, Any]:
        return {both: _jd("AV Systems Analyst", "apsa")}

    async def _no_roles(session: Any, query: str, *, limit: int) -> list[Any]:
        return []

    monkeypatch.setattr(search_mod, "_role_title_matches", _no_roles)
    monkeypatch.setattr(search_mod, "_clusters_for_sources", _no_clusters_fn)
    monkeypatch.setattr(search_mod, "_title_matches", fake_titles)
    monkeypatch.setattr(search_mod, "_nearest_source_ids", fake_nearest)
    monkeypatch.setattr(search_mod, "_load_latest_parsed", fake_load)

    hits = await search_mod.search_similar_jds(
        "AV Systems Analyst",
        embed_client=_FakeEmbed([0.1] * 768),  # type: ignore[arg-type]
        neo4j_driver=object(),  # type: ignore[arg-type]
        session=object(),  # type: ignore[arg-type]
        limit=10,
    )

    assert [h.source_document_id for h in hits] == [both]
    assert hits[0].match == "title"


async def test_title_matches_stay_jdfn_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """The title pass is subject to the SAME JDFN scope as the semantic one — a CUPE
    hit must not sneak in through the new path (HR-143/194)."""
    cupe = uuid.uuid4()

    async def fake_titles(session: Any, query: str, *, limit: int) -> dict[Any, Any]:
        return {cupe: _jd("AV Systems Analyst", "cupe")}

    async def fake_nearest(driver: Any, vector: Any, k: int) -> list[Any]:
        return []

    async def fake_load(session: Any, ids: Any) -> dict[Any, Any]:
        return {}

    async def _no_roles(session: Any, query: str, *, limit: int) -> list[Any]:
        return []

    monkeypatch.setattr(search_mod, "_role_title_matches", _no_roles)
    monkeypatch.setattr(search_mod, "_clusters_for_sources", _no_clusters_fn)
    monkeypatch.setattr(search_mod, "_title_matches", fake_titles)
    monkeypatch.setattr(search_mod, "_nearest_source_ids", fake_nearest)
    monkeypatch.setattr(search_mod, "_load_latest_parsed", fake_load)

    hits = await search_mod.search_similar_jds(
        "AV Systems Analyst",
        embed_client=_FakeEmbed([0.1] * 768),  # type: ignore[arg-type]
        neo4j_driver=object(),  # type: ignore[arg-type]
        session=object(),  # type: ignore[arg-type]
        limit=10,
    )

    assert hits == []


async def test_search_respects_the_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    ids = [(uuid.uuid4(), 0.9 - i * 0.01) for i in range(5)]
    parsed = {sid: _jd(f"role-{i}", "apsa") for i, (sid, _) in enumerate(ids)}

    async def fake_nearest(driver: Any, vector: Any, k: int) -> list[Any]:
        return ids

    async def fake_load(session: Any, sids: Any) -> dict[Any, Any]:
        return parsed

    _no_title_matches(monkeypatch)
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

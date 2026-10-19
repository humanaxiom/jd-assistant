"""Integration — Track I1: the library's hybrid search against a real Postgres.

Title tiers (exact, prefix, contains) first, then the role-vector pass shared with the
Builder (:func:`src.jd_bank.composer.search.semantic_role_neighbours`). The vector
index is faked at its single seam (``_nearest_role_ids``) and the embed client is a
fake, so no
GPU or Neo4j is needed; the live behaviour is covered by ``make smoke``.

What only a real database can prove: JSONB-path ILIKE over the CURRENT canonical per
cluster, ``IN`` scoping, and the current-parse title search on ``parsed_jds``.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.jd_bank.composer import search as search_mod
from src.jd_bank.db.models import ParsedJDRow
from src.jd_bank.library import list_roles, list_source_jds
from src.jd_core.rules import get_rules
from tests.integration.test_library_service import (  # noqa: F401
    _jd,
    _seed_role,
    _seed_source,
    migrated_pg_url,
    session_maker,
)
from tests.unit.retuned_rules import retuned_embeddings


class _FakeEmbed:
    """Stands in for ``EmbedClient``: a fixed vector, or raises like a dead host."""

    def __init__(self, *, fail: Exception | None = None) -> None:
        self.fail = fail
        self.calls: list[list[str]] = []

    async def embed_batch(self, texts: Any) -> list[list[float]]:
        self.calls.append(list(texts))
        if self.fail is not None:
            raise self.fail
        return [[0.1] * 768]


def _neighbours(monkeypatch: pytest.MonkeyPatch, ranked: list[uuid.UUID]) -> list[int]:
    """Make the role-vector index return ``ranked`` (best first); records each ``k``."""
    ks: list[int] = []

    async def fake(driver: Any, vector: Any, k: int, *, live_stamp: str) -> list[Any]:
        ks.append(k)
        return [(cid, "ignored", None, 0.5) for cid in ranked]

    monkeypatch.setattr(search_mod, "_nearest_role_ids", fake)
    return ks


async def _seed_titles(session: AsyncSession, *titles: str) -> dict[str, uuid.UUID]:
    out: dict[str, uuid.UUID] = {}
    for title in titles:
        out[title], _ = await _seed_role(session, content=_jd(title), members=[])
    await session.commit()
    return out


def _clients(embed: _FakeEmbed | None = None) -> dict[str, Any]:
    return {"embed_client": embed or _FakeEmbed(), "neo4j_driver": object()}


@pytest.mark.asyncio
async def test_search_ranks_title_tiers_exact_then_prefix_then_contains(
    session_maker: async_sessionmaker[AsyncSession],  # noqa: F811
) -> None:
    async with session_maker() as session:
        await _seed_titles(
            session,
            # Alphabetical order (A, C, C) differs from tier order on purpose, so a
            # tier-blind sort cannot pass.
            "Accounts Clerk",  # contains
            "Clerk Typist",  # prefix
            "Clerk",  # exact
            "Library Assistant",
        )
        page = await list_roles(session, q="clerk")

    assert [i.title for i in page.items] == [
        "Clerk",
        "Clerk Typist",
        "Accounts Clerk",
    ]
    assert page.sort == "relevance"
    assert {i.matched_by for i in page.items} == {"title"}


@pytest.mark.asyncio
async def test_search_appends_role_meaning_hits_after_titles_without_duplicates(
    session_maker: async_sessionmaker[AsyncSession],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with session_maker() as session:
        ids = await _seed_titles(
            session, "Accounts Payable Clerk", "Payables Assistant", "Library Clerk"
        )
        # The vector pass returns the title hit again plus a pure-meaning hit.
        ks = _neighbours(
            monkeypatch, [ids["Accounts Payable Clerk"], ids["Payables Assistant"]]
        )
        page = await list_roles(session, q="accounts payable", **_clients())

    assert [(i.title, i.matched_by) for i in page.items] == [
        ("Accounts Payable Clerk", "title"),
        ("Payables Assistant", "meaning"),
    ]
    assert page.total == 2
    assert page.banner is None
    assert ks == [get_rules().embeddings.library_vector_k], "uses the registered depth"


@pytest.mark.asyncio
async def test_a_meaning_only_query_is_not_empty(
    session_maker: async_sessionmaker[AsyncSession],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The 17-of-22 empty pages: nothing in any title, found by meaning."""
    async with session_maker() as session:
        ids = await _seed_titles(session, "Accounts Payable Clerk", "Library Clerk")
        _neighbours(monkeypatch, [ids["Accounts Payable Clerk"]])
        page = await list_roles(
            session, q="someone who processes invoices", **_clients()
        )

    assert [i.title for i in page.items] == ["Accounts Payable Clerk"]
    assert page.items[0].matched_by == "meaning"


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [ConnectionError("refused"), TimeoutError("stall")])
async def test_dead_embed_host_still_returns_title_hits_with_a_banner(
    session_maker: async_sessionmaker[AsyncSession],  # noqa: F811
    failure: Exception,
) -> None:
    async with session_maker() as session:
        await _seed_titles(session, "Accounts Payable Clerk", "Library Clerk")
        page = await list_roles(
            session, q="clerk", **_clients(_FakeEmbed(fail=failure))
        )

    assert {i.title for i in page.items} == {"Accounts Payable Clerk", "Library Clerk"}
    assert page.banner, "the reader must be told meaning search is off"
    assert "title" in page.banner.lower()


@pytest.mark.asyncio
async def test_a_stalled_embed_host_is_abandoned_within_the_interactive_budget(
    session_maker: async_sessionmaker[AsyncSession],  # noqa: F811
) -> None:
    class _Stalls(_FakeEmbed):
        async def embed_batch(self, texts: Any) -> list[list[float]]:
            await asyncio.sleep(30)
            return [[0.0]]

    async with session_maker() as session:
        await _seed_titles(session, "Accounts Payable Clerk")
        page = await asyncio.wait_for(
            list_roles(
                session,
                q="clerk",
                rules=retuned_embeddings(get_rules(), interactive_timeout_seconds=0.05),
                **_clients(_Stalls()),
            ),
            timeout=5,
        )
    assert [i.title for i in page.items] == ["Accounts Payable Clerk"]
    assert page.banner


@pytest.mark.asyncio
async def test_search_without_clients_is_title_only_and_unbannered(
    session_maker: async_sessionmaker[AsyncSession],  # noqa: F811
) -> None:
    async with session_maker() as session:
        await _seed_titles(session, "Accounts Payable Clerk")
        page = await list_roles(session, q="clerk")
    assert [i.title for i in page.items] == ["Accounts Payable Clerk"]
    assert page.banner is None


@pytest.mark.asyncio
async def test_a_blank_query_never_embeds(
    session_maker: async_sessionmaker[AsyncSession],  # noqa: F811
) -> None:
    embed = _FakeEmbed()
    async with session_maker() as session:
        await _seed_titles(session, "Accounts Payable Clerk")
        page = await list_roles(session, q="   ", **_clients(embed))
    assert embed.calls == []
    assert page.sort == "title" and page.banner is None


@pytest.mark.asyncio
async def test_hybrid_results_page_and_honour_an_explicit_sort(
    session_maker: async_sessionmaker[AsyncSession],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with session_maker() as session:
        ids = await _seed_titles(
            session, "Zeta Clerk", "Alpha Clerk", "Mid Clerk", "Meaning Only"
        )
        _neighbours(monkeypatch, [ids["Meaning Only"]])
        page1 = await list_roles(session, q="clerk", limit=2, offset=0, **_clients())
        page2 = await list_roles(session, q="clerk", limit=2, offset=2, **_clients())
        by_title = await list_roles(session, q="clerk", sort="title", **_clients())

    seen = [i.title for i in page1.items] + [i.title for i in page2.items]
    assert len(seen) == 4 == len(set(seen)) and page1.total == page2.total == 4
    assert seen[-1] == "Meaning Only", "meaning hits come after every title hit"
    assert [i.title for i in by_title.items] == [
        "Alpha Clerk",
        "Meaning Only",
        "Mid Clerk",
        "Zeta Clerk",
    ]
    assert by_title.sort == "title"


@pytest.mark.asyncio
async def test_search_respects_a_cluster_scope_and_uses_only_current_titles(
    session_maker: async_sessionmaker[AsyncSession],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with session_maker() as session:
        in_scope, _ = await _seed_role(session, content=_jd("Scoped Clerk"), members=[])
        await _seed_role(session, content=_jd("Other Clerk"), members=[])
        # An old title must not match once a newer version renamed the role.
        renamed, _ = await _seed_role(session, content=_jd("Old Name"), members=[])
        await _seed_role(
            session,
            content=_jd("Fresh Name"),
            members=[],
            version=2,
            cluster_id=renamed,
        )
        await session.commit()
        _neighbours(monkeypatch, [])
        scoped = await list_roles(session, q="clerk", cluster_ids=[in_scope])
        old = await list_roles(session, q="old name")
        fresh = await list_roles(session, q="fresh name")

    assert [i.title for i in scoped.items] == ["Scoped Clerk"]
    assert old.total == 0 and fresh.total == 1


@pytest.mark.asyncio
async def test_archive_search_finds_the_current_parsed_title_not_only_the_filename(
    session_maker: async_sessionmaker[AsyncSession],  # noqa: F811
) -> None:
    from src.jd_core.parser import PARSER_VERSION

    async with session_maker() as session:
        doc = await _seed_source(
            session, filename="scan-0042.docx", jd=_jd("Accounts Payable Clerk")
        )
        # A superseded parse carrying a title the current one no longer has.
        session.add(
            ParsedJDRow(
                source_document_id=doc,
                parsed=_jd("Ancient Title").model_dump(mode="json"),
                parser_version=f"{PARSER_VERSION}-older",
                parse_confidence=0.5,
                created_at=datetime(2020, 1, 1, tzinfo=UTC),
            )
        )
        await session.commit()

        by_title = await list_source_jds(session, q="payable")
        by_old = await list_source_jds(session, q="ancient")
        by_file = await list_source_jds(session, q="scan-0042")

    assert [i.source_document_id for i in by_title.items] == [doc]
    assert by_title.total == 1
    assert by_old.total == 0, "a superseded parse's title must not match"
    assert by_file.total == 1, "filename search still works"


@pytest.mark.asyncio
async def test_like_wildcards_in_a_query_are_literal(
    session_maker: async_sessionmaker[AsyncSession],  # noqa: F811
) -> None:
    """``%`` and ``_`` typed by a reader are characters, not LIKE wildcards — on the
    roles search and on the archive's filename/title search alike."""
    async with session_maker() as session:
        await _seed_titles(session, "Clerk_Typist", "ClerkXTypist", "Library Clerk")
        await _seed_source(session, filename="a_b.docx", jd=_jd("Plain"))
        await _seed_source(session, filename="axb.docx", jd=_jd("Other"))
        underscore = await list_roles(session, q="clerk_typist")
        percent = await list_roles(session, q="%")
        archive = await list_source_jds(session, q="a_b")

    assert [i.title for i in underscore.items] == ["Clerk_Typist"]
    assert percent.total == 0
    assert archive.total == 1


@pytest.mark.asyncio
async def test_meaning_hits_outside_the_scope_or_the_bank_are_not_counted(
    session_maker: async_sessionmaker[AsyncSession],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A vector node for a role outside the collection, or for a cluster the Bank no
    longer has (a stale node), must drop out of the rows AND the total — otherwise
    "showing 1-1 of 3" promises pages that do not exist."""
    async with session_maker() as session:
        ids = await _seed_titles(session, "Scoped Clerk", "Outside Role")
        _neighbours(monkeypatch, [ids["Outside Role"], uuid.uuid4()])
        page = await list_roles(
            session, q="clerk", cluster_ids=[ids["Scoped Clerk"]], **_clients()
        )

    assert [i.title for i in page.items] == ["Scoped Clerk"]
    assert page.total == 1

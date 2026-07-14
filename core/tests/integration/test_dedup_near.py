"""Integration — the Tier-2 pass against a real Postgres (+ Neo4j for the cosine
confirm), through the real migration.

A **content-keyed fake** ``TextSource`` stands in for the archive (HANDOFF: "fakes in
this suite must be content-keyed" — 3.2b's index-keyed fake made a whole class of bug
unwritable), so no archive bind and no parser are needed. What only a real database can
prove, and why each test exists:

1. **The reconcile is real, not merely additive.** Raising ``jaccard_min`` must
   DELETE edges that no longer qualify; changing ``shingle_size`` must UPDATE a
   surviving edge's score/method. A naive ``ON CONFLICT DO NOTHING`` (Tier-1's
   correct shape, wrong here) would go green on both and leave a stale row behind.
2. **``--limit`` must not prune what it never read.** Only a real reconcile query,
   scoped to the documents actually fetched, can prove this.
3. **``run_tier2`` never commits.** The caller owns the transaction.
4. **EXACT edges are untouched.** Tier-1 and Tier-2 share one table
   (``dedup_edges``); Tier-2 must only ever touch ``tier=NEAR_DUPLICATE`` rows.
5. **The cosine confirm reads Neo4j directly and never embeds.** A vector written
   straight into testcontainers Neo4j (no Ollama, no embed client) is enough to prove
   the veto and the "unavailable -> accepted on Jaccard alone" fallback.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterator

import pytest
from alembic import command
from alembic.config import Config
from neo4j import AsyncDriver, AsyncGraphDatabase
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from testcontainers.neo4j import Neo4jContainer
from testcontainers.postgres import PostgresContainer

from src.jd_bank.db.models import (
    DedupEdge,
    DedupTier,
    DocumentFormat,
    ParsedJDRow,
    SourceDocument,
)
from src.jd_bank.dedup.models import DocumentRef
from src.jd_bank.dedup.near.runner import run_tier2
from src.jd_bank.dedup.near.text import SerializedTextSource, TextResult
from src.jd_core.models.parsed_jd import SFUDuty, SFUJobDescription
from src.jd_core.parser import PARSER_VERSION
from src.jd_core.rules import Rules, get_rules
from tests.integration.test_dedup_tier1 import ALEMBIC_INI
from tests.unit.retuned_rules import retuned_dedup

# --- a content-keyed fake TextSource, and the fixture corpus it serves ------------

#: 10 shared tokens both "twin" documents open with, plus 5 tokens unique to each —
#: MEASURED (not hand-derived): k=3 shingles give J(a,b) == 8/18 exactly (13 grams
#: each, 8 shared, 18 in the union); k=4 give J(a,b) == 7/17. Single-word tokens only
#: (no hyphens/punctuation) — `tokenize`'s `[a-z0-9]+` would otherwise split
#: "unique-a1" into TWO tokens ("unique", "a1"), silently changing the grams and the
#: measured Jaccard values below out from under the tests.
_SHARED = "alpha beta gamma delta epsilon zeta eta theta iota kappa"
_TEXT_A = _SHARED + " aaaa bbbb cccc dddd eeee"
_TEXT_B = _SHARED + " ffff gggg hhhh iiii jjjj"
#: Shares NOTHING with A/B — an unrelated document.
_TEXT_C = "zulu yankee xray whiskey victor uniform tango sierra romeo quebec"


class _FakeTextSource:
    """Content-keyed: looked up by ``sha256``, never by id or arrival order."""

    def __init__(self, text_by_sha256: dict[str, str]) -> None:
        self._text_by_sha256 = text_by_sha256

    async def text_for(self, ref: DocumentRef) -> TextResult:
        text_value = self._text_by_sha256.get(ref.sha256)
        if text_value is None:
            return TextResult(text=None, reason="no fixture text for this sha256")
        return TextResult(text=text_value)


def _small_dedup_rules(**overrides: object) -> Rules:
    base: dict[str, object] = dict(
        redact_boilerplate=False,
        min_shingles=1,
        num_perm=32,
        # bands=32/rows=1: with rows=1, a SINGLE matching MinHash value in ANY band
        # is enough to bucket a pair together — MEASURED to reliably surface the
        # fixture's J~=0.4 pairs as LSH candidates (a tighter banding, e.g. the
        # shipped 32/4, does NOT: LSH is inherently probabilistic below the S-curve
        # midpoint, and this fixture corpus's exact minhash draw does not clear it
        # at that banding). This is a TEST-FIXTURE banding choice, not a claim about
        # the shipped default.
        bands=32,
        rows=1,
        shingle_size=3,
        jaccard_min=0.4,
        edge_scope="content",
    )
    base.update(overrides)
    return retuned_dedup(get_rules(), **base)


@pytest.fixture(scope="module")
def migrated_pg_url() -> Iterator[str]:
    with PostgresContainer("postgres:16-alpine") as pg:
        url = pg.get_connection_url().replace("psycopg2", "asyncpg")
        cfg = Config(str(ALEMBIC_INI))
        cfg.set_main_option("sqlalchemy.url", url)
        command.upgrade(cfg, "head")
        yield url


@pytest.fixture
async def session_maker(
    migrated_pg_url: str,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(migrated_pg_url)
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM source_documents"))
    maker = async_sessionmaker(engine, expire_on_commit=False)
    yield maker
    await engine.dispose()


def _sha(seed: str) -> str:
    return uuid.uuid5(uuid.NAMESPACE_OID, seed).hex * 2  # 64 hex chars


async def _add(session: AsyncSession, storage_ref: str, sha256: str) -> SourceDocument:
    doc = SourceDocument(
        storage_ref=storage_ref,
        filename=storage_ref.rsplit("/", 1)[-1],
        sha256=sha256,
        fmt=DocumentFormat.DOCX,
        byte_size=1024,
    )
    session.add(doc)
    await session.flush()
    return doc


async def _near_edges(session: AsyncSession) -> list[DedupEdge]:
    result = await session.scalars(
        select(DedupEdge)
        .where(DedupEdge.tier == DedupTier.NEAR_DUPLICATE)
        .order_by(DedupEdge.source_a_id, DedupEdge.source_b_id)
    )
    return list(result.all())


async def _seed_a_b(
    session_maker: async_sessionmaker[AsyncSession],
) -> tuple[SourceDocument, SourceDocument]:
    async with session_maker() as session:
        doc_a = await _add(session, "archive/twin_a.docx", _sha("twin-a"))
        doc_b = await _add(session, "archive/twin_b.docx", _sha("twin-b"))
        await session.commit()
        return doc_a, doc_b


_TEXT_SOURCE = _FakeTextSource(
    {_sha("twin-a"): _TEXT_A, _sha("twin-b"): _TEXT_B, _sha("outsider"): _TEXT_C}
)


# ── edges: written, oriented, exact-Jaccard-scored ────────────────────────────────


@pytest.mark.asyncio
async def test_edges_are_written_oriented_and_exact_jaccard_scored(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    doc_a, doc_b = await _seed_a_b(session_maker)
    rules = _small_dedup_rules()

    async with session_maker() as session:
        result = await run_tier2(
            session, rules=rules, text_source=_TEXT_SOURCE, limit=None
        )
        await session.commit()

        assert result.edges_written == 1
        assert result.qualifying_pairs == 1

        edges = await _near_edges(session)
        assert len(edges) == 1
        edge = edges[0]
        # oriented: "archive/twin_a.docx" < "archive/twin_b.docx"
        assert edge.source_a_id == doc_a.id
        assert edge.source_b_id == doc_b.id
        # 8 shared 3-grams / 18 total (8 shared + 5 + 5 unique) — see module header.
        assert edge.score == pytest.approx(8 / 18)
        assert edge.method.startswith("minhash+jaccard@")
        assert edge.method == f"minhash+jaccard@{rules.dedup.digest[:12]}"


# ── idempotency ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_second_pass_over_unchanged_corpus_writes_nothing(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    await _seed_a_b(session_maker)
    rules = _small_dedup_rules()

    async with session_maker() as session:
        first = await run_tier2(
            session, rules=rules, text_source=_TEXT_SOURCE, limit=None
        )
        await session.commit()
        before = [(e.id, e.score, e.method) for e in await _near_edges(session)]

        second = await run_tier2(
            session, rules=rules, text_source=_TEXT_SOURCE, limit=None
        )
        await session.commit()
        after = [(e.id, e.score, e.method) for e in await _near_edges(session)]

    assert first.edges_written == 1
    assert second.edges_written == 0
    assert second.edges_updated == 0
    assert second.edges_pruned == 0
    assert second.edges_unchanged == 1
    assert before == after  # same row, same id — not even rewritten


# ── THE reconcile: raising jaccard_min DELETES a non-qualifying edge ──────────────


@pytest.mark.asyncio
async def test_raising_jaccard_min_deletes_the_edge_that_no_longer_qualifies(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    """A naive `ON CONFLICT DO NOTHING` pass would go green here and leave the edge
    behind — a database full of an edge a config that no longer exists produced."""
    await _seed_a_b(session_maker)
    loose = _small_dedup_rules(jaccard_min=0.4)  # 8/18 ≈ 0.444 qualifies
    strict = _small_dedup_rules(jaccard_min=0.5)  # 8/18 ≈ 0.444 no longer qualifies

    async with session_maker() as session:
        first = await run_tier2(
            session, rules=loose, text_source=_TEXT_SOURCE, limit=None
        )
        await session.commit()
        assert first.edges_written == 1

        second = await run_tier2(
            session, rules=strict, text_source=_TEXT_SOURCE, limit=None
        )
        await session.commit()

        assert second.edges_pruned == 1
        assert second.edges_written == 0
        edges = await _near_edges(session)
        assert edges == []


# ── THE reconcile: changing shingle_size UPDATES a surviving edge, not stale ──────


@pytest.mark.asyncio
async def test_changing_shingle_size_updates_the_surviving_edges_score_and_method(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    """A naive `ON CONFLICT DO NOTHING` pass would leave the OLD score/method in
    place — a provenance falsehood the row itself can no longer even hint at."""
    await _seed_a_b(session_maker)
    k3 = _small_dedup_rules(shingle_size=3, jaccard_min=0.3)  # score 8/18
    k4 = _small_dedup_rules(shingle_size=4, jaccard_min=0.3)  # score 7/17 — still ok

    async with session_maker() as session:
        await run_tier2(session, rules=k3, text_source=_TEXT_SOURCE, limit=None)
        await session.commit()
        before = (await _near_edges(session))[0]
        # Snapshot as PLAIN VALUES, not the ORM object's live attributes: the
        # reconcile calls `session.expire_all()` on an UPDATE/DELETE (so a caller
        # holding this SAME object post-reconcile sees fresh data, not a stale
        # in-memory score) — which means `before` itself will read the NEW score
        # once refreshed, and comparing `before.score` after the fact would compare
        # the row against itself.
        before_id, before_score, before_method = before.id, before.score, before.method
        assert before_score == pytest.approx(8 / 18)

        result = await run_tier2(
            session, rules=k4, text_source=_TEXT_SOURCE, limit=None
        )
        await session.commit()

        assert result.edges_written == 0
        assert result.edges_updated == 1
        assert result.edges_pruned == 0

        after = (await _near_edges(session))[0]
        assert after.id == before_id  # same row — UPDATEd, not deleted + reinserted
        assert after.score == pytest.approx(7 / 17)
        assert after.score != before_score
        assert after.method != before_method
        assert after.method == f"minhash+jaccard@{k4.dedup.digest[:12]}"


# ── --limit must not prune what it never read ─────────────────────────────────────


@pytest.mark.asyncio
async def test_limit_does_not_prune_an_edge_it_never_read(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    doc_a, doc_b = await _seed_a_b(session_maker)
    rules = _small_dedup_rules()

    async with session_maker() as session:
        # An outsider whose storage_ref sorts BEFORE both twins, so a `limit=1` pass
        # reads ONLY the outsider — never touching doc_a or doc_b at all.
        await _add(session, "archive/aaa_outsider.docx", _sha("outsider"))
        await session.commit()

        full = await run_tier2(
            session, rules=rules, text_source=_TEXT_SOURCE, limit=None
        )
        await session.commit()
        assert full.edges_written == 1
        original_edge = (await _near_edges(session))[0]

        limited = await run_tier2(
            session, rules=rules, text_source=_TEXT_SOURCE, limit=1
        )
        await session.commit()

        assert limited.documents_seen == 1  # only the outsider
        assert limited.edges_pruned == 0
        edges = await _near_edges(session)
        assert len(edges) == 1
        assert edges[0].id == original_edge.id
        assert {edges[0].source_a_id, edges[0].source_b_id} == {doc_a.id, doc_b.id}


# ── does not commit ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_run_tier2_does_not_commit(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    await _seed_a_b(session_maker)
    rules = _small_dedup_rules()

    async with session_maker() as session:
        result = await run_tier2(
            session, rules=rules, text_source=_TEXT_SOURCE, limit=None
        )
        assert result.edges_written == 1
        await session.rollback()

    async with session_maker() as session:
        assert await _near_edges(session) == []


# ── EXACT edges are untouched ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_exact_edges_are_untouched_by_the_tier2_pass(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    doc_a, doc_b = await _seed_a_b(session_maker)
    rules = _small_dedup_rules()

    async with session_maker() as session:
        exact_edge = DedupEdge(
            source_a_id=doc_a.id,
            source_b_id=doc_b.id,
            tier=DedupTier.EXACT,
            score=1.0,
            method="sha256",
        )
        session.add(exact_edge)
        await session.commit()

        await run_tier2(session, rules=rules, text_source=_TEXT_SOURCE, limit=None)
        await session.commit()

        exact_rows = list(
            (
                await session.scalars(
                    select(DedupEdge).where(DedupEdge.tier == DedupTier.EXACT)
                )
            ).all()
        )
        assert len(exact_rows) == 1
        assert exact_rows[0].id == exact_edge.id
        assert exact_rows[0].score == 1.0
        assert exact_rows[0].method == "sha256"
        # ...and a NEAR edge exists ALONGSIDE it — one table, two tiers, both real.
        near_rows = await _near_edges(session)
        assert len(near_rows) == 1


# ── cosine confirm: reads Neo4j directly, never embeds ─────────────────────────────


@pytest.fixture(scope="module")
def neo4j_container() -> Iterator[Neo4jContainer]:
    with Neo4jContainer("neo4j:5-community") as neo:
        yield neo


@pytest.fixture
async def neo4j_driver(neo4j_container: Neo4jContainer) -> AsyncIterator[AsyncDriver]:
    driver = AsyncGraphDatabase.driver(
        neo4j_container.get_connection_url(), auth=("neo4j", neo4j_container.password)
    )
    async with driver.session() as session:
        await session.run("MATCH (n) DETACH DELETE n")
    yield driver
    await driver.close()


async def _write_vector(
    driver: AsyncDriver, doc_id: uuid.UUID, embedding: list[float]
) -> None:
    async with driver.session() as session:
        await session.run(
            "MERGE (d:JDDocument {id: $id}) SET d.embedding = $embedding",
            id=str(doc_id),
            embedding=embedding,
        )


@pytest.mark.asyncio
async def test_cosine_confirm_vetoes_a_low_cosine_jaccard_qualifying_pair(
    session_maker: async_sessionmaker[AsyncSession],
    neo4j_driver: AsyncDriver,
) -> None:
    doc_a, doc_b = await _seed_a_b(session_maker)
    rules = _small_dedup_rules(cosine_confirm_min=0.9)

    await _write_vector(neo4j_driver, doc_a.id, [1.0, 0.0, 0.0])
    await _write_vector(neo4j_driver, doc_b.id, [0.0, 1.0, 0.0])  # orthogonal: cos=0

    async with session_maker() as session:
        result = await run_tier2(
            session,
            rules=rules,
            text_source=_TEXT_SOURCE,
            neo4j_driver=neo4j_driver,
            limit=None,
        )
        await session.commit()

        # `qualifying_pairs` means "cleared Jaccard AND survived the confirm" — the
        # SAME predicate report.py's position split counts, so one artifact cannot
        # state two different numbers for "what qualified". The pair cleared Jaccard
        # and was then vetoed, so it lands in `cosine_vetoed`, not here.
        assert result.candidate_pairs == 1
        assert result.qualifying_pairs == 0
        assert result.cosine_vetoed == 1
        assert result.edges_written == 0
        assert await _near_edges(session) == []


@pytest.mark.asyncio
async def test_cosine_confirm_accepts_on_jaccard_alone_when_a_vector_is_missing(
    session_maker: async_sessionmaker[AsyncSession],
    neo4j_driver: AsyncDriver,
) -> None:
    doc_a, _doc_b = await _seed_a_b(session_maker)
    rules = _small_dedup_rules(cosine_confirm_min=0.9)

    # Only ONE side has a vector — the WJQ-style "no vector available" case.
    await _write_vector(neo4j_driver, doc_a.id, [1.0, 0.0, 0.0])

    async with session_maker() as session:
        result = await run_tier2(
            session,
            rules=rules,
            text_source=_TEXT_SOURCE,
            neo4j_driver=neo4j_driver,
            limit=None,
        )
        await session.commit()

        assert result.cosine_vetoed == 0
        assert result.edges_written == 1
        edge = (await _near_edges(session))[0]
        # NO "+cosine" suffix — accepted on Jaccard alone, and the row says so.
        assert not edge.method.endswith("+cosine")
        assert edge.method == f"minhash+jaccard@{rules.dedup.digest[:12]}"


@pytest.mark.asyncio
async def test_cosine_confirm_never_constructs_an_embed_client(
    session_maker: async_sessionmaker[AsyncSession],
    neo4j_driver: AsyncDriver,
) -> None:
    """The whole point: a vector written DIRECTLY into Neo4j (no Ollama call in this
    test at all) is sufficient. If ``run_tier2`` ever tried to construct an embed
    client, this test would need one and would fail/hang without it."""
    doc_a, doc_b = await _seed_a_b(session_maker)
    rules = _small_dedup_rules(cosine_confirm_min=0.5)

    await _write_vector(neo4j_driver, doc_a.id, [1.0, 1.0, 0.0])
    await _write_vector(neo4j_driver, doc_b.id, [1.0, 1.0, 0.01])  # cos ~ 1.0

    async with session_maker() as session:
        result = await run_tier2(
            session,
            rules=rules,
            text_source=_TEXT_SOURCE,
            neo4j_driver=neo4j_driver,
            limit=None,
        )
        await session.commit()

        assert result.edges_written == 1
        edge = (await _near_edges(session))[0]
        assert edge.method.endswith("+cosine")


# ── MUST-FIX 1: an unreadable document must NEVER prune its edges ─────────────────


class _PartiallyBlindTextSource:
    """Content-keyed, but returns ``TextResult(text=None)`` for one nominated sha256 —
    the shape of a transient ``OSError`` / extractor hiccup on a bind-mounted volume."""

    def __init__(self, text_by_sha256: dict[str, str], *, blind_to: str) -> None:
        self._text_by_sha256 = text_by_sha256
        self._blind_to = blind_to

    async def text_for(self, ref: DocumentRef) -> TextResult:
        if ref.sha256 == self._blind_to:
            return TextResult(text=None, reason="OSError: simulated transient failure")
        return TextResult(text=self._text_by_sha256[ref.sha256])


@pytest.mark.asyncio
async def test_an_unreadable_document_never_prunes_its_edges(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    """**THE data-loss regression the reviewer probed.** The first cut built the prune
    scope from every row FETCHED, not from the documents actually READ — so a document
    whose text could not be obtained planned no edge, and ``present - plan`` DELETED
    its perfectly good existing edges. Measured on the first cut: ``unreadable=1,
    pruned=1, edges_left=0``.

    An unreadable document is an UNKNOWN, not a "no". On the shipped default
    (``ArchiveTextSource`` re-reading 14,452 files through antiword off a bind mount),
    one transient ``OSError`` would silently destroy real near-dup findings on the next
    run. Same discipline as 3.2b's embedding runner, whose keep-list is derived BEFORE
    the risky step precisely so a transient failure can never trigger a delete.
    """
    doc_a, doc_b = await _seed_a_b(session_maker)
    rules = _small_dedup_rules()

    async with session_maker() as session:
        first = await run_tier2(
            session, rules=rules, text_source=_TEXT_SOURCE, limit=None
        )
        await session.commit()
        assert first.edges_written == 1
        original = (await _near_edges(session))[0]

        # ...now ONE of the two documents becomes unreadable this run.
        blind = _PartiallyBlindTextSource(
            {_sha("twin-a"): _TEXT_A, _sha("twin-b"): _TEXT_B},
            blind_to=_sha("twin-b"),
        )
        second = await run_tier2(session, rules=rules, text_source=blind, limit=None)
        await session.commit()

        assert second.documents_unreadable == 1
        assert second.documents_signed == 1
        # THE ASSERTION. Pre-fix this was `pruned == 1` and the edge was GONE.
        assert second.edges_pruned == 0
        edges = await _near_edges(session)
        assert len(edges) == 1
        assert edges[0].id == original.id
        assert {edges[0].source_a_id, edges[0].source_b_id} == {doc_a.id, doc_b.id}


@pytest.mark.asyncio
async def test_a_document_below_min_shingles_does_prune_its_edges(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    """The other half of the prune scope, and the reason it is not simply "prune only
    what was signed". A document READ but shingled below ``min_shingles`` is a
    DETERMINISTIC function of the config and the text — so raising ``min_shingles``
    MUST delete its edges. Only ``unreadable`` (an unknown) is protected.

    Goes red if the fix for must-fix 1 over-corrects into "prune scope == signed only".
    """
    await _seed_a_b(session_maker)
    loose = _small_dedup_rules(min_shingles=1)
    strict = _small_dedup_rules(min_shingles=500)  # nothing can clear this

    async with session_maker() as session:
        first = await run_tier2(
            session, rules=loose, text_source=_TEXT_SOURCE, limit=None
        )
        await session.commit()
        assert first.edges_written == 1

        second = await run_tier2(
            session, rules=strict, text_source=_TEXT_SOURCE, limit=None
        )
        await session.commit()

        assert second.documents_below_min_shingles == 2
        assert second.documents_unreadable == 0
        assert second.edges_pruned == 1  # the config says this edge no longer exists
        assert await _near_edges(session) == []


# ── MUST-FIX 3: SerializedTextSource against a real parsed_jds row ────────────────


async def _seed_parsed(
    session_maker: async_sessionmaker[AsyncSession],
    *,
    storage_ref: str,
    sha256: str,
    jd: SFUJobDescription | None,
) -> SourceDocument:
    async with session_maker() as session:
        doc = await _add(session, storage_ref, sha256)
        if jd is not None:
            session.add(
                ParsedJDRow(
                    source_document_id=doc.id,
                    parsed=jd.model_dump(mode="json"),
                    parser_version=PARSER_VERSION,
                    parse_confidence=1.0,
                )
            )
        await session.commit()
        return doc


@pytest.mark.asyncio
async def test_serialized_text_source_returns_the_serialized_parsed_jd(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    rules = get_rules()
    jd = SFUJobDescription(
        title="Coordinator",
        position_summary="Coordinates the departmental schedule.",
        duties=[SFUDuty(action_verb="Manages", statement="the meeting calendar.")],
        qualifications=[],
    )
    doc = await _seed_parsed(
        session_maker, storage_ref="archive/parsed.docx", sha256=_sha("parsed"), jd=jd
    )

    async with session_maker() as session:
        source = SerializedTextSource(session, embeddings_rules=rules.embeddings)
        result = await source.text_for(
            DocumentRef(
                id=doc.id,
                sha256=_sha("parsed"),
                storage_ref="archive/parsed.docx",
                filename="parsed.docx",
            )
        )

    assert result.reason is None
    assert result.text is not None
    assert "Coordinates the departmental schedule." in result.text
    assert "Manages the meeting calendar." in result.text
    # `include_title_in_document: false` (HR-128) — the title must NOT be in there.
    assert "Coordinator" not in result.text


@pytest.mark.asyncio
async def test_serialized_text_source_reports_a_missing_parsed_row(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    rules = get_rules()
    doc = await _seed_parsed(
        session_maker,
        storage_ref="archive/unparsed.docx",
        sha256=_sha("unparsed"),
        jd=None,
    )

    async with session_maker() as session:
        source = SerializedTextSource(session, embeddings_rules=rules.embeddings)
        result = await source.text_for(
            DocumentRef(
                id=doc.id,
                sha256=_sha("unparsed"),
                storage_ref="archive/unparsed.docx",
                filename="unparsed.docx",
            )
        )

    assert result.text is None
    assert result.reason == "no parsed_jds row at PARSER_VERSION"


@pytest.mark.asyncio
async def test_serialized_text_source_reports_the_wjq_empty_serialization_gap(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    """34.5% of parsed JDs serialize to EMPTY (the WJQ-template gap). That is exactly
    why ``text_source: raw_clean`` is the shipped default (HR-131) — and it must be
    COUNTED as unreadable here, never shingled as an empty string."""
    rules = get_rules()
    empty_jd = SFUJobDescription(
        title="Ghost", position_summary=None, duties=[], qualifications=[]
    )
    doc = await _seed_parsed(
        session_maker, storage_ref="archive/wjq.doc", sha256=_sha("wjq"), jd=empty_jd
    )

    async with session_maker() as session:
        source = SerializedTextSource(session, embeddings_rules=rules.embeddings)
        result = await source.text_for(
            DocumentRef(
                id=doc.id,
                sha256=_sha("wjq"),
                storage_ref="archive/wjq.doc",
                filename="wjq.doc",
            )
        )

    assert result.text is None
    assert result.reason is not None
    assert "WJQ" in result.reason

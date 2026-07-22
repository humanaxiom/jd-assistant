"""Integration tests — Phase 3.2b, Postgres ``parsed_jds`` -> real Neo4j.

Real Postgres (Alembic-migrated) + real Neo4j (``002_jd_vectors.cypher`` applied) via
testcontainers; only the embedding CALL is mocked (ADR-003: integration tests mock the
embedding call, never a live endpoint). Containers are started ONCE per module
(container startup dominates the runtime of a suite this size), but every test gets a
CLEAN graph and a clean set of Postgres rows: ``run_embeddings`` genuinely reads every
``parsed_jds`` row and every existing Neo4j node with no per-test scoping key (unlike
``test_archive_ingest_driver.py``'s ``storage_ref`` prefix trick), so leaving one
test's rows/nodes in place would let a later test's stamp change silently re-embed
them.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from neo4j import AsyncDriver, AsyncGraphDatabase
from sqlalchemy import text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from testcontainers.neo4j import Neo4jContainer
from testcontainers.postgres import PostgresContainer

from src.jd_bank.db.models import DocumentFormat, ParsedJDRow, SourceDocument
from src.jd_bank.embeddings.client import EmbeddingBadRequestError
from src.jd_bank.embeddings.runner import run_embeddings
from src.jd_core.bank.embed_text import (
    retruncate_within,
    serialize_document,
    serialize_section,
)
from src.jd_core.models.parsed_jd import (
    SFUDuty,
    SFUJobDescription,
    SFUQualification,
)
from src.jd_core.parser import PARSER_VERSION
from src.jd_core.rules import Rules, get_rules

CORE_DIR = Path(__file__).resolve().parents[2]
ALEMBIC_INI = CORE_DIR / "alembic.ini"
VECTOR_CYPHER = CORE_DIR / "db" / "migrations" / "002_jd_vectors.cypher"


def _cypher_statements(path: Path) -> list[str]:
    lines = [
        line
        for line in path.read_text(encoding="utf-8").splitlines()
        if not line.strip().startswith("//")
    ]
    body = "\n".join(lines)
    return [stmt.strip() for stmt in body.split(";") if stmt.strip()]


def _vector_for(text: str, dimensions: int) -> list[float]:
    """The vector this fake returns for ``text`` — a pure, deterministic function of
    the TEXT, and of nothing else (not of its position in the batch).

    **This is the oracle the binding tests use**, and it is why they can exist at
    all. The first cut returned ``[0.01 * (i + 1)] * dim`` — keyed on the batch
    INDEX — under which "did this node get the vector of its own text?" was
    literally unassertable: the vector carried no trace of the text it came from.
    Content-keying it turns the fake into a checkable oracle, so
    :func:`test_each_node_gets_the_vector_of_its_own_text` can recompute what each
    node's embedding *must* be and compare.

    Every dimension is varied from the hash (a counter-mode expansion of
    SHA-256), not one value repeated: an earlier cut used a single float from
    ``seed % 1000``, which gave two different texts a 1-in-1000 chance of the
    identical vector. Deterministic, so it could never *flake* — but a collision
    would have surfaced as a mysterious, permanently-failing assertion that looked
    like a real bug. The expansion drops that to nil.
    """
    values: list[float] = []
    block = hashlib.sha256(text.encode("utf-8")).digest()
    counter = 0
    while len(values) < dimensions:
        block = hashlib.sha256(block + counter.to_bytes(4, "big")).digest()
        for start in range(0, len(block), 4):
            if len(values) == dimensions:
                break
            word = int.from_bytes(block[start : start + 4], "big")
            values.append(round(word / 2**32, 6))
        counter += 1
    return values


class _FakeEmbedClient:
    """Stands in for :class:`~src.jd_bank.embeddings.client.EmbedClient` — a
    deterministic, dimension-correct, CONTENT-keyed fake. Records every batch it was
    asked to embed, so a test can assert it was called zero times.

    ``bad_request_texts`` makes the fake 400 exactly like the real server does: on
    the whole BATCH, if any text in it is over-long. That is what the runner's
    one-at-a-time isolation path exists to survive.
    """

    def __init__(
        self, dimensions: int, *, bad_request_texts: frozenset[str] = frozenset()
    ) -> None:
        self._dimensions = dimensions
        self._bad = bad_request_texts
        self.batches: list[list[str]] = []

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        self.batches.append(list(texts))
        offending = [t for t in texts if t in self._bad]
        if offending:
            # The real server 400s the BATCH, not the text — that is the whole point.
            raise EmbeddingBadRequestError(
                "the input length exceeds the context length"
            )
        return [_vector_for(text, self._dimensions) for text in texts]

    async def close(self) -> None:  # pragma: no cover - nothing to release
        pass

    @property
    def call_count(self) -> int:
        return len(self.batches)


def _jd(**overrides: Any) -> SFUJobDescription:
    base: dict[str, Any] = {
        "title": "Analyst, Integration Test",
        "position_summary": "Coordinates the integration test fixture's small team.",
        "duties": [
            SFUDuty(action_verb="Verifies", statement="that embeddings land correctly.")
        ],
        "qualifications": [],
    }
    base.update(overrides)
    return SFUJobDescription(**base)


@pytest.fixture(scope="module")
def pg_url() -> Iterator[str]:
    with PostgresContainer("postgres:16-alpine") as pg:
        url = pg.get_connection_url().replace("psycopg2", "asyncpg")
        cfg = Config(str(ALEMBIC_INI))
        cfg.set_main_option("sqlalchemy.url", url)
        command.upgrade(cfg, "head")
        yield url


@pytest.fixture
async def pg_sessionmaker(
    pg_url: str,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(pg_url)
    # A clean slate per test: `source_documents` cascades (ON DELETE CASCADE) to
    # `parsed_jds`, `validation_reports` and `dedup_edges`, so one DELETE is enough.
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM source_documents"))
    maker = async_sessionmaker(engine, expire_on_commit=False)
    yield maker
    await engine.dispose()


@pytest.fixture(scope="module")
def neo4j_container() -> Iterator[Neo4jContainer]:
    with Neo4jContainer("neo4j:5-community") as neo:
        yield neo


@pytest.fixture
async def neo4j_driver(neo4j_container: Neo4jContainer) -> AsyncIterator[AsyncDriver]:
    drv = AsyncGraphDatabase.driver(
        neo4j_container.get_connection_url(), auth=("neo4j", neo4j_container.password)
    )
    async with drv.session() as session:
        # A clean graph per test — see the module docstring for why.
        await session.run("MATCH (n) DETACH DELETE n")
        for stmt in _cypher_statements(VECTOR_CYPHER):
            await session.run(stmt)
    yield drv
    await drv.close()


async def _seed_parsed_jd(
    maker: async_sessionmaker[AsyncSession], jd: SFUJobDescription
) -> tuple[uuid.UUID, uuid.UUID]:
    """Insert one ``source_documents`` + ``parsed_jds`` row directly — this suite
    tests the embeddings layer, not ingestion, so it seeds Postgres the way
    ``parse_and_store`` would have left it rather than re-running extraction."""
    async with maker() as session:
        doc = SourceDocument(
            storage_ref=f"test/{uuid.uuid4()}.txt",
            filename="fixture.txt",
            sha256=uuid.uuid4().hex + uuid.uuid4().hex,
            fmt=DocumentFormat.TXT,
            byte_size=256,
            ingest_metadata={"status": "ingested"},
        )
        session.add(doc)
        await session.flush()
        row = ParsedJDRow(
            source_document_id=doc.id,
            parsed=jd.model_dump(mode="json"),
            parser_version=PARSER_VERSION,
            parse_confidence=1.0,
        )
        session.add(row)
        await session.commit()
        return doc.id, row.id


#: Every property a test needs off a written node, projected explicitly (the same
#: convention `memory.graph.GraphMemory` uses) rather than returned as a whole
#: driver `Node` object.
_DOC_PROPERTIES = (
    "d.id AS id, d.source_document_id AS source_document_id, "
    "d.parsed_jd_id AS parsed_jd_id, d.model AS model, d.embed_stamp AS embed_stamp, "
    "d.text_sha256 AS text_sha256, d.embedding AS embedding"
)
_SECTION_PROPERTIES = (
    "s.id AS id, s.section AS section, s.document_id AS document_id, "
    "s.text_sha256 AS text_sha256, s.embedding AS embedding"
)


async def _document_node(
    driver: AsyncDriver, source_document_id: uuid.UUID
) -> dict[str, Any] | None:
    async with driver.session() as session:
        result = await session.run(
            f"MATCH (d:JDDocument {{id: $id}}) RETURN {_DOC_PROPERTIES}",
            id=str(source_document_id),
        )
        record = await result.single()
        return dict(record) if record else None


async def _section_nodes(
    driver: AsyncDriver, source_document_id: uuid.UUID
) -> list[dict[str, Any]]:
    async with driver.session() as session:
        result = await session.run(
            "MATCH (d:JDDocument {id: $id})-[:HAS_SECTION]->(s:JDSection) "
            f"RETURN {_SECTION_PROPERTIES} ORDER BY s.section",
            id=str(source_document_id),
        )
        return [dict(record) async for record in result]


@pytest.mark.asyncio
async def test_first_pass_writes_document_and_section_nodes_with_has_section(
    pg_sessionmaker: async_sessionmaker[AsyncSession], neo4j_driver: AsyncDriver
) -> None:
    rules = get_rules()
    source_document_id, parsed_jd_id = await _seed_parsed_jd(pg_sessionmaker, _jd())
    fake = _FakeEmbedClient(rules.embeddings.dimensions)

    async with pg_sessionmaker() as session:
        result = await run_embeddings(session, neo4j_driver, rules=rules, client=fake)

    assert result.documents_embedded == 1
    assert result.sections_embedded == 2  # position_summary + duties; NOT quals
    assert fake.call_count >= 1

    # The counters that go into the committed artifact — every one of them, not just
    # the `*_embedded` half. `_jd()` has no qualifications, and `qualifications` is
    # one of the three `section_vectors`, so it is skipped rather than embedded.
    assert result.documents_seen == 1
    assert result.documents_unchanged == 0
    assert result.documents_empty == 0
    assert result.sections_unchanged == 0
    assert result.sections_skipped_short == 1
    assert result.nodes_pruned == 0
    assert result.bad_requests == 0

    doc_node = await _document_node(neo4j_driver, source_document_id)
    assert doc_node is not None
    assert doc_node["source_document_id"] == str(source_document_id)
    assert doc_node["parsed_jd_id"] == str(parsed_jd_id)
    assert doc_node["model"] == rules.embeddings.model
    assert len(doc_node["embedding"]) == rules.embeddings.dimensions

    sections = await _section_nodes(neo4j_driver, source_document_id)
    assert {s["section"] for s in sections} >= {"position_summary", "duties"}
    for section in sections:
        assert section["document_id"] == str(source_document_id)
        assert len(section["embedding"]) == rules.embeddings.dimensions


@pytest.mark.asyncio
async def test_second_pass_writes_nothing_and_calls_the_embedder_zero_times(
    pg_sessionmaker: async_sessionmaker[AsyncSession], neo4j_driver: AsyncDriver
) -> None:
    rules = get_rules()
    await _seed_parsed_jd(pg_sessionmaker, _jd())

    async with pg_sessionmaker() as session:
        await run_embeddings(
            session,
            neo4j_driver,
            rules=rules,
            client=_FakeEmbedClient(rules.embeddings.dimensions),
        )

    second_client = _FakeEmbedClient(rules.embeddings.dimensions)
    async with pg_sessionmaker() as session:
        second = await run_embeddings(
            session, neo4j_driver, rules=rules, client=second_client
        )

    assert second.documents_embedded == 0
    assert second.sections_embedded == 0
    assert second.embed_calls == 0
    assert second_client.call_count == 0  # THE pin: the mock was never even called


@pytest.mark.asyncio
async def test_a_stamp_change_re_embeds_in_place_with_no_orphan_nodes(
    pg_sessionmaker: async_sessionmaker[AsyncSession], neo4j_driver: AsyncDriver
) -> None:
    rules = get_rules()
    source_document_id, _ = await _seed_parsed_jd(pg_sessionmaker, _jd())

    async with pg_sessionmaker() as session:
        await run_embeddings(
            session,
            neo4j_driver,
            rules=rules,
            client=_FakeEmbedClient(rules.embeddings.dimensions),
        )
    before = await _document_node(neo4j_driver, source_document_id)
    before_stamp = before["embed_stamp"]

    retuned_rules = rules.model_copy(
        update={
            "embeddings": rules.embeddings.model_copy(
                update={"max_chars": rules.embeddings.max_chars - 1}
            )
        }
    )
    assert retuned_rules.embeddings.stamp != rules.embeddings.stamp

    async with pg_sessionmaker() as session:
        result = await run_embeddings(
            session,
            neo4j_driver,
            rules=retuned_rules,
            client=_FakeEmbedClient(rules.embeddings.dimensions),
        )

    assert result.documents_embedded == 1  # re-embedded, not skipped

    after = await _document_node(neo4j_driver, source_document_id)
    assert after is not None
    assert after["embed_stamp"] == retuned_rules.embeddings.stamp
    assert after["embed_stamp"] != before_stamp
    assert after["id"] == before["id"]  # SAME node — MERGE overwrote in place

    # ...and there is exactly ONE JDDocument node for this source document — no
    # orphan left behind by the stamp change.
    async with neo4j_driver.session() as session:
        count_result = await session.run(
            "MATCH (d:JDDocument {source_document_id: $id}) RETURN count(d) AS n",
            id=str(source_document_id),
        )
        record = await count_result.single()
    assert record is not None
    assert record["n"] == 1


@pytest.mark.asyncio
async def test_the_vector_actually_landed_in_the_index(
    pg_sessionmaker: async_sessionmaker[AsyncSession], neo4j_driver: AsyncDriver
) -> None:
    """Proves the vector is genuinely IN the index, not merely a property on the
    node — ``db.index.vector.queryNodes`` only returns indexed vectors."""
    rules = get_rules()
    source_document_id, _ = await _seed_parsed_jd(pg_sessionmaker, _jd())

    async with pg_sessionmaker() as session:
        await run_embeddings(
            session,
            neo4j_driver,
            rules=rules,
            client=_FakeEmbedClient(rules.embeddings.dimensions),
        )

    doc_node = await _document_node(neo4j_driver, source_document_id)
    query_vector = list(doc_node["embedding"])

    async with neo4j_driver.session() as session:
        result = await session.run(
            "CALL db.index.vector.queryNodes('jd_document_embeddings', 5, $vec) "
            "YIELD node RETURN node.id AS id",
            vec=query_vector,
        )
        ids = {record["id"] async for record in result}
    assert str(source_document_id) in ids


@pytest.mark.asyncio
async def test_vector_index_dimensions_match_the_rulebook(
    neo4j_driver: AsyncDriver,
) -> None:
    """The dimension lives in THREE homes (model, cypher, YAML) and the loader
    cannot see Neo4j — this is the only guard that checks the cypher migration
    actually agrees with ``rules.embeddings.dimensions``."""
    rules = get_rules()
    async with neo4j_driver.session() as session:
        result = await session.run(
            "SHOW VECTOR INDEXES YIELD name, options "
            "WHERE name IN ['jd_document_embeddings', 'jd_section_embeddings'] "
            "RETURN name, options"
        )
        # `options.indexConfig` — this Neo4j version's `SHOW VECTOR INDEXES` has no
        # top-level `indexConfig` column at all (only `options`, which nests it);
        # measured against the real image rather than assumed from older docs.
        rows = {
            record["name"]: record["options"]["indexConfig"] async for record in result
        }

    assert set(rows) == {"jd_document_embeddings", "jd_section_embeddings"}
    for config in rows.values():
        assert config["vector.dimensions"] == rules.embeddings.dimensions


@pytest.mark.asyncio
async def test_an_empty_text_jd_gets_no_node(
    pg_sessionmaker: async_sessionmaker[AsyncSession], neo4j_driver: AsyncDriver
) -> None:
    """The 34.5% WJQ-template case: a parsed JD whose configured sections are all
    empty must be counted as a skip and get NO node — never a zero vector."""
    rules = get_rules()
    empty_jd = SFUJobDescription(title="Untitled WJQ position")
    source_document_id, _ = await _seed_parsed_jd(pg_sessionmaker, empty_jd)
    fake = _FakeEmbedClient(rules.embeddings.dimensions)

    async with pg_sessionmaker() as session:
        result = await run_embeddings(session, neo4j_driver, rules=rules, client=fake)

    assert result.documents_empty == 1
    assert result.documents_embedded == 0
    assert fake.call_count == 0

    assert await _document_node(neo4j_driver, source_document_id) is None
    assert await _section_nodes(neo4j_driver, source_document_id) == []


# --- the sha -> vector binding: every node gets the vector of ITS OWN text --------


@pytest.mark.asyncio
async def test_each_node_gets_the_vector_of_its_own_text(
    pg_sessionmaker: async_sessionmaker[AsyncSession], neo4j_driver: AsyncDriver
) -> None:
    """**Every vector on the right JD — asserted, not assumed.**

    This is the same catastrophe the client's ``.index`` reassembly guard exists to
    prevent, one layer down: at the RUNNER's ``zip(chunk, vectors)`` rather than at
    the client's reassembly. The client honours its order contract and is tested for
    it; the runner *assumed* that contract and was tested for nothing. Mutating the
    runner to ``zip(chunk, reversed(vectors))`` — **every vector on the wrong JD** —
    left all 12 integration tests green, because not one of them ever asked what a
    node's embedding actually *is*:

    * ``test_first_pass`` only checked ``len(embedding) == dimensions``;
    * ``test_changed_parsed_content`` only checked the vector *changed*, not that it
      is *correct*;
    * ``test_byte_identical`` compares two documents that share a sha — the same
      vector either way.

    The shipped runner is correct. What was missing is the regression guard, and a
    future refactor (parallelising the batch loop, ``asyncio.gather`` over chunks,
    reordering ``to_embed``) is exactly what breaks this silently with the whole
    suite green.

    ``_FakeEmbedClient`` is content-keyed (:func:`_vector_for`), so the vector each
    node *must* carry is recomputable from that node's own serialized text — for the
    document AND for every section, because a section-level mis-binding is just as
    silent.
    """
    rules = get_rules()
    jd = _jd(
        qualifications=[
            SFUQualification(
                text="a bachelor's degree in a related discipline", kind="education"
            )
        ]
    )
    source_document_id, _ = await _seed_parsed_jd(pg_sessionmaker, jd)
    dimensions = rules.embeddings.dimensions

    async with pg_sessionmaker() as session:
        await run_embeddings(
            session,
            neo4j_driver,
            rules=rules,
            client=_FakeEmbedClient(dimensions),
        )

    # The DOCUMENT node carries the vector of the document's own serialized text.
    doc_node = await _document_node(neo4j_driver, source_document_id)
    assert doc_node is not None
    expected_document = serialize_document(jd, rules.embeddings)
    assert doc_node["text_sha256"] == expected_document.text_sha256
    assert doc_node["embedding"] == _vector_for(expected_document.text, dimensions)

    # ...and EACH SECTION node carries the vector of THAT SECTION's own text — which
    # is a different text from the document's, and from each other's.
    sections = await _section_nodes(neo4j_driver, source_document_id)
    assert len(sections) == 3  # position_summary + duties + qualifications
    seen: set[tuple[float, ...]] = set()
    for node in sections:
        expected_section = serialize_section(jd, rules.embeddings, node["section"])
        assert expected_section is not None
        assert node["text_sha256"] == expected_section.text_sha256
        assert node["embedding"] == _vector_for(expected_section.text, dimensions)
        seen.add(tuple(node["embedding"]))

    # The three section vectors really are distinct from one another and from the
    # document's — otherwise a mis-binding could not be detected by the assertions
    # above, and this test would be theatre for the same reason the model-source test
    # once was.
    assert len(seen) == 3
    assert tuple(doc_node["embedding"]) not in seen


# --- the content half of the skip key: text_sha256 --------------------------------


async def _reparse_in_place(
    maker: async_sessionmaker[AsyncSession],
    source_document_id: uuid.UUID,
    jd: SFUJobDescription,
) -> None:
    """Overwrite ``parsed_jds.parsed`` with new content at the SAME
    ``parser_version`` — exactly what a segmenter fix does to an existing row (the
    pending WJQ parser work will do this to 5,005 JDs)."""
    async with maker() as session:
        await session.execute(
            update(ParsedJDRow)
            .where(ParsedJDRow.source_document_id == source_document_id)
            .values(parsed=jd.model_dump(mode="json"))
        )
        await session.commit()


@pytest.mark.asyncio
async def test_changed_parsed_content_at_the_same_stamp_is_re_embedded(
    pg_sessionmaker: async_sessionmaker[AsyncSession], neo4j_driver: AsyncDriver
) -> None:
    """**The content half of the skip-first key, and nothing else pins it.**

    Drop ``text_sha256`` from the runner's ``NodeKey`` comparison — leaving it keyed
    on ``(model, embed_stamp)`` — and the whole suite stays green while a JD whose
    text has genuinely changed is silently SKIPPED, keeps its stale vector forever,
    and is reported as ``documents_unchanged``. Gates green, wrong vectors in the
    retrieval index.

    ``test_a_stamp_change_re_embeds_in_place`` cannot substitute: it moves the
    *stamp*, never the *text*. This moves the text and holds the stamp, the model and
    the parser_version all fixed — so the ONLY thing that can trigger the re-embed is
    the content hash.
    """
    rules = get_rules()
    source_document_id, _ = await _seed_parsed_jd(pg_sessionmaker, _jd())

    async with pg_sessionmaker() as session:
        await run_embeddings(
            session,
            neo4j_driver,
            rules=rules,
            client=_FakeEmbedClient(rules.embeddings.dimensions),
        )
    before = await _document_node(neo4j_driver, source_document_id)
    assert before is not None

    # A re-parse at the SAME parser_version, with materially different text.
    await _reparse_in_place(
        pg_sessionmaker,
        source_document_id,
        _jd(
            position_summary=(
                "An entirely different position summary, describing a different role "
                "with different responsibilities altogether."
            )
        ),
    )

    second_client = _FakeEmbedClient(rules.embeddings.dimensions)
    async with pg_sessionmaker() as session:
        result = await run_embeddings(
            session, neo4j_driver, rules=rules, client=second_client
        )

    # The stamp and the model did NOT move — only the text did.
    assert result.embed_stamp == before["embed_stamp"]
    assert result.model == before["model"]

    assert result.documents_embedded == 1  # RE-EMBEDDED...
    assert result.documents_unchanged == 0  # ...not reported as unchanged

    after = await _document_node(neo4j_driver, source_document_id)
    assert after is not None
    assert after["text_sha256"] != before["text_sha256"]
    assert after["embedding"] != before["embedding"]  # the VECTOR really moved


# --- the in-run memo: an optimization, NEVER a write-time collapse ---------------


@pytest.mark.asyncio
async def test_byte_identical_jds_embed_once_but_keep_separate_nodes(
    pg_sessionmaker: async_sessionmaker[AsyncSession], neo4j_driver: AsyncDriver
) -> None:
    """1,972 archive files are byte-identical duplicates (Tier-1's own finding) and
    serialize identically. The memo embeds each distinct text ONCE per run — but it
    must **never** collapse the nodes: two identical JDs are two documents, and 3.1
    spent an entire migration undoing exactly that write-time-collapse shape on
    ``source_documents``.

    So: one embed call, two nodes, and the memo reports the reuse.
    """
    rules = get_rules()
    identical = _jd()
    first_id, _ = await _seed_parsed_jd(pg_sessionmaker, identical)
    second_id, _ = await _seed_parsed_jd(pg_sessionmaker, identical)
    assert first_id != second_id

    fake = _FakeEmbedClient(rules.embeddings.dimensions)
    async with pg_sessionmaker() as session:
        result = await run_embeddings(session, neo4j_driver, rules=rules, client=fake)

    # ONE call: the two documents' texts, and their sections', are all identical, so
    # the distinct-sha set is small enough to fit in a single batch.
    assert result.embed_calls == 1
    assert result.embed_texts_reused_memo > 0

    # ...and TWO documents. Never one.
    assert result.documents_embedded == 2
    first_node = await _document_node(neo4j_driver, first_id)
    second_node = await _document_node(neo4j_driver, second_id)
    assert first_node is not None and second_node is not None
    assert first_node["id"] != second_node["id"]
    # Same content -> same vector and same sha (that IS the memo), different nodes.
    assert first_node["text_sha256"] == second_node["text_sha256"]
    assert first_node["embedding"] == second_node["embedding"]

    # ...and each keeps its own sections, hung off its own document.
    assert {s["document_id"] for s in await _section_nodes(neo4j_driver, first_id)} == {
        str(first_id)
    }
    assert {
        s["document_id"] for s in await _section_nodes(neo4j_driver, second_id)
    } == {str(second_id)}


# --- a 400 costs ONE text its vector, never its whole batch ----------------------


@pytest.mark.asyncio
async def test_one_over_long_text_does_not_cost_its_batch_mates_their_vectors(
    pg_sessionmaker: async_sessionmaker[AsyncSession], neo4j_driver: AsyncDriver
) -> None:
    """**A 400 is raised for the BATCH, not the text.**

    A naive ``except EmbeddingBadRequestError: continue`` writes off the whole chunk
    — up to ``batch_size - 1`` innocent JDs lose their vectors. And it never heals:
    ``to_embed`` is a sha-keyed dict rebuilt in the same deterministic order every
    run, so the identical batch fails identically, forever, while the process exits
    0. HR-126's ``impact_if_changed`` leans on "the runner catches and skips a 400"
    as the safety story for raising ``max_chars`` — this is what makes that true at
    BATCH granularity.

    Three JDs, one of them over-long: the other two must still land.
    """
    rules = get_rules()
    good_a, _ = await _seed_parsed_jd(pg_sessionmaker, _jd(position_summary="Role A."))
    good_b, _ = await _seed_parsed_jd(pg_sessionmaker, _jd(position_summary="Role B."))
    doomed_jd = _jd(position_summary="This one is too long for the server.")
    doomed, _ = await _seed_parsed_jd(pg_sessionmaker, doomed_jd)

    # The exact document text the runner will build for the doomed JD.
    doomed_text = serialize_document(doomed_jd, rules.embeddings).text
    fake = _FakeEmbedClient(
        rules.embeddings.dimensions, bad_request_texts=frozenset({doomed_text})
    )

    async with pg_sessionmaker() as session:
        result = await run_embeddings(session, neo4j_driver, rules=rules, client=fake)

    assert result.bad_requests == 1  # exactly ONE text was written off...
    # ...and its batch-mates were not.
    assert await _document_node(neo4j_driver, good_a) is not None
    assert await _document_node(neo4j_driver, good_b) is not None
    assert await _document_node(neo4j_driver, doomed) is None

    # The batch really was issued as one chunk first (that is what 400s), then the
    # runner isolated it: the fake saw a multi-text batch AND single-text retries.
    assert any(len(b) > 1 for b in fake.batches)
    assert any(len(b) == 1 for b in fake.batches)

    # `embed_calls` means "round-trips actually MADE" — so it counts the batch that
    # 400'd and every one-at-a-time retry it triggered. Pinned against the number of
    # calls the fake genuinely saw, so the counter cannot drift from the docstring.
    assert result.embed_calls == fake.call_count


# --- HR-193: an over-window text is RESCUED by the fallback ladder ----------------


def _long_doc_jd() -> SFUJobDescription:
    """A JD whose serialized document text exceeds ``max_chars`` — 40 qualification
    lines of ~380 chars each (~15k total, within the model's per-field caps) — so it
    truncates to the ``max_chars`` cap, and that truncated text is still long enough
    that re-cutting it to the first fallback rung (8,000) yields a DIFFERENT, shorter
    text. Models the dense WJQ docs that 400 even after truncation."""
    return _jd(
        qualifications=[
            SFUQualification(
                text=f"qualification {i}: " + "requirement detail " * 19, kind="skill"
            )
            for i in range(40)
        ]
    )


@pytest.mark.asyncio
async def test_an_over_window_text_is_rescued_by_the_fallback_ladder(
    pg_sessionmaker: async_sessionmaker[AsyncSession], neo4j_driver: AsyncDriver
) -> None:
    """**A 400 that survives ``max_chars`` truncation is backed off, not written off.**

    The shipped ladder is ``[8000, 6000, 4000]``. A doc whose ``max_chars`` text the
    server rejects gets re-cut to the first rung the server accepts, so it lands a
    best-effort (shorter) vector instead of none — the HR-193 resolution of HR-126.
    """
    rules = get_rules()
    assert rules.embeddings.max_chars_fallback[0] == 8_000  # the ladder under test
    doomed, _ = await _seed_parsed_jd(pg_sessionmaker, _long_doc_jd())

    # The exact ``max_chars`` text the runner builds — and what the first rung re-cuts
    # it to. Only the full text 400s; the shorter re-cut is accepted.
    doomed_serialized = serialize_document(_long_doc_jd(), rules.embeddings)
    doomed_text = doomed_serialized.text
    assert doomed_serialized.truncated is True  # sanity: it truncated at max_chars
    backed_off_text = retruncate_within(doomed_text, 8_000)
    assert 0 < len(backed_off_text) < len(doomed_text)
    fake = _FakeEmbedClient(
        rules.embeddings.dimensions, bad_request_texts=frozenset({doomed_text})
    )

    async with pg_sessionmaker() as session:
        result = await run_embeddings(session, neo4j_driver, rules=rules, client=fake)

    assert result.texts_backed_off == 1
    assert result.bad_requests == 0  # rescued, not written off
    assert result.documents_embedded == 1

    node = await _document_node(neo4j_driver, doomed)
    assert node is not None  # it got a vector, unlike the pre-HR-193 behavior
    # ...and it is the vector of the BACKED-OFF (shorter) text, not the doomed one.
    dim = rules.embeddings.dimensions
    assert node["embedding"] == _vector_for(backed_off_text, dim)
    assert node["embedding"] != _vector_for(doomed_text, dim)
    # Identity stays keyed on the full ``max_chars`` text (its sha), so a re-run is a
    # no-op — the skip-first idempotency guarantee survives the backoff.
    assert node["text_sha256"] == doomed_serialized.text_sha256

    fresh = _FakeEmbedClient(dim, bad_request_texts=frozenset({doomed_text}))
    async with pg_sessionmaker() as session:
        second = await run_embeddings(session, neo4j_driver, rules=rules, client=fresh)
    assert second.documents_embedded == 0  # unchanged corpus -> nothing re-embedded
    assert fresh.call_count == 0


@pytest.mark.asyncio
async def test_an_empty_fallback_ladder_writes_off_an_over_window_text(
    pg_sessionmaker: async_sessionmaker[AsyncSession], neo4j_driver: AsyncDriver
) -> None:
    """With ``max_chars_fallback = []`` the runner keeps the exact pre-HR-193
    behavior: the over-window text is counted ``bad_requests`` and gets NO node — so
    the knob's empty-list alternative is real, not decorative."""
    rules = get_rules()
    no_ladder = rules.model_copy(
        update={
            "embeddings": rules.embeddings.model_copy(update={"max_chars_fallback": ()})
        }
    )
    doomed, _ = await _seed_parsed_jd(pg_sessionmaker, _long_doc_jd())
    doomed_text = serialize_document(_long_doc_jd(), no_ladder.embeddings).text
    fake = _FakeEmbedClient(
        no_ladder.embeddings.dimensions, bad_request_texts=frozenset({doomed_text})
    )

    async with pg_sessionmaker() as session:
        result = await run_embeddings(
            session, neo4j_driver, rules=no_ladder, client=fake
        )

    assert result.texts_backed_off == 0
    assert result.bad_requests == 1
    assert await _document_node(neo4j_driver, doomed) is None


# --- the reconcile: a node that should no longer exist is DELETED, not left stale --


def _without_section(rules: Rules, section: str) -> Rules:
    kept = tuple(s for s in rules.embeddings.section_vectors if s != section)
    return rules.model_copy(
        update={
            "embeddings": rules.embeddings.model_copy(update={"section_vectors": kept})
        }
    )


@pytest.mark.asyncio
async def test_dropping_a_section_vector_prunes_its_nodes(
    pg_sessionmaker: async_sessionmaker[AsyncSession], neo4j_driver: AsyncDriver
) -> None:
    """**MERGE alone leaves the orphan LIVE IN THE QUERYABLE INDEX.**

    HR-130's ``impact_if_changed`` explicitly invites HR to drop a section from
    ``section_vectors``. Under a MERGE-only runner the stamp moves, everything
    re-embeds — and the orphaned ``<doc>:qualifications`` nodes are never touched
    again, so ``db.index.vector.queryNodes`` goes on returning a section the rulebook
    no longer says exists. 3.3/3.4 will query that index.

    So the node must be GONE, not merely stale. Asserted against the index itself,
    not only against the node.
    """
    rules = get_rules()
    jd = _jd(
        qualifications=[
            SFUQualification(
                text="a bachelor's degree in a related discipline", kind="education"
            )
        ]
    )
    source_document_id, _ = await _seed_parsed_jd(pg_sessionmaker, jd)

    async with pg_sessionmaker() as session:
        await run_embeddings(
            session,
            neo4j_driver,
            rules=rules,
            client=_FakeEmbedClient(rules.embeddings.dimensions),
        )
    before = {
        s["section"] for s in await _section_nodes(neo4j_driver, source_document_id)
    }
    assert "qualifications" in before

    # HR drops `qualifications` from section_vectors.
    retuned = _without_section(rules, "qualifications")
    async with pg_sessionmaker() as session:
        result = await run_embeddings(
            session,
            neo4j_driver,
            rules=retuned,
            client=_FakeEmbedClient(rules.embeddings.dimensions),
        )

    assert result.nodes_pruned == 1

    after = {
        s["section"] for s in await _section_nodes(neo4j_driver, source_document_id)
    }
    assert "qualifications" not in after
    assert after == before - {"qualifications"}

    # ...and it is gone from the INDEX, not merely from the HAS_SECTION traversal.
    async with neo4j_driver.session() as session:
        query = await session.run(
            "MATCH (s:JDSection {id: $id}) RETURN count(s) AS n",
            id=f"{source_document_id}:qualifications",
        )
        record = await query.single()
    assert record is not None
    assert record["n"] == 0


@pytest.mark.asyncio
async def test_a_jd_that_re_parses_to_empty_loses_its_nodes(
    pg_sessionmaker: async_sessionmaker[AsyncSession], neo4j_driver: AsyncDriver
) -> None:
    """The other reconcile path. A JD that had content and now parses to nothing
    (a segmenter change, a re-ingest of corrected bytes) would otherwise keep its
    **stale** ``JDDocument`` vector forever: the empty-text branch simply declines to
    write a node, and never goes looking for one that is already there."""
    rules = get_rules()
    source_document_id, _ = await _seed_parsed_jd(pg_sessionmaker, _jd())

    async with pg_sessionmaker() as session:
        await run_embeddings(
            session,
            neo4j_driver,
            rules=rules,
            client=_FakeEmbedClient(rules.embeddings.dimensions),
        )
    assert await _document_node(neo4j_driver, source_document_id) is not None
    assert await _section_nodes(neo4j_driver, source_document_id) != []

    await _reparse_in_place(
        pg_sessionmaker, source_document_id, SFUJobDescription(title="Now empty")
    )

    async with pg_sessionmaker() as session:
        result = await run_embeddings(
            session,
            neo4j_driver,
            rules=rules,
            client=_FakeEmbedClient(rules.embeddings.dimensions),
        )

    assert result.documents_empty == 1
    assert result.nodes_pruned >= 1

    assert await _document_node(neo4j_driver, source_document_id) is None
    async with neo4j_driver.session() as session:
        query = await session.run(
            "MATCH (s:JDSection {document_id: $id}) RETURN count(s) AS n",
            id=str(source_document_id),
        )
        record = await query.single()
    assert record is not None
    assert record["n"] == 0  # its sections went with it


@pytest.mark.asyncio
async def test_a_limited_run_never_prunes_what_it_did_not_read(
    pg_sessionmaker: async_sessionmaker[AsyncSession], neo4j_driver: AsyncDriver
) -> None:
    """**The reconcile's blast radius, pinned.**

    ``--limit`` takes the first N ``parsed_jds`` rows. The prune is scoped to the
    documents this run actually READ — its keep-list is built from the plan, which is
    built from ``rows`` — so a limited run must not touch a node belonging to a row it
    never looked at. Get that wrong and ``make embed --limit 200`` (the documented
    smoke test!) would delete the other 14,322 documents' vectors.

    ``limit`` was 0%-covered while MF5's entire safety story rested on it.
    """
    rules = get_rules()
    # Summaries long enough to clear `min_section_chars` (40) — otherwise the
    # position_summary section is legitimately skipped and this test would be
    # asserting the wrong section count for the wrong reason.
    ids = [
        (
            await _seed_parsed_jd(
                pg_sessionmaker,
                _jd(
                    position_summary=(
                        f"Coordinates workstream number {i} across the department, "
                        f"reporting to the associate director."
                    )
                ),
            )
        )[0]
        for i in range(3)
    ]

    async with pg_sessionmaker() as session:
        full = await run_embeddings(
            session,
            neo4j_driver,
            rules=rules,
            client=_FakeEmbedClient(rules.embeddings.dimensions),
        )
    assert full.documents_seen == 3
    assert full.documents_embedded == 3
    before = {i: await _document_node(neo4j_driver, i) for i in ids}
    assert all(node is not None for node in before.values())

    async with pg_sessionmaker() as session:
        limited = await run_embeddings(
            session,
            neo4j_driver,
            rules=rules,
            client=_FakeEmbedClient(rules.embeddings.dimensions),
            limit=1,
        )

    assert limited.documents_seen == 1  # it really did read only one row...
    assert limited.nodes_pruned == 0  # ...and it deleted NOTHING

    # All three documents — and all their sections — survive, byte for byte.
    async with neo4j_driver.session() as session:
        counted = await session.run("MATCH (d:JDDocument) RETURN count(d) AS docs")
        record = await counted.single()
    assert record is not None
    assert record["docs"] == 3
    for doc_id in ids:
        after = await _document_node(neo4j_driver, doc_id)
        assert after is not None
        assert after["embedding"] == before[doc_id]["embedding"]  # type: ignore[index]
        assert len(await _section_nodes(neo4j_driver, doc_id)) == 2


@pytest.mark.asyncio
async def test_an_unchanged_pass_prunes_nothing(
    pg_sessionmaker: async_sessionmaker[AsyncSession], neo4j_driver: AsyncDriver
) -> None:
    """The reconcile's own safety pin: pruning must not delete nodes that are still
    planned. A second pass over an unchanged corpus prunes ZERO — otherwise the
    reconcile would be re-embedding the archive on a churn of its own making."""
    rules = get_rules()
    await _seed_parsed_jd(pg_sessionmaker, _jd())

    async with pg_sessionmaker() as session:
        first = await run_embeddings(
            session,
            neo4j_driver,
            rules=rules,
            client=_FakeEmbedClient(rules.embeddings.dimensions),
        )
    async with pg_sessionmaker() as session:
        second = await run_embeddings(
            session,
            neo4j_driver,
            rules=rules,
            client=_FakeEmbedClient(rules.embeddings.dimensions),
        )

    assert first.nodes_pruned == 0
    assert second.nodes_pruned == 0
    # ...and the unchanged counters — the other half of the artifact — really report.
    assert second.documents_unchanged == 1
    assert second.sections_unchanged == first.sections_embedded
    assert second.sections_embedded == 0

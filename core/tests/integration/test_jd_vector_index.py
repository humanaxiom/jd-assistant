"""Integration test — JD Bank Neo4j vector indexes via testcontainers.

Applies ``core/db/migrations/002_jd_vectors.cypher`` to a real Neo4j and
asserts the two 768-dim cosine vector indexes (document + section) exist, in the
same spirit as ``001_init``'s ``artifact_embeddings`` index.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
from neo4j import AsyncGraphDatabase
from testcontainers.neo4j import Neo4jContainer

CORE_DIR = Path(__file__).resolve().parents[2]
VECTOR_CYPHER = CORE_DIR / "db" / "migrations" / "002_jd_vectors.cypher"


def _statements(path: Path) -> list[str]:
    """Split a .cypher file into individual statements, dropping // comments."""
    lines = [
        line
        for line in path.read_text(encoding="utf-8").splitlines()
        if not line.strip().startswith("//")
    ]
    body = "\n".join(lines)
    return [stmt.strip() for stmt in body.split(";") if stmt.strip()]


@pytest.fixture(scope="module")
def neo4j_container() -> Iterator[Neo4jContainer]:
    with Neo4jContainer("neo4j:5-community") as neo:
        yield neo


@pytest.fixture
async def driver(
    neo4j_container: Neo4jContainer,
) -> AsyncIterator[AsyncGraphDatabase]:
    drv = AsyncGraphDatabase.driver(
        neo4j_container.get_connection_url(),
        auth=("neo4j", neo4j_container.password),
    )
    yield drv
    await drv.close()


@pytest.mark.asyncio
async def test_jd_vector_indexes_created(driver: AsyncGraphDatabase) -> None:
    statements = _statements(VECTOR_CYPHER)
    assert statements, "expected at least one cypher statement"

    async with driver.session() as session:
        for stmt in statements:
            await session.run(stmt)

        result = await session.run(
            "SHOW INDEXES YIELD name, type "
            "WHERE type = 'VECTOR' RETURN collect(name) AS names"
        )
        record = await result.single()
        names = set(record["names"]) if record else set()

    assert "jd_document_embeddings" in names
    assert "jd_section_embeddings" in names

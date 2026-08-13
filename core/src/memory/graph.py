"""Neo4j graph memory — agent lineage graph + vector retrieval of artifacts.

Schema:
    (:Task)-[:DECOMPOSED_INTO]->(:Subtask)-[:EXECUTED_BY]->(:Agent)
    (:Subtask)-[:PRODUCED]->(:Artifact {embedding: vector})
    (:Run)-[:OF_TASK]->(:Task)
    (:Run)-[:GATE_RESULT]->(:GateResult)

Vector index `artifact_embeddings` supports semantic retrieval so agents
can ask "have we solved something like this before?".
"""

from __future__ import annotations

from typing import Any

from neo4j import AsyncDriver, AsyncGraphDatabase
from openai import AsyncOpenAI

from src.jd_bank.security.egress import assert_inference_host_allowed
from src.settings import get_settings


class GraphMemory:
    def __init__(self, driver: AsyncDriver | None = None) -> None:
        s = get_settings()
        self._driver = driver or AsyncGraphDatabase.driver(
            s.neo4j_uri, auth=(s.neo4j_user, s.neo4j_password)
        )
        # NN #5, at the point of construction (P0.1b-ii). The two JD-content sinks
        # (`jd_bank.llm.client`, `jd_bank.embeddings.client`) have been guarded since
        # Phase 4.6a; this one was not, and it builds the same kind of client from the
        # same setting. It embeds AGENT ARTIFACTS rather than JD text, which is why it
        # was missed and is not why it is safe: an artifact is a diff, a spec or a
        # reviewer's note about the JD pipeline, `ollama_base_url` is one value shared
        # with the guarded clients, and "this particular egress carries slightly less
        # sensitive content" is not a boundary anyone can maintain. One setting, one
        # rule, checked everywhere it is read.
        assert_inference_host_allowed(s.ollama_base_url)
        self._embed_client = AsyncOpenAI(
            base_url=s.ollama_base_url, api_key="ollama"  # Ollama ignores key
        )
        self._embed_model = s.embed_model

    async def close(self) -> None:
        await self._driver.close()

    async def verify_connectivity(self) -> None:
        """Round-trip the driver; raise if Neo4j is unreachable or refuses the auth.

        The readiness probe (``src.api.readiness``) needs *a* cheap liveness question to
        ask Neo4j, and it must ask it through this class rather than reaching into
        ``_driver`` — the driver is this object's private business.
        """
        await self._driver.verify_connectivity()

    # ── Write path ─────────────────────────────────────────────────────────

    async def record_subtask(
        self, task_id: str, subtask_id: str, agent_id: str, description: str
    ) -> None:
        query = """
        MERGE (t:Task {id: $task_id})
        MERGE (s:Subtask {id: $subtask_id})
        SET s.description = $description
        MERGE (a:Agent {id: $agent_id})
        MERGE (t)-[:DECOMPOSED_INTO]->(s)
        MERGE (s)-[:EXECUTED_BY]->(a)
        """
        async with self._driver.session() as session:
            await session.run(
                query,
                task_id=task_id,
                subtask_id=subtask_id,
                agent_id=agent_id,
                description=description,
            )

    async def record_artifact(
        self, subtask_id: str, artifact_id: str, content: str, kind: str
    ) -> None:
        """Store an artifact with its embedding for later semantic retrieval."""
        embedding = await self._embed(content)
        query = """
        MATCH (s:Subtask {id: $subtask_id})
        MERGE (ar:Artifact {id: $artifact_id})
        SET ar.content = $content, ar.kind = $kind, ar.embedding = $embedding
        MERGE (s)-[:PRODUCED]->(ar)
        """
        async with self._driver.session() as session:
            await session.run(
                query,
                subtask_id=subtask_id,
                artifact_id=artifact_id,
                content=content[:10_000],
                kind=kind,
                embedding=embedding,
            )

    # ── Read path ──────────────────────────────────────────────────────────

    async def similar_artifacts(
        self, query_text: str, k: int = 5
    ) -> list[dict[str, Any]]:
        """Vector search: find prior artifacts semantically similar to a query."""
        embedding = await self._embed(query_text)
        query = """
        CALL db.index.vector.queryNodes('artifact_embeddings', $k, $embedding)
        YIELD node, score
        RETURN node.id AS id, node.kind AS kind,
               left(node.content, 2000) AS content, score
        ORDER BY score DESC
        """
        async with self._driver.session() as session:
            result = await session.run(query, k=k, embedding=embedding)
            return [dict(record) async for record in result]

    async def task_lineage(self, task_id: str) -> list[dict[str, Any]]:
        """Full lineage of a task: subtasks, agents, artifacts."""
        query = """
        MATCH (t:Task {id: $task_id})-[:DECOMPOSED_INTO]->(s:Subtask)
        OPTIONAL MATCH (s)-[:EXECUTED_BY]->(a:Agent)
        OPTIONAL MATCH (s)-[:PRODUCED]->(ar:Artifact)
        RETURN s.id AS subtask, s.description AS description,
               a.id AS agent, collect(ar.id) AS artifacts
        """
        async with self._driver.session() as session:
            result = await session.run(query, task_id=task_id)
            return [dict(record) async for record in result]

    # ── Internals ──────────────────────────────────────────────────────────

    async def _embed(self, text: str) -> list[float]:
        response = await self._embed_client.embeddings.create(
            model=self._embed_model, input=text[:8_000]
        )
        return response.data[0].embedding

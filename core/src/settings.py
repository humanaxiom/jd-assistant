"""Central configuration — single source of truth, loaded from env."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Inference: Ollama on metal, OpenAI-compatible /v1 (ADR-003, amended 2026-07-13).
    # It runs on a TRUSTED INTERNAL HOST — `aria-gb10-2` — not on the dev box, and not
    # `host.docker.internal` (which is what this said until someone checked). Overridden
    # by OLLAMA_BASE_URL in compose. `nomic-embed-text` is 768-dim, matching the ADR-002
    # Neo4j vector index — verified from inside the `gates` container, not assumed.
    #
    # NOTE: local `make gates` reaches this host; CI (`ubuntu-latest`) CANNOT, and never
    # will. Nothing on the `make gates` path may call a live endpoint. See ADR-003.
    ollama_base_url: str = "http://aria-gb10-2:11434/v1"
    agent_model: str = "qwen2.5-coder:14b"
    embed_model: str = "nomic-embed-text"

    # Postgres (transactions)
    database_url: str = "postgresql+asyncpg://app:app@postgres:5432/harness"

    # Neo4j (graph + vector memory)
    neo4j_uri: str = "bolt://neo4j:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "harnesspass"

    # Redis / arq
    redis_url: str = "redis://redis:6379/0"

    # Review loop
    max_review_iterations: int = 5
    coverage_threshold: int = 80

    model_config = {"env_file": ".env", "extra": "ignore"}


@lru_cache
def get_settings() -> Settings:
    return Settings()

"""Central configuration — single source of truth, loaded from env."""

from __future__ import annotations

from functools import lru_cache

from pydantic import field_validator
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
    # Phase 4.6a — the build-enforced form of CLAUDE.md NN #5 (no vendor egress of JD
    # content). OPS/SECURITY config, NOT a JD-scoring rule: it changes no JD's score, so
    # it lives here and NOT in `jd_core/rules/` or the HR decision register. The two
    # JD-content network sinks (`jd_bank.llm.client.ChatClient`,
    # `jd_bank.embeddings.client.EmbedClient`) refuse to build against a host not on
    # this list — see `jd_bank.security.egress` and docs/security/egress-audit.md. The
    # default admits the internal Ollama host (`aria-gb10-2`) plus loopback / the docker
    # host (a future dev-box Ollama is a permitted INTERNAL case); private/RFC-1918 IP
    # literals are allowed by the guard directly. Override with the comma-separated env
    # var ALLOWED_INFERENCE_HOSTS. If the inference host ever moves OFF a trusted
    # segment this is a FIPPA question (NN #5) — re-decide it, don't just append here.
    allowed_inference_hosts: list[str] = [
        "aria-gb10-2",
        "localhost",
        "127.0.0.1",
        "host.docker.internal",
    ]
    agent_model: str = "qwen2.5-coder:14b"

    @field_validator("allowed_inference_hosts", mode="before")
    @classmethod
    def _split_allowed_hosts(cls, value: object) -> object:
        """Accept a comma-separated string (the natural env form) as a host list."""
        if isinstance(value, str):
            return [host.strip() for host in value.split(",") if host.strip()]
        return value

    # The HARNESS agent-memory embedding model (`memory.graph.GraphMemory`'s
    # `artifact_embeddings` index — lineage-graph retrieval). NOT what JD Bank
    # embeds a parsed JD with — that is `get_rules().embeddings.model` (HR-124),
    # a rulebook decision. The two coincide today (both `nomic-embed-text`) but
    # must be free to diverge: `src.jd_bank.embeddings` must never read this field.
    embed_model: str = "nomic-embed-text"
    # Phase 3.2b: OPERATIONAL, not a rulebook decision — MEASURED that a batched
    # embedding call returns identical vectors to one-at-a-time (ADR-003 / HR-124),
    # so this only trades throughput for memory and never changes what gets stored.
    embed_batch_size: int = 64

    # Phase 3.3: OPERATIONAL, not a rulebook decision — how many rows one
    # insert/update/delete statement (or one Neo4j vector fetch) carries in the
    # Tier-2 near-dup reconcile (`jd_bank.dedup.near.runner`). It cannot change WHICH
    # edges get written, only how many round-trips writing them costs; `dedup.yaml`
    # is where a decision that changes the RESULT would live.
    neardup_batch_size: int = 500

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

    # Read-only dashboards (Phase 4.6c): where the committed archive-baseline artifact
    # is mounted INSIDE the api container. `docs/` lives at the repo root (NOT under
    # `core/`, which binds to /app), so the compose api service binds `./docs:/docs:ro`
    # and this points at the baseline summary within it. Overridable (env
    # BASELINE_SUMMARY_PATH) and, in tests, via the `get_baseline_summary_path`
    # dependency — so a unit test can aim the loader at a fixture without a real mount.
    baseline_summary_path: str = "/docs/baseline/summary.json"

    # The dedup (Tier 1/2/3) + cluster read-only dashboards (Phase 4.6c slices 2+3) read
    # the SAME committed artifacts `make dedup` / `make near-dup` / `make dedup-role` /
    # `make cluster` write, mounted at `/docs/...` by the compose api service's
    # `./docs:/docs:ro` bind. Each mirrors `baseline_summary_path`: env-overridable
    # (DEDUP_SUMMARY_PATH etc.) and, in tests, aimed at a fixture via the matching
    # `get_*_summary_path` FastAPI dependency — so no real mount is needed to unit-test.
    dedup_summary_path: str = "/docs/dedup/summary.json"
    near_dup_summary_path: str = "/docs/dedup/near-dup-summary.json"
    role_equiv_summary_path: str = "/docs/dedup/role-equiv-summary.json"
    cluster_summary_path: str = "/docs/cluster/cluster-summary.json"

    model_config = {"env_file": ".env", "extra": "ignore"}


@lru_cache
def get_settings() -> Settings:
    return Settings()

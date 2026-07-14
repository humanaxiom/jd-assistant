"""JD Bank embeddings (Phase 3.2b): ``parsed_jds`` (Postgres) -> Neo4j vector index.

    from src.jd_bank.embeddings import run_embeddings

See :mod:`.runner` for the orchestration, :mod:`.store` for the Neo4j writes, and
:mod:`.client` for the Ollama call. The text a JD becomes is decided by the pure,
versioned :mod:`src.jd_core.bank.embed_text` (rulebook: ``embeddings.yaml``).
"""

from src.jd_bank.embeddings.client import EmbedClient, EmbeddingBadRequestError
from src.jd_bank.embeddings.models import (
    DocumentWrite,
    EmbedRunResult,
    NodeKey,
    SectionWrite,
)
from src.jd_bank.embeddings.runner import run_embeddings
from src.jd_bank.embeddings.store import prune_documents, prune_sections

__all__ = [
    "DocumentWrite",
    "EmbedClient",
    "EmbedRunResult",
    "EmbeddingBadRequestError",
    "NodeKey",
    "SectionWrite",
    "prune_documents",
    "prune_sections",
    "run_embeddings",
]

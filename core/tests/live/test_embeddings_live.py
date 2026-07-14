"""Live golden tests — the real ``nomic-embed-text`` on ``aria-gb10-2`` (ADR-003).

**Opt-in, LOCAL-ONLY.** ``make gates-live``, never ``make gates`` / CI:

* ``core/pyproject.toml``'s ``addopts`` deselects ``-m live`` by default, and the
  Makefile / CI additionally pass ``-m "not live"`` on the commands that matter — so
  even a bare ``pytest`` inside the ``gates`` container (its default compose command)
  cannot collect these.
* CI (``ubuntu-latest``) cannot route to ``aria-gb10-2`` and never will, marker or
  not — a cloud runner cannot reach a private internal host.
* A developer's local `make gates-live` still self-skips (see
  :func:`_skip_if_unreachable`) if they happen to be off-VPN, so this file is honest
  in every environment it might run in, not just the two we control for.

**Validator-as-oracle, applied to a vector**: every assertion here is a RELATION
(dimension count, equality, a comparative cosine) — never a hardcoded vector value,
which would not be portable across model-server versions anyway.
"""

from __future__ import annotations

import asyncio
import math

import pytest

from src.jd_bank.embeddings.client import EmbedClient
from src.jd_core.rules import get_rules

pytestmark = pytest.mark.live


def _probe_reachable() -> bool:
    async def _try() -> bool:
        client = EmbedClient(rules=get_rules())
        try:
            await asyncio.wait_for(client.embed_batch(["probe"]), timeout=5.0)
            return True
        except Exception:  # noqa: BLE001 - any failure means "not reachable right now"
            return False
        finally:
            await client.close()

    return asyncio.run(_try())


@pytest.fixture(autouse=True)
def _skip_if_unreachable() -> None:
    if not _probe_reachable():
        pytest.skip(
            "aria-gb10-2 (Ollama) is unreachable from this host — local-only test, "
            "see ADR-003"
        )


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    return dot / (norm_a * norm_b)


@pytest.mark.asyncio
async def test_the_embedding_dimension_matches_the_rulebook_and_the_index() -> None:
    """The THIRD home of "768" (model card, ``002_jd_vectors.cypher``, here) — the
    one thing the loader cannot check because it cannot see Ollama or Neo4j."""
    rules = get_rules()
    client = EmbedClient(rules=rules)
    try:
        [vector] = await client.embed_batch(["a representative job description"])
    finally:
        await client.close()
    assert len(vector) == rules.embeddings.dimensions


@pytest.mark.asyncio
async def test_the_same_text_yields_the_same_vector() -> None:
    """MEASURED basis of the whole content-keyed idempotency design (the store's
    skip-first pass, the runner's in-run memo): same text -> byte-identical vector."""
    client = EmbedClient(rules=get_rules())
    try:
        first = await client.embed_batch(["identical text, embedded twice"])
        second = await client.embed_batch(["identical text, embedded twice"])
    finally:
        await client.close()
    assert first == second


@pytest.mark.asyncio
async def test_a_reworded_jd_is_nearer_than_an_unrelated_one() -> None:
    """A RELATION, never a raw score: a paraphrase of the same role must sit closer
    in vector space than an unrelated one — cos(A, A') > cos(A, B)."""
    client = EmbedClient(rules=get_rules())
    try:
        vectors = await client.embed_batch(
            [
                "Manages the department's annual budget and supervises three "
                "financial analysts.",
                "Oversees the department's yearly budget and leads a team of "
                "financial analysts.",
                "Waters the office plants and restocks the supply closet.",
            ]
        )
    finally:
        await client.close()
    original, reworded, unrelated = vectors
    assert _cosine(original, reworded) > _cosine(original, unrelated)

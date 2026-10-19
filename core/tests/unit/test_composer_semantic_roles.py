"""Track I1 — ``semantic_role_neighbours``, the role pass shared with the library.

It must be the SAME pass the Builder runs (``_nearest_role_ids`` under the live embed
stamp), return an ORDER with no score, and never embed a blank query.
"""

from __future__ import annotations

import uuid
from typing import Any

from src.jd_bank.composer import search as search_mod
from src.jd_core.rules import get_rules


class _Embed:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    async def embed_batch(self, texts: Any) -> list[list[float]]:
        self.calls.append(list(texts))
        return [[0.5] * 768]


async def test_returns_the_order_without_scores_and_uses_the_live_stamp(
    monkeypatch: Any,
) -> None:
    a, b = uuid.uuid4(), uuid.uuid4()
    seen: dict[str, Any] = {}

    async def fake(driver: Any, vector: Any, k: int, *, live_stamp: str) -> list[Any]:
        seen.update(k=k, stamp=live_stamp, vector=vector)
        return [(a, "First", "apsa", 0.99), (b, "Second", None, 0.12)]

    monkeypatch.setattr(search_mod, "_nearest_role_ids", fake)
    embed = _Embed()

    out = await search_mod.semantic_role_neighbours(
        "invoices",
        embed_client=embed,  # type: ignore[arg-type]
        neo4j_driver=object(),  # type: ignore[arg-type]
        k=7,
    )

    assert out == [(a, "First", "apsa"), (b, "Second", None)]
    assert seen["k"] == 7
    assert seen["stamp"] == get_rules().embeddings.stamp
    assert embed.calls == [["invoices"]]


async def test_a_blank_query_is_never_embedded() -> None:
    embed = _Embed()
    out = await search_mod.semantic_role_neighbours(
        "  ",
        embed_client=embed,  # type: ignore[arg-type]
        neo4j_driver=object(),  # type: ignore[arg-type]
        k=5,
    )
    assert out == [] and embed.calls == []

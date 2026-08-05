"""Embed HARMONIZED ROLES into Neo4j so the Builder can search the Bank's own output.

The archive pass (:mod:`src.jd_bank.embeddings.runner`) embeds source *documents*.
This one embeds the roles those documents were harmonized into — one ``(:JDRole)``
node per cluster, in the ``jd_role_embeddings`` index (migration 003).

**Why roles need their own vectors.** Without them the Builder's "start from an
existing JD" can only reach a role by TITLE; a descriptive query ("someone who runs
AV kit for events") can only ever return raw archive parses, so the Bank cannot
semantically search the very output it exists to produce.

**Every current-version role, draft included.** The Builder's purpose here is to seed
a clone, not to publish: the role library already lists drafts and already offers
"Start from harmonized role" for them, so restricting this to PUBLISHED would index
four roles instead of ~1,800 and make the feature useful only after the pilot. The
node carries ``status`` so a hit can still be labelled honestly.

**Serialization is shared, not re-invented.** ``canonical_jds.content`` validates to
the same :class:`~src.jd_core.models.parsed_jd.SFUJobDescription` the archive pass
serializes, so :func:`~src.jd_core.bank.embed_text.serialize_document` is reused
verbatim — same rulebook knobs, same ``embed_stamp``, same title exclusion. No new
decision, and ``rules_version`` is untouched.

**Not wired into ``approve``.** Publishing must not depend on the GPU — a reviewer
has to be able to approve with Ollama down — and doing network I/O inside the review
transaction would hold the ``SELECT … FOR UPDATE`` lock across a slow call. This is an
idempotent runner you run afterwards, exactly like ``make embed``.

Skip-first on the same :class:`~src.jd_bank.embeddings.models.NodeKey` identity as
documents, so a re-run costs nothing and an edited role re-embeds automatically.
"""

from __future__ import annotations

from uuid import UUID

from neo4j import AsyncDriver
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.jd_bank.db.models import CanonicalJD
from src.jd_bank.embeddings.client import EmbedClient
from src.jd_bank.embeddings.models import NodeKey, RoleWrite
from src.jd_bank.embeddings.store import (
    fetch_existing_role_keys,
    prune_roles,
    write_roles,
)
from src.jd_core.bank.embed_text import (
    SERIALIZER_VERSION,
    SerializedText,
    serialize_document,
)
from src.jd_core.models.parsed_jd import SFUJobDescription
from src.jd_core.rules import Rules, get_rules

#: How many role texts go to the embedding endpoint at once. Matches the archive
#: runner's batching rationale: big enough to amortise the round trip, small enough
#: that one failure does not cost the whole run.
_BATCH = 64


class RoleEmbeddingSummary(BaseModel):
    """Counts for one role-embedding pass — the committed artifact's shape."""

    model_config = ConfigDict(extra="forbid")

    roles_seen: int = 0
    roles_embedded: int = 0
    roles_unchanged: int = 0
    roles_empty: int = 0
    nodes_pruned: int = 0
    model: str = ""
    dimensions: int = 0
    embed_stamp: str = ""
    serializer_version: str = ""


async def _current_roles(session: AsyncSession) -> list[CanonicalJD]:
    """The CURRENT canonical of every cluster — highest version per cluster.

    A superseded version must never be embedded: it would put a second vector for the
    same role in the index, and the older text would compete with the live one.
    """
    current = (
        select(
            CanonicalJD.cluster_id,
            func.max(CanonicalJD.version).label("version"),
        )
        .group_by(CanonicalJD.cluster_id)
        .subquery()
    )
    return list(
        (
            await session.scalars(
                select(CanonicalJD).join(
                    current,
                    (CanonicalJD.cluster_id == current.c.cluster_id)
                    & (CanonicalJD.version == current.c.version),
                )
            )
        ).all()
    )


async def run_role_embedding(
    session: AsyncSession,
    *,
    embed_client: EmbedClient,
    neo4j_driver: AsyncDriver,
    limit: int | None = None,
    rules: Rules | None = None,
) -> RoleEmbeddingSummary:
    """Embed every current-version harmonized role that is not already current in the
    index, and prune role nodes whose cluster is no longer planned."""
    rulebook = rules if rules is not None else get_rules()
    embeddings = rulebook.embeddings
    summary = RoleEmbeddingSummary(
        model=embeddings.model,
        dimensions=embeddings.dimensions,
        embed_stamp=embeddings.stamp,
        serializer_version=SERIALIZER_VERSION,
    )

    roles = await _current_roles(session)
    if limit is not None:
        roles = roles[:limit]
    existing = await fetch_existing_role_keys(neo4j_driver)

    planned: set[UUID] = set()
    pending: list[tuple[CanonicalJD, SerializedText]] = []
    for canonical in roles:
        summary.roles_seen += 1
        try:
            jd = SFUJobDescription.model_validate(canonical.content or {})
        except Exception:  # noqa: BLE001 — a malformed row must not abort the run
            summary.roles_empty += 1
            continue
        serialized = serialize_document(jd, embeddings)
        if not serialized.text:
            # No content-bearing text at all. NEVER embed "" — a zero-ish vector is a
            # nearest neighbour to everything, which is worse than being absent.
            summary.roles_empty += 1
            continue
        planned.add(canonical.cluster_id)
        key = NodeKey(serialized.text_sha256, embeddings.model, embeddings.stamp)
        if existing.get(canonical.cluster_id) == key:
            summary.roles_unchanged += 1
            continue
        pending.append((canonical, serialized))

    for start in range(0, len(pending), _BATCH):
        chunk = pending[start : start + _BATCH]
        vectors = await embed_client.embed_batch([s.text for _, s in chunk])
        rows = [
            RoleWrite(
                cluster_id=canonical.cluster_id,
                canonical_jd_id=canonical.id,
                version=canonical.version,
                status=canonical.status.value,
                title=str((canonical.content or {}).get("title") or ""),
                employee_group=(canonical.content or {}).get("employee_group"),
                text_sha256=serialized.text_sha256,
                text_chars=serialized.text_chars,
                truncated=serialized.truncated,
                embedding=list(vector),
                model=embeddings.model,
                dimensions=embeddings.dimensions,
                embed_stamp=embeddings.stamp,
                serializer_version=SERIALIZER_VERSION,
            )
            for (canonical, serialized), vector in zip(chunk, vectors, strict=True)
        ]
        await write_roles(neo4j_driver, rows)
        summary.roles_embedded += len(rows)

    # Roles that exist as nodes but are no longer planned (cluster pruned, or the
    # canonical no longer serializes) — MERGE alone would leave them as stale hits.
    summary.nodes_pruned = await prune_roles(
        neo4j_driver, [cid for cid in existing if cid not in planned]
    )
    return summary

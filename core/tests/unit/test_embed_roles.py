"""Phase 5.4b — embedding HARMONIZED ROLES so the Bank can search its own output.

The Postgres read and the Neo4j write are monkeypatched, so these pin the runner's
own decisions: which roles are planned (current version only), skip-first, never
embedding an empty text, and pruning nodes whose cluster is gone.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from src.jd_bank.embeddings import roles as roles_mod
from src.jd_bank.embeddings.client import EmbeddingBadRequestError
from src.jd_bank.embeddings.models import NodeKey
from src.jd_core.bank.embed_text import serialize_document
from src.jd_core.models.parsed_jd import (
    SFUDuty,
    SFUJobDescription,
    SFUQualification,
)
from src.jd_core.rules import get_rules


class _FakeEmbed:
    def __init__(self) -> None:
        self.batches: list[list[str]] = []

    async def embed_batch(self, texts: Any) -> list[list[float]]:
        batch = list(texts)
        self.batches.append(batch)
        return [[0.1] * 768 for _ in batch]

    async def close(self) -> None:
        return None


class _FakeCanonical:
    """Enough of ``CanonicalJD`` for the runner: it reads id/cluster/version/status
    and the content dict."""

    def __init__(
        self,
        *,
        cluster_id: uuid.UUID,
        content: dict[str, Any],
        version: int = 1,
        status: str = "DRAFT",
    ) -> None:
        self.id = uuid.uuid4()
        self.cluster_id = cluster_id
        self.version = version
        self.content = content
        self.status = type("S", (), {"value": status})()


def _content(title: str) -> dict[str, Any]:
    return SFUJobDescription(
        title=title,
        employee_group="apsa",
        position_summary=" ".join(["word"] * 60),
        duties=[SFUDuty(action_verb="Manages", statement="Manages the program")],
    ).model_dump(mode="json")


def _wire(
    monkeypatch: pytest.MonkeyPatch,
    *,
    current: list[Any],
    existing: dict[uuid.UUID, NodeKey] | None = None,
) -> dict[str, Any]:
    """Fake the three I/O seams and capture what the runner wrote/pruned."""
    captured: dict[str, Any] = {"written": [], "pruned": []}

    async def fake_current(session: Any) -> list[Any]:
        return current

    async def fake_existing(driver: Any) -> dict[uuid.UUID, NodeKey]:
        return dict(existing or {})

    async def fake_write(driver: Any, rows: Any) -> None:
        captured["written"].extend(rows)

    async def fake_prune(driver: Any, ids: Any) -> int:
        captured["pruned"].extend(ids)
        return len(list(ids))

    monkeypatch.setattr(roles_mod, "_current_roles", fake_current)
    monkeypatch.setattr(roles_mod, "fetch_existing_role_keys", fake_existing)
    monkeypatch.setattr(roles_mod, "write_roles", fake_write)
    monkeypatch.setattr(roles_mod, "prune_roles", fake_prune)
    return captured


async def test_embeds_every_current_role_including_drafts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """DRAFT roles are embedded on purpose. The Builder's use here is seeding a CLONE,
    not publishing: the role library already lists drafts and already offers "Start
    from harmonized role" for them, so a published-only index would hold 4 roles
    instead of ~1,800 and be useless until after the pilot."""
    draft = _FakeCanonical(cluster_id=uuid.uuid4(), content=_content("Analyst"))
    published = _FakeCanonical(
        cluster_id=uuid.uuid4(), content=_content("Advisor"), status="PUBLISHED"
    )
    captured = _wire(monkeypatch, current=[draft, published])

    summary = await roles_mod.run_role_embedding(
        object(),  # type: ignore[arg-type]
        embed_client=_FakeEmbed(),  # type: ignore[arg-type]
        neo4j_driver=object(),  # type: ignore[arg-type]
    )

    assert summary.roles_seen == 2
    assert summary.roles_embedded == 2
    statuses = {row.status for row in captured["written"]}
    assert statuses == {"DRAFT", "PUBLISHED"}
    # Keyed on the CLUSTER, so an edit that mints version+1 overwrites the same node.
    assert {row.cluster_id for row in captured["written"]} == {
        draft.cluster_id,
        published.cluster_id,
    }


async def test_skips_a_role_whose_text_is_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Skip-first on the same NodeKey identity as documents: a re-run costs nothing,
    and an edited role re-embeds automatically because its text_sha256 moves."""
    from src.jd_core.bank.embed_text import serialize_document

    role = _FakeCanonical(cluster_id=uuid.uuid4(), content=_content("Analyst"))
    rules = get_rules().embeddings
    serialized = serialize_document(
        SFUJobDescription.model_validate(role.content), rules
    )
    existing = {
        role.cluster_id: NodeKey(serialized.text_sha256, rules.model, rules.stamp)
    }
    captured = _wire(monkeypatch, current=[role], existing=existing)

    embed = _FakeEmbed()
    summary = await roles_mod.run_role_embedding(
        object(),  # type: ignore[arg-type]
        embed_client=embed,  # type: ignore[arg-type]
        neo4j_driver=object(),  # type: ignore[arg-type]
    )

    assert summary.roles_unchanged == 1
    assert summary.roles_embedded == 0
    assert embed.batches == []  # nothing sent to the model at all
    assert captured["written"] == []


async def test_an_empty_role_is_never_embedded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A role with no content-bearing text must be SKIPPED, not embedded as "" — a
    near-zero vector is a nearest neighbour to everything, which is worse than being
    absent from the index."""
    empty = _FakeCanonical(
        cluster_id=uuid.uuid4(),
        content=SFUJobDescription(title="Shell").model_dump(mode="json"),
    )
    captured = _wire(monkeypatch, current=[empty])

    embed = _FakeEmbed()
    summary = await roles_mod.run_role_embedding(
        object(),  # type: ignore[arg-type]
        embed_client=embed,  # type: ignore[arg-type]
        neo4j_driver=object(),  # type: ignore[arg-type]
    )

    assert summary.roles_empty == 1
    assert summary.roles_embedded == 0
    assert embed.batches == []
    assert captured["written"] == []


async def test_prunes_role_nodes_whose_cluster_is_gone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """MERGE alone would leave a deleted cluster's vector in the index forever, as a
    permanently stale search hit."""
    live = _FakeCanonical(cluster_id=uuid.uuid4(), content=_content("Analyst"))
    ghost = uuid.uuid4()
    existing = {ghost: NodeKey("stale-sha", "m", "s")}
    captured = _wire(monkeypatch, current=[live], existing=existing)

    summary = await roles_mod.run_role_embedding(
        object(),  # type: ignore[arg-type]
        embed_client=_FakeEmbed(),  # type: ignore[arg-type]
        neo4j_driver=object(),  # type: ignore[arg-type]
    )

    assert captured["pruned"] == [ghost]
    assert summary.nodes_pruned == 1


class _FakeEmbedRejectingLong(_FakeEmbed):
    """400s on every batch containing ONE designated text — the real behaviour.

    The API rejects the BATCH, not the offending item, which is exactly why a caller
    that lets the error escape loses every innocent role in the same chunk.
    """

    def __init__(self, reject_index: int) -> None:
        super().__init__()
        self.reject_index = reject_index
        self.doomed: str | None = None

    async def embed_batch(self, texts: Any) -> list[list[float]]:
        batch = list(texts)
        self.batches.append(batch)
        if self.doomed is None and len(batch) > self.reject_index:
            self.doomed = batch[self.reject_index]
        if self.doomed in batch:
            raise EmbeddingBadRequestError(
                "the input length exceeds the context length"
            )
        return [[0.1] * 768 for _ in batch]


@pytest.mark.asyncio
async def test_one_over_long_role_does_not_abort_the_whole_pass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """🔴 MEASURED ON THE LIVE BANK, 2026-08-29. `make embed-roles` died with
    `EmbeddingBadRequestError: the input length exceeds the context length` and stopped
    at **2,152 of 2,500 roles** — every role after the offending one left unembedded and
    invisible to Builder search, with the make target reporting only `Error 1`.

    The DOCUMENT runner has isolated this since Phase 3.2 (`runner.py`: "isolate
    instead — only the genuinely over-long text is skipped"). The role runner, added
    later, never got the same treatment: it let the error escape the batch loop.

    ⚠ It must not merely survive — it must SAY SO. A pass that silently skips a role
    reports success while search stays incomplete, which is the failure this whole
    session has been about.
    """

    def _distinct(word: str) -> dict[str, Any]:
        # ⚠ The TITLE is not part of the serialized embedding text, so three roles
        # differing only by title produce one identical string — which made an earlier
        # version of this test reject all three. Vary the summary instead.
        content = _content(word)
        content["position_summary"] = " ".join([word] * 60)
        return content

    fine_one = _FakeCanonical(cluster_id=uuid.uuid4(), content=_distinct("alpha"))
    poison = _FakeCanonical(cluster_id=uuid.uuid4(), content=_distinct("overlong"))
    fine_two = _FakeCanonical(cluster_id=uuid.uuid4(), content=_distinct("gamma"))
    _wire(monkeypatch, current=[fine_one, poison, fine_two])

    summary = await roles_mod.run_role_embedding(
        object(),  # type: ignore[arg-type]
        embed_client=_FakeEmbedRejectingLong(1),  # type: ignore[arg-type]
        neo4j_driver=object(),  # type: ignore[arg-type]
    )

    assert summary.roles_embedded == 2, "the innocent roles are still embedded"
    assert summary.roles_rejected == 1, "and the over-long one is COUNTED, not hidden"


class _FakeEmbedRejectingOverLength(_FakeEmbed):
    """400s on any batch containing a text longer than ``accepts`` characters.

    Closer to the real endpoint than :class:`_FakeEmbedRejectingLong`, which rejects one
    text by IDENTITY: the server refuses on LENGTH, so a re-cut of the same role is a
    different outcome. That is precisely what the fallback ladder depends on, and an
    identity-based fake can never exercise it.
    """

    def __init__(self, accepts: int) -> None:
        super().__init__()
        self.accepts = accepts

    async def embed_batch(self, texts: Any) -> list[list[float]]:
        batch = list(texts)
        self.batches.append(batch)
        if any(len(text) > self.accepts for text in batch):
            raise EmbeddingBadRequestError(
                "the input length exceeds the context length"
            )
        return [[0.1] * 768 for _ in batch]


def _overlong_content(word: str) -> dict[str, Any]:
    """A role that serializes past ``max_chars`` and stays dense after truncation.

    Many DUTIES rather than one huge summary, because `retruncate_within` cuts on whole
    LINES — a single unbroken line cannot be re-cut at all, and a fixture built that way
    would prove the ladder works when it had in fact never run.
    """
    return SFUJobDescription(
        title=f"{word} lead",
        employee_group="apsa",
        position_summary=" ".join([word] * 60),
        duties=[
            SFUDuty(
                action_verb="Manages",
                statement=f"Manages {word} workstream {index} " + "detail " * 50,
            )
            for index in range(12)  # the model caps duties at 12
        ],
        # The bulk comes from QUALIFICATIONS (cap 40, 400 chars each): enough lines to
        # exceed `max_chars` AND to still have somewhere to cut at each fallback rung.
        qualifications=[
            SFUQualification(text=f"{word} requirement {index} " + "detail " * 50)
            for index in range(40)
        ],
    ).model_dump(mode="json")


@pytest.mark.asyncio
async def test_an_over_long_role_is_rescued_by_the_fallback_ladder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """🔴 P3g's REMAINING half. `ba196b9` made one over-long role stop aborting the pass
    — it is isolated and counted. But counted is not embedded: the role still ends with
    NO vector and stays invisible to Builder search, which is the outcome that mattered.

    The DOCUMENT runner has solved this since HR-193: re-cut the text to each
    `embeddings.max_chars_fallback` rung and embed the first the server takes, counting
    it as backed-off. `roles.py` never got that ladder. This is the same rule for roles.
    """
    victim = _FakeCanonical(cluster_id=uuid.uuid4(), content=_overlong_content("aleph"))
    _wire(monkeypatch, current=[victim])

    # `max_chars` is 10,000 and the first fallback rung is 8,000, so a server that
    # accepts 8,000 refuses the truncated text and accepts the first re-cut.
    summary = await roles_mod.run_role_embedding(
        object(),  # type: ignore[arg-type]
        embed_client=_FakeEmbedRejectingOverLength(8_000),  # type: ignore[arg-type]
        neo4j_driver=object(),  # type: ignore[arg-type]
    )

    assert summary.roles_embedded == 1, "the role gets a vector, not a gap"
    assert summary.roles_backed_off == 1, "and the shorter vector is declared"
    assert summary.roles_rejected == 0


@pytest.mark.asyncio
async def test_the_backed_off_role_keeps_its_full_text_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The vector is of the SHORTER text; the node's skip-first key must still be the
    FULL one, exactly as the document runner memoises under the original sha.

    Otherwise an unchanged corpus re-embeds this role on every run — and worse, the
    stored `text_sha256` would describe text the Bank cannot reproduce from the role.
    """
    victim = _FakeCanonical(cluster_id=uuid.uuid4(), content=_overlong_content("beth"))
    captured = _wire(monkeypatch, current=[victim])

    await roles_mod.run_role_embedding(
        object(),  # type: ignore[arg-type]
        embed_client=_FakeEmbedRejectingOverLength(8_000),  # type: ignore[arg-type]
        neo4j_driver=object(),  # type: ignore[arg-type]
    )

    written = captured["written"][0]
    expected = serialize_document(
        SFUJobDescription.model_validate(victim.content), get_rules().embeddings
    )
    assert written.text_sha256 == expected.text_sha256
    assert written.truncated is True


@pytest.mark.asyncio
async def test_an_empty_fallback_ladder_writes_the_role_off_as_before(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """HR-193's off switch, for roles as for documents: an empty ladder restores the
    pre-HR-193 behaviour EXACTLY — counted in `roles_rejected`, never silently dropped.

    Pinned so the ladder cannot become unconditional: the rungs are a registered, `open`
    decision, and code that ignored an emptied list would take that decision away.
    """
    rules = get_rules()
    no_ladder = rules.model_copy(
        update={
            "embeddings": rules.embeddings.model_copy(update={"max_chars_fallback": ()})
        }
    )
    victim = _FakeCanonical(cluster_id=uuid.uuid4(), content=_overlong_content("gimel"))
    _wire(monkeypatch, current=[victim])

    summary = await roles_mod.run_role_embedding(
        object(),  # type: ignore[arg-type]
        embed_client=_FakeEmbedRejectingOverLength(8_000),  # type: ignore[arg-type]
        neo4j_driver=object(),  # type: ignore[arg-type]
        rules=no_ladder,
    )

    assert summary.roles_embedded == 0
    assert summary.roles_backed_off == 0
    assert summary.roles_rejected == 1

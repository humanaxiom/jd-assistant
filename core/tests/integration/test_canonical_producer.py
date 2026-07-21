"""Integration — the Phase-4.4a canonical PRODUCER against a real Postgres, through the
real migration. What only a real database can prove:

1. DRAFT-only: every persisted ``canonical_jds`` row is ``status=DRAFT`` (NN #1).
2. NO-CLOBBER, pinned by MUTATION: a PUBLISHED canonical (and a DRAFT with a review
   action) is left BYTE-IDENTICAL and counted ``skipped_reviewer_touched``; delete the
   guard and a behavioural assertion goes RED (the human content changed / the count is
   wrong).
3. IDEMPOTENT: two runs -> one cluster row, one canonical v1 (no dup versions), the
   second run reports 0 persisted / 1 refreshed and the same content.
4. LLM best-effort + injected: no client persists the merge draft (rewrite/audit
   recorded skipped); a client that RAISES on rewrite still persists the merge draft and
   counts ``rewrite_failures``; a valid rewrite lands the rewritten content + the
   anti-fab record; a failing audit omits the advisory audit but persists the draft.
5. APPEND-ONLY audit: each persist/refresh/skip writes an ``audit_log`` row; rows only
   accrue (never updated/deleted).
6. Reviewer packet is reconstructable, and the GateDecision is ``approved=False`` while
   the boilerplate gates block (validator-as-oracle — the draft is unapprovable).
7. Cluster spine reused: WJQ (CUPE) members are excluded + counted; JDFN-only.

No Neo4j: the producer recomputes clusters over the PG edge graph (no vectors needed).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterator

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from testcontainers.postgres import PostgresContainer

import src.jd_bank.canonical.runner as canonical_runner
from src.jd_bank.canonical.runner import run_canonical_producer
from src.jd_bank.cluster.models import cluster_id_for
from src.jd_bank.db.models import (
    AuditLog,
    CanonicalJD,
    CanonicalStatus,
    Cluster,
    DedupEdge,
    DedupTier,
    DocumentFormat,
    ParsedJDRow,
    ReviewAction,
    ReviewActionKind,
    SourceDocument,
)
from src.jd_core.bank.merge import merge_cluster
from src.jd_core.models.bank import HarmonizationDiff
from src.jd_core.models.parsed_jd import (
    SFUDuty,
    SFUJobDescription,
    SFUQualification,
)
from src.jd_core.models.quality import (
    GateDecision,
    JDQualityFinding,
    JDQualityFindings,
)
from src.jd_core.parser import PARSER_VERSION
from src.jd_core.rules import Rules, get_rules
from tests.integration.test_dedup_tier1 import ALEMBIC_INI


def _sha(seed: str) -> str:
    return uuid.uuid5(uuid.NAMESPACE_OID, seed).hex * 2  # 64 hex chars


def _analyst(group: str = "apsa", title: str = "Analyst") -> dict[str, object]:
    return SFUJobDescription(
        title=title,
        employee_group=group,
        qualifications=[SFUQualification(text="python sql database", kind="skill")],
    ).model_dump(mode="json")


# The fake rewrite output: grounded prose (python/sql are in the merge draft vocab) PLUS
# one blatantly ungrounded skill the anti-fab guard must scrub + record.
_INJECTED_SKILL = "Certified quantum teleportation licensing"
_REWRITE_SUMMARY = "Supports analytics and reporting with attention to detail."


def _rewrite_jd() -> SFUJobDescription:
    return SFUJobDescription(
        title="Data Analyst",
        position_summary=_REWRITE_SUMMARY,
        duties=[
            SFUDuty(
                action_verb="Analyzes",
                statement="Analyzes datasets and prepares reports for departments",
            )
        ],
        qualifications=[
            SFUQualification(text="python sql database", kind="skill"),
            SFUQualification(text=_INJECTED_SKILL, kind="skill"),
        ],
    )


class _FakeChat:
    """Content-keyed fake, dispatched on the requested SCHEMA (never call index — the
    documented fake-hygiene landmine): a rewrite asks for ``SFUJobDescription``, the
    audit asks for ``JDQualityFindings``. ``raise_on`` isolates a pass (best-effort)."""

    def __init__(
        self,
        *,
        rewrite_jd: SFUJobDescription | None = None,
        findings: JDQualityFindings | None = None,
        raise_on: str | None = None,
    ) -> None:
        self._rewrite_jd = rewrite_jd or _rewrite_jd()
        self._findings = findings or JDQualityFindings(issues=[])
        self._raise_on = raise_on
        #: Every schema this client was asked to complete — so a test can prove the
        #: producer routed the rewrite and the audit to their OWN injected clients and
        #: never crossed them (the point of the two-client split, NN #6).
        self.seen: list[type[object]] = []

    async def chat_json(
        self,
        messages: object,
        model_cls: type[object],
        *,
        max_tokens: int,
        max_retries: int,
    ) -> object:
        self.seen.append(model_cls)
        if model_cls is SFUJobDescription:
            if self._raise_on == "rewrite":
                raise RuntimeError("simulated rewrite failure")
            return self._rewrite_jd.model_copy(deep=True)
        if model_cls is JDQualityFindings:
            if self._raise_on == "audit":
                raise RuntimeError("simulated audit failure")
            return self._findings.model_copy(deep=True)
        raise AssertionError(f"unexpected model_cls {model_cls!r}")


@pytest.fixture(scope="module")
def rules() -> Rules:
    return get_rules()


def _no_group_veto(rules: Rules) -> Rules:
    """Employee-group veto OFF, so an APSA+CUPE pair can share a cluster — the only way
    to construct a MIXED JDFN/WJQ cluster (the veto blocks it in prod)."""
    return rules.model_copy(
        update={
            "comparison": rules.comparison.model_copy(
                update={"group_conflict_veto": False}
            )
        }
    )


@pytest.fixture(scope="module")
def migrated_pg_url() -> Iterator[str]:
    with PostgresContainer("postgres:16-alpine") as pg:
        url = pg.get_connection_url().replace("psycopg2", "asyncpg")
        cfg = Config(str(ALEMBIC_INI))
        cfg.set_main_option("sqlalchemy.url", url)
        command.upgrade(cfg, "head")
        yield url


@pytest.fixture
async def session_maker(
    migrated_pg_url: str,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(migrated_pg_url)
    async with engine.begin() as conn:
        # A clean slate per test — cascade wipes clusters/canonical/audit too.
        await conn.execute(text("DELETE FROM source_documents"))
        await conn.execute(text("DELETE FROM clusters"))
        await conn.execute(text("DELETE FROM audit_log"))
    maker = async_sessionmaker(engine, expire_on_commit=False)
    yield maker
    await engine.dispose()


async def _seed_jd(
    session: AsyncSession,
    *,
    storage_ref: str,
    sha256: str,
    parsed: dict[str, object],
) -> SourceDocument:
    doc = SourceDocument(
        storage_ref=storage_ref,
        filename=storage_ref.rsplit("/", 1)[-1],
        sha256=sha256,
        fmt=DocumentFormat.DOCX,
        byte_size=1024,
    )
    session.add(doc)
    await session.flush()
    session.add(
        ParsedJDRow(
            source_document_id=doc.id,
            parsed=parsed,
            parser_version=PARSER_VERSION,
            parse_confidence=1.0,
        )
    )
    return doc


async def _role_edge(session: AsyncSession, a: uuid.UUID, b: uuid.UUID) -> None:
    lo, hi = sorted((a, b), key=str)
    session.add(
        DedupEdge(
            source_a_id=lo,
            source_b_id=hi,
            tier=DedupTier.ROLE_EQUIVALENT,
            score=0.9,
            method="vec+skill@test",
        )
    )


async def _seed_pair(
    session: AsyncSession, *, group_b: str = "apsa"
) -> tuple[SourceDocument, SourceDocument]:
    """Two role-equivalent analysts (a JDFN cluster of two) sharing one ROLE edge."""
    a = await _seed_jd(session, storage_ref="a", sha256=_sha("a"), parsed=_analyst())
    b = await _seed_jd(
        session, storage_ref="b", sha256=_sha("b"), parsed=_analyst(group=group_b)
    )
    await _role_edge(session, a.id, b.id)
    return a, b


async def _seed_n_clusters(session: AsyncSession, n: int) -> None:
    """Seed ``n`` INDEPENDENT two-analyst JDFN clusters (``n`` role edges, no shared
    members) — the multi-cluster corpus the incremental-commit cadence needs."""
    for i in range(n):
        ra, rb = f"c{i}a", f"c{i}b"
        a = await _seed_jd(session, storage_ref=ra, sha256=_sha(ra), parsed=_analyst())
        b = await _seed_jd(session, storage_ref=rb, sha256=_sha(rb), parsed=_analyst())
        await _role_edge(session, a.id, b.id)


# --- acceptance #1 + #6: DRAFT-only, honest un-approvable draft ----------------------


@pytest.mark.asyncio
async def test_the_producer_persists_a_draft_a_human_still_has_to_approve(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    async with session_maker() as session:
        await _seed_pair(session)
        await session.commit()

        result = await run_canonical_producer(session, rewrite_client=None)
        await session.commit()

        assert result.drafts_persisted == 1
        assert result.clusters_seen == 1

        canonical = await session.scalar(select(CanonicalJD))
        assert canonical is not None
        # NN #1: the ONLY status the producer writes.
        assert canonical.status is CanonicalStatus.DRAFT
        assert canonical.validation_report_id is None
        assert len(canonical.source_document_ids) == 2

        # Reconstructable reviewer packet (acceptance #6) — and the draft is honestly
        # un-approvable: the boilerplate gates block, so approved=False.
        HarmonizationDiff.model_validate(canonical.change_log["harmonization_diff"])
        decision = GateDecision.model_validate(
            canonical.change_log["validator"]["gate_decision"]
        )
        assert decision.approved is False
        assert decision.blocking  # named gates say why the button is disabled


# --- acceptance #2: NO-CLOBBER, pinned by MUTATION -----------------------------------


async def _seed_cluster_and_canonical(
    session: AsyncSession,
    *,
    status: CanonicalStatus,
    content: dict[str, object],
    with_review_action: bool = False,
) -> tuple[uuid.UUID, uuid.UUID]:
    """Seed the two-analyst cluster's rows PLUS a pre-existing canonical at ``status``
    (optionally with a review action), keyed on the SAME content-derived cluster_id the
    producer will compute. Returns ``(cluster_id, canonical_id)``."""
    await _seed_pair(session)
    cluster_id = cluster_id_for(["a", "b"])
    session.add(Cluster(id=cluster_id, label="seeded", members=[]))
    await session.flush()
    canonical = CanonicalJD(
        cluster_id=cluster_id,
        version=1,
        status=status,
        content=content,
        source_document_ids=[],
        change_log={"seeded": True},
    )
    session.add(canonical)
    await session.flush()
    if with_review_action:
        session.add(
            ReviewAction(
                canonical_jd_id=canonical.id,
                action=ReviewActionKind.APPROVE,
                reviewer_id="hr-reviewer",
                reason="looks good",
            )
        )
    await session.commit()
    return cluster_id, canonical.id


@pytest.mark.asyncio
async def test_a_published_canonical_is_left_byte_identical_and_counted(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    """Highest-risk pin. A PUBLISHED canonical is a human artifact: the producer leaves
    it BYTE-IDENTICAL and counts ``skipped_reviewer_touched``. MUTATION: delete the
    no-clobber guard (let it overwrite) and these go RED — the published content moves,
    the status flips to draft, and the count is wrong."""
    human_content = {"title": "HUMAN APPROVED CANONICAL — DO NOT TOUCH"}
    async with session_maker() as session:
        cluster_id, canonical_id = await _seed_cluster_and_canonical(
            session, status=CanonicalStatus.PUBLISHED, content=human_content
        )

    async with session_maker() as session:
        result = await run_canonical_producer(session, rewrite_client=None)
        await session.commit()

        assert result.skipped_reviewer_touched == 1
        assert result.drafts_persisted == 0
        assert result.drafts_refreshed == 0

    async with session_maker() as session:
        row = await session.get(CanonicalJD, canonical_id)
        assert row is not None
        assert row.status is CanonicalStatus.PUBLISHED  # never demoted
        assert row.content == human_content  # never overwritten
        assert row.change_log == {"seeded": True}
        # Exactly one canonical for the cluster — no shadow draft alongside it.
        assert (
            await session.scalar(
                select(func.count())
                .select_from(CanonicalJD)
                .where(CanonicalJD.cluster_id == cluster_id)
            )
            == 1
        )


@pytest.mark.asyncio
async def test_a_draft_a_reviewer_acted_on_is_left_untouched_and_counted(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    """The OTHER half of the guard: a DRAFT with any ``review_actions`` row is a human
    artifact too. MUTATION: drop the review-action check (keep only the status check) so
    the producer refreshes it — the human content moves and the skip count is wrong."""
    human_content = {"title": "REVIEWER-EDITED DRAFT — DO NOT TOUCH"}
    async with session_maker() as session:
        _cluster_id, canonical_id = await _seed_cluster_and_canonical(
            session,
            status=CanonicalStatus.DRAFT,
            content=human_content,
            with_review_action=True,
        )

    async with session_maker() as session:
        result = await run_canonical_producer(session, rewrite_client=None)
        await session.commit()
        assert result.skipped_reviewer_touched == 1
        assert result.drafts_refreshed == 0
        assert result.drafts_persisted == 0

    async with session_maker() as session:
        row = await session.get(CanonicalJD, canonical_id)
        assert row is not None
        assert row.content == human_content  # never overwritten
        assert row.change_log == {"seeded": True}


# --- acceptance #3: IDEMPOTENT --------------------------------------------------------


@pytest.mark.asyncio
async def test_running_twice_yields_the_same_rows(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    async with session_maker() as session:
        await _seed_pair(session)
        await session.commit()

        first = await run_canonical_producer(session, rewrite_client=None)
        await session.commit()
        assert first.drafts_persisted == 1
        assert first.drafts_refreshed == 0

    async with session_maker() as session:
        canonical = await session.scalar(select(CanonicalJD))
        assert canonical is not None
        first_content = canonical.content

        second = await run_canonical_producer(session, rewrite_client=None)
        await session.commit()
        # No new cluster, no new canonical version — an untouched DRAFT is refreshed.
        assert second.drafts_persisted == 0
        assert second.drafts_refreshed == 1

    async with session_maker() as session:
        assert await session.scalar(select(func.count()).select_from(Cluster)) == 1
        assert await session.scalar(select(func.count()).select_from(CanonicalJD)) == 1
        row = await session.scalar(select(CanonicalJD))
        assert row is not None
        assert row.version == 1
        assert row.content == first_content  # deterministic -> byte-identical


# --- acceptance #4: LLM best-effort + injected ---------------------------------------


@pytest.mark.asyncio
async def test_client_none_persists_the_deterministic_merge_draft(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    async with session_maker() as session:
        await _seed_pair(session)
        await session.commit()

        result = await run_canonical_producer(session, rewrite_client=None)
        await session.commit()
        assert result.llm_enabled is False
        assert result.rewrite_failures == 0
        assert result.audit_failures == 0

        canonical = await session.scalar(select(CanonicalJD))
        assert canonical is not None
        expected = merge_cluster(
            [
                SFUJobDescription.model_validate(_analyst()),
                SFUJobDescription.model_validate(_analyst()),
            ]
        ).draft.model_dump(mode="json")
        assert canonical.content == expected
        assert canonical.change_log["pipeline"]["rewrite_ran"] is False
        assert canonical.change_log["pipeline"]["audit_ran"] is False
        assert canonical.change_log["anti_fabrication"] is None
        assert canonical.change_log["quality_audit"] is None


@pytest.mark.asyncio
async def test_a_valid_rewrite_lands_the_rewritten_content_and_anti_fab_record(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    findings = JDQualityFindings(
        issues=[
            JDQualityFinding(
                category="clarity",
                severity="medium",
                message="A nuance the regex validator cannot judge.",
                evidence="attention to detail",  # verbatim substring of the rewrite
            )
        ]
    )
    async with session_maker() as session:
        await _seed_pair(session)
        await session.commit()

        client = _FakeChat(findings=findings)
        result = await run_canonical_producer(
            session, rewrite_client=client, audit_client=client
        )
        await session.commit()

        assert result.llm_enabled is True
        assert result.rewrite_failures == 0
        assert result.audit_failures == 0

        canonical = await session.scalar(select(CanonicalJD))
        assert canonical is not None
        # The rewritten prose won (title from the fake), not the deterministic draft.
        assert canonical.content["title"] == "Data Analyst"
        # The ungrounded skill was scrubbed AND recorded in the packet.
        packet = canonical.change_log
        assert packet["pipeline"]["rewrite_ran"] is True
        assert _INJECTED_SKILL in packet["anti_fabrication"]["scrubbed_skills"]
        assert _INJECTED_SKILL not in [
            q["text"] for q in canonical.content["qualifications"]
        ]
        # The advisory audit ran and its grounded finding survived.
        assert packet["pipeline"]["audit_ran"] is True
        assert len(packet["quality_audit"]["issues"]) == 1


@pytest.mark.asyncio
async def test_a_rewrite_failure_falls_back_to_the_merge_draft_and_is_counted(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    async with session_maker() as session:
        await _seed_pair(session)
        await session.commit()

        client = _FakeChat(raise_on="rewrite")
        result = await run_canonical_producer(
            session, rewrite_client=client, audit_client=client
        )
        await session.commit()

        # The run did NOT abort — the draft was still persisted.
        assert result.drafts_persisted == 1
        assert result.rewrite_failures == 1

        canonical = await session.scalar(select(CanonicalJD))
        assert canonical is not None
        expected = merge_cluster(
            [
                SFUJobDescription.model_validate(_analyst()),
                SFUJobDescription.model_validate(_analyst()),
            ]
        ).draft.model_dump(mode="json")
        assert canonical.content == expected  # fell back to the deterministic draft
        assert canonical.change_log["pipeline"]["rewrite_failed"] is True
        assert canonical.change_log["pipeline"]["rewrite_ran"] is False


@pytest.mark.asyncio
async def test_an_audit_failure_omits_the_advisory_audit_but_persists_the_draft(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    async with session_maker() as session:
        await _seed_pair(session)
        await session.commit()

        client = _FakeChat(raise_on="audit")
        result = await run_canonical_producer(
            session, rewrite_client=client, audit_client=client
        )
        await session.commit()

        assert result.drafts_persisted == 1
        assert result.audit_failures == 1

        canonical = await session.scalar(select(CanonicalJD))
        assert canonical is not None
        # The rewrite still landed (the audit is advisory and independent).
        assert canonical.content["title"] == "Data Analyst"
        assert canonical.change_log["pipeline"]["audit_failed"] is True
        assert canonical.change_log["pipeline"]["audit_ran"] is False
        assert canonical.change_log["quality_audit"] is None


@pytest.mark.asyncio
async def test_rewrite_and_audit_are_routed_to_their_own_injected_clients(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    """The two-client split (NN #6): the producer sends the 4.2a rewrite ONLY to
    ``rewrite_client`` and the 4.2b audit ONLY to ``audit_client``. A regression that
    re-merged them (one client bound to the rewrite model passed to both) would either
    leave the audit client unused OR route the audit through the rewrite client, and the
    ``QualityAudit.model`` stamp — always ``rules.quality.model`` — would silently lie.
    Distinct fakes make the crossing observable: each must see ONLY its own schema.
    """
    findings = JDQualityFindings(
        issues=[
            JDQualityFinding(
                category="clarity",
                severity="medium",
                message="A nuance the regex validator cannot judge.",
                evidence="attention to detail",  # verbatim substring of the rewrite
            )
        ]
    )
    async with session_maker() as session:
        await _seed_pair(session)
        await session.commit()

        rewrite_client = _FakeChat()
        audit_client = _FakeChat(findings=findings)
        result = await run_canonical_producer(
            session, rewrite_client=rewrite_client, audit_client=audit_client
        )
        await session.commit()

        assert result.rewrite_failures == 0
        assert result.audit_failures == 0
        # The rewrite client saw ONLY the rewrite schema; the audit client ONLY the
        # audit schema. Neither saw the other's — the passes never share a client.
        assert rewrite_client.seen == [SFUJobDescription]
        assert audit_client.seen == [JDQualityFindings]


# --- acceptance #5: APPEND-ONLY audit ------------------------------------------------


@pytest.mark.asyncio
async def test_each_persist_and_refresh_writes_an_append_only_audit_row(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    async with session_maker() as session:
        await _seed_pair(session)
        await session.commit()

        await run_canonical_producer(session, rewrite_client=None)
        await session.commit()

    async with session_maker() as session:
        rows = (
            await session.scalars(select(AuditLog).order_by(AuditLog.created_at))
        ).all()
        assert len(rows) == 1
        assert rows[0].event_type == "canonical_draft.persisted"
        assert rows[0].actor == "producer"
        # Counts/flags only — NEVER JD text / incumbent PII.
        assert "cluster_id" in rows[0].payload
        assert "title" not in rows[0].payload

        await run_canonical_producer(session, rewrite_client=None)
        await session.commit()

    async with session_maker() as session:
        # Append-only: the persist row survives and a refresh row is ADDED (never an
        # update/delete of the first).
        rows = (
            await session.scalars(select(AuditLog).order_by(AuditLog.created_at))
        ).all()
        assert len(rows) == 2
        assert [r.event_type for r in rows] == [
            "canonical_draft.persisted",
            "canonical_draft.refreshed",
        ]


@pytest.mark.asyncio
async def test_a_skip_writes_an_append_only_audit_row(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    async with session_maker() as session:
        await _seed_cluster_and_canonical(
            session,
            status=CanonicalStatus.PUBLISHED,
            content={"title": "human"},
        )

    async with session_maker() as session:
        await run_canonical_producer(session, rewrite_client=None)
        await session.commit()

    async with session_maker() as session:
        rows = (await session.scalars(select(AuditLog))).all()
        assert len(rows) == 1
        assert rows[0].event_type == "canonical_draft.skipped_reviewer_touched"
        assert rows[0].payload["reason"] == "reviewer_touched"


# --- acceptance #7: cluster spine reused — WJQ excluded + counted --------------------


@pytest.mark.asyncio
async def test_wjq_members_are_excluded_and_counted(
    session_maker: async_sessionmaker[AsyncSession], rules: Rules
) -> None:
    async with session_maker() as session:
        a = await _seed_jd(
            session, storage_ref="a", sha256=_sha("a"), parsed=_analyst()
        )
        b = await _seed_jd(
            session, storage_ref="b", sha256=_sha("b"), parsed=_analyst()
        )
        # A CUPE (WJQ-proxy) member welded in only because the group veto is off.
        w = await _seed_jd(
            session, storage_ref="w", sha256=_sha("w"), parsed=_analyst(group="cupe")
        )
        await _role_edge(session, a.id, b.id)
        await _role_edge(session, b.id, w.id)
        await session.commit()

        result = await run_canonical_producer(
            session, rewrite_client=None, rules=_no_group_veto(rules)
        )
        await session.commit()

        assert result.wjq_members_excluded == 1
        assert result.clusters_mixed_jdfn_wjq == 1
        assert result.drafts_persisted == 1

        canonical = await session.scalar(select(CanonicalJD))
        assert canonical is not None
        # Only the two JDFN members fed the canonical — the WJQ member is not a source.
        assert len(canonical.source_document_ids) == 2


@pytest.mark.asyncio
async def test_a_fully_wjq_cluster_is_excluded_and_persists_nothing(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    """An all-CUPE cluster has no JDFN member — it is excluded WHOLE and counted, and no
    canonical is written (the producer is JDFN-only)."""
    async with session_maker() as session:
        a = await _seed_jd(
            session, storage_ref="a", sha256=_sha("a"), parsed=_analyst(group="cupe")
        )
        b = await _seed_jd(
            session, storage_ref="b", sha256=_sha("b"), parsed=_analyst(group="cupe")
        )
        await _role_edge(session, a.id, b.id)
        await session.commit()

        result = await run_canonical_producer(session, rewrite_client=None)
        await session.commit()

        assert result.clusters_fully_wjq_excluded == 1
        assert result.clusters_seen == 0
        assert result.drafts_persisted == 0
        assert result.wjq_members_excluded == 2
        assert await session.scalar(select(func.count()).select_from(CanonicalJD)) == 0


@pytest.mark.asyncio
async def test_a_single_jdfn_member_cluster_is_counted_single(
    session_maker: async_sessionmaker[AsyncSession], rules: Rules
) -> None:
    """A cluster with exactly one JDFN member (the rest WJQ) is a single-member merge —
    counted ``single_member_clusters`` and still persisted as a DRAFT."""
    async with session_maker() as session:
        a = await _seed_jd(
            session, storage_ref="a", sha256=_sha("a"), parsed=_analyst()
        )
        w = await _seed_jd(
            session, storage_ref="w", sha256=_sha("w"), parsed=_analyst(group="cupe")
        )
        await _role_edge(session, a.id, w.id)
        await session.commit()

        result = await run_canonical_producer(
            session, rewrite_client=None, rules=_no_group_veto(rules)
        )
        await session.commit()

        assert result.single_member_clusters == 1
        assert result.multi_member_clusters == 0
        assert result.wjq_members_excluded == 1
        assert result.drafts_persisted == 1


# --- per-cluster SAVEPOINT isolation, pinned by MUTATION -----------------------------


@pytest.mark.asyncio
async def test_a_mid_persist_failure_isolates_one_cluster_and_the_rest_persist(
    session_maker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A per-cluster fault mid-persist isolates THAT cluster (no orphan ``Cluster``, no
    partial ``CanonicalJD``, no ``audit_log`` row) while a healthy cluster persists and
    the run completes — the ``begin_nested`` SAVEPOINT's whole point.

    The fault is a monkeypatched ``AuditLog`` that raises when built for cluster A's
    payload — i.e. AFTER A's ``Cluster`` + ``CanonicalJD`` were flushed inside the
    SAVEPOINT, the strongest half-write case (without it an orphan ``Cluster`` row
    would survive the commit).

    MUTATION: swap ``begin_nested()`` for a plain block (or a naked ``rollback()``) and
    A's half-written rows survive — ``clusters``/``canon`` become two rows (RED)."""
    poisoned = cluster_id_for(["a", "b"])  # cluster A — forced to raise mid-persist
    healthy = cluster_id_for(["c", "d"])  # cluster B — must persist fully

    real_audit = canonical_runner.AuditLog

    def _poison_audit(**kwargs: object) -> object:
        if str(poisoned) in str(kwargs.get("payload", "")):
            raise RuntimeError("simulated mid-persist failure for cluster A")
        return real_audit(**kwargs)

    monkeypatch.setattr(canonical_runner, "AuditLog", _poison_audit)

    async with session_maker() as session:
        a = await _seed_jd(
            session, storage_ref="a", sha256=_sha("a"), parsed=_analyst()
        )
        b = await _seed_jd(
            session, storage_ref="b", sha256=_sha("b"), parsed=_analyst()
        )
        c = await _seed_jd(
            session, storage_ref="c", sha256=_sha("c"), parsed=_analyst()
        )
        d = await _seed_jd(
            session, storage_ref="d", sha256=_sha("d"), parsed=_analyst()
        )
        await _role_edge(session, a.id, b.id)
        await _role_edge(session, c.id, d.id)
        await session.commit()

        result = await run_canonical_producer(session, rewrite_client=None)
        await session.commit()

    # (d) the run completed; (c) exactly one cluster failed, the other persisted.
    assert result.clusters_seen == 2
    assert result.cluster_failures == 1
    assert result.drafts_persisted == 1

    async with session_maker() as session:
        clusters = (await session.scalars(select(Cluster.id))).all()
        canon = (await session.scalars(select(CanonicalJD.cluster_id))).all()
        audit = (await session.scalars(select(AuditLog))).all()

    # (a) the healthy cluster persisted fully; (b) the poisoned cluster wrote NOTHING —
    # no orphan Cluster, no partial CanonicalJD, no audit row.
    assert list(clusters) == [healthy]
    assert list(canon) == [healthy]
    assert len(audit) == 1
    assert audit[0].event_type == "canonical_draft.persisted"
    assert str(healthy) in str(audit[0].payload)
    assert str(poisoned) not in str(audit[0].payload)


# --- incremental commit + progress logging (crash-safe, observable long runs) --------


@pytest.mark.asyncio
async def test_commit_every_checkpoints_between_clusters(
    session_maker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``commit_every=N`` commits the session once per N processed clusters. With 3
    clusters and N=2 the runner fires EXACTLY one in-run commit (after cluster #2); the
    remainder is the caller's backstop. A spy on ``session.commit`` counts the
    cadence."""
    async with session_maker() as session:
        await _seed_n_clusters(session, 3)
        await session.commit()

        real_commit = session.commit
        commit_calls = 0

        async def _counting_commit(*args: object, **kwargs: object) -> None:
            nonlocal commit_calls
            commit_calls += 1
            await real_commit(*args, **kwargs)

        monkeypatch.setattr(session, "commit", _counting_commit)

        result = await run_canonical_producer(
            session, rewrite_client=None, commit_every=2
        )
        # 3 processed, checkpoint at #2 only -> ONE runner-initiated commit.
        assert commit_calls == 1
        assert result.clusters_seen == 3
        assert result.drafts_persisted == 3

        await real_commit()  # caller backstop for the remaining cluster #3

    async with session_maker() as session:
        assert await session.scalar(select(func.count()).select_from(CanonicalJD)) == 3


@pytest.mark.asyncio
async def test_committed_clusters_survive_a_crash_mid_run(
    session_maker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """THE crash-safety property. With ``commit_every=1`` each cluster is committed at a
    checkpoint. If the run dies AFTER a checkpoint (the 3rd commit raises — a simulated
    process death), the work durably committed before it survives: a FRESH session/
    transaction sees exactly the 2 clusters that checkpointed, and the partially
    processed 3rd (its SAVEPOINT released but its checkpoint never committed) rolled
    back, never a half-written row. Without incremental commit ALL work is lost."""
    async with session_maker() as session:
        await _seed_n_clusters(session, 3)
        await session.commit()

    async with session_maker() as session:
        real_commit = session.commit
        commit_calls = 0

        async def _crashing_commit(*args: object, **kwargs: object) -> None:
            nonlocal commit_calls
            commit_calls += 1
            if commit_calls >= 3:  # the 3rd checkpoint "crashes" before committing
                raise RuntimeError("simulated crash at checkpoint 3")
            await real_commit(*args, **kwargs)

        monkeypatch.setattr(session, "commit", _crashing_commit)

        with pytest.raises(RuntimeError, match="simulated crash"):
            await run_canonical_producer(session, rewrite_client=None, commit_every=1)

    # Fresh transaction: the two checkpointed clusters are DURABLE; the 3rd rolled back.
    async with session_maker() as session:
        assert await session.scalar(select(func.count()).select_from(CanonicalJD)) == 2
        assert await session.scalar(select(func.count()).select_from(Cluster)) == 2


@pytest.mark.asyncio
async def test_progress_is_logged_to_stderr_at_the_cadence(
    session_maker: async_sessionmaker[AsyncSession],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A multi-hour run must be watchable via container logs: with ``progress_every=2``
    the runner prints a progress line to STDERR at the cadence (processed/total +
    persisted/refreshed/skipped/failures + elapsed). 3 clusters -> one line at #2."""
    async with session_maker() as session:
        await _seed_n_clusters(session, 3)
        await session.commit()
        await run_canonical_producer(
            session, rewrite_client=None, commit_every=2, progress_every=2
        )
        await session.commit()

    err = capsys.readouterr().err
    assert "canonical-producer" in err  # the progress marker
    assert "2/3" in err  # processed / total clusters
    assert "persisted=" in err
    assert "elapsed=" in err


@pytest.mark.asyncio
async def test_default_path_does_not_commit_or_log_progress(
    session_maker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The DEFAULT (``commit_every=None``, ``progress_every=None``) is byte-identical to
    today: the runner NEVER commits (the caller owns the single final commit) and emits
    NO progress output. Pins that existing callers/tests are untouched."""
    async with session_maker() as session:
        await _seed_n_clusters(session, 2)
        await session.commit()

        real_commit = session.commit
        commit_calls = 0

        async def _counting_commit(*args: object, **kwargs: object) -> None:
            nonlocal commit_calls
            commit_calls += 1
            await real_commit(*args, **kwargs)

        monkeypatch.setattr(session, "commit", _counting_commit)

        result = await run_canonical_producer(session, rewrite_client=None)
        assert commit_calls == 0  # the runner did not commit — caller owns it
        assert result.drafts_persisted == 2

        await real_commit()

    err = capsys.readouterr().err
    assert "canonical-producer" not in err  # no progress output on the default path


@pytest.mark.asyncio
async def test_idempotent_rerun_with_commit_every_yields_the_same_rows(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    """IDEMPOTENT still holds with checkpointing on: a first run persists 3 DRAFTs; an
    idempotent re-run (also checkpointed) persists 0 and refreshes the same 3 in place —
    no dup clusters, no dup versions."""
    async with session_maker() as session:
        await _seed_n_clusters(session, 3)
        await session.commit()
        first = await run_canonical_producer(
            session, rewrite_client=None, commit_every=1
        )
        await session.commit()
        assert first.drafts_persisted == 3
        assert first.drafts_refreshed == 0

    async with session_maker() as session:
        second = await run_canonical_producer(
            session, rewrite_client=None, commit_every=1
        )
        await session.commit()
        assert second.drafts_persisted == 0
        assert second.drafts_refreshed == 3

    async with session_maker() as session:
        assert await session.scalar(select(func.count()).select_from(Cluster)) == 3
        assert await session.scalar(select(func.count()).select_from(CanonicalJD)) == 3


@pytest.mark.asyncio
async def test_reviewer_touched_still_skipped_and_only_draft_written_with_commit_every(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    """NO-CLOBBER + DRAFT-only hold with checkpointing on: a PUBLISHED canonical is left
    byte-identical and counted skipped, while the other clusters persist as DRAFT."""
    human_content = {"title": "HUMAN APPROVED — DO NOT TOUCH"}
    async with session_maker() as session:
        # The published/no-clobber cluster is the two-analyst ("a","b") cluster.
        _cluster_id, canonical_id = await _seed_cluster_and_canonical(
            session, status=CanonicalStatus.PUBLISHED, content=human_content
        )
        # Plus two fresh JDFN clusters that MUST persist as DRAFT.
        await _seed_n_clusters(session, 2)
        await session.commit()

    async with session_maker() as session:
        result = await run_canonical_producer(
            session, rewrite_client=None, commit_every=1
        )
        await session.commit()
        assert result.skipped_reviewer_touched == 1
        assert result.drafts_persisted == 2

    async with session_maker() as session:
        row = await session.get(CanonicalJD, canonical_id)
        assert row is not None
        assert row.status is CanonicalStatus.PUBLISHED  # never demoted
        assert row.content == human_content  # never overwritten
        # Every producer-written canonical is a DRAFT (NN #1).
        drafts = (
            await session.scalars(
                select(CanonicalJD).where(CanonicalJD.status == CanonicalStatus.DRAFT)
            )
        ).all()
        assert len(drafts) == 2
        assert all(d.status is CanonicalStatus.DRAFT for d in drafts)

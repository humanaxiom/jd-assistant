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
from src.jd_core.rules import Harmonization, Rules, get_rules
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
        constrain_to_schema: bool = False,
    ) -> object:
        self.seen.append(model_cls)
        if model_cls is SFUJobDescription:
            # the rewrite must NOT constrain — its large schema 500s Ollama's builder
            assert constrain_to_schema is False
            if self._raise_on == "rewrite":
                raise RuntimeError("simulated rewrite failure")
            return self._rewrite_jd.model_copy(deep=True)
        if model_cls is JDQualityFindings:
            # the audit constrains on its small schema (the ~24% enum fix)
            assert constrain_to_schema is True
            if self._raise_on == "audit":
                raise RuntimeError("simulated audit failure")
            return self._findings.model_copy(deep=True)
        raise AssertionError(f"unexpected model_cls {model_cls!r}")


@pytest.fixture(scope="module")
def rules() -> Rules:
    return get_rules()


def _jdfn_only(rules: Rules) -> Rules:
    """The pre-Phase-D scope: the Bank drafts the JDFN form only (HR-206). Rebuilt
    through ``Harmonization`` rather than ``model_copy(update=…)`` so the fixture cannot
    hand the producer a config the loader would refuse."""
    harmonization = Harmonization(
        **{**rules.harmonization.model_dump(), "templates_harmonized": ("jdfn",)}
    )
    return rules.model_copy(update={"harmonization": harmonization})


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


# --- the no-DOWNGRADE rule, over a real refresh cycle --------------------------------


@pytest.mark.asyncio
async def test_a_deterministic_run_will_not_overwrite_a_draft_the_llm_wrote(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    """🔴 WHAT ACTUALLY HAPPENED TO THE LIVE BANK on 2026-08-17, as a test.

    A full run writes a draft; a later `--no-llm` run must LEAVE IT ALONE rather than
    replace the rewrite with a deterministic merge. On the live Bank this cost 1,763
    JDFN drafts and 20 points of cohort mean in thirty-two seconds, reported as
    ``drafts_refreshed``.

    The second half is the half that matters: with ``allow_downgrade=True`` the same run
    DOES overwrite it. The guard is a default, not a prohibition — deliberately
    re-baselining the Bank on deterministic drafts is a legitimate thing to want, and it
    should cost a flag rather than be impossible.
    """
    async with session_maker() as session:
        await _seed_pair(session)
        await session.commit()

        await run_canonical_producer(
            session, rewrite_client=_FakeChat(), audit_client=_FakeChat()
        )
        await session.commit()

        written = await session.scalar(select(CanonicalJD))
        assert written is not None
        assert written.change_log["pipeline"]["llm_enabled"] is True

        # A cheap run over the expensive draft: skipped, counted, and left byte-alike.
        guarded = await run_canonical_producer(session, rewrite_client=None)
        await session.commit()

        assert guarded.skipped_would_downgrade == 1
        assert guarded.drafts_refreshed == 0
        after = await session.get(CanonicalJD, written.id)
        assert after is not None
        assert after.change_log["pipeline"]["llm_enabled"] is True

        # The audit trail says why, so a skipped row is never a silent one (NN #6).
        skips = (
            await session.scalars(
                select(AuditLog).where(
                    AuditLog.event_type == "canonical_draft.skipped_would_downgrade"
                )
            )
        ).all()
        assert len(skips) == 1
        assert skips[0].payload["reason"] == (
            "would_downgrade_llm_draft_to_deterministic"
        )

        # ...and the escape hatch works, because a default that cannot be overridden is
        # not a default, it is a wall.
        forced = await run_canonical_producer(
            session, rewrite_client=None, allow_downgrade=True
        )
        await session.commit()

        assert forced.skipped_would_downgrade == 0
        assert forced.drafts_refreshed == 1
        downgraded = await session.get(CanonicalJD, written.id)
        assert downgraded is not None
        assert downgraded.change_log["pipeline"]["llm_enabled"] is False


@pytest.mark.asyncio
async def test_resume_skips_the_clusters_an_llm_pass_already_finished(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    """A full LLM pass over this archive measures ~44 HOURS — 2,456 clusters at 64.8s,
    two model calls each. Without a resume it is also ALL-OR-NOTHING: an interruption
    anywhere means paying for every cluster again, including the ones already rewritten.

    ``make embed`` has had exactly this property since Phase 3.2, and the reindex
    runbook cites it as the reason an interrupted reindex needs no resume flag. The
    producer's far more expensive pass deserves the same.

    Pinned by the model call COUNT, not by the row: the point of a resume is that the
    work is not done twice, and a test asserting only the row contents would pass on a
    run that redid every completion and wrote the same answer.
    """
    async with session_maker() as session:
        await _seed_pair(session)
        await session.commit()

        first = _FakeChat()
        await run_canonical_producer(
            session, rewrite_client=first, audit_client=_FakeChat()
        )
        await session.commit()
        assert first.seen == [SFUJobDescription]  # one rewrite was paid for

        second = _FakeChat()
        resumed = await run_canonical_producer(
            session,
            rewrite_client=second,
            audit_client=_FakeChat(),
            skip_llm_written=True,
        )
        await session.commit()

        assert resumed.skipped_already_llm_written == 1
        assert resumed.drafts_refreshed == 0
        assert second.seen == []  # ...and NOT paid for a second time

        # Without the flag the same run does the work again — so the skip is the flag's
        # doing, not an unrelated idempotency the producer already had.
        third = _FakeChat()
        redone = await run_canonical_producer(
            session, rewrite_client=third, audit_client=_FakeChat()
        )
        await session.commit()

        assert redone.skipped_already_llm_written == 0
        assert redone.drafts_refreshed == 1
        assert third.seen == [SFUJobDescription]


@pytest.mark.asyncio
async def test_resume_retries_a_cluster_whose_rewrite_failed(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    """🔴 THE DEFECT: ``--resume`` permanently abandoned the clusters that most needed
    retrying — measured on the live Bank on 2026-08-19 at **44 drafts**.

    A rewrite failure is isolated, never fatal: the cluster keeps the deterministic
    merge draft and the run continues (that is deliberate — see ``_run_llm_passes``).
    But the resume predicate asked ``pipeline.llm_enabled``, which records only that a
    client was INJECTED. So a cluster whose rewrite raised was stamped ``llm_enabled:
    true`` exactly like one whose rewrite landed, and every later ``--resume`` pass
    skipped it. The transient failure became permanent, and a ~44-hour pass could never
    repair the rows it had itself damaged.

    ``rewrite_ran`` / ``rewrite_failed`` were already written to the same packet since
    Phase 4.2a. Nothing needed to be recorded; the wrong field was being read.

    Pinned by the model call COUNT, because the point is that the work IS redone.
    """
    async with session_maker() as session:
        await _seed_pair(session)
        await session.commit()

        # A pass whose rewrite raises: the merge draft is kept, the run continues.
        failed = _FakeChat(raise_on="rewrite")
        first = await run_canonical_producer(
            session, rewrite_client=failed, audit_client=_FakeChat()
        )
        await session.commit()

        assert first.rewrite_failures == 1
        assert first.drafts_persisted == 1
        written = await session.scalar(select(CanonicalJD))
        assert written is not None
        # The row records BOTH facts: a client was injected, and the rewrite did
        # not land.
        assert written.change_log["pipeline"]["llm_enabled"] is True
        assert written.change_log["pipeline"]["rewrite_ran"] is False
        assert written.change_log["pipeline"]["rewrite_failed"] is True

        # The resume owes this cluster work — the draft holds no rewritten prose.
        second = _FakeChat()
        resumed = await run_canonical_producer(
            session,
            rewrite_client=second,
            audit_client=_FakeChat(),
            skip_llm_written=True,
        )
        await session.commit()

        assert resumed.skipped_already_llm_written == 0
        assert resumed.drafts_refreshed == 1
        assert second.seen == [SFUJobDescription]  # the retry was actually attempted

        repaired = await session.get(CanonicalJD, written.id)
        assert repaired is not None
        assert repaired.change_log["pipeline"]["rewrite_ran"] is True
        assert repaired.change_log["pipeline"]["rewrite_failed"] is False

        # ...and NOW a further resume leaves it alone, so the fix narrows the skip
        # rather than removing it.
        third = _FakeChat()
        settled = await run_canonical_producer(
            session,
            rewrite_client=third,
            audit_client=_FakeChat(),
            skip_llm_written=True,
        )
        await session.commit()

        assert settled.skipped_already_llm_written == 1
        assert settled.drafts_refreshed == 0
        assert third.seen == []


@pytest.mark.asyncio
async def test_a_deterministic_run_may_refresh_a_draft_whose_rewrite_failed(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    """The no-DOWNGRADE rule protects LLM-written PROSE. A rewrite-failed draft holds
    the deterministic merge and nothing else, so refreshing it with a deterministic run
    replaces a merge with a merge — not a downgrade, and blocking it was the same
    misread of ``llm_enabled`` as the resume bug.

    The consequence on the live Bank: those 44 rows could be repaired by neither an
    expensive run (resume skipped them) nor a cheap one (the downgrade guard skipped
    them). They were unreachable by any producer invocation that did not name them.
    """
    async with session_maker() as session:
        await _seed_pair(session)
        await session.commit()

        await run_canonical_producer(
            session,
            rewrite_client=_FakeChat(raise_on="rewrite"),
            audit_client=_FakeChat(),
        )
        await session.commit()

        cheap = await run_canonical_producer(session, rewrite_client=None)
        await session.commit()

        assert cheap.skipped_would_downgrade == 0
        assert cheap.drafts_refreshed == 1


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


@pytest.mark.asyncio
async def test_a_resume_skip_writes_an_append_only_audit_row(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    """The module's stated invariant (NN #6, module docstring) is "one ``audit_log`` row
    per persist/refresh **and per skip**". The RESUME skip was the one skip that wrote
    nothing, so a resumed pass over the live Bank left no record of which clusters it
    declined and why — during exactly the ~44-hour run where telling a good pass from a
    ruined one matters most, and where `refreshed=N failures=0` prints identically
    either way.
    """
    async with session_maker() as session:
        await _seed_pair(session)
        await session.commit()

        await run_canonical_producer(
            session, rewrite_client=_FakeChat(), audit_client=_FakeChat()
        )
        await session.commit()

        resumed = await run_canonical_producer(
            session,
            rewrite_client=_FakeChat(),
            audit_client=_FakeChat(),
            skip_llm_written=True,
        )
        await session.commit()
        assert resumed.skipped_already_llm_written == 1

    async with session_maker() as session:
        skips = (
            await session.scalars(
                select(AuditLog).where(
                    AuditLog.event_type == "canonical_draft.skipped_resume"
                )
            )
        ).all()
        assert len(skips) == 1
        assert skips[0].actor == "producer"
        assert skips[0].payload["reason"] == "resume_rewrite_already_landed"
        # Counts/flags only — NEVER JD text / incumbent PII.
        assert "cluster_id" in skips[0].payload
        assert "title" not in skips[0].payload


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
        # ⚠ THE CONTROL FOR PHASE D. `templates_harmonized` ships `[jdfn, wjq]` as a
        # PRIORITY order, so a mixed cluster still authors JDFN and still drops its WJQ
        # member — byte-identical to the pre-Phase-D behaviour. Making CUPE drafts must
        # not quietly re-author a cluster a reviewer is already reading.
        assert result.clusters_by_template == {"jdfn": 1}
        assert result.wjq_members_authored == 0

        canonical = await session.scalar(select(CanonicalJD))
        assert canonical is not None
        # Only the two JDFN members fed the canonical — the WJQ member is not a source.
        assert len(canonical.source_document_ids) == 2
        assert canonical.content["employee_group"] == "apsa"


@pytest.mark.asyncio
async def test_an_all_cupe_cluster_gets_a_wjq_draft(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    """CUPE Phase D (HR-206): an all-CUPE cluster is DRAFTED, on the WJQ form.

    Before Phase D this cluster produced nothing — 657 of 2,458 real clusters (26.7%)
    and 3,511 member documents, counted as excluded but never given a draft a human
    could read. The draft carries the members' own ``employee_group``, which is what
    makes ``evaluate_jd_rules`` judge it against the WJQ profile (Phases B + C) rather
    than against a form it was never written on.
    """
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

        assert result.clusters_fully_wjq_excluded == 0
        assert result.clusters_seen == 1
        assert result.clusters_by_template == {"wjq": 1}
        assert result.drafts_persisted == 1
        # The two halves of the WJQ population, and they must not both count it.
        assert result.wjq_members_authored == 2
        assert result.wjq_members_excluded == 0

        canonical = await session.scalar(select(CanonicalJD))
        assert canonical is not None
        assert canonical.status is CanonicalStatus.DRAFT  # NN #1 — still just a draft
        assert canonical.content["employee_group"] == "cupe"
        assert len(canonical.source_document_ids) == 2


@pytest.mark.asyncio
async def test_each_form_is_evaluated_against_its_own_bar_and_never_blended(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    """CUPE Phase D's reporting rule, over a real run holding BOTH forms.

    Two separate clusters — one JDFN, one CUPE — produce two drafts, and each form's
    numbers are reported under its own key. The important assertion is the last one:
    the JDFN entry's counts are exactly what a JDFN-only run would have produced, so
    introducing the CUPE cohort cannot move the number HR has been reading.
    """
    async with session_maker() as session:
        a = await _seed_jd(
            session, storage_ref="a", sha256=_sha("a"), parsed=_analyst()
        )
        b = await _seed_jd(
            session, storage_ref="b", sha256=_sha("b"), parsed=_analyst()
        )
        c = await _seed_jd(
            session, storage_ref="c", sha256=_sha("c"), parsed=_analyst(group="cupe")
        )
        d = await _seed_jd(
            session, storage_ref="d", sha256=_sha("d"), parsed=_analyst(group="cupe")
        )
        await _role_edge(session, a.id, b.id)
        await _role_edge(session, c.id, d.id)
        await session.commit()

        result = await run_canonical_producer(session, rewrite_client=None)
        await session.commit()

        assert set(result.evaluation_by_template) == {"jdfn", "wjq"}
        jdfn = result.evaluation_by_template["jdfn"]
        wjq = result.evaluation_by_template["wjq"]
        assert jdfn.drafts_scored == 1
        assert wjq.drafts_scored == 1
        # Each form's grades account for exactly its own drafts — nothing crosses over.
        assert sum(jdfn.grades.values()) == jdfn.drafts_scored
        assert sum(wjq.grades.values()) == wjq.drafts_scored
        assert jdfn.clusters + wjq.clusters == result.clusters_seen

        # ⚠ THE CONTROL: the same run with CUPE off the list reports an IDENTICAL jdfn
        # block. If drafting CUPE could move the JDFN cohort's numbers, every figure HR
        # has already been given would silently change under them.
        jdfn_only = await run_canonical_producer(
            session, rewrite_client=None, rules=_jdfn_only(get_rules())
        )
        await session.commit()
        assert jdfn_only.evaluation_by_template["jdfn"] == jdfn


@pytest.mark.asyncio
async def test_a_fully_wjq_cluster_persists_nothing_with_wjq_off_the_list(
    session_maker: async_sessionmaker[AsyncSession], rules: Rules
) -> None:
    """The MUTATION that proves HR-206 is read at all, in the other direction: remove
    ``wjq`` from ``templates_harmonized`` and the same cluster produces no draft and is
    counted as excluded — the exact pre-Phase-D behaviour, reachable by a one-line YAML
    edit rather than by a code change. That is the whole point of the knob: if HR rules
    the Bank should not draft CUPE roles, nothing has to be rewritten to comply."""
    async with session_maker() as session:
        a = await _seed_jd(
            session, storage_ref="a", sha256=_sha("a"), parsed=_analyst(group="cupe")
        )
        b = await _seed_jd(
            session, storage_ref="b", sha256=_sha("b"), parsed=_analyst(group="cupe")
        )
        await _role_edge(session, a.id, b.id)
        await session.commit()

        result = await run_canonical_producer(
            session, rewrite_client=None, rules=_jdfn_only(rules)
        )
        await session.commit()

        assert result.clusters_fully_wjq_excluded == 1
        assert result.clusters_seen == 0
        assert result.clusters_by_template == {}
        assert result.drafts_persisted == 0
        assert result.wjq_members_excluded == 2
        assert result.wjq_members_authored == 0
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


@pytest.mark.asyncio
async def test_a_reviewer_acting_during_the_llm_window_is_not_overwritten(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    """🔴 NON-NEGOTIABLE #1, IN THE DIRECTION NOTHING WATCHED.

    The no-clobber check runs BEFORE the merge and two model calls — ~65 seconds before
    the write. A reviewer can approve inside that window, and the refresh is an
    unconditional UPDATE with no predicate: producer prose would land in a PUBLISHED row
    under an HR approval, audited as a "refresh". Not a bad publish — published content
    silently replaced.

    The fake client is what makes the race deterministic: it mutates the row mid-call,
    standing in for the reviewer who clicked Approve while the GPU was busy.

    ⚠ Note what is NOT done: the step-1 read is still lock-free. Locking there would
    hold a row lock across both LLM calls and block every reviewer who opened that draft
    during a multi-hour run. The lock belongs around the write.
    """

    class _ApproveMidFlight:
        """Publishes the row while the 'model' is thinking."""

        def __init__(self, session: AsyncSession, canonical_id: uuid.UUID) -> None:
            self._session = session
            self._id = canonical_id
            self.seen: list[type[object]] = []

        async def chat_json(
            self,
            messages: object,
            model_cls: type[object],
            *,
            max_tokens: int,
            max_retries: int,
            constrain_to_schema: bool = False,
        ) -> object:
            self.seen.append(model_cls)
            row = await self._session.get(CanonicalJD, self._id)
            if row is not None and row.status is CanonicalStatus.DRAFT:
                row.status = CanonicalStatus.PUBLISHED
                await self._session.flush()
            if model_cls is SFUJobDescription:
                return _rewrite_jd()
            return JDQualityFindings(issues=[])

    async with session_maker() as session:
        await _seed_pair(session)
        await session.commit()

        await run_canonical_producer(session, rewrite_client=None)
        await session.commit()
        written = await session.scalar(select(CanonicalJD))
        assert written is not None
        original = dict(written.content)

        hijack = _ApproveMidFlight(session, written.id)
        result = await run_canonical_producer(
            session, rewrite_client=hijack, audit_client=_FakeChat()
        )
        await session.commit()

        after = await session.get(CanonicalJD, written.id)
        assert after is not None
        # The reviewer's decision stands, and their published content is untouched.
        assert after.status is CanonicalStatus.PUBLISHED
        assert after.content == original
        assert result.drafts_refreshed == 0
        assert result.skipped_reviewer_touched == 1

        # ...and the audit says a human acted DURING the window, not just "touched".
        rows = (
            await session.scalars(
                select(AuditLog).where(
                    AuditLog.event_type == "canonical_draft.skipped_reviewer_touched"
                )
            )
        ).all()
        assert any(
            r.payload.get("reason") == "reviewer_touched_during_llm_window"
            for r in rows
        )


# --- operational scoping: --only-template --------------------------------------------


@pytest.mark.asyncio
async def test_only_template_processes_one_cohort_and_leaves_the_other_untouched(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    """🔴 WHY THIS EXISTS. Re-running the producer to repair the CUPE cohort meant a
    FULL pass — 2,493 clusters, ~44 hours — because the only scoping the CLI had was
    ``--limit N`` over ``parsed_jds`` rows, which is a smoke test rather than a cohort.
    Measured on the live Bank: **649 of 2,493 clusters are CUPE**, so the other 1,844
    were being rewritten purely as collateral, at ~4x the cost of the work actually
    wanted — and, with the 4.1 section merge still to land, they would need rewriting
    again immediately afterwards.

    ⚠ **This is OPERATIONAL scoping, not a rulebook decision.** It filters which
    clusters THIS INVOCATION processes, *after* the rulebook has decided which form
    each cluster authors on. It does NOT change that decision — that is
    ``harmonization.templates_harmonized``, an HR-registered priority order, and
    narrowing it to ``[wjq]`` would ALSO re-author mixed clusters and desynchronise the
    write-once ``clusters`` snapshot. Hence a CLI flag, in the same class as
    ``--limit``, and no register entry.

    The assertion that matters is the third one: the out-of-scope cohort is not merely
    uncounted, it has **no row written at all**.
    """
    async with session_maker() as session:
        # One CUPE cluster (authors WJQ) and one APSA cluster (authors JDFN).
        c1 = await _seed_jd(
            session, storage_ref="c1", sha256=_sha("c1"), parsed=_analyst(group="cupe")
        )
        c2 = await _seed_jd(
            session, storage_ref="c2", sha256=_sha("c2"), parsed=_analyst(group="cupe")
        )
        await _role_edge(session, c1.id, c2.id)
        j1 = await _seed_jd(
            session, storage_ref="j1", sha256=_sha("j1"), parsed=_analyst()
        )
        j2 = await _seed_jd(
            session, storage_ref="j2", sha256=_sha("j2"), parsed=_analyst()
        )
        await _role_edge(session, j1.id, j2.id)
        await session.commit()

        scoped = await run_canonical_producer(
            session, rewrite_client=None, only_template="wjq"
        )
        await session.commit()

        assert scoped.clusters_by_template == {"wjq": 1}
        assert scoped.drafts_persisted == 1
        assert scoped.clusters_out_of_scope == 1

    async with session_maker() as session:
        # The JDFN cohort was not touched: no draft, not merely an uncounted one.
        rows = (await session.scalars(select(CanonicalJD))).all()
        assert len(rows) == 1
        assert rows[0].content["employee_group"] == "cupe"

    async with session_maker() as session:
        # ...and the control: unscoped, the SAME corpus produces both.
        both = await run_canonical_producer(session, rewrite_client=None)
        await session.commit()

        assert both.clusters_by_template == {"wjq": 1, "jdfn": 1}
        assert both.clusters_out_of_scope == 0
        assert both.drafts_persisted == 1  # the JDFN one; the WJQ one is refreshed
        assert both.drafts_refreshed == 1


@pytest.mark.asyncio
async def test_only_template_does_not_pay_the_model_for_the_cohort_it_skips(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    """The whole point is the GPU hours. A scoping flag that still drove the rewrite
    over the out-of-scope cohort would count correctly and save nothing, and the counts
    are exactly what a passing test would otherwise check.

    Pinned by the model call COUNT, for the same reason the resume test is.
    """
    async with session_maker() as session:
        c1 = await _seed_jd(
            session, storage_ref="c1", sha256=_sha("c1"), parsed=_analyst(group="cupe")
        )
        c2 = await _seed_jd(
            session, storage_ref="c2", sha256=_sha("c2"), parsed=_analyst(group="cupe")
        )
        await _role_edge(session, c1.id, c2.id)
        j1 = await _seed_jd(
            session, storage_ref="j1", sha256=_sha("j1"), parsed=_analyst()
        )
        j2 = await _seed_jd(
            session, storage_ref="j2", sha256=_sha("j2"), parsed=_analyst()
        )
        await _role_edge(session, j1.id, j2.id)
        await session.commit()

        rewrite = _FakeChat()
        await run_canonical_producer(
            session,
            rewrite_client=rewrite,
            audit_client=_FakeChat(),
            only_template="wjq",
        )
        await session.commit()

        # ONE rewrite, for the one in-scope cluster — not two.
        assert rewrite.seen == [SFUJobDescription]


# --- the clusters snapshot follows the draft it describes ----------------------------


def _wjq_first(rules: Rules) -> Rules:
    """``templates_harmonized`` re-ordered so a MIXED cluster authors on the WJQ form
    instead of the JDFN one — the change that re-authors a draft without touching a
    single source document."""
    harmonization = Harmonization(
        **{**rules.harmonization.model_dump(), "templates_harmonized": ("wjq", "jdfn")}
    )
    return rules.model_copy(update={"harmonization": harmonization})


async def _seed_cupe_pair(session: AsyncSession) -> None:
    """Two role-equivalent CUPE analysts — an ALL-WJQ cluster, so the run authors on
    the WJQ form and every member of it is a WJQ member."""
    a = await _seed_jd(
        session, storage_ref="ca", sha256=_sha("ca"), parsed=_analyst(group="cupe")
    )
    b = await _seed_jd(
        session, storage_ref="cb", sha256=_sha("cb"), parsed=_analyst(group="cupe")
    )
    await _role_edge(session, a.id, b.id)


async def test_the_cluster_snapshot_is_re_authored_with_the_draft(
    session_maker: async_sessionmaker[AsyncSession], rules: Rules
) -> None:
    """🔴 THE SNAPSHOT WAS WRITE-ONCE, and the draft was not.

    The ``clusters`` row was built on FIRST INSERT and never touched again, while the
    canonical was re-authored on every run. So re-ordering ``templates_harmonized``
    flipped a mixed cluster's draft from JDFN to WJQ and left the snapshot claiming the
    OLD form and the OLD member list. The Library reads that snapshot to answer "which
    documents is this role drawn from?", so HR would have read a CUPE role whose sources
    were listed as APSA documents, with nothing anywhere saying the two disagreed.

    Both rows are DERIVED from the same members on the same run. They move together or
    the provenance is a lie (NN #6).
    """
    mixed = _no_group_veto(rules)
    async with session_maker() as session:
        apsa, cupe = await _seed_pair(session, group_b="cupe")
        await session.commit()

    # Pass 1 — shipped order: the mixed cluster authors JDFN.
    async with session_maker() as session:
        await run_canonical_producer(
            session, rewrite_client=None, audit_client=None, rules=mixed
        )
        await session.commit()

    async with session_maker() as session:
        cluster = (await session.scalars(select(Cluster))).one()
        assert cluster.constraint_metadata["authored_template"] == "jdfn"
        assert [m["source_id"] for m in cluster.members] == [str(apsa.id)]

    # Pass 2 — WJQ first. The DRAFT is re-authored on the other form...
    async with session_maker() as session:
        result = await run_canonical_producer(
            session,
            rewrite_client=None,
            audit_client=None,
            rules=_wjq_first(mixed),
        )
        await session.commit()
        assert result.drafts_refreshed == 1

    # ...and the snapshot followed it. Before this fix both assertions below held the
    # PASS-1 values while the canonical held CUPE prose.
    async with session_maker() as session:
        cluster = (await session.scalars(select(Cluster))).one()
        assert cluster.constraint_metadata["authored_template"] == "wjq"
        assert [m["source_id"] for m in cluster.members] == [str(cupe.id)]
        assert cluster.employee_group == "cupe"


async def test_an_unreadable_member_row_is_dropped_at_clustering_not_at_the_merge(
    session_maker: async_sessionmaker[AsyncSession], rules: Rules
) -> None:
    """🔴 WHY ``member_rows_dropped_unvalidatable`` IS STRUCTURALLY ZERO HERE — measured
    while trying to write the opposite test.

    The review finding "a member dropped by ``load_member_jds`` is invisible per
    cluster" describes a path that cannot currently be taken. Both loaders read the same
    ``parsed_jds`` rows through ``SFUJobDescription.model_validate``, but
    ``load_signed_corpus`` (clustering) ALSO has to build ``JobSignals``, so it accepts
    a strict SUBSET: a row that fails the member load would already have failed to sign
    and would never be in a cluster to be dropped from.

    So the loss is real but it happens EARLIER and is already counted, as
    ``documents_unsignable`` — which is what this test pins. The per-cluster
    ``members_unloadable`` field stays as defence in depth: the two loaders are separate
    functions with separate validation, and if anyone ever tightens the member load this
    becomes live without the snapshot needing to be retaught.
    """
    async with session_maker() as session:
        _a, b = await _seed_pair(session)
        await session.commit()

    # Corrupt in a SEPARATE session: inside the seeding one the ParsedJDRow is still a
    # pending ORM object, so the raw UPDATE hits nothing and the subsequent flush
    # inserts the pristine row over it.
    async with session_maker() as session:
        await session.execute(
            text(
                'UPDATE parsed_jds SET parsed = \'{"title": ""}\'::jsonb '
                "WHERE source_document_id = :sid"
            ),
            {"sid": b.id},
        )
        await session.commit()

    async with session_maker() as session:
        result = await run_canonical_producer(
            session, rewrite_client=None, audit_client=None, rules=rules
        )
        await session.commit()

    # Dropped at CLUSTERING, and counted there...
    assert result.documents_seen == 2
    assert result.documents_unsignable == 1
    # ...so the merge never saw it, and the member load dropped nothing.
    assert result.member_rows_dropped_unvalidatable == 0
    # The surviving document no longer clusters with anything, so nothing is drafted
    # from a silently-halved cluster — the outcome the finding was worried about.
    assert result.clusters_recomputed == 0
    assert result.clusters_seen == 0


async def test_wjq_members_are_authored_only_when_the_run_wrote_the_draft(
    session_maker: async_sessionmaker[AsyncSession], rules: Rules
) -> None:
    """``wjq_members_authored`` was incremented off the cluster's FORM before the
    cluster was processed, so it counted members of clusters the run then skipped. On a
    resumed pass — the whole point of #126 — that reported thousands of members
    "authored" by a run that wrote nothing. Authored now means "fed a draft this run
    WROTE"; the rest are ``wjq_members_unwritten``."""
    async with session_maker() as session:
        await _seed_cupe_pair(session)
        await session.commit()

    # Pass 1 writes the draft: the two CUPE members are genuinely authored.
    async with session_maker() as session:
        first = await run_canonical_producer(
            session, rewrite_client=None, audit_client=None, rules=rules
        )
        await session.commit()
    assert first.wjq_members_authored == 2
    assert first.wjq_members_unwritten == 0

    # Pass 2 SKIPS it (a reviewer touched the draft) — so nobody was authored by it.
    async with session_maker() as session:
        canonical = (await session.scalars(select(CanonicalJD))).one()
        session.add(
            ReviewAction(
                canonical_jd_id=canonical.id,
                reviewer_id="hr-user",
                action=ReviewActionKind.EDIT,
                reason="touched",
            )
        )
        await session.commit()

    async with session_maker() as session:
        second = await run_canonical_producer(
            session, rewrite_client=None, audit_client=None, rules=rules
        )
        await session.commit()

    assert second.skipped_reviewer_touched == 1
    assert second.wjq_members_authored == 0
    assert second.wjq_members_unwritten == 2


async def test_a_mixed_cluster_is_counted_mixed_whichever_form_wins(
    session_maker: async_sessionmaker[AsyncSession], rules: Rules
) -> None:
    """``clusters_mixed_jdfn_wjq`` also required the winner to be non-WJQ, so putting
    ``wjq`` first in ``templates_harmonized`` reported every mixed cluster as un-mixed.
    Mixed is a property of the CLUSTER's membership, not of which form won."""
    mixed_rules = _no_group_veto(rules)
    async with session_maker() as session:
        await _seed_pair(session, group_b="cupe")
        await session.commit()

    for scoped in (mixed_rules, _wjq_first(mixed_rules)):
        async with session_maker() as session:
            result = await run_canonical_producer(
                session, rewrite_client=None, audit_client=None, rules=scoped
            )
            await session.commit()
        assert result.clusters_mixed_jdfn_wjq == 1

"""Integration — the Phase-4.4b review SERVICE against a real Postgres, through the real
migration. This is where Phase 4's human-approval spine is pinned; what only a real
database can prove:

1. **NN #1, MUTATION-pinned.** A draft whose FRESH gate decision blocks CANNOT be
   approved: ``approve`` (no overrides) RAISES and publishes nothing — status stays
   DRAFT,
   no APPROVE action, no publish audit. A permitted draft (all gates clear) → PUBLISHED.
   Break the guard (publish while blocking) and the behavioural assertions go RED.
2. **Override needs a written reason.** An override of a real blocking overridable gate
+
   a reason publishes and writes an OVERRIDE action carrying the reason + an audit row.
   An
   override of a NON-overridable / not-currently-blocking gate RAISES and publishes
   nothing.
3. **Re-validate on approve/edit (validator-as-oracle).** Editing a permitted draft to
   REINTRODUCE a blocker makes the next approve RAISE; and a draft whose STORED roll-up
   says approvable but whose CURRENT content blocks is refused — the decision comes from
   the content, never the stored decision.
4. **Append-only audit + review actions.** approve/reject/edit each write the right
   ``review_actions`` + ``audit_log`` rows; rows only accrue. reject archives; edit
   mints
   ``version=2, status=DRAFT``.
5. **Legal transitions.** A missing id RAISES; approving/rejecting an already
   PUBLISHED/ARCHIVED canonical RAISES (no double-publish).
6. **Latest-version lookup.** After an edit (v2), the queue and the 4.4a producer's
   no-clobber lookup resolve to v2 (``order_by(version desc)``), not v1.

The clean-JD recipe is the same baseline the 2.2 validator + 2.3 gate suites use — a JD
that clears every gate — so "permitted" is a real, reproducible state, not a mock.
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
from src.jd_bank.jd_text import flatten_jd
from src.jd_bank.review import (
    CanonicalNotFoundError,
    GateOverrideError,
    IllegalTransitionError,
    MissingReasonError,
    NotApprovableError,
    approve,
    edit,
    get_review_packet,
    list_review_queue,
    reject,
)
from src.jd_core.models.parsed_jd import (
    SFUDuty,
    SFUJobDescription,
    SFUQualification,
    SFURelationships,
)
from src.jd_core.models.quality import GateOverride
from src.jd_core.parser import PARSER_VERSION
from src.jd_core.quality.gates import evaluate_gates
from src.jd_core.quality.scoring import score_issues
from src.jd_core.quality.validators import evaluate_jd_rules
from src.jd_core.rules import get_rules
from tests.integration.test_dedup_tier1 import ALEMBIC_INI

REVIEWER = "hr-reviewer"


# --- the clean, approvable JD (the 2.3 gate suite's baseline) ------------------------


def _clean_jd(**update: object) -> SFUJobDescription:
    jd = SFUJobDescription(
        title="Software Developer",
        employee_group="apsa",
        about_sfu_present=True,
        position_summary=" ".join(["word"] * 120),
        duties=[
            SFUDuty(
                action_verb=verb,
                statement=f"{verb} the program",
                how_why=["by coordinating stakeholders"],
            )
            for verb in ("Manages", "Coordinates", "Provides")
        ],
        decision_making=["Approves expenditures up to $5k"],
        problem_solving=["Resolves scheduling conflicts independently"],
        relationships=SFURelationships(
            supervisory="Supervises 2 staff",
            internal=["Finance"],
            external=["Vendors"],
        ),
        qualifications=[
            SFUQualification(
                text="Bachelor's degree or an equivalent combination of experience",
                kind="education",
            ),
            SFUQualification(
                text="Excellent knowledge of databases",
                kind="knowledge",
                modifier="excellent",
            ),
            SFUQualification(text="Python", kind="skill", modifier="advanced"),
            SFUQualification(text="Ability to work cooperatively", kind="ability"),
        ],
        territorial_acknowledgement_present=True,
        employment_equity_present=True,
    )
    return jd.model_copy(update=update)


def _decision(jd: SFUJobDescription) -> object:
    """The service's own decision path, so a test can assert its FIXTURE's precondition
    (the same flatten + validate + score + gates the service runs)."""
    rules = get_rules()
    issues = evaluate_jd_rules(jd, flatten_jd(jd), rules=rules)
    score, grade = score_issues(issues, scoring=rules.scoring)
    return evaluate_gates(issues, score, grade, gates=rules.gates)


# --- DB harness (mirrors the 4.4a producer suite) ------------------------------------


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
        await conn.execute(text("DELETE FROM source_documents"))
        await conn.execute(text("DELETE FROM clusters"))
        await conn.execute(text("DELETE FROM audit_log"))
    maker = async_sessionmaker(engine, expire_on_commit=False)
    yield maker
    await engine.dispose()


async def _seed_cluster(session: AsyncSession, cluster_id: uuid.UUID) -> None:
    if await session.get(Cluster, cluster_id) is None:
        session.add(Cluster(id=cluster_id, label="seeded", members=[]))
        await session.flush()


async def _seed_canonical(
    session: AsyncSession,
    *,
    content: dict[str, object],
    status: CanonicalStatus = CanonicalStatus.DRAFT,
    version: int = 1,
    change_log: dict[str, object] | None = None,
    cluster_id: uuid.UUID | None = None,
) -> CanonicalJD:
    cluster_id = cluster_id or uuid.uuid4()
    await _seed_cluster(session, cluster_id)
    canonical = CanonicalJD(
        cluster_id=cluster_id,
        version=version,
        status=status,
        content=content,
        source_document_ids=[],
        change_log=change_log or {},
    )
    session.add(canonical)
    await session.flush()
    return canonical


async def _counts(session: AsyncSession) -> tuple[int, int]:
    actions = await session.scalar(select(func.count()).select_from(ReviewAction))
    audits = await session.scalar(select(func.count()).select_from(AuditLog))
    return int(actions or 0), int(audits or 0)


# --- acceptance #1: NN #1 — nothing publishes unless the gate PERMITS it --------------


@pytest.mark.asyncio
async def test_a_permitted_draft_publishes_and_records_the_approval(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    assert _decision(_clean_jd()).approved is True  # fixture precondition
    async with session_maker() as session:
        canonical = await _seed_canonical(
            session, content=_clean_jd().model_dump(mode="json")
        )
        cid = canonical.id
        await session.commit()

        published = await approve(session, cid, reviewer_id=REVIEWER)
        await session.commit()
        assert published.status is CanonicalStatus.PUBLISHED

    async with session_maker() as session:
        row = await session.get(CanonicalJD, cid)
        assert row is not None and row.status is CanonicalStatus.PUBLISHED
        actions = (
            await session.scalars(
                select(ReviewAction).where(ReviewAction.canonical_jd_id == cid)
            )
        ).all()
        assert [a.action for a in actions] == [ReviewActionKind.APPROVE]
        audits = (
            await session.scalars(
                select(AuditLog).where(AuditLog.event_type == "review.approved")
            )
        ).all()
        assert len(audits) == 1
        assert "title" not in audits[0].payload  # counts/ids/reasons only, no JD prose


@pytest.mark.asyncio
async def test_a_blocking_draft_cannot_be_approved_and_publishes_nothing(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    """MUTATION pin of NN #1. A draft with duties removed trips the non-overridable
    MANDATORY-SECTIONS gate. ``approve`` (no overrides) must RAISE and write NOTHING.
    Delete the ``if not permitted.approved: raise`` guard (let it publish while
    blocking)
    and every assertion below goes RED."""
    blocking = _clean_jd(duties=[])
    assert _decision(blocking).approved is False  # fixture precondition
    async with session_maker() as session:
        canonical = await _seed_canonical(
            session, content=blocking.model_dump(mode="json")
        )
        cid = canonical.id
        await session.commit()

        with pytest.raises(NotApprovableError):
            await approve(session, cid, reviewer_id=REVIEWER)
        await session.commit()

    async with session_maker() as session:
        row = await session.get(CanonicalJD, cid)
        assert (
            row is not None and row.status is CanonicalStatus.DRAFT
        )  # never published
        actions, audits = await _counts(session)
        assert actions == 0  # no APPROVE action
        assert audits == 0  # no publish audit


# --- acceptance #2: an override needs a written reason --------------------------------


@pytest.mark.asyncio
async def test_an_overridable_blocker_is_published_only_with_a_reasoned_override(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    no_footer = _clean_jd(
        territorial_acknowledgement_present=False, employment_equity_present=False
    )
    decision = _decision(no_footer)
    assert decision.approved is False
    assert {r.gate_id for r in decision.blocking} == {"SFU-APPROVE-EDI-FOOTER"}
    async with session_maker() as session:
        canonical = await _seed_canonical(
            session, content=no_footer.model_dump(mode="json")
        )
        cid = canonical.id
        await session.commit()

        # Without an override it is refused.
        with pytest.raises(NotApprovableError):
            await approve(session, cid, reviewer_id=REVIEWER)
        await session.rollback()

        override = GateOverride(
            gate_id="SFU-APPROVE-EDI-FOOTER",
            reviewer=REVIEWER,
            reason="Footer is boilerplate the composer restores at publish.",
        )
        published = await approve(
            session, cid, reviewer_id=REVIEWER, overrides=[override]
        )
        await session.commit()
        assert published.status is CanonicalStatus.PUBLISHED

    async with session_maker() as session:
        actions = (
            await session.scalars(
                select(ReviewAction)
                .where(ReviewAction.canonical_jd_id == cid)
                .order_by(ReviewAction.action)
            )
        ).all()
        by_kind = {a.action: a for a in actions}
        assert set(by_kind) == {ReviewActionKind.APPROVE, ReviewActionKind.OVERRIDE}
        # The reason IS the record (NN #6): persisted on the OVERRIDE action + audit.
        assert by_kind[ReviewActionKind.OVERRIDE].reason.startswith("Footer is")
        waiver = (
            await session.scalars(
                select(AuditLog).where(AuditLog.event_type == "review.override")
            )
        ).all()
        assert len(waiver) == 1
        assert waiver[0].payload["gate_id"] == "SFU-APPROVE-EDI-FOOTER"
        assert waiver[0].payload["reason"].startswith("Footer is")


@pytest.mark.asyncio
async def test_overriding_a_non_overridable_gate_raises_and_publishes_nothing(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    blocking = _clean_jd(duties=[])  # trips the non-overridable MANDATORY-SECTIONS gate
    async with session_maker() as session:
        canonical = await _seed_canonical(
            session, content=blocking.model_dump(mode="json")
        )
        cid = canonical.id
        await session.commit()

        override = GateOverride(
            gate_id="SFU-APPROVE-MANDATORY-SECTIONS",
            reviewer=REVIEWER,
            reason="I want to publish anyway",
        )
        with pytest.raises(GateOverrideError):
            await approve(session, cid, reviewer_id=REVIEWER, overrides=[override])
        await session.commit()

    async with session_maker() as session:
        row = await session.get(CanonicalJD, cid)
        assert row is not None and row.status is CanonicalStatus.DRAFT
        actions, audits = await _counts(session)
        assert (actions, audits) == (0, 0)


@pytest.mark.asyncio
async def test_overriding_a_not_currently_blocking_gate_raises(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    """A clean draft has no blocking gate; waiving one that is not blocking is an error
    (``apply_overrides`` raises), and nothing publishes."""
    async with session_maker() as session:
        canonical = await _seed_canonical(
            session, content=_clean_jd().model_dump(mode="json")
        )
        cid = canonical.id
        await session.commit()

        override = GateOverride(
            gate_id="SFU-APPROVE-EDI-FOOTER", reviewer=REVIEWER, reason="unnecessary"
        )
        with pytest.raises(GateOverrideError):
            await approve(session, cid, reviewer_id=REVIEWER, overrides=[override])
        await session.commit()

    async with session_maker() as session:
        row = await session.get(CanonicalJD, cid)
        assert row is not None and row.status is CanonicalStatus.DRAFT


# --- acceptance #3: re-validate on approve/edit (validator-as-oracle) -----------------


@pytest.mark.asyncio
async def test_approve_trusts_current_content_not_the_stored_decision(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    """The strongest validator-as-oracle pin. The stored ``change_log`` roll-up LIES
    that
    the draft is approvable, but the CURRENT content blocks. ``approve`` must recompute
    from the content and REFUSE. If the service trusted the stored decision it would
    publish → RED."""
    blocking = _clean_jd(duties=[])
    lying_rollup = {
        "validator": {
            "gate_decision": {"approved": True, "blocking": [], "overridden": []}
        }
    }
    async with session_maker() as session:
        canonical = await _seed_canonical(
            session,
            content=blocking.model_dump(mode="json"),
            change_log=lying_rollup,
        )
        cid = canonical.id
        await session.commit()

        with pytest.raises(NotApprovableError):
            await approve(session, cid, reviewer_id=REVIEWER)
        await session.commit()

    async with session_maker() as session:
        row = await session.get(CanonicalJD, cid)
        assert row is not None and row.status is CanonicalStatus.DRAFT


@pytest.mark.asyncio
async def test_an_edit_that_reintroduces_a_blocker_makes_the_next_approve_refuse(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    async with session_maker() as session:
        canonical = await _seed_canonical(
            session, content=_clean_jd().model_dump(mode="json")
        )
        cid = canonical.id
        await session.commit()

        v2 = await edit(
            session,
            cid,
            reviewer_id=REVIEWER,
            new_content=_clean_jd(duties=[]).model_dump(mode="json"),
            reason="dropped the duties block by mistake",
        )
        await session.commit()
        v2_id = v2.id

        # The recompute is on the EDITED content — it now blocks, so approve refuses.
        with pytest.raises(NotApprovableError):
            await approve(session, v2_id, reviewer_id=REVIEWER)
        await session.commit()

    async with session_maker() as session:
        row = await session.get(CanonicalJD, v2_id)
        assert row is not None and row.status is CanonicalStatus.DRAFT


# --- get_review_packet: the READ side of the approval spine (validator-as-oracle) -----


@pytest.mark.asyncio
async def test_get_review_packet_recomputes_the_decision_from_current_content(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    """The read side must be validator-as-oracle too (NN #3). The packet's decision is
    what a reviewer/UI reads BEFORE clicking approve, so a stale stored roll-up must
    never be surfaced as the authority. The stored ``change_log`` LIES ``approved:true``
    over content that blocks; the packet must carry the FRESHLY recomputed, blocked
    decision.
    MUTATION: return the stored decision instead of recomputing → this goes RED."""
    blocking = _clean_jd(duties=[])
    lying_rollup = {
        "validator": {
            "gate_decision": {"approved": True, "blocking": [], "overridden": []}
        }
    }
    async with session_maker() as session:
        canonical = await _seed_canonical(
            session, content=blocking.model_dump(mode="json"), change_log=lying_rollup
        )
        cid = canonical.id
        await session.commit()

        packet = await get_review_packet(session, cid)
        assert packet is not None
        # The AUTHORITY is the fresh decision, not the lying stored roll-up.
        assert packet.decision.approved is False
        assert "SFU-APPROVE-MANDATORY-SECTIONS" in {
            reason.gate_id for reason in packet.decision.blocking
        }
        # The stored roll-up is still carried for DISPLAY — but it is NOT the decision.
        assert packet.change_log["validator"]["gate_decision"]["approved"] is True


@pytest.mark.asyncio
async def test_get_review_packet_resolves_to_the_edited_version(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    """Acceptance #6, read half. After an edit (v2), the live draft a reviewer packets
    is v2 — its content, its version, its freshly recomputed decision — not the archived
    v1. (The live draft for the cluster is resolved through the queue, which is v2.)"""
    async with session_maker() as session:
        v1 = await _seed_canonical(session, content=_clean_jd().model_dump(mode="json"))
        v1_id = v1.id
        await session.commit()

        v2 = await edit(
            session,
            v1_id,
            reviewer_id=REVIEWER,
            new_content=_clean_jd(title="Data Steward").model_dump(mode="json"),
            reason="clarified the title",
        )
        await session.commit()
        v2_id = v2.id

    async with session_maker() as session:
        # The live draft for the cluster is v2 (v1 is archived, off the queue).
        queue = await list_review_queue(session)
        assert [item.canonical_id for item in queue] == [v2_id]

        packet = await get_review_packet(session, v2_id)
        assert packet is not None
        assert packet.canonical_id == v2_id and packet.canonical_id != v1_id
        assert packet.version == 2
        assert packet.content["title"] == "Data Steward"  # the edited content, not v1's
        assert packet.decision.approved is True  # freshly recomputed on v2

        # And v1, the archived predecessor, is a distinct row carrying the old content.
        v1_packet = await get_review_packet(session, v1_id)
        assert v1_packet is not None
        assert v1_packet.status is CanonicalStatus.ARCHIVED
        assert v1_packet.content["title"] == "Software Developer"


@pytest.mark.asyncio
async def test_list_review_queue_honours_the_limit(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    async with session_maker() as session:
        for _ in range(3):
            await _seed_canonical(session, content=_clean_jd().model_dump(mode="json"))
        await session.commit()

        assert len(await list_review_queue(session)) == 3
        assert len(await list_review_queue(session, limit=2)) == 2


# --- acceptance #4: append-only audit + review actions --------------------------------


@pytest.mark.asyncio
async def test_reject_archives_and_records_a_reason(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    async with session_maker() as session:
        canonical = await _seed_canonical(
            session, content=_clean_jd().model_dump(mode="json")
        )
        cid = canonical.id
        await session.commit()

        archived = await reject(
            session, cid, reviewer_id=REVIEWER, reason="Duplicate of an existing role."
        )
        await session.commit()
        assert archived.status is CanonicalStatus.ARCHIVED

    async with session_maker() as session:
        actions = (
            await session.scalars(
                select(ReviewAction).where(ReviewAction.canonical_jd_id == cid)
            )
        ).all()
        assert [a.action for a in actions] == [ReviewActionKind.REJECT]
        assert actions[0].reason == "Duplicate of an existing role."
        audits = (
            await session.scalars(
                select(AuditLog).where(AuditLog.event_type == "review.rejected")
            )
        ).all()
        assert len(audits) == 1


@pytest.mark.asyncio
async def test_a_reject_with_a_blank_reason_raises(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    async with session_maker() as session:
        canonical = await _seed_canonical(
            session, content=_clean_jd().model_dump(mode="json")
        )
        cid = canonical.id
        await session.commit()

        with pytest.raises(MissingReasonError):
            await reject(session, cid, reviewer_id=REVIEWER, reason="   ")
        await session.commit()

    async with session_maker() as session:
        row = await session.get(CanonicalJD, cid)
        assert row is not None and row.status is CanonicalStatus.DRAFT
        actions, _ = await _counts(session)
        assert actions == 0


@pytest.mark.asyncio
async def test_an_edit_with_a_blank_reason_raises(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    """An edit is a recorded decision too — its reason is mandatory (symmetric to
    reject). A blank/whitespace reason raises and mints NO new version."""
    async with session_maker() as session:
        canonical = await _seed_canonical(
            session, content=_clean_jd().model_dump(mode="json")
        )
        cid = canonical.id
        await session.commit()

        with pytest.raises(MissingReasonError):
            await edit(
                session,
                cid,
                reviewer_id=REVIEWER,
                new_content=_clean_jd(title="Renamed").model_dump(mode="json"),
                reason="   ",
            )
        await session.commit()

    async with session_maker() as session:
        # No v2 minted; the sole row is the untouched v1 draft.
        rows = (await session.scalars(select(CanonicalJD))).all()
        assert [(r.version, r.status) for r in rows] == [(1, CanonicalStatus.DRAFT)]


@pytest.mark.asyncio
async def test_the_audit_log_is_append_only_across_a_sequence(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    """Rows only ACCRUE — a later decision never updates/deletes an earlier audit
    row."""
    async with session_maker() as session:
        rejected = await _seed_canonical(
            session, content=_clean_jd().model_dump(mode="json")
        )
        approved = await _seed_canonical(
            session, content=_clean_jd().model_dump(mode="json")
        )
        rid, aid = rejected.id, approved.id
        await session.commit()

        await reject(session, rid, reviewer_id=REVIEWER, reason="not needed")
        await session.commit()
        _, after_reject = await _counts(session)
        first_audit_id = await session.scalar(select(AuditLog.id))

        await approve(session, aid, reviewer_id=REVIEWER)
        await session.commit()
        _, after_approve = await _counts(session)

    assert after_approve > after_reject  # rows only grow

    async with session_maker() as session:
        # The reject's audit row is still there, untouched (append-only).
        survivor = await session.get(AuditLog, first_audit_id)
        assert survivor is not None and survivor.event_type == "review.rejected"


# --- acceptance #5: legal transitions only --------------------------------------------


@pytest.mark.asyncio
async def test_operating_on_a_missing_canonical_raises(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    ghost = uuid.uuid4()
    async with session_maker() as session:
        with pytest.raises(CanonicalNotFoundError):
            await approve(session, ghost, reviewer_id=REVIEWER)
        with pytest.raises(CanonicalNotFoundError):
            await reject(session, ghost, reviewer_id=REVIEWER, reason="x")
        assert await get_review_packet(session, ghost) is None


@pytest.mark.asyncio
async def test_a_published_canonical_cannot_be_approved_again(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    """Stale-status pin — no double-publish. A PUBLISHED (or ARCHIVED) canonical is a
    settled decision; approving/rejecting it raises IllegalTransitionError."""
    async with session_maker() as session:
        published = await _seed_canonical(
            session,
            content=_clean_jd().model_dump(mode="json"),
            status=CanonicalStatus.PUBLISHED,
        )
        archived = await _seed_canonical(
            session,
            content=_clean_jd().model_dump(mode="json"),
            status=CanonicalStatus.ARCHIVED,
        )
        pid, aid = published.id, archived.id
        await session.commit()

        with pytest.raises(IllegalTransitionError):
            await approve(session, pid, reviewer_id=REVIEWER)
        with pytest.raises(IllegalTransitionError):
            await reject(session, aid, reviewer_id=REVIEWER, reason="x")
        with pytest.raises(IllegalTransitionError):
            await edit(
                session,
                pid,
                reviewer_id=REVIEWER,
                new_content=_clean_jd().model_dump(mode="json"),
                reason="x",
            )
        await session.commit()

    async with session_maker() as session:
        assert (await session.get(CanonicalJD, pid)).status is CanonicalStatus.PUBLISHED
        assert (await session.get(CanonicalJD, aid)).status is CanonicalStatus.ARCHIVED


# --- acceptance #6: edit mints v2, supersedes v1, and the queue/producer see v2 -------


@pytest.mark.asyncio
async def test_edit_mints_a_new_draft_version_and_supersedes_the_prior(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    async with session_maker() as session:
        v1 = await _seed_canonical(session, content=_clean_jd().model_dump(mode="json"))
        v1_id = v1.id
        await session.commit()

        v2 = await edit(
            session,
            v1_id,
            reviewer_id=REVIEWER,
            new_content=_clean_jd(title="Senior Software Developer").model_dump(
                mode="json"
            ),
            reason="clarified the title",
        )
        await session.commit()
        v2_id = v2.id
        assert v2.version == 2
        assert v2.status is CanonicalStatus.DRAFT

    async with session_maker() as session:
        # v1 is superseded (archived), v2 is the live draft.
        assert (
            await session.get(CanonicalJD, v1_id)
        ).status is CanonicalStatus.ARCHIVED
        assert (await session.get(CanonicalJD, v2_id)).status is CanonicalStatus.DRAFT
        # The EDIT action lives on the NEW version (which is what protects it from the
        # producer's no-clobber).
        actions = (
            await session.scalars(
                select(ReviewAction).where(ReviewAction.canonical_jd_id == v2_id)
            )
        ).all()
        assert [a.action for a in actions] == [ReviewActionKind.EDIT]
        assert actions[0].payload["from_version"] == 1
        # The queue shows only the live draft — v2, not the archived v1.
        queue = await list_review_queue(session)
        assert [(item.canonical_id, item.version) for item in queue] == [(v2_id, 2)]


# --- acceptance #1 + #4 + #6 END-TO-END via the real 4.4a producer -------------------


async def _seed_jd(
    session: AsyncSession, *, storage_ref: str, parsed: dict[str, object]
) -> SourceDocument:
    doc = SourceDocument(
        storage_ref=storage_ref,
        filename=storage_ref,
        sha256=uuid.uuid5(uuid.NAMESPACE_OID, storage_ref).hex * 2,
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


async def _seed_producer_cluster(session: AsyncSession) -> None:
    """Two role-equivalent JDFN analysts (storage_refs a,b) — the producer will cluster
    them under ``cluster_id_for(['a','b'])``."""
    analyst = SFUJobDescription(
        title="Analyst",
        employee_group="apsa",
        qualifications=[SFUQualification(text="python sql", kind="skill")],
    ).model_dump(mode="json")
    a = await _seed_jd(session, storage_ref="a", parsed=analyst)
    b = await _seed_jd(session, storage_ref="b", parsed=analyst)
    lo, hi = sorted((a.id, b.id), key=str)
    session.add(
        DedupEdge(
            source_a_id=lo,
            source_b_id=hi,
            tier=DedupTier.ROLE_EQUIVALENT,
            score=0.9,
            method="vec+skill@test",
        )
    )
    await session.flush()


@pytest.mark.asyncio
async def test_a_real_producer_draft_can_be_rejected_end_to_end(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    """One end-to-end path on a REAL persisted producer draft (which honestly trips the
    boilerplate gates, so it cannot be approved) — the reviewer rejects it, and a second
    producer run then SKIPS it (reviewer-touched)."""
    async with session_maker() as session:
        await _seed_producer_cluster(session)
        await session.commit()
        result = await run_canonical_producer(session, client=None)
        await session.commit()
        assert result.drafts_persisted == 1

        draft = await session.scalar(select(CanonicalJD))
        assert draft is not None and draft.status is CanonicalStatus.DRAFT
        draft_id = draft.id  # capture BEFORE the failed approve + rollback expires it
        # The real producer draft is un-approvable (validator-as-oracle).
        with pytest.raises(NotApprovableError):
            await approve(session, draft_id, reviewer_id=REVIEWER)
        await session.rollback()

        await reject(session, draft_id, reviewer_id=REVIEWER, reason="not a real role")
        await session.commit()

    async with session_maker() as session:
        again = await run_canonical_producer(session, client=None)
        await session.commit()
        assert again.skipped_reviewer_touched == 1
        assert again.drafts_persisted == 0
        row = await session.get(CanonicalJD, draft_id)
        assert row is not None and row.status is CanonicalStatus.ARCHIVED


@pytest.mark.asyncio
async def test_the_producer_no_clobber_resolves_to_the_latest_version(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    """Acceptance #6 producer half, MUTATION-pinned. Two untouched DRAFT versions exist
    for the cluster; the producer must refresh the NEWEST (v2), leaving v1 alone. Drop
    the
    ``order_by(version desc)`` on the no-clobber lookup and the producer resolves to v1
    —
    it refreshes v1 and leaves v2 stale → RED."""
    cluster_id = cluster_id_for(["a", "b"])
    sentinel_v1 = {"title": "STALE V1 — must be left alone"}
    sentinel_v2 = {"title": "STALE V2 — the latest, must be refreshed"}
    async with session_maker() as session:
        await _seed_producer_cluster(session)
        await _seed_canonical(
            session, content=sentinel_v1, version=1, cluster_id=cluster_id
        )
        await _seed_canonical(
            session, content=sentinel_v2, version=2, cluster_id=cluster_id
        )
        await session.commit()

        result = await run_canonical_producer(session, client=None)
        await session.commit()
        assert result.drafts_refreshed == 1
        assert result.drafts_persisted == 0

    async with session_maker() as session:
        rows = {
            row.version: row
            for row in (await session.scalars(select(CanonicalJD))).all()
        }
        assert set(rows) == {1, 2}  # no v3 minted
        assert rows[1].content == sentinel_v1  # the older version left untouched
        assert rows[2].content != sentinel_v2  # the LATEST version was refreshed
        assert rows[2].content["title"] == "Analyst"  # to the real merge draft

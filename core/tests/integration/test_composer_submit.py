"""Integration (Phase 5.6) — a composed draft enters the REAL review queue and moves
through the real 4.4b human-approval spine, against a real Postgres.

What only a real database + the real service prove:

1. ``submit_composed_draft`` persists a DRAFT ``canonical_jds`` row (its own synthetic
   ``origin="composed"`` cluster) + an append-only ``canonical_draft.composed`` audit
   row; nothing is published (NN #1).
2. The composed draft shows up in ``list_review_queue`` like any other draft.
3. A clean composed JD is APPROVABLE through the real ``approve`` (→ PUBLISHED); an
   incomplete one RAISES ``NotApprovableError`` and stays DRAFT — the builder's live
   verdict and the queue agree because both flatten with ``flatten_jd``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from testcontainers.postgres import PostgresContainer

from src.jd_bank.composer import submit_composed_draft
from src.jd_bank.db.models import (
    AuditLog,
    CanonicalJD,
    CanonicalStatus,
    Cluster,
)
from src.jd_bank.review import NotApprovableError, approve, list_review_queue
from src.jd_core.models.parsed_jd import (
    SFUDuty,
    SFUJobDescription,
    SFUQualification,
    SFURelationships,
)
from tests.integration.test_dedup_tier1 import ALEMBIC_INI

AUTHOR = "hiring-manager-1"
REVIEWER = "hr-reviewer"


def _clean_jd() -> SFUJobDescription:
    """A fully-authored, approvable JD (the 2.3 gate suite's baseline recipe)."""
    return SFUJobDescription(
        title="Software Developer",
        employee_group="apsa",
        about_sfu_present=True,
        position_summary=" ".join(["word"] * 120),
        duties=[
            SFUDuty(action_verb=verb, statement=f"{verb} the program")
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


async def test_a_composed_draft_enters_the_queue_and_can_be_approved(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    async with session_maker() as session:
        canonical = await submit_composed_draft(session, _clean_jd(), author_id=AUTHOR)
        await session.commit()
        canonical_id = canonical.id

    async with session_maker() as session:
        # DRAFT, origin=composed cluster, no sources, append-only audit row.
        row = await session.get(CanonicalJD, canonical_id)
        assert row is not None
        assert row.status is CanonicalStatus.DRAFT
        assert row.source_document_ids == []
        assert row.change_log["origin"] == "composed"
        cluster = await session.get(Cluster, row.cluster_id)
        assert cluster is not None
        assert cluster.constraint_metadata["origin"] == "composed"
        assert cluster.members == []
        audits = (
            await session.scalars(
                select(AuditLog).where(
                    AuditLog.event_type == "canonical_draft.composed"
                )
            )
        ).all()
        assert len(audits) == 1
        assert audits[0].actor == AUTHOR

        # It is in the queue like any other draft.
        queue = await list_review_queue(session)
        assert canonical_id in {item.canonical_id for item in queue}

        # And the clean draft is approvable through the real service (→ PUBLISHED).
        published = await approve(session, canonical_id, reviewer_id=REVIEWER)
        await session.commit()
        assert published.status is CanonicalStatus.PUBLISHED


async def test_a_non_approvable_composed_draft_stays_draft(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    async with session_maker() as session:
        canonical = await submit_composed_draft(
            session, SFUJobDescription(title="Half-written role"), author_id=AUTHOR
        )
        await session.commit()
        canonical_id = canonical.id

    async with session_maker() as session:
        queue = await list_review_queue(session)
        assert canonical_id in {item.canonical_id for item in queue}
        with pytest.raises(NotApprovableError):
            await approve(session, canonical_id, reviewer_id=REVIEWER)

    async with session_maker() as session:
        row = await session.get(CanonicalJD, canonical_id)
        assert row is not None
        assert row.status is CanonicalStatus.DRAFT

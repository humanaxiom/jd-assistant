"""Integration (Phase 5.9) — the authoring guard's two SQL reads, against real Postgres.

``test_composer_duplicates.py`` drives :func:`find_related_roles` with the DB seams
monkeypatched, which is the right place to pin the guard's *behaviour* (degrade paths,
CUPE scoping, the cap, the absence of a score). It cannot prove the SQL. These can, and
they are the parts that only a real database decides:

* the title pass is CASE-INSENSITIVE and reads the CURRENT version only — a role
  renamed by harmonization must not still collide on the title it used to have (the
  ``d71e333`` / ``3b6a71b`` family of bugs, in a new place);
* it is JDFN-scoped: a CUPE role is never offered as a clone source (HR-143);
* the batched resolution really is ONE query returning the CURRENT title + status, so a
  role approved (or renamed) after it was embedded is labelled by what Postgres says
  today, not by the stale ``(:JDRole)`` snapshot;
* ``find_related_roles`` end-to-end with **no embedding client and no Neo4j driver at
  all** — the "GPU is down, the Builder still gets its panel" contract, run against a
  real database rather than a fake session.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from testcontainers.postgres import PostgresContainer

from src.jd_bank.composer import load_role_clone_answers
from src.jd_bank.composer.duplicates import (
    _current_role_rows,
    _title_collision_matches,
    find_related_roles,
)
from src.jd_bank.db.models import CanonicalJD, CanonicalStatus, Cluster
from src.jd_core.models.parsed_jd import SFUJobDescription
from src.jd_core.models.quality import DEFAULT_TEMPLATE
from src.jd_core.rules import get_rules
from tests.integration.test_dedup_tier1 import ALEMBIC_INI

#: The WJQ scope the production code resolves from the rulebook (HR-225). Read from the
#: rulebook rather than written as {"cupe"} so this cannot drift from the shipped value.
_WJQ_GROUPS = frozenset(get_rules().segmentation.wjq_employee_groups)


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
        await conn.execute(text("DELETE FROM clusters"))
    maker = async_sessionmaker(engine, expire_on_commit=False)
    yield maker
    await engine.dispose()


def _content(title: str, **extra: Any) -> dict[str, Any]:
    jd = SFUJobDescription(title=title, employee_group="apsa", **extra)
    return jd.model_dump(mode="json")


async def _seed(session: AsyncSession) -> dict[str, uuid.UUID]:
    """Four roles, each probing one thing the SQL has to get right."""
    ids = {
        name: uuid.uuid4()
        for name in ("advising", "science", "renamed", "cupe", "archived")
    }
    for cluster_id in ids.values():
        session.add(Cluster(id=cluster_id))

    # A published role, on its SECOND version — the current one is what must be read.
    session.add(
        CanonicalJD(
            cluster_id=ids["advising"],
            version=1,
            status=CanonicalStatus.DRAFT,
            content=_content("Academic Advisor", department="Old Department"),
        )
    )
    session.add(
        CanonicalJD(
            cluster_id=ids["advising"],
            version=2,
            status=CanonicalStatus.PUBLISHED,
            content=_content("Academic Advisor", department="Student Advising"),
        )
    )
    # A DRAFT role with the same title in different case, in another department.
    session.add(
        CanonicalJD(
            cluster_id=ids["science"],
            version=1,
            status=CanonicalStatus.DRAFT,
            content=_content("academic advisor", department="Faculty of Science"),
        )
    )
    # Harmonization RENAMED this role: v1 held the colliding title, v2 does not.
    session.add(
        CanonicalJD(
            cluster_id=ids["renamed"],
            version=1,
            status=CanonicalStatus.DRAFT,
            content=_content("Academic Advisor", department="Continuing Studies"),
        )
    )
    session.add(
        CanonicalJD(
            cluster_id=ids["renamed"],
            version=2,
            status=CanonicalStatus.DRAFT,
            content=_content("Advising Coordinator", department="Continuing Studies"),
        )
    )
    # CUPE/WJQ: never a JDFN clone source (HR-143).
    cupe = SFUJobDescription(title="Academic Advisor", employee_group="cupe")
    session.add(
        CanonicalJD(
            cluster_id=ids["cupe"],
            version=1,
            status=CanonicalStatus.PUBLISHED,
            content=cupe.model_dump(mode="json"),
        )
    )
    # ARCHIVED: settled, and not what the Bank holds today — offered nowhere, and not
    # counted in "SFU already has N roles titled X".
    session.add(
        CanonicalJD(
            cluster_id=ids["archived"],
            version=1,
            status=CanonicalStatus.ARCHIVED,
            content=_content("Academic Advisor", department="Archives"),
        )
    )
    await session.commit()
    return ids


async def test_the_title_pass_is_case_insensitive_current_version_and_jdfn_scoped(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    async with session_maker() as session:
        ids = await _seed(session)
        matches = await _title_collision_matches(
            session,
            "  ACADEMIC ADVISOR  ",
            wjq_groups=_WJQ_GROUPS,
            form=DEFAULT_TEMPLATE,
        )

    by_cluster = {row[0]: row for row in matches}
    # The renamed role does NOT collide on the title it no longer carries, the CUPE
    # role is not offered at all, and neither is the ARCHIVED one.
    assert set(by_cluster) == {ids["advising"], ids["science"]}
    # ...and the row carries the CURRENT version's department + status, not v1's.
    assert by_cluster[ids["advising"]][1:] == (
        "Academic Advisor",
        "Student Advising",
        "published",
    )
    assert by_cluster[ids["science"]][1:] == (
        "academic advisor",
        "Faculty of Science",
        "draft",
    )


async def test_a_title_nobody_holds_collides_with_nothing(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    async with session_maker() as session:
        await _seed(session)
        assert (
            await _title_collision_matches(
                session,
                "Underwater Basket Weaver",
                wjq_groups=_WJQ_GROUPS,
                form=DEFAULT_TEMPLATE,
            )
            == []
        )
        # ...and a blank title never reaches the database at all.
        assert (
            await _title_collision_matches(
                session, "   ", wjq_groups=_WJQ_GROUPS, form=DEFAULT_TEMPLATE
            )
            == []
        )


async def test_the_batched_resolution_returns_the_current_title_and_status(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    """What the ``(:JDRole)`` snapshot cannot tell you: this role was renamed and this
    one was approved AFTER they were embedded."""
    async with session_maker() as session:
        ids = await _seed(session)
        rows = await _current_role_rows(
            session, [ids["renamed"], ids["advising"], ids["renamed"]]
        )

    assert rows == {
        ids["renamed"]: ("Advising Coordinator", "Continuing Studies", "draft"),
        ids["advising"]: ("Academic Advisor", "Student Advising", "published"),
    }


async def test_the_guard_answers_with_no_embed_client_and_no_neo4j_driver(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    """The whole point of splitting the passes: with the inference host unreachable the
    Builder still gets the honest, non-vector half of its panel."""
    async with session_maker() as session:
        ids = await _seed(session)
        guard = await find_related_roles(
            SFUJobDescription(title="Academic Advisor", employee_group="apsa"),
            session=session,
            embed_client=None,
            neo4j_driver=None,
            exclude_cluster_id=ids["science"],
        )

    assert guard.checked is True
    assert [role.cluster_id for role in guard.title_collisions] == [ids["advising"]]
    # The cloned-from role is excluded from the LIST but still counted in the FACT
    # (2 = advising + science), and both departments are named.
    assert guard.same_title_count == 2
    assert set(guard.departments) == {"Student Advising", "Faculty of Science"}
    assert guard.related == []


async def test_cloning_a_role_records_which_role_it_came_from(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    """The lineage the Builder carries through the form and hands the guard as
    ``exclude_cluster_id``. Read from the CURRENT canonical, like the rest of the
    clone path — and untested until now."""
    async with session_maker() as session:
        ids = await _seed(session)
        answers = await load_role_clone_answers(session, ids["renamed"])

    assert answers is not None
    assert answers.title == "Advising Coordinator"  # the current version, not v1
    assert answers.cloned_from_cluster_id == ids["renamed"]


async def test_an_archived_role_is_never_a_title_collision(
    session_maker: async_sessionmaker[AsyncSession],
) -> None:
    """``802bff0`` refuses to edit an archived version because "rejected or superseded
    is settled". It is equally not something to clone, and equally not something to
    count in "SFU already has N roles with this title"."""
    async with session_maker() as session:
        ids = await _seed(session)
        matches = await _title_collision_matches(
            session, "Academic Advisor", wjq_groups=_WJQ_GROUPS, form=DEFAULT_TEMPLATE
        )

    assert ids["archived"] not in {row[0] for row in matches}
    assert "Archives" not in {row[2] for row in matches}

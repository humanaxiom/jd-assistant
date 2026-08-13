"""Phase 5.9 — the near-duplicate AUTHORING guard (advisory, ranked, score-free).

**Why this shape.** Measured against the live ``jd_role_embeddings`` index before this
was specified: a cosine threshold does NOT separate duplicates from unrelated roles —
same-title role pairs median 0.9335 cosine while the nearest UNRELATED role medians
0.9604. At a 0.90 cutoff the guard would fire on 99.2% of drafts at 22% precision. So
the guard shows a RANKED list (a same-title sibling is top-5 for 76% of roles) and
renders NO score, NO percentage, NO similarity number anywhere — the absolute number
is meaningless even though the ranking is good. See ``test_related_role_never_
carries_a_similarity_number`` — the pin that stops a future contributor "helpfully"
re-adding one.

Advisory only (NN #1): nothing here blocks submission or auto-publishes; it only helps
an author find the harmonized role to CLONE instead of authoring SFU's 10th "Academic
Advisor".

Two independent seams are exercised, both driven against the REAL ``find_related_
roles`` (never re-derived/re-implemented here):

* the title-collision pass (roles sharing the draft's exact title, case-insensitive,
  current version only) — needs no embedding client or Neo4j driver at all, so it
  keeps working with the GPU down.
* the semantic "related" pass — reuses ``jd_bank.composer.search``'s already-tested
  ``_nearest_role_ids`` (HR-143 CUPE scoping and all) and ``_role_departments``, the
  same pieces ``search_similar_jds`` is built from.

Test-seam note for the Coder (so the monkeypatches below actually intercept the call):
``duplicates.py`` must call the reused search-module helpers via a MODULE-QUALIFIED
reference (``search_mod._nearest_role_ids(...)``, ``search_mod._role_departments(...)``
where ``search_mod`` is ``from src.jd_bank.composer import search as search_mod``), not
a rebound top-level ``from ... import _nearest_role_ids`` — the latter would not observe
a ``monkeypatch.setattr(search_mod, "_nearest_role_ids", fake)`` done from this file
(exactly the convention ``search.py`` itself already relies on for its own callers).
The title-collision DB read is expected as a new private ``duplicates_mod.
_title_collision_matches(session, title) -> list[tuple[UUID, str, str | None, str]]``
(``cluster_id, title, department, status``) — new code, so it is monkeypatched at its
own module.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import ValidationError

from src.jd_bank.composer import duplicates as duplicates_mod
from src.jd_bank.composer import search as search_mod
from src.jd_bank.composer.duplicates import (
    DuplicateGuard,
    RelatedRole,
    find_related_roles,
)
from src.jd_core.bank.embed_text import SerializedText
from src.jd_core.models.parsed_jd import SFUDuty, SFUJobDescription
from src.jd_core.rules import get_rules
from tests.unit.retuned_rules import retuned_dedup


def _rules_with_guard(**overrides: Any) -> Any:
    base: dict[str, Any] = {
        "max_matches": 5,
        "min_draft_chars": 500,
        "timeout_seconds": 5.0,
    }
    base.update(overrides)
    return retuned_dedup(get_rules(), authoring_guard=base)


def _long_draft(title: str = "Academic Advisor") -> SFUJobDescription:
    """A realistic, well-over-500-char draft — long enough to clear the shipped
    ``min_draft_chars`` (500) so the semantic pass actually runs."""
    summary = (
        "Provides comprehensive academic advising to undergraduate students, "
        "interpreting university and faculty regulations, degree requirements, "
        "and program options for a diverse caseload. "
    ) * 6
    return SFUJobDescription(
        title=title,
        department="Student Services",
        employee_group="apsa",
        position_summary=summary,
        duties=[
            SFUDuty(
                action_verb="Advises",
                statement=(
                    "Advises students on course selection and degree progress "
                    "toward graduation"
                ),
            ),
            SFUDuty(
                action_verb="Interprets",
                statement=(
                    "Interprets faculty and university academic regulations for "
                    "individual student cases"
                ),
            ),
            SFUDuty(
                action_verb="Coordinates",
                statement=(
                    "Coordinates referrals to specialized student support "
                    "services across campus"
                ),
            ),
        ],
    )


def _short_draft(title: str = "Academic Advisor") -> SFUJobDescription:
    return SFUJobDescription(
        title=title, employee_group="apsa", position_summary="Short summary."
    )


def _blank_draft(title: str = "Academic Advisor") -> SFUJobDescription:
    """Serializes to `""` — every ``embeddings.yaml: document_sections`` entry is
    empty (the 34.5% WJQ-template gap's JDFN mirror: a draft with nothing written
    yet)."""
    return SFUJobDescription(title=title, employee_group="apsa")


class _FakeRow:
    """One ``canonical_jds`` row as the guard reads it: JSONB ``content`` plus a
    ``status`` enum member."""

    def __init__(
        self,
        cluster_id: uuid.UUID,
        title: str,
        *,
        status: str = "published",
        department: str | None = None,
    ) -> None:
        self.cluster_id = cluster_id
        self.content: dict[str, Any] = {"title": title}
        if department is not None:
            self.content["department"] = department
        self.status = SimpleNamespace(value=status)


class _FakeResult:
    def __init__(self, rows: list[_FakeRow]) -> None:
        self._rows = rows

    def scalars(self) -> list[_FakeRow]:
        return self._rows


class _FakeSession:
    """A session that answers the guard's CURRENT-canonical read.

    Deliberately returns every seeded row for any statement: this stands in for
    Postgres so the guard's own resolution logic (which title/status/department a row
    carries, which hit has no row at all) is exercised in-process. That the SQL really
    selects the current version, case-insensitively, JDFN-scoped, is proved against a
    real database in ``tests/integration/test_composer_duplicates_db.py`` — the two
    are complementary, and neither substitutes for the other.
    """

    def __init__(self, *rows: _FakeRow) -> None:
        self._rows = list(rows)
        self.executed = 0

    async def execute(self, statement: Any) -> _FakeResult:
        self.executed += 1
        return _FakeResult(self._rows)


class _FakeEmbed:
    def __init__(
        self, vector: list[float] | None = None, *, raises: bool = False
    ) -> None:
        self._vector = vector or [0.1] * 768
        self._raises = raises
        self.calls: list[list[str]] = []

    async def embed_batch(self, texts: Any) -> list[list[float]]:
        self.calls.append(list(texts))
        if self._raises:
            raise RuntimeError("aria-gb10-2 unreachable")
        return [self._vector]


class _ExplodingDriver:
    """Mirrors ``test_composer_search.py``'s ``_ExplodingDriver`` — a stack where
    migration 003 / ``make embed-roles`` has not run yet raises on ``.session()``."""

    def session(self) -> Any:
        raise RuntimeError("There is no such vector schema index: jd_role_embeddings")


async def _no_title_collisions(session: Any, title: str) -> list[Any]:
    return []


async def _no_departments(session: Any, ids: Any) -> dict[Any, Any]:
    return {}


# --- 1. title-collision pass needs no GPU at all --------------------------------


async def test_title_collision_pass_needs_no_embed_client_or_driver(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    advising, science = uuid.uuid4(), uuid.uuid4()

    async def fake_collisions(session: Any, title: str) -> list[Any]:
        assert title == "Academic Advisor"
        return [
            (advising, "Academic Advisor", "Student Advising", "published"),
            (science, "Academic Advisor", "Faculty of Science", "published"),
        ]

    monkeypatch.setattr(duplicates_mod, "_title_collision_matches", fake_collisions)

    guard = await find_related_roles(
        _long_draft(),
        session=object(),  # type: ignore[arg-type]
        embed_client=None,
        neo4j_driver=None,
    )

    assert isinstance(guard, DuplicateGuard)
    assert guard.checked is True
    assert {r.cluster_id for r in guard.title_collisions} == {advising, science}
    assert all(r.reason == "title_collision" for r in guard.title_collisions)
    assert guard.same_title_count == 2
    assert set(guard.departments) == {"Student Advising", "Faculty of Science"}
    assert guard.related == []


# --- 2. a too-short draft never embeds ------------------------------------------


async def test_a_short_draft_never_embeds(monkeypatch: pytest.MonkeyPatch) -> None:
    """States its own precondition: at a LOW ``min_draft_chars`` the SAME draft's
    serialized text clears the bar and DOES embed — proving the high-threshold run
    below is skipped BECAUSE of the configured threshold, not because the draft
    happens to have nothing to embed."""
    monkeypatch.setattr(
        duplicates_mod, "_title_collision_matches", _no_title_collisions
    )
    draft = _short_draft()

    low_embed = _FakeEmbed()
    await find_related_roles(
        draft,
        session=object(),  # type: ignore[arg-type]
        embed_client=low_embed,  # type: ignore[arg-type]
        neo4j_driver=object(),  # type: ignore[arg-type]
        rules=_rules_with_guard(min_draft_chars=5),
    )
    assert len(low_embed.calls) == 1  # precondition: this draft IS embeddable

    high_embed = _FakeEmbed()
    guard = await find_related_roles(
        draft,
        session=object(),  # type: ignore[arg-type]
        embed_client=high_embed,  # type: ignore[arg-type]
        neo4j_driver=object(),  # type: ignore[arg-type]
        rules=_rules_with_guard(min_draft_chars=500),
    )
    assert high_embed.calls == []
    assert guard.related == []


# --- 3. an empty serialized draft never embeds ----------------------------------


async def test_a_whitespace_only_draft_never_embeds_however_long_it_is(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LOAD-BEARING. Ollama embeds ``""`` into a constant vector that is a nearest
    neighbour to EVERYTHING — measured live, every empty query returned the
    identical role at a 0.8038 score. An empty/whitespace serialized draft must never
    reach the embedding client, and that refusal must be INDEPENDENT of
    ``min_draft_chars``.

    Proved by making the serialization 600 characters of whitespace — comfortably OVER
    the shipped floor of 500, so the length check cannot be what stops it and the
    strip-check is the only thing standing between this draft and the embedding
    endpoint. (Deleting that check makes this test embed, which is the mutation
    sensitivity the old version lost: it fed a draft that serialized to ``''``
    exactly, where the length check would have caught it anyway at any positive
    floor.)"""
    monkeypatch.setattr(
        duplicates_mod, "_title_collision_matches", _no_title_collisions
    )
    monkeypatch.setattr(
        duplicates_mod,
        "serialize_document",
        lambda jd, rules: SerializedText(" " * 600, 600, False, "sha"),
    )
    embed = _FakeEmbed()

    guard = await find_related_roles(
        _blank_draft(),
        session=object(),  # type: ignore[arg-type]
        embed_client=embed,  # type: ignore[arg-type]
        neo4j_driver=object(),  # type: ignore[arg-type]
        rules=_rules_with_guard(),  # the SHIPPED floor of 500 — not lowered
    )
    assert embed.calls == []
    assert guard.related == []


def test_the_authoring_guard_floor_cannot_be_switched_off_in_the_rulebook() -> None:
    """The other half of the refusal above: ``min_draft_chars`` is a length, and the
    loader model — not a validator somewhere above it — is what says so. That matters
    because ``retuned_rules.py`` promises a fixture built through it is rejected
    "exactly as it would be at load"; a field that validated at a different level
    would quietly break that promise for every suite that uses the fixture."""
    for refused in (0, -1):
        with pytest.raises(ValidationError):
            _rules_with_guard(min_draft_chars=refused)


# --- 4. a raising Neo4j driver degrades -----------------------------------------


async def test_a_raising_neo4j_driver_degrades_the_related_pass_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    collision = uuid.uuid4()

    async def fake_collisions(session: Any, title: str) -> list[Any]:
        return [(collision, "Academic Advisor", "Student Advising", "published")]

    monkeypatch.setattr(duplicates_mod, "_title_collision_matches", fake_collisions)

    guard = await find_related_roles(
        _long_draft(),
        session=object(),  # type: ignore[arg-type]
        embed_client=_FakeEmbed(),  # type: ignore[arg-type]
        neo4j_driver=_ExplodingDriver(),  # type: ignore[arg-type]
        rules=_rules_with_guard(),
    )
    assert [r.cluster_id for r in guard.title_collisions] == [collision]
    assert guard.related == []


# --- 5. a raising embed client degrades -----------------------------------------


async def test_a_raising_embed_client_degrades_the_related_pass_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The Builder must never lose its compliance panel because the GPU is down."""
    collision = uuid.uuid4()

    async def fake_collisions(session: Any, title: str) -> list[Any]:
        return [(collision, "Academic Advisor", "Student Advising", "published")]

    monkeypatch.setattr(duplicates_mod, "_title_collision_matches", fake_collisions)

    guard = await find_related_roles(
        _long_draft(),
        session=object(),  # type: ignore[arg-type]
        embed_client=_FakeEmbed(raises=True),  # type: ignore[arg-type]
        neo4j_driver=object(),  # type: ignore[arg-type]
        rules=_rules_with_guard(),
    )
    assert [r.cluster_id for r in guard.title_collisions] == [collision]
    assert guard.related == []


# --- 6. CUPE is excluded from `related` (HR-143) --------------------------------


async def test_cupe_roles_are_excluded_from_related(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """...and the row that survives is labelled from POSTGRES, not from the vector
    node: the node's ``title``/``status`` are a snapshot from embed time, so this
    seeds the database with a title and status the node does not have and requires
    the panel to show those."""
    apsa_role, cupe_role = uuid.uuid4(), uuid.uuid4()

    async def fake_nearest(
        driver: Any, vector: Any, k: int, *, live_stamp: str
    ) -> list[Any]:
        return [
            (apsa_role, "Academic Advisor", "apsa", 0.93),
            (cupe_role, "Clerk", "cupe", 0.95),
        ]

    monkeypatch.setattr(
        duplicates_mod, "_title_collision_matches", _no_title_collisions
    )
    monkeypatch.setattr(search_mod, "_nearest_role_ids", fake_nearest)
    monkeypatch.setattr(search_mod, "_role_departments", _no_departments)
    session = _FakeSession(
        # RENAMED and still a DRAFT since the node was written.
        _FakeRow(
            apsa_role,
            "Academic Advising Specialist",
            status="draft",
            department="Student Advising",
        )
    )

    guard = await find_related_roles(
        _long_draft(),
        session=session,  # type: ignore[arg-type]
        embed_client=_FakeEmbed(),  # type: ignore[arg-type]
        neo4j_driver=object(),  # type: ignore[arg-type]
        rules=_rules_with_guard(),
    )
    assert [r.cluster_id for r in guard.related] == [apsa_role]
    hit = guard.related[0]
    assert hit.title == "Academic Advising Specialist"  # NOT the node's snapshot
    assert hit.status == "draft"
    assert hit.department == "Student Advising"
    assert hit.clonable is True


async def test_a_hit_with_no_current_canonical_is_shown_but_not_clonable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A ``(:JDRole)`` node outlives the canonical it was built from until
    ``prune_roles`` catches up, so this is reachable. The role is still real, so the
    row shows — with the node's title and an honestly UNKNOWN status — but it carries
    no "Start from this role" link, because ``clone_role`` would 404 on it."""
    orphan = uuid.uuid4()

    async def fake_nearest(
        driver: Any, vector: Any, k: int, *, live_stamp: str
    ) -> list[Any]:
        return [(orphan, "Advising Coordinator", "apsa", 0.94)]

    monkeypatch.setattr(
        duplicates_mod, "_title_collision_matches", _no_title_collisions
    )
    monkeypatch.setattr(search_mod, "_nearest_role_ids", fake_nearest)
    monkeypatch.setattr(search_mod, "_role_departments", _no_departments)

    guard = await find_related_roles(
        _long_draft(),
        session=_FakeSession(),  # no canonical rows at all
        embed_client=_FakeEmbed(),  # type: ignore[arg-type]
        neo4j_driver=object(),  # type: ignore[arg-type]
        rules=_rules_with_guard(),
    )
    assert [r.cluster_id for r in guard.related] == [orphan]
    assert guard.related[0].title == "Advising Coordinator"
    assert guard.related[0].status == duplicates_mod.UNKNOWN_STATUS
    assert guard.related[0].clonable is False


async def test_archived_roles_are_never_offered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``802bff0`` refuses to EDIT an archived version because "rejected or superseded
    is settled"; offering to CLONE one would contradict that. Archived roles are
    dropped from ``related``, and from the title pass's count and list."""
    archived, live = uuid.uuid4(), uuid.uuid4()

    async def fake_nearest(
        driver: Any, vector: Any, k: int, *, live_stamp: str
    ) -> list[Any]:
        return [
            (archived, "Academic Advisor", "apsa", 0.95),
            (live, "Advising Coordinator", "apsa", 0.94),
        ]

    monkeypatch.setattr(
        duplicates_mod, "_title_collision_matches", _no_title_collisions
    )
    monkeypatch.setattr(search_mod, "_nearest_role_ids", fake_nearest)
    monkeypatch.setattr(search_mod, "_role_departments", _no_departments)
    session = _FakeSession(
        _FakeRow(archived, "Academic Advisor", status="archived"),
        _FakeRow(live, "Advising Coordinator", status="published"),
    )

    guard = await find_related_roles(
        _long_draft(),
        session=session,  # type: ignore[arg-type]
        embed_client=_FakeEmbed(),  # type: ignore[arg-type]
        neo4j_driver=object(),  # type: ignore[arg-type]
        rules=_rules_with_guard(),
    )
    assert [r.cluster_id for r in guard.related] == [live]


async def test_archived_hits_do_not_cost_the_panel_its_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The cap is applied to what SURVIVED the filters, not to the raw neighbour list.

    Applying it first is the tempting order and it silently under-advises: with
    ``max_matches=3`` and two of the top three archived, the panel showed ONE row while
    three live candidates were available. ``_OVERFETCH`` exists so that filtering costs
    headroom, not results.
    """
    ids = [uuid.uuid4() for _ in range(6)]

    async def fake_nearest(
        driver: Any, vector: Any, k: int, *, live_stamp: str
    ) -> list[Any]:
        return [
            (cid, f"Academic Advisor {n}", "apsa", 0.95) for n, cid in enumerate(ids)
        ]

    monkeypatch.setattr(
        duplicates_mod, "_title_collision_matches", _no_title_collisions
    )
    monkeypatch.setattr(search_mod, "_nearest_role_ids", fake_nearest)
    monkeypatch.setattr(search_mod, "_role_departments", _no_departments)
    # The two archived rows sit INSIDE the top three, so a cap-then-filter order can
    # only yield one row.
    session = _FakeSession(
        *(
            _FakeRow(
                cid,
                f"Academic Advisor {n}",
                status="archived" if n in (0, 1) else "published",
            )
            for n, cid in enumerate(ids)
        )
    )

    guard = await find_related_roles(
        _long_draft(),
        session=session,  # type: ignore[arg-type]
        embed_client=_FakeEmbed(),  # type: ignore[arg-type]
        neo4j_driver=object(),  # type: ignore[arg-type]
        rules=_rules_with_guard(max_matches=3),
    )
    assert [r.cluster_id for r in guard.related] == ids[2:5]


# --- 7. exclude_cluster_id appears in neither list ------------------------------


async def test_exclude_cluster_id_is_never_offered_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cloning a role must not immediately warn you that you duplicated the role
    you cloned."""
    cloned_from, other_collision, other_related = (uuid.uuid4() for _ in range(3))

    async def fake_collisions(session: Any, title: str) -> list[Any]:
        return [
            (cloned_from, "Academic Advisor", "Student Advising", "published"),
            (other_collision, "Academic Advisor", "Faculty of Science", "published"),
        ]

    async def fake_nearest(
        driver: Any, vector: Any, k: int, *, live_stamp: str
    ) -> list[Any]:
        return [
            (cloned_from, "Academic Advisor", "apsa", 0.95),
            (other_related, "Advising Coordinator", "apsa", 0.93),
        ]

    monkeypatch.setattr(duplicates_mod, "_title_collision_matches", fake_collisions)
    monkeypatch.setattr(search_mod, "_nearest_role_ids", fake_nearest)
    monkeypatch.setattr(search_mod, "_role_departments", _no_departments)
    session = _FakeSession(
        _FakeRow(other_related, "Advising Coordinator", department="Student Advising")
    )

    guard = await find_related_roles(
        _long_draft(),
        session=session,  # type: ignore[arg-type]
        embed_client=_FakeEmbed(),  # type: ignore[arg-type]
        neo4j_driver=object(),  # type: ignore[arg-type]
        rules=_rules_with_guard(),
        exclude_cluster_id=cloned_from,
    )
    all_ids = {r.cluster_id for r in guard.title_collisions} | {
        r.cluster_id for r in guard.related
    }
    assert cloned_from not in all_ids
    assert other_collision in {r.cluster_id for r in guard.title_collisions}
    assert other_related in {r.cluster_id for r in guard.related}
    # ...but the cloned-from role IS still counted: the sentence states a FACT about
    # how many roles carry this title, and excluding it would under-report by one.
    assert guard.same_title_count == 2
    assert set(guard.departments) == {"Student Advising", "Faculty of Science"}


async def test_the_same_title_count_is_the_true_total_not_the_listed_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The one number the panel states as a fact rather than a distance. It is neither
    capped by ``max_matches`` nor reduced by the cloned-from exclusion — an author
    cloning one of SFU's 9 "Academic Advisor" roles must be told there are 9."""
    ids = [uuid.uuid4() for _ in range(9)]

    async def fake_collisions(session: Any, title: str) -> list[Any]:
        return [
            (cluster_id, "Academic Advisor", f"Department {i % 6}", "published")
            for i, cluster_id in enumerate(ids)
        ]

    monkeypatch.setattr(duplicates_mod, "_title_collision_matches", fake_collisions)

    guard = await find_related_roles(
        _long_draft(),
        session=object(),  # type: ignore[arg-type]
        embed_client=None,
        neo4j_driver=None,
        rules=_rules_with_guard(max_matches=5),
        exclude_cluster_id=ids[0],
    )
    assert guard.same_title_count == 9  # the fact
    assert len(guard.departments) == 6  # ...and its department count, also uncapped
    assert len(guard.title_collisions) == 5  # the advice, capped like `related` (N-6)
    assert ids[0] not in {r.cluster_id for r in guard.title_collisions}


# --- 8. no role is listed twice --------------------------------------------------


async def test_a_role_in_title_collisions_is_not_repeated_in_related(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shared, only_related = uuid.uuid4(), uuid.uuid4()

    async def fake_collisions(session: Any, title: str) -> list[Any]:
        return [(shared, "Academic Advisor", "Student Advising", "published")]

    async def fake_nearest(
        driver: Any, vector: Any, k: int, *, live_stamp: str
    ) -> list[Any]:
        return [
            (shared, "Academic Advisor", "apsa", 0.95),
            (only_related, "Advising Coordinator", "apsa", 0.90),
        ]

    monkeypatch.setattr(duplicates_mod, "_title_collision_matches", fake_collisions)
    monkeypatch.setattr(search_mod, "_nearest_role_ids", fake_nearest)
    monkeypatch.setattr(search_mod, "_role_departments", _no_departments)
    session = _FakeSession(_FakeRow(only_related, "Advising Coordinator"))

    guard = await find_related_roles(
        _long_draft(),
        session=session,  # type: ignore[arg-type]
        embed_client=_FakeEmbed(),  # type: ignore[arg-type]
        neo4j_driver=object(),  # type: ignore[arg-type]
        rules=_rules_with_guard(),
    )
    assert [r.cluster_id for r in guard.title_collisions] == [shared]
    assert [r.cluster_id for r in guard.related] == [only_related]


# --- 9. max_matches is honoured and comes from rules ----------------------------


async def test_max_matches_caps_the_related_list_and_comes_from_rules(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    neighbours = [(uuid.uuid4(), f"Role {i}", "apsa", 0.9 - i * 0.01) for i in range(6)]

    async def fake_nearest(
        driver: Any, vector: Any, k: int, *, live_stamp: str
    ) -> list[Any]:
        return neighbours

    monkeypatch.setattr(
        duplicates_mod, "_title_collision_matches", _no_title_collisions
    )
    monkeypatch.setattr(search_mod, "_nearest_role_ids", fake_nearest)
    monkeypatch.setattr(search_mod, "_role_departments", _no_departments)
    session = _FakeSession(
        *(_FakeRow(cluster_id, title) for cluster_id, title, _, _ in neighbours)
    )

    guard = await find_related_roles(
        _long_draft(),
        session=session,  # type: ignore[arg-type]
        embed_client=_FakeEmbed(),  # type: ignore[arg-type]
        neo4j_driver=object(),  # type: ignore[arg-type]
        rules=_rules_with_guard(max_matches=2),
    )
    assert len(guard.related) == 2
    assert all(role.clonable for role in guard.related)


# --- 10. the deliberate absence of a score is pinned ----------------------------


def test_no_panel_model_ever_carries_a_similarity_number() -> None:
    """A future contributor "helpfully" adding a ``score`` (or ``similarity``, or
    ``percent``/``pct``) field to the panel must turn this suite red: measured on
    the live index, same-title role pairs median 0.9335 cosine while the nearest
    UNRELATED role medians 0.9604 — a score column would look precise and mean
    nothing.

    BOTH models, not just the row: a ``DuplicateGuard.top_score`` would reach the
    template just as easily as a ``RelatedRole.score`` and slipped through while this
    checked only one of them."""
    forbidden = ("score", "similar", "percent", "pct")
    for model in (RelatedRole, DuplicateGuard):
        for name in model.model_fields:
            lowered = name.lower()
            assert not any(bad in lowered for bad in forbidden), (
                f"{model.__name__} must never expose a similarity number — found "
                f"suspicious field {name!r}."
            )

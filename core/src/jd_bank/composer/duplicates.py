"""The near-duplicate AUTHORING guard (Phase 5.9) — advisory, ranked, score-free.

While an author composes a new JD, show which existing harmonized roles look like the
same role, so they clone one instead of authoring SFU's 10th "Academic Advisor".
**Advisory only** (NN #1): nothing here blocks submission, nothing publishes, and the
validator remains the sole oracle for approvability
(:func:`~src.jd_bank.composer.validate.assess_draft`).

WHY THERE IS NO SCORE, NO PERCENTAGE AND NO THRESHOLD — ANYWHERE
----------------------------------------------------------------
Measured over the live ``jd_role_embeddings`` index (1,797 role vectors) *before*
this module was specified:

* same-title role pairs — genuine duplicates, n=2,618 — median cosine **0.9335**;
* a role's nearest **unrelated** neighbour, n=200 — median **0.9604**, i.e. an
  unrelated role scores HIGHER than a real twin;
* so any cutoff is a constant dressed as a measurement: at 0.90 the guard would fire
  on **99.2%** of drafts at **22%** precision; at 0.97 it would still fire on 24% and
  lose most true duplicates. A top1-vs-top2 margin rule fails identically (0.0065 for
  a true sibling vs 0.0052 for noise);
* **ranking, however, is good**: for the 790 roles with a same-title sibling, that
  sibling is top-5 for 76% and top-10 for 84%.

So this module returns a RANKED LIST and no number. Rendering "94% similar" here would
be the exact defect commit ``89d0c74`` fixed for title search, where a 0.013 spread
across the whole result page rendered as "81%" on every row.
:class:`RelatedRole` therefore has no ``score``/``similar``/``percent`` field, and
``test_composer_duplicates.py::test_related_role_never_carries_a_similarity_number``
pins that absence against a future contributor "helpfully" re-adding one.

WHAT THE PANEL IS INSTEAD
-------------------------
A ranked list **plus one honest non-vector fact**: an exact title collision joined
with department. *"SFU already has 9 roles titled 'Academic Advisor', across 6
departments"* is TRUE and needs no vector at all; *"your draft is 94% similar"* is not.

TWO INDEPENDENT PASSES, AND THE SECOND ONE MAY FAIL
---------------------------------------------------
* the **title pass** — Postgres only, no GPU: roles whose CURRENT canonical carries
  the draft's exact title (case-insensitive), JDFN-scoped. It always runs.
* the **semantic pass** — the draft serialized exactly as the role vectors were
  (:func:`~src.jd_core.bank.embed_text.serialize_document` with the same
  ``embeddings`` knobs and ``embed_stamp``, reused verbatim from
  :mod:`src.jd_bank.embeddings.roles`, or the cosines would not be comparable),
  embedded once, then :func:`~src.jd_bank.composer.search._nearest_role_ids`.

:func:`find_related_roles` **never raises**. Any failure in the semantic pass — Ollama
down, the role index not built yet, a driver blowing up — degrades to ``related=[]``
while the title pass still answers, on the same principle ``cadfc30`` applied to
approve: the Builder must not lose its compliance panel because the GPU is down.
Missing (``None``) clients are a supported call, not an error.

**Never embed empty or whitespace-only draft text.** Ollama turns ``""`` into a
constant vector that is a plausible nearest neighbour to *everything* — measured, every
empty query returned the identical role at exactly 0.8038 — so an empty serialization
is refused unconditionally, separately from the ``min_draft_chars`` floor and whatever
that floor is set to. :mod:`src.jd_bank.embeddings.roles` carries the same "NEVER embed
``''``" guard for the same reason.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any, Literal
from uuid import UUID

from neo4j import AsyncDriver
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Select, Subquery, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.jd_bank.composer import search
from src.jd_bank.db.models import CanonicalJD
from src.jd_bank.embeddings.client import EmbedClient
from src.jd_core.bank.embed_text import serialize_document
from src.jd_core.models.parsed_jd import SFUJobDescription
from src.jd_core.models.quality import DEFAULT_TEMPLATE, JDTemplate
from src.jd_core.rules import Rules, get_rules

logger = logging.getLogger(__name__)

#: The status of a vector hit whose cluster has NO current canonical row at all — a
#: legitimately reachable state (a ``(:JDRole)`` node outlives the canonical it was
#: built from until ``prune_roles`` catches up). Better than inheriting the node's
#: snapshot, which is stale the moment a reviewer edits or approves the role, and far
#: better than guessing "published". Such a row is also not :attr:`RelatedRole.
#: clonable`.
UNKNOWN_STATUS: str = "unknown"

#: A role in this state is NOT offered — in either list. ``802bff0`` already refuses to
#: edit an archived version because "rejected or superseded is settled"; offering to
#: CLONE one, or counting it in "SFU already has N roles titled X", would contradict
#: that. An archived JD is not what the Bank holds today.
_ARCHIVED_STATUS = "archived"

#: How far past ``max_matches`` the vector query reaches, so that CUPE hits, the
#: excluded cluster and roles already listed as title collisions can be filtered out
#: without the panel coming up short. Shares :mod:`~src.jd_bank.composer.search`'s
#: over-fetch factor rather than inventing a second one.
_OVERFETCH = search._OVERFETCH


class RelatedRole(BaseModel):
    """One existing harmonized role the author may have just re-authored.

    Carries no similarity number **by construction** — see the module docstring for
    the measurement that makes any such number meaningless on this corpus.
    """

    model_config = ConfigDict(extra="forbid")

    cluster_id: UUID
    #: The role's CURRENT canonical title (not the vector node's snapshot).
    title: str
    #: What tells two same-titled roles apart — SFU genuinely has 9 distinct "Academic
    #: Advisor" roles across 6 departments. ``None`` when nothing is recorded anywhere;
    #: never fabricated.
    department: str | None = None
    #: The role's CURRENT lifecycle status, so the panel can say honestly that a
    #: suggestion is a DRAFT rather than an approved role (NN #1).
    status: str
    #: HOW this role was found. A title collision is a FACT (two roles carry the same
    #: title); ``related`` is a ranked vector neighbour. They are not the same claim,
    #: so they are not flattened into one list.
    reason: Literal["title_collision", "related"]
    #: Whether "Start from this role" can actually resolve. ``False`` for a vector hit
    #: whose cluster has no current canonical: ``clone_role`` would 404, and offering a
    #: link that cannot work is worse than offering none. The row still shows, because
    #: "a role like this exists" is true even when the Bank cannot seed a draft from it.
    clonable: bool = True


class DuplicateGuard(BaseModel):
    """The advisory panel's whole state for one draft."""

    model_config = ConfigDict(extra="forbid")

    #: ``False`` before the author runs a check (nothing renders), mirroring the
    #: inclusive-language meter's own ``checked`` flag.
    checked: bool = False
    #: Roles whose current canonical carries this exact title — capped at
    #: ``max_matches``, like :attr:`related`. The COUNT below is not capped.
    title_collisions: list[RelatedRole] = Field(default_factory=list)
    #: Ranked vector neighbours that are not already a title collision.
    related: list[RelatedRole] = Field(default_factory=list)
    #: How many existing roles carry this exact title — the honest, non-vector count,
    #: and the one number the panel states as a FACT. So it is the TRUE total, not
    #: ``len(title_collisions)``: it is neither capped by ``max_matches`` nor reduced
    #: by ``exclude_cluster_id``. An author cloning one of SFU's 9 "Academic Advisor"
    #: roles must be told there are 9, not 8 — under-counting in the one place the
    #: panel claims to state a fact rather than a distance would be the whole
    #: feature's credibility.
    same_title_count: int = 0
    #: The DISTINCT departments those same-titled roles sit in (blank ones dropped —
    #: an unlabelled row is better than an invented department).
    departments: list[str] = Field(default_factory=list)


def _current_version_subquery(cluster_ids: Sequence[UUID] | None = None) -> Subquery:
    """The highest ``version`` per cluster — a superseded canonical must never be
    offered as a role to clone (it is not what the Bank holds today).

    ``cluster_ids`` narrows the aggregate to the clusters actually being asked about.
    Without it this GROUP BYs the whole ``canonical_jds`` table on every check, just
    to answer a question about at most ``max_matches`` roles. The title pass cannot use
    it (it does not know the clusters until it has matched), and it deliberately does
    NOT push the title predicate inside either: filtering the aggregate by title would
    make ``max(version)`` the newest version *that still carries that title*, so a role
    harmonization RENAMED would keep colliding on the title it no longer has.
    """
    aggregate = select(
        CanonicalJD.cluster_id,
        func.max(CanonicalJD.version).label("version"),
    )
    if cluster_ids is not None:
        aggregate = aggregate.where(CanonicalJD.cluster_id.in_(list(cluster_ids)))
    return aggregate.group_by(CanonicalJD.cluster_id).subquery()


def _current_rows_query(cluster_ids: Sequence[UUID] | None = None) -> Select[Any]:
    """Every cluster's CURRENT canonical row, optionally narrowed to ``cluster_ids``.

    One place, because the two reads below are the same question ("what does the Bank
    hold for this role today?") and were the same eight lines twice.
    """
    current = _current_version_subquery(cluster_ids)
    return select(CanonicalJD).join(
        current,
        (CanonicalJD.cluster_id == current.c.cluster_id)
        & (CanonicalJD.version == current.c.version),
    )


async def _title_collision_matches(
    session: AsyncSession,
    title: str,
    *,
    wjq_groups: frozenset[str],
    form: JDTemplate,
) -> list[tuple[UUID, str, str | None, str]]:
    """Roles whose CURRENT canonical carries ``title`` exactly (case-insensitive) —
    ``(cluster_id, title, department, status)``.

    Postgres only: no embedding, no Neo4j, no GPU. This is the pass that keeps working
    when the inference host is unreachable, and it is also the only honest one — an
    exact title match is a fact, not a distance (the same reasoning
    :func:`~src.jd_bank.composer.search._title_matches` is built on).

    JDFN-scoped: CUPE roles are filtered out (HR-143) because the Builder only ever
    authors the JDFN template and must not offer a CUPE role as a clone source. So are
    ARCHIVED roles (:data:`_ARCHIVED_STATUS`).
    """
    wanted = title.strip().lower()
    if not wanted:
        return []
    rows = (
        await session.execute(
            _current_rows_query().where(
                func.lower(CanonicalJD.content["title"].astext) == wanted
            )
        )
    ).scalars()
    matches: list[tuple[UUID, str, str | None, str]] = []
    for row in rows:
        content = row.content or {}
        if search._out_of_scope(content.get("employee_group"), wjq_groups, form):
            continue
        status = row.status.value
        if status == _ARCHIVED_STATUS:
            continue
        department = content.get("department")
        matches.append(
            (
                row.cluster_id,
                str(content.get("title") or ""),
                str(department) if department else None,
                status,
            )
        )
    return matches


async def _current_role_rows(
    session: AsyncSession, cluster_ids: Sequence[UUID]
) -> dict[UUID, tuple[str, str | None, str]]:
    """``{cluster_id: (current title, department, status)}`` — ONE batched query for
    the whole page of hits.

    The ``(:JDRole)`` node's ``title``/``status`` are a snapshot taken when the role
    was embedded, and they go stale the moment a reviewer edits or approves the role —
    so a panel that offered to clone "Academic Advisor (published)" off the node could
    be describing a title that no longer exists and an approval that never happened.
    Resolved from Postgres instead, in one query for every hit rather than one query
    per hit: ``d71e333`` removed exactly that N-query loop from search, and it must not
    come back here.

    It reads the department too, so this is the SAME scan
    :func:`~src.jd_bank.composer.search._role_departments` would run rather than a
    second copy of it; that function is then only asked about the hits whose canonical
    states no department of its own, where its source-document fallback is the only
    thing that can answer (measured: it recovers 149 of the 221 roles that carry none).

    **Raises** on a database failure — deliberately. It used to swallow, and the only
    thing that bought was four unit tests that exercised nothing but the swallow. There
    is exactly one degrade point for this whole pass (:func:`find_related_roles`), and a
    real Postgres fault belongs at it, logged, not silently reinterpreted as "no roles
    like this".
    """
    if not cluster_ids:
        return {}
    wanted = list(dict.fromkeys(cluster_ids))
    rows = (await session.execute(_current_rows_query(wanted))).scalars()
    resolved: dict[UUID, tuple[str, str | None, str]] = {}
    for row in rows:
        content = row.content or {}
        department = content.get("department")
        resolved[row.cluster_id] = (
            str(content.get("title") or ""),
            str(department) if department else None,
            row.status.value,
        )
    return resolved


async def _related_by_vector(
    draft: SFUJobDescription,
    *,
    session: AsyncSession,
    embed_client: EmbedClient | None,
    neo4j_driver: AsyncDriver | None,
    rules: Rules,
    already_listed: set[UUID],
    wjq_groups: frozenset[str],
    form: JDTemplate,
) -> list[RelatedRole]:
    """The semantic pass: the harmonized roles nearest the draft, ranked, capped.

    Serializes the draft with the SAME serializer and rulebook knobs the role vectors
    were built with (:mod:`src.jd_bank.embeddings.roles` reuses
    :func:`serialize_document` verbatim; so does this, or the cosines would not be
    comparable), embeds it exactly once, and reads the role index.

    Raises whatever the embedding client / driver raise — :func:`find_related_roles`
    is the single place that decides a failure here costs only ``related``.
    """
    if embed_client is None or neo4j_driver is None:
        return []
    guard = rules.dedup.authoring_guard
    text = serialize_document(draft, rules.embeddings).text
    # Two SEPARATE refusals. The second is the length floor HR retunes; the first is
    # unconditional, because an empty text embeds to a constant vector that is a
    # plausible nearest neighbour to everything (module docstring).
    if not text.strip():
        return []
    if len(text) < guard.min_draft_chars:
        return []

    vector = (await embed_client.embed_batch([text]))[0]
    neighbours = await search._nearest_role_ids(
        neo4j_driver,
        vector,
        guard.max_matches * _OVERFETCH,
        # Only vectors embedded under the configuration now in force are comparable
        # to this query vector — see `search._comparable`.
        live_stamp=rules.embeddings.stamp,
    )

    # Rank the WHOLE over-fetched candidate list. Deliberately NOT capped here: the
    # archived filter below needs a real Postgres read to apply, and capping first
    # meant every archived row inside the cap silently shortened the panel instead of
    # being backfilled — measured, 3 candidates available and 1 row shown. `_OVERFETCH`
    # exists so that filtering costs headroom, not results, and the cap is therefore
    # applied ONCE, at the end, to what actually survived.
    ranked: list[tuple[UUID, str]] = []
    seen = set(already_listed)
    for cluster_id, node_title, group, _score in neighbours:
        if search._out_of_scope(group, wjq_groups, form):
            continue  # a different instrument's role cannot seed this draft (HR-225)
        if cluster_id in seen:
            continue  # the cloned-from role, or already listed as a title collision
        seen.add(cluster_id)
        ranked.append((cluster_id, node_title))
    if not ranked:
        return []

    ids = [cluster_id for cluster_id, _ in ranked]
    rows = await _current_role_rows(session, ids)
    # Only the hits whose own canonical states no department need the source-document
    # fallback, so the second scan usually does not happen at all.
    unlabelled = [
        cluster_id
        for cluster_id in ids
        if cluster_id not in rows or rows[cluster_id][1] is None
    ]
    fallback = await search._role_departments(session, unlabelled) if unlabelled else {}

    related: list[RelatedRole] = []
    for cluster_id, node_title in ranked:
        row = rows.get(cluster_id)
        if row is not None and row[2] == _ARCHIVED_STATUS:
            continue  # settled, not what the Bank holds today (N-9)
        related.append(
            RelatedRole(
                cluster_id=cluster_id,
                # A hit with no current canonical is reachable: a `(:JDRole)` node
                # outlives the canonical it was built from until `prune_roles` runs.
                # Show it (the role does exist) with the node's title and an honest
                # unknown status — but do not offer a clone link that would 404.
                title=row[0] if row is not None else node_title,
                department=(
                    row[1] if row is not None and row[1] else fallback.get(cluster_id)
                ),
                status=row[2] if row is not None else UNKNOWN_STATUS,
                reason="related",
                clonable=row is not None,
            )
        )
        if len(related) >= guard.max_matches:
            break  # the cap, applied to what SURVIVED the filters (see above)
    return related


async def find_related_roles(
    draft: SFUJobDescription,
    *,
    session: AsyncSession,
    embed_client: EmbedClient | None,
    neo4j_driver: AsyncDriver | None,
    rules: Rules | None = None,
    exclude_cluster_id: UUID | None = None,
    form: JDTemplate = DEFAULT_TEMPLATE,
) -> DuplicateGuard:
    """The existing harmonized roles that look like ``draft`` — ranked, never scored.

    ``exclude_cluster_id`` is the role the Builder was cloned FROM: cloning a role must
    not immediately warn you that you duplicated the role you cloned, so it appears in
    neither LIST — but it is still COUNTED in ``same_title_count``, which is the true
    total (see :class:`DuplicateGuard`).

    Never raises. The title pass answers with no embedding client or Neo4j driver at
    all; the semantic pass degrades to ``[]`` on any failure (see the module docstring).
    """
    rulebook = rules if rules is not None else get_rules()
    cap = rulebook.dedup.authoring_guard.max_matches
    # The guard compares against roles on the SAME instrument (HR-225): a JDFN role is
    # not a duplicate warning for a CUPE draft, and vice versa.
    wjq_groups = frozenset(rulebook.segmentation.wjq_employee_groups)

    try:
        matches = await _title_collision_matches(
            session, draft.title or "", wjq_groups=wjq_groups, form=form
        )
    except Exception:  # noqa: BLE001 — advisory panel: never cost the compliance check
        logger.exception("near-duplicate title pass failed; reporting no collisions")
        matches = []

    # COUNT everything that matched (the fact), then LIST at most `max_matches` of the
    # ones that are not the role we were cloned from (the advice). The cap is shared
    # with `related` so one pass cannot flood a panel the other is rationing.
    collisions: list[RelatedRole] = []
    departments: dict[str, None] = {}
    for cluster_id, title, department, status in matches:
        if department:
            departments[department] = None
        if cluster_id == exclude_cluster_id or len(collisions) >= cap:
            continue
        collisions.append(
            RelatedRole(
                cluster_id=cluster_id,
                title=title,
                department=department,
                status=status,
                reason="title_collision",
            )
        )

    already_listed = {cluster_id for cluster_id, *_ in matches}
    if exclude_cluster_id is not None:
        already_listed.add(exclude_cluster_id)
    try:
        related = await _related_by_vector(
            draft,
            session=session,
            embed_client=embed_client,
            neo4j_driver=neo4j_driver,
            rules=rulebook,
            already_listed=already_listed,
            wjq_groups=wjq_groups,
            form=form,
        )
    except Exception:  # noqa: BLE001 — Ollama down / no role index: lose only `related`
        logger.exception("near-duplicate semantic pass failed; reporting no matches")
        related = []

    return DuplicateGuard(
        checked=True,
        title_collisions=collisions,
        related=related,
        same_title_count=len(matches),
        # DISTINCT, in first-seen order, across EVERY match (the same fact the count
        # is). Blank departments are dropped rather than shown as a nameless row: 72 of
        # 791 same-titled roles genuinely record none anywhere, and an invented
        # department is worse than an unlabelled one.
        departments=list(departments),
    )

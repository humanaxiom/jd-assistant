"""Value objects for the read-only content library (the browsable JD Bank).

These are plain view models the library service assembles from ``source_documents`` /
``parsed_jds`` / ``clusters`` / ``canonical_jds`` and the templates render. They carry
**already-rendered readable text** (:func:`~src.jd_core.bank.render.render_sfu_jd_text`)
so the UI never re-derives prose — the point of the library is that HR can *read* a JD,
not just see a filename or a count.

Everything here is read-only (NN #1): no field carries an approval/publish decision, and
nothing in this package mutates a row.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True)


class RoleRef(_Frozen):
    """A lightweight pointer to a harmonized role (a back-link from a source JD)."""

    cluster_id: UUID
    canonical_id: UUID
    title: str
    status: str


class SourceJDView(_Frozen):
    """One archive source JD, rendered readable — the answer to "where is the actual
    content of this .docx?". Assembled from a ``source_documents`` row + its latest
    ``parsed_jds`` parse."""

    source_document_id: UUID
    filename: str | None
    title: str
    employee_group: str | None
    department: str | None
    grade: str | None
    position_number: str | None
    parse_confidence: float
    rendered_text: str
    #: The harmonized role this source JD fed into, if it is a cluster member — the
    #: back-link that makes "this file → that role" navigable. ``None`` for a singleton
    #: or an as-yet-unclustered document.
    role: RoleRef | None = None


class MemberJD(_Frozen):
    """One source JD that fed a harmonized role, as shown in the role's "distilled from"
    list. ``parsed`` is False when the member has no loadable parse (pruned/unparsed) —
    the row still shows its filename, it just has no readable body to link to."""

    source_document_id: UUID
    filename: str | None
    title: str | None
    employee_group: str | None
    parsed: bool


class RoleView(_Frozen):
    """One harmonized role: the canonical (draft/published) content rendered readable,
    plus the source JDs it was distilled from. This is the primary browsable unit — the
    thing the review queue distils the archive down to."""

    canonical_id: UUID
    cluster_id: UUID
    title: str
    status: str
    version: int
    score: float | None
    grade: str | None
    #: JDFN level band from the cluster's constraint metadata (e.g. "3" or "3–4"), or
    #: None. Employee group is not populated for JDFN roles, so band is the facet shown.
    level_band: str | None
    rendered_text: str
    members: tuple[MemberJD, ...]
    source_count: int


class RoleListItem(_Frozen):
    """A row in the roles library — enough to triage and click through, no body. Score /
    grade are the STORED roll-up (what the producer computed), not a fresh recompute —
    the same display-only roll-up the review queue shows. ``level_band`` is the JDFN
    band from the cluster (employee group is not populated for JDFN roles)."""

    canonical_id: UUID
    cluster_id: UUID
    title: str
    status: str
    level_band: str | None
    source_count: int
    score: float | None
    grade: str | None


class RolePage(_Frozen):
    """A page of the roles library, with the total (pre-pagination) so the template can
    render "showing 1–50 of 1,801" and prev/next."""

    items: tuple[RoleListItem, ...]
    total: int
    limit: int
    offset: int
    q: str


class SourceListItem(_Frozen):
    """A row in the flat source-archive browser (the "all the .docx files" view)."""

    source_document_id: UUID
    filename: str | None
    title: str | None
    employee_group: str | None
    parsed: bool


class SourcePage(_Frozen):
    """A page of the flat source archive."""

    items: tuple[SourceListItem, ...]
    total: int
    limit: int
    offset: int
    q: str

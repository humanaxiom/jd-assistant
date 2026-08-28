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

from src.jd_core.models.parsed_jd import JobClassification


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
    #: The structured pay grade / classification, when captured (CUPE source JDs carry
    #: it from the archive; JDFN grades come from Builder/review entry or the HRIS).
    classification: JobClassification | None = None
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
    #: The structured pay grade / classification, when captured (None until entered in
    #: the Builder/review or imported from the HRIS — see the grade-scales decision).
    classification: JobClassification | None = None
    rendered_text: str
    members: tuple[MemberJD, ...]
    source_count: int


class RoleListItem(_Frozen):
    """A row in the roles library — enough to triage and click through, no body. Score /
    grade (the validator QUALITY grade A–D, not a pay grade) are the STORED roll-up the
    producer computed, not a fresh recompute — the same display-only roll-up the
    review queue shows."""

    canonical_id: UUID
    cluster_id: UUID
    title: str
    status: str
    source_count: int
    score: float | None
    grade: str | None


class RolePage(_Frozen):
    """A page of the roles library, with the total (pre-pagination) so the template can
    render "showing 1–50 of 1,801" and prev/next, and the active ``sort`` column +
    ``direction`` so the header links can render the current sort and toggle it."""

    items: tuple[RoleListItem, ...]
    total: int
    limit: int
    offset: int
    q: str
    sort: str
    direction: str


class SourceListItem(_Frozen):
    """A row in the flat source-archive browser (the "all the .docx files" view)."""

    source_document_id: UUID
    filename: str | None
    title: str | None
    employee_group: str | None
    #: The captured pay grade value (e.g. "8"), when the parse recovered one (CUPE).
    grade: str | None = None
    parsed: bool


class SourcePage(_Frozen):
    """A page of the flat source archive."""

    items: tuple[SourceListItem, ...]
    total: int
    limit: int
    offset: int
    q: str


class CollectionStats(_Frozen):
    """The headline of a functional family's collection page (Phase A2).

    ``source_documents`` and ``roles`` are reported TOGETHER because the compression
    between them is the whole claim — "469 documents became 45 roles". A document count
    on its own invites "why so few?" and reads as loss rather than as harmonization.

    ``recall_note`` is not decoration. A family that does not state how it under-recalls
    is exactly the failure the functional taxonomy keeps re-committing: the first IT
    term list missed every engineer, the corrected one nearly misses every analyst, and
    neither was visible until checked against a known-good set of roles.
    """

    label: str
    slug: str
    #: Roles in the family — resolved membership, never a term-score cutoff.
    roles: int
    #: Archive documents behind those roles (the numerator of the compression story).
    source_documents: int
    #: How many of the roles pass every gate today. Read from the stored gate decision,
    #: the same roll-up the review queue shows — never a fresh recompute.
    approvable: int
    #: What this family publishes about its own recall, verbatim from the rulebook.
    recall_note: str


class FamilyCandidate(_Frozen):
    """A row in a family's REVIEW QUEUE — a role that might belong, for a human to rule
    on (Phase A2).

    ⚠ **A candidate is a candidate.** The match counts are shown so a reviewer can see
    why the row surfaced, and they are counts of matched terms — never a percentage and
    never a confidence, because the sweep was measured to be incapable of deciding
    membership at any cutoff. The one clear false positive the measurement found (a
    Research Technician) ranked as highly as genuine IT roles.
    """

    cluster_id: UUID
    canonical_id: UUID
    title: str
    status: str
    source_count: int
    #: Where the role sits. Known for ~72% of roles, so it may be ``None`` — and the
    #: template must show that rather than implying the role has no home.
    department: str | None
    #: How many distinct family duty terms the role's text contains.
    duty_matches: int
    #: How many distinct family title terms the role's TITLE contains.
    title_matches: int
    #: Whether the role sits in one of the family's DEPARTMENTS. A candidate signal
    #: only — shown so a reviewer can see a role reached the queue on its department
    #: rather than on its duty text, which for 45 real roles is the only reason it did.
    department_match: bool = False

    @property
    def matches(self) -> int:
        """The rank key — the ordering of the worklist, and nothing more."""
        return self.duty_matches + self.title_matches


class FunnelStage(_Frozen):
    """One step of the archive → published funnel (Phase A4).

    ``lost`` and ``note`` exist together, and that pairing is the point. A stage
    reporting only its own count lets a real gap hide inside an expected one: the drop
    from parsed documents to documents behind a role looks like ordinary
    de-duplication, and measured, 52% of it is — while 1,204 documents have no
    near-duplicate link at all and are simply unaccounted for. **Every stage names what
    it lost.**
    """

    key: str
    label: str
    count: int
    #: How many did not reach this stage from the previous one.
    lost: int
    #: What became of them, in words. ``None`` when nothing was lost.
    note: str | None = None


class Funnel(_Frozen):
    """The archive → published funnel for one scope (Phase A4)."""

    scope_key: str
    scope_label: str
    stages: tuple[FunnelStage, ...]
    #: Set when the scope has no archive-side definition, so the document-side stages
    #: are absent. Stated rather than silently omitted: a funnel starting at "roles" for
    #: one scope and at "documents" for another, unexplained, is one nobody can compare.
    documents_note: str | None = None


class FacetBucket(_Frozen):
    """One value of a facet, and how many roles carry it."""

    value: str
    count: int


class Facet(_Frozen):
    """One dimension of the roles in a scope, WITH its own coverage (Phase A5).

    ⚠ :attr:`not_stated` is never folded into the buckets and never dropped. A facet
    that silently omits the roles it has no value for is the archive-claim error in UI
    form, and this project has made that error before. For ``department`` the blind spot
    is 27.8% of the Bank.
    """

    key: str
    label: str
    buckets: tuple[FacetBucket, ...]
    #: Roles in buckets beyond the display limit — counted, never discarded.
    other: int
    #: Roles with no value for this dimension at all.
    not_stated: int
    total: int
    note: str | None = None

    @property
    def known(self) -> int:
        """Roles this facet can actually say something about."""
        return self.total - self.not_stated

    @property
    def coverage_pct(self) -> float:
        """The share of the scope this facet covers, for the page to state plainly."""
        return round(100.0 * self.known / self.total, 1) if self.total else 0.0

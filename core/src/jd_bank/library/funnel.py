"""The live funnel and facets — archive to published, from the DB (Phase A4/A5).

**Live, not an artifact.** Every other archive-side dashboard reads a committed JSON
file written by a batch run, which is why they disagree with the Bank the moment
anything is reprocessed. These read the database at request time.

**Scope-parameterised throughout** (:mod:`src.jd_bank.library.scopes`). Nothing here
knows what "IT" is; the IT view is one scope key. See
``docs/plans/SCOPES-AND-ORG-ROLLUP.md``.

## Why every stage names what it lost

A funnel showing 14,565 → 2,493 and saying nothing about the difference reads as loss
and invites "why so few?". Worse, it lets a real gap hide inside an expected one.
Measured 2026-08-27, the archive-wide drop from 14,522 parsed documents to the 10,869
behind a role is **not** one thing:

* **1,900** are near-duplicates of a document that *is* in a role — represented;
* **549** are near-duplicates only of each other, so their group reached no role;
* **1,204 have no near-duplicate edge at all** and are simply unaccounted for.

Only the first is benign, and it is 52% of the gap. A funnel reporting "3,653
de-duplicated" would have been a plausible sentence hiding 1,204 documents nobody has
explained. Each bucket is therefore counted and shown separately.

Read-only (NN #1): nothing here mutates a row.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.jd_bank.library.models import Facet, FacetBucket, Funnel, FunnelStage
from src.jd_bank.library.scopes import Scope

#: The current canonical per cluster — every count here is over CURRENT versions only.
_CURRENT = """
    SELECT DISTINCT ON (cluster_id) *
    FROM canonical_jds ORDER BY cluster_id, version DESC
"""

#: Approvability lives ONLY here — `validation_reports` is empty and answers 0 just as
#: convincingly.
_APPROVED = "(change_log->'validator'->'gate_decision'->>'approved')::boolean"

#: Roles in scope. A scope with an empty membership must select NOTHING, never
#: everything — the wrong direction shows a stakeholder the entire archive under their
#: own unit's name.
_IN_SCOPE = "(:all_scopes OR c.cluster_id = ANY(CAST(:ids AS uuid[])))"


def _scope_params(scope: Scope) -> dict[str, object]:
    return {
        "all_scopes": scope.is_whole_bank,
        "ids": [str(i) for i in (scope.cluster_ids or ())],
    }


async def build_funnel(session: AsyncSession, scope: Scope) -> Funnel:
    """Archive → parsed → in a role → roles → approvable → published, for ``scope``.

    The document-side stages need an archive-side definition of the scope
    (:attr:`Scope.source_filename_pattern`). A scope without one — an org unit, whose
    ``department`` comes from a parse rather than a filename — reports its role-side
    stages and says so, rather than inventing a document total it cannot defend.
    """
    params = _scope_params(scope)
    role_row = (
        await session.execute(
            text(f"""
                WITH cur AS ({_CURRENT})
                SELECT count(*) FROM cur c WHERE {_IN_SCOPE}
            """),
            params,
        )
    ).one()
    approvable_row = (
        await session.execute(
            text(f"""
                WITH cur AS ({_CURRENT})
                SELECT count(*) FILTER (WHERE {_APPROVED}),
                       count(*) FILTER (WHERE status = 'PUBLISHED')
                FROM cur c WHERE {_IN_SCOPE}
            """),
            params,
        )
    ).one()

    stages: list[FunnelStage] = []
    documents_note: str | None = None

    if scope.is_whole_bank or scope.source_filename_pattern is not None:
        doc_filter = "TRUE" if scope.is_whole_bank else "d.filename ~ :pattern"
        doc_params = dict(params)
        if scope.source_filename_pattern is not None:
            doc_params["pattern"] = scope.source_filename_pattern
        docs = (
            await session.execute(
                text(f"""
                WITH cur AS ({_CURRENT}),
                indraft AS (
                  SELECT DISTINCT (s.value->>'source_id')::uuid AS sid
                  FROM cur c, jsonb_array_elements(c.source_document_ids) s
                ),
                scoped AS (SELECT d.id FROM source_documents d WHERE {doc_filter}),
                parsed AS (
                  SELECT DISTINCT p.source_document_id AS sid FROM parsed_jds p
                  WHERE p.source_document_id IN (SELECT id FROM scoped)
                ),
                orphan AS (
                  SELECT sid FROM parsed WHERE sid NOT IN (SELECT sid FROM indraft)
                )
                SELECT (SELECT count(*) FROM scoped),
                       (SELECT count(*) FROM parsed),
                       (SELECT count(*) FROM parsed
                          WHERE sid IN (SELECT sid FROM indraft)),
                       (SELECT count(DISTINCT o.sid) FROM orphan o JOIN dedup_edges e
                          ON (e.source_a_id = o.sid
                              AND e.source_b_id IN (SELECT sid FROM indraft))
                          OR (e.source_b_id = o.sid
                              AND e.source_a_id IN (SELECT sid FROM indraft))),
                       (SELECT count(*) FROM orphan o WHERE NOT EXISTS (
                          SELECT 1 FROM dedup_edges e
                          WHERE e.source_a_id = o.sid OR e.source_b_id = o.sid))
                """),
                doc_params,
            )
        ).one()
        total, parsed, in_role, dup_of_kept, no_edge = (int(v or 0) for v in docs)
        orphans = parsed - in_role
        # Whatever is neither "duplicate of a kept document" nor "no edge at all" is a
        # near-duplicate of another orphan — its whole group reached no role.
        dup_of_orphan = max(0, orphans - dup_of_kept - no_edge)
        unreadable = total - parsed
        stages.append(
            FunnelStage(
                key="documents",
                label="Source documents in the archive",
                count=total,
                lost=0,
                note=None,
            )
        )
        stages.append(
            FunnelStage(
                key="parsed",
                label="Readable — a parse succeeded",
                count=parsed,
                lost=unreadable,
                note=(
                    (
                        f"{unreadable} could not be read at all. They are named, not "
                        "dropped — an unreadable file is a finding, not a "
                        "rounding error."
                    )
                    if unreadable
                    else None
                ),
            )
        )
        stages.append(
            FunnelStage(
                key="in_role",
                label="Behind a current role",
                count=in_role,
                lost=orphans,
                note=(
                    (
                        f"{dup_of_kept} are near-duplicates of a document that IS in a "
                        f"role — represented, not lost. {dup_of_orphan} are "
                        f"near-duplicates only of each other. ⚠ {no_edge} have no "
                        "near-duplicate link at all and are unaccounted for."
                    )
                    if orphans
                    else None
                ),
            )
        )
    else:
        documents_note = (
            "This scope has no archive-side definition — its roles are identified from "
            "parsed content, not from filenames — so the document stages cannot be "
            "computed for it without overstating them."
        )

    roles = int(role_row[0] or 0)
    approvable, published = (int(v or 0) for v in approvable_row)
    stages.append(
        FunnelStage(
            key="roles",
            label="Harmonized roles",
            count=roles,
            lost=0,
            note="Compression, not loss: many documents describe one job.",
        )
    )
    stages.append(
        FunnelStage(
            key="approvable",
            label="Passing every gate today",
            count=approvable,
            lost=roles - approvable,
            note=(
                (
                    f"{roles - approvable} are blocked by at least one gate — most of "
                    "them on policy nobody has ratified yet, not on content."
                )
                if roles - approvable
                else None
            ),
        )
    )
    stages.append(
        FunnelStage(
            key="published",
            label="Published",
            count=published,
            lost=approvable - published,
            note=(
                "⚠ This is the count of roles whose CURRENT version is published. "
                "Editing a published role mints a new draft and leaves the count "
                "lower than the number ever published."
            ),
        )
    )
    return Funnel(
        scope_key=scope.key,
        scope_label=scope.label,
        stages=tuple(stages),
        documents_note=documents_note,
    )


async def _facet(
    session: AsyncSession,
    scope: Scope,
    *,
    key: str,
    label: str,
    expression: str,
    note: str | None = None,
    limit: int = 12,
) -> Facet:
    """One facet over the roles in ``scope``, with its own coverage.

    ⚠ **Coverage is not decoration.** Every facet reports how many roles it can
    actually say anything about, and keeps a ``(not stated)`` bucket for the rest. A
    facet that silently drops the roles it has no value for is the archive-claim error
    in UI form — and for ``department`` that blind spot is 27.8% of the Bank.
    """
    params = _scope_params(scope)
    rows = await session.execute(
        text(f"""
            WITH cur AS ({_CURRENT}),
            scoped AS (SELECT c.* FROM cur c WHERE {_IN_SCOPE})
            SELECT coalesce(nullif({expression}, ''), '(not stated)') AS bucket,
                   count(*) AS n
            FROM scoped c GROUP BY 1 ORDER BY n DESC, bucket ASC
        """),
        params,
    )
    buckets = [(str(row.bucket), int(row.n)) for row in rows]
    total = sum(n for _, n in buckets)
    not_stated = next((n for b, n in buckets if b == "(not stated)"), 0)
    shown = [FacetBucket(value=b, count=n) for b, n in buckets if b != "(not stated)"]
    return Facet(
        key=key,
        label=label,
        buckets=tuple(shown[:limit]),
        other=sum(b.count for b in shown[limit:]),
        not_stated=not_stated,
        total=total,
        note=note,
    )


async def build_facets(session: AsyncSession, scope: Scope) -> tuple[Facet, ...]:
    """The facets for ``scope``, each carrying its own coverage.

    Deliberately does NOT include a ``classification`` facet: the field is parsed on
    21% of documents and reaches 0% of drafts, so a facet over it would render an empty
    dimension as though the archive had no classifications. The coarse family comes
    from filenames instead, and belongs to the scope resolver rather than to a facet
    over draft content.
    """
    return (
        await _facet(
            session,
            scope,
            key="employee_group",
            label="Form",
            expression="c.content->>'employee_group'",
            note="Which SFU template the role is written on. Reliable.",
        ),
        await _facet(
            session,
            scope,
            key="department",
            label="Department (as written on the JD)",
            expression="c.content->>'department'",
            note=(
                "⚠ Raw strings, NOT an org rollup. The same unit appears under several "
                "spellings, and a vice-presidency is never the string written on a "
                "JD — so this filters, it does not total a unit. See the scopes plan."
            ),
        ),
        await _facet(
            session,
            scope,
            key="grade",
            label="Quality grade",
            expression="c.change_log->'validator'->>'grade'",
            note="The validator's quality grade A–D. NOT a pay grade.",
        ),
        await _facet(
            session,
            scope,
            key="status",
            label="Status",
            expression="c.status::text",
        ),
    )

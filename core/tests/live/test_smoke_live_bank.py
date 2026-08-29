"""Live smoke — the REAL Bank must reconcile end to end, or this fails loudly.

Run with ``make smoke``. Unlike everything in ``tests/integration``, this reads the LIVE
database (``DATABASE_URL``): no fixtures, no seeding, no mocks. It exists because this
project repeatedly produced numbers that were internally consistent and wrong — the only
answer to which is a check anyone can run against the system itself, including a
reviewer
who trusts none of the documentation.

What it asserts, in the order review demanded — *parsing, dedup, categorize,
filterable*:

1. **Every document is accounted for.** unreadable + behind-a-role + gap buckets ==
   the archive, exactly. A single unaccounted document fails the run.
2. **The gap reconciles.** Its buckets sum to its total — "de-duplicated" can never
   again absorb documents nobody has explained.
3. **Membership is a union.** Every role reachable by any single signal is in the
   collection; the filename-only regression (45 roles reported where ~211 exist) cannot
   silently return.
4. **Random documents are findable.** A sample of the archive, each found by exact
   filename through the same query the archive browser uses — the "anyone scanning
   random documents" test, automated.

Marked ``live``: never part of ``make gates`` or CI (CI has no Bank). Skips, loudly,
when ``DATABASE_URL`` is unset rather than passing vacuously.
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.jd_bank.library import (
    build_funnel,
    build_gap,
    family_for,
    list_source_jds,
    membership_coverage,
    resolve_members,
)
from src.jd_bank.library.families import _membership_predicates
from src.jd_bank.library.funnel import _CURRENT
from src.jd_bank.library.scopes import WHOLE_BANK

pytestmark = pytest.mark.live

_DB = os.environ.get("DATABASE_URL", "")

#: How many random documents the findability sample checks. Small enough to run in
#: seconds; a failure of ANY single one fails the smoke.
SAMPLE = 100


@pytest.fixture
async def session():  # type: ignore[no-untyped-def]
    if not _DB:
        pytest.skip("DATABASE_URL is not set — the live smoke needs the real Bank")
    engine = create_async_engine(_DB)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        yield s
    await engine.dispose()


async def test_every_document_in_the_live_bank_is_accounted_for(session) -> None:  # type: ignore[no-untyped-def]
    """unreadable + behind-a-role + gap == the archive. Nothing outside the three."""
    funnel = await build_funnel(session, WHOLE_BANK)
    stage = {s.key: s for s in funnel.stages}
    gap = await build_gap(session, WHOLE_BANK)

    assert stage["documents"].count > 0, "an empty Bank is a broken smoke, not a pass"
    assert (
        stage["documents"].count == stage["parsed"].count + stage["parsed"].lost
    ), "documents = readable + unreadable, exactly"
    assert (
        stage["parsed"].count == stage["in_role"].count + gap.total
    ), "readable = behind-a-role + the gap, exactly"
    assert gap.reconciles, (
        "the gap's buckets no longer sum to its total — a document has fallen outside "
        "every named bucket, which is the exact failure this smoke exists to catch"
    )
    accounted = stage["parsed"].lost + stage["in_role"].count + gap.total
    assert accounted == stage["documents"].count


async def test_the_role_side_reconciles_and_units_are_labelled(session) -> None:  # type: ignore[no-untyped-def]
    """Roles ≥ approvable ≥ published, and every stage names its unit."""
    funnel = await build_funnel(session, WHOLE_BANK)
    stage = {s.key: s for s in funnel.stages}
    assert stage["roles"].count >= stage["approvable"].count >= stage["published"].count
    assert all(s.unit in {"documents", "roles"} for s in funnel.stages)
    # Documents and roles are different units, and the page must say which is which —
    # 14,565 → 2,493 → 129 was read as one series in review, and the last is roles.
    assert stage["in_role"].unit == "documents"
    assert stage["roles"].unit == "roles"


async def test_collection_membership_is_a_true_union_of_its_signals(session) -> None:  # type: ignore[no-untyped-def]
    """Every role any single signal matches is a member. The filename-only regression —
    45 roles reported where ~211 exist, because 65% of filenames carry no code — cannot
    silently return."""
    family = family_for("it")
    assert family is not None
    members = await resolve_members(session, family)
    predicates, params = _membership_predicates(family)
    assert len(predicates) >= 3, "classification, title and department must all be live"
    for predicate in predicates:
        rows = await session.execute(
            text(f"""
                WITH cur AS ({_CURRENT}),
                doc AS (
                  SELECT c.cluster_id, d.filename,
                         c.content->>'title' AS title,
                         c.content->>'department' AS department
                  FROM cur c
                  LEFT JOIN LATERAL jsonb_array_elements(c.source_document_ids) s
                    ON TRUE
                  LEFT JOIN source_documents d ON d.id = (s.value->>'source_id')::uuid
                )
                SELECT DISTINCT cluster_id FROM doc WHERE {predicate}
            """),
            params,
        )
        matched = {row[0] for row in rows}
        stragglers = matched - members - set(family.exclude)
        assert not stragglers, (
            f"{len(stragglers)} roles matched by a membership signal are not in the "
            "collection — the union has silently regressed to a subset of its signals"
        )
    coverage = await membership_coverage(session, family)
    assert coverage.members == len(members)
    assert (
        coverage.total_roles == coverage.members + coverage.unmatched
    ), "member + unmatched must equal the Bank — the blind spot is reported, not lost"


async def test_random_documents_are_findable_in_the_archive_browser(session) -> None:  # type: ignore[no-untyped-def]
    """The 'anyone scanning random documents' test, automated: a sample of the real
    archive, each document found by exact filename through the same query the archive
    browser page uses. One miss fails the smoke."""
    rows = await session.execute(
        text(
            "SELECT filename FROM source_documents"
            f" WHERE filename IS NOT NULL ORDER BY random() LIMIT {SAMPLE}"
        )
    )
    filenames = [row[0] for row in rows]
    assert len(filenames) > 0
    for filename in filenames:
        page = await list_source_jds(session, q=filename)
        assert page.total >= 1, (
            f"{filename!r} exists in the archive but the browser search cannot find "
            "it — a document the UI cannot reach is missing in every way that matters"
        )


async def test_no_document_is_judged_under_the_wrong_template(session) -> None:  # type: ignore[no-untyped-def]
    """A CUPE document behind a non-CUPE draft would be scored by the wrong form's
    gates. Zero exist today, and this keeps it that way.

    Asked directly in review ("what about the CUPE blind spot?"). The filename signal
    finds only 17.7% of CUPE — but nothing CUPE-facing reads filenames: template
    routing and every CUPE count come from the PARSED employee_group. Traced
    2026-08-28: of 4,440 CUPE documents, 3,446 sit behind cupe-labelled drafts, 0
    behind any other label, 0 behind ungrouped drafts, 994 in the known orphan gap.
    The ungrouped drafts (defaulted to JDFN gates) hide only apsa/apex/poly/excluded
    documents — all JDFN-template groups, so the default judges them correctly.
    """
    rows = await session.execute(text(f"""
            WITH cur AS ({_CURRENT}),
            latest AS (
              SELECT DISTINCT ON (source_document_id)
                     source_document_id AS sid, parsed->>'employee_group' AS grp
              FROM parsed_jds ORDER BY source_document_id, created_at DESC
            )
            SELECT count(*) FROM cur c,
                   jsonb_array_elements(c.source_document_ids) s
            JOIN latest l ON l.sid = (s.value->>'source_id')::uuid
            WHERE l.grp = 'cupe'
              AND coalesce(c.content->>'employee_group', '') <> 'cupe'
        """))
    misrouted = int(rows.scalar() or 0)
    assert misrouted == 0, (
        f"{misrouted} CUPE documents sit behind a draft not labelled cupe — they are "
        "being judged by the wrong template's gates"
    )


@pytest.mark.live
async def test_no_draft_claims_a_template_its_documents_do_not(session) -> None:  # type: ignore[no-untyped-def]
    """The INVERSE of the test above, and the one that was missing.

    ``test_no_document_is_judged_under_the_wrong_template`` asks "is a CUPE document
    behind a non-CUPE draft?". It cannot see the opposite: a draft labelled cupe whose
    documents are NOT cupe. That draft is a CUPE role built out of JDFN documents —
    scored on the WJQ profile, excluded from the JDFN cohort, and counted as CUPE in
    every facet.

    🔴 It was not hypothetical. The v6 parser fix (HR-226) found that ~140 documents had
    been labelled cupe by a passing MENTION — "Directly supervises CUPE employees" — and
    61 of them were already inside 24 cupe-labelled drafts, every one of which was
    ENTIRELY built from such documents. The one-directional guard stayed green through
    all of it, which is why a guard has to be asserted in both directions before it can
    be trusted: agreement in the direction you tested says nothing about the other.

    Ungrouped drafts are NOT a violation — a draft with no group recorded defaults to
    the JDFN gates, which is the documented behaviour and is checked above. This asks
    only about drafts that positively CLAIM cupe.
    """
    rows = await session.execute(text(f"""
            WITH cur AS ({_CURRENT}),
            latest AS (
              SELECT DISTINCT ON (source_document_id)
                     source_document_id AS sid, parsed->>'employee_group' AS grp
              FROM parsed_jds ORDER BY source_document_id, created_at DESC
            )
            SELECT count(DISTINCT c.cluster_id) FROM cur c,
                   jsonb_array_elements(c.source_document_ids) s
            JOIN latest l ON l.sid = (s.value->>'source_id')::uuid
            WHERE c.content->>'employee_group' = 'cupe'
              AND coalesce(l.grp, '') <> 'cupe'
        """))
    stale = int(rows.scalar() or 0)
    assert stale == 0, (
        f"{stale} drafts claim the cupe template while holding documents the parser "
        "does not call cupe — they are scored on the WJQ profile and counted as CUPE "
        "wrongly. Re-compose them on the template their documents actually are."
    )

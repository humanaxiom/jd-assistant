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
5. **Library search (Track I1), through the HTTP route.** A deterministic sample of live
   roles is found by exact title; the 22-query ``search_eval_v1`` set meets its recall
   floor; a dead embed host still returns title hits plus a banner; the archive tab
   finds a document by its current parsed title.

Marked ``live``: never part of ``make gates`` or CI (CI has no Bank). Skips, loudly,
when ``DATABASE_URL`` is unset rather than passing vacuously.
"""

from __future__ import annotations

import os
import re

import pytest

# Module-level on purpose: with `from __future__ import annotations`, FastAPI resolves
# the `request: Request` annotation of the auth override from module globals. Imported
# inside the fixture it is unresolvable, `request` becomes a required QUERY param, and
# every route call 422s (that is how these smoke tests first failed).
from fastapi import Request
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


# ── 7-8. The DERIVED index — what the relational smoke could never see ──────────


@pytest.fixture
async def neo4j():  # type: ignore[no-untyped-def]
    """The live Neo4j driver, or a skip. Separate from `session` on purpose: the
    relational checks above must still run on a box with no graph."""
    from src.settings import get_settings

    settings = get_settings()
    try:
        from neo4j import AsyncGraphDatabase
    except ImportError:  # pragma: no cover - the driver is a hard dependency
        pytest.skip("neo4j driver unavailable")
    driver = AsyncGraphDatabase.driver(
        settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password)
    )
    try:
        yield driver
    finally:
        await driver.close()


async def test_the_role_vector_index_covers_every_current_role(session, neo4j) -> None:  # type: ignore[no-untyped-def]
    """🔴 THE GAP THAT MADE "make smoke: 6 passed" MEAN LESS THAN IT SOUNDED.

    Neo4j is a DERIVED index and NOTHING rebuilds it — not `launch.ps1`, not a producer
    run, not a parser bump. Measured 2026-08-29 while answering "is launch.ps1 all I
    need?": `(:JDRole)` held **1,797 vectors against 2,500 roles**, so 703 roles were
    invisible to Builder search — with no error anywhere, because the query is
    `db.index.vector.queryNodes` with no coverage check.

    The six relational tests above all passed throughout. They reconcile the LEDGER;
    they cannot see a stale derived store, and calling that "end to end" is what let a
    completion be claimed over a half-built search index.

    ⚠ Expected to be RED until plan.md P3g lands: `make embed-roles` aborts on one role
    whose text exceeds the embedding context, so it stops partway and every role after
    it stays unembedded. That is the point — the gate should stay red while the system
    is incomplete.
    """
    from src.jd_bank.embeddings.roles import _embeddable_roles

    rows = (await session.execute(text(f"SELECT content FROM ({_CURRENT}) cur"))).all()
    #: Roles the runner would actually embed — its OWN rule, not a re-implementation:
    #: a role serializing to no text is never embedded, because a zero-ish vector is a
    #: nearest neighbour to everything. Comparing against the raw role count would make
    #: this gate permanently red by 8 and train everyone to ignore it.
    embeddable = _embeddable_roles(r[0] for r in rows)
    async with neo4j.session() as s:
        record = await (await s.run("MATCH (r:JDRole) RETURN count(r) AS n")).single()
        embedded = record["n"]

    assert embedded >= embeddable, (
        f"{embeddable - embedded} of {embeddable} embeddable roles have NO vector, so "
        f"Builder search cannot find them. Run `make embed-roles` (plan.md P3g)."
    )


async def test_the_document_vector_index_is_at_the_current_parser_version(  # type: ignore[no-untyped-def]
    neo4j,
) -> None:
    """A vector built from text the parser no longer produces ranks on fiction.

    Measured 2026-08-29: every `(:JDDocument)` node carried
    `parser_version = jd_segmenter_v2` — **six bumps stale** — while the Bank served v8
    parses. Nothing failed, because the vector query does not filter on version.

    `PARSER_VERSION`'s contract already says a bump ships WITH its re-parse. This
    extends the same rule to the derived store: a bump also owes `make embed`.
    """
    from src.jd_core.parser import PARSER_VERSION

    async with neo4j.session() as s:
        result = await s.run(
            "MATCH (d:JDDocument) RETURN DISTINCT d.parser_version AS v"
        )
        versions = sorted({r["v"] async for r in result})

    assert versions == [PARSER_VERSION], (
        f"document vectors are at {versions}, the Bank is at {PARSER_VERSION!r}. "
        f"Run `make embed`."
    )


# ── 9-12. Library hybrid search (Track I1) — through the HTTP route ─────────────
#
# Driven through the REAL FastAPI app (httpx ASGI transport) so the route, its optional
# embed/Neo4j dependencies and the template are all in the path. Only identity is
# overridden: `require_ui_user` stands in for CAS (the same synthetic user `make gates`
# runs as), and `get_session` is bound to the live database. The embed host and Neo4j
# are the REAL ones — except in the dead-host test, which points the embed client at a
# closed port on purpose.

_ROLE_LINK = re.compile(r'href="/jd-bank/ui/role/([0-9a-f-]{36})"')
#: Deterministic sample size for exact-title findability.
TITLE_SAMPLE = 50


@pytest.fixture
async def library(session):  # type: ignore[no-untyped-def]
    """``(http_client, run_sql)`` bound to the live Bank, with auth overridden."""
    from httpx import ASGITransport, AsyncClient

    from src.api.deps import transient_dev_user
    from src.api.main import app, get_session
    from src.api.routes.auth import require_ui_user
    from src.settings import get_settings

    engine = create_async_engine(_DB)
    maker = async_sessionmaker(engine, expire_on_commit=False)

    async def _session():  # type: ignore[no-untyped-def]
        async with maker() as s:
            yield s

    async def _user(request: Request):  # type: ignore[no-untyped-def]
        user = transient_dev_user(get_settings())
        request.state.user = user
        request.state.csrf_token = ""
        return user

    app.dependency_overrides[get_session] = _session
    app.dependency_overrides[require_ui_user] = _user
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://smoke") as client:
            yield client
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()


async def _search_ids(client, q: str, limit: int):  # type: ignore[no-untyped-def]
    resp = await client.get("/jd-bank/ui/library", params={"q": q, "limit": limit})
    assert resp.status_code == 200, f"/library?q={q!r} -> {resp.status_code}"
    ids = list(dict.fromkeys(_ROLE_LINK.findall(resp.text)))
    return resp, ids


async def test_sampled_live_roles_are_found_by_exact_title(library, session) -> None:  # type: ignore[no-untyped-def]
    """Typing a role's own title must find that role. A deterministic sample (md5 order,
    so a re-run checks the same roles), through the HTTP route a person would use."""
    rows = (
        await session.execute(
            text(
                f"SELECT cluster_id, content->>'title' FROM ({_CURRENT}) cur "
                "WHERE coalesce(content->>'title','') <> '' "
                f"ORDER BY md5(cluster_id::text) LIMIT {TITLE_SAMPLE}"
            )
        )
    ).all()
    assert len(rows) == TITLE_SAMPLE, "the live Bank has too few titled roles to sample"
    missed = []
    for cluster_id, title in rows:
        _, ids = await _search_ids(library, title, limit=200)
        if str(cluster_id) not in ids:
            missed.append(title)
    assert not missed, f"{len(missed)} roles are not found by their own title: {missed}"


async def test_search_eval_v1_meets_its_recall_floor(library, session) -> None:  # type: ignore[no-untyped-def]
    """The 22 reviewed queries (fixtures/search_eval_v1.yaml): at least FLOOR of them
    must put a relevant role in the first 10 results. Judged on the live roles'
    title / department / group, never on the page's wording. If this is below the floor
    REPORT it — do not lower the floor."""
    from tests.search_eval import load_eval

    floor, queries = load_eval()
    hits, misses = 0, []
    for q in queries:
        _, ids = await _search_ids(library, q.query, limit=10)
        top = ids[:10]
        rows = (
            await session.execute(
                text(
                    f"SELECT content->>'title', content->>'department', "
                    f"content->>'employee_group' FROM ({_CURRENT}) cur "
                    "WHERE cluster_id = ANY(CAST(:ids AS uuid[]))"
                ),
                {"ids": top},
            )
        ).all()
        if any(q.relevant(t, d, g) for t, d, g in rows):
            hits += 1
        else:
            misses.append(f"{q.id} {q.query!r}")
    assert hits >= floor, (
        f"search_eval_v1 hit@10 = {hits}/{len(queries)} (floor {floor}); "
        f"misses: {misses}"
    )


async def test_dead_embed_host_keeps_title_hits_and_banner(library, session) -> None:  # type: ignore[no-untyped-def]
    """The GPU box being off costs the meaning pass and shows a banner — not a 500,
    and not the title hits the page already had."""
    from openai import AsyncOpenAI

    from src.api.main import app
    from src.api.routes.library import get_optional_embed_client
    from src.jd_bank.embeddings.client import EmbedClient

    title_row = (
        await session.execute(
            text(
                f"SELECT cluster_id, content->>'title' FROM ({_CURRENT}) cur "
                "WHERE length(coalesce(content->>'title','')) > 12 "
                "ORDER BY md5(cluster_id::text) LIMIT 1"
            )
        )
    ).one()
    # Nothing listens on port 9: every connection is refused immediately.
    dead = AsyncOpenAI(base_url="http://127.0.0.1:9/v1", api_key="x", max_retries=0)
    app.dependency_overrides[get_optional_embed_client] = lambda: EmbedClient(
        client=dead
    )

    resp, ids = await _search_ids(library, title_row[1], limit=200)

    assert str(title_row[0]) in ids, "title hits must survive a dead embed host"
    assert "Search by meaning is unavailable" in resp.text


async def test_archive_finds_documents_by_current_parsed_title(session) -> None:  # type: ignore[no-untyped-def]
    """The archive tab used to search filenames only. Titles few documents share, so
    the document is on the first page; deterministic sample."""
    from src.jd_core.parser import PARSER_VERSION

    rows = (
        await session.execute(
            text(
                "SELECT parsed->>'title' AS title, min(source_document_id::text) "
                "FROM parsed_jds WHERE parser_version = :v "
                "AND length(coalesce(parsed->>'title','')) > 12 "
                "GROUP BY 1 HAVING count(*) BETWEEN 1 AND 40 "
                "ORDER BY md5(parsed->>'title') LIMIT 5"
            ),
            {"v": PARSER_VERSION},
        )
    ).all()
    assert rows, "no suitable current-parse titles to sample"
    for title, doc_id in rows:
        page = await list_source_jds(session, q=title, limit=200)
        assert doc_id in {str(i.source_document_id) for i in page.items}, (
            f"document {doc_id} (title {title!r}) is not found by its current parsed "
            "title in the archive browser"
        )

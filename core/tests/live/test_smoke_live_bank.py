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


#: Per current role: its distinct padded position ids, and whether EVERY member file
#: carries one. Derived by raw SQL, never through the builder under test.
_CRF_ROLES = f"""
    WITH cur AS ({_CURRENT}),
    pos AS (
      SELECT c.cluster_id, array_agg(DISTINCT m[1] ORDER BY m[1]) AS pids
      FROM cur c
      CROSS JOIN LATERAL jsonb_array_elements(c.source_document_ids) e
      JOIN source_documents s ON s.id::text = e->>'source_id'
      CROSS JOIN LATERAL regexp_matches(s.filename, :pat, 'g') m
      GROUP BY c.cluster_id),
    bad AS (
      SELECT DISTINCT c.cluster_id
      FROM cur c
      CROSS JOIN LATERAL jsonb_array_elements(c.source_document_ids) e
      LEFT JOIN source_documents s ON s.id::text = e->>'source_id'
      WHERE s.id IS NULL OR s.filename IS NULL OR s.filename !~ :pat)
"""


async def _crf_fill(session, cluster_id, **kwargs):  # type: ignore[no-untyped-def]
    import io

    from pypdf import PdfReader

    from src.jd_bank.forms import prefill_from_role
    from src.jd_export.comp_requisition import fill_compensation_requisition

    prefill = await prefill_from_role(session, cluster_id, **kwargs)
    pdf = fill_compensation_requisition(prefill)
    fields = PdfReader(io.BytesIO(pdf)).get_fields() or {}
    return prefill, {name: f.get("/V") for name, f in fields.items()}


async def test_crf_fills_from_a_live_single_position_role(session) -> None:  # type: ignore[no-untyped-def]
    """K2 — fill SFU's own CRF (re-evaluation) for a LIVE single-position role.

    No fixture: the role is the first current role, by cluster id, whose members ALL
    carry a padded position id, with exactly ONE position and a title, a department and
    an APSA/APEX group. Expected values are re-derived by raw SQL — NOT by calling the
    builder again — so a builder that silently dropped a field cannot agree with itself.
    """
    from src.jd_core.rules import get_rules
    from src.jd_export.comp_requisition import load_field_map

    pattern = get_rules().segmentation.position_id_pattern.pattern
    row = (
        await session.execute(
            text(_CRF_ROLES + """
                SELECT c.cluster_id, c.content->>'title', c.content->>'department',
                       upper(c.content->>'employee_group'), p.pids
                FROM cur c JOIN pos p USING (cluster_id)
                WHERE cardinality(p.pids) = 1
                  AND c.cluster_id NOT IN (SELECT cluster_id FROM bad)
                  AND nullif(trim(c.content->>'title'), '') IS NOT NULL
                  AND nullif(trim(c.content->>'department'), '') IS NOT NULL
                  AND c.content->>'employee_group' IN ('apsa', 'apex')
                ORDER BY c.cluster_id
                LIMIT 1
                """),
            {"pat": pattern},
        )
    ).first()
    assert row is not None, "no live role has one position + title + dept + group"
    cluster_id, title, department, group, pids = row

    _, got = await _crf_fill(
        session, cluster_id, request_type="reevaluation", jd_in_word_attached=True
    )

    fmap = load_field_map()
    pf = fmap.prefill_fields
    assert got[pf["position_number"]] == pids[0]
    assert got[pf["position_title"]] == title.strip()
    assert got[pf["department"]] == department.strip()
    assert got[pf["employee_group"]] == group
    assert got[pf["based_on_positions_b"]] == pids[0]
    assert got[pf["based_on_positions_a"]] in (None, "")  # not a Section A request
    assert got[pf["jd_in_word_attached"]] == fmap.checkbox_on_value
    for name in fmap.signature_fields:
        assert got[name] in (None, ""), f"{name} must stay empty"


async def test_crf_caps_a_live_many_position_role(session) -> None:  # type: ignore[no-untyped-def]
    """K2 — a live role with MORE positions than the single-line field holds.

    The Section A box is ~2 ids wide; the full list must land in the Reason field and
    the box carries the cap + a `+K more` marker, never an overflowing line.
    """
    from src.jd_core.rules import get_rules
    from src.jd_export.comp_requisition import load_field_map

    fmap = load_field_map()
    ov = fmap.overflow
    pattern = get_rules().segmentation.position_id_pattern.pattern
    row = (
        await session.execute(
            text(_CRF_ROLES + """
                SELECT c.cluster_id, p.pids
                FROM cur c JOIN pos p USING (cluster_id)
                WHERE cardinality(p.pids) > :n
                  AND c.cluster_id NOT IN (SELECT cluster_id FROM bad)
                ORDER BY cardinality(p.pids) DESC, c.cluster_id
                LIMIT 1
                """),
            {"pat": pattern, "n": ov.max_ids},
        )
    ).first()
    assert row is not None, "no live role has more positions than the box holds"
    cluster_id, pids = row

    prefill, got = await _crf_fill(
        session, cluster_id, request_type="new_based_on_existing"
    )

    pf = fmap.prefill_fields
    expected = ", ".join(pids[: ov.max_ids]) + f" +{len(pids) - ov.max_ids} more"
    assert got[pf["based_on_positions_a"]] == expected
    assert got[pf["position_number"]] in (None, "")  # N/A if new
    reason = str(got[ov.details_field])
    assert all(pid in reason for pid in pids)
    assert str(len(pids)) in reason
    assert list(prefill.candidate_positions) == list(pids)


async def test_crf_never_claims_one_position_for_an_unpadded_role(session) -> None:  # type: ignore[no-untyped-def]
    """The measured trap: a role with ONE padded id whose other member files carry only
    unpadded ids (the pattern cannot read 508 archive files) is not a single-position
    role. Every such live role must come back flagged with no position number."""
    from src.jd_bank.forms import prefill_from_role
    from src.jd_core.rules import get_rules

    pattern = get_rules().segmentation.position_id_pattern.pattern
    rows = (
        await session.execute(
            text(_CRF_ROLES + """
                SELECT c.cluster_id
                FROM cur c JOIN pos p USING (cluster_id)
                WHERE cardinality(p.pids) = 1
                  AND c.cluster_id IN (SELECT cluster_id FROM bad)
                ORDER BY c.cluster_id
                """),
            {"pat": pattern},
        )
    ).all()
    for (cluster_id,) in rows:
        prefill = await prefill_from_role(
            session, cluster_id, request_type="reevaluation"
        )
        assert prefill.positions_incomplete is True, cluster_id
        assert prefill.position_number is None, cluster_id


# ── 9-11. EXPORT — a live role, rendered and read back by the Bank's own parser ────
#
# Track J1. The unit suite proves the CUPE export round-trips on fixtures; a fixture
# cannot hold the shapes the archive actually produced (a form's instructions flattened
# into a section, a prompt typed twice, a tick typed beside an option). These take a
# LIVE role, export it through the same entry point the Builder's export routes call,
# extract the `.docx` with the ingest path, and re-parse it.
#
# MEASURED 2026-10-19 over every current role: 623 of 627 CUPE roles round-trip with no
# loss. The other 4 are WJQ-PARSER limits, not export defects — 3 hold authored text
# containing "an equivalent combination of", which is a `wjq.instruction_markers`
# fragment, so the parser discards that line; 1 has exactly 40 qualifications and the
# form's own "Years" cell re-reads as a 41st, pushing the last past the parser's cap.
# Fixing either is a parser change (hashed `wjq.yaml`, PARSER_VERSION, re-parse).


async def _first_current(session, where: str) -> tuple[str, dict]:  # type: ignore[no-untyped-def,type-arg]
    """The first current role (by cluster id — deterministic) matching ``where``."""
    row = (await session.execute(text(f"""
                WITH cur AS ({_CURRENT})
                SELECT cluster_id, content FROM cur c WHERE {where}
                ORDER BY cluster_id LIMIT 1
            """))).first()
    if row is None:
        pytest.fail(f"no current role matches {where!r} — an empty Bank is not a pass")
    return str(row[0]), row[1]


def _export_and_reparse(content: dict):  # type: ignore[no-untyped-def,type-arg]
    from src.jd_bank.db.models import DocumentFormat
    from src.jd_bank.ingest.extract import extract_text
    from src.jd_core.models.parsed_jd import SFUJobDescription
    from src.jd_core.parser.segmenter import parse_jd
    from src.jd_export import render_sfu_docx

    jd = SFUJobDescription.model_validate(content)
    body = extract_text(render_sfu_docx(jd), DocumentFormat.DOCX)
    return jd, body, parse_jd(body)


async def test_a_live_cupe_role_survives_export_and_reparse(session) -> None:  # type: ignore[no-untyped-def]
    """A live CUPE role exports on HR's CUPE form and the WJQ parser reads it back
    with title, functions (statement, how/why, frequency), contacts, qualifications and
    every point-factor section intact — and with no APSA boilerplate on it."""
    from src.jd_core.rules import get_rules
    from tests.export_roundtrip import cupe_round_trip_losses

    rules = get_rules()
    cid, content = await _first_current(
        session,
        "c.content->>'employee_group' = 'cupe' "
        "AND jsonb_array_length(c.content->'duties') > 0 "
        "AND c.content->>'additional_context' IS NOT NULL "
        "AND jsonb_typeof(c.content->'relationships') = 'object'",
    )
    jd, body, result = _export_and_reparse(content)

    assert (
        result.template == "wjq"
    ), f"role {cid}: the export is not read as a CUPE form"
    losses = cupe_round_trip_losses(jd, result.jd, rules)
    assert losses == [], f"role {cid} lost fields on export -> re-parse: {losses}"
    for line in rules.cupe_form.banner:
        assert line in body, f"role {cid}: CUPE banner line {line!r} missing"
    boiler = rules.boilerplate
    for passage in (
        *boiler.territorial_acknowledgement,
        *boiler.employment_equity,
        *boiler.about_sfu,
    ):
        assert passage not in body, f"role {cid}: APSA boilerplate on the CUPE form"


async def test_no_live_cupe_role_exports_with_the_apsa_footer(session) -> None:  # type: ignore[no-untyped-def]
    """Every current CUPE role, not a sample: none exports in the APSA layout or with
    the APSA territorial / equity footer (CUPE 3338 Art. 15.04)."""
    from src.jd_core.rules import get_rules

    rules = get_rules()
    footer = [
        *rules.boilerplate.territorial_acknowledgement,
        *rules.boilerplate.employment_equity,
    ]
    rows = (await session.execute(text(f"""
                WITH cur AS ({_CURRENT})
                SELECT cluster_id, content FROM cur c
                WHERE c.content->>'employee_group' = 'cupe'
            """))).all()
    assert rows, "no current CUPE role — an empty Bank is not a pass"
    wrong = []
    for cid, content in rows:
        _, body, result = _export_and_reparse(content)
        if result.template != "wjq" or any(p in body for p in footer):
            wrong.append(str(cid))
    assert not wrong, f"{len(wrong)} CUPE roles export on the APSA form: {wrong[:5]}"


async def test_a_live_apsa_role_survives_export_and_reparse(session) -> None:  # type: ignore[no-untyped-def]
    """The APSA export is unchanged by J1 and still carries its footer; a live APSA
    role's title and position summary come back through the JDFN parser.

    ⚠ Duties are NOT asserted, and that is a measured pre-existing defect of the APSA
    export, not a gap in this test: 1,798 of 1,876 current non-CUPE roles re-read with a
    different duty count (``tests/export_roundtrip.py :: jdfn_round_trip_losses``). J1
    must leave the APSA output byte-identical in content, so it is reported, not fixed.
    """
    from src.jd_core.rules import get_rules
    from tests.export_roundtrip import jdfn_round_trip_losses

    rules = get_rules()
    cid, content = await _first_current(
        session,
        "c.content->>'employee_group' = 'apsa' "
        "AND jsonb_array_length(c.content->'duties') > 0 "
        "AND c.content->>'position_summary' IS NOT NULL",
    )
    jd, body, result = _export_and_reparse(content)

    assert result.template != "wjq", f"role {cid}: an APSA export read as a CUPE form"
    losses = jdfn_round_trip_losses(jd, result.jd)
    assert losses == [], f"role {cid} lost fields on export -> re-parse: {losses}"
    for passage in rules.boilerplate.territorial_acknowledgement:
        assert passage in body, f"role {cid}: the APSA footer is missing"

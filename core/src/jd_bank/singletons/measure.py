"""Read the live Bank and answer HR-223: how many SFU jobs exist exactly once?

Postgres only — no Neo4j, no Ollama, no archive bind. It reads and writes no Bank row,
so it is safe to run at any time, including mid-producer-run (the numbers are then
mid-flight, which this report cannot know).

⚠ **This is a question about CLUSTERING, so the database is the right source.** The
standing rule "check the source files, not the database" applies when the *parse* is
what is in question; here the parse is an input and the edges are the subject, and
edges exist nowhere but the database. What the parse contributes — the title — is
exactly what the ``title_unjudgeable`` bucket refuses to guess about.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from statistics import median

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.jd_bank.singletons.buckets import (
    DocumentTitle,
    bucket_documents,
    unique_titles,
)
from src.jd_bank.singletons.models import SingletonSummary
from src.jd_core.parser import PARSER_VERSION
from src.jd_core.rules.loader import Rules

#: The current version of each role. A cluster's older versions are history; counting a
#: document as "in a role" through a superseded version would credit the Bank with
#: lineage it has replaced.
_CURRENT = """
    SELECT DISTINCT ON (cluster_id) *
    FROM canonical_jds ORDER BY cluster_id, version DESC
"""

#: One row per parsed document: its title, whether a current role cites it, and whether
#: it carries a `dedup_edges` row at EITHER end.
#:
#: ⚠ `has_edge` is `EXISTS`, deliberately, over both endpoints. Edges are oriented by a
#: structural key, so testing only `source_a_id` would silently call every b-side
#: document edgeless — a wrong query returns a comfortable number exactly as
#: convincingly as a right one.
_DOCUMENTS = f"""
    WITH cur AS ({_CURRENT}),
    indraft AS (
      SELECT DISTINCT (s.value->>'source_id')::uuid AS sid
      FROM cur c, jsonb_array_elements(c.source_document_ids) s
    )
    SELECT p.source_document_id,
           coalesce(p.parsed->>'title', '') AS title,
           (p.source_document_id IN (SELECT sid FROM indraft)) AS in_role,
           EXISTS (SELECT 1 FROM dedup_edges e
                   WHERE e.source_a_id = p.source_document_id
                      OR e.source_b_id = p.source_document_id) AS has_edge,
           coalesce(jsonb_array_length(p.parsed->'qualifications'), 0) AS quals
    FROM parsed_jds p
    WHERE p.parser_version = :parser_version
"""


async def measure_singletons(
    session: AsyncSession, *, rules: Rules | None = None, examples: int = 12
) -> SingletonSummary:
    """Measure the one-of-a-kind population over every current-version parse.

    Returns counts only — no document id, no title beyond the handful of examples that
    let a reader check the result by eye rather than believe it.
    """
    rows: Sequence[tuple[uuid.UUID, str, bool, bool, int]] = (
        (await session.execute(text(_DOCUMENTS), {"parser_version": PARSER_VERSION}))
        .tuples()
        .all()
    )

    documents = [
        DocumentTitle(
            document_id=source_id, title=title, in_role=in_role, has_edge=has_edge
        )
        for source_id, title, in_role, has_edge, _quals in rows
    ]
    buckets = bucket_documents(documents, rules=rules)

    in_role = [r for r in rows if r[2]]
    pool = [r for r in rows if not r[2] and not r[3]]

    def mean_quals(
        population: Sequence[tuple[uuid.UUID, str, bool, bool, int]],
    ) -> float | None:
        # A mean over an empty population is not 0.0 — that would read as "these
        # documents have no qualifications", a finding rather than the absence of one.
        # NaN is not valid JSON either, so the honest answer is null.
        if not population:
            return None
        return round(sum(r[4] for r in population) / len(population), 2)

    def median_quals(
        population: Sequence[tuple[uuid.UUID, str, bool, bool, int]],
    ) -> float | None:
        return round(median(r[4] for r in population), 2) if population else None

    return SingletonSummary(
        parser_version=PARSER_VERSION,
        parsed_documents=len(rows),
        documents_in_a_role=len(in_role),
        orphans=len(rows) - len(in_role),
        documents_with_no_edge=sum(1 for r in rows if not r[3]),
        documents_with_no_edge_in_a_role=sum(1 for r in rows if r[2] and not r[3]),
        buckets=buckets,
        mean_qualifications_pool=mean_quals(pool),
        mean_qualifications_in_role=mean_quals(in_role),
        median_qualifications_pool=median_quals(pool),
        median_qualifications_in_role=median_quals(in_role),
        unique_title_examples=unique_titles(documents, rules=rules, limit=examples),
    )

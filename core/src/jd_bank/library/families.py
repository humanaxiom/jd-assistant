"""Functional role families — gathering roles by what people DO (Phase A2).

The read side of ``functional_families.yaml``. Two operations, and the distinction
between them is the whole point of this module:

* :func:`resolve_members` — **who is in the family.** SFU's own classification family
  (``ITP``, carried in the source filename) plus the reviewed ``include``, minus the
  reviewed ``exclude``. Nothing else. It does not read a single duty word.
* :func:`rank_candidates` — **who a reviewer should look at next.** A ranked worklist,
  ordered by how many distinct family terms a role's text contains.

**The score never decides membership, and that is measured rather than cautious.**
Scored against the 45 roles SFU's ITP classification already calls IT: keeping 98% of
them requires returning 1,141 roles (46% of the archive), and trimming to a plausible
~166 keeps only 48.9%. No cut point is both precise and complete, so a term list can
only ever ORDER a queue. See ``docs/plans/IT-FUNCTIONAL-SWEEP-MEASUREMENT.md`` §1.

Read-only (NN #1): nothing here mutates a row, publishes, or touches a gate.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.jd_bank.library.models import (
    CollectionStats,
    FamilyCandidate,
)
from src.jd_core.rules import FunctionalFamily, Rules, get_rules

#: How many candidates a review queue returns at most — a worklist, not a corpus dump.
MAX_CANDIDATES = 200

#: The current canonical per cluster. Every query here is over the CURRENT version
#: only: a role that has been edited must appear once, as its newest draft.
_CURRENT = """
    SELECT DISTINCT ON (cluster_id) *
    FROM canonical_jds ORDER BY cluster_id, version DESC
"""

#: Approvability lives ONLY here. ``validation_reports`` is empty and every draft's
#: ``validation_report_id`` is NULL, so a query against that table returns 0 approvable
#: and looks exactly like a real answer.
_APPROVED = "(change_log->'validator'->'gate_decision'->>'approved')::boolean"

#: Title + summary + duties, lowercased — the text a family's terms are matched over.
_BODY = """
    lower(coalesce(c.content->>'title','') || ' ' ||
          coalesce(c.content->>'position_summary','') || ' ' ||
          coalesce(c.content->'duties','[]'::jsonb)::text)
"""


def python_patterns(terms: Sequence[str]) -> tuple[re.Pattern[str], ...]:
    """Each family term as its own Python word-boundary regex.

    **One regex per term, not one alternation over all of them**, because the score is
    a count of TERMS. Under a single alternation, ``servers?`` matching both "server"
    and "servers" in one JD counts twice — one concept, two points, and a role that
    happens to use both spellings outranks one that does not. Per-term matching is what
    makes the count mean what its name says.

    ⚠ **Word boundaries are load-bearing, not an optimisation.** Matched as bare
    substrings, the three-letter term ``lan`` also matches "plan", "planning" and
    "Langara": measured at 1,568 of 2,493 roles — 63% of the corpus from one term. A
    substring sweep produces a confident, wrong, *plausible-looking* cohort, and 63% is
    not obviously absurd when you already expect the family to be bigger than the org
    chart suggests. :func:`postgres_patterns` is the same rule in Postgres' dialect,
    and a test pins the two to the same verdict on exactly that case.
    """
    return tuple(
        re.compile(rf"\b(?:{term})\b", re.IGNORECASE) for term in terms if term
    )


def postgres_patterns(terms: Sequence[str]) -> list[str]:
    """Each family term as its own Postgres word-boundary regex.

    Postgres spells the boundaries ``\\m`` (start) and ``\\M`` (end), not ``\\b``. The
    list is passed to SQL as a single ``text[]`` parameter and counted with
    ``unnest`` — so the SQL counts terms exactly as :func:`score_text` does, rather
    than approximating it with a different expression that could drift.
    """
    return [rf"\m({term})\M" for term in terms if term]


def score_text(body: str, terms: Sequence[str]) -> int:
    """How many DISTINCT family terms ``body`` contains.

    ⚠ A ranking signal only. It is never compared against a cutoff to decide whether a
    role belongs to a family — see the module note.
    """
    return sum(1 for pattern in python_patterns(terms) if pattern.search(body))


def family_for(slug: str, rules: Rules | None = None) -> FunctionalFamily | None:
    """The family a collection URL names (``?collection=it``), or ``None``."""
    resolved = rules if rules is not None else get_rules()
    return resolved.functional_families.by_slug(slug)


def _classification_regex(family: FunctionalFamily) -> str | None:
    """The classification-family token match against a FILENAME.

    Filenames are not prose (``20060503_30181_ITP_III_Gr_12.doc``), so this is not
    ``\\m``/``\\M``. The rule is **preceded by a non-letter, and not followed by a
    lowercase letter**, which is asymmetric on purpose:

    * the *leading* boundary is what rejects a fragment — ``EXITPLAN`` contains "ITP"
      but is not an ITP job description;
    * the *trailing* side must NOT require a non-letter, because the archive jams the
      level onto the code with no separator: ``20120103_101503ITPIII.doc``,
      ``20120216_00102623ITPI,_Gr._10.doc``. A symmetric boundary silently dropped 10
      genuine ITP documents and turned the collection's own headline from
      "469 documents → 45 roles" into "449 → 44" — the published figure and the shipped
      page disagreeing by exactly the kind of margin nobody notices until it is on a
      screen in front of the CIO.

    "Not a lowercase letter" keeps both: SFU's codes and their level suffixes are
    uppercase, so ``ITPIII`` matches while ``ITPlanning`` does not. It follows that the
    match is **case-sensitive** — a case-insensitive ``[^a-z]`` would mean nothing.
    Verified against the archive: no lowercase spelling of any code exists.
    """
    if not family.classification_families:
        return None
    body = "|".join(re.escape(f) for f in family.classification_families)
    return rf"(^|[^A-Za-z])({body})([^a-z]|$)"


# --- membership: the authority ----------------------------------------------------


async def resolve_members(
    session: AsyncSession, family: FunctionalFamily
) -> frozenset[UUID]:
    """The cluster ids in ``family``: classification family ∪ include − exclude.

    **Resolved against the live Bank, never frozen into the rulebook.** Cluster ids are
    not stable across a re-clustering run, so a rulebook holding 45 of them would rot
    silently into a family pointing at nothing.

    ``exclude`` is applied last and beats every other signal on purpose: a human ruling
    always wins over a rule.

    Reads no duty text. **The term lists cannot put a role in a family** (module note).
    """
    matched: set[UUID] = set()
    pattern = _classification_regex(family)
    if pattern is not None:
        rows = await session.execute(
            text(f"""
                WITH cur AS ({_CURRENT})
                SELECT DISTINCT c.cluster_id
                FROM cur c, jsonb_array_elements(c.source_document_ids) s
                JOIN source_documents d
                  ON d.id = (s.value->>'source_id')::uuid
                WHERE d.filename ~ :pattern
            """),
            {"pattern": pattern},
        )
        matched.update(row[0] for row in rows)
    matched.update(family.include)
    return frozenset(matched - set(family.exclude))


async def collection_stats(
    session: AsyncSession, family: FunctionalFamily
) -> CollectionStats:
    """The headline for a family's collection page — roles, documents, approvable.

    ``source_documents`` counts the documents behind the family's roles, which is the
    compression story ("469 documents became 45 roles"). It is deliberately reported
    alongside ``roles`` and never on its own.
    """
    members = await resolve_members(session, family)
    if not members:
        return CollectionStats(
            label=family.label,
            slug=family.slug,
            roles=0,
            source_documents=0,
            approvable=0,
            recall_note=family.recall_note,
        )
    row = (
        await session.execute(
            text(f"""
                WITH cur AS ({_CURRENT})
                SELECT count(*),
                       coalesce(sum(jsonb_array_length(source_document_ids)), 0),
                       count(*) FILTER (WHERE {_APPROVED})
                FROM cur WHERE cluster_id = ANY(:ids)
            """),
            {"ids": list(members)},
        )
    ).one()
    return CollectionStats(
        label=family.label,
        slug=family.slug,
        roles=int(row[0]),
        source_documents=int(row[1]),
        approvable=int(row[2]),
        recall_note=family.recall_note,
    )


# --- the review queue: ordering only ----------------------------------------------


async def rank_candidates(
    session: AsyncSession,
    family: FunctionalFamily,
    *,
    limit: int = MAX_CANDIDATES,
    rules: Rules | None = None,
) -> tuple[FamilyCandidate, ...]:
    """Roles that are NOT yet in ``family``, ranked by family-term density.

    **A worklist for a human, not a membership answer.** Every row carries its score so
    a reviewer can see why it surfaced, and the score is shown as a count of matched
    terms — never as a percentage or a confidence, because it is neither.

    ``review_queue_min_score`` truncates the list. It is a queue depth: at the shipped
    value the sweep finds only 17.8% of the roles SFU itself classifies as IT, so using
    it to *decide* the family would discard three of every four of them.
    """
    resolved = rules if rules is not None else get_rules()
    cutoff = resolved.functional_families.review_queue_min_score
    duty = postgres_patterns(family.duty_terms)
    title = postgres_patterns(family.title_terms)
    if not duty and not title:
        return ()
    members = await resolve_members(session, family)
    # An EMPTY term list must contribute 0, not match everything. `unnest` over an
    # empty array yields no rows and so counts 0 — the safe direction — but it is
    # stated here because the opposite mistake (an empty pattern matching every row)
    # is the one that produces a confident, wrong cohort.
    rows = await session.execute(
        text(f"""
            WITH cur AS ({_CURRENT}),
            scored AS (
              SELECT c.cluster_id,
                     c.id AS canonical_id,
                     c.content->>'title' AS title,
                     c.status::text AS status,
                     jsonb_array_length(c.source_document_ids) AS sources,
                     c.content->>'department' AS department,
                     (SELECT count(*) FROM unnest(CAST(:duty AS text[])) t
                        WHERE {_BODY} ~ t)::int AS duty_hits,
                     (SELECT count(*) FROM unnest(CAST(:title AS text[])) t
                        WHERE lower(coalesce(c.content->>'title','')) ~ t)::int
                        AS title_hits
              FROM cur c
              WHERE NOT (c.cluster_id = ANY(CAST(:members AS uuid[])))
            )
            SELECT cluster_id, canonical_id, title, status, sources, department,
                   duty_hits, title_hits
            FROM scored
            WHERE duty_hits + title_hits >= :cutoff
            ORDER BY duty_hits + title_hits DESC, sources DESC, title ASC
            LIMIT :limit
        """),
        {
            "duty": duty,
            "title": title,
            "members": [str(m) for m in members],
            "cutoff": cutoff,
            "limit": max(1, min(limit, MAX_CANDIDATES)),
        },
    )
    return tuple(
        FamilyCandidate(
            cluster_id=row.cluster_id,
            canonical_id=row.canonical_id,
            title=row.title or "(untitled)",
            status=row.status,
            source_count=int(row.sources or 0),
            department=row.department,
            duty_matches=int(row.duty_hits or 0),
            title_matches=int(row.title_hits or 0),
        )
        for row in rows
    )

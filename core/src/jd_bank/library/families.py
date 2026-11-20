"""Functional role families — gathering roles by what people DO (Phase A2).

The read side of ``functional_families.yaml``. Two operations, and the distinction
between them is the whole point of this module:

* :func:`resolve_members` — **who is in the family.** Every DIRECT signal unioned —
  the classification code in the filename, the role's title, the department it names —
  plus reviewed ``include``, minus reviewed ``exclude``. It reads no duty text.
* :func:`rank_candidates` — **who a reviewer should look at next.** A ranked worklist.
* :func:`membership_coverage` — **what the signals could NOT see.** Never optional.

**Recall first, and it is the correction to a measured failure.** Membership was once
the filename code alone, and 9,481 of 14,565 documents (65%) carry no code in their
filename — so the IT collection reported 45 roles where the archive holds ~211, and
presented that as "the IT function". A false positive is rejected in review; a false
negative is invisible. See ``docs/FINDINGS.md`` §3.

**A score still cannot decide membership.** Scored against the ITP seed, 98% recall
costs
46% of the archive and a plausible-sized cohort keeps 48.9% — no cut point works, so
``duty_terms`` ranks the queue and never confers membership. A direct attribute is
different evidence from a similarity score. ⚠ And that seed shared the filter's blind
spot, which is why 98% recall against it meant so little (``FINDINGS.md`` §4a).

Read-only (NN #1): nothing here mutates a row, publishes, or touches a gate.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.jd_bank.library.models import (
    CollectionStats,
    FamilyCandidate,
    MembershipCoverage,
    SignalCoverage,
)
from src.jd_core.parser import FALLBACK_TITLE
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


@dataclass(frozen=True)
class _Signal:
    """One membership signal: what it is called, when one document row matches it, and
    when that row cannot be judged by it at all."""

    label: str
    #: SQL over one ``doc`` row (:data:`_DOC_CTE`). NULL counts as "no match".
    predicate: str
    #: SQL true when the row lacks the attribute the signal reads — its blind spot.
    #: A role is unevaluable only when EVERY one of its rows is blind.
    blind: str


#: Every current role joined to each of its source documents: one row per (role,
#: document), and one row with a NULL document for a role that has none.
#:
#: Title and department are read out of ``content`` ONCE PER ROLE, inside the
#: DISTINCT ON (which Postgres cannot flatten). Read after the join, the large jsonb
#: was de-TOASTed once per DOCUMENT row (~11,000 on the live Bank) and the OR of the
#: signals took ~2.6 s where each alone took < 0.6 s.
_DOC_CTE = """
    WITH cur AS (
      SELECT DISTINCT ON (cluster_id) cluster_id, source_document_ids,
             content->>'title' AS title,
             content->>'department' AS department
      FROM canonical_jds ORDER BY cluster_id, version DESC
    ),
    doc AS (
      SELECT c.cluster_id, d.filename, c.title, c.department
      FROM cur c
      LEFT JOIN LATERAL jsonb_array_elements(c.source_document_ids) s ON TRUE
      LEFT JOIN source_documents d ON d.id = (s.value->>'source_id')::uuid
    )
"""


def _signals(family: FunctionalFamily) -> tuple[list[_Signal], dict[str, object]]:
    """The family's configured signals, each carrying its OWN label, and their bound
    parameters. A signal and its label travel together: pairing them by position
    once reported the title count as the filename-code count for any family with no
    codes."""
    signals: list[_Signal] = []
    params: dict[str, object] = {}
    classification = _classification_regex(family)
    if classification is not None:
        signals.append(
            _Signal(
                "classification code in the filename",
                "filename ~ :classification",
                "filename IS NULL",
            )
        )
        params["classification"] = classification
    if family.title_terms:
        signals.append(
            _Signal(
                "the role's title",
                "EXISTS (SELECT 1 FROM unnest(CAST(:title_terms AS text[])) t"
                " WHERE lower(coalesce(title,'')) ~ t)",
                f"coalesce(title, '') = '' OR title = '{FALLBACK_TITLE}'",
            )
        )
        params["title_terms"] = postgres_patterns(family.title_terms)
    if family.department_terms:
        # The terms are lowered and trimmed ONCE (an uncorrelated ARRAY(...) is an
        # InitPlan), not once per row: the per-row form cost ~1.9 s on the live Bank.
        signals.append(
            _Signal(
                "the department",
                "lower(trim(coalesce(department,''))) = ANY(ARRAY("
                "SELECT lower(trim(d)) FROM unnest(CAST(:department_terms AS text[])) d"
                "))",
                "coalesce(department, '') = ''",
            )
        )
        params["department_terms"] = list(family.department_terms)
    return signals, params


def _membership_predicates(
    family: FunctionalFamily,
) -> tuple[list[str], dict[str, object]]:
    """The SQL for each membership signal, and its bound parameters.

    Returned as a list so the live smoke can evaluate them one at a time and check
    the union. **A signal nobody can see the contribution of is a signal nobody can
    check.**
    """
    signals, params = _signals(family)
    return [s.predicate for s in signals], params


async def resolve_members(
    session: AsyncSession, family: FunctionalFamily
) -> frozenset[UUID]:
    """The cluster ids in ``family`` — **every signal unioned**, minus reviewed
    removals.

    🔴 **Recall first. A filter that cannot see a document is worse than a wrong one**,
    because a missing role is invisible and a wrong one gets rejected in review.

    That is not a preference; it is the correction to a measured failure. Membership was
    once the classification code in the source FILENAME alone — and **9,481 of 14,565
    documents (65%) carry no code in their filename at all**. The IT collection
    therefore
    reported 45 roles when the archive holds ~210, and reported it as "the IT function"
    with no statement of what the signal could not see. For an employer the size of ITS
    that is not a rounding error, it is a credibility failure.

    Three signals, each a DIRECT ATTRIBUTE of the document rather than a score:

    * ``classification_families`` — SFU's own job-family code in the filename;
    * ``title_terms`` — the role's title;
    * ``department_terms`` — the unit the JD names.

    ``duty_terms`` is deliberately **absent**: it is a score, and no cut point of it was
    both precise and complete (see ``docs/FINDINGS.md`` §4a). It ranks the review queue
    and never decides membership. A direct attribute match is a different kind of
    evidence from a similarity score, which is why these three may decide and it may
    not.

    ``include`` adds, ``exclude`` removes, and ``exclude`` is applied last so a human
    ruling beats every rule. **False positives are the reviewer's job; false negatives
    are invisible and therefore ours.**

    Use :func:`membership_coverage` to report what this did NOT match. A count without
    its blind spot stated is the defect this docstring exists to prevent.
    """
    predicates, params = _membership_predicates(family)
    matched: set[UUID] = set()
    if predicates:
        rows = await session.execute(
            text(
                f"{_DOC_CTE} SELECT DISTINCT cluster_id FROM doc "
                f"WHERE {' OR '.join(predicates)}"
            ),
            params,
        )
        matched.update(row[0] for row in rows)
    matched.update(family.include)
    return frozenset(matched - set(family.exclude))


async def collection_stats(
    session: AsyncSession,
    family: FunctionalFamily,
    *,
    members: frozenset[UUID] | None = None,
) -> CollectionStats:
    """The headline for a family's collection page — roles, documents, approvable.

    ``source_documents`` counts the documents behind the family's roles, which is the
    compression story ("469 documents became 45 roles"). It is deliberately reported
    alongside ``roles`` and never on its own. Pass ``members`` (from
    :func:`resolve_members`) when the caller already has them.
    """
    if members is None:
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

    **A DEPARTMENT match reaches the queue regardless of score**, and that is
    deliberate.
    Measured: 47 roles carried an ITS department without the ITP classification, and 45
    of them were surfaced nowhere at all — *Systems Administrator*, *Senior Systems
    Engineer*, *PeopleSoft Developer*, *Research Computing Analyst*. Their duty text
    scores below any usable cutoff, so ranking alone could never have found them, and an
    IT director looking for their own staff would not have seen them. Union the signals;
    never intersect them. ⚠ It raises a **candidate**, never a member.
    """
    resolved = rules if rules is not None else get_rules()
    cutoff = resolved.functional_families.review_queue_min_score
    duty = postgres_patterns(family.duty_terms)
    title = postgres_patterns(family.title_terms)
    departments = list(family.department_terms)
    if not duty and not title and not departments:
        return ()
    members = await resolve_members(session, family)
    # An EMPTY term list must contribute 0, not match everything. `unnest` over an
    # empty array yields no rows and so counts 0 — the safe direction — but it is
    # stated here because the opposite mistake (an empty pattern matching every row)
    # is the one that produces a confident, wrong cohort.
    rows = await session.execute(
        text(f"""
            WITH cur AS ({_CURRENT}),
            -- Each role's text is built ONCE, here (MATERIALIZED, so the planner
            -- cannot inline it back). Written inside the per-term subquery it was
            -- rebuilt — title + summary + every duty, lowercased — once per duty TERM,
            -- and the IT queue took ~13 s on the live Bank.
            base AS MATERIALIZED (
              SELECT c.cluster_id,
                     c.id AS canonical_id,
                     c.content->>'title' AS title,
                     c.status::text AS status,
                     jsonb_array_length(c.source_document_ids) AS sources,
                     c.content->>'department' AS department,
                     {_BODY} AS body
              FROM cur c
              WHERE NOT (c.cluster_id = ANY(CAST(:members AS uuid[])))
            ),
            scored AS (
              SELECT b.cluster_id, b.canonical_id, b.title, b.status, b.sources,
                     b.department,
                     (SELECT count(*) FROM unnest(CAST(:duty AS text[])) t
                        WHERE b.body ~ t)::int AS duty_hits,
                     (SELECT count(*) FROM unnest(CAST(:title AS text[])) t
                        WHERE lower(coalesce(b.title,'')) ~ t)::int
                        AS title_hits,
                     -- Department is compared case-INSENSITIVELY and whole-string:
                     -- `FACILITIES SERVICES` and `Facilities Services` are two distinct
                     -- strings in this archive, and a substring match would sweep in
                     -- `School of Computing Science`, an academic unit that is not ITS.
                     EXISTS (
                       SELECT 1 FROM unnest(CAST(:departments AS text[])) d
                       WHERE lower(trim(coalesce(b.department,''))) =
                             lower(trim(d))
                     ) AS department_match
              FROM base b
            )
            SELECT cluster_id, canonical_id, title, status, sources, department,
                   duty_hits, title_hits, department_match
            FROM scored
            WHERE duty_hits + title_hits >= :cutoff OR department_match
            ORDER BY duty_hits + title_hits DESC, sources DESC, title ASC
            LIMIT :limit
        """),
        {
            "duty": duty,
            "title": title,
            "departments": departments,
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
            department_match=bool(row.department_match),
        )
        for row in rows
    )


async def membership_coverage(
    session: AsyncSession,
    family: FunctionalFamily,
    *,
    members: frozenset[UUID] | None = None,
) -> MembershipCoverage:
    """What each membership signal found, and **what none of them could see**.

    🔴 **The point of this function is the last number.** A collection that reports "45
    roles" without reporting the population it could not evaluate is unfalsifiable: a
    reader cannot tell a small function from a blind filter. That is precisely how
    the IT
    collection reported a third of ITS and looked correct doing it.

    Every role in the Bank lands in exactly one of: a member, a candidate for review, or
    unmatched by any signal. The three sum to the whole Bank — and the page shows all
    three, so the claim can be checked rather than believed.

    "Cannot judge at all" (:attr:`_Signal.blind`) is not "looked and found nothing": a
    department signal says nothing whatever about a role with no department recorded,
    and reporting the two as one number is how a filter becomes unfalsifiable. A role
    is unevaluable for a signal only when NONE of its documents carries the attribute —
    one usable filename or department is enough to speak for it.

    ONE grouped pass over the role/document join. It was seven queries, three of them a
    ``NOT IN`` anti-join, and took ~20 s of the IT page's ~25 s on the live Bank.
    """
    signals, params = _signals(family)
    per_role = ",\n".join(
        f"bool_or({s.predicate}) AS m{i}, bool_and(coalesce(({s.blind}), true)) AS u{i}"
        for i, s in enumerate(signals)
    )
    counts = ", ".join(
        f"count(*) FILTER (WHERE m{i}), count(*) FILTER (WHERE u{i})"
        for i in range(len(signals))
    )
    row = (
        await session.execute(
            text(
                f"{_DOC_CTE}, per AS (SELECT cluster_id"
                f"{', ' + per_role if per_role else ''} FROM doc GROUP BY cluster_id) "
                f"SELECT count(*){', ' + counts if counts else ''} FROM per"
            ),
            params,
        )
    ).one()
    per_signal = tuple(
        SignalCoverage(
            label=s.label,
            roles=int(row[1 + 2 * i] or 0),
            unevaluable=int(row[2 + 2 * i] or 0),
        )
        for i, s in enumerate(signals)
    )
    if members is None:
        members = await resolve_members(session, family)
    return MembershipCoverage(
        total_roles=int(row[0] or 0),
        members=len(members),
        signals=per_signal,
        included_by_hand=len(family.include),
        excluded_by_hand=len(family.exclude),
    )

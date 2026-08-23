"""What the live Bank actually contains, per FORM — the carry-through audit.

🔴 WHY THIS EXISTS. Every content-loss defect in Phases A–G was found the same way: by
someone hand-writing SQL against the live Bank, usually days after the pass that caused
it, and usually after a fix had already been reported as landed. The pattern is worth
stating because it repeated four times:

* a fix is verified by ``make gates`` (a claim about the TESTS) and by a handful of
  sampled clusters (a claim about the SAMPLE), and reported as done;
* the defect is in the other 99% of the cohort;
* nothing in the producer's own summary can see it, because the summary counts
  CLUSTERS PROCESSED, not CONTENT KEPT — ``refreshed=649 failures=0`` prints identically
  whether the run enriched every draft or gutted it.

HR-209 is the worked example. It was measured over the five largest all-CUPE clusters
and reported duty-frequency retention rising 27.8% → 43.8%. Measured here over all 649:
**24.1%.** The sample was not wrong about the five clusters; it was never evidence about
the cohort. This module is the thing that makes the cohort answer cheap enough that
nobody is tempted to quote a sample again.

**The organising idea is CARRY-THROUGH, not counts.** For each section, two numbers that
only mean something together:

* how many clusters had that content **in their source documents** (what the archive
  offered), and
* how many drafts **carry it now** (what the Bank kept).

A count alone is unreadable — "620 drafts carry point-factor content" is either perfect
or a disaster depending on whether 620 or 6,490 clusters had any. The ratio is the
signal, and a ratio that falls between two runs is a content-loss defect, stated in the
one form that cannot be argued with.

**Per FORM, never blended** (CUPE Phase D). A JDFN draft and a CUPE draft are judged by
different rules against different thresholds, so a single number over both is a mean
over two different measurements. Every metric here is keyed by template.

**Read-only.** This module opens a session, runs SELECTs and returns models. It writes
no row, mutates nothing, and takes no rulebook decision — it reports what is there. It
is therefore safe to run against production while a producer pass is in flight, though
the numbers will be mid-flight if you do.
"""

from __future__ import annotations

from typing import cast

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.jd_bank.bank_audit.models import (
    BankAudit,
    CarryThrough,
    FormAudit,
    GateBlock,
    RewriteHealth,
)
from src.jd_core.models.quality import JDTemplate
from src.jd_core.parser.segmenter import PARSER_VERSION
from src.jd_core.rules import Rules, get_rules

#: The parser version whose rows are the archive of record. Everything here reads the
#: same population the producer reads, so an audit and a run can never disagree about
#: which documents exist.
#:
#: ⚠ IMPORTED, NOT COPIED — it was a hardcoded `"jd_segmenter_v4"` until the v5 bump,
#: which is the one thing that CAN make an audit and a run disagree. Every other
#: consumer filters on the constant itself; this module alone held a duplicate, so a
#: bump would have left the audit reporting the OLD corpus against the NEW Bank and
#: calling the difference content loss.
_PARSER_VERSION = PARSER_VERSION

#: `employee_group` -> the FORM that group's documents are written on. The same
#: separator `template_of` applies, expressed in SQL because this module aggregates over
#: the whole corpus rather than validating one JD. Kept as a single mapping so the two
#: cannot drift silently: `tests/unit/test_bank_audit.py` pins it against
#: `jd_core.quality.validators.template_of` over every known group.
_WJQ_GROUPS = ("cupe",)


def _group_sql(template: str) -> str:
    """The ``employee_group`` predicate selecting ONE form's documents.

    🔴 JDFN IS "NOT CUPE", NOT "apsa/apex/poly" — and getting that wrong was this
    module's own first bug, caught by its own first run. Spelling the JDFN side as an
    explicit allow-list silently omitted **1,300 drafts** whose ``employee_group`` is
    null: 31.9% of the archive does not state its group in a way the reader has
    recovered yet, and those documents are still parsed, still drafted and still scored.
    The audit reported 541 JDFN drafts where the Bank holds 1,841.

    ``template_of`` treats every non-CUPE document as JDFN, so this must too, or the two
    partitions disagree and the audit quietly under-reports the cohort it exists to
    watch. ``IS DISTINCT FROM`` (not ``<>``) because ``NULL <> 'cupe'`` is NULL, which
    is exactly how the 1,300 vanished.
    """
    if template == "wjq":
        return f"IN {_WJQ_GROUPS!r}".replace(",)", ")")
    return f"IS DISTINCT FROM {_WJQ_GROUPS[0]!r}"


async def _scalar(session: AsyncSession, sql: str) -> int:
    value = await session.scalar(text(sql))
    return int(value or 0)


async def _carry_through(
    session: AsyncSession, *, template: str, section: str, policy: str | None = None
) -> CarryThrough:
    """One section's SOURCE availability vs DRAFT presence, for one form.

    ``offered`` counts CLUSTERS with at least one source document carrying the section —
    the honest denominator, because a cluster whose sources are all silent cannot lose
    anything and must not be counted as a miss. ``kept`` counts the DRAFTS with it.
    """
    groups = _group_sql(template)
    # The section's "is present" test differs by shape: two are JSON arrays, one is an
    # object that may be present-but-null, one is a string.
    if section in ("decision_making", "problem_solving"):
        src = f"jsonb_array_length(coalesce(p.parsed->'{section}','[]'::jsonb)) > 0"
        dst = f"jsonb_array_length(coalesce(j.content->'{section}','[]'::jsonb)) > 0"
    elif section == "relationships":
        src = "p.parsed->'relationships' IS NOT NULL "
        src += "AND p.parsed->'relationships' <> 'null'::jsonb"
        dst = "j.content->'relationships' IS NOT NULL "
        dst += "AND j.content->'relationships' <> 'null'::jsonb"
    else:  # additional_context — the WJQ point-factor blocks
        src = f"coalesce(p.parsed->>'{section}','') <> ''"
        dst = f"coalesce(j.content->>'{section}','') <> ''"

    offered = await _scalar(
        session,
        f"""
        SELECT count(*) FROM clusters c
        JOIN canonical_jds j ON j.cluster_id = c.id AND j.status = 'DRAFT'
        WHERE j.content->>'employee_group' {groups}
          AND EXISTS (
            SELECT 1 FROM jsonb_array_elements(c.members) m
            JOIN parsed_jds p ON p.source_document_id = (m->>'source_id')::uuid
            WHERE p.parser_version = '{_PARSER_VERSION}' AND ({src}))
        """,
    )
    kept = await _scalar(
        session,
        f"""
        SELECT count(*) FROM canonical_jds j
        WHERE j.status = 'DRAFT' AND j.content->>'employee_group' {groups}
          AND ({dst})
        """,
    )
    return CarryThrough(section=section, offered=offered, kept=kept, policy=policy)


async def _rewrite_health(session: AsyncSession, *, template: str) -> RewriteHealth:
    """What the LLM rewrite did to this form's drafts — including the natural
    experiment that identifies it as the cause of a loss rather than a correlate.

    🔴 THE SPLIT IS THE POINT. A rewrite FAILURE is not a corrupted draft: the cluster
    falls back to the deterministic merge, so those rows are the same pipeline with the
    model removed. Comparing duty-frequency retention across that split is a controlled
    comparison the Bank produces for free, and it is what turned "frequencies are low"
    into "the rewrite destroys them": measured 2026-08-22 over the CUPE cohort, drafts
    whose rewrite landed retained **23.5%** and drafts whose rewrite failed retained
    **75.0%**, against a source availability of 79.7%.
    """
    groups = _group_sql(template)
    base = (
        f"FROM canonical_jds j WHERE j.status='DRAFT' "
        f"AND j.content->>'employee_group' {groups}"
    )

    async def freq(rewrite_failed: bool) -> tuple[int, int]:
        rows = await session.execute(text(f"""
                WITH d AS (
                  SELECT jsonb_array_elements(j.content->'duties') AS duty
                  {base} AND coalesce(
                    (j.change_log->'pipeline'->>'rewrite_failed')::boolean, false)
                    = {"true" if rewrite_failed else "false"})
                SELECT count(*),
                       count(*) FILTER (WHERE coalesce(duty->>'frequency','') <> '')
                FROM d
                """))
        total, kept = rows.one()
        return int(total or 0), int(kept or 0)

    rewritten_duties, rewritten_freq = await freq(False)
    merge_only_duties, merge_only_freq = await freq(True)

    flagged = await session.execute(text(f"""
            SELECT count(*),
              coalesce(sum(jsonb_array_length(coalesce(
                j.change_log->'anti_fabrication'->'flagged_duties','[]'::jsonb))), 0),
              coalesce(sum(jsonb_array_length(coalesce(
                j.content->'duties','[]'::jsonb))), 0),
              count(*) FILTER (WHERE jsonb_array_length(coalesce(
                j.change_log->'anti_fabrication'->'flagged_duties','[]'::jsonb)) > 0)
            {base}
            """))
    drafts, flagged_total, duties_total, drafts_flagged = flagged.one()

    return RewriteHealth(
        rewritten_duties=rewritten_duties,
        rewritten_with_frequency=rewritten_freq,
        merge_only_duties=merge_only_duties,
        merge_only_with_frequency=merge_only_freq,
        duties_total=int(duties_total or 0),
        duties_flagged=int(flagged_total or 0),
        drafts=int(drafts or 0),
        drafts_with_a_flagged_duty=int(drafts_flagged or 0),
    )


async def _blocking_gates(
    session: AsyncSession, *, template: str, limit: int = 6
) -> list[GateBlock]:
    """The gates keeping this form's drafts unapprovable, commonest first — the answer
    to "why is only N of M approvable?", which is the first question any reviewer asks
    and the producer summary cannot answer."""
    rows = await session.execute(text(f"""
            WITH g AS (
              SELECT jsonb_array_elements(
                j.change_log->'validator'->'gate_decision'->'blocking') AS b
              FROM canonical_jds j
              WHERE j.status='DRAFT' AND j.content->>'employee_group'
                {_group_sql(template)})
            SELECT b->>'gate_id', count(*) FROM g GROUP BY 1
            ORDER BY 2 DESC LIMIT {int(limit)}
            """))
    return [GateBlock(gate_id=str(g), drafts=int(n)) for g, n in rows if g]


async def _form_audit(
    session: AsyncSession, *, template: str, rules: Rules | None = None
) -> FormAudit:
    groups = _group_sql(template)
    totals = await session.execute(text(f"""
            SELECT count(*),
                   coalesce(round(avg((j.change_log->'validator'->>'score')::numeric),
                     2), 0),
                   coalesce(round(avg(jsonb_array_length(coalesce(
                     j.content->'duties','[]'::jsonb))), 2), 0),
                   count(*) FILTER (WHERE (j.change_log->'validator'->'gate_decision'
                     ->>'approved')::boolean)
            FROM canonical_jds j
            WHERE j.status='DRAFT' AND j.content->>'employee_group' {groups}
            """))
    drafts, mean_score, mean_duties, approvable = totals.one()

    # The REGISTERED merge policy per section, resolved for THIS form — so a section
    # the rulebook deliberately drops is reported as a policy rather than flagged as a
    # loss (HR-169's `drop` on JDFN `additional_context` is the live example).
    harmon = (rules if rules is not None else get_rules()).harmonization_for(
        cast("JDTemplate", template)
    )
    policies: dict[str, str] = {
        "additional_context": harmon.additional_context_policy,
        "relationships": harmon.relationships_policy,
        "decision_making": harmon.decision_making_policy,
        "problem_solving": harmon.problem_solving_policy,
    }
    carry = [
        await _carry_through(session, template=template, section=s, policy=policies[s])
        for s in policies
    ]
    return FormAudit(
        template=template,
        drafts=int(drafts or 0),
        mean_score=float(mean_score or 0),
        mean_duties=float(mean_duties or 0),
        approvable=int(approvable or 0),
        carry_through=tuple(carry),
        rewrite=await _rewrite_health(session, template=template),
        blocking_gates=tuple(await _blocking_gates(session, template=template)),
    )


async def audit_bank(session: AsyncSession, *, rules: Rules | None = None) -> BankAudit:
    """Audit the live Bank, per form. Read-only; commits nothing."""
    published = await _scalar(
        session, "SELECT count(*) FROM canonical_jds WHERE status='PUBLISHED'"
    )
    documents = await _scalar(
        session,
        f"SELECT count(*) FROM parsed_jds WHERE parser_version='{_PARSER_VERSION}'",
    )
    return BankAudit(
        documents_parsed=documents,
        published=published,
        forms=tuple(
            [
                await _form_audit(session, template="jdfn", rules=rules),
                await _form_audit(session, template="wjq", rules=rules),
            ]
        ),
    )

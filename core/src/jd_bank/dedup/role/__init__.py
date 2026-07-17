"""Tier-3 role-equivalence dedup (Phase 3.4b): the SAME-ROLE pass. Writes
``dedup_edges`` rows at ``tier=ROLE_EQUIVALENT`` for pairs that are the same role even
when their text differs (Tier-3's added value over Tier-2's near-dup).

    from src.jd_bank.dedup.role import run_tier3
    result = await run_tier3(session, neo4j_driver=driver)  # caller commits

A separate subpackage from :mod:`src.jd_bank.dedup` (Tier-1) and :mod:`.near` (Tier-2):
Tier-3 reuses the 2.4c comparison maths (``build_job_signals`` -> ``skill_overlap`` +
``seniority_closeness`` + ``score_job_similarity``) with an idf corpus computed HERE,
and adds the hard family-band conflict veto — a different pass from either sibling, so
keeping them apart keeps each module's docstring true of the whole file it is in.
"""

from src.jd_bank.dedup.role.idf import IDF_VERSION, IdfCorpus, compute_idf
from src.jd_bank.dedup.role.models import (
    ROLE_EQUIV_VERSION,
    RoleDoc,
    RoleEdgeSpec,
    RolePairRecord,
    ScoredRolePair,
    Tier3Result,
)
from src.jd_bank.dedup.role.report import (
    DEFAULT_ADJUDICATION_TARGET,
    RoleEquivSummary,
    build_role_equiv_summary,
    sample_for_adjudication,
    write_adjudication_csv,
    write_summary,
)
from src.jd_bank.dedup.role.runner import (
    NEAR_TIER,
    ROLE_TIER,
    admit_and_score,
    band_vetoes,
    build_plan,
    generate_candidates,
    group_vetoes,
    run_tier3,
    score_role_pair,
    tier3_stamp,
)

__all__ = [
    "DEFAULT_ADJUDICATION_TARGET",
    "IDF_VERSION",
    "NEAR_TIER",
    "ROLE_EQUIV_VERSION",
    "ROLE_TIER",
    "IdfCorpus",
    "RoleDoc",
    "RoleEdgeSpec",
    "RoleEquivSummary",
    "RolePairRecord",
    "ScoredRolePair",
    "Tier3Result",
    "admit_and_score",
    "band_vetoes",
    "build_plan",
    "build_role_equiv_summary",
    "compute_idf",
    "generate_candidates",
    "group_vetoes",
    "run_tier3",
    "sample_for_adjudication",
    "score_role_pair",
    "tier3_stamp",
    "write_adjudication_csv",
    "write_summary",
]

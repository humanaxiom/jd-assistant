"""Tier-2 near-duplicate dedup (Phase 3.3): MinHash-candidate, exact-Jaccard-scored,
DB-reconciled ``dedup_edges`` rows at ``tier=NEAR_DUPLICATE``.

    from src.jd_bank.dedup.near import run_tier2, ArchiveTextSource
    result = await run_tier2(session, text_source=ArchiveTextSource())  # caller commits

A separate subpackage from :mod:`src.jd_bank.dedup` (Tier-1) rather than an addition
to it — Tier-1's ``__main__.py`` (the baseline-rows report) and its additive,
never-deletes contract are unrelated to Tier-2's DB-reconciling, text-re-reading
pass, and keeping them apart is what makes each module's docstring true of the whole
file it is in.
"""

from src.jd_bank.dedup.near.models import (
    NEAR_DUP_VERSION,
    CandidatePair,
    NearEdgeSpec,
    PairRecord,
    Signature,
    Tier2Result,
)
from src.jd_bank.dedup.near.report import (
    DEFAULT_ADJUDICATION_TARGET,
    NearDupSummary,
    build_near_dup_summary,
    sample_for_adjudication,
    write_adjudication_csv,
    write_summary,
)
from src.jd_bank.dedup.near.runner import (
    NEAR_TIER,
    CandidateOverflowError,
    run_tier2,
)
from src.jd_bank.dedup.near.text import (
    ArchiveTextSource,
    SerializedTextSource,
    TextResult,
    TextSource,
    text_source_for,
)

__all__ = [
    "DEFAULT_ADJUDICATION_TARGET",
    "NEAR_DUP_VERSION",
    "NEAR_TIER",
    "ArchiveTextSource",
    "CandidateOverflowError",
    "CandidatePair",
    "NearDupSummary",
    "NearEdgeSpec",
    "PairRecord",
    "SerializedTextSource",
    "Signature",
    "Tier2Result",
    "TextResult",
    "TextSource",
    "build_near_dup_summary",
    "run_tier2",
    "sample_for_adjudication",
    "text_source_for",
    "write_adjudication_csv",
    "write_summary",
]

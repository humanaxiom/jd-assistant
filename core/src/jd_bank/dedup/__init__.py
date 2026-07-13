"""Dedup — Tier 1 (exact), and the report over it.

Tier 1 groups ``source_documents`` by SHA-256 and records the duplicates as
``DedupEdge`` rows. **It is a finding, not a collapse:** the ledger keeps one row per
archive file (migration ``0002``), and duplication is something we *say about* those
rows, never something we do *to* them. Tiers 2 (MinHash + cosine) and 3 (embedding +
skill similarity) are later phases and will write into the same table.

    from src.jd_bank.dedup import run_tier1
    result = await run_tier1(session)     # idempotent; caller commits
"""

from src.jd_bank.dedup.models import (
    DedupReport,
    DocumentRef,
    DuplicateGroup,
    EdgeSpec,
    GroupSample,
    Tier1Result,
    order_key,
)
from src.jd_bank.dedup.report import (
    DEFAULT_TOP_GROUPS,
    build_dedup_report,
    positions_from_baseline_rows,
    read_baseline_rows,
    refs_from_baseline_rows,
    write_groups,
    write_report,
)
from src.jd_bank.dedup.tier1 import (
    EXACT_METHOD,
    EXACT_SCORE,
    EXACT_TIER,
    edge_counts,
    exact_edges,
    group_by_sha256,
    run_tier1,
)

__all__ = [
    "DEFAULT_TOP_GROUPS",
    "EXACT_METHOD",
    "EXACT_SCORE",
    "EXACT_TIER",
    "DedupReport",
    "DocumentRef",
    "DuplicateGroup",
    "EdgeSpec",
    "GroupSample",
    "Tier1Result",
    "build_dedup_report",
    "edge_counts",
    "exact_edges",
    "group_by_sha256",
    "order_key",
    "positions_from_baseline_rows",
    "read_baseline_rows",
    "refs_from_baseline_rows",
    "run_tier1",
    "write_groups",
    "write_report",
]

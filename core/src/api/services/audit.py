"""Audit-chain verification (ADR-008).

The ``audit_log`` hash chain (migration 0005) makes tampering DETECTABLE:
:func:`verify_audit_chain` recomputes every row's hash — using the SAME
``audit_log_payload()`` SQL function the trigger used, so there is no Python/SQL
format drift — and walks the prev_hash -> row_hash links from the genesis. Any altered
row (its recomputed hash won't match) or any deleted row (the walk won't reach every
chained row) makes it return ``ok = False``.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

#: The genesis prev_hash the tail is seeded with (migration 0005).
_GENESIS = b"\x00"


@dataclass(frozen=True)
class AuditVerifyResult:
    """The outcome of a chain verification."""

    ok: bool
    checked: int  #: chained rows visited
    total: int  #: chained rows present (row_hash not null)
    detail: str


async def verify_audit_chain(db: AsyncSession) -> AuditVerifyResult:
    """Verify the ``audit_log`` hash chain. ``ok`` iff every chained row's stored
    ``row_hash`` equals its recomputed hash AND the prev/row links form one unbroken
    chain from the genesis covering every chained row (no deletions/insertions)."""
    rows = (
        await db.execute(
            text(
                # Recompute in SQL (same audit_log_payload the trigger used).
                "SELECT prev_hash, row_hash, "
                "digest(coalesce(prev_hash, :genesis) || audit_log_payload("
                "created_at, actor, event_type, entity_type, entity_id, payload), "
                "'sha256') AS recomputed "
                "FROM audit_log WHERE row_hash IS NOT NULL"
            ),
            {"genesis": _GENESIS},
        )
    ).all()
    total = len(rows)
    if total == 0:
        return AuditVerifyResult(True, 0, 0, "empty chain")

    by_prev: dict[bytes, tuple[bytes, bytes]] = {}
    for prev_hash, row_hash, recomputed in rows:
        if bytes(recomputed) != bytes(row_hash):
            return AuditVerifyResult(
                False, 0, total, "a row's content does not match its hash (altered)"
            )
        by_prev[bytes(prev_hash)] = (bytes(row_hash), bytes(recomputed))

    # Walk the single chain from the genesis; every chained row must be reachable.
    checked = 0
    prev = _GENESIS
    while prev in by_prev:
        row_hash, _ = by_prev[prev]
        prev = row_hash
        checked += 1
    if checked != total:
        return AuditVerifyResult(
            False, checked, total, "chain is broken (a row was deleted or reordered)"
        )
    return AuditVerifyResult(True, checked, total, "chain intact")

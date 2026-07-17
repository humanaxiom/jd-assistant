"""The shared ``parsed_jds -> JobSignals`` loader (Phase 3.4b / 3.5).

Extracted verbatim from ``dedup/role/runner.py`` once the Tier-3 archive run had
finished: BOTH the Tier-3 role-equivalence runner and the Phase-3.5 clustering runner
turn every v2 ``parsed_jds`` row into a :class:`~src.jd_core.models.bank.JobSignals`,
joined to its ``source_documents`` row for orientation + filenames, and BOTH inherit the
same discipline — a row that fails to validate/sign is COUNTED (``unsignable``) and
dropped, never crashed on, and (the 3.3 data-loss lesson) never in prune scope.

Keeping one loader means the two callers cannot drift on *which* JDs are in scope. The
only addition over the Tier-3 private version is :attr:`SignedCorpus.confidence` — the
per-document ``parse_confidence`` the clustering runner needs to pick a cluster
representative (``cluster_representative_policy``). Tier-3 does not read it, so the
extraction is behaviour-preserving for it (pinned by the unchanged Tier-3 suite).
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.jd_bank.db.models import ParsedJDRow, SourceDocument
from src.jd_bank.dedup.models import DocumentRef
from src.jd_core.bank.signals import build_job_signals
from src.jd_core.models.bank import JobSignals
from src.jd_core.models.parsed_jd import SFUJobDescription
from src.jd_core.parser import PARSER_VERSION
from src.jd_core.rules import Rules


@dataclass(frozen=True, slots=True)
class SignedCorpus:
    """Every v2 ``parsed_jds`` row that could be turned into :class:`JobSignals`.

    ``signals``/``refs``/``confidence`` are keyed by ``source_document_id`` and share
    one key set — exactly the documents this run SIGNED, which is Tier-3's prune scope
    and the cluster scope Phase 3.5 clusters over. ``seen`` counts
    every row visited (post-``--limit``); ``unsignable`` counts the rows dropped because
    they would not validate.
    """

    signals: dict[UUID, JobSignals]
    refs: dict[UUID, DocumentRef]
    #: ``source_document_id -> parse_confidence`` — the cluster representative anchor.
    confidence: dict[UUID, float]
    seen: int
    unsignable: int


async def load_signed_corpus(
    session: AsyncSession, *, rules: Rules, limit: int | None
) -> SignedCorpus:
    """Every v2 ``parsed_jds`` row turned into :class:`JobSignals`, joined to its
    ``source_documents`` row for orientation + filenames. A row that fails to
    validate/sign is COUNTED (``unsignable``) and dropped — never crashed on, and
    never in prune/cluster scope.

    Deterministic ordering (``storage_ref`` then ``source_document_id``) so a limited
    smoke run reads a stable prefix. Pure read; commits nothing.
    """
    stmt = (
        select(
            ParsedJDRow.source_document_id,
            SourceDocument.sha256,
            SourceDocument.storage_ref,
            SourceDocument.filename,
            ParsedJDRow.parse_confidence,
            ParsedJDRow.parsed,
        )
        .join(SourceDocument, SourceDocument.id == ParsedJDRow.source_document_id)
        .where(ParsedJDRow.parser_version == PARSER_VERSION)
        .order_by(SourceDocument.storage_ref, ParsedJDRow.source_document_id)
    )
    if limit is not None:
        stmt = stmt.limit(limit)
    rows = await session.execute(stmt)

    signals: dict[UUID, JobSignals] = {}
    refs: dict[UUID, DocumentRef] = {}
    confidence: dict[UUID, float] = {}
    seen = 0
    unsignable = 0
    for source_id, sha256, storage_ref, filename, parse_confidence, parsed in rows:
        seen += 1
        try:
            jd = SFUJobDescription.model_validate(parsed)
            job_signals = build_job_signals(jd, rules=rules)
        except Exception:  # noqa: BLE001 - an unsignable JD is UNKNOWN, never a crash
            unsignable += 1
            continue
        signals[source_id] = job_signals
        refs[source_id] = DocumentRef(
            id=source_id, sha256=sha256, storage_ref=storage_ref, filename=filename
        )
        confidence[source_id] = parse_confidence
    return SignedCorpus(
        signals=signals,
        refs=refs,
        confidence=confidence,
        seen=seen,
        unsignable=unsignable,
    )

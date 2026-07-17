"""Content-keyed fakes for the Phase-3.5 clustering unit suite.

Fakes in this repo MUST be content-keyed (HANDOFF: a batch-index-keyed fake once made a
whole class of bug unwritable). Every id here is a ``uuid5`` of its ``key``, so
two fakes with the same key ARE the same document and a fake's identity follows its
content — never its construction order.
"""

from __future__ import annotations

from uuid import NAMESPACE_OID, UUID, uuid5

from src.jd_bank.cluster.models import ClusterEdge
from src.jd_bank.db.models import DedupTier
from src.jd_bank.dedup.models import DocumentRef
from src.jd_core.models.bank import JobSignals, TitleFamily, TitleFunction


def doc_id(key: str) -> UUID:
    """The stable id of the document named ``key``."""
    return uuid5(NAMESPACE_OID, key)


def ref(
    key: str, *, sha256: str | None = None, filename: str | None = None
) -> DocumentRef:
    """A :class:`DocumentRef` whose id + storage_ref derive from ``key``. ``sha256``
    defaults to a per-key hash (distinct content); pass a shared value to make two refs
    byte-identical."""
    return DocumentRef(
        id=doc_id(key),
        sha256=sha256 if sha256 is not None else uuid5(NAMESPACE_OID, key).hex * 2,
        storage_ref=f"archive/{key}.docx",
        filename=filename if filename is not None else f"{key}.docx",
    )


def sig(
    *,
    skills: frozenset[str] = frozenset(),
    family: TitleFamily = "unmapped",
    function: TitleFunction = "unmapped",
    employee_group: str | None = None,
    department: str | None = None,
    title: str = "Analyst",
    education_ordinal: int | None = None,
    experience_years: int | None = None,
    supervisory_reports: int | None = None,
    restricted: bool = False,
) -> JobSignals:
    """A :class:`JobSignals` with test-chosen classification signals; everything else a
    harmless default."""
    return JobSignals(
        skills=skills,
        education_ordinal=education_ordinal,
        experience_years=experience_years,
        supervisory_reports=supervisory_reports,
        title=title,
        normalized_title=title.lower(),
        family=family,
        function=function,
        comma_supervisory=False,
        restricted=restricted,
        employee_group=employee_group,
        department=department,
    )


def edge(
    a: str, b: str, *, tier: DedupTier, score: float, method: str = "test"
) -> ClusterEdge:
    """A :class:`ClusterEdge` between the documents named ``a`` and ``b``."""
    return ClusterEdge(a=doc_id(a), b=doc_id(b), tier=tier, score=score, method=method)

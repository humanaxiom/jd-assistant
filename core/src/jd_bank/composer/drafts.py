"""What happened to the drafts I submitted? — the read behind "My drafts" (P0.0).

The Builder's submit path (:mod:`src.jd_bank.composer.persist`) records the author on
the draft's own synthetic cluster (``constraint_metadata = {"origin": "composed",
"author": …}``) and in ``change_log["author"]``. Nothing read it back, so an author
submitted into the review queue and had **no page anywhere** telling them it existed —
the redirect went to the reviewer-only review page, which the default new-user role
(``author``) is refused from. This is the read that closes that loop.

**Read-only (NN #1)** and **scoped by the caller's identity, never by a parameter**: the
route passes the authenticated username straight in, so "my drafts" cannot be turned
into "anyone's drafts" by editing a URL. Unpublished draft JD content is exactly what
P0.1a was about.

**One row per role, not per version.** A reviewer's edit mints ``version + 1`` and
archives the prior row, so listing rows would show an author the same draft three times,
the newest of which is the only true one.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.jd_bank.composer.persist import COMPOSED_ORIGIN
from src.jd_bank.db.models import CanonicalJD, Cluster

#: How many of an author's drafts the page shows. Not a rulebook metric and not an HR
#: decision — a page-size, like the library's own.
DEFAULT_LIMIT = 50


class AuthoredDraft(BaseModel):
    """One draft an author submitted, as its author needs to see it."""

    canonical_id: UUID
    cluster_id: UUID
    title: str
    status: str
    version: int
    score: float | None
    grade: str | None
    created_at: datetime | None


def _title(canonical: CanonicalJD, cluster: Cluster) -> str:
    content = canonical.content if isinstance(canonical.content, dict) else {}
    title = content.get("title") or cluster.label
    return str(title) if title else "Untitled draft"


def _validator_rollup(canonical: CanonicalJD) -> tuple[float | None, str | None]:
    """The stored ``change_log`` roll-up — display-only, exactly as the library and the
    review queue show it. Never a fresh gate decision: the authority is the review
    service's own re-validation at approve time (NN #3)."""
    change_log = canonical.change_log if isinstance(canonical.change_log, dict) else {}
    validator = change_log.get("validator")
    if not isinstance(validator, dict):
        return None, None
    score = validator.get("score")
    grade = validator.get("grade")
    return (
        float(score) if isinstance(score, (int, float)) else None,
        str(grade) if grade else None,
    )


async def list_authored_drafts(
    session: AsyncSession, *, author_id: str, limit: int = DEFAULT_LIMIT
) -> list[AuthoredDraft]:
    """Every JD ``author_id`` composed, newest first, one row per role."""
    author = author_id.strip()
    if not author:
        return []
    rows = (
        await session.execute(
            select(CanonicalJD, Cluster)
            .join(Cluster, Cluster.id == CanonicalJD.cluster_id)
            .where(Cluster.constraint_metadata["origin"].astext == COMPOSED_ORIGIN)
            .where(Cluster.constraint_metadata["author"].astext == author)
            .order_by(CanonicalJD.created_at.desc(), CanonicalJD.version.desc())
        )
    ).all()

    drafts: list[AuthoredDraft] = []
    seen: set[UUID] = set()
    for canonical, cluster in rows:
        if canonical.cluster_id in seen:
            continue  # an earlier version of a role already listed (newest wins)
        seen.add(canonical.cluster_id)
        score, grade = _validator_rollup(canonical)
        drafts.append(
            AuthoredDraft(
                canonical_id=canonical.id,
                cluster_id=canonical.cluster_id,
                title=_title(canonical, cluster),
                status=str(canonical.status.value),
                version=canonical.version,
                score=score,
                grade=grade,
                created_at=canonical.created_at,
            )
        )
        if len(drafts) >= limit:
            break
    return drafts

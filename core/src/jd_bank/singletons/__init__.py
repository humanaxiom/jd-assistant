"""HR-223 — how many SFU jobs exist exactly ONCE, and what the Bank does with them.

The Bank's contract is *many documents become one role*. It has no answer for *one
document is already the role*: :func:`~src.jd_core.bank.clustering.build_clusters` takes
EDGES as its only input, so a document with no near-duplicate is never considered, let
alone rejected. ``comparison.singleton_role_policy`` records that as ``drop`` — what we
do today, registered as a decision rather than left as an accident, because it caps what
the Bank can EVER publish.

This package measures the population that policy governs, against the live Bank::

    make singletons

It writes ``docs/singletons/singleton-summary.json`` and prints the buckets. It reads;
it writes no Bank row, and it needs Postgres only.
"""

from __future__ import annotations

from src.jd_bank.singletons.buckets import (
    DocumentTitle,
    bucket_documents,
    unique_titles,
)
from src.jd_bank.singletons.models import (
    BucketedDocuments,
    SingletonSummary,
    TitleBuckets,
)

__all__ = [
    "BucketedDocuments",
    "DocumentTitle",
    "SingletonSummary",
    "TitleBuckets",
    "bucket_documents",
    "unique_titles",
]

"""Unit — bucketing the one-of-a-kind population (HR-223).

The question HR-223 asks is "how many jobs exist exactly ONCE at SFU?", and the trap is
answering it with a single number. A document that reached no role because it has no
near-duplicate anywhere is a genuinely singular job; one that shares a title with
documents that DID cluster is a **dedup recall miss** wearing the same shape; and one
whose title the parser never recovered CANNOT BE JUDGED either way.

Reported as one total those three are indistinguishable, and the third silently inflates
the first — the mistake the IT collection made with a code present on 35% of the
archive. So the split is the unit under test, and the could-not-evaluate bucket is a
first-class result, never folded into "no".
"""

from __future__ import annotations

import uuid

import pytest

from src.jd_bank.singletons import DocumentTitle, TitleBuckets, bucket_documents
from src.jd_core.parser import FALLBACK_TITLE


def _doc(title: str, *, in_role: bool = False, has_edge: bool = False) -> DocumentTitle:
    return DocumentTitle(
        document_id=uuid.uuid4(), title=title, in_role=in_role, has_edge=has_edge
    )


# --- the pool is exactly "no role, and no near-duplicate link at all" ---------------


def test_only_documents_with_no_role_and_no_edge_are_in_the_pool() -> None:
    """HR-223 is about a job with NO twin — not about every document outside a role.

    A document that has a `dedup_edges` row reached no role for some other reason (its
    whole group did), and clustering *did* consider it. Folding those in would answer a
    different question with the same number.
    """
    result = bucket_documents(
        [
            _doc("Solitary Job"),
            _doc("Grouped Job", has_edge=True),
            _doc("Published Job", in_role=True),
            _doc("Both", in_role=True, has_edge=True),
        ]
    )

    assert result.pool.total == 1
    assert result.pool.unique_title == 1


# --- the four buckets are exhaustive and mutually exclusive -------------------------


def test_the_buckets_partition_the_pool() -> None:
    """Every pooled document lands in exactly ONE bucket, and they sum to the pool.

    A split whose arithmetic does not close is hiding a case, which is how 1,204
    documents sat inside what read as ordinary de-duplication.
    """
    documents = [
        _doc("Disaster Recovery Coordinator"),
        _doc("Program Assistant"),
        _doc("Program Assistant", in_role=True, has_edge=True),
        _doc("Twin Orphan"),
        _doc("Twin Orphan"),
        _doc(FALLBACK_TITLE),
    ]

    result = bucket_documents(documents)

    assert result.pool == TitleBuckets(
        unique_title=1,
        shares_title_with_role_document=1,
        shares_title_with_other_orphan=2,
        title_unjudgeable=1,
    )
    assert result.pool.total == 5


def test_a_shared_title_is_a_recall_miss_not_a_unique_job() -> None:
    """The distinction that changes what the number MEANS.

    Two documents titled the same job, one of which reached a role, is evidence the
    dedup missed an edge (plan.md D3) — not evidence of a job that exists once. Counting
    it as unique would overstate the ceiling HR-223 is asked to raise.
    """
    result = bucket_documents(
        [_doc("Research Analyst"), _doc("Research Analyst", in_role=True)]
    )

    assert result.pool.shares_title_with_role_document == 1
    assert result.pool.unique_title == 0


def test_the_placeholder_title_cannot_be_judged_and_is_never_counted_as_unique() -> (
    None
):
    """🔴 A PLACEHOLDER IS NOT A NULL. The parser writes ``Untitled Position`` when it
    finds no title, so an emptiness check reports full coverage over documents that have
    none — the exact false all-clear that hid 2,050 titleless documents.

    Two placeholder documents are not "a title shared by two jobs"; they are two
    unanswered questions, and they must be reported as such.
    """
    result = bucket_documents([_doc(FALLBACK_TITLE), _doc(FALLBACK_TITLE)])

    assert result.pool.title_unjudgeable == 2
    assert result.pool.shares_title_with_other_orphan == 0
    assert result.pool.unique_title == 0


@pytest.mark.parametrize("title", ["", "   ", "Senior", "II"])
def test_a_title_that_normalises_to_nothing_cannot_be_judged(title: str) -> None:
    """Not only the sentinel. An empty title, or one that is nothing but the seniority
    markers `comparison.title_stopwords` strips (HR-089), leaves no stem to compare — so
    it is a could-not-evaluate, not a unique job.
    """
    result = bucket_documents([_doc(title)])

    assert result.pool.title_unjudgeable == 1


# --- the control ------------------------------------------------------------------


def test_the_same_split_is_reported_for_documents_that_did_reach_a_role() -> None:
    """A CONTROL is what tells a finding from a broken probe.

    If the could-not-evaluate rate were as high among documents that DID cluster, the
    probe would be measuring the parser rather than the archive. The control makes that
    visible instead of leaving it to be assumed.
    """
    result = bucket_documents(
        [
            _doc("Solitary Job"),
            _doc("Clustered Job", in_role=True, has_edge=True),
            _doc(FALLBACK_TITLE, in_role=True, has_edge=True),
        ]
    )

    assert result.pool.total == 1
    assert result.control.total == 2
    assert result.control.title_unjudgeable == 1


def test_title_matching_uses_the_registered_stem_not_raw_equality() -> None:
    """Titles collapse on `comparison.title_stopwords` (HR-089, `normalize_title`).

    Reusing the registered normaliser rather than inventing one here matters in a
    measurable direction: it MERGES `Senior Developer II` into `Developer`, so it can
    only ever report FEWER unique jobs than raw equality would. The ceiling HR-223 is
    asked about is therefore a floor, which is the safe way for it to be wrong.
    """
    result = bucket_documents(
        [_doc("Senior Developer II"), _doc("Developer", in_role=True)]
    )

    assert result.pool.shares_title_with_role_document == 1
    assert result.pool.unique_title == 0


@pytest.mark.parametrize("title", ["#01246", "06595", "....", "00110757 —"])
def test_a_title_with_no_letters_in_it_cannot_be_judged(title: str) -> None:
    """Found by EYEBALLING the sample, which is why the sample is printed.

    The measurement surfaced `#01246` and `06595` among its "unique jobs" — position
    numbers the parser captured where a title should be. They are not rare titles; they
    are titles it did not recover, and counting them as unique inflates the one number
    HR is being asked to act on.

    This is definitional, not a hypothesis: a string with no letter in it cannot be a
    job title in any language SFU writes JDs in. It is therefore NOT a registered knob
    — there is no parameter to tune and no default that could be wrong. The judgement
    calls it deliberately does NOT make (banner text, a truncated title, an incumbent's
    name) stay in `unique_title`, which is why that count is an upper bound.
    """
    result = bucket_documents([_doc(title)])

    assert result.pool.title_unjudgeable == 1
    assert result.pool.unique_title == 0


def test_a_title_with_letters_among_the_digits_is_still_a_title() -> None:
    """The inverse direction — a guard asserted one way is decoration.

    Real SFU titles carry digits (`Director, 4D LABS`, `Business System Analyst III`).
    Dropping anything containing a number would delete genuine singular jobs, so the
    rule is "no letters AT ALL", and this is what pins it there.
    """
    result = bucket_documents([_doc("Director, 4D LABS")])

    assert result.pool.unique_title == 1
    assert result.pool.title_unjudgeable == 0

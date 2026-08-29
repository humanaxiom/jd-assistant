"""Split the one-of-a-kind population by what its titles can and cannot tell us.

Pure: it takes rows and returns counts, so the rule can be tested without a database and
the SQL can be tested without re-testing the rule.

**Why titles at all.** Clustering takes EDGES as its only input, so a document with no
near-duplicate is never *considered* — it is not rejected by any rule. To ask whether
such a document is a genuinely singular job we need a second, independent signal, and
the title is the only one every document is supposed to carry. It is a weak signal and
this module is built to say so: whenever the parser recovered no usable title, the
answer is ``title_unjudgeable`` rather than a guess in either direction.

**Which normaliser.** :func:`~src.jd_core.bank.similarity.normalize_title` — the
registered one (``comparison.title_stopwords``, HR-089), not a new one invented here.
That choice has a measurable direction: it collapses ``Senior Developer II`` onto
``developer``, so it can only ever report FEWER unique titles than raw equality would.
The ceiling HR-223 asks about is therefore reported as a floor, which is the safe way
for it to be wrong.
"""

from __future__ import annotations

import uuid
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass

from src.jd_bank.singletons.models import BucketedDocuments, TitleBuckets
from src.jd_core.bank.similarity import normalize_title
from src.jd_core.parser import FALLBACK_TITLE
from src.jd_core.rules.loader import Rules


@dataclass(frozen=True)
class DocumentTitle:
    """One parsed document, reduced to what the split needs.

    ``in_role`` and ``has_edge`` are kept separate on purpose. They answer different
    questions — "did it produce anything?" and "did clustering ever look at it?" — and
    conflating them is what makes an ordinary de-duplication story out of documents the
    pipeline never examined.
    """

    document_id: uuid.UUID
    title: str
    in_role: bool
    has_edge: bool


def _stem(title: str, *, rules: Rules | None = None) -> str | None:
    """The comparable stem of a title, or ``None`` when there is nothing to compare.

    🔴 The sentinel check comes FIRST and is checked by value, not by emptiness:
    ``FALLBACK_TITLE`` is a placeholder, so ``title <> ''`` calls it a title and reports
    full coverage over documents that have none.
    """
    if title.strip() in {"", FALLBACK_TITLE}:
        return None
    # A string with no letter in it is not a job title in any language SFU writes JDs
    # in — it is a position number the parser captured where a title should be
    # (`#01246`, `06595`). Definitional, so it is not a registered knob: there is no
    # parameter to tune and no default that could be wrong. Note the direction it is
    # NOT asserted in — real titles carry digits (`Director, 4D LABS`), so the test is
    # "no letters at all", never "contains a digit".
    if not any(character.isalpha() for character in title):
        return None
    stem = normalize_title(title, rules=rules)
    # A title that is nothing but seniority markers ("Senior", "II") normalises away
    # entirely. There is no stem left to match on, so it cannot be judged either.
    return stem or None


def bucket_documents(
    documents: Iterable[DocumentTitle], *, rules: Rules | None = None
) -> BucketedDocuments:
    """Split the no-edge/no-role pool — and, as a CONTROL, the documents that did reach
    a role — into :class:`TitleBuckets`.

    Title frequencies are counted over EVERY document supplied, not only over the pool:
    "appears exactly once in the archive" is a claim about the archive, and counting it
    within the pool alone would call a document unique because its twin is elsewhere.
    """
    rows = list(documents)
    stems = {row.document_id: _stem(row.title, rules=rules) for row in rows}

    archive_counts = Counter(s for s in stems.values() if s is not None)
    role_stems = {
        stems[row.document_id]
        for row in rows
        if row.in_role and stems[row.document_id] is not None
    }

    def split(population: list[DocumentTitle]) -> TitleBuckets:
        unique = shared_with_role = shared_with_orphan = unjudgeable = 0
        for row in population:
            stem = stems[row.document_id]
            if stem is None:
                unjudgeable += 1
            elif archive_counts[stem] == 1:
                unique += 1
            elif stem in role_stems:
                shared_with_role += 1
            else:
                shared_with_orphan += 1
        return TitleBuckets(
            unique_title=unique,
            shares_title_with_role_document=shared_with_role,
            shares_title_with_other_orphan=shared_with_orphan,
            title_unjudgeable=unjudgeable,
        )

    return BucketedDocuments(
        pool=split([r for r in rows if not r.in_role and not r.has_edge]),
        control=split([r for r in rows if r.in_role]),
    )


def unique_titles(
    documents: Iterable[DocumentTitle], *, rules: Rules | None = None, limit: int = 12
) -> tuple[str, ...]:
    """Up to ``limit`` pool titles whose stem appears exactly once, verbatim.

    Present so the headline count can be EYEBALLED. A number of this kind has been wrong
    in this project more than once while being perfectly self-consistent; a reader who
    can see `Coordinator, Disaster Recovery` in the list can tell in seconds whether the
    query answered the question that was asked.
    """
    rows = list(documents)
    stems = {row.document_id: _stem(row.title, rules=rules) for row in rows}
    counts = Counter(s for s in stems.values() if s is not None)
    pool = [
        (row.title, stems[row.document_id])
        for row in rows
        if not row.in_role and not row.has_edge
    ]
    found = sorted(
        title for title, stem in pool if stem is not None and counts[stem] == 1
    )
    if len(found) <= limit:
        return tuple(found)
    # An EVEN STRIDE across the sorted list, not its first `limit` entries. Sorted-first
    # is not a sample: punctuation and digits sort before letters, so it shows only the
    # junk end and would read as "every unique title is garbage".
    stride = len(found) / limit
    return tuple(found[int(i * stride)] for i in range(limit))

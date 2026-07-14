"""MinHash / LSH banding over shingle sets — the Tier-2 *candidate index*, never the
*score* (Phase 3.3).

Pure — no I/O, no ``jd_bank`` import. Seeded Carter-Wegman universal hashing over the
Mersenne prime :data:`_MERSENNE_PRIME` (``2**61 - 1``), no new dependency (``numpy`` is
NOT needed here — MEASURED: pure Python does the whole corpus in ~3.5 minutes).

**MinHash is ONLY the index. The score a caller keeps is always
:func:`exact_jaccard`, recomputed on the two documents' shingle sets — never
:func:`estimate_jaccard`.** A MinHash estimate's standard error is
``sqrt(J(1-J)/num_perm)``, which at ``num_perm=128`` is σ≈0.088 at the worst case
(J=0.5) — far too coarse to threshold a similarity decision on. What MinHash + LSH
banding buys is sub-quadratic *candidate generation*: two documents are only compared
by exact Jaccard at all if they land in the same band bucket at least once, which
:attr:`~src.jd_core.rules.Dedup.s_curve_threshold` (``(1/bands)^(1/rows)``, derived —
see the rulebook) says happens with high probability once the true Jaccard clears that
midpoint. It is what makes ``num_perm=128`` defensible: the estimator's own error
never reaches a threshold decision, only a "worth comparing exactly" decision.

**Determinism.** :data:`_SEED` is a module constant — arbitrary, but FIXED. Two
processes computing a MinHash signature for the SAME shingle set must get the SAME
signature, or two runs over the same corpus would produce different candidate sets and
an "idempotent pass" would be a fiction. This is the same class of requirement
:mod:`.shingles` states for ``blake2b`` over Python's salted ``hash()``.
"""

from __future__ import annotations

import random
from collections.abc import Sequence
from functools import cache
from typing import Final

#: The Mersenne prime 2**61 - 1. Standard choice for Carter-Wegman universal hashing:
#: large enough that collisions among a corpus's worth of 64-bit shingle hashes are
#: negligible, and a Mersenne prime makes the modulo cheap (though this module does not
#: bother with the bit-trick — clarity over a few pure-Python ops).
_MERSENNE_PRIME: Final[int] = (1 << 61) - 1

#: Seeds the Carter-Wegman coefficient draw (:func:`_permutations`). Arbitrary — the
#: only property that matters is that it never changes: it is what makes
#: :func:`minhash_signature` a PURE function of ``(hashes, num_perm)`` rather than of
#: "whichever process happened to run first". Bump :data:`MINHASH_VERSION` if this
#: value, or the draw algorithm, ever changes — that is a behavioural break, not a
#: rulebook tuning, so it does not belong on the decision surface.
_SEED: Final[int] = 1_469_598_103

#: Bump when this module's OUTPUT changes for the same input (a code change; a
#: rulebook change to ``num_perm``/``bands``/``rows`` already moves ``Dedup.stamp``).
MINHASH_VERSION: Final[str] = "minhash_v1"


@cache
def _permutations(num_perm: int) -> tuple[tuple[int, int], ...]:
    """``num_perm`` ``(a, b)`` Carter-Wegman coefficient pairs, seeded and cached.

    ``a`` is drawn from ``[1, prime - 1]`` (never 0 — a zero coefficient collapses the
    hash family to a constant function) and ``b`` from ``[0, prime - 1]``. Cached
    because a real pass calls this once per distinct ``num_perm`` (normally one value,
    the rulebook's) but :func:`minhash_signature` is called once per document.
    """
    if num_perm <= 0:
        raise ValueError(f"num_perm must be positive, got {num_perm}")
    rng = random.Random(_SEED)
    return tuple(
        (rng.randrange(1, _MERSENNE_PRIME), rng.randrange(0, _MERSENNE_PRIME))
        for _ in range(num_perm)
    )


def minhash_signature(hashes: Sequence[int], num_perm: int) -> tuple[int, ...]:
    """The ``num_perm``-length MinHash signature of a shingle-hash set.

    ``hashes`` is normally :func:`~src.jd_core.bank.shingles.shingle_hashes`'s output
    (a sorted ``array('Q')``), but any iterable of ints works — order does not matter,
    only membership.

    An EMPTY ``hashes`` yields a signature of :data:`_MERSENNE_PRIME` repeated
    ``num_perm`` times — a value no real hash can ever equal (every real hash's
    permuted value is strictly less than the prime), so two empty signatures compare
    as identical to EACH OTHER but that is moot: the rulebook's ``min_shingles`` guard
    means a document with no shingles never reaches this function via the real
    pipeline (see :mod:`src.jd_bank.dedup.near.runner`).
    """
    coefficients = _permutations(num_perm)
    if not hashes:
        return tuple(_MERSENNE_PRIME for _ in coefficients)
    return tuple(
        min((a * h + b) % _MERSENNE_PRIME for h in hashes) for a, b in coefficients
    )


def band_keys(
    signature: Sequence[int], bands: int, rows: int
) -> tuple[tuple[int, tuple[int, ...]], ...]:
    """``signature`` sliced into ``bands`` consecutive chunks of ``rows`` values each,
    tagged by band index — the LSH bucket keys.

    Two documents are CANDIDATES (worth an exact-Jaccard comparison) iff they share at
    least one ``(band_index, chunk)`` key. Tagging by band index matters: without it, a
    chunk that happens to repeat in band 3 of one document and band 7 of another would
    falsely bucket them together.

    Raises:
        ValueError: ``bands * rows`` does not equal ``len(signature)`` — the same
            cross-check the rulebook loader enforces on ``Dedup.bands`` /
            ``Dedup.rows`` / ``Dedup.num_perm``, so a caller passing a signature from a
            DIFFERENT ``num_perm`` than the banding it requests fails loudly rather
            than silently truncating the signature.
    """
    if bands * rows != len(signature):
        raise ValueError(
            f"bands*rows ({bands}*{rows}={bands * rows}) must equal the signature "
            f"length ({len(signature)})"
        )
    return tuple(
        (band, tuple(signature[band * rows : (band + 1) * rows]))
        for band in range(bands)
    )


def estimate_jaccard(sig_a: Sequence[int], sig_b: Sequence[int]) -> float:
    """The MinHash ESTIMATE of Jaccard similarity: the fraction of signature
    positions where the two signatures agree.

    **Never used as a score** — see the module docstring. Exposed for tests (pinning
    that the estimate tracks :func:`exact_jaccard` within tolerance) and for anyone
    who needs to reason about the estimator's own error, not for a decision.

    Raises:
        ValueError: the signatures are different lengths — they were not built with
            the same ``num_perm``, so position-wise comparison is meaningless.
    """
    if len(sig_a) != len(sig_b):
        raise ValueError(
            f"signatures must be the same length to compare positionally: "
            f"{len(sig_a)} != {len(sig_b)}"
        )
    if not sig_a:
        return 0.0
    matches = sum(1 for a, b in zip(sig_a, sig_b, strict=True) if a == b)
    return matches / len(sig_a)


def exact_jaccard(a: Sequence[int], b: Sequence[int]) -> float:
    """The TRUE Jaccard similarity of two shingle-hash sets, by merge-intersection.

    **THE score.** Every Tier-2 edge's ``score`` is this, never
    :func:`estimate_jaccard` and never a cosine blend — see the module docstring.

    ``a`` and ``b`` MUST already be sorted with no duplicates (exactly what
    :func:`~src.jd_core.bank.shingles.shingle_hashes` returns) — this function does
    not sort or dedupe, so passing anything else silently produces a wrong answer
    rather than raising. That trade is deliberate: this runs once per LSH candidate
    pair over a real corpus, and re-sorting on every call would be wasted work when
    every caller already has a sorted ``array('Q')`` in hand.

    Two empty sets have Jaccard **0.0** here (not 1.0, not undefined) — "no shared
    content" is the conservative reading, and the rulebook's ``min_shingles`` guard
    means this pipeline never scores a genuinely empty document against anything in
    practice.
    """
    i = j = 0
    len_a, len_b = len(a), len(b)
    intersection = 0
    while i < len_a and j < len_b:
        if a[i] == b[j]:
            intersection += 1
            i += 1
            j += 1
        elif a[i] < b[j]:
            i += 1
        else:
            j += 1
    union = len_a + len_b - intersection
    return intersection / union if union else 0.0


def s_curve_threshold(bands: int, rows: int) -> float:
    """The Jaccard value at which the LSH banding's "probability of becoming a
    candidate" S-curve crosses 50% — ``(1/bands)^(1/rows)``.

    Pure derived fact of ``(bands, rows)``, no rulebook dependency: this is what lets
    :attr:`~src.jd_core.rules.Dedup.s_curve_threshold` be a **property**, never a
    stored YAML key holding a THIRD number that ``bands``/``rows`` could drift out of
    step with (the ``max_listed`` duplicate-knob shape).
    """
    return float((1 / bands) ** (1 / rows))

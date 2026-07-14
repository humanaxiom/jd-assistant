"""``jd_core.bank.minhash`` — MinHash / LSH banding (Phase 3.3).

The literal-signature test is the one that goes red if anyone reaches for a
non-deterministic or per-process-salted source of randomness where the seeded
Carter-Wegman draw belongs — exactly the same class of regression
``test_shingles.py`` pins for ``blake2b`` over ``hash()``.
"""

from __future__ import annotations

from array import array

import pytest

from src.jd_core.bank.minhash import (
    band_keys,
    estimate_jaccard,
    exact_jaccard,
    minhash_signature,
    s_curve_threshold,
)
from src.jd_core.bank.shingles import shingle_hashes

_FOX = "The quick brown fox jumps over the lazy dog."

#: Computed once via `minhash_signature(shingle_hashes(_FOX, shingle_size=5, ...), 8)`
#: — see the module docstring. Pinning this literal tuple is what makes a
#: non-deterministic coefficient draw (or a seed change) visible as a failing test
#: rather than a silently different — but still "valid-looking" — signature.
_FOX_SIGNATURE_NUM_PERM_8 = (
    712620187660693846,
    78168194238892159,
    711356851093301354,
    32284938436067982,
    385107159797943740,
    203001770629160499,
    528150613179299001,
    267980034776925532,
)


def _fox_hashes() -> array[int]:
    return shingle_hashes(_FOX, shingle_size=5, redact_boilerplate=False)


def test_minhash_signature_is_a_literal_pinned_value_for_a_literal_input() -> None:
    signature = minhash_signature(_fox_hashes(), 8)
    assert signature == _FOX_SIGNATURE_NUM_PERM_8


def test_minhash_signature_is_deterministic_across_repeated_calls() -> None:
    hashes = _fox_hashes()
    assert minhash_signature(hashes, 32) == minhash_signature(hashes, 32)


def test_minhash_signature_length_matches_num_perm() -> None:
    signature = minhash_signature(_fox_hashes(), 16)
    assert len(signature) == 16


def test_empty_hashes_yields_a_signature_no_real_hash_can_ever_match() -> None:
    empty_sig = minhash_signature(array("Q"), 8)
    real_sig = minhash_signature(_fox_hashes(), 8)
    assert len(empty_sig) == 8
    assert set(empty_sig).isdisjoint(real_sig)


def test_band_keys_rejects_a_banding_that_does_not_partition_the_signature() -> None:
    signature = minhash_signature(_fox_hashes(), 8)
    with pytest.raises(ValueError, match="must equal the signature"):
        band_keys(signature, bands=3, rows=2)  # 3*2=6 != 8


def test_band_keys_tags_each_chunk_by_its_band_index() -> None:
    """Two documents whose signatures repeat the SAME chunk in DIFFERENT band
    positions must not collide — band index is part of the key."""
    signature = (1, 2, 3, 4, 1, 2)
    keys = band_keys(signature, bands=3, rows=2)
    assert keys == ((0, (1, 2)), (1, (3, 4)), (2, (1, 2)))
    assert keys[0] != keys[2]  # same chunk (1, 2), different band -> different key


def test_identical_shingle_sets_always_become_a_candidate() -> None:
    """J=1.0 must ALWAYS be a candidate — a structural guarantee, not a probability.
    Two identical shingle sets produce the identical MinHash signature (every
    permutation's minimum is over the same values), so EVERY band matches, not just
    "probably enough of them"."""
    hashes = _fox_hashes()
    sig_a = minhash_signature(hashes, 32)
    sig_b = minhash_signature(hashes, 32)  # a second, independent document, same text
    assert sig_a == sig_b
    keys_a = band_keys(sig_a, bands=8, rows=4)
    keys_b = band_keys(sig_b, bands=8, rows=4)
    assert set(keys_a) & set(keys_b) == set(keys_a)  # every band matches


def test_estimate_tracks_exact_within_tolerance() -> None:
    """The estimator is not used as a score (see the module docstring), but it must
    still be a REASONABLE estimator — the MinHash algorithm's basic correctness
    property, not a Tier-2-specific claim."""
    shared = shingle_hashes(
        "alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu nu",
        shingle_size=3,
        redact_boilerplate=False,
    )
    only_a = shingle_hashes(
        "alpha beta gamma delta epsilon zeta eta theta iota omicron pi rho sigma",
        shingle_size=3,
        redact_boilerplate=False,
    )
    exact = exact_jaccard(shared, only_a)
    sig_shared = minhash_signature(shared, 256)
    sig_only_a = minhash_signature(only_a, 256)
    estimate = estimate_jaccard(sig_shared, sig_only_a)
    assert abs(estimate - exact) < 0.15


def test_exact_jaccard_of_disjoint_sets_is_exactly_zero() -> None:
    """Disjoint shingle sets must NEVER register as similar — the one property that
    holds unconditionally (unlike "never becomes an LSH candidate", which is only
    probabilistically true and not a fact to assert as a hard guarantee)."""
    a = array("Q", [1, 2, 3])
    b = array("Q", [4, 5, 6])
    assert exact_jaccard(a, b) == 0.0


def test_exact_jaccard_of_identical_sets_is_one() -> None:
    a = array("Q", [1, 2, 3])
    assert exact_jaccard(a, a) == 1.0


def test_exact_jaccard_matches_the_textbook_definition() -> None:
    a = array("Q", [1, 2, 3, 4])
    b = array("Q", [3, 4, 5, 6])
    # intersection {3,4}=2, union {1,2,3,4,5,6}=6 -> 2/6
    assert exact_jaccard(a, b) == pytest.approx(2 / 6)


def test_exact_jaccard_of_two_empty_sets_is_zero_not_undefined() -> None:
    empty = array("Q")
    assert exact_jaccard(empty, empty) == 0.0


def test_estimate_jaccard_rejects_mismatched_signature_lengths() -> None:
    with pytest.raises(ValueError, match="same length"):
        estimate_jaccard((1, 2, 3), (1, 2))


def test_s_curve_threshold_is_the_textbook_formula() -> None:
    assert s_curve_threshold(bands=32, rows=4) == pytest.approx((1 / 32) ** (1 / 4))
    assert s_curve_threshold(bands=16, rows=8) == pytest.approx((1 / 16) ** (1 / 8))
    # more bands / fewer rows -> a LOWER midpoint -> more candidates at the same
    # true Jaccard, not fewer.
    assert s_curve_threshold(bands=32, rows=4) < s_curve_threshold(bands=16, rows=8)

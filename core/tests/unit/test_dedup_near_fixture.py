"""§7(a) — THE CI regression gate for Tier-2, in place of a precision/recall check
against ``fixtures/labels/pairs.csv`` (see ``dedup.yaml``'s header and HR-138 for why
that label set cannot referee ``jaccard_min`` on this corpus).

A handful of ALREADY-EXTRACTED, committed ``.txt`` fixtures (never binaries — the
``gates`` container has no archive) run through the REAL SHIPPED ``dedup.yaml``
config (never retuned in the PIN tests below), and the exact candidate set, the
exact Jaccard score (4 dp) for every pair, and the exact edge set are pinned as
LITERAL measured values. This is a real regression gate: it pins BEHAVIOUR, not an
estimate, and moving ANY knob (shingle_size, jaccard_min, the LSH banding,
min_shingles) must turn it red — ``test_retuning_any_knob_changes_the_pinned_result``
proves that property rather than merely asserting it in prose.

The four fixtures, and what they are for:

* ``role_summary_v1.txt`` / ``role_summary_v1_reformatted.txt`` — the SAME content,
  reformatted (upper-cased, commas -> semicolons) — punctuation and case fold away
  entirely, so these MUST shingle identically (J=1.0) and MUST become an edge. The
  ``.doc``-vs-``.docx`` "archetypal Tier-2 positive" shape, at fixture scale.
* ``role_summary_v2.txt`` — the same JD with one word genuinely changed
  ("prepares"->"drafts"). MEASURED: this is a real LSH candidate at the shipped
  bands=16/rows=8 banding (J=0.7368 clears the 0.707 S-curve midpoint) but its exact
  Jaccard sits BELOW the shipped `jaccard_min` of 0.85 — so it does NOT become an
  edge at the shipped threshold, though it IS reported (`PairRecord.qualifies=False`),
  never silently dropped. This is not a fixture bug: it is the honest, measured shape
  of "a casual revision is not close enough to trip a 0.85 bar", and it is exactly the
  kind of case ``docs/dedup/near-dup-adjudication-sample.csv`` exists to surface for
  a human, not for this gate to silently decide either way.
  NOTE (retune, HR-136/HR-137, bands 32/4 -> 16/8): the fixture originally changed
  TWO words ("prepares"->"drafts", "multiple"->"several"), J=0.6098. At the old
  bands=32/rows=4 banding (midpoint 0.420) that was comfortably a candidate; at the
  new bands=16/rows=8 banding (midpoint 0.707) it drops BELOW the midpoint and stops
  being an LSH candidate at all — losing this fixture's demonstration that a
  candidate can fail to qualify without being silently dropped. The fixture was
  narrowed to a single-word change (J=0.7368) specifically so it clears the new
  0.707 midpoint and still falls short of 0.85, keeping that property exercised at
  fixture scale rather than only in prose.
* ``unrelated.txt`` — shares no vocabulary with the other three. MEASURED: zero
  overlap, never a candidate.

Note: `redact_boilerplate` and `edge_scope` are NOT exercised as mutations here —
none of these four fixtures contains any of SFU's mandated boilerplate text (so
`redact_boilerplate` is a genuine no-op on this specific corpus), and every fixture
is its own singleton `sha256` group (so `edge_scope` cannot matter on a corpus with
no duplicate-content groups at all). Both are pinned by mutation elsewhere instead:
`redact_boilerplate` in `test_shingles.py`, `edge_scope` in `test_dedup_near_pure.py`.
"""

from __future__ import annotations

import itertools
from pathlib import Path

import pytest

from src.jd_bank.dedup.models import DocumentRef, order_key
from src.jd_bank.dedup.near import runner as near_runner
from src.jd_bank.dedup.near.models import CandidatePair, Signature
from src.jd_bank.dedup.near.text import TextResult
from src.jd_core.bank.minhash import exact_jaccard
from src.jd_core.rules import Dedup, Rules, get_rules
from tests.unit.retuned_rules import retuned_dedup

_FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "neardup"
_FILES = (
    "role_summary_v1.txt",
    "role_summary_v1_reformatted.txt",
    "role_summary_v2.txt",
    "unrelated.txt",
)

_BASELINE_CANDIDATES = frozenset(
    {
        frozenset({"sha-role_summary_v1.txt", "sha-role_summary_v1_reformatted.txt"}),
        frozenset({"sha-role_summary_v1.txt", "sha-role_summary_v2.txt"}),
        frozenset({"sha-role_summary_v1_reformatted.txt", "sha-role_summary_v2.txt"}),
    }
)


class _FixtureTextSource:
    """Content-keyed (by ``sha256``) — reads the committed fixture files once."""

    def __init__(self, text_by_sha256: dict[str, str]) -> None:
        self._text_by_sha256 = text_by_sha256

    async def text_for(self, ref: DocumentRef) -> TextResult:
        return TextResult(text=self._text_by_sha256[ref.sha256])


def _refs() -> list[DocumentRef]:
    return [
        DocumentRef.for_path(
            f"fixtures/neardup/{name}", sha256=f"sha-{name}", filename=name
        )
        for name in _FILES
    ]


def _text_source() -> _FixtureTextSource:
    texts = {
        f"sha-{name}": (_FIXTURE_DIR / name).read_text(encoding="utf-8")
        for name in _FILES
    }
    return _FixtureTextSource(texts)


async def _signatures_for(
    rules: Rules,
) -> near_runner._Signatures:
    refs = _refs()
    groups = near_runner._group_all_by_sha256(refs)
    boilerplate = rules.boilerplate
    passages = (
        boilerplate.about_sfu
        + boilerplate.territorial_acknowledgement
        + boilerplate.employment_equity
    )
    return await near_runner._build_signatures(
        groups,
        text_source=_text_source(),
        dedup_rules=rules.dedup,
        boilerplate_passages=passages,
    )


async def _pipeline(
    rules: Rules,
) -> tuple[dict[str, Signature], set[frozenset[str]], list[CandidatePair]]:
    """The candidate-generation + scoring pipeline, without a database — mirrors
    what ``run_tier2`` does internally, minus the Postgres/reconcile I/O. Does NOT
    assert ``unreadable``/``below_min_shingles`` are zero — the mutation test
    deliberately drives ``below_min`` above zero (``min_shingles=40``)."""
    signatures = (await _signatures_for(rules)).signatures
    candidates = near_runner._lsh_candidates(signatures, dedup_rules=rules.dedup)
    scored = near_runner._score_candidates(candidates, signatures)
    return signatures, candidates, scored


@pytest.fixture(scope="module")
def rules() -> Rules:
    return get_rules()


# --- pin 1: every pair's EXACT Jaccard, to 4dp, on the SHIPPED config -------------


@pytest.mark.asyncio
async def test_exact_jaccard_is_pinned_to_four_decimal_places_for_every_pair(
    rules: Rules,
) -> None:
    built = await _signatures_for(rules)
    signatures = built.signatures
    assert built.unreadable_shas == set()
    assert built.below_min_shas == set()
    pairwise = {
        tuple(sorted((a, b))): round(
            exact_jaccard(signatures[a].shingles, signatures[b].shingles), 4
        )
        for a, b in itertools.combinations(sorted(signatures), 2)
    }
    assert pairwise == {
        ("sha-role_summary_v1.txt", "sha-role_summary_v1_reformatted.txt"): 1.0,
        ("sha-role_summary_v1.txt", "sha-role_summary_v2.txt"): 0.7368,
        ("sha-role_summary_v1.txt", "sha-unrelated.txt"): 0.0,
        ("sha-role_summary_v1_reformatted.txt", "sha-role_summary_v2.txt"): 0.7368,
        ("sha-role_summary_v1_reformatted.txt", "sha-unrelated.txt"): 0.0,
        ("sha-role_summary_v2.txt", "sha-unrelated.txt"): 0.0,
    }


# --- pin 2: the exact LSH candidate set on the SHIPPED banding --------------------


@pytest.mark.asyncio
async def test_the_lsh_candidate_set_is_pinned_on_the_shipped_banding(
    rules: Rules,
) -> None:
    _signatures, candidates, _scored = await _pipeline(rules)
    assert candidates == set(_BASELINE_CANDIDATES)
    # unrelated.txt is a candidate of NOTHING — zero overlap, never bucketed together.
    assert not any("sha-unrelated.txt" in pair for pair in candidates)


# --- pin 3: the exact edge set the SHIPPED jaccard_min (0.85) implies -------------


@pytest.mark.asyncio
async def test_the_edge_set_is_pinned_on_the_shipped_jaccard_min(rules: Rules) -> None:
    _signatures, _candidates, scored = await _pipeline(rules)
    refs_by_id = {ref.id: ref for ref in _refs()}
    plan = near_runner._build_plan(
        scored,
        refs_by_id=refs_by_id,
        dedup_rules=rules.dedup,
        segmentation=rules.segmentation,
    )

    v1 = DocumentRef.for_path(
        "fixtures/neardup/role_summary_v1.txt",
        sha256="sha-role_summary_v1.txt",
        filename="role_summary_v1.txt",
    )
    v1_reformatted = DocumentRef.for_path(
        "fixtures/neardup/role_summary_v1_reformatted.txt",
        sha256="sha-role_summary_v1_reformatted.txt",
        filename="role_summary_v1_reformatted.txt",
    )
    assert order_key(v1) < order_key(v1_reformatted)

    # EXACTLY one edge — the reformatted twin. v2's 0.7368 does not clear 0.85.
    assert len(plan.edges) == 1
    (((source_a, source_b), spec),) = list(plan.edges.items())
    assert (source_a, source_b) == (v1.id, v1_reformatted.id)
    assert spec.score == 1.0
    assert spec.method == f"minhash+jaccard@{rules.dedup.digest[:12]}"

    # ALL 3 LSH candidates are reported — including v1<->v2 and v1_reformatted<->v2,
    # which are candidates but DID NOT qualify. Never silently dropped: this is
    # exactly what the adjudication sample is for.
    assert len(plan.pairs) == 3
    assert sum(1 for p in plan.pairs if p.qualifies) == 1
    assert sum(1 for p in plan.pairs if not p.qualifies) == 2
    non_qualifying_scores = sorted(
        round(p.jaccard, 4) for p in plan.pairs if not p.qualifies
    )
    assert non_qualifying_scores == [0.7368, 0.7368]


# --- moving ANY knob must turn this gate red --------------------------------------


async def _fingerprint(
    rules: Rules,
) -> tuple[
    frozenset[frozenset[str]],
    dict[tuple[str, str], float],
    dict[tuple[str, str], tuple[float, str]],
]:
    """A single comparable snapshot of "everything this gate pins": the candidate
    set, every pair's rounded Jaccard, and the written edges (keyed by filename pair,
    since document ids are not stable across separately-constructed ref lists)."""
    signatures, candidates, scored = await _pipeline(rules)
    pairwise: dict[tuple[str, str], float] = {}
    for a, b in itertools.combinations(sorted(signatures), 2):
        pairwise[(a, b)] = round(
            exact_jaccard(signatures[a].shingles, signatures[b].shingles), 4
        )
    refs_by_id = {ref.id: ref for ref in _refs()}
    # Every fixture ref carries a non-None `filename` (see `_refs()`), so this is
    # safe — asserted, not merely assumed, to keep mypy --strict honest about it.
    filenames_by_id: dict[object, str] = {}
    for ref in _refs():
        assert ref.filename is not None
        filenames_by_id[ref.id] = ref.filename
    plan = near_runner._build_plan(
        scored,
        refs_by_id=refs_by_id,
        dedup_rules=rules.dedup,
        segmentation=rules.segmentation,
    )
    edges: dict[tuple[str, str], tuple[float, str]] = {}
    for (source_a, source_b), spec in plan.edges.items():
        key_a, key_b = sorted((filenames_by_id[source_a], filenames_by_id[source_b]))
        edges[(key_a, key_b)] = (round(spec.score, 4), spec.method)
    return frozenset(candidates), pairwise, edges


#: knob -> the value this gate retunes it to. Every one of these MUST change the
#: fingerprint (candidate set + every pair's Jaccard + the edge set).
_BEHAVIOURALLY_MUTATED: dict[str, object] = {
    "shingle_size": 4,
    "jaccard_min": 0.5,  # would ADD 2 edges (v1<->v2, v1_reformatted<->v2)
    "bands": 8,
    "rows": 16,
    "min_shingles": 40,  # excludes all 4 fixtures (each has 33 shingles)
}

#: knob -> why THIS FIXTURE CORPUS cannot move it behaviourally, and where it IS
#: pinned instead. An honest exemption, not a silent omission — the closed-world check
#: below refuses to let a knob be absent from BOTH dicts.
_NOT_BEHAVIOURAL_ON_THIS_FIXTURE: dict[str, str] = {
    "num_perm": (
        "MEASURED: retuning num_perm (64/16x4, 256/64x4) leaves this 4-document "
        "fixture's candidate set, Jaccards and edges IDENTICAL — it changes only the "
        "MinHash index's resolution, and the score is always exact Jaccard, never the "
        "estimate. Nothing to assert here that would not be a coincidence. Pinned by "
        "stamp mutation in test_dedup_rules.py, and by band_keys' length cross-check."
    ),
    "text_source": (
        "Not an input to the pure pipeline at all — it SELECTS a TextSource, which "
        "this gate injects directly. Pinned behaviourally by "
        "test_dedup_near_text.py::test_the_text_source_knob_selects_the_source."
    ),
    "redact_boilerplate": (
        "None of these four fixtures contains any of SFU's mandated boilerplate, so "
        "redaction is a genuine no-op ON THIS CORPUS. Pinned by mutation in "
        "test_shingles.py (both the shared-passage case and the split-across-a-"
        "paragraph-break case)."
    ),
    "cosine_confirm_min": (
        "The pure pipeline has no vectors (Neo4j is not in scope for a unit test). "
        "Pinned in tests/integration/test_dedup_near.py (veto, missing-vector "
        "fallback, and the never-constructs-an-embed-client property)."
    ),
    "edge_scope": (
        "Every fixture is its own singleton sha256 group, so content scope and file "
        "scope coincide by construction. Pinned by mutation in "
        "test_dedup_near_pure.py (incl. the 6-member exact-duplicate group)."
    ),
    "max_candidate_pairs": (
        "A safety valve that RAISES; it cannot change a result, only refuse to "
        "produce one. Pinned by test_dedup_near_pure.py's overflow tests."
    ),
}


def test_every_dedup_knob_is_either_behaviourally_pinned_here_or_exempted() -> None:
    """**The guard ON the guard** (reviewer nit). ``test_dedup_rules.py`` has a
    closed-world check for the STAMP mutation list; this gate — the *behavioural* one —
    had none, so a knob added to ``dedup.yaml`` tomorrow would silently escape it.
    ``num_perm`` already had.

    Every field of ``Dedup`` must be in exactly one of the two dicts above: mutated and
    proven to move the pinned result, or explicitly exempted WITH a reason naming where
    it is pinned instead.
    """
    declared = set(Dedup.model_fields) - {"version"}
    covered = set(_BEHAVIOURALLY_MUTATED) | set(_NOT_BEHAVIOURAL_ON_THIS_FIXTURE)
    assert declared == covered, sorted(declared.symmetric_difference(covered))

    overlap = set(_BEHAVIOURALLY_MUTATED) & set(_NOT_BEHAVIOURAL_ON_THIS_FIXTURE)
    assert not overlap, f"a knob is both mutated and exempted: {sorted(overlap)}"

    for knob, reason in _NOT_BEHAVIOURAL_ON_THIS_FIXTURE.items():
        assert len(reason) > 40, f"{knob}'s exemption must state a real reason"


@pytest.mark.parametrize(
    ("field", "value"), sorted(_BEHAVIOURALLY_MUTATED.items(), key=lambda kv: kv[0])
)
@pytest.mark.asyncio
async def test_retuning_any_knob_changes_the_pinned_result(
    rules: Rules, field: str, value: object
) -> None:
    """The guard on the guard: THIS is what proves the pins above are a real
    regression gate and not an assertion that merely happens to be true today."""
    overrides: dict[str, object] = {field: value}
    if field in ("bands", "rows"):
        other = "rows" if field == "bands" else "bands"
        overrides[other] = rules.dedup.num_perm // value  # type: ignore[operator]
    retuned = retuned_dedup(rules, **overrides)

    baseline = await _fingerprint(rules)
    mutated = await _fingerprint(retuned)
    assert (
        mutated != baseline
    ), f"retuning {field}={value!r} left the pinned result unchanged"

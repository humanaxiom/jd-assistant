"""Tier-3 role-equivalence — the PURE candidate/veto/scoring maths (Phase 3.4b), no DB.

Every decision the runner embodies is comparison.yaml data (HR-155…HR-160), so each is
pinned **by mutation**: retune the knob (via ``retuned``, which re-validates the shipped
YAML) and watch the behaviour follow. A module that hardcoded a family name or a
threshold in Python would pass a value assertion and fail these.
"""

from __future__ import annotations

import random
from uuid import NAMESPACE_OID, uuid5

import pytest

from src.jd_bank.dedup.models import DocumentRef
from src.jd_bank.dedup.role import (
    RoleDoc,
    ScoredRolePair,
    admit_and_score,
    band_vetoes,
    build_plan,
    compute_idf,
    generate_candidates,
    group_vetoes,
    score_role_pair,
    tier3_stamp,
)
from src.jd_bank.dedup.role.runner import _cosine
from src.jd_core.bank.similarity import skill_overlap
from src.jd_core.models.bank import JobSignals
from src.jd_core.rules import Rules, get_rules
from tests.unit.retuned_rules import retuned


def _highdim(seed: int, dims: int = 768) -> tuple[float, ...]:
    """A 768-dim vector at real embedding magnitude — NOT the synthetic ``[1, 0, 0]``
    that hid the clamps. ``random.Random(11)`` gives a self-cosine that floats above 1.0
    by a float ulp (measured 1.0000000000000002), exactly like a real near-dup pair."""
    r = random.Random(seed)
    return tuple(r.uniform(-1.0, 1.0) for _ in range(dims))


@pytest.fixture
def rules() -> Rules:
    return get_rules()


def _sig(
    *,
    skills: frozenset[str] = frozenset(),
    family: str = "unmapped",
    function: str = "unmapped",
    restricted: bool = False,
    group: str | None = None,
    edu: int | None = None,
    years: int | None = None,
) -> JobSignals:
    return JobSignals(
        skills=skills,
        education_ordinal=edu,
        experience_years=years,
        supervisory_reports=None,
        title="Some Title",
        normalized_title="some title",
        family=family,  # type: ignore[arg-type]
        function=function,  # type: ignore[arg-type]
        comma_supervisory=False,
        restricted=restricted,
        employee_group=group,  # type: ignore[arg-type]
        department=None,
    )


def _doc(
    seed: str, signals: JobSignals, *, vector: tuple[float, ...] | None = None
) -> RoleDoc:
    ref = DocumentRef(
        id=uuid5(NAMESPACE_OID, seed),
        sha256="0" * 64,
        storage_ref=f"archive/{seed}.docx",
        filename=f"{seed}.docx",
    )
    return RoleDoc(ref=ref, signals=signals, vector=vector)


# ── the HARD constraint: the family-band conflict veto ────────────────────────


def test_the_band_veto_drops_a_senior_junior_pair_before_scoring(rules: Rules) -> None:
    """A senior-vs-junior pair (bands 4 and 0, > max_band_gap 1) is dropped at
    ADMISSION, even though — identical skills + vectors — it would otherwise blend to
    ~1.0.
    MUTATION: raise ``max_band_gap`` to 9 and the same pair survives and scores."""
    senior = _doc(
        "a",
        _sig(family="director", skills=frozenset({"python", "sql"})),
        vector=(1.0, 0.0),
    )
    junior = _doc(
        "b",
        _sig(family="assistant", skills=frozenset({"python", "sql"})),
        vector=(1.0, 0.0),
    )
    docs = {senior.ref.id: senior, junior.ref.id: junior}
    idf = compute_idf([senior.signals.skills, junior.signals.skills]).weights
    candidates = {frozenset((senior.ref.id, junior.ref.id))}

    vetoed = admit_and_score(candidates, docs, idf=idf, rules=rules)
    assert vetoed.band_vetoed == 1
    assert vetoed.scored == ()

    loose = retuned(rules, max_band_gap=9)
    survives = admit_and_score(candidates, docs, idf=idf, rules=loose)
    assert survives.band_vetoed == 0
    assert len(survives.scored) == 1
    # ...and it WOULD have been an edge — proving the veto fired pre-scoring, not post.
    assert survives.scored[0].blended >= rules.comparison.role_equiv_threshold


def test_band_veto_never_fires_when_either_side_is_unmapped(rules: Rules) -> None:
    """70% of titles are ``unmapped`` (no band) — the veto is PARTIAL by design
    (HR-155). An unmapped side means the ladder cannot compare them: NOT vetoed."""
    senior = _sig(family="director")
    unmapped = _sig(family="unmapped")
    assert band_vetoes(senior, unmapped, rules.comparison) is False


def test_adjacent_bands_are_admissible_but_two_rungs_apart_are_vetoed(
    rules: Rules,
) -> None:
    mid = _sig(family="manager")  # band 3
    below = _sig(family="lead")  # band 2 (adjacent)
    high = _sig(family="director")  # band 4 (two rungs from below)
    assert band_vetoes(mid, below, rules.comparison) is False
    assert band_vetoes(high, below, rules.comparison) is True


# ── the SOFT constraint: the employee-group veto ──────────────────────────────


def test_group_veto_drops_both_known_and_differing_but_never_a_null(
    rules: Rules,
) -> None:
    apsa = _sig(group="apsa")
    cupe = _sig(group="cupe")
    unknown = _sig(group=None)
    assert group_vetoes(apsa, cupe, rules.comparison) is True
    # a null on either side is an UNKNOWN, never a conflict.
    assert group_vetoes(apsa, unknown, rules.comparison) is False
    assert group_vetoes(unknown, cupe, rules.comparison) is False
    # MUTATION: turn the veto off -> the apsa/cupe pair is no longer dropped.
    off = retuned(rules, group_conflict_veto=False)
    assert group_vetoes(apsa, cupe, off.comparison) is False


# ── the restricted flag ───────────────────────────────────────────────────────


def test_a_restricted_endpoint_flags_the_pair_and_its_edge(rules: Rules) -> None:
    a = _doc(
        "a", _sig(restricted=True, skills=frozenset({"python"})), vector=(1.0, 0.0)
    )
    b = _doc("b", _sig(skills=frozenset({"python"})), vector=(1.0, 0.0))
    idf = compute_idf([a.signals.skills, b.signals.skills]).weights
    scored = score_role_pair(a, b, idf=idf, rules=rules)
    assert scored.restricted is True

    plan = build_plan([scored], comparison=rules.comparison, stamp="stamp123")
    (spec,) = plan.edges.values()
    assert spec.method.endswith("+restricted")  # never silently merged
    (record,) = plan.pairs
    assert record.restricted is True


# ── the threshold boundary ────────────────────────────────────────────────────


def _pair(a: RoleDoc, b: RoleDoc, blended: float) -> ScoredRolePair:
    return ScoredRolePair(
        a=a,
        b=b,
        vector_score=0.0,
        skill_overlap=0.0,
        seniority=0.0,
        blended=blended,
        restricted=False,
        same_function=True,
    )


def test_the_threshold_is_the_boundary_0_5_in_0_4999_out(rules: Rules) -> None:
    a, b = _doc("a", _sig()), _doc("b", _sig())
    comparison = rules.comparison
    at = build_plan([_pair(a, b, 0.5)], comparison=comparison, stamp="s")
    below = build_plan([_pair(a, b, 0.4999)], comparison=comparison, stamp="s")
    assert len(at.edges) == 1
    assert len(below.edges) == 0
    # ...but the below-threshold pair is still REPORTED (for the adjudication sample).
    assert len(below.pairs) == 1 and below.pairs[0].qualifies is False
    # MUTATION: raise the threshold -> 0.5 no longer qualifies.
    strict = retuned(rules, role_equiv_threshold=0.6)
    raised = build_plan([_pair(a, b, 0.5)], comparison=strict.comparison, stamp="s")
    assert len(raised.edges) == 0


# ── idf: deterministic + distinctive-skills-weigh-more ───────────────────────


def test_idf_is_deterministic_over_corpus_and_skill_order() -> None:
    sets = [frozenset({"a", "b"}), frozenset({"b", "c"}), frozenset()]
    forward = compute_idf(sets)
    reverse = compute_idf(list(reversed(sets)))
    assert forward.weights == reverse.weights
    assert forward.stamp == reverse.stamp
    assert forward.num_documents == 3
    # 'a' (df 1) is more distinctive than 'b' (df 2): ln(3/2) > ln(3/3).
    assert forward.weights["a"] > forward.weights["b"]


def test_a_ubiquitous_skill_floors_to_zero_never_negative() -> None:
    """REAL-DATA regression (reviewer must-fix 2). ``ln(N/(1+df))`` goes NEGATIVE when a
    skill is in every signed doc (df -> N). The full archive can't hit it (41% empty
    bags cap max df), but ``--limit`` runs a small slice where it does — a negative idf
    weight drags ``skill_overlap`` (whose ``min(1.0, ...)`` clamps only the top) below
    0, then the blend below 0, crashing ``RolePairRecord.score`` (``ge=0.0``). The
    reviewer's repro corpus: ``[{x, y}, {x}, {x}]`` -> x in all 3 docs.

    MUTATION: drop the ``max(0.0, ...)`` floor in ``compute_idf`` and both asserts red
    (x's weight is ``ln(3/4)`` ~= -0.288, and ``skill_overlap`` returns ~= -2.46)."""
    idf = compute_idf([frozenset({"x", "y"}), frozenset({"x"}), frozenset({"x"})])
    assert idf.weights["x"] == 0.0  # floored; the raw log is ln(3/4) < 0
    assert skill_overlap({"x", "y"}, {"x"}, {}, idf=idf.weights) >= 0.0


# ── candidate generation ──────────────────────────────────────────────────────


def test_cosine_knn_pairs_only_within_a_function_bucket(rules: Rules) -> None:
    a = _doc("a", _sig(function="analyst"), vector=(1.0, 0.0))
    b = _doc("b", _sig(function="analyst"), vector=(0.9, 0.1))
    other = _doc("c", _sig(function="officer"), vector=(1.0, 0.0))
    docs = {d.ref.id: d for d in (a, b, other)}
    candidates = generate_candidates(docs, frozenset(), comparison=rules.comparison)
    assert frozenset((a.ref.id, b.ref.id)) in candidates
    # different function bucket -> never a cosine candidate, however close the vectors.
    assert frozenset((a.ref.id, other.ref.id)) not in candidates


def test_candidate_k_limits_the_number_of_neighbours(rules: Rules) -> None:
    a = _doc("a", _sig(function="analyst"), vector=(1.0, 0.0))
    b = _doc("b", _sig(function="analyst"), vector=(0.99, 0.01))  # very close to a
    c = _doc("c", _sig(function="analyst"), vector=(0.0, 1.0))  # far from both
    docs = {d.ref.id: d for d in (a, b, c)}
    k1 = generate_candidates(
        docs, frozenset(), comparison=retuned(rules, candidate_k=1).comparison
    )
    k2 = generate_candidates(
        docs, frozenset(), comparison=retuned(rules, candidate_k=2).comparison
    )
    assert len(k1) < len(k2)


def test_a_vectorless_pair_is_a_candidate_only_via_a_near_dup_seed(
    rules: Rules,
) -> None:
    """The 118 empty-serialization + 11 token-limit JDs have no vector, so cosine k-NN
    cannot see them — but a Tier-2 near-dup seed still admits them, and they score with
    ``vector_score`` 0.0 rather than crashing (HR-160)."""
    a = _doc("a", _sig(function="analyst"), vector=None)
    b = _doc("b", _sig(function="analyst"), vector=None)
    docs = {a.ref.id: a, b.ref.id: b}
    assert generate_candidates(docs, frozenset(), comparison=rules.comparison) == set()

    seed = frozenset({frozenset((a.ref.id, b.ref.id))})
    candidates = generate_candidates(docs, seed, comparison=rules.comparison)
    assert candidates == {frozenset((a.ref.id, b.ref.id))}
    scored = score_role_pair(a, b, idf={}, rules=rules)
    assert scored.vector_score == 0.0


# ── the empty-skill bimodal floor is honest, not a crash ─────────────────────


def test_empty_skill_pair_scores_on_vector_and_seniority_alone(rules: Rules) -> None:
    """41% of JDs have an empty skill bag — they score on vector + seniority only, and
    ``skill_overlap`` of two empty sets is 0.0 (not an error). The bimodal floor."""
    a = _doc("a", _sig(skills=frozenset()), vector=(1.0, 0.0))
    b = _doc("b", _sig(skills=frozenset()), vector=(1.0, 0.0))
    scored = score_role_pair(a, b, idf={}, rules=rules)
    assert scored.skill_overlap == 0.0
    assert scored.vector_score == pytest.approx(1.0)


def test_a_cosine_that_floats_above_one_is_clamped_not_stored_raw(rules: Rules) -> None:
    """REAL-DATA regression (reviewer must-fix 1). Two near-identical 768-dim embeddings
    compute a doc-vector cosine that floats ABOVE 1.0 by a float ulp — 636 of 3,996 real
    NEAR_DUPLICATE seed pairs (16%) do. That raw value is stored verbatim into
    ``RolePairRecord.vector_score`` (a ``[0, 1]`` field), so without a clamp
    ``build_plan`` raises ``ValidationError`` on the archive's first such pair — a
    guaranteed crash the synthetic ``[1, 0, 0]`` fixtures (cosine EXACTLY 1.0) hid.

    MUTATION: drop the ``max(0.0, min(1.0, ...))`` in ``score_role_pair`` and
    ``build_plan`` raises here instead of returning."""
    vec = _highdim(11)
    # the raw artifact is real, so the clamp is load-bearing — break this, the pin dies
    assert _cosine(vec, vec) > 1.0
    a = _doc("a", _sig(skills=frozenset({"python"})), vector=vec)
    b = _doc("b", _sig(skills=frozenset({"python"})), vector=vec)
    idf = compute_idf([a.signals.skills, b.signals.skills]).weights
    scored = score_role_pair(a, b, idf=idf, rules=rules)
    assert scored.vector_score == 1.0  # clamped, not 1.0000000000000002
    plan = build_plan([scored], comparison=rules.comparison, stamp="s")
    assert plan.pairs[0].vector_score == 1.0  # the [0, 1] field constructs, no crash


# ── the stamp moves on a scoring/idf change (so a retune re-reconciles) ───────


def test_the_stamp_moves_when_a_scoring_knob_or_the_idf_moves(rules: Rules) -> None:
    idf = compute_idf([frozenset({"a"})])
    base = tier3_stamp(rules.comparison, idf)
    assert tier3_stamp(retuned(rules, role_equiv_threshold=0.7).comparison, idf) != base
    reweighted = retuned(
        rules, weight_vector=0.4, weight_skill=0.45, weight_seniority=0.15
    )
    assert tier3_stamp(reweighted.comparison, idf) != base
    # a corpus change moves idf, which moves the stamp too.
    idf2 = compute_idf([frozenset({"a"}), frozenset({"a", "b"})])
    assert tier3_stamp(rules.comparison, idf2) != base

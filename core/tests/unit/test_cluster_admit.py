"""Pure unit tests for Phase-3.5 clustering — admission, EXACT synthesis, the cohesion
cap, the representative, and THE blob guard. No database: content-keyed fakes only.

Each decision is pinned BY MUTATION (retune the shipped YAML, watch behaviour follow),
not merely by reading today's value — the standing bar in this repo.
"""

from __future__ import annotations

import pytest

from src.jd_bank.cluster.admit import admit_edges
from src.jd_bank.cluster.models import BAND_SPREAD, GROUP_MIX, OVERSIZE
from src.jd_bank.cluster.runner import (
    build_cluster_record,
    choose_representative,
    synthesize_exact_edges,
)
from src.jd_bank.db.models import DedupTier
from src.jd_core.bank.clustering import build_clusters
from src.jd_core.rules import Rules, RulesError, get_rules
from tests.unit.cluster_fakes import doc_id, edge, ref, sig
from tests.unit.retuned_rules import retuned

EXACT = DedupTier.EXACT
NEAR = DedupTier.NEAR_DUPLICATE
ROLE = DedupTier.ROLE_EQUIVALENT


@pytest.fixture(scope="module")
def rules() -> Rules:
    return get_rules()


# ── admit_edges: the tiered gate ─────────────────────────────────────────────


def test_a_role_edge_below_the_gate_is_dropped(rules: Rules) -> None:
    signals = {doc_id("a"): sig(), doc_id("b"): sig()}
    admitted, drops = admit_edges(
        [edge("a", "b", tier=ROLE, score=0.6)],
        signals,
        comparison=rules.comparison,
    )
    assert admitted == []
    assert drops.role_below_min == 1


def test_a_role_edge_above_the_gate_survives(rules: Rules) -> None:
    signals = {doc_id("a"): sig(), doc_id("b"): sig()}
    admitted, drops = admit_edges(
        [edge("a", "b", tier=ROLE, score=0.8)],
        signals,
        comparison=rules.comparison,
    )
    assert len(admitted) == 1
    assert drops.role_below_min == 0


def test_exact_and_near_are_not_re_thresholded(rules: Rules) -> None:
    """EXACT/NEAR are strong, well-scaled evidence — the ROLE gate does not apply.
    An EXACT edge always survives (byte-identical endpoints, so no veto fires), and a
    NEAR edge at its own floor is admitted without the ROLE gate."""
    signals = {doc_id("a"): sig(), doc_id("b"): sig()}
    admitted, _ = admit_edges(
        [
            edge("a", "b", tier=EXACT, score=1.0),
            edge("a", "b", tier=NEAR, score=0.85),
        ],
        signals,
        comparison=rules.comparison,
    )
    assert len(admitted) == 2


def test_a_tier_not_in_cluster_tiers_is_dropped(rules: Rules) -> None:
    """Mutation: drop ``exact`` from ``cluster_tiers`` and an EXACT edge is dropped —
    tier-excluded; pins HR-161."""
    without_exact = retuned(rules, cluster_tiers=["near_duplicate", "role_equivalent"])
    signals = {doc_id("a"): sig(), doc_id("b"): sig()}
    admitted, drops = admit_edges(
        [edge("a", "b", tier=EXACT, score=1.0)],
        signals,
        comparison=without_exact.comparison,
    )
    assert admitted == []
    assert drops.tier_excluded == 1


def test_a_director_assistant_edge_is_band_vetoed(rules: Rules) -> None:
    signals = {
        doc_id("dir"): sig(family="director"),
        doc_id("asst"): sig(family="assistant"),
    }
    admitted, drops = admit_edges(
        [edge("dir", "asst", tier=ROLE, score=1.0)],
        signals,
        comparison=rules.comparison,
    )
    assert admitted == []
    assert drops.band_vetoed == 1


def test_an_apsa_cupe_edge_is_group_vetoed_but_apsa_null_survives(rules: Rules) -> None:
    signals = {
        doc_id("apsa"): sig(employee_group="apsa"),
        doc_id("cupe"): sig(employee_group="cupe"),
        doc_id("null"): sig(employee_group=None),
    }
    admitted, drops = admit_edges(
        [
            edge("apsa", "cupe", tier=ROLE, score=0.9),
            edge("apsa", "null", tier=ROLE, score=0.9),
        ],
        signals,
        comparison=rules.comparison,
    )
    assert drops.group_vetoed == 1
    assert {frozenset((e.a, e.b)) for e in admitted} == {
        frozenset((doc_id("apsa"), doc_id("null")))
    }


def test_an_unsignable_endpoint_is_never_a_veto(rules: Rules) -> None:
    """An endpoint absent from the signals map is UNKNOWN, not a "no" — the veto needs
    both sides, so it cannot fire and the edge survives the veto stage."""
    signals = {doc_id("apsa"): sig(employee_group="apsa")}  # "ghost" is unsignable
    admitted, drops = admit_edges(
        [edge("apsa", "ghost", tier=ROLE, score=0.9)],
        signals,
        comparison=rules.comparison,
    )
    assert len(admitted) == 1
    assert drops.band_vetoed == 0
    assert drops.group_vetoed == 0


# ── EXACT synthesis: the connectivity Tier-2 structurally drops ──────────────


def test_a_byte_identical_trio_becomes_a_connected_two_edge_star() -> None:
    same = "f" * 64
    refs = {ref(k, sha256=same).id: ref(k, sha256=same) for k in ("x", "y", "z")}
    edges = synthesize_exact_edges(refs)
    assert len(edges) == 2  # a star on 3, not the clique (which would be 3)
    assert all(e.tier is EXACT and e.score == 1.0 for e in edges)
    components = build_clusters([(e.a, e.b, e.score) for e in edges], threshold=0.0)
    assert len(components) == 1
    assert len(components[0]) == 3


def test_distinct_content_synthesizes_no_exact_edges() -> None:
    refs = {ref(k).id: ref(k) for k in ("x", "y", "z")}  # per-key shas -> all distinct
    assert synthesize_exact_edges(refs) == []


def test_without_exact_synthesis_two_identical_files_split() -> None:
    """The regression pin for the hole: Tier-2 keeps one signature per distinct content,
    so two byte-identical files have NO near-dup edge. WITHOUT synthesis they cluster
    separately; WITH it they reunite. Remove the synthesis and the WITH case goes red.
    """
    same = "a" * 64
    refs = {ref(k, sha256=same).id: ref(k, sha256=same) for k in ("p", "q")}

    without = build_clusters([], threshold=0.0)  # no persisted edge exists for them
    assert without == []  # -> two separate singletons, the bug

    synthesized = synthesize_exact_edges(refs)
    with_synth = build_clusters(
        [(e.a, e.b, e.score) for e in synthesized], threshold=0.0
    )
    assert len(with_synth) == 1 and len(with_synth[0]) == 2  # reunited


# ── the cohesion cap: FLAG, never split ──────────────────────────────────────


def _record(rules: Rules, member_keys: list[str], signals: dict, internal: list):
    refs = {doc_id(k): ref(k) for k in member_keys}
    confidence = {doc_id(k): 1.0 for k in member_keys}
    return build_cluster_record(
        [doc_id(k) for k in member_keys],
        internal,
        signals=signals,
        refs=refs,
        confidence=confidence,
        rules=rules,
    )


def test_a_band_spanning_chain_is_flagged_band_spread(rules: Rules) -> None:
    signals = {
        doc_id("a"): sig(family="assistant"),  # band 0
        doc_id("b"): sig(family="associate"),  # band 1
        doc_id("c"): sig(family="lead"),  # band 2
    }
    record = _record(
        rules,
        ["a", "b", "c"],
        signals,
        [edge("a", "b", tier=ROLE, score=0.9), edge("b", "c", tier=ROLE, score=0.9)],
    )
    assert record.family_band_spread == 2
    assert BAND_SPREAD in record.constraint_violations
    assert record.member_count == 3  # FLAG, not split — membership unchanged


def test_a_null_group_bridged_apsa_cupe_cluster_is_flagged_group_mix(
    rules: Rules,
) -> None:
    signals = {
        doc_id("a"): sig(employee_group="apsa"),
        doc_id("b"): sig(employee_group=None),  # the bridge that dodged the edge veto
        doc_id("c"): sig(employee_group="cupe"),
    }
    record = _record(
        rules,
        ["a", "b", "c"],
        signals,
        [edge("a", "b", tier=ROLE, score=0.9), edge("b", "c", tier=ROLE, score=0.9)],
    )
    assert GROUP_MIX in record.constraint_violations
    assert record.cross_group is True
    assert record.member_count == 3


def test_an_oversize_cluster_is_flagged(rules: Rules) -> None:
    """Mutation: shrink ``cluster_max_size`` to 2 and a 3-member cluster is oversize."""
    small_cap = retuned(rules, cluster_max_size=2)
    signals = {doc_id(k): sig() for k in ("a", "b", "c")}
    record = _record(
        small_cap,
        ["a", "b", "c"],
        signals,
        [edge("a", "b", tier=ROLE, score=0.9), edge("b", "c", tier=ROLE, score=0.9)],
    )
    assert OVERSIZE in record.constraint_violations
    assert record.member_count == 3


def test_a_cohesive_cluster_trips_no_flag(rules: Rules) -> None:
    signals = {
        doc_id(k): sig(family="manager", employee_group="apsa") for k in ("a", "b")
    }
    record = _record(rules, ["a", "b"], signals, [edge("a", "b", tier=NEAR, score=0.9)])
    assert record.constraint_violations == ()


# ── the representative + drift roll-up ───────────────────────────────────────


def test_the_representative_is_the_highest_parse_confidence(rules: Rules) -> None:
    refs = {doc_id(k): ref(k) for k in ("a", "b", "c")}
    confidence = {doc_id("a"): 0.5, doc_id("b"): 0.9, doc_id("c"): 0.9}
    chosen = choose_representative(
        [doc_id(k) for k in ("a", "b", "c")],
        confidence=confidence,
        refs=refs,
        policy="max_parse_confidence",
    )
    # b and c tie at 0.9 -> order_key breaks the tie on storage_ref (b sorts before c)
    assert chosen == doc_id("b")


def test_an_unimplemented_representative_policy_raises(rules: Rules) -> None:
    refs = {doc_id("a"): ref("a")}
    with pytest.raises(RulesError, match="not implemented"):
        choose_representative(
            [doc_id("a")], confidence={doc_id("a"): 1.0}, refs=refs, policy="louvain"
        )


def test_drift_rolls_up_max_and_counts_majors(rules: Rules) -> None:
    signals = {
        doc_id("rep"): sig(skills=frozenset({"alpha", "beta"})),
        doc_id("same"): sig(skills=frozenset({"alpha", "beta"})),  # aligned
        doc_id("far"): sig(skills=frozenset({"gamma", "delta"})),  # disjoint -> major
    }
    # rep has the highest confidence so it is the anchor.
    refs = {doc_id(k): ref(k) for k in ("rep", "same", "far")}
    confidence = {doc_id("rep"): 1.0, doc_id("same"): 0.5, doc_id("far"): 0.5}
    record = build_cluster_record(
        [doc_id(k) for k in ("rep", "same", "far")],
        [
            edge("rep", "same", tier=ROLE, score=0.9),
            edge("rep", "far", tier=ROLE, score=0.9),
        ],
        signals=signals,
        refs=refs,
        confidence=confidence,
        rules=rules,
    )
    assert record.representative_filename == "rep.docx"
    assert record.drift_level_max == "major"
    assert record.drift_major_count == 1
    rep_member = next(m for m in record.members if m.is_representative)
    assert rep_member.drift_vs_representative == "aligned"


# ── THE blob guard: the load-bearing measured decision (HR-162) ──────────────


def _blob_edges() -> list:
    # a 6-node chain of WEAK role edges (0.6: below the 0.75 gate, above 0.5) ...
    chain = [edge(f"n{i}", f"n{i + 1}", tier=ROLE, score=0.6) for i in range(5)]
    # ... plus one genuine STRONG role pair that survives either gate.
    strong = [edge("s0", "s1", tier=ROLE, score=0.9)]
    return chain + strong


def _signals_for_blob() -> dict:
    keys = [f"n{i}" for i in range(6)] + ["s0", "s1"]
    return {doc_id(k): sig() for k in keys}


def test_the_blob_only_forms_below_the_gate(rules: Rules) -> None:
    edges = _blob_edges()
    signals = _signals_for_blob()

    # At the shipped gate (0.75) the weak chain drops: only the strong pair clusters.
    admitted, _ = admit_edges(edges, signals, comparison=rules.comparison)
    at_gate = build_clusters(
        [(e.a, e.b, e.score) for e in admitted], threshold=0.0, rules=rules
    )
    assert max(len(c) for c in at_gate) == 2
    assert len(at_gate) == 1

    # MUTATION — drop the gate to 0.5 and the 6-node blob reappears (red at the gate).
    open_gate = retuned(rules, cluster_role_equiv_min=0.5)
    admitted_lo, _ = admit_edges(edges, signals, comparison=open_gate.comparison)
    blob = build_clusters(
        [(e.a, e.b, e.score) for e in admitted_lo], threshold=0.0, rules=open_gate
    )
    assert max(len(c) for c in blob) == 6

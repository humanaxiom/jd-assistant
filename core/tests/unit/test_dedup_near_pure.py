"""Pure edge-derivation tests for Tier-2 (``jd_bank.dedup.near.runner``'s private
helpers) — no database, no Neo4j. A **content-keyed fake** ``TextSource`` (HANDOFF:
"fakes in this suite must be content-keyed" — 3.2b's index-keyed fake made a whole
class of bug unwritable) stands in for the archive.

**THE landmine test in this file**
(``test_a_six_member_exact_duplicate_group_gets_zero_near_edges_inside_it``) pins the
single most dangerous shape in this module: a naive "skip a pair if it already has an
EXACT edge" check would MISS most of a large ``star``-topology group's internal
pairs (a 6-member group has 15 possible pairs but only 5 EXACT edges under ``star``)
and would happily write NEAR edges for the other 10. This design never performs that
check — candidates are generated over one :class:`~src.jd_bank.dedup.near.models.
Signature` per DISTINCT ``sha256``, so two members of the SAME group can never even
become a candidate. A pair-sized fixture cannot catch a regression here, because
``star`` and ``clique`` coincide on a group of two — this fixture uses six.
"""

from __future__ import annotations

from uuid import UUID

import pytest

from src.jd_bank.dedup.models import DocumentRef, order_key
from src.jd_bank.dedup.near import runner as near_runner
from src.jd_bank.dedup.near.models import CandidatePair, Signature
from src.jd_bank.dedup.near.text import TextResult
from src.jd_core.rules import Dedup, get_rules
from tests.unit.retuned_rules import retuned_dedup


class _FakeTextSource:
    """A content-keyed fake: text is looked up by ``sha256``, never by list index or
    document id — exactly the property HANDOFF's 3.2b lesson demands, so a bug that
    binds the wrong text to the wrong content cannot become structurally
    unwritable-to-catch."""

    def __init__(self, text_by_sha256: dict[str, str]) -> None:
        self._text_by_sha256 = text_by_sha256

    async def text_for(self, ref: DocumentRef) -> TextResult:
        text = self._text_by_sha256.get(ref.sha256)
        if text is None:
            return TextResult(text=None, reason="no fixture text for this sha256")
        return TextResult(text=text)


def _ref(storage_ref: str, *, sha256: str, filename: str | None = None) -> DocumentRef:
    return DocumentRef.for_path(
        storage_ref, sha256=sha256, filename=filename or storage_ref.rsplit("/", 1)[-1]
    )


_LONG_TEXT = (
    "alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu nu xi "
    "omicron pi rho sigma tau upsilon phi chi psi omega"
)


def _small_rules(**overrides: object) -> Dedup:
    base: dict[str, object] = dict(
        redact_boilerplate=False,
        min_shingles=1,
        num_perm=32,
        bands=8,
        rows=4,
        jaccard_min=0.5,
    )
    base.update(overrides)
    return retuned_dedup(get_rules(), **base).dedup


# --- _group_all_by_sha256 ---------------------------------------------------------


def test_group_all_by_sha256_includes_singletons() -> None:
    """UNLIKE Tier-1's ``group_by_sha256`` (groups of 2+ only — a "group" of one is
    not a Tier-1 FINDING), Tier-2 needs a unit for every distinct content."""
    refs = [
        _ref("archive/a.docx", sha256="sha-a"),
        _ref("archive/b.docx", sha256="sha-b"),
    ]
    groups = near_runner._group_all_by_sha256(refs)
    assert set(groups) == {"sha-a", "sha-b"}
    assert len(groups["sha-a"]) == 1


def test_group_all_by_sha256_sorts_members_by_order_key() -> None:
    refs = [
        _ref("archive/z.docx", sha256="sha-x"),
        _ref("archive/a.docx", sha256="sha-x"),
    ]
    groups = near_runner._group_all_by_sha256(refs)
    assert [m.storage_ref for m in groups["sha-x"]] == [
        "archive/a.docx",
        "archive/z.docx",
    ]


# --- _expand_endpoints (edge_scope) ------------------------------------------------


def _signature(rep_id: UUID, group_members: tuple[UUID, ...]) -> Signature:
    return Signature(
        id=rep_id,
        sha256="irrelevant",
        filename=None,
        storage_ref="irrelevant",
        group_members=group_members,
    )


def test_expand_endpoints_content_scope_writes_one_edge_per_content_pair() -> None:
    a_ids = tuple(UUID(int=i) for i in range(1, 4))
    b_ids = tuple(UUID(int=i) for i in range(11, 13))
    pair = CandidatePair(
        a=_signature(a_ids[0], a_ids), b=_signature(b_ids[0], b_ids), jaccard=0.9
    )
    endpoints = near_runner._expand_endpoints(pair, edge_scope="content")
    assert endpoints == [(a_ids[0], b_ids[0])]


def test_expand_endpoints_file_scope_writes_every_cross_group_pair() -> None:
    """MEASURED consequence (HR-140): two 11-member exact-duplicate groups near-dup
    of each other emit 121 edges under `file` scope. Here: 3 x 2 = 6."""
    a_ids = tuple(UUID(int=i) for i in range(1, 4))  # 3 members
    b_ids = tuple(UUID(int=i) for i in range(11, 13))  # 2 members
    pair = CandidatePair(
        a=_signature(a_ids[0], a_ids), b=_signature(b_ids[0], b_ids), jaccard=0.9
    )
    endpoints = near_runner._expand_endpoints(pair, edge_scope="file")
    assert len(endpoints) == 6
    assert set(endpoints) == {(a, b) for a in a_ids for b in b_ids}
    # ...and NONE of them pairs two members of the SAME group with each other.
    a_set, b_set = set(a_ids), set(b_ids)
    assert not any({x, y} <= a_set or {x, y} <= b_set for x, y in endpoints)


# --- orientation: _build_plan always uses order_key, never insertion order --------


def test_build_plan_orients_every_edge_by_order_key_not_by_pair_order() -> None:
    early = _ref("archive/a_early.docx", sha256="sha-early")
    late = _ref("archive/z_late.docx", sha256="sha-late")
    refs_by_id = {early.id: early, late.id: late}
    dedup_rules = _small_rules(edge_scope="content")

    # Constructed BACKWARDS: `b` (early) paired second, `a` (late) paired first.
    pair = CandidatePair(
        a=_signature(late.id, (late.id,)),
        b=_signature(early.id, (early.id,)),
        jaccard=0.9,
    )
    plan = near_runner._build_plan(
        [pair],
        refs_by_id=refs_by_id,
        dedup_rules=dedup_rules,
        segmentation=get_rules().segmentation,
    )
    (((source_a, source_b), spec),) = plan.edges.items()
    assert (source_a, source_b) == (early.id, late.id)
    assert spec.source_a_id == early.id
    assert spec.source_b_id == late.id
    assert order_key(early) < order_key(late)


# --- THE landmine: a 6-member byte-identical group gets ZERO internal edges -------


@pytest.mark.asyncio
async def test_a_six_member_exact_duplicate_group_gets_zero_near_edges_inside_it() -> (
    None
):
    group = [_ref(f"archive/dup_{i}.docx", sha256="sha-dup-group") for i in range(6)]
    outsider = _ref("archive/near_twin.docx", sha256="sha-outsider")

    text_source = _FakeTextSource(
        {"sha-dup-group": _LONG_TEXT, "sha-outsider": _LONG_TEXT}  # near-identical
    )
    dedup_rules = _small_rules(edge_scope="file")  # the scope where the bug would show

    groups = near_runner._group_all_by_sha256([*group, outsider])
    assert len(groups) == 2  # ONE unit for all 6 duplicates, ONE for the outsider

    built = await near_runner._build_signatures(
        groups,
        text_source=text_source,
        dedup_rules=dedup_rules,
        boilerplate_passages=(),
    )
    signatures = built.signatures
    assert built.unreadable_shas == set()
    assert built.below_min_shas == set()
    assert len(signatures) == 2  # never 7 — the 6 duplicates collapse to ONE signature

    candidates = near_runner._lsh_candidates(signatures, dedup_rules=dedup_rules)
    # The only possible candidate is (dup-group, outsider) — structurally, no pair
    # can EVER form between two members of the SAME sha256 group, because there is
    # only one Signature representing all six of them.
    assert candidates == {frozenset({"sha-dup-group", "sha-outsider"})}

    scored = near_runner._score_candidates(candidates, signatures)
    plan = near_runner._build_plan(
        scored,
        refs_by_id={ref.id: ref for ref in [*group, outsider]},
        dedup_rules=dedup_rules,
        segmentation=get_rules().segmentation,
    )

    group_ids = {ref.id for ref in group}
    for source_a, source_b in plan.edges:
        assert not ({source_a, source_b} <= group_ids), (
            "a NEAR edge was written between two members of the same "
            "byte-identical group"
        )
    # ...and every one of the 6 duplicates DID get cross-linked to the outsider —
    # this is not "nothing was written", it is "the internal pairs specifically
    # were never written".
    assert len(plan.edges) == 6
    assert all(
        outsider.id in (a, b) for a, b in plan.edges
    ), "every edge should link a duplicate-group member to the outsider"


# --- max_candidate_pairs: the safety valve raises, never truncates ----------------


def test_lsh_candidates_raises_when_the_safety_valve_is_exceeded() -> None:
    """A tiny corpus, deliberately made INDISTINGUISHABLE to the banding (every
    signature position forced identical) so all N choose 2 pairs bucket together —
    then the valve is set below that count."""
    signatures = {
        f"sha-{i}": Signature(
            id=UUID(int=i + 1),
            sha256=f"sha-{i}",
            filename=None,
            storage_ref=f"archive/{i}.docx",
            group_members=(UUID(int=i + 1),),
            minhash=(1, 2, 3, 4),  # identical for every "document" -> one big bucket
        )
        for i in range(5)
    }
    dedup_rules = _small_rules(bands=1, rows=4, num_perm=4, max_candidate_pairs=3)
    # 5 choose 2 = 10 candidates, valve at 3.
    with pytest.raises(near_runner.CandidateOverflowError):
        near_runner._lsh_candidates(signatures, dedup_rules=dedup_rules)


def test_lsh_candidates_stays_under_the_valve_for_a_normal_run() -> None:
    signatures = {
        f"sha-{i}": Signature(
            id=UUID(int=i + 1),
            sha256=f"sha-{i}",
            filename=None,
            storage_ref=f"archive/{i}.docx",
            group_members=(UUID(int=i + 1),),
            minhash=(1, 2, 3, 4),
        )
        for i in range(5)
    }
    dedup_rules = _small_rules(bands=1, rows=4, num_perm=4, max_candidate_pairs=250_000)
    candidates = near_runner._lsh_candidates(signatures, dedup_rules=dedup_rules)
    assert len(candidates) == 10  # 5 choose 2


# --- _same_position ----------------------------------------------------------------


def test_same_position_true_when_filenames_share_a_position_id() -> None:
    segmentation = get_rules().segmentation
    assert (
        near_runner._same_position(
            "20200101_00012345_Old_Title.doc",
            "20210101_00012345_New_Title.docx",
            segmentation,
        )
        is True
    )


def test_same_position_false_when_filenames_differ_in_position_id() -> None:
    segmentation = get_rules().segmentation
    assert (
        near_runner._same_position(
            "20200101_00012345_Title_A.doc",
            "20200101_00099999_Title_B.doc",
            segmentation,
        )
        is False
    )


def test_same_position_none_when_either_filename_has_no_position_id() -> None:
    segmentation = get_rules().segmentation
    assert (
        near_runner._same_position(
            "no_id_here.doc", "20200101_00012345_X.doc", segmentation
        )
        is None
    )
    assert (
        near_runner._same_position(None, "20200101_00012345_X.doc", segmentation)
        is None
    )


# --- the prune scope: read vs merely fetched (must-fix 1, at unit level) ----------


@pytest.mark.asyncio
async def test_build_signatures_separates_unreadable_from_below_min_shingles() -> None:
    """``read_shas`` is the PRUNE SCOPE, and the two "no signature" outcomes are NOT
    the same thing:

    * ``below_min_shingles`` — the text WAS read; the rulebook declined to sign it. A
      deterministic function of config + text, so it stays IN prune scope (raising
      ``min_shingles`` must delete its edges).
    * ``unreadable`` — the text could not be obtained. An UNKNOWN, not a "no", so it
      must NEVER prune.

    Collapsing the two (either way) is a bug: one direction silently deletes real
    edges on a transient read failure, the other makes ``min_shingles`` unable to
    prune. Both directions are pinned end-to-end in ``tests/integration``.
    """
    readable = _ref("archive/readable.docx", sha256="sha-readable")
    tiny = _ref("archive/tiny.docx", sha256="sha-tiny")
    blind = _ref("archive/blind.docx", sha256="sha-blind")

    class _Source:
        async def text_for(self, ref: DocumentRef) -> TextResult:
            if ref.sha256 == "sha-blind":
                return TextResult(text=None, reason="OSError: simulated")
            if ref.sha256 == "sha-tiny":
                return TextResult(text="one two three")  # far below min_shingles
            return TextResult(text=_LONG_TEXT)

    dedup_rules = _small_rules(min_shingles=10)
    groups = near_runner._group_all_by_sha256([readable, tiny, blind])
    built = await near_runner._build_signatures(
        groups,
        text_source=_Source(),
        dedup_rules=dedup_rules,
        boilerplate_passages=(),
    )

    assert set(built.signatures) == {"sha-readable"}
    assert built.below_min_shas == {"sha-tiny"}
    assert built.unreadable_shas == {"sha-blind"}

    # THE prune scope: signed + below-min, and NOT the unreadable one.
    assert built.read_shas == {"sha-readable", "sha-tiny"}
    assert "sha-blind" not in built.read_shas

    # ...and every sha256 is accounted for exactly once — nothing is silently dropped.
    assert built.read_shas | built.unreadable_shas == set(groups)
    assert not (built.read_shas & built.unreadable_shas)

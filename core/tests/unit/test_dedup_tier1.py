"""Tier-1 exact-duplicate dedup — the pure half: grouping, edge topology, report.

Two properties this suite exists to hold, and both were provenance bugs before 3.1:

* **A duplicate is a FINDING, not a collapse.** Grouping never discards a member. A
  group of 11 byte-identical files is 11 documents and 10 redundant copies — never
  one document and ten forgotten filenames.
* **The edge topology is a DECISION, not an implementation detail** (HR-123). It is a
  rulebook knob, and *both* of its values are implemented — a knob whose alternative
  is unimplemented is the ``cluster_algo`` landmine, which this same PR is fixing.
"""

from __future__ import annotations

import datetime as dt
from uuid import UUID

import pytest

from src.jd_bank.baseline.models import BaselineRow
from src.jd_bank.dedup import (
    EXACT_METHOD,
    EXACT_SCORE,
    DocumentRef,
    build_dedup_report,
    exact_edges,
    group_by_sha256,
    positions_from_baseline_rows,
    refs_from_baseline_rows,
)
from src.jd_core.rules import Rules, get_rules
from tests.unit.retuned_rules import retuned

_A = "a" * 64
_B = "b" * 64
_C = "c" * 64


@pytest.fixture(scope="module")
def rules() -> Rules:
    return get_rules()


def _ref(name: str, sha: str) -> DocumentRef:
    """A ref whose id is a pure function of its path — so a test's edge set is
    reproducible and the ordering key can be asserted, not guessed."""
    return DocumentRef.for_path(f"archive/{name}", sha256=sha, filename=name)


# ── grouping ────────────────────────────────────────────────────────────────


def test_group_by_sha256_keeps_every_member_of_a_duplicate_group() -> None:
    """The provenance fix, stated as a test: N identical files stay N documents."""
    refs = [_ref(f"jd_{i}.docx", _A) for i in range(11)]
    groups = group_by_sha256(refs)

    assert len(groups) == 1
    group = groups[0]
    assert group.size == 11
    assert group.redundant == 10
    assert {member.filename for member in group.members} == {
        f"jd_{i}.docx" for i in range(11)
    }


def test_a_singleton_is_not_a_duplicate_group() -> None:
    groups = group_by_sha256([_ref("only.docx", _A), _ref("other.docx", _B)])
    assert groups == []


def test_grouping_is_deterministic_and_order_independent() -> None:
    """Same files, different walk order -> byte-identical groups. An audit trail
    that reordered itself between runs would not be one."""
    refs = [_ref("c.docx", _A), _ref("a.docx", _A), _ref("b.docx", _A)]
    forward = group_by_sha256(refs)
    backward = group_by_sha256(list(reversed(refs)))

    assert forward == backward
    # members sort by the canonical key (storage_ref), NOT by walk order.
    assert [m.filename for m in forward[0].members] == ["a.docx", "b.docx", "c.docx"]
    assert forward[0].representative.filename == "a.docx"


def test_a_ref_with_no_hash_cannot_be_grouped_and_is_not_silently_dropped() -> None:
    """The one archive file whose bytes are never read (the 89 MB .rtf over the
    extractor's cap) has no sha256. It is not a duplicate of anything — but the
    report must still count it, so it is reported as unhashed, never as absent."""
    rows = (
        _row("big.rtf", sha256=None),
        _row("x.docx", sha256=_A),
        _row("y.docx", sha256=_A),
    )
    report = build_dedup_report(refs_from_baseline_rows(rows), source="test")

    assert report.total_documents == 3
    assert report.unhashed == 1
    assert report.hashed == 2
    assert report.files_in_groups == 2


# ── edge topology (HR-123) ──────────────────────────────────────────────────


def test_star_writes_n_minus_1_edges_all_anchored_on_the_representative(
    rules: Rules,
) -> None:
    groups = group_by_sha256([_ref(f"jd_{i}.docx", _A) for i in range(5)])
    edges = exact_edges(groups, rules=retuned(rules, exact_edge_topology="star"))

    assert len(edges) == 4  # N - 1
    rep = groups[0].representative
    assert {edge.source_a_id for edge in edges} == {rep.id}
    assert {edge.source_b_id for edge in edges} == {
        member.id for member in groups[0].members[1:]
    }


def test_clique_writes_n_choose_2_edges(rules: Rules) -> None:
    """The alternative is IMPLEMENTED, not merely named. A knob whose other value
    does nothing is the `cluster_algo` bug in a new place."""
    groups = group_by_sha256([_ref(f"jd_{i}.docx", _A) for i in range(5)])
    edges = exact_edges(groups, rules=retuned(rules, exact_edge_topology="clique"))

    assert len(edges) == 10  # 5 * 4 / 2
    pairs = {(edge.source_a_id, edge.source_b_id) for edge in edges}
    assert len(pairs) == 10


def test_no_edge_is_written_in_both_directions_under_either_topology(
    rules: Rules,
) -> None:
    """`uq_dedup_pair_tier` is on the ORDERED pair, so it cannot stop (b, a) from
    landing next to (a, b). Only the canonical orientation can, and it is the
    same total order under both topologies."""
    groups = group_by_sha256([_ref(f"jd_{i}.docx", _A) for i in range(6)])
    for topology in ("star", "clique"):
        edges = exact_edges(groups, rules=retuned(rules, exact_edge_topology=topology))
        pairs = {(edge.source_a_id, edge.source_b_id) for edge in edges}
        reversed_pairs = {(b, a) for a, b in pairs}
        assert not (pairs & reversed_pairs)
        assert all(edge.source_a_id != edge.source_b_id for edge in edges)


def test_the_star_is_the_subset_of_the_clique_incident_on_the_representative(
    rules: Rules,
) -> None:
    """Both topologies orient by ONE total order, so a star is never a differently
    -oriented clique subset — which is what would make the two settings write
    conflicting rows into the same unique constraint."""
    groups = group_by_sha256([_ref(f"jd_{i}.docx", _A) for i in range(4)])
    star = set(exact_edges(groups, rules=retuned(rules, exact_edge_topology="star")))
    clique = set(
        exact_edges(groups, rules=retuned(rules, exact_edge_topology="clique"))
    )
    assert star < clique


def test_the_topology_comes_from_the_rulebook_not_from_python(rules: Rules) -> None:
    """MUTATION test: move the YAML value and behaviour must follow. A module
    holding the topology as a Python constant passes every test above and fails
    this one."""
    groups = group_by_sha256([_ref(f"jd_{i}.docx", _A) for i in range(5)])
    assert rules.comparison.exact_edge_topology == "star"
    assert len(exact_edges(groups, rules=rules)) == 4
    assert (
        len(exact_edges(groups, rules=retuned(rules, exact_edge_topology="clique")))
        == 10
    )


def test_an_unimplemented_topology_fails_to_load(rules: Rules) -> None:
    with pytest.raises(ValueError):
        retuned(rules, exact_edge_topology="minimum_spanning_tree")


def test_the_exact_tier_stamps_are_definitional() -> None:
    """Byte-identity is not a similarity estimate: the score is 1.0 by definition
    and the method names the hash. Neither is a knob, and neither may drift."""
    assert EXACT_SCORE == 1.0
    assert EXACT_METHOD == "sha256"


# ── the report ──────────────────────────────────────────────────────────────


def _row(
    filename: str, *, sha256: str | None, position_ids: tuple[str, ...] = ()
) -> BaselineRow:
    return BaselineRow(
        path=f"/archive/{filename}",
        filename=filename,
        sha256=sha256,
        byte_size=1024,
        extension=filename.rsplit(".", 1)[-1],
        format="docx",
        era="new",
        template_token=True,
        position_id=position_ids[0] if position_ids else None,
        position_ids=position_ids,
        status="scored" if sha256 else "skipped",
        file_date=dt.date(2021, 9, 13),
        rules_version="jd_rules_sfu_v4+deadbeefcafe",
        parser_version="jd_segmenter_v1",
        config_stamp="stamp",
    )


def test_the_report_counts_groups_redundancy_and_the_size_distribution() -> None:
    rows = (
        *[_row(f"a{i}.docx", sha256=_A) for i in range(3)],
        *[_row(f"b{i}.docx", sha256=_B) for i in range(2)],
        _row("solo.docx", sha256=_C),
    )
    report = build_dedup_report(refs_from_baseline_rows(rows), source="test")

    assert report.total_documents == 6
    assert report.distinct_sha256 == 3
    assert report.group_count == 2
    assert report.files_in_groups == 5
    # The number of files that could be dropped without losing any CONTENT — and
    # the number of filenames the old unique-sha256 ingest would have discarded.
    assert report.redundant_files == 3
    assert report.group_size_distribution == {2: 1, 3: 1}
    assert report.largest_group_size == 3
    assert report.edges_star == 3  # (3-1) + (2-1)
    assert report.edges_clique == 4  # 3 + 1


def test_the_report_names_the_biggest_groups(rules: Rules) -> None:
    rows = (
        *[_row(f"big{i}.docx", sha256=_A) for i in range(4)],
        *[_row(f"small{i}.docx", sha256=_B) for i in range(2)],
    )
    report = build_dedup_report(
        refs_from_baseline_rows(rows), source="test", top_groups=1, rules=rules
    )

    assert len(report.biggest_groups) == 1
    biggest = report.biggest_groups[0]
    assert biggest.size == 4
    assert biggest.sha256 == _A
    assert biggest.filenames == ("big0.docx", "big1.docx", "big2.docx", "big3.docx")
    # The live topology is stamped, so a report's edge count is reconcilable with
    # the pass that produced the rows.
    assert report.topology == "star"
    assert report.edges_at_topology == report.edges_star


def test_an_archive_with_no_duplicates_reports_zeroes_not_nothing() -> None:
    report = build_dedup_report(
        refs_from_baseline_rows((_row("a.docx", sha256=_A),)), source="test"
    )
    assert report.group_count == 0
    assert report.redundant_files == 0
    assert report.redundancy_rate == 0.0
    assert report.biggest_groups == ()


def test_a_pinned_anchor_keeps_the_star_hubbed_on_it(rules: Rules) -> None:
    """The pure half of the re-anchoring fix. Given the group's ESTABLISHED
    representative, the star stays HUBBED on it — every edge is incident to it — even
    when a member that sorts first has since arrived. Without this, ``exact_edges``
    re-derives ``members[0]`` every pass, the old star's edges survive (the pass never
    deletes), and the two accumulate into the clique.

    Note what is asserted: the anchor is an **endpoint of every edge**, NOT that it is
    ``source_a``. Which endpoint it lands on is decided by ``order_key`` and has nothing
    to do with being the representative — see the next test.
    """
    incumbent = _ref("m_second.docx", _A)
    newcomer = _ref("a_first.docx", _A)  # sorts BEFORE the incumbent
    third = _ref("z_third.docx", _A)  # sorts AFTER it
    groups = group_by_sha256([incumbent, newcomer, third])

    assert groups[0].representative.filename == "a_first.docx"  # the naive rep

    edges = exact_edges(groups, rules=rules, anchors={_A: incumbent.id})

    assert len(edges) == 2  # N - 1, a star — not the 3-edge clique
    # ...and the incumbent, not the sort-first newcomer, is the hub of it.
    assert all(incumbent.id in (edge.source_a_id, edge.source_b_id) for edge in edges)
    assert {edge.source_a_id for edge in edges} | {
        edge.source_b_id for edge in edges
    } == {incumbent.id, newcomer.id, third.id}


def test_a_pinned_anchor_does_not_change_which_way_an_edge_points(
    rules: Rules,
) -> None:
    """**WHO the rep is and HOW an edge is oriented are separate questions.**

    Conflating them was a real bug: star edges were written *from the anchor*, which
    points backwards for every member sorting before it — precisely the case an anchor
    exists to create. Measured on 6 duplicates in reverse arrival order: 4 of the 5
    star edges reversed, and a later flip to ``clique`` then produced 19 edges with 4
    mirrored pairs (a clean clique on 6 is 15, with none).

    ``uq_dedup_pair_tier`` is on the ORDERED triple and cannot catch a mirror, so this
    invariant has nothing but the code holding it up.
    """
    incumbent = _ref("m_second.docx", _A)
    newcomer = _ref("a_first.docx", _A)  # sorts BEFORE the incumbent anchor
    groups = group_by_sha256([incumbent, newcomer])

    edges = exact_edges(groups, rules=rules, anchors={_A: incumbent.id})

    assert len(edges) == 1
    # The anchor is the incumbent — but the EDGE still runs earlier -> later, i.e. from
    # the newcomer. `source_a` is not "the representative"; it is the smaller order_key.
    assert edges[0].source_a_id == newcomer.id
    assert edges[0].source_b_id == incumbent.id


def test_a_re_anchored_star_is_still_a_subset_of_the_clique(rules: Rules) -> None:
    """HR-123 promises that flipping ``star -> clique`` "simply ADDS the missing pairs".
    That is only true if BOTH topologies orient by ``order_key`` — an anchor-oriented
    star is not a subset of the clique, it is a set of mirrors of part of it."""
    refs = [_ref(f"jd_{i}.docx", _A) for i in range(6)]
    groups = group_by_sha256(refs)
    # The rep is the LAST member by sort order — the worst case for orientation.
    anchors = {_A: groups[0].members[-1].id}

    star = set(
        exact_edges(
            groups, rules=retuned(rules, exact_edge_topology="star"), anchors=anchors
        )
    )
    clique = set(
        exact_edges(
            groups, rules=retuned(rules, exact_edge_topology="clique"), anchors=anchors
        )
    )

    assert len(star) == 5
    assert len(clique) == 15
    assert star < clique  # a strict subset — no mirrors, nothing to reconcile

    pairs = {(edge.source_a_id, edge.source_b_id) for edge in clique}
    assert not (pairs & {(b, a) for a, b in pairs})


def test_an_anchor_that_is_no_longer_a_member_falls_back_to_the_sort_order(
    rules: Rules,
) -> None:
    """A rep deleted from the ledger cannot anchor anything. The group falls back to
    ``members[0]`` rather than emitting an edge from a source_id that does not exist."""
    refs = [_ref("a.docx", _A), _ref("b.docx", _A)]
    groups = group_by_sha256(refs)
    stale = _ref("deleted.docx", _A).id

    edges = exact_edges(groups, rules=rules, anchors={_A: stale})
    assert {edge.source_a_id for edge in edges} == {groups[0].members[0].id}


# ── what the duplicates ARE (the Phase-3 finding, computed not narrated) ─────


def test_the_report_separates_shared_jds_from_re_saves() -> None:
    """**The most useful number in the report, and it must be regenerable.**

    A duplicate group can mean two very different things: one position re-saved (noise),
    or several DIFFERENT positions sharing one byte-identical JD — which is real role
    redundancy, and a Phase-3.5 role cluster with the similarity already pinned at 1.0.
    On the real archive it is overwhelmingly the latter (798 of 1,037 groups), and that
    claim lived only in hand-written prose until this test existed.
    """
    rows = (
        # one JD, TWO positions -> real redundancy
        _row("a1.docx", sha256=_A, position_ids=("00001",)),
        _row("a2.docx", sha256=_A, position_ids=("00002",)),
        # one JD, ONE position, saved twice -> a re-save
        _row("b1.docx", sha256=_B, position_ids=("00003",)),
        _row("b2.docx", sha256=_B, position_ids=("00003",)),
        # one JD, no position id at all
        _row("c1.docx", sha256=_C, position_ids=()),
        _row("c2.docx", sha256=_C, position_ids=()),
    )
    report = build_dedup_report(
        refs_from_baseline_rows(rows),
        source="test",
        positions=positions_from_baseline_rows(rows),
    )

    assert report.group_count == 3
    assert report.groups_spanning_multiple_positions == 1
    assert report.groups_within_one_position == 1
    assert report.groups_without_position_id == 1
    assert report.files_in_multi_position_groups == 2


def test_positions_omitted_is_reported_as_unmeasured_never_as_zero() -> None:
    """ "We did not measure the positions" and "no group spans several positions" are
    the two states this report most needs to keep apart — the same rule the baseline's
    ``score=None`` follows."""
    rows = (
        _row("a1.docx", sha256=_A, position_ids=("00001",)),
        _row("a2.docx", sha256=_A, position_ids=("00002",)),
    )
    report = build_dedup_report(refs_from_baseline_rows(rows), source="test")

    assert report.groups_spanning_multiple_positions == 0
    assert report.groups_without_position_id == 1  # unmeasured, and it SAYS so


def test_a_bundled_file_naming_several_positions_spans_them() -> None:
    """A single file can bundle several position ids (the archive does this). A group of
    such files spans every id its members name — the union, not the first."""
    rows = (
        _row("bundle1.docx", sha256=_A, position_ids=("00001", "00002")),
        _row("bundle2.docx", sha256=_A, position_ids=("00001", "00002")),
    )
    report = build_dedup_report(
        refs_from_baseline_rows(rows),
        source="test",
        positions=positions_from_baseline_rows(rows),
    )
    assert report.groups_spanning_multiple_positions == 1


def test_refs_from_baseline_rows_ids_are_stable_across_runs() -> None:
    """The report's synthetic ids are a pure function of the archive path (uuid5),
    exactly as the baseline's synthetic job_id is — so the report's edge counts are
    the counts the DB pass would write, not a differently-shuffled coincidence."""
    rows = (_row("x.docx", sha256=_A),)
    first = refs_from_baseline_rows(rows)
    second = refs_from_baseline_rows(rows)
    assert first == second
    assert isinstance(first[0].id, UUID)

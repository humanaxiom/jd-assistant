"""Tier-3 report artifacts (Phase 3.4b): the committed summary + adjudication sample.

Pure — no DB. Proves the summary is derived from a ``Tier3Result`` (never re-counted),
the adjudication sample stratifies by score band × same/cross-function and is
deterministic, and neither artifact carries document text.
"""

from __future__ import annotations

import csv
from pathlib import Path

from src.jd_bank.dedup.role.models import RolePairRecord, Tier3Result
from src.jd_bank.dedup.role.report import (
    build_role_equiv_summary,
    sample_for_adjudication,
    write_adjudication_csv,
    write_summary,
)


def _pair(
    name: str, score: float, *, same_function: bool = True, restricted: bool = False
) -> RolePairRecord:
    return RolePairRecord(
        filename_a=f"{name}_a.docx",
        filename_b=f"{name}_b.docx",
        score=score,
        vector_score=score,
        skill_overlap=score,
        seniority=0.7,
        family_a="manager",
        family_b="manager",
        restricted=restricted,
        same_function=same_function,
        qualifies=score >= 0.5,
    )


def _result(pairs: tuple[RolePairRecord, ...]) -> Tier3Result:
    return Tier3Result(
        documents_seen=10,
        documents_signed=8,
        documents_unsignable=2,
        documents_with_vector=6,
        documents_without_vector=2,
        candidate_pairs=len(pairs),
        band_vetoed=1,
        group_vetoed=1,
        admissible_pairs=len(pairs),
        qualifying_pairs=sum(1 for p in pairs if p.qualifies),
        restricted_flagged=sum(1 for p in pairs if p.qualifies and p.restricted),
        edges_written=sum(1 for p in pairs if p.qualifies),
        edges_updated=0,
        edges_unchanged=0,
        edges_pruned=0,
        role_equiv_threshold=0.5,
        max_band_gap=1,
        candidate_k=25,
        seed_from_near_dup=True,
        group_conflict_veto=True,
        idf_stamp="idf_v1+abc123456789",
        idf_skills=42,
        dedup_stamp="dedup_role_v1+deadbeefcafe",
        family_distribution={"manager": 5, "unmapped": 3},
        pairs=pairs,
    )


def test_summary_is_derived_from_the_result_not_recounted() -> None:
    pairs = (
        _pair("hi", 0.9, same_function=True),
        _pair("lo", 0.6, same_function=False),
        _pair("below", 0.3),  # below threshold -> not an edge
    )
    summary = build_role_equiv_summary(
        _result(pairs), source="test", rules_version="jd_rules_sfu_v4+deadbeefcafe"
    )
    assert summary.qualifying_pairs == 2
    assert summary.same_function_edges == 1
    assert summary.cross_function_edges == 1
    assert summary.score_percentiles["max"] == 0.9
    assert summary.idf_stamp == "idf_v1+abc123456789"
    assert summary.family_distribution == {"manager": 5, "unmapped": 3}


def test_summary_round_trips_to_json(tmp_path: Path) -> None:
    summary = build_role_equiv_summary(
        _result((_pair("x", 0.8),)),
        source="test",
        rules_version="jd_rules_sfu_v4+deadbeefcafe",
    )
    out = write_summary(summary, tmp_path / "role-equiv-summary.json")
    assert out.exists()
    assert '"dedup_stamp": "dedup_role_v1+deadbeefcafe"' in out.read_text()


def test_adjudication_sample_is_stratified_and_deterministic() -> None:
    pairs = tuple(
        _pair(f"p{i}", 0.1 * (i % 10), same_function=(i % 2 == 0)) for i in range(60)
    )
    first = sample_for_adjudication(pairs, target=20)
    second = sample_for_adjudication(pairs, target=20)
    assert [p.filename_a for p in first] == [p.filename_a for p in second]
    # both same- and cross-function pairs are represented (not only the top edges).
    assert any(p.same_function for p in first)
    assert any(not p.same_function for p in first)


def test_adjudication_csv_has_an_empty_human_label_and_no_text(tmp_path: Path) -> None:
    out = write_adjudication_csv(
        (_pair("x", 0.8, restricted=True),), tmp_path / "adj.csv"
    )
    rows = list(csv.reader(out.read_text(encoding="utf-8").splitlines()))
    assert rows[0][-1] == "human_label"
    assert rows[1][-1] == ""  # empty label — prejudges nothing
    assert rows[1][-2] == "True"  # restricted flag surfaced

"""``jd_bank.dedup.near.report`` — the committed Tier-2 artifacts (Phase 3.3).

Pure-function tests for the summary builder and the adjudication sampler, plus the
two writers (``tmp_path``, no real archive needed). §7(c): the committed summary is
the audit trail an algorithm change lands as a reviewed diff against — these tests
are what keep that artifact's SHAPE trustworthy.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

from src.jd_bank.dedup.near.models import PairRecord, Tier2Result
from src.jd_bank.dedup.near.report import (
    build_near_dup_summary,
    sample_for_adjudication,
    write_adjudication_csv,
    write_summary,
)


def _pair(
    *,
    jaccard: float,
    same_position: bool | None = None,
    qualifies: bool = True,
    filename_a: str = "a.docx",
    filename_b: str = "b.docx",
) -> PairRecord:
    return PairRecord(
        filename_a=filename_a,
        filename_b=filename_b,
        jaccard=jaccard,
        cosine=None,
        same_position=same_position,
        qualifies=qualifies,
    )


def _result(pairs: tuple[PairRecord, ...]) -> Tier2Result:
    # documents_seen (FILES) deliberately != distinct_contents (Tier-1 folded some
    # byte-identical duplicates away already) — a fixture where the two coincide
    # would not catch a bug that divides by the wrong one (see the real archive:
    # 14,565 files -> 12,593 distinct contents). unreadable + below_min_shingles +
    # signed partitions distinct_contents EXACTLY (1 + 1 + 8 == 10), never
    # documents_seen.
    return Tier2Result(
        documents_seen=14,
        distinct_contents=10,
        documents_unreadable=1,
        documents_below_min_shingles=1,
        documents_signed=8,
        candidate_pairs=len(pairs),
        qualifying_pairs=sum(1 for p in pairs if p.qualifies),
        cosine_vetoed=0,
        edges_written=sum(1 for p in pairs if p.qualifies),
        edges_updated=0,
        edges_unchanged=0,
        edges_pruned=0,
        text_source="raw_clean",
        edge_scope="content",
        jaccard_min=0.85,
        cosine_confirm_min=None,
        s_curve_threshold=0.42,
        dedup_stamp="jd_rules_sfu_v4+abc123456789",
        pairs=pairs,
    )


# --- build_near_dup_summary --------------------------------------------------------


def test_coverage_rate_is_documents_signed_over_distinct_contents() -> None:
    # documents_seen=14 (files) != distinct_contents=10 (distinct contents) here on
    # purpose. The bug this pins divided by documents_seen instead: that would give
    # 8 / 14 =~ 0.5714, not the correct 8 / 10 = 0.8 — a fixture where seen ==
    # distinct_contents cannot tell the two formulas apart (this is exactly the
    # unit error the real archive artifact shipped: 85.8% reported vs a true 99.2%).
    result = _result(())
    summary = build_near_dup_summary(
        result, source="test", rules_version="jd_rules_sfu_v4+deadbeefcafe"
    )
    assert summary.coverage_rate == 8 / 10
    assert summary.coverage_rate != 8 / 14
    assert summary.documents_signed == 8
    assert summary.distinct_contents == 10
    assert summary.documents_seen == 14


def test_coverage_rate_is_zero_not_a_division_error_when_no_distinct_contents() -> None:
    result = _result(()).model_copy(
        update={
            "distinct_contents": 0,
            "documents_unreadable": 0,
            "documents_below_min_shingles": 0,
            "documents_signed": 0,
        }
    )
    summary = build_near_dup_summary(result, source="test", rules_version="v")
    assert summary.coverage_rate == 0.0


def test_jaccard_percentiles_are_computed_over_qualifying_pairs_only() -> None:
    pairs = (
        _pair(jaccard=0.9, qualifies=True),
        _pair(jaccard=0.95, qualifies=True),
        _pair(jaccard=0.5, qualifies=False),  # below jaccard_min — excluded
    )
    summary = build_near_dup_summary(_result(pairs), source="test", rules_version="v")
    assert summary.jaccard_percentiles["max"] == 0.95
    assert summary.jaccard_percentiles["p50"] in (0.9, 0.95)  # nearest-rank of 2


def test_jaccard_percentiles_are_zero_not_an_error_with_no_qualifying_pairs() -> None:
    summary = build_near_dup_summary(_result(()), source="test", rules_version="v")
    assert summary.jaccard_percentiles["max"] == 0.0
    assert summary.jaccard_percentiles["p50"] == 0.0


def test_position_split_counts_only_qualifying_pairs() -> None:
    pairs = (
        _pair(jaccard=0.9, same_position=True, qualifies=True),
        _pair(jaccard=0.9, same_position=False, qualifies=True),
        _pair(jaccard=0.9, same_position=None, qualifies=True),
        _pair(jaccard=0.5, same_position=True, qualifies=False),  # excluded
    )
    summary = build_near_dup_summary(_result(pairs), source="test", rules_version="v")
    assert summary.same_position_edges == 1
    assert summary.cross_position_edges == 1
    assert summary.unknown_position_edges == 1


def test_summary_carries_the_stamps_forward_verbatim() -> None:
    result = _result(())
    summary = build_near_dup_summary(
        result, source="parsed_jds", rules_version="jd_rules_sfu_v4+deadbeefcafe"
    )
    assert summary.dedup_stamp == result.dedup_stamp
    assert summary.rules_version == "jd_rules_sfu_v4+deadbeefcafe"
    assert summary.source == "parsed_jds"
    assert summary.s_curve_threshold == result.s_curve_threshold


# --- write_summary ------------------------------------------------------------------


def test_write_summary_creates_parent_dirs_and_writes_valid_json(
    tmp_path: Path,
) -> None:
    summary = build_near_dup_summary(_result(()), source="test", rules_version="v")
    out = tmp_path / "nested" / "near-dup-summary.json"
    written = write_summary(summary, out)
    assert written == out
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["dedup_stamp"] == summary.dedup_stamp
    assert payload["source"] == "test"
    # never document text — only counts/stamps/percentiles/filenames-in-the-CSV-only
    assert "text" not in json.dumps(payload).lower().replace("text_source", "")


# --- sample_for_adjudication ---------------------------------------------------------


def test_sample_for_adjudication_only_includes_qualifying_pairs() -> None:
    pairs = (
        _pair(jaccard=0.9, qualifies=True, filename_a="q1.docx"),
        _pair(jaccard=0.5, qualifies=False, filename_a="nq1.docx"),
    )
    sample = sample_for_adjudication(pairs, jaccard_min=0.85, target=10)
    assert {p.filename_a for p in sample} == {"q1.docx"}


def test_sample_for_adjudication_is_deterministic() -> None:
    pairs = tuple(
        _pair(
            jaccard=0.85 + (i % 15) * 0.01,
            filename_a=f"f{i}a.docx",
            filename_b=f"f{i}b.docx",
        )
        for i in range(40)
    )
    first = sample_for_adjudication(pairs, jaccard_min=0.85, target=20)
    second = sample_for_adjudication(pairs, jaccard_min=0.85, target=20)
    assert first == second


def test_sample_for_adjudication_returns_empty_for_no_qualifying_pairs() -> None:
    pairs = (_pair(jaccard=0.1, qualifies=False),)
    assert sample_for_adjudication(pairs, jaccard_min=0.85, target=200) == []


def test_sample_for_adjudication_never_exceeds_target() -> None:
    pairs = tuple(
        _pair(jaccard=0.9, filename_a=f"f{i}a.docx", filename_b=f"f{i}b.docx")
        for i in range(500)
    )
    sample = sample_for_adjudication(pairs, jaccard_min=0.85, target=50)
    assert len(sample) <= 50


# --- write_adjudication_csv ---------------------------------------------------------


def test_write_adjudication_csv_has_an_empty_human_label_column(
    tmp_path: Path,
) -> None:
    pairs = [
        _pair(jaccard=0.9, filename_a="x.docx", filename_b="y.docx", same_position=True)
    ]
    out = tmp_path / "sample.csv"
    written = write_adjudication_csv(pairs, out)
    assert written == out

    with out.open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 1
    row = rows[0]
    assert row["filename_a"] == "x.docx"
    assert row["filename_b"] == "y.docx"
    assert row["jaccard"] == "0.9000"
    assert row["cosine"] == ""
    assert row["same_position"] == "True"
    assert (
        row["human_label"] == ""
    )  # NEVER pre-filled — this is what adjudication is for


def test_write_adjudication_csv_creates_parent_dirs(tmp_path: Path) -> None:
    out = tmp_path / "nested" / "sample.csv"
    write_adjudication_csv([], out)
    assert out.exists()

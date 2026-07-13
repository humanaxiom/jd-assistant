"""The Phase 2.5 archive-baseline RUNNER: no silent drops, and it segments.

Two properties this suite exists to hold:

1. **NO SILENT DROPS.** Every file the walk finds is accounted for in the output —
   either as a scored row or as a ledger entry with its reason. The ``.tif``, the
   ``.serv``, the ``.dot``s and any antiword failure are themselves a *finding*, not
   noise to be swallowed. ``rows == files`` is asserted by construction.
2. **It segments** — by format, by era, and by dedup population. An un-deduplicated
   approval rate is weighted by how many times a position happened to be re-saved
   (~13.5% of the archive is byte-for-byte duplicate; ~8,160 files are a non-first
   version of an already-seen position — census §7a/b).

The tests build a **synthetic archive** in ``tmp_path``. They must: the real archive is
outside the repo and is not mounted in the ``gates`` container (ADR-006 / HANDOFF
"gotchas"). Everything asserted here is the validator's post-state — never verbatim
text.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest
from docx import Document

from src.jd_bank.baseline.__main__ import main
from src.jd_bank.baseline.aggregate import histogram, population, summarise
from src.jd_bank.baseline.config import get_baseline_config
from src.jd_bank.baseline.models import BaselineRow, BaselineSummary, SegmentStats
from src.jd_bank.baseline.runner import (
    _stable_reason,
    evaluate_file,
    run_baseline,
    write_artifacts,
)
from src.jd_core.parser import PARSER_VERSION
from src.jd_core.rules import Segmentation, get_rules

_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


@pytest.fixture
def config() -> Segmentation:
    return get_baseline_config()


def _names(rows: list[BaselineRow]) -> set[str]:
    return {row.filename for row in rows}


def _docx_bytes(text: str) -> bytes:
    """A real OOXML ``.docx`` — built, not committed as a binary fixture."""
    doc = Document()
    for line in text.splitlines():
        doc.add_paragraph(line)
    out = _FIXTURES / "__scratch.docx"
    doc.save(str(out))
    data = out.read_bytes()
    out.unlink()
    return data


@pytest.fixture
def archive(tmp_path: Path) -> Path:
    """A tiny synthetic archive with every shape the real one has.

    12 files: 2 formats that score, 2 eras, an exact-duplicate pair, a two-version
    position, an unsupported format, a corrupt document, and an oversize-safe stub.
    """
    root = tmp_path / "SFU_JDs"
    root.mkdir()
    new_template = (_FIXTURES / "sfu_new_template.txt").read_text(encoding="utf-8")
    old_template = (_FIXTURES / "sfu_old_template.txt").read_text(encoding="utf-8")

    # -- scored: NEW era (JDFN token), .docx --------------------------------------
    (root / "20200227_00109742_JDFN_APSA_20200227.docx").write_bytes(
        _docx_bytes(new_template)
    )
    # -- scored: NEW era, a SECOND version of the SAME position (later revision) ---
    (root / "20200227_00109742_JDFN_APSA_20240815.docx").write_bytes(
        _docx_bytes(new_template + "\nAdditional Context\nRevised 2024.\n")
    )
    # -- scored: OLD era, legacy binary .doc (antiword; the line-wrapping corpus) --
    (root / "20050220_00001638Intl_undergrad_adv.doc").write_bytes(
        (_FIXTURES / "sample_legacy.doc").read_bytes()
    )
    # -- scored: TRANSITION era, .txt ---------------------------------------------
    (root / "20140101_00002222_Coordinator.txt").write_text(
        old_template, encoding="utf-8"
    )
    # -- scored: an EXACT byte-for-byte duplicate pair (census §7a) ----------------
    # Deliberately NOT the Coordinator's bytes: a third identical file would collapse
    # the pair into a triple and quietly change what this fixture tests. (It did, once.)
    duplicate = (old_template + "\nADDITIONAL CONTEXT\nFront desk coverage.\n").encode(
        "utf-8"
    )
    (root / "20150101_00003333_Clerk.txt").write_bytes(duplicate)
    (root / "20150102_00004444_Clerk_copy.txt").write_bytes(duplicate)
    # -- scored: no position id in the filename (census: ~7% of the archive) -------
    (root / "20160101_Carpenter_JDFN_POLY_20160101.txt").write_text(
        new_template, encoding="utf-8"
    )
    # -- LEDGER: formats with no extraction backend --------------------------------
    (root / "20080101_00005555_Scan.tif").write_bytes(b"II*\x00 not really a tiff")
    (root / "20080102_00005556_Opaque.serv").write_bytes(b"\x00\x01opaque")
    (root / "20080103_00005557_Template.dot").write_bytes(b"\xd0\xcf\x11\xe0 template")
    # -- LEDGER: a supported format whose content is corrupt ------------------------
    (root / "20210101_00006666_Corrupt.docx").write_bytes(b"PK\x03\x04 not a docx")
    # -- LEDGER: a .doc antiword cannot read ----------------------------------------
    (root / "20030101_00007777_Corrupt.doc").write_bytes(b"not a word document at all")
    return root


# --- 1. NO SILENT DROPS ---------------------------------------------------------


def test_every_file_the_walk_finds_becomes_exactly_one_row(
    archive: Path, config: Segmentation
) -> None:
    """The headline guarantee. 14,565 files in, 14,565 rows out — a file that fails
    extraction is a FINDING, not a drop."""
    rows = list(run_baseline(archive, config=config))
    on_disk = sorted(p.name for p in archive.iterdir())
    assert len(rows) == len(on_disk)
    assert sorted(r.filename for r in rows) == on_disk


def test_a_file_with_no_extraction_backend_lands_in_the_ledger_not_the_bin(
    archive: Path, config: Segmentation
) -> None:
    """The ``.tif``, the ``.serv`` and the ``.dot``s (census §8.5: "not text-parseable
    ... need OCR / manual triage")."""
    rows = {r.filename: r for r in run_baseline(archive, config=config)}
    for name in (
        "20080101_00005555_Scan.tif",
        "20080102_00005556_Opaque.serv",
        "20080103_00005557_Template.dot",
    ):
        row = rows[name]
        assert row.status == "skipped"
        assert row.skip_stage == "extract"
        assert "no extraction backend" in (row.skip_reason or "")
        assert row.score is None and row.approved is None
        # ...but it is still IDENTIFIED: hashed, dated, era'd, segmented — so the
        # ledger can be read by era and by format, which is where the pattern is.
        assert row.sha256 and row.era == "old" and row.file_date is not None


def test_a_corrupt_document_lands_in_the_ledger_with_its_reason(
    archive: Path, config: Segmentation
) -> None:
    """A corrupt ``.docx`` and a ``.doc`` antiword refuses are different failures and
    the ledger says which — "route to manual triage", not "score 0"."""
    rows = {r.filename: r for r in run_baseline(archive, config=config)}
    docx = rows["20210101_00006666_Corrupt.docx"]
    assert docx.status == "skipped"
    assert docx.skip_stage == "extract"
    assert "docx parse failed" in (docx.skip_reason or "")

    doc = rows["20030101_00007777_Corrupt.doc"]
    assert doc.status == "skipped"
    assert doc.skip_stage == "extract"
    assert doc.skip_reason


def test_an_oversized_file_is_never_read_into_memory(
    archive: Path, config: Segmentation, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The DoS guard, preserved. ``extract_text`` enforces the 50 MiB cap — but only
    *after* the bytes are in memory, which is why ``extract_text_from_path`` stats
    first. The runner must do the same, or a batch over 14,565 files hands the guard a
    document it has already loaded.

    **Not hypothetical.** MEASURED: exactly one file in the archive exceeds the cap —
    ``19980120_19980120_00000293_Asst_to_Director,_Rec_Services.rtf``, **89,397,431
    bytes**. It is an ``.rtf``, not a ``.doc``: it maps to ``DocumentFormat.RTF``, we
    *have* an extractor for it, and it is skipped on size alone — so it is a JD we could
    otherwise have read, and the ledger must say so rather than filing it under
    "unsupported". This test proves the bytes are never read at all (``read_bytes`` is
    made to explode) and that the row is still produced, segmented and counted.
    """
    monkeypatch.setattr(
        "src.jd_bank.ingest.extract.MAX_DOCUMENT_BYTES", 10, raising=True
    )
    monkeypatch.setattr(
        "src.jd_bank.baseline.runner.MAX_DOCUMENT_BYTES", 10, raising=True
    )

    def _explode(self: Path) -> bytes:  # pragma: no cover - must never be called
        raise AssertionError(f"{self} was read despite exceeding the size cap")

    monkeypatch.setattr(Path, "read_bytes", _explode)

    row = evaluate_file(archive / "20140101_00002222_Coordinator.txt", config=config)
    assert row.status == "skipped"
    assert row.skip_stage == "read"
    assert "exceeds the extractor's cap" in (row.skip_reason or "")
    assert row.sha256 is None  # the whole point: the bytes were never touched
    assert row.byte_size is not None and row.byte_size > 10
    assert row.era == "transition"  # ...and it is STILL segmented and counted


def test_two_runs_over_the_same_archive_produce_byte_identical_rows(
    archive: Path, config: Segmentation, tmp_path: Path
) -> None:
    """Reproducibility is what an audit trail is MADE of — it is why this runner is
    deliberately single-process and un-parallelised. So it has to actually hold.

    It did not. ``extract._extract_doc`` writes each ``.doc`` to a randomly-named
    ``NamedTemporaryFile``, and antiword's failure message quotes that name back
    (``antiword failed: /tmp/tmp0k444cks.doc is not a Word Document``). Two runs over
    the same archive therefore produced *different* ``rows.jsonl`` bytes, and the
    grouped skip ledger reported four identically-broken files as four unique reasons
    with a count of 1 each — measured on the real archive. ``_stable_reason`` scrubs the
    path; nothing else about the message is touched.
    """
    first = [row.model_dump_json() for row in run_baseline(archive, config=config)]
    second = [row.model_dump_json() for row in run_baseline(archive, config=config)]
    assert first == second

    corrupt = next(
        row
        for row in run_baseline(archive, config=config)
        if row.filename == "20030101_00007777_Corrupt.doc"
    )
    assert "<tmpfile>" in (corrupt.skip_reason or "")
    assert tempfile.gettempdir() not in (corrupt.skip_reason or "")
    # ...and the substance of antiword's complaint survives verbatim
    assert "antiword failed" in (corrupt.skip_reason or "")


def test_a_heap_address_never_reaches_the_ledger() -> None:
    """The SECOND source of per-run noise, and it was missed when the first was fixed.

    ``_extract_docx`` hands python-docx a ``BytesIO``, and python-docx puts its **repr**
    in the failure message — carrying a heap address that differs on every run::

        docx parse failed: file '<_io.BytesIO object at 0x7917efaa0590>' is not a Word..

    One real archive file (a macro-enabled ``.docx``) hits this, so ``summary.json`` was
    NOT byte-reproducible across two runs of the same archive — under a runner whose own
    docstring calls reproducibility "the property an audit trail is made of", and which
    is single-process precisely to guarantee it. The tmpfile fix shipped with a
    "verified byte-identical across two real runs" claim that this file falsified.

    The address is our heap layout, not a fact about the JD. Scrub it; keep the rest.
    """
    exc = ValueError(
        "file '<_io.BytesIO object at 0x7917efaa0590>' is not a Word file, "
        "content type is 'application/vnd.ms-word.document.macroEnabled.main+xml'"
    )
    reason = _stable_reason(exc)

    assert "0x" not in reason
    assert "<_io.BytesIO>" in reason
    # The substance — WHICH file type python-docx refused — survives verbatim.
    assert "macroEnabled" in reason
    assert "is not a Word file" in reason
    # Two different heap addresses collapse to one ledger reason, so the grouped
    # skip ledger counts them together instead of reporting N groups of 1.
    other = ValueError(
        "file '<_io.BytesIO object at 0xdeadbeef99>' is not a Word file, "
        "content type is 'application/vnd.ms-word.document.macroEnabled.main+xml'"
    )
    assert _stable_reason(other) == reason


def test_identically_broken_files_group_into_one_ledger_reason(
    archive: Path, config: Segmentation, tmp_path: Path
) -> None:
    """The skip ledger is only useful if it AGGREGATES. "4 files failed to extract for
    this one reason" is a finding; "4 files each failed for their own unique reason" is
    noise that hides it."""
    root = tmp_path / "broken"
    root.mkdir()
    for index in range(4):
        (root / f"20030{index}01_0000777{index}_Corrupt.doc").write_bytes(b"not a word")

    summary = summarise(
        list(run_baseline(root, config=config)), archive_root=str(root), config=config
    )
    assert summary.skipped == 4
    assert len(summary.skip_reasons) == 1
    assert next(iter(summary.skip_reasons.values())) == 4


def test_a_skipped_file_never_lands_in_the_score_distribution(
    archive: Path, config: Segmentation
) -> None:
    """A failed extraction scored as 0 would be the single most misleading number the
    baseline could publish: it would read as "this JD is terrible" when it means "we
    could not open it"."""
    rows = list(run_baseline(archive, config=config))
    summary = summarise(rows, archive_root=str(archive), config=config)
    overall = _segment(summary, "all", "all", "all")
    assert overall.n_files == len(rows)
    assert overall.n_skipped == 5
    assert overall.n_scored == len(rows) - 5
    assert overall.score is not None
    assert overall.score.n == overall.n_scored
    assert summary.skip_reasons  # the ledger, grouped by reason


# --- 2. the run scores real JDs through the ONE public chain ---------------------


def test_a_real_jd_is_scored_through_extract_parse_validate_report(
    archive: Path, config: Segmentation
) -> None:
    """No second extraction path (HANDOFF 2.5 scope): the runner drives this repo's own
    ``extract -> parse_jd -> evaluate_jd_rules -> build_report``, so the baseline
    measures the shipped validator, not a lookalike."""
    row = evaluate_file(
        archive / "20200227_00109742_JDFN_APSA_20200227.docx", config=config
    )
    assert row.status == "scored"
    assert row.score is not None and 0.0 <= row.score <= 100.0
    assert row.grade in {"A", "B", "C", "D", "F"}
    assert row.issue_count == len(row.findings)
    assert row.approved is not None
    assert row.parse_confidence is not None
    assert row.char_count and row.char_count > 0
    # the gate decision and the blocking list are kept in step (GateDecision's own
    # invariant) — a scored row cannot claim "approved" while naming a blocker
    assert row.approved == (not row.blocking_gate_ids)


def test_the_findings_carry_their_rule_ids_and_a_capped_evidence_snippet(
    archive: Path, config: Segmentation
) -> None:
    """The per-rule frequency table is built from these. Evidence is capped: real JD
    binaries are already committed under ``fixtures/golden/``, so JD-derived text
    in-repo is precedented — dumping whole documents into an artifact is not."""
    row = evaluate_file(
        archive / "20050220_00001638Intl_undergrad_adv.doc", config=config
    )
    assert row.status == "scored"
    assert row.rule_ids, "a legacy JD with no findings at all would be suspicious"
    assert set(row.rule_ids) <= set(get_rules().rule_catalog.by_id)
    assert tuple(sorted(set(row.rule_ids))) == row.rule_ids  # sorted + deduped
    for finding in row.findings:
        assert finding.severity in {"info", "low", "medium", "high"}
        if finding.evidence is not None:
            assert len(finding.evidence) <= config.evidence_max_chars


# --- 3. EVERY artifact is stamped ------------------------------------------------


def test_every_row_and_the_summary_are_stamped_with_the_rules_that_produced_them(
    archive: Path, config: Segmentation
) -> None:
    """PR #16 exists for this. "A baseline that cannot say which rulebook produced it is
    not an audit trail" — and that now includes the SEGMENTATION, because which files a
    number was computed over is as load-bearing as the rules it was computed with."""
    rules_version = get_rules().version
    rows = list(run_baseline(archive, config=config))
    for row in rows:
        assert row.rules_version == rules_version
        assert row.parser_version == PARSER_VERSION
        assert row.config_stamp == config.stamp

    summary = summarise(rows, archive_root=str(archive), config=config)
    assert summary.rules_version == rules_version
    assert summary.parser_version == PARSER_VERSION
    assert summary.config_stamp == config.stamp
    assert summary.archive_root == str(archive)
    assert summary.file_count == len(rows)


def test_a_retuned_rulebook_restamps_the_rows(
    archive: Path, config: Segmentation
) -> None:
    """The stamp tracks CONTENT, so a baseline produced under a tuned bar cannot be
    mistaken for one produced under the shipped bar — which is the whole point of 2.5
    being "the trial of the approval bar"."""
    shipped = get_rules()
    tuned = shipped.model_copy(
        update={"scoring": shipped.scoring.model_copy(update={"severity_decay": 0.9})}
    )
    assert tuned.version != shipped.version
    row = evaluate_file(
        archive / "20140101_00002222_Coordinator.txt", config=config, rules=tuned
    )
    assert row.rules_version == tuned.version


# --- 4. the three dedup populations ---------------------------------------------


def test_the_all_population_counts_every_scored_file(
    archive: Path, config: Segmentation
) -> None:
    rows = list(run_baseline(archive, config=config))
    summary = summarise(rows, archive_root=str(archive), config=config)
    assert _segment(summary, "all", "all", "all").n_scored == 7


def test_the_content_dedup_population_collapses_byte_identical_files(
    archive: Path, config: Segmentation
) -> None:
    """Census §7a: ~13.5% of the archive is byte-for-byte duplicate. Counting a JD twice
    because someone re-saved it under a new name weights the approval rate by filing
    habits."""
    rows = list(run_baseline(archive, config=config))
    summary = summarise(rows, archive_root=str(archive), config=config)
    assert _segment(summary, "content_dedup", "all", "all").n_scored == 6  # one pair


def test_the_latest_per_position_population_keeps_only_the_current_jd(
    archive: Path, config: Segmentation
) -> None:
    """Census §7b: ~8,160 files are a non-first version of an already-seen position. The
    approval bar applies to the CURRENT JD for a position, so this is the
    decision-relevant population — and it is the one that must not be silently blended
    away."""
    rows = list(run_baseline(archive, config=config))
    summary = summarise(rows, archive_root=str(archive), config=config)
    # position 00109742 has two versions; only the 2024 revision survives
    assert _segment(summary, "latest_per_position", "all", "all").n_scored == 6

    kept = _names(population(rows, "latest_per_position", config=config))
    assert "20200227_00109742_JDFN_APSA_20240815.docx" in kept
    assert "20200227_00109742_JDFN_APSA_20200227.docx" not in kept


def test_the_latest_version_is_chosen_by_revision_date_not_filename_order(
    archive: Path, config: Segmentation
) -> None:
    """Both versions of 00109742 lead with `20200227`; only the JDFN revision token
    tells
    them apart. Sorting by filename would have kept the 2020 one."""
    rows = [
        r for r in run_baseline(archive, config=config) if r.position_id == "00109742"
    ]
    assert len(rows) == 2
    assert max(r.version_date for r in rows if r.version_date is not None).year == 2024


def test_a_bundled_multi_position_file_is_grouped_by_the_configured_strategy(
    tmp_path: Path, config: Segmentation
) -> None:
    """HR-116. A real filename bundles several positions into one document, and the
    census (§7b) admits that grouping by the FIRST id under-counts the others: position
    ``00000002`` loses a version it genuinely has, so it is represented in the
    current-JD population by an older standalone JD than the bundle that supersedes it.

    Both strategies are implemented, so the registered default is one a reviewer can
    actually change — and this proves it *does* something, rather than pinning a branch.
    """
    root = tmp_path / "bundled"
    root.mkdir()
    template = (_FIXTURES / "sfu_new_template.txt").read_text(encoding="utf-8")
    # the older standalone JD for position 00000002...
    (root / "20200101_00000002_Clerk.txt").write_text(template, encoding="utf-8")
    # ...superseded in 2023 by a bundle naming 00000001 AND 00000002.
    (root / "20230101_00000001,_00000002_Bundle.txt").write_text(
        template, encoding="utf-8"
    )

    rows = list(run_baseline(root, config=config))
    assert config.position_id_grouping == "first"
    kept = _names(population(rows, "latest_per_position", config=config))
    # `first`: the bundle counts only for 00000001, so 00000002 is still represented by
    # its stale 2020 standalone — the census's own admitted under-count, made visible.
    assert set(kept) == {
        "20200101_00000002_Clerk.txt",
        "20230101_00000001,_00000002_Bundle.txt",
    }

    grouped_all = config.model_copy(update={"position_id_grouping": "all"})
    kept_all = _names(population(rows, "latest_per_position", config=grouped_all))
    # `all`: the bundle IS the current JD of 00000002 too, so the stale standalone drops
    # out — and the bundle appears ONCE, not once per position it names.
    assert set(kept_all) == {"20230101_00000001,_00000002_Bundle.txt"}
    assert len(kept_all) == 1


def test_a_file_with_no_position_id_is_kept_and_the_choice_is_configurable(
    archive: Path, config: Segmentation
) -> None:
    """~7% of the real archive carries no zero-padded id. Dropping them from the
    decision-relevant population would silently shrink it; keeping them is the shipped
    default AND a registered knob, not a hidden one."""
    rows = list(run_baseline(archive, config=config))
    kept = _names(population(rows, "latest_per_position", config=config))
    assert "20160101_Carpenter_JDFN_POLY_20160101.txt" in kept

    dropped = config.model_copy(update={"keep_files_without_position_id": False})
    kept_without = _names(population(rows, "latest_per_position", config=dropped))
    assert "20160101_Carpenter_JDFN_POLY_20160101.txt" not in kept_without


# --- 5. the aggregation maths ----------------------------------------------------


def test_the_score_distribution_is_min_median_mean_max_and_a_histogram(
    archive: Path, config: Segmentation
) -> None:
    rows = list(run_baseline(archive, config=config))
    scored = sorted(r.score for r in rows if r.score is not None)
    stats = _segment(
        summarise(rows, archive_root=str(archive), config=config), "all", "all", "all"
    ).score
    assert stats is not None
    assert stats.minimum == pytest.approx(scored[0])
    assert stats.maximum == pytest.approx(scored[-1])
    assert stats.mean == pytest.approx(sum(scored) / len(scored))
    assert sum(b.count for b in stats.histogram) == len(scored)
    # bins tile [0, 100] at the configured width, in order, with no gaps
    assert [b.lower for b in stats.histogram] == [
        0.0,
        10.0,
        20.0,
        30.0,
        40.0,
        50.0,
        60.0,
        70.0,
        80.0,
        90.0,
    ]


def test_a_perfect_score_lands_in_the_top_bin_not_off_the_end(
    config: Segmentation,
) -> None:
    """The classic histogram off-by-one: 100.0 belongs in the 90-100 bin, and if it
    silently vanished the top of the distribution would be under-reported."""
    bins = histogram([0.0, 99.9, 100.0], bin_width=config.score_histogram_bin)
    assert bins[0].count == 1
    assert bins[-1].count == 2
    assert sum(b.count for b in bins) == 3


def test_the_rule_frequency_counts_files_not_findings(
    archive: Path, config: Segmentation
) -> None:
    """ "The top of the finding-frequency table is a bug list, not a quality verdict"
    (HANDOFF). A rule that fires 6 times inside ONE JD must not out-rank a rule that
    fires once in every JD — so the table counts FILES, and the finding total is
    reported separately."""
    rows = list(run_baseline(archive, config=config))
    stats = _segment(
        summarise(rows, archive_root=str(archive), config=config), "all", "all", "all"
    )
    for rule_id, files in stats.rule_frequency.items():
        expected = sum(1 for r in rows if rule_id in r.rule_ids)
        assert files == expected
        assert files <= stats.n_scored


def test_the_gate_frequency_counts_the_gates_that_blocked_approval(
    archive: Path, config: Segmentation
) -> None:
    rows = list(run_baseline(archive, config=config))
    stats = _segment(
        summarise(rows, archive_root=str(archive), config=config), "all", "all", "all"
    )
    blocked = sum(1 for r in rows if r.approved is False)
    assert stats.approved == stats.n_scored - blocked
    assert stats.approval_rate == pytest.approx(stats.approved / stats.n_scored)
    for gate_id, files in stats.gate_frequency.items():
        assert files == sum(1 for r in rows if gate_id in r.blocking_gate_ids)


def test_every_segment_is_reported_for_every_population(
    archive: Path, config: Segmentation
) -> None:
    """The brief: score/grade/rule/gate/approval "each broken down by every segmentation
    above" — format, era, and dedup population."""
    rows = list(run_baseline(archive, config=config))
    summary = summarise(rows, archive_root=str(archive), config=config)
    keys = {(s.population, s.dimension, s.value) for s in summary.segments}
    for name in ("all", "content_dedup", "latest_per_position"):
        assert (name, "all", "all") in keys
        assert (name, "format", "doc") in keys
        assert (name, "format", "docx") in keys
        assert (name, "era", "old") in keys
        assert (name, "era", "new") in keys


def test_an_empty_segment_reports_no_score_rather_than_a_zero(
    config: Segmentation,
) -> None:
    """A segment with nothing in it must not report `mean=0.0` / `approval_rate=0.0` —
    "no data" and "everything failed" are the two things this baseline most needs to
    keep apart."""
    summary = summarise([], archive_root="/archive", config=config)
    overall = _segment(summary, "all", "all", "all")
    assert overall.n_scored == 0
    assert overall.score is None
    assert overall.approval_rate is None


# --- 6. the artifacts ------------------------------------------------------------


def test_the_artifacts_are_jsonl_plus_a_summary_and_account_for_every_file(
    archive: Path, config: Segmentation, tmp_path: Path
) -> None:
    rows = list(run_baseline(archive, config=config))
    summary = summarise(rows, archive_root=str(archive), config=config)
    out = tmp_path / "out"
    written = write_artifacts(out, rows=rows, summary=summary)

    assert {p.name for p in written} == {"rows.jsonl", "errors.jsonl", "summary.json"}

    lines = (out / "rows.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == len(rows)
    first = json.loads(lines[0])
    assert first["rules_version"] == get_rules().version
    assert {"path", "sha256", "format", "era", "score", "grade", "rule_ids"} <= set(
        first
    )

    errors = (out / "errors.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(errors) == sum(1 for r in rows if r.status == "skipped")

    doc = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert doc["file_count"] == len(rows)
    assert doc["scored"] + doc["skipped"] == doc["file_count"]
    assert doc["rules_version"] == get_rules().version


def test_the_committed_artifacts_are_the_audit_trail_not_the_corpus_dump(
    archive: Path, config: Segmentation, tmp_path: Path
) -> None:
    """A baseline that only exists in a gitignored directory is not an audit trail.

    ``summary.json`` (every number the written read rests on, fully stamped) and
    ``errors.jsonl`` (the skip ledger IS a finding) go to ``docs/baseline/`` and are
    committed. ``rows.jsonl`` — 14,565 rows carrying evidence snippets — is a bulk
    derived copy of the corpus and stays in the ignored working directory. The
    ``fixtures/golden/`` precedent is for CURATED fixtures, not a dump.
    """
    rows = list(run_baseline(archive, config=config))
    summary = summarise(rows, archive_root=str(archive), config=config)
    out, committed = tmp_path / "out", tmp_path / "docs-baseline"

    write_artifacts(out, rows=rows, summary=summary, commit_dir=committed)

    assert {p.name for p in committed.iterdir()} == {"summary.json", "errors.jsonl"}
    assert not (committed / "rows.jsonl").exists()
    # ...and the committed copies are the same artifacts, not a lossy re-render
    assert (committed / "summary.json").read_text(encoding="utf-8") == (
        out / "summary.json"
    ).read_text(encoding="utf-8")
    assert (committed / "errors.jsonl").read_text(encoding="utf-8") == (
        out / "errors.jsonl"
    ).read_text(encoding="utf-8")


def test_population_membership_is_recomputable_from_rows_jsonl_alone(
    archive: Path, config: Segmentation, tmp_path: Path
) -> None:
    """Why the summary ships **no** membership list (it would be ~2.2 MB of filenames
    in a ~150 KB file): it does not need to. ``population()`` is a pure function of the
    rows and the config, and every row carries the ``sha256`` / ``position_ids`` /
    ``version_date`` it needs — plus the ``config_stamp`` naming the policy that grouped
    them. So membership is derivable from the artifact, with no second copy to drift.
    """
    rows = list(run_baseline(archive, config=config))
    out = tmp_path / "out"
    write_artifacts(
        out,
        rows=rows,
        summary=summarise(rows, archive_root=str(archive), config=config),
    )

    # ...re-read the artifact from disk, as a consumer would, and re-derive
    reloaded = [
        BaselineRow.model_validate_json(line)
        for line in (out / "rows.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert {row.config_stamp for row in reloaded} == {config.stamp}

    for name in ("all", "content_dedup", "latest_per_position"):
        assert _names(population(reloaded, name, config=config)) == _names(
            population(rows, name, config=config)
        )
    # and it agrees with the counts the summary DOES ship
    summary = summarise(rows, archive_root=str(archive), config=config)
    for name in ("all", "content_dedup", "latest_per_position"):
        assert (
            len(population(reloaded, name, config=config))
            == _segment(summary, name, "all", "all").n_files
        )


# --- 7. the sampling flags (used to smoke the runner without the full 8-9 min) ----


def test_limit_takes_the_first_n_files_deterministically(
    archive: Path, config: Segmentation
) -> None:
    first = [r.filename for r in run_baseline(archive, config=config, limit=3)]
    assert len(first) == 3
    assert first == [r.filename for r in run_baseline(archive, config=config, limit=3)]
    assert first == sorted(first)


def test_sample_spreads_evenly_across_the_sorted_archive(
    archive: Path, config: Segmentation
) -> None:
    """The archive sorts by date, so an evenly-spaced sample spans eras and formats by
    construction — no RNG, no seed, and reproducible for whoever re-runs it."""
    sampled = [r.filename for r in run_baseline(archive, config=config, sample=4)]
    assert len(sampled) == 4
    assert sampled == [
        r.filename for r in run_baseline(archive, config=config, sample=4)
    ]
    assert len(set(sampled)) == 4


@pytest.mark.parametrize("flag", ["--limit", "--sample"])
def test_a_non_positive_limit_or_sample_is_refused_not_treated_as_everything(
    archive: Path, config: Segmentation, flag: str
) -> None:
    """``--sample 0`` used to fall straight through to a FULL run — on the real corpus
    that is 14,565 files and ~9 minutes, and the output would then be read as a
    *sample*. A quiet mis-scoping of an artifact is what this phase cannot afford."""
    value = 0 if flag == "--limit" else -1
    with pytest.raises(ValueError, match="must be a positive number of files"):
        kwargs = {flag.lstrip("-"): value}
        list(run_baseline(archive, config=config, **kwargs))  # type: ignore[arg-type]


def test_an_empty_archive_root_is_refused_loudly(
    tmp_path: Path, config: Segmentation
) -> None:
    """The compose service binds ``${JD_ARCHIVE_PATH:-./archive}``; an unset variable
    would otherwise bind an empty directory and produce a confident baseline of nothing.
    """
    empty = tmp_path / "nothing"
    empty.mkdir()
    with pytest.raises(FileNotFoundError, match="no files"):
        list(run_baseline(empty, config=config))


# --- 8. the CLI (`python -m src.jd_bank.baseline`) --------------------------------


def test_the_cli_runs_the_baseline_and_writes_every_artifact(
    archive: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "cli-out"
    assert main(["--archive", str(archive), "--out", str(out)]) == 0

    rows = (out / "rows.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(rows) == len(list(archive.iterdir()))
    summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert summary["rules_version"] == get_rules().version

    printed = capsys.readouterr().err
    assert get_rules().version in printed
    assert "all accounted for" in printed


def test_the_cli_refuses_an_empty_archive_rather_than_baselining_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Exit 2, loudly. Not exit 0 with an empty, fully-stamped summary that reads like a
    real result."""
    empty = tmp_path / "nothing"
    empty.mkdir()
    assert main(["--archive", str(empty), "--out", str(tmp_path / "out")]) == 2
    assert "no files" in capsys.readouterr().err


def test_the_cli_sample_flag_scores_a_subset(archive: Path, tmp_path: Path) -> None:
    out = tmp_path / "sampled"
    assert main(["--archive", str(archive), "--out", str(out), "--sample", "4"]) == 0
    assert len((out / "rows.jsonl").read_text(encoding="utf-8").splitlines()) == 4


# --- helper ----------------------------------------------------------------------


def _segment(
    summary: BaselineSummary, population: str, dimension: str, value: str
) -> SegmentStats:
    for segment in summary.segments:
        if (segment.population, segment.dimension, segment.value) == (
            population,
            dimension,
            value,
        ):
            return segment
    raise AssertionError(f"no segment {population}/{dimension}/{value}")

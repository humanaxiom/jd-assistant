"""Filename facets: format, era, position ID, dates — the SEGMENTATION half of 2.5.

The archive baseline is worthless unless it segments (HANDOFF "2.5 — the brief"). A
blended, whole-corpus approval rate is a **category error**: ``SFU-COMP-TERRITORIAL`` /
``-ABOUT`` / ``-EDI`` fire on nearly every pre-2019 JD because those sections *did not
exist in the template those JDs were authored under*, and ``SFU-APPROVE-EDI-FOOTER``
blocks. Reporting "the archive is catastrophically non-compliant" would be reporting
that much of it is simply **old**.

So era, the template token, and the dedup population are policy calls, and they are
**data** — ``jd_core/rules/segmentation.yaml``, an ordinary rule file (CLAUDE.md §2),
registered as HR-109 … HR-118. Never literals in this module's logic.

Every number asserted here was measured against the real archive
(``C:\\repos\\hris\\fixtures\\SFU_JDs``, 14,565 files) — see
``test_the_shipped_defaults_are_the_ones_measured_against_the_archive``, which also
records the one place we do NOT agree with the Phase-0 census.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

import pytest
import yaml

from src.jd_bank.baseline.config import get_baseline_config
from src.jd_bank.baseline.facets import file_facets
from src.jd_core.rules import RULE_FILES, RulesError, Segmentation, load_rules

_PKG_DIR = Path(__file__).resolve().parents[2] / "src" / "jd_core" / "rules"


@pytest.fixture
def config() -> Segmentation:
    return get_baseline_config()


def _rules_dir(tmp_path: Path, mutate: Any = None) -> Path:
    """A scratch copy of the shipped rulebook, with ``segmentation.yaml`` mutated.

    The same helper shape ``test_decision_register`` uses. It exists because the
    segmentation policy is not a bespoke config with a bespoke loader any more — it is a
    rule file, so it is corrupted and re-loaded exactly like ``thresholds.yaml`` is.
    """
    for name in RULE_FILES:
        (tmp_path / name).write_text(
            (_PKG_DIR / name).read_text(encoding="utf-8"), encoding="utf-8"
        )
    if mutate is not None:
        path = tmp_path / "segmentation.yaml"
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        mutate(data)
        path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return tmp_path


# --- the config is DATA, and it identifies itself ------------------------------


def test_the_segmentation_policy_ships_as_a_rule_file_not_as_literals(
    config: Segmentation,
) -> None:
    """CLAUDE.md §2, unqualified: versioned decision YAML lives under
    ``src/jd_core/rules/``. Era bands, the template token and the dedup knobs are
    decisions, so they are data — in the rulebook, like every other decision."""
    assert "segmentation.yaml" in RULE_FILES
    assert (_PKG_DIR / "segmentation.yaml").is_file()
    assert config.era_template_token == "JDFN"
    assert config.era_old_max_year == 2009
    assert config.era_transition_max_year == 2018
    assert config.position_id_grouping == "first"


def test_the_segmentation_stamps_itself_with_its_own_content_digest(
    config: Segmentation,
) -> None:
    """It is excluded from ``rules_version`` (it cannot move a score), so it needs an
    identity of its own — otherwise a baseline could not say which population it
    describes. Same contract as ``Rules.content_hash``: derived from content, moves when
    the content moves."""
    assert config.digest == config.digest  # deterministic
    moved = config.model_copy(update={"era_transition_max_year": 2017})
    assert moved.digest != config.digest
    assert moved.stamp != config.stamp
    assert config.stamp.startswith(config.version)
    assert config.digest[:12] in config.stamp


def test_era_bands_must_be_ordered(tmp_path: Path) -> None:
    """A transition band below the old band would make `transition` unreachable — a
    segment that can never be assigned is this rulebook's "a gate that can never fire"
    failure, so it is a LOAD error."""
    directory = _rules_dir(
        tmp_path,
        lambda d: d.update(era_old_max_year=2018, era_transition_max_year=2009),
    )
    with pytest.raises(RulesError, match="era_old_max_year"):
        load_rules(directory)


def test_a_malformed_regex_is_a_load_error(tmp_path: Path) -> None:
    directory = _rules_dir(
        tmp_path,
        lambda d: d["position_id_pattern"].__setitem__("pattern", "(unclosed"),
    )
    with pytest.raises(RulesError):
        load_rules(directory)


def test_an_unknown_key_is_a_load_error(tmp_path: Path) -> None:
    """``extra="forbid"``: a tunable number cannot be smuggled in without a field to
    hold it — and a field that exists is automatically on the decision surface, because
    ``segmentation`` is a FLAT surface file. Both halves of the guarantee."""
    directory = _rules_dir(tmp_path, lambda d: d.__setitem__("fudge_factor", 1.5))
    with pytest.raises(RulesError):
        load_rules(directory)


def test_an_unimplemented_grouping_strategy_is_a_load_error(tmp_path: Path) -> None:
    """The ``comparison.cluster_algo`` landmine, pre-empted: a ``Literal``, not a free
    string, so a data-only switch to a strategy nobody wrote fails loudly instead of
    silently doing nothing while the artifact claims otherwise."""
    directory = _rules_dir(
        tmp_path, lambda d: d.__setitem__("position_id_grouping", "cleverest")
    )
    with pytest.raises(RulesError):
        load_rules(directory)


# --- format --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "extension", "fmt"),
    [
        ("20210401_00124799_JDFN_APSA_20210401.docx", "docx", "docx"),
        ("19670501_00006855Assistant_to_assoc_dean.doc", "doc", "doc"),
        ("20200101_00000001_Macro.docm", "docm", "docx"),  # OOXML, reads as docx
        ("20200101_00000001_Note.txt", "txt", "txt"),
        ("20200101_00000001_Note.rtf", "rtf", "rtf"),
        ("20200101_00000001_Template.dot", "dot", "other"),
        ("20200101_00000001_Scan.tif", "tif", "other"),
        ("20200101_00000001_Opaque.serv", "serv", "other"),
        ("20040127_00006875Program_assistant_Jan2004.doc.doc", "doc", "doc"),
    ],
)
def test_format_is_the_extension_the_extractor_will_dispatch_on(
    config: Segmentation, name: str, extension: str, fmt: str
) -> None:
    """The mandated ``.doc`` vs ``.docx`` split (antiword wraps; python-docx does not).
    The raw extension is kept alongside it, because ``.docm``/``.dot``/``.tif`` all
    collapse into a ``DocumentFormat`` and the ledger must still name them."""
    facets = file_facets(Path("/archive") / name, config)
    assert facets.extension == extension
    assert facets.format == fmt


# --- era ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "era"),
    [
        # pure date bands (census §4a)
        ("19670501_00006855Assistant_to_assoc_dean.doc", "old"),
        ("20091231_00000001_Clerk.doc", "old"),
        ("20100101_00000001_Clerk.doc", "transition"),
        ("20181125_00124410_Communications_Associate.docx", "transition"),
        ("20190731_00102112_Compensation_Consultant.docx", "new"),
        # ...and the template token OVERRIDES the date band, in both directions.
        # 50 real JDFN files predate 2019 (1 in 2010, 1 in 2012, 1 in 2015, 2 in 2016,
        # 20 in 2017, 25 in 2018): they were authored under the CURRENT template, so
        # the current bar is the one they should be judged against.
        ("20180322_Carpenter_JDFN_POLY_20200216.docx", "new"),
        ("20170101_00000001_JDFN_APSA_20170101.docx", "new"),
    ],
)
def test_era_is_the_template_token_first_then_the_date_band(
    config: Segmentation, name: str, era: str
) -> None:
    """Census §4b: "Era for [the 2008-2021 middle band] is most reliably inferred from
    the ``JDFN`` filename token, not body headings.\" """
    assert file_facets(Path("/archive") / name, config).era == era


def test_a_file_with_no_date_prefix_is_era_unknown(config: Segmentation) -> None:
    """Not a silent default to `old`: an unclassifiable file says so, and the summary
    counts it. (Measured: 0 of 14,565 real files land here — every one carries a
    YYYYMMDD prefix — but the segment exists rather than guessing.)"""
    assert file_facets(Path("/archive/Clerk.doc"), config).era == "unknown"
    assert file_facets(Path("/archive/Clerk.doc"), config).file_date is None


def test_the_body_era_and_the_archive_era_are_different_things(
    config: Segmentation,
) -> None:
    """A named trap: ``jd_core.parser.headings.Era`` is old/new/unknown derived from the
    document BODY. This era is old/transition/new/unknown derived from the FILENAME.
    They answer different questions and must never be conflated — so the vocabularies
    differ, and the row carries both."""
    from src.jd_core.parser import headings

    assert "transition" not in headings.Era.__args__  # type: ignore[attr-defined]


# --- position id, dates, employee group -----------------------------------------


def test_the_position_id_is_the_zero_padded_id_the_census_counted(
    config: Segmentation,
) -> None:
    """A zero-padded 8-digit id cannot collide with the YYYYMMDD prefix or the JDFN
    revision date (both start `19`/`20`), which is what makes the pattern safe."""
    facets = file_facets(
        Path("/archive/20210401_00110783_JDFN_APSA_20210401.docx"), config
    )
    assert facets.position_id == "00110783"
    assert facets.position_ids == ("00110783",)


def test_a_multi_id_bundle_keeps_every_id_and_groups_by_the_first(
    config: Segmentation,
) -> None:
    """Real filename. Census §7b flags bundles as the reason ID-based near-dup counting
    OVER-counts, so the bundle is recorded in full and the *primary* (first) id is the
    grouping key — stated, not hidden."""
    facets = file_facets(
        Path("/archive/20220201_00114560,_00114369,_00132130_JDFN_APSA_20220201.docx"),
        config,
    )
    assert facets.position_ids == ("00114560", "00114369", "00132130")
    assert facets.position_id == "00114560"


def test_an_unpadded_legacy_id_is_not_claimed_as_a_position_id(
    config: Segmentation,
) -> None:
    """Real filename (`43353`). The census's own id count is zero-padded-only; claiming
    a 5-digit token would also claim years and percentages. It becomes a row with no
    position id, which the `latest_per_position` population then handles explicitly."""
    assert (
        file_facets(Path("/archive/20060411_43353Technician.doc"), config).position_id
        is None
    )


def test_dates_and_employee_group_are_read_off_the_filename(
    config: Segmentation,
) -> None:
    facets = file_facets(
        Path("/archive/20180322_Carpenter_JDFN_POLY_20200216.docx"), config
    )
    assert facets.file_date == dt.date(2018, 3, 22)
    assert facets.revision_date == dt.date(2020, 2, 16)
    assert facets.employee_group == "POLY"
    assert facets.template_token is True
    # The version key prefers the REVISION date: this JD was re-issued in 2020, and
    # "which is the current JD for this position" is what the population turns on.
    assert facets.version_date == dt.date(2020, 2, 16)


def test_the_version_date_falls_back_to_the_file_date(config: Segmentation) -> None:
    """143 of the 4,637 real JDFN files carry no revision token, and 9,928 files are not
    JDFN at all. They are versioned by their leading date, not dropped."""
    facets = file_facets(
        Path("/archive/20120111_00111026_Student_Recruiter.doc"), config
    )
    assert facets.revision_date is None
    assert facets.version_date == dt.date(2012, 1, 11)


def test_an_impossible_date_does_not_crash_the_run(config: Segmentation) -> None:
    """The runner walks 14,565 real files and must be total. A filename can say
    anything; `20211301` is not a month."""
    facets = file_facets(Path("/archive/20211301_00000001_Clerk.doc"), config)
    assert facets.file_date is None
    assert facets.era == "unknown"


def test_the_shipped_defaults_are_the_ones_measured_against_the_archive(
    config: Segmentation,
) -> None:
    """EVERY CLAIM ABOUT THE ARCHIVE MUST BE CHECKED AGAINST THE ARCHIVE (HANDOFF), and
    that includes the claims in this docstring. Each was re-measured by running the
    SHIPPED pattern over all 14,565 real filenames:

    * ``JDFN`` — 4,637 files (census §3 says 4,637 too).
    * ``era_old_max_year=2009`` / ``era_transition_max_year=2018`` — the census §4a
      bands. On the leading date prefix: 3,339 / 5,014 / 6,212 files.
    * the zero-padded id — **13,572** of 14,565 files carry one; **993** carry none.

    ⚠ **The distinct-position count is NOT a single number, and an earlier version of
    this file asserted one that was neither.** It depends on how a bundled filename is
    counted (HR-116):

    * ``position_id_grouping: first`` (shipped) → **5,327** distinct positions;
    * ``position_id_grouping: all``            → **5,541** distinct positions.

    The census (§7b) reported **5,436**, which matches neither — a ~2% divergence, not
    the "~0.2%" a previous version of this docstring reconciled away around a number
    (5,428) that was an artefact of the *measuring command*, not of the shipped pattern.
    The gap is real, it is stated, and it is not explained away. `first` is shipped
    because it reproduces the census's METHOD, not its number.
    """
    assert config.era_template_token == "JDFN"
    assert (config.era_old_max_year, config.era_transition_max_year) == (2009, 2018)
    assert config.position_id_pattern.pattern == r"(?<![0-9])(0[0-9]{7})(?![0-9])"
    assert config.position_id_grouping == "first"

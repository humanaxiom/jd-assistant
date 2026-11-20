"""The archive-filename POSITION reader (``jd_bank/positions``), one test per real name.

Every filename below is a REAL archive basename (all 14,565 were measured; see the
``filename_positions`` block of ``segmentation.yaml`` and HR-325 … HR-331). The reader
is SEPARATE from ``segmentation.position_id_pattern`` on purpose: the baseline and
near-dedup stay on the padded form, so nothing here may move a registered baseline
number — :func:`test_the_padded_baseline_pattern_is_untouched` pins that.
"""

from __future__ import annotations

import random
import string
import uuid

import pytest
from pydantic import ValidationError

from src.jd_bank.positions import (
    FilenameFacets,
    PositionIndex,
    normalise_position_id,
    read_filename,
)
from src.jd_core.rules import FilenamePositions, Segmentation, get_rules

NONE: frozenset[str] = frozenset()


@pytest.fixture
def seg() -> Segmentation:
    return get_rules().segmentation


def _ids(facets: FilenameFacets) -> list[str]:
    return [p.id8 for p in facets.positions]


def _retuned(seg: Segmentation, **changes: object) -> Segmentation:
    block = seg.filename_positions.model_copy(update=changes)
    return seg.model_copy(update={"filename_positions": block})


# --- one test per real name ---------------------------------------------------


def test_an_unpadded_leading_bundle_reads_every_position(seg: Segmentation) -> None:
    name = "20200601_61,_30785,_208,_975_JDFN_APSA_20211117.docx"
    facets = read_filename(name, seg, frozenset({"00000061"}))
    assert _ids(facets) == ["00000061", "00030785", "00000208", "00000975"]
    assert {p.source for p in facets.positions} == {"leading"}
    assert [p.raw for p in facets.positions] == ["61", "30785", "208", "975"]
    assert str(facets.as_of_date) == "2020-06-01"
    assert str(facets.jd_date) == "2021-11-17"
    assert facets.employee_group == "APSA"


def test_a_two_digit_id_counts_only_when_another_name_vouches_for_it(
    seg: Segmentation,
) -> None:
    name = "20200601_61,_30785,_208,_975_JDFN_APSA_20211117.docx"
    assert _ids(read_filename(name, seg, NONE)) == ["00030785", "00000208", "00000975"]
    vouched = read_filename(name, seg, frozenset({"00000061"})).positions[0]
    assert vouched.vouched is True


def test_a_labelled_position_is_read_and_the_grade_is_not(seg: Segmentation) -> None:
    facets = read_filename("20090601_Secretary,_gr_6,_Pos.__1433.doc", seg, NONE)
    assert _ids(facets) == ["00001433"]
    assert facets.positions[0].source == "labelled"


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("20070322_98184_Clerk_Typist,_Gr._6.rtf", ["00098184"]),
        ("20060612_Clerk,_gr_7,_64368,_Res___Housing.doc", []),
        ("20060512_ITP_I,_grade_10_Job_Description_(NIES).doc", []),
        ("20080222_06863_Secretary_gr7.doc", ["00006863"]),
    ],
)
def test_a_grade_number_is_never_a_position(
    seg: Segmentation, name: str, expected: list[str]
) -> None:
    # Vouch for every small number, so only the GRAMMAR can keep a grade out.
    vouched = frozenset(f"{n:08d}" for n in range(1, 20))
    assert _ids(read_filename(name, seg, vouched)) == expected


def test_a_template_number_is_dropped_unless_vouched(seg: Segmentation) -> None:
    name = "20200101_14_-_Template_JDFN_Director,_Admin.docx"
    assert _ids(read_filename(name, seg, NONE)) == []
    assert _ids(read_filename(name, seg, frozenset({"00000014"}))) == ["00000014"]


def test_a_seven_digit_00_token_is_dropped_unless_vouched(seg: Segmentation) -> None:
    name = "20171005_0011878_Business_Analyst.docx"
    assert _ids(read_filename(name, seg, NONE)) == []
    assert _ids(read_filename(name, seg, frozenset({"00011878"}))) == ["00011878"]


def test_a_nine_digit_000_token_normalises_to_eight(seg: Segmentation) -> None:
    facets = read_filename("20030527_000101719_Clerk.doc", seg, NONE)
    assert _ids(facets) == ["00101719"]
    assert facets.positions[0].vouched is False  # kept without corroboration


def test_a_caret_tail_is_not_a_position(seg: Segmentation) -> None:
    name = "20230308_1081_1115_1320_1080_11083^1_JDFN_CUPE_20230418.docx"
    # Vouch for 00000001 too: the tail must be refused by the grammar, not the gate.
    vouched = frozenset({"00000001", "00001080", "00001081"})
    ids = _ids(read_filename(name, seg, vouched))
    assert set(ids) == {"00001080", "00001081", "00001115", "00001320", "00011083"}
    assert "00000001" not in ids


def test_an_id_above_the_ceiling_is_rejected(seg: Segmentation) -> None:
    assert _ids(read_filename("20150101_001354781_Analyst.docx", seg, NONE)) == []


def test_a_second_leading_date_is_a_date_not_a_position(seg: Segmentation) -> None:
    facets = read_filename("20110525_20070810_01038_Clerk_Typist_gr5.doc", seg, NONE)
    assert _ids(facets) == ["00001038"]


def test_a_caret_joined_padded_pair_reads_both(seg: Segmentation) -> None:
    facets = read_filename(
        "20260624_00126035^00138583_JDFN_APSA_20260624.docx", seg, NONE
    )
    assert _ids(facets) == ["00126035", "00138583"]
    assert all(p.vouched for p in facets.positions)


def test_a_padded_id_outside_the_leading_list_is_still_read(seg: Segmentation) -> None:
    """The reader is a SUPERSET of the padded pattern, so no consumer can regress."""
    facets = read_filename("20100101_Clerk_00012345_rev.doc", seg, NONE)
    assert _ids(facets) == ["00012345"]
    assert facets.positions[0].source == "padded"


def test_dates_group_and_title_are_read_and_a_bad_date_is_none(
    seg: Segmentation,
) -> None:
    facets = read_filename("20211301_00012345_Program_Assistant.docx", seg, NONE)
    assert facets.as_of_date is None  # month 13: the filename lied
    assert facets.jd_date is None and facets.employee_group is None
    assert facets.title_slug == "Program Assistant"


def test_the_reader_never_raises_on_arbitrary_strings(seg: Segmentation) -> None:
    rng = random.Random(325)
    alphabet = string.digits * 4 + string.ascii_letters + "_,^.#() -" + "é"
    samples = [
        "",
        "_",
        "^",
        "20200101",
        "20200101_",
        "20200101_^^^,,__",
        "Pos",
        "x" * 500,
    ]
    for _ in range(2000):
        prefix = rng.choice(["", "20200601_", "19991231__", "20209999_"])
        body = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 60)))
        samples.append(prefix + body)
    for name in samples:
        facets = read_filename(name, seg, frozenset({"00000001"}))
        assert all(len(p.id8) == 8 and p.id8.isdigit() for p in facets.positions)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("61", "00000061"),
        ("000101719", "00101719"),
        ("00012345", "00012345"),
        ("0", None),
        ("0000", None),
        ("1000000", None),
        ("", None),
        ("12a", None),
    ],
)
def test_normalise_position_id(raw: str, expected: str | None) -> None:
    assert normalise_position_id(raw, max_position_id=999999) == expected


# --- the knobs are READ, not hardcoded ---------------------------------------


def test_the_corroboration_gate_is_read_from_the_rulebook(seg: Segmentation) -> None:
    off = _retuned(
        seg,
        corroboration={
            "unvouched_min_digits": 0,
            "seven_digit_00_requires_corroboration": False,
        },
    )
    assert _ids(read_filename("20171005_0011878_Business_Analyst.docx", off, NONE)) == [
        "00011878"
    ]
    assert _ids(
        read_filename("20200101_14_-_Template_JDFN_Director,_Admin.docx", off, NONE)
    ) == ["00000014"]


def test_the_ceiling_and_caret_tail_are_read_from_the_rulebook(
    seg: Segmentation,
) -> None:
    low = _retuned(seg, max_position_id=100000)
    assert _ids(read_filename("20030527_000101719_Clerk.doc", low, NONE)) == []
    tail = _retuned(seg, caret_tail_min_digits=1)
    name = "20230308_1081_1115_1320_1080_11083^1_JDFN_CUPE_20230418.docx"
    assert "00000001" in _ids(read_filename(name, tail, frozenset({"00000001"})))


def test_the_bare_trailing_tier_cannot_be_switched_on(seg: Segmentation) -> None:
    data = {
        "leading_list_pattern": {"pattern": r"^(\d+)", "ignore_case": False},
        "labelled_position_pattern": {"pattern": r"Pos(\d+)", "ignore_case": False},
        "max_position_id": 999999,
        "corroboration": {
            "unvouched_min_digits": 3,
            "seven_digit_00_requires_corroboration": True,
        },
        "caret_tail_min_digits": 3,
        "bare_trailing_ids": False,
        "consumers": ["crf"],
    }
    FilenamePositions.model_validate(data)
    with pytest.raises(ValidationError, match="bare_trailing_ids"):
        FilenamePositions.model_validate({**data, "bare_trailing_ids": True})
    with pytest.raises(ValidationError):
        FilenamePositions.model_validate({**data, "consumers": ["baseline"]})
    with pytest.raises(ValidationError):
        FilenamePositions.model_validate(
            {**data, "corroboration": {"unvouched_min_digits": 3}}
        )
    with pytest.raises(ValidationError, match="group 1"):
        FilenamePositions.model_validate(
            {**data, "leading_list_pattern": {"pattern": "^x", "ignore_case": False}}
        )


def test_the_padded_baseline_pattern_is_untouched(seg: Segmentation) -> None:
    """HR-114's numbers, near-dedup's ``_same_position`` and the baseline all read the
    PADDED pattern. Widening it moves registered numbers; the reader is separate."""
    assert seg.position_id_pattern.pattern == r"(?<![0-9])(0[0-9]{7})(?![0-9])"
    assert "crf" in seg.filename_positions.consumers


def test_the_filename_positions_knobs_are_registered_open() -> None:
    rules = get_rules()
    entries = {
        d.id: d
        for d in rules.decision_register.decisions
        if d.config.path.startswith("segmentation.filename_positions.")
    }
    assert sorted(entries) == [f"HR-{n}" for n in range(325, 332)]
    for decision in entries.values():
        assert decision.status == "open"
        assert decision.provenance == "our_invention"


# --- the index -----------------------------------------------------------------


def test_the_index_vouches_from_other_filenames_and_maps_both_ways(
    seg: Segmentation,
) -> None:
    bundle, other, nothing = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    index = PositionIndex.build(
        [
            (bundle, "20200601_61,_30785,_208,_975_JDFN_APSA_20211117.docx"),
            (other, "20190101_00000061_Clerk.docx"),
            (nothing, None),
        ],
        seg,
    )
    assert index.positions_of(bundle) == (
        "00000061",
        "00030785",
        "00000208",
        "00000975",
    )
    assert index.positions_of(nothing) == ()
    assert index.positions_of(uuid.uuid4()) == ()
    assert set(index.docs_for("00000061")) == {bundle, other}
    assert index.docs_for("00030785") == (bundle,)
    assert index.files_with_positions == 2

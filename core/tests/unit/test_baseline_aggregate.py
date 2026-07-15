"""The current-practice cohort and the WJQ facet (Phase 3.4).

The GUARDRAIL that must land with the WJQ parser: a CUPE/WJQ JD scored on the JDFN bar
is a category error, so it is excluded from the cohort HR ratifies the bar against.
Pinned by MUTATION — with the exclusion off
(``segmentation.wjq_excluded_from_current_practice: false``) a current-era WJQ file
lands in the cohort and moves its approval rate; with it on, the cohort is WJQ-free.
"""

from __future__ import annotations

import datetime as dt

import pytest

from src.jd_bank.baseline import current_practice_cohort, get_baseline_config, summarise
from src.jd_bank.baseline.models import BaselineRow
from src.jd_core.rules import Segmentation


def _row(
    *,
    name: str,
    era: str,
    template: str,
    approved: bool,
    rule_ids: tuple[str, ...] = (),
    status: str = "scored",
) -> BaselineRow:
    return BaselineRow(
        path=f"archive/{name}",
        filename=name,
        extension="docx",
        format="DOCX",
        era=era,  # type: ignore[arg-type]
        template_token=True,
        status=status,  # type: ignore[arg-type]
        template=template,
        score=80.0,
        grade="B",
        issue_count=0,
        rule_ids=rule_ids,
        approved=approved,
        rules_version="jd_rules_sfu_v4+deadbeefcafe",
        parser_version="jd_segmenter_v2",
        config_stamp="stamp",
    )


@pytest.fixture()
def cohort_rows() -> list[BaselineRow]:
    # A JDFN current-practice JD (approved) + a WJQ current-era JD (blocked). Both are
    # `current` era and neither trips the territorial gate, so ONLY the template clause
    # decides whether the WJQ row is in the cohort.
    return [
        _row(name="jdfn.docx", era="current", template="jdfn", approved=True),
        _row(name="wjq.docx", era="current", template="wjq", approved=False),
        # noise that never qualifies on the other two clauses
        _row(name="old.docx", era="old", template="jdfn", approved=True),
        _row(
            name="nofooter.docx",
            era="current",
            template="jdfn",
            approved=False,
            rule_ids=("SFU-COMP-TERRITORIAL",),
        ),
    ]


def _config(*, exclude_wjq: bool) -> Segmentation:
    return get_baseline_config().model_copy(
        update={"wjq_excluded_from_current_practice": exclude_wjq}
    )


def test_cohort_excludes_wjq_when_the_knob_is_on(
    cohort_rows: list[BaselineRow],
) -> None:
    cohort = current_practice_cohort(cohort_rows, config=_config(exclude_wjq=True))
    names = {row.filename for row in cohort}
    assert names == {"jdfn.docx"}  # WJQ-free; no old-era, no territorial-blocked
    approval = sum(1 for r in cohort if r.approved) / len(cohort)
    assert approval == 1.0


def test_without_the_exclusion_wjq_contaminates_the_cohort_and_moves_approval(
    cohort_rows: list[BaselineRow],
) -> None:
    """The mutation: flip the knob off and the WJQ JD enters the cohort — and because it
    is blocked, it drags the approval rate down. This is the number HR would ratify."""
    cohort = current_practice_cohort(cohort_rows, config=_config(exclude_wjq=False))
    names = {row.filename for row in cohort}
    assert names == {"jdfn.docx", "wjq.docx"}
    approval = sum(1 for r in cohort if r.approved) / len(cohort)
    assert approval == 0.5  # moved from 1.0 — the contamination the exclusion prevents


def test_the_shipped_default_excludes_wjq() -> None:
    assert get_baseline_config().wjq_excluded_from_current_practice is True


def test_template_is_reported_as_its_own_facet() -> None:
    """WJQ appears as a `template` segment, so nobody quotes its JDFN-bar score inside
    the current-practice cohort."""
    rows = [
        _row(name="a.docx", era="current", template="jdfn", approved=True),
        _row(name="b.docx", era="current", template="wjq", approved=False),
    ]
    summary = summarise(
        rows, archive_root="archive", generated_at=dt.datetime(2026, 7, 15)
    )
    template_values = {
        seg.value for seg in summary.segments if seg.dimension == "template"
    }
    assert {"jdfn", "wjq"} <= template_values

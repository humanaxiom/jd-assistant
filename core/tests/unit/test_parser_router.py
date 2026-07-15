"""The template router (Phase 3.4) must not perturb the JDFN/legacy path.

The hard guard on the WJQ work: adding a router in front of ``parse_jd`` is only safe
if a document that is NOT a WJQ questionnaire parses EXACTLY as before. Two committed
golden snapshots (`fixtures/golden_jdfn/*.json`) pin the full parsed output of the
canonical NEW and OLD fixtures; if the router ever routes one of them to the WJQ
segmenter — or otherwise changes the JDFN parse — the snapshot comparison fails.

To see this guard bite: make ``is_wjq`` return ``True`` unconditionally and both
assertions below go red (the fixtures route to WJQ and no longer match their golden).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.jd_core.parser import ParseResult, parse_jd

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
GOLDEN = FIXTURES / "golden_jdfn"


def _snapshot(result: ParseResult) -> dict[str, object]:
    return {
        "template": result.template,
        "era": result.era,
        "parse_confidence": result.parse_confidence,
        "section_confidence": result.section_confidence,
        "jd": result.jd.model_dump(mode="json"),
    }


@pytest.mark.parametrize("stem", ["sfu_new_template", "sfu_old_template"])
def test_jdfn_fixture_parses_byte_identical_to_its_golden(stem: str) -> None:
    text = (FIXTURES / f"{stem}.txt").read_text(encoding="utf-8")
    result = parse_jd(text)
    assert result.template == "jdfn"
    golden = json.loads((GOLDEN / f"{stem}.json").read_text(encoding="utf-8"))
    assert _snapshot(result) == golden


def test_jdfn_duties_carry_no_frequency() -> None:
    """`SFUDuty.frequency` is additive: the JDFN template has no frequency tag, so every
    JDFN duty leaves it ``None`` (and the golden above records exactly that)."""
    text = (FIXTURES / "sfu_new_template.txt").read_text(encoding="utf-8")
    duties = parse_jd(text).jd.duties
    assert duties
    assert all(d.frequency is None for d in duties)

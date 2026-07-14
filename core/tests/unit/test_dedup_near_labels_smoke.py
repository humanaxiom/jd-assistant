"""§7(b) — the label-set SMOKE test. NEVER a percentage.

**Why not a precision/recall gate against ``fixtures/labels/pairs.csv``.** MEASURED
(HANDOFF 2026-07-13): same-position "negative" pairs in that file have HIGHER median
Jaccard (0.30) than cross-position LSH "candidate" pairs (0.58) — the negatives are
MORE similar than the candidates, at every threshold tried the hard-negative rate
exceeds the weak-positive rate, and 69-73% of the near-dup edges this pass would
write are cross-position (Tier-1 found the identical shape: 77% of exact-duplicate
groups span more than one position — SFU's redundancy is cross-position CLONING, not
within-position revision). The label set is 101 pairs / 44 files / 12 near-dup
positives, the column is literally ``best_guess_label``, and it was authored in
Phase 0 citing a census this repo later found wrong. Optimising a threshold against
it would be tuning against the wrong oracle, not a better oracle.

**What this file does instead.** At most a SMOKE check: a high-confidence near-dup
pair's text, if committed as a fixture, must appear as an LSH CANDIDATE (never that it
must become an EDGE — the whole point of HR-138 is that Jaccard alone decides that,
and 0.85 is unratified); a high-confidence "different" pair's text must NEVER become
an edge.

**Provenance note — read before trusting this file's specific numbers.**
``fixtures/labels/pairs.csv`` lives at the REPO ROOT (``C:\\repos\\JD-Assistant\\
fixtures\\labels\\pairs.csv``), and the `gates` container mounts only ``./core`` —
so it is invisible here, and even if it were visible, it names real archive
FILENAMES, not committed TEXT (the archive itself is external, read-only, and its
content is never committed into this repo as a fixture — the same boundary
``core/tests/fixtures/neardup/`` already respects). So this file does NOT replay
the real 101 labels. It is a SYNTHETIC analogue, built from committed text this repo
already owns, that exercises the exact CI-gate shape §7(b) asks for: a
high-confidence "same" pair must candidate, a high-confidence "different" pair must
never edge. Treat every number in THIS file as a fixture property, never as a claim
about the real label set or the real archive.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.jd_bank.dedup.models import DocumentRef
from src.jd_bank.dedup.near import runner as near_runner
from src.jd_bank.dedup.near.text import TextResult
from src.jd_core.rules import Rules, get_rules

_FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "neardup"

#: (file_a, file_b, confidence-shaped label) — the SAME shape as `pairs.csv`'s
#: columns (`doc_a, doc_b, best_guess_label`), applied to this repo's own committed
#: fixture text rather than to real archive filenames/content.
_HIGH_CONFIDENCE_SAME = ("role_summary_v1.txt", "role_summary_v1_reformatted.txt")
_HIGH_CONFIDENCE_DIFFERENT = ("role_summary_v1.txt", "unrelated.txt")


class _FixtureTextSource:
    def __init__(self, text_by_sha256: dict[str, str]) -> None:
        self._text_by_sha256 = text_by_sha256

    async def text_for(self, ref: DocumentRef) -> TextResult:
        return TextResult(text=self._text_by_sha256[ref.sha256])


def _refs(names: tuple[str, ...]) -> list[DocumentRef]:
    return [
        DocumentRef.for_path(
            f"fixtures/neardup/{name}", sha256=f"sha-{name}", filename=name
        )
        for name in names
    ]


async def _candidates_and_plan(
    rules: Rules, names: tuple[str, ...]
) -> tuple[set[frozenset[str]], dict[object, object]]:
    refs = _refs(names)
    groups = near_runner._group_all_by_sha256(refs)
    boilerplate = rules.boilerplate
    passages = (
        boilerplate.about_sfu
        + boilerplate.territorial_acknowledgement
        + boilerplate.employment_equity
    )
    built = await near_runner._build_signatures(
        groups,
        text_source=_FixtureTextSource(
            {f"sha-{n}": (_FIXTURE_DIR / n).read_text(encoding="utf-8") for n in names}
        ),
        dedup_rules=rules.dedup,
        boilerplate_passages=passages,
    )
    signatures = built.signatures
    candidates = near_runner._lsh_candidates(signatures, dedup_rules=rules.dedup)
    scored = near_runner._score_candidates(candidates, signatures)
    refs_by_id = {ref.id: ref for ref in refs}
    plan = near_runner._build_plan(
        scored,
        refs_by_id=refs_by_id,
        dedup_rules=rules.dedup,
        segmentation=rules.segmentation,
    )
    return candidates, dict(plan.edges)


@pytest.mark.asyncio
async def test_a_high_confidence_same_pair_becomes_an_lsh_candidate() -> None:
    """The weakest possible claim this suite makes about "same": Tier-2 must at
    least consider comparing the two exactly — never silently skip them."""
    rules = get_rules()
    candidates, _edges = await _candidates_and_plan(rules, _HIGH_CONFIDENCE_SAME)
    assert len(candidates) == 1


@pytest.mark.asyncio
async def test_a_high_confidence_different_pair_never_becomes_an_edge() -> None:
    rules = get_rules()
    _candidates, edges = await _candidates_and_plan(rules, _HIGH_CONFIDENCE_DIFFERENT)
    assert edges == {}

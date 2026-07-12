"""Phase 2.5 — the archive baseline.

Runs the SHIPPED validator + gate runner across the real SFU JD archive (14,565 files)
and produces the quality-baseline data. It is **the trial of the approval bar, not of
the archive**: the score floor of 60, the grade floor of C, the severity floor, the
14-rule blocking set and the 2 non-overridable gates are all ``our_invention`` and none
of them has been ratified by SFU. This run is the first time they meet real data, and it
is allowed to kill them.

Two things shape everything in this package:

* **It segments, or it lies.** ``SFU-COMP-TERRITORIAL`` / ``-ABOUT`` / ``-EDI`` fire on
  nearly every pre-2019 JD because those sections *did not exist in the template those
  JDs were authored under* — and ``SFU-APPROVE-EDI-FOOTER`` blocks. A blended,
  whole-corpus approval rate would report the archive as catastrophically non-compliant
  when much of it is simply **old**. So every number is reported inside a segment: by
  format (``.doc``/``.docx``), by era (old/transition/new), and by dedup population.
* **No silent drops.** Every one of the 14,565 files is accounted for — as a scored row,
  or as a ledger entry with its reason. The ``.tif``, the ``.serv``, the ``.dot``s and
  any antiword failure are themselves a finding.

The segmentation policy this package reads — era bands, the template token, the dedup
knobs — is **not** here. It is ``jd_core/rules/segmentation.yaml``: an ordinary rule
file (CLAUDE.md §2), registered as HR-109 … HR-118, drift-checked by ``make gates``, and
deliberately excluded from ``rules_version`` because it cannot move a JD's score.
``jd_bank`` reads it through ``jd_core``, which is the direction it already depended in;
there is no config subsystem of its own, and no import edge back into the core.

Public surface::

    from src.jd_bank.baseline import get_baseline_config, run_baseline, summarise

    rows = list(run_baseline(Path("/archive")))
    summary = summarise(rows, archive_root="/archive")

Run it: ``make baseline JD_ARCHIVE_PATH=<archive>`` (see ``__main__.py``).
"""

from src.jd_bank.baseline.aggregate import population, summarise
from src.jd_bank.baseline.config import (
    POPULATIONS,
    ArchiveEra,
    DedupPopulation,
    get_baseline_config,
)
from src.jd_bank.baseline.facets import FileFacets, file_facets
from src.jd_bank.baseline.models import BaselineRow, BaselineSummary, SegmentStats
from src.jd_bank.baseline.runner import evaluate_file, run_baseline, write_artifacts
from src.jd_core.rules import Segmentation

__all__ = [
    "POPULATIONS",
    "ArchiveEra",
    "BaselineRow",
    "BaselineSummary",
    "DedupPopulation",
    "FileFacets",
    "Segmentation",
    "SegmentStats",
    "evaluate_file",
    "file_facets",
    "get_baseline_config",
    "population",
    "run_baseline",
    "summarise",
    "write_artifacts",
]

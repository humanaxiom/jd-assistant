"""HRIS grade import — the authoritative ``position_number -> grade`` source (Phase C).

For the JDFN majority the grade is NOT in the JD document; the authoritative value lives
in the HRIS keyed by position number. This parses an HR-provided export into structured
:class:`~src.jd_core.models.parsed_jd.JobClassification` values (``source="hris"``) that
``scripts/import_grades.py`` applies to canonical roles by ``position_number``.

Only the PURE parse lives here (so it is unit-testable without a DB or a real export);
the CLI wrapper does the DB apply. **This importer is a scaffold: running it for real
needs the HR export AND a FIPPA review** — grade is compensation-adjacent data. See
``docs/decisions/grade-scales.md``.

Expected CSV columns (header row): ``position_number``, ``scheme``, ``grade``.
"""

from __future__ import annotations

import csv
import io

from src.jd_core.models.parsed_jd import JobClassification


def parse_grade_csv(text: str) -> dict[str, JobClassification]:
    """Parse an HRIS grade export into ``position_number -> JobClassification`` (source
    ``hris``). Rows missing a position number or a grade are skipped; a blank ``scheme``
    falls back to ``"unknown"``. Later rows win on a duplicate position number."""
    mapping: dict[str, JobClassification] = {}
    for row in csv.DictReader(io.StringIO(text)):
        position_number = (row.get("position_number") or "").strip()
        grade = (row.get("grade") or "").strip()
        if not position_number or not grade:
            continue
        scheme = (row.get("scheme") or "").strip() or "unknown"
        mapping[position_number] = JobClassification(
            scheme=scheme, value=grade, source="hris"
        )
    return mapping

"""P3b — audit the identification fields against the RAW ARCHIVE.

`title` and `employee_group` are the only two fields ever compared against the source
files, and **each produced defects on first contact** — two and one respectively.
`department`, `grade`, `classification` and `position_number` had never been checked at
all. This package checks the ones read from a LABEL::

    make field-audit JD_ARCHIVE_PATH=<SFU JDs>

It reads the archive and the database and writes neither. See :mod:`.probe` for why
discovery and readability are separate steps, and what the probe cannot see.
"""

from __future__ import annotations

from src.jd_bank.field_audit.probe import (
    FieldHit,
    FieldSpec,
    Readability,
    ValuePlacement,
    probe_field,
)

__all__ = [
    "FieldHit",
    "FieldSpec",
    "Readability",
    "ValuePlacement",
    "probe_field",
]

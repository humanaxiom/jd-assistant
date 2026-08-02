"""Group-aware extraction of a position's pay grade / classification.

The legacy ``SFUJobDescription.grade`` free string was grabbed by a naive "Grade:"
label regex and is noise (see ``docs/audit/data-state-and-grade-2026-08-01.md`` — 3%
populated, mostly adjacent field text). This extracts a STRUCTURED, provenance-carrying
:class:`~src.jd_core.models.parsed_jd.JobClassification`, conservatively:

* **CUPE** JDs print a numeric pay grade in the classification line ("Secretary,
  grade 8") — ~64% recoverable, measured. -> ``scheme="cupe"``.
* **JDFN** (APSA/APEX/POLY) JDs state a grade in the identification block's ``Grade:``
  field, or in the older "Classification & Grade Approved:" field. Both are captured
  ONLY when they hold a plausible grade token; the field is often blank (a grade
  assigned post-authoring lives in the HRIS), and a blank must never be invented.

  The bare ``Grade:`` form is line-anchored *because* the identification block is now
  a real, bounded section: until the docx-header fix
  (:func:`~src.jd_bank.ingest.extract._docx_identification_block`) these documents had
  no identification block at all, ``text`` was the whole document, and an unanchored
  "grade" match there is what produced the 430 garbage ``grade`` strings the audit
  found. Measured after the fix: **876 archive documents state a JDFN grade** in the
  header — the same audit reported it "not extracted anywhere", having looked only at
  body text.

Pure and total — never raises; returns ``None`` when no trustworthy grade is present
(the common case), so a grade the document does not state is never manufactured. Call
with the identification block (not the whole document) to avoid matching a "grade 12
students" in a duty. ``source`` is always ``"parsed"`` (author/HRIS grades enter
elsewhere).
"""

from __future__ import annotations

import re

from src.jd_core.models.parsed_jd import JobClassification, SFUEmployeeGroup

#: A numeric CUPE pay grade: "grade 8", "Gr. 6", "GRADE 10".
_CUPE_GRADE_RX = re.compile(r"\b(?:gr\.?|grade)\s*[:#]?\s*(\d{1,2})\b", re.IGNORECASE)

#: A JDFN "Classification & Grade Approved:" value that is ACTUALLY a grade — a 1–2
#: digit number, optionally "PG"-prefixed — not another field label and not blank.
_JDFN_GRADE_APPROVED_RX = re.compile(
    r"grade\s+approved\s*[:#]?\s*((?:PG\s*)?\d{1,2})\b", re.IGNORECASE
)

#: The modern template's identification-block ``Grade:`` field. Line-anchored (see the
#: module docstring): the whole point is that it is a labelled FIELD, not the word
#: "grade" appearing somewhere in prose.
_JDFN_GRADE_FIELD_RX = re.compile(
    r"(?im)^[ \t]*(?:pay )?grade[ \t]*[:#][ \t]*((?:PG[ \t]*)?\d{1,2})\b"
)

_JDFN_SCHEMES = frozenset({"apsa", "apex", "poly"})


def extract_classification(
    text: str, employee_group: SFUEmployeeGroup | None
) -> JobClassification | None:
    """Best-effort structured grade for a JD, or ``None`` when none is trustworthy."""
    if not text:
        return None
    if employee_group == "cupe":
        match = _CUPE_GRADE_RX.search(text)
        if match is not None:
            return JobClassification(
                scheme="cupe", value=match.group(1), source="parsed"
            )
        return None
    # JDFN / unknown group: only an explicit, filled grade FIELD.
    match = _JDFN_GRADE_APPROVED_RX.search(text) or _JDFN_GRADE_FIELD_RX.search(text)
    if match is not None:
        scheme = employee_group if employee_group in _JDFN_SCHEMES else "unknown"
        return JobClassification(
            scheme=scheme, value=match.group(1).strip(), source="parsed"
        )
    return None

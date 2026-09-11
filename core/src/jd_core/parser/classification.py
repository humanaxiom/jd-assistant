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

🔴 **THE MATCHERS ARE RULEBOOK DATA, NOT CONSTANTS (Track P, P3f).** They were three
module-level ``re.compile`` calls, which is the gap FINDINGS §9e names outright: "those
regexes being hardcoded is itself a rulebook-as-data gap". They now sit in
``rules/classification.yaml``, registered as HR-233 … HR-236 (all ``open``) and
drift-checked, so retuning one breaks the build until the register is updated.

⚠ **No value changed in the move** — measured over 78,384 comparisons against real Bank
text with 0 mismatches — so the parse is byte-identical, ``PARSER_VERSION`` did not bump
and no re-parse was owed. Two of the matchers are known loose (HR-233 accepts the bare
token ``GR8`` as grade 8) and that is now an HR question on the register rather than a
constant nobody could see.

⚠ **What P3f did NOT fix:** the field audit reads LABELS, and a grade pulled by a
matcher is still not a labelled field, so ``classification`` stays invisible to it.
Registering the matchers made them reviewable, not auditable — §9e's first sentence
stands.

Pure and total — never raises; returns ``None`` when no trustworthy grade is present
(the common case), so a grade the document does not state is never manufactured. Call
with the identification block (not the whole document) to avoid matching a "grade 12
students" in a duty. ``source`` is always ``"parsed"`` (author/HRIS grades enter
elsewhere).
"""

from __future__ import annotations

from src.jd_core.models.parsed_jd import JobClassification, SFUEmployeeGroup
from src.jd_core.rules import Classification, get_rules


def extract_classification(
    text: str,
    employee_group: SFUEmployeeGroup | None,
    rules: Classification | None = None,
) -> JobClassification | None:
    """Best-effort structured grade for a JD, or ``None`` when none is trustworthy.

    ``rules`` defaults to the loaded rulebook. It is injectable for the same reason
    :func:`~src.jd_core.parser.wjq.segment_wjq` takes its ``Wjq`` block: the suite shows
    this reads the YAML by re-loading it retuned and watching the behaviour follow — a
    module holding a constant would fail that.
    """
    if not text:
        return None
    rules = rules if rules is not None else get_rules().classification
    if employee_group == "cupe":
        match = rules.cupe_grade_pattern.search(text)
        if match is not None:
            return JobClassification(
                scheme="cupe", value=match.group(1), source="parsed"
            )
        return None
    # JDFN / unknown group: only an explicit, filled grade FIELD.
    match = rules.jdfn_grade_approved_pattern.search(
        text
    ) or rules.jdfn_grade_field_pattern.search(text)
    if match is not None:
        scheme = (
            employee_group
            if employee_group is not None and employee_group in rules.jdfn_schemes
            else "unknown"
        )
        return JobClassification(
            scheme=scheme, value=match.group(1).strip(), source="parsed"
        )
    return None

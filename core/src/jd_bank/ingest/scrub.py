"""Incumbent-name normalization — the rulebook "job, not person" quality step.

SFU JDs describe the *role*, not the person filling it (plan §0). Legacy
templates nonetheless carry an incumbent field (``NAME OF EMPLOYEE:`` /
``INCUMBENT:``) and the odd contact detail; the census found a name-bearing
field in ~56% of sampled documents, concentrated in the OLD/TRANSITION bands.
This module strips those values so no incumbent identity flows into parsing,
embedding, or retrieval. **This is a quality normalization, not a privacy gate**
— JDs are not résumés (plan §1, build-new gap #3).

The name/email/phone matching primitives are ported from hris
``services/redaction.py`` (reuse map #25). What is dropped: the résumé-specific
machinery — the known-candidate-name matcher, the employer/school label map, and
the entire foreign-location scrub (ADR 0028) — none of which applies to a JD.
What is kept and adapted: the email regex, the conservative ">=10 digit" phone
matcher, and — new here, because a JD's incumbent name is not known a priori
(unlike a résumé's) — a *field-label* matcher that redacts the value of the
incumbent field rather than a supplied name.

The returned :class:`ScrubReport` records only counts and kinds — never the
removed values — so it is safe to persist in ``source_documents`` and to log.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

# ── Ported primitives (hris services/redaction.py) ──────────────────────────
_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")

# Phone candidate: a run of digits + common separators. Only a candidate with
# >= 10 digits is redacted, so year ranges ("2002-2007", 8 digits) and single
# years survive while real phone numbers do not.
_PHONE_CAND_RE = re.compile(r"(?<!\w)\+?\d[\d().\-\s]{6,}\d(?!\w)")
_MIN_PHONE_DIGITS = 10

# ── JD-specific: incumbent field-label matcher (new) ─────────────────────────
# Matches an incumbent field label at line start and captures its value to the
# end of the line. Labels observed in the census: "NAME OF EMPLOYEE:" (OLD-era
# .doc) and "INCUMBENT:" (1982 variant), plus close spellings.
_INCUMBENT_LABEL = (
    r"name of employee|name of incumbent|employee name|incumbent name|incumbent"
)
_INCUMBENT_FIELD_RE = re.compile(
    rf"(?im)^([ \t]*(?:{_INCUMBENT_LABEL})[ \t]*:[ \t]*)(.*)$"
)
# Values that are not a real name — a blank/placeholder field is left as-is and
# not counted as a removed name.
_PLACEHOLDER_VALUES = {"", "n/a", "na", "none", "vacant", "tba", "tbd", "-", "--"}

_NAME_MASK = "[name redacted]"
_CONTACT_MASK = "[contact redacted]"


@dataclass(frozen=True)
class ScrubReport:
    """Counts of what the normalizer removed, by kind. Contains **no PII** — only
    tallies — so it is safe to store in ``normalization_report`` and to log."""

    names_removed: int = 0
    emails_removed: int = 0
    phones_removed: int = 0

    @property
    def total_removed(self) -> int:
        return self.names_removed + self.emails_removed + self.phones_removed

    @property
    def changed(self) -> bool:
        return self.total_removed > 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "names_removed": self.names_removed,
            "emails_removed": self.emails_removed,
            "phones_removed": self.phones_removed,
            "total_removed": self.total_removed,
        }


def _scrub_incumbent_fields(text: str) -> tuple[str, int]:
    count = 0

    def _repl(m: re.Match[str]) -> str:
        nonlocal count
        label, value = m.group(1), m.group(2)
        if value.strip().casefold() in _PLACEHOLDER_VALUES:
            return m.group(0)
        count += 1
        return f"{label}{_NAME_MASK}"

    return _INCUMBENT_FIELD_RE.sub(_repl, text), count


def _scrub_phones(text: str) -> tuple[str, int]:
    count = 0

    def _repl(m: re.Match[str]) -> str:
        nonlocal count
        if sum(c.isdigit() for c in m.group(0)) >= _MIN_PHONE_DIGITS:
            count += 1
            return _CONTACT_MASK
        return m.group(0)

    return _PHONE_CAND_RE.sub(_repl, text), count


def normalize_incumbent_names(text: str) -> tuple[str, ScrubReport]:
    """Strip incumbent identity from ``text`` and report what was removed.

    Removes, in order: incumbent field values (``NAME OF EMPLOYEE:`` /
    ``INCUMBENT:`` -> ``[name redacted]``), email addresses, and phone-shaped
    runs (>= 10 digits) -> ``[contact redacted]``. Ordinary prose is untouched.
    Safe on empty input. Returns the cleaned text and a PII-free
    :class:`ScrubReport`.
    """
    if not text:
        return text, ScrubReport()

    out, names = _scrub_incumbent_fields(text)

    emails = len(_EMAIL_RE.findall(out))
    out = _EMAIL_RE.sub(_CONTACT_MASK, out)

    out, phones = _scrub_phones(out)

    return out, ScrubReport(
        names_removed=names, emails_removed=emails, phones_removed=phones
    )

"""Section-heading patterns for the deterministic JD segmenter — encoded as
*versioned data*, not hardcoded in the segmentation logic.

Two SFU template eras are covered (derived from ``docs/rulebook/
sfu-jd-standards.txt`` — Part 2 = the NEW template structure/order, Part 8 =
the OLD-template transposition conventions):

* **NEW** — the current APSA/APEX/Poly template: an ``ABOUT SIMON FRASER
  UNIVERSITY`` banner, un-lettered section names in the Part-2 order, an
  ``IMPACT OF DECISION MAKING`` label, and a mandatory territorial-
  acknowledgement + Employment-Equity footer.
* **OLD** — the legacy templates: lettered section headings
  (``A. IDENTIFICATION`` / ``B. POSITION SUMMARY`` / ``C. DUTIES …``), a
  ``POSITION DESCRIPTION`` banner, a ``NAME OF EMPLOYEE:`` / ``INCUMBENT:``
  incumbent marker, and side-margin labels (``TYPICAL DUTIES``, ``SUMMARY OF
  RESPONSIBILITY``, ``SUPERVISION RECEIVED/EXERCISED``, ``MINIMUM ENTRANCE
  QUALIFICATIONS``).

The file itself is *not* needed at runtime — the derived patterns live here as
data so the parser runs inside the gates container (which does not mount the
rulebook). Each pattern is tagged with the era it signals; ``"any"`` patterns
are shared. Matching is deterministic: a line is normalised (letter prefix and
trailing colon stripped, whitespace collapsed) and ``fullmatch``-ed against the
patterns in :data:`SECTION_ORDER` priority so a content line can never be
mistaken for a heading.
"""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Literal

# Detected document era (segmenter output). ``"any"`` is a *pattern* tag only.
Era = Literal["old", "new", "unknown"]
HeadingEra = Literal["old", "new", "any"]


class SectionKey(StrEnum):
    """The ten canonical SFU JD sections (Part 2 order), used as the internal
    segmentation keys and the per-section confidence keys."""

    IDENTIFICATION = "identification"
    ABOUT_SFU = "about_sfu"
    POSITION_SUMMARY = "position_summary"
    DUTIES = "duties"
    DECISION_MAKING = "decision_making"
    PROBLEM_SOLVING = "problem_solving"
    RELATIONSHIPS = "relationships"
    QUALIFICATIONS = "qualifications"
    FOOTER = "footer"
    ADDITIONAL_CONTEXT = "additional_context"


# Priority order for heading matching (also the confidence-report key order).
SECTION_ORDER: tuple[SectionKey, ...] = (
    SectionKey.IDENTIFICATION,
    SectionKey.ABOUT_SFU,
    SectionKey.POSITION_SUMMARY,
    SectionKey.DUTIES,
    SectionKey.DECISION_MAKING,
    SectionKey.PROBLEM_SOLVING,
    SectionKey.RELATIONSHIPS,
    SectionKey.QUALIFICATIONS,
    SectionKey.FOOTER,
    SectionKey.ADDITIONAL_CONTEXT,
)

# ── Heading patterns (versioned data) ───────────────────────────────────────
# (era, regex) pairs per section. Regexes are matched with ``fullmatch`` against
# a normalised, upper/lower-insensitive heading line. Most-specific first.
HEADING_PATTERNS: dict[SectionKey, list[tuple[HeadingEra, str]]] = {
    SectionKey.IDENTIFICATION: [
        ("any", r"IDENTIFICATION(?: SECTION)?"),
        ("any", r"POSITION IDENTIFICATION"),
    ],
    SectionKey.ABOUT_SFU: [
        ("new", r"ABOUT SIMON FRASER UNIVERSITY"),
        ("new", r"ABOUT SFU"),
    ],
    SectionKey.POSITION_SUMMARY: [
        ("any", r"POSITION SUMMARY"),
        ("old", r"SUMMARY OF RESPONSIBILITY(?: LEVEL)?"),
        ("any", r"JOB SUMMARY"),
        ("any", r"SUMMARY"),
    ],
    SectionKey.DUTIES: [
        ("any", r"DUTIES(?: AND| &)? RESPONSIBILITIES"),
        ("old", r"TYPICAL DUTIES"),
        ("any", r"KEY DUTIES"),
        ("any", r"PRIMARY FUNCTIONS"),
        ("any", r"DUTIES"),
    ],
    SectionKey.DECISION_MAKING: [
        ("new", r"IMPACT OF DECISION[ -]?MAKING"),
        ("any", r"DECISION[ -]?MAKING"),
    ],
    SectionKey.PROBLEM_SOLVING: [
        ("any", r"PROBLEM[ -]?SOLVING(?: AND LEVEL OF SUPERVISION)?"),
    ],
    SectionKey.RELATIONSHIPS: [
        ("any", r"RELATIONSHIPS"),
        ("any", r"PRIMARY WORKING RELATIONSHIPS"),
        ("old", r"SUPERVISION RECEIVED"),
        ("old", r"SUPERVISION EXERCISED"),
        ("any", r"CONTACTS"),
    ],
    SectionKey.QUALIFICATIONS: [
        ("old", r"MINIMUM ENTRANCE QUALIFICATIONS"),
        ("any", r"MINIMUM QUALIFICATIONS"),
        ("any", r"QUALIFICATIONS"),
        ("any", r"EDUCATION AND EXPERIENCE"),
    ],
    SectionKey.FOOTER: [
        ("new", r"TERRITORIAL ACKNOWLEDGE?MENT(?: AND EDI COMMITMENT)?"),
        ("new", r"EDI COMMITMENT"),
        ("new", r"EMPLOYMENT EQUITY"),
    ],
    SectionKey.ADDITIONAL_CONTEXT: [
        ("any", r"ADDITIONAL CONTEXT(?:UAL INFORMATION)?"),
        ("any", r"ADDITIONAL INFORMATION"),
    ],
}

# Flattened, compiled, in SECTION_ORDER priority — the matcher iterates this.
_COMPILED: list[tuple[SectionKey, HeadingEra, re.Pattern[str]]] = [
    (section, era, re.compile(pat, re.IGNORECASE))
    for section in SECTION_ORDER
    for era, pat in HEADING_PATTERNS[section]
]

# Leading enumeration prefix on a heading line: ``A.`` / ``B)`` / ``1.`` etc.
_LETTER_PREFIX = re.compile(r"^\s*(?:[A-Za-z]|\d{1,2})[.)]\s+")
_LETTERED_HEADING = re.compile(r"^\s*[A-J][.)]\s+[A-Z]")


def normalise_heading(line: str) -> str:
    """Normalise a raw line for heading matching: drop a leading ``A.`` / ``1)``
    enumeration prefix, drop a trailing colon, and collapse internal whitespace.
    Returns ``""`` for a blank line."""
    text = line.strip()
    if not text:
        return ""
    text = _LETTER_PREFIX.sub("", text, count=1)
    text = text.rstrip(":").strip()
    return re.sub(r"\s+", " ", text)


def match_heading(line: str) -> tuple[SectionKey, HeadingEra] | None:
    """Return the ``(section, era)`` a line is a heading for, or ``None``.

    Uses ``fullmatch`` on the normalised line so ordinary content (e.g.
    ``"Responsible for solving problems related to:"``) is never taken for a
    heading. First match in :data:`SECTION_ORDER` priority wins."""
    norm = normalise_heading(line)
    if not norm:
        return None
    for section, era, rx in _COMPILED:
        if rx.fullmatch(norm):
            return section, era
    return None


def is_lettered_heading(line: str) -> bool:
    """True if the raw line is an OLD-era lettered heading (``A. IDENTIFICATION``)."""
    return bool(_LETTERED_HEADING.match(line))


# ── Era-detection signals (searched, not fullmatched) ───────────────────────
OLD_ERA_SIGNALS: tuple[str, ...] = (
    r"POSITION DESCRIPTION",
    r"NAME OF EMPLOYEE",
    r"\bINCUMBENT\b",
    r"ADMINISTRATIVE AND PROFESSIONAL STAFF POSITIONS",
    r"MINIMUM ENTRANCE QUALIFICATIONS",
    r"TYPICAL DUTIES",
    r"SUPERVISION (?:RECEIVED|EXERCISED)",
    r"SUMMARY OF RESPONSIBILITY",
)
NEW_ERA_SIGNALS: tuple[str, ...] = (
    r"ABOUT SIMON FRASER UNIVERSITY",
    r"IMPACT OF DECISION MAKING",
    r"PROBLEM SOLVING AND LEVEL OF SUPERVISION",
    r"committed to the principle of Employment Equity",
    r"respectfully acknowledges",
    r"unceded traditional territor",
    r"Initial Effective Date",
    r"Last Revised Date",
)
_OLD_SIGNAL_RX = [re.compile(p, re.IGNORECASE) for p in OLD_ERA_SIGNALS]
_NEW_SIGNAL_RX = [re.compile(p, re.IGNORECASE) for p in NEW_ERA_SIGNALS]


def era_signal_scores(text: str, lettered_headings: int) -> tuple[int, int]:
    """Return ``(old_score, new_score)`` — counts of era signals present. Three
    or more lettered headings add a strong OLD vote."""
    old = sum(1 for rx in _OLD_SIGNAL_RX if rx.search(text))
    new = sum(1 for rx in _NEW_SIGNAL_RX if rx.search(text))
    if lettered_headings >= 3:
        old += 2
    return old, new


# ── Presence-boolean signals (footer + About SFU) ───────────────────────────
_ABOUT_SFU_RX = re.compile(
    r"about simon fraser university|canada'?s engaged university", re.IGNORECASE
)
_TERRITORIAL_RX = re.compile(
    r"respectfully acknowledges|unceded traditional territor|territorial acknowledge",
    re.IGNORECASE,
)
_EQUITY_RX = re.compile(r"employment equity", re.IGNORECASE)


def has_about_sfu(text: str) -> bool:
    return bool(_ABOUT_SFU_RX.search(text))


def has_territorial_acknowledgement(text: str) -> bool:
    return bool(_TERRITORIAL_RX.search(text))


def has_employment_equity(text: str) -> bool:
    return bool(_EQUITY_RX.search(text))


# ── Identification field labels ─────────────────────────────────────────────
# Each label maps to a search regex capturing everything to end-of-line; the
# value is later cut at the next inline label by ``NEXT_LABEL_RX``.
TITLE_LABEL_RX = re.compile(
    r"(?im)^[ \t]*(?:position title|job title|title)[ \t]*:[ \t]*(.+)$"
)
DEPARTMENT_LABEL_RX = re.compile(
    r"(?im)^[ \t]*department(?:/unit| ?/ ?unit|/? ?unit)?[ \t]*:[ \t]*(.+)$"
)
POSITION_NO_LABEL_RX = re.compile(
    r"(?im)^[ \t]*position[ \t]*(?:#|no\.?|number)[ \t]*:?[ \t]*([A-Za-z0-9\-]+)"
)
GRADE_LABEL_RX = re.compile(r"(?im)^[ \t]*(?:pay )?grade[ \t]*:[ \t]*(.+)$")
EMPLOYEE_GROUP_LABEL_RX = re.compile(r"(?im)^[ \t]*employee group[ \t]*:[ \t]*(.+)$")

# Cut a captured field value at the next inline label (legacy rows pack several
# fields on one physical line, e.g. ``JOB TITLE: X INCUMBENT:``).
NEXT_LABEL_RX = re.compile(
    r"\b(?:incumbent|name of employee|employee name|date|position\s*(?:#|no\.?|number)"
    r"|department|employee group|effective date|last revised|revised date"
    r"|supervisor'?s? title|grade)\b\s*:?",
    re.IGNORECASE,
)

EMPLOYEE_GROUP_TOKENS: tuple[str, ...] = ("apsa", "apex", "poly", "cupe", "excluded")

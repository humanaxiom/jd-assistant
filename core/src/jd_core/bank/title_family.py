"""Classify a role title on SFU's two title dimensions (pure, deterministic).

Ported from hris ``packages/pipeline/src/pipeline/bank/title_family.py``
(reuse-map #12, ADR-005). A title carries two independent signals, and this
module reads both:

* **Seniority** — the family ladder (vp → assistant). *Not* SFU-published: hris
  cited it to the Job Titling Guide (Toolkit p18-19) and the claim does not
  survive checking against ``docs/rulebook/sfu-jd-standards.txt``. Inherited
  calibration, registered `open` as **HR-059**. Advisory.
* **Function** — SFU's Job-Title Application Table (rulebook Part 3.3): what the
  title *word* means. "Data Analyst" is family ``unmapped`` but function
  ``analyst``.

Both are advisory title anchors that help the Bank standardize titling and compare
like roles. They pair with the Hay-factor signals; neither assigns a grade.

**The tables are data, and so is their order.** hris hardcoded four Python tables
and — silently — the sequence they are tried in. That sequence is policy: first
match wins, so trying ``manager`` before ``director`` is the whole reason
"Associate Director" is a manager and not a director, and trying ``executive``
first is the whole reason "Executive Director" is an executive. Ladder, keywords,
match order and the comma-supervisory set now live in ``rules/titles.yaml``
(CLAUDE.md §2) and this module only *executes* them.

The supervisory signal sharpens the family rationale; it never overrides the title.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import TypeVar

from src.jd_core.models.bank import (
    TitleClassification,
    TitleFamilyResult,
    TitleFunctionResult,
)
from src.jd_core.rules import UNMAPPED, Rules, Titles, get_rules

_NON_ALPHANUMERIC = re.compile(r"[^a-z0-9]+")

#: A title vocabulary member — ``TitleFamily`` or ``TitleFunction``. Generic so the
#: matcher below is shared by both dimensions without widening either to ``str``
#: (hris needed two ``# type: ignore[arg-type]`` here; this is why it does not).
_Name = TypeVar("_Name", bound=str)


def _titles(rules: Rules | None) -> Titles:
    return (rules if rules is not None else get_rules()).titles


def _normalize(title: str) -> str:
    """A title reduced to lower-case tokens, space-padded at both ends.

    The padding is what lets a keyword match a *whole token*: ``" vp "`` hits
    "VP Finance" but not "Development", and the keyword table space-pads exactly
    the short abbreviations that need it (see ``titles.yaml``).
    """
    return " " + _NON_ALPHANUMERIC.sub(" ", title.lower()).strip() + " "


def _first_match(
    norm: str,
    match_order: Sequence[_Name],
    keywords: Mapping[_Name, tuple[str, ...]],
) -> tuple[_Name, str] | None:
    """The first ``(name, keyword)`` in ``match_order`` whose keyword is in ``norm``.

    First match wins, and ``match_order`` — not the vocabulary order — decides
    which. It is loaded from the rulebook, so the tie-breaks are configuration.
    The loader guarantees ``keywords`` has an entry for every name in
    ``match_order``, so the lookup cannot ``KeyError``.
    """
    for name in match_order:
        for keyword in keywords[name]:
            if keyword in norm:
                return name, keyword.strip()
    return None


def classify_title_family(
    title: str,
    *,
    has_supervisory: bool = False,
    rules: Rules | None = None,
) -> TitleFamilyResult:
    """Classify ``title`` onto the seniority ladder (advisory, HR-059).

    ``has_supervisory`` (does the role supervise staff?) sharpens the rationale for
    the manager/lead boundary but **never** overrides the title keyword — the title
    is the evidence; supervision is only a gloss on it.
    """
    titles = _titles(rules)
    hit = _first_match(
        _normalize(title), titles.family_match_order, titles.family_keywords
    )
    if hit is None:
        return TitleFamilyResult(
            family=UNMAPPED,
            label=titles.family_labels[UNMAPPED],
            rationale="Title does not match any SFU title family; classify manually.",
            matched_on=None,
        )
    family, keyword = hit
    label = titles.family_labels[family]
    supervises = " (supervises staff)" if has_supervisory else ""
    return TitleFamilyResult(
        family=family,
        label=label,
        rationale=f'Title matches the "{label}" family{supervises}.',
        matched_on=keyword,
    )


def classify_title_function(
    title: str, *, rules: Rules | None = None
) -> TitleFunctionResult:
    """Classify ``title`` onto SFU's functional Application Table (Part 3.3).

    Independent of the seniority family: "Data Analyst" is family ``unmapped`` but
    function ``analyst``. Unmatched -> ``unmapped``.
    """
    titles = _titles(rules)
    hit = _first_match(
        _normalize(title), titles.function_match_order, titles.function_keywords
    )
    if hit is None:
        return TitleFunctionResult(
            function=UNMAPPED,
            label=titles.function_labels[UNMAPPED],
            matched_on=None,
        )
    function, keyword = hit
    return TitleFunctionResult(
        function=function,
        label=titles.function_labels[function],
        matched_on=keyword,
    )


def title_comma_supervisory(title: str, *, rules: Rules | None = None) -> bool:
    """Does the title's *format* signal supervision? (SFU title-format rule, Part 3.4)

    A supervisory title leads with the role word and a comma ("Manager, Laboratory
    Operations"); a non-supervisory one trails it ("Laboratory Operations Manager").
    True when the text *before the first comma* is itself a supervisory-capable
    family — reusing the ladder is what stops a non-role prefix ("Software
    Developer, Platform") false-positiving. Which families count is
    ``titles.comma_supervisory_families``, not a set literal in this function.
    """
    titles = _titles(rules)
    head, separator, _ = title.partition(",")
    if not separator:
        return False
    family = classify_title_family(head, rules=rules).family
    return family in titles.comma_supervisory_families


def classify_title(
    title: str,
    *,
    has_supervisory: bool = False,
    rules: Rules | None = None,
) -> TitleClassification:
    """Both dimensions plus the comma-format signal, in one advisory result.

    ``has_supervisory`` is what the *caller* knows from outside the title — hris
    read it from the role's Relationships section. The title's own comma format is
    a **second, independent** supervision signal, and hris ORs the two before
    classifying (``jd_bank_service.py``::

        family = classify_title_family(
            role.title, has_supervisory=rel_supervisory or comma_supervisory
        )

    ). So "Manager, Laboratory Operations" earns the "(supervises staff)" rationale
    from its format alone, even when the caller knows nothing about the role's
    reports. That OR is pure and derivable from the title, so it belongs here; only
    the Relationships half is the caller's to supply. Advisory copy either way — it
    sharpens the rationale and never changes the family.
    """
    comma_supervisory = title_comma_supervisory(title, rules=rules)
    return TitleClassification(
        family=classify_title_family(
            title,
            has_supervisory=has_supervisory or comma_supervisory,
            rules=rules,
        ),
        function=classify_title_function(title, rules=rules),
        comma_supervisory=comma_supervisory,
    )

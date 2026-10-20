"""ONE check of a CUPE draft's stored form block against HR's closed lists (Track J2).

The CUPE form block (``SFUJobDescription.wjq_form``) holds values HR's form offers as
FIXED choices — level letters, (D)/(W)/(M)/(S) codes, duration / frequency scales —
plus counts with a limit. Review M1 (2026-10-19) found those lists enforced only by the
Builder's assembler: a reviewer edit, through the structured form or the JSON API,
could store ``level_of_independence=['Z', '<script>…']``, a row with frequency
'Annual' and duration 'forever', or twenty minor functions. The export then printed
them on HR's form, and cloning the role raised an unhandled ValidationError.

So the check is HERE, over the stored block, and every door calls it:

* the Builder's assembler (``composer/wjq_assemble.py``), after building the draft;
* the review edit (``review/service.edit`` — the structured page AND the JSON API go
  through it), BEFORE anything is read from or written to the Bank;
* the clone transform, so bad stored data is refused with a message, not a 500.

Every list is rulebook data (``cupe_form.yaml``) and every refusal names its register
entry. A JD with NO block — every JDFN JD, every role parsed from the archive, every
pre-J2 draft — is not checked: it carries none of these choices.
"""

from __future__ import annotations

from collections.abc import Sequence

from src.jd_core.models.parsed_jd import SFUDuty, SFUJobDescription, WJQRow
from src.jd_core.rules import CupeForm, Rules

__all__ = ["CupeFormError", "check_cupe_form", "check_function_counts"]

#: The checkbox sections and the human name each refusal uses.
_LEVEL_SECTIONS: dict[str, str] = {
    "level_of_independence": "5 · Level of Independence",
    "training_exercised": "6 · Training Exercised",
    "direction_exercised": "7 · Direction Exercised",
    "continuing_education": "12 · Continuing Education",
}


class CupeFormError(ValueError):
    """A CUPE form block holds a value outside HR's lists. A ``ValueError``, so every
    Builder handler already renders it as the page's error; the review routes map it
    to their own refusal (422 / the detail page with the message)."""


def check_function_counts(majors: int, minors: int, form: CupeForm) -> list[str]:
    """HR-246: the function limits, as messages (empty = within them)."""
    problems: list[str] = []
    for name, count, key in (
        ("3 · Major Functions", majors, "major_functions"),
        ("4 · Minor Functions", minors, "minor_functions"),
    ):
        limit = form.function_limits[key]  # type: ignore[index]
        if count > limit:
            problems.append(
                f"{name} lists {count} functions; the form takes at most {limit} "
                "(cupe_form.function_limits, HR-246). Nothing was removed — combine "
                f"or delete {count - limit} of them"
            )
    return problems


def _scale(
    value: str | None, allowed: Sequence[str], what: str, entry: str
) -> list[str]:
    if value is None or value in allowed:
        return []
    return [f"{what} {value!r} is not on HR's scale ({', '.join(allowed)}; {entry})"]


def _frequencies(duties: Sequence[SFUDuty], form: CupeForm, where: str) -> list[str]:
    return [
        problem
        for duty in duties
        for problem in _scale(
            duty.frequency,
            form.function_frequencies,
            f"{where} frequency",
            "cupe_form.function_frequencies, HR-247",
        )
    ]


def _rows(rows: Sequence[WJQRow], form: CupeForm, where: str) -> list[str]:
    out: list[str] = []
    for row in rows:
        out += _scale(
            row.duration,
            form.table_durations,
            f"{where} duration",
            "cupe_form.table_durations, HR-248",
        )
        out += _scale(
            row.frequency,
            form.table_frequencies,
            f"{where} frequency",
            "cupe_form.table_frequencies, HR-249",
        )
    return out


def check_cupe_form(jd: SFUJobDescription, rules: Rules) -> None:
    """Refuse a CUPE form block holding anything outside HR's lists, with EVERY
    problem and its register id in one message. No block -> nothing to check."""
    extra = jd.wjq_form
    if extra is None:
        return
    form = rules.cupe_form
    problems = check_function_counts(len(jd.duties), len(extra.minor_functions), form)
    problems += _frequencies(jd.duties, form, "a major function's")
    problems += _frequencies(extra.minor_functions, form, "a minor function's")
    for section, name in _LEVEL_SECTIONS.items():
        letters = list(getattr(extra, section))
        known = form.level_letters(section)  # type: ignore[arg-type]
        unknown = [x for x in letters if x not in known]
        if unknown:
            problems.append(
                f"{name} has no level {unknown[0][:20]!r} on HR's form (levels "
                f"{', '.join(known)}; cupe_form.checkbox_options, HR-238)"
            )
        if section in form.single_choice_sections and len(set(letters)) > 1:
            problems.append(
                f'{name}: HR\'s form takes one level only ("Check one box"); '
                f"{len(set(letters))} were ticked (HR-238)"
            )
    problems += _rows(extra.contacts, form, "a contact's")
    problems += _rows(extra.effort, form, "an effort row's")
    problems += _rows(extra.locations, form, "a location row's")
    problems += _rows(extra.uncomfortable, form, "an uncomfortable-conditions row's")
    problems += _rows(extra.hazards, form, "a hazard row's")
    if (
        extra.equivalency_acceptable is False
        and not (extra.equivalency_rationale or "").strip()
        and form.equivalency_rationale_required
    ):
        problems.append(
            "the equivalency is marked NOT acceptable, so HR's form needs the reason "
            '("…is not acceptable because: (please explain)"; HR-252)'
        )
    if problems:
        raise CupeFormError("CUPE form: " + "; ".join(problems) + ".")

"""Read the positions (and dates, group, title) an archive FILENAME names.

Archive names are ``<PeopleSoft as-of date YYYYMMDD>_<user file name>``, and the user
file name often LEADS with the positions it covers — frequently unpadded::

    20200601_61,_30785,_208,_975_JDFN_APSA_20211117.docx
      -> 00000061, 00030785, 00000208, 00000975

This is a SEPARATE reader from ``segmentation.position_id_pattern`` (the padded form
the archive baseline and near-dedup read, HR-114). It is a superset of that pattern —
every padded id is still read — plus three more tiers, each a knob in
``segmentation.yaml: filename_positions`` (HR-325 … HR-331):

* ``leading`` — the run of numbers right after the leading date (HR-325);
* ``labelled`` — ``Pos.__1433`` / ``Pos106294`` / ``pos_0436`` anywhere (HR-326);
* ``padded`` — a zero-padded id the other two did not reach.

A number is never read from anywhere else, so a grade (``gr_6``, ``Gr._7``,
``grade_5``) cannot become a position. Short or oddly padded tokens need a second
witness — the same id zero-padded in some filename (``vouched``, HR-328).

**Total by construction**: it runs over every filename in the Bank, so it returns empty
facts rather than raising, whatever the name.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from typing import Literal

from src.jd_core.rules import Segmentation

__all__ = [
    "FilenameFacets",
    "PositionRef",
    "PositionSource",
    "normalise_position_id",
    "read_filename",
]

PositionSource = Literal["leading", "labelled", "padded"]

#: Every run of digits inside a matched list.
_DIGITS = re.compile(r"\d+")
#: A trailing file extension, possibly repeated (``….doc.doc``). Presentation only: it
#: is stripped for the title slug and nowhere else.
_EXTENSION = re.compile(r"(?:\.[A-Za-z0-9]{1,5})+$")
#: A trailing ``JDFN_<GROUP>[_<date>]`` block, stripped for the title slug only.
_JDFN_TAIL = re.compile(r"_*JDFN(?:_[A-Za-z]+)?(?:_\d*)?$")


@dataclass(frozen=True)
class PositionRef:
    """One position a filename names."""

    #: The PeopleSoft id, zero-padded to 8 digits.
    id8: str
    #: The token as written in the filename (``61``, ``000101719``).
    raw: str
    source: PositionSource
    #: True when this id is written zero-padded here or in some filename in the Bank.
    vouched: bool


@dataclass(frozen=True)
class FilenameFacets:
    """What one filename says, read off the name alone (no I/O)."""

    #: The leading PeopleSoft as-of date, or ``None`` if the name has none / it is not
    #: a real date.
    as_of_date: dt.date | None
    #: Distinct, in the order they first appear in the name.
    positions: tuple[PositionRef, ...]
    #: The ``JDFN_<GROUP>`` token, exactly as written (typos included, HR-118).
    employee_group: str | None
    #: The ``JDFN_<GROUP>_<YYYYMMDD>`` date.
    jd_date: dt.date | None
    #: What is left once the date, position list and JDFN block are removed.
    title_slug: str | None

    @property
    def position_ids(self) -> tuple[str, ...]:
        return tuple(p.id8 for p in self.positions)


def normalise_position_id(raw: str, *, max_position_id: int) -> str | None:
    """A digit token -> its zero-padded 8-digit id, or ``None`` if it cannot be one.

    Zero and anything above ``max_position_id`` (HR-327) are refused.
    """
    if not raw.isascii() or not raw.isdigit():
        return None
    value = int(raw)
    if value == 0 or value > max_position_id:
        return None
    return f"{value:08d}"


def _date(match: re.Match[str] | None) -> dt.date | None:
    if match is None:
        return None
    try:
        year, month, day = (int(g) for g in match.groups()[:3])
        return dt.date(year, month, day)
    except (TypeError, ValueError):
        return None


def read_filename(
    name: str, cfg: Segmentation, vouched: frozenset[str]
) -> FilenameFacets:
    """Every fact the filename ``name`` states. Pure; never raises.

    ``vouched`` is the set of ids that appear zero-padded in ANY filename in the Bank
    (:class:`~src.jd_bank.positions.index.PositionIndex` builds it); a token the
    corroboration gate holds back is kept only if its id is in it.
    """
    fp = cfg.filename_positions
    gate = fp.corroboration
    found: dict[str, PositionRef] = {}

    def keep(raw: str, source: PositionSource) -> None:
        id8: str | None
        if len(raw) == 8 and raw.startswith("0"):
            # Already the padded form: kept exactly as `position_id_pattern` keeps it
            # (no ceiling, no gate), so this reader stays a superset of it.
            if raw == "00000000":
                return
            id8 = raw
        else:
            if len(raw) == 8 and cfg.file_date_pattern.match(raw):
                return  # a second date (`20110525_20070810_…`), never a position
            id8 = normalise_position_id(raw, max_position_id=fp.max_position_id)
            if id8 is None:
                return
            significant = raw.lstrip("0")
            needs_witness = len(significant) < gate["unvouched_min_digits"] or (
                gate["seven_digit_00_requires_corroboration"]
                and len(raw) == 7
                and raw.startswith("00")
            )
            if needs_witness and id8 not in vouched:
                return
        if id8 not in found:
            padded_form = raw == id8
            found[id8] = PositionRef(id8, raw, source, padded_form or id8 in vouched)

    lead = fp.leading_list_pattern.search(name)
    lead_end = 0
    if lead is not None:
        run = lead.group(1) or ""
        lead_end = lead.end()
        for token in _DIGITS.finditer(run):
            after_caret = token.start() > 0 and run[token.start() - 1] == "^"
            if after_caret and len(token.group()) < fp.caret_tail_min_digits:
                continue
            keep(token.group(), "leading")
    for label in fp.labelled_position_pattern.finditer(name):
        for token in _DIGITS.finditer(label.group(1) or ""):
            keep(token.group(), "labelled")
    for padded in cfg.position_id_pattern.finditer(name):
        keep(padded.group(1) if padded.re.groups else padded.group(0), "padded")

    group = cfg.employee_group_pattern.search(name)
    return FilenameFacets(
        as_of_date=_date(cfg.file_date_pattern.match(name)),
        positions=tuple(found.values()),
        employee_group=group.group(1) if group else None,
        jd_date=_date(cfg.revision_date_pattern.search(name)),
        title_slug=_title_slug(name, cfg, lead_end),
    )


def _title_slug(name: str, cfg: Segmentation, lead_end: int) -> str | None:
    stem = _EXTENSION.sub("", name)
    if lead_end:
        rest = stem[min(lead_end, len(stem)) :]
    else:
        date = cfg.file_date_pattern.match(stem)
        rest = stem[date.end() :] if date else stem
    rest = _JDFN_TAIL.sub("", rest)
    slug = " ".join(rest.replace("_", " ").split()).strip(" ,-")
    return slug or None

"""What a filename tells you about a JD: format, era, position id, dates, group.

The archive's filenames are a real data source, not decoration (census §3): the
``YYYYMMDD`` prefix is on **all 14,565** files, the ``JDFN`` token is the only reliable
era signal in the 2008-2021 middle band (§4b), and the zero-padded position id is what
turns 14,565 files into 5,327 *positions* (§7b — and see HR-114: the count depends on
how a bundled filename is attributed, so it is 5,541 under `position_id_grouping: all`).

Everything this module decides comes from :class:`~src.jd_core.rules.loader.
Segmentation`. Nothing here is a literal — move a band, retire the token, or change
what counts as an id, and it is a YAML edit.

**Total by construction.** It runs over 14,565 real filenames that can say anything
(``20211301`` is not a month; ``...doc.doc.doc`` is a real name; a file can carry three
position ids or none). A crash here would abort a 9-minute run, so every field is
``None`` rather than an exception.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from pathlib import Path

from src.jd_bank.baseline.config import ArchiveEra
from src.jd_bank.db.models import DocumentFormat
from src.jd_bank.ingest.ingest import detect_format
from src.jd_core.rules import Segmentation


@dataclass(frozen=True)
class FileFacets:
    """One archive file's segmentation keys, read off its name alone (no I/O)."""

    #: The raw final extension (``docx``, ``doc``, ``dot``, ``tif``, ``serv``…). Kept
    #: alongside :attr:`format` because ``.docm``/``.dot``/``.tif``/``.serv`` all
    #: collapse into a ``DocumentFormat`` and the error ledger must still name them.
    extension: str
    #: The :class:`DocumentFormat` the extractor will dispatch on — this is the
    #: ``.doc`` vs ``.docx`` split the brief mandates (antiword hard-wraps legacy
    #: ``.doc``; python-docx does not, and that difference moves findings).
    format: DocumentFormat
    era: ArchiveEra
    #: True when the filename carries the current-template token.
    template_token: bool
    #: The bargaining unit token, present only on JDFN filenames. Usually one of SFU's
    #: four real units — MEASURED over the archive: APSA 3,351 / CUPE 771 / APEX 329 /
    #: POLY 49 — but the shipped pattern yields **12** distinct values in total, because
    #: 36 real filenames carry a typo'd or truncated token (ASPA 26, ASAP 2, D 2, B 2,
    #: S 1, CUPS 1, ASPSA 1, APA 1). Those are reported exactly as found (HR-118): the
    #: baseline does not silently repair the archive's own data.
    employee_group: str | None
    #: The leading ``YYYYMMDD`` (present on every real file).
    file_date: dt.date | None
    #: The trailing ``JDFN_<GROUP>_<YYYYMMDD>`` revision date, when there is one. Read
    #: as a FACT about the filename, independent of whether policy uses it.
    revision_date: dt.date | None
    #: Which date says "this is the current JD for this position" — the POLICY-applied
    #: choice (``prefer_revision_date_for_version``), computed once at read time rather
    #: than re-derived at every call site where the two could drift apart.
    #:
    #: It matters: the revision date differs from the leading date on 2,857 of the 4,494
    #: real JDFN files that carry one, so the knob materially moves which file is
    #: treated as the current JD for a position.
    version_date: dt.date | None
    #: Every zero-padded id in the name (a real filename can bundle three).
    position_ids: tuple[str, ...]

    @property
    def position_id(self) -> str | None:
        """The **primary** id: the first one in the name, or ``None`` if there is none.

        This is a fact about the filename, not a grouping decision. **Which id(s) a file
        is actually grouped by is HR-116** (``position_id_grouping``), and it is applied
        in :func:`~src.jd_bank.baseline.aggregate.population`, which reads
        :attr:`position_ids` — under ``all`` a bundle is grouped by *every* id it names,
        not by this one.

        Census §7b names the limit the shipped ``first`` grouping inherits, and it is
        not hidden: a bundle (``00124799,_00124800,_00124801``) is one file describing
        several positions, so grouping it under its first id over-counts that position's
        revision history and under-counts the others. The full list is always kept in
        :attr:`position_ids`, whichever way the knob is set, so nothing is lost.
        """
        return self.position_ids[0] if self.position_ids else None


def _date_from(match_groups: tuple[str, ...]) -> dt.date | None:
    """``(YYYY, MM, DD)`` -> a date, or ``None`` if the filename lied."""
    try:
        return dt.date(int(match_groups[0]), int(match_groups[1]), int(match_groups[2]))
    except ValueError:
        # e.g. `20211301_...` — a real risk over 14,565 hand-named files. Not a crash:
        # the file still gets a row, in the `unknown` era, and is counted.
        return None


def _era(
    *, file_date: dt.date | None, template_token: bool, config: Segmentation
) -> ArchiveEra:
    """The template era: the date band, with the template token as a PROMOTION.

    **Four bands, because SFU made two transitions four years apart** (HR-109 … HR-111,
    HR-122): the JDFN *template* (2019 -> ``new``) and the territorial/EDI *footer*
    (2023-24 -> ``current``). The 2.5 baseline disproved the three-band model: ``new``
    captured the first transition and was then judged by a blocking gate that only the
    second satisfies, so a 2019 JDFN document — authored correctly under the template
    of its day — was un-approvable. Measured: 10.0% ``new``-era approval against 71.9%
    among JDs carrying the acknowledgement. A sevenfold gap, all of it date.

    **The token promotes; it does not cap.** MEASURED: 50 real files carry the
    current-template token with a pre-2019 leading date (1 in 2010, 1 in 2012, 1 in
    2015, 2 in 2016, 20 in 2017, 25 in 2018) — they were authored under the current
    template, so ``new`` is the bar they should be judged against (census §4b: era in
    the middle band "is most reliably inferred from the JDFN filename token, not body
    headings"). But *every* JD SFU writes today also carries the token, so a token that
    won OUTRIGHT — as it did before 2.6 — would pull every 2024+ file back into ``new``
    and collapse the fourth band on the day it was added. Promotion up the ladder, never
    demotion down it. The promotion is a judgement, not a fact; it is HR-109.

    Era is read from the LEADING (original) date, not the revision date: it asks which
    template a JD was AUTHORED under. ``prefer_revision_date_for_version`` (HR-112)
    answers the different question of which file is a position's current version.
    """
    if file_date is None:
        return "new" if template_token else "unknown"
    year = file_date.year
    if year > config.era_new_max_year:
        return "current"
    if year > config.era_transition_max_year:
        return "new"
    if template_token:
        return "new"
    return "old" if year <= config.era_old_max_year else "transition"


def file_facets(path: Path, config: Segmentation) -> FileFacets:
    """Read every segmentation key off ``path``'s name. Pure; never raises."""
    name = path.name
    extension = path.suffix.lower().lstrip(".")

    date_match = config.file_date_pattern.search(name)
    file_date = _date_from(date_match.groups()) if date_match else None

    revision_match = config.revision_date_pattern.search(name)
    revision_date = _date_from(revision_match.groups()) if revision_match else None

    group_match = config.employee_group_pattern.search(name)
    template_token = config.era_template_token in name

    version_date = file_date
    if config.prefer_revision_date_for_version and revision_date is not None:
        version_date = revision_date

    return FileFacets(
        extension=extension,
        format=detect_format(name),
        era=_era(file_date=file_date, template_token=template_token, config=config),
        template_token=template_token,
        employee_group=group_match.group(1) if group_match else None,
        file_date=file_date,
        revision_date=revision_date,
        version_date=version_date,
        position_ids=tuple(config.position_id_pattern.findall(name)),
    )

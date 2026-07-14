"""``jd_bank.dedup.near.text`` — the I/O boundary every real Tier-2 run goes through.

**Why this file exists (reviewer must-fix 3).** The first cut of 3.3 shipped
``text.py`` at **53% coverage**: no test imported ``ArchiveTextSource`` or
``SerializedTextSource`` at all, because every other test injects a fake. So the code
path that the *shipped default* uses — the only place ``detect_format`` /
``extract_text`` / ``normalize_incumbent_names`` / ``stable_reason`` are wired for
Tier-2 — **never ran in CI**. Worse, ``dedup.text_source`` (HR-131) was the one dedup
knob with no behavioural pin anywhere: flipping it moved only ``Dedup.stamp``. HR-131's
own register entry defends itself with *"Both branches are IMPLEMENTED — a knob whose
alternative does nothing is the ``cluster_algo`` landmine in a new place."* Implemented
is not exercised.

``SerializedTextSource`` needs a live ``parsed_jds`` row, so its tests live in
``tests/integration/test_dedup_near.py``. Everything here is unit-scope: a real file on
``tmp_path`` for the archive source, and the rulebook-driven selector.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.jd_bank.dedup.models import DocumentRef
from src.jd_bank.dedup.near.text import (
    ArchiveTextSource,
    SerializedTextSource,
    TextResult,
    text_source_for,
)
from src.jd_core.rules import get_rules
from tests.unit.retuned_rules import retuned_dedup


def _ref(path: Path, *, filename: str | None = None) -> DocumentRef:
    return DocumentRef.for_path(
        str(path), sha256="sha-fixture", filename=filename or path.name
    )


# --- TextResult's own guard (was uncovered: text.py line 59) -----------------------


def test_a_missing_text_must_carry_a_reason() -> None:
    """A ``TextResult`` with neither text nor a reason is a silent drop wearing a
    result's clothes — the exact thing this module refuses to allow."""
    with pytest.raises(ValueError, match="must carry a reason"):
        TextResult(text=None)


def test_a_present_text_needs_no_reason() -> None:
    assert TextResult(text="hello").reason is None


# --- ArchiveTextSource: THE SHIPPED DEFAULT'S code path ---------------------------


@pytest.mark.asyncio
async def test_archive_text_source_reads_and_extracts_a_real_file(
    tmp_path: Path,
) -> None:
    path = tmp_path / "20200101_00012345_Coordinator.txt"
    path.write_text("The Coordinator manages the schedule.", encoding="utf-8")

    result = await ArchiveTextSource().text_for(_ref(path))
    assert result.reason is None
    assert result.text is not None
    assert "Coordinator manages the schedule" in result.text


@pytest.mark.asyncio
async def test_archive_text_source_scrubs_incumbent_names(tmp_path: Path) -> None:
    """LANDMINE 2 (Phase 3.2a), in Tier-2's clothing: this text is what gets
    shingled, and (if the cosine confirm is ever on) sits beside vectors computed on
    `aria-gb10-2`. An incumbent name must never survive the read."""
    path = tmp_path / "legacy.txt"
    path.write_text(
        "NAME OF EMPLOYEE: Jane Q. Doe\nThe Coordinator manages the schedule.",
        encoding="utf-8",
    )

    result = await ArchiveTextSource().text_for(_ref(path))
    assert result.text is not None
    assert "Jane" not in result.text
    assert "[name redacted]" in result.text
    assert "Coordinator manages the schedule" in result.text


@pytest.mark.asyncio
async def test_archive_text_source_reports_a_missing_file_as_unreadable(
    tmp_path: Path,
) -> None:
    """An ``OSError`` must come back as a COUNTED unreadable, never raise out of the
    pass — and (must-fix 1) never prune the document's edges either."""
    missing = tmp_path / "not_here.txt"
    result = await ArchiveTextSource().text_for(_ref(missing))
    assert result.text is None
    assert result.reason is not None
    assert "FileNotFoundError" in result.reason


@pytest.mark.asyncio
async def test_archive_text_source_reports_an_unsupported_format_as_unreadable(
    tmp_path: Path,
) -> None:
    """``detect_format`` returns ``DocumentFormat.OTHER`` for a ``.pdf``/``.tif``, and
    ``extract_text`` raises ``UnsupportedFormatError``. Nothing tested this before;
    the archive genuinely contains such files (the 2.5 skip ledger)."""
    path = tmp_path / "scan.pdf"
    path.write_bytes(b"%PDF-1.4 not really a pdf")

    result = await ArchiveTextSource().text_for(_ref(path))
    assert result.text is None
    assert result.reason is not None
    assert "UnsupportedFormatError" in result.reason


@pytest.mark.asyncio
async def test_archive_text_source_reports_an_empty_extract_as_unreadable(
    tmp_path: Path,
) -> None:
    path = tmp_path / "blank.txt"
    path.write_text("   \n\n  ", encoding="utf-8")

    result = await ArchiveTextSource().text_for(_ref(path))
    assert result.text is None
    assert result.reason == "extracted to empty text"


@pytest.mark.asyncio
async def test_archive_text_sources_reason_is_stable_across_runs(
    tmp_path: Path,
) -> None:
    """The reason string feeds counted, committed output — it must not carry a temp
    path or a heap address (``stable_reason``; HANDOFF's byte-identical-artifact
    rule)."""
    missing = tmp_path / "gone.txt"
    first = await ArchiveTextSource().text_for(_ref(missing))
    second = await ArchiveTextSource().text_for(_ref(missing))
    assert first.reason == second.reason
    assert "0x" not in (first.reason or "")


# --- THE KNOB: dedup.text_source SELECTS a source (HR-131) ------------------------


def test_the_text_source_knob_selects_the_source() -> None:
    """**HR-131's behavioural pin.** Flip the knob in the rulebook and a DIFFERENT
    class comes back — the knob selects code, it does not merely stamp a string.
    Without this, `text_source` was `cluster_algo`'s landmine with one extra step:
    both branches written, neither one proven to be reachable from the rulebook.

    ``session`` is passed as ``None`` (typed away) because ``ArchiveTextSource`` never
    touches it and ``SerializedTextSource`` only stores it — the SELECTION is what is
    under test here, not either source's behaviour (covered above / in the
    integration suite).
    """
    rules = get_rules()
    assert rules.dedup.text_source == "raw_clean"  # the shipped default

    raw = text_source_for(rules, session=None)  # type: ignore[arg-type]
    assert isinstance(raw, ArchiveTextSource)

    serialized = text_source_for(
        retuned_dedup(rules, text_source="serialized"),
        session=None,  # type: ignore[arg-type]
    )
    assert isinstance(serialized, SerializedTextSource)
    assert not isinstance(serialized, ArchiveTextSource)

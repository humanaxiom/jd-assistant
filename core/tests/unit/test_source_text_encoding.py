"""No source file may carry DOUBLE-ENCODED text — the funnel page shipped 29 of them.

**What went wrong.** `jd_bank/library/funnel.py` held 29 characters that had been
encoded to UTF-8, decoded again as latin-1, then re-encoded — 19 em dashes, 6 arrows,
3 warning signs and an en dash, each arriving as two or three stray glyphs. Because the
result is still *valid* UTF-8, nothing failed: not the parser, not ruff, not mypy, not
any test. It failed only in the one place that matters — **on the page**, where a
stakeholder read `The validator's quality grade A<garbage>D`.

**Why a guard and not just a fix.** Every surface string in this project is written to
be read by an HR reviewer or a vice-president, and mojibake is invisible to every other
gate the repo has. It also comes back: the corruption arrives from an editor or a paste,
not from anything a reviewer would notice in a diff full of prose.

**How it detects.** A run of two or more characters in the latin-1 range that *decodes
cleanly as UTF-8 when re-encoded to latin-1* is, with overwhelming probability,
mojibake: that round trip only succeeds on byte sequences that were UTF-8 to begin with.
A lone `§` or `·` is a legitimate character and never matches, because it is one
character and does not form a multi-byte sequence.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[2] / "src"

#: Two to six adjacent latin-1-range characters — the shape a multi-byte UTF-8 sequence
#: takes once it has been mis-decoded as latin-1.
#: Written as ESCAPES, not literal characters. A guard file about text encoding that
#: itself holds raw high-bytes is one bad paste away from testing something else.
_RUN = re.compile("[\u0080-\u00ff]{2,6}")

#: The file types whose text reaches a human.
_SUFFIXES = (".py", ".html", ".md", ".yaml", ".yml", ".txt", ".json")


def _mojibake_in(text: str) -> list[tuple[str, str]]:
    """Every run in ``text`` that round-trips to valid UTF-8, with what it should be."""
    found: list[tuple[str, str]] = []
    for run in _RUN.findall(text):
        try:
            decoded = run.encode("latin-1").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            continue  # a genuine pair of latin-1 characters, not a mis-decode
        found.append((run, decoded))
    return found


def _source_files() -> list[Path]:
    return sorted(
        path
        for path in _SRC.rglob("*")
        if path.is_file()
        and path.suffix in _SUFFIXES
        and "__pycache__" not in path.parts
    )


def test_there_are_source_files_to_check() -> None:
    """The control. A guard that silently scanned nothing would pass forever — which is
    this repo's standing objection to a gate that can never fire."""
    files = _source_files()
    assert len(files) > 100, f"only {len(files)} source files found — is _SRC right?"


def test_no_source_file_contains_double_encoded_text() -> None:
    """MEASURED 2026-09-11: 29 such characters in `library/funnel.py` alone, and
    every one rendered on the LIVE funnel - the page shown to the CIO task force."""
    offenders: list[str] = []
    for path in _source_files():
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:  # pragma: no cover - a non-UTF-8 file is its own bug
            offenders.append(f"{path}: is not valid UTF-8 at all")
            continue
        hits = _mojibake_in(text)
        if hits:
            shown = ", ".join(f"{run!r} -> {fixed!r}" for run, fixed in hits[:5])
            offenders.append(f"{path.relative_to(_SRC)}: {len(hits)} run(s) — {shown}")

    assert not offenders, (
        "double-encoded (mojibake) text found. It is valid UTF-8, so nothing else "
        "catches it — but it renders as garbage on the page:\n  "
        + "\n  ".join(offenders)
    )


@pytest.mark.parametrize(
    ("broken", "intended"),
    [
        ("â", "—"),  # em dash - the 19 in funnel.py
        ("â", "–"),  # en dash - "quality grade A-D"
        ("â", "→"),  # arrow   - "archive -> published"
        ("â ", "⚠"),  # warning sign
    ],
)
def test_the_detector_catches_the_shapes_that_actually_shipped(
    broken: str, intended: str
) -> None:
    """Pin the detector against the REAL corruptions, so a future refactor of the regex
    cannot quietly stop finding them."""
    assert _mojibake_in(f"text {broken} more") == [(broken, intended)]


def test_legitimate_single_latin1_characters_are_not_flagged() -> None:
    """`§` and `·` are real characters this repo uses on purpose, and a false positive
    here would make the guard something people delete rather than fix."""
    assert _mojibake_in("see § 4 · and · 5") == []
    assert _mojibake_in("café naïve") == []

"""Deterministic JD parser — clean text → segmented ``SFUJobDescription``.

The Phase-1.4 parse step: a no-LLM section segmenter tolerant of both the OLD
and NEW SFU JD templates, with per-section confidence. See
:mod:`jd_core.parser.segmenter` for the algorithm and
:mod:`jd_core.parser.headings` for the versioned heading-pattern data.
"""

from __future__ import annotations

from src.jd_core.parser.headings import Era, SectionKey
from src.jd_core.parser.segmenter import (
    FALLBACK_TITLE,
    PARSER_VERSION,
    ParseResult,
    Template,
    parse_jd,
)

__all__ = [
    "FALLBACK_TITLE",
    "PARSER_VERSION",
    "Era",
    "ParseResult",
    "SectionKey",
    "Template",
    "parse_jd",
]

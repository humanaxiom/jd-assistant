"""Unit — the WJQ point-factor sections are stored WHOLE (Phase A of CUPE support).

``wjq.py::_structure_context`` documents itself as storing the seven Hay-factor sections
"verbatim — lossless", and until now its last statement was ``[:_MAX_SUMMARY]`` — a
4,000-character cut. **The docstring was false**, and the cost was measured over the
live archive: **81.4% of CUPE JDs (3,613 of 4,440) sat exactly at the cap**, against
**0%** of APSA. The cut falls in document order, so the tail of the instrument was what
disappeared — ``continuing_education``, the last section, survived in only **17.0%** of
documents.

Measured with the real parser over a 500-file random sample of the archive (149 WJQ
documents with context): true lengths run **min 2,677 · p50 5,500 · p90 6,614 ·
p99 8,931 · max 9,916**. At the old cap **80.5%** were truncated — which independently
reproduces the 81.4% seen in the database, from the other direction.

**The cap is now rulebook data and registered** as
``segmentation.additional_context_max_chars`` (HR-200). It remains a real bound — an
unbounded field is how one malformed document becomes a database problem — but it is a
bound chosen against the measured distribution rather than inherited from
``position_summary``, a field with entirely different semantics.
"""

from __future__ import annotations

from src.jd_core.models.parsed_jd import SFUJobDescription
from src.jd_core.parser.wjq import _structure_context
from src.jd_core.rules import get_rules


def _context_sections(chars_each: int) -> dict[str, str]:
    """One block per WJQ context section, each ``chars_each`` long."""
    rules = get_rules()
    return {section: "x" * chars_each for section in rules.wjq.context_sections}


def test_the_seven_point_factor_sections_survive_whole() -> None:
    """🔴 THE REGRESSION. Seven sections of ~800 chars is ~5,600 — the measured p50 of a
    real CUPE JD — and under the old 4,000-char cut the last two vanished entirely."""
    rules = get_rules()
    context = _structure_context(_context_sections(800), rules.wjq)  # type: ignore[arg-type]

    assert context is not None
    for section in rules.wjq.context_sections:
        heading = rules.wjq.section_headings[section][0]
        assert heading in context, f"{section} was truncated away"


def test_a_document_at_the_measured_maximum_is_not_cut() -> None:
    """The largest real WJQ context over the WHOLE archive is **13,379** characters
    (two near-identical Technician JDs). A cap that cuts the biggest genuine document is
    the defect, not the guard.

    ⚠ That number is why this test says 13,379 and not 9,916. A 149-document sample said
    9,916, the cap was set to 12,000 for headroom, and re-parsing all 14,522 files put
    those two documents at exactly the cap — **the sample understated the corpus maximum
    by 35%** while predicting the corpus mean within 2%. A sample is a good estimator of
    the middle and a poor one of the tail, and a cap lives entirely in the tail.
    """
    rules = get_rules()
    per_section = 13379 // len(rules.wjq.context_sections) + 1
    context = _structure_context(_context_sections(per_section), rules.wjq)  # type: ignore[arg-type]

    assert context is not None
    assert len(context) >= 13379


def test_the_cap_is_rulebook_data_not_a_code_constant() -> None:
    """A metric that decides whether 81% of a cohort loses content is not a constant to
    bury in a parser — the standing rule is that it is YAML-configurable and registered.
    """
    cap = get_rules().segmentation.additional_context_max_chars

    assert cap >= 10000, "below the measured p100 of a real CUPE document"


def test_the_configured_cap_still_fits_the_model_contract() -> None:
    """The rulebook cap and the pydantic ceiling must not drift apart: a configured cap
    ABOVE the model's ``max_length`` would turn a truncation into a ValidationError —
    a parse failure instead of a lossy parse. The model ceiling is the outer bound; the
    rulebook picks the operative value under it."""
    cap = get_rules().segmentation.additional_context_max_chars
    ceiling = SFUJobDescription.model_fields["additional_context"].metadata

    limits = [getattr(m, "max_length", None) for m in ceiling]
    model_max = next(limit for limit in limits if limit is not None)
    assert (
        cap <= model_max
    ), f"configured cap {cap} exceeds the model ceiling {model_max}"


def test_context_is_still_bounded() -> None:
    """It is a *bound*, not an open field. An unbounded column is how one malformed
    document becomes a database problem."""
    rules = get_rules()
    cap = rules.segmentation.additional_context_max_chars
    context = _structure_context(_context_sections(cap), rules.wjq)  # type: ignore[arg-type]

    assert context is not None
    assert len(context) <= cap


def test_no_context_sections_still_yields_none() -> None:
    """A JDFN document routed here, or a WJQ form with none of the seven sections, must
    produce ``None`` rather than an empty string — ``None`` is what the confidence map
    reads as "absent"."""
    assert _structure_context({}, get_rules().wjq) is None

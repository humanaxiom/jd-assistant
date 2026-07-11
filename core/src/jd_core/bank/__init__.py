"""jd_core.bank — JD Bank's pure harmonization primitives (no I/O).

Ported from hris ``packages/pipeline/src/pipeline/bank/`` (ADR-005, reuse-map
#11–12). Phase 2.4a lands the two mechanical pieces:

    from src.jd_core.bank import render_sfu_jd_text, skill_frequency

    freq = skill_frequency([{"python", "sql"}, {"python"}])  # provenance
    text = render_sfu_jd_text(canonical.jd)                  # canonical -> text

The similarity / clustering / title-family / Hay-signal / drift / export modules
of the same hris package land in later tasks. Everything in here is pure and
deterministic, so it is unit-tested in isolation.
"""

from src.jd_core.bank.provenance import skill_frequency
from src.jd_core.bank.render import render_sfu_jd_text

__all__ = ["render_sfu_jd_text", "skill_frequency"]

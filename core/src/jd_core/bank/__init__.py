"""jd_core.bank — JD Bank's pure harmonization primitives (no I/O).

Ported from hris ``packages/pipeline/src/pipeline/bank/`` (ADR-005, reuse-map
#11–12). Phase 2.4a landed the two mechanical pieces; 2.4b adds the two advisory
classifiers::

    from src.jd_core.bank import (
        classify_title, estimate_hay_signals, render_sfu_jd_text, skill_frequency,
    )

    freq = skill_frequency([{"python", "sql"}, {"python"}])  # provenance
    text = render_sfu_jd_text(canonical.jd)                  # canonical -> text
    title = classify_title("Manager, Research Services")     # seniority + function
    hay = estimate_hay_signals(canonical.jd)                 # advisory, NEVER a grade

Both classifiers are **advisory**: the title family/function anchors help
standardize titling and compare like roles, and the Hay signals help Compensation
*level* a role. Neither decides anything — no approval gate reads them — and
neither assigns a Hay grade (SFU publishes no point charts, and
:class:`~src.jd_core.models.bank.HaySignals` has no field that could hold one).

Every table they read is versioned YAML under ``jd_core/rules/`` (CLAUDE.md §2),
down to the *order* the title keywords are tried in.

The similarity / clustering / drift / export modules of the same hris package land
in later tasks. Everything in here is pure and deterministic, so it is unit-tested
in isolation.
"""

from src.jd_core.bank.hay_signals import estimate_hay_signals
from src.jd_core.bank.provenance import skill_frequency
from src.jd_core.bank.render import render_sfu_jd_text
from src.jd_core.bank.title_family import (
    classify_title,
    classify_title_family,
    classify_title_function,
    title_comma_supervisory,
)

__all__ = [
    "classify_title",
    "classify_title_family",
    "classify_title_function",
    "estimate_hay_signals",
    "render_sfu_jd_text",
    "skill_frequency",
    "title_comma_supervisory",
]

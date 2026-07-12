"""The baseline's own vocabulary, and the one accessor for its segmentation policy.

**The policy itself is not here.** It is ``jd_core/rules/segmentation.yaml``, loaded and
validated by the rulebook loader like every other rule file, registered as HR-109 …
HR-118, and drift-checked by ``make gates`` — CLAUDE.md non-negotiable #2: versioned
decision YAML lives under ``jd_core/rules/``, never anywhere else. It is deliberately
excluded from the rulebook's *content hash* (see
:class:`~src.jd_core.rules.loader.Segmentation`), so re-banding an era cannot churn
``rules_version``; but it is an ordinary rule file in every other respect, exactly as
``decision_register.yaml`` is.

So this module is thin on purpose. The segmentation policy is reached through
:func:`get_baseline_config`, which is ``get_rules().segmentation`` and nothing more.
There is no second config subsystem, and ``jd_bank`` depends on ``jd_core`` — the
direction it already depended in.
"""

from __future__ import annotations

from typing import Final, Literal

from src.jd_core.rules import Segmentation, get_rules

#: The template era a JD was authored under, inferred from its FILENAME.
#:
#: **Not** :data:`src.jd_core.parser.headings.Era` (``old``/``new``/``unknown``), which
#: is inferred from the document BODY. They answer different questions — "what template
#: was this written on?" vs "what headings does this text use?" — and conflating them
#: would be a category error, so the vocabularies deliberately differ (``transition``
#: exists only here). A baseline row carries both.
ArchiveEra = Literal["old", "transition", "new", "unknown"]

#: The three populations the baseline reports over. See ``segmentation.yaml`` for why a
#: single blended number would be weighted by re-save habits rather than by quality.
DedupPopulation = Literal["all", "content_dedup", "latest_per_position"]

#: All three, in report order — derived from the type, so adding a population to the
#: vocabulary makes the aggregator demand one rather than silently omit it.
POPULATIONS: Final[tuple[DedupPopulation, ...]] = (
    "all",
    "content_dedup",
    "latest_per_position",
)


def get_baseline_config() -> Segmentation:
    """The live segmentation policy — one line, because it is just a rule file.

    :func:`~src.jd_core.rules.get_rules` already parses it once, validates it,
    cross-checks every registered ``current_default`` against it, and refuses to
    start if the register has drifted. The baseline gets all of that free by *not*
    having a loader of its own.
    """
    return get_rules().segmentation

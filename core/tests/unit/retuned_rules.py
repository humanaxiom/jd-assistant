"""A rulebook with ``comparison.yaml`` retuned — the "what if HR moved it" fixture.

Every number in ``rules/comparison.yaml`` is an *open* HR decision (HR-082 …
HR-103): nobody at SFU has ratified one. So the bank suites do not merely assert
today's values — they assert that the modules **read the YAML**, by re-loading the
shipped file with one key changed and watching the behaviour follow. A module that
kept an hris constant in Python would pass the value assertions and fail these.

The retuned file is built from the *real* ``comparison.yaml`` text and run through
:class:`~src.jd_core.rules.Comparison` in full, so a retuning that the rulebook
would reject (weights that do not sum to 1, a cue for a rung that is not on the
ladder) fails here exactly as it would at load. It is deliberately not a
``model_dump()`` round-trip: the file's compiled ``Regex`` fields do not survive
one, and a fixture that silently skipped validation would be no fixture at all.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from src.jd_core.rules import Comparison, Rules

_PKG_DIR = Path(__file__).resolve().parents[2] / "src" / "jd_core" / "rules"
_COMPARISON = _PKG_DIR / "comparison.yaml"


def raw_comparison() -> dict[str, Any]:
    """The shipped ``comparison.yaml``, as the loader sees it before validation."""
    data: dict[str, Any] = yaml.safe_load(_COMPARISON.read_text(encoding="utf-8"))
    return data


def retuned(rules: Rules, **fields: Any) -> Rules:
    """``rules`` with ``comparison.yaml`` re-validated, ``fields`` overridden."""
    comparison = Comparison.model_validate({**raw_comparison(), **fields})
    return rules.model_copy(update={"comparison": comparison})

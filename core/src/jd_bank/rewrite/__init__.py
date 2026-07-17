"""LLM harmonize rewrite pass (Phase 4.2a).

Takes the deterministic Phase-4.1 merge draft and has a self-hosted LLM reword it into
cleaner, template-faithful prose WITHOUT inventing content, then scores the result with
the validator (the oracle). The output is an explicit DRAFT — nothing auto-publishes.
"""

from __future__ import annotations

from src.jd_bank.rewrite.harmonize import rewrite_merged_role

__all__ = ["rewrite_merged_role"]

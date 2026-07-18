"""LLM nuanced quality-audit pass (Phase 4.2b).

Takes an already-parsed ``SFUJobDescription`` (a 4.1 merge draft or a 4.2a rewritten
draft) and has a self-hosted LLM report only the three NUANCED dimensions a regex
validator cannot judge — inclusive language, clarity, seniority mismatch — each backed
by a VERBATIM quote from the JD. The anti-fabrication guard drops any finding whose
evidence is not found verbatim in the JD. The result is an advisory, frozen
``QualityAudit``: it computes NO score and no grade (the deterministic validator remains
the oracle), and nothing auto-publishes.
"""

from __future__ import annotations

from src.jd_bank.quality.audit import audit_quality

__all__ = ["audit_quality"]

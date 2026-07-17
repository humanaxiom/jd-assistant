"""Phase-4.1 harmonization measurement pass (report-only).

Drives the pure ``jd_core.bank.merge.merge_cluster`` engine over the real JDFN role
clusters and measures the distributions the nine ``harmonization.yaml`` knobs (HR-167…
HR-175) cut on, so a human can calibrate them. Persists nothing, commits nothing, picks
no knob value — the coder MEASURES, the orchestrator DECIDES.
"""

from src.jd_bank.harmonize.models import (
    ClusterHarmonization,
    HarmonizationResult,
)
from src.jd_bank.harmonize.runner import run_harmonization

__all__ = [
    "ClusterHarmonization",
    "HarmonizationResult",
    "run_harmonization",
]

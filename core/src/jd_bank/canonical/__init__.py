"""Phase-4.4a canonical-draft PRODUCER (clusters -> persisted DRAFT canonical_jds).

Turns the real JDFN role clusters into persisted ``canonical_jds`` DRAFT rows — the
work-list the 4.4b review service and the 4.4d UI consume. Per cluster it drives the
Phase-4 pipeline end to end (4.1 merge -> 4.2a rewrite -> 4.2b audit -> 4.3 change-log
-> validator) and persists the result as a DRAFT.

**Nothing is ever published or approved** (non-negotiable #1). Re-running is idempotent
and NEVER clobbers a canonical a reviewer has already acted on.
"""

from src.jd_bank.canonical.models import CanonicalProducerResult
from src.jd_bank.canonical.runner import run_canonical_producer

__all__ = [
    "CanonicalProducerResult",
    "run_canonical_producer",
]

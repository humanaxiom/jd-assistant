"""Document-frequency idf over the corpus's skill keyword-bags (Phase 3.4b).

The keyword bag :attr:`~src.jd_core.models.bank.JobSignals.skills` (3.4a) is
deliberately noisy: a stopword list cannot separate a distinctive skill (``kubernetes``)
from a ubiquitous one (``communication``) — idf is what does. This module computes, over
the WHOLE v2 corpus's skill sets, the inverse-document-frequency weight ``ln(N / (1 +
df))`` for every skill, and STAMPS the result so a Tier-3 edge can record which idf
corpus produced its score.

The idf *numbers* are a DERIVED artifact (6,058 of them on the real archive), NOT
rulebook data — they do not go in YAML. The idf *method* is what is registered (it is
``score_job_similarity``'s skill term; the source kinds + stopwords that feed the bag
are HR-149/HR-150). This module is the derivation.

**DETERMINISM is load-bearing** (the reproducibility rule, HANDOFF). The same corpus —
in ANY order — must yield byte-identical weights and an identical
:attr:`~IdfCorpus.stamp`, because the stamp rides in the edge ``method`` and two runs
that disagreed would churn the reconcile forever. So ``df`` is counted over a SORTED
skill iteration, the stamp digests the integer ``(N, df)`` pairs (never the float
weights, whose ``repr`` could carry platform noise), and nothing here uses a set's
iteration order as data.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

#: Stamp prefix — bump only when the idf FORMULA changes (a code change, not a corpus
#: change; a corpus change already moves the digest half).
IDF_VERSION: Final[str] = "idf_v1"

#: Short-digest length, mirroring ``CONTENT_HASH_LENGTH`` / the dedup stamps.
_STAMP_HASH_LENGTH: Final[int] = 12


@dataclass(frozen=True, slots=True)
class IdfCorpus:
    """The idf weights over a corpus's skill bags, plus the identity of the corpus that
    produced them.

    ``weights[skill] = max(0, ln(N / (1 + df)))``. A skill absent from the corpus is NOT
    a key — a consumer defaults it to ``1.0`` (plain Jaccard), which is exactly what
    :func:`~src.jd_core.bank.similarity.skill_overlap` does. Ubiquitous skills earn a
    weight near zero — FLOORED at 0 when ``df`` reaches ``N`` (the raw log would go
    negative; see :func:`compute_idf`) — which is the whole point: they stop dominating
    the overlap, and a negative weight can never drag ``skill_overlap`` below 0.
    """

    weights: Mapping[str, float]
    num_documents: int
    #: ``<IDF_VERSION>+<12-hex digest of (N, df)>`` — a corpus's content identity.
    stamp: str

    @property
    def num_skills(self) -> int:
        return len(self.weights)


def compute_idf(skill_sets: Iterable[frozenset[str]]) -> IdfCorpus:
    """The idf corpus over ``skill_sets`` (one per JD, INCLUDING the empty bags — a JD
    with no skills still counts toward ``N``, which is honest: 41% of the archive has an
    empty bag, and pretending they are not documents would inflate every idf weight).

    Pure + deterministic: iteration order of the input, and of every skill set within
    it, does not affect the result (``df`` is a count; the stamp digests sorted integer
    data).
    """
    materialized = list(skill_sets)
    num_documents = len(materialized)
    document_frequency: Counter[str] = Counter()
    for skills in materialized:
        document_frequency.update(skills)

    # Sorted iteration -> a deterministic dict AND a deterministic digest.
    # ``ln(N/(1+df))`` as HR-158's basis specifies, FLOORED AT 0: the raw log goes
    # NEGATIVE when a skill is in (nearly) every signed doc (df -> N). On the full
    # archive that cannot happen (41% empty bags cap max df; min real weight +0.53), but
    # ``--limit`` runs a small slice where a skill in every doc makes ``skill_overlap``
    # (and the blend) negative and crashes a ``ge=0.0`` field. A 0 floor also serves
    # this module's "ubiquitous skills earn ~zero weight" rationale better than a
    # negative does. N==0 yields an empty corpus (no skills at all).
    weights = {
        skill: max(0.0, math.log(num_documents / (1 + document_frequency[skill])))
        for skill in sorted(document_frequency)
    }
    payload = json.dumps(
        {
            "n": num_documents,
            "df": {skill: document_frequency[skill] for skill in sorted(weights)},
        },
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return IdfCorpus(
        weights=MappingProxyType(weights),
        num_documents=num_documents,
        stamp=f"{IDF_VERSION}+{digest[:_STAMP_HASH_LENGTH]}",
    )

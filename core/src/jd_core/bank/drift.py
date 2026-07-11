"""Drift detection: how far a posting has diverged from its canonical role (pure).

Ported from hris ``packages/pipeline/src/pipeline/bank/drift.py`` (reuse-map,
ADR-005). A JD linked to a canonical role can drift as it is edited, or as the
canonical evolves. We compare the two **skill sets** and report what the posting
added, what it dropped, and a deterministic drift level.

Beyond raw skill churn, a change to the *qualifications that change the technical
knowledge required* escalates the level to "major" on its own. We key that on three
comparable signals: the required **education level**, the **experience bar**, and
the **supervisory scope** (> 5 direct reports). Each escalation fires only when
*both* sides supply a value and they differ, so a missing or unparseable
requirement never manufactures drift. Advisory, like the Hay signals: it flags a
posting worth a second look at review time. It blocks nothing.

⚠ **NOT WIRED TO ANYTHING, DELIBERATELY.** Nothing in JD Bank calls these
functions, and nothing can yet:

* ``compute_drift`` compares two **skill sets**. In hris those came from a Neo4j
  skill graph with a canonical-name ontology. JD Bank has no skill graph, no skill
  ontology, and :class:`~src.jd_core.models.parsed_jd.SFUJobDescription` carries no
  skill set — only free-text qualifications.
* the education / experience / supervisory signals are ``int``s the *caller*
  supplies. The text helpers below can produce them from prose, but nothing
  persists a canonical role's education level or years bar to compare against.

That is expected and accepted. The maths and the thresholds are what this task
lands — tested, and registered with HR (HR-098 … HR-103) — so that when Phase 3
(dedup & clustering) builds the corpus that *can* feed them, the numbers arrive
already declared rather than smuggled in inside a feature PR. **Do not invent a
skill source, and do not scrape prose to make these callable.**

⚠ **PROVENANCE.** hris cited the escalations to "SFU's re-evaluation criteria
(Toolkit p26)" and the > 5-reports rule to "Toolkit p23-24". The rulebook this repo
ships (``docs/rulebook/sfu-jd-standards.txt``) contains **no re-evaluation criteria
at all** — only l.22, "Major revisions can trigger re-evaluation", which quantifies
nothing. The *intent* is plausibly SFU's; the numbers are not published. Every
threshold here is registered ``hris_calibration``, ``open``. See ``comparison.yaml``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.jd_core.models.bank import DriftLevel
from src.jd_core.rules import Comparison, Rules, get_rules

#: The level a JD sits at before any cutoff or escalation moves it.
_ALIGNED: DriftLevel = "aligned"

#: What an out-of-range ordinal is called in a reason. hris used the same "?": the
#: reason is HR-facing copy and must not raise on a caller's bad ordinal.
_UNKNOWN_RUNG = "?"


def _comparison(rules: Rules | None) -> Comparison:
    return (rules if rules is not None else get_rules()).comparison


def _rung_name(ladder: tuple[str, ...], ordinal: int) -> str:
    """The ladder rung ``ordinal`` names — ``"?"`` if it names none."""
    return ladder[ordinal] if 0 <= ordinal < len(ladder) else _UNKNOWN_RUNG


def education_ordinal(
    min_level: str | None, *, rules: Rules | None = None
) -> int | None:
    """A structured education level's position on the rulebook's education ladder.

    ``None`` when the level is absent or is not a rung (``comparison.yaml ::
    education_ladder``, HR-082) — an unknown level never becomes an ordinal, and so
    never manufactures drift.
    """
    return _comparison(rules).education_ordinal(min_level)


def education_level_from_text(text: str, *, rules: Rules | None = None) -> int | None:
    """Best-effort ordinal for a *free-text* education requirement.

    The cues are tried most-senior rung first (``Comparison.education_text_rules``),
    so "Master's degree" maps to *masters* and not to the generic "degree" ->
    *bachelors* rung. ``None`` when no cue matches: an unparseable requirement is
    conservative, never an escalation.
    """
    comparison = _comparison(rules)
    low = text.lower()
    for rung, cues in comparison.education_text_rules:
        if any(cue in low for cue in cues):
            return comparison.education_ordinal(rung)
    return None


def experience_years_from_text(text: str, *, rules: Rules | None = None) -> int | None:
    """The first explicit year-count in a free-text experience requirement (e.g.
    "5 years", "3+ years"). ``None`` when the text names no number."""
    match = _comparison(rules).experience_years_pattern.search(text)
    return int(match.group(1)) if match else None


def supervisory_reports_from_text(
    text: str, *, rules: Rules | None = None
) -> int | None:
    """The first direct-reports count named in a free-text supervisory statement
    ("supervises 4 coordinators" -> 4, "manages a team of 8" -> 8).

    ``None`` when the statement is qualitative ("supervises the comms team") or empty
    — then we do not escalate; many supervisory statements state no number at all.
    Heuristic: the first small integer. Documented, unit-tested, and its regex is
    data (HR-100).
    """
    match = _comparison(rules).supervisory_reports_pattern.search(text)
    return int(match.group(1)) if match else None


@dataclass(frozen=True)
class DriftResult:
    """One posting's drift from its canonical role. Advisory; blocks nothing."""

    level: DriftLevel  # "aligned" | "minor" | "major"
    drift_score: float  # skill-set Jaccard distance in [0, 1]
    added: list[str]  # skills the posting has that the canonical doesn't
    dropped: list[str]  # canonical skills the posting no longer has
    shared_count: int
    reasons: list[str] = field(default_factory=list)  # why the level was escalated


def compute_drift(
    canonical_skills: set[str],
    job_skills: set[str],
    *,
    canonical_education: int | None = None,
    job_education: int | None = None,
    canonical_years: int | None = None,
    job_years: int | None = None,
    canonical_reports: int | None = None,
    job_reports: int | None = None,
    rules: Rules | None = None,
) -> DriftResult:
    """Drift between a canonical role and one of its member postings.

    ``drift_score`` is the skill-set Jaccard distance (0 = identical skill sets,
    1 = disjoint); two empty sets are treated as aligned (nothing to diverge on).
    The level is that distance against ``drift_minor_at`` / ``drift_major_at``.

    On top of skill churn, a change to the **technical knowledge required** escalates
    to "major" in its own right: a shift in the required **education level**, a
    material shift in the **experience bar** (``material_years_delta``), or a change
    of more than ``material_reports_delta`` **direct reports**. Each side's signal is
    optional — an escalation fires only when *both* sides supply a value and they
    differ, so a missing or unparseable requirement never manufactures drift.
    """
    comparison = _comparison(rules)
    shared = canonical_skills & job_skills
    union = canonical_skills | job_skills
    score = 0.0 if not union else 1.0 - len(shared) / len(union)
    level: DriftLevel = _ALIGNED
    if score >= comparison.drift_major_at:
        level = "major"
    elif score >= comparison.drift_minor_at:
        level = "minor"

    reasons: list[str] = []
    if (
        canonical_education is not None
        and job_education is not None
        and canonical_education != job_education
    ):
        ladder = comparison.education_ladder
        was = _rung_name(ladder, canonical_education)
        now = _rung_name(ladder, job_education)
        reasons.append(f"education requirement changed ({was} → {now})")
    if (
        canonical_years is not None
        and job_years is not None
        and abs(canonical_years - job_years) >= comparison.material_years_delta
    ):
        reasons.append(f"experience bar changed ({canonical_years}y → {job_years}y)")
    if (
        canonical_reports is not None
        and job_reports is not None
        and abs(canonical_reports - job_reports) > comparison.material_reports_delta
    ):
        reasons.append(
            f"supervisory scope changed "
            f"({canonical_reports} → {job_reports} direct reports)"
        )
    if reasons:
        # A qualification change that moves the technical knowledge required calls
        # for re-evaluation, independent of how much the skill set moved.
        level = "major"

    return DriftResult(
        level=level,
        drift_score=round(score, 4),
        added=sorted(job_skills - canonical_skills),
        dropped=sorted(canonical_skills - job_skills),
        shared_count=len(shared),
        reasons=reasons,
    )

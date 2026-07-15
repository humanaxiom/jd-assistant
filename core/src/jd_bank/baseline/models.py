"""The baseline's output contracts: one row per file, and the segmented summary.

Two rules shape every model here.

**NO SILENT DROPS.** A :class:`BaselineRow` exists for *every* file the walk finds —
14,565 of them. A file that could not be extracted is a row with ``status="skipped"``
and a reason, never an absence. The ``.tif``, the ``.serv``, the ``.dot``s and any
antiword failure are themselves a finding (census §8.5: "not text-parseable ... need
OCR / manual triage"), and a baseline that quietly lost them would over-state its own
coverage.

**"No data" is not "everything failed."** A segment with nothing in it reports
``score=None`` and ``approval_rate=None`` — never ``0.0``. Those two states are the ones
this baseline most needs to keep apart, and making the empty case *unrepresentable as a
zero* is cheaper than remembering to check.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from src.jd_bank.baseline.config import ArchiveEra, DedupPopulation
from src.jd_core.models.quality import JDGrade, JDIssueCategory, JDIssueSeverity

#: Where a file dropped out. ``read`` = the bytes could not be taken off disk (or the
#: file is over the extractor's 50 MiB DoS cap); ``extract`` = no backend for the
#: format,
#: or the backend failed (a corrupt ``.docx``, an antiword timeout).
#:
#: There is deliberately no ``parse`` or ``validate`` member: ``parse_jd`` is documented
#: total ("Deterministic and total: never raises") and ``evaluate_jd_rules`` is pure
#: over its output. If either ever *does* raise, the runner must not swallow it into a
#: tidy ledger entry — that would hide a validator crash on real archive input, which is
#: exactly the bug the Phase-2.3 reviewer found. It propagates and stops the run.
SkipStage = Literal["read", "extract"]

RowStatus = Literal["scored", "skipped"]

#: What a segment slices the population by. ``all`` is the un-sliced whole. ``template``
#: (Phase 3.4) reports the CUPE/WJQ population as its own facet, so nobody quotes a WJQ
#: JD's JDFN-bar score as if it belonged to the current-practice cohort.
SegmentDimension = Literal["all", "format", "era", "template"]


class BaselineFinding(BaseModel):
    """One rule finding, flattened for the artifact.

    ``evidence`` is the verbatim JD span the validator quoted, **truncated** to the
    config's ``evidence_max_chars``. Real JD binaries are already committed under
    ``fixtures/golden/``, so JD-derived text in-repo is precedented — but an artifact
    must not become a copy of the corpus.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    #: ``None`` only for an uncatalogued (LLM) finding. The 2.5 run is
    #: deterministic-only,
    #: so in practice every finding has one — but the field mirrors ``JDQualityIssue``
    #: rather than asserting a property of a run that has not happened yet.
    rule_id: str | None = None
    category: JDIssueCategory
    severity: JDIssueSeverity
    evidence: str | None = None


class BaselineRow(BaseModel):
    """One archive file's complete account: identity, segmentation, and outcome."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    # --- identity ---------------------------------------------------------------
    path: str
    filename: str
    #: ``None`` only when the bytes could not be read at all (``skip_stage="read"``).
    #: Every other row — including every extraction failure — is hashed, because the
    #: exact-content dedup population must be able to see the duplicates *among the
    #: failures* too.
    sha256: str | None = None
    byte_size: int | None = None

    # --- segmentation (from the filename; see `facets.py`) -----------------------
    extension: str
    format: str
    era: ArchiveEra
    template_token: bool
    employee_group: str | None = None
    position_id: str | None = None
    position_ids: tuple[str, ...] = ()
    file_date: dt.date | None = None
    revision_date: dt.date | None = None
    version_date: dt.date | None = None

    # --- outcome -----------------------------------------------------------------
    status: RowStatus
    skip_stage: SkipStage | None = None
    skip_reason: str | None = None

    # --- parse (None on a skipped row) --------------------------------------------
    #: The BODY-derived era (``old``/``new``/``unknown``) — a different question from
    #: :attr:`era`, which is filename-derived. Both are carried so the baseline can say
    #: how often they disagree instead of assuming they do not.
    body_era: str | None = None
    #: Which document TEMPLATE the parser routed to (``jdfn`` / ``wjq``; ``None`` on a
    #: skipped row). Phase 3.4. This is what keeps WJQ (CUPE) JDs OUT of the JDFN
    #: approval-bar cohort (``baseline.aggregate.current_practice_cohort``) — a WJQ JD
    #: scored on the JDFN bar is a category error, and whether CUPE gets its own bar
    #: is a deferred HR decision (HR-143), not one to make by omission.
    template: str | None = None
    parse_confidence: float | None = None
    char_count: int | None = None

    # --- quality (None on a skipped row) -------------------------------------------
    score: float | None = None
    grade: JDGrade | None = None
    issue_count: int | None = None
    #: Sorted + deduplicated: the frequency table counts FILES a rule fired in, not
    #: findings, so a rule firing six times inside one JD must not out-rank one firing
    #: once in every JD.
    rule_ids: tuple[str, ...] = ()
    findings: tuple[BaselineFinding, ...] = ()
    #: **Not an approval.** ``True`` means the rulebook *permits* a human to approve
    #: (CLAUDE.md §1); nothing auto-publishes.
    approved: bool | None = None
    blocking_gate_ids: tuple[str, ...] = ()
    #: The subset a reviewer cannot waive at all — a permanently un-approvable JD. Split
    #: out because HR-047's placeholder gate is non-overridable and is a known live
    #: false positive: "the archive has 4,000 un-waivable JDs" and "our rule is wrong"
    #: look identical in a blended gate count.
    non_overridable_gate_ids: tuple[str, ...] = ()

    # --- stamps ---------------------------------------------------------------------
    #: The content-derived rulebook identity (PR #16) — *which rules produced this row*.
    rules_version: str
    parser_version: str
    #: The segmentation policy's own content stamp — *which population this row is in*.
    config_stamp: str


class HistogramBin(BaseModel):
    """One score bucket: ``lower <= score < upper`` (the top bin includes ``upper``)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    lower: float
    upper: float
    count: int = Field(ge=0)


class ScoreStats(BaseModel):
    """A score distribution. Constructed only when there is something to describe."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    n: int = Field(gt=0)
    minimum: float
    median: float
    mean: float
    maximum: float
    histogram: tuple[HistogramBin, ...]


class SegmentStats(BaseModel):
    """One (population x dimension x value) slice of the archive.

    The unit the whole baseline exists to produce. A blended, whole-corpus approval rate
    would be a category error — ``SFU-COMP-TERRITORIAL`` / ``-ABOUT`` / ``-EDI`` fire on
    nearly every pre-2019 JD because those sections did not exist in the template those
    JDs were authored under — so the number is only ever reported *inside a segment*.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    population: DedupPopulation
    dimension: SegmentDimension
    value: str

    n_files: int = Field(ge=0)
    n_scored: int = Field(ge=0)
    n_skipped: int = Field(ge=0)

    #: ``None`` when nothing in this segment scored — never a zero.
    score: ScoreStats | None = None
    grades: Mapping[JDGrade, int] = Field(default_factory=dict)
    mean_issue_count: float | None = None

    #: How many scored JDs the rulebook would PERMIT a human to approve.
    approved: int = Field(ge=0)
    #: ``None`` when ``n_scored == 0``.
    approval_rate: float | None = None

    #: rule_id -> number of FILES it fired in (not findings). The top of this table is a
    #: bug list, not a quality verdict (HANDOFF): HR-047, HR-046, HR-055, HR-025 and
    #: HR-048 are registered live false-positive generators and are expected near the
    #: top.
    rule_frequency: Mapping[str, int] = Field(default_factory=dict)
    #: The total findings raised, so a rule firing many times in one JD is still
    #: visible.
    total_findings: int = Field(ge=0, default=0)
    #: gate_id -> number of files it BLOCKED.
    gate_frequency: Mapping[str, int] = Field(default_factory=dict)
    #: The un-waivable subset of the above.
    non_overridable_gate_frequency: Mapping[str, int] = Field(default_factory=dict)


class BaselineSummary(BaseModel):
    """The whole run: what it was computed over, and every segment of it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    archive_root: str
    file_count: int = Field(ge=0)
    scored: int = Field(ge=0)
    skipped: int = Field(ge=0)

    #: The three stamps that make this an audit trail rather than a number: the rules
    #: that scored it, the parser that read it, and the segmentation that decided which
    #: files it describes.
    rules_version: str
    parser_version: str
    config_stamp: str
    generated_at: dt.datetime

    segments: tuple[SegmentStats, ...] = ()
    #: The error/skip ledger, grouped: reason -> file count. Every skipped file is also
    #: a full row in ``rows.jsonl`` and a line in ``errors.jsonl``; this is the roll-up.
    skip_reasons: Mapping[str, int] = Field(default_factory=dict)

    # There is deliberately NO population-membership list here. Each population's size
    # is in its segments, and WHO is in it is recomputable from `rows.jsonl` alone:
    # `aggregate.population(rows, name, config=...)` is a pure function of the rows
    # (which carry sha256 / position_ids / version_date) and the config (stamped on
    # every row). Shipping the list would put ~33,500 filenames (~2.2 MB) into a ~150 KB
    # artifact, to restate something already derivable — and would create a second copy
    # of it that can drift.

"""Roll the rows up — segmented, because a blended number would be a category error.

``SFU-COMP-TERRITORIAL``, ``SFU-COMP-ABOUT`` and ``SFU-COMP-EDI`` fire on nearly every
pre-2019 JD because **those sections did not exist in the template those JDs were
authored under**, and ``SFU-APPROVE-EDI-FOOTER`` *blocks*. So a whole-corpus approval
rate would report that the archive is catastrophically non-compliant, when much of it is
simply
**old**. Every number this module produces therefore lives inside a segment:

* **by format** — ``.doc`` vs ``.docx`` (antiword hard-wraps; python-docx does not);
* **by era** — old / transition / new, where *new* is the population the bar is actually
  *for*;
* **by dedup population** — all files / exact-content dedup /
  latest-version-per-position.
  The archive is ~13.5% byte-for-byte duplicate and ~8,160 files are a non-first version
  of an already-seen position (census §7a/b), so an un-deduplicated rate is weighted by
  how often a position happened to be re-saved.

This module **measures**. It does not conclude, rank, excuse or editorialise — the
analytical read of these numbers is a separate, human step. In particular: the top of
the per-rule frequency table is *a bug list, not a quality verdict*. HR-047, HR-046,
HR-055, HR-025 and HR-048 are registered live false-positive generators and are expected
near the top. Nothing here is allowed to quietly suppress them.
"""

from __future__ import annotations

import datetime as dt
import statistics
from collections import Counter
from collections.abc import Callable, Iterable, Sequence

from src.jd_bank.baseline.config import (
    POPULATIONS,
    DedupPopulation,
    get_baseline_config,
)
from src.jd_bank.baseline.models import (
    BaselineRow,
    BaselineSummary,
    HistogramBin,
    ScoreStats,
    SegmentDimension,
    SegmentStats,
)
from src.jd_core.models.quality import JDGrade
from src.jd_core.parser import PARSER_VERSION
from src.jd_core.rules import Segmentation, get_rules

#: The score scale the histogram tiles. The rulebook's own ``scoring.max_score`` is the
#: authority on the top of the scale; this is the axis it is plotted on.
SCORE_FLOOR: float = 0.0
SCORE_CEILING: float = 100.0


def histogram(scores: Iterable[float], *, bin_width: float) -> tuple[HistogramBin, ...]:
    """Tile ``[0, 100]`` at ``bin_width`` and count ``scores`` into it.

    ``lower <= score < upper``, **except** the top bin, which is closed at 100. That is
    not pedantry: a perfect 100.0 falling off the end would silently under-report the
    top of the distribution — which, in a run whose whole purpose is to ask "does the
    archive ratify a score floor of 60?", is the one end you cannot afford to lose.
    """
    edges: list[float] = []
    edge = SCORE_FLOOR
    while edge < SCORE_CEILING:
        edges.append(edge)
        edge += bin_width
    counts = [0] * len(edges)
    for score in scores:
        index = int((score - SCORE_FLOOR) // bin_width)
        counts[min(max(index, 0), len(edges) - 1)] += 1
    return tuple(
        HistogramBin(
            lower=lower, upper=min(lower + bin_width, SCORE_CEILING), count=count
        )
        for lower, count in zip(edges, counts, strict=True)
    )


def _score_stats(scores: Sequence[float], *, bin_width: float) -> ScoreStats | None:
    """The distribution — or ``None`` when there is nothing to describe.

    Never a zero. "No JD in this segment scored" and "every JD in this segment scored 0"
    are the two states the baseline most needs to keep apart, so the empty case is
    *unrepresentable* as a number rather than merely discouraged.
    """
    if not scores:
        return None
    return ScoreStats(
        n=len(scores),
        minimum=min(scores),
        median=statistics.median(scores),
        mean=statistics.fmean(scores),
        maximum=max(scores),
        histogram=histogram(scores, bin_width=bin_width),
    )


def _stats(
    rows: Sequence[BaselineRow],
    *,
    population: DedupPopulation,
    dimension: SegmentDimension,
    value: str,
    config: Segmentation,
) -> SegmentStats:
    """One slice's numbers. Frequencies count FILES, not findings — a rule firing six
    times inside one JD must not out-rank one firing once in every JD."""
    scored = [row for row in rows if row.status == "scored"]
    scores = [row.score for row in scored if row.score is not None]

    rule_files: Counter[str] = Counter()
    gate_files: Counter[str] = Counter()
    hard_gate_files: Counter[str] = Counter()
    grades: Counter[JDGrade] = Counter()
    total_findings = 0
    for row in scored:
        rule_files.update(row.rule_ids)
        gate_files.update(row.blocking_gate_ids)
        hard_gate_files.update(row.non_overridable_gate_ids)
        if row.grade is not None:
            grades[row.grade] += 1
        total_findings += row.issue_count or 0

    approved = sum(1 for row in scored if row.approved)
    return SegmentStats(
        population=population,
        dimension=dimension,
        value=value,
        n_files=len(rows),
        n_scored=len(scored),
        n_skipped=len(rows) - len(scored),
        score=_score_stats(scores, bin_width=config.score_histogram_bin),
        grades=dict(sorted(grades.items())),
        mean_issue_count=(total_findings / len(scored)) if scored else None,
        approved=approved,
        approval_rate=(approved / len(scored)) if scored else None,
        rule_frequency=dict(sorted(rule_files.items(), key=lambda kv: (-kv[1], kv[0]))),
        total_findings=total_findings,
        gate_frequency=dict(sorted(gate_files.items(), key=lambda kv: (-kv[1], kv[0]))),
        non_overridable_gate_frequency=dict(
            sorted(hard_gate_files.items(), key=lambda kv: (-kv[1], kv[0]))
        ),
    )


def _content_dedup(rows: Sequence[BaselineRow]) -> list[BaselineRow]:
    """One row per distinct sha256 — census §7a (~13.5% of the archive is a pure
    byte-for-byte copy). The first in walk order wins, so the choice is deterministic
    and re-runnable. A row with no hash at all (the bytes could not be read) cannot be
    de-duplicated and is kept: dropping it would be a silent drop."""
    seen: set[str] = set()
    kept: list[BaselineRow] = []
    for row in rows:
        if row.sha256 is None:
            kept.append(row)
            continue
        if row.sha256 in seen:
            continue
        seen.add(row.sha256)
        kept.append(row)
    return kept


def _latest_per_position(
    rows: Sequence[BaselineRow], *, config: Segmentation
) -> list[BaselineRow]:
    """The CURRENT JD for each position — the decision-relevant population.

    Census §7b: ~8,160 files are a non-first version of an already-seen position id. The
    approval bar would apply to a position's *current* JD, not to its revision history,
    so this is the population an HR reviewer would actually ratify the bar against.

    Latest = the greatest ``version_date`` (the JDFN revision date when there is one —
    see ``prefer_revision_date_for_version``), tie-broken by filename so a tie is
    resolved the same way on every machine. Files with **no** position id cannot be
    de-versioned; they are kept or dropped per ``keep_files_without_position_id`` (~7%
    of the archive, so this is not a rounding error), never silently either way.

    A file that BUNDLES several positions is attributed per ``position_id_grouping``
    (HR-116): to its ``first`` id only — the census's own method, and its own admitted
    over/under-count — or to ``all`` of them, in which case it survives if it is the
    current version for any one. Both are implemented, so the register entry pins a
    default a reviewer can actually change.
    """
    latest: dict[str, BaselineRow] = {}
    unpositioned: list[BaselineRow] = []
    for row in rows:
        if not row.position_ids:
            unpositioned.append(row)
            continue
        grouped = (
            row.position_ids
            if config.position_id_grouping == "all"
            else row.position_ids[:1]
        )
        for position_id in grouped:
            current = latest.get(position_id)
            if current is None or _version_key(row) > _version_key(current):
                latest[position_id] = row

    # Under ``all``, one bundle can be the current JD of several positions — so it would
    # appear several times. De-duplicate by path: a population is a set of FILES.
    kept = {row.path: row for row in latest.values()}
    if config.keep_files_without_position_id:
        kept |= {row.path: row for row in unpositioned}
    return sorted(kept.values(), key=lambda row: row.path)


def _version_key(row: BaselineRow) -> tuple[dt.date, str]:
    """Order two versions of one position. A row with no date at all sorts oldest —
    it cannot displace a dated JD as "the current one" on the strength of having no
    evidence."""
    return (row.version_date or dt.date.min, row.filename)


def population(
    rows: Sequence[BaselineRow],
    name: DedupPopulation,
    *,
    config: Segmentation,
) -> list[BaselineRow]:
    """The rows in one dedup population — a PURE function of ``rows`` + ``config``.

    Public, and that is the point: the summary deliberately does **not** ship a
    membership list. It would be ~33,500 filenames (~2.2 MB) in a file whose actual
    segment data is ~150 KB, and it would buy nothing — every row in ``rows.jsonl``
    carries its ``sha256``, ``position_ids`` and ``version_date``, and the config that
    grouped them is stamped on every row. So membership is fully **recomputable** from
    the artifacts, by calling this. An artifact should carry evidence, not conclusions
    it
    could re-derive.
    """
    if name == "all":
        return list(rows)
    if name == "content_dedup":
        return _content_dedup(rows)
    return _latest_per_position(rows, config=config)


#: How each mandated slice keys a row. Enumerating the VALUES from the data (rather than
#: from a hand-kept list) is what makes a format or an era nobody predicted — a
#: ``.dot``,
#: an ``unknown`` era — show up as its own segment instead of being folded into a
#: neighbour or dropped.
_DIMENSIONS: tuple[tuple[SegmentDimension, Callable[[BaselineRow], str]], ...] = (
    ("format", lambda row: row.format),
    ("era", lambda row: row.era),
    # Phase 3.4: the CUPE/WJQ population as its own facet (`wjq` vs `jdfn`; a skipped
    # row that never parsed is `unknown`). So a WJQ JD's JDFN-bar score is visible as a
    # WJQ number, never quoted inside the current-practice cohort — see
    # `current_practice_cohort` and HR-143.
    ("template", lambda row: row.template or "unknown"),
    # The BARGAINING UNIT, read from the document's CONTENT — a different question from
    # `template`, and the one readers were answering with it.
    #
    # 🔴 `template_of` returns `wjq` only for `cupe` and defaults everything else,
    # so the template facet reads as an APSA-vs-CUPE split and is not one: its `jdfn`
    # bucket
    # holds APSA, APEX, POLY, `excluded` AND every document stating no group at all —
    # about a third of the archive. Measured 2026-08-29 by reading the SOURCE FILES, 92%
    # of those genuinely name no group anywhere, so the silence is real and is REPORTED
    # here rather than defaulted away: matched, not-matched, and could-not-evaluate, the
    # rule the IT collection cost us.
    #
    # ⚠ Reads `parsed_employee_group` (content), never `employee_group` (FILENAME):
    # FINDINGS §3c measured the filename signal finding 17.7% of CUPE and 12.9% of
    # the ungrouped, so faceting on it would publish a confident wrong number.
    ("employee_group", lambda row: row.parsed_employee_group or _UNRECORDED_GROUP),
)

#: What a document that names no bargaining unit is called. Punctuated so it
#: can never be mistaken for a group SFU recognises, nor collide with a real token.
_UNRECORDED_GROUP = "(unrecorded)"

#: The eras the JDFN approval bar is judged against — the two current-template bands.
_CURRENT_PRACTICE_ERAS: frozenset[str] = frozenset({"new", "current"})

#: The gate whose firing means SFU's mandated territorial acknowledgement is ABSENT —
#: a rollout still in progress, not a quality failure (HANDOFF "one gate is a DATE
#: DETECTOR"). The current-practice cohort is the JDs on which it did NOT fire.
_TERRITORIAL_RULE_ID: str = "SFU-COMP-TERRITORIAL"

#: The template the JDFN approval bar is FOR. A WJQ (CUPE) JD scored on this bar is a
#: category error — the WJQ template has no About-SFU/territorial footer, so it
#: fails the footer gate for a reason that has nothing to do with its quality.
_WJQ_TEMPLATE: str = "wjq"


def current_practice_cohort(
    rows: Sequence[BaselineRow], *, config: Segmentation | None = None
) -> list[BaselineRow]:
    """The JDs the JDFN approval bar is actually ratified against (HANDOFF's 874).

    THREE clauses, all necessary, none of them a score threshold:

    * ``era ∈ {new, current}`` — authored under the current JDFN template, not judged
      for lacking sections that did not exist when they were written;
    * ``SFU-COMP-TERRITORIAL`` did NOT fire — SFU's mandated acknowledgement is actually
      present, so the JD is not being penalised for a rollout still in progress;
    * ``template != "wjq"`` (**Phase 3.4**), applied only when
      ``segmentation.wjq_excluded_from_current_practice`` is set (HR-143, default
      ``true``) — a WJQ/CUPE JD is on a DIFFERENT template with no About-SFU/territorial
      footer by design; scoring it on the JDFN bar is a category error, and whether CUPE
      gets a bar of its own is a deferred HR decision, not one to make by silently
      letting WJQ contaminate this cohort.

    Before the WJQ router (v1 parser), WJQ files read as ~empty and graded F, so they
    sat in the archive-wide "~5% approval" figure and never reached this cohort. The v2
    router parses them into real content — 1,011 ``new`` + 182 ``current`` WJQ files
    (MEASURED) — which is exactly why the ``template`` clause must land WITH the parser:
    without it, a third of a WJQ JD's real content would now flow into the number HR
    ratifies the JDFN bar against. Scored-only: an unscored row has no approval outcome.
    """
    cfg = config if config is not None else get_baseline_config()
    exclude_wjq = cfg.wjq_excluded_from_current_practice
    return [
        row
        for row in rows
        if row.status == "scored"
        and row.era in _CURRENT_PRACTICE_ERAS
        and _TERRITORIAL_RULE_ID not in row.rule_ids
        and not (exclude_wjq and row.template == _WJQ_TEMPLATE)
    ]


def _stamp(rows: Sequence[BaselineRow], field: str, fallback: str) -> str:
    """The stamp the ROWS carry — not whatever the current process happens to load.

    A summary that read ``get_rules().version`` would silently mis-stamp a run scored
    under a tuned rulebook (which is exactly what 2.5 invites: "the run is allowed to
    kill them"). The rows are the evidence; the summary describes them, never the other
    way round. Rows disagreeing is a bug in the runner, and it is loud.
    """
    stamps = {str(getattr(row, field)) for row in rows}
    if not stamps:
        return fallback
    if len(stamps) > 1:
        raise ValueError(
            f"rows carry {len(stamps)} different {field} values ({sorted(stamps)}) — a "
            f"single baseline cannot describe two rulebooks"
        )
    return stamps.pop()


def summarise(
    rows: Sequence[BaselineRow],
    *,
    archive_root: str,
    config: Segmentation | None = None,
    generated_at: dt.datetime | None = None,
) -> BaselineSummary:
    """Every segment of every population — the dashboard data 2.5 exists to produce.

    Pure but for the clock (pass ``generated_at`` to make it fully deterministic).
    """
    cfg = config if config is not None else get_baseline_config()
    segments: list[SegmentStats] = []

    for name in POPULATIONS:
        in_population = population(rows, name, config=cfg)
        segments.append(
            _stats(
                in_population,
                population=name,
                dimension="all",
                value="all",
                config=cfg,
            )
        )
        for dimension, key in _DIMENSIONS:
            for value in sorted({key(row) for row in in_population}):
                segments.append(
                    _stats(
                        [row for row in in_population if key(row) == value],
                        population=name,
                        dimension=dimension,
                        value=value,
                        config=cfg,
                    )
                )

    # The current-practice cohort (Phase 4.6c). Unlike everything above, this is NOT a
    # dedup population nor a per-value dimension slice — it is the ONE cross-cutting
    # population the JDFN approval bar is actually tried against (era ∈ {new, current} ∧
    # SFU-COMP-TERRITORIAL absent ∧ non-WJQ; see `current_practice_cohort`). It rides as
    # `population="all", dimension="cohort", value="current_practice"` so its n,
    # approval rate, median and grades are IN the artifact, not only derivable from it.
    # `_stats` computes them the same way as every other segment, over exactly the rows
    # `current_practice_cohort` selects — the two cannot silently diverge.
    segments.append(
        _stats(
            current_practice_cohort(rows, config=cfg),
            population="all",
            dimension="cohort",
            value="current_practice",
            config=cfg,
        )
    )

    skipped = [row for row in rows if row.status == "skipped"]
    return BaselineSummary(
        archive_root=archive_root,
        file_count=len(rows),
        scored=len(rows) - len(skipped),
        skipped=len(skipped),
        rules_version=_stamp(rows, "rules_version", get_rules().version),
        parser_version=_stamp(rows, "parser_version", PARSER_VERSION),
        config_stamp=_stamp(rows, "config_stamp", cfg.stamp),
        generated_at=(
            generated_at if generated_at is not None else dt.datetime.now(dt.UTC)
        ),
        segments=tuple(segments),
        # NB: no membership LIST. Each population size is reported in
        # its segments; who is *in* it is recomputable from `rows.jsonl` with
        # `population(rows, name, config=...)` — the rows carry the sha256, position ids
        # and version dates it needs, and the config that grouped them is stamped on
        # every one. Shipping the list would add ~2.2 MB of filenames to a ~150 KB file
        # and would let the two drift apart.
        skip_reasons=dict(
            sorted(
                Counter(row.skip_reason or "unknown" for row in skipped).items(),
                key=lambda kv: (-kv[1], kv[0]),
            )
        ),
    )

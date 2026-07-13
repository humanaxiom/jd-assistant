"""Walk the archive, run the SHIPPED validator over every file, account for every file.

The Phase 2.5 chain, and there is exactly one of it (HANDOFF 2.5 scope: "via this repo's
own ``ingest/extract.py`` + parser — do not hand-roll a second path")::

    walk_archive -> read bytes -> compute_sha256 -> extract_text
                 -> parse_jd  -> evaluate_jd_rules -> build_report -> BaselineRow

**What this run is FOR.** It is the trial of the approval bar, not of the archive. The
score floor of 60, the grade floor of C, the severity floor, the 14-rule blocking set
and the 2 non-overridable gates are ``our_invention`` — none ratified by SFU. 2.5 is the
first time they meet real data, and **the run is allowed to kill them**. So this module
*measures and segments*; it draws no conclusion, tunes nothing, and excuses nothing.

**NO SILENT DROPS.** Every file the walk finds produces exactly one
:class:`~src.jd_bank.baseline.models.BaselineRow`. Extraction failures become ledger
rows with a reason — the ``.tif``, the ``.serv``, the three ``.dot``s and any antiword
failure are themselves a finding, not noise.

**Single-process on purpose.** Measured end-to-end: ~32 ms/file for ``.doc``, ~36
ms/file for ``.docx`` -> ~8-9 minutes for all 14,565. Multiprocessing would buy nothing
and would trade determinism — the property an audit trail is *made of* — for it.
"""

from __future__ import annotations

import json
import re
import tempfile
from collections.abc import Iterable, Iterator, Sequence
from pathlib import Path
from uuid import UUID, uuid5

from src.jd_bank.baseline.config import get_baseline_config
from src.jd_bank.baseline.facets import file_facets
from src.jd_bank.baseline.models import BaselineFinding, BaselineRow, BaselineSummary
from src.jd_bank.ingest.extract import (
    MAX_DOCUMENT_BYTES,
    ExtractionError,
    extract_text,
)
from src.jd_bank.ingest.ingest import compute_sha256, walk_archive
from src.jd_core.parser import PARSER_VERSION, parse_jd
from src.jd_core.quality import build_report, evaluate_jd_rules
from src.jd_core.rules import Rules, Segmentation, get_rules

#: What the report's ``model`` / ``prompt_version`` stamps say for a run with no LLM in
#: it. ``build_report`` requires both, and "a deterministic-only run should say so
#: explicitly rather than leave them blank" (its own docstring). Phase 5 adds the LLM
#: pass; until then this is the honest value.
DETERMINISTIC_ONLY: str = "none (deterministic rules only)"

#: A stable namespace, so a file's synthetic ``job_id`` is a pure function of its name.
#: The archive has no job ids, and a random UUID per run would make two runs of the same
#: corpus incomparable row-for-row — the opposite of an audit trail.
_JOB_NAMESPACE: UUID = UUID("6ba7b812-9dad-11d1-80b4-00c04fd430c8")

#: Any path under the system temp dir, as it appears inside an exception message.
_TMPFILE = re.compile(re.escape(tempfile.gettempdir()) + r"[/\\]\S+")

#: A CPython object repr — ``<_io.BytesIO object at 0x7f...>``. The address is the
#: process's heap layout, not a fact about the JD, and it is different every run.
_OBJ_ADDR = re.compile(r"<([\w.]+) object at 0x[0-9a-fA-F]+>")


def _stable_reason(exc: Exception) -> str:
    """``exc`` as a ledger reason that is the SAME on every run.

    Two sources of per-run noise leak into extractor exception messages, and BOTH have
    to go or the ledger is not an audit trail:

    1. ``extract._extract_doc`` writes the bytes to a ``NamedTemporaryFile`` before
       handing them to antiword, so a failure message names it::

           antiword failed: /tmp/tmp0k444cks.doc is not a Word Document

    2. ``extract._extract_docx`` hands python-docx a ``BytesIO``, and python-docx puts
       its **repr** in the message — which carries a heap address::

           docx parse failed: file '<_io.BytesIO object at 0x7917efaa0590>' is not a
           Word file, content type is 'application/vnd.ms-word.document.macroEnabled...'

    Both are freshly random every run. Left in, they would (a) make ``rows.jsonl`` and
    ``summary.json`` byte-different on two runs over the *same* archive — destroying
    the reproducibility an audit trail is made of — and (b) shatter the grouped skip
    ledger, so files that failed for one identical reason would each report as their
    own unique reason with a count of 1. Measured over the full archive: 11 files name
    the temp path (largest group that would shatter: 9), and 1 names a heap address.

    (2) was missed when (1) was fixed, and it outlived a "verified byte-identical
    across two runs" claim. Both are artefacts of **our own** plumbing and say nothing
    about the JD, so scrubbing them discards no evidence. The rest survives verbatim.
    """
    reason = _TMPFILE.sub("<tmpfile>", f"{type(exc).__name__}: {exc}")
    return _OBJ_ADDR.sub(r"<\1>", reason)


def _row(
    path: Path, config: Segmentation, rules: Rules, **outcome: object
) -> BaselineRow:
    """This file's identity + segmentation + stamps, plus whatever the run made of it.

    Every row is built here, so no code path — least of all the failure paths — can emit
    one that forgot to say which rules produced it and which population it belongs to.
    """
    facets = file_facets(path, config)
    return BaselineRow(
        path=path.as_posix(),
        filename=path.name,
        extension=facets.extension,
        format=facets.format.value,
        era=facets.era,
        template_token=facets.template_token,
        employee_group=facets.employee_group,
        position_id=facets.position_id,
        position_ids=facets.position_ids,
        file_date=facets.file_date,
        revision_date=facets.revision_date,
        version_date=facets.version_date,
        rules_version=rules.version,
        parser_version=PARSER_VERSION,
        config_stamp=config.stamp,
        **outcome,
    )


def evaluate_file(
    path: Path,
    *,
    config: Segmentation | None = None,
    rules: Rules | None = None,
) -> BaselineRow:
    """Score ONE archive file through the shipped chain. Total on bad *input*.

    A bad file is a *result* here, not an exception — the run must reach file 14,565.
    But only the two failures that are genuinely about the FILE are caught (see
    :data:`~src.jd_bank.baseline.models.SkipStage`): unreadable/oversized bytes, and a
    failed extraction.

    ``parse_jd`` is documented total ("never raises") and ``evaluate_jd_rules`` is pure
    over its output, so if either raises, that is **a bug in us**. It propagates and
    stops the run rather than being laundered into a tidy ledger entry — Phase 2.3's
    reviewer found a validator that *crashed on real archive input*, and a runner that
    swallowed that would have published a clean baseline over a broken validator.
    """
    cfg = config if config is not None else get_baseline_config()
    rulebook = rules if rules is not None else get_rules()
    fmt = file_facets(path, cfg).format

    try:
        # STAT BEFORE READ, exactly as `extract_text_from_path` does. `extract_text`
        # also enforces the cap — but only *after* the bytes are already in memory, so
        # reading first would hand a 50 MiB+ document straight past the DoS guard the
        # extractor deliberately added.
        #
        # Not hypothetical. MEASURED: exactly one archive file exceeds the cap —
        # `19980120_19980120_00000293_Asst_to_Director,_Rec_Services.rtf`, 89,397,431
        # bytes. Note it is an `.rtf`, not a `.doc`: it maps to `DocumentFormat.RTF` and
        # we DO have an extractor for it, so this is a file we could otherwise read. It
        # is skipped on size alone, and it segments as `format: rtf` in the ledger.
        size = path.stat().st_size
        if size > MAX_DOCUMENT_BYTES:
            return _row(
                path,
                cfg,
                rulebook,
                status="skipped",
                skip_stage="read",
                # No sha256: the point is that the bytes are never read. The row is
                # still segmented and counted — an oversized file is a FINDING, not
                # a drop.
                byte_size=size,
                skip_reason=(
                    f"DocumentTooLargeError: {size} bytes exceeds the extractor's cap "
                    f"of {MAX_DOCUMENT_BYTES} bytes (not read)"
                ),
            )
        data = path.read_bytes()
    except OSError as exc:
        return _row(
            path,
            cfg,
            rulebook,
            status="skipped",
            skip_stage="read",
            skip_reason=_stable_reason(exc),
        )

    sha256 = compute_sha256(data)

    try:
        text = extract_text(data, fmt)
    except ExtractionError as exc:
        # UnsupportedFormatError (.tif/.serv/.dot -> DocumentFormat.OTHER), a corrupt
        # .docx, an antiword failure or timeout. Hashed and segmented anyway: the ledger
        # is read BY ERA AND BY FORMAT (that is where a pattern would be), and the
        # exact-content dedup population must be able to see the duplicates among the
        # failures too.
        return _row(
            path,
            cfg,
            rulebook,
            status="skipped",
            skip_stage="extract",
            skip_reason=_stable_reason(exc),
            sha256=sha256,
            byte_size=len(data),
        )

    parsed = parse_jd(text)
    issues = evaluate_jd_rules(parsed.jd, text, rules=rulebook)
    report = build_report(
        job_id=uuid5(_JOB_NAMESPACE, path.name),
        issues=issues,
        model=DETERMINISTIC_ONLY,
        prompt_version=DETERMINISTIC_ONLY,
        rules=rulebook,
    )
    decision = report.gate_decision
    if decision is None:  # pragma: no cover - build_report always computes one
        raise RuntimeError(f"build_report returned no gate decision for {path}")

    return _row(
        path,
        cfg,
        rulebook,
        status="scored",
        sha256=sha256,
        byte_size=len(data),
        body_era=parsed.era,
        parse_confidence=parsed.parse_confidence,
        char_count=len(text),
        score=report.overall_score,
        grade=report.grade,
        issue_count=report.issue_count,
        rule_ids=tuple(
            sorted({i.rule_id for i in report.issues if i.rule_id is not None})
        ),
        findings=tuple(
            BaselineFinding(
                rule_id=issue.rule_id,
                category=issue.category,
                severity=issue.severity,
                evidence=(
                    issue.evidence[: cfg.evidence_max_chars]
                    if issue.evidence is not None
                    else None
                ),
            )
            for issue in report.issues
        ),
        approved=decision.approved,
        blocking_gate_ids=tuple(sorted(r.gate_id for r in decision.blocking)),
        non_overridable_gate_ids=tuple(
            sorted(r.gate_id for r in decision.blocking if not r.overridable)
        ),
    )


def select(
    paths: Sequence[Path], *, limit: int | None = None, sample: int | None = None
) -> list[Path]:
    """The files to run, chosen deterministically.

    ``limit`` takes the first N of the sorted walk. ``sample`` spreads N *evenly* across
    it — and since the archive sorts by its ``YYYYMMDD`` filename prefix, an evenly
    spaced sample spans eras and formats by construction. No RNG and no seed: whoever
    re-runs it gets the same files, which is the only kind of sample worth quoting in a
    report.

    A non-positive ``limit``/``sample`` is a usage error, not "run everything". On a
    14,565-file corpus ``--sample 0`` used to fall straight through to a full 9-minute
    run whose output was then read as a *sample* — a quiet mis-scoping of exactly the
    kind this phase's artifacts must not carry.

    Raises:
        ValueError: ``limit`` or ``sample`` is not positive.
    """
    for name, value in (("limit", limit), ("sample", sample)):
        if value is not None and value <= 0:
            raise ValueError(
                f"--{name} must be a positive number of files, got {value}"
            )
    if sample is not None:
        if sample >= len(paths):
            return list(paths)
        step = len(paths) / sample
        return [paths[int(index * step)] for index in range(sample)]
    if limit is not None:
        return list(paths[:limit])
    return list(paths)


def run_baseline(
    archive_root: Path,
    *,
    config: Segmentation | None = None,
    rules: Rules | None = None,
    limit: int | None = None,
    sample: int | None = None,
) -> Iterator[BaselineRow]:
    """Every selected file under ``archive_root``, as exactly one row each.

    Raises:
        FileNotFoundError: the root is not a directory, or holds no files. The compose
            service binds ``${JD_ARCHIVE_PATH:-./archive}``; an unset variable would
            otherwise bind an *empty* directory, and the run would emit a confident,
            fully-stamped baseline of nothing at all.
    """
    if not archive_root.is_dir():
        raise FileNotFoundError(f"archive root {archive_root} is not a directory")
    paths = list(walk_archive(archive_root))
    if not paths:
        raise FileNotFoundError(
            f"archive root {archive_root} contains no files — point JD_ARCHIVE_PATH at "
            f"the SFU JD archive root"
        )

    cfg = config if config is not None else get_baseline_config()
    rulebook = rules if rules is not None else get_rules()
    for path in select(paths, limit=limit, sample=sample):
        yield evaluate_file(path, config=cfg, rules=rulebook)


def _write_summary(path: Path, summary: BaselineSummary) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(json.loads(summary.model_dump_json()), indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _write_rows(path: Path, rows: Iterable[BaselineRow]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(row.model_dump_json() + "\n")


def write_artifacts(
    out_dir: Path,
    *,
    rows: Sequence[BaselineRow],
    summary: BaselineSummary,
    commit_dir: Path | None = None,
) -> tuple[Path, ...]:
    """Write the run's artifacts. Returns every path it wrote.

    Into ``out_dir`` (gitignored ``/out``), all three:

    ``rows.jsonl``    one line per file, scored **or** skipped — so "every one of the
                      14,565 files is accounted for" is checkable with ``wc -l`` rather
                      than on trust. This is the raw evidence.
    ``errors.jsonl``  the skipped subset, for triage.
    ``summary.json``  the segmented dashboard data.

    Into ``commit_dir`` (``docs/baseline/``), the two that are **committed** — because
    an
    audit trail that only exists in an ignored directory is not an audit trail:

    * ``summary.json`` — every number the written read is based on, stamped with the
      rules, parser and segmentation identities that produced it.
    * ``errors.jsonl`` — small, and the skip ledger IS a finding. Read it rather than
      trusting a summary of it: on the full archive it holds 43 files, the largest group
      being 22 ``.docx`` python-docx cannot open, then 9 ``.doc``-named files that are
      really RTF (a format we *have* a backend for), 3 damaged ``.doc``, an 89 MB
      ``.rtf`` over the extractor's cap, the ``.tif`` and the ``.serv``.

    ``rows.jsonl`` is deliberately **not** committed: 14,565 rows carrying evidence
    snippets is a bulk derived copy of the corpus, and the ``fixtures/golden/``
    precedent
    is for *curated* fixtures, not a dump. Nothing is lost — every aggregate in
    ``summary.json`` is reproducible from it by re-running, and population membership is
    recomputable with :func:`~src.jd_bank.baseline.aggregate.population`.
    """
    rows_path = out_dir / "rows.jsonl"
    errors_path = out_dir / "errors.jsonl"
    summary_path = out_dir / "summary.json"
    skipped = [row for row in rows if row.status == "skipped"]

    _write_rows(rows_path, rows)
    _write_rows(errors_path, skipped)
    _write_summary(summary_path, summary)
    written = [rows_path, errors_path, summary_path]

    if commit_dir is not None:
        committed_summary = commit_dir / "summary.json"
        committed_errors = commit_dir / "errors.jsonl"
        _write_summary(committed_summary, summary)
        _write_rows(committed_errors, skipped)
        written += [committed_summary, committed_errors]

    return tuple(written)

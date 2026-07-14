"""What one run of the archive ingest driver did.

Mirrors :mod:`src.jd_bank.dedup.models`: a plain frozen dataclass, no pydantic and no
database — the driver (:mod:`src.jd_bank.ingest.driver`) is the only thing that
constructs it, and the CLI (:mod:`src.jd_bank.ingest.__main__`) only reads it.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SkipEntry:
    """One file this run could not carry through to a parse — the archive path (not
    the JD content) and a :func:`~src.jd_bank.stable_reason.stable_reason`-scrubbed
    explanation, so the ledger reproduces byte-for-byte across runs."""

    storage_ref: str
    reason: str


@dataclass(frozen=True, slots=True)
class IngestResult:
    """Counts for one run of :func:`~src.jd_bank.ingest.driver.run_archive_ingest`.

    Every counter below answers "did THIS run do X to this file", not "is this file
    currently in state X" — so a re-run over an already-ingested-and-parsed archive
    reports ``ingested=0`` and ``parsed=0`` (the idempotency guarantee, stated as a
    number), with every file instead landing in :attr:`already_done`. The one
    exception is :attr:`failed`: an unrecoverable file is worth re-reporting on every
    run, not just the run that first discovered it, so it is counted from the row's
    current status regardless of whether that row is new this run.

    ``files_seen`` is a total, not a partition — a freshly-ingested-and-freshly-parsed
    file increments both :attr:`ingested` and :attr:`parsed`, so the four action
    counters need not sum to it.
    """

    #: Total files the walk selected this run (after ``limit``, before any skip).
    files_seen: int = 0
    #: ``source_documents`` rows this run created via a SUCCESSFUL extraction — i.e.
    #: the row did not already exist, and its format extracted cleanly. Does NOT
    #: include newly-created ``failed``/``unsupported`` rows (see :attr:`failed`).
    ingested: int = 0
    #: ``parsed_jds`` rows this run created. Zero on any run over an archive whose
    #: every document is already ingested AND already parsed at the current parser
    #: version — the idempotency guarantee LANDMINE 1 exists to hold.
    parsed: int = 0
    #: Files needing NO work this run: already ingested (status ``ingested``) AND
    #: already carrying a ``parsed_jds`` row for the current parser version.
    already_done: int = 0
    #: Files this run could not carry through to a parse. Three kinds, and they are NOT
    #: all the same shape in the database:
    #:
    #: * extraction failed, or the format has no backend -> a ``source_documents`` row
    #:   with status ``failed`` / ``unsupported``;
    #: * the file is over the extractor's size cap -> a row with status ``failed``,
    #:   carrying a real ``stream_sha256`` digest (too big to *extract* is not too big
    #:   to *record*);
    #: * the bytes could not be read AT ALL (``OSError`` — permissions, a vanished
    #:   file) -> **no row**, because there is nothing to hash and the
    #:   ``(storage_ref, sha256)`` key is genuinely unsatisfiable. Counted and
    #:   ledgered here, never dropped. Zero files in the 2.5 archive ledger hit this.
    #:
    #: Counted from this run's read of the file, whether the row is new or pre-existing
    #: — an unrecoverable file is worth re-surfacing on every run, not only on the run
    #: that first found it. That is why this counter, alone, is not "new this run only".
    failed: int = 0
    #: One entry per file counted in :attr:`failed` — including the row-less ``OSError``
    #: case above — each with a reproducible reason. The evidence behind the count.
    skipped: tuple[SkipEntry, ...] = ()

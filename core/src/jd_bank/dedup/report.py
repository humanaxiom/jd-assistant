"""The Tier-1 finding over a whole corpus, as a committed artifact.

**It does not walk the archive.** HANDOFF is explicit — *"do not hand-roll a second
path"* — and there is already exactly one chain that reads the SFU archive through this
repo's own extractor: the Phase 2.5 baseline. Its ``rows.jsonl`` already carries a
``sha256`` (from ``ingest.compute_sha256``, the same function ``ingest_document`` uses),
a ``filename`` and a ``byte_size`` for **every one of the 14,565 files**. So the report
reads *that*, and calls the *same* :func:`~src.jd_bank.dedup.tier1.group_by_sha256` the
database pass calls.

The consequence worth having: the report's numbers are not a second implementation that
happens to agree with the pass — they are the edges the pass **would write**, computed
by the pass's own code. The only thing the report substitutes is the document id, which
the database has not assigned yet: :meth:`DocumentRef.for_path` derives a stable
``uuid5`` from the archive path instead (the baseline runner's own trick for its
synthetic ``job_id``).

Regenerate with ``make dedup`` (after ``make baseline``, whose output it reads).
"""

from __future__ import annotations

import datetime as dt
import json
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path

from src.jd_bank.baseline.models import BaselineRow
from src.jd_bank.dedup.models import DedupReport, DocumentRef, GroupSample
from src.jd_bank.dedup.tier1 import edge_counts, exact_edges, group_by_sha256
from src.jd_core.rules import Rules, get_rules

#: How many of the biggest groups the committed artifact names. Enough to *see* the tail
#: (the archive's largest group is 11), few enough that the artifact stays a summary.
DEFAULT_TOP_GROUPS: int = 20


def refs_from_baseline_rows(rows: Iterable[BaselineRow]) -> list[DocumentRef]:
    """Baseline rows -> Tier-1 refs. Unhashed rows are **kept** (id-less content cannot
    be grouped, but a file that could not be read is still a file, and the report counts
    it) — they are given an empty ``sha256`` and filtered out of the grouping by
    :func:`build_dedup_report`, never dropped on the way in."""
    return [
        DocumentRef.for_path(row.path, sha256=row.sha256 or "", filename=row.filename)
        for row in rows
    ]


def read_baseline_rows(path: Path) -> list[BaselineRow]:
    """``rows.jsonl`` -> rows. Raises ``FileNotFoundError`` with the fix in the message:
    a dedup report over an archive nobody has walked is a report of nothing."""
    if not path.is_file():
        raise FileNotFoundError(
            f"{path} does not exist — the dedup report reads the BASELINE's row dump "
            f"rather than walking the archive a second time. Run `make baseline "
            f"JD_ARCHIVE_PATH=<archive>` first."
        )
    with path.open(encoding="utf-8") as handle:
        return [
            BaselineRow.model_validate_json(line) for line in handle if line.strip()
        ]


def positions_from_baseline_rows(
    rows: Iterable[BaselineRow],
) -> dict[str, tuple[str, ...]]:
    """``storage_ref -> the position ids the filename encodes`` (a file may bundle
    several). Keyed by ``path``, which is what :func:`refs_from_baseline_rows` uses as
    the ``storage_ref``, so the two line up by construction."""
    return {row.path: row.position_ids for row in rows}


def build_dedup_report(
    refs: Sequence[DocumentRef],
    *,
    source: str,
    rules: Rules | None = None,
    top_groups: int = DEFAULT_TOP_GROUPS,
    byte_sizes: dict[str, int] | None = None,
    positions: Mapping[str, tuple[str, ...]] | None = None,
    generated_at: dt.datetime | None = None,
) -> DedupReport:
    """The whole Tier-1 finding for ``refs``. Pure but for the clock.

    ``positions`` (``storage_ref -> position ids``) is what turns "13.5% of the archive
    is duplicated" into the finding that actually matters: **are these re-saves of one
    position, or different positions sharing one JD?** Omit it and every group counts as
    ``groups_without_position_id`` — an honest "not measured", never a silent zero.
    """
    rulebook = rules if rules is not None else get_rules()
    hashed = [ref for ref in refs if ref.sha256]
    groups = group_by_sha256(hashed)
    star, clique = edge_counts(groups)
    at_topology = len(exact_edges(groups, rules=rulebook))

    files_in_groups = sum(group.size for group in groups)
    redundant = sum(group.redundant for group in groups)
    sizes = Counter(group.size for group in groups)
    # Biggest first; ties by hash, so the sample is stable between runs.
    ranked = sorted(groups, key=lambda group: (-group.size, group.sha256))

    # A group's positions = the union over its members. Three outcomes, kept apart:
    # several positions (real redundancy), one position (a re-save), or none at all.
    known = positions or {}
    multi = single = unpositioned = files_multi = 0
    for group in groups:
        ids = {
            position
            for member in group.members
            for position in known.get(member.storage_ref, ())
        }
        if len(ids) > 1:
            multi += 1
            files_multi += group.size
        elif len(ids) == 1:
            single += 1
        else:
            unpositioned += 1

    return DedupReport(
        source=source,
        generated_at=(
            generated_at if generated_at is not None else dt.datetime.now(dt.UTC)
        ),
        total_documents=len(refs),
        hashed=len(hashed),
        unhashed=len(refs) - len(hashed),
        distinct_sha256=len({ref.sha256 for ref in hashed}),
        group_count=len(groups),
        files_in_groups=files_in_groups,
        redundant_files=redundant,
        redundancy_rate=(redundant / len(hashed)) if hashed else 0.0,
        group_size_distribution=dict(sorted(sizes.items())),
        largest_group_size=max((group.size for group in groups), default=0),
        groups_spanning_multiple_positions=multi,
        groups_within_one_position=single,
        groups_without_position_id=unpositioned,
        files_in_multi_position_groups=files_multi,
        biggest_groups=tuple(
            GroupSample(
                sha256=group.sha256,
                size=group.size,
                byte_size=(byte_sizes or {}).get(group.sha256),
                filenames=tuple(
                    member.filename or member.storage_ref for member in group.members
                ),
            )
            for group in ranked[:top_groups]
        ),
        edges_star=star,
        edges_clique=clique,
        topology=rulebook.comparison.exact_edge_topology,
        edges_at_topology=at_topology,
        rules_version=rulebook.version,
    )


def write_report(report: DedupReport, path: Path) -> Path:
    """Write ``report`` as pretty JSON with a trailing newline (the ``summary.json``
    convention the baseline already commits)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(json.loads(report.model_dump_json()), indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return path


def write_groups(refs: Sequence[DocumentRef], path: Path) -> Path:
    """Every duplicate group, one JSON line each, with every member filename.

    The **raw evidence**, and deliberately NOT committed — it names ~3,009 archive
    files, which is a bulk derived index of a read-only corpus that lives outside the
    repo (the same call ``rows.jsonl`` gets). It goes to the gitignored ``/out``, and
    the committed ``summary.json`` names only the biggest groups.
    """
    groups = group_by_sha256([ref for ref in refs if ref.sha256])
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for group in groups:
            handle.write(
                json.dumps(
                    {
                        "sha256": group.sha256,
                        "size": group.size,
                        "redundant": group.redundant,
                        "representative": group.representative.storage_ref,
                        "members": [member.storage_ref for member in group.members],
                    }
                )
                + "\n"
            )
    return path

"""Walk the archive, probe each identification field, and compare with what was stored.

⚠ **This reads the SOURCE FILES, not the database.** Both `employee_group` defects were
invisible in `parsed_jds` and obvious in the archive; the title defect was too. The
database is one side of the comparison here, never the evidence.

Postgres for the stored side, the archive bind for the truth side. Writes no row.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterator, Sequence
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.jd_bank.baseline.runner import select
from src.jd_bank.field_audit.models import (
    FieldAuditSummary,
    FieldOutcome,
    GapExample,
    GroupAudit,
)
from src.jd_bank.field_audit.probe import (
    FieldSpec,
    Readability,
    identification_block,
    probe_field,
)
from src.jd_bank.ingest.extract import extract_text_from_path
from src.jd_bank.ingest.ingest import walk_archive
from src.jd_core.parser import PARSER_VERSION
from src.jd_core.parser import headings as hd
from src.jd_core.rules.loader import Rules, WjqIdField

#: The fields read from a LABEL, and therefore visible to this probe. `title` is here as
#: the CONTROL: its answer is already known (P3a recovered 805 of them), so a run that
#: reports title as badly broken is measuring its own matching rule, not the archive.
_LABELLED_FIELDS: tuple[WjqIdField, ...] = (
    "title",
    "department",
    "position_number",
    "grade",
)

#: Published rather than omitted — a filter must report what it cannot see.
_NOT_EVALUATED = {
    "classification": (
        "Not read from a label at all: `parser/classification.py` pulls it with "
        "hardcoded regexes (`_CUPE_GRADE_RX`, `_JDFN_GRADE_APPROVED_RX`, "
        "`_JDFN_GRADE_FIELD_RX`) that are not rulebook data. A label probe says "
        "NOTHING "
        "about it, so it is reported as unevaluated rather than as clean. ⚠ Those "
        "regexes being hardcoded is itself a rulebook-as-data gap."
    ),
}

#: What the parser stored, per source document, at the CURRENT version only. A stale
#: version would compare this archive against a different one — v6→v7 moved 805 titles.
_STORED = f"""
    SELECT d.filename,
           coalesce(p.parsed->>'employee_group', '(unrecorded)') AS employee_group,
           nullif(p.parsed->>'title', '')            AS title,
           nullif(p.parsed->>'department', '')       AS department,
           nullif(p.parsed->>'position_number', '')  AS position_number,
           nullif(p.parsed->>'grade', '')            AS grade
    FROM parsed_jds p
    JOIN source_documents d ON d.id = p.source_document_id
    WHERE p.parser_version = '{PARSER_VERSION}'
"""


def _stored_has_value(row: dict[str, str | None], field: str) -> bool:
    """Whether the parser stored a real value — checking the SENTINEL, not emptiness.

    🔴 `title <> ''` reports 100% coverage over documents that have no title, because
    the parser writes a PLACEHOLDER. That false all-clear was produced during the very
    investigation that then found it, so it is closed here by value.
    """
    from src.jd_core.parser import FALLBACK_TITLE

    value = row.get(field)
    return bool(value) and value != FALLBACK_TITLE


#: Broad DISCOVERY terms per field — over-inclusive on purpose, and separate from the
#: registered spellings that decide READABILITY. Conflating the two is what made the
#: first run of this audit contradict the parser on 129 of 129 APSA documents.
_KEY_WORDS: dict[WjqIdField, tuple[str, ...]] = {
    "title": ("title",),
    "department": ("department", "unit"),
    "position_number": ("position number", "position no", "position #"),
    "grade": ("grade",),
}

#: Names that belong to ANOTHER field. MEASURED from this probe's own verbatim output:
#: `Department Position Title` is the TITLE field and was claimed as an unreadable
#: DEPARTMENT 31 times; `Evaluating Supervisor's Position Title` and `Position Reports
#: To (Title)` are a different position's title entirely and must never be read as this
#: job's. Stated as exclusions rather than settled by ranking key words, because the
#: exclusion IS the claim: this name is not this field.
_EXCLUDE: dict[WjqIdField, tuple[str, ...]] = {
    "title": ("supervisor", "reports to", "report to", "incumbent"),
    "department": ("title",),
    "position_number": (),
    "grade": (),
}

#: The MODERN template's label readers. Hardcoded regexes in `parser/headings.py`, NOT
#: rulebook data — which is the second provenance, and a rulebook-as-data gap in itself.
_MODERN_RX = {
    "title": hd.TITLE_LABEL_RX,
    "department": hd.DEPARTMENT_LABEL_RX,
    "position_number": hd.POSITION_NO_LABEL_RX,
    "grade": hd.GRADE_LABEL_RX,
}


def _specs(rules: Rules) -> dict[WjqIdField, FieldSpec]:
    """How to find each field, and who can already read it.

    The WJQ spellings come from the RULEBOOK rather than being restated here: a probe
    carrying its own copy of the label list would keep agreeing with itself after
    someone fixed the real one.
    """
    id_labels = rules.wjq.id_labels
    return {
        field: FieldSpec(
            key_words=_KEY_WORDS[field],
            wjq_labels=tuple(id_labels[field]),
            modern_rx=_MODERN_RX[field],
            exclude=_EXCLUDE[field],
        )
        for field in _LABELLED_FIELDS
    }


def _iter_documents(
    archive_root: Path, *, sample: int | None
) -> Iterator[tuple[str, str]]:
    """``(filename, extracted text)`` for each selected archive file.

    A file that will not extract is SKIPPED and counted, never silently dropped: an
    unreadable document is a different fact from a document that states nothing.
    """
    paths: Sequence[Path] = list(walk_archive(archive_root))
    if not paths:
        raise FileNotFoundError(
            f"archive root {archive_root} contains no files — point JD_ARCHIVE_PATH at "
            "the SFU JD archive root"
        )
    for path in select(list(paths), sample=sample):
        try:
            yield path.name, extract_text_from_path(path)
        except Exception:  # noqa: BLE001 — one bad file must not abort the audit
            yield path.name, ""


async def run_field_audit(
    session: AsyncSession,
    archive_root: Path,
    *,
    rules: Rules,
    sample: int | None = None,
    evidence: int = 0,
    identification_only: bool = False,
) -> FieldAuditSummary:
    """Audit every labelled identification field against the raw archive."""
    stored = {
        row["filename"]: row
        for row in (
            dict(r) for r in (await session.execute(text(_STORED))).mappings().all()
        )
    }
    specs = _specs(rules)

    counters: dict[str, dict[str, Counter[str]]] = defaultdict(
        lambda: defaultdict(Counter)
    )
    group_documents: Counter[str] = Counter()
    unreadable_names: dict[str, Counter[str]] = defaultdict(Counter)
    gap_examples: list[GapExample] = []
    read = skipped = 0

    for filename, body in _iter_documents(archive_root, sample=sample):
        row = stored.get(filename)
        if row is None or not body:
            # Not parsed at the current version, or unreadable. Either way it is not a
            # comparison — counting it as "the document states nothing" would invent a
            # finding out of a file we never opened.
            skipped += 1
            continue
        # 🔴 P3d: the PARSER reads only the identification block. Probing the whole
        # document counts fields the parser had no access to — "the archive states it"
        # is a different question from "a fix would recover it".
        if identification_only:
            body = identification_block(body, rules=rules)
            if not body:
                skipped += 1  # could not scope: no WJQ identification heading
                continue
        read += 1
        group = str(row["employee_group"])
        group_documents[group] += 1

        for field, spec in specs.items():
            bucket = counters[group][field]
            if _stored_has_value(row, field):
                bucket["parser_has_value"] += 1

            hit = probe_field(body, spec, cells=True)
            if hit is None:
                bucket["no_label_found"] += 1
            elif not hit.states_a_value:
                bucket["label_present_no_value"] += 1
            elif hit.readability is Readability.UNREADABLE:
                bucket["unreadable_with_value"] += 1
                unreadable_names[field][hit.field_name] += 1
            else:
                bucket["readable_with_value"] += 1
                # 🔴 THE GAP, file by file: the archive states a value under a name
                # the parser CAN read, and the parser stored nothing. An aggregate is
                # not a finding until these have been opened.
                if len(gap_examples) < evidence and not _stored_has_value(row, field):
                    gap_examples.append(
                        GapExample(
                            filename=filename,
                            employee_group=group,
                            field=field,
                            field_name=hit.field_name,
                            document_value=hit.value[:120],
                        )
                    )

    by_group = {
        group: GroupAudit(
            employee_group=group,
            documents=group_documents[group],
            fields={
                field: FieldOutcome(
                    wjq_labels=specs[field].wjq_labels,
                    key_words=specs[field].key_words,
                    excluded_terms=specs[field].exclude,
                    documents=group_documents[group],
                    parser_has_value=counters[group][field]["parser_has_value"],
                    unreadable_with_value=counters[group][field][
                        "unreadable_with_value"
                    ],
                    readable_with_value=counters[group][field]["readable_with_value"],
                    label_present_no_value=counters[group][field][
                        "label_present_no_value"
                    ],
                    no_label_found=counters[group][field]["no_label_found"],
                )
                for field in specs
            },
        )
        for group in sorted(group_documents)
    }

    return FieldAuditSummary(
        parser_version=PARSER_VERSION,
        documents_read=read,
        sampled=sample,
        documents_skipped=skipped,
        by_group=by_group,
        unreadable_examples={
            field: counter.most_common(10)
            for field, counter in unreadable_names.items()
        },
        gap_examples=gap_examples,
        not_evaluated=_NOT_EVALUATED,
    )

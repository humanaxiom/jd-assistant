"""What the reviewer is told about content the rewrite LOST and the guard PUT BACK.

Non-negotiable #6, read from the reviewer's end (2026-10-21). Since HR-269…HR-271 the
4.2a guard folds a source duty's lost sentences back into the draft
(``folded_duty_content``) and restores lost Decision Making / Problem Solving /
Relationships / Qualification items (``restored_items``), verbatim. They then sat in the
draft **indistinguishable from the model's own wording**, and the "removed content"
panel listed only what was NOT in the draft — so nothing told a reviewer which lines of
a duty were the model's and which the source documents'. This module turns the stored
anti-fabrication record into:

* :func:`restored_view` — every restored piece with the section it is in, the rewritten
  duty it sits under, and (when the record carries it, since 2026-10-21) the source duty
  it came from and the source documents that state that duty;
* :func:`mark_restored` — the rendered draft cut into segments, restored text flagged,
  so the page can mark it inline (the template escapes every segment; nothing here is
  markup);
* :data:`REMOVED_REASON_LABELS` — one plain sentence per change-log reason, in place of
  the raw ``[item_dropped_by_rewrite · decision_making]`` codes the page showed.

**Everything is read from what is already stored** (``canonical_jds.change_log`` and
``content``): a draft produced before this module existed renders its restored content
the same way, with no re-run of the model. Pure: no I/O, no rulebook lookups (the caller
passes the section labels), no ``jd_bank`` import.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final, get_args

from pydantic import ValidationError

from src.jd_core.models.bank import AntiFabricationRecord, RemovedReason
from src.jd_core.parser.headings import CANONICAL_HEADING, SectionKey

#: One sentence per :data:`~src.jd_core.models.bank.RemovedReason`, in HR's terms. A
#: display string, not a decision: it changes no verdict and no stored value. A test
#: holds it to the full reason set, so a new reason cannot reach the page as a code.
REMOVED_REASON_LABELS: Final[Mapping[str, str]] = {
    "duty_deduplicated": (
        "A near-identical duty from another source document was kept in its place."
    ),
    "duty_dropped_over_max": (
        "Left out because the source documents state more duties than the form holds."
    ),
    "section_not_merged": (
        "From a section of one source document that the combined draft does not carry."
    ),
    "qualification_scrubbed_ungrounded": (
        "A qualification the rewrite wrote that no source document supports, so it "
        "was removed."
    ),
    "duty_removed_by_rewrite": (
        "The rewrite has no duty close to this source duty; any of its content that "
        "was lost is put back in the draft or listed here separately."
    ),
    "qualification_bar_restored": (
        "An education, experience or security requirement the rewrite changed; the "
        "source documents' own requirement was kept instead."
    ),
    "how_why_scrubbed_ungrounded": (
        "A how/why point the rewrite wrote that no source duty supports, so it was "
        "removed."
    ),
    "item_scrubbed_ungrounded": (
        "A point the rewrite wrote that this section of the source documents does not "
        "support, so it was removed."
    ),
    "item_dropped_by_rewrite": (
        "Stated in this section of the source documents, left out by the rewrite and "
        "not put back — add it if it belongs to the role."
    ),
    "duty_content_dropped_by_rewrite": (
        "Stated in a source duty, left out by the rewrite and not put back (no related "
        "duty to file it under and no room for a duty of its own, or it carries a form "
        "placeholder) — add it if it belongs to the role."
    ),
    "form_text_stripped": (
        "Set aside before the rewrite as questionnaire instructions or SFU's standard "
        "wording — check it is not part of the role."
    ),
    "form_instruction_stripped": (
        "The old job-description questionnaire's instructions to the person filling "
        "it in — not part of the role, so set aside."
    ),
    "boilerplate_stripped": (
        "SFU's standard wording (About SFU, territorial acknowledgement or employment "
        "equity), which the form supplies itself — set aside."
    ),
    "boilerplate_matched_in_role_content": (
        "Matched SFU's standard wording (territorial acknowledgement, About SFU or "
        "employment equity) and was set aside — check it is not part of the role."
    ),
    "page_header_stripped": (
        "A page header or footer of the source document (its position number, page "
        'number or "Continued") that was read into the text — not part of the role, '
        "so set aside."
    ),
    "rewrite_over_form_limit": (
        "The rewrite wrote more than the form holds here, so this was left out; any "
        "source content it carried is put back in the draft or listed separately."
    ),
}

#: Shown for a reason this build does not know (a packet from a newer build). Never a
#: raw code, and never an error on the page a JD is approved on.
_UNKNOWN_REASON: Final[str] = "Not in the draft."

#: The sections a restored piece can be in, in template order (``SECTION_ORDER``).
_RESTORABLE_SECTIONS: Final[tuple[str, ...]] = (
    "duties",
    "decision_making",
    "problem_solving",
    "relationships",
    "qualifications",
)

#: How many source-document titles one restored duty names before "and N more".
_TITLES_SHOWN: Final[int] = 3


def removed_reason_label(reason: str) -> str:
    """The plain-language sentence for a change-log ``reason``."""
    return REMOVED_REASON_LABELS.get(reason, _UNKNOWN_REASON)


def unlabelled_reasons() -> frozenset[str]:
    """Every :data:`RemovedReason` with no label — empty by construction (the test)."""
    return frozenset(get_args(RemovedReason)) - set(REMOVED_REASON_LABELS)


def labels_for_unknown_reasons() -> frozenset[str]:
    """Labels keyed by a string that is not a :data:`RemovedReason` — a typo'd key
    would leave the real reason unlabelled while looking covered."""
    return frozenset(REMOVED_REASON_LABELS) - frozenset(get_args(RemovedReason))


@dataclass(frozen=True, slots=True)
class RestoredItem:
    """One piece of source text the guard put back, verbatim."""

    text: str
    #: The source duty it was restored from (duties only, records since 2026-10-21).
    source_duty: str | None = None
    #: The source documents that state that duty (their titles), first few only.
    source_documents: tuple[str, ...] = ()
    #: How many more source documents state it than :attr:`source_documents` names.
    more_documents: int = 0


@dataclass(frozen=True, slots=True)
class RestoredGroup:
    """The restored pieces of one section — for duties, of one rewritten duty."""

    section: str
    label: str
    #: Duties only: the duty (as it reads in the draft) the pieces sit under.
    duty: str | None = None
    #: Duties only: the pieces came back as a duty of their own, not under another.
    own_duty: bool = False
    items: tuple[RestoredItem, ...] = ()


@dataclass(frozen=True, slots=True)
class RestoredView:
    """Everything the guard put back that is still in the draft."""

    groups: tuple[RestoredGroup, ...] = ()
    #: Labels of whole sections the rewrite returned empty and the source's came back.
    whole_sections: tuple[str, ...] = ()
    #: ``(section, text)`` to mark inline in the rendered draft.
    marks: tuple[tuple[str, str], ...] = ()

    @property
    def count(self) -> int:
        return sum(len(group.items) for group in self.groups)


@dataclass(frozen=True, slots=True)
class Segment:
    """A run of the rendered draft; ``restored`` runs are source text put back."""

    text: str
    restored: bool = False


def restored_view(
    change_log: Mapping[str, Any] | None,
    content: Mapping[str, Any] | None,
    *,
    section_label: Callable[[str], str],
) -> RestoredView | None:
    """The restored content of a stored draft, or ``None`` when it has no rewrite
    record (a merge-only or Builder draft) or the record cannot be read — the page's
    job is the approve/reject decision, and a provenance panel must never take it down.

    A piece is listed only if it is STILL in ``content``: a reviewer's later edit can
    remove it, and calling text "restored" that the draft no longer holds would be
    false."""
    record = _record(change_log)
    if record is None:
        return None
    content = content or {}
    duties = [d for d in content.get("duties") or [] if isinstance(d, Mapping)]
    titles = _duty_documents((change_log or {}).get("harmonization_diff"))
    origins: dict[str, str] = {}
    for sentence, statement in record.folded_duty_origins:
        origins.setdefault(sentence, statement)

    groups: list[RestoredGroup] = []
    marks: list[tuple[str, str]] = []
    label = section_label("duties")
    by_duty: dict[int, list[RestoredItem]] = {}
    own: dict[int, bool] = {}
    for sentence in dict.fromkeys(record.folded_duty_content):
        where = _locate_in_duties(sentence, duties)
        if where is None:
            continue
        index, is_statement = where
        source = origins.get(sentence)
        documents = titles.get(source, ()) if source else ()
        by_duty.setdefault(index, []).append(
            RestoredItem(
                text=sentence,
                source_duty=source,
                source_documents=documents[:_TITLES_SHOWN],
                more_documents=max(0, len(documents) - _TITLES_SHOWN),
            )
        )
        own[index] = own.get(index, False) or is_statement
        marks.append(("duties", sentence))
    for index in sorted(by_duty):
        groups.append(
            RestoredGroup(
                section="duties",
                label=label,
                duty=_duty_heading(duties[index]),
                own_duty=own[index],
                items=tuple(by_duty[index]),
            )
        )

    for section in _RESTORABLE_SECTIONS[1:]:
        present = set(_section_texts(content, section))
        items = [
            RestoredItem(text=text)
            for text in dict.fromkeys(
                text for sec, text in record.restored_items if sec == section
            )
            if text in present or any(text in p for p in present)
        ]
        if items:
            groups.append(
                RestoredGroup(
                    section=section, label=section_label(section), items=tuple(items)
                )
            )
            marks.extend((section, item.text) for item in items)

    whole = tuple(
        section_label(section)
        for section in record.restored_sections
        if section in _RESTORABLE_SECTIONS
    )
    return RestoredView(groups=tuple(groups), whole_sections=whole, marks=tuple(marks))


def mark_restored(
    rendered: str, marks: Sequence[tuple[str, str]]
) -> tuple[Segment, ...]:
    """``rendered`` (``render_sfu_jd_text`` output) cut into segments, each restored
    piece flagged. A piece is looked for only inside its own section's block, from the
    END (the guard appends what it restores), and only where it stands as a whole item
    — a list line, a contact, a how/why point between ``(`` / ``;`` and ``;`` / ``)``,
    or a duty statement — so a short restored contact ("1 hour") cannot light up the
    same words inside another line. A piece that cannot be found is simply not marked:
    the panel below still lists it."""
    spans: list[tuple[int, int]] = []
    for section, text in sorted(marks, key=lambda mark: -len(mark[1])):
        block = _block(rendered, section)
        if block is None or not text:
            continue
        found = _find_last(rendered, text, block, spans)
        if found is not None:
            spans.append(found)
    if not spans:
        return (Segment(rendered),)
    out: list[Segment] = []
    cursor = 0
    for start, end in sorted(spans):
        if start > cursor:
            out.append(Segment(rendered[cursor:start]))
        out.append(Segment(rendered[start:end], restored=True))
        cursor = end
    if cursor < len(rendered):
        out.append(Segment(rendered[cursor:]))
    return tuple(out)


# --- internals ---------------------------------------------------------------------


def _record(change_log: Mapping[str, Any] | None) -> AntiFabricationRecord | None:
    raw = (change_log or {}).get("anti_fabrication")
    if not isinstance(raw, Mapping):
        return None
    try:
        return AntiFabricationRecord.model_validate(raw)
    except ValidationError:
        return None


def _duty_documents(diff: object) -> dict[str, tuple[str, ...]]:
    """Merge-draft duty statement -> the titles of the source documents whose own duty
    it is (the per-source diff's ``duties_kept``: a merge duty IS its representative
    member's statement, verbatim)."""
    out: dict[str, list[str]] = {}
    if not isinstance(diff, Mapping):
        return {}
    for member in diff.get("per_source") or []:
        if not isinstance(member, Mapping):
            continue
        title = str(member.get("title") or "").strip()
        if not title:
            continue
        for statement in member.get("duties_kept") or []:
            names = out.setdefault(str(statement), [])
            if title not in names:
                names.append(title)
    return {statement: tuple(names) for statement, names in out.items()}


def _duty_heading(duty: Mapping[str, Any]) -> str:
    """The duty as a reviewer reads it. Most stored statements already open with
    their action verb ("Engage community partners…", verb "Engage"); prefixing it again
    would read "Engage Engage…"."""
    verb = str(duty.get("action_verb") or "").strip()
    statement = str(duty.get("statement") or "").strip()
    if not verb or statement.lower().startswith(verb.lower()):
        return statement
    return f"{verb} {statement}"


def _locate_in_duties(
    sentence: str, duties: Sequence[Mapping[str, Any]]
) -> tuple[int, bool] | None:
    """``(duty index, is its statement)`` of the duty holding ``sentence``, or None.
    A how/why point is matched exactly (the guard appends it verbatim); a duty that
    came back as its own carries the sentence in its statement."""
    for index, duty in enumerate(duties):
        if sentence in (duty.get("how_why") or []):
            return index, False
    for index, duty in enumerate(duties):
        if sentence in str(duty.get("statement") or ""):
            return index, True
    return None


def _section_texts(content: Mapping[str, Any], section: str) -> Iterator[str]:
    if section in ("decision_making", "problem_solving"):
        yield from (str(item) for item in content.get(section) or [])
    elif section == "relationships":
        rel = content.get("relationships")
        if isinstance(rel, Mapping):
            if rel.get("supervisory"):
                yield str(rel["supervisory"])
            yield from (str(c) for c in rel.get("internal") or [])
            yield from (str(c) for c in rel.get("external") or [])
    elif section == "qualifications":
        for qual in content.get("qualifications") or []:
            if isinstance(qual, Mapping):
                yield str(qual.get("text") or "")


def _block(rendered: str, section: str) -> tuple[int, int] | None:
    """``(start, end)`` of a section's block in the rendered draft (blocks are
    separated by a blank line and open with the section's canonical heading)."""
    try:
        heading = CANONICAL_HEADING[SectionKey(section)]
    except (ValueError, KeyError):
        return None
    start = 0
    while start <= len(rendered):
        end = rendered.find("\n\n", start)
        end = len(rendered) if end < 0 else end
        if rendered.startswith(f"{heading}\n", start):
            return start + len(heading) + 1, end
        if end >= len(rendered):
            return None
        start = end + 2
    return None  # pragma: no cover


#: What may stand right before / after a whole item in the rendered draft.
_BEFORE: Final[str] = "\n (;:"
_AFTER: Final[tuple[str, ...]] = ("\n", ";", ")", " (")


def _find_last(
    rendered: str, text: str, block: tuple[int, int], taken: Sequence[tuple[int, int]]
) -> tuple[int, int] | None:
    lo, hi = block
    end_limit = hi
    while True:
        start = rendered.rfind(text, lo, end_limit)
        if start < 0:
            return None
        end = start + len(text)
        before_ok = start == lo or rendered[start - 1] in _BEFORE
        after_ok = end == hi or any(rendered.startswith(a, end) for a in _AFTER)
        free = all(end <= s or start >= e for s, e in taken)
        if before_ok and after_ok and free:
            return start, end
        end_limit = start + len(text) - 1

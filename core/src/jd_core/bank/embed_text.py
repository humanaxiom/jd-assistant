"""Turn a parsed JD into the exact text an embedding model sees (Phase 3.2b).

Pure — no I/O, no Ollama, no Neo4j. :mod:`src.jd_bank.embeddings` calls this to build
what it sends across the private network to ``aria-gb10-2`` (ADR-003) and what it
stamps a Neo4j node with. Same shape as :mod:`.similarity` / :mod:`.clustering`: the
maths (here, the serialization) is pure and versioned; the wiring lives in ``jd_bank``.

**Why this exists as its own module, and why it is picky.** An embedding is only as
good as the text it was computed over, and three failure modes are easy to ship by
accident and hard to notice once shipped (a bad vector still LOOKS like a vector):

* **the title leaking into the document vector.** :mod:`.similarity`'s module
  docstring promises the score is *"title-agnostic by construction"* — titles are
  never a term of it. If the title were folded into the document text, that promise
  would be silently broken through the back door: ``weight_vector`` would now be
  scoring title similarity too. :attr:`~src.jd_core.rules.Embeddings.
  include_title_in_document` defaults ``false`` for exactly this reason, and it is
  pinned by mutation (flip it and the title appears in the serialized text; ship it
  and it does not).
* **SFU's mandated boilerplate converging every modern JD's vector.** About-SFU, the
  territorial acknowledgement and the Employment Equity statement are IDENTICAL text
  on every compliant JD (HR-058's shape, in the vector domain). They are represented
  on :class:`~src.jd_core.models.parsed_jd.SFUJobDescription` as presence *booleans*
  (``about_sfu_present`` etc.), never as text — so serializing the PARSED JD (never
  the raw extracted text) keeps them out for free, with no exemption list to maintain.
* **an unfalsifiable field re-appearing.** ``SFUDuty.how_why`` is never populated by
  the deterministic segmenter (the 2.6 finding, HR-121) — so it is simply not read
  here. A duty contributes only ``f"{action_verb} {statement}"``. The day Phase 4
  populates ``how_why``, this serializer does not need to change to pick it up
  correctly — it already doesn't reference the field, so there is nothing to get
  wrong twice.

**Why not reuse ``jd_core.textnorm.fold``.** Folding (dropping zero-width characters,
collapsing whitespace runs, normalizing typographic punctuation) is a *scanner*
decision (HR-108) — it exists to make the deterministic gate matchers robust to
`.doc` line-wrapping. Coupling the embedding text to it would mean flipping HR-108
re-embeds the entire archive for a reason that has nothing to do with what a JD
*means*. This module does the minimum, explicit normalization instead: each field is
``.strip()``ed, and nothing else — no case folding, no whitespace collapsing beyond
what ``.strip()`` does. A vector is not a gate; it does not need HR-108's robustness,
and it must not inherit HR-108's blast radius.

**Determinism.** Same :class:`~src.jd_core.models.parsed_jd.SFUJobDescription` +
same :class:`~src.jd_core.rules.Embeddings` -> byte-identical text -> the same
``text_sha256`` -> (measured against the real endpoint, ADR-003) the same vector. That
identity is what makes the store's skip-first pass and the runner's in-run memo sound.

**Truncation.** ``max_chars`` is enforced at whole-UNIT boundaries — never mid-word,
never mid-item. A "unit" is one contributed line (one duty, one qualification, one
relationship entry, the whole position summary...). Units are greedily included, in
order, while they still fit; the first one that would overflow, and everything after
it, is dropped. :attr:`SerializedText.text_chars` is the PRE-truncation length, so a
caller can tell "this would have been longer" from "this is exactly what it is".
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping
from typing import Final, NamedTuple

from src.jd_core.models.parsed_jd import SFUJobDescription
from src.jd_core.rules import Embeddings

#: Stamped on every embedded node (``serializer_version``) — bump when this module's
#: output changes for the SAME rulebook knobs (a code change, not a data change; a
#: data change already moves ``Embeddings.stamp``). A code constant, not a knob: it
#: has no "value" HR could ratify, only an identity this module's output carries.
SERIALIZER_VERSION: Final[str] = "embed_text_v1"


class SerializedText(NamedTuple):
    """One embeddable unit of text, truncated to the rulebook's ``max_chars``."""

    text: str
    #: The length BEFORE truncation — lets a caller tell "this JD is genuinely huge"
    #: from "this JD is exactly 400 characters".
    text_chars: int
    truncated: bool
    #: SHA-256 of :attr:`text` (the text actually embedded, post-truncation) — the
    #: content-identity key the store's skip-first pass and the runner's in-run memo
    #: both key on.
    text_sha256: str


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _clean(value: str | None) -> str:
    """``.strip()``, tolerating ``None`` — the ONLY normalization this module does."""
    return value.strip() if value else ""


# --- one unit-producer per content-bearing SFU section ------------------------


def _position_summary_units(jd: SFUJobDescription) -> list[str]:
    text = _clean(jd.position_summary)
    return [text] if text else []


def _duties_units(jd: SFUJobDescription) -> list[str]:
    # NEVER reads `how_why` — the segmenter never populates it (HR-121), and this
    # serializer does not need to change when Phase 4 starts filling it in: it
    # already only reads `action_verb` and `statement`.
    units = []
    for duty in jd.duties:
        line = f"{duty.action_verb} {duty.statement}".strip()
        if line:
            units.append(line)
    return units


def _decision_making_units(jd: SFUJobDescription) -> list[str]:
    return [text for item in jd.decision_making if (text := _clean(item))]


def _problem_solving_units(jd: SFUJobDescription) -> list[str]:
    return [text for item in jd.problem_solving if (text := _clean(item))]


def _relationships_units(jd: SFUJobDescription) -> list[str]:
    rel = jd.relationships
    if rel is None:
        return []
    units: list[str] = []
    supervisory = _clean(rel.supervisory)
    if supervisory:
        units.append(supervisory)
    # Supervisory, THEN internal, THEN external — file order is content, never sorted.
    units.extend(text for item in rel.internal if (text := _clean(item)))
    units.extend(text for item in rel.external if (text := _clean(item)))
    return units


def _qualifications_units(jd: SFUJobDescription) -> list[str]:
    units = []
    for qual in jd.qualifications:
        text = _clean(qual.text)
        if not text:
            continue
        line = f"{qual.modifier} {text}".strip() if qual.modifier else text
        units.append(line)
    return units


def _additional_context_units(jd: SFUJobDescription) -> list[str]:
    text = _clean(jd.additional_context)
    return [text] if text else []


#: Every section :data:`~src.jd_core.rules.Embeddings.document_sections` /
#: :data:`~src.jd_core.rules.Embeddings.section_vectors` may name — the loader
#: restricts both fields to this same set (``loader._CONTENT_SECTIONS``), so a
#: section named in the rulebook always has a producer here and vice versa.
_SECTION_UNITS: Final[Mapping[str, Callable[[SFUJobDescription], list[str]]]] = {
    "position_summary": _position_summary_units,
    "duties": _duties_units,
    "decision_making": _decision_making_units,
    "problem_solving": _problem_solving_units,
    "relationships": _relationships_units,
    "qualifications": _qualifications_units,
    "additional_context": _additional_context_units,
}


def _join_truncated(units: list[str], *, max_chars: int) -> SerializedText:
    """Join ``units`` with ``\\n``, truncating at ``max_chars`` on a whole-unit
    boundary — greedily include units, in order, while they still fit."""
    full = "\n".join(units)
    if len(full) <= max_chars:
        return SerializedText(
            text=full, text_chars=len(full), truncated=False, text_sha256=_sha256(full)
        )

    kept: list[str] = []
    length = 0
    for unit in units:
        addition = len(unit) + (1 if kept else 0)  # +1 for the joining "\n"
        if length + addition > max_chars:
            break
        kept.append(unit)
        length += addition
    truncated_text = "\n".join(kept)
    return SerializedText(
        text=truncated_text,
        text_chars=len(full),
        truncated=True,
        text_sha256=_sha256(truncated_text),
    )


def retruncate_within(text: str, max_chars: int) -> str:
    """Re-cut an already-serialized (``\\n``-joined) ``text`` to ``max_chars`` by
    dropping whole trailing LINES — the last-resort fallback the embedding runner
    reaches for when :func:`serialize_document`'s own ``max_chars`` output still 400s
    (dense text over the model's token window; HR-193).

    Cuts on ``\\n`` because that is the delimiter :func:`_join_truncated` joins units
    with, so for the single-line units that make up almost every JD (one duty, one
    qualification) a line boundary *is* the unit boundary — the same whole-unit
    guarantee the primary path gives, reached the same way. The one exception is a
    unit that itself contains a newline (a multi-paragraph position summary): this
    may cut such a unit internally. That is an accepted limit of a deliberately
    best-effort fallback for text the model's window physically cannot hold — the
    primary ``max_chars`` path never does this, and this path only ever runs for the
    ~11 densest documents in the archive.

    Returns ``""`` when not one whole line fits under ``max_chars`` (the caller must
    treat that as "no rung fit", never embed the empty string).
    """
    if len(text) <= max_chars:
        return text
    kept: list[str] = []
    length = 0
    for line in text.split("\n"):
        addition = len(line) + (1 if kept else 0)  # +1 for the joining "\n"
        if length + addition > max_chars:
            break
        kept.append(line)
        length += addition
    return "\n".join(kept)


def serialize_document(jd: SFUJobDescription, rules: Embeddings) -> SerializedText:
    """The whole-document text :attr:`~src.jd_core.rules.Embeddings.document_sections`
    describes, in template order.

    Empty (``text == ""``) for a JD whose configured sections are all empty — the
    34.5% WJQ-template case the segmenter cannot read. The caller (the runner) must
    treat that as "no document unit", never embed ``""``, and count it as a skip.
    """
    units: list[str] = []
    if rules.include_title_in_document:
        title = _clean(jd.title)
        if title:
            units.append(title)
    for section in rules.document_sections:
        units.extend(_SECTION_UNITS[section](jd))
    return _join_truncated(units, max_chars=rules.max_chars)


def serialize_section(
    jd: SFUJobDescription, rules: Embeddings, section: str
) -> SerializedText | None:
    """One section's own text (for :attr:`~src.jd_core.rules.Embeddings.
    section_vectors`) — ``None`` when the section has nothing to say, or says too
    little to be worth an embedding (:attr:`~src.jd_core.rules.Embeddings.
    min_section_chars`, a guard-rail against a near-empty section, not a filter that
    trims real content).

    Raises:
        KeyError: ``section`` is not one of :data:`_SECTION_UNITS` — the loader
            restricts ``section_vectors`` to that same set, so this can only happen
            if a caller passes a section name the rulebook itself would reject.
    """
    units = _SECTION_UNITS[section](jd)
    if not units:
        return None
    serialized = _join_truncated(units, max_chars=rules.max_chars)
    if serialized.text_chars < rules.min_section_chars:
        return None
    return serialized

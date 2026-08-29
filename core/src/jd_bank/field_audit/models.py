"""What the P3b field audit reports.

Three numbers per field per bargaining unit, never one: **the parser read it**, **the
parser did not and the document states it**, and **could not evaluate**. A filter that
cannot publish what it cannot see is unfalsifiable — the IT collection reported 45 roles
against a true ~211 and nothing on the page let a reader tell a small set from a blind
one.

⚠ **Split by employee group, always.** `title` was never a general problem: 47.6% of
CUPE documents carried no title against **0.0%** everywhere else, and the aggregate hid
it completely. A single archive-wide percentage for any of these fields is a number that
has already been wrong once.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class FieldOutcome(BaseModel):
    """One field, in one population of documents, split by what the archive says."""

    model_config = ConfigDict(frozen=True)

    #: The WJQ spellings this field is read from — `wjq.id_labels`, verbatim, so a
    #: reader can see what was searched for rather than trust it was the right list.
    wjq_labels: tuple[str, ...] = ()
    #: The probe's own DISCOVERY terms. Published because they are its blind spot: a
    #: field named without one of these is invisible here.
    key_words: tuple[str, ...] = ()
    #: Names ruled OUT as belonging to another field. Published for the same reason —
    #: an exclusion is a claim, and a claim you cannot see is one you cannot check.
    excluded_terms: tuple[str, ...] = ()
    documents: int = Field(ge=0)

    #: The parser stored a value. (From `parsed_jds`, at the current PARSER_VERSION.)
    parser_has_value: int = Field(ge=0)

    #: 🔴 THE DEFECT COLUMN. The document states the field, with a value, under a name
    #: NEITHER registered mechanism can read — not a `wjq.id_labels` spelling and not
    #: matched by the modern template's regex. Every one is a value the archive holds
    #: and the Bank cannot.
    unreadable_with_value: int = Field(ge=0)

    #: The document states the field, with a value, under a name one of the two
    #: mechanisms reads. Where the parser still has nothing, the cause is not the label.
    readable_with_value: int = Field(ge=0)

    #: The label is present and EMPTY — a blank form field. Not a defect, and counting
    #: it as stated is the mistake that made the first P3a fix recover exactly zero.
    label_present_no_value: int = Field(ge=0)

    #: ⚠ COULD NOT EVALUATE. No field name containing any registered spelling appears at
    #: all. The document may state it under a name sharing no substring, or not at all.
    #: The probe cannot tell, and says so rather than counting it as absent.
    no_label_found: int = Field(ge=0)

    @property
    def stated_in_document(self) -> int:
        return self.readable_with_value + self.unreadable_with_value


class GroupAudit(BaseModel):
    """Every audited field for one bargaining unit."""

    model_config = ConfigDict(frozen=True)

    employee_group: str
    documents: int = Field(ge=0)
    fields: dict[str, FieldOutcome]


class GapExample(BaseModel):
    """One document where the archive states a value the Bank does not hold.

    🔴 **The evidence, and it is not optional.** An aggregate is not a finding until the
    files behind it have been opened: this project has twice produced a confident,
    self-consistent number whose query answered a different question. These rows let a
    reader — or the owner, with no assistant — check the count by eye.
    """

    model_config = ConfigDict(frozen=True)

    filename: str
    employee_group: str
    field: str
    #: The field name as the DOCUMENT writes it, and the value found after it.
    field_name: str
    document_value: str


class FieldAuditSummary(BaseModel):
    """The whole P3b run."""

    model_config = ConfigDict(frozen=True)

    parser_version: str
    #: ⚠ Stamped because a sample is not the corpus. ``None`` means a full run.
    documents_read: int = Field(ge=0)
    sampled: int | None = None
    #: Documents the archive holds that this run did not open.
    documents_skipped: int = Field(ge=0, default=0)
    by_group: dict[str, GroupAudit]
    #: Field -> the UNREADABLE field names actually seen, most frequent first.
    #: The evidence. A count without the strings behind it cannot be checked by eye, and
    #: every defect this project has found was found by reading them.
    unreadable_examples: dict[str, list[tuple[str, int]]] = {}
    #: Documents where the archive states a READABLE value and the parser stored none —
    #: the gap, file by file. Empty unless `--evidence` asked for it.
    gap_examples: list[GapExample] = []
    #: Fields NOT covered by this probe, and why. Published, never omitted.
    not_evaluated: dict[str, str] = {}

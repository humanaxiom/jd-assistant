"""Compensation Requisition Form filler (Track K, K2).

Fills SFU's OWN AcroForm (``templates/CompensationRequisitionForm_2024.pdf``, "Updated
September 17, 2024") with the few facts the Bank actually holds. It does not redraw the
form: the output is the official document, still editable, for the requester to finish,
sign in Acrobat and email to Compensation.

    pdf_bytes = fill_compensation_requisition(CompReqPrefill(position_title="..."))

**Scope: prefill + download. No request store, no workflow** — HRIS stays the system of
record for the pay transaction. This module is a PURE function over bytes: no I/O
beyond the shipped template, no network, no model.

Invariants (each has a test):

* **The template is pinned** by sha256 in ``templates/comp_requisition.yaml``; a PDF
  whose hash differs is refused, and a test pins the PDF's full 115-name field set.
* **Only mapped fields are writable.** The semantic -> PDF field map is data (the PDF's
  own names are misleading), and :func:`validate_field_map` refuses a map that points at
  a signature field.
* **The three signature fields are never filled.**
* **No incumbent name can be passed in** — :class:`CompReqPrefill` has no such field
  (``extra="forbid"``), and the Bank strips incumbent names at ingestion anyway.
* **Unfilled stays empty**: a ``None`` / empty value writes nothing; nothing is guessed.
"""

from __future__ import annotations

import hashlib
import io
from functools import lru_cache
from pathlib import Path
from typing import Final, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field
from pypdf import PdfReader, PdfWriter

#: Where the template PDF and its field map ship (inside the image: ``COPY . .``).
TEMPLATE_DIR: Final[Path] = Path(__file__).resolve().parent / "templates"
FIELD_MAP_FILE: Final[str] = "comp_requisition.yaml"


class TemplateMismatchError(ValueError):
    """The template PDF is not the pinned one (SFU revised it, or it is corrupt)."""


class OverflowRules(BaseModel):
    """How a list longer than its single-line box is written (see the YAML)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    max_ids: int = Field(ge=1)
    more_template: str
    field_width_pt: float
    font_size_pt: float
    details_field: str
    section_labels: dict[str, str]


class CompReqFieldMap(BaseModel):
    """``templates/comp_requisition.yaml`` — the field map and the template pin."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: str
    template_file: str
    template_sha256: str
    checkbox_on_value: str
    prefill_fields: dict[str, str]
    unwritten_fields: tuple[str, ...]
    overflow: OverflowRules
    employee_group_options: dict[str, str]
    signature_fields: tuple[str, ...]
    all_fields: tuple[str, ...]


class CompReqPrefill(BaseModel):
    """ONLY what the Bank can supply. Deliberately no field for a person's name,
    a signature, an email, a supervisor or a grade: those are the requester's to enter.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    #: One position number, or ``None`` — a role spans several positions, so a caller
    #: must pick one (K3); the filler never chooses.
    position_number: str | None = None
    position_title: str | None = None
    department: str | None = None
    #: Section A / Section B "list all position #" — joined as ``a, b`` on the form.
    based_on_positions_a: tuple[str, ...] = Field(default=())
    based_on_positions_b: tuple[str, ...] = Field(default=())
    #: Checklist: "Job description in Word format" (the Bank renders that .docx).
    jd_in_word_attached: bool = False
    #: VPA section dropdown — only APSA / APEX exist on the form.
    employee_group: Literal["APSA", "APEX"] | None = None
    #: Every position the Bank can name for the role, for the caller's picker. NEVER
    #: written to the PDF.
    candidate_positions: tuple[str, ...] = Field(default=())
    #: True when some member file names no position the pattern can read (e.g. an
    #: unpadded id), so ``candidate_positions`` may be a partial list. NEVER written.
    positions_incomplete: bool = False


def validate_field_map(fmap: CompReqFieldMap) -> CompReqFieldMap:
    """Refuse a map that could write something it must not. Returns ``fmap``."""
    names = set(fmap.all_fields)
    targets = set(fmap.prefill_fields.values())
    if targets & set(fmap.signature_fields):
        raise ValueError("prefill_fields points at a signature field")
    if not targets <= names:
        unknown = sorted(targets - names)
        raise ValueError(f"prefill_fields names unknown PDF fields: {unknown}")
    if not set(fmap.signature_fields) <= names:
        raise ValueError("signature_fields names a field the form does not have")
    if set(fmap.prefill_fields) | set(fmap.unwritten_fields) != set(
        CompReqPrefill.model_fields
    ):
        raise ValueError(
            "prefill_fields + unwritten_fields must cover exactly the "
            "CompReqPrefill fields"
        )
    if set(fmap.prefill_fields) & set(fmap.unwritten_fields):
        raise ValueError("a field cannot be both written and unwritten")
    details = fmap.overflow.details_field
    if details not in names or details in fmap.signature_fields or details in targets:
        raise ValueError(
            "overflow.details_field must be a real, unmapped, unsigned field"
        )
    return fmap


@lru_cache(maxsize=1)
def load_field_map() -> CompReqFieldMap:
    raw = yaml.safe_load((TEMPLATE_DIR / FIELD_MAP_FILE).read_text(encoding="utf-8"))
    return validate_field_map(CompReqFieldMap(**raw))


def _load_template(fmap: CompReqFieldMap, template_path: Path | None) -> bytes:
    data = (template_path or TEMPLATE_DIR / fmap.template_file).read_bytes()
    actual = hashlib.sha256(data).hexdigest()
    if actual != fmap.template_sha256:
        raise TemplateMismatchError(
            f"template sha256 {actual} != pinned {fmap.template_sha256}: SFU has "
            "revised "
            "the form (or the file is damaged). Re-map the fields before filling."
        )
    return data


def _values_to_write(fmap: CompReqFieldMap, prefill: CompReqPrefill) -> dict[str, str]:
    """PDF field name -> value, for exactly the facts supplied. Empty writes nothing."""
    pf = fmap.prefill_fields
    out: dict[str, str] = {}

    def put(key: str, value: str | None) -> None:
        if value:
            out[pf[key]] = value

    put("position_number", prefill.position_number)
    put("position_title", prefill.position_title)
    put("department", prefill.department)
    ov = fmap.overflow
    details: list[str] = []
    for key, ids in (
        ("based_on_positions_a", prefill.based_on_positions_a),
        ("based_on_positions_b", prefill.based_on_positions_b),
    ):
        if len(ids) > ov.max_ids:
            shown = ", ".join(ids[: ov.max_ids])
            put(key, shown + ov.more_template.format(k=len(ids) - ov.max_ids))
            details.append(
                f"{ov.section_labels[key]} position # ({len(ids)}): " + ", ".join(ids)
            )
        else:
            put(key, ", ".join(ids))
    if details:
        out[ov.details_field] = "\n".join(details)
    if prefill.jd_in_word_attached:
        out[pf["jd_in_word_attached"]] = fmap.checkbox_on_value
    put("employee_group", prefill.employee_group)
    # Defence in depth: whatever the map said, a signature field is never written.
    return {k: v for k, v in out.items() if k not in fmap.signature_fields}


def fill_compensation_requisition(
    prefill: CompReqPrefill, *, template_path: Path | None = None
) -> bytes:
    """Fill SFU's Compensation Requisition Form with ``prefill``; return the PDF bytes.

    Raises :class:`TemplateMismatchError` if the template is not the pinned one.
    """
    fmap = load_field_map()
    template = _load_template(fmap, template_path)
    values = _values_to_write(fmap, prefill)

    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(template)))
    if values:
        for page in writer.pages:
            writer.update_page_form_field_values(page, values, auto_regenerate=False)
    # The template carries no /NeedAppearances; ask viewers to draw the filled values.
    writer.set_need_appearances_writer(True)

    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()

"""Unit — the Compensation Requisition Form filler (Track K, K2).

The filler is a PURE function over SFU's own AcroForm. What these tests defend:

1. **The template is pinned.** A PDF whose sha256 differs is refused, and the field
   set must equal the 115 names in the YAML, so an SFU revision cannot be filled against
   a stale map.
2. **Only the mapped fields can be written**; the three signature fields never are; no
   incumbent name can enter (the prefill model has no field for one).
3. **Unfilled fields stay empty** and what is filled reads back EXACTLY as supplied.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from pydantic import ValidationError
from pypdf import PdfReader

from src.jd_export import comp_requisition as crf
from src.jd_export.comp_requisition import (
    CompReqPrefill,
    TemplateMismatchError,
    fill_compensation_requisition,
    load_field_map,
)


def _values(pdf: bytes) -> dict[str, object]:
    fields = PdfReader(io.BytesIO(pdf)).get_fields() or {}
    return {name: f.get("/V") for name, f in fields.items()}


def _full() -> CompReqPrefill:
    return CompReqPrefill(
        position_number="00001234",
        position_title="Research Coordinator",
        department="School of Computing Science",
        based_on_positions_a=("00001234", "00005678"),
        based_on_positions_b=("00001234",),
        jd_in_word_attached=True,
        employee_group="APSA",
    )


# --- the pinned template ---


def test_the_shipped_template_matches_the_pinned_sha256() -> None:
    import hashlib

    fmap = load_field_map()
    data = (crf.TEMPLATE_DIR / fmap.template_file).read_bytes()
    assert hashlib.sha256(data).hexdigest() == fmap.template_sha256


def test_the_pdf_field_set_is_exactly_the_pinned_115() -> None:
    """SFU changing the form (adding, renaming or dropping a field) fails HERE."""
    fmap = load_field_map()
    reader = PdfReader(str(crf.TEMPLATE_DIR / fmap.template_file))
    assert len(fmap.all_fields) == 115
    assert set((reader.get_fields() or {}).keys()) == set(fmap.all_fields)


def test_every_mapped_and_signature_field_exists_on_the_form() -> None:
    fmap = load_field_map()
    names = set(fmap.all_fields)
    assert set(fmap.prefill_fields.values()) <= names
    assert set(fmap.signature_fields) <= names
    assert len(fmap.signature_fields) == 3


def test_the_map_never_points_a_prefill_at_a_signature() -> None:
    fmap = load_field_map()
    assert not set(fmap.prefill_fields.values()) & set(fmap.signature_fields)


def test_a_template_with_a_different_sha256_is_refused(tmp_path: Path) -> None:
    other = tmp_path / "CompensationRequisitionForm_2024.pdf"
    other.write_bytes(
        (crf.TEMPLATE_DIR / load_field_map().template_file).read_bytes() + b"\n%x"
    )
    with pytest.raises(TemplateMismatchError):
        fill_compensation_requisition(_full(), template_path=other)


# --- filling ---


def test_every_prefilled_value_reads_back_exactly() -> None:
    fmap = load_field_map()
    out = _values(fill_compensation_requisition(_full()))
    pf = fmap.prefill_fields
    assert out[pf["position_number"]] == "00001234"
    assert out[pf["position_title"]] == "Research Coordinator"
    assert out[pf["department"]] == "School of Computing Science"
    assert out[pf["based_on_positions_a"]] == "00001234, 00005678"
    assert out[pf["based_on_positions_b"]] == "00001234"
    assert out[pf["jd_in_word_attached"]] == fmap.checkbox_on_value
    assert out[pf["employee_group"]] == "APSA"


def test_signature_fields_are_never_filled() -> None:
    fmap = load_field_map()
    out = _values(fill_compensation_requisition(_full()))
    for name in fmap.signature_fields:
        assert out[name] in (None, ""), name


def test_every_field_that_was_not_prefilled_is_unchanged_from_the_blank_form() -> None:
    fmap = load_field_map()
    blank = _values((crf.TEMPLATE_DIR / fmap.template_file).read_bytes())
    filled = _values(fill_compensation_requisition(_full()))
    touched = set(fmap.prefill_fields.values())
    for name in fmap.all_fields:
        if name not in touched:
            assert filled[name] == blank[name], name


def test_an_empty_prefill_leaves_the_form_exactly_blank() -> None:
    fmap = load_field_map()
    blank = _values((crf.TEMPLATE_DIR / fmap.template_file).read_bytes())
    assert _values(fill_compensation_requisition(CompReqPrefill())) == blank


def test_none_fields_are_left_empty_not_guessed() -> None:
    fmap = load_field_map()
    out = _values(fill_compensation_requisition(CompReqPrefill(position_title="X")))
    assert out[fmap.prefill_fields["position_title"]] == "X"
    assert out[fmap.prefill_fields["department"]] in (None, "")
    assert out[fmap.prefill_fields["jd_in_word_attached"]] in (None, "/Off")


def test_the_output_is_a_pdf_and_stays_an_editable_form() -> None:
    pdf = fill_compensation_requisition(_full())
    assert pdf.startswith(b"%PDF")
    assert PdfReader(io.BytesIO(pdf)).get_fields()


def test_the_filler_is_deterministic_for_the_same_input() -> None:
    a = _values(fill_compensation_requisition(_full()))
    b = _values(fill_compensation_requisition(_full()))
    assert a == b


# --- the model: no incumbent name, no stray fields ---


@pytest.mark.parametrize(
    "field", ["incumbent_name", "incumbent_names", "employee_name", "name", "signature"]
)
def test_no_incumbent_or_signature_value_can_be_passed_in(field: str) -> None:
    with pytest.raises(ValidationError):
        CompReqPrefill(**{field: "Jane Doe"})  # type: ignore[arg-type]


def test_the_model_has_no_field_that_could_carry_a_person() -> None:
    forbidden = ("incumbent", "name_of", "employee_name", "signature", "email")
    for field in CompReqPrefill.model_fields:
        assert not any(bit in field for bit in forbidden), field


def test_the_model_fields_are_exactly_the_mapped_fields() -> None:
    assert set(CompReqPrefill.model_fields) == set(load_field_map().prefill_fields)


def test_employee_group_must_be_a_dropdown_option() -> None:
    with pytest.raises(ValidationError):
        CompReqPrefill(employee_group="CUPE")  # type: ignore[arg-type]


def test_the_filler_refuses_to_write_a_signature_even_if_the_map_were_edited() -> None:
    """Belt and braces: a signature field in prefill_fields is rejected at load."""
    fmap = load_field_map()
    bad = fmap.model_copy(
        update={
            "prefill_fields": {**fmap.prefill_fields, "position_title": "Signature"}
        }
    )
    with pytest.raises(ValueError, match="signature"):
        crf.validate_field_map(bad)

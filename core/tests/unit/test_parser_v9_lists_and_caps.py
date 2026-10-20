"""Parser v9 — Word list paragraphs are items, and the duty caps are rulebook data.

Three defects, each verified on the live Bank 2026-10-19 and re-measured on a throwaway
copy of it before this change shipped (``docs/plans/PARSER-V9-LISTS-AND-CAPS.md``):

1. **Word list bullets were invisible.** A Word list paragraph carries its bullet as
   FORMATTING (``<w:numPr>``, directly or through its style), not as a glyph in the
   text. python-docx returns the bare words, so the segmenter's ``_logical_lines`` saw
   no bullet marker and appended every item to the previous one: the whole DUTIES
   section became ONE run-on duty, then was cut at 400 characters. Typed-bullet files
   (a ``•`` in the text) never had the problem — the defect was the FORMAT, not the
   content.
2. **Every duty statement was cut at 400 characters** (``_MAX_DUTY_STMT``, mirrored on
   ``SFUDuty.statement``), unregistered.
3. **The WJQ re-read kept 12 functions** (``_MAX_DUTIES``, majors first) — the minor
   functions of a full CUPE questionnaire were dropped.

The fixtures below are shaped like the archive, not like python-docx's defaults: the
modern SFU template writes its duties as ``ListParagraph`` paragraphs with a DIRECT
``numPr`` (measured on ``20260702_00138566_JDFN_APSA_20260626.docx``), and older files
use a numbered STYLE.
"""

from __future__ import annotations

from io import BytesIO

import pytest
from docx import Document
from docx.document import Document as DocxDocument
from docx.oxml import parse_xml
from docx.oxml.ns import nsdecls

from src.jd_bank.db.models import DocumentFormat
from src.jd_bank.ingest.extract import LIST_ITEM_MARKER, extract_text
from src.jd_core.bank.shingles import shingle_hashes
from src.jd_core.models.parsed_jd import SFUDuty, SFUJobDescription
from src.jd_core.parser import PARSER_VERSION, parse_jd
from src.jd_core.parser.wjq import segment_wjq
from src.jd_core.rules import get_rules

_DUTIES = [
    "Writes strategic funding proposals and develops proposal budgets.",
    "Supports Principal Investigators in writing innovative funding proposals.",
    "Interprets grant regulations and reviews applications for completeness.",
    "Creates presentations, seminars and workshops on funding opportunities.",
    "Maintains familiarity with leading research at SFU.",
    "Liaises with peers at other institutions on current developments.",
]


def _numpr(num_id: str, ilvl: str = "0") -> object:
    return parse_xml(
        f'<w:numPr {nsdecls("w")}><w:ilvl w:val="{ilvl}"/>'
        f'<w:numId w:val="{num_id}"/></w:numPr>'
    )


def _list_para(doc: DocxDocument, text: str, num_id: str = "2") -> None:
    """A ``ListParagraph`` with a DIRECT ``numPr`` — the modern template's shape."""
    p = doc.add_paragraph(text, style="List Paragraph")
    p._p.get_or_add_pPr().append(_numpr(num_id))


def _numbered_style(doc: DocxDocument, style_id: str = "DutyBullet") -> str:
    """A custom paragraph style that carries ``numPr`` itself, based on Normal — the
    older template's shape (numbering inherited, nothing on the paragraph)."""
    styles = doc.styles.element
    styles.append(
        parse_xml(
            f'<w:style {nsdecls("w")} w:type="paragraph" w:styleId="{style_id}">'
            f'<w:name w:val="{style_id}"/><w:basedOn w:val="Normal"/>'
            f'<w:pPr><w:numPr><w:numId w:val="7"/></w:numPr></w:pPr></w:style>'
        )
    )
    return style_id


def _blob(doc: DocxDocument) -> bytes:
    buf = BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _jdfn_doc(add_duty: object) -> bytes:
    doc = Document()
    doc.add_paragraph("POSITION SUMMARY")
    doc.add_paragraph("The Strategic Grants Advisor supports grant development.")
    doc.add_paragraph("DUTIES AND RESPONSIBILITIES")
    for duty in _DUTIES:
        add_duty(doc, duty)  # type: ignore[operator]
    doc.add_paragraph("QUALIFICATIONS")
    doc.add_paragraph("Bachelor's degree and five years of related experience.")
    return _blob(doc)


def _duties_of(blob: bytes) -> list[SFUDuty]:
    return parse_jd(extract_text(blob, DocumentFormat.DOCX)).jd.duties


# ── Defect 1: Word list paragraphs ───────────────────────────────────────────


def test_direct_numpr_list_items_parse_as_separate_duties() -> None:
    """🔴 THE REGRESSION. Six ``ListParagraph`` duties with a direct ``numPr`` parsed as
    ONE duty under v8 (every item appended to the first, then cut at 400)."""
    duties = _duties_of(_jdfn_doc(_list_para))

    assert [d.statement for d in duties] == [d.rstrip(".") + "." for d in _DUTIES]


def test_style_inherited_numbering_parse_as_separate_duties() -> None:
    """The older template numbers through the STYLE — nothing on the paragraph."""
    doc = Document()
    style_id = _numbered_style(doc)
    doc.add_paragraph("DUTIES AND RESPONSIBILITIES")
    for duty in _DUTIES:
        p = doc.add_paragraph(duty)
        p._p.get_or_add_pPr().get_or_add_pStyle().val = style_id
    duties = _duties_of(_blob(doc))

    assert len(duties) == len(_DUTIES)


def test_numid_zero_switches_numbering_off() -> None:
    """``numId=0`` on the paragraph is Word's explicit "not a list", even under a
    numbered style — so those paragraphs keep the v8 reading (no marker)."""
    doc = Document()
    style_id = _numbered_style(doc)
    p = doc.add_paragraph("Not actually a bullet.")
    ppr = p._p.get_or_add_pPr()
    ppr.get_or_add_pStyle().val = style_id
    ppr.append(_numpr("0"))

    text = extract_text(_blob(doc), DocumentFormat.DOCX)
    assert LIST_ITEM_MARKER not in text


def test_typed_bullets_are_unchanged() -> None:
    """A typed ``•`` already splits; the marker is never doubled."""

    def typed(doc: DocxDocument, text: str) -> None:
        doc.add_paragraph(f"•\t{text}")

    blob = _jdfn_doc(typed)
    assert len(_duties_of(blob)) == len(_DUTIES)
    assert f"{LIST_ITEM_MARKER}•" not in extract_text(blob, DocumentFormat.DOCX)


def test_plain_paragraphs_extract_byte_identically() -> None:
    """No list formatting, no change: the marker is the ONLY extraction difference."""
    doc = Document()
    for line in ("POSITION SUMMARY", "Plain prose.", "More prose."):
        doc.add_paragraph(line)
    assert extract_text(_blob(doc), DocumentFormat.DOCX) == (
        "POSITION SUMMARY\nPlain prose.\nMore prose."
    )


def test_a_numbered_heading_still_opens_its_section() -> None:
    """Outline-numbered headings are list paragraphs too. Marking one would hide it
    from the heading matcher and silently merge two sections — so headings (JDFN and
    WJQ vocabularies) are never marked."""
    doc = Document()
    _list_para(doc, "DUTIES AND RESPONSIBILITIES", num_id="9")
    for duty in _DUTIES[:3]:
        _list_para(doc, duty)
    _list_para(doc, "QUALIFICATIONS", num_id="9")
    _list_para(doc, "Bachelor's degree in a related field.")
    result = parse_jd(extract_text(_blob(doc), DocumentFormat.DOCX))

    assert len(result.jd.duties) == 3
    assert [q.text for q in result.jd.qualifications] == [
        "Bachelor's degree in a related field."
    ]


def test_a_wjq_docx_keeps_the_unmarked_reading() -> None:
    """The WJQ duty reader enters "bulleted" mode on ONE bullet and then fuses every
    plain paragraph into the duty before it. On a ``.docx`` that mixes list and plain
    paragraphs that measured net-harmful (183 documents lost duties, up to 37 -> 5), so
    a WJQ questionnaire extracts exactly as before v9."""
    doc = Document()
    doc.add_paragraph("WEIGHTED JOB QUESTIONNAIRE (WJQ) CUSTOM")
    doc.add_paragraph("3.  MAJOR FUNCTIONS")
    _list_para(doc, "Answers enquiries about registration. (D)")
    doc.add_paragraph("Prepares weekly enrolment reports for the Registrar.")
    doc.add_paragraph("Reconciles term statistics at semester end.")
    text = extract_text(_blob(doc), DocumentFormat.DOCX)

    assert LIST_ITEM_MARKER not in text
    assert len(parse_jd(text).jd.duties) == 3


def test_bulleted_contacts_stay_in_their_connections_list() -> None:
    """A bullet under "Internal Connections" is a logical line of its own; before v9 it
    matched no label and was appended to ``supervisory`` (213 documents measured)."""
    doc = Document()
    doc.add_paragraph("RELATIONSHIPS")
    doc.add_paragraph("Establishes and maintains relationships.")
    doc.add_paragraph("Internal Connections")
    _list_para(doc, "Director, Research Services - policy updates")
    _list_para(doc, "Associate Dean - postdoctoral opportunities")
    doc.add_paragraph("External Connections")
    _list_para(doc, "Immigration Canada - policy clarification")
    rel = parse_jd(extract_text(_blob(doc), DocumentFormat.DOCX)).jd.relationships

    assert rel is not None
    assert "Director, Research Services - policy updates" in rel.internal
    assert "Associate Dean - postdoctoral opportunities" in rel.internal
    assert "Immigration Canada - policy clarification" in rel.external
    assert rel.supervisory == "Establishes and maintains relationships."


def test_a_fallback_title_never_carries_the_list_glyph() -> None:
    doc = Document()
    _list_para(doc, "We are a leading research university.")
    title = parse_jd(extract_text(_blob(doc), DocumentFormat.DOCX)).jd.title
    assert title == "We are a leading research university."


def test_list_marker_is_invisible_to_tier2_near_dup_shingles() -> None:
    """Tier-2 near-dup re-extracts raw text (``dedup.text_source: raw_clean``); the
    marker must not move a single shingle, or every Word-list document's near-dup
    edges would shift for a formatting reason."""
    plain = "Writes funding proposals.\nReviews proposal budgets with investigators."
    marked = (
        f"{LIST_ITEM_MARKER}Writes funding proposals.\n"
        f"{LIST_ITEM_MARKER}Reviews proposal budgets with investigators."
    )
    size = get_rules().dedup.shingle_size
    marked_hashes = shingle_hashes(marked, shingle_size=size, redact_boilerplate=False)
    plain_hashes = shingle_hashes(plain, shingle_size=size, redact_boilerplate=False)
    assert len(plain_hashes) > 0
    assert marked_hashes == plain_hashes


# ── Defect 2: the 400-character duty statement ───────────────────────────────


def test_a_long_duty_statement_survives_past_400() -> None:
    long_duty = "Coordinates " + "the research grant lifecycle and reporting, " * 20
    assert len(long_duty) > 800
    result = parse_jd(f"DUTIES AND RESPONSIBILITIES\n• {long_duty.strip()}\n")

    assert len(result.jd.duties[0].statement) == len(long_duty.strip())


def test_the_statement_cap_is_rulebook_data_and_fits_the_contract() -> None:
    seg = get_rules().segmentation
    ceiling = _max_length(SFUDuty, "statement")
    assert 400 < seg.duty_statement_max_chars <= ceiling


def test_the_caps_are_applied_from_the_rulebook(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Retune the knobs and the parser follows — no code constant in the way."""
    from src.jd_core import rules as rules_mod

    real = get_rules()
    tuned = real.model_copy(
        update={
            "segmentation": real.segmentation.model_copy(
                update={"duty_statement_max_chars": 50, "duty_max_count": 2}
            )
        }
    )
    monkeypatch.setattr(rules_mod, "get_rules", lambda: tuned)
    long_duty = "Coordinates " + "x " * 100
    result = parse_jd(
        f"DUTIES AND RESPONSIBILITIES\n• {long_duty}\n• Second duty.\n• Third duty.\n"
    )
    assert len(result.jd.duties) == 2
    assert len(result.jd.duties[0].statement) == 50


# ── Defect 3: the 12-function WJQ ceiling ────────────────────────────────────

_WJQ_HEAD = """SIMON FRASER UNIVERSITY & C.U.P.E., LOCAL 3338
WEIGHTED JOB QUESTIONNAIRE (WJQ) CUSTOM
1.  POSITION IDENTIFICATION
Department Position Title:
Program Assistant
3.  MAJOR FUNCTIONS
"""


def _wjq_with(major: int, minor: int) -> str:
    lines = [_WJQ_HEAD.rstrip("\n")]
    lines += [f"• Performs major function number {i}. (D)" for i in range(1, major + 1)]
    lines.append("4.  MINOR FUNCTIONS")
    lines += [f"• Performs minor function number {i}." for i in range(1, minor + 1)]
    lines.append("13.  QUALIFICATIONS")
    lines.append("High School graduation.")
    return "\n".join(lines) + "\n"


def test_a_fourteen_function_cupe_questionnaire_keeps_all_fourteen() -> None:
    """HR's own Dec-2024 CUPE sample carries 14 functions; v8 kept 12 (majors first),
    so the last minor functions vanished."""
    result = segment_wjq(_wjq_with(major=10, minor=4), get_rules().wjq)

    assert len(result.jd.duties) == 14
    assert result.jd.duties[-1].statement == "Performs minor function number 4"


def test_a_full_24_function_questionnaire_fits() -> None:
    """The form carries 12 major + 12 minor slots, and the Builder exports that many
    (HR-246) — a re-read must be able to hold what the Builder can write."""
    result = segment_wjq(_wjq_with(major=12, minor=12), get_rules().wjq)
    assert len(result.jd.duties) == 24


def test_the_duty_count_caps_are_rulebook_data_and_fit_the_contract() -> None:
    seg = get_rules().segmentation
    ceiling = _max_length(SFUJobDescription, "duties")
    assert 12 < seg.duty_max_count <= ceiling
    assert 24 <= seg.wjq_duty_max_count <= ceiling


def test_the_parser_version_moved() -> None:
    assert PARSER_VERSION == "jd_segmenter_v9"


def _max_length(model: type[object], field: str) -> int:
    fields = model.model_fields  # type: ignore[attr-defined]
    return int(
        next(
            m.max_length
            for m in fields[field].metadata
            if getattr(m, "max_length", None) is not None
        )
    )

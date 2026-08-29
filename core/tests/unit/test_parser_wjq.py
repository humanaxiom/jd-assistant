"""The CUPE / Weighted Job Questionnaire (WJQ) segmenter (Phase 3.4).

Two kinds of fixture: a hand-built synthetic WJQ document (docx-shaped, one cell per
line) for PRECISE assertions — frequency stripping, the lowercase ``(s)`` guard,
instruction-cruft removal, ``(CONTINUED)`` recurrence, the data-driven label mutation —
and three REAL archive files (`fixtures/wjq_*`) as end-to-end regression anchors.

Every behavioural claim is pinned so that a mutation of the shipped data or logic breaks
it: the label-rename test proves extraction reads ``wjq.yaml`` and not a hardcode, and
the marker-removal test proves the router, not the filename, decides the template.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.jd_bank.ingest.extract import extract_text_from_path
from src.jd_core.parser import ParseResult, parse_jd
from src.jd_core.parser.wjq import _match_heading, is_wjq, segment_wjq
from src.jd_core.rules import Rules, get_rules

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


@pytest.fixture(scope="module")
def rules() -> Rules:
    return get_rules()


# A synthetic WJQ document in the python-docx render shape (one table cell per line).
# Deliberately exercises: the id labels, the summary-instruction cruft, per-duty
# `(D)/(W)/(S)` markers, a lowercase `location(s)` (the false-positive trap), a
# `(CONTINUED)` recurrence, the KSA block cues, the contacts table, a Hay section, and
# the dropped APPROVAL section.
_WJQ = """SIMON FRASER UNIVERSITY & C.U.P.E., LOCAL 3338
WEIGHTED JOB QUESTIONNAIRE (WJQ) CUSTOM
PART 1: JOB DESCRIPTION
1.  POSITION IDENTIFICATION
Department Position Title:
Program Assistant
Department Name:
Registrar
Position Number(s):
00099999
Classification & Grade Approved:
Grade 9
2.  POSITION SUMMARY
A summary of the major functions of the position in three or four sentences.
Provides support to the Registrar across multiple location(s) on campus.
3.  MAJOR FUNCTIONS
List the duties and responsibilities of the position in order of frequency
(i.e., (D) Daily; (W) Weekly; (M) Monthly; (S) Semester)
Answers enquiries about registration at various location(s). (D)
Prepares weekly enrolment reports for the Registrar. (W)
3.  MAJOR FUNCTIONS (CONTINUED)
Reconciles term statistics at semester end. (S)
4.  MINOR FUNCTIONS
List duties and responsibilities that occur annually throughout the year.
Archives graduation records at year end.
8.  INTERNAL AND EXTERNAL CONTACTS
Type of Contact
Faculty and staff
External applicants and off campus vendors
13.  QUALIFICATIONS
Minimum required to satisfactorily perform the work.
Formal education: identify the highest level of formal schooling required.
High School graduation and a diploma in office administration.
In addition to the above qualifications, the number of years of minimum experience are:
2
Occupational Skills:  Identify skills required to perform the work.
Intermediate keyboarding skills.
Occupational Requirement(s): Identify non-skill requirements.
Ability to work flexible hours.
9.  IMPACT OF ERRORS
Errors in records can delay student registration.
14.  APPROVAL AND REVIEW
Name of Evaluating Supervisor
"""


@pytest.fixture()
def parsed(rules: Rules) -> ParseResult:
    return segment_wjq(_WJQ, rules.wjq)


# ── Detection / routing ──────────────────────────────────────────────────────


def test_marker_routes_to_the_wjq_path(rules: Rules) -> None:
    assert is_wjq(_WJQ, rules.wjq) is True
    assert parse_jd(_WJQ).template == "wjq"


def test_removing_the_marker_routes_to_jdfn_and_wjq_sections_vanish(
    rules: Rules,
) -> None:
    """Flip the guard: with no marker the document takes the JDFN path, which does not
    know the WJQ headings — so its duties do not parse and no frequency is ever set."""
    all_markers = rules.wjq.marker_primary + rules.wjq.marker_corroborating
    no_marker = "\n".join(
        line
        for line in _WJQ.splitlines()
        if not any(m.lower() in line.lower() for m in all_markers)
    )
    assert is_wjq(no_marker, rules.wjq) is False
    result = parse_jd(no_marker)
    assert result.template == "jdfn"
    assert all(d.frequency is None for d in result.jd.duties)


def test_a_jdfn_fixture_is_not_detected_as_wjq(rules: Rules) -> None:
    jdfn = (FIXTURES / "sfu_new_template.txt").read_text(encoding="utf-8")
    assert is_wjq(jdfn, rules.wjq) is False
    assert parse_jd(jdfn).template == "jdfn"


def test_a_jdfn_jd_that_only_cites_the_union_stays_jdfn(rules: Rules) -> None:
    """MUST-FIX 2 (reviewer): a genuine JDFN JD — with real JDFN headings — that merely
    MENTIONS "CUPE, Local 3338" in a duty must NOT route to WJQ. One loose union marker
    is below the corroboration bar and there is no WJQ title phrase, so it stays JDFN
    with its rich parse. Drop the `corroborating_min` guard (to 1) and this reds — the
    exact 69-file misroute the reviewer measured."""
    jdfn = (
        "SIMON FRASER UNIVERSITY\n"
        "JOB TITLE: Labour Relations Advisor\n"
        "DEPARTMENT: Human Resources\n"
        "POSITION SUMMARY\n"
        "Advises managers on collective agreements.\n"
        "DUTIES AND RESPONSIBILITIES\n"
        "- Interprets the CUPE, Local 3338 collective agreement for managers.\n"
        "SUPERVISION RECEIVED\n"
        "Reports to the Director, Employee Relations.\n"
        "MINIMUM ENTRANCE QUALIFICATIONS\n"
        "Bachelor's degree and three years of labour-relations experience.\n"
    )
    assert is_wjq(jdfn, rules.wjq) is False
    result = parse_jd(jdfn)
    assert result.template == "jdfn"
    assert result.jd.title == "Labour Relations Advisor"
    assert result.jd.duties  # a rich JDFN parse, not the empty WJQ misread


# ── Identification ───────────────────────────────────────────────────────────


def test_identification_fields(parsed: ParseResult) -> None:
    jd = parsed.jd
    assert jd.title == "Program Assistant"
    assert jd.department == "Registrar"
    assert jd.position_number == "00099999"
    assert jd.grade == "Grade 9"
    assert jd.employee_group == "cupe"


def test_title_reads_the_label_data_not_a_hardcode(rules: Rules) -> None:
    """Rename the title label in the data → the title is no longer found and falls back.
    Proves the extractor reads ``wjq.id_labels``, not a hardcoded column."""
    mutated = rules.wjq.model_copy(
        update={"id_labels": {**rules.wjq.id_labels, "title": ("No Such Label",)}}
    )
    assert segment_wjq(_WJQ, mutated).jd.title == "Untitled Position"


# ── Position summary ─────────────────────────────────────────────────────────


def test_heading_less_wjq_with_a_huge_id_block_does_not_raise(rules: Rules) -> None:
    """MUST-FIX 1 (reviewer): when a WJQ form omits the `POSITION SUMMARY` heading
    (common in legacy `.doc`), the fallback grabs the whole identification block — which
    routinely exceeds `position_summary`'s 4000-char ceiling. Uncapped that raised
    ValidationError on 568 real files and aborted the archive re-parse. `parse_jd` is
    contractually total, so the fallback must cap. Drop the `[:_MAX_SUMMARY]` cap in
    `_summary_fallback` and this reds with a ValidationError."""
    huge = " ".join(f"sentence number {i} of the role." for i in range(400))
    assert len(huge) > 4000
    text = f"WEIGHTED JOB QUESTIONNAIRE\n1.  POSITION IDENTIFICATION\n{huge}\n"
    result = segment_wjq(text, rules.wjq)  # must not raise
    assert result.template == "wjq"
    summary = result.jd.position_summary
    assert summary is not None
    assert len(summary) <= 4000


def test_summary_keeps_prose_and_drops_the_instruction(parsed: ParseResult) -> None:
    summary = parsed.jd.position_summary
    assert summary is not None
    assert "support to the Registrar" in summary
    assert "A summary of the major functions" not in summary
    # the lowercase `(s)` in the summary is untouched — it is not a frequency marker
    assert "location(s)" in summary


# ── Duties + frequency ───────────────────────────────────────────────────────


def test_duty_frequencies_are_stripped_and_stored(parsed: ParseResult) -> None:
    duties = parsed.jd.duties
    by_freq = {d.frequency: d.statement for d in duties}
    assert "daily" in by_freq and "weekly" in by_freq and "semester" in by_freq
    # the marker itself is gone from the statement
    assert all("(D)" not in d.statement and "(W)" not in d.statement for d in duties)


def test_lowercase_s_is_not_a_frequency(parsed: ParseResult) -> None:
    """`location(s)` occurs mid-sentence in a duty. It must survive verbatim, the duty
    must not be split on it, and its frequency comes from the trailing `(D)` — never
    from the `(s)`."""
    duty = next(d for d in parsed.jd.duties if "location(s)" in d.statement)
    assert duty.frequency == "daily"
    assert "Answers enquiries" in duty.statement


def test_continued_recurrence_is_concatenated(parsed: ParseResult) -> None:
    """The duty under `MAJOR FUNCTIONS (CONTINUED)` lands on the same section."""
    assert any(
        "Reconciles term statistics" in d.statement and d.frequency == "semester"
        for d in parsed.jd.duties
    )


def test_the_frequency_instruction_line_is_not_a_duty(parsed: ParseResult) -> None:
    assert not any("Daily; " in d.statement for d in parsed.jd.duties)
    assert not any("List the duties" in d.statement for d in parsed.jd.duties)


# ── Qualifications ───────────────────────────────────────────────────────────


def test_qualification_kinds(parsed: ParseResult) -> None:
    quals = parsed.jd.qualifications
    kinds = {q.kind for q in quals}
    assert {"education", "experience", "skill", "ability"} <= kinds
    education = next(q for q in quals if q.kind == "education")
    assert "High School" in education.text


# ── Relationships / context / Hay ────────────────────────────────────────────


def test_contacts_split_best_effort(parsed: ParseResult) -> None:
    rel = parsed.jd.relationships
    assert rel is not None
    assert rel.supervisory is None  # WJQ invents no supervisory signal
    assert any("Faculty" in c for c in rel.internal)
    assert any("off campus" in c.lower() for c in rel.external)


def test_hay_sections_go_to_additional_context(parsed: ParseResult) -> None:
    jd = parsed.jd
    assert jd.additional_context is not None
    assert "Errors in records" in jd.additional_context
    # decision_making / problem_solving are left EMPTY (no bogus Hay signal)
    assert jd.decision_making == []
    assert jd.problem_solving == []


def test_approval_section_is_dropped(parsed: ParseResult) -> None:
    assert "Evaluating Supervisor" not in (parsed.jd.additional_context or "")


def test_wjq_has_no_about_or_footer(parsed: ParseResult) -> None:
    jd = parsed.jd
    assert jd.about_sfu_present is False
    assert jd.territorial_acknowledgement_present is False
    assert jd.employment_equity_present is False


# ── Real archive fixtures (end-to-end regression anchors) ────────────────────


@pytest.mark.parametrize(
    "name",
    ["wjq_markers_sample.docx", "wjq_grouped_sample.doc", "wjq_cupe_sample.doc"],
)
def test_real_wjq_fixture_parses(name: str) -> None:
    text = extract_text_from_path(FIXTURES / name)
    result = parse_jd(text)
    assert result.template == "wjq"
    jd = result.jd
    assert jd.employee_group == "cupe"
    assert len(jd.duties) >= 5
    assert any(d.frequency for d in jd.duties)
    assert jd.decision_making == [] and jd.problem_solving == []
    assert jd.additional_context is not None


def test_the_docx_fixture_recovers_all_the_id_fields() -> None:
    """The `.docx` template carries `Department Position Title`, so the title is real
    (not the `Untitled Position` fallback the `.doc` renders take)."""
    text = extract_text_from_path(FIXTURES / "wjq_markers_sample.docx")
    jd = parse_jd(text).jd
    assert jd.title == "Directors Assistant"
    assert jd.department == "Curriculum & Instruction"
    assert jd.position_number == "01803"
    assert {"education", "experience", "skill", "ability"} <= {
        q.kind for q in jd.qualifications
    }
    assert {"daily", "weekly"} <= {d.frequency for d in jd.duties if d.frequency}


# --- the antiword COLUMN GAP (2026-08-22) --------------------------------------------


def test_a_heading_sharing_a_line_with_the_next_column_is_still_a_heading() -> None:
    """🔴 THE DEFECT THAT LOST 16% OF THE CUPE ARCHIVE'S DUTIES.

    `_cells` splits on `|`, which is how antiword renders a table it recognises. A
    MULTI-COLUMN layout it does not recognise comes out as fixed-width text with no
    pipes, so the heading and the cell to its right land on one physical line — exactly
    as below, taken from `19920428_00001201Clerk.doc`. Cleaned, that reads
    `1. POSITION IDENTIFICATION FOR USE BY HUMAN`, which equals no heading phrase, so
    the section never opened.

    MEASURED: 719 of 4,440 CUPE documents (16.2%) parsed to ZERO duties, against 2.2%
    on the APSA form — and the rewrite filled that silence with 1,219 invented duties
    across 153 drafts (HR-213).
    """
    wjq = get_rules().wjq
    line = " 1. POSITION IDENTIFICATION                        For Use by Human"
    assert _match_heading(line, wjq) == "position_identification"


def test_a_duty_that_merely_starts_with_a_heading_phrase_is_not_a_heading() -> None:
    """The protection the original exact match existed for, and the reason the column
    gap is TWO spaces rather than a plain prefix: running prose continues after ONE
    space, so a duty opening with a heading's words is still not the heading."""
    wjq = get_rules().wjq
    section = next(iter(wjq.section_headings))
    phrase = wjq.section_headings[section][0]
    assert _match_heading(f"{phrase} required to complete the task", wjq) is None


def test_a_heading_alone_on_its_line_still_matches() -> None:
    """The unchanged case — the exact match that already worked must keep working, or
    this fix trades one cohort's duties for another's."""
    wjq = get_rules().wjq
    section = next(iter(wjq.section_headings))
    phrase = wjq.section_headings[section][0]
    assert _match_heading(f"  {phrase}  ", wjq) == section


def test_internal_whitespace_in_a_heading_is_tolerated() -> None:
    """antiword's fixed-width output also stretches headings — `1. POSITION
    IDENTIFICATION` appears with two and three internal spaces across the archive."""
    wjq = get_rules().wjq
    assert _match_heading("1. POSITION   IDENTIFICATION", wjq) == (
        "position_identification"
    )


def test_a_heading_with_internal_whitespace_and_a_column_beside_it_matches() -> None:
    """🔴 THE COLUMN GAP AND THE INTERNAL RUN, TOGETHER — the variant the first fix
    left behind.

    `_match_heading` accepted a heading either exactly (whitespace-collapsed) or as a
    RAW prefix before a column gap. A heading carrying BOTH — antiword stretches the
    words apart AND prints the next column beside it — satisfied neither: the collapsed
    compare failed on the trailing column, and `startswith` failed on the internal run.

    MEASURED 2026-08-22 over a 400-file archive sample (122 WJQ documents): 4 documents
    lost 11 heading lines to this combination, and they are the DUTY-BEARING ones —
    `4. MINOR  FUNCTIONS`, `MAJOR   FUNCTIONS   CONTINUED`, `2. POSITION  SUMMARY`.
    Same root cause as the case above, one variant over.
    """
    wjq = get_rules().wjq
    assert (
        _match_heading(
            "1. POSITION   IDENTIFICATION                 For Use by Human", wjq
        )
        == "position_identification"
    )
    assert (
        _match_heading(
            "4.    MINOR  FUNCTIONS    (List duties and responsibilities that occur",
            wjq,
        )
        == "minor_functions"
    )
    assert _match_heading("MAJOR   FUNCTIONS   (CONTINUED)", wjq) == "major_functions"


# --- The form's own spelling of its title label ---------------------------------------


@pytest.mark.parametrize(
    "label",
    [
        "Department's Position Title",  # straight apostrophe — the archive's commonest
        "Department’s Position Title",  # the curly one Word inserts
        "Departments Position Title",  # and the apostrophe-less spelling
        "Department Position Title",  # the spelling already shipped
        "Position Title",
    ],
)
def test_every_spelling_of_the_title_label_is_read(label: str) -> None:
    """🔴 MEASURED 2026-08-29 against the raw archive: **47.6% of CUPE documents (2,046
    of 4,300) have no title at all** — they carry the sentinel `Untitled Position` —
    while every other bargaining unit is at 0.0%. It is not a general title problem; it
    is this form.

    `_extract_label` matches a cell EXACTLY (case-insensitive, colon-stripped), and
    `wjq.id_labels.title` listed only "Department Position Title" / "Position Title".
    The archive's dominant spelling is the POSSESSIVE — "Department's Position Title" —
    which therefore matched nothing. Reading the source files for 500 placeholder
    documents, 17.4% carry a title under a spelling the rulebook did not know, with the
    value correctly in its own next cell.

    ⚠ 1,395 of those placeholders are ALREADY inside drafts, so this silence did not
    stay in the archive.
    """
    doc = _WJQ.replace("Department Position Title:", f"{label}:")
    assert parse_jd(doc).jd.title == "Program Assistant"


def test_a_title_label_with_no_value_still_yields_the_sentinel() -> None:
    """The other half: recovering MORE titles must not start inventing them.

    A label whose next cell is another label has no value, and the document must keep
    saying so. `Untitled Position` is an honest placeholder; a wrong title is not, and
    the archive contains cells where the neighbouring column is a person's name.
    """
    doc = _WJQ.replace(
        "Department Position Title:\nProgram Assistant",
        "Department's Position Title:\nDepartment Name:",
    )
    assert parse_jd(doc).jd.title == "Untitled Position"


# --- Label and value in ONE cell (antiword's fixed-width render) ----------------------


def test_an_inline_label_and_value_in_one_cell_is_read() -> None:
    """🔴 THE ACTUAL CAUSE of 47.6% of CUPE documents having no title.

    `_extract_label` takes the value from the NEXT cell, which is right for the
    python-docx render. antiword's fixed-width render of the same form puts the label
    and its value in ONE cell, so there is no next cell and the title fell through to
    the sentinel. Verbatim from the archive's identification sections:

        'Department Position Title: Program Assistant'
        'Department Position Title: Budget Assistant Department Name/Section:'
        'Department Position Title: Clinical Office Assistant Department'

    ⚠ Found only by re-measuring after the FIRST fix recovered ZERO. The earlier probe
    scanned the whole document and saw the possessive spelling in the form's blank
    template header; the parser reads the identification SECTION, where the spelling is
    the one already supported. A probe whose scope does not match the parser's scope
    measures a different question and answers it confidently.
    """
    doc = _WJQ.replace(
        "Department Position Title:\nProgram Assistant",
        "Department Position Title: Program Assistant",
    )
    assert parse_jd(doc).jd.title == "Program Assistant"


@pytest.mark.parametrize(
    ("cell", "expected"),
    [
        ("Department Position Title: Program Assistant", "Program Assistant"),
        # The neighbouring column bleeds in; it must be cut at the next label, not kept.
        (
            "Department Position Title: Budget Assistant Department Name/Section:",
            "Budget Assistant",
        ),
        (
            "Department Position Title: Clinical Office Assistant Department",
            "Clinical Office Assistant",
        ),
    ],
)
def test_an_inline_value_is_cut_at_the_next_label(cell: str, expected: str) -> None:
    """Recovering the value must not swallow the column printed beside it.

    In the fixed-width render the next field's LABEL lands in the same cell. Keeping it
    would write "Budget Assistant Department Name/Section:" into the Bank as a job title
    — a confident wrong value, which is worse than the honest sentinel it replaced.
    """
    doc = _WJQ.replace("Department Position Title:\nProgram Assistant", cell)
    assert parse_jd(doc).jd.title == expected


@pytest.mark.parametrize(
    ("cell", "expected"),
    [
        # Trailing punctuation is noise from the render, not part of the title.
        ("Department Position Title: Helpdesk Technician,", "Helpdesk Technician"),
        ("Department Position Title: Cashier /", "Cashier"),
        # ...but a dangling CONNECTOR means the value was cut off by the column width.
        # "Housing &" is not a job title; the honest answer is the sentinel.
        ("Department Position Title: Housing &", "Untitled Position"),
        ("Department Position Title: Acquisitions Approvals &", "Untitled Position"),
        ("Department Position Title: Research and", "Untitled Position"),
    ],
)
def test_a_truncated_inline_value_is_refused_not_stored(
    cell: str, expected: str
) -> None:
    """MEASURED on the 811 titles the inline fix recovered: 3.5% ended mid-phrase, and
    ~22 of them were fragments left by antiword's column width — "Housing &",
    "Research &", "Acquisitions Approvals &".

    A fragment is a CONFIDENT WRONG VALUE. `Untitled Position` announces its own
    failure, and every surface already reports it as a gap; "Housing &" would be read as
    a job title. Recovering more titles must not mean inventing them, so a value whose
    last token is a connector is refused and the sentinel stands.
    """
    doc = _WJQ.replace("Department Position Title:\nProgram Assistant", cell)
    assert parse_jd(doc).jd.title == expected


@pytest.mark.parametrize(
    ("cell", "expected"),
    [
        # Underscores are the form's fill-in rule, not part of the title.
        (
            "Department Position Title: _Departmental Assistant_____",
            "Departmental Assistant",
        ),
        # "Approved by" is the sign-off column printed beside this one.
        (
            "Department Position Title: Departmental Assistant Approved by",
            "Departmental Assistant",
        ),
    ],
)
def test_form_furniture_is_stripped_from_a_recovered_title(
    cell: str, expected: str
) -> None:
    """Found by reading the 807 recovered titles rather than trusting the count.

    The fixed-width render leaves the blank form's own furniture in the cell: the
    underscore fill-in rule, and the sign-off column's "Approved by". Both are in
    the archive and neither belongs in a job title.
    """
    doc = _WJQ.replace("Department Position Title:\nProgram Assistant", cell)
    assert parse_jd(doc).jd.title == expected

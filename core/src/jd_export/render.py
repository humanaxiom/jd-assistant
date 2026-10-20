"""Render an SFU JD to the official ``.docx`` template (Phase 5.7).

The composer/export half of the plan (§2.5). ``render_sfu_docx`` is the one entry point
and picks the FORM by :func:`~src.jd_core.quality.validators.template_of` (Track J1): a
CUPE (WJQ) JD goes to :mod:`src.jd_export.cupe` — HR's CUPE form, no APSA footer — and
every other JD to :func:`render_jdfn_docx`, which composes an
:class:`~src.jd_core.models.parsed_jd.SFUJobDescription` into a Word document laid out
as HR's 2024 template (``APSA_APEX_POLY_JD Template_20240530.docx``) and SFU's
formatting standard (rulebook Part 10.1):

* **The identification table in the page header** (Track J4) — banner, Position
  Title, Position #, Employee Group, the two dates (blank: not in the model), then the
  supervisor's title and position # (``apsa_form.yaml``, HR-258).
* **About SFU first** (Track J4), from ``boilerplate.yaml`` as it stands (HR-104 open).
* **Times New Roman, size 10** — set on the ``Normal`` style, so every paragraph
  inherits it.
* **Bold section headings in template order**, in the PARSER's vocabulary
  (``CANONICAL_HEADING``, which is also the template's wording); **empty sections are
  dropped** (Part 10.1: "Additional Contextual Info Section: DELETE if not used").
* **Typed bullets** (``apsa_form.bullet_glyph``, HR-259) for duties, decisions,
  problems, contacts and qualifications; each duty's **"How and why" clauses** as Word
  sub-bullets beneath it. Typed because a Word list bullet never reaches the extracted
  text: before J4, 1,798 of 1,876 live roles re-read with their duties run into one.
* Percentage allocations already live in the duty text as ``(NN%)`` (the composer
  renders them there), so they carry through verbatim.
* The **mandated footer** — the territorial acknowledgement + the Employment-Equity
  statement — after Qualifications, as on the template, injected from the rulebook
  boilerplate (:func:`~src.jd_core.rules.get_rules`), the single source of that text,
  never a literal here (CLAUDE.md: "footer wording lives in a single config
  constant"), under the one heading the template lacks and the parser needs (HR-256).
* **Additional Contextual Information last**, as on the template.

The Bank reads its own export back: ``extract_text`` -> ``parse_jd`` returns every
field the parser can read (``tests/export_roundtrip.py``; the live smoke checks every
current non-CUPE role).

⚠ The footer wording is a Phase-6 sign-off item — verify it against SFU's current
official text before any external distribution. It is data in ``boilerplate.yaml``,
so that verification is a one-file review, not a code change.

Deterministic and pure of I/O beyond building bytes: same JD (+ rulebook) → same
document. Nothing here validates or publishes — export is a rendering of whatever
draft it is given.
"""

from __future__ import annotations

from io import BytesIO

from docx import Document
from docx.document import Document as DocxDocument
from docx.shared import Inches, Pt

from src.jd_core.models.parsed_jd import (
    SFUDuty,
    SFUJobDescription,
    SFUQualification,
    SFURelationships,
)
from src.jd_core.models.quality import WJQ_TEMPLATE
from src.jd_core.parser.headings import (
    CANONICAL_HEADING,
    CANONICAL_REL_LABEL,
    SectionKey,
)
from src.jd_core.quality.validators import template_of
from src.jd_core.rules import ApsaForm, Rules, get_rules
from src.jd_export.cupe import render_cupe_docx

_BODY_FONT = "Times New Roman"
_BODY_SIZE = Pt(10)
#: The template's "How and why" sub-bullets: Word list formatting ON PURPOSE (its
#: bullet never reaches the extracted text, so a clause re-reads inside its duty).
_SUB_BULLET_STYLE = "List Bullet 2"
#: Hanging indent of a typed-bullet item — the bullet sits in it, the text after it.
_ITEM_INDENT = Inches(0.25)
_HEADER_TABLE_WIDTH = Inches(6.5)


def _set_base_font(doc: DocxDocument) -> None:
    """Times New Roman 10 on the ``Normal`` style — every paragraph inherits it."""
    font = doc.styles["Normal"].font
    font.name = _BODY_FONT
    font.size = _BODY_SIZE


def _header(doc: DocxDocument, text: str) -> None:
    paragraph = doc.add_paragraph()
    run = paragraph.add_run(text)
    run.bold = True


def _heading(doc: DocxDocument, section: SectionKey) -> None:
    """A bold section heading in the PARSER's own vocabulary (``CANONICAL_HEADING``),
    which is also the 2024 template's wording — so the Bank reads its export back."""
    _header(doc, CANONICAL_HEADING[section])


def _item(doc: DocxDocument, text: str, form: ApsaForm) -> None:
    """One list item: the typed bullet (HR-259), a tab, the text, on a hanging indent.

    Typed, not Word list formatting: a Word bullet never reaches the extracted text, so
    the parser joined every duty into one (1,798 of 1,876 live roles, pre-J4). Normal
    style, so Word draws no second bullet beside the typed one."""
    paragraph = doc.add_paragraph(f"{form.bullet_glyph}\t{text}")
    fmt = paragraph.paragraph_format
    fmt.left_indent = _ITEM_INDENT
    fmt.first_line_indent = -_ITEM_INDENT
    fmt.tab_stops.add_tab_stop(_ITEM_INDENT)


def _bullets(
    doc: DocxDocument, section: SectionKey, lines: list[str], form: ApsaForm
) -> None:
    """A heading + one item per non-empty line. A no-op if nothing is left after
    dropping blanks, so an empty section never emits a lone heading."""
    kept = [line for line in lines if line.strip()]
    if not kept:
        return
    _heading(doc, section)
    for line in kept:
        _item(doc, line, form)


def _paragraph_section(
    doc: DocxDocument, section: SectionKey, text: str | None
) -> None:
    if not (text or "").strip():
        return
    _heading(doc, section)
    doc.add_paragraph(text or "")


def _duties(doc: DocxDocument, duties: list[SFUDuty], form: ApsaForm) -> None:
    """The template's "ACTION VERB… WHAT by" items, each followed by its "How and why"
    clauses as Word SUB-bullets — deliberately formatting-only, so they re-read as part
    of their duty rather than as duties of their own."""
    kept = [d for d in duties if _duty_line(d).strip()]
    if not kept:
        return
    _heading(doc, SectionKey.DUTIES)
    for duty in kept:
        _item(doc, _duty_line(duty), form)
        for clause in duty.how_why:
            if clause.strip():
                doc.add_paragraph(clause.strip(), style=_SUB_BULLET_STYLE)


def _identification(doc: DocxDocument, jd: SFUJobDescription, form: ApsaForm) -> None:
    """The template's page header: banner, then one label | value row per field
    (HR-258). A field the draft does not carry prints its label with an EMPTY cell —
    never guessed. The ingest path reads exactly this header back
    (``extract._docx_identification_block``)."""
    header = doc.sections[0].header
    first = header.paragraphs[0]
    for index, line in enumerate(form.banner):
        paragraph = first if index == 0 else header.add_paragraph()
        paragraph.add_run(line).bold = True
    group = (jd.employee_group or "").upper()
    values: dict[str, str | None] = {
        "title": jd.title,
        "position_number": jd.position_number,
        "employee_group": group or None,
        "initial_effective_date": None,
        "latest_revision_date": None,
        "supervisor_title": jd.supervisor_title,
        "supervisor_position_number": jd.supervisor_position_number,
    }
    table = header.add_table(rows=len(values), cols=2, width=_HEADER_TABLE_WIDTH)
    for row, (field, value) in zip(table.rows, values.items(), strict=True):
        row.cells[0].text = form.id_labels[field]  # type: ignore[index]
        row.cells[1].text = (value or "").strip()


def _about_sfu(doc: DocxDocument, rules: Rules) -> None:
    """The pre-populated About SFU block, from ``boilerplate.yaml`` AS IT STANDS —
    always, like the footer (mandated on every APSA JD). ⚠ HR-104 is open and the 2024
    template carries a different paragraph; this prints the rulebook's, not a guess."""
    _heading(doc, SectionKey.ABOUT_SFU)
    for passage in rules.boilerplate.about_sfu:
        doc.add_paragraph(passage)


def _duty_line(duty: SFUDuty) -> str:
    """The duty as one bullet. The statement usually already leads with the action
    verb (the composer/merge write it that way); prepend the verb only when it does
    not, so a duty never doubles or drops its verb."""
    statement = duty.statement.strip()
    verb = duty.action_verb.strip()
    if verb and not statement.lower().startswith(verb.lower()):
        return f"{verb} {statement}"
    return statement


def _qual_line(qual: SFUQualification) -> str:
    """The qualification as one bullet, with its Toolkit modifier prefixed when it is
    not already part of the text."""
    text = qual.text.strip()
    modifier = (qual.modifier or "").strip()
    if modifier and modifier.lower() not in text.lower():
        return f"{modifier} {text}"
    return text


def _relationships(
    doc: DocxDocument, rel: SFURelationships | None, form: ApsaForm
) -> None:
    """Each line carries the sub-label the parser reads (``CANONICAL_REL_LABEL``). The
    pre-J4 ``Internal:`` / ``External:`` were labels it did not know, so every contact
    re-read as supervisory prose."""
    if rel is None:
        return
    label = CANONICAL_REL_LABEL
    lines: list[str] = []
    if (rel.supervisory or "").strip():
        lines.append(f"{label['supervisory']}: {rel.supervisory}")
    lines += [f"{label['internal']}: {c}" for c in rel.internal if c.strip()]
    lines += [f"{label['external']}: {c}" for c in rel.external if c.strip()]
    _bullets(doc, SectionKey.RELATIONSHIPS, lines, form)


def _footer(doc: DocxDocument, rules: Rules) -> None:
    """Inject the mandated territorial acknowledgement + Employment-Equity statement
    from the rulebook boilerplate — always, regardless of the draft's presence flags
    (the footer is required on every published JD) — under the one heading the
    template does not have and the parser needs (HR-256)."""
    boilerplate = rules.boilerplate
    _header(doc, rules.apsa_form.footer_heading)
    for passage in boilerplate.territorial_acknowledgement:
        doc.add_paragraph(passage)
    for passage in boilerplate.employment_equity:
        doc.add_paragraph(passage)


def render_sfu_docx(jd: SFUJobDescription, *, rules: Rules | None = None) -> bytes:
    """Compose ``jd`` into the ``.docx`` of ITS OWN SFU form and return the bytes.

    The single public entry point (Track J1): callers never branch on the form. The
    form is :func:`~src.jd_core.quality.validators.template_of` — the same separator the
    validator judges the JD by — so a CUPE (WJQ) JD exports on HR's CUPE form
    (:func:`~src.jd_export.cupe.render_cupe_docx`: no APSA footer, CUPE 3338 Art. 15.04)
    and every other JD on the APSA/APEX/Poly layout (:func:`render_jdfn_docx`, its
    content pinned by ``tests/fixtures/golden_export/apsa_export_v1.json`` since J4).
    Deterministic."""
    if template_of(jd) == WJQ_TEMPLATE:
        return render_cupe_docx(jd, rules=rules)
    return render_jdfn_docx(jd, rules=rules)


def render_jdfn_docx(jd: SFUJobDescription, *, rules: Rules | None = None) -> bytes:
    """Compose ``jd`` into an APSA/APEX/Poly (JDFN) ``.docx`` and return its bytes.

    Laid out as HR's 2024 template (``APSA_APEX_POLY_JD Template_20240530.docx``):
    the identification table in the page header; About SFU; the sections in template
    order (empty ones dropped); the mandated footer after Qualifications; Additional
    Contextual Information last. Built so the Bank's own ingest path reads it back
    (Track J4): headings in the parser's vocabulary, typed bullets. Deterministic."""
    rulebook = rules if rules is not None else get_rules()
    form = rulebook.apsa_form
    doc = Document()
    _set_base_font(doc)

    _identification(doc, jd, form)
    _about_sfu(doc, rulebook)
    _paragraph_section(doc, SectionKey.POSITION_SUMMARY, jd.position_summary)
    _duties(doc, list(jd.duties), form)
    _bullets(doc, SectionKey.DECISION_MAKING, list(jd.decision_making), form)
    _bullets(doc, SectionKey.PROBLEM_SOLVING, list(jd.problem_solving), form)
    _relationships(doc, jd.relationships, form)
    _bullets(
        doc,
        SectionKey.QUALIFICATIONS,
        [_qual_line(q) for q in jd.qualifications],
        form,
    )
    _footer(doc, rulebook)
    _paragraph_section(doc, SectionKey.ADDITIONAL_CONTEXT, jd.additional_context)

    buffer = BytesIO()
    doc.save(buffer)
    return buffer.getvalue()

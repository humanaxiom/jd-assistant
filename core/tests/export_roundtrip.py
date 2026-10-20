"""The export round-trip ORACLE, shared by the unit suite and the live smoke (Track J1).

The property: a JD exported to ``.docx`` and then read back by the Bank's OWN ingest
path (``extract_text`` -> ``parse_jd``) must come back with everything the parser is
able to read. These helpers return a list of human-readable LOSSES (empty = the round
trip holds), so a failure names every field that did not survive rather than the first.

Written independently of ``jd_export``: nothing here imports the renderer's helpers,
so a renderer bug cannot be mirrored into the oracle and agree with itself. What it
does lean on is the PARSER's documented normalisation (whitespace collapsed, ``(NN%)``
stripped), because that is the reader whose verdict the property is about.

What "survives" means, field by field — and where it is deliberately weaker than
equality, it says why:

* identity fields (title, department, position number, employee group) — **equal**;
* position summary — **equal** word for word;
* duties — **same count, same order, same frequency**, and each re-read statement holds
  the original's words (verb + statement + how/why) in order. ``how_why`` cannot come
  back as its own field: the WJQ parser has never filled it, so the form prints it as
  part of the duty sentence (HR's form asks for "what + how + why" in one line);
* contacts — every original contact comes back (internal and external pooled: the form
  has one "Type of Contact" column, and the parser's internal/external split is a
  documented best-effort keyword guess). Extra rows are tolerated — see
  :func:`cupe_round_trip_losses`;
* qualifications — every original line comes back with the kind the form's block maps
  it to (``knowledge`` reads back as ``skill``; ``security`` as ``ability``);
* point-factor sections (5-7, 9-12) — every WORD of the original section comes back in
  the same section. Word-multiset containment, not equality, because the form itself
  prints its own instructions and options around the content.

Track J2 — an AUTHORED draft's CUPE form block (``wjq_form``):

* minor functions come back AFTER the majors in the one duty list the parser builds
  (it merges sections 3 and 4) — same count, order and words. ⚠ The parser stops at
  twelve (``segmenter._MAX_DUTIES``), so more than twelve functions re-read short; this
  oracle REPORTS that as a loss rather than excusing it, and a caller that knows it is
  past the ceiling asserts the exact message;
* every ticked level comes back as ``<ticked glyph> <option>`` in its section's text;
* every table row's words (item + duration / frequency / hours) come back in its
  section (contacts: the contact itself, as above);
* certification comes back as ``education`` (HR's prompt sits in the education cue),
  Occupational Requirement(s) as ``ability``.

What the PARSER cannot carry, and so is checked on the export TEXT instead
(:func:`cupe_export_text_losses`): the identification fields it has no label for, the
"completed by" tick, and the equivalency tick (its option lines are dropped as form
instructions, ``wjq.instruction_markers``).
"""

from __future__ import annotations

import re
from collections import Counter

from src.jd_core.models.parsed_jd import SFUJobDescription, WJQRow
from src.jd_core.parser.segmenter import _PERCENT_RE
from src.jd_core.rules import Rules

_WORD = re.compile(r"[a-z0-9]+")

#: The parser's own duty-statement ceiling (``segmenter._MAX_DUTY_STMT``) — a rendered
#: duty longer than this is legitimately cut on re-read.
_MAX_DUTY_STMT = 400

#: Which kind each original qualification kind reads back as, through the CUPE form.
_CUPE_KIND_BACK = {
    "education": "education",
    "experience": "experience",
    "knowledge": "skill",
    "skill": "skill",
    "ability": "ability",
    "security": "ability",
}


def words(text: str | None) -> list[str]:
    """``text`` as lowercase alphanumeric words, ``(NN%)`` allocations removed."""
    return _WORD.findall(_PERCENT_RE.sub(" ", text or "").lower())


def _norm(text: str | None) -> str:
    return " ".join(words(text))


def _contained(needle: list[str], haystack: list[str]) -> bool:
    """Multiset containment: every word of ``needle`` occurs in ``haystack`` at least
    as often."""
    have = Counter(haystack)
    return not (Counter(needle) - have)


def _duty_words(verb: str, statement: str, how_why: list[str]) -> list[str]:
    """The words a duty should read back as: verb (when the statement does not already
    lead with it), statement, then its how/why clauses."""
    lead: list[str] = []
    if verb.strip() and not statement.strip().lower().startswith(verb.strip().lower()):
        lead = words(verb)
    tail: list[str] = []
    for clause in how_why:
        tail += words(clause)
    return lead + words(statement) + tail


def split_context(context: str | None, rules: Rules) -> dict[str, list[str]]:
    """``additional_context`` as ``{section: words}``, split on the canonical WJQ
    headings both the parser and the assembler write on their own line. Text before
    the first heading belongs to the first point-factor section (the clone
    transform's documented rule)."""
    headings = {rules.wjq.section_headings[s][0]: s for s in rules.wjq.context_sections}
    current = rules.wjq.context_sections[0]
    out: dict[str, list[str]] = {}
    for line in (context or "").splitlines():
        if line.strip() in headings:
            current = headings[line.strip()]
            out.setdefault(current, [])
            continue
        out.setdefault(current, []).extend(words(line))
    return out


def cupe_round_trip_losses(
    original: SFUJobDescription, reparsed: SFUJobDescription, rules: Rules
) -> list[str]:
    """Every way ``reparsed`` failed to bring back what ``original`` held. Empty list =
    the CUPE round trip holds."""
    losses: list[str] = []
    if reparsed.employee_group != "cupe":
        losses.append(f"employee_group came back {reparsed.employee_group!r}")
    for field in ("title", "department", "position_number"):
        want = (getattr(original, field) or "").strip() or None
        got = (getattr(reparsed, field) or "").strip() or None
        if want != got and not (field == "title" and want is None):
            losses.append(f"{field}: {want!r} came back as {got!r}")
    if _norm(original.position_summary) != _norm(reparsed.position_summary):
        losses.append("position_summary changed")

    extra = original.wjq_form
    # The parser reads section 4 into the same list, after section 3 (J2).
    exported = [*original.duties, *(extra.minor_functions if extra else [])]
    if len(exported) != len(reparsed.duties):
        losses.append(
            f"duties: {len(exported)} exported, {len(reparsed.duties)} re-read"
        )
    for i, (src, back) in enumerate(
        zip(exported, reparsed.duties, strict=False), start=1
    ):
        if src.frequency != back.frequency:
            losses.append(
                f"duty {i}: frequency {src.frequency!r} -> {back.frequency!r}"
            )
        want = _duty_words(src.action_verb, src.statement, list(src.how_why))
        got = words(back.statement)
        if got == want:
            continue
        # The parser cuts a statement at its ceiling; a cut duty must still be a
        # faithful PREFIX (its last word may be split mid-word).
        if (
            len(back.statement) >= _MAX_DUTY_STMT - 1
            and got[:-1] == want[: len(got) - 1]
        ):
            continue
        losses.append(f"duty {i}: {want[:12]}... came back as {got[:12]}...")

    rel_src = original.relationships
    rel_back = reparsed.relationships
    src_contacts = Counter(
        _norm(c)
        for c in ([*rel_src.internal, *rel_src.external] if rel_src else [])
        if _norm(c)
    )
    back_contacts = Counter(
        _norm(c) for c in ([*rel_back.internal, *rel_back.external] if rel_back else [])
    )
    missing_contacts = src_contacts - back_contacts
    if missing_contacts:
        losses.append(f"contacts lost: {sorted(missing_contacts)}")

    src_quals = Counter(
        (_norm(_qual_text(q.text, q.modifier)), _CUPE_KIND_BACK[q.kind])
        for q in original.qualifications
    )
    back_quals = Counter((_norm(q.text), q.kind) for q in reparsed.qualifications)
    missing_quals = src_quals - back_quals
    if missing_quals:
        losses.append(f"qualifications lost or re-kinded: {sorted(missing_quals)}")

    src_ctx = split_context(original.additional_context, rules)
    back_ctx = split_context(reparsed.additional_context, rules)
    form = rules.cupe_form
    extras = {
        form.supervisory_section: words(
            rel_src.supervisory if rel_src is not None else None
        ),
        form.decision_making_section: [
            w for line in original.decision_making for w in words(line)
        ],
        form.problem_solving_section: [
            w for line in original.problem_solving for w in words(line)
        ],
    }
    if extra is not None:
        extras["effort"] = extras.get("effort", []) + _row_words(extra.effort)
        extras["working_conditions"] = extras.get("working_conditions", []) + [
            *_row_words(extra.locations),
            *_row_words(extra.uncomfortable),
            *_row_words(extra.hazards),
        ]
    for section in rules.wjq.context_sections:
        want_words = src_ctx.get(section, []) + extras.get(section, [])
        if want_words and not _contained(want_words, back_ctx.get(section, [])):
            missing = Counter(want_words) - Counter(back_ctx.get(section, []))
            losses.append(f"{section}: words lost {sorted(missing)[:10]}")
    if extra is not None:
        losses += _form_block_losses(original, reparsed, rules)
    return losses


def _row_words(rows: list[WJQRow]) -> list[str]:
    out: list[str] = []
    for row in rows:
        for value in (row.item, row.duration, row.frequency, row.hours):
            out += words(value)
    return out


def raw_sections(context: str | None, rules: Rules) -> dict[str, str]:
    """``additional_context`` as ``{section: whitespace-collapsed raw text}`` — for the
    checks that need more than words (a tick glyph is not a word)."""
    headings = {rules.wjq.section_headings[s][0]: s for s in rules.wjq.context_sections}
    current = rules.wjq.context_sections[0]
    out: dict[str, list[str]] = {}
    for line in (context or "").splitlines():
        if line.strip() in headings:
            current = headings[line.strip()]
            out.setdefault(current, [])
            continue
        out.setdefault(current, []).append(line)
    return {k: " ".join(" ".join(v).split()) for k, v in out.items()}


def _form_block_losses(
    original: SFUJobDescription, reparsed: SFUJobDescription, rules: Rules
) -> list[str]:
    """J2: the parts of ``wjq_form`` the parser CAN read back."""
    extra = original.wjq_form
    assert extra is not None
    losses: list[str] = []
    form = rules.cupe_form
    sections = raw_sections(reparsed.additional_context, rules)
    for section in (
        "level_of_independence",
        "training_exercised",
        "direction_exercised",
        "continuing_education",
    ):
        options = form.checkbox_options[section]  # type: ignore[index]
        text = sections.get(section, "")
        for letter in getattr(extra, section):
            option = " ".join(options[ord(letter) - ord("A")].split())
            if f"{form.checkbox_ticked_glyph} {option}" not in text:
                losses.append(f"{section}: tick on level {letter} lost")
    back_kinds = Counter((_norm(q.text), q.kind) for q in reparsed.qualifications)
    for text, kind in (
        *((c, "education") for c in extra.certification),
        *((r, "ability") for r in extra.occupational_requirements),
    ):
        if back_kinds[(_norm(text), kind)] < 1:
            losses.append(f"qualification {text!r} did not come back as {kind}")
    return losses


def cupe_export_text_losses(
    jd: SFUJobDescription, lines: list[str], rules: Rules
) -> list[str]:
    """Every part of an authored draft's CUPE form block (``wjq_form``) that is missing
    from the export's extracted TEXT — the Bank's own ``extract_text`` lines, in
    document order. Covers what the parser cannot carry (identification, the
    completed-by and equivalency ticks) as well as what it can, so a caller can assert
    "nothing dropped on export" independently of the parser's ceilings. Also: no APSA
    footer, and HR's box blank. Empty list = the export holds everything."""
    losses: list[str] = []
    form = rules.cupe_form
    extra = jd.wjq_form
    norm = [" ".join(ln.split()) for ln in lines]
    have = set(norm)

    def need(text: str, what: str) -> None:
        if " ".join(text.split()) not in have:
            losses.append(f"{what}: {text!r} not on the export")

    body = "\n".join(lines)
    boilerplate = rules.boilerplate
    for passage in (
        *boilerplate.territorial_acknowledgement,
        *boilerplate.employment_equity,
        *boilerplate.about_sfu,
    ):
        if passage in body:
            losses.append("APSA boilerplate printed on the CUPE form")
            break
    # Each HR-box label is followed by the NEXT label on the form, never a value
    # (python-docx drops an empty cell from the extracted text).
    labels = {*form.id_labels.values(), *form.hr_box_labels, form.completed_by_label}
    for label in form.hr_box_labels:
        if label in have:
            i = norm.index(label)
            nxt = norm[i + 1] if i + 1 < len(norm) else ""
            if nxt and nxt not in labels:
                losses.append(f"HR box {label!r} is not blank (next: {nxt!r})")
    if extra is None:
        return losses

    for value, what in (
        (extra.current_classification, "current classification"),
        (extra.supervisor_title, "supervisor title"),
        (extra.date_completed.isoformat() if extra.date_completed else None, "date"),
    ):
        if value:
            need(value, what)
    if extra.completed_by is not None:
        option = form.completed_by_options[0 if extra.completed_by == "employee" else 1]
        need(f"{form.checkbox_ticked_glyph} {option}", "completed by")

    # Minor functions: under section 4's heading and before section 5's.
    minor_at = _index_of(norm, rules.wjq.section_headings["minor_functions"][0])
    level_at = _index_of(norm, rules.wjq.section_headings["level_of_independence"][0])
    for duty in extra.minor_functions:
        found = [
            i
            for i, ln in enumerate(norm)
            if " ".join(duty.statement.split()) in ln and minor_at < i < level_at
        ]
        if not found:
            losses.append(f"minor function {duty.statement[:40]!r} not under section 4")
    for section in (
        "level_of_independence",
        "training_exercised",
        "direction_exercised",
        "continuing_education",
    ):
        options = form.checkbox_options[section]  # type: ignore[index]
        for letter in getattr(extra, section):
            need(
                f"{form.checkbox_ticked_glyph} {options[ord(letter) - ord('A')]}",
                f"{section} tick",
            )
    for name, rows in (
        ("contacts", extra.contacts),
        ("effort", extra.effort),
        ("locations", extra.locations),
        ("uncomfortable", extra.uncomfortable),
        ("hazards", extra.hazards),
    ):
        for row in rows:
            cells = [c for c in (row.item, row.duration, row.frequency, row.hours) if c]
            if not _consecutive(norm, cells):
                losses.append(f"{name} row {cells} not printed as one row")
    for text in (*extra.certification, *extra.occupational_requirements):
        need(text, "section 13")
    if extra.experience_years is not None:
        if not _consecutive(
            norm, [str(extra.experience_years), form.qualifications_experience_unit]
        ):
            losses.append("years of experience not printed")
    if extra.equivalency_acceptable is not None:
        option = form.qualifications_equivalency_options[
            0 if extra.equivalency_acceptable else 1
        ]
        need(f"{form.checkbox_ticked_glyph} {option}", "equivalency")
    if extra.equivalency_rationale:
        need(extra.equivalency_rationale, "equivalency rationale")
    return losses


def _index_of(lines: list[str], heading: str) -> int:
    for i, ln in enumerate(lines):
        if ln.endswith(heading):
            return i
    return -1


def _consecutive(lines: list[str], cells: list[str]) -> bool:
    """``cells`` appear as consecutive lines — one table row in extracted text."""
    want = [" ".join(c.split()) for c in cells]
    n = len(want)
    return any(lines[i : i + n] == want for i in range(len(lines) - n + 1))


def _qual_text(text: str, modifier: str | None) -> str:
    """A qualification as printed: its Toolkit modifier prefixed when not already in
    the text (the JDFN export's rule, kept so the modifier is never dropped)."""
    mod = (modifier or "").strip()
    if mod and mod.lower() not in text.lower():
        return f"{mod} {text}"
    return text


def jdfn_round_trip_losses(
    original: SFUJobDescription, reparsed: SFUJobDescription
) -> list[str]:
    """The APSA/JDFN round trip, over what the (unchanged) APSA export and the JDFN
    parser actually carry between them: title and position summary.

    ⚠ NOT duties, and that is a measured finding, not an omission. MEASURED 2026-10-19
    over the live Bank: 1,798 of 1,876 current non-CUPE roles come back with a
    different duty count (typically "5 exported, 1 re-read"). Checked on a three-duty
    JD: the APSA export prints duties as Word "List Bullet" paragraphs, whose bullet is
    list FORMATTING with no character in the extracted text, so the JDFN parser joins
    the lines into ONE duty — and the export's footer heading ("Territorial
    Acknowledgement & Employment Equity") is not a heading that parser knows, so it and
    the footer text join that duty too. J1 must leave the APSA output unchanged
    (checked: identical in content for every live non-CUPE role), so it is reported
    (and measurable through :func:`jdfn_duty_count_survives`), not silently fixed here.
    """
    losses: list[str] = []
    if original.title.strip() != reparsed.title.strip():
        losses.append(f"title: {original.title!r} came back as {reparsed.title!r}")
    if _norm(original.position_summary) != _norm(reparsed.position_summary):
        losses.append("position_summary changed")
    return losses


def jdfn_duty_count_survives(
    original: SFUJobDescription, reparsed: SFUJobDescription
) -> bool:
    """Whether the APSA export's duties come back as the same number of duties."""
    return len(original.duties) == len(reparsed.duties)

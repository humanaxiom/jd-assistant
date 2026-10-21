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
  (it merges sections 3 and 4) — same count, order and words. The parser's ceiling is
  `segmentation.wjq_duty_max_count` (HR-263, 120 since parser v9; it was a hardcoded
  twelve); a re-read short of it is REPORTED as a loss, never excused;
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
from src.jd_core.parser.headings import NEXT_LABEL_RX, POSITION_NO_LABEL_RX
from src.jd_core.parser.segmenter import _PERCENT_RE
from src.jd_core.rules import Rules, get_rules

_WORD = re.compile(r"[a-z0-9]+")

#: The parser's own duty-statement ceiling — a rendered duty longer than this is
#: legitimately cut on re-read. Rulebook data since parser v9 (HR-261); it was the
#: code constant ``segmenter._MAX_DUTY_STMT = 400``.
_MAX_DUTY_STMT = get_rules().segmentation.duty_statement_max_chars
#: The parser's ceiling for a decision / problem / qualification item
#: (``segmenter._MAX_BULLET`` / ``_MAX_QUAL``).
_MAX_LIST_ITEM = 400
#: ``segmenter._MAX_SUPERVISORY``.
_MAX_SUPERVISORY = 600

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
        (jd.supervisor_title, "supervisor title"),  # J4's top-level field (M2)
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


def _item_survives(want: list[str], back_text: str, cap: int) -> bool:
    """A re-read list item holds exactly the original's words — or, when the parser
    cut it at its ceiling ``cap``, a faithful PREFIX of them (last word may be split).
    """
    got = words(back_text)
    if got == want:
        return True
    return len(back_text) >= cap - 1 and got[:-1] == want[: len(got) - 1]


def _supervisory_survives(want: list[str], back_text: str) -> bool:
    """The supervisory prose came back — all its words, or, when the re-read reached
    the parser's ceiling (``segmenter._MAX_SUPERVISORY``), every word up to the cut, in
    order. The parser keeps the line's ``Supervisory:`` label in the prose (it files
    every non-contact line there), so a 600-character original re-reads as label + 587
    characters: a CEILING cut, not a loss the export can avoid."""
    got = words(back_text)
    if _contained(want, got):
        return True
    if len(back_text) < _MAX_SUPERVISORY - 1:
        return False
    # With or without the label word the parser keeps; the last word may be cut.
    candidates = [got[:-1]] + ([got[1:-1]] if got[:1] == ["supervisory"] else [])
    return any(kept and kept == want[: len(kept)] for kept in candidates)


def _list_losses(
    name: str, want: list[list[str]], back: list[str], cap: int
) -> list[str]:
    if len(want) != len(back):
        return [f"{name}: {len(want)} exported, {len(back)} re-read"]
    return [
        f"{name} {i}: {w[:12]}... came back as {words(b)[:12]}..."
        for i, (w, b) in enumerate(zip(want, back, strict=True), start=1)
        if not _item_survives(w, b, cap)
    ]


def jdfn_round_trip_losses(
    original: SFUJobDescription, reparsed: SFUJobDescription
) -> list[str]:
    """Every way ``reparsed`` failed to bring back what ``original`` held, through the
    APSA/APEX/Poly export and the JDFN parser. Empty list = the round trip holds.

    History: until Track J4 this checked only title and summary, because MEASURED
    2026-10-19 1,798 of 1,876 current non-CUPE roles came back with a different duty
    count (typically "5 exported, 1 re-read") — the export printed Word "List Bullet"
    paragraphs whose bullet never reaches the extracted text, so the parser joined
    every duty, and the footer under a heading it did not know, into one. J4 fixed it
    in the renderer; this now checks every field the parser can read:

    * title, position number, employee group (when the original has one) — **equal**;
    * position summary and additional context — **equal** word for word;
    * duties — **same count, same order**, each re-read duty (statement, then its
      how/why) holding the original verb + statement + how/why words in order. How/why
      print as sub-bullets of their duty; since parser v9 they come back AS how/why
      (before v9 they fused into the statement — both readings satisfy this check, and
      the v9 structure is pinned separately);
    * decision making, problem solving, qualifications — **same count, same order, same
      words** (qualifications as printed: modifier prefixed when absent). Kinds are NOT
      compared: the parser's kind is a keyword guess (``_classify_qual``);
    * contacts — internal and external **equal**, in order; the supervisory prose's
      words all come back (the re-read keeps its "Supervisory:" label);
    * About SFU, territorial acknowledgement, employment equity — **present**.

    ``supervisor_title`` / ``supervisor_position_number`` are printed but the parser
    has no field for them, so they are checked in the export, not here.
    """
    losses: list[str] = []
    if original.title.strip() != reparsed.title.strip():
        losses.append(f"title: {original.title!r} came back as {reparsed.title!r}")
    want_pos = (original.position_number or "").strip() or None
    got_pos = (reparsed.position_number or "").strip() or None
    if want_pos != got_pos:
        losses.append(f"position_number: {want_pos!r} came back as {got_pos!r}")
    if original.employee_group and original.employee_group != reparsed.employee_group:
        losses.append(
            f"employee_group: {original.employee_group!r} came back as "
            f"{reparsed.employee_group!r}"
        )
    if _norm(original.position_summary) != _norm(reparsed.position_summary):
        losses.append("position_summary changed")
    if _norm(original.additional_context) != _norm(reparsed.additional_context):
        losses.append("additional_context changed")

    losses += _list_losses(
        "duty",
        [
            _duty_words(d.action_verb, d.statement, list(d.how_why))
            for d in original.duties
        ],
        [" ".join((d.statement, *d.how_why)) for d in reparsed.duties],
        _MAX_DUTY_STMT,
    )
    for field in ("decision_making", "problem_solving"):
        losses += _list_losses(
            field,
            [words(item) for item in getattr(original, field)],
            list(getattr(reparsed, field)),
            _MAX_LIST_ITEM,
        )
    losses += _list_losses(
        "qualification",
        [words(_qual_text(q.text, q.modifier)) for q in original.qualifications],
        [q.text for q in reparsed.qualifications],
        _MAX_LIST_ITEM,
    )

    rel_src, rel_back = original.relationships, reparsed.relationships
    for side in ("internal", "external"):
        want_c = [_norm(c) for c in (getattr(rel_src, side) if rel_src else [])]
        got_c = [_norm(c) for c in (getattr(rel_back, side) if rel_back else [])]
        if want_c != got_c:
            losses.append(f"{side} contacts: {want_c} came back as {got_c}")
    want_sup = words(rel_src.supervisory if rel_src else None)
    back_sup = (rel_back.supervisory if rel_back else None) or ""
    if want_sup and not _supervisory_survives(want_sup, back_sup):
        losses.append("supervisory prose lost words")

    for flag in (
        "about_sfu_present",
        "territorial_acknowledgement_present",
        "employment_equity_present",
    ):
        if not getattr(reparsed, flag):
            losses.append(f"{flag}: the export's boilerplate did not re-read")
    return losses


#: ``segmenter._maybe_split_semicolons``: a logical line longer than this with at least
#: two semicolons is split into separate duties (legacy run-on "Typical Duties").
_SEMICOLON_SPLIT_LEN = 200


def jdfn_parser_limits(jd: SFUJobDescription) -> dict[str, str]:
    """Why the JDFN parser CANNOT bring a field of ``jd`` back, whatever the export
    prints — ``{loss prefix: reason}``. Each is a documented reader limit, and fixing
    any is a parser change (hashed heading/label vocabulary or segmenter code,
    ``PARSER_VERSION``, archive re-parse), not an export one.

    The live smoke lets a role lose a field ONLY when this names that field; any other
    loss is an export defect and fails it. Measured 2026-10-19 over all 1,876 current
    non-CUPE roles: 4 roles, under ``duty`` (2), ``title`` (1), ``position_number`` (1).
    """
    limits: dict[str, str] = {}
    for duty in jd.duties:
        line = " ".join(
            [duty.action_verb, duty.statement, *duty.how_why]
            if not duty.statement.lower().startswith(duty.action_verb.lower())
            else [duty.statement, *duty.how_why]
        )
        if len(line) > _SEMICOLON_SPLIT_LEN and line.count(";") >= 2:
            limits["duty"] = (
                "a duty (with its how/why) over 200 characters with 2+ semicolons is "
                "split into several duties (segmenter._maybe_split_semicolons)"
            )
    for field, items in (
        ("duty", [d.statement for d in jd.duties if not d.how_why]),
        ("decision_making", list(jd.decision_making)),
        ("problem_solving", list(jd.problem_solving)),
        ("qualification", [q.text for q in jd.qualifications]),
    ):
        if any(item.strip().endswith(":") for item in items):
            limits[field] = "an item ending in ':' is read as an intro line and dropped"
    if NEXT_LABEL_RX.search(jd.title):
        limits["title"] = (
            "the title holds a word the parser cuts a label value at "
            "(headings.NEXT_LABEL_RX: department, date, grade, ...)"
        )
        if not jd.position_number and POSITION_NO_LABEL_RX.search(
            "\n"
            + re.split(r"(?i)(?=position\s*(?:#|no\.?|number))", jd.title, maxsplit=1)[
                -1
            ]
        ):
            limits["position_number"] = (
                "the draft's TITLE carries 'Position #: <id>' (a pre-v9 parse leaked "
                "the label into the title); since v9 the parser cuts the title there "
                "and reads the id as the position number"
            )
    if not jd.position_number and any(
        POSITION_NO_LABEL_RX.search(text or "")
        for text in (
            jd.position_summary,
            jd.additional_context,
            *(d.statement for d in jd.duties),
        )
    ):
        limits["position_number"] = (
            "the draft has no position number, but its own TEXT carries a "
            "'Position Number: …' label (copied from a member's summary), and the "
            "parser's whole-document fallback reads it (pre-existing; found on the v9 "
            "Bank, 1 role)"
        )
    if jd.position_number and not re.fullmatch(r"[A-Za-z0-9\-]+", jd.position_number):
        limits["position_number"] = (
            "the parser reads ONE token after 'Position #:' "
            "(headings.POSITION_NO_LABEL_RX); this value has spaces or punctuation"
        )
    return limits


def jdfn_unexplained_losses(
    original: SFUJobDescription, reparsed: SFUJobDescription
) -> list[str]:
    """The round-trip losses NOT explained by a :func:`jdfn_parser_limits` entry —
    each one an export defect."""
    limits = jdfn_parser_limits(original)
    return [
        loss
        for loss in jdfn_round_trip_losses(original, reparsed)
        if re.split(r"[ :]", loss, maxsplit=1)[0] not in limits
    ]


def jdfn_duty_count_survives(
    original: SFUJobDescription, reparsed: SFUJobDescription
) -> bool:
    """Whether the APSA export's duties come back as the same number of duties."""
    return len(original.duties) == len(reparsed.duties)

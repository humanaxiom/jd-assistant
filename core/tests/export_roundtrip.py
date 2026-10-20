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
"""

from __future__ import annotations

import re
from collections import Counter

from src.jd_core.models.parsed_jd import SFUJobDescription
from src.jd_core.parser.segmenter import _PERCENT_RE
from src.jd_core.rules import Rules, get_rules

_WORD = re.compile(r"[a-z0-9]+")

#: The parser's own duty-statement ceiling — a rendered duty longer than this is
#: legitimately cut on re-read. Rulebook data since parser v9 (HR-261); it was the
#: code constant ``segmenter._MAX_DUTY_STMT = 400``.
_MAX_DUTY_STMT = get_rules().segmentation.duty_statement_max_chars

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

    if len(original.duties) != len(reparsed.duties):
        losses.append(
            f"duties: {len(original.duties)} exported, {len(reparsed.duties)} re-read"
        )
    for i, (src, back) in enumerate(
        zip(original.duties, reparsed.duties, strict=False), start=1
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
    for section in rules.wjq.context_sections:
        want_words = src_ctx.get(section, []) + extras.get(section, [])
        if want_words and not _contained(want_words, back_ctx.get(section, [])):
            missing = Counter(want_words) - Counter(back_ctx.get(section, []))
            losses.append(f"{section}: words lost {sorted(missing)[:10]}")
    return losses


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

"""Unit tests for rendering a canonical SFU JD back to text.

Ported from hris ``tests/unit/test_jd_bank_render.py`` (3 tests) — the hris suite
is the behavioural oracle for this EXTRACT port (ADR-005 #12). Imports rewritten
to jd_core paths.

**Two deliberate departures from the hris suite**, both because hris re-parsed a
rendered JD with an LLM and this repo re-parses it with a deterministic regex:

1. The hris tests assert the *substring* ``"PROBLEM SOLVING"``, which passes even
   when the emitted heading is one the parser cannot read. It was — hris emitted
   ``PROBLEM SOLVING & LEVEL OF SUPERVISION`` and
   :func:`~src.jd_core.parser.headings.match_heading` accepts only ``AND``, so a
   rendered JD lost its entire Problem Solving section on re-parse. Headings are
   now pinned **exactly**, every emitted heading must ``match_heading()`` back to
   its own section, and a real ``parse_jd`` round trip guards the section.
2. Headings therefore come from :data:`CANONICAL_HEADING` (parser-owned data), so
   duties render as ``DUTIES AND RESPONSIBILITIES``, not hris's ``&`` form.
"""

from __future__ import annotations

from src.jd_core.bank import render_sfu_jd_text
from src.jd_core.models.parsed_jd import (
    SFUDuty,
    SFUJobDescription,
    SFUQualification,
    SFURelationships,
)
from src.jd_core.parser import parse_jd
from src.jd_core.parser.headings import (
    CANONICAL_HEADING,
    SECTION_ORDER,
    SectionKey,
    match_heading,
)


def _full_jd() -> SFUJobDescription:
    return SFUJobDescription(
        title="Applications Developer",
        department="ITS",
        grade="B80",
        employee_group="apsa",
        position_summary="Builds and maintains applications.",
        duties=[
            SFUDuty(action_verb="Develops", statement="software", how_why=["to spec"])
        ],
        decision_making=["Chooses the implementation approach."],
        problem_solving=["Debugs novel failures."],
        relationships=SFURelationships(
            supervisory="Supervises 3 staff.",
            internal=["Registrar", "Finance"],
            external=["Vendors"],
        ),
        qualifications=[
            SFUQualification(text="Python", kind="skill", modifier="advanced")
        ],
        additional_context="Occasional evening work.",
    )


# ---------- the hris oracle (behaviour), with headings pinned exactly ----------


def test_render_sections_in_order_and_skips_empty() -> None:
    jd = SFUJobDescription(
        title="Applications Developer",
        department="ITS",
        grade="B80",
        position_summary="Builds and maintains applications.",
        duties=[
            SFUDuty(action_verb="Develops", statement="software", how_why=["to spec"])
        ],
        decision_making=["Chooses the implementation approach."],
        problem_solving=["Debugs novel failures."],
        relationships=SFURelationships(
            supervisory=None, internal=["Registrar"], external=[]
        ),
        qualifications=[
            SFUQualification(text="Python", kind="skill", modifier="advanced")
        ],
    )
    text = render_sfu_jd_text(jd)

    # Header + sections present, in template order. Headings pinned EXACTLY (the
    # hris suite's substring assertions are what let the & / AND bug through).
    assert text.startswith("Applications Developer")
    assert "ITS · Grade B80" in text
    order = [
        "POSITION SUMMARY",
        "DUTIES AND RESPONSIBILITIES",
        "IMPACT OF DECISION MAKING",
        "PROBLEM SOLVING AND LEVEL OF SUPERVISION",
        "RELATIONSHIPS",
        "QUALIFICATIONS",
    ]
    for heading in order:
        assert f"\n{heading}\n" in text, f"heading {heading!r} not emitted verbatim"
    positions = [text.index(h) for h in order]
    assert positions == sorted(positions), "sections not in SFU template order"
    # Duty formatting: "ACTION VERB statement (how/why)".
    assert "- Develops software (to spec)" in text
    # Qualification carries its Toolkit modifier + kind.
    assert "- [skill] advanced Python" in text
    # Empty external relationships omitted; supervisory omitted (None).
    assert "External:" not in text
    assert "Supervisory:" not in text


def test_render_minimal_is_just_the_title() -> None:
    assert render_sfu_jd_text(SFUJobDescription(title="Coordinator")) == "Coordinator"


def test_render_is_long_enough_for_a_job_create() -> None:
    # A harmonized canonical produces well over the 50-char description_raw floor.
    jd = SFUJobDescription(
        title="Systems Administrator",
        position_summary=(
            "Administers the institution's server and network infrastructure."
        ),
        duties=[
            SFUDuty(statement="Maintains servers and network devices across sites.")
        ],
    )
    assert len(render_sfu_jd_text(jd)) >= 50


# ---------- renderer and parser cannot disagree (the bug this suite exists for) -


def test_every_canonical_heading_matches_back_to_its_own_section() -> None:
    """The single source of truth for SFU headings, proved consistent with the
    patterns that read them. A heading the renderer can emit but the parser cannot
    match is a silently-dropped section."""
    assert set(CANONICAL_HEADING) == set(SECTION_ORDER)  # all ten, none missing
    for section, heading in CANONICAL_HEADING.items():
        matched = match_heading(heading)
        assert matched is not None, f"{heading!r} ({section}) is not matchable"
        assert (
            matched[0] == section
        ), f"{heading!r} parses back as {matched[0]}, not {section}"


def test_every_heading_the_renderer_emits_parses_back_to_its_section() -> None:
    """Whatever the renderer actually writes — not just what the map says it
    would — must be readable by ``match_heading``."""
    emitted = [
        line
        for line in render_sfu_jd_text(_full_jd()).splitlines()
        if line and line == line.upper() and line.strip()
    ]
    # every all-caps line the renderer emits is a heading, and every one is known
    assert emitted, "no headings emitted"
    for line in emitted:
        matched = match_heading(line)
        assert matched is not None, f"renderer emitted unparseable heading {line!r}"
        assert CANONICAL_HEADING[matched[0]] == line


def test_rendered_jd_reparses_with_every_rendered_section_intact() -> None:
    """The regression for the data-loss bug: render -> ``parse_jd`` (the real,
    deterministic parser) -> the sections come back. Before the headings were
    shared data, ``problem_solving`` came back EMPTY and its text was swallowed
    into the preceding duty."""
    parsed = parse_jd(render_sfu_jd_text(_full_jd())).jd

    assert parsed.position_summary is not None
    assert "Builds and maintains applications." in parsed.position_summary
    assert [d.statement for d in parsed.duties] == ["Develops software (to spec)"]
    assert parsed.decision_making == ["Chooses the implementation approach."]
    # THE bug: this was `[]`, with the heading + bullet swallowed into duties.
    assert parsed.problem_solving == ["Debugs novel failures."]
    # The same bug one level down: under hris's `Internal:` label these came back
    # as *supervisory prose* — the connections were not lost, they were refiled.
    assert parsed.relationships is not None
    assert parsed.relationships.internal == ["Registrar", "Finance"]
    assert parsed.relationships.external == ["Vendors"]
    assert parsed.relationships.supervisory is not None
    assert "Supervises 3 staff." in parsed.relationships.supervisory
    assert [q.text for q in parsed.qualifications] == ["[skill] advanced Python"]
    assert parsed.additional_context is not None
    assert "Occasional evening work." in parsed.additional_context


def test_render_to_parse_is_documented_lossy_exactly_where_it_says_it_is() -> None:
    """The gap is real, so it is pinned, not implied. These are the fields a
    rendered canonical does NOT get back, and the two labels that come back stuck
    to their values. Fix one (HANDOFF backlog) and this test fails and sends you to
    the module docstring — the docstring is a contract, not a wish."""
    text = render_sfu_jd_text(_full_jd())
    parsed = parse_jd(text).jd

    # Identification: a subtitle line, not the labelled fields the segmenter reads.
    assert parsed.department is None
    assert parsed.grade is None
    assert parsed.position_number is None
    assert parsed.employee_group == "apsa"  # ...this one survives: token-scanned.
    # Boilerplate: presence booleans on the model, so there is no text to render.
    assert parsed.about_sfu_present is False
    assert parsed.territorial_acknowledgement_present is False
    assert parsed.employment_equity_present is False
    # Labels the segmenter does not strip -> a second render would double them.
    assert parsed.qualifications[0].text.startswith("[skill] advanced ")
    assert parsed.relationships is not None
    assert parsed.relationships.supervisory is not None
    assert parsed.relationships.supervisory.startswith("Supervisory: ")


def test_problem_solving_heading_is_the_and_form_not_the_ampersand_form() -> None:
    """Pinned by name: hris's ``&`` heading is the exact string that broke, and a
    regex-only parser is why. Re-introducing it must fail loudly here."""
    assert (
        CANONICAL_HEADING[SectionKey.PROBLEM_SOLVING]
        == "PROBLEM SOLVING AND LEVEL OF SUPERVISION"
    )
    assert match_heading("PROBLEM SOLVING & LEVEL OF SUPERVISION") is None
    text = render_sfu_jd_text(
        SFUJobDescription(title="Coordinator", problem_solving=["Debugs failures."])
    )
    assert "PROBLEM SOLVING & LEVEL OF SUPERVISION" not in text


# ---------- branches the hris suite leaves uncovered (same behaviour, pinned) ---


def test_render_identification_upcases_employee_group_and_keeps_order() -> None:
    jd = SFUJobDescription(
        title="Coordinator", department="ITS", grade="B80", employee_group="apsa"
    )
    assert render_sfu_jd_text(jd) == "Coordinator\n\nITS · Grade B80 · APSA"


def test_render_duty_without_action_verb_is_just_the_statement() -> None:
    jd = SFUJobDescription(
        title="Coordinator", duties=[SFUDuty(statement="Maintains the schedule.")]
    )
    assert "- Maintains the schedule." in render_sfu_jd_text(jd)


def test_render_duty_joins_multiple_how_why_with_semicolons() -> None:
    jd = SFUJobDescription(
        title="Coordinator",
        duties=[
            SFUDuty(
                action_verb="Develops",
                statement="software",
                how_why=["to spec", "on time"],
            )
        ],
    )
    assert "- Develops software (to spec; on time)" in render_sfu_jd_text(jd)


def test_render_relationships_labels_each_connection_as_the_parser_reads_it() -> None:
    """Departure from hris: the segmenter's labels are ``Internal connections:`` /
    ``External connections:``, one connection per line — hris's comma-joined
    ``Internal:`` was unreadable to it (see the round-trip test)."""
    jd = SFUJobDescription(
        title="Manager",
        relationships=SFURelationships(
            supervisory="Supervises 3 staff.",
            internal=["Registrar", "Finance"],
            external=["Vendors"],
        ),
    )
    text = render_sfu_jd_text(jd)
    assert "Supervisory: Supervises 3 staff." in text
    assert "Internal connections: Registrar" in text
    assert "Internal connections: Finance" in text
    assert "External connections: Vendors" in text


def test_render_omits_an_entirely_empty_relationships_section() -> None:
    jd = SFUJobDescription(title="Coordinator", relationships=SFURelationships())
    assert render_sfu_jd_text(jd) == "Coordinator"


def test_render_qualification_without_a_modifier_omits_it() -> None:
    jd = SFUJobDescription(
        title="Coordinator",
        qualifications=[SFUQualification(text="Bachelor's degree", kind="education")],
    )
    assert "- [education] Bachelor's degree" in render_sfu_jd_text(jd)


def test_render_appends_additional_context_last() -> None:
    jd = SFUJobDescription(
        title="Coordinator",
        position_summary="Coordinates things.",
        additional_context="Occasional evening work.",
    )
    text = render_sfu_jd_text(jd)
    assert text.index("POSITION SUMMARY") < text.index(
        "ADDITIONAL CONTEXTUAL INFORMATION"
    )
    assert text.endswith("Occasional evening work.")

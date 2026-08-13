"""The pure JD -> embed-text serializer (Phase 3.2b).

Every hard rule from the spec gets its own failing-fixture test:

* the title is excluded by default, and the `include_title_in_document` knob is
  pinned by MUTATION (`model_copy`);
* SFU's mandated boilerplate is never embedded (it has no text field to leak from,
  and this test proves the presence booleans cannot smuggle any in);
* `how_why` is never emitted, even when the parser one day populates it;
* lists stay in file order;
* truncation lands on a whole-unit boundary, never mid-word/mid-item;
* a sub-`min_section_chars` section, and an all-empty JD, yield no unit at all.
"""

from __future__ import annotations

import pytest

from src.jd_core.bank.embed_text import (
    SERIALIZER_VERSION,
    retruncate_within,
    serialize_document,
    serialize_section,
)
from src.jd_core.models.parsed_jd import (
    SFUDuty,
    SFUJobDescription,
    SFUQualification,
    SFURelationships,
)
from src.jd_core.rules import Embeddings, Rules, get_rules


@pytest.fixture(scope="module")
def rules() -> Rules:
    return get_rules()


def _jd(**overrides: object) -> SFUJobDescription:
    base: dict[str, object] = {
        "title": "Manager, Special Projects",
        "position_summary": "Leads a small team delivering cross-department projects.",
        "duties": [
            SFUDuty(action_verb="Manages", statement="the annual project portfolio."),
            SFUDuty(action_verb="Coordinates", statement="stakeholder communications."),
        ],
        "decision_making": ["Decides project prioritization within budget."],
        "problem_solving": ["Resolves cross-team scheduling conflicts."],
        "relationships": SFURelationships(
            supervisory="Supervises two project coordinators.",
            internal=["Finance", "IT Services"],
            external=["Vendors"],
        ),
        "qualifications": [
            SFUQualification(
                text="project management", kind="skill", modifier="advanced"
            ),
            SFUQualification(
                text="a bachelor's degree", kind="education", modifier=None
            ),
        ],
        "additional_context": "Some travel may be required.",
    }
    base.update(overrides)
    return SFUJobDescription(**base)  # type: ignore[arg-type]


def _empty_jd(**overrides: object) -> SFUJobDescription:
    base: dict[str, object] = {"title": "Empty JD"}
    base.update(overrides)
    return SFUJobDescription(**base)  # type: ignore[arg-type]


# --- SERIALIZER_VERSION --------------------------------------------------------


def test_serializer_version_is_a_stable_string() -> None:
    assert isinstance(SERIALIZER_VERSION, str) and SERIALIZER_VERSION


# --- title exclusion (title-agnostic-by-construction, pinned by mutation) ------


def test_the_title_is_excluded_by_default(rules: Rules) -> None:
    jd = _jd(title="A Very Distinctive Title String")
    result = serialize_document(jd, rules.embeddings)
    assert "A Very Distinctive Title String" not in result.text


def test_include_title_in_document_true_adds_the_title(rules: Rules) -> None:
    """Pinned by MUTATION: flip the knob via `model_copy` and the title appears;
    the shipped default omits it."""
    mutated = rules.embeddings.model_copy(update={"include_title_in_document": True})
    jd = _jd(title="A Very Distinctive Title String")

    default_result = serialize_document(jd, rules.embeddings)
    mutated_result = serialize_document(jd, mutated)

    assert "A Very Distinctive Title String" not in default_result.text
    assert mutated_result.text.startswith("A Very Distinctive Title String")


# --- SFU's mandated boilerplate is never embedded ------------------------------


def test_boilerplate_presence_booleans_never_change_the_serialized_text(
    rules: Rules,
) -> None:
    """The parsed model represents About-SFU / territorial-ack / EDI footer as
    presence BOOLEANS with no text field — so flipping all three from False to
    True must be a complete no-op on the serialized document. This is what keeps
    SFU's byte-identical mandated paragraphs out of every JD's vector for free."""
    without_boilerplate = _jd(
        about_sfu_present=False,
        territorial_acknowledgement_present=False,
        employment_equity_present=False,
    )
    with_boilerplate = _jd(
        about_sfu_present=True,
        territorial_acknowledgement_present=True,
        employment_equity_present=True,
    )
    without_result = serialize_document(without_boilerplate, rules.embeddings)
    with_result = serialize_document(with_boilerplate, rules.embeddings)
    assert without_result == with_result


# --- how_why is never emitted ---------------------------------------------------


def test_how_why_is_never_emitted_even_when_populated(rules: Rules) -> None:
    """HR-121: the segmenter never populates `how_why` today, but this serializer
    must not depend on that — it simply never reads the field, so Phase 4
    populating it changes nothing here."""
    jd = _jd(
        duties=[
            SFUDuty(
                action_verb="Manages",
                statement="the annual project portfolio.",
                how_why=["HOW: via quarterly reviews", "WHY: to hit the budget"],
            )
        ]
    )
    result = serialize_document(jd, rules.embeddings)
    assert "HOW: via quarterly reviews" not in result.text
    assert "WHY: to hit the budget" not in result.text
    assert "Manages the annual project portfolio." in result.text


# --- lists stay in file order ---------------------------------------------------


def test_duties_stay_in_file_order_never_sorted(rules: Rules) -> None:
    jd = _jd(
        duties=[
            SFUDuty(action_verb="Zebra-verb", statement="last alphabetically."),
            SFUDuty(action_verb="Apple-verb", statement="first alphabetically."),
        ]
    )
    result = serialize_document(jd, rules.embeddings)
    assert result.text.index("Zebra-verb") < result.text.index("Apple-verb")


def test_relationships_order_is_supervisory_then_internal_then_external(
    rules: Rules,
) -> None:
    jd = _jd(
        relationships=SFURelationships(
            supervisory="Supervises the widget team.",
            internal=["Legal Affairs"],
            external=["External Auditors"],
        )
    )
    result = serialize_document(jd, rules.embeddings)
    assert (
        result.text.index("Supervises the widget team.")
        < result.text.index("Legal Affairs")
        < result.text.index("External Auditors")
    )


def test_qualification_modifier_is_prefixed_only_when_present(rules: Rules) -> None:
    jd = _jd(
        qualifications=[
            SFUQualification(
                text="project management", kind="skill", modifier="advanced"
            ),
            SFUQualification(
                text="a valid driver's license", kind="ability", modifier=None
            ),
        ]
    )
    result = serialize_document(jd, rules.embeddings)
    assert "advanced project management" in result.text
    assert "a valid driver's license" in result.text
    # no stray "None " prefix ever appears
    assert "None a valid driver's license" not in result.text


# --- determinism -----------------------------------------------------------


def test_the_same_jd_yields_a_byte_identical_text_sha256(rules: Rules) -> None:
    jd = _jd()
    first = serialize_document(jd, rules.embeddings)
    second = serialize_document(jd, rules.embeddings)
    assert first == second
    assert first.text_sha256 == second.text_sha256


def test_a_different_jd_yields_a_different_text_sha256(rules: Rules) -> None:
    other = _jd(additional_context="A materially different sentence.")
    a = serialize_document(_jd(), rules.embeddings)
    b = serialize_document(other, rules.embeddings)
    assert a.text_sha256 != b.text_sha256


# --- truncation at whole-unit boundaries ---------------------------------------


def test_truncation_never_cuts_a_unit_in_half(rules: Rules) -> None:
    tiny = rules.embeddings.model_copy(update={"max_chars": 50})
    duties = [
        SFUDuty(action_verb="Manages", statement=f"responsibility number {i} in full.")
        for i in range(10)
    ]
    jd = _jd(
        duties=duties,
        position_summary=None,
        decision_making=[],
        problem_solving=[],
        relationships=None,
        qualifications=[],
        additional_context=None,
    )

    result = serialize_document(jd, tiny)

    assert result.truncated is True
    assert len(result.text) <= 50
    # text_chars is the PRE-truncation length — strictly greater than what survived
    assert result.text_chars > len(result.text)
    # every kept line is a WHOLE duty line — never a fragment of one
    for line in result.text.split("\n"):
        assert line == "" or any(
            line == f"Manages responsibility number {i} in full." for i in range(10)
        ), f"a partial unit survived truncation: {line!r}"


def test_an_untruncated_text_reports_truncated_false_and_equal_lengths(
    rules: Rules,
) -> None:
    jd = _jd()
    result = serialize_document(jd, rules.embeddings)
    assert result.truncated is False
    assert result.text_chars == len(result.text)


# --- the HR-193 over-length fallback re-cut (retruncate_within) -----------------


def test_retruncate_within_returns_the_text_unchanged_when_it_fits() -> None:
    text = "line one\nline two\nline three"
    assert retruncate_within(text, 1000) == text


def test_retruncate_within_drops_whole_trailing_lines() -> None:
    """The fallback cuts on the same ``\\n`` boundary the serializer joins units on,
    so a re-cut keeps whole lines — never a fragment of one."""
    text = "aaaa\nbbbb\ncccc\ndddd"  # 4 lines, 4 chars each, joined = 19 chars
    # Room for "aaaa\nbbbb" (9) but not the next "\ncccc" (would be 14).
    assert retruncate_within(text, 11) == "aaaa\nbbbb"
    # Every survivor is a whole original line.
    for line in retruncate_within(text, 11).split("\n"):
        assert line in {"aaaa", "bbbb", "cccc", "dddd"}


def test_retruncate_within_returns_empty_when_not_one_line_fits() -> None:
    """The caller must treat ``""`` as "no rung fit" and never embed it — a zero
    vector is exactly what the whole pipeline forbids."""
    assert retruncate_within("a-long-first-line\nsecond", 3) == ""


# --- section vectors: no unit below min_section_chars, none for empty JD ------


def test_a_section_shorter_than_min_section_chars_yields_no_unit(rules: Rules) -> None:
    guarded = rules.embeddings.model_copy(update={"min_section_chars": 1000})
    jd = _jd(position_summary="Too short.")
    assert serialize_section(jd, guarded, "position_summary") is None


def test_a_section_with_content_at_a_zero_guard_rail_yields_a_unit(
    rules: Rules,
) -> None:
    disabled = rules.embeddings.model_copy(update={"min_section_chars": 0})
    jd = _jd(position_summary="Short.")
    result = serialize_section(jd, disabled, "position_summary")
    assert result is not None
    assert result.text == "Short."


def test_an_empty_section_yields_no_unit_regardless_of_min_section_chars(
    rules: Rules,
) -> None:
    jd = _empty_jd()
    assert serialize_section(jd, rules.embeddings, "position_summary") is None
    assert serialize_section(jd, rules.embeddings, "duties") is None
    assert serialize_section(jd, rules.embeddings, "qualifications") is None


def test_an_all_empty_jd_yields_no_document_unit(rules: Rules) -> None:
    jd = _empty_jd()
    result = serialize_document(jd, rules.embeddings)
    assert result.text == ""
    assert result.text_chars == 0
    assert result.truncated is False


# --- Embeddings model itself: the loader restricts section names --------------


def test_the_loader_rejects_a_section_with_no_producer() -> None:
    with pytest.raises(Exception, match="no embeddable content|no producer"):
        Embeddings(
            version="jd_rules_sfu_v4",
            model="nomic-embed-text",
            dimensions=768,
            max_chars=10_000,
            min_section_chars=40,
            include_title_in_document=False,
            document_sections=("about_sfu",),  # not a content-bearing section
            section_vectors=("position_summary",),
            interactive_timeout_seconds=10.0,
        )


def test_section_vectors_must_be_a_subset_of_document_sections() -> None:
    with pytest.raises(Exception, match="not in embeddings.document_sections"):
        Embeddings(
            version="jd_rules_sfu_v4",
            model="nomic-embed-text",
            dimensions=768,
            max_chars=10_000,
            min_section_chars=40,
            include_title_in_document=False,
            document_sections=("position_summary",),
            section_vectors=("duties",),  # not in document_sections
            interactive_timeout_seconds=10.0,
        )

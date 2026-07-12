"""HR-058: a scanner may not mark down text SFU forbids the author to edit.

SFU pre-populates the About-SFU paragraph (rulebook Part 1.5, "do not edit") and
mandates the territorial-acknowledgement + Employment-Equity statements (Part 1.6).
SFU's own About-SFU sentence contains ``compassionate``, which *our* coded-term
lexicon files at ``medium``. So a compliant JD scored 91.5/A -> 81.5/B, and a JD
that dropped the paragraph to dodge that tripped ``SFU-COMP-ABOUT`` instead. It was
penalised either way, on nearly every compliant JD in the archive — depressing the
very baseline the Phase-2.5 run is meant to ratify the score floor against.

This suite is the spec for the fix. It proves four things, and the first two are the
"both directions" the rulebook demands of every gate (CLAUDE.md #4):

1. **Paragraph present** -> no coded-term finding from it, AND no ``SFU-COMP-ABOUT``.
   Same score as the same JD without it: the 10-point artefact is gone.
2. **Paragraph absent** -> ``SFU-COMP-ABOUT`` still fires. The exemption did not
   quietly disable the presence gate.
3. **No loophole.** The exemption is granted to SFU's *text*, never to a location: a
   heading, a fragment, a near-miss and a splice all exempt nothing. Coded language
   around, between and inside a doctored block is still caught.
4. **It is data, not code** (CLAUDE.md #2). Empty ``coded_term_scan_exempt`` in the
   YAML and the false positive comes straight back — pinning the decision by VALUE,
   not merely by the register's drift check.

Everything asserts validator post-state (#3) — rule_ids and severities — never model
prose.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from pydantic import ValidationError

from src.jd_core.models.parsed_jd import (
    SFUDuty,
    SFUJobDescription,
    SFUQualification,
    SFURelationships,
)
from src.jd_core.models.quality import JDQualityIssue
from src.jd_core.parser import headings
from src.jd_core.quality import evaluate_jd_rules, score_issues
from src.jd_core.quality.boilerplate import normalize, redact_passages
from src.jd_core.rules import Boilerplate, Rules, get_rules

_PKG_DIR = Path(__file__).resolve().parents[2] / "src" / "jd_core" / "rules"
_BOILERPLATE_YAML = _PKG_DIR / "boilerplate.yaml"

#: The golden SFU new-template JD — an archive document, not a hand-written string.
#: READ, never transcribed: a copy of the block pasted into this file would be
#: faithful today with nothing keeping it so, and it is precisely the divergence
#: between the rulebook's text and the ARCHIVE's text that this fix turns on.
_TEMPLATE_FIXTURE = (
    Path(__file__).resolve().parents[1] / "fixtures" / "sfu_new_template.txt"
)


def _archive_about_sfu() -> str:
    """The About-SFU block exactly as SFU's own new-template JD carries it.

    Everything from the heading down to the blank line before IDENTIFICATION. Note it
    carries only the FIRST TWO of the rulebook's three sentences — which is why the
    unit of exemption is a passage and not the whole paragraph.
    """
    text = _TEMPLATE_FIXTURE.read_text(encoding="utf-8")
    block = text.split("\n\n", 1)[0]
    assert block.startswith("ABOUT SIMON FRASER UNIVERSITY"), block[:40]
    assert "compassionate" in block  # the fixture still contains the defect's trigger
    return block


_CLEAN_RAW = (
    "Bachelor's degree in Computer Science or other relevant discipline, plus "
    "five years of related experience or an equivalent combination of education, "
    "training and experience. Establishes and maintains relationships and "
    "alliances. The team values collaboration and clear writing."
)


@pytest.fixture
def rules() -> Rules:
    return get_rules()


@pytest.fixture
def boilerplate(rules: Rules) -> Boilerplate:
    return rules.boilerplate


def _clean_jd(**update: Any) -> SFUJobDescription:
    jd = SFUJobDescription(
        title="Software Developer",
        about_sfu_present=True,
        position_summary=" ".join(["word"] * 120),
        duties=[
            SFUDuty(
                action_verb=verb,
                statement=f"{verb} the program",
                how_why=["by coordinating stakeholders"],
            )
            for verb in ("Manages", "Coordinates", "Provides")
        ],
        decision_making=["Approves expenditures up to $5k"],
        problem_solving=["Resolves scheduling conflicts independently"],
        relationships=SFURelationships(
            supervisory="Supervises 2 staff",
            internal=["Finance"],
            external=["Vendors"],
        ),
        qualifications=[
            SFUQualification(
                text="Bachelor's degree or an equivalent combination of experience",
                kind="education",
            ),
            SFUQualification(
                text="Excellent knowledge of databases",
                kind="knowledge",
                modifier="excellent",
            ),
            SFUQualification(text="Python", kind="skill", modifier="advanced"),
            SFUQualification(text="Ability to work cooperatively", kind="ability"),
        ],
        territorial_acknowledgement_present=True,
        employment_equity_present=True,
    )
    return jd.model_copy(update=update) if update else jd


def _ids(issues: list[JDQualityIssue]) -> set[str | None]:
    return {issue.rule_id for issue in issues}


def _coded(issues: list[JDQualityIssue]) -> list[JDQualityIssue]:
    return [issue for issue in issues if issue.rule_id == "SFU-LANG-CODED"]


def _mandated_paragraph(boilerplate: Boilerplate, block: str) -> str:
    """SFU's mandated block, as a JD would carry it (one wrapped paragraph)."""
    return " ".join(boilerplate.blocks[block])


def _retuned(rules: Rules, **fields: Any) -> Rules:
    """``rules`` with ``boilerplate.yaml`` re-validated, ``fields`` overridden.

    Built from the real shipped file and run through :class:`Boilerplate` in full, so
    a retuning the rulebook would reject fails here exactly as it would at load.
    """
    raw: dict[str, Any] = yaml.safe_load(_BOILERPLATE_YAML.read_text(encoding="utf-8"))
    return rules.model_copy(
        update={"boilerplate": Boilerplate.model_validate({**raw, **fields})}
    )


# --- 0. the defect is real: SFU's own text trips SFU's own lexicon -------------


def test_sfu_mandates_a_paragraph_that_contains_one_of_our_own_coded_terms(
    rules: Rules, boilerplate: Boilerplate
) -> None:
    """The premise of the whole fix, asserted rather than assumed.

    If a future lexicon edit makes this pass vacuously the fix would still be
    correct, but HR-058 would have been closed by a different route — so the register
    should say so. Read this test as: *this* is the term, in *this* block.
    """
    coded = {term for _severity, terms in rules.coded_terms.tiers for term in terms}
    hits = {
        block: sorted(
            term
            for term in coded
            for passage in passages
            if f" {term} " in f" {normalize(passage)} ".replace(",", " ")
        )
        for block, passages in boilerplate.blocks.items()
    }
    assert hits["about_sfu"] == ["compassionate"], hits
    # The siblings are clean TODAY — this is what makes their exemption a guard
    # rather than a fix. If either of these ever goes non-empty, the same class of
    # defect has landed on the footer and HR must be told (HR-105 / HR-106).
    assert hits["territorial_acknowledgement"] == [], hits
    assert hits["employment_equity"] == [], hits


# --- 1. paragraph PRESENT: no coded-term hit, no SFU-COMP-ABOUT ----------------


def test_the_mandated_about_sfu_paragraph_raises_no_coded_term_finding(
    boilerplate: Boilerplate,
) -> None:
    raw = f"{_mandated_paragraph(boilerplate, 'about_sfu')}\n{_CLEAN_RAW}"
    issues = evaluate_jd_rules(_clean_jd(), raw)
    assert _coded(issues) == [], [i.message for i in _coded(issues)]
    assert "SFU-COMP-ABOUT" not in _ids(issues)
    assert issues == [], [(i.rule_id, i.message) for i in issues]


def test_the_archives_real_about_sfu_block_raises_no_coded_term_finding() -> None:
    """The one that would have failed a whole-paragraph match.

    SFU's own new-template JD (tests/fixtures/sfu_new_template.txt) carries only the
    first TWO sentences of the rulebook's About-SFU paragraph. Matching the block as
    one paragraph would have exempted nothing on the real corpus, and every JD in the
    archive would still be docked 10 points.
    """
    issues = evaluate_jd_rules(_clean_jd(), f"{_archive_about_sfu()}\n\n{_CLEAN_RAW}")
    assert _coded(issues) == []
    assert "SFU-COMP-ABOUT" not in _ids(issues)


def test_obeying_sfu_no_longer_costs_ten_points_and_a_grade(
    boilerplate: Boilerplate,
) -> None:
    """HR-058's headline number, as a behavioural assertion.

    Before the fix: 91.5/A without the mandated paragraph, 81.5/B with it. The
    baseline Phase 2.5 measures must not depend on whether the JD obeyed SFU.
    """
    without = score_issues(evaluate_jd_rules(_clean_jd(), _CLEAN_RAW))
    with_block = score_issues(
        evaluate_jd_rules(
            _clean_jd(),
            f"{_mandated_paragraph(boilerplate, 'about_sfu')}\n{_CLEAN_RAW}",
        )
    )
    assert with_block == without == (100.0, "A")


def test_the_whole_mandated_footer_is_exempt_too(boilerplate: Boilerplate) -> None:
    """Same class of defect, pre-empted on the siblings (HR-105 / HR-106)."""
    raw = "\n".join(
        [
            _mandated_paragraph(boilerplate, "about_sfu"),
            _CLEAN_RAW,
            _mandated_paragraph(boilerplate, "territorial_acknowledgement"),
            _mandated_paragraph(boilerplate, "employment_equity"),
        ]
    )
    assert evaluate_jd_rules(_clean_jd(), raw) == []


def test_a_repeated_footer_is_exempt_in_every_copy(boilerplate: Boilerplate) -> None:
    """Every occurrence, not just the first — archive JDs repeat the footer."""
    block = _mandated_paragraph(boilerplate, "about_sfu")
    assert evaluate_jd_rules(_clean_jd(), f"{block}\n{_CLEAN_RAW}\n{block}") == []


# --- 2. paragraph ABSENT: the presence gate still fires -----------------------


def test_a_jd_without_the_about_sfu_paragraph_still_trips_the_gate() -> None:
    issues = evaluate_jd_rules(_clean_jd(about_sfu_present=False), _CLEAN_RAW)
    assert "SFU-COMP-ABOUT" in _ids(issues)
    assert [i.severity for i in issues if i.rule_id == "SFU-COMP-ABOUT"] == ["low"]


@pytest.mark.parametrize(
    ("field", "rule_id"),
    [
        ("about_sfu_present", "SFU-COMP-ABOUT"),
        ("territorial_acknowledgement_present", "SFU-COMP-TERRITORIAL"),
        ("employment_equity_present", "SFU-COMP-EDI"),
    ],
)
def test_the_exemption_did_not_disable_any_presence_gate(
    boilerplate: Boilerplate, field: str, rule_id: str
) -> None:
    """Even with all three mandated blocks in the raw text, a JD whose parse says the
    block is missing still trips its gate: presence is a property of the PARSE, and
    the redaction touches only what the coded-term scan reads."""
    raw = "\n".join(
        _mandated_paragraph(boilerplate, block) for block in boilerplate.block_names
    )
    issues = evaluate_jd_rules(_clean_jd(**{field: False}), f"{raw}\n{_CLEAN_RAW}")
    assert rule_id in _ids(issues)


# --- 3. no loophole: the exemption is granted to SFU's TEXT, not to a place ----


def test_coded_language_outside_the_block_is_still_caught(
    boilerplate: Boilerplate,
) -> None:
    raw = (
        f"{_mandated_paragraph(boilerplate, 'about_sfu')}\n"
        "The successful candidate is a compassionate, aggressive self-starter.\n"
        f"{_CLEAN_RAW}"
    )
    hits = _coded(evaluate_jd_rules(_clean_jd(), raw))
    # "aggressive" and "compassionate" — the JD's OWN prose, both still `medium`.
    assert len(hits) == 2, [i.message for i in hits]
    assert {i.severity for i in hits} == {"medium"}


def test_an_about_sfu_heading_exempts_nothing(boilerplate: Boilerplate) -> None:
    """The loophole the fix must NOT open: exempt the mandated text, never a section.

    A JD that files arbitrary coded language under an "About SFU" heading — even with
    SFU's real first sentence above it for cover — is scanned in full.
    """
    raw = (
        "ABOUT SIMON FRASER UNIVERSITY\n"
        f"{boilerplate.about_sfu[0]}\n"
        "We are an aggressive, dominant, competitive employer.\n"
        f"{_CLEAN_RAW}"
    )
    terms = {i.message for i in _coded(evaluate_jd_rules(_clean_jd(), raw))}
    assert len(terms) == 3, terms  # aggressive + dominant + competitive


@pytest.mark.parametrize(
    ("label", "text"),
    [
        (
            "fragment of a mandated sentence",
            "The team is fearless, compassionate, approachable and ready.",
        ),
        (
            "words spliced into a mandated sentence",
            "We are unconventional, fearless, compassionate, aggressive, "
            "approachable and ready.",
        ),
        (
            "a mandated sentence with a word changed",
            "We are unconventional, fearless, compassionate, approachable and eager.",
        ),
        (
            "a paraphrase",
            "SFU is unconventional, fearless and compassionate.",
        ),
    ],
)
def test_a_near_miss_is_not_the_mandated_block_and_is_scanned_in_full(
    label: str, text: str
) -> None:
    """What counts as the mandated block, decided and pinned.

    Anything that is not one of SFU's sentences VERBATIM is the JD's own prose and is
    scanned as such — including a splice, which is the smuggling route.
    """
    issues = evaluate_jd_rules(_clean_jd(), f"{text}\n{_CLEAN_RAW}")
    assert _coded(issues), label


@pytest.mark.parametrize(
    ("label", "render"),
    [
        ("line-wrapped mid-sentence", lambda t: t.replace(", ", ",\n")),
        ("double-spaced", lambda t: t.replace(" ", "  ")),
        ("shouted", str.upper),
        ("title-cased", str.title),
        ("smart quotes from a .docx", lambda t: t.replace("'", "’")),
        ("non-breaking spaces", lambda t: t.replace(" ", " ")),
    ],
)
def test_a_faithful_rendering_of_the_mandated_block_is_still_the_mandated_block(
    boilerplate: Boilerplate, label: str, render: Any
) -> None:
    """The other side of "verbatim": whitespace, case and typographic punctuation are
    extraction artefacts, not edits. A JD must not be penalised because Word gave it a
    curly apostrophe or the extractor wrapped a line."""
    raw = f"{render(_mandated_paragraph(boilerplate, 'about_sfu'))}\n{_CLEAN_RAW}"
    assert _coded(evaluate_jd_rules(_clean_jd(), raw)) == [], label


def test_redaction_cannot_weld_two_words_into_a_third(
    boilerplate: Boilerplate,
) -> None:
    """Cutting a passage out must not invent a finding out of the join: ``work`` +
    ``man`` welded together is ``workman``, a `medium` coded term the JD never
    contained. The cut leaves a space behind, so it cannot happen."""
    block = _mandated_paragraph(boilerplate, "about_sfu")
    redacted = redact_passages(f"work{block}man", [block])
    assert redacted == "work man"
    assert "workman" not in redacted


def test_redaction_leaves_a_document_with_no_boilerplate_alone() -> None:
    """A legacy JD carries none of the new template's blocks — untouched, byte for
    byte, so nothing about the old-era archive changes."""
    assert redact_passages(_CLEAN_RAW, ["We celebrate diversity."]) == _CLEAN_RAW


# --- the matcher's guard rails: the states the DATA is allowed to reach --------


def test_two_wordings_of_one_paragraph_collapse_into_a_single_cut() -> None:
    """The overlapping-span branch — and it is NOT hypothetical.

    HR-104's ``impact_if_changed`` tells HR exactly how to reach this state: *"if SFU
    has revised this paragraph, BOTH wordings belong in this list until the archive is
    re-issued."* Two wordings of one paragraph share most of their text, so their
    spans overlap in a JD that carries either. Overlapping spans must collapse into
    ONE cut: a second cut from a cursor already past the span's start would slice
    backwards and DUPLICATE the tail of the document into the scanned text — inventing
    findings (or hiding them) rather than removing SFU's words.

    Pinned for all three shapes, and for both orderings of the passage list, because
    `_spans` yields them in list order and only the sort makes it order-independent.
    """
    old = "We are unconventional, fearless, compassionate, approachable and ready."
    revised = "We are unconventional, fearless, compassionate and ready."
    nested = "We are unconventional, fearless, compassionate"  # a prefix of both
    straddling = "compassionate, approachable and ready. Apply now."

    doc = f"Intro. {old} Outro."
    # The JD's own space before the block, the cut marker, the JD's own space after:
    # the boilerplate is gone and NOTHING of the JD's own text is lost or duplicated.
    cut = "Intro.   Outro."

    # (a) two revisions of one paragraph, both listed, JD carries the old one — the
    #     exact data state HR-104 tells HR to create.
    assert redact_passages(doc, [old, revised]) == cut
    assert redact_passages(doc, [revised, old]) == cut  # list order must not matter
    # (b) one passage nested wholly inside another -> the wider cut wins, once
    assert redact_passages(doc, [nested, old]) == cut
    assert redact_passages(doc, [old, nested]) == cut
    # (c) spans that straddle -> merged into ONE cut spanning both. Without the
    #     collapse this would slice backwards and duplicate the tail.
    assert redact_passages(f"Intro. {old} Apply now. Outro.", [old, straddling]) == cut


def test_a_zero_width_character_inside_the_mandated_text_is_still_the_mandated_text(
    boilerplate: Boilerplate,
) -> None:
    """The ``_FOLD -> ""`` drop. A ``.docx`` extraction routinely leaves a BOM or a
    zero-width space mid-paragraph; SFU's text with an invisible character in it is
    still SFU's text and must still be exempt."""
    block = _mandated_paragraph(boilerplate, "about_sfu")
    bommed = block.replace("compassionate", "comp﻿assionate")
    assert bommed != block
    assert normalize(bommed) == normalize(block)
    assert _coded(evaluate_jd_rules(_clean_jd(), f"{bommed}\n{_CLEAN_RAW}")) == []


def test_a_blank_passage_matches_nothing_rather_than_everything() -> None:
    """A whitespace-only passage normalizes to the empty string, and ``"" in text`` is
    True at every index — so an unguarded matcher would redact the WHOLE document and
    silently disable the coded-term scan. It must be a no-op instead."""
    assert redact_passages(_CLEAN_RAW, ["   \n\t "]) == _CLEAN_RAW
    assert redact_passages(_CLEAN_RAW, [""]) == _CLEAN_RAW
    # ...and it cannot be reached from the rulebook anyway: see the load guards below.


# --- 4. it is DATA: move the value, watch the behaviour follow ----------------


def test_emptying_the_exemption_brings_the_false_positive_straight_back(
    rules: Rules, boilerplate: Boilerplate
) -> None:
    """The by-VALUE pin (HR-107). A validator that hardcoded the exemption — or read
    the blocks but ignored ``coded_term_scan_exempt`` — passes every test above and
    fails this one."""
    raw = f"{_mandated_paragraph(boilerplate, 'about_sfu')}\n{_CLEAN_RAW}"
    unexempted = _retuned(rules, coded_term_scan_exempt=[])

    hits = _coded(evaluate_jd_rules(_clean_jd(), raw, rules=unexempted))
    assert [i.severity for i in hits] == ["medium"]
    assert score_issues(
        evaluate_jd_rules(_clean_jd(), raw, rules=unexempted),
        scoring=unexempted.scoring,
    ) == (90.0, "A")


def test_the_scan_reads_the_shipped_passages_not_a_hardcoded_paragraph(
    rules: Rules,
) -> None:
    """Change SFU's text in the YAML and the exemption follows it — the other half of
    rulebook-as-data. A validator holding the paragraph as a Python literal passes
    everything above and fails here."""
    invented = _retuned(rules, about_sfu=["We are a compassionate employer."])
    clean = _clean_jd()

    # the invented passage is now exempt...
    assert (
        _coded(
            evaluate_jd_rules(
                clean, f"We are a compassionate employer.\n{_CLEAN_RAW}", rules=invented
            )
        )
        == []
    )
    # ...and SFU's real sentence, no longer in the rulebook, is not.
    assert _coded(
        evaluate_jd_rules(
            clean,
            "We are unconventional, fearless, compassionate, approachable and ready.\n"
            f"{_CLEAN_RAW}",
            rules=invented,
        )
    )


# --- the LOAD guards: a failing fixture for each (CLAUDE.md #4) ---------------


def test_an_exemption_for_a_block_that_does_not_exist_fails_to_load(
    rules: Rules,
) -> None:
    """A gate that can never fire is the worst failure mode for a rulebook — so an
    exemption naming a block this file does not define is a LOAD error, not a quiet
    no-op."""
    with pytest.raises(ValidationError, match="vision_statement"):
        _retuned(rules, coded_term_scan_exempt=["about_sfu", "vision_statement"])


def test_a_blank_mandated_passage_fails_to_load(rules: Rules) -> None:
    """The dangerous one. A blank passage normalizes to ``""``, which is "found" at
    every index of every JD — an unguarded matcher would redact the entire document
    and turn the coded-term scan off, university-wide, from one stray YAML line. It
    must not be loadable at all.
    """
    with pytest.raises(ValidationError, match="must not be blank"):
        _retuned(rules, about_sfu=["We celebrate diversity.", "   "])


def test_a_repeated_mandated_passage_fails_to_load(rules: Rules) -> None:
    """The same passage twice would cut the same span twice — harmless today only
    because the spans collapse. It is a copy-paste slip in rule data, and rule data
    fails loudly."""
    passage = "We celebrate the diversity of people, ideas and cultures."
    with pytest.raises(ValidationError, match="must not repeat a passage"):
        _retuned(rules, about_sfu=[passage, passage])


def test_a_repeated_exempt_block_fails_to_load(rules: Rules) -> None:
    """Ditto for the exemption list: naming a block twice says nothing new."""
    with pytest.raises(ValidationError, match="must not repeat a block"):
        _retuned(rules, coded_term_scan_exempt=["about_sfu", "about_sfu"])


# --- the file itself: provenance + cross-module consistency -------------------


def test_the_mandated_text_matches_the_rulebook_our_parser_detects(
    boilerplate: Boilerplate,
) -> None:
    """The parser detects these blocks by regex (``parser/headings.py``); the rulebook
    stores their text. Two descriptions of one thing, and nothing kept them in step —
    rewrite the stored About-SFU passage and the parser could stop calling it present
    while the scan happily exempts it. Cheap to assert, so asserted."""
    about = _mandated_paragraph(boilerplate, "about_sfu")
    assert headings.has_about_sfu(about)
    assert headings.has_territorial_acknowledgement(
        _mandated_paragraph(boilerplate, "territorial_acknowledgement")
    )
    assert headings.has_employment_equity(
        _mandated_paragraph(boilerplate, "employment_equity")
    )


def test_every_mandated_block_is_registered_and_the_exemption_is_ours(
    rules: Rules,
) -> None:
    """Provenance (CLAUDE.md #6), enforced. SFU's text is transcribed and must cite a
    Part; the decision to stop scanning it is OURS and must say so."""
    by_path = {d.config.path: d for d in rules.decision_register.decisions}
    for block in rules.boilerplate.block_names:
        entry = by_path[f"boilerplate.{block}"]
        assert entry.provenance == "sfu_rulebook", block
        assert entry.source_part in {"Part 1.5", "Part 1.6"}, block
        assert entry.status == "open"

    exemption = by_path["boilerplate.coded_term_scan_exempt"]
    assert exemption.provenance == "our_invention"
    assert exemption.source_part is None
    assert exemption.status == "open"


def test_normalize_is_idempotent_and_strips_exactly_what_it_claims_to() -> None:
    """Leading/trailing/collapsed whitespace, case, and typographic punctuation — and
    nothing else. Everything the matcher's "verbatim" promise rests on."""
    text = "  We  are\nCanada’s engaged  university.  "
    assert normalize(text) == "we are canada's engaged university."
    assert normalize(normalize(text)) == normalize(text)

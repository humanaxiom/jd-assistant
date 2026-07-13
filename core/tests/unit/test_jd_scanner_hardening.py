"""The scanners could not see through a document's own formatting.

Every scan anchored its term with ``(?<!\\w)term(?!\\w)`` over the JD's raw text, so the
matcher only ever saw the document byte-for-byte. Two artefacts defeated it, and it is
worth being precise about which one matters, because they are not remotely equal
(CLAUDE.md #6 — this is provenance, and a wrong story here is a wrong story in 2.5's
audit trail):

* **An invisible character.** ``comp<ZWSP>assionate`` is not the string
  ``compassionate``, so ONE zero-width space defeated the coded-term scan, the
  banned-phrase scan and the placeholder scan **outright**. Total, in code. **And it
  moves ~nothing on the real archive**: 600 sampled ``.docx`` carry zero format
  characters, zero soft hyphens and zero ligatures, and not one of them changes a
  finding. Correct hardening against a real defect in a corpus that does not currently
  exercise it — do not sell it as more than that.
* **A line wrap.** ``antiword`` hard-wraps the legacy ``.doc`` corpus, so a JD that
  plainly says "…or an equivalent combination of education…" reached the scanner as
  ``equivalent\\n      combination`` and was reported as **missing the equivalency
  path**. Measured on a random 400-document ``.doc`` sample: ``SFU-QUAL-EQUIVALENT``
  **74 -> 35** (39 false positives, 9.75% of legacy JDs), plus **3** real findings the
  wrap had been hiding; 42/400 documents change. **This is the change that moves the
  baseline** — the same class of false positive as HR-058, penalising a JD for how a
  converter wrapped it, and the real reason this landed before 2.5.

The suite is organised as the fix's argument:

1. **The blast radius.** Every scan that reads a term against JD text, each with a
   failing fixture (obfuscated -> now caught) and a passing fixture (clean -> the rule
   still behaves).
2. **The other direction.** The scans whose rule fires on ABSENCE — the equivalency
   path, the Relationships header, the related-discipline escape, the action-verb
   glossary, the modifier vocabulary. There the artefact produced a FALSE POSITIVE, and
   the fix removes it.
3. **A superset — of the MATCHER, not of the report.** :func:`_find` reads the JD as
   written *and* as read, so nothing the old matcher caught can go missing. Two honest
   caveats, both tested: with the HR-058 exemption on, ~26 exempted ``SFU-LANG-CODED``
   findings correctly *disappear* archive-wide (the widened fold now matches a mandated
   passage the old redactor could not); and ``asse<ZWSP>ts<ZWSP>management`` is still
   missed by both passes.
4. **Offsets.** Evidence still quotes the ORIGINAL text, windowed around the match in
   the original's own coordinates.
5. **No new loophole**, and **HR-108** — how far the whitespace collapse is allowed to
   go. Collapsing across a *paragraph* break INVENTS findings out of two unrelated
   paragraphs, one of them a trip of the non-overridable no-placeholders gate. So the
   boundary stands, it is rule data, and the tests pin it by VALUE.
6. **Load guards.** Rule data that folds to nothing cannot be loaded.

Validator post-state is the oracle throughout (CLAUDE.md #3): rule_ids and severities,
never model prose.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from src.jd_core.models.parsed_jd import (
    SFUDuty,
    SFUJobDescription,
    SFUQualification,
    SFURelationships,
)
from src.jd_core.models.quality import JDQualityIssue
from src.jd_core.quality import evaluate_jd_rules
from src.jd_core.quality.validators import _find
from src.jd_core.rules import (
    Boilerplate,
    CodedTerms,
    Markers,
    Rules,
    TextNorm,
    get_rules,
)
from src.jd_core.textnorm import fold, fold_text

#: The zero-width space (U+200B) — the character the whole defect turns on.
ZWSP = "​"
#: The soft hyphen (U+00AD) and the BOM (U+FEFF): the other two Word leaves behind.
SHY = "­"
BOM = "﻿"
#: A non-breaking space (U+00A0) and a non-breaking hyphen (U+2011).
NBSP = " "
NBHYPHEN = "‑"

#: A JD body with no findings in it: the equivalency path, the Relationships header
#: and a related-discipline escape, and not one coded term, marker or banned phrase.
_CLEAN_RAW = (
    "Bachelor's degree in Computer Science or other relevant discipline, plus "
    "five years of related experience or an equivalent combination of education, "
    "training and experience. Establishes and maintains relationships and "
    "alliances. The team values collaboration and clear writing."
)


@pytest.fixture
def rules() -> Rules:
    return get_rules()


def _summary(tail: str = "") -> str:
    """A Position Summary of a template-legal length (100-150 words)."""
    return " ".join(["word"] * 115) + (f" {tail}" if tail else "")


#: The clean JD's qualifications, minus the equivalency phrase — so a test about the
#: equivalency path in the RAW TEXT is not satisfied by the qualifications instead.
_QUALS_WITHOUT_EQUIVALENCY = [
    SFUQualification(text="Bachelor's degree", kind="education"),
    SFUQualification(
        text="Excellent knowledge of databases", kind="knowledge", modifier="excellent"
    ),
    SFUQualification(text="Python", kind="skill", modifier="advanced"),
    SFUQualification(text="Ability to work cooperatively", kind="ability"),
]


def _clean_jd(**update: Any) -> SFUJobDescription:
    """A JD that, against ``_CLEAN_RAW``, produces exactly zero findings."""
    jd = SFUJobDescription(
        title="Software Developer",
        about_sfu_present=True,
        position_summary=_summary(),
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


def _ids(issues: list[JDQualityIssue]) -> list[str | None]:
    return [issue.rule_id for issue in issues]


def _hits(jd: SFUJobDescription, raw: str, rule_id: str) -> list[JDQualityIssue]:
    return [i for i in evaluate_jd_rules(jd, raw) if i.rule_id == rule_id]


def _quals_saying(text: str) -> list[SFUQualification]:
    """The clean qualifications, plus one that says ``text``.

    Where a banned-phrase probe has to live since Phase 2.6: ``SFU-QUAL-BANNED-PHRASE``
    reads the QUALIFICATIONS, not the whole document (HR-120 — the whole-document scan
    was the defect that drove all 104 SFU-APPROVE-QUAL-MINIMUM blocks in the 2.5
    baseline). The fold still applies to that text, which is what these tests are about,
    so the probe is unchanged in substance — only in *where the JD says it*.

    Inserted before the ability so Knowledge -> Skills -> Abilities order still holds.
    """
    jd = _clean_jd()
    probe = SFUQualification(text=text, kind="skill", modifier="advanced")
    return [*jd.qualifications[:-1], probe, jd.qualifications[-1]]


def test_the_clean_fixture_really_is_clean() -> None:
    """Every test below reads a finding as caused by the one thing it introduced. That
    is only true if the baseline is empty."""
    assert evaluate_jd_rules(_clean_jd(), _CLEAN_RAW) == []


# --- 1. the blast radius: every scan that matches a term against JD text -------


@pytest.mark.parametrize(
    ("label", "noise"),
    [
        ("zero-width space", ZWSP),
        ("zero-width non-joiner", "‌"),
        ("zero-width joiner", "‍"),
        ("byte-order mark", BOM),
        ("soft hyphen", SHY),
        ("word joiner", "⁠"),
        ("left-to-right mark", "‎"),
    ],
)
def test_an_invisible_character_no_longer_hides_a_coded_term(
    label: str, noise: str
) -> None:
    """THE defect. One invisible character inside the word and the coded-term scan
    returned nothing at all."""
    raw = f"{_CLEAN_RAW} We want an agg{noise}ressive self-starter."
    hits = _hits(_clean_jd(), raw, "SFU-LANG-CODED")
    assert [i.severity for i in hits] == ["medium"], label


def test_the_same_sentence_without_the_noise_still_fires() -> None:
    """The passing fixture for the pair above: nothing about the clean path moved."""
    raw = f"{_CLEAN_RAW} We want an aggressive self-starter."
    assert [i.severity for i in _hits(_clean_jd(), raw, "SFU-LANG-CODED")] == ["medium"]


@pytest.mark.parametrize(
    ("label", "term", "written"),
    [
        (
            "non-breaking hyphen inside a hyphenated term",
            "in-kind",
            f"in{NBHYPHEN}kind",
        ),
        ("latin ligature", "confidential", "conﬁdential"),
        ("zero-width space", "manpower", f"man{ZWSP}power"),
        ("soft hyphen", "chairman", f"chair{SHY}man"),
    ],
)
def test_a_typographic_artefact_no_longer_hides_a_coded_term(
    label: str, term: str, written: str
) -> None:
    """Word writes ``in‑kind`` with a non-breaking hyphen and ``conﬁdential`` with a
    ligature. Both are coded terms; neither used to match."""
    assert written != term  # the fixture is really obfuscated
    hits = _hits(_clean_jd(), f"{_CLEAN_RAW} The role is {written}.", "SFU-LANG-CODED")
    assert [i.severity for i in hits] == ["medium"], label


def test_an_invisible_character_no_longer_hides_a_banned_qualification_phrase() -> None:
    jd = _clean_jd(qualifications=_quals_saying(f"SQL and Java are asse{ZWSP}ts"))
    assert _hits(jd, _CLEAN_RAW, "SFU-QUAL-BANNED-PHRASE")


def test_a_line_wrap_no_longer_hides_a_two_word_banned_phrase() -> None:
    """The multi-word half of the hole: a banned phrase is matched as a literal
    substring, so the archive's habit of wrapping mid-phrase hid it."""
    jd = _clean_jd(
        qualifications=_quals_saying("Duties may\ninclude a professional certification")
    )
    assert _hits(jd, _CLEAN_RAW, "SFU-QUAL-BANNED-PHRASE")


def test_an_invisible_character_no_longer_hides_a_placeholder_marker() -> None:
    """``SFU-STRUCT-PLACEHOLDER`` feeds a **non-overridable** approval gate. A marker
    that an invisible character can switch off is a false safety guarantee: the JD is
    approvable with the template's own instructional text still in it."""
    raw = f"{_CLEAN_RAW} Reports to [in{ZWSP}sert department]."
    assert _hits(_clean_jd(), raw, "SFU-STRUCT-PLACEHOLDER")


def test_a_line_wrap_no_longer_hides_a_two_word_placeholder_marker() -> None:
    raw = f"{_CLEAN_RAW} Begin each duty with an action\nverb."
    assert _hits(_clean_jd(), raw, "SFU-STRUCT-PLACEHOLDER")


def test_an_invisible_character_no_longer_hides_a_working_condition_marker() -> None:
    jd = _clean_jd(position_summary=_summary(f"The role includes on{ZWSP}-call duty."))
    assert _hits(jd, _CLEAN_RAW, "SFU-AUTH-SUMMARY-CONDITIONS")


def test_an_invisible_character_no_longer_hides_incumbent_language() -> None:
    """``patterns.yaml`` regexes read the folded text too — ``\\bmy\\b`` did not match
    ``m<ZWSP>y``.

    The fixture says "the work is done", NOT "I am responsible". ``patterns.incumbent``
    is ``\\bmy\\b|\\bmyself\\b|\\bi am\\b``, so a fixture carrying "I am" fires with or
    without the fold and proves nothing at all. The obfuscated ``m<ZWSP>y`` has to be
    the only thing in the summary that can trip this rule.
    """
    jd = _clean_jd(position_summary=_summary(f"In m{ZWSP}y role the work is done."))
    assert _hits(jd, _CLEAN_RAW, "SFU-AUTH-SUMMARY-INCUMBENT")


def test_the_same_summary_without_the_first_person_word_is_clean() -> None:
    """The passing fixture — and the proof the one above is not vacuous."""
    jd = _clean_jd(position_summary=_summary("In this role the work is done."))
    assert _hits(jd, _CLEAN_RAW, "SFU-AUTH-SUMMARY-INCUMBENT") == []


def test_an_invisible_character_no_longer_hides_a_restricted_title() -> None:
    jd = _clean_jd(title=f"Regi{ZWSP}strar")
    assert [i.severity for i in _hits(jd, _CLEAN_RAW, "SFU-AUTH-TITLE-REGISTRAR")] == [
        "info"
    ]


def test_an_invisible_character_no_longer_hides_the_reserved_senior_prefix() -> None:
    """Part 3.5's "Senior" gate: reserved for roles that supervise junior peers."""
    jd = _clean_jd(
        title=f"Se{ZWSP}nior Analyst",
        relationships=SFURelationships(internal=["Finance"], external=["Vendors"]),
    )
    assert _hits(jd, _CLEAN_RAW, "SFU-GATE-SENIOR-TITLE")


def test_an_invisible_character_no_longer_hides_a_duty_time_allocation() -> None:
    """Part 11.6: the per-duty allocations must total 100. With the digits split by a
    zero-width space the scanner found NO allocations at all, so the gate — which only
    fires once it can see at least two — stayed silent on a JD totalling 80%."""
    raw = f"{_CLEAN_RAW} Runs the program (5{ZWSP}0%). Runs the office (3{ZWSP}0%)."
    hits = _hits(_clean_jd(), raw, "SFU-GATE-DUTY-PCT")
    assert hits
    assert "50" in (hits[0].evidence or "") and "30" in (hits[0].evidence or "")


def test_obfuscated_allocations_that_actually_total_one_hundred_do_not_fire() -> None:
    """The passing fixture: the gate reads the digits, it does not merely notice that
    something is there."""
    raw = f"{_CLEAN_RAW} Runs the program (6{ZWSP}0%). Runs the office (4{ZWSP}0%)."
    assert _hits(_clean_jd(), raw, "SFU-GATE-DUTY-PCT") == []


# --- 2. the other direction: the artefact used to invent a FALSE finding -------
#
# Where a rule fires on ABSENCE, a scanner blind to a `.docx` artefact reported text
# as missing that the JD demonstrably contains. Each pair: obfuscated -> silent (the
# false positive is gone), genuinely absent/wrong -> still fires (the gate is intact).


def test_an_obfuscated_equivalency_path_is_no_longer_reported_missing() -> None:
    raw = _CLEAN_RAW.replace(
        "equivalent combination", f"equivalent{NBSP}com{SHY}bination"
    )
    jd = _clean_jd(qualifications=_QUALS_WITHOUT_EQUIVALENCY)
    assert _hits(jd, raw, "SFU-QUAL-EQUIVALENT") == []


def test_a_genuinely_missing_equivalency_path_still_fires() -> None:
    raw = _CLEAN_RAW.replace("or an equivalent combination of education, ", "")
    jd = _clean_jd(qualifications=_QUALS_WITHOUT_EQUIVALENCY)
    assert _hits(jd, raw, "SFU-QUAL-EQUIVALENT")


def test_a_line_wrapped_relationships_header_is_no_longer_reported_missing() -> None:
    """Part 2F's standardized header is a 52-character phrase; the archive wraps it."""
    raw = _CLEAN_RAW.replace(
        "Establishes and maintains relationships and alliances",
        "Establishes and maintains\nrelationships  and alliances",
    )
    assert _hits(_clean_jd(), raw, "SFU-GATE-REL-HEADER") == []


def test_a_genuinely_missing_relationships_header_still_fires() -> None:
    raw = _CLEAN_RAW.replace(
        "Establishes and maintains relationships and alliances.", ""
    )
    assert _hits(_clean_jd(), raw, "SFU-GATE-REL-HEADER")


#: A body whose ONLY related-discipline escape is the phrase "relevant discipline" —
#: `_CLEAN_RAW` also says "or other relevant", which the rulebook's regex accepts on
#: its own and which would make the test below pass for the wrong reason.
_ONE_ESCAPE_RAW = _CLEAN_RAW.replace(
    "in Computer Science or other relevant discipline", "in a relevant discipline"
)


def test_an_obfuscated_related_discipline_escape_is_no_longer_reported_missing() -> (
    None
):
    raw = _ONE_ESCAPE_RAW.replace("relevant discipline", f"relevant dis{SHY}cipline")
    assert "or other relevant" not in raw  # the escape really is the obfuscated one
    assert _hits(_clean_jd(), raw, "SFU-QUAL-DEGREE-DISCIPLINE") == []


def test_a_degree_with_no_discipline_escape_still_fires() -> None:
    raw = _ONE_ESCAPE_RAW.replace("in a relevant discipline", "")
    assert _hits(_clean_jd(), raw, "SFU-QUAL-DEGREE-DISCIPLINE")


def test_an_obfuscated_approved_action_verb_is_no_longer_marked_down() -> None:
    jd = _clean_jd(
        duties=[
            SFUDuty(
                action_verb=f"Man{ZWSP}ages", statement="the program", how_why=["by"]
            )
            for _ in range(3)
        ]
    )
    assert _hits(jd, _CLEAN_RAW, "SFU-STRUCT-ACTION-VERB") == []


def test_a_verb_that_is_genuinely_off_the_glossary_still_fires() -> None:
    jd = _clean_jd(
        duties=[
            SFUDuty(action_verb="Zorbs", statement="the program", how_why=["by"])
            for _ in range(3)
        ]
    )
    assert _hits(jd, _CLEAN_RAW, "SFU-STRUCT-ACTION-VERB")


def test_an_obfuscated_skill_modifier_is_no_longer_off_the_vocabulary() -> None:
    jd = _clean_jd(
        qualifications=[
            SFUQualification(text="Python", kind="skill", modifier=f"adv{ZWSP}anced"),
            SFUQualification(text=f"Ability{NBSP}to work", kind="ability"),
        ]
    )
    issues = evaluate_jd_rules(jd, _CLEAN_RAW)
    assert "SFU-QUAL-MODIFIER-VOCAB" not in _ids(issues)
    assert "SFU-AUTH-ABILITIES-OBSERVABLE" not in _ids(issues)


def test_a_modifier_genuinely_off_the_vocabulary_still_fires() -> None:
    jd = _clean_jd(
        qualifications=[
            SFUQualification(text="Python", kind="skill", modifier="wizardly"),
        ]
    )
    assert _hits(jd, _CLEAN_RAW, "SFU-QUAL-MODIFIER-VOCAB")


def test_an_ability_that_is_genuinely_not_observable_still_fires() -> None:
    jd = _clean_jd(
        qualifications=[SFUQualification(text="Team player", kind="ability")],
    )
    assert _hits(jd, _CLEAN_RAW, "SFU-AUTH-ABILITIES-OBSERVABLE")


# --- 3. a STRICT superset: catch more, never less ------------------------------


def test_folding_alone_would_have_lost_a_finding_so_the_raw_text_is_scanned_too() -> (
    None
):
    """The counterexample that makes the union necessary, not merely tidy.

    ``assets<ZWSP>management`` contains the word ``assets`` bounded by a non-word
    character, so the OLD scanner flagged it. Folded, it becomes
    ``assetsmanagement`` — and the word ``assets`` is no longer in there at all. A
    fold-only fix would have silently dropped a finding the buggy scanner caught.

    The matcher therefore reads the JD **as written** and **as read**, and takes the
    union. This test is the pin: delete the raw pass from ``_find`` and it goes red.
    """
    written = f"Java and SQL are asse{ZWSP}ts"  # obfuscated -> only the FOLD sees it
    lost = f"Skills: assets{ZWSP}management experience"  # only the RAW text sees it
    assert "assetsmanagement" in fold(
        lost, join_paragraphs=False
    )  # the fold really does destroy this one

    for probe in (written, lost):
        jd = _clean_jd(qualifications=_quals_saying(probe))
        assert _hits(jd, _CLEAN_RAW, "SFU-QUAL-BANNED-PHRASE"), probe


def test_every_coded_term_in_the_shipped_lexicon_is_still_caught(rules: Rules) -> None:
    """Nothing previously caught is now missed — asserted over the WHOLE lexicon, at
    the severity the lexicon files it under, rather than on a sample."""
    for severity, terms in rules.coded_terms.tiers:
        for term in terms:
            raw = f"{_CLEAN_RAW} The role is {term} in nature."
            hits = _hits(_clean_jd(), raw, "SFU-LANG-CODED")
            assert [i.severity for i in hits] == [severity], term
            assert all(i.evidence for i in hits), term


def test_every_placeholder_marker_and_banned_phrase_is_still_caught(
    rules: Rules,
) -> None:
    for marker in rules.markers.placeholder:
        raw = f"{_CLEAN_RAW} Draft note: {marker} goes here."
        assert _hits(_clean_jd(), raw, "SFU-STRUCT-PLACEHOLDER"), marker
    for phrase in rules.qualifications.banned_phrases:
        jd = _clean_jd(
            qualifications=_quals_saying(f"Certification {phrase} something")
        )
        assert _hits(jd, _CLEAN_RAW, "SFU-QUAL-BANNED-PHRASE"), phrase


def test_a_term_still_does_not_match_inside_a_longer_word() -> None:
    """The anchoring the fold must not have thrown away: ``trust`` must not fire inside
    ``trustee``, ``aggressive`` inside ``aggressively``, ``individual`` inside
    ``individually``."""
    raw = f"{_CLEAN_RAW} The trustee acted aggressively and individually."
    assert evaluate_jd_rules(_clean_jd(), raw) == []


# --- 4. offsets: evidence still points at the ORIGINAL text --------------------


def test_evidence_for_an_obfuscated_term_quotes_the_jd_verbatim() -> None:
    """The subtle bug this fix could have introduced. Normalizing the text moves every
    index in it: window the match in FOLDED coordinates and slice the RAW text and the
    snippet lands somewhere else entirely; slice the FOLDED text instead and the
    "evidence" is a normalized paraphrase no reviewer can find in the document.

    So: the span is mapped back through the origin map, the window is measured in the
    original's own coordinates, and the snippet is cut from the original — invisible
    characters and all.
    """
    noise = f"Lorem{ZWSP} ipsum{SHY} dolor{BOM} sit amet. " * 6  # shifts every index
    raw = f"{_CLEAN_RAW} {noise}We want an agg{ZWSP}ressive self-starter. {noise}"
    evidence = _hits(_clean_jd(), raw, "SFU-LANG-CODED")[0].evidence or ""

    # verbatim: the zero-width space the JD actually contains is IN the snippet
    assert f"agg{ZWSP}ressive" in evidence
    # windowed on the match, not on the start of the document
    assert f"an agg{ZWSP}ressive self-starter" in evidence
    assert evidence.startswith("…") and evidence.endswith("…")
    assert "Bachelor" not in evidence


def test_the_evidence_window_is_measured_in_the_original_texts_coordinates(
    rules: Rules,
) -> None:
    window = rules.thresholds.evidence_context_window
    raw = f"{_CLEAN_RAW} We want an agg{ZWSP}ressive self-starter."
    evidence = _hits(_clean_jd(), raw, "SFU-LANG-CODED")[0].evidence or ""
    # <= window either side + the matched span + the two ellipses
    assert len(evidence) <= 2 * window + len(f"agg{ZWSP}ressive") + 2


@pytest.mark.parametrize(
    ("label", "term"),
    [
        ("found only in the folded text", f"agg{ZWSP}ressive"),
        ("found in the raw text too", "aggressive"),
    ],
)
def test_a_document_full_of_invisible_characters_does_not_shift_the_evidence_window(
    label: str, term: str
) -> None:
    """The origin map, pinned where a gentler fixture cannot pin it.

    Folding moves every index in the document, and the count of characters dropped
    *before* a match is exactly how far a snippet windowed in FOLDED coordinates gets
    slid to the left. With only a handful of invisible characters in the document that
    drift is smaller than the evidence window, so a mis-sliced snippet still happens to
    contain the term — and the bug hides behind a passing test.

    So: 300 invisible characters, and a drift far wider than the window. Report a
    folded offset as if it were a raw one (drop the ``to_raw`` call from ``_find``) and
    the snippet lands in the middle of the noise. This is the test that goes red.
    """
    raw = f"{_CLEAN_RAW} {ZWSP * 300} We want an {term} self-starter."
    evidence = _hits(_clean_jd(), raw, "SFU-LANG-CODED")[0].evidence or ""
    assert f"an {term} self-starter" in evidence, label


def test_the_matched_span_is_reported_in_the_original_texts_own_coordinates() -> None:
    """The invariant every evidence snippet — and any downstream highlighting — rests
    on, asserted on the matcher directly rather than inferred from a snippet."""
    text = fold_text(
        f"Noise:{ZWSP * 50} we want an agg{ZWSP}ressive self-starter.",
        join_paragraphs=False,
    )
    span = _find(text, "aggressive")
    assert span is not None
    assert text.raw[span[0] : span[1]] == f"agg{ZWSP}ressive"


def test_a_term_at_the_very_end_of_the_document_is_not_marked_truncated() -> None:
    raw = f"{_CLEAN_RAW} The successful candidate is agg{ZWSP}ressive"
    evidence = _hits(_clean_jd(), raw, "SFU-LANG-CODED")[0].evidence or ""
    assert evidence.startswith("…")
    assert not evidence.endswith("…")


def test_evidence_for_a_working_condition_marker_quotes_the_summary_verbatim() -> None:
    """The same origin map, on a different text: the finding's evidence is cut from the
    Position Summary the JD was written with, not from a folded rendering of it."""
    jd = _clean_jd(position_summary=_summary(f"Requires on{ZWSP}-call availability."))
    evidence = _hits(jd, _CLEAN_RAW, "SFU-AUTH-SUMMARY-CONDITIONS")[0].evidence or ""
    assert f"on{ZWSP}-call" in evidence


# --- 5. no new loophole -------------------------------------------------------


def test_the_fold_does_not_weld_two_separate_words_into_a_coded_one() -> None:
    """``man power`` (a real space) is two words and must stay two words; only the
    INVISIBLE separator — which a human reader cannot see, so a human reads
    ``manpower`` — is folded away."""
    spaced = f"{_CLEAN_RAW} We track man power costs."
    assert evaluate_jd_rules(_clean_jd(), spaced) == []
    assert _hits(
        _clean_jd(), f"{_CLEAN_RAW} We track man{ZWSP}power costs.", "SFU-LANG-CODED"
    )


def test_an_accented_word_does_not_normalize_onto_a_coded_term() -> None:
    """``trust`` and ``honest`` are coded terms. A fold aggressive enough to strip
    diacritics would land a different word on them — a finding invented out of
    normalization. Accents survive."""
    accented = f"{_CLEAN_RAW} A trüst and hönest résumé."
    assert evaluate_jd_rules(_clean_jd(), accented) == []


def test_the_boilerplate_exemption_is_still_granted_to_sfus_text_not_to_a_place(
    rules: Rules,
) -> None:
    """HR-058's fix must not have been widened by the fold. Re-run its loophole cases
    with the new normalization in place: an About-SFU heading exempts nothing, and a
    mandated sentence with words spliced in is a different sentence and is scanned in
    full — even when the splice is dressed up with invisible characters."""
    mandated = rules.boilerplate.about_sfu[1]
    assert "compassionate" in mandated  # the fixture is the real HR-058 sentence

    heading = (
        f"ABOUT SIMON FRASER UNIVERSITY\n{mandated}\n"
        f"We are an agg{ZWSP}ressive, dominant employer.\n{_CLEAN_RAW}"
    )
    assert (
        len(_hits(_clean_jd(), heading, "SFU-LANG-CODED")) == 2
    )  # aggressive+dominant

    spliced = mandated.replace("compassionate", f"compassionate, agg{ZWSP}ressive")
    hits = _hits(_clean_jd(), f"{spliced}\n{_CLEAN_RAW}", "SFU-LANG-CODED")
    # not SFU's sentence any more -> exempt nothing -> BOTH terms are the JD's own
    assert sorted(i.severity for i in hits) == ["medium", "medium"]


def test_sfus_own_mandated_text_is_still_exempt_through_the_wider_fold(
    rules: Rules,
) -> None:
    """The passing fixture for the pair above, and a check that extending the fold
    vocabulary did not accidentally *narrow* the exemption: SFU's paragraph carrying a
    soft hyphen or a ligature is still SFU's paragraph."""
    mandated = " ".join(rules.boilerplate.about_sfu)
    artefacts = mandated.replace("compassionate", f"com{SHY}passionate").replace(
        "diversity", f"di{ZWSP}versity"
    )
    assert artefacts != mandated
    assert evaluate_jd_rules(_clean_jd(), f"{artefacts}\n{_CLEAN_RAW}") == []


# --- 5b. HR-108: the whitespace collapse, and how far it is allowed to go ------
#
# This — not the zero-width fix — is what actually moves the archive baseline, in both
# directions. Collapsing a line WRAP removes real false positives that `antiword` put
# there. Collapsing across a PARAGRAPH break would invent findings out of two unrelated
# paragraphs. The default takes the first without the second, and it is rule DATA.


def _retuned(rules: Rules, *, join: bool) -> Rules:
    """``rules`` with HR-108 flipped, validated through the real ``TextNorm`` model."""
    return rules.model_copy(
        update={
            "textnorm": TextNorm.model_validate(
                {
                    "version": rules.textnorm.version,
                    "collapse_across_paragraph_break": join,
                }
            )
        }
    )


def test_an_antiword_hard_wrap_no_longer_hides_the_equivalency_path() -> None:
    """THE archive win, in one fixture. ``antiword`` hard-wraps the legacy ``.doc``
    corpus, so a JD that plainly grants the equivalency path reached the scanner as
    "equivalent\\n      combination" and was reported as MISSING it — 39 of the 74
    ``SFU-QUAL-EQUIVALENT`` findings on a random 400-document ``.doc`` sample, i.e.
    9.75% of legacy JDs. Same class of false positive as HR-058: penalising a JD for how
    a converter wrapped it."""
    raw = _CLEAN_RAW.replace("equivalent combination", "equivalent\n      combination")
    jd = _clean_jd(qualifications=_QUALS_WITHOUT_EQUIVALENCY)
    assert _hits(jd, raw, "SFU-QUAL-EQUIVALENT") == []


@pytest.mark.parametrize(
    ("label", "text", "rule_id", "in_qualifications"),
    [
        # ...and the marker feeds the NON-OVERRIDABLE no-placeholders gate (HR-047):
        # a JD made permanently un-approvable, with no waiver, by a text transform.
        (
            "placeholder marker `what by`",
            "Decides what\n\nBy whom is set elsewhere.",
            "SFU-STRUCT-PLACEHOLDER",
            False,
        ),
        # The banned-phrase probe lives in the QUALIFICATIONS now (HR-120) — the only
        # text this rule reads. The paragraph-boundary property is the same one, and the
        # risk it guards is real there too: the segmenter can put two wrapped
        # requirement lines in one item, and joining them invents a BLOCKING finding.
        (
            "banned phrase `may include`",
            "Duties may\n\nInclude other tasks.",
            "SFU-QUAL-BANNED-PHRASE",
            True,
        ),
    ],
)
def test_collapsing_across_a_paragraph_break_would_invent_a_finding(
    rules: Rules, label: str, text: str, rule_id: str, in_qualifications: bool
) -> None:
    """The reason the default is paragraph-AWARE, proved from both sides.

    Two unrelated paragraphs. Neither contains the term. Join them and the term appears
    — a finding assembled by our own normalization out of text no author wrote. So the
    shipped rulebook does NOT join them (no finding), and flipping HR-108 in the YAML
    conjures it straight back (the by-VALUE pin: a validator that hardcoded
    paragraph-awareness passes the first assertion and fails the second).
    """
    jd = (
        _clean_jd(qualifications=_quals_saying(text))
        if in_qualifications
        else _clean_jd()
    )
    raw = _CLEAN_RAW if in_qualifications else f"{_CLEAN_RAW}\n\n{text}"
    assert _hits(jd, raw, rule_id) == [], label

    joined = _retuned(rules, join=True)
    invented = [
        i for i in evaluate_jd_rules(jd, raw, rules=joined) if i.rule_id == rule_id
    ]
    assert invented, label


def test_a_working_condition_marker_is_not_assembled_across_two_paragraphs(
    rules: Rules,
) -> None:
    """The same, on the Position Summary rather than the body."""
    summary = _summary("Coordinates on\n\ncall centre staffing.")
    jd = _clean_jd(position_summary=summary)
    assert _hits(jd, _CLEAN_RAW, "SFU-AUTH-SUMMARY-CONDITIONS") == []

    joined = _retuned(rules, join=True)
    assert [
        i
        for i in evaluate_jd_rules(jd, _CLEAN_RAW, rules=joined)
        if i.rule_id == "SFU-AUTH-SUMMARY-CONDITIONS"
    ]


def test_a_wrap_is_still_collapsed_when_the_paragraph_boundary_is_respected() -> None:
    """The boundary must not throw the win away: ONE line break is a wrap and still
    collapses. Only a blank line stops a term."""
    jd = _clean_jd(qualifications=_quals_saying("Duties may\ninclude a certification"))
    assert _hits(jd, _CLEAN_RAW, "SFU-QUAL-BANNED-PHRASE")


def test_the_paragraph_scope_is_registered_and_ours(rules: Rules) -> None:
    """It is a DECISION, not a mechanical text fact, so HR is told about it (HR-108) —
    unlike the zero-width/typographic folding, which is not registered and must not be.
    """
    by_path = {d.config.path: d for d in rules.decision_register.decisions}
    entry = by_path["textnorm.collapse_across_paragraph_break"]
    assert entry.provenance == "our_invention"
    assert entry.source_part is None
    assert entry.status == "open"
    assert entry.current_default is False


# --- 6. load guards: rule data that folds to nothing cannot be shipped ---------


def test_a_coded_term_made_only_of_invisible_characters_fails_to_load() -> None:
    """A term of nothing but a zero-width space passes ``str.strip()`` and looks like
    real rule data — but it folds to ``""``, which is "found" at every index of every
    JD. One stray YAML line would flag every document in the archive. It must not be
    loadable at all."""
    with pytest.raises(ValidationError, match="nothing left to match"):
        CodedTerms.model_validate(
            {"version": "v", "medium": {ZWSP: '"caring"'}, "low": {}}
        )


def test_a_marker_made_only_of_invisible_characters_fails_to_load() -> None:
    with pytest.raises(ValidationError, match="nothing left to match"):
        Markers.model_validate(
            {
                "version": "v",
                "placeholder": [SHY],
                "working_conditions": ["on-call"],
                "relationships_header": "establishes and maintains",
            }
        )


def test_a_mandated_passage_made_only_of_invisible_characters_fails_to_load() -> None:
    """``strip()`` does not remove a zero-width space, so the old guard let this
    through — and a passage that normalizes to ``""`` redacts the WHOLE document and
    silently turns the coded-term scan off, university-wide."""
    with pytest.raises(ValidationError, match="must not be blank"):
        Boilerplate.model_validate(
            {
                "version": "v",
                "about_sfu": [ZWSP + BOM],
                "territorial_acknowledgement": ["We acknowledge."],
                "employment_equity": ["We are committed."],
                "coded_term_scan_exempt": [],
            }
        )

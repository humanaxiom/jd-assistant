"""The pure ``ParsedJD -> JobSignals`` adapter + the title normalizer (Phase 3.4a).

Built to the MEASURED shape of the real corpus (ADR-007): JDFN hides the degree and the
years inside the ``knowledge`` blob, the skill vocabulary is free-text noise, and 41% of
JDs carry no qualifications at all. Every decision the adapter embodies is
comparison.yaml data (HR-149…HR-153), so each is pinned **by mutation**: retune the knob
and the honest consequence appears.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from src.jd_core.bank import build_job_signals, canonical_title
from src.jd_core.models.bank import CanonicalTitle, JobSignals
from src.jd_core.models.parsed_jd import (
    SFUJobDescription,
    SFUQualification,
    SFURelationships,
)
from src.jd_core.rules import Rules, check_register, decision_surface, get_rules
from tests.unit.retuned_rules import retuned as _retuned


@pytest.fixture
def rules() -> Rules:
    return get_rules()


def _qual(text: str, kind: str) -> SFUQualification:
    return SFUQualification(text=text, kind=kind)  # type: ignore[arg-type]


# --- the JDFN blob: education + years live inside a `knowledge` qual -----------


def _jdfn_blob_jd() -> SFUJobDescription:
    """A JDFN JD whose ONLY degree + years signal is inside a spelled-out knowledge
    blob — the exact shape that made `kind == education` capture 40 of ~10,000 and the
    digit-only regex capture 226 of 4,888."""
    return SFUJobDescription(
        title="Applications Developer",
        employee_group="apsa",
        department="Information Technology Services",
        qualifications=[
            _qual(
                "Bachelor's degree in Computing Science or related discipline, and "
                "five years of related experience; or an equivalent combination of "
                "education and experience.",
                "knowledge",
            ),
        ],
    )


def test_jdfn_blob_yields_education_and_experience(rules: Rules) -> None:
    signals = build_job_signals(_jdfn_blob_jd())
    assert signals.education_ordinal == 2  # bachelors, read from the knowledge blob
    assert signals.experience_years == 5  # "five years", spelled out


def test_reverting_word_years_makes_the_experience_signal_vanish(rules: Rules) -> None:
    """MUTATION: empty the spelled-out-numbers map and the JDFN blob's experience bar
    goes None — proof the word-number support (HR-152) is load-bearing, not decor."""
    off = _retuned(rules, experience_word_numbers={})
    assert build_job_signals(_jdfn_blob_jd(), rules=off).experience_years is None


def test_reading_education_from_the_education_kind_only_loses_it(rules: Rules) -> None:
    """MUTATION: restrict education sources to `[education]` and the knowledge-blob
    degree disappears -- proof the 40 -> 8,414 lift (HR-153) is comparison.yaml data."""
    education_only = _retuned(rules, education_source_kinds=["education"])
    signals = build_job_signals(_jdfn_blob_jd(), rules=education_only)
    assert signals.education_ordinal is None


def test_experience_prefers_experience_quals_then_falls_back_to_knowledge() -> None:
    """The bar is read from `experience` quals first (max), then the knowledge blob."""
    jd = SFUJobDescription(
        title="Analyst",
        qualifications=[
            _qual("Three years in a related role", "experience"),
            _qual("7 years of progressive experience preferred", "experience"),
            _qual("Bachelor's degree and five years of experience", "knowledge"),
        ],
    )
    # max across the experience quals (7), not the knowledge blob's 5
    assert build_job_signals(jd).experience_years == 7

    knowledge_only = SFUJobDescription(
        title="Analyst",
        qualifications=[_qual("A degree and ten years of experience", "knowledge")],
    )
    assert build_job_signals(knowledge_only).experience_years == 10


def test_experience_source_kinds_are_data(rules: Rules) -> None:
    """The experience source kinds + their fallback order are comparison.yaml data
    (HR-154), not a literal tuple. MUTATION: drop the `knowledge` fallback and a JD
    whose only years live in the knowledge blob loses its experience bar."""
    knowledge_only = SFUJobDescription(
        title="Analyst",
        qualifications=[_qual("A degree and ten years of experience", "knowledge")],
    )
    assert build_job_signals(knowledge_only).experience_years == 10
    no_fallback = _retuned(rules, experience_source_kinds=["experience"])
    assert build_job_signals(knowledge_only, rules=no_fallback).experience_years is None


# --- the CUPE skill-list JD: clean skill/ability quals -> keyword bag ----------


def _cupe_skill_jd() -> SFUJobDescription:
    return SFUJobDescription(
        title="Program Assistant",
        employee_group="cupe",
        qualifications=[
            _qual("Excellent knowledge of Python and PostgreSQL", "skill"),
            _qual("Ability to operate spreadsheet and database software", "ability"),
            _qual("Five years of related experience", "experience"),  # not a skill kind
        ],
    )


def test_cupe_skill_bag_is_clean_and_noise_words_are_absent(rules: Rules) -> None:
    bag = build_job_signals(_cupe_skill_jd()).skills
    # real signal survives
    assert {"python", "postgresql", "spreadsheet", "database"} <= bag
    # measured top-20 noise is stripped
    assert not ({"knowledge", "ability", "excellent", "experience", "related"} & bag)
    # the `experience` qual is not a skill source: its years/tokens never reach the bag
    assert "five" not in bag


def test_emptying_the_stopword_list_lets_noise_back_in(rules: Rules) -> None:
    """MUTATION: empty `skill_stopwords` (HR-150) and the top-20 noise floods the bag —
    proof the list is what makes the bag meaningful, and that it is data."""
    no_stopwords = _retuned(rules, skill_stopwords=[])
    bag = build_job_signals(_cupe_skill_jd(), rules=no_stopwords).skills
    assert {"knowledge", "ability", "excellent"} <= bag


def test_min_token_len_is_data(rules: Rules) -> None:
    jd = SFUJobDescription(
        title="Clerk",
        qualifications=[_qual("go qa ci pipelines", "skill")],
    )
    # shipped: min length 3 drops the 2-char tokens
    assert build_job_signals(jd).skills == frozenset({"pipelines"})
    shorter = _retuned(rules, skill_min_token_len=2)
    assert {"go", "qa", "ci"} <= build_job_signals(jd, rules=shorter).skills


# --- the zero-qual JD: honest emptiness, no crash -----------------------------


def test_zero_qual_jd_is_empty_not_broken() -> None:
    """41% of the archive. Empty skills + None seniority is correct, not a bug."""
    jd = SFUJobDescription(title="Research Assistant")
    signals = build_job_signals(jd)
    assert signals.skills == frozenset()
    assert signals.education_ordinal is None
    assert signals.experience_years is None
    assert signals.supervisory_reports is None
    assert signals.title == "Research Assistant"


# --- supervisory scope from the Relationships section -------------------------


def test_supervisory_reports_read_from_relationships() -> None:
    jd = SFUJobDescription(
        title="Manager, Research Services",
        relationships=SFURelationships(supervisory="Supervises 4 coordinators."),
    )
    signals = build_job_signals(jd)
    assert signals.supervisory_reports == 4

    qualitative = SFUJobDescription(
        title="Manager",
        relationships=SFURelationships(supervisory="Leads the communications team"),
    )
    assert build_job_signals(qualitative).supervisory_reports is None


# --- the title anchors: director vs assistant (3.4b's hard constraint) --------


def test_director_and_assistant_titles_differ_on_family_and_restriction(
    rules: Rules,
) -> None:
    """What Tier-3's hard constraint keys on: a director and an assistant are not the
    same role. The reserved-phrase flag reuses `titles.yaml :: restricted`."""
    director = canonical_title("Executive Director, Research Services")
    assistant = canonical_title("Administrative Assistant")
    assert director.family != assistant.family
    assert director.restricted is True  # "executive director" is SFU-reserved (Part 3)
    assert assistant.restricted is False


def test_canonical_title_composes_the_existing_classifiers() -> None:
    # normalize_title drops seniority/level markers
    assert canonical_title("Senior Developer II").normalized == "developer"
    # the functional dimension is independent of the seniority family
    analyst = canonical_title("Data Analyst")
    assert analyst.function == "analyst"
    assert analyst.restricted is False
    # a bare reserved phrase is caught
    assert canonical_title("Registrar").restricted is True
    # the comma format signals supervision without a caller flag
    assert canonical_title("Manager, Laboratory Operations").comma_supervisory is True


def test_build_job_signals_carries_the_title_anchors() -> None:
    jd = SFUJobDescription(
        title="Manager, Laboratory Operations", department="Chemistry"
    )
    signals = build_job_signals(jd)
    assert signals.normalized_title == canonical_title(jd.title).normalized
    assert signals.family == "manager"
    assert signals.comma_supervisory is True
    assert signals.department == "Chemistry"


# --- the models are frozen + closed -------------------------------------------


def test_job_signals_and_canonical_title_are_frozen_and_closed() -> None:
    signals = build_job_signals(SFUJobDescription(title="Clerk"))
    assert signals.model_config["frozen"] is True
    assert signals.model_config["extra"] == "forbid"
    with pytest.raises(ValidationError):
        signals.title = "mutated"  # frozen: no in-place reassignment
    with pytest.raises(ValidationError):
        JobSignals(  # type: ignore[call-arg]
            skills=frozenset(),
            education_ordinal=None,
            experience_years=None,
            supervisory_reports=None,
            title="x",
            normalized_title="x",
            family="unmapped",
            function="unmapped",
            comma_supervisory=False,
            restricted=False,
            surprise=1,  # extra field
        )
    title = canonical_title("Clerk")
    assert title.model_config["frozen"] is True
    with pytest.raises(ValidationError):
        CanonicalTitle(  # type: ignore[call-arg]
            raw="x",
            normalized="x",
            family="unmapped",
            function="unmapped",
            surprise=1,
        )


# --- the new rulebook knobs: registered, on the surface, hashed ---------------


def test_the_new_comparison_knobs_are_on_the_decision_surface(rules: Rules) -> None:
    surface = decision_surface(rules)
    for field in (
        "skill_source_kinds",
        "skill_stopwords",
        "skill_min_token_len",
        "experience_word_numbers",
        "experience_source_kinds",
        "education_source_kinds",
    ):
        assert f"comparison.{field}" in surface, field
    # ...and the register accounts for every one of them (no drift, all registered)
    assert check_register(rules) == ()


def test_moving_a_new_knob_moves_rules_version(rules: Rules) -> None:
    """comparison.yaml IS hashed, so a new knob's value is part of `rules_version` — a
    silent retune of what the clusterer computes cannot hide."""
    assert _retuned(rules, skill_min_token_len=4).version != rules.version
    assert _retuned(rules, experience_word_numbers={}).version != rules.version


def test_signals_module_does_not_import_jd_bank() -> None:
    """The ratchet, at the file that most wants to reach for a runner: the pure adapter
    stays in `jd_core` and never imports `jd_bank` (also covered corpus-wide by
    `test_decision_register.test_no_new_core_to_bank_import_appears`)."""
    source = (
        Path(__file__).resolve().parents[2] / "src" / "jd_core" / "bank" / "signals.py"
    ).read_text(encoding="utf-8")
    assert "src.jd_bank" not in source

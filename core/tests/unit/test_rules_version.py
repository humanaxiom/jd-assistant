"""``rules_version`` must identify the rules that produced a report.

The defect. Every :class:`JDQualityReport` is stamped ``rules_version`` as provenance
(CLAUDE.md non-negotiable #6). Until Phase 2.5-prep that stamp was the literal string
every YAML carried — ``jd_rules_sfu_v3`` — and the rules under it changed materially
across 2.2, 2.3 and 2.4 (new files, new gates, 45 new decisions) without it moving.
Two reports stamped ``v3`` could have been produced by different rulebooks. The
string tracked nothing, and Phase 2.5 was about to pin the archive baseline to it.

The fix: ``Rules.version`` is now ``<declared>+<12 hex of a SHA-256 over the
canonicalised rule data>``. This suite is its spec:

1. **It moves when a rule moves.** One test per hashed rule file — change a value,
   the stamp changes. *That is the whole point*, so it is asserted file by file, not
   in aggregate.
2. **It does not move when nothing decided moves.** Comments, key order, quoting and
   line wrapping are not rules; neither is the decision register's prose.
3. **It is deterministic** — across processes and across ``PYTHONHASHSEED`` (no
   reliance on Python's randomised ``hash()``, no clock, no file mtime).
4. **It is readable, and it fits.** An HR reader holding an old report can tell at a
   glance which rulebook it came from; the string fits the persisted column.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Final

import pytest
import yaml

from src.jd_bank.db.models import ValidationReport
from src.jd_core.quality import build_report
from src.jd_core.rules import (
    CONTENT_HASH_LENGTH,
    REGISTER_FILE,
    RULE_FILES,
    VERSION_SEPARATOR,
    Rules,
    get_rules,
    load_rules,
)

_PKG_DIR: Final[Path] = (
    Path(__file__).resolve().parents[2] / "src" / "jd_core" / "rules"
)

DECLARED_VERSION: Final[str] = "jd_rules_sfu_v4"

#: A valid, minimal edit to each rule file that a human might plausibly make — and
#: that MUST move the stamped version. One per hashed file: a table, so a new rule
#: file added without an entry here fails `test_every_hashed_rule_file_is_covered`.
MUTATIONS: Final[dict[str, Any]] = {
    "thresholds.yaml": lambda d: d.update(duties_max=d["duties_max"] + 1),
    "action_verbs.yaml": lambda d: d["approved"].append("supports"),
    # NB: not `pop("compassionate")` — HR-058 registers that exact path, so deleting
    # it fails at LOAD (a register entry naming a dead config key). The register's
    # own guard rail, working.
    "coded_terms.yaml": lambda d: d["low"].update({"driven": '"motivated"'}),
    "qualifications.yaml": lambda d: d["banned_phrases"].append("desirable"),
    "markers.yaml": lambda d: d["working_conditions"].remove("parking"),
    "patterns.yaml": lambda d: d["senior_title"].update(pattern=r"\bsenior|lead\b"),
    "titles.yaml": lambda d: d["family_keywords"]["director"].append("dean"),
    "boilerplate.yaml": lambda d: d.update(coded_term_scan_exempt=["about_sfu"]),
    "hay_signals.yaml": lambda d: d["know_how_levels"].update(high=6.0),
    "comparison.yaml": lambda d: d.update(clone_threshold=0.93),
    "scoring.yaml": lambda d: d["severity_penalty"].update(low=6.0),
    "rule_catalog.yaml": lambda d: d["section_labels"].update(general="General"),
    "gates.yaml": lambda d: d.update(max_listed=d["max_listed"] + 1),
}


def _write_rules(directory: Path) -> None:
    for name in RULE_FILES:
        (directory / name).write_text(
            (_PKG_DIR / name).read_text(encoding="utf-8"), encoding="utf-8"
        )


def _patch(directory: Path, name: str, mutate: Any) -> None:
    data = yaml.safe_load((directory / name).read_text(encoding="utf-8"))
    mutate(data)
    (directory / name).write_text(
        yaml.safe_dump(data, allow_unicode=True), encoding="utf-8"
    )


@pytest.fixture
def rules() -> Rules:
    return get_rules()


# --- 1. change a rule -> the stamp moves. The whole point. --------------------


def test_every_hashed_rule_file_is_covered_by_a_mutation() -> None:
    """Nobody may add a rule file that this suite does not prove the version tracks."""
    hashed = set(RULE_FILES) - {REGISTER_FILE}
    assert set(MUTATIONS) == hashed, sorted(hashed.symmetric_difference(MUTATIONS))


@pytest.mark.parametrize("name", sorted(MUTATIONS))
def test_changing_a_rule_moves_the_stamped_version(
    tmp_path: Path, rules: Rules, name: str
) -> None:
    _write_rules(tmp_path)
    _patch(tmp_path, name, MUTATIONS[name])
    tuned = load_rules(tmp_path)

    assert tuned.declared_version == rules.declared_version  # the human half is stable
    assert tuned.content_hash != rules.content_hash, name
    assert tuned.version != rules.version, name


def test_a_report_is_stamped_with_the_rules_that_produced_it(
    tmp_path: Path, rules: Rules
) -> None:
    """The provenance claim, end to end (CLAUDE.md #6): two reports over the SAME
    findings, scored under two DIFFERENT rulebooks, must not carry the same stamp."""
    _write_rules(tmp_path)
    _patch(tmp_path, "scoring.yaml", MUTATIONS["scoring.yaml"])
    tuned = load_rules(tmp_path)

    from uuid import uuid4

    job_id = uuid4()
    shipped_report = build_report(
        job_id=job_id, issues=[], model="none", prompt_version="none", rules=rules
    )
    tuned_report = build_report(
        job_id=job_id, issues=[], model="none", prompt_version="none", rules=tuned
    )
    assert shipped_report.rules_version == rules.version
    assert tuned_report.rules_version == tuned.version
    assert shipped_report.rules_version != tuned_report.rules_version


def test_a_retuned_rulebook_cannot_stamp_a_stale_version(rules: Rules) -> None:
    """``model_copy`` is how the suites retune a rulebook, and it does not re-run
    validation. If the version were a stored field it would survive the copy and the
    retuned rules would stamp a lie. It is derived, so it cannot."""
    retuned = rules.model_copy(
        update={
            "thresholds": rules.thresholds.model_copy(
                update={"duties_max": rules.thresholds.duties_max + 1}
            )
        }
    )
    assert retuned.version != rules.version


# --- 2. it does NOT move when nothing decided moves ---------------------------


def test_reformatting_the_yaml_does_not_move_the_version(
    tmp_path: Path, rules: Rules
) -> None:
    """Comments, key order, quoting and line wrapping are not rules. Every file is
    round-tripped through ``safe_load``/``safe_dump`` with keys re-sorted — which
    strips every comment and reorders every mapping — and the identity must hold."""
    for name in RULE_FILES:
        data = yaml.safe_load((_PKG_DIR / name).read_text(encoding="utf-8"))
        (tmp_path / name).write_text(
            yaml.safe_dump(
                data, sort_keys=True, allow_unicode=True, default_flow_style=False
            ),
            encoding="utf-8",
        )
    assert load_rules(tmp_path).version == rules.version


def test_editing_the_registers_prose_does_not_move_the_version(
    tmp_path: Path, rules: Rules
) -> None:
    """``decision_register.yaml`` describes the rules; it does not change what they
    decide about a JD. A copy-edit to an HR explanation must not invalidate every
    report ever stamped. (A real rule change is still caught — by every test above,
    and by ``check_register``, which fails the build if the register drifts.)"""

    def _reword(data: dict[str, Any]) -> None:
        data["decisions"][0]["why_it_matters"] += " (Clarified for HR, 2026.)"

    _write_rules(tmp_path)
    _patch(tmp_path, REGISTER_FILE, _reword)
    assert load_rules(tmp_path).version == rules.version


def test_the_version_is_stable_across_loads(rules: Rules, tmp_path: Path) -> None:
    _write_rules(tmp_path)
    assert load_rules(tmp_path).version == load_rules(tmp_path).version == rules.version


# --- 3. deterministic: no hash randomization, no clock, no mtime ---------------


@pytest.mark.parametrize("seed", ["0", "1", "12345", "random"])
def test_the_version_does_not_depend_on_python_hash_randomization(seed: str) -> None:
    """Computed in a FRESH process under a different ``PYTHONHASHSEED`` each time.

    Sets are canonicalised sorted and mappings by sorted key precisely so this holds;
    a digest over an unordered ``frozenset``'s iteration order would pass in-process
    and give a different answer on the next container start — silently making every
    stamped report unverifiable.
    """
    env = {**os.environ, "PYTHONHASHSEED": seed}
    out = subprocess.run(  # noqa: S603 - fixed argv, no shell
        [
            sys.executable,
            "-c",
            "from src.jd_core.rules import get_rules; print(get_rules().version)",
        ],
        capture_output=True,
        text=True,
        check=True,
        env=env,
        cwd=Path(__file__).resolve().parents[2],
    )
    assert out.stdout.strip() == get_rules().version


def test_the_hash_is_a_sha256_of_the_canonicalised_rules(rules: Rules) -> None:
    """No timestamps, no mtimes, no environment: the digest is a pure function of the
    rule data, so the same rules on another machine give the same stamp."""
    assert re.fullmatch(r"[0-9a-f]{64}", rules.content_hash)
    # ...and it is json-canonicalisable data, not an object address.
    json.dumps(rules.declared_version)


# --- 4. readable to HR, and it fits what we persist ---------------------------


def test_the_stamp_is_readable_and_names_the_rulebook(rules: Rules) -> None:
    """A bare digest is useless to HR and a bare label tracks nothing — so it is both.
    An HR reader holding an old report compares ONE string against today's."""
    assert rules.version == (
        f"{DECLARED_VERSION}{VERSION_SEPARATOR}"
        f"{rules.content_hash[:CONTENT_HASH_LENGTH]}"
    )
    assert re.fullmatch(r"jd_rules_sfu_v\d+\+[0-9a-f]{12}", rules.version)
    assert rules.declared_version == DECLARED_VERSION


def test_every_rule_file_declares_the_same_human_version(rules: Rules) -> None:
    declared = {
        getattr(rules, field).version
        for field in type(rules).model_fields
        if hasattr(getattr(rules, field), "version")
    }
    assert declared == {DECLARED_VERSION}


def test_the_stamp_fits_the_column_it_is_persisted_in(rules: Rules) -> None:
    """``validation_reports.rules_version`` is ``String(64)``. A stamp that silently
    truncated on write would be provenance that lies."""
    column = ValidationReport.__table__.columns["rules_version"]
    assert column.type.length is not None
    assert len(rules.version) <= column.type.length

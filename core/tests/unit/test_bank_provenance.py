"""Unit tests for harmonization provenance (skill frequency).

Ported from hris ``tests/unit/test_jd_bank_provenance.py`` (3 tests, verbatim
behaviour) — the hris suite is the behavioural oracle for this EXTRACT port
(ADR-005 #11). Imports rewritten to jd_core paths.
"""

from __future__ import annotations

from src.jd_core.bank import skill_frequency


def test_counts_members_requiring_each_skill() -> None:
    members = [{"python", "sql"}, {"python", "go"}, {"python"}]
    assert skill_frequency(members) == [("python", 3), ("go", 1), ("sql", 1)]


def test_dedups_within_a_member() -> None:
    # A skill listed twice by one member still counts once for that member.
    assert skill_frequency([["python", "python"], ["python"]]) == [("python", 2)]


def test_empty() -> None:
    assert skill_frequency([]) == []

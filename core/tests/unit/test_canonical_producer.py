"""The Phase-4.4a canonical PRODUCER — pure per-cluster logic.

The DB-touching invariants (no-clobber / idempotency / append-only audit / draft-only on
a real row) live in ``tests/integration/test_canonical_producer.py`` — they need a real
Postgres. Here: the no-clobber PREDICATE (all four combinations), the reviewer-packet
builder round-trips, the frozen counts-only result, and the WJQ proxy REUSE (imported
from the harmonize runner, never forked).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.jd_bank.canonical import __main__ as cli
from src.jd_bank.canonical import runner as canon_runner
from src.jd_bank.canonical.models import CanonicalProducerResult
from src.jd_bank.canonical.runner import (
    DRAFT,
    build_change_log_packet,
    reviewer_touched,
)
from src.jd_bank.db.models import CanonicalStatus
from src.jd_bank.harmonize import runner as harmonize_runner
from src.jd_core.models.bank import (
    HarmonizationDiff,
    MergedRole,
    MergeProvenance,
)
from src.jd_core.models.parsed_jd import SFUJobDescription
from src.jd_core.models.quality import GateDecision, GateReason
from src.jd_core.rules import get_rules

# --- the no-clobber predicate (all four combinations) ---------------------------------


def test_an_untouched_draft_is_the_only_refreshable_canonical() -> None:
    """Only a DRAFT with zero review actions may be refreshed — every other state is a
    human artifact the producer must leave untouched (NN #1)."""
    assert reviewer_touched(CanonicalStatus.DRAFT, 0) is False


@pytest.mark.parametrize(
    ("status", "actions"),
    [
        (CanonicalStatus.DRAFT, 1),  # a reviewer acted on it (approve/reject/edit)
        (CanonicalStatus.PUBLISHED, 0),  # published — a human artifact
        (CanonicalStatus.ARCHIVED, 0),  # archived — a human artifact
        (CanonicalStatus.PUBLISHED, 3),  # both
    ],
)
def test_a_reviewer_touched_canonical_is_never_refreshed(
    status: CanonicalStatus, actions: int
) -> None:
    """The guard fires on a non-DRAFT status OR any review action — the two halves of
    'a human touched this'. Each combination must count as touched, so the producer
    skips it (integration proves it byte-identical)."""
    assert reviewer_touched(status, actions) is True


# --- the reviewer packet (change_log JSONB) round-trips -------------------------------


def _merged() -> MergedRole:
    return MergedRole(
        draft=SFUJobDescription(title="Data Analyst"),
        provenance=MergeProvenance(
            member_count=2,
            skill_frequency=(("python", 2), ("sql", 1)),
            flags=("no_core_skills",),
        ),
    )


def _blocked_decision() -> GateDecision:
    return GateDecision(
        approved=False,
        blocking=(
            GateReason(
                gate_id="SFU-COMP-SUMMARY",
                source_part="Part 4",
                reason="the position summary is missing",
                overridable=True,
            ),
        ),
    )


def test_the_change_log_packet_round_trips_to_the_reviewer_artifacts() -> None:
    """The packet is a self-contained reviewer artifact: it round-trips to the 4.3 diff,
    the merge provenance, and the validator roll-up (score/grade + GateDecision), and it
    is JSON-safe (every value came from ``model_dump(mode='json')``)."""
    merged = _merged()
    diff = HarmonizationDiff(rendered_draft="Data Analyst\n...")
    decision = _blocked_decision()

    packet = build_change_log_packet(
        merged=merged,
        diff=diff,
        rewritten=None,
        quality_audit=None,
        issues=[],
        score=41.0,
        grade="F",
        gate_decision=decision,
        rules_version="jd_rules_sfu_v4+abc",
        llm_enabled=False,
        rewrite_failed=False,
        audit_failed=False,
    )

    # 4.3 diff + merge provenance survive the round trip.
    assert HarmonizationDiff.model_validate(packet["harmonization_diff"]) == diff
    assert packet["merge_provenance"]["flags"] == ["no_core_skills"]
    assert packet["merge_provenance"]["skill_frequency"] == [["python", 2], ["sql", 1]]

    # The validator roll-up + the GateDecision — approvable=False while gates block.
    roll = packet["validator"]
    assert roll["score"] == 41.0
    assert roll["grade"] == "F"
    reconstructed = GateDecision.model_validate(roll["gate_decision"])
    assert reconstructed.approved is False
    assert [r.gate_id for r in reconstructed.blocking] == ["SFU-COMP-SUMMARY"]

    # Deterministic-only run: rewrite/audit recorded as NOT run.
    assert packet["anti_fabrication"] is None
    assert packet["quality_audit"] is None
    assert packet["pipeline"] == {
        "llm_enabled": False,
        "rewrite_ran": False,
        "rewrite_failed": False,
        "audit_ran": False,
        "audit_failed": False,
    }


# --- the WJQ proxy is REUSED, never forked -------------------------------------------


def test_the_wjq_proxy_is_imported_from_the_harmonize_runner_not_forked() -> None:
    """Acceptance #7: the producer reuses the harmonize runner's ``is_wjq_member`` /
    ``member_has_frequency`` (one home). Same function OBJECT — not a second copy that
    could silently disagree on which members are WJQ."""
    assert canon_runner.is_wjq_member is harmonize_runner.is_wjq_member
    assert canon_runner.member_has_frequency is harmonize_runner.member_has_frequency


# --- draft-only + counts-only frozen result ------------------------------------------


def test_the_producer_writes_only_the_draft_status() -> None:
    """The only status the producer writes is DRAFT (NN #1 — nothing publishes)."""
    assert DRAFT is CanonicalStatus.DRAFT


def _result() -> CanonicalProducerResult:
    return CanonicalProducerResult(
        documents_seen=10,
        documents_signed=9,
        documents_unsignable=1,
        clusters_recomputed=3,
        wjq_members_excluded=2,
        wjq_members_frequency_confirmed=2,
        clusters_fully_wjq_excluded=1,
        clusters_mixed_jdfn_wjq=0,
        member_rows_dropped_unvalidatable=0,
        clusters_seen=2,
        multi_member_clusters=2,
        single_member_clusters=0,
        drafts_persisted=2,
        drafts_refreshed=0,
        skipped_reviewer_touched=0,
        cluster_failures=0,
        rewrite_failures=0,
        audit_failures=0,
        rules_version="jd_rules_sfu_v4+abc",
        llm_enabled=False,
        rewrite_model="gpt-oss:120b",
        rewrite_prompt_version="jd_harmonize_v1",
        quality_model="gpt-oss:120b",
        quality_prompt_version="jd_quality_v1",
    )


def test_the_result_is_frozen_and_counts_only() -> None:
    """The result is an audit record — frozen (cannot be edited after the fact) and it
    carries no JD-text field, only counts + stamps."""
    result = _result()
    with pytest.raises(ValidationError):
        result.drafts_persisted = 99  # type: ignore[misc]
    # Counts-only: no field carries JD prose (content lives on the persisted rows).
    forbidden = {"content", "draft", "drafts", "clusters", "jds", "members"}
    assert not (set(CanonicalProducerResult.model_fields) & forbidden)


# --- the two-client CLI wiring (NN #6: the audit stamp cannot lie) --------------------


def test_build_clients_binds_the_audit_client_to_the_quality_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``_build_clients`` must bind the audit client EXPLICITLY to ``rules.quality`` so
    ``QualityAudit.model`` (always stamped ``rules.quality.model``) cannot lie once the
    rewrite and quality YAMLs diverge (NN #6). The rewrite client is left on the
    ``ChatClient`` default (``rules.rewrite.model`` — no explicit ``model`` kwarg).
    Forces the two models apart so a regression that binds the audit to the rewrite
    model — or reuses one client for both — is caught, not masked by identical defaults.
    """
    built: list[dict[str, object]] = []

    class _RecordingClient:
        def __init__(self, **kwargs: object) -> None:
            built.append(kwargs)

    monkeypatch.setattr(cli, "ChatClient", _RecordingClient)

    rules = get_rules()
    rules = rules.model_copy(
        update={
            "quality": rules.quality.model_copy(
                update={"model": "QUALITY-ONLY-MODEL", "temperature": 0.42}
            )
        }
    )

    rewrite_client, audit_client = cli._build_clients(rules, no_llm=False)

    assert rewrite_client is not None
    assert audit_client is not None
    assert len(built) == 2
    rewrite_kwargs, audit_kwargs = built
    # Rewrite: no explicit model -> ChatClient falls back to rules.rewrite.model.
    assert rewrite_kwargs.get("model") is None
    # Audit: bound to the quality model/temperature, distinct from the rewrite default.
    assert audit_kwargs["model"] == "QUALITY-ONLY-MODEL"
    assert audit_kwargs["temperature"] == 0.42


def test_build_clients_no_llm_yields_no_clients() -> None:
    """``--no-llm`` -> ``(None, None)``: the deterministic path, no Ollama needed."""
    assert cli._build_clients(get_rules(), no_llm=True) == (None, None)

"""The Phase-4.4a canonical PRODUCER — pure per-cluster logic.

The DB-touching invariants (no-clobber / idempotency / append-only audit / draft-only on
a real row) live in ``tests/integration/test_canonical_producer.py`` — they need a real
Postgres. Here: the no-clobber PREDICATE (all four combinations), the reviewer-packet
builder round-trips, the frozen counts-only result, and the WJQ proxy REUSE (imported
from the harmonize runner, never forked).
"""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from src.jd_bank.canonical import __main__ as cli
from src.jd_bank.canonical import runner as canon_runner
from src.jd_bank.canonical.models import CanonicalProducerResult, TemplateEvaluation
from src.jd_bank.canonical.runner import (
    DRAFT,
    build_change_log_packet,
    reviewer_touched,
)
from src.jd_bank.db.models import CanonicalStatus
from src.jd_bank.harmonize import models as harmonize_models
from src.jd_bank.harmonize import runner as harmonize_runner
from src.jd_core.models import quality as quality_models
from src.jd_core.models.bank import (
    HarmonizationDiff,
    MergedRole,
    MergeProvenance,
)
from src.jd_core.models.parsed_jd import SFUJobDescription
from src.jd_core.models.quality import GateDecision, GateReason
from src.jd_core.quality import validators
from src.jd_core.rules import Harmonization, get_rules

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
    """Acceptance #7: the producer reuses the harmonize runner's helpers (one home).
    Same function OBJECT — not a second copy that could silently disagree on which
    members are WJQ."""
    assert canon_runner.member_has_frequency is harmonize_runner.member_has_frequency
    # The producer partitions by `template_of` rather than by `is_wjq_member` (a
    # partition needs the FORM, not a boolean), so the anti-fork property is now that
    # the two answer identically — pinned below over both values.
    assert canon_runner.template_of is validators.template_of


def test_there_is_exactly_one_definition_of_which_documents_are_cupe() -> None:
    """🔴 THE FORK THIS TEST DID NOT USED TO CATCH.

    ``jd_bank.harmonize.models`` defined ``WJQ_EMPLOYEE_GROUP = "cupe"`` and Phase B
    gave ``jd_core.models.quality`` a second literal ``"cupe"`` for ``template_of`` /
    ``applies_to``. Two independent definitions of *which documents are CUPE*: the
    producer's member filter and the validator's rule selection could have drifted
    apart, and a member dropped from a merge as WJQ would still have been JUDGED as
    JDFN. The old assertion pinned ``jd_bank``'s two runners to each other — one layer
    below where the fork actually was.

    Pinned two ways, because the constant being shared is not the same claim as the two
    predicates agreeing: the value is one object, and ``is_wjq_member`` is expressed in
    terms of ``template_of`` rather than re-deriving it.
    """
    assert harmonize_models.WJQ_EMPLOYEE_GROUP is quality_models.WJQ_EMPLOYEE_GROUP

    cupe = SFUJobDescription(title="Clerk", employee_group="cupe")
    apsa = SFUJobDescription(title="Analyst", employee_group="apsa")
    none = SFUJobDescription(title="Analyst")
    for jd in (cupe, apsa, none):
        assert harmonize_runner.is_wjq_member(jd) is (
            validators.template_of(jd) == quality_models.WJQ_TEMPLATE
        )


# --- which FORM authors a cluster (HR-206, CUPE Phase D) -----------------------------


def _pair(group: str | None) -> tuple[uuid.UUID, SFUJobDescription]:
    return uuid.uuid4(), SFUJobDescription(title="Analyst", employee_group=group)


def _harmonization(*templates: str) -> Harmonization:
    """A variant of the shipped harmonization block, RE-CONSTRUCTED rather than
    ``model_copy(update=…)``-ed — the same reason ``Rules.thresholds_for`` re-runs its
    model: ``model_copy`` skips validation, so a fixture built that way can hand the
    code under test a config the loader would have refused."""
    data = {
        **get_rules().harmonization.model_dump(),
        "templates_harmonized": tuple(templates),
    }
    return Harmonization(**data)


def test_a_cluster_is_authored_on_the_first_listed_form_present_in_it() -> None:
    """``templates_harmonized`` is a PRIORITY order: a MIXED cluster authors on the
    first listed form it actually holds, so shipping ``[jdfn, wjq]`` leaves every mixed
    cluster doing exactly what it did before Phase D. Reversing the list moves it —
    which is the mutation that proves the order is read at all, not just the membership.
    """
    by_form = canon_runner.partition_by_template([_pair("apsa"), _pair("cupe")])
    assert sorted(by_form) == ["jdfn", "wjq"]

    assert canon_runner.authoring_template(by_form, _harmonization("jdfn", "wjq")) == (
        "jdfn"
    )
    assert canon_runner.authoring_template(by_form, _harmonization("wjq", "jdfn")) == (
        "wjq"
    )


def test_a_cluster_with_no_listed_form_authors_nothing() -> None:
    """The pre-Phase-D behaviour, reachable by configuration alone: with ``wjq`` off the
    list an all-CUPE cluster has no authoring form and produces no draft. ``None`` is
    the honest answer — not a fallback to JDFN, which would author a CUPE role's draft
    against a form it was never written on."""
    by_form = canon_runner.partition_by_template([_pair("cupe"), _pair("cupe")])
    assert canon_runner.authoring_template(by_form, _harmonization("jdfn")) is None
    assert canon_runner.authoring_template(by_form, _harmonization("jdfn", "wjq")) == (
        "wjq"
    )


def test_a_form_may_not_be_listed_twice() -> None:
    """A repeated template is unreachable in a priority order, and an unreachable entry
    in a policy list reads like a decision that was never made."""
    with pytest.raises(ValidationError):
        _harmonization("jdfn", "wjq", "jdfn")


def test_the_shipped_rulebook_harmonizes_both_forms() -> None:
    """The shipped default is HR-206's ``[jdfn, wjq]`` — pinned here so removing CUPE
    from the Bank's drafting scope has to be an argued diff, not a quiet YAML edit."""
    assert get_rules().harmonization.templates_harmonized == ("jdfn", "wjq")


# --- the no-DOWNGRADE rule (found by running it against the live Bank) ---------------


@pytest.mark.parametrize(
    ("change_log", "llm_enabled", "expected"),
    [
        # The defect: a cheap run over an expensive draft.
        ({"pipeline": {"llm_enabled": True}}, False, True),
        # A full run may always refresh — it is at least as good.
        ({"pipeline": {"llm_enabled": True}}, True, False),
        # Deterministic over deterministic is a like-for-like refresh, not a downgrade.
        ({"pipeline": {"llm_enabled": False}}, False, False),
        # Provenance we cannot establish is not treated as precious: an unreadable
        # packet must not make the producer un-runnable against rows it did not write.
        ({}, False, False),
        (None, False, False),
        ({"pipeline": None}, False, False),
        ({"pipeline": "not-a-mapping"}, False, False),
    ],
)
def test_only_a_cheap_run_over_an_llm_written_draft_is_a_downgrade(
    change_log: dict[str, object] | None, llm_enabled: bool, expected: bool
) -> None:
    """🔴 THE DEFECT, found by running the producer against the LIVE Bank on 2026-08-17.

    `--no-llm` refreshed 1,763 untouched JDFN drafts, discarding the rewrite pass on
    every one, and reported it as ``drafts_refreshed`` — a word that reads like an
    improvement. The cohort's mean fell from 73.0 to 52.73 in thirty-two seconds and
    nothing in the output said a capability had been REMOVED.

    The existing no-clobber rule protects HUMAN work and says nothing about PIPELINE
    work. That was a fair place to stop while every run was a full run; it stopped being
    fair the moment the producer had a cheap mode.
    """
    assert canon_runner.would_downgrade(change_log, llm_enabled=llm_enabled) is expected


# --- per-form evaluation: there is no blended number to quote (CUPE Phase D) ---------


def test_the_result_carries_no_field_that_scores_both_forms_at_once() -> None:
    """🔴 THE PROPERTY, and it is about what is ABSENT.

    A CUPE draft is judged by the WJQ profile and a JDFN draft by the JDFN one, so a
    single mean over both is a mean over two different measurements — the category error
    this whole phase removed. The defence is not a convention: the result object has no
    overall score/grade/approvable field at all, so there is nothing for a reader to
    quote and nothing for a later template to render. Every quality figure hangs off
    ``evaluation_by_template``, which cannot be read without naming a form.

    Adding a `mean_score` to the top level turns this red — which is the point, because
    that is exactly the field someone will reach for when asked "so how good are the
    drafts?"
    """
    top_level = set(CanonicalProducerResult.model_fields)
    assert not (top_level & {"mean_score", "score", "grade", "grades", "approvable"})
    per_form = set(TemplateEvaluation.model_fields)
    assert {"mean_score", "approvable", "grades"} <= per_form


def test_an_unscored_cluster_does_not_enter_a_forms_mean_as_a_zero() -> None:
    """A reviewer-touched or failed cluster produced no draft, so the producer scored
    nothing for it. Counting it as a zero would understate the cohort — and it would do
    so exactly where drafts are being reviewed most, since a cluster becomes skippable
    by a human having WORKED on it. ``drafts_scored`` is the denominator, not
    ``clusters``."""
    agg = canon_runner._TemplateAgg()
    agg.clusters = 3  # three entered...
    agg.drafts_scored = 1  # ...one produced a draft
    agg.score_total = 80.0
    agg.grades["B"] = 1

    evaluation = agg.evaluation()
    assert evaluation.clusters == 3
    assert evaluation.drafts_scored == 1
    assert evaluation.mean_score == 80.0  # not 26.67


def test_a_form_that_scored_nothing_reports_zero_rather_than_dividing_by_zero() -> None:
    """A form can be drafted and score nothing — every one of its clusters skipped as
    reviewer-touched. That is a real state on a re-run, not an edge case."""
    assert canon_runner._TemplateAgg().evaluation().mean_score == 0.0


# --- draft-only + counts-only frozen result ------------------------------------------


def test_the_producer_writes_only_the_draft_status() -> None:
    """The only status the producer writes is DRAFT (NN #1 — nothing publishes)."""
    assert DRAFT is CanonicalStatus.DRAFT


def _result(**overrides: object) -> CanonicalProducerResult:
    base: dict[str, object] = dict(
        documents_seen=10,
        documents_signed=9,
        documents_unsignable=1,
        clusters_recomputed=3,
        wjq_members_excluded=2,
        wjq_members_authored=0,
        wjq_members_frequency_confirmed=2,
        clusters_fully_wjq_excluded=1,
        clusters_mixed_jdfn_wjq=0,
        member_rows_dropped_unvalidatable=0,
        clusters_seen=2,
        clusters_by_template={"jdfn": 2},
        evaluation_by_template={
            "jdfn": TemplateEvaluation(
                clusters=2,
                drafts_scored=2,
                mean_score=73.0,
                approvable=1,
                grades={"B": 1, "C": 1},
            )
        },
        multi_member_clusters=2,
        single_member_clusters=0,
        drafts_persisted=2,
        drafts_refreshed=0,
        skipped_reviewer_touched=0,
        skipped_would_downgrade=0,
        skipped_already_llm_written=0,
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
    base.update(overrides)
    return CanonicalProducerResult(**base)  # type: ignore[arg-type]


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


# --- the two partitions, enforced rather than described ------------------------------
#
# The class docstring used to claim "persisted + refreshed + skipped + failed account
# for every cluster the run entered". True when written; false by the time it was read,
# because two skip counters were added underneath it. And three cluster shapes fell
# through EVERY counter, so a run could decline work and still report a total that
# looked complete. Both identities are now model validators — a docstring cannot go
# stale into a ValidationError.


def test_a_result_whose_outcome_buckets_do_not_sum_is_refused() -> None:
    """The first identity. One cluster entered, none accounted for — exactly the shape
    a new outcome bucket that nobody added to the sum would produce."""
    with pytest.raises(ValidationError, match="outcome buckets"):
        _result(clusters_seen=3, clusters_recomputed=4, drafts_persisted=2)


def test_a_result_that_loses_a_cluster_between_recompute_and_entry_is_refused() -> None:
    """The second identity, and the one that catches a genuinely NEW fall-through: a
    cluster the clustering produced that no counter claims. Before these fields existed
    this was silent, which is what let three shapes go missing."""
    with pytest.raises(ValidationError, match="clusters accounted for"):
        _result(clusters_recomputed=9)


def test_the_two_new_decline_reasons_close_the_second_identity() -> None:
    """...and they close it: the same otherwise-unaccounted clusters, once named, make
    the result constructible. This is the pair of tests that says the fields are load-
    bearing rather than decorative."""
    result = _result(
        clusters_recomputed=9,
        clusters_no_authorable_template=3,
        clusters_no_members_loaded=3,
    )
    assert result.clusters_no_authorable_template == 3
    assert result.clusters_no_members_loaded == 3


def test_a_skip_counter_is_part_of_the_outcome_partition() -> None:
    """The regression that made the old docstring false: a cluster skipped by a resume
    (or by the no-downgrade guard) is ENTERED, so it must be in the sum. If someone
    adds a seventh bucket and forgets the validator, this is the shape that goes red."""
    result = _result(
        clusters_seen=4,
        clusters_recomputed=5,
        drafts_persisted=2,
        skipped_already_llm_written=1,
        skipped_would_downgrade=1,
    )
    assert result.clusters_seen == 4


# --- contradictory CLI flags are refused, not silently resolved ----------------------


def test_resume_with_allow_downgrade_is_refused_instead_of_doing_nothing(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """🔴 THE DEFECT: this combination was a SILENT NO-OP that exited 0.

    ``--resume`` skips every cluster holding a landed rewrite; ``--allow-downgrade``
    exists only to overwrite exactly those clusters. Resume is tested first, so it won,
    the deliberate re-baseline never happened, and the run reported success. An operator
    reaching for ``--allow-downgrade`` is discarding a ~44-hour pass on purpose and is
    the last person who should have to infer from a summary that it did not happen.
    """
    exit_code = cli.main(["--resume", "--allow-downgrade", "--no-llm"])
    assert exit_code == 2
    err = capsys.readouterr().err
    assert "--resume and --allow-downgrade contradict" in err


def test_either_flag_alone_is_still_accepted() -> None:
    """The other direction — the guard must reject the CONTRADICTION, not the flags. A
    check that also refused a plain ``--resume`` would break the resume this repo just
    spent #126 making correct."""
    for argv in (["--resume"], ["--allow-downgrade", "--no-llm"]):
        args = cli._parse_args(argv)
        assert cli._reject_contradictory_flags(args) is None

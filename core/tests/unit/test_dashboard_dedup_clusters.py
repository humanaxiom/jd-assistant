"""Unit tests for the Phase-4.6c read-only Dedup (Tier 1/2/3) and Clusters dashboards.

Slices 2 + 3, built to the exact discipline of slice 1 (``test_dashboard.py``): each
page renders values READ FROM its committed artifact — never a hardcoded number. The
load-bearing tests point each loader at a FIXTURE with DISTINCT sentinel numbers and
assert the page shows THOSE numbers, so re-introducing a literal figure into a template
goes red.

Mirrors ``test_dashboard.py``: drive ``TestClient(app)`` WITHOUT the lifespan, override
the per-artifact ``get_*_summary_path`` dependencies to point at fixtures (or at a
missing / corrupt path, to prove the graceful empty-state) — no DB, no real ``docs/``.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.api.main import app
from src.api.routes.dashboard import (
    get_cluster_summary_path,
    get_dedup_summary_path,
    get_near_dup_summary_path,
    get_role_equiv_summary_path,
)

_FIXTURE = Path(__file__).resolve().parent.parent / "fixtures"
_DEDUP = _FIXTURE / "dedup_summary_sentinel.json"
_NEAR = _FIXTURE / "near_dup_summary_sentinel.json"
_ROLE = _FIXTURE / "role_equiv_summary_sentinel.json"
_CLUSTER = _FIXTURE / "cluster_summary_sentinel.json"


@pytest.fixture(autouse=True)
def _clear_overrides() -> Iterator[None]:
    yield
    app.dependency_overrides.clear()


def _dedup_client(
    *, tier1: Path = _DEDUP, tier2: Path = _NEAR, tier3: Path = _ROLE
) -> TestClient:
    app.dependency_overrides[get_dedup_summary_path] = lambda: tier1
    app.dependency_overrides[get_near_dup_summary_path] = lambda: tier2
    app.dependency_overrides[get_role_equiv_summary_path] = lambda: tier3
    return TestClient(app, follow_redirects=False)


def _cluster_client(*, cluster: Path = _CLUSTER) -> TestClient:
    app.dependency_overrides[get_cluster_summary_path] = lambda: cluster
    return TestClient(app, follow_redirects=False)


# --- index links --------------------------------------------------------------------


def test_index_links_to_dedup_and_cluster_pages() -> None:
    client = TestClient(app, follow_redirects=False)

    resp = client.get("/jd-bank/ui/dashboard")

    assert resp.status_code == 200
    assert "/jd-bank/ui/dashboard/dedup" in resp.text
    assert "/jd-bank/ui/dashboard/clusters" in resp.text


# --- GET /dedup — the three tiers on one page, read from three artifacts -------------


def test_dedup_page_renders_all_three_tiers_from_their_files() -> None:
    """Every figure below is a sentinel that appears ONLY in the fixtures, so a passing
    assertion proves the value was read from the artifact, not typed into a template."""
    client = _dedup_client()

    resp = client.get("/jd-bank/ui/dashboard/dedup")

    assert resp.status_code == 200
    body = resp.text

    # Tier-1 (docs/dedup/summary.json).
    assert "70000" in body  # hashed
    assert "60002" in body  # distinct_sha256
    assert "5051" in body  # group_count
    assert "4747" in body  # redundant_files
    assert "21.1" in body  # redundancy_rate 0.211111 -> 21.1%
    assert "3131" in body  # groups_spanning_multiple_positions
    assert "1717" in body  # groups_within_one_position
    assert "8181" in body  # files_in_multi_position_groups
    assert "4141" in body  # edges_star / edges_at_topology
    assert "9393" in body  # edges_clique
    # biggest-group sample: size distribution + an (escaped) archive filename.
    assert "4111" in body and "2111" in body and "611" in body  # size dist counts
    assert "SENTINEL_dupe_alpha.docx" in body  # untrusted filename, rendered
    assert "424242" in body  # byte_size
    # Tier-1 provenance stamp.
    assert "SENTINEL_DEDUP_RULES+aa11bb22" in body
    assert "2097" in body  # generated_at year

    # Tier-2 (docs/dedup/near-dup-summary.json).
    assert "71001" in body  # documents_seen
    assert "61002" in body  # distinct_contents
    assert "60777" in body  # documents_signed
    assert "91.9" in body  # coverage_rate 0.919191 -> 91.9%
    assert "24681" in body  # candidate_pairs
    assert "1191" in body  # edges_written
    assert "13901" in body  # edges_updated
    assert "391" in body  # edges_pruned
    assert "3911" in body  # same_position_edges
    assert "8911" in body  # cross_position_edges
    assert "2911" in body  # unknown_position_edges
    # jaccard percentiles, straight from the artifact.
    assert "0.861" in body and "0.929" in body and "0.977" in body
    assert "SENTINEL_NEAR_STAMP+dd44ee55" in body  # dedup_stamp
    assert "2096" in body

    # Tier-3 (docs/dedup/role-equiv-summary.json).
    assert "134111" in body  # edges_written / qualifying_pairs
    assert "261357" in body  # candidate_pairs
    assert "257111" in body  # admissible_pairs
    assert "2811" in body  # band_vetoed
    assert "1311" in body  # group_vetoed
    assert "3511" in body  # restricted_flagged
    assert "133511" in body  # same_function_edges
    assert "599" in body  # cross_function_edges
    assert "6111" in body  # idf_skills
    assert "71444" in body  # documents_with_vector
    # score percentiles + family distribution, from the artifact.
    assert "0.511" in body and "0.566" in body and "0.988" in body
    assert "10211" in body and "1751" in body  # family distribution counts
    assert "SENTINEL_ROLE_STAMP+ff66aa77" in body  # dedup_stamp
    assert "2095" in body


def test_dedup_page_frames_cross_position_cloning_honestly() -> None:
    """The README framing must be reflected: SFU redundancy is cross-position cloning,
    so the 'same position => duplicate' oracle fails — a one-line note, not a claim."""
    client = _dedup_client()

    body = client.get("/jd-bank/ui/dashboard/dedup").text.lower()

    assert "position" in body
    assert "cross-position" in body or "different positions" in body


def test_dedup_page_degrades_per_tier_when_one_artifact_is_missing(
    tmp_path: Path,
) -> None:
    """A single missing tier must NOT blank the whole page: the others still render.
    Here only Tier-2 is present; Tier-1 and Tier-3 fall to their own empty-states."""
    missing = tmp_path / "nope.json"
    assert not missing.exists()
    client = _dedup_client(tier1=missing, tier2=_NEAR, tier3=missing)

    resp = client.get("/jd-bank/ui/dashboard/dedup")

    assert resp.status_code == 200
    body = resp.text
    # Tier-2 still fully renders from its artifact...
    assert "24681" in body  # candidate_pairs
    assert "make near-dup</code>" not in body  # Tier-2 did NOT fall to empty-state
    # ...while Tier-1 and Tier-3 show their per-tier empty-state hints.
    assert "make dedup</code>" in body  # Tier-1 empty-state (distinct from dedup-role)
    assert "make dedup-role</code>" in body  # Tier-3 empty-state


def test_dedup_page_all_missing_is_graceful_empty_state_not_500(
    tmp_path: Path,
) -> None:
    missing = tmp_path / "nope.json"
    client = _dedup_client(tier1=missing, tier2=missing, tier3=missing)

    resp = client.get("/jd-bank/ui/dashboard/dedup")

    assert resp.status_code == 200
    body = resp.text
    assert "make dedup</code>" in body
    assert "make near-dup</code>" in body
    assert "make dedup-role</code>" in body


def test_dedup_page_corrupt_artifacts_are_graceful(tmp_path: Path) -> None:
    """Present-but-corrupt artifacts degrade to the empty-state, never a 500 — proven
    for each of the three tiers independently."""
    broken = tmp_path / "broken.json"
    broken.write_text("{ not valid json", encoding="utf-8")

    # Corrupt Tier-1 only: Tiers 2 + 3 still render.
    resp = _dedup_client(tier1=broken).get("/jd-bank/ui/dashboard/dedup")
    assert resp.status_code == 200
    assert "make dedup</code>" in resp.text
    assert "24681" in resp.text  # Tier-2 unaffected

    app.dependency_overrides.clear()

    # Corrupt Tier-2 only.
    resp = _dedup_client(tier2=broken).get("/jd-bank/ui/dashboard/dedup")
    assert resp.status_code == 200
    assert "make near-dup</code>" in resp.text
    assert "70000" in resp.text  # Tier-1 unaffected

    app.dependency_overrides.clear()

    # Corrupt Tier-3 only.
    resp = _dedup_client(tier3=broken).get("/jd-bank/ui/dashboard/dedup")
    assert resp.status_code == 200
    assert "make dedup-role</code>" in resp.text
    assert "134111" not in resp.text  # Tier-3 figures gone
    assert "70000" in resp.text  # Tier-1 unaffected


# --- GET /clusters ------------------------------------------------------------------


def test_clusters_page_renders_numbers_from_the_file() -> None:
    client = _cluster_client()

    resp = client.get("/jd-bank/ui/dashboard/clusters")

    assert resp.status_code == 200
    body = resp.text

    assert "2461" in body  # cluster_count
    assert "133" in body  # largest_cluster (and size_distribution key)
    assert "3611" in body  # singletons
    assert "10911" in body  # clustered_documents
    assert "75.1" in body  # coverage_rate 0.751234 -> 75.1%
    assert "150911" in body  # edges_considered
    assert "47111" in body  # edges_admitted
    assert "11" in body  # flagged_clusters
    assert "372" in body  # cross_department_clusters
    assert "151" in body  # restricted_touching_clusters
    assert "1966" in body  # exact_synthesized
    # tier contribution bars.
    assert "616" in body and "2062" in body and "1432" in body
    # size distribution bars.
    assert "1191" in body and "491" in body
    # family distribution.
    assert "10212" in body and "1752" in body and "978" in body
    # provenance.
    assert "SENTINEL_CLUSTER_STAMP+cc99dd00" in body
    assert "SENTINEL_method_alpha" in body
    assert "2094" in body


def test_clusters_page_frames_coverage_honestly() -> None:
    """The cluster page notes what coverage means (most signed JDs land in a cluster;
    the rest are singletons) — a one-line note, not overclaim."""
    client = _cluster_client()

    body = client.get("/jd-bank/ui/dashboard/clusters").text.lower()

    assert "singleton" in body
    assert "coverage" in body


def test_clusters_page_missing_artifact_is_graceful_not_500() -> None:
    missing = _FIXTURE / "does_not_exist_cluster.json"
    assert not missing.exists()
    client = _cluster_client(cluster=missing)

    resp = client.get("/jd-bank/ui/dashboard/clusters")

    assert resp.status_code == 200
    assert "make cluster" in resp.text


def test_clusters_page_corrupt_artifact_is_graceful(tmp_path: Path) -> None:
    broken = tmp_path / "broken.json"
    broken.write_text("{ not valid json", encoding="utf-8")
    client = _cluster_client(cluster=broken)

    resp = client.get("/jd-bank/ui/dashboard/clusters")

    assert resp.status_code == 200
    assert "make cluster" in resp.text

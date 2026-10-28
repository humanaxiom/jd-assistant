"""Unit — the Compensation Requisition Form download page (Track K, K3).

K2 shipped a tested filler that nothing reached: no route, no button. By Directive #1
that is not delivered. These pin the two routes that deliver it —
``GET /jd-bank/ui/role/{cluster_id}/comp-requisition`` (the picker page) and the
``POST`` that streams SFU's own filled PDF — and the two places a person finds them:
the role page in the Library and the Builder's Export block on a cloned draft.

Driven through ``TestClient(app)`` without the lifespan (no DB): the Bank read,
:func:`prefill_from_role`, is replaced with a mock returning a fixed prefill, so the
tests see exactly what the route does with it. Pins:

* the page offers EVERY position the role holds as a picker, flags a possibly partial
  list, and marks each Bank-supplied value *confirm*;
* the download is a real ``application/pdf`` attachment carrying the chosen values;
* a position the role does not hold re-renders the page with the error — no PDF, no
  500 — and a bad request type likewise;
* an unknown role is a 404 page, not a crash;
* the role page and a cloned Builder draft both link here (discoverable).
"""

from __future__ import annotations

import io
import uuid
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader

from src.api.main import app, get_session
from src.api.routes import library as library_routes
from src.jd_bank.forms import REQUEST_TYPE_LABELS
from src.jd_export.comp_requisition import CompReqPrefill, load_field_map

CLUSTER = uuid.uuid4()
PAGE = f"/jd-bank/ui/role/{CLUSTER}/comp-requisition"


def _prefill(**overrides: object) -> CompReqPrefill:
    base: dict[str, object] = {
        "position_title": "Research Coordinator",
        "department": "School of Computing Science",
        "employee_group": "APSA",
        "candidate_positions": ("00001111", "00005555", "00009999"),
        "positions_incomplete": False,
    }
    base.update(overrides)
    return CompReqPrefill(**base)  # type: ignore[arg-type]


def _client() -> TestClient:
    async def override() -> AsyncIterator[object]:
        yield object()

    app.dependency_overrides[get_session] = override
    return TestClient(app)


@pytest.fixture(autouse=True)
def _clear_overrides():  # type: ignore[no-untyped-def]
    yield
    app.dependency_overrides.clear()


def _mock_prefill(
    monkeypatch: pytest.MonkeyPatch, prefill: CompReqPrefill
) -> AsyncMock:
    """Stand in for the Bank read. Mirrors the builder's contract: a chosen position
    outside the candidates is a ``ValueError``; a position-bearing request type
    carries it through; Section A puts it in the based-on list instead."""

    async def fake(  # type: ignore[no-untyped-def]
        session,
        cluster_id,
        request_type=None,
        *,
        jd_in_word_attached=False,
        position_number=None,
    ):
        assert cluster_id == CLUSTER
        if position_number and position_number not in prefill.candidate_positions:
            raise ValueError(f"position {position_number} is not one this role holds")
        update: dict[str, object] = {"jd_in_word_attached": jd_in_word_attached}
        if request_type == "new_based_on_existing":
            update["based_on_positions_a"] = prefill.candidate_positions
        elif request_type is not None:
            update["position_number"] = position_number
        return prefill.model_copy(update=update)

    mock = AsyncMock(side_effect=fake)
    monkeypatch.setattr(library_routes, "prefill_from_role", mock)
    return mock


def _pdf_values(content: bytes) -> dict[str, object]:
    fields = PdfReader(io.BytesIO(content)).get_fields() or {}
    return {name: f.get("/V") for name, f in fields.items()}


# ── the picker page ──────────────────────────────────────────────────────────────


def test_the_page_offers_every_position_and_marks_bank_values_confirm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_prefill(monkeypatch, _prefill())
    resp = _client().get(PAGE)
    assert resp.status_code == 200
    html = resp.text
    for pid in ("00001111", "00005555", "00009999"):
        assert f'name="position_number" value="{pid}"' in html
    assert "Research Coordinator" in html
    assert "School of Computing Science" in html
    assert html.count("confirm") >= 3
    # Every request type on the form is offered, by the shared label table.
    for code, label in REQUEST_TYPE_LABELS.items():
        assert f'name="request_type" value="{code}"' in html
        assert label in html
    assert f'action="{PAGE}"' in html
    assert 'name="csrf_token"' in html


def test_a_possibly_partial_position_list_is_flagged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_prefill(monkeypatch, _prefill(positions_incomplete=True))
    html = _client().get(PAGE).text
    assert "may be incomplete" in html


def test_a_complete_position_list_is_not_flagged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_prefill(monkeypatch, _prefill())
    html = _client().get(PAGE).text
    assert "may be incomplete" not in html


def test_a_role_outside_apsa_apex_says_the_dropdown_has_no_option(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_prefill(monkeypatch, _prefill(employee_group=None))
    html = _client().get(PAGE).text
    assert "not an option on this form" in html


def test_an_unknown_role_is_a_404_page(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        library_routes, "prefill_from_role", AsyncMock(side_effect=LookupError("x"))
    )
    resp = _client().get(PAGE)
    assert resp.status_code == 404
    assert "text/html" in resp.headers["content-type"]


# ── the download ─────────────────────────────────────────────────────────────────


def test_the_download_is_sfu_s_filled_pdf_with_the_chosen_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_prefill(monkeypatch, _prefill())
    resp = _client().post(
        PAGE,
        data={
            "request_type": "reevaluation",
            "position_number": "00005555",
            "jd_in_word_attached": "on",
        },
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert 'attachment; filename="' in resp.headers["content-disposition"]
    assert "research-coordinator" in resp.headers["content-disposition"]
    assert resp.content[:5] == b"%PDF-"
    fmap = load_field_map()
    got = _pdf_values(resp.content)
    pf = fmap.prefill_fields
    assert got[pf["position_number"]] == "00005555"
    assert got[pf["position_title"]] == "Research Coordinator"
    assert got[pf["department"]] == "School of Computing Science"
    assert got[pf["employee_group"]] == "APSA"
    assert got[pf["jd_in_word_attached"]] == fmap.checkbox_on_value


def test_the_download_passes_the_request_type_and_attachment_to_the_bank_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock = _mock_prefill(monkeypatch, _prefill())
    _client().post(PAGE, data={"request_type": "new_based_on_existing"})
    mock.assert_awaited_once()
    args, kwargs = mock.await_args
    assert args[2] == "new_based_on_existing"
    assert kwargs == {"jd_in_word_attached": False, "position_number": None}


def test_no_request_type_fills_only_the_general_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The requester ticks the type on the form; the Bank asserts no section."""
    _mock_prefill(monkeypatch, _prefill())
    resp = _client().post(PAGE, data={})
    assert resp.headers["content-type"] == "application/pdf"
    pf = load_field_map().prefill_fields
    got = _pdf_values(resp.content)
    assert got[pf["position_title"]] == "Research Coordinator"
    assert not got.get(pf["position_number"])
    assert not got.get(pf["based_on_positions_a"])


def test_a_position_the_role_does_not_hold_rerenders_with_the_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_prefill(monkeypatch, _prefill())
    resp = _client().post(
        PAGE, data={"request_type": "editorial", "position_number": "00007777"}
    )
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "00007777" in resp.text
    assert resp.content[:5] != b"%PDF-"


def test_an_unknown_request_type_rerenders_with_the_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock = _mock_prefill(monkeypatch, _prefill())
    resp = _client().post(PAGE, data={"request_type": "promotion"})
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "promotion" in resp.text
    # The page still needs the picker, so the Bank is read, never with the bad type.
    for call in mock.await_args_list:
        assert (call.args + (None,) * 3)[2] is None


def test_a_download_for_an_unknown_role_is_a_404_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        library_routes, "prefill_from_role", AsyncMock(side_effect=LookupError("x"))
    )
    resp = _client().post(PAGE, data={"request_type": "editorial"})
    assert resp.status_code == 404


# ── discoverable: the role page and the Builder link here ─────────────────────────


def test_the_role_page_links_to_the_form(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.jd_bank.library.models import RoleView

    role = RoleView(
        canonical_id=uuid.uuid4(),
        cluster_id=CLUSTER,
        title="Research Coordinator",
        status="draft",
        version=1,
        score=None,
        grade=None,
        rendered_text="...",
        members=(),
        source_count=0,
    )
    monkeypatch.setattr(library_routes, "get_role", AsyncMock(return_value=role))
    html = _client().get(f"/jd-bank/ui/role/{CLUSTER}").text
    assert f'href="{PAGE}"' in html


def test_a_cloned_builder_draft_links_to_the_source_role_s_form() -> None:
    resp = _client().post(
        "/jd-bank/ui/compose/new",
        data={"title": "New Role", "cloned_from_cluster_id": str(CLUSTER)},
    )
    assert f'href="{PAGE}"' in resp.text


def test_a_from_scratch_builder_draft_has_no_form_link() -> None:
    """No role, no positions to pick from: a link to a 404 is worse than none."""
    resp = _client().post("/jd-bank/ui/compose/new", data={"title": "New Role"})
    assert "/comp-requisition" not in resp.text

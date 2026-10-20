"""Track J2 — review fixes (M1, M3, L1, L2).

* **M1** — HR's closed lists were enforced only by the Builder's assembler. A reviewer
  edit (structured form or JSON API) could store ``level_of_independence=['Z', …]``, a
  row with frequency 'Annual' and duration 'forever', or 20 minor functions; those then
  printed on the export, and cloning the role raised an unhandled ValidationError. ONE
  validator over the stored CUPE form block (``check_cupe_form``) now runs in the
  assembler AND the edit paths, and clone refuses bad stored data with a message.
* **M3** — owner ruling 2026-10-19 ("Abilities → Requirements"): cloning a role with
  no CUPE form block sends its ``ability`` lines to Occupational Requirement(s) — where
  the parser read them and where the export prints them (HR-239) — and only knowledge +
  skill to the one Occupational Skills list. A lead phrase is never put in front of a
  line that already reads as a phrase (HR-253).
* **L1** — a 13th major function gets the HR-246 refusal, not pydantic's raw error.
* **L2** — a pre-J2 answer set with more than 40 folded lines still LOADS; the
  assembler refuses it with the limit.
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock

import pytest

from src.api.main import app  # noqa: F401 — the routes import back from it
from src.api.routes import compose_ui
from src.jd_bank.composer.wjq_answers import (
    FunctionAnswer,
    SkillAnswer,
    WJQAnswers,
)
from src.jd_bank.composer.wjq_assemble import assemble_wjq_jd, wjq_answers_from_jd
from src.jd_bank.review import service
from src.jd_core.models.parsed_jd import (
    SFUDuty,
    SFUJobDescription,
    SFUQualification,
    WJQForm,
    WJQRow,
)
from src.jd_core.rules import Rules, get_rules
from src.jd_core.wjq_form_check import CupeFormError, check_cupe_form
from tests.unit.test_compose_ui import (  # noqa: F401 — the two fixtures are autouse
    _clear_overrides,
    _client,
    _default_related_roles_deps,
)


@pytest.fixture(scope="module")
def rules() -> Rules:
    return get_rules()


def _cupe(**form: Any) -> SFUJobDescription:
    return SFUJobDescription(
        title="Clerk",
        employee_group="cupe",
        duties=[
            SFUDuty(action_verb="Files", statement="Files records", frequency="daily")
        ],
        wjq_form=WJQForm(**form),
    )


# ── M1: one validator over the stored block ───────────────────────────────────────


@pytest.mark.parametrize(
    ("form", "entry"),
    [
        ({"level_of_independence": ["Z"]}, "HR-238"),
        ({"level_of_independence": ["A", "B"]}, "HR-238"),
        ({"training_exercised": ["<script>alert(1)</script>"]}, "HR-238"),
        ({"effort": [WJQRow(item="Visual", frequency="Annual")]}, "HR-249"),
        ({"contacts": [WJQRow(item="Students", duration="forever")]}, "HR-248"),
        (
            {
                "minor_functions": [
                    SFUDuty(action_verb="Does", statement=f"Minor {i}")
                    for i in range(20)
                ]
            },
            "HR-246",
        ),
        ({"equivalency_acceptable": False}, "HR-252"),
    ],
)
def test_a_stored_block_outside_hrs_lists_is_refused(
    rules: Rules, form: dict[str, Any], entry: str
) -> None:
    with pytest.raises(CupeFormError, match=entry):
        check_cupe_form(_cupe(**form), rules)


def test_a_major_function_frequency_hr_does_not_offer_is_refused(rules: Rules) -> None:
    jd = _cupe().model_copy(
        update={"duties": [SFUDuty(statement="Audits files", frequency="annual")]}
    )
    with pytest.raises(CupeFormError, match="HR-247"):
        check_cupe_form(jd, rules)


def test_a_valid_block_and_a_role_with_no_block_pass(rules: Rules) -> None:
    check_cupe_form(_cupe(level_of_independence=["B"]), rules)
    check_cupe_form(SFUJobDescription(title="Clerk", employee_group="cupe"), rules)


async def test_the_review_service_refuses_a_bad_block_before_touching_the_bank() -> (
    None
):
    """``service.edit`` validates the content first — a session that explodes on any
    use proves nothing was read or written."""
    content = _cupe(level_of_independence=["Z"]).model_dump(mode="json")
    with pytest.raises(CupeFormError, match="HR-238"):
        await service.edit(
            object(),  # type: ignore[arg-type]
            uuid.uuid4(),
            reviewer_id="r",
            new_content=content,
            reason="edit",
        )


def test_the_json_edit_api_answers_422_with_the_register_id() -> None:
    from fastapi.testclient import TestClient

    from tests.unit.test_review_ui import FakeSession, make_client

    client: TestClient = make_client(FakeSession())
    bad = _cupe(effort=[WJQRow(item="Visual", frequency="Annual")])
    resp = client.post(
        f"/jd-bank/review/{uuid.uuid4()}/edit",
        json={"new_content": bad.model_dump(mode="json"), "reason": "edit"},
    )
    assert resp.status_code == 422, resp.text
    assert "HR-249" in resp.text


def test_the_review_page_refuses_a_bad_block_and_says_why(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.unit.test_review_ui import FakeSession, _packet, make_client, ui

    canonical_id = uuid.uuid4()
    monkeypatch.setattr(
        ui.service, "get_review_packet", AsyncMock(return_value=_packet())
    )
    bad = WJQForm(contacts=[WJQRow(item="Students", duration="forever")])
    resp = make_client(FakeSession()).post(
        f"/jd-bank/ui/review/{canonical_id}/edit",
        data={
            "title": "Clerk",
            "employee_group": "cupe",
            "reason": "edit",
            "wjq_form_json": bad.model_dump_json(),
        },
    )
    assert resp.status_code == 200, resp.status_code
    assert "HR-248" in resp.text


def test_cloning_bad_stored_data_refuses_with_a_message_not_a_crash() -> None:
    bad = _cupe(level_of_independence=["Z"])
    with pytest.raises(CupeFormError, match="HR-238"):
        wjq_answers_from_jd(bad)


def test_the_clone_route_renders_the_refusal_rather_than_500(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _bad(*_: object, **__: object) -> WJQAnswers:
        return wjq_answers_from_jd(_cupe(level_of_independence=["Z"]))

    monkeypatch.setattr(compose_ui, "load_role_clone_answers", _bad)
    resp = _client().get(f"/jd-bank/ui/compose/clone-role/{uuid.uuid4()}")
    assert resp.status_code == 422, resp.status_code
    assert "HR-238" in resp.text


# ── M3: abilities -> Occupational Requirement(s); no ungrammatical helpers ─────────


def _legacy() -> SFUJobDescription:
    return SFUJobDescription(
        title="Clerk",
        employee_group="cupe",
        qualifications=[
            SFUQualification(text="Health terminology", kind="knowledge"),
            SFUQualification(text="Good knowledge of accounting", kind="knowledge"),
            SFUQualification(text="Functional fluency in French", kind="knowledge"),
            SFUQualification(text="Keyboarding", kind="skill", modifier="intermediate"),
            SFUQualification(text="Excellent interpersonal skills", kind="ability"),
            SFUQualification(text="Valid driver's licence", kind="ability"),
        ],
    )


def test_a_parsed_roles_abilities_clone_into_occupational_requirements() -> None:
    answers = wjq_answers_from_jd(_legacy())
    assert answers.occupational_requirements == [
        "Excellent interpersonal skills",
        "Valid driver's licence",
    ]
    assert answers.occupational_skills == [
        SkillAnswer(helper="Knowledge of", text="Health terminology"),
        SkillAnswer(text="Good knowledge of accounting"),
        SkillAnswer(text="Functional fluency in French"),
        SkillAnswer(text="intermediate Keyboarding"),
    ]


def test_the_clone_exports_its_requirements_under_occupational_requirements(
    rules: Rules,
) -> None:
    """Same block as exporting the role directly prints them in (HR-239)."""
    from src.jd_bank.db.models import DocumentFormat
    from src.jd_bank.ingest.extract import extract_text
    from src.jd_export import render_sfu_docx

    jd = assemble_wjq_jd(wjq_answers_from_jd(_legacy()))
    lines = extract_text(render_sfu_docx(jd), DocumentFormat.DOCX).splitlines()
    prompt = lines.index(rules.cupe_form.qualifications_requirements_prompt)
    assert lines.index("Excellent interpersonal skills") > prompt
    assert lines.index("Valid driver's licence") > prompt
    assert lines.index("Knowledge of Health terminology") < prompt


def test_no_lead_phrase_goes_in_front_of_a_line_that_is_already_a_phrase() -> None:
    """ "Ability to | Excellent interpersonal…" was the reviewer's example."""
    for answers in (
        wjq_answers_from_jd(_legacy()),
        WJQAnswers.model_validate(
            {"knowledge": [{"text": "Proficiency with PeopleSoft"}], "title": "x"}
        ),
    ):
        for skill in answers.occupational_skills:
            if skill.helper is not None:
                assert skill.text in {"Health terminology"}, skill


def test_a_legacy_answer_sets_abilities_also_go_to_requirements() -> None:
    answers = WJQAnswers.model_validate(
        {"title": "x", "abilities": ["Work occasional evenings"]}
    )
    assert answers.occupational_requirements == ["Work occasional evenings"]
    assert answers.occupational_skills == []


def test_a_j2_drafts_ability_line_from_a_review_edit_also_clones_to_requirements() -> (
    None
):
    jd = _cupe(occupational_requirements=["Shift work"]).model_copy(
        update={
            "qualifications": [
                SFUQualification(text="Ability to use Excel", kind="skill"),
                SFUQualification(text="Lift 10 kg", kind="ability"),
            ]
        }
    )
    answers = wjq_answers_from_jd(jd)
    assert answers.occupational_requirements == ["Lift 10 kg", "Shift work"]
    assert answers.occupational_skills == [
        SkillAnswer(helper="Ability to", text="use Excel")
    ]


# ── L1 / L2: the limit is stated, never pydantic's raw error, never a crash ───────


def test_a_thirteenth_major_function_gets_the_hr_246_refusal() -> None:
    answers = WJQAnswers(
        title="Clerk",
        major_functions=[
            FunctionAnswer(action_verb="Does", statement=f"Major {i}")
            for i in range(13)
        ],
    )
    with pytest.raises(ValueError, match="HR-246"):
        assemble_wjq_jd(answers)


def test_a_thirteenth_major_function_through_the_page_is_told_not_crashed() -> None:
    from urllib.parse import urlencode

    pairs = [("form", "wjq"), ("title", "Clerk")]
    for i in range(13):
        pairs += [
            ("major_functions_action_verb", "Does"),
            ("major_functions_statement", f"Major function {i}"),
        ]
    resp = _client().post(
        "/jd-bank/ui/compose/new",
        content=urlencode(pairs),
        headers={"content-type": "application/x-www-form-urlencoded"},
    )
    assert resp.status_code == 200
    assert "HR-246" in resp.text
    assert "at most 12 items" not in resp.text
    assert 'value="Major function 12"' in resp.text  # the 13th is still on the page


def test_a_legacy_set_with_more_than_40_lines_loads_and_is_refused_with_the_limit() -> (
    None
):
    legacy = {
        "title": "Clerk",
        "knowledge": [{"text": f"Knowledge line {i}"} for i in range(25)],
        "skills": [{"text": f"Skill line {i}"} for i in range(20)],
    }
    answers = WJQAnswers.model_validate(legacy)  # loads — never a crash
    assert len(answers.occupational_skills) == 45
    with pytest.raises(ValueError, match="at most 40"):
        assemble_wjq_jd(answers)

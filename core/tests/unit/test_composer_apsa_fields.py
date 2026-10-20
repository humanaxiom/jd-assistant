"""Track J, PR J4 — the APSA/APEX/Poly Builder collects what HR's template asks for.

The gap analysis (§2b A1/A2/A6/A14) found four things the template or the Toolkit asks
for that the Builder could not collect, though the JD model already carried most of
them:

* **Position #** (template header) — ``SFUJobDescription.position_number``;
* **"How and why" sub-bullets** under each duty — ``SFUDuty.how_why``;
* **E. Security credentials (if applicable)** — the criminal-record-check sentence,
  from ``apsa_form.yaml`` (HR-257), as a yes/no; and a cloned role's security
  qualifications were silently DROPPED (``jd_to_answers`` had no field for them);
* **the supervisor's title and position #** (Toolkit Part 11.1; the JAQ).

Each is pinned three ways: it assembles into the JD, it survives a clone, and it gets
from the Builder's own HTML form all the way into the exported ``.docx``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from io import BytesIO
from urllib.parse import urlencode

import pytest
from docx import Document
from fastapi.testclient import TestClient

from src.api.main import app, get_session
from src.api.routes import compose
from src.jd_bank.composer import ComposerAnswers, assemble_jd, jd_to_answers
from src.jd_bank.db.models import DocumentFormat
from src.jd_bank.ingest.extract import extract_text
from src.jd_core.models.parsed_jd import SFUDuty, SFUJobDescription, SFUQualification
from src.jd_core.parser.segmenter import parse_jd
from src.jd_core.rules import get_rules

_SENTENCE = get_rules().apsa_form.security_check_sentence


def _answers(**update: object) -> ComposerAnswers:
    """Built through validation (not ``model_copy``) so a dict duty becomes a row."""
    base: dict[str, object] = dict(
        title="Academic Programs Manager",
        position_number="00012345",
        supervisor_title="Director, Academic Operations",
        supervisor_position_number="00054321",
        employee_group="apsa",
        position_summary="Provides support for the School's academic programs.",
        duties=[
            {
                "action_verb": "Manages",
                "statement": "Manages the delivery of all academic programs by:",
                "allocation": 60,
                "how_why": [
                    "Representing the department on committees.",
                    "Developing work plans.",
                ],
            },
            {
                "action_verb": "Leads",
                "statement": "Leads staffing processes",
                "allocation": 40,
            },
        ],
        criminal_record_check=True,
    )
    return ComposerAnswers.model_validate({**base, **update})


# ── assemble ─────────────────────────────────────────────────────────────────────


def test_position_and_supervisor_fields_assemble_into_the_jd() -> None:
    jd = assemble_jd(_answers())
    assert jd.position_number == "00012345"
    assert jd.supervisor_title == "Director, Academic Operations"
    assert jd.supervisor_position_number == "00054321"


def test_how_why_assembles_onto_its_duty() -> None:
    jd = assemble_jd(_answers())
    assert jd.duties[0].how_why == [
        "Representing the department on committees.",
        "Developing work plans.",
    ]
    assert jd.duties[1].how_why == []
    # The allocation still renders into the statement, where the gate reads it.
    assert jd.duties[0].statement.endswith("(60%)")


def test_blank_how_why_lines_are_dropped() -> None:
    answers = _answers(duties=[{"statement": "Leads staffing", "how_why": ["", "  "]}])
    assert assemble_jd(answers).duties[0].how_why == []


def test_the_criminal_record_check_adds_the_sentence_from_the_rulebook() -> None:
    """A yes/no, never typed: the sentence is HR's (``apsa_form.yaml``, HR-257)."""
    jd = assemble_jd(_answers())
    security = [q for q in jd.qualifications if q.kind == "security"]
    assert [q.text for q in security] == [_SENTENCE]


def test_no_criminal_record_check_adds_no_security_qualification() -> None:
    jd = assemble_jd(_answers(criminal_record_check=False))
    assert not [q for q in jd.qualifications if q.kind == "security"]


def test_security_credentials_come_last_in_the_qualifications() -> None:
    """Toolkit order: A education … D abilities, then E security credentials."""
    jd = assemble_jd(
        _answers(abilities=["Ability to work cooperatively"], security=["Clearance"])
    )
    kinds = [q.kind for q in jd.qualifications]
    assert kinds == ["ability", "security", "security"]
    assert jd.qualifications[1].text == _SENTENCE


# ── clone ────────────────────────────────────────────────────────────────────────


def _source_jd() -> SFUJobDescription:
    return SFUJobDescription(
        title="Academic Programs Manager",
        position_number="00012345",
        supervisor_title="Director, Academic Operations",
        supervisor_position_number="00054321",
        employee_group="apsa",
        duties=[
            SFUDuty(
                action_verb="Manages",
                statement="Manages the programs by:",
                how_why=["Representing the department."],
            )
        ],
        qualifications=[
            SFUQualification(text="Ability to lead", kind="ability"),
            SFUQualification(text=_SENTENCE, kind="security"),
            SFUQualification(text="Enhanced Reliability clearance", kind="security"),
        ],
    )


def test_a_clone_keeps_its_security_credentials() -> None:
    """Pre-J4, ``jd_to_answers`` dropped every ``security`` qualification. The
    rulebook's own sentence comes back as the yes/no; any other security line is kept
    verbatim — nothing is dropped and nothing is doubled."""
    answers = jd_to_answers(_source_jd())
    assert answers.criminal_record_check is True
    assert answers.security == ["Enhanced Reliability clearance"]
    rebuilt = assemble_jd(answers)
    assert [q.text for q in rebuilt.qualifications if q.kind == "security"] == [
        _SENTENCE,
        "Enhanced Reliability clearance",
    ]


def test_the_sentence_is_recognised_whatever_its_case_and_spacing() -> None:
    """The archive line-wraps and re-cases; the parser collapses whitespace."""
    jd = _source_jd().model_copy(
        update={
            "qualifications": [
                SFUQualification(
                    text="  " + _SENTENCE.upper().replace(" ", "  ") + ". ",
                    kind="security",
                )
            ]
        }
    )
    answers = jd_to_answers(jd)
    assert answers.criminal_record_check is True
    assert answers.security == []


def test_a_clone_keeps_how_why_position_and_supervisor() -> None:
    answers = jd_to_answers(_source_jd())
    assert answers.duties[0].how_why == ["Representing the department."]
    assert answers.position_number == "00012345"
    assert answers.supervisor_title == "Director, Academic Operations"
    assert answers.supervisor_position_number == "00054321"
    rebuilt = assemble_jd(answers)
    assert rebuilt.duties[0].how_why == ["Representing the department."]


def test_answers_written_before_j4_still_load() -> None:
    """``answers_json`` persisted on existing drafts has none of the new keys and the
    contract is ``extra="forbid"`` — it must still validate, every new field defaulted.
    """
    old = ComposerAnswers.model_validate_json(
        '{"title": "Old Draft", "duties": [{"action_verb": "Leads",'
        ' "statement": "Leads staff", "allocation": 50}]}'
    )
    assert old.duties[0].how_why == []
    assert old.criminal_record_check is False
    assert old.security == []
    assert old.position_number is None


# ── the Builder's own form, end to end ──────────────────────────────────────────


@pytest.fixture(autouse=True)
def _no_live_deps() -> Iterator[None]:
    """The check step also runs the near-duplicate guard; stub its I/O (as
    ``test_compose_ui`` does) — nothing here touches a DB, Neo4j or the GPU."""

    class _FakeClose:
        async def close(self) -> None:
            return None

    async def override_session() -> AsyncIterator[object]:
        yield object()

    app.dependency_overrides[get_session] = override_session
    for dep in (
        compose.get_embed_client,
        compose.get_neo4j_driver,
        compose.get_optional_embed_client,
        compose.get_optional_neo4j_driver,
    ):
        app.dependency_overrides[dep] = lambda: _FakeClose()
    yield
    app.dependency_overrides.clear()


def _post(client: TestClient, url: str, pairs: list[tuple[str, str]]):  # type: ignore[no-untyped-def]
    return client.post(
        url,
        content=urlencode(pairs),
        headers={"content-type": "application/x-www-form-urlencoded"},
    )


def test_the_builder_page_offers_the_new_fields() -> None:
    html = TestClient(app).get("/jd-bank/ui/compose/new").text
    for name in (
        'name="position_number"',
        'name="supervisor_title"',
        'name="supervisor_position_number"',
        'name="criminal_record_check"',
        'name="security"',
        'name="duties_how_why"',
    ):
        assert name in html, name
    # The WJQ form shares the duty-row widget; how/why is a JDFN field and must not
    # appear on a form whose contract cannot carry it.
    wjq = TestClient(app).get("/jd-bank/ui/compose/new?form=wjq").text
    assert "_how_why" not in wjq


def test_the_criminal_record_check_box_is_not_ticked_by_default() -> None:
    """The template rendered EVERY checkbox from the boilerplate default, so a second
    checkbox would have arrived pre-ticked — asserting a security requirement the
    author never chose."""
    html = TestClient(app).get("/jd-bank/ui/compose/new").text
    tag = html[html.index('name="criminal_record_check"') :].split(">", 1)[0]
    assert "checked" not in tag


def test_a_checked_criminal_record_check_survives_a_check_round() -> None:
    resp = _post(
        TestClient(app),
        "/jd-bank/ui/compose/new",
        [("title", "Role"), ("criminal_record_check", "on")],
    )
    tag = resp.text[resp.text.index('name="criminal_record_check"') :].split(">", 1)[0]
    assert "checked" in tag


def test_builder_fields_reach_the_exported_docx() -> None:
    """Form POST -> check -> the page's own answers_json -> export -> the .docx, read
    back by the Bank's ingest path: position #, how/why, security, supervisor."""
    import html as html_lib
    import re

    client = TestClient(app)
    check = _post(
        client,
        "/jd-bank/ui/compose/new",
        [
            ("title", "Academic Programs Manager"),
            ("employee_group", "apsa"),
            ("position_number", "00012345"),
            ("supervisor_title", "Director, Academic Operations"),
            ("supervisor_position_number", "00054321"),
            ("duties_verb", "Manages"),
            ("duties_statement", "Manages the delivery of programs by:"),
            ("duties_allocation", "60"),
            ("duties_how_why", "Representing the department.\nDeveloping work plans."),
            ("duties_verb", "Leads"),
            ("duties_statement", "Leads staffing processes"),
            ("duties_allocation", "40"),
            ("duties_how_why", ""),
            ("criminal_record_check", "on"),
            ("include_sfu_boilerplate", "on"),
        ],
    )
    assert check.status_code == 200
    match = re.search(r'name="answers_json" value="([^"]*)"', check.text)
    assert match is not None
    answers_json = html_lib.unescape(match.group(1))

    export = _post(
        client,
        "/jd-bank/ui/compose/export",
        [("answers_json", answers_json), ("form", "jdfn")],
    )
    assert export.status_code == 200 and export.content[:2] == b"PK"
    body = extract_text(export.content, DocumentFormat.DOCX)
    back = parse_jd(body).jd
    assert back.position_number == "00012345"
    assert len(back.duties) == 2
    assert "Representing the department" in back.duties[0].statement
    assert "Director, Academic Operations" in body
    assert "00054321" in body
    assert _SENTENCE in body
    doc = Document(BytesIO(export.content))
    assert any(p.text == "Developing work plans." for p in doc.paragraphs)
